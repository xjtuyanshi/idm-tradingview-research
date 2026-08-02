from __future__ import annotations

from dataclasses import replace

from research.phase1_10m_position_reversal_oracle import (
    Event,
    PositionReversalEngine,
    ReasonCode,
    State,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    bar,
    prior_atr,
    resistance_band,
    standard_bands,
    support_band,
)


def test_duplicate_watch_and_terminal_bars_do_not_advance_twice() -> None:
    engine = PositionReversalEngine()
    target = resistance_band(lower_bound=7460.0, upper_bound=7460.0)
    touch_bar = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)

    first = engine.ingest(touch_bar, (support_band(), target), prior_atr())
    duplicate_watch = engine.ingest(
        touch_bar,
        (support_band(), target),
        prior_atr(),
    )
    assert first.event is Event.SUPPORT_WATCH
    assert duplicate_watch.event is Event.NONE
    assert duplicate_watch.reason_code is ReasonCode.DATA_DUPLICATE_IGNORED
    assert duplicate_watch.reaction_bars_seen == 1

    confirm_bar = bar(12, 10, 7421.4, 7435.0, 7421.0, 7434.0)
    terminal = engine.ingest(confirm_bar, (support_band(), target), prior_atr())
    duplicate_terminal = engine.ingest(
        confirm_bar,
        (support_band(), target),
        prior_atr(),
    )
    assert terminal.event is Event.BOUNCE_CONFIRMED
    assert duplicate_terminal.event is Event.NONE
    assert duplicate_terminal.reason_code is ReasonCode.DATA_DUPLICATE_IGNORED
    assert len(engine.opportunities) == 1


def test_terminal_requires_strict_later_full_clear_before_new_episode() -> None:
    engine = PositionReversalEngine()
    bands = standard_bands()
    failed = engine.ingest(
        bar(10, 0, 7430.0, 7432.0, 7412.0, 7415.5),
        bands,
        prior_atr(),
    )
    assert failed.event is Event.ACCEPTED_BREAK
    first_episode = failed.episode_id

    still_crossing = engine.ingest(
        bar(10, 10, 7415.5, 7430.0, 7409.0, 7428.0),
        bands,
        prior_atr(),
    )
    assert still_crossing.state is State.WAIT_CLEAR
    assert still_crossing.reason_code is ReasonCode.WAIT_CLEAR_REQUIRED
    assert still_crossing.episode_id == first_episode
    assert still_crossing.marker_text is None

    clear_bar = engine.ingest(
        bar(10, 20, 7428.0, 7440.0, 7424.3, 7435.8),
        bands,
        prior_atr(),
    )
    assert clear_bar.event is Event.WAIT_CLEAR_COMPLETED
    assert clear_bar.episode_id == first_episode
    assert clear_bar.marker_text is None

    retouch = engine.ingest(
        bar(10, 30, 7435.8, 7443.8, 7420.9, 7443.5),
        bands,
        prior_atr(),
    )
    assert retouch.event is Event.BOUNCE_CONFIRMED
    assert retouch.state is State.READY
    assert retouch.episode_id != first_episode


def test_wait_clear_equality_at_point_twelve_atr_counts_but_whole_bar_must_clear() -> None:
    engine = PositionReversalEngine()
    bands = standard_bands()
    engine.ingest(
        bar(10, 0, 7430.0, 7432.0, 7412.0, 7415.5),
        bands,
        prior_atr(),
    )
    distance = 0.12 * prior_atr().value
    exact_close = LOWER_TRIGGER + distance

    crosses_old_band = engine.ingest(
        bar(10, 10, exact_close, exact_close + 1.0, LOWER_TRIGGER, exact_close),
        bands,
        prior_atr(),
    )
    assert crosses_old_band.reason_code is ReasonCode.WAIT_CLEAR_REQUIRED

    full_clear = engine.ingest(
        bar(
            10,
            20,
            exact_close,
            exact_close + 1.0,
            LOWER_TRIGGER + 0.1,
            exact_close,
        ),
        bands,
        prior_atr(),
    )
    assert full_clear.event is Event.WAIT_CLEAR_COMPLETED


def test_ready_payload_is_frozen_serializable_and_append_only() -> None:
    engine = PositionReversalEngine()
    opening = engine.ingest(
        bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1),
        standard_bands(),
        prior_atr(),
    )
    assert opening.opportunity is not None
    original = opening.opportunity
    original_json = original.to_json()

    # A later changed source version may reset runtime, but it cannot mutate or
    # delete the already-published immutable payload ledger.
    changed_bands = (
        support_band(source_version="v2", lower_bound=7400.0, upper_bound=7400.0),
        resistance_band(source_version="v2", lower_bound=7500.0, upper_bound=7500.0),
    )
    engine.ingest(
        bar(9, 40, 7450.0, 7454.0, 7440.0, 7448.0),
        changed_bands,
        replace(prior_atr(), source_version="2026-07-31-v2", value=101.0),
    )

    assert engine.opportunities == (original,)
    assert engine.opportunities[0].to_json() == original_json
    assert engine.opportunities[0].trigger == original.trigger
    assert engine.opportunities[0].invalidation == original.invalidation
    assert engine.opportunities[0].target == original.target
    assert engine.opportunities[0].expires_at_ms > original.visible_at_ms


def test_gap_reset_does_not_reuse_an_old_episode() -> None:
    engine = PositionReversalEngine()
    first = engine.ingest(
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert first.event is Event.SUPPORT_WATCH

    gap = engine.ingest(
        bar(12, 20, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert gap.event is Event.DATA_RESET
    assert gap.reason_code is ReasonCode.DATA_GAP_RESET
    assert gap.state is State.DISABLED
    assert gap.episode_id is None


def test_first_valid_bar_after_source_recovery_is_immediately_eligible() -> None:
    engine = PositionReversalEngine()
    disabled = engine.ingest(
        bar(12, 0, 7440.0, 7445.0, 7435.0, 7440.0),
        standard_bands(),
        prior_atr(enabled=False),
    )
    assert disabled.event is Event.DATA_RESET
    assert disabled.reason_code is ReasonCode.ATR_NOT_READY
    assert disabled.state is State.DISABLED

    recovered = engine.ingest(
        bar(12, 10, 7425.0, 7435.0, 7420.9, 7434.0),
        standard_bands(),
        prior_atr(),
    )
    assert recovered.event is Event.BOUNCE_CONFIRMED
    assert recovered.state is State.READY
    assert recovered.reason_code is ReasonCode.READY
    assert recovered.opportunity is not None


def test_gap_reset_discards_only_gap_bar_not_next_contiguous_eligible_bar() -> None:
    engine = PositionReversalEngine()
    first = engine.ingest(
        bar(12, 0, 7440.0, 7445.0, 7435.0, 7440.0),
        standard_bands(),
        prior_atr(),
    )
    assert first.event is Event.NONE

    gap = engine.ingest(
        bar(12, 20, 7425.0, 7435.0, 7420.9, 7434.0),
        standard_bands(),
        prior_atr(),
    )
    assert gap.event is Event.DATA_RESET
    assert gap.reason_code is ReasonCode.DATA_GAP_RESET
    assert gap.state is State.DISABLED
    assert gap.opportunity is None

    recovered = engine.ingest(
        bar(12, 30, 7425.0, 7435.0, 7420.9, 7434.0),
        standard_bands(),
        prior_atr(),
    )
    assert recovered.event is Event.BOUNCE_CONFIRMED
    assert recovered.state is State.READY
    assert recovered.reason_code is ReasonCode.READY
    assert recovered.opportunity is not None
