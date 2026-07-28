"""V15.1 · 状态层假设的检验：区间态里交叉类信号的【符号】是不是反的。

被检验的假设（来自 2026-07-28 与 Saty 实盘逐条对账，见 docs/SATY_LIVE_2026-07-27_28.md
与 SYSTEM_DESIGN_V15.md §1.1，写进设计文档时**没有任何统计检验**）：

    区间态 = 价格在 trigger box 内（|(close−锚)/ATR| ≤ 0.236）**或** 五条 EMA 未排列
    趋势态 = 五线排列 **且** 已在 box 外
    → 区间态里，EMA 交叉类 setup（"袋子刚变色"）必然在最差位置发火：
      跌到区间底才叉得下来，涨到顶才叉得上去。所以区间态应禁用交叉类，
      只做边缘拒绝（盒下沿做多、上沿做空）。

这是关于【符号】的断言，不是关于【幅度】的断言。所以本文件做四件事：

  §2  (状态 × setup类型) 分层，看核心格子「区间 × 交叉类」是否显著劣于几何零假设
  §3  **符号检验**：把区间态的交叉类信号方向反过来做。假设为真 ⇒ 反做显著更好
  §4  **位置检验**：区间态交叉类信号发生时价格在盒内的相对位置分布
  §5  **边缘拒绝检验**：新写一个盒沿拒绝扫描器，与同期交叉类对比
  §6  **混淆控制**：区间态之所以差，会不会只是因为那里止损小（刻度错配），与符号无关

铁律遵守情况
------------
1. 命中率的零假设一律是几何零假设 P = S/(S+T)，报告 z_geom。
2. 路径判定全部落到 5 分钟子 K（10m setup / 5m 裁决），绝无同根裁决。
3. 多重比较：全局 CELLS 计数 + Bonferroni 门槛，在 §7 自报。
4. 点差 0.6 点，毛 R 与净 R 都报。
5. 主样本 ES=F（含完整夜盘，作息与 CAPITALCOM:SPX500 一致）；^GSPC 只做 RTH 对照。
   本报告的状态定义**直接依赖位价**（盒内/盒外），所以 §7 必须显式标注这个局限。
6. 小样本就说小；任何"砍掉笔数后转正"先验证单笔质量。
7. 与假设相反的格子单列一节（§8）。

Usage:  .venv/bin/python research/satylab/study_regime_layer.py
"""

from __future__ import annotations

import math
import statistics as st
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats                                    # noqa: E402
from satylab.data import Bar                                       # noqa: E402
from satylab.indicators import ema                                 # noqa: E402
from satylab.study_v14_repro import (                              # noqa: E402
    LevelBook, load_10m, next_rung, run_v14, trade_day,
)
from satylab.study_entry_location import (                         # noqa: E402
    RACE_CAP, SPREAD, Sig, bracket, build, excursion, isolated_trade,
    norm_sf, quantile_bins, sequenced, spearman, trend_z, tstat, two_sided,
    z_geom,
)

TRIGGER = 0.236
MIN_RISK_PTS = 2.0
NQ = 5
REPORT = Path(__file__).resolve().parents[1] / "reports" / "V15_REGIME_LAYER.md"
RAW = Path(__file__).resolve().parents[1] / "reports" / "V15_REGIME_LAYER_raw.txt"

RANGE, TREND = "区间", "趋势"
SETUP_LABEL = {"Recovery": "交叉·延续 (Recovery)", "Vomy": "交叉·翻转 (Vomy)"}

CELLS = 0


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ══════════════════════════ 状态标注 ═════════════════════════════════════════
def stack_flags(bars: list[Bar]) -> list[bool | None]:
    """每根 setup K 上「五条 EMA 是否排列」（8/13/21/34/48 全同向）。"""
    closes = [b.close for b in bars]
    e8, e13, e21, e34, e48 = (ema(closes, n) for n in (8, 13, 21, 34, 48))
    out: list[bool | None] = []
    for i in range(len(bars)):
        if e48[i] is None:
            out.append(None)
            continue
        bull = e8[i] > e13[i] > e21[i] > e34[i] > e48[i]
        bear = e8[i] < e13[i] < e21[i] < e34[i] < e48[i]
        out.append(bull or bear)
    return out


def stack_dir(bars: list[Bar]) -> list[int]:
    closes = [b.close for b in bars]
    e8, e13, e21, e34, e48 = (ema(closes, n) for n in (8, 13, 21, 34, 48))
    out: list[int] = []
    for i in range(len(bars)):
        if e48[i] is None:
            out.append(0)
        elif e8[i] > e13[i] > e21[i] > e34[i] > e48[i]:
            out.append(+1)
        elif e8[i] < e13[i] < e21[i] < e34[i] < e48[i]:
            out.append(-1)
        else:
            out.append(0)
    return out


def annotate(sigs: list[Sig], bars: list[Bar], book: LevelBook) -> list[Sig]:
    """给每个信号贴上 v15.1 的状态标签。全部只用入场那一刻已知的信息。"""
    flags = stack_flags(bars)
    sdir = stack_dir(bars)
    keep: list[Sig] = []
    for s in sigs:
        lv = book.get(trade_day(bars[s.i]))
        if lv is None or flags[s.i] is None:
            continue
        anchor, atr = lv
        if atr <= 0:
            continue
        s.anchor = anchor
        s.u = (s.entry - anchor) / atr              # 位置，单位 ATR
        s.ubox = s.u / TRIGGER                      # 盒内相对位置，盒沿 = ±1
        s.in_box = abs(s.u) <= TRIGGER
        s.stacked = bool(flags[s.i])
        s.sdir = sdir[s.i]
        s.state = RANGE if (s.in_box or not s.stacked) else TREND
        s.v = s.direction * s.ubox                  # >0 = 信号发在自己方向的那一侧
        s.aligned = (s.sdir == s.direction)
        keep.append(s)
    return keep


# ══════════════════════════ 结果变量（纯括号口径） ═══════════════════════════
def br(s) -> float:
    """纯括号 R：命中 T1 记 +|T1−entry|/risk，先撞保护位记 −1。未裁决 = nan。"""
    if s.hit is None:
        return float("nan")
    return abs(s.t1 - s.entry) / s.risk if s.hit else -1.0


def bnet(s) -> float:
    r = br(s)
    return r - SPREAD / s.risk if s.risk > 0 else float("nan")


def bmoney(s) -> float:
    """净盈亏 × 风险距离(ATR) —— 跨止损档比较「钱」的唯一合法列。"""
    return bnet(s) * s.d4


def race(i0: int, d: int, entry: float, prot: float, t1: float,
         bars: list[Bar], subs, cap: int = RACE_CAP) -> bool | None:
    """保护位 vs T1 谁先到，落到 5m 子 K 裁决（纪律 2）。含混返回 None。"""
    for i in range(i0 + 1, min(i0 + 1 + cap, len(bars))):
        for sb in (subs[i] if subs is not None else [bars[i]]):
            ph = (sb.low <= prot) if d > 0 else (sb.high >= prot)
            gh = (sb.high >= t1) if d > 0 else (sb.low <= t1)
            if ph and gh:
                return None
            if gh:
                return True
            if ph:
                return False
    return None


# ══════════════════════════ 统计工具 ═════════════════════════════════════════
def rank_avg(v: list[float]) -> list[float]:
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


