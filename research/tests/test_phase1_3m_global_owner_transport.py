from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

import research.phase1_3m_global_owner_oracle as global_owner_oracle
from research.generate_phase1_3m_global_owner_pine_v1 import PINE_SOURCE
from research.phase1_3m_global_owner_oracle import (
    CompletedTenMinutePayload,
    ConsumerBarDecision,
    Direction,
    GlobalOwnerHost,
    LaneId,
    OwnerEvent,
    OwnerManager,
    OwnerReason,
    OwnerState,
    SharedCompletedTenMinuteTransport,
    TransportOutcome,
    TransportReason,
    TransportStatus,
)
from research.tests.fixture_phase1_3m_global_owner import bar3, candidate, et_ms


def transport_audit(
    transport: SharedCompletedTenMinuteTransport,
) -> tuple[object, int | None, int | None, frozenset[int], int | None]:
    return (
        transport.pending_payload,
        transport.last_observed_source_time,
        transport.last_consumed_source_time,
        transport.rejected_source_times,
        transport.reset_visible_at_cutoff_ms,
    )


class _TransportHarness:
    """Private test-only harness using the production integrated host API."""

    def __init__(self) -> None:
        self.host = GlobalOwnerHost()

    @property
    def transport(self) -> SharedCompletedTenMinuteTransport:
        return self.host.transport

    @staticmethod
    def _bar(timestamp_ms: int) -> object:
        return replace(bar3(0, 0), timestamp_ms=timestamp_ms)

    def poll(
        self,
        hour: int,
        minute: int,
        status: TransportStatus,
        reason: TransportReason,
        *,
        payload: CompletedTenMinutePayload | None = None,
    ) -> TransportOutcome:
        target = et_ms(hour, minute)
        prior = self.host.manager.last_timestamp_ms
        if prior is not None and target > prior + 180_000:
            for timestamp_ms in range(prior + 180_000, target, 180_000):
                filler = self.host.process_bar(self._bar(timestamp_ms))
                assert filler.consumer_bar.eligible
        step = self.host.process_bar(
            self._bar(target),
            completed_ten_minute_payload=payload,
        )
        assert step.transport_outcome is not None
        outcome = step.transport_outcome
        assert outcome.status is status
        assert outcome.reason is reason
        return outcome


def test_0940_payload_stays_pending_on_0939_and_consumes_at_0942() -> None:
    harness = _TransportHarness()
    payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        candidates=(candidate(LaneId.TREND_CONTINUATION, Direction.LONG),),
    )

    pending = harness.poll(
        9,
        39,
        TransportStatus.PENDING,
        TransportReason.WAIT_VISIBLE_AT,
        payload=payload,
    )
    assert pending.payload == payload
    assert harness.transport.last_consumed_source_time is None
    delivered = harness.poll(
        9,
        42,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
    )
    assert delivered.payload == payload
    assert harness.transport.last_consumed_source_time == et_ms(9, 30)


def test_1140_payload_stays_pending_on_1139_and_consumes_at_1142() -> None:
    harness = _TransportHarness()
    payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(11, 30),
        visible_at_ms=et_ms(11, 40),
    )

    pending = harness.poll(
        11,
        39,
        TransportStatus.PENDING,
        TransportReason.WAIT_VISIBLE_AT,
        payload=payload,
    )
    assert pending.payload == payload
    assert harness.transport.last_consumed_source_time is None
    delivered = harness.poll(
        11,
        42,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
    )
    assert delivered.payload == payload


def test_forming_payload_is_ignored_and_duplicate_completed_timestamp_delivers_once() -> None:
    harness = _TransportHarness()
    forming = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        is_previous_completed=False,
    )
    harness.poll(
        9,
        42,
        TransportStatus.PENDING,
        TransportReason.NO_PENDING_PAYLOAD,
        payload=forming,
    )

    completed = replace(forming, is_previous_completed=True)
    delivered = harness.poll(
        9,
        45,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=completed,
    )
    assert delivered.payload == completed
    harness.poll(
        9,
        48,
        TransportStatus.PENDING,
        TransportReason.NO_PENDING_PAYLOAD,
    )
    duplicate = harness.poll(
        9,
        51,
        TransportStatus.DUPLICATE,
        TransportReason.ALREADY_CONSUMED,
        payload=completed,
    )
    assert duplicate.payload == completed


def test_completed_payload_requires_exact_10m_span_and_matching_candidate_clock() -> None:
    with pytest.raises(ValueError, match="600000ms"):
        CompletedTenMinutePayload(
            source_time_ms=et_ms(9, 30),
            visible_at_ms=et_ms(9, 41),
        )

    value = candidate(LaneId.TREND_CONTINUATION, Direction.LONG)
    with pytest.raises(ValueError, match="confirmation"):
        CompletedTenMinutePayload(
            source_time_ms=et_ms(9, 20),
            visible_at_ms=et_ms(9, 30),
            candidates=(value,),
        )

    mismatched_visibility = replace(
        value,
        envelope=replace(value.envelope, visible_at_ms=et_ms(9, 50)),
    )
    with pytest.raises(ValueError, match="visibility"):
        CompletedTenMinutePayload(
            source_time_ms=et_ms(9, 30),
            visible_at_ms=et_ms(9, 40),
            candidates=(mismatched_visibility,),
        )


def test_raw_10m_gap_returns_typed_reset_and_recovers_only_above_cutoff() -> None:
    harness = _TransportHarness()
    first = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    delivered = harness.poll(
        9,
        42,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=first,
    )
    assert delivered.payload == first
    assert harness.transport.last_observed_source_time == et_ms(9, 30)
    assert harness.transport.last_consumed_source_time == et_ms(9, 30)

    gap = CompletedTenMinutePayload(et_ms(10, 0), et_ms(10, 10))
    reset = harness.poll(
        10,
        12,
        TransportStatus.RESET,
        TransportReason.RAW_10M_GAP,
        payload=gap,
    )
    assert reset.payload == gap
    assert reset.reset_cutoff_ms == et_ms(10, 12)
    assert harness.transport.last_observed_source_time == et_ms(10, 0)
    assert harness.transport.last_consumed_source_time == et_ms(9, 30)
    assert gap.source_time_ms in harness.transport.rejected_source_times

    recovered = CompletedTenMinutePayload(et_ms(10, 10), et_ms(10, 20))
    recovery = harness.poll(
        10,
        21,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=recovered,
    )
    assert recovery.payload == recovered
    assert harness.transport.last_consumed_source_time == et_ms(10, 10)


def test_raw_10m_backward_rejects_less_and_equal_cutoff_then_recovers_above() -> None:
    harness = _TransportHarness()
    original = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    first = harness.poll(
        9,
        51,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=original,
    )
    assert first.payload == original

    backward = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    reset = harness.poll(
        10,
        0,
        TransportStatus.RESET,
        TransportReason.RAW_10M_BACKWARD,
        payload=backward,
    )
    assert reset.reset_cutoff_ms == et_ms(10, 0)
    assert harness.transport.last_observed_source_time == et_ms(9, 30)
    assert harness.transport.last_consumed_source_time == et_ms(9, 40)

    less_than_cutoff = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    less = harness.poll(
        10,
        3,
        TransportStatus.REJECTED,
        TransportReason.RESET_CUTOFF,
        payload=less_than_cutoff,
    )
    assert less.payload == less_than_cutoff
    assert harness.transport.last_consumed_source_time == et_ms(9, 40)

    equal_cutoff = CompletedTenMinutePayload(et_ms(9, 50), et_ms(10, 0))
    equal = harness.poll(
        10,
        6,
        TransportStatus.REJECTED,
        TransportReason.RESET_CUTOFF,
        payload=equal_cutoff,
    )
    assert equal.payload == equal_cutoff
    assert equal_cutoff.source_time_ms in harness.transport.rejected_source_times
    assert harness.transport.last_consumed_source_time == et_ms(9, 40)

    recovered = CompletedTenMinutePayload(et_ms(10, 0), et_ms(10, 10))
    recovery = harness.poll(
        10,
        12,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=recovered,
    )
    assert recovery.payload == recovered
    assert harness.transport.last_consumed_source_time == et_ms(10, 0)


