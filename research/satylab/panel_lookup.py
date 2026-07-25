"""Probability-panel lookup tables + reference renderer.

This is the machine-readable half of `research/reports/PROBABILITY_PANEL_SPEC.md`.
It does NOT invent any statistic.  Every table it builds is one of the tables
already published in the base-rate reports; the only thing added here is the
**serving logic**: given a live state, which cell do we read, how confident is
it, and when must the panel say "样本不足" instead of printing a number.

Design rules (fixed before looking at any output — no grid search here):

  1. The panel never shows a probability without n and a Wilson 95% interval.
  2. Cells degrade along a fixed fallback chain, coarsest-last:
         hour-conditioned hourly (730d)  ->  all-hours hourly (730d)
         ->  unconditional daily (20y)   ->  INSUFFICIENT
     The tier that actually served the number is always displayed.
  3. Tier thresholds (chosen once, on decision-usefulness grounds, not tuned):
         A  n >= 100 and Wilson width <= 20pp   -> print the number
         B  n >=  30 and Wilson width <= 35pp   -> print with a wide-CI flag
         C  otherwise                            -> print "样本不足 (n=..)"
     A 35pp-wide interval cannot separate "likely" from "coin flip", which is
     the only question the panel is being asked, so it is not shown as a rate.
  4. Direction is never asserted.  Both sides of every level are always shown.

Run:
    .venv/bin/python research/satylab/panel_lookup.py            # tables + demo panel
    .venv/bin/python research/satylab/panel_lookup.py --day 2026-07-23
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats  # noqa: E402
from satylab.levels import DayLevels  # noqa: E402

LADDER = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)
HOURS = ("OPEN", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")

# Tier thresholds — see docstring rule 3.
TIER_A_N, TIER_A_W = 100, 0.20
TIER_B_N, TIER_B_W = 30, 0.35


# ----------------------------------------------------------------- cells ---
@dataclass
class Cell:
    k: int = 0
    n: int = 0
    src: str = ""

    def add(self, hit: bool) -> None:
        self.n += 1
        self.k += int(hit)

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return stats.wilson(self.k, self.n)

    @property
    def width(self) -> float:
        lo, hi = self.ci
        return hi - lo

    @property
    def tier(self) -> str:
        if self.n >= TIER_A_N and self.width <= TIER_A_W:
            return "A"
        if self.n >= TIER_B_N and self.width <= TIER_B_W:
            return "B"
        return "C"

    def render(self) -> str:
        """The exact string the panel is allowed to print."""
        if self.n == 0:
            return "样本不足 (n=0)"
        if self.tier == "C":
            return f"样本不足 (n={self.n})"
        lo, hi = self.ci
        flag = "" if self.tier == "A" else " ~宽"
        return f"{100*self.rate:.0f}% [{100*lo:.0f},{100*hi:.0f}] n={self.n}{flag}"


# ------------------------------------------------------------- day model ---
def hour_slot(sess: list[data.Bar], idx: int) -> str:
    return sess[idx].hhmm if sess[idx].hhmm in HOURS else "OTHER"


def clean_sessions(hourly: list[data.Bar], lv: dict[date, DayLevels]):
    """722-ish complete 7-bar RTH sessions that also have a level map."""
    out = []
    for day, bars in data.group_by_day(hourly).items():
        if day not in lv:
            continue
        bars = [b for b in bars if b.hhmm in HOURS[1:]]
        if len(bars) != 7:
            continue
        out.append((day, bars, lv[day]))
    out.sort(key=lambda x: x[0])
    return out


def first_touch_slot(sess: list[data.Bar], L: DayLevels,
                     ratio: float, side: int) -> str | None:
    """'OPEN' if the opening print is already through the level, else the
    hh:mm of the first bar that reaches it, else None."""
    price = L.at(side * ratio)
    o = sess[0].open
    if (o >= price) if side > 0 else (o <= price):
        return "OPEN"
    for b in sess:
        if (b.high >= price) if side > 0 else (b.low <= price):
            return b.hhmm
    return None


# --------------------------------------------------------------- tables ---
def build_tables():
    d = data.daily(years="20y")
    h = data.hourly()
    lv = levels.build(d)
    sessions = clean_sessions(h, lv)

    # T1 hourly, conditioned on the hour of first touch of the FROM level.
    t_hour: dict[tuple[int, float, float, str], Cell] = {}
    # T2 hourly, pooled over hours.
    t_all: dict[tuple[int, float, float], Cell] = {}

    for _day, sess, L in sessions:
        for side in (+1, -1):
            for i, a in enumerate(LADDER):
                slot = first_touch_slot(sess, L, a, side)
                if slot is None:
                    continue
                for b in LADDER[i + 1:]:
                    tgt = L.at(side * b)
                    hit = any((x.high >= tgt) if side > 0 else (x.low <= tgt)
                              for x in sess)
                    t_hour.setdefault((side, a, b, slot), Cell()).add(hit)
                    t_all.setdefault((side, a, b), Cell()).add(hit)

    # T3 daily 20y, unconditional (high/low only — immune to the open defect).
    t_daily: dict[tuple[int, float, float], Cell] = {}
    prev = None
    for bar in d:
        L = lv.get(bar.day)
        prev = bar
        if L is None:
            continue
        for side in (+1, -1):
            reach = {}
            for r in LADDER:
                p = L.at(side * r)
                reach[r] = (bar.high >= p) if side > 0 else (bar.low <= p)
            for i, a in enumerate(LADDER):
                if not reach[a]:
                    continue
                for b in LADDER[i + 1:]:
                    t_daily.setdefault((side, a, b), Cell()).add(reach[b])

    # T4 remaining-travel budget: from each hour's OPEN price, locked
    # direction, how often does price still travel >= D ATR.
    budget: dict[tuple[str, float, int], Cell] = {}
    best: dict[tuple[str, float], Cell] = {}
    dead: dict[str, Cell] = {}
    for _day, sess, L in sessions:
        for t, bar in enumerate(sess):
            slot = bar.hhmm
            p0 = bar.open
            rest = sess[t:]
            up = (max(x.high for x in rest) - p0) / L.atr
            dn = (p0 - min(x.low for x in rest)) / L.atr
            for D in (0.118, 0.236, 0.382, 0.5):
                budget.setdefault((slot, D, +1), Cell()).add(up >= D)
                budget.setdefault((slot, D, -1), Cell()).add(dn >= D)
                best.setdefault((slot, D), Cell()).add(max(up, dn) >= D)
            dead.setdefault(slot, Cell()).add(max(up, dn) < 0.236)

    return dict(daily=d, hourly=h, lv=lv, sessions=sessions,
                t_hour=t_hour, t_all=t_all, t_daily=t_daily,
                budget=budget, best=best, dead=dead)


# --------------------------------------------------------------- serving ---
def lookup_transition(T, side: int, frm: float, to: float,
                      slot: str | None) -> tuple[Cell, str]:
    """The fallback chain from the module docstring.  Returns (cell, tier-src)."""
    if slot is not None:
        c = T["t_hour"].get((side, frm, to, slot))
        if c and c.tier in ("A", "B"):
            return c, f"1h/{slot}"
    c = T["t_all"].get((side, frm, to))
    if c and c.tier in ("A", "B"):
        return c, "1h/全时段"
    c = T["t_daily"].get((side, frm, to))
    if c and c.tier in ("A", "B"):
        return c, "20y日线/无条件"
    # nothing qualified — report the most-populated one so n is visible
    cands = [(T["t_hour"].get((side, frm, to, slot)) if slot else None,
              f"1h/{slot}"),
             (T["t_all"].get((side, frm, to)), "1h/全时段"),
             (T["t_daily"].get((side, frm, to)), "20y日线")]
    cands = [(c, s) for c, s in cands if c]
    if not cands:
        return Cell(), "无数据"
    c, s = max(cands, key=lambda x: x[0].n)
    return c, s


# ----------------------------------------------------------------- panel ---
def dwidth(s: str) -> int:
    """Display width — CJK / box glyphs occupy two terminal columns."""
    w = 0
    for ch in s:
        o = ord(ch)
        if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
                or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
                or 0xFFE0 <= o <= 0xFFE6 or 0x2460 <= o <= 0x24FF
                or 0x3000 <= o <= 0x303F):
            w += 2
        else:
            w += 1
    return w


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def render_panel(T, day: date, upto: str = "11:30", width: int = 92) -> str:
    """Render the panel as it would look at `upto` on `day`, using only bars
    at or before that hour.  Nothing here is forward-looking."""
    sess_map = {d: (s, L) for d, s, L in T["sessions"]}
    if day not in sess_map:
        raise SystemExit(f"{day} not a clean session in the 730d window")
    sess, L = sess_map[day]
    i = [b.hhmm for b in sess].index(upto)
    seen = sess[: i + 1]
    px = seen[-1].close
    r = L.ratio_of(px)
    r_hi = L.ratio_of(max(b.high for b in seen))
    r_lo = L.ratio_of(min(b.low for b in seen))
    r_open = L.ratio_of(sess[0].open)
    fh = seen[0]                                  # 09:30 bar = first hour
    fh_amp = (fh.high - fh.low) / L.atr
    fh_reach = max(abs(L.ratio_of(fh.high)), abs(L.ratio_of(fh.low)))

    # The research conditions on the hour at which the FROM level was first
    # touched, NOT on the current hour.  The panel must therefore remember,
    # per side and per level, when it was first reached today.
    touched_up = [x for x in LADDER if r_hi >= x - 1e-9]
    touched_dn = [x for x in LADDER if -r_lo >= x - 1e-9]
    ft_up = {x: first_touch_slot(seen, L, x, +1) for x in touched_up}
    ft_dn = {x: first_touch_slot(seen, L, x, -1) for x in touched_dn}

    W = width
    out = ["┌" + "─" * W + "┐"]
    body: list[str] = []

    def row(s: str = "") -> None:
        body.append(s)

    head = (f"SPX 概率地图   {day}  {upto} ET   "
            f"ATR(前日)={L.atr:.1f}   锚(PDC)={L.anchor:.1f}")
    row(head)
    row("═" * (W - 2))

    # ① 你在哪
    row(f"① 我在哪    {px:.1f} = {r:+.3f} ATR   "
        f"今日高 {r_hi:+.3f} / 低 {r_lo:+.3f}   开盘 {r_open:+.3f}")
    row(f"            {_band_name(r)}")
    for ln in _gap_line(r_open):
        row(f"            {ln}")
    row()

    # ② 时钟
    slot = upto
    row(f"② 时钟      剩余 {_mins_left(slot)} 分钟"
        f"    <- 这一行与有没有信号无关，永远有值")
    row(f"            还能再走 0.236 ATR   最优边(上界) "
        f"{T['best'][(slot, 0.236)].render()}")
    row(f"                                 锁定多 "
        f"{T['budget'][(slot, 0.236, +1)].render()}   锁定空 "
        f"{T['budget'][(slot, 0.236, -1)].render()}")
    row(f"            今日行程已用尽(两边 0.236 都到不了) "
        f"{T['dead'][slot].render()}")
    row()

    # ③ 今日模式（首小时否决器）
    _v = _first_hour_verdict(fh_amp, fh_reach)
    row("③ 今日模式  " + _v[0])
    for ln in _v[1:]:
        row(ln)
    row()

    # ④/⑤ 阶梯
    row("④ 上行阶梯  (起点 = 今日已触及的最高上方档；概率 = 当日内到达)")
    body += _ladder_rows(T, +1, touched_up, ft_up, slot, L, r)
    row()
    row("⑤ 下行阶梯")
    body += _ladder_rows(T, -1, touched_dn, ft_dn, slot, L, r)
    row()

    # ⑥ 回归
    _pd = _pdc_row(touched_up, touched_dn)
    row("⑥ 回锚概率  " + _pd[0])
    for ln in _pd[1:]:
        row("            " + ln)
    row()

    # ⑦ 明确的空
    row("⑦ 已知为空  方向: 首小时方向不预测当日方向 (22.0% vs 26.7%, z=+/-1.50, n=722)")
    row("            方向: ribbon 位置不预测先摸哪边 (52.0% vs 基准 52.0%, z=+0.00, n=1337)")
    row("            方向: 触发箱内先上还是先下 (53.6% [48,59] n=336, z=+1.31)")
    row("            -> 本面板不显示任何方向判断。两侧永远同时显示。")

    for line in body:
        out.append("│ " + pad(line, W - 2) + " │")
    out.append("└" + "─" * W + "┘")
    return "\n".join(out)


def _gap_line(r_open: float) -> list[str]:
    """SPY 20y gap-fill table (BASERATE_OPENING_TYPE §5.4) + amplitude §3.1."""
    a = abs(r_open)
    if a < 0.236:
        fill = ("87.6% [86,89] n=1075" if r_open < 0 else "85.0% [83,87] n=1270")
        amp = "P(日振幅>=1ATR) 25.5% [23,28] n=1294  低于基准 33.0%"
    elif a < 0.5:
        fill = ("58.4% [55,62] n=659" if r_open < 0 else "54.7% [52,58] n=946")
        amp = "P(日振幅>=1ATR) 32.9% [31,35] n=1605  约等于基准"
    else:
        fill = ("33.2% [29,37] n=506" if r_open < 0 else "27.3% [24,31] n=560")
        amp = "P(日振幅>=1ATR) 46.9% [44,50] n=1066  高于基准 33.0%"
    return [f"开盘形态: 跳空 {r_open:+.3f} ATR -> 当日回补锚 {fill}",
            f"          {amp}"]


def _first_hour_verdict(amp: float, reach: float) -> list[str]:
    """BASERATE_TIME_STRUCTURE §5 (4a/4b) - a veto, never an entry."""
    if reach < 0.236:
        out = ["首小时未越过 0.236 档 -> 10:30 后触 +/-1ATR 仅 5.8% [2.7,12.0] n=104",
               "            (基线 29.5% [26,33] n=722)"]
        if amp < 0.30:
            out.append("            首小时振幅 <0.30 ATR 同时成立 -> 4.1% [1.4,11.3] n=74")
        out.append("            => 降级为区间日: 关闭所有 >=0.382 ATR 的目标")
        return out
    if reach >= 0.382:
        out = ["首小时已越过 0.382 档 -> 10:30 后触 +/-1ATR 41.7% [37,46] n=472",
               "            (基线 29.5% [26,33] n=722)"]
        if amp > 0.57:
            out.append("            首小时振幅 >0.57 ATR 同时成立 -> 56.9% [50,64] n=174")
        return out
    return ["首小时只到 0.236 档 -> 10:30 后触 +/-1ATR 6.8% [3.8,12.1] n=146",
            "            (基线 29.5% [26,33] n=722)"]


def _band_name(r: float) -> str:
    a, s = abs(r), ("上" if r >= 0 else "下")
    if a < 0.236:
        return "区间: 触发箱内 (|r|<0.236)  -  两侧触发位都还没被打掉"
    if a < 0.382:
        return f"区间: {s}方 trigger(0.236) 与 GG 入口(0.382) 之间"
    if a < 0.618:
        return f"区间: {s}方 Golden Gate 之内 (0.382 -> 0.618)"
    if a < 1.0:
        return f"区间: {s}方 GG 已完成，向 +/-1 ATR 推进"
    return f"区间: {s}方 +/-1 ATR 之外（扩展区）"


def _mins_left(slot: str) -> int:
    return {"09:30": 390, "10:30": 330, "11:30": 270, "12:30": 210,
            "13:30": 150, "14:30": 90, "15:30": 30}.get(slot, 0)


# Locked-direction remaining-travel table (BASERATE_TIME_STRUCTURE §3.1),
# used when a target is NOT reachable through the ladder chain (no level of
# that side touched yet)  -  then the honest answer is a distance question.
def _budget_lookup(T, slot: str, dist: float, side: int) -> str:
    grid = [0.118, 0.236, 0.382, 0.5]
    if dist <= grid[0]:
        c = T["budget"][(slot, 0.118, side)]
        return f">={100*c.rate:.0f}% (查表 0.118 档, n={c.n})"
    if dist >= grid[-1]:
        c = T["budget"][(slot, 0.5, side)]
        return f"<={100*c.rate:.0f}% (查表 0.5 档, n={c.n})"
    for a, b in zip(grid, grid[1:]):
        if a <= dist <= b:
            ca = T["budget"][(slot, a, side)]
            cb = T["budget"][(slot, b, side)]
            return (f"{100*cb.rate:.0f}-{100*ca.rate:.0f}% "
                    f"(内插 {a}/{b} 档, n={ca.n})")
    return "样本不足"


def _ladder_rows(T, side: int, touched: list[float],
                 ft: dict[float, str | None], slot: str,
                 L: DayLevels, r_now: float) -> list[str]:
    rows: list[str] = []
    if not touched:
        rows.append("            该方向今日尚未触及具名位 -> 改用『距离 x 时钟』读法:")
        shown = 0
        for to in LADDER:
            price = L.at(side * to)
            dist = abs(side * to - r_now)
            if dist > 0.5 and shown >= 1:
                rows.append(f"            更远的档需走 >{dist:.2f} ATR  -  "
                            f"锁定方向查表已到底(0.5 档 "
                            f"{100*T['budget'][(slot, 0.5, side)].rate:.0f}%)，不再逐档列出")
                break
            rows.append(f"            -> {side*to:+.3f} @ {price:8.1f}  "
                        f"需走 {dist:.3f} ATR   "
                        f"{_budget_lookup(T, slot, dist, side)}")
            shown += 1
        return rows
    frm = max(touched)
    frm_slot = ft.get(frm)            # <- condition on FIRST TOUCH hour
    rows.append(f"            起点 {side*frm:+.3f} 于 {frm_slot} 首触"
                f"（条件变量是首触时段，不是当前时段）")
    for to in LADDER:
        if to <= frm + 1e-9:
            continue
        c, src = lookup_transition(T, side, frm, to, frm_slot)
        price = L.at(side * to)
        rows.append(f"            {side*frm:+.3f} -> {side*to:+.3f} @ {price:8.1f}   "
                    f"{pad(c.render(), 26)} [{src}]")
    return rows


# BASERATE_LEVEL_TRANSITIONS §E, hourly, strict reading (post-first-touch bars
# only).  Hard-coded because these are published numbers the panel must match.
PDC_UP = {0.236: (47.2, 43, 52, 494), 0.382: (34.4, 30, 39, 395),
          0.5: (26.7, 22, 32, 322), 0.618: (19.1, 15, 24, 267),
          0.786: (14.0, 10, 20, 179), 1.0: (10.5, 6, 18, 105),
          1.272: (7.8, 3, 19, 51), 1.618: (0.0, 0, 18, 18)}
PDC_DN = {0.236: (48.9, 44, 54, 411), 0.382: (33.0, 28, 38, 315),
          0.5: (26.3, 21, 32, 262), 0.618: (20.8, 16, 27, 221),
          0.786: (12.6, 8, 18, 167), 1.0: (9.1, 5, 16, 121),
          1.272: (4.0, 1, 11, 75), 1.618: (2.8, 0, 14, 36)}


def _pdc_cell(tbl: dict, lvl: float, sign: str) -> str:
    """Same tier rule as everywhere else: n<30 or CI>35pp -> 样本不足."""
    p, lo, hi, n = tbl[lvl]
    if n < TIER_B_N or (hi - lo) > 100 * TIER_B_W:
        return f"已触 {sign}{lvl:.3f} -> 回锚 样本不足 (n={n})"
    flag = "" if (n >= TIER_A_N and (hi - lo) <= 100 * TIER_A_W) else " ~宽"
    return f"已触 {sign}{lvl:.3f} -> 回锚 {p:.1f}% [{lo},{hi}] n={n}{flag}"


def _pdc_row(tu: list[float], td: list[float]) -> list[str]:
    parts = []
    if tu and max(tu) in PDC_UP:
        parts.append(_pdc_cell(PDC_UP, max(tu), "+"))
    if td and max(td) in PDC_DN:
        parts.append(_pdc_cell(PDC_DN, max(td), "-"))
    if not parts:
        return ["两侧均未触及具名位 - 无条件回锚率 64.7% [63,66] n=5016 (SPY 20y)"]
    parts[-1] += "  (多空每档 z<1.0，无方向差异)"
    return parts


# ------------------------------------------------------- premarket script ---
def premarket_script(T, day: date) -> str:
    """The if-then playbook, generated before the bell from prior-session
    information only (anchor, ATR, prev high/low).  No open price is used."""
    lv = T["lv"]
    if day not in lv:
        raise SystemExit(f"no level map for {day}")
    L = lv[day]
    out = [f"【盘前剧本 · SPX · {day}】"
           f"  锚(PDC)={L.anchor:.1f}  ATR(前日,Wilder14)={L.atr:.1f}"
           f"  前日高={L.prev_high:.1f} 前日低={L.prev_low:.1f}",
           "",
           "本剧本只陈述条件概率，不预测方向。两个分支都写出来，因为数据说方向不可预测",
           "（触发箱内先上还是先下 53.6% [48,59] n=336，z=+1.31，不显著）。",
           ""]

    for side, arrow, name in ((+1, "上破", "多"), (-1, "跌破", "空")):
        out.append(f"── 若{arrow} {side*0.236:+.3f} ATR = {L.at(side*0.236):.1f}"
                   f"（{'call' if side > 0 else 'put'} trigger）──")
        chain = [(0.236, 0.382), (0.382, 0.618), (0.618, 1.0)]
        for a, b in chain:
            for tag, slot in (("开盘即穿透", "OPEN"), ("09:30 段触发", "09:30")):
                c, src = lookup_transition(T, side, a, b, slot)
                if c.tier == "C":
                    continue
                out.append(f"   [{tag}] {side*a:+.3f} → 目标 {side*b:+.3f} "
                           f"= {L.at(side*b):.1f}   {c.render()}  [{src}]")
            c, src = lookup_transition(T, side, a, b, None)
            out.append(f"   [全时段合并] {side*a:+.3f} → {side*b:+.3f} "
                       f"= {L.at(side*b):.1f}   {c.render()}  [{src}]")
        # ceiling
        c1, s1 = lookup_transition(T, side, 1.0, 1.272, None)
        out.append(f"   [尾部] {side*1.0:+.3f} → {side*1.272:+.3f} "
                   f"= {L.at(side*1.272):.1f}   {c1.render()}  [{s1}]")
        if side > 0:
            out.append("   ⇒ 多头尾部目标最远挂到 +1.0 ATR："
                       "1.0→1.272 = 50.7% [47,54] n=739 (20y 日线, z=+0.40, 抛硬币)")
        else:
            out.append("   ⇒ 空头尾部可挂到 −1.272："
                       "1.0→1.272 = 60.3% [57,64] n=834 (20y 日线, z=+5.96)")
            out.append("     ⚠ 这不是做空理由 —— §I(d) 证明它是波动率聚集+滞后 ATR 的产物")
        out.append("")

    out += [
        "── 无论哪个分支都成立的三条 ──",
        f"   · 若开盘即在 ±0.236 之外：2017 年后 45.8% 的交易日如此，"
        f"『等触发位』这句话当场过期",
        f"   · 10:30 检查点：首小时未过 0.236 → 当日触及 ±1ATR 仅 5.8% [2.7,12.0] "
        f"n=104（基线 29.5%）→ 关闭 ≥0.382 目标",
        f"   · 14:30 之后不再开需要 0.236 ATR 行程的新仓："
        f"即使事后选对方向也只有 49.7% [46,53] n=722",
        "",
        "── 本剧本明确不说的 ──",
        "   · 不说今天偏多或偏空（所有方向格子 |z| 均 <2.3，低于家族阈值）",
        "   · 不说『GG 触发所以做多』（盘中触发的 GG 是轻微均值回归的，McNemar z=−4.62）",
        "   · 不给入场价与止损价（入场层尚未被任何研究证实存在）",
    ]
    return "\n".join(out)


# ------------------------------------------------------------------ main ---
def dump_coverage(T) -> None:
    """The table the spec quotes: which (from,to,hour) cells are servable."""
    print("\n=== 转移格子的可服务性（小时线 730d，按首触时段）===")
    print("行=起始档，列=时段；A=可直接显示，B=显示但标宽区间，C=必须显示『样本不足』")
    for side, lab in ((+1, "多头"), (-1, "空头")):
        print(f"\n--- {lab} · 目标=下一档 ---")
        hdr = "  from  " + "".join(f"{h:>10}" for h in HOURS)
        print(hdr)
        for i, a in enumerate(LADDER[:-1]):
            b = LADDER[i + 1]
            cells = []
            for hslot in HOURS:
                c = T["t_hour"].get((side, a, b, hslot))
                if c is None:
                    cells.append(f"{'-':>10}")
                else:
                    cells.append(f"{c.tier}:{c.n:<3}".rjust(10))
            print(f"  {a:<6}" + "".join(cells))

    print("\n=== 全族规模 ===")
    print(f"  小时线时段格 : {len(T['t_hour'])}")
    print(f"  小时线合并格 : {len(T['t_all'])}")
    print(f"  20y 日线格   : {len(T['t_daily'])}")
    print(f"  预算格       : {len(T['budget']) + len(T['best']) + len(T['dead'])}")
    tot = (len(T["t_hour"]) + len(T["t_all"]) + len(T["t_daily"])
           + len(T["budget"]) + len(T["best"]) + len(T["dead"]))
    print(f"  合计         : {tot}  ← 面板只是这些格子的查表器，没有新增统计量")
    ntA = sum(1 for c in T["t_hour"].values() if c.tier == "A")
    ntB = sum(1 for c in T["t_hour"].values() if c.tier == "B")
    ntC = sum(1 for c in T["t_hour"].values() if c.tier == "C")
    print(f"  时段格分级   : A={ntA}  B={ntB}  C={ntC}"
          f"  → {100*ntC/(ntA+ntB+ntC):.0f}% 的时段格必须显示『样本不足』")


def dump_budget(T) -> None:
    print("\n=== 时钟表（面板第②行的数据源）===")
    print(f"  {'时刻':<8}{'剩余分':>7}{'最优边≥0.236':>26}{'锁定多≥0.236':>26}"
          f"{'P(今日已走完)':>26}")
    for hslot in HOURS[1:]:
        b = T["best"][(hslot, 0.236)]
        u = T["budget"][(hslot, 0.236, +1)]
        d = T["dead"][hslot]
        print(f"  {hslot:<8}{_mins_left(hslot):>7}{b.render():>26}"
              f"{u.render():>26}{d.render():>26}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--at", default="11:30")
    ap.add_argument("--tables", action="store_true")
    ap.add_argument("--script", action="store_true")
    a = ap.parse_args()

    T = build_tables()
    print(f"clean sessions: {len(T['sessions'])}  "
          f"({T['sessions'][0][0]} → {T['sessions'][-1][0]})")
    if a.tables:
        dump_coverage(T)
        dump_budget(T)

    day = (datetime.strptime(a.day, "%Y-%m-%d").date() if a.day
           else T["sessions"][-1][0])
    if a.script:
        print()
        print(premarket_script(T, day))
    print()
    print(render_panel(T, day, a.at))


if __name__ == "__main__":
    main()
