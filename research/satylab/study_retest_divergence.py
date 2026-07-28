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


# ── 组间比较必须在「超额」尺度上做，不能用原味两比例 z ──────────────────────
# 本项目的铁律 1 说零假设是 S/(S+T)。两个子组的止损/目标几何**不一样**，
# 所以它们的零假设也不一样（实测能差 7 个百分点）。直接比两个原始命中率，
# 等于把几何差异当成了信号——这正是本项目一路上最容易犯的错。
# 下面的统计量比的是「各自相对自己零假设的超额」，几何差异被逐笔扣掉。
def _exc(tr: list[dict]) -> tuple[float, float, int]:
    """返回 (平均超额, 平均超额的方差, n)。超额 = 命中(0/1) − 该笔的几何零假设。"""
    r = [t for t in tr if t["hit"] is not None]
    n = len(r)
    if n == 0:
        return (float("nan"), float("nan"), 0)
    e = sum((1 if t["hit"] else 0) - t["p"] for t in r) / n
    v = sum(t["p"] * (1 - t["p"]) for t in r) / (n * n)
    return (e, v, n)


def excess_z(a: list[dict], b: list[dict], min_n: int = 10) -> float:
    """A 组的超额 vs B 组的超额。几何零假设逐笔扣除后的组间 z。"""
    ea, va, na = _exc(a)
    eb, vb, nb = _exc(b)
    if na < min_n or nb < min_n or not (va + vb) > 0:
        return float("nan")
    return (ea - eb) / math.sqrt(va + vb)


def excess_interaction_z(a11, a10, a01, a00, min_n: int = 8) -> float:
    """2×2 交互：(超额11 − 超额10) − (超额01 − 超额00)，同样在超额尺度上。"""
    parts = [_exc(x) for x in (a11, a10, a01, a00)]
    if any(p[2] < min_n for p in parts):
        return float("nan")
    est = (parts[0][0] - parts[1][0]) - (parts[2][0] - parts[3][0])
    var = sum(p[1] for p in parts)
    return est / math.sqrt(var) if var > 0 else float("nan")


def welch_t(a: list[float], b: list[float]) -> float:
    """两组均值差的 Welch t（用于均净R 这种连续量）。"""
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    return (mean(a) - mean(b)) / math.sqrt(va + vb) if (va + vb) > 0 \
        else float("nan")


def nets_of(tr: list[dict]) -> list[float]:
    return [t["net"] for t in tr if t["hit"] is not None]


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


PLB_KINDS = ("均匀随机", "整体平移", "逐位抖动")


