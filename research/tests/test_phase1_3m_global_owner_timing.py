from __future__ import annotations

from dataclasses import replace

import pytest

from research.phase1_3m_global_owner_oracle import (
    Direction,
    LaneId,
    OwnerEvent,
    OwnerManager,
    OwnerReason,
    OwnerState,
    ProducerTerminal,
    ProducerTerminalKind,
)
from research.tests.fixture_phase1_3m_global_owner import (
    accepted_july31_1140_space_lt_1r_boundary,
    bar3,
    candidate,
    et_ms,
)


def _adopt_immediate_long(manager: OwnerManager) -> None:
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    result = manager.ingest(
        bar3(9, 42, 100.0, 102.0, 99.0, 101.0),
        candidates=(value,),
    )
    assert result.state is OwnerState.WAIT_IMMEDIATE_CONFIRM
    assert result.event is OwnerEvent.NONE


def _adopt_immediate_short(manager: OwnerManager) -> None:
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        trigger=100.0,
        stop=105.0,
        target=90.0,
    )
    result = manager.ingest(
        bar3(9, 42, 100.0, 101.0, 98.0, 99.0, ema5=99.0, ema12=100.0),
        candidates=(value,),
    )
    assert result.state is OwnerState.WAIT_IMMEDIATE_CONFIRM


def test_reversal_immediate_confirm_long_and_short_enter_only_next_bar() -> None:
    long_manager = OwnerManager()
    _adopt_immediate_long(long_manager)
    long_entry = long_manager.ingest(
        bar3(9, 45, 101.0, 101.5, 100.0, 100.8, ema5=101.0, ema12=100.0)
    )
    assert long_entry.event is OwnerEvent.LONG_ENTRY
    assert long_entry.state is OwnerState.ENTERED

    short_manager = OwnerManager()
    _adopt_immediate_short(short_manager)
    short_entry = short_manager.ingest(
        bar3(9, 45, 99.0, 100.0, 98.5, 99.2, ema5=99.0, ema12=100.0)
    )
    assert short_entry.event is OwnerEvent.SHORT_ENTRY
    assert short_entry.state is OwnerState.ENTERED


def test_immediate_confirm_extension_or_ema_failure_is_final_missed() -> None:
    manager = OwnerManager()
    _adopt_immediate_long(manager)
    missed = manager.ingest(
        bar3(9, 45, 101.0, 103.0, 100.0, 102.1, ema5=101.0, ema12=100.0)
    )
    assert missed.event is OwnerEvent.MISSED
    assert missed.reason_code is OwnerReason.IMMEDIATE_CONFIRM_MISSED
    assert manager.owner is None

    manager2 = OwnerManager()
    _adopt_immediate_long(manager2)
    missed2 = manager2.ingest(
        bar3(9, 45, 101.0, 101.5, 100.0, 100.8, ema5=99.0, ema12=100.0)
    )
    assert missed2.event is OwnerEvent.MISSED
    assert manager2.owner is None


def test_adoption_equal_trigger_selects_fresh_cross_and_first_cross_enters() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        stop=90.0,
        target=111.0,
    )
    adoption = manager.ingest(
        bar3(9, 42, 99.5, 101.0, 99.0, 100.0),
        candidates=(value,),
    )
    assert adoption.state is OwnerState.WAIT_FRESH_CROSS

    entry = manager.ingest(
        bar3(9, 45, 100.0, 101.0, 99.8, 100.5, ema5=101.0, ema12=100.0)
    )
    assert entry.event is OwnerEvent.LONG_ENTRY
    assert entry.remaining_r == pytest.approx(1.0)


