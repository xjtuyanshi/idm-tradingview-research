"""Execution-layer filters on IDM v14 — can "trading less" flip the sign?

The complement to the ablation rounds.  Nothing about *when* the state machine
fires is touched here; the entry rules are byte-identical to `study_v14_repro`.
What changes is *whether we take the fill*: a daily cap, a session window, a
minimum risk distance, a minimum target distance, a higher-timeframe direction
filter.  The question is narrow and answerable:

    does any subset of v14's entries carry positive expectancy,
    or does every filter merely shrink the number of bets?

Three rails keep this from becoming a parameter hunt:

  1. **Every filter reports its retention.**  A filter that keeps 8% of the
     book is a filter with 8% of the evidence, and its total R must be read
     against the spread of a *random* 8% subset, not against zero.
     `z_sel` does exactly that: it is the filtered book's mean R measured
     against the baseline mean, with the finite-population correction for
     sampling m of N without replacement.  z_sel is the "quality, not
     quantity" statistic.  If z_sel ~ 0 the filter did nothing except
     reduce n — even if its total R is positive.

  2. **The geometric null is the null.**  Win rate is compared to
     Sigma S/(S+T) via the Poisson-binomial z of the pure bracket race
     (protective vs T1, exit rule deleted), so a high win rate bought with a
     near stop is not mistaken for an edge.  Path order inside a bar is
     resolved on 5m sub-bars where they exist; where they do not, a bar that
     touches both barriers is counted as unresolved and dropped, and the
     unresolved share is printed.

  3. **Costs are charged per trade against that trade's own risk distance.**
     A filter that survives gross and dies net has not survived.

Two engines are run for every filter, because they answer different questions:

  * **in-engine** — the gate sits where the Pine's `risk >= minRiskPts` test
    sits, so a rejected signal releases the position slot and a later setup can
    fill instead.  This is what the account would actually have done.  The
    rejection follows the source's own asymmetry: Recovery clears its pullback
    state either way (`recL := 0` is outside the risk filter), Vomy stays armed
    (`vomS := 0` is inside it).
  * **post-hoc subset** — the baseline book, filtered.  Every surviving trade
    keeps its baseline R, so the comparison is paired and z_sel is exact.

Usage:  .venv/bin/python research/satylab/study_v14_filters.py
"""

from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                          # noqa: E402
from satylab.data import Bar                                     # noqa: E402
from satylab.indicators import ema                               # noqa: E402
from satylab.study_v14_repro import (                            # noqa: E402
    MIN_RISK_PTS, STACK_BARS, LevelBook, Trade, drop_close_stub,
    next_rung, run_v14, to_10m, trade_day,
)

ET = ZoneInfo("America/New_York")
CACHE = Path(__file__).resolve().parent / "cache"
SPREAD = 0.6                     # CAPITALCOM:SPX500 typical, per the Pine tooltip
SPREADS = (0.4, 0.6, 0.8)
RACE_CAP = 400                   # bars a bracket may run before we give up
BOOT = 4000
random.seed(20260727)


# ═══════════════════════════ candidate seen by a gate ════════════════════════
@dataclass(slots=True)
class Cand:
    setup: str
    direction: int
    entry: float
    prot: float
    risk: float
    t1: float
    t2: float
    atr: float
    dt: datetime
    in_rth: bool
    sday: date
    n_today: int

    @property
    def risk_atr(self) -> float:
        return self.risk / self.atr if self.atr else 0.0

    @property
    def t1_atr(self) -> float:
        return abs(self.t1 - self.entry) / self.atr if self.atr else 0.0

    @property
    def mins_from_open(self) -> float:
        return (self.dt.hour * 60 + self.dt.minute) - (9 * 60 + 30)


