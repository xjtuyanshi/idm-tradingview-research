"""Deterministic reference oracle for the Phase 1 3m global owner.

The oracle joins two already-accepted 10m producers only at an immutable
``PlanEnvelope`` boundary.  It does not vote, score, place orders, call a broker,
or claim fills/profitability.  The implementation is deliberately explicit:
TREND_CONTINUATION and POSITION_REVERSAL keep different timing and stop policies,
while one OwnerManager enforces global ownership, suppression, collision
fail-closed behavior, and one outward event per confirmed 3m bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum, IntEnum
from math import isfinite
from typing import Iterable, Sequence

from research.phase1_10m_position_reversal_oracle import (
    Direction as ReversalDirection,
    OpportunityPayload as ReversalOpportunityPayload,
)
from research.phase1_10m_primary_opportunity_oracle import (
    Direction as TrendDirection,
    NamedLevelSource,
    OpportunityPlan as TrendOpportunityPlan,
)

PROTOCOL_VERSION = "phase1-3m-global-owner-1.0"
SCHEMA_VERSION = "phase1-plan-envelope-1.0"
EXPECTED_SYMBOL = "CAPITALCOM:SPX500"
THREE_MINUTE_MS = 180_000
TEN_MINUTE_MS = 600_000
MINIMUM_SPACE_R = 1.0
TREND_MAX_TRIGGER_BARS = 8
PLAN_FINGERPRINT_VERSION = "GOFP1"
PLAN_NUMBER_SCALE = 10_000_000_000


class LaneId(str, Enum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    POSITION_REVERSAL = "POSITION_REVERSAL"


class Direction(IntEnum):
    SHORT = -1
    NONE = 0
    LONG = 1


class OwnerState(str, Enum):
    WAIT_10M = "WAIT_10M"
    WAIT_PULLBACK = "WAIT_PULLBACK"
    WAIT_TRIGGER = "WAIT_TRIGGER"
    WAIT_IMMEDIATE_CONFIRM = "WAIT_IMMEDIATE_CONFIRM"
    WAIT_FRESH_CROSS = "WAIT_FRESH_CROSS"
    ENTERED = "ENTERED"


class OwnerEvent(str, Enum):
    NONE = "NONE"
    LONG_ENTRY = "LONG_ENTRY"
    SHORT_ENTRY = "SHORT_ENTRY"
    INVALIDATED = "INVALIDATED"
    TARGET_REACHED = "TARGET_REACHED"
    EXPIRED = "EXPIRED"
    MISSED = "MISSED"
    CONFLICT = "CONFLICT"
    DATA_RESET = "DATA_RESET"


class OwnerReason(str, Enum):
    WAIT_10M = "WAIT_10M"
    DATA_UNCONFIRMED = "DATA_UNCONFIRMED"
    DATA_SYMBOL_MISMATCH = "DATA_SYMBOL_MISMATCH"
    DATA_TIMEFRAME_MISMATCH = "DATA_TIMEFRAME_MISMATCH"
    DATA_NON_STANDARD = "DATA_NON_STANDARD"
    DATA_INVALID = "DATA_INVALID"
    DATA_DUPLICATE_IGNORED = "DATA_DUPLICATE_IGNORED"
    DATA_NON_MONOTONIC = "DATA_NON_MONOTONIC"
    DATA_GAP_RESET = "DATA_GAP_RESET"
    NEW_TREND_OWNER = "NEW_TREND_OWNER"
    NEW_REVERSAL_OWNER = "NEW_REVERSAL_OWNER"
    WAIT_PULLBACK = "WAIT_PULLBACK"
    PULLBACK_FROZEN = "PULLBACK_FROZEN"
    WAIT_LATER_TRIGGER = "WAIT_LATER_TRIGGER"
    WAIT_IMMEDIATE_CONFIRM = "WAIT_IMMEDIATE_CONFIRM"
    WAIT_FIRST_FRESH_CROSS = "WAIT_FIRST_FRESH_CROSS"
    ENTRY_CONFIRMED = "ENTRY_CONFIRMED"
    SPACE_LT_1R = "SPACE_LT_1R"
    IMMEDIATE_CONFIRM_MISSED = "IMMEDIATE_CONFIRM_MISSED"
    FIRST_CROSS_MISSED = "FIRST_CROSS_MISSED"
    TREND_TRIGGER_EXPIRED = "TREND_TRIGGER_EXPIRED"
    PERMISSION_EXPIRED = "PERMISSION_EXPIRED"
    CONTEXT_EXPIRED = "CONTEXT_EXPIRED"
    PRODUCER_EXPIRED = "PRODUCER_EXPIRED"
    SOURCE_INVALID = "SOURCE_INVALID"
    OPPORTUNITY_INVALIDATED = "OPPORTUNITY_INVALIDATED"
    OPPORTUNITY_TARGET_REACHED = "OPPORTUNITY_TARGET_REACHED"
    PRE_ADOPTION_INVALIDATED = "PRE_ADOPTION_INVALIDATED"
    PRE_ADOPTION_TARGET_REACHED = "PRE_ADOPTION_TARGET_REACHED"
    OWNER_RETAINED = "OWNER_RETAINED"
    OWNER_BLOCKED_CANDIDATE = "OWNER_BLOCKED_CANDIDATE"
    OPPOSITE_DIRECTION_CONFLICT = "OPPOSITE_DIRECTION_CONFLICT"
    IDENTITY_COLLISION = "IDENTITY_COLLISION"
    CANDIDATE_SUPPRESSED = "CANDIDATE_SUPPRESSED"


class TransportStatus(str, Enum):
    """Closed result vocabulary for one confirmed 3m transport poll."""

    PENDING = "PENDING"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    RESET = "RESET"
    DELIVERED = "DELIVERED"


class TransportReason(str, Enum):
    """Audit reason paired with :class:`TransportStatus`."""

    NO_PENDING_PAYLOAD = "NO_PENDING_PAYLOAD"
    WAIT_VISIBLE_AT = "WAIT_VISIBLE_AT"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"
    EXPLICIT_REJECTED_LEDGER = "EXPLICIT_REJECTED_LEDGER"
    RESET_CUTOFF = "RESET_CUTOFF"
    RAW_10M_OHLC_INVALID = "RAW_10M_OHLC_INVALID"
    RAW_10M_BACKWARD = "RAW_10M_BACKWARD"
    RAW_10M_GAP = "RAW_10M_GAP"
    DELIVERED = "DELIVERED"


class ProducerTerminalKind(str, Enum):
    """Closed producer-event vocabulary accepted by OwnerManager.

    INVALIDATED and TARGET_REACHED may settle either waiting or entered owners.
    EXPIRED may settle an unentered owner only.  The remaining values are lane
    lifecycle/status observations: they may end an unentered owner but are
    ignored after entry.  Unknown strings are rejected at construction time.
    """

    INVALIDATED = "INVALIDATED"
    TARGET_REACHED = "TARGET_REACHED"
    EXPIRED = "EXPIRED"
    ACTIVE_NONE = "ACTIVE_NONE"
    PERMISSION_EXPIRED = "PERMISSION_EXPIRED"
    CONTEXT_EXPIRED = "CONTEXT_EXPIRED"
    SOURCE_INVALID = "SOURCE_INVALID"
    IDENTITY_DRIFT = "IDENTITY_DRIFT"
    SUPPRESSED = "SUPPRESSED"
    CONTEXT_RESET = "CONTEXT_RESET"
    DATA_RESET = "DATA_RESET"


UNENTERED_ENDING_TERMINALS = frozenset(
    {
        ProducerTerminalKind.EXPIRED,
        ProducerTerminalKind.ACTIVE_NONE,
        ProducerTerminalKind.PERMISSION_EXPIRED,
        ProducerTerminalKind.CONTEXT_EXPIRED,
        ProducerTerminalKind.SOURCE_INVALID,
        ProducerTerminalKind.IDENTITY_DRIFT,
        ProducerTerminalKind.SUPPRESSED,
        ProducerTerminalKind.CONTEXT_RESET,
        ProducerTerminalKind.DATA_RESET,
    }
)


@dataclass(frozen=True, slots=True)
class ThreeMinuteBar:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    ema5: float
    ema12: float
    symbol: str = EXPECTED_SYMBOL
    timeframe_ms: int = THREE_MINUTE_MS
    is_confirmed: bool = True
    is_standard: bool = True

    @property
    def close_time_ms(self) -> int:
        return self.timestamp_ms + self.timeframe_ms


@dataclass(frozen=True, slots=True)
class PlanEnvelope:
    schema_version: str
    lane_id: LaneId
    opportunity_id: str
    episode_id: str
    payload_fingerprint: str
    direction: Direction
    producer_trigger: float
    invalidation: float
    target: float
    target_source_key: str
    confirmation_time_ms: int
    visible_at_ms: int
    permission_expires_at_ms: int
    context_valid_until_ms: int | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported PlanEnvelope schema_version")
        if not isinstance(self.lane_id, LaneId):
            raise ValueError("PlanEnvelope lane_id must use the closed lane set")
        if not self.opportunity_id or not self.episode_id or not self.payload_fingerprint:
            raise ValueError("PlanEnvelope identity fields must be non-empty")
        if not self.target_source_key:
            raise ValueError("PlanEnvelope target_source_key must be non-empty")
        if not isinstance(self.direction, Direction) or self.direction not in (
            Direction.LONG,
            Direction.SHORT,
        ):
            raise ValueError("PlanEnvelope direction must be LONG or SHORT")
        numbers = (self.producer_trigger, self.invalidation, self.target)
        if not all(isfinite(value) for value in numbers):
            raise ValueError("PlanEnvelope geometry must be finite")
        if self.confirmation_time_ms <= 0 or self.visible_at_ms <= 0:
            raise ValueError("PlanEnvelope times must be positive")
        if self.visible_at_ms <= self.confirmation_time_ms:
            raise ValueError("visible_at_ms must be after confirmation_time_ms")
        if self.permission_expires_at_ms <= self.visible_at_ms:
            raise ValueError("permission expiry must be after visibility")
        if (
            self.context_valid_until_ms is not None
            and self.context_valid_until_ms <= self.visible_at_ms
        ):
            raise ValueError("context validity must extend beyond visibility")

    @property
    def base_identity(self) -> tuple[LaneId, str]:
        return self.lane_id, self.opportunity_id

    @property
    def full_identity(self) -> tuple[LaneId, str, str]:
        return self.lane_id, self.opportunity_id, self.payload_fingerprint


@dataclass(frozen=True, slots=True)
class AdapterCandidate:
    envelope: PlanEnvelope
    overlap_bar: ThreeMinuteBar


@dataclass(frozen=True, slots=True)
class ProducerTerminal:
    lane_id: LaneId
    opportunity_id: str
    payload_fingerprint: str
    kind: ProducerTerminalKind

    def __post_init__(self) -> None:
        if not isinstance(self.lane_id, LaneId):
            raise ValueError("producer terminal lane_id is outside the closed lane set")
        if not isinstance(self.kind, ProducerTerminalKind):
            raise ValueError("producer terminal kind is outside the closed allowlist")
        if not self.opportunity_id or not self.payload_fingerprint:
            raise ValueError("producer terminal identity must be complete")

    @property
    def full_identity(self) -> tuple[LaneId, str, str]:
        return self.lane_id, self.opportunity_id, self.payload_fingerprint


@dataclass(frozen=True, slots=True)
class CompletedTenMinutePayload:
    source_time_ms: int
    visible_at_ms: int
    is_previous_completed: bool = True
    raw_ohlc_valid: bool = True
    candidates: tuple[AdapterCandidate, ...] = ()
    terminals: tuple[ProducerTerminal, ...] = ()

    def __post_init__(self) -> None:
        if self.source_time_ms <= 0 or self.visible_at_ms <= self.source_time_ms:
            raise ValueError("invalid completed-10m source/visible times")
        if self.visible_at_ms - self.source_time_ms != TEN_MINUTE_MS:
            raise ValueError("completed-10m payload must span exactly 600000ms")
        if not isinstance(self.raw_ohlc_valid, bool):
            raise ValueError("raw_ohlc_valid must be bool")
        for candidate in self.candidates:
            envelope = candidate.envelope
            if envelope.confirmation_time_ms != self.source_time_ms:
                raise ValueError("candidate confirmation must match payload source time")
            if envelope.visible_at_ms != self.visible_at_ms:
                raise ValueError("candidate visibility must match payload time_close")
            if not (
                candidate.overlap_bar.timestamp_ms < self.visible_at_ms
                <= candidate.overlap_bar.close_time_ms
            ):
                raise ValueError("candidate overlap bar must contain payload visibility")


@dataclass(frozen=True, slots=True)
class TransportOutcome:
    """Typed result of polling the shared completed-10m transport.

    A raw reset is never represented as an ordinary missing payload.  The
    caller can therefore route ``RESET`` to OwnerManager before any owner price
    terminal, producer terminal, timing, or adoption logic.
    """

    status: TransportStatus
    reason: TransportReason
    confirmed_bar_open_ms: int
    payload: CompletedTenMinutePayload | None = None
    reset_cutoff_ms: int | None = None

    def __post_init__(self) -> None:
        if self.confirmed_bar_open_ms <= 0:
            raise ValueError("confirmed_bar_open_ms must be positive")
        if not isinstance(self.status, TransportStatus):
            raise ValueError("transport status is outside the closed set")
        if not isinstance(self.reason, TransportReason):
            raise ValueError("transport reason is outside the closed set")

        allowed_reasons = {
            TransportStatus.PENDING: {
                TransportReason.NO_PENDING_PAYLOAD,
                TransportReason.WAIT_VISIBLE_AT,
            },
            TransportStatus.DUPLICATE: {TransportReason.ALREADY_CONSUMED},
            TransportStatus.REJECTED: {
                TransportReason.EXPLICIT_REJECTED_LEDGER,
                TransportReason.RESET_CUTOFF,
            },
            TransportStatus.RESET: {
                TransportReason.RAW_10M_OHLC_INVALID,
                TransportReason.RAW_10M_BACKWARD,
                TransportReason.RAW_10M_GAP,
            },
            TransportStatus.DELIVERED: {TransportReason.DELIVERED},
        }
        if self.reason not in allowed_reasons[self.status]:
            raise ValueError("transport status/reason pair is invalid")

        payload_required = self.status in {
            TransportStatus.DUPLICATE,
            TransportStatus.REJECTED,
            TransportStatus.RESET,
            TransportStatus.DELIVERED,
        }
        if payload_required and self.payload is None:
            raise ValueError("transport outcome status requires a payload")
        if self.status is TransportStatus.RESET:
            if self.reset_cutoff_ms is None:
                raise ValueError("transport reset requires reset_cutoff_ms")
        elif self.reset_cutoff_ms is not None:
            raise ValueError("only transport reset may carry reset_cutoff_ms")

    @property
    def delivered_payload(self) -> CompletedTenMinutePayload | None:
        return self.payload if self.status is TransportStatus.DELIVERED else None


@dataclass(frozen=True, slots=True)
class ConsumerBarDecision:
    """Public audit value for the Pine-equivalent 3m host gate.

    This value is intentionally *not* a transport capability.  It may be
    constructed by callers for inspection or tests, but no transport mutation
    API trusts its ``eligible`` boolean.  Only :class:`GlobalOwnerHost` can mint
    the private, host-bound, one-shot permit used by the transport.
    """

    bar_open_ms: int
    eligible: bool
    reason: OwnerReason | None

    def __post_init__(self) -> None:
        if self.bar_open_ms <= 0:
            raise ValueError("consumer bar open must be positive")
        if self.eligible != (self.reason is None):
            raise ValueError(
                "eligible consumer bars must have no reason; ineligible bars need one"
            )


_TRANSPORT_PERMIT_CONSTRUCTOR_KEY = object()


@dataclass(frozen=True, slots=True, init=False)
class _TransportPermit:
    """Private one-shot capability binding one host, manager, transport and bar."""

    authority: object
    host: object
    manager: object
    transport: object
    bar: ThreeMinuteBar
    decision: ConsumerBarDecision
    manager_clock_before_ms: int | None
    nonce: int

    def __init__(
        self,
        *,
        constructor_key: object,
        authority: object,
        host: object,
        manager: object,
        transport: object,
        bar: ThreeMinuteBar,
        decision: ConsumerBarDecision,
        manager_clock_before_ms: int | None,
        nonce: int,
    ) -> None:
        if constructor_key is not _TRANSPORT_PERMIT_CONSTRUCTOR_KEY:
            raise TypeError("transport permits are minted only by GlobalOwnerHost")
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "manager", manager)
        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "bar", bar)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "manager_clock_before_ms", manager_clock_before_ms)
        object.__setattr__(self, "nonce", nonce)


@dataclass(slots=True)
class _PermitRecord:
    permit: _TransportPermit
    transport_used: bool = False
    manager_used: bool = False
    outcome: TransportOutcome | None = None


class _HostMutationAuthority:
    """Private capability authority shared by exactly one integrated host."""

    def __init__(
        self,
        *,
        host: GlobalOwnerHost,
        manager: OwnerManager,
        transport: SharedCompletedTenMinuteTransport,
    ) -> None:
        self._host = host
        self._manager = manager
        self._transport = transport
        self._next_nonce = 1
        self._records: dict[int, _PermitRecord] = {}

    def assert_bound_components(
        self,
        *,
        host: GlobalOwnerHost,
        manager: OwnerManager,
        transport: SharedCompletedTenMinuteTransport,
    ) -> None:
        """Fail before staging/polling if the integrated host identity drifted."""

        if host is not self._host:
            raise ValueError("mutation authority belongs to another global owner host")
        if host._authority is not self:
            raise ValueError("global owner host authority identity changed")
        if manager is not self._manager or host.manager is not self._manager:
            raise ValueError("global owner host manager identity changed")
        if transport is not self._transport or host.transport is not self._transport:
            raise ValueError("global owner host transport identity changed")
        if manager._host_authority is not self:
            raise ValueError("owner manager is not bound to this global owner host")
        if transport._authority is not self:
            raise ValueError("transport is not bound to this global owner host")

    def issue(
        self,
        *,
        host: GlobalOwnerHost,
        bar: ThreeMinuteBar,
        decision: ConsumerBarDecision,
    ) -> _TransportPermit:
        self.assert_bound_components(
            host=host, manager=self._manager, transport=self._transport
        )
        expected = self._manager.consumer_bar_decision(bar)
        if decision != expected or not expected.eligible:
            raise ValueError("only the bound host may authorize an eligible 3m bar")
        if decision.bar_open_ms != bar.timestamp_ms:
            raise ValueError("consumer decision timestamp does not match the host bar")
        nonce = self._next_nonce
        self._next_nonce += 1
        permit = _TransportPermit(
            constructor_key=_TRANSPORT_PERMIT_CONSTRUCTOR_KEY,
            authority=self,
            host=self._host,
            manager=self._manager,
            transport=self._transport,
            bar=bar,
            decision=decision,
            manager_clock_before_ms=self._manager.last_timestamp_ms,
            nonce=nonce,
        )
        self._records[nonce] = _PermitRecord(permit=permit)
        return permit

    def _record_for(
        self,
        permit: _TransportPermit,
        *,
        expected_bar_open_ms: int,
    ) -> _PermitRecord:
        if not isinstance(permit, _TransportPermit):
            raise TypeError("host-bound transport permit required")
        if permit.authority is not self:
            raise ValueError("transport permit belongs to another host")
        if permit.host is not self._host:
            raise ValueError("transport permit belongs to another global owner host")
        if permit.manager is not self._manager:
            raise ValueError("transport permit belongs to another owner manager")
        if permit.transport is not self._transport:
            raise ValueError("transport permit belongs to another transport")
        if permit.bar.timestamp_ms != expected_bar_open_ms:
            raise ValueError("transport permit timestamp mismatch")
        if permit.decision.bar_open_ms != expected_bar_open_ms:
            raise ValueError("transport permit decision timestamp mismatch")
        record = self._records.get(permit.nonce)
        if record is None or record.permit is not permit:
            raise ValueError("transport permit is unknown or already consumed")
        return record

    def authorize_transport(
        self,
        permit: _TransportPermit,
        *,
        transport: SharedCompletedTenMinuteTransport,
        confirmed_bar_open_ms: int,
    ) -> None:
        self.assert_bound_components(
            host=permit.host, manager=permit.manager, transport=transport
        )
        if transport is not self._transport:
            raise ValueError("transport permit is bound to a different transport")
        record = self._record_for(
            permit, expected_bar_open_ms=confirmed_bar_open_ms
        )
        if record.transport_used:
            raise ValueError("transport permit has already polled the transport")
        if record.manager_used:
            raise ValueError("transport permit has already completed the host step")
        if self._manager.last_timestamp_ms != permit.manager_clock_before_ms:
            raise ValueError("owner manager clock changed after permit issuance")
        expected = self._manager.consumer_bar_decision(permit.bar)
        if expected != permit.decision or not expected.eligible:
            raise ValueError("transport permit no longer matches an eligible host bar")
        record.transport_used = True

    def bind_outcome(
        self, permit: _TransportPermit, outcome: TransportOutcome
    ) -> None:
        self.assert_bound_components(
            host=permit.host, manager=permit.manager, transport=permit.transport
        )
        record = self._record_for(
            permit, expected_bar_open_ms=outcome.confirmed_bar_open_ms
        )
        if not record.transport_used or record.manager_used:
            raise ValueError("transport outcome is outside the permitted host phase")
        if record.outcome is not None:
            raise ValueError("transport permit already has an outcome")
        record.outcome = outcome

    def authorize_manager(
        self,
        permit: _TransportPermit,
        *,
        manager: OwnerManager,
        bar_open_ms: int,
        outcome: TransportOutcome,
    ) -> None:
        self.assert_bound_components(
            host=permit.host, manager=manager, transport=permit.transport
        )
        if manager is not self._manager:
            raise ValueError("transport permit is bound to a different owner manager")
        record = self._record_for(permit, expected_bar_open_ms=bar_open_ms)
        if not record.transport_used or record.outcome is not outcome:
            raise ValueError("manager must receive the exact host-polled outcome")
        if record.manager_used:
            raise ValueError("transport permit has already been used by the manager")
        if self._manager.last_timestamp_ms != permit.manager_clock_before_ms:
            raise ValueError("owner manager clock changed before host ingest")
        record.manager_used = True
        del self._records[permit.nonce]


@dataclass(frozen=True, slots=True)
class OwnerObservation:
    protocol_version: str
    timestamp_ms: int
    data_valid: bool
    state: OwnerState
    event: OwnerEvent
    reason_code: OwnerReason
    lane_id: LaneId | None
    opportunity_id: str | None
    payload_fingerprint: str | None
    direction: Direction
    frozen_trigger: float | None
    invalidation: float | None
    target: float | None
    entry_price: float | None
    remaining_r: float | None
    marker_price: float | None
    suppressed_count: int
    collision_tombstone_count: int


@dataclass(frozen=True, slots=True)
class GlobalOwnerStep:
    """One integrated 3m host step and its optional transport audit result."""

    consumer_bar: ConsumerBarDecision
    transport_outcome: TransportOutcome | None
    observation: OwnerObservation

    def __post_init__(self) -> None:
        if self.consumer_bar.eligible != (self.transport_outcome is not None):
            raise ValueError(
                "only an eligible confirmed 3m consumer bar may poll the transport"
            )
        if (
            self.transport_outcome is not None
            and self.transport_outcome.confirmed_bar_open_ms
            != self.consumer_bar.bar_open_ms
        ):
            raise ValueError("consumer decision and transport outcome bar mismatch")


class SharedCompletedTenMinuteTransport:
    """One host-bound previous-completed 10m transport.

    Public callers may inspect audit state but cannot offer, poll, reject, or
    change reset cutoffs.  The only production mutation path is the atomic
    GlobalOwnerHost.process_bar flow, which supplies a host-bound, single-use
    permit after the confirmed 3m bar passed the Pine-equivalent eligibility
    gate.  Observation and consumption remain separate audit identities.
    """

    def __init__(self) -> None:
        self._last_observed_source_time: int | None = None
        self._last_consumed_source_time: int | None = None
        self._reset_visible_at_cutoff_ms: int | None = None
        self._rejected_source_times: set[int] = set()
        self._pending: CompletedTenMinutePayload | None = None
        self._authority: _HostMutationAuthority | None = None

    @property
    def last_observed_source_time(self) -> int | None:
        """Read-only timestamp of the latest raw 10m payload audited."""

        return self._last_observed_source_time

    @property
    def last_consumed_source_time(self) -> int | None:
        """Read-only timestamp of the latest 10m payload delivered."""

        return self._last_consumed_source_time

    @property
    def reset_visible_at_cutoff_ms(self) -> int | None:
        return self._reset_visible_at_cutoff_ms

    @property
    def rejected_source_times(self) -> frozenset[int]:
        return frozenset(self._rejected_source_times)

    @property
    def pending_payload(self) -> CompletedTenMinutePayload | None:
        """Read-only audit view used by parity and adversarial tests."""

        return self._pending

    def _bind_authority(self, authority: _HostMutationAuthority) -> None:
        if self._authority is not None and self._authority is not authority:
            raise ValueError("transport is already bound to another global owner host")
        self._authority = authority

    # These legacy public entry points remain as explicit fail-closed guards so
    # a caller cannot mistake a public dataclass decision for authorization.
    def record_reset_boundary(self, boundary_ms: int) -> None:
        del boundary_ms
        raise RuntimeError(
            "public transport mutation is disabled; use GlobalOwnerHost.process_bar()"
        )

    def offer(self, payload: CompletedTenMinutePayload) -> None:
        del payload
        raise RuntimeError(
            "public transport mutation is disabled; use GlobalOwnerHost.process_bar()"
        )

    def consume_for(self, consumer_bar: ConsumerBarDecision) -> TransportOutcome:
        del consumer_bar
        raise RuntimeError(
            "public transport mutation is disabled; use GlobalOwnerHost.process_bar()"
        )

    def _record_reset_boundary(self, boundary_ms: int) -> None:
        if boundary_ms <= 0:
            raise ValueError("reset boundary must be positive")
        self._reset_visible_at_cutoff_ms = (
            boundary_ms
            if self._reset_visible_at_cutoff_ms is None
            else max(self._reset_visible_at_cutoff_ms, boundary_ms)
        )

    def _offer_from_host(self, payload: CompletedTenMinutePayload) -> None:
        if not payload.is_previous_completed:
            return
        if (
            self._pending is None
            or payload.source_time_ms >= self._pending.source_time_ms
        ):
            self._pending = payload

    def _outcome(
        self,
        *,
        status: TransportStatus,
        reason: TransportReason,
        confirmed_bar_open_ms: int,
        payload: CompletedTenMinutePayload | None = None,
        reset_cutoff_ms: int | None = None,
    ) -> TransportOutcome:
        return TransportOutcome(
            status=status,
            reason=reason,
            confirmed_bar_open_ms=confirmed_bar_open_ms,
            payload=payload,
            reset_cutoff_ms=reset_cutoff_ms,
        )

    def _raw_reset(
        self,
        *,
        payload: CompletedTenMinutePayload,
        confirmed_bar_open_ms: int,
        reason: TransportReason,
    ) -> TransportOutcome:
        self._record_reset_boundary(confirmed_bar_open_ms)
        self._rejected_source_times.add(payload.source_time_ms)
        return self._outcome(
            status=TransportStatus.RESET,
            reason=reason,
            confirmed_bar_open_ms=confirmed_bar_open_ms,
            payload=payload,
            reset_cutoff_ms=self._reset_visible_at_cutoff_ms,
        )

    def _consume_core(self, confirmed_bar_open_ms: int) -> TransportOutcome:
        payload = self._pending
        if payload is None:
            return self._outcome(
                status=TransportStatus.PENDING,
                reason=TransportReason.NO_PENDING_PAYLOAD,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
            )
        if payload.visible_at_ms > confirmed_bar_open_ms:
            return self._outcome(
                status=TransportStatus.PENDING,
                reason=TransportReason.WAIT_VISIBLE_AT,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
                payload=payload,
            )
        self._pending = None

        prior_observed = self._last_observed_source_time
        self._last_observed_source_time = payload.source_time_ms
        new_observation = (
            prior_observed is None or payload.source_time_ms != prior_observed
        )
        if new_observation and not payload.raw_ohlc_valid:
            return self._raw_reset(
                payload=payload,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
                reason=TransportReason.RAW_10M_OHLC_INVALID,
            )
        if new_observation and prior_observed is not None and (
            payload.source_time_ms <= prior_observed
            or payload.source_time_ms - prior_observed != TEN_MINUTE_MS
        ):
            reason = (
                TransportReason.RAW_10M_BACKWARD
                if payload.source_time_ms <= prior_observed
                else TransportReason.RAW_10M_GAP
            )
            return self._raw_reset(
                payload=payload,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
                reason=reason,
            )

        cutoff = self._reset_visible_at_cutoff_ms
        was_rejected = payload.source_time_ms in self._rejected_source_times
        rejected_by_cutoff = cutoff is not None and payload.visible_at_ms <= cutoff
        if was_rejected or rejected_by_cutoff:
            self._rejected_source_times.add(payload.source_time_ms)
            reason = (
                TransportReason.EXPLICIT_REJECTED_LEDGER
                if was_rejected
                else TransportReason.RESET_CUTOFF
            )
            return self._outcome(
                status=TransportStatus.REJECTED,
                reason=reason,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
                payload=payload,
            )
        if payload.source_time_ms == self._last_consumed_source_time:
            return self._outcome(
                status=TransportStatus.DUPLICATE,
                reason=TransportReason.ALREADY_CONSUMED,
                confirmed_bar_open_ms=confirmed_bar_open_ms,
                payload=payload,
            )
        self._last_consumed_source_time = payload.source_time_ms
        return self._outcome(
            status=TransportStatus.DELIVERED,
            reason=TransportReason.DELIVERED,
            confirmed_bar_open_ms=confirmed_bar_open_ms,
            payload=payload,
        )

    def _poll_from_host(
        self,
        *,
        permit: _TransportPermit,
        confirmed_bar_open_ms: int,
        offered_payload: CompletedTenMinutePayload | None,
        reset_boundary_ms: int | None,
    ) -> TransportOutcome:
        """Atomically synchronize cutoff, offer, and poll under one permit."""

        if offered_payload is not None and not isinstance(
            offered_payload, CompletedTenMinutePayload
        ):
            raise TypeError("offered payload must be a completed-10m payload")
        if reset_boundary_ms is not None and reset_boundary_ms <= 0:
            raise ValueError("reset boundary must be positive")
        authority = self._authority
        if authority is None:
            raise RuntimeError("transport is not bound to a global owner host")
        # Authorization is the first stateful operation.  Wrong host/manager,
        # timestamp, reused, or forged permits therefore fail before any
        # transport audit field can change.
        authority.authorize_transport(
            permit,
            transport=self,
            confirmed_bar_open_ms=confirmed_bar_open_ms,
        )
        if reset_boundary_ms is not None:
            self._record_reset_boundary(reset_boundary_ms)
        if offered_payload is not None:
            self._offer_from_host(offered_payload)
        outcome = self._consume_core(confirmed_bar_open_ms)
        authority.bind_outcome(permit, outcome)
        return outcome


def _direction(value: TrendDirection | ReversalDirection | Direction) -> Direction:
    if int(value) == 1:
        return Direction.LONG
    if int(value) == -1:
        return Direction.SHORT
    raise ValueError("producer plan direction must be LONG or SHORT")


def _length_prefix(value: str) -> str:
    return f"{len(value)}:{value}"


def _scaled_number(value: float) -> str:
    if not isfinite(value):
        return "N"
    scaled = (Decimal(str(value)) * PLAN_NUMBER_SCALE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return str(int(scaled))


def _lane_code(lane_id: LaneId) -> int:
    return 1 if lane_id is LaneId.TREND_CONTINUATION else 2


def canonical_plan_fingerprint(
    *,
    lane_id: LaneId,
    opportunity_id: str,
    episode_id: str,
    direction: Direction,
    producer_trigger: float,
    invalidation: float,
    target: float,
    target_source_key: str,
    confirmation_time_ms: int,
    visible_at_ms: int,
    permission_expires_at_ms: int,
    context_valid_until_ms: int | None,
    source_context_key: str,
) -> str:
    """Cross-language length-prefixed PlanEnvelope fingerprint material.

    The Pine host emits the same ``GOFP1`` grammar.  Length prefixes make source
    strings unambiguous even when they contain pipes, at-signs, hashes, spaces,
    or other delimiter-like characters.
    """

    fields = (
        str(_lane_code(lane_id)),
        opportunity_id,
        episode_id,
        str(int(direction)),
        _scaled_number(producer_trigger),
        _scaled_number(invalidation),
        _scaled_number(target),
        target_source_key,
        str(confirmation_time_ms),
        str(visible_at_ms),
        str(permission_expires_at_ms),
        "N" if context_valid_until_ms is None else str(context_valid_until_ms),
        source_context_key,
    )
    return PLAN_FINGERPRINT_VERSION + "".join(_length_prefix(value) for value in fields)


class TrendAdapter:
    lane_id = LaneId.TREND_CONTINUATION

    @staticmethod
    def envelope_from_plan(
        plan: TrendOpportunityPlan,
        *,
        overlap_bar: ThreeMinuteBar,
        visible_at_ms: int | None = None,
        permission_expires_at_ms: int | None = None,
    ) -> AdapterCandidate:
        if plan.next_named_level is None:
            raise ValueError("trend plan without a frozen target cannot be adapted")
        visible = (
            plan.confirmation_time_ms + TEN_MINUTE_MS
            if visible_at_ms is None
            else visible_at_ms
        )
        expires = (
            visible + 12 * TEN_MINUTE_MS
            if permission_expires_at_ms is None
            else permission_expires_at_ms
        )
        direction = _direction(plan.direction)
        provenance = (
            "N"
            if plan.next_named_level_provenance_time_ms is None
            else str(plan.next_named_level_provenance_time_ms)
        )
        target_source_key = f"{plan.next_named_level_source.value}@{provenance}"
        source_context_key = (
            _length_prefix(plan.epoch_id)
            + _length_prefix(plan.episode_id)
            + _length_prefix(target_source_key)
        )
        fingerprint = canonical_plan_fingerprint(
            lane_id=TrendAdapter.lane_id,
            opportunity_id=plan.opportunity_id,
            episode_id=plan.episode_id,
            direction=direction,
            producer_trigger=plan.entry_reference,
            invalidation=plan.invalidation,
            target=plan.next_named_level,
            target_source_key=target_source_key,
            confirmation_time_ms=plan.confirmation_time_ms,
            visible_at_ms=visible,
            permission_expires_at_ms=expires,
            context_valid_until_ms=None,
            source_context_key=source_context_key,
        )
        envelope = PlanEnvelope(
            schema_version=SCHEMA_VERSION,
            lane_id=TrendAdapter.lane_id,
            opportunity_id=plan.opportunity_id,
            episode_id=plan.episode_id,
            payload_fingerprint=fingerprint,
            direction=direction,
            producer_trigger=plan.entry_reference,
            invalidation=plan.invalidation,
            target=plan.next_named_level,
            target_source_key=target_source_key,
            confirmation_time_ms=plan.confirmation_time_ms,
            visible_at_ms=visible,
            permission_expires_at_ms=expires,
            context_valid_until_ms=None,
        )
        return AdapterCandidate(envelope=envelope, overlap_bar=overlap_bar)


class ReversalAdapter:
    lane_id = LaneId.POSITION_REVERSAL

    @staticmethod
    def envelope_from_payload(
        payload: ReversalOpportunityPayload,
        *,
        overlap_bar: ThreeMinuteBar,
    ) -> AdapterCandidate:
        context_valid_until = min(
            payload.source_valid_until_ms,
            payload.target_valid_until_ms,
            payload.atr_valid_until_ms,
        )
        direction = _direction(payload.direction)
        target_source_key = payload.target_source_fingerprint
        source_context_key = (
            _length_prefix(payload.source_fingerprint)
            + _length_prefix(payload.target_source_fingerprint)
            + _length_prefix(payload.atr_source_fingerprint)
        )
        fingerprint = canonical_plan_fingerprint(
            lane_id=ReversalAdapter.lane_id,
            opportunity_id=payload.opportunity_id,
            episode_id=payload.episode_id,
            direction=direction,
            producer_trigger=payload.trigger,
            invalidation=payload.invalidation,
            target=payload.target,
            target_source_key=target_source_key,
            confirmation_time_ms=payload.confirmation_time_ms,
            visible_at_ms=payload.visible_at_ms,
            permission_expires_at_ms=payload.expires_at_ms,
            context_valid_until_ms=context_valid_until,
            source_context_key=source_context_key,
        )
        envelope = PlanEnvelope(
            schema_version=SCHEMA_VERSION,
            lane_id=ReversalAdapter.lane_id,
            opportunity_id=payload.opportunity_id,
            episode_id=payload.episode_id,
            payload_fingerprint=fingerprint,
            direction=direction,
            producer_trigger=payload.trigger,
            invalidation=payload.invalidation,
            target=payload.target,
            target_source_key=target_source_key,
            confirmation_time_ms=payload.confirmation_time_ms,
            visible_at_ms=payload.visible_at_ms,
            permission_expires_at_ms=payload.expires_at_ms,
            context_valid_until_ms=context_valid_until,
        )
        return AdapterCandidate(envelope=envelope, overlap_bar=overlap_bar)


class OwnerManager:
    """Single global owner with lane-specific timing and terminal policies."""

    def __init__(self) -> None:
        self._last_timestamp_ms: int | None = None
        self._reset_visible_at_cutoff_ms: int | None = None
        self._owner: PlanEnvelope | None = None
        self._state = OwnerState.WAIT_10M
        self._adoption_bar: ThreeMinuteBar | None = None
        self._frozen_trigger: float | None = None
        self._trend_trigger_age = 0
        self._previous_confirmed_close: float | None = None
        self._entry_price: float | None = None
        self._entry_remaining_r: float | None = None
        self._suppressed: set[tuple[LaneId, str, str]] = set()
        self._base_registry: dict[tuple[LaneId, str], str] = {}
        self._collision_tombstones: set[tuple[LaneId, str]] = set()
        self._host_authority: _HostMutationAuthority | None = None

    def _bind_host_authority(self, authority: _HostMutationAuthority) -> None:
        if self._host_authority is not None and self._host_authority is not authority:
            raise ValueError("owner manager is already bound to another global owner host")
        self._host_authority = authority

    @property
    def owner(self) -> PlanEnvelope | None:
        return self._owner

    @property
    def state(self) -> OwnerState:
        return self._state

    @property
    def suppressed_identities(self) -> frozenset[tuple[LaneId, str, str]]:
        return frozenset(self._suppressed)

    @property
    def collision_tombstones(self) -> frozenset[tuple[LaneId, str]]:
        return frozenset(self._collision_tombstones)

    @property
    def reset_visible_at_cutoff_ms(self) -> int | None:
        """Newest 3m reset boundary; older/equal 10m payloads stay rejected."""

        return self._reset_visible_at_cutoff_ms

    @property
    def last_timestamp_ms(self) -> int | None:
        """Current confirmed-3m continuity clock used by the host gate."""

        return self._last_timestamp_ms

    @staticmethod
    def _valid_ohlc(bar: ThreeMinuteBar) -> bool:
        values = (bar.open, bar.high, bar.low, bar.close, bar.ema5, bar.ema12)
        return all(isfinite(value) for value in values) and not (
            bar.high < bar.low
            or bar.high < max(bar.open, bar.close)
            or bar.low > min(bar.open, bar.close)
        )

    @staticmethod
    def _host_reason(bar: ThreeMinuteBar) -> OwnerReason | None:
        if bar.symbol != EXPECTED_SYMBOL:
            return OwnerReason.DATA_SYMBOL_MISMATCH
        if bar.timeframe_ms != THREE_MINUTE_MS:
            return OwnerReason.DATA_TIMEFRAME_MISMATCH
        if not bar.is_standard:
            return OwnerReason.DATA_NON_STANDARD
        if not OwnerManager._valid_ohlc(bar):
            return OwnerReason.DATA_INVALID
        return None

    def consumer_bar_decision(self, bar: ThreeMinuteBar) -> ConsumerBarDecision:
        """Classify the 3m host bar without mutating manager or transport state.

        This mirrors Pine ``goConsumerBarEligible``.  Callers must make this
        decision before offering or polling a completed-10m payload.
        """

        if not bar.is_confirmed:
            return ConsumerBarDecision(
                bar.timestamp_ms, False, OwnerReason.DATA_UNCONFIRMED
            )
        host_reason = self._host_reason(bar)
        if host_reason is not None:
            return ConsumerBarDecision(bar.timestamp_ms, False, host_reason)
        prior = self._last_timestamp_ms
        if prior is not None and bar.timestamp_ms == prior:
            return ConsumerBarDecision(
                bar.timestamp_ms, False, OwnerReason.DATA_DUPLICATE_IGNORED
            )
        if prior is not None and bar.timestamp_ms < prior:
            return ConsumerBarDecision(
                bar.timestamp_ms, False, OwnerReason.DATA_NON_MONOTONIC
            )
        if prior is not None and bar.timestamp_ms - prior != THREE_MINUTE_MS:
            return ConsumerBarDecision(
                bar.timestamp_ms, False, OwnerReason.DATA_GAP_RESET
            )
        return ConsumerBarDecision(bar.timestamp_ms, True, None)

    @staticmethod
    def _transport_reset_owner_reason(reason: TransportReason) -> OwnerReason:
        if reason is TransportReason.RAW_10M_GAP:
            return OwnerReason.DATA_GAP_RESET
        if reason is TransportReason.RAW_10M_BACKWARD:
            return OwnerReason.DATA_NON_MONOTONIC
        if reason is TransportReason.RAW_10M_OHLC_INVALID:
            return OwnerReason.DATA_INVALID
        raise ValueError("transport RESET outcome has a non-reset reason")

    def _snapshot(
        self,
        *,
        bar: ThreeMinuteBar,
        data_valid: bool,
        event: OwnerEvent,
        reason: OwnerReason,
        marker_price: float | None = None,
        owner_override: PlanEnvelope | None = None,
        state_override: OwnerState | None = None,
        entry_price_override: float | None = None,
        remaining_r_override: float | None = None,
    ) -> OwnerObservation:
        owner = self._owner if owner_override is None else owner_override
        return OwnerObservation(
            protocol_version=PROTOCOL_VERSION,
            timestamp_ms=bar.timestamp_ms,
            data_valid=data_valid,
            state=self._state if state_override is None else state_override,
            event=event,
            reason_code=reason,
            lane_id=None if owner is None else owner.lane_id,
            opportunity_id=None if owner is None else owner.opportunity_id,
            payload_fingerprint=None if owner is None else owner.payload_fingerprint,
            direction=Direction.NONE if owner is None else owner.direction,
            frozen_trigger=self._frozen_trigger,
            invalidation=None if owner is None else owner.invalidation,
            target=None if owner is None else owner.target,
            entry_price=(
                self._entry_price
                if entry_price_override is None
                else entry_price_override
            ),
            remaining_r=(
                self._entry_remaining_r
                if remaining_r_override is None
                else remaining_r_override
            ),
            marker_price=marker_price,
            suppressed_count=len(self._suppressed),
            collision_tombstone_count=len(self._collision_tombstones),
        )

    def _clear_owner(self) -> None:
        self._owner = None
        self._state = OwnerState.WAIT_10M
        self._adoption_bar = None
        self._frozen_trigger = None
        self._trend_trigger_age = 0
        self._previous_confirmed_close = None
        self._entry_price = None
        self._entry_remaining_r = None

    def _suppress(self, envelope: PlanEnvelope) -> None:
        self._suppressed.add(envelope.full_identity)

    def _suppress_candidates(self, candidates: Sequence[AdapterCandidate]) -> None:
        for candidate in candidates:
            self._register_identity(candidate.envelope)
            self._suppress(candidate.envelope)

    def _register_identity(self, envelope: PlanEnvelope) -> bool:
        base = envelope.base_identity
        if base in self._collision_tombstones:
            self._suppress(envelope)
            return False
        prior = self._base_registry.get(base)
        if prior is None:
            self._base_registry[base] = envelope.payload_fingerprint
            return True
        if prior == envelope.payload_fingerprint:
            return True
        self._collision_tombstones.add(base)
        self._suppressed.add((base[0], base[1], prior))
        self._suppress(envelope)
        return False

    def _owner_local_stop(self, bar: ThreeMinuteBar) -> bool:
        owner = self._owner
        if owner is None:
            return False
        if owner.lane_id is LaneId.TREND_CONTINUATION:
            return (
                owner.direction is Direction.LONG and bar.close < owner.invalidation
            ) or (
                owner.direction is Direction.SHORT and bar.close > owner.invalidation
            )
        return (
            owner.direction is Direction.LONG and bar.low <= owner.invalidation
        ) or (
            owner.direction is Direction.SHORT and bar.high >= owner.invalidation
        )

    @staticmethod
    def _target_hit(envelope: PlanEnvelope, bar: ThreeMinuteBar) -> bool:
        return (
            envelope.direction is Direction.LONG and bar.high >= envelope.target
        ) or (
            envelope.direction is Direction.SHORT and bar.low <= envelope.target
        )

    @staticmethod
    def _stop_hit(envelope: PlanEnvelope, bar: ThreeMinuteBar) -> bool:
        if envelope.lane_id is LaneId.TREND_CONTINUATION:
            return (
                envelope.direction is Direction.LONG
                and bar.close < envelope.invalidation
            ) or (
                envelope.direction is Direction.SHORT
                and bar.close > envelope.invalidation
            )
        return (
            envelope.direction is Direction.LONG and bar.low <= envelope.invalidation
        ) or (
            envelope.direction is Direction.SHORT and bar.high >= envelope.invalidation
        )

    @staticmethod
    def _remaining_r(envelope: PlanEnvelope, close: float) -> float | None:
        if envelope.direction is Direction.LONG:
            risk = close - envelope.invalidation
            reward = envelope.target - close
        else:
            risk = envelope.invalidation - close
            reward = close - envelope.target
        if not (isfinite(risk) and isfinite(reward)) or risk <= 0 or reward <= 0:
            return None
        return reward / risk

    def _matching_terminals(
        self, terminals: Sequence[ProducerTerminal]
    ) -> tuple[ProducerTerminal, ...]:
        if self._owner is None:
            return ()
        identity = self._owner.full_identity
        return tuple(item for item in terminals if item.full_identity == identity)

    def _finish(
        self,
        *,
        bar: ThreeMinuteBar,
        event: OwnerEvent,
        reason: OwnerReason,
        marker_price: float | None = None,
        candidates: Sequence[AdapterCandidate] = (),
    ) -> OwnerObservation:
        owner = self._owner
        if owner is None:
            raise RuntimeError("owner terminal requires an owner")
        self._suppress(owner)
        self._suppress_candidates(candidates)
        entry = self._entry_price
        remaining = self._entry_remaining_r
        self._clear_owner()
        return self._snapshot(
            bar=bar,
            data_valid=True,
            event=event,
            reason=reason,
            marker_price=marker_price,
            owner_override=owner,
            state_override=OwnerState.WAIT_10M,
            entry_price_override=entry,
            remaining_r_override=remaining,
        )

    def _reset(
        self,
        *,
        bar: ThreeMinuteBar,
        reason: OwnerReason,
        candidates: Sequence[AdapterCandidate],
        keep_timestamp: bool,
        reset_boundary_ms: int | None = None,
    ) -> OwnerObservation:
        prior = self._owner
        prior_timestamp = self._last_timestamp_ms
        derived_boundary = (
            bar.timestamp_ms
            if prior_timestamp is None
            else max(bar.timestamp_ms, prior_timestamp)
        )
        reset_boundary = (
            derived_boundary
            if reset_boundary_ms is None
            else max(derived_boundary, reset_boundary_ms)
        )
        self._reset_visible_at_cutoff_ms = (
            reset_boundary
            if self._reset_visible_at_cutoff_ms is None
            else max(self._reset_visible_at_cutoff_ms, reset_boundary)
        )
        if prior is not None:
            self._suppress(prior)
        self._suppress_candidates(candidates)
        entry = self._entry_price
        remaining = self._entry_remaining_r
        self._clear_owner()
        self._last_timestamp_ms = bar.timestamp_ms if keep_timestamp else None
        return self._snapshot(
            bar=bar,
            data_valid=False,
            event=OwnerEvent.DATA_RESET,
            reason=reason,
            owner_override=prior,
            state_override=OwnerState.WAIT_10M,
            entry_price_override=entry,
            remaining_r_override=remaining,
        )

    def _candidate_preterminated(
        self, candidate: AdapterCandidate, adoption_bar: ThreeMinuteBar
    ) -> OwnerReason | None:
        envelope = candidate.envelope
        checked_bars = (candidate.overlap_bar, adoption_bar)
        if any(self._stop_hit(envelope, checked_bar) for checked_bar in checked_bars):
            return OwnerReason.PRE_ADOPTION_INVALIDATED
        if any(self._target_hit(envelope, checked_bar) for checked_bar in checked_bars):
            return OwnerReason.PRE_ADOPTION_TARGET_REACHED
        return None

    def _adopt(self, candidate: AdapterCandidate, bar: ThreeMinuteBar) -> OwnerObservation:
        envelope = candidate.envelope
        self._owner = envelope
        self._adoption_bar = bar
        self._previous_confirmed_close = bar.close
        self._entry_price = None
        self._entry_remaining_r = None
        self._suppress(envelope)  # seen ledger prevents later re-adoption
        if envelope.lane_id is LaneId.TREND_CONTINUATION:
            self._state = OwnerState.WAIT_PULLBACK
            reason = OwnerReason.NEW_TREND_OWNER
        else:
            beyond = (
                envelope.direction is Direction.LONG
                and bar.close > envelope.producer_trigger
            ) or (
                envelope.direction is Direction.SHORT
                and bar.close < envelope.producer_trigger
            )
            self._state = (
                OwnerState.WAIT_IMMEDIATE_CONFIRM
                if beyond
                else OwnerState.WAIT_FRESH_CROSS
            )
            reason = OwnerReason.NEW_REVERSAL_OWNER
        return self._snapshot(
            bar=bar,
            data_valid=True,
            event=OwnerEvent.NONE,
            reason=reason,
        )

    def _entry(self, bar: ThreeMinuteBar, remaining_r: float) -> OwnerObservation:
        if self._owner is None:
            raise RuntimeError("entry requires an owner")
        self._state = OwnerState.ENTERED
        self._entry_price = bar.close
        self._entry_remaining_r = remaining_r
        event = (
            OwnerEvent.LONG_ENTRY
            if self._owner.direction is Direction.LONG
            else OwnerEvent.SHORT_ENTRY
        )
        return self._snapshot(
            bar=bar,
            data_valid=True,
            event=event,
            reason=OwnerReason.ENTRY_CONFIRMED,
            marker_price=bar.close,
        )

    def ingest(
        self,
        bar: ThreeMinuteBar,
        *,
        candidates: Sequence[AdapterCandidate] = (),
        producer_terminals: Sequence[ProducerTerminal] = (),
        transport_outcome: TransportOutcome | None = None,
        _host_permit: _TransportPermit | None = None,
    ) -> OwnerObservation:
        consumer_bar = self.consumer_bar_decision(bar)

        if transport_outcome is not None:
            if candidates or producer_terminals:
                raise ValueError(
                    "transport outcome cannot be mixed with direct candidates/terminals"
                )
            if transport_outcome.confirmed_bar_open_ms != bar.timestamp_ms:
                raise ValueError("transport outcome belongs to a different 3m bar")
            if not consumer_bar.eligible:
                raise ValueError(
                    "ineligible 3m host bars must not carry a transport outcome; "
                    "use GlobalOwnerHost.process_bar()"
                )
            authority = self._host_authority
            if authority is None or _host_permit is None:
                raise ValueError(
                    "transport outcomes are accepted only from GlobalOwnerHost.process_bar()"
                )
            authority.authorize_manager(
                _host_permit,
                manager=self,
                bar_open_ms=bar.timestamp_ms,
                outcome=transport_outcome,
            )
        elif _host_permit is not None:
            raise ValueError("host permit requires the matching transport outcome")

        if not consumer_bar.eligible:
            reason = consumer_bar.reason
            if reason is None:
                raise RuntimeError("ineligible consumer bar is missing an audit reason")
            if reason is OwnerReason.DATA_UNCONFIRMED:
                return self._snapshot(
                    bar=bar,
                    data_valid=False,
                    event=OwnerEvent.NONE,
                    reason=reason,
                )
            if reason is OwnerReason.DATA_DUPLICATE_IGNORED:
                return self._snapshot(
                    bar=bar,
                    data_valid=False,
                    event=OwnerEvent.NONE,
                    reason=reason,
                )
            return self._reset(
                bar=bar,
                reason=reason,
                candidates=candidates,
                keep_timestamp=reason is OwnerReason.DATA_GAP_RESET,
            )

        # Raw shared-transport reset is part of global data validation and thus
        # precedes every price/producer/timing/adoption branch.  It can only be
        # produced after this bar passed the same eligibility gate as Pine.
        if (
            transport_outcome is not None
            and transport_outcome.status is TransportStatus.RESET
        ):
            payload = transport_outcome.payload
            if payload is None or transport_outcome.reset_cutoff_ms is None:
                raise RuntimeError("validated transport reset is incomplete")
            return self._reset(
                bar=bar,
                reason=self._transport_reset_owner_reason(transport_outcome.reason),
                candidates=payload.candidates,
                # Pine clears goLast3mTime on a pure goRawReset, so the next
                # confirmed 3m bar rebaselines while the cutoff remains.
                keep_timestamp=False,
                reset_boundary_ms=transport_outcome.reset_cutoff_ms,
            )

        self._last_timestamp_ms = bar.timestamp_ms

        # A successful transport delivery is the only non-reset outcome allowed
        # to contribute candidates/terminals. Pending, duplicate and rejected
        # outcomes leave the current owner timing unchanged.
        if transport_outcome is not None:
            if transport_outcome.status is TransportStatus.DELIVERED:
                payload = transport_outcome.payload
                if payload is None:
                    raise RuntimeError("validated transport delivery is incomplete")
                candidates = payload.candidates
                producer_terminals = payload.terminals
            else:
                candidates = ()
                producer_terminals = ()

        collision_on_owner = False
        for candidate in candidates:
            registered = self._register_identity(candidate.envelope)
            if (
                not registered
                and self._owner is not None
                and candidate.envelope.base_identity == self._owner.base_identity
            ):
                collision_on_owner = True

        # Existing owner price terminal always wins; stop precedes target.
        if self._owner is not None and self._owner_local_stop(bar):
            return self._finish(
                bar=bar,
                event=OwnerEvent.INVALIDATED,
                reason=OwnerReason.OPPORTUNITY_INVALIDATED,
                marker_price=self._owner.invalidation,
                candidates=candidates,
            )
        if self._owner is not None and self._target_hit(self._owner, bar):
            return self._finish(
                bar=bar,
                event=OwnerEvent.TARGET_REACHED,
                reason=OwnerReason.OPPORTUNITY_TARGET_REACHED,
                marker_price=self._owner.target,
                candidates=candidates,
            )

        matching = self._matching_terminals(producer_terminals)
        invalidated = next(
            (x for x in matching if x.kind is ProducerTerminalKind.INVALIDATED),
            None,
        )
        target_reached = next(
            (x for x in matching if x.kind is ProducerTerminalKind.TARGET_REACHED),
            None,
        )
        if self._owner is not None and invalidated is not None:
            return self._finish(
                bar=bar,
                event=OwnerEvent.INVALIDATED,
                reason=OwnerReason.OPPORTUNITY_INVALIDATED,
                marker_price=self._owner.invalidation,
                candidates=candidates,
            )
        if self._owner is not None and target_reached is not None:
            return self._finish(
                bar=bar,
                event=OwnerEvent.TARGET_REACHED,
                reason=OwnerReason.OPPORTUNITY_TARGET_REACHED,
                marker_price=self._owner.target,
                candidates=candidates,
            )

        if self._owner is not None and self._state is OwnerState.ENTERED:
            self._suppress_candidates(candidates)
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=OwnerEvent.NONE,
                reason=OwnerReason.OWNER_RETAINED,
            )

        if self._owner is not None:
            if collision_on_owner or self._owner.base_identity in self._collision_tombstones:
                return self._finish(
                    bar=bar,
                    event=OwnerEvent.MISSED,
                    reason=OwnerReason.IDENTITY_COLLISION,
                    candidates=candidates,
                )
            unentered_end = next(
                (x for x in matching if x.kind in UNENTERED_ENDING_TERMINALS),
                None,
            )
            if unentered_end is not None:
                reason = (
                    OwnerReason.PRODUCER_EXPIRED
                    if unentered_end.kind is ProducerTerminalKind.EXPIRED
                    else OwnerReason.SOURCE_INVALID
                )
                return self._finish(
                    bar=bar,
                    event=OwnerEvent.EXPIRED,
                    reason=reason,
                    candidates=candidates,
                )
            if bar.timestamp_ms >= self._owner.permission_expires_at_ms:
                return self._finish(
                    bar=bar,
                    event=OwnerEvent.EXPIRED,
                    reason=OwnerReason.PERMISSION_EXPIRED,
                    candidates=candidates,
                )
            if (
                self._owner.context_valid_until_ms is not None
                and bar.close_time_ms >= self._owner.context_valid_until_ms
            ):
                return self._finish(
                    bar=bar,
                    event=OwnerEvent.EXPIRED,
                    reason=OwnerReason.CONTEXT_EXPIRED,
                    candidates=candidates,
                )

            # A later, still-eligible opposite candidate conflicts with an
            # unentered owner before the old owner's timing can fire.  Repeated,
            # tombstoned, invisible, expired, or preterminated plans are not
            # eligible.  Same-direction candidates keep the existing no-queue /
            # no-replacement behavior.
            eligible_opposite = False
            for candidate in candidates:
                envelope = candidate.envelope
                if envelope.direction is self._owner.direction:
                    continue
                if (
                    self._reset_visible_at_cutoff_ms is not None
                    and envelope.visible_at_ms <= self._reset_visible_at_cutoff_ms
                ):
                    self._suppress(envelope)
                    continue
                if envelope.base_identity in self._collision_tombstones:
                    continue
                if envelope.full_identity in self._suppressed:
                    continue
                if envelope.visible_at_ms > bar.timestamp_ms:
                    continue
                terminal_reason = self._candidate_preterminated(candidate, bar)
                if terminal_reason is not None:
                    self._suppress(envelope)
                    continue
                if bar.timestamp_ms >= envelope.permission_expires_at_ms:
                    self._suppress(envelope)
                    continue
                if (
                    envelope.context_valid_until_ms is not None
                    and bar.close_time_ms >= envelope.context_valid_until_ms
                ):
                    self._suppress(envelope)
                    continue
                eligible_opposite = True

            if eligible_opposite:
                return self._finish(
                    bar=bar,
                    event=OwnerEvent.CONFLICT,
                    reason=OwnerReason.OPPOSITE_DIRECTION_CONFLICT,
                    candidates=candidates,
                )

            # Every non-conflicting new candidate is still permanently
            # suppressed: no queue and no replacement.
            self._suppress_candidates(candidates)
            owner = self._owner
            cloud_upper = max(bar.ema5, bar.ema12)
            cloud_lower = min(bar.ema5, bar.ema12)

            if self._state is OwnerState.WAIT_PULLBACK:
                touched = (
                    owner.direction is Direction.LONG and bar.low <= cloud_upper
                ) or (
                    owner.direction is Direction.SHORT and bar.high >= cloud_lower
                )
                if touched:
                    self._frozen_trigger = (
                        bar.high if owner.direction is Direction.LONG else bar.low
                    )
                    self._trend_trigger_age = 0
                    self._state = OwnerState.WAIT_TRIGGER
                    reason = OwnerReason.PULLBACK_FROZEN
                else:
                    reason = OwnerReason.WAIT_PULLBACK
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=OwnerEvent.NONE,
                    reason=reason,
                )

            if self._state is OwnerState.WAIT_TRIGGER:
                if self._frozen_trigger is None:
                    raise RuntimeError("trend WAIT_TRIGGER is missing frozen trigger")
                self._trend_trigger_age += 1
                if self._trend_trigger_age > TREND_MAX_TRIGGER_BARS:
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.EXPIRED,
                        reason=OwnerReason.TREND_TRIGGER_EXPIRED,
                    )
                eligible = (
                    owner.direction is Direction.LONG
                    and bar.ema5 > bar.ema12
                    and bar.close > self._frozen_trigger
                    and bar.close > cloud_upper
                ) or (
                    owner.direction is Direction.SHORT
                    and bar.ema5 < bar.ema12
                    and bar.close < self._frozen_trigger
                    and bar.close < cloud_lower
                )
                if eligible:
                    remaining = self._remaining_r(owner, bar.close)
                    if remaining is None or remaining < MINIMUM_SPACE_R:
                        return self._finish(
                            bar=bar,
                            event=OwnerEvent.MISSED,
                            reason=OwnerReason.SPACE_LT_1R,
                        )
                    return self._entry(bar, remaining)
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=OwnerEvent.NONE,
                    reason=OwnerReason.WAIT_LATER_TRIGGER,
                )

            if self._state is OwnerState.WAIT_IMMEDIATE_CONFIRM:
                if self._adoption_bar is None:
                    raise RuntimeError("immediate-confirm is missing adoption bar")
                if bar.timestamp_ms != self._adoption_bar.timestamp_ms + THREE_MINUTE_MS:
                    # Normally intercepted by the global continuity gate; keep a
                    # fail-closed assertion at the branch boundary as well.
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.MISSED,
                        reason=OwnerReason.IMMEDIATE_CONFIRM_MISSED,
                    )
                eligible = (
                    owner.direction is Direction.LONG
                    and bar.close > owner.producer_trigger
                    and bar.close <= self._adoption_bar.high
                    and bar.ema5 > bar.ema12
                ) or (
                    owner.direction is Direction.SHORT
                    and bar.close < owner.producer_trigger
                    and bar.close >= self._adoption_bar.low
                    and bar.ema5 < bar.ema12
                )
                if not eligible:
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.MISSED,
                        reason=OwnerReason.IMMEDIATE_CONFIRM_MISSED,
                    )
                remaining = self._remaining_r(owner, bar.close)
                if remaining is None or remaining < MINIMUM_SPACE_R:
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.MISSED,
                        reason=OwnerReason.SPACE_LT_1R,
                    )
                return self._entry(bar, remaining)

            if self._state is OwnerState.WAIT_FRESH_CROSS:
                previous = self._previous_confirmed_close
                if previous is None:
                    raise RuntimeError("fresh-cross is missing previous confirmed close")
                crossed = (
                    owner.direction is Direction.LONG
                    and previous <= owner.producer_trigger
                    and bar.close > owner.producer_trigger
                ) or (
                    owner.direction is Direction.SHORT
                    and previous >= owner.producer_trigger
                    and bar.close < owner.producer_trigger
                )
                self._previous_confirmed_close = bar.close
                if not crossed:
                    return self._snapshot(
                        bar=bar,
                        data_valid=True,
                        event=OwnerEvent.NONE,
                        reason=OwnerReason.WAIT_FIRST_FRESH_CROSS,
                    )
                ema_ok = (
                    owner.direction is Direction.LONG and bar.ema5 > bar.ema12
                ) or (
                    owner.direction is Direction.SHORT and bar.ema5 < bar.ema12
                )
                remaining = self._remaining_r(owner, bar.close)
                if not ema_ok:
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.MISSED,
                        reason=OwnerReason.FIRST_CROSS_MISSED,
                    )
                if remaining is None or remaining < MINIMUM_SPACE_R:
                    return self._finish(
                        bar=bar,
                        event=OwnerEvent.MISSED,
                        reason=OwnerReason.SPACE_LT_1R,
                    )
                return self._entry(bar, remaining)

            raise RuntimeError(f"unhandled owner state: {self._state}")

        # No existing owner: candidate arbitration/adoption only.
        usable: list[AdapterCandidate] = []
        pre_adoption_reason: OwnerReason | None = None
        for candidate in candidates:
            envelope = candidate.envelope
            if (
                self._reset_visible_at_cutoff_ms is not None
                and envelope.visible_at_ms <= self._reset_visible_at_cutoff_ms
            ):
                self._suppress(envelope)
                continue
            if envelope.base_identity in self._collision_tombstones:
                self._suppress(envelope)
                continue
            if envelope.full_identity in self._suppressed:
                continue
            if envelope.visible_at_ms > bar.timestamp_ms:
                continue
            terminal_reason = self._candidate_preterminated(candidate, bar)
            if terminal_reason is not None:
                self._suppress(envelope)
                if (
                    pre_adoption_reason is None
                    or terminal_reason is OwnerReason.PRE_ADOPTION_INVALIDATED
                ):
                    pre_adoption_reason = terminal_reason
                continue
            if bar.timestamp_ms >= envelope.permission_expires_at_ms:
                self._suppress(envelope)
                continue
            if (
                envelope.context_valid_until_ms is not None
                and bar.close_time_ms >= envelope.context_valid_until_ms
            ):
                self._suppress(envelope)
                continue
            usable.append(candidate)

        if not usable:
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=OwnerEvent.NONE,
                reason=(
                    pre_adoption_reason
                    if pre_adoption_reason is not None
                    else OwnerReason.CANDIDATE_SUPPRESSED
                    if candidates
                    else OwnerReason.WAIT_10M
                ),
            )

        directions = {item.envelope.direction for item in usable}
        if len(directions) > 1:
            self._suppress_candidates(usable)
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=OwnerEvent.CONFLICT,
                reason=OwnerReason.OPPOSITE_DIRECTION_CONFLICT,
            )

        winner = min(
            usable,
            key=lambda item: (
                item.envelope.visible_at_ms,
                0
                if item.envelope.lane_id is LaneId.TREND_CONTINUATION
                else 1,
            ),
        )
        for item in usable:
            if item is not winner:
                self._suppress(item.envelope)
        return self._adopt(winner, bar)


class GlobalOwnerHost:
    """Canonical integrated 3m host -> HTF transport -> owner flow.

    The host owns both state machines so a caller cannot observe, reject, consume,
    or clear the raw 10m transport before the confirmed 3m host bar passes the
    Pine-equivalent clock, host, and OHLC gate.  The latest ``gaps_off`` snapshot
    may update on an ineligible bar, but it is staged outside transport audit state
    and offered only on the first later eligible consumer bar.

    Manager, transport, and authority identities are sealed at construction.
    Public ``manager`` and ``transport`` properties are read-only, and every host
    step revalidates all three bindings before staging a raw snapshot or mutating
    either state machine.
    """

    __slots__ = (
        "_manager",
        "_transport",
        "_authority",
        "_latest_raw_snapshot",
        "_raw_snapshot_dirty",
    )

    _SEALED_BINDING_NAMES = frozenset({"_manager", "_transport", "_authority"})

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"manager", "transport"}:
            raise AttributeError(f"{name} is a read-only GlobalOwnerHost binding")
        if name in self._SEALED_BINDING_NAMES and hasattr(self, name):
            raise AttributeError(f"{name} is sealed after GlobalOwnerHost construction")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        manager: OwnerManager | None = None,
        transport: SharedCompletedTenMinuteTransport | None = None,
    ) -> None:
        bound_manager = OwnerManager() if manager is None else manager
        bound_transport = (
            SharedCompletedTenMinuteTransport()
            if transport is None
            else transport
        )
        authority = _HostMutationAuthority(
            host=self, manager=bound_manager, transport=bound_transport
        )
        object.__setattr__(self, "_manager", bound_manager)
        object.__setattr__(self, "_transport", bound_transport)
        object.__setattr__(self, "_authority", authority)
        bound_manager._bind_host_authority(authority)
        bound_transport._bind_authority(authority)
        self._latest_raw_snapshot: CompletedTenMinutePayload | None = None
        self._raw_snapshot_dirty = False

    @property
    def manager(self) -> OwnerManager:
        """Read-only owner manager bound to this host at construction."""

        return self._manager

    @property
    def transport(self) -> SharedCompletedTenMinuteTransport:
        """Read-only completed-10m transport bound to this host at construction."""

        return self._transport

    def _assert_bound_components(self) -> None:
        self._authority.assert_bound_components(
            host=self, manager=self._manager, transport=self._transport
        )

    @property
    def staged_raw_snapshot(self) -> CompletedTenMinutePayload | None:
        """Latest gaps-off snapshot staged outside transport audit state."""

        return self._latest_raw_snapshot

    @property
    def raw_snapshot_dirty(self) -> bool:
        """Whether the staged snapshot still awaits the next eligible poll."""

        return self._raw_snapshot_dirty

    def process_bar(
        self,
        bar: ThreeMinuteBar,
        *,
        completed_ten_minute_payload: CompletedTenMinutePayload | None = None,
    ) -> GlobalOwnerStep:
        # Identity validation is deliberately the first operation.  A replaced
        # manager/transport (including private tampering) cannot stage a payload,
        # mint a permit, or mutate any audit field before this check fails.
        self._assert_bound_components()
        consumer_bar = self._manager.consumer_bar_decision(bar)
        if completed_ten_minute_payload is not None:
            # Staging mirrors the latest gaps_off tuple without touching the
            # transport's pending/observed/consumed/rejected/cutoff audit state.
            self._latest_raw_snapshot = completed_ten_minute_payload
            self._raw_snapshot_dirty = True

        if not consumer_bar.eligible:
            # Do not offer, observe, poll, reject, clear, or advance any raw HTF
            # audit identity or cutoff on an ineligible chart bar.  The manager
            # alone owns this host reset/no-op and Pine-equivalent 3m clock rule.
            observation = self._manager.ingest(bar)
            return GlobalOwnerStep(consumer_bar, None, observation)

        # One host-bound permit authorizes an atomic cutoff-sync + offer + poll,
        # followed by the matching OwnerManager ingest on this same bar.  No
        # caller-visible window exists between eligibility and transport mutation.
        permit = self._authority.issue(
            host=self, bar=bar, decision=consumer_bar
        )
        offered_payload = (
            self._latest_raw_snapshot
            if self._raw_snapshot_dirty and self._latest_raw_snapshot is not None
            else None
        )
        transport_outcome = self._transport._poll_from_host(
            permit=permit,
            confirmed_bar_open_ms=bar.timestamp_ms,
            offered_payload=offered_payload,
            reset_boundary_ms=self._manager.reset_visible_at_cutoff_ms,
        )
        if offered_payload is not None:
            self._raw_snapshot_dirty = False
        observation = self._manager.ingest(
            bar,
            transport_outcome=transport_outcome,
            _host_permit=permit,
        )
        return GlobalOwnerStep(consumer_bar, transport_outcome, observation)


def run_owner(
    rows: Iterable[
        tuple[
            ThreeMinuteBar,
            Sequence[AdapterCandidate],
            Sequence[ProducerTerminal],
        ]
    ],
) -> list[OwnerObservation]:
    engine = OwnerManager()
    return [
        engine.ingest(bar, candidates=candidates, producer_terminals=terminals)
        for bar, candidates, terminals in rows
    ]


__all__ = [
    "AdapterCandidate",
    "CompletedTenMinutePayload",
    "Direction",
    "EXPECTED_SYMBOL",
    "GlobalOwnerHost",
    "GlobalOwnerStep",
    "LaneId",
    "MINIMUM_SPACE_R",
    "OwnerEvent",
    "OwnerManager",
    "OwnerObservation",
    "OwnerReason",
    "OwnerState",
    "PLAN_FINGERPRINT_VERSION",
    "PLAN_NUMBER_SCALE",
    "PlanEnvelope",
    "ProducerTerminal",
    "ProducerTerminalKind",
    "PROTOCOL_VERSION",
    "ReversalAdapter",
    "SCHEMA_VERSION",
    "THREE_MINUTE_MS",
    "ThreeMinuteBar",
    "TransportOutcome",
    "TransportReason",
    "TransportStatus",
    "TrendAdapter",
    "canonical_plan_fingerprint",
    "run_owner",
]
