"""Fail-closed and direction-ownership tests."""

from __future__ import annotations

from dataclasses import replace

from research.phase1_10m_primary_opportunity_oracle import (
    Direction,
    OpportunityTimingEngine,
    PrimaryEvent,
    PrimaryOpportunityEngine,
    PrimaryState,
    ReasonCode,
    TimingEvent,
    TimingReason,
    TimingState,
    run_primary,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    active_long_plan,
    active_short_plan,
    long_bar,
    long_episode,
    shifted_plan,
    three_bar,
)


def test_touch_without_later_reclaim_never_emits_main() -> None:
    engine = PrimaryOpportunityEngine()
    for bar in long_episode()[:3]:
        engine.ingest(bar)
    observations = []
    for index in range(3, 10):
        observations.append(
            engine.ingest(
                long_bar(
                    index,
                    open_=104.0,
                    high=106.0,
                    low=103.0,
                    close=104.5,
                    ema5=105.5,
                    ema12=105.0,
                    ema21=103.5,
                    ema48=102.2,
                )
            )
        )
    assert PrimaryEvent.MAIN_LONG not in [item.event for item in observations]
    assert observations[-1].event == PrimaryEvent.EXPIRED
    assert observations[-1].reason_code == ReasonCode.REACTION_EXPIRED


def test_slow_long_with_temporarily_fast_short_cannot_emit_main_short() -> None:
    engine = PrimaryOpportunityEngine()
    for bar in long_episode()[:3]:
        engine.ingest(bar)
    pullback = engine.ingest(
        long_bar(
            3,
            open_=104.0,
            high=105.5,
            low=102.5,
            close=103.5,
            ema5=103.0,
            ema12=104.0,
            ema21=103.5,
            ema48=102.2,
        )
    )
    assert pullback.event == PrimaryEvent.NONE
    assert pullback.slow_direction == Direction.LONG
    assert pullback.fast_direction == Direction.SHORT
    assert pullback.event != PrimaryEvent.MAIN_SHORT
    assert pullback.outcome_direction != Direction.SHORT


def test_forming_10m_bar_does_not_start_epoch_or_emit_watch() -> None:
    forming = replace(long_episode()[0], is_confirmed=False)
    observation = PrimaryOpportunityEngine().ingest(forming)
    assert not observation.data_valid
    assert observation.event == PrimaryEvent.NONE
    assert observation.reason_code == ReasonCode.DATA_UNCONFIRMED
    assert observation.epoch_id is None


def test_wrong_symbol_or_timeframe_disables_primary() -> None:
    wrong_symbol = replace(long_episode()[0], symbol="CME_MINI:ES1!")
    wrong_tf = replace(long_episode()[0], timeframe_seconds=180)
    for bar, reason in [
        (wrong_symbol, ReasonCode.DATA_SYMBOL_MISMATCH),
        (wrong_tf, ReasonCode.DATA_TIMEFRAME_MISMATCH),
    ]:
        observation = PrimaryOpportunityEngine().ingest(bar)
        assert observation.state == PrimaryState.DISABLED
        assert observation.reason_code == reason
        assert not observation.data_valid


def test_watch_never_creates_a_3m_timing_plan_or_marker() -> None:
    watch = run_primary(long_episode()[:3])[-1]
    assert watch.event == PrimaryEvent.WATCH_LONG
    assert watch.plan is None
    timing = OpportunityTimingEngine().ingest(three_bar(0), None, watch.event)
    assert timing.event == TimingEvent.NONE
    assert timing.reason_code == TimingReason.WAIT_10M
    assert timing.state == TimingState.WAIT_10M


def test_no_active_10m_opportunity_means_no_3m_trader_marker() -> None:
    engine = OpportunityTimingEngine()
    observations = [engine.ingest(three_bar(i), None) for i in range(4)]
    assert all(item.event == TimingEvent.NONE for item in observations)
    assert all(item.state == TimingState.WAIT_10M for item in observations)


def test_3m_cannot_emit_opposite_direction_entry() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), plan)
    engine.ingest(three_bar(1, high=106.6, low=105.4, close=106.0), plan)
    opposite = engine.ingest(
        three_bar(2, high=106.5, low=104.8, close=105.0, ema5=105.0, ema12=105.5),
        plan,
    )
    assert opposite.event == TimingEvent.NONE
    assert opposite.event != TimingEvent.SHORT_ENTRY


def test_old_plan_invalidation_beats_same_bar_new_opportunity_adoption() -> None:
    old_plan = active_long_plan()
    new_plan = active_short_plan(opportunity_id="10M-TC-S-1785780600000")
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), old_plan)
    terminal = engine.ingest(
        three_bar(1, open_=102.0, high=103.0, low=101.0, close=101.0),
        new_plan,
    )
    assert terminal.event == TimingEvent.LONG_INVALIDATED
    assert terminal.reason_code == TimingReason.OPPORTUNITY_INVALIDATED
    assert terminal.opportunity_id == old_plan.opportunity_id

    adopted_later = engine.ingest(
        three_bar(2, open_=94.0, high=94.3, low=93.7, close=94.0, ema5=94.2, ema12=94.6),
        new_plan,
    )
    assert adopted_later.event == TimingEvent.NONE
    assert adopted_later.reason_code == TimingReason.OPPORTUNITY_REPLACED
    assert adopted_later.opportunity_id == new_plan.opportunity_id


def test_old_plan_target_reached_beats_same_bar_replacement() -> None:
    old_plan = active_long_plan()
    new_plan = shifted_plan(old_plan, opportunity_id="10M-TC-L-1785781200000")
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), old_plan)
    terminal = engine.ingest(
        three_bar(1, open_=113.0, high=114.2, low=112.5, close=113.5),
        new_plan,
    )
    assert terminal.event == TimingEvent.LONG_TARGET_REACHED
    assert terminal.reason_code == TimingReason.OPPORTUNITY_TARGET_REACHED
    assert terminal.opportunity_id == old_plan.opportunity_id


def test_unconfirmed_3m_does_not_adopt_active_plan() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    forming = engine.ingest(replace(three_bar(0), is_confirmed=False), plan)
    assert forming.event == TimingEvent.NONE
    assert forming.reason_code == TimingReason.DATA_UNCONFIRMED
    assert forming.opportunity_id is None