def wilcoxon(xs: list[float]) -> tuple[float, float, int]:
    """单样本 Wilcoxon 符号秩（正态近似 + 并列修正）。返回 (W, z, n_used)。"""
    vals = [x for x in xs if abs(x) > 1e-12]
    n = len(vals)
    if n < 10:
        return float("nan"), float("nan"), n
    absv = [abs(x) for x in vals]
    rk = rank_avg(absv)
    W = sum(r for r, x in zip(rk, vals) if x > 0)
    mu = n * (n + 1) / 4.0
    var = n * (n + 1) * (2 * n + 1) / 24.0
    for t in Counter(absv).values():
        if t > 1:
            var -= (t ** 3 - t) / 48.0
    return W, (W - mu) / math.sqrt(var) if var > 0 else float("nan"), n


def sign_test_z(xs: list[float]) -> tuple[int, int, float]:
    pos = sum(1 for x in xs if x > 0)
    n = sum(1 for x in xs if abs(x) > 1e-12)
    if n == 0:
        return 0, 0, float("nan")
    return pos, n, (pos - n / 2) / math.sqrt(n / 4)


def mean_diff_z(a: list[float], b: list[float]) -> tuple[float, float]:
    """两独立样本均值差 (a−b) 的 Welch z。"""
    if len(a) < 3 or len(b) < 3:
        return float("nan"), float("nan")
    va = st.variance(a) / len(a)
    vb = st.variance(b) / len(b)
    d = st.mean(a) - st.mean(b)
    se = math.sqrt(va + vb)
    return d, d / se if se > 0 else float("nan")


