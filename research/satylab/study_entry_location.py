"""V15 · 入场位置质量：把「追」这个变量单独拎出来量化。

为什么有这个文件
----------------
v14 线上账本 695 笔 / 32% / −44.1R。上一轮诊断已经确认 churn 是真的，也确认
**修 churn 只把「快亏」变成「慢亏」**：纯括号赛跑（保护位 vs T1 谁先到）实测
53.4% 对几何零假设 56.8%，z_geom = −1.68；60 个格子的 z_geom 中位 −1.33，没有
一个越过 +1.96。孤立的入场时点不带方向信息。

用户（真实 0DTE SPX 交易者）给的机制性诊断是：

    "你每次买卖的时机，要么是在剧烈下跌的时候去卖，要么是在剧烈上涨的时候去买，
     那肯定不是什么好位置。"

机制上这个说法有具体的代码依据：v14 的入场价 = 信号 K 的**收盘价**。信号 K 越大
（剧烈行情），入场离参考线（EMA13）越远、离结构止损越远、风险距离越大。所以
「追」不是一个感觉，它是四个入场时刻就能算出来的数：

    D1  |入场价 − EMA13| / 当日ATR            离参考线多远
    D2  信号 K 的 (H−L)/ATR 和 |C−O|/ATR      信号 K 有多大
    D3  dir × (close[i] − close[i−3]) / ATR   近端冲量（正 = 顺信号方向追）
    D4  风险距离 / ATR                        离结构止损多远

本文件测的是：**这四个数与后续结果之间有没有单调关系。**

抽样口径（重要）
----------------
主样本是「**未被持仓吞掉的全部信号**」——把 v14 的 `pDir == 0` 单仓闸门拿掉之后
状态机吐出的每一个入场事件。理由：入场位置质量是入场事件的属性，而「这一笔有没有
被上一笔挡住」是排队顺序的产物，与位置质量无关，按它筛样本会引入选择偏差。线上
实际成交的那 462 笔作为稳健性对照单独再跑一遍，两者结论必须一致才算数。

结果变量全部用 5 分钟子 K 解路径（纪律 3）。位相关一律 ATR 归一（纪律 5）。
比例的零假设一律是几何零假设 S/(S+T)，不是 50%（纪律 1）。

Usage:  .venv/bin/python research/satylab/study_entry_location.py
"""

from __future__ import annotations

import math
import statistics as st
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats                              # noqa: E402
from satylab.data import Bar                                 # noqa: E402
from satylab.indicators import ema                           # noqa: E402
from satylab.study_v14_repro import (                        # noqa: E402
    LevelBook, load_10m, next_rung, run_v14, trade_day,
)

STACK_BARS = 5
MIN_RISK_PTS = 2.0
SPREAD = 0.6              # CAPITALCOM:SPX500 典型点差，来自 Pine tooltip
RACE_CAP = 400            # 括号最多跑多少根 setup K
MFE_H = 18                # MFE/MAE 的固定前视窗口：18 根 10m = 3 小时
NQ = 5                    # 分档数
REPORT = Path(__file__).resolve().parents[1] / "reports" / "V15_ENTRY_LOCATION.md"

CELLS = 0                 # 全局：检视过的格子数（family size）


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ══════════════════════════════ 信号采集 ══════════════════════════════════════
@dataclass
class Sig:
    setup: str
    direction: int
    session: str
    i: int
    dt: object
    entry: float
    prot: float
    risk: float
    t1: float
    t2: float
    atr: float
    blocked: bool             # 线上会被已有持仓吞掉吗
    # 位置变量
    d1: float = 0.0           # |entry − EMA13| / ATR
    d2r: float = 0.0          # 信号 K (H−L) / ATR
    d2b: float = 0.0          # 信号 K |C−O| / ATR
    d2s: float = 0.0          # dir × 信号 K (C−O) / ATR —— 顺向实体（最贴用户原话）
    d3: float = 0.0           # dir × 近 3 根净位移 / ATR
    d4: float = 0.0           # 风险距离 / ATR
    # 结果变量
    hit: bool | None = None   # 纯括号：T1 先到 True / 保护位先到 False / 未裁决 None
    pnull: float = 0.0        # 几何零假设 S/(S+T)
    r: float = float("nan")   # 孤立重放的实际 R（含分批 + 13 线离场）
    hold: int = 0
    mfe: float = 0.0          # ATR 归一，固定 18 根窗口
    mae: float = 0.0
    mae_r: float = 0.0        # MAE / 风险距离
    mae3: float = 0.0         # 前 3 根内的 MAE（ATR）

    @property
    def net(self) -> float:
        return self.r - SPREAD / self.risk if self.risk > 0 else float("nan")

    @property
    def money(self) -> float:
        """净盈亏，每 1 单位名义本金，以日 ATR 为单位。

        R 不是货币：风险 0.03 ATR 的一笔和风险 0.30 ATR 的一笔，同样报 −1R，
        亏的钱差十倍。任何按风险距离分层的表，R 那一列的分母是被分层变量本身
        改动过的，**不能**用来比较跨档的钱。这一列才能。
        """
        return self.net * self.d4

    @property
    def in_rth(self) -> bool:
        return self.session == "RTH"


