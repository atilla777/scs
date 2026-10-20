"""Real SC external Buffer integration; own tiny MIT sample fixtures."""

import json
import hashlib
import math
import os
import struct
import stat
import tempfile
import unittest
import wave
from pathlib import Path
import test_headless

SOURCE = r"""{ |ctx|
    var def = SynthDef(\resourceFixture, {
        Out.ar(0, PlayBuf.ar(2, 0, BufRateScale.kr(0), loop: 1) * 0.1)
    });
    (
        contract: "scs-nrt-source/2",
        score: Score([
            [0, [\d_recv, def.asBytes]],
            [0.01, [\s_new, \resourceFixture, 1000, 0, 1]],
            [0.4, [\n_free, 1000]],
            [0.51, [\s_new, \resourceFixture, 1001, 0, 1]]
        ]),
        resources: [
            (id: "data", bufnum: 0, at: 0, retire: 0.5,
                initial: (kind: "data", frames: 3, channels: 2, sample_rate: 32000,
                    samples: FloatArray[0.125, -0.25, 0.375, -0.5, 0.625, -0.75])),
            (id: "zero", bufnum: 0, at: 0.5, retire: nil,
                initial: (kind: "zero", frames: 3, channels: 2, sample_rate: 22050))
        ],
        uses: [(anchor: [2, 0], from: 0.01, through: 0.4, resources: ["data"]),
            (anchor: [4, 0], from: 0.51, through: ctx[\duration], resources: ["zero"])]
    )
}"""


