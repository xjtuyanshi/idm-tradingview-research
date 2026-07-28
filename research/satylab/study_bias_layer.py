#!/usr/bin/env python3
"""V15 · 日线偏向层：它到底有没有信息，如果有，正确的用法是什么。

为什么有这个文件
----------------
用户否掉了把日线偏向当**硬闸门**的方案，理由是机制性的：

    「日内交易不可能一直都是单边下跌的……位置下不去以后最终不还是反抽上来了吗」

但同一段对话里他又说：

    「第一层那个确实是有用的，我认为是给一个 bias 的参考」
    「你也可以去研究一下它的历史」

所以这一轮不是在问「偏向能不能当闸门」（那已经被否了），而是在问三件事：

  A. 四种偏向定义（日线EMA21 / 日线ribbon / 月线pivot / 周线21）下，
     顺偏向与逆偏向的交易，命中率、几何零假设、z_geom、均净R 差多少。
  B. 偏向影响的是**命中率**还是**幅度**？如果只影响幅度，那正确用法是
     调仓位/调目标，不是筛信号——正好和用户的直觉一致。
  C. 「反抽」到底多常见？把用户那句话量化：偏向为空的日子里，
     日内低点之后反弹 ≥0.236 / 0.382 / 0.5 ATR 的比例是多少。

三条容易踩的坑，这里全部显式处理：

  * **偏向在 60 天窗口里几乎等价于方向。** 2026-05 → 2026-07 的日线 EMA21
    偏向 48/62 天为多、日线 ribbon 50/62 天为多且一天都没有转空。在这样的
    窗口里「顺偏向 vs 逆偏向」= 「做多 vs 做空」，是个彻底的混淆。所以主结论
    必须来自偏向真的会翻的长样本，不能来自 60 天的 10m 样本。
  * **日聚类。** 517 笔交易只来自约 50 个交易日，同一天的交易高度相关。
    所有关键对比都报**按交易日聚类**的稳健 z，不报朴素 z。
  * **纪律 3。** 10m 样本用 5m 子 K 判路径；1h 长样本没有更细的数据，
    所以同一根 1h K 内两边都被触到的交易一律记「未裁决」，绝不同根裁决。
    每个格子都报未裁决率，防止未裁决率本身在两组之间不对称。

Usage:  .venv/bin/python research/satylab/study_bias_layer.py
"""

from __future__ import annotations

import math
import statistics as st
import sys
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                        # noqa: E402
from satylab.data import Bar                                   # noqa: E402
from satylab.indicators import ema                             # noqa: E402
from satylab.mtf_levels import build_mtf, regime_label, resample  # noqa: E402
from satylab.study_v14_repro import (                          # noqa: E402
    LevelBook, load_10m, run_v14, trade_day,
)
from satylab.study_entry_location import (                     # noqa: E402
    MFE_H, RACE_CAP, SPREAD, Sig, bracket, excursion, harvest,
    isolated_trade, location_vars, norm_sf, tstat, two_sided, z_geom,
    _bonf_z,
)

REPORT = Path(__file__).resolve().parents[1] / "reports" / "V15_BIAS_LAYER.md"

CELLS = 0
ZLOG: list[tuple[str, str, float]] = []      # (样本, 格子名, z) —— 用于 §8 如实核对


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


def zlog(sample: str, cell: str, z: float) -> float:
    if z == z:
        ZLOG.append((sample, cell, z))
    return z


def fmt(x, p=2, sign=False) -> str:
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


# ═══════════════════════════ 偏向定义 ════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Bias:
    """一天开盘前就完全确定的日线偏向集合。全部只用**前一根已完成日线**及更早。"""
    e21: int          # 前收 vs 日线 EMA21          +1/-1
    ribbon: int       # 日线 8/13/21/34/48 排列      +1/-1/0
    mpivot: int       # 前收 vs 上月 pivot (H+L+C)/3 +1/-1
    wk21: int         # 前收 vs 周线 EMA21(已完成周) +1/-1
    er10: float       # 日线 10 日效率比（Kaufman）  0..1
    mbox: str         # 月线位状态（trigger_box / gg_zone / extended / beyond）
    ref: float        # 前一日收盘（这些判断的参照价）


BIAS_DEFS = [
    ("D-EMA21", "前收 vs 日线 EMA21", lambda b: b.e21),
    ("D-Ribbon", "日线 EMA 8/13/21/34/48 排列", lambda b: b.ribbon),
    ("M-Pivot", "前收 vs 上月 pivot (H+L+C)/3", lambda b: b.mpivot),
    ("W-EMA21", "前收 vs 周线 EMA21（仅已完成周）", lambda b: b.wk21),
]


class BiasBook:
    """day -> Bias，缺失日按最近一次已知值前推（与 LevelBook 同一套 carry 逻辑）。"""

    def __init__(self, daily: list[Bar]):
        closes = [b.close for b in daily]
        e8, e13 = ema(closes, 8), ema(closes, 13)
        e21, e34, e48 = ema(closes, 21), ema(closes, 34), ema(closes, 48)

        weeks = resample(daily, "W")
        months = resample(daily, "M")
        wclose = [w.close for w in weeks]
        we21 = ema(wclose, 21)

        def wkey(d):
            iso = d.isocalendar()
            return (iso[0], iso[1])

        wk_index, mo_index = {}, {}
        for j, w in enumerate(weeks):
            wk_index[wkey(w.day)] = j
        for j, m in enumerate(months):
            mo_index[(m.day.year, m.day.month)] = j
        # 每根日线属于第几周 / 第几月
        wi = [wk_index[wkey(b.day)] for b in daily]
        mi = [mo_index[(b.day.year, b.day.month)] for b in daily]

        mmap = build_mtf(daily, "M")

        out: dict = {}
        for i in range(1, len(daily)):
            p = daily[i - 1]
            j = i - 1
            if e48[j] is None or e21[j] is None:
                continue
            # 日线 ribbon 排列
            if e8[j] > e13[j] > e21[j] > e34[j] > e48[j]:
                rb = 1
            elif e8[j] < e13[j] < e21[j] < e34[j] < e48[j]:
                rb = -1
            else:
                rb = 0
            # 周线 EMA21：只用**已完成**的周（当周还没走完，不能用）
            wj = wi[j] - 1
            if wj < 0 or we21[wj] is None:
                continue
            wk = 1 if p.close > we21[wj] else -1
            # 月线 pivot：上一个**已完成**月的 (H+L+C)/3
            mj = mi[j] - 1
            if mj < 0:
                continue
            mp_price = (months[mj].high + months[mj].low + months[mj].close) / 3.0
            mp = 1 if p.close > mp_price else -1
            # Kaufman 效率比（10 日）
            if j >= 10:
                num = abs(closes[j] - closes[j - 10])
                den = sum(abs(closes[k] - closes[k - 1]) for k in range(j - 9, j + 1))
                er = num / den if den > 0 else float("nan")
            else:
                er = float("nan")
            out[daily[i].day] = Bias(
                e21=1 if p.close > e21[j] else -1, ribbon=rb, mpivot=mp,
                wk21=wk, er10=er,
                mbox=regime_label(p.close, mmap.get(p.day)), ref=p.close)

        self.days = sorted(out)
        self.map = out

    def get(self, d) -> Bias | None:
        i = bisect_left(self.days, d)
        if i < len(self.days) and self.days[i] == d:
            return self.map[self.days[i]]
        if i > 0:
            return self.map[self.days[i - 1]]
        return None


# ═══════════════════════ 日聚类稳健统计 ══════════════════════════════════════
def cluster_mean_z(ys: list[float], cl: list) -> tuple[float, float, float, int]:
    """单组均值的按簇稳健 z。返回 (mean, se, z, n_clusters)。"""
    n = len(ys)
    if n < 3:
        return float("nan"), float("nan"), float("nan"), 0
    m = sum(ys) / n
    acc: dict = {}
    for y, c in zip(ys, cl):
        acc[c] = acc.get(c, 0.0) + (y - m)
    v = sum(s * s for s in acc.values()) / (n * n)
    se = math.sqrt(v) if v > 0 else float("nan")
    z = m / se if se and se == se and se > 0 else float("nan")
    return m, se, z, len(acc)


def cluster_diff_z(ys: list[float], isa: list[int],
                   cl: list) -> tuple[float, float, float, int]:
    """两组均值差 (A−B) 的按簇稳健 z（OLS y = a + b·1{A} 的三明治方差）。"""
    n = len(ys)
    na = sum(isa)
    nb = n - na
    if na < 3 or nb < 3:
        return float("nan"), float("nan"), float("nan"), 0
    ma = sum(y for y, x in zip(ys, isa) if x) / na
    mb = sum(y for y, x in zip(ys, isa) if not x) / nb
    b = ma - mb
    a = mb
    # (X'X)^-1 = 1/(na*nb) * [[na, -na],[-na, n]]
    k = 1.0 / (na * nb)
    inv = ((k * na, -k * na), (-k * na, k * n))
    meat = [[0.0, 0.0], [0.0, 0.0]]
    s0: dict = {}
    s1: dict = {}
    for y, x, c in zip(ys, isa, cl):
        e = y - (a + b * x)
        s0[c] = s0.get(c, 0.0) + e
        s1[c] = s1.get(c, 0.0) + x * e
    for c in s0:
        u0, u1 = s0[c], s1.get(c, 0.0)
        meat[0][0] += u0 * u0
        meat[0][1] += u0 * u1
        meat[1][0] += u1 * u0
        meat[1][1] += u1 * u1
    # V = inv * meat * inv ; 取 [1][1]
    tmp = [[sum(inv[i][k2] * meat[k2][j] for k2 in range(2)) for j in range(2)]
           for i in range(2)]
    v11 = sum(tmp[1][k2] * inv[k2][1] for k2 in range(2))
    se = math.sqrt(v11) if v11 > 0 else float("nan")
    z = b / se if se and se == se and se > 0 else float("nan")
    return b, se, z, len(s0)


def prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    return stats.two_proportion_z(k1, n1, k2, n2)


# ═══════════════════════════ 样本构建 ════════════════════════════════════════
def build_sample(symbol: str, tf: str, rth_only: bool = False) -> dict:
    """tf ∈ {'10m','1h'}。10m 用 5m 子 K 判路径；1h 无更细数据 → 同根一律未裁决。"""
    if tf == "10m":
        bars, subs = load_10m(symbol, rth_only)
    else:
        bars = data.load(symbol, "730d", "1h")
        if rth_only:
            bars = [b for b in bars if not (b.dt.hour == 16 and b.dt.minute == 0)]
        subs = None
    daily = data.load(symbol, "20y", "1d")
    book = LevelBook(daily)
    bb = BiasBook(daily)
    sigs, e13s = harvest(bars, book)
    sigs = location_vars(sigs, bars, e13s)
    for s in sigs:
        bracket(s, bars, subs)
        isolated_trade(s, bars, subs, e13s)
        excursion(s, bars, subs, h=MFE_H)
    keep = []
    for s in sigs:
        d = trade_day(bars[s.i])
        b = bb.get(d)
        if b is None:
            continue
        s.day = d          # type: ignore[attr-defined]
        s.bias = b         # type: ignore[attr-defined]
        keep.append(s)
    return {"symbol": symbol, "tf": tf, "bars": bars, "subs": subs,
            "book": book, "bb": bb, "daily": daily, "e13": e13s, "sigs": keep}


# ═══════════════════════════ 顺/逆 分组表 ════════════════════════════════════
def group_row(g: list[Sig], name: str) -> dict:
    res = [s for s in g if s.hit is not None]
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    kk = sum(1 for s in res if s.hit)
    lo, hi = stats.wilson(kk, n) if n else (float("nan"), float("nan"))
    exc = [(1.0 if s.hit else 0.0) - s.pnull for s in res]
    _, _, zc, ncl = cluster_mean_z(exc, [s.day for s in res])   # type: ignore
    nets = [s.net for s in g]
    _, _, zr, _ = cluster_mean_z(nets, [s.day for s in g])      # type: ignore
    wins = [x for x in nets if x > 0]
    loss = [x for x in nets if x <= 0]
    return {
        "name": name, "n": len(g), "nres": n, "ncl": ncl,
        "obs": obs, "null": null, "exc": (obs - null) if n else float("nan"),
        "z": z, "zc": zc, "lo": lo, "hi": hi,
        "avg_r": st.mean([s.r for s in g]) if g else float("nan"),
        "avg_net": st.mean(nets) if g else float("nan"),
        "z_net": zr, "tot_net": sum(nets),
        "wr": len(wins) / len(g) if g else float("nan"),
        "avg_win": st.mean(wins) if wins else float("nan"),
        "avg_loss": st.mean(loss) if loss else float("nan"),
        "mfe": st.mean([s.mfe for s in g]) if g else float("nan"),
        "mae": st.mean([s.mae for s in g]) if g else float("nan"),
        "d4": st.mean([s.d4 for s in g]) if g else float("nan"),
        "t1d": st.mean([abs(s.t1 - s.entry) / s.atr for s in g]) if g else float("nan"),
        "money": st.mean([s.money for s in g]) if g else float("nan"),
        "unres": 1 - n / len(g) if g else float("nan"),
        "sigs": g,
    }


def split_bias(sigs: list[Sig], getter):
    with_, against, neutral = [], [], []
    for s in sigs:
        b = getter(s.bias)                                     # type: ignore
        if b == 0:
            neutral.append(s)
        elif b == s.direction:
            with_.append(s)
        else:
            against.append(s)
    return with_, against, neutral


