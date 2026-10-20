"""Opt-in real SC gate: no GUI, host audio devices, network or realtime state."""

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills/supercollider/scripts/sc-tool.py"
SAMPLE = ROOT / "skills/supercollider/assets/minimal-nrt.scd"


@unittest.skipUnless(
    os.environ.get("SCS_REAL_TESTS") == "1", "explicit real SC test opt-in"
)
class HeadlessTests(unittest.TestCase):
    def test_real_caller_relative_path_matches_absolute_control(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-path-", dir="/tmp/opencode"
        ) as name:
            tmp = Path(name)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            for binary in ["sclang", "scsynth"]:
                (bin_dir / binary).symlink_to("/usr/bin/" + binary)
            relative = self.invoke(
                SAMPLE, tmp / "relative.wav", tmp, path="bin:/usr/bin:/bin"
            )
            absolute = self.invoke(
                SAMPLE, tmp / "absolute.wav", tmp, path=str(bin_dir) + ":/usr/bin:/bin"
            )
            self.assertEqual(absolute["status"], "success", absolute)
            self.assertEqual(relative["status"], "success", relative)
            self.assertEqual(relative["measured"]["frames"], 96064)
            self.assertEqual(
                relative["measured"]["sha256"], absolute["measured"]["sha256"]
            )

    def test_real_sequential_usage_intervals(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-intervals-", dir="/tmp/opencode"
        ) as name:
            tmp = Path(name)
            source = tmp / "intervals.scd"
            text = SAMPLE.read_text().replace(
                "uses: [(anchor: [2, 0], from: 0.01, through: ctx[\\duration], resources: [])]",
                "uses: [(anchor: [2, 0], from: 0.01, through: 1.0, resources: []), "
                "(anchor: [2, 0], from: 1.0, through: ctx[\\duration], resources: [])]",
            )
            self.assertNotEqual(text, SAMPLE.read_text())
            source.write_text(text)
            result = self.invoke(source, tmp / "intervals.wav", tmp)
            self.assertEqual(result["status"], "success", result)
            self.assertEqual(result["measured"]["frames"], 96064)
            self.assertEqual(result["resource_evidence"]["verified_generations"], 0)

    def test_real_source_hang_deadline(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-hang-", dir="/tmp/opencode"
        ) as name:
            tmp = Path(name)
            source = tmp / "hang.scd"
            source.write_text("{ |ctx| loop {} }")
            result = self.invoke(source, tmp / "never.wav", tmp, ["--timeout", "1"])
            self.assertEqual(result["exit_code"], 24, result)
            self.assertEqual(result["stage"], "prepare")
            self.assertFalse(list(tmp.glob("scs-work-*")))
            self.assertEqual(result["artifacts"]["ready"], [])

    def test_real_native_variant(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-variant-", dir="/tmp/opencode"
        ) as name:
            tmp = Path(name)
            source = tmp / "variant.scd"
            text = SAMPLE.read_text().replace(
                "}).asBytes", "}, variants: (v: [])).asBytes"
            )
            text = text.replace("\\s_new, \\scsMinimal,", '\\s_new, "scsMinimal.v",')
            source.write_text(text)
            result = self.invoke(source, tmp / "variant.wav", tmp)
            self.assertEqual(result["status"], "success", result)

    def invoke(self, source, output, tmp, extra=(), path="/usr/bin:/bin"):
        env = {
            "PATH": path,
            "HOME": str(tmp / "caller-home"),
            "QT_QPA_PLATFORM": "offscreen",
            "TMPDIR": str(tmp),
        }
        env["HOME"] and Path(env["HOME"]).mkdir(exist_ok=True)
        args = [
            "bwrap",
            "--unshare-net",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--dir",
            "/dev/snd",
            "--bind",
            str(tmp),
            str(tmp),
            "--chdir",
            str(tmp),
            "--",
            sys.executable,
            "-B",
            str(CLI),
            "render",
            "--source",
            str(source),
            "--output",
            str(output),
            "--duration",
            "2",
            "--sample-rate",
            "48000",
            "--channels",
            "2",
            "--temp-dir",
            str(tmp),
            "--diagnostics-dir",
            str(tmp),
        ]
        process = subprocess.run(
            args + list(extra), capture_output=True, text=True, env=env, timeout=20
        )
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, result["exit_code"])
        self.assertEqual(process.stderr, "")
        if os.environ.get("SCS_EVIDENCE_DIR"):
            target = Path(os.environ["SCS_EVIDENCE_DIR"]) / result["run_id"]
            shutil.copytree(result["diagnostics"]["directory"], target)
            (target / "cli.stdout.json").write_text(process.stdout)
            (target / "cli.stderr.log").write_text(process.stderr)
        return result

    def test_real_minimal_repeat_and_source_failures(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-real-", dir="/tmp/opencode"
        ) as name:
            tmp = Path(name)
            results, samples = [], []
            source = tmp / "source '$;\n.scd"
            source.write_bytes(SAMPLE.read_bytes())
            original = source.read_bytes()
            for i in range(2):
                output = tmp / f"out '{i};$\n.wav"
                result = self.invoke(source, output, tmp)
                self.assertEqual(result["status"], "success", result)
                self.assertEqual(result["measured"]["frames"], 96064)
                self.assertEqual(result["resource_evidence"]["generations"], 0)
                self.assertEqual(result["resource_evidence"]["verified_generations"], 0)
                self.assertEqual(len(result["artifacts"]["ready"]), 1)
                with wave.open(str(output), "rb") as audio:
                    self.assertEqual(audio.getparams()[:3], (2, 2, 48000))
                    audio.setpos(4800)
                    raw = audio.readframes(86400)
                values = [x[0] / 32768 for x in struct.iter_unpack("<h", raw)]
                for channel in (values[::2], values[1::2]):
                    rms = math.sqrt(sum(x * x for x in channel) / len(channel))
                    self.assertAlmostEqual(rms, 0.1 / math.sqrt(2), delta=0.002)
                    projection = abs(
                        sum(
                            x * math.cos(2 * math.pi * 480 * j / 48000)
                            for j, x in enumerate(channel)
                        )
                    ) / len(channel)
                    sine = abs(
                        sum(
                            x * math.sin(2 * math.pi * 480 * j / 48000)
                            for j, x in enumerate(channel)
                        )
                    ) / len(channel)
                    self.assertAlmostEqual(
                        math.hypot(projection, sine) * 2, 0.1, delta=0.002
                    )
                samples.append(values)
                results.append(result)
            self.assertEqual(source.read_bytes(), original)
            rmse = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(*samples)) / len(samples[0])
            )
            self.assertLessEqual(rmse, 2 / 32768)
            for offset in [0, 1]:
                rms = [
                    math.sqrt(
                        sum(x * x for x in values[offset::2]) / len(values[offset::2])
                    )
                    for values in samples
                ]
                self.assertLessEqual(abs(rms[0] - rms[1]), 1e-4)
            for kind, text, expected in [
                ("wrong", "42", "source_contract"),
                ("runtime", '{ |ctx| Error("fixture failure").throw }', "sclang_error"),
                ("syntax", "{ broken +++", "sclang_error"),
                (
                    "missing",
                    '{ |ctx| (contract:"scs-nrt-source/2",score:Score([[0,[\\s_new,\\missing,1000,0,1]]]),resources:[],uses:[(anchor:[1,0],from:0,through:2,resources:[])]) }',
                    "source_contract",
                ),
                (
                    "resources",
                    original.decode().replace(
                        "resources: [],", 'resources: [(id:"unsupported")],', 1
                    ),
                    "source_contract",
                ),
            ]:
                bad = tmp / (kind + ".scd")
                bad.write_text(text)
                result = self.invoke(bad, tmp / (kind + ".wav"), tmp)
                self.assertNotEqual(result["status"], "success")
                self.assertEqual(result["errors"][0]["code"], expected, result)
                self.assertEqual(result["artifacts"]["ready"], [])
