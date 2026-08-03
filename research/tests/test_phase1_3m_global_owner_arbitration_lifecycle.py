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
from research.tests.fixture_phase1_3m_global_owner import bar3, candidate, et_ms


def _enter_reversal_long(manager: OwnerManager, *, opportunity_id: str = "PR-enter"):
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id=opportunity_id,
        fingerprint=f"fp-{opportunity_id}",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    manager.ingest(
        bar3(9, 42, open_=100.0, high=102.0, low=99.0, close=101.0),
        candidates=(value,),
    )
    entered = manager.ingest(
        bar3(9, 45, open_=101.0, high=101.5, low=100.0, close=100.8)
    )
    assert entered.event is OwnerEvent.LONG_ENTRY
    return value


def test_unentered_owner_is_not_replaced_and_same_direction_candidate_is_not_queued() -> None:
    manager = OwnerManager()
    trend = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    adopted = manager.ingest(bar3(9, 42), candidates=(trend,))
    assert adopted.state is OwnerState.WAIT_PULLBACK

    same_direction = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-blocked",
        fingerprint="fp-PR-L-blocked",
    )
    retained = manager.ingest(bar3(9, 45), candidates=(same_direction,))
    assert manager.owner == trend.envelope
    assert retained.event is OwnerEvent.NONE
    assert same_direction.envelope.full_identity in manager.suppressed_identities

    # End the original owner on a later bar.  The blocked same-direction plan
    # cannot be adopted from a persistent/repeated producer state after release.
    terminal_bar = manager.ingest(
        bar3(9, 48, open_=96.0, high=97.0, low=94.0, close=94.9)
    )
    assert terminal_bar.event is OwnerEvent.INVALIDATED
    repeated = manager.ingest(bar3(9, 51), candidates=(same_direction,))
    assert repeated.event is OwnerEvent.NONE
    assert repeated.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert manager.owner is None


def test_terminal_bar_candidate_is_seen_suppressed_and_cannot_adopt_next_bar() -> None:
    manager = OwnerManager()
    old = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-old",
        fingerprint="fp-old",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    manager.ingest(bar3(9, 42, high=102.0, close=101.0), candidates=(old,))

    new = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.SHORT,
        opportunity_id="TC-new",
        fingerprint="fp-new",
    )
    terminal = manager.ingest(
        bar3(9, 45, open_=96.0, high=97.0, low=94.0, close=94.9),
        candidates=(new,),
    )
    assert terminal.event is OwnerEvent.INVALIDATED
    assert new.envelope.full_identity in manager.suppressed_identities

    later = manager.ingest(bar3(9, 48), candidates=(new,))
    assert later.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert manager.owner is None


def test_base_id_collision_tombstone_rejects_original_second_and_third_fingerprint() -> None:
    manager = OwnerManager()
    first = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="BASE",
        fingerprint="fp-1",
    )
    manager.ingest(bar3(9, 42), candidates=(first,))

    second = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="BASE",
        fingerprint="fp-2",
    )
    collision = manager.ingest(bar3(9, 45), candidates=(second,))
    assert collision.event is OwnerEvent.MISSED
    assert collision.reason_code is OwnerReason.IDENTITY_COLLISION
    assert (LaneId.TREND_CONTINUATION, "BASE") in manager.collision_tombstones
    assert first.envelope.full_identity in manager.suppressed_identities
    assert second.envelope.full_identity in manager.suppressed_identities

    third = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="BASE",
        fingerprint="fp-3",
    )
    rejected = manager.ingest(bar3(9, 48), candidates=(third,))
    assert rejected.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert third.envelope.full_identity in manager.suppressed_identities
    assert manager.owner is None


