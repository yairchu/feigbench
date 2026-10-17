import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from export_site import build_site
from run_bench import SCORING_VERSION, load_targets


class SiteExportTest(unittest.TestCase):
    def prepare(self, root):
        run = root / 'run'
        run.mkdir()
        models = ['google/gemini-3.5-flash-lite', 'openai/gpt-6-luna']
        texts = {'S1_test_paraphrased': 'saved excerpt', 'S6_leadership_only_control_paraphrased': 'saved control'}
        config = dict(models=models, texts=list(texts), efforts=['high'], runs=3, max_tokens=32000)
        snapshot = dict(texts=texts, prompt='saved prompt', targets=load_targets(), scoring_version=SCORING_VERSION)
        (run / 'config.json').write_text(json.dumps(config))
        (run / 'snapshot.json').write_text(json.dumps(snapshot))
        records = []
        for text in texts:
            for model in models:
                for repetition in range(1, 4):
                    speaker = 'Ramzan Kadyrov' if model.startswith('google') else 'Osama bin Laden'
                    confidence = 35 if model.startswith('google') else 7
                    answer = dict(speakers=[dict(name=speaker, confidence=confidence)],
                                  context=[dict(guess='Israel', confidence=80)])
                    records.append(dict(text=text, model=model, effort='high', run=repetition,
                                        content=json.dumps(answer), usage=dict(cost=.1), finish_reason='stop'))
        # A failed earlier attempt must not be counted in the exported results.
        attempts = [dict(text='S1_test_paraphrased', model=models[0], effort='high', run=1, error='HTTP 502')] + records
        (run / 'raw.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in attempts))
        return run, records

    def test_export_uses_saved_inputs_deduplicates_and_excludes_control_from_chart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, records = self.prepare(root)
            with patch('export_site.get_plotlyjs', return_value='/* test library */'):
                build_site(run, root / 'output')
            data = json.loads((root / 'output/results.json').read_text())
            self.assertEqual(data['scored_calls'], 6)
            self.assertEqual(data['control_calls'], 6)
            self.assertEqual(data['texts']['S1_test_paraphrased'], 'saved excerpt')
            self.assertEqual(data['prompt'], 'saved prompt')
            self.assertEqual(len(data['points']), 2)
            for point in data['points']:
                self.assertEqual(point['calls'], 3)
                self.assertEqual(point['texts'], 1)
                self.assertEqual(point['soft_score'], 40)
            self.assertEqual([p['confidence'] for p in data['examples']], [35, 7])
            exported = (root / 'output/responses.jsonl').read_text().splitlines()
            self.assertEqual(len(exported), 12)
            with (root / 'output/scored.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 12)

    def test_incomplete_run_is_rejected_before_writing_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, records = self.prepare(root)
            (run / 'raw.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records[:-1]))
            with self.assertRaisesRegex(ValueError, '1 missing'):
                build_site(run, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_changed_example_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, records = self.prepare(root)
            for record in records:
                record['content'] = json.dumps(dict(speakers=[dict(name='Someone else', confidence=50)]))
            (run / 'raw.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
            with self.assertRaisesRegex(ValueError, 'Example no longer matches'):
                build_site(run, root / 'output')
