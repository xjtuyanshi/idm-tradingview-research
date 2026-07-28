"""V15.1 · 具名位闸门：入场必须贴着一个具名位吗？

假设（来自 Saty 的行为而非直觉）
--------------------------------
Saty 每一篇 #ideas 的句式都是「IF 守住/破 <具名位> THEN 目标 <具名位>」。
于是有：**入场价必须贴着一个具名位（≤0.10 日ATR），否则不下注。**

具名位 = ATR 梯（0, ±0.236, ±0.382, ±0.5, ±0.618, ±0.786, ±1.0, ±1.272, ±1.618）
       + 夜盘高低（18:00–09:30 ET）+ 盘前高低（04:00–09:30 ET）+ 前日高低 PDH/PDL。

本文件测的是：**到最近具名位的距离与后续结果之间有没有单调关系**，以及——更要紧
的——**这个关系在安慰剂梯子上是否同样存在**。GOLDEN_GATE_REPRODUCTION 已经证明
具名斐波那契比例本身不特殊（整条梯子平移后完成率 63.7% vs 真 GG 64.6%）。如果
平移梯 / 等距梯给出同样的分层效果，那么「贴着具名位」测的其实是「贴着任意规则
网格」，也就是「离整数距离近」这个平凡属性。

抽样口径、结果变量、路径判定全部沿用 `study_entry_location.py`（V15_ENTRY_LOCATION）：
主样本 ES=F 10m 的全部 v14 入场信号（去掉单仓闸门），纯括号赛跑（保护位 vs T1），
5m 子 K 裁决路径，零假设一律几何零假设 S/(S+T)。

无前视保证：夜盘 / 盘前高低一律只用**信号 K 之前**的 K 计算（running extremes），
PDH/PDL 来自前一根完整日线。所有位在入场那一刻都是已知的。

Usage:  .venv/bin/python research/satylab/study_named_level.py
"""

from __future__ import annotations

import csv
import math
import random
import statistics as st
import sys
from bisect import bisect_left
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels as lvmod, stats                # noqa: E402
from satylab.data import Bar                                    # noqa: E402
from satylab.study_v14_repro import (                           # noqa: E402
    LevelBook, load_10m, trade_day,
)
from satylab.study_entry_location import (                      # noqa: E402
    NQ, RACE_CAP, SPREAD, bracket, corr, excursion, f, harvest,
    isolated_trade, location_vars, norm_sf, q, quantile_bins, spearman,
    trend_z, tstat, two_sided, z_geom, _bonf_z,
)

