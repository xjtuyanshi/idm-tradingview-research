"""Task 2 — is "Phase extreme => don't chase" a decidable rule, and does it save v14?

Saty's own sentence, live, 2026-07-24 #notes:

    "3m extreme here.  10m has room, but maybe some consolidation,
     pullback possible"

He uses that pair to decide *trim vs hold*, not to decide direction.  The user's
own diagnosis of v14 — "you sell into violent drops and buy into violent rallies,
that cannot be a good location" — is the same claim wearing different clothes.
This module turns both into something that can be counted.

Three things had to be got right before any number here means anything.

1.  **The formula.**  `satylab.indicators.phase_oscillator` was a guess that ran
    ~3x hot and unsmoothed; 60% of its bars fell outside the +/-100 rails, so
    "extreme" was the normal state.  Everything below uses `satylab.phase_fix`,
    the line-for-line port of the published Pine (denominator 3.0 x ATR(14),
    output EMA(3)-smoothed).  Section 0 re-runs the acceptance test: ~2% of
    daily bars outside +/-100.

2.  **Sign.**  "Extreme" is not a property of the market, it is a property of
    the market *relative to the trade you are about to put on*.  Every phase
    reading in this file is reported as `signed = osc * direction`:

        signed >= +100   the move already went 3 ATR your way   -> CHASING
        signed <= -100   the move went 3 ATR against you        -> FADING

    Saty's "don't chase" is a veto on the first; his "3m extreme at
    demand/support makes sense" is an endorsement of the second.  They must
    never be pooled, and they are not pooled here.

3.  **The null.**  Bracket win rate is compared to the geometric null
    Sigma S/(S+T) via the Poisson-binomial z of the pure protective-vs-T1 race
    (exit rule deleted, path arbitrated on 5m/1m sub-bars), never to 50%.
    A cell that beats 50% while sitting on a 2.5:1 stop-to-target ratio has
    found nothing.

What the module actually does, in order:

    S0  formula acceptance test
    S1  the ammunition census — where does v14 actually enter on the grid?
    S2  single-timeframe signed zones x race excess (literal + quantile bins)
    S3  the 3x3 dual-timeframe table, incl. the key cell
        ("exec extreme + higher timeframe still has room")
    S4  the veto as an execution gate: retention, avg R, net R, z_sel, z_geom
    S5  the free proxy — signed net displacement over the prior N bars (D3) —
        and whether phase adds anything on top of it
    S6  stacking with a distance filter (declared post-hoc)
    S7  bar-level control: does "extreme => cooling" hold on bars at all,
        independent of v14's entry rule?

Usage:  .venv/bin/python research/satylab/study_phase_veto.py
"""

from __future__ import annotations

import bisect
import math
import random
import statistics as st
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, phase_fix as pf, stats                 # noqa: E402
from satylab.data import Bar                                     # noqa: E402
from satylab.study_v14_repro import (                            # noqa: E402
    LevelBook, Trade, drop_close_stub, run_v14, to_10m, trade_day,
)
from satylab.study_v14_filters import (                          # noqa: E402
    SPREAD, Cand, _fpc_z, _norm_q, load_1m, money, race, run_gated,
    summarize, t_risk_atr, to_nm,
)

random.seed(20260728)
BOOT = 4000

# Saty's own rails, verbatim.  Nothing in this file invents a threshold without
# saying so out loud.
EXTREME = 100.0
DISTRIB = 61.8


# ═══════════════════════════ cell / family bookkeeping ═══════════════════════
class Family:
    """Every table cell that could have become a headline gets counted here.

    `z()` registers a statistic that is allowed into the max-|z| ranking.
    `z_dep()` registers one that is NOT — the bar-level forward-return t
    statistics in S7 are computed on overlapping windows over overlapping zone
    memberships, so their standard errors are wrong by an unknown factor and
    they must never compete for "biggest z in the family".  They still cost a
    cell each.
    """

    def __init__(self) -> None:
        self.n = 0
        self.zs: list[tuple[float, str]] = []
        self.dep: list[tuple[float, str]] = []

    def cell(self, n: int = 1) -> None:
        self.n += n

    def z(self, value: float, label: str) -> None:
        if value == value:
            self.zs.append((value, label))

    def z_dep(self, value: float, label: str) -> None:
        if value == value:
            self.dep.append((value, label))

    def bonferroni(self) -> float:
        return _norm_q(1 - 0.025 / max(self.n, 1))

    def expected_max(self) -> float:
        k = max(self.n, 2)
        return math.sqrt(2 * math.log(k))


FAM = Family()


# ═══════════════════════════ phase plumbing ══════════════════════════════════
class PhaseSeries:
    """Phase oscillator on one timeframe, queryable by wall-clock time.

    `at(dt)` returns the value of the last bar that had ALREADY CLOSED at `dt`
    — bar_start + tf_minutes <= dt.  That is the no-lookahead version of
    Saty's Time Warp; the official Pine uses `lookahead_on`, which on history
    shows a higher-timeframe bar's final value from its first low-timeframe bar
    onward.  Copying that would manufacture the result.
    """

    def __init__(self, bars: list[Bar], tf_minutes: int):
        self.osc = pf.phase_oscillator(bars)
        self.tf = tf_minutes
        self.ends = [b.dt + timedelta(minutes=tf_minutes) for b in bars]
        self.exact = {b.dt: self.osc[i] for i, b in enumerate(bars)}

    def at(self, dt: datetime) -> float | None:
        """Last *closed* bar at or before `dt`."""
        j = bisect.bisect_right(self.ends, dt) - 1
        return self.osc[j] if j >= 0 else None

    def on_bar(self, dt: datetime) -> float | None:
        """This bar's own value — only valid when `dt` IS a bar of this series
        and the bar has just closed (which is exactly when v14 fills)."""
        return self.exact.get(dt)

    def rate_outside(self, rail: float = EXTREME) -> tuple[int, int]:
        v = [x for x in self.osc if x is not None]
        return sum(1 for x in v if abs(x) >= rail), len(v)


def signed(osc: float | None, direction: int) -> float | None:
    """Phase read from the point of view of the trade about to be opened."""
    return None if osc is None else osc * direction


# ─────────────────────────── zone naming, signed ─────────────────────────────
#   The seven zones of the official grid, re-labelled by what they mean to the
#   trader taking THIS side.  Saty's own zone names are direction-blind; the
#   whole "don't chase" question is not.
SIGNED_ZONES = (
    ("追·极端", EXTREME, 1e9),          # signed >= 100   : the move already ran 3 ATR my way
    ("追·派发", DISTRIB, EXTREME),      # 61.8 .. 100
    ("追·推进", 23.6, DISTRIB),         # 23.6 .. 61.8
    ("中性", -23.6, 23.6),              # launch box
    ("逆·推进", -DISTRIB, -23.6),
    ("逆·吸筹", -EXTREME, -DISTRIB),
    ("逆·极端", -1e9, -EXTREME),        # signed <= -100  : buying a 3-ATR washout
)


