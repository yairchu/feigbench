"""Offline tests: runs run_bench.py against an in-process mock of the OpenRouter API.

  uv run python -m unittest discover tests
"""
import csv, glob, io, json, os, ssl, subprocess, sys, tempfile, threading, unittest, urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_bench  # noqa: E402

CLEAN = {"context": [{"guess": "Israel-Gaza war 2023", "confidence": 80}],
         "speakers": [{"name": "Moshe Feiglin", "confidence": 60, "clues_for": "", "clues_against": ""}],
         "most_revealing_clue": "Oslo"}

# Prose around a fenced block, string confidences, braces inside strings, and lists not sorted by confidence.
MESSY = """Sure! Here is my answer {as requested}:
```json
{"context": [{"guess": "Russia-Ukraine", "confidence": "10%"}, {"guess": "Israel / Gaza", "confidence": "~70%"}],
 "speakers": [{"name": "Bezalel Smotrich", "confidence": "20%", "clues_for": "uses {braces}", "clues_against": ""},
              {"name": "Moshe Feiglin", "confidence": "35%", "clues_for": "", "clues_against": ""}],
 "most_revealing_clue": "the Treaty"}
```"""

# model id -> list of (status, body) replies, served in order; the last one repeats
SCRIPT = {
    "mock/clean": [(200, {"choices": [{"message": {"content": json.dumps(CLEAN)}, "finish_reason": "stop"}]})],
    "mock/messy": [(200, {"choices": [{"message": {"content": MESSY}, "finish_reason": "stop"}]})],
    "mock/reasoning-truncated": [(200, {"choices": [{"message": {"content": None}, "finish_reason": "length"}]})],
    "mock/flaky": [(503, {"error": "overloaded"}),
                   (200, {"choices": [{"message": {"content": json.dumps(CLEAN)}, "finish_reason": "stop"}]})],
    "mock/bad-request": [(400, {"error": {"message": "unknown model"}})],
}


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class MockOpenRouter:
    """Stands in for urllib.request.urlopen, replying per SCRIPT."""

    def __init__(self):
        self.calls = {}
        self.lock = threading.Lock()

    def __call__(self, req, data=None, timeout=None, context=None):
        model = json.loads(data)["model"]
        with self.lock:
            n = self.calls[model] = self.calls.get(model, 0) + 1
        status, reply = SCRIPT[model][min(n, len(SCRIPT[model])) - 1]
        body = io.BytesIO(json.dumps(reply).encode())
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "mock error", {}, body)
        return body  # BytesIO is a context manager with .read(), like the real response