def test_overlap_reversal_stop_touch_suppresses_before_adoption() -> None:
    manager = OwnerManager()
    overlap = bar3(9, 39, 99.0, 101.0, 94.9, 100.0)
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        overlap=overlap,
        stop=95.0,
        target=110.0,
    )
    result = manager.ingest(bar3(9, 42), candidates=(value,))

    assert result.event is OwnerEvent.NONE
    assert result.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert manager.owner is None
    assert value.envelope.full_identity in manager.suppressed_identities


def test_overlap_trend_wick_below_stop_does_not_invalidate_but_close_does() -> None:
    wick_only = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        overlap=bar3(9, 39, 99.0, 101.0, 94.0, 96.0),
        stop=95.0,
    )
    manager = OwnerManager()
    adopted = manager.ingest(bar3(9, 42), candidates=(wick_only,))
    assert adopted.reason_code is OwnerReason.NEW_TREND_OWNER

    close_breach = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-L-2",
        fingerprint="fp-TC-L-2",
        overlap=bar3(9, 39, 99.0, 101.0, 94.0, 94.9),
        stop=95.0,
    )
    manager2 = OwnerManager()
    blocked = manager2.ingest(bar3(9, 42), candidates=(close_breach,))
    assert blocked.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert manager2.owner is None


def test_adoption_bar_target_hit_and_stop_plus_target_are_suppressed_stop_first() -> None:
    target_only = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        stop=95.0,
        target=101.0,
    )
    manager = OwnerManager()
    result = manager.ingest(
        bar3(9, 42, 100.0, 101.1, 99.0, 100.0),
        candidates=(target_only,),
    )
    assert result.reason_code is OwnerReason.PRE_ADOPTION_TARGET_REACHED
    assert manager.owner is None

    both = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-L-both",
        fingerprint="fp-both",
        stop=99.0,
        target=101.0,
    )
    manager2 = OwnerManager()
    result2 = manager2.ingest(
        bar3(9, 42, 100.0, 101.1, 98.9, 100.0),
        candidates=(both,),
    )
    assert result2.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert manager2.owner is None


def test_overlap_target_and_adoption_stop_are_globally_stop_first() -> None:
    value = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-cross-bar-stop-first",
        fingerprint="fp-cross-bar-stop-first",
        overlap=bar3(9, 39, 100.0, 111.0, 99.0, 100.0),
        stop=95.0,
        target=110.0,
    )
    manager = OwnerManager()
    result = manager.ingest(
        bar3(9, 42, 100.0, 101.0, 94.9, 100.0),
        candidates=(value,),
    )

    assert result.event is OwnerEvent.NONE
    assert result.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert manager.owner is None
    assert value.envelope.full_identity in manager.suppressed_identities


def test_wrong_host_duplicate_backward_and_gap_follow_global_priority() -> None:
    manager = OwnerManager()
    first = manager.ingest(bar3(9, 42))
    assert first.reason_code is OwnerReason.WAIT_10M

    duplicate_wrong_host = manager.ingest(
        bar3(9, 42, symbol="OTHER"),
    )
    assert duplicate_wrong_host.reason_code is OwnerReason.DATA_SYMBOL_MISMATCH
    assert duplicate_wrong_host.event is OwnerEvent.DATA_RESET

    manager2 = OwnerManager()
    manager2.ingest(bar3(9, 42))
    backward = manager2.ingest(bar3(9, 39))
    assert backward.reason_code is OwnerReason.DATA_NON_MONOTONIC
    assert backward.event is OwnerEvent.DATA_RESET

    manager3 = OwnerManager()
    manager3.ingest(bar3(9, 42))
    gap = manager3.ingest(bar3(9, 48))
    assert gap.reason_code is OwnerReason.DATA_GAP_RESET
    assert gap.event is OwnerEvent.DATA_RESET
    next_bar = manager3.ingest(bar3(9, 51))
    assert next_bar.reason_code is OwnerReason.WAIT_10M


def test_short_overlap_and_adoption_terminal_checks_mirror_stop_first() -> None:
    reversal_both = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        opportunity_id="PR-S-pre-both",
        fingerprint="fp-PR-S-pre-both",
        stop=105.0,
        target=99.0,
    )
    reversal_manager = OwnerManager()
    reversal_result = reversal_manager.ingest(
        bar3(9, 42, open_=100.0, high=105.1, low=98.9, close=100.0),
        candidates=(reversal_both,),
    )
    assert reversal_result.event is OwnerEvent.NONE
    assert reversal_result.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert reversal_manager.owner is None

    trend_wick = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.SHORT,
        opportunity_id="TC-S-pre-wick",
        fingerprint="fp-TC-S-pre-wick",
        overlap=bar3(9, 39, open_=100.0, high=106.0, low=99.0, close=104.0),
        stop=105.0,
        target=90.0,
    )
    trend_manager = OwnerManager()
    adopted = trend_manager.ingest(
        bar3(9, 42, open_=100.0, high=104.0, low=99.0, close=100.0),
        candidates=(trend_wick,),
    )
    assert adopted.reason_code is OwnerReason.NEW_TREND_OWNER

    trend_close = replace(
        trend_wick,
        envelope=replace(
            trend_wick.envelope,
            opportunity_id="TC-S-pre-close",
            episode_id="episode-TC-S-pre-close",
            payload_fingerprint="fp-TC-S-pre-close",
        ),
        overlap_bar=bar3(9, 39, open_=100.0, high=106.0, low=99.0, close=105.1),
    )
    trend_manager2 = OwnerManager()
    blocked = trend_manager2.ingest(
        bar3(9, 42, open_=100.0, high=104.0, low=99.0, close=100.0),
        candidates=(trend_close,),
    )
    assert blocked.reason_code is OwnerReason.PRE_ADOPTION_INVALIDATED
    assert trend_manager2.owner is None


