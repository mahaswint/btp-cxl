"""Exercise suite orchestration with tiny fake runners, never gem5 or workloads."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

GUEST = Path(__file__).parents[2] / 'guest'
with patch.object(sys, 'path', [str(GUEST), *sys.path]):
    spec = importlib.util.spec_from_file_location('guest_suite', GUEST / 'run_all.py')
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)

FAKE_RUNNER = '''
import argparse
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--workload')
parser.add_argument('--output-dir')
parser.add_argument('--print-command', action='store_true')
parser.add_argument('--trial-minutes')
args, _ = parser.parse_known_args()
if args.print_command:
    raise SystemExit(0)
output = Path(args.output_dir)
output.mkdir()
print('fake output from ' + args.workload)
raise SystemExit((124 if args.trial_minutes else 7) if args.workload == 'stream' else 0)
'''


class GuestSuiteTest(unittest.TestCase):
    def test_trial_preserves_incomplete_status_and_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self.invoke(root, '--size', 'smoke', '--trial-minutes', '45', '--keep-going'), 1)
            report = json.loads((root / 'results/summary.json').read_text())
            self.assertEqual([r['status'] for r in report['runs']], ['completed', 'trial_incomplete', 'completed'])
            calibration = json.loads((root / 'results/calibration.json').read_text())
            self.assertIsNone(calibration['under_six_hours_measured'])

    def invoke(self, root, *args):
        (root / 'images').mkdir()
        (root / 'images/btp.img.json').write_text('{"profile": "basic"}')
        (root / 'run.py').write_text(FAKE_RUNNER)
        with patch.object(suite, 'HERE', root), patch.object(suite, 'REPO', root):
            return suite.main(['--output-dir', str(root / 'results'), *args])

    def test_failure_stops_and_marks_remaining_runs_not_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self.invoke(root), 1)
            report = json.loads((root / 'results/summary.json').read_text())
            self.assertEqual([r['status'] for r in report['runs']], ['completed', 'failed', 'not_run'])
            self.assertEqual(report['runs'][1]['exit_code'], 7)
            self.assertIn('fake output from stream', Path(report['runs'][1]['runner_log']).read_text())
            self.assertFalse(Path(report['runs'][2]['output_dir']).exists())
            self.assertIn('gups', report['unavailable'])

    def test_keep_going_repeats_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self.invoke(root, '--repeat', '2', '--keep-going'), 1)
            records = json.loads((root / 'results/summary.json').read_text())['runs']
            self.assertEqual(len({r['output_dir'] for r in records}), 6)
            self.assertEqual([r['status'] for r in records], ['completed', 'failed', 'completed'] * 2)
            self.assertTrue((root / 'results/summary.csv').is_file())

    def test_dry_run_creates_no_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self.invoke(root, '--dry-run'), 0)
            self.assertFalse((root / 'results').exists())

    def test_all_suite_rejects_basic_image_before_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(SystemExit) as exc:
                self.invoke(root, '--suite', 'all')
            self.assertEqual(exc.exception.code, 2)
            self.assertFalse((root / 'results').exists())

    def test_all_profile_selects_every_supported_workload(self):
        self.assertEqual(suite.select_workloads('all', 'installed', None), list(suite.ORDER))
        self.assertEqual(set(suite.ORDER), suite.ALL)


if __name__ == '__main__':
    unittest.main()
