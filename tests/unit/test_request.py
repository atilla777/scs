"""Public request and independent timing examples from design v2."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool import render


class RequestTests(unittest.TestCase):
    def test_minimum_frames_and_riff_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "source.scd").write_text("{}")
            base = [
                "render",
                "--source",
                "source.scd",
                "--output",
                "out.wav",
                "--duration",
                "0.0000625",
                "--sample-rate",
                "8000",
                "--channels",
                "1",
            ]
            request = render.validate_request(base + ["--json"], cwd=tmp)
            self.assertEqual(request["target_frames"], 1)
            self.assertEqual(request["expected_frames"], 64)
            # Last representable block-aligned RIFF output with a header reserve.
            limit = ((2**32 - 1 - 4096) // 2 // 64) * 64
            frame = limit
            while render.timing(frame, 48000)["expected_frames"] > limit:
                frame -= 1
            base[base.index("--sample-rate") + 1] = "48000"
            from decimal import Decimal

            base[base.index("--duration") + 1] = str(Decimal(frame) / 48000)
            request = render.validate_request(base, cwd=tmp)
            self.assertEqual(request["expected_frames"], limit)
            base[base.index("--duration") + 1] = str(Decimal(frame + 1) / 48000)
            with self.assertRaises(ValueError):
                render.validate_request(base, cwd=tmp)

    def test_reject_bad_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "source.scd").write_text("{}")
            base = [
                "render",
                "--source",
                "source.scd",
                "--output",
                "out.wav",
                "--duration",
                "2",
                "--sample-rate",
                "48000",
                "--channels",
                "2",
            ]
            cases = [
                base + ["--channels", "2"],
                base + ["--unknown", "x"],
                base[:-2],
                base + ["--format", "aiff"],
            ]
            for key, value in [
                ("duration", "NaN"),
                ("duration", "0"),
                ("duration", "86401"),
                ("duration", "0.00000001"),
                ("channels", "0"),
                ("channels", "33"),
                ("sample-rate", "7999"),
                ("sample-rate", "192001"),
                ("seed", "-1"),
                ("seed", "2147483648"),
                ("timeout", "0"),
                ("timeout", "86401"),
            ]:
                args = base.copy()
                if "--" + key in args:
                    args[args.index("--" + key) + 1] = value
                else:
                    args += ["--" + key, value]
                cases.append(args)
            for args in cases:
                with self.subTest(args=args):
                    rejected = False
                    try:
                        render.validate_request(args, cwd=tmp)
                    except ValueError:
                        rejected = True
                    self.assertTrue(rejected, "invalid request must be rejected")

    def test_timing_regressions_and_terminal_validation(self):
        self.assertEqual(render.timing(192000000, 192000)["expected_frames"], 192000128)
        for rate in [8000, 48000, 192000]:
            q = 64 * (1 << 32) // rate
            for ticks in [0, 1, q - 1, q, q + 1, 2 * q, 2 * q + 1]:
                blocks, clock = 1, q
                while clock < ticks:
                    blocks += 1
                    clock += q
                self.assertEqual(
                    render.timing(1, rate, ticks)["expected_frames"], blocks * 64
                )

    def test_required_request_and_rounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "source.scd").write_text("{}")
            request = render.validate_request(
                [
                    "render",
                    "--source",
                    "source.scd",
                    "--output",
                    "out.wav",
                    "--duration",
                    "2",
                    "--sample-rate",
                    "48000",
                    "--channels",
                    "2",
                ],
                cwd=tmp,
            )
            self.assertIsNotNone(request, "valid render request must be normalized")
            self.assertEqual(request["target_frames"], 96000)
            self.assertEqual(request["expected_frames"], 96064)
            self.assertEqual(request["source"], str(Path(tmp, "source.scd")))
            self.assertEqual(request["seed"], 0)


if __name__ == "__main__":
    unittest.main()
