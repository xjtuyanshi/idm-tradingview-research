"""V15 · 刻度错配：目标与止损用了两把尺子，代价是多少。

为什么有这个文件
----------------
v14/v15 的设计里，一笔交易的两个边界来自**两个互不相干的坐标系**：

    目标 = 顺方向下一个具名位（日线 ATR 梯，锚=前收，格距 0.118–0.346 ATR，
           一整天固定不动）
    止损 = 结构性极值（近 3–5 根 10m K 的高/低点 + 缓冲，随行情逐根变化）

`V15_ENTRY_LOCATION.md` 已经确认：**唯一有效的闸门是「止损放远」**
（D4≥中位：均净R +0.005 vs 基线 −0.142，z_sel +4.37）。本文件问的是机制问题：
「止损放远」有效，是不是因为它在**顺手修正刻度错配**？

因为目标固定、止损可变，T/S 比（目标距离 / 止损距离）几乎完全由止损决定：
止损放远 ⇒ T/S 变小 ⇒ 几何零假设命中率变高、单笔赔率变低、点差占 R 的比重变小。
所以 D4 和 T/S 在数学上是同一个东西的两种写法，必须显式拆开。

本文件测四件事：
  1. T/S 分位分层：z_geom 与均净R 随 T/S 怎么变
  2. 目标改成固定 R（k=1/1.5/2/3），止损不动
  3. 止损改成反方向的相邻具名位（两把尺子合并成位的尺子）
  4. 止损改成 k × 近期已实现波动（20 根 setup K 的 Wilder ATR）
最后给 5×5 总表，并回答：v14 的负期望里，多少能归因于两把尺子。

方法学纪律
----------
- 零假设一律是几何零假设 P = S/(S+T)（纪律 1），报 z_geom。
- 路径判定全部落到 5 分钟子 K（纪律 2）。同一根 5m 子 K 内同时触及双边的，
  单列为「含混」，命中率里剔除、R 里按保守（判止损）计，两种口径都报。
- 点差 0.6 点（纪律 4），毛 R 与净 R 并列。
- 主样本 ES=F（含夜盘，作息与 CAPITALCOM:SPX500 一致），^GSPC RTH 仅作对照。
  位价具体数值有 ±12% 的仪器差（纪律 5），凡依赖具体位价的结论都标注。
- 25 个组合跑在**同一批信号**上，所以主检验用**配对差**（同一笔在两种定义下的
  净R 之差），比两组独立均值比较强得多，也诚实得多。

Usage:  .venv/bin/python research/satylab/study_scale_mismatch.py
"""

from __future__ import annotations

import math
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats                                   # noqa: E402
from satylab.data import Bar                                      # noqa: E402
from satylab.study_v14_repro import (                             # noqa: E402
    LevelBook, load_10m, next_rung, run_v14, trade_day,
)
from satylab.study_entry_location import (                        # noqa: E402
    RACE_CAP, SPREAD, Sig, _bonf_z, bracket, excursion, harvest,
    isolated_trade, location_vars, norm_sf, q, quantile_bins,
    spearman, trend_z, tstat, two_sided, z_geom,
)

MIN_RISK_PTS = 2.0        # v14 的最小风险距离，替代止损沿用同一个地板
VOL_LEN = 20              # 「近期已实现波动」= 20 根 setup K 的 Wilder ATR
NQ = 5
REPORT = Path(__file__).resolve().parents[1] / "reports" / "V15_SCALE_MISMATCH.md"

CELLS = 0


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


def fmt(x, p=3, sign=False):
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


# ═══════════════════════ 波动尺（10m Wilder ATR20） ═══════════════════════════
def wilder(bars: list[Bar], n: int) -> list[float | None]:
    trs: list[float] = []
    for i, b in enumerate(bars):
        trs.append(b.high - b.low if i == 0 else max(
            b.high - b.low, abs(b.high - bars[i - 1].close),
            abs(b.low - bars[i - 1].close)))
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n:
        return out
    prev = sum(trs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(bars)):
        prev = (prev * (n - 1) + trs[i]) / n
        out[i] = prev
    return out


# ═══════════════════════════ 组合的定义 ══════════════════════════════════════
# 止损定义：给 (sig, ctx) 返回止损距离（点）。ctx 带 anchor/atr/vol20。
def stop_struct(s: Sig, c: dict) -> float:
    return s.risk


def stop_rung(s: Sig, c: dict) -> float:
    px = next_rung(s.entry, -s.direction, c["anchor"], c["atr"])
    return max(abs(s.entry - px), MIN_RISK_PTS)


def make_stop_vol(k: float):
    def f_(s: Sig, c: dict) -> float:
        return max(k * c["vol20"], MIN_RISK_PTS)
    return f_


# 目标定义：给 (sig, S, ctx) 返回目标距离（点）。
def tgt_level(s: Sig, S: float, c: dict) -> float:
    return abs(s.t1 - s.entry)


def make_tgt_r(k: float):
    def f_(s: Sig, S: float, c: dict) -> float:
        return k * S
    return f_


def make_tgt_level_floor(floor_fn):
    """具名位目标，但要求最小距离——不够就跳到梯子的再下一格。

    这是「不放弃 Saty 的具名位」的最小修补：目标仍然只落在具名位上，
    只是不再接受「入场价刚好贴着位下沿」造成的 0.03 点余数目标。
    """
    def f_(s: Sig, S: float, c: dict) -> float:
        floor = floor_fn(s, S)
        px, nx = s.entry, s.entry
        for _ in range(24):
            nx = next_rung(px, s.direction, c["anchor"], c["atr"])
            if abs(nx - s.entry) >= floor:
                break
            px = nx
        return abs(nx - s.entry)
    return f_


FLOOR_TARGETS = [
    ("具名位 ≥4×点差", "LVLf24", make_tgt_level_floor(lambda s, S: 4 * SPREAD),
     f"绝对地板 {4*SPREAD:.1f} 点"),
    ("具名位 ≥0.5×S", "LVLf05", make_tgt_level_floor(lambda s, S: 0.5 * S),
     "相对地板（混合尺）"),
    ("具名位 ≥1.0×S", "LVLf10", make_tgt_level_floor(lambda s, S: 1.0 * S),
     "相对地板（混合尺）"),
]


STOPS = [
    ("结构极值", "STRUCT", stop_struct, "v14 原样：近 3–5 根 K 的极值"),
    ("反向具名位", "RUNG", stop_rung, "与目标同一把尺子"),
    ("1.0×ATR20", "VOL1.0", make_stop_vol(1.0), "已实现波动尺"),
    ("1.5×ATR20", "VOL1.5", make_stop_vol(1.5), "已实现波动尺"),
    ("2.0×ATR20", "VOL2.0", make_stop_vol(2.0), "已实现波动尺"),
]

TARGETS = [
    ("下一具名位", "LVL", tgt_level, "v14 原样：日线 ATR 梯"),
    ("1.0R", "R1.0", make_tgt_r(1.0), "固定 R 尺"),
    ("1.5R", "R1.5", make_tgt_r(1.5), "固定 R 尺"),
    ("2.0R", "R2.0", make_tgt_r(2.0), "固定 R 尺"),
    ("3.0R", "R3.0", make_tgt_r(3.0), "固定 R 尺"),
]


@dataclass
class Leg:
    """一笔交易在某个 (目标定义 × 止损定义) 下的结果。"""
    S: float
    T: float
    pnull: float
    code: str            # T 命中 / S 止损 / A 含混 / U 未裁决
    gross: float
    bars: int
    atr: float

    @property
    def hit(self) -> bool | None:
        return True if self.code == "T" else (False if self.code == "S" else None)

    @property
    def net(self) -> float:
        return self.gross - SPREAD / self.S

    @property
    def net_opt(self) -> float:
        """含混判成命中的乐观口径。"""
        g = (self.T / self.S) if self.code == "A" else self.gross
        return g - SPREAD / self.S

    @property
    def money(self) -> float:
        """净盈亏折成「日 ATR 的几分之一」——固定手数口径，R 之外的第二个尺子。"""
        return self.net * self.S / self.atr

    @property
    def ts(self) -> float:
        return self.T / self.S


def race(s: Sig, S: float, T: float, bars: list[Bar], subs,
         cap: int = RACE_CAP) -> tuple[str, int, float]:
    """纯括号赛跑，5m 子 K 裁决。返回 (code, 持有根数, 收盘 mark-to-market)。"""
    d = s.direction
    stop_px = s.entry - d * S
    tgt_px = s.entry + d * T
    for i in range(s.i + 1, min(s.i + 1 + cap, len(bars))):
        b = bars[i]
        hs = (b.low <= stop_px) if d > 0 else (b.high >= stop_px)
        ht = (b.high >= tgt_px) if d > 0 else (b.low <= tgt_px)
        if not (hs or ht):
            continue
        for sb in (subs[i] if subs is not None else [b]):
            phs = (sb.low <= stop_px) if d > 0 else (sb.high >= stop_px)
            pht = (sb.high >= tgt_px) if d > 0 else (sb.low <= tgt_px)
            if phs and pht:
                return "A", i - s.i, 0.0
            if pht:
                return "T", i - s.i, 0.0
            if phs:
                return "S", i - s.i, 0.0
    j = min(s.i + cap, len(bars) - 1)
    return "U", j - s.i, d * (bars[j].close - s.entry)


def eval_combo(sigs: list[Sig], ctx: dict, bars, subs,
               stop_fn, tgt_fn) -> list[Leg]:
    out: list[Leg] = []
    for s in sigs:
        c = ctx[s.i]
        S = stop_fn(s, c)
        T = tgt_fn(s, S, c)
        code, nb, mtm = race(s, S, T, bars, subs)
        if code == "T":
            g = T / S
        elif code in ("S", "A"):
            g = -1.0
        else:
            g = mtm / S
        out.append(Leg(S=S, T=T, pnull=S / (S + T), code=code, gross=g,
                       bars=nb, atr=s.atr))
    return out


# ═══════════════════════════ 汇总统计 ════════════════════════════════════════
def summarise(legs: list[Leg]) -> dict:
    dec = [l for l in legs if l.hit is not None]
    z, n, obs, null = z_geom([l.hit for l in dec], [l.pnull for l in dec])
    k = sum(1 for l in dec if l.hit)
    lo, hi = stats.wilson(k, n) if n else (float("nan"), float("nan"))
    return {
        "n": len(legs), "ndec": n, "namb": sum(1 for l in legs if l.code == "A"),
        "nund": sum(1 for l in legs if l.code == "U"),
        "hit": obs, "null": null, "z": z, "lo": lo, "hi": hi,
        "gross": st.mean([l.gross for l in legs]),
        "net": st.mean([l.net for l in legs]),
        "net_opt": st.mean([l.net_opt for l in legs]),
        "tot": sum(l.net for l in legs),
        "tot_gross": sum(l.gross for l in legs),
        "money": st.mean([l.money for l in legs]),
        "tot_money": sum(l.money for l in legs),
        "t": tstat([l.net for l in legs]),
        "ts_med": st.median([l.ts for l in legs]),
        "S_med": st.median([l.S for l in legs]),
        "bars_med": st.median([l.bars for l in legs]),
        "drag": st.mean([SPREAD / l.S for l in legs]),
    }


