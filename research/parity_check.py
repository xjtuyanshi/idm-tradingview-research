#!/usr/bin/env python3
"""Bar-by-bar parity check: frozen Pine (true TradingView export) vs replica.

Usage:
    python research/parity_check.py <fixture_dir>

The fixture directory must contain the three private true-v11 exports (kept
OUTSIDE the public repository on purpose):

    IDM_V11_TRUE_FIXTURE_SPX500_3M_<date>.csv    OHLC + 54 IDM plot columns
    IDM_V11_TRUE_FIXTURE_SPX500_10M_<date>.csv   OHLC + relay plot columns
    IDM_V11_TRUE_FIXTURE_SPX500_1D_<date>.csv    OHLC only

Column layout of the study exports is positional: field 0..5 are
time/open/high/low/close/volume (time = bar OPEN, epoch seconds), field 6+k is
Pine ``plot_k``.  The plot-id semantics below were captured from the running
chart's metaInfo on 2026-07-21 and match the frozen source order
(pine:1146-1473).

State alignment: the strategy runs with ``calc_bars_count=1500``, so Pine
seeded every 3m series at the first bar of its calculation window.  Feeding
the replica exactly the rows where the study columns are populated reproduces
that seeding bar-for-bar.  The 10m/daily context series are recomputed from
their own exports (long warm-up; EMA/RMA memory decays well before the 3m
window starts) and validated against Pine's own plotted context columns.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from v11_pine_replica import (  # noqa: E402
    Bar,
    ReplicaConfig,
    V11PineReplica,
)

# plot_k -> semantic name (captured from metaInfo, 2026-07-21)
PLOT = {
    "ema5": 0,
    "ema12": 2,
    "ctx_ema34": 5,
    "ctx_ema50": 7,
    "support": 10,
    "resistance": 11,
    "plan_entry_line": 12,
    "plan_initial_stop_line": 13,
    "plan_stop_line": 14,
    "plan_t1_line": 15,
    "plan_t2_line": 16,
    "canonical_time": 35,
    "ctx_time": 36,
    "ctx_dir": 37,
    "ctx_pace": 38,
    "signal_id": 39,
    "signal_setup": 40,
    "signal_grade": 41,
    "signal_mask": 42,
    "long_blocker": 43,
    "short_blocker": 44,
    "next_buy_trigger": 45,
    "next_sell_trigger": 46,
    "frozen_entry": 47,
    "frozen_initial_stop": 48,
    "effective_stop": 49,
    "frozen_t1": 50,
    "frozen_t2": 51,
    "plan_event_code": 52,
}


def plot_field(row: list[str], name: str) -> float | None:
    value = row[6 + PLOT[name]]
    if value == "":
        return None
    return float(value)


@dataclass
class FieldDiff:
    name: str
    compared: int = 0
    mismatched: int = 0
    max_abs: float = 0.0
    first_bad_time: int | None = None
    samples: list = field(default_factory=list)

    def check(self, time_s: int, pine, mine, tol: float = 1e-6) -> None:
        both_none = pine is None and mine is None
        if both_none:
            return
        self.compared += 1
        if pine is None or mine is None:
            bad, delta = True, float("inf")
        else:
            delta = abs(pine - mine)
            bad = delta > tol
        if bad:
            self.mismatched += 1
            if delta != float("inf"):
                self.max_abs = max(self.max_abs, delta)
            if self.first_bad_time is None:
                self.first_bad_time = time_s
            if len(self.samples) < 3:
                self.samples.append((time_s, pine, mine))


def load_rows(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return rows[1:]  # drop header


def to_bars(rows: list[list[str]], tf_seconds: int) -> list[Bar]:
    bars = []
    for row in rows:
        bars.append(
            Bar(
                (int(float(row[0])) + tf_seconds) * 1000,
                float(row[1]), float(row[2]), float(row[3]), float(row[4]),
            )
        )
    return bars


def to_daily_bars(rows: list[list[str]]) -> list[Bar]:
    """Daily bars with session-chained closes.

    CAPITALCOM CFD daily bars are not uniformly 24h: the Sunday-reopen bar
    runs 23h (22:00 UTC -> 21:00 UTC).  A fixed +24h close kept the stale
    prior-day anchor alive for the first hour of the next session and
    produced phantom signals there, so each bar closes at
    min(open + 24h, next bar's open).
    """

    opens = [int(float(r[0])) for r in rows]
    bars = []
    for k, row in enumerate(rows):
        close_s = opens[k] + 86400
        if k + 1 < len(rows):
            close_s = min(close_s, opens[k + 1])
        bars.append(
            Bar(
                close_s * 1000,
                float(row[1]), float(row[2]), float(row[3]), float(row[4]),
            )
        )
    return bars


def run(fixture_dir: str) -> dict:
    root = Path(fixture_dir)
    f3 = next(root.glob("*_3M_*.csv"))
    f10 = next(root.glob("*_10M_*.csv"))
    f1d = next(root.glob("*_1D_*.csv"))

    rows3 = load_rows(f3)[:-1]      # drop the live (open) capture bar
    rows10 = load_rows(f10)[:-1]
    rows1d = load_rows(f1d)[:-1]

    # Pine's calc window = rows whose study columns are populated.  Its own
    # early-window na plots (EMA, next-trigger) prove the strategy seeded all
    # 3m series at the first bar of that window, so the replica starts there
    # too; with SMA-seeded ta.ema/ta.rma semantics the states then coincide.
    study_rows = [r for r in rows3 if r[6 + PLOT["canonical_time"]] != ""]
    window_start = rows3.index(study_rows[0])
    replay_rows = rows3[window_start:]

    bars3_all = to_bars(rows3, 180)
    bars10 = to_bars(rows10, 600)
    bars1d = to_daily_bars(rows1d)

    config = ReplicaConfig.from_contract()  # mintick 0.1 (CAPITALCOM:SPX500)
    replica = V11PineReplica(bars_10m=bars10, bars_daily=bars1d, config=config)
    snapshots = replica.replay(bars3_all[window_start:])

    diffs = {
        name: FieldDiff(name)
        for name in (
            "ema5", "ema12", "ctx_ema34", "ctx_ema50", "ctx_time",
            "ctx_dir", "ctx_pace", "support", "resistance",
            "next_buy_trigger", "next_sell_trigger",
            "long_blocker", "short_blocker",
            "plan_entry", "plan_initial_stop", "plan_effective_stop",
            "plan_t1", "plan_t2",
        )
    }

    pine_signals = []
    pine_plan_events = []
    for row, snap in zip(replay_rows, snapshots):
        time_s = int(float(row[0]))
        dbg = snap.debug
        diffs["ema5"].check(time_s, plot_field(row, "ema5"), dbg["ema5"])
        diffs["ema12"].check(time_s, plot_field(row, "ema12"), dbg["ema12"])
        diffs["ctx_ema34"].check(time_s, plot_field(row, "ctx_ema34"), dbg["ctx_ema34"])
        diffs["ctx_ema50"].check(time_s, plot_field(row, "ctx_ema50"), dbg["ctx_ema50"])
        diffs["ctx_time"].check(time_s, plot_field(row, "ctx_time"), snap.context_close_ms)
        diffs["ctx_dir"].check(time_s, plot_field(row, "ctx_dir"), snap.context_direction, 0)
        diffs["ctx_pace"].check(time_s, plot_field(row, "ctx_pace"), snap.context_pace, 0)
        diffs["support"].check(time_s, plot_field(row, "support"), snap.support)
        diffs["resistance"].check(time_s, plot_field(row, "resistance"), snap.resistance)
        diffs["next_buy_trigger"].check(
            time_s, plot_field(row, "next_buy_trigger"), snap.next_long_trigger
        )
        diffs["next_sell_trigger"].check(
            time_s, plot_field(row, "next_sell_trigger"), snap.next_short_trigger
        )
        diffs["long_blocker"].check(time_s, plot_field(row, "long_blocker"), snap.long_blocker, 0)
        diffs["short_blocker"].check(time_s, plot_field(row, "short_blocker"), snap.short_blocker, 0)
        plan = snap.plan
        diffs["plan_entry"].check(
            time_s, plot_field(row, "frozen_entry"), plan.entry if plan.active else None
        )
        diffs["plan_initial_stop"].check(
            time_s, plot_field(row, "frozen_initial_stop"), plan.stop if plan.active else None
        )
        diffs["plan_effective_stop"].check(
            time_s, plot_field(row, "effective_stop"),
            plan.effective_stop if plan.active else None,
        )
        diffs["plan_t1"].check(
            time_s, plot_field(row, "frozen_t1"), plan.t1 if plan.active else None
        )
        diffs["plan_t2"].check(
            time_s, plot_field(row, "frozen_t2"), plan.t2 if plan.active else None
        )
        sid = plot_field(row, "signal_id")
        if sid is not None:
            pine_signals.append(
                (
                    time_s, int(sid),
                    int(plot_field(row, "signal_setup") or 0),
                    int(plot_field(row, "signal_grade") or 0),
                    int(plot_field(row, "signal_mask") or 0),
                )
            )
        pec = plot_field(row, "plan_event_code")
        if pec is not None:
            pine_plan_events.append((time_s, int(pec)))

    window_first_close = bars3_all[window_start].close_ms
    window_signals = [s for s in replica.signals if s.close_ms >= window_first_close]
    window_events = [e for e in replica.plan_events if e.close_ms >= window_first_close]
    my_signals = {s.id: s for s in window_signals}
    pine_ids = {sid for _, sid, *_ in pine_signals}
    matched = missing = wrong_meta = 0
    detail_missing = []
    for time_s, sid, setup, grade, mask in pine_signals:
        mine = my_signals.get(sid)
        if mine is None:
            missing += 1
            if len(detail_missing) < 8:
                detail_missing.append((time_s, sid, setup, grade, mask))
        elif (mine.setup, mine.grade, mine.reason_mask) != (setup, grade, mask):
            wrong_meta += 1
        else:
            matched += 1
    extra = [s for s in window_signals if s.id not in pine_ids]

    my_events_by_bar: dict[int, list[int]] = {}
    for event in window_events:
        my_events_by_bar.setdefault(event.close_ms // 1000 - 180, []).append(event.type)
    event_matched = event_missing = 0
    event_detail = []
    for time_s, code in pine_plan_events:
        if code in my_events_by_bar.get(time_s, []):
            event_matched += 1
        else:
            event_missing += 1
            if len(event_detail) < 8:
                event_detail.append((time_s, code))
    my_event_count = len(window_events)

    return {
        "rows3": len(rows3),
        "window_rows": len(replay_rows),
        "pine_signals": pine_signals,
        "replica_signals": window_signals,
        "matched": matched,
        "wrong_meta": wrong_meta,
        "missing": missing,
        "missing_detail": detail_missing,
        "extra": extra,
        "pine_plan_events": pine_plan_events,
        "replica_plan_events": window_events,
        "event_matched": event_matched,
        "event_missing": event_missing,
        "event_detail": event_detail,
        "diffs": diffs,
    }


def main(fixture_dir: str) -> int:
    stats = run(fixture_dir)
    diffs = stats["diffs"]
    print(f"fixture 3m rows: {stats['rows3']}  calc-window rows: {stats['window_rows']}")
    print(f"pine signals: {len(stats['pine_signals'])}  replica signals: {len(stats['replica_signals'])}")
    print(f"  matched(id+setup+grade+mask): {stats['matched']}")
    print(f"  id matched but meta wrong:    {stats['wrong_meta']}")
    print(f"  pine-only (missing in replica): {stats['missing']}")
    print(f"  replica-only (extra):           {len(stats['extra'])}")
    if stats["missing_detail"]:
        print("  first pine-only:", stats["missing_detail"])
    if stats["extra"][:5]:
        print("  first replica-only:", [(s.close_ms // 1000 - 180, s.id) for s in stats["extra"][:5]])
    print(f"pine plan-event pulses: {len(stats['pine_plan_events'])}  replica plan events: {len(stats['replica_plan_events'])}")
    print(f"  matched: {stats['event_matched']}  pine-only: {stats['event_missing']}")
    if stats["event_detail"]:
        print("  first pine-only plan events:", stats["event_detail"])
    print()
    print(f"{'field':22} {'compared':>9} {'mismatch':>9} {'max|d|':>12}  first-bad(sample pine vs mine)")
    for diff in diffs.values():
        sample = ""
        if diff.samples:
            t, pine_v, mine_v = diff.samples[0]
            sample = f"t={t} pine={pine_v} mine={mine_v}"
        print(
            f"{diff.name:22} {diff.compared:>9} {diff.mismatched:>9} "
            f"{diff.max_abs:>12.6g}  {sample}"
        )
    total_bad = sum(d.mismatched for d in diffs.values()) + stats["missing"] + len(stats["extra"])
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
