"""Positive-path tests for R3 native-10m opportunities and 3m timing."""

from __future__ import annotations

import pytest

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
    TraderOutcome,
    run_primary,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    active_long_plan,
    active_short_plan,
    long_bar,
    long_episode,
    short_episode,
    shifted_plan,
    three_bar,
)


def test_long_episode_emits_one_watch_then_one_main_at_exactly_one_r() -> None:
    observations = run_primary(long_episode())
    assert [item.event for item in observations] == [
        PrimaryEvent.NONE,
        PrimaryEvent.NONE,
        PrimaryEvent.WATCH_LONG,
        PrimaryEvent.MAIN_LONG,
    ]
    watch = observations[2]
    main = observations[3]
    assert watch.state == PrimaryState.WAIT_REACTION
    assert watch.outcome == TraderOutcome.WATCH_LONG
    assert watch.plan is None
    assert not watch.opportunity_active
    assert main.state == PrimaryState.ACTIVE
    assert main.outcome == TraderOutcome.MAIN_LONG
    assert main.plan is not None
    assert main.plan.direction == Direction.LONG
    assert main.plan.space_r == pytest.approx(1.0)
    assert main.opportunity_active


def test_short_episode_is_exact_directional_mirror() -> None:
    observations = run_primary(short_episode())
    assert observations[2].event == PrimaryEvent.WATCH_SHORT
    main = observations[3]
    assert main.event == PrimaryEvent.MAIN_SHORT
    assert main.plan is not None
    assert main.plan.direction == Direction.SHORT
    assert main.plan.space_r == pytest.approx(1.0)
    assert main.marker_price == pytest.approx(93.2)


def test_terminal_then_strict_later_full_clear_rearms_same_slow_epoch() -> None:
    # First episode is blocked at <1R, which is terminal for that episode only.
    engine = PrimaryOpportunityEngine()
    first = long_episode(target=109.0)
    observations = [engine.ingest(bar) for bar in first]
    terminal = observations[-1]
    assert terminal.event == PrimaryEvent.DONT_CHASE
    assert terminal.state == PrimaryState.WAIT_CLEAR
    first_epoch = terminal.epoch_id
    first_episode = terminal.episode_id

    # The terminal bar cannot also rearm.  A later bar that still intersects the
    # cloud remains WAIT_CLEAR.
    no_clear = engine.ingest(
        long_bar(
            4,
            open_=106.0,
            high=107.0,
            low=104.0,
            close=105.0,
            ema5=105.5,
            ema12=105.0,
            ema21=104.0,
            ema48=102.5,
        )
    )
    assert no_clear.state == PrimaryState.WAIT_CLEAR
    assert no_clear.reason_code == ReasonCode.WAIT_FULL_CLEAR
    assert no_clear.episode_id == first_episode

    clear = engine.ingest(
        long_bar(
            5,
            open_=108.0,
            high=114.0,
            low=107.0,
            close=110.0,
            ema5=106.0,
            ema12=105.5,
            ema21=104.5,
            ema48=103.0,
        )
    )
    assert clear.state == PrimaryState.ARMED
    assert clear.reason_code == ReasonCode.EPISODE_ARMED
    assert clear.epoch_id == first_epoch
    assert clear.episode_id != first_episode

    watch = engine.ingest(
        long_bar(
            6,
            open_=108.0,
            high=109.0,
            low=105.5,
            close=107.0,
            ema5=108.0,
            ema12=107.0,
            ema21=105.0,
            ema48=103.5,
        )
    )
    assert watch.event == PrimaryEvent.WATCH_LONG
    assert watch.episode_id == clear.episode_id


def test_active_long_plan_emits_only_one_later_3m_entry() -> None:
    plan = active_long_plan()
    engine = OpportunityTimingEngine()
    rows = [
        three_bar(0, close=106.0),
        three_bar(1, open_=106.0, high=106.6, low=105.4, close=106.0),
        three_bar(2, open_=106.1, high=106.5, low=105.9, close=106.3),
        three_bar(3, open_=106.3, high=107.2, low=106.2, close=107.0, ema5=106.8, ema12=106.4),
        three_bar(4, open_=107.0, high=107.5, low=106.8, close=107.2, ema5=107.0, ema12=106.6),
    ]
    observations = [engine.ingest(bar, plan) for bar in rows]
    assert observations[0].reason_code == TimingReason.NEW_OPPORTUNITY
    assert observations[1].reason_code == TimingReason.PULLBACK_FROZEN
    assert observations[2].reason_code == TimingReason.WAIT_LATER_TRIGGER
    assert observations[3].event == TimingEvent.LONG_ENTRY
    assert observations[3].state == TimingState.ENTERED
    assert observations[4].event == TimingEvent.NONE
    assert observations[4].reason_code == TimingReason.ENTERED_PLAN_MANAGEMENT


def test_active_short_plan_emits_only_one_later_3m_entry() -> None:
    plan = active_short_plan()
    engine = OpportunityTimingEngine()
    rows = [
        three_bar(0, open_=94.0, high=94.2, low=93.8, close=94.0, ema5=94.2, ema12=94.6),
        three_bar(1, open_=94.0, high=94.8, low=93.7, close=94.2, ema5=94.2, ema12=94.6),
        three_bar(2, open_=94.1, high=94.4, low=93.8, close=94.0, ema5=94.1, ema12=94.5),
        three_bar(3, open_=94.0, high=94.1, low=92.9, close=93.0, ema5=93.5, ema12=94.0),
    ]
    observations = [engine.ingest(bar, plan) for bar in rows]
    assert observations[-1].event == TimingEvent.SHORT_ENTRY
    assert TimingEvent.LONG_ENTRY not in [item.event for item in observations]


def test_different_new_3m_opportunity_cannot_replace_entered_owner() -> None:
    old_plan = active_long_plan()
    new_plan = shifted_plan(old_plan, opportunity_id="10M-TC-L-1785779400000")
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), old_plan)
    engine.ingest(three_bar(1, high=106.6, low=105.4), old_plan)
    entered = engine.ingest(
        three_bar(2, high=107.2, low=106.0, close=107.0, ema5=106.8, ema12=106.4),
        old_plan,
    )
    assert entered.event == TimingEvent.LONG_ENTRY

    retained = engine.ingest(
        three_bar(3, high=108.0, low=105.0, close=107.5, ema5=107.2, ema12=106.8),
        new_plan,
    )
    assert retained.event == TimingEvent.NONE
    assert retained.reason_code == TimingReason.ENTERED_PLAN_MANAGEMENT
    assert retained.state == TimingState.ENTERED
    assert retained.opportunity_id == old_plan.opportunity_id
    assert retained.plan_invalidation == pytest.approx(old_plan.invalidation)
    assert retained.plan_target == pytest.approx(old_plan.next_named_level)
