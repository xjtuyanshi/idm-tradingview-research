"""Deterministic oracle for the R3 native-10m primary-opportunity contract.

Only TREND_CONTINUATION is enabled.  Native confirmed 10-minute bars determine
slow direction, first-touch WATCH events, causal named-level routing, the 1R
permission gate, and active-plan termination.  The 3-minute engine only times an
entry or reports invalidation for one active 10-minute opportunity identity.

The module is read-only.  It creates no TradingView alert, strategy order,
broker action, score, profitability claim, or VIX/SATy/ATR/divergence vote.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum, IntEnum
from math import isfinite
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

PROTOCOL_VERSION = "phase1-10m-primary-opportunity-3.0"
TIMING_PROTOCOL_VERSION = "phase1-3m-opportunity-timing-3.0"
POSITION_REVERSAL_ENABLED = False
PRIMARY_INTERVAL_SECONDS = 600
TIMING_INTERVAL_SECONDS = 180
PIVOT_LEFT_BARS = 2
PIVOT_RIGHT_BARS = 2
MAX_PIVOT_LEVELS = 64
MAX_REACTION_BARS = 6
MAX_ACTIVE_BARS = 12
MAX_TIMING_TRIGGER_BARS = 8
MINIMUM_SPACE_R = 1.0
OPPORTUNITY_PREFIX_LONG = "10M-TC-L-"
OPPORTUNITY_PREFIX_SHORT = "10M-TC-S-"
EPOCH_PREFIX_LONG = "10M-EPOCH-L-"
EPOCH_PREFIX_SHORT = "10M-EPOCH-S-"
EPISODE_PREFIX_LONG = "10M-EP-L-"
EPISODE_PREFIX_SHORT = "10M-EP-S-"
NEW_YORK = ZoneInfo("America/New_York")


class Direction(IntEnum):
    SHORT = -1
    NONE = 0
    LONG = 1


class PrimaryState(str, Enum):
    DISABLED = "DISABLED"
    WAIT_TREND = "WAIT_TREND"
    WAIT_CLEAR = "WAIT_CLEAR"
    ARMED = "ARMED"
    WAIT_REACTION = "WAIT_REACTION"
    ACTIVE = "ACTIVE"


class TraderOutcome(str, Enum):
    WATCH_LONG = "观多"
    WATCH_SHORT = "观空"
    MAIN_LONG = "主多机会"
    MAIN_SHORT = "主空机会"
    DONT_CHASE = "不追"
    NO_OPPORTUNITY = "无大机会"


class PrimaryEvent(str, Enum):
    NONE = "NONE"
    WATCH_LONG = "WATCH_LONG"
    WATCH_SHORT = "WATCH_SHORT"
    MAIN_LONG = "MAIN_LONG"
    MAIN_SHORT = "MAIN_SHORT"
    DONT_CHASE = "DONT_CHASE"
    SPACE_UNKNOWN = "SPACE_UNKNOWN"
    INVALIDATED = "INVALIDATED"
    TARGET_REACHED = "TARGET_REACHED"
    EXPIRED = "EXPIRED"
    CONTEXT_RESET = "CONTEXT_RESET"
    DATA_RESET = "DATA_RESET"


class ReasonCode(str, Enum):
    DATA_TIMEFRAME_MISMATCH = "DATA_TIMEFRAME_MISMATCH"
    DATA_SYMBOL_MISMATCH = "DATA_SYMBOL_MISMATCH"
    DATA_NON_STANDARD = "DATA_NON_STANDARD"
    DATA_UNCONFIRMED = "DATA_UNCONFIRMED"
    DATA_INVALID = "DATA_INVALID"
    DATA_DUPLICATE_IGNORED = "DATA_DUPLICATE_IGNORED"
    DATA_NON_MONOTONIC = "DATA_NON_MONOTONIC"
    DATA_GAP_RESET = "DATA_GAP_RESET"
    WAIT_SLOW_TREND = "WAIT_SLOW_TREND"
    EPOCH_STARTED = "EPOCH_STARTED"
    WAIT_FULL_CLEAR = "WAIT_FULL_CLEAR"
    EPISODE_ARMED = "EPISODE_ARMED"
    WAIT_FIRST_PULLBACK = "WAIT_FIRST_PULLBACK"
    FIRST_PULLBACK_WATCH = "FIRST_PULLBACK_WATCH"
    WAIT_LATER_RECLAIM = "WAIT_LATER_RECLAIM"
    REACTION_EXPIRED = "REACTION_EXPIRED"
    SLOW_CONTEXT_LOST = "SLOW_CONTEXT_LOST"
    FROZEN_INVALIDATION_BROKEN = "FROZEN_INVALIDATION_BROKEN"
    SPACE_UNKNOWN = "SPACE_UNKNOWN"
    SPACE_LT_1R = "SPACE_LT_1R"
    MAIN_OPPORTUNITY_ACTIVE = "MAIN_OPPORTUNITY_ACTIVE"
    TARGET_REACHED = "TARGET_REACHED"
    ACTIVE_EXPIRED = "ACTIVE_EXPIRED"


class NamedLevelSource(str, Enum):
    PRIOR_EXCURSION_10M = "PRIOR_EXCURSION_10M"
    CONFIRMED_PIVOT_10M = "CONFIRMED_PIVOT_10M"
    PREVIOUS_COMPLETED_DAY_HIGH = "PREVIOUS_COMPLETED_DAY_HIGH"
    PREVIOUS_COMPLETED_DAY_LOW = "PREVIOUS_COMPLETED_DAY_LOW"
    UNKNOWN = "UNKNOWN"


SOURCE_PRIORITY: dict[NamedLevelSource, int] = {
    NamedLevelSource.PRIOR_EXCURSION_10M: 1,
    NamedLevelSource.CONFIRMED_PIVOT_10M: 2,
    NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH: 3,
    NamedLevelSource.PREVIOUS_COMPLETED_DAY_LOW: 3,
    NamedLevelSource.UNKNOWN: 99,
}


@dataclass(frozen=True, slots=True)
class PrimaryConfig:
    expected_symbol: str = "CAPITALCOM:SPX500"
    interval_seconds: int = PRIMARY_INTERVAL_SECONDS
    minimum_tick: float = 0.1
    minimum_space_r: float = MINIMUM_SPACE_R
    max_reaction_bars: int = MAX_REACTION_BARS
    max_active_bars: int = MAX_ACTIVE_BARS
    pivot_left_bars: int = PIVOT_LEFT_BARS
    pivot_right_bars: int = PIVOT_RIGHT_BARS
    max_pivot_levels: int = MAX_PIVOT_LEVELS

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if not isfinite(self.minimum_tick) or self.minimum_tick <= 0:
            raise ValueError("minimum_tick must be finite and positive")
        if not isfinite(self.minimum_space_r) or self.minimum_space_r <= 0:
            raise ValueError("minimum_space_r must be finite and positive")
        if self.max_reaction_bars < 1 or self.max_active_bars < 1:
            raise ValueError("expiry bars must be positive")
        if self.pivot_left_bars != 2 or self.pivot_right_bars != 2:
            raise ValueError("R3 freezes confirmed pivots at left=2/right=2")
        if self.max_pivot_levels < 1:
            raise ValueError("max_pivot_levels must be positive")


@dataclass(frozen=True, slots=True)
class TenMinuteBar:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    ema5: float
    ema12: float
    ema21: float
    ema48: float
    symbol: str = "CAPITALCOM:SPX500"
    timeframe_seconds: int = PRIMARY_INTERVAL_SECONDS
    is_confirmed: bool = True
    is_standard: bool = True


@dataclass(frozen=True, slots=True)
class NamedLevelCandidate:
    price: float
    source: NamedLevelSource
    provenance_time_ms: int | None
    consumed: bool = False


@dataclass(frozen=True, slots=True)
class OpportunityPlan:
    opportunity_id: str
    epoch_id: str
    episode_id: str
    direction: Direction
    confirmation_time_ms: int
    entry_reference: float
    invalidation: float
    next_named_level: float | None
    next_named_level_source: NamedLevelSource
    next_named_level_provenance_time_ms: int | None
    risk: float
    space: float | None
    space_r: float | None


@dataclass(frozen=True, slots=True)
class PrimaryObservation:
    protocol_version: str
    timestamp_ms: int
    data_valid: bool
    state: PrimaryState
    outcome: TraderOutcome
    outcome_direction: Direction
    event: PrimaryEvent
    reason_code: ReasonCode
    slow_direction: Direction
    fast_direction: Direction
    epoch_id: str | None
    episode_id: str | None
    pullback_time_ms: int | None
    prior_excursion: float | None
    reaction_high: float | None
    reaction_low: float | None
    frozen_candidates: tuple[NamedLevelCandidate, ...]
    opportunity_active: bool
    plan: OpportunityPlan | None
    marker_price: float | None


class TimingState(str, Enum):
    DISABLED = "DISABLED"
    WAIT_10M = "WAIT_10M"
    WAIT_PULLBACK = "WAIT_PULLBACK"
    WAIT_TRIGGER = "WAIT_TRIGGER"
    ENTERED = "ENTERED"
    LOCKED = "LOCKED"


class TimingEvent(str, Enum):
    NONE = "NONE"
    LONG_ENTRY = "LONG_ENTRY"
    SHORT_ENTRY = "SHORT_ENTRY"
    LONG_INVALIDATED = "LONG_INVALIDATED"
    SHORT_INVALIDATED = "SHORT_INVALIDATED"
    LONG_TARGET_REACHED = "LONG_TARGET_REACHED"
    SHORT_TARGET_REACHED = "SHORT_TARGET_REACHED"


class TimingReason(str, Enum):
    DATA_TIMEFRAME_MISMATCH = "DATA_TIMEFRAME_MISMATCH"
    DATA_SYMBOL_MISMATCH = "DATA_SYMBOL_MISMATCH"
    DATA_NON_STANDARD = "DATA_NON_STANDARD"
    DATA_UNCONFIRMED = "DATA_UNCONFIRMED"
    DATA_INVALID = "DATA_INVALID"
    DATA_DUPLICATE_IGNORED = "DATA_DUPLICATE_IGNORED"
    DATA_NON_MONOTONIC = "DATA_NON_MONOTONIC"
    DATA_GAP_RESET = "DATA_GAP_RESET"
    WAIT_10M = "WAIT_10M"
    NEW_OPPORTUNITY = "NEW_OPPORTUNITY"
    OPPORTUNITY_REPLACED = "OPPORTUNITY_REPLACED"
    OPPORTUNITY_SUPPRESSED = "OPPORTUNITY_SUPPRESSED"
    WAIT_PULLBACK = "WAIT_PULLBACK"
    PULLBACK_FROZEN = "PULLBACK_FROZEN"
    WAIT_LATER_TRIGGER = "WAIT_LATER_TRIGGER"
    TRIGGER_EXPIRED = "TRIGGER_EXPIRED"
    ENTRY_CONFIRMED = "ENTRY_CONFIRMED"
    OPPORTUNITY_INVALIDATED = "OPPORTUNITY_INVALIDATED"
    OPPORTUNITY_TARGET_REACHED = "OPPORTUNITY_TARGET_REACHED"
    OPPORTUNITY_ENDED = "OPPORTUNITY_ENDED"
    SPACE_LT_1R = "SPACE_LT_1R"
    ENTERED_PLAN_MANAGEMENT = "ENTERED_PLAN_MANAGEMENT"


@dataclass(frozen=True, slots=True)
class TimingConfig:
    expected_symbol: str = "CAPITALCOM:SPX500"
    interval_seconds: int = TIMING_INTERVAL_SECONDS
    max_trigger_bars: int = MAX_TIMING_TRIGGER_BARS
    minimum_space_r: float = MINIMUM_SPACE_R

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.max_trigger_bars < 1:
            raise ValueError("max_trigger_bars must be positive")
        if not isfinite(self.minimum_space_r) or self.minimum_space_r <= 0:
            raise ValueError("minimum_space_r must be finite and positive")


@dataclass(frozen=True, slots=True)
class ThreeMinuteBar:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    ema5: float
    ema12: float
    symbol: str = "CAPITALCOM:SPX500"
    timeframe_seconds: int = TIMING_INTERVAL_SECONDS
    is_confirmed: bool = True
    is_standard: bool = True


@dataclass(frozen=True, slots=True)
class TimingObservation:
    protocol_version: str
    timestamp_ms: int
    data_valid: bool
    state: TimingState
    event: TimingEvent
    reason_code: TimingReason
    opportunity_id: str | None
    direction: Direction
    plan_invalidation: float | None
    plan_target: float | None
    plan_target_source: NamedLevelSource
    frozen_trigger: float | None
    suppressed_opportunity_id: str | None
    marker_price: float | None


def canonical_epoch_id(direction: Direction, timestamp_ms: int) -> str:
    if direction == Direction.LONG:
        prefix = EPOCH_PREFIX_LONG
    elif direction == Direction.SHORT:
        prefix = EPOCH_PREFIX_SHORT
    else:
        raise ValueError("epoch id requires LONG or SHORT")
    return f"{prefix}{timestamp_ms}"


def canonical_episode_id(direction: Direction, timestamp_ms: int) -> str:
    if direction == Direction.LONG:
        prefix = EPISODE_PREFIX_LONG
    elif direction == Direction.SHORT:
        prefix = EPISODE_PREFIX_SHORT
    else:
        raise ValueError("episode id requires LONG or SHORT")
    return f"{prefix}{timestamp_ms}"


def canonical_opportunity_id(direction: Direction, timestamp_ms: int) -> str:
    if direction == Direction.LONG:
        prefix = OPPORTUNITY_PREFIX_LONG
    elif direction == Direction.SHORT:
        prefix = OPPORTUNITY_PREFIX_SHORT
    else:
        raise ValueError("opportunity id requires LONG or SHORT")
    return f"{prefix}{timestamp_ms}"


def _valid_ohlc(open_: float, high: float, low: float, close: float) -> bool:
    values = (open_, high, low, close)
    if not all(isfinite(value) for value in values):
        return False
    return not (high < low or high < max(open_, close) or low > min(open_, close))


def _directional_risk(direction: Direction, entry: float, invalidation: float) -> float:
    if direction == Direction.LONG:
        return entry - invalidation
    if direction == Direction.SHORT:
        return invalidation - entry
    raise ValueError("directional risk requires LONG or SHORT")


def _directional_space(direction: Direction, entry: float, target: float) -> float:
    if direction == Direction.LONG:
        return target - entry
    if direction == Direction.SHORT:
        return entry - target
    raise ValueError("directional space requires LONG or SHORT")


def _et_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).astimezone(
        NEW_YORK
    )


def _day_key(timestamp_ms: int) -> tuple[int, int, int]:
    value = _et_datetime(timestamp_ms)
    return value.year, value.month, value.day


def _date_from_key(key: tuple[int, int, int]) -> date:
    return date(*key)


class PrimaryOpportunityEngine:
    """Confirmed-only native 10m TREND_CONTINUATION state machine."""

    def __init__(self, config: PrimaryConfig | None = None) -> None:
        self.config = config or PrimaryConfig()
        self._last_timestamp_ms: int | None = None
        self._state = PrimaryState.WAIT_TREND
        self._epoch_direction = Direction.NONE
        self._epoch_id: str | None = None
        self._episode_id: str | None = None
        self._prior_excursion: float | None = None
        self._prior_excursion_time_ms: int | None = None
        self._pullback_time_ms: int | None = None
        self._reaction_high: float | None = None
        self._reaction_low: float | None = None
        self._frozen_invalidation: float | None = None
        self._frozen_candidates: list[NamedLevelCandidate] = []
        self._reaction_age = 0
        self._active_age = 0
        self._plan: OpportunityPlan | None = None
        self._opportunity_active = False
        self._outcome = TraderOutcome.NO_OPPORTUNITY
        self._outcome_direction = Direction.NONE

        self._pivot_window: deque[TenMinuteBar] = deque(maxlen=5)
        self._pivot_highs: deque[NamedLevelCandidate] = deque(
            maxlen=self.config.max_pivot_levels
        )
        self._pivot_lows: deque[NamedLevelCandidate] = deque(
            maxlen=self.config.max_pivot_levels
        )
        self._current_day_key: tuple[int, int, int] | None = None
        self._current_day_high: float | None = None
        self._current_day_low: float | None = None
        self._current_day_first_timestamp_ms: int | None = None
        self._current_day_last_timestamp_ms: int | None = None
        self._current_day_bar_count = 0
        self._current_day_contiguous = False
        self._previous_day_high: float | None = None
        self._previous_day_low: float | None = None
        self._previous_day_completed_at_ms: int | None = None
        self._previous_day_high_consumed = False
        self._previous_day_low_consumed = False

    @staticmethod
    def _slow_direction(bar: TenMinuteBar) -> Direction:
        if bar.ema21 > bar.ema48 and bar.close >= bar.ema48:
            return Direction.LONG
        if bar.ema21 < bar.ema48 and bar.close <= bar.ema48:
            return Direction.SHORT
        return Direction.NONE

    @staticmethod
    def _fast_direction(bar: TenMinuteBar) -> Direction:
        if bar.ema5 > bar.ema12:
            return Direction.LONG
        if bar.ema5 < bar.ema12:
            return Direction.SHORT
        return Direction.NONE

    @staticmethod
    def _cloud(bar: TenMinuteBar) -> tuple[float, float]:
        return max(bar.ema5, bar.ema12), min(bar.ema5, bar.ema12)

    def _departure(self, bar: TenMinuteBar, direction: Direction) -> bool:
        upper, lower = self._cloud(bar)
        fast = self._fast_direction(bar)
        if direction == Direction.LONG:
            return fast == Direction.LONG and bar.low > upper and bar.close > upper
        if direction == Direction.SHORT:
            return fast == Direction.SHORT and bar.high < lower and bar.close < lower
        return False

    def _reset_episode_fields(self) -> None:
        self._episode_id = None
        self._prior_excursion = None
        self._prior_excursion_time_ms = None
        self._pullback_time_ms = None
        self._reaction_high = None
        self._reaction_low = None
        self._frozen_invalidation = None
        self._frozen_candidates = []
        self._reaction_age = 0
        self._active_age = 0
        self._plan = None
        self._opportunity_active = False
        self._outcome = TraderOutcome.NO_OPPORTUNITY
        self._outcome_direction = Direction.NONE

    def _clear_epoch(self) -> None:
        self._state = PrimaryState.WAIT_TREND
        self._epoch_direction = Direction.NONE
        self._epoch_id = None
        self._reset_episode_fields()

    def _clear_market_context(self) -> None:
        self._pivot_window.clear()
        self._pivot_highs.clear()
        self._pivot_lows.clear()
        self._current_day_key = None
        self._current_day_high = None
        self._current_day_low = None
        self._current_day_first_timestamp_ms = None
        self._current_day_last_timestamp_ms = None
        self._current_day_bar_count = 0
        self._current_day_contiguous = False
        self._previous_day_high = None
        self._previous_day_low = None
        self._previous_day_completed_at_ms = None
        self._previous_day_high_consumed = False
        self._previous_day_low_consumed = False

    def _clear_all(self) -> None:
        self._clear_epoch()
        self._clear_market_context()

    def _snapshot(
        self,
        *,
        bar: TenMinuteBar,
        data_valid: bool,
        event: PrimaryEvent,
        reason: ReasonCode,
        slow_direction: Direction,
        fast_direction: Direction,
        marker_price: float | None = None,
        state_override: PrimaryState | None = None,
    ) -> PrimaryObservation:
        return PrimaryObservation(
            protocol_version=PROTOCOL_VERSION,
            timestamp_ms=bar.timestamp_ms,
            data_valid=data_valid,
            state=self._state if state_override is None else state_override,
            outcome=self._outcome,
            outcome_direction=self._outcome_direction,
            event=event,
            reason_code=reason,
            slow_direction=slow_direction,
            fast_direction=fast_direction,
            epoch_id=self._epoch_id,
            episode_id=self._episode_id,
            pullback_time_ms=self._pullback_time_ms,
            prior_excursion=self._prior_excursion,
            reaction_high=self._reaction_high,
            reaction_low=self._reaction_low,
            frozen_candidates=tuple(self._frozen_candidates),
            opportunity_active=self._opportunity_active,
            plan=self._plan,
            marker_price=marker_price,
        )

    def _host_contract_reason(self, bar: TenMinuteBar) -> ReasonCode | None:
        if bar.symbol != self.config.expected_symbol:
            return ReasonCode.DATA_SYMBOL_MISMATCH
        if bar.timeframe_seconds != self.config.interval_seconds:
            return ReasonCode.DATA_TIMEFRAME_MISMATCH
        if not bar.is_standard:
            return ReasonCode.DATA_NON_STANDARD
        return None

    @staticmethod
    def _data_ready(bar: TenMinuteBar) -> bool:
        return _valid_ohlc(bar.open, bar.high, bar.low, bar.close) and all(
            isfinite(value) for value in (bar.ema5, bar.ema12, bar.ema21, bar.ema48)
        )

    def _start_current_day(self, key: tuple[int, int, int]) -> None:
        self._current_day_key = key
        self._current_day_high = None
        self._current_day_low = None
        self._current_day_first_timestamp_ms = None
        self._current_day_last_timestamp_ms = None
        self._current_day_bar_count = 0
        self._current_day_contiguous = True

    def _current_day_is_publishable(
        self, next_day_key: tuple[int, int, int]
    ) -> bool:
        if self._current_day_key is None:
            return False
        if _date_from_key(next_day_key) != _date_from_key(self._current_day_key) + timedelta(days=1):
            return False
        if (
            not self._current_day_contiguous
            or self._current_day_bar_count != 144
            or self._current_day_first_timestamp_ms is None
            or self._current_day_last_timestamp_ms is None
            or self._current_day_high is None
            or self._current_day_low is None
        ):
            return False
        first = _et_datetime(self._current_day_first_timestamp_ms)
        last = _et_datetime(self._current_day_last_timestamp_ms)
        return (
            first.hour == 0
            and first.minute == 0
            and first.second == 0
            and last.hour == 23
            and last.minute == 50
            and last.second == 0
        )

    def _roll_day_before_bar(self, bar: TenMinuteBar) -> None:
        key = _day_key(bar.timestamp_ms)
        if self._current_day_key is None:
            self._start_current_day(key)
            return
        if key != self._current_day_key:
            if self._current_day_is_publishable(key):
                self._previous_day_high = self._current_day_high
                self._previous_day_low = self._current_day_low
                self._previous_day_completed_at_ms = bar.timestamp_ms
            else:
                self._previous_day_high = None
                self._previous_day_low = None
                self._previous_day_completed_at_ms = None
            self._previous_day_high_consumed = False
            self._previous_day_low_consumed = False
            self._start_current_day(key)

    def _consume_known_levels_before_state(self, bar: TenMinuteBar) -> None:
        self._pivot_highs = deque(
            (
                replace(item, consumed=item.consumed or bar.high >= item.price)
                for item in self._pivot_highs
            ),
            maxlen=self.config.max_pivot_levels,
        )
        self._pivot_lows = deque(
            (
                replace(item, consumed=item.consumed or bar.low <= item.price)
                for item in self._pivot_lows
            ),
            maxlen=self.config.max_pivot_levels,
        )
        if self._previous_day_high is not None and bar.high >= self._previous_day_high:
            self._previous_day_high_consumed = True
        if self._previous_day_low is not None and bar.low <= self._previous_day_low:
            self._previous_day_low_consumed = True

    def _finalize_day_after_bar(self, bar: TenMinuteBar) -> None:
        key = _day_key(bar.timestamp_ms)
        if self._current_day_key != key:
            raise RuntimeError("day tracker was not rolled before state processing")
        if self._current_day_bar_count == 0:
            local = _et_datetime(bar.timestamp_ms)
            self._current_day_first_timestamp_ms = bar.timestamp_ms
            self._current_day_last_timestamp_ms = bar.timestamp_ms
            self._current_day_bar_count = 1
            self._current_day_contiguous = (
                local.hour == 0 and local.minute == 0 and local.second == 0
            )
        else:
            if self._current_day_last_timestamp_ms is None:
                raise RuntimeError("day tracker is missing its last timestamp")
            self._current_day_contiguous = self._current_day_contiguous and (
                bar.timestamp_ms - self._current_day_last_timestamp_ms
                == self.config.interval_seconds * 1000
            )
            self._current_day_last_timestamp_ms = bar.timestamp_ms
            self._current_day_bar_count += 1
        self._current_day_high = (
            bar.high
            if self._current_day_high is None
            else max(self._current_day_high, bar.high)
        )
        self._current_day_low = (
            bar.low
            if self._current_day_low is None
            else min(self._current_day_low, bar.low)
        )

    def _register_pivot_after_bar(self, bar: TenMinuteBar) -> None:
        self._pivot_window.append(bar)
        if len(self._pivot_window) != 5:
            return
        rows = tuple(self._pivot_window)
        center = rows[2]
        others = rows[:2] + rows[3:]
        if all(center.high > item.high for item in others):
            self._pivot_highs.append(
                NamedLevelCandidate(
                    price=center.high,
                    source=NamedLevelSource.CONFIRMED_PIVOT_10M,
                    provenance_time_ms=center.timestamp_ms,
                )
            )
        if all(center.low < item.low for item in others):
            self._pivot_lows.append(
                NamedLevelCandidate(
                    price=center.low,
                    source=NamedLevelSource.CONFIRMED_PIVOT_10M,
                    provenance_time_ms=center.timestamp_ms,
                )
            )

    @staticmethod
    def _candidate_sort_key(
        direction: Direction, candidate: NamedLevelCandidate
    ) -> tuple[float, int, int]:
        directional_price = (
            candidate.price if direction == Direction.LONG else -candidate.price
        )
        provenance = (
            candidate.provenance_time_ms
            if candidate.provenance_time_ms is not None
            else -1
        )
        return directional_price, SOURCE_PRIORITY[candidate.source], provenance

    def _freeze_candidates(self, bar: TenMinuteBar) -> list[NamedLevelCandidate]:
        direction = self._epoch_direction
        candidates: list[NamedLevelCandidate] = []

        def add(candidate: NamedLevelCandidate) -> None:
            if not isfinite(candidate.price):
                return
            forward = (
                direction == Direction.LONG and candidate.price > bar.high
            ) or (direction == Direction.SHORT and candidate.price < bar.low)
            if not forward:
                return
            key = (candidate.price, candidate.source, candidate.provenance_time_ms)
            if any(
                (item.price, item.source, item.provenance_time_ms) == key
                for item in candidates
            ):
                return
            candidates.append(candidate)

        if self._prior_excursion is not None:
            add(
                NamedLevelCandidate(
                    price=self._prior_excursion,
                    source=NamedLevelSource.PRIOR_EXCURSION_10M,
                    provenance_time_ms=self._prior_excursion_time_ms,
                )
            )
        pivots: Sequence[NamedLevelCandidate] = (
            tuple(self._pivot_highs)
            if direction == Direction.LONG
            else tuple(self._pivot_lows)
        )
        for pivot in pivots:
            if not pivot.consumed:
                add(pivot)
        if (
            direction == Direction.LONG
            and self._previous_day_high is not None
            and not self._previous_day_high_consumed
        ):
            add(
                NamedLevelCandidate(
                    price=self._previous_day_high,
                    source=NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH,
                    provenance_time_ms=self._previous_day_completed_at_ms,
                )
            )
        if (
            direction == Direction.SHORT
            and self._previous_day_low is not None
            and not self._previous_day_low_consumed
        ):
            add(
                NamedLevelCandidate(
                    price=self._previous_day_low,
                    source=NamedLevelSource.PREVIOUS_COMPLETED_DAY_LOW,
                    provenance_time_ms=self._previous_day_completed_at_ms,
                )
            )
        candidates.sort(key=lambda item: self._candidate_sort_key(direction, item))
        return candidates

    def _consume_candidates(self, bar: TenMinuteBar) -> None:
        direction = self._epoch_direction
        updated: list[NamedLevelCandidate] = []
        for candidate in self._frozen_candidates:
            consumed_now = (
                direction == Direction.LONG and bar.high >= candidate.price
            ) or (direction == Direction.SHORT and bar.low <= candidate.price)
            updated.append(
                replace(candidate, consumed=candidate.consumed or consumed_now)
            )
        self._frozen_candidates = updated

    def _select_forward_candidate(
        self, bar: TenMinuteBar
    ) -> NamedLevelCandidate | None:
        direction = self._epoch_direction
        eligible = [
            item
            for item in self._frozen_candidates
            if not item.consumed
            and (
                (direction == Direction.LONG and item.price > bar.high)
                or (direction == Direction.SHORT and item.price < bar.low)
            )
        ]
        if not eligible:
            return None
        eligible.sort(key=lambda item: self._candidate_sort_key(direction, item))
        return eligible[0]

    def _start_episode(self, bar: TenMinuteBar) -> None:
        if self._epoch_direction == Direction.NONE:
            raise RuntimeError("cannot start episode without a slow epoch")
        self._reset_episode_fields()
        self._episode_id = canonical_episode_id(
            self._epoch_direction, bar.timestamp_ms
        )
        self._prior_excursion = (
            bar.high if self._epoch_direction == Direction.LONG else bar.low
        )
        self._prior_excursion_time_ms = bar.timestamp_ms
        self._state = PrimaryState.ARMED

    def _enter_wait_clear(self) -> None:
        self._state = PrimaryState.WAIT_CLEAR
        self._opportunity_active = False

    def _context_reset(
        self,
        *,
        bar: TenMinuteBar,
        slow_direction: Direction,
        fast_direction: Direction,
        event: PrimaryEvent = PrimaryEvent.CONTEXT_RESET,
        reason: ReasonCode = ReasonCode.SLOW_CONTEXT_LOST,
        marker_price: float | None = None,
    ) -> PrimaryObservation:
        # The returned terminal snapshot retains the frozen plan for audit, but
        # trader permission/outcome is already cleared on this bar.
        self._opportunity_active = False
        self._outcome = TraderOutcome.NO_OPPORTUNITY
        self._outcome_direction = Direction.NONE
        snapshot = self._snapshot(
            bar=bar,
            data_valid=True,
            event=event,
            reason=reason,
            slow_direction=slow_direction,
            fast_direction=fast_direction,
            marker_price=marker_price,
            state_override=PrimaryState.WAIT_TREND,
        )
        self._clear_epoch()
        return snapshot

    def _initialize_context_after_gap(self, bar: TenMinuteBar) -> None:
        self._clear_market_context()
        self._roll_day_before_bar(bar)
        self._finalize_day_after_bar(bar)
        self._register_pivot_after_bar(bar)

    def ingest(self, bar: TenMinuteBar) -> PrimaryObservation:
        host_reason = self._host_contract_reason(bar)
        if host_reason is not None:
            self._clear_all()
            self._last_timestamp_ms = None
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.NONE,
                reason=host_reason,
                slow_direction=Direction.NONE,
                fast_direction=Direction.NONE,
                state_override=PrimaryState.DISABLED,
            )

        if not bar.is_confirmed:
            ready = self._data_ready(bar)
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.NONE,
                reason=ReasonCode.DATA_UNCONFIRMED,
                slow_direction=self._slow_direction(bar) if ready else Direction.NONE,
                fast_direction=self._fast_direction(bar) if ready else Direction.NONE,
            )

        if not self._data_ready(bar):
            self._clear_all()
            self._last_timestamp_ms = None
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.DATA_RESET,
                reason=ReasonCode.DATA_INVALID,
                slow_direction=Direction.NONE,
                fast_direction=Direction.NONE,
                state_override=PrimaryState.DISABLED,
            )

        if self._last_timestamp_ms is not None and bar.timestamp_ms == self._last_timestamp_ms:
            # Exact duplicates are transport/noise observations.  They never
            # advance, emit, consume levels, or clear state.
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.NONE,
                reason=ReasonCode.DATA_DUPLICATE_IGNORED,
                slow_direction=self._slow_direction(bar),
                fast_direction=self._fast_direction(bar),
            )

        if self._last_timestamp_ms is not None and bar.timestamp_ms < self._last_timestamp_ms:
            self._clear_all()
            self._last_timestamp_ms = None
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.DATA_RESET,
                reason=ReasonCode.DATA_NON_MONOTONIC,
                slow_direction=Direction.NONE,
                fast_direction=Direction.NONE,
                state_override=PrimaryState.DISABLED,
            )

        slow_direction = self._slow_direction(bar)
        fast_direction = self._fast_direction(bar)
        expected_ms = self.config.interval_seconds * 1000
        if (
            self._last_timestamp_ms is not None
            and bar.timestamp_ms - self._last_timestamp_ms != expected_ms
        ):
            self._clear_epoch()
            self._initialize_context_after_gap(bar)
            self._last_timestamp_ms = bar.timestamp_ms
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=PrimaryEvent.DATA_RESET,
                reason=ReasonCode.DATA_GAP_RESET,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        self._roll_day_before_bar(bar)
        self._consume_known_levels_before_state(bar)
        observation = self._advance(bar, slow_direction, fast_direction)
        self._finalize_day_after_bar(bar)
        # A 2/2 pivot becomes known only after this bar closes.  Registering it
        # after state advancement prevents a pivot confirmed on the touch bar
        # from being backfilled into that same episode.
        self._register_pivot_after_bar(bar)
        self._last_timestamp_ms = bar.timestamp_ms
        return observation

    def _advance(
        self,
        bar: TenMinuteBar,
        slow_direction: Direction,
        fast_direction: Direction,
    ) -> PrimaryObservation:
        cloud_upper, cloud_lower = self._cloud(bar)

        if self._epoch_direction == Direction.NONE:
            if slow_direction == Direction.NONE:
                self._state = PrimaryState.WAIT_TREND
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.NONE,
                    reason=ReasonCode.WAIT_SLOW_TREND,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )
            self._reset_episode_fields()
            self._epoch_direction = slow_direction
            self._epoch_id = canonical_epoch_id(slow_direction, bar.timestamp_ms)
            self._state = PrimaryState.WAIT_CLEAR
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=PrimaryEvent.NONE,
                reason=ReasonCode.EPOCH_STARTED,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        # WAIT_REACTION and ACTIVE have terminal priorities that must be settled
        # before the generic slow-context reset below.
        if self._state == PrimaryState.WAIT_REACTION:
            if self._frozen_invalidation is None:
                raise RuntimeError("reaction state is missing frozen invalidation")
            invalidated = (
                self._epoch_direction == Direction.LONG
                and bar.close < self._frozen_invalidation
            ) or (
                self._epoch_direction == Direction.SHORT
                and bar.close > self._frozen_invalidation
            )
            if invalidated:
                self._opportunity_active = False
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                if slow_direction != self._epoch_direction:
                    return self._context_reset(
                        bar=bar,
                        slow_direction=slow_direction,
                        fast_direction=fast_direction,
                        event=PrimaryEvent.INVALIDATED,
                        reason=ReasonCode.FROZEN_INVALIDATION_BROKEN,
                        marker_price=self._frozen_invalidation,
                    )
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.INVALIDATED,
                    reason=ReasonCode.FROZEN_INVALIDATION_BROKEN,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                    marker_price=self._frozen_invalidation,
                )
            if slow_direction != self._epoch_direction:
                return self._context_reset(
                    bar=bar,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )

            self._consume_candidates(bar)
            self._reaction_age += 1
            if self._reaction_age > self.config.max_reaction_bars:
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.EXPIRED,
                    reason=ReasonCode.REACTION_EXPIRED,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )

            if self._reaction_high is None or self._reaction_low is None:
                raise RuntimeError("reaction state is missing frozen trigger")
            later_reclaim = (
                self._epoch_direction == Direction.LONG
                and fast_direction == Direction.LONG
                and bar.close > self._reaction_high
                and bar.close > cloud_upper
            ) or (
                self._epoch_direction == Direction.SHORT
                and fast_direction == Direction.SHORT
                and bar.close < self._reaction_low
                and bar.close < cloud_lower
            )
            if not later_reclaim:
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.NONE,
                    reason=ReasonCode.WAIT_LATER_RECLAIM,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )

            if self._epoch_id is None or self._episode_id is None:
                raise RuntimeError("reclaim is missing epoch/episode identity")
            direction = self._epoch_direction
            entry = bar.close
            invalidation = self._frozen_invalidation
            risk = _directional_risk(direction, entry, invalidation)
            selected = self._select_forward_candidate(bar)
            plan_id = canonical_opportunity_id(direction, bar.timestamp_ms)
            if risk <= 2.0 * self.config.minimum_tick or selected is None:
                self._plan = OpportunityPlan(
                    opportunity_id=plan_id,
                    epoch_id=self._epoch_id,
                    episode_id=self._episode_id,
                    direction=direction,
                    confirmation_time_ms=bar.timestamp_ms,
                    entry_reference=entry,
                    invalidation=invalidation,
                    next_named_level=None,
                    next_named_level_source=NamedLevelSource.UNKNOWN,
                    next_named_level_provenance_time_ms=None,
                    risk=risk,
                    space=None,
                    space_r=None,
                )
                self._opportunity_active = False
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.SPACE_UNKNOWN,
                    reason=ReasonCode.SPACE_UNKNOWN,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )

            space = _directional_space(direction, entry, selected.price)
            space_r = space / risk
            self._plan = OpportunityPlan(
                opportunity_id=plan_id,
                epoch_id=self._epoch_id,
                episode_id=self._episode_id,
                direction=direction,
                confirmation_time_ms=bar.timestamp_ms,
                entry_reference=entry,
                invalidation=invalidation,
                next_named_level=selected.price,
                next_named_level_source=selected.source,
                next_named_level_provenance_time_ms=selected.provenance_time_ms,
                risk=risk,
                space=space,
                space_r=space_r,
            )
            if space_r < self.config.minimum_space_r:
                self._opportunity_active = False
                self._outcome = TraderOutcome.DONT_CHASE
                self._outcome_direction = direction
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.DONT_CHASE,
                    reason=ReasonCode.SPACE_LT_1R,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )

            self._state = PrimaryState.ACTIVE
            self._opportunity_active = True
            self._active_age = 0
            self._outcome_direction = direction
            if direction == Direction.LONG:
                self._outcome = TraderOutcome.MAIN_LONG
                event = PrimaryEvent.MAIN_LONG
            else:
                self._outcome = TraderOutcome.MAIN_SHORT
                event = PrimaryEvent.MAIN_SHORT
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=event,
                reason=ReasonCode.MAIN_OPPORTUNITY_ACTIVE,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
                marker_price=entry,
            )

        if self._state == PrimaryState.ACTIVE:
            if self._plan is None:
                raise RuntimeError("active state is missing its plan")
            direction = self._plan.direction
            invalidated = (
                direction == Direction.LONG and bar.close < self._plan.invalidation
            ) or (
                direction == Direction.SHORT and bar.close > self._plan.invalidation
            )
            if invalidated:
                self._opportunity_active = False
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                if slow_direction != self._epoch_direction:
                    return self._context_reset(
                        bar=bar,
                        slow_direction=slow_direction,
                        fast_direction=fast_direction,
                        event=PrimaryEvent.INVALIDATED,
                        reason=ReasonCode.FROZEN_INVALIDATION_BROKEN,
                        marker_price=self._plan.invalidation,
                    )
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.INVALIDATED,
                    reason=ReasonCode.FROZEN_INVALIDATION_BROKEN,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                    marker_price=self._plan.invalidation,
                )

            target = self._plan.next_named_level
            target_reached = target is not None and (
                (direction == Direction.LONG and bar.high >= target)
                or (direction == Direction.SHORT and bar.low <= target)
            )
            if target_reached:
                self._opportunity_active = False
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                if slow_direction != self._epoch_direction:
                    return self._context_reset(
                        bar=bar,
                        slow_direction=slow_direction,
                        fast_direction=fast_direction,
                        event=PrimaryEvent.TARGET_REACHED,
                        reason=ReasonCode.TARGET_REACHED,
                        marker_price=target,
                    )
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.TARGET_REACHED,
                    reason=ReasonCode.TARGET_REACHED,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                    marker_price=target,
                )

            if slow_direction != self._epoch_direction:
                return self._context_reset(
                    bar=bar,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                    event=PrimaryEvent.INVALIDATED,
                    reason=ReasonCode.SLOW_CONTEXT_LOST,
                )

            self._active_age += 1
            if self._active_age > self.config.max_active_bars:
                self._opportunity_active = False
                self._outcome = TraderOutcome.NO_OPPORTUNITY
                self._outcome_direction = Direction.NONE
                self._enter_wait_clear()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=PrimaryEvent.EXPIRED,
                    reason=ReasonCode.ACTIVE_EXPIRED,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                )
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=PrimaryEvent.NONE,
                reason=ReasonCode.MAIN_OPPORTUNITY_ACTIVE,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        if slow_direction != self._epoch_direction:
            return self._context_reset(
                bar=bar,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        if self._state == PrimaryState.WAIT_CLEAR:
            if self._departure(bar, self._epoch_direction):
                self._start_episode(bar)
                reason = ReasonCode.EPISODE_ARMED
            else:
                reason = ReasonCode.WAIT_FULL_CLEAR
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=PrimaryEvent.NONE,
                reason=reason,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        if self._state == PrimaryState.ARMED:
            touch = (
                self._epoch_direction == Direction.LONG and bar.low <= cloud_upper
            ) or (
                self._epoch_direction == Direction.SHORT and bar.high >= cloud_lower
            )
            if touch:
                buffer = 2.0 * self.config.minimum_tick
                self._pullback_time_ms = bar.timestamp_ms
                self._reaction_high = bar.high
                self._reaction_low = bar.low
                self._frozen_invalidation = (
                    min(bar.low, bar.ema48) - buffer
                    if self._epoch_direction == Direction.LONG
                    else max(bar.high, bar.ema48) + buffer
                )
                self._frozen_candidates = self._freeze_candidates(bar)
                self._reaction_age = 0
                self._state = PrimaryState.WAIT_REACTION
                self._outcome_direction = self._epoch_direction
                if self._epoch_direction == Direction.LONG:
                    self._outcome = TraderOutcome.WATCH_LONG
                    event = PrimaryEvent.WATCH_LONG
                    marker = bar.low
                else:
                    self._outcome = TraderOutcome.WATCH_SHORT
                    event = PrimaryEvent.WATCH_SHORT
                    marker = bar.high
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=event,
                    reason=ReasonCode.FIRST_PULLBACK_WATCH,
                    slow_direction=slow_direction,
                    fast_direction=fast_direction,
                    marker_price=marker,
                )

            if self._epoch_direction == Direction.LONG:
                if self._prior_excursion is None or bar.high > self._prior_excursion:
                    self._prior_excursion = bar.high
                    self._prior_excursion_time_ms = bar.timestamp_ms
            else:
                if self._prior_excursion is None or bar.low < self._prior_excursion:
                    self._prior_excursion = bar.low
                    self._prior_excursion_time_ms = bar.timestamp_ms
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=PrimaryEvent.NONE,
                reason=ReasonCode.WAIT_FIRST_PULLBACK,
                slow_direction=slow_direction,
                fast_direction=fast_direction,
            )

        raise RuntimeError(f"unhandled primary state: {self._state}")


class OpportunityTimingEngine:
    """Narrow 3m consumer with separate permission and entered-plan lifetimes."""

    def __init__(self, config: TimingConfig | None = None) -> None:
        self.config = config or TimingConfig()
        self._last_timestamp_ms: int | None = None
        self._state = TimingState.WAIT_10M
        self._plan: OpportunityPlan | None = None
        self._frozen_trigger: float | None = None
        self._trigger_age = 0
        self._locked_reason = TimingReason.WAIT_10M
        self._suppressed_opportunity_id: str | None = None

    def _suppress_current(self) -> None:
        if self._plan is not None:
            self._suppressed_opportunity_id = self._plan.opportunity_id

    def _clear_runtime(self) -> None:
        self._state = TimingState.WAIT_10M
        self._plan = None
        self._frozen_trigger = None
        self._trigger_age = 0
        self._locked_reason = TimingReason.WAIT_10M

    def _snapshot(
        self,
        *,
        bar: ThreeMinuteBar,
        data_valid: bool,
        event: TimingEvent,
        reason: TimingReason,
        marker_price: float | None = None,
        state_override: TimingState | None = None,
        opportunity_id_override: str | None = None,
        direction_override: Direction | None = None,
    ) -> TimingObservation:
        plan = self._plan
        return TimingObservation(
            protocol_version=TIMING_PROTOCOL_VERSION,
            timestamp_ms=bar.timestamp_ms,
            data_valid=data_valid,
            state=self._state if state_override is None else state_override,
            event=event,
            reason_code=reason,
            opportunity_id=(
                opportunity_id_override
                if opportunity_id_override is not None
                else None
                if plan is None
                else plan.opportunity_id
            ),
            direction=(
                direction_override
                if direction_override is not None
                else Direction.NONE
                if plan is None
                else plan.direction
            ),
            plan_invalidation=None if plan is None else plan.invalidation,
            plan_target=None if plan is None else plan.next_named_level,
            plan_target_source=(
                NamedLevelSource.UNKNOWN
                if plan is None
                else plan.next_named_level_source
            ),
            frozen_trigger=self._frozen_trigger,
            suppressed_opportunity_id=self._suppressed_opportunity_id,
            marker_price=marker_price,
        )

    def _host_contract_reason(self, bar: ThreeMinuteBar) -> TimingReason | None:
        if bar.symbol != self.config.expected_symbol:
            return TimingReason.DATA_SYMBOL_MISMATCH
        if bar.timeframe_seconds != self.config.interval_seconds:
            return TimingReason.DATA_TIMEFRAME_MISMATCH
        if not bar.is_standard:
            return TimingReason.DATA_NON_STANDARD
        return None

    @staticmethod
    def _data_ready(bar: ThreeMinuteBar) -> bool:
        return _valid_ohlc(bar.open, bar.high, bar.low, bar.close) and all(
            isfinite(value) for value in (bar.ema5, bar.ema12)
        )

    @staticmethod
    def _invalidates(plan: OpportunityPlan, close: float) -> bool:
        return (plan.direction == Direction.LONG and close < plan.invalidation) or (
            plan.direction == Direction.SHORT and close > plan.invalidation
        )

    @staticmethod
    def _target_reached(plan: OpportunityPlan, bar: ThreeMinuteBar) -> bool:
        target = plan.next_named_level
        if target is None:
            return False
        return (plan.direction == Direction.LONG and bar.high >= target) or (
            plan.direction == Direction.SHORT and bar.low <= target
        )

    @staticmethod
    def _space_r_at_close(plan: OpportunityPlan, close: float) -> float | None:
        target = plan.next_named_level
        if target is None:
            return None
        risk = _directional_risk(plan.direction, close, plan.invalidation)
        space = _directional_space(plan.direction, close, target)
        if risk <= 0 or space <= 0:
            return None
        return space / risk

    @staticmethod
    def _invalidation_event(direction: Direction) -> TimingEvent:
        return (
            TimingEvent.LONG_INVALIDATED
            if direction == Direction.LONG
            else TimingEvent.SHORT_INVALIDATED
        )

    @staticmethod
    def _target_event(direction: Direction) -> TimingEvent:
        return (
            TimingEvent.LONG_TARGET_REACHED
            if direction == Direction.LONG
            else TimingEvent.SHORT_TARGET_REACHED
        )

    def _terminal(
        self,
        *,
        bar: ThreeMinuteBar,
        reason: TimingReason,
        event: TimingEvent = TimingEvent.NONE,
        marker_price: float | None = None,
    ) -> TimingObservation:
        if self._plan is None:
            raise RuntimeError("timing terminal requires a current plan")
        self._suppressed_opportunity_id = self._plan.opportunity_id
        self._state = TimingState.LOCKED
        self._locked_reason = reason
        self._frozen_trigger = None
        self._trigger_age = 0
        return self._snapshot(
            bar=bar,
            data_valid=True,
            event=event,
            reason=reason,
            marker_price=marker_price,
        )

    def _reset_with_suppression(
        self,
        *,
        bar: ThreeMinuteBar,
        reason: TimingReason,
        state: TimingState,
        keep_timestamp: bool,
    ) -> TimingObservation:
        self._suppress_current()
        suppressed = self._suppressed_opportunity_id
        self._clear_runtime()
        self._suppressed_opportunity_id = suppressed
        self._last_timestamp_ms = bar.timestamp_ms if keep_timestamp else None
        return self._snapshot(
            bar=bar,
            data_valid=False,
            event=TimingEvent.NONE,
            reason=reason,
            state_override=state,
        )

    @staticmethod
    def _event_matches_plan(
        current: OpportunityPlan | None,
        event_plan: OpportunityPlan | None,
    ) -> bool:
        return (
            current is not None
            and event_plan is not None
            and current.opportunity_id == event_plan.opportunity_id
        )

    def ingest(
        self,
        bar: ThreeMinuteBar,
        active_plan: OpportunityPlan | None,
        primary_event: PrimaryEvent = PrimaryEvent.NONE,
        primary_event_plan: OpportunityPlan | None = None,
    ) -> TimingObservation:
        host_reason = self._host_contract_reason(bar)
        if host_reason is not None:
            return self._reset_with_suppression(
                bar=bar,
                reason=host_reason,
                state=TimingState.DISABLED,
                keep_timestamp=False,
            )

        if not bar.is_confirmed:
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=TimingEvent.NONE,
                reason=TimingReason.DATA_UNCONFIRMED,
            )

        if not self._data_ready(bar):
            return self._reset_with_suppression(
                bar=bar,
                reason=TimingReason.DATA_INVALID,
                state=TimingState.DISABLED,
                keep_timestamp=False,
            )

        if self._last_timestamp_ms is not None and bar.timestamp_ms == self._last_timestamp_ms:
            return self._snapshot(
                bar=bar,
                data_valid=False,
                event=TimingEvent.NONE,
                reason=TimingReason.DATA_DUPLICATE_IGNORED,
            )

        if self._last_timestamp_ms is not None and bar.timestamp_ms < self._last_timestamp_ms:
            return self._reset_with_suppression(
                bar=bar,
                reason=TimingReason.DATA_NON_MONOTONIC,
                state=TimingState.DISABLED,
                keep_timestamp=False,
            )

        expected_ms = self.config.interval_seconds * 1000
        if (
            self._last_timestamp_ms is not None
            and bar.timestamp_ms - self._last_timestamp_ms != expected_ms
        ):
            return self._reset_with_suppression(
                bar=bar,
                reason=TimingReason.DATA_GAP_RESET,
                state=TimingState.WAIT_10M,
                keep_timestamp=True,
            )
        self._last_timestamp_ms = bar.timestamp_ms

        current = self._plan
        terminal_already_emitted = self._state == TimingState.LOCKED
        event_matches_current = self._event_matches_plan(current, primary_event_plan)
        old_invalidated = current is not None and not terminal_already_emitted and (
            self._invalidates(current, bar.close)
            or (event_matches_current and primary_event == PrimaryEvent.INVALIDATED)
        )
        old_target_reached = current is not None and not terminal_already_emitted and (
            self._target_reached(current, bar)
            or (event_matches_current and primary_event == PrimaryEvent.TARGET_REACHED)
        )

        # The old frozen plan always owns terminal arbitration on this 3m bar.
        # Invalidation precedes target; neither can be bypassed by a replacement.
        if old_invalidated and current is not None:
            return self._terminal(
                bar=bar,
                reason=TimingReason.OPPORTUNITY_INVALIDATED,
                event=self._invalidation_event(current.direction),
                marker_price=current.invalidation,
            )
        if old_target_reached and current is not None:
            return self._terminal(
                bar=bar,
                reason=TimingReason.OPPORTUNITY_TARGET_REACHED,
                event=self._target_event(current.direction),
                marker_price=current.next_named_level,
            )

        # R3 splits the entry-permission lifetime from entered-plan management.
        # ACTIVE_EXPIRED / active_plan=None / a different new plan cannot evict an
        # ENTERED plan.  Only target, invalidation, or a fail-closed data/host reset
        # above may release ownership.
        if self._state == TimingState.ENTERED and current is not None:
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=TimingReason.ENTERED_PLAN_MANAGEMENT,
            )

        if active_plan is None:
            if current is not None:
                self._suppressed_opportunity_id = current.opportunity_id
                old_id = current.opportunity_id
                old_direction = current.direction
                self._clear_runtime()
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=TimingEvent.NONE,
                    reason=TimingReason.OPPORTUNITY_ENDED,
                    opportunity_id_override=old_id,
                    direction_override=old_direction,
                )
            self._clear_runtime()
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=TimingReason.WAIT_10M,
            )

        # A terminal/consumed ID remains suppressed across gap, invalid, and
        # non-monotonic resets.  A genuinely different ID clears suppression.
        if (
            self._plan is None
            and active_plan.opportunity_id == self._suppressed_opportunity_id
        ):
            self._state = TimingState.WAIT_10M
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=TimingReason.OPPORTUNITY_SUPPRESSED,
                opportunity_id_override=active_plan.opportunity_id,
                direction_override=active_plan.direction,
            )

        is_new_plan = (
            self._plan is None
            or active_plan.opportunity_id != self._plan.opportunity_id
        )
        if is_new_plan:
            replaced = self._plan is not None
            self._suppressed_opportunity_id = None
            self._plan = active_plan
            self._state = TimingState.WAIT_PULLBACK
            self._frozen_trigger = None
            self._trigger_age = 0
            self._locked_reason = TimingReason.WAIT_10M
            if self._invalidates(active_plan, bar.close):
                return self._terminal(
                    bar=bar,
                    reason=TimingReason.OPPORTUNITY_INVALIDATED,
                    event=self._invalidation_event(active_plan.direction),
                    marker_price=active_plan.invalidation,
                )
            if self._target_reached(active_plan, bar):
                return self._terminal(
                    bar=bar,
                    reason=TimingReason.OPPORTUNITY_TARGET_REACHED,
                    event=self._target_event(active_plan.direction),
                    marker_price=active_plan.next_named_level,
                )
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=(
                    TimingReason.OPPORTUNITY_REPLACED
                    if replaced
                    else TimingReason.NEW_OPPORTUNITY
                ),
            )

        if self._plan is None:
            raise RuntimeError("same-plan timing branch lacks a plan")

        if self._state == TimingState.LOCKED:
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=self._locked_reason,
            )

        cloud_upper = max(bar.ema5, bar.ema12)
        cloud_lower = min(bar.ema5, bar.ema12)
        direction = self._plan.direction

        if self._state == TimingState.WAIT_PULLBACK:
            touch = (direction == Direction.LONG and bar.low <= cloud_upper) or (
                direction == Direction.SHORT and bar.high >= cloud_lower
            )
            if touch:
                self._frozen_trigger = (
                    bar.high if direction == Direction.LONG else bar.low
                )
                self._trigger_age = 0
                self._state = TimingState.WAIT_TRIGGER
                reason = TimingReason.PULLBACK_FROZEN
            else:
                reason = TimingReason.WAIT_PULLBACK
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=reason,
            )

        if self._state == TimingState.WAIT_TRIGGER:
            if self._frozen_trigger is None:
                raise RuntimeError("WAIT_TRIGGER is missing its frozen trigger")
            self._trigger_age += 1
            if self._trigger_age > self.config.max_trigger_bars:
                return self._terminal(
                    bar=bar,
                    reason=TimingReason.TRIGGER_EXPIRED,
                )

            fast_direction = (
                Direction.LONG
                if bar.ema5 > bar.ema12
                else Direction.SHORT
                if bar.ema5 < bar.ema12
                else Direction.NONE
            )
            entry = (
                direction == Direction.LONG
                and fast_direction == Direction.LONG
                and bar.close > self._frozen_trigger
                and bar.close > cloud_upper
            ) or (
                direction == Direction.SHORT
                and fast_direction == Direction.SHORT
                and bar.close < self._frozen_trigger
                and bar.close < cloud_lower
            )
            if entry:
                remaining_space_r = self._space_r_at_close(self._plan, bar.close)
                if remaining_space_r is None or remaining_space_r < self.config.minimum_space_r:
                    return self._terminal(
                        bar=bar,
                        reason=TimingReason.SPACE_LT_1R,
                    )
                self._suppressed_opportunity_id = self._plan.opportunity_id
                self._state = TimingState.ENTERED
                event = (
                    TimingEvent.LONG_ENTRY
                    if direction == Direction.LONG
                    else TimingEvent.SHORT_ENTRY
                )
                return self._snapshot(
                    bar=bar,
                    data_valid=True,
                    event=event,
                    reason=TimingReason.ENTRY_CONFIRMED,
                    marker_price=bar.close,
                )
            return self._snapshot(
                bar=bar,
                data_valid=True,
                event=TimingEvent.NONE,
                reason=TimingReason.WAIT_LATER_TRIGGER,
            )

        raise RuntimeError(f"unhandled timing state: {self._state}")

def run_primary(
    bars: Iterable[TenMinuteBar],
    config: PrimaryConfig | None = None,
) -> list[PrimaryObservation]:
    engine = PrimaryOpportunityEngine(config)
    return [engine.ingest(bar) for bar in bars]


TimingInput = (
    tuple[ThreeMinuteBar, OpportunityPlan | None]
    | tuple[ThreeMinuteBar, OpportunityPlan | None, PrimaryEvent]
    | tuple[
        ThreeMinuteBar,
        OpportunityPlan | None,
        PrimaryEvent,
        OpportunityPlan | None,
    ]
)


def run_timing(
    rows: Iterable[TimingInput],
    config: TimingConfig | None = None,
) -> list[TimingObservation]:
    engine = OpportunityTimingEngine(config)
    observations: list[TimingObservation] = []
    for row in rows:
        if len(row) == 2:
            bar, plan = row
            primary_event = PrimaryEvent.NONE
            primary_event_plan = None
        elif len(row) == 3:
            bar, plan, primary_event = row
            primary_event_plan = None
        else:
            bar, plan, primary_event, primary_event_plan = row
        observations.append(
            engine.ingest(bar, plan, primary_event, primary_event_plan)
        )
    return observations
