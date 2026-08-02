"""Duplicate timestamps and persistent 3m opportunity-id suppression tests."""

from __future__ import annotations

from dataclasses import replace
from math import nan

from research.phase1_10m_primary_opportunity_oracle import (
    OpportunityTimingEngine,
    PrimaryEvent,
    PrimaryOpportunityEngine,
    PrimaryState,
    ReasonCode,
    TimingConfig,
    TimingEvent,
    TimingReason,
    TimingState,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    active_long_plan,
    long_episode,
    shifted_plan,
    three_bar,
)


def _enter_long(engine: OpportunityTimingEngine, plan) -> None:
    assert engine.ingest(three_bar(0), plan).event == TimingEvent.NONE
    assert (
        engine.ingest(three_bar(1, high=106.6, low=105.4, close=106.0), plan).reason_code
        == TimingReason.PULLBACK_FROZEN
    )
    entered = engine.ingest(
        three_bar(2, high=107.2, low=106.0, close=107.0, ema5=106.8, ema12=106.4),
        plan,
    )
    assert entered.event == TimingEvent.LONG_ENTRY


def test_primary_duplicate_timestamp_is_ignored_without_state_reset() -> None:
    engine = PrimaryOpportunityEngine()
    first = long_episode()[0]
    engine.ingest(first)
    duplicate = engine.ingest(first)
    assert duplicate.event == PrimaryEvent.NONE
    assert duplicate.reason_code == ReasonCode.DATA_DUPLICATE_IGNORED
    assert duplicate.state == PrimaryState.WAIT_CLEAR
    assert not duplicate.data_valid


def test_primary_backward_timestamp_matches_duplicate_behavior() -> None:
    engine = PrimaryOpportunityEngine()
    bars = long_episode()
    engine.ingest(bars[0])
    engine.ingest(bars[1])
    backward = engine.ingest(bars[0])
    assert backward.event == PrimaryEvent.DATA_RESET
    assert backward.reason_code == ReasonCode.DATA_NON_MONOTONIC
    assert backward.state == PrimaryState.DISABLED


def test_3m_entered_then_gap_same_id_is_never_readopted_or_reentered() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    _enter_long(engine, plan)

    gap = engine.ingest(three_bar(4), plan)
    assert gap.reason_code == TimingReason.DATA_GAP_RESET
    assert gap.suppressed_opportunity_id == plan.opportunity_id

    same = engine.ingest(three_bar(5), plan)
    assert same.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED
    assert same.state == TimingState.WAIT_10M
    assert same.event == TimingEvent.NONE

    later = engine.ingest(
        three_bar(6, high=108.0, low=105.0, close=107.5, ema5=107.2, ema12=106.8),
        plan,
    )
    assert later.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED
    assert later.event == TimingEvent.NONE


def test_trigger_expired_then_invalid_reset_same_id_remains_suppressed() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine(TimingConfig(max_trigger_bars=1))
    engine.ingest(three_bar(0), plan)
    engine.ingest(three_bar(1, high=106.6, low=105.4, close=106.0), plan)
    engine.ingest(three_bar(2, high=106.4, low=105.8, close=106.2), plan)
    expired = engine.ingest(three_bar(3, high=106.5, low=105.9, close=106.3), plan)
    assert expired.reason_code == TimingReason.TRIGGER_EXPIRED
    assert expired.state == TimingState.LOCKED
    assert expired.suppressed_opportunity_id == plan.opportunity_id

    invalid = engine.ingest(replace(three_bar(4), close=nan), plan)
    assert invalid.reason_code == TimingReason.DATA_INVALID
    same = engine.ingest(three_bar(5), plan)
    assert same.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED


def test_space_below_one_r_then_gap_same_id_remains_suppressed() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), plan)
    engine.ingest(three_bar(1, high=109.8, low=105.5, close=106.0), plan)
    blocked = engine.ingest(
        three_bar(2, open_=109.5, high=110.5, low=109.2, close=110.2, ema5=110.0, ema12=109.6),
        plan,
    )
    assert blocked.reason_code == TimingReason.SPACE_LT_1R
    gap = engine.ingest(three_bar(4), plan)
    assert gap.reason_code == TimingReason.DATA_GAP_RESET
    same = engine.ingest(three_bar(5), plan)
    assert same.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED


def test_invalidated_then_nonmonotonic_reset_same_id_remains_suppressed() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), plan)
    invalidated = engine.ingest(
        three_bar(1, open_=102.0, high=102.2, low=101.0, close=101.0),
        plan,
    )
    assert invalidated.event == TimingEvent.LONG_INVALIDATED
    assert invalidated.reason_code == TimingReason.OPPORTUNITY_INVALIDATED

    backward = engine.ingest(three_bar(0), plan)
    assert backward.reason_code == TimingReason.DATA_NON_MONOTONIC
    same = engine.ingest(three_bar(2), plan)
    assert same.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED


def test_different_id_after_suppression_can_adopt_but_not_enter_same_bar() -> None:
    old_plan = active_long_plan()
    new_plan = shifted_plan(old_plan, opportunity_id="10M-TC-L-1785780000000")
    engine = OpportunityTimingEngine()
    _enter_long(engine, old_plan)
    engine.ingest(three_bar(4), old_plan)  # gap, preserves old suppression
    suppressed = engine.ingest(three_bar(5), old_plan)
    assert suppressed.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED

    adopted = engine.ingest(
        three_bar(6, high=110.0, low=104.0, close=108.0, ema5=107.8, ema12=107.2),
        new_plan,
    )
    assert adopted.reason_code == TimingReason.NEW_OPPORTUNITY
    assert adopted.state == TimingState.WAIT_PULLBACK
    assert adopted.event == TimingEvent.NONE
    assert adopted.opportunity_id == new_plan.opportunity_id


def test_timing_duplicate_timestamp_is_ignored_without_reset() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), plan)
    duplicate = engine.ingest(three_bar(0), plan)
    assert duplicate.reason_code == TimingReason.DATA_DUPLICATE_IGNORED
    assert duplicate.state == TimingState.WAIT_PULLBACK
    assert duplicate.suppressed_opportunity_id is None