def test_reset_cutoff_permanently_rejects_pending_old_htf_payload_after_3m_gap() -> None:
    """09:39 -> missing 09:42 -> 09:45 reset -> stale 09:40 payload stays dead."""

    host = GlobalOwnerHost()
    stale_candidate = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        opportunity_id="TC-stale-across-reset",
        fingerprint="fp-TC-stale-across-reset",
    )
    stale_payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        candidates=(stale_candidate,),
    )

    pending = host.process_bar(
        bar3(9, 39), completed_ten_minute_payload=stale_payload
    )
    assert pending.transport_outcome is not None
    assert pending.transport_outcome.status is TransportStatus.PENDING
    assert host.manager.owner is None

    reset = host.process_bar(bar3(9, 45))
    assert reset.transport_outcome is None
    assert reset.observation.event is OwnerEvent.DATA_RESET
    assert reset.observation.reason_code is OwnerReason.DATA_GAP_RESET
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(9, 45)
    assert host.transport.pending_payload == stale_payload

    rejected = host.process_bar(bar3(9, 48))
    assert rejected.transport_outcome is not None
    assert rejected.transport_outcome.status is TransportStatus.REJECTED
    assert rejected.transport_outcome.reason is TransportReason.RESET_CUTOFF
    assert rejected.transport_outcome.payload == stale_payload
    assert host.transport.last_observed_source_time == et_ms(9, 30)
    assert host.transport.last_consumed_source_time is None
    assert et_ms(9, 30) in host.transport.rejected_source_times
    assert host.manager.owner is None

    reappeared = host.process_bar(
        bar3(9, 51), completed_ten_minute_payload=stale_payload
    )
    assert reappeared.transport_outcome is not None
    assert reappeared.transport_outcome.status is TransportStatus.REJECTED
    assert (
        reappeared.transport_outcome.reason
        is TransportReason.EXPLICIT_REJECTED_LEDGER
    )
    assert host.transport.last_consumed_source_time is None

    direct = host.manager.ingest(bar3(9, 54), candidates=(stale_candidate,))
    assert direct.event is OwnerEvent.NONE
    assert direct.reason_code is OwnerReason.CANDIDATE_SUPPRESSED
    assert host.manager.owner is None
    assert stale_candidate.envelope.full_identity in host.manager.suppressed_identities


def test_last_observed_is_continuity_audit_not_consumption_gate() -> None:
    harness = _TransportHarness()
    first = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    gap = CompletedTenMinutePayload(et_ms(10, 0), et_ms(10, 10))
    recovery = CompletedTenMinutePayload(et_ms(10, 10), et_ms(10, 20))

    first_outcome = harness.poll(
        9,
        42,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=first,
    )
    assert first_outcome.payload == first
    reset = harness.poll(
        10,
        12,
        TransportStatus.RESET,
        TransportReason.RAW_10M_GAP,
        payload=gap,
    )
    assert reset.payload == gap

    assert harness.transport.last_observed_source_time == gap.source_time_ms
    assert harness.transport.last_consumed_source_time == first.source_time_ms
    assert gap.source_time_ms in harness.transport.rejected_source_times

    harness.poll(
        10,
        15,
        TransportStatus.REJECTED,
        TransportReason.EXPLICIT_REJECTED_LEDGER,
        payload=gap,
    )
    assert harness.transport.last_observed_source_time == gap.source_time_ms
    assert harness.transport.last_consumed_source_time == first.source_time_ms

    recovered = harness.poll(
        10,
        21,
        TransportStatus.DELIVERED,
        TransportReason.DELIVERED,
        payload=recovery,
    )
    assert recovered.payload == recovery
    assert harness.transport.last_observed_source_time == recovery.source_time_ms
    assert harness.transport.last_consumed_source_time == recovery.source_time_ms


def test_reset_visible_cutoff_is_monotonic_for_backward_and_host_resets() -> None:
    host = GlobalOwnerHost()
    host.process_bar(bar3(9, 45))

    backward = host.process_bar(bar3(9, 42))
    assert backward.observation.event is OwnerEvent.DATA_RESET
    assert backward.observation.reason_code is OwnerReason.DATA_NON_MONOTONIC
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(9, 45)
    assert host.transport.reset_visible_at_cutoff_ms is None

    wrong_host = host.process_bar(bar3(9, 48, symbol="OTHER"))
    assert wrong_host.observation.event is OwnerEvent.DATA_RESET
    assert wrong_host.observation.reason_code is OwnerReason.DATA_SYMBOL_MISMATCH
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(9, 48)
    assert host.transport.reset_visible_at_cutoff_ms is None

    synced = host.process_bar(bar3(9, 51))
    assert synced.transport_outcome is not None
    assert synced.transport_outcome.status is TransportStatus.PENDING
    assert host.transport.reset_visible_at_cutoff_ms == et_ms(9, 48)


def test_entered_owner_raw_gap_reset_preempts_price_terminal_and_clears_next_bar() -> None:
    host = GlobalOwnerHost()
    reversal = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-entered-raw-gap",
        fingerprint="fp-PR-entered-raw-gap",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    first_payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        candidates=(reversal,),
    )
    adopted = host.process_bar(
        bar3(9, 42, 100.0, 101.0, 99.0, 100.2),
        completed_ten_minute_payload=first_payload,
    )
    assert adopted.transport_outcome is not None
    assert adopted.transport_outcome.status is TransportStatus.DELIVERED
    assert adopted.observation.state is OwnerState.WAIT_IMMEDIATE_CONFIRM

    entered = host.process_bar(bar3(9, 45, 100.2, 101.0, 99.5, 100.6))
    assert entered.observation.event is OwnerEvent.LONG_ENTRY
    assert entered.observation.state is OwnerState.ENTERED

    for hour, minute in (
        (9, 48),
        (9, 51),
        (9, 54),
        (9, 57),
        (10, 0),
        (10, 3),
        (10, 6),
        (10, 9),
    ):
        retained = host.process_bar(bar3(hour, minute))
        assert retained.observation.state is OwnerState.ENTERED
        assert retained.observation.reason_code is OwnerReason.OWNER_RETAINED

    raw_gap = CompletedTenMinutePayload(et_ms(10, 0), et_ms(10, 10))
    reset = host.process_bar(
        bar3(10, 12, 100.0, 111.0, 94.0, 100.0),
        completed_ten_minute_payload=raw_gap,
    )
    assert reset.transport_outcome is not None
    assert reset.transport_outcome.status is TransportStatus.RESET
    assert reset.transport_outcome.reason is TransportReason.RAW_10M_GAP
    observation = reset.observation
    assert observation.event is OwnerEvent.DATA_RESET
    assert observation.reason_code is OwnerReason.DATA_GAP_RESET
    assert observation.state is OwnerState.WAIT_10M
    assert host.manager.state is OwnerState.WAIT_10M
    assert host.manager.owner is None
    assert observation.lane_id is LaneId.POSITION_REVERSAL
    assert observation.invalidation == 95.0
    assert observation.target == 110.0
    assert observation.entry_price == entered.observation.entry_price
    assert observation.remaining_r == entered.observation.remaining_r
    assert reversal.envelope.full_identity in host.manager.suppressed_identities
    assert host.transport.reset_visible_at_cutoff_ms == et_ms(10, 12)
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(10, 12)

    cleared = host.process_bar(bar3(10, 15)).observation
    assert cleared.event is OwnerEvent.NONE
    assert cleared.state is OwnerState.WAIT_10M
    assert cleared.lane_id is None
    assert cleared.invalidation is None
    assert cleared.target is None
    assert cleared.remaining_r is None


