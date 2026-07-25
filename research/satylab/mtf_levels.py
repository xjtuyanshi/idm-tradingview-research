"""Multi-timeframe ATR levels — Weekly / Monthly / Quarterly.

Saty's weekly note for 2026-07-26 reads:

    "We are still in the **monthly trigger box roughly between 7400 and 7600**.
     Weaker stance going into next week under D21 and H200 ... Bounced -1
     Monthly ATR ... Below that can see -1 Quarterly ATR."

Our engine only ever built the DAILY ladder, so none of that language was
representable — and the two weeks he calls "hard mode" are exactly the window
our forward test lost money in.  This module builds the same ladder on higher
timeframes so the regime becomes measurable instead of anecdotal.

Construction is identical to the daily map, one timeframe up: anchor is the
prior period's close, ATR is Wilder(14) over prior periods, and the "trigger
box" is anchor +/- 0.236 * ATR — the same ratio that names the daily call/put
triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .data import Bar
from .levels import DayLevels, wilder_atr


def resample(daily: list[Bar], period: str) -> list[Bar]:
    """Aggregate daily bars into weekly / monthly / quarterly bars."""
    def key(d: date):
        if period == "W":
            iso = d.isocalendar()
            return (iso[0], iso[1])
        if period == "M":
            return (d.year, d.month)
        if period == "Q":
            return (d.year, (d.month - 1) // 3)
        raise ValueError(period)

    out: list[Bar] = []
    cur_key = None
    bucket: list[Bar] = []
    for b in daily:
        k = key(b.day)
        if cur_key is None:
            cur_key = k
        if k != cur_key:
            out.append(_agg(bucket))
            bucket, cur_key = [], k
        bucket.append(b)
    if bucket:
        out.append(_agg(bucket))
    return out


def _agg(rows: list[Bar]) -> Bar:
    return Bar(rows[-1].dt, rows[-1].day, rows[0].open,
               max(r.high for r in rows), min(r.low for r in rows),
               rows[-1].close, sum(r.volume for r in rows))


@dataclass(frozen=True, slots=True)
class MtfMap:
    """Higher-timeframe level map, valid for every day inside the period."""
    period_start: date
    anchor: float
    atr: float

    def at(self, ratio: float) -> float:
        return self.anchor + ratio * self.atr

    def ratio_of(self, price: float) -> float:
        return (price - self.anchor) / self.atr

    def in_trigger_box(self, price: float) -> bool:
        return abs(self.ratio_of(price)) < 0.236

    def box(self) -> tuple[float, float]:
        return self.at(-0.236), self.at(0.236)


def build_mtf(daily: list[Bar], period: str) -> dict[date, MtfMap]:
    """day -> the higher-timeframe map in force that day (prior period only)."""
    periods = resample(daily, period)
    atr = wilder_atr(periods)
    maps: list[tuple[date, MtfMap]] = []
    for i in range(1, len(periods)):
        prev, prev_atr = periods[i - 1], atr[i - 1]
        if prev_atr is None or prev_atr <= 0:
            continue
        # this map takes effect the day AFTER the prior period closed
        maps.append((prev.day, MtfMap(prev.day, prev.close, prev_atr)))

    out: dict[date, MtfMap] = {}
    j = -1
    for b in daily:
        while j + 1 < len(maps) and maps[j + 1][0] < b.day:
            j += 1
        if j >= 0:
            out[b.day] = maps[j][1]
    return out


def regime_label(price: float, m: MtfMap | None) -> str:
    """Where today sits inside the higher-timeframe structure."""
    if m is None:
        return "na"
    r = m.ratio_of(price)
    if abs(r) < 0.236:
        return "trigger_box"          # compressed, no higher-tf direction yet
    if abs(r) < 0.618:
        return "gg_zone"
    if abs(r) < 1.0:
        return "extended"
    return "beyond_1atr"
