import json
import tempfile
import unittest
from pathlib import Path

import speaker_report


class SpeakerReportTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {'entries': [
            {'name': 'Igor Girkin', 'aliases': ['Igor Strelkov'], 'classification': 'non_israeli', 'background': 'Russian'},
            {'name': 'Moshe Feiglin', 'classification': 'israeli', 'background': 'Israeli'}]}

    def record(self, name, text='S3_test', confidence=80):
        return dict(text=text, model='m', effort='medium', run=1,
                    content=json.dumps({'speakers': [{'name': 'Moshe Feiglin', 'confidence': 40},
                                                     {'name': name, 'confidence': confidence}]}))

    def test_ranking_normalization_aliases_and_separate_control(self):
        choices = speaker_report.first_choices([self.record('Igor Strelkov'), self.record('Igor Girkin'),
                                               self.record('Igor Girkin', 'S6_leadership_only_control_paraphrased')], self.catalog)
        self.assertEqual({c['name'] for c in choices}, {'Igor Girkin'})
        self.assertAlmostEqual(choices[0]['confidence'], 80 / 120 * 100)
        scored, control = speaker_report.summarize_choices(choices)
        self.assertEqual((scored['scope'], scored['top1_calls']), ('scored', 2))
        self.assertEqual((control['scope'], control['top1_calls']), ('control', 1))

    def test_unknown_is_not_assumed_non_israeli(self):
        choice, = speaker_report.first_choices([self.record('Unreviewed Person')], self.catalog)
        self.assertEqual(choice['classification'], 'unclassified')
        self.assertEqual(speaker_report.summarize_choices([choice]), [])
        self.assertEqual(speaker_report.first_choices([{'content': 'not JSON'}], self.catalog), [])

    def test_report_files_and_actual_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            speaker_report.write_report(tmp, [self.record('Igor Girkin (Strelkov)'), self.record('Unknown person')])
            text = (Path(tmp) / 'non_israeli_speakers.md').read_text()
            self.assertIn('1 non-Israeli first choices / 2 calls', text)
            self.assertIn('Unknown person', (Path(tmp) / 'unclassified_speakers.csv').read_text())
            self.assertTrue((Path(tmp) / 'speaker_report_catalog.json').exists())


if __name__ == '__main__':
    unittest.main()