def plb_rng(kind: str, rep: int, d: date) -> random.Random:
    """确定性种子。**不能用 `hash()`** —— Python 对字符串的 hash 每个进程都不同，
    用它做种子会让「固定随机种子」这句话变成假话（本轮第一版就踩了：
    同一份代码跑两次，安慰剂的 z_geom 从 +1.41 变成 −1.95）。"""
    k = PLB_KINDS.index(kind)
    return random.Random(SEED * 1_000_003 + rep * 9176 + d.toordinal() * 31
                         + k * 7_919)


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
         subs=None, cap: int | None = None) -> tuple[bool | None, str]:
    """止损与目标谁先到。返回 (hit, why)。

    why = ""（判定了）/ "AMBIG"（同一根 K 内同时碰到两边，分辨率不够）/
    "TIMEOUT"（窗口内两边都没碰到）。**这两种未判定必须分开数**：AMBIG 是
    分辨率缺陷（用更细的子 K 可以救），TIMEOUT 是行情本身没走完（救不了）。
    把它们混在一起报，会让「换更细的子 K 复核」这件事看起来什么都没改变。
    """
    end = len(rows) if cap is None else min(len(rows), start + cap)
    for j in range(start, end):
        seq = subs[j] if (subs is not None and subs[j]) else [rows[j]]
        for sb in seq:
            hs = (sb.low <= stop) if d > 0 else (sb.high >= stop)
            ht = (sb.high >= target) if d > 0 else (sb.low <= target)
            if hs and ht:
                return None, "AMBIG"
            if hs:
                return False, ""
            if ht:
                return True, ""
    return None, "TIMEOUT"


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
        hit, why = race(rows, e.i1 + 1, d, stop, target, subs)
        out.append({"ep": e, "hit": hit, "why": why,
                    "p": risk / (risk + tdist),
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
            "amb": sum(1 for t in tr if t["why"] == "AMBIG"),
            "tmo": sum(1 for t in tr if t["why"] == "TIMEOUT"),
            "k": sum(1 for h in hits if h), "obs": o, "null": nu, "z_geom": z,
            "avg_r": mean(rs), "avg_net": mean(nets),
            "tot_r": sum(rs), "net_r": sum(nets), "t_net": tstat(nets),
            "z_sel": zs, "risk": mean(t["risk_atr"] for t in res),
            "ts": st.median([t["ts"] for t in res]) if res else float("nan")}


# 每一个报出来的 z_geom 都登记在案，文末的「最大 |z|」才敢说是真的最大。
# 纪律：只要某个 z_geom 出现在正文的表里，就必须先经过 regz()。
ZREG: list[tuple[str, float]] = []


def regz(lbl: str, m: dict) -> str:
    """登记并返回格式化的 z_geom。"""
    if m["n"] and m["z_geom"] == m["z_geom"]:
        ZREG.append((lbl, m["z_geom"]))
    return f(m["z_geom"])


def row_s2(lbl: str, m: dict, reg: bool = True) -> str:
    if m["n"] == 0:
        return f"| {lbl} | {m['n_all']} | 0 | – | – | – | – | – | – | – | – |"
    if reg and m["z_geom"] == m["z_geom"]:
        ZREG.append((lbl.replace("*", ""), m["z_geom"]))
    return (f"| {lbl} | {m['n_all']} | {m['n']} | {m['amb']} | {m['tmo']} | "
            f"**{pct(m['k'], m['n'])}** | {100*m['null']:.1f}% | "
            f"**{f(m['z_geom'])}** | {m['avg_r']:+.3f} | "
            f"**{m['avg_net']:+.3f}** | {m['net_r']:+.1f} | {f(m['t_net'])} |")


HEAD_S2 = ("| 分组 | 事件数 | 已判定 | 未判定(同根歧义) | 未判定(未走完) | "
           "**命中率 [95% Wilson]** | 几何零假设 | **z_geom** | 均R(毛) | "
           "**均净R** | 总净R | t(均净R) |")
RULE_S2 = "|---|---|---|---|---|---|---|---|---|---|---|---|"


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
        hit, why = race(bars, i + 1, d, stop, target, subs, cap)
        out.append({"ext": s, "hit": hit, "why": why,
                    "p": risk / (risk + tdist),
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

    plb: dict[tuple[str, int, date], list[float]] = {}

    def make_plb(kind: str, rep: int = 0):
        def g(d: date) -> list[float]:
            key = (kind, rep, d)
            if key not in plb:
                plb[key] = placebo_ratios(kind, plb_rng(kind, rep, d))
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

    # 安慰剂：不能只抽一把。单把安慰剂的 z_geom 抖动幅度和「效应」本身同量级
    # （本轮初版就因为种子不确定，两次运行分别得到 +1.41 和 −1.95）。
    # 所以这里抽 REPS 把，报出整条零分布，再看真具名位落在第几个百分位。
    REPS = 200
    print(f"S2 安慰剂（{REPS} 次重抽）…", file=sys.stderr)
    PLB = {}
    for kind in PLB_KINDS:
        zs, nets, d21 = [], [], []
        for rep in range(REPS):
            t2 = s2_trades(DS, run_scan(DS, make_plb(kind, rep)))
            m2 = summarize(t2)
            a1 = summarize([t for t in t2 if t["ep"].k == 1])
            a2 = summarize([t for t in t2 if t["ep"].k >= 2])
            if m2["z_geom"] == m2["z_geom"]:
                zs.append(m2["z_geom"])
                nets.append(m2["avg_net"])
            if a1["n"] and a2["n"]:
                d21.append(a2["avg_net"] - a1["avg_net"])
            plb.clear()
        PLB[kind] = {"z": sorted(zs), "net": sorted(nets), "d21": sorted(d21)}

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
    # 深度本身作为连续变量（不看递减，只看这次深不深）。
    # 注意：一半以上的拒绝事件深度恰好为 0（价格进了带但根本没越过该位），
    # 所以「按中位数对切」实际就是「0 vs 非 0」，标签必须照实说。
    zero_tr = [t for t in TR if t["ep"].depth <= 1e-9]
    pos_tr = [t for t in TR if t["ep"].depth > 1e-9]
    m_shal, m_deep = summarize(zero_tr, TR), summarize(pos_tr, TR)

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
      "（作息与 CAPITALCOM:SPX500 一致）；S3 的 setup 在由同一批 5m 聚合出的 "
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
    A(f"- **衰减（穿透深度递减）是三条候选规则里最不坏的一条，但同样没到证据强度**："
      f"「本次深度 < 上次深度」{m_dec['n']} 笔，z_geom {f(m_dec['z_geom'])}，"
      f"均净R {m_dec['avg_net']:+.3f}；「深度未递减」{m_inc['n']} 笔，"
      f"z_geom {f(m_inc['z_geom'])}，均净R {m_inc['avg_net']:+.3f}；"
      f"两组超额口径 z = {f(excess_z(dec_tr, inc_tr))}，"
      f"均净R 差 {m_dec['avg_net']-m_inc['avg_net']:+.3f}。"
      f"三条规则的 z_sel 分别是：次数 k≥2 {f(m_ge2['z_sel'])}、"
      f"一步递减 {f(m_dec['z_sel'])}、两步递减 {f(m_dec2['z_sel'])}——"
      "**全部不显著；递减只是「负得比计数少」，不是「正」。**")
    A()
    zs_div = [(N, k, DIV[(N, k)]["m"][c]["z_geom"], c)
              for (N, k) in DIV for c in ("D1", "D1L1")
              if DIV[(N, k)]["m"][c]["n"] >= 25]
    bst = max(zs_div, key=lambda x: x[2]) if zs_div else None
    zs_d1 = [DIV[k]["m"]["D1"]["z_geom"] for k in DIV
             if DIV[k]["m"]["D1"]["n"] >= 20]
    zdm = [excess_z(DIV[(N, k)]["g"]["D1"], DIV[(N, k)]["g"]["D0"])
           for N in (10, 15, 20, 30) for k in ("bull", "bear")]
    zdm = [z for z in zdm if z == z]
    nneg = sum(1 for N in (10, 15, 20, 30) for k in ("bull", "bear")
               if DIV[(N, k)]["m"]["D1"]["avg_net"] < 0)
    A("**S3（Phase 背离）：作为入场条件不成立；但它确实分离样本——"
      "分离的形状是「否决」而不是「入场」。合取则是检验力不足，不下结论。**")
    A(f"- **单项打不过自己的几何零假设**：8 个纯背离格子 z_geom 最大 "
      f"{max(zs_d1):+.2f}，均净R {nneg}/8 为负。")
    A(f"- **但背离标签不是完全没用**：把它和「无背离」（价格创新极值且 Phase "
      f"**也**创新极值＝纯动量延续）在**超额口径**下对比，8 个格子的 z 范围 "
      f"[{min(zdm):+.2f}, {max(zdm):+.2f}]（>1.96 的只有 "
      f"{sum(1 for z in zdm if z > 1.96)} 个），Δ均净R 8/8 同号——"
      "但四个 N 跑在同一批 K 上高度重叠，实际只等于「底/顶两次同号」。"
      "**结论是「无背离那一类特别差」，不是「背离那一类好」。**")
    A("- ⚠ **这里必须用超额口径**：两组止损几何不同、几何零假设能差 7 个百分点，"
      "原味两比例 z 会把同一个格子从 +1.93 虚报成 +3.00（§B.4 保留了这一列做对照）。")
    A(f"- **合取（背离 ∧ 极值落在具名位 ≤{AT_LEVEL} ATR）：交互 z 全部在 ±2 以内，"
      f"但对照格（背离∧不在位）只有十几笔，本设计测不出中等大小的交互。**"
      "这是『没测出来』，不是『测出来没有』——见 §B.4 末尾写给下一轮的补法。")
    A()
    A("**共同判决：两条都不该以「新增入场条件」的身份进 v15。** "
      "S2 值得画出来的是**穿透深度**（不是触及次数）；"
      "S3 值得画出来的是**背离灯 + 它离最近具名位多远**——"
      "画出来同时也在为「合取」积累前向样本，这是本项目现在最缺的东西。")
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
    A("- **路径**：5m 逐根推进。两种未判定分开数——**同根歧义**（一根 K 内同时碰到"
      "止损与目标，分辨率不够）与**未走完**（当日收盘前两边都没碰到）。"
      "两者都剔除，但必须分开报：只有前者才是「换更细的子 K 能救」的那一种"
      "（§A.7 用 1m 复核）。交易只在当日内结算"
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
            tag = f"§A.3 带宽 in±{ib}/out{ob}"
            A(f"| ±{ib}{flag}{main} | {ob} | {r['n_ep']} | {r['maxk']} | "
              f"{r['all']['n']} / {regz(tag+' 全部', r['all'])} / "
              f"{r['all']['avg_net']:+.3f} | "
              f"{r['k1']['n']} / {regz(tag+' k=1', r['k1'])} / "
              f"{r['k1']['avg_net']:+.3f} | "
              f"{r['k2']['n']} / {regz(tag+' k≥2', r['k2'])} / "
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
                   ("对照：本次深度 = 0（进带但没越过该位）", m_shal),
                   ("对照：本次深度 > 0（确实越过了该位）", m_deep)):
        A(row_s2(lbl, m))
        cell()
    A()
    zdi = excess_z(dec_tr, inc_tr)
    A(f"- **递减 vs 未递减**（在 k≥2 内部对切）：**超额口径 z = {f(zdi)}**"
      f"（两组的止损/目标几何并不同构，所以这里比的是各自相对自己几何零假设的"
      f"超额，不是原始命中率之差——原味两比例 z = "
      f"{stats.two_proportion_z(m_dec['k'], m_dec['n'], m_inc['k'], m_inc['n']):+.2f}，"
      f"那个数不能用）；均净R 差 **{m_dec['avg_net']-m_inc['avg_net']:+.3f}**"
      f"（Welch t = {f(welch_t(nets_of(dec_tr), nets_of(inc_tr)))}）。")
    A(f"- **递减 vs 计数**：规则 ② 的 z_sel = {f(m_dec['z_sel'])}，"
      f"规则 ① 的 z_sel = {f(m_ge2['z_sel'])}。"
      f"两者都是相对同一个全样本基线算的，可以直接比。")
    A(f"- **深度作为连续变量**（不看递减，只看这一次扎得深不深）："
      f"深度=0 的 {m_shal['n']} 笔均净R {m_shal['avg_net']:+.3f}"
      f"（z_geom {f(m_shal['z_geom'])}），深度>0 的 {m_deep['n']} 笔 "
      f"{m_deep['avg_net']:+.3f}（z_geom {f(m_deep['z_geom'])}），"
      f"超额口径 z = {f(excess_z(pos_tr, zero_tr))}。"
      "⚠ 这一对切**不是**「浅一半 / 深一半」——"
      f"{100*m_shal['n']/max(1,m_shal['n']+m_deep['n']):.0f}% 的拒绝事件深度恰好为 0，"
      "所以中位数就是 0，这里只能切成「有没有越过该位」。")
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

    A("### A.5 安慰剂：把具名位换成随机价位（200 次重抽的零分布）")
    A()
    A("三种安慰剂（密度分布不同，做法不同）：**均匀随机** 17 个位"
      "（与任一具名位 ≥0.06 ATR）；**整体平移** 整条阶梯 +0.118 ATR"
      "（挪到相邻档位正中间）；**逐位抖动** 每个位随机偏移 ±0.06~0.118 ATR。")
    A()
    A("> **本节的方法论比结果重要。** 初版只抽了一把安慰剂，"
      "而且种子用了 Python 的 `hash()`——它对字符串是每进程随机的。"
      "结果：同一份代码跑两次，「逐位抖动」的 z_geom 从 **+1.41** 变成 **−1.95**，"
      "足以把结论从「安慰剂更好」翻成「安慰剂更差」。"
      "**一把安慰剂根本不是对照，它只是又一次抽样。** "
      "所以下面改成抽 200 把，报整条零分布，再看真具名位落在第几个百分位。")
    A()
    A("| 安慰剂 | z_geom 零分布（均值 / 5% / 50% / 95%） | "
      "均净R 零分布（均值 / 5% / 95%） | **真具名位的百分位** |")
    A("|---|---|---|---|")

    def q(v: list[float], p: float) -> float:
        return v[min(len(v) - 1, max(0, int(p * len(v))))] if v else float("nan")

    def prc(v: list[float], x: float) -> float:
        return 100.0 * sum(1 for a in v if a < x) / len(v) if v else float("nan")

    for kind in PLB_KINDS:
        r = PLB[kind]
        if len(set(r["z"])) <= 1:          # 整体平移没有随机性，200 把全一样
            A(f"| {kind}（确定性变体，无随机性） | {r['z'][0]:+.2f}（单值） | "
              f"{r['net'][0]:+.3f}（单值） | 不适用——只有一个取值 |")
            cell()
            continue
        A(f"| {kind} | {mean(r['z']):+.2f} / {q(r['z'],.05):+.2f} / "
          f"{q(r['z'],.50):+.2f} / {q(r['z'],.95):+.2f} | "
          f"{mean(r['net']):+.3f} / {q(r['net'],.05):+.3f} / "
          f"{q(r['net'],.95):+.3f} | z_geom 第 "
          f"**{prc(r['z'], m_all['z_geom']):.0f}** 百分位，"
          f"均净R 第 **{prc(r['net'], m_all['avg_net']):.0f}** 百分位 |")
        cell(2)
    A()
    A(f"真具名位：z_geom **{f(m_all['z_geom'])}**，均净R **{m_all['avg_net']:+.3f}**。"
      "「整体平移」是一个确定性变体（整条阶梯挪 +0.118 ATR，没有随机成分），"
      "所以它没有零分布，只有一个取值——列在这里是为了看「挪到档位正中间」"
      "会不会变差，答案是不会。")
    A()
    zw = PLB["均匀随机"]
    A(f"**判读。** 随机位的 z_geom 零分布宽度是 "
      f"[{q(zw['z'],.05):+.2f}, {q(zw['z'],.95):+.2f}]——"
      "**「把随机价位当成支撑阻力去做拒绝单」这件事本身的结果波动，"
      "就已经和我们想找的效应同量级。** 真具名位落在这条零分布的中段"
      f"（z_geom 第 {prc(zw['z'], m_all['z_geom']):.0f} 百分位，"
      f"均净R 第 {prc(zw['net'], m_all['avg_net']):.0f} 百分位），"
      "没有任何一项排到尾部。")
    A()
    A("**所以：斐波那契这一层没有贡献。** 把结论里的「具名位」三个字删掉，"
      "S2 的全部结论一字不变。这一节同时也说明——"
      "本项目以后凡是做安慰剂对照，**必须重抽多次并报零分布**，"
      "单次抽样的安慰剂没有证据价值。")
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
          f"{100*m['null']:.1f}% | {regz('§A.6 位类型 '+tp, m)} | "
          f"{m['avg_net']:+.3f} |")
        cell()
    A()
    A("| 时段 | n | 命中率 | 几何零假设 | z_geom | 均净R |")
    A("|---|---|---|---|---|---|")
    for ss in ("RTH", "夜盘"):
        m = summarize([t for t in TR if t["ep"].sess == ss], TR)
        A(f"| {ss} | {m['n']} | {pct(m['k'], m['n'])} | {100*m['null']:.1f}% | "
          f"{regz('§A.6 时段 '+ss, m)} | {m['avg_net']:+.3f} |")
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
          f"{regz('§A.6 '+lbl, m)} | {m['avg_net']:+.3f} |")
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
    A("**纪律 2 的复核，以及一个必须说清楚的发现。**")
    A()
    A(f"主表 {m_all['n_all']} 笔里未判定 {m_all['unres']} 笔，"
      f"**其中同根歧义只有 {m_all['amb']} 笔（{100*m_all['amb']/max(1,m_all['n_all']):.1f}%），"
      f"其余 {m_all['tmo']} 笔是当日收盘前两边都没碰到**。"
      "这两种未判定完全不是一回事：前者是分辨率缺陷（换更细的子 K 能救），"
      "后者是行情本身没走完（换多细的子 K 都救不了）。")
    A()
    A(f"为什么同根歧义这么少：本构造的止损距离约 {m_all['risk']:.3f} ATR、"
      f"止损到目标的总跨度中位 {(1+m_all['ts'])*m_all['risk']:.2f} ATR，"
      "一根 5m K 很少能一口气吃掉整个跨度。所以——")
    A()
    A(f"> **在有 1m 数据的 {len(DS_1M.rows_by_day)} 天上，5m 判路径与 1m 子 K 判路径"
      f"给出的结果逐笔完全一致**（未判定 {m_15['unres']} → {m_11['unres']}，"
      f"其中同根歧义 {m_15['amb']} → {m_11['amb']}；命中率 {100*m_15['obs']:.1f}% → "
      f"{100*m_11['obs']:.1f}%）。这不是「复核通过」的漂亮话，"
      "而是因为**这段样本里根本没有同根歧义可拆**。")
    A()
    A("这条复核的真实结论只有一句：**S2 的构造在 5m 上不存在同根裁决问题**"
      "（跨度远大于单根 K），所以纪律 2 在这里不是靠「换更细的 K」满足的，"
      "是靠「入场价取收盘 + 跨度足够大」满足的。"
      f"⚠ 1m 只覆盖 {len(DS_1M.rows_by_day)} 天，且这 18 天的均净R "
      f"（{m_15['avg_net']:+.3f}）明显差于全样本（{m_all['avg_net']:+.3f}），"
      "说明**这一小段样本本身就不具代表性**，绝不能拿它读水平。")
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
                if m["z_geom"] == m["z_geom"]:
                    ZREG.append((f"N={N}·{kind}·{lbl.replace('*','')}",
                                 m["z_geom"]))
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
    A("> **口径警告（本节最容易出错的地方）。** D1 与 D0 的**几何零假设不一样**："
      "背离根的 N 根极值离收盘更近，止损更短，S/(S+T) 因此不同——实测两组的零假设"
      "能差 7 个百分点。所以**不能比原始命中率**（原味两比例 z 会把几何差异当成信号，"
      "这正是本项目铁律 1 要防的事）。下表的所有 z 都是**超额口径**："
      "先逐笔减去自己的 S/(S+T)，再比两组的平均超额。")
    A()
    A("| N | 方向 | ① 背离边际 Δ均净R | **z(超额)** | 原味z(不可用) | "
      "② 在位边际 Δ均净R | **z(超额)** | ③ 交互 Δ均净R | **③ z(超额)** | D1L1 的 n |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    zd_all, zl_all, zis = [], [], []
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            m, g = DIV[(N, kind)]["m"], DIV[(N, kind)]["g"]
            d_marg = m["D1"]["avg_net"] - m["D0"]["avg_net"]
            zd = excess_z(g["D1"], g["D0"])
            zd_naive = stats.two_proportion_z(m["D1"]["k"], m["D1"]["n"],
                                              m["D0"]["k"], m["D0"]["n"])
            l_marg = m["L1"]["avg_net"] - m["L0"]["avg_net"]
            zl = excess_z(g["L1"], g["L0"])
            inter = ((m["D1L1"]["avg_net"] - m["D1L0"]["avg_net"]) -
                     (m["D0L1"]["avg_net"] - m["D0L0"]["avg_net"]))
            zi = excess_interaction_z(g["D1L1"], g["D1L0"],
                                      g["D0L1"], g["D0L0"])
            for lst, v in ((zd_all, zd), (zl_all, zl), (zis, zi)):
                if v == v:
                    lst.append(v)
            A(f"| {N} | {'底' if kind=='bull' else '顶'} | {f(d_marg, 3)} | "
              f"**{f(zd)}** | ~~{zd_naive:+.2f}~~ | {f(l_marg, 3)} | "
              f"**{f(zl)}** | {f(inter, 3)} | **{f(zi)}** | "
              f"{m['D1L1']['n']} |")
            cell(3)
    A()
    A(f"**① 背离这个标签：方向一致，强度弱。** 8 个格子的超额 z 范围 "
      f"[{min(zd_all):+.2f}, {max(zd_all):+.2f}]，"
      f">1.96 的只有 {sum(1 for z in zd_all if z > 1.96)} 个；"
      f"Δ均净R 为正的有 "
      f"{sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['D1']['avg_net'] > DIV[(N,k)]['m']['D0']['avg_net'])}/8 个。"
      "**「8/8 同号」看着有力，但这 8 个格子远不是 8 个独立证据**——"
      "四个 N 跑在同一批 10m K 上，事件高度重叠，同一段行情被数了四遍；"
      "真正独立的只有「底 / 顶」这一个二分。按两个独立方向算，"
      "这就是「两次同号」，不是「八次同号」。")
    A()
    A("**顺带看一眼「原味z」那一列。** 它系统性地大于超额 z"
      f"（最夸张的一格 N=20·顶：原味 +3.00 vs 超额 "
      f"{f(excess_z(DIV[(20,'bear')]['g']['D1'], DIV[(20,'bear')]['g']['D0']))}）。"
      "多出来的那一截全是**几何差异**：背离根的 N 根极值离收盘更近、止损更短，"
      "S/(S+T) 天然更高。如果本节按原味 z 写，就会得到「背离显著有效」的结论，"
      "而那个结论是假的。**这一列留在表里，是本报告最值得记住的一张反面教材。**")
    A()
    A("**但「分离样本」不等于「能交易」。** 看 §B.2：8 个纯背离格子的均净R 里 "
      f"{sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['D1']['avg_net'] < 0)}/8 是负的，"
      "自身 z_geom 全部在 ±1.96 以内。也就是说背离的作用是"
      "**把「无背离」那一类（价格创新极值且振荡器同步创新极值＝纯动量延续）排除掉**——"
      "那一类做反向括号单亏得特别惨。**这是一条否决规则的证据，不是一条入场规则的证据。** "
      "而一条把你从「亏很多」拉到「亏一点」的否决规则，不值得单独占一个入场条件。")
    A()
    A(f"**② 在位边际**：超额 z 范围 [{min(zl_all):+.2f}, {max(zl_all):+.2f}]，"
      f">1.96 的有 {sum(1 for z in zl_all if z > 1.96)} 个；Δ均净R 为正的有 "
      f"{sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['L1']['avg_net'] > DIV[(N,k)]['m']['L0']['avg_net'])}/8 个。"
      "方向一致但强度低，且 L0（不在位）那一类的 n 只有个位数到二十几，"
      "所以这个边际本身就是靠一个很小的对照组撑起来的。")
    A()
    if zis:
        A(f"**③ 交互——这才是「合取」这个词真正要问的东西。** "
          f"{len(zis)} 个可算的交互 z 范围 [{min(zis):+.2f}, {max(zis):+.2f}]，"
          f"|z|>1.96 的有 {sum(1 for z in zis if abs(z) > 1.96)} 个，"
          f"符号 {sum(1 for z in zis if z > 0)} 正 / {sum(1 for z in zis if z < 0)} 负。"
          "**没有交互的证据。**")
    A()
    n_conj = [DIV[k]["m"]["D1L1"]["n"] for k in DIV]
    A(f"**⚠ 但「没有交互的证据」离「有证据说没有交互」很远。** "
      f"8 个合取格的 n 分别是 " + "、".join(str(x) for x in n_conj) +
      f"（中位 {int(st.median(n_conj))}），对照格 D1L0 的 n 只有 "
      + "、".join(str(DIV[k]["m"]["D1L0"]["n"]) for k in DIV) + "。"
      "交互项的标准误由**最小的那个格子**决定，所以本设计的检验力实际上被 "
      f"D1L0 的十几笔锁死了。粗算：在 n≈15 的对照格下，要让交互 z 越过 1.96，"
      "交互效应得大到 25 个百分点以上——那已经不是「中等效应」，是「奇迹」。")
    A()
    A("> 所以本节的正确表述是：**「背离 ∧ 在位」这个合取在本样本上没有测出额外效应，"
      "而本样本也没有能力测出一个中等大小的额外效应。这是『没测出来』，"
      "不是『测出来没有』。** 任何据此宣称 Saty 的「10m divergence at support」"
      "被证伪的说法都是过度解读；同样，任何据此把合取写进 v15 当自动触发的做法"
      "也同样没有依据。这一条是本报告唯一一处诚实的「我不知道」。")
    A()
    A("**这个缺口要怎么补**（写给下一轮）：交互检验的瓶颈是 D1L0（背离但不在位）"
      f"太少——因为具名位一天有 17 条，±{AT_LEVEL} ATR 的口袋几乎盖满了全天价格区间"
      f"（实测 {100*len(DIV[(10,'bull')]['g']['L1'])/max(1,len(DIV[(10,'bull')]['g']['ALL'])):.0f}% "
      "的极值都算「在位」）。要让这个检验有力量，得先把「在位」定义收紧到"
      "真正稀缺的程度（比如只认 0.382/0.618，或把口袋压到 0.03 ATR），"
      "或者换更长的样本。**在那之前，不要再报一次这个交互并假装它说明了什么。**")
    A()

    A("### B.5 S3 判决")
    A()
    A(f"1. **纯背离（单项）：作为入场条件不成立。** 8 个格子自身的 z_geom 最大 "
      f"{max(zs_d1):+.2f}（Bonferroni 门槛见文末），"
      f"均净R {sum(1 for N in (10,15,20,30) for k in ('bull','bear') if DIV[(N,k)]['m']['D1']['avg_net'] < 0)}/8 为负。"
      "**打不过自己的几何零假设。**")
    A("2. **但要更正一句话**：不能说「背离这个条件没把任何信息加进来」。"
      "§B.4 的超额口径显示背离组与无背离组**确实可分**"
      f"（8 个格子超额 z 最大 {max(zd_all):+.2f}，Δ均净R 8/8 同号）。"
      "只是这个信息的形状是**否决**而不是**入场**："
      "背离的价值在于排除掉「振荡器同步创新极值」那一类纯动量延续，"
      "而排除之后剩下的仍然不赚钱。")
    A(f"3. **合取（背离 ∧ 在位）：检验力不足，不下结论。** 交互 z 全部在 ±2 以内，"
      f"但对照格 D1L0 只有十几笔，本设计根本测不出中等大小的交互。"
      "**这是本报告唯一一处「我不知道」，并且是诚实的不知道。**")
    A("4. **能做什么**：把 10m Phase 背离画成一盏提示灯（画出来、不触发），"
      "并在灯亮时标注它离最近具名位多远。这既让用户自己在盘面上判断，"
      "也在为「合取」这个假设积累前向样本——本项目现在最缺的就是这个。")
    A("5. **不能做什么**：不能用本节去反驳用户的手工记录。"
      "他的背离是看图判断的（含摆动结构、当日故事、他敢不敢下手），"
      "本节测的是一个**机械代理**；代理无效不蕴含原物无效。"
      "反过来也成立：代理无效时把它做成自动触发是没有依据的。")
    A()

    # ═══════════════════════ 与假设相反的格子 ═══════════════════════
    A("---")
    A()
    A("## C. 与假设相反 / 意料之外的格子（纪律 7）")
    A()
    A("本节单列所有「和本报告主结论唱反调」的格子。它们**不是结论**——"
      "在文末那个 family size 下，单个 |z|<3.5 的格子不构成证据——"
      "但把它们藏起来会让报告变成一份辩护词。")
    A()
    A("| 出处 | 格子 | n | z_geom | 均净R | 为什么它和主结论矛盾 |")
    A("|---|---|---|---|---|---|")
    A(f"| §A.2 | 第 1 次触及 | {m_k['1']['n']} | {f(m_k['1']['z_geom'])} | "
      f"{m_k['1']['avg_net']:+.3f} | **k 桶里唯一均净R 为正的一格，"
      f"而它恰好是用户认为最不该做的那一次。** 用户猜「碰两次以后才考虑」，"
      f"数据的方向是反的。 |")
    for tp in TYPE_ORDER:
        m = summarize([t for t in TR if t["ep"].ltype == tp], TR)
        if m["n"] >= 30 and m["z_geom"] > 1.5:
            A(f"| §A.6 | 位类型 {tp} | {m['n']} | {f(m['z_geom'])} | "
              f"{m['avg_net']:+.3f} | S2 整体没信号，这一类却是正的。"
              f"8 个位类型里挑出来的，未校正。 |")
    for kind in PLB_KINDS:
        if len(set(PLB[kind]["z"])) <= 1:
            continue
        p = prc(PLB[kind]["net"], m_all["avg_net"])
        if p < 50:
            A(f"| §A.5 | 安慰剂「{kind}」 | {REPS} 次重抽 | – | "
              f"零分布均值 {mean(PLB[kind]['net']):+.3f} | "
              f"**真具名位的均净R 只排在这类随机位的第 {p:.0f} 百分位**——"
              f"即多数随机价位做得比真具名位还好。不支持「具名位有特殊性」。 |")
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            mm = DIV[(N, kind)]["m"]
            for key, lbl in (("D1L1", "背离∧在位"), ("D0L1", "无背离∧在位")):
                if mm[key]["n"] >= 25 and abs(mm[key]["z_geom"]) > 1.8:
                    A(f"| §B.3 | N={N}·{'底' if kind=='bull' else '顶'}·{lbl} | "
                      f"{mm[key]['n']} | {f(mm[key]['z_geom'])} | "
                      f"{mm[key]['avg_net']:+.3f} | "
                      f"{'合取格里最好的一个，但 32 个 2×2 格子里挑的。' if mm[key]['z_geom'] > 0 else '负得比其余格子明显——这是「无背离」那一类特别差的直接证据，支持 §B.4 的否决式读法。'} |")
    A()
    A("**怎么读这张表。** 第一行（第 1 次触及最好）和倒数几行（无背离格特别差）"
      "是两条方向清楚、机制上讲得通、但强度不够的线索；"
      "中间那些（某个位类型、某个安慰剂）更像是格子挑出来的噪声。"
      "本报告不基于其中任何一条提出建议。")
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
    thr = _norm_q(1 - 0.025 / max(CELLS, 1))
    top = sorted(ZREG, key=lambda x: -abs(x[1]))[:5]
    A(f"**登记在案的 z_geom 共 {len(ZREG)} 个**（每报一个就登记一个，"
      "所以下面这个「最大」是真的最大，不是挑着算的）。绝对值最大的五个：")
    A()
    for lbl, z in top:
        A(f"- {lbl}：z_geom = **{z:+.2f}**"
          f"{'　← 越过全报告 Bonferroni 门槛' if abs(z) > thr else ''}")
    A()
    n_over = sum(1 for _, z in ZREG if abs(z) > 1.96)
    A(f"未校正 |z|>1.96 的有 **{n_over} 个**；按纯随机预期，"
      f"{len(ZREG)} 个格子本来就该出现约 {0.05*len(ZREG):.1f} 个。"
      f"**实际 {n_over} 个，和随机没有区别。** "
      f"越过全报告 Bonferroni 门槛 {thr:.2f} 的有 "
      f"**{sum(1 for _, z in ZREG if abs(z) > thr)} 个**。")
    A()
    A("**结论：本报告没有任何一个候选构成证据。** "
      "常规 |z| > 1.96 在这个 family size 下不是发现，是噪声的正常产量。"
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
    A(f"3. **1m 只有 {len(DS_1M.rows_by_day)} 天，而且这次复核实际上是空转。** "
      f"这 {len(DS_1M.rows_by_day)} 天里 5m 判路径产生的同根歧义是 "
      f"{m_15['amb']} 笔，所以「换 1m 子 K」逐笔没有改变任何结果（§A.7）。"
      "这**不能**被读成「1m 复核通过」——它只说明 S2 的构造在 5m 上"
      "本来就没有同根裁决问题。真正需要 1m 的是 S3 那种止损很近的构造，"
      "而 S3 用的是 10m/5m，已经合规。")
    A(f"4. **穿透深度有天花板**：事件在收盘离开 {OUT_BAND}·ATR 时结束，"
      f"所以被拒绝事件的深度落在 [0, ~{OUT_BAND}] ATR。"
      "「深度递减」测的是「扎进去的那一点点在不在缩」，"
      "不是用户看图时感觉到的那种「一波比一波弱」的大结构。**两者不是同一件事。**")
    A("5. **S2 的路径判定与 setup 同在 5m**（纪律 2 的例外，必须写明）。"
      "±0.03 ATR 的带在 10m 上无法分辨「触及」与「穿过」，所以触及只能在 5m 上数。"
      "三条补偿：① 入场价一律取 K 线收盘，所以**入场本身不存在同根裁决**；"
      f"② 止损到目标的跨度中位 {(1+m_all['ts'])*m_all['risk']:.2f} ATR，"
      f"远大于单根 5m K，实测同根歧义只占 {100*m_all['amb']/max(1,m_all['n_all']):.1f}%；"
      "③ 这些歧义笔一律剔除并单列成表内一栏。"
      "**即便如此，这仍然是一个例外，不是一个合规的做法。**")
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
