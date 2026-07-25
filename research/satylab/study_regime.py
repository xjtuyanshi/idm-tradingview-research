#!/usr/bin/env python3
"""Is "hard mode" measurable?

Saty, Friday 2026-07-24 11:50 ET:  "Last two weeks have been on hard mode.
Once this daily box resolves, should get a little easier."
Weekly note the same afternoon: "We are still in the monthly trigger box
roughly between 7400 and 7600."

Those two weeks are exactly when our forward test took two full stops and the
user said the system was getting worse.  If sitting inside the higher-timeframe
trigger box is a real regime, then intraday continuation should measurably
fail there — and we would have a filter that says "today is not a trading day"
instead of discovering it one loss at a time.

This is a pre-registered test of ONE hypothesis with ONE conditioner.  The
outcome variables are the same ones used in every other study in this lab, so
there is no room to shop for a flattering pairing.

Usage: python research/satylab/study_regime.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.mtf_levels import build_mtf, regime_label  # noqa: E402

RATIO_TRIGGER = levels.TRIGGER
RATIO_GG_IN = levels.GG_ENTRY
RATIO_GG_OUT = levels.GG_COMPLETE


def main() -> None:
    daily = data.daily("^GSPC", years="20y")
    lv = levels.build(daily)
    monthly = build_mtf(daily, "M")
    weekly = build_mtf(daily, "W")
    print(f"日线样本 {len(daily)} 根 ({daily[0].day} -> {daily[-1].day})")
    print(f"月线位图覆盖 {len(monthly)} 天，周线位图覆盖 {len(weekly)} 天\n")

    tables = {
        "gg_trigger": stats.RateTable("① 当日是否触发 GG（±0.382 日ATR）"),
        "gg_done": stats.RateTable("② 触发后是否完成 GG（±0.618）"),
        "full_atr": stats.RateTable("③ 当日是否触及 ±1.0 日ATR"),
        "trend_day": stats.RateTable("④ 是否趋势日（收盘落在当日区间外侧 25%）"),
        "inside": stats.RateTable("⑤ 是否内包日（当日区间窄于 0.5 日ATR）"),
    }

    for i in range(1, len(daily)):
        b = daily[i]
        L = lv.get(b.day)
        m = monthly.get(b.day)
        if not L or not m:
            continue
        # regime is decided by where the PRIOR close sat — known before the open
        reg = regime_label(daily[i - 1].close, m)

        up_trig = b.high >= L.at(RATIO_GG_IN)
        dn_trig = b.low <= L.at(-RATIO_GG_IN)
        tables["gg_trigger"].add(reg, up_trig or dn_trig)
        if up_trig or dn_trig:
            done = ((b.high >= L.at(RATIO_GG_OUT)) if up_trig else False) or \
                   ((b.low <= L.at(-RATIO_GG_OUT)) if dn_trig else False)
            tables["gg_done"].add(reg, done)
        tables["full_atr"].add(reg,
                               b.high >= L.at(1.0) or b.low <= L.at(-1.0))
        rng = b.high - b.low
        if rng > 0:
            pos = (b.close - b.low) / rng
            tables["trend_day"].add(reg, pos > 0.75 or pos < 0.25)
        tables["inside"].add(reg, rng < 0.5 * L.atr)

    order = ["trigger_box", "gg_zone", "extended", "beyond_1atr"]
    for t in tables.values():
        print(t.render(order=order))
        print()

    print("=" * 72)
    print("两比例检验：trigger_box vs 其余全部（这是本研究唯一的假设）")
    print("=" * 72)
    for name, t in tables.items():
        box = t.cells.get("trigger_box")
        rest_k = sum(c.k for k, c in t.cells.items() if k != "trigger_box")
        rest_n = sum(c.n for k, c in t.cells.items() if k != "trigger_box")
        if not box or rest_n == 0:
            continue
        z = stats.two_proportion_z(box.k, box.n, rest_k, rest_n)
        mark = "**显著**" if abs(z) >= 1.96 else "不显著"
        print(f"  {name:<12} 箱内={100*box.rate:5.1f}% (n={box.n:<5}) "
              f"箱外={100*rest_k/rest_n:5.1f}% (n={rest_n:<5}) "
              f"z={z:+6.2f}  {mark}")

    # how much of the time are we in the box at all?
    total = sum(c.n for c in tables["gg_trigger"].cells.values())
    inbox = tables["gg_trigger"].cells.get("trigger_box")
    if inbox:
        print(f"\n  月线触发箱内的交易日占比: "
              f"{stats.fmt_rate(inbox.n, total)}")

    print("\n" + "=" * 72)
    print("同样的检验，换成周线触发箱（独立复核，不是第二次择优）")
    print("=" * 72)
    wt = stats.RateTable("周线箱：当日是否触及 ±1.0 日ATR")
    for i in range(1, len(daily)):
        b = daily[i]
        L, w = lv.get(b.day), weekly.get(b.day)
        if not L or not w:
            continue
        wt.add(regime_label(daily[i - 1].close, w),
               b.high >= L.at(1.0) or b.low <= L.at(-1.0))
    box = wt.cells.get("trigger_box")
    rest_k = sum(c.k for k, c in wt.cells.items() if k != "trigger_box")
    rest_n = sum(c.n for k, c in wt.cells.items() if k != "trigger_box")
    if box and rest_n:
        z = stats.two_proportion_z(box.k, box.n, rest_k, rest_n)
        print(f"  箱内={stats.fmt_rate(box.k, box.n)}")
        print(f"  箱外={stats.fmt_rate(rest_k, rest_n)}")
        print(f"  z={z:+.2f}")

    # the specific window Saty called hard mode
    print("\n" + "=" * 72)
    print("Saty 所说的『过去两周』(2026-07-10 ~ 07-24) 实况")
    print("=" * 72)
    recent = [b for b in daily if b.day.isoformat() >= "2026-07-10"]
    for b in recent:
        L, m = lv.get(b.day), monthly.get(b.day)
        if not L or not m:
            continue
        rng_atr = (b.high - b.low) / L.atr
        print(f"  {b.day}  月线位置 {m.ratio_of(b.close):+.3f} "
              f"({regime_label(b.close, m):<12}) 当日振幅 {rng_atr:.2f} 日ATR"
              f"{'  ← 内包日' if rng_atr < 0.5 else ''}")


if __name__ == "__main__":
    main()
