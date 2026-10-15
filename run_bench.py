#!/usr/bin/env python3
"""feigbench: can LLMs identify the speaker of a disguised interview?

Runs every text x model x run through OpenRouter, saves raw answers and a
scored CSV. Run with uv to install dependencies automatically.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  uv run run_bench.py --list-models gpt claude gemini   # find model ids
  uv run run_bench.py --dry-run                        # show the plan, no API calls
  uv run run_bench.py --runs 3                         # rewritten excerpts + control
  uv run run_bench.py --texts 'S*' --models openai/gpt-4o --runs 5
  uv run run_bench.py --summarize results/<run_dir>     # re-score an existing run

The expected speaker and context for each text are in targets.json.
Set OPENROUTER_BASE_URL to use another OpenAI-compatible endpoint.
"""
import argparse, csv, datetime, fcntl, fnmatch, glob, hashlib, json, math, os, re, shutil, ssl, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import certifi

ROOT = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
TARGETS_FILE = os.path.join(ROOT, "targets.json")
EFFORTS = ("default", "none", "minimal", "low", "medium", "high", "xhigh", "max")
SCORING_VERSION = "soft-confidence-v2"
DEFAULT_TEXTS = "S*_paraphrased"
CONTROL = "S6_leadership_only_control"


def is_control(text):
    return text.removesuffix("_paraphrased") == CONTROL


def job_key(record):
    return record['text'], record['model'], record.get('effort', 'default'), record['run']


def read_attempts(run_dir):
    path = Path(run_dir) / 'raw.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def effective_records(attempts):
    """One result per job: keep the first model response, otherwise the latest API error."""
    selected = {}
    for record in attempts:
        key = job_key(record)
        if key not in selected or selected[key].get('error'):
            selected[key] = record
    return list(selected.values())


def execute_jobs(run_dir, jobs, texts, template, key, max_tokens, concurrency):
    """Bound in-flight requests; stop submitting on credit/authentication failures."""
    remaining = iter(jobs)
    stopped = False
    done = 0
    with open(Path(run_dir) / 'raw.jsonl', 'a') as out, ThreadPoolExecutor(concurrency) as executor:
        pending = {}

        def fill():
            while not stopped and len(pending) < concurrency:
                job = next(remaining, None)
                if job is None:
                    break
                text, model, effort, run = job
                pending[executor.submit(call, model, template.replace('{{TEXT}}', texts[text]),
                                        key, max_tokens, effort)] = job

        fill()
        while pending:
            try:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            except KeyboardInterrupt:
                stopped = True
                print('\nStopping new calls; saving in-flight replies before exiting...', flush=True)
                continue
            for future in completed:
                text, model, effort, run = pending.pop(future)
                record = dict(text=text, model=model, effort=effort, run=run, **future.result())
                out.write(json.dumps(record, ensure_ascii=False) + '\n')
                out.flush()
                done += 1
                error = record.get('error', '')
                status = 'ERROR ' + error[:80] if error else record.get('finish_reason', 'ok')
                print(f'[{done}/{len(jobs)}] {text} | {model} | effort {effort} | run {run}: {status}', flush=True)
                if record.get('http_status') in (401, 402) or error.startswith(('HTTP 401:', 'HTTP 402:')):
                    stopped = True
                    print('Credit/key limit or authentication failure: no further calls will be submitted.', flush=True)
            fill()
    return stopped


