"""Faithful re-implementation of IDM v14's two state machines, for audit.

Why this file exists
--------------------
IDM v14 went live on CAPITALCOM:SPX500 10m and its own on-chart ledger read
695 trades / 32% / -44.1R.  695 trades over the chart's history is roughly one
trade every 7 setup bars, which is not a discretionary method, it is churn.
Before changing a single rule we have to know *whether the churn is real and
where the R goes*.  So this module transcribes the Pine literally — same order
of operations, same tie-breaks, same accounting — and replays it on bars we
control, so every trade can be dissected.

Transcription notes (the details that change the answer)
--------------------------------------------------------
* The live chart runs setupTF == chart TF == 10m, therefore `useHTF` is FALSE
  in the Pine and the state machines read the CURRENT confirmed bar's EMAs and
  OHLC — not a [1]-shifted higher-timeframe series.  `newSetupBar` is always
  true.  Reproducing the HTF branch instead would be reproducing a code path
  the user is not running.
* Order inside one confirmed bar is: (1) advance the sBull/sBear stack
  counters, (2) manage the open position, (3) run the four setup machines.
  An exit and a fresh entry can therefore happen on the SAME bar.
* `hitProt` short-circuits the whole exit block: when a bar both reaches the
  protective price and a target, the Pine books the protective exit.  That is
  the conservative tie-break and it is preserved here.  `hitT2` is evaluated
  from the bar-open value of pT1done, so T1 and T2 can never both fill on one
  bar.
* Recovery clears its pullback state on ANY close back through the 13
  (`recL := 0` sits outside the risk filter), while Vomy clears its state only
  when an entry actually fires (`vomS := 0` sits INSIDE `if risk >= minRisk`).
  That asymmetry is in the source and is reproduced.
* `vomSConf` / `vomLConf` ("broke and held the 48") are computed and then never
  read.  The 48 confirmation does not gate anything.  Reproduced as-is, and
  recorded so we can measure what gating on it would have done.

Level caveat (see levels.py): ^GSPC is not the traded instrument and its ATR
runs 0.83-1.42x the CFD's.  So targets here are reported in ATR-normalised and
R-normalised distance, never as "the price of the call trigger".

Usage:  .venv/bin/python research/satylab/study_v14_repro.py
"""

from __future__ import annotations

import statistics as st
import sys
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                    # noqa: E402
from satylab.data import Bar                               # noqa: E402
from satylab.indicators import ema                         # noqa: E402

