#!/usr/bin/env python3
"""Report reviewed non-Israeli highest-confidence speaker guesses for a run."""
import argparse
import csv
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from run_bench import is_control, normalized_candidates, parse_answer, effective_records, read_attempts

CATALOG = Path(__file__).with_name('speaker_origins.json')


def name_key(name):
    return ''.join(c for c in unicodedata.normalize('NFKD', name).casefold() if c.isalnum())


def catalog_index(catalog):
    index = {}
    for entry in catalog['entries']:
        for name in [entry['name'], *entry.get('aliases', [])]:
            key = name_key(name)
            if key in index and index[key]['name'] != entry['name']:
                raise ValueError(f'Duplicate identity alias: {name}')
            index[key] = entry
    return index


def first_choices(records, catalog):
    index = catalog_index(catalog)
    choices = []
    for record in records:
        answer = parse_answer(record.get('content', ''))
        if not answer:
            continue
        speakers, _ = normalized_candidates(answer.get('speakers') or [])
        if not speakers:
            continue
        top = speakers[0]  # Same ranking/tie-break as the benchmark scorer.
        name = str(top.get('name', ''))
        entry = index.get(name_key(name), {})
        choices.append(dict(scope='control' if is_control(record['text']) else 'scored',
                            text=record['text'], model=record['model'], effort=record.get('effort', 'default'),
                            run=record['run'], raw_name=name, name=entry.get('name', name),
                            classification=entry.get('classification', 'unclassified'),
                            background=entry.get('background', ''), confidence=top['confidence'],
                            source=entry.get('source', '')))
    return choices


def summarize_choices(choices):
    groups = defaultdict(list)
    for choice in choices:
        if choice['classification'] == 'non_israeli':
            groups[choice['scope'], choice['name']].append(choice)
    rows = []
    for (scope, name), calls in groups.items():
        models = Counter(c['model'] for c in calls)
        texts = Counter(c['text'] for c in calls)
        rows.append(dict(scope=scope, name=name, background=calls[0]['background'], top1_calls=len(calls),
                         mean_confidence=round(sum(c['confidence'] for c in calls) / len(calls), 2),
                         models='; '.join(f'{m}: {n}' for m, n in sorted(models.items())),
                         excerpts='; '.join(f'{t}: {n}' for t, n in sorted(texts.items())), source=calls[0]['source']))
    return sorted(rows, key=lambda r: (r['scope'] == 'control', -r['top1_calls'], r['name']))


def write_csv(path, rows, fields):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def write_report(run_dir, records=None):
    directory = Path(run_dir)
    if records is None:
        records = effective_records(read_attempts(directory))
    catalog = json.loads(CATALOG.read_text())
    choices = first_choices(records, catalog)
    summary = summarize_choices(choices)
    detail_fields = ['scope', 'text', 'model', 'effort', 'run', 'raw_name', 'name', 'classification', 'background', 'confidence', 'source']
    write_csv(directory / 'speaker_first_choices.csv', choices, detail_fields)
    write_csv(directory / 'unclassified_speakers.csv', [c for c in choices if c['classification'] == 'unclassified'], detail_fields)
    write_csv(directory / 'non_israeli_speakers.csv', summary,
              ['scope', 'name', 'background', 'top1_calls', 'mean_confidence', 'models', 'excerpts', 'source'])
    (directory / 'speaker_report_catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    md = [f'# Non-Israeli speaker guesses — {directory.name}', '',
          'Counts refer to the highest-confidence speaker per reply, across all effort levels and repetitions. '
          'Ties use the model\'s listed order, matching benchmark scoring. Confidence is normalized before aggregation. '
          'These are model guesses, not evidence that the named people expressed the views in the excerpts.', '',
          'Background is a national association label, not an exhaustive citizenship register. '
          'Identities and aliases use the accompanying reviewed catalog; unknown names and generic descriptions '
          'are left unclassified rather than inferred from their spelling.', '']
    for scope, label in [('scored', 'Scored texts'), ('control', 'S6 control (separate)')]:
        rs = [r for r in summary if r['scope'] == scope]
        scoped = [r for r in choices if r['scope'] == scope]
        attempts = [r for r in records if ('control' if is_control(r['text']) else 'scored') == scope]
        non_israeli = sum(r['top1_calls'] for r in rs)
        unclassified = sum(c['classification'] == 'unclassified' for c in scoped)
        md += [f'## {label}', '',
               f'{non_israeli} non-Israeli first choices / {len(attempts)} calls; '
               f'{unclassified} unclassified first choices; {len(attempts) - len(scoped)} calls without a speaker guess.', '',
               '| Speaker | Background | First choices | Mean confidence | Excerpts |',
               '|---|---|---:|---:|---|']
        for r in rs:
            linked_name = f"[{r['name']}]({r['source']})"
            excerpts = Counter(c['text'].split('_')[0] for c in scoped if c['name'] == r['name'])
            md.append('| ' + ' | '.join(map(cell, [linked_name, r['background'], r['top1_calls'],
                f"{r['mean_confidence']:.1f}%", ', '.join(f'{t} ×{n}' for t, n in sorted(excerpts.items()))])) + ' |')
        md += ['', '| Model | Non-Israeli first-choice guesses (count) |', '|---|---|']
        for model in sorted({r['model'] for r in attempts}):
            counts = Counter(c['name'] for c in scoped if c['model'] == model and c['classification'] == 'non_israeli')
            md.append(f"| {cell(model)} | {cell('; '.join(f'{n} ×{k}' for n,k in counts.most_common()) or 'None')} |")
        md += ['']
    unknown = Counter(c['raw_name'] for c in choices if c['classification'] == 'unclassified')
    if unknown:
        md += ['## Unclassified first choices', '',
               'These are excluded from the nationality totals; see `unclassified_speakers.csv` for model and text details.', '',
               '| Guess | Count |', '|---|---:|']
        md += [f'| {cell(n)} | {k} |' for n,k in unknown.most_common()]
    (directory / 'non_israeli_speakers.md').write_text('\n'.join(md) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir')
    args = parser.parse_args()
    write_report(args.run_dir)
    print(f'Report: {args.run_dir}/non_israeli_speakers.md')


if __name__ == '__main__':
    main()
