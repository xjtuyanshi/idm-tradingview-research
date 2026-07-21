#!/usr/bin/env python3
"""Independent, causal replay oracle for the IDM v11 clean engine.

This module intentionally does **not** import any v10 reducer, watch ledger, or
episode implementation.  A confirmed three-minute bar is evaluated directly:

``confirmed 10m context -> four direct setups -> arbitration -> frozen plan``

The four setup families are Trend Ignition, Cloud Pullback Continuation,
Compression/Structure Breakout, and Level Rejection.  Once a position exists,
the same reducer emits HOLD / PROTECT / EXIT guidance.  Every input bar receives
exactly one :class:`BarAction` and a human-readable reason.

This is a deterministic rule oracle, not a probability model.  ``A/B/C`` are
rule-completeness grades and must never be displayed as a win rate or used as an
automatic position-size recommendation.

Time convention
---------------
``Bar.confirmed_at`` is the instant the bar became confirmed (normally its
close time).  A ten-minute context snapshot is eligible only when
``snapshot.confirmed_at <= bar.confirmed_at``.  A future snapshot is never
consulted, including when it is supplied early in the input list.
"""

from __future__ import annotations

from bisect import bisect_right
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
import math
from os import PathLike
from typing import Iterable, Sequence


class Side(IntEnum):
    SHORT = -1
    FLAT = 0
    LONG = 1


class SetupType(str, Enum):
    LEVEL_REJECTION = "LEVEL_REJECTION"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"
    COMPRESSION_BREAKOUT = "COMPRESSION_BREAKOUT"
    TREND_IGNITION = "TREND_IGNITION"


class RuleGrade(str, Enum):
    X = "X"
    C = "C"
    B = "B"
    A = "A"


class BarAction(str, Enum):
    ENTER = "ENTER"
    HOLD = "HOLD"
    PROTECT = "PROTECT"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"
    EXIT = "EXIT"


class PlanEvent(str, Enum):
    NONE = "NONE"
    ENTRY = "ENTRY"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    STOP = "STOP"
    STRUCTURE_EXIT = "STRUCTURE_EXIT"
    OPPOSITE_EXIT = "OPPOSITE_EXIT"
    PACE_PROTECT = "PACE_PROTECT"
    CONTEXT_PROTECT = "CONTEXT_PROTECT"
    COUNTERTREND_ADVISORY = "COUNTERTREND_ADVISORY"


SETUP_PRIORITY: tuple[SetupType, ...] = (
    SetupType.LEVEL_REJECTION,
    SetupType.PULLBACK_CONTINUATION,
    SetupType.COMPRESSION_BREAKOUT,
    SetupType.TREND_IGNITION,
)

GRADE_PRIORITY = {
    RuleGrade.X: 0,
    RuleGrade.C: 1,
    RuleGrade.B: 2,
    RuleGrade.A: 3,
}


@dataclass(frozen=True, slots=True)
class Bar:
    """A confirmed market bar.

    Optional support/resistance fields let Pine parity fixtures supply the
    exact level pool known on that bar.  When omitted, the oracle derives a
    causal rolling high/low from bars that were already confirmed.
    """

    confirmed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 1.0
    support: float | None = None
    resistance: float | None = None


@dataclass(frozen=True, slots=True)
class Context10m:
    """A context snapshot whose values became available at ``confirmed_at``."""

    confirmed_at: datetime
    close: float
    ema5: float
    ema12: float
    ema34: float
    ema50: float

    @property
    def trend_side(self) -> Side:
        return _side_of(self.ema34 - self.ema50)

    @property
    def pace_side(self) -> Side:
        return _side_of(self.ema5 - self.ema12)


@dataclass(frozen=True, slots=True)
class EngineConfig:
    fast_length: int = 5
    slow_length: int = 12
    anchor_fast_length: int = 34
    anchor_slow_length: int = 50
    atr_length: int = 14
    breakout_lookback: int = 4
    compression_lookback: int = 8
    level_lookback: int = 20
    strong_body_fraction: float = 0.45
    close_edge_fraction: float = 0.32
    wick_fraction: float = 0.22
    breakout_epsilon_atr: float = 0.03
    level_tolerance_atr: float = 0.12
    compression_width_atr: float = 2.25
    no_chase_distance_atr: float = 0.35
    stop_buffer_atr: float = 0.10
    max_risk_atr: float = 1.30
    min_space_r: float = 0.55
    b_space_r: float = 0.75
    a_space_r: float = 1.00
    max_extension_atr: float = 1.00
    volume_expansion_ratio: float = 1.05

    def __post_init__(self) -> None:
        integer_fields = (
            self.fast_length,
            self.slow_length,
            self.anchor_fast_length,
            self.anchor_slow_length,
            self.atr_length,
            self.breakout_lookback,
            self.compression_lookback,
            self.level_lookback,
        )
        if any(value <= 0 for value in integer_fields):
            raise ValueError("all lookback lengths must be positive")
        if not (
            self.fast_length < self.slow_length
            and self.anchor_fast_length < self.anchor_slow_length
        ):
            raise ValueError("EMA fast lengths must be shorter than slow lengths")
        if self.max_risk_atr <= 0.0 or self.min_space_r <= 0.0:
            raise ValueError("risk and minimum-space limits must be positive")


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    bar_index: int
    ema_fast: float
    ema_slow: float
    ema_anchor_fast: float
    ema_anchor_slow: float
    atr: float
    volume_average: float
    support: float | None
    resistance: float | None
    ready: bool

    @property
    def fast_side(self) -> Side:
        return _side_of(self.ema_fast - self.ema_slow)

    @property
    def anchor_side(self) -> Side:
        return _side_of(self.ema_anchor_fast - self.ema_anchor_slow)

    @property
    def fast_low(self) -> float:
        return min(self.ema_fast, self.ema_slow)

    @property
    def fast_high(self) -> float:
        return max(self.ema_fast, self.ema_slow)

    @property
    def anchor_low(self) -> float:
        return min(self.ema_anchor_fast, self.ema_anchor_slow)

    @property
    def anchor_high(self) -> float:
        return max(self.ema_anchor_fast, self.ema_anchor_slow)


