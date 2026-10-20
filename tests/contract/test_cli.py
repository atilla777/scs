import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills/supercollider/scripts/sc-tool.py"
SAMPLE = ROOT / "skills/supercollider/assets/minimal-nrt.scd"


class CliTests(unittest.TestCase):
    def invoke(self, args, cwd=None):
        process = subprocess.run(
            [sys.executable, "-B", str(CLI)] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        result = json.loads(process.stdout)
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(result["exit_code"], process.returncode)
        self.assertEqual(process.stderr, "")
        return result

    def test_invalid_request(self):
        result = self.invoke(["render"])
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["errors"][0]["code"], "invalid_input")
        self.assertEqual(result["artifacts"]["ready"], [])

    def test_existing_output_and_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, "out ' ;$\n.wav")
            base = [
                "render",
                "--source",
                str(SAMPLE),
                "--output",
                str(output),
                "--duration",
                "2",
                "--sample-rate",
                "48000",
                "--channels",
                "2",
                "--temp-dir",
                tmp,
                "--diagnostics-dir",
                tmp,
            ]
            missing = self.invoke(base + ["--sclang", str(Path(tmp, "missing"))])
            self.assertEqual(missing["exit_code"], 3)
            self.assertEqual(missing["errors"][0]["code"], "dependency_missing")
            binary = Path(tmp, "not executable")
            binary.write_text("not executable")
            result = self.invoke(base + ["--sclang", str(binary)])
            self.assertEqual(result["errors"][0]["code"], "dependency_unexecutable")
            for dangling in (False, True):
                if dangling:
                    output.symlink_to("missing")
                else:
                    output.write_bytes(b"protected")
                result = self.invoke(base)
                self.assertEqual(result["exit_code"], 14)
                self.assertEqual(result["errors"][0]["code"], "output_exists")
                if dangling:
                    self.assertTrue(output.is_symlink())
                else:
                    self.assertEqual(output.read_bytes(), b"protected")
                output.unlink()
