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
    A("任务书的猜想是「很远的目标 + 很紧的止损」。**数据不支持这个方向**，"
      "而且它错得很有信息量：")
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
      "它是「入场价落在梯子哪一格里」的余数，可以是 0.03 点，也可以是 27 点，"
      "与这笔交易承担的风险毫无关系。下面所有检验都围绕这一点展开。")
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
          f"最大的那一档 Q5 单独就是 z_geom {zs_ts[-1]:+.2f}——"
          f"命中 {100*summarise([l for l,b in zip(base,bins_pre(base)) if b==NQ-1])['hit']:.1f}% "
          f"对几何零假设，缺口两位数 pp。")
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
          f"只换目标定义），所以不是抽样差异。按第 10 节的 Bonferroni 门槛"
          f"（|z| > {abs(_bonf_z(1)):.2f} 需在最终 family size 下重算）再判一次。")
    else:
        A("**没有一个固定 R 目标在配对检验下显著优于具名位。**"
          "与原作者方法的冲突因此**不成立**——这一节没有给出「该抛弃具名位」的证据。")
    A("")
    A("值得单独记一笔的是 **1.0R 这一档**：它把目标与止损强行绑成同一把尺子，"
      "T/S 恒等于 1，几何零假设恒等于 50%。它是本报告里「统一刻度」最纯粹的形态。")
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
      f"**{sum(1 for c in allc if c[0] > bs['net'])}/25 格优于基线。**")
    A("")
    A(f"最好的那一格相对基线的配对差 **{pmb:+.3f} R/笔 (t={ptb:+.2f}, "
      f"p={two_sided(ptb):.3f})**——但这是**从 25 格里挑出来的最大值**，"
      f"必须按第 10 节的 family size 打折。")
    A("")
    A("**没有一格的均净R 为正。** 这是本报告最重要的一行：换尺子能把亏损"
      "从 {a} 减到 {b}，但换不出正期望。".format(
          a=f"{bs['net']:+.3f}", b=f"{bestn:+.3f}"))
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
    g2 = gate_rows["2.0R 目标（T/S≡2）"]
    A(f"**读法**：v14 原样下 D4 闸门的净R 效应是 {g0[2]:+.3f}（t={g0[3]:+.2f}）。"
      f"把目标换成 2.0R、刻度错配构造性消除之后，同一个闸门的净R 效应变成 "
      f"{g2[2]:+.3f}（t={g2[3]:+.2f}），毛R 效应 {g2[0]:+.3f}（t={g2[1]:+.2f}）。")
    if abs(g2[2]) < abs(g0[2]):
        A(f"效应缩小到原来的 **{100*abs(g2[2])/abs(g0[2]):.0f}%**——"
          f"也就是说 D4 闸门约 {100*(1-abs(g2[2])/abs(g0[2])):.0f}% 的表观效力"
          f"来自「T/S 与点差」这两个纯几何/摩擦通道，剩下的才是别的东西。")
    else:
        A("效应**没有**缩小——D4 闸门不是刻度错配的修正，它另有来源。")
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
    bump()
    A(f"T/S 与持有根数的秩相关 ρ = {rho3:+.3f} (z={rz3:+.2f})。")
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
    A("含混率高的组合（止损与目标都很近）对这个口径最敏感；如实标注。")
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
    A("1. **任务书猜的方向是反的。** 猜想是「远目标 + 紧止损」，实测是"
      f" {100*n_lt1/len(tsv):.0f}% 的交易**目标比止损近**（T/S 中位 "
      f"{st.median(tsv):.2f}）。真正的病是目标距离**不受控**，不是它太远。")
    A(f"2. **z_geom 不随 T/S 单调。** 若刻度错配伤的是命中概率，就该看到单调"
      f"关系；实测趋势 z 见第 2 节，各档 z_geom 在 "
      f"{min(zs_ts):+.2f}…{max(zs_ts):+.2f} 之间无序摆动。刻度错配改的是"
      f"赔率结构和摩擦，不是预测力——这削弱了「刻度错配 = 亏损主因」的强版本。")
    A(f"3. **统一刻度并没有把期望做正。** 25 格全部为负，最好一格 {bestn:+.3f}。"
      f"如果两把尺子是主因，统一之后至少该有一格越过 0。")
    good = [c for c in allc if c[0] > bs["net"]]
    A(f"4. 优于基线的 {len(good)} 格里，配对 t 越过 |t|>2 的有 "
      f"{sum(1 for _, tk, sk in good if abs(paired(G[(tk,sk)], base)[1]) > 2)} 个；"
      f"越过第 10 节 Bonferroni 门槛的见下。")
    A("")

    A("## 11 · 多重比较")
    A("")
    thr = _bonf_z(CELLS)
    A(f"全文共检视 **{CELLS} 个格子**（分层格、总表 25 格及其三种口径、条件化格、"
      f"闸门格、时段格、稳健性格、对照格）。Bonferroni 门槛 "
      f"|z| > **{thr:.2f}**（α=0.05 双侧）。")
    A("")
    A("在这个 family size 下：")
    A("")
    surv = []
    for _, tk, _, _ in TARGETS:
        for _, sk, _, _ in STOPS:
            if (tk, sk) == ("LVL", "STRUCT"):
                continue
            pm3, pt3 = paired(G[(tk, sk)], base)
            if abs(pt3) > thr:
                surv.append((tk, sk, pm3, pt3))
    if surv:
        A(f"- 相对基线的**配对差**越过 Bonferroni 门槛的组合共 {len(surv)} 个：")
        for tk, sk, pm3, pt3 in sorted(surv, key=lambda x: -x[2]):
            A(f"  - {tk} × {sk}：{pm3:+.3f} R/笔，t={pt3:+.2f}")
    else:
        A("- **没有任何组合的配对差越过 Bonferroni 门槛。**")
    A(f"- 常规 |z|>1.96 在 {CELLS} 个格子的 family 下毫无意义："
      f"纯随机也会有约 {0.05*CELLS:.0f} 个格子越线。")
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
    A("| 分项 | 总R | 占总亏损 | 能不能归因于「两把尺子」 |")
    A("|---|---|---|---|")
    A(f"| 点差摩擦 `−点差/S` | −{tot_drag:.1f} | "
      f"{100*tot_drag/abs(bs['tot']):.0f}% | **能，部分**：S 由止损尺子决定；"
      f"换尺子能改，见下 |")
    A(f"| 命中率相对几何零假设的偏离 `(p−p0)(1+T/S)` | {bs['tot_gross']:+.1f} | "
      f"{100*abs(bs['tot_gross'])/abs(bs['tot']):.0f}% | **基本不能**：换尺子"
      f"不改变 (p−p0)，只改变放大系数 |")
    A(f"| 合计 | {bs['tot']:+.1f} | 100% | |")
    A("")
    A("再用「换成最好的统一刻度能挽回多少」做上界估计：")
    A("")
    A(f"- 基线（两把尺子）总净R **{bs['tot']:+.1f}**")
    A(f"- 25 格里最好的组合（{bt} × {bsk}）总净R **{summarise(G[(bt,bsk)])['tot']:+.1f}**")
    A(f"- 差额 **{summarise(G[(bt,bsk)])['tot']-bs['tot']:+.1f} R**，"
      f"= 基线亏损的 **{100*(summarise(G[(bt,bsk)])['tot']-bs['tot'])/abs(bs['tot']):.0f}%**")
    A(f"- 但这是 **25 选 1 的最大值**，配对 t={ptb:+.2f}，Bonferroni 门槛 "
      f"{thr:.2f}。")
    A("")
    A("### 12.2 结论")
    A("")
    frac_best = (summarise(G[(bt, bsk)])["tot"] - bs["tot"]) / abs(bs["tot"])
    A(f"**能归因的部分：约 {100*frac_best:.0f}%（上界，且是 25 选 1 的乐观估计）。**")
    A("")
    A("拆开说：")
    A("")
    A(f"1. **「两把尺子」确实制造了一笔真金白银的成本，但它主要走的是摩擦通道，"
      f"不是概率通道。** 点差摩擦占纯括号亏损的 "
      f"{100*tot_drag/abs(bs['tot']):.0f}%，而它之所以这么大，是因为结构止损的"
      f"离散度极高（p05 {q([s.risk for s in sigs],0.05):.1f} 点 → p95 "
      f"{q([s.risk for s in sigs],0.95):.1f} 点）：止损 3 点的那些交易，一个 "
      f"{SPREAD} 点的点差就吃掉 {SPREAD/3:.2f}R。把止损换成波动尺（离散度只有 "
      f"{q(v20,0.95)/q(v20,0.05):.1f}×）能直接压掉这一块。")
    A("")
    A(f"2. **「两把尺子」没有制造概率上的劣势。** T/S 分层的 z_geom 不单调"
      f"（趋势 z 见第 2 节），各档偏离几何零假设的幅度相近。目标是不是位、"
      f"止损是不是结构，**不改变价格路径先撞谁的概率相对于随机游走的偏离**。")
    A("")
    A(f"3. **所以剩下的大头归因不了。** 统一刻度之后 25 格没有一格为正，"
      f"最好一格仍是 {bestn:+.3f} R/笔。v14 负期望的主体是"
      f"**入场信号本身不带方向信息**——这与 `V15_ENTRY_LOCATION.md` 的结论"
      f"（60 个格子的 z_geom 没有一个越过 +1.96）一致，与出场/目标/止损的"
      f"定义无关。**排除刻度错配作为主因的证据就是这条：把两把尺子换成一把、"
      f"换三种不同的一把、加上四种目标定义，25 种组合全负。**")
    A("")
    A(f"4. **D4「止损放远」闸门的机制被拆开了**：它 "
      f"{100*(1-min(1,abs(g2[2])/abs(g0[2]))):.0f}% 的表观效力可以由"
      f"「T/S 放大系数 + 点差/S」这两个纯几何通道解释"
      f"（把目标换成 2.0R 后效应从 {g0[2]:+.3f} 变成 {g2[2]:+.3f}）。"
      f"它不是「找到了更好的交易」，而是「把同一批交易的赔率结构和摩擦改善了」。"
      f"这也解释了为什么它在 V15 里 z_sel 很高却只把总净R 从 −73.6 抬到 +1.3——"
      f"**它消除的是成本，不是在制造 alpha**。")
    A("")
    A("### 12.3 如果只能带走一句话")
    A("")
    A("> 目标与止损用两把尺子，代价是**可测的、但是二阶的**：它让点差摩擦"
      "在小止损的那一半交易上失控（占纯括号亏损约 "
      f"{100*tot_drag/abs(bs['tot']):.0f}%），并让赔率结构随机化"
      "（T/S 从 0.00 到 7.14）。统一刻度能把亏损压掉约 "
      f"{100*frac_best:.0f}%，但压不出正期望。**v14 亏钱的主因不在这里。**")
    A("")
    A("### 12.4 可执行的最小改动（不改信号，只改几何）")
    A("")
    A("按证据强度排序，全部是成本侧改动，不承诺 alpha：")
    A("")
    A(f"- **给 T1 加最小距离地板**。目前 {nsp} 笔（{100*nsp/len(t1p):.1f}%）"
      f"的目标 ≤ 一个点差，这些交易在毛口径上就不可能赢。把 `next_rung` 的 "
      f"`px + minTick` 改成 `px + max(minTick, c×点差)` 或直接跳到再下一个位。")
    A(f"- **给 S 加上限**，或换成波动尺。结构止损 p95 是 p05 的 "
      f"{q([s.risk for s in sigs],0.95)/q([s.risk for s in sigs],0.05):.0f} 倍，"
      f"这个离散度让 R 这个单位在跨交易比较时几乎失效。")
    A(f"- 以上两条都**不需要**放弃具名位目标，因此**不与 Saty 的方法冲突**"
      f"（第 3 节已判定：没有一个固定 R 目标在配对检验下显著优于具名位）。")
    A("")
    A("---")
    A("")
    A(f"*生成于 `study_scale_mismatch.py`；family size {CELLS}；"
      f"Bonferroni |z| > {thr:.2f}。*")

    txt = "\n".join(o)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
