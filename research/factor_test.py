#!/usr/bin/env python3
"""Factor study over the 13-day plan ledger.

For every settled plan, build a binary/categorical feature set, then:
  1. payoff decomposition (why is expectancy negative: avg win vs avg loss
     vs the win rate the payoff structure REQUIRES);
  2. univariate factor tables;
  3. exhaustive filter-combination search (all subsets of 10 binary filters,
     n >= 40) ranked by average R;
  4. hand-rolled logistic regression on T1-first as factor "weights".

In-sample, single instrument, single fortnight: ranks factors, proves nothing.

Usage: python research/factor_test.py <fixture_dir>
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from itertools import combinations
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from v11_pine_replica import (  # noqa: E402
    Bar,
    EVENT_REVERSE,
    EVENT_STOP,
    EVENT_STRUCTURE_EXIT,
    EVENT_T1,
    EVENT_T2,
    ReplicaConfig,
    SETUP_BREAKOUT,
    SETUP_IGNITION,
    SETUP_LEVEL_REJECTION,
    SETUP_NAMES,
    SETUP_PULLBACK_CONTINUATION,
    SIDE_LONG,
    V11PineReplica,
)

ET = timezone(timedelta(hours=-4))
WARMUP = 60


def load(path: Path, tf: int) -> list[Bar]:
    rows = list(csv.reader(open(path, encoding="utf-8")))[1:-1]
    return [Bar((int(float(r[0])) + tf) * 1000, float(r[1]), float(r[2]),
                float(r[3]), float(r[4])) for r in rows]


def load_daily(path: Path) -> list[Bar]:
    rows = list(csv.reader(open(path, encoding="utf-8")))[1:-1]
    opens = [int(float(r[0])) for r in rows]
    out = []
    for k, r in enumerate(rows):
        close_s = opens[k] + 86400
        if k + 1 < len(rows):
            close_s = min(close_s, opens[k + 1])
        out.append(Bar(close_s * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return out


def build_plans(root: Path) -> list[dict]:
    bars3 = load(next(root.glob("*_3M_*.csv")), 180)
    replica = V11PineReplica(
        bars_10m=load(next(root.glob("*_10M_*.csv")), 600),
        bars_daily=load_daily(next(root.glob("*_1D_*.csv"))),
        config=ReplicaConfig.from_contract(),
    )
    snapshots = replica.replay(bars3)
    events_by_ms = defaultdict(list)
    for e in replica.plan_events:
        events_by_ms[e.close_ms].append(e)

    idx_of = {b.close_ms: i for i, b in enumerate(bars3)}
    plans: list[dict] = []
    open_plan: dict | None = None
    for snap in snapshots:
        i = idx_of[snap.close_ms]
        if i < WARMUP:
            continue
        for e in events_by_ms.get(snap.close_ms, []):
            if open_plan is not None:
                open_plan["events"].append((e.type, e.price, snap.close_ms))
        if open_plan is not None and not snap.plan.active:
            open_plan["ended"] = True
        sig = snap.new_signal
        if sig is not None and snap.plan.active and snap.plan.signal_id == sig.id:
            if open_plan is not None:
                open_plan["ended"] = True
            t = datetime.fromtimestamp(snap.close_ms / 1000, ET)
            hm = t.hour * 60 + t.minute
            open_plan = {
                "id": sig.id, "open_ms": snap.close_ms, "side": sig.side,
                "setup": sig.setup, "grade": sig.grade,
                "mask": sig.reason_mask,
                "entry": sig.entry, "stop": sig.stop, "t1": sig.t1, "t2": sig.t2,
                "risk": (sig.entry - sig.stop) * sig.side,
                "space": sig.space_r,
                "atr": snap.atr or 0.0,
                "ema5": snap.debug.get("ema5"),
                "hm": hm, "weekday": t.weekday(),
                "events": [],
            }
            plans.append(open_plan)

    for p in plans:
        risk, side, entry = p["risk"], p["side"], p["entry"]
        legs, remaining = [], 1.0
        t1_done = t2_done = False
        outcome = None
        for etype, price, ms in p["events"]:
            if etype == EVENT_T1 and not t1_done:
                legs.append((0.5, p["t1"])); remaining -= 0.5; t1_done = True
            elif etype == EVENT_T2 and not t2_done:
                if not t1_done:
                    legs.append((0.5, p["t1"])); remaining -= 0.5; t1_done = True
                legs.append((0.25, p["t2"])); remaining -= 0.25; t2_done = True
            elif etype in (EVENT_STOP, EVENT_STRUCTURE_EXIT, EVENT_REVERSE):
                legs.append((remaining, price)); remaining = 0.0
                outcome = etype
                break
        if remaining > 0 and t2_done and p.get("ended"):
            legs.append((remaining, p["t2"])); remaining = 0.0
            outcome = "T2_EXIT"
        p["settled"] = remaining <= 1e-9
        if remaining > 0:
            legs.append((remaining, None))  # genuinely running at data end
        p["t1_hit"] = t1_done
        if p["settled"] and risk > 1e-9:
            p["r"] = sum(f * ((px - entry) * side) for f, px in legs) / risk
        else:
            p["r"] = None
    return [p for p in plans if p["settled"] and p["r"] is not None]


def features(p: dict) -> dict:
    ext = abs(p["entry"] - p["ema5"]) / p["atr"] if p["ema5"] and p["atr"] else 9.9
    rth = 570 < p["hm"] <= 960
    return {
        "顺势": p["mask"] < 128,
        "10m方向同向": bool(p["mask"] & 16),
        "10m节奏同向": bool(p["mask"] & 32),
        "Phase同向": bool(p["mask"] & 64),
        "非启动类": p["setup"] != SETUP_IGNITION,
        "非拒绝类": p["setup"] != SETUP_LEVEL_REJECTION,
        "回踩或突破": p["setup"] in (SETUP_PULLBACK_CONTINUATION, SETUP_BREAKOUT),
        "常规时段": rth,
        "空间≥0.8R": p["space"] >= 0.8,
        "止损≤0.8ATR": (p["risk"] / p["atr"] if p["atr"] else 9) <= 0.8,
        "未过度延伸≤1ATR": ext <= 1.0,
        "A级": p["grade"] == 3,
    }


def agg(rows):
    n = len(rows)
    if n == 0:
        return None
    t1 = sum(1 for p in rows if p["t1_hit"])
    wins = [p["r"] for p in rows if p["r"] > 0]
    losses = [p["r"] for p in rows if p["r"] <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    need = abs(avg_loss) / (avg_win + abs(avg_loss)) * 100 if (avg_win + abs(avg_loss)) > 0 else 100
    return dict(n=n, t1=100 * t1 / n, r=sum(p["r"] for p in rows) / n,
                winrate=100 * len(wins) / n, avg_win=avg_win, avg_loss=avg_loss, need=need)


def main(fixture_dir: str) -> None:
    plans = build_plans(Path(fixture_dir))
    feats = [features(p) for p in plans]
    names = list(feats[0].keys())

    total = agg(plans)
    print(f"settled plans: {total['n']}")
    print(f"总体: T1先达 {total['t1']:.1f}%  盈亏比意义上的胜率 {total['winrate']:.1f}%  均R {total['r']:+.3f}")
    print(f"收益结构: 平均盈利单 {total['avg_win']:+.3f}R vs 平均亏损单 {total['avg_loss']:+.3f}R")
    print(f"→ 该收益结构下打平所需胜率 = {total['need']:.1f}%   （这就是负期望的数学根源）")

    print(f"\n== 单因子 ==")
    print(f"{'因子':16} {'有·n':>5} {'有·T1%':>7} {'有·均R':>8} | {'无·n':>5} {'无·T1%':>7} {'无·均R':>8}")
    for name in names:
        yes = [p for p, f in zip(plans, feats) if f[name]]
        no = [p for p, f in zip(plans, feats) if not f[name]]
        ay, an = agg(yes), agg(no)
        if ay and an:
            print(f"{name:16} {ay['n']:>5} {ay['t1']:>7.1f} {ay['r']:>+8.3f} | "
                  f"{an['n']:>5} {an['t1']:>7.1f} {an['r']:>+8.3f}")

    print(f"\n== 组合搜索（全部 1-4 因子组合，n≥40，按均R排序，前 12）==")
    results = []
    for k in range(1, 5):
        for combo in combinations(names, k):
            rows = [p for p, f in zip(plans, feats) if all(f[c] for c in combo)]
            a = agg(rows)
            if a and a["n"] >= 40:
                results.append((a["r"], a, combo))
    results.sort(key=lambda x: -x[0])
    seen_best = []
    for r, a, combo in results:
        label = " + ".join(combo)
        if any(set(combo) >= set(prev) for prev in seen_best):
            continue
        seen_best.append(combo)
        print(f"  {a['r']:+.3f}R  T1 {a['t1']:>5.1f}%  胜率 {a['winrate']:>5.1f}%  n={a['n']:>4}  {label}")
        if len(seen_best) >= 12:
            break

    # logistic regression on t1_hit -> factor weights
    X = [[1.0] + [1.0 if f[name] else 0.0 for name in names] for f in feats]
    y = [1.0 if p["t1_hit"] else 0.0 for p in plans]
    w = [0.0] * (len(names) + 1)
    lr = 0.05
    for _ in range(4000):
        grad = [0.0] * len(w)
        for xi, yi in zip(X, y):
            z = sum(wj * xj for wj, xj in zip(w, xi))
            pr = 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))
            err = pr - yi
            for j, xj in enumerate(xi):
                grad[j] += err * xj
        for j in range(len(w)):
            w[j] -= lr * grad[j] / len(X)
    print(f"\n== T1先达的逻辑回归权重（正=提升成功率）==")
    ranked = sorted(zip(names, w[1:]), key=lambda t: -abs(t[1]))
    for name, weight in ranked:
        print(f"  {weight:+.3f}  {name}")
    print(f"  (截距 {w[0]:+.3f})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