def harvest(bars: list[Bar], book: LevelBook, stack_bars: int = STACK_BARS,
            min_risk: float = MIN_RISK_PTS) -> tuple[list[Sig], list]:
    """v14 的四台状态机，**去掉单仓闸门**，吐出每一个入场事件。

    单仓闸门（Pine 的 `if pDir == 0`）在这里改成「记录一下会不会被吞掉」，
    其余转移逻辑逐字保留，包括 Recovery 无条件复位 / Vomy 只在真开仓时复位
    这个不对称——那是源码里的，不是我们的。
    """
    closes = [b.close for b in bars]
    e8s, e13s = ema(closes, 8), ema(closes, 13)
    e34s, e48s = ema(closes, 34), ema(closes, 48)
    e21s = ema(closes, 21)

    sBull = sBear = 0
    prev_sBull = prev_sBear = 0
    recL = recS = 0
    recLExt = recSExt = None
    vomS = vomL = 0
    vomSFin = vomLFin = None
    out: list[Sig] = []

    for i, b in enumerate(bars):
        if e48s[i] is None:
            continue
        e8, e13, e21, e34, e48 = e8s[i], e13s[i], e21s[i], e34s[i], e48s[i]
        sc, sh, sl = b.close, b.high, b.low
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        anchor, atr = lv

        prev_sBull, prev_sBear = sBull, sBear
        sBull = sBull + 1 if (e8 > e13 > e21 > e34 > e48) else 0
        sBear = sBear + 1 if (e8 < e13 < e21 < e34 < e48) else 0
        stack_bull, stack_bear = sBull > 0, sBear > 0

        hh10 = max(x.high for x in bars[max(0, i - 9):i + 1])
        ll10 = min(x.low for x in bars[max(0, i - 9):i + 1])
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)

        def emit(setup: str, d: int, prot: float, risk: float) -> None:
            out.append(Sig(setup=setup, direction=d,
                           session="RTH" if in_rth else "夜盘",
                           i=i, dt=b.dt, entry=sc, prot=prot, risk=risk,
                           t1=next_rung(sc, d, anchor, atr),
                           t2=next_rung(next_rung(sc, d, anchor, atr), d,
                                        anchor, atr),
                           atr=atr, blocked=False))

        # Recovery long
        if recL == 0 and sBull >= stack_bars and sc < e13:
            recL, recLExt = 1, sl
        elif recL == 1:
            recLExt = min(recLExt, sl)
            if sc < e34 or stack_bear:
                recL = 0
            elif sc > e13:
                if sc - recLExt >= min_risk:
                    emit("Recovery", +1, recLExt, sc - recLExt)
                recL = 0
        # Recovery short
        if recS == 0 and sBear >= stack_bars and sc > e13:
            recS, recSExt = 1, sh
        elif recS == 1:
            recSExt = max(recSExt, sh)
            if sc > e34 or stack_bull:
                recS = 0
            elif sc < e13:
                if recSExt - sc >= min_risk:
                    emit("Recovery", -1, recSExt, recSExt - sc)
                recS = 0
        # Vomy short
        if vomS == 0 and prev_sBull >= stack_bars and sc < e13 and sc < e8:
            vomS, vomSFin = 2, hh10
        elif vomS == 2:
            vomSFin = max(vomSFin, sh)
            if sc > e13:
                vomS = 0
            elif sh >= e13:
                if vomSFin - sc >= min_risk:
                    emit("Vomy", -1, vomSFin, vomSFin - sc)
                    vomS = 0
        # inverse Vomy long
        if vomL == 0 and prev_sBear >= stack_bars and sc > e13 and sc > e8:
            vomL, vomLFin = 2, ll10
        elif vomL == 2:
            vomLFin = min(vomLFin, sl)
            if sc < e13:
                vomL = 0
            elif sl <= e13:
                if sc - vomLFin >= min_risk:
                    emit("Vomy", +1, vomLFin, sc - vomLFin)
                    vomL = 0

    return out, e13s


# ══════════════════════════ 位置变量 & 结果变量 ═══════════════════════════════
def location_vars(sigs: list[Sig], bars: list[Bar],
                  e13s: list[float | None]) -> list[Sig]:
    keep: list[Sig] = []
    for s in sigs:
        i = s.i
        if i < 3 or e13s[i] is None or s.atr <= 0:
            continue
        b = bars[i]
        s.d1 = abs(s.entry - e13s[i]) / s.atr
        s.d2r = (b.high - b.low) / s.atr
        s.d2b = abs(b.close - b.open) / s.atr
        s.d2s = s.direction * (b.close - b.open) / s.atr
        s.d3 = s.direction * (b.close - bars[i - 3].close) / s.atr
        s.d4 = s.risk / s.atr
        keep.append(s)
    return keep


def _subseq(bars: list[Bar], subs: list[list[Bar]] | None, i: int) -> list[Bar]:
    return subs[i] if subs is not None else [bars[i]]


def bracket(s: Sig, bars: list[Bar], subs, cap: int = RACE_CAP) -> None:
    """纯括号：删掉 13 线离场，只跑保护位 vs T1。结果只反映入场质量。"""
    s.pnull = s.risk / (s.risk + abs(s.t1 - s.entry))
    d = s.direction
    for i in range(s.i + 1, min(s.i + 1 + cap, len(bars))):
        for sb in _subseq(bars, subs, i):
            ph = (sb.low <= s.prot) if d > 0 else (sb.high >= s.prot)
            gh = (sb.high >= s.t1) if d > 0 else (sb.low <= s.t1)
            if ph and gh:
                s.hit = None                      # 5m 分辨率下仍然含混
                return
            if gh:
                s.hit = True
                return
            if ph:
                s.hit = False
                return
    s.hit = None


def isolated_trade(s: Sig, bars: list[Bar], subs,
                   e13s: list[float | None], cap: int = RACE_CAP) -> None:
    """把这一个信号当成唯一一笔来重放 v14 的完整管理（分批 + 13 线离场）。

    管理从 i+1 开始（Pine 在入场 K 上不管理已开仓位）。同一根 K 上既触保护位又
    触目标时，用 5m 子 K 裁决先后；仍含混则按 Pine 的保守口径判保护位。
    """
    d, frac, legs = s.direction, 1.0, 0.0
    t1done = t2done = False
    for i in range(s.i + 1, min(s.i + 1 + cap, len(bars))):
        b = bars[i]
        e13 = e13s[i]
        hit_prot = (b.low <= s.prot) if d > 0 else (b.high >= s.prot)
        hit_t1 = (not t1done) and ((b.high >= s.t1) if d > 0 else (b.low <= s.t1))
        hit_t2 = t1done and (not t2done) and \
            ((b.high >= s.t2) if d > 0 else (b.low <= s.t2))
        struct = (b.close < e13) if d > 0 else (b.close > e13)

        prot_first = True
        if hit_prot and (hit_t1 or hit_t2):
            tgt = s.t1 if hit_t1 else s.t2
            for sb in _subseq(bars, subs, i):
                ph = (sb.low <= s.prot) if d > 0 else (sb.high >= s.prot)
                th = (sb.high >= tgt) if d > 0 else (sb.low <= tgt)
                if ph and th:
                    break
                if th:
                    prot_first = False
                    break
                if ph:
                    break

        if hit_prot and prot_first:
            s.r = legs + frac * (s.prot - s.entry) * d / s.risk
            s.hold = i - s.i
            return
        if hit_t1:
            legs += 0.50 * (s.t1 - s.entry) * d / s.risk
            frac -= 0.50
            t1done = True
        if hit_t2:
            legs += 0.25 * (s.t2 - s.entry) * d / s.risk
            frac -= 0.25
            t2done = True
        if hit_prot:
            s.r = legs + frac * (s.prot - s.entry) * d / s.risk
            s.hold = i - s.i
            return
        if struct:
            s.r = legs + frac * (b.close - s.entry) * d / s.risk
            s.hold = i - s.i
            return
    j = min(s.i + cap, len(bars) - 1)
    s.r = legs + frac * (bars[j].close - s.entry) * d / s.risk
    s.hold = j - s.i


