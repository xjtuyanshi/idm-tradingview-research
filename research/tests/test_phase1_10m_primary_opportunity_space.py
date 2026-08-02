"""Named-level routing and hard-space-gate tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from research.phase1_10m_primary_opportunity_oracle import (
    Direction,
    NamedLevelCandidate,
    NamedLevelSource,
    OpportunityTimingEngine,
    PrimaryEvent,
    PrimaryOpportunityEngine,
    PrimaryState,
    TimingEvent,
    TimingReason,
    TimingState,
    TraderOutcome,
    run_primary,
)
from research.tests.fixture_phase1_10m_primary_opportunity import (
    active_long_plan,
    long_episode,
    three_bar,
)


def test_exactly_one_r_is_main_inclusively() -> None:
    outcome = run_primary(long_episode(target=112.0))[-1]
    assert outcome.event == PrimaryEvent.MAIN_LONG
    assert outcome.plan is not None
    assert outcome.plan.space_r == pytest.approx(1.0)


def test_forward_space_below_one_r_is_dont_chase_not_main() -> None:
    outcome = run_primary(long_episode(target=109.0))[-1]
    assert outcome.event == PrimaryEvent.DONT_CHASE
    assert outcome.outcome == TraderOutcome.DONT_CHASE
    assert outcome.state == PrimaryState.WAIT_CLEAR
    assert not outcome.opportunity_active
    assert outcome.plan is not None
    assert outcome.plan.space_r is not None and outcome.plan.space_r < 1.0


def test_target_unknown_remains_fail_closed() -> None:
    # The only frozen prior-excursion level is inside the confirmation bar.
    rows = long_episode(target=106.9)
    outcome = run_primary(rows)[-1]
    assert outcome.event == PrimaryEvent.SPACE_UNKNOWN
    assert outcome.plan is not None
    assert outcome.plan.next_named_level is None
    assert outcome.plan.next_named_level_source == NamedLevelSource.UNKNOWN
    assert not outcome.opportunity_active


def test_same_price_source_tie_break_is_deterministic() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.LONG  # noqa: SLF001 - contract-level router test
    engine._frozen_candidates = [  # noqa: SLF001
        NamedLevelCandidate(120.0, NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH, 30),
        NamedLevelCandidate(120.0, NamedLevelSource.CONFIRMED_PIVOT_10M, 20),
        NamedLevelCandidate(120.0, NamedLevelSource.PRIOR_EXCURSION_10M, 10),
    ]
    confirmation = replace(long_episode()[3], high=110.0)
    selected = engine._select_forward_candidate(confirmation)  # noqa: SLF001
    assert selected is not None
    assert selected.source == NamedLevelSource.PRIOR_EXCURSION_10M


def test_nearest_unconsumed_forward_level_is_selected() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.LONG  # noqa: SLF001
    engine._frozen_candidates = [  # noqa: SLF001
        NamedLevelCandidate(118.0, NamedLevelSource.CONFIRMED_PIVOT_10M, 10),
        NamedLevelCandidate(114.0, NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH, 20),
        NamedLevelCandidate(112.0, NamedLevelSource.PRIOR_EXCURSION_10M, 30, consumed=True),
    ]
    selected = engine._select_forward_candidate(long_episode()[3])  # noqa: SLF001
    assert selected is not None
    assert selected.price == pytest.approx(114.0)


def test_router_cannot_skip_nearer_obstacle_to_manufacture_one_r() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.LONG  # noqa: SLF001
    engine._frozen_candidates = [  # noqa: SLF001
        NamedLevelCandidate(109.0, NamedLevelSource.CONFIRMED_PIVOT_10M, 10),
        NamedLevelCandidate(120.0, NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH, 20),
    ]
    confirmation = long_episode()[3]
    selected = engine._select_forward_candidate(confirmation)  # noqa: SLF001
    assert selected is not None and selected.price == pytest.approx(109.0)
    risk = confirmation.close - 101.6
    assert (selected.price - confirmation.close) / risk < 1.0


def test_confirmation_whole_bar_consumes_nearer_level_then_routes_farther() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.LONG  # noqa: SLF001
    engine._frozen_candidates = [  # noqa: SLF001
        NamedLevelCandidate(107.0, NamedLevelSource.PRIOR_EXCURSION_10M, 10),
        NamedLevelCandidate(115.0, NamedLevelSource.CONFIRMED_PIVOT_10M, 20),
    ]
    confirmation = replace(long_episode()[3], high=107.2)
    engine._consume_candidates(confirmation)  # noqa: SLF001
    assert engine._frozen_candidates[0].consumed  # noqa: SLF001
    selected = engine._select_forward_candidate(confirmation)  # noqa: SLF001
    assert selected is not None
    assert selected.price == pytest.approx(115.0)
    assert selected.source == NamedLevelSource.CONFIRMED_PIVOT_10M


def test_later_bar_consumption_is_sticky() -> None:
    engine = PrimaryOpportunityEngine()
    engine._epoch_direction = Direction.SHORT  # noqa: SLF001
    engine._frozen_candidates = [  # noqa: SLF001
        NamedLevelCandidate(90.0, NamedLevelSource.CONFIRMED_PIVOT_10M, 10),
        NamedLevelCandidate(80.0, NamedLevelSource.PREVIOUS_COMPLETED_DAY_LOW, 20),
    ]
    consume = replace(long_episode()[3], high=96.0, low=89.5, close=93.0, open=94.0)
    engine._consume_candidates(consume)  # noqa: SLF001
    later = replace(consume, low=91.0)
    engine._consume_candidates(later)  # noqa: SLF001
    assert engine._frozen_candidates[0].consumed  # noqa: SLF001
    selected = engine._select_forward_candidate(later)  # noqa: SLF001
    assert selected is not None and selected.price == pytest.approx(80.0)


def test_3m_rechecks_remaining_space_and_locks_below_one_r() -> None:
    plan = active_long_plan(target=112.0)
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0, close=106.0), plan)
    engine.ingest(three_bar(1, high=109.8, low=105.5, close=106.0), plan)
    outcome = engine.ingest(
        three_bar(
            2,
            open_=109.5,
            high=110.5,
            low=109.2,
            close=110.2,
            ema5=110.0,
            ema12=109.6,
        ),
        plan,
    )
    assert outcome.event == TimingEvent.NONE
    assert outcome.state == TimingState.LOCKED
    assert outcome.reason_code == TimingReason.SPACE_LT_1R
    assert outcome.suppressed_opportunity_id == plan.opportunity_id


def test_3m_accepts_exactly_one_remaining_r_inclusively() -> None:
    plan = active_long_plan(target=112.0)
    engine = OpportunityTimingEngine()
    engine.ingest(three_bar(0), plan)
    engine.ingest(three_bar(1, high=106.6, low=105.5, close=106.0), plan)
    # (112 - x) == (x - 101.6) -> x = 106.8.
    outcome = engine.ingest(
        three_bar(2, open_=106.6, high=107.0, low=106.5, close=106.8, ema5=106.7, ema12=106.4),
        plan,
    )
    assert outcome.event == TimingEvent.LONG_ENTRY
    assert outcome.state == TimingState.ENTERED
