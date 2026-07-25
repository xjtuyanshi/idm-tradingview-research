"""Saty's own indicator set, rebuilt so studies measure his system, not ours.

The previous engine substituted Ripster 5/12 + 34/50 clouds for Saty's Pivot
Ribbon — measuring one author's setups with another author's ruler.  These are
the mechanical parts of Saty's stack:

  Pivot Ribbon      8 EMA vs 21 EMA (+ optional 34 EMA context).  Structure is
                    read from the ordering of the EMAs and where price sits
                    relative to the ribbon body.
  TimeWarp          the ribbon computed on a HIGHER timeframe and drawn on the
                    execution chart — Saty's standard multi-timeframe device
                    (his "Day 3/10" template = 3m chart, 10m TimeWarp ribbon).
  Phase Oscillator  distance from the 21 EMA measured in ATR units, scaled so
                    +/-1 ATR = +/-100; zone rails at 100 / 61.8 / 23.6 and the
                    negatives, matching the rails visible on the user's chart.

Exact naming of the discretionary states (Yummy / Vomy) is pinned by the
Discord study; what is implemented here is only what is mechanically checkable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data import Bar

FAST = 8
SLOW = 21
CONTEXT = 34


def ema(values: list[float], length: int) -> list[float | None]:
    """SMA-seeded EMA, matching TradingView's ta.ema warm-up behaviour."""
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    seed = sum(values[:length]) / length
    out[length - 1] = seed
    k = 2.0 / (length + 1.0)
    prev = seed
    for i in range(length, len(values)):
        prev = (values[i] - prev) * k + prev
        out[i] = prev
    return out


def atr_series(bars: list[Bar], length: int = 14) -> list[float | None]:
    trs: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            trs.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    out: list[float | None] = [None] * len(bars)
    if len(bars) < length:
        return out
    prev = sum(trs[:length]) / length
    out[length - 1] = prev
    for i in range(length, len(bars)):
        prev = (prev * (length - 1) + trs[i]) / length
        out[i] = prev
    return out


@dataclass(frozen=True, slots=True)
class RibbonState:
    fast: float
    slow: float
    context: float | None
    close: float

    @property
    def bullish_stack(self) -> bool:
        return self.fast > self.slow

    @property
    def above(self) -> bool:
        """Price clear of the ribbon body on the upside."""
        return self.close > max(self.fast, self.slow)

    @property
    def below(self) -> bool:
        return self.close < min(self.fast, self.slow)

    @property
    def inside(self) -> bool:
        return not (self.above or self.below)

    def label(self) -> str:
        """Coarse, checkable structure label used by every base-rate table."""
        if self.above and self.bullish_stack:
            return "bull_trend"        # price above a bull-stacked ribbon
        if self.below and not self.bullish_stack:
            return "bear_trend"
        if self.inside:
            return "in_ribbon"         # pullback / indecision inside the body
        return "conflict"              # price and stack disagree


def ribbon(bars: list[Bar], fast: int = FAST, slow: int = SLOW,
           context: int = CONTEXT) -> list[RibbonState | None]:
    closes = [b.close for b in bars]
    ef, es, ec = ema(closes, fast), ema(closes, slow), ema(closes, context)
    out: list[RibbonState | None] = []
    for i, b in enumerate(bars):
        if ef[i] is None or es[i] is None:
            out.append(None)
        else:
            out.append(RibbonState(ef[i], es[i], ec[i], b.close))
    return out


def timewarp(exec_bars: list[Bar], higher_bars: list[Bar],
             fast: int = FAST, slow: int = SLOW,
             context: int = CONTEXT) -> list[RibbonState | None]:
    """Higher-timeframe ribbon projected onto the execution bars.

    Each execution bar reads the most recent *completed* higher-timeframe bar,
    so nothing from the future leaks in — the same discipline the Pine relay
    uses when it re-derives 3m state on the 10m host.
    """
    hi_states = ribbon(higher_bars, fast, slow, context)
    out: list[RibbonState | None] = []
    j = -1
    for b in exec_bars:
        while j + 1 < len(higher_bars) and higher_bars[j + 1].dt <= b.dt:
            j += 1
        # j indexes the higher bar containing b; use the previous, completed one
        out.append(hi_states[j - 1] if j - 1 >= 0 else None)
    return out


PHASE_RAILS = (100.0, 61.8, 23.6, -23.6, -61.8, -100.0)


def phase_oscillator(bars: list[Bar], length: int = SLOW,
                     atr_len: int = 14) -> list[float | None]:
    """Distance from the 21 EMA in ATR units, scaled so 1 ATR = 100."""
    closes = [b.close for b in bars]
    e = ema(closes, length)
    a = atr_series(bars, atr_len)
    out: list[float | None] = []
    for i, b in enumerate(bars):
        if e[i] is None or a[i] is None or a[i] <= 0:
            out.append(None)
        else:
            out.append((b.close - e[i]) / a[i] * 100.0)
    return out


def phase_zone(value: float | None) -> str:
    if value is None:
        return "na"
    if value >= 100:
        return "extended_up"
    if value >= 61.8:
        return "distribution"
    if value >= 23.6:
        return "bull_mean_rev"
    if value > -23.6:
        return "neutral"
    if value > -61.8:
        return "bear_mean_rev"
    if value > -100:
        return "accumulation"
    return "extended_down"
