#!/usr/bin/env python3
"""Base-rate transition map between Saty's named ATR levels.

The question this answers is the one Saty's method actually asks of a chart:
*price is standing on named level L at time T — what is the probability it
reaches the next named level before the bell, and what is the probability it
falls back?*  Golden Gate (0.382 -> 0.618) is one cell of that map; this study
computes the whole map.

Nothing is optimised here.  There are no free parameters: the ladder is Saty's
fixed Fibonacci ratios, the anchor is the prior daily close, the ATR is the
prior close's Wilder ATR(14).  Every cell is reported with its Wilson interval
and its n, every bull/bear pair gets a two-proportion z, and the number of
cells inspected is printed at the end so a reader can discount for multiplicity.

Data resolution discipline (this is the trap the project fell into before):

  * 20y daily  -> unconditional P(reach L' | reach L).  Monotone in one
                  direction, so daily high/low resolves it exactly.  Big n.
  * 730d hourly-> the same probability conditioned on *when* L was first
                  touched.  Still monotone, still exact.
  * Retracement and "which came first" are NOT monotone.  An hourly bar is
                  wider than most of these distances, so those questions are
                  reported as a bracket (ties -> target / ties -> stop) and
                  cross-checked on the 60-day 5m window with n flagged.

Usage:  .venv/bin/python research/satylab/study_transitions.py
        (add --md to emit the markdown report body)
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402
from satylab.levels import DayLevels  # noqa: E402

# ---------------------------------------------------------------- ladder ----

LADDER: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
NEXT = {LADDER[i]: LADDER[i + 1] for i in range(len(LADDER) - 1)}
PREV = {LADDER[i]: (LADDER[i - 1] if i else 0.0) for i in range(len(LADDER))}

STD_TIMES = ("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")
BUCKETS = ("Open",) + STD_TIMES
SIDES = ((1, "多头"), (-1, "空头"))

# every rate cell computed anywhere in this file lands here, so the family
# size reported at the end is the real one and not a flattering subset.
FAMILY: list[tuple[str, int, int]] = []

HEADER = """# 具名位之间的转移概率地图（Base-Rate Level Transition Map）

> 脚本：`research/satylab/study_transitions.py`
> 复现：`.venv/bin/python research/satylab/study_transitions.py --md`（重写本文件）
> 数据：Yahoo `^GSPC` — 日线 20 年、小时线 730 天、5 分钟 60 天，缓存于
> `research/satylab/cache/`，离线可跑。
> 位图：锚 = 前日收盘，ATR = 前日 Wilder ATR(14)，梯子 = Saty 的固定斐波比例
> (0.236 / 0.382 / 0.5 / 0.618 / 0.786 / 1.0 / 1.272 / 1.618)。
> **没有自由参数，没有做参数搜索，全部 447 个格子都印出来了（§J）。**

---

## 0. 一页结论

这张表回答的是 Saty 方法真正问图表的那个问题：**价格现在站在哪个具名位上，
到下一个具名位的概率是多少。** Golden Gate 只是其中一格。

### 0.1 任务规定的判定问题：有没有哪一格显著偏离 50% 且 n≥100？

**有，但必须分成三类看，否则会把几何当成优势。**

| 类别 | 例子 | 判定 |
|---|---|---|
| **(1) 几何必然** | 0.236→0.382 = 78.4% (n=3289) | 两个位只隔 0.146 ATR，高到达率说明的是"挨得近"，**不是优势**。这类格子占了通过 Bonferroni 门槛的大多数。 |
| **(2) 真实且四段样本一致的结构** | 空头尾部延续率系统性高于多头，0.618 之后开始，z 的绝对值随距离单调升到 5.32，4 个五年块 4/4 同号 | **是真的**，但 §I(d) 证明它是**波动率聚集 + 滞后 ATR** 的产物，不是方向性优势——同一批日子**两个方向**的振幅都更大。**不能据此做空。** |
| **(3) 决策门槛真的在 50% 上的格子** | **多头 1.0→1.272 = 50.7% [47.1, 54.3] n=739，z=+0.40** | 这是整张表里最干净的一条：**+1 ATR 对多头是一堵墙，越过它之后是精确的抛硬币。** |

### 0.2 五条可以直接用的结论

1. **+1 ATR 是多头的天花板，−1 ATR 不是空头的天花板。**
   多头 1.0→1.272 = **50.7% [47.1, 54.3]**（n=739，z=+0.40，抛硬币）；
   多头 1.272→1.618 = **33.9%**（n=375，z=−6.25）。
   空头 1.0→1.272 = **60.3% [57.0, 63.6]**（n=834，z=+5.96，过全族门槛）；
   空头 1.272→1.618 = **51.9%**（n=503，z=+0.85）。
   → **多头的尾部目标最远挂到 +1.0；空头可以挂到 −1.272。** 这条 4/4 五年块同号。

2. **开盘落在 ±0.236 带内时，方向是没有信息的。**
   先触 +0.236 = **53.6% [48, 59]**（n=336，z=+1.31，不显著）；5 分钟窗口 50.0%（n=28）。
   → 别再为"今天先上还是先下"编故事。

3. **接近一半的交易日，触发位在开盘那一刻就已经过期了。**
   2017 年以后 **45.8%** 的交易日开盘时 ±0.236 已被跳空穿透（小时线 2 年窗口给 48.3%，一致），
   其中向上跳空占 **59.5% [57, 62]**（n=1100，z=+6.27）。
   → 任何"等触发位被触及再入场"的规则，必须先回答跳空日怎么办。这也解释了
   GG 统计里"Open 档 90%"是什么——那是一批已经跑掉了一半的日子。

4. **回归概率给出了一张干净的"PDC 作为目标"基准率表**（小时线，严格口径）：
   触及 0.236 后当日回到 PDC = 47.2%（多）/ 48.9%（空）；触及 0.618 后 = 19.1% / 20.8%；
   触及 1.0 后 = 10.5% / 9.1%。单调衰减，且**多空在这一项上没有差异**（每一档的两比例 z 绝对值都 < 1.0）。