def test_unentered_raw_backward_reset_rejects_cutoff_and_recovers_strictly_after() -> None:
    host = GlobalOwnerHost()
    waiting = candidate(
        LaneId.TREND_CONTINUATION,
        Direction.LONG,
        adoption_time=(9, 51),
        overlap=bar3(9, 48, 100.0, 100.5, 99.5, 100.0),
        opportunity_id="TC-unentered-raw-backward",
        fingerprint="fp-TC-unentered-raw-backward",
        confirmation_time_ms=et_ms(9, 40),
        visible_at_ms=et_ms(9, 50),
        permission_expires_at_ms=et_ms(11, 50),
    )
    first_payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 40),
        visible_at_ms=et_ms(9, 50),
        candidates=(waiting,),
    )
    adopted = host.process_bar(
        bar3(9, 51, 101.0, 102.0, 100.8, 101.0),
        completed_ten_minute_payload=first_payload,
    )
    assert adopted.transport_outcome is not None
    assert adopted.transport_outcome.status is TransportStatus.DELIVERED
    assert adopted.observation.state is OwnerState.WAIT_PULLBACK
    host.process_bar(bar3(9, 54, 101.0, 102.0, 100.8, 101.0))
    host.process_bar(bar3(9, 57, 101.0, 102.0, 100.8, 101.0))

    backward_payload = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    reset = host.process_bar(
        bar3(10, 0), completed_ten_minute_payload=backward_payload
    )
    assert reset.transport_outcome is not None
    assert reset.transport_outcome.status is TransportStatus.RESET
    assert reset.transport_outcome.reason is TransportReason.RAW_10M_BACKWARD
    assert reset.observation.event is OwnerEvent.DATA_RESET
    assert reset.observation.reason_code is OwnerReason.DATA_NON_MONOTONIC
    assert reset.observation.state is OwnerState.WAIT_10M
    assert host.manager.owner is None
    assert waiting.envelope.full_identity in host.manager.suppressed_identities

    less_than_cutoff = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    less = host.process_bar(
        bar3(10, 3), completed_ten_minute_payload=less_than_cutoff
    )
    assert less.transport_outcome is not None
    assert less.transport_outcome.status is TransportStatus.REJECTED
    assert less.transport_outcome.reason is TransportReason.RESET_CUTOFF
    assert less.observation.lane_id is None

    equal_cutoff = CompletedTenMinutePayload(et_ms(9, 50), et_ms(10, 0))
    equal = host.process_bar(
        bar3(10, 6), completed_ten_minute_payload=equal_cutoff
    )
    assert equal.transport_outcome is not None
    assert equal.transport_outcome.status is TransportStatus.REJECTED
    assert equal.transport_outcome.reason is TransportReason.RESET_CUTOFF
    assert equal.observation.lane_id is None
    assert less_than_cutoff.source_time_ms in host.transport.rejected_source_times
    assert equal_cutoff.source_time_ms in host.transport.rejected_source_times
    assert host.transport.last_consumed_source_time == et_ms(9, 40)

    host.process_bar(bar3(10, 9))
    recovery_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        adoption_time=(10, 12),
        overlap=bar3(10, 9, 100.0, 101.0, 99.0, 100.0),
        opportunity_id="PR-after-raw-reset",
        fingerprint="fp-PR-after-raw-reset",
        trigger=100.0,
        stop=105.0,
        target=90.0,
        confirmation_time_ms=et_ms(10, 0),
        visible_at_ms=et_ms(10, 10),
        permission_expires_at_ms=et_ms(12, 10),
    )
    recovery_payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(10, 0),
        visible_at_ms=et_ms(10, 10),
        candidates=(recovery_candidate,),
    )
    recovered = host.process_bar(
        bar3(10, 12), completed_ten_minute_payload=recovery_payload
    )
    assert recovered.transport_outcome is not None
    assert recovered.transport_outcome.status is TransportStatus.DELIVERED
    assert recovered.observation.reason_code is OwnerReason.NEW_REVERSAL_OWNER
    assert host.manager.owner == recovery_candidate.envelope
    assert host.transport.last_observed_source_time == et_ms(10, 0)
    assert host.transport.last_consumed_source_time == et_ms(10, 0)


def test_raw_10m_ohlc_invalid_is_typed_global_reset() -> None:
    host = GlobalOwnerHost()
    initial = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    delivered = host.process_bar(
        bar3(9, 42), completed_ten_minute_payload=initial
    )
    assert delivered.transport_outcome is not None
    assert delivered.transport_outcome.status is TransportStatus.DELIVERED
    host.process_bar(bar3(9, 45))
    host.process_bar(bar3(9, 48))

    invalid = CompletedTenMinutePayload(
        et_ms(9, 40),
        et_ms(9, 50),
        raw_ohlc_valid=False,
    )
    reset = host.process_bar(
        bar3(9, 51), completed_ten_minute_payload=invalid
    )
    assert reset.transport_outcome is not None
    assert reset.transport_outcome.status is TransportStatus.RESET
    assert reset.transport_outcome.reason is TransportReason.RAW_10M_OHLC_INVALID
    assert reset.observation.event is OwnerEvent.DATA_RESET
    assert reset.observation.reason_code is OwnerReason.DATA_INVALID
    assert reset.observation.state is OwnerState.WAIT_10M
    assert host.transport.reset_visible_at_cutoff_ms == et_ms(9, 51)
    assert invalid.source_time_ms in host.transport.rejected_source_times


def test_python_raw_reset_priority_and_cutoff_match_generated_pine() -> None:
    assert "or goRawReset" in PINE_SOURCE
    assert "e_timeClose <= goResetVisibleCutoffMs" in PINE_SOURCE
    assert "array.push(goRejected10mSourceTimes, e_time)" in PINE_SOURCE
    assert "goEventPulse := GO_EVENT_DATA_RESET" in PINE_SOURCE
    assert "goState := GO_WAIT_10M" in PINE_SOURCE
    assert "goLast3mTime := goGap3m ? time : na" in PINE_SOURCE
    pine_reset = PINE_SOURCE.index("if globalReset")
    pine_price_terminal = PINE_SOURCE.index(
        "// Existing owner price terminal always wins; stop precedes target."
    )
    assert pine_reset < pine_price_terminal

    oracle_source = inspect.getsource(OwnerManager.ingest)
    oracle_reset = oracle_source.index(
        "transport_outcome.status is TransportStatus.RESET"
    )
    oracle_price_terminal = oracle_source.index("self._owner_local_stop(bar)")
    assert oracle_reset < oracle_price_terminal
    assert "keep_timestamp=False" in oracle_source


def _integrated_host_seeded_through_0954() -> GlobalOwnerHost:
    host = GlobalOwnerHost()
    seed = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    first = host.process_bar(
        bar3(9, 42), completed_ten_minute_payload=seed
    )
    assert first.consumer_bar.eligible
    assert first.transport_outcome is not None
    assert first.transport_outcome.status is TransportStatus.DELIVERED
    for hour, minute in ((9, 45), (9, 48), (9, 51), (9, 54)):
        step = host.process_bar(bar3(hour, minute))
        assert step.consumer_bar.eligible
        assert step.transport_outcome is not None
        assert step.transport_outcome.status is TransportStatus.PENDING
    assert host.manager.last_timestamp_ms == et_ms(9, 54)
    assert host.transport.last_observed_source_time == et_ms(9, 30)
    assert host.transport.last_consumed_source_time == et_ms(9, 30)
    return host


