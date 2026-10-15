import contextlib
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import run_bench

ANSWER = json.dumps({'speakers': [{'name': 'Moshe Feiglin', 'confidence': 80}],
                     'context': [{'guess': 'Israel', 'confidence': 90}]})


class ResumeTest(unittest.TestCase):
    def prepare(self, directory):
        run_bench.snapshot_run(directory, {'S1_test': 'saved text'}, 'saved {{TEXT}}', run_bench.load_targets())
        config = dict(models=['m'], texts=['S1_test'], efforts=['high'], runs=3, max_tokens=32000,
                      prompt='saved {{TEXT}}', sampling='provider defaults (temperature omitted)')
        (directory / 'config.json').write_text(json.dumps(config))
        successful = dict(text='S1_test', model='m', effort='high', run=1, content=ANSWER,
                          finish_reason='stop', usage={'cost': .1})
        error = dict(text='S1_test', model='m', effort='high', run=2, error='HTTP 402: empty balance')
        raw = json.dumps(successful) + '\n' + json.dumps(error) + '\n'
        (directory / 'raw.jsonl').write_text(raw)
        return raw

    def test_resume_skips_success_retries_errors_and_counts_jobs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            before = self.prepare(directory)
            with mock.patch.object(run_bench, 'call', return_value={'content': ANSWER, 'finish_reason': 'stop', 'usage': {'cost': .2}}) as call, \
                 mock.patch.object(run_bench, 'load_texts', side_effect=AssertionError('current inputs used')), \
                 mock.patch.object(run_bench, 'summarize'), \
                 mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test'}), contextlib.redirect_stdout(io.StringIO()):
                run_bench.resume_run(tmp, concurrency=1)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(call.call_args.args, ('m', 'saved saved text', 'test', 32000, 'high'))
            self.assertTrue((directory / 'raw.jsonl').read_text().startswith(before))
            attempts = run_bench.read_attempts(tmp)
            self.assertEqual(len(attempts), 4)
            effective = run_bench.effective_records(attempts)
            self.assertEqual(len(effective), 3)
            self.assertFalse(any(r.get('error') for r in effective))
            self.assertEqual(effective[0]['usage']['cost'], .1)
            with mock.patch('plot_bench.plot_results'), contextlib.redirect_stdout(io.StringIO()):
                run_bench.summarize(tmp)
            with (directory / 'summary.csv').open() as f:
                summary, = csv.DictReader(f)
            self.assertEqual((summary['runs'], summary['target_top1']), ('3', '3/3'))
            with mock.patch.object(run_bench, 'call') as call, mock.patch.object(run_bench, 'summarize'), \
                 contextlib.redirect_stdout(io.StringIO()):
                run_bench.resume_run(tmp)
            call.assert_not_called()

    def test_credit_failure_stops_scheduling(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [('S1', 'm', 'high', n) for n in range(1, 8)]
            with mock.patch.object(run_bench, 'call', return_value={'error': 'HTTP 402: cap', 'http_status': 402}) as call, \
                 contextlib.redirect_stdout(io.StringIO()):
                stopped = run_bench.execute_jobs(tmp, jobs, {'S1': 'text'}, '{{TEXT}}', 'key', 32000, 1)
            self.assertTrue(stopped)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(len(run_bench.read_attempts(tmp)), 1)

    def test_dry_run_and_no_selective_resampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.prepare(directory)
            attempts = run_bench.read_attempts(tmp)
            attempts[0].update(content='', finish_reason='length')
            (directory / 'raw.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in attempts))
            with mock.patch.object(run_bench, 'call') as call, contextlib.redirect_stdout(io.StringIO()) as output:
                run_bench.resume_run(tmp, dry_run=True)
            call.assert_not_called()
            self.assertIn('1 completed; 2 missing or API-failed', output.getvalue())
            self.assertEqual(len(run_bench.read_attempts(tmp)), 2)

    def test_error_in_success_http_response_stops_without_retries(self):
        with mock.patch.object(run_bench, 'http', return_value={'error': {'code': 402, 'message': 'cap'}}) as http:
            result = run_bench.call('m', 'prompt', 'key', 32000)
        self.assertEqual(result['http_status'], 402)
        http.assert_called_once()

    def test_effective_results_preserve_first_response_over_later_failures(self):
        record = dict(text='S1', model='m', effort='low', run=1, content=ANSWER)
        rows = run_bench.effective_records([record, {**record, 'error': 'HTTP 402'}, {**record, 'content': 'different answer'}])
        self.assertEqual(rows, [record])


if __name__ == '__main__':
    unittest.main()
