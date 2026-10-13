"""Offline tests: runs run_bench.py against an in-process mock of the OpenRouter API.

  uv run python -m unittest discover tests
"""
import csv, glob, io, json, os, ssl, sys, tempfile, threading, unittest, urllib.error
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
        rows, summary = self.run_bench("--texts", "S1_*", "--runs", "1", "--models", models)

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
            result = run_bench.call("mock/model", "prompt", 1, "test", 100)
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


if __name__ == "__main__":
    unittest.main()
