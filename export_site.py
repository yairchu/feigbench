#!/usr/bin/env python3
"""Build a self-contained static benchmark page from a saved run."""
import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

from plotly.offline import get_plotlyjs, get_plotlyjs_version
from plot_bench import EFFORT_ORDER, MODEL_NAMES, VENDOR_COLORS, VENDOR_NAMES, model_summary
from run_bench import SCORING_VERSION, effective_records, is_control, job_key, normalized_candidates, parse_answer, read_attempts, run_targets, score

ROOT = Path(__file__).resolve().parent


def build_site(run_dir, output):
    directory, output = Path(run_dir), Path(output)
    snapshot = json.loads((directory / 'snapshot.json').read_text())
    config = json.loads((directory / 'config.json').read_text())
    targets, _ = run_targets(directory)
    records = effective_records(read_attempts(directory))
    expected = {(t, m, e, r) for t in config['texts'] for m in config['models']
                for e in config.get('efforts', ['default']) for r in range(1, config['runs'] + 1)}
    actual = {job_key(r) for r in records}
    if actual != expected:
        raise ValueError(f'Page requires a complete run: {len(expected - actual)} missing and {len(actual - expected)} unexpected calls.')
    rows = [score(r, targets) for r in records]
    points = model_summary(rows)
    cohorts = defaultdict(set)
    for row in rows:
        if not is_control(row['text']):
            cohorts[(row['model'], row['effort'])].add((row['text'], row['run']))
    for p in points:
        p['name'] = MODEL_NAMES.get(p['model'].split('/')[-1], p['model'].split('/')[-1])
        p['vendor'] = p['model'].split('/')[0]
        p['vendor_name'] = VENDOR_NAMES.get(p['vendor'], p['vendor'].capitalize())
        p['color'] = VENDOR_COLORS.get(p['vendor'], '#61747b')
    links = []
    for model in config['models']:
        ps = sorted((p for p in points if p['model'] == model and p['mean_cost_usd'] is not None),
                    key=lambda p: EFFORT_ORDER.index(p['effort']))
        if ps and all(cohorts[(model, p['effort'])] == cohorts[(model, ps[0]['effort'])] for p in ps):
            links.append([f"{p['model']}|{p['effort']}" for p in ps])
    examples = []
    for name, model, effort, run in [('Ramzan Kadyrov', 'google/gemini-3.5-flash-lite', 'high', 3),
                                      ('Osama bin Laden', 'openai/gpt-6-luna', 'high', 3)]:
        for r in records:
            if r['model'] == model and r.get('effort') == effort and r['run'] == run and r['text'].startswith('S1_'):
                candidates, _ = normalized_candidates((parse_answer(r.get('content', '')) or {}).get('speakers') or [])
                if not candidates or candidates[0]['name'] != name:
                    raise ValueError(f'Example no longer matches the saved response: {name}')
                examples.append(dict(speaker=name, model=model, effort=effort, run=run,
                                     confidence=candidates[0]['confidence'], text=r['text'], candidates=candidates))
    if len(examples) != 2:
        raise ValueError('This page’s worked examples require the October 15 run.')
    data = dict(run=directory.name, scoring_version=SCORING_VERSION, models=len(config['models']),
                scored_calls=sum(not is_control(r['text']) for r in rows), control_calls=sum(is_control(r['text']) for r in rows),
                api_errors=sum(bool(r.get('error')) for r in records), repetitions=config['runs'],
                max_tokens=config['max_tokens'], points=points, links=links, examples=examples,
                texts=snapshot['texts'], prompt=snapshot['prompt'], targets=snapshot['targets'],
                effort_order=list(EFFORT_ORDER), plotly_version=get_plotlyjs_version())
    output.mkdir(parents=True, exist_ok=True)
    for filename in ('index.html', 'style.css', 'app.js'):
        shutil.copyfile(ROOT / 'site' / filename, output / filename)
    (output / 'plotly.min.js').write_text(get_plotlyjs())
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False)
    (output / 'data.js').write_text('window.FEIGBENCH = ' + serialized + ';\n')
    (output / 'results.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    for filename, values in [('model_summary.csv', points), ('scored.csv', rows)]:
        with (output / filename).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    (output / 'prompt.txt').write_text(snapshot['prompt'])
    (output / 'texts.json').write_text(json.dumps(snapshot['texts'], ensure_ascii=False, indent=2))
    (output / 'responses.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    print(f'Built {output}/index.html: {len(points)} settings, {data["scored_calls"]} scored calls; Plotly {data["plotly_version"]}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir')
    parser.add_argument('--output', type=Path, default=ROOT / 'site' / 'dist')
    args = parser.parse_args()
    build_site(args.run_dir, args.output)
