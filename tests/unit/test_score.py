import copy
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool.sc import validate_source_plan


def string(value):
    data = value.encode() + b"\0"
    return data + b"\0" * (-len(data) % 4)


def message(command, *args):
    tags, payload = "", b""
    for arg in args:
        if isinstance(arg, int):
            tags += "i"
            payload += struct.pack(">i", arg)
        elif isinstance(arg, bytes):
            tags += "b"
            payload += struct.pack(">I", len(arg)) + arg + b"\0" * (-len(arg) % 4)
        else:
            tags += "s"
            payload += string(arg)
    address = (
        struct.pack(">i", command) if isinstance(command, int) else string(command)
    )
    return address + string("," + tags) + payload


def bundle(ticks, *messages):
    payload = b"#bundle\0" + struct.pack(">Q", ticks)
    payload += b"".join(struct.pack(">I", len(msg)) + msg for msg in messages)
    return struct.pack(">I", len(payload)) + payload


# Own tiny valid SCgf v2 fixture; no third-party synth graph or samples.
DEF = (
    b"SCgf"
    + struct.pack(">ih", 2, 1)
    + b"\x04test"
    + struct.pack(">iiiih", 0, 0, 0, 0, 0)
)
SOURCE = bundle(0, message("/d_recv", DEF)) + bundle(
    1 << 32, message("/s_new", "test", 1000, 0, 1)
)
FINAL = SOURCE + bundle(2 << 32, message(0))
MANIFEST = {
    "contract": "scs-nrt-source/2",
    "resources": [],
    "uses": [{"anchor": [1, 0], "from": 1, "through": 2, "resources": []}],
}


class ScoreTests(unittest.TestCase):
    def test_sequential_usage_intervals_share_one_creation_anchor(self):
        first = {"anchor": [1, 0], "from": 1, "through": 1.5, "resources": []}
        later = {"anchor": [1, 0], "from": 1.5, "through": 2, "resources": []}
        for intervals in ([first, later], [later, first]):
            with self.subTest(intervals=intervals):
                accepted, reason = False, None
                try:
                    accepted = (
                        validate_source_plan(
                            SOURCE, FINAL, {**MANIFEST, "uses": intervals}, 96000, 48000
                        )
                        is not None
                    )
                except ValueError as exc:
                    reason = str(exc)
                self.assertTrue(
                    accepted, f"valid sequential intervals rejected: {reason}"
                )

    def test_sequential_intervals_still_require_creation_coverage(self):
        later = {"anchor": [1, 0], "from": 1.5, "through": 2, "resources": []}
        with self.assertRaises(ValueError):
            validate_source_plan(
                SOURCE, FINAL, {**MANIFEST, "uses": [later]}, 96000, 48000
            )

    def test_native_variants_and_free_availability(self):
        blob = DEF[:-2] + struct.pack(">h", 1) + b"\x06test.v"
        for free, name in [("absent", "test.v"), ("test.v", "test")]:
            with self.subTest(free=free):
                source = bundle(0, message("/d_recv", blob), message("/d_free", free))
                source += bundle(1 << 32, message("/s_new", name, 1000, 0, 1))
                accepted = False
                try:
                    accepted = (
                        validate_source_plan(
                            source,
                            source + bundle(2 << 32, message(0)),
                            MANIFEST,
                            96000,
                            48000,
                        )
                        is not None
                    )
                except ValueError:
                    pass
                self.assertTrue(accepted, "SCgf variant names are full native names")
        for free, name in [("test", "test.v"), ("test.v", "test.v")]:
            source = bundle(0, message("/d_recv", blob), message("/d_free", free))
            source += bundle(1 << 32, message("/s_new", name, 1000, 0, 1))
            with self.assertRaises(ValueError):
                validate_source_plan(
                    source, source + bundle(2 << 32, message(0)), MANIFEST, 96000, 48000
                )

    def test_native_blob_alignment_bytes_are_not_a_completion(self):
        raw = message("/d_recv", DEF)
        pad = -len(DEF) % 4
        self.assertGreater(pad, 0)
        raw = raw[:-pad] + b"X" * pad
        source = bundle(0, raw) + bundle(1 << 32, message("/s_new", "test", 1000, 0, 1))
        accepted = False
        try:
            plan = validate_source_plan(
                source, source + bundle(2 << 32, message(0)), MANIFEST, 96000, 48000
            )
            accepted = plan is not None
        except ValueError:
            pass
        self.assertTrue(accepted, "SC native blob alignment bytes are not OSC payload")

    def test_binary_plan(self):
        plan = validate_source_plan(SOURCE, FINAL, MANIFEST, 96000, 48000)
        self.assertIsNotNone(plan, "valid native Score must be verified")
        self.assertEqual(plan["terminal_osc_ticks"], 2 << 32)
        self.assertEqual(plan["generations"], 0)

    def test_forbidden_malformed_and_missing_def(self):
        bad_sources = [
            bundle(0, message("/b_alloc", 0, 10, 1)),
            bundle(0, message(29, 0, "sample.wav", 0, -1)),
            bundle(0, message("/quit")),
            SOURCE[:-1],
            SOURCE + b"junk",
            bundle(0, message("/d_recv", DEF, b"hidden completion")),
            bundle(0, message("/d_recv", b"SCgfbroken")),
            bundle(0, message("/s_new", "missing", 1000, 0, 1)),
            bundle(0, message("/g_new", 1, 0)),
            bundle(0, message("/c_set", 0, b"opaque")),
        ]
        for source in bad_sources:
            rejected = False
            try:
                validate_source_plan(
                    source, source + bundle(2 << 32, message(0)), MANIFEST, 96000, 48000
                )
            except ValueError:
                rejected = True
            self.assertTrue(rejected, repr(source))

    def test_declarations_anchors_and_instrumentation(self):
        manifests = []
        for key, value in [
            ("resources", [{}]),
            ("resources", None),
            ("uses", []),
            ("contract", "scs-nrt-source/1"),
        ]:
            manifest = copy.deepcopy(MANIFEST)
            manifest[key] = value
            manifests.append(manifest)
        for key, value in [
            ("anchor", [0, 0]),
            ("anchor", [-1, 0]),
            ("from", 2),
            ("through", 3),
            ("resources", ["hidden"]),
        ]:
            manifest = copy.deepcopy(MANIFEST)
            manifest["uses"][0][key] = value
            manifests.append(manifest)
        for manifest in manifests:
            rejected = False
            try:
                validate_source_plan(SOURCE, FINAL, manifest, 96000, 48000)
            except ValueError:
                rejected = True
            self.assertTrue(rejected, repr(manifest))
        for final in [
            SOURCE,
            FINAL[:-1],
            SOURCE + bundle(3 << 32, message(0)),
            FINAL + bundle(2 << 32, message("/c_set", 0, 1)),
        ]:
            with self.assertRaises(ValueError):
                validate_source_plan(SOURCE, final, MANIFEST, 96000, 48000)