@unittest.skipUnless(
    os.environ.get("SCS_REAL_TESTS") == "1", "explicit real SC test opt-in"
)
class ResourceHeadlessTests(unittest.TestCase):
    def test_real_resource_fixed_seed_repeat(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-resource-repeat-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            source = root / "repeat.scd"
            source.write_text(SOURCE)
            samples = []
            for index in range(2):
                output = root / f"repeat-{index}.wav"
                result = self.invoke(source, output, root)
                self.assertEqual(result["exit_code"], 0, result)
                self.assertEqual(result["measured"]["frames"], 96064)
                self.assertEqual(result["resource_evidence"]["verified_generations"], 2)
                with wave.open(str(output), "rb") as audio:
                    raw = audio.readframes(audio.getnframes())
                samples.append([x[0] / 32768 for x in struct.iter_unpack("<h", raw)])
            self.assertEqual(len(samples[0]), len(samples[1]))
            rmse = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(*samples)) / len(samples[0])
            )
            self.assertLessEqual(rmse, 2 / 32768)
            for channel in (0, 1):
                rms = [
                    math.sqrt(
                        sum(x * x for x in values[channel::2]) / len(values[channel::2])
                    )
                    for values in samples
                ]
                self.assertLessEqual(abs(rms[0] - rms[1]), 1e-4)

    def test_real_same_timestamp_consumers_follow_initial_snapshots(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-same-time-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            text = SOURCE.replace("0.01", "0.0").replace("0.51", "0.5")
            source = root / "same-time.scd"
            source.write_text(text)
            result = self.invoke(source, root / "out.wav", root)
            self.assertEqual(result["exit_code"], 0, result)
            self.assertEqual(result["resource_evidence"]["verified_generations"], 2)

    def test_real_invalid_initial_state_and_symbol_id_fail_before_nrt(self):
        cases = [
            ("nonfinite", SOURCE.replace("0.125, -0.25", "inf, -0.25")),
            ("symbol-id", SOURCE.replace('id: "data"', "id: \\data")),
            (
                "missing-def",
                SOURCE.replace(
                    "[0, [\\d_recv, def.asBytes]]",
                    "[0, [\\d_recv, def.asBytes], [\\d_free, \\resourceFixture]]",
                ),
            ),
        ]
        for label, text in cases:
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory(
                    prefix="scs-invalid-resource-", dir="/tmp/opencode"
                ) as name,
            ):
                root = Path(name)
                source = root / "bad.scd"
                source.write_text(text)
                result = self.invoke(source, root / "out.wav", root)
                self.assertEqual(result["exit_code"], 2, result)
                self.assertFalse(
                    any(p["stage"] == "nrt" for p in result["diagnostics"]["processes"])
                )
                self.assertEqual(result["artifacts"]["ready"], [])

    def test_real_short_file_input_rejected_before_nrt(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-short-resource-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            sample = root / "input.wav"
            with wave.open(str(sample), "wb") as f:
                f.setparams((2, 2, 32000, 0, "NONE", ""))
                f.writeframes(b"\0" * 12)
            sample.write_bytes(sample.read_bytes()[:-4])
            old = '(kind: "data", frames: 3, channels: 2, sample_rate: 32000,\n                    samples: FloatArray[0.125, -0.25, 0.375, -0.5, 0.625, -0.75])'
            source = root / "short.scd"
            source.write_text(
                SOURCE.replace(old, '(kind: "file", path: "input.wav", frames: 3)')
            )
            result = self.invoke(source, root / "out.wav", root)
            self.assertEqual(result["exit_code"], 2, result)
            self.assertFalse(
                any(p["stage"] == "nrt" for p in result["diagnostics"]["processes"])
            )

    def test_real_private_file_copy_and_server_error_with_normal_wav(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-file-error-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            sample = root / "input.wav"
            with wave.open(str(sample), "wb") as f:
                f.setparams((2, 2, 32000, 0, "NONE", ""))
                f.writeframes(
                    struct.pack("<6h", 4096, -8192, 12288, -16384, 20480, -24576)
                )
            sample.chmod(0o644)
            old = '(kind: "data", frames: 3, channels: 2, sample_rate: 32000,\n                    samples: FloatArray[0.125, -0.25, 0.375, -0.5, 0.625, -0.75])'
            text = SOURCE.replace(old, '(kind: "file", path: "input.wav", frames: 3)')
            text = text.replace(
                "[0.51, [\\s_new, \\resourceFixture, 1001, 0, 1]]",
                "[0.51, [\\s_new, \\resourceFixture, 1001, 0, 1]], [1.5, [\\n_set, 99999, \\amp, 0.1]]",
            )
            source = root / "server-error.scd"
            source.write_text(text)
            result = self.invoke(source, root / "out.wav", root)
            self.assertEqual(result["exit_code"], 11, result)
            self.assertEqual(result["errors"][0]["code"], "nrt_error", result)
            self.assertEqual(result["artifacts"]["ready"], [])
            with wave.open(result["artifacts"]["partial"][0]["path"], "rb") as f:
                self.assertEqual(f.getnframes(), 96064)
            manifest = json.loads(
                Path(result["resource_evidence"]["manifest"]).read_text()
            )
            staged = Path(manifest["resources"][0]["input"]["staged"])
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
            self.assertEqual(staged.read_bytes(), sample.read_bytes())

    def test_real_dsp_mutation_is_not_claimed_as_later_dsp_proof(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-mutate-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            text = SOURCE.replace(
                "Out.ar(0,",
                "BufWr.ar(DC.ar([0.9, -0.9]), 0, Phasor.ar(0, 1, 0, BufFrames.kr(0))); Out.ar(0,",
            )
            source = root / "mutate.scd"
            source.write_text(text)
            result = self.invoke(source, root / "out.wav", root)
            self.assertEqual(result["exit_code"], 0, result)
            manifest = json.loads(
                Path(result["resource_evidence"]["manifest"]).read_text()
            )
            for g in manifest["resources"]:
                self.assertTrue(g["comparison"]["matches"])
                self.assertFalse(g["comparison"]["subsequent_dsp_proven"])
                self.assertFalse(g["comparison"]["internal_history_proven"])

    invoke = test_headless.HeadlessTests.invoke

    def test_real_file_range_channel_reorder_repeat(self):
        for selection in ([1, 0], [1, 0, 1]):
            with (
                self.subTest(selection=selection),
                tempfile.TemporaryDirectory(
                    prefix="scs-file-", dir="/tmp/opencode"
                ) as name,
            ):
                root = Path(name)
                samples = (0.125, -0.25, 0.375, -0.5, 0.625, -0.75, 0.875, -1.0)
                raw = struct.pack("<8f", *samples)
                fmt = struct.pack("<HHIIHH", 3, 2, 32000, 256000, 8, 32)
                body = (
                    b"WAVEfmt "
                    + struct.pack("<I", 16)
                    + fmt
                    + b"data"
                    + struct.pack("<I", len(raw))
                    + raw
                )
                sample = root / "sample '$;\n.wav"
                sample.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
                initial = (
                    '(kind: "file", path: '
                    + json.dumps(sample.name)
                    + ", start_frame: 1, frames: 2, channels: "
                    + str(selection)
                    + ")"
                )
                old = '(kind: "data", frames: 3, channels: 2, sample_rate: 32000,\n                    samples: FloatArray[0.125, -0.25, 0.375, -0.5, 0.625, -0.75])'
                source = root / "file.scd"
                text = SOURCE.replace(old, initial)
                text = text.replace("PlayBuf.ar(2,", f"PlayBuf.ar({len(selection)},")
                text = text.replace(
                    "channels: 2, sample_rate: 22050",
                    f"channels: {len(selection)}, sample_rate: 22050",
                )
                self.assertNotEqual(text, SOURCE)
                source.write_text(text)
                result = self.invoke(source, root / "out.wav", root)
                self.assertEqual(result["status"], "success", result)
                manifest = json.loads(
                    Path(result["resource_evidence"]["manifest"]).read_text()
                )
                g = manifest["resources"][0]
                expected = [
                    samples[frame * 2 + c] for frame in (1, 2) for c in selection
                ]
                digest = hashlib.sha256(
                    struct.pack("<" + "f" * len(expected), *expected)
                ).hexdigest()
                self.assertEqual(g["comparison"]["measured"]["sample_sha256"], digest)
                self.assertEqual(g["comparison"]["measured"]["frames"], 2)
                self.assertEqual(
                    g["comparison"]["measured"]["channels"], len(selection)
                )
                self.assertEqual(
                    sample.read_bytes(), b"RIFF" + struct.pack("<I", len(body)) + body
                )

    def test_real_data_zero_scheduled_reuse_full_state(self):
        with tempfile.TemporaryDirectory(
            prefix="scs-resource-", dir="/tmp/opencode"
        ) as name:
            root = Path(name)
            source = root / "resource.scd"
            source.write_text(SOURCE)
            result = self.invoke(source, root / "out.wav", root)
            self.assertEqual(result["status"], "success", result)
            self.assertEqual(result["measured"]["frames"], 96064)
            self.assertEqual(result["resource_evidence"]["generations"], 2)
            self.assertEqual(result["resource_evidence"]["verified_generations"], 2)
            manifest = json.loads(
                Path(result["resource_evidence"]["manifest"]).read_text()
            )
            for g in manifest["resources"]:
                self.assertTrue(g["comparison"]["matches"])
                self.assertEqual(g["comparison"]["measured"]["decoded_samples"], 6)