def test_fresh_cross_waits_for_discrete_event_and_first_failed_cross_never_recrosses() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    manager.ingest(bar3(9, 42, close=99.5), candidates=(value,))
    waiting = manager.ingest(bar3(9, 45, close=99.8))
    assert waiting.reason_code is OwnerReason.WAIT_FIRST_FRESH_CROSS

    first_cross_bad_ema = manager.ingest(
        bar3(9, 48, close=100.5, ema5=99.0, ema12=100.0)
    )
    assert first_cross_bad_ema.event is OwnerEvent.MISSED
    assert first_cross_bad_ema.reason_code is OwnerReason.FIRST_CROSS_MISSED
    assert manager.owner is None

    later = manager.ingest(bar3(9, 51, close=101.0))
    assert later.event is OwnerEvent.NONE
    assert later.reason_code is OwnerReason.WAIT_10M


def test_exact_one_r_passes_and_sub_one_r_is_permanently_missed() -> None:
    exact = OwnerManager()
    exact_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        stop=90.0,
        target=111.0,
    )
    exact.ingest(bar3(9, 42, close=100.0), candidates=(exact_candidate,))
    passed = exact.ingest(bar3(9, 45, close=100.5, ema5=101.0, ema12=100.0))
    assert passed.event is OwnerEvent.LONG_ENTRY
    assert passed.remaining_r == pytest.approx(1.0)

    sub = OwnerManager()
    sub_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-sub",
        fingerprint="fp-sub",
        trigger=100.0,
        stop=90.0,
        target=110.9,
    )
    sub.ingest(bar3(9, 42, close=100.0), candidates=(sub_candidate,))
    failed = sub.ingest(bar3(9, 45, close=100.5, ema5=101.0, ema12=100.0))
    assert failed.event is OwnerEvent.MISSED
    assert failed.reason_code is OwnerReason.SPACE_LT_1R
    assert sub.owner is None


def test_permission_and_context_equality_expire_before_cross() -> None:
    permission = OwnerManager()
    permission_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        permission_expires_at_ms=et_ms(9, 45),
    )
    permission.ingest(bar3(9, 42, close=99.5), candidates=(permission_candidate,))
    expired = permission.ingest(bar3(9, 45, close=100.5))
    assert expired.event is OwnerEvent.EXPIRED
    assert expired.reason_code is OwnerReason.PERMISSION_EXPIRED

    context = OwnerManager()
    context_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-context",
        fingerprint="fp-context",
        trigger=100.0,
        context_valid_until_ms=et_ms(9, 48),
    )
    context.ingest(bar3(9, 42, close=99.5), candidates=(context_candidate,))
    expired_context = context.ingest(bar3(9, 45, close=100.5))
    assert expired_context.event is OwnerEvent.EXPIRED
    assert expired_context.reason_code is OwnerReason.CONTEXT_EXPIRED


def test_expiry_plus_cross_and_terminal_plus_cross_cannot_enter() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        permission_expires_at_ms=et_ms(9, 45),
    )
    manager.ingest(bar3(9, 42, close=99.5), candidates=(value,))
    result = manager.ingest(bar3(9, 45, high=101.0, low=99.0, close=100.5))
    assert result.event is OwnerEvent.EXPIRED

    terminal = OwnerManager()
    terminal_value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-terminal",
        fingerprint="fp-terminal",
        trigger=100.0,
        stop=99.0,
        target=110.0,
        overlap=bar3(9, 39, open_=99.5, high=100.0, low=99.1, close=99.5),
    )
    terminal.ingest(bar3(9, 42, close=99.5, low=99.1), candidates=(terminal_value,))
    stopped = terminal.ingest(bar3(9, 45, high=101.0, low=98.9, close=100.5))
    assert stopped.event is OwnerEvent.INVALIDATED
    assert stopped.reason_code is OwnerReason.OPPORTUNITY_INVALIDATED


def test_stop_and_target_same_entry_bar_is_stop_first_for_reversal() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        trigger=100.0,
        stop=99.0,
        target=101.0,
        overlap=bar3(9, 39, open_=99.5, high=100.0, low=99.1, close=99.5),
    )
    manager.ingest(bar3(9, 42, high=100.5, low=99.1, close=99.5), candidates=(value,))
    result = manager.ingest(bar3(9, 45, high=101.1, low=98.9, close=100.5))
    assert result.event is OwnerEvent.INVALIDATED


