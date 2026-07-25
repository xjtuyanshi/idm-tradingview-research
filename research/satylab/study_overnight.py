#!/usr/bin/env python3
"""Overnight / pre-market levels — the biggest gap in our level map.

The Discord corpus (docs/SATY_PLAYBOOK_CORPUS.md) shows Saty referencing
"pre-market support", "pre-market highs", "overnight lows" and "H21 (RTH)" in
almost every script, and our engine has none of them.  This study measures
whether those levels carry base rates worth putting on the chart.

Data: ES futures, which trade nearly 24h and are what the CAPITALCOM:SPX500
CFD tracks overnight.  SPX cash (^GSPC) has no overnight session at all, so
these questions are simply unanswerable on the data every other study uses.

Sessions (ET), following the CME equity-index calendar:
    overnight  18:00 (prev) -> 09:30
    pre-market 04:00        -> 09:30      (the window equity traders quote)
    RTH        09:30        -> 16:00

Usage: python research/satylab/study_overnight.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402

RTH_START, RTH_END = "09:30", "16:00"
PM_START = "04:00"


def session_split(bars: list[Bar]) -> dict[date, dict]:
    """Bucket 24h bars into overnight / pre-market / RTH by trading day."""
    by_day: dict[date, list[Bar]] = defaultdict(list)
    for b in bars:
        by_day[b.day].append(b)

    out: dict[date, dict] = {}
    days = sorted(by_day)
    for i, d in enumerate(days):
        rows = sorted(by_day[d], key=lambda x: x.dt)
        rth = [b for b in rows if RTH_START <= b.hhmm < RTH_END]
        pm = [b for b in rows if PM_START <= b.hhmm < RTH_START]
        # overnight = this day's pre-open bars plus the prior day's post-close
        prev_evening: list[Bar] = []
        if i > 0:
            prev_evening = [b for b in sorted(by_day[days[i - 1]],
                                              key=lambda x: x.dt)
                            if b.hhmm >= "18:00"]
        overnight = prev_evening + [b for b in rows if b.hhmm < RTH_START]
        if len(rth) < 5 or not overnight:
            continue
        out[d] = {"rth": rth, "pm": pm, "on": overnight,
                  "prev_day": days[i - 1] if i > 0 else None}
    return out


def rng(bars: list[Bar]) -> tuple[float, float]:
    return max(b.high for b in bars), min(b.low for b in bars)


def main() -> None:
    print("ES futures — overnight / pre-market level study\n")
    daily = data.daily("ES=F", years="20y")
    hourly = data.load("ES=F", "730d", "1h")
    lv = levels.build(daily)
    sess = session_split(hourly)
    print(f"sessions with full 24h coverage: {len(sess)} "
          f"({min(sess)} -> {max(sess)})\n")

    sweep = stats.RateTable("1. RTH 是否扫掉夜盘区间")
    first_side = stats.RateTable("2. 先扫哪一边 -> 当日收盘方向是否同向")
    pm_hold = stats.RateTable("3. Saty 剧本：守住盘前低 + 上破盘前高 -> 后续")
    on_size = stats.RateTable("4. 夜盘区间大小(ATR) -> RTH 是否触及 ±1 ATR")
    gg_link = stats.RateTable("5. 夜盘已进 GG -> RTH 完成 GG")

    rows = []
    for d in sorted(sess):
        s = sess[d]
        L = lv.get(d)
        if not L:
            continue
        onh, onl = rng(s["on"])
        rth = s["rth"]
        rh, rl = rng(rth)
        first, last = rth[0], rth[-1]

        took_high = rh > onh
        took_low = rl < onl
        sweep.add("扫上沿 ONH", took_high)
        sweep.add("扫下沿 ONL", took_low)
        sweep.add("两边都扫", took_high and took_low)
        sweep.add("两边都没扫(困在夜盘区间内)", not took_high and not took_low)

        # which side was taken first, and did the day close that way?
        if took_high or took_low:
            i_hi = levels.first_touch(rth, onh, +1)
            i_lo = levels.first_touch(rth, onl, -1)
            if i_hi is not None and (i_lo is None or i_hi < i_lo):
                first_side.add("先破夜盘高 -> 收阳", last.close > first.open)
            elif i_lo is not None:
                first_side.add("先破夜盘低 -> 收阴", last.close < first.open)

        # Saty's exact script: hold pre-market support, break pre-market highs
        if s["pm"]:
            pmh, pml = rng(s["pm"])
            broke_pmh = levels.first_touch(rth, pmh, +1)
            if broke_pmh is not None:
                after = rth[broke_pmh:]
                held = min(b.low for b in rth[:broke_pmh + 1]) > pml
                if held:
                    # continuation target: the next named level above
                    r_now = L.ratio_of(pmh)
                    nxt = next((r for r in levels.RATIOS if r > r_now + 1e-9),
                               None)
                    if nxt is not None:
                        hit = any(b.high >= L.at(nxt) for b in after)
                        pm_hold.add(f"守盘前低+破盘前高 -> 触及上一位", hit)
                else:
                    r_now = L.ratio_of(pmh)
                    nxt = next((r for r in levels.RATIOS if r > r_now + 1e-9),
                               None)
                    if nxt is not None:
                        hit = any(b.high >= L.at(nxt) for b in after)
                        pm_hold.add(f"未守盘前低就破盘前高 -> 触及上一位", hit)

        on_ratio = (onh - onl) / L.atr
        bucket = ("夜盘窄 <0.4ATR" if on_ratio < 0.4 else
                  "夜盘中 0.4-0.8" if on_ratio < 0.8 else "夜盘宽 >0.8ATR")
        on_size.add(bucket, rh >= L.at(1.0) or rl <= L.at(-1.0))

        on_in_gg = onh >= L.at(levels.GG_ENTRY)
        if on_in_gg:
            gg_link.add("夜盘已到 0.382 上方", rh >= L.at(levels.GG_COMPLETE))
        elif onh >= L.at(levels.TRIGGER):
            gg_link.add("夜盘只到 0.236", rh >= L.at(levels.GG_COMPLETE))
        else:
            gg_link.add("夜盘未过 0.236", rh >= L.at(levels.GG_COMPLETE))

        rows.append({"day": d, "on_ratio": on_ratio, "took_high": took_high,
                     "took_low": took_low})

    for t in (sweep, first_side, pm_hold, on_size, gg_link):
        print(t.render())
        print()

    # does holding pre-market support do any work, statistically?
    a = pm_hold.cells.get("守盘前低+破盘前高 -> 触及上一位")
    b = pm_hold.cells.get("未守盘前低就破盘前高 -> 触及上一位")
    if a and b:
        z = stats.two_proportion_z(a.k, a.n, b.k, b.n)
        verdict = "有做功" if abs(z) >= 1.96 else "**没有做功**"
        print(f"两比例检验（Saty 的『守住盘前支撑』条件）: z={z:+.2f} -> {verdict}")

    print(f"\n夜盘区间/ATR 的分布: "
          f"中位 {sorted(r['on_ratio'] for r in rows)[len(rows)//2]:.2f}")


if __name__ == "__main__":
    main()
