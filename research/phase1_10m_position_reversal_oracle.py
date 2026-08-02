"""Causal 10-minute POSITION_REVERSAL oracle for prior-published SATy/ATR bands.

This module implements only the first independent producer increment:

    prior-published named band -> confirmed 10m reaction -> immutable opportunity

It does not consume 3-minute data, VIX, divergence, forming MTF values, alerts,
orders, strategies, or profitability assumptions.  A touch is observation only.
An accepted break terminates the episode and cannot be backfilled by a later
reclaim.  The engine is deterministic, confirmed-only, and read-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum, IntEnum
from hashlib import sha256
import json
from math import ceil, floor, isfinite
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Sequence

PROTOCOL_VERSION: Final[str] = "phase1-10m-position-reversal-1.3"
LANE_ID: Final[str] = "POSITION_REVERSAL"
EXPECTED_SYMBOL: Final[str] = "CAPITALCOM:SPX500"
BAR_INTERVAL_MS: Final[int] = 600_000
MAX_REACTION_BARS: Final[int] = 3
MINIMUM_SPACE_R: Final[float] = 1.0
STOP_BUFFER_ATR: Final[float] = 0.002
REARM_ATR: Final[float] = 0.12
OPPORTUNITY_LIFETIME_BARS: Final[int] = 12
DEFAULT_STALE_AFTER_MS: Final[int] = 36 * 60 * 60 * 1000
MINIMUM_TICK: Final[float] = 0.1
EFFECTIVE_NUMBER_SCALE: Final[int] = 10_000_000_000
DAILY_TIMEFRAME: Final[str] = "D"
IDENTITY_ENCODING_VERSION: Final[str] = "CID1"
IDENTITY_COMPONENT_MAX_LENGTH: Final[int] = 64
IDENTITY_ASCII_ALNUM: Final[str] = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)
IDENTITY_COMPONENT_SAFE_CHARS: Final[str] = IDENTITY_ASCII_ALNUM + "._:-"
_IDENTITY_ASCII_ALNUM_SET: Final[frozenset[str]] = frozenset(
    IDENTITY_ASCII_ALNUM
)
_IDENTITY_COMPONENT_SAFE_SET: Final[frozenset[str]] = frozenset(
    IDENTITY_COMPONENT_SAFE_CHARS
)
MARKER_TEXTS: Final[tuple[str, ...]] = (
    "支撑观察",
    "反弹确认",
    "阻力观察",
    "压回确认",
)

CANONICAL_CONTRACT: Final[Mapping[str, object]] = MappingProxyType(
    {
        "protocol_version": PROTOCOL_VERSION,
        "lane_id": LANE_ID,
        "expected_symbol": EXPECTED_SYMBOL,
        "bar_interval_ms": BAR_INTERVAL_MS,
        "max_reaction_bars": MAX_REACTION_BARS,
        "minimum_space_r": MINIMUM_SPACE_R,
        "stop_buffer_atr": STOP_BUFFER_ATR,
        "rearm_atr": REARM_ATR,
        "opportunity_lifetime_bars": OPPORTUNITY_LIFETIME_BARS,
        "default_stale_after_ms": DEFAULT_STALE_AFTER_MS,
        "minimum_tick": MINIMUM_TICK,
        "effective_number_scale": EFFECTIVE_NUMBER_SCALE,
        "band_source_kind_allowlist": ("SATY_ATR_MAP_LEVEL",),
        "atr_source_kind_allowlist": ("PREVIOUS_COMPLETED_DAILY_ATR",),
        "atr_source_timeframe": DAILY_TIMEFRAME,
        "marker_texts": MARKER_TEXTS,
        "source_stability": "PRIOR_PUBLISHED",
        "target_router": "touch-time-freeze-nearest-first-no-skip",
        "target_consumed_scope": "touch-through-reaction-episode-extremes",
        "accepted_break_priority": True,
        "same_bar_touch_reaction": True,
        "same_bar_consumer_entry": False,
        "identity_encoding_version": IDENTITY_ENCODING_VERSION,
        "identity_component_max_length": IDENTITY_COMPONENT_MAX_LENGTH,
        "identity_component_safe_chars": IDENTITY_COMPONENT_SAFE_CHARS,
        "identity_component_grammar": (
            "raw-equals-trim;ascii-only;alnum-boundaries;"
            "interior-[A-Za-z0-9._:-];reject-|@#-and-whitespace"
        ),
        "identity_serialization": "CID1:<source_id>@<source_version>",
        "effective_material_encoding": (
            "CID1-pipe-delimited-fixed-arity-after-safe-identity-validation"
        ),
        "identity_policy": "fail-closed-no-silent-normalization",
        "source_freshness_policy": (
            "absolute-valid-until-plus-v1-fixed-default-ttl-fail-closed"
        ),
        "atr_provenance_policy": "previous-completed-daily-source-bar-metadata",
        "pine_reload_policy": "full-history-recompute-not-append-only",
        "recovery_policy": "first-valid-contiguous-bar-is-eligible",
        "card_default": False,
        "card_position": "bottom_right",
        "same_side_multi_touch_policy": "MULTIPLE_SAME_SIDE_NO_PERMISSION",
    }
)
CANONICAL_CONTRACT_JSON: Final[str] = json.dumps(
    dict(CANONICAL_CONTRACT),
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
CANONICAL_CONTRACT_SHA256: Final[str] = sha256(
    CANONICAL_CONTRACT_JSON.encode("utf-8")
).hexdigest()


class Direction(IntEnum):
    SHORT = -1
    NONE = 0
    LONG = 1


class BandRole(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class Stability(str, Enum):
    PRIOR_PUBLISHED = "PRIOR_PUBLISHED"
    FORMING = "FORMING"
    UNSTABLE = "UNSTABLE"


class SourceKind(str, Enum):
    SATY_ATR_MAP_LEVEL = "SATY_ATR_MAP_LEVEL"
    PREVIOUS_COMPLETED_DAILY_ATR = "PREVIOUS_COMPLETED_DAILY_ATR"


ALLOWED_BAND_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {SourceKind.SATY_ATR_MAP_LEVEL.value}
)
ALLOWED_ATR_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {SourceKind.PREVIOUS_COMPLETED_DAILY_ATR.value}
)


class State(str, Enum):
    WAIT_CLEAR = "WAIT_CLEAR"
    APPROACH = "APPROACH"
    REACTION = "REACTION"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class Event(str, Enum):
    NONE = "NONE"
    SUPPORT_WATCH = "SUPPORT_WATCH"
    RESISTANCE_WATCH = "RESISTANCE_WATCH"
    BOUNCE_CONFIRMED = "BOUNCE_CONFIRMED"
    REJECTION_CONFIRMED = "REJECTION_CONFIRMED"
    ACCEPTED_BREAK = "ACCEPTED_BREAK"
    REACTION_EXPIRED = "REACTION_EXPIRED"
    WAIT_CLEAR_COMPLETED = "WAIT_CLEAR_COMPLETED"
    POSITION_CONFLICT = "POSITION_CONFLICT"
    MULTIPLE_SAME_SIDE = "MULTIPLE_SAME_SIDE"
    DATA_RESET = "DATA_RESET"


class ReasonCode(str, Enum):
    IDLE = "IDLE"
    WATCH_ONLY = "WATCH_ONLY"
    READY = "READY"
    DATA_UNCONFIRMED = "DATA_UNCONFIRMED"
    DATA_SYMBOL_MISMATCH = "DATA_SYMBOL_MISMATCH"
    DATA_TIMEFRAME_MISMATCH = "DATA_TIMEFRAME_MISMATCH"
    DATA_NON_STANDARD = "DATA_NON_STANDARD"
    DATA_INVALID_OHLC = "DATA_INVALID_OHLC"
    DATA_DUPLICATE_IGNORED = "DATA_DUPLICATE_IGNORED"
    DATA_NON_MONOTONIC = "DATA_NON_MONOTONIC"
    DATA_GAP_RESET = "DATA_GAP_RESET"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    SOURCE_IDENTITY_DRIFT = "SOURCE_IDENTITY_DRIFT"
    ATR_NOT_READY = "ATR_NOT_READY"
    ATR_IDENTITY_DRIFT = "ATR_IDENTITY_DRIFT"
    ACCEPTED_BREAK = "ACCEPTED_BREAK"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_CONSUMED = "TARGET_CONSUMED"
    RISK_INVALID = "RISK_INVALID"
    SPACE_LT_1R = "SPACE_LT_1R"
    REACTION_WINDOW_EXPIRED = "REACTION_WINDOW_EXPIRED"
    WAIT_CLEAR_REQUIRED = "WAIT_CLEAR_REQUIRED"
    WAIT_CLEAR_COMPLETED = "WAIT_CLEAR_COMPLETED"
    SIMULTANEOUS_POSITION_CONFLICT = "SIMULTANEOUS_POSITION_CONFLICT"
    MULTIPLE_SAME_SIDE_NO_PERMISSION = "MULTIPLE_SAME_SIDE_NO_PERMISSION"


class SourceRejection(str, Enum):
    DISABLED = "DISABLED"
    IDENTITY_MISSING = "IDENTITY_MISSING"
    IDENTITY_NON_CANONICAL = "IDENTITY_NON_CANONICAL"
    IDENTITY_GRAMMAR_INVALID = "IDENTITY_GRAMMAR_INVALID"
    SOURCE_KIND_NOT_ALLOWED = "SOURCE_KIND_NOT_ALLOWED"
    ROLE_INVALID = "ROLE_INVALID"
    BOUNDS_INVALID = "BOUNDS_INVALID"
    TIME_INVALID = "TIME_INVALID"
    FUTURE_PUBLICATION = "FUTURE_PUBLICATION"
    FUTURE_KNOWN_AT = "FUTURE_KNOWN_AT"
    VALID_UNTIL_INVALID = "VALID_UNTIL_INVALID"
    EXPIRED = "EXPIRED"
    STALE = "STALE"
    FRESHNESS_NON_CANONICAL = "FRESHNESS_NON_CANONICAL"
    STABILITY_NOT_PRIOR_PUBLISHED = "STABILITY_NOT_PRIOR_PUBLISHED"
    ATR_TIMEFRAME_INVALID = "ATR_TIMEFRAME_INVALID"
    ATR_SOURCE_BAR_INVALID = "ATR_SOURCE_BAR_INVALID"
    ATR_SOURCE_BAR_NOT_COMPLETED = "ATR_SOURCE_BAR_NOT_COMPLETED"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"


@dataclass(frozen=True, slots=True)
class ReversalConfig:
    expected_symbol: str = EXPECTED_SYMBOL
    interval_ms: int = BAR_INTERVAL_MS
    max_reaction_bars: int = MAX_REACTION_BARS
    minimum_space_r: float = MINIMUM_SPACE_R
    stop_buffer_atr: float = STOP_BUFFER_ATR
    rearm_atr: float = REARM_ATR
    opportunity_lifetime_bars: int = OPPORTUNITY_LIFETIME_BARS
    minimum_tick: float = MINIMUM_TICK

    def __post_init__(self) -> None:
        if self.expected_symbol != EXPECTED_SYMBOL:
            raise ValueError(
                f"the v1 lane expected_symbol is frozen at {EXPECTED_SYMBOL!r}"
            )
        if self.interval_ms != BAR_INTERVAL_MS:
            raise ValueError("the v1 lane is fixed to native 10-minute bars")
        if self.max_reaction_bars != MAX_REACTION_BARS:
            raise ValueError("MAX_REACTION_BARS is frozen at 3")
        if (
            not isfinite(self.minimum_space_r)
            or self.minimum_space_r != MINIMUM_SPACE_R
        ):
            raise ValueError("the v1 readiness gate is frozen at >= 1.0R")
        if (
            not isfinite(self.stop_buffer_atr)
            or self.stop_buffer_atr != STOP_BUFFER_ATR
        ):
            raise ValueError(f"stop_buffer_atr is frozen at {STOP_BUFFER_ATR}")
        if not isfinite(self.rearm_atr) or self.rearm_atr != REARM_ATR:
            raise ValueError(f"rearm_atr is frozen at {REARM_ATR}")
        if self.opportunity_lifetime_bars != OPPORTUNITY_LIFETIME_BARS:
            raise ValueError(
                "opportunity_lifetime_bars is frozen at "
                f"{OPPORTUNITY_LIFETIME_BARS}"
            )
        if not isfinite(self.minimum_tick) or self.minimum_tick != MINIMUM_TICK:
            raise ValueError(f"minimum_tick is frozen at {MINIMUM_TICK}")


@dataclass(frozen=True, slots=True)
class TenMinuteBar:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    symbol: str = EXPECTED_SYMBOL
    timeframe_ms: int = BAR_INTERVAL_MS
    is_confirmed: bool = True
    is_standard: bool = True

    @property
    def visible_at_ms(self) -> int:
        return self.timestamp_ms + self.timeframe_ms


@dataclass(frozen=True, slots=True)
class NamedBand:
    source_id: str
    source_version: str
    role: BandRole
    lower_bound: float
    upper_bound: float
    published_at_ms: int
    level_known_at_ms: int
    source_kind: SourceKind | str = ""
    valid_until_ms: int = 0
    stability: Stability = Stability.PRIOR_PUBLISHED
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    enabled: bool = True

    @property
    def canonical_source_id(self) -> str:
        return canonical_identity_component(self.source_id)

    @property
    def canonical_source_version(self) -> str:
        return canonical_identity_component(self.source_version)

    @property
    def identity(self) -> str:
        return canonical_source_identity(self.source_id, self.source_version)

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            _source_kind_value(self.source_kind),
            self.role,
            self.lower_bound,
            self.upper_bound,
            self.published_at_ms,
            self.level_known_at_ms,
            self.valid_until_ms,
            self.stability,
            self.stale_after_ms,
        )

    @property
    def effective_fingerprint(self) -> str:
        """Cross-language canonical source material used in effective IDs.

        Pine constructs the same field order with integer-scaled prices.  This
        is deliberately not a cryptographic digest: the material is auditable
        in a generated episode/opportunity ID and changes whenever the accepted
        producer content changes.
        """
        role = self.role.value if isinstance(self.role, BandRole) else str(self.role)
        return "|".join(
            (
                IDENTITY_ENCODING_VERSION,
                "B",
                _source_kind_value(self.source_kind),
                self.identity,
                role,
                str(_scaled_number(self.lower_bound)),
                str(_scaled_number(self.upper_bound)),
                str(self.published_at_ms),
                str(self.level_known_at_ms),
                str(self.valid_until_ms),
            )
        )

    @property
    def effective_identity(self) -> str:
        return f"{self.identity}#{self.effective_fingerprint}"


@dataclass(frozen=True, slots=True)
class PriorAtrContext:
    value: float
    source_id: str
    source_version: str
    published_at_ms: int
    known_at_ms: int
    source_kind: SourceKind | str = ""
    source_timeframe: str = ""
    completed_source_open_ms: int = 0
    completed_source_close_ms: int = 0
    valid_until_ms: int = 0
    stability: Stability = Stability.PRIOR_PUBLISHED
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    enabled: bool = True

    @property
    def canonical_source_id(self) -> str:
        return canonical_identity_component(self.source_id)

    @property
    def canonical_source_version(self) -> str:
        return canonical_identity_component(self.source_version)

    @property
    def identity(self) -> str:
        return canonical_source_identity(self.source_id, self.source_version)

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            _source_kind_value(self.source_kind),
            self.value,
            self.published_at_ms,
            self.known_at_ms,
            self.source_timeframe,
            self.completed_source_open_ms,
            self.completed_source_close_ms,
            self.valid_until_ms,
            self.stability,
            self.stale_after_ms,
        )

    @property
    def effective_fingerprint(self) -> str:
        """Cross-language canonical ATR provenance material."""
        return "|".join(
            (
                IDENTITY_ENCODING_VERSION,
                "A",
                _source_kind_value(self.source_kind),
                self.identity,
                str(_scaled_number(self.value)),
                str(self.published_at_ms),
                str(self.known_at_ms),
                str(self.valid_until_ms),
                self.source_timeframe.strip(),
                str(self.completed_source_open_ms),
                str(self.completed_source_close_ms),
            )
        )

    @property
    def effective_identity(self) -> str:
        return f"{self.identity}#{self.effective_fingerprint}"


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    source_id: str
    source_version: str
    source_kind: str
    role: BandRole
    target_price: float
    source_order: int
    lower_bound: float
    upper_bound: float
    published_at_ms: int
    level_known_at_ms: int
    valid_until_ms: int
    effective_fingerprint: str

    @property
    def target_source(self) -> str:
        return canonical_source_identity(self.source_id, self.source_version)


@dataclass(frozen=True, slots=True)
class OpportunityPayload:
    lane_id: str
    opportunity_id: str
    episode_id: str
    source_id: str
    source_version: str
    source_kind: str
    source_fingerprint: str
    source_valid_until_ms: int
    direction: Direction
    trigger: float
    invalidation: float
    target: float
    target_source: str
    target_source_id: str
    target_source_version: str
    target_source_kind: str
    target_source_fingerprint: str
    target_valid_until_ms: int
    confirmation_time_ms: int
    visible_at_ms: int
    expires_at_ms: int
    prior_atr: float
    atr_source: str
    atr_source_kind: str
    atr_source_fingerprint: str
    atr_valid_until_ms: int
    risk: float
    reward: float
    space_r: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["direction"] = self.direction.name
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class Observation:
    protocol_version: str
    lane_id: str
    bar_time_ms: int
    visible_at_ms: int
    visible: bool
    data_valid: bool
    state: State
    event: Event
    reason_code: ReasonCode
    episode_id: str | None
    source_id: str | None
    source_version: str | None
    source_role: BandRole | None
    frozen_lower: float | None
    frozen_upper: float | None
    frozen_atr: float | None
    episode_low: float | None
    episode_high: float | None
    reaction_bars_seen: int
    watch_registered: bool
    terminal_registered: bool
    clear_required: bool
    marker_text: str | None
    marker_price: float | None
    target_candidate: TargetCandidate | None
    opportunity: OpportunityPayload | None
    source_rejections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ValidatedSources:
    bands: tuple[tuple[int, NamedBand], ...]
    rejections: tuple[str, ...]
    fatal_reason: ReasonCode | None


def _valid_ohlc(bar: TenMinuteBar) -> bool:
    values = (bar.open, bar.high, bar.low, bar.close)
    return all(isfinite(value) for value in values) and not (
        bar.high < bar.low
        or bar.high < max(bar.open, bar.close)
        or bar.low > min(bar.open, bar.close)
    )


def _identity_component_rejection(value: object) -> SourceRejection | None:
    """Return the shared Python/Pine fail-closed identity verdict.

    A canonical component is 1..64 ASCII characters, starts and ends with an
    ASCII alphanumeric, contains only ``[A-Za-z0-9._:-]``, and is already equal
    to its trimmed form.  In particular, whitespace and the outward/material
    delimiters ``|``, ``@`` and ``#`` are never accepted as data.
    """

    if not isinstance(value, str) or not value or not value.strip():
        return SourceRejection.IDENTITY_MISSING
    if value != value.strip():
        return SourceRejection.IDENTITY_NON_CANONICAL
    if not (1 <= len(value) <= IDENTITY_COMPONENT_MAX_LENGTH):
        return SourceRejection.IDENTITY_GRAMMAR_INVALID
    if (
        value[0] not in _IDENTITY_ASCII_ALNUM_SET
        or value[-1] not in _IDENTITY_ASCII_ALNUM_SET
        or any(character not in _IDENTITY_COMPONENT_SAFE_SET for character in value)
    ):
        return SourceRejection.IDENTITY_GRAMMAR_INVALID
    return None


def _identity_rejection(
    source_id: object, source_version: object
) -> SourceRejection | None:
    for component in (source_id, source_version):
        rejection = _identity_component_rejection(component)
        if rejection is not None:
            return rejection
    return None


def canonical_identity_component(value: str) -> str:
    """Return one unchanged canonical component or raise on any normalization."""

    rejection = _identity_component_rejection(value)
    if rejection is not None:
        raise ValueError(f"invalid canonical identity component: {rejection.value}")
    return value


def canonical_source_identity(source_id: str, source_version: str) -> str:
    """Serialize one unambiguous, protocol-versioned producer identity."""

    return (
        f"{IDENTITY_ENCODING_VERSION}:"
        f"{canonical_identity_component(source_id)}@"
        f"{canonical_identity_component(source_version)}"
    )


def _identity_audit_label(source_id: object, source_version: object) -> str:
    """Use canonical identity when valid, otherwise expose quoted raw inputs."""

    if isinstance(source_id, str) and isinstance(source_version, str):
        try:
            return canonical_source_identity(source_id, source_version)
        except ValueError:
            pass
    return f"RAW_ID({source_id!r},{source_version!r})"


def _source_kind_value(value: SourceKind | str) -> str:
    return value.value if isinstance(value, SourceKind) else str(value).strip()


def _scaled_number(value: float) -> int:
    """Round a finite number to the canonical 1e-10 integer representation."""
    if not isfinite(value):
        raise ValueError("effective fingerprint values must be finite")
    scaled = value * EFFECTIVE_NUMBER_SCALE
    return floor(scaled + 0.5) if scaled >= 0 else ceil(scaled - 0.5)


def _time_valid(value: int) -> bool:
    return isinstance(value, int) and value > 0


def _band_rejection(band: NamedBand, bar_open_ms: int) -> SourceRejection | None:
    if not band.enabled:
        return SourceRejection.DISABLED
    identity_rejection = _identity_rejection(band.source_id, band.source_version)
    if identity_rejection is not None:
        return identity_rejection
    if _source_kind_value(band.source_kind) not in ALLOWED_BAND_SOURCE_KINDS:
        return SourceRejection.SOURCE_KIND_NOT_ALLOWED
    if not isinstance(band.role, BandRole):
        return SourceRejection.ROLE_INVALID
    if not (
        isfinite(band.lower_bound)
        and isfinite(band.upper_bound)
        and band.lower_bound <= band.upper_bound
    ):
        return SourceRejection.BOUNDS_INVALID
    if not (
        _time_valid(band.published_at_ms)
        and _time_valid(band.level_known_at_ms)
        and _time_valid(band.stale_after_ms)
    ):
        return SourceRejection.TIME_INVALID
    if not _time_valid(band.valid_until_ms) or (
        band.published_at_ms >= band.valid_until_ms
        or band.level_known_at_ms >= band.valid_until_ms
    ):
        return SourceRejection.VALID_UNTIL_INVALID
    if band.stale_after_ms != DEFAULT_STALE_AFTER_MS:
        return SourceRejection.FRESHNESS_NON_CANONICAL
    if band.published_at_ms > bar_open_ms:
        return SourceRejection.FUTURE_PUBLICATION
    if band.level_known_at_ms > bar_open_ms:
        return SourceRejection.FUTURE_KNOWN_AT
    if bar_open_ms >= band.valid_until_ms:
        return SourceRejection.EXPIRED
    usable_at = max(band.published_at_ms, band.level_known_at_ms)
    if bar_open_ms - usable_at > band.stale_after_ms:
        return SourceRejection.STALE
    if band.stability is not Stability.PRIOR_PUBLISHED:
        return SourceRejection.STABILITY_NOT_PRIOR_PUBLISHED
    return None


def _atr_rejection(atr: PriorAtrContext, bar_open_ms: int) -> SourceRejection | None:
    if not atr.enabled:
        return SourceRejection.DISABLED
    identity_rejection = _identity_rejection(atr.source_id, atr.source_version)
    if identity_rejection is not None:
        return identity_rejection
    if _source_kind_value(atr.source_kind) not in ALLOWED_ATR_SOURCE_KINDS:
        return SourceRejection.SOURCE_KIND_NOT_ALLOWED
    if not isfinite(atr.value) or atr.value <= 0:
        return SourceRejection.BOUNDS_INVALID
    if atr.source_timeframe.strip() != DAILY_TIMEFRAME:
        return SourceRejection.ATR_TIMEFRAME_INVALID
    if not (
        _time_valid(atr.published_at_ms)
        and _time_valid(atr.known_at_ms)
        and _time_valid(atr.completed_source_open_ms)
        and _time_valid(atr.completed_source_close_ms)
        and _time_valid(atr.valid_until_ms)
        and _time_valid(atr.stale_after_ms)
    ):
        return SourceRejection.TIME_INVALID
    if atr.completed_source_open_ms >= atr.completed_source_close_ms:
        return SourceRejection.ATR_SOURCE_BAR_INVALID
    if atr.completed_source_close_ms > atr.known_at_ms:
        return SourceRejection.ATR_SOURCE_BAR_NOT_COMPLETED
    if (
        atr.published_at_ms >= atr.valid_until_ms
        or atr.known_at_ms >= atr.valid_until_ms
    ):
        return SourceRejection.VALID_UNTIL_INVALID
    if atr.stale_after_ms != DEFAULT_STALE_AFTER_MS:
        return SourceRejection.FRESHNESS_NON_CANONICAL
    if atr.published_at_ms > bar_open_ms:
        return SourceRejection.FUTURE_PUBLICATION
    if atr.known_at_ms > bar_open_ms:
        return SourceRejection.FUTURE_KNOWN_AT
    if bar_open_ms >= atr.valid_until_ms:
        return SourceRejection.EXPIRED
    usable_at = max(atr.published_at_ms, atr.known_at_ms)
    if bar_open_ms - usable_at > atr.stale_after_ms:
        return SourceRejection.STALE
    if atr.stability is not Stability.PRIOR_PUBLISHED:
        return SourceRejection.STABILITY_NOT_PRIOR_PUBLISHED
    return None


def _direction_for_role(role: BandRole) -> Direction:
    return Direction.LONG if role is BandRole.SUPPORT else Direction.SHORT


def _marker_for_watch(role: BandRole) -> str:
    return "支撑观察" if role is BandRole.SUPPORT else "阻力观察"


def _marker_for_reaction(role: BandRole) -> str:
    return "反弹确认" if role is BandRole.SUPPORT else "压回确认"


def _watch_event(role: BandRole) -> Event:
    return (
        Event.SUPPORT_WATCH
        if role is BandRole.SUPPORT
        else Event.RESISTANCE_WATCH
    )


def _reaction_event(role: BandRole) -> Event:
    return (
        Event.BOUNCE_CONFIRMED
        if role is BandRole.SUPPORT
        else Event.REJECTION_CONFIRMED
    )


def canonical_episode_id(
    direction: Direction,
    source_id: str,
    source_version: str,
    source_fingerprint: str,
    timestamp_ms: int,
) -> str:
    if direction not in (Direction.LONG, Direction.SHORT):
        raise ValueError("episode direction must be LONG or SHORT")
    if not source_fingerprint:
        raise ValueError("episode source fingerprint must be non-empty")
    side = "L" if direction is Direction.LONG else "S"
    source_identity = canonical_source_identity(source_id, source_version)
    return (
        f"PR-EP-{side}-{source_identity}"
        f"#{source_fingerprint}-{timestamp_ms}"
    )


def canonical_opportunity_id(
    direction: Direction,
    source_id: str,
    source_version: str,
    source_fingerprint: str,
    target_fingerprint: str,
    atr_fingerprint: str,
    timestamp_ms: int,
) -> str:
    if direction not in (Direction.LONG, Direction.SHORT):
        raise ValueError("opportunity direction must be LONG or SHORT")
    if not all((source_fingerprint, target_fingerprint, atr_fingerprint)):
        raise ValueError("opportunity fingerprints must be non-empty")
    side = "L" if direction is Direction.LONG else "S"
    source_identity = canonical_source_identity(source_id, source_version)
    return (
        f"PR-OP-{side}-{source_identity}"
        f"#{source_fingerprint}|{target_fingerprint}|{atr_fingerprint}"
        f"-{timestamp_ms}"
    )


def _conflict_episode_id(
    timestamp_ms: int,
    source_fingerprints: Iterable[str],
    atr_fingerprint: str,
    *,
    same_side: bool,
) -> str:
    """Return the cross-language effective identity for a multi-touch terminal.

    Even though this branch never grants permission, its episode identity must
    still change when any touched producer or the frozen ATR context changes.
    Pine emits the same ordered, auditable material.
    """
    material = "|".join(source_fingerprints)
    if not material or not atr_fingerprint:
        raise ValueError("multi-touch effective material must be non-empty")
    prefix = "PR-MULTIPLE-SAME-SIDE" if same_side else "PR-CONFLICT"
    return f"{prefix}-{timestamp_ms}#{material}|{atr_fingerprint}"


class PositionReversalEngine:
    """One causal position-reversal episode at a time.

    Terminal states are visible on their event bar.  Starting with the next
    confirmed bar, the detector is locked in WAIT_CLEAR until one complete bar
    clears the old band on its original reaction side by at least 0.12 ATR.
    That clear bar never starts a new episode.
    """

    def __init__(self, config: ReversalConfig | None = None) -> None:
        self.config = config or ReversalConfig()
        self._last_timestamp_ms: int | None = None
        self._state = State.WAIT_CLEAR
        self._needs_clear = False
        self._source_registry: dict[str, tuple[object, ...]] = {}
        self._atr_registry: dict[str, tuple[object, ...]] = {}
        self._opportunities: list[OpportunityPayload] = []
        self._clear_episode_fields()

    @property
    def state(self) -> State:
        return self._state

    @property
    def opportunities(self) -> tuple[OpportunityPayload, ...]:
        return tuple(self._opportunities)

    @property
    def latest_opportunity(self) -> OpportunityPayload | None:
        return self._opportunities[-1] if self._opportunities else None

    def _clear_episode_fields(self) -> None:
        self._episode_id: str | None = None
        self._source_id: str | None = None
        self._source_version: str | None = None
        self._source_kind: str | None = None
        self._source_fingerprint: str | None = None
        self._source_valid_until_ms: int | None = None
        self._source_role: BandRole | None = None
        self._frozen_lower: float | None = None
        self._frozen_upper: float | None = None
        self._frozen_atr: float | None = None
        self._atr_source: str | None = None
        self._atr_source_kind: str | None = None
        self._atr_fingerprint: str | None = None
        self._atr_valid_until_ms: int | None = None
        self._episode_low: float | None = None
        self._episode_high: float | None = None
        self._reaction_bars_seen = 0
        self._watch_registered = False
        self._terminal_registered = False
        self._frozen_target: TargetCandidate | None = None
        self._current_opportunity: OpportunityPayload | None = None

    def _reset_runtime(self) -> None:
        self._state = State.WAIT_CLEAR
        self._needs_clear = False
        self._clear_episode_fields()

    def _snapshot(
        self,
        bar: TenMinuteBar,
        *,
        data_valid: bool,
        event: Event,
        reason: ReasonCode,
        marker_text: str | None = None,
        marker_price: float | None = None,
        rejections: Sequence[str] = (),
        state_override: State | None = None,
    ) -> Observation:
        return Observation(
            protocol_version=PROTOCOL_VERSION,
            lane_id=LANE_ID,
            bar_time_ms=bar.timestamp_ms,
            visible_at_ms=bar.visible_at_ms,
            visible=bar.is_confirmed and data_valid,
            data_valid=data_valid,
            state=self._state if state_override is None else state_override,
            event=event,
            reason_code=reason,
            episode_id=self._episode_id,
            source_id=self._source_id,
            source_version=self._source_version,
            source_role=self._source_role,
            frozen_lower=self._frozen_lower,
            frozen_upper=self._frozen_upper,
            frozen_atr=self._frozen_atr,
            episode_low=self._episode_low,
            episode_high=self._episode_high,
            reaction_bars_seen=self._reaction_bars_seen,
            watch_registered=self._watch_registered,
            terminal_registered=self._terminal_registered,
            clear_required=self._needs_clear,
            marker_text=marker_text,
            marker_price=marker_price,
            target_candidate=self._frozen_target,
            opportunity=self._current_opportunity,
            source_rejections=tuple(rejections),
        )

    def _host_reason(self, bar: TenMinuteBar) -> ReasonCode | None:
        if bar.symbol != self.config.expected_symbol:
            return ReasonCode.DATA_SYMBOL_MISMATCH
        if bar.timeframe_ms != self.config.interval_ms:
            return ReasonCode.DATA_TIMEFRAME_MISMATCH
        if not bar.is_standard:
            return ReasonCode.DATA_NON_STANDARD
        if not _valid_ohlc(bar):
            return ReasonCode.DATA_INVALID_OHLC
        return None

    def _validate_sources(
        self, bar: TenMinuteBar, bands: Sequence[NamedBand]
    ) -> _ValidatedSources:
        valid: list[tuple[int, NamedBand]] = []
        rejections: list[str] = []
        seen: dict[str, tuple[object, ...]] = {}
        fatal: ReasonCode | None = None
        for order, band in enumerate(bands):
            rejection = _band_rejection(band, bar.timestamp_ms)
            if rejection is not None:
                rejections.append(
                    f"{_identity_audit_label(band.source_id, band.source_version)}:"
                    f"{rejection.value}"
                )
                if rejection in {
                    SourceRejection.IDENTITY_MISSING,
                    SourceRejection.IDENTITY_NON_CANONICAL,
                    SourceRejection.IDENTITY_GRAMMAR_INVALID,
                    SourceRejection.SOURCE_KIND_NOT_ALLOWED,
                    SourceRejection.VALID_UNTIL_INVALID,
                    SourceRejection.EXPIRED,
                }:
                    fatal = ReasonCode.SOURCE_NOT_READY
                continue
            identity = band.identity
            prior_in_call = seen.get(identity)
            if prior_in_call is not None:
                rejections.append(
                    f"{identity}:{SourceRejection.DUPLICATE_IDENTITY.value}"
                )
                fatal = ReasonCode.SOURCE_IDENTITY_DRIFT
                continue
            seen[identity] = band.fingerprint
            prior = self._source_registry.get(identity)
            if prior is not None and prior != band.fingerprint:
                rejections.append(f"{identity}:IDENTITY_DRIFT")
                fatal = ReasonCode.SOURCE_IDENTITY_DRIFT
                continue
            self._source_registry[identity] = band.fingerprint
            valid.append((order, band))
        return _ValidatedSources(tuple(valid), tuple(rejections), fatal)

    def _validate_atr(
        self, bar: TenMinuteBar, atr: PriorAtrContext
    ) -> tuple[ReasonCode | None, tuple[str, ...]]:
        rejection = _atr_rejection(atr, bar.timestamp_ms)
        if rejection is not None:
            return ReasonCode.ATR_NOT_READY, (
                f"{_identity_audit_label(atr.source_id, atr.source_version)}:"
                f"{rejection.value}",
            )
        prior = self._atr_registry.get(atr.identity)
        if prior is not None and prior != atr.fingerprint:
            return ReasonCode.ATR_IDENTITY_DRIFT, (f"{atr.identity}:IDENTITY_DRIFT",)
        self._atr_registry[atr.identity] = atr.fingerprint
        return None, ()

    @staticmethod
    def _touched(bar: TenMinuteBar, band: NamedBand) -> bool:
        if band.role is BandRole.SUPPORT:
            return bar.low <= band.upper_bound
        return bar.high >= band.lower_bound

    @staticmethod
    def _accepted_break(bar: TenMinuteBar, role: BandRole, lower: float, upper: float) -> bool:
        if role is BandRole.SUPPORT:
            return bar.close < lower
        return bar.close > upper

    @staticmethod
    def _reaction_confirmed(
        bar: TenMinuteBar, role: BandRole, lower: float, upper: float
    ) -> bool:
        if role is BandRole.SUPPORT:
            return bar.close > upper
        return bar.close < lower

    def _freeze_nearest_target(
        self,
        *,
        touch_bar: TenMinuteBar,
        reaction_band: NamedBand,
        valid_bands: Sequence[tuple[int, NamedBand]],
    ) -> TargetCandidate | None:
        direction = _direction_for_role(reaction_band.role)
        candidates: list[TargetCandidate] = []
        for order, band in valid_bands:
            if band.role is reaction_band.role:
                continue
            if direction is Direction.LONG:
                target_price = band.lower_bound
                ahead = target_price > touch_bar.high
            else:
                target_price = band.upper_bound
                ahead = target_price < touch_bar.low
            if not ahead:
                continue
            candidates.append(
                TargetCandidate(
                    source_id=band.canonical_source_id,
                    source_version=band.canonical_source_version,
                    source_kind=_source_kind_value(band.source_kind),
                    role=band.role,
                    target_price=target_price,
                    source_order=order,
                    lower_bound=band.lower_bound,
                    upper_bound=band.upper_bound,
                    published_at_ms=band.published_at_ms,
                    level_known_at_ms=band.level_known_at_ms,
                    valid_until_ms=band.valid_until_ms,
                    effective_fingerprint=band.effective_fingerprint,
                )
            )
        if not candidates:
            return None
        if direction is Direction.LONG:
            candidates.sort(key=lambda item: (item.target_price, item.source_order))
        else:
            candidates.sort(key=lambda item: (-item.target_price, item.source_order))
        return candidates[0]

    def _start_episode(
        self,
        bar: TenMinuteBar,
        band: NamedBand,
        atr: PriorAtrContext,
        valid_bands: Sequence[tuple[int, NamedBand]],
    ) -> None:
        self._clear_episode_fields()
        direction = _direction_for_role(band.role)
        self._episode_id = canonical_episode_id(
            direction,
            band.canonical_source_id,
            band.canonical_source_version,
            band.effective_fingerprint,
            bar.timestamp_ms,
        )
        self._source_id = band.canonical_source_id
        self._source_version = band.canonical_source_version
        self._source_kind = _source_kind_value(band.source_kind)
        self._source_fingerprint = band.effective_fingerprint
        self._source_valid_until_ms = band.valid_until_ms
        self._source_role = band.role
        self._frozen_lower = band.lower_bound
        self._frozen_upper = band.upper_bound
        self._frozen_atr = atr.value
        self._atr_source = atr.identity
        self._atr_source_kind = _source_kind_value(atr.source_kind)
        self._atr_fingerprint = atr.effective_fingerprint
        self._atr_valid_until_ms = atr.valid_until_ms
        self._episode_low = bar.low
        self._episode_high = bar.high
        self._reaction_bars_seen = 1
        self._watch_registered = True
        self._terminal_registered = False
        self._frozen_target = self._freeze_nearest_target(
            touch_bar=bar,
            reaction_band=band,
            valid_bands=valid_bands,
        )
        self._state = State.APPROACH

    def _set_clear_lock(self) -> None:
        self._needs_clear = True

    def _full_clear(self, bar: TenMinuteBar) -> bool:
        if (
            self._source_role is None
            or self._frozen_lower is None
            or self._frozen_upper is None
            or self._frozen_atr is None
        ):
            return False
        distance = self.config.rearm_atr * self._frozen_atr
        if self._source_role is BandRole.SUPPORT:
            return (
                bar.low > self._frozen_upper
                and bar.close >= self._frozen_upper + distance
            )
        return (
            bar.high < self._frozen_lower
            and bar.close <= self._frozen_lower - distance
        )

    def _conflict_clear(self, bar: TenMinuteBar) -> bool:
        if (
            self._frozen_lower is None
            or self._frozen_upper is None
            or self._frozen_atr is None
        ):
            return False
        distance = self.config.rearm_atr * self._frozen_atr
        return (
            bar.low > self._frozen_upper
            and bar.close >= self._frozen_upper + distance
        ) or (
            bar.high < self._frozen_lower
            and bar.close <= self._frozen_lower - distance
        )

    def _update_episode_extremes(self, bar: TenMinuteBar) -> None:
        self._episode_low = (
            bar.low if self._episode_low is None else min(self._episode_low, bar.low)
        )
        self._episode_high = (
            bar.high
            if self._episode_high is None
            else max(self._episode_high, bar.high)
        )

    def _terminal(
        self,
        bar: TenMinuteBar,
        *,
        state: State,
        event: Event,
        reason: ReasonCode,
        marker_text: str | None = None,
        marker_price: float | None = None,
        opportunity: OpportunityPayload | None = None,
        rejections: Sequence[str] = (),
    ) -> Observation:
        self._state = state
        self._terminal_registered = True
        self._current_opportunity = opportunity
        self._set_clear_lock()
        return self._snapshot(
            bar,
            data_valid=True,
            event=event,
            reason=reason,
            marker_text=marker_text,
            marker_price=marker_price,
            rejections=rejections,
        )

    def _finish_reaction(self, bar: TenMinuteBar) -> Observation:
        if (
            self._source_role is None
            or self._source_id is None
            or self._source_version is None
            or self._source_kind is None
            or self._source_fingerprint is None
            or self._source_valid_until_ms is None
            or self._episode_id is None
            or self._frozen_lower is None
            or self._frozen_upper is None
            or self._frozen_atr is None
            or self._episode_low is None
            or self._episode_high is None
            or self._atr_source is None
            or self._atr_source_kind is None
            or self._atr_fingerprint is None
            or self._atr_valid_until_ms is None
        ):
            raise RuntimeError("reaction is missing frozen episode fields")

        # The fixed path includes REACTION, but target/risk gating is completed
        # atomically on this same confirmed 10m close.  The outward snapshot is
        # therefore READY or FAILED, never a second mutable reaction state.
        self._state = State.REACTION
        role = self._source_role
        direction = _direction_for_role(role)
        event = _reaction_event(role)
        marker_text = _marker_for_reaction(role)
        marker_price = bar.close
        trigger = bar.high if direction is Direction.LONG else bar.low
        buffer = max(
            2.0 * self.config.minimum_tick,
            self.config.stop_buffer_atr * self._frozen_atr,
        )
        invalidation = (
            self._episode_low - buffer
            if direction is Direction.LONG
            else self._episode_high + buffer
        )
        risk = (
            trigger - invalidation
            if direction is Direction.LONG
            else invalidation - trigger
        )
        target_candidate = self._frozen_target
        if target_candidate is None:
            return self._terminal(
                bar,
                state=State.FAILED,
                event=event,
                reason=ReasonCode.TARGET_MISSING,
                marker_text=marker_text,
                marker_price=marker_price,
            )

        target = target_candidate.target_price
        # Consumption is episode-wide, not confirmation-bar-only.  A target
        # touched on any bar from the initial location touch through the
        # confirmed reaction is already spent and cannot authorize READY later.
        consumed = (
            direction is Direction.LONG and self._episode_high >= target
        ) or (
            direction is Direction.SHORT and self._episode_low <= target
        )
        if consumed:
            return self._terminal(
                bar,
                state=State.FAILED,
                event=event,
                reason=ReasonCode.TARGET_CONSUMED,
                marker_text=marker_text,
                marker_price=marker_price,
            )
        reward = (
            target - trigger
            if direction is Direction.LONG
            else trigger - target
        )
        if not (isfinite(risk) and isfinite(reward)) or risk <= 0 or reward <= 0:
            return self._terminal(
                bar,
                state=State.FAILED,
                event=event,
                reason=ReasonCode.RISK_INVALID,
                marker_text=marker_text,
                marker_price=marker_price,
            )
        space_r = reward / risk
        if space_r < self.config.minimum_space_r:
            return self._terminal(
                bar,
                state=State.FAILED,
                event=event,
                reason=ReasonCode.SPACE_LT_1R,
                marker_text=marker_text,
                marker_price=marker_price,
            )

        opportunity_id = canonical_opportunity_id(
            direction,
            self._source_id,
            self._source_version,
            self._source_fingerprint,
            target_candidate.effective_fingerprint,
            self._atr_fingerprint,
            bar.timestamp_ms,
        )
        visible_at_ms = bar.visible_at_ms
        opportunity = OpportunityPayload(
            lane_id=LANE_ID,
            opportunity_id=opportunity_id,
            episode_id=self._episode_id,
            source_id=self._source_id,
            source_version=self._source_version,
            source_kind=self._source_kind,
            source_fingerprint=self._source_fingerprint,
            source_valid_until_ms=self._source_valid_until_ms,
            direction=direction,
            trigger=trigger,
            invalidation=invalidation,
            target=target,
            target_source=target_candidate.target_source,
            target_source_id=target_candidate.source_id,
            target_source_version=target_candidate.source_version,
            target_source_kind=target_candidate.source_kind,
            target_source_fingerprint=target_candidate.effective_fingerprint,
            target_valid_until_ms=target_candidate.valid_until_ms,
            confirmation_time_ms=bar.timestamp_ms,
            visible_at_ms=visible_at_ms,
            expires_at_ms=(
                visible_at_ms
                + self.config.opportunity_lifetime_bars * self.config.interval_ms
            ),
            prior_atr=self._frozen_atr,
            atr_source=self._atr_source,
            atr_source_kind=self._atr_source_kind,
            atr_source_fingerprint=self._atr_fingerprint,
            atr_valid_until_ms=self._atr_valid_until_ms,
            risk=risk,
            reward=reward,
            space_r=space_r,
        )
        self._opportunities.append(opportunity)
        return self._terminal(
            bar,
            state=State.READY,
            event=event,
            reason=ReasonCode.READY,
            marker_text=marker_text,
            marker_price=marker_price,
            opportunity=opportunity,
        )

    def _process_approach(self, bar: TenMinuteBar) -> Observation:
        if (
            self._source_role is None
            or self._frozen_lower is None
            or self._frozen_upper is None
        ):
            raise RuntimeError("APPROACH is missing a frozen source")
        self._reaction_bars_seen += 1
        self._update_episode_extremes(bar)
        if self._accepted_break(
            bar, self._source_role, self._frozen_lower, self._frozen_upper
        ):
            return self._terminal(
                bar,
                state=State.FAILED,
                event=Event.ACCEPTED_BREAK,
                reason=ReasonCode.ACCEPTED_BREAK,
            )
        if self._reaction_confirmed(
            bar, self._source_role, self._frozen_lower, self._frozen_upper
        ):
            return self._finish_reaction(bar)
        if self._reaction_bars_seen >= self.config.max_reaction_bars:
            return self._terminal(
                bar,
                state=State.EXPIRED,
                event=Event.REACTION_EXPIRED,
                reason=ReasonCode.REACTION_WINDOW_EXPIRED,
            )
        return self._snapshot(
            bar,
            data_valid=True,
            event=Event.NONE,
            reason=ReasonCode.WATCH_ONLY,
        )

    def ingest(
        self,
        bar: TenMinuteBar,
        bands: Sequence[NamedBand],
        atr: PriorAtrContext,
    ) -> Observation:
        host_reason = self._host_reason(bar)
        if host_reason is not None:
            if bar.is_confirmed:
                self._reset_runtime()
                self._last_timestamp_ms = None
            return self._snapshot(
                bar,
                data_valid=False,
                event=Event.DATA_RESET if bar.is_confirmed else Event.NONE,
                reason=host_reason,
                state_override=State.DISABLED,
            )

        if not bar.is_confirmed:
            return self._snapshot(
                bar,
                data_valid=False,
                event=Event.NONE,
                reason=ReasonCode.DATA_UNCONFIRMED,
            )

        if self._last_timestamp_ms is not None:
            if bar.timestamp_ms == self._last_timestamp_ms:
                return self._snapshot(
                    bar,
                    data_valid=False,
                    event=Event.NONE,
                    reason=ReasonCode.DATA_DUPLICATE_IGNORED,
                )
            if bar.timestamp_ms < self._last_timestamp_ms:
                self._reset_runtime()
                self._last_timestamp_ms = None
                return self._snapshot(
                    bar,
                    data_valid=False,
                    event=Event.DATA_RESET,
                    reason=ReasonCode.DATA_NON_MONOTONIC,
                    state_override=State.DISABLED,
                )
            if bar.timestamp_ms - self._last_timestamp_ms != self.config.interval_ms:
                self._reset_runtime()
                self._last_timestamp_ms = bar.timestamp_ms
                return self._snapshot(
                    bar,
                    data_valid=False,
                    event=Event.DATA_RESET,
                    reason=ReasonCode.DATA_GAP_RESET,
                    state_override=State.DISABLED,
                )

        self._last_timestamp_ms = bar.timestamp_ms
        validated = self._validate_sources(bar, bands)
        atr_reason, atr_rejections = self._validate_atr(bar, atr)
        rejections = validated.rejections + atr_rejections
        fatal_reason = validated.fatal_reason or atr_reason
        if fatal_reason is not None or not validated.bands:
            self._reset_runtime()
            return self._snapshot(
                bar,
                data_valid=False,
                event=Event.DATA_RESET,
                reason=fatal_reason or ReasonCode.SOURCE_NOT_READY,
                rejections=rejections,
                state_override=State.DISABLED,
            )

        # A terminal event is outward on its own bar.  Only a strictly later
        # confirmed bar enters the WAIT_CLEAR lock.
        if self._state in (State.READY, State.FAILED, State.EXPIRED):
            self._state = State.WAIT_CLEAR
            self._current_opportunity = None

        if self._needs_clear:
            clear = (
                self._conflict_clear(bar)
                if self._source_role is None
                else self._full_clear(bar)
            )
            if not clear:
                return self._snapshot(
                    bar,
                    data_valid=True,
                    event=Event.NONE,
                    reason=ReasonCode.WAIT_CLEAR_REQUIRED,
                    rejections=rejections,
                )
            self._needs_clear = False
            snapshot = self._snapshot(
                bar,
                data_valid=True,
                event=Event.WAIT_CLEAR_COMPLETED,
                reason=ReasonCode.WAIT_CLEAR_COMPLETED,
                rejections=rejections,
            )
            self._clear_episode_fields()
            self._state = State.WAIT_CLEAR
            return snapshot

        if self._state is State.APPROACH:
            current_identities = {
                band.effective_identity for _, band in validated.bands
            }
            active_identity = (
                f"{canonical_source_identity(self._source_id, self._source_version)}"
                f"#{self._source_fingerprint}"
                if self._source_id is not None
                and self._source_version is not None
                and self._source_fingerprint is not None
                else None
            )
            target_identity = (
                (
                    f"{self._frozen_target.target_source}"
                    f"#{self._frozen_target.effective_fingerprint}"
                )
                if self._frozen_target is not None
                else None
            )
            source_missing = (
                active_identity is None
                or active_identity not in current_identities
                or (
                    target_identity is not None
                    and target_identity not in current_identities
                )
            )
            atr_changed = (
                self._atr_source is None
                or atr.identity != self._atr_source
                or self._atr_fingerprint is None
                or atr.effective_fingerprint != self._atr_fingerprint
                or self._frozen_atr is None
                or atr.value != self._frozen_atr
            )
            if source_missing or atr_changed:
                self._reset_runtime()
                return self._snapshot(
                    bar,
                    data_valid=False,
                    event=Event.DATA_RESET,
                    reason=(
                        ReasonCode.ATR_NOT_READY
                        if atr_changed
                        else ReasonCode.SOURCE_NOT_READY
                    ),
                    rejections=rejections,
                    state_override=State.DISABLED,
                )
            return self._process_approach(bar)

        if self._state is not State.WAIT_CLEAR:
            raise AssertionError(f"unhandled state {self._state}")

        touched = [
            (order, band)
            for order, band in validated.bands
            if self._touched(bar, band)
        ]
        if not touched:
            return self._snapshot(
                bar,
                data_valid=True,
                event=Event.NONE,
                reason=ReasonCode.IDLE,
                rejections=rejections,
            )

        if len(touched) != 1:
            self._clear_episode_fields()
            touched_roles = {item.role for _, item in touched}
            same_side = len(touched_roles) == 1
            if same_side:
                self._source_role = next(iter(touched_roles))
            self._frozen_lower = min(item.lower_bound for _, item in touched)
            self._frozen_upper = max(item.upper_bound for _, item in touched)
            self._frozen_atr = atr.value
            self._episode_low = bar.low
            self._episode_high = bar.high
            self._episode_id = _conflict_episode_id(
                bar.timestamp_ms,
                (item.effective_fingerprint for _, item in touched),
                atr.effective_fingerprint,
                same_side=same_side,
            )
            self._terminal_registered = True
            self._state = State.FAILED
            self._set_clear_lock()
            return self._snapshot(
                bar,
                data_valid=True,
                event=(
                    Event.MULTIPLE_SAME_SIDE
                    if same_side
                    else Event.POSITION_CONFLICT
                ),
                reason=(
                    ReasonCode.MULTIPLE_SAME_SIDE_NO_PERMISSION
                    if same_side
                    else ReasonCode.SIMULTANEOUS_POSITION_CONFLICT
                ),
                rejections=rejections,
            )

        _, selected = touched[0]
        self._start_episode(bar, selected, atr, validated.bands)
        if self._accepted_break(
            bar, selected.role, selected.lower_bound, selected.upper_bound
        ):
            # Accepted break wins over touch/reaction.  The watch is registered
            # for audit, but no misleading watch marker is emitted.
            return self._terminal(
                bar,
                state=State.FAILED,
                event=Event.ACCEPTED_BREAK,
                reason=ReasonCode.ACCEPTED_BREAK,
                rejections=rejections,
            )
        if self._reaction_confirmed(
            bar, selected.role, selected.lower_bound, selected.upper_bound
        ):
            # Same-bar touch+reaction is valid at this 10m close.  Only the
            # terminal confirmation marker is outward, keeping one marker/bar.
            return self._finish_reaction(bar)
        return self._snapshot(
            bar,
            data_valid=True,
            event=_watch_event(selected.role),
            reason=ReasonCode.WATCH_ONLY,
            marker_text=_marker_for_watch(selected.role),
            marker_price=bar.low if selected.role is BandRole.SUPPORT else bar.high,
            rejections=rejections,
        )


def run_reversal(
    bars: Sequence[TenMinuteBar],
    bands_by_bar: Sequence[Sequence[NamedBand]],
    atr_by_bar: Sequence[PriorAtrContext],
    *,
    config: ReversalConfig | None = None,
) -> list[Observation]:
    if not (len(bars) == len(bands_by_bar) == len(atr_by_bar)):
        raise ValueError("bars, bands_by_bar, and atr_by_bar must have equal lengths")
    engine = PositionReversalEngine(config)
    return [
        engine.ingest(bar, bands, atr)
        for bar, bands, atr in zip(bars, bands_by_bar, atr_by_bar, strict=True)
    ]
