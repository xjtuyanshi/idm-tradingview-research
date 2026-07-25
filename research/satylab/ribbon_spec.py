"""Reference implementation of the Saty Pivot Ribbon, transcribed from the
author's own published source (github.com/satymahajan/saty_pivot_ribbon).

This file is STANDALONE on purpose: `satylab.indicators` is shared by several
studies running in parallel, so nothing here mutates it.  It imports only the
pure helpers (`ema`, `atr_series`) from it.

What is mechanical (matches the published Pine, no interpretation):
    ribbon EMAs            8 / 21 / 34 on CLOSE of the ribbon timeframe
    conviction EMAs        13 / 48 on CLOSE of the ribbon timeframe
    fast cloud colour      green if ema8 >= ema21 else red
    slow cloud colour      aqua  if ema21 >= ema34 else orange
    conviction state       bull if ema13 >= ema48 else bear
    conviction arrow       plotted on the bar where conviction state flips
    TimeWarp               ribbon computed ON the higher timeframe, then held
                           flat across execution bars until the next higher
                           timeframe bar closes (step function, one HTF bar lag)

What is INFERRED (candidate definitions, flagged as such):
    yummy_* / vomy_*       see SPEC_PIVOT_RIBBON.md; three rival readings are
                           implemented side by side so they can be compared on
                           a chart instead of being guessed at.

Run `python research/satylab/ribbon_spec.py` for the self-check.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime

if __package__ in (None, ""):                                   # script mode
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
    from satylab.data import Bar                                # noqa: E402
    from satylab.indicators import atr_series, ema              # noqa: E402
else:
    from .data import Bar
    from .indicators import atr_series, ema

# ---------------------------------------------------------------- constants
FAST = 8            # "fast ema"
PIVOT = 21          # "pivot ema"  -- the H21 / D21 / W21 of Saty's language
SLOW = 34           # "slow ema"
CONV_FAST = 13      # conviction ema (fast)
CONV_SLOW = 48      # conviction ema (slow)


# ---------------------------------------------------------------- resampling
def resample(bars: list[Bar], factor: int) -> list[Bar]:
    """Aggregate `factor` consecutive bars into one, never crossing a session.

    5m x 2 -> 10m, 5m x 3 -> 15m, 5m x 6 -> 30m.  Grouping restarts each day so
    the first aggregate bar of a session always opens at the session open, which
    is how TradingView aligns intraday higher timeframes on RTH charts.
    """
    out: list[Bar] = []
    by_day: dict[date, list[Bar]] = {}
    order: list[date] = []
    for b in bars:
        if b.day not in by_day:
            by_day[b.day] = []
            order.append(b.day)
        by_day[b.day].append(b)
    for day in order:
        rows = by_day[day]
        for i in range(0, len(rows), factor):
            chunk = rows[i:i + factor]
            out.append(Bar(
                dt=chunk[0].dt, day=day,
                open=chunk[0].open,
                high=max(c.high for c in chunk),
                low=min(c.low for c in chunk),
                close=chunk[-1].close,
                volume=sum(c.volume for c in chunk),
            ))
    return out


# ---------------------------------------------------------------- ribbon frame
@dataclass(frozen=True, slots=True)
class Frame:
    """One bar's worth of ribbon state.  All fields are what the indicator draws."""
    dt: datetime
    close: float
    high: float
    low: float
    e8: float
    e21: float
    e34: float
    e13: float | None
    e48: float | None
    atr: float | None

    # --- exactly what the published script colours -------------------------
    @property
    def fast_cloud_bull(self) -> bool:          # green vs red
        return self.e8 >= self.e21

    @property
    def slow_cloud_bull(self) -> bool:          # aqua vs orange
        return self.e21 >= self.e34

    @property
    def conviction_bull(self) -> bool | None:   # 13/48, drives the arrows
        if self.e13 is None or self.e48 is None:
            return None
        return self.e13 >= self.e48

    # --- derived, still mechanical ----------------------------------------
    @property
    def state(self) -> str:
        """4-state ribbon reading. 'folded' == the two clouds disagree."""
        if self.fast_cloud_bull and self.slow_cloud_bull:
            return "full_bull"
        if not self.fast_cloud_bull and not self.slow_cloud_bull:
            return "full_bear"
        return "folded"

    @property
    def body_hi(self) -> float:
        return max(self.e8, self.e21, self.e34)

    @property
    def body_lo(self) -> float:
        return min(self.e8, self.e21, self.e34)

    @property
    def price_zone(self) -> str:
        if self.close > self.body_hi:
            return "above"
        if self.close < self.body_lo:
            return "below"
        return "inside"

    @property
    def thickness(self) -> float | None:
        """|ema8 - ema34| in ATR units.  Saty's 'thick / clear trend' proxy."""
        if self.atr is None or self.atr <= 0:
            return None
        return abs(self.e8 - self.e34) / self.atr


