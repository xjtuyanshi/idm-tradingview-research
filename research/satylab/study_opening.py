#!/usr/bin/env python3
"""Opening type as a conditioning variable — base rates, not signals.

Question: before you risk anything, the cheapest information available is *how
the day opened*.  Does it condition the day's behaviour on the Saty ATR level
map — GG trigger, GG completion, +-1 ATR, trend-vs-reversal, and above all the
day's range, which decides whether the day is worth trading at all?

Everything here is a base rate.  Nothing here is a trade.  Four rails, all
learned the expensive way from the v12 failure:

  1. Every proportion carries a Wilson CI and its n.
  2. Every conditioned cell is tested against its complement with a two-
     proportion z.  |z| < 1.96 prints as "没做功", however pretty the point
     estimate is.
  3. Directional claims use a WITHIN-DAY paired test (McNemar) as well.  A gap
     bucket is also a volatility bucket: on a big-gap day BOTH sides of the
     open get reached more often, so an unpaired "up-side rate is higher than
     baseline" proves nothing about direction.  Only up-only vs down-only does.
  4. Every headline claim is re-run on four disjoint sub-periods.  A result
     that only exists pooled is reported as unstable.
  5. Every test lands in a family counter, printed at the end.

READ SECTION 0 BEFORE ANYTHING ELSE.  It shows that Yahoo's ^GSPC open — the
series every other study in this repo uses — is a stale index print, and that
running this study on it manufactures a spurious "gaps continue" signal at
z=+7.5 which reverses to z=-0.6 on the same days measured with real traded
prices.  The primary instrument here is therefore SPY.

Usage:
    python research/satylab/study_opening.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402

INF = float("inf")
GSPC_CLEAN_FROM = date(2017, 1, 1)
K = 0.236
GG = levels.GG_ENTRY        # 0.382
GGC = levels.GG_COMPLETE    # 0.618

ERAS = [(date(2006, 1, 1), date(2011, 1, 1)),
        (date(2011, 1, 1), date(2016, 1, 1)),
        (date(2016, 1, 1), date(2021, 1, 1)),
        (date(2021, 1, 1), date(2027, 1, 1))]


# --------------------------------------------------------------------------
# family accounting
# --------------------------------------------------------------------------
class Family:
    def __init__(self) -> None:
        self.tests: list[tuple[str, float, int]] = []

    def record(self, label: str, z: float, n: int) -> float:
        self.tests.append((label, z, n))
        return z

    def report(self) -> str:
        m = len(self.tests)
        sig = [t for t in self.tests if abs(t[1]) >= 1.96]
        strong = [t for t in self.tests if abs(t[1]) >= 3.0]
        zmax = max((abs(t[1]) for t in self.tests), default=0.0)
        p_one = 2 * (1 - _norm_cdf(zmax))
        p_family = 1 - (1 - p_one) ** m if m else 1.0
        out = ["", "=" * 78,
               "家族统计（FAMILY ACCOUNTING）— 上次失败就是死在这一步没做",
               "=" * 78,
               f"  本报告共执行 {m} 次两比例/配对检验。",
               f"  |z|>=1.96: {len(sig)} 个（纯噪声期望 {0.05*m:.1f}）",
               f"  |z|>=3.00: {len(strong)} 个（纯噪声期望 {0.0027*m:.1f}）",
               f"  最极端 |z|={zmax:.2f}，单次 p={p_one:.2e}，"
               f"家族极值 p(Šidák,M={m})={p_family:.2e}",
               "",
               "  注：这些检验彼此高度相关（同一批日子、互相嵌套的结果变量），",
               "  所以 Šidák 是保守的、期望值是乐观的。真正的判据不是 p，",
               "  而是第 6/7 节的分期稳定性——一个只在合并样本里存在的效应不算数。",
               "",
               "  |z| 最大的 20 个格子："]
        for label, z, n in sorted(self.tests, key=lambda t: -abs(t[1]))[:20]:
            mark = "***" if abs(z) >= 3 else ("*" if abs(z) >= 1.96 else "")
            out.append(f"    {mark:<4}z={z:+6.2f}  n={n:<6} {label}")
        return "\n".join(out)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


FAM = Family()


def mcnemar_z(a_only: int, b_only: int) -> float:
    """Paired within-day comparison.  a_only/b_only are the discordant counts.

    This is the test that survives the volatility confound: on a big-gap day
    both barriers are reached more often, and only the days where exactly one
    was reached carry directional information.
    """
    d = a_only + b_only
    if d == 0:
        return 0.0
    return (a_only - d / 2) / math.sqrt(d * 0.25)


# --------------------------------------------------------------------------
# per-day features
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DayRow:
    day: date
    anchor: float
    atr: float
    o: float
    h: float
    l: float
    c: float
    prev_high: float
    prev_low: float

    @property
    def gap(self) -> float:
        """(open - prior close) / ATR.  Identical to the open's ladder ratio."""
        return (self.o - self.anchor) / self.atr

    @property
    def r_hi(self) -> float: return (self.h - self.anchor) / self.atr

    @property
    def r_lo(self) -> float: return (self.l - self.anchor) / self.atr

    @property
    def rng(self) -> float: return (self.h - self.l) / self.atr

    @property
    def mfe(self) -> float:
        """Travel ABOVE the open, in ATR — measured where you can act."""
        return (self.h - self.o) / self.atr

    @property
    def mae(self) -> float:
        """Travel BELOW the open, in ATR."""
        return (self.o - self.l) / self.atr

    @property
    def body(self) -> float: return (self.c - self.o) / self.atr

    @property
    def toward_anchor(self) -> float:
        """Excursion from the open back toward the prior close."""
        return self.mae if self.gap > 0 else self.mfe

    @property
    def away_anchor(self) -> float:
        return self.mfe if self.gap > 0 else self.mae

    @property
    def filled(self) -> bool:
        """Did the day trade all the way back to the anchor (prior close)?"""
        return (self.r_lo <= 0) if self.gap > 0 else (self.r_hi >= 0)


def build_rows(daily: list[Bar], lv: dict[date, levels.DayLevels],
               start: date | None = None) -> list[DayRow]:
    out = []
    for b in daily:
        L = lv.get(b.day)
        if not L or (start and b.day < start):
            continue
        out.append(DayRow(b.day, L.anchor, L.atr, b.open, b.high, b.low,
                          b.close, L.prev_high, L.prev_low))
    return out


def rth_daily_from_hourly(sym: str) -> list[Bar]:
    """Synthetic RTH-only daily bars from 730d hourly, identical construction
    for every symbol so anchors and ATRs stay comparable."""
    sess = data.group_by_day(data.load(sym, "730d", "1h"))
    out = []
    for day in sorted(sess):
        bars = [b for b in sess[day] if "09:30" <= b.hhmm < "16:00"]
        if len(bars) < 5 or bars[0].hhmm != "09:30":
            continue
        out.append(Bar(bars[0].dt, day, bars[0].open,
                       max(b.high for b in bars), min(b.low for b in bars),
                       bars[-1].close, 0.0))
    return out


