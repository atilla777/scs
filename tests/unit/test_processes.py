import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool.processes import ProcessOwner, CleanupError


class ProcessTests(unittest.TestCase):
    def test_cleanup_budget_is_not_restarted_on_retry(self):
        owner = ProcessOwner()
        clock = [0.0]
        with (
            mock.patch.object(owner, "discover"),
            mock.patch.object(owner, "remaining", return_value=[123]),
            mock.patch(
                "scs_tool.processes.time.monotonic", side_effect=lambda: clock[0]
            ),
            mock.patch(
                "scs_tool.processes.time.sleep",
                side_effect=lambda n: clock.__setitem__(0, clock[0] + n),
            ),
        ):
            for _ in range(2):
                with self.assertRaises(CleanupError):
                    owner.cleanup()
        self.assertLessEqual(
            clock[0], 5.02, "one cleanup budget, not five seconds per retry"
        )

    def test_owned_output_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = ProcessOwner()
            result = owner.run(
                [
                    sys.executable,
                    "-c",
                    'import sys;print("raw");print("err",file=sys.stderr)',
                ],
                Path(tmp),
                "child",
                time.monotonic() + 5,
            )
            self.assertIsNotNone(result, "owned child must return process evidence")
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(Path(result["stdout"]).read_text(), "raw\n")
            self.assertEqual(Path(result["stderr"]).read_text(), "err\n")
            control = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(10)"]
            )
            try:
                with self.assertRaises(TimeoutError):
                    owner.run(
                        [sys.executable, "-c", "import time;time.sleep(10)"],
                        Path(tmp),
                        "hang",
                        time.monotonic() + 0.15,
                    )
                self.assertIsNone(control.poll(), "foreign control must remain alive")
                self.assertEqual(owner.remaining(), [])
            finally:
                control.terminate()
                control.wait()


if __name__ == "__main__":
    unittest.main()