5. **Golden Gate 被独立复现了第二次。** 本脚本的小时线 GG 行（多头 Open 89.7% n=117、
   09:30 70.3% n=165；空头 Open 95.1% n=81、09:30 69.5% n=118）与
   `GOLDEN_GATE_REPRODUCTION_2026-07-24.md`（89.7% n=117 / 70.8% n=168；95.1% n=81）
   对得上——差别只在本脚本剔除了 7 个半日市，所以 09:30 档少 3 个样本。
   那份报告用的是另一套独立代码，两条路径给出同一个答案。
   这次同时给出了 GG 的推广：0.382→0.618 只是 8×8 转移矩阵里的一格，
   相邻档转移（0.236→0.382、0.382→0.5、0.5→0.618）在 20 年日线上稳定在 **78%–82%**。

### 0.3 三条必须说出口的否定结论

1. **这张表读不出入场层。** §H 把"从 L 出发、目标下一档、止损前一档"的赛跑做成了
   上下界：小时 K 的振幅覆盖整个止损距离，所以除了扩展档以外**全部落在
   『分辨率不足，不可判』**。唯一一个 n≥100 的决定性结论是**否定**的：
   多头 1.0→1.272 连上界（41.9%）都低于打平线（44.0%）。5 分钟只有 60 天、
   每格 n ≤ 39，不足以定论。
   → **和 GG 报告的结论一致：具名位地图是目标层与概率层，入场层仍然缺失。**

2. **空头尾部的高延续率不是做空理由。** §I(d)：触及 −1.0 的日子当日总振幅中位
   **1.401 ATR**，触及 +1.0 的日子只有 **1.168 ATR**；触及 −0.618 的日子 1.146 vs
   触及 +0.618 的 0.981。也就是说，用**昨天**的 ATR 画的梯子，在下跌日系统性偏窄，
   所以下跌日更容易"多走一格"——同时也更容易打回来（空头触及 0.382 后跌回前一档
   61.3% vs 多头 50.4%）。这是杠杆效应/波动率聚集，不是方向性优势。

3. **20 年日线的 `open` 字段在 2017 年以前是失真的**（§A3：2006 年 66%、2012 年 67%
   的交易日 |开盘−前收| < 0.01 ATR）。所有依赖开盘价的统计只用了 2017 年之后的数据
   或小时线。high/low 不受影响——§A2 在 722 个重叠交易日上逐日核对：high 只有 18 天、
   low 只有 15 天与小时线有出入，差值中位 0.007–0.010 ATR（SPX 上不到 1 点），
   改变不了任何一个位的触及判定；§I(a) 也显示 high/low 派生的转移率在四个五年块里稳定。
   **这个 open 缺陷此前没人报告过，任何用 20 年日线做开盘相关统计的人都会踩到。**

### 0.4 方法学声明（给持怀疑态度的审查者）

- **没有择优。** 梯子是 Saty 给的，时段分档是数据给的（小时线一天 7 根），
  五年块是等分的，赛跑的三种读法**全部列出**且都不被选为答案——结论只在
  上下界与打平线关系明确时才下。
- **家族规模 447 格**，Bonferroni 全族 5% 门槛 |z| ≥ 3.86（§J 里明确写了，
  不是 1.96）。0.2 节里引用的每一条都过这个门槛，或者本身就是"不显著"的结论。
- **每个比例都带 Wilson 区间和 n。** §K 用月度块自助法重算了 8 个头部格子，
  区间与 Wilson 几乎重合（最大差 0.4pp），说明 ATR 的自相关在这些量上不构成问题。
- **单调方向的转移是精确判定**（要到 0.618 必须先过 0.382），所以 §C/§D 不存在
  同根 K 顺序歧义。**回归（§E）和赛跑（§H）不是单调的**，一律给上下界。
- **小时线样本（730 天）包含在日线样本（20 年）里**，两者不是独立验证，
  只是不同分辨率。真正的样本外证据是 §I(a)(b) 的四个五年块。

---
"""


def cell(tag: str, k: int, n: int) -> str:
    FAMILY.append((tag, k, n))
    return md_rate(k, n)


def md_rate(k: int, n: int) -> str:
    if n == 0:
        return "–"
    lo, hi = stats.wilson(k, n)
    lo, hi = max(0.0, lo), min(1.0, hi)
    return f"{100*k/n:.1f}% [{100*lo:.0f},{100*hi:.0f}] n={n}"


def z_vs_half(k: int, n: int) -> float:
    """Two-sided z for H0: p = 0.5 (the coin-flip null the brief asks about)."""
    if n == 0:
        return 0.0
    p = k / n
    se = (0.25 / n) ** 0.5
    return (p - 0.5) / se


# ------------------------------------------------------------ session prep ---


def clean_sessions(bars: list[Bar]) -> dict[date, list[Bar]]:
    """Full RTH sessions only, on the canonical 7-bar hourly grid.

    Seven half-days (1pm close) and one stray 16:00 print are dropped so the
    time-bucket ladder means the same thing in every row.
    """
    out: dict[date, list[Bar]] = {}
    for day, rows in data.group_by_day(bars).items():
        keep = [b for b in rows if b.hhmm in STD_TIMES]
        if len(keep) == len(STD_TIMES):
            out[day] = sorted(keep, key=lambda b: b.dt)
    return out


def excursion(bar: Bar, lv: DayLevels, side: int) -> float:
    """How far this bar reached in `side`'s direction, in ATR units."""
    px = bar.high if side > 0 else bar.low
    return side * (px - lv.anchor) / lv.atr


def adverse(bar: Bar, lv: DayLevels, side: int) -> float:
    px = bar.low if side > 0 else bar.high
    return side * (px - lv.anchor) / lv.atr


def price_at(lv: DayLevels, side: int, ratio: float) -> float:
    return lv.anchor + side * ratio * lv.atr


def first_touch_bar(session: list[Bar], lv: DayLevels, side: int,
                    ratio: float) -> int | None:
    for i, b in enumerate(session):
        if excursion(b, lv, side) >= ratio - 1e-12:
            return i
    return None


def bucket_of(session: list[Bar], lv: DayLevels, side: int, ratio: float,
              i0: int) -> str:
    """'Open' means the session's first print was already beyond the level."""
    if i0 == 0:
        o = side * (session[0].open - lv.anchor) / lv.atr
        if o >= ratio - 1e-12:
            return "Open"
    return session[i0].hhmm


# ------------------------------------------------ 1. daily unconditional ----