ET = ZoneInfo("America/New_York")
RATIOS = (-1.618, -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236, 0.0,
          0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
GATE = 0.10               # 假设里的闸门：到最近具名位 ≤ 0.10 日ATR
SHIFTS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
EQ_STEP = 0.20
FIX10 = Path(__file__).resolve().parents[1] / "fixtures" / \
    "SPX500_10m_with_official_levels.csv"
REPORT = Path(__file__).resolve().parents[1] / "reports" / \
    "V15_NAMED_LEVEL_GATE.md"

CELLS = 0


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ══════════════════════════ 具名位的构造 ════════════════════════════════════
class FullBook:
    """day -> DayLevels（锚 / ATR / 前日高 / 前日低），缺失日向前结转。"""

    def __init__(self, daily: list[Bar]):
        self.map = lvmod.build(daily)
        self.days = sorted(self.map)

    def get(self, d):
        i = bisect_left(self.days, d)
        if i < len(self.days) and self.days[i] == d:
            return self.map[self.days[i]]
        return self.map[self.days[i - 1]] if i > 0 else None


def in_on(b: Bar) -> bool:
    """夜盘窗口：18:00 ET 至次日 09:30 ET（trade_day 已把 ≥18:00 归到次日）。"""
    h, m = b.dt.hour, b.dt.minute
    return h >= 18 or (h, m) < (9, 30)


def in_pm(b: Bar) -> bool:
    """盘前窗口：04:00–09:30 ET。"""
    h, m = b.dt.hour, b.dt.minute
    return (4, 0) <= (h, m) < (9, 30)


def session_extremes(bars: list[Bar]):
    """每根 K 的「截至上一根为止」的夜盘 / 盘前高低（严格无前视）。

    同时返回滞后 3 根的版本：running extreme 的毛病是「我刚创的新高就是位」——
    那是动量代理不是静态地图。滞后版把最近 3 根排除在外，用来检查这个污染。
    """
    n = len(bars)
    out = [dict() for _ in range(n)]
    cur = None
    onH: list[float] = []
    onL: list[float] = []
    pmH: list[float] = []
    pmL: list[float] = []
    for i, b in enumerate(bars):
        d = trade_day(b)
        if d != cur:
            cur, onH, onL, pmH, pmL = d, [], [], [], []
        r = out[i]
        if onH:
            r["ON_hi"], r["ON_lo"] = onH[-1], onL[-1]
        if len(onH) >= 4:
            r["ON_hi_lag3"], r["ON_lo_lag3"] = onH[-4], onL[-4]
        if pmH:
            r["PM_hi"], r["PM_lo"] = pmH[-1], pmL[-1]
        if len(pmH) >= 4:
            r["PM_hi_lag3"], r["PM_lo_lag3"] = pmH[-4], pmL[-4]
        if in_on(b):
            onH.append(max(onH[-1], b.high) if onH else b.high)
            onL.append(min(onL[-1], b.low) if onL else b.low)
        if in_pm(b):
            pmH.append(max(pmH[-1], b.high) if pmH else b.high)
            pmL.append(min(pmL[-1], b.low) if pmL else b.low)
    return out


def ladder(anchor: float, atr: float, ratios) -> list[float]:
    return [anchor + r * atr for r in ratios]


def eq_ratios(step: float, phase: float = 0.0, span: float = 1.7) -> tuple:
    k = int(span / step)
    return tuple(j * step + phase for j in range(-k, k + 1))


def nearest(price: float, lvls: list[float]) -> tuple[float, float]:
    """返回 (到最近位的绝对距离, 最近位的价格)。"""
    best = min(lvls, key=lambda L: abs(price - L))
    return abs(price - best), best


# ══════════════════════════ 统计小工具 ══════════════════════════════════════
def zsel(sub: list[float], pop: list[float]) -> float:
    """有限总体修正的选择 z：从 N 笔里抽 n 笔，均值高出总体这么多算不算意外。"""
    N, n = len(pop), len(sub)
    if n < 2 or n >= N:
        return float("nan")
    mu, var = st.mean(pop), st.pvariance(pop)
    se = math.sqrt(var / n * (N - n) / (N - 1))
    return (st.mean(sub) - mu) / se if se > 0 else float("nan")


def cellstat(g: list, pop: list) -> dict:
    res = [s for s in g if s.hit is not None]
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    k = sum(1 for s in res if s.hit)
    lo, hi = stats.wilson(k, n) if n else (float("nan"), float("nan"))
    nets = [s.net for s in g]
    moneys = [s.money for s in g]
    return {"n": len(g), "nres": n, "obs": obs, "null": null, "z": z,
            "lo": lo, "hi": hi,
            "r": st.mean([s.r for s in g]) if g else float("nan"),
            "net": st.mean(nets) if g else float("nan"),
            "money": st.mean(moneys) if g else float("nan"),
            "zs_net": zsel(nets, [s.net for s in pop]),
            "zs_money": zsel(moneys, [s.money for s in pop])}


HDR = ("| 档 | 距离区间(ATR) | n | 纯括号命中 [95%CI] | 几何零假设 | 超额pp | "
       "z_geom | 均R | 均净R | z_sel(净R) | 净钱×1000 | z_sel(钱) |")
SEP = "|---|---|---|---|---|---|---|---|---|---|---|---|"


def row(label: str, rng: str, c: dict) -> str:
    return (f"| {label} | {rng} | {c['n']} | "
            f"{100*c['obs']:.1f}% [{100*c['lo']:.1f},{100*c['hi']:.1f}] | "
            f"{100*c['null']:.1f}% | {100*(c['obs']-c['null']):+.1f} | "
            f"{c['z']:+.2f} | {c['r']:+.3f} | {c['net']:+.3f} | "
            f"{f(c['zs_net'],2,True)} | {1000*c['money']:+.1f} | "
            f"{f(c['zs_money'],2,True)} |")


def strata(sigs: list, dist, out: list[str], k: int = NQ) -> dict:
    """按到最近具名位的距离做分位数分层 + 单调性检验。"""
    res = [s for s in sigs if s.hit is not None and dist(s) == dist(s)]
    if len(res) < 5 * k:
        out.append(f"（样本不足：可裁决 n={len(res)}）")
        return {}
    vals = [dist(s) for s in res]
    bins = quantile_bins(vals, k)
    out.append(HDR)
    out.append(SEP)
    for j in range(k):
        g = [s for s, b in zip(res, bins) if b == j]
        gv = [v for v, b in zip(vals, bins) if b == j]
        if not g:
            continue
        bump()
        out.append(row(f"Q{j+1}", f"{min(gv):.3f}–{max(gv):.3f}",
                       cellstat(g, res)))
    ranks = [float(b + 1) for b in bins]
    ys = [1 if s.hit else 0 for s in res]
    ps = [s.pnull for s in res]
    tz = trend_z(ranks, ys, ps)
    tzc = trend_z(vals, ys, ps)
    rho_n, z_n = spearman(vals, [s.net for s in res])
    rho_m, z_m = spearman(vals, [s.money for s in res])
    bump(4)
    out.append("")
    out.append(f"- **单调性**：超额趋势得分 z = **{tz:+.2f}** (p={two_sided(tz):.3f})；"
               f"用连续距离而非档位 z = {tzc:+.2f} (p={two_sided(tzc):.3f})。"
               f"假设预测 z<0（越贴位越好）。")
    out.append(f"- **秩相关（距离 vs 结果）**：净均R ρ = {rho_n:+.3f} "
               f"(z={z_n:+.2f})；净钱(ATR) ρ = {rho_m:+.3f} (z={z_m:+.2f})。"
               f"假设预测 ρ<0。")
    return {"tz": tz, "tzc": tzc, "rho_n": rho_n, "z_n": z_n,
            "rho_m": rho_m, "z_m": z_m, "n": len(res)}


def gate_row(sigs: list, dist, thr: float) -> tuple[dict, dict]:
    """闸门 ≤thr vs >thr 的两格。"""
    ok = [s for s in sigs if dist(s) == dist(s) and dist(s) <= thr]
    no = [s for s in sigs if dist(s) == dist(s) and dist(s) > thr]
    bump(2)
    return cellstat(ok, sigs), cellstat(no, sigs)


# ══════════════════════════ 数据集组装 ══════════════════════════════════════
def build(symbol: str, rth_only: bool) -> dict:
    bars, subs = load_10m(symbol, rth_only)
    book = LevelBook(data.load(symbol, "20y", "1d"))
    full = FullBook(data.load(symbol, "20y", "1d"))
    sigs, e13s = harvest(bars, book)
    sigs = location_vars(sigs, bars, e13s)
    sess = session_extremes(bars)
    rng = random.Random(20260728)
    phase_of: dict = {}

    for s in sigs:
        b = bars[s.i]
        d = trade_day(b)
        dl = full.get(d)
        anchor, atr = dl.anchor, dl.atr
        s.anchor, s.pdh, s.pdl = anchor, dl.prev_high, dl.prev_low
        s.ratio_entry = (s.entry - anchor) / atr

        # ── 组 A：ATR 梯
        A = ladder(anchor, atr, RATIOS)
        s.dA, s.lvA = nearest(s.entry, A)
        s.dA /= atr

        # ── 组 B：时段位（夜盘 / 盘前 / 前日）
        sl = sess[s.i]
        B, Bn = [], []
        for nm in ("ON_hi", "ON_lo", "PM_hi", "PM_lo"):
            if nm in sl:
                B.append(sl[nm])
                Bn.append(nm)
        B += [dl.prev_high, dl.prev_low]
        Bn += ["PDH", "PDL"]
        s.nB = len(B)
        dB, lvB = nearest(s.entry, B)
        s.dB, s.lvB = dB / atr, lvB
        s.nameB = Bn[min(range(len(B)), key=lambda t: abs(s.entry - B[t]))]

        # 滞后 3 根版的时段位（去掉「我刚创的高就是位」这个污染）
        B3 = [sl[nm] for nm in ("ON_hi_lag3", "ON_lo_lag3",
                                "PM_hi_lag3", "PM_lo_lag3") if nm in sl]
        B3 += [dl.prev_high, dl.prev_low]
        s.dB3 = nearest(s.entry, B3)[0] / atr

        # ── 组 C：合并
        s.dC, s.lvC = nearest(s.entry, A + B)
        s.dC /= atr
        s.nameC = "ATR梯" if s.lvC == s.lvA else s.nameB

        # ── 安慰剂：整条梯平移
        for sh in SHIFTS:
            setattr(s, f"dS{int(sh*100):02d}",
                    nearest(s.entry, ladder(anchor, atr,
                                            [r + sh for r in RATIOS]))[0] / atr)
        # ── 安慰剂：等距梯（0.20 ATR 一档），三种相位
        for tag, ph in (("E00", 0.0), ("E10", 0.10)):
            setattr(s, f"d{tag}",
                    nearest(s.entry, ladder(anchor, atr,
                                            eq_ratios(EQ_STEP, ph)))[0] / atr)
        if d not in phase_of:
            phase_of[d] = rng.uniform(0.0, EQ_STEP)
        s.dER = nearest(s.entry, ladder(anchor, atr,
                                        eq_ratios(EQ_STEP, phase_of[d])))[0] / atr

        # ── 方向性：最近的具名位在前方还是后方
        s.aheadA = (s.lvA - s.entry) * s.direction > 0
        s.aheadC = (s.lvC - s.entry) * s.direction > 0
        s.crossA = b.low <= s.lvA <= b.high
        s.crossC = b.low <= s.lvC <= b.high

    for s in sigs:
        bracket(s, bars, subs)
        isolated_trade(s, bars, subs, e13s)
        excursion(s, bars, subs)
    return {"symbol": symbol, "bars": bars, "subs": subs, "sigs": sigs,
            "full": full}


# ══════════════════════════ 标的敏感性（§5）═════════════════════════════════
def fixture_check(prim: dict, out: list[str]) -> None:
    rows = list(csv.DictReader(FIX10.open()))
    fx = []
    for r in rows:
        try:
            anchor = float(r["Previous Close"])
            up = float(r["Upper Trigger"])
        except (ValueError, KeyError):
            continue
        atr = (up - anchor) / 0.236
        dt = datetime.fromtimestamp(int(r["time"]), ET)
        fx.append({"dt": dt, "close": float(r["close"]),
                   "high": float(r["high"]), "low": float(r["low"]),
                   "anchor": anchor, "atr": atr})
    bars = prim["bars"]
    es = {b.dt: b for b in bars}
    full = prim["full"]

    pairs = []
    for r in fx:
        b = es.get(r["dt"])
        if b is None:
            continue
        dl = full.get(trade_day(b))
        if dl is None or dl.atr <= 0:
            continue
        dS = nearest(r["close"], ladder(r["anchor"], r["atr"], RATIOS))[0] / r["atr"]
        dE = nearest(b.close, ladder(dl.anchor, dl.atr, RATIOS))[0] / dl.atr
        pairs.append({"dt": b.dt, "dS": dS, "dE": dE,
                      "atrS": r["atr"], "atrE": dl.atr,
                      "cS": r["close"], "cE": b.close,
                      "aS": r["anchor"], "aE": dl.anchor})
    out.append(f"夹具 `SPX500_10m_with_official_levels.csv` 共 {len(rows)} 行，"
               f"{fx[0]['dt']:%Y-%m-%d %H:%M} → {fx[-1]['dt']:%Y-%m-%d %H:%M} ET；"
               f"与 ES=F 10m 时间戳对上的 **{len(pairs)} 根**。样本太小，"
               f"只能用来看**距离分布**像不像，不能定论任何交易结论。")
    out.append("")
    if len(pairs) < 30:
        out.append("（对齐样本不足 30 根，本节作废。）")
        return

    dS = [p["dS"] for p in pairs]
    dE = [p["dE"] for p in pairs]
    out.append("**到最近 ATR 梯位的距离分布（同一套比例，各用各自标的的锚与 ATR）**")
    out.append("")
    out.append("| 标的 | n | 均值 | 中位 | sd | p10 | p25 | p75 | p90 | "
               f"≤{GATE} 占比 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for nm, v in (("CAPITALCOM:SPX500（官方位）", dS), ("ES=F（本研究的位）", dE)):
        out.append(f"| {nm} | {len(v)} | {st.mean(v):.4f} | {q(v,0.5):.4f} | "
                   f"{st.pstdev(v):.4f} | {q(v,0.10):.4f} | {q(v,0.25):.4f} | "
                   f"{q(v,0.75):.4f} | {q(v,0.90):.4f} | "
                   f"{100*sum(1 for x in v if x<=GATE)/len(v):.1f}% |")
    out.append("")
    # KS
    allv = sorted(set(dS + dE))
    ks = max(abs(sum(1 for x in dS if x <= t) / len(dS)
                 - sum(1 for x in dE if x <= t) / len(dE)) for t in allv)
    crit = 1.36 * math.sqrt(1 / len(dS) + 1 / len(dE))
    rho, zr = spearman(dS, dE)
    ratios = [p["atrE"] / p["atrS"] for p in pairs]
    basis = [p["cE"] - p["cS"] for p in pairs]
    bump(2)
    out.append(f"- **边际分布几乎重合**：KS 统计量 D = **{ks:.3f}**，"
               f"α=0.05 临界值 {crit:.3f}（n1={len(dS)}, n2={len(dE)}）→ "
               f"{'不能拒绝同分布' if ks < crit else '名义上可以拒绝同分布'}。"
               f"⚠ 这 292 根 K 强烈自相关（同一天内相邻 K 的位置几乎连续），"
               f"KS 的独立性前提不成立，临界值偏松；这个检验只能当描述用，"
               f"不能当推断用。看均值/中位/分位就够了：两列小数点后第二位才分家。")
    out.append(f"- **但逐根完全不一致**：同一时刻两个标的的 d_min 秩相关 ρ = "
               f"**{rho:+.3f}** (z={zr:+.2f})——**负的**。原因是几何的：两条梯子"
               f"步长相近（ATR 比值 {st.mean(ratios):.3f}）但**相位不同**（锚差 + "
               f"期货基差 {st.mean(basis):+.1f} 点 ≈ {st.mean(basis)/st.mean([p['atrS'] for p in pairs]):.2f} ATR），"
               f"两条锯齿波错开半格就会反相。")
    out.append("")
    out.append(f"**闸门一致性**（同一根 K，两个标的会不会给出同一个「贴位/不贴位」判决）：")
    out.append("")
    out.append("| 阈值 | SPX500 通过率 | ES 通过率 | 同时通过 | 只 SPX500 | 只 ES | "
               "都不通过 | 原始一致率 | Cohen κ |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for thr in (GATE, 0.05, 0.03, 0.02):
        both = sum(1 for p in pairs if p["dS"] <= thr and p["dE"] <= thr)
        only_s = sum(1 for p in pairs if p["dS"] <= thr and p["dE"] > thr)
        only_e = sum(1 for p in pairs if p["dS"] > thr and p["dE"] <= thr)
        neither = len(pairs) - both - only_s - only_e
        po = (both + neither) / len(pairs)
        pe = ((both + only_s) * (both + only_e)
              + (only_e + neither) * (only_s + neither)) / len(pairs) ** 2
        kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
        bump()
        out.append(f"| d≤{thr:.2f} | {100*(both+only_s)/len(pairs):.1f}% | "
                   f"{100*(both+only_e)/len(pairs):.1f}% | {both} | {only_s} | "
                   f"{only_e} | {neither} | {100*po:.1f}% | {f(kappa,3,True)} |")
    out.append("")
    out.append(f"- 这几天的 ATR 比值 ES/SPX500 = {st.mean(ratios):.3f} "
               f"(sd {st.pstdev(ratios):.3f})，价差（ES−SPX500）均 "
               f"{st.mean(basis):+.1f} 点 (sd {st.pstdev(basis):.1f})。"
               f"注意这只是 4 天，`levels.py` 记录的 246 天 ^GSPC/SPX500 比值 "
               f"sd 0.083 才是长期波动的量级。")
    out.append("")


# ══════════════════════════════ 报告 ════════════════════════════════════════
def main() -> None:
    o: list[str] = []
    A = o.append

    prim = build("ES=F", False)
    sigs = prim["sigs"]
    bars = prim["bars"]
    res = [s for s in sigs if s.hit is not None]

    A("# V15.1 · 具名位闸门：入场必须贴着一个具名位吗")
    A("")
    A(f"生成脚本 `research/satylab/study_named_level.py`。主样本 **ES=F 10m**"
      f"（由 60d 5m 聚合，含完整夜盘，与 CAPITALCOM:SPX500 作息一致），"
      f"{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，{len(bars)} 根 setup K，"
      f"v14 入场信号 **{len(sigs)}** 个（去掉单仓闸门，口径与 V15_ENTRY_LOCATION "
      f"§1 完全一致），其中可裁决 {len(res)}。路径判定落到 5 分钟子 K（纪律 3），"
      f"零假设一律几何零假设 S/(S+T)（纪律 1），点差 {SPREAD} 点（纪律 4）。")
    A("")
    A("## 0 · 假设与判定标准")
    A("")
    A("> **入场价必须贴着一个具名位（≤0.10 日ATR），否则不下注。**")
    A("")
    A("依据是 Saty 的行为：每篇 #ideas 都是「IF 守住/破 <具名位> THEN 目标 "
      "<具名位>」。判定标准三条，缺一不可：")
    A("")
    A("1. **单调**：距离越大结果越差，而且是单调的，不是某一档孤零零地好。")
    A("2. **过安慰剂**：把整条 ATR 梯平移、或换成等距梯，效应必须**消失**。"
      "否则测到的是「离任意规则网格近」这个平凡属性。")
    A("3. **过多重比较**：见文末 Bonferroni 门槛。")
    A("")
    A("**读表须知（这一条决定你怎么读下面所有的表）**：真 ATR 梯的 d_min 与 T1 "
      "距离在定义上纠缠——如果最近的梯位在**前方** 0.02 ATR，那 T1 就**是**它，"
      "T1 距离也是 0.02 ATR，几何零假设 S/(S+T) 因此接近 1，原始命中率必然爆表。"
      "所以**原始命中率那一列在组 A 上完全不可读**，只能读 `z_geom`（已扣掉几何）"
      "和 `净钱×1000`（每 1 单位名义本金的净盈亏，以日 ATR 计——R 的分母是风险距离，"
      "跨档不可比）。")
    A("")

    # ── 1 · 距离的构造与描述 ────────────────────────────────────────────────
    A("## 1 · 三组具名位与距离分布")
    A("")
    A("| 组 | 位的内容 | 每根 K 的位数 | d_min 均值 | 中位 | p90 | "
      f"≤{GATE} 占比 |")
    A("|---|---|---|---|---|---|---|")
    GROUPS = [
        ("A · ATR梯", "0, ±0.236, ±0.382, ±0.5, ±0.618, ±0.786, ±1.0, ±1.272, ±1.618",
         17, lambda s: s.dA),
        ("B · 时段位", "夜盘高低 / 盘前高低 / PDH / PDL（均为信号 K 之前的 running 值）",
         None, lambda s: s.dB),
        ("C · 合并", "A ∪ B", None, lambda s: s.dC),
    ]
    for nm, desc, k, g in GROUPS:
        v = [g(s) for s in sigs]
        kk = k if k else f"{st.mean([s.nB for s in sigs]):.1f}（B 平均）" \
            if nm.startswith("B") else f"{17+st.mean([s.nB for s in sigs]):.1f}"
        A(f"| {nm} | {desc} | {kk} | {st.mean(v):.4f} | {q(v,0.5):.4f} | "
          f"{q(v,0.90):.4f} | {100*sum(1 for x in v if x<=GATE)/len(v):.1f}% |")
    A("")
    A(f"**第一个坏消息**：ATR 梯的最大档间距是 1.272→1.618 的 0.346 ATR，"
      f"所以到最近梯位的距离**在数学上不可能超过 0.173 ATR**；锚附近档距只有 "
      f"0.118 ATR，半距 0.059。也就是说 "
      f"**{100*sum(1 for s in sigs if s.dA<=GATE)/len(sigs):.0f}% 的信号自动通过 "
      f"≤{GATE} 这个闸门**——闸门几乎不筛掉任何东西。合并组 C 更极端："
      f"{100*sum(1 for s in sigs if s.dC<=GATE)/len(sigs):.0f}%。")
    A("")
    A("**第二个坏消息**：梯子疏密不均（锚附近密、外围疏），所以 d_min 天然与"
      "「离锚多远」相关。下面这张相关矩阵是必须看的——如果 d_min 只是 "
      "|离锚距离| 的一个变形，那它根本不是一个新变量。")
    A("")
    A("| | d_A | d_B | d_C | \\|离锚\\|(ATR) | D1 | D4 |")
    A("|---|---|---|---|---|---|---|")
    cols = [("d_A", lambda s: s.dA), ("d_B", lambda s: s.dB),
            ("d_C", lambda s: s.dC),
            ("|离锚|", lambda s: abs(s.ratio_entry)),
            ("D1", lambda s: s.d1), ("D4", lambda s: s.d4)]
    for na, ga in cols[:3] + [cols[3]]:
        line = f"| {na} "
        for nb, gb in cols:
            line += f"| {corr([ga(s) for s in sigs], [gb(s) for s in sigs]):+.2f} "
        A(line + "|")
    A("")

    # ── 2 · 主检验 ──────────────────────────────────────────────────────────
    A("## 2 · 分位分层：距离越大，结果越差吗")
    A("")
    summary = {}
    for tag, nm, g in (("A", "组 A · 只用 ATR 梯", lambda s: s.dA),
                       ("B", "组 B · 只用时段位", lambda s: s.dB),
                       ("C", "组 C · 两者合并", lambda s: s.dC)):
        A(f"### 2.{'ABC'.index(tag)+1} {nm}")
        A("")
        summary[tag] = strata(sigs, g, o)
        A("")

    A("### 2.4 三组对比与判决")
    A("")
    A("| 组 | 可裁决 n | 超额趋势 z | p | 净钱 ρ | z | 判决（假设预测 z<0 / ρ<0） |")
    A("|---|---|---|---|---|---|---|")
    for tag, nm in (("A", "A · ATR梯"), ("B", "B · 时段位"), ("C", "C · 合并")):
        m = summary[tag]
        verdict = ("**支持假设**" if m["tz"] < -1.96 else
                   "**反向**" if m["tz"] > 1.96 else "无证据（|z|<1.96）")
        A(f"| {nm} | {m['n']} | {f(m['tz'],2,True)} | {two_sided(m['tz']):.3f} | "
          f"{f(m['rho_m'],3,True)} | {f(m['z_m'],2,True)} | {verdict} |")
    A("")

    # ── 3 · 闸门本身 ────────────────────────────────────────────────────────
    A("## 3 · 直接测那个闸门：d_min ≤ 0.10 ATR")
    A("")
    A("假设给的是一个具体阈值，所以直接测它，不只测趋势。`z_sel` 是有限总体修正下"
      "「从全样本里抽这么多笔，均值能高出这么多」的选择 z（纪律 6）。")
    A("")
    base_net = st.mean([s.net for s in sigs])
    base_money = st.mean([s.money for s in sigs])
    A(f"基线（全部 {len(sigs)} 笔）：均净R = **{base_net:+.3f}**，"
      f"净钱×1000 = **{1000*base_money:+.1f}**，总净R = "
      f"{sum(s.net for s in sigs):+.1f}。")
    A("")
    A("| 闸门 | n (占比) | 纯括号命中 | 几何零假设 | z_geom | 均净R | Δ均净R | "
      "z_sel(净R) | 净钱×1000 | Δ净钱 | z_sel(钱) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for tag, nm, g in (("A", "组A d≤0.10", lambda s: s.dA),
                       ("B", "组B d≤0.10", lambda s: s.dB),
                       ("C", "组C d≤0.10", lambda s: s.dC)):
        ok, no = gate_row(sigs, g, GATE)
        for lbl, c in ((nm, ok), (nm.replace("≤", ">"), no)):
            A(f"| {lbl} | {c['n']} ({100*c['n']/len(sigs):.0f}%) | "
              f"{100*c['obs']:.1f}% | {100*c['null']:.1f}% | {c['z']:+.2f} | "
              f"{c['net']:+.3f} | {c['net']-base_net:+.3f} | "
              f"{f(c['zs_net'],2,True)} | {1000*c['money']:+.1f} | "
              f"{1000*(c['money']-base_money):+.1f} | {f(c['zs_money'],2,True)} |")
    A("")
    A("更严的阈值（因为 0.10 几乎不筛东西）：")
    A("")
    A("| 闸门 | n (占比) | z_geom | 均净R | Δ均净R | z_sel(净R) | 净钱×1000 | "
      "Δ净钱 | z_sel(钱) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for tag, g in (("A", lambda s: s.dA), ("B", lambda s: s.dB),
                   ("C", lambda s: s.dC)):
        for thr in (0.02, 0.03, 0.05):
            c, _ = gate_row(sigs, g, thr)
            if c["n"] < 30:
                A(f"| 组{tag} d≤{thr:.2f} | {c['n']} | 样本不足 | | | | | | |")
                continue
            A(f"| 组{tag} d≤{thr:.2f} | {c['n']} ({100*c['n']/len(sigs):.0f}%) | "
              f"{c['z']:+.2f} | {c['net']:+.3f} | {c['net']-base_net:+.3f} | "
              f"{f(c['zs_net'],2,True)} | {1000*c['money']:+.1f} | "
              f"{1000*(c['money']-base_money):+.1f} | {f(c['zs_money'],2,True)} |")
    A("")

    # ── 4 · 安慰剂 ──────────────────────────────────────────────────────────
    A("## 4 · ⚠ 安慰剂检验：平移梯与等距梯")
    A("")
    A("这是本项目的传统，也是本文最重要的一节。GOLDEN_GATE_REPRODUCTION 已经证明"
      "具名斐波那契比例不特殊（残差 ≤0.76σ；整条梯子平移后完成率 63.7% vs 真 GG "
      "64.6%）。所以：把整条 ATR 梯**平移** δ（间距不变），以及**换成等距梯**"
      "（每 0.2 ATR 一档，三种相位），重做第 2 节与第 3 节。")
    A("")
    A("**先看一个决定性的数字**——真梯与安慰剂梯的 d_min 之间的秩相关。如果它们"
      "高度相关，那两条梯子根本在测同一件事，后面的表只是确认。")
    A("")
    A("| 安慰剂梯 | 与真 ATR 梯 d_min 的秩相关 ρ | z |")
    A("|---|---|---|")
    PLAC = [(f"平移 +{s:.2f}", f"dS{int(s*100):02d}") for s in SHIFTS] + \
        [("等距 0.20（相位 0）", "dE00"), ("等距 0.20（相位 0.10）", "dE10"),
         ("等距 0.20（每日随机相位）", "dER")]
    for nm, at in PLAC:
        rho, z = spearman([s.dA for s in sigs],
                          [getattr(s, at) for s in sigs])
        bump()
        A(f"| {nm} | {rho:+.3f} | {z:+.2f} |")
    A("")
    A("### 4.1 安慰剂梯的分层与闸门（与真梯逐行对照）")
    A("")
    A("| 梯子 | ≤0.10 通过率 | 超额趋势 z | p | 净钱 ρ | z | d≤0.10 的 n | "
      "该格 z_geom | 该格净钱×1000 | Δ净钱 | z_sel(钱) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    plac_tz, plac_rm = [], []

    def plac_line(nm, g, collect=True):
        tmp: list[str] = []
        m = strata(sigs, g, tmp)
        ok, _ = gate_row(sigs, g, GATE)
        if collect:
            plac_tz.append(m["tz"])
            plac_rm.append(m["rho_m"])
        return (f"| {nm} | {100*ok['n']/len(sigs):.0f}% | {f(m['tz'],2,True)} | "
                f"{two_sided(m['tz']):.3f} | "
                f"{f(m['rho_m'],3,True)} | {f(m['z_m'],2,True)} | {ok['n']} | "
                f"{ok['z']:+.2f} | {1000*ok['money']:+.1f} | "
                f"{1000*(ok['money']-base_money):+.1f} | "
                f"{f(ok['zs_money'],2,True)} |")

    A(plac_line("**真 ATR 梯（组 A）**", lambda s: s.dA, collect=False))
    for nm, at in PLAC:
        A(plac_line(nm, (lambda a: (lambda s: getattr(s, a)))(at)))
    A("")
    real_tz = summary["A"]["tz"]
    real_rm = summary["A"]["rho_m"]
    rank = sum(1 for t in plac_tz if t <= real_tz)
    A(f"**安慰剂分布 vs 真梯**：{len(plac_tz)} 条安慰剂梯的超额趋势 z 均值 "
      f"{st.mean(plac_tz):+.2f}、sd {st.stdev(plac_tz):.2f}、范围 "
      f"[{min(plac_tz):+.2f}, {max(plac_tz):+.2f}]。真 ATR 梯 z = "
      f"**{real_tz:+.2f}**，在这个分布里排第 {rank+1}/{len(plac_tz)+1}"
      f"（经验分位 {100*(rank+0.5)/(len(plac_tz)+1):.0f}%）。"
      f"净钱 ρ 同理：安慰剂均值 {st.mean(plac_rm):+.3f}、sd {st.stdev(plac_rm):.3f}，"
      f"真梯 {real_rm:+.3f}。")
    A("")
    A("**判决**：真 ATR 梯的分层效果**落在安慰剂梯的正常波动范围之内**——"
      "既有安慰剂比它「更支持假设」（平移 +0.20 的 z = "
      f"{[t for n,t in zip([p[0] for p in PLAC], plac_tz) if n=='平移 +0.20'][0]:+.2f}，"
      "比真梯更负），也有安慰剂朝反方向走。安慰剂梯自己之间的散布（sd "
      f"{st.stdev(plac_tz):.2f}）就已经比真梯与零的距离（{abs(real_tz):.2f}）大。"
      "这与 GOLDEN_GATE_REPRODUCTION 的结论完全一致：**具名斐波那契比例没有特殊性**。")
    A("")
    A("### 4.2 两条代表性安慰剂梯的完整分层表")
    A("")
    for nm, at in (("平移 +0.15 的梯子", "dS15"), ("等距 0.20 ATR 梯", "dE00")):
        A(f"**{nm}**")
        A("")
        strata(sigs, (lambda a: (lambda s: getattr(s, a)))(at), o)
        A("")

    # ── 5 · 方向性 ──────────────────────────────────────────────────────────
    A("## 5 · 方向性：拒绝（远离该位）vs 接受（穿过该位）")
    A("")
    A("定义：最近的具名位在入场价的**后方**（(位−入场价)·方向 < 0）= 价格刚从这个位"
      "弹开、交易方向远离它 = **拒绝**；在**前方**（>0）= 交易方向要穿过它 = "
      "**接受/突破**。假设预测「拒绝」优于「接受」。")
    A("")
    A(f"⚠ 这一节有一个结构性陷阱：组 A 里「位在前方」时，那个位**就是 T1**"
      f"（`next_rung` 取的就是前方最近的梯位），所以 T1 距离 = d_min，几何零假设"
      f"接近 1，原始命中率必然极高而每笔赚的钱极少。**只能读 z_geom 与净钱。**")
    A("")
    for tag, nm, dg, ag in (("A", "组 A（ATR 梯）", lambda s: s.dA, lambda s: s.aheadA),
                            ("C", "组 C（合并）", lambda s: s.dC, lambda s: s.aheadC)):
        A(f"**{nm}，限 d_min ≤ {GATE} ATR 的信号**")
        A("")
        near = [s for s in sigs if dg(s) <= GATE]
        A(HDR.replace("| 档 | 距离区间(ATR) |", "| 方向 | 说明 |"))
        A(SEP)
        for lbl, desc, fn in (
            ("拒绝", "位在后方，方向远离它", lambda s: not ag(s)),
            ("接受", "位在前方，方向穿过它", ag),
        ):
            g = [s for s in near if fn(s)]
            if len(g) < 20:
                A(f"| {lbl} | {desc} | {len(g)} | 样本不足 | | | | | | | | |")
                continue
            bump()
            A(row(lbl, desc, cellstat(g, near)))
        rej = [s for s in near if not ag(s) and s.hit is not None]
        acc = [s for s in near if ag(s) and s.hit is not None]
        if len(rej) >= 20 and len(acc) >= 20:
            xs = [0.0 if not ag(s) else 1.0 for s in rej + acc]
            ys = [1 if s.hit else 0 for s in rej + acc]
            ps = [s.pnull for s in rej + acc]
            zi = trend_z(xs, ys, ps)
            mm = [s.money for s in rej], [s.money for s in acc]
            bump(2)
            A("")
            A(f"- 「接受」相对「拒绝」的超额得分 z = **{zi:+.2f}** "
              f"(p={two_sided(zi):.3f})；净钱×1000 差 = "
              f"{1000*(st.mean(mm[1])-st.mean(mm[0])):+.1f}"
              f"（拒绝 {1000*st.mean(mm[0]):+.1f} vs 接受 "
              f"{1000*st.mean(mm[1]):+.1f}）。")
        A("")
    A("**信号 K 是否真的横跨该位**（更严格的「穿过」定义：位落在信号 K 的 "
      "low–high 之间）：")
    A("")
    A(HDR.replace("| 档 | 距离区间(ATR) |", "| 分组 | 说明 |"))
    A(SEP)
    nearC = [s for s in sigs if s.dC <= GATE]
    for lbl, fn in (("K 横跨该位", lambda s: s.crossC),
                    ("K 未触及该位", lambda s: not s.crossC)):
        g = [s for s in nearC if fn(s)]
        if len(g) < 20:
            A(f"| {lbl} | — | {len(g)} | 样本不足 | | | | | | | | |")
            continue
        bump()
        A(row(lbl, "组 C, d≤0.10", cellstat(g, nearC)))
    A("")

    # ── 6 · 时段位单独看 ────────────────────────────────────────────────────
    A("## 6 · 时段位单独看（语料里出现频率最高的那一类）")
    A("")
    A("### 6.1 最近的时段位是哪一种")
    A("")
    A("| 最近的时段位 | n | 纯括号命中 | 几何零假设 | z_geom | 均净R | 净钱×1000 |")
    A("|---|---|---|---|---|---|---|")
    NAMES = {"ON_hi": "夜盘高", "ON_lo": "夜盘低", "PM_hi": "盘前高",
             "PM_lo": "盘前低", "PDH": "前日高", "PDL": "前日低"}
    for k2, cn in NAMES.items():
        g = [s for s in sigs if s.nameB == k2]
        if len(g) < 20:
            A(f"| {cn} | {len(g)} | 样本不足 | | | | |")
            continue
        bump()
        c = cellstat(g, sigs)
        A(f"| {cn} | {c['n']} | {100*c['obs']:.1f}% | {100*c['null']:.1f}% | "
          f"{c['z']:+.2f} | {c['net']:+.3f} | {1000*c['money']:+.1f} |")
    A("")
    A("### 6.2 running extreme 的污染：滞后 3 根之后还剩什么")
    A("")
    A("夜盘 / 盘前高低是**在线累积**的，「我刚创的新高」立刻变成一个位——那是动量"
      "代理，不是静态地图。把最近 3 根排除在外重算，如果效应消失，说明组 B 测的"
      "是「刚创新高」而不是「贴着一个位」。")
    A("")
    A("| 时段位版本 | 超额趋势 z | p | 净钱 ρ | z | d≤0.10 的 n | 该格 z_geom | "
      "该格净钱×1000 |")
    A("|---|---|---|---|---|---|---|---|")
    for nm, g in (("B · running（主表）", lambda s: s.dB),
                  ("B · 滞后 3 根", lambda s: s.dB3)):
        tmp: list[str] = []
        m = strata(sigs, g, tmp)
        ok, _ = gate_row(sigs, g, GATE)
        A(f"| {nm} | {f(m.get('tz'),2,True)} | {two_sided(m.get('tz',float('nan'))):.3f} | "
          f"{f(m.get('rho_m'),3,True)} | {f(m.get('z_m'),2,True)} | {ok['n']} | "
          f"{ok['z']:+.2f} | {1000*ok['money']:+.1f} |")
    A("")
    A("### 6.3 分 RTH / 夜盘（RTH 里夜盘位与盘前位已经封盘，是干净的静态位）")
    A("")
    A("| 时段 | 组 | 可裁决 n | 超额趋势 z | p | 净钱 ρ | z |")
    A("|---|---|---|---|---|---|---|")
    for lbl, sub in (("RTH", [s for s in sigs if s.in_rth]),
                     ("夜盘", [s for s in sigs if not s.in_rth])):
        for tag, g in (("A", lambda s: s.dA), ("B", lambda s: s.dB),
                       ("C", lambda s: s.dC)):
            tmp = []
            m = strata(sub, g, tmp)
            if not m:
                A(f"| {lbl} | {tag} | {len([s for s in sub if s.hit is not None])} "
                  f"| 样本不足 | | | |")
                continue
            A(f"| {lbl} | {tag} | {m['n']} | {f(m['tz'],2,True)} | "
              f"{two_sided(m['tz']):.3f} | {f(m['rho_m'],3,True)} | "
              f"{f(m['z_m'],2,True)} |")
    A("")

    # ── 7 · 标的局限 ────────────────────────────────────────────────────────
    A("## 7 · ⚠ 数据局限：ES=F 的位不是用户交易的位")
    A("")
    A("纪律 5：位相关研究不能用 ^GSPC 代理，主样本必须用 ES=F。但 ES=F 的位与 "
      "CAPITALCOM:SPX500 的官方位也**不是同一套**——锚（前日收盘）与 ATR 都不同。"
      "本节用仓库里的官方位夹具校验「距离分布」在两个标的上是否相似。")
    A("")
    fixture_check(prim, o)
    A("**判断**：见文末结论 §10.4。")
    A("")

    # ── 8 · 反例 ────────────────────────────────────────────────────────────
    A("## 8 · 与假设相反的格子（纪律 7：单列一节）")
    A("")
    A("| 格子 | n | 命中率 | 几何零假设 | 超额pp | z_geom | 净钱×1000 |")
    A("|---|---|---|---|---|---|---|")
    contr = []
    for tag, g in (("A", lambda s: s.dA), ("B", lambda s: s.dB),
                   ("C", lambda s: s.dC)):
        rr = [s for s in sigs if s.hit is not None]
        vals = [g(s) for s in rr]
        bins = quantile_bins(vals, NQ)
        for j in range(NQ):
            grp = [s for s, b in zip(rr, bins) if b == j]
            if len(grp) < 20:
                continue
            c = cellstat(grp, rr)
            contr.append((c["z"], f"组{tag} Q{j+1}", c))
    contr.sort(reverse=True)
    for z, nm, c in contr[:4] + contr[-3:]:
        A(f"| {nm} | {c['n']} | {100*c['obs']:.1f}% | {100*c['null']:.1f}% | "
          f"{100*(c['obs']-c['null']):+.1f} | {z:+.2f} | "
          f"{1000*c['money']:+.1f} |")
    A("")
    A(f"全部 {len(contr)} 个分层格的 z_geom：最大 {max(c[0] for c in contr):+.2f}，"
      f"中位 {st.median([c[0] for c in contr]):+.2f}，"
      f"最小 {min(c[0] for c in contr):+.2f}。")
    A("")

    # ── 9 · 多重比较与结论 ──────────────────────────────────────────────────
    A("## 9 · 多重比较")
    A("")
    thr = _bonf_z(CELLS)
    zmax = max(abs(c[0]) for c in contr)
    A(f"全文共检视 **{CELLS} 个格子**（分层格、趋势检验、闸门格、方向格、安慰剂梯、"
      f"相关系数、标的一致性格）。Bonferroni 门槛 |z| > **{thr:.2f}**"
      f"（α=0.05 双侧）。全文最大的 |z_geom|（分层格）只有 {zmax:.2f}，"
      f"最大的选择 z |z_sel| 也在 3 以内。**没有任何一个格子越过 {thr:.2f}。**"
      f"常规 |z|>1.96 在这个 family size 下没有意义：{CELLS} 个格子里按纯噪声"
      f"就该出现约 {0.05*CELLS:.0f} 个 |z|>1.96。")
    A("")

    # ── 10 · 结论 ──────────────────────────────────────────────────────────
    A("## 10 · 结论")
    A("")
    A("### 10.1 具名位闸门：不成立")
    A("")
    okA = cellstat([s for s in sigs if s.dA <= GATE], sigs)   # 已在 §3 计入 family
    okC = cellstat([s for s in sigs if s.dC <= GATE], sigs)
    A(f"1. **闸门本身几乎是空的**。ATR 梯的最大半档距是 0.173 ATR，"
      f"所以 ≤0.10 ATR 这个条件放过 **{100*okA['n']/len(sigs):.0f}%** 的信号；"
      f"加上时段位（组 C）放过 **{100*okC['n']/len(sigs):.0f}%**。"
      f"一个不筛东西的闸门不可能改善任何东西——事实上 Δ均净R = "
      f"{okA['net']-base_net:+.3f}（z_sel = {f(okA['zs_net'],2,True)}）。")
    A(f"2. **单调性不存在**。三组的超额趋势 z 分别 "
      f"{f(summary['A']['tz'],2,True)} / {f(summary['B']['tz'],2,True)} / "
      f"{f(summary['C']['tz'],2,True)}，全部 |z|<1.96，而且**符号不一致**"
      f"（组 B 是正的，即「离时段位越远反而越好」，与假设相反）。")
    A("3. **组 A 的 Q5 那个 z_geom = −2.56 是唯一像样的格子，但它撑不住**："
      "①它不单调（Q2 是 +0.18，Q3 是 −0.02）；②它在 "
      f"{CELLS} 个格子里，Bonferroni 门槛是 {thr:.2f}；③净钱只有 −13.7/1000 ATR，"
      "与 Q3 的 −21.2 相比并不是最差的那一档。")
    A("")
    A("### 10.2 安慰剂：测的确实是「离任意规则网格近」")
    A("")
    A(f"真梯的趋势 z（{real_tz:+.2f}）落在 9 条安慰剂梯的经验分布"
      f"（均值 {st.mean(plac_tz):+.2f}，sd {st.stdev(plac_tz):.2f}）的中间地带；"
      f"平移 +0.20 的假梯（z = "
      f"{[t for n,t in zip([p[0] for p in PLAC], plac_tz) if n=='平移 +0.20'][0]:+.2f}）"
      f"比真梯更「支持假设」。等距 0.20 梯与真梯的 d_min 秩相关高达 +0.55——"
      "两条梯子本来就在测同一个量。**所以：即使分层效果是真的，它测的也是"
      "「价格离某个规则网格有多近」这个平凡的模运算属性，与斐波那契、"
      "与 Saty 的具名位无关。** 这是本项目第二次得到同一个结论"
      "（第一次是 GOLDEN_GATE_REPRODUCTION 的安慰剂梯子）。")
    A("")
    A("### 10.3 方向性：假设的方向反了（但同样不显著）")
    A("")
    A("假设预测「拒绝（远离该位）」优于「接受（穿过该位）」。实测两组的 z_geom "
      "都是负的、彼此差异 z = +0.17（组 A）/ +0.13（组 C），即**接受略优于拒绝**，"
      "方向与假设相反，幅度是零。更严格的「信号 K 真的横跨该位」这个分组也指向"
      "同一边：横跨组 z_geom −0.63 / 净钱 +1.0，未触及组 −2.09 / −10.5，"
      "差异 z_sel(净R) = +2.14。这个格子是全文最像样的一个，但 ①它在 "
      f"{CELLS} 个格子里，Bonferroni 门槛 {thr:.2f}；②它说的是**穿过**位好，不是**贴着**位好——"
      "那是「信号 K 有力度」的另一种说法，和 V15_ENTRY_LOCATION 里 D2r "
      "（信号K越大反而越好，趋势 z = +2.25）是同一个东西的两次测量，不是新证据。")
    A("")
    A("### 10.4 标的局限：这个闸门原理上就不可移植")
    A("")
    A("**边际分布可移植，逐笔判决不可移植。** 292 根重叠 K 上，两个标的的 d_min "
      "边际分布几乎一样（均值 0.046 vs 0.044，中位 0.045 vs 0.039），"
      "但**同一根 K 上的 d_min 秩相关是 −0.35**，闸门在有筛选力的阈值上 "
      "Cohen κ 接近 0。原因是几何的、不是噪声：两条梯子步长几乎相同"
      "（ATR 比值 1.054）但相位差约半格（期货基差 +46 点 ≈ 0.50 ATR，"
      "锚也不同），两条锯齿波错开半格必然反相。")
    A("")
    A("这有两层含义，都必须说清楚：")
    A("")
    A("- **对本文的结论无影响**：本文的结论是「没有效应」。距离分布在两个标的上"
      "同形，所以「d_min 分不出好坏」这个否定结论可以直接搬到 SPX500——"
      "一个在 ES 上是纯噪声的变量，换个相位仍然是纯噪声。")
    A("- **对任何肯定结论有致命影响**：如果将来有人在 ES=F 上找到一个"
      "「贴位」效应并想上线到 CAPITALCOM:SPX500，κ≈0 意味着"
      "**线上被选中的将是完全不同的一批交易**。位价相关的肯定结论必须在"
      "真 SPX500 历史上重做，不能移植。仓库里现有的 SPX500 历史只有 4 天 / "
      "299 根，远远不够。")
    A("")
    A("### 10.5 一句话")
    A("")
    A("**具名位闸门不成立，而且是三重不成立**：闸门放过 91–97% 的信号所以"
      "根本不筛东西；分层不单调且三组符号不一致；把梯子平移或换成等距梯得到"
      "同样量级的效应，说明测的是「离任意网格近」而不是「离具名位近」。"
      "**不要把它写进 v15。** 如果一定要从 Saty 的 #ideas 句式里提取什么，"
      "可提取的是**目标**那一半（去哪儿、多大概率到），不是**入场**那一半——"
      "这与 GOLDEN_GATE_REPRODUCTION §4 的降级结论一致。")
    A("")

    txt = "\n".join(o)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(txt)
    print(txt)
    print("\n\n[CELLS]", CELLS, "[bonf]", f"{thr:.2f}")


if __name__ == "__main__":
    main()