def test_same_direction_earlier_visible_wins_and_exact_tie_prefers_trend() -> None:
    earlier = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-earlier",
        fingerprint="fp-earlier",
        confirmation_time_ms=et_ms(9, 20),
        visible_at_ms=et_ms(9, 30),
    )
    later = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-later",
        fingerprint="fp-later",
    )
    manager = OwnerManager()
    result = manager.ingest(bar3(9, 42), candidates=(later, earlier))
    assert result.lane_id is LaneId.POSITION_REVERSAL
    assert manager.owner == earlier.envelope
    assert later.envelope.full_identity in manager.suppressed_identities

    tie_trend = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-tie",
        fingerprint="fp-TC-tie",
    )
    tie_reversal = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-tie",
        fingerprint="fp-PR-tie",
    )
    manager2 = OwnerManager()
    tie = manager2.ingest(bar3(9, 42), candidates=(tie_reversal, tie_trend))
    assert tie.lane_id is LaneId.TREND_CONTINUATION
    assert manager2.owner == tie_trend.envelope


def test_opposite_direction_same_bar_conflict_suppresses_both() -> None:
    long = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    short = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        opportunity_id="PR-S-conflict",
        fingerprint="fp-conflict",
    )
    manager = OwnerManager()
    result = manager.ingest(bar3(9, 42), candidates=(long, short))

    assert result.event is OwnerEvent.CONFLICT
    assert result.reason_code is OwnerReason.OPPOSITE_DIRECTION_CONFLICT
    assert manager.owner is None
    assert long.envelope.full_identity in manager.suppressed_identities
    assert short.envelope.full_identity in manager.suppressed_identities


def test_entered_owner_ignores_closed_nonterminal_lane_events_and_new_plans() -> None:
    manager = OwnerManager()
    owner_candidate = _enter_reversal_long(manager)
    identity = owner_candidate.envelope
    kinds = (
        ProducerTerminalKind.EXPIRED,
        ProducerTerminalKind.ACTIVE_NONE,
        ProducerTerminalKind.PERMISSION_EXPIRED,
        ProducerTerminalKind.CONTEXT_EXPIRED,
        ProducerTerminalKind.SOURCE_INVALID,
        ProducerTerminalKind.IDENTITY_DRIFT,
        ProducerTerminalKind.SUPPRESSED,
        ProducerTerminalKind.CONTEXT_RESET,
        ProducerTerminalKind.DATA_RESET,
    )
    minute = 48
    for index, kind in enumerate(kinds):
        new = candidate(
            LaneId.TREND_CONTINUATION,
            Direction.SHORT,
            opportunity_id=f"new-{index}",
            fingerprint=f"new-fp-{index}",
        )
        terminal = ProducerTerminal(
            lane_id=identity.lane_id,
            opportunity_id=identity.opportunity_id,
            payload_fingerprint=identity.payload_fingerprint,
            kind=kind,
        )
        result = manager.ingest(
            bar3(9 + (minute // 60), minute % 60, open_=100.0, high=101.0, low=99.0, close=100.0),
            candidates=(new,),
            producer_terminals=(terminal,),
        )
        assert result.reason_code is OwnerReason.OWNER_RETAINED
        assert result.event is OwnerEvent.NONE
        assert manager.owner == identity
        minute += 3


def test_exact_invalidated_and_target_pulses_settle_but_wrong_identity_cannot() -> None:
    manager = OwnerManager()
    owner_candidate = _enter_reversal_long(manager)
    owner = owner_candidate.envelope

    wrong = ProducerTerminal(
        lane_id=owner.lane_id,
        opportunity_id=owner.opportunity_id,
        payload_fingerprint="wrong",
        kind=ProducerTerminalKind.INVALIDATED,
    )
    ignored = manager.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0),
        producer_terminals=(wrong,),
    )
    assert ignored.reason_code is OwnerReason.OWNER_RETAINED

    exact = replace(wrong, payload_fingerprint=owner.payload_fingerprint)
    closed = manager.ingest(
        bar3(9, 51, open_=100.0, high=101.0, low=99.0, close=100.0),
        producer_terminals=(exact,),
    )
    assert closed.event is OwnerEvent.INVALIDATED
    assert manager.owner is None

    manager2 = OwnerManager()
    second = _enter_reversal_long(manager2, opportunity_id="PR-target")
    target = ProducerTerminal(
        lane_id=second.envelope.lane_id,
        opportunity_id=second.envelope.opportunity_id,
        payload_fingerprint=second.envelope.payload_fingerprint,
        kind=ProducerTerminalKind.TARGET_REACHED,
    )
    hit = manager2.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0),
        producer_terminals=(target,),
    )
    assert hit.event is OwnerEvent.TARGET_REACHED