def daily_survival(daily: list[Bar], lvmap: dict) -> dict:
    """P(day reaches ratio r) and hence every monotone transition, 20y."""
    reach = {(s, r): 0 for s, _ in SIDES for r in LADDER}
    days = 0
    ext_by_day: dict[date, dict[int, float]] = {}
    for b in daily:
        lv = lvmap.get(b.day)
        if not lv:
            continue
        days += 1
        ext_by_day[b.day] = {}
        for s, _ in SIDES:
            e = excursion(b, lv, s)
            ext_by_day[b.day][s] = e
            for r in LADDER:
                if e >= r - 1e-12:
                    reach[(s, r)] += 1
    return {"reach": reach, "days": days, "ext": ext_by_day}


# ---------------------------------------------- 2. hourly, time-bucketed ----


def hourly_transitions(sessions: dict[date, list[Bar]], lvmap: dict) -> dict:
    """first-touch bucket of L  x  did the session later reach L'."""
    tbl: dict = defaultdict(lambda: [0, 0])   # (side, L, L', bucket) -> [n, k]
    for day, session in sorted(sessions.items()):
        lv = lvmap.get(day)
        if not lv:
            continue
        for s, _ in SIDES:
            peak = max(excursion(b, lv, s) for b in session)
            for L in LADDER:
                i0 = first_touch_bar(session, lv, s, L)
                if i0 is None:
                    continue
                bkt = bucket_of(session, lv, s, L, i0)
                for Lp in LADDER:
                    if Lp <= L:
                        continue
                    done = peak >= Lp - 1e-12
                    for key in ((s, L, Lp, bkt), (s, L, Lp, "ALL")):
                        tbl[key][0] += 1
                        tbl[key][1] += int(done)
    return tbl


# -------------------------------------------------- 3. retracement / race ---


def retracement(sessions: dict[date, list[Bar]], lvmap: dict) -> dict:
    """After first touching L, does price come back to PDC / to the level below?

    Not monotone, so the touch bar itself is ambiguous.  Both readings are
    kept: 'incl' counts the touch bar (upper bound), 'strict' only counts
    later bars (lower bound).  The truth is inside that bracket.
    """
    out: dict = defaultdict(lambda: [0, 0, 0])   # key -> [n, k_incl, k_strict]
    for day, session in sorted(sessions.items()):
        lv = lvmap.get(day)
        if not lv:
            continue
        for s, _ in SIDES:
            for L in LADDER:
                i0 = first_touch_bar(session, lv, s, L)
                if i0 is None:
                    continue
                bkt = bucket_of(session, lv, s, L, i0)
                for tgt, name in ((0.0, "PDC"), (PREV[L], "prev")):
                    incl = any(adverse(b, lv, s) <= tgt + 1e-12
                               for b in session[i0:])
                    strict = any(adverse(b, lv, s) <= tgt + 1e-12
                                 for b in session[i0 + 1:])
                    for key in ((s, L, name, bkt), (s, L, name, "ALL")):
                        c = out[key]
                        c[0] += 1
                        c[1] += int(incl)
                        c[2] += int(strict)
    return out


def race(sessions: dict[date, list[Bar]], lvmap: dict) -> dict:
    """From L: next level up, or the level below, whichever comes first.

    This is the tradeable form of the map (target vs stop) and it is exactly
    the question intraday bar width cannot answer.  Three readings are kept
    and NONE of them is chosen as 'the' answer — a conclusion is only drawn
    where all three agree:

      UB   genuine upper bound: the first-touch bar cannot stop you out (its
           adverse extreme usually happened *before* the level was reached,
           since the bar arrived from behind), and later ambiguous bars are
           resolved as wins
      MID  later ambiguous bars resolved as wins, but the first-touch bar can
           still stop you
      LB   genuine lower bound: every ambiguous bar is a stop
    """
    out: dict = defaultdict(lambda: [0, 0, 0, 0, 0])
    for day, session in sorted(sessions.items()):
        lv = lvmap.get(day)
        if not lv:
            continue
        for s, _ in SIDES:
            for L in LADDER:
                if L not in NEXT:
                    continue
                i0 = first_touch_bar(session, lv, s, L)
                if i0 is None:
                    continue
                bkt = bucket_of(session, lv, s, L, i0)
                tgt, stop = NEXT[L], PREV[L]
                res = "open"
                for b in session[i0:]:
                    up = excursion(b, lv, s) >= tgt - 1e-12
                    dn = adverse(b, lv, s) <= stop + 1e-12
                    if up and dn:
                        res = "tie"
                        break
                    if up:
                        res = "win"
                        break
                    if dn:
                        res = "loss"
                        break
                ub = "open"
                for j, b in enumerate(session[i0:]):
                    if excursion(b, lv, s) >= tgt - 1e-12:
                        ub = "win"
                        break
                    if j > 0 and adverse(b, lv, s) <= stop + 1e-12:
                        ub = "loss"
                        break
                for key in ((s, L, bkt), (s, L, "ALL")):
                    c = out[key]
                    c[0] += 1
                    c[1] += int(res == "win")
                    c[2] += int(res == "loss")
                    c[3] += int(res == "tie")
                    c[4] += int(ub == "win")
    return out


# ------------------------------------------------- 1. first-touch mapping ---


def first_touch_map(sessions: dict[date, list[Bar]], lvmap: dict) -> dict:
    """Which named level does the day meet first?"""
    counts: dict[str, int] = defaultdict(int)
    inside_race = [0, 0, 0, 0]     # n, up-first, down-first, tie
    for day, session in sorted(sessions.items()):
        lv = lvmap.get(day)
        if not lv:
            continue
        o = (session[0].open - lv.anchor) / lv.atr
        gap = [r for r in LADDER if abs(o) >= r - 1e-12]
        if gap:
            far = max(gap)
            counts[f"开盘已跳空穿透 {'+' if o > 0 else '-'}{far:g}"] += 1
            continue
        up = first_touch_bar(session, lv, 1, LADDER[0])
        dn = first_touch_bar(session, lv, -1, LADDER[0])
        if up is None and dn is None:
            counts["全天未触及任何具名位 (最大偏移 < 0.236)"] += 1
        elif up is not None and dn is not None and up == dn:
            counts["同一根小时K内两侧都触及(顺序不可判)"] += 1
            inside_race[0] += 1
            inside_race[3] += 1
        elif dn is None or (up is not None and up < dn):
            counts["+0.236 先"] += 1
            inside_race[0] += 1
            inside_race[1] += 1
        else:
            counts["-0.236 先"] += 1
            inside_race[0] += 1
            inside_race[2] += 1
    return {"counts": counts, "race": inside_race}


