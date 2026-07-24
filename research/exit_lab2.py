#!/usr/bin/env python3
"""v12 follower simulation: one-position-at-a-time + cooldown + exit variants.

Chronological simulation of the proposed v12 "跟单模块" on top of the frozen
engine's signals: take only selected setups during selected sessions, hold at
most ONE follower position at a time (new signals while busy are ignored),
and after a stop-out ignore same-side signals for a cooldown window.  Exits
per variant (V1 = current 50/25/25 fractions with the stop never tightened;
V4 = all-in/all-out at T2 or stop).  Conservative stop-first fills,
session-end flat.  In-sample, ~13 days, one instrument.

Usage: python research/exit_lab2.py <fixture_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from exit_lab import build_plans, session_end_index  # noqa: E402

COOLDOWN_MS = 30 * 60 * 1000


def simulate_follower(plan, bars3, end_i, bar_index, variant):
    """Single-loop oracle (ChatGPT review P1-6c): returns
    (r, flat_i, full_stop) in ONE pass so R, the flat bar and the cooldown
    trigger can never drift apart.  Day-end semantics match the Pine core:
    the position settles at end_i's close and the follower is busy through
    the boundary bar (flat_i = end_i + 1), which also blocks a same-bar
    re-entry on the first bar of the new session.
    """
    side = plan["side"]
    entry = plan["entry"]
    risk = plan["risk"]
    if risk <= 1e-9:
        return None, None, False
    stop = plan["stop"]
    t1, t2 = plan["t1"], plan["t2"]
    start_i = bar_index[plan["open_ms"]]
    legs = []
    remaining = 1.0
    t1_done = t2_done = False
    for i in range(start_i + 1, end_i + 1):
        b = bars3[i]
        stop_hit = (b.low <= stop) if side == 1 else (b.high >= stop)
        t1_hit = (b.high >= t1) if side == 1 else (b.low <= t1)
        t2_hit = (b.high >= t2) if side == 1 else (b.low <= t2)
        if stop_hit:
            legs.append((remaining, stop))
            r = sum(f * (px - entry) * side / risk for f, px in legs)
            return r, i, (not t1_done)
        if variant == "V1":
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
            if t2_hit and t1_done and not t2_done:
                legs.append((0.25, t2)); remaining -= 0.25; t2_done = True
        elif variant == "V4":
            if t2_hit:
                legs.append((remaining, t2))
                r = sum(f * (px - entry) * side / risk for f, px in legs)
                return r, i, False
    # day-end settlement at end_i close; busy through the boundary bar
    if end_i + 1 >= len(bars3):
        return None, None, False  # data end while holding: unsettled
    legs.append((remaining, bars3[end_i].close))
    r = sum(f * (px - entry) * side / risk for f, px in legs)
    return r, end_i + 1, False


def run(plans, bars3, bars1d, bar_index, variant, setups, sessions,
        cooldown=True, one_at_a_time=True):
    busy_until = -1
    cd_side = 0
    cd_until = -1
    taken = []
    for p in plans:
        if p["setup"] not in setups or p["session"] not in sessions:
            continue
        if one_at_a_time and p["open_ms"] <= busy_until:
            continue
        if cooldown and p["side"] == cd_side and p["open_ms"] <= cd_until:
            continue
        end_i = session_end_index(p["open_ms"], bars3, bars1d, bar_index)
        r, flat_i, full_stop = simulate_follower(p, bars3, end_i, bar_index,
                                                 variant)
        if r is None:
            continue
        busy_until = bars3[flat_i].close_ms
        if full_stop:
            cd_side = p["side"]
            cd_until = busy_until + COOLDOWN_MS
        taken.append((p, r))
    return taken


EPS = 1e-12


def stats(taken):
    rs = [r for _, r in taken]
    n = len(rs)
    if n == 0:
        return "n=0"
    wins = [r for r in rs if r > EPS]
    losses = [r for r in rs if r < -EPS]
    flats = n - len(wins) - len(losses)
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    eq = mdd = peak = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return (f"n={n:<4} 均R={sum(rs)/n:+.3f} 正收益率={100*len(wins)/n:.1f}% "
            f"(平局{flats}) 均赢={aw:+.2f} 均亏={al:+.2f} 总R={sum(rs):+.1f} "
            f"闭合权益最大回撤={mdd:.1f}R")


def main(fixture_dir: str) -> None:
    root = Path(fixture_dir)
    plans, bars3, bars1d = build_plans(root)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}
    plans.sort(key=lambda p: p["open_ms"])

    LR = {"LEVEL_REJECTION"}
    LRB = {"LEVEL_REJECTION", "BREAKOUT"}
    AM_MID = {"开盘段0930-1130", "午间1130-1400"}
    RTH = AM_MID | {"尾盘1400-1600"}

    cases = [
        ("拒绝 · 早午盘 · V1 · 冷却+单仓", "V1", LR, AM_MID, True, True),
        ("拒绝 · 早午盘 · V4 · 冷却+单仓", "V4", LR, AM_MID, True, True),
        ("拒绝+突破 · 早午盘 · V1 · 冷却+单仓", "V1", LRB, AM_MID, True, True),
        ("拒绝+突破 · 早午盘 · V4 · 冷却+单仓", "V4", LRB, AM_MID, True, True),
        ("拒绝 · 全RTH · V1 · 冷却+单仓", "V1", LR, RTH, True, True),
        ("拒绝 · 早午盘 · V1 · 无冷却无单仓", "V1", LR, AM_MID, False, False),
        ("拒绝+突破 · 早午盘 · V1 · 无冷却无单仓", "V1", LRB, AM_MID, False, False),
    ]
    for name, v, st, ss, cd, oaat in cases:
        taken = run(plans, bars3, bars1d, bar_index, v, st, ss, cd, oaat)
        print(f"{name:34} {stats(taken)}")

    # per-day equity for the headline (pre-registered) case
    print("\n拒绝 · 早午盘 · V1 · 冷却+单仓（定案配置）—— 按日:")
    taken = run(plans, bars3, bars1d, bar_index, "V1", LR, AM_MID, True, True)
    from collections import defaultdict
    from datetime import datetime
    from signal_stats import ET
    days = defaultdict(list)
    for p, r in taken:
        days[datetime.fromtimestamp(p["open_ms"] / 1000, ET).strftime("%m-%d")].append(r)
    for d in sorted(days):
        rs = days[d]
        print(f"  {d}  n={len(rs):<3} 日R={sum(rs):+.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