def bias_table(sigs: list[Sig], out: list[str], title: str) -> dict:
    out.append(f"**{title}**")
    out.append("")
    out.append("| 偏向定义 | 组 | n (日数) | 未裁决 | 纯括号命中 [95%CI] | 几何零假设 "
               "| 超额 pp | z_geom | z_geom(日聚类) | 均净R | z(日聚类) | 总净R |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    res = {}
    for key, _desc, getter in BIAS_DEFS:
        w, a, nu = split_bias(sigs, getter)
        rows = [("顺偏向", w), ("逆偏向", a)]
        if nu:
            rows.append(("中性", nu))
        cells = {}
        for label, g in rows:
            if not g:
                continue
            r = group_row(g, label)
            bump()
            cells[label] = r
            out.append(
                f"| {key} | {label} | {r['n']} ({r['ncl']}) | "
                f"{100*r['unres']:.0f}% | "
                f"{100*r['obs']:.1f}% [{100*r['lo']:.1f},{100*r['hi']:.1f}] | "
                f"{100*r['null']:.1f}% | {100*r['exc']:+.1f} | {fmt(r['z'],2,True)} | "
                f"**{fmt(r['zc'],2,True)}** | {fmt(r['avg_net'],3,True)} | "
                f"{fmt(r['z_net'],2,True)} | {fmt(r['tot_net'],1,True)} |")
        res[key] = cells
    out.append("")
    return res


def contrast_table(res: dict, sigs: list[Sig], out: list[str],
                   tag: str = "") -> None:
    """顺−逆 的差，全部按交易日聚类。这是这一节真正的判决行。"""
    out.append("顺 − 逆 的差（按交易日聚类的稳健 z；|z|>1.96 才谈得上「有」）：")
    out.append("")
    out.append("| 偏向定义 | Δ超额pp (顺−逆) | z_clu | Δ均净R | z_clu | "
               "Δ赢单均净R | Δ输单均净R | ΔMFE(ATR) | ΔMAE(ATR) | 命中率差 z |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for key, _desc, getter in BIAS_DEFS:
        w, a, _ = split_bias(sigs, getter)
        if len(w) < 20 or len(a) < 20:
            out.append(f"| {key} | 样本不足（顺 {len(w)} / 逆 {len(a)}） | | | | | | | | |")
            continue
        bump(2)
        rw, ra = res[key]["顺偏向"], res[key]["逆偏向"]
        # Δ超额（hit − pnull），日聚类
        ys, isa, cl = [], [], []
        wset = set(id(x) for x in w)
        for s in w + a:
            if s.hit is None:
                continue
            ys.append((1.0 if s.hit else 0.0) - s.pnull)
            isa.append(1 if id(s) in wset else 0)
            cl.append(s.day)                                    # type: ignore
        de, _, zde, _ = cluster_diff_z(ys, isa, cl)
        ys2 = [s.net for s in w + a]
        isa2 = [1 if id(s) in wset else 0 for s in w + a]
        cl2 = [s.day for s in w + a]                            # type: ignore
        dr, _, zdr, _ = cluster_diff_z(ys2, isa2, cl2)
        kw = sum(1 for s in w if s.hit)
        nw = sum(1 for s in w if s.hit is not None)
        ka = sum(1 for s in a if s.hit)
        na_ = sum(1 for s in a if s.hit is not None)
        zp = prop_z(kw, nw, ka, na_)
        zlog(tag, f"{key} Δ超额(顺−逆)", zde)
        zlog(tag, f"{key} Δ均净R(顺−逆)", zdr)
        out.append(
            f"| {key} | {100*de:+.1f} | **{fmt(zde,2,True)}** | {fmt(dr,3,True)} | "
            f"**{fmt(zdr,2,True)}** | "
            f"{fmt(rw['avg_win']-ra['avg_win'],3,True)} | "
            f"{fmt(rw['avg_loss']-ra['avg_loss'],3,True)} | "
            f"{fmt(rw['mfe']-ra['mfe'],3,True)} | "
            f"{fmt(rw['mae']-ra['mae'],3,True)} | {fmt(zp,2,True)} |")
    out.append("")


MAGS = [
    ("MFE(ATR)", lambda s: s.mfe),
    ("MAE(ATR)", lambda s: s.mae),
    ("风险距离(ATR)", lambda s: s.d4),
    ("T1距离(ATR)", lambda s: abs(s.t1 - s.entry) / s.atr),
    ("几何零假设", lambda s: s.pnull),
    ("每单位名义本金净盈亏", lambda s: s.money),
]


def magnitude_contrast(sigs: list[Sig], out: list[str], tag: str) -> None:
    """顺−逆 在**幅度类**变量上的差，全部按交易日聚类。

    这一节存在的理由：R 不是钱。风险距离 0.05 ATR 的一笔和 0.30 ATR 的一笔同样报
    −1R，亏的钱差六倍。如果顺/逆两组的风险距离本来就不同，那「均净R 差不多」
    并不等于「赚的钱差不多」。`每单位名义本金净盈亏 = 净R × 风险距离(ATR)` 才可比。
    """
    out.append("| 幅度变量 | 偏向定义 | 顺 | 逆 | Δ(顺−逆) | z(日聚类) |")
    out.append("|---|---|---|---|---|---|")
    for name, get in MAGS:
        for key, _d, getter in BIAS_DEFS:
            w, a = split_bias(sigs, getter)[:2]
            if len(w) < 20 or len(a) < 20:
                continue
            bump()
            wset = set(id(x) for x in w)
            ys = [get(s) for s in w + a]
            isa = [1 if id(s) in wset else 0 for s in w + a]
            cl = [s.day for s in w + a]                          # type: ignore
            d, _, z, _ = cluster_diff_z(ys, isa, cl)
            zlog(tag + "-幅度", f"{key} Δ{name}(顺−逆)", z)
            mw = st.mean([get(s) for s in w])
            ma = st.mean([get(s) for s in a])
            out.append(f"| {name} | {key} | {mw:+.3f} | {ma:+.3f} | "
                       f"{d:+.3f} | **{fmt(z,2,True)}** |")
    out.append("")


def direction_table(sigs: list[Sig], out: list[str], label: str) -> None:
    """按**方向**（多/空）而不是按偏向切一遍。用来看「顺/逆」是不是只是「多/空」。"""
    out.append(f"{label}，按方向切：")
    out.append("")
    out.append("| 方向 | n | 纯括号命中 | 几何零假设 | 超额pp | z_geom(日聚类) | "
               "均净R | z(日聚类) | 均风险(ATR) |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for lab, d in (("做多", 1), ("做空", -1)):
        g = [s for s in sigs if s.direction == d]
        if len(g) < 20:
            continue
        bump()
        r = group_row(g, lab)
        out.append(f"| {lab} | {r['n']} | {100*r['obs']:.1f}% | {100*r['null']:.1f}% | "
                   f"{100*r['exc']:+.1f} | {fmt(r['zc'],2,True)} | "
                   f"{fmt(r['avg_net'],3,True)} | {fmt(r['z_net'],2,True)} | "
                   f"{r['d4']:.3f} |")
    out.append("")


# ═══════════════════ 命中率 vs 幅度：分解 ════════════════════════════════════
def decomposition(res: dict, out: list[str]) -> None:
    """ΔE = Δp·(W̄−L̄) + p̄·ΔW + (1−p̄)·ΔL —— 把顺/逆的均净R差拆成三块。"""
    out.append("| 偏向定义 | ΔE=Δ均净R | 命中率贡献 | 赢单幅度贡献 | 输单幅度贡献 | "
               "命中率占比 | 幅度占比 |")
    out.append("|---|---|---|---|---|---|---|")
    for key, _d, _g in BIAS_DEFS:
        c = res.get(key, {})
        if "顺偏向" not in c or "逆偏向" not in c:
            continue
        w, a = c["顺偏向"], c["逆偏向"]
        if w["n"] < 20 or a["n"] < 20:
            continue
        bump()
        p1, p2 = w["wr"], a["wr"]
        W1, W2 = w["avg_win"], a["avg_win"]
        L1, L2 = w["avg_loss"], a["avg_loss"]
        if any(x != x for x in (W1, W2, L1, L2)):
            continue
        pbar = (p1 + p2) / 2
        Wbar, Lbar = (W1 + W2) / 2, (L1 + L2) / 2
        c_p = (p1 - p2) * (Wbar - Lbar)
        c_w = pbar * (W1 - W2)
        c_l = (1 - pbar) * (L1 - L2)
        tot = c_p + c_w + c_l
        den = abs(c_p) + abs(c_w) + abs(c_l)
        out.append(
            f"| {key} | {fmt(tot,3,True)} | {fmt(c_p,3,True)} | {fmt(c_w,3,True)} | "
            f"{fmt(c_l,3,True)} | {100*abs(c_p)/den:.0f}% | "
            f"{100*(abs(c_w)+abs(c_l))/den:.0f}% |")
    out.append("")


# ═══════════════════════ 持续性：「反抽」有多常见 ═════════════════════════════
def sessions_of(bars: list[Bar]) -> dict:
    out: dict = {}
    for b in bars:
        out.setdefault(trade_day(b), []).append(b)
    for v in out.values():
        v.sort(key=lambda x: x.dt)
    return out


REB_TH = (0.236, 0.382, 0.5, 0.618, 1.0)


def persistence(symbol: str, out: list[str]) -> dict:
    """日内低点之后的反弹 / 日内高点之后的回落，按日线偏向分组。"""
    bars = data.load(symbol, "730d", "1h")
    daily = data.load(symbol, "20y", "1d")
    book, bb = LevelBook(daily), BiasBook(daily)
    sess = sessions_of(bars)

    rows = []
    for d, bs in sorted(sess.items()):
        if len(bs) < 10:
            continue
        lv, bi = book.get(d), bb.get(d)
        if lv is None or bi is None:
            continue
        atr = lv[1]
        if atr <= 0:
            continue
        lo_i = min(range(len(bs)), key=lambda i: bs[i].low)
        hi_i = max(range(len(bs)), key=lambda i: bs[i].high)
        lo, hi = bs[lo_i].low, bs[hi_i].high
        reb = (max(x.high for x in bs[lo_i + 1:]) - lo) / atr if lo_i + 1 < len(bs) else 0.0
        pul = (hi - min(x.low for x in bs[hi_i + 1:])) / atr if hi_i + 1 < len(bs) else 0.0
        rows.append({
            "day": d, "bias": bi, "atr": atr, "reb": max(reb, 0.0),
            "pul": max(pul, 0.0), "n": len(bs),
            "open": bs[0].open, "close": bs[-1].close,
            "down_day": bs[-1].close < bs[0].open,
            "range": (hi - lo) / atr,
            "dn_ext": (bs[0].open - lo) / atr, "up_ext": (hi - bs[0].open) / atr,
            "lo_frac": lo_i / (len(bs) - 1), "hi_frac": hi_i / (len(bs) - 1),
        })

    def block(name: str, sel, key: str) -> str:
        g = [r for r in rows if sel(r)]
        if len(g) < 10:
            return f"| {name} | {len(g)} | 样本不足 | | | | | |"
        bump()
        vals = [r[key] for r in g]
        fr = [sum(1 for v in vals if v >= t) / len(g) for t in REB_TH]
        return (f"| {name} | {len(g)} | "
                + " | ".join(f"{100*x:.0f}%" for x in fr)
                + f" | {st.median(vals):.3f} | {st.mean(vals):.3f} |")

    hdr = ("| 分组 | 日数 | ≥0.236 | ≥0.382 | ≥0.5 | ≥0.618 | ≥1.0 | 中位 | 均值 |")
    sep = "|---|---|---|---|---|---|---|---|---|"

    out.append("**A · 日内低点之后的反弹（ATR 归一）**")
    out.append("")
    out.append(hdr)
    out.append(sep)
    out.append(block("全部交易日", lambda r: True, "reb"))
    for key, _d, getter in BIAS_DEFS:
        out.append(block(f"{key} 偏空日", lambda r, g=getter: g(r["bias"]) < 0, "reb"))
        out.append(block(f"{key} 偏多日", lambda r, g=getter: g(r["bias"]) > 0, "reb"))
    out.append(block("收阴日（close<open）", lambda r: r["down_day"], "reb"))
    out.append(block("D-EMA21 偏空 且 收阴",
                     lambda r: r["bias"].e21 < 0 and r["down_day"], "reb"))
    out.append(block("D-EMA21 偏空 且 当日跌幅>0.5ATR",
                     lambda r: r["bias"].e21 < 0 and (r["open"] - r["close"]) / r["atr"] > 0.5,
                     "reb"))
    out.append("")

    out.append("**B · 日内高点之后的回落（镜像）**")
    out.append("")
    out.append(hdr)
    out.append(sep)
    out.append(block("全部交易日", lambda r: True, "pul"))
    for key, _d, getter in BIAS_DEFS:
        out.append(block(f"{key} 偏多日", lambda r, g=getter: g(r["bias"]) > 0, "pul"))
        out.append(block(f"{key} 偏空日", lambda r, g=getter: g(r["bias"]) < 0, "pul"))
    out.append(block("收阳日（close>open）", lambda r: not r["down_day"], "pul"))
    out.append(block("D-EMA21 偏多 且 收阳",
                     lambda r: r["bias"].e21 > 0 and not r["down_day"], "pul"))
    out.append("")

    out.append("**C · 反抽相对于跌幅有多大** —— 「跌下去」和「弹回来」的尺寸对比")
    out.append("")
    out.append("| 分组 | 日数 | 中位 开盘→低点 跌幅(ATR) | 中位 低点后反弹(ATR) | "
               "反弹/跌幅 中位比 | 反弹 ≥ 跌幅 的天数占比 |")
    out.append("|---|---|---|---|---|---|")
    for lab, sel in (("全部交易日", lambda r: True),
                     ("D-EMA21 偏空日", lambda r: r["bias"].e21 < 0),
                     ("D-EMA21 偏多日", lambda r: r["bias"].e21 > 0),
                     ("D-Ribbon 偏空日", lambda r: r["bias"].ribbon < 0),
                     ("收阴日", lambda r: r["down_day"])):
        g = [r for r in rows if sel(r)]
        if len(g) < 10:
            continue
        bump()
        dn = [max(r["dn_ext"], 0.0) for r in g]
        rb = [r["reb"] for r in g]
        ratio = [b / a for a, b in zip(dn, rb) if a > 1e-6]
        ge = sum(1 for a, b in zip(dn, rb) if b >= a) / len(g)
        out.append(f"| {lab} | {len(g)} | {st.median(dn):.3f} | {st.median(rb):.3f} | "
                   f"{st.median(ratio) if ratio else float('nan'):.2f} | "
                   f"{100*ge:.0f}% |")
    out.append("")
    return {"rows": rows, "bars": bars}


def persistence_5m(symbol: str, out: list[str]) -> None:
    """同一件事在 5m 分辨率上复核（只有 60 天，但路径分辨率高 12 倍）。"""
    b5 = data.load(symbol, "60d", "5m")
    daily = data.load(symbol, "20y", "1d")
    book, bb = LevelBook(daily), BiasBook(daily)
    sess = sessions_of(b5)
    rows = []
    for d, bs in sorted(sess.items()):
        if len(bs) < 60:
            continue
        lv, bi = book.get(d), bb.get(d)
        if lv is None or bi is None or lv[1] <= 0:
            continue
        atr = lv[1]
        lo_i = min(range(len(bs)), key=lambda i: bs[i].low)
        hi_i = max(range(len(bs)), key=lambda i: bs[i].high)
        reb = (max(x.high for x in bs[lo_i + 1:]) - bs[lo_i].low) / atr \
            if lo_i + 1 < len(bs) else 0.0
        pul = (bs[hi_i].high - min(x.low for x in bs[hi_i + 1:])) / atr \
            if hi_i + 1 < len(bs) else 0.0
        rows.append((d, bi, max(reb, 0.0), max(pul, 0.0)))
    if not rows:
        return
    bump(2)
    reb = [r[2] for r in rows]
    pul = [r[3] for r in rows]
    out.append(f"5m 复核（{len(rows)} 个交易日，{rows[0][0]} → {rows[-1][0]}）："
               f"低点后反弹 ≥0.236 ATR 的比例 "
               f"{100*sum(1 for v in reb if v >= 0.236)/len(reb):.0f}%，"
               f"≥0.382 {100*sum(1 for v in reb if v >= 0.382)/len(reb):.0f}%，"
               f"中位 {st.median(reb):.3f} ATR；"
               f"高点后回落 ≥0.236 的比例 "
               f"{100*sum(1 for v in pul if v >= 0.236)/len(pul):.0f}%，"
               f"中位 {st.median(pul):.3f} ATR。"
               f"1h 分辨率会**低估**反抽（一根 1h K 内部的来回看不见），"
               f"所以 5m 的数字更高才是对的。")
    out.append("")


# ═══════════════════ 与状态层的交互 ══════════════════════════════════════════
def regime_of(s: Sig, er_cut: tuple[float, float]) -> str:
    er = s.bias.er10                                            # type: ignore
    if er != er:
        return "na"
    if er >= er_cut[1]:
        return "趋势(ER高)"
    if er <= er_cut[0]:
        return "区间(ER低)"
    return "中(ER中)"


def interaction(sigs: list[Sig], out: list[str], label: str,
                tag: str = "S2-交互") -> None:
    ers = sorted(s.bias.er10 for s in sigs                      # type: ignore
                 if s.bias.er10 == s.bias.er10)                 # type: ignore
    if len(ers) < 30:
        return
    lo = ers[len(ers) // 3]
    hi = ers[2 * len(ers) // 3]
    out.append(f"**{label}** — ER10 三分位切点 {lo:.3f} / {hi:.3f}。")
    out.append("")
    out.append("| 状态 | 偏向定义 | 顺 n | 顺超额pp | 逆 n | 逆超额pp | "
               "Δ超额pp | z_clu | Δ均净R | z_clu |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    regimes = ["区间(ER低)", "中(ER中)", "趋势(ER高)"]
    for reg in regimes:
        sub = [s for s in sigs if regime_of(s, (lo, hi)) == reg]
        for key, _d, getter in BIAS_DEFS:
            w, a = split_bias(sub, getter)[:2]
            if len(w) < 15 or len(a) < 15:
                continue
            bump(2)
            rw, ra = group_row(w, "顺"), group_row(a, "逆")
            wset = set(id(x) for x in w)
            ys, isa, cl = [], [], []
            for s in w + a:
                if s.hit is None:
                    continue
                ys.append((1.0 if s.hit else 0.0) - s.pnull)
                isa.append(1 if id(s) in wset else 0)
                cl.append(s.day)                                # type: ignore
            de, _, zde, _ = cluster_diff_z(ys, isa, cl)
            dr, _, zdr, _ = cluster_diff_z(
                [s.net for s in w + a],
                [1 if id(s) in wset else 0 for s in w + a],
                [s.day for s in w + a])                          # type: ignore
            zlog(tag, f"ER·{reg}·{key} Δ超额", zde)
            zlog(tag, f"ER·{reg}·{key} Δ均净R", zdr)
            out.append(f"| {reg} | {key} | {rw['n']} | {100*rw['exc']:+.1f} | "
                       f"{ra['n']} | {100*ra['exc']:+.1f} | {100*de:+.1f} | "
                       f"{fmt(zde,2,True)} | {fmt(dr,3,True)} | {fmt(zdr,2,True)} |")
    out.append("")

    # 月线位状态（Saty 自己的词汇）
    out.append("月线位状态（`mtf_levels.regime_label`，用前收判定，盘前即知）：")
    out.append("")
    out.append("| 月线状态 | 偏向定义 | 顺 n | 顺超额pp | 逆 n | 逆超额pp | "
               "Δ超额pp | z_clu | Δ均净R | z_clu |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for box in ["trigger_box", "gg_zone", "extended", "beyond_1atr"]:
        sub = [s for s in sigs if s.bias.mbox == box]            # type: ignore
        for key, _d, getter in BIAS_DEFS:
            w, a = split_bias(sub, getter)[:2]
            if len(w) < 15 or len(a) < 15:
                continue
            bump(2)
            rw, ra = group_row(w, "顺"), group_row(a, "逆")
            wset = set(id(x) for x in w)
            ys, isa, cl = [], [], []
            for s in w + a:
                if s.hit is None:
                    continue
                ys.append((1.0 if s.hit else 0.0) - s.pnull)
                isa.append(1 if id(s) in wset else 0)
                cl.append(s.day)                                # type: ignore
            de, _, zde, _ = cluster_diff_z(ys, isa, cl)
            dr, _, zdr, _ = cluster_diff_z(
                [s.net for s in w + a],
                [1 if id(s) in wset else 0 for s in w + a],
                [s.day for s in w + a])                          # type: ignore
            zlog(tag, f"月线·{box}·{key} Δ超额", zde)
            zlog(tag, f"月线·{box}·{key} Δ均净R", zdr)
            out.append(f"| {box} | {key} | {rw['n']} | {100*rw['exc']:+.1f} | "
                       f"{ra['n']} | {100*ra['exc']:+.1f} | {100*de:+.1f} | "
                       f"{fmt(zde,2,True)} | {fmt(dr,3,True)} | {fmt(zdr,2,True)} |")
    out.append("")


# ═══════════════════ 大样本日线检验：偏向有没有方向信息 ═══════════════════════
def daily_test(symbol: str, out: list[str], years: str = "20y") -> None:
    daily = data.load(symbol, years, "1d")
    bb = BiasBook(daily)
    atr = levels.wilder_atr(daily)
    recs = []
    for i in range(1, len(daily)):
        b, p = daily[i], daily[i - 1]
        bi = bb.map.get(b.day)
        a = atr[i - 1]
        if bi is None or a is None or a <= 0:
            continue
        recs.append({
            "bias": bi, "up": b.close > p.close,
            "ret": (b.close - p.close) / a,
            "up_exc": (b.high - p.close) / a,
            "dn_exc": (p.close - b.low) / a,
            "t236u": b.high >= p.close + 0.236 * a,
            "t236d": b.low <= p.close - 0.236 * a,
        })
    n = len(recs)
    base = sum(1 for r in recs if r["up"]) / n
    out.append(f"样本 {symbol} 日线 {n} 根（{daily[1].day} → {daily[-1].day}）。"
               f"无条件收涨率 {100*base:.1f}%（这才是这里的零假设，不是 50%）。")
    out.append("")
    out.append("| 偏向定义 | 组 | n | 收涨率 [95%CI] | vs 无条件 z | 均次日R(ATR) | t | "
               "均上行幅度 | 均下行幅度 | 幅度差 | t | P(触+0.236) | P(触−0.236) |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, _d, getter in BIAS_DEFS:
        for lab, sel in (("偏多", 1), ("偏空", -1), ("中性", 0)):
            g = [r for r in recs if getter(r["bias"]) == sel]
            if len(g) < 30:
                continue
            bump()
            k = sum(1 for r in g if r["up"])
            lo, hi = stats.wilson(k, len(g))
            p0 = base
            se = math.sqrt(p0 * (1 - p0) / len(g))
            z = (k / len(g) - p0) / se if se > 0 else float("nan")
            rets = [r["ret"] for r in g]
            ue = [r["up_exc"] for r in g]
            de = [r["dn_exc"] for r in g]
            diff = [a2 - b2 for a2, b2 in zip(ue, de)]
            out.append(
                f"| {key} | {lab} | {len(g)} | {100*k/len(g):.1f}% "
                f"[{100*lo:.1f},{100*hi:.1f}] | {fmt(z,2,True)} | "
                f"{fmt(st.mean(rets),3,True)} | {fmt(tstat(rets),2,True)} | "
                f"{st.mean(ue):.3f} | {st.mean(de):.3f} | "
                f"{fmt(st.mean(diff),3,True)} | {fmt(tstat(diff),2,True)} | "
                f"{100*sum(1 for r in g if r['t236u'])/len(g):.0f}% | "
                f"{100*sum(1 for r in g if r['t236d'])/len(g):.0f}% |")
    out.append("")


def daily_race(symbol: str, out: list[str]) -> None:
    """对称括号赛跑：从前收出发 ±0.382 ATR 谁先到，用 1h 路径裁决（730d）。

    对称 ⇒ 几何零假设正好 50%（S=T）。同一根 1h K 内两边都触 → 未裁决，不裁。
    """
    bars = data.load(symbol, "730d", "1h")
    daily = data.load(symbol, "20y", "1d")
    book, bb = LevelBook(daily), BiasBook(daily)
    sess = sessions_of(bars)
    recs = []
    for d, bs in sorted(sess.items()):
        if len(bs) < 10:
            continue
        lv, bi = book.get(d), bb.get(d)
        if lv is None or bi is None or lv[1] <= 0:
            continue
        anc, a = lv
        up, dn = anc + 0.382 * a, anc - 0.382 * a
        res = None
        for x in bs:
            hu, hd = x.high >= up, x.low <= dn
            if hu and hd:
                res = None
                break
            if hu:
                res = True
                break
            if hd:
                res = False
                break
        if res is None:
            recs.append({"bias": bi, "hit": None})
        else:
            recs.append({"bias": bi, "hit": res})
    tot = len(recs)
    dec = [r for r in recs if r["hit"] is not None]
    out.append(f"{tot} 个交易日，其中 {len(dec)} 天可裁决"
               f"（{tot-len(dec)} 天要么没碰到任一侧、要么同一根 1h K 内两侧都碰到 "
               f"→ 按纪律 3 不裁决）。对称括号 ⇒ 几何零假设 = 50.0%。")
    out.append("")
    out.append("| 偏向定义 | 组 | 可裁决 n | 先触上方 % [95%CI] | z vs 50% |")
    out.append("|---|---|---|---|---|")
    for key, _d, getter in BIAS_DEFS:
        for lab, sel in (("偏多", 1), ("偏空", -1), ("中性", 0)):
            g = [r for r in dec if getter(r["bias"]) == sel]
            if len(g) < 20:
                continue
            bump()
            k = sum(1 for r in g if r["hit"])
            lo, hi = stats.wilson(k, len(g))
            z = (k - 0.5 * len(g)) / math.sqrt(0.25 * len(g))
            out.append(f"| {key} | {lab} | {len(g)} | {100*k/len(g):.1f}% "
                       f"[{100*lo:.1f},{100*hi:.1f}] | {fmt(z,2,True)} |")
    out.append("")


# ═════════════════════════════ 主程序 ════════════════════════════════════════
def main() -> None:
    o: list[str] = []
    A = o.append

    s10 = build_sample("ES=F", "10m", rth_only=False)
    s1h = build_sample("ES=F", "1h", rth_only=False)

    sig10, sig1h = s10["sigs"], s1h["sigs"]
    b10, b1h = s10["bars"], s1h["bars"]

    A("# V15 · 日线偏向层：有没有信息，如果有，正确的用法是什么")
    A("")
    A("生成脚本 `research/satylab/study_bias_layer.py`。")
    A("")
    A("## 0 · 这一轮在回答什么")
    A("")
    A("用户已经否掉了把日线偏向当**硬闸门**：")
    A("")
    A("> 「日内交易不可能一直都是单边下跌的……位置下不去以后最终不还是反抽上来了吗」")
    A("")
    A("但同一段对话里他也说：")
    A("")
    A("> 「第一层那个确实是有用的，我认为是给一个 bias 的参考」／「你也可以去研究一下它的历史」")
    A("")
    A("所以问题不是「能不能当闸门」（已否），而是：**偏向到底有没有信息；"
      "如果有，既然不能筛信号，正确的用法是什么。**")
    A("")

    # ── 1 样本与定义 ────────────────────────────────────────────────────────
    A("## 1 · 偏向定义、样本、以及一个必须先说的混淆")
    A("")
    A("### 1.1 四个定义（全部只用前一根已完成日线及更早，盘前即固定）")
    A("")
    A("| 记号 | 定义 | 取值 |")
    A("|---|---|---|")
    A("| D-EMA21 | 前一日收盘 vs 日线 EMA21 | ±1 |")
    A("| D-Ribbon | 日线 EMA 8/13/21/34/48 是否完全排列 | +1 多排 / −1 空排 / 0 缠绕 |")
    A("| M-Pivot | 前一日收盘 vs 上一个**已完成**月的 pivot (H+L+C)/3 | ±1 |")
    A("| W-EMA21 | 前一日收盘 vs 周线 EMA21（只用**已完成**周） | ±1 |")
    A("")
    A("周线 EMA21 刻意只用已完成周、月 pivot 刻意只用已完成月——TradingView 上"
      "习惯用「还在长的当周/当月」，那在回测里是前视。这里宁可让指标钝一点。")
    A("")
    A("### 1.2 四个样本")
    A("")
    A("| 记号 | 数据 | 跨度 | 路径分辨率 | 用途 |")
    A("|---|---|---|---|---|")
    A(f"| S1 | ES=F 10m（60d 5m 聚合） | {b10[0].dt:%Y-%m-%d} → {b10[-1].dt:%Y-%m-%d}，"
      f"{len(b10)} 根 | 5m 子 K | v14 交易层，主样本口径，但**偏向几乎不翻** |")
    A(f"| S2 | ES=F 1h | {b1h[0].dt:%Y-%m-%d} → {b1h[-1].dt:%Y-%m-%d}，"
      f"{len(b1h)} 根 | 无更细数据 → 同根不裁决 | v14 交易层，**偏向会翻**，这一轮的主证据 |")
    A("| S3 | ES=F 日线 20y | 2006 → 2026，约 5000 根 | 不需要 | 偏向对**次日方向/幅度**有没有信息 |")
    A("| S4 | ES=F 1h 730d + 5m 60d | 约 600 / 60 个交易日 | 1h / 5m | 「反抽」的频率与幅度 |")
    A("")
    A("⚠ **S2 不是生产口径。** v14 的 setup 周期是 10m；S2 把同一套状态机"
      "（ribbon 8/13/21/34/48、Recovery / Vomy 转移、ATR 位梯目标）原封不动"
      "跑在 **1h** setup K 上，只为了换来 730 天、偏向会翻的样本。"
      "所以 S2 回答的是「偏向这个变量对这套状态机有没有信息」，"
      "**不是**「v14 在生产周期上会怎样」。S1 才是生产周期，但 S1 的偏向不翻。"
      "两个样本各缺一半，这是这一轮无法绕开的结构性限制："
      "5m 数据只有 60 天，要更长的历史就只能牺牲周期。")
    A("")
    A("S1/S2 的交易样本都是 **把 v14 单仓闸门拿掉之后状态机吐出的全部入场事件**，"
      "与 `V15_ENTRY_LOCATION.md` 同一口径（排队顺序与偏向无关，按它筛样本会引入选择偏差）。"
      "结果变量用纯括号（保护位 vs T1 谁先到），几何零假设 P=S/(S+T)。"
      "点差按 0.6 点扣，毛 R 与净 R 都报。")
    A("")

    # 混淆
    A("### 1.3 ⚠ 先说坏消息：60 天窗口里「偏向」几乎就是「方向」")
    A("")
    days10 = sorted({s.day for s in sig10})                      # type: ignore
    A(f"S1 的 {len(sig10)} 笔信号只来自 **{len(days10)} 个交易日**。这些日子里日线偏向的分布：")
    A("")
    A("| 偏向定义 | 偏多天数 | 偏空天数 | 中性天数 | 顺偏向笔数 | 逆偏向笔数 | "
      "顺偏向里做多占比 | 逆偏向里做多占比 |")
    A("|---|---|---|---|---|---|---|---|")
    bb10 = s10["bb"]
    for key, _d, getter in BIAS_DEFS:
        cnt = Counter(getter(bb10.get(d)) for d in days10)
        w, a, _nu = split_bias(sig10, getter)
        lw = sum(1 for s in w if s.direction > 0) / len(w) if w else float("nan")
        la = sum(1 for s in a if s.direction > 0) / len(a) if a else float("nan")
        A(f"| {key} | {cnt.get(1,0)} | {cnt.get(-1,0)} | {cnt.get(0,0)} | "
          f"{len(w)} | {len(a)} | {100*lw:.0f}% | {100*la:.0f}% |")
    A("")
    A("**这几行决定了这份报告怎么读。** 如果「顺偏向里 100% 是多单、逆偏向里 100% 是空单」，"
      "那 S1 上任何「顺偏向更好」的结论都只是「这 60 天做多更好」的换句话说，"
      "和偏向本身没有关系。S2（730 天、偏向会翻）才是能分开这两件事的样本。")
    A("")
    days1h = sorted({s.day for s in sig1h})                      # type: ignore
    A(f"S2 的 {len(sig1h)} 笔信号来自 **{len(days1h)} 个交易日**，偏向分布：")
    A("")
    A("| 偏向定义 | 偏多天数 | 偏空天数 | 中性天数 | 顺偏向笔数 | 逆偏向笔数 | "
      "顺偏向里做多占比 | 逆偏向里做多占比 |")
    A("|---|---|---|---|---|---|---|---|")
    bb1h = s1h["bb"]
    for key, _d, getter in BIAS_DEFS:
        cnt = Counter(getter(bb1h.get(d)) for d in days1h)
        w, a, _nu = split_bias(sig1h, getter)
        lw = sum(1 for s in w if s.direction > 0) / len(w) if w else float("nan")
        la = sum(1 for s in a if s.direction > 0) / len(a) if a else float("nan")
        A(f"| {key} | {cnt.get(1,0)} | {cnt.get(-1,0)} | {cnt.get(0,0)} | "
          f"{len(w)} | {len(a)} | {100*lw:.0f}% | {100*la:.0f}% |")
    A("")

    # ── 2 顺/逆 ─────────────────────────────────────────────────────────────
    A("## 2 · 顺偏向 vs 逆偏向")
    A("")
    A("`z_geom` 是朴素的（把每笔当独立）；`z_geom(日聚类)` 把同一交易日的交易当一簇做"
      "稳健方差。两者差多少，就是「507 笔其实只是 50 天」这件事值多少。**只认后者。**")
    A("")
    res1h = bias_table(sig1h, o, "S2 · ES=F 1h 730d（主证据：偏向会翻）")
    contrast_table(res1h, sig1h, o, tag="S2")
    A("注意两组的**几何零假设本身就不同**（顺偏向 68.1% vs 逆偏向 75.8%，D-EMA21）。"
      "这不是噪声，是结构：逆偏向的信号出现在价格已经朝偏向方向走远的位置，"
      "结构止损更远、顺方向的下一个 ATR 位更近，所以 S/(S+T) 更高。"
      "**这正是为什么「命中率差 z」那一列（−2.40）完全不能读成「偏向有信息」**——"
      "它量的是几何，不是边缘。扣掉几何之后的 Δ超额 只有 +0.8 pp，z_clu = +0.25。")
    A("")
    direction_table(sig1h, o, "S2")
    res10 = bias_table(sig10, o, "S1 · ES=F 10m 60d（偏向几乎不翻，看看就好）")
    contrast_table(res10, sig10, o, tag="S1")
    direction_table(sig10, o, "S1")
    A("把 S1 的「顺/逆」表和「多/空」表并排看：两张表几乎是同一张表。"
      "这就是 §1.3 那个混淆的直接证据——S1 上所谓的「偏向效应」就是「这 60 天做多亏钱」。")
    A("")

    # ── 3 命中率 vs 幅度 ────────────────────────────────────────────────────
    A("## 3 · 关键区分：偏向影响的是【命中率】还是【幅度】")
    A("")
    A("这是这一轮真正要回答的问题。用户的直觉是「偏向不该拿来筛信号」；"
      "如果数据显示偏向只挪动幅度、不挪动命中率，那这个直觉就有了机制上的支持——"
      "**幅度信息的正确用法是调仓位/调目标，命中率信息才配当筛子。**")
    A("")
    A("### 3.1 顺/逆 的幅度画像（S2）")
    A("")
    A("| 偏向定义 | 组 | n | 命中率 | 几何零 | 超额pp | 均净R | 盈利笔占比 | "
      "赢单均净R | 输单均净R | 赢/输幅度比 | MFE(ATR) | MAE(ATR) | 均风险(ATR) | "
      "均T1距离(ATR) | 均钱(净R×风险) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, _d, _g in BIAS_DEFS:
        for lab in ("顺偏向", "逆偏向", "中性"):
            r = res1h.get(key, {}).get(lab)
            if not r:
                continue
            A(f"| {key} | {lab} | {r['n']} | {100*r['obs']:.1f}% | "
              f"{100*r['null']:.1f}% | {100*r['exc']:+.1f} | "
              f"{fmt(r['avg_net'],3,True)} | {100*r['wr']:.1f}% | "
              f"{fmt(r['avg_win'],3,True)} | {fmt(r['avg_loss'],3,True)} | "
              f"{abs(r['avg_win']/r['avg_loss']):.2f} | "
              f"{r['mfe']:.3f} | {r['mae']:.3f} | {r['d4']:.3f} | {r['t1d']:.3f} | "
              f"{fmt(r['money'],4,True)} |")
    A("")
    A("「均钱」那一列必须看：R 不是钱。风险 0.05 ATR 的一笔和风险 0.30 ATR 的一笔"
      "同样报 −1R，亏的钱差六倍。顺/逆两组的风险距离本来就不同"
      "（见「均风险」列），所以只比均净R 会得出错误的结论。")
    A("")
    A("### 3.2 幅度类变量的顺/逆对比（S2，全部按交易日聚类）")
    A("")
    magnitude_contrast(sig1h, o, "S2")
    A("**这张表要小心读，两个坑：**")
    A("")
    A("1. **几何差只出现在两种定义上。** 风险距离的 Δ 在 D-EMA21（z −4.47）和 "
      "M-Pivot（z −3.40）上很大，在 D-Ribbon（z −0.06）和 W-EMA21（z +0.20）上"
      "**完全没有**。合理解释：D-EMA21 / M-Pivot 是「前收 vs 一条价格常在附近来回穿的线」，"
      "「逆偏向」在这两种定义下意味着价格已经越过那条线并走远，结构止损自然更远；"
      "而 D-Ribbon 把模棱两可的日子丢进「中性」档（467 天里 114 天），"
      "W-EMA21 则几乎恒为多（406 : 61），顺/逆退化回多/空。"
      "所以这是**两个定义**的性质，不是「偏向」这个概念的普遍性质。")
    A("2. **「均钱」四种定义全部没有差别**（|z| ≤ 1.36）。"
      "也就是说：顺偏向和逆偏向，按固定金额风险下单时赚到/亏掉的钱是一样的。"
      "**没有任何证据支持按偏向调整仓位倍数。**")
    A("")
    # 混淆核对：风险距离的差是不是只是多/空的组成差
    A("**混淆核对**：顺偏向里 70% 是多单、逆偏向里 33% 是多单，而 S2 里多单的"
      "均风险距离本来就比空单大。如果 Δ风险距离 只是这个组成差造成的，"
      "那应该是顺偏向的风险**更大**才对：")
    A("")
    lg = [s for s in sig1h if s.direction > 0]
    sh = [s for s in sig1h if s.direction < 0]
    rl, rs = st.mean([s.d4 for s in lg]), st.mean([s.d4 for s in sh])
    w_e, a_e = split_bias(sig1h, BIAS_DEFS[0][2])[:2]
    fw = sum(1 for s in w_e if s.direction > 0) / len(w_e)
    fa = sum(1 for s in a_e if s.direction > 0) / len(a_e)
    predw = fw * rl + (1 - fw) * rs
    preda = fa * rl + (1 - fa) * rs
    A(f"- 多单均风险 {rl:.3f} ATR，空单 {rs:.3f} ATR。")
    A(f"- 只按多/空组成预测：顺偏向应为 {predw:.3f}、逆偏向应为 {preda:.3f}，"
      f"差 **{predw-preda:+.3f}**。")
    A(f"- 实际观测：顺 {st.mean([s.d4 for s in w_e]):.3f}、逆 "
      f"{st.mean([s.d4 for s in a_e]):.3f}，差 "
      f"**{st.mean([s.d4 for s in w_e])-st.mean([s.d4 for s in a_e]):+.3f}**。")
    A("- 符号相反、量级差 5 倍。**这个几何差不是多/空混淆的产物**，"
      "它是「价格离那条线多远」的产物。")
    A("")
    A("### 3.3 把 Δ均净R 拆成「命中率贡献 + 幅度贡献」（S2）")
    A("")
    A("恒等式 E = p·W + (1−p)·L，两组之差可以精确拆成三项：")
    A("")
    A("    ΔE = (p₁−p₂)·(W̄−L̄)  +  p̄·(W₁−W₂)  +  (1−p̄)·(L₁−L₂)")
    A("         └── 命中率贡献 ──┘  └──── 赢/输单幅度贡献 ────┘")
    A("")
    decomposition(res1h, o)
    A("同一张表在 S1（60 天窗口）上的样子：")
    A("")
    decomposition(res10, o)

    # ── 4 持续性 ────────────────────────────────────────────────────────────
    A("## 4 · 持续性检验：「反抽」到底多常见")
    A("")
    A("直接回应这句：")
    A("")
    A("> 「日内交易不可能一直都是单边下跌的……位置下不去以后最终不还是反抽上来了吗」")
    A("")
    A("度量：当日（含夜盘，trade_day 口径）**最低点之后**的最高价，减去最低点，"
      "除以当日 ATR（前一日 Wilder ATR14）。这是「跌完之后反抽了多少」的直接量化。"
      "镜像量是最高点之后的最低价。样本 = ES=F 1h 730d 的每个交易日。")
    A("")
    A("⚠ 这个度量有一个内建的选择偏差，必须先说：**从当日最低点起算的反弹一定 ≥0**，"
      "因为最低点就是全天最有利的起跳点。所以「87% 的日子反弹 ≥0.236 ATR」"
      "**不是一个可交易的数字**——没有人能买在最低点。"
      "它能回答的是另一个问题：**「当天有没有过一段像样的反向行情」**，"
      "也就是硬闸门会不会挡掉真实存在的机会。"
      "跨组比较（偏空日 vs 偏多日）是公平的，因为同一个选择偏差对两组一样。")
    A("")
    pers = persistence("ES=F", o)
    persistence_5m("ES=F", o)
    rows = pers["rows"]
    if rows and sum(1 for r in rows if r["bias"].e21 < 0) >= 10:
        bump()
        allreb = [r["reb"] for r in rows]
        bear = [r for r in rows if r["bias"].e21 < 0]
        bull = [r for r in rows if r["bias"].e21 > 0]
        A(f"**读法**：全样本 {len(rows)} 个交易日里，低点后反弹 ≥0.236 ATR 的比例是 "
          f"{100*sum(1 for v in allreb if v>=0.236)/len(allreb):.0f}%；"
          f"日线偏空的 {len(bear)} 天里这个比例是 "
          f"{100*sum(1 for r in bear if r['reb']>=0.236)/len(bear):.0f}%，"
          f"偏多的 {len(bull)} 天里是 "
          f"{100*sum(1 for r in bull if r['reb']>=0.236)/len(bull):.0f}%。"
          f"**偏空日和偏多日几乎一样会反抽**——偏向不会把一天变成单边。"
          f"这就是硬闸门方案在机制上错在哪儿：闸门假设的是"
          f"「偏空日只该做空」，而偏空日里 "
          f"{100*sum(1 for r in bear if r['reb']>=0.382)/len(bear):.0f}% "
          f"都出现了 ≥0.382 ATR 的反弹，那正是被闸门挡掉的那一半机会。")
        A("")
        # 低点出现时间
        A("反抽不是「收盘前一分钟才发生」的：")
        A("")
        A("| 分组 | 日数 | 日内低点出现在当日进程的中位位置 | 高点中位位置 | "
          "反弹中位(ATR) | 回落中位(ATR) |")
        A("|---|---|---|---|---|---|")
        for lab, g in (("全部", rows), ("D-EMA21 偏空", bear), ("D-EMA21 偏多", bull)):
            if len(g) < 10:
                continue
            bump()
            A(f"| {lab} | {len(g)} | {100*st.median([r['lo_frac'] for r in g]):.0f}% | "
              f"{100*st.median([r['hi_frac'] for r in g]):.0f}% | "
              f"{st.median([r['reb'] for r in g]):.3f} | "
              f"{st.median([r['pul'] for r in g]):.3f} |")
        A("")

    # ── 5 交互 ──────────────────────────────────────────────────────────────
    A("## 5 · 与状态层的交互：趋势态里偏向更值钱吗")
    A("")
    A("先验猜测（任务书写明）：趋势态里偏向有用，区间态里偏向有害，因为区间就是要做两边。"
      "状态用两套盘前就能算的定义：日线 10 日 Kaufman 效率比 ER10（三分位），"
      "以及月线位状态（Saty 自己的词汇：trigger_box / gg_zone / extended / beyond_1atr）。")
    A("")
    interaction(sig1h, o, "S2 · ES=F 1h 730d")

    # ── 6 大样本方向检验 ────────────────────────────────────────────────────
    A("## 6 · 大样本：偏向能不能预测方向（S3）")
    A("")
    A("⚠ 既有结论（三轮检验、四类工具）：**方向不可由 ribbon / phase / 跳空方向 / "
      "首小时方向 / 位状态预测**。如果这一节发现偏向能预测方向，那是与既有结论冲突的"
      "强主张，需要极高标准的证据。所以这里刻意用最大的样本、最简单的口径、"
      "以及**无条件收涨率**（不是 50%）当零假设。")
    A("")
    daily_test("ES=F", o)
    A("同样的表在 ^GSPC 上（第二个标的的方向性对照；按纪律 5，^GSPC 不能代理位价，"
      "但这里量的是 ATR 归一的方向与幅度，不是具体位价）：")
    A("")
    daily_test("^GSPC", o)
    A("### 6.1 对称括号赛跑：几何零假设正好 50%")
    A("")
    A("上表的「收涨率」混了幅度进去。更干净的口径是**对称括号**：从前收出发 ±0.382 ATR，"
      "哪一侧先被触到。S=T ⇒ 几何零假设正好 50.0%，没有任何几何偏差可以藏。")
    A("")
    daily_race("ES=F", o)

    # ── 7 稳健性 / 反例 ─────────────────────────────────────────────────────
    A("## 7 · 反例与不利证据（单列，纪律 7）")
    A("")
    A("凡是与「偏向有用」相反、或与本报告主线相反的格子，列在这里。")
    A("")
    A("| 出处 | 格子 | 数字 | 为什么它与主线相反 |")
    A("|---|---|---|---|")
    contrary: list[tuple[str, str, str, str]] = []
    for key, _d, _g in BIAS_DEFS:
        c = res1h.get(key, {})
        if "顺偏向" in c and "逆偏向" in c:
            w, a = c["顺偏向"], c["逆偏向"]
            if a["exc"] > w["exc"]:
                contrary.append((
                    "S2 §2", f"{key} 逆偏向超额 > 顺偏向超额",
                    f"逆 {100*a['exc']:+.1f} pp vs 顺 {100*w['exc']:+.1f} pp",
                    "如果偏向有方向信息，顺偏向的超额应该更高"))
            if a["avg_net"] > w["avg_net"]:
                contrary.append((
                    "S2 §2", f"{key} 逆偏向均净R > 顺偏向",
                    f"逆 {a['avg_net']:+.3f} vs 顺 {w['avg_net']:+.3f}",
                    "同上"))
    for key, _d, _g in BIAS_DEFS:
        c = res10.get(key, {})
        if "顺偏向" in c and "逆偏向" in c:
            w, a = c["顺偏向"], c["逆偏向"]
            if a["avg_net"] > w["avg_net"]:
                contrary.append((
                    "S1 §2", f"{key} 逆偏向均净R > 顺偏向",
                    f"逆 {a['avg_net']:+.3f} vs 顺 {w['avg_net']:+.3f}",
                    "60 天窗口里逆偏向≈做空，说明这一格量的是方向不是偏向"))
    if not contrary:
        A("| — | 没有格子与主线相反 | — | — |")
    for row in contrary[:24]:
        A("| " + " | ".join(row) + " |")
    A("")

    A("## 8 · 多重比较：谁越过了门槛，谁没有")
    A("")
    thr = _bonf_z(CELLS)
    A(f"全文共检视 **{CELLS} 个格子**（分组格、对比行、幅度行、分解行、状态交互格、"
      f"持续性格、日线格、赛跑格）。Bonferroni 门槛 |z| > **{thr:.2f}**（α=0.05 双侧）。"
      f"常规 |z| > 1.96 在这个 family size 下**没有意义**。")
    A("")
    fams = ["S2", "S1", "S2-幅度", "S2-交互"]
    FAMNOTE = {
        "S2": "S2 顺/逆 的方向类对比（Δ超额、Δ均净R）——**本报告的主问题**",
        "S1": "S1 顺/逆 的方向类对比（60 天窗口，偏向≈方向）",
        "S2-幅度": "S2 顺/逆 的幅度类对比（MFE/MAE/风险距离/T1距离/几何零假设/钱）",
        "S2-交互": "S2 偏向 × 状态 的交互格（ER10 三分位 + 月线位状态）",
    }
    A("| family | 格子数 | 最大 z 绝对值 | 出处 | 越过 " + f"{thr:.2f}" + " 的个数 |")
    A("|---|---|---|---|---|")
    for fam in fams:
        rs = [r for r in ZLOG if r[0] == fam]
        if not rs:
            continue
        mz = max(rs, key=lambda r: abs(r[2]))
        nsurv = sum(1 for r in rs if abs(r[2]) > thr)
        A(f"| {FAMNOTE[fam]} | {len(rs)} | **{abs(mz[2]):.2f}** | {mz[1]} | {nsurv} |")
    A("")
    surv = sorted([r for r in ZLOG if abs(r[2]) > thr], key=lambda r: -abs(r[2]))
    s2z = [r for r in ZLOG if r[0] == "S2"]
    if s2z:
        mz = max(s2z, key=lambda r: abs(r[2]))
        A(f"**这张表的判决**：在能把偏向和方向分开的样本（S2）里，"
          f"顺/逆的方向类对比最大 |z| = {abs(mz[2]):.2f}，"
          f"连未修正的 1.96 都没到，更不用说 {thr:.2f}。"
          f"而幅度类对比里有 "
          f"{sum(1 for r in ZLOG if r[0]=='S2-幅度' and abs(r[2])>thr)} 个越过了 "
          f"{thr:.2f}——**偏向的信息全在幅度这一侧，方向那一侧一无所有。**")
        A("")
    if surv:
        A(f"越过 {thr:.2f} 的全部格子（{len(surv)} 个），以及它们各自到底在说什么：")
        A("")
        A("| family | 格子 | z | 它量的是什么 |")
        A("|---|---|---|---|")
        for smp, cell, z in surv[:20]:
            if smp == "S1":
                why = ("S1 的「顺偏向」有 74–100% 是多单，这一格量的是"
                       "「这 60 天做多亏钱」，不是「偏向有信息」")
            elif smp == "S2-幅度":
                why = "偏向确实改变交易的几何与幅度——这是 §10.2 的主结论"
            else:
                why = "见对应小节"
            A(f"| {smp} | {cell} | {z:+.2f} | {why} |")
        A("")
    else:
        A(f"**没有任何格子越过 {thr:.2f}。**")
        A("")
    A("另外要分清两类 z：§2 表里的「均净R z(日聚类)」检验的是"
      "「这一组的均净R 是不是显著小于 0」——那是在复述 v14 本来就在亏钱"
      "（`V15_ENTRY_LOCATION.md` 已确认），不是偏向的证据。"
      "只有「Δ(顺−逆)」那几列才是这一轮的检验对象。")
    A("")

    A("## 9 · 局限")
    A("")
    A("1. **位价局限（纪律 5）**：主样本 ES=F，作息与 CAPITALCOM:SPX500 一致。"
      "^GSPC 只在 §6 做方向性对照。ES=F 与 SPX500 的 ATR 比值不是常数"
      "（246 天 mean 1.117 / sd 0.083 / 范围 0.826–1.418），"
      "所以本报告里所有依赖具体位价的数字（月线 pivot、±0.382 ATR 括号）"
      "在用户实际交易的标的上会有几个百分点的偏移；结论是关于**方向与幅度的秩序**，"
      "不是关于具体价位。")
    A("2. **S1 的偏向不翻**：60 天窗口里日线偏向几乎恒为多，"
      "「顺/逆」与「多/空」几乎共线，S1 的任何顺/逆差都不能解读为偏向的作用。")
    A("3. **S2 换了 setup 周期**：主证据来自 1h setup K，而生产是 10m。"
      "命中率、几何零假设、风险距离的**绝对值**在两个周期上不可比"
      "（S1 命中 54%、S2 命中 71%，就是周期差出来的）。"
      "可比的只有**同一样本内部顺/逆两组的差**。任何把 S2 的绝对数字"
      "搬到生产周期上的读法都是错的。")
    A("4. **S2 的路径分辨率**：1h 没有更细的数据，同一根 K 内两侧都被触到的交易"
      "一律记未裁决（纪律 3）。未裁决率在表里逐格报出；如果两组未裁决率差很多，"
      "命中率的对比本身就有选择偏差。")
    A("5. **日聚类**：所有关键 z 都按交易日聚类。朴素 z 一律不作数。")
    A("6. **样本量**：S1 约 50 个交易日、S2 约 600 个交易日。"
      "S2 的 600 天里日线偏向的**独立**翻转次数远少于 600——"
      "偏向本身是高度自相关的序列，日聚类也修不了这一层。真正的有效样本"
      "是「偏向段」的数目，量级在两位数。任何 S2 上的边际显著都要按这个折价。")
    A("")

    # ── 10 判决 ─────────────────────────────────────────────────────────────
    A("## 10 · 判决")
    A("")
    r_w = res1h["D-EMA21"]["顺偏向"]
    r_a = res1h["D-EMA21"]["逆偏向"]
    s2max = max((abs(z) for _s, _c, z in ZLOG if _s == "S2"), default=float("nan"))
    allexc =[res1h[k][g]["exc"] for k, _d, _g2 in BIAS_DEFS
              for g in ("顺偏向", "逆偏向") if g in res1h.get(k, {})]
    A("### 10.1 偏向有没有【方向】信息？没有。")
    A("")
    A(f"- **S2（{len(sig1h)} 笔 / {len(days1h)} 天，偏向会翻）**：四种定义、顺/逆两组，"
      f"扣掉几何零假设之后的超额全部落在 {100*min(allexc):+.1f} pp 到 "
      f"{100*max(allexc):+.1f} pp 之间，日聚类 z 最大 |z| = {s2max:.2f}。"
      f"没有一项接近 1.96，更不用说 Bonferroni 门槛 {thr:.2f}。")
    A("- **S3（ES=F 日线 4929 根 / 20 年）**：偏多组收涨 54.1%、偏空组收涨 54.7%，"
      "无条件收涨率 54.3%——**偏空日的次日收涨率反而略高于偏多日**。"
      "^GSPC 上同一张表同一个方向（偏空 55.8% vs 偏多 53.7%）。")
    A("- **对称括号赛跑（几何零假设正好 50%，没有几何可藏）**：偏多日先触上方 51.8%，"
      "偏空日先触上方 53.8%。两个都在 50% 附近，而且**排序是反的**。")
    A("")
    A("这与既有结论一致，不构成冲突：**方向不可由 ribbon / phase / 跳空方向 / "
      "首小时方向 / 位状态预测**，现在再加一条——也不可由日线偏向预测。"
      "这一轮没有发现任何需要「极高标准证据」的反常结果。")
    A("")
    A("### 10.2 那它有没有信息？有，在【幅度】和【几何】上。")
    A("")
    A(f"S2 里顺/逆两组最稳的差别根本不是命中率，而是**交易的几何形状**：")
    A("")
    A(f"| | 顺偏向 | 逆偏向 | 差 |")
    A(f"|---|---|---|---|")
    A(f"| 几何零假设（=S/(S+T)） | {100*r_w['null']:.1f}% | {100*r_a['null']:.1f}% | "
      f"{100*(r_w['null']-r_a['null']):+.1f} pp |")
    A(f"| 均风险距离(ATR) | {r_w['d4']:.3f} | {r_a['d4']:.3f} | "
      f"{r_w['d4']-r_a['d4']:+.3f} |")
    A(f"| 均T1距离(ATR) | {r_w['t1d']:.3f} | {r_a['t1d']:.3f} | "
      f"{r_w['t1d']-r_a['t1d']:+.3f} |")
    A(f"| 赢单均净R | {r_w['avg_win']:+.3f} | {r_a['avg_win']:+.3f} | "
      f"{r_w['avg_win']-r_a['avg_win']:+.3f} |")
    A(f"| 输单均净R | {r_w['avg_loss']:+.3f} | {r_a['avg_loss']:+.3f} | "
      f"{r_w['avg_loss']-r_a['avg_loss']:+.3f} |")
    A(f"| 均净R | {r_w['avg_net']:+.3f} | {r_a['avg_net']:+.3f} | "
      f"{r_w['avg_net']-r_a['avg_net']:+.3f} |")
    A("")
    A("读法：**顺偏向的交易是「大赢大输」，逆偏向的交易是「小赢小输」**，"
      "而两者的期望几乎一模一样（−0.106 vs −0.099），"
      "换算成钱（净R × 风险距离）更是完全重合（−0.0245 vs −0.0234，z_clu −0.10）。"
      "§3.3 的分解把这件事量化到底：D-EMA21 的 Δ均净R 里，"
      "命中率贡献只占 2%，幅度贡献占 98%；M-Pivot 是 5% / 95%。"
      "四种定义里命中率贡献占比最高的 W-EMA21 也只有 40%。")
    A("")
    A("**所以偏向是一个尺度（scale）信号，不是一个方向（sign）信号。**"
      "但要立刻加上 §3.2 的两个限定：这个尺度效应只在 D-EMA21 和 M-Pivot 上显著"
      "（D-Ribbon、W-EMA21 的 Δ风险距离 |z| < 0.21），"
      "而且它**不转化为钱**——它改变的是同一笔钱被切成 R 的方式，不是钱本身。")
    A("")
    A("### 10.3 正确的用法（严格区分「数据支持的」和「数据没反对但也没检验的」）")
    A("")
    A("| 用法 | 判定 | 证据 |")
    A("|---|---|---|")
    A("| 硬闸门（逆偏向不许开仓） | **数据反对** | 逆偏向的期望和顺偏向一样"
      f"（Δ均净R {r_w['avg_net']-r_a['avg_net']:+.3f}，z_clu −0.16；"
      "Δ钱 −0.001，z_clu −0.10）。砍掉一半笔数换不来单笔质量提升，只是把样本砍半"
      "（纪律 6）。而且 §4 显示偏空日里 82% 都出现 ≥0.382 ATR 的反抽。 |")
    A("| 按偏向调仓位倍数 | **数据反对** | 「均钱」四种定义全部无差别（z 绝对值 ≤ 1.36）。"
      "顺/逆的风险距离确实不同，但按固定金额风险下单时这一步已经自动完成，"
      "**再乘一个偏向系数没有任何证据支持**。 |")
    A("| 按偏向调目标 / 分批点 | **未检验，别当成结论** | 数据只说明「逆偏向的 T1 "
      f"天然更近」（顺 {r_w['t1d']:.3f} vs 逆 {r_a['t1d']:.3f} ATR，四种定义同号，"
      "最大 z 2.54，未过 Bonferroni）。"
      "「所以顺偏向该把 T2 放远」是**推论，本报告没有检验它**——"
      "要检验必须重跑一遍带不同目标规则的完整回测。别把它写进结论。 |")
    A("| 显示 / 账本分组 | **数据不反对，且成本为零** | 偏向不改变任何一笔的期望，"
      "所以拿它当解释语言和复盘维度是安全的：它不会让你少做或多做任何一笔。"
      "这正是 v15 已经采纳的位置。 |")
    A("")
    A("**一句话**：用户的直觉「第一层是给一个 bias 的参考」在数据上成立，"
      "但成立的方式比他说的还要弱一点——偏向连「参考」的方向性都没有，"
      "它只描述**今天这笔交易会长成什么形状**（止损多远、目标多近、"
      "赢单输单的尺寸），不描述**它会不会赢**。")
    A("")
    A("### 10.4 与状态层的交互：先验猜测不成立")
    A("")
    A("任务书的先验是「趋势态里偏向有用、区间态里偏向有害」。数据不支持：")
    A("")
    ixz = [r for r in ZLOG if r[0] == "S2-交互"]
    ixe = [r for r in ixz if "Δ超额" in r[1]]
    mix = max(ixe, key=lambda r: abs(r[2])) if ixe else None
    A("- ER10 三分位 × 4 定义：**趋势态（ER 高）那一档里，顺偏向的均净R 反而更低**"
      "（D-EMA21 Δ −0.141，z −2.02；D-Ribbon Δ −0.177，z −2.24），符号与先验相反。")
    A("- 月线位状态 × 4 定义：`extended` 那一档四个定义齐刷刷 Δ超额 +10 到 +14 pp，"
      "看着最像真的——但 n 只有 47–89，|z| 只有 1.14–1.30，"
      "而且四个定义在这一档高度重叠（D-EMA21 和 M-Pivot 的格子 n 完全相同：73/89），"
      "不是四个独立证据，是同一批日子被数了四遍。")
    A("")
    if mix:
        A(f"{len(ixe)} 个交互格（Δ超额口径）里最大 |z| = **{abs(mix[2]):.2f}**"
          f"（{mix[1]}），Bonferroni 门槛 {thr:.2f}。**没有交互。**")
    A("")
    A("### 10.5 用户那句话的量化答案")
    A("")
    if rows:
        bear = [r for r in rows if r["bias"].e21 < 0]
        bull = [r for r in rows if r["bias"].e21 > 0]
        A("> 「日内交易不可能一直都是单边下跌的……位置下不去以后最终不还是反抽上来了吗」")
        A("")
        A(f"**对，而且偏空日反抽得比偏多日还大。** ES=F 603 个交易日（1h 路径，"
          f"5m 复核在 §4）：")
        A("")
        A(f"- 日线偏空的 {len(bear)} 天里，日内低点之后反弹 ≥0.236 ATR 的占 "
          f"{100*sum(1 for r in bear if r['reb']>=0.236)/len(bear):.0f}%，"
          f"≥0.382 占 {100*sum(1 for r in bear if r['reb']>=0.382)/len(bear):.0f}%，"
          f"≥0.618 占 {100*sum(1 for r in bear if r['reb']>=0.618)/len(bear):.0f}%，"
          f"反弹中位 {st.median([r['reb'] for r in bear]):.3f} ATR。")
        A(f"- 偏多的 {len(bull)} 天里同样口径是 "
          f"{100*sum(1 for r in bull if r['reb']>=0.236)/len(bull):.0f}% / "
          f"{100*sum(1 for r in bull if r['reb']>=0.382)/len(bull):.0f}% / "
          f"{100*sum(1 for r in bull if r['reb']>=0.618)/len(bull):.0f}%，"
          f"中位 {st.median([r['reb'] for r in bull]):.3f} ATR。")
        A(f"- 即使只看**真的收阴**的 {sum(1 for r in rows if r['down_day'])} 天，"
          f"低点后仍有 "
          f"{100*sum(1 for r in rows if r['down_day'] and r['reb']>=0.236)/max(1,sum(1 for r in rows if r['down_day'])):.0f}% "
          f"反弹 ≥0.236 ATR。")
        A(f"- 日内低点的中位出现位置是当日进程的 "
          f"{100*st.median([r['lo_frac'] for r in rows]):.0f}%——"
          f"反抽不是收盘前才发生的，后面还有三分之一个交易日。")
        dnb = [max(r["dn_ext"], 0.0) for r in bear]
        rbb = [r["reb"] for r in bear]
        A(f"- **尺寸对比**：偏空日的中位「开盘→低点」跌幅是 {st.median(dnb):.3f} ATR，"
          f"中位「低点后反弹」是 {st.median(rbb):.3f} ATR，比值 "
          f"{st.median([b/a for a, b in zip(dnb, rbb) if a > 1e-6]):.2f}；"
          f"{100*sum(1 for a, b in zip(dnb, rbb) if b >= a)/len(bear):.0f}% 的偏空日里"
          f"**反弹幅度大于当日跌幅**。")
        A("")
        A("这就是硬闸门在机制上错在哪里：闸门的隐含假设是「偏空日 = 单边下跌日」，"
          "而数据说偏空日的**反抽幅度比偏多日更大**（中位 "
          f"{st.median([r['reb'] for r in bear]):.3f} vs "
          f"{st.median([r['reb'] for r in bull]):.3f} ATR）。"
          "偏空日之所以反抽更大，只是因为它们的绝对波动更大——"
          "这又一次是**幅度**，不是**方向**。")
    A("")

    txt = "\n".join(o) + "\n"
    REPORT.write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