# ── v14 inputs, verbatim from the Pine defaults ──────────────────────────────
STACK_BARS = 5
MIN_RISK_PTS = 2.0
RUNGS = (-1.618, -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236, 0.0,
         0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
MINTICK = 0.01
SPREADS = (0.4, 0.6, 0.8)


# ═════════════════════════════ bar plumbing ═════════════════════════════════
def to_10m(bars5: list[Bar]) -> tuple[list[Bar], list[list[Bar]]]:
    """Aggregate 5m -> 10m on wall-clock 10-minute boundaries.

    Returns the 10m series and, for each 10m bar, the 5m sub-bars it was made
    from — the only legitimate way to resolve intrabar path order (a 10m bar's
    range is routinely wider than the whole stop distance).
    """
    out: list[Bar] = []
    subs: list[list[Bar]] = []
    key = None
    buf: list[Bar] = []

    def flush() -> None:
        if not buf:
            return
        out.append(Bar(buf[0].dt, buf[0].day, buf[0].open,
                       max(b.high for b in buf), min(b.low for b in buf),
                       buf[-1].close, sum(b.volume for b in buf)))
        subs.append(list(buf))

    for b in bars5:
        k = (b.day, b.dt.hour, b.dt.minute // 10)
        if k != key:
            flush()
            buf, key = [], k
        buf.append(b)
    flush()
    return out, subs


def drop_close_stub(bars5: list[Bar]) -> list[Bar]:
    """Remove the single 16:00 print Yahoo appends to RTH-only series."""
    return [b for b in bars5 if not (b.dt.hour == 16 and b.dt.minute == 0)]


def trade_day(b: Bar) -> date:
    """Session date: >=18:00 ET belongs to the next session (futures/CFD)."""
    return b.day + timedelta(days=1) if b.dt.hour >= 18 else b.day


class LevelBook:
    """day -> (anchor, atr), with carry-forward for days the daily feed lacks."""

    def __init__(self, daily: list[Bar]):
        lm = levels.build(daily)
        self.days = sorted(lm)
        self.map = lm

    def get(self, d: date):
        i = bisect_left(self.days, d)
        if i < len(self.days) and self.days[i] == d:
            dl = self.map[self.days[i]]
        elif i > 0:
            dl = self.map[self.days[i - 1]]      # carry the last known map
        else:
            return None
        return dl.anchor, dl.atr


def next_rung(px: float, direction: int, anchor: float, atr: float) -> float:
    """f_next_rung: nearest named ATR level strictly beyond px, else +0.236ATR."""
    best = None
    if atr > 0:
        for r in RUNGS:
            lv = anchor + r * atr
            if direction > 0 and lv > px + MINTICK and (best is None or lv < best):
                best = lv
            if direction < 0 and lv < px - MINTICK and (best is None or lv > best):
                best = lv
    return px + direction * 0.236 * atr if best is None else best


# ═════════════════════════════ trade record ═════════════════════════════════
@dataclass
class Trade:
    setup: str
    direction: int
    session: str
    entry_i: int
    exit_i: int = -1
    entry_dt: object = None
    exit_dt: object = None
    entry: float = 0.0
    prot: float = 0.0
    risk: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    atr: float = 0.0
    t1done: bool = False
    t2done: bool = False
    conf48: bool = False        # Vomy only: had it broken the 48 at entry
    pullback_bars: int = 0      # bars spent in the setup state before entry
    exit_reason: str = ""       # PROT | STRUCT
    r: float = 0.0
    legs: list = field(default_factory=list)

    @property
    def hold(self) -> int:
        return self.exit_i - self.entry_i

    @property
    def stage(self) -> str:
        return "T2" if self.t2done else ("T1" if self.t1done else "T0")

    @property
    def tag(self) -> str:
        return f"{self.exit_reason}·{self.stage}"

    @property
    def t1_dist_r(self) -> float:
        return abs(self.t1 - self.entry) / self.risk if self.risk else 0.0

    @property
    def risk_atr(self) -> float:
        return self.risk / self.atr if self.atr else 0.0


# ═════════════════════════ the v14 engine, verbatim ═════════════════════════
def run_v14(bars: list[Bar], book: LevelBook, subs: list[list[Bar]] | None = None,
            stack_bars: int = STACK_BARS, min_risk: float = MIN_RISK_PTS,
            en_recovery: bool = True, en_vomy: bool = True,
            path_resolve: bool = False) -> tuple[list[Trade], dict]:
    """Replay the Pine bar by bar.  `path_resolve` uses 5m sub-bars to order
    protective-vs-target touches instead of the Pine's conservative tie-break."""
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
    diag = {"setup_bars": 0, "rec_arm_L": 0, "rec_arm_S": 0,
            "vom_arm_S": 0, "vom_arm_L": 0,
            "rec_trigger_blocked_inpos": 0, "vom_trigger_blocked_inpos": 0,
            "blocked_minrisk": 0, "rec_cancelled": 0, "vom_cancelled": 0,
            "struct_exits": 0, "same_bar_rearm": 0}
    exit_dir_this_bar = 0

    def close_trade(t: Trade, i: int, price: float, reason: str) -> None:
        nonlocal pos, pFrac, pLegsR
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

        # ---- (1) stack counters (global scope in Pine, before the engine) ---
        prev_sBull, prev_sBear = sBull, sBear
        stack_bull = e8 > e13 > e21 > e34 > e48
        stack_bear = e8 < e13 < e21 < e34 < e48
        sBull = sBull + 1 if stack_bull else 0
        sBear = sBear + 1 if stack_bear else 0

        hh10 = max(x.high for x in bars[max(0, i - 9):i + 1])
        ll10 = min(x.low for x in bars[max(0, i - 9):i + 1])
        in_rth = (b.dt.hour, b.dt.minute) >= (9, 30) and (b.dt.hour, b.dt.minute) < (16, 0)

        # ---- (2) manage the open position -----------------------------------
        exit_dir_this_bar = 0
        if pos is not None:
            d = pos.direction
            hit_prot = (b.low <= pos.prot) if d > 0 else (b.high >= pos.prot)
            hit_t1 = (not pos.t1done) and ((b.high >= pos.t1) if d > 0 else (b.low <= pos.t1))
            hit_t2 = pos.t1done and (not pos.t2done) and \
                ((b.high >= pos.t2) if d > 0 else (b.low <= pos.t2))
            struct_out = (sc < e13) if d > 0 else (sc > e13)

            order_prot_first = True
            if path_resolve and subs is not None and hit_prot and (hit_t1 or hit_t2):
                tgt = pos.t1 if hit_t1 else pos.t2
                for sb in subs[i]:
                    p_hit = (sb.low <= pos.prot) if d > 0 else (sb.high >= pos.prot)
                    t_hit = (sb.high >= tgt) if d > 0 else (sb.low <= tgt)
                    if p_hit and t_hit:
                        break                      # still ambiguous at 5m
                    if t_hit:
                        order_prot_first = False
                        break
                    if p_hit:
                        break

            if hit_prot and order_prot_first:
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
                if hit_prot:            # path-resolved: target first, then stop
                    close_trade(pos, i, pos.prot, "PROT")
                elif struct_out:
                    exit_dir_this_bar = d
                    diag["struct_exits"] += 1
                    close_trade(pos, i, sc, "STRUCT")

        def enter(setup: str, d: int, entry: float, prot: float, risk: float,
                  started: int, conf: bool = False) -> bool:
            nonlocal pos, pFrac, pLegsR
            t1 = next_rung(entry, d, anchor, atr)
            t2 = next_rung(t1, d, anchor, atr)
            pos = Trade(setup=setup, direction=d,
                        session="RTH" if in_rth else "夜盘",
                        entry_i=i, entry_dt=b.dt, entry=entry, prot=prot,
                        risk=risk, t1=t1, t2=t2, atr=atr, conf48=conf,
                        pullback_bars=i - started)
            pFrac, pLegsR = 1.0, 0.0
            return True

        # ---- (3) setup machines, in the Pine's order -------------------------
        if en_recovery:
            # Recovery long
            if recL == 0 and sBull >= stack_bars and sc < e13:
                recL, recLExt, recL_start = 1, sl, i
                diag["rec_arm_L"] += 1
                if exit_dir_this_bar > 0:
                    # the very bar that closed the long below the 13 re-arms the
                    # long pullback — the churn loop, in one line of evidence
                    diag["same_bar_rearm"] += 1
            elif recL == 1:
                recLExt = min(recLExt, sl)
                if sc < e34 or stack_bear:
                    recL = 0
                    diag["rec_cancelled"] += 1
                elif sc > e13:
                    if pos is None:
                        risk = sc - recLExt
                        if risk >= min_risk:
                            enter("Recovery", +1, sc, recLExt, risk, recL_start)
                        else:
                            diag["blocked_minrisk"] += 1
                    else:
                        diag["rec_trigger_blocked_inpos"] += 1
                    recL = 0
            # Recovery short
            if recS == 0 and sBear >= stack_bars and sc > e13:
                recS, recSExt, recS_start = 1, sh, i
                diag["rec_arm_S"] += 1
                if exit_dir_this_bar < 0:
                    diag["same_bar_rearm"] += 1
            elif recS == 1:
                recSExt = max(recSExt, sh)
                if sc > e34 or stack_bull:
                    recS = 0
                    diag["rec_cancelled"] += 1
                elif sc < e13:
                    if pos is None:
                        risk = recSExt - sc
                        if risk >= min_risk:
                            enter("Recovery", -1, sc, recSExt, risk, recS_start)
                        else:
                            diag["blocked_minrisk"] += 1
                    else:
                        diag["rec_trigger_blocked_inpos"] += 1
                    recS = 0

        if en_vomy:
            # Vomy short (after a bull stack)
            if vomS == 0 and prev_sBull >= stack_bars and sc < e13 and sc < e8:
                vomS, vomSFin, vomSConf, vomS_start = 2, hh10, False, i
                diag["vom_arm_S"] += 1
            elif vomS == 2:
                vomSFin = max(vomSFin, sh)
                if sc < e48:
                    vomSConf = True
                if sc > e13:
                    vomS = 0
                    diag["vom_cancelled"] += 1
                elif sh >= e13:
                    if pos is None:
                        risk = vomSFin - sc
                        if risk >= min_risk:
                            enter("Vomy", -1, sc, vomSFin, risk, vomS_start, vomSConf)
                            vomS = 0
                        else:
                            diag["blocked_minrisk"] += 1
                    else:
                        diag["vom_trigger_blocked_inpos"] += 1
            # inverse Vomy long (after a bear stack)
            if vomL == 0 and prev_sBear >= stack_bars and sc > e13 and sc > e8:
                vomL, vomLFin, vomLConf, vomL_start = 2, ll10, False, i
                diag["vom_arm_L"] += 1
            elif vomL == 2:
                vomLFin = min(vomLFin, sl)
                if sc > e48:
                    vomLConf = True
                if sc < e13:
                    vomL = 0
                    diag["vom_cancelled"] += 1
                elif sl <= e13:
                    if pos is None:
                        risk = sc - vomLFin
                        if risk >= min_risk:
                            enter("Vomy", +1, sc, vomLFin, risk, vomL_start, vomLConf)
                            vomL = 0
                        else:
                            diag["blocked_minrisk"] += 1
                    else:
                        diag["vom_trigger_blocked_inpos"] += 1

    return trades, diag


# ═══════════════════════════════ reporting ══════════════════════════════════
def q(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(trades: list[Trade], label: str) -> str:
    if not trades:
        return f"{label}: n=0"
    rs = [t.r for t in trades]
    e = stats.expectancy(rs)
    k = sum(1 for r in rs if r > 1e-12)
    lo, hi = stats.wilson(k, len(rs))
    return (f"{label:<26} n={len(rs):<4} 胜率={100*k/len(rs):4.1f}% "
            f"[{100*lo:.1f},{100*hi:.1f}]  总R={e['total_r']:+7.1f}  "
            f"均R={e['avg_r']:+.3f}  均赢={e['avg_win']:+.2f} 均亏={e['avg_loss']:+.2f}  "
            f"中位持仓={st.median([t.hold for t in trades]):.0f}根")


def cost_table(trades: list[Trade]) -> list[str]:
    """Round-trip spread charged against each trade's OWN risk distance."""
    out = []
    gross = sum(t.r for t in trades)
    for s in SPREADS:
        deds = [s / t.risk for t in trades]
        tot = sum(deds)
        out.append(f"  点差 {s:.1f} 点 → 每笔扣减中位 {st.median(deds):.3f}R "
                   f"(p25 {q(deds,.25):.3f} / p75 {q(deds,.75):.3f} / 最大 {max(deds):.3f})"
                   f"  合计 -{tot:.1f}R  →  净总R {gross - tot:+.1f}")
    return out


def churn_metrics(trades: list[Trade]) -> dict:
    """How much of the book is the 13 EMA arguing with itself?"""
    holds = [t.hold for t in trades]
    quick_struct = [t for t in trades if t.exit_reason == "STRUCT" and t.hold <= 2]
    reentry_same_dir = 0
    reentry_gap = []
    for a, b in zip(trades, trades[1:]):
        gap = b.entry_i - a.exit_i
        reentry_gap.append(gap)
        if gap <= 2 and b.direction == a.direction and a.exit_reason == "STRUCT":
            reentry_same_dir += 1
    return {
        "median_hold": st.median(holds), "p25": q(holds, .25), "p75": q(holds, .75),
        "p90": q(holds, .90), "max": max(holds),
        "hold_le1": sum(1 for h in holds if h <= 1),
        "hold_le2": sum(1 for h in holds if h <= 2),
        "hold_le3": sum(1 for h in holds if h <= 3),
        "quick_struct_n": len(quick_struct),
        "quick_struct_r": sum(t.r for t in quick_struct),
        "reentry_same_dir": reentry_same_dir,
        "median_gap": st.median(reentry_gap) if reentry_gap else float("nan"),
    }


def load_10m(symbol: str, rth_only: bool):
    b5 = data.load(symbol, "60d", "5m")
    if rth_only:
        b5 = drop_close_stub(b5)
    return to_10m(b5)


def build_dataset(name: str, symbol: str, rth_only: bool, kind: str):
    if kind == "10m":
        bars, subs = load_10m(symbol, rth_only)
    else:
        bars, subs = data.load(symbol, "730d", "1h"), None
        if rth_only:
            bars = [b for b in bars if not (b.dt.hour == 16 and b.dt.minute == 0)]
    book = LevelBook(data.load(symbol, "20y", "1d"))
    return name, bars, subs, book


def report(name: str, bars, subs, book, out: list[str], path_resolve=False):
    trades, diag = run_v14(bars, book, subs, path_resolve=path_resolve)
    n_bars = diag["setup_bars"]
    rs = [t.r for t in trades]
    k = sum(1 for r in rs if r > 1e-12)
    per_1000 = 1000 * len(trades) / n_bars if n_bars else 0
    cm = churn_metrics(trades)

    out.append(f"\n### {name}")
    out.append(f"样本：{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，"
               f"可用 setup K {n_bars} 根")
    out.append(f"交易 {len(trades)} 笔 = **每 1000 根 setup K {per_1000:.1f} 笔** "
               f"（约每 {n_bars/max(len(trades),1):.1f} 根一笔）")
    out.append(f"胜率 {100*k/max(len(trades),1):.1f}% "
               f"{stats.fmt_rate(k, len(trades))}｜总R {sum(rs):+.1f}｜"
               f"均R {sum(rs)/max(len(trades),1):+.3f}")
    out.append(f"持仓根数：中位 {cm['median_hold']:.0f}，p25 {cm['p25']:.0f}，"
               f"p75 {cm['p75']:.0f}，p90 {cm['p90']:.0f}，max {cm['max']}")
    out.append("")
    out.append("| 切片 | n | 胜率 | 总R | 均R | 中位持仓 |")
    out.append("|---|---|---|---|---|---|")
    groups = [("全部", trades),
              ("RTH", [t for t in trades if t.session == "RTH"]),
              ("夜盘", [t for t in trades if t.session != "RTH"]),
              ("Recovery", [t for t in trades if t.setup == "Recovery"]),
              ("Vomy", [t for t in trades if t.setup == "Vomy"]),
              ("多", [t for t in trades if t.direction > 0]),
              ("空", [t for t in trades if t.direction < 0])]
    for lbl, g in groups:
        if not g:
            out.append(f"| {lbl} | 0 | – | – | – | – |")
            continue
        kk = sum(1 for t in g if t.r > 1e-12)
        lo, hi = stats.wilson(kk, len(g))
        out.append(f"| {lbl} | {len(g)} | {100*kk/len(g):.0f}% "
                   f"[{100*lo:.0f},{100*hi:.0f}] | {sum(t.r for t in g):+.1f} | "
                   f"{sum(t.r for t in g)/len(g):+.3f} | "
                   f"{st.median([t.hold for t in g]):.0f} |")
    return trades, diag, cm


EXIT_ORDER = ["PROT·T0", "PROT·T1", "PROT·T2", "STRUCT·T0", "STRUCT·T1", "STRUCT·T2"]
EXIT_CN = {
    "PROT·T0": "触保护位（未到 T1）",
    "PROT·T1": "T1 后触保护位",
    "PROT·T2": "T1+T2 后触保护位",
    "STRUCT·T0": "收盘穿 13 离场（未到 T1）",
    "STRUCT·T1": "T1 后收盘穿 13",
    "STRUCT·T2": "T1+T2 后收盘穿 13（runner）",
}


def exit_attribution(trades: list[Trade], out: list[str]) -> None:
    tot = sum(t.r for t in trades)
    out.append("| 离场原因 | 笔数 | 占比 | 贡献 R | 占总 R | 均 R | 中位持仓 |")
    out.append("|---|---|---|---|---|---|---|")
    for tag in EXIT_ORDER:
        g = [t for t in trades if t.tag == tag]
        if not g:
            out.append(f"| {EXIT_CN[tag]} | 0 | – | – | – | – | – |")
            continue
        r = sum(t.r for t in g)
        out.append(f"| {EXIT_CN[tag]} | {len(g)} | {100*len(g)/len(trades):.1f}% | "
                   f"{r:+.1f} | {100*r/tot if tot else 0:.0f}% | {r/len(g):+.3f} | "
                   f"{st.median([t.hold for t in g]):.0f} |")
    out.append(f"| **合计** | **{len(trades)}** | 100% | **{tot:+.1f}** | 100% | "
               f"{tot/len(trades):+.3f} | {st.median([t.hold for t in trades]):.0f} |")


def quick_exit_table(trades: list[Trade], out: list[str]) -> None:
    out.append("| 入场后第几根离场 | 笔数 | 占比 | 其中「收盘穿回 13」 | 该类贡献 R |")
    out.append("|---|---|---|---|---|")
    for h in (1, 2, 3):
        g = [t for t in trades if t.hold == h]
        s = [t for t in g if t.exit_reason == "STRUCT"]
        out.append(f"| 第 {h} 根 | {len(g)} | {100*len(g)/len(trades):.1f}% | "
                   f"{len(s)} | {sum(t.r for t in s):+.1f} |")
    g12 = [t for t in trades if t.hold <= 2]
    s12 = [t for t in g12 if t.exit_reason == "STRUCT"]
    p12 = [t for t in g12 if t.exit_reason == "PROT"]
    out.append(f"| **1–2 根合计** | **{len(g12)}** | **{100*len(g12)/len(trades):.1f}%** | "
               f"**{len(s12)}（{100*len(s12)/len(trades):.1f}% of all）** | "
               f"**{sum(t.r for t in s12):+.1f}** |")
    out.append("")
    out.append(f"- 1–2 根内离场的 {len(g12)} 笔里，{len(s12)} 笔是**收盘穿回 13**"
               f"（贡献 {sum(t.r for t in s12):+.1f}R），{len(p12)} 笔是触保护位"
               f"（贡献 {sum(t.r for t in p12):+.1f}R）。")


def null_vs_observed(trades: list[Trade]) -> str:
    """Geometric null for 'T1 before stop' = S/(S+T), per trade, not 50%."""
    exp = sum(t.risk / (t.risk + abs(t.t1 - t.entry)) for t in trades)
    obs = sum(1 for t in trades if t.t1done)
    lo, hi = stats.wilson(obs, len(trades))
    return (f"规则内 T1 触及率：{obs}/{len(trades)} = {100*obs/len(trades):.1f}% "
            f"[{100*lo:.1f},{100*hi:.1f}]。**不要**直接拿它跟几何零假设 "
            f"{100*exp/len(trades):.1f}% 比——13 线离场在到达任一栏之前就砍断了大量交易，"
            f"两者不是同一个实验。干净的比较见下面的两栏赛跑。")


def decompose(trades: list[Trade], n_bars: int, out: list[str]) -> None:
    rec = [t for t in trades if t.setup == "Recovery"]
    vom = [t for t in trades if t.setup == "Vomy"]
    rows = [
        ("笔数", lambda g: f"{len(g)}"),
        ("每 1000 根 K 的笔数", lambda g: f"{1000*len(g)/n_bars:.1f}"),
        ("胜率", lambda g: f"{100*sum(1 for t in g if t.r>1e-12)/len(g):.1f}% "
                           f"[{100*stats.wilson(sum(1 for t in g if t.r>1e-12),len(g))[0]:.0f},"
                           f"{100*stats.wilson(sum(1 for t in g if t.r>1e-12),len(g))[1]:.0f}]"),
        ("总 R", lambda g: f"{sum(t.r for t in g):+.1f}"),
        ("均 R", lambda g: f"{sum(t.r for t in g)/len(g):+.3f}"),
        ("均赢 R", lambda g: f"{st.mean([t.r for t in g if t.r>1e-12]):+.2f}"),
        ("均亏 R", lambda g: f"{st.mean([t.r for t in g if t.r<-1e-12]):+.2f}"),
        ("赔率（均赢/|均亏|）", lambda g: f"{st.mean([t.r for t in g if t.r>1e-12])/abs(st.mean([t.r for t in g if t.r<-1e-12])):.2f}"),
        ("打平所需胜率", lambda g: f"{100*stats.expectancy([t.r for t in g])['breakeven_wr']:.1f}%"),
        ("中位持仓（根）", lambda g: f"{st.median([t.hold for t in g]):.0f}"),
        ("p75 持仓（根）", lambda g: f"{q([t.hold for t in g], .75):.0f}"),
        ("1–2 根内离场占比", lambda g: f"{100*sum(1 for t in g if t.hold<=2)/len(g):.0f}%"),
        ("T1 触及率", lambda g: f"{100*sum(1 for t in g if t.t1done)/len(g):.0f}%"),
        ("T2 触及率", lambda g: f"{100*sum(1 for t in g if t.t2done)/len(g):.0f}%"),
        ("风险距离 中位（ATR 归一）", lambda g: f"{st.median([t.risk_atr for t in g]):.3f} ATR"),
        ("T1 距离 中位（R）", lambda g: f"{st.median([t.t1_dist_r for t in g]):.2f} R"),
        ("几何零假设 T1 率", lambda g: f"{100*st.mean([t.risk/(t.risk+abs(t.t1-t.entry)) for t in g]):.0f}%"),
        ("保护位离场占比", lambda g: f"{100*sum(1 for t in g if t.exit_reason=='PROT')/len(g):.0f}%"),
        ("保护位离场贡献 R", lambda g: f"{sum(t.r for t in g if t.exit_reason=='PROT'):+.1f}"),
        ("结构离场贡献 R", lambda g: f"{sum(t.r for t in g if t.exit_reason=='STRUCT'):+.1f}"),
        ("入场前状态停留 中位（根）", lambda g: f"{st.median([t.pullback_bars for t in g]):.0f}"),
    ]
    out.append("| 指标 | Recovery | Vomy | 差异 |")
    out.append("|---|---|---|---|")
    for label, fn in rows:
        a = fn(rec) if rec else "–"
        b = fn(vom) if vom else "–"
        out.append(f"| {label} | {a} | {b} |  |")


def money_normalised(trades: list[Trade], out: list[str]) -> None:
    """R is not a currency.  Two setups with different stop widths report the
    same loss in different units, so also express P&L in ATR of the underlying
    (per 1 unit of notional), which IS comparable across setups."""
    out.append("| 组 | n | 总 R | 中位风险(ATR) | 总盈亏(ATR 单位) | 每笔盈亏(ATR) |")
    out.append("|---|---|---|---|---|---|")
    for lbl, g in (("Recovery", [t for t in trades if t.setup == "Recovery"]),
                   ("Vomy", [t for t in trades if t.setup == "Vomy"]),
                   ("全部", trades)):
        if not g:
            continue
        pnl_atr = sum(t.r * t.risk_atr for t in g)
        out.append(f"| {lbl} | {len(g)} | {sum(t.r for t in g):+.1f} | "
                   f"{st.median([t.risk_atr for t in g]):.3f} | {pnl_atr:+.2f} | "
                   f"{pnl_atr/len(g):+.4f} |")


def counterfactual(trades: list[Trade], out: list[str]) -> None:
    """Which single term makes Recovery ~10x worse than Vomy?  Swap one term
    at a time and re-price Recovery's book."""
    rec = [t for t in trades if t.setup == "Recovery"]
    vom = [t for t in trades if t.setup == "Vomy"]
    if not rec or not vom:
        return

    def parts(g):
        w = [t.r for t in g if t.r > 1e-12]
        l = [t.r for t in g if t.r < -1e-12]
        return (len(g), len(w) / len(g), st.mean(w) if w else 0.0,
                st.mean(l) if l else 0.0)

    nR, wR, awR, alR = parts(rec)
    nV, wV, awV, alV = parts(vom)
    base = nR * (wR * awR + (1 - wR) * alR)
    swaps = [
        ("原样", nR, wR, awR, alR),
        ("换成 Vomy 的胜率", nR, wV, awR, alR),
        ("换成 Vomy 的均赢", nR, wR, awV, alR),
        ("**换成 Vomy 的均亏**", nR, wR, awR, alV),
        ("换成 Vomy 的笔数", nV, wR, awR, alR),
    ]
    out.append("| Recovery 账本，替换其中一项 | 重算总 R | 相对原样的改善 |")
    out.append("|---|---|---|")
    for lbl, n, w, aw, al in swaps:
        tot = n * (w * aw + (1 - w) * al)
        out.append(f"| {lbl} | {tot:+.1f} | {tot - base:+.1f} |")
    out.append(f"| Vomy 实际 | {sum(t.r for t in vom):+.1f} | |")


def barrier_race(trades: list[Trade], bars: list[Bar],
                 subs: list[list[Bar]] | None, out: list[str],
                 cap: int = 300) -> None:
    """Delete the 13-EMA exit and let each entry run to stop-or-T1.

    This is the only way to state the geometric null honestly: the observed
    "T1 hit" rate inside the live rules is truncated by the structural exit,
    so comparing it to S/(S+T) compares two different experiments.  Here the
    race is actually run.  Path order inside a bar is resolved on the 5m
    sub-bars where they exist (a 10m bar's range routinely exceeds the whole
    stop distance, so bar-level OHLC cannot arbitrate).
    """
    t1_first = prot_first = unresolved = 0
    exp = 0.0
    for t in trades:
        p_null = t.risk / (t.risk + abs(t.t1 - t.entry))
        d, done = t.direction, False
        for i in range(t.entry_i + 1, min(t.entry_i + 1 + cap, len(bars))):
            seq = subs[i] if subs is not None else [bars[i]]
            for sb in seq:
                p = (sb.low <= t.prot) if d > 0 else (sb.high >= t.prot)
                g = (sb.high >= t.t1) if d > 0 else (sb.low <= t.t1)
                if p and g:
                    unresolved += 1
                    done = True
                    break
                if g:
                    t1_first += 1
                    exp += p_null
                    done = True
                    break
                if p:
                    prot_first += 1
                    exp += p_null
                    done = True
                    break
            if done:
                break
        if not done:
            unresolved += 1
    n = t1_first + prot_first
    lo, hi = stats.wilson(t1_first, n) if n else (0, 1)
    mu = exp / n if n else 0.0        # null restricted to the resolved trades
    sd = (mu * (1 - mu) / n) ** 0.5 if n else 1.0
    z = (t1_first / n - mu) / sd if n and sd else 0.0
    out.append(f"- 去掉 13 线离场、只跑「保护位 vs T1」的两栏赛跑（5m 子 K 裁决顺序）："
               f"T1 先到 {t1_first}/{n} = **{100*t1_first/max(n,1):.1f}%** "
               f"[{100*lo:.1f},{100*hi:.1f}]")
    out.append(f"- 同一批（已裁决的）入场的几何零假设 S/(S+T) = **{100*mu:.1f}%**"
               f"；{unresolved} 笔在 {cap} 根内或 5m 分辨率下无法裁决，已剔除")
    out.append(f"- 相对几何零假设的超额：**{100*(t1_first/max(n,1)-mu):+.1f} 个百分点**"
               f"（z={z:+.2f}）——正=入场时点带方向信息，负=入场是负选择")


def stability(trades: list[Trade], out: list[str]) -> None:
    if len(trades) < 20:
        return
    mid = len(trades) // 2
    for lbl, g in (("前半段", trades[:mid]), ("后半段", trades[mid:])):
        k = sum(1 for t in g if t.r > 1e-12)
        out.append(f"- {lbl}（{g[0].entry_dt:%m-%d} → {g[-1].entry_dt:%m-%d}）："
                   f"n={len(g)}，胜率 {100*k/len(g):.0f}%，总R {sum(t.r for t in g):+.1f}，"
                   f"Recovery {sum(t.r for t in g if t.setup=='Recovery'):+.1f}R / "
                   f"Vomy {sum(t.r for t in g if t.setup=='Vomy'):+.1f}R")


def main() -> None:
    out: list[str] = []
    sets = [
        build_dataset("A · ^GSPC 10m（RTH-only，60 天）", "^GSPC", True, "10m"),
        build_dataset("B · ES=F 10m（近 23h，59 天）——最接近 SPX500 CFD 的连续标的",
                      "ES=F", False, "10m"),
        build_dataset("C · ^GSPC 1h（730 天，低分辨率对照）", "^GSPC", True, "1h"),
        build_dataset("D · ES=F 1h（730 天，23h，低分辨率对照）", "ES=F", False, "1h"),
    ]
    allres = {}
    for name, bars, subs, book in sets:
        tr, diag, cm = report(name, bars, subs, book, out)
        allres[name] = (tr, diag, cm, bars, subs, book)

    for name, (tr, diag, cm, bars, subs, book) in allres.items():
        out.append(f"\n\n## 归因 — {name}")
        occ = sum(t.hold for t in tr)
        out.append(f"在场占比：{100*occ/diag['setup_bars']:.1f}% 的 setup K 处于持仓中"
                   f"（{occ}/{diag['setup_bars']} 根）")
        out.append(f"状态机启动次数：Recovery多 {diag['rec_arm_L']} / Recovery空 "
                   f"{diag['rec_arm_S']} / Vomy空 {diag['vom_arm_S']} / invVomy多 "
                   f"{diag['vom_arm_L']}；因已有持仓被吞掉的触发 "
                   f"{diag['rec_trigger_blocked_inpos']+diag['vom_trigger_blocked_inpos']} 次；"
                   f"因风险<{MIN_RISK_PTS}点被跳过 {diag['blocked_minrisk']} 次")
        out.append("")
        out.append("**离场原因归因**\n")
        exit_attribution(tr, out)
        out.append("")
        out.append("**入场后 1–3 根内离场**\n")
        quick_exit_table(tr, out)
        out.append("")
        out.append(f"同向再入场（结构离场后 ≤2 根内又开同方向）：{cm['reentry_same_dir']} 次"
                   f"（{100*cm['reentry_same_dir']/len(tr):.0f}% of 笔数）；"
                   f"两笔之间的间隔中位 {cm['median_gap']:.0f} 根")
        out.append(f"**同根 K 自我续杯**：{diag['struct_exits']} 笔结构离场里，有 "
                   f"{diag['same_bar_rearm']} 笔在**同一根 K 上**就把同方向的 Recovery "
                   f"回踩状态重新点亮（{100*diag['same_bar_rearm']/max(diag['struct_exits'],1):.0f}%），"
                   f"下一根收回 13 即再次开仓")
        out.append(f"- {null_vs_observed(tr)}")
        out.append("")
        out.append("**几何零假设：把 13 线离场拿掉后的两栏赛跑**\n")
        barrier_race(tr, bars, subs, out)
        for lbl, g in (("Recovery", [t for t in tr if t.setup == "Recovery"]),
                       ("Vomy", [t for t in tr if t.setup == "Vomy"])):
            sub = []
            barrier_race(g, bars, subs, sub)
            out.append(f"  - {lbl}：" + sub[0].split("）：", 1)[1] + "；零假设 " +
                       sub[1].split("= ", 1)[1].split("；")[0] + "；超额 " +
                       sub[2].split("：", 1)[1])
        out.append("")
        out.append("**成本冲击（每笔用自己的风险距离做分母）**\n")
        out.extend(cost_table(tr))
        out.append("")
        out.append("**Recovery vs Vomy 逐项拆解**\n")
        decompose(tr, diag["setup_bars"], out)
        out.append("")
        out.append("**同一笔钱换成 ATR 单位（R 不是货币）**\n")
        money_normalised(tr, out)
        out.append("")
        out.append("**反事实拆解：把 Recovery 的某一项换成 Vomy 的**\n")
        counterfactual(tr, out)
        out.append("")
        out.append("**分期稳定性**\n")
        stability(tr, out)

    # path resolution: only legitimate on datasets with 5m sub-bars
    out.append("\n\n## 路径判定（用 5 分钟子 K 裁决「同一根 K 既触保护位又触目标」）")
    for name, symbol, rth in (("A · ^GSPC 10m", "^GSPC", True),
                              ("B · ES=F 10m", "ES=F", False)):
        bars, subs = load_10m(symbol, rth)
        book = LevelBook(data.load(symbol, "20y", "1d"))
        t_cons, _ = run_v14(bars, book, subs, path_resolve=False)
        t_path, _ = run_v14(bars, book, subs, path_resolve=True)
        out.append(f"- {name}：保守裁决 {len(t_cons)} 笔 / 总R "
                   f"{sum(t.r for t in t_cons):+.1f}；5m 路径裁决 {len(t_path)} 笔 / 总R "
                   f"{sum(t.r for t in t_path):+.1f}"
                   f"（差 {sum(t.r for t in t_path)-sum(t.r for t in t_cons):+.1f}R）")

    txt = "\n".join(out)
    print(txt)
    Path(__file__).with_name("v14_repro_raw.txt").write_text(txt)
    return allres


if __name__ == "__main__":
    main()
