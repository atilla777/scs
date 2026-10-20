"""Own MIT fixtures; initial-state evidence, never arbitrary DSP proof."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool.sc import validate_source_plan
from test_score import SOURCE, MANIFEST, bundle, message


def generation(identifier="first", at=0, retire=None, bufnum=0):
    return dict(
        id=identifier,
        at=at,
        retire=retire,
        bufnum=bufnum,
        initial=dict(kind="zero", frames=3, channels=2, sample_rate=32000),
        prepared=dict(
            frames=3,
            channels=2,
            sample_rate=32000,
            canonical=f"/run/{identifier}.wav",
            reference=f"/run/{identifier}.f32",
            snapshot=f"/run/{identifier}-snapshot.wav",
        ),
    )


def instrument(resources):
    events = []
    for index, g in enumerate(resources):
        ticks = int(g["at"] * (1 << 32))
        p = g["prepared"]
        init = message(
            "/b_alloc", g["bufnum"], p["frames"], p["channels"], 0, p["sample_rate"]
        )
        events.append(
            (
                ticks,
                1,
                index,
                bundle(
                    ticks,
                    message("/b_free", g["bufnum"]),
                    init,
                    message(
                        "/b_write", g["bufnum"], p["snapshot"], "WAV", "float", -1, 0, 0
                    ),
                ),
            )
        )
        if g["retire"] is not None:
            t = int(g["retire"] * (1 << 32))
            events.append((t, 0, index, bundle(t, message("/b_free", g["bufnum"]))))
    # SOURCE has user events at 0 and 1, terminal at 2.
    from test_score import DEF

    events += [
        (0, 2, 0, bundle(0, message("/d_recv", DEF))),
        (1 << 32, 2, 0, bundle(1 << 32, message("/s_new", "test", 1000, 0, 1))),
        (2 << 32, 3, 0, bundle(2 << 32, message(0))),
    ]
    return b"".join(x[3] for x in sorted(events))


class ResourcePlanTests(unittest.TestCase):
    def test_pinned_generated_numeric_opcodes_are_not_other_buffer_commands(self):
        resources = [generation()]
        p = resources[0]["prepared"]
        # Independently encode the pinned numeric command forms.
        from test_score import DEF

        numeric = bundle(
            0,
            message(32, 0),
            message(28, 0, 3, 2, 0, 32000),
            message(31, 0, p["snapshot"], "WAV", "float", -1, 0, 0),
        )
        numeric += (
            bundle(0, message("/d_recv", DEF))
            + bundle(1 << 32, message("/s_new", "test", 1000, 0, 1))
            + bundle(2 << 32, message(0))
        )
        accepted = False
        try:
            accepted = self.check_plan(resources, final=numeric)["generations"] == 1
        except ValueError:
            pass
        self.assertTrue(
            accepted, "Native b_free=32 and b_write=31 must match pinned reference"
        )
        for free_opcode, write_opcode in [(30, 31), (32, 33)]:
            bad = bundle(
                0,
                message(free_opcode, 0),
                message(28, 0, 3, 2, 0, 32000),
                message(write_opcode, 0, p["snapshot"], "WAV", "float", -1, 0, 0),
            )
            bad += (
                bundle(0, message("/d_recv", DEF))
                + bundle(1 << 32, message("/s_new", "test", 1000, 0, 1))
                + bundle(2 << 32, message(0))
            )
            with self.assertRaises(ValueError):
                self.check_plan(resources, final=bad)

    def test_consumer_before_init_in_same_block_is_not_ready(self):
        # Both are block 751, but the consumer constructor runs first.
        with self.assertRaises(ValueError):
            self.check_plan([generation(at=1.00001)])

    def test_last_use_and_retirement_in_same_block_are_unsafe(self):
        # At 48 kHz these distinct timestamps are both execution block 376.
        resources = [generation(retire=0.50002), generation("second", at=0.50002)]
        uses = [
            dict(anchor=[1, 0], **{"from": 0.5}, through=0.50001, resources=["first"]),
            dict(anchor=[1, 0], **{"from": 1}, through=2, resources=["second"]),
        ]
        with self.assertRaises(ValueError):
            self.check_plan(resources, uses=uses)

    def check_plan(self, resources, uses=None, final=None):
        manifest = copy.deepcopy(MANIFEST)
        manifest["resources"] = resources
        manifest["uses"] = uses or [
            dict(
                anchor=[1, 0], **{"from": 1}, through=2, resources=[resources[-1]["id"]]
            )
        ]
        return validate_source_plan(
            SOURCE,
            instrument(resources) if final is None else final,
            manifest,
            96000,
            48000,
        )

    def test_nonempty_zero_generation_is_validated(self):
        accepted, reason = False, None
        try:
            plan = self.check_plan([generation()])
            accepted = plan["generations"] == 1 and plan["verified_generations"] == 0
        except ValueError as exc:
            reason = str(exc)
        self.assertTrue(accepted, reason)

    def test_scheduled_reuse_and_same_timestamp_order(self):
        resources = [generation(retire=0.5), generation("second", at=0.5)]
        self.assertEqual(self.check_plan(resources)["generations"], 2)
        final = instrument(resources)
        wrong = final.replace(message("/b_free", 0), message("/b_free", 1), 1)
        with self.assertRaises(ValueError):
            self.check_plan(resources, final=wrong)

    def test_malformed_bounds_overlap_and_identity_rejected(self):
        for key, value in [
            ("id", "bad/id"),
            ("bufnum", 1024),
            ("at", -1),
            ("at", float("nan")),
            ("retire", 0),
            ("retire", 3),
        ]:
            g = generation()
            g[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check_plan([g], final=bundle(2 << 32, message(0)))
        for changes in [
            dict(frames=0),
            dict(channels=16384),
            dict(sample_rate=16777217),
            dict(frames=1 << 31),
            dict(sample_rate=True),
        ]:
            g = generation()
            g["initial"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check_plan([g])
        for resources in [
            [generation(), generation("second", at=0.5)],
            [generation(retire=0.50002), generation("second", at=0.50001)],
            [generation(retire=0.5), generation(at=0.5)],
        ]:
            with self.assertRaises(ValueError):
                self.check_plan(resources)

    def test_lifetime_checks_and_duplicate_snapshot(self):
        resources = [generation(retire=1.5)]
        with self.assertRaises(ValueError):
            self.check_plan(resources)
        resources = [generation(retire=0.5), generation("second", at=0.5)]
        resources[1]["prepared"]["snapshot"] = resources[0]["prepared"]["snapshot"]
        with self.assertRaises(ValueError):
            self.check_plan(resources)
