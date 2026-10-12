#!/usr/bin/env python3
"""feigbench: can LLMs identify the speaker of a disguised interview?

Runs every text x model x run through OpenRouter, saves raw answers and a
scored CSV. Standard library only.

Usage:
  export OPENROUTER_API_KEY=sk-or-...
  python3 run_bench.py --list-models gpt claude gemini   # find model ids
  python3 run_bench.py --dry-run                          # show the plan, no API calls
  python3 run_bench.py --runs 3                           # run everything
  python3 run_bench.py --texts 'S*' --models openai/gpt-4o --runs 5
  python3 run_bench.py --summarize results/<run_dir>      # re-score an existing run
"""
import argparse, csv, datetime, glob, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
API = "https://openrouter.ai/api/v1"
TARGET_PATTERNS = [r"feiglin", r"feiglen", r"פייגלין", r"פיגלין"]
CONTEXT_PATTERNS = [r"israel", r"gaza", r"palestin", r"ישראל", r"עזה"]


def http(method, url, body=None, key=None, timeout=300):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Title", "feigbench")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        return json.loads(r.read())


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
            return {
                "content": r["choices"][0]["message"].get("content") or "",
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
        except Exception as e:  # noqa: BLE001
            if attempt < 5:
                time.sleep(2 ** attempt * 3)
                continue
            return {"error": repr(e)}


def parse_answer(text):
    """Pull the first JSON object out of a model reply."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def matches(s, patterns):
    return any(re.search(p, s or "", re.I) for p in patterns)


def score(record):
    a = parse_answer(record.get("content", "")) if "content" in record else None
    row = {k: record[k] for k in ("text", "model", "run")}
    row.update(parsed=bool(a), target_rank="", target_conf="", top1_speaker="", top1_conf="",
               top_context="", context_is_target=False, error=record.get("error", ""))
    if not a:
        # fall back: does the target name appear anywhere in the raw reply?
        row["target_rank"] = "mentioned" if matches(record.get("content", ""), TARGET_PATTERNS) else ""
        return row
    speakers = a.get("speakers") or []
    for i, s in enumerate(speakers, 1):
        if matches(str(s.get("name")), TARGET_PATTERNS):
            row["target_rank"], row["target_conf"] = i, s.get("confidence", "")
            break
    if speakers:
        row["top1_speaker"], row["top1_conf"] = speakers[0].get("name", ""), speakers[0].get("confidence", "")
    ctx = a.get("context") or []
    if ctx:
        row["top_context"] = ctx[0].get("guess", "")
        row["context_is_target"] = matches(row["top_context"], CONTEXT_PATTERNS)
    return row


def summarize(run_dir):
    records = [json.loads(l) for l in open(os.path.join(run_dir, "raw.jsonl"))]
    rows = [score(r) for r in records]
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
        confs = [float(r["target_conf"] or 0) for r in rs if r["parsed"]]
        ctx = sum(1 for r in rs if r["context_is_target"])
        agg.append({
            "text": text, "model": model, "runs": n,
            "target_top1": f"{top1}/{n}", "target_in_top5": f"{top5}/{n}",
            "mean_target_conf": round(sum(confs) / len(confs), 1) if confs else "",
            "context_israel": f"{ctx}/{n}",
            "parse_failures": sum(1 for r in rs if not r["parsed"]),
            "top1_answers": "; ".join(sorted({str(r["top1_speaker"]) for r in rs if r["top1_speaker"]})),
        })
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys()))
        w.writeheader()
        w.writerows(agg)

    # markdown table for quick reading
    cols = ["text", "model", "target_top1", "target_in_top5", "mean_target_conf", "context_israel", "top1_answers"]
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(a[c]) for c in cols) + " |" for a in agg]
    open(os.path.join(run_dir, "summary.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=os.path.join(ROOT, "models.txt"), help="file with one model id per line, or comma-separated ids")
    ap.add_argument("--texts", default="*", help="glob over texts/ (without .md), e.g. 'S*' or 'A_*'")
    ap.add_argument("--prompt", default=os.path.join(ROOT, "prompts", "identify.md"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-models", nargs="*", metavar="FILTER")
    ap.add_argument("--summarize", metavar="RUN_DIR")
    args = ap.parse_args()

    if args.list_models is not None:
        return list_models(args.list_models)
    if args.summarize:
        return summarize(args.summarize)

    models = load_models(args.models)
    texts = load_texts(args.texts)
    template = open(args.prompt).read()
    jobs = [(t, m, r) for t in texts for m in models for r in range(1, args.runs + 1)]
    print(f"{len(texts)} texts x {len(models)} models x {args.runs} runs = {len(jobs)} calls")
    if args.dry_run or not jobs:
        print("texts:", ", ".join(texts))
        print("models:", ", ".join(models))
        return

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first.")

    run_dir = os.path.join(ROOT, "results", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
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
            status = "ERROR " + rec["error"][:80] if "error" in rec else "ok"
            print(f"[{done}/{len(jobs)}] {t} | {m} | run {r}: {status}", flush=True)
    out.close()
    print(f"\nRaw answers: {run_dir}/raw.jsonl\n")
    summarize(run_dir)


if __name__ == "__main__":
    main()