def test_trend_keeps_pullback_then_later_trigger_and_eight_bar_lifetime() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        trigger=99.0,
        stop=90.0,
        target=120.0,
    )
    adoption = manager.ingest(bar3(9, 42, close=101.0), candidates=(value,))
    assert adoption.state is OwnerState.WAIT_PULLBACK

    pullback = manager.ingest(
        bar3(9, 45, open_=101.0, high=102.0, low=99.9, close=100.5, ema5=101.0, ema12=100.0)
    )
    assert pullback.state is OwnerState.WAIT_TRIGGER
    assert pullback.reason_code is OwnerReason.PULLBACK_FROZEN
    assert pullback.event is OwnerEvent.NONE

    entry = manager.ingest(
        bar3(9, 48, open_=100.5, high=103.0, low=100.0, close=102.5, ema5=102.0, ema12=101.0)
    )
    assert entry.event is OwnerEvent.LONG_ENTRY


def test_gap_before_immediate_confirm_is_global_reset_not_late_entry() -> None:
    manager = OwnerManager()
    _adopt_immediate_long(manager)
    gap = manager.ingest(bar3(9, 48, close=100.8))
    assert gap.event is OwnerEvent.DATA_RESET
    assert gap.reason_code is OwnerReason.DATA_GAP_RESET
    assert manager.owner is None


def test_accepted_july31_1140_space_lt_1r_boundary_creates_no_envelope_or_entry() -> None:
    observation, engine = accepted_july31_1140_space_lt_1r_boundary()
    assert observation.opportunity is None
    assert engine.opportunities == ()

    manager = OwnerManager()
    no_adoption = manager.ingest(bar3(11, 42), candidates=())
    assert no_adoption.event is OwnerEvent.NONE
    assert no_adoption.reason_code is OwnerReason.WAIT_10M
    later = manager.ingest(bar3(11, 45, open_=7495.0, close=7500.0, high=7501.0, low=7490.0))
    assert later.event is OwnerEvent.NONE
    assert manager.owner is None


def test_reversal_fresh_cross_short_passes_once_and_failed_first_cross_cannot_recross() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        opportunity_id="PR-S-fresh",
        fingerprint="fp-PR-S-fresh",
        trigger=100.0,
        stop=105.0,
        target=94.0,
    )
    adoption = manager.ingest(
        bar3(9, 42, close=100.0, ema5=99.0, ema12=100.0),
        candidates=(value,),
    )
    assert adoption.state is OwnerState.WAIT_FRESH_CROSS
    entry = manager.ingest(
        bar3(9, 45, close=99.5, ema5=99.0, ema12=100.0)
    )
    assert entry.event is OwnerEvent.SHORT_ENTRY
    assert entry.remaining_r == pytest.approx(1.0)

    failed = OwnerManager()
    failed_value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        opportunity_id="PR-S-fresh-fail",
        fingerprint="fp-PR-S-fresh-fail",
        trigger=100.0,
        stop=105.0,
        target=90.0,
    )
    failed.ingest(
        bar3(9, 42, close=100.0, ema5=99.0, ema12=100.0),
        candidates=(failed_value,),
    )
    first = failed.ingest(
        bar3(9, 45, close=99.5, ema5=101.0, ema12=100.0)
    )
    assert first.event is OwnerEvent.MISSED
    assert first.reason_code is OwnerReason.FIRST_CROSS_MISSED
    later = failed.ingest(
        bar3(9, 48, close=99.0, ema5=99.0, ema12=100.0)
    )
    assert later.event is OwnerEvent.NONE
    assert later.reason_code is OwnerReason.WAIT_10M


def test_exact_producer_expiry_on_first_cross_bar_precedes_entry() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-producer-expiry",
        fingerprint="fp-PR-L-producer-expiry",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    manager.ingest(bar3(9, 42, close=99.5), candidates=(value,))
    terminal = ProducerTerminal(
        lane_id=value.envelope.lane_id,
        opportunity_id=value.envelope.opportunity_id,
        payload_fingerprint=value.envelope.payload_fingerprint,
        kind=ProducerTerminalKind.EXPIRED,
    )
    result = manager.ingest(
        bar3(9, 45, close=100.5, ema5=101.0, ema12=100.0),
        producer_terminals=(terminal,),
    )
    assert result.event is OwnerEvent.EXPIRED
    assert result.reason_code is OwnerReason.PRODUCER_EXPIRED
    assert manager.owner is None