def test_unentered_exact_expired_ends_before_timing() -> None:
    manager = OwnerManager()
    value = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    manager.ingest(bar3(9, 42), candidates=(value,))
    expired = ProducerTerminal(
        lane_id=value.envelope.lane_id,
        opportunity_id=value.envelope.opportunity_id,
        payload_fingerprint=value.envelope.payload_fingerprint,
        kind=ProducerTerminalKind.EXPIRED,
    )
    result = manager.ingest(bar3(9, 45), producer_terminals=(expired,))
    assert result.event is OwnerEvent.EXPIRED
    assert result.reason_code is OwnerReason.PRODUCER_EXPIRED
    assert manager.owner is None


def _prepare_trend_long_for_0951_entry(
    manager: OwnerManager,
):
    owner = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-later-conflict-owner",
        fingerprint="fp-TC-later-conflict-owner",
        stop=95.0,
        target=110.0,
    )
    adopted = manager.ingest(
        bar3(9, 42, open_=100.0, high=101.0, low=99.0, close=100.0),
        candidates=(owner,),
    )
    assert adopted.state is OwnerState.WAIT_PULLBACK
    pullback = manager.ingest(
        bar3(9, 45, open_=100.0, high=101.0, low=99.0, close=100.0)
    )
    assert pullback.state is OwnerState.WAIT_TRIGGER
    waiting = manager.ingest(
        bar3(
            9,
            48,
            open_=100.0,
            high=100.8,
            low=99.5,
            close=100.4,
            ema5=100.5,
            ema12=99.8,
        )
    )
    assert waiting.state is OwnerState.WAIT_TRIGGER
    assert waiting.event is OwnerEvent.NONE
    return owner


def _candidate_visible_at_0950(
    direction: Direction, *, opportunity_id: str
):
    return candidate(
        LaneId.POSITION_REVERSAL,
        direction,
        adoption_time=(9, 51),
        overlap=bar3(
            9,
            48,
            open_=100.0,
            high=100.8,
            low=99.5,
            close=100.4,
        ),
        opportunity_id=opportunity_id,
        fingerprint=f"fp-{opportunity_id}",
        trigger=101.0,
        stop=106.0 if direction is Direction.SHORT else 95.0,
        target=90.0 if direction is Direction.SHORT else 115.0,
        confirmation_time_ms=et_ms(9, 40),
        visible_at_ms=et_ms(9, 50),
        permission_expires_at_ms=et_ms(11, 50),
    )


def test_later_eligible_opposite_candidate_on_old_entry_bar_conflicts_before_timing() -> None:
    manager = OwnerManager()
    old = _prepare_trend_long_for_0951_entry(manager)
    opposite = _candidate_visible_at_0950(
        Direction.SHORT, opportunity_id="PR-S-later-conflict"
    )

    conflict = manager.ingest(
        bar3(
            9,
            51,
            open_=100.5,
            high=102.0,
            low=100.0,
            close=101.6,
            ema5=101.2,
            ema12=100.8,
        ),
        candidates=(opposite,),
    )

    assert conflict.event is OwnerEvent.CONFLICT
    assert conflict.reason_code is OwnerReason.OPPOSITE_DIRECTION_CONFLICT
    assert conflict.event is not OwnerEvent.LONG_ENTRY
    assert manager.owner is None
    assert old.envelope.full_identity in manager.suppressed_identities
    assert opposite.envelope.full_identity in manager.suppressed_identities


