"""R3 split-lifetime and primary-pulse identity regressions."""

from __future__ import annotations

import pytest

from research.phase1_10m_primary_opportunity_oracle import (
    OpportunityTimingEngine,
    PrimaryEvent,
    TimingEvent,
    TimingReason,
    TimingState,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    active_long_plan,
    shifted_plan,
    three_bar,
)


def _entered_engine():
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    rows = [
        engine.ingest(three_bar(0), plan),
        engine.ingest(three_bar(1, high=106.6, low=105.4), plan),
        engine.ingest(
            three_bar(
                2,
                high=107.2,
                low=106.0,
                close=107.0,
                ema5=106.8,
                ema12=106.4,
            ),
            plan,
        ),
    ]
    assert rows[-1].event == TimingEvent.LONG_ENTRY
    return engine, plan, rows


def test_entered_primary_expiry_retains_frozen_plan_until_later_target() -> None:
    engine, plan, rows = _entered_engine()
    expired = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        None,
        PrimaryEvent.EXPIRED,
        plan,
    )
    assert expired.state == TimingState.ENTERED
    assert expired.reason_code == TimingReason.ENTERED_PLAN_MANAGEMENT
    assert expired.opportunity_id == plan.opportunity_id
    assert expired.plan_invalidation == pytest.approx(plan.invalidation)
    assert expired.plan_target == pytest.approx(plan.next_named_level)

    target = engine.ingest(
        three_bar(4, open_=113.0, high=plan.next_named_level + 0.1, low=110.0, close=113.8),
        None,
    )
    assert target.event == TimingEvent.LONG_TARGET_REACHED
    assert target.reason_code == TimingReason.OPPORTUNITY_TARGET_REACHED
    assert target.state == TimingState.LOCKED
    assert [item.event for item in rows + [expired, target]].count(TimingEvent.LONG_ENTRY) == 1


def test_entered_primary_expiry_retains_plan_until_later_close_invalidation() -> None:
    engine, plan, rows = _entered_engine()
    expired = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        None,
        PrimaryEvent.EXPIRED,
        plan,
    )
    invalidated = engine.ingest(
        three_bar(
            4,
            open_=102.0,
            high=102.2,
            low=101.0,
            close=plan.invalidation - 0.1,
            ema5=101.8,
            ema12=101.7,
        ),
        None,
    )
    assert invalidated.event == TimingEvent.LONG_INVALIDATED
    assert invalidated.reason_code == TimingReason.OPPORTUNITY_INVALIDATED
    assert invalidated.state == TimingState.LOCKED
    assert [item.event for item in rows + [expired, invalidated]].count(TimingEvent.LONG_ENTRY) == 1


def test_entered_different_new_plan_cannot_replace_old_owner() -> None:
    engine, old_plan, rows = _entered_engine()
    new_plan = shifted_plan(old_plan, opportunity_id="10M-TC-L-1785779400000")
    retained = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        new_plan,
    )
    assert retained.state == TimingState.ENTERED
    assert retained.reason_code == TimingReason.ENTERED_PLAN_MANAGEMENT
    assert retained.opportunity_id == old_plan.opportunity_id
    assert retained.opportunity_id != new_plan.opportunity_id
    assert [item.event for item in rows + [retained]].count(TimingEvent.LONG_ENTRY) == 1


def test_matching_primary_target_pulse_closes_entered_plan_without_3m_touch() -> None:
    engine, plan, rows = _entered_engine()
    target = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        None,
        PrimaryEvent.TARGET_REACHED,
        plan,
    )
    assert target.event == TimingEvent.LONG_TARGET_REACHED
    assert target.marker_price == pytest.approx(plan.next_named_level)
    assert target.state == TimingState.LOCKED
    assert [item.event for item in rows + [target]].count(TimingEvent.LONG_ENTRY) == 1


def test_matching_primary_invalidation_pulse_closes_entered_plan_without_3m_close_break() -> None:
    engine, plan, rows = _entered_engine()
    invalidated = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        None,
        PrimaryEvent.INVALIDATED,
        plan,
    )
    assert invalidated.event == TimingEvent.LONG_INVALIDATED
    assert invalidated.marker_price == pytest.approx(plan.invalidation)
    assert invalidated.state == TimingState.LOCKED
    assert [item.event for item in rows + [invalidated]].count(TimingEvent.LONG_ENTRY) == 1


def test_unrelated_primary_target_pulse_cannot_close_entered_old_plan() -> None:
    engine, old_plan, _ = _entered_engine()
    other_plan = shifted_plan(old_plan, opportunity_id="10M-TC-L-1785779400000")
    retained = engine.ingest(
        three_bar(3, open_=107.2, high=108.0, low=107.0, close=107.5),
        other_plan,
        PrimaryEvent.TARGET_REACHED,
        other_plan,
    )
    assert retained.state == TimingState.ENTERED
    assert retained.event == TimingEvent.NONE
    assert retained.opportunity_id == old_plan.opportunity_id


def test_waiting_primary_expiry_ends_and_suppresses_entry_permission() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    adopted = engine.ingest(three_bar(0), plan)
    assert adopted.reason_code == TimingReason.NEW_OPPORTUNITY
    ended = engine.ingest(
        three_bar(1, high=106.4, low=105.8, close=106.1),
        None,
        PrimaryEvent.EXPIRED,
        plan,
    )
    assert ended.state == TimingState.WAIT_10M
    assert ended.reason_code == TimingReason.OPPORTUNITY_ENDED
    assert ended.suppressed_opportunity_id == plan.opportunity_id
    suppressed = engine.ingest(three_bar(2), plan)
    assert suppressed.reason_code == TimingReason.OPPORTUNITY_SUPPRESSED
    assert suppressed.event == TimingEvent.NONE