def test_integrated_3m_gap_clears_entered_owner_without_polling_same_bar_raw_gap() -> None:
    host = GlobalOwnerHost()
    entered_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        opportunity_id="PR-entered-before-combined-gap",
        fingerprint="fp-PR-entered-before-combined-gap",
        trigger=100.0,
        stop=95.0,
        target=110.0,
    )
    payload = CompletedTenMinutePayload(
        et_ms(9, 30), et_ms(9, 40), candidates=(entered_candidate,)
    )
    adopted = host.process_bar(
        bar3(9, 42, 100.0, 101.0, 99.0, 100.2),
        completed_ten_minute_payload=payload,
    )
    assert adopted.observation.state is OwnerState.WAIT_IMMEDIATE_CONFIRM
    entered = host.process_bar(
        bar3(9, 45, 100.2, 101.0, 99.5, 100.6)
    )
    assert entered.observation.event is OwnerEvent.LONG_ENTRY
    assert entered.observation.state is OwnerState.ENTERED
    for hour, minute in ((9, 48), (9, 51), (9, 54)):
        retained = host.process_bar(bar3(hour, minute))
        assert retained.observation.state is OwnerState.ENTERED

    audit_before = (
        host.transport.pending_payload,
        host.transport.last_observed_source_time,
        host.transport.last_consumed_source_time,
        host.transport.rejected_source_times,
        host.transport.reset_visible_at_cutoff_ms,
    )
    combined_gap = host.process_bar(
        bar3(10, 0),
        completed_ten_minute_payload=CompletedTenMinutePayload(
            et_ms(9, 50), et_ms(10, 0)
        ),
    )
    assert not combined_gap.consumer_bar.eligible
    assert combined_gap.consumer_bar.reason is OwnerReason.DATA_GAP_RESET
    assert combined_gap.transport_outcome is None
    assert combined_gap.observation.event is OwnerEvent.DATA_RESET
    assert combined_gap.observation.state is OwnerState.WAIT_10M
    assert combined_gap.observation.lane_id is LaneId.POSITION_REVERSAL
    assert host.manager.owner is None
    assert host.manager.last_timestamp_ms == et_ms(10, 0)
    assert entered_candidate.envelope.full_identity in host.manager.suppressed_identities
    assert (
        host.transport.pending_payload,
        host.transport.last_observed_source_time,
        host.transport.last_consumed_source_time,
        host.transport.rejected_source_times,
        host.transport.reset_visible_at_cutoff_ms,
    ) == audit_before


def test_integrated_gap_then_repeated_gap_cannot_poll_or_create_false_owner() -> None:
    """09:54 -> 10:00 gap -> 10:12 gap: no HTF audit/adoption until 10:15."""

    host = _integrated_host_seeded_through_0954()
    raw_gap_snapshot = CompletedTenMinutePayload(
        source_time_ms=et_ms(9, 50),
        visible_at_ms=et_ms(10, 0),
    )
    transport_before = (
        host.transport.pending_payload,
        host.transport.last_observed_source_time,
        host.transport.last_consumed_source_time,
        host.transport.rejected_source_times,
        host.transport.reset_visible_at_cutoff_ms,
    )

    first_gap = host.process_bar(
        bar3(10, 0),
        completed_ten_minute_payload=raw_gap_snapshot,
    )
    assert not first_gap.consumer_bar.eligible
    assert first_gap.consumer_bar.reason is OwnerReason.DATA_GAP_RESET
    assert first_gap.transport_outcome is None
    assert first_gap.observation.event is OwnerEvent.DATA_RESET
    assert first_gap.observation.state is OwnerState.WAIT_10M
    assert host.manager.last_timestamp_ms == et_ms(10, 0)
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(10, 0)
    assert host.manager.owner is None
    assert (
        host.transport.pending_payload,
        host.transport.last_observed_source_time,
        host.transport.last_consumed_source_time,
        host.transport.rejected_source_times,
        host.transport.reset_visible_at_cutoff_ms,
    ) == transport_before

    stale_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        adoption_time=(10, 12),
        overlap=bar3(10, 9),
        opportunity_id="PR-gap-host-stale-recovery",
        fingerprint="fp-PR-gap-host-stale-recovery",
        confirmation_time_ms=et_ms(10, 0),
        visible_at_ms=et_ms(10, 10),
        permission_expires_at_ms=et_ms(12, 10),
    )
    recovery_snapshot = CompletedTenMinutePayload(
        source_time_ms=et_ms(10, 0),
        visible_at_ms=et_ms(10, 10),
        candidates=(stale_candidate,),
    )
    second_gap = host.process_bar(
        bar3(10, 12),
        completed_ten_minute_payload=recovery_snapshot,
    )
    assert not second_gap.consumer_bar.eligible
    assert second_gap.consumer_bar.reason is OwnerReason.DATA_GAP_RESET
    assert second_gap.transport_outcome is None
    assert second_gap.observation.event is OwnerEvent.DATA_RESET
    assert second_gap.observation.state is OwnerState.WAIT_10M
    assert host.manager.last_timestamp_ms == et_ms(10, 12)
    assert host.manager.reset_visible_at_cutoff_ms == et_ms(10, 12)
    assert host.manager.owner is None
    assert (
        host.transport.pending_payload,
        host.transport.last_observed_source_time,
        host.transport.last_consumed_source_time,
        host.transport.rejected_source_times,
        host.transport.reset_visible_at_cutoff_ms,
    ) == transport_before

    # 10:15 is the first continuous eligible 3m bar.  Only now is the latest
    # gaps_off snapshot offered and audited.  Relative to the last audited 09:30
    # source, source 10:00 is a raw 10m gap, so it resets and cannot adopt.
    first_eligible = host.process_bar(bar3(10, 15))
    assert first_eligible.consumer_bar.eligible
    assert first_eligible.transport_outcome is not None
    assert first_eligible.transport_outcome.status is TransportStatus.RESET
    assert first_eligible.transport_outcome.reason is TransportReason.RAW_10M_GAP
    assert first_eligible.observation.event is OwnerEvent.DATA_RESET
    assert first_eligible.observation.state is OwnerState.WAIT_10M
    assert host.manager.last_timestamp_ms is None
    assert host.manager.owner is None
    assert host.transport.pending_payload is None
    assert host.transport.last_observed_source_time == et_ms(10, 0)
    assert host.transport.last_consumed_source_time == et_ms(9, 30)
    assert raw_gap_snapshot.source_time_ms not in host.transport.rejected_source_times
    assert recovery_snapshot.source_time_ms in host.transport.rejected_source_times
    assert host.transport.reset_visible_at_cutoff_ms == et_ms(10, 15)
    assert stale_candidate.envelope.full_identity in host.manager.suppressed_identities


def test_integrated_strictly_continuous_payload_above_cutoff_recovers() -> None:
    host = _integrated_host_seeded_through_0954()
    host.process_bar(
        bar3(10, 0),
        completed_ten_minute_payload=CompletedTenMinutePayload(
            et_ms(9, 50), et_ms(10, 0)
        ),
    )
    stale_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.LONG,
        adoption_time=(10, 12),
        overlap=bar3(10, 9),
        opportunity_id="PR-cutoff-equality-blocked",
        fingerprint="fp-PR-cutoff-equality-blocked",
        confirmation_time_ms=et_ms(10, 0),
        visible_at_ms=et_ms(10, 10),
        permission_expires_at_ms=et_ms(12, 10),
    )
    host.process_bar(
        bar3(10, 12),
        completed_ten_minute_payload=CompletedTenMinutePayload(
            et_ms(10, 0), et_ms(10, 10), candidates=(stale_candidate,)
        ),
    )
    raw_reset = host.process_bar(bar3(10, 15))
    assert raw_reset.transport_outcome is not None
    assert raw_reset.transport_outcome.status is TransportStatus.RESET
    assert host.transport.reset_visible_at_cutoff_ms == et_ms(10, 15)
    assert host.manager.owner is None

    # Pure raw reset clears the 3m clock; the next confirmed bar rebaselines it.
    rebaseline = host.process_bar(bar3(10, 18))
    assert rebaseline.consumer_bar.eligible
    assert rebaseline.transport_outcome is not None
    assert rebaseline.transport_outcome.status is TransportStatus.PENDING
    assert host.manager.last_timestamp_ms == et_ms(10, 18)

    fresh_candidate = candidate(
        LaneId.POSITION_REVERSAL,
        Direction.SHORT,
        adoption_time=(10, 21),
        overlap=bar3(10, 18),
        opportunity_id="PR-after-integrated-host-reset",
        fingerprint="fp-PR-after-integrated-host-reset",
        trigger=100.0,
        stop=105.0,
        target=90.0,
        confirmation_time_ms=et_ms(10, 10),
        visible_at_ms=et_ms(10, 20),
        permission_expires_at_ms=et_ms(12, 20),
    )
    fresh_payload = CompletedTenMinutePayload(
        source_time_ms=et_ms(10, 10),
        visible_at_ms=et_ms(10, 20),
        candidates=(fresh_candidate,),
    )
    recovered = host.process_bar(
        bar3(10, 21, ema5=99.5, ema12=100.5),
        completed_ten_minute_payload=fresh_payload,
    )
    assert recovered.transport_outcome is not None
    assert recovered.transport_outcome.status is TransportStatus.DELIVERED
    assert recovered.observation.event is OwnerEvent.NONE
    assert recovered.observation.reason_code is OwnerReason.NEW_REVERSAL_OWNER
    assert recovered.observation.state is OwnerState.WAIT_FRESH_CROSS
    assert host.manager.owner == fresh_candidate.envelope
    assert fresh_payload.visible_at_ms > et_ms(10, 15)
    assert host.transport.last_observed_source_time == et_ms(10, 10)
    assert host.transport.last_consumed_source_time == et_ms(10, 10)


