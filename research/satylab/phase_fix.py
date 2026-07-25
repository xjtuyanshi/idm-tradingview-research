"""Saty Phase Oscillator — faithful port of the published Pine v5 source.

WHY THIS FILE EXISTS
--------------------
`satylab.indicators.phase_oscillator` was a guess: ``(close - EMA21) / ATR14 * 100``.
The real indicator, whose source was pulled straight off TradingView's own
pine-facade endpoint for the live published script
(``PUB;f27506d00fc64f30b880835f6847ac6e``, created 2026-01-11,
"Saty Phase Oscillator / Copyright (C) 2022-2026 Saty Mahajan"), is::

    pivot      = ta.ema(close, 21)
    atr        = ta.atr(14)                       # Wilder / RMA, SAME timeframe
    raw_signal = ((close - pivot) / (3.0 * atr)) * 100
    oscillator = ta.ema(raw_signal, 3)

So the guess was wrong twice over:
  1. the denominator is **3 x ATR**, not 1 x ATR  -> guess ran ~3x too hot;
  2. the plotted value is **EMA(3)-smoothed**, not raw.
+/-100 therefore means "close is 3 ATR away from the 21 EMA *of this chart's
timeframe*".  It is NOT the daily ATR that Saty ATR Levels uses — on a 3m chart
the Phase Oscillator measures 3m ATRs.  That is what makes "3m extreme while
10m has room" a meaningful sentence.

The compression flag ("Compression" table label, magenta/grey plot) is a
Bollinger-inside-Keltner squeeze::

    compression       = 2*stdev(close,21) - 2.000*atr(14)
    in_expansion_zone = 2*stdev(close,21) - 1.854*atr(14)
    expansion         = compression[1] <= compression[0]     # gap widening
    tracker = false if (expansion and in_expansion_zone > 0)
              else true if compression <= 0
              else false

(In the Pine source both `compression` and `in_expansion_zone` are written as
above_pivot ? (bband_up - threshold_up) : (threshold_down - bband_down); the two
branches are algebraically identical, so `above_pivot` does not actually affect
the flag.  `verify_compression_branches` below proves that on real data.)

Everything here is verified against the two independent third-party ports that
agree line-for-line (rishid/thinkscripts `saty_phase_oscillator.tosts`, and a
2024-era Pine copy in krithin98/Whispr); see
research/reports/SPEC_PHASE_OSCILLATOR.md.

This module deliberately does not touch `satylab.indicators` — parallel studies
import that.  Import from here instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .data import Bar

# ---------------------------------------------------------------------------
# constants straight out of the published source
# ---------------------------------------------------------------------------

PIVOT_LEN = 21          # ta.ema(close, 21)
ATR_LEN = 14            # ta.atr(14)
ATR_MULT = 3.0          # (close - pivot) / (3.0 * atr)
SIGNAL_SMOOTH = 3       # ta.ema(raw_signal, 3)

STDEV_LEN = 21          # ta.stdev(close, 21)
BB_MULT = 2.0           # 2.0 * stdev
COMPRESSION_MULT = 2.0  # pivot +/- 2.000 * atr
EXPANSION_MULT = 1.854  # pivot +/- 1.854 * atr

EXTREME = 100.0
DISTRIBUTION = 61.8     # +61.8 "Distribution Zone"
ACCUMULATION = -61.8    # -61.8 "Accumulation Zone"
LAUNCH = 23.6           # +/-23.6 "Neutral / Launch Zone"
RAILS = (100.0, 61.8, 23.6, -23.6, -61.8, -100.0)


# ---------------------------------------------------------------------------
# Pine primitives
# ---------------------------------------------------------------------------

def ta_ema(values: list[float | None], length: int) -> list[float | None]:
    """`ta.ema` — SMA-seeded EMA. Leading `None`s are skipped, matching Pine's
    behaviour of only starting to accumulate once the source is non-na."""
    out: list[float | None] = [None] * len(values)
    buf: list[float] = []
    prev: float | None = None
    k = 2.0 / (length + 1.0)
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            buf.append(v)
            if len(buf) == length:
                prev = sum(buf) / length
                out[i] = prev
        else:
            prev = (v - prev) * k + prev
            out[i] = prev
    return out


def ta_rma(values: list[float], length: int) -> list[float | None]:
    """`ta.rma` — Wilder smoothing, SMA-seeded (what `ta.atr` uses)."""
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    prev = sum(values[:length]) / length
    out[length - 1] = prev
    for i in range(length, len(values)):
        prev = (prev * (length - 1) + values[i]) / length
        out[i] = prev
    return out


def ta_atr(bars: list[Bar], length: int = ATR_LEN) -> list[float | None]:
    """`ta.atr(length)` = ta.rma(ta.tr(true), length).  First bar's TR = h - l."""
    trs: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            trs.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    return ta_rma(trs, length)


