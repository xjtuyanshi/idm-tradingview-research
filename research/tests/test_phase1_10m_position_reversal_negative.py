from __future__ import annotations

from research.phase1_10m_position_reversal_oracle import (
    BandRole,
    Event,
    NamedBand,
    PositionReversalEngine,
    ReasonCode,
    SourceKind,
    State,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    PUBLISHED_AT_MS,
    VALID_UNTIL_MS,
    bar,
    prior_atr,
    resistance_band,
    support_band,
)


def test_touch_without_reclaim_expires_on_inclusive_third_bar() -> None:
    engine = PositionReversalEngine()
    target = resistance_band(lower_bound=7460.0, upper_bound=7460.0)
    bars = (
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        bar(12, 10, LOWER_TRIGGER, 7428.0, 7420.8, LOWER_TRIGGER),
        bar(12, 20, LOWER_TRIGGER, 7427.0, 7420.7, LOWER_TRIGGER),
    )

    first = engine.ingest(bars[0], (support_band(), target), prior_atr())
    second = engine.ingest(bars[1], (support_band(), target), prior_atr())
    third = engine.ingest(bars[2], (support_band(), target), prior_atr())

    assert first.event is Event.SUPPORT_WATCH
    assert first.reaction_bars_seen == 1
    assert second.event is Event.NONE
    assert second.reaction_bars_seen == 2
    assert third.event is Event.REACTION_EXPIRED
    assert third.state is State.EXPIRED
    assert third.reason_code is ReasonCode.REACTION_WINDOW_EXPIRED
    assert third.reaction_bars_seen == 3
    assert third.marker_text is None
    assert engine.opportunities == ()


def test_accepted_break_has_priority_over_touch_and_never_draws_watch_marker() -> None:
    engine = PositionReversalEngine()
    result = engine.ingest(
        bar(10, 0, 7430.0, 7432.0, 7412.0, 7415.5),
        (support_band(), resistance_band()),
        prior_atr(),
    )

    assert result.state is State.FAILED
    assert result.event is Event.ACCEPTED_BREAK
    assert result.reason_code is ReasonCode.ACCEPTED_BREAK
    assert result.watch_registered is True
    assert result.terminal_registered is True
    assert result.marker_text is None
    assert result.opportunity is None


def test_resistance_accepted_break_is_symmetric() -> None:
    engine = PositionReversalEngine()
    result = engine.ingest(
        bar(12, 0, 7460.0, 7475.0, 7458.0, 7470.0),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert result.state is State.FAILED
    assert result.event is Event.ACCEPTED_BREAK
    assert result.reason_code is ReasonCode.ACCEPTED_BREAK
    assert result.marker_text is None


def test_target_missing_keeps_reaction_description_but_never_ready() -> None:
    result = PositionReversalEngine().ingest(
        bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5),
        (support_band(),),
        prior_atr(),
    )

    assert result.event is Event.BOUNCE_CONFIRMED
    assert result.marker_text == "反弹确认"
    assert result.state is State.FAILED
    assert result.reason_code is ReasonCode.TARGET_MISSING
    assert result.opportunity is None


def test_nearest_target_consumed_on_confirmation_is_not_skipped() -> None:
    engine = PositionReversalEngine()
    nearest = resistance_band(
        source_id="SATY-ATR-NEAR-RESISTANCE",
        lower_bound=7445.0,
        upper_bound=7445.0,
    )
    farther = resistance_band(
        source_id="SATY-ATR-FAR-RESISTANCE",
        source_version="v2",
        lower_bound=7500.0,
        upper_bound=7500.0,
    )
    touch = engine.ingest(
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        (support_band(), nearest, farther),
        prior_atr(),
    )
    assert touch.target_candidate is not None
    assert touch.target_candidate.target_price == 7445.0

    confirm = engine.ingest(
        bar(12, 10, 7421.4, 7446.0, 7421.0, 7435.0),
        (support_band(), nearest, farther),
        prior_atr(),
    )
    assert confirm.event is Event.BOUNCE_CONFIRMED
    assert confirm.state is State.FAILED
    assert confirm.reason_code is ReasonCode.TARGET_CONSUMED
    assert confirm.target_candidate is not None
    assert confirm.target_candidate.target_price == 7445.0
    assert confirm.opportunity is None