# ═════════════════════ v14 engine + one gate, nothing else ═══════════════════
def run_gated(bars: list[Bar], book: LevelBook,
              subs: list[list[Bar]] | None = None,
              gate: Callable[[Cand], bool] | None = None,
              daycap: int | None = None,
              stack_bars: int = STACK_BARS,
              min_risk: float = MIN_RISK_PTS) -> tuple[list[Trade], dict]:
    """`study_v14_repro.run_v14` with an execution gate at the fill decision.

    The gate is evaluated in exactly the place the Pine evaluates
    `risk >= minRiskPts`, so a blocked signal disposes of its state machine
    the same way an under-sized signal does.
    """
    closes = [b.close for b in bars]
    e8s, e13s, e21s = ema(closes, 8), ema(closes, 13), ema(closes, 21)
    e34s, e48s = ema(closes, 34), ema(closes, 48)

    sBull = sBear = 0
    prev_sBull = prev_sBear = 0
    recL = recS = 0
    recLExt = recSExt = None
    recL_start = recS_start = 0
    vomS = vomL = 0
    vomSFin = vomLFin = None
    vomSConf = vomLConf = False
    vomS_start = vomL_start = 0

    pos: Trade | None = None
    pFrac = 1.0
    pLegsR = 0.0
    trades: list[Trade] = []
    day_n: dict[date, int] = {}
    diag = {"setup_bars": 0, "gated_out": 0, "blocked_minrisk": 0,
            "blocked_inpos": 0, "signals": 0}

    def close_trade(t: Trade, i: int, price: float, reason: str) -> None:
        nonlocal pos
        t.legs.append((reason, pFrac, price))
        t.r = pLegsR + pFrac * (price - t.entry) * t.direction / t.risk
        t.exit_i = i
        t.exit_dt = bars[i].dt
        t.exit_reason = reason
        trades.append(t)
        pos = None

    for i, b in enumerate(bars):
        if e48s[i] is None:
            continue
        e8, e13, e21, e34, e48 = e8s[i], e13s[i], e21s[i], e34s[i], e48s[i]
        sc, sh, sl = b.close, b.high, b.low
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        anchor, atr = lv
        diag["setup_bars"] += 1
        sday = trade_day(b)

        prev_sBull, prev_sBear = sBull, sBear
        stack_bull = e8 > e13 > e21 > e34 > e48
        stack_bear = e8 < e13 < e21 < e34 < e48
        sBull = sBull + 1 if stack_bull else 0
        sBear = sBear + 1 if stack_bear else 0

        hh10 = max(x.high for x in bars[max(0, i - 9):i + 1])
        ll10 = min(x.low for x in bars[max(0, i - 9):i + 1])
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)

        # ---- manage the open position (unchanged from v14) ------------------
        if pos is not None:
            d = pos.direction
            hit_prot = (b.low <= pos.prot) if d > 0 else (b.high >= pos.prot)
            hit_t1 = (not pos.t1done) and ((b.high >= pos.t1) if d > 0 else (b.low <= pos.t1))
            hit_t2 = pos.t1done and (not pos.t2done) and \
                ((b.high >= pos.t2) if d > 0 else (b.low <= pos.t2))
            struct_out = (sc < e13) if d > 0 else (sc > e13)

            if hit_prot:
                close_trade(pos, i, pos.prot, "PROT")
            else:
                if hit_t1:
                    pLegsR += 0.50 * (pos.t1 - pos.entry) * d / pos.risk
                    pFrac -= 0.50
                    pos.t1done = True
                    pos.legs.append(("T1", 0.50, pos.t1))
                if hit_t2:
                    pLegsR += 0.25 * (pos.t2 - pos.entry) * d / pos.risk
                    pFrac -= 0.25
                    pos.t2done = True
                    pos.legs.append(("T2", 0.25, pos.t2))
                if struct_out:
                    close_trade(pos, i, sc, "STRUCT")

        def try_enter(setup: str, d: int, entry: float, prot: float,
                      risk: float, started: int, conf: bool = False) -> bool:
            """Return True iff the fill happened (mirrors `risk >= minRisk`)."""
            nonlocal pos, pFrac, pLegsR
            diag["signals"] += 1
            if risk < min_risk:
                diag["blocked_minrisk"] += 1
                return False
            t1 = next_rung(entry, d, anchor, atr)
            t2 = next_rung(t1, d, anchor, atr)
            n_today = day_n.get(sday, 0)
            if daycap is not None and n_today >= daycap:
                diag["gated_out"] += 1
                return False
            if gate is not None:
                c = Cand(setup, d, entry, prot, risk, t1, t2, atr,
                         b.dt, in_rth, sday, n_today)
                if not gate(c):
                    diag["gated_out"] += 1
                    return False
            pos = Trade(setup=setup, direction=d,
                        session="RTH" if in_rth else "夜盘",
                        entry_i=i, entry_dt=b.dt, entry=entry, prot=prot,
                        risk=risk, t1=t1, t2=t2, atr=atr, conf48=conf,
                        pullback_bars=i - started)
            pFrac, pLegsR = 1.0, 0.0
            day_n[sday] = n_today + 1
            return True

        # ---- Recovery long / short -----------------------------------------
        if recL == 0 and sBull >= stack_bars and sc < e13:
            recL, recLExt, recL_start = 1, sl, i
        elif recL == 1:
            recLExt = min(recLExt, sl)
            if sc < e34 or stack_bear:
                recL = 0
            elif sc > e13:
                if pos is None:
                    try_enter("Recovery", +1, sc, recLExt, sc - recLExt, recL_start)
                else:
                    diag["blocked_inpos"] += 1
                recL = 0
        if recS == 0 and sBear >= stack_bars and sc > e13:
            recS, recSExt, recS_start = 1, sh, i
        elif recS == 1:
            recSExt = max(recSExt, sh)
            if sc > e34 or stack_bull:
                recS = 0
            elif sc < e13:
                if pos is None:
                    try_enter("Recovery", -1, sc, recSExt, recSExt - sc, recS_start)
                else:
                    diag["blocked_inpos"] += 1
                recS = 0

        # ---- Vomy short / inverse Vomy long ---------------------------------
        if vomS == 0 and prev_sBull >= stack_bars and sc < e13 and sc < e8:
            vomS, vomSFin, vomSConf, vomS_start = 2, hh10, False, i
        elif vomS == 2:
            vomSFin = max(vomSFin, sh)
            if sc < e48:
                vomSConf = True
            if sc > e13:
                vomS = 0
            elif sh >= e13:
                if pos is None:
                    if try_enter("Vomy", -1, sc, vomSFin, vomSFin - sc,
                                 vomS_start, vomSConf):
                        vomS = 0          # `vomS := 0` lives inside the filter
                else:
                    diag["blocked_inpos"] += 1
        if vomL == 0 and prev_sBear >= stack_bars and sc > e13 and sc > e8:
            vomL, vomLFin, vomLConf, vomL_start = 2, ll10, False, i
        elif vomL == 2:
            vomLFin = min(vomLFin, sl)
            if sc > e48:
                vomLConf = True
            if sc < e13:
                vomL = 0
            elif sl <= e13:
                if pos is None:
                    if try_enter("Vomy", +1, sc, vomLFin, sc - vomLFin,
                                 vomL_start, vomLConf):
                        vomL = 0
                else:
                    diag["blocked_inpos"] += 1

    return trades, diag


# ══════════════════════════ higher-timeframe ribbon ══════════════════════════
class RibbonBook:
    """Session day -> daily ribbon state, built only from completed daily bars."""

    def __init__(self, daily: list[Bar]):
        closes = [b.close for b in daily]
        e = {n: ema(closes, n) for n in (8, 13, 21, 34, 48)}
        self.map: dict[date, dict] = {}
        for i in range(1, len(daily)):
            j = i - 1
            if e[48][j] is None:
                continue
            v = {n: e[n][j] for n in (8, 13, 21, 34, 48)}
            stack = 1 if v[8] > v[13] > v[21] > v[34] > v[48] else \
                   (-1 if v[8] < v[13] < v[21] < v[34] < v[48] else 0)
            self.map[daily[i].day] = {
                "stack": stack,
                "e821": 1 if v[8] > v[21] else -1,
                "c48": 1 if daily[j].close > v[48] else -1,
            }
        self.days = sorted(self.map)

    def get(self, d: date) -> dict | None:
        i = bisect_left(self.days, d)
        if i < len(self.days) and self.days[i] == d:
            return self.map[self.days[i]]
        if i > 0:
            return self.map[self.days[i - 1]]
        return None


# ═══════════════════════════════ filter catalogue ════════════════════════════
@dataclass
class Spec:
    key: str
    group: str
    label: str
    gate: Callable[[Cand], bool] | None = None
    daycap: int | None = None
    sub: Callable[[list[Trade]], list[Trade]] | None = None


def _by_day_index(trades: list[Trade]) -> list[int]:
    seen: dict[date, int] = {}
    idx = []
    for t in trades:
        d = trade_day_of(t)
        idx.append(seen.get(d, 0))
        seen[d] = seen.get(d, 0) + 1
    return idx


def trade_day_of(t: Trade) -> date:
    dt = t.entry_dt
    return dt.date() + timedelta(days=1) if dt.hour >= 18 else dt.date()


def t_risk_atr(t: Trade) -> float:
    return t.risk / t.atr if t.atr else 0.0


def t_t1_atr(t: Trade) -> float:
    return abs(t.t1 - t.entry) / t.atr if t.atr else 0.0


def t_mins(t: Trade) -> float:
    return (t.entry_dt.hour * 60 + t.entry_dt.minute) - (9 * 60 + 30)


