#!/usr/bin/env python3
"""Adversarial audit, part 4 — cross-report contradictions and the geometry
report's own numbers.

Run:  .venv/bin/python research/satylab/audit_adversarial4.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats  # noqa: E402

LINE = "=" * 78


def hdr(t: str) -> None:
    print(f"\n{LINE}\n{t}\n{LINE}")


def d1_gapthrough_contradiction() -> None:
    hdr("D1  『45.8% 的日子开盘已跳穿 ±0.236』—— 但它是用被证明失真的 "
        "^GSPC 开盘价算的")
    for sym in ("^GSPC", "SPY"):
        d = data.daily(sym, years="20y")
        lv = levels.build(d)
        n = up = dn = 0
        for b in d:
            L = lv.get(b.day)
            if L is None or b.day.year < 2017:
                continue
            n += 1
            r = L.ratio_of(b.open)
            if r >= 0.236:
                up += 1
            elif r <= -0.236:
                dn += 1
        g = up + dn
        print(f"  {sym:<7} 2017+ n={n}  跳穿 ±0.236 = {g} "
              f"({100*g/n:.1f}%)  其中向上 {stats.fmt_rate(up, g)}")
    print("\n  ⇒ BASERATE_LEVEL_TRANSITIONS 的头条『45.8%』用的是 ^GSPC，")
    print("     而 BASERATE_OPENING_TYPE 已经证明 ^GSPC 的开盘价被压缩约 22%。")
    print("     两份报告在同一个周末互相否定了对方的输入。")


def d2_gg_completion_by_source() -> None:
    hdr("D2  GG 完成率在 ^GSPC 与 SPY 上是同一个数吗（20y 日线，同口径）")
    for sym in ("^GSPC", "SPY"):
        d = data.daily(sym, years="20y")
        lv = levels.build(d)
        for side, name in ((+1, "多"), (-1, "空")):
            k = n = 0
            for b in d:
                L = lv.get(b.day)
                if L is None:
                    continue
                pf_ = L.at(side * 0.382)
                pt = L.at(side * 0.618)
                got = (b.high >= pf_) if side > 0 else (b.low <= pf_)
                if not got:
                    continue
                n += 1
                k += int((b.high >= pt) if side > 0 else (b.low <= pt))
            print(f"  {sym:<7} {name} 0.382→0.618  {stats.fmt_rate(k, n)}")


def d3_geometry_numbers() -> None:
    hdr("D3  GEOMETRY_MFE_MAE 的两条核心数字复核")
    d = data.daily(years="20y")
    lv = levels.build(d)
    fs = data.group_by_day(data.fine())
    # (1) drift after first touch of a named level, to close
    drifts = []
    mfe, mae = [], []
    for day in sorted(fs):
        if day not in lv:
            continue
        rows, L = fs[day], lv[day]
        for side in (+1, -1):
            for r in (0.236, 0.382, 0.5, 0.618):
                p = L.at(side * r)
                ti = next((i for i, b in enumerate(rows)
                           if ((b.high >= p) if side > 0 else (b.low <= p))),
                          None)
                if ti is None or ti >= len(rows) - 1:
                    continue
                entry = rows[ti].close
                rest = rows[ti + 1:]
                drifts.append((rows[-1].close - entry) * side / L.atr)
                hi = max(b.high for b in rest)
                lo = min(b.low for b in rest)
                mfe.append(((hi - entry) if side > 0 else (entry - lo)) / L.atr)
                mae.append(((entry - lo) if side > 0 else (hi - entry)) / L.atr)
    n = len(drifts)
    m = sum(drifts) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in drifts) / (n - 1))
    print(f"  5m 首触后到收盘的漂移: n={n} 均值={m:+.4f} ATR "
          f"SE={sd/math.sqrt(n):.4f} t={m/(sd/math.sqrt(n)):+.2f}")
    dm = sum(mfe) / n - sum(mae) / n
    sdiff = [a - b for a, b in zip(mfe, mae)]
    sds = math.sqrt(sum((x - dm) ** 2 for x in sdiff) / (n - 1))
    print(f"  E[MFE]-E[MAE] = {dm:+.4f} ATR  SE={sds/math.sqrt(n):.4f} "
          f"t={dm/(sds/math.sqrt(n)):+.2f}")
    mfe.sort()
    mae.sort()
    print(f"  MFE 中位 {mfe[n//2]:.3f} ATR   MAE 中位 {mae[n//2]:.3f} ATR "
          f"(报告的『噪声尺度 0.26–0.32 ATR』)")
    # (2) the accounting artefact: entry at level price vs entry at bar close
    gap = []
    for day in sorted(fs):
        if day not in lv:
            continue
        rows, L = fs[day], lv[day]
        for side in (+1, -1):
            p = L.at(side * 0.236)
            ti = next((i for i, b in enumerate(rows)
                       if ((b.high >= p) if side > 0 else (b.low <= p))), None)
            if ti is None:
                continue
            gap.append((rows[ti].close - p) * side / L.atr)
    g = sum(gap) / len(gap)
    print(f"  记账差（首触根收盘 − 位价，延续方向）: n={len(gap)} "
          f"均值={g:+.4f} ATR = {g/0.05:.2f} 个 0.05ATR 止损宽度")
    print("  ⇒ 复现报告 §1 的『口径就是结论』：把入场价记成位价就是白送这一段。")


def d4_regression_to_pdc() -> None:
    hdr("D4  『触及 0.236 后回 PDC = 47.2%』是不是也含同根 K 污染")
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    days = sorted(k for k in sess if k in lv and len(sess[k]) == 7)
    for start in (0, 1):
        out = defaultdict(lambda: [0, 0])
        for day in days:
            rows, L = sess[day], lv[day]
            for side, nm in ((+1, "多"), (-1, "空")):
                for r in (0.236, 0.618, 1.0):
                    p = L.at(side * r)
                    ti = next((i for i, b in enumerate(rows)
                               if ((b.high >= p) if side > 0
                                   else (b.low <= p))), None)
                    if ti is None:
                        continue
                    back = any((b.low <= L.anchor) if side > 0
                               else (b.high >= L.anchor)
                               for b in rows[ti + start:])
                    c = out[(nm, r)]
                    c[0] += back
                    c[1] += 1
        lab = "含首触根" if start == 0 else "剔除首触根"
        print(f"  {lab}:")
        for k in sorted(out, key=lambda x: (x[0], x[1])):
            print(f"    {k[0]} 触及 {k[1]:.3f} 后回 PDC  "
                  f"{stats.fmt_rate(*out[k])}")


def main() -> None:
    print(f"ADVERSARIAL AUDIT part 4  —  {datetime.now():%Y-%m-%d %H:%M}")
    d1_gapthrough_contradiction()
    d2_gg_completion_by_source()
    d3_geometry_numbers()
    d4_regression_to_pdc()


if __name__ == "__main__":
    main()