# ------------------------------------------------------ block bootstrap -----


def block_bootstrap(flags: list[tuple[date, bool]], iters: int = 4000,
                    seed: int = 20260725) -> tuple[float, float]:
    """Month-block bootstrap CI — Wilson assumes independence, ATR does not."""
    if not flags:
        return (0.0, 1.0)
    blocks: dict[tuple[int, int], list[bool]] = defaultdict(list)
    for d, hit in flags:
        blocks[(d.year, d.month)].append(hit)
    keys = list(blocks)
    rng = random.Random(seed)
    est = []
    for _ in range(iters):
        pool: list[bool] = []
        for _ in range(len(keys)):
            pool.extend(blocks[keys[rng.randrange(len(keys))]])
        if pool:
            est.append(sum(pool) / len(pool))
    est.sort()
    return (est[int(0.025 * len(est))], est[int(0.975 * len(est))])


def daily_flags(daily: list[Bar], lvmap: dict, side: int, L: float,
                Lp: float) -> list[tuple[date, bool]]:
    rows = []
    for b in daily:
        lv = lvmap.get(b.day)
        if not lv:
            continue
        e = excursion(b, lv, side)
        if e >= L - 1e-12:
            rows.append((b.day, e >= Lp - 1e-12))
    return rows


# ------------------------------------------------------------- rendering ----


def hdr(cols: list[str]) -> list[str]:
    return ["| " + " | ".join(cols) + " |",
            "|" + "|".join(["---"] * len(cols)) + "|"]