def excursion(s: Sig, bars: list[Bar], subs, h: int = MFE_H) -> None:
    """固定 18 根（3 小时）前视窗口的 MFE / MAE，与任何离场规则无关。

    顺向位移 = d>0 时 (high−entry)、d<0 时 (entry−low)，取窗口最大值 = MFE。
    逆向位移 = d>0 时 (low−entry)、d<0 时 (entry−high)，取窗口最小值 = MAE(≤0)。
    """
    d = s.direction
    mfe = mae = mae3 = 0.0
    for k, i in enumerate(range(s.i + 1, min(s.i + 1 + h, len(bars)))):
        for sb in _subseq(bars, subs, i):
            fav = (sb.high - s.entry) if d > 0 else (s.entry - sb.low)
            adv = (sb.low - s.entry) if d > 0 else (s.entry - sb.high)
            mfe = max(mfe, fav)
            mae = min(mae, adv)
            if k < 3:
                mae3 = min(mae3, adv)
    s.mfe = mfe / s.atr
    s.mae = mae / s.atr
    s.mae3 = mae3 / s.atr
    s.mae_r = mae / s.risk if s.risk > 0 else float("nan")


# ═════════════════════════════ 统计工具 ══════════════════════════════════════
def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_sided(z: float) -> float:
    if z != z:
        return float("nan")
    return 2.0 * norm_sf(abs(z))


def z_geom(hits: list[bool], ps: list[float]) -> tuple[float, int, float, float]:
    """观测命中数 vs 泊松-二项零假设。返回 (z, n, obs_rate, null_rate)。"""
    n = len(hits)
    if n == 0:
        return float("nan"), 0, float("nan"), float("nan")
    k = sum(1 for h in hits if h)
    sp = sum(ps)
    v = sum(p * (1 - p) for p in ps)
    z = (k - sp) / math.sqrt(v) if v > 0 else float("nan")
    return z, n, k / n, sp / n


def trend_z(xs: list[float], ys: list[int], ps: list[float]) -> float:
    """带 offset 的趋势得分检验（Cochran-Armitage 在异质零假设下的推广）。

    模型 logit(p_j) = offset_j + beta·x_j 的 score test：
        U = Σ (x_j − x̄_w)(y_j − p_j),  Var = Σ (x_j − x̄_w)² p_j(1−p_j)
    x̄_w 是以 p(1−p) 为权的 x 均值。beta>0 ⇒ z>0 ⇒ x 越大越容易命中。
    """
    w = [p * (1 - p) for p in ps]
    W = sum(w)
    if W <= 0 or len(xs) < 3:
        return float("nan")
    xbar = sum(x * wi for x, wi in zip(xs, w)) / W
    U = sum((x - xbar) * (y - p) for x, y, p in zip(xs, ys, ps))
    V = sum((x - xbar) ** 2 * wi for x, wi in zip(xs, w))
    return U / math.sqrt(V) if V > 0 else float("nan")


def ca_z(xs: list[float], ys: list[int]) -> float:
    """原味 Cochran-Armitage（忽略几何零假设，只看原始命中率的趋势）。"""
    n = len(ys)
    if n < 3:
        return float("nan")
    p = sum(ys) / n
    xbar = sum(xs) / n
    U = sum((x - xbar) * (y - p) for x, y in zip(xs, ys))
    V = p * (1 - p) * sum((x - xbar) ** 2 for x in xs)
    return U / math.sqrt(V) if V > 0 else float("nan")


