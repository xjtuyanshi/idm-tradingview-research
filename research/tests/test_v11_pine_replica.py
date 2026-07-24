"""Behavioral tests for the frozen-Pine replica.

Each test targets a semantic where the frozen Pine differs from the legacy
``v11_oracle`` (see research/reports/IDM_V11_TAKEOVER_AUDIT_2026-07-21.md,
section B).  The replica must reproduce the *Pine* behavior, including quirks.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

RESEARCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_DIR))

from v11_pine_replica import (  # noqa: E402
    Bar,
    BLOCK_SPACE,
    EVENT_REVERSE,
    EVENT_STOP,
    EVENT_T1,
    EVENT_T2,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    ReplicaConfig,
    ROLE_ADD,
    ROLE_REVERSE,
    SETUP_BREAKOUT,
    SETUP_IGNITION,
    SETUP_LEVEL_REJECTION,
    SIDE_LONG,
    SIDE_SHORT,
    V11PineReplica,
)

BASE_MS = 1_700_000_000_000
M3 = 180_000
M10 = 600_000
DAY = 86_400_000

CFG = ReplicaConfig.from_contract(mintick=0.01)


def bar3(index: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(BASE_MS + (index + 1) * M3, o, h, low, c)


def quiet_warmup(n: int = 55) -> list[Bar]:
    """Near-doji bars with a tiny monotonic drift.

    The drift keeps every high strictly below its left neighbors and every
    low strictly above its right neighbors, so the tie-tolerant TV pivot rule
    confirms no pivots during warm-up; EMAs stay within ~0.1 of 100 and the
    ATR stays ~1.0.
    """

    return [
        bar3(i, 100.0, 100.5 - 0.002 * i, 99.5 - 0.002 * i, 100.0)
        for i in range(n)
    ]


def flat_10m(level: float, count: int = 60) -> list[Bar]:
    """10m bars before the 3m session whose EMAs all equal ``level``."""

    start = BASE_MS - count * M10
    return [
        Bar(start + (i + 1) * M10, level, level + 0.5, level - 0.5, level)
        for i in range(count)
    ]


def trending_10m(start_level: float, step: float, count: int = 60) -> list[Bar]:
    start = BASE_MS - count * M10
    bars = []
    for i in range(count):
        mid = start_level + step * i
        bars.append(Bar(start + (i + 1) * M10, mid, mid + 0.5, mid - 0.5, mid))
    return bars


HAMMER = dict(o=100.00, h=100.05, low=99.00, c=100.04)


def hammer_bar(index: int) -> Bar:
    return bar3(index, HAMMER["o"], HAMMER["h"], HAMMER["low"], HAMMER["c"])


class SmallBodyRejectionTests(unittest.TestCase):
    """B-table #6: Pine accepts a small-body hammer; the old oracle demanded
    a 0.45 body.  Body here is 0.04/1.05 ≈ 3.8%."""

    def test_hammer_fires_level_rejection_with_grade_b(self) -> None:
        replica = V11PineReplica(bars_10m=flat_10m(99.0), config=CFG)
        replica.replay(quiet_warmup())
        snap = replica.process(hammer_bar(55))

        self.assertIsNotNone(snap.new_signal)
        signal = snap.new_signal
        self.assertEqual(signal.side, SIDE_LONG)
        self.assertEqual(signal.setup, SETUP_LEVEL_REJECTION)
        self.assertEqual(signal.grade, GRADE_B)
        self.assertEqual(signal.id, snap.close_ms + 100 + 10 * SETUP_LEVEL_REJECTION + GRADE_B)
        self.assertFalse(signal.countertrend)
        body_ratio = abs(HAMMER["c"] - HAMMER["o"]) / (HAMMER["h"] - HAMMER["low"])
        self.assertLess(body_ratio, CFG.strong_body_ratio)
        plan = snap.plan
        self.assertTrue(plan.active)
        self.assertAlmostEqual(plan.entry, 100.04)
        self.assertAlmostEqual(plan.stop, 99.00 - 0.10 * snap.atr, places=9)
        self.assertAlmostEqual(plan.t1, plan.entry + (plan.entry - plan.stop), places=9)

    def test_no_confirmed_10m_context_does_not_block_the_signal(self) -> None:
        """B-table #22: Pine has no NO_CONFIRMED_10M_CONTEXT blocker."""

        replica = V11PineReplica(config=CFG)  # no 10m, no daily
        replica.replay(quiet_warmup())
        snap = replica.process(hammer_bar(55))

        self.assertIsNone(snap.context_close_ms)
        self.assertIsNotNone(snap.new_signal)
        self.assertEqual(snap.new_signal.setup, SETUP_LEVEL_REJECTION)
        self.assertEqual(snap.new_signal.grade, GRADE_B)