@dataclass(frozen=True, slots=True)
class Candidate:
    side: Side
    setup: SetupType
    grade: RuleGrade
    entry: float
    stop: float
    t1: float
    t2: float
    risk: float
    space_r: float
    context_aligned: bool
    countertrend: bool
    trigger_reason: str
    stop_basis: str
    blocker: str | None = None

    @property
    def tradable(self) -> bool:
        return self.blocker is None and self.grade != RuleGrade.X


@dataclass(frozen=True, slots=True)
class FrozenPlan:
    signal_id: int
    side: Side
    setup: SetupType
    grade: RuleGrade
    opened_bar_index: int
    entry: float
    initial_stop: float
    active_stop: float
    t1: float
    t2: float
    countertrend: bool
    t1_reached: bool = False
    t2_reached: bool = False
    active: bool = True


@dataclass(frozen=True, slots=True)
class BarDecision:
    bar_index: int
    confirmed_at: datetime
    action: BarAction
    reason: str
    event: PlanEvent
    event_side: Side
    context: Context10m | None
    features: FeatureSnapshot
    candidate: Candidate | None = None
    plan: FrozenPlan | None = None
    exit_price: float | None = None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    decisions: tuple[BarDecision, ...]

    @property
    def entries(self) -> tuple[BarDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.action == BarAction.ENTER
        )

    @property
    def exits(self) -> tuple[BarDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.action == BarAction.EXIT
        )


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    bars: int
    enter_long: int
    enter_short: int
    holds: int
    protects: int
    waits: int
    blocked: int
    exits: int
    event_lines: tuple[str, ...]

    @property
    def compact(self) -> str:
        counts = (
            f"bars={self.bars} long={self.enter_long} short={self.enter_short} "
            f"hold={self.holds} protect={self.protects} exit={self.exits} "
            f"blocked={self.blocked} wait={self.waits}"
        )
        if not self.event_lines:
            return counts
        return counts + " | events: " + " ; ".join(self.event_lines)


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    side: Side
    setup: SetupType
    stop_anchor: float
    trigger_reason: str
    stop_basis: str


def _side_of(value: float, epsilon: float = 1e-12) -> Side:
    if value > epsilon:
        return Side.LONG
    if value < -epsilon:
        return Side.SHORT
    return Side.FLAT


def _ema(previous: float | None, value: float, length: int) -> float:
    if previous is None:
        return value
    alpha = 2.0 / (length + 1.0)
    return previous + alpha * (value - previous)


def _validate_bar(bar: Bar) -> None:
    prices = (bar.open, bar.high, bar.low, bar.close)
    if not all(math.isfinite(value) for value in prices):
        raise ValueError("bar prices must be finite")
    if bar.low > bar.high:
        raise ValueError("bar low cannot exceed high")
    if not bar.low <= bar.open <= bar.high:
        raise ValueError("bar open must be inside the bar range")
    if not bar.low <= bar.close <= bar.high:
        raise ValueError("bar close must be inside the bar range")
    if not math.isfinite(bar.volume) or bar.volume < 0:
        raise ValueError("bar volume must be finite and non-negative")


class ConfirmedContextIndex:
    """Causal lookup for confirmed ten-minute context snapshots."""

    def __init__(self, snapshots: Iterable[Context10m]) -> None:
        ordered = sorted(snapshots, key=lambda item: item.confirmed_at)
        times = [item.confirmed_at for item in ordered]
        if len(set(times)) != len(times):
            raise ValueError("10m context confirmation times must be unique")
        self._snapshots = tuple(ordered)
        self._times = tuple(times)

    def at(self, confirmed_at: datetime) -> Context10m | None:
        position = bisect_right(self._times, confirmed_at) - 1
        if position < 0:
            return None
        snapshot = self._snapshots[position]
        # Keep the causal invariant explicit even though bisect already implies it.
        if snapshot.confirmed_at > confirmed_at:
            raise AssertionError("future 10m context escaped the causal lookup")
        return snapshot


def build_confirmed_10m_contexts(
    bars: Sequence[Bar],
    *,
    fast_length: int = 5,
    slow_length: int = 12,
    anchor_fast_length: int = 34,
    anchor_slow_length: int = 50,
) -> tuple[Context10m, ...]:
    """Build EMA snapshots from already-confirmed 10m bars.

    The helper never shifts a value backward.  The output snapshot carries the
    exact confirmation timestamp of its source bar.
    """

    if not bars:
        return ()
    previous_time: datetime | None = None
    ema5 = ema12 = ema34 = ema50 = None
    result: list[Context10m] = []
    for bar in bars:
        _validate_bar(bar)
        if previous_time is not None and bar.confirmed_at <= previous_time:
            raise ValueError("10m bars must be strictly time ordered")
        previous_time = bar.confirmed_at
        ema_source = (bar.high + bar.low) / 2.0
        ema5 = _ema(ema5, ema_source, fast_length)
        ema12 = _ema(ema12, ema_source, slow_length)
        ema34 = _ema(ema34, ema_source, anchor_fast_length)
        ema50 = _ema(ema50, ema_source, anchor_slow_length)
        result.append(
            Context10m(
                confirmed_at=bar.confirmed_at,
                close=bar.close,
                ema5=ema5,
                ema12=ema12,
                ema34=ema34,
                ema50=ema50,
            )
        )
    return tuple(result)