def test_long_target_consumed_on_earlier_reaction_window_bar_never_becomes_ready() -> None:
    engine = PositionReversalEngine()
    target = resistance_band(
        source_id="SATY-ATR-REACTION-WINDOW-TARGET",
        lower_bound=7480.0,
        upper_bound=7480.0,
    )
    bands = (support_band(), target)

    touch = engine.ingest(
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        bands,
        prior_atr(),
    )
    consumed_early = engine.ingest(
        bar(12, 10, LOWER_TRIGGER, 7481.0, 7421.0, LOWER_TRIGGER),
        bands,
        prior_atr(),
    )
    reclaim = engine.ingest(
        bar(12, 20, LOWER_TRIGGER, 7435.0, 7421.0, 7434.0),
        bands,
        prior_atr(),
    )

    assert touch.event is Event.SUPPORT_WATCH
    assert consumed_early.event is Event.NONE
    assert consumed_early.episode_high == 7481.0
    assert reclaim.event is Event.BOUNCE_CONFIRMED
    assert reclaim.state is State.FAILED
    assert reclaim.reason_code is ReasonCode.TARGET_CONSUMED
    assert reclaim.episode_high == 7481.0
    assert reclaim.target_candidate is not None
    assert reclaim.target_candidate.target_price == 7480.0
    assert reclaim.opportunity is None
    assert engine.opportunities == ()


def test_short_target_consumed_on_earlier_reaction_window_bar_never_becomes_ready() -> None:
    engine = PositionReversalEngine()
    reaction = resistance_band(
        source_id="SATY-ATR-REACTION-WINDOW-RESISTANCE",
        lower_bound=7480.0,
        upper_bound=7480.0,
    )
    target = support_band(
        source_id="SATY-ATR-REACTION-WINDOW-TARGET",
        lower_bound=7400.0,
        upper_bound=7400.0,
    )
    bands = (target, reaction)

    touch = engine.ingest(
        bar(12, 0, 7470.0, 7480.2, 7460.0, 7480.0),
        bands,
        prior_atr(),
    )
    consumed_early = engine.ingest(
        bar(12, 10, 7480.0, 7481.0, 7399.0, 7480.0),
        bands,
        prior_atr(),
    )
    rejection = engine.ingest(
        bar(12, 20, 7479.0, 7479.5, 7455.0, 7460.0),
        bands,
        prior_atr(),
    )

    assert touch.event is Event.RESISTANCE_WATCH
    assert consumed_early.event is Event.NONE
    assert consumed_early.episode_low == 7399.0
    assert rejection.event is Event.REJECTION_CONFIRMED
    assert rejection.state is State.FAILED
    assert rejection.reason_code is ReasonCode.TARGET_CONSUMED
    assert rejection.episode_low == 7399.0
    assert rejection.target_candidate is not None
    assert rejection.target_candidate.target_price == 7400.0
    assert rejection.opportunity is None
    assert engine.opportunities == ()


def test_nearest_target_below_one_r_is_not_replaced_by_farther_target() -> None:
    near = resistance_band(
        source_id="SATY-ATR-NEAR-RESISTANCE",
        lower_bound=7445.0,
        upper_bound=7445.0,
    )
    far = resistance_band(
        source_id="SATY-ATR-FAR-RESISTANCE",
        source_version="v2",
        lower_bound=7540.0,
        upper_bound=7540.0,
    )
    result = PositionReversalEngine().ingest(
        bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5),
        (support_band(), near, far),
        prior_atr(),
    )

    assert result.event is Event.BOUNCE_CONFIRMED
    assert result.marker_text == "反弹确认"
    assert result.state is State.FAILED
    assert result.reason_code is ReasonCode.SPACE_LT_1R
    assert result.target_candidate is not None
    assert result.target_candidate.target_price == 7445.0
    assert result.opportunity is None


