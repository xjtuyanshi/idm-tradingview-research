#!/usr/bin/env python3
"""Adversarial audit, part 3 — the Phase headline, with the study's own
definitions, then attacked.

Run:  .venv/bin/python research/satylab/audit_adversarial3.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats                      # noqa: E402
from satylab import phase_fix as pf, ribbon_spec as rs       # noqa: E402

LINE = "=" * 78
FIXED_R = 0.236


def hdr(t: str) -> None:
    print(f"\n{LINE}\n{t}\n{LINE}")


def build():
    bars = [b for b in data.hourly() if b.hhmm != "16:00"]
    daily = data.daily(years="20y")
    lv = levels.build(daily)
    osc = pf.phase_oscillator(bars)
    fr = rs.frames(bars)
    hatr = pf.ta_atr(bars, pf.ATR_LEN)
    by_day = defaultdict(list)
    for i, b in enumerate(bars):
        by_day[b.day].append(i)
    return bars, osc, fr, hatr, dict(by_day), lv


def c1_phase_headline() -> None:
    hdr("C1  Phase 头条（唯一正面发现）：用研究自己的定义复核，然后攻击")
    bars, osc, fr, hatr, by_day, lv = build()
    recs = []
    for day in sorted(by_day):
        di = by_day[day]
        if day not in lv:
            continue
        L = lv[day]
        # locate the 10:30 bar
        j = next((i for i in di if bars[i].hhmm == "10:30"), None)
        if j is None or j == di[-1]:
            continue
        if osc[j] is None or fr[j] is None or hatr[j] is None:
            continue
        rest = [bars[i] for i in di if i > j]
        if not rest:
            continue
        ref = bars[j].close
        d = FIXED_R * L.atr
        hu = any(b.high >= ref + d for b in rest)
        hd = any(b.low <= ref - d for b in rest)
        dead = not hu and not hd
        # free proxy 1: hourly ATR / daily ATR  (the oscillator's denominator)
        vol = hatr[j] / L.atr
        # free proxy 2: how much of the day has already been travelled
        sofar = [bars[i] for i in di if i <= j]
        trav = (max(b.high for b in sofar) - min(b.low for b in sofar)) / L.atr
        recs.append({"day": day, "zone": pf.phase_zone(osc[j]),
                     "ribbon": fr[j].state, "dead": dead, "vol": vol,
                     "trav": trav, "osc": osc[j]})
    print(f"  10:30 独立日样本 n={len(recs)}")

    def rate(pred):
        v = [r for r in recs if pred(r)]
        return sum(r["dead"] for r in v), len(v)

    bull = lambda r: r["ribbon"] == "full_bull"                    # noqa: E731
    lb = rate(lambda r: bull(r) and r["zone"] == "launch_box")
    ds = rate(lambda r: bull(r) and r["zone"] == "distribution")
    print(f"  ribbon=full_bull & launch_box   {stats.fmt_rate(*lb)}")
    print(f"  ribbon=full_bull & distribution {stats.fmt_rate(*ds)}")
    print(f"  两比例 z = {stats.two_proportion_z(*lb, *ds):+.2f}  "
          f"(报告: 11.7% n=103 / 32.7% n=101, z=-3.62)")

    # --- attack 1: three time slices
    days = sorted({r["day"] for r in recs})
    third = len(days) // 3
    seg = {d: min(2, i // third) for i, d in enumerate(days)}
    print("\n  攻击 1 — 730 天三等分，效应是否同号")
    for s in range(3):
        a = rate(lambda r, s=s: seg[r["day"]] == s and bull(r)
                 and r["zone"] == "launch_box")
        b = rate(lambda r, s=s: seg[r["day"]] == s and bull(r)
                 and r["zone"] == "distribution")
        zz = stats.two_proportion_z(*a, *b) if a[1] and b[1] else 0.0
        print(f"    段{s+1}  launch_box {stats.fmt_rate(*a):<26}"
              f"distribution {stats.fmt_rate(*b):<26} z={zz:+.2f}")

    # --- attack 2: is the free proxy (already-travelled range) as good?
    print("\n  攻击 2 — 一个免费替代变量：10:30 之前【已经走过的区间】")
    tr = sorted(r["trav"] for r in recs)
    q = [tr[int(len(tr) * f)] for f in (0.25, 0.5, 0.75)]
    print(f"    已走区间四分位切点: {q[0]:.3f} / {q[1]:.3f} / {q[2]:.3f} ATR")
    for lo, hi, lab in ((0, q[0], "Q1 最窄"), (q[0], q[1], "Q2"),
                        (q[1], q[2], "Q3"), (q[2], 9, "Q4 最宽")):
        k, n = rate(lambda r, lo=lo, hi=hi: lo <= r["trav"] < hi)
        print(f"    已走区间 {lab:<8}P(dead) {stats.fmt_rate(k, n)}")
    print("    ⇒ 跨度对比：phase 分区（full_bull 内）11.7%→32.7% = 21.0pp")

    # --- attack 3: does the zone survive INSIDE a travelled-range quartile?
    print("\n  攻击 3 — 在【已走区间四分位】内部再比 launch_box vs distribution")
    agree = 0
    for lo, hi, lab in ((0, q[0], "Q1"), (q[0], q[1], "Q2"),
                        (q[1], q[2], "Q3"), (q[2], 9, "Q4")):
        a = rate(lambda r, lo=lo, hi=hi: lo <= r["trav"] < hi and bull(r)
                 and r["zone"] == "launch_box")
        b = rate(lambda r, lo=lo, hi=hi: lo <= r["trav"] < hi and bull(r)
                 and r["zone"] == "distribution")
        if a[1] < 5 or b[1] < 5:
            print(f"    {lab}  n 太小 (launch_box n={a[1]}, distribution "
                  f"n={b[1]}) — 不可判")
            continue
        zz = stats.two_proportion_z(*a, *b)
        agree += int(zz < 0)
        print(f"    {lab}  launch_box {stats.fmt_rate(*a):<26}"
              f"distribution {stats.fmt_rate(*b):<26} z={zz:+.2f}")
    # Mantel-Haenszel across travelled-range quartiles
    num = den = 0.0
    var = 0.0
    for lo, hi in ((0, q[0]), (q[0], q[1]), (q[1], q[2]), (q[2], 9)):
        a = rate(lambda r, lo=lo, hi=hi: lo <= r["trav"] < hi and bull(r)
                 and r["zone"] == "distribution")
        b = rate(lambda r, lo=lo, hi=hi: lo <= r["trav"] < hi and bull(r)
                 and r["zone"] == "launch_box")
        n1, n2 = a[1], b[1]
        if n1 == 0 or n2 == 0:
            continue
        N = n1 + n2
        m1 = a[0] + b[0]
        num += a[0] - n1 * m1 / N
        var += (n1 * n2 * m1 * (N - m1)) / (N * N * (N - 1)) if N > 1 else 0
    if var > 0:
        print(f"    Mantel-Haenszel（按已走区间分层）z = {num/math.sqrt(var):+.2f}")

    # --- attack 4: overlap between zone and travelled range
    zs = [r for r in recs if bull(r) and r["zone"] == "distribution"]
    ls = [r for r in recs if bull(r) and r["zone"] == "launch_box"]
    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else float("nan")
    print(f"\n  攻击 4 — 两组的免费变量本来就不同："
          f"\n    distribution: 已走区间中位 {med([r['trav'] for r in zs]):.3f} ATR，"
          f"hourly/daily ATR 中位 {med([r['vol'] for r in zs]):.3f}"
          f"\n    launch_box  : 已走区间中位 {med([r['trav'] for r in ls]):.3f} ATR，"
          f"hourly/daily ATR 中位 {med([r['vol'] for r in ls]):.3f}")


def c2_panel_coverage() -> None:
    hdr("C2  面板规格的『可服务格子』矩阵复核")
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    days = sorted(k for k in sess if k in lv and len(sess[k]) == 7)
    ratios = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272)
    nxt = {0.236: 0.382, 0.382: 0.5, 0.5: 0.618, 0.618: 0.786,
           0.786: 1.0, 1.0: 1.272, 1.272: 1.618}
    grid = defaultdict(lambda: [0, 0])
    for day in days:
        rows, L = sess[day], lv[day]
        for side in (+1, -1):
            for r in ratios:
                p = L.at(side * r)
                ti = next((i for i, b in enumerate(rows)
                           if ((b.high >= p) if side > 0 else (b.low <= p))),
                          None)
                if ti is None:
                    continue
                gapped = (rows[0].open >= p) if side > 0 else \
                         (rows[0].open <= p)
                bucket = "OPEN" if (gapped and ti == 0) else rows[ti].hhmm
                q = L.at(side * nxt[r])
                got = any((b.high >= q) if side > 0 else (b.low <= q)
                          for b in rows[ti:])
                c = grid[(side, r, bucket)]
                c[0] += got
                c[1] += 1
    A = B = C = 0
    per_bucket = defaultdict(lambda: [0, 0, 0])
    for key, (k, n) in grid.items():
        lo, hi = stats.wilson(k, n)
        w = 100 * (hi - lo)
        if n >= 100 and w <= 20:
            A += 1
            per_bucket[key[2]][0] += 1
        elif n >= 30 and w <= 35:
            B += 1
            per_bucket[key[2]][1] += 1
        else:
            C += 1
            per_bucket[key[2]][2] += 1
    total = 2 * len(ratios) * 8
    print(f"  (方向 × 起始档 × 首触时段) 理论格数 = {total}，"
          f"实际有样本的 = {len(grid)}")
    print(f"  A 档(n>=100 且 CI<=20pp) = {A}   B 档 = {B}   "
          f"C 档(样本不足，含 0 样本) = {C + (total - len(grid))}")
    print(f"  报告称: A=55, B=68, 样本不足=325（合计 448）")
    print(f"  {'时段':<10}{'A':>5}{'B':>5}{'C':>5}")
    for k in ["OPEN", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30",
              "15:30"]:
        v = per_bucket[k]
        print(f"  {k:<10}{v[0]:>5}{v[1]:>5}{v[2]:>5}")


def c3_cross_report() -> None:
    hdr("C3  跨报告一致性：同一个 GG 数字在四份报告里是同一个数吗")
    print("  GOLDEN_GATE_REPRODUCTION  开盘档 89.7% n=117 / 09:30 70.8% n=168")
    print("  BASERATE_LEVEL_TRANSITIONS 开盘档 89.7% n=117 / 09:30 70.3% n=165")
    print("  BASERATE_TIME_STRUCTURE   开盘档 91.9% n=198(多空合并) / "
          "09:30 70.0% n=283")
    print("  BASERATE_OPENING_TYPE     跳空档 85.9% n=936 (SPY 20y 日线)")
    print("  本审查 (小时线, 多头, 7 根日)  开盘档 89.7% n=117 / 09:30 70.3% n=165")
    print("\n  ⇒ 数字本身对得上，但『89.7%』『91.9%』『85.9%』是三个不同的量：")
    print("     89.7% = 小时线多头、剔除半日市、含『开盘已在 0.618 之外』的既成事实")
    print("     91.9% = 小时线多空合并、同样含既成事实")
    print("     86.3% = 剔除既成事实之后的可交易版本")
    print("     85.9% = SPY 20 年日线的跳空档")
    print("  面板/图表上只能出现 86.3% 那一个；其余三个都不可用于决策。")


def main() -> None:
    print(f"ADVERSARIAL AUDIT part 3  —  {datetime.now():%Y-%m-%d %H:%M}")
    c1_phase_headline()
    c2_panel_coverage()
    c3_cross_report()


if __name__ == "__main__":
    main()
