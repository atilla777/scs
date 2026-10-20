"""Real CLI/process/file adapters, fake external SC executables only.

The fake prep emits independently constructed valid binary Score fixtures;
this isolates failure policy, and does not replace real SC integration.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/unit"))
sys.path.insert(0, str(ROOT / "skills/supercollider/scripts"))
from test_score import SOURCE, FINAL, MANIFEST
from scs_tool import render, files, sc
from scs_tool.processes import CleanupError

CLI = ROOT / "skills/supercollider/scripts/sc-tool.py"
SAMPLE = ROOT / "skills/supercollider/assets/minimal-nrt.scd"


class PipelineTests(unittest.TestCase):
    def test_caller_relative_path_matches_absolute_path_control(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, self.wav())
            for flag in ["--sclang", "--scsynth"]:
                index = args.index(flag)
                del args[index : index + 2]
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            (bin_dir / "sclang").symlink_to(tmp / "fake sclang")
            (bin_dir / "scsynth").symlink_to(tmp / "fake scsynth")
            outcomes = []
            for name, path in [
                ("relative", "bin:/usr/bin:/bin"),
                ("absolute", str(bin_dir) + ":/usr/bin:/bin"),
            ]:
                request = args.copy()
                request[request.index("--output") + 1] = str(tmp / (name + ".wav"))
                process = subprocess.run(
                    [sys.executable, "-B", str(CLI)] + request,
                    cwd=tmp,
                    env={**os.environ, "PATH": path},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                result = json.loads(process.stdout)
                self.assertEqual(process.returncode, result["exit_code"])
                self.assertEqual(process.stderr, "")
                outcomes.append(result)
            self.assertEqual(outcomes[1]["exit_code"], 0, outcomes[1])
            self.assertEqual(outcomes[0]["exit_code"], 0, outcomes[0])
            self.assertEqual(outcomes[0]["measured"], outcomes[1]["measured"])
            for result in outcomes:
                for process in result["diagnostics"]["processes"]:
                    self.assertTrue(Path(process["argv"][0]).is_absolute())

    def test_version_and_prepared_protocol_fail_closed(self):
        for mutation, expected in [
            (
                lambda text: text.replace("sclang 3.14.1", "sclang 9.0.0"),
                "unsupported_environment",
            ),
            (
                lambda text: text.replace('"+token+"', '"+"wrong-token"+"'),
                "sclang_unconfirmed",
            ),
            (
                lambda text: text + '\nprint("ERROR: fixture compile failure")\n',
                "sclang_error",
            ),
        ]:
            with (
                self.subTest(expected=expected),
                tempfile.TemporaryDirectory() as directory,
            ):
                tmp = Path(directory)
                args = self.fixture(tmp, self.wav())
                language = tmp / "fake sclang"
                language.write_text(mutation(language.read_text()))
                result = self.run_cli(args)
                self.assertEqual(result["errors"][0]["code"], expected, result)
                self.assertEqual(result["artifacts"]["ready"], [])
                self.assertFalse((tmp / "output.wav").exists())

    def test_wrapper_exception_is_not_sc_success(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, self.wav())
            with mock.patch.object(
                sc, "discover", side_effect=RuntimeError("fixture wrapper fault")
            ):
                result = render.execute(args)
            self.assertEqual(result["exit_code"], 20)
            self.assertEqual(result["errors"][0]["code"], "wrapper_error")
            self.assertEqual(result["artifacts"]["ready"], [])

    def test_cleanup_failure_retains_published_output(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, self.wav())
            original = files.finalize_run

            def fail_cleanup(work, staging, keep):
                original(work, staging, keep)
                return [{"action": "remove_owned_directory", "path": str(work)}]

            with mock.patch.object(files, "finalize_run", side_effect=fail_cleanup):
                result = render.execute(args)
            self.assertEqual(result["exit_code"], 25, result)
            self.assertEqual(result["artifacts"]["ready"], [])
            self.assertTrue(result["artifacts"]["partial"][0]["published"])
            self.assertTrue(result["artifacts"]["partial"][0]["verified"])
            self.assertTrue((tmp / "output.wav").exists())
            self.assertTrue(result["unfinished_actions"])

    def test_cleanup_failure_preserves_original_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, "pass")

            def fail_discovery(*args):
                try:
                    raise TimeoutError("original timeout")
                except TimeoutError as cause:
                    raise CleanupError("cleanup failed") from cause

            with mock.patch.object(sc, "discover", side_effect=fail_discovery):
                result = render.execute(args)
            self.assertEqual(result["exit_code"], 25)
            self.assertIn("timeout", [error["code"] for error in result["errors"]])

    def test_preparation_warnings_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, self.wav())
            language = tmp / "fake sclang"
            language.write_text(
                language.read_text()
                + '\nprint("WARNING: Could not set realtime scheduling priority")\n'
            )
            result = self.run_cli(args)
            self.assertEqual(result["exit_code"], 0, result)
            self.assertTrue(
                any("realtime scheduling" in w["message"] for w in result["warnings"]),
                "observed preparation warning must be explicit",
            )

    def fixture(self, tmp, behavior):
        lib = tmp / "library/Common/Control"
        lib.mkdir(parents=True)
        (lib / "Score.sc").write_text("// fake boundary only")
        language = tmp / "fake sclang"
        language.write_text(
            "#!/usr/bin/python3\n" + "import sys,json\nfrom pathlib import Path\n"
            'if sys.argv[1:]==["-v"]:\n print("sclang 3.14.1 (Built from test)");sys.exit(0)\n'
            "source,final,status,token,frames,rate,channels,seed=sys.argv[-8:]\n"
            "p=Path(final).parent\n"
            + f'(p/"source.osc").write_bytes({SOURCE!r})\n'
            + f"Path(final).write_bytes({FINAL!r})\n"
            + f'(p/"source-plan.json").write_text({json.dumps(MANIFEST)!r})\n'
            + 'Path(status).write_text("SC_TOOL\\t2\\t"+token+"\\tPREPARED\\t"+frames+"\\t"+rate+"\\t"+channels+"\\n")\n'
        )
        server = tmp / "fake scsynth"
        server.write_text(
            "#!/usr/bin/python3\n"
            "import sys,wave,struct,time,os,subprocess\nfrom pathlib import Path\n"
            'if sys.argv[1:]==["-v"]:\n print("scsynth 3.14.1 (Built from test)");sys.exit(0)\n'
            "out=sys.argv[4]\n" + behavior + "\n"
        )
        language.chmod(0o700)
        server.chmod(0o700)
        return [
            "render",
            "--source",
            str(SAMPLE),
            "--output",
            str(tmp / "output.wav"),
            "--duration",
            "2",
            "--sample-rate",
            "48000",
            "--channels",
            "2",
            "--sclang",
            str(language),
            "--scsynth",
            str(server),
            "--sc-class-library",
            str(tmp / "library"),
            "--temp-dir",
            str(tmp),
            "--diagnostics-dir",
            str(tmp),
        ]

    @staticmethod
    def wav(frames=96064, rate=48000, channels=2):
        return (
            'with wave.open(out,"wb") as w:\n'
            f' w.setparams(({channels},2,{rate},0,"NONE",""))\n'
            f' w.writeframes(b"\\0"*({frames}*{channels}*2))\n'
        )

    def run_cli(self, args):
        completed = subprocess.run(
            [sys.executable, "-B", str(CLI)] + args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, result["exit_code"])
        self.assertEqual(completed.stderr, "")
        return result

    def test_external_failure_matrix_baseline(self):
        cases = [
            ("missing", "pass", "audio_invalid", 12),
            ("broken", 'Path(out).write_bytes(b"broken")', "audio_invalid", 12),
            ("frames", self.wav(frames=96063), "audio_mismatch", 13),
            ("rate", self.wav(rate=44100), "audio_mismatch", 13),
            ("channels", self.wav(channels=1), "audio_mismatch", 13),
            (
                "error",
                self.wav() + 'print("FAILURE IN SERVER /s_new")',
                "nrt_error",
                11,
            ),
            (
                "unknown",
                self.wav() + 'print("mysterious diagnostic")',
                "nrt_unconfirmed",
                11,
            ),
            ("exit", "sys.exit(7)", "nrt_error", 11),
            ("limit", 'os.write(1,b"x"*(16*1024*1024+65536))', "resource_limit", 21),
        ]
        for name, behavior, code, exit_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                tmp = Path(directory)
                args = self.fixture(tmp, behavior)
                result = self.run_cli(args)
                self.assertEqual(result["errors"][0]["code"], code, result)
                self.assertEqual(result["exit_code"], exit_code)
                self.assertEqual(result["artifacts"]["ready"], [])
                self.assertFalse((tmp / "output.wav").exists())
                self.assertFalse(list(tmp.glob("scs-work-*")))
                if name not in ["missing", "exit", "limit"]:
                    self.assertEqual(len(result["artifacts"]["partial"]), 1)
                    self.assertFalse(result["artifacts"]["partial"][0]["published"])

    def test_timeout_and_signal_owned_tree(self):
        for signum in (None, signal.SIGINT, signal.SIGTERM):
            with (
                self.subTest(signum=signum),
                tempfile.TemporaryDirectory() as directory,
            ):
                tmp = Path(directory)
                # Descendant starts a new session and closes inherited pipes.
                behavior = (
                    'child=subprocess.Popen([sys.executable,"-c",'
                    '"import time;time.sleep(60)"],start_new_session=True,'
                    "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                    f'Path({str(tmp / "output.wav.pids")!r}).write_text(str(os.getpid())+" "+str(child.pid))\n'
                    "time.sleep(60)"
                )
                args = self.fixture(tmp, behavior) + [
                    "--timeout",
                    "1" if signum is None else "10",
                ]
                control = subprocess.Popen(
                    [sys.executable, "-c", "import time;time.sleep(60)"]
                )
                process = subprocess.Popen(
                    [sys.executable, "-B", str(CLI)] + args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    until = time.monotonic() + 5
                    while (
                        not (tmp / "output.wav.pids").exists()
                        and time.monotonic() < until
                    ):
                        time.sleep(0.01)
                    self.assertTrue((tmp / "output.wav.pids").exists())
                    if signum:
                        process.send_signal(signum)
                    stdout, stderr = process.communicate(timeout=8)
                    result = json.loads(stdout)
                    self.assertEqual(stderr, "")
                    self.assertEqual(
                        result["exit_code"], 128 + signum if signum else 24, result
                    )
                    self.assertEqual(
                        result["status"], "cancelled" if signum else "timeout"
                    )
                    for pid in map(int, (tmp / "output.wav.pids").read_text().split()):
                        self.assertFalse(
                            Path(f"/proc/{pid}").exists(), f"owned {pid} survived"
                        )
                    self.assertIsNone(control.poll())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    control.terminate()
                    control.wait()
                    process.stdout.close()
                    process.stderr.close()

    def test_parallel_same_target_no_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            args = self.fixture(tmp, self.wav())
            processes = [
                subprocess.Popen(
                    [sys.executable, "-B", str(CLI)] + args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(stderr, "")
                results.append(json.loads(stdout))
            self.assertEqual(sorted(r["exit_code"] for r in results), [0, 14], results)
            self.assertNotEqual(results[0]["run_id"], results[1]["run_id"])
            self.assertNotEqual(
                results[0]["diagnostics"]["directory"],
                results[1]["diagnostics"]["directory"],
            )
