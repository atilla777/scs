"""Integrated coordinator fault matrix; only the external SC boundary is fake.

Injected exceptions model boundary failures, not actual kernel/SC failures.
Cancellation uses the same latched callback as CLI signal handlers. Real signal
delivery/process ownership is checked separately in test_pipeline/test_processes.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_pipeline
import test_resource_pipeline
from scs_tool import files, render, sc, wav


class ResilienceTests(unittest.TestCase):
    fixture = test_pipeline.PipelineTests.fixture
    wav = staticmethod(test_pipeline.PipelineTests.wav)
    resource_fixture = test_resource_pipeline.ResourcePipelineTests.resource_fixture

    def execute(self, args, **kwargs):
        result = render.execute(args, **kwargs)
        if os.environ.get("SCS_EVIDENCE_DIR"):
            target = Path(os.environ["SCS_EVIDENCE_DIR"]) / result["run_id"]
            directory = result["diagnostics"]["directory"]
            if directory:
                shutil.copytree(directory, target)
            else:
                target.mkdir(parents=True)
            (target / "observed.json").write_text(json.dumps(result) + "\n")
            (target / "case.json").write_text(
                json.dumps(
                    {
                        "test": self.id(),
                        "case": str(self._subtest),
                        "argv": args,
                        "boundary": "contract model; external SC executables are fake",
                    }
                )
                + "\n"
            )
        return result

    def request(self, root, resources):
        return (
            self.resource_fixture(root) if resources else self.fixture(root, self.wav())
        )

    def assert_final(self, root, result, stage, code, published=False):
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["stage"], stage, result)
        self.assertEqual(result["exit_code"], code, result)
        self.assertEqual(
            result["status"],
            "timeout" if code == 24 else "cancelled" if code in (130, 143) else "error",
            result,
        )
        self.assertEqual(result["artifacts"]["ready"], [])
        self.assertEqual((root / "output.wav").exists(), published)
        self.assertFalse(list(root.glob("scs-work-*")))
        directory = result["diagnostics"]["directory"]
        if directory:
            self.assertEqual(
                json.loads((Path(directory) / "result.json").read_text()), result
            )
            for record in result["diagnostics"]["processes"]:
                self.assertFalse(Path(f"/proc/{record['pid']}").exists())
                for stream in ("stdout", "stderr"):
                    self.assertTrue(Path(record[stream]).is_file())
        if published:
            artifact = result["artifacts"]["partial"][0]
            self.assertTrue(artifact["published"])
            self.assertTrue(artifact["verified"])
            self.assertEqual(artifact["reason"], "published_not_ready")

    def test_boundary_error_and_timeout_matrix_both_resource_branches(self):
        # Each seam is entered by the real coordinator after all prior stages.
        boundaries = [
            (render, "validate_request", "input", 2),
            (sc, "discover", "dependencies", 3),
            (sc, "prepare_score", "prepare", 10),
            (sc, "run_nrt", "nrt", 11),
            (sc, "verify_resources", "resources", 11),
            (wav, "read_wav", "audio", 12),
            (files, "publish_no_replace", "publish", 14),
        ]
        for resources in (False, True):
            for module, name, stage, code in boundaries:
                for timeout in (False, True):
                    if stage == "input" and timeout:
                        # Validation has no timed blocking seam; the deadline
                        # begins from the validated request at its checkpoint.
                        continue
                    with self.subTest(
                        resources=resources, stage=stage, timeout=timeout
                    ):
                        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                            root = Path(tmp)
                            args = self.request(root, resources)
                            failure = (
                                TimeoutError("injected deadline")
                                if timeout
                                else sc.Failure(
                                    "fixture_fault", code, "injected " + stage
                                )
                            )
                            with mock.patch.object(
                                module, name, side_effect=failure
                            ) as seam:
                                result = self.execute(args)
                            seam.assert_called_once()
                            self.assert_final(
                                root, result, stage, 24 if timeout else code
                            )
                            self.assertEqual(
                                result["errors"][0]["code"],
                                "timeout" if timeout else "fixture_fault",
                            )
                            # No later subprocess stage is launched after a stopping cause.
                            stages = [
                                p["stage"] for p in result["diagnostics"]["processes"]
                            ]
                            if stage in ("input", "dependencies", "prepare"):
                                self.assertNotIn("nrt", stages)
                            if stage in ("resources", "audio", "publish"):
                                self.assertTrue(result["artifacts"]["partial"])
                            if stage in ("audio", "publish"):
                                count = int(resources)
                                self.assertEqual(
                                    result["resource_evidence"]["generations"], count
                                )
                                self.assertEqual(
                                    result["resource_evidence"]["verified_generations"],
                                    count,
                                )

    def test_latched_signals_at_every_stage_both_resource_branches(self):
        for resources in (False, True):
            for stage in (
                "input",
                "dependencies",
                "prepare",
                "nrt",
                "resources",
                "audio",
                "publish",
                "cleanup",
            ):
                for signum in (signal.SIGINT, signal.SIGTERM):
                    with self.subTest(resources=resources, stage=stage, signal=signum):
                        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                            root = Path(tmp)
                            args = self.request(root, resources)
                            flag = None
                            # Poll real checkpoints inside discover/prepare/NRT/readers;
                            # publication cancellation is latched before its checkpoint.
                            module, name = {
                                "input": (render, "validate_request"),
                                "dependencies": (sc, "discover"),
                                "prepare": (sc, "prepare_score"),
                                "nrt": (sc, "run_nrt"),
                                "resources": (sc, "run_nrt"),
                                "audio": (wav, "read_wav"),
                                "publish": (render, "compare_audio"),
                                "cleanup": (files, "finalize_run"),
                            }[stage]
                            original = getattr(module, name)

                            def latch(*a, **kw):
                                nonlocal flag
                                if stage in (
                                    "input",
                                    "resources",
                                    "publish",
                                    "cleanup",
                                ):
                                    value = original(*a, **kw)
                                    flag = signum
                                    return value
                                flag = signum
                                return original(*a, **kw)

                            with mock.patch.object(
                                module, name, side_effect=latch
                            ) as seam:
                                result = self.execute(args, cancelled=lambda: flag)
                            seam.assert_called_once()
                            self.assert_final(
                                root,
                                result,
                                stage,
                                128 + signum,
                                published=stage == "cleanup",
                            )
                            self.assertEqual(result["errors"][0]["code"], "cancelled")
                            self.assertEqual(result["unfinished_actions"], [])

    def test_publication_and_final_evidence_faults(self):
        for resources in (False, True):
            for fault in (
                "before_link",
                "after_link",
                "files.json",
                "result.json",
                "cleanup",
            ):
                with self.subTest(resources=resources, fault=fault):
                    with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                        root = Path(tmp)
                        args = self.request(root, resources)
                        flag = None
                        link, write, finalize = (
                            files.publish_no_replace,
                            files.write_json,
                            files.finalize_run,
                        )

                        def publish(*a):
                            nonlocal flag
                            if fault == "before_link":
                                raise OSError("injected atomic link failure")
                            link(*a)
                            if fault == "after_link":
                                flag = signal.SIGTERM

                        def save(path, value):
                            if Path(path).name == fault:
                                raise OSError("injected evidence write failure")
                            return write(path, value)

                        def cleanup(*a):
                            actions = finalize(*a)
                            return actions + (
                                [
                                    {
                                        "action": "remove_owned_directory",
                                        "path": str(a[0]),
                                    }
                                ]
                                if fault == "cleanup"
                                else []
                            )

                        with (
                            mock.patch.object(files, "publish_no_replace", publish),
                            mock.patch.object(files, "write_json", save),
                            mock.patch.object(files, "finalize_run", cleanup),
                        ):
                            result = self.execute(args, cancelled=lambda: flag)
                        code = (
                            14
                            if fault == "before_link"
                            else 143
                            if fault == "after_link"
                            else 25
                        )
                        self.assertEqual(result["exit_code"], code, result)
                        self.assertEqual(result["artifacts"]["ready"], [])
                        self.assertEqual(
                            (root / "output.wav").exists(), fault != "before_link"
                        )
                        if fault != "before_link":
                            self.assertTrue(
                                result["artifacts"]["partial"][0]["published"]
                            )
                        if code == 25:
                            self.assertTrue(result["unfinished_actions"])
                            self.assertEqual(result["stage"], "cleanup")

    def test_existing_aliases_are_never_modified(self):
        for resources in (False, True):
            for alias in ("source", "hardlink", "symlink", "dangling", "regular"):
                with self.subTest(resources=resources, alias=alias):
                    with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                        root = Path(tmp)
                        args = self.request(root, resources)
                        source = root / "source '$;\n.scd"
                        source.write_bytes(test_pipeline.SAMPLE.read_bytes())
                        args[args.index("--source") + 1] = str(source)
                        target = root / "output.wav"
                        if alias == "source":
                            target = source
                            args[args.index("--output") + 1] = str(source)
                        elif alias == "hardlink":
                            os.link(source, target)
                        elif alias == "symlink":
                            target.symlink_to(source)
                        elif alias == "dangling":
                            target.symlink_to(root / "missing")
                        else:
                            target.write_bytes(b"foreign output")
                        before = (
                            source.read_bytes(),
                            target.lstat(),
                            os.readlink(target)
                            if target.is_symlink()
                            else target.read_bytes(),
                        )
                        result = self.execute(args)
                        self.assertEqual(
                            result["errors"][0]["code"], "output_exists", result
                        )
                        self.assertEqual(result["exit_code"], 14)
                        self.assertEqual(result["diagnostics"]["processes"], [])
                        self.assertEqual(source.read_bytes(), before[0])
                        self.assertEqual(target.lstat().st_ino, before[1].st_ino)
                        self.assertEqual(
                            os.readlink(target)
                            if target.is_symlink()
                            else target.read_bytes(),
                            before[2],
                        )

    def test_canonical_and_snapshot_read_cancellation_and_io_fault(self):
        for module, name, stage in (
            (sc, "read_canonical_resource", "prepare"),
            (wav, "compare_resource_state", "resources"),
        ):
            for outcome in ("io", "timeout", signal.SIGINT, signal.SIGTERM):
                with self.subTest(boundary=name, outcome=outcome):
                    with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                        root = Path(tmp)
                        args = self.request(root, True)
                        flag = None
                        original = getattr(module, name)

                        def interrupt(*a, **kw):
                            nonlocal flag
                            if stage == "resources" and not str(a[1]).endswith(
                                ".snapshot.wav"
                            ):
                                return original(*a, **kw)
                            if outcome == "io":
                                raise OSError("injected resource read failure")
                            if outcome == "timeout":

                                def deadline():
                                    raise TimeoutError(
                                        "resource read deadline exceeded"
                                    )

                                return original(*a[:-1], deadline)
                            flag = outcome
                            return original(*a, **kw)

                        with mock.patch.object(module, name, side_effect=interrupt):
                            result = self.execute(args, cancelled=lambda: flag)
                        self.assert_final(
                            root,
                            result,
                            stage,
                            24
                            if outcome == "timeout"
                            else (2 if stage == "prepare" else 14)
                            if outcome == "io"
                            else 128 + outcome,
                        )
                        self.assertEqual(result["artifacts"]["ready"], [])

    def test_lost_logs_and_overflow_never_become_ready(self):
        for resources in (False, True):
            for stage in ("dependencies", "prepare", "nrt", "lost_logs"):
                with self.subTest(resources=resources, stage=stage):
                    with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                        root = Path(tmp)
                        args = self.request(root, resources)
                        if stage == "lost_logs":
                            original = sc.run_nrt

                            def lose_log(request, owner, *a):
                                # Remove actual observed stream evidence before
                                # adapter validation, not a fake result object.
                                actual_run = owner.run

                                def run(*args, **kwargs):
                                    record = actual_run(*args, **kwargs)
                                    Path(record["stderr"]).unlink()
                                    return record

                                with mock.patch.object(owner, "run", run):
                                    return original(request, owner, *a)

                            with mock.patch.object(sc, "run_nrt", lose_log):
                                result = self.execute(args)
                            self.assertEqual(result["exit_code"], 14, result)
                        else:
                            executable = root / (
                                "fake scsynth" if stage == "nrt" else "fake sclang"
                            )
                            text = executable.read_text()
                            overflow = (
                                "import os;os.write(2,b'x'*(16*1024*1024+65536))\n"
                            )
                            if stage == "dependencies":
                                text = text.replace(
                                    "import sys,json\n",
                                    "import sys,json\n" + overflow,
                                    1,
                                )
                            else:
                                text += "\n" + overflow
                            executable.write_text(text)
                            result = self.execute(args)
                            self.assertEqual(result["exit_code"], 21, result)
                            self.assertEqual(
                                result["errors"][0]["code"], "resource_limit"
                            )
                        self.assertEqual(
                            result["stage"], "nrt" if stage == "lost_logs" else stage
                        )
                        self.assertEqual(result["artifacts"]["ready"], [])
                        self.assertFalse((root / "output.wav").exists())

    def test_nested_score_and_audio_read_deadlines(self):
        for resources in (False, True):
            for module, name, stage in (
                (sc, "validate_source_plan", "prepare"),
                (wav, "read_wav", "audio"),
            ):
                with self.subTest(resources=resources, boundary=name):
                    with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                        root = Path(tmp)
                        args = self.request(root, resources)
                        original = getattr(module, name)

                        def deadline():
                            raise TimeoutError("nested read deadline exceeded")

                        def interrupt(*a):
                            return original(*a[:-1], deadline)

                        with mock.patch.object(module, name, side_effect=interrupt):
                            result = self.execute(args)
                        self.assert_final(root, result, stage, 24)
                        self.assertEqual(result["errors"][0]["code"], "timeout")

    def test_real_version_probe_hang_keeps_timeout_cause(self):
        for resources in (False, True):
            with self.subTest(resources=resources):
                with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                    root = Path(tmp)
                    args = self.request(root, resources) + ["--timeout", "1"]
                    language = root / "fake sclang"
                    language.write_text(
                        language.read_text().replace(
                            "import sys,json\n",
                            "import sys,json,time\ntime.sleep(60)\n",
                            1,
                        )
                    )
                    result = self.execute(args)
                    self.assert_final(root, result, "dependencies", 24)
                    self.assertEqual(result["errors"][0]["code"], "timeout")

    def test_concurrent_success_failure_and_same_target_keep_independent_truth(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            requests = []
            for label, resources, fail in (
                ("empty", False, False),
                ("resource", True, False),
                ("failure", True, True),
            ):
                child = root / label
                child.mkdir()
                args = self.request(child, resources)
                args[args.index("--output") + 1] = str(root / "shared '$;\n.wav")
                server = child / "fake scsynth"
                # Hold all three real subprocesses at NRT before any publisher
                # can win the input check. The failure must be an actual NRT
                # failure, not an early output_exists shortcut.
                server.write_text(
                    server.read_text() + f"\nbarrier=Path({str(root)!r})\n"
                    f"(barrier/{('ready-' + label)!r}).touch()\n"
                    "until=time.monotonic()+5\n"
                    "while len(list(barrier.glob('ready-*')))<3:\n"
                    " if time.monotonic()>until: raise RuntimeError('barrier deadline')\n"
                    " time.sleep(.01)\n"
                )
                if fail:
                    server.write_text(
                        server.read_text() + '\nprint("FAILURE IN SERVER injected")\n'
                    )
                requests.append(args)
            processes = [
                subprocess.Popen(
                    [sys.executable, "-B", str(test_pipeline.CLI)] + args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for args in requests
            ]
            results = []
            try:
                for process in processes:
                    out, err = process.communicate(timeout=10)
                    self.assertEqual(err, "")
                    result = json.loads(out)
                    self.assertEqual(process.returncode, result["exit_code"])
                    results.append(result)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdout.close()
                    process.stderr.close()
            self.assertEqual(sum(r["exit_code"] == 0 for r in results), 1, results)
            self.assertIn(14, [r["exit_code"] for r in results])
            self.assertEqual(results[2]["exit_code"], 11, results)
            self.assertEqual(len({r["run_id"] for r in results}), 3)
            directories = [
                r["diagnostics"]["directory"]
                for r in results
                if r["diagnostics"]["directory"]
            ]
            self.assertEqual(len(directories), len(set(directories)))
            for result in results:
                if result["resource_evidence"] is not None:
                    manifest = json.loads(
                        Path(result["resource_evidence"]["manifest"]).read_text()
                    )
                    self.assertEqual(manifest["run_id"], result["run_id"])
                    for generation in manifest["resources"]:
                        self.assertEqual(
                            Path(generation["prepared"]["snapshot"]).parent,
                            Path(result["diagnostics"]["directory"]),
                        )