@pytest.mark.parametrize(
    ("bad_bar", "expected_reason", "expected_event", "expected_clock"),
    (
        (
            bar3(9, 45),
            OwnerReason.DATA_DUPLICATE_IGNORED,
            OwnerEvent.NONE,
            et_ms(9, 45),
        ),
        (
            bar3(9, 42),
            OwnerReason.DATA_NON_MONOTONIC,
            OwnerEvent.DATA_RESET,
            None,
        ),
        (
            bar3(9, 48, symbol="OTHER"),
            OwnerReason.DATA_SYMBOL_MISMATCH,
            OwnerEvent.DATA_RESET,
            None,
        ),
        (
            bar3(9, 48, timeframe_ms=600_000),
            OwnerReason.DATA_TIMEFRAME_MISMATCH,
            OwnerEvent.DATA_RESET,
            None,
        ),
        (
            bar3(9, 48, is_standard=False),
            OwnerReason.DATA_NON_STANDARD,
            OwnerEvent.DATA_RESET,
            None,
        ),
        (
            bar3(9, 48, 100.0, 99.0, 101.0, 100.0),
            OwnerReason.DATA_INVALID,
            OwnerEvent.DATA_RESET,
            None,
        ),
        (
            bar3(9, 48, is_confirmed=False),
            OwnerReason.DATA_UNCONFIRMED,
            OwnerEvent.NONE,
            et_ms(9, 45),
        ),
    ),
    ids=(
        "duplicate",
        "backward",
        "wrong-symbol",
        "wrong-timeframe",
        "non-standard",
        "invalid-ohlc",
        "unconfirmed",
    ),
)
def test_integrated_ineligible_host_bar_leaves_transport_audit_untouched(
    bad_bar: object,
    expected_reason: OwnerReason,
    expected_event: OwnerEvent,
    expected_clock: int | None,
) -> None:
    host = GlobalOwnerHost()
    host.process_bar(
        bar3(9, 42),
        completed_ten_minute_payload=CompletedTenMinutePayload(
            et_ms(9, 30), et_ms(9, 40)
        ),
    )
    existing_pending = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    pending_step = host.process_bar(
        bar3(9, 45), completed_ten_minute_payload=existing_pending
    )
    assert pending_step.transport_outcome is not None
    assert pending_step.transport_outcome.status is TransportStatus.PENDING
    assert host.transport.pending_payload == existing_pending

    latest_snapshot = CompletedTenMinutePayload(et_ms(9, 50), et_ms(10, 0))
    audit_before = transport_audit(host.transport)
    step = host.process_bar(
        bad_bar,  # type: ignore[arg-type]
        completed_ten_minute_payload=latest_snapshot,
    )

    assert not step.consumer_bar.eligible
    assert step.consumer_bar.reason is expected_reason
    assert step.transport_outcome is None
    assert step.observation.reason_code is expected_reason
    assert step.observation.event is expected_event
    assert host.manager.last_timestamp_ms == expected_clock
    assert transport_audit(host.transport) == audit_before
    assert host.staged_raw_snapshot == latest_snapshot
    assert host.raw_snapshot_dirty


def test_public_forged_consumer_decision_cannot_mutate_transport() -> None:
    host = _integrated_host_seeded_through_0954()
    gap_bar = bar3(10, 0)
    real_decision = host.manager.consumer_bar_decision(gap_bar)
    assert not real_decision.eligible
    assert real_decision.reason is OwnerReason.DATA_GAP_RESET

    raw_gap = CompletedTenMinutePayload(et_ms(9, 50), et_ms(10, 0))
    before = transport_audit(host.transport)
    with pytest.raises(RuntimeError, match="public transport mutation is disabled"):
        host.transport.offer(raw_gap)
    assert transport_audit(host.transport) == before

    forged = ConsumerBarDecision(gap_bar.timestamp_ms, True, None)
    with pytest.raises(RuntimeError, match="public transport mutation is disabled"):
        host.transport.consume_for(forged)
    assert transport_audit(host.transport) == before

    step = host.process_bar(
        gap_bar, completed_ten_minute_payload=raw_gap
    )
    assert not step.consumer_bar.eligible
    assert step.transport_outcome is None
    assert step.observation.event is OwnerEvent.DATA_RESET
    assert step.observation.state is OwnerState.WAIT_10M
    assert transport_audit(host.transport) == before


def test_host_bound_permit_rejects_other_host_wrong_time_and_reuse_pre_mutation() -> None:
    host_a = GlobalOwnerHost()
    host_b = GlobalOwnerHost()
    bar = bar3(9, 42)
    decision_a = host_a.manager.consumer_bar_decision(bar)
    decision_b = host_b.manager.consumer_bar_decision(bar)
    permit_a = host_a._authority.issue(host=host_a, bar=bar, decision=decision_a)
    permit_b = host_b._authority.issue(host=host_b, bar=bar, decision=decision_b)
    payload = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))

    before_a = transport_audit(host_a.transport)
    with pytest.raises(ValueError, match="another .*host"):
        host_a.transport._poll_from_host(
            permit=permit_b,
            confirmed_bar_open_ms=bar.timestamp_ms,
            offered_payload=payload,
            reset_boundary_ms=None,
        )
    assert transport_audit(host_a.transport) == before_a

    with pytest.raises(ValueError, match="timestamp mismatch"):
        host_a.transport._poll_from_host(
            permit=permit_a,
            confirmed_bar_open_ms=et_ms(9, 45),
            offered_payload=payload,
            reset_boundary_ms=None,
        )
    assert transport_audit(host_a.transport) == before_a

    outcome = host_a.transport._poll_from_host(
        permit=permit_a,
        confirmed_bar_open_ms=bar.timestamp_ms,
        offered_payload=payload,
        reset_boundary_ms=None,
    )
    assert outcome.status is TransportStatus.DELIVERED
    after_valid_poll = transport_audit(host_a.transport)
    with pytest.raises(ValueError, match="already polled"):
        host_a.transport._poll_from_host(
            permit=permit_a,
            confirmed_bar_open_ms=bar.timestamp_ms,
            offered_payload=None,
            reset_boundary_ms=None,
        )
    assert transport_audit(host_a.transport) == after_valid_poll

    manager_b_before = (
        host_b.manager.last_timestamp_ms,
        host_b.manager.state,
        host_b.manager.owner,
    )
    with pytest.raises(ValueError, match="another .*host"):
        host_b.manager.ingest(
            bar, transport_outcome=outcome, _host_permit=permit_a
        )
    assert (
        host_b.manager.last_timestamp_ms,
        host_b.manager.state,
        host_b.manager.owner,
    ) == manager_b_before

    accepted = host_a.manager.ingest(
        bar, transport_outcome=outcome, _host_permit=permit_a
    )
    assert accepted.state is OwnerState.WAIT_10M
    with pytest.raises(ValueError):
        GlobalOwnerHost(transport=host_a.transport)


