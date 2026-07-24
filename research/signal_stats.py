#!/usr/bin/env python3
"""Signal-conditional statistics over the full true-data window.

Replays the frozen-Pine replica over the ENTIRE 3m export (~13 trading days,
much wider than the 1500-bar study window) and produces a plan-level ledger:
every plan's outcome sequence, realized R (50/25/25 leg model at recorded
event prices), MFE/MAE, and conditional slices by setup / grade / trend side /
session hour.  This is in-sample exploration on one instrument and one regime;
it ranks conditions, it does NOT prove edge.

Usage: python research/signal_stats.py <fixture_dir> [--csv out.csv]
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from v11_pine_replica import (  # noqa: E402
    Bar,
    EVENT_NAMES,
    EVENT_REVERSE,
    EVENT_STOP,
    EVENT_STRUCTURE_EXIT,
    EVENT_T1,
    EVENT_T2,
    ReplicaConfig,
    ROLE_COUNTERTREND_ADVISORY,
    ROLE_INITIAL,
    ROLE_REVERSE,
    SETUP_NAMES,
    SIDE_LONG,
    V11PineReplica,
)

ET = timezone(timedelta(hours=-4))
WARMUP_BARS = 60


def load(path: Path, tf: int) -> list[Bar]:
    rows = list(csv.reader(open(path, encoding="utf-8")))[1:-1]
    return [
        Bar((int(float(r[0])) + tf) * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]))
        for r in rows
    ]


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


def session_bucket(close_ms: int) -> str:
    t = datetime.fromtimestamp(close_ms / 1000, ET)
    hm = t.hour * 60 + t.minute
    if 9 * 60 + 30 < hm <= 11 * 60 + 30:
        return "开盘段0930-1130"
    if 11 * 60 + 30 < hm <= 14 * 60:
        return "午间1130-1400"
    if 14 * 60 < hm <= 16 * 60:
        return "尾盘1400-1600"
    return "盘外时段"


def main(fixture_dir: str, csv_out: str | None = None) -> None:
    root = Path(fixture_dir)
    bars3 = load(next(root.glob("*_3M_*.csv")), 180)
    bars10 = load(next(root.glob("*_10M_*.csv")), 600)
    bars1d = load_daily(next(root.glob("*_1D_*.csv")))

    replica = V11PineReplica(bars_10m=bars10, bars_daily=bars1d,
                             config=ReplicaConfig.from_contract())
    snapshots = replica.replay(bars3)

    bar_by_ms = {b.close_ms: (i, b) for i, b in enumerate(bars3)}
    ms_sorted = [b.close_ms for b in bars3]

    # Build plan records: a plan starts at a signal whose id becomes plan.signal_id.
    plans: list[dict] = []
    open_plan: dict | None = None
    events_by_ms = defaultdict(list)
    for e in replica.plan_events:
        events_by_ms[e.close_ms].append(e)

    for snap in snapshots:
        if bar_by_ms[snap.close_ms][0] < WARMUP_BARS:
            continue
        # close events against the open plan
        for e in events_by_ms.get(snap.close_ms, []):
            if open_plan is not None and e.type in (
                EVENT_T1, EVENT_T2, EVENT_STOP, EVENT_STRUCTURE_EXIT, EVENT_REVERSE
            ):
                open_plan["events"].append((e.type, e.price, snap.close_ms))
        sig = snap.new_signal
        plan = snap.plan
        if sig is not None and plan.active and plan.signal_id == sig.id:
            # a new plan opened on this bar (INITIAL or REVERSE)
            if open_plan is not None:
                open_plan["ended"] = True
            open_plan = {
                "id": sig.id, "open_ms": snap.close_ms, "side": sig.side,
                "setup": SETUP_NAMES[sig.setup], "grade": "ABC"[3 - sig.grade] if sig.grade in (1,2,3) else "?",
                "grade_n": sig.grade,
                "countertrend": sig.reason_mask >= 128,
                "ctx_aligned": bool(sig.reason_mask & 16),
                "pace_aligned": bool(sig.reason_mask & 32),
                "entry": sig.entry, "stop": sig.stop, "t1": sig.t1, "t2": sig.t2,
                "risk": (sig.entry - sig.stop) * sig.side,
                "session": session_bucket(snap.close_ms),
                "events": [], "closed": False,
            }
            plans.append(open_plan)
        if open_plan is not None and not plan.active:
            open_plan["ended"] = True

    # Outcome + realized R per plan (50/25/25 legs at event prices).
    for p in plans:
        risk = p["risk"]
        side = p["side"]
        entry = p["entry"]
        legs = []  # (fraction, exit_price)
        remaining = 1.0
        t1_done = t2_done = False
        outcome = "OPEN"
        for etype, price, ms in p["events"]:
            if etype == EVENT_T1 and not t1_done:
                legs.append((0.5, p["t1"])); remaining -= 0.5; t1_done = True
            elif etype == EVENT_T2 and not t2_done:
                if not t1_done:
                    legs.append((0.5, p["t1"])); remaining -= 0.5; t1_done = True
                legs.append((0.25, p["t2"])); remaining -= 0.25; t2_done = True
            elif etype in (EVENT_STOP, EVENT_STRUCTURE_EXIT, EVENT_REVERSE):
                legs.append((remaining, price)); remaining = 0.0
                outcome = EVENT_NAMES[etype]
                break
        if remaining > 0:
            if t2_done and p.get("ended"):
                # terminal T2 full exit (runner not intact): the engine closed
                # everything at the T2 price with no further event.
                legs.append((remaining, p["t2"])); remaining = 0.0
                outcome = "T2_EXIT"
            else:
                # genuinely still running at data end: leave unsettled
                outcome = "RUNNING_T1" if t1_done else "RUNNING"
        if outcome == "OPEN":
            outcome = "UNSETTLED"
        elif outcome == "STOP":
            outcome = "STOP_AFTER_T1" if t1_done else "LOSS_STOP"
        p["settled"] = remaining <= 1e-9
        p["outcome"] = outcome
        p["t1_hit"] = t1_done
        p["r"] = (sum(f * ((px - entry) * side) for f, px in legs) / risk
                  if risk > 1e-9 and p["settled"] else None)

        # MFE / MAE until plan close (or data end)
        start_i = bar_by_ms[p["open_ms"]][0]
        end_ms = p["events"][-1][2] if p["events"] else ms_sorted[-1]
        end_i = bar_by_ms.get(end_ms, (len(bars3) - 1, None))[0]
        mfe = mae = 0.0
        for b in bars3[start_i + 1: end_i]:  # exclude the terminal bar
            up = (b.high - entry) * side
            dn = (b.low - entry) * side
            mfe = max(mfe, up if side == SIDE_LONG else (entry - b.low))
            mae = min(mae, dn if side == SIDE_LONG else (entry - b.high))
        p["mfe_r"] = ((max(0.0, ( (b.high - entry) if side==SIDE_LONG else (entry - b.low)))) if False else mfe / risk) if risk > 1e-9 else 0.0
        p["mae_r"] = mae / risk if risk > 1e-9 else 0.0
        p["fast_death"] = (not t1_done) and p["mfe_r"] < 0.3 and p["outcome"] == "LOSS_STOP"

    done = [p for p in plans if p["settled"] and p["r"] is not None]

    def agg(rows):
        n = len(rows)
        if n == 0:
            return dict(n=0)
        t1 = sum(1 for p in rows if p["t1_hit"])
        return dict(
            n=n,
            t1_rate=100.0 * t1 / n,
            avg_r=sum(p["r"] for p in rows) / n,
            fast_death=100.0 * sum(1 for p in rows if p["fast_death"]) / n,
            avg_mae=sum(p["mae_r"] for p in rows) / n,
        )

    def show(title, keyfn):
        groups = defaultdict(list)
        for p in done:
            groups[keyfn(p)].append(p)
        print(f"\n== {title} ==")
        print(f"{'组':18} {'n':>4} {'T1先达%':>8} {'均R':>7} {'秒杀%':>7} {'均MAE(R)':>9}")
        for k in sorted(groups, key=lambda k: -agg(groups[k]).get('t1_rate', 0)):
            a = agg(groups[k])
            print(f"{str(k):18} {a['n']:>4} {a['t1_rate']:>8.1f} {a['avg_r']:>7.3f} {a['fast_death']:>7.1f} {a['avg_mae']:>9.2f}")

    total = agg(done)
    print(f"window: {datetime.fromtimestamp(bars3[WARMUP_BARS].close_ms/1000, ET):%m-%d} -> "
          f"{datetime.fromtimestamp(bars3[-1].close_ms/1000, ET):%m-%d}  "
          f"plans={len(plans)} settled={len(done)}")
    print(f"TOTAL  T1先达 {total['t1_rate']:.1f}%  均R {total['avg_r']:.3f}  秒杀率 {total['fast_death']:.1f}%")

    show("按类型 setup", lambda p: p["setup"])
    show("按等级 grade", lambda p: {3:"A",2:"B",1:"C"}[p["grade_n"]])
    show("顺势/逆势", lambda p: "逆势CT" if p["countertrend"] else "顺势")
    show("按时段(ET)", lambda p: p["session"])
    show("等级x方向", lambda p: ("逆" if p["countertrend"] else "顺") + {3:"A",2:"B",1:"C"}[p["grade_n"]])
    show("setup x 顺逆", lambda p: p["setup"][:8] + ("/逆" if p["countertrend"] else "/顺"))
    show("10m方向一致性", lambda p: "dir+pace" if (p["ctx_aligned"] and p["pace_aligned"]) else ("dir仅" if p["ctx_aligned"] else "不一致"))

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id","open_et","side","setup","grade","countertrend","session",
                        "outcome","t1_hit","r","mfe_r","mae_r","fast_death","risk"])
            for p in plans:
                w.writerow([p["id"], datetime.fromtimestamp(p["open_ms"]/1000, ET).isoformat(),
                            p["side"], p["setup"], {3:"A",2:"B",1:"C"}[p["grade_n"]],
                            int(p["countertrend"]), p["session"], p["outcome"], int(p["t1_hit"]),
                            round(p["r"],4), round(p["mfe_r"],3), round(p["mae_r"],3),
                            int(p["fast_death"]), round(p["risk"],3)])
        print(f"\nledger -> {csv_out}")


if __name__ == "__main__":
    out = None
    args = [a for a in sys.argv[1:]]
    if "--csv" in args:
        i = args.index("--csv"); out = args[i+1]; del args[i:i+2]
    main(args[0] if args else ".", out)