class V11ReplayOracle:
    """Stateful, direct-trigger IDM v11 replay reducer."""

    def __init__(
        self,
        contexts_10m: Iterable[Context10m],
        config: EngineConfig | None = None,
    ) -> None:
        self.config = config or EngineConfig()
        self.contexts = ConfirmedContextIndex(contexts_10m)
        self._bars: list[Bar] = []
        self._features: list[FeatureSnapshot] = []
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._ema_anchor_fast: float | None = None
        self._ema_anchor_slow: float | None = None
        self._atr: float | None = None
        self._plan: FrozenPlan | None = None
        self._next_signal_id = 1

    @property
    def active_plan(self) -> FrozenPlan | None:
        return self._plan

    def replay(self, bars: Iterable[Bar]) -> ReplayResult:
        decisions = [self.process(bar) for bar in bars]
        return ReplayResult(tuple(decisions))

    def process(self, bar: Bar) -> BarDecision:
        _validate_bar(bar)
        if self._bars and bar.confirmed_at <= self._bars[-1].confirmed_at:
            raise ValueError("3m bars must be strictly time ordered")

        index = len(self._bars)
        feature = self._update_features(bar, index)
        context = self.contexts.at(bar.confirmed_at)
        raw_candidates = self._detect_raw_candidates(bar, feature)
        candidates = tuple(
            self._complete_candidate(raw, bar, feature, context)
            for raw in raw_candidates
        )
        candidate = self._arbitrate(candidates)

        if self._plan is not None and self._plan.active:
            decision = self._manage_position(
                bar, feature, context, candidate, self._plan
            )
        elif candidate is not None and candidate.tradable:
            plan = FrozenPlan(
                signal_id=self._next_signal_id,
                side=candidate.side,
                setup=candidate.setup,
                grade=candidate.grade,
                opened_bar_index=index,
                entry=candidate.entry,
                initial_stop=candidate.stop,
                active_stop=candidate.stop,
                t1=candidate.t1,
                t2=candidate.t2,
                countertrend=candidate.countertrend,
            )
            self._next_signal_id += 1
            self._plan = plan
            decision = BarDecision(
                bar_index=index,
                confirmed_at=bar.confirmed_at,
                action=BarAction.ENTER,
                reason=(
                    f"{candidate.side.name} {candidate.setup.value} "
                    f"grade {candidate.grade.value}: {candidate.trigger_reason}"
                ),
                event=PlanEvent.ENTRY,
                event_side=candidate.side,
                context=context,
                features=feature,
                candidate=candidate,
                plan=plan,
            )
        elif candidate is not None:
            decision = BarDecision(
                bar_index=index,
                confirmed_at=bar.confirmed_at,
                action=BarAction.BLOCKED,
                reason=(
                    f"{candidate.side.name} {candidate.setup.value} blocked: "
                    f"{candidate.blocker or 'RULE_GRADE_X'}"
                ),
                event=PlanEvent.NONE,
                event_side=Side.FLAT,
                context=context,
                features=feature,
                candidate=candidate,
            )
        else:
            decision = BarDecision(
                bar_index=index,
                confirmed_at=bar.confirmed_at,
                action=BarAction.WAIT,
                reason=self._wait_reason(bar, feature, context),
                event=PlanEvent.NONE,
                event_side=Side.FLAT,
                context=context,
                features=feature,
            )

        self._bars.append(bar)
        self._features.append(feature)
        return decision

    def _update_features(self, bar: Bar, index: int) -> FeatureSnapshot:
        cfg = self.config
        previous_close = self._bars[-1].close if self._bars else bar.close
        true_range = max(
            bar.high - bar.low,
            abs(bar.high - previous_close),
            abs(bar.low - previous_close),
        )
        ema_source = (bar.high + bar.low) / 2.0
        self._ema_fast = _ema(self._ema_fast, ema_source, cfg.fast_length)
        self._ema_slow = _ema(self._ema_slow, ema_source, cfg.slow_length)
        self._ema_anchor_fast = _ema(
            self._ema_anchor_fast, ema_source, cfg.anchor_fast_length
        )
        self._ema_anchor_slow = _ema(
            self._ema_anchor_slow, ema_source, cfg.anchor_slow_length
        )
        if self._atr is None:
            self._atr = true_range
        else:
            self._atr += (true_range - self._atr) / cfg.atr_length

        prior_level_bars = self._bars[-cfg.level_lookback :]
        derived_support = (
            min(item.low for item in prior_level_bars)
            if prior_level_bars
            else None
        )
        derived_resistance = (
            max(item.high for item in prior_level_bars)
            if prior_level_bars
            else None
        )
        volume_bars = self._bars[-cfg.level_lookback :]
        volume_average = (
            sum(item.volume for item in volume_bars) / len(volume_bars)
            if volume_bars
            else max(bar.volume, 1.0)
        )
        ready_after = max(
            cfg.anchor_slow_length,
            cfg.atr_length,
            cfg.breakout_lookback + 1,
        )
        return FeatureSnapshot(
            bar_index=index,
            ema_fast=self._ema_fast,
            ema_slow=self._ema_slow,
            ema_anchor_fast=self._ema_anchor_fast,
            ema_anchor_slow=self._ema_anchor_slow,
            atr=max(self._atr, 1e-9),
            volume_average=max(volume_average, 1e-9),
            support=bar.support if bar.support is not None else derived_support,
            resistance=(
                bar.resistance
                if bar.resistance is not None
                else derived_resistance
            ),
            ready=index + 1 >= ready_after,
        )

    def _detect_raw_candidates(
        self, bar: Bar, feature: FeatureSnapshot
    ) -> tuple[_RawCandidate, ...]:
        if not feature.ready or not self._bars or not self._features:
            return ()
        cfg = self.config
        previous = self._bars[-1]
        previous_feature = self._features[-1]
        atr = feature.atr
        eps = atr * cfg.breakout_epsilon_atr
        tolerance = atr * cfg.level_tolerance_atr
        bar_range = max(bar.high - bar.low, 1e-9)
        body_fraction = abs(bar.close - bar.open) / bar_range
        bull_strong = (
            bar.close > bar.open
            and body_fraction >= cfg.strong_body_fraction
            and (bar.high - bar.close) / bar_range <= cfg.close_edge_fraction
        )
        bear_strong = (
            bar.close < bar.open
            and body_fraction >= cfg.strong_body_fraction
            and (bar.close - bar.low) / bar_range <= cfg.close_edge_fraction
        )
        lower_wick = (min(bar.open, bar.close) - bar.low) / bar_range
        upper_wick = (bar.high - max(bar.open, bar.close)) / bar_range
        candidates: list[_RawCandidate] = []

        # 1. Level rejection: support can only produce LONG; resistance only SHORT.
        support = feature.support
        resistance = feature.resistance
        if support is not None:
            support_touch = bar.low <= support + tolerance
            support_reclaim = bar.close > support + eps
            prior_support_tests = sum(
                item.low <= support + tolerance and item.close >= support - tolerance
                for item in self._bars[-4:]
            )
            immediate = (
                support_touch
                and support_reclaim
                and bull_strong
                and lower_wick >= cfg.wick_fraction
            )
            confirmed_repeat = (
                prior_support_tests >= 2
                and bar.close > previous.high + eps
                and bull_strong
            )
            if immediate or confirmed_repeat:
                candidates.append(
                    _RawCandidate(
                        Side.LONG,
                        SetupType.LEVEL_REJECTION,
                        bar.low - cfg.stop_buffer_atr * atr,
                        "support rejected and reclaimed",
                        "LEVEL_SWEEP_LOW",
                    )
                )
        if resistance is not None:
            resistance_touch = bar.high >= resistance - tolerance
            resistance_reclaim = bar.close < resistance - eps
            prior_resistance_tests = sum(
                item.high >= resistance - tolerance
                and item.close <= resistance + tolerance
                for item in self._bars[-4:]
            )
            immediate = (
                resistance_touch
                and resistance_reclaim
                and bear_strong
                and upper_wick >= cfg.wick_fraction
            )
            confirmed_repeat = (
                prior_resistance_tests >= 2
                and bar.close < previous.low - eps
                and bear_strong
            )
            if immediate or confirmed_repeat:
                candidates.append(
                    _RawCandidate(
                        Side.SHORT,
                        SetupType.LEVEL_REJECTION,
                        bar.high + cfg.stop_buffer_atr * atr,
                        "resistance rejected and lost",
                        "LEVEL_SWEEP_HIGH",
                    )
                )

        # 2. Cloud pullback: a same-bar rejection or a next-bar break confirms it.
        long_touch_now = (
            bar.low <= feature.fast_high + tolerance
            and bar.close > feature.fast_high + eps
        ) or (
            bar.low <= feature.anchor_high + tolerance
            and bar.close > feature.anchor_high + eps
        )
        short_touch_now = (
            bar.high >= feature.fast_low - tolerance
            and bar.close < feature.fast_low - eps
        ) or (
            bar.high >= feature.anchor_low - tolerance
            and bar.close < feature.anchor_low - eps
        )
        # A valid pullback can take two or three bars to test the Cloud.  The
        # former implementation inspected exactly ``[-2]`` and therefore
        # forgot an established trend as soon as the test lasted more than one
        # bar (the real 2026-07-21 10:42 and 11:06 reclaims are examples).
        # Search only already-confirmed bars *before* the test bar; this widens
        # the causal memory without consulting the current or future bar.
        established_pairs = tuple(
            zip(self._bars[-4:-1], self._features[-4:-1])
        )
        established_long_before = any(
            item.close > item_feature.fast_high + tolerance
            for item, item_feature in established_pairs
        )
        established_short_before = any(
            item.close < item_feature.fast_low - tolerance
            for item, item_feature in established_pairs
        )
        long_touch_previous = established_long_before and (
            previous.low <= previous_feature.fast_high + tolerance
            or previous.low <= previous_feature.anchor_high + tolerance
        )
        short_touch_previous = established_short_before and (
            previous.high >= previous_feature.fast_low - tolerance
            or previous.high >= previous_feature.anchor_low - tolerance
        )
        long_same_bar_confirm = (
            long_touch_now
            and bull_strong
            and lower_wick >= cfg.wick_fraction
        )
        long_next_bar_confirm = (
            long_touch_previous
            and bull_strong
            and bar.close > previous.high + eps
        )
        short_same_bar_confirm = (
            short_touch_now
            and bear_strong
            and upper_wick >= cfg.wick_fraction
        )
        short_next_bar_confirm = (
            short_touch_previous
            and bear_strong
            and bar.close < previous.low - eps
        )
        if feature.fast_side == Side.LONG and (
            long_same_bar_confirm or long_next_bar_confirm
        ):
            pullback_test_low = (
                bar.low
                if long_same_bar_confirm
                else max(previous.low, bar.low)
            )
            candidates.append(
                _RawCandidate(
                    Side.LONG,
                    SetupType.PULLBACK_CONTINUATION,
                    pullback_test_low - cfg.stop_buffer_atr * atr,
                    "bullish Cloud pullback reclaimed",
                    (
                        "PULLBACK_REJECTION_LOW"
                        if long_same_bar_confirm
                        else "PULLBACK_CONFIRM_LOW"
                    ),
                )
            )
        if feature.fast_side == Side.SHORT and (
            short_same_bar_confirm or short_next_bar_confirm
        ):
            pullback_test_high = (
                bar.high
                if short_same_bar_confirm
                else min(previous.high, bar.high)
            )
            candidates.append(
                _RawCandidate(
                    Side.SHORT,
                    SetupType.PULLBACK_CONTINUATION,
                    pullback_test_high + cfg.stop_buffer_atr * atr,
                    "bearish Cloud pullback rejected",
                    (
                        "PULLBACK_REJECTION_HIGH"
                        if short_same_bar_confirm
                        else "PULLBACK_CONFIRM_HIGH"
                    ),
                )
            )

        # 3. Compression/structure breakout.  The prior box never includes the
        # current trigger bar, so a close cannot retroactively change its gate.
        compression_bars = self._bars[-cfg.compression_lookback :]
        breakout_bars = self._bars[-cfg.breakout_lookback :]
        if len(compression_bars) >= cfg.compression_lookback:
            box_high = max(item.high for item in compression_bars)
            box_low = min(item.low for item in compression_bars)
            compressed = box_high - box_low <= cfg.compression_width_atr * atr
            recent_high = max(item.high for item in breakout_bars)
            recent_low = min(item.low for item in breakout_bars)
            if (
                compressed
                and feature.fast_side == Side.LONG
                and bull_strong
                and bar.close > recent_high + eps
            ):
                candidates.append(
                    _RawCandidate(
                        Side.LONG,
                        SetupType.COMPRESSION_BREAKOUT,
                        max(bar.low, recent_high)
                        - cfg.stop_buffer_atr * atr,
                        "confirmed close above prior compression box",
                        "BREAKOUT_BOX_HIGH",
                    )
                )
            if (
                compressed
                and feature.fast_side == Side.SHORT
                and bear_strong
                and bar.close < recent_low - eps
            ):
                candidates.append(
                    _RawCandidate(
                        Side.SHORT,
                        SetupType.COMPRESSION_BREAKOUT,
                        min(bar.high, recent_low)
                        + cfg.stop_buffer_atr * atr,
                        "confirmed close below prior compression box",
                        "BREAKOUT_BOX_LOW",
                    )
                )

        # 4. Trend ignition: current-bar 5/12 cross or 34/50 reclaim plus a
        # causal break of the previous structure window.
        breakout_bars = self._bars[-cfg.breakout_lookback :]
        previous_high = max(item.high for item in breakout_bars)
        previous_low = min(item.low for item in breakout_bars)
        cross_long = (
            previous_feature.ema_fast <= previous_feature.ema_slow
            and feature.ema_fast > feature.ema_slow
        )
        cross_short = (
            previous_feature.ema_fast >= previous_feature.ema_slow
            and feature.ema_fast < feature.ema_slow
        )
        anchor_reclaim_long = (
            previous.close <= previous_feature.anchor_high
            and bar.close > feature.anchor_high + eps
        )
        anchor_reclaim_short = (
            previous.close >= previous_feature.anchor_low
            and bar.close < feature.anchor_low - eps
        )
        if (
            (cross_long or anchor_reclaim_long)
            and bull_strong
            and bar.close > previous_high + eps
        ):
            candidates.append(
                _RawCandidate(
                    Side.LONG,
                    SetupType.TREND_IGNITION,
                    max(
                        bar.low,
                        feature.anchor_high
                        if anchor_reclaim_long
                        else bar.low,
                    )
                    - cfg.stop_buffer_atr * atr,
                    "5/12 or anchor reclaimed with structure break",
                    (
                        "IGNITION_ANCHOR_RECLAIM"
                        if anchor_reclaim_long
                        else "IGNITION_SIGNAL_LOW"
                    ),
                )
            )
        if (
            (cross_short or anchor_reclaim_short)
            and bear_strong
            and bar.close < previous_low - eps
        ):
            candidates.append(
                _RawCandidate(
                    Side.SHORT,
                    SetupType.TREND_IGNITION,
                    min(
                        bar.high,
                        feature.anchor_low
                        if anchor_reclaim_short
                        else bar.high,
                    )
                    + cfg.stop_buffer_atr * atr,
                    "5/12 or anchor lost with structure break",
                    (
                        "IGNITION_ANCHOR_RECLAIM"
                        if anchor_reclaim_short
                        else "IGNITION_SIGNAL_HIGH"
                    ),
                )
            )
        return tuple(candidates)

    def _complete_candidate(
        self,
        raw: _RawCandidate,
        bar: Bar,
        feature: FeatureSnapshot,
        context: Context10m | None,
    ) -> Candidate:
        cfg = self.config
        entry = bar.close
        stop = raw.stop_anchor
        risk = (entry - stop) * int(raw.side)
        blocker: str | None = None

        if context is None:
            blocker = "NO_CONFIRMED_10M_CONTEXT"
        elif risk <= 0.0:
            blocker = "STOP_WRONG_SIDE"
        elif risk > cfg.max_risk_atr * feature.atr:
            blocker = "RISK_EXCEEDS_1.30_ATR"

        support = feature.support
        resistance = feature.resistance
        no_chase = cfg.no_chase_distance_atr * feature.atr
        eps = cfg.breakout_epsilon_atr * feature.atr
        if blocker is None and raw.side == Side.LONG and resistance is not None:
            if entry < resistance and resistance - entry <= no_chase:
                blocker = "LONG_INTO_RESISTANCE"
        if blocker is None and raw.side == Side.SHORT and support is not None:
            if entry > support and entry - support <= no_chase:
                blocker = "SHORT_INTO_SUPPORT"

        context_side = context.trend_side if context is not None else Side.FLAT
        context_pace = context.pace_side if context is not None else Side.FLAT
        context_aligned = (
            context_side == raw.side and context_pace in (raw.side, Side.FLAT)
        )
        countertrend = context_side == Side(-int(raw.side))
        if (
            blocker is None
            and context_side == Side(-int(raw.side))
            and raw.setup != SetupType.LEVEL_REJECTION
        ):
            blocker = "OPPOSITE_10M_CONTEXT"

        if risk <= 0.0:
            # Finite placeholder geometry keeps blocked candidates inspectable.
            risk = max(feature.atr, 1e-9)
        one_r_target = entry + int(raw.side) * risk
        obstacle: float | None = None
        if raw.side == Side.LONG and resistance is not None:
            if resistance > entry + eps:
                obstacle = resistance
        elif raw.side == Side.SHORT and support is not None:
            if support < entry - eps:
                obstacle = support
        if obstacle is None:
            t1 = one_r_target
        elif raw.side == Side.LONG:
            t1 = min(one_r_target, obstacle)
        else:
            t1 = max(one_r_target, obstacle)
        space_r = ((t1 - entry) * int(raw.side)) / risk
        t2 = entry + int(raw.side) * 2.0 * risk

        if blocker is None and space_r < cfg.min_space_r:
            blocker = "TARGET_SPACE_BELOW_0.55R"

        extension = (
            max(0.0, entry - feature.anchor_high)
            if raw.side == Side.LONG
            else max(0.0, feature.anchor_low - entry)
        ) / feature.atr
        volume_expanded = bar.volume >= (
            cfg.volume_expansion_ratio * feature.volume_average
        )
        extra_evidence = raw.setup in (
            SetupType.LEVEL_REJECTION,
            SetupType.PULLBACK_CONTINUATION,
        ) or volume_expanded

        if blocker is not None:
            grade = RuleGrade.X
        elif (
            context_aligned
            and feature.fast_side == raw.side
            and feature.anchor_side in (raw.side, Side.FLAT)
            and extension <= cfg.max_extension_atr
            and space_r >= cfg.a_space_r
            and extra_evidence
        ):
            grade = RuleGrade.A
        elif (
            context_side in (raw.side, Side.FLAT)
            and space_r >= cfg.b_space_r
        ):
            grade = RuleGrade.B
        elif (
            context_side in (raw.side, Side.FLAT)
            and space_r >= cfg.min_space_r
        ):
            grade = RuleGrade.C
        elif (
            raw.setup == SetupType.LEVEL_REJECTION
            and space_r >= cfg.min_space_r
        ):
            grade = RuleGrade.C
        else:
            grade = RuleGrade.X
            blocker = "RULE_COMPLETENESS_BELOW_C"

        return Candidate(
            side=raw.side,
            setup=raw.setup,
            grade=grade,
            entry=entry,
            stop=stop,
            t1=t1,
            t2=t2,
            risk=risk,
            space_r=space_r,
            context_aligned=context_aligned,
            countertrend=countertrend,
            trigger_reason=raw.trigger_reason,
            stop_basis=raw.stop_basis,
            blocker=blocker,
        )

    def _arbitrate(self, candidates: Sequence[Candidate]) -> Candidate | None:
        if not candidates:
            return None
        setup_rank = {
            setup: len(SETUP_PRIORITY) - index
            for index, setup in enumerate(SETUP_PRIORITY)
        }
        return max(
            candidates,
            key=lambda candidate: (
                int(candidate.tradable),
                GRADE_PRIORITY[candidate.grade],
                setup_rank[candidate.setup],
                int(candidate.context_aligned),
                candidate.space_r,
                int(candidate.side),
            ),
        )

    def _manage_position(
        self,
        bar: Bar,
        feature: FeatureSnapshot,
        context: Context10m | None,
        candidate: Candidate | None,
        plan: FrozenPlan,
    ) -> BarDecision:
        index = feature.bar_index
        eligible = index > plan.opened_bar_index
        long_plan = plan.side == Side.LONG
        stop_hit = eligible and (
            bar.low <= plan.active_stop if long_plan else bar.high >= plan.active_stop
        )
        t1_hit = eligible and not plan.t1_reached and (
            bar.high >= plan.t1 if long_plan else bar.low <= plan.t1
        )
        t2_hit = eligible and not plan.t2_reached and (
            bar.high >= plan.t2 if long_plan else bar.low <= plan.t2
        )

        # Conservative order is deliberate when intrabar sequencing is absent.
        if stop_hit:
            return self._close_decision(
                bar,
                feature,
                context,
                candidate,
                plan,
                PlanEvent.STOP,
                plan.active_stop,
                "active stop touched; stop-first used for an ambiguous bar",
            )
        if t2_hit:
            context_side = context.trend_side if context is not None else Side.FLAT
            trend_runner_intact = (
                context_side == plan.side and feature.fast_side == plan.side
            )
            if trend_runner_intact:
                protected = replace(
                    plan,
                    t1_reached=True,
                    t2_reached=True,
                    active_stop=(
                        max(plan.active_stop, plan.t1)
                        if long_plan
                        else min(plan.active_stop, plan.t1)
                    ),
                )
                self._plan = protected
                return BarDecision(
                    index,
                    bar.confirmed_at,
                    BarAction.PROTECT,
                    "T2 reached; confirmed 10m and 3m trend remain aligned, "
                    "so keep a protected context runner instead of returning to WAIT",
                    PlanEvent.TARGET_2,
                    plan.side,
                    context,
                    feature,
                    candidate,
                    protected,
                )
            return self._close_decision(
                bar,
                feature,
                context,
                candidate,
                plan,
                PlanEvent.TARGET_2,
                plan.t2,
                "T2 reached; runner closed",
            )
        if t1_hit:
            protected = replace(
                plan,
                t1_reached=True,
                active_stop=plan.entry,
            )
            self._plan = protected
            return BarDecision(
                index,
                bar.confirmed_at,
                BarAction.PROTECT,
                "T1 reached; initial geometry remains frozen and active stop moves to entry",
                PlanEvent.TARGET_1,
                plan.side,
                context,
                feature,
                candidate,
                protected,
            )

        opposite_candidate = (
            candidate is not None
            and candidate.tradable
            and candidate.side == Side(-int(plan.side))
        )
        if eligible and opposite_candidate:
            if candidate.countertrend:
                return BarDecision(
                    index,
                    bar.confirmed_at,
                    BarAction.PROTECT,
                    "opposite countertrend C probe is visible as a risk advisory; "
                    "the aligned trend plan is not auto-reversed",
                    PlanEvent.COUNTERTREND_ADVISORY,
                    plan.side,
                    context,
                    feature,
                    candidate,
                    plan,
                )
            return self._close_decision(
                bar,
                feature,
                context,
                candidate,
                plan,
                PlanEvent.OPPOSITE_EXIT,
                bar.close,
                (
                    f"opposite countertrend {candidate.setup.value} probe "
                    "confirmed; close the old plan but do not present it as "
                    "a trend reversal"
                    if candidate.countertrend
                    else f"opposite {candidate.setup.value} confirmed; "
                    "no same-bar reversal"
                ),
            )

        context_side = context.trend_side if context is not None else Side.FLAT
        pace_lost = feature.fast_side == Side(-int(plan.side))
        context_lost = context_side == Side(-int(plan.side))
        complete_anchor_break = (
            bar.close < feature.anchor_low
            if long_plan
            else bar.close > feature.anchor_high
        )
        prior_structure = self._bars[-self.config.breakout_lookback :]
        structure_broken = False
        if prior_structure:
            structure_broken = (
                bar.close < min(item.low for item in prior_structure)
                if long_plan
                else bar.close > max(item.high for item in prior_structure)
            )
        if eligible and complete_anchor_break and structure_broken:
            return self._close_decision(
                bar,
                feature,
                context,
                candidate,
                plan,
                PlanEvent.STRUCTURE_EXIT,
                bar.close,
                "complete 34/50 damage plus adverse structure break",
            )
        if eligible and (pace_lost or context_lost):
            event = (
                PlanEvent.PACE_PROTECT
                if pace_lost
                else PlanEvent.CONTEXT_PROTECT
            )
            reason = (
                "5/12 pace turned against the plan; protect, do not auto-reverse"
                if pace_lost
                else "confirmed 10m context turned against the plan; protect"
            )
            return BarDecision(
                index,
                bar.confirmed_at,
                BarAction.PROTECT,
                reason,
                event,
                plan.side,
                context,
                feature,
                candidate,
                plan,
            )

        same_side_note = ""
        if candidate is not None and candidate.tradable and candidate.side == plan.side:
            route = "countertrend probe" if candidate.countertrend else "trend route"
            same_side_note = (
                f"; fresh {candidate.setup.value} {route} observed "
                "(visible ADD reference; frozen plan unchanged)"
            )
        return BarDecision(
            index,
            bar.confirmed_at,
            BarAction.HOLD,
            f"plan structure and stop remain intact{same_side_note}",
            PlanEvent.NONE,
            plan.side,
            context,
            feature,
            candidate,
            plan,
        )

    def _close_decision(
        self,
        bar: Bar,
        feature: FeatureSnapshot,
        context: Context10m | None,
        candidate: Candidate | None,
        plan: FrozenPlan,
        event: PlanEvent,
        exit_price: float,
        reason: str,
    ) -> BarDecision:
        closed = replace(plan, active=False)
        self._plan = None
        return BarDecision(
            feature.bar_index,
            bar.confirmed_at,
            BarAction.EXIT,
            reason,
            event,
            plan.side,
            context,
            feature,
            candidate,
            closed,
            exit_price,
        )

    def _wait_reason(
        self,
        bar: Bar,
        feature: FeatureSnapshot,
        context: Context10m | None,
    ) -> str:
        if not feature.ready:
            return "indicator warm-up; no setup can be evaluated yet"
        if context is None:
            return "no confirmed 10m context yet"
        support_text = (
            f"support {feature.support:.2f}"
            if feature.support is not None
            else "no support"
        )
        resistance_text = (
            f"resistance {feature.resistance:.2f}"
            if feature.resistance is not None
            else "no resistance"
        )
        side = feature.fast_side.name
        return (
            f"no direct trigger on this close; 3m pace {side}, "
            f"{support_text}, {resistance_text}"
        )