def test_ineligible_host_cannot_mint_private_transport_permit() -> None:
    host = _integrated_host_seeded_through_0954()
    gap_bar = bar3(10, 0)
    forged = ConsumerBarDecision(gap_bar.timestamp_ms, True, None)
    before = transport_audit(host.transport)
    with pytest.raises(ValueError, match="eligible 3m bar"):
        host._authority.issue(host=host, bar=gap_bar, decision=forged)
    assert transport_audit(host.transport) == before


def test_exact_public_manager_rebind_reproduction_fails_before_transport_transaction() -> None:
    host = _integrated_host_seeded_through_0954()
    replacement = OwnerManager()
    bar = bar3(9, 57)
    payload = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))

    original_clock = host.manager.last_timestamp_ms
    replacement_clock = replacement.last_timestamp_ms
    assert host.manager.consumer_bar_decision(bar) == replacement.consumer_bar_decision(
        bar
    )
    audit_before = transport_audit(host.transport)
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)

    with pytest.raises(AttributeError, match="read-only"):
        setattr(host, "manager", replacement)

    assert host.manager.last_timestamp_ms == original_clock == et_ms(9, 54)
    assert replacement.last_timestamp_ms == replacement_clock is None
    assert transport_audit(host.transport) == audit_before
    assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before

    # The failed rebind leaves the original integrated transaction usable; only
    # this subsequent legitimate host step may advance transport audit state.
    step = host.process_bar(bar, completed_ten_minute_payload=payload)
    assert step.transport_outcome is not None
    assert step.transport_outcome.status is TransportStatus.DELIVERED
    assert host.manager.last_timestamp_ms == et_ms(9, 57)
    assert replacement.last_timestamp_ms is None


def test_public_manager_and_transport_bindings_are_read_only_pre_mutation() -> None:
    host = _integrated_host_seeded_through_0954()
    other = GlobalOwnerHost()
    original_manager = host.manager
    original_transport = host.transport
    audit_before = transport_audit(original_transport)
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)

    replacements = (
        ("manager", OwnerManager()),
        ("manager", other.manager),
        ("transport", SharedCompletedTenMinuteTransport()),
        ("transport", other.transport),
    )
    for attribute, replacement in replacements:
        with pytest.raises(AttributeError, match="read-only"):
            setattr(host, attribute, replacement)
        assert host.manager is original_manager
        assert host.transport is original_transport
        assert transport_audit(original_transport) == audit_before
        assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before


@pytest.mark.parametrize("replacement_kind", ("new-manager", "other-manager"))
def test_manager_identity_tamper_fails_before_staging_or_transport_mutation(
    replacement_kind: str,
) -> None:
    host = _integrated_host_seeded_through_0954()
    other = GlobalOwnerHost()
    original_manager = host.manager
    original_transport = host.transport
    replacement = OwnerManager() if replacement_kind == "new-manager" else other.manager
    payload = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    audit_before = transport_audit(original_transport)
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)
    replacement_before = (
        replacement.last_timestamp_ms,
        replacement.state,
        replacement.owner,
    )

    # Bypass the normal read-only property only to prove the process_bar boundary
    # itself fails before staging or transport mutation.
    object.__setattr__(host, "_manager", replacement)
    with pytest.raises(ValueError, match="manager identity changed"):
        host.process_bar(
            bar3(9, 57), completed_ten_minute_payload=payload
        )

    assert transport_audit(original_transport) == audit_before
    assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before
    assert original_manager.last_timestamp_ms == et_ms(9, 54)
    assert (
        replacement.last_timestamp_ms,
        replacement.state,
        replacement.owner,
    ) == replacement_before


@pytest.mark.parametrize("replacement_kind", ("new-transport", "other-transport"))
def test_transport_identity_tamper_fails_before_staging_or_any_audit_mutation(
    replacement_kind: str,
) -> None:
    host = _integrated_host_seeded_through_0954()
    other = GlobalOwnerHost()
    original_transport = host.transport
    replacement = (
        SharedCompletedTenMinuteTransport()
        if replacement_kind == "new-transport"
        else other.transport
    )
    payload = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    original_before = transport_audit(original_transport)
    replacement_before = transport_audit(replacement)
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)

    object.__setattr__(host, "_transport", replacement)
    with pytest.raises(ValueError, match="transport identity changed"):
        host.process_bar(
            bar3(9, 57), completed_ten_minute_payload=payload
        )

    assert transport_audit(original_transport) == original_before
    assert transport_audit(replacement) == replacement_before
    assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before
    assert host.manager.last_timestamp_ms == et_ms(9, 54)


def test_direct_manager_ingest_cannot_manufacture_host_transport_receipt() -> None:
    host = _integrated_host_seeded_through_0954()
    bar = bar3(9, 57)
    payload = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    forged_outcome = TransportOutcome(
        status=TransportStatus.DELIVERED,
        reason=TransportReason.DELIVERED,
        confirmed_bar_open_ms=bar.timestamp_ms,
        payload=payload,
    )
    audit_before = transport_audit(host.transport)
    manager_before = (
        host.manager.last_timestamp_ms,
        host.manager.state,
        host.manager.owner,
    )

    with pytest.raises(
        ValueError, match="accepted only from GlobalOwnerHost.process_bar"
    ):
        host.manager.ingest(bar, transport_outcome=forged_outcome)

    assert transport_audit(host.transport) == audit_before
    assert (
        host.manager.last_timestamp_ms,
        host.manager.state,
        host.manager.owner,
    ) == manager_before



def test_public_transport_audit_clocks_are_read_only_and_cannot_forge_raw_gap() -> None:
    host = GlobalOwnerHost()
    first = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    delivered = host.process_bar(
        bar3(9, 42), completed_ten_minute_payload=first
    )
    assert delivered.transport_outcome is not None
    assert delivered.transport_outcome.status is TransportStatus.DELIVERED
    host.process_bar(bar3(9, 45))
    host.process_bar(bar3(9, 48))

    audit_before = transport_audit(host.transport)
    manager_clock_before = host.manager.last_timestamp_ms
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)
    assert audit_before[1:3] == (et_ms(9, 30), et_ms(9, 30))

    with pytest.raises(AttributeError):
        host.transport.last_observed_source_time = et_ms(9, 20)
    with pytest.raises(AttributeError):
        host.transport.last_consumed_source_time = et_ms(9, 20)

    assert transport_audit(host.transport) == audit_before
    assert host.manager.last_timestamp_ms == manager_clock_before == et_ms(9, 48)
    assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before

    second = CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))
    recovered = host.process_bar(
        bar3(9, 51), completed_ten_minute_payload=second
    )
    assert recovered.transport_outcome is not None
    assert recovered.transport_outcome.status is TransportStatus.DELIVERED
    assert recovered.transport_outcome.reason is TransportReason.DELIVERED
    assert host.transport.last_observed_source_time == et_ms(9, 40)
    assert host.transport.last_consumed_source_time == et_ms(9, 40)