class CountertrendIgnitionTests(unittest.TestCase):
    """B-table #18: ignition's route clause is satisfied by construction, so a
    10m-opposite ignition fires as a C-grade countertrend signal in Pine."""

    def test_ignition_fires_against_bearish_10m_context(self) -> None:
        replica = V11PineReplica(
            bars_10m=trending_10m(152.0, -0.2), config=CFG
        )
        replica.replay(quiet_warmup())
        snap = replica.process(bar3(55, 100.0, 101.4, 99.95, 101.2))

        self.assertEqual(snap.context_direction, SIDE_SHORT)
        self.assertIsNotNone(snap.new_signal)
        signal = snap.new_signal
        self.assertEqual(signal.side, SIDE_LONG)
        self.assertEqual(signal.setup, SETUP_IGNITION)
        self.assertEqual(signal.grade, GRADE_C)
        self.assertTrue(signal.countertrend)
        self.assertEqual(signal.reason_mask & 128, 128)
        self.assertEqual(signal.reason_mask & 8, 8)


class EdgeDedupAndAddTests(unittest.TestCase):
    """B-table #23: per-setup ready edges de-duplicate; a same-side signal
    while a plan is active is recorded as ADD and never rewrites the plan."""

    def test_t1_protect_add_reference_and_breakeven_stop(self) -> None:
        replica = V11PineReplica(bars_10m=flat_10m(99.0), config=CFG)
        replica.replay(quiet_warmup())
        entry_snap = replica.process(hammer_bar(55))
        original = entry_snap.plan
        original_id = original.signal_id
        t1 = original.t1

        follow = replica.process(bar3(56, 100.5, 101.3, 100.3, 101.0))
        events = [e.type for e in follow.new_plan_events]
        self.assertIn(EVENT_T1, events)
        t1_event = follow.new_plan_events[0]
        self.assertAlmostEqual(t1_event.price, t1, places=9)
        self.assertAlmostEqual(follow.plan.effective_stop, original.entry, places=9)
        # The same bar also completes a fresh breakout: it must surface as an
        # ADD reference, with the frozen plan untouched.
        self.assertIsNotNone(follow.new_signal)
        self.assertEqual(follow.new_signal.role, ROLE_ADD)
        self.assertEqual(follow.new_signal.setup, SETUP_BREAKOUT)
        self.assertEqual(follow.plan.signal_id, original_id)
        self.assertAlmostEqual(follow.plan.entry, original.entry, places=9)
        self.assertAlmostEqual(follow.plan.t1, original.t1, places=9)

        stop_snap = replica.process(bar3(57, 100.9, 101.0, 99.9, 100.0))
        stop_events = [e for e in stop_snap.new_plan_events if e.type == EVENT_STOP]
        self.assertEqual(len(stop_events), 1)
        self.assertAlmostEqual(stop_events[0].price, original.entry, places=9)

    def test_persistently_ready_setup_fires_only_once(self) -> None:
        replica = V11PineReplica(bars_10m=flat_10m(99.0), config=CFG)
        replica.replay(quiet_warmup())
        first = replica.process(hammer_bar(55))
        self.assertIsNotNone(first.new_signal)
        # A second identical hammer immediately after: swept-support proof and
        # readiness stay true, so no new edge and no second SignalEvent...
        second = replica.process(hammer_bar(56))
        if second.new_signal is not None:
            # ...unless a *different* setup family produced its own new edge.
            self.assertNotEqual(
                second.new_signal.setup, SETUP_LEVEL_REJECTION
            )


class SameBarReverseTests(unittest.TestCase):
    """B-table #27/#28: a non-countertrend opposite signal ends the plan with
    EVENT_REVERSE and opens the opposite plan on the same confirmed close."""

    def test_reverse_closes_long_and_opens_short_same_bar(self) -> None:
        replica = V11PineReplica(bars_10m=flat_10m(99.0), config=CFG)
        replica.replay(quiet_warmup())
        entry_snap = replica.process(hammer_bar(55))
        self.assertEqual(entry_snap.plan.side, SIDE_LONG)

        snap = replica.process(bar3(56, 100.3, 100.9, 99.75, 99.85))
        self.assertIsNotNone(snap.new_signal)
        self.assertEqual(snap.new_signal.side, SIDE_SHORT)
        self.assertEqual(snap.new_signal.role, ROLE_REVERSE)
        self.assertEqual(snap.new_signal.setup, SETUP_LEVEL_REJECTION)
        reverse_events = [e for e in snap.new_plan_events if e.type == EVENT_REVERSE]
        self.assertEqual(len(reverse_events), 1)
        self.assertEqual(reverse_events[0].side, SIDE_LONG)
        self.assertTrue(snap.plan.active)
        self.assertEqual(snap.plan.side, SIDE_SHORT)
        self.assertEqual(snap.plan.signal_id, snap.new_signal.id)