def replay_v11(
    bars_3m: Iterable[Bar],
    contexts_10m: Iterable[Context10m],
    config: EngineConfig | None = None,
) -> ReplayResult:
    """Convenience function for a one-shot deterministic replay."""

    return V11ReplayOracle(contexts_10m, config).replay(bars_3m)


def load_tradingview_ohlc_csv(
    path: str | PathLike[str],
    *,
    timeframe_minutes: int,
) -> tuple[Bar, ...]:
    """Load TradingView OHLC export rows using causal close timestamps.

    TradingView's exported ``time`` field denotes the bar's *opening* Unix
    timestamp.  The oracle consumes confirmed bars, so this loader adds the
    timeframe duration.  Indicator columns may be present and are ignored.
    Exports without volume are valid and receive a neutral volume of ``1``.
    """

    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    required = ("time", "open", "high", "low", "close")
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("TradingView CSV has no header")
        missing = [name for name in required if name not in reader.fieldnames]
        if missing:
            raise ValueError(
                "TradingView CSV missing columns: " + ", ".join(missing)
            )
        for row_number, row in enumerate(reader, start=2):
            # Some TradingView exports repeat a header after a symbol reload.
            if row.get("time", "").strip().lower() == "time":
                continue
            try:
                open_at = datetime.fromtimestamp(
                    int(float(row["time"])), timezone.utc
                )
                confirmed_at = open_at + timedelta(minutes=timeframe_minutes)
                volume_text = (
                    row.get("volume")
                    or row.get("Volume")
                    or row.get("成交量")
                    or "1"
                )
                bar = Bar(
                    confirmed_at=confirmed_at,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(volume_text),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"invalid TradingView OHLC row {row_number}: {error}"
                ) from error
            _validate_bar(bar)
            if bars and bar.confirmed_at <= bars[-1].confirmed_at:
                raise ValueError(
                    f"TradingView rows are not strictly ordered at row {row_number}"
                )
            bars.append(bar)
    return tuple(bars)


