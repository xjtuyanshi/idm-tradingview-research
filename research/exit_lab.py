#!/usr/bin/env python3
"""Exit-geometry laboratory: same entries, alternative exits.

Replays the frozen replica to collect every plan (identical construction to
signal_stats.py), then re-simulates each plan's outcome under alternative
exit geometries using the actual 3m bar path.  Entries are held fixed (the
engine's own entry price on the signal bar), so differences between variants
isolate the exit design.  All variants use conservative stop-first accounting
on ambiguous bars and force a flat exit at the session boundary (last 3m bar
of the CAPITALCOM daily session that contains the entry).

This is in-sample exploration on one instrument and ~13 trading days; it
ranks exit designs, it does NOT prove edge.

Usage: python research/exit_lab.py <fixture_dir>
"""

from __future__ import annotations

import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from signal_stats import ET, WARMUP_BARS, load, load_daily, session_bucket  # noqa: E402
from v11_pine_replica import (  # noqa: E402
    ReplicaConfig,
    SETUP_NAMES,
    SIDE_LONG,
    V11PineReplica,
)


def build_plans(root: Path):
    bars3 = load(next(root.glob("*_3M_*.csv")), 180)
    bars10 = load(next(root.glob("*_10M_*.csv")), 600)
    bars1d = load_daily(next(root.glob("*_1D_*.csv")))
    replica = V11PineReplica(bars_10m=bars10, bars_daily=bars1d,
                             config=ReplicaConfig.from_contract())
    snapshots = replica.replay(bars3)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}

    plans = []
    for snap in snapshots:
        if bar_index[snap.close_ms] < WARMUP_BARS:
            continue
        sig = snap.new_signal
        plan = snap.plan
        if sig is not None and plan.active and plan.signal_id == sig.id:
            plans.append({
                "id": sig.id, "open_ms": snap.close_ms, "side": sig.side,
                "setup": SETUP_NAMES[sig.setup],
                "grade": {3: "A", 2: "B", 1: "C"}.get(sig.grade, "?"),
                "countertrend": sig.reason_mask >= 128,
                "entry": sig.entry, "stop": sig.stop, "t1": sig.t1,
                "t2": sig.t2, "risk": (sig.entry - sig.stop) * sig.side,
                "session": session_bucket(snap.close_ms),
            })
    return plans, bars3, bars1d


def session_end_index(open_ms: int, bars3, bars1d, bar_index) -> int:
    """Index of the last 3m bar of the daily session containing open_ms."""
    closes = [b.close_ms for b in bars1d]
    # bisect_left: a 3m bar closing exactly on the daily close belongs to
    # THAT session, not the next one (ChatGPT review P1-6a).
    k = bisect_left(closes, open_ms)
    cap_ms = closes[k] if k < len(closes) else bars3[-1].close_ms
    # last 3m bar whose close <= cap_ms
    ms_list = [b.close_ms for b in bars3]
    j = bisect_right(ms_list, cap_ms) - 1
    return max(j, bar_index[open_ms])


def simulate(plan, bars3, end_i, bar_index, variant: str):
    """Return realized R for the plan under the given exit variant, or None
    if the path runs off the data end while still holding."""
    side = plan["side"]
    entry = plan["entry"]
    risk = plan["risk"]
    if risk <= 1e-9:
        return None
    stop0 = plan["stop"]
    t1 = plan["t1"]
    t2 = plan["t2"]
    start_i = bar_index[plan["open_ms"]]
    if start_i >= end_i and variant != "V0":
        return 0.0  # entered on the session's last bar: flat immediately

    def pnl_r(price):
        return (price - entry) * side / risk

    legs = []          # (fraction, exit_price)
    remaining = 1.0
    stop = stop0
    t1_done = t2_done = False
    hh = entry         # best favorable extreme since entry (close basis high/low)
    ema12_prev = None

    for i in range(start_i + 1, end_i + 1):
        b = bars3[i]
        hi = (b.high - entry) * side
        lo = (b.low - entry) * side
        stop_hit = (b.low <= stop) if side == SIDE_LONG else (b.high >= stop)
        t1_hit = (b.high >= t1) if side == SIDE_LONG else (b.low <= t1)
        t2_hit = (b.high >= t2) if side == SIDE_LONG else (b.low <= t2)

        # conservative: stop first on ambiguous bars
        if stop_hit:
            legs.append((remaining, stop))
            remaining = 0.0
            break

        if variant == "V1":  # current fractions, stop never tightens
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
            if t2_hit and not t2_done and t1_done:
                legs.append((0.25, t2)); remaining -= 0.25; t2_done = True
        elif variant == "V2":  # BE delayed: after T1, stop -> entry - 0.25R
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
                stop = entry - 0.25 * risk * side
            if t2_hit and not t2_done and t1_done:
                legs.append((0.25, t2)); remaining -= 0.25; t2_done = True
                stop = entry  # runner protected at cost only after +2R
        elif variant == "V3":  # thirds + 1.2R trail after T1
            if t1_hit and not t1_done:
                legs.append((1 / 3, t1)); remaining -= 1 / 3; t1_done = True
            if t2_hit and not t2_done and t1_done:
                legs.append((1 / 3, t2)); remaining -= 1 / 3; t2_done = True
            if t1_done:
                trail = (hh - 1.2 * risk) if side == SIDE_LONG else (hh + 1.2 * risk)
                stop = max(stop, trail) if side == SIDE_LONG else min(stop, trail)
        elif variant == "V4":  # all-in all-out: 100% at T2 or stop
            if t2_hit:
                legs.append((remaining, t2)); remaining = 0.0
                break
        elif variant == "V5":  # 50% at T1, runner rides 3m close vs t1-level
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
            if t1_done:
                # runner exits when a 3m close gives back to entry level
                give_back = (b.close <= entry) if side == SIDE_LONG else (b.close >= entry)
                if give_back:
                    legs.append((remaining, b.close)); remaining = 0.0
                    break

        # update favorable extreme (price terms)
        if side == SIDE_LONG:
            hh = max(hh, b.high)
        else:
            hh = min(hh, b.low)

        if remaining <= 1e-9:
            break

    if remaining > 1e-9:
        if end_i >= len(bars3) - 1 and plan["open_ms"] >= bars3[-1].close_ms - 86400_000:
            return None  # data end, still holding: unsettled
        legs.append((remaining, bars3[end_i].close))
        remaining = 0.0
    return sum(f * pnl_r(px) for f, px in legs)


