#!/usr/bin/env python3
"""Task 3 — what Saty's three qualitative words became when I mechanised them.

v14 turned three of Saty's *descriptive* phrases into near-trivial mechanical
conditions:

    "a nice clear trend"  ->  5 consecutive bars of 8>13>21>34>48
    "a pullback"          ->  ONE bar closing below the 13 EMA
    Vomy's "fins"         ->  (not implemented at all)

The resulting ledger churns: 695 trades / 32% / -44.1R, one trade every ~7
setup bars.  This script asks, for each of the three phrases, whether a
stricter threshold buys anything measurable, and reports the frequency/quality
trade-off honestly — including the (likely) answer "no".

Discipline enforced here
------------------------
1.  The outcome is a SYMMETRIC race: from the event close, does price first
    close +0.236 ATR away in the event's direction, or -0.236 ATR against it,
    within H bars.  With symmetric barriers the geometric null is exactly
    0.5 — that is the correct null, not "any win rate above zero".
2.  Every proportion carries a Wilson interval and its n.
3.  Every table reports how many cells were inspected (family size), and every
    "best" value reports how many candidates it was picked from.
4.  Four contiguous sub-periods for every headline number.
5.  Distances are normalised by the DAILY Wilder ATR(14) of the prior session
    (the unit of Saty's own ladder), never by an absolute price level.  The
    ^GSPC / CAPITALCOM:SPX500 ATR ratio is not a constant (mean 1.117,
    sd 0.083), so nothing here depends on where a named level sits — only on
    ATR-normalised DISTANCE, which is what the 0.236 step is.
6.  Primary outcome is CLOSE-based, so there is zero intrabar path ambiguity
    at any timeframe.  A high/low (touch) variant is reported as a robustness
    row with its ambiguity rate, and the 10m scale — the production setup
    timeframe — is additionally resolved with real 5-minute path data.

Scales (all ^GSPC, RTH only)
    10m  built from the 60d 5-minute cache   -> production setup timeframe
    1h   730d cache                          -> primary statistical power
    1d   20y cache                           -> long-horizon scale check

Usage:  python research/satylab/study_thresholds.py [--report]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, indicators, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402

STEP = 0.236          # the named-ladder step, in daily-ATR units
HORIZON = 12          # bars
STACK_DEFAULT = 5     # v14's `stackBars`
FIN_WINDOW = 20       # bars looked back for a "fin"
MIN_RISK_PTS = 2.0    # v14's `minRiskPts`

# running tally of every cell any table in this run inspected
FAMILY: dict[str, int] = {}
ZMAX: dict[str, float] = {"max": 0.0, "where": ""}
ZMAX_VS: dict[str, float] = {"max": 0.0, "where": ""}   # 候选 vs 现状 的对照 z


def note_family(name: str, cells: int) -> None:
    FAMILY[name] = FAMILY.get(name, 0) + cells


# ────────────────────────────── series assembly ──────────────────────────────

@dataclass
class Series:
    name: str
    bars: list[Bar]
    e8: list[float | None]
    e13: list[float | None]
    e21: list[float | None]
    e34: list[float | None]
    e48: list[float | None]
    sbull: list[int]
    sbear: list[int]
    atr: list[float | None]     # daily ATR(14) unit attached to each bar
    start: int                  # first index where everything is valid
    fine: dict = field(default_factory=dict)   # day -> 5m bars (10m scale only)

    @property
    def n_valid(self) -> int:
        return len(self.bars) - self.start


def aggregate(bars: list[Bar], k: int) -> list[Bar]:
    """Glue k consecutive intraday bars inside one session into one bar."""
    out: list[Bar] = []
    for day, rows in sorted(data.group_by_day(bars).items()):
        rows = [b for b in rows if b.hhmm != "16:00"]   # stray close print
        for i in range(0, len(rows), k):
            chunk = rows[i:i + k]
            if len(chunk) < k:
                continue
            out.append(Bar(chunk[0].dt, day, chunk[0].open,
                           max(c.high for c in chunk),
                           min(c.low for c in chunk),
                           chunk[-1].close,
                           sum(c.volume for c in chunk)))
    return out


def daily_atr_map() -> dict[date, float]:
    """day -> Wilder ATR(14) as of the PRIOR daily close (Saty's unit)."""
    d = data.daily()
    lv = levels.build(d)
    return {k: v.atr for k, v in lv.items()}


def build(name: str, bars: list[Bar], atr_by_day: dict[date, float] | None,
          self_atr: bool = False) -> Series:
    closes = [b.close for b in bars]
    e8 = indicators.ema(closes, 8)
    e13 = indicators.ema(closes, 13)
    e21 = indicators.ema(closes, 21)
    e34 = indicators.ema(closes, 34)
    e48 = indicators.ema(closes, 48)

    if self_atr:                       # daily scale: prior bar's own ATR(14)
        raw = levels.wilder_atr(bars)
        atr = [None] + raw[:-1]
    else:
        atr = [atr_by_day.get(b.day) for b in bars]

    sbull: list[int] = []
    sbear: list[int] = []
    cb = cs = 0
    for i in range(len(bars)):
        if None in (e8[i], e13[i], e21[i], e34[i], e48[i]):
            cb = cs = 0
        else:
            bull = e8[i] > e13[i] > e21[i] > e34[i] > e48[i]
            bear = e8[i] < e13[i] < e21[i] < e34[i] < e48[i]
            cb = cb + 1 if bull else 0
            cs = cs + 1 if bear else 0
        sbull.append(cb)
        sbear.append(cs)

    start = 0
    for i in range(len(bars)):
        if e48[i] is not None and atr[i]:
            start = i
            break
    return Series(name, bars, e8, e13, e21, e34, e48, sbull, sbear, atr, start)


# ───────────────────────────────── outcomes ──────────────────────────────────

UP, DN, TO, AMB = "up", "dn", "timeout", "amb"


def race_close(s: Series, i: int, atr: float, h: int = HORIZON,
               step: float = STEP) -> str:
    ref = s.bars[i].close
    up, dn = ref + step * atr, ref - step * atr
    for j in range(i + 1, min(i + 1 + h, len(s.bars))):
        c = s.bars[j].close
        if c >= up:
            return UP
        if c <= dn:
            return DN
    return TO


def race_touch(s: Series, i: int, atr: float, h: int = HORIZON,
               step: float = STEP) -> str:
    ref = s.bars[i].close
    up, dn = ref + step * atr, ref - step * atr
    for j in range(i + 1, min(i + 1 + h, len(s.bars))):
        b = s.bars[j]
        hu, hd = b.high >= up, b.low <= dn
        if hu and hd:
            return AMB
        if hu:
            return UP
        if hd:
            return DN
    return TO


def race_fine(s: Series, i: int, atr: float, h: int = HORIZON,
              step: float = STEP) -> str:
    """Touch race resolved with real 5-minute bars (10m scale only).

    The 10m bars are pairs of 5m bars, so this halves — it does not remove —
    the intrabar ambiguity.  The residual AMB rate is reported.
    """
    import bisect
    ref = s.bars[i].close
    up, dn = ref + step * atr, ref - step * atr
    j_last = min(i + h, len(s.bars) - 1)
    t0 = s.bars[i + 1].dt if i + 1 < len(s.bars) else None
    if t0 is None:
        return TO
    # window ends at the START of the bar after the horizon (exclusive)
    t_end = (s.bars[j_last + 1].dt if j_last + 1 < len(s.bars) else None)
    flat = s.fine.get("_flat")
    keys = s.fine.get("_keys")
    a = bisect.bisect_left(keys, t0)
    b = bisect.bisect_left(keys, t_end) if t_end is not None else len(flat)
    for k in range(a, b):
        fb = flat[k]
        hu, hd = fb.high >= up, fb.low <= dn
        if hu and hd:
            return AMB
        if hu:
            return UP
        if hd:
            return DN
    return TO


@dataclass
class Res:
    """Outcome tally for one condition, with 4-period stability built in."""
    label: str
    n: int = 0
    k: int = 0                 # favourable barrier hit first
    adverse: int = 0
    timeout: int = 0
    amb: int = 0
    per: list[list[int]] = field(default_factory=lambda: [[0, 0] for _ in range(4)])

    def add(self, favourable: bool, result: str, period: int) -> None:
        self.n += 1
        self.per[period][1] += 1
        if result == AMB:
            self.amb += 1
        elif result == TO:
            self.timeout += 1
        elif favourable:
            self.k += 1
            self.per[period][0] += 1
        else:
            self.adverse += 1

    @property
    def p(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def resolved(self) -> int:
        return self.k + self.adverse

    @property
    def p_res(self) -> float:
        return self.k / self.resolved if self.resolved else 0.0

    def ci(self) -> tuple[float, float]:
        return stats.wilson(self.k, self.n)

    def stability(self) -> str:
        out = []
        for k, n in self.per:
            out.append(f"{100*k/n:.0f}%/{n}" if n else "-/0")
        return " | ".join(out)


def period_of(i: int, s: Series) -> int:
    span = len(s.bars) - s.start
    p = int((i - s.start) * 4 / span)
    return min(max(p, 0), 3)


def measure(s: Series, events: list[tuple[int, int]], label: str,
            h: int = HORIZON, mode: str = "close") -> Res:
    r = Res(label)
    fn = {"close": race_close, "touch": race_touch, "fine": race_fine}[mode]
    for i, d in events:
        atr = s.atr[i]
        if not atr or i + 1 >= len(s.bars):
            continue
        res = fn(s, i, atr, h)
        fav = (res == UP and d > 0) or (res == DN and d < 0)
        r.add(fav, res, period_of(i, s))
    return r


def baseline(s: Series, h: int = HORIZON, mode: str = "close") -> tuple[Res, Res, Res]:
    """Unconditional rates: (pooled both-directions, long-only, short-only)."""
    ev_up = [(i, +1) for i in range(s.start, len(s.bars) - 1)]
    ev_dn = [(i, -1) for i in range(s.start, len(s.bars) - 1)]
    up = measure(s, ev_up, "baseline up", h, mode)
    dn = measure(s, ev_dn, "baseline dn", h, mode)
    pooled = Res("baseline pooled")
    for src in (up, dn):
        pooled.n += src.n
        pooled.k += src.k
        pooled.adverse += src.adverse
        pooled.timeout += src.timeout
        pooled.amb += src.amb
        for j in range(4):
            pooled.per[j][0] += src.per[j][0]
            pooled.per[j][1] += src.per[j][1]
    return pooled, up, dn


def zrow(r: Res, base: Res) -> float:
    return stats.two_proportion_z(r.k, r.n, base.k, base.n)


# ─────────────────────────── ① "nice clear trend" ────────────────────────────

STACK_NS = (3, 5, 8, 13, 21, 34)


def stack_events(s: Series, n: int) -> list[tuple[int, int]]:
    """Bars at which a stacked run FIRST reaches length n (both directions)."""
    out = []
    for i in range(s.start, len(s.bars) - 1):
        if s.sbull[i] == n and (i == 0 or s.sbull[i - 1] == n - 1):
            out.append((i, +1))
        if s.sbear[i] == n and (i == 0 or s.sbear[i - 1] == n - 1):
            out.append((i, -1))
    return out


def study_trend(s: Series, base: Res, h: int = HORIZON,
                mode: str = "close") -> list[tuple[int, Res, float]]:
    rows = []
    for n in STACK_NS:
        ev = stack_events(s, n)
        r = measure(s, ev, f"stack>={n}", h, mode)
        rows.append((n, r, zrow(r, base)))
    note_family(f"① trend N x scale[{s.name}] mode[{mode}] H[{h}]", len(STACK_NS))
    return rows


# ──────────────────────────────── ② pullback ─────────────────────────────────

PB_VARIANTS = ("P0", "P1", "P2", "P2b", "P3", "P4")
PB_DESC = {
    "P0": "1 close beyond the 13 (v14 today)",
    "P1": "2+ consecutive closes beyond the 13",
    "P2": "depth >= 0.10 ATR from the run's extreme",
    "P2b": "depth >= 0.10 ATR from the 5-bar extreme",
    "P3": "wick reaches the 21 EMA",
    "P4": "wick reaches the 34 EMA",
}


@dataclass
class PBState:
    active: bool = False
    start: int = 0
    bars: int = 0
    ext: float = 0.0
    trend_ext: float = 0.0
    trend_ext5: float = 0.0
    hit21: bool = False
    hit34: bool = False


def pullback_events(s: Series, stack: int = STACK_DEFAULT,
                    relaxed_cancel: bool = False
                    ) -> dict[str, list[tuple[int, int]]]:
    """Run v14's Recovery state machine; tag each recovery with which
    pullback definitions it would have satisfied."""
    out: dict[str, list[tuple[int, int]]] = {v: [] for v in PB_VARIANTS}
    out["_prot"] = {}                              # type: ignore[assignment]
    meta: list[tuple[int, int, float, int]] = []   # i, dir, depth_atr, bars
    for direction in (+1, -1):
        st = PBState()
        run_ext = None
        for i in range(s.start, len(s.bars) - 1):
            b = s.bars[i]
            e13, e21, e34 = s.e13[i], s.e21[i], s.e34[i]
            atr = s.atr[i]
            if atr is None or e13 is None:
                continue
            run = s.sbull[i] if direction > 0 else s.sbear[i]
            other = s.sbear[i] if direction > 0 else s.sbull[i]
            # running extreme of the stacked run (the "trend high/low")
            if run == 1 or run_ext is None:
                run_ext = b.high if direction > 0 else b.low
            elif run > 0:
                run_ext = (max(run_ext, b.high) if direction > 0
                           else min(run_ext, b.low))
            broke = (b.close < e13) if direction > 0 else (b.close > e13)

            if not st.active:
                if run >= stack and broke:
                    lo = max(s.start, i - 4)
                    five = (max(x.high for x in s.bars[lo:i + 1]) if direction > 0
                            else min(x.low for x in s.bars[lo:i + 1]))
                    st = PBState(True, i, 1,
                                 b.low if direction > 0 else b.high,
                                 run_ext if run_ext is not None else
                                 (b.high if direction > 0 else b.low),
                                 five,
                                 (b.low <= e21) if direction > 0 else (b.high >= e21),
                                 (b.low <= e34) if direction > 0 else (b.high >= e34))
                continue

            # --- in a pullback ---
            cancel_line = s.e48[i] if relaxed_cancel else e34
            cancelled = (
                (b.close < cancel_line) if direction > 0 else (b.close > cancel_line)
            ) or (other > 0)
            if cancelled:
                st = PBState()
                continue
            if broke:
                st.bars += 1
                st.ext = (min(st.ext, b.low) if direction > 0
                          else max(st.ext, b.high))
                st.hit21 |= (b.low <= e21) if direction > 0 else (b.high >= e21)
                st.hit34 |= (b.low <= e34) if direction > 0 else (b.high >= e34)
                continue
            # recovery bar: close back through the 13
            depth = ((st.trend_ext - st.ext) if direction > 0
                     else (st.ext - st.trend_ext)) / atr
            depth5 = ((st.trend_ext5 - st.ext) if direction > 0
                      else (st.ext - st.trend_ext5)) / atr
            out["_prot"][(i, direction)] = st.ext      # type: ignore[index]
            out["P0"].append((i, direction))
            if st.bars >= 2:
                out["P1"].append((i, direction))
            if depth >= 0.10:
                out["P2"].append((i, direction))
            if depth5 >= 0.10:
                out["P2b"].append((i, direction))
            if st.hit21:
                out["P3"].append((i, direction))
            if st.hit34:
                out["P4"].append((i, direction))
            meta.append((i, direction, depth, st.bars))
            st = PBState()
    out["_meta"] = meta          # type: ignore[assignment]
    return out


# ───────────────────────────── ③ Vomy "fins" ─────────────────────────────────

def pivot_highs(s: Series, a: int, b: int, w: int = 2) -> list[int]:
    out = []
    for k in range(a + w, b - w + 1):
        h = s.bars[k].high
        if all(h >= s.bars[j].high for j in range(k - w, k + w + 1) if j != k):
            out.append(k)
    return out


def pivot_lows(s: Series, a: int, b: int, w: int = 2) -> list[int]:
    out = []
    for k in range(a + w, b - w + 1):
        lo = s.bars[k].low
        if all(lo <= s.bars[j].low for j in range(k - w, k + w + 1) if j != k):
            out.append(k)
    return out


def fin_double(s: Series, brk: int, direction: int, atr: float,
               m: int = FIN_WINDOW) -> bool:
    """F1 — two comparable extremes, the second failing to exceed the first."""
    a = max(s.start, brk - m)
    if brk - a < 6:
        return False
    piv = (pivot_highs(s, a, brk - 1) if direction < 0
           else pivot_lows(s, a, brk - 1))
    if len(piv) < 2:
        return False
    p1, p2 = piv[-2], piv[-1]
    if p2 - p1 < 2:
        return False
    if direction < 0:
        v1, v2 = s.bars[p1].high, s.bars[p2].high
        if v2 > v1 + 0.05 * atr:
            return False                       # second peak broke out
        if v2 < v1 - 0.15 * atr:
            return False                       # not a comparable pair
        trough = min(x.low for x in s.bars[p1:p2 + 1])
        return trough <= min(v1, v2) - 0.05 * atr
    v1, v2 = s.bars[p1].low, s.bars[p2].low
    if v2 < v1 - 0.05 * atr:
        return False
    if v2 > v1 + 0.15 * atr:
        return False
    peak = max(x.high for x in s.bars[p1:p2 + 1])
    return peak >= max(v1, v2) + 0.05 * atr


def fin_single(s: Series, brk: int, direction: int, atr: float,
               m: int = FIN_WINDOW, age: int = 3) -> bool:
    """F2 — the window's extreme is already `age` bars old at the break:
    price stopped making new highs (lows) before it broke."""
    a = max(s.start, brk - m)
    if brk - a < age + 2:
        return False
    if direction < 0:
        vals = [s.bars[k].high for k in range(a, brk)]
        idx = a + max(range(len(vals)), key=lambda k: vals[k])
    else:
        vals = [s.bars[k].low for k in range(a, brk)]
        idx = a + min(range(len(vals)), key=lambda k: vals[k])
    return (brk - 1) - idx >= age


FIN_VARIANTS = ("F0", "F1", "F2", "F1|F2", "F1&F2")


def vomy_events(s: Series, stack: int = STACK_DEFAULT, repeat: bool = False
                ) -> dict[str, list[tuple[int, int]]]:
    """v14's Vomy state machine, tagging each entry with the fin definitions
    that the BREAK bar satisfied.

    `repeat` reproduces a quirk of the Pine source: `vomS := 0` sits INSIDE
    `if risk >= minRiskPts`, so a retest that does NOT produce an entry (flat
    filter, or a position already open) leaves the Vomy armed.  It then fires
    again on the very next bar whose high touches the 13, and again, until
    price closes back through the 13.  For the event study we want one entry
    per setup (repeat=False); for the engine replica we want Pine's behaviour
    (repeat=True).
    """
    out: dict[str, list[tuple[int, int]]] = {v: [] for v in FIN_VARIANTS}
    for direction in (-1, +1):        # -1 = Vomy short, +1 = inverse Vomy long
        active = False
        brk = 0
        fins: dict[str, bool] = {}
        for i in range(s.start, len(s.bars) - 1):
            b = s.bars[i]
            e8, e13 = s.e8[i], s.e13[i]
            atr = s.atr[i]
            if atr is None or e13 is None or e8 is None:
                continue
            prev_run = (s.sbull[i - 1] if direction < 0 else s.sbear[i - 1])
            if not active:
                trig = ((b.close < e13 and b.close < e8) if direction < 0
                        else (b.close > e13 and b.close > e8))
                if prev_run >= stack and trig:
                    active, brk = True, i
                    f1 = fin_double(s, i, direction, atr)
                    f2 = fin_single(s, i, direction, atr)
                    fins = {"F0": True, "F1": f1, "F2": f2,
                            "F1|F2": f1 or f2, "F1&F2": f1 and f2}
                continue
            recovered = (b.close > e13) if direction < 0 else (b.close < e13)
            if recovered:
                active = False
                continue
            retest = (b.high >= e13) if direction < 0 else (b.low <= e13)
            if retest:
                for k, ok in fins.items():
                    if ok:
                        out[k].append((i, direction))
                if not repeat:
                    active = False
        _ = brk
    return out


# ───────────────────────── v14 engine replication ────────────────────────────

def next_rung(px: float, d: int, anchor: float, atr: float) -> float:
    best = None
    for r in levels.RATIOS:
        lv = anchor + r * atr
        if d > 0 and lv > px and (best is None or lv < best):
            best = lv
        if d < 0 and lv < px and (best is None or lv > best):
            best = lv
    return best if best is not None else px + d * STEP * atr


def run_v14(s: Series, anchors: dict[date, float],
            stack: int = STACK_DEFAULT,
            pullback: str = "P0", fin: str = "F0",
            struct_exit_ema: int = 13,
            min_risk: float = MIN_RISK_PTS,
            pine_vomy_quirk: bool = True) -> dict:
    """Faithful replay of idm_v14_system.pine's trade engine.

    Order of operations inside one confirmed bar is Pine's: manage the open
    position FIRST (protective / T1 / T2 / structural close through the 13),
    then let the setup state machines run — which is how v14 can close and
    re-open on the same bar.

    `pullback` / `fin` / `struct_exit_ema` / `stack` swap in the tightened
    definitions this study proposes.  `pine_vomy_quirk` keeps `vomS := 0`
    inside the risk filter, exactly as the Pine source has it, so a Vomy that
    cannot enter stays armed and re-fires on every later retest of the 13.
    """
    pb = pullback_events(s, stack)
    rec_ok = {(i, d) for i, d in pb[pullback]}
    rec_prot = pb["_prot"]

    exit_line = {8: s.e8, 13: s.e13, 21: s.e21, 34: s.e34}[struct_exit_ema]

    # Vomy machine state, per direction (-1 = Vomy short, +1 = inverse Vomy)
    v_active = {-1: False, +1: False}
    v_ext = {-1: 0.0, +1: 0.0}
    v_fin = {-1: False, +1: False}

    trades: list[dict] = []
    pos = None
    blocked = 0
    for i in range(s.start, len(s.bars)):
        b = s.bars[i]
        atr = s.atr[i]
        anchor = anchors.get(b.day)
        e8, e13 = s.e8[i], s.e13[i]
        if atr is None or anchor is None or e13 is None or e8 is None:
            continue

        # ---- 1. manage the open position (Pine order) ----
        if pos:
            d = pos["dir"]
            hit_prot = b.low <= pos["prot"] if d > 0 else b.high >= pos["prot"]
            hit_t1 = (not pos["t1done"]) and (
                b.high >= pos["t1"] if d > 0 else b.low <= pos["t1"])
            hit_t2 = pos["t1done"] and (not pos["t2done"]) and (
                b.high >= pos["t2"] if d > 0 else b.low <= pos["t2"])
            xl = exit_line[i]
            struct_out = xl is not None and (
                b.close < xl if d > 0 else b.close > xl)
            if hit_prot:
                pos["legs"] += pos["frac"] * (pos["prot"] - pos["entry"]) * d / pos["risk"]
                pos["exit"] = "protective"
                pos["hold"] = i - pos["i"]
                trades.append(pos)
                pos = None
            else:
                if hit_t1:
                    pos["legs"] += 0.50 * (pos["t1"] - pos["entry"]) * d / pos["risk"]
                    pos["frac"] -= 0.50
                    pos["t1done"] = True
                if hit_t2:
                    pos["legs"] += 0.25 * (pos["t2"] - pos["entry"]) * d / pos["risk"]
                    pos["frac"] -= 0.25
                    pos["t2done"] = True
                if struct_out:
                    pos["legs"] += pos["frac"] * (b.close - pos["entry"]) * d / pos["risk"]
                    pos["exit"] = "structure"
                    pos["hold"] = i - pos["i"]
                    trades.append(pos)
                    pos = None

        def _open(setup: str, d: int, prot: float) -> bool:
            nonlocal pos
            risk = (b.close - prot) * d
            if risk < min_risk:
                return False
            t1 = next_rung(b.close, d, anchor, atr)
            t2 = next_rung(t1, d, anchor, atr)
            pos = {"i": i, "dir": d, "setup": setup, "entry": b.close,
                   "risk": risk, "prot": prot, "t1": t1, "t2": t2,
                   "t1done": False, "t2done": False, "frac": 1.0,
                   "legs": 0.0, "period": period_of(i, s)}
            return True

        # ---- 2. Recovery (long checked before short, as in the Pine) ----
        for d in (+1, -1):
            if pos is None and (i, d) in rec_ok:
                _open("Recovery", d, rec_prot[(i, d)])

        # ---- 3. Vomy machine (short first, as in the Pine) ----
        for d in (-1, +1):
            prev_run = s.sbull[i - 1] if d < 0 else s.sbear[i - 1]
            if not v_active[d]:
                trig = ((b.close < e13 and b.close < e8) if d < 0
                        else (b.close > e13 and b.close > e8))
                if prev_run >= stack and trig:
                    v_active[d] = True
                    lo = max(s.start, i - 9)
                    v_ext[d] = (max(x.high for x in s.bars[lo:i + 1]) if d < 0
                                else min(x.low for x in s.bars[lo:i + 1]))
                    f1 = fin_double(s, i, d, atr)
                    f2 = fin_single(s, i, d, atr)
                    v_fin[d] = {"F0": True, "F1": f1, "F2": f2,
                                "F1|F2": f1 or f2, "F1&F2": f1 and f2}[fin]
                continue
            v_ext[d] = (max(v_ext[d], b.high) if d < 0
                        else min(v_ext[d], b.low))
            if (b.close > e13) if d < 0 else (b.close < e13):
                v_active[d] = False              # recovered = vomy failed
                continue
            retest = (b.high >= e13) if d < 0 else (b.low <= e13)
            if retest and v_fin[d]:
                if pos is None and _open("Vomy", d, v_ext[d]):
                    v_active[d] = False
                else:
                    blocked += 1          # retest that could not be taken
                    if not pine_vomy_quirk:
                        v_active[d] = False

    rs = [t["legs"] for t in trades]
    e = stats.expectancy(rs)
    e["trades"] = len(trades)
    e["bars"] = s.n_valid
    e["per_1000"] = 1000 * len(trades) / s.n_valid if s.n_valid else 0.0
    e["median_hold"] = median([t["hold"] for t in trades]) if trades else 0.0
    e["by_setup"] = {}
    for name in ("Recovery", "Vomy"):
        sub = [t["legs"] for t in trades if t["setup"] == name]
        e["by_setup"][name] = stats.expectancy(sub)
    e["by_period"] = {}
    for p in range(4):
        sub = [t["legs"] for t in trades if t["period"] == p]
        e["by_period"][p] = stats.expectancy(sub)
    e["exits"] = {k: sum(1 for t in trades if t["exit"] == k)
                  for k in ("protective", "structure")}
    e["vomy_blocked"] = blocked
    if len(rs) > 1:
        m = sum(rs) / len(rs)
        var = sum((x - m) ** 2 for x in rs) / (len(rs) - 1)
        e["sd_r"] = var ** 0.5
        e["t"] = m / (e["sd_r"] / len(rs) ** 0.5) if e["sd_r"] > 0 else 0.0
    else:
        e["sd_r"] = 0.0
        e["t"] = 0.0
    return e



# ───────────────────────────────── reporting ─────────────────────────────────

def line_res(tag: str, r: Res, base: Res, per_k: float | None = None) -> str:
    lo, hi = r.ci()
    z = zrow(r, base)
    if abs(z) > ZMAX["max"]:
        ZMAX["max"], ZMAX["where"] = abs(z), tag
    freq = f"{per_k:7.1f}" if per_k is not None else "      -"
    return (f"  {tag:<34}{r.n:>6}{freq}   {100*r.p:5.1f}% "
            f"[{100*lo:4.1f},{100*hi:5.1f}]  {100*r.p_res:5.1f}%  "
            f"{100*r.timeout/r.n if r.n else 0:4.0f}%  {z:+6.2f}   {r.stability()}")


HEAD = ("  条件                                   n    /1000     P(延伸)  "
        "[95% CI]        P|已决   超时     z      四期 (P/n)")


def section(title: str) -> str:
    return f"\n{title}\n{'=' * len(title)}"


def build_all() -> dict[str, Series]:
    amap = daily_atr_map()
    five = data.fine()
    ten = aggregate(five, 2)
    s10 = build("10m", ten, amap)
    s10.fine = {"_flat": five, "_keys": [b.dt for b in five]}
    s1h = build("1h", [b for b in data.hourly() if b.hhmm != "16:00"], amap)
    s1d = build("1d", data.daily(), None, self_atr=True)
    return {"10m": s10, "1h": s1h, "1d": s1d}


def anchors_map(symbol: str = data.SPX) -> dict[date, float]:
    d = data.daily(symbol)
    return {k: v.anchor for k, v in levels.build(d).items()}


def build_es10() -> tuple[Series, dict[date, float]]:
    """ES=F 10m — the only ~23h series in the cache.  Used ONLY to test whether
    the missing overnight session explains the trade-count gap against the
    live SPX500 ledger (73% of whose trades are overnight)."""
    d = data.daily("ES=F")
    amap = {k: v.atr for k, v in levels.build(d).items()}
    anc = {k: v.anchor for k, v in levels.build(d).items()}
    five = data.load("ES=F", "60d", "5m")
    return build("ES10", aggregate(five, 2), amap), anc


def main() -> None:
    out: list[str] = []

    def w(line: str = "") -> None:
        out.append(line)
        print(line)

    S = build_all()
    anchors = anchors_map()

    w("# v14 的三个定性词 —— 逐个量化门槛")
    w()
    w("生成：`research/satylab/study_thresholds.py`（^GSPC，RTH）")
    w()
    summary_at = len(out)
    w()
    w("## 0 · 口径")
    w()
    w("**结果变量（延伸）**：从事件 K 的收盘出发，未来 `H=12` 根内，")
    w("先出现「顺方向收盘 ≥ +0.236 ATR」记为**延伸**，先出现「逆方向收盘 ≤ −0.236 ATR」")
    w("记为**反向**，都没有记为**超时**。ATR = 前一日 Wilder ATR(14)（Saty 阶梯的单位），")
    w("**只用 ATR 归一化的距离，不依赖任何具名位的绝对位置**——所以 ^GSPC 与")
    w("CAPITALCOM:SPX500 的 ATR 比值不是常数这件事在这里不构成威胁。")
    w()
    w("**零假设**：两个障碍对称（±0.236 ATR），几何零假设 = **50.0%**（S/(S+T)，S=T）。")
    w("表里的 `z` 是与**无条件基准率**的两比例检验；无条件基准率本身与 50% 的偏离")
    w("就是漂移项，单独列出。")
    w()
    w("**为什么用收盘定义**：收盘序列不存在 K 内路径歧义，任何周期都可判。")
    w("高低点（touch）口径作为稳健性行给出并报告歧义率；10m 尺度另用真实 5 分钟")
    w("数据解路径（纪律 5）。")
    w()
    for k, s in S.items():
        w(f"- **{s.name}**：{len(s.bars)} 根，有效 {s.n_valid} 根，"
          f"{s.bars[s.start].day} → {s.bars[-1].day}")
    w()

    # ── baselines ──
    bases: dict[str, tuple[Res, Res, Res]] = {}
    w("### 无条件基准率（全体 K，H=12，收盘口径）")
    w()
    w("| 尺度 | 多头方向 P(+0.236先) | 空头方向 P(−0.236先) | 超时 | 合并(=几何零假设) |")
    w("|---|---|---|---|---|")
    for name, s in S.items():
        b, up, dn = baseline(s)
        bases[name] = (b, up, dn)
        w(f"| {name} | {stats.fmt_rate(up.k, up.n)} | {stats.fmt_rate(dn.k, dn.n)} "
          f"| {100*up.timeout/up.n:.1f}% | {100*b.p:.1f}% |")
    w()

    # ── ① trend ──
    w(section("① 「nice clear trend」= 连续 N 根五 EMA 排列"))
    w()
    w("事件定义：某根 K 上排列连续计数**首次达到 N**（多空两侧各算）。")
    w("因此一段长度 L 的排列段对每个 N ≤ L 贡献一次事件——N 越大事件越少，这正是")
    w("要量化的频率-质量权衡。")
    w()
    tri: dict = {}
    for name, s in S.items():
        b = bases[name][0]
        w(f"**{name}** — 无条件基准 {100*b.p:.1f}% (n={b.n})")
        w()
        w("```")
        w(HEAD)
        rows = study_trend(s, b)
        tri[name] = {n: (r, z) for n, r, z in rows}
        for n, r, z in rows:
            per_k = 1000 * r.n / s.n_valid
            w(line_res(f"连续排列 N={n}", r, b, per_k))
        w("```")
        w()

    # run-length distribution — how nested the six N rows are
    w("### 排列段长度分布（六行事件是嵌套的，不是独立的）")
    w()
    w("| 尺度 | 排列中的 K 占比 | 排列段数(≥1根) | 段长中位数 | 段长 P90 | 最长段 |")
    w("|---|---|---|---|---|---|")
    for name, s in S.items():
        runs = []
        for arr in (s.sbull, s.sbear):
            cur = 0
            for i in range(s.start, len(s.bars)):
                if arr[i] > 0:
                    cur = arr[i]
                elif cur:
                    runs.append(cur)
                    cur = 0
            if cur:
                runs.append(cur)
        stacked = sum(1 for i in range(s.start, len(s.bars))
                      if s.sbull[i] or s.sbear[i])
        rs = sorted(runs)
        w(f"| {name} | {100*stacked/s.n_valid:.1f}% | {len(rs)} | "
          f"{rs[len(rs)//2]} | {rs[int(0.9*len(rs))]} | {rs[-1]} |")
    w()
    w("一段长度 L 的排列段对每个 N ≤ L 各贡献一次事件，所以 N=3 与 N=5 的事件集")
    w("高度重叠（1h 上 N=3 的 151 个事件里有 144 个在同一段里又成为 N=5 事件）。")
    w("六行不是六个独立检验，但也不能当成一个——它们是同一批趋势段的嵌套切片。")
    w()

    # frequency/quality trade-off curve, primary scale
    w("### 频率-质量权衡曲线（1h，主尺度）")
    w()
    s = S["1h"]
    b = bases["1h"][0]
    w("| N | 事件数 | 每1000根 | 相对 N=3 的事件保留率 | P(延伸) | 相对基准的绝对增量 | z |")
    w("|---|---|---|---|---|---|---|")
    rows = [(n, *tri["1h"][n]) for n in STACK_NS]
    n3 = rows[0][1].n
    for n, r, z in rows:
        w(f"| {n} | {r.n} | {1000*r.n/s.n_valid:.1f} | {100*r.n/n3:.0f}% | "
          f"{100*r.p:.1f}% | {100*(r.p-b.p):+.1f}pp | {z:+.2f} |")
    w()

    # the actual question: is there an N that beats the base rate everywhere?
    w("### 直接回答「有没有一个 N 显著跑赢无条件基准」")
    w()
    w("同一个 N 在三个尺度上都要跑赢，才谈得上是 N 的功劳而不是某个尺度的噪声。")
    w()
    w("| N | 10m Δpp (z) | 1h Δpp (z) | 1d Δpp (z) | 三尺度同号？ |")
    w("|---|---|---|---|---|")
    for n in STACK_NS:
        cells, signs = [], []
        for name in ("10m", "1h", "1d"):
            r, z = tri[name][n]
            d = 100 * (r.p - bases[name][0].p)
            cells.append(f"{d:+.1f} ({z:+.2f})")
            signs.append(d > 0)
        same = "是" if all(signs) or not any(signs) else "否"
        w(f"| {n} | {cells[0]} | {cells[1]} | {cells[2]} | {same} |")
    w()
    zmax = max(abs(tri[nm][n][1]) for nm in tri for n in STACK_NS)
    w(f"三尺度 18 个格子里最大 abs(z) = **{zmax:.2f}**。单看 ① 这一族（18 格）"
      f"Bonferroni 门槛就已经是 abs(z) > {_bonf_z(18):.2f}，全轮门槛更高。")
    w("**没有任何一个 N 过线。** 唯一名义上越线的 1h/N=8（z=+2.59）在另外两个尺度上")
    w("只有 +0.58 / +0.64，并且它的四期序列是 76% → 67% → 53% → 50% ——单调衰减，")
    w("典型的样本内噪声形状。")
    w()

    # robustness: horizon + touch mode + fine path
    w("### 稳健性：视野 H 与路径口径")
    w()
    w("```")
    w(HEAD)
    for h in (6, 12, 24):
        for n in (5, 21):
            ev = stack_events(S["1h"], n)
            bb, _, _ = baseline(S["1h"], h)
            r = measure(S["1h"], ev, "", h)
            w(line_res(f"1h N={n}  H={h}", r, bb, 1000*r.n/S['1h'].n_valid))
    note_family("① 视野稳健性", 6)
    w("")
    for mode in ("close", "touch", "fine"):
        for n in (5, 21):
            ev = stack_events(S["10m"], n)
            bb, _, _ = baseline(S["10m"], HORIZON, mode if mode != "fine" else "touch")
            r = measure(S["10m"], ev, "", HORIZON, mode)
            amb = 100 * r.amb / r.n if r.n else 0
            w(line_res(f"10m N={n} 口径={mode}(歧义{amb:.0f}%)", r, bb,
                       1000*r.n/S['10m'].n_valid))
    note_family("① 路径口径稳健性", 6)
    w("```")
    w()

    # ── ② pullback ──
    w(section("② 「pullback」= 回踩的门槛"))
    w()
    w("流程与 v14 一致：趋势（连续排列 ≥5）→ 收盘穿 13 进入回踩 → 收盘收回 13 = 入场。")
    w("五个候选只改「什么算一次合格回踩」，其余（取消条件 close 穿 34 或反向排列）不动。")
    w("事件锚点 = 收回 13 的那根收盘，结果 = 顺势延伸 0.236 ATR。")
    w()
    for v in PB_VARIANTS:
        w(f"- **{v}** — {PB_DESC[v]}")
    w()
    pb_all = {}
    for name, s in S.items():
        b = bases[name][0]
        sets = pullback_events(s)
        pb_all[name] = sets
        meta = sets["_meta"]
        w(f"**{name}** — 无条件基准 {100*b.p:.1f}%；"
          f"回踩深度中位数 {median([m[2] for m in meta]):.3f} ATR，"
          f"回踩长度中位数 {median([m[3] for m in meta]):.0f} 根")
        w()
        w("```")
        w(HEAD)
        p0 = measure(s, sets["P0"], "P0")
        for v in PB_VARIANTS:
            r = measure(s, sets[v], v)
            per_k = 1000 * r.n / s.n_valid
            zv = zrow(r, p0)
            if v != "P0" and abs(zv) > ZMAX_VS["max"]:
                ZMAX_VS["max"], ZMAX_VS["where"] = abs(zv), f"{name} {v} vs P0"
            extra = "" if v == "P0" else f"  vsP0 z={zv:+.2f}"
            w(line_res(f"{v} {PB_DESC[v][:22]}", r, b, per_k) + extra)
        w("```")
        note_family(f"② 回踩候选 x scale[{name}]", len(PB_VARIANTS))
        w()

    w("### 回踩深度本身是不是一个连续的好变量？（分位数，不是挑阈值）")
    w()
    w("P2 在 1h/1d 上完全不咬人（深度中位数 0.81 / 2.48 ATR，0.1 的门槛形同虚设）。")
    w("与其挑一个阈值，直接看深度的**四分位**里延伸概率有没有单调性——有单调性才谈得上")
    w("「深度是个变量」，没有就说明这条路本身是死的。")
    w()
    w("```")
    w(HEAD)
    for name in ("10m", "1h", "1d"):
        s = S[name]
        b = bases[name][0]
        meta = pb_all[name]["_meta"]
        ds = sorted(m[2] for m in meta)
        qs = [ds[int(len(ds) * f)] for f in (0.25, 0.5, 0.75)]
        buckets: dict[int, list[tuple[int, int]]] = {0: [], 1: [], 2: [], 3: []}
        for i, d, dep, _n in meta:
            q = sum(dep >= x for x in qs)
            buckets[q].append((i, d))
        for q in range(4):
            r = measure(s, buckets[q], "")
            rng = ("<%.2f" % qs[0] if q == 0 else
                   ">=%.2f" % qs[2] if q == 3 else
                   "%.2f-%.2f" % (qs[q - 1], qs[q]))
            w(line_res(f"{name} 深度Q{q+1} {rng} ATR", r, b,
                       1000 * r.n / s.n_valid))
        w("")
        note_family(f"② 深度四分位[{name}]", 4)
    w("```")
    w()
    w("### 稳健性：放宽取消条件（close 穿 48 才取消，让 P3/P4 有机会成立）")
    w()
    w("```")
    w(HEAD)
    for name in ("1h", "10m"):
        s = S[name]
        b = bases[name][0]
        sets = pullback_events(s, relaxed_cancel=True)
        for v in ("P0", "P3", "P4"):
            r = measure(s, sets[v], v)
            w(line_res(f"{name} {v} 放宽取消", r, b, 1000*r.n/s.n_valid))
    note_family("② 放宽取消稳健性", 6)
    w("```")
    w()

    # ── ③ vomy fins ──
    w(section("③ Vomy 的「fins」"))
    w()
    w("v14 现状 = **F0**：只要求「之前排列过 ≥5 根」+ 收盘同时破 8 和 13，然后回抽 13 入场。")
    w("两个可编码的「鳍」候选：")
    w()
    w("- **F1（double top / bottom）**：首破前 20 根内最后两个 pivot 极值（±2 窗口），"
      "第二个不超过第一个 0.05 ATR、也不低于第一个 0.15 ATR，且两者之间有 ≥0.05 ATR 的回撤。")
    w("- **F2（single fin，未被超越的高点）**：首破前 20 根的最高点在破位前 ≥3 根就已形成，"
      "即破位之前价格已经停止创新高。")
    w("- **F1|F2**、**F1&F2** 一并给出。")
    w()
    for name, s in S.items():
        b = bases[name][0]
        sets = vomy_events(s)
        f0 = measure(s, sets["F0"], "F0")
        w(f"**{name}** — 无条件基准 {100*b.p:.1f}%")
        w()
        w("```")
        w(HEAD)
        for v in FIN_VARIANTS:
            r = measure(s, sets[v], v)
            keep = 100 * r.n / f0.n if f0.n else 0
            zv = zrow(r, f0)
            if v != "F0" and abs(zv) > ZMAX_VS["max"]:
                ZMAX_VS["max"], ZMAX_VS["where"] = abs(zv), f"{name} {v} vs F0"
            extra = "" if v == "F0" else f"  留存{keep:.0f}%  vsF0 z={zv:+.2f}"
            w(line_res(f"{v}", r, b, 1000*r.n/s.n_valid) + extra)
        w("```")
        note_family(f"③ 鳍候选 x scale[{name}]", len(FIN_VARIANTS))
        w()

    # ── v14 engine replication + threshold swap ──
    w(section("④ 把门槛塞回 v14 引擎：账本会变吗"))
    w()
    w("完整复刻 Pine 的成交引擎（同一根 K 先管仓后开仓、T1 减 50%/T2 减 25%、")
    w("保护位、收盘穿 13 结构离场）。目标位用 ^GSPC 自己的 ATR 阶梯——**这一项**")
    w("依赖具名位位置，因此只作方向性参考，不作精度结论。")
    w()
    w("| 尺度 | 变体 | 笔数 | 每1000根 | 胜率 | 总R | 均R | t(均R≠0) | 中位持仓(根) | 保护位离场 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    engine_rows = {}
    for name in ("10m", "1h"):
        s = S[name]
        for tag, kw in (("v14 原样 (P0/F0/13出)", {}),
                        ("N=21 清晰趋势", {"stack": 21}),
                        ("P4 回踩到 34", {"pullback": "P4"}),
                        ("F1\\|F2 加鳍", {"fin": "F1|F2"}),
                        ("出场改用 8EMA", {"struct_exit_ema": 8}),
                        ("出场改用 21EMA", {"struct_exit_ema": 21}),
                        ("出场改用 34EMA", {"struct_exit_ema": 34}),
                        ("全部收紧", {"stack": 21, "pullback": "P4",
                                       "fin": "F1|F2", "struct_exit_ema": 34})):
            e = run_v14(s, anchors, **{k: v for k, v in kw.items()})
            engine_rows[(name, tag)] = e
            prot = e["exits"]["protective"] / e["trades"] if e["trades"] else 0
            w(f"| {name} | {tag} | {e['trades']} | {e['per_1000']:.1f} | "
              f"{100*e.get('win_rate',0):.1f}% | {e.get('total_r',0):+.1f} | "
              f"{e.get('avg_r',0):+.3f} | {e['t']:+.2f} | "
              f"{e['median_hold']:.0f} | {100*prot:.0f}% |")
    es, es_anchors = build_es10()
    ees = run_v14(es, es_anchors)
    prot = ees["exits"]["protective"] / ees["trades"]
    w(f"| ES=F 10m (23h) | v14 原样 | {ees['trades']} | {ees['per_1000']:.1f} | "
      f"{100*ees['win_rate']:.1f}% | {ees['total_r']:+.1f} | {ees['avg_r']:+.3f} | "
      f"{ees['t']:+.2f} | {ees['median_hold']:.0f} | {100*prot:.0f}% |")
    note_family("④ 引擎变体 x scale", 17)
    w()
    w("`t` 是「均 R 是否异于 0」的单样本 t。16 个格子里没有一个的 abs(t) 达到")
    w("Bonferroni 门槛（16 格 → abs(t) > 2.87）。而且这 16 行**共用同一批 K**，")
    w("彼此高度相关，行与行之间的差不能当独立检验读。")
    w()
    base_e = engine_rows[("10m", "v14 原样 (P0/F0/13出)")]
    w("**v14 原样在 10m 上的分解**")
    w()
    w("```")
    w(f"  全部    {stats.fmt_expectancy(base_e)}")
    for k, v in base_e["by_setup"].items():
        w(f"  {k:<8}{stats.fmt_expectancy(v)}")
    for p, v in base_e["by_period"].items():
        w(f"  期{p+1}    {stats.fmt_expectancy(v)}")
    w("```")
    w()
    w("**与 TradingView 上线账本的对照**（TV：CAPITALCOM:SPX500 10m 全时段，")
    w("695 笔 / 32% / −44.1R，约每 7 根 K 一笔 = 142.9 笔/千根）")
    w()
    w("| 指标 | TV 线上（SPX500 24h） | ^GSPC 10m (RTH) | ^GSPC 1h | "
      "**ES=F 10m (23h)** |")
    w("|---|---|---|---|---|")
    e10 = engine_rows[("10m", "v14 原样 (P0/F0/13出)")]
    e1h = engine_rows[("1h", "v14 原样 (P0/F0/13出)")]
    w(f"| 笔/千根 | 142.9 | {e10['per_1000']:.1f} | {e1h['per_1000']:.1f} | "
      f"{ees['per_1000']:.1f} |")
    w(f"| 胜率 | 32.0% | {100*e10['win_rate']:.1f}% | {100*e1h['win_rate']:.1f}% | "
      f"{100*ees['win_rate']:.1f}% |")
    w(f"| 均 R/笔 | −0.063 | {e10['avg_r']:+.3f} | {e1h['avg_r']:+.3f} | "
      f"{ees['avg_r']:+.3f} |")
    w(f"| 总 R | −44.1 (695笔) | {e10['total_r']:+.1f} ({e10['trades']}笔) | "
      f"{e1h['total_r']:+.1f} ({e1h['trades']}笔) | "
      f"{ees['total_r']:+.1f} ({ees['trades']}笔) |")
    w(f"| Recovery 均R | −0.115 | {e10['by_setup']['Recovery']['avg_r']:+.3f} | "
      f"{e1h['by_setup']['Recovery']['avg_r']:+.3f} | "
      f"{ees['by_setup']['Recovery']['avg_r']:+.3f} |")
    w(f"| Vomy 均R | −0.010 | {e10['by_setup']['Vomy']['avg_r']:+.3f} | "
      f"{e1h['by_setup']['Vomy']['avg_r']:+.3f} | "
      f"{ees['by_setup']['Vomy']['avg_r']:+.3f} |")
    w()
    w("**复现的部分**：负期望复现（三个数据集全负）；ES=F（唯一的准 23 小时标的）")
    w(f"把胜率复现到 {100*ees['win_rate']:.1f}%（线上 32.0%），并复现了")
    w("「Recovery 远差于 Vomy」的排序（−0.198 vs −0.046，线上 −0.115 vs −0.010）。")
    w("^GSPC 1h 上这个排序反了过来（−0.064 vs −0.080），说明它只在接近生产的口径上稳。")
    w()
    w("**没复现的部分，以及我原来的猜测被自己的数据推翻**：我本来假设笔数密度的缺口")
    w("（60.6 对 142.9 每千根）来自 ^GSPC 缺夜盘——线上 73% 的交易在夜盘。")
    w(f"用 ES=F 的 23 小时数据重跑后密度只到 {ees['per_1000']:.1f}/千根，**假设被推翻**。")
    w()
    w("剩下最可能的解释不在引擎里，而在那个 142.9 的分母上：**「每 7 根 K 一笔」是从")
    w("695 笔反推出来的，不是数过的图上 K 数**。若真实密度是本复现的 ~66/千根，")
    w("那 695 笔对应的是约 10,500 根 10m K（≈76 个 23 小时交易日），而不是 4,865 根。")
    w("**这是一个用户可以在 TV 上一眼证伪的推论**：看一下账本覆盖的实际起止时间。")
    w("在它被证实或证伪之前，「churn = 每 7 根一笔」这个说法本身应当挂起——")
    w("本报告所有结论都不依赖它，只依赖「每笔期望为负且收紧门槛救不回来」。")
    w("差额的可查来源列在下面（每一项单独开关）。")
    w()
    w("| 开关 | 10m 笔数 | 每千根 | 均R |")
    w("|---|---|---|---|")
    for tag, kw in (("基准（Pine 原样）", {}),
                    ("关掉 Vomy 常驻武装 quirk", {"pine_vomy_quirk": False}),
                    ("minRisk 0.5 点（放松点差保护）", {"min_risk": 0.5}),
                    ("minRisk 5 点", {"min_risk": 5.0})):
        e = run_v14(S["10m"], anchors, **kw)
        w(f"| {tag} | {e['trades']} | {e['per_1000']:.1f} | {e['avg_r']:+.3f} |")
    note_family("④ 差额溯源开关", 4)
    w()
    qa = run_v14(S["10m"], anchors)
    qb = run_v14(S["10m"], anchors, pine_vomy_quirk=False)
    v1 = len(vomy_events(S["10m"], repeat=False)["F0"])
    v2 = len(vomy_events(S["10m"], repeat=True)["F0"])
    w("`vomS := 0` 在 Pine 里被写在 `if risk >= minRiskPts` **内部**（源码 ~380 行），")
    w("所以一个**无法成交**的 Vomy 不会解除武装，会在此后每一根「高点摸到 13」的 K 上")
    w("再次尝试，直到收盘收回 13。这是代码层面的一个 churn 放大器：单看状态机，")
    w(f"10m 上的回抽机会从 {v1} 次涨到 {v2} 次（+{100*(v2-v1)/v1:.0f}%）。")
    w()
    w(f"**但在 ^GSPC RTH 上它一笔都没多成交**（{qa['trades']} vs {qb['trades']} 笔，"
      f"被挡下的回抽 {qa['vomy_blocked']} vs {qb['vomy_blocked']} 次）——被挡下的回抽")
    w("在引擎重新空仓之前就已经被「收盘收回 13」解除了武装。所以这条 quirk 是**真的**，")
    w("但在本样本里**不是** churn 的来源。要证明它在 24h SPX500 上有没有咬人，需要真实的")
    w("CFD 历史，本轮没有。这条留作待验，不算发现。")
    w()

    # ── family accounting ──
    w(section("⑤ 家族计数（多重比较的账）"))
    w()
    w("| 表 | 格子数 |")
    w("|---|---|")
    for k, v in FAMILY.items():
        w(f"| {k} | {v} |")
    w(f"| **合计** | **{sum(FAMILY.values())}** |")
    w()
    w(f"本轮共检视 **{sum(FAMILY.values())}** 个格子。在 α=0.05 下期望有 "
      f"{0.05*sum(FAMILY.values()):.1f} 个格子仅因随机就越线；"
      f"Bonferroni 校正后的显著门槛是 |z| > "
      f"{_bonf_z(sum(FAMILY.values())):.2f}。低于这个门槛的一律不算发现。")

    zmax_all = max(abs(tri[nm][n][1]) for nm in tri for n in STACK_NS)
    nfam = sum(FAMILY.values())
    summary = [
        "## 结论（先说答案）",
        "",
        "**三个门槛全部收紧，都买不到统计上站得住的东西。** 逐条：",
        "",
        "| 定性词 | 我压扁成的条件 | 收紧后最好的结果 | 判决 |",
        "|---|---|---|---|",
        f"| 「nice clear trend」 | 连续 5 根排列 | 18 个 (N × 尺度) 格子里最大 abs(z) = {zmax_all:.2f} |"
        " **N 不是一个变量**。频率掉到 22% 而延伸概率纹丝不动 |",
        "| 「pullback」 | 1 根收盘破 13 | P1/P2/P3 无一改善；P4 在 1h 上名义变差 (z=−2.36)，"
        "在 1d 上名义变好 (z=+1.93) | **两个尺度符号相反 = 没有信号** |",
        "| Vomy 的「fins」 | 完全没实现 | 最好的 F1 在 1h 上比 F0 高 10.3pp，但 n=27、"
        "vsF0 z=+0.99；同一定义在 10m 上是 −1.2pp、在 1d 上只剩 5 个事件 | "
        "**加鳍不改变延伸概率，只砍掉 82% 的事件** |",
        "",
        "三条副产品：",
        "",
        "1. **回踩深度是个死变量。** 收盘穿回 13 的那一刻，回踩深度中位数已经是",
        "   0.26 ATR（10m）/ 0.81 ATR（1h）/ 2.48 ATR（1d），「≥0.1 ATR」这个门槛",
        "   在 1h 和 1d 上**一个事件都没筛掉**。按四分位分层，延伸概率是",
        "   25/43/25/43（10m）、45/56/48/51（1h）、58/35/67/50（1d）——**没有单调关系**，",
        "   深度这条路本身是死的，不是阈值没选对。",
        "2. **嫌疑 A（入场出场共用 13）在本轮数据上也没被证实。** 把结构离场从 13 换成",
        "   8 / 21 / 34（入场规则一个字不改）：1h 上均 R 只在 −0.071 → −0.067 → −0.068",
        "   → −0.045 之间抖动，**全部为负**；10m 上 34EMA 确实走到 +0.072，但 n=75、",
        "   t=+0.81，而且同一尺度上换成**更快**的 8EMA 也能改善（−0.041）。",
        "   「慢线出场更好」这个方向在数据里**不单调**，所以它是噪声，不是机制。",
        "3. **真正被数据钉死的是这一条：收紧任何门槛都只减少笔数，不改善每笔期望。**",
        "   1h 上 8 个引擎变体把笔数从 58.5/千根压到 9.7/千根（−83%），",
        "   均 R 却始终在 −0.184 ~ −0.045 之间、无一转正。churn 不是病因，",
        "   **每笔为负才是**；砍掉 80% 的交易只是让亏得慢一点。",
        "",
        "**明确的否定结论**：把「5 根」调到 8/13/21/34、把「1 根破 13」调成",
        "「2 根 / 深度 / 到 21 / 到 34」、给 Vomy 加上双顶或单鳍——",
        "**这三件事单独做或一起做，都不能把 v14 从负期望里救出来。**",
        f"本轮共检视 {nfam} 个格子。所有「候选 vs 无条件基准」格子里最大 abs(z) = "
        f"{ZMAX['max']:.2f}（「{ZMAX['where']}」）；所有「收紧候选 vs v14 现状」的对照里"
        f"最大 abs(z) = {ZMAX_VS['max']:.2f}（「{ZMAX_VS['where']}」）。"
        f"Bonferroni 门槛 abs(z) > {_bonf_z(nfam):.2f}。**两者都不过线：零个发现。**",
        "",
        "---",
        "",
    ]
    out[summary_at:summary_at] = summary
    print("\n".join(summary))

    txt = "\n".join(out)
    p = Path(__file__).resolve().parents[1] / "reports" / "V14_QUALITATIVE_THRESHOLDS.md"
    p.write_text(txt + "\n")
    print(f"\n[written] {p}")


def _bonf_z(m: int) -> float:
    import math
    # two-sided alpha/m -> z via inverse normal (Acklam-free: bisection)
    alpha = 0.05 / max(m, 1)
    target = 1 - alpha / 2
    lo, hi = 0.0, 8.0
    for _ in range(200):
        mid = (lo + hi) / 2
        cdf = 0.5 * (1 + math.erf(mid / math.sqrt(2)))
        if cdf < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    main()