def frames(bars: list[Bar], fast: int = FAST, pivot: int = PIVOT,
           slow: int = SLOW, conv_fast: int = CONV_FAST,
           conv_slow: int = CONV_SLOW, atr_len: int = 14) -> list[Frame | None]:
    """Compute the ribbon on the timeframe of `bars`.  Source = close (per source)."""
    closes = [b.close for b in bars]
    e8, e21, e34 = ema(closes, fast), ema(closes, pivot), ema(closes, slow)
    e13, e48 = ema(closes, conv_fast), ema(closes, conv_slow)
    a = atr_series(bars, atr_len)
    out: list[Frame | None] = []
    for i, b in enumerate(bars):
        if e8[i] is None or e21[i] is None or e34[i] is None:
            out.append(None)
            continue
        out.append(Frame(b.dt, b.close, b.high, b.low,
                         e8[i], e21[i], e34[i], e13[i], e48[i], a[i]))
    return out


# ---------------------------------------------------------------- time warp
def timewarp(exec_bars: list[Bar], htf_bars: list[Bar],
             htf_frames: list[Frame | None] | None = None,
             lag: int = 1) -> list[Frame | None]:
    """Project a higher-timeframe ribbon onto execution bars.

    Semantics of the published Pine (`request.security(..., lookahead_off)` with
    the `[barstate.isrealtime ? 1 : 0]` realtime offset): an execution bar shows
    the EMA values of the most recently CLOSED higher-timeframe bar.  The series
    is therefore a STEP function -- flat for every execution bar inside a forming
    HTF bar, stepping only at HTF boundaries.  It is not a resample and it does
    not repaint on closed bars.

    `lag=1` is the faithful setting (the HTF bar containing the execution bar has
    not closed yet).  `lag=0` uses the containing bar and IS lookahead -- exposed
    only so the sensitivity of a result to this convention can be measured.
    """
    if htf_frames is None:
        htf_frames = frames(htf_bars)
    out: list[Frame | None] = []
    j = -1
    for b in exec_bars:
        while j + 1 < len(htf_bars) and htf_bars[j + 1].dt <= b.dt:
            j += 1
        k = j - lag
        out.append(htf_frames[k] if 0 <= k < len(htf_frames) else None)
    return out


# ---------------------------------------------------------------- events
def fold_events(fs: list[Frame | None]) -> list[str | None]:
    """Per-bar label for Saty's 'ribbon folding' = an EMA crossover.

    fast_fold_up   ema8 crosses above ema21   (fast cloud turns green)
    fast_fold_down ema8 crosses below ema21   (fast cloud turns red)
    slow_fold_up   ema21 crosses above ema34  (slow cloud turns aqua)
    slow_fold_down ema21 crosses below ema34  (slow cloud turns orange)
    """
    out: list[str | None] = [None] * len(fs)
    for i in range(1, len(fs)):
        a, b = fs[i - 1], fs[i]
        if a is None or b is None:
            continue
        if not a.fast_cloud_bull and b.fast_cloud_bull:
            out[i] = "fast_fold_up"
        elif a.fast_cloud_bull and not b.fast_cloud_bull:
            out[i] = "fast_fold_down"
        elif not a.slow_cloud_bull and b.slow_cloud_bull:
            out[i] = "slow_fold_up"
        elif a.slow_cloud_bull and not b.slow_cloud_bull:
            out[i] = "slow_fold_down"
    return out


def conviction_arrows(fs: list[Frame | None]) -> list[str | None]:
    """Exactly the published rule: arrow on the bar where 13/48 state flips."""
    out: list[str | None] = [None] * len(fs)
    for i in range(1, len(fs)):
        a, b = fs[i - 1], fs[i]
        if a is None or b is None:
            continue
        pa, pb = a.conviction_bull, b.conviction_bull
        if pa is None or pb is None:
            continue
        if pb and not pa:
            out[i] = "bullish_conviction"
        elif pa and not pb:
            out[i] = "bearish_conviction"
    return out