def test_unseeded_transport_audit_properties_reject_public_assignment_pre_mutation() -> None:
    host = GlobalOwnerHost()
    audit_before = transport_audit(host.transport)
    manager_before = host.manager.last_timestamp_ms
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)

    replacements = (
        ("last_observed_source_time", et_ms(9, 20)),
        ("last_consumed_source_time", et_ms(9, 20)),
        ("pending_payload", CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))),
        ("rejected_source_times", frozenset({et_ms(9, 30)})),
        ("reset_visible_at_cutoff_ms", et_ms(9, 42)),
    )
    for attribute, value in replacements:
        with pytest.raises(AttributeError):
            setattr(host.transport, attribute, value)
        assert transport_audit(host.transport) == audit_before
        assert host.manager.last_timestamp_ms == manager_before is None
        assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before


def test_cross_host_audit_reads_cannot_be_assigned_into_another_transport() -> None:
    host_a = GlobalOwnerHost()
    host_b = GlobalOwnerHost()
    payload_a = CompletedTenMinutePayload(et_ms(9, 30), et_ms(9, 40))
    payload_b = CompletedTenMinutePayload(et_ms(10, 0), et_ms(10, 10))
    assert host_a.process_bar(
        bar3(9, 42), completed_ten_minute_payload=payload_a
    ).transport_outcome.status is TransportStatus.DELIVERED
    assert host_b.process_bar(
        bar3(10, 12), completed_ten_minute_payload=payload_b
    ).transport_outcome.status is TransportStatus.DELIVERED

    audit_a_before = transport_audit(host_a.transport)
    audit_b_before = transport_audit(host_b.transport)
    clocks_a_before = host_a.manager.last_timestamp_ms
    staged_a_before = (host_a.staged_raw_snapshot, host_a.raw_snapshot_dirty)

    with pytest.raises(AttributeError):
        host_a.transport.last_observed_source_time = (
            host_b.transport.last_observed_source_time
        )
    with pytest.raises(AttributeError):
        host_a.transport.last_consumed_source_time = (
            host_b.transport.last_consumed_source_time
        )

    assert transport_audit(host_a.transport) == audit_a_before
    assert transport_audit(host_b.transport) == audit_b_before
    assert host_a.manager.last_timestamp_ms == clocks_a_before
    assert (host_a.staged_raw_snapshot, host_a.raw_snapshot_dirty) == staged_a_before


def test_host_audit_properties_are_read_only_pre_mutation() -> None:
    host = _integrated_host_seeded_through_0954()
    transport_before = transport_audit(host.transport)
    manager_before = host.manager.last_timestamp_ms
    staged_before = (host.staged_raw_snapshot, host.raw_snapshot_dirty)

    for attribute, value in (
        ("staged_raw_snapshot", CompletedTenMinutePayload(et_ms(9, 40), et_ms(9, 50))),
        ("raw_snapshot_dirty", not host.raw_snapshot_dirty),
    ):
        with pytest.raises(AttributeError):
            setattr(host, attribute, value)
        assert transport_audit(host.transport) == transport_before
        assert host.manager.last_timestamp_ms == manager_before
        assert (host.staged_raw_snapshot, host.raw_snapshot_dirty) == staged_before


def test_integrated_host_gate_and_priority_match_generated_pine() -> None:
    assert (
        "bool goConsumerBarEligible = barstate.isconfirmed and goHostContractOk "
        "and goPreDataOk and not goDuplicate3m and not goBackward3m and not goGap3m"
        in PINE_SOURCE
    )
    assert "bool goPayloadVisible = goConsumerBarEligible" in PINE_SOURCE
    assert "goLast3mTime := goGap3m ? time : na" in PINE_SOURCE
    assert PINE_SOURCE.index("bool goConsumerBarEligible") < PINE_SOURCE.index(
        "bool goPayloadVisible"
    )
    assert PINE_SOURCE.index("if globalReset") < PINE_SOURCE.index(
        "// Existing owner price terminal always wins; stop precedes target."
    )

    integrated_source = inspect.getsource(GlobalOwnerHost.process_bar)
    binding_index = integrated_source.index("self._assert_bound_components()")
    gate_index = integrated_source.index("consumer_bar_decision(bar)")
    stage_index = integrated_source.index("if completed_ten_minute_payload is not None")
    ineligible_index = integrated_source.index("if not consumer_bar.eligible")
    permit_index = integrated_source.index("self._authority.issue")
    poll_index = integrated_source.index("self._transport._poll_from_host")
    manager_index = integrated_source.index("self._manager.ingest(", poll_index)
    assert (
        binding_index
        < gate_index
        < stage_index
        < ineligible_index
        < permit_index
        < poll_index
        < manager_index
    )
    assert "return GlobalOwnerStep(consumer_bar, None, observation)" in (
        integrated_source[ineligible_index:permit_index]
    )
    assert "self.transport.offer(" not in integrated_source
    assert "self.transport.consume_for(" not in integrated_source

    host_source = inspect.getsource(GlobalOwnerHost)
    authority_source = inspect.getsource(
        global_owner_oracle._HostMutationAuthority.assert_bound_components
    )
    assert "def manager(self)" in host_source
    assert "def transport(self)" in host_source
    assert "@manager.setter" not in host_source
    assert "@transport.setter" not in host_source
    assert "read-only GlobalOwnerHost binding" in host_source
    assert "host is not self._host" in authority_source
    assert "host._authority is not self" in authority_source
    assert "host.manager is not self._manager" in authority_source
    assert "host.transport is not self._transport" in authority_source

    transport_source = inspect.getsource(SharedCompletedTenMinuteTransport)
    assert "def last_observed_source_time(self)" in transport_source
    assert "def last_consumed_source_time(self)" in transport_source
    assert "@last_observed_source_time.setter" not in transport_source
    assert "@last_consumed_source_time.setter" not in transport_source
    assert "self._last_observed_source_time" in transport_source
    assert "self._last_consumed_source_time" in transport_source
    assert "self.last_observed_source_time =" not in transport_source
    assert "self.last_consumed_source_time =" not in transport_source

    public_offer = inspect.getsource(SharedCompletedTenMinuteTransport.offer)
    public_poll = inspect.getsource(SharedCompletedTenMinuteTransport.consume_for)
    assert "public transport mutation is disabled" in public_offer
    assert "public transport mutation is disabled" in public_poll

    atomic_poll = inspect.getsource(
        SharedCompletedTenMinuteTransport._poll_from_host
    )
    authorize_index = atomic_poll.index("authority.authorize_transport")
    cutoff_index = atomic_poll.index("self._record_reset_boundary")
    offer_index = atomic_poll.index("self._offer_from_host")
    consume_index = atomic_poll.index("self._consume_core")
    assert authorize_index < cutoff_index < offer_index < consume_index

    manager_source = inspect.getsource(OwnerManager.ingest)
    decision_index = manager_source.index("consumer_bar_decision(bar)")
    outcome_reject_index = manager_source.index(
        "ineligible 3m host bars must not carry a transport outcome"
    )
    authority_index = manager_source.index("authority.authorize_manager")
    raw_reset_index = manager_source.index(
        "transport_outcome.status is TransportStatus.RESET"
    )
    price_terminal_index = manager_source.index("self._owner_local_stop(bar)")
    assert (
        decision_index
        < outcome_reject_index
        < authority_index
        < raw_reset_index
        < price_terminal_index
    )
    assert "keep_timestamp=reason is OwnerReason.DATA_GAP_RESET" in manager_source

    assert "ConsumerBarDecision" not in global_owner_oracle.__all__
    assert "SharedCompletedTenMinuteTransport" not in global_owner_oracle.__all__