def spearman(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """秩相关 + 正态近似 z（z = rho·sqrt(n−1)）。"""
    n = len(xs)
    if n < 5:
        return float("nan"), float("nan")

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return float("nan"), float("nan")
    rho = num / (dx * dy)
    return rho, rho * math.sqrt(n - 1)


def tstat(xs: list[float]) -> float:
    if len(xs) < 3:
        return float("nan")
    sd = st.stdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd > 0 else float("nan")


def quantile_bins(vals: list[float], k: int = NQ) -> list[int]:
    """按分位数切 k 档；并列值多时档内 n 会不均，如实呈现。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    bins = [0] * len(vals)
    for rank, idx in enumerate(order):
        bins[idx] = min(k - 1, rank * k // len(vals))
    return bins


def q(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    a = (len(s) - 1) * p
    lo, hi = int(a), min(int(a) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (a - lo)


def f(x, p=2, sign=False):
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


# ═══════════════════════════ 分层表 ══════════════════════════════════════════
VARS = [
    ("D1", "|入场价−EMA13| / ATR", lambda s: s.d1, "离参考线越远"),
    ("D2r", "信号K (H−L) / ATR", lambda s: s.d2r, "信号K越大"),
    ("D2b", "信号K |C−O| / ATR", lambda s: s.d2b, "信号K实体越大"),
    ("D2s", "信号K 顺向实体 (C−O)·dir / ATR", lambda s: s.d2s,
     "剧烈顺向 K 上入场"),
    ("D3", "近3根净位移(顺向) / ATR", lambda s: s.d3, "追得越凶"),
    ("D4", "风险距离 / ATR", lambda s: s.d4, "离结构止损越远"),
]


def strata_table(sigs: list[Sig], getter, out: list[str],
                 k: int = NQ) -> dict:
    """一个位置变量的分位数分层表 + 单调性检验。"""
    res = [s for s in sigs if s.hit is not None]
    if len(res) < 5 * k:
        out.append(f"（样本不足：可裁决 n={len(res)}）")
        return {}
    vals = [getter(s) for s in res]
    bins = quantile_bins(vals, k)

    out.append("| 档 | 变量区间 | n | 纯括号命中率 [95%CI] | 几何零假设 | "
               "超额 pp | z_geom | 均R | 净均R | 净均(ATR钱) | MFE(ATR) | MAE(ATR) |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for j in range(k):
        g = [s for s, bn in zip(res, bins) if bn == j]
        gv = [v for v, bn in zip(vals, bins) if bn == j]
        if not g:
            continue
        bump()
        z, n, obs, null = z_geom([s.hit for s in g], [s.pnull for s in g])
        kk = sum(1 for s in g if s.hit)
        lo, hi = stats.wilson(kk, n)
        rs = [s.r for s in g]
        ns = [s.net for s in g]
        out.append(
            f"| Q{j+1} | {min(gv):.3f}–{max(gv):.3f} | {n} | "
            f"{100*obs:.1f}% [{100*lo:.1f},{100*hi:.1f}] | {100*null:.1f}% | "
            f"{100*(obs-null):+.1f} | {z:+.2f} | {st.mean(rs):+.3f} | "
            f"{st.mean(ns):+.3f} | {1000*st.mean([s.money for s in g]):+.1f} | "
            f"{st.mean([s.mfe for s in g]):.3f} | "
            f"{st.mean([s.mae for s in g]):+.3f} |")

    ranks = [float(b + 1) for b in bins]
    ys = [1 if s.hit else 0 for s in res]
    ps = [s.pnull for s in res]
    tz_rank = trend_z(ranks, ys, ps)
    tz_cont = trend_z(vals, ys, ps)
    caz = ca_z(ranks, ys)
    rho_r, z_r = spearman(vals, [s.r for s in res])
    rho_n, z_n = spearman(vals, [s.net for s in res])
    rho_m, z_m = spearman(vals, [s.money for s in res])
    rho_mae, z_mae = spearman(vals, [s.mae for s in res])
    bump(5)
    out.append("")
    out.append("（「净均(ATR钱)」= 每笔净盈亏 ×1000，单位是日 ATR / 每 1 单位名义本金。"
               "跨档比较只能看这一列——R 的分母就是被分层的那个变量。）")
    out.append("")
    out.append(f"- **单调性（超额 vs 档位）**：趋势得分检验 z = **{tz_rank:+.2f}** "
               f"(p={two_sided(tz_rank):.3f})；用连续变量而非档位 z = {tz_cont:+.2f} "
               f"(p={two_sided(tz_cont):.3f})。原味 Cochran-Armitage（忽略几何零假设）"
               f"z = {caz:+.2f} (p={two_sided(caz):.3f})。")
    out.append(f"- **秩相关**：均R ρ = {rho_r:+.3f} (z={z_r:+.2f}, "
               f"p={two_sided(z_r):.3f})；净均R ρ = {rho_n:+.3f} "
               f"(z={z_n:+.2f}, p={two_sided(z_n):.3f})；"
               f"**净钱(ATR) ρ = {rho_m:+.3f} (z={z_m:+.2f}, "
               f"p={two_sided(z_m):.3f})**；MAE ρ = {rho_mae:+.3f} (z={z_mae:+.2f})。")
    return {"tz": tz_rank, "tz_cont": tz_cont, "ca": caz,
            "rho_r": rho_r, "z_r": z_r, "rho_n": rho_n, "z_n": z_n,
            "rho_m": rho_m, "z_m": z_m, "n": len(res)}


def cond_trend_z(sigs: list[Sig], xget, sget, k: int = NQ) -> float:
    """在 sget 的分位数分层内部做趋势检验，再把各层的 U/V 汇总（Mantel-Haenszel）。

    这是把「追」和「止损小」拆开的唯一办法：D3 与 D4 相关 0.38、D2r 与 D4 相关
    0.58，不控制风险距离就分不清「追得凶所以差」还是「止损被追出来的大小所以差」。
    层内把 x 换成 0–1 的秩，避免各层量纲不同时被方差最大的那层主导。
    """
    res = [s for s in sigs if s.hit is not None]
    if len(res) < 10 * k:
        return float("nan")
    bins = quantile_bins([sget(s) for s in res], k)
    U = V = 0.0
    for j in range(k):
        g = [s for s, b in zip(res, bins) if b == j]
        if len(g) < 10:
            continue
        raw = [xget(s) for s in g]
        order = sorted(range(len(raw)), key=lambda t: raw[t])
        xs = [0.0] * len(raw)
        for rk, idx in enumerate(order):
            xs[idx] = rk / (len(raw) - 1)
        ys = [1 if s.hit else 0 for s in g]
        ps = [s.pnull for s in g]
        w = [p * (1 - p) for p in ps]
        W = sum(w)
        if W <= 0:
            continue
        xbar = sum(x * wi for x, wi in zip(xs, w)) / W
        U += sum((x - xbar) * (y - p) for x, y, p in zip(xs, ys, ps))
        V += sum((x - xbar) ** 2 * wi for x, wi in zip(xs, w))
    return U / math.sqrt(V) if V > 0 else float("nan")


def cond_spearman_z(sigs: list[Sig], xget, yget, sget,
                    k: int = NQ) -> tuple[float, float]:
    """层内秩相关，用 sqrt(n−1) 加权做 Stouffer 合并。返回 (加权ρ, 合并z)。"""
    if len(sigs) < 10 * k:
        return float("nan"), float("nan")
    bins = quantile_bins([sget(s) for s in sigs], k)
    num = den = 0.0
    wr = wn = 0.0
    for j in range(k):
        g = [s for s, b in zip(sigs, bins) if b == j]
        if len(g) < 10:
            continue
        rho, z = spearman([xget(s) for s in g], [yget(s) for s in g])
        if rho != rho:
            continue
        w = math.sqrt(len(g) - 1)
        num += z * w
        den += w * w
        wr += rho * len(g)
        wn += len(g)
    return (wr / wn if wn else float("nan"),
            num / math.sqrt(den) if den > 0 else float("nan"))


def cross_2x2(sigs: list[Sig], out: list[str]) -> dict:
    """D1（近/远）× D3（不追/追）的 2×2。切点取各自中位数。"""
    res = [s for s in sigs if s.hit is not None]
    if len(res) < 40:
        out.append("（样本不足）")
        return {}
    m1 = st.median([s.d1 for s in res])
    m3 = st.median([s.d3 for s in res])
    out.append(f"切点：D1 中位 {m1:.3f} ATR，D3 中位 {m3:+.3f} ATR。")
    out.append("")
    out.append("| 格子 | n | 命中率 [CI] | 几何零假设 | 超额 pp | z_geom | "
               "均R | 净均R | 净均(ATR钱)×1000 | 均MAE(ATR) |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    cells = {}
    for lbl, fn in (
        ("近13 · 不追", lambda s: s.d1 <= m1 and s.d3 <= m3),
        ("近13 · 追", lambda s: s.d1 <= m1 and s.d3 > m3),
        ("远13 · 不追", lambda s: s.d1 > m1 and s.d3 <= m3),
        ("远13 · 追", lambda s: s.d1 > m1 and s.d3 > m3),
    ):
        g = [s for s in res if fn(s)]
        if not g:
            continue
        bump()
        z, n, obs, null = z_geom([s.hit for s in g], [s.pnull for s in g])
        kk = sum(1 for s in g if s.hit)
        lo, hi = stats.wilson(kk, n)
        cells[lbl] = {"n": n, "obs": obs, "null": null, "z": z,
                      "r": st.mean([s.r for s in g]),
                      "net": st.mean([s.net for s in g]),
                      "excess": obs - null}
        out.append(f"| {lbl} | {n} | {100*obs:.1f}% [{100*lo:.1f},{100*hi:.1f}] | "
                   f"{100*null:.1f}% | {100*(obs-null):+.1f} | {z:+.2f} | "
                   f"{st.mean([s.r for s in g]):+.3f} | "
                   f"{st.mean([s.net for s in g]):+.3f} | "
                   f"{1000*st.mean([s.money for s in g]):+.1f} | "
                   f"{st.mean([s.mae for s in g]):+.3f} |")
    # 交互项：把 D1、D3 都编码成 ±0.5，交互 = 乘积
    xs = [(1 if s.d1 > m1 else 0) * (1 if s.d3 > m3 else 0) for s in res]
    ys = [1 if s.hit else 0 for s in res]
    ps = [s.pnull for s in res]
    zi = trend_z([float(x) for x in xs], ys, ps)
    bump()
    out.append("")
    out.append(f"- 「远且追」这个格子相对其余三格的交互得分 z = **{zi:+.2f}** "
               f"(p={two_sided(zi):.3f})。")
    return cells


# ═══════════════════════════ 数据集组装 ═════════════════════════════════════
def build(symbol: str, rth_only: bool) -> dict:
    bars, subs = load_10m(symbol, rth_only)
    book = LevelBook(data.load(symbol, "20y", "1d"))
    sigs, e13s = harvest(bars, book)
    sigs = location_vars(sigs, bars, e13s)
    # 「线上会不会被吞掉」= 真引擎里这个 (bar, setup, 方向) 有没有真的成交
    live, _ = run_v14(bars, book, subs, path_resolve=True)
    filled = {(t.entry_i, t.setup, t.direction) for t in live}
    for s in sigs:
        s.blocked = (s.i, s.setup, s.direction) not in filled
    for s in sigs:
        bracket(s, bars, subs)
        isolated_trade(s, bars, subs, e13s)
        excursion(s, bars, subs)
    return {"symbol": symbol, "bars": bars, "subs": subs, "book": book,
            "e13": e13s, "sigs": sigs}


def sequenced(ds: dict) -> list[Sig]:
    """线上口径：跑真正的 v14 引擎，把成交的那些交易也做成 Sig 以便同表比较。"""
    bars, subs, book, e13s = ds["bars"], ds["subs"], ds["book"], ds["e13"]
    trades, _ = run_v14(bars, book, subs, path_resolve=True)
    out: list[Sig] = []
    for t in trades:
        i = t.entry_i
        if i < 3 or e13s[i] is None or t.atr <= 0:
            continue
        b = bars[i]
        s = Sig(setup=t.setup, direction=t.direction, session=t.session, i=i,
                dt=t.entry_dt, entry=t.entry, prot=t.prot, risk=t.risk,
                t1=t.t1, t2=t.t2, atr=t.atr, blocked=False)
        s.d1 = abs(s.entry - e13s[i]) / s.atr
        s.d2r = (b.high - b.low) / s.atr
        s.d2b = abs(b.close - b.open) / s.atr
        s.d3 = s.direction * (b.close - bars[i - 3].close) / s.atr
        s.d4 = s.risk / s.atr
        bracket(s, bars, subs)
        excursion(s, bars, subs)
        s.r = t.r                      # 线上排队口径的真实 R
        s.hold = t.hold
        out.append(s)
    return out


# ═══════════════════════════════ 报告 ═══════════════════════════════════════
def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def overall_block(sigs: list[Sig], label: str, out: list[str]) -> dict:
    res = [s for s in sigs if s.hit is not None]
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    bump()
    kk = sum(1 for s in res if s.hit)
    lo, hi = stats.wilson(kk, n)
    rs = [s.r for s in sigs]
    ns = [s.net for s in sigs]
    out.append(f"- **{label}**：信号 {len(sigs)} 个，可裁决 {n}（"
               f"{len(sigs)-n} 个在 {RACE_CAP} 根内 / 5m 分辨率下无法裁决）。"
               f"纯括号命中 {100*obs:.1f}% [{100*lo:.1f},{100*hi:.1f}]，"
               f"几何零假设 {100*null:.1f}%，超额 {100*(obs-null):+.1f} pp，"
               f"**z_geom = {z:+.2f}**。均R {st.mean(rs):+.3f}（t={tstat(rs):+.2f}），"
               f"净均R {st.mean(ns):+.3f}，总净R {sum(ns):+.1f}。")
    return {"z": z, "n": n, "obs": obs, "null": null,
            "avg_r": st.mean(rs), "avg_net": st.mean(ns)}


def gate_test(sigs: list[Sig], name: str, fn, out: list[str],
              base_avg: float) -> None:
    """一个候选闸门：必须验证单笔质量（均净R）是否真提升，不能只看总R（纪律 6）。"""
    g = [s for s in sigs if fn(s)]
    if len(g) < 30:
        out.append(f"| {name} | {len(g)} | 样本不足 | | | | |")
        return
    bump()
    ns = [s.net for s in g]
    res = [s for s in g if s.hit is not None]
    z, _, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    # 有限总体修正的选择 z：从 N 个里抽 n 个，均值是否显著高于全样本
    N = len(sigs)
    allns = [s.net for s in sigs]
    mu = st.mean(allns)
    var = st.pvariance(allns)
    se = math.sqrt(var / len(g) * (N - len(g)) / (N - 1)) if N > len(g) else float("nan")
    zsel = (st.mean(ns) - mu) / se if se and se == se and se > 0 else float("nan")
    out.append(f"| {name} | {len(g)} ({100*len(g)/N:.0f}%) | {st.mean(ns):+.3f} | "
               f"{st.mean(ns)-base_avg:+.3f} | {tstat(ns):+.2f} | {zsel:+.2f} | "
               f"{sum(ns):+.1f} | {z:+.2f} |")


def main() -> None:
    o: list[str] = []
    A = o.append

    prim = build("ES=F", False)
    ctrl = build("^GSPC", True)
    seq = sequenced(prim)

    sigs = prim["sigs"]
    bars = prim["bars"]

    A("# V15 · 入场位置质量：「追」到底有多贵")
    A("")
    A(f"生成脚本 `research/satylab/study_entry_location.py`。"
      f"主样本 **ES=F 10m**（由 60d 5m 聚合，含完整 23 小时时段，与 "
      f"CAPITALCOM:SPX500 作息一致），{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，"
      f"{len(bars)} 根 setup K。^GSPC 10m（仅 RTH）作对照。"
      f"路径判定全部落到 5 分钟子 K（纪律 3）。")
    A("")
    A("## 0 · 这一轮在回答什么")
    A("")
    A("用户的诊断是机制性的，不是感觉：")
    A("")
    A("> 「你每次买卖的时机，要么是在剧烈下跌的时候去卖，要么是在剧烈上涨的时候去买，"
      "那肯定不是什么好位置。」")
    A("")
    A("代码上确有其事——v14 的入场价就是**信号 K 的收盘价**，信号 K 越大，入场离 "
      "EMA13、离结构止损就越远。所以这四个数在入场那一刻全都是已知的：")
    A("")
    A("| 记号 | 定义 | 「越大」的含义 |")
    A("|---|---|---|")
    for key, desc, _, mean_of_big in VARS:
        A(f"| {key} | {desc} | {mean_of_big} |")
    A("")
    A("**结果变量**用纯括号（保护位 vs T1 谁先到，删掉 13 线离场），这样结果只反映"
      "入场质量、不掺出场规则；另外报告孤立重放的实际 R（含分批）、扣 "
      f"{SPREAD} 点点差的净 R、以及固定 {MFE_H} 根（3 小时）窗口的 MFE / MAE。")
    A("")

    # ── 抽样口径 ────────────────────────────────────────────────────────────
    A("## 1 · 抽样口径与样本量")
    A("")
    nb = sum(1 for s in sigs if s.blocked)
    A(f"主样本是**把 v14 的单仓闸门拿掉之后状态机吐出的全部入场事件**："
      f"{len(sigs)} 个。其中 {nb} 个（{100*nb/len(sigs):.0f}%）在线上会被当时的持仓"
      f"吞掉。用全部信号而不是成交的那些，是因为「有没有被上一笔挡住」是排队顺序的"
      f"产物，与入场位置质量无关，按它筛样本会引入选择偏差。线上排队口径的 "
      f"{len(seq)} 笔在第 6 节单独复核。")
    A("")
    overall_block(sigs, "全部信号（ES=F 10m）", o)
    overall_block([s for s in sigs if s.in_rth], "其中 RTH", o)
    overall_block([s for s in sigs if not s.in_rth], "其中 夜盘", o)
    overall_block(ctrl["sigs"], "对照 ^GSPC 10m RTH", o)
    A("")
    A("这就是上一轮那个 −1.68 的复现：**去掉排队效应、样本翻倍之后，整体仍然是负的**。"
      "下面把它拆开，看负在哪儿。")
    A("")

    # ── 变量之间的相关 ──────────────────────────────────────────────────────
    A("### 1.1 四个位置变量彼此并不独立")
    A("")
    A("| | D1 | D2r | D2b | D3 | D4 |")
    A("|---|---|---|---|---|---|")
    getters = [g for _, _, g, _ in VARS]
    keys = [k for k, _, _, _ in VARS]
    for a_i, ka in enumerate(keys):
        row = [f"| {ka} "]
        for b_i in range(len(keys)):
            r = corr([getters[a_i](s) for s in sigs], [getters[b_i](s) for s in sigs])
            row.append(f"| {r:+.2f} ")
        A("".join(row) + "|")
    A("")
    A("D1 与 D4 高度相关是结构性的：Recovery 的风险距离就是「收盘价 − 回踩低点」，"
      "而收盘价越高于 13，这个距离通常也越大。所以 D1/D4 的两张表不是两个独立证据。")
    A("")

    # ── 主表 ────────────────────────────────────────────────────────────────
    A("## 2 · 四个位置变量的分位数分层表（全样本）")
    A("")
    summary = {}
    for key, desc, g, big in VARS:
        A(f"### 2.{keys.index(key)+1} {key} — {desc}")
        A("")
        summary[key] = strata_table(sigs, g, o)
        A("")

    # ── 单调性汇总 ──────────────────────────────────────────────────────────
    A("## 3 · 单调性检验汇总")
    A("")
    A("判定标准：**单调才算证据**，最好那一档孤零零地好不算。趋势得分检验是带 "
      "offset 的 Cochran-Armitage 推广（零假设 p_j = S_j/(S_j+T_j) 逐笔不同，"
      "所以不能用原味 CA），z<0 = 变量越大命中越差 = 用户的假设成立。")
    A("")
    A("| 变量 | 「越大」= | 趋势 z(超额) | p | 净均R ρ | z | 净钱(ATR) ρ | z | 结论 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for key, desc, _, big in VARS:
        m = summary.get(key, {})
        if not m:
            continue
        tz = m["tz"]
        verdict = ("**支持「追很贵」**" if tz < -1.96 else
                   "**反向：追反而好**" if tz > 1.96 else "无证据（|z|<1.96）")
        A(f"| {key} | {big} | {f(tz,2,True)} | {two_sided(tz):.3f} | "
          f"{f(m['rho_n'],3,True)} | {f(m['z_n'],2,True)} | "
          f"{f(m['rho_m'],3,True)} | {f(m['z_m'],2,True)} | {verdict} |")
    A("")
    A("**读表警告**：`净均R` 那一列在 D1 / D2r / D4 上都显著为正，但这三个变量与"
      "风险距离的相关分别是 0.61 / 0.58 / 1.00，而 R 的分母**就是风险距离**。"
      "一笔风险 0.03 ATR 的交易和一笔风险 0.30 ATR 的交易同样亏 1R，亏的钱差十倍。"
      "所以看钱只能看 `净钱(ATR)` 那一列。")
    A("")

    # ── 控制风险距离之后 ───────────────────────────────────────────────────
    A("### 3.1 控制风险距离之后，「追」还剩下什么")
    A("")
    A("D3 与 D4 相关 0.38、D2r 与 D4 相关 0.58：追出来的信号 K 更大，止损也被推得"
      "更远。不把 D4 按住，就分不清「追得凶所以差」和「止损小所以差」。下表在 "
      "**D4 五档之内**重做同一批检验，再用 Mantel-Haenszel 汇总。")
    A("")
    A("| 变量（控制 D4 后） | 超额趋势 z | p | 净钱(ATR) 层内 ρ | 合并 z | "
      "|MAE| 层内 ρ | 合并 z |")
    A("|---|---|---|---|---|---|---|")
    for key, desc, g, big in VARS:
        if key == "D4":
            continue
        cz = cond_trend_z(sigs, g, lambda s: s.d4)
        rm, zm = cond_spearman_z(sigs, g, lambda s: s.money, lambda s: s.d4)
        ra, za = cond_spearman_z(sigs, g, lambda s: -s.mae, lambda s: s.d4)
        bump(3)
        A(f"| {key} — {big} | {f(cz,2,True)} | {two_sided(cz):.3f} | "
          f"{f(rm,3,True)} | {f(zm,2,True)} | {f(ra,3,True)} | {f(za,2,True)} |")
    A("")
    A("反过来也做一遍：控制住 D3（追的程度）之后，风险距离 D4 还剩多少解释力。")
    A("")
    cz4 = cond_trend_z(sigs, lambda s: s.d4, lambda s: s.d3)
    rm4, zm4 = cond_spearman_z(sigs, lambda s: s.d4, lambda s: s.money,
                               lambda s: s.d3)
    bump(2)
    A(f"- D4（控制 D3 后）：超额趋势 z = **{f(cz4,2,True)}** "
      f"(p={two_sided(cz4):.3f})，净钱层内 ρ = {f(rm4,3,True)} "
      f"(合并 z = {f(zm4,2,True)})。")
    A("")

    # ── 交互 ────────────────────────────────────────────────────────────────
    A("## 4 · D1 × D3 交互（近/远 × 追/不追）")
    A("")
    cells = cross_2x2(sigs, o)
    A("")

    # ── 分时段 ──────────────────────────────────────────────────────────────
    A("## 5 · 分 RTH / 夜盘")
    A("")
    A("线上账本 73% 的交易在夜盘，所以这一节不是可选项。")
    for lbl, sub in (("RTH", [s for s in sigs if s.in_rth]),
                     ("夜盘", [s for s in sigs if not s.in_rth])):
        A("")
        A(f"### 5.{1 if lbl=='RTH' else 2} {lbl}（n={len(sub)}）")
        for key, desc, g, big in VARS:
            A("")
            A(f"**{key} — {desc}**")
            A("")
            strata_table(sub, g, o)
        A("")
        A(f"**{lbl} 的 D1×D3 交互**")
        A("")
        cross_2x2(sub, o)

    # ── 线上排队口径复核 ────────────────────────────────────────────────────
    A("")
    A("## 6 · 线上排队口径复核（真正成交的那些）")
    A("")
    A(f"跑真正的 v14 引擎（单仓闸门在位，5m 路径裁决），{len(seq)} 笔。"
      f"如果第 2 节的结论只是抽样口径的产物，这里应该看不到同样的方向。")
    A("")
    overall_block(seq, f"{prim['symbol']} 10m 线上排队口径", o)
    A("")
    for key, desc, g, big in VARS:
        A(f"**{key} — {desc}**")
        A("")
        strata_table(seq, g, o)
        A("")

    # ── 对照 ────────────────────────────────────────────────────────────────
    A("## 7 · ^GSPC 10m RTH 对照")
    A("")
    A("^GSPC 只有 RTH、ATR 与 SPX500 的比值 mean 1.117 / sd 0.083（不是常数，见 "
      "`levels.py`），所以这只是**独立标的上的方向性对照**，不是第二个证据。")
    A("")
    for key, desc, g, big in VARS:
        A(f"**{key} — {desc}**")
        A("")
        strata_table(ctrl["sigs"], g, o)
        A("")

    # ── 候选闸门 ────────────────────────────────────────────────────────────
    A("## 8 · 如果照着做，能挣到钱吗")
    A("")
    A("纪律 6：任何「砍掉笔数后总 R 转正」都必须先验证**单笔质量**（均净R）"
      "是否真的显著提升。下表的 `Δ均净R` 和 `t` 就是这个验证；`z_sel` 是有限总体"
      "修正下「从全样本里抽这么多笔，均值能高出这么多」的选择 z。")
    A("")
    base_avg = st.mean([s.net for s in sigs])
    A(f"基线（全部 {len(sigs)} 个信号）均净R = **{base_avg:+.3f}**，"
      f"总净R = {sum(s.net for s in sigs):+.1f}。")
    A("")
    A("| 闸门 | n (占比) | 均净R | Δ均净R | t | z_sel | 总净R | z_geom |")
    A("|---|---|---|---|---|---|---|---|")
    d1q = [q([s.d1 for s in sigs], x) for x in (0.2, 0.4, 0.5, 0.6)]
    d3q = [q([s.d3 for s in sigs], x) for x in (0.2, 0.4, 0.5, 0.6)]
    d4q = [q([s.d4 for s in sigs], x) for x in (0.2, 0.4, 0.5, 0.6)]
    gates = [
        (f"D1 ≤ p20 ({d1q[0]:.3f} ATR)", lambda s: s.d1 <= d1q[0]),
        (f"D1 ≤ p40 ({d1q[1]:.3f})", lambda s: s.d1 <= d1q[1]),
        (f"D1 ≤ 中位 ({d1q[2]:.3f})", lambda s: s.d1 <= d1q[2]),
        (f"D3 ≤ p20 ({d3q[0]:+.3f})", lambda s: s.d3 <= d3q[0]),
        (f"D3 ≤ 中位 ({d3q[2]:+.3f})", lambda s: s.d3 <= d3q[2]),
        (f"D3 ≥ 中位（反着做：只追）", lambda s: s.d3 > d3q[2]),
        (f"D4 ≤ 中位 ({d4q[2]:.3f})", lambda s: s.d4 <= d4q[2]),
        (f"D4 ≥ 中位（大止损）", lambda s: s.d4 > d4q[2]),
        ("D1≤中位 且 D3≤中位（近且不追）", lambda s: s.d1 <= d1q[2] and s.d3 <= d3q[2]),
        ("D1>中位 且 D3>中位（远且追）", lambda s: s.d1 > d1q[2] and s.d3 > d3q[2]),
        ("只 RTH", lambda s: s.in_rth),
        ("只 RTH 且 D1≤中位", lambda s: s.in_rth and s.d1 <= d1q[2]),
    ]
    for nm, fn in gates:
        gate_test(sigs, nm, fn, o, base_avg)
    A("")
    thr = 1.96
    A(f"多重比较：全文共检视 **{CELLS} 个格子**（分层格、趋势检验、交互格、闸门），"
      f"Bonferroni 门槛 |z| > {abs(_bonf_z(CELLS)):.2f}（α=0.05 双侧）。"
      f"常规 |z|>{thr} 在这个 family size 下基本没有意义。")
    A("")

    # ── MFE/MAE 形状 ────────────────────────────────────────────────────────
    A("## 9 · MFE / MAE：入场后立刻挨打了吗")
    A("")
    A(f"固定 {MFE_H} 根（3 小时）前视窗口，与任何离场规则无关。"
      "如果「追」真的是坏位置，最直接的指纹是**入场后前 3 根的逆行**更深。")
    A("")
    A("| 分组 | n | 均MFE(ATR) | 均MAE(ATR) | 均MAE(R) | 前3根均MAE(ATR) | MFE/|MAE| |")
    A("|---|---|---|---|---|---|---|")
    m1 = st.median([s.d1 for s in sigs])
    m3 = st.median([s.d3 for s in sigs])
    for lbl, fn in (("全部", lambda s: True),
                    ("近13 (D1≤中位)", lambda s: s.d1 <= m1),
                    ("远13 (D1>中位)", lambda s: s.d1 > m1),
                    ("不追 (D3≤中位)", lambda s: s.d3 <= m3),
                    ("追 (D3>中位)", lambda s: s.d3 > m3),
                    ("远且追", lambda s: s.d1 > m1 and s.d3 > m3),
                    ("近且不追", lambda s: s.d1 <= m1 and s.d3 <= m3)):
        g = [s for s in sigs if fn(s)]
        if not g:
            continue
        bump()
        mfe = st.mean([s.mfe for s in g])
        mae = st.mean([s.mae for s in g])
        A(f"| {lbl} | {len(g)} | {mfe:.3f} | {mae:+.3f} | "
          f"{st.mean([s.mae_r for s in g]):+.3f} | "
          f"{st.mean([s.mae3 for s in g]):+.3f} | "
          f"{mfe/abs(mae) if mae else float('nan'):.3f} |")
    A("")
    # MAE(R) 的秩相关，对每个变量
    A("**位置变量 vs 逆行深度的秩相关**（ρ>0 = 变量越大逆行越深，用 |MAE| 表述）：")
    A("")
    for key, desc, g, big in VARS:
        rho, z = spearman([g(s) for s in sigs], [-s.mae for s in sigs])
        rho3, z3 = spearman([g(s) for s in sigs], [-s.mae3 for s in sigs])
        rhor, zr = spearman([g(s) for s in sigs], [-s.mae_r for s in sigs])
        bump(3)
        A(f"- {key}（{big}）：|MAE|(ATR) ρ = {rho:+.3f} (z={z:+.2f})；"
          f"前3根 |MAE| ρ = {rho3:+.3f} (z={z3:+.2f})；"
          f"|MAE|/风险 ρ = {rhor:+.3f} (z={zr:+.2f})")
    A("")

    # ── 反例 ────────────────────────────────────────────────────────────────
    A("## 10 · 反例检查")
    A("")
    A("动量策略在某些市场里就是「追得越凶越好」。这一节如实报告任何与用户假设"
      "相反的格子。")
    A("")
    hi = []
    for key, desc, g, big in VARS:
        res = [s for s in sigs if s.hit is not None]
        vals = [g(s) for s in res]
        bins = quantile_bins(vals, NQ)
        for j in range(NQ):
            grp = [s for s, b in zip(res, bins) if b == j]
            if len(grp) < 20:
                continue
            z, n, obs, null = z_geom([s.hit for s in grp], [s.pnull for s in grp])
            hi.append((z, key, j + 1, n, obs, null, st.mean([s.net for s in grp])))
    hi.sort(reverse=True)
    A("| 格子 | n | 命中率 | 几何零假设 | 超额 pp | z_geom | 均净R |")
    A("|---|---|---|---|---|---|---|")
    for z, key, j, n, obs, null, net in hi[:5]:
        A(f"| {key} Q{j}（最好的几档） | {n} | {100*obs:.1f}% | {100*null:.1f}% | "
          f"{100*(obs-null):+.1f} | {z:+.2f} | {net:+.3f} |")
    for z, key, j, n, obs, null, net in hi[-3:]:
        A(f"| {key} Q{j}（最差的几档） | {n} | {100*obs:.1f}% | {100*null:.1f}% | "
          f"{100*(obs-null):+.1f} | {z:+.2f} | {net:+.3f} |")
    A("")
    A(f"全样本 {len(hi)} 个分层格的 z_geom：最大 {max(h[0] for h in hi):+.2f}，"
      f"中位 {st.median([h[0] for h in hi]):+.2f}，"
      f"最小 {min(h[0] for h in hi):+.2f}。")
    A("")

    txt = "\n".join(o)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(txt)
    print(txt)
    return {"sigs": sigs, "seq": seq, "ctrl": ctrl["sigs"], "summary": summary,
            "cells": CELLS}


def _bonf_z(m: int, alpha: float = 0.05) -> float:
    """Bonferroni 双侧临界 z（二分求解，避免引入 scipy）。"""
    target = alpha / max(m, 1) / 2.0
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if norm_sf(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    main()