class BenchTest(unittest.TestCase):
    def setUp(self):
        self.api = MockOpenRouter()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_bench(self, *argv, targets=None):
        targets_file = run_bench.TARGETS_FILE
        if targets:
            targets_file = os.path.join(self.tmp.name, "targets.json")
            with open(targets_file, "w") as f:
                json.dump(targets, f)
        with mock.patch.object(run_bench.urllib.request, "urlopen", self.api), \
             mock.patch.object(run_bench, "TARGETS_FILE", targets_file), \
             mock.patch.object(run_bench.time, "sleep"), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), \
             mock.patch.object(sys, "argv", ["run_bench.py", "--results-dir", self.tmp.name, *argv]), \
             mock.patch("sys.stdout", new=io.StringIO()):
            run_bench.main()
        (run_dir,) = glob.glob(os.path.join(self.tmp.name, "2*"))
        rows, summary = (read_csv(os.path.join(run_dir, f)) for f in ("scored.csv", "summary.csv"))
        return {r["model"]: r for r in rows}, {s["model"]: s for s in summary}

    def test_end_to_end(self):
        models = ",".join(SCRIPT)
        rows, summary = self.run_bench("--texts", "S1_burned_cities", "--runs", "1", "--models", models)

        r = rows["mock/clean"]
        self.assertEqual((r["target_rank"], r["target_conf"], r["context_match"]), ("1", "60.0", "True"))

        r = rows["mock/messy"]
        self.assertEqual(r["parsed"], "True")
        self.assertEqual((r["target_rank"], r["target_conf"]), ("1", "35.0"))  # re-sorted above Smotrich's 20%
        self.assertEqual((r["top_context"], r["context_match"]), ("Israel / Gaza", "True"))

        r = rows["mock/reasoning-truncated"]
        self.assertEqual(r["parsed"], "False")
        self.assertIn("truncated", r["error"])

        self.assertEqual(rows["mock/flaky"]["target_rank"], "1")
        self.assertEqual(self.api.calls["mock/flaky"], 2)

        self.assertIn("HTTP 400", rows["mock/bad-request"]["error"])
        self.assertEqual(self.api.calls["mock/bad-request"], 1)  # not retried
        self.assertEqual(summary["mock/bad-request"]["errors"], "1")

    def test_per_text_target(self):
        targets = {"S1_*": {"speaker": ["smotrich"], "context": ["ukrain"]},
                   "default": {"speaker": ["feiglin"], "context": ["israel"]}}
        rec = {"model": "m", "run": 1, "content": MESSY, "finish_reason": "stop"}
        s1 = run_bench.score({**rec, "text": "S1_burned_cities"}, targets)
        s2 = run_bench.score({**rec, "text": "S2_expulsion"}, targets)
        self.assertEqual((s1["target_rank"], s1["context_match"]), (2, False))
        self.assertEqual((s2["target_rank"], s2["context_match"]), (1, True))

    def test_default_dataset_and_control_report(self):
        self.run_bench("--models", "mock/clean", "--runs", "1")
        directory, = Path(self.tmp.name).glob("2*")
        saved = json.loads((directory / "snapshot.json").read_text())
        self.assertEqual(len(saved["texts"]), 6)
        self.assertTrue(all(t.startswith("S") and t.endswith("_paraphrased") for t in saved["texts"]))
        self.assertEqual(len(read_csv(directory / "control_summary.csv")), 1)
        point, = read_csv(directory / "model_summary.csv")
        self.assertEqual(point["texts"], "5")
        self.assertEqual(saved["scoring_version"], run_bench.SCORING_VERSION)
        self.assertEqual(saved["prompt"], json.loads((directory / "config.json").read_text())["prompt"])
        self.assertTrue((directory / "code" / "run_bench.py").exists())