def ta_stdev(values: list[float], length: int = STDEV_LEN,
             biased: bool = True) -> list[float | None]:
    """`ta.stdev(source, length)` — Pine's default is biased=true, i.e. the
    POPULATION standard deviation (divide by N), taken around the SMA."""
    out: list[float | None] = [None] * len(values)
    denom = length if biased else (length - 1)
    for i in range(length - 1, len(values)):
        win = values[i - length + 1:i + 1]
        m = sum(win) / length
        out[i] = sqrt(sum((x - m) ** 2 for x in win) / denom)
    return out


# ---------------------------------------------------------------------------
# the oscillator
# ---------------------------------------------------------------------------

def phase_oscillator(bars: list[Bar]) -> list[float | None]:
    """Saty Phase Oscillator, computed on the timeframe of `bars`.

    Returns the *plotted* value (EMA-3 smoothed).  Feed it 3m bars for the 3m
    reading, 10m bars for the 10m reading — that pair is Saty's "Day 3/10"
    template, and reading both at once is his Time Warp.
    """
    closes = [b.close for b in bars]
    pivot = ta_ema(closes, PIVOT_LEN)          # type: ignore[arg-type]
    atr = ta_atr(bars, ATR_LEN)
    raw: list[float | None] = []
    for i, b in enumerate(bars):
        p, a = pivot[i], atr[i]
        if p is None or a is None or a <= 0:
            raw.append(None)
        else:
            raw.append((b.close - p) / (ATR_MULT * a) * 100.0)
    return ta_ema(raw, SIGNAL_SMOOTH)


def phase_raw(bars: list[Bar]) -> list[float | None]:
    """The unsmoothed `raw_signal`.  Exposed only for diagnostics — the
    indicator on the chart plots the EMA-3 of this, never this."""
    closes = [b.close for b in bars]
    pivot = ta_ema(closes, PIVOT_LEN)          # type: ignore[arg-type]
    atr = ta_atr(bars, ATR_LEN)
    out: list[float | None] = []
    for i, b in enumerate(bars):
        p, a = pivot[i], atr[i]
        out.append(None if (p is None or a is None or a <= 0)
                   else (b.close - p) / (ATR_MULT * a) * 100.0)
    return out


# ---------------------------------------------------------------------------
# compression (the "Compression" label)
# ---------------------------------------------------------------------------

def compression_tracker(bars: list[Bar], biased_stdev: bool = True
                        ) -> list[bool | None]:
    """The magenta/grey squeeze flag and the "Compression" table label.

    True  <=> the 2-sigma Bollinger width sits inside the 2 x ATR Keltner width
              (with an early release once sigma pushes past 0.927 x ATR *and*
              the gap is widening).
    """
    closes = [b.close for b in bars]
    pivot = ta_ema(closes, PIVOT_LEN)          # type: ignore[arg-type]
    atr = ta_atr(bars, ATR_LEN)
    sd = ta_stdev(closes, STDEV_LEN, biased=biased_stdev)

    comp: list[float | None] = []
    expz: list[float | None] = []
    for i in range(len(bars)):
        if pivot[i] is None or atr[i] is None or sd[i] is None:
            comp.append(None)
            expz.append(None)
        else:
            comp.append(BB_MULT * sd[i] - COMPRESSION_MULT * atr[i])
            expz.append(BB_MULT * sd[i] - EXPANSION_MULT * atr[i])

    out: list[bool | None] = []
    for i in range(len(bars)):
        if comp[i] is None:
            out.append(None)
            continue
        prev = comp[i - 1] if i > 0 else None
        expansion = (prev is not None) and (prev <= comp[i])
        if expansion and expz[i] > 0:
            out.append(False)
        elif comp[i] <= 0:
            out.append(True)
        else:
            out.append(False)
    return out


