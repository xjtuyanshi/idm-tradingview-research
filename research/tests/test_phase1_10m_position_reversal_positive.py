from __future__ import annotations

import pytest

from research.phase1_10m_position_reversal_oracle import (
    Direction,
    Event,
    PositionReversalEngine,
    ReasonCode,
    State,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    UPPER_TRIGGER,
    et_ms,
    july31_mandatory_replay,
)


def test_july31_required_short_and_long_are_visible_only_at_10m_close() -> None:
    bars, bands_by_bar, atr_by_bar = july31_mandatory_replay()
    engine = PositionReversalEngine()
    observations = [
        engine.ingest(bar, bands, atr)
        for bar, bands, atr in zip(
            bars, bands_by_bar, atr_by_bar, strict=True
        )
    ]

    opening = observations[0]
    assert opening.state is State.READY
    assert opening.event is Event.REJECTION_CONFIRMED
    assert opening.reason_code is ReasonCode.READY
    assert opening.marker_text == "空头确认"
    assert opening.watch_registered is True
    assert opening.terminal_registered is True
    assert opening.bar_time_ms == et_ms(9, 30)
    assert opening.visible_at_ms == et_ms(9, 40)
    assert opening.opportunity is not None
    assert opening.opportunity.direction is Direction.SHORT
    assert opening.opportunity.trigger == pytest.approx(7462.8)
    assert opening.opportunity.target == pytest.approx(LOWER_TRIGGER)
    assert opening.opportunity.target_source == "CID1:SATY-ATR-LOWER-TRIGGER@v1"
    assert opening.opportunity.space_r >= 1.0

    accepted_break = observations[3]
    assert accepted_break.bar_time_ms == et_ms(10, 0)
    assert accepted_break.state is State.FAILED
    assert accepted_break.event is Event.ACCEPTED_BREAK
    assert accepted_break.reason_code is ReasonCode.ACCEPTED_BREAK
    assert accepted_break.marker_text is None

    reclaim_after_break = observations[5]
    assert reclaim_after_break.bar_time_ms == et_ms(10, 20)
    assert reclaim_after_break.state is State.WAIT_CLEAR
    assert reclaim_after_break.event is Event.NONE
    assert reclaim_after_break.reason_code is ReasonCode.WAIT_CLEAR_REQUIRED
    assert reclaim_after_break.marker_text is None
    assert reclaim_after_break.opportunity is None

    clear = observations[6]
    assert clear.bar_time_ms == et_ms(10, 30)
    assert clear.event is Event.WAIT_CLEAR_COMPLETED
    assert clear.reason_code is ReasonCode.WAIT_CLEAR_COMPLETED
    assert clear.marker_text is None

    lower = observations[-1]
    assert lower.state is State.READY
    assert lower.event is Event.BOUNCE_CONFIRMED
    assert lower.reason_code is ReasonCode.READY
    assert lower.marker_text == "多头确认"
    assert lower.watch_registered is True
    assert lower.terminal_registered is True
    assert lower.bar_time_ms == et_ms(11, 30)
    assert lower.visible_at_ms == et_ms(11, 40)
    assert lower.opportunity is not None
    assert lower.opportunity.direction is Direction.LONG
    assert lower.opportunity.trigger == pytest.approx(7443.8)
    assert lower.opportunity.invalidation == pytest.approx(7420.7)
    assert lower.opportunity.target == pytest.approx(UPPER_TRIGGER)
    assert lower.opportunity.target_source == "CID1:SATY-ATR-UPPER-TRIGGER@v1"
    assert lower.opportunity.space_r >= 1.0

    assert len(engine.opportunities) == 2
    assert engine.opportunities[0] == opening.opportunity
    assert engine.opportunities[1] == lower.opportunity


def test_same_bar_touch_and_reaction_uses_one_terminal_marker() -> None:
    bars, bands_by_bar, atr_by_bar = july31_mandatory_replay()
    engine = PositionReversalEngine()
    opening = engine.ingest(bars[0], bands_by_bar[0], atr_by_bar[0])

    assert opening.watch_registered is True
    assert opening.terminal_registered is True
    assert opening.marker_text == "空头确认"
    assert opening.event is Event.REJECTION_CONFIRMED
    assert opening.state is State.READY