def is_spy_exdiv_candidate(d: date) -> bool:
    """SPY goes ex-dividend on the third Friday of Mar/Jun/Sep/Dec.  On those
    days SPY gaps down ~0.3% for a reason that has nothing to do with the
    market, which is a real (small) bias in every SPY gap statistic here."""
    return d.month in (3, 6, 9, 12) and d.weekday() == 4 and 15 <= d.day <= 21


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------
def outcomes_open_relative(r: DayRow) -> dict[str, bool | None]:
    """All measured FROM THE OPEN, so they are comparable across gap buckets.
    An anchor-relative outcome such as 'touched +0.382' is mechanically
    guaranteed for a +0.5 gap and would only be measuring the gap again."""
    return {
        "开盘上行>=0.236ATR": r.mfe >= K,
        "开盘下行>=0.236ATR": r.mae >= K,
        "开盘上行>=0.382ATR": r.mfe >= GG,
        "开盘下行>=0.382ATR": r.mae >= GG,
        "开盘上行>=0.618ATR": r.mfe >= GGC,
        "开盘下行>=0.618ATR": r.mae >= GGC,
        "仅上破0.236(未下破)": (r.mfe >= K) and (r.mae < K),
        "仅下破0.236(未上破)": (r.mae >= K) and (r.mfe < K),
        "两边0.236都没破(死盘)": (r.mfe < K) and (r.mae < K),
        "收盘高于开盘": r.c > r.o,
        "日振幅>=1.0ATR": r.rng >= 1.0,
        "日振幅<0.5ATR": r.rng < 0.5,
    }


def outcomes_anchor_relative(r: DayRow) -> dict[str, bool | None]:
    """None = the open already sits beyond the level, so the 'touch' is
    predetermined and is not a test."""
    def g(predetermined: bool, hit: bool) -> bool | None:
        return None if predetermined else hit
    return {
        "触及+0.382(开盘未在其上)": g(r.gap >= GG, r.r_hi >= GG),
        "触及-0.382(开盘未在其下)": g(r.gap <= -GG, r.r_lo <= -GG),
        "触及+0.618(开盘未在其上)": g(r.gap >= GGC, r.r_hi >= GGC),
        "触及-0.618(开盘未在其下)": g(r.gap <= -GGC, r.r_lo <= -GGC),
        "触及+1.0ATR(开盘未在其上)": g(r.gap >= 1.0, r.r_hi >= 1.0),
        "触及-1.0ATR(开盘未在其下)": g(r.gap <= -1.0, r.r_lo <= -1.0),
        "触及±1.0ATR任一侧": g(abs(r.gap) >= 1.0,
                                r.r_hi >= 1.0 or r.r_lo <= -1.0),
    }


def gg_completion(r: DayRow) -> dict[str, bool | None]:
    up = (r.r_hi >= GGC) if (r.gap < GG and r.r_hi >= GG) else None
    dn = (r.r_lo <= -GGC) if (r.gap > -GG and r.r_lo <= -GG) else None
    return {"看涨GG完成|盘中真触发": up, "看跌GG完成|盘中真触发": dn}


# --------------------------------------------------------------------------
# buckets
# --------------------------------------------------------------------------
GAP_EDGES = [(-INF, -0.5), (-0.5, -0.236), (-0.236, 0.0),
             (0.0, 0.236), (0.236, 0.5), (0.5, INF)]
GAP_NAMES = ["跳空 < -0.5", "-0.5 ~ -0.236", "-0.236 ~ 0",
             "0 ~ +0.236", "+0.236 ~ +0.5", "跳空 > +0.5"]
ABSGAP_NAMES = ["|跳空| < 0.1", "0.1 ~ 0.236", "0.236 ~ 0.5", "|跳空| > 0.5"]
ZONE_ORDER = ["开在 -1ATR 以下", "开在 -0.618 以下", "开在 GG 内(空)",
              "开在 put trigger 下方", "开在锚附近 ±0.236", "开在 call trigger 上方",
              "开在 GG 内(多)", "开在 +0.618 以上", "开在 +1ATR 以上"]
PRIOR_ORDER = ["开在前日低之下", "开在前日区间内", "开在前日高之上"]
SIGN_ORDER = ["跳空低开<=-0.236", "平开 |跳空|<0.05", "跳空高开>=0.236"]


def gap_bucket(r: DayRow) -> str:
    for (lo, hi), name in zip(GAP_EDGES, GAP_NAMES):
        if lo <= r.gap < hi:
            return name
    return GAP_NAMES[-1]


def absgap_bucket(r: DayRow) -> str:
    a = abs(r.gap)
    return ("|跳空| < 0.1" if a < 0.1 else "0.1 ~ 0.236" if a < K
            else "0.236 ~ 0.5" if a < 0.5 else "|跳空| > 0.5")


def gap_sign(r: DayRow) -> str | None:
    if r.gap >= K:
        return "跳空高开>=0.236"
    if r.gap <= -K:
        return "跳空低开<=-0.236"
    if abs(r.gap) < 0.05:
        return "平开 |跳空|<0.05"
    return None


def open_zone(r: DayRow) -> str:
    g = r.gap
    if g >= 1.0:
        return "开在 +1ATR 以上"
    if g >= GGC:
        return "开在 +0.618 以上"
    if g >= GG:
        return "开在 GG 内(多)"
    if g >= K:
        return "开在 call trigger 上方"
    if g > -K:
        return "开在锚附近 ±0.236"
    if g > -GG:
        return "开在 put trigger 下方"
    if g > -GGC:
        return "开在 GG 内(空)"
    if g > -1.0:
        return "开在 -0.618 以下"
    return "开在 -1ATR 以下"


def prior_range_zone(r: DayRow) -> str:
    if r.o > r.prev_high:
        return "开在前日高之上"
    if r.o < r.prev_low:
        return "开在前日低之下"
    return "开在前日区间内"


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
def crosstab(title: str, rows: list, bucket_fn, outcome_fn,
             order: list[str] | None = None, min_n: int = 25,
             note: str = "", getter=lambda x: x) -> str:
    tally: dict[str, dict[str, list[int]]] = {}
    tot: dict[str, list[int]] = {}
    for raw in rows:
        r = getter(raw)
        b = bucket_fn(raw)
        if b is None:
            continue
        for name, hit in outcome_fn(r).items():
            if hit is None:
                continue
            c = tally.setdefault(b, {}).setdefault(name, [0, 0])
            c[0] += int(hit)
            c[1] += 1
            t = tot.setdefault(name, [0, 0])
            t[0] += int(hit)
            t[1] += 1

    keys = [k for k in (order or sorted(tally)) if k in tally]
    lines = [title, "=" * (len(title) + 12)]
    if note:
        lines.append(note)
    lines.append("")
    for name in tot:
        k0, n0 = tot[name]
        lines.append(f"  ▸ {name}    无条件基准 {stats.fmt_rate(k0, n0)}")
        for b in keys:
            cell = tally[b].get(name)
            if not cell:
                continue
            k, n = cell
            if n < min_n:
                lines.append(f"      {b:<24}{stats.fmt_rate(k, n)}"
                             f"   (n<{min_n}, 不检验)")
                continue
            z = FAM.record(f"{title} | {b} | {name}",
                           stats.two_proportion_z(k, n, k0 - k, n0 - n), n)
            v = "**做功**" if abs(z) >= 3 else "做功" if abs(z) >= 1.96 else "没做功"
            lines.append(f"      {b:<24}{stats.fmt_rate(k, n)}   z={z:+5.2f} {v}")
        lines.append("")
    lines.append(f"  [family: 本表检视 {sum(len(v) for v in tally.values())} "
                 f"个 (条件×结果) 格子]")
    return "\n".join(lines)