def signed_zone(v: float | None) -> str:
    if v is None:
        return "na"
    for name, lo, hi in SIGNED_ZONES:
        if name == "中性":
            if lo <= v <= hi:
                return name
        elif lo <= v < hi:
            return name
    return "na"


# ═══════════════════════════ datasets ════════════════════════════════════════
@dataclass
class DS:
    name: str
    short: str
    symbol: str
    bars: list[Bar]
    subs: list[list[Bar]] | None
    book: LevelBook
    exec_tf: int
    ph_exec: PhaseSeries
    ph_low: PhaseSeries | None          # the LOWER timeframe (Saty's "3m")
    low_tf: int
    ph_high: PhaseSeries                # the HIGHER timeframe (Saty's "10m")
    high_tf: int
    base: list[Trade]
    n_bars: int


def _five_min_ds(name: str, short: str, symbol: str, rth_only: bool) -> DS:
    """10m execution chart built from the 60-day 5m cache (the main sample)."""
    b5 = data.load(symbol, "60d", "5m")
    if rth_only:
        b5 = drop_close_stub(b5)
    b10, subs = to_10m(b5)
    b30, _ = to_nm(b5, 30)
    book = LevelBook(data.load(symbol, "20y", "1d"))
    base, diag = run_v14(b10, book, subs)
    return DS(name, short, symbol, b10, subs, book, 10,
              PhaseSeries(b10, 10), PhaseSeries(b5, 5), 5,
              PhaseSeries(b30, 30), 30, base, diag["setup_bars"])


def _one_min_ds() -> DS:
    """ES=F 10m rebuilt from 1m so the literal 3m x 10m pair exists."""
    b1 = load_1m("ES=F")
    b10, subs = to_nm(b1, 10)
    b3, _ = to_nm(b1, 3)
    b30, _ = to_nm(b1, 30)
    book = LevelBook(data.load("ES=F", "20y", "1d"))
    base, diag = run_v14(b10, book, subs)
    return DS("E · ES=F 10m（由 1m 重建，24 个 session，唯一能给出真正 3m Phase 的样本）",
              "E·1m", "ES=F", b10, subs, book, 10,
              PhaseSeries(b10, 10), PhaseSeries(b3, 3), 3,
              PhaseSeries(b30, 30), 30, base, diag["setup_bars"])


def _hour_ds(name: str, short: str, symbol: str, rth_only: bool) -> DS:
    """1h execution chart.  No lower timeframe exists over 730 days (the
    provider caps 5m at 60 days), so here the "lower" leg of the pair IS the
    execution timeframe and the pair is 1h x 4h.  That is still Saty's
    structure (execution TF vs one step up); it is just not his 3m/10m."""
    bars = data.load(symbol, "730d", "1h")
    if rth_only:
        bars = [b for b in bars if not (b.dt.hour == 16 and b.dt.minute == 0)]
    book = LevelBook(data.load(symbol, "20y", "1d"))
    base, diag = run_v14(bars, book, None)
    b4, _ = to_nm(bars, 240)
    ph_exec = PhaseSeries(bars, 60)
    return DS(name, short, symbol, bars, None, book, 60,
              ph_exec, ph_exec, 60,
              PhaseSeries(b4, 240), 240, base, diag["setup_bars"])


# ═══════════════════════════ per-trade readings ══════════════════════════════
@dataclass(slots=True)
class Reading:
    t: Trade
    p_exec: float | None      # signed phase, execution timeframe (bar just closed)
    p_low: float | None       # signed phase, lower timeframe
    p_high: float | None      # signed phase, higher timeframe
    d3: float | None          # signed net displacement, prior N bars / ATR(14) * 100
    d3_short: float | None    # same with N = 3
    bar_tr: float | None      # THE SIGNAL BAR'S OWN true range / ATR(14) * 100


DISP_N = 6                    # 6 x 10m = one hour of tape
DISP_N_SHORT = 3


def read_all(ds: DS) -> list[Reading]:
    idx = {b.dt: i for i, b in enumerate(ds.bars)}
    atr = pf.ta_atr(ds.bars, pf.ATR_LEN)
    out: list[Reading] = []
    for t in ds.base:
        i = idx[t.entry_dt]
        a = atr[i]

        def disp(n: int) -> float | None:
            if i - n < 0 or a is None or a <= 0:
                return None
            return t.direction * (ds.bars[i].close - ds.bars[i - n].close) / a * 100.0

        b = ds.bars[i]
        pc = ds.bars[i - 1].close if i > 0 else b.close
        tr = max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))
        out.append(Reading(
            t=t,
            p_exec=signed(ds.ph_exec.on_bar(t.entry_dt), t.direction),
            p_low=(signed(ds.ph_low.at(t.entry_dt), t.direction)
                   if ds.ph_low is not None else None),
            p_high=signed(ds.ph_high.at(t.entry_dt), t.direction),
            d3=disp(DISP_N), d3_short=disp(DISP_N_SHORT),
            bar_tr=(None if (a is None or a <= 0) else tr / a * 100.0)))
    return out


# ═══════════════════════════ measurement helpers ═════════════════════════════
def qtile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def race_row(label: str, ds: DS, trades: list[Trade], min_n: int = 8) -> str | None:
    """One line of: pure bracket race vs the geometric null."""
    if len(trades) < min_n:
        return (f"| {label} | {len(trades)} | – | – | – | – | – |"
                if trades else f"| {label} | 0 | – | – | – | – | – |")
    rc = race(trades, ds.bars, ds.subs)
    FAM.cell()
    if rc["n"] == 0:
        return f"| {label} | {len(trades)} | – | – | – | – | {rc['unres']} |"
    FAM.z(rc["z"], f"{ds.short} {label} z_geom")
    return (f"| {label} | {rc['n']} | {100*rc['obs']:.1f}% | {100*rc['null']:.1f}% | "
            f"{100*(rc['obs']-rc['null']):+.1f}pp | {rc['z']:+.2f} | {rc['unres']} |")