def test_later_same_direction_candidate_does_not_block_old_owner_entry() -> None:
    manager = OwnerManager()
    old = _prepare_trend_long_for_0951_entry(manager)
    same_direction = _candidate_visible_at_0950(
        Direction.LONG, opportunity_id="PR-L-later-same-direction"
    )

    entry = manager.ingest(
        bar3(
            9,
            51,
            open_=100.5,
            high=102.0,
            low=100.0,
            close=101.6,
            ema5=101.2,
            ema12=100.8,
        ),
        candidates=(same_direction,),
    )

    assert entry.event is OwnerEvent.LONG_ENTRY
    assert entry.state is OwnerState.ENTERED
    assert manager.owner == old.envelope
    assert same_direction.envelope.full_identity in manager.suppressed_identities


def test_entered_owner_ignores_later_eligible_opposite_candidate() -> None:
    manager = OwnerManager()
    entered_owner = _enter_reversal_long(manager, opportunity_id="PR-entered-retain")
    first_retained = manager.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0)
    )
    assert first_retained.reason_code is OwnerReason.OWNER_RETAINED

    opposite = _candidate_visible_at_0950(
        Direction.SHORT, opportunity_id="PR-S-after-entered"
    )
    retained = manager.ingest(
        bar3(9, 51, open_=100.0, high=101.0, low=99.0, close=100.0),
        candidates=(opposite,),
    )

    assert retained.event is OwnerEvent.NONE
    assert retained.reason_code is OwnerReason.OWNER_RETAINED
    assert manager.owner == entered_owner.envelope
    assert opposite.envelope.full_identity in manager.suppressed_identities


def test_entry_pulse_bar_and_retained_bar_are_distinct_observations() -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-card-state",
        fingerprint="fp-PR-card-state",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    manager.ingest(
        bar3(9, 42, open_=100.0, high=102.0, low=99.0, close=101.0),
        candidates=(value,),
    )
    pulse = manager.ingest(
        bar3(9, 45, open_=101.0, high=101.5, low=100.0, close=100.8)
    )
    retained = manager.ingest(
        bar3(9, 48, open_=100.8, high=101.2, low=99.8, close=100.5)
    )

    assert pulse.event is OwnerEvent.LONG_ENTRY
    assert pulse.reason_code is OwnerReason.ENTRY_CONFIRMED
    assert retained.event is OwnerEvent.NONE
    assert retained.state is OwnerState.ENTERED
    assert retained.reason_code is OwnerReason.OWNER_RETAINED


def test_terminal_snapshot_is_one_bar_and_next_wait_bar_clears_plan_values() -> None:
    manager = OwnerManager()
    value = _enter_reversal_long(manager, opportunity_id="PR-terminal-snapshot")
    terminal = manager.ingest(
        bar3(9, 48, open_=100.0, high=110.5, low=99.0, close=109.5)
    )

    assert terminal.event is OwnerEvent.TARGET_REACHED
    # Terminal-bar audit state matches Pine: the owner has already returned to
    # WAIT_10M even though the immutable terminal snapshot still explains the plan.
    assert terminal.state is OwnerState.WAIT_10M
    assert manager.state is OwnerState.WAIT_10M
    assert terminal.lane_id is value.envelope.lane_id
    assert terminal.invalidation == value.envelope.invalidation
    assert terminal.target == value.envelope.target
    assert terminal.entry_price is not None
    assert terminal.remaining_r is not None

    waiting = manager.ingest(bar3(9, 51))
    assert waiting.event is OwnerEvent.NONE
    assert waiting.reason_code is OwnerReason.WAIT_10M
    assert waiting.lane_id is None
    assert waiting.invalidation is None
    assert waiting.target is None
    assert waiting.entry_price is None
    assert waiting.remaining_r is None

    new_owner = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        adoption_time=(9, 54),
        opportunity_id="TC-after-terminal",
        fingerprint="fp-TC-after-terminal",
    )
    adopted = manager.ingest(bar3(9, 54), candidates=(new_owner,))
    assert adopted.reason_code is OwnerReason.NEW_TREND_OWNER
    assert adopted.entry_price is None
    assert adopted.remaining_r is None


