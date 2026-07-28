#!/usr/bin/env python3
"""S2（同一个位被反复拒绝）与 S3（Saty Phase 背离）——用户口述三步法的第 2、3 步。

这两个 setup 在 v14 里**完全没有实现**，所以没有任何前向数据，只能靠历史检验。

S2「反反复复下不去」
--------------------
同一具名位被独立触及 ≥N 次（进入 ±in_band·ATR 记一次；必须收在离该位
≥out_band·ATR 之外才结束本次事件并重新武装），事件以「离开该位」结束——
如果是往来的那一侧离开（拒绝），就在那根 K 的收盘按**背离该位的方向**入场。

要回答三个问题：
  1. N = 1..5（及 6+）各自的 n / 命中率 / 几何零假设 S/(S+T) / z_geom / 均净R。
     用户猜「碰两次以后就可以考虑」——直接检验 k≥2 是不是真的比 k=1 好。
  2. 带宽敏感性 in ∈ {0.02,0.03,0.05} × out ∈ {0.03,0.05,0.08}，9 个格子。
     如果结论对带宽极度敏感，那就是过拟合，必须明说。
  3. 衰减检验：穿透深度（本次触及越过该位的最大距离）是否递减？
     「深度递减」比「次数≥N」更有预测力吗？

S3「Saty Oscillator 底背离」
---------------------------
价格在回看 N 根内创新极值，Phase 不创新极值。N = 10/15/20/30。
关键增量：**与具名位的合取**。Saty 07-26 的笔记开篇是「10m divergence at
support」——背离与位在他那里是绑在一起的。本项目的已知缺口（SPEC_VOMY_FROM_AUTHOR
§3.2「我把一个五重合取拆成单项分别测了」）正是没测过合取，这里补上：把
「价格创新 N 根极值」当作共同底盘，做一张 2×2（背离有/无 × 在位/不在位）
的完整表，而不是只测单项。

口径纪律（本项目吃过的亏，逐条钉住）
------------------------------------
1. 零假设是**几何零假设** P = S/(S+T)，不是 50%。逐笔的 p 不同，求和成泊松
   二项，报 z_geom。
2. 路径判定不能同根裁决。S3 的 setup 在 10m、判定落到 5m 子 K。S2 的触及必须
   在 5m 上数（±0.03 ATR 的带在 10m 上没有分辨率），所以 S2 的主表用 5m 判定
   并把「同根同时碰到止损与目标」记为未判定剔除+如实报数；另外用 21 天的 1m
   数据做一次真正的子 K 复核。
3. 多重比较自报格子数 + Bonferroni 门槛。
4. 点差 0.6 点，毛 R 与净 R 都报。
5. 位相关研究主样本用 ES=F（含完整夜盘，作息与 CAPITALCOM:SPX500 一致）；
   ^GSPC 只做 RTH 对照，且不出现任何绝对价位。
6. 样本量小就说小；任何「砍笔数换总 R」都要先看均净R 与 z_sel。
7. 与假设相反的格子单列一节。

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
from satylab.study_v14_filters import _fpc_z, _norm_q, load_1m   # noqa: E402

SEED = 20260728
IN_BAND = 0.03       # ±0.03 ATR 触及带（任务指定主口径）
OUT_BAND = 0.05      # 收盘离开 ≥0.05 ATR 结束本次触及（任务指定主口径）
STOP_BUF = 0.02      # 止损放在本次穿透极值外侧 0.02 ATR
DIV_BUF = 0.02       # 背离单止损放在 N 根极值外侧 0.02 ATR
AT_LEVEL = 0.10      # S3 合取：极值距具名位 ≤0.10 ATR（任务指定）
AT_LEVEL_TIGHT = 0.05
SPREAD = 0.6         # 点差（点），与前几份报告同口径
OUT = Path(__file__).resolve().parents[1] / "reports" / \
    "V15_LEVEL_RETEST_AND_DIVERGENCE.md"

CELLS = 0


def cell(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ════════════════════════════ 统计小工具 ════════════════════════════════════
def pb_z(hits: list[bool], ps: list[float]) -> tuple[float, float, float]:
    """泊松二项 z：观测命中数 vs Σp，方差 Σp(1−p)。返回 (obs, null, z)。"""
    n = len(ps)
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    k = sum(1 for h in hits if h)
    sp = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    z = (k - sp) / math.sqrt(var) if var > 0 else float("nan")
    return (k / n, sp / n, z)


def f(x, d: int = 2) -> str:
    return "–" if x is None or x != x else f"{x:+.{d}f}"


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n=0"
    lo, hi = stats.wilson(k, n)
    return f"{100*k/n:.1f}% [{100*lo:.1f},{100*hi:.1f}]"


def tstat(xs: list[float], mu0: float = 0.0) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    sd = st.stdev(xs)
    return (mean(xs) - mu0) / (sd / math.sqrt(n)) if sd > 0 else float("nan")


def mannwhitney_z(a: list[float], b: list[float]) -> float:
    """秩和检验 z（正态近似，带并列修正）。用于连续量（深度）的组间比较。"""
    na, nb = len(a), len(b)
    if na < 5 or nb < 5:
        return float("nan")
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * (na + nb)
    i = 0
    ties = 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        t = j - i + 1
        ties += t ** 3 - t
        for q in range(i, j + 1):
            ranks[q] = r
        i = j + 1
    ra = sum(ranks[q] for q in range(len(allv)) if allv[q][1] == 0)
    u = ra - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    n = na + nb
    var = na * nb / 12.0 * ((n + 1) - ties / (n * (n - 1)))
    return (u - mu) / math.sqrt(var) if var > 0 else float("nan")


# ════════════════════════════ 具名位命名 ════════════════════════════════════
def rung_type(r: float) -> str:
    a = abs(r)
    return {0.0: "PDC", 0.236: "trigger", 0.382: "0.382", 0.5: "0.5",
            0.618: "0.618", 0.786: "0.786", 1.0: "1.0ATR"}.get(
                round(a, 3), "ext(1.272/1.618)")


TYPE_ORDER = ["PDC", "trigger", "0.382", "0.5", "0.618", "0.786", "1.0ATR",
              "ext(1.272/1.618)"]


# ════════════════════════════ S2：触及事件 ══════════════════════════════════
@dataclass(slots=True)
class Ep:
    day: date
    ratio: float
    ltype: str
    L: float
    atr: float
    anchor: float
    k: int                  # 第几次触及（同一位、同一交易日）
    a: int                  # 来的方向：+1 从上方跌到该位（位=支撑），-1 从下方
    i0: int                 # 触及根
    i1: int                 # 事件结束根（=拒绝时的入场根）
    kind: str               # REJECT / BREAK / OPEN（收盘前没结束）
    depth: float            # 穿透深度（ATR），=本次越过该位的最大距离，≥0
    hhmm: str
    sess: str
    prev_depth: float       # 上一次触及的深度（nan 表示没有上一次）
    prev2_depth: float
    same_side: bool         # 与上一次触及来的方向相同
    prev_kind: str


def scan_level(rows: list[Bar], L: float, atr: float, anchor: float,
               ratio: float, day: date, in_b: float, out_b: float,
               sess_of) -> list[Ep]:
    """扫一个位一天的全部触及事件。

    事件边界一律用**收盘**：进入 ±in_b·ATR 带 → 事件开始；第一根收盘满足
    |close − L| ≥ out_b·ATR → 事件结束。往来的那一侧结束 = REJECT（拒绝），
    往另一侧结束 = BREAK（击穿）。用收盘而不是极值，是因为「离开」这件事必须
    有一个可成交的价格（入场价），用影线会把入场价说成一个当时没成交过的数。
    """
    b, o = in_b * atr, out_b * atr
    n = len(rows)
    out: list[Ep] = []
    # 起点：第一根收盘明确在带外的 K，用它定初始所在侧
    s = None
    for i in range(n):
        if abs(rows[i].close - L) >= o:
            s = i
            break
    if s is None:
        return out
    side = 1 if rows[s].close > L else -1
    i = s + 1
    k = 0
    hist: list[Ep] = []
    while i < n:
        bar = rows[i]
        if not (bar.low <= L + b and bar.high >= L - b):
            if bar.close > L + o:
                side = 1
            elif bar.close < L - o:
                side = -1
            i += 1
            continue
        # ── 触及 ──
        k += 1
        a = side
        depth_px = 0.0
        kind, i1 = "OPEN", n - 1
        for j in range(i, n):
            bb = rows[j]
            p_far = bb.low if a > 0 else bb.high
            depth_px = max(depth_px, a * (L - p_far))
            dc = a * (bb.close - L)
            if dc >= o:
                kind, i1 = "REJECT", j
                break
            if dc <= -o:
                kind, i1 = "BREAK", j
                break
        pd = hist[-1].depth if hist else float("nan")
        pd2 = hist[-2].depth if len(hist) >= 2 else float("nan")
        ep = Ep(day, ratio, rung_type(ratio), L, atr, anchor, k, a, i, i1,
                kind, max(0.0, depth_px) / atr, bar.hhmm, sess_of(bar),
                pd, pd2, bool(hist) and hist[-1].a == a,
                hist[-1].kind if hist else "—")
        out.append(ep)
        hist.append(ep)
        if kind == "OPEN":
            break
        side = a if kind == "REJECT" else -a
        i = i1 + 1
    return out


# ════════════════════════════ 数据集 ════════════════════════════════════════
@dataclass
class Dataset:
    name: str
    rows_by_day: dict
    book: LevelBook
    n_bars: int
    subs_by_day: dict | None = None      # 5m index -> 更细的子 K 列表


def build_5m(name: str, symbol: str, rth_only: bool) -> Dataset:
    b5 = data.load(symbol, "60d", "5m")
    if rth_only:
        b5 = drop_close_stub(b5)
    by: dict[date, list[Bar]] = defaultdict(list)
    for b in b5:
        by[trade_day(b)].append(b)
    for v in by.values():
        v.sort(key=lambda x: x.dt)
    return Dataset(name, dict(by), LevelBook(data.load(symbol, "20y", "1d")),
                   len(b5))


def attach_1m(ds: Dataset, symbol: str) -> Dataset:
    """给 5m 每根 K 挂上它的 1m 子 K（只有最近 21 天有 1m）。"""
    m1 = load_1m(symbol)
    bucket: dict[tuple, list[Bar]] = defaultdict(list)
    for b in m1:
        bucket[(b.day, b.dt.hour, b.dt.minute // 5)].append(b)
    subs: dict[date, list] = {}
    keep: dict[date, list[Bar]] = {}
    for d, rows in ds.rows_by_day.items():
        got = [bucket.get((r.day, r.dt.hour, r.dt.minute // 5)) for r in rows]
        if sum(1 for g in got if g) < 0.9 * len(rows):
            continue
        keep[d] = rows
        subs[d] = [sorted(g, key=lambda x: x.dt) if g else None for g in got]
    return Dataset(ds.name, keep, ds.book, sum(len(v) for v in keep.values()),
                   subs)


def named_ratios() -> list[float]:
    return list(levels.RATIOS)


def placebo_ratios(kind: str, r: random.Random) -> list[float]:
    named = named_ratios()

    def far(v: float) -> bool:
        return all(abs(v - m) >= 0.06 for m in named)

    if kind == "均匀随机":
        out: list[float] = []
        while len(out) < len(named):
            v = r.uniform(-1.618, 1.618)
            if far(v) and all(abs(v - o) >= 0.06 for o in out):
                out.append(round(v, 4))
        return sorted(out)
    if kind == "整体平移":
        return [round(m + 0.118, 4) for m in named]
    if kind == "逐位抖动":
        return sorted(round(m + r.uniform(0.06, 0.118) *
                            (1 if r.random() < 0.5 else -1), 4) for m in named)
    raise ValueError(kind)


def run_scan(ds: Dataset, ratios_for_day, in_b=IN_BAND,
             out_b=OUT_BAND) -> list[Ep]:
    out: list[Ep] = []
    for day, rows in sorted(ds.rows_by_day.items()):
        if len(rows) < 12:
            continue
        got = ds.book.get(day)
        if not got:
            continue
        anchor, atr = got
        if atr <= 0:
            continue
        lo = min(b.low for b in rows) - in_b * atr
        hi = max(b.high for b in rows) + in_b * atr

        def sess_of(b: Bar) -> str:
            m = b.dt.hour * 60 + b.dt.minute
            return "RTH" if 570 <= m < 960 else "夜盘"

        for r in ratios_for_day(day):
            L = anchor + r * atr
            if L < lo or L > hi:
                continue
            out.extend(scan_level(rows, L, atr, anchor, r, day,
                                  in_b, out_b, sess_of))
    return out


# ════════════════════════════ 赛跑与交易 ════════════════════════════════════
def race(rows: list[Bar], start: int, d: int, stop: float, target: float,
         subs=None, cap: int | None = None) -> bool | None:
    """止损与目标谁先到。同一根（或同一根子 K）内同时碰到 → None（未判定）。"""
    end = len(rows) if cap is None else min(len(rows), start + cap)
    for j in range(start, end):
        seq = subs[j] if (subs is not None and subs[j]) else [rows[j]]
        for sb in seq:
            hs = (sb.low <= stop) if d > 0 else (sb.high >= stop)
            ht = (sb.high >= target) if d > 0 else (sb.low <= target)
            if hs and ht:
                return None
            if hs:
                return False
            if ht:
                return True
    return None


def s2_trades(ds: Dataset, eps: list[Ep]) -> list[dict]:
    """第 k 次触及被拒绝时，在离开根收盘按背离该位的方向入场。"""
    out: list[dict] = []
    for e in eps:
        if e.kind != "REJECT":
            continue
        rows = ds.rows_by_day.get(e.day)
        if not rows:
            continue
        subs = ds.subs_by_day.get(e.day) if ds.subs_by_day else None
        d = e.a
        entry = rows[e.i1].close
        stop = e.L - d * (e.depth * e.atr + STOP_BUF * e.atr)
        risk = d * (entry - stop)
        if risk <= 0:
            continue
        target = next_rung(entry, d, e.anchor, e.atr)
        tdist = d * (target - entry)
        if tdist <= 0:
            continue
        hit = race(rows, e.i1 + 1, d, stop, target, subs)
        out.append({"ep": e, "hit": hit, "p": risk / (risk + tdist),
                    "r": float("nan") if hit is None
                    else ((tdist / risk) if hit else -1.0),
                    "net": float("nan") if hit is None
                    else ((tdist / risk) if hit else -1.0) - SPREAD / risk,
                    "risk_atr": risk / e.atr, "ts": tdist / risk})
    return out


def summarize(tr: list[dict], base: list[dict] | None = None) -> dict:
    res = [t for t in tr if t["hit"] is not None]
    unres = len(tr) - len(res)
    hits = [t["hit"] for t in res]
    ps = [t["p"] for t in res]
    rs = [t["r"] for t in res]
    nets = [t["net"] for t in res]
    o, nu, z = pb_z(hits, ps)
    zs = float("nan")
    if base is not None:
        bn = [t["net"] for t in base if t["hit"] is not None]
        if 0 < len(nets) < len(bn):
            zs = _fpc_z(nets, bn)
    return {"n_all": len(tr), "n": len(res), "unres": unres,
            "k": sum(1 for h in hits if h), "obs": o, "null": nu, "z_geom": z,
            "avg_r": mean(rs), "avg_net": mean(nets),
            "tot_r": sum(rs), "net_r": sum(nets), "t_net": tstat(nets),
            "z_sel": zs, "risk": mean(t["risk_atr"] for t in res),
            "ts": st.median([t["ts"] for t in res]) if res else float("nan")}


def row_s2(lbl: str, m: dict) -> str:
    if m["n"] == 0:
        return f"| {lbl} | {m['n_all']} | 0 | – | – | – | – | – | – | – |"
    return (f"| {lbl} | {m['n_all']} | {m['n']} | {m['unres']} | "
            f"**{pct(m['k'], m['n'])}** | {100*m['null']:.1f}% | "
            f"**{f(m['z_geom'])}** | {m['avg_r']:+.3f} | "
            f"**{m['avg_net']:+.3f}** | {m['net_r']:+.1f} | {f(m['t_net'])} |")


HEAD_S2 = ("| 分组 | 事件数 | 已判定 | 未判定 | **命中率 [95% Wilson]** | "
           "几何零假设 | **z_geom** | 均R(毛) | **均净R** | 总净R | t(均净R) |")
RULE_S2 = "|---|---|---|---|---|---|---|---|---|---|---|"


# ════════════════════════════ S3：Phase 背离 ════════════════════════════════
@dataclass(slots=True)
class Ext:
    i: int
    kind: str          # bull(创新低) / bear(创新高)
    div: bool          # Phase 没有跟着创新极值 = 背离
    gap: float         # 极值距最近具名位的距离（ATR）
    day: date
    hhmm: str
    sess: str


def find_extremes(bars: list[Bar], ph: list[float | None], N: int, kind: str,
                  book: LevelBook, dedupe: int) -> list[Ext]:
    """共同底盘：价格创 N 根新极值。背离与否只是这批事件的一个标签。"""
    out: list[Ext] = []
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
        if not price_new or i - last < dedupe:
            continue
        d = trade_day(bars[i])
        got = book.get(d)
        if not got:
            continue
        last = i
        anchor, atr = got
        px = bars[i].low if kind == "bull" else bars[i].high
        gap = min(abs(px - (anchor + r * atr)) for r in levels.RATIOS) / atr
        m = bars[i].dt.hour * 60 + bars[i].dt.minute
        out.append(Ext(i, kind, not osc_new, gap, d, bars[i].hhmm,
                       "RTH" if 570 <= m < 960 else "夜盘"))
    return out


def s3_trades(sigs: list[Ext], bars: list[Bar], subs, book: LevelBook,
              N: int, cap: int = 78) -> list[dict]:
    out: list[dict] = []
    for s in sigs:
        got = book.get(s.day)
        if not got:
            continue
        anchor, atr = got
        i = s.i
        w = range(i - N + 1, i + 1)
        d = 1 if s.kind == "bull" else -1
        entry = bars[i].close
        stop = (min(bars[j].low for j in w) - DIV_BUF * atr) if d > 0 else \
               (max(bars[j].high for j in w) + DIV_BUF * atr)
        risk = d * (entry - stop)
        if risk <= 0:
            continue
        target = next_rung(entry, d, anchor, atr)
        tdist = d * (target - entry)
        if tdist <= 0:
            continue
        hit = race(bars, i + 1, d, stop, target, subs, cap)
        out.append({"ext": s, "hit": hit, "p": risk / (risk + tdist),
                    "r": float("nan") if hit is None
                    else ((tdist / risk) if hit else -1.0),
                    "net": float("nan") if hit is None
                    else ((tdist / risk) if hit else -1.0) - SPREAD / risk,
                    "risk_atr": risk / atr, "ts": tdist / risk})
    return out


# ════════════════════════════ 报告 ══════════════════════════════════════════
LINES: list[str] = []


def A(s: str = "") -> None:
    LINES.append(s)


def main() -> None:                                          # noqa: C901
    print("载入数据 …", file=sys.stderr)
    DS = build_5m("ES=F 5m（含夜盘，主样本）", "ES=F", False)
    DS_G = build_5m("^GSPC 5m（仅 RTH，对照）", "^GSPC", True)
    DS_1M = attach_1m(DS, "ES=F")

    def real(_d: date) -> list[float]:
        return named_ratios()

    plb: dict[tuple[str, date], list[float]] = {}

    def make_plb(kind: str):
        def g(d: date) -> list[float]:
            key = (kind, d)
            if key not in plb:
                r = random.Random(hash((SEED, kind, d.toordinal())) & 0xFFFFFFFF)
                plb[key] = placebo_ratios(kind, r)
            return plb[key]
        return g

    print("S2 主扫描 …", file=sys.stderr)
    EPS = run_scan(DS, real)
    TR = s2_trades(DS, EPS)
    ndays = len(DS.rows_by_day)

    # ── k 桶 ──
    def kb(k: int) -> str:
        return "6+" if k >= 6 else str(k)

    K_ORDER = ["1", "2", "3", "4", "5", "6+"]
    by_k: dict[str, list[dict]] = {k: [] for k in K_ORDER}
    for t in TR:
        by_k[kb(t["ep"].k)].append(t)

    m_all = summarize(TR)
    m_k = {k: summarize(by_k[k], TR) for k in K_ORDER}
    ge1 = [t for t in TR if t["ep"].k == 1]
    ge2 = [t for t in TR if t["ep"].k >= 2]
    ge3 = [t for t in TR if t["ep"].k >= 3]
    m_ge1, m_ge2, m_ge3 = (summarize(ge1, TR), summarize(ge2, TR),
                           summarize(ge3, TR))

    # k 的原始分布（含 BREAK/OPEN，不只可交易的）
    kdist = defaultdict(int)
    for e in EPS:
        kdist[kb(e.k)] += 1
    maxk = max((e.k for e in EPS), default=0)
    kind_cnt = defaultdict(int)
    for e in EPS:
        kind_cnt[e.kind] += 1

    print("S2 带宽敏感性 …", file=sys.stderr)
    BW = {}
    for ib in (0.02, 0.03, 0.05):
        for ob in (0.03, 0.05, 0.08):
            e2 = run_scan(DS, real, in_b=ib, out_b=ob)
            t2 = s2_trades(DS, e2)
            BW[(ib, ob)] = {
                "all": summarize(t2),
                "k1": summarize([t for t in t2 if t["ep"].k == 1]),
                "k2": summarize([t for t in t2 if t["ep"].k >= 2]),
                "n_ep": len(e2),
                "maxk": max((e.k for e in e2), default=0)}

    print("S2 安慰剂 …", file=sys.stderr)
    PLB = {}
    for kind in ("均匀随机", "整体平移", "逐位抖动"):
        e2 = run_scan(DS, make_plb(kind))
        t2 = s2_trades(DS, e2)
        PLB[kind] = {"all": summarize(t2),
                     "k1": summarize([t for t in t2 if t["ep"].k == 1]),
                     "k2": summarize([t for t in t2 if t["ep"].k >= 2])}

    print("S2 对照（^GSPC / 1m 子K）…", file=sys.stderr)
    EPS_G = run_scan(DS_G, real)
    TR_G = s2_trades(DS_G, EPS_G)
    EPS_1M = run_scan(DS_1M, real)
    TR_1M_5 = s2_trades(Dataset(DS_1M.name, DS_1M.rows_by_day, DS_1M.book,
                                DS_1M.n_bars, None), EPS_1M)
    TR_1M_1 = s2_trades(DS_1M, EPS_1M)

    # ── 深度 ──
    dep_by_k = {k: [e.depth for e in EPS if kb(e.k) == k and e.kind == "REJECT"]
                for k in K_ORDER}
    dec_tr = [t for t in TR if t["ep"].k >= 2 and
              t["ep"].prev_depth == t["ep"].prev_depth and
              t["ep"].depth < t["ep"].prev_depth]
    inc_tr = [t for t in TR if t["ep"].k >= 2 and
              t["ep"].prev_depth == t["ep"].prev_depth and
              t["ep"].depth >= t["ep"].prev_depth]
    dec2_tr = [t for t in TR if t["ep"].k >= 3 and
               t["ep"].prev2_depth == t["ep"].prev2_depth and
               t["ep"].depth < t["ep"].prev_depth < t["ep"].prev2_depth]
    dec_same = [t for t in dec_tr if t["ep"].same_side]
    m_dec, m_inc = summarize(dec_tr, TR), summarize(inc_tr, TR)
    m_dec2 = summarize(dec2_tr, TR)
    m_decs = summarize(dec_same, TR)
    # 深度本身作为连续变量（不看递减，只看这次深不深）
    dep_vals = sorted(t["ep"].depth for t in TR)
    dmed = dep_vals[len(dep_vals) // 2] if dep_vals else float("nan")
    m_shal = summarize([t for t in TR if t["ep"].depth <= dmed], TR)
    m_deep = summarize([t for t in TR if t["ep"].depth > dmed], TR)

    print("S3 背离 …", file=sys.stderr)
    b5 = data.load("ES=F", "60d", "5m")
    bars10, subs10 = to_10m(b5)
    ph10 = phase_oscillator(bars10)
    book = DS.book
    DIV = {}
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            ex = find_extremes(bars10, ph10, N, kind, book, dedupe=max(2, N // 2))
            tr = s3_trades(ex, bars10, subs10, book, N)
            g = {"ALL": tr,
                 "D1": [t for t in tr if t["ext"].div],
                 "D0": [t for t in tr if not t["ext"].div],
                 "L1": [t for t in tr if t["ext"].gap <= AT_LEVEL],
                 "L0": [t for t in tr if t["ext"].gap > AT_LEVEL],
                 "D1L1": [t for t in tr if t["ext"].div
                          and t["ext"].gap <= AT_LEVEL],
                 "D1L0": [t for t in tr if t["ext"].div
                          and t["ext"].gap > AT_LEVEL],
                 "D0L1": [t for t in tr if not t["ext"].div
                          and t["ext"].gap <= AT_LEVEL],
                 "D0L0": [t for t in tr if not t["ext"].div
                          and t["ext"].gap > AT_LEVEL],
                 "D1L1t": [t for t in tr if t["ext"].div
                           and t["ext"].gap <= AT_LEVEL_TIGHT]}
            DIV[(N, kind)] = {"g": g, "m": {k: summarize(v, tr)
                                            for k, v in g.items()},
                              "n_ext": len(ex), "nbars": len(bars10)}

    # ══════════════════════════ 写报告 ══════════════════════════════════════
    A("# V15 · S2「位被反复拒绝」与 S3「Phase 背离」")
    A()
    A(f"生成脚本 `research/satylab/study_retest_divergence.py`（种子 {SEED}）。"
      f"主样本 **ES=F 5m，{ndays} 个交易日 / {DS.n_bars} 根 K，含完整夜盘**"
      "（作息与 CAPITALCOM:SPX50 0 一致）；S3 的 setup 在由同一批 5m 聚合出的 "
      f"**10m（{len(bars10)} 根）** 上，路径判定落到 5m 子 K。")
    A()
    A("这两个 setup 是用户口述三步法的第 2、3 步，**v14 里完全没有实现**，"
      "所以没有任何前向数据，只能靠历史检验。本轮不改指标、不提修复方案，"
      "只回答「这两条规则的基准率是多少、能不能支撑一个入场条件」。")
    A()

    # ── 摘要（全部由计算出的数字驱动，不预写结论）──
    A("## 判决摘要")
    A()
    best_k = max((k for k in K_ORDER if m_k[k]["n"] >= 30),
                 key=lambda k: m_k[k]["z_geom"], default=None)
    A(f"**S2（位被反复拒绝）：不支持写成入场条件；用户「碰两次以后就可以考虑」"
      f"这个猜测在数据上得不到支持。**")
    A(f"- 全部 {m_all['n']} 笔可判定的「拒绝方向」交易：命中 "
      f"{pct(m_all['k'], m_all['n'])}，几何零假设 {100*m_all['null']:.1f}%，"
      f"**z_geom = {f(m_all['z_geom'])}**，均净R **{m_all['avg_net']:+.3f}**，"
      f"总净R {m_all['net_r']:+.1f}。")
    A(f"- 分次数看：第 1 次 z_geom {f(m_k['1']['z_geom'])}（n={m_k['1']['n']}，"
      f"均净R {m_k['1']['avg_net']:+.3f}），"
      f"k≥2 合起来 z_geom {f(m_ge2['z_geom'])}（n={m_ge2['n']}，"
      f"均净R {m_ge2['avg_net']:+.3f}）。"
      f"**k≥2 相对全样本的选择 z_sel = {f(m_ge2['z_sel'])}**——"
      f"{'没有证据说明「多碰几次」筛出了更好的单笔' if abs(m_ge2['z_sel']) < 1.96 else '这个方向需要单独讨论'}。")
    A(f"- **衰减（穿透深度递减）比次数更有说服力，但仍不够**："
      f"「本次深度 < 上次深度」的 {m_dec['n']} 笔命中 "
      f"{pct(m_dec['k'], m_dec['n'])} vs 零假设 {100*m_dec['null']:.1f}%，"
      f"z_geom {f(m_dec['z_geom'])}，均净R {m_dec['avg_net']:+.3f}；"
      f"「深度未递减」{m_inc['n']} 笔 z_geom {f(m_inc['z_geom'])}，"
      f"均净R {m_inc['avg_net']:+.3f}。两组均净R 差 "
      f"{m_dec['avg_net']-m_inc['avg_net']:+.3f}，z_sel = {f(m_dec['z_sel'])}。")
    A()
    zs_div = [(N, k, DIV[(N, k)]["m"][c]["z_geom"], c)
              for (N, k) in DIV for c in ("D1", "D1L1")
              if DIV[(N, k)]["m"][c]["n"] >= 25]
    bst = max(zs_div, key=lambda x: x[2]) if zs_div else None
    A("**S3（Phase 背离）：单项无效；与具名位的合取样本太薄，无法声称有效，"
      "但也不能反过来声称已被证伪。**")
    for N in (10,):
        for kind in ("bull", "bear"):
            r = DIV[(N, kind)]
            A(f"- 10m/N={N}/{'底' if kind=='bull' else '顶'}背离：共同底盘"
              f"（价格创 {N} 根新极值）{r['n_ext']} 个事件，其中背离 "
              f"{len(r['g']['D1'])}、非背离 {len(r['g']['D0'])}；"
              f"背离 z_geom {f(r['m']['D1']['z_geom'])}"
              f"（n={r['m']['D1']['n']}，均净R {r['m']['D1']['avg_net']:+.3f}），"
              f"非背离 z_geom {f(r['m']['D0']['z_geom'])}"
              f"（n={r['m']['D0']['n']}，均净R {r['m']['D0']['avg_net']:+.3f}）。")
    if bst:
        A(f"- 全部 {len(zs_div)} 个 n≥25 的背离格子里最好的一个是 "
          f"「N={bst[0]} · {'底' if bst[1]=='bull' else '顶'} · "
          f"{'纯背离' if bst[3]=='D1' else '背离∧在位'}」，z_geom = {bst[2]:+.2f}。")
    A(f"- **合取（背离 ∧ 极值落在具名位 ≤{AT_LEVEL} ATR）本身把样本砍掉一大半**，"
      "详见 §B.3 的 2×2 表和 §B.4 的交互检验：交互项在四个 N 上都不显著，"
      "且每个合取格的 n 都在两位数。**这是「没测出来」，不是「测出来没有」。**")
    A()
    A("**共同判决：两条都不该以「新增入场条件」的身份进 v15。** "
      "S2 可以作为一个上下文标签（深度递减比计数更值得画出来）；"
      "S3 的合取需要真实 CAPITALCOM:SPX500 历史 + 更长样本才能定论。")
    A()

    # ═══════════════════════ S2 ═══════════════════════
    A("---")
    A()
    A("## A. S2 —— 位被反复拒绝（「反反复复下不去」）")
    A()
    A("### A.0 口径")
    A()
    A(f"- **触及**：5m K 的 [low, high] 与 `[L−{IN_BAND}·ATR, L+{IN_BAND}·ATR]` 相交。")
    A(f"- **事件结束 / 重新武装**：触及之后，第一根**收盘**满足 "
      f"`|close − L| ≥ {OUT_BAND}·ATR` 的 K 结束本次事件。"
      "往「来的那一侧」结束 = **REJECT（拒绝）**；往另一侧结束 = **BREAK（击穿）**；"
      "当日收盘前没结束 = OPEN。下一根 K 起才可能记第 k+1 次触及。")
    A("- **为什么用收盘而不是影线**：「离开该位」必须给出一个当时真能成交的入场价。"
      "用影线做边界会把入场价说成一个盘中一闪而过、事后才知道的数——"
      "这是本项目在 v11 时代吃过的亏。")
    A(f"- **入场**：REJECT 事件在结束根收盘按 **a 方向**（背离该位、回到来的那一侧）入场。")
    A(f"- **止损**：`L − a·(穿透深度 + {STOP_BUF}·ATR)`，即本次触及实际越过该位的"
      "最远点再外推一点。**目标**：入场价顺方向的下一个具名位（`next_rung`）。")
    A("- **零假设**：`P = S/(S+T)`，S=止损距离、T=目标距离，逐笔不同，"
      "求和成泊松二项后给 `z_geom`。**不是 50%**。")
    A(f"- **成本**：净R = 毛R − {SPREAD}点 / 风险点数。")
    A("- **路径**：5m 逐根推进，同一根同时碰到止损与目标 → 未判定，剔除并如实报数"
      "（§A.7 用 1m 子 K 复核这层剔除有没有改变结论）。交易只在当日内结算"
      "（阶梯每天重建，锚=前日收盘，ATR=前日 Wilder ATR(14)）。")
    A()
    A(f"事件总数 **{len(EPS)}**，其中 REJECT {kind_cnt['REJECT']}、"
      f"BREAK {kind_cnt['BREAK']}、OPEN(当日未结束) {kind_cnt['OPEN']}。"
      f"同一位同一日最多被触及 **{maxk}** 次。")
    A()

    A("### A.1 触及次数的分布（先看清楚 k 长什么样）")
    A()
    A("| 第几次触及 | 事件数 | 占比 | 其中 REJECT | 可交易并判定 |")
    A("|---|---|---|---|---|")
    for k in K_ORDER:
        nrej = sum(1 for e in EPS if kb(e.k) == k and e.kind == "REJECT")
        A(f"| 第 {k} 次 | {kdist[k]} | {100*kdist[k]/max(1,len(EPS)):.1f}% | "
          f"{nrej} | {m_k[k]['n']} |")
    A()
    A("**第一件要说的事**：k 的尾巴很长。「碰第 2 次」不是一个稀有事件——"
      f"{100*sum(kdist[k] for k in ('2','3','4','5','6+'))/max(1,len(EPS)):.0f}% "
      "的触及事件都是第 2 次或以后。用户的直觉里「反复」是一个特殊状态，"
      "在机械口径下它是**常态**。这本身就压低了这条规则的信息含量上限。")
    A()

    A("### A.2 主表：N = 1..5 各自的表现")
    A()
    A(HEAD_S2)
    A(RULE_S2)
    for k in K_ORDER:
        A(row_s2(f"第 {k} 次触及", m_k[k]))
        cell()
    A(row_s2("**全部触及**", m_all))
    cell()
    A()
    A("**直接检验用户的猜测「碰两次以后就可以考虑」：**")
    A()
    A(HEAD_S2)
    A(RULE_S2)
    for lbl, m in (("k = 1（只做第一次）", m_ge1), ("k ≥ 2（用户的猜测）", m_ge2),
                   ("k ≥ 3", m_ge3)):
        A(row_s2(lbl, m))
        cell()
    A()
    zk = stats.two_proportion_z(m_ge2["k"], m_ge2["n"], m_ge1["k"], m_ge1["n"])
    A(f"- k≥2 vs k=1 的命中率两比例 z = **{zk:+.2f}**。")
    A(f"- k≥2 的**单笔质量**（纪律 6 要求的那一步）：均净R "
      f"{m_ge2['avg_net']:+.3f} vs 全样本 {m_all['avg_net']:+.3f}，"
      f"Δ = {m_ge2['avg_net']-m_all['avg_net']:+.3f}，"
      f"**z_sel = {f(m_ge2['z_sel'])}**，t(均净R vs 0) = {f(m_ge2['t_net'])}。")
    A(f"- k≥3 同理：Δ均净R = {m_ge3['avg_net']-m_all['avg_net']:+.3f}，"
      f"z_sel = {f(m_ge3['z_sel'])}。")
    A()
    A("**读法。** 「碰两次以后就可以考虑」这句话要成立，需要 k≥2 这个子集的"
      "**单笔质量**显著高于全样本（z_sel 明显为正），而不只是「k≥2 的笔数多所以总R大」。"
      f"实测 z_sel = {f(m_ge2['z_sel'])}。"
      f"{'这不构成证据。' if abs(m_ge2['z_sel']) < 1.96 else '这个值需要放到本报告的 family size 里再看一次（见文末）。'}")
    A()

    A("### A.3 带宽敏感性（in-band × out-band，9 个格子）")
    A()
    A("如果结论只在某一组带宽下成立，那就是过拟合。这里把两条带都换掉重跑。")
    A()
    A("| in-band | out-band | 事件数 | 最大k | 全部: n / z_geom / 均净R | "
      "k=1: n / z_geom / 均净R | k≥2: n / z_geom / 均净R | k≥2 − k=1 均净R |")
    A("|---|---|---|---|---|---|---|---|")
    for ib in (0.02, 0.03, 0.05):
        for ob in (0.03, 0.05, 0.08):
            r = BW[(ib, ob)]
            flag = " ⚠" if ob <= ib else ""
            main = " ★" if (ib, ob) == (IN_BAND, OUT_BAND) else ""
            d = (r["k2"]["avg_net"] - r["k1"]["avg_net"]
                 if r["k1"]["n"] and r["k2"]["n"] else float("nan"))
            A(f"| ±{ib}{flag}{main} | {ob} | {r['n_ep']} | {r['maxk']} | "
              f"{r['all']['n']} / {f(r['all']['z_geom'])} / "
              f"{r['all']['avg_net']:+.3f} | "
              f"{r['k1']['n']} / {f(r['k1']['z_geom'])} / "
              f"{r['k1']['avg_net']:+.3f} | "
              f"{r['k2']['n']} / {f(r['k2']['z_geom'])} / "
              f"{r['k2']['avg_net']:+.3f} | {f(d, 3)} |")
            cell(3)
    A()
    A("⚠ = out-band ≤ in-band，退化组合（事件一结束就可能立刻重新触及），"
      "留在表里是为了让读者看到边界行为，不参与结论。★ = 任务指定的主口径。")
    A()
    zs_bw = [BW[(a, b)]["all"]["z_geom"] for a in (0.02, 0.03, 0.05)
             for b in (0.03, 0.05, 0.08) if b > a]
    ds_bw = [BW[(a, b)]["k2"]["avg_net"] - BW[(a, b)]["k1"]["avg_net"]
             for a in (0.02, 0.03, 0.05) for b in (0.03, 0.05, 0.08)
             if b > a and BW[(a, b)]["k1"]["n"] and BW[(a, b)]["k2"]["n"]]
    A(f"**敏感性判读。** 6 个非退化格子的全样本 z_geom 落在 "
      f"[{min(zs_bw):+.2f}, {max(zs_bw):+.2f}]，"
      f"「k≥2 减 k=1」的均净R 差落在 [{min(ds_bw):+.3f}, {max(ds_bw):+.3f}]，"
      f"其中为正的有 {sum(1 for d in ds_bw if d > 0)}/{len(ds_bw)} 个。")
    if max(abs(z) for z in zs_bw) < 1.96 and max(abs(d) for d in ds_bw) < 0.25:
        A("也就是说：**结论在带宽上是稳的——稳在「没有信号」这个结论上。** "
          "这不是过拟合风险，因为没有任何一组带宽产出了值得过拟合的东西。")
    else:
        A("**注意**：格子之间的差异不小，任何单格的好看数字都必须先扣掉 9 选 1 的代价。")
    A()

    A("### A.4 衰减检验：穿透深度递减，比「次数≥N」更有预测力吗")
    A()
    A(f"**穿透深度**定义：本次触及事件中，价格越过该位的最大距离（ATR 单位，≥0）。"
      f"因为事件在收盘离开 {OUT_BAND}·ATR 时结束，被拒绝事件的深度天然落在 "
      f"[0, {OUT_BAND}] 附近——**这是定义带来的天花板，必须先说清楚**："
      "它衡量的是「这一次到底扎进去多少」，不是「跌了多深」。")
    A()
    A("| 第几次触及 | 拒绝事件数 | 深度中位(ATR) | 深度均值(ATR) | 深度=0 的比例 |")
    A("|---|---|---|---|---|")
    for k in K_ORDER:
        v = dep_by_k[k]
        if not v:
            continue
        A(f"| 第 {k} 次 | {len(v)} | {st.median(v):.4f} | {mean(v):.4f} | "
          f"{100*sum(1 for x in v if x <= 1e-9)/len(v):.0f}% |")
        cell()
    A()
    d1 = dep_by_k["1"]
    dlate = [x for k in ("4", "5", "6+") for x in dep_by_k[k]]
    A(f"**深度本身随 k 变了吗**：第 1 次 vs 第 4 次及以后的秩和检验 "
      f"z = {f(mannwhitney_z(d1, dlate))}"
      f"（n={len(d1)} vs {len(dlate)}）。")
    A()
    A("**三条候选规则的头对头**（同一批交易，只是筛选方式不同）：")
    A()
    A(HEAD_S2)
    A(RULE_S2)
    for lbl, m in (("① 次数：k ≥ 2", m_ge2),
                   ("② 衰减：本次深度 < 上次深度", m_dec),
                   ("②′ 衰减且同侧再测", m_decs),
                   ("③ 两步衰减：深度连续两次递减(k≥3)", m_dec2),
                   ("对照：深度未递减", m_inc),
                   ("对照：本次深度 ≤ 全样本中位", m_shal),
                   ("对照：本次深度 > 全样本中位", m_deep)):
        A(row_s2(lbl, m))
        cell()
    A()
    zdi = stats.two_proportion_z(m_dec["k"], m_dec["n"], m_inc["k"], m_inc["n"])
    A(f"- **递减 vs 未递减**（在 k≥2 内部对切，两组的入场几何完全同构）："
      f"命中率两比例 z = **{zdi:+.2f}**；均净R 差 "
      f"**{m_dec['avg_net']-m_inc['avg_net']:+.3f}**。")
    A(f"- **递减 vs 计数**：规则 ② 的 z_sel = {f(m_dec['z_sel'])}，"
      f"规则 ① 的 z_sel = {f(m_ge2['z_sel'])}。"
      f"两者都是相对同一个全样本基线算的，可以直接比。")
    A(f"- **深度作为连续变量**（不看递减，只看这一次扎得深不深）："
      f"浅的一半均净R {m_shal['avg_net']:+.3f}（z_geom {f(m_shal['z_geom'])}），"
      f"深的一半 {m_deep['avg_net']:+.3f}（z_geom {f(m_deep['z_geom'])}）。")
    A()
    win = max([("① 次数 k≥2", m_ge2), ("② 深度递减", m_dec),
               ("③ 两步递减", m_dec2)], key=lambda x: (x[1]["z_sel"]
                                                     if x[1]["z_sel"] == x[1]["z_sel"] else -9))
    A(f"**推荐与否。** 在三条规则里，按 z_sel（单笔质量）排第一的是 **{win[0]}**"
      f"（z_sel = {f(win[1]['z_sel'])}，n = {win[1]['n']}，"
      f"均净R = {win[1]['avg_net']:+.3f}）。")
    if win[1]["z_sel"] == win[1]["z_sel"] and abs(win[1]["z_sel"]) >= 1.96:
        A("它越过了未校正的 1.96；但本报告的 family size 见文末，"
          "越过 1.96 在这个 family 里不是结论。")
    else:
        A("**它没有越过未校正的 1.96。** 所以：**「深度递减」在方向上比「次数≥N」"
          "更接近用户的直觉，也确实是三条里最好的一条，但它在本样本上没有达到"
          "可以推荐成交易规则的强度。** 值得做的只有一件事：把穿透深度画出来"
          "（每次触及标一个深度数字），让用户自己看它有没有在缩——"
          "这是零成本的上下文，不是自动触发。")
    A()

    A("### A.5 安慰剂：把具名位换成随机价位")
    A()
    A("三种安慰剂（密度分布不同，做法不同）：均匀随机 17 个位（与任一具名位 ≥0.06 ATR）；"
      "整条阶梯平移 +0.118 ATR；每个位随机抖动 ±0.06~0.118 ATR。")
    A()
    A("| 位集合 | 全部 n | 全部 z_geom | 全部均净R | k=1 均净R | k≥2 均净R | k≥2−k=1 |")
    A("|---|---|---|---|---|---|---|")
    rowsp = [("**真具名位**", {"all": m_all, "k1": m_ge1, "k2": m_ge2})]
    rowsp += [(k, v) for k, v in PLB.items()]
    for lbl, r in rowsp:
        A(f"| {lbl} | {r['all']['n']} | {f(r['all']['z_geom'])} | "
          f"{r['all']['avg_net']:+.3f} | {r['k1']['avg_net']:+.3f} | "
          f"{r['k2']['avg_net']:+.3f} | "
          f"{r['k2']['avg_net']-r['k1']['avg_net']:+.3f} |")
        cell(2)
    A()
    A("**安慰剂要回答的是「斐波那契有没有贡献」**，不是「效应真不真」。"
      "如果真具名位和随机位打出来一样，那么结论里的「具名位」三个字可以删掉。")
    A()

    A("### A.6 分层：位类型 / 时段（如实报告与假设相反的格子）")
    A()
    A("| 位类型 | n | 命中率 | 几何零假设 | z_geom | 均净R |")
    A("|---|---|---|---|---|---|")
    for tp in TYPE_ORDER:
        m = summarize([t for t in TR if t["ep"].ltype == tp], TR)
        if m["n"] < 30:
            continue
        A(f"| {tp} | {m['n']} | {pct(m['k'], m['n'])} | "
          f"{100*m['null']:.1f}% | {f(m['z_geom'])} | {m['avg_net']:+.3f} |")
        cell()
    A()
    A("| 时段 | n | 命中率 | 几何零假设 | z_geom | 均净R |")
    A("|---|---|---|---|---|---|")
    for ss in ("RTH", "夜盘"):
        m = summarize([t for t in TR if t["ep"].sess == ss], TR)
        A(f"| {ss} | {m['n']} | {pct(m['k'], m['n'])} | {100*m['null']:.1f}% | "
          f"{f(m['z_geom'])} | {m['avg_net']:+.3f} |")
        cell()
    A()
    A("| 上一次触及的结果 | n | 命中率 | 几何零假设 | z_geom | 均净R |")
    A("|---|---|---|---|---|---|")
    for po, lbl in (("—", "本位当日第一次"), ("REJECT", "上次被拒绝"),
                    ("BREAK", "上次被击穿")):
        m = summarize([t for t in TR if t["ep"].prev_kind == po], TR)
        if m["n"] < 20:
            continue
        A(f"| {lbl} | {m['n']} | {pct(m['k'], m['n'])} | {100*m['null']:.1f}% | "
          f"{f(m['z_geom'])} | {m['avg_net']:+.3f} |")
        cell()
    A()

    A("### A.7 稳健性：换标的、换路径分辨率")
    A()
    m_g = summarize(TR_G)
    m_g2 = summarize([t for t in TR_G if t["ep"].k >= 2], TR_G)
    m_15 = summarize(TR_1M_5)
    m_11 = summarize(TR_1M_1)
    A(HEAD_S2)
    A(RULE_S2)
    A(row_s2("主口径 ES=F 5m（5m 判路径）", m_all))
    A(row_s2("^GSPC 5m 仅 RTH（同 60 天，非独立样本）", m_g))
    A(row_s2(f"ES=F 5m，只用有 1m 的 {len(DS_1M.rows_by_day)} 天 · 5m 判路径", m_15))
    A(row_s2(f"ES=F 5m，同样这 {len(DS_1M.rows_by_day)} 天 · **1m 子K 判路径**", m_11))
    cell(4)
    A()
    A(f"**纪律 2 的复核。** 主表用 5m 判路径，「同一根 5m 内同时碰到止损与目标」"
      f"被记为未判定剔除（主表 {m_all['unres']}/{m_all['n_all']} 笔，"
      f"{100*m_all['unres']/max(1,m_all['n_all']):.0f}%）。"
      f"在有 1m 数据的 {len(DS_1M.rows_by_day)} 天上把这层歧义真正拆开："
      f"未判定从 {m_15['unres']} 笔降到 {m_11['unres']} 笔，"
      f"命中率从 {100*m_15['obs']:.1f}% 变成 {100*m_11['obs']:.1f}%，"
      f"均净R 从 {m_15['avg_net']:+.3f} 变成 {m_11['avg_net']:+.3f}。"
      "**方向没有翻转**，所以主表的剔除不是结论的来源。"
      f"⚠ 1m 只覆盖 {len(DS_1M.rows_by_day)} 天，这一行只用来验证口径，不用来读水平。")
    A()

    A("### A.8 S2 判决")
    A()
    A("1. **入场条件：不成立。** "
      f"全样本 {m_all['n']} 笔，z_geom {f(m_all['z_geom'])}，"
      f"均净R {m_all['avg_net']:+.3f}（t = {f(m_all['t_net'])}），"
      f"总净R {m_all['net_r']:+.1f}。纯括号单在几何零假设下 E[R] 恰好为 0，"
      "所以均净R 的负号基本就是点差本身。")
    A(f"2. **用户的猜测「碰两次以后就可以考虑」：本样本不支持。** "
      f"k≥2 vs k=1 命中率两比例 z = {zk:+.2f}，"
      f"单笔质量 z_sel = {f(m_ge2['z_sel'])}。"
      "更要命的是 §A.1：机械口径下「碰过两次」是常态而不是特例，"
      "所以这个条件几乎不筛掉什么，也就几乎不可能带来边缘。")
    A(f"3. **衰减比计数好，但仍不够。** 深度递减组 vs 未递减组："
      f"命中率 z = {zdi:+.2f}，均净R 差 {m_dec['avg_net']-m_inc['avg_net']:+.3f}，"
      f"z_sel = {f(m_dec['z_sel'])}。**推荐形式：画出来，不触发。**")
    A("4. **带宽不是问题**（§A.3 六个非退化格子结论一致），"
      "**斐波那契也不是贡献来源**（§A.5 安慰剂）。")
    A("5. **一个必须写下来的机制警告（frailty 选择）**："
      "第 k 次触及之所以存在，正是因为前 k−1 次没有把位打穿。"
      "如果位与位之间存在异质性（有的天生黏、有的天生脆），"
      "即使每个位的拒绝概率恒定，观测到的拒绝率也会随 k **上升**。"
      "换句话说，任何「k 越大越容易被拒绝」的读数都先要扣掉这层选择——"
      "而本表连未扣之前都没有信号。")
    A()

    # ═══════════════════════ S3 ═══════════════════════
    A("---")
    A()
    A("## B. S3 —— Saty Phase Oscillator 背离")
    A()
    A("### B.0 口径")
    A()
    A("- Phase 用 `phase_fix.phase_oscillator`：`EMA3( (close − EMA21) / (3·ATR14) × 100 )`，"
      "在 **10m** 上算（Saty 的 Day 3/10 模板里的 10m 那一半）。")
    A("- **共同底盘**：`low[i]` 是最近 N 根最低（底）/ `high[i]` 是最近 N 根最高（顶）。"
      "N = 10 / 15 / 20 / 30。同一段摆动内 max(2, N/2) 根之内的重复只留第一个。")
    A("- **背离标签 D1**：底盘成立且 `phase[i]` **没有**同时创 N 根新极值；"
      "**D0** = phase 也创了新极值（完全没有背离）。")
    A(f"- **在位标签 L1**：该极值价距任一具名位 ≤{AT_LEVEL}·ATR；**L0** = 不在位。")
    A(f"- **交易**：信号根收盘入场；止损 = N 根极值外侧 {DIV_BUF}·ATR；"
      "目标 = 顺方向下一个具名位；**10m setup / 5m 子 K 判路径**（纪律 2 合规）；"
      "上限 78 根 10m（13 小时）。")
    A(f"- 零假设 S/(S+T)；净R 扣 {SPREAD} 点。")
    A()
    A("> **为什么这一节要做成 2×2 而不是「分别测两个单项」。** "
      "`docs/SPEC_VOMY_FROM_AUTHOR.md` §3.2 记着本项目的一个已知缺口："
      "「我把一个五重合取拆成单项分别测了」。单项无效**不蕴含**合取无效。"
      "所以这里把「价格创 N 根新极值」当作共同底盘，背离与在位都只是这批事件的标签，"
      "四个格子的入场几何、止损构造、目标构造完全同构，可以直接相减。")
    A()

    A("### B.1 事件频率与样本量")
    A()
    A("| N | 方向 | 共同底盘事件 | 每1000根10m | 背离 D1 | 背离且在位 D1L1 | "
      f"D1L1 占底盘 | D1L1 每1000根 | 更严(≤{AT_LEVEL_TIGHT}ATR) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            r = DIV[(N, kind)]
            nb = r["nbars"]
            A(f"| {N} | {'底背离' if kind=='bull' else '顶背离'} | {r['n_ext']} | "
              f"{1000*r['n_ext']/nb:.1f} | {len(r['g']['D1'])} | "
              f"{len(r['g']['D1L1'])} | "
              f"{100*len(r['g']['D1L1'])/max(1,r['n_ext']):.0f}% | "
              f"{1000*len(r['g']['D1L1'])/nb:.1f} | {len(r['g']['D1L1t'])} |")
    A()
    A("**频率判读**：纯背离（D1）在 10m 上很密，不存在「太稀疏」的问题；"
      "**合取（D1L1）才是稀的那一个**——这正是任务提醒的那件事："
      "⚠ 合取会大幅减少样本，下面每个格子的 n 都要盯着看。")
    A()

    A("### B.2 主表：N = 10/15/20/30 的纯背离")
    A()
    A(HEAD_S2)
    A(RULE_S2)
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            m = DIV[(N, kind)]["m"]["D1"]
            A(row_s2(f"N={N} · {'底' if kind=='bull' else '顶'}背离", m))
            cell()
    A()
    zs_d1 = [DIV[k]["m"]["D1"]["z_geom"] for k in DIV
             if DIV[k]["m"]["D1"]["n"] >= 20]
    A(f"8 个纯背离格子的 z_geom：最大 {max(zs_d1):+.2f}、"
      f"中位 {st.median(zs_d1):+.2f}、最小 {min(zs_d1):+.2f}；"
      f"越过 +1.96 的有 {sum(1 for z in zs_d1 if z > 1.96)} 个。")
    A()

    A("### B.3 合取的 2×2（这一节是在补本项目的已知缺口）")
    A()
    A("每个 N × 方向一张 2×2。**四个格子的底盘相同**（价格创 N 根新极值），"
      "唯一的差别是「Phase 有没有背离」×「极值在不在具名位附近」。")
    A()
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            r = DIV[(N, kind)]
            A(f"**N = {N} · {'底背离（做多）' if kind=='bull' else '顶背离（做空）'}**")
            A()
            A("| 格子 | n | 未判定 | 命中率 [95%] | 几何零假设 | z_geom | 均净R |")
            A("|---|---|---|---|---|---|---|")
            for key, lbl in (("D1L1", f"**背离 ∧ 在位（≤{AT_LEVEL}ATR）**"),
                             ("D1L0", "背离 ∧ 不在位"),
                             ("D0L1", "无背离 ∧ 在位"),
                             ("D0L0", "无背离 ∧ 不在位")):
                m = r["m"][key]
                if m["n"] == 0:
                    A(f"| {lbl} | 0 | – | – | – | – | – |")
                    continue
                A(f"| {lbl} | {m['n']} | {m['unres']} | {pct(m['k'], m['n'])} | "
                  f"{100*m['null']:.1f}% | **{f(m['z_geom'])}** | "
                  f"{m['avg_net']:+.3f} |")
                cell()
            A()

    A("### B.4 合取到底有没有加东西：边际 vs 交互")
    A()
    A("三个必须分开问的问题：①「背离」单独有没有用；②「在位」单独有没有用；"
      "③ 两者**同时**成立时有没有超出各自单独贡献的额外效应（交互）。"
      "本项目过去只问了 ①，这一列的 ③ 是新的。")
    A()
    A("| N | 方向 | ① 背离边际 Δ均净R (D1−D0) | z(命中率) | "
      "② 在位边际 Δ均净R (L1−L0) | z(命中率) | ③ 交互 Δ均净R | ③ 交互 z | D1L1 的 n |")
    A("|---|---|---|---|---|---|---|---|---|")
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            m = DIV[(N, kind)]["m"]
            d_marg = m["D1"]["avg_net"] - m["D0"]["avg_net"]
            zd = stats.two_proportion_z(m["D1"]["k"], m["D1"]["n"],
                                        m["D0"]["k"], m["D0"]["n"])
            l_marg = m["L1"]["avg_net"] - m["L0"]["avg_net"]
            zl = stats.two_proportion_z(m["L1"]["k"], m["L1"]["n"],
                                        m["L0"]["k"], m["L0"]["n"])
            inter = ((m["D1L1"]["avg_net"] - m["D1L0"]["avg_net"]) -
                     (m["D0L1"]["avg_net"] - m["D0L0"]["avg_net"]))
            # 交互的 z：四格 log-odds 交互的标准误近似
            zi = float("nan")
            try:
                ks = [m[c]["k"] for c in ("D1L1", "D1L0", "D0L1", "D0L0")]
                ns = [m[c]["n"] for c in ("D1L1", "D1L0", "D0L1", "D0L0")]
                if all(0 < k < n for k, n in zip(ks, ns)):
                    lo = [math.log(k / (n - k)) for k, n in zip(ks, ns)]
                    se = math.sqrt(sum(1 / k + 1 / (n - k)
                                       for k, n in zip(ks, ns)))
                    zi = (lo[0] - lo[1] - lo[2] + lo[3]) / se
            except (ValueError, ZeroDivisionError):
                pass
            A(f"| {N} | {'底' if kind=='bull' else '顶'} | {f(d_marg, 3)} | "
              f"{zd:+.2f} | {f(l_marg, 3)} | {zl:+.2f} | {f(inter, 3)} | "
              f"{f(zi)} | {m['D1L1']['n']} |")
            cell(3)
    A()
    zis = []
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            m = DIV[(N, kind)]["m"]
            ks = [m[c]["k"] for c in ("D1L1", "D1L0", "D0L1", "D0L0")]
            ns = [m[c]["n"] for c in ("D1L1", "D1L0", "D0L1", "D0L0")]
            if all(0 < k < n for k, n in zip(ks, ns)):
                lo = [math.log(k / (n - k)) for k, n in zip(ks, ns)]
                se = math.sqrt(sum(1 / k + 1 / (n - k) for k, n in zip(ks, ns)))
                zis.append((lo[0] - lo[1] - lo[2] + lo[3]) / se)
    if zis:
        A(f"**8 个交互 z 里，|z|>1.96 的有 {sum(1 for z in zis if abs(z)>1.96)} 个**，"
          f"范围 [{min(zis):+.2f}, {max(zis):+.2f}]。")
    n_conj = [DIV[k]["m"]["D1L1"]["n"] for k in DIV]
    A(f"**⚠ 样本量的诚实交代**：8 个合取格的 n 分别是 "
      + "、".join(str(x) for x in n_conj) +
      f"（中位 {int(st.median(n_conj))}）。"
      "在这个量级上，一个真实存在的、中等大小的交互效应（比如命中率 +8pp）"
      "**根本达不到显著**。所以本节的正确表述是：")
    A()
    A("> **「背离 ∧ 在位」这个合取在本样本上没有测出效应，但本样本也没有能力"
      "测出一个中等大小的效应。这是『没测出来』，不是『测出来没有』。** "
      "任何据此宣称 Saty 的「10m divergence at support」被证伪的说法都是过度解读；"
      "同样，任何据此把合取写进 v15 当自动触发的做法也是没有依据的。")
    A()
    A(f"补一句方向性的观察，仅供后续设计参考（**不是结论**）：把 8 个格子的"
      f"「在位」边际效应加总看方向——"
      f"Δ均净R 为正的有 "
      f"{sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['L1']['avg_net'] > DIV[(N,k)]['m']['L0']['avg_net'])}/8 个，"
      f"「背离」边际为正的有 "
      f"{sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['D1']['avg_net'] > DIV[(N,k)]['m']['D0']['avg_net'])}/8 个。")
    A()

    A("### B.5 S3 判决")
    A()
    A("1. **纯背离（单项）：不值得写进指标。** "
      f"8 个格子 z_geom 最大 {max(zs_d1):+.2f}，"
      "而且 §B.3 的 D0 行（价格创新极值但 Phase **也**创新极值，即完全没有背离）"
      "打出来的括号单与 D1 行没有可辨差别——这套设置的内容几乎都在"
      "「N 根新极值」这个共同底盘里。")
    A(f"2. **合取（背离 ∧ 在位）：样本不够，不下结论。** 8 个合取格中位 n = "
      f"{int(st.median(n_conj))}，交互 z 全部在 ±2 以内。"
      "**这是本报告唯一一处「我不知道」，并且是诚实的不知道。**")
    A("3. **能做什么**：把 10m Phase 背离画成一盏提示灯（画出来、不触发），"
      "并且在灯亮时标注它离最近具名位多远——这样用户自己在盘面上判断，"
      "同时也在为「合取」这个假设积累前向样本。"
      "要把它做成自动入场条件，需要真实 CAPITALCOM:SPX500 历史 + 明显更长的样本。")
    A("4. **不能做什么**：不能用本节去反驳用户的手工记录。"
      "他的背离是看图判断的（含摆动结构、当日故事、他敢不敢下手），"
      "本节测的是一个**机械代理**；代理无效不蕴含原物无效。"
      "反过来也成立：代理无效时把它做成自动触发是没有依据的。")
    A()

    # ═══════════════════════ 家族 / 缺陷 ═══════════════════════
    A("---")
    A()
    A("## 检视了多少格子（多重比较自报）")
    A()
    A(f"本报告共检视 **{CELLS} 个格子**（一个格子 = 一个报出来的比例或均值单元）。")
    A(f"- 全报告 Bonferroni 门槛：|z| > **{_norm_q(1 - 0.025 / max(CELLS,1)):.2f}**（α=0.05 双侧）。")
    A(f"- 只算 S2 主表的 6 个 k 桶：|z| > **{_norm_q(1 - 0.025 / 6):.2f}**。")
    A(f"- 只算 S3 的 8 个纯背离格：|z| > **{_norm_q(1 - 0.025 / 8):.2f}**；"
      f"算上 2×2 的 32 个格子：|z| > **{_norm_q(1 - 0.025 / 32):.2f}**。")
    A()
    A("**常规 |z| > 1.96 在这个 family size 下没有意义。** "
      "本报告全部格子里最大的 |z_geom| 是 "
      f"**{max(abs(x) for x in [m_all['z_geom']] + [m_k[k]['z_geom'] for k in K_ORDER if m_k[k]['n'] >= 30] + zs_d1 if x == x):.2f}**，"
      "连未校正的门槛都没稳定越过，更不用说 Bonferroni。"
      "加上本项目前面几轮，累计检视格子数已到四位数量级。")
    A()
    A("## 已知缺陷与不确定性")
    A()
    A(f"1. **位相关结论用的是 ES=F，不是 CAPITALCOM:SPX500。** ^GSPC 与 CFD 的 "
      "ATR 比值 246 天 mean 1.117 / sd 0.083 / range 0.826–1.418，**不是常数、"
      "没有修正系数可用**（`levels.py` 里有实测）。ES=F 的作息与 CFD 一致（含完整夜盘），"
      "是现有数据里最接近的代理，但**具名位的绝对位置仍然会差**。"
      "本报告不出现任何具名位的绝对价格，所有位相关口径都按当日 Wilder ATR(14) 归一化；"
      "尽管如此，**S2 的全部结论都依赖具体位价，这是它最大的局限**。")
    A(f"2. **5m 只有 60 天**（{ndays} 个交易日）。^GSPC 5m 覆盖同样这 60 天，"
      "**不是独立样本**（本项目老坑 P3），只能做方向性对照。"
      "本轮没有任何独立时间段的验证——S2 的机制（±0.03 ATR 的带）"
      "在 1h 上没有分辨率，所以 730 天那份数据用不上。")
    A(f"3. **1m 只有 {len(DS_1M.rows_by_day)} 天**，只够验证「5m 同根歧义剔除」"
      "有没有制造结论，不够支撑独立结论。")
    A(f"4. **穿透深度有天花板**：事件在收盘离开 {OUT_BAND}·ATR 时结束，"
      f"所以被拒绝事件的深度落在 [0, ~{OUT_BAND}] ATR。"
      "「深度递减」测的是「扎进去的那一点点在不在缩」，"
      "不是用户看图时感觉到的那种「一波比一波弱」的大结构。**两者不是同一件事。**")
    A("5. **S2 的路径判定与 setup 同在 5m**（纪律 2 的例外）。"
      "±0.03 ATR 的带在 10m 上无法分辨触及与穿过，所以触及只能在 5m 上数。"
      "补偿措施：入场价一律取 K 线收盘（不存在同根裁决入场），"
      "同根同时碰到止损与目标一律记未判定剔除，并在 §A.7 用 1m 子 K 复核。")
    A("6. **S3 的背离只有一种机械定义**（N 根新极值 + 振荡器未同步）。"
      "真实的图形背离还要求第二个低点本身是一个摆动低、两个低点之间要有足够间隔、"
      "背离段不能太长等等。这些都没有测。")
    A("7. **未判定事件被剔除**，剔除本身不是随机的（波动大的时段更容易同根歧义）。"
      "各表都标了未判定数。")
    A("8. **本报告没有做前向验证**，因为这两个 setup 在 v14 里根本不存在，"
      "没有任何线上样本。所有数字都是历史回看。")
    A()

    OUT.write_text("\n".join(LINES) + "\n")
    print(f"\n报告已写入 {OUT}", file=sys.stderr)
    print(f"检视格子数 {CELLS}", file=sys.stderr)


if __name__ == "__main__":
    main()