def resume_run(run_dir, dry_run=False, concurrency=4):
    directory = Path(run_dir)
    config = json.loads((directory / 'config.json').read_text())
    snapshot = json.loads((directory / 'snapshot.json').read_text())
    run_targets(directory)  # Check scorer compatibility; never use current workspace inputs.
    if snapshot.get('api_base_url', API) != API:
        raise ValueError('OPENROUTER_BASE_URL differs from the saved run.')
    if config.get('sampling') != 'provider defaults (temperature omitted)':
        raise ValueError('Resume currently supports runs made with provider-default sampling only.')
    if snapshot['prompt'] != config['prompt'] or set(snapshot['texts']) != set(config['texts']):
        raise ValueError('Saved configuration and input snapshot disagree.')
    # New processes cooperate on this lock. Older runners must be stopped before resuming.
    with (directory / '.runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another runner is already writing to this run.') from None
        attempts = read_attempts(directory)
        completed = {job_key(r) for r in attempts if not r.get('error')}
        planned = [(t, m, e, r) for t in config['texts'] for m in config['models']
                   for e in config.get('efforts', ['default']) for r in range(1, config['runs'] + 1)]
        jobs = [job for job in planned if job not in completed]
        print(f'Resume {directory}: {len(planned) - len(jobs)} completed; {len(jobs)} missing or API-failed calls remain.')
        if dry_run:
            return
        if jobs:
            key = os.environ.get('OPENROUTER_API_KEY')
            if not key:
                raise ValueError('Set OPENROUTER_API_KEY first.')
            resumed = directory / 'resumptions' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            resumed.mkdir(parents=True)
            snapshot_run(resumed, snapshot['texts'], snapshot['prompt'], snapshot['targets'])
            shutil.copyfile(directory / 'config.json', resumed / 'config.json')
            (directory / 'resumptions' / 'latest.json').write_text(json.dumps(
                dict(code_path=str(resumed.relative_to(directory) / 'code'), pending_calls=len(jobs)), indent=2) + '\n')
            execute_jobs(directory, jobs, snapshot['texts'], snapshot['prompt'], key, config['max_tokens'], concurrency)
        summarize(directory)


def snapshot_run(run_dir, texts, prompt, targets):
    """Save exact inputs and runnable scoring sources, without environment secrets."""
    directory = Path(run_dir)
    sources = directory / "code"
    sources.mkdir()
    hashes = {}
    for name in ("run_bench.py", "plot_bench.py", "speaker_report.py", "speaker_origins.json", "pyproject.toml", "uv.lock", "README.md"):
        source = Path(ROOT) / name
        shutil.copyfile(source, sources / name)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "diff", "HEAD", "--", *hashes], cwd=ROOT, stderr=subprocess.DEVNULL))
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    snapshot = dict(texts=texts, prompt=prompt, targets=targets, scoring_version=SCORING_VERSION,
                    controls=[t for t in texts if is_control(t)], code_commit=commit,
                    code_dirty=dirty, source_sha256=hashes, python_version=sys.version,
                    api_base_url=API)
    (directory / "snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")


def run_targets(run_dir):
    snapshot = Path(run_dir) / "snapshot.json"
    if snapshot.exists():
        saved = json.loads(snapshot.read_text())
        if saved["scoring_version"] != SCORING_VERSION:
            raise ValueError(f"Run uses {saved['scoring_version']}; use its saved code/run_bench.py to summarize it.")
        return saved["targets"], "snapshot.json"
    return load_targets(), "current targets.json (legacy run; original inputs were not saved)"


