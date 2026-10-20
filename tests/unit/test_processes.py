import os
import signal
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
    def test_parallel_stream_drain_and_per_stream_limit(self):
        for stream in (1, 2):
            with (
                self.subTest(stream=stream),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
            ):
                owner = ProcessOwner()
                record = owner.run(
                    [
                        sys.executable,
                        "-c",
                        "import os\nfor _ in range(64):\n os.write(1,b'o'*8192);os.write(2,b'e'*8192)",
                    ],
                    Path(tmp),
                    "drain",
                    time.monotonic() + 5,
                )
                self.assertEqual(
                    Path(record["stdout"]).read_bytes(), b"o" * (64 * 8192)
                )
                self.assertEqual(
                    Path(record["stderr"]).read_bytes(), b"e" * (64 * 8192)
                )
                with self.assertRaisesRegex(OverflowError, "Log limit"):
                    owner.run(
                        [
                            sys.executable,
                            "-c",
                            f"import os;os.write({stream},b'x'*(16*1024*1024+65536))",
                        ],
                        Path(tmp),
                        "overflow",
                        time.monotonic() + 5,
                    )
                self.assertEqual(owner.remaining(), [])
                path = Path(owner.evidence[-1]["stdout" if stream == 1 else "stderr"])
                self.assertLessEqual(path.stat().st_size, 16 * 1024 * 1024)

    def test_exited_leader_detached_term_ignoring_descendant_is_killed_and_reaped(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            control = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(30)"]
            )
            owner = ProcessOwner()
            pidfile = root / "child.pid"
            child = (
                "import os,signal,time;from pathlib import Path;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(30)"
            )
            leader = (
                "import subprocess,sys,time;from pathlib import Path;"
                f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True);"
                f"p=Path({str(pidfile)!r})\nwhile not p.exists(): time.sleep(.01)"
            )
            actual_signal = signal.pidfd_send_signal
            sent = []

            def observe(fd, signum):
                sent.append(signum)
                return actual_signal(fd, signum)

            try:
                with mock.patch("scs_tool.processes.signal.pidfd_send_signal", observe):
                    with self.assertRaises(TimeoutError):
                        owner.run(
                            [sys.executable, "-c", leader],
                            root,
                            "orphan",
                            time.monotonic() + 0.4,
                        )
                self.assertTrue(pidfile.exists())
                self.assertFalse(Path("/proc/" + pidfile.read_text()).exists())
                self.assertEqual(owner.remaining(), [])
                self.assertIn(signal.SIGTERM, sent)
                self.assertIn(signal.SIGKILL, sent)
                self.assertIsNone(control.poll())
            finally:
                owner.cleanup()
                control.terminate()
                control.wait()

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
