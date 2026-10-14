#!/usr/bin/env python3
"""feigbench: can LLMs identify the speaker of a disguised interview?

Runs every text x model x run through OpenRouter, saves raw answers and a
scored CSV. Run with uv to install dependencies automatically.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  uv run run_bench.py --list-models gpt claude gemini   # find model ids
  uv run run_bench.py --dry-run                        # show the plan, no API calls
  uv run run_bench.py --runs 3                         # run everything
  uv run run_bench.py --texts 'S*' --models openai/gpt-4o --runs 5
  uv run run_bench.py --summarize results/<run_dir>     # re-score an existing run

The expected speaker and context for each text are in targets.json.
Set OPENROUTER_BASE_URL to use another OpenAI-compatible endpoint.
"""
import argparse, csv, datetime, fnmatch, glob, json, math, os, re, ssl, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import certifi

ROOT = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
TARGETS_FILE = os.path.join(ROOT, "targets.json")


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


def load_models(arg):
    if os.path.isfile(arg):
        lines = open(arg).read().splitlines()
    else:
        lines = arg.split(",")
    return [l.split("#")[0].strip() for l in lines if l.split("#")[0].strip()]


def load_texts(pattern):
    paths = sorted(glob.glob(os.path.join(ROOT, "texts", pattern + ("" if pattern.endswith(".md") else ".md"))))
    return {os.path.splitext(os.path.basename(p))[0]: open(p).read().strip() for p in paths}


