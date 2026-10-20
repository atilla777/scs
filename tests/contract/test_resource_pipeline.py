"""Resource failure models at the external SC boundary, not SC integration."""

import json
import hashlib
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import test_pipeline
from scs_tool import render, sc, files

ROOT = Path(__file__).resolve().parents[2]


class ResourcePipelineTests(unittest.TestCase):
    def assert_cancelled_resource_cleanup(self, root, result, signum):
        self.assertEqual(result["status"], "cancelled", result)
        self.assertEqual(result["exit_code"], 128 + signum, result)
        self.assertEqual(result["stage"], "cleanup")
        self.assertEqual(result["artifacts"]["ready"], [])
        artifact = result["artifacts"]["partial"][0]
        self.assertEqual(artifact["reason"], "published_not_ready")
        self.assertTrue(artifact["published"])
        self.assertTrue(artifact["verified"])
        output = root / "output.wav"
        self.assertEqual(
            hashlib.sha256(output.read_bytes()).hexdigest(),
            result["measured"]["sha256"],
        )
        self.assertEqual(result["unfinished_actions"], [])
        directory = Path(result["diagnostics"]["directory"])
        self.assertEqual(json.loads((directory / "result.json").read_text()), result)
        manifest = json.loads((directory / "resources.json").read_text())
        for g in manifest["resources"]:
            for role in ("canonical", "reference", "snapshot"):
                self.assertEqual(g["retention"][role], "removed")
                self.assertFalse(Path(g["prepared"][role]).exists())
            if "input" in g:
                self.assertEqual(g["input"]["retention"], "removed")
                self.assertFalse(Path(g["input"]["staged"]).exists())
        self.assertFalse(list(root.glob("scs-work-*")))
        self.assertFalse(list(root.glob(".scs-staging-*")))

    def test_cancel_during_each_resource_cleanup_preserves_published_partial(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            for suffix in (
                ".canonical.wav",
                ".reference.f32",
                ".snapshot.wav",
                ".input",
            ):
                with (
                    self.subTest(signum=signum, suffix=suffix),
                    tempfile.TemporaryDirectory(dir="/tmp/opencode") as name,
                ):
                    root = Path(name)
                    args = self.resource_fixture(root)
                    flag = None
                    actual_unlink, actual_prepare = Path.unlink, sc.prepare_score

                    def add_staged_cleanup_role(*args, **kwargs):
                        # Model an already validated owned staged-file cleanup role;
                        # this is not evidence of SC file decoding/integration.
                        plan = actual_prepare(*args, **kwargs)
                        staged = Path(
                            plan["resources"][0]["prepared"]["canonical"]
                        ).with_name("resource-0.input")
                        staged.write_bytes(b"owned staged input")
                        plan["resources"][0]["input"] = dict(
                            staged=str(staged), retention="pending"
                        )
                        return plan

                    def cancel_during_unlink(path, *args, **kwargs):
                        nonlocal flag
                        if str(path).endswith(suffix):
                            flag = signum
                        return actual_unlink(path, *args, **kwargs)

                    with (
                        mock.patch.object(sc, "prepare_score", add_staged_cleanup_role),
                        mock.patch.object(Path, "unlink", cancel_during_unlink),
                    ):
                        result = render.execute(args, cancelled=lambda: flag)
                    self.assertEqual(flag, signum)
                    self.assert_cancelled_resource_cleanup(root, result, signum)

    def test_cancel_during_final_evidence_writes_is_saved_truthfully(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            for filename in ("resources.json", "files.json", "result.json"):
                with (
                    self.subTest(signum=signum, filename=filename),
                    tempfile.TemporaryDirectory(dir="/tmp/opencode") as name,
                ):
                    root = Path(name)
                    args = self.resource_fixture(root)
                    flag = None
                    actual_write = files.write_json

                    def cancel_during_final_write(path, value):
                        nonlocal flag
                        actual_write(path, value)
                        # Only the post-publication finalization write is the seam.
                        if (
                            Path(path).name == filename
                            and (root / "output.wav").exists()
                        ):
                            flag = signum

                    with mock.patch.object(
                        files, "write_json", cancel_during_final_write
                    ):
                        result = render.execute(args, cancelled=lambda: flag)
                    self.assertEqual(flag, signum)
                    self.assert_cancelled_resource_cleanup(root, result, signum)

    def test_cleanup_failure_keeps_priority_over_late_cancellation(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with (
                self.subTest(signum=signum),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as name,
            ):
                root = Path(name)
                args = self.resource_fixture(root)
                flag = None
                actual_unlink = Path.unlink

                def cancel_then_fail_cleanup(path, *args, **kwargs):
                    nonlocal flag
                    if str(path).endswith(".canonical.wav"):
                        flag = signum
                    if str(path).endswith(".snapshot.wav"):
                        raise PermissionError(13, "injected cleanup denial", str(path))
                    return actual_unlink(path, *args, **kwargs)

                with mock.patch.object(Path, "unlink", cancel_then_fail_cleanup):
                    result = render.execute(args, cancelled=lambda: flag)
                self.assertEqual(flag, signum)
                self.assertEqual(result["exit_code"], 25, result)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["artifacts"]["ready"], [])
                self.assertTrue(result["artifacts"]["partial"][0]["published"])
                self.assertTrue((root / "output.wav").exists())
                directory = Path(result["diagnostics"]["directory"])
                self.assertEqual(
                    json.loads((directory / "result.json").read_text()), result
                )
                g = json.loads((directory / "resources.json").read_text())["resources"][
                    0
                ]
                self.assertEqual(g["retention"]["snapshot"], "cleanup_failed")
                self.assertTrue(
                    any(
                        a["action"] == "remove_owned_file"
                        and a["path"] == g["prepared"]["snapshot"]
                        for a in result["unfinished_actions"]
                    )
                )

    def test_resource_parallel_target_race_isolated_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            args = self.resource_fixture(root)
            processes = [
                subprocess.Popen(
                    [sys.executable, "-B", str(test_pipeline.CLI)] + args,
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
            prepared = [r for r in results if r["resource_evidence"] is not None]
            if len(prepared) == 2:
                paths = [
                    json.loads(Path(r["resource_evidence"]["manifest"]).read_text())[
                        "resources"
                    ][0]["prepared"]["snapshot"]
                    for r in prepared
                ]
                self.assertNotEqual(paths[0], paths[1])

    def test_resource_request_protects_existing_target(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            args = self.resource_fixture(root)
            (root / "output.wav").write_bytes(b"protected")
            result = self.run_cli(args)
            self.assertEqual(result["exit_code"], 14, result)
            self.assertEqual((root / "output.wav").read_bytes(), b"protected")
            self.assertEqual(result["diagnostics"]["processes"], [])

    def test_resource_cleanup_failure_preserves_published_output_and_exact_action(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            args = self.resource_fixture(root)
            original = Path.unlink

            def fail_snapshot(path, *a, **kw):
                if str(path).endswith(".snapshot.wav"):
                    raise PermissionError(
                        13, "injected snapshot cleanup denial", str(path)
                    )
                return original(path, *a, **kw)

            with mock.patch.object(Path, "unlink", fail_snapshot):
                result = render.execute(args)
            self.assertEqual(result["exit_code"], 25, result)
            self.assertEqual(result["artifacts"]["ready"], [])
            self.assertTrue(result["artifacts"]["partial"][0]["published"])
            self.assertTrue((root / "output.wav").exists())
            self.assertTrue(
                any(
                    a["action"] == "remove_owned_file"
                    and a["path"].endswith(".snapshot.wav")
                    for a in result["unfinished_actions"]
                ),
                result,
            )

    fixture = test_pipeline.PipelineTests.fixture
    wav = staticmethod(test_pipeline.PipelineTests.wav)
    run_cli = test_pipeline.PipelineTests.run_cli

    def resource_fixture(self, root, prep_mutation="", server_mutation="", zero=False):
        args = self.fixture(root, self.wav())
        language = root / "fake sclang"
        header = language.read_text().split("source,final,")[0]
        language.write_text(
            header
            + "sys.dont_write_bytecode=True\n"
            + f"sys.path.insert(0,{str(ROOT / 'tests/unit')!r})\n"
            "import struct,copy\nfrom test_score import SOURCE,MANIFEST,bundle,message\n"
            "from test_resources import generation\nfrom test_float_resources import float_wav\n"
            "source,final,status,token,frames,rate,channels,seed=sys.argv[-8:]\n"
            "p=Path(final).parent\ng=generation()\n"
            "g['prepared'].update({key:str(p/('resource-0'+suffix)) for key,suffix in [('canonical','.canonical.wav'),('reference','.reference.f32'),('snapshot','.snapshot.wav')]})\n"
            f"values={(0.0,) * 6 if zero else (0.125, -0.25, 0.375, -0.5, 0.625, -0.75)!r}\n"
            + (
                ""
                if zero
                else "g['initial'].update(kind='data',samples=list(values))\n"
            )
            + "m=copy.deepcopy(MANIFEST);m['resources']=[g];m['uses'][0]['resources']=['first']\n"
            "props=g['prepared']; b=g['bufnum']\n"
            + (
                "init=message('/b_alloc',b,3,2,0,32000)\n"
                if zero
                else "init=message('/b_allocRead',b,props['canonical'],0,-1)\n"
            )
            + "prefix=bundle(0,message('/b_free',b),init,message('/b_write',b,props['snapshot'],'WAV','float',-1,0,0))\n"
            "source_bytes=SOURCE;final_bytes=prefix+SOURCE+bundle(2<<32,message(0))\n"
            "Path(props['canonical']).write_bytes(float_wav(values))\n"
            "Path(props['reference']).write_bytes(struct.pack('<6f',*values))\n"
            + prep_mutation
            + "\n"
            + "(p/'source.osc').write_bytes(source_bytes);Path(final).write_bytes(final_bytes)\n"
            "(p/'source-plan.json').write_text(json.dumps(m))\n"
            'Path(status).write_text("SC_TOOL\\t2\\t"+token+"\\tPREPARED\\t"+frames+"\\t"+rate+"\\t"+channels+"\\n")\n'
        )
        server = root / "fake scsynth"
        server.write_text(
            server.read_text() + "p=Path(sys.argv[2]).parent\nimport json\n"
            "g=json.loads((p/'source-plan.json').read_text())['resources'][0]\n"
            "props=g['prepared']\nPath(props['snapshot']).write_bytes(Path(props['canonical']).read_bytes())\n"
            + server_mutation
            + "\n"
        )
        return args

    def test_resource_success_coverage_history_and_retention(self):
        for zero in (False, True):
            with self.subTest(zero=zero), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                result = self.run_cli(self.resource_fixture(root, zero=zero))
                self.assertEqual(result["exit_code"], 0, result)
                summary = result["resource_evidence"]
                self.assertEqual(summary["verified_generations"], 1)
                self.assertEqual(summary["dependency_coverage"], "trusted-declared")
                self.assertFalse(summary["dependencies_inferred"])
                g = json.loads(Path(summary["manifest"]).read_text())["resources"][0]
                self.assertEqual(
                    json.loads(Path(summary["manifest"]).read_text())["run_id"],
                    result["run_id"],
                )
                self.assertTrue(g["comparison"]["matches"])
                self.assertFalse(g["comparison"]["internal_history_proven"])
                self.assertFalse(g["comparison"]["subsequent_dsp_proven"])
                for role, path in g["prepared"].items():
                    if role in ("snapshot", "canonical", "reference"):
                        self.assertFalse(Path(path).exists())
                        self.assertEqual(g["retention"][role], "removed")

    def test_good_main_and_exit_zero_cannot_hide_bad_snapshot(self):
        cases = [
            (
                "zero-silent-allocation-model",
                "Path(props['snapshot']).write_bytes(Path(props['canonical']).read_bytes()[:-24]+b'\\0'*24)",
                "resource_evidence_mismatch",
            ),
            (
                "wrong-order",
                "raw=Path(props['snapshot']).read_bytes();Path(props['snapshot']).write_bytes(raw[:-24]+raw[-24:][::-1])",
                "resource_evidence_mismatch",
            ),
            (
                "missing",
                "Path(props['snapshot']).unlink()",
                "resource_evidence_missing",
            ),
            (
                "truncated",
                "Path(props['snapshot']).write_bytes(Path(props['snapshot']).read_bytes()[:-1])",
                "resource_evidence_invalid",
            ),
            (
                "server-error",
                "print('FAILURE IN SERVER /s_new missing SynthDef')",
                "nrt_error",
            ),
            (
                "unknown-diagnostic",
                "print('unknown server diagnostic')",
                "nrt_unconfirmed",
            ),
        ]
        for label, mutation, code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                result = self.run_cli(
                    self.resource_fixture(root, server_mutation=mutation)
                )
                self.assertEqual(result["errors"][0]["code"], code, result)
                self.assertEqual(result["exit_code"], 11)
                self.assertEqual(result["artifacts"]["ready"], [])
                self.assertTrue(result["artifacts"]["partial"])
                self.assertFalse((root / "output.wav").exists())
                if code.startswith("resource_evidence"):
                    manifest = json.loads(
                        Path(result["resource_evidence"]["manifest"]).read_text()
                    )
                    comparison = manifest["resources"][0]["comparison"]
                    self.assertFalse(comparison["matches"])
                    self.assertIn("reason", comparison)
                    if code == "resource_evidence_mismatch":
                        self.assertEqual(comparison["measured"]["decoded_samples"], 6)

    def test_bad_preparation_never_runs_nrt(self):
        cases = [
            (
                "canonical-short",
                "Path(props['canonical']).write_bytes(Path(props['canonical']).read_bytes()[:-1])",
            ),
            ("reference-short", "Path(props['reference']).write_bytes(b'\\0'*20)"),
            (
                "stale-before-nrt",
                "Path(props['snapshot']).write_bytes(Path(props['canonical']).read_bytes())",
            ),
            ("foreign-run", "g['prepared']['snapshot']='/tmp/foreign-snapshot.wav'"),
            (
                "duplicate-mapping",
                "other=copy.deepcopy(g);other.update(id='other',bufnum=1);m['resources'].append(other)",
            ),
            ("raw-buffer", "source_bytes=bundle(0,message('/b_allocRead',0,'x',0,-1))"),
            ("numeric-alias", "source_bytes=bundle(0,message(29,0,'x',0,-1))"),
            (
                "nested-completion",
                "from test_score import DEF\nsource_bytes=bundle(0,message('/d_recv',DEF,bundle(0,message(29,0,'x',0,-1))))",
            ),
            ("extra-blob", "source_bytes=bundle(0,message('/c_set',0,b'opaque'))"),
            ("trailing-args", "source_bytes=bundle(0,message(0,123))"),
        ]
        for label, mutation in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                result = self.run_cli(
                    self.resource_fixture(root, prep_mutation=mutation)
                )
                self.assertEqual(result["exit_code"], 2, result)
                self.assertFalse(
                    any(p["stage"] == "nrt" for p in result["diagnostics"]["processes"])
                )
                self.assertEqual(result["artifacts"]["ready"], [])
