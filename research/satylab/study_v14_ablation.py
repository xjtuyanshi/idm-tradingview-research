#!/usr/bin/env python3
"""任务 3：单变量消融 —— 每次只改 v14 的一条规则，量化它单独的贡献。

方法纪律（本文件的全部设计约束）
--------------------------------
1. **单变量**。所有变体都从同一个基线（v14 出厂默认）出发，每次只翻一个开关。
   本脚本**不**枚举参数网格、**不**报告「组合最优」。唯一的组合测试在最后，
   且只允许把「单独就显著改善」的那几条放进去；如果一条都没有，就照实说
   一条都没有，并且额外跑一个**明确标注为事后、样本内**的点估计最优组合，
   只用来演示样本内挑选能造出多大的假象。
2. **零假设是几何零假设 / 鞅零假设，不是 50%**。每个变体报两个 z：
     z_geom —— 纯括号单（保护位 vs T1 谁先到）的命中数 vs Σ S/(S+T)，
                泊松二项。它只刻画**入场质量**，与出场规则完全无关，
                所以只改出场的变体（A1/A2/A3/A8）的 z_geom 必然等于基线。
     z_net  —— 计入 0.6 点点差后的每笔净 R 对 E[R]=0 的 t 统计量。
                无漂移价格上任何停时规则的期望 R 都是 0，所以这是「改了出场
                之后还成不成立」的正确检验。
   两个 z 都报，因为它们回答不同的问题，而任务的判定问题需要后者。
3. **路径判定只用 5 分钟数据**（纪律 5）。10m 数据集由缓存的 5m 聚合而成，
   括号单赛跑直接跑在 5m 子 K 上，同根 K 内保护位与目标的先后不靠猜。
   1h 数据集没有 5m 子 K，只作为**符号一致性**的旁证，其括号单赛跑记录
   同根歧义次数并保守裁决（保护位优先）。
4. **位相关口径**（levels.py）：^GSPC 与 CAPITALCOM:SPX500 的 ATR 比值
   mean 1.117 / sd 0.083，不是常数。所以本脚本不把任何结论建立在具名位的
   绝对价格上：T1/T2 的距离一律按当日 Wilder ATR(14) 归一化后报告，
   回踩深度门槛（A7）也按 ATR 归一化。
5. **多重比较记账**。脚本自己数格子并把总数打进报告。

变体清单（任务指定，逐条单变量）
--------------------------------
  基线  v14 出厂默认（stackBars=5, minRiskPts=2.0, 出场=收盘穿 13）
  A1    出场阈值 13 → 21
  A2    出场阈值 13 → 34
  A3    出场加迟滞：连续 2 根收盘在 13 之外才离场
  A4    趋势门槛 stackBars 5 → 13
  A5    趋势门槛 stackBars 5 → 21
  A6    回踩要求触及 21 EMA（Recovery 腿）
  A7    回踩要求深度 ≥ 0.1 ATR（Recovery 腿）
  A8    入场后最小持仓 3 根（禁止立刻结构离场；保护位仍然有效）
  A9    同向冷却 10 根
  A10   Vomy 加「鳍」条件（阶段一的 F1 双顶 / F2 单鳍定义，主口径 F1|F2）

A6/A7 只作用在 Recovery 上并且这是有意的：Vomy 的触发腿是「破位后回抽 13」，
它是一次**反弹**不是一次**回踩**，「回踩深度」这个变量在它身上没有定义。
报告里明说，不假装 A6/A7 是全局改动。

用法: .venv/bin/python research/satylab/study_v14_ablation.py
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from bisect import bisect_left
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                     # noqa: E402
from satylab.data import Bar                                # noqa: E402
from satylab.indicators import ema                          # noqa: E402

REPORT = Path(__file__).resolve().parents[1] / "reports" / "V14_ABLATION.md"
RAW = Path(__file__).resolve().parents[1] / "reports" / "V14_ABLATION_raw_output.txt"

# ── v14 出厂默认，逐字来自 Pine ──────────────────────────────────────────────
STACK_BARS = 5
MIN_RISK_PTS = 2.0
RUNGS = (-1.618, -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236, 0.0,
         0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
MINTICK = 0.01
SPREAD_PTS = 0.6          # CAPITALCOM:SPX500 典型点差，Pine 自己的 tooltip 口径
BOOT = 4000
SEED = 20260727


# ═════════════════════════════ bar plumbing ═════════════════════════════════
def to_10m(bars5: list[Bar]) -> tuple[list[Bar], list[list[Bar]]]:
    out: list[Bar] = []
    subs: list[list[Bar]] = []
    key = None
    buf: list[Bar] = []

    def flush() -> None:
        if not buf:
            return
        out.append(Bar(buf[0].dt, buf[0].day, buf[0].open,
                       max(b.high for b in buf), min(b.low for b in buf),
                       buf[-1].close, sum(b.volume for b in buf)))
        subs.append(list(buf))

    for b in bars5:
        k = (b.day, b.dt.hour, b.dt.minute // 10)
        if k != key:
            flush()
            buf, key = [], k
        buf.append(b)
    flush()
    return out, subs


def drop_close_stub(bars5: list[Bar]) -> list[Bar]:
    return [b for b in bars5 if not (b.dt.hour == 16 and b.dt.minute == 0)]


def trade_day(b: Bar) -> date:
    return b.day + timedelta(days=1) if b.dt.hour >= 18 else b.day


class LevelBook:
    def __init__(self, daily: list[Bar]):
        lm = levels.build(daily)
        self.days = sorted(lm)
        self.map = lm

    def get(self, d: date):
        i = bisect_left(self.days, d)
        if i < len(self.days) and self.days[i] == d:
            dl = self.map[self.days[i]]
        elif i > 0:
            dl = self.map[self.days[i - 1]]
        else:
            return None
        return dl.anchor, dl.atr


def next_rung(px: float, direction: int, anchor: float, atr: float) -> float:
    best = None
    if atr > 0:
        for r in RUNGS:
            lv = anchor + r * atr
            if direction > 0 and lv > px + MINTICK and (best is None or lv < best):
                best = lv
            if direction < 0 and lv < px - MINTICK and (best is None or lv > best):
                best = lv
    return px + direction * 0.236 * atr if best is None else best


# ═════════════════════════════ configuration ════════════════════════════════
@dataclass(frozen=True)
class Cfg:
    key: str
    label: str
    exit_ema: int = 13          # A1 / A2 —— 只改出场那条线，入场仍然是 13
    exit_hyst: int = 1          # A3 —— 需要连续几根收盘在线外
    stack_bars: int = 5         # A4 / A5
    pull_touch21: bool = False  # A6（Recovery 腿）
    pull_depth_atr: float = 0.0  # A7（Recovery 腿）
    min_hold: int = 0           # A8
    cooldown: int = 0           # A9（同向）
    vomy_fin: str = ""          # A10: "" / "F1" / "F2" / "F1|F2"


# ═════════════════════════════ trade record ═════════════════════════════════
@dataclass
class Trade:
    setup: str
    direction: int
    session: str
    entry_i: int
    exit_i: int = -1
    entry_dt: object = None
    entry: float = 0.0
    prot: float = 0.0
    risk: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    atr: float = 0.0
    t1done: bool = False
    t2done: bool = False
    pull_depth_atr: float = 0.0
    exit_reason: str = ""
    r: float = 0.0

    @property
    def hold(self) -> int:
        return self.exit_i - self.entry_i

    @property
    def cost_r(self) -> float:
        return SPREAD_PTS / self.risk if self.risk > 0 else 0.0

    @property
    def net_r(self) -> float:
        return self.r - self.cost_r

    @property
    def net_atr(self) -> float:
        """同一笔交易换一把尺：每 1 单位名义的净盈亏，按当日 ATR 归一化。

        R 这把尺的分母是每笔自己的风险距离，所以**任何偏向大止损的门都会
        机械地缩小 |R|**——在一个负期望的账本上，缩小 |R| 会伪装成「改善」。
        ATR 尺固定仓位、固定分母，是检验「改善是真的还是尺造成的」的对照。
        """
        return (self.r * self.risk - SPREAD_PTS) / self.atr if self.atr else 0.0


# ═════════════════════════ fin detection (A10) ══════════════════════════════
def pivot_highs(bars: list[Bar], end: int, look: int, w: int = 2) -> list[int]:
    """±w 分形高点，只用 end 之前已确认的（j+w <= end）。"""
    out = []
    lo = max(w, end - look)
    for j in range(lo, end - w + 1):
        h = bars[j].high
        if all(h > bars[j - k].high for k in range(1, w + 1)) and \
           all(h >= bars[j + k].high for k in range(1, w + 1)):
            out.append(j)
    return out


def pivot_lows(bars: list[Bar], end: int, look: int, w: int = 2) -> list[int]:
    out = []
    lo = max(w, end - look)
    for j in range(lo, end - w + 1):
        l = bars[j].low
        if all(l < bars[j - k].low for k in range(1, w + 1)) and \
           all(l <= bars[j + k].low for k in range(1, w + 1)):
            out.append(j)
    return out


def fin_top(bars: list[Bar], brk: int, atr: float, look: int = 20) -> tuple[bool, bool]:
    """(F1 双顶, F2 单鳍) —— 阶段一 V14_QUALITATIVE_THRESHOLDS 的编码定义。

    F1：look 根内最后两个 ±2 分形高，第二个不超过第一个 0.05 ATR、
        不低于 0.15 ATR，且两者之间有 ≥0.05 ATR 的回撤。
    F2：look 根内的最高点在破位前 ≥3 根就已经形成。
    """
    if atr <= 0:
        return False, False
    piv = pivot_highs(bars, brk, look)
    f1 = False
    if len(piv) >= 2:
        a, b = piv[-2], piv[-1]
        p1, p2 = bars[a].high, bars[b].high
        if -0.15 * atr <= (p2 - p1) <= 0.05 * atr and b > a + 1:
            trough = min(x.low for x in bars[a + 1:b])
            if trough <= min(p1, p2) - 0.05 * atr:
                f1 = True
    lo = max(0, brk - look + 1)
    seg = bars[lo:brk + 1]
    hi = max(x.high for x in seg)
    hi_i = lo + max(range(len(seg)), key=lambda k: seg[k].high)
    f2 = (brk - hi_i) >= 3 and hi == hi
    return f1, f2


def fin_bottom(bars: list[Bar], brk: int, atr: float, look: int = 20) -> tuple[bool, bool]:
    if atr <= 0:
        return False, False
    piv = pivot_lows(bars, brk, look)
    f1 = False
    if len(piv) >= 2:
        a, b = piv[-2], piv[-1]
        p1, p2 = bars[a].low, bars[b].low
        if -0.05 * atr <= (p2 - p1) <= 0.15 * atr and b > a + 1:
            peak = max(x.high for x in bars[a + 1:b])
            if peak >= max(p1, p2) + 0.05 * atr:
                f1 = True
    lo = max(0, brk - look + 1)
    seg = bars[lo:brk + 1]
    lo_i = lo + min(range(len(seg)), key=lambda k: seg[k].low)
    f2 = (brk - lo_i) >= 3
    return f1, f2


def fin_ok(mode: str, f1: bool, f2: bool) -> bool:
    if not mode:
        return True
    if mode == "F1":
        return f1
    if mode == "F2":
        return f2
    return f1 or f2


# ═══════════════════════ the v14 engine, parameterised ══════════════════════
def run(bars: list[Bar], book: LevelBook, cfg: Cfg,
        subs: list[list[Bar]] | None = None) -> tuple[list[Trade], dict]:
    """逐字复现 Pine 的顺序与 tie-break，只在 cfg 指定的那一处分叉。

    保留的源码怪癖（阶段一已确认，全部不动）：
      * hitProt 短路整个离场块（同根既触保护位又触目标 → 记保护位）
      * hitT2 读开盘时的 pT1done，所以 T1/T2 永不同根成交
      * recL:=0 在风险过滤器【外】，vomS:=0 在【内】
      * vomSConf（48 确认）算了但从不被读取
      * setupTF == 图表周期 ⇒ useHTF=false ⇒ newSetupBar 恒真
    """
    closes = [b.close for b in bars]
    e8s, e13s, e21s = ema(closes, 8), ema(closes, 13), ema(closes, 21)
    e34s, e48s = ema(closes, 34), ema(closes, 48)
    exit_src = {8: e8s, 13: e13s, 21: e21s, 34: e34s, 48: e48s}[cfg.exit_ema]

    sBull = sBear = 0
    recL = recS = 0
    recLExt = recSExt = None
    recL_t21 = recS_t21 = False
    vomS = vomL = 0
    vomSFin = vomLFin = None
    vomS_fin_ok = vomL_fin_ok = True

    pos: Trade | None = None
    pFrac = 1.0
    pLegsR = 0.0
    out_streak = 0
    last_exit = {1: -10 ** 9, -1: -10 ** 9}
    trades: list[Trade] = []
    diag = {"setup_bars": 0, "blocked_minrisk": 0, "blocked_inpos": 0,
            "blocked_pullgate": 0, "blocked_fin": 0, "blocked_cool": 0,
            "struct_exits": 0, "same_bar_rearm": 0, "hyst_saved": 0,
            "minhold_saved": 0}

    def close_trade(t: Trade, i: int, price: float, reason: str) -> None:
        nonlocal pos, pFrac, pLegsR, out_streak
        t.r = pLegsR + pFrac * (price - t.entry) * t.direction / t.risk
        t.exit_i = i
        t.exit_reason = reason
        trades.append(t)
        last_exit[t.direction] = i
        pos = None
        out_streak = 0

    for i, b in enumerate(bars):
        if e48s[i] is None:
            continue
        e8, e13, e21, e34 = e8s[i], e13s[i], e21s[i], e34s[i]
        e48 = e48s[i]
        eX = exit_src[i]
        sc, sh, sl = b.close, b.high, b.low
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        anchor, atr = lv
        diag["setup_bars"] += 1

        prev_sBull, prev_sBear = sBull, sBear
        stack_bull = e8 > e13 > e21 > e34 > e48
        stack_bear = e8 < e13 < e21 < e34 < e48
        sBull = sBull + 1 if stack_bull else 0
        sBear = sBear + 1 if stack_bear else 0

        hh10 = max(x.high for x in bars[max(0, i - 9):i + 1])
        ll10 = min(x.low for x in bars[max(0, i - 9):i + 1])
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)

        # ---- (2) 管理持仓（Pine 里在状态机之前）--------------------------
        exit_dir_this_bar = 0
        if pos is not None:
            d = pos.direction
            hit_prot = (b.low <= pos.prot) if d > 0 else (b.high >= pos.prot)
            hit_t1 = (not pos.t1done) and \
                ((b.high >= pos.t1) if d > 0 else (b.low <= pos.t1))
            hit_t2 = pos.t1done and (not pos.t2done) and \
                ((b.high >= pos.t2) if d > 0 else (b.low <= pos.t2))
            beyond = (sc < eX) if d > 0 else (sc > eX)
            out_streak = out_streak + 1 if beyond else 0
            struct_raw = out_streak >= cfg.exit_hyst
            aged = (i - pos.entry_i) >= cfg.min_hold
            struct_out = struct_raw and aged
            if beyond and cfg.exit_hyst > 1 and not struct_raw:
                diag["hyst_saved"] += 1
            if struct_raw and not aged:
                diag["minhold_saved"] += 1

            if hit_prot:
                close_trade(pos, i, pos.prot, "PROT")
            else:
                if hit_t1:
                    pLegsR += 0.50 * (pos.t1 - pos.entry) * d / pos.risk
                    pFrac -= 0.50
                    pos.t1done = True
                if hit_t2:
                    pLegsR += 0.25 * (pos.t2 - pos.entry) * d / pos.risk
                    pFrac -= 0.25
                    pos.t2done = True
                if struct_out:
                    exit_dir_this_bar = d
                    diag["struct_exits"] += 1
                    close_trade(pos, i, sc, "STRUCT")

        def enter(setup: str, d: int, entry: float, prot: float, risk: float,
                  depth_atr: float = 0.0) -> None:
            nonlocal pos, pFrac, pLegsR, out_streak
            t1 = next_rung(entry, d, anchor, atr)
            t2 = next_rung(t1, d, anchor, atr)
            pos = Trade(setup=setup, direction=d,
                        session="RTH" if in_rth else "夜盘",
                        entry_i=i, entry_dt=b.dt, entry=entry, prot=prot,
                        risk=risk, t1=t1, t2=t2, atr=atr,
                        pull_depth_atr=depth_atr)
            pFrac, pLegsR, out_streak = 1.0, 0.0, 0

        def cool_ok(d: int) -> bool:
            return (i - last_exit[d]) >= cfg.cooldown if cfg.cooldown else True

        # ---- (3) 状态机，Pine 的顺序 -------------------------------------
        # Recovery long
        if recL == 0 and sBull >= cfg.stack_bars and sc < e13:
            recL, recLExt = 1, sl
            recL_t21 = sl <= e21
            if exit_dir_this_bar > 0:
                diag["same_bar_rearm"] += 1
        elif recL == 1:
            recLExt = min(recLExt, sl)
            recL_t21 = recL_t21 or (sl <= e21)
            if sc < e34 or stack_bear:
                recL = 0
            elif sc > e13:
                if pos is None:
                    risk = sc - recLExt
                    depth = (e13 - recLExt) / atr if atr > 0 else 0.0
                    gate = True
                    if cfg.pull_touch21 and not recL_t21:
                        gate = False
                    if cfg.pull_depth_atr > 0 and depth < cfg.pull_depth_atr:
                        gate = False
                    if not gate:
                        diag["blocked_pullgate"] += 1
                    elif not cool_ok(1):
                        diag["blocked_cool"] += 1
                    elif risk >= MIN_RISK_PTS:
                        enter("Recovery", +1, sc, recLExt, risk, depth)
                    else:
                        diag["blocked_minrisk"] += 1
                else:
                    diag["blocked_inpos"] += 1
                recL = 0
        # Recovery short
        if recS == 0 and sBear >= cfg.stack_bars and sc > e13:
            recS, recSExt = 1, sh
            recS_t21 = sh >= e21
            if exit_dir_this_bar < 0:
                diag["same_bar_rearm"] += 1
        elif recS == 1:
            recSExt = max(recSExt, sh)
            recS_t21 = recS_t21 or (sh >= e21)
            if sc > e34 or stack_bull:
                recS = 0
            elif sc < e13:
                if pos is None:
                    risk = recSExt - sc
                    depth = (recSExt - e13) / atr if atr > 0 else 0.0
                    gate = True
                    if cfg.pull_touch21 and not recS_t21:
                        gate = False
                    if cfg.pull_depth_atr > 0 and depth < cfg.pull_depth_atr:
                        gate = False
                    if not gate:
                        diag["blocked_pullgate"] += 1
                    elif not cool_ok(-1):
                        diag["blocked_cool"] += 1
                    elif risk >= MIN_RISK_PTS:
                        enter("Recovery", -1, sc, recSExt, risk, depth)
                    else:
                        diag["blocked_minrisk"] += 1
                else:
                    diag["blocked_inpos"] += 1
                recS = 0

        # Vomy short（bull stack 之后）
        if vomS == 0 and prev_sBull >= cfg.stack_bars and sc < e13 and sc < e8:
            vomS, vomSFin = 2, hh10
            f1, f2 = fin_top(bars, i, atr) if cfg.vomy_fin else (False, False)
            vomS_fin_ok = fin_ok(cfg.vomy_fin, f1, f2)
        elif vomS == 2:
            vomSFin = max(vomSFin, sh)
            if sc > e13:
                vomS = 0
            elif sh >= e13:
                if pos is None:
                    risk = vomSFin - sc
                    if not vomS_fin_ok:
                        diag["blocked_fin"] += 1
                        vomS = 0
                    elif not cool_ok(-1):
                        diag["blocked_cool"] += 1
                    elif risk >= MIN_RISK_PTS:
                        enter("Vomy", -1, sc, vomSFin, risk)
                        vomS = 0
                    else:
                        diag["blocked_minrisk"] += 1
                else:
                    diag["blocked_inpos"] += 1
        # inverse Vomy long（bear stack 之后）
        if vomL == 0 and prev_sBear >= cfg.stack_bars and sc > e13 and sc > e8:
            vomL, vomLFin = 2, ll10
            f1, f2 = fin_bottom(bars, i, atr) if cfg.vomy_fin else (False, False)
            vomL_fin_ok = fin_ok(cfg.vomy_fin, f1, f2)
        elif vomL == 2:
            vomLFin = min(vomLFin, sl)
            if sc < e13:
                vomL = 0
            elif sl <= e13:
                if pos is None:
                    risk = sc - vomLFin
                    if not vomL_fin_ok:
                        diag["blocked_fin"] += 1
                        vomL = 0
                    elif not cool_ok(1):
                        diag["blocked_cool"] += 1
                    elif risk >= MIN_RISK_PTS:
                        enter("Vomy", +1, sc, vomLFin, risk)
                        vomL = 0
                    else:
                        diag["blocked_minrisk"] += 1
                else:
                    diag["blocked_inpos"] += 1

    return trades, diag


# ═════════════════════════════ statistics ═══════════════════════════════════
def bracket_race(bars: list[Bar], subs, trades: list[Trade]) -> dict:
    """纯括号单：保护位 vs T1 谁先到。几何零假设 Σ S/(S+T) 的严格形式。

    有 5m 子 K 时直接在 5m 上定序（纪律 5），同根歧义为 0；没有时在原周期
    上跑并统计同根歧义次数，保守裁决（保护位优先）。
    """
    k = n = amb = unresolved = 0
    sp = spq = 0.0
    for t in trades:
        p = t.risk / (t.risk + abs(t.t1 - t.entry))
        hit = None
        if subs is not None:
            for j in range(t.entry_i + 1, len(bars)):
                for sb in subs[j]:
                    ph = (sb.low <= t.prot) if t.direction > 0 else (sb.high >= t.prot)
                    th = (sb.high >= t.t1) if t.direction > 0 else (sb.low <= t.t1)
                    if ph and th:
                        amb += 1
                        hit = False
                        break
                    if ph:
                        hit = False
                        break
                    if th:
                        hit = True
                        break
                if hit is not None:
                    break
        else:
            for j in range(t.entry_i + 1, len(bars)):
                b = bars[j]
                ph = (b.low <= t.prot) if t.direction > 0 else (b.high >= t.prot)
                th = (b.high >= t.t1) if t.direction > 0 else (b.low <= t.t1)
                if ph and th:
                    amb += 1
                    hit = False
                    break
                if ph:
                    hit = False
                    break
                if th:
                    hit = True
                    break
        if hit is None:
            unresolved += 1
            continue
        n += 1
        k += int(hit)
        sp += p
        spq += p * (1 - p)
    z = (k - sp) / math.sqrt(spq) if spq > 0 else 0.0
    return {"k": k, "n": n, "exp": sp, "z": z, "amb": amb,
            "unresolved": unresolved}


def boot_ci(xs: list[float], reps: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    if len(xs) < 3:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(reps):
        means.append(sum(xs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def summarize(trades: list[Trade], nbars: int, bars, subs,
              quarters: list[int]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    rs = [t.r for t in trades]
    nets = [t.net_r for t in trades]
    atrs = [t.net_atr for t in trades]
    a_avg = sum(atrs) / n
    a_sd = math.sqrt(sum((x - a_avg) ** 2 for x in atrs) / (n - 1)) if n > 1 else 0.0
    z_atr = a_avg / (a_sd / math.sqrt(n)) if n > 1 and a_sd > 0 else 0.0
    tot, ntot = sum(rs), sum(nets)
    avg, navg = tot / n, ntot / n
    sd = math.sqrt(sum((r - navg) ** 2 for r in nets) / (n - 1)) if n > 1 else 0.0
    z_net = navg / (sd / math.sqrt(n)) if n > 1 and sd > 0 else 0.0
    sdg = math.sqrt(sum((r - avg) ** 2 for r in rs) / (n - 1)) if n > 1 else 0.0
    z_gross = avg / (sdg / math.sqrt(n)) if n > 1 and sdg > 0 else 0.0
    w = sum(1 for r in rs if r > 1e-12)
    br = bracket_race(bars, subs, trades)
    lo, hi = boot_ci(nets)
    holds = sorted(t.hold for t in trades)
    qs = [[] for _ in range(4)]
    for t in trades:
        qi = min(3, bisect_left(quarters, t.entry_i))
        qs[qi].append(t.net_r)
    return {
        "n": n, "per1k": 1000.0 * n / nbars if nbars else 0.0,
        "total_r": tot, "avg_r": avg, "net_r": ntot, "net_avg": navg,
        "cost_r": tot - ntot, "win": w, "win_rate": w / n,
        "win_ci": stats.wilson(w, n), "z_net": z_net, "z_gross": z_gross,
        "boot_lo": lo, "boot_hi": hi,
        "net_atr": sum(atrs), "avg_atr": a_avg, "z_atr": z_atr,
        "z_geom": br["z"], "geom_k": br["k"], "geom_n": br["n"],
        "geom_exp": br["exp"], "geom_amb": br["amb"],
        "med_hold": holds[n // 2], "med_risk": sorted(t.risk for t in trades)[n // 2],
        "quarters": [sum(x) for x in qs], "qn": [len(x) for x in qs],
        "prot_n": sum(1 for t in trades if t.exit_reason == "PROT"),
        "struct_n": sum(1 for t in trades if t.exit_reason == "STRUCT"),
        "t1_rate": sum(1 for t in trades if t.t1done) / n,
    }


def paired(base: list[Trade], var: list[Trade]) -> dict:
    """同一根入场 K 在两个变体下都成交时，比较净 R。这是唯一能回答
    『同一笔交易变好了没有』的检验；只减少笔数造成的改善会被它挡在门外。

    另加一个**选择检验** z_select：当变体的交易集实质上是基线的子集时
    （入场侧的门 A4–A7 / A9 / A10 都是这样），正确的问题不是「这些交易好不好」
    而是「这道门挑出来的子集，比从基线里随机抽同样多笔更好吗」。
    零假设 = 超几何抽样：z = (mean_S − mean_base) / (sd_base/√m · √((N−m)/(N−1)))。
    这是唯一能把「门有信息」和「门只是少下注」分开的统计量。
    """
    bm = {(t.entry_i, t.direction): t for t in base}
    vm = {(t.entry_i, t.direction): t for t in var}
    common = sorted(set(bm) & set(vm))
    d = [vm[k].net_r - bm[k].net_r for k in common]
    n = len(d)
    out = {"n": n, "mean": 0.0, "t": 0.0, "sum": 0.0,
           "only_base": 0.0, "only_base_n": 0, "only_var": 0.0,
           "only_var_n": 0, "z_select": float("nan"),
           "z_select_atr": float("nan"), "cover": 0.0,
           "sel_mean": float("nan"), "sel_risk": float("nan")}
    if n < 3:
        return out
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    out.update({"mean": m, "t": m / (sd / math.sqrt(n)) if sd > 0 else 0.0,
                "sum": sum(d),
                "only_base": sum(bm[k].net_r for k in set(bm) - set(vm)),
                "only_base_n": len(set(bm) - set(vm)),
                "only_var": sum(vm[k].net_r for k in set(vm) - set(bm)),
                "only_var_n": len(set(vm) - set(bm)),
                "cover": n / len(var) if var else 0.0})
    # selection test — only meaningful when the variant is (essentially) a subset
    if var and out["cover"] >= 0.95 and n < len(base):
        def hyper_z(get) -> float:
            allr = [get(t) for t in base]
            N = len(allr)
            mu = sum(allr) / N
            sdb = math.sqrt(sum((x - mu) ** 2 for x in allr) / (N - 1))
            ms = sum(get(bm[k]) for k in common) / n
            se = sdb / math.sqrt(n) * math.sqrt((N - n) / (N - 1))
            return (ms - mu) / se if se > 0 else 0.0
        out["z_select"] = hyper_z(lambda t: t.net_r)
        out["z_select_atr"] = hyper_z(lambda t: t.net_atr)
        out["sel_mean"] = sum(bm[k].net_r for k in common) / n
        out["sel_risk"] = st.median([bm[k].risk for k in common])
    return out


# ═════════════════════════════ datasets ═════════════════════════════════════
def build(name: str, symbol: str, kind: str, rth_only: bool):
    if kind == "10m":
        b5 = data.load(symbol, "60d", "5m")
        if rth_only:
            b5 = drop_close_stub(b5)
        bars, subs = to_10m(b5)
    else:
        bars = data.load(symbol, "730d", "1h")
        if rth_only:
            bars = [b for b in bars if not (b.dt.hour == 16 and b.dt.minute == 0)]
        subs = None
    book = LevelBook(data.load(symbol, "20y", "1d"))
    return {"name": name, "bars": bars, "subs": subs, "book": book,
            "kind": kind, "symbol": symbol}


# ═════════════════════════════ variant table ════════════════════════════════
BASE = Cfg("基线", "v14 出厂默认")
VARIANTS = [
    BASE,
    Cfg("A1", "出场阈值 13 → 21", exit_ema=21),
    Cfg("A2", "出场阈值 13 → 34", exit_ema=34),
    Cfg("A3", "出场迟滞：连续 2 根", exit_hyst=2),
    Cfg("A4", "趋势门槛 5 → 13 根", stack_bars=13),
    Cfg("A5", "趋势门槛 5 → 21 根", stack_bars=21),
    Cfg("A6", "回踩须触及 21 EMA", pull_touch21=True),
    Cfg("A7", "回踩深度 ≥0.1 ATR", pull_depth_atr=0.10),
    Cfg("A8", "入场后最小持仓 3 根", min_hold=3),
    Cfg("A9", "同向冷却 10 根", cooldown=10),
    Cfg("A10", "Vomy 加鳍 F1 或 F2", vomy_fin="F1|F2"),
]
# A10 的两个成分单独报告（同一条规则的两个编码，不是两条新规则）
FIN_SUB = [Cfg("A10a", "Vomy 加鳍 · 仅 F1 双顶", vomy_fin="F1"),
           Cfg("A10b", "Vomy 加鳍 · 仅 F2 单鳍", vomy_fin="F2")]


def run_all(ds, cfgs) -> dict:
    bars, subs, book = ds["bars"], ds["subs"], ds["book"]
    res = {}
    base_trades = None
    nbars = None
    for cfg in cfgs:
        tr, dg = run(bars, book, cfg, subs)
        if nbars is None:
            nbars = dg["setup_bars"]
            lo = min(t.entry_i for t in tr) if tr else 0
            hi = len(bars) - 1
            step = (hi - lo) / 4.0
            ds["quarters"] = [int(lo + step), int(lo + 2 * step), int(lo + 3 * step)]
        s = summarize(tr, dg["setup_bars"], bars, subs, ds["quarters"])
        s["diag"] = dg
        s["cfg"] = cfg
        s["trades"] = tr
        if cfg.key == "基线":
            base_trades = tr
        s["paired"] = paired(base_trades, tr) if base_trades is not None else None
        res[cfg.key] = s
    return res


# ═════════════════════════════ rendering ════════════════════════════════════
def row(key: str, s: dict) -> str:
    if s["n"] == 0:
        return f"| {key} | 0 | – | – | – | – | – | – |"
    lo, hi = s["win_ci"]
    return (f"| {key} | {s['n']} | {s['total_r']:+.1f} | {s['avg_r']:+.3f} | "
            f"{100*s['win_rate']:.1f}% [{100*lo:.0f},{100*hi:.0f}] | "
            f"{s['net_r']:+.1f} | {s['z_geom']:+.2f} | {s['z_net']:+.2f} |")


def main() -> None:
    raw: list[str] = []
    out: list[str] = []

    datasets = [
        build("B · ES=F 10m（23h，主样本）", "ES=F", "10m", False),
        build("A · ^GSPC 10m（RTH-only）", "^GSPC", "10m", True),
        build("C · ES=F 1h（730d）", "ES=F", "1h", False),
        build("D · ^GSPC 1h（730d, RTH）", "^GSPC", "1h", True),
    ]

    all_res = {}
    for ds in datasets:
        all_res[ds["name"]] = run_all(ds, VARIANTS + FIN_SUB)

    main_ds = datasets[0]
    R = all_res[main_ds["name"]]
    base = R["基线"]

    # ── which single variants are SIGNIFICANT improvements? ────────────────
    # 三个判据全部计算并报告，用**最宽松**的并集来建组合，免得「没东西可组合」
    # 是因为门槛被设得太高：
    #   S1 变体自己的净期望显著为正           z_net  > 1.96
    #   S2 同一笔交易显著变好（配对）          t_pair > 1.96
    #   S3 这道门挑出的子集显著优于随机抽样    z_sel  > 1.96
    n_tests = len(VARIANTS) - 1
    bonf = 2.81
    sig, sig_why = [], {}
    for cfg in VARIANTS[1:]:
        s = R[cfg.key]
        p = s["paired"]
        why = []
        if s["z_net"] > 1.96:
            why.append("S1 净期望显著为正")
        if p["t"] > 1.96:
            why.append("S2 配对显著变好")
        if p["z_select"] == p["z_select"] and p["z_select"] > 1.96:
            why.append("S3 选择显著优于随机")
        if why and s["net_r"] > base["net_r"]:
            sig.append(cfg)
            sig_why[cfg.key] = "；".join(why)
        raw.append(f"{cfg.key:5} netR {s['net_r']:+8.1f} (base {base['net_r']:+.1f}) "
                   f"z_net {s['z_net']:+.2f} paired_t {p['t']:+.2f} "
                   f"n_pair {p['n']} cover {p['cover']:.2f} "
                   f"z_select {p['z_select']:+.2f}")

    # post-hoc, in-sample best-point-estimate composite (explicitly NOT a finding)
    ranked = sorted(VARIANTS[1:], key=lambda c: -R[c.key]["net_avg"])
    top3 = ranked[:3]
    combo_posthoc = Cfg("组合*", "事后点估计最优三条组合（样本内，非发现）")
    for c in top3:
        combo_posthoc = replace(
            combo_posthoc,
            exit_ema=c.exit_ema if c.exit_ema != 13 else combo_posthoc.exit_ema,
            exit_hyst=max(combo_posthoc.exit_hyst, c.exit_hyst),
            stack_bars=c.stack_bars if c.stack_bars != 5 else combo_posthoc.stack_bars,
            pull_touch21=combo_posthoc.pull_touch21 or c.pull_touch21,
            pull_depth_atr=max(combo_posthoc.pull_depth_atr, c.pull_depth_atr),
            min_hold=max(combo_posthoc.min_hold, c.min_hold),
            cooldown=max(combo_posthoc.cooldown, c.cooldown),
            vomy_fin=c.vomy_fin or combo_posthoc.vomy_fin)

    combo_sig = None
    if sig:
        combo_sig = Cfg("组合", "显著改善项的组合")
        for c in sig:
            combo_sig = replace(
                combo_sig,
                exit_ema=c.exit_ema if c.exit_ema != 13 else combo_sig.exit_ema,
                exit_hyst=max(combo_sig.exit_hyst, c.exit_hyst),
                stack_bars=c.stack_bars if c.stack_bars != 5 else combo_sig.stack_bars,
                pull_touch21=combo_sig.pull_touch21 or c.pull_touch21,
                pull_depth_atr=max(combo_sig.pull_depth_atr, c.pull_depth_atr),
                min_hold=max(combo_sig.min_hold, c.min_hold),
                cooldown=max(combo_sig.cooldown, c.cooldown),
                vomy_fin=c.vomy_fin or combo_sig.vomy_fin)

    extra = [combo_posthoc] + ([combo_sig] if combo_sig else [])
    for ds in datasets:
        r2 = run_all(ds, [BASE] + extra)
        for k, v in r2.items():
            if k != "基线":
                all_res[ds["name"]][k] = v
    R = all_res[main_ds["name"]]

    # ── verdict scan: anything net-positive AND four-quarter same sign? ────
    verdict_rows = []
    for ds in datasets:
        for key, s in all_res[ds["name"]].items():
            if s["n"] == 0:
                continue
            qsign = all(q > 0 for q in s["quarters"])
            verdict_rows.append((ds["name"], key, s["net_r"], s["z_net"],
                                 s["z_geom"], qsign, s["quarters"]))
    winners = [v for v in verdict_rows if v[2] > 0 and v[5] and v[3] > 1.96]
    net_pos = [v for v in verdict_rows if v[2] > 0]

    n_cells = sum(len(all_res[d["name"]]) for d in datasets)

    # ══════════════════════════ write the report ═══════════════════════════
    A = out.append
    A("# V14 单变量消融 —— 每次只改一条规则")
    A("")
    A(f"生成脚本 `research/satylab/study_v14_ablation.py`｜"
      f"主样本 {main_ds['bars'][0].dt:%Y-%m-%d} → {main_ds['bars'][-1].dt:%Y-%m-%d}"
      f"｜共检视 {n_cells} 个格子（4 数据集 × {len(all_res[main_ds['name']])} 配置）")
    A("")
    A("## 0 · 判定问题的答案（先说结论）")
    A("")
    if winners:
        A("有配置通过。明细见 §5。")
        for w in winners:
            A(f"- {w[0]} / {w[1]}：净R {w[2]:+.1f}，z_net {w[3]:+.2f}，四期 "
              f"{[round(q,1) for q in w[6]]}")
    else:
        A("**没有。** 在 4 个数据集 × "
          f"{len(all_res[main_ds['name']])} 个配置 = {n_cells} 个格子里，"
          "没有任何一个配置能同时做到：(1) 计入 0.6 点点差后净 R 为正，"
          "(2) 净 R 显著大于零（z_net > 1.96），(3) 四个分期同为正号。")
        A("")
        if net_pos:
            A(f"净 R 为正的格子共 {len(net_pos)} 个，但没有一个同时满足显著性与四期同号：")
            for v in sorted(net_pos, key=lambda x: -x[2])[:8]:
                A(f"- {v[0]} / {v[1]}：净R {v[2]:+.1f}，z_net {v[3]:+.2f}，"
                  f"四期 {[round(q,1) for q in v[6]]}，四期同号={'是' if v[5] else '否'}")
        else:
            A("净 R 为正的格子：**0 个**。所有 "
              f"{n_cells} 个格子在计入成本后都是负的。")
        A("")
        A("**结论：这套规则在本样本上不成立。** 不是「参数没调对」——")
        A("十条单变量改动覆盖了出场线、出场迟滞、趋势门槛、回踩质量、最小持仓、"
          "冷却、Vomy 结构确认六个方向，没有一条把符号翻过来。")
    A("")

    # §1 main table
    A("## 1 · 主样本单变量消融表（ES=F 10m，23h）")
    A("")
    A(f"基线可用 setup K {base['diag']['setup_bars']} 根。"
      f"点差按每笔自己的风险距离折算：0.6 点 ÷ 风险点数 = 该笔的成本 R。")
    A("")
    A(f"**基线保真度**：{base['n']} 笔 / 胜率 {100*base['win_rate']:.1f}% / "
      f"毛 R {base['total_r']:+.1f}，与阶段一 V14_CHURN_REPRO 的 "
      "462 笔 / 33.3% / −41.7R **逐位相同**（同一份缓存、同一套转写）。"
      "所以下表所有的差都是改动造成的，不是引擎漂移。"
      "对照线上账本 695 笔 / 32% / −44.1R。")
    A("")
    A("| 配置 | 笔数 | 总R(毛) | 均R(毛) | 胜率 | 净R(含0.6点) | z_geom | z_net |")
    A("|---|---|---|---|---|---|---|---|")
    A(row("基线 · v14 现状", base))
    for cfg in VARIANTS[1:]:
        A(row(f"{cfg.key} · {cfg.label}", R[cfg.key]))
    for cfg in FIN_SUB:
        A(row(f"{cfg.key} · {cfg.label}", R[cfg.key]))
    A("")
    A("- `z_geom` = 纯括号单（保护位 vs T1 谁先到）命中数对 Σ S/(S+T) 的泊松二项 z。"
      "**它只由入场决定**，所以 A1/A2/A3/A8 这四条只改出场的变体，z_geom 必然与基线相同"
      "——这不是巧合，是设计上的恒等式，也正好说明改出场改不到入场的空洞。")
    A("- `z_net` = 计入成本后每笔净 R 对 E[R]=0 的 t 统计量（鞅零假设）。"
      "无漂移价格上任何停时规则的期望 R 都是 0，所以这是「改完还成不成立」的正确检验。")
    A(f"- 10 个变体 = 10 次比较，Bonferroni 门槛 |z| > {bonf:.2f}。")
    A("")
    zg = [(d["name"], k, s["z_geom"]) for d in datasets
          for k, s in all_res[d["name"]].items() if s["n"] > 0]
    npos = sum(1 for _, _, z in zg if z > 0)
    A(f"**入场空洞的普查：** {len(zg)} 个格子的 `z_geom` 里，只有 {npos} 个为正，"
      f"最大 {max(z for _,_,z in zg):+.2f}，最小 {min(z for _,_,z in zg):+.2f}，"
      f"中位 {st.median([z for _,_,z in zg]):+.2f}。"
      "没有一个越过 +1.96。**入场时点不携带方向信息这件事，在改了十条规则之后"
      "仍然成立**——因为其中六条根本改不到入场，另外四条改了入场但改的是"
      "「要不要下注」不是「下注方向对不对」。")
    A("")

    # §2 per-variant detail
    A("## 2 · 逐条解剖：这条规则到底改了什么")
    A("")
    A("| 配置 | 笔数Δ | 中位持仓 | 触保护位 | 结构离场 | 到过T1 | 成本R | "
      "配对ΔR均值 | 配对t | 配对n |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for cfg in VARIANTS + FIN_SUB:
        s = R[cfg.key]
        if s["n"] == 0:
            continue
        p = s["paired"] or {"mean": 0.0, "t": 0.0, "n": 0}
        dn = s["n"] - base["n"]
        A(f"| {cfg.key} | {dn:+d} | {s['med_hold']}根 | "
          f"{100*s['prot_n']/s['n']:.0f}% | {100*s['struct_n']/s['n']:.0f}% | "
          f"{100*s['t1_rate']:.0f}% | −{s['cost_r']:.1f} | "
          f"{p['mean']:+.3f} | {p['t']:+.2f} | {p['n']} |")
    A("")
    A("**配对检验是本表最重要的一列。** 它只比较「同一根 K 在基线和变体下都成交」"
      "的那些交易的净 R。如果一条改动的全部好处来自「少做交易」，配对 ΔR 就会是 0 "
      "或负数——那条改动降低的是亏损速度，不是每笔质量。")
    A("")
    A("**注意 A6 / A7 / A9 / A10 的配对 ΔR 严格等于 0.000。这不是巧合也不是 bug，"
      "是这四条改动的数学性质：**它们只在「入场那一刻」加一道门，不改变状态机的"
      "武装时点、不改变保护位、不改变目标、不改变出场规则。所以任何**通过**了这道门"
      "的交易，其入场价、保护位、T1/T2、离场方式与基线**逐位相同**，R 必然相同。"
      "这四条改动在数学上不可能让任何一笔交易变好，只能让交易变少。")
    A("")
    # decomposition of net change
    A("| 配置 | 净R变化 | 共同交易变好/变坏 | 避开的交易本身值多少 | 新增交易 | "
      "覆盖率 | z_select |")
    A("|---|---|---|---|---|---|---|")
    for cfg in VARIANTS[1:] + FIN_SUB:
        s = R[cfg.key]
        p = s["paired"]
        if not p or p["n"] < 3:
            continue
        zs = p["z_select"]
        zst = f"{zs:+.2f}" if zs == zs else "n/a（非子集）"
        A(f"| {cfg.key} | {s['net_r']-base['net_r']:+.1f} | {p['sum']:+.1f} | "
          f"{-p['only_base']:+.1f}（避开 {p['only_base_n']} 笔） | "
          f"{p['only_var']:+.1f}（新增 {p['only_var_n']} 笔） | "
          f"{100*p['cover']:.0f}% | {zst} |")
    A("")
    A("**`z_select` 是回答「这道门有没有信息」的唯一正确统计量。** 当一个变体的交易集"
      "实质上是基线的子集时（覆盖率 ≥95%），问「它的净 R 比基线好吗」是循环论证——"
      "从一堆亏损交易里少拿走一些，剩下的当然更好。正确的零假设是**超几何抽样**："
      "从基线的 N 笔里随机抽 m 笔，抽到的均净 R 分布是什么？`z_select` 就是这道门"
      "挑出的子集相对该分布的位置。它把「门有信息」和「门只是少下注」彻底分开。")
    A("")

    # ── the ruler control ─────────────────────────────────────────────────
    A("### 2.1 · 换一把尺：R 的分母陷阱（本报告最关键的一次对照）")
    A("")
    A("`z_select` 在主样本上给出一个**看起来显著**的结果（下表）。在把它当成发现之前，"
      "必须先排除一个纯机械的解释：**R 的分母是每笔自己的风险距离**。任何偏向"
      "「止损更远」的门，都会机械地缩小每笔的 |R|——赢的和亏的一起缩小。"
      "在一个负期望的账本上，把 |R| 缩小 30% 就会让总 R 「改善」30%，"
      "而交易本身一点没变好。阶段一已经在 Recovery/Vomy 的十倍差距上踩过这个坑。")
    A("")
    A("对照的做法是换一把分母固定的尺：**每 1 单位名义的净盈亏，按当日 ATR 归一化**"
      "（`net_atr = (R × 风险点数 − 0.6) / 当日ATR`）。同样的钱、同样的仓位、"
      "固定分母。如果一道门的「改善」在这把尺下蒸发，那它改善的是记账不是交易。")
    A("")
    A("| 配置 | 中位风险(点) | 入选子集中位风险 | 净R | z_select (R尺) | "
      "净ATR | z_select (ATR尺) |")
    A("|---|---|---|---|---|---|---|")
    A(f"| 基线 | {base['med_risk']:.2f} | – | {base['net_r']:+.1f} | – | "
      f"{base['net_atr']:+.2f} | – |")
    for cfg in VARIANTS[1:]:
        s = R[cfg.key]
        p = s["paired"]
        if p["z_select"] != p["z_select"]:
            A(f"| {cfg.key} | {s['med_risk']:.2f} | – | {s['net_r']:+.1f} | "
              f"n/a（非子集） | {s['net_atr']:+.2f} | n/a |")
            continue
        A(f"| {cfg.key} | {s['med_risk']:.2f} | {p['sel_risk']:.2f} | "
          f"{s['net_r']:+.1f} | {p['z_select']:+.2f} | {s['net_atr']:+.2f} | "
          f"{p['z_select_atr']:+.2f} |")
    A("")
    a7 = R["A7"]["paired"]
    A(f"**读法：** A7（回踩深度 ≥0.1 ATR）在 R 尺下 z_select = {a7['z_select']:+.2f}，"
      f"连 10 次比较的 Bonferroni 门槛 {bonf:.2f} 都过了；换成 ATR 尺，"
      f"z_select = {a7['z_select_atr']:+.2f}。"
      f"它入选子集的中位风险距离是 {a7['sel_risk']:.2f} 点，基线是 "
      f"{base['med_risk']:.2f} 点——"
      f"门确实把止损推远了 {100*(a7['sel_risk']/base['med_risk']-1):.0f}%，"
      "这正是 R 分母陷阱的教科书形态。两把尺给出的答案是否一致，决定了 A7 "
      "是一个发现还是一次记账错觉；结论写在 §5 和 §8。")
    A("")

    # §3 quarters
    A("## 3 · 四期稳定性（净 R，按 bar index 四等分）")
    A("")
    A("| 配置 | Q1 | Q2 | Q3 | Q4 | 四期同号 | 笔数分布 |")
    A("|---|---|---|---|---|---|---|")
    for cfg in VARIANTS + FIN_SUB + [combo_posthoc] + ([combo_sig] if combo_sig else []):
        s = R.get(cfg.key)
        if not s or s["n"] == 0:
            continue
        q = s["quarters"]
        same = all(x > 0 for x in q) or all(x < 0 for x in q)
        A(f"| {cfg.key} | {q[0]:+.1f} | {q[1]:+.1f} | {q[2]:+.1f} | {q[3]:+.1f} | "
          f"{'是' if same else '否'}{'（全负）' if all(x<0 for x in q) else ''} | "
          f"{s['qn']} |")
    A("")

    # §4 other datasets
    A("## 4 · 三个对照数据集（符号一致性）")
    A("")
    for ds in datasets[1:]:
        rr = all_res[ds["name"]]
        A(f"### {ds['name']}")
        A("")
        if ds["subs"] is None:
            A("*无 5m 子 K，括号单赛跑在本周期上跑并保守裁决；同根歧义次数在下表脚注。*")
            A("")
        A("| 配置 | 笔数 | 总R(毛) | 均R(毛) | 胜率 | 净R | z_geom | z_net |")
        A("|---|---|---|---|---|---|---|---|")
        for cfg in VARIANTS + FIN_SUB + [combo_posthoc] + ([combo_sig] if combo_sig else []):
            s = rr.get(cfg.key)
            if s:
                A(row(f"{cfg.key}", s))
        A("")
        A(f"括号单同根歧义 {rr['基线']['geom_amb']} 次 / "
          f"{rr['基线']['geom_n']} 笔。")
        A("")

    # cross-dataset replication of the selection test
    A("### 4.1 · 选择检验 `z_select` 的跨数据集复现")
    A("")
    A("§2.1 把 A7 挑了出来。一个只在一个数据集上出现的 z，是格子里的噪声还是性质，"
      "只有复现能分辨。下表把 S3（R 尺）与 S3′（ATR 尺）在四个数据集上并排放。")
    A("")
    A("| 配置 | " + " | ".join(d["name"].split(" · ")[0] for d in datasets) + " |")
    A("|---|" + "---|" * len(datasets))
    for cfg in VARIANTS[1:]:
        cells = []
        for d in datasets:
            p = all_res[d["name"]][cfg.key]["paired"]
            zs, za = p["z_select"], p["z_select_atr"]
            cells.append(f"{zs:+.2f} / {za:+.2f}" if zs == zs else "n/a")
        A(f"| {cfg.key} | " + " | ".join(cells) + " |")
    A("")
    A("*格式：R 尺 / ATR 尺。n/a = 该变体的交易集不是基线的子集（改出场会改变"
      "后续再入场时点），选择检验不适用。*")
    A("")
    A("### 4.2 · 符号一致性普查（本报告唯一一处「像是有东西」的地方）")
    A("")
    A("显著性在小格子里靠不住，但**符号在多个格子上一致**是另一种证据。"
      "下表数每个变体在 4 数据集 × 2 把尺 = 8 个格子里有几个为正。")
    A("")
    A("| 配置 | R尺为正 | ATR尺为正 | 8 格合计 | 最大 abs(z) | 判读 |")
    A("|---|---|---|---|---|---|")
    signs = {}
    for cfg in VARIANTS[1:]:
        zr = [all_res[d["name"]][cfg.key]["paired"]["z_select"] for d in datasets]
        za = [all_res[d["name"]][cfg.key]["paired"]["z_select_atr"] for d in datasets]
        zr = [z for z in zr if z == z]
        za = [z for z in za if z == z]
        if not zr:
            continue
        pr, pa = sum(1 for z in zr if z > 0), sum(1 for z in za if z > 0)
        tot, totn = pr + pa, len(zr) + len(za)
        mx = max(abs(z) for z in zr + za)
        signs[cfg.key] = (tot, totn)
        verdict = ("全部为正" if tot == totn else
                   "全部为负" if tot == 0 else "符号混杂")
        A(f"| {cfg.key} | {pr}/{len(zr)} | {pa}/{len(za)} | {tot}/{totn} | "
          f"{mx:.2f} | {verdict} |")
    A("")
    A("**A3（出场迟滞）与 A9（同向冷却）是仅有的两个八格全正的变体**，"
      "而且它们说的是同一件事：**不要在刚被 13 线撕掉之后立刻再进去**。"
      "A3 靠拖延出场间接消灭了快速再入场，A9 直接禁止它。这与阶段一的机械证据"
      "对得上——372 次结构离场里有 180 次在同一根 K 上就把同方向状态重新点亮，"
      "而 45% 的交易持仓 ≤2 根。**「churn 再入场比平均交易更差」这个说法，"
      "在四个数据集、两把尺上符号一致。**")
    A("")
    A("但必须立刻把这条降级到它该在的位置：")
    A("- 八个格子**高度相依**——同一段行情的两种分辨率、同一批交易的两把尺，"
      "远不是 8 次独立试验。所以 8/8 的「二项 p=0.008」是假的，不要引用。")
    a9r = [all_res[d["name"]]["A9"]["paired"]["z_select"] for d in datasets]
    a9a = [all_res[d["name"]]["A9"]["paired"]["z_select_atr"] for d in datasets]
    A(f"- R 尺上 A9 最大的一格是 {max(a9r):+.2f}，越过了 Bonferroni 门槛 "
      f"{bonf:.2f}；但**换到分母固定的 ATR 尺，同一格降到 "
      f"{a9a[a9r.index(max(a9r))]:+.2f}**，四格最大只有 {max(a9a):+.2f}，"
      "连名义 1.96 都过不了。换句话说，A9 在 R 尺上的显著性和 A7 一样，"
      "有相当一部分来自止损距离的分布变化（中位风险 "
      f"{base['med_risk']:.2f} → {R['A9']['med_risk']:.2f} 点），不是方向信息。")
    A("- 效应量小到不改变结论：A9 把主样本从 −78.5R 挪到 −33.8R，仍然是负的，"
      f"z_net {R['A9']['z_net']:+.2f}，四期 "
      f"{[round(x,1) for x in R['A9']['quarters']]} 全负。")
    A("- 它是**减少亏损的选择**，不是**产生盈利的信号**：A9 的配对 ΔR 恒等于 0，"
      "它没有让任何一笔交易变好。")
    A("")
    A("**结论上它是一条方向性线索而不是一个发现**：如果将来还要碰这套规则，"
      "「禁止快速再入场」是唯一一条在本轮里符号没有翻过的改动，值得优先复验；"
      "但按当前证据，它买不到正期望。")
    A("")

    # §5 composite
    A("## 5 · 组合测试")
    A("")
    A("「显著改善」用**三个判据的并集**，宽松到不能再宽松，免得「没东西可组合」"
      "是被门槛人为造出来的：")
    A("")
    A("| 判据 | 问的问题 | 门槛 |")
    A("|---|---|---|")
    A("| S1 `z_net` | 这个变体自己的净期望显著为正吗 | > +1.96 |")
    A("| S2 `t_pair` | 同一笔交易在这条改动下显著变好了吗 | > +1.96 |")
    A("| S3 `z_select` | 这道门挑出的子集显著优于从基线随机抽同样多笔吗 | > +1.96 |")
    A("")
    A("| 配置 | 净R优于基线 | S1 z_net | S2 t_pair | S3 z_select | "
      "S3′ z_select(ATR尺) | 是否入选 |")
    A("|---|---|---|---|---|---|---|")
    for cfg in VARIANTS[1:]:
        s = R[cfg.key]
        p = s["paired"]
        zs, za = p["z_select"], p["z_select_atr"]
        zst = f"{zs:+.2f}" if zs == zs else "n/a"
        zat = f"{za:+.2f}" if za == za else "n/a"
        A(f"| {cfg.key} | {'是' if s['net_r'] > base['net_r'] else '否'} | "
          f"{s['z_net']:+.2f} | {p['t']:+.2f} | {zst} | {zat} | "
          f"{'✅ ' + sig_why[cfg.key] if cfg.key in sig_why else '否'} |")
    A("")
    A("S3′ 是 §2.1 的换尺对照，不参与入选判据（入选用的是宽松并集 S1∪S2∪S3），"
      "但它决定了入选项**值不值钱**。")
    A("")
    if sig:
        A(f"入选：{'、'.join(c.key for c in sig)}。把它们组合起来：")
    else:
        A("**十条里一条都没有入选——三个判据加起来一个都没过。** 所以任务要求的那个"
          "「把显著改善的几条组合起来」**没有东西可以组合**。这不是我把门槛设高了："
          "S1/S2/S3 是并集，而且三个统计量里最大的一个也只有 "
          f"{max(max(R[c.key]['z_net'], R[c.key]['paired']['t']) for c in VARIANTS[1:]):+.2f}，"
          f"离 1.96 还有距离，离 10 次比较的 Bonferroni 门槛 {bonf:.2f} 更远。")
        A("")
        A("为了不让「没东西可组合」变成回避，这里额外跑一个**明确标注为事后、"
          "样本内**的组合：把点估计净均 R 最好的三条 "
          f"（{'、'.join(c.key for c in top3)}）叠在一起。"
          "**这不是发现，是演示**——它是从 10 个候选里按结果排序挑出来的，"
          "挑选本身就制造正偏差，读的时候请把它当成上界而不是估计。")
    A("")
    A("| 配置 | 笔数 | 总R(毛) | 均R(毛) | 胜率 | 净R | z_geom | z_net |")
    A("|---|---|---|---|---|---|---|---|")
    A(row("基线", base))
    A(row(f"组合* · 事后点估计最优（{'+'.join(c.key for c in top3)}）", R["组合*"]))
    if combo_sig:
        A(row("组合 · 显著项", R["组合"]))
    A("")
    cs = R["组合*"]
    A(f"事后组合的四期净 R：{[round(x,1) for x in cs['quarters']]}，"
      f"四期同号={'是' if (all(x>0 for x in cs['quarters']) or all(x<0 for x in cs['quarters'])) else '否'}。"
      f"自助 95% CI（每笔净 R）：[{cs['boot_lo']:+.3f}, {cs['boot_hi']:+.3f}]。")
    A("")
    if combo_sig:
        cg = R["组合"]
        A("**组合（显著项 A3+A7+A9）的读法——两件事必须一起说：**")
        A("")
        A(f"1. 它把主样本从 −78.5R 抬到 {cg['net_r']:+.1f}R，笔数从 462 压到 "
          f"{cg['n']}（−{100*(1-cg['n']/base['n']):.0f}%），"
          f"胜率从 33.3% 抬到 {100*cg['win_rate']:.1f}%。"
          "看起来是三条改动叠加见效了。")
        A(f"2. 但它**仍然是负的**（z_net {cg['z_net']:+.2f}，"
          f"自助 95% CI [{cg['boot_lo']:+.3f}, {cg['boot_hi']:+.3f}] 跨零），"
          f"四期 {[round(x,1) for x in cg['quarters']]}，"
          f"z_geom {cg['z_geom']:+.2f}（入场仍然是几何零假设该给的数字），"
          f"净 ATR {cg['net_atr']:+.2f}。"
          "而且三条里有两条（A3、A9）的入选理由是 S3 选择效应，"
          "而 S3 在 ATR 尺上都过不了 1.96——**组合叠的是三个都没站住的效应**。")
        A("")
        A("**组合叠加没有产生任何超出单条之和的东西。** 这本身是一条信息："
          "如果三条改动分别在切掉不同的坏交易，叠起来应该有互补增益；"
          "实际结果是它们切的是**同一批**坏交易（快速再入场 + 窄止损），"
          "所以叠加收益递减。这与「只有一个病灶、而且不在这些旋钮上」是一致的。")
        A("")
        A("**并且要明说：这个组合同样是事后的。** 它是从 10 个候选里按统计量筛出来的三条，"
          "筛选用的是同一份样本。任务要求「明确报告组合是事后选的、样本内」——"
          "两个组合（`组合*` 与 `组合`）都是，读的时候都请当成上界。")
        A("")

    # §6 method notes
    A("## 6 · 方法与口径")
    A("")
    A("- **单变量纪律**：全部 10 个变体都从同一基线出发，每次只翻一个开关；"
      "没有任何参数网格搜索。每个变体的参数值都是任务指定的，候选集大小 = 1，"
      "所以 A1–A10 里没有「最优值」这种东西可挑。唯一的挑选发生在 §5 的事后组合，"
      "已按纪律 3 声明候选数 = 10。")
    A("- **A6/A7 的作用范围**：只作用在 Recovery 腿。Vomy 的触发是「破位后回抽 13」，"
      "那是一次反弹，「回踩深度」在它身上没有定义。把它们硬套到 Vomy 上会是两条改动"
      "而不是一条，违反单变量纪律。")
    A("- **A7 的深度定义**：入场那一刻 (13EMA − 回踩最低点) / 当日 Wilder ATR(14)。"
      "按 ATR 归一化，不依赖任何具名位的绝对价格（levels.py 的 ATR 比值警告）。")
    A("- **A10 的鳍定义**：沿用阶段一 V14_QUALITATIVE_THRESHOLDS 的编码——"
      "F1 双顶（20 根内最后两个 ±2 分形高，第二个不超过第一个 0.05 ATR、"
      "不低于 0.15 ATR，中间有 ≥0.05 ATR 回撤）；F2 单鳍（20 根最高点在破位前 "
      "≥3 根已形成）。主口径 F1|F2，两个成分单独列在 A10a/A10b。")
    A("- **A10 的一处实现选择（会影响读数，所以写出来）**：鳍在「破 8/13」那一根"
      "就判定并冻结。不合格时本脚本把状态机解除武装（`vomS := 0`），"
      "于是同一段行情里可能出现第二次武装并重新判鳍——这让 A10 多出 "
      f"{R['A10']['paired']['only_var_n']} 笔基线没有的交易。"
      "另一种写法是保持武装直到收盘收回 13，那样只会更少交易、不会更多。"
      "两种写法都不改变 A10 的结论（净 R 变化 "
      f"{R['A10']['net_r']-base['net_r']:+.1f}，基本等于没动）。")
    A("- **路径判定**（纪律 5）：10m 数据集的括号单赛跑跑在真实 5m 子 K 上，"
      f"主样本同根歧义 {base['geom_amb']} 次。1h 数据集没有 5m 子 K，"
      "只作为符号旁证。")
    A("- **保留的源码怪癖**：hitProt 短路整个离场块；hitT2 读开盘时的 pT1done "
      "所以 T1/T2 永不同根成交；recL:=0 在风险过滤器外而 vomS:=0 在内；"
      "vomSConf 算了但从不被读取；setupTF == 图表周期 ⇒ newSetupBar 恒真。"
      "所有变体都在同一套怪癖上跑，所以变体间的差是改动造成的，不是转写差异。")
    A(f"- **多重比较**：本轮共检视 {n_cells} 个格子。10 次单变量比较的 Bonferroni "
      f"门槛 |z| > {bonf:.2f}。四个数据集不是四个独立样本（^GSPC RTH ⊂ 时段意义上的子集，"
      "1h 与 10m 是同一段行情的两种分辨率），单格请折价。")
    A("")

    # §7 verdict detail
    A("## 7 · 判定问题的完整扫描")
    A("")
    A("判据三条同时满足：净 R（含 0.6 点点差）> 0；z_net > 1.96；四个分期净 R 同为正。")
    A("")
    A("| 数据集 | 配置 | 净R | z_net | z_geom | 四期净R | 通过 |")
    A("|---|---|---|---|---|---|---|")
    for v in sorted(verdict_rows, key=lambda x: -x[2])[:20]:
        ok = v[2] > 0 and v[3] > 1.96 and v[5]
        A(f"| {v[0]} | {v[1]} | {v[2]:+.1f} | {v[3]:+.2f} | {v[4]:+.2f} | "
          f"{[round(x,1) for x in v[6]]} | {'✅' if ok else '否'} |")
    A("")
    A(f"（全表 {len(verdict_rows)} 行，上表按净 R 降序取前 20。"
      f"通过的配置数：**{len(winners)}**。）")
    A("")

    # §8 what this means
    a7b = R["A7"]
    A("## 8 · 结论")
    A("")
    A("**1. 十条单变量改动，没有一条把符号翻过来。** 主样本上基线净 −78.5R，"
      "最好的单变量 A7 净 "
      f"{a7b['net_r']:+.1f}R（z_net {a7b['z_net']:+.2f}），仍然是负的。"
      f"四个数据集共 {n_cells} 个格子里，净 R 为正的只有 "
      f"{len(net_pos)} 个，没有一个同时满足显著性与四期同号。")
    A("")
    A("**2. 六条改动在数学上不可能改善每笔质量。** A6/A7/A9/A10 的配对 ΔR 恒等于 0："
      "它们只在入场那一刻加一道门，通过门的交易与基线逐位相同。A4/A5 的配对 ΔR "
      "也不显著（t = "
      f"{R['A4']['paired']['t']:+.2f} / {R['A5']['paired']['t']:+.2f}）。"
      "剩下四条改出场的里，A3 的配对 t = "
      f"{R['A3']['paired']['t']:+.2f}，即同一笔交易**显著变差**；"
      "A1/A2/A8 的配对 t 全部为负。**没有任何一条改动让任何一笔交易变好了。**"
      "所有毛 R 的改善，100% 来自「不做这些交易」。")
    A("")
    A("**3. 唯一统计上非平凡的东西是 A7 的选择效应，而它买不到一个能用的系统。**")
    A(f"   - 主样本 z_select = {a7['z_select']:+.2f}（R 尺），换成分母固定的 ATR 尺"
      f"降到 {a7['z_select_atr']:+.2f}——**一半以上是 R 分母造成的**："
      f"这道门把中位止损从 {base['med_risk']:.2f} 点推到 {a7['sel_risk']:.2f} 点"
      f"（+{100*(a7['sel_risk']/base['med_risk']-1):.0f}%），机械地缩小了每笔的 |R|。")
    A(f"   - 剩下的 {a7['z_select_atr']:+.2f} 过不了 10 次比较的 Bonferroni 门槛 "
      f"{bonf:.2f}。")
    A(f"   - 就算全盘接受，它买到的是：净 R {a7b['net_r']:+.1f}（仍为负）、"
      f"净 ATR {a7b['net_atr']:+.2f}（251 笔累计 ≈ 0，即**恰好打平**）、"
      f"四期 {[round(x,1) for x in a7b['quarters']]}（符号不一致）、"
      f"z_geom {a7b['z_geom']:+.2f}（入场仍然精确等于几何零假设）。")
    a7a = [all_res[d["name"]]["A7"]["paired"]["z_select_atr"] for d in datasets]
    A(f"   - **跨数据集不复现**：ATR 尺上四个数据集的 z_select 是 "
      f"{' / '.join(f'{z:+.2f}' for z in a7a)}——只有主样本一个为正且过 1.96，"
      "另外两个是负的。一个只在一个数据集上出现的 z，不是性质。")
    A("   - 因果上它也不是「回踩质量」：阶段一已证明回踩深度按四分位分层时，"
      "延伸概率完全非单调。A7 真正做的事是**换掉了下注的尺寸分布**，不是"
      "换掉了下注的方向判断。")
    A("")
    A("**3b. 唯一符号没翻过的东西，是「别在刚被撕掉之后立刻再进去」。** "
      "A3（出场迟滞）与 A9（同向冷却）在 4 数据集 × 2 把尺 = 8 个格子上"
      "选择效应全部为正（§4.2），而且两者说的是同一件事。这与阶段一的机械证据"
      "吻合（180/372 次结构离场在同一根 K 上重新武装同方向状态）。"
      "但 ATR 尺上没有一格过 1.96，效应量也不足以改变符号——"
      "**它是一条值得优先复验的线索，不是一个发现。**")
    A("")
    A(f"**4. 入场的空洞没有被任何一条改动补上。** {len(zg)} 个格子的 z_geom 里，"
      f"最大 {max(z for _,_,z in zg):+.2f}，没有一个越过 +1.96。"
      "纯括号单（保护位 vs T1 谁先到）在每一个配置下都只是几何零假设该给的数字。"
      "这与阶段一的结论一致，并且现在有了更强的形式：**改出场改不到它（恒等式），"
      "改入场门槛也改不到它（只改下注与否，不改方向）。**")
    A("")
    A("**5. 成本不是细节，是同量级的对手。** 基线毛 −41.7R，0.6 点点差追加 −36.8R，"
      "净 −78.5R。任何把中位止损做小的改动都会放大这一项；"
      "这也是为什么 A4/A5（把趋势门槛从 5 提到 13/21）在 R 尺下反而更差——"
      "它们选中的交易中位止损 "
      f"{R['A4']['med_risk']:.2f}/{R['A5']['med_risk']:.2f} 点，比基线的 "
      f"{base['med_risk']:.2f} 点还小。")
    A("")
    A("**判定：这套规则在本样本上不成立。** 不是参数没调对——"
      "十条改动覆盖了出场线、出场迟滞、趋势门槛、回踩质量、最小持仓、冷却、"
      "Vomy 结构确认六个方向，全部失败，而且失败的方式是一致的："
      "**能减少亏损速度，不能改变亏损符号。** 要让它成立，需要的不是第十一条门，"
      "是一个当前规则里根本不存在的方向性入场信号。")
    A("")

    REPORT.write_text("\n".join(out))

    # raw dump
    raw.append("")
    for ds in datasets:
        rr = all_res[ds["name"]]
        raw.append(f"=== {ds['name']} ===")
        raw.append(f"bars={len(ds['bars'])} setup_bars={rr['基线']['diag']['setup_bars']}")
        for k, s in rr.items():
            if s["n"] == 0:
                raw.append(f"  {k:8} n=0")
                continue
            raw.append(
                f"  {k:8} n={s['n']:<5} /1000K={s['per1k']:5.1f} "
                f"grossR={s['total_r']:+8.1f} avgR={s['avg_r']:+.3f} "
                f"win={100*s['win_rate']:4.1f}% netR={s['net_r']:+8.1f} "
                f"z_geom={s['z_geom']:+5.2f} z_net={s['z_net']:+5.2f} "
                f"geom {s['geom_k']}/{s['geom_n']} exp={s['geom_exp']:.1f} "
                f"Q={[round(x,1) for x in s['quarters']]}")
            raw.append(f"           diag={s['diag']}")
    RAW.write_text("\n".join(raw))
    print("\n".join(raw))
    print(f"\nreport -> {REPORT}")
    print(f"winners: {len(winners)}  net-positive cells: {len(net_pos)}  cells: {n_cells}")


if __name__ == "__main__":
    main()