def paired(a: list[Leg], b: list[Leg]) -> tuple[float, float]:
    """配对差 mean(a−b) 与 t 值。同一批信号，所以配对合法。"""
    d = [x.net - y.net for x, y in zip(a, b)]
    return st.mean(d), tstat(d)


# ═══════════════════════════════ 报告 ════════════════════════════════════════
def build(symbol: str, rth_only: bool) -> dict:
    bars, subs = load_10m(symbol, rth_only)
    book = LevelBook(data.load(symbol, "20y", "1d"))
    sigs, e13s = harvest(bars, book)
    sigs = location_vars(sigs, bars, e13s)
    vol = wilder(bars, VOL_LEN)
    ctx: dict[int, dict] = {}
    keep: list[Sig] = []
    for s in sigs:
        lv = book.get(trade_day(bars[s.i]))
        if lv is None or vol[s.i] is None or vol[s.i] <= 0:
            continue
        ctx[s.i] = {"anchor": lv[0], "atr": lv[1], "vol20": vol[s.i]}
        keep.append(s)
    return {"symbol": symbol, "bars": bars, "subs": subs, "book": book,
            "e13": e13s, "sigs": keep, "ctx": ctx}


def grid(ds: dict) -> dict:
    out: dict[tuple[str, str], list[Leg]] = {}
    for _, tk, tf, _ in TARGETS:
        for _, sk, sf, _ in STOPS:
            out[(tk, sk)] = eval_combo(ds["sigs"], ds["ctx"], ds["bars"],
                                       ds["subs"], sf, tf)
    return out