def test_trend_trigger_allows_eight_later_bars_and_expires_on_ninth() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-eight-bars",
        fingerprint="fp-TC-eight-bars",
        stop=90.0,
        target=120.0,
    )
    manager.ingest(
        bar3(9, 42, open_=103.0, high=104.0, low=102.0, close=103.0),
        candidates=(value,),
    )
    pullback = manager.ingest(
        bar3(9, 45, open_=103.0, high=104.0, low=100.0, close=103.0)
    )
    assert pullback.state is OwnerState.WAIT_TRIGGER

    later_times = ((9, 48), (9, 51), (9, 54), (9, 57), (10, 0), (10, 3), (10, 6), (10, 9))
    for index, (hour, minute) in enumerate(later_times, start=1):
        waiting = manager.ingest(
            bar3(hour, minute, open_=103.0, high=103.5, low=102.0, close=103.0)
        )
        assert waiting.event is OwnerEvent.NONE, index
        assert waiting.reason_code is OwnerReason.WAIT_LATER_TRIGGER, index
        assert manager.owner == value.envelope

    ninth = manager.ingest(
        bar3(10, 12, open_=103.0, high=103.5, low=102.0, close=103.0)
    )
    assert ninth.event is OwnerEvent.EXPIRED
    assert ninth.reason_code is OwnerReason.TREND_TRIGGER_EXPIRED
    assert manager.owner is None


def test_adoption_permission_or_context_equality_suppresses_without_owner() -> None:
    permission_manager = OwnerManager()
    permission = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-adopt-expired",
        fingerprint="fp-PR-adopt-expired",
        permission_expires_at_ms=et_ms(9, 42),
    )
    result = permission_manager.ingest(bar3(9, 42), candidates=(permission,))
    assert result.event is OwnerEvent.NONE
    assert result.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert permission_manager.owner is None
    assert permission.envelope.full_identity in permission_manager.suppressed_identities

    context_manager = OwnerManager()
    context = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-adopt-context-expired",
        fingerprint="fp-PR-adopt-context-expired",
        context_valid_until_ms=et_ms(9, 45),
    )
    context_result = context_manager.ingest(bar3(9, 42), candidates=(context,))
    assert context_result.event is OwnerEvent.NONE
    assert context_result.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert context_manager.owner is None
    assert context.envelope.full_identity in context_manager.suppressed_identities


def test_trend_short_preserves_pullback_then_later_confirmed_trigger() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.SHORT,
        opportunity_id="TC-S-global",
        fingerprint="fp-TC-S-global",
        trigger=101.0,
        stop=110.0,
        target=80.0,
    )
    adoption = manager.ingest(
        bar3(
            9,
            42,
            open_=100.0,
            high=101.0,
            low=98.5,
            close=99.0,
            ema5=99.0,
            ema12=100.0,
        ),
        candidates=(value,),
    )
    assert adoption.state is OwnerState.WAIT_PULLBACK

    pullback = manager.ingest(
        bar3(
            9,
            45,
            open_=99.0,
            high=100.5,
            low=98.5,
            close=99.5,
            ema5=99.0,
            ema12=100.0,
        )
    )
    assert pullback.state is OwnerState.WAIT_TRIGGER
    assert pullback.reason_code is OwnerReason.PULLBACK_FROZEN
    assert pullback.event is OwnerEvent.NONE

    entry = manager.ingest(
        bar3(
            9,
            48,
            open_=99.0,
            high=99.2,
            low=97.5,
            close=98.0,
            ema5=99.0,
            ema12=100.0,
        )
    )
    assert entry.event is OwnerEvent.SHORT_ENTRY
    assert entry.state is OwnerState.ENTERED