class StopFirstTests(unittest.TestCase):
    """Ambiguous bars are stop-first (pine:769-788)."""

    def test_bar_spanning_stop_and_t1_exits_at_stop(self) -> None:
        replica = V11PineReplica(bars_10m=flat_10m(99.0), config=CFG)
        replica.replay(quiet_warmup())
        entry_snap = replica.process(hammer_bar(55))
        plan = entry_snap.plan

        snap = replica.process(bar3(56, 100.0, 101.5, 98.5, 100.0))
        events = snap.new_plan_events
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, EVENT_STOP)
        self.assertAlmostEqual(events[0].price, plan.stop, places=9)
        self.assertFalse(snap.plan.active)


class TrendRunnerTests(unittest.TestCase):
    """T2 with aligned confirmed 10m trend and 3m pace keeps a protected
    runner with the stop lifted to T1 (pine:789-805)."""

    def test_aligned_t2_keeps_runner_and_lifts_stop_to_t1(self) -> None:
        replica = V11PineReplica(
            bars_10m=trending_10m(88.0, 0.12), config=CFG
        )
        replica.replay(quiet_warmup())
        entry_snap = replica.process(bar3(55, 100.0, 101.2, 99.9, 101.0))
        self.assertIsNotNone(entry_snap.new_signal)
        self.assertEqual(entry_snap.new_signal.setup, SETUP_BREAKOUT)
        self.assertEqual(entry_snap.new_signal.grade, GRADE_A)
        plan = entry_snap.plan

        snap = replica.process(bar3(56, 101.2, 102.5, 101.0, 102.3))
        t2_events = [e for e in snap.new_plan_events if e.type == EVENT_T2]
        self.assertEqual(len(t2_events), 1)
        self.assertTrue(snap.plan.active)
        self.assertTrue(snap.plan.t2_reached)
        self.assertAlmostEqual(snap.plan.effective_stop, plan.t1, places=9)


class ContextBoundaryTests(unittest.TestCase):
    """B-table #32: a 3m close coinciding with a 10m close reads the 10m bar
    *before* the one closing at that instant (containing-bar [1] semantics)."""

    def test_coincident_close_reads_previous_10m_bar(self) -> None:
        bars_10m = [
            Bar(BASE_MS + (i + 1) * M10, 100.0, 100.5, 99.5, 100.0)
            for i in range(6)
        ]
        replica = V11PineReplica(bars_10m=bars_10m, config=CFG)
        bars_3m = [
            Bar(BASE_MS + (i + 1) * M3, 100.0, 100.5, 99.5, 100.0)
            for i in range(12)
        ]
        snapshots = replica.replay(bars_3m)
        by_close = {s.close_ms: s for s in snapshots}

        coincident = by_close[BASE_MS + 10 * M3]  # closes with the 3rd 10m bar
        self.assertEqual(coincident.close_ms, BASE_MS + 3 * M10)
        self.assertEqual(coincident.context_close_ms, BASE_MS + 2 * M10)

        after = by_close[BASE_MS + 11 * M3]
        self.assertEqual(after.context_close_ms, BASE_MS + 3 * M10)

        # A 3m bar inside the very first 10m bar has no previous 10m bar yet.
        early = by_close[BASE_MS + 3 * M3]
        self.assertIsNone(early.context_close_ms)


class SpaceBlockTests(unittest.TestCase):
    """A near Saty lid beyond touch tolerance caps space and blocks the
    candidate with BLOCK_SPACE (pine:242-258); there is no separate
    oracle-style no-chase blocker (B-table #9)."""

    def test_saty_lid_within_055r_blocks_candidate(self) -> None:
        daily_start = BASE_MS - 30 * DAY
        bars_daily = [
            Bar(daily_start + (i + 1) * DAY, 100.0, 101.0, 99.0, 100.0)
            for i in range(15)
        ]
        replica = V11PineReplica(
            bars_10m=flat_10m(99.0), bars_daily=bars_daily, config=CFG
        )
        replica.replay(quiet_warmup())
        snap = replica.process(hammer_bar(55))

        self.assertAlmostEqual(snap.debug["saty_above"], 100.472, places=6)
        self.assertIsNone(snap.new_signal)
        self.assertEqual(snap.long_blocker, BLOCK_SPACE)


class ArbitrationPriorityTests(unittest.TestCase):
    """Setup priority is fixed rejection > pullback > breakout > ignition
    (pine:274-278); grade never outranks setup priority within one side."""

    def test_priority_order_matches_contract(self) -> None:
        self.assertGreater(
            V11PineReplica._setup_priority(SETUP_LEVEL_REJECTION),
            V11PineReplica._setup_priority(SETUP_BREAKOUT),
        )
        self.assertGreater(
            V11PineReplica._setup_priority(SETUP_BREAKOUT),
            V11PineReplica._setup_priority(SETUP_IGNITION),
        )


if __name__ == "__main__":
    unittest.main()