class CertificateTest(unittest.TestCase):
    def setUp(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError(1, "unable to get local issuer certificate"))
        self.urlopen = mock.Mock(side_effect=error)
        patch = mock.patch.object(run_bench.urllib.request, "urlopen", self.urlopen)
        patch.start()
        self.addCleanup(patch.stop)

    def test_list_models_reports_setup_command(self):
        with mock.patch.object(sys, "platform", "darwin"), \
             mock.patch.object(sys, "argv", ["run_bench.py", "--list-models", "openai"]):
            with self.assertRaises(SystemExit) as cm:
                run_bench.main()
        self.assertIn("uv sync", str(cm.exception))
        self.assertIn("SSL_CERT_FILE", str(cm.exception))

    def test_certificate_failure_is_not_retried(self):
        with mock.patch.object(run_bench.time, "sleep") as sleep:
            result = run_bench.call("mock/model", "prompt", "test", 100)
        self.assertIn("TLS certificate verification failed", result["error"])
        self.urlopen.assert_called_once()
        sleep.assert_not_called()

    def test_other_network_errors_are_preserved(self):
        error = urllib.error.URLError("connection refused")
        self.urlopen.side_effect = error
        with self.assertRaises(urllib.error.URLError) as cm:
            run_bench.http("GET", "https://example.com")
        self.assertIs(cm.exception, error)

    def test_bundled_certificates_keep_verification_enabled(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            context = run_bench.tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)

    def test_custom_certificate_configuration_is_respected(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/custom/ca.pem"}), \
             mock.patch.object(run_bench.ssl, "create_default_context") as create:
            context = run_bench.tls_context()
        self.assertIs(context, create.return_value)
        context.load_verify_locations.assert_not_called()


class ParseTest(unittest.TestCase):
    def test_conf(self):
        for v, want in [(35, 35.0), ("35", 35.0), ("35%", 35.0), ("~12.5 %", 12.5), (None, None), ("high", None), (True, None)]:
            self.assertEqual(run_bench.conf(v), want, v)

    def test_parse_skips_non_answer_objects(self):
        self.assertEqual(run_bench.parse_answer('{"note": 1} then {"speakers": []}'), {"speakers": []})
        self.assertIsNone(run_bench.parse_answer("no json here"))


class SoftScoreTest(unittest.TestCase):
    def score(self, answer):
        return run_bench.score({"text": "A_full_masked", "model": "m", "run": 1,
                                "content": json.dumps(answer), "usage": {"cost": .002}},
                               run_bench.load_targets())

    def test_sums_matching_contexts_and_uses_non_top1_speaker(self):
        row = self.score({"speakers": [{"name": "Someone else", "confidence": 60},
                                       {"name": "Moshe Feiglin", "confidence": 40}],
                          "context": [{"guess": "Israel 2023", "confidence": 50},
                                      {"guess": "Gaza 2014", "confidence": 30},
                                      {"guess": "Ukraine", "confidence": 20}]})
        self.assertEqual((row["speaker_conf"], row["context_conf"], row["soft_score"]), (40, 80, 60))
        self.assertEqual(row["target_rank"], 2)
        self.assertEqual(row["cost_usd"], .002)

    def test_caps_confidence_and_missing_matches_are_zero(self):
        row = self.score({"context": [{"guess": "Israel", "confidence": 90},
                                      {"guess": "Gaza", "confidence": 80}]})
        self.assertEqual((row["speaker_conf"], row["context_conf"], row["soft_score"]), (0, 100, 50))
        self.assertEqual(self.score({"speakers": []})["soft_score"], 0)
        self.assertEqual(run_bench.probability(float("nan")), 0)
        self.assertEqual(run_bench.probability(-10), 0)

    def test_normalizes_entire_lists_before_matching(self):
        row = self.score({"speakers": [{"name": "Moshe Feiglin", "confidence": 75},
                                       {"name": "Someone else", "confidence": 50}],
                          "context": [{"guess": "Israel", "confidence": 60},
                                      {"guess": "Gaza", "confidence": 40},
                                      {"guess": "Ukraine", "confidence": 100}]})
        self.assertEqual((row["speaker_conf_total"], row["context_conf_total"]), (125, 200))
        self.assertEqual((row["target_conf"], row["speaker_conf"], row["context_conf"], row["soft_score"]), (60, 60, 50, 55))
        self.assertEqual(row["target_rank"], 1)
        self.assertEqual(self.score(CLEAN)["soft_score"], 70)  # partial lists are never scaled up

    def test_aggregation_weights_texts_equally_and_excludes_control(self):
        from plot_bench import model_summary
        row = self.score(CLEAN)
        rows = [row, row, {**row, "text": "B_no_biography", "soft_score": 0, "cost_usd": .004},
                {**row, "text": "S6_leadership_only_control", "soft_score": 100, "cost_usd": 1},
                {**row, "text": "S6_leadership_only_control_paraphrased", "soft_score": 100, "cost_usd": 1}]
        point, = model_summary(rows)
        self.assertEqual((point["texts"], point["calls"], point["soft_score"]), (2, 3, 35))
        self.assertEqual(point["mean_cost_usd"], .003)
        point, = model_summary([{**row, "cost_usd": None}])
        self.assertIsNone(point["mean_cost_usd"])


class SnapshotTest(unittest.TestCase):
    def test_saved_targets_and_code_survive_workspace_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            targets = {"default": {"speaker": ["someone else"], "context": ["ukraine"]}}
            run_bench.snapshot_run(tmp, {"S1_test": "original input"}, "original prompt", targets)
            record = dict(text="S1_test", model="m", run=1, content=json.dumps(CLEAN))
            (directory / "raw.jsonl").write_text(json.dumps(record) + "\n")
            with mock.patch.object(run_bench, "load_targets", side_effect=AssertionError("workspace targets used")), \
                 mock.patch("sys.stdout", new=io.StringIO()):
                run_bench.summarize(tmp)
            row, = read_csv(directory / "scored.csv")
            self.assertEqual(float(row["soft_score"]), 0)
            self.assertEqual(json.loads((directory / "scoring.json").read_text())["targets_source"], "snapshot.json")
            # The saved scorer works outside the repository and uses saved targets.
            subprocess.run([sys.executable, str(directory / "code" / "run_bench.py"), "--summarize", tmp],
                           cwd=tmp, check=True, capture_output=True, text=True)
            row, = read_csv(directory / "scored.csv")
            self.assertEqual(float(row["soft_score"]), 0)
            snapshot = json.loads((directory / "snapshot.json").read_text())
            snapshot["scoring_version"] = "future-version"
            (directory / "snapshot.json").write_text(json.dumps(snapshot))
            with self.assertRaises(ValueError):
                run_bench.run_targets(tmp)

    def test_legacy_run_does_not_fabricate_an_input_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(run_bench, "load_targets", return_value={"saved": False}):
            targets, source = run_bench.run_targets(tmp)
            self.assertEqual(targets, {"saved": False})
            self.assertIn("legacy", source)
            self.assertFalse((Path(tmp) / "snapshot.json").exists())


class EffortTest(unittest.TestCase):
    def test_request_body_and_default(self):
        reply = {"choices": [{"message": {"content": json.dumps(CLEAN)}, "finish_reason": "stop"}]}
        with mock.patch.object(run_bench, "http", return_value=reply) as http:
            run_bench.call("m", "prompt", "key", 16000, "low")
            body = http.call_args.args[2]
            self.assertEqual(body["reasoning"], {"effort": "low"})
            self.assertTrue(body["provider"]["require_parameters"])
            self.assertNotIn("temperature", body)
            run_bench.call("m", "prompt", "key", 16000)
            self.assertNotIn("reasoning", http.call_args.args[2])
            self.assertNotIn("temperature", http.call_args.args[2])

    def test_preflight_support(self):
        catalog = {"data": [{"id": "m", "reasoning": {
            "supported_efforts": ["low", "medium", "high"], "mandatory": True}},
            {"id": "no-reasoning"}]}
        with mock.patch.object(run_bench, "http", return_value=catalog) as http:
            run_bench.validate_efforts(["m"], ["default"])
            http.assert_not_called()
            run_bench.validate_efforts(["m"], ["low", "medium", "high"])
            for model, effort in [("m", "none"), ("m", "max"), ("no-reasoning", "low"), ("missing", "low")]:
                with self.assertRaises(ValueError):
                    run_bench.validate_efforts([model], [effort])

    def test_sweep_records_and_summaries_remain_separate(self):
        reply = {"content": json.dumps(CLEAN), "usage": {"cost": .002}, "finish_reason": "stop"}
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(run_bench, "call", return_value=reply) as call, \
             mock.patch.object(run_bench, "validate_efforts", return_value={}), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), \
             mock.patch.object(sys, "argv", ["run_bench.py", "--models", "m", "--texts", "S1_burned_cities",
                                             "--runs", "1", "--efforts", "low", "mid", "high", "low",
                                             "--results-dir", directory]), \
             mock.patch("sys.stdout", new=io.StringIO()), \
             mock.patch("plot_bench.plot_results"):
            run_bench.main()
            run_dir, = glob.glob(os.path.join(directory, "2*"))
            self.assertEqual(call.call_count, 3)
            self.assertTrue(all(c.args[2] == 'test' for c in call.call_args_list))
            self.assertEqual({c.args[-1] for c in call.call_args_list}, {"low", "medium", "high"})
            for name in ("scored.csv", "summary.csv"):
                self.assertEqual({r["effort"] for r in read_csv(os.path.join(run_dir, name))}, {"low", "medium", "high"})
            from plot_bench import model_summary
            with open(os.path.join(run_dir, "raw.jsonl")) as f:
                records = [json.loads(line) for line in f]
            points = model_summary([run_bench.score(r, run_bench.load_targets()) for r in records])
            self.assertEqual(len(points), 3)
            self.assertTrue(all(p["calls"] == 1 for p in points))

    def test_records_provider_default_sampling(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(run_bench, "http", return_value={"choices": [{"message": {"content": json.dumps(CLEAN)}}]}) as http, \
             mock.patch.object(run_bench, "validate_efforts", return_value={"m": {"supported_parameters": ["reasoning", "max_tokens", "temperature"]}}), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), \
             mock.patch.object(sys, "argv", ["run_bench.py", "--models", "m", "--texts", "S1_burned_cities", "--runs", "1",
                                             "--efforts", "low", "--results-dir", directory]), \
             mock.patch("sys.stdout", new=io.StringIO()), mock.patch("plot_bench.plot_results"):
            run_bench.main()
            self.assertNotIn('temperature', http.call_args.args[2])
            run_dir, = glob.glob(os.path.join(directory, "2*"))
            with open(os.path.join(run_dir, "config.json")) as f:
                config = json.load(f)
            self.assertNotIn('temperature', config)
            self.assertNotIn('effective_temperatures', config)
            self.assertEqual(config['sampling'], 'provider defaults (temperature omitted)')


if __name__ == "__main__":
    unittest.main()