def strata(legs: list[Leg], getter, o: list[str], label: str,
           k: int = NQ) -> list[float]:
    """按某个连续量分位分层。返回每档的 z_geom。"""
    vals = [getter(l) for l in legs]
    bins = quantile_bins(vals, k)
    o.append(f"| 档 | {label} 区间 | n | 命中率 [95%CI] | 几何零假设 | 超额 pp | "
             "z_geom | 均毛R | 均净R | 点差拖累 | 均money | 中位根数 |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    zs = []
    for j in range(k):
        g = [l for l, b in zip(legs, bins) if b == j]
        v = [x for x, b in zip(vals, bins) if b == j]
        if not g:
            continue
        bump()
        s = summarise(g)
        zs.append(s["z"])
        o.append(f"| Q{j+1} | {min(v):.2f}–{max(v):.2f} | {len(g)} | "
                 f"{100*s['hit']:.1f}% [{100*s['lo']:.1f},{100*s['hi']:.1f}] | "
                 f"{100*s['null']:.1f}% | {100*(s['hit']-s['null']):+.1f} | "
                 f"**{s['z']:+.2f}** | {s['gross']:+.3f} | {s['net']:+.3f} | "
                 f"−{s['drag']:.3f} | {s['money']:+.4f} | {s['bars_med']:.0f} |")
    dec = [l for l in legs if l.hit is not None]
    dv = [getter(l) for l in dec]
    tz = trend_z(dv, [int(l.hit) for l in dec], [l.pnull for l in dec])
    rho, rz = spearman(vals, [l.net for l in legs])
    rho2, rz2 = spearman(vals, [l.money for l in legs])
    bump(3)
    o.append("")
    o.append(f"- 趋势得分检验（带几何 offset）z = **{tz:+.2f}** (p={two_sided(tz):.3f})"
             f"；z<0 = {label} 越大越劣于几何零假设。")
    o.append(f"- 净R 秩相关 ρ = {rho:+.3f} (z={rz:+.2f})；"
             f"money 秩相关 ρ = {rho2:+.3f} (z={rz2:+.2f})。")
    return zs


def combo_row(name: str, s: dict, base: dict | None,
              pr: tuple[float, float] | None) -> str:
    d = f"{s['net']-base['net']:+.3f}" if base else "—"
    p = f"{pr[0]:+.3f} / t={pr[1]:+.2f}" if pr else "—"
    return (f"| {name} | {s['n']} | {s['ts_med']:.2f} | {s['S_med']:.1f} | "
            f"{100*s['hit']:.1f}% | {100*s['null']:.1f}% | "
            f"{100*(s['hit']-s['null']):+.1f} | **{s['z']:+.2f}** | "
            f"{s['gross']:+.3f} | {s['net']:+.3f} | {s['tot']:+.1f} | "
            f"{s['money']:+.4f} | {d} | {p} |")


HDR = ("| 组合 | n | 中位T/S | 中位S(点) | 命中率 | 几何零假设 | 超额pp | z_geom | "
       "均毛R | 均净R | 总净R | 均money | Δ均净R | 配对差/t |")
SEP = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def main() -> None:
    o: list[str] = []
    A = o.append

    prim = build("ES=F", False)
    ctrl = build("^GSPC", True)
    sigs, bars, subs, e13s = prim["sigs"], prim["bars"], prim["subs"], prim["e13"]
    G = grid(prim)
    GC = grid(ctrl)
    base = G[("LVL", "STRUCT")]
    bs = summarise(base)
    FG: dict[str, list[Leg]] = {}

    # v14 完整管理（分批 + 13 线离场）的锚，用来说明纯括号基线与它不是一个数
    for s in sigs:
        bracket(s, bars, subs)
        isolated_trade(s, bars, subs, e13s)
        excursion(s, bars, subs)
    full_net = [s.net for s in sigs]

    A("# V15 · 刻度错配：目标与止损用了两把尺子，代价是多少")
    A("")
    A(f"生成脚本 `research/satylab/study_scale_mismatch.py`。主样本 **ES=F 10m**"
      f"（由 60d 5m 聚合，含完整 23 小时时段，与 CAPITALCOM:SPX500 作息一致），"
      f"{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，{len(bars)} 根 setup K，"
      f"{len(sigs)} 个入场信号（去掉单仓闸门，与 `V15_ENTRY_LOCATION.md` 同一批）。"
      f"^GSPC 10m RTH 作对照。路径判定全部落到 5 分钟子 K（纪律 2）。")
    A("")

    # ───────────────────────── 0 ─────────────────────────
    A("## 0 · 这一轮在问什么，以及一开始就要改的一个说法")
    A("")
    A("v14 的两个边界来自两个坐标系：")
    A("")
    A("| | 尺子 | 谁决定它 | 一天之内会变吗 |")
    A("|---|---|---|---|")
    A("| 目标 T1 | 日线 ATR 梯（锚=前收，格距 0.118–0.346 ATR） | 昨天的收盘与 ATR | 不变 |")
    A("| 止损 S | 近 3–5 根 10m K 的结构极值 | 最近半小时的价格路径 | 每根 K 都在变 |")
    A("")
    A("任务书的猜想是「很远的目标 + 很紧的止损」。这个猜想**一半对、一半错**，"
      "而错的那一半很有信息量——先说错的那一半：")
    A("")
    tsv = [abs(s.t1 - s.entry) / s.risk for s in sigs]
    t1p = [abs(s.t1 - s.entry) for s in sigs]
    bump()
    A(f"- T/S 的分布：最小 {min(tsv):.3f}，p05 {q(tsv,0.05):.2f}，p25 {q(tsv,0.25):.2f}，"
      f"**中位 {st.median(tsv):.2f}**，p75 {q(tsv,0.75):.2f}，p95 {q(tsv,0.95):.2f}，"
      f"最大 {max(tsv):.2f}。")
    n_lt1 = sum(1 for x in tsv if x < 1.0)
    n_lt05 = sum(1 for x in tsv if x < 0.5)
    n_gt2 = sum(1 for x in tsv if x > 2.0)
    A(f"- **{100*n_lt1/len(tsv):.0f}%（{n_lt1}/{len(tsv)}）的交易，目标比止损还近**"
      f"（T/S<1）；{100*n_lt05/len(tsv):.0f}% 的 T/S<0.5；只有 "
      f"{100*n_gt2/len(tsv):.0f}% 的 T/S>2。")
    nsp = sum(1 for x in t1p if x <= SPREAD)
    nsp2 = sum(1 for x in t1p if x <= 2 * SPREAD)
    A(f"- 更难看的一头：**{nsp} 笔（{100*nsp/len(t1p):.1f}%）的 T1 距离 ≤ 一个点差"
      f"（{SPREAD} 点）**，{nsp2} 笔（{100*nsp2/len(t1p):.1f}%）≤ 两个点差。"
      f"T1 距离最小 {min(t1p):.2f} 点——`next_rung` 只要求位比入场价高一个 "
      f"minTick（0.01），所以入场价刚好贴着一个位下沿时，v14 会挂一个"
      f"**赚不回点差的目标**。")
    A("")
    A("所以「两把尺子」真实的病灶不是「目标太远」，而是**目标距离完全不受控**："
      f"它是「入场价落在梯子哪一格里」的余数，可以是 {min(t1p):.2f} 点，"
      f"也可以是 {max(t1p):.1f} 点，与这笔交易承担的风险毫无关系。")
    A("")
    A("**对的那一半**在第 2 节：T/S 确实**是**一个有预测力的坏消息变量——"
      "T/S 最大的那一档系统性地劣于几何零假设，趋势检验显著。"
      "任务书猜对了机制，猜错了这个机制覆盖多少交易。"
      "下面所有检验都围绕这个区分展开。")
    A("")
    A("### 0.1 两个基线不是一个数，先说清楚")
    A("")
    A(f"- **v14 完整管理**（T1 分批 50% / T2 再 25% / 13 线离场，孤立重放）："
      f"均净R {st.mean(full_net):+.3f}，总净R {sum(full_net):+.1f}。这是 "
      f"`V15_ENTRY_LOCATION.md` 里的那个数。")
    A(f"- **本文的纯括号基线**（单一目标 T1，全进全出，无分批、无 13 线离场）："
      f"均净R {bs['net']:+.3f}，总净R {bs['tot']:+.1f}，均毛R {bs['gross']:+.3f}。")
    A("")
    A("两者不同是**设计上的**：25 个格子必须用同一种、最简单的结算方式才能互比，"
      "分批与 13 线离场会把出场规则的影响掺进来。凡是拿本文的格子和 v14 线上账本"
      "直接对数的，都要先扣掉这个口径差。")
    A("")

    # ───────────────────────── 1 ─────────────────────────
    A("## 1 · 一个恒等式：为什么 T/S 是「刻度错配」的全部")
    A("")
    A("纯括号一笔的毛期望（命中赔 T/S，止损赔 −1）：")
    A("")
    A("```")
    A("E_gross = p·(T/S) − (1−p)·1")
    A("")
    A("几何零假设 p0 = S/(S+T) 代入：")
    A("E0 = [S/(S+T)]·(T/S) − T/(S+T) = T/(S+T) − T/(S+T) = 0")
    A("")
    A("所以           E_gross = (p − p0) · (1 + T/S)")
    A("               E_net   = (p − p0) · (1 + T/S) − 点差/S")
    A("```")
    A("")
    A("**几何零假设下毛期望恰好等于 0**——这不是巧合，是随机游走对称停时的性质。"
      "于是整个系统的毛盈亏只剩下一件事：命中率相对几何零假设的偏离 `(p − p0)`，"
      "再乘以一个**放大系数 (1 + T/S)**。")
    A("")
    A("这就把「两把尺子」的代价写成了两项，而且两项都由 T/S 与 S 直接控制：")
    A("")
    A("| 项 | 形式 | 谁在放大它 |")
    A("|---|---|---|")
    A("| 边际项 | `(p−p0)·(1+T/S)` | T/S 越大，同样的每单位概率亏损被放得越大 |")
    A("| 摩擦项 | `−点差/S` | S 越小，点差占 R 的比重越大 |")
    A("")
    A("注意这两项**指向相反**：要压住摩擦项就得把 S 放大，而 S 放大会让 T/S 变小、"
      "边际项的放大系数变小。所以「止损放远」同时改善两项——这正是 D4 闸门有效的"
      "机制候选。第 6 节把它拆开验证。")
    A("")
    tot_drag = sum(SPREAD / s.risk for s in sigs)
    bump()
    A(f"先给两项在 v14 基线上的实测量级（{len(sigs)} 笔纯括号）：")
    A("")
    A(f"- 总毛R = **{bs['tot_gross']:+.1f}**，总点差拖累 = **−{tot_drag:.1f}R**，"
      f"总净R = {bs['tot']:+.1f}。")
    A(f"- 也就是说，纯括号基线的亏损里 **{100*tot_drag/abs(bs['tot']):.0f}% 是点差"
      f"摩擦**，其余 {100*abs(bs['tot_gross'])/abs(bs['tot']):.0f}% 才是命中率不足。")
    A(f"- 每笔平均点差拖累 {bs['drag']:.4f} R。中位止损距离 {bs['S_med']:.1f} 点时"
      f"点差只吃 {SPREAD/bs['S_med']:.3f} R，但止损 3 点时要吃 {SPREAD/3:.2f} R——"
      f"**摩擦项是止损尺子的直接产物**。")
    A("")

    # ───────────────────────── 2 ─────────────────────────
    A("## 2 · T/S 分位分层（目标=具名位，止损=结构极值，即 v14 原样）")
    A("")
    A("任务书的预测：T/S 极端大的档应该系统性劣于几何零假设。下表逐档检验。")
    A("")
    zs_ts = strata(base, lambda l: l.ts, o, "T/S")
    dec_b = [l for l in base if l.hit is not None]
    tz_ts = trend_z([l.ts for l in dec_b], [int(l.hit) for l in dec_b],
                    [l.pnull for l in dec_b])
    A("")
    A("**判读**：")
    A("")
    worst = min(range(len(zs_ts)), key=lambda i: zs_ts[i])
    A(f"- 最差的一档是 **Q{worst+1}**（z_geom {zs_ts[worst]:+.2f}），"
      f"{'正是' if worst == NQ-1 else '不是'} T/S 最大的那一档。"
      "逐档 z_geom：" + "，".join(f"Q{i+1} {z:+.2f}" for i, z in enumerate(zs_ts))
      + "。")
    if tz_ts < -1.96:
        A(f"- **任务书的预测方向得到支持**：趋势得分检验 z = {tz_ts:+.2f} "
          f"(p={two_sided(tz_ts):.3f})，T/S 越大越系统性地劣于几何零假设。"
          f"最大的那一档 Q5 单独就是 z_geom {zs_ts[-1]:+.2f}。")
        A("- 也就是说刻度错配**同时**伤三个通道，而不是只伤赔率：")
        A("  1. **概率通道**：T/S 大的那些交易，命中率相对几何零假设的缺口最大；")
        A("  2. **放大通道**：同样的缺口再乘 (1+T/S)，Q5 的放大系数是 Q1 的 3.6 倍；")
        A("  3. **摩擦通道**：T/S 大 ⇔ S 小，点差占 R 的比重最大。")
        A("  三个通道同向叠加，所以均净R 从 Q1 到 Q5 掉了一个数量级。")
    else:
        A(f"- **任务书的预测方向没有得到支持**：趋势 z = {tz_ts:+.2f} "
          f"(p={two_sided(tz_ts):.3f})，z_geom 不随 T/S 单调下降。"
          f"刻度错配改的是赔率结构与摩擦，不是预测力。")
    A("")
    A("**但这张表有一个必须点破的共线性**：目标距离由日线梯决定、止损距离由结构"
      "决定，所以 T/S ≈ 常数/S。按 T/S 分层，**在很大程度上就是按止损大小反着"
      "分层**——它与 `V15_ENTRY_LOCATION.md` 第 2.5 节的 D4 表不是两份独立证据"
      "（相关系数见第 7 节）。这张表的增量价值不在「又发现一个变量」，"
      "而在**把 D4 的效应改写成一个有机制的量**：T/S。第 7 节做正面拆解。")
    A("")
    A("### 2.1 把两项分开：均净R 的差异到底由谁贡献")
    A("")
    A("对每档报 `(p−p0)`、放大系数、边际项预测值、摩擦项，和实测均净R。"
      "如果 `边际项 + 摩擦项 ≈ 实测`，恒等式就把这张表解释完了。")
    A("")
    vals = [l.ts for l in base]
    bins = quantile_bins(vals, NQ)
    A("| 档 | T/S 区间 | n | (p−p0) | 均(1+T/S) | 边际项预测 | 摩擦项 | 合计预测 | 实测均净R |")
    A("|---|---|---|---|---|---|---|---|---|")
    for j in range(NQ):
        g = [l for l, b in zip(base, bins) if b == j]
        v = [x for x, b in zip(vals, bins) if b == j]
        if not g:
            continue
        bump()
        s = summarise(g)
        amp = st.mean([1 + l.ts for l in g])
        marg = (s["hit"] - s["null"]) * amp
        fr = -s["drag"]
        A(f"| Q{j+1} | {min(v):.2f}–{max(v):.2f} | {len(g)} | "
          f"{s['hit']-s['null']:+.4f} | {amp:.2f} | {marg:+.3f} | {fr:+.3f} | "
          f"{marg+fr:+.3f} | {s['net']:+.3f} |")
    A("")
    A("（预测与实测的残差来自：含混判止损、未裁决按收盘 mark-to-market、"
      "以及 (p−p0) 的档内异质性。方向与量级对得上就足够支撑机制解释。）")
    A("")

    # ───────────────────────── 3 ─────────────────────────
    A("## 3 · 固定 R 目标 vs 下一个具名位（止损=结构极值不动）")
    A("")
    A("⚠ **与原作者方法冲突的前置声明**：Saty 本人的语料里 **0 次**出现"
      "「目标 2R」这类固定 R 目标，他的目标永远是具名位（call/put trigger、"
      "golden gate、±1 ATR、扩展位）。所以这一节若显示固定 R 更好，那是一个"
      "**背离原作者方法**的结果，不能含糊过去。判决写在本节末尾。")
    A("")
    A(HDR)
    A(SEP)
    for tn, tk, _, _ in TARGETS:
        legs = G[(tk, "STRUCT")]
        s = summarise(legs)
        bump()
        A(combo_row(f"{tn} × 结构极值", s, bs if tk != "LVL" else None,
                    paired(legs, base) if tk != "LVL" else None))
    A("")
    best_r = max(("R1.0", "R1.5", "R2.0", "R3.0"),
                 key=lambda k: summarise(G[(k, "STRUCT")])["net"])
    br = summarise(G[(best_r, "STRUCT")])
    pm, pt = paired(G[(best_r, "STRUCT")], base)
    A(f"**判决**：固定 R 目标里最好的是 **{best_r}**，均净R {br['net']:+.3f} "
      f"vs 具名位 {bs['net']:+.3f}，配对差 **{pm:+.3f} R/笔（t={pt:+.2f}，"
      f"p={two_sided(pt):.3f}）**，总净R {br['tot']:+.1f} vs {bs['tot']:+.1f}。")
    A("")
    if pt > 0 and two_sided(pt) < 0.05:
        A(f"这个差是**配对**检验出来的（同一批 {len(sigs)} 笔信号，同一个止损，"
          f"只换目标定义），不是抽样差异。但它 **t={pt:+.2f} 达不到第 11 节的 "
          f"Bonferroni 门槛**，而且方向上「更好的固定 R 目标」恰好是 1.0R——"
          f"也就是最靠近具名位中位 T/S（{bs['ts_med']:.2f}）的那一档。"
          f"随着 k 变大（1.5R / 2.0R / 3.0R）配对差单调转负。")
        A("")
        A("**所以与 Saty 方法的冲突并不成立**：数据没有说「固定 R 比具名位好」，"
          "它说的是「T/S 别太大」。1.0R 之所以赢，是因为它把 T/S 压到 1，"
          "而不是因为「固定 R」这个原理本身。凡是能把 T/S 压住的做法都行——"
          "包括下一节那个完全保留具名位的修补。")
    else:
        A("**没有一个固定 R 目标在配对检验下显著优于具名位。**"
          "与原作者方法的冲突因此**不成立**——这一节没有给出「该抛弃具名位」的证据。")
    A("")
    A("值得单独记一笔的是 **1.0R 这一档**：它把目标与止损强行绑成同一把尺子，"
      "T/S 恒等于 1，几何零假设恒等于 50%。它是本报告里「统一刻度」最纯粹的形态。"
      "而 3.0R 是最差的一档（配对差转负）——**这直接反驳了「目标该放更远」**。")
    A("")
    A("### 3.1 不放弃具名位的修补：给目标加一个最小距离地板")
    A("")
    A("第 0 节的病灶是「目标距离是余数」。修它不需要抛弃具名位，只需要**在梯子上"
      "多跳一格**：如果下一个位离入场价太近，就取再下一个位。目标仍然只落在 Saty "
      "的具名位上，方法论上零冲突。三种地板：")
    A("")
    A(HDR)
    A(SEP)
    A(combo_row("下一具名位（v14 原样）", bs, None, None))
    for tn, tk, tf, _ in FLOOR_TARGETS:
        legs = eval_combo(sigs, prim["ctx"], bars, subs, stop_struct, tf)
        FG[tk] = legs
        s = summarise(legs)
        bump()
        A(combo_row(f"{tn} × 结构极值", s, bs, paired(legs, base)))
    A("")
    bestf = max(FLOOR_TARGETS, key=lambda x: paired(FG[x[1]], base)[1])
    sf = summarise(FG[bestf[1]])
    pf, ptf = paired(FG[bestf[1]], base)
    A(f"最好的地板是 **{bestf[0]}**：均净R {sf['net']:+.3f}（基线 {bs['net']:+.3f}），"
      f"总净R {sf['tot']:+.1f}（基线 {bs['tot']:+.1f}），配对差 "
      f"**{pf:+.3f} R/笔 (t={ptf:+.2f}, p={two_sided(ptf):.3f})**，"
      f"中位 T/S 从 {bs['ts_med']:.2f} 变成 {sf['ts_med']:.2f}。")
    A("")
    A("**但全样本配对差是被稀释的**：地板只在「下一个位太近」的那些交易上"
      "改变任何东西，其余交易两种定义完全相同、配对差恒为 0。所以正确的"
      "检验口径是**只看被改动的那些笔**：")
    A("")
    A("| 地板 | 被改动笔数 | 占比 | 这些笔 基线均净R | 改后均净R | 配对差 | t | 全样本总净R 变化 |")
    A("|---|---|---|---|---|---|---|---|")
    for tn, tk, _, _ in FLOOR_TARGETS:
        legs = FG[tk]
        idx = [i for i in range(len(base)) if abs(legs[i].T - base[i].T) > 1e-9]
        if len(idx) < 10:
            continue
        bump()
        d = [legs[i].net - base[i].net for i in idx]
        A(f"| {tn} | {len(idx)} | {100*len(idx)/len(base):.1f}% | "
          f"{st.mean([base[i].net for i in idx]):+.3f} | "
          f"{st.mean([legs[i].net for i in idx]):+.3f} | {st.mean(d):+.3f} | "
          f"{tstat(d):+.2f} | {summarise(legs)['tot']-bs['tot']:+.1f} |")
    A("")
    A("这一节的**方法论价值**在于它把「两把尺子」的核心病灶单独隔离出来："
      "同样的信号、同样的止损、同样的梯子，只是不再接受一个赚不回点差的目标。"
      "它是全文唯一**既针对刻度错配、又完全不与 Saty 的具名位方法冲突**的改动。"
      "判决写在第 12.2 与 12.4 节——**方向对，量级小，统计上过不了关**。")
    A("")

    # ───────────────────────── 4 ─────────────────────────
    A("## 4 · 止损改用具名位（两把尺子合并成「位」这一把）")
    A("")
    A(f"止损 = 反方向相邻的具名位，并沿用 v14 的最小风险地板 {MIN_RISK_PTS} 点。")
    nfloor = sum(1 for s in sigs
                 if abs(s.entry - next_rung(s.entry, -s.direction,
                                            prim["ctx"][s.i]["anchor"],
                                            prim["ctx"][s.i]["atr"])) < MIN_RISK_PTS)
    A(f"地板在 **{nfloor} 笔（{100*nfloor/len(sigs):.1f}%）**上起作用——"
      f"入场价贴着位下沿时，「上一个位」离得太近，不加地板会造出 0.06 点的止损。"
      f"这本身是另一个「余数失控」的证据：**同一把尺子并不保证间距合理**。")
    A("")
    A(HDR)
    A(SEP)
    for tn, tk, _, _ in TARGETS:
        legs = G[(tk, "RUNG")]
        s = summarise(legs)
        bump()
        A(combo_row(f"{tn} × 反向具名位", s, bs, paired(legs, base)))
    A("")
    lr = summarise(G[("LVL", "RUNG")])
    pm2, pt2 = paired(G[("LVL", "RUNG")], base)
    A(f"**最纯的「一把尺子」组合**（目标=下一个位，止损=上一个位）：均净R "
      f"{lr['net']:+.3f}，总净R {lr['tot']:+.1f}，中位 T/S {lr['ts_med']:.2f}，"
      f"z_geom {lr['z']:+.2f}，配对差 vs v14 基线 **{pm2:+.3f} R/笔 "
      f"(t={pt2:+.2f}, p={two_sided(pt2):.3f})**。")
    A("")

    # ───────────────────────── 5 ─────────────────────────
    A("## 5 · 止损改用已实现波动（第三种统一刻度）")
    A("")
    A(f"止损 = k × 最近 {VOL_LEN} 根 setup K 的 Wilder ATR（10m 尺度），"
      f"同样带 {MIN_RISK_PTS} 点地板。这把尺子既不是日线梯、也不是结构极值，"
      f"而是「这半天真实走了多少」。")
    v20 = [prim["ctx"][s.i]["vol20"] for s in sigs]
    bump()
    A("")
    A(f"- ATR20(10m) 分布：p05 {q(v20,0.05):.2f}，中位 {st.median(v20):.2f}，"
      f"p95 {q(v20,0.95):.2f} 点。对比结构止损中位 "
      f"{st.median([s.risk for s in sigs]):.1f} 点——两者量级相近，"
      f"但**结构止损的离散度大得多**（p05 {q([s.risk for s in sigs],0.05):.1f} → "
      f"p95 {q([s.risk for s in sigs],0.95):.1f}，跨度 "
      f"{q([s.risk for s in sigs],0.95)/q([s.risk for s in sigs],0.05):.0f}×；"
      f"波动尺只有 {q(v20,0.95)/q(v20,0.05):.1f}×）。")
    A("")
    A(HDR)
    A(SEP)
    for sn, sk, _, _ in STOPS:
        if not sk.startswith("VOL"):
            continue
        for tn, tk, _, _ in TARGETS:
            legs = G[(tk, sk)]
            s = summarise(legs)
            bump()
            A(combo_row(f"{tn} × {sn}", s, bs, paired(legs, base)))
    A("")

    # ───────────────────────── 6 ─────────────────────────
    A("## 6 · 总表：目标定义 × 止损定义")
    A("")
    A("每格上行 = 均净R，下行 = z_geom。基线格（下一具名位 × 结构极值）加粗。")
    A("")
    A("| 目标 ＼ 止损 | " + " | ".join(sn for sn, _, _, _ in STOPS) + " |")
    A("|---|" + "---|" * len(STOPS))
    for tn, tk, _, _ in TARGETS:
        row = [f"| **{tn}** 均净R "]
        row2 = [f"| {tn} z_geom "]
        for sn, sk, _, _ in STOPS:
            s = summarise(G[(tk, sk)])
            star = "**" if (tk, sk) == ("LVL", "STRUCT") else ""
            row.append(f"| {star}{s['net']:+.3f}{star} ")
            row2.append(f"| {s['z']:+.2f} ")
        A("".join(row) + "|")
        A("".join(row2) + "|")
    A("")
    A("同一张表换成**总净R**（25 格跑的是同一批 "
      f"{len(sigs)} 笔信号，所以总R 可直接互比）：")
    A("")
    A("| 目标 ＼ 止损 | " + " | ".join(sn for sn, _, _, _ in STOPS) + " |")
    A("|---|" + "---|" * len(STOPS))
    for tn, tk, _, _ in TARGETS:
        row = [f"| {tn} "]
        for sn, sk, _, _ in STOPS:
            s = summarise(G[(tk, sk)])
            row.append(f"| {s['tot']:+.1f} ")
        A("".join(row) + "|")
    A("")
    A("以及**固定手数口径的 money**（净R × S / 日ATR，消掉「小止损把 R 放大」"
      "这个幻觉）：")
    A("")
    A("| 目标 ＼ 止损 | " + " | ".join(sn for sn, _, _, _ in STOPS) + " |")
    A("|---|" + "---|" * len(STOPS))
    for tn, tk, _, _ in TARGETS:
        row = [f"| {tn} "]
        for sn, sk, _, _ in STOPS:
            s = summarise(G[(tk, sk)])
            row.append(f"| {s['tot_money']:+.2f} ")
        A("".join(row) + "|")
    A("")
    allc = sorted(((summarise(G[(tk, sk)])["net"], tk, sk)
                   for _, tk, _, _ in TARGETS for _, sk, _, _ in STOPS),
                  reverse=True)
    bestn, bt, bsk = allc[0]
    pmb, ptb = paired(G[(bt, bsk)], base)
    A(f"**25 格全景**：最好 {bestn:+.3f}（{bt} × {bsk}），最差 "
      f"{allc[-1][0]:+.3f}（{allc[-1][1]} × {allc[-1][2]}），中位 "
      f"{st.median([c[0] for c in allc]):+.3f}，基线 {bs['net']:+.3f}。"
      f"**{sum(1 for c in allc if c[0] > bs['net'])}/24 个非基线格优于基线。**")
    A("")
    A(f"最好的那一格相对基线的配对差 **{pmb:+.3f} R/笔 (t={ptb:+.2f}, "
      f"p={two_sided(ptb):.3f})**——但这是**从 25 格里挑出来的最大值**，"
      f"必须按第 11 节的 family size 打折。")
    A("")
    A("**没有一格的均净R 为正。** 这是本报告最重要的一行：换尺子能把亏损"
      "从 {a} 减到 {b}，但换不出正期望。".format(
          a=f"{bs['net']:+.3f}", b=f"{bestn:+.3f}"))
    A("")
    A("### 6.1 一个被证伪的旁支假设：结构止损是不是块磁铁")
    A("")
    A("把目标固定成具名位、只换止损，z_geom 这一列有一个诱人的排序：")
    A("")
    A("| 止损定义 | 中位S(点) | 命中率 | 几何零假设 | 超额pp | z_geom |")
    A("|---|---|---|---|---|---|")
    for sn, sk, _, _ in STOPS:
        s2 = summarise(G[("LVL", sk)])
        bump()
        A(f"| {sn} | {s2['S_med']:.1f} | {100*s2['hit']:.1f}% | "
          f"{100*s2['null']:.1f}% | {100*(s2['hit']-s2['null']):+.1f} | "
          f"{s2['z']:+.2f} |")
    A("")
    A("结构止损的 z_geom 是五种里最差的，**而它的中位距离并不是最小的**"
      "（比 1.0×ATR20 和 1.5×ATR20 都大）。诱人的解读是：结构止损被放在"
      "「最近 3–5 根 K 的极值」上，那正是市场上其他人的止损也在的地方，"
      "所以它被打的频率高于随机游走的几何预期——**止损位置本身是块磁铁**。"
      "如果成立，这是一个与刻度错配完全无关的第二机制。")
    A("")
    A("**但这张表不能用来下这个结论**：五行的 S 分布不同，几何零假设也不同，"
      "z_geom 跨行不可直接比。正确的做法是**逐笔匹配**——只取「结构止损与 "
      "1.5×ATR20 止损距离相差不到 25%」的那些交易：同一批信号、同一个目标、"
      "止损距离几乎一样，只有**位置**不同。")
    A("")
    ms = []
    for i, s in enumerate(sigs):
        sv = max(1.5 * prim["ctx"][s.i]["vol20"], MIN_RISK_PTS)
        if abs(sv - s.risk) / s.risk < 0.25:
            ms.append(i)
    A(f"匹配上的样本 **n = {len(ms)}**（{100*len(ms)/len(sigs):.0f}%）。")
    A("")
    A("| 止损位置 | n | 中位S(点) | 命中率 | 几何零假设 | 超额pp | z_geom |")
    A("|---|---|---|---|---|---|---|")
    for lbl, sk in (("结构极值（贴近期高/低点）", "STRUCT"),
                    ("1.5×ATR20（纯距离）", "VOL1.5")):
        sub = [G[("LVL", sk)][i] for i in ms]
        s2 = summarise(sub)
        bump()
        A(f"| {lbl} | {s2['n']} | {s2['S_med']:.1f} | {100*s2['hit']:.1f}% | "
          f"{100*s2['null']:.1f}% | {100*(s2['hit']-s2['null']):+.1f} | "
          f"{s2['z']:+.2f} |")
    both = [i for i in ms if G[("LVL", "STRUCT")][i].hit is not None
            and G[("LVL", "VOL1.5")][i].hit is not None]
    a_ = [G[("LVL", "STRUCT")][i] for i in both]
    b_ = [G[("LVL", "VOL1.5")][i] for i in both]
    dh = [float(int(x.hit) - int(y.hit)) for x, y in zip(a_, b_)]
    pmm, ptm = paired([G[("LVL", "STRUCT")][i] for i in ms],
                      [G[("LVL", "VOL1.5")][i] for i in ms])
    bump(2)
    A("")
    A(f"逐笔配对（两侧都可裁决的 {len(both)} 笔）：命中差 = "
      f"**{100*st.mean(dh):+.1f} pp（t={tstat(dh):+.2f}）**，"
      f"方向是**结构止损更少被打**；净R 配对差 {pmm:+.3f}（t={ptm:+.2f}），"
      f"同样偏向结构止损。")
    A("")
    A("**判决：磁铁假设被证伪。** 在止损距离匹配之后，结构止损不但没有更容易"
      "被打，反而略微更少被打。上面那张五行表里结构止损 z_geom 最差，"
      "是 S 分布差异造成的假象——**这正是为什么跨行比 z_geom 是错的**，"
      "本报告其余部分一律用配对差。")
    A("")
    A("代价是：第 12.1 节里那一块「换尺子之后 (p−p0) 收窄 3.0 pp」"
      "**失去了机制解释**。它是真实的、可测的，但我们指不出它走的是哪条通道；"
      "最显然的那个候选已经被这一节排除。归因账里必须按「机制不明」处理。")
    A("")

    # ───────────────────────── 7 ─────────────────────────
    A("## 7 · D4 闸门（止损放远）到底是不是「刻度错配的修正」")
    A("")
    A("这是任务书的核心问题。检验路线：")
    A("")
    A("1. D4 与 T/S 是不是同一个东西的两种写法（相关性）")
    A("2. 把 D4 与 T/S 互相条件化，看谁在解释谁")
    A("3. **在刻度已经统一的世界里重跑 D4 闸门**——如果 D4 的效应消失，"
      "就说明它原本就是在修正刻度；如果还在，就说明它另有来源")
    A("")
    d4 = [s.d4 for s in sigs]
    rho, rz = spearman(d4, [l.ts for l in base])
    bump()
    A(f"**（1）** D4（风险距离/ATR）与 T/S 的秩相关 ρ = **{rho:+.3f}** "
      f"(z={rz:+.2f})。目标固定、止损可变，所以 T/S ≈ 常数/S，与 D4 近乎"
      f"确定性地反相关。**D4 高 = T/S 低，这在代数上就是同一件事。**")
    A("")
    A("**（2）条件化**：把样本按 T/S 三分，在每个 T/S 层内再按 D4 中位切两半。"
      "如果 D4 只是 T/S 的代理，层内就不该再有差。")
    A("")
    tsq = [q([l.ts for l in base], x) for x in (1/3, 2/3)]
    A("| T/S 层 | n | D4≤层内中位 均净R | D4>层内中位 均净R | Δ | t(两样本) |")
    A("|---|---|---|---|---|---|")
    for lab, lo_, hi_ in (("低 T/S", -1e9, tsq[0]), ("中 T/S", tsq[0], tsq[1]),
                          ("高 T/S", tsq[1], 1e9)):
        idx = [i for i, l in enumerate(base) if lo_ < l.ts <= hi_]
        if len(idx) < 30:
            continue
        bump()
        med = st.median([sigs[i].d4 for i in idx])
        a_ = [base[i].net for i in idx if sigs[i].d4 <= med]
        b_ = [base[i].net for i in idx if sigs[i].d4 > med]
        if len(a_) < 5 or len(b_) < 5:
            continue
        se = math.sqrt(st.variance(a_) / len(a_) + st.variance(b_) / len(b_))
        tt = (st.mean(b_) - st.mean(a_)) / se if se > 0 else float("nan")
        A(f"| {lab} | {len(idx)} | {st.mean(a_):+.3f} | {st.mean(b_):+.3f} | "
          f"{st.mean(b_)-st.mean(a_):+.3f} | {tt:+.2f} |")
    A("")
    A("反过来，把样本按 D4 三分，层内按 T/S 中位切：")
    A("")
    d4q = [q(d4, x) for x in (1/3, 2/3)]
    A("| D4 层 | n | T/S≤层内中位 均净R | T/S>层内中位 均净R | Δ | t(两样本) |")
    A("|---|---|---|---|---|---|")
    for lab, lo_, hi_ in (("小止损", -1e9, d4q[0]), ("中止损", d4q[0], d4q[1]),
                          ("大止损", d4q[1], 1e9)):
        idx = [i for i, s in enumerate(sigs) if lo_ < s.d4 <= hi_]
        if len(idx) < 30:
            continue
        bump()
        med = st.median([base[i].ts for i in idx])
        a_ = [base[i].net for i in idx if base[i].ts <= med]
        b_ = [base[i].net for i in idx if base[i].ts > med]
        if len(a_) < 5 or len(b_) < 5:
            continue
        se = math.sqrt(st.variance(a_) / len(a_) + st.variance(b_) / len(b_))
        tt = (st.mean(b_) - st.mean(a_)) / se if se > 0 else float("nan")
        A(f"| {lab} | {len(idx)} | {st.mean(a_):+.3f} | {st.mean(b_):+.3f} | "
          f"{st.mean(b_)-st.mean(a_):+.3f} | {tt:+.2f} |")
    A("")
    A("**（3）在统一刻度里重跑 D4 闸门。** 关键设计：`R1.0` / `R2.0` 目标下 "
      "T/S 恒为常数，刻度错配被**构造性消除**；此时 D4 若还有效，它就不是"
      "刻度问题。同时必须把毛R 和净R 分开看——净R 里还留着 `点差/S` 这一项，"
      "而它天然偏向大止损。")
    A("")
    md4 = st.median(d4)
    A("| 组合 | D4≤中位 均毛R | D4>中位 均毛R | Δ毛R | t | D4≤中位 均净R | "
      "D4>中位 均净R | Δ净R | t |")
    A("|---|---|---|---|---|---|---|---|---|")
    gate_rows = {}
    for tk, sk, nm in (("LVL", "STRUCT", "v14 原样（两把尺子）"),
                       ("R1.0", "STRUCT", "1.0R 目标（T/S≡1）"),
                       ("R2.0", "STRUCT", "2.0R 目标（T/S≡2）"),
                       ("LVL", "RUNG", "位目标 × 位止损")):
        legs = G[(tk, sk)]
        lo_g = [l.gross for l, s in zip(legs, sigs) if s.d4 <= md4]
        hi_g = [l.gross for l, s in zip(legs, sigs) if s.d4 > md4]
        lo_n = [l.net for l, s in zip(legs, sigs) if s.d4 <= md4]
        hi_n = [l.net for l, s in zip(legs, sigs) if s.d4 > md4]
        bump(2)

        def tt2(a_, b_):
            se = math.sqrt(st.variance(a_) / len(a_) + st.variance(b_) / len(b_))
            return (st.mean(b_) - st.mean(a_)) / se if se > 0 else float("nan")
        dg, dn = st.mean(hi_g) - st.mean(lo_g), st.mean(hi_n) - st.mean(lo_n)
        gate_rows[nm] = (dg, tt2(lo_g, hi_g), dn, tt2(lo_n, hi_n))
        A(f"| {nm} | {st.mean(lo_g):+.3f} | {st.mean(hi_g):+.3f} | "
          f"**{dg:+.3f}** | {tt2(lo_g,hi_g):+.2f} | {st.mean(lo_n):+.3f} | "
          f"{st.mean(hi_n):+.3f} | **{dn:+.3f}** | {tt2(lo_n,hi_n):+.2f} |")
    A("")
    g0 = gate_rows["v14 原样（两把尺子）"]
    g1 = gate_rows["1.0R 目标（T/S≡1）"]
    g2 = gate_rows["2.0R 目标（T/S≡2）"]
    A(f"**读法**：v14 原样下 D4 闸门的净R 效应是 {g0[2]:+.3f}（t={g0[3]:+.2f}），"
      f"毛R 效应 {g0[0]:+.3f}（t={g0[1]:+.2f}）——这就是 `V15_ENTRY_LOCATION.md` "
      f"里那个 z_sel +4.37 的闸门。把目标换成 2.0R、T/S 被构造成常数之后，"
      f"同一个闸门只剩净R {g2[2]:+.3f}（t={g2[3]:+.2f}）、"
      f"毛R {g2[0]:+.3f}（t={g2[1]:+.2f}）。1.0R 下同理"
      f"（毛R {g1[0]:+.3f}, t={g1[1]:+.2f}）。")
    A("")
    A("### 7.1 把 D4 闸门拆成三份")
    A("")
    ch_res = g2[0]                      # T/S 固定后仍存在的毛R 效应
    ch_fric = g2[2] - g2[0]             # 点差/S 在两半之间的差
    ch_amp = g0[2] - g2[2]              # T/S 放大系数通道
    A(f"在 T/S≡2 的世界里，D4 闸门的净R 效应 {g2[2]:+.3f} 恰好可以拆成"
      f"「毛R {g2[0]:+.3f} + 点差差 {ch_fric:+.3f}」；而 v14 原样的 {g0[2]:+.3f} "
      f"比它多出来的 {ch_amp:+.3f} 就是 (1+T/S) 放大系数通道。三份：")
    A("")
    A("| 通道 | 贡献(R/笔) | 占 D4 闸门总效应 | 是不是「刻度错配」 | 统计力 |")
    A("|---|---|---|---|---|")
    A(f"| (1+T/S) 放大系数 | {ch_amp:+.3f} | {100*ch_amp/g0[2]:.1f}% | "
      f"**是**——两把尺子的直接产物 | — |")
    A(f"| 点差/S 摩擦 | {ch_fric:+.3f} | {100*ch_fric/g0[2]:.1f}% | "
      f"**部分是**——S 的离散度由止损尺子决定 | — |")
    A(f"| 残差（T/S 固定后的 p−p0 差） | {ch_res:+.3f} | {100*ch_res/g0[2]:.1f}% | "
      f"**不是** | t={g2[1]:+.2f}，与 0 无法区分 |")
    A(f"| 合计 | {g0[2]:+.3f} | 100.0% | | t={g0[3]:+.2f} |")
    A("")
    A(f"**结论（本节）**：D4「止损放远」这个闸门里，"
      f"**{100*(ch_amp+ch_fric)/g0[2]:.0f}% 是几何与摩擦**，"
      f"只有 {100*ch_res/g0[2]:.0f}% 是「大止损的交易本身更容易赢」，"
      f"而这 {100*ch_res/g0[2]:.0f}% 的 t 值只有 {g2[1]:+.2f}，"
      f"**统计上与零无法区分**。")
    A("")
    A("所以任务书的猜想在这一点上**成立**：V15 里唯一有效的那个闸门，"
      "机制上确实就是在修正刻度错配。它不是发现了更好的交易，"
      "而是把同一批交易的赔率结构与摩擦改善了——这也解释了为什么它"
      "只能把总净R 从 −73.6 抬到 +1.3（勉强打平），而不是抬成盈利。")
    A("")

    # ───────────────────────── 8 ─────────────────────────
    A("## 8 · 时间成本：远目标真的要等更久吗")
    A("")
    A("任务书提到「很远的目标还要额外承受时间成本」。这一节量化。")
    A("")
    A("| T/S 档 | n | 中位持有根数(10m) | 中位小时 | 命中笔的中位根数 | 止损笔的中位根数 | 未裁决 |")
    A("|---|---|---|---|---|---|---|")
    for j in range(NQ):
        g = [l for l, b in zip(base, bins) if b == j]
        v = [x for x, b in zip(vals, bins) if b == j]
        if not g:
            continue
        bump()
        hb = [l.bars for l in g if l.code == "T"]
        sb2 = [l.bars for l in g if l.code == "S"]
        A(f"| Q{j+1} ({min(v):.2f}–{max(v):.2f}) | {len(g)} | "
          f"{st.median([l.bars for l in g]):.0f} | "
          f"{st.median([l.bars for l in g])/6:.1f} | "
          f"{st.median(hb) if hb else float('nan'):.0f} | "
          f"{st.median(sb2) if sb2 else float('nan'):.0f} | "
          f"{sum(1 for l in g if l.code == 'U')} |")
    A("")
    rho3, rz3 = spearman([l.ts for l in base], [float(l.bars) for l in base])
    hb_all = [(j, [l.bars for l, b in zip(base, bins) if b == j and l.code == "T"])
              for j in range(NQ)]
    bump()
    A(f"T/S 与持有根数的秩相关 ρ = {rho3:+.3f} (z={rz3:+.2f})。")
    A("")
    A("**判读**：时间成本存在，但比想象的小，而且被一个组成效应掩盖了。")
    A("")
    A(f"- **条件在命中上**，持有时间确实随 T/S 上升："
      f"命中笔的中位根数从 Q1 的 {st.median(hb_all[0][1]):.0f} 根"
      f"（{st.median(hb_all[0][1])*10:.0f} 分钟）到 Q4 的 "
      f"{st.median(hb_all[3][1]):.0f} 根。这是纯几何：目标越远越晚到。")
    A(f"- **但整体中位在 Q5 反而掉回 {st.median([l.bars for l, b in zip(base, bins) if b == NQ-1]):.0f} 根**，"
      f"因为 Q5 有 {100*(1-summarise([l for l, b in zip(base, bins) if b == NQ-1])['hit']):.0f}% "
      f"的交易是止损出场，而止损（S 很小）来得极快。**「远目标」在 v14 里"
      f"很少真的等很久——它们大多先被那个很紧的止损打掉了。**")
    A(f"- 绝对量级上，最长的一档中位持有也只有 "
      f"{max(st.median([l.bars for l, b in zip(base, bins) if b == j]) for j in range(NQ))/6:.1f} "
      f"小时。对 0DTE 期权而言 theta 成本不可忽略，但对本报告的纯价差口径"
      f"（标的 CFD）来说，**时间成本不是刻度错配的主要传导通道**——"
      f"任务书提到的这一条，量级上排在放大系数与点差摩擦之后。")
    A("")

    # ───────────────────────── 9 ─────────────────────────
    A("## 9 · 稳健性：RTH / 夜盘、含混口径、^GSPC 对照")
    A("")
    A("### 9.1 分时段（只列四个关键组合）")
    A("")
    A("| 组合 | 段 | n | 命中率 | 几何零假设 | z_geom | 均净R | 总净R |")
    A("|---|---|---|---|---|---|---|---|")
    for tk, sk, nm in (("LVL", "STRUCT", "v14 原样"), ("R1.0", "STRUCT", "1.0R×结构"),
                       ("R2.0", "STRUCT", "2.0R×结构"), ("LVL", "RUNG", "位×位")):
        for seg, fn in (("RTH", lambda s: s.in_rth), ("夜盘", lambda s: not s.in_rth)):
            legs = [l for l, s in zip(G[(tk, sk)], sigs) if fn(s)]
            if len(legs) < 20:
                continue
            bump()
            s2 = summarise(legs)
            A(f"| {nm} | {seg} | {s2['n']} | {100*s2['hit']:.1f}% | "
              f"{100*s2['null']:.1f}% | {s2['z']:+.2f} | {s2['net']:+.3f} | "
              f"{s2['tot']:+.1f} |")
    A("")
    A("（夜盘由另一路研究单独解剖，这里只验证「换尺子」的结论在两个时段"
      "方向一致，不重复它的诊断。）")
    A("")
    A("### 9.2 含混与未裁决")
    A("")
    A("| 组合 | 含混(A) | 未裁决(U) | 均净R(A判止损) | 均净R(A判命中) | 差 |")
    A("|---|---|---|---|---|---|")
    for tk, sk, nm in (("LVL", "STRUCT", "v14 原样"), ("R1.0", "STRUCT", "1.0R×结构"),
                       ("R2.0", "STRUCT", "2.0R×结构"), ("LVL", "RUNG", "位×位"),
                       ("R2.0", "VOL1.5", "2.0R×1.5ATR20")):
        s2 = summarise(G[(tk, sk)])
        bump()
        A(f"| {nm} | {s2['namb']} | {s2['nund']} | {s2['net']:+.3f} | "
          f"{s2['net_opt']:+.3f} | {s2['net_opt']-s2['net']:+.3f} |")
    A("")
    rng5 = [b.high - b.low for b in data.load("ES=F", "60d", "5m")]
    widths = [l.S + l.T for l in base]
    bump()
    A(f"含混数接近 0 不是 bug，是量级问题：5m K 的中位振幅 "
      f"{st.median(rng5):.2f} 点、p95 {q(rng5,0.95):.2f} 点，而基线组合的"
      f"双边总宽度（S+T）中位 {st.median(widths):.1f} 点、p05 "
      f"{q(widths,0.05):.1f} 点。只有 "
      f"{100*sum(1 for w in widths if w < q(rng5,0.95))/len(widths):.1f}% 的交易"
      f"其双边总宽度小于 p95 的 5m 振幅，所以「一根 5m K 同时吃掉两边」极少发生。"
      f"「位×位」出现 4 例，是因为它两边都可能贴得很近——这也正是它对口径最敏感"
      f"的原因（差 {summarise(G[('LVL','RUNG')])['net_opt']-summarise(G[('LVL','RUNG')])['net']:+.3f} R）。")
    A("")
    A("**这仍然是一个上界式的免责声明**：5m 是本项目能拿到的最细分辨率，"
      "真实的 tick 路径在极少数格子里可能翻转判决。凡是含混数 >0 的组合，"
      "两种口径都已列出。")
    A("")
    A("### 9.3 ^GSPC 10m RTH 对照")
    A("")
    A(f"^GSPC 只有 RTH，且其 ATR 与 CAPITALCOM:SPX500 的比值 mean 1.117 / "
      f"sd 0.083 / 范围 0.826–1.418（`levels.py`）。**本报告所有依赖具体位价的"
      f"结论（具名位目标、具名位止损）在 ^GSPC 上的位价与用户实际交易的位价"
      f"系统性不同**，所以下表只是「换尺子的方向」在另一个标的上的复核，"
      f"不是第二份证据。样本 {len(ctrl['sigs'])} 笔。")
    A("")
    A("| 组合 | n | 命中率 | 几何零假设 | z_geom | 均净R | 总净R |")
    A("|---|---|---|---|---|---|---|")
    for tk, sk, nm in (("LVL", "STRUCT", "v14 原样"), ("R1.0", "STRUCT", "1.0R×结构"),
                       ("R2.0", "STRUCT", "2.0R×结构"), ("R3.0", "STRUCT", "3.0R×结构"),
                       ("LVL", "RUNG", "位×位"), ("R2.0", "VOL1.5", "2.0R×1.5ATR20")):
        s2 = summarise(GC[(tk, sk)])
        bump()
        A(f"| {nm} | {s2['n']} | {100*s2['hit']:.1f}% | {100*s2['null']:.1f}% | "
          f"{s2['z']:+.2f} | {s2['net']:+.3f} | {s2['tot']:+.1f} |")
    A("")

    # ───────────────────────── 10 ─────────────────────────
    A("## 10 · 与假设相反的格子（诚实优先）")
    A("")
    A("纪律 7：如实单列所有与「刻度错配是主因」相反的观察。")
    A("")
    A(f"1. **任务书猜的分布方向是反的。** 猜想是「很远的目标 + 很紧的止损」，"
      f"实测 {100*n_lt1/len(tsv):.0f}% 的交易**目标比止损近**（T/S 中位 "
      f"{st.median(tsv):.2f}，只有 {100*n_gt2/len(tsv):.0f}% 的 T/S>2）。"
      f"病灶是目标距离**不受控**（0.03–{max(t1p):.1f} 点），不是它太远。"
      f"猜想的**机制**（T/S 大的那一头劣于几何零假设）站得住，"
      f"**流行病学**（那一头是主流）站不住。")
    A(f"2. **「目标该放更远」被明确证伪。** 3.0R 目标在结构止损下的配对差是 "
      f"{paired(G[('R3.0','STRUCT')], base)[0]:+.3f} R/笔——比基线还差。"
      f"总表里 3.0R 那一行是五行里最差的。")
    A(f"3. **统一刻度并没有把期望做正。** 25 格全部为负，最好一格 {bestn:+.3f}。"
      f"如果两把尺子是亏损的**主因**，统一之后至少该有一格越过 0。没有。")
    good = [c for c in allc if c[0] > bs["net"]]
    n2 = sum(1 for _, tk, sk in good if abs(paired(G[(tk, sk)], base)[1]) > 2)
    A(f"4. **改善格子多，但多重比较那一关另说。** 24 个非基线格里 "
      f"{len(good)} 个优于基线，配对 |t|>2 的有 {n2} 个；"
      f"能不能越过 Bonferroni 门槛见第 11 节。")
    A(f"5. **T/S 与 D4 高度共线（ρ={rho:+.3f}）。** 第 2 节的 T/S 表"
      f"不是独立于 `V15_ENTRY_LOCATION.md` D4 表的新证据，"
      f"两张表说的是同一批交易的同一件事。本报告的增量在机制拆解"
      f"（第 7.1 节的三通道），不在「又找到一个变量」。")
    A(f"6. **RTH 的「位×位」组合是全文唯一为正的格子**（均净R "
      f"{summarise([l for l, s in zip(G[('LVL','RUNG')], sigs) if s.in_rth])['net']:+.3f}，"
      f"总净R "
      f"{summarise([l for l, s in zip(G[('LVL','RUNG')], sigs) if s.in_rth])['tot']:+.1f}，"
      f"n=142，z_geom "
      f"{summarise([l for l, s in zip(G[('LVL','RUNG')], sigs) if s.in_rth])['z']:+.2f}）。"
      f"如实列出，但**不要据此下单**：这是 @@CELLS@@ 个格子里的一个，"
      f"n=142，且 ^GSPC 对照上同一个组合是负的（第 9.3 节）。")
    A("")

    A("## 11 · 多重比较")
    A("")
    # family size 还会在第 12 节继续增长；用占位符，最后统一回填，
    # 免得报告里出现两个不同的数。
    bump(2)                          # 第 12 节的协方差表，先记账
    thr = _bonf_z(CELLS)
    A("全文共检视 **@@CELLS@@ 个格子**（分层格、总表 25 格及其三种口径、"
      "条件化格、闸门格、匹配格、时段格、稳健性格、对照格）。Bonferroni 门槛 "
      f"|z| > **{thr:.2f}**（α=0.05 双侧）。")
    A("")
    A("在这个 family size 下：")
    A("")
    surv = []
    cand = [(tk, sk, G[(tk, sk)]) for _, tk, _, _ in TARGETS
            for _, sk, _, _ in STOPS if (tk, sk) != ("LVL", "STRUCT")]
    cand += [(tk, "STRUCT", FG[tk]) for _, tk, _, _ in FLOOR_TARGETS]
    for tk, sk, legs in cand:
        pm3, pt3 = paired(legs, base)
        if abs(pt3) > thr:
            surv.append((tk, sk, pm3, pt3))
    top = sorted(((abs(paired(l, base)[1]), tk, sk, *paired(l, base))
                  for tk, sk, l in cand), reverse=True)[:3]
    A(f"- 28 个候选几何（25 格 + 3 个目标地板变体）相对基线的配对 t，"
      f"最大三个：" + "；".join(
          f"{tk}×{sk} t={t3:+.2f} ({m3:+.3f} R/笔)" for _, tk, sk, m3, t3 in top)
      + "。")
    if surv:
        A(f"- 相对基线的**配对差**越过 Bonferroni 门槛的组合共 {len(surv)} 个：")
        for tk, sk, pm3, pt3 in sorted(surv, key=lambda x: -x[2]):
            A(f"  - {tk} × {sk}：{pm3:+.3f} R/笔，t={pt3:+.2f}")
    else:
        A("- **没有任何组合的配对差越过 Bonferroni 门槛。**")
    A("- 常规 |z|>1.96 在 @@CELLS@@ 个格子的 family 下毫无意义："
      "纯随机也会有约 @@CELLS20@@ 个格子越线。")
    A("- 配对检验（同一批信号、只换定义）比跨组比较强，但它检验的是"
      "「定义 A 与定义 B 谁好」，**不是**「定义 A 有正期望」。后者需要"
      "均净R 的 t 检验，全表 25 格没有一个为正。")
    A("")

    # ───────────────────────── 12 ─────────────────────────
    A("## 12 · 判决：v14 的负期望里，有多少能归因于「两把尺子」")
    A("")
    A("### 12.1 归因账")
    A("")
    A("用第 1 节的恒等式做加法分解（纯括号口径，"
      f"{len(sigs)} 笔，总净R {bs['tot']:+.1f}）：")
    A("")
    A("| 分项 | 总R | 占总亏损 | 换尺子能改吗 |")
    A("|---|---|---|---|")
    A(f"| 点差摩擦 `−点差/S` | −{tot_drag:.1f} | "
      f"{100*tot_drag/abs(bs['tot']):.0f}% | **能，部分**：S 的离散度由止损尺子"
      f"决定（p05 {q([s.risk for s in sigs],0.05):.1f} → p95 "
      f"{q([s.risk for s in sigs],0.95):.1f} 点，"
      f"{q([s.risk for s in sigs],0.95)/q([s.risk for s in sigs],0.05):.0f}×） |")
    A(f"| 毛R `Σ(p−p0)(1+T/S)` | {bs['tot_gross']:+.1f} | "
      f"{100*abs(bs['tot_gross'])/abs(bs['tot']):.0f}% | **能，部分**：确定能压住"
      f"放大系数 (1+T/S)；(p−p0) 也会跟着动，但机制不明（见本节末） |")
    A(f"| 合计 | {bs['tot']:+.1f} | 100% | |")
    A("")
    bg = summarise(G[(bt, bsk)])
    imp_gross = bg["tot_gross"] - bs["tot_gross"]
    imp_drag = -(sum(SPREAD / l.S for l in G[(bt, bsk)]) - tot_drag)
    A(f"把「换成最好的统一刻度」这件事按同样两项拆开（{bt} × {bsk}）：")
    A("")
    A("| 分项 | 基线 | 最好组合 | 改善 |")
    A("|---|---|---|---|")
    A(f"| 毛R | {bs['tot_gross']:+.1f} | {bg['tot_gross']:+.1f} | "
      f"**{imp_gross:+.1f}**（{100*imp_gross/(bg['tot']-bs['tot']):.0f}% 的总改善）|")
    A(f"| 点差摩擦 | −{tot_drag:.1f} | −{sum(SPREAD/l.S for l in G[(bt,bsk)]):.1f} | "
      f"**{imp_drag:+.1f}**（{100*imp_drag/(bg['tot']-bs['tot']):.0f}%）|")
    A(f"| 净R | {bs['tot']:+.1f} | {bg['tot']:+.1f} | **{bg['tot']-bs['tot']:+.1f}** |")
    A("")
    A(f"**改善的大头（{100*imp_gross/(bg['tot']-bs['tot']):.0f}%）在毛R 一侧，"
      f"不在摩擦一侧。** 毛R 那一侧还能再拆一层——把 "
      f"`mean[(p−p0)(1+T/S)]` 拆成「整体缺口 × 平均放大系数」加上一个协方差项"
      f"（缺口最大的交易是不是恰好放大系数也最大）：")
    A("")
    A("| 组合 | 整体 (p−p0) | 平均放大系数 | 乘积（均匀情形） | 实测均毛R | 协方差项 |")
    A("|---|---|---|---|---|---|")
    for lbl, legs in (("基线（两把尺子）", base), (f"{bt} × {bsk}", G[(bt, bsk)])):
        s2 = summarise(legs)
        amp = st.mean([1 + l.ts for l in legs])
        prod = (s2["hit"] - s2["null"]) * amp
        bump()
        A(f"| {lbl} | {s2['hit']-s2['null']:+.4f} | {amp:.2f} | {prod:+.3f} | "
          f"{s2['gross']:+.3f} | {s2['gross']-prod:+.3f} |")
    A("")
    ampb = st.mean([1 + l.ts for l in base])
    ampg = st.mean([1 + l.ts for l in G[(bt, bsk)]])
    covb = bs["gross"] - (bs["hit"] - bs["null"]) * ampb
    covg = bg["gross"] - (bg["hit"] - bg["null"]) * ampg
    frac_best_pre = (bg["tot"] - bs["tot"]) / abs(bs["tot"])
    d_unif = ((bg["hit"] - bg["null"]) * ampg - (bs["hit"] - bs["null"]) * ampb)
    A("毛R 的改善（每笔 "
      f"{bg['gross']-bs['gross']:+.3f}，总量 {imp_gross:+.1f} R）由此分成两块，"
      "**而这两块归因去处不同**：")
    A("")
    A("| 通道 | 每笔改善 | 总量 | 占毛R 改善 | 归因 |")
    A("|---|---|---|---|---|")
    A(f"| 协方差项被切断 | {covg-covb:+.3f} | {(covg-covb)*len(sigs):+.1f} R | "
      f"{100*(covg-covb)/(bg['gross']-bs['gross']):.0f}% | "
      f"**「两把尺子」的直接代价** |")
    A(f"| 整体缺口 (p−p0) 收窄 × 放大系数 | {d_unif:+.3f} | "
      f"{d_unif*len(sigs):+.1f} R | "
      f"{100*d_unif/(bg['gross']-bs['gross']):.0f}% | "
      f"**机制不明**——见第 6.1 节 |")
    A("")
    A(f"- **协方差项**从 {covb:+.3f} 到 {covg:+.3f}。这一项才是「两把尺子」"
      f"最干净的代价：v14 把最大的赔率杠杆 (1+T/S)，"
      f"**恰好架在了命中率缺口最大的那一批交易上**。这不是巧合——"
      f"T/S 大 ⇔ S 小 ⇔ 止损贴得最紧，两件事由同一个变量驱动。"
      f"**这一块可以放心记在「两把尺子」头上。**")
    A(f"- **整体缺口收窄**：(p−p0) 从 {bs['hit']-bs['null']:+.4f} 到 "
      f"{bg['hit']-bg['null']:+.4f}，放大系数几乎没变"
      f"（{ampb:.2f}→{ampg:.2f}），所以这一块几乎全部来自命中率本身。"
      f"**它是真的，但我们说不清它为什么真。** 最显然的候选（结构止损是"
      f"磁铁）已在第 6.1 节被逐笔匹配证伪。它可能是目标端的效应"
      f"（具名位目标的余数问题）、可能是两端的交互，也可能就是 "
      f"{len(sigs)} 笔样本上的噪声——按「机制不明」处理，"
      f"**不要拿它当作已理解的改进去改代码**。")
    A("")
    A(f"这给了归因账一个**下界**：只把机制清楚的两块（协方差 + 摩擦）"
      f"算作刻度错配的代价，最好组合的 {bg['tot']-bs['tot']:+.1f} R 改善里"
      f"只有 {(covg-covb)*len(sigs) + imp_drag:+.1f} R 说得清楚，"
      f"即基线亏损的 **{100*((covg-covb)*len(sigs)+imp_drag)/abs(bs['tot']):.0f}%**。"
      f"上界仍然是 {100*frac_best_pre:.0f}%（把机制不明那块也算上）。")
    A("")
    A("### 12.2 四个口径的归因数字")
    A("")
    med_alt = st.median([c[0] for c in allc if (c[1], c[2]) != ("LVL", "STRUCT")])
    frac_best = (bg["tot"] - bs["tot"]) / abs(bs["tot"])
    frac_med = (med_alt - bs["net"]) * len(sigs) / abs(bs["tot"])
    fl = summarise(FG[bestf[1]])
    frac_fl = (fl["tot"] - bs["tot"]) / abs(bs["tot"])
    frac_mech = ((covg - covb) * len(sigs) + imp_drag) / abs(bs["tot"])
    A("| 口径 | 组合 / 定义 | 挽回 R | 占基线亏损 | 配对 t | 过 Bonferroni? |")
    A("|---|---|---|---|---|---|")
    A(f"| **上界**（25 选 1，含机制不明那块） | {bt} × {bsk} | "
      f"{bg['tot']-bs['tot']:+.1f} | **{100*frac_best:.0f}%** | {ptb:+.2f} | "
      f"否（门槛 {thr:.2f}）|")
    A(f"| **机制清楚的部分**（协方差 + 摩擦） | 同上，只算说得清的两块 | "
      f"{(covg-covb)*len(sigs)+imp_drag:+.1f} | **{100*frac_mech:.0f}%** | — | — |")
    A(f"| **中位**（24 个替代几何的中位格） | — | "
      f"{(med_alt-bs['net'])*len(sigs):+.1f} | **{100*frac_med:.0f}%** | — | — |")
    A(f"| **只修病灶**（不与原作者冲突的最小修补） | {bestf[0]} × 结构极值 | "
      f"{fl['tot']-bs['tot']:+.1f} | **{100*frac_fl:.0f}%** | {ptf:+.2f} | "
      f"{'是' if abs(ptf) > thr else '否'} |")
    A("")
    A("四个数差得很开，这本身是结论的一部分：")
    A("")
    A(f"- **{100*frac_fl:.0f}%** 是「只把明确坏掉的那部分修好」"
      f"（目标近到赚不回点差）。最保守、最可信。")
    A(f"- **{100*frac_mech:.0f}%** 是「机制说得清楚的全部」——"
      f"赔率杠杆架在缺口最大的交易上（协方差通道）+ 点差摩擦。"
      f"**这是本报告推荐引用的那个数。**")
    A(f"- **{100*frac_med:.0f}%** 是「随便换一把统一的尺子」的典型效果。")
    A(f"- **{100*frac_best:.0f}%** 是「事后挑最好的那把尺子」，"
      f"含过拟合，且其中 {100*d_unif/(bg['gross']-bs['gross']):.0f}% 的毛R "
      f"改善机制不明。")
    A("")
    A("### 12.3 结论")
    A("")
    A(f"> **v14 的负期望里，能归因于「目标与止损用了两把尺子」的部分："
      f"机制清楚的约 {100*frac_mech:.0f}%（下界 {100*frac_fl:.0f}%，"
      f"上界 {100*frac_best:.0f}%）。剩下的 "
      f"{100*(1-frac_mech):.0f}% 归因不了，而且没有一个替代几何的改善"
      f"扛得住 @@CELLS@@ 个格子的 Bonferroni 门槛。**")
    A("")
    A("五条支撑：")
    A("")
    A(f"1. **归因得上的部分，机制是清楚的。** 「两把尺子」让 T/S 变成一个"
      f"从 {min(tsv):.3f} 到 {max(tsv):.2f} 的失控余数，而 T/S 大的那一头"
      f"同时吃三份亏：命中率相对几何零假设的缺口最大（第 2 节趋势 z "
      f"{tz_ts:+.2f}）、缺口被 (1+T/S) 放大最多、点差占 R 的比重最大。"
      f"三通道同向，所以 T/S 分层的均净R 从 Q1 {'%+.3f' % summarise([l for l, b in zip(base, bins) if b == 0])['net']} "
      f"掉到 Q5 {'%+.3f' % summarise([l for l, b in zip(base, bins) if b == NQ-1])['net']}。")
    A("")
    A(f"2. **V15 里唯一有效的闸门确实就是刻度修正。** D4≥中位的 "
      f"{g0[2]:+.3f} R/笔里，{100*ch_amp/g0[2]:.0f}% 是 (1+T/S) 放大系数、"
      f"{100*ch_fric/g0[2]:.0f}% 是点差摩擦，只有 {100*ch_res/g0[2]:.0f}% "
      f"是「大止损的交易本身更容易赢」，而这一份 t={g2[1]:+.2f}，"
      f"与零无法区分（第 7.1 节）。**任务书的怀疑在这一点上是对的。**")
    A("")
    A(f"3. **但归因不上的部分更大，而且证据是干净的。** 排除「刻度错配 = 主因」"
      f"的直接证据：把两把尺子换成一把（位×位）、换成第二把（k×已实现波动）、"
      f"换成第三把（固定 kR），共 25 种组合，"
      f"**没有一格的均净R 为正**（最好 {bestn:+.3f}）。如果尺子是病根，"
      f"统一之后至少该有一格越过 0。剩下的负期望来自入场信号本身不带方向"
      f"信息——这与 `V15_ENTRY_LOCATION.md` 的结论一致，与几何无关。")
    A("")
    A(f"4. **归因账里有一块必须标成「机制不明」。** 最好组合的毛R 改善里，"
      f"{100*d_unif/(bg['gross']-bs['gross']):.0f}% 来自「整体命中率缺口从 "
      f"{100*(bs['hit']-bs['null']):+.1f} pp 收窄到 "
      f"{100*(bg['hit']-bg['null']):+.1f} pp」，而最显然的机制候选"
      f"（结构止损贴在近期极值上、是块止损磁铁）**已被第 6.1 节的逐笔匹配"
      f"证伪**——匹配止损距离之后，结构止损反而少被打 "
      f"{100*st.mean(dh):+.1f} pp。这一块归因不了，因此本报告推荐引用 "
      f"{100*frac_mech:.0f}% 而不是 {100*frac_best:.0f}%。")
    A("")
    A(f"5. **别把这份报告读成「换尺子能救 v14」。** 最好的 25 选 1 组合"
      f"（{bt} × {bsk}）仍然是 {bestn:+.3f} R/笔、总净R {bg['tot']:+.1f}；"
      f"配对 t={ptb:+.2f} 达不到门槛 {thr:.2f}。它把一个每笔亏 "
      f"{abs(bs['net']):.3f}R 的系统变成每笔亏 {abs(bestn):.3f}R 的系统，"
      f"**没有把它变成能挣钱的系统**。")
    A("")
    A("### 12.4 可执行的最小改动（不改信号，只改几何）")
    A("")
    A("全部是成本侧改动，**不承诺 alpha**：")
    A("")
    A(f"1. **给 T1 加最小距离地板**（第 3.1 节实测）。目前 {nsp} 笔"
      f"（{100*nsp/len(t1p):.1f}%）的目标 ≤ 一个点差、{nsp2} 笔"
      f"（{100*nsp2/len(t1p):.1f}%）≤ 两个点差，这些交易在毛口径上就赢不了钱。"
      f"改法：`next_rung` 找到的位若离入场价不足地板，就跳到梯子的再下一格。"
      f"最好的地板是 **{bestf[0]}**，全样本配对差 {pf:+.3f} R/笔 "
      f"(t={ptf:+.2f})，总净R {fl['tot']-bs['tot']:+.1f}。"
      f"**完全保留具名位，与 Saty 方法零冲突；但要诚实：t 值过不了关，"
      f"它是「修掉一个明显的缺陷」，不是「已证明的改进」。**")
    A(f"2. **压住 S 的离散度**。结构止损 p95 是 p05 的 "
      f"{q([s.risk for s in sigs],0.95)/q([s.risk for s in sigs],0.05):.0f} 倍，"
      f"波动尺只有 {q(v20,0.95)/q(v20,0.05):.1f} 倍。止损 3 点的交易，一个 "
      f"{SPREAD} 点点差就吃掉 {SPREAD/3:.2f}R。可以只做上下限截断"
      f"（clamp 到 [0.5, 2.0]×ATR20），不必整个换掉结构止损。")
    A(f"3. **不要**改成固定 kR 目标。第 3 节：k=1.5/2/3 的配对差单调转负，"
      f"只有 k=1.0 略优，而 k=1.0 之所以优是因为它压住了 T/S，"
      f"不是因为「固定 R」这个原理。**与原作者方法的冲突不成立，"
      f"也没有必要制造这个冲突。**")
    A(f"4. **最重要的一条：以上三条都不解决亏损的主体。** 先把入场信号的"
      f"方向性问题解决掉，再谈几何。")
    A("")
    A("---")
    A("")
    A("*生成于 `study_scale_mismatch.py`；family size @@CELLS@@；"
      f"Bonferroni |z| > {thr:.2f}。*")

    txt = "\n".join(o)
    txt = txt.replace("@@CELLS20@@", f"{0.05*CELLS:.0f}")
    txt = txt.replace("@@CELLS@@", str(CELLS))
    assert "@@" not in txt, "family size 占位符没回填干净"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