def qs(vals: list[float], q=(0.1, 0.25, 0.5, 0.75, 0.9)) -> list[float]:
    s = sorted(vals)
    return [s[min(len(s) - 1, int(len(s) * x))] for x in q]


def dist_table(title: str, rows: list, bucket_fn, value_fn,
               order: list[str] | None = None, min_n: int = 25) -> str:
    grp: dict[str, list[float]] = {}
    for r in rows:
        b = bucket_fn(r)
        if b is not None:
            grp.setdefault(b, []).append(value_fn(r))
    allv = [v for g in grp.values() for v in g]
    keys = [k for k in (order or sorted(grp)) if k in grp]
    lines = [title, "-" * (len(title) + 12), "",
             f"  {'条件':<24}{'n':>6}{'p10':>7}{'p25':>7}{'中位':>7}"
             f"{'p75':>7}{'p90':>7}"]
    lines.append(f"  {'【无条件基准】':<22}{len(allv):>6}" +
                 "".join(f"{x:>7.2f}" for x in qs(allv)))
    for b in keys:
        if len(grp[b]) < min_n:
            continue
        lines.append(f"  {b:<24}{len(grp[b]):>6}" +
                     "".join(f"{x:>7.2f}" for x in qs(grp[b])))
    return "\n".join(lines)


def stability(title: str, rows: list[DayRow], bucket_fn, stat_name: str,
              hit_fn, order: list[str], min_n: int = 20) -> str:
    """Re-run one binary statistic on four disjoint eras.  This is the real
    filter: pooled significance with era-by-era sign flips is not a finding."""
    lines = [title, "-" * (len(title) + 12), "",
             f"  {'条件':<20}{'期间':<12}{'n':>5}   {stat_name}"]
    for b in order:
        sel = [r for r in rows if bucket_fn(r) == b]
        if len(sel) < min_n:
            continue
        k = sum(1 for r in sel if hit_fn(r))
        lines.append(f"  {b:<20}{'全样本':<12}{len(sel):>5}   "
                     f"{stats.fmt_rate(k, len(sel))}")
        for a, z in ERAS:
            e = [r for r in sel if a <= r.day < z]
            if len(e) < min_n:
                continue
            k = sum(1 for r in e if hit_fn(r))
            lines.append(f"  {'':<20}{f'{a.year}-{z.year-1}':<12}{len(e):>5}   "
                         f"{stats.fmt_rate(k, len(e))}")
        lines.append("")
    return "\n".join(lines)