def count_legacy_formal_signals(
    path: str | PathLike[str],
) -> int:
    """Count historical v10 A/B/C BUY/SELL markers in an exported CSV."""

    columns = (
        "历史买入 A",
        "历史买入 B",
        "历史买入 C",
        "历史卖出 A",
        "历史卖出 B",
        "历史卖出 C",
    )
    total = 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("TradingView CSV has no header")
        missing = [name for name in columns if name not in reader.fieldnames]
        if missing:
            raise ValueError(
                "legacy signal columns missing: " + ", ".join(missing)
            )
        for row_number, row in enumerate(reader, start=2):
            if row.get("time", "").strip().lower() == "time":
                continue
            try:
                total += sum(
                    1
                    for name in columns
                    if abs(float(row.get(name) or 0.0)) > 1e-12
                )
            except ValueError as error:
                raise ValueError(
                    f"invalid legacy signal value at row {row_number}"
                ) from error
    return total


def summarize_replay(
    result: ReplayResult,
    *,
    max_event_lines: int = 24,
) -> ReplaySummary:
    """Create a compact diagnostic suitable for reports and test failures."""

    if max_event_lines < 0:
        raise ValueError("max_event_lines cannot be negative")
    decisions = result.decisions
    lines: list[str] = []
    for decision in decisions:
        if decision.action == BarAction.WAIT:
            continue
        candidate = decision.candidate
        setup = candidate.setup.value if candidate is not None else "-"
        grade = candidate.grade.value if candidate is not None else "-"
        lines.append(
            f"{decision.confirmed_at.isoformat()} {decision.action.value} "
            f"{decision.event_side.name} {setup}/{grade} {decision.event.value}"
        )
        if len(lines) >= max_event_lines:
            break
    return ReplaySummary(
        bars=len(decisions),
        enter_long=sum(
            decision.action == BarAction.ENTER
            and decision.event_side == Side.LONG
            for decision in decisions
        ),
        enter_short=sum(
            decision.action == BarAction.ENTER
            and decision.event_side == Side.SHORT
            for decision in decisions
        ),
        holds=sum(decision.action == BarAction.HOLD for decision in decisions),
        protects=sum(
            decision.action == BarAction.PROTECT for decision in decisions
        ),
        waits=sum(decision.action == BarAction.WAIT for decision in decisions),
        blocked=sum(
            decision.action == BarAction.BLOCKED for decision in decisions
        ),
        exits=sum(decision.action == BarAction.EXIT for decision in decisions),
        event_lines=tuple(lines),
    )