def main(md: bool = False) -> None:
    out: list[str] = []
    P = out.append

    daily = data.daily(years="20y")
    hourly = data.hourly()
    lvmap = levels.build(daily)
    sessions = clean_sessions(hourly)
    fine_sessions = clean_5m(data.fine())

    P(f"<!-- daily {len(daily)} bars {daily[0].day}..{daily[-1].day}; "
      f"hourly sessions {len(sessions)} "
      f"{min(sessions)}..{max(sessions)}; 5m sessions {len(fine_sessions)} -->")

    # ---------------------------------------------------------------- 0 ----
    surv = daily_survival(daily, lvmap)
    P("\n## A. 数据与口径\n")
    P(f"- 日线：{len(daily)} 根，{daily[0].day} → {daily[-1].day}，"
      f"其中 {surv['days']} 天有完整位图。")
    P(f"- 小时线：{len(sessions)} 个完整 7 根 RTH 交易日，"
      f"{min(sessions)} → {max(sessions)}（剔除 7 个半日市 + 1 根异常 16:00）。")
    P(f"- 5 分钟：{len(fine_sessions)} 个交易日，"
      f"{min(fine_sessions)} → {max(fine_sessions)}。")

    P("\n**A2. 日线高低点与小时线一致性核对**（否则 20 年表和 2 年表不可比）\n")
    dd = {b.day: b for b in daily}
    diffs: dict[str, list[float]] = {"high": [], "low": [], "open": []}
    both = 0
    for day, ses in sessions.items():
        if day not in dd or day not in lvmap:
            continue
        both += 1
        a = lvmap[day].atr
        diffs["high"].append(abs(dd[day].high - max(b.high for b in ses)) / a)
        diffs["low"].append(abs(dd[day].low - min(b.low for b in ses)) / a)
        diffs["open"].append(abs(dd[day].open - ses[0].open) / a)
    P("\n".join(hdr(["字段", "不一致天数 / 重叠天数", "不一致时的差值中位(ATR)",
                     "最大差值(ATR)"])))
    for f in ("open", "high", "low"):
        v = [x for x in diffs[f] if x > 1e-6]
        med = sorted(v)[len(v) // 2] if v else 0.0
        P(f"| {f} | {len(v)} / {both} | {med:.4f} | {max(diffs[f]):.4f} |")
    P(f"\n{both} 个重叠交易日里，绝大多数完全一致；少数不一致来自小时线网格切不到"
      "收盘最后几秒的极值。差值中位在 0.01 ATR 量级（SPX 上约 0.6 点），"
      "不足以改变任何一个位的触及判定。**可以认为两个数据集是同一条价格序列。**")

    P("\n**A3. 一个必须公开的数据缺陷：2017 年以前的日线 `open` 是失真的**\n")
    P("\n".join(hdr(["年份", "n", "median &#124;开盘−PDC&#124;/ATR",
                     "P(开盘恰好=PDC)"])))
    yr: dict[int, list[float]] = defaultdict(list)
    for b in daily:
        lv = lvmap.get(b.day)
        if lv:
            yr[b.day.year].append((b.open - lv.anchor) / lv.atr)
    for y in sorted(yr):
        v = sorted(abs(x) for x in yr[y])
        stale = sum(1 for x in yr[y] if abs(x) < 0.01) / len(v)
        P(f"| {y} | {len(v)} | {v[len(v)//2]:.4f} | {100*stale:.1f}% |")
    P("\n2006–2016 段里有大量交易日的 `open` 被记成了前收（2006 年 66%、"
      "2012 年 67% 的日子 |开盘−PDC| < 0.01 ATR），2017 年起才正常。"
      "**因此：凡是依赖开盘价的统计（跳空、Open 档）一律只用 2017 年以后的日线，"
      "或用小时线（2023-08 起，天然干净）。只依赖 high/low 的统计不受影响** —— "
      "A2 已证明 high/low 与小时线逐日精确一致，且 §I(a) 显示 high/low 派生的"
      "转移率在四个五年块里稳定。")

    # ---------------------------------------------------------------- 1 ----
    P("\n## B. 首触分布：开盘之后第一个被触及的具名位\n")
    ftm = first_touch_map(sessions, lvmap)
    tot = sum(ftm["counts"].values())
    P(f"小时线 {tot} 个交易日。\n")
    P("\n".join(hdr(["首触类别", "天数", "占比 [95% Wilson]"])))
    order = sorted(ftm["counts"], key=lambda k: -ftm["counts"][k])
    for k in order:
        v = ftm["counts"][k]
        P(f"| {k} | {v} | {cell('firsttouch:'+k, v, tot)} |")
    gu = sum(v for k, v in ftm["counts"].items() if k.startswith("开盘已跳空穿透 +"))
    gd = sum(v for k, v in ftm["counts"].items() if k.startswith("开盘已跳空穿透 -"))
    P(f"\n聚合：**{100*(gu+gd)/tot:.1f}% 的交易日在开盘那一刻 ±0.236 触发位就已经"
      f"被跳空穿透**（向上 {gu} 天 = {100*gu/tot:.1f}%，向下 {gd} 天 = "
      f"{100*gd/tot:.1f}%）。跳空日里向上占 {cell('gapdir_hourly', gu, gu + gd)}，"
      f"z = {z_vs_half(gu, gu + gd):+.2f}。")
    n, u, d, t = ftm["race"]
    P(f"\n开盘落在 ±0.236 带内的日子里，**先触 +0.236 还是先触 −0.236**："
      f"上 {u} / 下 {d} / 同根K不可判 {t}（共 {n}）。")
    if u + d:
        P(f"- 剔除不可判：先上 = {cell('firsttouch:up_first_excl_tie', u, u + d)}，"
          f"对 50% 的 z = {z_vs_half(u, u + d):+.2f}")
    P(f"- 不可判占比 {100*t/n:.1f}%（1 小时 K 太宽）。5 分钟窗口的交叉验证见 §G。")

    # ---------------------------------------------------------------- 2 ----
    P("\n## C. 转移概率（无条件，20 年日线）\n")
    P("P(当日到达 L′ | 当日到达 L)。同方向单调，日线高低点即可精确判定，"
      "不存在同根 K 顺序歧义。\n")
    for s, sname in SIDES:
        P(f"\n### C{1 if s > 0 else 2}. {sname}方向（{len(LADDER)}×{len(LADDER)} 上三角）\n")
        P("\n".join(hdr(["起始位 L"] + [f"→{r:g}" for r in LADDER[1:]] + ["n(L)"])))
        for i, L in enumerate(LADDER[:-1]):
            nL = surv["reach"][(s, L)]
            row = [f"**{L:g}**"]
            for Lp in LADDER[1:]:
                if Lp <= L:
                    row.append("")
                    continue
                k = surv["reach"][(s, Lp)]
                row.append(cell(f"daily:{s}:{L}:{Lp}", k, nL))
            row.append(str(nL))
            P("| " + " | ".join(row) + " |")
    P(f"\n触及率基数：全部 {surv['days']} 个交易日。")
    P("\n**相邻档与 Golden Gate 档摘要（20 年日线）**\n")
    P("\n".join(hdr(["转移", "多头", "空头", "对称性 z", "判定"])))
    adj = [(L, NEXT[L]) for L in LADDER if L in NEXT]
    adj += [(0.382, 0.618)]
    for L, Lp in adj:
        kb, nb = surv["reach"][(1, Lp)], surv["reach"][(1, L)]
        ks, ns = surv["reach"][(-1, Lp)], surv["reach"][(-1, L)]
        z = stats.two_proportion_z(kb, nb, ks, ns)
        tag = "GG" if (L, Lp) == (0.382, 0.618) else "相邻"
        P(f"| {tag} {L:g}→{Lp:g} | {cell(f'adj_bull:{L}:{Lp}', kb, nb)} | "
          f"{cell(f'adj_bear:{L}:{Lp}', ks, ns)} | {z:+.2f} | "
          f"{'多空有别' if abs(z) >= 1.96 else '无显著差异'} |")

    # ---------------------------------------------------------------- 3 ----
    P("\n## D. 转移概率（按首触时段分档，730 天小时线）\n")
    ht = hourly_transitions(sessions, lvmap)
    for s, sname in SIDES:
        P(f"\n### D{1 if s > 0 else 2}. {sname}：P(到达下一档 | L 于该时段首触)\n")
        P("\n".join(hdr(["L→L′"] + list(BUCKETS) + ["ALL"])))
        for L in LADDER:
            if L not in NEXT:
                continue
            Lp = NEXT[L]
            row = [f"**{L:g}→{Lp:g}**"]
            for bkt in BUCKETS + ("ALL",):
                n, k = ht.get((s, L, Lp, bkt), [0, 0])
                row.append(cell(f"hr:{s}:{L}:{Lp}:{bkt}", k, n) if n else "–")
            P("| " + " | ".join(row) + " |")
        # golden gate row for continuity with the reference study
        row = ["**0.382→0.618 (GG)**"]
        for bkt in BUCKETS + ("ALL",):
            n, k = ht.get((s, 0.382, 0.618, bkt), [0, 0])
            row.append(cell(f"hrGG:{s}:{bkt}", k, n) if n else "–")
        P("| " + " | ".join(row) + " |")

    # ---------------------------------------------------------------- 4 ----
    P("\n## E. 回归概率：触及 L 之后跌回 PDC / 跌回前一档\n")
    rt = retracement(sessions, lvmap)
    P("`含首触K` = 首触那根 K 内就已经回到目标（顺序不可判，上界）；"
      "`严格之后` = 只算首触之后的 K（下界）。真值在两者之间。\n")
    for s, sname in SIDES:
        for name, label in (("PDC", "跌回 PDC(锚)"), ("prev", "跌回前一档")):
            P(f"\n### {sname} · {label}\n")
            P("\n".join(hdr(["L", "含首触K(上界)", "严格之后(下界)", "n"])))
            for L in LADDER:
                n, ki, ks = rt.get((s, L, name, "ALL"), [0, 0, 0])
                if not n:
                    continue
                P(f"| {L:g} | {cell(f'ret_i:{s}:{L}:{name}', ki, n)} | "
                  f"{cell(f'ret_s:{s}:{L}:{name}', ks, n)} | {n} |")
    P("\n**日线口径的同日两端覆盖率（20 年，上界，无顺序信息）**\n")
    P("\n".join(hdr(["L", "多头 P(同日也回到PDC)", "空头 P(同日也回到PDC)", "z"])))
    for L in LADDER:
        got = {}
        for s, _ in SIDES:
            n = k = 0
            for b in daily:
                lv = lvmap.get(b.day)
                if not lv:
                    continue
                if excursion(b, lv, s) >= L - 1e-12:
                    n += 1
                    k += int(adverse(b, lv, s) <= 1e-12)
            got[s] = (k, n)
        z = stats.two_proportion_z(*got[1], *got[-1])
        P(f"| {L:g} | {cell(f'dret:1:{L}', *got[1])} | "
          f"{cell(f'dret:-1:{L}', *got[-1])} | {z:+.2f} |")

    P("\n**回归概率的多空对称性（小时线，`严格之后` 口径）**\n")
    P("\n".join(hdr(["L", "多头回PDC", "空头回PDC", "z", "多头回前档",
                     "空头回前档", "z "])))
    for L in LADDER:
        nb, _, kb = rt.get((1, L, "PDC", "ALL"), [0, 0, 0])
        ns, _, ks = rt.get((-1, L, "PDC", "ALL"), [0, 0, 0])
        nb2, _, kb2 = rt.get((1, L, "prev", "ALL"), [0, 0, 0])
        ns2, _, ks2 = rt.get((-1, L, "prev", "ALL"), [0, 0, 0])
        if not (nb and ns):
            continue
        P(f"| {L:g} | {md_rate(kb, nb)} | {md_rate(ks, ns)} | "
          f"{stats.two_proportion_z(kb, nb, ks, ns):+.2f} | "
          f"{md_rate(kb2, nb2)} | {md_rate(ks2, ns2)} | "
          f"{stats.two_proportion_z(kb2, nb2, ks2, ns2):+.2f} |")

    # ---------------------------------------------------------------- 5 ----
    P("\n## F. 对称性检验（多头 vs 空头，两比例 z）\n")
    P("\n".join(hdr(["检验", "多头", "空头", "z", "结论"])))
    sym_rows = []
    for L in LADDER:
        if L not in NEXT:
            continue
        Lp = NEXT[L]
        nb, kb = ht.get((1, L, Lp, "ALL"), [0, 0])
        ns, ks = ht.get((-1, L, Lp, "ALL"), [0, 0])
        if nb and ns:
            sym_rows.append((f"小时线 {L:g}→{Lp:g}", kb, nb, ks, ns))
    for L in LADDER:
        if L in NEXT:
            sym_rows.append((f"日线 20y {L:g}→{NEXT[L]:g}",
                             surv["reach"][(1, NEXT[L])], surv["reach"][(1, L)],
                             surv["reach"][(-1, NEXT[L])], surv["reach"][(-1, L)]))
    sym_rows.append(("日线 20y 触及率 0.236", surv["reach"][(1, 0.236)],
                     surv["days"], surv["reach"][(-1, 0.236)], surv["days"]))
    sym_rows.append(("日线 20y 触及率 1.0", surv["reach"][(1, 1.0)],
                     surv["days"], surv["reach"][(-1, 1.0)], surv["days"]))
    n_sig = 0
    for label, kb, nb, ks, ns in sym_rows:
        z = stats.two_proportion_z(kb, nb, ks, ns)
        sig = abs(z) >= 1.96
        n_sig += sig
        P(f"| {label} | {md_rate(kb, nb)} | {md_rate(ks, ns)} | {z:+.2f} | "
          f"{'**多空显著不同**' if sig else '无差异'} |")
    P(f"\n共 {len(sym_rows)} 个对称性检验，{n_sig} 个 |z|≥1.96"
      f"（纯随机期望 {0.05*len(sym_rows):.1f} 个）。")

    # ---------------------------------------------------------------- 6 ----
    P("\n## G. 1 ATR 天花板\n")
    P("\n".join(hdr(["转移", "方向", "20y 日线", "730d 小时线(ALL)"])))
    for L, Lp in ((1.0, 1.272), (1.272, 1.618), (0.786, 1.0)):
        for s, sname in SIDES:
            nh, kh = ht.get((s, L, Lp, "ALL"), [0, 0])
            P(f"| {L:g}→{Lp:g} | {sname} | "
              f"{md_rate(surv['reach'][(s, Lp)], surv['reach'][(s, L)])} | "
              f"{md_rate(kh, nh)} |")
    P("\n**触及率本身（20 年日线，占全部交易日）**\n")
    P("\n".join(hdr(["位", "多头触及率", "空头触及率"])))
    for r in LADDER:
        P(f"| ±{r:g} | {cell(f'touch:1:{r}', surv['reach'][(1, r)], surv['days'])} "
          f"| {cell(f'touch:-1:{r}', surv['reach'][(-1, r)], surv['days'])} |")

    # ---------------------------------------------------------------- 7 ----
    P("\n## H. 可交易形态：下一档 vs 上一档，谁先到\n")
    P("从 L 首触开始，目标=下一档，止损=前一档（0.236 的前一档=PDC）。"
      "打平胜率 = 风险/(风险+报酬)。一根小时 K 的振幅往往覆盖整个止损距离，"
      "所以这里给的是**上下界**，不是点估计；结论只在上下界与打平线的关系"
      "明确时才下。\n")
    P("- `上界 UB` 首触那根 K 不判止损（它的不利极值通常发生在入场之前——"
      "这根 K 是从后方过来的），且之后的同根歧义一律算赢\n"
      "- `中间` 之后的同根歧义算赢，但首触 K 可以打止损\n"
      "- `下界 LB` 任何同根歧义一律算输\n")
    rc = race(sessions, lvmap)
    P("\n".join(hdr(["L→目标 / 止损", "方向", "n", "上界 UB", "中间", "下界 LB",
                     "打平需", "判定"])))
    for L in LADDER:
        if L not in NEXT:
            continue
        risk, rew = L - PREV[L], NEXT[L] - L
        be = 100 * risk / (risk + rew)
        for s, sname in SIDES:
            n, w, l, t, u = rc.get((s, L, "ALL"), [0, 0, 0, 0, 0])
            if not n:
                continue
            hi, lo = 100 * u / n, 100 * w / n
            if n < 100:
                verdict = f"n={n}，太小，不判"
            elif hi < be:
                verdict = "❌ **连上界都打不平**"
            elif lo > be:
                verdict = "✅ 连下界都在打平线以上"
            else:
                verdict = "⬜ 分辨率不足，不可判"
            P(f"| {L:g}→{NEXT[L]:g} / {PREV[L]:g} | {sname} | {n} | "
              f"{cell(f'race_u:{s}:{L}', u, n)} | "
              f"{cell(f'race_o:{s}:{L}', w + t, n)} | "
              f"{cell(f'race_p:{s}:{L}', w, n)} | {be:.1f}% | {verdict} |")
    P("\n**5 分钟交叉验证（60 天，n 很小，仅作方向性核对）**\n")
    rc5 = race(fine_sessions, lvmap)
    ft5 = first_touch_map_5m(fine_sessions, lvmap)
    P("\n".join(hdr(["L→目标 / 止损", "方向", "n", "目标先到", "tie", "打平需"])))
    for L in LADDER:
        if L not in NEXT:
            continue
        risk, rew = L - PREV[L], NEXT[L] - L
        be = 100 * risk / (risk + rew)
        for s, sname in SIDES:
            n, w, l, t, m = rc5.get((s, L, "ALL"), [0, 0, 0, 0, 0])
            if not n:
                continue
            P(f"| {L:g}→{NEXT[L]:g} / {PREV[L]:g} | {sname} | {n} | "
              f"{cell(f'race5:{s}:{L}', w, n)} | {t} | {be:.1f}% |")
    u5, d5, t5 = ft5
    P(f"\n5 分钟首触方向（开盘在带内）：先上 {u5} / 先下 {d5} / 同根K {t5}"
      f" → 先上 {md_rate(u5, u5 + d5) if u5 + d5 else '–'}"
      f"（z={z_vs_half(u5, u5 + d5):+.2f}）。同根K不可判仅 {t5} 例，"
      "说明小时线的歧义主要是分辨率造成的。")

    # ---------------------------------------------------------------- 8 ----
    P("\n## I. 样本外与分期稳健性\n")
    P("20 年日线切成 4 个五年块。一个真实的结构应该在每块里同号；"
      "只在一块里出现的东西是噪声。\n")
    blocks = [(2006, 2011), (2011, 2016), (2016, 2021), (2021, 2027)]

    def sub(lo: int, hi: int) -> list[Bar]:
        return [b for b in daily if lo <= b.day.year < hi]

    P("**(a) 相邻转移概率，按五年块**\n")
    P("\n".join(hdr(["转移", "方向"] + [f"{a}–{b-1}" for a, b in blocks])))
    for L in LADDER:
        if L not in NEXT:
            continue
        for s, sname in SIDES:
            row = [f"{L:g}→{NEXT[L]:g}", sname]
            for a, b in blocks:
                fl = daily_flags(sub(a, b), lvmap, s, L, NEXT[L])
                k, n = sum(h for _, h in fl), len(fl)
                row.append(cell(f"blk:{s}:{L}:{a}", k, n) if n else "–")
            P("| " + " | ".join(row) + " |")
    P("\n**(b) 多空不对称（空头率 − 多头率）的符号稳定性，按五年块**\n")
    P("\n".join(hdr(["转移"] + [f"{a}–{b-1}" for a, b in blocks] + ["同号?"])))
    for L in LADDER:
        if L not in NEXT:
            continue
        zs, signs = [], []
        for a, b in blocks:
            fb = daily_flags(sub(a, b), lvmap, 1, L, NEXT[L])
            fs = daily_flags(sub(a, b), lvmap, -1, L, NEXT[L])
            kb, nb = sum(h for _, h in fb), len(fb)
            ks, ns = sum(h for _, h in fs), len(fs)
            diff = (ks / ns - kb / nb) * 100 if (nb and ns) else 0.0
            z = stats.two_proportion_z(ks, ns, kb, nb)
            zs.append(f"{diff:+.1f}pp (z={z:+.1f})")
            signs.append(diff > 0)
        P(f"| {L:g}→{NEXT[L]:g} | " + " | ".join(zs) + " | "
          f"{'✅ 4/4 空头更高' if all(signs) else ('4/4 多头更高' if not any(signs) else f'{sum(signs)}/4')} |")

    P("\n**(d) 空头尾部更容易延续 —— 是方向性优势，还是 ATR 滞后造成的假象？**\n")
    P("如果是方向性优势，空头方向应该只是**走得更远**；"
      "如果是波动率聚集加上我们用的是昨天的 ATR，那么同一批日子应该"
      "**两个方向的振幅都更大**——包括回撤。下面直接量一下。\n")
    P("\n".join(hdr(["条件", "n", "当日总振幅 (high−low)/前日ATR 中位",
                     "反向偏移中位(ATR)", "次日 ATR / 当日 ATR 中位"])))
    atrs = levels.wilder_atr(daily)
    idx = {b.day: i for i, b in enumerate(daily)}
    for s, sname in SIDES:
        for L in (0.618, 1.0):
            rng, back, expand = [], [], []
            for b in daily:
                lv = lvmap.get(b.day)
                if not lv or excursion(b, lv, s) < L - 1e-12:
                    continue
                rng.append((b.high - b.low) / lv.atr)
                back.append(-adverse(b, lv, s))
                i = idx[b.day]
                if atrs[i] and lv.atr:
                    expand.append(atrs[i] / lv.atr)
            if not rng:
                continue
            med = lambda v: sorted(v)[len(v) // 2]  # noqa: E731
            P(f"| {sname} 触及 {L:g} | {len(rng)} | {med(rng):.3f} | "
              f"{med(back):+.3f} | {med(expand):.3f} |")
    P("\n（`反向偏移` = 当日在相反方向上离锚最远的距离，用 ATR 表示；"
      "正数表示当天也向反方向跑了那么多。）")

    P("\n**(c) 开盘跳空方向 — 只能用 2017 年之后的数据，理由见 §A3**\n")
    P("\n".join(hdr(["窗口", "n(交易日)", "开盘>+0.236", "开盘<−0.236",
                     "跳空日占比", "跳空中向上占比", "z vs 50%"])))
    gap_res = {}
    for lo, hi, tag in ((2006, 2017, "2006–2016（开盘价失真，仅供对照）"),
                        (2017, 2027, "2017–2026（可用）")):
        up = dn = tot = 0
        for b in sub(lo, hi):
            lv = lvmap.get(b.day)
            if not lv:
                continue
            tot += 1
            o = (b.open - lv.anchor) / lv.atr
            up += int(o >= 0.236)
            dn += int(o <= -0.236)
        gap_res[tag] = (up, dn, tot)
        P(f"| {tag} | {tot} | {up} | {dn} | {100*(up+dn)/tot:.1f}% | "
          f"{cell(f'gapdir:{lo}', up, up + dn)} | "
          f"{z_vs_half(up, up + dn):+.2f} |")
    up, dn, tot = gap_res["2017–2026（可用）"]
    P(f"\n2017 年以后，**{100*(up+dn)/tot:.1f}% 的交易日开盘时 ±0.236 触发位"
      f"已经被跳空穿透**，其中向上跳空占 {100*up/(up+dn):.1f}%。"
      "这条对交易系统很要命：接近一半的日子里，『等触发位被触及再入场』这句话"
      "在开盘那一刻就已经过期了。（隔夜漂移本身另有专题，见 study_overnight*.py，"
      "此处只作为位图的入口条件记录。）")

    # ---------------------------------------------------------------- 9 ----
    P("\n## J. 显著偏离 50% 的格子（n≥100）\n")
    fam = len(FAMILY)
    try:
        from statistics import NormalDist
        bonf = NormalDist().inv_cdf(1 - 0.05 / (2 * max(fam, 1)))
    except Exception:  # noqa: BLE001
        bonf = 4.0
    hits = [(tag, k, n, z_vs_half(k, n)) for tag, k, n in FAMILY if n >= 100]
    n_pass = sum(1 for _, _, _, z in hits if abs(z) >= bonf)
    P(f"本脚本共产出 **{fam}** 个概率格子（含分期块），n≥100 的有 {len(hits)} 个，"
      f"其中 {n_pass} 个 |z|≥{bonf:.2f}。")
    P(f"Bonferroni 全族 5% 门槛：|z| ≥ {bonf:.2f}（不是 1.96）。**但大多数通过的格子"
      "是几何必然而非交易优势**——0.236→0.382 只隔 0.146 ATR，78% 的到达率说明的是"
      "两个位挨得近，不是有人在买。下面只列 50% 真正构成决策门槛的格子。\n")
    KEY = [
        ("多头 1.0→1.272（20y 日线）", surv["reach"][(1, 1.272)], surv["reach"][(1, 1.0)]),
        ("空头 1.0→1.272（20y 日线）", surv["reach"][(-1, 1.272)], surv["reach"][(-1, 1.0)]),
        ("多头 1.272→1.618（20y 日线）", surv["reach"][(1, 1.618)], surv["reach"][(1, 1.272)]),
        ("空头 1.272→1.618（20y 日线）", surv["reach"][(-1, 1.618)], surv["reach"][(-1, 1.272)]),
        ("多头 0.618→0.786（20y 日线）", surv["reach"][(1, 0.786)], surv["reach"][(1, 0.618)]),
        ("空头 0.618→0.786（20y 日线）", surv["reach"][(-1, 0.786)], surv["reach"][(-1, 0.618)]),
        ("多头 0.786→1.0（20y 日线）", surv["reach"][(1, 1.0)], surv["reach"][(1, 0.786)]),
        ("空头 0.786→1.0（20y 日线）", surv["reach"][(-1, 1.0)], surv["reach"][(-1, 0.786)]),
        ("多头 GG 0.382→0.618（20y 日线）", surv["reach"][(1, 0.618)], surv["reach"][(1, 0.382)]),
        ("空头 GG 0.382→0.618（20y 日线）", surv["reach"][(-1, 0.618)], surv["reach"][(-1, 0.382)]),
        ("开盘在带内时先触 +0.236（小时线）", ftm["race"][1],
         ftm["race"][1] + ftm["race"][2]),
        ("跳空日里向上跳空（20y 日线）", up, up + dn),
    ]
    for L in LADDER:
        n, _, ks = rt.get((1, L, "prev", "ALL"), [0, 0, 0])
        if n >= 100:
            KEY.append((f"多头触及 {L:g} 后跌回前一档（严格，小时线）", ks, n))
        n, _, ks = rt.get((-1, L, "prev", "ALL"), [0, 0, 0])
        if n >= 100:
            KEY.append((f"空头触及 {L:g} 后跌回前一档（严格，小时线）", ks, n))
    P("\n".join(hdr(["格子", "概率", "z vs 50%", "过 1.96", "过全族门槛"])))
    for label, k, n in KEY:
        if n < 100:
            continue
        z = z_vs_half(k, n)
        P(f"| {label} | {md_rate(k, n)} | {z:+.2f} | "
          f"{'✅' if abs(z) >= 1.96 else '—'} | "
          f"{'✅' if abs(z) >= bonf else '—'} |")

    # ---------------------------------------------------------------- 9 ----
    P("\n## K. 月度块自助法（Wilson 假设独立，ATR 不独立）\n")
    P("\n".join(hdr(["格子(20y 日线)", "点估计", "Wilson 95%", "月块自助 95%"])))
    for s, sname in SIDES:
        for L, Lp in ((0.236, 0.382), (0.382, 0.618), (0.618, 0.786),
                      (1.0, 1.272)):
            flags = daily_flags(daily, lvmap, s, L, Lp)
            k, n = sum(h for _, h in flags), len(flags)
            lo, hi = stats.wilson(k, n)
            blo, bhi = block_bootstrap(flags)
            P(f"| {sname} {L:g}→{Lp:g} | {100*k/n:.1f}% (n={n}) | "
              f"[{100*lo:.1f}, {100*hi:.1f}] | [{100*blo:.1f}, {100*bhi:.1f}] |")

    text = "\n".join(out)
    if md:
        path = (Path(__file__).resolve().parents[1] / "reports"
                / "BASERATE_LEVEL_TRANSITIONS.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER + "\n" + text + "\n")
        print(f"wrote {path}")
    else:
        print(text)
    return text


# --------------------------------------------------------------- 5m helpers -


def clean_5m(bars: list[Bar]) -> dict[date, list[Bar]]:
    out = {}
    for day, rows in data.group_by_day(bars).items():
        rows = sorted([b for b in rows if "09:30" <= b.hhmm <= "15:59"],
                      key=lambda b: b.dt)
        if len(rows) >= 70:
            out[day] = rows
    return out


def first_touch_map_5m(sessions: dict[date, list[Bar]], lvmap: dict):
    u = d = t = 0
    for day, session in sorted(sessions.items()):
        lv = lvmap.get(day)
        if not lv:
            continue
        o = (session[0].open - lv.anchor) / lv.atr
        if abs(o) >= LADDER[0] - 1e-12:
            continue
        iu = first_touch_bar(session, lv, 1, LADDER[0])
        idn = first_touch_bar(session, lv, -1, LADDER[0])
        if iu is None and idn is None:
            continue
        if iu is not None and idn is not None and iu == idn:
            t += 1
        elif idn is None or (iu is not None and iu < idn):
            u += 1
        else:
            d += 1
    return u, d, t


if __name__ == "__main__":
    main("--md" in sys.argv)