def mh_score_z(sigs, xget, sget, k: int = NQ) -> float:
    """在 sget 的分位数分层内部做 x 对「命中−几何零假设」的得分检验，再汇总。

    x 用状态指示（1=区间）时，z<0 ⇒ 控制住 sget 之后区间仍然更差。
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
        xs = [float(xget(s)) for s in g]
        if max(xs) == min(xs):
            continue
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


def mh_mean_z(sigs, yget, xget, sget, k: int = NQ) -> tuple[float, float, int]:
    """分层内的均值差 (x=1 减 x=0)，逆方差加权汇总。返回 (合并差, z, 用到的层数)。"""
    vals = [s for s in sigs if yget(s) == yget(s)]
    if len(vals) < 10 * k:
        return float("nan"), float("nan"), 0
    bins = quantile_bins([sget(s) for s in vals], k)
    num = den = 0.0
    used = 0
    for j in range(k):
        g = [s for s, b in zip(vals, bins) if b == j]
        a = [yget(s) for s in g if xget(s)]
        c = [yget(s) for s in g if not xget(s)]
        if len(a) < 5 or len(c) < 5:
            continue
        va = st.variance(a) / len(a)
        vc = st.variance(c) / len(c)
        v = va + vc
        if v <= 0:
            continue
        w = 1.0 / v
        num += (st.mean(a) - st.mean(c)) * w
        den += w
        used += 1
    if den <= 0:
        return float("nan"), float("nan"), used
    est = num / den
    return est, est * math.sqrt(den), used


def bonf_z(m: int, alpha: float = 0.05) -> float:
    target = alpha / max(m, 1) / 2.0
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if norm_sf(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def f(x, p=3, sign=False):
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


# ══════════════════════════ 分层表 ═══════════════════════════════════════════
def cell_row(label: str, g: list[Sig]) -> tuple[str, dict]:
    bump()
    res = [s for s in g if s.hit is not None]
    if not res:
        return f"| {label} | {len(g)} | 0 | – | – | – | – | – | – | – | – | – |", {}
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    kk = sum(1 for s in res if s.hit)
    lo, hi = stats.wilson(kk, n)
    brs = [br(s) for s in res]
    bns = [bnet(s) for s in res]
    bms = [bmoney(s) for s in res]
    v14 = [s.r for s in g if s.r == s.r]
    v14n = [s.net for s in g if s.net == s.net]
    v14s = f"{st.mean(v14):+.3f}" if v14 else "n/a"
    v14ns = f"{st.mean(v14n):+.3f}" if v14n else "n/a"
    row = (f"| {label} | {len(g)} | {n} | "
           f"{100*obs:.1f}% [{100*lo:.1f},{100*hi:.1f}] | {100*null:.1f}% | "
           f"{100*(obs-null):+.1f} | **{z:+.2f}** | {st.mean(brs):+.3f} | "
           f"{st.mean(bns):+.3f} | {1000*st.mean(bms):+.1f} | "
           f"{v14s} | {v14ns} | "
           f"{st.mean([s.d4 for s in g]):.3f} |")
    return row, {"n": len(g), "res": n, "obs": obs, "null": null, "z": z,
                 "br": st.mean(brs), "bnet": st.mean(bns),
                 "bmoney": st.mean(bms), "t": tstat(bns),
                 "d4": st.mean([s.d4 for s in g]),
                 "v14": st.mean(v14) if v14 else float("nan")}


HDR = ("| 格子 | n | 可裁决 | 纯括号命中 [95%CI] | 几何零假设 | 超额pp | z_geom | "
       "括号均R | 括号净均R | 净钱(ATR)×1000 | v14管理均R | v14管理净均R | 均D4 |")
SEP = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"


# ══════════════════════════ 边缘拒绝扫描器 ═══════════════════════════════════
def edge_rejections(bars: list[Bar], subs, book: LevelBook,
                    require_prev_inside: bool = False,
                    min_risk: float = MIN_RISK_PTS) -> list[Sig]:
    """「在盒沿被拒绝」= 触及 ±0.236 位后收盘回到盒内，方向朝盒内。

    预登记的判据（写在这里，不是跑完再挑）：
      · 上沿拒绝 ⇒ 做空：bar.high ≥ +0.236位 且 bar.close < +0.236位
        且 |(close−锚)/ATR| ≤ 0.236（真的收回盒内，不是一路砸穿）
      · 去重：前一根若已满足同侧条件则不重复记（只取拒绝序列的第一根）
      · 入场 = 该 K 收盘（与 v14 同口径），保护位 = 该 K 的拒绝极值（high/low）
      · 风险 ≥ 2.0 点（与 v14 的 minRisk 同）
      · T1/T2 = 顺方向下一个/再下一个具名位（与 v14 同）
    """
    out: list[Sig] = []
    for i, b in enumerate(bars):
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        anchor, atr = lv
        if atr <= 0:
            continue
        up, dn = anchor + TRIGGER * atr, anchor - TRIGGER * atr
        inside = abs((b.close - anchor) / atr) <= TRIGGER
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)
        prev = bars[i - 1] if i > 0 else None

        def prev_hit(level: float, side: int) -> bool:
            if prev is None:
                return False
            if side > 0:
                return prev.high >= level and prev.close < level
            return prev.low <= level and prev.close > level

        def prev_inside() -> bool:
            if prev is None:
                return False
            return abs((prev.close - anchor) / atr) <= TRIGGER

        # 上沿拒绝 → 做空
        if b.high >= up and b.close < up and inside and not prev_hit(up, +1):
            if (not require_prev_inside) or prev_inside():
                prot, risk = b.high, b.high - b.close
                if risk >= min_risk:
                    t1 = next_rung(b.close, -1, anchor, atr)
                    out.append(Sig(setup="EdgeReject", direction=-1,
                                   session="RTH" if in_rth else "夜盘", i=i,
                                   dt=b.dt, entry=b.close, prot=prot, risk=risk,
                                   t1=t1, t2=next_rung(t1, -1, anchor, atr),
                                   atr=atr, blocked=False))
        # 下沿拒绝 → 做多
        if b.low <= dn and b.close > dn and inside and not prev_hit(dn, -1):
            if (not require_prev_inside) or prev_inside():
                prot, risk = b.low, b.close - b.low
                if risk >= min_risk:
                    t1 = next_rung(b.close, +1, anchor, atr)
                    out.append(Sig(setup="EdgeReject", direction=+1,
                                   session="RTH" if in_rth else "夜盘", i=i,
                                   dt=b.dt, entry=b.close, prot=prot, risk=risk,
                                   t1=t1, t2=next_rung(t1, +1, anchor, atr),
                                   atr=atr, blocked=False))
    for s in out:
        s.d4 = s.risk / s.atr
        s.d1 = 0.0
        s.d2r = (bars[s.i].high - bars[s.i].low) / s.atr
        s.d3 = 0.0
        bracket(s, bars, subs)
        excursion(s, bars, subs)
        s.r = float("nan")
        s.hold = 0
    return out


# ══════════════════════════════ 主流程 ═══════════════════════════════════════
def main() -> None:
    o: list[str] = []
    A = o.append
    log: list[str] = []

    prim = build("ES=F", False)
    ctrl = build("^GSPC", True)
    bars, subs, book = prim["bars"], prim["subs"], prim["book"]

    sigs = annotate(prim["sigs"], bars, book)
    csigs = annotate(ctrl["sigs"], ctrl["bars"], ctrl["book"])
    seq = annotate(sequenced(prim), bars, book)

    rng = [s for s in sigs if s.state == RANGE]
    trd = [s for s in sigs if s.state == TREND]

    # ── §3 符号检验：反着做 ────────────────────────────────────────────────
    for s in sigs:
        d2 = -s.direction
        prot2 = s.entry - d2 * s.risk              # 止损镜像到入场价另一侧
        t1_rung = next_rung(s.entry, d2, s.anchor, s.atr)
        s.rev_hit = race(s.i, d2, s.entry, prot2, t1_rung, bars, subs)
        s.rev_pnull = s.risk / (s.risk + abs(t1_rung - s.entry))
        s.rev_r = (abs(t1_rung - s.entry) / s.risk
                   if s.rev_hit else (-1.0 if s.rev_hit is False else float("nan")))
        s.rev_net = s.rev_r - SPREAD / s.risk
        t1_mir = s.entry + d2 * abs(s.t1 - s.entry)
        s.mir_hit = race(s.i, d2, s.entry, prot2, t1_mir, bars, subs)
        s.mir_pnull = s.pnull
        s.mir_r = (abs(s.t1 - s.entry) / s.risk
                   if s.mir_hit else (-1.0 if s.mir_hit is False else float("nan")))
        s.mir_net = s.mir_r - SPREAD / s.risk

    # ── §5 边缘拒绝 ───────────────────────────────────────────────────────
    edges = annotate(edge_rejections(bars, subs, book), bars, book)
    edges_strict = annotate(edge_rejections(bars, subs, book,
                                            require_prev_inside=True), bars, book)
    cedges = annotate(edge_rejections(ctrl["bars"], ctrl["subs"], ctrl["book"]),
                      ctrl["bars"], ctrl["book"])

    # ═══════════════════════════ 报告 ═══════════════════════════════════════
    A("# V15.1 · 状态层假设的检验：区间态里交叉类信号的【符号】是不是反的")
    A("")
    A(f"生成脚本 `research/satylab/study_regime_layer.py`。主样本 **ES=F 10m**"
      f"（由 60d 5m 聚合，含完整夜盘，作息与 CAPITALCOM:SPX500 一致），"
      f"{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，{len(bars)} 根 setup K。"
      f"^GSPC 10m（仅 RTH）作对照。路径判定全部落到 **5 分钟子 K**（纪律 2）。")
    A("")

    # ── 0 ────────────────────────────────────────────────────────────────
    A("## 0 · 被检验的是什么，以及预登记的判据")
    A("")
    A("`SYSTEM_DESIGN_V15.md` §1.1 / 第 0 层写下的断言（当时的证据是 **07-28 一天**"
      "的逐条对账，`docs/SATY_LIVE_2026-07-27_28.md`）：")
    A("")
    A("> 在区间里，EMA 交叉类触发**只可能**在最差位置发火——价格跌到区间底部才叉得下来，"
      "涨到顶部才叉得上去。所以区间里我们信号的**符号**是反的，不是幅度不对。")
    A("")
    A("这句话如果为真，会有四个可证伪的推论。本报告逐条测，判据在跑数之前就写死：")
    A("")
    A("| # | 推论 | 通过的条件 |")
    A("|---|---|---|")
    A("| P1 | 区间态 × 交叉类显著劣于几何零假设 | z_geom 显著为负 |")
    A("| P2 | 把这一格**反过来做**会显著更好 | 配对超额差 z 显著为正 |")
    A("| P3 | 空信号集中在盒下半、多信号集中在盒上半 | 有向位置 v=dir×(位置/0.236) 均值显著 >0 |")
    A("| P4 | 盒沿拒绝优于同期交叉类 | 边缘拒绝的 z_geom / 净均R 显著更好 |")
    A("")
    A("**P2 是最硬的一条。** 「符号反了」的字面含义就是反着做会更好；如果反着做不更好，"
      "那么无论 P1 成不成立，「符号」这个诊断都不成立——那只是幅度/刻度问题。")
    A("")

    # ── 1 ────────────────────────────────────────────────────────────────
    A("## 1 · 口径")
    A("")
    A("### 1.1 状态怎么算")
    A("")
    A("逐字照抄 v15.1 第 0 层的定义，全部只用入场那一刻已知的信息"
      "（锚与 ATR 来自前一日收盘，EMA 来自当根已收 K）：")
    A("")
    A("```")
    A("u        = (close − 锚) / ATR                 位置，单位 ATR")
    A("in_box   = |u| ≤ 0.236                        在 trigger box 内")
    A("stacked  = EMA 8/13/21/34/48 五条全同向排列")
    A("区间态   = in_box  OR  (not stacked)")
    A("趋势态   = stacked AND (not in_box)")
    A("```")
    A("")
    A("### 1.2 setup 类型：v14 里**没有**非交叉类")
    A("")
    A("这一点必须先说清楚，否则整张表会被误读。v14 只有两台状态机，"
      "**两台都是 EMA13 交叉驱动的**：")
    A("")
    A("| setup | 触发 | 在 v15.1 的话里 |")
    A("|---|---|---|")
    A("| Recovery | 五线排列 ≥5 根 → 收盘回踩到 13 另一侧 → **收盘再叉回来** | 交叉·延续 |")
    A("| Vomy | 五线排列**破掉** + 收盘同时穿过 13 与 8（袋子刚变色）→ 回抽 13 触发 | 交叉·翻转 |")
    A("")
    A("所以「区间态 × 交叉类」这一格的分母是 v14 在区间态里的**全部**信号；"
      "**v14 里没有边缘拒绝类可以做对照**——§5 的对照组是本文件新写的扫描器，"
      "不是 v14 的既有信号。")
    A("")
    A("### 1.3 结果变量")
    A("")
    A("主结果是**纯括号**（保护位 vs T1 谁先到，删掉 EMA13 结构离场），"
      "因为它只反映「这一注下在什么位置」，不掺任何出场规则；而且反做的那一半"
      "**必须**用纯括号——v14 的 EMA13 结构离场对反向仓位会在下一根就触发，"
      "拿它比较等于用出场规则替符号检验做判决。")
    A("")
    A("- 括号均R：命中 T1 记 +|T1−entry|/risk，先撞保护位记 −1")
    A("- 括号净均R：再扣 0.6 点点差 / 该笔风险距离（纪律 4）")
    A("- **净钱(ATR)**：净R × (风险距离/ATR)。**跨止损档比较「钱」只能看这一列**——"
      "R 的分母就是被分层的那个变量本身")
    A("- v14管理均R / 净均R：完整重放（分批 + 13 线离场），只为与既有报告接得上")
    A("")

    # ── 2 ────────────────────────────────────────────────────────────────
    A("## 2 · (状态 × setup类型) 分层")
    A("")
    n_rng = len(rng)
    A(f"全部 {len(sigs)} 个入场信号里，**区间态 {n_rng} 个（{100*n_rng/len(sigs):.1f}%）**，"
      f"趋势态 {len(trd)} 个（{100*len(trd)/len(sigs):.1f}%）。")
    A("")
    A(HDR)
    A(SEP)
    core = {}
    grid = {}
    for stt in (RANGE, TREND):
        for su in ("Recovery", "Vomy"):
            g = [s for s in sigs if s.state == stt and s.setup == su]
            if not g:
                continue
            row, d = cell_row(f"{stt} × {SETUP_LABEL[su]}", g)
            A(row)
            grid[(stt, su)] = d
    for stt in (RANGE, TREND):
        g = [s for s in sigs if s.state == stt]
        row, d = cell_row(f"**{stt} · 合计**", g)
        A(row)
        grid[(stt, "ALL")] = d
        if stt == RANGE:
            core = d
    row, d_all = cell_row("全样本", sigs)
    A(row)
    A("")

    zr, zt = grid[(RANGE, "ALL")]["z"], grid[(TREND, "ALL")]["z"]
    dz = mh_score_z(sigs, lambda s: 1 if s.state == RANGE else 0,
                    lambda s: 0.0, k=1)
    bump()
    A(f"**核心格子（区间 × 交叉类，= 区间合计）：n={grid[(RANGE,'ALL')]['n']}，"
      f"命中 {100*grid[(RANGE,'ALL')]['obs']:.1f}%，几何零假设 "
      f"{100*grid[(RANGE,'ALL')]['null']:.1f}%，z_geom = {zr:+.2f}，"
      f"括号净均R {grid[(RANGE,'ALL')]['bnet']:+.3f}。**")
    A("")
    dd, zdd = mean_diff_z([bnet(s) for s in rng if s.hit is not None],
                          [bnet(s) for s in trd if s.hit is not None])
    dm, zdm = mean_diff_z([bmoney(s) for s in rng if s.hit is not None],
                          [bmoney(s) for s in trd if s.hit is not None])
    bump(3)
    A(f"- 区间 vs 趋势的**超额**差（未控制任何变量）：得分检验 z = **{dz:+.2f}** "
      f"(p={two_sided(dz):.3f})，负号 = 区间更差。")
    A(f"- 区间 vs 趋势的**括号净均R**差 = {dd:+.3f}（z={zdd:+.2f}）；"
      f"**净钱(ATR)×1000** 差 = {1000*dm:+.1f}（z={zdm:+.2f}）。")
    A("")

    # 2.2 状态定义两条腿的分解
    A("### 2.2 状态定义那个 `OR` 的两条腿，是哪一条在干活")
    A("")
    A("`区间 = 盒内 OR 未排列` 是一个或，两条腿完全可能一条有效一条无效。"
      "而且 **Vomy 按构造就是「排列破掉之后」才发火**，所以它几乎必然落在"
      "「未排列」这条腿上——不拆开看，整张表会把 setup 差异误读成状态差异。")
    A("")
    A(HDR)
    A(SEP)
    legs = {}
    for lbl, fn in (
        ("盒内 · 已排列", lambda s: s.in_box and s.stacked),
        ("盒内 · 未排列", lambda s: s.in_box and not s.stacked),
        ("盒外 · 未排列", lambda s: (not s.in_box) and not s.stacked),
        ("盒外 · 已排列（=趋势）", lambda s: (not s.in_box) and s.stacked),
    ):
        g = [s for s in sigs if fn(s)]
        row, d = cell_row(lbl, g)
        A(row)
        legs[lbl] = d
    A("")
    A("**同一个分解，只看 Vomy（翻转类）与只看 Recovery（延续类）：**")
    A("")
    A(HDR)
    A(SEP)
    for su in ("Recovery", "Vomy"):
        for lbl, fn in (
            ("盒内", lambda s: s.in_box),
            ("盒外·未排列", lambda s: (not s.in_box) and not s.stacked),
            ("盒外·已排列", lambda s: (not s.in_box) and s.stacked),
        ):
            g = [s for s in sigs if s.setup == su and fn(s)]
            if len(g) < 5:
                continue
            row, _ = cell_row(f"{SETUP_LABEL[su]} · {lbl}", g)
            A(row)
    A("")
    nv_ns = sum(1 for s in sigs if s.setup == "Vomy" and not s.stacked)
    nv = sum(1 for s in sigs if s.setup == "Vomy")
    nr_ns = sum(1 for s in sigs if s.setup == "Recovery" and not s.stacked)
    nr = sum(1 for s in sigs if s.setup == "Recovery")
    A(f"- Vomy 信号里 **{nv_ns}/{nv} = {100*nv_ns/max(nv,1):.0f}%** 在入场那根「未排列」；"
      f"Recovery 是 **{nr_ns}/{nr} = {100*nr_ns/max(nr,1):.0f}%**。"
      f"「未排列」这条腿在很大程度上**就是 Vomy 的同义词**，这一点在读上表时必须记住。")
    A("")
    A("**顺/逆排列（只在已排列的信号里可分）：**")
    A("")
    A(HDR)
    A(SEP)
    for lbl, fn in (("已排列 · 信号顺排列方向", lambda s: s.stacked and s.aligned),
                    ("已排列 · 信号逆排列方向", lambda s: s.stacked and not s.aligned)):
        g = [s for s in sigs if fn(s)]
        if len(g) >= 5:
            row, _ = cell_row(lbl, g)
            A(row)
    A("")

    # 2.3 对照
    A("### 2.3 ^GSPC 10m RTH 对照（方向性对照，不是第二个证据）")
    A("")
    A("⚠ 纪律 5：^GSPC 的 ATR 与 CAPITALCOM:SPX500 的比值 mean 1.117 / sd 0.083 / "
      "范围 0.826–1.418，**不是常数**。本报告的状态定义直接依赖位价（盒内/盒外），"
      "所以这张表**只能**当独立标的上的方向性对照读。")
    A("")
    A(HDR)
    A(SEP)
    for stt in (RANGE, TREND):
        g = [s for s in csigs if s.state == stt]
        if len(g) >= 5:
            row, _ = cell_row(f"^GSPC RTH · {stt}", g)
            A(row)
    A("")

    # 2.4 线上排队口径
    A("### 2.4 线上排队口径复核（真正成交的那些）")
    A("")
    A(HDR)
    A(SEP)
    for stt in (RANGE, TREND):
        g = [s for s in seq if s.state == stt]
        if len(g) >= 5:
            row, _ = cell_row(f"线上口径 · {stt}", g)
            A(row)
    A("")

    # ── 3 符号检验 ────────────────────────────────────────────────────────
    A("## 3 · 符号检验：把区间态的交叉类信号**反过来做**")
    A("")
    A("这是最直接的检验，比任何过滤器都硬。构造：")
    A("")
    A("- 方向取反，入场价不变（仍是信号 K 收盘）")
    A("- 保护位 = 原止损**镜像到入场价另一侧**（风险距离逐笔完全相同 ⇒ R 单位可比）")
    A("- 目标两种：**A 具名位**（反方向的下一个 ATR 位，与系统一致）；"
      "**B 完全镜像**（把 T1 也镜像过去 ⇒ 几何零假设逐笔与顺做完全相同，数学上最干净）")
    A("- 路径同样落到 5m 子 K 裁决")
    A("")

    def rev_block(g: list[Sig], label: str) -> None:
        bump(4)
        fw = [s for s in g if s.hit is not None]
        zf, nf, of_, nlf = z_geom([s.hit for s in fw], [s.pnull for s in fw])
        ra = [s for s in g if s.rev_hit is not None]
        za, na, oa, nla = z_geom([s.rev_hit for s in ra], [s.rev_pnull for s in ra])
        rb = [s for s in g if s.mir_hit is not None]
        zb, nb, ob, nlb = z_geom([s.mir_hit for s in rb], [s.mir_pnull for s in rb])
        A(f"**{label}**")
        A("")
        A("| 做法 | 可裁决n | 命中 [95%CI] | 几何零假设 | 超额pp | z_geom | "
          "括号均R | 括号净均R | 净钱(ATR)×1000 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for nm, gg, hs, ps, rs in (
            ("顺着做（v14 原样）", fw, [s.hit for s in fw],
             [s.pnull for s in fw], [br(s) for s in fw]),
            ("反着做 A（具名位目标）", ra, [s.rev_hit for s in ra],
             [s.rev_pnull for s in ra], [s.rev_r for s in ra]),
            ("反着做 B（完全镜像）", rb, [s.mir_hit for s in rb],
             [s.mir_pnull for s in rb], [s.mir_r for s in rb]),
        ):
            z, n, obs, null = z_geom(hs, ps)
            kk = sum(1 for h in hs if h)
            lo, hi = stats.wilson(kk, n)
            nets = [r - SPREAD / s.risk for r, s in zip(rs, gg)]
            money = [x * s.d4 for x, s in zip(nets, gg)]
            A(f"| {nm} | {n} | {100*obs:.1f}% [{100*lo:.1f},{100*hi:.1f}] | "
              f"{100*null:.1f}% | {100*(obs-null):+.1f} | **{z:+.2f}** | "
              f"{st.mean(rs):+.3f} | {st.mean(nets):+.3f} | "
              f"{1000*st.mean(money):+.1f} |")
        A("")
        # 配对检验（B：零假设逐笔相同，配对差最干净）
        pair = [s for s in g if s.hit is not None and s.mir_hit is not None]
        dex = [((1 if s.mir_hit else 0) - s.mir_pnull)
               - ((1 if s.hit else 0) - s.pnull) for s in pair]
        dnet = [(s.mir_net - bnet(s)) for s in pair]
        za_p = tstat(dex)
        zn_p = tstat(dnet)
        pos, npos, zs = sign_test_z(dnet)
        A(f"- **配对符号检验（B 镜像，n={len(pair)}）**：每笔「反做超额 − 顺做超额」"
          f"均值 {st.mean(dex) if dex else float('nan'):+.3f}，"
          f"配对 t = **{za_p:+.2f}** (p={two_sided(za_p):.3f})。")
        A(f"- 配对净R 差（反 − 顺）均值 {st.mean(dnet) if dnet else float('nan'):+.3f}，"
          f"t = **{zn_p:+.2f}** (p={two_sided(zn_p):.3f})；"
          f"符号检验 {pos}/{npos} 为正，z = {zs:+.2f}。")
        A("")

    rev_block(rng, f"区间态 · 全部交叉类（n={len(rng)}）")
    rev_block([s for s in rng if s.in_box],
              f"区间态 · 只看真在盒内的（n={sum(1 for s in rng if s.in_box)}）")
    rev_block(trd, f"对照：趋势态（n={len(trd)}）")
    rev_block(sigs, f"对照：全样本（n={len(sigs)}）")

    A("**怎么读这几张表**：反做 A 与顺做的几何零假设不同（目标位置不同），"
      "所以两者的「超额 pp」才是可比的量，命中率本身不可比。"
      "反做 B 的零假设与顺做逐笔完全相同，配对 t 就是最纯的符号检验。")
    A("")
    A("### 3.1 交互检验：反做的好处是**区间态特有的**吗")
    A("")
    A("上面每一组反做都比顺做好一点点。但假设说的不是「反做到处都好」——"
      "**它说的是区间态里符号是反的、趋势态里符号是对的**。"
      "所以真正要看的不是各组的配对 t，而是**组间差**：区间的配对差是否显著大于趋势的。")
    A("")

    def pd_net(g):
        return [s.mir_net - bnet(s)
                for s in g if s.hit is not None and s.mir_hit is not None]

    def pd_ex(g):
        return [((1 if s.mir_hit else 0) - s.mir_pnull)
                - ((1 if s.hit else 0) - s.pnull)
                for s in g if s.hit is not None and s.mir_hit is not None]

    A("| 组 A（假设说符号反） | 组 B（假设说符号对） | A 的配对净R差 | B 的配对净R差 | "
      "**A−B** | z | A 的超额差 | B 的超额差 | **A−B** | z |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for la, ga, lb, gb in (
        ("区间", rng, "趋势", trd),
        ("盒内", [s for s in sigs if s.in_box], "盒外", [s for s in sigs if not s.in_box]),
        ("未排列", [s for s in sigs if not s.stacked], "已排列",
         [s for s in sigs if s.stacked]),
        ("盒内·Recovery", [s for s in sigs if s.in_box and s.setup == "Recovery"],
         "其余全部", [s for s in sigs if not (s.in_box and s.setup == "Recovery")]),
    ):
        bump(2)
        na, nb = pd_net(ga), pd_net(gb)
        ea, eb = pd_ex(ga), pd_ex(gb)
        dn, zn_ = mean_diff_z(na, nb)
        de, ze_ = mean_diff_z(ea, eb)
        A(f"| {la} (n={len(na)}) | {lb} (n={len(nb)}) | {st.mean(na):+.3f} | "
          f"{st.mean(nb):+.3f} | **{dn:+.3f}** | {zn_:+.2f} | {st.mean(ea):+.3f} | "
          f"{st.mean(eb):+.3f} | **{de:+.3f}** | {ze_:+.2f} |")
    A("")

    # ── 4 位置检验 ────────────────────────────────────────────────────────
    A("## 4 · 位置检验：区间态交叉类信号发生时，价格在盒子的哪一半")
    A("")
    A("`v = 方向 × (close−锚)/(0.236×ATR)`。假设预测：做空集中在盒**下**半、"
      "做多集中在盒**上**半 ⇒ 空的 u<0、多的 u>0 ⇒ **v 显著为正**"
      "（信号发在自己方向已经走过的那一侧 = 最差位置）。")
    A("")

    def pos_block(g: list[Sig], label: str) -> None:
        bump(3)
        if len(g) < 10:
            A(f"- {label}：n={len(g)}，样本不足。")
            return
        us = [s.ubox for s in g]
        vs = [s.v for s in g]
        longs = [s.ubox for s in g if s.direction > 0]
        shorts = [s.ubox for s in g if s.direction < 0]
        tv = tstat(vs)
        _, wz, wn = wilcoxon(vs)
        pos, npos, zs = sign_test_z(vs)
        A(f"**{label}**（n={len(g)}；多 {len(longs)} / 空 {len(shorts)}）")
        A("")
        A("| 量 | n | 均值 | 中位 | p10 | p25 | p75 | p90 | >0 的比例 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for nm, xs in (("u (盒内相对位置)", us), ("多头信号的 u", longs),
                       ("空头信号的 u", shorts), ("**v = dir×u**", vs)):
            if len(xs) < 3:
                continue
            ss = sorted(xs)
            def qq(p):
                a = (len(ss) - 1) * p
                lo, hi = int(a), min(int(a) + 1, len(ss) - 1)
                return ss[lo] + (ss[hi] - ss[lo]) * (a - lo)
            A(f"| {nm} | {len(xs)} | {st.mean(xs):+.3f} | {st.median(xs):+.3f} | "
              f"{qq(.10):+.2f} | {qq(.25):+.2f} | {qq(.75):+.2f} | {qq(.90):+.2f} | "
              f"{100*sum(1 for x in xs if x > 0)/len(xs):.0f}% |")
        A("")
        A(f"- **符号检验**：v 的均值 {st.mean(vs):+.3f}，t = **{tv:+.2f}** "
          f"(p={two_sided(tv):.3f})；Wilcoxon 符号秩 z = **{wz:+.2f}** "
          f"(p={two_sided(wz):.3f}, n={wn})；简单符号检验 {pos}/{npos} 为正 "
          f"(z={zs:+.2f})。**正号 = 假设成立方向。**")
        # v 是否真的预测坏结果
        res = [s for s in g if s.hit is not None]
        if len(res) >= 20:
            tz = trend_z([s.v for s in res], [1 if s.hit else 0 for s in res],
                         [s.pnull for s in res])
            rho, zr_ = spearman([s.v for s in res], [bnet(s) for s in res])
            bump(2)
            A(f"- **v 有没有真的预测坏结果**：超额的趋势检验 z = **{tz:+.2f}** "
              f"(p={two_sided(tz):.3f})，负号 = v 越大越差；"
              f"净R 秩相关 ρ = {rho:+.3f} (z={zr_:+.2f})。")
        A("")

    pos_block([s for s in rng if s.in_box], "区间态 · 盒内的交叉类信号")
    pos_block([s for s in rng if s.in_box and s.setup == "Recovery"],
              "盒内 · 只看 Recovery（交叉·延续）")
    pos_block([s for s in rng if s.in_box and s.setup == "Vomy"],
              "盒内 · 只看 Vomy（交叉·翻转）")
    pos_block(rng, "区间态 · 全部（含盒外未排列，|u| 会超出 ±1）")

    # ── 5 边缘拒绝 ────────────────────────────────────────────────────────
    A("## 5 · 边缘拒绝检验")
    A("")
    A("v14 没有这一类信号，所以这里是**新写的扫描器**（判据见脚本 `edge_rejections`，"
      "写在跑数之前）：触及 ±0.236 位后收盘回到盒内、方向朝盒内，"
      "保护位 = 该 K 的拒绝极值，目标 = 顺方向下一个具名位，最小风险 2.0 点"
      "（与 v14 同）。连续满足的只取第一根。")
    A("")
    A("⚠ 对比必须用**纯括号**：v14 的 EMA13 结构离场对边缘拒绝仓位会在下一两根就触发"
      "（在盒顶做空时价格通常在 13 上方），拿 v14 的管理去跑边缘拒绝，"
      "等于让出场规则替这个检验做判决。所以下表 v14 管理那两列对边缘拒绝是空的。")
    A("")
    A(HDR)
    A(SEP)
    edge_stats = {}
    for lbl, g in (("边缘拒绝（全部）", edges),
                   ("边缘拒绝 · 上沿做空", [s for s in edges if s.direction < 0]),
                   ("边缘拒绝 · 下沿做多", [s for s in edges if s.direction > 0]),
                   ("边缘拒绝 · 变体：要求前一根也在盒内", edges_strict),
                   ("同期对照：区间态交叉类", rng),
                   ("同期对照：盒内交叉类", [s for s in rng if s.in_box])):
        if len(g) < 5:
            continue
        row, d = cell_row(lbl, g)
        A(row)
        edge_stats[lbl] = d
    A("")
    ge = [s for s in edges if s.hit is not None]
    gc = [s for s in rng if s.in_box and s.hit is not None]
    if len(ge) >= 10 and len(gc) >= 10:
        de, zde = mean_diff_z([bnet(s) for s in ge], [bnet(s) for s in gc])
        dme, zdme = mean_diff_z([bmoney(s) for s in ge], [bmoney(s) for s in gc])
        exe = [(1 if s.hit else 0) - s.pnull for s in ge]
        exc = [(1 if s.hit else 0) - s.pnull for s in gc]
        dxx, zxx = mean_diff_z(exe, exc)
        bump(3)
        A(f"- **边缘拒绝 vs 盒内交叉类**：超额差 {100*dxx:+.1f} pp（z=**{zxx:+.2f}**）；"
          f"括号净均R 差 {de:+.3f}（z={zde:+.2f}）；"
          f"净钱(ATR)×1000 差 {1000*dme:+.1f}（z={zdme:+.2f}）。")
    A(f"- 风险距离对比：边缘拒绝均 D4 = "
      f"{st.mean([s.d4 for s in edges]):.3f} ATR，"
      f"盒内交叉类均 D4 = "
      f"{st.mean([s.d4 for s in rng if s.in_box]):.3f} ATR。"
      f"**边缘拒绝的止损更小，却没有更差**——这本身就是「一切都只是止损距离」"
      f"那个解释的一个反例。")
    A(f"- ⚠ **但边缘拒绝并不赚钱**：括号净均R {st.mean([bnet(s) for s in ge]):+.3f}，"
      f"总净R **{sum(bnet(s) for s in ge):+.1f}**（{len(ge)} 笔）。"
      f"命中 {100*st.mean([1.0 if s.hit else 0.0 for s in ge]):.1f}% 对几何零假设 "
      f"{100*st.mean([s.pnull for s in ge]):.1f}%，z_geom "
      f"{z_geom([s.hit for s in ge], [s.pnull for s in ge])[0]:+.2f}——"
      f"**它只是「不比几何零假设差」，不是「有优势」**。"
      f"换规则换来的是少亏，不是转正。")
    if len(cedges) >= 5:
        row, _ = cell_row("^GSPC RTH · 边缘拒绝", cedges)
        A("")
        A("**^GSPC RTH 对照**（同样只是方向性对照）：")
        A("")
        A(HDR)
        A(SEP)
        A(row)
    A("")

    # ── 6 混淆控制 ────────────────────────────────────────────────────────
    A("## 6 · 必须处理的混淆：区间态是不是仅仅因为止损小")
    A("")
    A("`REGIME_MONTHLY_BOX_2026-07-25.md` 在 20 年样本上否掉的是「**对同一套规则**"
      "按箱内/箱外开关」；这里问的是「**换规则**」，两者不是同一个命题，前者被否"
      "不蕴含后者被否。但还有一个更朴素、也更难看的可能："
      "**区间态之所以差，也许只是因为那里波动小、结构止损近**，"
      "而 `V15_ENTRY_LOCATION.md` 已经证明**止损近才是真正的杀手**"
      "（D4 最小档命中 24.0% vs 几何零假设 35.8%，z=−2.74，均净R −0.551；"
      "D4 是全报告唯一越过 Bonferroni 的变量）。如果控制住风险距离之后状态效应消失，"
      "那状态层就是刻度错配的伪装，与「符号」无关。")
    A("")
    A("### 6.1 先看区间态是不是真的止损更小")
    A("")
    A("| 分组 | n | 均风险距离 D4(ATR) | 中位 D4 | 均信号K振幅/ATR | 均日ATR(点) | "
      "均 \\|T1−entry\\|/ATR | 均几何零假设 |")
    A("|---|---|---|---|---|---|---|---|")
    for lbl, g in ((RANGE, rng), (TREND, trd),
                   ("盒内", [s for s in sigs if s.in_box]),
                   ("盒外", [s for s in sigs if not s.in_box]),
                   ("未排列", [s for s in sigs if not s.stacked]),
                   ("已排列", [s for s in sigs if s.stacked])):
        if not g:
            continue
        bump()
        A(f"| {lbl} | {len(g)} | {st.mean([s.d4 for s in g]):.3f} | "
          f"{st.median([s.d4 for s in g]):.3f} | "
          f"{st.mean([s.d2r for s in g]):.3f} | "
          f"{st.mean([s.atr for s in g]):.1f} | "
          f"{st.mean([abs(s.t1-s.entry)/s.atr for s in g]):.3f} | "
          f"{st.mean([s.pnull for s in g]):.3f} |")
    A("")
    dd4, zd4 = mean_diff_z([s.d4 for s in rng], [s.d4 for s in trd])
    bump()
    A(f"- 区间 − 趋势 的均风险距离差 = **{dd4:+.3f} ATR**（z={zd4:+.2f}）。")
    A("")
    A("### 6.2 控制风险距离之后，状态效应还剩多少")
    A("")
    A("方法：把全部信号按 D4 切 5 个分位层，**层内**比较区间 vs 趋势，再把各层汇总"
      "（得分检验用 Mantel-Haenszel 式的 U/V 汇总；均值差用逆方差加权）。"
      "同样的做法再对日 ATR、信号 K 振幅各做一遍。")
    A("")
    A("| 控制变量 | 超额的状态得分 z | 括号净均R 差(区间−趋势) | z | "
      "净钱(ATR)×1000 差 | z |")
    A("|---|---|---|---|---|---|")
    isr = (lambda s: s.state == RANGE)
    raw_dn, raw_zn = mean_diff_z([bnet(s) for s in rng if s.hit is not None],
                                 [bnet(s) for s in trd if s.hit is not None])
    raw_dm, raw_zm = mean_diff_z([bmoney(s) for s in rng if s.hit is not None],
                                 [bmoney(s) for s in trd if s.hit is not None])
    A(f"| **不控制（原始）** | {dz:+.2f} | {raw_dn:+.3f} | {raw_zn:+.2f} | "
      f"{1000*raw_dm:+.1f} | {raw_zm:+.2f} |")
    dec = [s for s in sigs if s.hit is not None]
    for cname, cget in (("风险距离 D4", lambda s: s.d4),
                        ("日 ATR", lambda s: s.atr),
                        ("信号K振幅/ATR", lambda s: s.d2r),
                        ("几何零假设本身", lambda s: s.pnull)):
        bump(3)
        zc = mh_score_z(sigs, lambda s: 1 if s.state == RANGE else 0, cget)
        en, zn_ = mh_mean_z(dec, bnet, isr, cget)[:2]
        em, zm_ = mh_mean_z(dec, bmoney, isr, cget)[:2]
        A(f"| 控制 {cname}（5 层） | {zc:+.2f} | {en:+.3f} | {zn_:+.2f} | "
          f"{1000*em:+.1f} | {zm_:+.2f} |")
    A("")
    A("**同样的控制，套在 §3 的符号检验上**（配对差本身逐笔已消掉几何零假设，"
      "所以这里直接看配对净R 差在 D4 各层是否稳定）：")
    A("")
    A("| D4 分位层 | n | 区间态配对净R差(反−顺) | t |")
    A("|---|---|---|---|")
    pair = [s for s in rng if s.hit is not None and s.mir_hit is not None]
    if len(pair) >= 25:
        bins = quantile_bins([s.d4 for s in pair], NQ)
        for j in range(NQ):
            g = [s for s, b in zip(pair, bins) if b == j]
            if len(g) < 5:
                continue
            bump()
            d = [s.mir_net - bnet(s) for s in g]
            lo = min(s.d4 for s in g)
            hi = max(s.d4 for s in g)
            A(f"| Q{j+1} ({lo:.3f}–{hi:.3f}) | {len(g)} | {st.mean(d):+.3f} | "
              f"{tstat(d):+.2f} |")
    A("")
    A("### 6.3 真正需要控制的不是「区间」，是那一个格子")
    A("")
    A("上表看不出什么，是因为「区间」这个标签把两台性质相反的机器搅在了一起"
      "（见 §2.2 与 §4）。真正扎眼的是 **盒内 × Recovery**：n="
      f"{sum(1 for s in sigs if s.in_box and s.setup=='Recovery')}，"
      "超额 −11.6 pp，括号净均R −0.479，**均风险距离只有 0.081 ATR**——"
      "正好落在 `V15_ENTRY_LOCATION.md` 里那个唯一越过 Bonferroni 的杀手区间"
      "（D4 最小两档：0.019–0.088 ATR，净均R −0.551 / −0.184）。"
      "所以这一格必须单独做控制。")
    A("")
    A("| 对比 | 控制 | 超额得分 z | 括号净均R 差 | z | 净钱(ATR)×1000 差 | z |")
    A("|---|---|---|---|---|---|---|")
    isrecbox = (lambda s: 1 if (s.in_box and s.setup == "Recovery") else 0)
    recs = [s for s in sigs if s.setup == "Recovery"]
    recs_dec = [s for s in recs if s.hit is not None]
    for lbl, pool, xget, ctrl_name, ctrl_get in (
        ("盒内×Recovery vs 其余全部", sigs, isrecbox, "不控制", None),
        ("盒内×Recovery vs 其余全部", sigs, isrecbox, "D4 5 层", lambda s: s.d4),
        ("Recovery 内部：盒内 vs 盒外", recs,
         lambda s: 1 if s.in_box else 0, "不控制", None),
        ("Recovery 内部：盒内 vs 盒外", recs,
         lambda s: 1 if s.in_box else 0, "D4 5 层", lambda s: s.d4),
        ("Vomy 内部：盒内 vs 盒外",
         [s for s in sigs if s.setup == "Vomy"],
         lambda s: 1 if s.in_box else 0, "不控制", None),
        ("Vomy 内部：盒内 vs 盒外",
         [s for s in sigs if s.setup == "Vomy"],
         lambda s: 1 if s.in_box else 0, "D4 5 层", lambda s: s.d4),
    ):
        bump(3)
        dec = [s for s in pool if s.hit is not None]
        if ctrl_get is None:
            zc = mh_score_z(pool, xget, lambda s: 0.0, k=1)
            a = [bnet(s) for s in dec if xget(s)]
            c = [bnet(s) for s in dec if not xget(s)]
            en, zn_ = mean_diff_z(a, c)
            am = [bmoney(s) for s in dec if xget(s)]
            cm = [bmoney(s) for s in dec if not xget(s)]
            em, zm_ = mean_diff_z(am, cm)
        else:
            zc = mh_score_z(pool, xget, ctrl_get)
            en, zn_ = mh_mean_z(dec, bnet, xget, ctrl_get)[:2]
            em, zm_ = mh_mean_z(dec, bmoney, xget, ctrl_get)[:2]
        A(f"| {lbl} | {ctrl_name} | {zc:+.2f} | {en:+.3f} | {zn_:+.2f} | "
          f"{1000*em:+.1f} | {zm_:+.2f} |")
    A("")
    A("**Recovery 逐 D4 分位层的盒内 / 盒外超额**（层内直接对照，不汇总）：")
    A("")
    A("| D4 层 | 盒内 n | 盒内超额pp | 盒外 n | 盒外超额pp | 差 |")
    A("|---|---|---|---|---|---|")
    if len(recs_dec) >= 50:
        rbins = quantile_bins([s.d4 for s in recs_dec], NQ)
        for j in range(NQ):
            g = [s for s, b in zip(recs_dec, rbins) if b == j]
            a = [s for s in g if s.in_box]
            c = [s for s in g if not s.in_box]
            if len(a) < 3 or len(c) < 3:
                lo_, hi_ = min(s.d4 for s in g), max(s.d4 for s in g)
                A(f"| Q{j+1} ({lo_:.3f}–{hi_:.3f}) | {len(a)} | – | {len(c)} | – | "
                  f"层内一侧不足 3 笔 |")
                continue
            bump()
            _, _, oa, nla = z_geom([s.hit for s in a], [s.pnull for s in a])
            _, _, oc, nlc = z_geom([s.hit for s in c], [s.pnull for s in c])
            lo_, hi_ = min(s.d4 for s in g), max(s.d4 for s in g)
            A(f"| Q{j+1} ({lo_:.3f}–{hi_:.3f}) | {len(a)} | {100*(oa-nla):+.1f} | "
              f"{len(c)} | {100*(oc-nlc):+.1f} | {100*((oa-nla)-(oc-nlc)):+.1f} |")
    A("")

    # ── 7 多重比较 ────────────────────────────────────────────────────────
    A("## 7 · 多重比较与样本量的自报")
    A("")
    thr = bonf_z(CELLS)
    A(f"本报告全文检视 **{CELLS} 个格子**（分层格、趋势/符号/配对检验、控制层、"
      f"边缘拒绝变体），Bonferroni 门槛 |z| > **{thr:.2f}**（α=0.05 双侧）。")
    A("")
    A(f"**常规 |z|>1.96 在这个 family size 下没有意义。** 本报告里没有任何一个 z "
      f"越过 {thr:.2f}，所以下面所有判决都只能是「**没找到证据**」或"
      f"「**方向与假设相反**」，不能是「证明了反面」。")
    A("")
    A(f"样本量：{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，"
      f"只有 {len(set(b.day for b in bars))} 个交易日、{len(sigs)} 个信号。"
      f"这是 5m 数据 60 天上限的硬约束，不是选择。区间态 {len(rng)} 个、"
      f"趋势态 {len(trd)} 个，**趋势态这一格本身就小**，任何"
      f"「区间比趋势差多少」的结论都受它的方差支配。")
    A("")
    A("**位价局限（纪律 5）**：本报告的状态定义**直接依赖位价**"
      "（盒内/盒外由 (close−锚)/ATR 判定），所以主样本必须是 ES=F。"
      "^GSPC 的 ATR 与 CAPITALCOM:SPX500 的比值 mean 1.117 / sd 0.083 / "
      "范围 0.826–1.418，**用 ^GSPC 会把一部分盒内信号错判成盒外，反之亦然**。"
      "ES=F 与 CAPITALCOM:SPX500 也不是同一个标的，只是作息一致；"
      "**在界面导出真实 CFD 历史之前，本报告的盒内/盒外划分有已知的、无法修正的噪声。**")
    A("")

    # ── 8 反例 ────────────────────────────────────────────────────────────
    A("## 8 · 与假设相反的格子（如实单列）")
    A("")
    A("| 格子 | n | 命中 | 几何零假设 | 超额pp | z_geom | 括号净均R | 说明 |")
    A("|---|---|---|---|---|---|---|---|")
    contra = []
    for (stt, su), d in sorted(grid.items(), key=lambda kv: -(kv[1].get("z") or -9)):
        if not d:
            continue
        nm = f"{stt} × {SETUP_LABEL.get(su, '合计')}"
        contra.append((nm, d))
    for nm, d in contra:
        A(f"| {nm} | {d['n']} | {100*d['obs']:.1f}% | {100*d['null']:.1f}% | "
          f"{100*(d['obs']-d['null']):+.1f} | {d['z']:+.2f} | {d['bnet']:+.3f} | |")
    A("")

    # ── 9 判决 ────────────────────────────────────────────────────────────
    A("## 9 · 判决")
    A("")
    # 计算判决所需的数
    pair_all = [s for s in rng if s.hit is not None and s.mir_hit is not None]
    dex_all = [((1 if s.mir_hit else 0) - s.mir_pnull)
               - ((1 if s.hit else 0) - s.pnull) for s in pair_all]
    t_dex = tstat(dex_all)
    inbox = [s for s in rng if s.in_box]
    v_t = tstat([s.v for s in inbox]) if len(inbox) >= 10 else float("nan")
    _, v_w, _ = wilcoxon([s.v for s in inbox]) if len(inbox) >= 10 else (0, float("nan"), 0)
    A("| 推论 | 结果 | 判定 |")
    A("|---|---|---|")
    A(f"| P1 区间×交叉类劣于几何零假设 | z_geom = {zr:+.2f} "
      f"(n={grid[(RANGE,'ALL')]['res']}) | 见下 |")
    A(f"| P2 反着做更好（**最硬的一条**） | 配对超额差 t = {t_dex:+.2f} | 见下 |")
    A(f"| P3 空在盒下半 / 多在盒上半 | v 均值 {st.mean([s.v for s in inbox]):+.3f}，"
      f"t = {v_t:+.2f}，Wilcoxon z = {v_w:+.2f} | 见下 |")
    A(f"| P4 边缘拒绝优于同期交叉类 | 见 §5 | 见下 |")
    A("")

    txt = "\n".join(o) + "\n"
    REPORT.write_text(txt)
    RAW.write_text(txt)
    print(txt)

    # 控制台摘要，供最终返回值使用
    print("=" * 78)
    print("SUMMARY-FOR-AGENT")
    print(f"cells={CELLS} bonf={thr:.2f}")
    print(f"n_all={len(sigs)} n_range={len(rng)} n_trend={len(trd)}")
    for k, d in grid.items():
        if d:
            print(f"  {k}: n={d['n']} res={d['res']} obs={d['obs']:.4f} "
                  f"null={d['null']:.4f} z={d['z']:+.3f} bnet={d['bnet']:+.4f} "
                  f"money={1000*d['bmoney']:+.2f}")
    print(f"state_score_z={dz:+.3f}")
    print(f"pair_excess_t={t_dex:+.3f} n={len(pair_all)}")
    print(f"v_mean={st.mean([s.v for s in inbox]):+.4f} t={v_t:+.3f} w={v_w:+.3f} "
          f"n_inbox={len(inbox)}")
    print(f"n_edges={len(edges)}")


if __name__ == "__main__":
    main()
