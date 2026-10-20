import struct
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool import wav, sc


def float_wav(values, channels=2, rate=32000):
    payload = struct.pack("<" + "f" * len(values), *values)
    fmt = struct.pack(
        "<HHIIHH", 3, channels, rate, rate * channels * 4, channels * 4, 32
    )
    body = (
        b"WAVEfmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", len(payload))
        + payload
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


class FloatResourceTests(unittest.TestCase):
    def test_snapshot_deadline_is_not_invalid_audio(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as name:
            snapshot = Path(name) / "snapshot.wav"
            snapshot.write_bytes(float_wav((0.125, -0.25)))

            def deadline():
                raise TimeoutError("snapshot deadline exceeded")

            with self.assertRaisesRegex(TimeoutError, "snapshot deadline"):
                wav.read_buffer_snapshot(snapshot, deadline)

    def test_stable_input_read_may_update_atime(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            original = root / "original.wav"
            original.write_bytes(b"fixed staged source bytes")
            staged = root / "resource-0.input"
            staged.write_bytes(original.read_bytes())
            canonical = root / "resource-0.canonical.wav"
            canonical.write_bytes(float_wav((0.125, -0.25, 0.375, -0.5, 0.625, -0.75)))
            reference = root / "resource-0.reference.f32"
            reference.write_bytes(
                struct.pack("<6f", 0.125, -0.25, 0.375, -0.5, 0.625, -0.75)
            )
            props = dict(
                frames=3,
                channels=2,
                sample_rate=32000,
                canonical=str(canonical),
                reference=str(reference),
                snapshot=str(root / "resource-0.snapshot.wav"),
            )
            plan = dict(
                resources=[
                    dict(initial=dict(kind="file", path=str(original)), prepared=props)
                ]
            )
            info = original.stat()
            manifest = dict(
                staged_inputs=[
                    dict(
                        original=str(original),
                        staged=str(staged),
                        size=info.st_size,
                        mtime=int(info.st_mtime),
                    )
                ]
            )
            actual_stat = Path.stat
            calls = 0

            def strict_atime(path, *args, **kwargs):
                nonlocal calls
                result = actual_stat(path, *args, **kwargs)
                if path == original:
                    calls += 1
                    if calls > 1:
                        fields = {
                            key: getattr(result, key)
                            for key in (
                                "st_dev",
                                "st_ino",
                                "st_mode",
                                "st_size",
                                "st_mtime",
                                "st_mtime_ns",
                                "st_ctime_ns",
                            )
                        }
                        return SimpleNamespace(**fields, st_atime=result.st_atime + 1)
                return result

            accepted = False
            with mock.patch.object(Path, "stat", strict_atime):
                try:
                    sc.read_canonical_resource(plan, manifest, root)
                    accepted = True
                except ValueError:
                    pass
            self.assertTrue(
                accepted,
                "A read-only atime update must not be treated as source modification",
            )

    def test_full_float32_state_not_header_hash_or_epsilon(self):
        self.assertTrue(
            callable(getattr(wav, "read_buffer_snapshot", None)),
            "Full float32 snapshot seam absent",
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            reference, snapshot = root / "ref.f32", root / "snapshot.wav"
            expected = dict(frames=3, channels=2, sample_rate=32000)
            values = (0.125, -0.25, 0.375, -0.5, 0.625, -0.0)
            reference.write_bytes(struct.pack("<6f", *values))
            snapshot.write_bytes(float_wav(values))
            measured = wav.read_buffer_snapshot(snapshot)
            self.assertEqual(measured["decoded_samples"], 6)
            self.assertTrue(
                wav.compare_resource_state(reference, snapshot, expected)["matches"]
            )
            for wrong in [(0.0,) * 6, values[::-1], values[:-1] + (1e-10,)]:
                snapshot.write_bytes(float_wav(wrong))
                with self.assertRaises(ValueError):
                    wav.compare_resource_state(reference, snapshot, expected)
            snapshot.write_bytes(float_wav(values[:-1] + (0.0,)))
            self.assertTrue(
                wav.compare_resource_state(reference, snapshot, expected)["matches"]
            )
            for raw in [
                float_wav(values)[:-1],
                float_wav(values, channels=1),
                float_wav(values[:-1] + (float("nan"),)),
                float_wav(values[:-1] + (float("inf"),)),
            ]:
                snapshot.write_bytes(raw)
                with self.assertRaises(ValueError):
                    wav.compare_resource_state(reference, snapshot, expected)
            snapshot.unlink()
            with self.assertRaises(ValueError):
                wav.compare_resource_state(reference, snapshot, expected)

    def test_short_reference_and_no_symlink(self):
        self.assertTrue(
            callable(getattr(wav, "read_buffer_snapshot", None)),
            "Float32 reader absent",
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            reference, snapshot = root / "ref", root / "snap"
            snapshot.write_bytes(float_wav((0.0,) * 6))
            reference.write_bytes(b"\0" * 20)
            with self.assertRaises(ValueError):
                wav.compare_resource_state(
                    reference, snapshot, dict(frames=3, channels=2, sample_rate=32000)
                )
            alias = root / "alias"
            alias.symlink_to(snapshot)
            with self.assertRaises(ValueError):
                wav.read_buffer_snapshot(alias)