def call(model, prompt, temperature, key, max_tokens):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    for attempt in range(6):
        try:
            t0 = time.time()
            r = http("POST", f"{API}/chat/completions", body, key)
            if "error" in r:
                raise RuntimeError(json.dumps(r["error"]))
            choice = r["choices"][0]
            return {
                "content": choice["message"].get("content") or "",
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
            return {"error": f"HTTP {e.code}: {msg}"}
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
    return json.load(open(path or TARGETS_FILE))


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
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


def by_conf(items):
    """Dict entries sorted by descending confidence; stable, so the model's order breaks ties."""
    items = [x for x in items if isinstance(x, dict)]
    return sorted(items, key=lambda x: -(conf(x.get("confidence")) or 0))


def probability(value):
    value = conf(value)
    return min(100., max(0., value)) if value is not None and math.isfinite(value) else 0.


def score(record, targets):
    t = target_for(record["text"], targets)
    content = record.get("content", "")
    a = parse_answer(content) if content else None
    error = record.get("error", "")
    if not error and not content and record.get("finish_reason") == "length":
        error = "truncated: max_tokens used up before any answer (reasoning model?)"
    row = {k: record[k] for k in ("text", "model", "run")}
    row.update(parsed=bool(a), target_rank="", target_conf="", top1_speaker="", top1_conf="",
               top_context="", context_match=False, error=error,
               speaker_conf=0., context_conf=0., soft_score=0.,
               cost_usd=(record.get("usage") or {}).get("cost"))
    if not a:
        # fall back: does the target name appear anywhere in the raw reply?
        row["target_rank"] = "mentioned" if matches(content, t["speaker"]) else ""
        return row
    speakers = by_conf(a.get("speakers") or [])
    for i, s in enumerate(speakers, 1):
        if matches(str(s.get("name")), t["speaker"]):
            row["target_rank"], row["target_conf"] = i, conf(s.get("confidence"))
            break
    if speakers:
        row["top1_speaker"], row["top1_conf"] = speakers[0].get("name", ""), conf(speakers[0].get("confidence"))
    ctx = by_conf(a.get("context") or [])
    if ctx:
        row["top_context"] = ctx[0].get("guess", "")
        row["context_match"] = matches(row["top_context"], t["context"])
    row["speaker_conf"] = probability(row["target_conf"])
    row["context_conf"] = min(100., sum(probability(c.get("confidence")) for c in ctx
                                       if matches(str(c.get("guess", "")), t["context"])))
    row["soft_score"] = (row["speaker_conf"] + row["context_conf"]) / 2
    return row


def summarize(run_dir):
    records = [json.loads(l) for l in open(os.path.join(run_dir, "raw.jsonl")) if l.strip()]
    if not records:
        print(f"No records in {run_dir}/raw.jsonl")
        return
    targets = load_targets()
    rows = [score(r, targets) for r in records]
    with open(os.path.join(run_dir, "scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # aggregate per text x model
    groups = {}
    for r in rows:
        groups.setdefault((r["text"], r["model"]), []).append(r)
    agg = []
    for (text, model), rs in sorted(groups.items()):
        n = len(rs)
        top1 = sum(1 for r in rs if r["target_rank"] == 1)
        top5 = sum(1 for r in rs if isinstance(r["target_rank"], int))
        confs = [r["target_conf"] or 0 for r in rs if r["parsed"]]
        ctx = sum(1 for r in rs if r["context_match"])
        agg.append({
            "text": text, "model": model, "runs": n,
            "target_top1": f"{top1}/{n}", "target_in_top5": f"{top5}/{n}",
            "mean_target_conf": round(sum(confs) / len(confs), 1) if confs else "",
            "context_match": f"{ctx}/{n}",
            "mean_context_conf": round(sum(r["context_conf"] for r in rs) / n, 2),
            "soft_score": round(sum(r["soft_score"] for r in rs) / n, 2),
            "parse_failures": sum(1 for r in rs if not r["parsed"]),
            "errors": sum(1 for r in rs if r["error"]),
            "top1_answers": "; ".join(sorted({str(r["top1_speaker"]) for r in rs if r["top1_speaker"]})),
        })
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys()))
        w.writeheader()
        w.writerows(agg)

    # markdown table for quick reading
    cols = ["text", "model", "target_top1", "target_in_top5", "mean_target_conf", "context_match", "soft_score", "errors", "top1_answers"]
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(a[c]) for c in cols) + " |" for a in agg]
    open(os.path.join(run_dir, "summary.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    from plot_bench import plot_results
    plot_results(run_dir, rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=os.path.join(ROOT, "models.txt"), help="file with one model id per line, or comma-separated ids")
    ap.add_argument("--texts", default="*", help="glob over texts/ (without .md), e.g. 'S*' or 'A_*'")
    ap.add_argument("--prompt", default=os.path.join(ROOT, "prompts", "identify.md"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=16000, help="includes hidden reasoning tokens on reasoning models")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-models", nargs="*", metavar="FILTER")
    ap.add_argument("--summarize", metavar="RUN_DIR")
    ap.add_argument("--results-dir", default=os.path.join(ROOT, "results"))
    args = ap.parse_args()

    if args.list_models is not None:
        try:
            return list_models(args.list_models)
        except CertificateError as e:
            sys.exit(str(e))
    if args.summarize:
        return summarize(args.summarize)

    models = load_models(args.models)
    texts = load_texts(args.texts)
    template = open(args.prompt).read()
    targets = load_targets()
    jobs = [(t, m, r) for t in texts for m in models for r in range(1, args.runs + 1)]
    print(f"{len(texts)} texts x {len(models)} models x {args.runs} runs = {len(jobs)} calls")
    if args.dry_run or not jobs:
        print("texts:", ", ".join(f"{t} -> {target_for(t, targets)['speaker'][0]}" for t in texts))
        print("models:", ", ".join(models))
        return

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first.")

    run_dir = os.path.join(args.results_dir, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir)
    json.dump({"models": models, "texts": list(texts), "runs": args.runs, "temperature": args.temperature,
               "prompt": template}, open(os.path.join(run_dir, "config.json"), "w"), indent=2, ensure_ascii=False)

    out = open(os.path.join(run_dir, "raw.jsonl"), "w")
    done = 0
    with ThreadPoolExecutor(args.concurrency) as ex:
        futs = {ex.submit(call, m, template.replace("{{TEXT}}", texts[t]), args.temperature, key, args.max_tokens): (t, m, r)
                for t, m, r in jobs}
        for fut in as_completed(futs):
            t, m, r = futs[fut]
            rec = {"text": t, "model": m, "run": r, **fut.result()}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            done += 1
            status = "ERROR " + rec["error"][:80] if "error" in rec else "ok" if rec["content"] else f"EMPTY (finish_reason={rec['finish_reason']})"
            print(f"[{done}/{len(jobs)}] {t} | {m} | run {r}: {status}", flush=True)
    out.close()
    print(f"\nRaw answers: {run_dir}/raw.jsonl\n")
    summarize(run_dir)


if __name__ == "__main__":
    main()