def test_global_reset_bar_suppresses_owner_and_candidate_without_price_terminal_marker() -> None:
    manager = OwnerManager()
    old = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    manager.ingest(bar3(9, 42), candidates=(old,))
    new = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        opportunity_id="PR-reset",
        fingerprint="fp-reset",
    )
    reset = manager.ingest(
        bar3(9, 45, symbol="OTHER"),
        candidates=(new,),
    )
    assert reset.event is OwnerEvent.DATA_RESET
    assert reset.marker_price is None
    assert manager.owner is None
    assert old.envelope.full_identity in manager.suppressed_identities
    assert new.envelope.full_identity in manager.suppressed_identities


def test_terminal_kind_vocabulary_is_closed() -> None:
    with pytest.raises(ValueError):
        ProducerTerminalKind("SOMETHING_NEW")


def test_wrong_lane_id_fingerprint_and_unrelated_terminals_cannot_settle_entered_owner() -> None:
    manager = OwnerManager()
    owner_candidate = _enter_reversal_long(manager, opportunity_id="PR-exact-binding")
    owner = owner_candidate.envelope
    terminals = (
        ProducerTerminal(
            lane_id=LaneId.TREND_CONTINUATION,
            opportunity_id=owner.opportunity_id,
            payload_fingerprint=owner.payload_fingerprint,
            kind=ProducerTerminalKind.INVALIDATED,
        ),
        ProducerTerminal(
            lane_id=owner.lane_id,
            opportunity_id="wrong-id",
            payload_fingerprint=owner.payload_fingerprint,
            kind=ProducerTerminalKind.INVALIDATED,
        ),
        ProducerTerminal(
            lane_id=owner.lane_id,
            opportunity_id=owner.opportunity_id,
            payload_fingerprint="wrong-fingerprint",
            kind=ProducerTerminalKind.TARGET_REACHED,
        ),
        ProducerTerminal(
            lane_id=LaneId.TREND_CONTINUATION,
            opportunity_id="unrelated",
            payload_fingerprint="unrelated-fingerprint",
            kind=ProducerTerminalKind.TARGET_REACHED,
        ),
    )
    result = manager.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0),
        producer_terminals=terminals,
    )
    assert result.event is OwnerEvent.NONE
    assert result.reason_code is OwnerReason.OWNER_RETAINED
    assert manager.owner == owner


def test_exact_invalidated_precedes_exact_target_when_both_arrive() -> None:
    manager = OwnerManager()
    owner_candidate = _enter_reversal_long(manager, opportunity_id="PR-both-pulses")
    owner = owner_candidate.envelope
    invalidated = ProducerTerminal(
        lane_id=owner.lane_id,
        opportunity_id=owner.opportunity_id,
        payload_fingerprint=owner.payload_fingerprint,
        kind=ProducerTerminalKind.INVALIDATED,
    )
    target = replace(invalidated, kind=ProducerTerminalKind.TARGET_REACHED)
    result = manager.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0),
        producer_terminals=(target, invalidated),
    )
    assert result.event is OwnerEvent.INVALIDATED
    assert result.reason_code is OwnerReason.OPPORTUNITY_INVALIDATED
    assert manager.owner is None