def test_same_bar_support_and_resistance_touch_fails_closed() -> None:
    close_resistance = NamedBand(
        source_id="SATY-ATR-CLOSE-RESISTANCE",
        source_version="v1",
        role=BandRole.RESISTANCE,
        lower_bound=7425.0,
        upper_bound=7425.0,
        published_at_ms=PUBLISHED_AT_MS,
        level_known_at_ms=PUBLISHED_AT_MS,
        source_kind=SourceKind.SATY_ATR_MAP_LEVEL,
        valid_until_ms=VALID_UNTIL_MS,
    )
    result = PositionReversalEngine().ingest(
        bar(12, 0, 7423.0, 7426.0, 7420.0, 7423.0),
        (support_band(), close_resistance),
        prior_atr(),
    )

    assert result.state is State.FAILED
    assert result.event is Event.POSITION_CONFLICT
    assert result.reason_code is ReasonCode.SIMULTANEOUS_POSITION_CONFLICT
    assert result.source_role is None
    assert result.marker_text is None
    assert result.opportunity is None
    assert result.episode_id is not None
    assert result.episode_id.startswith("PR-CONFLICT-")
    assert support_band().effective_fingerprint in result.episode_id
    assert close_resistance.effective_fingerprint in result.episode_id
    assert prior_atr().effective_fingerprint in result.episode_id


def test_multiple_same_side_touches_are_no_permission_not_direction_conflict() -> None:
    second_support = support_band(
        source_id="SATY-ATR-SECOND-SUPPORT",
        source_version="v2",
        lower_bound=7422.0,
        upper_bound=7422.0,
    )
    result = PositionReversalEngine().ingest(
        bar(12, 0, 7423.0, 7430.0, 7420.9, 7423.0),
        (support_band(), second_support, resistance_band()),
        prior_atr(),
    )

    assert result.state is State.FAILED
    assert result.event is Event.MULTIPLE_SAME_SIDE
    assert result.reason_code is ReasonCode.MULTIPLE_SAME_SIDE_NO_PERMISSION
    assert result.source_role is BandRole.SUPPORT
    assert result.marker_text is None
    assert result.opportunity is None
    assert result.episode_id is not None
    assert result.episode_id.startswith("PR-MULTIPLE-SAME-SIDE-")
    assert support_band().effective_fingerprint in result.episode_id
    assert second_support.effective_fingerprint in result.episode_id
    assert prior_atr().effective_fingerprint in result.episode_id


def test_multiple_same_side_resistance_touches_are_also_no_permission() -> None:
    second_resistance = resistance_band(
        source_id="SATY-ATR-SECOND-RESISTANCE",
        source_version="v2",
        lower_bound=7466.0,
        upper_bound=7466.0,
    )
    result = PositionReversalEngine().ingest(
        bar(9, 30, 7470.0, 7480.0, 7455.0, 7465.0),
        (support_band(), resistance_band(), second_resistance),
        prior_atr(),
    )

    assert result.state is State.FAILED
    assert result.event is Event.MULTIPLE_SAME_SIDE
    assert result.reason_code is ReasonCode.MULTIPLE_SAME_SIDE_NO_PERMISSION
    assert result.source_role is BandRole.RESISTANCE
    assert result.marker_text is None
    assert result.opportunity is None
    assert result.episode_id is not None
    assert result.episode_id.startswith("PR-MULTIPLE-SAME-SIDE-")
    assert resistance_band().effective_fingerprint in result.episode_id
    assert second_resistance.effective_fingerprint in result.episode_id
    assert prior_atr().effective_fingerprint in result.episode_id
