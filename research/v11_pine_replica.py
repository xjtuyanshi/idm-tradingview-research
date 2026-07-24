#!/usr/bin/env python3
"""Bar-by-bar Python replica of the frozen IDM v11 Pine engine.

Purpose
-------
``v11_oracle.py`` is a *causal opportunity* study engine and is intentionally
preserved unchanged.  It is **not** a replica of the frozen Pine release: the
2026-07-21 takeover audit (research/reports/IDM_V11_TAKEOVER_AUDIT_2026-07-21.md)
lists 24 semantic differences.  This module is the parity artifact: it follows
``intraday_decision_map_v11_aggressive_clean.pine`` (release 11.0.0-clean)
line by line.  Where this file and the Pine disagree, the Pine is right and
this file must be fixed — never the other way around.

Every rule constant comes from ``research/config/v11_contract.json``
(contract_version 1).  Deliberate rule improvements do not belong here.

Pine references below use ``pine:N`` for line N of the frozen source.

Semantics deliberately mirrored, including known Pine quirks:

* ``na`` propagation: comparisons with undefined values are False; setups
  simply cannot fire until ATR(14) and their level sources become defined
  (no oracle-style readiness gate, pine:380-467).
* ``request.security(tf, expr[1], lookahead_on)`` boundary rule: a 3m bar
  reads the HTF bar *before the HTF bar containing it*, so a 3m close that
  coincides with a 10m close reads the 10m bar before the one closing at
  that instant (pine:394-404).
* Trend Ignition is effectively never route-blocked (pine:614-615).
* Same-bar arbitration is setup-priority first, then grade, then candle
  direction (pine:274-278, 749-761).
* Per-setup ``ready and not ready[1]`` edge de-duplication (pine:635-642).
* Plan lifecycle order STOP -> T2 -> T1 -> structure exit -> pace protect,
  stop-first on ambiguous bars, same-bar stop+reentry and same-bar reverse
  (pine:769-866).

Known unverified micro-semantics (kept from TV documentation, must be
confirmed against a true v11 fixture): ``ta.pivotlow/pivothigh`` tie
handling, and HTF mapping across session gaps.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import json
import math
from os import PathLike
from pathlib import Path
from typing import Iterable, Sequence

_CONTRACT_PATH = Path(__file__).resolve().parent / "config" / "v11_contract.json"

SIDE_SHORT = -1
SIDE_FLAT = 0
SIDE_LONG = 1

SETUP_NONE = 0
SETUP_LEVEL_REJECTION = 1
SETUP_PULLBACK_CONTINUATION = 2
SETUP_BREAKOUT = 3
SETUP_IGNITION = 4

GRADE_NONE = 0
GRADE_C = 1
GRADE_B = 2
GRADE_A = 3

ROLE_INITIAL = 1
ROLE_ADD = 2
ROLE_REVERSE = 3
ROLE_COUNTERTREND_ADVISORY = 4

PLAN_FLAT = 0
PLAN_HOLD = 1
PLAN_PROTECT = 2
PLAN_EXIT = 3

EVENT_NONE = 0
EVENT_T1 = 1
EVENT_T2 = 2
EVENT_STOP = 3
EVENT_PROTECT = 4
EVENT_STRUCTURE_EXIT = 5
EVENT_REVERSE = 6

BLOCK_READY = 0
BLOCK_TRIGGER = 1
BLOCK_CONTEXT = 2
BLOCK_RISK = 3
BLOCK_SPACE = 4
BLOCK_COUNTERTREND = 5

SETUP_NAMES = {
    SETUP_NONE: "NONE",
    SETUP_LEVEL_REJECTION: "LEVEL_REJECTION",
    SETUP_PULLBACK_CONTINUATION: "PULLBACK_CONTINUATION",
    SETUP_BREAKOUT: "BREAKOUT",
    SETUP_IGNITION: "IGNITION",
}

EVENT_NAMES = {
    EVENT_NONE: "NONE",
    EVENT_T1: "T1",
    EVENT_T2: "T2",
    EVENT_STOP: "STOP",
    EVENT_PROTECT: "PROTECT",
    EVENT_STRUCTURE_EXIT: "STRUCTURE_EXIT",
    EVENT_REVERSE: "REVERSE",
}


# ─────────────────────────────────────────────────────────────────────────────
# na-propagating helpers (Pine semantics: any comparison with na is false)
# ─────────────────────────────────────────────────────────────────────────────

def _gt(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a > b


def _lt(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a < b


def _ge(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a >= b


def _le(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a <= b


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _mul(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a * b


def _min2(a: float | None, b: float | None) -> float | None:
    # Pine math.min(na, x) is na.
    return None if a is None or b is None else min(a, b)


def _max2(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else max(a, b)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration bound to the contract file
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ReplicaConfig:
    # lengths (pine:96-105)
    pace_fast: int = 5
    pace_slow: int = 12
    anchor_fast: int = 34
    anchor_slow: int = 50
    atr_length: int = 14
    pivot_length: int = 3
    structure_lookback: int = 4
    compression_lookback: int = 8
    # thresholds (pine:107-121, 452-457, 487, 510, 535, 537, 724, 729, 781)
    touch_atr: float = 0.10
    trigger_atr: float = 0.02
    trigger_buffer_min_ticks: int = 2
    strong_body_ratio: float = 0.34
    close_edge_fraction: float = 0.32
    pullback_wick_fraction: float = 0.24
    rejection_wick_fraction: float = 0.38
    compression_atr: float = 2.20
    stop_buffer_atr: float = 0.10
    max_risk_atr: float = 1.30
    min_space_r: float = 0.55
    b_space_r: float = 0.75
    a_space_r: float = 1.00
    a_max_ema5_distance_atr: float = 1.20
    hard_structure_break_atr: float = 0.08
    # phase proxy (pine:388-392, 456-457)
    phase_base_length: int = 21
    phase_atr_multiple: float = 3.0
    phase_smooth_length: int = 3
    phase_bull_floor: float = -23.6
    phase_bear_ceiling: float = 23.6
    phase_stdev_length: int = 21
    phase_compression_atr: float = 1.10
    # symbol
    mintick: float = 0.1
    saty_ratios: tuple[float, ...] = (
        -3.0, -2.618, -2.0, -1.618, -1.272, -1.0, -0.786, -0.618, -0.5,
        -0.382, -0.236, 0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272,
        1.618, 2.0, 2.618, 3.0,
    )

    @classmethod
    def from_contract(
        cls, path: str | PathLike[str] = _CONTRACT_PATH, *, mintick: float | None = None
    ) -> "ReplicaConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        lengths = data["lengths"]
        th = data["thresholds"]
        ph = data["phase"]
        return cls(
            pace_fast=lengths["pace_fast"],
            pace_slow=lengths["pace_slow"],
            anchor_fast=lengths["anchor_fast"],
            anchor_slow=lengths["anchor_slow"],
            atr_length=lengths["atr"],
            pivot_length=lengths["pivot"],
            structure_lookback=lengths["structure_lookback"],
            compression_lookback=lengths["compression_lookback"],
            touch_atr=th["touch_atr"],
            trigger_atr=th["trigger_atr"],
            trigger_buffer_min_ticks=th["trigger_buffer_min_ticks"],
            strong_body_ratio=th["strong_body_ratio"],
            close_edge_fraction=th["close_edge_fraction"],
            pullback_wick_fraction=th["pullback_wick_fraction"],
            rejection_wick_fraction=th["rejection_wick_fraction"],
            compression_atr=th["compression_atr"],
            stop_buffer_atr=th["stop_buffer_atr"],
            max_risk_atr=th["max_risk_atr"],
            min_space_r=th["min_space_r"],
            b_space_r=th["b_space_r"],
            a_space_r=th["a_space_r"],
            a_max_ema5_distance_atr=th["a_max_ema5_distance_atr"],
            hard_structure_break_atr=th["hard_structure_break_atr"],
            phase_base_length=ph["base_ema_length"],
            phase_atr_multiple=ph["atr_normalization_multiple"],
            phase_smooth_length=ph["smoothing_ema_length"],
            phase_bull_floor=ph["bull_floor"],
            phase_bear_ceiling=ph["bear_ceiling"],
            phase_stdev_length=ph["stdev_length"],
            phase_compression_atr=ph["compression_stdev_atr"],
            mintick=(
                mintick
                if mintick is not None
                else data["runtime"]["default_mintick_capitalcom_spx500"]
            ),
            saty_ratios=tuple(data["levels"]["saty_ratios"]),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Market data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Bar:
    """A confirmed bar keyed by its close time in epoch milliseconds."""

    close_ms: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(p) for p in prices):
            raise ValueError("bar prices must be finite")
        if self.low > self.high:
            raise ValueError("bar low cannot exceed high")
        if not (self.low <= self.open <= self.high) or not (
            self.low <= self.close <= self.high
        ):
            raise ValueError("bar open/close must be inside the bar range")


@dataclass(frozen=True, slots=True)
class HtfRow:
    close_ms: int
    close: float
    ema5: float | None
    ema12: float | None
    ema34: float | None
    ema50: float | None


@dataclass(frozen=True, slots=True)
class DailyRow:
    close_ms: int
    close: float
    atr: float | None
    high: float
    low: float


class _PrevHtfIndex:
    """``request.security(tf, expr[1], lookahead_on)`` lookup (pine:394-404).

    Empirically established against the true 2026-07-21 TradingView export
    (301/1508 bars would disagree under any close-time rule): a chart bar maps
    to the HTF bar containing its **open time**, and ``[1]`` reads the bar
    before that.  Equivalently: the last HTF row whose close time is at or
    before the 3m bar's open.  A 3m bar that straddles an HTF boundary
    (e.g. 09:09-09:12 across 09:10) therefore still reads the HTF bar that
    closed before the straddled boundary.
    """

    def __init__(self, close_times: Sequence[int]):
        self._times = list(close_times)

    def prev_index_at(self, open_ms: int) -> int | None:
        position = bisect_right(self._times, open_ms) - 1
        return position if position >= 0 else None


def build_10m_rows(bars: Sequence[Bar], config: ReplicaConfig) -> tuple[HtfRow, ...]:
    """SMA-seeded hl2 EMAs over confirmed 10m bars (pine:396-399 series)."""

    ema5 = _Ema(config.pace_fast)
    ema12 = _Ema(config.pace_slow)
    ema34 = _Ema(config.anchor_fast)
    ema50 = _Ema(config.anchor_slow)
    rows: list[HtfRow] = []
    previous = None
    for bar in bars:
        if previous is not None and bar.close_ms <= previous:
            raise ValueError("10m bars must be strictly time ordered")
        previous = bar.close_ms
        source = (bar.high + bar.low) / 2.0
        rows.append(
            HtfRow(
                bar.close_ms, bar.close,
                ema5.update(source), ema12.update(source),
                ema34.update(source), ema50.update(source),
            )
        )
    return tuple(rows)


def build_daily_rows(bars: Sequence[Bar], config: ReplicaConfig) -> tuple[DailyRow, ...]:
    """Daily close/ATR/high/low series feeding the Saty anchor (pine:401-404)."""

    rows: list[DailyRow] = []
    atr: float | None = None
    trs: list[float] = []
    previous_close: float | None = None
    previous_time: int | None = None
    for bar in bars:
        if previous_time is not None and bar.close_ms <= previous_time:
            raise ValueError("daily bars must be strictly time ordered")
        previous_time = bar.close_ms
        if previous_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        previous_close = bar.close
        if atr is None:
            trs.append(tr)
            if len(trs) == config.atr_length:
                atr = sum(trs) / len(trs)
        else:
            atr = (atr * (config.atr_length - 1) + tr) / config.atr_length
        rows.append(DailyRow(bar.close_ms, bar.close, atr, bar.high, bar.low))
    return tuple(rows)


class _Ema:
    """TradingView ``ta.ema``: na for the first ``length-1`` defined inputs,
    seeded with the SMA of the first ``length`` inputs, recursive afterwards.

    Established empirically against the 2026-07-21 true export: the frozen
    strategy's own 3m EMA plots are na for the first bars of its calc window
    and a first-value-seeded replica diverges for ~4x length bars before
    converging; the SMA seed reproduces Pine bit-for-bit.
    """

    __slots__ = ("length", "_buffer", "value")

    def __init__(self, length: int) -> None:
        self.length = length
        self._buffer: list[float] = []
        self.value: float | None = None

    def update(self, source: float | None) -> float | None:
        if source is None:
            return self.value
        if self.value is None:
            self._buffer.append(source)
            if len(self._buffer) == self.length:
                self.value = sum(self._buffer) / self.length
                self._buffer.clear()
            return self.value
        alpha = 2.0 / (self.length + 1.0)
        self.value = self.value + alpha * (source - self.value)
        return self.value


# ─────────────────────────────────────────────────────────────────────────────
# Event and snapshot records
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SignalEvent:
    id: int
    close_ms: int
    side: int
    setup: int
    grade: int
    role: int
    entry: float
    stop: float
    t1: float
    t2: float
    space_r: float
    reason_mask: int

    @property
    def countertrend(self) -> bool:
        return self.reason_mask >= 128


@dataclass(frozen=True, slots=True)
class PlanEvent:
    id: int
    close_ms: int
    type: int
    price: float
    side: int


@dataclass(slots=True)
class PlanState:
    active: bool = False
    side: int = SIDE_FLAT
    status: int = PLAN_FLAT
    signal_id: int = 0
    start_ms: int | None = None
    entry: float | None = None
    stop: float | None = None
    effective_stop: float | None = None
    t1: float | None = None
    t2: float | None = None
    countertrend: bool = False
    t1_reached: bool = False
    t2_reached: bool = False
    event_id: int = 0
    event_ms: int | None = None
    event_type: int = EVENT_NONE
    event_price: float | None = None

    def copy(self) -> "PlanState":
        return PlanState(
            self.active, self.side, self.status, self.signal_id, self.start_ms,
            self.entry, self.stop, self.effective_stop, self.t1, self.t2,
            self.countertrend, self.t1_reached, self.t2_reached,
            self.event_id, self.event_ms, self.event_type, self.event_price,
        )


@dataclass(frozen=True, slots=True)
class BarSnapshot:
    """Mirror of the Pine Data Window audit fields plus test hooks."""

    close_ms: int
    context_close_ms: int | None
    context_direction: int
    context_pace: int
    atr: float | None
    support: float | None
    resistance: float | None
    next_long_trigger: float | None
    next_short_trigger: float | None
    long_blocker: int
    short_blocker: int
    new_signal: SignalEvent | None
    new_plan_events: tuple[PlanEvent, ...]
    plan: PlanState
    debug: dict


# ─────────────────────────────────────────────────────────────────────────────
# The replica engine
# ─────────────────────────────────────────────────────────────────────────────

class V11PineReplica:
    def __init__(
        self,
        bars_10m: Iterable[Bar] = (),
        bars_daily: Iterable[Bar] = (),
        config: ReplicaConfig | None = None,
        engine_bar_ms: int = 180_000,
    ) -> None:
        self.config = config or ReplicaConfig.from_contract()
        self.engine_bar_ms = engine_bar_ms
        self._rows_10m = build_10m_rows(tuple(bars_10m), self.config)
        self._rows_daily = build_daily_rows(tuple(bars_daily), self.config)
        self._idx_10m = _PrevHtfIndex([r.close_ms for r in self._rows_10m])
        self._idx_daily = _PrevHtfIndex([r.close_ms for r in self._rows_daily])

        # 3m recursive state
        self._ema5 = _Ema(self.config.pace_fast)
        self._ema12 = _Ema(self.config.pace_slow)
        self._ema34 = _Ema(self.config.anchor_fast)
        self._ema50 = _Ema(self.config.anchor_slow)
        self._atr: float | None = None
        self._trs: list[float] = []
        self._phase_base = _Ema(self.config.phase_base_length)
        self._phase = _Ema(self.config.phase_smooth_length)
        self._closes: list[float] = []

        # per-bar history (index-aligned with processed bars)
        self._bars: list[Bar] = []
        self._fast_upper: list[float | None] = []
        self._fast_lower: list[float | None] = []
        self._tolerance: list[float | None] = []
        self._support_hist: list[float | None] = []
        self._resistance_hist: list[float | None] = []
        self._swept_support: list[bool] = []
        self._swept_resistance: list[bool] = []
        self._phase_hist: list[float | None] = []
        self._ema5_prev: float | None = None
        self._ema12_prev: float | None = None
        self._ready_prev: dict[str, bool] = {}

        self._pivot_low: float | None = None
        self._pivot_high: float | None = None

        self._plan = PlanState()
        self._last_signal: SignalEvent | None = None
        self._signals: list[SignalEvent] = []
        self._plan_events: list[PlanEvent] = []
        self._snapshots: list[BarSnapshot] = []

    # public API ------------------------------------------------------------

    @property
    def signals(self) -> tuple[SignalEvent, ...]:
        return tuple(self._signals)

    @property
    def plan_events(self) -> tuple[PlanEvent, ...]:
        return tuple(self._plan_events)

    @property
    def snapshots(self) -> tuple[BarSnapshot, ...]:
        return tuple(self._snapshots)

    def replay(self, bars_3m: Iterable[Bar]) -> tuple[BarSnapshot, ...]:
        for bar in bars_3m:
            self.process(bar)
        return self.snapshots

    # engine ----------------------------------------------------------------

    def process(self, bar: Bar) -> BarSnapshot:
        cfg = self.config
        if self._bars and bar.close_ms <= self._bars[-1].close_ms:
            raise ValueError("3m bars must be strictly time ordered")

        ema5_prev_bar = self._ema5.value
        ema12_prev_bar = self._ema12.value

        # ── series updates (pine:382-392) ──
        source = (bar.high + bar.low) / 2.0
        ema5 = self._ema5.update(source)
        ema12 = self._ema12.update(source)
        ema34 = self._ema34.update(source)
        ema50 = self._ema50.update(source)

        previous_close = self._bars[-1].close if self._bars else None
        if previous_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        if self._atr is None:
            self._trs.append(tr)
            if len(self._trs) == cfg.atr_length:
                self._atr = sum(self._trs) / len(self._trs)
        else:
            self._atr = (self._atr * (cfg.atr_length - 1) + tr) / cfg.atr_length
        atr = self._atr

        safe_atr = None if atr is None else max(atr, cfg.mintick)
        phase_base = self._phase_base.update(bar.close)
        phase_prev = self._phase.value
        phase_raw = (
            None
            if safe_atr is None or phase_base is None
            else ((bar.close - phase_base) / (cfg.phase_atr_multiple * safe_atr))
            * 100.0
        )
        phase = self._phase.update(phase_raw)

        self._closes.append(bar.close)
        if len(self._closes) >= cfg.phase_stdev_length:
            window = self._closes[-cfg.phase_stdev_length:]
            mean = sum(window) / len(window)
            phase_deviation: float | None = math.sqrt(
                sum((c - mean) ** 2 for c in window) / len(window)
            )
        else:
            phase_deviation = None
        phase_compression = (
            phase_deviation is not None
            and atr is not None
            and phase_deviation <= cfg.phase_compression_atr * atr
        )

        # ── confirmed HTF context (pine:394-404) ──
        bar_open_ms = bar.close_ms - self.engine_bar_ms
        ctx_i = self._idx_10m.prev_index_at(bar_open_ms)
        ctx = self._rows_10m[ctx_i] if ctx_i is not None else None
        day_i = self._idx_daily.prev_index_at(bar_open_ms)
        day = self._rows_daily[day_i] if day_i is not None else None
        daily_anchor = day.close if day is not None else None
        daily_atr = day.atr if day is not None else None
        prior_day_high = day.high if day is not None else None
        prior_day_low = day.low if day is not None else None

        context_direction = (
            SIDE_LONG if ctx is not None and _gt(ctx.ema34, ctx.ema50)
            else SIDE_SHORT if ctx is not None and _lt(ctx.ema34, ctx.ema50)
            else SIDE_FLAT
        )
        context_pace = (
            SIDE_LONG if ctx is not None and _gt(ctx.ema5, ctx.ema12)
            else SIDE_SHORT if ctx is not None and _lt(ctx.ema5, ctx.ema12)
            else SIDE_FLAT
        )
        pace_direction = (
            SIDE_LONG if _gt(ema5, ema12)
            else SIDE_SHORT if _lt(ema5, ema12)
            else SIDE_FLAT
        )

        fast_lower = _min2(ema5, ema12)
        fast_upper = _max2(ema5, ema12)
        anchor_lower = _min2(ema34, ema50)
        anchor_upper = _max2(ema34, ema50)
        context_anchor_lower = _min2(
            ctx.ema34 if ctx else None, ctx.ema50 if ctx else None
        )
        context_anchor_upper = _max2(
            ctx.ema34 if ctx else None, ctx.ema50 if ctx else None
        )
        tolerance = _mul(cfg.touch_atr, atr)
        trigger_buffer = (
            None
            if atr is None
            else max(2.0 * cfg.mintick, cfg.trigger_atr * atr)
        )

        # ── confirmed pivots (pine:422-425) ──
        self._update_pivots(bar)
        known_pivot_low = self._pivot_low
        known_pivot_high = self._pivot_high
        saty_below, saty_above = self._nearest_saty(daily_anchor, daily_atr, bar.close)

        # ── S1/R1 six-source blend (pine:426-441) ──
        support: float | None = None
        for candidate in (
            saty_below, known_pivot_low, prior_day_low,
            fast_lower, anchor_lower, context_anchor_lower,
        ):
            support = self._pick_support(bar.close, support, candidate, tolerance)
        resistance: float | None = None
        for candidate in (
            saty_above, known_pivot_high, prior_day_high,
            fast_upper, anchor_upper, context_anchor_upper,
        ):
            resistance = self._pick_resistance(bar.close, resistance, candidate, tolerance)

        # ── structure windows over PREVIOUS bars (pine:443-447) ──
        prior_structure_high = self._window_high(cfg.structure_lookback)
        prior_structure_low = self._window_low(cfg.structure_lookback)
        prior_box_high = self._window_high(cfg.compression_lookback)
        prior_box_low = self._window_low(cfg.compression_lookback)
        prior_box_range = _sub(prior_box_high, prior_box_low)

        # ── candle anatomy (pine:448-457) ──
        candle_range = max(bar.high - bar.low, cfg.mintick)
        candle_body = abs(bar.close - bar.open)
        lower_wick = min(bar.open, bar.close) - bar.low
        upper_wick = bar.high - max(bar.open, bar.close)
        strong_bull = (
            bar.close > bar.open
            and candle_body / candle_range >= cfg.strong_body_ratio
            and bar.close >= bar.high - cfg.close_edge_fraction * candle_range
        )
        strong_bear = (
            bar.close < bar.open
            and candle_body / candle_range >= cfg.strong_body_ratio
            and bar.close <= bar.low + cfg.close_edge_fraction * candle_range
        )
        bull_phase = (
            phase is not None
            and (
                (phase_prev is not None and phase > phase_prev)
                or phase >= cfg.phase_bull_floor
            )
        )
        bear_phase = (
            phase is not None
            and (
                (phase_prev is not None and phase < phase_prev)
                or phase <= cfg.phase_bear_ceiling
            )
        )

        # ── 1. Trend Ignition (pine:459-467) ──
        cross_over = (
            ema5_prev_bar is not None
            and ema12_prev_bar is not None
            and ema5_prev_bar <= ema12_prev_bar
            and _gt(ema5, ema12)
        )
        cross_under = (
            ema5_prev_bar is not None
            and ema12_prev_bar is not None
            and ema5_prev_bar >= ema12_prev_bar
            and _lt(ema5, ema12)
        )
        prev_bar = self._bars[-1] if self._bars else None
        prev_anchor_upper = self._prev_anchor_upper
        prev_anchor_lower = self._prev_anchor_lower
        ignition_long = (
            (
                (cross_over and _gt(bar.close, anchor_upper))
                or (
                    prev_bar is not None
                    and prev_anchor_upper is not None
                    and prev_bar.close <= prev_anchor_upper
                    and _gt(bar.close, anchor_upper)
                )
            )
            and _gt(bar.close, _add(prior_structure_high, trigger_buffer))
            and strong_bull
        )
        ignition_short = (
            (
                (cross_under and _lt(bar.close, anchor_lower))
                or (
                    prev_bar is not None
                    and prev_anchor_lower is not None
                    and prev_bar.close >= prev_anchor_lower
                    and _lt(bar.close, anchor_lower)
                )
            )
            and _lt(bar.close, _sub(prior_structure_low, trigger_buffer))
            and strong_bear
        )

        # ── 2. Pullback Continuation (pine:469-515) ──
        fast_touch_long = _le(bar.low, _add(fast_upper, tolerance)) and _gt(bar.close, fast_upper)
        anchor_touch_long = _le(bar.low, _add(anchor_upper, tolerance)) and _gt(bar.close, anchor_upper)
        context_touch_long = (
            _le(bar.low, _add(context_anchor_upper, tolerance))
            and _gt(bar.close, context_anchor_upper)
        )
        level_touch_long = (
            support is not None
            and _le(bar.low, _add(support, tolerance))
            and bar.close > support
        )
        touch_long_now = fast_touch_long or anchor_touch_long or context_touch_long or level_touch_long

        prior_test_long = self._prior_test(SIDE_LONG)
        established_long_before = self._established_before(SIDE_LONG)
        same_bar_pullback_long = (
            touch_long_now and strong_bull
            and lower_wick >= cfg.pullback_wick_fraction * candle_range
        )
        next_bar_pullback_long = (
            prior_test_long and established_long_before
            and prev_bar is not None
            and _gt(bar.close, _add(prev_bar.high, trigger_buffer))
            and strong_bull
        )
        pullback_long = (
            pace_direction == SIDE_LONG
            and (context_direction != SIDE_SHORT or context_pace == SIDE_LONG)
            and (same_bar_pullback_long or next_bar_pullback_long)
        )

        fast_touch_short = _ge(bar.high, _sub(fast_lower, tolerance)) and _lt(bar.close, fast_lower)
        anchor_touch_short = _ge(bar.high, _sub(anchor_lower, tolerance)) and _lt(bar.close, anchor_lower)
        context_touch_short = (
            _ge(bar.high, _sub(context_anchor_lower, tolerance))
            and _lt(bar.close, context_anchor_lower)
        )
        level_touch_short = (
            resistance is not None
            and _ge(bar.high, _sub(resistance, tolerance))
            and bar.close < resistance
        )
        touch_short_now = fast_touch_short or anchor_touch_short or context_touch_short or level_touch_short

        prior_test_short = self._prior_test(SIDE_SHORT)
        established_short_before = self._established_before(SIDE_SHORT)
        same_bar_pullback_short = (
            touch_short_now and strong_bear
            and upper_wick >= cfg.pullback_wick_fraction * candle_range
        )
        next_bar_pullback_short = (
            prior_test_short and established_short_before
            and prev_bar is not None
            and _lt(bar.close, _sub(prev_bar.low, trigger_buffer))
            and strong_bear
        )
        pullback_short = (
            pace_direction == SIDE_SHORT
            and (context_direction != SIDE_LONG or context_pace == SIDE_SHORT)
            and (same_bar_pullback_short or next_bar_pullback_short)
        )

        # ── 3. Compression / Structure Breakout (pine:517-524) ──
        compact_box = (
            _le(prior_box_range, _mul(cfg.compression_atr, atr)) or phase_compression
        )
        breakout_long = (
            compact_box
            and _gt(bar.close, _add(prior_structure_high, trigger_buffer))
            and strong_bull
            and pace_direction == SIDE_LONG
        )
        breakout_short = (
            compact_box
            and _lt(bar.close, _sub(prior_structure_low, trigger_buffer))
            and strong_bear
            and pace_direction == SIDE_SHORT
        )

        # ── 4. Level Rejection (pine:526-538) ──
        swept_support = (
            support is not None
            and _le(bar.low, _add(support, tolerance))
            and _gt(bar.close, _add(support, trigger_buffer))
        )
        swept_resistance = (
            resistance is not None
            and _ge(bar.high, _sub(resistance, tolerance))
            and _lt(bar.close, _sub(resistance, trigger_buffer))
        )
        swept_support_prev = self._swept_support[-1] if self._swept_support else False
        swept_resistance_prev = self._swept_resistance[-1] if self._swept_resistance else False
        repeated_support = (
            swept_support_prev
            and prev_bar is not None
            and _ge(bar.low, _sub(prev_bar.low, tolerance))
            and _gt(bar.close, _add(prev_bar.high, trigger_buffer))
        )
        repeated_resistance = (
            swept_resistance_prev
            and prev_bar is not None
            and _le(bar.high, _add(prev_bar.high, tolerance))
            and _lt(bar.close, _sub(prev_bar.low, trigger_buffer))
        )
        rejection_long = (
            swept_support
            and lower_wick >= cfg.rejection_wick_fraction * candle_range
            and bar.close > bar.open
        ) or (repeated_support and strong_bull)
        rejection_short = (
            swept_resistance
            and upper_wick >= cfg.rejection_wick_fraction * candle_range
            and bar.close < bar.open
        ) or (repeated_resistance and strong_bear)

        proofs = {
            (SIDE_LONG, SETUP_LEVEL_REJECTION): rejection_long,
            (SIDE_LONG, SETUP_PULLBACK_CONTINUATION): pullback_long,
            (SIDE_LONG, SETUP_BREAKOUT): breakout_long,
            (SIDE_LONG, SETUP_IGNITION): ignition_long,
            (SIDE_SHORT, SETUP_LEVEL_REJECTION): rejection_short,
            (SIDE_SHORT, SETUP_PULLBACK_CONTINUATION): pullback_short,
            (SIDE_SHORT, SETUP_BREAKOUT): breakout_short,
            (SIDE_SHORT, SETUP_IGNITION): ignition_short,
        }

        # ── obstacle pools (pine:555-570) ──
        long_entry = bar.close
        short_entry = bar.close
        long_obstacle: float | None = None
        for candidate in (
            saty_above, known_pivot_high, prior_day_high,
            fast_upper, anchor_upper, context_anchor_upper,
        ):
            long_obstacle = self._pick_above(long_entry, long_obstacle, candidate, tolerance)
        short_obstacle: float | None = None
        for candidate in (
            saty_below, known_pivot_low, prior_day_low,
            fast_lower, anchor_lower, context_anchor_lower,
        ):
            short_obstacle = self._pick_below(short_entry, short_obstacle, candidate, tolerance)

        # ── per-setup stops (pine:572-584) ──
        buffer = _mul(cfg.stop_buffer_atr, atr)
        stops: dict[tuple[int, int], float | None] = {}
        if prev_bar is not None and repeated_support:
            long_rejection_base: float | None = min(bar.low, prev_bar.low)
        else:
            long_rejection_base = bar.low
        stops[(SIDE_LONG, SETUP_LEVEL_REJECTION)] = _sub(long_rejection_base, buffer)
        if prev_bar is not None and next_bar_pullback_long:
            long_pullback_base: float | None = max(prev_bar.low, bar.low)
        else:
            long_pullback_base = bar.low
        stops[(SIDE_LONG, SETUP_PULLBACK_CONTINUATION)] = _sub(long_pullback_base, buffer)
        stops[(SIDE_LONG, SETUP_BREAKOUT)] = _sub(_max2(bar.low, prior_structure_high), buffer)
        stops[(SIDE_LONG, SETUP_IGNITION)] = _sub(_max2(bar.low, anchor_upper), buffer)
        if prev_bar is not None and repeated_resistance:
            short_rejection_base: float | None = max(bar.high, prev_bar.high)
        else:
            short_rejection_base = bar.high
        stops[(SIDE_SHORT, SETUP_LEVEL_REJECTION)] = _add(short_rejection_base, buffer)
        if prev_bar is not None and next_bar_pullback_short:
            short_pullback_base: float | None = min(prev_bar.high, bar.high)
        else:
            short_pullback_base = bar.high
        stops[(SIDE_SHORT, SETUP_PULLBACK_CONTINUATION)] = _add(short_pullback_base, buffer)
        stops[(SIDE_SHORT, SETUP_BREAKOUT)] = _add(_min2(bar.high, prior_structure_low), buffer)
        stops[(SIDE_SHORT, SETUP_IGNITION)] = _add(_min2(bar.high, anchor_lower), buffer)

        def risk_of(side: int, setup: int) -> float | None:
            stop = stops[(side, setup)]
            if stop is None:
                return None
            return (bar.close - stop) if side == SIDE_LONG else (stop - bar.close)

        def space_of(side: int, setup: int) -> float:
            # f_candidate_space (pine:242-246)
            stop = stops[(side, setup)]
            if stop is None:
                return 0.0
            risk = (bar.close - stop) * side
            obstacle = long_obstacle if side == SIDE_LONG else short_obstacle
            obstacle_distance = risk if obstacle is None else (obstacle - bar.close) * side
            target_distance = min(risk, max(0.0, obstacle_distance))
            return target_distance / risk if risk > cfg.mintick else 0.0

        # ── routes (pine:612-615) ──
        long_trend_route = context_direction != SIDE_SHORT
        short_trend_route = context_direction != SIDE_LONG
        long_ignition_route = long_trend_route or _gt(bar.close, anchor_upper)
        short_ignition_route = short_trend_route or _lt(bar.close, anchor_lower)
        routes = {
            (SIDE_LONG, SETUP_LEVEL_REJECTION): True,
            (SIDE_LONG, SETUP_PULLBACK_CONTINUATION): long_trend_route,
            (SIDE_LONG, SETUP_BREAKOUT): long_trend_route,
            (SIDE_LONG, SETUP_IGNITION): long_ignition_route,
            (SIDE_SHORT, SETUP_LEVEL_REJECTION): True,
            (SIDE_SHORT, SETUP_PULLBACK_CONTINUATION): short_trend_route,
            (SIDE_SHORT, SETUP_BREAKOUT): short_trend_route,
            (SIDE_SHORT, SETUP_IGNITION): short_ignition_route,
        }

        # ── ready + edges (pine:616-642) ──
        def candidate_ready(side: int, setup: int) -> bool:
            risk = risk_of(side, setup)
            return (
                proofs[(side, setup)]
                and routes[(side, setup)]
                and risk is not None
                and atr is not None
                and risk > cfg.mintick
                and risk <= cfg.max_risk_atr * atr
                and space_of(side, setup) >= cfg.min_space_r
            )

        ready_now: dict[str, bool] = {}
        edges: dict[tuple[int, int], bool] = {}
        for side in (SIDE_LONG, SIDE_SHORT):
            for setup in (
                SETUP_LEVEL_REJECTION, SETUP_PULLBACK_CONTINUATION,
                SETUP_BREAKOUT, SETUP_IGNITION,
            ):
                key = f"{side}:{setup}"
                is_ready = candidate_ready(side, setup)
                ready_now[key] = is_ready
                edges[(side, setup)] = is_ready and not self._ready_prev.get(key, False)

        def first_setup(mapping, side: int) -> int:
            for setup in (
                SETUP_LEVEL_REJECTION, SETUP_PULLBACK_CONTINUATION,
                SETUP_BREAKOUT, SETUP_IGNITION,
            ):
                if mapping(side, setup):
                    return setup
            return SETUP_NONE

        long_fire_setup = first_setup(lambda s, u: edges[(s, u)], SIDE_LONG)
        short_fire_setup = first_setup(lambda s, u: edges[(s, u)], SIDE_SHORT)
        long_best_ready = first_setup(lambda s, u: ready_now[f"{s}:{u}"], SIDE_LONG)
        short_best_ready = first_setup(lambda s, u: ready_now[f"{s}:{u}"], SIDE_SHORT)
        long_evidence = first_setup(lambda s, u: proofs[(s, u)], SIDE_LONG)
        short_evidence = first_setup(lambda s, u: proofs[(s, u)], SIDE_SHORT)
        long_setup = (
            long_fire_setup if long_fire_setup != SETUP_NONE
            else long_best_ready if long_best_ready != SETUP_NONE
            else long_evidence
        )
        short_setup = (
            short_fire_setup if short_fire_setup != SETUP_NONE
            else short_best_ready if short_best_ready != SETUP_NONE
            else short_evidence
        )

        # ── selected geometry (pine:673-702) ──
        def selected_stop(side: int, setup: int) -> float | None:
            if setup == SETUP_NONE:
                setup = SETUP_IGNITION  # pine falls through to ignition stop
            return stops[(side, setup)]

        long_stop = selected_stop(SIDE_LONG, long_setup)
        short_stop = selected_stop(SIDE_SHORT, short_setup)
        long_risk = None if long_stop is None else long_entry - long_stop
        short_risk = None if short_stop is None else short_stop - short_entry
        long_space = space_of(SIDE_LONG, long_setup if long_setup != SETUP_NONE else SETUP_IGNITION)
        short_space = space_of(SIDE_SHORT, short_setup if short_setup != SETUP_NONE else SETUP_IGNITION)

        long_t1 = (
            None if long_risk is None
            else min(long_entry + long_risk, long_obstacle)
            if long_obstacle is not None else long_entry + long_risk
        )
        short_t1 = (
            None if short_risk is None
            else max(short_entry - short_risk, short_obstacle)
            if short_obstacle is not None else short_entry - short_risk
        )
        long_second_obstacle: float | None = None
        if long_t1 is not None:
            for candidate in (saty_above, known_pivot_high, prior_day_high):
                long_second_obstacle = self._pick_above(
                    long_t1, long_second_obstacle, candidate, tolerance
                )
        long_t2 = (
            None if long_risk is None
            else min(long_entry + 2.0 * long_risk, long_second_obstacle)
            if long_second_obstacle is not None else
            None if long_risk is None else long_entry + 2.0 * long_risk
        )
        short_second_obstacle: float | None = None
        if short_t1 is not None:
            for candidate in (saty_below, known_pivot_low, prior_day_low):
                short_second_obstacle = self._pick_below(
                    short_t1, short_second_obstacle, candidate, tolerance
                )
        short_t2 = (
            None if short_risk is None
            else max(short_entry - 2.0 * short_risk, short_second_obstacle)
            if short_second_obstacle is not None else
            None if short_risk is None else short_entry - 2.0 * short_risk
        )

        # ── blockers (pine:703-720, 253-258) ──
        def selected_proof(side: int, setup: int) -> bool:
            return proofs[(side, setup)] if setup != SETUP_NONE else False

        def selected_route(side: int, setup: int) -> bool:
            if setup == SETUP_LEVEL_REJECTION:
                return True
            if setup == SETUP_IGNITION:
                return routes[(side, SETUP_IGNITION)]
            return long_trend_route if side == SIDE_LONG else short_trend_route

        def blocker_of(side: int, setup: int, risk: float | None, space: float) -> int:
            # f_candidate_blocker (pine:253-258) with Pine na semantics: an
            # undefined risk/ATR comparison is false, so warm-up bars fall
            # through to the space check rather than reporting BLOCK_RISK.
            if not selected_proof(side, setup):
                return BLOCK_TRIGGER
            if not selected_route(side, setup):
                return BLOCK_COUNTERTREND
            risk_too_small = risk is not None and risk <= cfg.mintick
            risk_too_wide = (
                risk is not None and atr is not None
                and risk > cfg.max_risk_atr * atr
            )
            if risk_too_small or risk_too_wide:
                return BLOCK_RISK
            if space < cfg.min_space_r:
                return BLOCK_SPACE
            return BLOCK_READY

        long_blocker = (
            BLOCK_READY if long_best_ready != SETUP_NONE
            else blocker_of(SIDE_LONG, long_setup, long_risk, long_space)
        )
        short_blocker = (
            BLOCK_READY if short_best_ready != SETUP_NONE
            else blocker_of(SIDE_SHORT, short_setup, short_risk, short_space)
        )

        # ── grades (pine:722-731) ──
        long_a = (
            context_direction == SIDE_LONG and context_pace == SIDE_LONG
            and pace_direction == SIDE_LONG and bull_phase
            and atr is not None and ema5 is not None
            and abs(bar.close - ema5) <= cfg.a_max_ema5_distance_atr * atr
            and long_space >= cfg.a_space_r
        )
        short_a = (
            context_direction == SIDE_SHORT and context_pace == SIDE_SHORT
            and pace_direction == SIDE_SHORT and bear_phase
            and atr is not None and ema5 is not None
            and abs(bar.close - ema5) <= cfg.a_max_ema5_distance_atr * atr
            and short_space >= cfg.a_space_r
        )
        long_grade = (
            GRADE_A if long_a
            else GRADE_B
            if context_direction != SIDE_SHORT and long_space >= cfg.b_space_r
            else GRADE_C
        )
        short_grade = (
            GRADE_A if short_a
            else GRADE_B
            if context_direction != SIDE_LONG and short_space >= cfg.b_space_r
            else GRADE_C
        )

        # ── same-bar arbitration (pine:733-761) ──
        long_ready = long_fire_setup != SETUP_NONE
        short_ready = short_fire_setup != SETUP_NONE
        chosen_side = SIDE_FLAT
        chosen_setup = SETUP_NONE
        chosen_grade = GRADE_NONE
        if long_ready and not short_ready:
            chosen_side, chosen_setup, chosen_grade = SIDE_LONG, long_setup, long_grade
        elif short_ready and not long_ready:
            chosen_side, chosen_setup, chosen_grade = SIDE_SHORT, short_setup, short_grade
        elif long_ready and short_ready:
            long_priority = self._setup_priority(long_setup)
            short_priority = self._setup_priority(short_setup)
            if (
                long_priority > short_priority
                or (long_priority == short_priority and long_grade > short_grade)
                or (
                    long_priority == short_priority
                    and long_grade == short_grade
                    and bar.close >= bar.open
                )
            ):
                chosen_side, chosen_setup, chosen_grade = SIDE_LONG, long_setup, long_grade
            else:
                chosen_side, chosen_setup, chosen_grade = SIDE_SHORT, short_setup, short_grade

        # ── plan lifecycle BEFORE new signal (pine:769-826) ──
        new_plan_events: list[PlanEvent] = []
        plan = self._plan

        def record_plan_event(event_type: int, price: float | None) -> None:
            plan.event_id = bar.close_ms + event_type
            plan.event_ms = bar.close_ms
            plan.event_type = event_type
            plan.event_price = price
            event = PlanEvent(plan.event_id, bar.close_ms, event_type, price, plan.side)
            new_plan_events.append(event)
            self._plan_events.append(event)

        if plan.active:
            stopped = (
                _le(bar.low, plan.effective_stop)
                if plan.side == SIDE_LONG
                else _ge(bar.high, plan.effective_stop)
            )
            reached_t2 = not plan.t2_reached and (
                _ge(bar.high, plan.t2) if plan.side == SIDE_LONG else _le(bar.low, plan.t2)
            )
            reached_t1 = (
                _ge(bar.high, plan.t1) if plan.side == SIDE_LONG else _le(bar.low, plan.t1)
            )
            pace_against = (
                pace_direction == SIDE_SHORT
                if plan.side == SIDE_LONG
                else pace_direction == SIDE_LONG
            )
            hard_structure_break = (
                _lt(bar.close, _sub(anchor_lower, _mul(cfg.hard_structure_break_atr, atr)))
                and pace_against
                if plan.side == SIDE_LONG
                else _gt(bar.close, _add(anchor_upper, _mul(cfg.hard_structure_break_atr, atr)))
                and pace_against
            )
            if stopped:
                record_plan_event(EVENT_STOP, plan.effective_stop)
                plan.active = False
                plan.status = PLAN_EXIT
            elif reached_t2:
                runner_intact = (
                    context_direction == plan.side and pace_direction == plan.side
                )
                record_plan_event(EVENT_T2, plan.t2)
                if runner_intact:
                    plan.t1_reached = True
                    plan.t2_reached = True
                    plan.status = PLAN_PROTECT
                    plan.effective_stop = (
                        _max2(plan.effective_stop, plan.t1)
                        if plan.side == SIDE_LONG
                        else _min2(plan.effective_stop, plan.t1)
                    )
                else:
                    plan.active = False
                    plan.status = PLAN_EXIT
            elif reached_t1 and not plan.t1_reached:
                plan.t1_reached = True
                plan.status = PLAN_PROTECT
                plan.effective_stop = plan.entry
                record_plan_event(EVENT_T1, plan.t1)
            elif hard_structure_break:
                record_plan_event(EVENT_STRUCTURE_EXIT, bar.close)
                plan.active = False
                plan.status = PLAN_EXIT
            elif pace_against and plan.status != PLAN_PROTECT:
                plan.status = PLAN_PROTECT
                record_plan_event(EVENT_PROTECT, bar.close)

        # ── new SignalEvent (pine:828-866) ──
        new_signal: SignalEvent | None = None
        if chosen_side != SIDE_FLAT:
            same_side_plan = plan.active and plan.side == chosen_side
            opposite_plan = plan.active and plan.side == -chosen_side
            chosen_countertrend = context_direction == -chosen_side
            countertrend_advisory = opposite_plan and chosen_countertrend
            role = (
                ROLE_COUNTERTREND_ADVISORY if countertrend_advisory
                else ROLE_ADD if same_side_plan
                else ROLE_REVERSE if opposite_plan
                else ROLE_INITIAL
            )
            if opposite_plan and not countertrend_advisory:
                record_plan_event(EVENT_REVERSE, bar.close)
                plan.active = False
            reason_mask = (
                (1 if chosen_setup == SETUP_LEVEL_REJECTION else 0)
                + (2 if chosen_setup == SETUP_PULLBACK_CONTINUATION else 0)
                + (4 if chosen_setup == SETUP_BREAKOUT else 0)
                + (8 if chosen_setup == SETUP_IGNITION else 0)
                + (16 if context_direction == chosen_side else 0)
                + (32 if context_pace == chosen_side else 0)
                + (64 if (bull_phase if chosen_side == SIDE_LONG else bear_phase) else 0)
                + (128 if context_direction == -chosen_side else 0)
            )
            signal_entry = long_entry if chosen_side == SIDE_LONG else short_entry
            signal_stop = long_stop if chosen_side == SIDE_LONG else short_stop
            signal_t1 = long_t1 if chosen_side == SIDE_LONG else short_t1
            signal_t2 = long_t2 if chosen_side == SIDE_LONG else short_t2
            signal_space = long_space if chosen_side == SIDE_LONG else short_space
            signal_id = (
                bar.close_ms
                + (100 if chosen_side == SIDE_LONG else 200)
                + chosen_setup * 10
                + chosen_grade
            )
            new_signal = SignalEvent(
                signal_id, bar.close_ms, chosen_side, chosen_setup, chosen_grade,
                role, signal_entry, signal_stop, signal_t1, signal_t2,
                signal_space, reason_mask,
            )
            self._last_signal = new_signal
            self._signals.append(new_signal)
            if not same_side_plan and not countertrend_advisory:
                carried = plan
                plan = PlanState(
                    active=True, side=chosen_side, status=PLAN_HOLD,
                    signal_id=signal_id, start_ms=bar.close_ms,
                    entry=signal_entry, stop=signal_stop,
                    effective_stop=signal_stop, t1=signal_t1, t2=signal_t2,
                    countertrend=chosen_countertrend,
                    event_id=carried.event_id, event_ms=carried.event_ms,
                    event_type=carried.event_type, event_price=carried.event_price,
                )
                self._plan = plan

        next_long_trigger = _add(prior_structure_high, trigger_buffer)
        next_short_trigger = _sub(prior_structure_low, trigger_buffer)

        snapshot = BarSnapshot(
            close_ms=bar.close_ms,
            context_close_ms=ctx.close_ms if ctx is not None else None,
            context_direction=context_direction,
            context_pace=context_pace,
            atr=atr,
            support=support,
            resistance=resistance,
            next_long_trigger=next_long_trigger,
            next_short_trigger=next_short_trigger,
            long_blocker=long_blocker,
            short_blocker=short_blocker,
            new_signal=new_signal,
            new_plan_events=tuple(new_plan_events),
            plan=self._plan.copy(),
            debug={
                "proofs": {
                    f"{'L' if s == SIDE_LONG else 'S'}:{SETUP_NAMES[u]}": v
                    for (s, u), v in proofs.items()
                },
                "ready": dict(ready_now),
                "pace_direction": pace_direction,
                "strong_bull": strong_bull,
                "strong_bear": strong_bear,
                "long_space": long_space,
                "short_space": short_space,
                "long_setup": long_setup,
                "short_setup": short_setup,
                "fast_upper": fast_upper,
                "anchor_upper": anchor_upper,
                "ema5": ema5,
                "ema12": ema12,
                "ctx_ema34": ctx.ema34 if ctx is not None else None,
                "ctx_ema50": ctx.ema50 if ctx is not None else None,
                "tolerance": tolerance,
                "trigger_buffer": trigger_buffer,
                "saty_below": saty_below,
                "saty_above": saty_above,
                "pivot_low": known_pivot_low,
                "pivot_high": known_pivot_high,
            },
        )
        self._snapshots.append(snapshot)

        # ── history bookkeeping ──
        self._bars.append(bar)
        self._fast_upper.append(fast_upper)
        self._fast_lower.append(fast_lower)
        self._tolerance.append(tolerance)
        self._support_hist.append(support)
        self._resistance_hist.append(resistance)
        self._swept_support.append(bool(swept_support))
        self._swept_resistance.append(bool(swept_resistance))
        self._phase_hist.append(phase)
        self._prev_anchor_upper = anchor_upper
        self._prev_anchor_lower = anchor_lower
        self._context_upper_hist.append(context_anchor_upper)
        self._context_lower_hist.append(context_anchor_lower)
        self._ready_prev = ready_now
        return snapshot

    # helpers ---------------------------------------------------------------

    _prev_anchor_upper: float | None = None
    _prev_anchor_lower: float | None = None

    def __post_init_lists__(self) -> None:  # pragma: no cover - documentation
        pass

    @property
    def _context_upper_hist(self) -> list:
        if not hasattr(self, "_ctx_upper_hist"):
            self._ctx_upper_hist: list[float | None] = []
        return self._ctx_upper_hist

    @property
    def _context_lower_hist(self) -> list:
        if not hasattr(self, "_ctx_lower_hist"):
            self._ctx_lower_hist: list[float | None] = []
        return self._ctx_lower_hist

    @staticmethod
    def _setup_priority(setup: int) -> int:
        # f_setup_priority (pine:274-278)
        return {
            SETUP_LEVEL_REJECTION: 4,
            SETUP_PULLBACK_CONTINUATION: 3,
            SETUP_BREAKOUT: 2,
            SETUP_IGNITION: 1,
        }.get(setup, 0)

    def _pick_support(self, reference, current, candidate, tolerance):
        # f_pick_support (pine:226-228)
        eligible = candidate is not None and _le(candidate, _add(reference, tolerance))
        if eligible and (current is None or candidate > current):
            return candidate
        return current

    def _pick_resistance(self, reference, current, candidate, tolerance):
        eligible = candidate is not None and _ge(candidate, _sub(reference, tolerance))
        if eligible and (current is None or candidate < current):
            return candidate
        return current

    def _pick_above(self, reference, current, candidate, tolerance):
        eligible = candidate is not None and _gt(candidate, _add(reference, tolerance))
        if eligible and (current is None or candidate < current):
            return candidate
        return current

    def _pick_below(self, reference, current, candidate, tolerance):
        eligible = candidate is not None and _lt(candidate, _sub(reference, tolerance))
        if eligible and (current is None or candidate > current):
            return candidate
        return current

    def _nearest_saty(self, anchor, daily_atr, reference):
        # f_nearest_saty (pine:260-272)
        if anchor is None or daily_atr is None or daily_atr <= 0:
            return None, None
        below = above = None
        for ratio in self.config.saty_ratios:
            level = anchor + daily_atr * ratio
            if level <= reference and (below is None or level > below):
                below = level
            if level >= reference and (above is None or level < above):
                above = level
        return below, above

    def _window_high(self, lookback: int) -> float | None:
        # ta.highest(high[1], n): highest of the n bars before the current one.
        if len(self._bars) < lookback:
            return None
        return max(b.high for b in self._bars[-lookback:])

    def _window_low(self, lookback: int) -> float | None:
        if len(self._bars) < lookback:
            return None
        return min(b.low for b in self._bars[-lookback:])

    def _prior_test(self, side: int) -> bool:
        # priorTestLong/Short (pine:479-482, 502-505): previous bar touched any
        # of fast/anchor(3m)/context clouds or S1/R1 using that bar's tolerance.
        if not self._bars:
            return False
        prev = self._bars[-1]
        tol = self._tolerance[-1]
        fast_upper = self._fast_upper[-1]
        fast_lower = self._fast_lower[-1]
        anchor_upper = self._prev_anchor_upper
        anchor_lower = self._prev_anchor_lower
        ctx_upper = self._context_upper_hist[-1] if self._context_upper_hist else None
        ctx_lower = self._context_lower_hist[-1] if self._context_lower_hist else None
        if side == SIDE_LONG:
            support_prev = self._support_hist[-1]
            return (
                _le(prev.low, _add(fast_upper, tol))
                or _le(prev.low, _add(anchor_upper, tol))
                or _le(prev.low, _add(ctx_upper, tol))
                or (support_prev is not None and _le(prev.low, _add(support_prev, tol)))
            )
        resistance_prev = self._resistance_hist[-1]
        return (
            _ge(prev.high, _sub(fast_lower, tol))
            or _ge(prev.high, _sub(anchor_lower, tol))
            or _ge(prev.high, _sub(ctx_lower, tol))
            or (resistance_prev is not None and _ge(prev.high, _sub(resistance_prev, tol)))
        )

    def _established_before(self, side: int) -> bool:
        # establishedLongBefore (pine:483-485): close[k] beyond fast cloud with
        # each bar's own tolerance, k in {2,3,4}.
        result = False
        for offset in (2, 3, 4):
            if len(self._bars) < offset:
                continue
            bar = self._bars[-offset]
            fast_upper = self._fast_upper[-offset]
            fast_lower = self._fast_lower[-offset]
            tol = self._tolerance[-offset]
            if side == SIDE_LONG:
                result = result or _gt(bar.close, _add(fast_upper, tol))
            else:
                result = result or _lt(bar.close, _sub(fast_lower, tol))
        return result

    def _update_pivots(self, bar: Bar) -> None:
        # ta.pivotlow/pivothigh(pivotLen, pivotLen) + valuewhen(..., 0)
        # (pine:422-425).  A pivot at bar p confirms pivotLen bars later.
        # Tie handling established empirically against two disambiguating
        # cases in the 2026-07-21 true export: ties are allowed on the LEFT
        # side and rejected on the RIGHT side, so of a flat double bottom/top
        # the most recent bar becomes the pivot.
        n = self.config.pivot_length
        history = self._bars + [bar]
        if len(history) < 2 * n + 1:
            return
        center = history[-(n + 1)]
        left = history[-(2 * n + 1):-(n + 1)]
        right = history[-n:]
        if all(center.low <= b.low for b in left) and all(
            center.low < b.low for b in right
        ):
            self._pivot_low = center.low
        if all(center.high >= b.high for b in left) and all(
            center.high > b.high for b in right
        ):
            self._pivot_high = center.high


# ─────────────────────────────────────────────────────────────────────────────
# TradingView CSV loader (open-time rows -> close-time bars)
# ─────────────────────────────────────────────────────────────────────────────

def load_tradingview_csv(
    path: str | PathLike[str], *, timeframe_minutes: int
) -> tuple[Bar, ...]:
    import csv

    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {
            "time", "open", "high", "low", "close"
        }.issubset(reader.fieldnames):
            raise ValueError("TradingView CSV must contain time/open/high/low/close")
        for row in reader:
            if row.get("time", "").strip().lower() == "time":
                continue
            close_ms = (int(float(row["time"])) + timeframe_minutes * 60) * 1000
            bar = Bar(
                close_ms,
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
            )
            if bars and bar.close_ms <= bars[-1].close_ms:
                raise ValueError("TradingView rows are not strictly ordered")
            bars.append(bar)
    return tuple(bars)
