#!/usr/bin/env python3
"""Adversarial audit, part 5 — the placebo-ladder test.

The whole weekend rests on one premise: that Saty's NAMED ratios
(0.236 / 0.382 / 0.5 / 0.618 / 0.786 / 1.0) are special.  If the transition
probabilities lie on a smooth curve with no bump at the named ratios, then the
"named level map" is a re-parameterisation of distance and nothing else.

Run:  .venv/bin/python research/satylab/audit_adversarial5.py
"""

from __future__ import annotations

import math
import sys
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats  # noqa: E402

LINE = "=" * 78
NAMED = {0.236, 0.382, 0.5, 0.618, 0.786, 1.0}


def hdr(t: str) -> None:
    print(f"\n{LINE}\n{t}\n{LINE}")


def transition(d, lv, start: float, dist: float, side: int) -> tuple[int, int]:
    k = n = 0
    for b in d:
        L = lv.get(b.day)
        if L is None:
            continue
        p0 = L.at(side * start)
        p1 = L.at(side * (start + dist))
        got = (b.high >= p0) if side > 0 else (b.low <= p0)
        if not got:
            continue
        n += 1
        k += int((b.high >= p1) if side > 0 else (b.low <= p1))
    return k, n


def e1_placebo_ladder() -> None:
    hdr("E1  安慰剂梯子：把起点在 0.20–0.70 之间连续滑动，"
        "具名比例上有没有『台阶』")
    d = data.daily(years="20y")
    lv = levels.build(d)
    print("  固定推进距离 = 0.236 ATR（= GG 的门到门距离）")
    print(f"  {'起点':>7}{'具名?':>7}{'多头 P(到达)':>26}"
          f"{'空头 P(到达)':>26}")
    xs, ys = [], []
    grid = sorted({round(0.20 + 0.025 * i, 3) for i in range(21)}
                  | {0.236, 0.382, 0.5, 0.618})
    for s in grid:
        ku, nu = transition(d, lv, s, 0.236, +1)
        kd, nd = transition(d, lv, s, 0.236, -1)
        tag = "★具名" if any(abs(s - x) < 1e-6 for x in NAMED) else ""
        print(f"  {s:>7.3f}{tag:>7}{stats.fmt_rate(ku, nu):>26}"
              f"{stats.fmt_rate(kd, nd):>26}")
        xs.append(s)
        ys.append(ku / nu)
    # residual from a local linear fit: do the named ratios sit above trend?
    print("\n  局部趋势残差（多头）：把 P 对起点做二次拟合，看具名点是否高于拟合线")
    n = len(xs)
    # quadratic least squares
    A = [[sum(x ** (i + j) for x in xs) for j in range(3)] for i in range(3)]
    bvec = [sum((x ** i) * y for x, y in zip(xs, ys)) for i in range(3)]
    # solve 3x3
    import copy
    M = [row[:] + [bvec[i]] for i, row in enumerate(A)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(3):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for k2 in range(c, 4):
                M[r][k2] -= f * M[c][k2]
    coef = [M[i][3] / M[i][i] for i in range(3)]
    res_named, res_other = [], []
    for x, y in zip(xs, ys):
        fit = coef[0] + coef[1] * x + coef[2] * x * x
        r = y - fit
        (res_named if any(abs(x - v) < 1e-6 for v in NAMED)
         else res_other).append(r)
        tag = "★" if any(abs(x - v) < 1e-6 for v in NAMED) else " "
        print(f"    {tag} 起点 {x:.3f}  实测 {100*y:5.1f}%  拟合 {100*fit:5.1f}%"
              f"  残差 {100*r:+5.2f}pp")
    mn = sum(res_named) / len(res_named)
    mo = sum(res_other) / len(res_other)
    sd = math.sqrt(sum((r - mo) ** 2 for r in res_other) / (len(res_other) - 1))
    print(f"\n  具名点平均残差 = {100*mn:+.2f}pp（{len(res_named)} 点）")
    print(f"  非具名点平均残差 = {100*mo:+.2f}pp，非具名残差标准差 = "
          f"{100*sd:.2f}pp")
    print(f"  ⇒ 具名点的残差 = {mn/sd:+.2f} 个标准差。"
          "没有台阶 = 具名比例不特殊，做功的是距离。")


def e2_distance_only() -> None:
    hdr("E2  把『到达率』直接对距离作图：GG 的 64.6% 是不是就落在距离曲线上")
    d = data.daily(years="20y")
    lv = levels.build(d)
    print("  起点固定 = 0.382（GG 入口），推进距离滑动")
    print(f"  {'距离':>7}{'到达位':>9}{'具名?':>7}{'多头 P(到达)':>26}")
    for i in range(1, 13):
        dist = round(0.05 * i, 3)
        end = round(0.382 + dist, 3)
        ku, nu = transition(d, lv, 0.382, dist, +1)
        tag = "★具名" if any(abs(end - x) < 0.002 for x in NAMED) else ""
        print(f"  {dist:>7.3f}{end:>9.3f}{tag:>7}{stats.fmt_rate(ku, nu):>26}")


def e3_placebo_anchor() -> None:
    hdr("E3  安慰剂锚：把锚从『前日收盘』换成『前日中点』，GG 完成率变吗")
    d = data.daily(years="20y")
    lv = levels.build(d)
    for label, anchor_fn in (
            ("前收 (Saty 口径)", lambda L, b: L.anchor),
            ("前日中点", lambda L, b: (L.prev_high + L.prev_low) / 2),
            ("前日高", lambda L, b: L.prev_high),
            ("前日低", lambda L, b: L.prev_low)):
        k = n = 0
        for b in d:
            L = lv.get(b.day)
            if L is None:
                continue
            a = anchor_fn(L, b)
            p0, p1 = a + 0.382 * L.atr, a + 0.618 * L.atr
            if b.high < p0:
                continue
            n += 1
            k += int(b.high >= p1)
        print(f"  锚={label:<16}多头 GG 完成率 {stats.fmt_rate(k, n)}")
    print("  ⇒ 若换个任意锚也得到同量级的完成率，"
          "则『GG 完成率高』说的是日内行程分布，不是这两条线。")


def e4_shifted_ladder() -> None:
    hdr("E4  安慰剂偏移：整条梯子平移 +0.05 ATR（所有位都不再是斐波那契）")
    d = data.daily(years="20y")
    lv = levels.build(d)
    for shift in (0.0, 0.03, 0.05, -0.05):
        k = n = 0
        for b in d:
            L = lv.get(b.day)
            if L is None:
                continue
            p0 = L.at(0.382 + shift)
            p1 = L.at(0.618 + shift)
            if b.high < p0:
                continue
            n += 1
            k += int(b.high >= p1)
        print(f"  梯子平移 {shift:+.2f} ATR: 多头『GG』完成率 "
              f"{stats.fmt_rate(k, n)}")


def main() -> None:
    print(f"ADVERSARIAL AUDIT part 5  —  {datetime.now():%Y-%m-%d %H:%M}")
    e1_placebo_ladder()
    e2_distance_only()
    e3_placebo_anchor()
    e4_shifted_ladder()


if __name__ == "__main__":
    main()
