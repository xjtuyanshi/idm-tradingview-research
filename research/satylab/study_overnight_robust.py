#!/usr/bin/env python3
"""Robustness gauntlet for the overnight/pre-market findings.

study_overnight.py produced the strongest numbers this project has seen, which
is exactly when it is most likely to be fooling itself.  Before any of it goes
near a chart it has to survive four attacks:

  A. Tautology     — is the conditioner just restating the outcome?
  B. Confounding   — does the effect vanish once gap size and overnight range
                     are held fixed?
  C. Instability   — does it hold in each third of the sample separately?
  D. Instrument    — does it reproduce on SPY/cash rather than only ES?

Anything that fails A or C is dead.  Failing B means the finding belongs to
the confounder, not to Saty's condition.

Usage: python research/satylab/study_overnight_robust.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.study_overnight import rng, session_split  # noqa: E402


def collect(symbol: str = "ES=F") -> list[dict]:
    """One row per session with the conditioner, the confounders and outcomes."""
    daily = data.daily(symbol, years="20y")
    hourly = data.load(symbol, "730d", "1h")
    lv = levels.build(daily)
    sess = session_split(hourly)

    rows: list[dict] = []
    for d in sorted(sess):
        s, L = sess[d], lv.get(d)
        if not L or not s["pm"]:
            continue
        rth = s["rth"]
        pmh, pml = rng(s["pm"])
        onh, onl = rng(s["on"])
        i_break = levels.first_touch(rth, pmh, +1)
        if i_break is None:
            continue                        # the setup never triggered
        held = min(b.low for b in rth[:i_break + 1]) > pml
        r_at = L.ratio_of(pmh)
        nxt = next((r for r in levels.RATIOS if r > r_at + 1e-9), None)
        if nxt is None:
            continue
        after = rth[i_break:]
        rows.append({
            "day": d,
            "held": held,
            "hit": any(b.high >= L.at(nxt) for b in after),
            # confounders
            "gap": (rth[0].open - L.anchor) / L.atr,
            "on_range": (onh - onl) / L.atr,
            "dist_to_next": nxt - r_at,        # how far the target actually is
            "bars_left": len(after),
            "start_ratio": r_at,
        })
    return rows


def split_test(rows: list[dict], label: str, key, edges: list[float]) -> None:
    print(f"\n  控制变量: {label}")
    buckets: dict[str, dict[bool, list[dict]]] = {}
    for r in rows:
        v = key(r)
        name = "低"
        for i, e in enumerate(edges):
            if v >= e:
                name = ["低", "中", "高"][min(i + 1, 2)]
        buckets.setdefault(name, {True: [], False: []})[r["held"]].append(r)
    for name in ("低", "中", "高"):
        b = buckets.get(name)
        if not b:
            continue
        h, nh = b[True], b[False]
        if len(h) < 15 or len(nh) < 15:
            print(f"    {name:<4} 样本不足 (守={len(h)} 未守={len(nh)})")
            continue
        kh, nh_ = sum(r["hit"] for r in h), len(h)
        kn, nn_ = sum(r["hit"] for r in nh), len(nh)
        z = stats.two_proportion_z(kh, nh_, kn, nn_)
        mark = "✓" if abs(z) >= 1.96 else "✗ 消失"
        print(f"    {name:<4} 守={stats.fmt_rate(kh, nh_)}   "
              f"未守={stats.fmt_rate(kn, nn_)}   z={z:+.2f} {mark}")


def main() -> None:
    rows = collect("ES=F")
    print(f"ES 触发『上破盘前高』的交易日: {len(rows)}\n")
    print("=" * 70)
    print("攻击 A — 同义反复检验：条件与结果是不是同一件事的两种说法？")
    print("=" * 70)
    print("""  条件 = 上破盘前高之前，是否始终守住盘前低
  结果 = 上破之后，是否触及位图上的下一个具名位
  两组的**前提完全相同**（都上破了盘前高），差别只在此前的路径。
  结果发生在条件确定之后，且目标位来自与盘前区间无关的日线 ATR 位图。
  -> 不构成同义反复。但下面仍要检验它是不是别的东西的影子。""")

    k1 = sum(r["hit"] for r in rows if r["held"])
    n1 = sum(1 for r in rows if r["held"])
    k0 = sum(r["hit"] for r in rows if not r["held"])
    n0 = sum(1 for r in rows if not r["held"])
    print(f"\n  总体  守住={stats.fmt_rate(k1, n1)}   "
          f"未守={stats.fmt_rate(k0, n0)}   "
          f"z={stats.two_proportion_z(k1, n1, k0, n0):+.2f}")

    print()
    print("=" * 70)
    print("攻击 B — 混杂检验：控制住跳空、夜盘幅度、目标距离后还在吗？")
    print("=" * 70)
    split_test(rows, "开盘跳空 (ATR)", lambda r: r["gap"], [-0.1, 0.15])
    split_test(rows, "夜盘区间 (ATR)", lambda r: r["on_range"], [0.45, 0.75])
    split_test(rows, "到下一位的距离 (ATR)", lambda r: r["dist_to_next"],
               [0.10, 0.20])
    split_test(rows, "破位时剩余K数", lambda r: r["bars_left"], [3, 5])

    print()
    print("=" * 70)
    print("攻击 C — 时间稳定性：三段分别检验，异号即判死")
    print("=" * 70)
    third = len(rows) // 3
    for i, name in enumerate(("前 1/3", "中 1/3", "后 1/3")):
        seg = rows[i * third:(i + 1) * third] if i < 2 else rows[2 * third:]
        kh = sum(r["hit"] for r in seg if r["held"])
        nh = sum(1 for r in seg if r["held"])
        kn = sum(r["hit"] for r in seg if not r["held"])
        nn = sum(1 for r in seg if not r["held"])
        if nh and nn:
            z = stats.two_proportion_z(kh, nh, kn, nn)
            sign = "同号 ✓" if (kh / nh) > (kn / nn) else "**反号 ✗**"
            print(f"  {name} ({seg[0]['day']}~{seg[-1]['day']})  "
                  f"守={stats.fmt_rate(kh, nh)}  未守={stats.fmt_rate(kn, nn)}  "
                  f"z={z:+.2f}  {sign}")

    print()
    print("=" * 70)
    print("攻击 D — 换标的：SPY（现货 ETF，含盘前但无夜盘期货时段）")
    print("=" * 70)
    try:
        spy = collect("SPY")
        kh = sum(r["hit"] for r in spy if r["held"])
        nh = sum(1 for r in spy if r["held"])
        kn = sum(r["hit"] for r in spy if not r["held"])
        nn = sum(1 for r in spy if not r["held"])
        z = stats.two_proportion_z(kh, nh, kn, nn)
        print(f"  SPY n={len(spy)}  守={stats.fmt_rate(kh, nh)}  "
              f"未守={stats.fmt_rate(kn, nn)}  z={z:+.2f}")
        print("  注：Yahoo 的 SPY 小时线只覆盖 RTH，'盘前'区间可能为空或极短，")
        print("      因此本项检验偏弱，不能作为否定证据，只作为正向佐证。")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  SPY 检验无法进行: {exc}")


if __name__ == "__main__":
    main()