# ------------------------------------------------- H21 / D21 language, mechanical
def holding_pivot(f: Frame, tol_atr: float = 0.0) -> bool:
    """'holding H21' / 'holding the 21': bar traded down into the pivot EMA and
    closed back above it.  tol_atr widens the touch test by that many ATR."""
    if f.atr is None:
        return False
    touch = f.low <= f.e21 + tol_atr * f.atr
    return touch and f.close > f.e21


def rejected_ribbon(f: Frame, bearish: bool = True, tol_atr: float = 0.0) -> bool:
    """'rejected bearish daily ribbon': price pushed INTO a bear-stacked ribbon
    body from below and closed back under it (mirror for the bullish case)."""
    if f.atr is None:
        return False
    pad = tol_atr * (f.atr or 0.0)
    if bearish:
        return f.state == "full_bear" and f.high >= f.body_lo - pad and f.close < f.body_lo
    return f.state == "full_bull" and f.low <= f.body_hi + pad and f.close > f.body_hi


# ---------------------------------------------------------------- YUMMY / VOMY
# INFERRED.  Public sources document "Vomy" (bearish) only, and only loosely.
# Three rival readings, all bearish; each has a `yummy_*` mirror.
# See research/reports/SPEC_PIVOT_RIBBON.md section 4 for the evidence behind each.

def _trend_established(fs: list[Frame | None], i: int, bull: bool,
                       lookback: int, min_thick: float) -> bool:
    """Was the ribbon in a clear, thick, correctly-stacked trend recently?"""
    want = "full_bull" if bull else "full_bear"
    for k in range(max(0, i - lookback), i):
        f = fs[k]
        if f is None or f.thickness is None:
            continue
        if f.state == want and f.thickness >= min_thick:
            return True
    return False


def vomy_v1(fs: list[Frame | None], i: int, lookback: int = 20,
            min_thick: float = 1.0) -> bool:
    """V1 -- CONVICTION BREAK (best third-party support: the "Dolphin Vomit").

    Prior thick bull-stacked ribbon within `lookback`, ribbon no longer full_bull
    now, and this bar closes below the 48 conviction EMA for the first time.
    """
    f, p = fs[i], fs[i - 1] if i else None
    if f is None or p is None or f.e48 is None or p.e48 is None:
        return False
    return (_trend_established(fs, i, True, lookback, min_thick)
            and f.state != "full_bull"
            and p.close >= p.e48 and f.close < f.e48)


def yummy_v1(fs: list[Frame | None], i: int, lookback: int = 20,
             min_thick: float = 1.0) -> bool:
    f, p = fs[i], fs[i - 1] if i else None
    if f is None or p is None or f.e48 is None or p.e48 is None:
        return False
    return (_trend_established(fs, i, False, lookback, min_thick)
            and f.state != "full_bear"
            and p.close <= p.e48 and f.close > f.e48)


def vomy_v2(fs: list[Frame | None], i: int) -> bool:
    """V2 -- CONVICTION ARROW (the indicator's own primitive, no extra rules).

    Bearish conviction arrow: ema13 crosses under ema48 on this bar.
    """
    a, b = (fs[i - 1] if i else None), fs[i]
    if a is None or b is None:
        return False
    pa, pb = a.conviction_bull, b.conviction_bull
    return pa is True and pb is False


def yummy_v2(fs: list[Frame | None], i: int) -> bool:
    a, b = (fs[i - 1] if i else None), fs[i]
    if a is None or b is None:
        return False
    pa, pb = a.conviction_bull, b.conviction_bull
    return pa is False and pb is True


def vomy_v3(fs: list[Frame | None], i: int, lookback: int = 20,
            min_thick: float = 1.0) -> bool:
    """V3 -- FULL RIBBON FLIP (pure shape reading, ignores the 48).

    Prior thick bull stack within `lookback`, and the ribbon completes the fold
    to a full bear stack (8 < 21 < 34) on this bar.
    """
    a, b = (fs[i - 1] if i else None), fs[i]
    if a is None or b is None:
        return False
    return (_trend_established(fs, i, True, lookback, min_thick)
            and a.state != "full_bear" and b.state == "full_bear")


def yummy_v3(fs: list[Frame | None], i: int, lookback: int = 20,
             min_thick: float = 1.0) -> bool:
    a, b = (fs[i - 1] if i else None), fs[i]
    if a is None or b is None:
        return False
    return (_trend_established(fs, i, False, lookback, min_thick)
            and a.state != "full_bull" and b.state == "full_bull")


