"""Causality, pivot visibility, completed-day, and terminal-priority tests."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from research.phase1_10m_primary_opportunity_oracle import (
    Direction,
    NamedLevelSource,
    PrimaryEvent,
    PrimaryOpportunityEngine,
    PrimaryState,
    ReasonCode,
    run_primary,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    BASE_10M,
    long_bar,
    long_episode,
    short_bar,
    short_episode,
    ten_bar,
)


def _pivot_bar(index: int, high: float, low: float = 90.0):
    return long_bar(
        index,
        open_=95.0,
        high=high,
        low=low,
        close=96.0,
        ema5=94.0,
        ema12=93.5,
        ema21=93.0,
        ema48=92.0,
    )


def test_confirmed_pivot_is_unavailable_until_both_right_bars_close() -> None:
    engine = PrimaryOpportunityEngine()
    rows = [
        _pivot_bar(0, 100.0),
        _pivot_bar(1, 105.0),
        _pivot_bar(2, 120.0),
        _pivot_bar(3, 110.0),
        _pivot_bar(4, 108.0),
    ]
    for bar in rows[:4]:
        engine._register_pivot_after_bar(bar)  # noqa: SLF001
    assert list(engine._pivot_highs) == []  # noqa: SLF001
    engine._register_pivot_after_bar(rows[4])  # noqa: SLF001
    pivots = list(engine._pivot_highs)  # noqa: SLF001
    assert len(pivots) == 1
    assert pivots[0].price == pytest.approx(120.0)
    assert pivots[0].provenance_time_ms == rows[2].timestamp_ms


def test_pivot_that_becomes_confirmed_on_touch_bar_cannot_backfill_episode() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.LONG  # noqa: SLF001
    engine._epoch_id = "10M-EPOCH-L-1"  # noqa: SLF001
    engine._episode_id = "10M-EP-L-2"  # noqa: SLF001
    engine._state = PrimaryState.ARMED  # noqa: SLF001
    engine._prior_excursion = 110.0  # noqa: SLF001
    engine._prior_excursion_time_ms = 2  # noqa: SLF001
    engine._pivot_window = deque(  # noqa: SLF001
        [
            _pivot_bar(0, 100.0),
            _pivot_bar(1, 105.0),
            _pivot_bar(2, 120.0),
            _pivot_bar(3, 110.0),
        ],
        maxlen=5,
    )
    touch = long_bar(
        4,
        open_=105.0,
        high=108.0,
        low=102.0,
        close=104.0,
        ema5=105.0,
        ema12=104.0,
        ema21=103.0,
        ema48=102.5,
    )
    observation = engine.ingest(touch)
    assert observation.event == PrimaryEvent.WATCH_LONG
    assert not any(
        item.source == NamedLevelSource.CONFIRMED_PIVOT_10M
        and item.price == pytest.approx(120.0)
        for item in observation.frozen_candidates
    )
    assert any(item.price == pytest.approx(120.0) for item in engine._pivot_highs)  # noqa: SLF001


def _day_bar(index: int, *, base: datetime, high: float, low: float):
    return ten_bar(
        index,
        open_=100.0,
        high=high,
        low=low,
        close=100.0,
        ema5=101.0,
        ema12=100.0,
        ema21=99.0,
        ema48=98.0,
        base=base,
    )


def test_midday_initialization_never_publishes_partial_previous_day() -> None:
    engine = PrimaryOpportunityEngine()
    base = datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    for index in range(72):
        engine.ingest(_day_bar(index, base=base, high=110.0, low=90.0))
    engine.ingest(_day_bar(72, base=base, high=105.0, low=95.0))
    assert engine._previous_day_high is None  # noqa: SLF001
    assert engine._previous_day_low is None  # noqa: SLF001
    assert engine._previous_day_completed_at_ms is None  # noqa: SLF001


def test_same_day_gap_makes_day_ineligible_for_previous_day_publication() -> None:
    engine = PrimaryOpportunityEngine()
    base = datetime(2026, 8, 3, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    for index in range(144):
        if index == 50:
            continue
        engine.ingest(_day_bar(index, base=base, high=110.0, low=90.0))
    engine.ingest(_day_bar(144, base=base, high=105.0, low=95.0))
    assert engine._previous_day_high is None  # noqa: SLF001
    assert engine._previous_day_low is None  # noqa: SLF001


def test_complete_day_is_not_published_after_skipping_the_immediate_next_et_date() -> None:
    engine = PrimaryOpportunityEngine()
    base = datetime(2026, 8, 3, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    for index in range(144):
        engine.ingest(_day_bar(index, base=base, high=115.0, low=85.0))

    skipped_day = datetime(2026, 8, 5, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    engine.ingest(_day_bar(0, base=skipped_day, high=105.0, low=95.0))
    assert engine._previous_day_high is None  # noqa: SLF001
    assert engine._previous_day_low is None  # noqa: SLF001
    assert engine._previous_day_completed_at_ms is None  # noqa: SLF001


def test_complete_144_bar_et_day_publishes_exact_range_only_on_next_day() -> None:
    engine = PrimaryOpportunityEngine()
    base = datetime(2026, 8, 3, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    for index in range(144):
        high = 120.0 if index == 50 else 110.0
        low = 80.0 if index == 70 else 90.0
        engine.ingest(_day_bar(index, base=base, high=high, low=low))
        assert engine._previous_day_high is None  # noqa: SLF001
        assert engine._previous_day_low is None  # noqa: SLF001

    next_day = _day_bar(144, base=base, high=105.0, low=95.0)
    engine.ingest(next_day)
    assert engine._previous_day_high == pytest.approx(120.0)  # noqa: SLF001
    assert engine._previous_day_low == pytest.approx(80.0)  # noqa: SLF001
    assert engine._previous_day_completed_at_ms == next_day.timestamp_ms  # noqa: SLF001

    engine._epoch_direction = Direction.LONG  # noqa: SLF001
    engine._prior_excursion = None  # noqa: SLF001
    frozen = engine._freeze_candidates(next_day)  # noqa: SLF001
    previous = [
        item
        for item in frozen
        if item.source == NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH
    ]
    assert len(previous) == 1
    assert previous[0].price == pytest.approx(120.0)

def test_touch_bar_emits_watch_only_and_never_self_confirms() -> None:
    observations = run_primary(long_episode()[:3])
    touch = observations[-1]
    assert touch.event == PrimaryEvent.WATCH_LONG
    assert touch.state == PrimaryState.WAIT_REACTION
    assert touch.plan is None
    assert not touch.opportunity_active


def test_forming_reclaim_does_not_age_or_consume_frozen_candidates() -> None:
    bars = long_episode()
    engine = PrimaryOpportunityEngine()
    for bar in bars[:3]:
        engine.ingest(bar)
    forming = engine.ingest(replace(bars[3], is_confirmed=False, high=120.0))
    assert forming.event == PrimaryEvent.NONE
    assert forming.state == PrimaryState.WAIT_REACTION
    assert all(not item.consumed for item in forming.frozen_candidates)
    confirmed = engine.ingest(bars[3])
    assert confirmed.event == PrimaryEvent.MAIN_LONG


def test_later_bar_can_consume_prior_excursion_before_reclaim() -> None:
    bars = long_episode(target=112.0)[:3]
    bars.extend(
        [
            long_bar(
                3,
                open_=105.0,
                high=112.2,
                low=103.0,
                close=105.0,
                ema5=105.8,
                ema12=105.4,
                ema21=103.5,
                ema48=102.2,
            ),
            long_bar(
                4,
                open_=105.0,
                high=107.2,
                low=104.0,
                close=106.8,
                ema5=105.8,
                ema12=105.4,
                ema21=103.6,
                ema48=102.3,
            ),
        ]
    )
    outcome = run_primary(bars)[-1]
    assert outcome.event == PrimaryEvent.SPACE_UNKNOWN
    assert outcome.frozen_candidates[0].consumed


def test_wait_reaction_frozen_invalidation_beats_simultaneous_slow_loss() -> None:
    engine = PrimaryOpportunityEngine()
    for bar in long_episode()[:3]:
        engine.ingest(bar)
    simultaneous = long_bar(
        3,
        open_=102.0,
        high=103.0,
        low=99.0,
        close=100.0,
        ema5=101.0,
        ema12=101.5,
        ema21=100.0,
        ema48=101.0,
    )
    outcome = engine.ingest(simultaneous)
    assert outcome.event == PrimaryEvent.INVALIDATED
    assert outcome.reason_code == ReasonCode.FROZEN_INVALIDATION_BROKEN
    assert outcome.state == PrimaryState.WAIT_TREND
    assert outcome.plan is None
    assert outcome.outcome_direction == Direction.NONE
    assert outcome.marker_price == pytest.approx(101.6)


def test_short_watch_invalidation_has_no_plan_and_keeps_frozen_marker() -> None:
    engine = PrimaryOpportunityEngine()
    for bar in short_episode()[:3]:
        watch = engine.ingest(bar)
    assert watch.event == PrimaryEvent.WATCH_SHORT
    invalidated = engine.ingest(
        short_bar(
            3,
            open_=98.0,
            high=99.4,
            low=97.8,
            close=99.0,
            ema5=97.0,
            ema12=97.5,
            ema21=97.0,
            ema48=98.0,
        )
    )
    assert invalidated.event == PrimaryEvent.INVALIDATED
    assert invalidated.reason_code == ReasonCode.FROZEN_INVALIDATION_BROKEN
    assert invalidated.plan is None
    assert invalidated.outcome_direction == Direction.NONE
    assert invalidated.marker_price == pytest.approx(98.4)


def test_source_identity_survives_from_frozen_candidate_into_plan() -> None:
    outcome = run_primary(long_episode())[-1]
    assert outcome.plan is not None
    assert outcome.plan.next_named_level_source == NamedLevelSource.PRIOR_EXCURSION_10M
    assert outcome.plan.next_named_level_provenance_time_ms == long_episode()[1].timestamp_ms


def test_context_reset_terminal_snapshot_clears_trader_permission() -> None:
    engine = PrimaryOpportunityEngine()
    observations = [engine.ingest(bar) for bar in long_episode()]
    assert observations[-1].event == PrimaryEvent.MAIN_LONG
    reset = engine.ingest(
        long_bar(
            4,
            open_=100.0,
            high=101.0,
            low=98.0,
            close=99.0,
            ema5=99.5,
            ema12=100.0,
            ema21=99.0,
            ema48=100.0,
        )
    )
    assert reset.event == PrimaryEvent.INVALIDATED
    assert reset.reason_code == ReasonCode.FROZEN_INVALIDATION_BROKEN
    assert reset.state == PrimaryState.WAIT_TREND
    assert not reset.opportunity_active
    assert reset.outcome_direction == Direction.NONE
    assert reset.outcome.value == "无大机会"