VARIANTS = {
    "V1": "现行分批50/25/25，但止损全程不动（无保本）",
    "V2": "保本延迟：T1后止损只到 入场−0.25R；T2后才到成本",
    "V3": "1/3制：T1/T2各1/3，末仓T1后1.2R跟踪",
    "V4": "不分批：100%仓位 T2或止损，二选一",
    "V5": "50%T1落袋，余仓收盘跌回入场价才走（无硬保本）",
}


def main(fixture_dir: str) -> None:
    root = Path(fixture_dir)
    plans, bars3, bars1d = build_plans(root)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}

    for p in plans:
        p["end_i"] = session_end_index(p["open_ms"], bars3, bars1d, bar_index)

    def agg(rs):
        rs = [r for r in rs if r is not None]
        n = len(rs)
        if n == 0:
            return dict(n=0, avg=0.0, win=0.0, aw=0.0, al=0.0, need=0.0, tot=0.0)
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        aw = sum(wins) / len(wins) if wins else 0.0
        al = sum(losses) / len(losses) if losses else 0.0
        need = 100.0 * (-al) / (aw - al) if aw - al > 1e-9 else 0.0
        return dict(n=n, avg=sum(rs) / n, win=100.0 * len(wins) / n,
                    aw=aw, al=al, need=need, tot=sum(rs))

    print(f"plans={len(plans)}  (entries identical across variants; "
          f"session-end flat; stop-first on ambiguous bars)")
    print(f"\n{'变体':4} {'n':>4} {'均R':>8} {'胜率%':>7} {'均赢R':>7} "
          f"{'均亏R':>7} {'打平需%':>8} {'总R':>8}   说明")

    results = {}
    for v, desc in VARIANTS.items():
        rs = [simulate(p, bars3, p["end_i"], bar_index, v) for p in plans]
        results[v] = rs
        a = agg(rs)
        print(f"{v:4} {a['n']:>4} {a['avg']:>8.3f} {a['win']:>7.1f} "
              f"{a['aw']:>7.3f} {a['al']:>7.3f} {a['need']:>8.1f} "
              f"{a['tot']:>8.1f}   {desc}")

    # entry-filter overlays on each variant
    filters = {
        "全部": lambda p: True,
        "非启动": lambda p: p["setup"] != "IGNITION",
        "非启动+RTH": lambda p: p["setup"] != "IGNITION"
        and p["session"] != "盘外时段",
        "非启动+RTH+非尾盘": lambda p: p["setup"] != "IGNITION"
        and p["session"] in ("开盘段0930-1130", "午间1130-1400"),
        "拒绝类+RTH+非尾盘": lambda p: p["setup"] == "LEVEL_REJECTION"
        and p["session"] in ("开盘段0930-1130", "午间1130-1400"),
    }
    print("\n== 变体 x 入场过滤（均R / n）==")
    hdr = f"{'过滤':16}" + "".join(f"{v:>16}" for v in VARIANTS)
    print(hdr)
    for fname, fn in filters.items():
        row = f"{fname:16}"
        for v in VARIANTS:
            rs = [r for p, r in zip(plans, results[v]) if fn(p) and r is not None]
            a = agg(rs)
            row += f"{a['avg']:>9.3f}/{a['n']:<6}"
        print(row)

    # best-variant slices
    best = max(VARIANTS, key=lambda v: agg(results[v])["avg"])
    print(f"\n== 最优变体 {best} 分切片（均R / n）==")
    for title, keyfn in [
        ("setup", lambda p: p["setup"]),
        ("grade", lambda p: p["grade"]),
        ("顺逆", lambda p: "逆势" if p["countertrend"] else "顺势"),
        ("时段", lambda p: p["session"]),
    ]:
        groups = defaultdict(list)
        for p, r in zip(plans, results[best]):
            if r is not None:
                groups[keyfn(p)].append(r)
        parts = [f"{k} {sum(v)/len(v):+.3f}/{len(v)}"
                 for k, v in sorted(groups.items())]
        print(f"  {title}: " + "  ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
