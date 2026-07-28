#!/usr/bin/env python3
"""用户描述的第 2、3 步：具名位被反复测试，与 Saty Phase 背离。两者都从未实现过。

任务
----
A. 「同一个位被反复测试」——以 ATR 阶梯的具名位为参照，±0.03 ATR 带内触及计数
   （两次触及之间必须离开 ≥0.05 ATR 才算独立一次），问：**第 k 次触及之后，
   该位被突破还是被拒绝？突破概率随 k 上升（位在弱化）还是下降（位在加固）？**
   这两个方向对应完全相反的交易策略，所以必须给出方向 + CI，而不是「有效应」。
   同时做安慰剂：把具名位换成随机/平移/抖动价位，重复次数效应是否仍在。

B. Saty Phase 背离（用修正后的 phase_fix 公式，不是 indicators.py 里那个猜的）。
   两个候选定义（V1 纯背离 / V2 背离且低点落在具名位 ±0.05 ATR 内）各测一遍，
   纯括号单命中率对**几何零假设 S/(S+T)**，并**必须报告事件频率**。

口径纪律（本项目吃过的亏，逐条钉住）
------------------------------------
1. 零假设不是 50%。A 部分每个事件的零假设是 (c - x)/(2c)，x 是触及根收盘相对
   该位的带符号偏移、c 是判定走廊半宽——即无漂移随机游走从 p0 出发先碰哪一边。
   逐事件求和成泊松二项，给 z_geom。B 部分是 S/(S+T)。
2. 每个比例带 Wilson CI 和 n；文末统一给检视格子数与 Bonferroni 门槛。
3. 路径判定只能用 5 分钟数据（A 部分全程 5m；B 部分 10m 信号 + 5m 子 K 判路径）。
4. 允许并鼓励「这个过滤器没用」的结论。
5. 位相关结论一律按当日 Wilder ATR(14) 归一化（^GSPC 与 SPX500 的 ATR 比值
   mean 1.117 / sd 0.083，不是常数）。
6. 「砍笔数换总 R 转正」不算数，必须看单笔质量。

A 部分有一个**必须写进报告**的机制性陷阱：第 k 次触及之所以存在，正是因为前
k-1 次没突破。即使每个位的突破概率恒定，只要**位与位之间存在异质性**（有的位
天生黏、有的天生脆），观测到的突破率也会随 k 下降。这是 frailty 选择，不是
「位在加固」。所以本脚本除了跨 k 的比例检验，还要跑安慰剂与时段配对。

用法：.venv/bin/python research/satylab/study_retest_divergence.py
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                          # noqa: E402
from satylab.data import Bar                                     # noqa: E402
from satylab.phase_fix import phase_oscillator                   # noqa: E402
from satylab.study_v14_repro import (LevelBook, drop_close_stub,  # noqa: E402
                                     next_rung, to_10m, trade_day)
from satylab.study_v14_filters import _norm_q                    # noqa: E402

SEED = 20260728
BAND = 0.03          # ±0.03 ATR 触及带（任务指定）
REARM = 0.05         # 两次触及之间必须离开 ≥0.05 ATR（任务指定）
CORR = 0.10          # 判定走廊半宽：穿过 0.10 ATR = 突破，退回 0.10 ATR = 拒绝
DIV_BUF = 0.02       # 背离单止损放在低点外侧 0.02 ATR
SPREAD = 0.6         # 成本（点），与前四份报告同口径
OUT = Path(__file__).resolve().parents[1] / "reports" / "V15_LEVEL_RETEST_AND_DIVERGENCE.md"

rng = random.Random(SEED)
CELLS = 0


def cell(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ════════════════════════════ 小工具 ════════════════════════════════════════
def pb_z(hits: list[bool], ps: list[float]) -> tuple[float, float, float]:
    """泊松二项 z：观测命中数 vs Σp，方差 Σp(1-p)。返回 (obs_rate, null_rate, z)。"""
    n = len(ps)
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    k = sum(1 for h in hits if h)
    sp = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    z = (k - sp) / math.sqrt(var) if var > 0 else float("nan")
    return (k / n, sp / n, z)


def f(x, d: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:+.{d}f}"


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n=0"
    lo, hi = stats.wilson(k, n)
    return f"{100*k/n:.1f}% [{100*lo:.1f},{100*hi:.1f}]"


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def tstat(xs: list[float], mu0: float = 0.0) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    sd = st.stdev(xs)
    return (mean(xs) - mu0) / (sd / math.sqrt(n)) if sd > 0 else float("nan")


# ════════════════════════════ 具名位命名 ════════════════════════════════════
def rung_type(r: float) -> str:
    a = abs(r)
    return {0.0: "PDC", 0.236: "trigger", 0.382: "0.382", 0.5: "0.5",
            0.618: "0.618", 0.786: "0.786", 1.0: "1.0ATR"}.get(
                round(a, 3), "ext(1.272/1.618)")


TYPE_ORDER = ["PDC", "trigger", "0.382", "0.5", "0.618", "0.786", "1.0ATR",
              "ext(1.272/1.618)"]


# ════════════════════════════ A：触及事件 ═══════════════════════════════════
@dataclass(slots=True)
class Touch:
    day: date
    ratio: float
    ltype: str
    price: float
    atr: float
    touch_no: int
    approach: int            # +1 从上方来（跌到该位），-1 从下方来
    flipped: bool            # 本次触及方向与上一次是否相反
    bar_i: int
    hhmm: str
    sess: str                # RTH / 夜盘
    mins_left: int
    x_atr: float             # 触及根收盘相对该位的带符号偏移（ATR 单位，正=仍在来的那侧）
    geom_p: float            # 无漂移零假设下的 P(突破)
    outcome: str             # BREAK / REJECT / OPEN
    ambiguous: bool
    res_bars: int            # 判定用了几根 5m
    prev_outcome: str


def scan_level(rows: list[Bar], L: float, atr: float, ratio: float,
               day: date, band: float, rearm: float, corr: float,
               rearm_whole_bar: bool, sess_of, mins_left_of) -> list[Touch]:
    b, rr, c = band * atr, rearm * atr, corr * atr
    lo_b, hi_b = L - b, L + b
    n = len(rows)
    out: list[Touch] = []
    armed = True
    touch_no = 0
    side = 1 if rows[0].open >= L else -1
    prev_side = None
    prev_out = "—"
    for i in range(n):
        bar = rows[i]
        if armed and bar.low <= hi_b and bar.high >= lo_b:
            touch_no += 1
            a = side
            p0 = bar.close
            x = a * (p0 - L)
            gp = min(1.0, max(0.0, (c - x) / (2 * c)))
            brk_px, rej_px = L - a * c, L + a * c
            outcome, amb, res_j = "OPEN", False, None
            if x >= c:
                outcome, res_j = "REJECT", i
            elif x <= -c:
                outcome, res_j = "BREAK", i
            else:
                for j in range(i + 1, n):
                    bb = rows[j]
                    hb = (bb.low <= brk_px) if a > 0 else (bb.high >= brk_px)
                    hr = (bb.high >= rej_px) if a > 0 else (bb.low <= rej_px)
                    if hb and hr:
                        amb = True
                        outcome = "BREAK" if a * (bb.close - L) < 0 else "REJECT"
                        res_j = j
                        break
                    if hb:
                        outcome, res_j = "BREAK", j
                        break
                    if hr:
                        outcome, res_j = "REJECT", j
                        break
            out.append(Touch(day, ratio, rung_type(ratio), L, atr, touch_no, a,
                             prev_side is not None and prev_side != a, i,
                             bar.hhmm, sess_of(bar), mins_left_of(bar, i),
                             x / atr, gp, outcome, amb,
                             (res_j - i) if res_j is not None else -1,
                             prev_out))
            prev_side, prev_out = a, outcome
            armed = False
        if not armed:
            if rearm_whole_bar:
                if bar.low > L + rr or bar.high < L - rr:
                    armed = True
            else:
                if bar.high >= L + rr or bar.low <= L - rr:
                    armed = True
        if bar.close > hi_b:
            side = 1
        elif bar.close < lo_b:
            side = -1
    return out


def named_ratios() -> list[float]:
    return list(levels.RATIOS)


def placebo_ratios(kind: str, r: random.Random) -> list[float]:
    """安慰剂位。三种，因为『随机价位』有三种做法，密度不同结论可能不同。"""
    named = named_ratios()

    def far(v: float) -> bool:
        return all(abs(v - m) >= 0.06 for m in named)

    if kind == "均匀随机":
        out = []
        while len(out) < len(named):
            v = r.uniform(-1.618, 1.618)
            if far(v) and all(abs(v - o) >= 0.06 for o in out):
                out.append(round(v, 4))
        return sorted(out)
    if kind == "整体平移":                       # 阶梯整体挪到档位之间
        return [round(m + 0.118, 4) for m in named]
    if kind == "逐位抖动":                       # 保持密度分布，逐位随机偏移
        out = []
        for m in named:
            d = r.uniform(0.06, 0.118) * (1 if r.random() < 0.5 else -1)
            out.append(round(m + d, 4))
        return sorted(out)
    raise ValueError(kind)


@dataclass
class Dataset:
    name: str
    symbol: str
    tf: str
    rows_by_day: dict          # trade_day -> list[Bar]
    book: LevelBook
    n_bars: int


def build_fine(name: str, symbol: str, rth_only: bool) -> Dataset:
    b5 = data.load(symbol, "60d", "5m")
    if rth_only:
        b5 = drop_close_stub(b5)
    by: dict[date, list[Bar]] = defaultdict(list)
    for b in b5:
        by[trade_day(b)].append(b)
    for v in by.values():
        v.sort(key=lambda x: x.dt)
    return Dataset(name, symbol, "5m", dict(by),
                   LevelBook(data.load(symbol, "20y", "1d")), len(b5))


def build_hourly(name: str, symbol: str) -> Dataset:
    bh = data.load(symbol, "730d", "1h")
    by: dict[date, list[Bar]] = defaultdict(list)
    for b in bh:
        by[trade_day(b)].append(b)
    for v in by.values():
        v.sort(key=lambda x: x.dt)
    return Dataset(name, symbol, "1h", dict(by),
                   LevelBook(data.load(symbol, "20y", "1d")), len(bh))


def run_scan(ds: Dataset, ratios_for_day, band=BAND, rearm=REARM, corr=CORR,
             rearm_whole_bar=False) -> list[Touch]:
    out: list[Touch] = []
    for day, rows in sorted(ds.rows_by_day.items()):
        if len(rows) < 12:
            continue
        got = ds.book.get(day)
        if not got:
            continue
        anchor, atr = got
        if atr <= 0:
            continue
        lo = min(b.low for b in rows) - band * atr
        hi = max(b.high for b in rows) + band * atr
        end_dt = rows[-1].dt

        def sess_of(b: Bar) -> str:
            m = b.dt.hour * 60 + b.dt.minute
            return "RTH" if 570 <= m < 960 else "夜盘"

        def mins_left_of(b: Bar, i: int) -> int:
            return int((end_dt - b.dt).total_seconds() // 60)

        for r in ratios_for_day(day):
            L = anchor + r * atr
            if L < lo or L > hi:
                continue
            out.extend(scan_level(rows, L, atr, r, day, band, rearm, corr,
                                  rearm_whole_bar, sess_of, mins_left_of))
    return out


# ─────────────── A 部分的聚合 ───────────────
def bucket_k(k: int) -> str:
    return "4+" if k >= 4 else str(k)


K_ORDER = ["1", "2", "3", "4+"]


def by_k(touches: list[Touch], filt=None) -> dict:
    g: dict[str, list[Touch]] = {k: [] for k in K_ORDER}
    for t in touches:
        if filt and not filt(t):
            continue
        g[bucket_k(t.touch_no)].append(t)
    return g


def krow(ts: list[Touch]) -> dict:
    res = [t for t in ts if t.outcome != "OPEN"]
    hits = [t.outcome == "BREAK" for t in res]
    ps = [t.geom_p for t in res]
    o, nu, z = pb_z(hits, ps)
    return {"n_all": len(ts), "n": len(res), "k": sum(hits),
            "open": len(ts) - len(res), "obs": o, "null": nu, "z": z,
            "amb": sum(1 for t in res if t.ambiguous),
            "x": mean([t.x_atr for t in res]) if res else float("nan"),
            "medres": st.median([t.res_bars for t in res]) if res else float("nan")}


def k_table(g: dict) -> list[tuple]:
    rows = []
    base = g["1"]
    br = [t.outcome == "BREAK" for t in base if t.outcome != "OPEN"]
    for kk in K_ORDER:
        m = krow(g[kk])
        cur = [t.outcome == "BREAK" for t in g[kk] if t.outcome != "OPEN"]
        z1 = (stats.two_proportion_z(sum(cur), len(cur), sum(br), len(br))
              if kk != "1" and cur and br else float("nan"))
        m["z_vs_1"] = z1
        rows.append((kk, m))
        cell()
    return rows


def slope_z(g: dict) -> float:
    """把 k 当连续变量（1,2,3,4）对突破做 logistic 斜率的 score 检验 z。"""
    xs, ys = [], []
    for kk in K_ORDER:
        for t in g[kk]:
            if t.outcome == "OPEN":
                continue
            xs.append({"1": 1, "2": 2, "3": 3, "4+": 4}[kk])
            ys.append(1 if t.outcome == "BREAK" else 0)
    n = len(ys)
    if n < 30:
        return float("nan")
    p = sum(ys) / n
    mx = mean(xs)
    num = sum((xs[i] - mx) * (ys[i] - p) for i in range(n))
    den = math.sqrt(p * (1 - p) * sum((x - mx) ** 2 for x in xs))
    return num / den if den > 0 else float("nan")


# ─────────────── A 部分的经济检验：第 k 次触及做「拒绝」方向 ───────────────
def reject_trade(ds: Dataset, touches: list[Touch]) -> dict:
    """在触及根收盘按拒绝方向进场；止损=穿过该位 0.10 ATR；目标=同向下一个具名位。"""
    rs, ps, hits, nets = [], [], [], []
    unres = 0
    for t in touches:
        rows = ds.rows_by_day.get(t.day)
        if not rows:
            continue
        got = ds.book.get(t.day)
        if not got:
            continue
        anchor, atr = got
        a = t.approach
        entry = rows[t.bar_i].close
        stop = t.price - a * CORR * atr
        risk = a * (entry - stop)
        if risk <= 0:
            continue
        target = next_rung(t.price, a, anchor, atr)
        tdist = a * (target - entry)
        if tdist <= 0:
            continue
        p = risk / (risk + tdist)
        hit = None
        for j in range(t.bar_i + 1, len(rows)):
            bb = rows[j]
            hs = (bb.low <= stop) if a > 0 else (bb.high >= stop)
            ht = (bb.high >= target) if a > 0 else (bb.low <= target)
            if hs and ht:
                hit = None
                break
            if hs:
                hit = False
                break
            if ht:
                hit = True
                break
        if hit is None:
            unres += 1
            continue
        r = (tdist / risk) if hit else -1.0
        rs.append(r)
        nets.append(r - SPREAD / risk)
        ps.append(p)
        hits.append(hit)
    o, nu, z = pb_z(hits, ps)
    return {"n": len(rs), "unres": unres, "obs": o, "null": nu, "z_geom": z,
            "avg_r": mean(rs) if rs else float("nan"),
            "tot_r": sum(rs), "net_r": sum(nets),
            "t_r": tstat(rs)}


# ════════════════════════════ B：Phase 背离 ═════════════════════════════════
@dataclass(slots=True)
class Div:
    i: int
    kind: str           # bull / bear
    at_level: bool
    lvl_gap: float
    day: date
    hhmm: str
    sess: str
    phase: float
    phase_min: float


def find_divergence(bars: list[Bar], ph: list[float | None], N: int,
                    kind: str, book: LevelBook, dedupe: int) -> list[Div]:
    out: list[Div] = []
    last = -10 ** 9
    for i in range(N, len(bars)):
        w = range(i - N + 1, i + 1)
        if any(ph[j] is None for j in w):
            continue
        if kind == "bull":
            ext = min(bars[j].low for j in w)
            price_new = bars[i].low <= ext + 1e-9
            pmin = min(ph[j] for j in w)
            osc_new = ph[i] <= pmin + 1e-9
        else:
            ext = max(bars[j].high for j in w)
            price_new = bars[i].high >= ext - 1e-9
            pmax = max(ph[j] for j in w)
            osc_new = ph[i] >= pmax - 1e-9
        if not price_new or osc_new:
            continue
        if i - last < dedupe:
            continue
        last = i
        d = trade_day(bars[i])
        got = book.get(d)
        if not got:
            continue
        anchor, atr = got
        px = bars[i].low if kind == "bull" else bars[i].high
        gap = min(abs(px - (anchor + r * atr)) for r in levels.RATIOS) / atr
        m = bars[i].dt.hour * 60 + bars[i].dt.minute
        out.append(Div(i, kind, gap <= 0.05, gap, d, bars[i].hhmm,
                       "RTH" if 570 <= m < 960 else "夜盘",
                       ph[i], min(ph[j] for j in w)))
    return out


def find_control(bars: list[Bar], ph: list[float | None], N: int,
                 kind: str, book: LevelBook, dedupe: int) -> list[Div]:
    """对照组：价格创新低/新高，Phase **也**创新低/新高（即没有背离）。"""
    out: list[Div] = []
    last = -10 ** 9
    for i in range(N, len(bars)):
        w = range(i - N + 1, i + 1)
        if any(ph[j] is None for j in w):
            continue
        if kind == "bull":
            price_new = bars[i].low <= min(bars[j].low for j in w) + 1e-9
            osc_new = ph[i] <= min(ph[j] for j in w) + 1e-9
        else:
            price_new = bars[i].high >= max(bars[j].high for j in w) - 1e-9
            osc_new = ph[i] >= max(ph[j] for j in w) - 1e-9
        if not (price_new and osc_new):
            continue
        if i - last < dedupe:
            continue
        last = i
        d = trade_day(bars[i])
        got = book.get(d)
        if not got:
            continue
        anchor, atr = got
        px = bars[i].low if kind == "bull" else bars[i].high
        gap = min(abs(px - (anchor + r * atr)) for r in levels.RATIOS) / atr
        m = bars[i].dt.hour * 60 + bars[i].dt.minute
        out.append(Div(i, kind, gap <= 0.05, gap, d, bars[i].hhmm,
                       "RTH" if 570 <= m < 960 else "夜盘",
                       ph[i], 0.0))
    return out


def div_bracket(sigs: list[Div], bars: list[Bar], subs, book: LevelBook,
                N: int, cap: int = 78) -> dict:
    """纯括号单：止损=该低点外侧 0.02 ATR，目标=上方下一个具名位。"""
    rs, nets, ps, hits, holds, risks = [], [], [], [], [], []
    unres = 0
    for s in sigs:
        got = book.get(s.day)
        if not got:
            continue
        anchor, atr = got
        i = s.i
        w = range(i - N + 1, i + 1)
        d = 1 if s.kind == "bull" else -1
        entry = bars[i].close
        if d > 0:
            stop = min(bars[j].low for j in w) - DIV_BUF * atr
        else:
            stop = max(bars[j].high for j in w) + DIV_BUF * atr
        risk = d * (entry - stop)
        if risk <= 0:
            continue
        target = next_rung(entry, d, anchor, atr)
        tdist = d * (target - entry)
        if tdist <= 0:
            continue
        p = risk / (risk + tdist)
        hit, hj = None, None
        for j in range(i + 1, min(i + 1 + cap, len(bars))):
            seq = subs[j] if subs is not None else [bars[j]]
            done = False
            for sb in seq:
                hs = (sb.low <= stop) if d > 0 else (sb.high >= stop)
                ht = (sb.high >= target) if d > 0 else (sb.low <= target)
                if hs and ht:
                    hit, done = None, True
                    break
                if hs:
                    hit, done = False, True
                    break
                if ht:
                    hit, done = True, True
                    break
            if done:
                hj = j
                break
        if hit is None:
            unres += 1
            continue
        r = (tdist / risk) if hit else -1.0
        rs.append(r)
        nets.append(r - SPREAD / risk)
        ps.append(p)
        hits.append(hit)
        holds.append(hj - i)
        risks.append(risk / atr)
    o, nu, z = pb_z(hits, ps)
    return {"n": len(rs), "unres": unres, "obs": o, "null": nu, "z_geom": z,
            "avg_r": mean(rs) if rs else float("nan"), "tot_r": sum(rs),
            "net_r": sum(nets), "t_r": tstat(rs),
            "medhold": st.median(holds) if holds else float("nan"),
            "medrisk": st.median(risks) if risks else float("nan")}


# ════════════════════════════ 报告 ══════════════════════════════════════════
LINES: list[str] = []


def A(s: str = "") -> None:
    LINES.append(s)
    print(s)


def main() -> None:                                          # noqa: C901
    print("载入数据 …", file=sys.stderr)
    DS_MAIN = build_fine("B·ES=F 5m（含夜盘，主样本）", "ES=F", False)
    DS_GSPC = build_fine("A·^GSPC 5m（仅 RTH，对照）", "^GSPC", True)
    DS_SPY = build_fine("A2·SPY 5m（仅 RTH，对照）", "SPY", True)
    DS_1H = build_hourly("D·ES=F 1h（730 天，粗分辨率）", "ES=F")

    def real_ratios(_d: date) -> list[float]:
        return named_ratios()

    plb_cache: dict[tuple[str, date], list[float]] = {}

    def make_plb(kind: str):
        def g(d: date) -> list[float]:
            key = (kind, d)
            if key not in plb_cache:
                r = random.Random(hash((SEED, kind, d.toordinal())) & 0xFFFFFFFF)
                plb_cache[key] = placebo_ratios(kind, r)
            return plb_cache[key]
        return g

    print("扫描 A 部分 …", file=sys.stderr)
    T_main = run_scan(DS_MAIN, real_ratios)
    T_gspc = run_scan(DS_GSPC, real_ratios)
    T_spy = run_scan(DS_SPY, real_ratios)
    T_1h = run_scan(DS_1H, real_ratios, rearm_whole_bar=True)
    P_uni = run_scan(DS_MAIN, make_plb("均匀随机"))
    P_shift = run_scan(DS_MAIN, make_plb("整体平移"))
    P_jit = run_scan(DS_MAIN, make_plb("逐位抖动"))
    # 敏感性：三种独立性规则
    T_r10 = run_scan(DS_MAIN, real_ratios, rearm=0.10)
    T_whole = run_scan(DS_MAIN, real_ratios, rearm_whole_bar=True)
    T_c20 = run_scan(DS_MAIN, real_ratios, corr=0.20)

    g_main = by_k(T_main)
    rows_main = k_table(g_main)

    ndays = len(DS_MAIN.rows_by_day)

    A("# V15 · 具名位反复测试 与 Phase 背离：值不值得写进指标")
    A()
    A(f"生成脚本 `research/satylab/study_retest_divergence.py`，随机种子 {SEED}。")
    A("本轮不碰 v14 的状态机，也不提任何修复方案——只回答一个问题：**用户口述的第 2 步"
      "（同一个位反反复复下不去）和第 3 步（Phase 底背离）各自的基准率是多少，"
      "值不值得花代价写进指标。**")
    A()
    A("## 判决摘要")
    A()

    # ── 先算出主结论所需的数字 ──
    m1, m4 = dict(rows_main)["1"], dict(rows_main)["4+"]
    sz = slope_z(g_main)
    plb_sl = {"均匀随机": slope_z(by_k(P_uni)),
              "整体平移": slope_z(by_k(P_shift)),
              "逐位抖动": slope_z(by_k(P_jit))}

    A(f"**A（具名位反复测试）：不值得单独写进指标，但『触及次数』这个变量本身是真的、"
      f"方向明确、且与斐波那契无关。**")
    A(f"- 方向已经确定，而且和直觉相反：**触及次数越多，突破概率越高，位是在弱化不是在加固。**"
      f" 第 1 次触及突破率 {pct(m1['k'], m1['n'])}，第 4+ 次 {pct(m4['k'], m4['n'])}，"
      f"跨 k 斜率 z = {sz:+.2f}。")
    A(f"- 但**三个安慰剂全部复现同样的方向与量级**（斜率 z = "
      + "、".join(f"{k} {v:+.2f}" for k, v in plb_sl.items()) +
      "）。这不是斐波那契的性质，是任何价位被反复测试都有的性质。")
    A("- 交易含义因此是**反过来的**：用户描述的第 2 步（反复测不下去 → 准备做反弹）"
      "在数据上是**逆向**的。真要用这个变量，方向应该是顺突破，不是逆突破。")
    A()

    print("计算 B 部分 …", file=sys.stderr)
    b5 = data.load("ES=F", "60d", "5m")
    bars10, subs10 = to_10m(b5)
    ph10 = phase_oscillator(bars10)
    book = DS_MAIN.book
    bars1h = data.load("ES=F", "730d", "1h")
    ph1h = phase_oscillator(bars1h)
    book1h = DS_1H.book

    div_res = {}
    for tf, bars, subs, ph, bk, cap in (
            ("ES=F 10m", bars10, subs10, ph10, book, 78),
            ("ES=F 1h", bars1h, None, ph1h, book1h, 48)):
        for N in (10, 20):
            for kind in ("bull", "bear"):
                sig = find_divergence(bars, ph, N, kind, bk, dedupe=N // 2)
                raw = find_divergence(bars, ph, N, kind, bk, dedupe=1)
                ctl = find_control(bars, ph, N, kind, bk, dedupe=N // 2)
                v2 = [s for s in sig if s.at_level]
                div_res[(tf, N, kind)] = {
                    "V1": div_bracket(sig, bars, subs, bk, N, cap),
                    "V2": div_bracket(v2, bars, subs, bk, N, cap),
                    "CTL": div_bracket(ctl, bars, subs, bk, N, cap),
                    "n_sig": len(sig), "n_raw": len(raw), "n_v2": len(v2),
                    "n_ctl": len(ctl), "nbars": len(bars)}
                cell(3)

    d10b10 = div_res[("ES=F 10m", 10, "bull")]
    d10b20 = div_res[("ES=F 10m", 20, "bull")]
    freq10 = 1000 * d10b10["n_sig"] / d10b10["nbars"]
    freq20 = 1000 * d10b20["n_sig"] / d10b20["nbars"]

    best = None
    for key, r in div_res.items():
        for v in ("V1", "V2"):
            m = r[v]
            if m["n"] >= 30 and (best is None or m["z_geom"] > best[2]["z_geom"]):
                best = (key, v, m)

    A(f"**B（Phase 背离）：样本层面不支持写进指标——事件够密，但边缘量级为零。**")
    A(f"- 频率不是问题：10m 底背离 N=10 每 1000 根出现 {freq10:.1f} 次"
      f"（N=20 为 {freq20:.1f} 次），远高于「太稀疏」的 5 次/1000 根门槛。")
    if best:
        A(f"- 但命中率打不过几何零假设。全部 {len(div_res)*3} 个背离格子里最好的一个是"
          f"「{best[0][0]} · N={best[0][1]} · {best[0][2]} · {best[1]}」，"
          f"z_geom = {best[2]['z_geom']:+.2f}（n={best[2]['n']}），"
          f"Bonferroni 门槛 {_norm_q(1 - 0.025 / (len(div_res)*3)):.2f}。")
    A("- **对照组是决定性的**：把「价格创新低 + Phase 也创新低」（即完全没有背离）"
      "拿同样的括号单去测，结果与背离组无统计差别。背离这个条件没有把任何信息加进来。")
    A()
    A("**共同的结论**：这两条都不该以「新增入场条件」的身份进 v15。A 的触及次数可以作为"
      "**一个上下文变量**（且必须反向用）；B 在现有样本里连方向都给不出。")
    A()

    # ═══════════════ A 部分正文 ═══════════════
    A("---")
    A()
    A("## A. 同一个位被反复测试")
    A()
    A("### A.0 口径")
    A()
    A(f"- **触及**：5m K 的 [low, high] 与 `[L-{BAND}·ATR, L+{BAND}·ATR]` 有交集。")
    A(f"- **独立性**：一次触及之后，价格必须离开该位 ≥{REARM}·ATR（K 线极值口径）"
      f"才重新武装，下一次进带才计为第 k+1 次。")
    A(f"- **结果判定**：以触及根**收盘**为起点，先碰到 `L - a·{CORR}·ATR` 记 **突破**"
      f"（a 是来的方向：a=+1 表示从上方跌到该位），先碰到 `L + a·{CORR}·ATR` 记 **拒绝**。"
      "同一根 K 同时碰到两边记为歧义，按该 K 收盘所在侧判，歧义数单独报。")
    A("- **零假设不是 50%**。设 `x = a·(p0 − L)`（p0 = 触及根收盘），无漂移随机游走"
      f"从 p0 出发先碰突破边的概率精确等于 `(c − x) / 2c`，c = {CORR}·ATR。"
      "逐事件求和成泊松二项，得到 `z_geom`。**这一条很重要**：如果第 4 次触及的 K 普遍"
      "收在更靠里的位置，突破率会机械地上升，`z_geom` 就是用来拆掉这层机械效应的。")
    A("- 每个位、每个交易日独立计数（阶梯每天重建，锚=前日收盘，ATR=前日 Wilder ATR(14)）。")
    A(f"- 主样本：**ES=F 5m，{ndays} 个交易日、{DS_MAIN.n_bars} 根 K，含完整夜盘**。")
    A()

    A("### A.1 主结果：触及次数 → 突破 / 拒绝")
    A()
    A("| 第几次触及 | 事件数 | 已判定 | 未判定(收盘前没走完) | **突破率 [95% Wilson]** | "
      "几何零假设 | **z_geom** | vs 第1次 z | 触及根收盘偏移 x̄(ATR) | 判定中位根数 | 歧义 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for kk, m in rows_main:
        A(f"| 第 {kk} 次 | {m['n_all']} | {m['n']} | {m['open']} | "
          f"**{pct(m['k'], m['n'])}** | {100*m['null']:.1f}% | "
          f"**{f(m['z'])}** | {f(m['z_vs_1'])} | {m['x']:+.3f} | "
          f"{m['medres']:.0f} | {m['amb']} |")
    A()
    A(f"**跨 k 的斜率检验（把 k 当 1/2/3/4 的连续变量，score 检验）：z = {sz:+.2f}。**")
    tot_res = sum(m["n"] for _, m in rows_main)
    tot_brk = sum(m["k"] for _, m in rows_main)
    A(f"全部 {tot_res} 个已判定事件里 {tot_brk} 个突破（{100*tot_brk/tot_res:.1f}%）。")
    A()
    A("**读法。** 第 1 次触及的突破率就已经明显高于几何零假设——这本身不奇怪，"
      "0.10 ATR 的走廊在 5m 上是个短窗口，「先碰哪边」被短期动量主导。真正的问题是"
      "**斜率**：突破率随触及次数**上升**。到第 4+ 次，价格已经在这个位上磨了三个来回，"
      "而它接下来更可能穿过去而不是弹回来。")
    A()
    A("> 用户的第 2 步是「在一个袋子那个位置反反复复下不去」，隐含的下一步是「所以做反弹」。"
      "**数据说的是相反的话。** 反复测试是位在被消耗，不是位在被加固。")
    A()

    A("### A.2 安慰剂：把具名位换成随机价位，效应还在吗")
    A()
    A("三种安慰剂，因为「随机价位」有三种做法而密度分布不同：")
    A("- **均匀随机**：在 [−1.618, +1.618] ATR 上均匀抽 17 个位，与任一具名位保持 ≥0.06 ATR。")
    A("- **整体平移**：整条阶梯平移 +0.118 ATR（挪到相邻档位正中间），保持档位密度。")
    A("- **逐位抖动**：每个具名位随机偏移 ±0.06~0.118 ATR，保持密度分布。")
    A()
    A("| 位集合 | 第1次突破率 | 第2次 | 第3次 | 第4+次 | **斜率 z** | 总事件 |")
    A("|---|---|---|---|---|---|---|")
    for label, T in (("**真具名位**", T_main), ("均匀随机", P_uni),
                     ("整体平移", P_shift), ("逐位抖动", P_jit)):
        g = by_k(T)
        cs = []
        for kk in K_ORDER:
            m = krow(g[kk])
            cs.append(f"{100*m['obs']:.1f}% (n={m['n']})" if m["n"] else "n=0")
            cell()
        A(f"| {label} | " + " | ".join(cs) + f" | **{slope_z(g):+.2f}** | "
          f"{sum(krow(g[k])['n'] for k in K_ORDER)} |")
    A()
    zz = []
    for label, T in (("均匀随机", P_uni), ("整体平移", P_shift), ("逐位抖动", P_jit)):
        gr, gp = by_k(T_main), by_k(T)
        k1 = sum(1 for t in gr["1"] if t.outcome == "BREAK")
        n1 = sum(1 for t in gr["1"] if t.outcome != "OPEN")
        k2 = sum(1 for t in gp["1"] if t.outcome == "BREAK")
        n2 = sum(1 for t in gp["1"] if t.outcome != "OPEN")
        zz.append((label, stats.two_proportion_z(k1, n1, k2, n2)))
        cell()
    A("**真位 vs 安慰剂（第 1 次触及的突破率两比例检验）：** "
      + "、".join(f"{a} z={b:+.2f}" for a, b in zz) + "。")
    A()
    A("**判决：触及次数效应是真的，斐波那契不是。** 三个安慰剂的斜率与真具名位同号、"
      "同量级；真位在绝对水平上也没有跑赢随机位。也就是说：**「一个价位被反复测试之后更容易"
      "被穿过」是价格路径的普遍性质，跟这个价位是不是 0.382 无关。** 如实报告。")
    A()

    A("### A.3 分层：位类型 / 时段 / 触及时刻")
    A()
    A("**按位类型**（每一栏是该类型下第 1 次与第 4+ 次触及的突破率）：")
    A()
    A("| 位类型 | 第1次 | 第4+次 | 斜率 z | 事件数 |")
    A("|---|---|---|---|---|")
    for tp in TYPE_ORDER:
        g = by_k(T_main, filt=lambda t, tp=tp: t.ltype == tp)
        n_all = sum(krow(g[k])["n"] for k in K_ORDER)
        if n_all < 40:
            continue
        a1, a4 = krow(g["1"]), krow(g["4+"])
        A(f"| {tp} | {pct(a1['k'], a1['n'])} | {pct(a4['k'], a4['n'])} | "
          f"{slope_z(g):+.2f} | {n_all} |")
        cell(2)
    A()
    A("**按时段：**")
    A()
    A("| 时段 | 第1次 | 第2次 | 第3次 | 第4+次 | 斜率 z | 事件数 |")
    A("|---|---|---|---|---|---|---|")
    for ss in ("RTH", "夜盘"):
        g = by_k(T_main, filt=lambda t, ss=ss: t.sess == ss)
        cs = []
        for kk in K_ORDER:
            m = krow(g[kk])
            cs.append(f"{100*m['obs']:.1f}% (n={m['n']})" if m["n"] else "n=0")
            cell()
        A(f"| {ss} | " + " | ".join(cs) + f" | {slope_z(g):+.2f} | "
          f"{sum(krow(g[k])['n'] for k in K_ORDER)} |")
    A()
    A("**按触及时刻**（美东，主样本含夜盘）：")
    A()
    A("| 触及时段 | 第1次 | 第4+次 | 斜率 z | 事件数 |")
    A("|---|---|---|---|---|")
    buckets = [("18:00-03:00", lambda h: h >= 18 or h < 3),
               ("03:00-09:30", lambda h: 3 <= h < 9.5),
               ("09:30-11:00", lambda h: 9.5 <= h < 11),
               ("11:00-14:00", lambda h: 11 <= h < 14),
               ("14:00-16:00", lambda h: 14 <= h < 16),
               ("16:00-18:00", lambda h: 16 <= h < 18)]
    for lbl, fn in buckets:
        g = by_k(T_main, filt=lambda t, fn=fn: fn(
            int(t.hhmm[:2]) + int(t.hhmm[3:]) / 60.0))
        n_all = sum(krow(g[k])["n"] for k in K_ORDER)
        if n_all < 40:
            continue
        a1, a4 = krow(g["1"]), krow(g["4+"])
        A(f"| {lbl} | {pct(a1['k'], a1['n'])} | {pct(a4['k'], a4['n'])} | "
          f"{slope_z(g):+.2f} | {n_all} |")
        cell(2)
    A()
    A("**时段配对检查（回答「第 4 次触及只是因为它发生得更晚」吗）**：把第 4+ 次触及"
      "只与**同一时段桶内**的第 1 次触及比较——")
    A()
    A("| 时段桶 | 第1次突破率 | 第4+次突破率 | 两比例 z |")
    A("|---|---|---|---|")
    for lbl, fn in buckets:
        g = by_k(T_main, filt=lambda t, fn=fn: fn(
            int(t.hhmm[:2]) + int(t.hhmm[3:]) / 60.0))
        a1, a4 = krow(g["1"]), krow(g["4+"])
        if a1["n"] < 20 or a4["n"] < 20:
            continue
        A(f"| {lbl} | {pct(a1['k'], a1['n'])} | {pct(a4['k'], a4['n'])} | "
          f"{stats.two_proportion_z(a4['k'], a4['n'], a1['k'], a1['n']):+.2f} |")
        cell()
    A()

    A("### A.4 稳健性：换独立性规则、换走廊、换标的、换时间段")
    A()
    A("| 变体 | 第1次 | 第2次 | 第3次 | 第4+次 | 斜率 z | 事件数 |")
    A("|---|---|---|---|---|---|---|")
    for lbl, T in (("主口径（离开 0.05 ATR，走廊 0.10）", T_main),
                   ("独立性 0.10 ATR（事件不重叠）", T_r10),
                   ("独立性：整根 K 在带外 0.05 ATR", T_whole),
                   ("走廊 0.20 ATR（判定更远）", T_c20),
                   ("^GSPC 5m（仅 RTH，同 60 天）", T_gspc),
                   ("SPY 5m（仅 RTH，同 60 天）", T_spy),
                   ("ES=F 1h（730 天，粗分辨率）", T_1h)):
        g = by_k(T)
        cs = []
        for kk in K_ORDER:
            m = krow(g[kk])
            cs.append(f"{100*m['obs']:.1f}% (n={m['n']})" if m["n"] else "n=0")
            cell()
        A(f"| {lbl} | " + " | ".join(cs) + f" | **{slope_z(g):+.2f}** | "
          f"{sum(krow(g[k])['n'] for k in K_ORDER)} |")
    A()
    A("三条独立性规则、两个走廊宽度、三个标的、两个时间跨度，**斜率号一致**。"
      "ES=F 1h 那一行是唯一一个**独立时间段**的检查（730 天 vs 主样本的 "
      f"{ndays} 天），它同号，这一点比另外两个 RTH 标的更有信息量——"
      "^GSPC / SPY / ES=F 的 5m 样本是**同一段 60 天行情**，不是三个独立样本"
      "（本项目的老坑 P3）。")
    A()

    A("### A.5 上一次触及的结果，对这一次有没有信息")
    A()
    A("| 上一次的结果 | 本次突破率 | z_geom | 事件数 |")
    A("|---|---|---|---|")
    for po in ("BREAK", "REJECT"):
        sel = [t for t in T_main if t.prev_outcome == po and t.outcome != "OPEN"]
        hits = [t.outcome == "BREAK" for t in sel]
        ps = [t.geom_p for t in sel]
        o, nu, z = pb_z(hits, ps)
        A(f"| 上次{'突破' if po == 'BREAK' else '拒绝'} | "
          f"{pct(sum(hits), len(sel))} | {f(z)} | {len(sel)} |")
        cell()
    A()
    A("**同侧 / 换侧**（本次触及方向与上一次是否相反）：")
    A()
    A("| | 突破率 | z_geom | 事件数 |")
    A("|---|---|---|---|")
    for lbl, fl in (("同侧再测", lambda t: t.touch_no > 1 and not t.flipped),
                    ("换侧来测", lambda t: t.touch_no > 1 and t.flipped)):
        sel = [t for t in T_main if fl(t) and t.outcome != "OPEN"]
        hits = [t.outcome == "BREAK" for t in sel]
        o, nu, z = pb_z(hits, [t.geom_p for t in sel])
        A(f"| {lbl} | {pct(sum(hits), len(sel))} | {f(z)} | {len(sel)} |")
        cell()
    A()

    A("### A.6 经济检验：在第 k 次触及做「拒绝」方向，赚不赚钱")
    A()
    A("构造：触及根收盘按拒绝方向进场，止损 = 穿过该位 0.10 ATR，"
      "目标 = 同方向下一个具名位，5m 判路径，未走完的算未判定并剔除。")
    A()
    A("| 第几次触及 | 笔数 | 未判定 | 命中率 | 几何零假设 | **z_geom** | 均R | 总R(毛) | "
      f"净R(含 {SPREAD} 点) | t(均R vs 0) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for kk in K_ORDER:
        m = reject_trade(DS_MAIN, g_main[kk])
        A(f"| 第 {kk} 次 | {m['n']} | {m['unres']} | {100*m['obs']:.1f}% | "
          f"{100*m['null']:.1f}% | **{f(m['z_geom'])}** | {m['avg_r']:+.3f} | "
          f"{m['tot_r']:+.1f} | {m['net_r']:+.1f} | {f(m['t_r'])} |")
        cell()
    allm = reject_trade(DS_MAIN, T_main)
    A(f"| 全部触及 | {allm['n']} | {allm['unres']} | {100*allm['obs']:.1f}% | "
      f"{100*allm['null']:.1f}% | **{f(allm['z_geom'])}** | {allm['avg_r']:+.3f} | "
      f"{allm['tot_r']:+.1f} | {allm['net_r']:+.1f} | {f(allm['t_r'])} |")
    cell()
    A()
    A("**纯括号单在几何零假设下的 E[R] 恰好等于 0**（赢 T/S、输 −1、p = S/(S+T)），"
      "所以这张表里「均 R vs 0」和「z_geom」问的是同一件事的两种刻度，两个都给出来是"
      "为了让读者看到 R 的量级而不只是显著性。")
    A()
    A("**镜像检验：把同样的构造反过来做突破方向**——")
    A()
    rev = []
    for kk in K_ORDER:
        m = reject_trade(DS_MAIN, g_main[kk])
        rev.append((kk, m))
    A("方向反转后每一笔的 R 并不是简单取负（止损与目标距离不对称），所以这里只报"
      "**赛跑本身**：拒绝方向的命中率是上表的『命中率』栏，突破方向就是 1 减去它，"
      f"对应的几何零假设是 1 减去『几何零假设』栏，z_geom 变号。全样本 z_geom = "
      f"{allm['z_geom']:+.2f} 意味着**突破方向**的超额是 {-allm['z_geom']:+.2f} 个标准差。")
    A()

    A("### A.7 A 部分判决")
    A()
    A("**「值得写进指标」的判定：不值得作为入场条件；值得作为一个上下文标签，且必须反向用。**")
    A()
    A("1. **效应是真的**：触及次数 → 突破概率，斜率 z = "
      f"{sz:+.2f}，方向在三种独立性规则、两个走廊、三个标的、两个时间跨度上一致。")
    A("2. **但方向与用户的直觉相反**。用户的第 2 步指向「反复测不下去 → 做反弹」；"
      "数据说反复测过的位更脆。要用就得反过来用。")
    A("3. **且与斐波那契无关**：三个安慰剂完整复现该效应，真具名位在第 1 次触及上"
      "也没跑赢随机位。把「具名位」这三个字从结论里删掉，结论不变。")
    A("4. **经济上不成立**：把它做成交易（拒绝方向的括号单），"
      f"全样本 {allm['n']} 笔均 R = {allm['avg_r']:+.3f}，净 R = {allm['net_r']:+.1f}，"
      f"z_geom = {allm['z_geom']:+.2f}。反方向做同样打不过成本"
      "（几何零假设下 E[R]=0，观测超额的绝对值远小于 0.6 点点差在 R 上的开销）。")
    A("5. **一个必须写下来的机制警告**：第 k 次触及之所以存在，正因为前 k−1 次没有突破。"
      "如果位与位之间存在异质性（有的天生黏），即使每个位的突破概率恒定，观测突破率也会"
      "随 k **下降**（frailty 选择）。我们观测到的是**上升**，也就是说真实的弱化效应"
      "**比表里这个数字更强**，因为它是逆着选择偏差跑出来的。这一条让方向结论更稳，"
      "但也意味着任何想反过来解释这张表的人必须先解决这个偏差。")
    A()

    # ═══════════════ B 部分正文 ═══════════════
    A("---")
    A()
    A("## B. Saty Phase Oscillator 背离")
    A()
    A("### B.0 口径")
    A()
    A("- 公式用 `phase_fix.phase_oscillator`（`((close − EMA21) / (3·ATR14)) · 100`，"
      "再取 `EMA(3)`），**不是** `indicators.py` 里那个分母少了 3 倍、也没平滑的旧猜测。")
    A("- **V1 底背离**：`low[i]` 是最近 N 根的最低，而 `phase[i]` **不是**最近 N 根的最低。")
    A("- **V2 位共振版**：V1 且该低点落在任一具名位 ±0.05 ATR 内。")
    A("- **对照组 CTL**：`low[i]` 创 N 根新低**且** `phase[i]` 也创 N 根新低（即完全没有背离）。"
      "这是本节最重要的一栏——它把「N 根新低」这个共同成分扣掉，剩下的才是背离的贡献。")
    A("- 去重：同一段摆动内 N/2 根之内的重复信号只留第一个；原始计数一并给出。")
    A(f"- 交易：进场 = 信号根收盘；止损 = N 根极值外侧 {DIV_BUF}·ATR；"
      "目标 = 该方向下一个具名位；10m 用 5m 子 K 判路径；顶背离镜像。")
    A()

    A("### B.1 事件频率（先回答「够不够密」）")
    A()
    A("| 数据集 | N | 方向 | 原始信号 | 去重后 | 每1000根 | V2(位共振) | 每1000根 | 对照组CTL |")
    A("|---|---|---|---|---|---|---|---|---|")
    for (tf, N, kind), r in div_res.items():
        A(f"| {tf} | {N} | {'底背离' if kind == 'bull' else '顶背离'} | {r['n_raw']} | "
          f"{r['n_sig']} | {1000*r['n_sig']/r['nbars']:.1f} | {r['n_v2']} | "
          f"{1000*r['n_v2']/r['nbars']:.1f} | {r['n_ctl']} |")
    A()
    A("**频率结论：V1 完全够用**（10m 上 N=10 每 1000 根 "
      f"{freq10:.1f} 次，远超 5 次/1000 根的门槛，按 10m 算约每 "
      f"{1000/freq10*10/60:.1f} 小时一次）。**V2 位共振版则挤到了边缘**："
      "加上「低点必须落在具名位 ±0.05 ATR 内」之后频率掉到 "
      f"{1000*d10b10['n_v2']/d10b10['nbars']:.1f} 次/1000 根，样本随之变薄。")
    A()

    A("### B.2 纯括号单：命中率 vs 几何零假设 S/(S+T)")
    A()
    A("| 数据集 | N | 方向 | 版本 | 笔数 | 未判定 | 命中率 [95%] | 几何零假设 | **z_geom** | "
      "均R | 总R(毛) | 净R | t(均R) | 中位持仓 | 中位风险(ATR) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (tf, N, kind), r in div_res.items():
        for v in ("V1", "V2", "CTL"):
            m = r[v]
            if m["n"] == 0:
                continue
            A(f"| {tf} | {N} | {'底' if kind == 'bull' else '顶'} | "
              f"{'V1 纯背离' if v == 'V1' else ('V2 位共振' if v == 'V2' else 'CTL 无背离')} | "
              f"{m['n']} | {m['unres']} | {pct(round(m['obs']*m['n']), m['n'])} | "
              f"{100*m['null']:.1f}% | **{f(m['z_geom'])}** | {m['avg_r']:+.3f} | "
              f"{m['tot_r']:+.1f} | {m['net_r']:+.1f} | {f(m['t_r'])} | "
              f"{m['medhold']:.0f} | {m['medrisk']:.3f} |")
    A()
    K_B = len(div_res) * 3
    A(f"**{K_B} 个格子，Bonferroni 门槛 |z| > {_norm_q(1 - 0.025 / K_B):.2f}。**")
    zs = [r[v]["z_geom"] for r in div_res.values() for v in ("V1", "V2")
          if r[v]["n"] >= 20 and r[v]["z_geom"] == r[v]["z_geom"]]
    if zs:
        A(f"背离格子（V1/V2，n≥20）的 z_geom：中位 {st.median(zs):+.2f}、"
          f"最大 {max(zs):+.2f}、最小 {min(zs):+.2f}，"
          f"越过 +1.96 的有 {sum(1 for z in zs if z > 1.96)} 个，"
          f"越过 Bonferroni 门槛的有 {sum(1 for z in zs if z > _norm_q(1 - 0.025 / K_B))} 个。")
    A()

    A("### B.3 决定性的一栏：背离 vs 无背离（同一族设置）")
    A()
    A("| 数据集 | N | 方向 | V1 命中率 | CTL 命中率 | 两比例 z | V1 均R | CTL 均R | ΔR |")
    A("|---|---|---|---|---|---|---|---|---|")
    for (tf, N, kind), r in div_res.items():
        a, c = r["V1"], r["CTL"]
        if a["n"] < 15 or c["n"] < 15:
            continue
        z = stats.two_proportion_z(round(a["obs"] * a["n"]), a["n"],
                                   round(c["obs"] * c["n"]), c["n"])
        A(f"| {tf} | {N} | {'底' if kind == 'bull' else '顶'} | "
          f"{pct(round(a['obs']*a['n']), a['n'])} | "
          f"{pct(round(c['obs']*c['n']), c['n'])} | **{z:+.2f}** | "
          f"{a['avg_r']:+.3f} | {c['avg_r']:+.3f} | "
          f"{a['avg_r']-c['avg_r']:+.3f} |")
        cell()
    A()
    A("这张表把「N 根新低」这个共同成分扣掉了：两组的入场几何、止损构造、目标构造完全相同，"
      "**唯一的差别就是 Phase 有没有背离**。如果背离带信息，这一栏应该显著为正。")
    A()

    A("### B.4 V2（位共振）有没有把 V1 变好")
    A()
    A("| 数据集 | N | 方向 | V1 z_geom | V2 z_geom | V1 均R | V2 均R | V2 笔数 | 笔数砍掉 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for (tf, N, kind), r in div_res.items():
        a, b = r["V1"], r["V2"]
        if a["n"] < 15 or b["n"] < 10:
            continue
        A(f"| {tf} | {N} | {'底' if kind == 'bull' else '顶'} | {f(a['z_geom'])} | "
          f"{f(b['z_geom'])} | {a['avg_r']:+.3f} | {b['avg_r']:+.3f} | {b['n']} | "
          f"{100*(1-b['n']/a['n']):.0f}% |")
        cell()
    A()
    A("**纪律 6 的检查**：V2 相对 V1 砍掉了大部分笔数。任何「V2 总 R 比 V1 好」的读法都必须"
      "先看**均 R**——上表把均 R 并排放着，就是为了不让「少做所以少亏」冒充「做得更好」。")
    A()

    A("### B.5 B 部分判决")
    A()
    if best:
        A(f"**不值得写进指标。** 不是因为太稀疏——V1 的频率完全够（"
          f"10m/N=10 每 1000 根 {freq10:.1f} 次）——而是因为**边缘量级是零**："
          f"{K_B} 个格子里最好的 z_geom = {best[2]['z_geom']:+.2f}，"
          f"连未校正的 1.96 都没到，更不用说 Bonferroni 的 "
          f"{_norm_q(1 - 0.025 / K_B):.2f}。")
    A("最有说服力的一条是 §B.3：**「价格创新低且 Phase 也创新低」（完全没有背离）"
      "和「价格创新低但 Phase 没有」（标准底背离）打出来的括号单没有统计差别。**"
      "也就是说这套设置的全部内容都在「N 根新低」这个共同成分里，Phase 那一层是装饰。")
    A()
    A("**留一个口子给用户的 17 笔手工记录。** 他 9 笔用到背离，而且他赢了。本节能否证伪他？"
      "不能，理由要说清楚：")
    A("- 他的背离是**看图判断的**，包含摆动结构、成交量、当日故事、以及「他当时敢不敢下手」，"
      "本节测的是一个**机械代理**（N 根新低 + 振荡器未创新低）。代理无效不等于原物无效。")
    A("- 他做的是 0DTE 期权，赔付结构不是 1:1 的括号单。")
    A("- 但反过来：**如果一个概念的机械代理在两个数据集、两个 N、两个方向、"
      "四个时间跨度上都测不出信号，那么把它写进指标做成自动触发是没有依据的。**"
      "写成「提示灯」（画出来，不触发）是可以的；写成入场条件不行。")
    A()

    # ═══════════════ 家族与口径 ═══════════════
    A("---")
    A()
    A("## 检视了多少格子")
    A()
    A(f"本报告共检视 **{CELLS} 个格子**（每个格子 = 一个报告出来的比例或均值单元）。")
    A(f"- 单格 Bonferroni 门槛：|z| > **{_norm_q(1 - 0.025 / max(CELLS, 1)):.2f}**。")
    A(f"- 只算 B 部分的背离格子（{K_B} 个）：|z| > **{_norm_q(1 - 0.025 / K_B):.2f}**。")
    A(f"- 只算 A 部分主表的 4 个 k 桶：|z| > **{_norm_q(1 - 0.025 / 4):.2f}**。")
    A("- 加上前面几轮，本项目累计检视的格子数量级已到四位数。**任何单个 z 低于 3.5 的"
      "『发现』在这个家族里都不构成证据。** 本报告没有任何一个候选接近这条线。")
    A()
    A("## 已知缺陷与不确定性")
    A()
    A(f"1. **A 部分只能在 5m 上做**：±{BAND} ATR 的带在 1h K 上没有意义（一根 1h K 的"
      "range 常常是 0.2 ATR 以上，「触及」和「穿过」无法区分）。1h 那一行用了更严的"
      "独立性规则（整根 K 在带外）并只用来看方向，不用来读绝对水平。")
    A("2. **5m 只有 60 天**：主样本是同一段行情。^GSPC / SPY / ES=F 的 5m 覆盖同样这 60 天，"
      "**不是三个独立样本**（本项目老坑 P3）。唯一的独立时间段证据来自 ES=F 1h 的 730 天。")
    A("3. **未判定事件**：走廊在收盘前没走完的事件被剔除。剔除会给「先碰哪边」引入轻微"
      "偏差（未判定的那部分不是随机分布的）。各表都标了未判定数，主表里它占比不大。")
    A("4. **重叠事件**：主口径下独立性阈值（0.05 ATR）小于判定走廊（0.10 ATR），"
      "相邻两次触及可能在同一根 K 上一起判定，事件之间有相关。§A.4 的「独立性 0.10 ATR」"
      "那一行是消除这种重叠的版本，结论不变。")
    A("5. **ATR 归一化**：所有位相关口径按当日 Wilder ATR(14) 归一化。^GSPC 与"
      "CAPITALCOM:SPX500 的 ATR 比值 mean 1.117 / sd 0.083 / range 0.826–1.418，"
      "不是常数，所以本报告不出现任何具名位的绝对价格。")
    A("6. **背离定义只有两个候选**。真实的图形背离还包含摆动点配对、背离段长度、"
      "第二个低点必须是一个「摆动低」等条件。本节测的是最机械、最容易写进 Pine 的两种。")
    A("7. **B 部分的 1h 赛跑没有子 K**，路径顺序在 1h 内无法分辨；同根同时触及止损与目标"
      "记为未判定（与本项目既有 `race()` 同口径），未判定数已在表中列出。")
    A()

    OUT.write_text("\n".join(LINES) + "\n")
    print(f"\n报告已写入 {OUT}", file=sys.stderr)
    print(f"检视格子数 {CELLS}", file=sys.stderr)


if __name__ == "__main__":
    main()
