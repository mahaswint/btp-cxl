"""Tests for the application-defined DLRM CPU-switch boundary."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
WRAPPER = ROOT / "guest/payload/src/dlrm_roi.py"


class DlrmRoiTest(unittest.TestCase):
    def test_switch_and_phase_markers_surround_inference(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            dlrm = temp / "dlrm.py"
            dlrm.write_text(
                "def inference():\n"
                "    print('DUMMY INFERENCE', flush=True)\n"
                "def run():\n"
                "    inference()\n"
            )
            control = temp / "control.py"
            control.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "with open(os.environ['CONTROL_LOG'], 'a') as log:\n"
                "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
            )
            control.chmod(0o755)
            log = temp / "control.log"
            status = temp / "status.txt"
            env = dict(
                os.environ,
                SIMCXL_DLRM_ENTRY=str(dlrm),
                SIMCXL_M5=str(control),
                SIMCXL_PHASE=str(control),
                SIMCXL_ROI_STATUS=str(status),
                SIMCXL_EXIT_AT_ROI_END="0",
                CONTROL_LOG=str(log),
            )
            result = subprocess.run(
                [sys.executable, str(WRAPPER)],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertEqual(
                log.read_text().splitlines(),
                ["--addr exit", "begin workload", "end workload"],
            )
            self.assertLess(
                result.stdout.index("ROI SWITCH REQUEST"),
                result.stdout.index("DUMMY INFERENCE"),
            )
            self.assertLess(
                result.stdout.index("DUMMY INFERENCE"),
                result.stdout.index("ROI END"),
            )
            fields = dict(
                line.split("=", 1) for line in status.read_text().splitlines()
            )
            self.assertEqual(fields["roi_switch_requested"], "1")
            self.assertEqual(fields["roi_completed"], "1")
            self.assertEqual(fields["roi_cache_state"], "cold_at_switch")
            self.assertGreaterEqual(float(fields["roi_seconds"]), 0)

    def test_missing_inference_fails_without_switching(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            dlrm = temp / "dlrm.py"
            dlrm.write_text("def inference(): pass\ndef run(): pass\n")
            log = temp / "control.log"
            status = temp / "status.txt"
            env = dict(
                os.environ,
                SIMCXL_DLRM_ENTRY=str(dlrm),
                SIMCXL_M5="/does/not/matter",
                SIMCXL_PHASE="/does/not/matter",
                SIMCXL_ROI_STATUS=str(status),
                CONTROL_LOG=str(log),
            )
            result = subprocess.run(
                [sys.executable, str(WRAPPER)],
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("without entering inference", result.stderr)
            self.assertFalse(status.exists())


if __name__ == "__main__":
    unittest.main()