def build_specs(rib: RibbonBook) -> list[Spec]:
    S: list[Spec] = [Spec("BASE", "基线", "v14 原样（无过滤）")]

    # 1 — daily cap
    for n in (1, 2, 3, 5):
        S.append(Spec(f"CAP{n}", "①每日笔数上限", f"每日最多 {n} 笔（按 setup 出现顺序）",
                      daycap=n,
                      sub=lambda ts, n=n: [t for t, k in zip(ts, _by_day_index(ts)) if k < n]))

    # 2 — session
    S.append(Spec("RTH", "②时段", "只做 RTH（09:30–16:00 ET）",
                  gate=lambda c: c.in_rth,
                  sub=lambda ts: [t for t in ts if t.session == "RTH"]))
    S.append(Spec("ON", "②时段", "只做夜盘（RTH 之外）",
                  gate=lambda c: not c.in_rth,
                  sub=lambda ts: [t for t in ts if t.session != "RTH"]))

    # 3 — opening window (Saty clocks out 11:47)
    for key, lo, hi, lbl in (("OPEN60", 0, 60, "只做 09:30–10:30（第一小时）"),
                             ("OPEN120", 0, 120, "只做 09:30–11:30（开盘后 2 小时）"),
                             ("OPEN137", 0, 137, "只做 09:30–11:47（Saty 的收工时间）")):
        S.append(Spec(key, "③开盘窗口", lbl,
                      gate=lambda c, lo=lo, hi=hi: lo <= c.mins_from_open < hi,
                      sub=lambda ts, lo=lo, hi=hi: [t for t in ts if lo <= t_mins(t) < hi]))

    # 4 — minimum risk distance
    for x in (0.05, 0.10, 0.15):
        S.append(Spec(f"RISK{int(x*100):02d}", "④风险距离", f"只做 风险 ≥ {x:.2f} ATR",
                      gate=lambda c, x=x: c.risk_atr >= x,
                      sub=lambda ts, x=x: [t for t in ts if t_risk_atr(t) >= x]))

    # 5 — minimum target distance
    for y in (0.10, 0.15, 0.20):
        S.append(Spec(f"TGT{int(y*100):02d}", "⑤目标距离", f"只做 T1 距离 ≥ {y:.2f} ATR",
                      gate=lambda c, y=y: c.t1_atr >= y,
                      sub=lambda ts, y=y: [t for t in ts if t_t1_atr(t) >= y]))

    # 6 — daily ribbon agreement
    def _rib(d: date, field: str) -> int:
        r = rib.get(d)
        return 0 if r is None else r[field]

    for key, field, lbl in (("RIBSTK", "stack", "日线 ribbon 完全排列同向"),
                            ("RIB821", "e821", "日线 8EMA vs 21EMA 同向"),
                            ("RIBC48", "c48", "日线收盘 vs 48EMA 同向")):
        S.append(Spec(key, "⑥日线方向", lbl,
                      gate=lambda c, f=field: _rib(c.sday, f) == c.direction,
                      sub=lambda ts, f=field: [t for t in ts
                                               if _rib(trade_day_of(t), f) == t.direction]))
    S.append(Spec("RIBSTKX", "⑥日线方向", "日线完全排列【逆】向（对照）",
                  gate=lambda c: _rib(c.sday, "stack") == -c.direction,
                  sub=lambda ts: [t for t in ts
                                  if _rib(trade_day_of(t), "stack") == -t.direction]))
    return S