# ---------------------------------------------------------------- self-check
def _selfcheck() -> None:
    if __package__ in (None, ""):
        from satylab import data
    else:
        from . import data

    print("=" * 74)
    print("Saty Pivot Ribbon reference implementation -- self-check")
    print("=" * 74)

    f5 = data.fine()
    b10 = resample(f5, 2)
    print(f"\n5m bars: {len(f5)}   ->  10m bars: {len(b10)}   "
          f"({f5[0].day} .. {f5[-1].day})")

    fs10 = frames(b10)
    ok = [f for f in fs10 if f is not None]
    print(f"10m frames with full ribbon: {len(ok)}")

    dist: dict[str, int] = {}
    for f in ok:
        dist[f.state] = dist.get(f.state, 0) + 1
    print("\n10m ribbon state distribution:")
    for k in ("full_bull", "full_bear", "folded"):
        n = dist.get(k, 0)
        print(f"   {k:<10} {n:5d}  {100.0 * n / len(ok):5.1f}%")

    zdist: dict[str, int] = {}
    for f in ok:
        zdist[f.price_zone] = zdist.get(f.price_zone, 0) + 1
    print("\nprice vs ribbon body:")
    for k in ("above", "inside", "below"):
        n = zdist.get(k, 0)
        print(f"   {k:<10} {n:5d}  {100.0 * n / len(ok):5.1f}%")

    folds = [x for x in fold_events(fs10) if x]
    arrows = [x for x in conviction_arrows(fs10) if x]
    print(f"\nfold events on 10m: {len(folds)}   "
          f"conviction arrows on 10m: {len(arrows)}")

    print("\ncandidate Yummy/Vomy event counts on 10m "
          f"({len(set(b.day for b in b10))} sessions):")
    for name, fn in (("vomy_v1", vomy_v1), ("yummy_v1", yummy_v1),
                     ("vomy_v2", vomy_v2), ("yummy_v2", yummy_v2),
                     ("vomy_v3", vomy_v3), ("yummy_v3", yummy_v3)):
        hits = [i for i in range(1, len(fs10)) if fn(fs10, i)]
        per_day = len(hits) / max(1, len(set(b.day for b in b10)))
        print(f"   {name:<9} {len(hits):4d}   {per_day:.2f}/session")

    # how much do the three readings actually disagree?
    s1 = {i for i in range(1, len(fs10)) if vomy_v1(fs10, i)}
    s2 = {i for i in range(1, len(fs10)) if vomy_v2(fs10, i)}
    s3 = {i for i in range(1, len(fs10)) if vomy_v3(fs10, i)}
    print(f"\n   vomy_v1 & vomy_v2 same bar: {len(s1 & s2)}")
    print(f"   vomy_v1 & vomy_v3 same bar: {len(s1 & s3)}")
    print(f"   vomy_v2 & vomy_v3 same bar: {len(s2 & s3)}")

    # TimeWarp: lag convention sensitivity
    tw1 = timewarp(f5, b10, fs10, lag=1)
    tw0 = timewarp(f5, b10, fs10, lag=0)
    both = [(a, b) for a, b in zip(tw1, tw0) if a is not None and b is not None]
    diff = sum(1 for a, b in both if a.state != b.state)
    print(f"\nTimeWarp 10m->5m: {len(both)} comparable exec bars; "
          f"state differs under lag=0 vs lag=1 on {diff} "
          f"({100.0 * diff / max(1, len(both)):.1f}%)")

    # H21 / D21 language on their native timeframes
    h = data.hourly()
    fh = frames(h)
    hold = sum(1 for f in fh if f is not None and holding_pivot(f))
    print(f"\nhourly bars {len(h)}: 'holding H21' bars = {hold} "
          f"({100.0 * hold / max(1, len([f for f in fh if f])):.1f}%)")

    d = data.daily()
    fd = frames(d)
    okd = [f for f in fd if f is not None]
    rej = sum(1 for f in okd if rejected_ribbon(f, bearish=True))
    ddist: dict[str, int] = {}
    for f in okd:
        ddist[f.state] = ddist.get(f.state, 0) + 1
    print(f"daily bars {len(d)}: 'rejected bearish daily ribbon' bars = {rej}")
    print(f"daily ribbon states: {ddist}")
    print("\n" + "=" * 74)
    print("NOTE: our bars are RTH-only.  Saty's own templates are ETH.")
    print("      An 8/21/34 EMA on ETH bars is NOT the same series -- see")
    print("      research/reports/SPEC_PIVOT_RIBBON.md section 6.")
    print("=" * 74)


if __name__ == "__main__":
    _selfcheck()
