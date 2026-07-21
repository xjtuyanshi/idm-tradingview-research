"""Synthetic behavioral tests for the independent IDM v11 replay oracle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


RESEARCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_DIR))

from v11_oracle import (  # noqa: E402
    Bar,
    BarAction,
    ConfirmedContextIndex,
    Context10m,
    EngineConfig,
    PlanEvent,
    ReplayResult,
    RuleGrade,
    SetupType,
    Side,
    V11ReplayOracle,
    build_confirmed_10m_contexts,
    count_legacy_formal_signals,
    load_tradingview_ohlc_csv,
    summarize_replay,
)


START = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)


def config() -> EngineConfig:
    """Short lookbacks keep fixtures readable; rule thresholds stay live-like."""

    return EngineConfig(
        fast_length=2,
        slow_length=3,
        anchor_fast_length=4,
        anchor_slow_length=5,
        atr_length=3,
        breakout_lookback=3,
        compression_lookback=4,
        level_lookback=6,
    )


def market_bar(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    volume: float = 100.0,
    support: float | None = 95.0,
    resistance: float | None = 110.0,
) -> Bar:
    return Bar(
        confirmed_at=START + timedelta(minutes=3 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        support=support,
        resistance=resistance,
    )


def bull_context(
    confirmed_at: datetime = START - timedelta(minutes=10),
) -> Context10m:
    return Context10m(
        confirmed_at=confirmed_at,
        close=102.0,
        ema5=102.0,
        ema12=101.0,
        ema34=100.0,
        ema50=99.0,
    )


def bear_context(
    confirmed_at: datetime = START - timedelta(minutes=10),
) -> Context10m:
    return Context10m(
        confirmed_at=confirmed_at,
        close=98.0,
        ema5=98.0,
        ema12=99.0,
        ema34=100.0,
        ema50=101.0,
    )


def quiet_warmup(*, support: float = 95.0, resistance: float = 110.0) -> list[Bar]:
    # Two wide dojis seed ATR, followed by four tight dojis.  Their tiny bodies
    # cannot trigger any of the direct setup families.
    specifications = [
        (100.0, 101.5, 98.5, 100.02),
        (100.02, 101.5, 98.5, 100.00),
        (100.00, 100.25, 99.80, 100.03),
        (100.03, 100.25, 99.85, 100.01),
        (100.01, 100.25, 99.85, 100.04),
        (100.04, 100.25, 99.88, 100.02),
    ]
    return [
        market_bar(
            index,
            open_,
            high,
            low,
            close,
            support=support,
            resistance=resistance,
        )
        for index, (open_, high, low, close) in enumerate(specifications)
    ]


def compression_breakout_bar(index: int, close: float = 100.70) -> Bar:
    return market_bar(
        index,
        100.05,
        close + 0.08,
        99.92,
        close,
        volume=180.0,
    )


class DirectSignalTests(unittest.TestCase):
    def test_one_way_rally_emits_buy_then_persistent_hold(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        bars = quiet_warmup()
        bars.append(compression_breakout_bar(6))
        bars.extend(
            [
                market_bar(7, 100.80, 101.00, 100.65, 100.92),
                market_bar(8, 100.92, 101.15, 100.82, 101.05),
                market_bar(9, 101.05, 101.20, 100.95, 101.15),
            ]
        )

        result = oracle.replay(bars)

        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.event_side, Side.LONG)
        self.assertIn(
            entry.candidate.setup,
            (SetupType.COMPRESSION_BREAKOUT, SetupType.TREND_IGNITION),
        )
        self.assertEqual(entry.candidate.stop_basis, "BREAKOUT_BOX_HIGH")
        self.assertIn(entry.candidate.grade, (RuleGrade.A, RuleGrade.B))
        self.assertTrue(all(item.action == BarAction.HOLD for item in result.decisions[7:]))
        self.assertTrue(all(item.plan is not None for item in result.decisions[6:]))

    def test_cloud_pullback_reclaim_emits_buy_without_serial_episode(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        # Rising dojis make the 3m Cloud bullish but do not satisfy strong-candle
        # setup gates.  The bearish pullback touches the Cloud, then the next
        # confirmed bar breaks its high.
        bars = [
            market_bar(0, 99.9, 101.0, 99.0, 100.0),
            market_bar(1, 100.0, 101.2, 99.2, 100.2),
            market_bar(2, 100.2, 100.5, 100.0, 100.3),
            market_bar(3, 100.3, 100.7, 100.1, 100.5),
            market_bar(4, 100.5, 100.9, 100.3, 100.7),
            market_bar(5, 100.7, 101.1, 100.5, 100.9),
            market_bar(6, 100.9, 101.0, 100.35, 100.45),
            market_bar(7, 100.45, 101.25, 100.40, 101.18, volume=170.0),
        ]

        result = oracle.replay(bars)
        entry = result.decisions[-1]

        self.assertEqual(entry.action, BarAction.ENTER)
        self.assertEqual(entry.event_side, Side.LONG)
        self.assertEqual(entry.candidate.setup, SetupType.PULLBACK_CONTINUATION)
        self.assertEqual(entry.candidate.stop_basis, "PULLBACK_CONFIRM_LOW")
        self.assertIn("Cloud pullback", entry.reason)

    def test_trend_ignition_is_a_direct_same_close_setup(self) -> None:
        ignition_config = replace(config(), compression_width_atr=0.01)
        oracle = V11ReplayOracle([bull_context()], ignition_config)
        bars = [
            market_bar(0, 100.0, 101.5, 98.5, 100.0),
            market_bar(1, 100.0, 101.5, 98.5, 99.8),
            market_bar(2, 99.8, 100.0, 99.5, 99.7),
            market_bar(3, 99.7, 99.9, 99.4, 99.6),
            market_bar(4, 99.6, 99.8, 99.3, 99.5),
            market_bar(5, 99.5, 99.7, 99.2, 99.4),
            market_bar(6, 99.4, 100.5, 99.3, 100.4, volume=200.0),
        ]

        decision = oracle.replay(bars).decisions[-1]

        self.assertEqual(decision.action, BarAction.ENTER)
        self.assertEqual(decision.event_side, Side.LONG)
        self.assertEqual(decision.candidate.setup, SetupType.TREND_IGNITION)
        self.assertTrue(decision.candidate.stop_basis.startswith("IGNITION_"))
        self.assertEqual(decision.candidate.entry, bars[-1].close)

    def test_support_rejection_never_chases_a_short_into_support(self) -> None:
        oracle = V11ReplayOracle([bear_context()], config())
        bars = quiet_warmup(support=99.0, resistance=110.0)
        bars.append(
            market_bar(
                6,
                99.90,
                100.55,
                99.45,
                100.45,
                volume=175.0,
                support=99.6,
                resistance=110.0,
            )
        )

        decision = oracle.replay(bars).decisions[-1]

        self.assertNotEqual(decision.event_side, Side.SHORT)
        self.assertEqual(decision.action, BarAction.ENTER)
        self.assertEqual(decision.event_side, Side.LONG)
        self.assertEqual(decision.candidate.setup, SetupType.LEVEL_REJECTION)
        self.assertEqual(decision.candidate.grade, RuleGrade.C)
        self.assertEqual(decision.candidate.stop_basis, "LEVEL_SWEEP_LOW")

    def test_resistance_rejection_never_chases_a_long_into_pressure(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        bars = quiet_warmup(support=90.0, resistance=100.4)
        bars.append(
            market_bar(
                6,
                100.10,
                100.55,
                99.45,
                99.55,
                volume=175.0,
                support=90.0,
                resistance=100.4,
            )
        )

        decision = oracle.replay(bars).decisions[-1]

        self.assertNotEqual(decision.event_side, Side.LONG)
        self.assertEqual(decision.action, BarAction.ENTER)
        self.assertEqual(decision.event_side, Side.SHORT)
        self.assertEqual(decision.candidate.setup, SetupType.LEVEL_REJECTION)
        self.assertEqual(decision.candidate.grade, RuleGrade.C)
        self.assertEqual(decision.candidate.stop_basis, "LEVEL_SWEEP_HIGH")

    def test_bearish_breakout_is_blocked_when_support_is_immediately_below(self) -> None:
        oracle = V11ReplayOracle([bear_context()], config())
        bars = quiet_warmup(support=99.65, resistance=110.0)
        bars.append(
            market_bar(
                6,
                100.05,
                100.10,
                99.70,
                99.75,
                volume=180.0,
                support=99.65,
                resistance=110.0,
            )
        )

        decision = oracle.replay(bars).decisions[-1]

        self.assertEqual(decision.action, BarAction.BLOCKED)
        self.assertEqual(decision.candidate.side, Side.SHORT)
        self.assertEqual(decision.candidate.stop_basis, "BREAKOUT_BOX_LOW")
        self.assertEqual(decision.candidate.blocker, "SHORT_INTO_SUPPORT")

    def test_bullish_breakout_is_blocked_when_resistance_is_immediately_above(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        bars = quiet_warmup(support=90.0, resistance=100.8)
        bars.append(
            market_bar(
                6,
                100.05,
                100.78,
                99.92,
                100.70,
                volume=180.0,
                support=90.0,
                resistance=100.8,
            )
        )

        decision = oracle.replay(bars).decisions[-1]

        self.assertEqual(decision.action, BarAction.BLOCKED)
        self.assertEqual(decision.candidate.side, Side.LONG)
        self.assertEqual(decision.candidate.stop_basis, "BREAKOUT_BOX_HIGH")
        self.assertEqual(decision.candidate.blocker, "LONG_INTO_RESISTANCE")


class FrozenPlanLifecycleTests(unittest.TestCase):
    def _entered_oracle(self) -> tuple[V11ReplayOracle, object]:
        oracle = V11ReplayOracle([bull_context()], config())
        for bar in quiet_warmup():
            oracle.process(bar)
        entry = oracle.process(compression_breakout_bar(6))
        self.assertEqual(entry.action, BarAction.ENTER)
        return oracle, entry.plan

    def test_entry_stop_and_targets_remain_frozen_while_holding(self) -> None:
        oracle, original = self._entered_oracle()
        decision = oracle.process(
            market_bar(7, 100.80, 101.00, 100.65, 100.92)
        )
        self.assertEqual(decision.action, BarAction.HOLD)
        self.assertEqual(decision.plan.entry, original.entry)
        self.assertEqual(decision.plan.initial_stop, original.initial_stop)
        self.assertEqual(decision.plan.t1, original.t1)
        self.assertEqual(decision.plan.t2, original.t2)

    def test_t1_protects_plan_without_rewriting_initial_geometry(self) -> None:
        oracle, original = self._entered_oracle()
        bar = market_bar(
            7,
            original.entry,
            original.t1 + 0.02,
            original.entry - 0.02,
            original.t1,
        )
        decision = oracle.process(bar)
        self.assertEqual(decision.action, BarAction.PROTECT)
        self.assertEqual(decision.event, PlanEvent.TARGET_1)
        self.assertEqual(decision.plan.initial_stop, original.initial_stop)
        self.assertEqual(decision.plan.active_stop, original.entry)
        self.assertEqual(decision.plan.t1, original.t1)
        self.assertEqual(decision.plan.t2, original.t2)

    def test_same_bar_target_and_stop_uses_conservative_stop_first(self) -> None:
        oracle, plan = self._entered_oracle()
        ambiguous = market_bar(
            7,
            plan.entry,
            plan.t2 + 0.10,
            plan.active_stop - 0.10,
            plan.entry,
        )
        decision = oracle.process(ambiguous)
        self.assertEqual(decision.action, BarAction.EXIT)
        self.assertEqual(decision.event, PlanEvent.STOP)
        self.assertEqual(decision.exit_price, plan.active_stop)
        self.assertIn("stop-first", decision.reason)

    def test_intact_trend_is_hold_not_arbitrary_timeout_exit(self) -> None:
        oracle, _ = self._entered_oracle()
        decisions = [
            oracle.process(market_bar(index, 100.8, 101.0, 100.6, 100.9))
            for index in range(7, 12)
        ]
        self.assertTrue(all(item.action == BarAction.HOLD for item in decisions))
        self.assertTrue(all(item.event == PlanEvent.NONE for item in decisions))


class CausalityAndAuditTests(unittest.TestCase):
    def test_future_10m_context_is_never_visible_before_confirmation(self) -> None:
        future_time = START + timedelta(minutes=30)
        contexts = [
            bear_context(),
            bull_context(future_time),
        ]
        index = ConfirmedContextIndex(reversed(contexts))

        before = index.at(future_time - timedelta(seconds=1))
        at_confirmation = index.at(future_time)

        self.assertEqual(before.trend_side, Side.SHORT)
        self.assertLessEqual(before.confirmed_at, future_time - timedelta(seconds=1))
        self.assertEqual(at_confirmation.trend_side, Side.LONG)
        self.assertEqual(at_confirmation.confirmed_at, future_time)

    def test_future_bull_context_cannot_release_earlier_long_breakout(self) -> None:
        bullish_confirmation = START + timedelta(minutes=30)
        oracle = V11ReplayOracle(
            [bear_context(), bull_context(bullish_confirmation)],
            config(),
        )
        bars = quiet_warmup()
        trigger = compression_breakout_bar(6)
        self.assertLess(trigger.confirmed_at, bullish_confirmation)

        decision = oracle.replay([*bars, trigger]).decisions[-1]

        self.assertEqual(decision.context.trend_side, Side.SHORT)
        self.assertEqual(decision.action, BarAction.BLOCKED)
        self.assertEqual(decision.candidate.blocker, "OPPOSITE_10M_CONTEXT")

    def test_context_builder_does_not_shift_values_backward(self) -> None:
        bars_10m = [
            Bar(
                confirmed_at=START + timedelta(minutes=10 * index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
            )
            for index in range(4)
        ]
        contexts = build_confirmed_10m_contexts(
            bars_10m,
            fast_length=2,
            slow_length=3,
            anchor_fast_length=2,
            anchor_slow_length=4,
        )
        self.assertEqual(
            [item.confirmed_at for item in contexts],
            [item.confirmed_at for item in bars_10m],
        )
        lookup = ConfirmedContextIndex(contexts)
        self.assertIsNone(lookup.at(START - timedelta(seconds=1)))
        self.assertEqual(lookup.at(START), contexts[0])

    def test_every_bar_has_one_auditable_action_and_nonempty_reason(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        bars = [*quiet_warmup(), compression_breakout_bar(6)]
        result = oracle.replay(bars)

        self.assertEqual(len(result.decisions), len(bars))
        for index, decision in enumerate(result.decisions):
            self.assertEqual(decision.bar_index, index)
            self.assertIsInstance(decision.action, BarAction)
            self.assertTrue(decision.reason.strip())
            self.assertLessEqual(
                decision.context.confirmed_at,
                decision.confirmed_at,
            )

    def test_invalid_or_out_of_order_bars_fail_closed(self) -> None:
        oracle = V11ReplayOracle([bull_context()], config())
        oracle.process(market_bar(0, 100.0, 101.0, 99.0, 100.0))
        with self.assertRaisesRegex(ValueError, "strictly time ordered"):
            oracle.process(market_bar(0, 100.0, 101.0, 99.0, 100.0))
        with self.assertRaisesRegex(ValueError, "inside the bar range"):
            oracle.process(market_bar(1, 100.0, 101.0, 99.0, 102.0))


@unittest.skipUnless(
    (
        RESEARCH_DIR
        / "fixtures"
        / "v11_2026-07-21"
        / "IDM_V11_FIXTURE_SPX500_3M_2026-07-21.csv"
    ).exists()
    and (
        RESEARCH_DIR
        / "fixtures"
        / "v11_2026-07-21"
        / "IDM_V11_FIXTURE_SPX500_10M_2026-07-21.csv"
    ).exists(),
    "private TradingView/Capital.com fixtures are not redistributed",
)
class July21TradingViewFixtureTests(unittest.TestCase):
    FIXTURE_DIR = RESEARCH_DIR / "fixtures" / "v11_2026-07-21"
    BARS_3M = FIXTURE_DIR / "IDM_V11_FIXTURE_SPX500_3M_2026-07-21.csv"
    BARS_10M = FIXTURE_DIR / "IDM_V11_FIXTURE_SPX500_10M_2026-07-21.csv"

    def _full_replay(self) -> ReplayResult:
        bars_3m = load_tradingview_ohlc_csv(
            self.BARS_3M,
            timeframe_minutes=3,
        )
        bars_10m = load_tradingview_ohlc_csv(
            self.BARS_10M,
            timeframe_minutes=10,
        )
        contexts = build_confirmed_10m_contexts(bars_10m)
        return V11ReplayOracle(contexts).replay(bars_3m)

    def test_real_morning_drought_is_replaced_by_long_entry_and_hold(self) -> None:
        bars_3m = load_tradingview_ohlc_csv(
            self.BARS_3M,
            timeframe_minutes=3,
        )
        bars_10m = load_tradingview_ohlc_csv(
            self.BARS_10M,
            timeframe_minutes=10,
        )
        full_result = self._full_replay()

        eastern = ZoneInfo("America/New_York")
        start_open = datetime(2026, 7, 21, 9, 30, tzinfo=eastern)
        end_open = datetime(2026, 7, 21, 13, 18, tzinfo=eastern)
        session_decisions = tuple(
            decision
            for decision in full_result.decisions
            if start_open
            <= (
                decision.confirmed_at - timedelta(minutes=3)
            ).astimezone(eastern)
            <= end_open
        )
        session = ReplayResult(session_decisions)
        summary = summarize_replay(session)

        self.assertEqual(len(bars_3m), 305)
        self.assertEqual(len(bars_10m), 302)
        self.assertEqual(len(session_decisions), 77, summary.compact)
        self.assertEqual(
            count_legacy_formal_signals(self.BARS_3M),
            0,
            "the frozen v10.1R export must preserve the reported drought",
        )

        long_entries = [
            decision
            for decision in session_decisions
            if decision.action == BarAction.ENTER
            and decision.event_side == Side.LONG
        ]
        self.assertTrue(long_entries, summary.compact)
        long_with_later_hold = False
        for entry in long_entries:
            signal_id = entry.plan.signal_id
            if any(
                later.bar_index > entry.bar_index
                and later.action == BarAction.HOLD
                and later.plan is not None
                and later.plan.signal_id == signal_id
                for later in session_decisions
            ):
                long_with_later_hold = True
                break
        self.assertTrue(long_with_later_hold, summary.compact)
        self.assertGreater(summary.holds, 0, summary.compact)

        for decision in session_decisions:
            self.assertIsInstance(decision.action, BarAction, summary.compact)
            self.assertTrue(decision.reason.strip(), summary.compact)
            self.assertIsNotNone(decision.context, summary.compact)
            self.assertLessEqual(
                decision.context.confirmed_at,
                decision.confirmed_at,
                summary.compact,
            )

    def test_setup_specific_stop_keeps_or_releases_the_1024_breakout(self) -> None:
        """The main-rally breakout must not inherit a prior pullback low.

        Before this fix, the 10:24 ET bar produced both a 1.52 ATR pullback
        candidate and a 1.54 ATR breakout candidate; both were blocked.  The
        pullback may remain blocked, but the breakout owns its box boundary.
        """

        result = self._full_replay()
        eastern = ZoneInfo("America/New_York")
        decisions_by_confirmation = {
            decision.confirmed_at.astimezone(eastern): decision
            for decision in result.decisions
        }
        at_1018 = decisions_by_confirmation[
            datetime(2026, 7, 21, 10, 18, tzinfo=eastern)
        ]
        at_1024 = decisions_by_confirmation[
            datetime(2026, 7, 21, 10, 24, tzinfo=eastern)
        ]
        at_1027 = decisions_by_confirmation[
            datetime(2026, 7, 21, 10, 27, tzinfo=eastern)
        ]
        diagnostic = (
            "before: 10:18 STOP; 10:27 Pullback 1.52ATR + Breakout "
            "1.54ATR both BLOCKED | after: "
            f"10:18={at_1018.action.value}, "
            f"10:24={at_1024.action.value}, "
            f"10:27={at_1027.action.value}/"
            f"{at_1027.candidate.setup.value if at_1027.candidate else '-'} "
            f"riskATR="
            f"{at_1027.candidate.risk / at_1027.features.atr:.2f}"
        )

        # hl2 parity with Pine makes the 10:12-open reclaim the first formal
        # entry; its intentionally tight aggressive stop is hit by the later
        # deep 10:15 test.  That stopped plan must not suppress the independent
        # 10:24-open / 10:27-confirmed breakout.
        self.assertEqual(at_1018.action, BarAction.EXIT, diagnostic)
        self.assertEqual(at_1018.event, PlanEvent.STOP, diagnostic)
        self.assertEqual(at_1024.action, BarAction.WAIT, diagnostic)
        self.assertEqual(at_1027.action, BarAction.ENTER, diagnostic)
        self.assertIsNotNone(at_1027.candidate, diagnostic)
        self.assertTrue(at_1027.candidate.tradable, diagnostic)
        self.assertEqual(
            at_1027.candidate.setup,
            SetupType.COMPRESSION_BREAKOUT,
            diagnostic,
        )
        self.assertEqual(
            at_1027.candidate.stop_basis,
            "BREAKOUT_BOX_HIGH",
            diagnostic,
        )
        self.assertLessEqual(
            at_1027.candidate.risk / at_1027.features.atr,
            EngineConfig().max_risk_atr,
            diagnostic,
        )
        self.assertIsNotNone(at_1027.plan, diagnostic)

    def test_real_fixture_keeps_reentry_runner_and_labels_countertrend_probe(self) -> None:
        result = self._full_replay()
        eastern = ZoneInfo("America/New_York")
        by_open_time = {
            (decision.confirmed_at - timedelta(minutes=3)).astimezone(eastern): decision
            for decision in result.decisions
        }

        at_1042 = by_open_time[
            datetime(2026, 7, 21, 10, 42, tzinfo=eastern)
        ]
        at_1109 = by_open_time[
            datetime(2026, 7, 21, 11, 9, tzinfo=eastern)
        ]
        self.assertEqual(at_1042.action, BarAction.ENTER)
        self.assertEqual(at_1042.event_side, Side.LONG)
        self.assertEqual(at_1042.candidate.setup, SetupType.PULLBACK_CONTINUATION)
        self.assertEqual(at_1109.action, BarAction.ENTER)
        self.assertEqual(at_1109.event_side, Side.LONG)

        runner_window = [
            decision
            for open_time, decision in by_open_time.items()
            if datetime(2026, 7, 21, 11, 9, tzinfo=eastern)
            <= open_time
            <= datetime(2026, 7, 21, 13, 9, tzinfo=eastern)
        ]
        self.assertTrue(runner_window)
        self.assertTrue(
            all(decision.action != BarAction.WAIT for decision in runner_window)
        )
        self.assertTrue(
            all(
                decision.plan is not None and decision.plan.side == Side.LONG
                for decision in runner_window
            )
        )

        at_1133 = by_open_time[
            datetime(2026, 7, 21, 11, 33, tzinfo=eastern)
        ]
        self.assertEqual(at_1133.action, BarAction.PROTECT)
        self.assertEqual(at_1133.event, PlanEvent.COUNTERTREND_ADVISORY)
        self.assertTrue(at_1133.candidate.countertrend)
        self.assertEqual(at_1133.candidate.grade, RuleGrade.C)
        self.assertEqual(at_1133.plan.side, Side.LONG)

    def test_csv_loader_converts_open_time_to_confirmed_time(self) -> None:
        bars = load_tradingview_ohlc_csv(
            self.BARS_3M,
            timeframe_minutes=3,
        )
        with self.BARS_3M.open(encoding="utf-8-sig") as handle:
            header = handle.readline()
            first_row = handle.readline().split(",")
        self.assertTrue(header.startswith("time,open,high,low,close"))
        expected = datetime.fromtimestamp(int(first_row[0]), timezone.utc)
        self.assertEqual(
            bars[0].confirmed_at,
            expected + timedelta(minutes=3),
        )


if __name__ == "__main__":
    unittest.main()