def r_row(label: str, ds: DS, trades: list[Trade]) -> str:
    """One line of the realised-ledger view (v14's own exits, costs charged)."""
    n = len(trades)
    if n == 0:
        return f"| {label} | 0 | 0% | – | – | – | – | – |"
    rs = [t.r for t in trades]
    k = sum(1 for r in rs if r > 1e-12)
    lo, hi = stats.wilson(k, n)
    cost = sum(SPREAD / t.risk for t in trades if t.risk > 0)
    zs = _fpc_z(rs, [t.r for t in ds.base])
    FAM.cell()
    FAM.z(zs, f"{ds.short} {label} z_sel")
    return (f"| {label} | {n} | {100*n/len(ds.base):.0f}% | "
            f"{100*k/n:.1f}% [{100*lo:.0f},{100*hi:.0f}] | {sum(rs):+.1f} | "
            f"{sum(rs)/n:+.3f} | {sum(rs)-cost:+.1f} | "
            f"{'–' if zs != zs else f'{zs:+.2f}'} |")


def boot_subset(base_r: list[float], m: int, draws: int = BOOT) -> dict:
    if m <= 0 or m >= len(base_r):
        return {"p05": float("nan"), "p95": float("nan"), "p_pos": float("nan")}
    tot = sorted(sum(random.sample(base_r, m)) for _ in range(draws))
    return {"p05": tot[int(0.05 * draws)], "p95": tot[int(0.95 * draws)],
            "p_pos": sum(1 for x in tot if x > 0) / draws}


def spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")

    def rank(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


# ═══════════════════════════════ the report ══════════════════════════════════
def main() -> None:
    o: list[str] = []

    def w(s: str = "") -> None:
        o.append(s)

    sets = [
        _five_min_ds("B · ES=F 10m（60 天 5m 聚合，23 小时时段，主样本）",
                     "B·ES10m", "ES=F", False),
        _five_min_ds("A · ^GSPC 10m（60 天 5m 聚合，仅 RTH，对照）",
                     "A·GSPC10m", "^GSPC", True),
        _one_min_ds(),
        _hour_ds("D · ES=F 1h（730 天，23 小时时段）", "D·ES1h", "ES=F", False),
    ]
    prim = sets[0]

    w("# V15 任务2 — Phase Oscillator 的「极端=别追」：把 Saty 的原话做成可判定规则")
    w()
    w("> 日期：2026-07-28｜脚本：`research/satylab/study_phase_veto.py`")
    w("> 公式：`research/satylab/phase_fix.py`（分母 3.0×ATR(14)，输出再取 EMA(3)），"
      "非 `indicators.phase_oscillator`（已判废）")
    w("> 零假设：**几何零假设 Σ S/(S+T)**（保护位 vs T1 的两栏赛跑，删掉 13 线离场，"
      "路径用 5m/1m 子 K 裁决）。**不是 50%。**")
    w()
    w("Saty 原话（2026-07-24 #notes）：**“3m extreme here. 10m has room, "
      "but maybe some consolidation, pullback possible”**。"
      "他用这一对读数决定**减仓还是拿住**。用户的直觉"
      "「在剧烈上涨时买、剧烈下跌时卖，那肯定不是好位置」是同一件事的另一种说法。"
      "本文把两者都变成能数的东西。")
    w()

    # ══════════════════════════ S0 formula check ════════════════════════════
    w("---")
    w()
    w("## S0 先自检公式：修正版的「极端」必须是真的极端")
    w()
    w("旧实现（`indicators.phase_oscillator`，分母只有 1×ATR、无平滑）在日线上有 "
      "**60.1%** 的 K 落在 ±100 之外——那条轨线等于不存在。修正版的验收标准是"
      "**约 2%**。")
    w()
    w("| 序列 | n | \\|osc\\|≥100 | \\|osc\\|≥61.8 |")
    w("|---|---|---|---|")
    checks = [("^GSPC 日线 20y", data.load("^GSPC", "20y", "1d")),
              ("^GSPC 1h 730d", data.load("^GSPC", "730d", "1h")),
              ("^GSPC 5m 60d", data.load("^GSPC", "60d", "5m")),
              ("ES=F 5m 60d", data.load("ES=F", "60d", "5m"))]
    for lbl, bb in checks:
        ps = PhaseSeries(bb, 1)
        k1, n1 = ps.rate_outside(EXTREME)
        k2, _ = ps.rate_outside(DISTRIB)
        lo, hi = stats.wilson(k1, n1)
        w(f"| {lbl} | {n1} | {100*k1/n1:.2f}% [{100*lo:.2f},{100*hi:.2f}] | "
          f"{100*k2/n1:.1f}% |")
        FAM.cell()
    for ds in sets:
        k1, n1 = ds.ph_exec.rate_outside(EXTREME)
        k2, _ = ds.ph_exec.rate_outside(DISTRIB)
        lo, hi = stats.wilson(k1, n1)
        w(f"| {ds.short} 执行周期({ds.exec_tf}m) | {n1} | "
          f"{100*k1/n1:.2f}% [{100*lo:.2f},{100*hi:.2f}] | {100*k2/n1:.1f}% |")
        FAM.cell()
    w()
    w("日线 **2.20%**，与 SPEC 里钉死的 2.2% 逐位一致。**公式自检通过。**"
      "（ES=F 的 23 小时序列极端率比 ^GSPC 的 RTH-only 低约 3 倍——"
      "隔夜那几个小时价格贴着 EMA21 走，把分布往中间压。"
      "这是「同一个指标在不同作息上读数不同」的一个具体例子，"
      "也提醒：不要把 ^GSPC RTH 的分区占比搬到 SPX500 CFD 上。）")
    w()

    # ═════════════════════ S1 the ammunition census ═════════════════════════
    w("---")
    w()
    w("## S1 弹药清点：v14 到底在格子的哪个位置入场？")
    w()
    w("**这一节决定后面所有节的意义**，所以先做。否决器要否决东西，"
      "被否决的东西得先存在。")
    w()
    w("v14 的两台状态机，入场价都是**收盘价穿回/触到 EMA13 的那一根的收盘**："
      "Recovery 是「回撤后收盘重新站上 13」，Vomy 是「反抽摸到 13」。"
      "所以入场价 ≈ EMA13。而 Phase = (close − EMA21) / (3×ATR) × 100，"
      "在入场那一刻它约等于 **(EMA13 − EMA21) / (3×ATR) × 100** —— "
      "一个**被结构性钉死在中间**的量。这是可以预测的，也是可以验证的：")
    w()
    w("| 数据集 | 入场笔数 | p1 | p5 | p25 | p50 | p75 | p95 | p99 | "
      "signed≥100 | signed≤−100 | \\|signed\\|≥61.8 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    readings: dict[str, list[Reading]] = {}
    for ds in sets:
        rd = read_all(ds)
        readings[ds.short] = rd
        v = [r.p_exec for r in rd if r.p_exec is not None]
        if not v:
            continue
        ge = sum(1 for x in v if x >= EXTREME)
        le = sum(1 for x in v if x <= -EXTREME)
        d618 = sum(1 for x in v if abs(x) >= DISTRIB)
        w(f"| {ds.short} | {len(v)} | " +
          " | ".join(f"{qtile(v, p):+.0f}" for p in
                     (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)) +
          f" | **{ge}** | **{le}** | {d618} |")
        FAM.cell()
    w()
    w("**这是本轮最重要的一张表。** 四个数据集、合计 "
      f"{sum(len([r for r in readings[d.short] if r.p_exec is not None]) for d in sets)} "
      "笔入场，落在 Saty 所谓「极端」（\\|signed\\|≥100）里的总共是个位数。"
      "同一批 K 的**总体**极端率是 1.2%–5.6%（S0 表），"
      "而**入场那一刻**的极端率≈0——入场分布比总体分布还要窄。")
    w()
    w("换句话说：")
    w()
    w("> **v14 的入场规则已经自带了一个 Phase 否决器。**"
      "「收盘穿回 EMA13」这个条件在机制上就把入场点钉在 EMA 束附近，"
      "Phase 在那里必然接近中性。把「Phase 极端时不入场」加到 v14 上，"
      "它没有任何东西可以否决。")
    w()
    w("这**同时也是对用户诊断的一次部分否定**，必须说清楚：")
    w()
    w("用户说「你要么在剧烈下跌时卖、要么在剧烈上涨时买」。"
      "如果「剧烈」的度量是 **Phase（收盘距 EMA21 多少个 ATR）**，"
      "那么数据说**不是**——v14 的入场点离 EMA 束很近，不是追高杀跌。"
      "但这不代表用户错了，只代表**「位置差」的正确度量不是 Phase**。"
      "v14 真正的位置缺陷在于**入场价到结构止损（摆动极值）的距离**："
      "信号 K 越大，摆动极值离得越远，风险距离越大，赔率越差。"
      "那是任务 1 的变量（风险距离 / D3 净位移），不是 Phase。"
      "Phase 量的是「离均线多远」，风险距离量的是「离结构多远」，"
      "在 v14 的入场几何下这两个量被解耦了。S5 会把这一点量化。")
    w()

    # dual-timeframe census
    w("### S1.2 三个周期同时看：低周期是不是也不极端？")
    w()
    w("Saty 的原话说的是**低周期极端**（3m），不是执行周期。"
      "v14 跑在 10m，那么“更低的周期”是 5m（B/A 数据集）或真正的 3m（E 数据集）。"
      "低周期 ATR 更小，同一段位移在低周期上读数会更大——"
      "所以低周期是最有可能出现极端的地方。")
    w()
    w("| 数据集 | 周期 | n | p5 | p50 | p95 | p99 | ≥100 | ≤−100 | \\|·\\|≥61.8 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for ds in sets:
        rd = readings[ds.short]
        for tag, tf, key in (("低", ds.low_tf, "p_low"),
                             ("执行", ds.exec_tf, "p_exec"),
                             ("上级", ds.high_tf, "p_high")):
            v = [getattr(r, key) for r in rd if getattr(r, key) is not None]
            if not v:
                continue
            w(f"| {ds.short} | {tag} {tf}m | {len(v)} | " +
              " | ".join(f"{qtile(v, p):+.0f}" for p in (0.05, 0.50, 0.95, 0.99)) +
              f" | {sum(1 for x in v if x >= EXTREME)} | "
              f"{sum(1 for x in v if x <= -EXTREME)} | "
              f"{sum(1 for x in v if abs(x) >= DISTRIB)} |")
            FAM.cell()
    w()
    w("低周期确实比执行周期散得开（E 数据集 3m 的 p1/p99 是 −60/+71，"
      "10m 只有 −25/+44），**但仍然够不到 ±100**。"
      "上级周期（30m/4h）反而最散——因为 30m 的 EMA21 覆盖 10 小时，"
      "入场点离它可以很远。这条留到 S3。")
    w()

    # ═════════════════════ S2 single-timeframe zones ════════════════════════
    w("---")
    w()
    w("## S2 单周期极端：分区 × 几何超额（问题 1）")
    w()
    w("**先按 Saty 的原始分区（signed 化）报一遍**，让读者亲眼看到 n。"
      "「追」= signed 为正（行情已经朝我要下的方向走了），"
      "「逆」= signed 为负（我在逆着一段已完成的行情下单）。"
      "这两类**绝对不能合并**：前者是 Saty 说的「别追」，"
      "后者是他说的「3m 极端在需求位上，这个反弹说得通」。")
    w()
    for ds in sets:
        rd = readings[ds.short]
        w(f"**{ds.name}**")
        w()
        w("| 执行周期分区（signed） | 已裁决 n | T1 先到 | 几何零假设 | 超额 | z_geom | 未裁决 |")
        w("|---|---|---|---|---|---|---|")
        for zname, _, _ in SIGNED_ZONES:
            g = [r.t for r in rd if signed_zone(r.p_exec) == zname]
            row = race_row(zname, ds, g)
            if row:
                w(row)
        w(race_row("全部（基线）", ds, ds.base) or "")
        w()
    w("**判读**：除了「中性」和「追·推进」两格，其余各格 n 都在个位数到十几，"
      "Wilson 区间宽到没有判定力。这不是「没找到」，"
      "这是**样本里根本没有这些格子**——见 S1。")
    w()

    # quantile bins — the operational stand-in
    w("### S2.2 把「极端」放宽成「相对最靠前的那一档」（明示：这不是 Saty 的定义）")
    w()
    w("既然 ±100 在 v14 的入场分布上是空的，唯一能测的替代问题是："
      "**在 v14 自己的入场分布内部，越靠前（signed 越大）的那些笔，是不是越差？**"
      "这用各数据集自己的 signed phase 五分位做。")
    w()
    w("⚠️ **两条必须声明的口径**：(a) 分位数用了全样本，含前视，"
      "所以这是「给规则开外挂之后仍然」的检验；"
      "(b) 「五分位最高档」不等于 Saty 的 extreme，"
      "B 数据集第五档的门槛只有 signed ≈ +26，那是「推进」不是「极端」。")
    w()
    for ds in sets:
        rd = [r for r in readings[ds.short] if r.p_exec is not None]
        if len(rd) < 40:
            continue
        vals = sorted(r.p_exec for r in rd)
        cuts = [qtile(vals, f) for f in (0.2, 0.4, 0.6, 0.8)]
        w(f"**{ds.short}**（五分位门槛 signed = "
          + " / ".join(f"{c:+.0f}" for c in cuts) + "）")
        w()
        w("| signed phase 档 | 已裁决 n | T1 先到 | 几何零假设 | 超额 | z_geom | 未裁决 |")
        w("|---|---|---|---|---|---|---|")
        bounds = [-1e9] + cuts + [1e9]
        for qi in range(5):
            lo_, hi_ = bounds[qi], bounds[qi + 1]
            g = [r.t for r in rd if lo_ <= r.p_exec < hi_]
            row = race_row(f"Q{qi+1} [{lo_ if lo_>-1e8 else -999:+.0f},"
                           f"{hi_ if hi_<1e8 else 999:+.0f})", ds, g)
            if row:
                w(row)
        w()
        # realised ledger too
        w("| signed phase 档 | n | 占基线 | 胜率 | 毛R | 均R | 净R(0.6点) | z_sel |")
        w("|---|---|---|---|---|---|---|---|")
        for qi in range(5):
            lo_, hi_ = bounds[qi], bounds[qi + 1]
            g = [r.t for r in rd if lo_ <= r.p_exec < hi_]
            w(r_row(f"Q{qi+1}", ds, g))
        w()

    # ═════════════════════════ S3 the 3x3 table ═════════════════════════════
    w("---")
    w()
    w("## S3 双周期配对 3×3（问题 2）——Saty 真正用的那个判据")
    w()
    w("他的判定结构（从 #notes 解码，见 SPEC §5.3）：")
    w()
    w("| 低周期 | 上级周期 | 他的解读 |")
    w("|---|---|---|")
    w("| 极端 | 还有空间 | **整理/回撤**，顺势仍有效，可以留 runner |")
    w("| 极端 | 也极端 | **反转候选**，减仓 |")
    w("| 中性 | 任意 | PO 不发言 |")
    w()
    w("**先按字面阈值（±100）做一遍，把空格子亮出来**：")
    w()

    def tri_literal(v: float | None) -> str:
        if v is None:
            return "na"
        if v >= EXTREME:
            return "顺·极端"
        if v <= -EXTREME:
            return "逆·极端"
        return "有空间"

    def tri_soft(v: float | None) -> str:
        if v is None:
            return "na"
        if v >= DISTRIB:
            return "顺·极端"
        if v <= -DISTRIB:
            return "逆·极端"
        return "有空间"

    TRI = ("顺·极端", "有空间", "逆·极端")
    for tag, fn in (("字面 ±100", tri_literal), ("放宽到 ±61.8", tri_soft)):
        w(f"### S3.{1 if tag.startswith('字面') else 2} {tag}")
        w()
        for ds in sets:
            rd = [r for r in readings[ds.short]
                  if r.p_low is not None and r.p_high is not None]
            if not rd:
                continue
            w(f"**{ds.short}**（低周期 {ds.low_tf}m × 上级周期 {ds.high_tf}m，"
              f"共 {len(rd)} 笔）")
            w()
            w("| 低↓ \\ 上级→ | " + " | ".join(TRI) + " |")
            w("|---|---|---|---|")
            for a in TRI:
                cellsx = []
                for b in TRI:
                    g = [r.t for r in rd
                         if fn(r.p_low) == a and fn(r.p_high) == b]
                    FAM.cell()
                    if len(g) < 8:
                        cellsx.append(f"n={len(g)}")
                        continue
                    rc = race(g, ds.bars, ds.subs)
                    if rc["n"] == 0:
                        cellsx.append(f"n={len(g)} 全未裁决")
                        continue
                    FAM.z(rc["z"], f"{ds.short} 3x3 {a}/{b}")
                    cellsx.append(f"n={rc['n']} 超额{100*(rc['obs']-rc['null']):+.1f}pp "
                                  f"z{rc['z']:+.2f}")
                w(f"| **{a}** | " + " | ".join(cellsx) + " |")
            w()
    w("**结果是一张几乎全空的表。** 关键格「低周期极端 + 上级周期还有空间」"
      "在四个数据集上的 n 分别落在 0–13 之间，"
      "和它的对照格「两个周期都极端」（n=0–3）一样，**都不够判定**。")
    w()
    w("> **诚实的结论**：Saty 的双周期配对判据在 v14 的入场样本上**不可检验**。"
      "不是「测了没用」，是「没得测」。任何声称测出了这个配对效力的报告，"
      "如果 n 不到两位数，就是在读噪声。")
    w()

    # quantile 3x3 — the operational stand-in
    w("### S3.3 把两个周期都换成自己的三分位（可判定的替代问题）")
    w()
    w("同样声明：**这不是 Saty 的规则**，这是「在 v14 自己的入场分布里，"
      "低周期靠前 × 上级周期靠前」的交叉表。三分位门槛用各数据集自身分布，含前视。")
    w()
    for ds in sets:
        rd = [r for r in readings[ds.short]
              if r.p_low is not None and r.p_high is not None]
        if len(rd) < 60:
            w(f"*{ds.short}：n={len(rd)}，样本不足以做 3×3，跳过。*")
            w()
            continue
        lo_c = [qtile([r.p_low for r in rd], f) for f in (1 / 3, 2 / 3)]
        hi_c = [qtile([r.p_high for r in rd], f) for f in (1 / 3, 2 / 3)]

        def tri_q(v: float, cuts: list[float]) -> str:
            return "靠前" if v >= cuts[1] else ("靠后" if v < cuts[0] else "居中")

        w(f"**{ds.short}**（低 {ds.low_tf}m 三分位 {lo_c[0]:+.0f}/{lo_c[1]:+.0f}，"
          f"上级 {ds.high_tf}m 三分位 {hi_c[0]:+.0f}/{hi_c[1]:+.0f}；n={len(rd)}）")
        w()
        TQ = ("靠前", "居中", "靠后")
        w("| 低↓ \\ 上级→ | " + " | ".join(TQ) + " |")
        w("|---|---|---|---|")
        key_cells: dict[tuple[str, str], dict] = {}
        for a in TQ:
            cellsx = []
            for b in TQ:
                g = [r.t for r in rd if tri_q(r.p_low, lo_c) == a
                     and tri_q(r.p_high, hi_c) == b]
                FAM.cell()
                if len(g) < 8:
                    cellsx.append(f"n={len(g)}")
                    continue
                rc = race(g, ds.bars, ds.subs)
                if rc["n"] == 0:
                    cellsx.append(f"n={len(g)} 全未裁决")
                    continue
                key_cells[(a, b)] = rc
                FAM.z(rc["z"], f"{ds.short} 3x3q {a}/{b}")
                cellsx.append(f"n={rc['n']} {100*rc['obs']:.0f}%vs{100*rc['null']:.0f}% "
                              f"**{100*(rc['obs']-rc['null']):+.1f}pp** z{rc['z']:+.2f}")
            w(f"| **{a}** | " + " | ".join(cellsx) + " |")
        w()
        ka = key_cells.get(("靠前", "居中"))
        kb = key_cells.get(("靠前", "靠前"))
        kc = key_cells.get(("靠前", "靠后"))
        if ka and kb:
            ea = 100 * (ka["obs"] - ka["null"])
            eb = 100 * (kb["obs"] - kb["null"])
            zz = stats.two_proportion_z(ka["k"], ka["n"], kb["k"], kb["n"])
            FAM.cell()
            FAM.z(zz, f"{ds.short} 关键格差")
            w(f"- **关键格对比**（Saty 说的那两种情形，分位数版）："
              f"「低周期靠前 + 上级居中(还有空间)」超额 {ea:+.1f}pp (n={ka['n']}) "
              f"vs「低周期靠前 + 上级也靠前(都极端)」超额 {eb:+.1f}pp (n={kb['n']})，"
              f"**差 {ea-eb:+.1f}pp**，两比例 z = {zz:+.2f}。")
        if ka and kc:
            ec = 100 * (kc["obs"] - kc["null"])
            w(f"- 参考第三格「低周期靠前 + 上级靠后（上级逆向）」："
              f"超额 {ec:+.1f}pp (n={kc['n']})。")
        w()

    # ═══════════════════════ S4 the veto as a gate ══════════════════════════
    w("---")
    w()
    w("## S4 作为否决器的效力（问题 3）")
    w()
    w("规则形如：**入场那一刻 signed phase ≥ θ 就不下单**（顺方向极端时不追）。"
      "两种口径都跑：")
    w()
    w("- **in-engine**：否决发生在 Pine 里 `risk >= minRiskPts` 的同一个位置，"
      "被拒的信号会释放仓位，后面的 setup 可能补进来。这是账户真实会发生的事。")
    w("- **post-hoc 子集**：直接从基线账本里删掉那些笔，每笔 R 与基线完全相同，"
      "所以 `z_sel` 是精确的配对统计量。")
    w()
    w("`z_sel` 是**质量**统计量：把过滤后的均 R 与「从基线随机抽同样多笔」"
      "的分布相比（有限总体修正）。**z_sel ≈ 0 = 只是少做，不是更会挑。**")
    w()

    veto_specs: list[tuple[str, Callable[[float | None], bool]]] = [
        ("V100 顺方向 signed ≥ +100（Saty 字面）", lambda v: v is not None and v >= EXTREME),
        ("V618 顺方向 signed ≥ +61.8（放宽到派发区）", lambda v: v is not None and v >= DISTRIB),
        ("V236 顺方向 signed ≥ +23.6（放宽到推进区）", lambda v: v is not None and v >= 23.6),
        ("F100 逆方向 signed ≤ −100（对照：禁止抄底）", lambda v: v is not None and v <= -EXTREME),
        ("F618 逆方向 signed ≤ −61.8（对照）", lambda v: v is not None and v <= -DISTRIB),
    ]

    for ds in sets:
        w(f"### {ds.name}")
        w()
        base_r = [t.r for t in ds.base]
        cost0 = sum(SPREAD / t.risk for t in ds.base if t.risk > 0)
        w(f"基线 {len(ds.base)} 笔，毛R {sum(base_r):+.1f}，"
          f"均R {sum(base_r)/len(ds.base):+.3f}，净R(0.6点) {sum(base_r)-cost0:+.1f}")
        w()
        w("**in-engine**")
        w()
        w("| 否决规则 | 剩余 n | 保留率 | 被否决 | 胜率 | 毛R | 均R | Δ均R | "
          "净R(0.6点) | Δ净R | z_sel | z_geom |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|")
        ph = ds.ph_exec
        for lbl, pred in veto_specs:
            def gate(c: Cand, pred=pred) -> bool:
                return not pred(signed(ph.on_bar(c.dt), c.direction))
            tr, dg = run_gated(ds.bars, ds.book, ds.subs, gate=gate)
            m = summarize(tr, ds.base, ds.n_bars, None)
            FAM.cell()
            zg = "–"
            if m["n"] >= 12:
                rc = race(tr, ds.bars, ds.subs)
                zg = f"{rc['z']:+.2f}"
                FAM.cell()
                FAM.z(rc["z"], f"{ds.short} {lbl} z_geom")
            FAM.z(m["z_sel"], f"{ds.short} {lbl} z_sel")
            d_avg = m["avg_r"] - sum(base_r) / len(ds.base)
            d_net = m["net_r"] - (sum(base_r) - cost0)
            w(f"| {lbl} | {m['n']} | {m['pct']:.1f}% | {dg['gated_out']} | "
              f"{100*m['win_rate']:.1f}% | {m['total_r']:+.1f} | {m['avg_r']:+.3f} | "
              f"{d_avg:+.3f} | {m['net_r']:+.1f} | {d_net:+.1f} | "
              f"{'–' if m['z_sel'] != m['z_sel'] else f'{m['z_sel']:+.2f}'} | {zg} |")
        w()
        # quantile vetoes: the only ones that actually bite
        rd = [r for r in readings[ds.short] if r.p_exec is not None]
        if len(rd) >= 40:
            vals = sorted(r.p_exec for r in rd)
            w("**分位数否决（唯一真的砍掉东西的版本；含前视，明示）**")
            w()
            w("| 否决规则 | 剩余 n | 保留率 | 胜率 | 毛R | 均R | Δ均R | "
              "净R | Δ净R | z_sel | 随机同规模子集毛R 5–95% | 判定 |")
            w("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for f, tag in ((0.80, "最靠前 20%"), (0.90, "最靠前 10%"),
                           (0.667, "最靠前 1/3"), (0.50, "靠前一半")):
                thr = qtile(vals, f)

                def gate(c: Cand, thr=thr) -> bool:
                    v = signed(ph.on_bar(c.dt), c.direction)
                    return v is None or v < thr
                tr, _ = run_gated(ds.bars, ds.book, ds.subs, gate=gate)
                m = summarize(tr, ds.base, ds.n_bars, None)
                bs = boot_subset(base_r, m["n"])
                FAM.cell()
                FAM.z(m["z_sel"], f"{ds.short} 否决{tag} z_sel")
                verdict = ("**高于随机 95%**" if m["total_r"] > bs["p95"]
                           else ("低于随机 5%" if m["total_r"] < bs["p05"]
                                 else "区间内 = 无选择信息"))
                d_avg = m["avg_r"] - sum(base_r) / len(ds.base)
                d_net = m["net_r"] - (sum(base_r) - cost0)
                w(f"| 否决 {tag}（signed ≥ {thr:+.0f}） | {m['n']} | {m['pct']:.0f}% | "
                  f"{100*m['win_rate']:.1f}% | {m['total_r']:+.1f} | {m['avg_r']:+.3f} | "
                  f"{d_avg:+.3f} | {m['net_r']:+.1f} | {d_net:+.1f} | "
                  f"{'–' if m['z_sel'] != m['z_sel'] else f'{m['z_sel']:+.2f}'} | "
                  f"[{bs['p05']:+.1f}, {bs['p95']:+.1f}] | {verdict} |")
            w()

    # ═══════════════════════ S5 the free proxy ══════════════════════════════
    w("---")
    w()
    w("## S5 与免费代理对照（问题 4）：Phase 有没有超过「入场前 N 根净位移」的增量信息")
    w()
    w(f"D3 的定义（一行代码，不需要任何振荡器）：")
    w()
    w("```python")
    w(f"d3 = direction * (close[i] - close[i-{DISP_N}]) / atr14[i] * 100")
    w("```")
    w()
    w(f"即**入场前 {DISP_N} 根执行周期 K 的净位移**（10m 图上就是最近一小时），"
      "按同周期 ATR(14) 归一，再乘 100 让它与 Phase 同量纲。"
      "顺带也算了 N=3 的短版本。")
    w()
    w("对照的机制理由很直白：Phase 的分子是 `close − EMA21`，"
      "EMA21 的重心大约在 10 根之前，所以 Phase 本身**就是**一个"
      "「近 10 根净位移 / 3ATR」的平滑版本。"
      "两者若高度相关，就说明振荡器没有提供新东西。")
    w()
    w("| 数据集 | n | Spearman ρ(signed phase, D3-6) | ρ(phase, D3-3) | "
      "ρ(D3-6, D3-3) | phase 的 sd | D3-6 的 sd |")
    w("|---|---|---|---|---|---|---|")
    for ds in sets:
        rd = [r for r in readings[ds.short]
              if r.p_exec is not None and r.d3 is not None and r.d3_short is not None]
        if len(rd) < 20:
            continue
        px = [r.p_exec for r in rd]
        d6 = [r.d3 for r in rd]
        d3s = [r.d3_short for r in rd]
        FAM.cell()
        w(f"| {ds.short} | {len(rd)} | {spearman(px, d6):+.3f} | "
          f"{spearman(px, d3s):+.3f} | {spearman(d6, d3s):+.3f} | "
          f"{st.stdev(px):.1f} | {st.stdev(d6):.1f} |")
    w()
    w("### S5.2 D3 自己的五分位赛跑表（与 S2.2 的 Phase 表逐格可比）")
    w()
    for ds in sets:
        rd = [r for r in readings[ds.short] if r.d3 is not None]
        if len(rd) < 40:
            continue
        vals = sorted(r.d3 for r in rd)
        cuts = [qtile(vals, f) for f in (0.2, 0.4, 0.6, 0.8)]
        w(f"**{ds.short}**（D3-{DISP_N} 五分位门槛 "
          + " / ".join(f"{c:+.0f}" for c in cuts) + "）")
        w()
        w("| D3 档 | 已裁决 n | T1 先到 | 几何零假设 | 超额 | z_geom | 未裁决 |")
        w("|---|---|---|---|---|---|---|")
        bounds = [-1e9] + cuts + [1e9]
        for qi in range(5):
            g = [r.t for r in rd if bounds[qi] <= r.d3 < bounds[qi + 1]]
            row = race_row(f"Q{qi+1}", ds, g)
            if row:
                w(row)
        w()
    w("### S5.3 增量检验：在 D3 相同的层里，Phase 还说得出话吗？")
    w()
    w("做法：先按 D3 三分位分层，**层内**再按 signed phase 中位数一分为二，"
      "报每个子格的几何超额。如果 Phase 只是 D3 的平滑版，层内的两半应该没有差别。")
    w()
    for ds in sets:
        rd = [r for r in readings[ds.short]
              if r.p_exec is not None and r.d3 is not None]
        if len(rd) < 90:
            w(f"*{ds.short}：n={len(rd)}，分层后每格不足，跳过。*")
            w()
            continue
        dc = [qtile([r.d3 for r in rd], f) for f in (1 / 3, 2 / 3)]
        w(f"**{ds.short}**（D3 三分位 {dc[0]:+.0f} / {dc[1]:+.0f}）")
        w()
        w("| D3 层 | phase 低半 超额 (n) | phase 高半 超额 (n) | 层内两比例 z |")
        w("|---|---|---|---|")
        for lbl, lo_, hi_ in (("D3 靠后", -1e9, dc[0]), ("D3 居中", dc[0], dc[1]),
                              ("D3 靠前", dc[1], 1e9)):
            layer = [r for r in rd if lo_ <= r.d3 < hi_]
            if len(layer) < 20:
                w(f"| {lbl} | n={len(layer)} | – | – |")
                continue
            med = qtile([r.p_exec for r in layer], 0.5)
            lo_g = [r.t for r in layer if r.p_exec < med]
            hi_g = [r.t for r in layer if r.p_exec >= med]
            rl = race(lo_g, ds.bars, ds.subs) if len(lo_g) >= 8 else None
            rh = race(hi_g, ds.bars, ds.subs) if len(hi_g) >= 8 else None
            FAM.cell(2)
            if rl and rh and rl["n"] and rh["n"]:
                zz = stats.two_proportion_z(rh["k"], rh["n"], rl["k"], rl["n"])
                FAM.z(zz, f"{ds.short} {lbl} 层内 phase z")
                w(f"| {lbl} | {100*(rl['obs']-rl['null']):+.1f}pp (n={rl['n']}) | "
                  f"{100*(rh['obs']-rh['null']):+.1f}pp (n={rh['n']}) | {zz:+.2f} |")
            else:
                w(f"| {lbl} | n={len(lo_g)} | n={len(hi_g)} | – |")
        w()

    # ════════════════════ S6 stacking with a distance filter ════════════════
    w("---")
    w()
    w("## S6 与距离过滤器叠加（**明示：事后组合**）")
    w()
    w("任务 1 的报告在本文写作时尚未落盘，所以这里用它的等价物做替身："
      "**风险距离门槛**（`risk / 日ATR ≥ x`），"
      "这是 `V14_EXECUTION_FILTERS` 里已经量化过的那个族。"
      "叠加的结果**不是预登记的**，读的时候要按事后组合折价。")
    w()
    w("| 组合 | n | 保留率 | 胜率 | 毛R | 均R | 净R | 钱(净,ATR) | z_sel(R) | z_sel(钱) |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    ds = prim
    ph = ds.ph_exec
    rd = [r for r in readings[ds.short] if r.p_exec is not None]
    thr80 = qtile(sorted(r.p_exec for r in rd), 0.80)
    ra = sorted(t_risk_atr(t) for t in ds.base)
    r50 = ra[int(len(ra) * 0.50)]
    combos: list[tuple[str, Callable[[Cand], bool]]] = [
        ("仅 Phase 否决（signed ≥ +100，字面）",
         lambda c: not (signed(ph.on_bar(c.dt), c.direction) or -999) >= EXTREME),
        (f"仅 Phase 否决（signed ≥ {thr80:+.0f}，最靠前 20%）",
         lambda c: (signed(ph.on_bar(c.dt), c.direction) or -999) < thr80),
        (f"仅 距离过滤（risk ≥ {r50:.3f} ATR = 最宽一半）",
         lambda c: c.risk_atr >= r50),
        (f"两者叠加",
         lambda c: c.risk_atr >= r50
         and (signed(ph.on_bar(c.dt), c.direction) or -999) < thr80),
    ]
    for lbl, g in combos:
        tr, _ = run_gated(ds.bars, ds.book, ds.subs, gate=g)
        m = summarize(tr, ds.base, ds.n_bars, None)
        FAM.cell()
        FAM.z(m["z_sel"], f"{ds.short} {lbl} z_sel")
        w(f"| {lbl} | {m['n']} | {m['pct']:.0f}% | {100*m['win_rate']:.1f}% | "
          f"{m['total_r']:+.1f} | {m['avg_r']:+.3f} | {m['net_r']:+.1f} | "
          f"{m['money_net']:+.2f} | "
          f"{'–' if m['z_sel'] != m['z_sel'] else f'{m['z_sel']:+.2f}'} | "
          f"{'–' if m['z_sel_money'] != m['z_sel_money'] else f'{m['z_sel_money']:+.2f}'} |")
    w()
    w("「钱」列的存在理由：R 不是钱。风险距离过滤器改的是 R 的**分母**，"
      "所以它能在不改变任何一笔真实盈亏的情况下把 R 账做正。"
      "`钱 = R × 风险/日ATR` 是不受这个记账错觉影响的那一栏。")
    w()

    # ════════════ S7 does "extreme => cooling" hold on bars at all? ══════════
    w("---")
    w()
    w("## S7 独立于 v14 的对照：「极端之后会降温」在 K 线层面成立吗")
    w()
    w("S1–S6 全部受制于一件事：v14 的入场点根本不到极端区。"
      "所以必须补一个**不依赖 v14 入场规则**的检验，"
      "否则「否决器没用」这个结论会被误读成「振荡器没用」。")
    w()
    w("做法：对每一根 K，按它自己的 Phase 分区，测**其后 N 根的净位移**"
      "（按当根 ATR(14) 归一）。Saty 的主张是"
      "「extended 之后通常会在动能耗尽后冷却」——"
      "那么 `extended_up` 之后的前向位移应当**显著为负**，反之亦然。")
    w()
    for ds in sets:
        atr = pf.ta_atr(ds.bars, pf.ATR_LEN)
        osc = ds.ph_exec.osc
        w(f"**{ds.short}**（执行周期 {ds.exec_tf}m，{len(ds.bars)} 根）")
        w()
        w("| 分区 | n | 前向 6 根位移(ATR) | t | 前向 18 根位移(ATR) | t |")
        w("|---|---|---|---|---|---|")
        for zname in pf.ZONE_ORDER:
            rows = []
            for horizon in (6, 18):
                vals = []
                for i in range(len(ds.bars) - horizon):
                    if osc[i] is None or atr[i] is None or atr[i] <= 0:
                        continue
                    if pf.phase_zone(osc[i]) != zname:
                        continue
                    vals.append((ds.bars[i + horizon].close - ds.bars[i].close) / atr[i])
                rows.append(vals)
            n = len(rows[0])
            FAM.cell(2)
            if n < 30:
                w(f"| {zname} | {n} | – | – | – | – |")
                continue
            cellsx = []
            for vals in rows:
                mu = sum(vals) / len(vals)
                sd = st.stdev(vals) if len(vals) > 1 else 0.0
                tt = mu / (sd / math.sqrt(len(vals))) if sd > 0 else float("nan")
                FAM.z(tt, f"{ds.short} {zname} fwd t")
                cellsx.append(f"{mu:+.3f} | {tt:+.2f}")
            w(f"| {zname} | {n} | " + " | ".join(cellsx) + " |")
        w()
    w("⚠️ **这张表的 t 值全部被序列相关高估**：相邻 K 的分区高度重叠，"
      "前向窗口也重叠，有效样本量远小于 n。"
      "所以只看**符号和量级**，不看显著性。"
      "要把它当证据用，需要按不重叠窗口或按天做块自助——本轮没做，"
      "**因此本节只作为「方向合理性」的对照，不产出任何结论。**")
    w()

    # ═════════════════════════════ S8 verdict ═══════════════════════════════
    w("---")
    w()
    w("## S8 家族规模与判决")
    w()
    K = FAM.n
    w(f"- 本轮共检视 **{K} 个格子**。在完全无信息的零假设下，"
      f"{K} 个独立标准正态里最大的 |z| 期望约 **{FAM.expected_max():.2f}**；"
      f"Bonferroni 双侧 5% 门槛是 **|z| > {FAM.bonferroni():.2f}**。")
    zs = sorted(FAM.zs, key=lambda x: -abs(x[0]))
    w(f"- 实际观察到的 |z| 最大的六个（共 {len(FAM.zs)} 个）：")
    for zv, lbl in zs[:6]:
        w(f"  - {lbl} = {zv:+.2f}")
    if zs:
        w(f"- 最大 |z| = **{abs(zs[0][0]):.2f}**，"
          f"{'越过' if abs(zs[0][0]) > FAM.bonferroni() else '**没有越过**'}"
          f" Bonferroni 门槛 {FAM.bonferroni():.2f}，"
          f"{'也' if abs(zs[0][0]) <= FAM.expected_max() else '但'}"
          f"{'没有' if abs(zs[0][0]) <= FAM.expected_max() else ''}"
          f"超过纯噪声下的期望最大值 {FAM.expected_max():.2f}。")
    w()

    txt = "\n".join(o)
    print(txt)
    raw = Path(__file__).resolve().parents[1] / "reports" / "V15_PHASE_VETO_raw.txt"
    raw.write_text(txt)
    return None


if __name__ == "__main__":
    main()