def tls_context():
    context = ssl.create_default_context()
    if not (os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")):
        context.load_verify_locations(cafile=certifi.where())
    return context


TLS_CONTEXT = tls_context()


class CertificateError(RuntimeError):
    """A certificate setup failure that retrying cannot fix."""


def http(method, url, body=None, key=None, timeout=300):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Title", "feigbench")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout, context=TLS_CONTEXT) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
        hint = "Run uv sync --upgrade-package certifi to update trusted certificates, or set SSL_CERT_FILE to your trusted CA bundle."
        raise CertificateError(f"TLS certificate verification failed. {hint}") from e


def list_models(filters):
    models = http("GET", f"{API}/models")["data"]
    for m in sorted(models, key=lambda m: m["id"]):
        if not filters or any(f.lower() in m["id"].lower() for f in filters):
            print(m["id"])


def list_efforts(filters):
    for m in sorted(http("GET", f"{API}/models")["data"], key=lambda m: m["id"]):
        if filters and not any(f.lower() in m["id"].lower() for f in filters):
            continue
        reasoning = m.get("reasoning") or {}
        levels = reasoning.get("supported_efforts", "not advertised")
        print(f"{m['id']}: {levels}; default={reasoning.get('default_effort', 'unspecified')}")


def validate_efforts(models, efforts):
    """Reject known unsupported requests before starting paid calls."""
    explicit = [e for e in efforts if e != "default"]
    if not explicit:
        return {}
    available = {m["id"]: m for m in http("GET", f"{API}/models")["data"]}
    metadata = {}
    for model in models:
        if model not in available:
            raise ValueError(f"Model {model} is absent from the model catalog.")
        m = available[model]
        reasoning = m.get("reasoning") or {}
        if not reasoning and "reasoning" not in (m.get("supported_parameters") or []):
            raise ValueError(f"{model} does not advertise reasoning support. Use --efforts default.")
        if reasoning and "supported_efforts" not in reasoning:
            raise ValueError(f"{model} does not advertise effort selection. Use --efforts default.")
        supported = reasoning.get("supported_efforts")
        for effort in explicit:
            if (supported is not None and effort not in supported) or (effort == "none" and reasoning.get("mandatory")):
                raise ValueError(f"{model} does not support effort {effort}; supported levels: {supported}.")
        metadata[model] = {**reasoning, "supported_parameters": m.get("supported_parameters")}
    return metadata


def load_models(arg):
    if os.path.isfile(arg):
        lines = open(arg).read().splitlines()
    else:
        lines = arg.split(",")
    return [l.split("#")[0].strip() for l in lines if l.split("#")[0].strip()]


def load_texts(pattern, include_originals=False):
    paths = sorted(glob.glob(os.path.join(ROOT, "texts", pattern + ("" if pattern.endswith(".md") else ".md"))))
    # Prefer rewritten excerpts in broad selections; exact filenames stay accessible.
    if not include_originals and glob.has_magic(pattern):
        paths = [p for p in paths if not os.path.isfile(p.removesuffix(".md") + "_paraphrased.md")]
    return {os.path.splitext(os.path.basename(p))[0]: Path(p).read_text().strip() for p in paths}


def call(model, prompt, key, max_tokens, effort="default"):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    if effort != "default":
        body["reasoning"] = {"effort": effort}
        body["provider"] = {"require_parameters": True}
    for attempt in range(6):
        try:
            t0 = time.time()
            r = http("POST", f"{API}/chat/completions", body, key)
            if "error" in r:
                code = r['error'].get('code') if isinstance(r['error'], dict) else None
                if code in (401, 402):
                    return {'error': f'HTTP {code}: {json.dumps(r["error"])}', 'http_status': code}
                raise RuntimeError(json.dumps(r["error"]))
            choice = r["choices"][0]
            return {
                "content": choice["message"].get("content") or "",
                "response_model": r.get("model"),
                "generation_id": r.get("id"),
                "finish_reason": choice.get("finish_reason"),
                "provider": r.get("provider"),
                "usage": r.get("usage"),
                "seconds": round(time.time() - t0, 1),
            }
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(2 ** attempt * 3)
                continue
            return {"error": f"HTTP {e.code}: {msg}", "http_status": e.code}
        except CertificateError as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            if attempt < 5:
                time.sleep(2 ** attempt * 3)
                continue
            return {"error": repr(e)}


def parse_answer(text):
    """Pull the first JSON object (with "speakers" or "context") out of a model reply."""
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and ("speakers" in obj or "context" in obj):
            return obj
    return None


def load_targets(path=None):
    """targets.json maps text-name globs to {"speaker": [regex...], "context": [regex...]}.
    The first matching key wins, "default" applies when none match."""
    return json.loads(Path(path or TARGETS_FILE).read_text())


def target_for(text, targets):
    for pat, t in targets.items():
        if pat != "default" and fnmatch.fnmatch(text, pat):
            return t
    return targets["default"]


def matches(s, patterns):
    return any(re.search(p, s or "", re.I) for p in patterns)


def conf(v):
    """Confidence as a float: accepts 35, "35", "35%", "~35"; None if there's no number."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = re.search(r"[+-]?\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


def by_conf(items):
    """Dict entries sorted by descending confidence; stable, so the model's order breaks ties."""
    items = [x for x in items if isinstance(x, dict)]
    return sorted(items, key=lambda x: -(conf(x.get("confidence")) or 0))


def probability(value):
    value = conf(value)
    return min(100., max(0., value)) if value is not None and math.isfinite(value) else 0.


def normalized_candidates(items):
    """Scale an overfull list down to 100; never scale an underfull list up."""
    items = [x for x in items if isinstance(x, dict)]
    values = [probability(x.get("confidence")) for x in items]
    total = sum(values)
    scale = 100 / max(100., total)
    candidates = [{**item, "confidence": value * scale} for item, value in zip(items, values)]
    return by_conf(candidates), total


def score(record, targets):
    t = target_for(record["text"], targets)
    content = record.get("content", "")
    a = parse_answer(content) if content else None
    error = record.get("error", "")
    if not error and record.get("finish_reason") == "length":
        error = "truncated: max_tokens reached" + (" before any answer" if not content else " during the answer")
    row = {k: record[k] for k in ("text", "model", "run")}
    row["effort"] = record.get("effort", "default")
    row["scoring_version"] = SCORING_VERSION
    row["is_control"] = is_control(record["text"])
    row["finish_reason"] = record.get("finish_reason", "")
    row["completion_tokens"] = (record.get("usage") or {}).get("completion_tokens")
    row["reasoning_tokens"] = ((record.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens")
    row.update(parsed=bool(a), target_rank="", target_conf="", top1_speaker="", top1_conf="",
               top_context="", context_match=False, error=error,
               speaker_conf=0., context_conf=0., soft_score=0.,
               speaker_conf_total=0., context_conf_total=0.,
               cost_usd=(record.get("usage") or {}).get("cost"))
    if not a:
        # fall back: does the target name appear anywhere in the raw reply?
        row["target_rank"] = "mentioned" if matches(content, t["speaker"]) else ""
        return row
    speakers, row["speaker_conf_total"] = normalized_candidates(a.get("speakers") or [])
    for i, s in enumerate(speakers, 1):
        if matches(str(s.get("name")), t["speaker"]):
            row["target_rank"], row["target_conf"] = i, conf(s.get("confidence"))
            break
    if speakers:
        row["top1_speaker"], row["top1_conf"] = speakers[0].get("name", ""), conf(speakers[0].get("confidence"))
    ctx, row["context_conf_total"] = normalized_candidates(a.get("context") or [])
    if ctx:
        row["top_context"] = ctx[0].get("guess", "")
        row["context_match"] = matches(row["top_context"], t["context"])
    row["speaker_conf"] = probability(row["target_conf"])
    row["context_conf"] = min(100., sum(probability(c.get("confidence")) for c in ctx
                                       if matches(str(c.get("guess", "")), t["context"])))
    row["soft_score"] = (row["speaker_conf"] + row["context_conf"]) / 2
    return row


def summarize(run_dir):
    records = effective_records(read_attempts(run_dir))
    if not records:
        print(f"No records in {run_dir}/raw.jsonl")
        return
    targets, targets_source = run_targets(run_dir)
    rows = [score(r, targets) for r in records]
    with open(os.path.join(run_dir, "scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # aggregate per text x model x requested effort
    groups = {}
    for r in rows:
        groups.setdefault((r["text"], r["model"], r["effort"]), []).append(r)
    agg = []
    for (text, model, effort), rs in sorted(groups.items()):
        n = len(rs)
        top1 = sum(1 for r in rs if r["target_rank"] == 1)
        top5 = sum(1 for r in rs if isinstance(r["target_rank"], int))
        confs = [r["target_conf"] or 0 for r in rs if r["parsed"]]
        ctx = sum(1 for r in rs if r["context_match"])
        agg.append({
            "text": text, "model": model, "effort": effort, "runs": n,
            "scoring_version": SCORING_VERSION, "is_control": is_control(text),
            "target_top1": f"{top1}/{n}", "target_in_top5": f"{top5}/{n}",
            "mean_target_conf": round(sum(confs) / len(confs), 1) if confs else "",
            "context_match": f"{ctx}/{n}",
            "mean_context_conf": round(sum(r["context_conf"] for r in rs) / n, 2),
            "soft_score": round(sum(r["soft_score"] for r in rs) / n, 2),
            "parse_failures": sum(1 for r in rs if not r["parsed"]),
            "errors": sum(1 for r in rs if r["error"]),
            "truncations": sum(r["finish_reason"] == "length" for r in rs),
            "normalized_speaker_lists": sum(r["speaker_conf_total"] > 100 for r in rs),
            "normalized_context_lists": sum(r["context_conf_total"] > 100 for r in rs),
            "top1_answers": "; ".join(sorted({str(r["top1_speaker"]) for r in rs if r["top1_speaker"]})),
        })
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys()))
        w.writeheader()
        w.writerows(agg)
    controls = [a for a in agg if a["is_control"]]
    with (Path(run_dir) / "control_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0]))
        w.writeheader()
        w.writerows(controls)

    # markdown table for quick reading
    cols = ["text", "model", "effort", "target_top1", "target_in_top5", "mean_target_conf", "context_match", "soft_score", "errors", "truncations", "top1_answers"]
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    table_header = md.copy()
    md += ["| " + " | ".join(str(a[c]) for c in cols) + " |" for a in agg if not a["is_control"]]
    if controls:
        md += ["", "Control results (reported separately; lower recognition confidence is expected)", "", *table_header]
        md += ["| " + " | ".join(str(a[c]) for c in cols) + " |" for a in controls]
    md = [f"Scoring: {SCORING_VERSION}. Targets: {targets_source}.", "", *md]
    (Path(run_dir) / "summary.md").write_text("\n".join(md) + "\n")
    (Path(run_dir) / "scoring.json").write_text(json.dumps(dict(scoring_version=SCORING_VERSION,
        targets_source=targets_source, targets=targets), indent=2, ensure_ascii=False) + "\n")
    print("\n".join(md))
    from plot_bench import plot_results
    plot_results(run_dir, rows)
    from speaker_report import write_report
    write_report(run_dir, records)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=os.path.join(ROOT, "models.txt"), help="file with one model id per line, or comma-separated ids")
    ap.add_argument("--texts", default=DEFAULT_TEXTS, help="glob over texts/ (without .md); default: rewritten S1–S6; '*' also includes A–H")
    ap.add_argument("--include-originals", action="store_true", help="include original excerpts alongside paraphrases in glob selections")
    ap.add_argument("--prompt", default=os.path.join(ROOT, "prompts", "identify.md"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=16000, help="includes hidden reasoning tokens on reasoning models")
    ap.add_argument("--efforts", nargs="+", choices=EFFORTS, default=["default"],
                    type=lambda e: "medium" if e == "mid" else e,
                    help="reasoning effort levels to sweep, e.g. low medium high; default leaves effort unspecified")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-models", nargs="*", metavar="FILTER")
    ap.add_argument("--list-efforts", nargs="*", metavar="FILTER", help="show advertised effort levels for matching model ids")
    ap.add_argument("--summarize", metavar="RUN_DIR")
    ap.add_argument("--resume", metavar="RUN_DIR", help="resume saved inputs/settings; skip completed responses and retry API errors")
    ap.add_argument("--results-dir", default=os.path.join(ROOT, "results"))
    args = ap.parse_args()

    if args.resume:
        try:
            return resume_run(args.resume, args.dry_run, args.concurrency)
        except (ValueError, OSError) as e:
            sys.exit(str(e))

    if args.list_models is not None or args.list_efforts is not None:
        try:
            return list_efforts(args.list_efforts) if args.list_efforts is not None else list_models(args.list_models)
        except (CertificateError, urllib.error.URLError) as e:
            sys.exit(str(e))
    if args.summarize:
        return summarize(args.summarize)

    models = load_models(args.models)
    texts = load_texts(args.texts, args.include_originals)
    template = Path(args.prompt).read_text()
    targets = load_targets()
    efforts = list(dict.fromkeys(args.efforts))
    jobs = [(t, m, e, r) for t in texts for m in models for e in efforts for r in range(1, args.runs + 1)]
    print(f"{len(texts)} texts x {len(models)} models x {len(efforts)} efforts x {args.runs} runs = {len(jobs)} calls")
    if args.dry_run or not jobs:
        print("texts:", ", ".join(f"{t} -> {target_for(t, targets)['speaker'][0]}" for t in texts))
        print("models:", ", ".join(models))
        print("efforts:", ", ".join(efforts), "(support is checked before live calls)")
        return

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first.")
    try:
        reasoning_models = validate_efforts(models, efforts)
    except (ValueError, CertificateError, urllib.error.URLError) as e:
        sys.exit(str(e))

    run_dir = os.path.join(args.results_dir, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir)
    snapshot_run(run_dir, texts, template, targets)
    (Path(run_dir) / "config.json").write_text(json.dumps({"models": models, "texts": list(texts), "runs": args.runs,
               "efforts": efforts, "reasoning_models": reasoning_models, "max_tokens": args.max_tokens,
               "sampling": "provider defaults (temperature omitted)",
               "scoring_version": SCORING_VERSION, "text_selection": args.texts,
               "include_originals": args.include_originals,
               "prompt": template}, indent=2, ensure_ascii=False) + "\n")

    with (Path(run_dir) / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute_jobs(run_dir, jobs, texts, template, key, args.max_tokens, args.concurrency)
    print(f"\nRaw answers: {run_dir}/raw.jsonl\n")
    summarize(run_dir)


if __name__ == "__main__":
    main()