def paired_table(title: str, rows: list[DayRow], bucket_fn,
                 order: list[str], thr: float = GG,
                 up_label: str = "上行", dn_label: str = "下行",
                 up_fn=lambda r, t: r.mfe >= t,
                 dn_fn=lambda r, t: r.mae >= t,
                 by_era: bool = True) -> str:
    """Within-day paired (McNemar) direction test, plus era stability."""
    lines = [title, "-" * (len(title) + 12), "",
             f"  {'条件':<20}{'期间':<12}{'n':>5}{up_label+'率':>9}"
             f"{dn_label+'率':>9}{'仅'+up_label:>7}{'仅'+dn_label:>7}"
             f"{'McNemar z':>11}  判定"]

    def emit(sel, b, era):
        u = sum(1 for r in sel if up_fn(r, thr))
        d = sum(1 for r in sel if dn_fn(r, thr))
        uo = sum(1 for r in sel if up_fn(r, thr) and not dn_fn(r, thr))
        do = sum(1 for r in sel if dn_fn(r, thr) and not up_fn(r, thr))
        z = mcnemar_z(uo, do)
        if era == "全样本":
            FAM.record(f"{title} | {b} | McNemar {up_label} vs {dn_label}",
                       z, len(sel))
        v = "做功" if abs(z) >= 1.96 else "没做功"
        return (f"  {b if era=='全样本' else '':<20}{era:<12}{len(sel):>5}"
                f"{100*u/len(sel):>8.1f}%{100*d/len(sel):>8.1f}%"
                f"{uo:>7}{do:>7}{z:>11.2f}  {v}")

    for b in order:
        sel = [r for r in rows if bucket_fn(r) == b]
        if len(sel) < 20:
            continue
        lines.append(emit(sel, b, "全样本"))
        if by_era:
            for a, z in ERAS:
                e = [r for r in sel if a <= r.day < z]
                if len(e) >= 20:
                    lines.append(emit(e, b, f"{a.year}-{z.year-1}"))
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# section 0 — why this study cannot be run on ^GSPC
# --------------------------------------------------------------------------
def section0() -> str:
    out = ["", "=" * 78,
           "0. 数据健康：^GSPC 的开盘价是滞后印刷，它会凭空造出一个『跳空延续』信号",
           "=" * 78]

    g = data.daily("^GSPC", years="20y")
    s = data.daily("SPY", years="20y")
    lg, ls = levels.build(g), levels.build(s)
    G = {b.day: b for b in g}
    S = {b.day: b for b in s}

    out += ["", "0A. 逐年对比：同一天，两个标的记录的跳空幅度（ATR 归一）", "",
            f"  {'年':<6}{'n':>5}{'中位|GSPC跳空|':>16}{'中位|SPY跳空|':>15}"
            f"{'比值':>8}{'相关':>8}"]
    per: dict[int, list[tuple[float, float]]] = {}
    for day in sorted(set(G) & set(S)):
        Lg, Ls = lg.get(day), ls.get(day)
        if not Lg or not Ls:
            continue
        per.setdefault(day.year, []).append(
            (Lg.ratio_of(G[day].open), Ls.ratio_of(S[day].open)))
    for y in sorted(per):
        a = [x for x, _ in per[y]]
        b = [x for _, x in per[y]]
        ma = sorted(abs(x) for x in a)[len(a) // 2]
        mb = sorted(abs(x) for x in b)[len(b) // 2]
        mxa, mxb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - mxa) * (y2 - mxb) for x, y2 in zip(a, b))
        den = math.sqrt(sum((x - mxa) ** 2 for x in a) *
                        sum((y2 - mxb) ** 2 for y2 in b))
        r = cov / den if den else 0.0
        flag = "  <-- 明显失真" if ma / mb < 0.6 else ""
        out.append(f"  {y:<6}{len(per[y]):>5}{ma:>16.3f}{mb:>15.3f}"
                   f"{ma/mb:>8.2f}{r:>8.3f}{flag}")
    neq = sum(1 for i in range(1, len(g))
              if abs(g[i].open - g[i - 1].close) < 1e-9)
    out += ["",
            f"  ^GSPC 上『开盘价 == 前收盘价（精确相等）』共 {neq} 次 / {len(g)-1}，"
            "全部落在 2006-2015。",
            "  2017 年之后比值升到 0.8-0.93、相关 0.97-0.99，但仍然系统性压缩约 10%。"]

    out += ["", "0B. 失真机制：开盘后头几分钟是否在『把跳空补齐』（60 天 5 分钟线）", ""]
    for sym in ("^GSPC", "SPY"):
        dd = data.daily(sym, years="20y")
        lv = levels.build(dd)
        f = data.group_by_day(data.fine(sym))
        xs, y5, y30 = [], [], []
        for day in sorted(f):
            L, bars = lv.get(day), f[day]
            if not L or len(bars) < 10:
                continue
            b0 = bars[0]
            xs.append((b0.open - L.anchor) / L.atr)
            y5.append((b0.close - b0.open) / L.atr)
            y30.append((bars[5].close - b0.open) / L.atr)
        r5, s5 = _corr_slope(xs, y5)
        r30, s30 = _corr_slope(xs, y30)
        out.append(f"  {sym:<7} n={len(xs)}  corr(跳空, 前5分钟漂移)={r5:+.3f} "
                   f"斜率={s5:+.3f}   corr(跳空, 前30分钟漂移)={r30:+.3f} "
                   f"斜率={s30:+.3f}")
    out += ["  解读：若开盘印刷滞后，跳空越大、开盘后头几分钟越会顺跳空方向补齐，",
            "        斜率显著为正即是失真证据。^GSPC 斜率 +0.086、SPY +0.007。",
            "        也就是说 ^GSPC 的开盘印刷平均漏掉了约 9% 的跳空，",
            "        这 9% 会在开盘后 5 分钟内走完——而它在数据里长得像『延续』。"]
    # independent corroboration: regress the GSPC gap on the SPY gap
    gx, gy = [], []
    for day in sorted(set(G) & set(S)):
        Lg, Ls = lg.get(day), ls.get(day)
        if not Lg or not Ls or day < GSPC_CLEAN_FROM:
            continue
        gx.append(Ls.ratio_of(S[day].open))
        gy.append(Lg.ratio_of(G[day].open))
    r, sl = _corr_slope(gx, gy)
    out += ["",
            f"  独立佐证（2017+，n={len(gx)}）：回归 GSPC跳空 ~ SPY跳空，"
            f"corr={r:.3f}，斜率={sl:.3f}。",
            "  斜率 <1 即为压缩。注意它比 0A 表里的中位数比值（0.8-0.93）更低——",
            "  回归被大跳空日主导，说明**跳空越大压缩越狠**，这正是滞后印刷的预测",
            "  （行情越大，09:30 时还没开盘的成分股越多）。",
            "  0B 的漂移斜率 (+0.086) 只覆盖开盘后 5 分钟、且 n=59，是压缩量的下界，",
            "  两者方向一致但不必数值互补——不要把它们当成同一个量。"]

    out += ["", "0C. 决定性对照：同一批日子，两个标的各自度量的当日走势", "",
            "  日子由 SPY 的跳空定义（2017 年之后，^GSPC 已是最干净的时期）。",
            "  这两行必须一致，否则其中一个是错的。", ""]
    SR = {r.day: r for r in build_rows(s, ls)}
    GR = {r.day: r for r in build_rows(g, lg)}
    common = sorted(set(SR) & set(GR))
    for lo, hi, lab in ((-INF, -0.5, "SPY 跳空 <= -0.5"),
                        (0.5, INF, "SPY 跳空 >= +0.5")):
        days = [d for d in common
                if lo <= SR[d].gap < hi and d >= GSPC_CLEAN_FROM]
        out.append(f"  {lab}   (2017+, n={len(days)})")
        for nm, M in (("SPY  ", SR), ("^GSPC", GR)):
            up = sum(1 for d in days if M[d].mfe >= GG)
            dn = sum(1 for d in days if M[d].mae >= GG)
            uo = sum(1 for d in days if M[d].mfe >= GG and M[d].mae < GG)
            do = sum(1 for d in days if M[d].mae >= GG and M[d].mfe < GG)
            z = mcnemar_z(uo, do)
            med = sorted(M[d].gap for d in days)[len(days) // 2]
            mfe = sorted(M[d].mfe for d in days)[len(days) // 2]
            mae = sorted(M[d].mae for d in days)[len(days) // 2]
            out.append(f"    {nm}  上行>=0.382 {100*up/len(days):5.1f}%   "
                       f"下行>=0.382 {100*dn/len(days):5.1f}%   "
                       f"McNemar z={z:+5.2f}   "
                       f"中位跳空{med:+.3f} 中位上行{mfe:.3f} 中位下行{mae:.3f}")
        out.append("")
    out += ["  结论：同一批日子，^GSPC 说『跳空强烈延续』(z=+7.5/-4.7)，",
            "  SPY 说『什么也没有』(z=-0.6/+1.8)。差异完全来自开盘印刷。",
            "  index 的 09:30 印刷不可成交，SPY 的可以——所以 SPY 是真值，",
            "  ^GSPC 的『延续信号』是数据伪影。",
            "",
            "  → 本报告主标的 = SPY（20 年真实开盘印刷，ATR 归一后与 SPX 同构）。",
            "  → 已知偏差：SPY 每季度第三个周五除息，机械低开约 0.3%（≈0.3 ATR）。",
            "    第 7 节给出剔除这些日子的稳健性复核。",
            "  → 这条结论对本仓库其他研究同样成立：任何用 ^GSPC 开盘价做的",
            "    『开盘后如何』类统计都需要重新检查。"]
    return "\n".join(out)


def _corr_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    return (cov / math.sqrt(sx * sy) if sx * sy else 0.0,
            cov / sx if sx else 0.0)


# --------------------------------------------------------------------------
# first-hour rows (hourly, 730d) — built on SPY for the same reason
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class HourRow:
    """First-hour state plus REST-OF-DAY outcomes.

    Measuring the day's full high/low against the first hour's direction is
    circular: the first hour is inside the day's range, so "first hour up ->
    day travelled up 0.382" is largely arithmetic, not prediction (it produced
    z=+14 in an earlier draft of this script).  Everything scored below starts
    at the 10:30 price and uses only the remaining bars.
    """
    base: DayRow
    first_close: float
    rest_hi: float
    rest_lo: float
    close: float
    hi_after_h1: bool
    lo_after_h1: bool

    @property
    def day(self) -> date: return self.base.day

    @property
    def h1(self) -> str:
        m = (self.first_close - self.base.o) / self.base.atr
        if m > 0.05:
            return "首小时收在开盘上方"
        if m < -0.05:
            return "首小时收在开盘下方"
        return "首小时基本平收"

    @property
    def rest_mfe(self) -> float:
        return (self.rest_hi - self.first_close) / self.base.atr

    @property
    def rest_mae(self) -> float:
        return (self.first_close - self.rest_lo) / self.base.atr

    @property
    def rest_rng(self) -> float:
        return (self.rest_hi - self.rest_lo) / self.base.atr


def hour_rows(sym: str) -> list[HourRow]:
    d = rth_daily_from_hourly(sym)
    lv = levels.build(d)
    sess = data.group_by_day(data.load(sym, "730d", "1h"))
    out = []
    for b in d:
        L = lv.get(b.day)
        bars = [x for x in sess[b.day] if "09:30" <= x.hhmm < "16:00"]
        if not L or len(bars) < 4:
            continue
        rest = bars[1:]
        base = DayRow(b.day, L.anchor, L.atr, b.open, b.high, b.low, b.close,
                      L.prev_high, L.prev_low)
        rh = max(x.high for x in rest)
        rl = min(x.low for x in rest)
        out.append(HourRow(base, bars[0].close, rh, rl, bars[-1].close,
                           rh >= bars[0].high, rl <= bars[0].low))
    return out


def outcomes_rest_of_day(x: HourRow) -> dict[str, bool | None]:
    """Scored from the 10:30 price forward — no overlap with the first hour."""
    up = "上方" in x.h1
    return {
        "余下时段上行>=0.236ATR": x.rest_mfe >= K,
        "余下时段下行>=0.236ATR": x.rest_mae >= K,
        "余下时段上行>=0.382ATR": x.rest_mfe >= GG,
        "余下时段下行>=0.382ATR": x.rest_mae >= GG,
        "顺首小时方向再走>=0.236": (x.rest_mfe if up else x.rest_mae) >= K,
        "逆首小时方向再走>=0.236": (x.rest_mae if up else x.rest_mfe) >= K,
        "收盘在10:30价之上": x.close > x.first_close,
        "收盘顺首小时方向": (x.close > x.first_close) == up,
        "收盘高于开盘": x.close > x.base.o,
        "当日高点出现在首小时之后": x.hi_after_h1,
        "当日低点出现在首小时之后": x.lo_after_h1,
        "余下时段振幅>=0.5ATR": x.rest_rng >= 0.5,
    }


def barrier_race(sym: str, interval: str, rng_: str, label: str,
                 k: float = K) -> str:
    """From the open, which symmetric +-k ATR barrier is reached FIRST?

    A bar whose own range spans both barriers makes the order unknowable at
    that resolution — counted separately.  A large share there is the honest
    signal that the timeframe cannot answer the question (the trap the Golden
    Gate report already fell into once)."""
    d = rth_daily_from_hourly(sym) if interval == "1h" else None
    if d is None:
        sess_all = data.group_by_day(data.load(sym, rng_, interval))
        bars_by_day = {day: [b for b in v if "09:30" <= b.hhmm < "16:00"]
                       for day, v in sess_all.items()}
        d = []
        for day in sorted(bars_by_day):
            bs = bars_by_day[day]
            if len(bs) < 20:
                continue
            d.append(Bar(bs[0].dt, day, bs[0].open,
                         max(x.high for x in bs), min(x.low for x in bs),
                         bs[-1].close, 0.0))
    else:
        sess_all = data.group_by_day(data.load(sym, "730d", "1h"))
        bars_by_day = {day: [b for b in v if "09:30" <= b.hhmm < "16:00"]
                       for day, v in sess_all.items()}
    lv = levels.build(d)

    tab: dict[str, list[int]] = {}
    for b in d:
        L = lv.get(b.day)
        bars = bars_by_day.get(b.day)
        if not L or not bars:
            continue
        row = DayRow(b.day, L.anchor, L.atr, b.open, b.high, b.low, b.close,
                     L.prev_high, L.prev_low)
        g = gap_sign(row)
        if g is None:
            continue
        up_t, dn_t = b.open + k * L.atr, b.open - k * L.atr
        verdict = 3
        for x in bars:
            hu, hd = x.high >= up_t, x.low <= dn_t
            if hu and hd:
                verdict = 2
                break
            if hu:
                verdict = 0
                break
            if hd:
                verdict = 1
                break
        c = tab.setdefault(g, [0, 0, 0, 0, 0])
        c[verdict] += 1
        c[4] += 1

    lines = [label, "-" * (len(label) + 12),
             f"  {'条件':<20}{'n':>5}{'先上破':>8}{'先下破':>8}"
             f"{'同K不可判':>11}{'都没到':>8}   可判部分『先上破』占比"]
    for g in [x for x in SIGN_ORDER if x in tab]:
        u, dn, amb, non, n = tab[g]
        res = u + dn
        lines.append(f"  {g:<20}{n:>5}{u:>8}{dn:>8}{amb:>11}{non:>8}   "
                     + (stats.fmt_rate(u, res) if res else "n=0"))
    a, b2 = tab.get("跳空高开>=0.236"), tab.get("跳空低开<=-0.236")
    if a and b2 and (a[0] + a[1]) and (b2[0] + b2[1]):
        z = FAM.record(f"{label} | 高开 vs 低开 先上破占比",
                       stats.two_proportion_z(a[0], a[0] + a[1],
                                              b2[0], b2[0] + b2[1]),
                       a[4] + b2[4])
        lines.append(f"  高开 vs 低开 的『先上破』占比: z={z:+.2f} "
                     f"({'做功' if abs(z) >= 1.96 else '没做功'})")
    tot = max(1, sum(v[4] for v in tab.values()))
    amb = sum(v[2] for v in tab.values()) / tot
    lines.append(f"  同根K不可判 = {100*amb:.1f}%"
                 + ("   ← 分辨率不足，本表只能当参考" if amb > 0.25 else ""))
    # explicit resolution diagnostic: how wide is one bar vs the 2k barrier gap
    widths, first_w = [], []
    for day, bars in bars_by_day.items():
        L = lv.get(day)
        if not L or not bars:
            continue
        for x in bars:
            widths.append((x.high - x.low) / L.atr)
        first_w.append((bars[0].high - bars[0].low) / L.atr)
    if widths:
        widths.sort()
        med = widths[len(widths) // 2]
        share = sum(1 for x in widths if x >= 2 * k) / len(widths)
        fmed = sorted(first_w)[len(first_w) // 2]
        fshare = sum(1 for x in first_w if x >= 2 * k) / len(first_w)
        lines.append(f"  分辨率诊断：双边距离 {2*k:.3f} ATR；单根 K 振幅中位 "
                     f"{med:.3f}，其中 {100*share:.1f}% 的 K 自身就跨得过双边；"
                     f"首根 K 中位 {fmed:.3f}，{100*fshare:.1f}% 跨得过。")
    return "\n".join(lines)


# --------------------------------------------------------------------------
def main() -> None:
    print(__doc__.split("Usage:")[0])
    print(section0())

    spy_d = data.daily("SPY", years="20y")
    spy_lv = levels.build(spy_d)
    rows = build_rows(spy_d, spy_lv)
    gspc_d = data.daily("^GSPC", years="20y")
    grows = build_rows(gspc_d, levels.build(gspc_d), start=GSPC_CLEAN_FROM)
    hrows = hour_rows("SPY")

    print(f"\n主样本 SPY 日线 {len(rows)} 天 ({rows[0].day} → {rows[-1].day})")
    print(f"对照   ^GSPC 日线 2017+ {len(grows)} 天（仅用于展示伪影）")
    print(f"日内   SPY 小时线 {len(hrows)} 天 "
          f"({hrows[0].day} → {hrows[-1].day})")

    # ---- 1. unconditional baselines -------------------------------------
    print("\n" + "=" * 78)
    print("1. 无条件基准率（先知道『什么都不看』是什么样，否则无从判断做功与否）")
    print("=" * 78 + "\n")
    acc: dict[str, list[int]] = {}
    for r in rows:
        for k_, v in {**outcomes_open_relative(r),
                      **outcomes_anchor_relative(r)}.items():
            if v is None:
                continue
            c = acc.setdefault(k_, [0, 0])
            c[0] += int(v)
            c[1] += 1
    for k_, (kk, nn) in acc.items():
        print(f"    {k_:<28}{stats.fmt_rate(kk, nn)}")
    print(f"    {'当日回补缺口(回到前收锚)':<28}"
          f"{stats.fmt_rate(sum(1 for r in rows if r.filled), len(rows))}")
    print("\n  ▸ 这几行就是全部判断的分母。特别记住：")
    print("    · 一天从开盘往上走 0.382ATR 的概率 46.5%，往下 47.5%——几乎对称。")
    print("    · 日振幅中位数只有 0.81 ATR，只有三分之一的日子振幅 >= 1 ATR。")
    print("    · 任何条件如果不能把这些数字推离十个百分点以上，它就不值得上图。")
    print()
    print(dist_table("1B. 当日振幅 / ATR 的无条件分布", rows,
                     lambda r: "SPY 20y 全样本", lambda r: r.rng))

    # ---- 2. gap buckets, open-relative ----------------------------------
    print("\n" + "=" * 78)
    print("2. 跳空幅度分档 → 当日结果（一律从开盘价起算）")
    print("=" * 78 + "\n")
    print(crosstab("2A. SPY 20y", rows, gap_bucket, outcomes_open_relative,
                   order=GAP_NAMES,
                   note="  所有结果从开盘价起算，因此不会被跳空本身机械放大。\n"
                        "  但注意：跳空档同时也是波动率档，单边比率变高不等于有方向"
                        "——方向必须看第 7 节的配对检验。"))

    # ---- 3. anchor-relative ---------------------------------------------
    print("\n" + "=" * 78)
    print("3. 跳空幅度 → 位图（锚相对）触及率")
    print("=" * 78)
    print("  这些才是图上直接标出来的位。已剔除『开盘就已经在该位之外』的日子——")
    print("  否则一个 +0.6 的高开日 100% 触及 +0.382，而那不是信息，是同义反复。\n")
    print(crosstab("3A. SPY 20y — 位图触及率", rows, gap_bucket,
                   outcomes_anchor_relative, order=GAP_NAMES))
    print()
    print(crosstab("3B. SPY 20y — Golden Gate 完成率（条件于盘中真触发）",
                   rows, gap_bucket, gg_completion, order=GAP_NAMES))
    print()
    print("3C. 把 GOLDEN_GATE_REPRODUCTION 的总完成率拆开：")
    print("    『开盘就穿透 0.382』和『盘中才触发』根本不是同一件事。\n")
    for sym, rr in (("SPY 20y", rows), ("^GSPC 2017+ (对照)", grows)):
        for side, nm in ((1, "看涨"), (-1, "看跌")):
            trig = [r for r in rr if (r.r_hi >= GG if side > 0
                                      else r.r_lo <= -GG)]
            done = [r for r in trig if (r.r_hi >= GGC if side > 0
                                        else r.r_lo <= -GGC)]
            thru = [r for r in trig if (r.gap >= GG if side > 0
                                        else r.gap <= -GG)]
            tdone = [r for r in thru if r in done]
            intra = [r for r in trig if r not in thru]
            idone = [r for r in intra if r in done]
            z = FAM.record(f"3C {sym} {nm} 开盘穿透 vs 盘中触发 完成率",
                           stats.two_proportion_z(len(tdone), len(thru),
                                                  len(idone), len(intra)),
                           len(trig))
            print(f"  {sym:<20}{nm}GG 全部触发   {stats.fmt_rate(len(done), len(trig))}")
            print(f"  {'':<20}  开盘即穿透 {stats.fmt_rate(len(tdone), len(thru))}"
                  f"   (占全部交易日 {100*len(thru)/len(rr):.1f}%)")
            print(f"  {'':<20}  盘中才触发 {stats.fmt_rate(len(idone), len(intra))}"
                  f"   两者 z={z:+.2f}")
        print()
    print("  读法：GOLDEN_GATE_REPRODUCTION 报的 66% 是一个混合数。")
    print("  它由约 36% 的『开盘跳空穿透』触发（完成率 86-89%）和 64% 的")
    print("  『盘中才触发』（完成率 51-55%）拼成，两者 z=+16~18，是完全不同的两件事。")
    print("  图上给概率时必须分开报——否则在盘中才触发的那一半日子里，")
    print("  你显示的概率会高出十几个百分点。这与 GG 报告里 tesrak 的分时段表一致：")
    print("  开盘档 ~90%、09:30 档 ~70%、之后单调衰减。")
    print("  另注：^GSPC 判定为『开盘即穿透』的日子占比明显低于 SPY，")
    print("  仍然是第 0 节那个开盘印刷压缩造成的（跳空被记小了）。")

    # ---- 4. named open zone ---------------------------------------------
    print("\n" + "=" * 78)
    print("4. 开盘位置（位图命名区间）")
    print("=" * 78)
    print("  锚 = 前收，所以『开盘位置』和『跳空幅度』是同一个随机变量换了个说法，")
    print("  不是第二条独立证据。列出来只因为图上是这么说话的。\n")
    print(crosstab("4A. SPY 20y", rows, open_zone, outcomes_open_relative,
                   order=ZONE_ORDER))

    # ---- 5. prior-day range ---------------------------------------------
    print("\n" + "=" * 78)
    print("5. 开盘 vs 前日区间 —— 这才是与跳空幅度不同的第二个变量")
    print("=" * 78 + "\n")
    print(crosstab("5A. SPY 20y", rows, prior_range_zone,
                   outcomes_open_relative, order=PRIOR_ORDER))
    print()
    print(stability("5B. 分期稳定性：P(日振幅 >= 1.0 ATR)", rows,
                    prior_range_zone, "P(振幅>=1ATR)",
                    lambda r: r.rng >= 1.0, order=PRIOR_ORDER))
    print("5C. 增量价值：控制住跳空大小之后，前日区间位置还剩多少信息？\n")
    print("  『开在前日低之下』通常也是大跳空日，所以上面的 z 可能只是把跳空幅度")
    print("  换个说法。下表在每个跳空档内部再切一次——如果格子间差异消失，")
    print("  那这个变量就没有增量价值。\n")
    print(f"  {'跳空档':<16}{'前日区间位置':<16}{'n':>6}   P(日振幅>=1.0ATR)")
    for gb in ABSGAP_NAMES:
        sub = [r for r in rows if absgap_bucket(r) == gb]
        cells = {}
        for pz in PRIOR_ORDER:
            s2 = [r for r in sub if prior_range_zone(r) == pz]
            if len(s2) < 30:
                continue
            cells[pz] = (sum(1 for r in s2 if r.rng >= 1.0), len(s2))
        for pz, (k, n) in cells.items():
            print(f"  {gb:<16}{pz:<16}{n:>6}   {stats.fmt_rate(k, n)}")
        if "开在前日低之下" in cells and "开在前日高之上" in cells:
            a, b = cells["开在前日低之下"], cells["开在前日高之上"]
            z = FAM.record(f"5C {gb} 前日低之下 vs 前日高之上 P(振幅>=1ATR)",
                           stats.two_proportion_z(a[0], a[1], b[0], b[1]),
                           a[1] + b[1])
            print(f"  {'':<16}{'↑ 两端对比':<16}{'':>6}   z={z:+.2f} "
                  f"{'做功' if abs(z) >= 1.96 else '没做功（该变量在此档内无增量）'}")
        print()

    # ---- 6. range — the robust finding -----------------------------------
    print("\n" + "=" * 78)
    print("6. 当日振幅 / ATR —— 本研究唯一稳健的结论")
    print("=" * 78 + "\n")
    print(dist_table("6A. 按跳空绝对值看 当日振幅/ATR", rows, absgap_bucket,
                     lambda r: r.rng, order=ABSGAP_NAMES))
    print()
    print(dist_table("6B. 按跳空绝对值看 开盘后上行幅度 (high-open)/ATR", rows,
                     absgap_bucket, lambda r: r.mfe, order=ABSGAP_NAMES))
    print()
    print(dist_table("6C. 按跳空绝对值看 开盘后下行幅度 (open-low)/ATR", rows,
                     absgap_bucket, lambda r: r.mae, order=ABSGAP_NAMES))
    print()
    print(crosstab("6D. 跳空绝对值 → 振幅二值检验", rows, absgap_bucket,
                   lambda r: {"日振幅>=1.0ATR": r.rng >= 1.0,
                              "日振幅>=1.5ATR": r.rng >= 1.5,
                              "日振幅<0.5ATR(死盘)": r.rng < 0.5,
                              "开盘后任一方向>=0.382ATR": max(r.mfe, r.mae) >= GG,
                              "开盘后任一方向>=0.618ATR": max(r.mfe, r.mae) >= GGC},
                   order=ABSGAP_NAMES))
    print()
    print(stability("6E. 分期稳定性：P(日振幅 >= 1.0 ATR)", rows, absgap_bucket,
                    "P(振幅>=1ATR)", lambda r: r.rng >= 1.0,
                    order=ABSGAP_NAMES))
    print(stability("6F. 分期稳定性：P(日振幅 < 0.5 ATR)（死盘日）", rows,
                    absgap_bucket, "P(振幅<0.5ATR)", lambda r: r.rng < 0.5,
                    order=ABSGAP_NAMES))

    # ---- 7. the fill-vs-continuation question ---------------------------
    print("\n" + "=" * 78)
    print("7. 关键判定：缺口回补 还是 缺口延续？")
    print("=" * 78)
    print("""
  这是有名的分歧问题，所以用四个互相独立、互相制约的口径同时检验：
    (a) 配对方向检验  —— 从开盘算起，只上破 vs 只下破（McNemar，去掉波动率混淆）
    (b) 完全回补率    —— 当日有没有回到锚（前收）
    (c) 收盘方向      —— 顺跳空 or 逆跳空
    (d) 顺序赛跑      —— 哪一边"先"到（必须日内数据，且要报告分辨率是否够）
  每一项都同时给出四个不重叠子期的结果。合并显著但子期翻号的，一律判为不稳定。
""")
    print(paired_table("7A. 配对方向检验：开盘上行 vs 下行 0.382ATR（含分期）",
                       rows, gap_bucket, GAP_NAMES))
    print(paired_table("7B. 配对：朝锚方向 vs 背锚方向 走 0.236ATR（含分期）",
                       rows, gap_bucket, GAP_NAMES, thr=K,
                       up_label="朝锚", dn_label="背锚",
                       up_fn=lambda r, t: r.toward_anchor >= t,
                       dn_fn=lambda r, t: r.away_anchor >= t))
    print(stability("7C. 完全回补率：当日回到锚（前收）", rows, gap_bucket,
                    "P(当日回到锚)", lambda r: r.filled, order=GAP_NAMES))
    print(stability("7D. 收盘方向：收盘高于开盘", rows, gap_bucket,
                    "P(收盘>开盘)", lambda r: r.c > r.o, order=GAP_NAMES))

    print("\n7E. 除息稳健性复核（剔除每季第三个周五，SPY 机械低开约 0.3%）\n")
    clean = [r for r in rows if not is_spy_exdiv_candidate(r.day)]
    print(f"  剔除 {len(rows)-len(clean)} 天。重跑 7A 的两个极端档：\n")
    print(paired_table("7E-1. 剔除除息日后", clean, gap_bucket,
                       ["跳空 < -0.5", "跳空 > +0.5"], by_era=False))

    print("\n7F. 汇总配对：整体是否存在『向锚拉回』，以及它随跳空变大如何变化\n")
    pooled = [r for r in rows if abs(r.gap) >= 0.1]
    print(paired_table("7F-0. 汇总（|跳空|>=0.1 的全部日子）", pooled,
                       lambda r: "|跳空|>=0.1 全部", ["|跳空|>=0.1 全部"],
                       thr=K, up_label="朝锚", dn_label="背锚",
                       up_fn=lambda r, t: r.toward_anchor >= t,
                       dn_fn=lambda r, t: r.away_anchor >= t))
    print("7F-1. 门槛扫描：拉回效应随跳空变大而消失（全部 4 个门槛都列出，没有挑）\n")
    print(f"  {'样本':<22}{'期间':<12}{'n':>6}{'仅朝锚':>8}{'仅背锚':>8}"
          f"{'朝锚占不一致':>14}{'McNemar z':>11}")
    for thr in (0.1, 0.236, 0.382, 0.5):
        sel = [r for r in rows if abs(r.gap) >= thr]
        for lab, sub in ([("全样本", sel)] +
                         [(f"{a.year}-{b.year-1}", [r for r in sel
                                                    if a <= r.day < b])
                          for a, b in ERAS]):
            uo = sum(1 for r in sub if r.toward_anchor >= K
                     and r.away_anchor < K)
            do = sum(1 for r in sub if r.away_anchor >= K
                     and r.toward_anchor < K)
            z = mcnemar_z(uo, do)
            if lab == "全样本":
                FAM.record(f"7F-1 |跳空|>={thr} 朝锚 vs 背锚", z, len(sub))
            share = 100 * uo / (uo + do) if uo + do else 0
            head = f"|跳空| >= {thr}" if lab == "全样本" else ""
            print(f"  {head:<22}{lab:<12}{len(sub):>6}{uo:>8}{do:>8}"
                  f"{share:>13.1f}%{z:>11.2f}")
        print()
    print("  [family: 本表 4 门槛 × 5 行 = 20 个格子，全部列出]")
    print("  读法：0.1 与 0.236 门槛上四个子期全部同号（其中 0.1 门槛四期全显著），")
    print("  但 0.382 与 0.5 门槛上效应归零、子期还翻号。也就是说——")
    print("  『缺口倾向于被部分回补』只在小跳空日成立，而小跳空日的回补距离")
    print("  本来就短到不值得交易；真正有目标距离的大跳空日反而没有这个倾向。")

    print("\n7G. 顺序赛跑（谁先到）\n")
    print(barrier_race("SPY", "1h", "730d",
                       "7G-1. SPY 730d 小时线"))
    print()
    print(barrier_race("SPY", "5m", "60d",
                       "7G-2. SPY 60d 5 分钟线（n 极小，仅方向性参考）"))
    print()
    print(barrier_race("^GSPC", "5m", "60d",
                       "7G-3. ^GSPC 60d 5 分钟线（伪影对照，勿采信）"))

    print("\n7H. 伪影对照：同一检验跑在 ^GSPC 2017+ 上会得到什么\n")
    print(paired_table("7H-1. ^GSPC 2017+（不可采信，仅示范伪影强度）",
                       grows, gap_bucket, GAP_NAMES, by_era=False))

    # ---- 8. first hour ---------------------------------------------------
    print("\n" + "=" * 78)
    print("8. 开盘第一小时方向（SPY 730d 小时线）")
    print("=" * 78)
    print("  口径说明 1：任务书写的是『开盘 30 分钟』，但 730 天的数据只有小时线，")
    print("  所以这里是 60 分钟。真正的 30 分钟口径只有 60 天 5 分钟线，见 8D。")
    print("  口径说明 2（重要）：所有结果都从 10:30 的价格起算、只用其后的 K 线。")
    print("  用『当日高低点』去对照首小时方向是循环论证——首小时本身就在当日高低点")
    print("  里面。本脚本的早期版本那么做时得到 z=+14，那个数字没有任何预测含义。\n")
    h1_order = ["首小时收在开盘下方", "首小时基本平收", "首小时收在开盘上方"]
    print(crosstab("8A. 首小时方向 → 余下时段结果（从 10:30 起算）", hrows,
                   lambda x: x.h1, outcomes_rest_of_day, order=h1_order))
    print()
    print(paired_table("8B. 配对：余下时段 顺首小时方向 vs 逆方向 走 0.236ATR",
                       hrows, lambda x: x.h1, h1_order, thr=K,
                       up_label="顺势", dn_label="逆势",
                       up_fn=lambda x, t: ((x.rest_mfe if "上方" in x.h1
                                            else x.rest_mae) >= t),
                       dn_fn=lambda x, t: ((x.rest_mae if "上方" in x.h1
                                            else x.rest_mfe) >= t),
                       by_era=False))
    print()
    print(dist_table("8C. 首小时方向 → 余下时段振幅/ATR（从 10:30 起算）", hrows,
                     lambda x: x.h1, lambda x: x.rest_rng, order=h1_order))

    print("\n8D. 真·前 30 分钟方向（SPY 5 分钟线，仅 60 天）\n")
    fs = data.group_by_day(data.fine("SPY"))
    tab: dict[str, list[int]] = {}
    for day in sorted(fs):
        bars = [b for b in fs[day] if "09:30" <= b.hhmm < "16:00"]
        if len(bars) < 20:
            continue
        p30 = bars[5].close
        lab = "前30分上涨" if p30 > bars[0].open else "前30分下跌"
        c = tab.setdefault(lab, [0, 0])
        c[0] += int(bars[-1].close > p30)      # rest of day, not the whole day
        c[1] += 1
    for k_, (kk, nn) in sorted(tab.items()):
        print(f"    {k_:<14} → 收盘高于 10:00 价（余下时段）  "
              f"{stats.fmt_rate(kk, nn)}")
    if len(tab) == 2:
        a, b = tab["前30分上涨"], tab["前30分下跌"]
        z = FAM.record("8D 前30分方向 → 余下时段方向 (SPY 5m, 60d)",
                       stats.two_proportion_z(a[0], a[1], b[0], b[1]),
                       a[1] + b[1])
        print(f"    z={z:+.2f} ({'做功' if abs(z) >= 1.96 else '没做功'})"
              f"   ← n≈60，功率几乎为零，这一格无论正负都不该采信")

    # ---- 9. interaction ---------------------------------------------------
    print("\n" + "=" * 78)
    print("9. 交互：跳空方向 × 首小时方向（确认 vs 反转）")
    print("=" * 78 + "\n")

    def combo(x: HourRow) -> str | None:
        g = gap_sign(x.base)
        if g is None or g.startswith("平开") or "平收" in x.h1:
            return None
        return (("高开" if "高开" in g else "低开") + " + " +
                ("首小时上" if "上方" in x.h1 else "首小时下"))

    combo_order = ["低开 + 首小时下", "低开 + 首小时上",
                   "高开 + 首小时下", "高开 + 首小时上"]
    print(crosstab("9A. 跳空 × 首小时 → 余下时段结果（从 10:30 起算）", hrows,
                   combo, outcomes_rest_of_day, order=combo_order))
    print()
    print(dist_table("9B. 跳空 × 首小时 → 余下时段振幅/ATR", hrows, combo,
                     lambda x: x.rest_rng, order=combo_order))

    print(FAM.report())


if __name__ == "__main__":
    main()