@pytest.mark.parametrize(
    "kind",
    (
        ProducerTerminalKind.ACTIVE_NONE,
        ProducerTerminalKind.PERMISSION_EXPIRED,
        ProducerTerminalKind.CONTEXT_EXPIRED,
        ProducerTerminalKind.SOURCE_INVALID,
        ProducerTerminalKind.IDENTITY_DRIFT,
        ProducerTerminalKind.SUPPRESSED,
        ProducerTerminalKind.CONTEXT_RESET,
        ProducerTerminalKind.DATA_RESET,
    ),
)
def test_closed_unentered_lane_endings_expire_before_timing(
    kind: ProducerTerminalKind,
) -> None:
    manager = OwnerManager()
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id=f"PR-unentered-{kind.value}",
        fingerprint=f"fp-unentered-{kind.value}",
        trigger=100.0,
    )
    manager.ingest(bar3(9, 42, close=99.5), candidates=(value,))
    terminal = ProducerTerminal(
        lane_id=value.envelope.lane_id,
        opportunity_id=value.envelope.opportunity_id,
        payload_fingerprint=value.envelope.payload_fingerprint,
        kind=kind,
    )
    result = manager.ingest(
        bar3(9, 45, close=100.5), producer_terminals=(terminal,)
    )
    assert result.event is OwnerEvent.EXPIRED
    assert result.reason_code is OwnerReason.SOURCE_INVALID
    assert manager.owner is None


def test_entered_owner_survives_same_base_collision_but_tombstone_persists() -> None:
    manager = OwnerManager()
    original = _enter_reversal_long(manager, opportunity_id="PR-enter-collision")
    owner = original.envelope
    changed = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id=owner.opportunity_id,
        fingerprint="changed-fingerprint",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    retained = manager.ingest(
        bar3(9, 48, open_=100.0, high=101.0, low=99.0, close=100.0),
        candidates=(changed,),
    )
    assert retained.event is OwnerEvent.NONE
    assert retained.reason_code is OwnerReason.OWNER_RETAINED
    assert manager.owner == owner
    assert owner.base_identity in manager.collision_tombstones
    assert owner.full_identity in manager.suppressed_identities
    assert changed.envelope.full_identity in manager.suppressed_identities

    third = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id=owner.opportunity_id,
        fingerprint="third-fingerprint",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    retained_again = manager.ingest(
        bar3(9, 51, open_=100.0, high=101.0, low=99.0, close=100.0),
        candidates=(third,),
    )
    assert retained_again.reason_code is OwnerReason.OWNER_RETAINED
    assert manager.owner == owner
    assert third.envelope.full_identity in manager.suppressed_identities


def test_unconfirmed_wrong_host_bar_mutates_no_clock_owner_or_suppression() -> None:
    manager = OwnerManager()
    value = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    unconfirmed = manager.ingest(
        bar3(9, 42, symbol="OTHER", is_confirmed=False),
        candidates=(value,),
    )
    assert unconfirmed.event is OwnerEvent.NONE
    assert unconfirmed.reason_code is OwnerReason.DATA_UNCONFIRMED
    assert manager.owner is None
    assert manager.suppressed_identities == frozenset()
    assert manager.collision_tombstones == frozenset()

    confirmed_same_timestamp = manager.ingest(bar3(9, 42), candidates=(value,))
    assert confirmed_same_timestamp.reason_code is OwnerReason.NEW_TREND_OWNER
    assert manager.owner == value.envelope


def test_raw_string_terminal_kind_is_rejected_before_owner_processing() -> None:
    with pytest.raises(ValueError, match="closed allowlist"):
        ProducerTerminal(
            lane_id=LaneId.TREND_CONTINUATION,
            opportunity_id="TC-raw-terminal",
            payload_fingerprint="fp-raw-terminal",
            kind="EXPIRED",  # type: ignore[arg-type]
        )


def test_two_same_base_fingerprints_on_one_bar_tombstone_without_adoption() -> None:
    manager = OwnerManager()
    first = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-same-bar-base",
        fingerprint="fp-one",
    )
    second = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-same-bar-base",
        fingerprint="fp-two",
    )
    result = manager.ingest(bar3(9, 42), candidates=(first, second))
    assert result.event is OwnerEvent.NONE
    assert manager.owner is None
    assert first.envelope.base_identity in manager.collision_tombstones
    assert first.envelope.full_identity in manager.suppressed_identities
    assert second.envelope.full_identity in manager.suppressed_identities