def verify_compression_branches(bars: list[Bar]) -> dict[str, int]:
    """Prove the `above_pivot ? ... : ...` branch in the Pine source is a no-op.

    up   branch = (pivot + 2*sd) - (pivot + 2*atr) = 2*sd - 2*atr
    down branch = (pivot - 2*atr) - (pivot - 2*sd) = 2*sd - 2*atr
    Identical.  This walks real bars and counts any disagreement > 1e-9.
    """
    closes = [b.close for b in bars]
    pivot = ta_ema(closes, PIVOT_LEN)          # type: ignore[arg-type]
    atr = ta_atr(bars, ATR_LEN)
    sd = ta_stdev(closes, STDEV_LEN)
    checked = mismatch = 0
    for i, b in enumerate(bars):
        if pivot[i] is None or atr[i] is None or sd[i] is None:
            continue
        up = (pivot[i] + BB_MULT * sd[i]) - (pivot[i] + COMPRESSION_MULT * atr[i])
        dn = (pivot[i] - COMPRESSION_MULT * atr[i]) - (pivot[i] - BB_MULT * sd[i])
        checked += 1
        if abs(up - dn) > 1e-9:
            mismatch += 1
    return {"checked": checked, "mismatch": mismatch}


# ---------------------------------------------------------------------------
# zones — names taken verbatim from Saty's own scanning plots
# ---------------------------------------------------------------------------

#   extended_up      osc >= 100                 "Extreme"
#   in_distribution  61.8 <= osc < 100          "Distribution Zone"
#   in_mark_up       23.6 <  osc < 61.8         Wyckoff "Mark Up"
#   in_launch_box    -23.6 <= osc <= 23.6       "Neutral / Launch Zone"
#   in_mark_down     -61.8 < osc < -23.6        Wyckoff "Mark Down"
#   in_accumulation  -100 < osc <= -61.8        "Accumulation Zone"
#   extended_down    osc <= -100                "Extreme"
ZONE_ORDER = ("extended_down", "accumulation", "mark_down", "launch_box",
              "mark_up", "distribution", "extended_up")

#: Saty's own numeric encoding of the `phase` scanning plot.
ZONE_CODE = {"launch_box": 0, "mark_up": 1, "mark_down": -1,
             "accumulation": -2, "distribution": 2,
             "extended_down": -3, "extended_up": 3}


def phase_zone(value: float | None) -> str:
    """Exact boundary handling copied from the thinkScript scanning plots."""
    if value is None:
        return "na"
    if value >= 100.0:
        return "extended_up"
    if value >= 61.8:
        return "distribution"
    if value > 23.6:
        return "mark_up"
    if value >= -23.6:
        return "launch_box"
    if value > -61.8:
        return "mark_down"
    if value > -100.0:
        return "accumulation"
    return "extended_down"


def phase_code(value: float | None) -> int | None:
    z = phase_zone(value)
    return None if z == "na" else ZONE_CODE[z]


def is_extreme(value: float | None) -> bool:
    """Saty's word "extreme" == outside the +/-100 rails."""
    return value is not None and abs(value) >= 100.0


# ---------------------------------------------------------------------------
# the four "yellow light" mean-reversion crossover dots
# ---------------------------------------------------------------------------

CROSS_NAMES = ("leaving_accumulation", "leaving_extreme_down",
               "leaving_distribution", "leaving_extreme_up")


def crossovers(osc: list[float | None]) -> list[tuple[str, ...]]:
    """Per-bar tuple of the crossover events the indicator prints as yellow dots.

    leaving_accumulation  osc[1] <= -61.8 and osc >  -61.8
    leaving_extreme_down  osc[1] <= -100  and osc >  -100
    leaving_distribution  osc[1] >=  61.8 and osc <   61.8
    leaving_extreme_up    osc[1] >=  100  and osc <   100
    """
    out: list[tuple[str, ...]] = [()]
    for i in range(1, len(osc)):
        p, c = osc[i - 1], osc[i]
        if p is None or c is None:
            out.append(())
            continue
        ev: list[str] = []
        if p <= -61.8 and c > -61.8:
            ev.append("leaving_accumulation")
        if p <= -100.0 and c > -100.0:
            ev.append("leaving_extreme_down")
        if p >= 61.8 and c < 61.8:
            ev.append("leaving_distribution")
        if p >= 100.0 and c < 100.0:
            ev.append("leaving_extreme_up")
        out.append(tuple(ev))
    return out


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PhaseState:
    value: float | None
    zone: str
    compressed: bool | None
    events: tuple[str, ...]

    @property
    def extreme(self) -> bool:
        return is_extreme(self.value)

    @property
    def bullish(self) -> bool | None:
        """Plot colour: green at/above zero, red below (grey when compressed)."""
        return None if self.value is None else self.value >= 0.0


def phase_states(bars: list[Bar]) -> list[PhaseState]:
    osc = phase_oscillator(bars)
    comp = compression_tracker(bars)
    xs = crossovers(osc)
    return [PhaseState(osc[i], phase_zone(osc[i]), comp[i], xs[i])
            for i in range(len(bars))]