# ═══════════════════════════════ measurement ═════════════════════════════════
def _norm_q(p: float) -> float:
    """Inverse standard normal CDF (Acklam), good to ~1e-9 — for Bonferroni."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        qq = math.sqrt(-2 * math.log(p))
        return (((((c[0]*qq+c[1])*qq+c[2])*qq+c[3])*qq+c[4])*qq+c[5]) / \
               ((((d[0]*qq+d[1])*qq+d[2])*qq+d[3])*qq+1)
    if p > ph:
        qq = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*qq+c[1])*qq+c[2])*qq+c[3])*qq+c[4])*qq+c[5]) / \
               ((((d[0]*qq+d[1])*qq+d[2])*qq+d[3])*qq+1)
    qq = p - 0.5
    r = qq * qq
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*qq / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def q(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def race(trades: list[Trade], bars: list[Bar], subs: list[list[Bar]] | None,
         cap: int = RACE_CAP) -> dict:
    """Pure bracket: protective vs T1, exit rule deleted.  Geometric null."""
    k = n = unres = 0
    sp = spq = 0.0
    for t in trades:
        p = t.risk / (t.risk + abs(t.t1 - t.entry))
        d, done, hit = t.direction, False, None
        for i in range(t.entry_i + 1, min(t.entry_i + 1 + cap, len(bars))):
            seq = subs[i] if subs is not None else [bars[i]]
            for sb in seq:
                ph = (sb.low <= t.prot) if d > 0 else (sb.high >= t.prot)
                gh = (sb.high >= t.t1) if d > 0 else (sb.low <= t.t1)
                if ph and gh:
                    done, hit = True, None
                    break
                if gh:
                    done, hit = True, True
                    break
                if ph:
                    done, hit = True, False
                    break
            if done:
                break
        if hit is None:
            unres += 1
            continue
        n += 1
        k += int(hit)
        sp += p
        spq += p * (1 - p)
    z = (k - sp) / math.sqrt(spq) if spq > 0 else float("nan")
    return {"k": k, "n": n, "unres": unres,
            "null": sp / n if n else float("nan"),
            "obs": k / n if n else float("nan"), "z": z}


def money(t: Trade) -> float:
    """P&L of one trade per 1 unit of notional, in daily-ATR units.

    R is not a currency: a trade that risks 0.06 ATR and one that risks 0.15
    ATR report the same +1R for very different amounts of money.  Any filter
    that selects ON the risk distance therefore rigs the R ledger by changing
    its denominator.  This is the unrigged column.
    """
    return t.r * (t.risk / t.atr) if t.atr else 0.0


def _fpc_z(sub_vals: list[float], base_vals: list[float]) -> float:
    """Mean of a size-m subset vs the baseline mean, sampling m of N w/o repl."""
    n, N = len(sub_vals), len(base_vals)
    if not (0 < n < N) or N < 2:
        return float("nan")
    mu = sum(base_vals) / N
    var = st.pvariance(base_vals)
    se = math.sqrt(var / n * (N - n) / (N - 1))
    return ((sum(sub_vals) / n) - mu) / se if se > 0 else float("nan")


def summarize(trades: list[Trade], base: list[Trade], n_bars: int,
              mid_dt: datetime | None, spread: float = SPREAD) -> dict:
    n = len(trades)
    rs = [t.r for t in trades]
    ms = [money(t) for t in trades]
    out = {"n": n, "pct": 100.0 * n / len(base) if base else float("nan"),
           "per1k": 1000.0 * n / n_bars if n_bars else float("nan")}
    if n == 0:
        nan = float("nan")
        return out | {"win": 0, "win_rate": nan, "ci": (0.0, 1.0),
                      "total_r": 0.0, "avg_r": nan, "cost_r": 0.0, "net_r": 0.0,
                      "z_sel": nan, "z_r": nan, "h1": 0.0, "h2": 0.0,
                      "h1n": 0, "h2n": 0, "med_hold": nan, "med_risk": nan,
                      "med_risk_atr": nan, "avg_win": nan, "avg_loss": nan,
                      "money": 0.0, "money_net": 0.0, "z_sel_money": nan,
                      "z_money": nan}
    k = sum(1 for r in rs if r > 1e-12)
    e = stats.expectancy(rs)
    cost = sum(spread / t.risk for t in trades if t.risk > 0)
    cost_m = sum(spread / t.atr for t in trades if t.atr > 0)
    sdz = st.stdev(rs) if n > 1 else 0.0
    sdm = st.stdev(ms) if n > 1 else 0.0
    out |= {"win": k, "win_rate": k / n, "ci": stats.wilson(k, n),
            "total_r": e["total_r"], "avg_r": e["avg_r"],
            "avg_win": e["avg_win"], "avg_loss": e["avg_loss"],
            "med_hold": st.median([t.hold for t in trades]),
            "med_risk": st.median([t.risk for t in trades]),
            "med_risk_atr": st.median([t_risk_atr(t) for t in trades]),
            "cost_r": cost, "net_r": e["total_r"] - cost,
            "money": sum(ms), "money_net": sum(ms) - cost_m,
            "z_r": e["avg_r"] / (sdz / math.sqrt(n)) if n > 1 and sdz > 0 else float("nan"),
            "z_money": (sum(ms) / n) / (sdm / math.sqrt(n))
                       if n > 1 and sdm > 0 else float("nan"),
            "z_sel": _fpc_z(rs, [t.r for t in base]),
            "z_sel_money": _fpc_z(ms, [money(t) for t in base])}
    if mid_dt is not None:
        out["h1"] = sum(t.r for t in trades if t.entry_dt < mid_dt)
        out["h2"] = sum(t.r for t in trades if t.entry_dt >= mid_dt)
        out["h1n"] = sum(1 for t in trades if t.entry_dt < mid_dt)
        out["h2n"] = sum(1 for t in trades if t.entry_dt >= mid_dt)
    return out


def boot_subset(base_r: list[float], m: int, draws: int = BOOT) -> dict:
    """What a RANDOM m-subset of the baseline looks like — the illusion yardstick."""
    if m <= 0 or m >= len(base_r):
        return {"p_pos": float("nan"), "sd": float("nan"), "p95": float("nan")}
    tot = []
    for _ in range(draws):
        tot.append(sum(random.sample(base_r, m)))
    tot.sort()
    return {"p_pos": sum(1 for x in tot if x > 0) / draws,
            "sd": st.pstdev(tot), "p95": tot[int(0.95 * draws)],
            "p05": tot[int(0.05 * draws)]}


# ═══════════════════════════════ datasets ════════════════════════════════════
def to_nm(bars: list[Bar], n: int) -> tuple[list[Bar], list[list[Bar]]]:
    out: list[Bar] = []
    subs: list[list[Bar]] = []
    key = None
    buf: list[Bar] = []

    def flush() -> None:
        if buf:
            out.append(Bar(buf[0].dt, buf[0].day, buf[0].open,
                           max(b.high for b in buf), min(b.low for b in buf),
                           buf[-1].close, sum(b.volume for b in buf)))
            subs.append(list(buf))

    for b in bars:
        k = (b.day, b.dt.hour, b.dt.minute // n)
        if k != key:
            flush()
            buf, key = [], k
        buf.append(b)
    flush()
    return out, subs


def load_1m(symbol: str) -> list[Bar]:
    path = CACHE / f"{symbol.replace('^','IDX_').replace('=','_')}__1m_chunks.json"
    rows = json.loads(path.read_text())
    out = []
    for ts, o, hi, lo, c in rows:
        dt = datetime.fromtimestamp(ts, ET)
        out.append(Bar(dt, dt.date(), float(o), float(hi), float(lo), float(c), 0.0))
    return out


def build(name: str, symbol: str, rth_only: bool, kind: str) -> dict:
    if kind == "10m":
        b5 = data.load(symbol, "60d", "5m")
        if rth_only:
            b5 = drop_close_stub(b5)
        bars, subs = to_10m(b5)
    else:
        bars = data.load(symbol, "730d", "1h")
        if rth_only:
            bars = [b for b in bars if not (b.dt.hour == 16 and b.dt.minute == 0)]
        subs = None
    daily = data.load(symbol, "20y", "1d")
    return {"name": name, "symbol": symbol, "bars": bars, "subs": subs,
            "book": LevelBook(daily), "rib": RibbonBook(daily),
            "has_on": not rth_only, "kind": kind}


# ═══════════════════════════════ reporting ═══════════════════════════════════
def hdr(o: list[str], s: str) -> None:
    o.append("")
    o.append(s)
    o.append("")


def _z(x: float) -> str:
    return "–" if x != x else f"{x:+.2f}"


HEAD = ("| 过滤器 | n | 占基线 | 胜率 | 毛R | 均R | z_R | 净R(0.6点) | "
        "钱(毛,ATR) | 钱(净,ATR) | z_sel(R) | z_sel(钱) | 前半R / 后半R |")
RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def fmt_row(lbl: str, m: dict) -> str:
    if m["n"] == 0:
        return f"| {lbl} | 0 | 0% | – | – | – | – | – | – | – | – | – | – |"
    lo, hi = m["ci"]
    return (f"| {lbl} | {m['n']} | {m['pct']:.0f}% | "
            f"{100*m['win_rate']:.1f}% [{100*lo:.0f},{100*hi:.0f}] | "
            f"{m['total_r']:+.1f} | {m['avg_r']:+.3f} | {_z(m['z_r'])} | "
            f"{m['net_r']:+.1f} | {m['money']:+.2f} | {m['money_net']:+.2f} | "
            f"{_z(m['z_sel'])} | {_z(m['z_sel_money'])} | "
            f"{m.get('h1',0):+.1f} / {m.get('h2',0):+.1f} |")


def main() -> None:
    o: list[str] = []
    cells = 0
    sets = [
        build("B · ES=F 10m（23h，最接近 SPX500 CFD）", "ES=F", False, "10m"),
        build("A · ^GSPC 10m（RTH-only，60 天）", "^GSPC", True, "10m"),
        build("D · ES=F 1h（730 天，23h）", "ES=F", False, "1h"),
        build("C · ^GSPC 1h（730 天，RTH）", "^GSPC", True, "1h"),
    ]

    o.append("# V14 执行层过滤器：「少做」能不能把负期望变正")
    o.append("")
    o.append("入场逻辑一字未改（与 `study_v14_repro` 逐字相同）。"
             "本轮只改**要不要接这一笔**。")
    o.append("")
    o.append("每个过滤器都必须同时回答两个问题：**它砍掉了多少笔**，"
             "以及**剩下的笔是不是更好**。第二个问题由 `z_sel` 回答——"
             "把过滤后的均 R 与「从基线里随机抽同样多笔」的分布相比"
             "（有限总体修正）。z_sel≈0 = 只是少交易，不是更会挑。")
    o.append("")

    results_for_struct = []
    all_metrics = {}

    for ds in sets:
        name, bars, subs, book, rib = (ds["name"], ds["bars"], ds["subs"],
                                       ds["book"], ds["rib"])
        # sanity: the gated engine with no gate must equal the audited baseline
        base_ref, _ = run_v14(bars, book, subs)
        base, dbase = run_gated(bars, book, subs)
        assert len(base) == len(base_ref) and \
            abs(sum(t.r for t in base) - sum(t.r for t in base_ref)) < 1e-9, \
            f"gated engine diverged from run_v14 on {name}"
        n_bars = dbase["setup_bars"]
        ds["n_bars"] = n_bars
        mid = base[len(base) // 2].entry_dt if base else None
        base_r = [t.r for t in base]
        specs = build_specs(rib)

        hdr(o, f"## {name}")
        o.append(f"样本 {bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，"
                 f"setup K {n_bars} 根；基线 {len(base)} 笔 "
                 f"= 每千根 {1000*len(base)/n_bars:.1f} 笔，"
                 f"总R {sum(base_r):+.1f}，均R {sum(base_r)/len(base):+.3f}")
        o.append("")
        o.append("**主表 = in-engine（拒单会释放仓位，后面的 setup 可能补上）**")
        o.append("")
        o.append(HEAD)
        o.append(RULE)

        ds_metrics = {}
        for sp in specs:
            if sp.key == "BASE":
                tr = base
            else:
                tr, _ = run_gated(bars, book, subs, gate=sp.gate, daycap=sp.daycap)
            m = summarize(tr, base, n_bars, mid)
            ds_metrics[sp.key] = (sp, tr, m)
            cells += 1
            o.append(fmt_row(f"{sp.group} {sp.label}", m))
        all_metrics[name] = ds_metrics

        # post-hoc subset table — paired, so z_sel is exact
        o.append("")
        o.append("**对照表 = post-hoc 子集（每笔 R 与基线完全相同，配对比较；"
                 "与 in-engine 的差 = 释放仓位后补进来的那些笔）**")
        o.append("")
        o.append("| 过滤器 | n | 占基线 | 胜率 | 毛R | 均R | 净R(0.6点) | "
                 "钱(净,ATR) | z_sel(R) | z_sel(钱) | 与 in-engine 差 |")
        o.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for sp in specs:
            sub = base if sp.sub is None else sp.sub(base)
            m2 = summarize(sub, base, n_bars, mid)
            cells += 1
            d_in = ds_metrics[sp.key][2]
            dd = (f"{m2['total_r']-d_in['total_r']:+.1f}R / "
                  f"{m2['n']-d_in['n']:+d} 笔")
            lo, hi = m2["ci"]
            if m2["n"] == 0:
                o.append(f"| {sp.group} {sp.label} | 0 | 0% | – | – | – | – | – | – | {dd} |")
            else:
                o.append(f"| {sp.group} {sp.label} | {m2['n']} | {m2['pct']:.0f}% | "
                         f"{100*m2['win_rate']:.1f}% [{100*lo:.0f},{100*hi:.0f}] | "
                         f"{m2['total_r']:+.1f} | {m2['avg_r']:+.3f} | "
                         f"{m2['net_r']:+.1f} | {m2['money_net']:+.2f} | "
                         f"{_z(m2['z_sel'])} | {_z(m2['z_sel_money'])} | {dd} |")

        # quantity-vs-quality correlation across the whole family
        pts = [(m["pct"], m["avg_r"]) for k, (s, t, m) in ds_metrics.items()
               if k != "BASE" and m["n"] >= 15]
        if len(pts) >= 5:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            num = sum((a - mx) * (b - my) for a, b in pts)
            den = math.sqrt(sum((a - mx) ** 2 for a in xs) *
                            sum((b - my) ** 2 for b in ys))
            r = num / den if den else float("nan")
            o.append("")
            o.append(f"- **「砍得越狠越好」检验**：{len(pts)} 个 n≥15 的过滤器上，"
                     f"保留率与均R 的相关系数 r = {r:+.2f}"
                     f"（r 显著为负才意味着「少做=更好」；≈0 意味着挑选没有信息）")

        # geometric null, only where path order can be arbitrated
        o.append("")
        o.append("**几何零假设（删掉 13 线离场，只跑 保护位 vs T1 的两栏赛跑）**")
        o.append("")
        pr = "5m 子K 裁决" if subs is not None else "1h K 裁决（同根双触=不裁决，见下）"
        o.append(f"| 过滤器 | 已裁决 n | T1 先到 | 几何零假设 S/(S+T) | 超额 | z_geom | 未裁决 |")
        o.append("|---|---|---|---|---|---|---|")
        for sp in specs:
            _, tr, m = ds_metrics[sp.key]
            if m["n"] < 12:
                continue
            rc = race(tr, bars, subs)
            cells += 1
            if rc["n"] == 0:
                continue
            o.append(f"| {sp.group} {sp.label} | {rc['n']} | {100*rc['obs']:.1f}% | "
                     f"{100*rc['null']:.1f}% | {100*(rc['obs']-rc['null']):+.1f}pp | "
                     f"{rc['z']:+.2f} | {rc['unres']} |")
            ds_metrics[sp.key] = (sp, tr, m | {"race": rc})
        o.append("")
        o.append(f"（路径口径：{pr}）")

    # ═══════════════════ cross-dataset sign consistency ══════════════════════
    hdr(o, "## 跨数据集符号一致性（一个过滤器要活下来，四张表得指同一个方向）")
    o.append("| 过滤器 | B·ES=F 10m | A·^GSPC 10m | D·ES=F 1h | C·^GSPC 1h | 净R 为正的数据集 |")
    o.append("|---|---|---|---|---|---|")
    order = [s.key for s in build_specs(sets[0]["rib"])]
    names = [ds["name"] for ds in sets]
    for key in order:
        cellsx = []
        pos = 0
        for nm in names:
            m = all_metrics[nm][key][2]
            if m["n"] == 0:
                cellsx.append("–")
                continue
            pos += int(m["net_r"] > 0)
            cellsx.append(f"{m['avg_r']:+.3f} / 净{m['net_r']:+.1f} "
                          f"(n={m['n']}, z_sel {_z(m['z_sel'])})")
        lbl = all_metrics[names[0]][key][0]
        o.append(f"| {lbl.group} {lbl.label} | " + " | ".join(cellsx) +
                 f" | **{pos}/4** |")
        cells += 1

    # ══════════ why the risk filter "works": the R denominator moves ═════════
    prim0 = sets[0]
    base0 = all_metrics[prim0["name"]]["BASE"][1]
    hdr(o, "## ④ 为什么风险距离过滤器能把 R 变正——它换的是分母，不是入场")
    o.append("把基线按风险距离（ATR 归一）分四档，每档同时报 R 和「钱」"
             "（钱 = R × 风险/ATR，即每 1 单位名义的盈亏，以日 ATR 为单位）。"
             "如果 R 随档位上升而钱不动，那 R 的改善就是分母造成的记账错觉。")
    o.append("")
    o.append("| 风险档（ATR） | n | 胜率 | 均R | 总R | 均钱 | 总钱 | "
             "中位风险(ATR) | 中位风险(点) | 0.6点成本占风险 | 被扫止损占比 |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|")
    ra = sorted(t_risk_atr(t) for t in base0)
    qs = [ra[int(len(ra) * f)] for f in (0.25, 0.50, 0.75)]
    buckets = [("Q1 最小", -1e9, qs[0]), ("Q2", qs[0], qs[1]),
               ("Q3", qs[1], qs[2]), ("Q4 最大", qs[2], 1e9)]
    for lbl, lo_, hi_ in buckets:
        g = [t for t in base0 if lo_ <= t_risk_atr(t) < hi_]
        if not g:
            continue
        cells += 1
        kk = sum(1 for t in g if t.r > 1e-12)
        mm = [money(t) for t in g]
        o.append(f"| {lbl} [{lo_ if lo_>-1e8 else 0:.3f},"
                 f"{hi_ if hi_<1e8 else 9.999:.3f}) | {len(g)} | "
                 f"{100*kk/len(g):.1f}% | {sum(t.r for t in g)/len(g):+.3f} | "
                 f"{sum(t.r for t in g):+.1f} | {sum(mm)/len(g):+.4f} | "
                 f"{sum(mm):+.2f} | {st.median([t_risk_atr(t) for t in g]):.3f} | "
                 f"{st.median([t.risk for t in g]):.2f} | "
                 f"{100*st.median([SPREAD/t.risk for t in g]):.1f}% | "
                 f"{100*sum(1 for t in g if t.exit_reason=='PROT')/len(g):.1f}% |")

    o.append("")
    o.append("同一张表在四个数据集上（`≥X ATR` 这个绝对门槛在 1h 上几乎不筛东西，"
             "所以下面第二张表改用**分位数门槛**，让四个周期可比）：")
    o.append("")
    o.append("| 数据集 | Q1 均R / 均钱 | Q2 均R / 均钱 | Q3 均R / 均钱 | Q4 均R / 均钱 | "
             "Q4−Q1 均钱 |")
    o.append("|---|---|---|---|---|---|")
    for ds in sets:
        bb = all_metrics[ds["name"]]["BASE"][1]
        ra2 = sorted(t_risk_atr(t) for t in bb)
        qq = [ra2[int(len(ra2) * f)] for f in (0.25, 0.50, 0.75)]
        row, mus = [], []
        for lo_, hi_ in ((-1e9, qq[0]), (qq[0], qq[1]), (qq[1], qq[2]), (qq[2], 1e9)):
            g = [t for t in bb if lo_ <= t_risk_atr(t) < hi_]
            cells += 1
            if not g:
                row.append("–")
                mus.append(float("nan"))
                continue
            mm = sum(money(t) for t in g) / len(g)
            mus.append(mm)
            row.append(f"{sum(t.r for t in g)/len(g):+.3f} / {mm:+.4f}")
        o.append(f"| {ds['name'].split('（')[0]} | " + " | ".join(row) +
                 f" | {mus[3]-mus[0]:+.4f} |")

    # ── do the four datasets even overlap in stop size? ──
    o.append("")
    o.append("上表的四行不能直接对比，因为四个数据集的风险距离根本不在同一个量程上。"
             "下表按**绝对 ATR 分箱**，只在重叠的箱子里比较：")
    o.append("")
    bins = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 99.0)]
    o.append("| 风险箱(ATR) | " + " | ".join(
        f"{ds['name'].split('·')[0].strip()} n / 均R / 均钱" for ds in sets) + " |")
    o.append("|---|" + "---|" * len(sets))
    for lo_, hi_ in bins:
        row = []
        for ds in sets:
            g = [t for t in all_metrics[ds["name"]]["BASE"][1]
                 if lo_ <= t_risk_atr(t) < hi_]
            cells += 1
            row.append("–" if len(g) < 5 else
                       f"{len(g)} / {sum(t.r for t in g)/len(g):+.3f} / "
                       f"{sum(money(t) for t in g)/len(g):+.4f}")
        o.append(f"| [{lo_:.2f},{hi_ if hi_<90 else 9.99:.2f}) | " + " | ".join(row) + " |")

    # ── timeframe-invariant version: keep the widest-stop half / quarter ──
    o.append("")
    o.append("**分位数门槛（每个数据集用自己的风险分布，"
             "所以 10m 与 1h 可比；注意这用到了全样本分位数=有前视，"
             "只能算「给过滤器开外挂后仍然」的检验）**")
    o.append("")
    o.append("| 数据集 | 门槛 | n | 占基线 | 胜率 | 毛R | 净R | 钱(净,ATR) | "
             "z_sel(R) | z_sel(钱) | z_geom |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for ds in sets:
        bb = all_metrics[ds["name"]]["BASE"][1]
        ra2 = sorted(t_risk_atr(t) for t in bb)
        midd = bb[len(bb) // 2].entry_dt
        for lbl, f in (("最宽的 50%", 0.50), ("最宽的 25%", 0.75)):
            thr = ra2[int(len(ra2) * f)]
            tr, _ = run_gated(ds["bars"], ds["book"], ds["subs"],
                              gate=lambda c, thr=thr: c.risk_atr >= thr)
            m = summarize(tr, bb, ds["n_bars"], midd)
            cells += 1
            zg = "–"
            if m["n"] >= 12:
                rc = race(tr, ds["bars"], ds["subs"])
                zg = f"{rc['z']:+.2f}"
                cells += 1
            o.append(f"| {ds['name'].split('（')[0]} | {lbl} (≥{thr:.3f} ATR) | "
                     f"{m['n']} | {m['pct']:.0f}% | {100*m['win_rate']:.1f}% | "
                     f"{m['total_r']:+.1f} | {m['net_r']:+.1f} | "
                     f"{m['money_net']:+.2f} | {_z(m['z_sel'])} | "
                     f"{_z(m['z_sel_money'])} | {zg} |")

    # ═════════════ combinations — an explicit data-dredging exhibit ══════════
    hdr(o, "## 组合过滤器（明示的挖数据展览：从 8 个组合里挑最好的那个）")
    rib0 = prim0["rib"]

    def _ribg(d: date, f: str) -> int:
        r = rib0.get(d)
        return 0 if r is None else r[f]

    combos = [
        ("风险≥0.10 + RTH", lambda c: c.risk_atr >= 0.10 and c.in_rth, None),
        ("风险≥0.15 + RTH", lambda c: c.risk_atr >= 0.15 and c.in_rth, None),
        ("风险≥0.10 + 每日≤2", lambda c: c.risk_atr >= 0.10, 2),
        ("风险≥0.15 + 每日≤2", lambda c: c.risk_atr >= 0.15, 2),
        ("风险≥0.10 + 开盘2小时", lambda c: c.risk_atr >= 0.10 and 0 <= c.mins_from_open < 120, None),
        ("风险≥0.15 + T1≥0.20ATR", lambda c: c.risk_atr >= 0.15 and c.t1_atr >= 0.20, None),
        ("风险≥0.10 + 日线逆向", lambda c: c.risk_atr >= 0.10 and _ribg(c.sday, "stack") == -c.direction, None),
        ("风险≥0.10 + RTH + 每日≤2", lambda c: c.risk_atr >= 0.10 and c.in_rth, 2),
    ]
    o.append(HEAD)
    o.append(RULE)
    mid0 = base0[len(base0) // 2].entry_dt
    combo_ms = []
    for lbl, g, cap in combos:
        tr, _ = run_gated(prim0["bars"], prim0["book"], prim0["subs"], gate=g, daycap=cap)
        m = summarize(tr, base0, prim0["n_bars"], mid0)
        combo_ms.append((lbl, tr, m))
        cells += 1
        o.append(fmt_row(lbl, m))
    o.append("")
    for lbl, tr, m in combo_ms:
        if m["n"] >= 12:
            rc = race(tr, prim0["bars"], prim0["subs"])
            cells += 1
            o.append(f"- {lbl}：几何赛跑 T1 先到 {100*rc['obs']:.1f}% vs "
                     f"零假设 {100*rc['null']:.1f}%，z_geom={rc['z']:+.2f}（n={rc['n']}）")

    # the only test that matters for a dredged combo: does it move?
    o.append("")
    o.append("**把挑出来的前三名原样搬到另外三个数据集（唯一有意义的检验）**")
    o.append("")
    o.append("| 组合 | B·ES=F 10m | A·^GSPC 10m | D·ES=F 1h | C·^GSPC 1h | 净R 为正 |")
    o.append("|---|---|---|---|---|---|")
    top3 = sorted(zip(combos, combo_ms), key=lambda x: -x[1][2]["net_r"])[:3]
    for (lbl, g, cap), _ in top3:
        row, pos = [], 0
        for ds in sets:
            bb = all_metrics[ds["name"]]["BASE"][1]
            midd = bb[len(bb) // 2].entry_dt
            tr, _ = run_gated(ds["bars"], ds["book"], ds["subs"], gate=g, daycap=cap)
            m = summarize(tr, bb, ds["n_bars"], midd)
            cells += 1
            pos += int(m["n"] > 0 and m["net_r"] > 0)
            row.append("–" if m["n"] == 0 else
                       f"n={m['n']} 净{m['net_r']:+.1f} 钱{m['money_net']:+.2f} "
                       f"(z_sel {_z(m['z_sel'])})")
        o.append(f"| {lbl} | " + " | ".join(row) + f" | **{pos}/4** |")

    # ═════════════ selection-illusion demo on the primary dataset ════════════
    prim = sets[0]["name"]
    dsm = all_metrics[prim]
    base = dsm["BASE"][1]
    base_r = [t.r for t in base]
    hdr(o, "## 「砍到 n 笔就转正」是不是幻觉：随机子集对照")
    o.append("对每个过滤器，问一个更苛刻的问题：**从基线里随机抽同样多笔**，"
             "总R 长什么样？如果过滤器的总R 落在随机子集的中间 90% 里，"
             "它就没有提供任何选择信息。")
    o.append("")
    o.append("| 过滤器 | n | 实际毛R | 随机同规模子集 5%–95% | 随机子集总R>0 的概率 | 判定 |")
    o.append("|---|---|---|---|---|---|")
    for key, (sp, tr, m) in dsm.items():
        if key == "BASE" or m["n"] < 10:
            continue
        bs = boot_subset(base_r, m["n"])
        cells += 1
        if m["total_r"] > bs["p95"]:
            verdict = "**高于随机 95%**"
        elif m["total_r"] < bs["p05"]:
            verdict = "低于随机 5%（选得更差）"
        else:
            verdict = "区间内 = 无选择信息"
        o.append(f"| {sp.group} {sp.label} | {m['n']} | {m['total_r']:+.1f} | "
                 f"[{bs['p05']:+.1f}, {bs['p95']:+.1f}] | {100*bs['p_pos']:.1f}% | "
                 f"{verdict} |")

    # ═════════════════ the 3m / 10m overnight contradiction ══════════════════
    hdr(o, "## 夜盘的矛盾：3m 上 +3.7R，10m 上 −28.2R")
    b1 = load_1m("ES=F")
    daily = data.load("ES=F", "20y", "1d")
    book1 = LevelBook(daily)
    o.append(f"用同一段 1 分钟数据（ES=F，{b1[0].dt:%Y-%m-%d} → {b1[-1].dt:%Y-%m-%d}，"
             f"{len(set(trade_day(b) for b in b1))} 个 23h session）"
             f"同时构造 3m / 5m / 10m / 15m 四张图，跑同一套 v14。"
             f"**同期同标的**，所以周期是唯一变量。")
    o.append("")
    o.append("| 周期 | K 数 | 笔数 | 每千根 | 胜率 | 毛R | 中位风险(点) | 中位风险(ATR) | "
             "0.6点成本 | 净R | 夜盘毛R | RTH毛R |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    tf_rows = {}
    for nmin in (3, 5, 10, 15):
        bb, ss = to_nm(b1, nmin)
        tr, dg = run_gated(bb, book1, ss)
        cells += 1
        if not tr:
            continue
        on = [t for t in tr if t.session != "RTH"]
        rth = [t for t in tr if t.session == "RTH"]
        cost = sum(SPREAD / t.risk for t in tr)
        k = sum(1 for t in tr if t.r > 1e-12)
        tf_rows[nmin] = (tr, on, rth)
        o.append(f"| {nmin}m | {dg['setup_bars']} | {len(tr)} | "
                 f"{1000*len(tr)/dg['setup_bars']:.1f} | {100*k/len(tr):.1f}% | "
                 f"{sum(t.r for t in tr):+.1f} | "
                 f"{st.median([t.risk for t in tr]):.2f} | "
                 f"{st.median([t_risk_atr(t) for t in tr]):.3f} | "
                 f"−{cost:.1f} | {sum(t.r for t in tr)-cost:+.1f} | "
                 f"{sum(t.r for t in on):+.1f} (n={len(on)}) | "
                 f"{sum(t.r for t in rth):+.1f} (n={len(rth)}) |")

    o.append("")
    o.append("**夜盘切片的分期稳定性与「钱」口径**")
    o.append("")
    o.append("| 周期 | 夜盘 n | 夜盘毛R | 前半 / 后半 | 每笔R的sd | 总R 的 1sd | "
             "z(总R vs 0) | 夜盘钱(毛,ATR) | 夜盘钱(净,ATR) |")
    o.append("|---|---|---|---|---|---|---|---|---|")
    for nmin in (3, 5, 10, 15):
        if nmin not in tf_rows:
            continue
        tr, on, _ = tf_rows[nmin]
        if len(on) < 3:
            continue
        cells += 1
        onm = sorted(on, key=lambda t: t.entry_dt)
        h = len(onm) // 2
        sd = st.stdev([t.r for t in on])
        se_tot = sd * math.sqrt(len(on))
        gm = sum(money(t) for t in on)
        cm = sum(SPREAD / t.atr for t in on)
        o.append(f"| {nmin}m | {len(on)} | {sum(t.r for t in on):+.1f} | "
                 f"{sum(t.r for t in onm[:h]):+.1f} / {sum(t.r for t in onm[h:]):+.1f} | "
                 f"{sd:.2f} | ±{se_tot:.1f}R | "
                 f"{sum(t.r for t in on)/se_tot if se_tot else float('nan'):+.2f} | "
                 f"{gm:+.2f} | {gm-cm:+.2f} |")
    if 10 in tf_rows:
        _, on10, _ = tf_rows[10]
        sd10 = st.stdev([t.r for t in on10])
        se509 = sd10 * math.sqrt(509)
        o.append("")
        o.append(f"- 线上夜盘那本账 509 笔。以 {sd10:.2f} 的每笔 R 的 sd 计，"
                 f"「总R」这个数字的 1 个标准误就是 ±{se509:.1f}R。"
                 f"**+3.7R 与 −28.2R 相差 31.9R = {31.9/se509:.2f} 个标准误** "
                 f"(双侧 p≈{2*(1-0.5*(1+math.erf((31.9/se509)/math.sqrt(2)))):.2f})"
                 f"——两张图的夜盘账本在统计上区分不开，"
                 f"「3m 夜盘赚钱、10m 夜盘亏钱」不是一个需要机制解释的现象。")
    if 3 in tf_rows and 10 in tf_rows:
        tr3, on3, _ = tf_rows[3]
        tr10, on10, _ = tf_rows[10]
        c3 = st.median([SPREAD / t.risk for t in on3])
        c10 = st.median([SPREAD / t.risk for t in on10])
        o.append(f"- 第二重解释是**成本**：0.6 点点差在 3m 夜盘每笔要扣 "
                 f"{c3:.3f}R（中位），在 10m 夜盘只扣 {c10:.3f}R——"
                 f"3m 的摩擦是 10m 的 {c3/c10:.1f} 倍。"
                 f"一本 500 笔的 3m 夜盘毛账 +3.7R，净账就是 "
                 f"{3.7 - 500*c3:+.1f}R。**毛R 转正在 3m 上没有任何意义。**")
        o.append(f"- 第三重解释是**R 不是钱**：3m 夜盘中位风险 "
                 f"{st.median([t_risk_atr(t) for t in on3]):.3f} ATR，"
                 f"10m 夜盘 {st.median([t_risk_atr(t) for t in on10]):.3f} ATR。"
                 f"同样的 1R 在 3m 上只有 10m 上 "
                 f"{st.median([t_risk_atr(t) for t in on3])/st.median([t_risk_atr(t) for t in on10]):.0%} "
                 f"的钱。把两本账换成同一单位（每 1 单位名义、以日 ATR 计），"
                 f"3m 夜盘 {sum(money(t) for t in on3):+.2f} ATR，"
                 f"10m 夜盘 {sum(money(t) for t in on10):+.2f} ATR。")

    # ═══════════════════════ family-wise selection cost ══════════════════════
    hdr(o, "## 挑选的代价：这批 z 值里最大的那个，本来就该有多大")
    zs = []
    for nm in names:
        for key, (sp, tr, m) in all_metrics[nm].items():
            if key != "BASE" and m["n"] >= 10 and m["z_sel"] == m["z_sel"]:
                zs.append((abs(m["z_sel"]), nm, sp.label, m["z_sel"]))
    zs.sort(reverse=True)
    K = len(zs)
    exp_max = math.sqrt(2 * math.log(K)) if K > 1 else 0.0
    o.append(f"- 全部 {K} 个「过滤器 × 数据集」格子给出了 {K} 个 z_sel。"
             f"在完全没有信息的零假设下，{K} 个独立标准正态里最大的 |z| "
             f"期望约 **{exp_max:.2f}**；Bonferroni 双侧 5% 门槛是 "
             f"**|z| > {_norm_q(1 - 0.025 / K):.2f}**。")
    o.append("- 实际最大的五个：")
    for a, nm, lbl, zv in zs[:5]:
        o.append(f"  - {lbl}（{nm.split('·')[0].strip()}）z_sel = {zv:+.2f}")
    o.append("")

    # ═════════════════════════════ verdict ══════════════════════════════════
    hdr(o, "## 结论")
    o.append(f"- 本轮共检视 **{cells} 个格子**。候选集不是 1，"
             f"所以任何「最好的那个」都必须先扣掉挑选的代价。")
    o.append("")

    txt = "\n".join(o)
    print(txt)
    rep = Path(__file__).resolve().parents[1] / "reports" / "V14_EXECUTION_FILTERS_raw.txt"
    rep.write_text(txt)
    return all_metrics


if __name__ == "__main__":
    main()
