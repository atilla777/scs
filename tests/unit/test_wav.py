import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool.wav import read_wav
from scs_tool.render import compare_audio


class WavTests(unittest.TestCase):
    def test_comparison_is_exact(self):
        request = {"sample_rate": 48000, "channels": 2}
        effective = {"expected_frames": 96064}
        measured = {"sample_rate": 48000, "channels": 2, "frames": 96064}
        self.assertTrue(compare_audio(request, effective, measured))
        for key, value in [
            ("frames", 96063),
            ("frames", 96065),
            ("sample_rate", 44100),
            ("channels", 1),
        ]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    compare_audio(request, effective, {**measured, key: value})

    def test_full_decode_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "tiny.wav")
            with wave.open(str(path), "wb") as stream:
                stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
                stream.writeframes(struct.pack("<hhhh", -32768, 32767, 0, 100))
            measured = read_wav(path)
            self.assertIsNotNone(measured, "PCM16 must be fully measured")
            self.assertEqual(measured["frames"], 2)
            self.assertEqual(measured["sample_rate"], 48000)
            self.assertEqual(measured["channels"], 2)
            self.assertEqual(measured["decoded_samples"], 4)
            original = path.read_bytes()
            for bad in [
                b"",
                b"BAD!" + original[4:],
                original[:-1],
                original + b"trailing",
            ]:
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    read_wav(path)


if __name__ == "__main__":
    unittest.main()
