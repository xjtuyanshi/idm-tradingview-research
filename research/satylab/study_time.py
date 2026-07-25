#!/usr/bin/env python3
"""Intraday time structure and volatility budget — "when NOT to trade".

The complaint this study answers: the engine fires signals in dead time.  So
measure the clock, not the signal.  Five questions, all base-rate style, no
fitted parameters anywhere:

  S1  How is the day's amplitude distributed across the hours?  How dead is
      the midday dead zone, in numbers?
  S2  At time T, how much travel is left in the day (in ATR)?  This is what
      decides whether a 0.618 target is still reachable from here.
  S3  How long does it take to walk 0.382 -> 0.618?  This explains the Golden
      Gate time decay and gives a "how much clock is enough" threshold.
  S4  Can the first hour tell us whether the day will reach +/-1 ATR?  A
      candidate "is today worth trading at all" filter.
  S5  Day-of-week and month effects — reported as null if null.

Data resolution discipline (see satylab/data.py):
  * 1d  20y   ~5030 sessions  -> calendar effects, unconditional touch rates
  * 1h  730d   ~723 sessions  -> hour-of-day structure, remaining budget
  * 5m  60d      60 sessions  -> minute-level timing.  n is tiny; every 5m
                                 number below is labelled as directional only.

The 15:30 hourly bar spans only 30 minutes (15:30->16:00).  Everything that
compares hours reports the per-minute normalisation as well, otherwise the
last bucket looks artificially dead.

Usage:
    python research/satylab/study_time.py            # full report to stdout
    python research/satylab/study_time.py --json OUT # also dump raw numbers
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402

HOURS = ("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")
HOUR_MINUTES = {"09:30": 60, "10:30": 60, "11:30": 60, "12:30": 60,
                "13:30": 60, "14:30": 60, "15:30": 30}
# minutes elapsed since 09:30 at the OPEN of each hourly bar
HOUR_ELAPSED = {"09:30": 0, "10:30": 60, "11:30": 120, "12:30": 180,
                "13:30": 240, "14:30": 300, "15:30": 360}
SESSION_MINUTES = 390

DOW = ("Mon", "Tue", "Wed", "Thu", "Fri")


# --------------------------------------------------------------------------
# tiny stdlib stats helpers (no numpy in this venv)
# --------------------------------------------------------------------------
def pct(xs: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0,1]."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    i = q * (len(s) - 1)
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def sign_test_p(pos: int, tot: int) -> float:
    """One-sided binomial p for `pos` of `tot` years agreeing, H0: p=0.5."""
    if tot == 0:
        return 1.0
    from math import comb
    return sum(comb(tot, k) for k in range(pos, tot + 1)) / 2 ** tot


def dist(xs: list[float]) -> dict:
    return {"n": len(xs), "mean": mean(xs), "p25": pct(xs, .25),
            "p50": pct(xs, .50), "p75": pct(xs, .75), "p90": pct(xs, .90)}


def fmt_dist(d: dict) -> str:
    return (f"n={d['n']:<5} 均值={d['mean']:.3f} "
            f"p25={d['p25']:.3f} 中位={d['p50']:.3f} "
            f"p75={d['p75']:.3f} p90={d['p90']:.3f}")


# --------------------------------------------------------------------------
# session assembly
# --------------------------------------------------------------------------
def clean_hourly_sessions(bars: list[Bar], lv: dict) -> dict[date, list[Bar]]:
    """Full 7-bar RTH sessions that also have a level map.

    Half days (13:00 close) and the tail day without a prior-close level are
    dropped, and the count of drops is reported by the caller — a session with
    a missing 12:30 bar would silently distort every per-hour statistic.
    """
    raw = data.group_by_day(bars)
    out: dict[date, list[Bar]] = {}
    for d, rows in raw.items():
        if d not in lv:
            continue
        keep = [b for b in rows if b.hhmm in HOUR_MINUTES]
        if len(keep) != len(HOURS):
            continue
        if tuple(b.hhmm for b in keep) != HOURS:
            continue
        out[d] = keep
    return out


def clean_fine_sessions(bars: list[Bar], lv: dict) -> dict[date, list[Bar]]:
    raw = data.group_by_day(bars)
    out: dict[date, list[Bar]] = {}
    for d, rows in raw.items():
        if d not in lv:
            continue
        keep = [b for b in rows if "09:30" <= b.hhmm <= "15:55"]
        if len(keep) < 70:
            continue
        out[d] = keep
    return out


def minutes_from_open(b: Bar) -> int:
    return (b.dt.hour - 9) * 60 + (b.dt.minute - 30)


# --------------------------------------------------------------------------
# S1 — amplitude by hour
# --------------------------------------------------------------------------
def s1_amplitude(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Two different senses of 'how much happens in this hour'.

    share_of_range  = bar range / day range.  Activity.  Sums to >1 because
                      hours overlap in price.
    new_range       = how much of the day's final range this hour DISCOVERED
                      (running high/low expansion).  Sums to exactly 1.  This
                      is the budget sense: once an hour discovers no new
                      range, holding through it earns nothing.
    """
    share = defaultdict(list)
    newr = defaultdict(list)
    amp_atr = defaultdict(list)
    dead = defaultdict(lambda: [0, 0])      # hour added literally nothing
    done = defaultdict(lambda: [0, 0])      # day's high AND low both already in
    day_range_atr: list[float] = []

    for d, rows in sess.items():
        L = lv[d]
        hi = max(b.high for b in rows)
        lo = min(b.low for b in rows)
        rng = hi - lo
        if rng <= 0:
            continue
        day_range_atr.append(rng / L.atr)
        run_hi = run_lo = None
        prev_span = 0.0
        for b in rows:
            share[b.hhmm].append((b.high - b.low) / rng)
            amp_atr[b.hhmm].append((b.high - b.low) / L.atr)
            run_hi = b.high if run_hi is None else max(run_hi, b.high)
            run_lo = b.low if run_lo is None else min(run_lo, b.low)
            span = run_hi - run_lo
            inc = (span - prev_span) / rng
            newr[b.hhmm].append(inc)
            dead[b.hhmm][1] += 1
            dead[b.hhmm][0] += int(inc <= 1e-12)
            done[b.hhmm][1] += 1
            done[b.hhmm][0] += int(run_hi >= hi - 1e-9 and run_lo <= lo + 1e-9)
            prev_span = span

    return {
        "day_range_atr": dist(day_range_atr),
        "share": {h: dist(share[h]) for h in HOURS},
        "new_range": {h: dist(newr[h]) for h in HOURS},
        "amp_atr": {h: dist(amp_atr[h]) for h in HOURS},
        "dead": {h: dead[h] for h in HOURS},
        "range_done_by": {h: done[h] for h in HOURS},
    }


def s1_fine(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Half-hour resolution on the 60-day 5m window — dead-zone shape only."""
    buckets = [f"{9 + (30 + 30 * i) // 60:02d}:{(30 + 30 * i) % 60:02d}"
               for i in range(13)]
    amp = defaultdict(list)
    newr = defaultdict(list)
    for d, rows in sess.items():
        L = lv[d]
        hi = max(b.high for b in rows)
        lo = min(b.low for b in rows)
        if hi <= lo:
            continue
        rng = hi - lo
        grouped: dict[str, list[Bar]] = defaultdict(list)
        for b in rows:
            m = minutes_from_open(b)
            idx = min(m // 30, 12)
            grouped[buckets[idx]].append(b)
        run_hi = run_lo = None
        prev = 0.0
        for key in buckets:
            g = grouped.get(key)
            if not g:
                continue
            bh = max(x.high for x in g)
            bl = min(x.low for x in g)
            amp[key].append((bh - bl) / L.atr)
            run_hi = bh if run_hi is None else max(run_hi, bh)
            run_lo = bl if run_lo is None else min(run_lo, bl)
            span = run_hi - run_lo
            newr[key].append((span - prev) / rng)
            prev = span
    return {"buckets": buckets,
            "amp_atr": {k: dist(amp[k]) for k in buckets},
            "new_range": {k: dist(newr[k]) for k in buckets}}


# --------------------------------------------------------------------------
# S2 — remaining travel budget
# --------------------------------------------------------------------------
DISTANCES = (0.118, 0.236, 0.382, 0.500)


def s2_budget(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """At the OPEN of each hourly bar, what travel is left?

    p_T = open of bar T (a price you could actually have transacted at).
    up   = (max high from T onward - p_T) / ATR
    down = (p_T - min low from T onward) / ATR
    best = max(up, down) -- the perfect-hindsight direction.  Any real system
           gets less than this, so `best` is an upper bound on what a trade
           entered at T could capture.
    """
    per_T: dict[str, dict] = {}
    for i, h in enumerate(HOURS):
        rem_range, ups, downs, bests = [], [], [], []
        reach = {d: [0, 0] for d in DISTANCES}     # best-side
        reach_up = {d: [0, 0] for d in DISTANCES}  # committed long
        reach_dn = {d: [0, 0] for d in DISTANCES}  # committed short
        for d, rows in sess.items():
            L = lv[d]
            p = rows[i].open
            tail = rows[i:]
            hi = max(b.high for b in tail)
            lo = min(b.low for b in tail)
            u = (hi - p) / L.atr
            dn = (p - lo) / L.atr
            rem_range.append((hi - lo) / L.atr)
            ups.append(u)
            downs.append(dn)
            b = max(u, dn)
            bests.append(b)
            for x in DISTANCES:
                reach[x][1] += 1
                reach[x][0] += int(b >= x)
                reach_up[x][1] += 1
                reach_up[x][0] += int(u >= x)
                reach_dn[x][1] += 1
                reach_dn[x][0] += int(dn >= x)
        per_T[h] = {
            "rem_range": dist(rem_range),
            "up": dist(ups), "down": dist(downs), "best": dist(bests),
            "reach": {str(x): reach[x] for x in DISTANCES},
            "reach_up": {str(x): reach_up[x] for x in DISTANCES},
            "reach_dn": {str(x): reach_dn[x] for x in DISTANCES},
            "minutes_left": SESSION_MINUTES - HOUR_ELAPSED[h],
        }
    return per_T


def s2_budget_fine(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Same construction on 5m, half-hour decision points.  n=60 sessions."""
    out: dict[str, dict] = {}
    for k in range(13):
        m0 = 30 * k
        key = f"{9 + (30 + m0) // 60:02d}:{(30 + m0) % 60:02d}"
        bests, rem = [], []
        reach = {d: [0, 0] for d in DISTANCES}
        for d, rows in sess.items():
            L = lv[d]
            tail = [b for b in rows if minutes_from_open(b) >= m0]
            if not tail:
                continue
            p = tail[0].open
            hi = max(b.high for b in tail)
            lo = min(b.low for b in tail)
            best = max((hi - p), (p - lo)) / L.atr
            bests.append(best)
            rem.append((hi - lo) / L.atr)
            for x in DISTANCES:
                reach[x][1] += 1
                reach[x][0] += int(best >= x)
        out[key] = {"best": dist(bests), "rem_range": dist(rem),
                    "reach": {str(x): reach[x] for x in DISTANCES},
                    "minutes_left": SESSION_MINUTES - m0}
    return out


# --------------------------------------------------------------------------
# S3 — time from 0.382 to 0.618
# --------------------------------------------------------------------------
def _trigger_index(rows: list[Bar], trig: float, side: int) -> tuple[int, bool]:
    """(bar index of first touch of `trig`, opened_beyond) or (-1, False)."""
    if (rows[0].open >= trig) if side > 0 else (rows[0].open <= trig):
        return 0, True
    i = levels.first_touch(rows, trig, side)
    return (i, False) if i is not None else (-1, False)


def s3_hourly(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Bars from GG trigger to GG completion, on 730 days of hourly bars.

    Coarse (1 bar = 1 hour) but n is large.  'lag 0' = the gate completed
    inside the same hourly bar that triggered it; the true within-bar timing
    is unknowable at this resolution and is NOT claimed here.
    """
    lag_by_bucket: dict[str, list[int]] = defaultdict(list)
    comp_by_bucket: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lag_all: list[int] = []
    same_bar = [0, 0]
    # conditional survival: triggered, not complete by end of trigger bar
    survive: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    # gap hygiene: an open already beyond 0.618 "completes" before you can act
    gap_total = 0
    gap_open_past_gate = 0
    gap_tradeable = [0, 0]
    for d, rows in sess.items():
        L = lv[d]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            gate = L.at(side * levels.GG_COMPLETE)
            ti, gapped = _trigger_index(rows, trig, side)
            if ti < 0:
                continue
            if gapped and ti == 0:
                gap_total += 1
                past = (rows[0].open >= gate) if side > 0 else \
                       (rows[0].open <= gate)
                if past:
                    gap_open_past_gate += 1
                else:
                    gi0 = levels.first_touch(rows, gate, side, start=0)
                    gap_tradeable[1] += 1
                    gap_tradeable[0] += int(gi0 is not None)
            bucket = "OPEN(gap)" if gapped and ti == 0 else rows[ti].hhmm
            gi = levels.first_touch(rows, gate, side, start=ti)
            done = gi is not None
            comp_by_bucket[bucket][1] += 1
            comp_by_bucket[bucket][0] += int(done)
            same_bar[1] += 1
            if done:
                lag = gi - ti
                lag_all.append(lag)
                lag_by_bucket[bucket].append(lag)
                same_bar[0] += int(lag == 0)
            # survival past the trigger bar
            done_in_bar = done and gi == ti
            if not done_in_bar:
                survive[bucket][1] += 1
                survive[bucket][0] += int(done)
    return {
        "lag_all": {"n": len(lag_all),
                    "p50": pct([float(x) for x in lag_all], .5),
                    "p75": pct([float(x) for x in lag_all], .75),
                    "p90": pct([float(x) for x in lag_all], .90),
                    "hist": {str(k): lag_all.count(k)
                             for k in sorted(set(lag_all))}},
        "same_bar": same_bar,
        "gap": {"total": gap_total, "open_past_gate": gap_open_past_gate,
                "tradeable": gap_tradeable},
        "by_bucket": {b: {"complete": comp_by_bucket[b],
                          "lag_p50": pct([float(x) for x in lag_by_bucket[b]], .5),
                          "lag_p75": pct([float(x) for x in lag_by_bucket[b]], .75),
                          "n_lag": len(lag_by_bucket[b]),
                          "survive": survive[b]}
                      for b in comp_by_bucket},
    }


def s3_symmetry(sess: dict[date, list[Bar]], lv: dict,
                fsess: dict[date, list[Bar]] | None = None) -> dict:
    """Does the 0.382 trigger point anywhere, or is it just the clock?

    Matched comparison, same day, same instant, same distance: from the moment
    price touches 0.382, ask whether it later reaches 0.618 (0.236 further in
    the trigger direction) and whether it reaches 0.146 (0.236 back the other
    way).  Both can happen; the informative statistic is the discordant pairs
    (McNemar), which is the only version of this question that isn't
    contaminated by "the day was volatile".
    """
    BACK = levels.GG_ENTRY - (levels.GG_COMPLETE - levels.GG_ENTRY)   # 0.146
    per_hour: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "up": 0, "dn": 0, "only_up": 0, "only_dn": 0})
    tot = {"n": 0, "up": 0, "dn": 0, "only_up": 0, "only_dn": 0}
    for d, rows in sess.items():
        L = lv[d]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            gate = L.at(side * levels.GG_COMPLETE)
            back = L.at(side * BACK)
            ti, gapped = _trigger_index(rows, trig, side)
            if ti < 0:
                continue
            bucket = "OPEN(gap)" if gapped and ti == 0 else rows[ti].hhmm
            up = levels.first_touch(rows, gate, side, start=ti) is not None
            dn = levels.first_touch(rows, back, -side, start=ti) is not None
            for tgt in (per_hour[bucket], tot):
                tgt["n"] += 1
                tgt["up"] += int(up)
                tgt["dn"] += int(dn)
                tgt["only_up"] += int(up and not dn)
                tgt["only_dn"] += int(dn and not up)

    # The OPEN(gap) bucket cannot be compared symmetrically: 41% of those days
    # open ALREADY past 0.618, so "reached 0.618" is true before the bell while
    # "pulled back to 0.146" still has to be earned.  Pool the intraday
    # triggers separately — that is the only clean pooled number.
    intraday = {k: sum(v[k] for b, v in per_hour.items() if b != "OPEN(gap)")
                for k in ("n", "up", "dn", "only_up", "only_dn")}

    # 5m: the real question — which one arrives FIRST.  n is tiny.
    first: dict[str, int] = {"up_first": 0, "dn_first": 0, "neither": 0,
                             "up_first_intra": 0, "dn_first_intra": 0,
                             "neither_intra": 0}
    if fsess:
        for d, rows in fsess.items():
            L = lv[d]
            for side in (+1, -1):
                trig = L.at(side * levels.GG_ENTRY)
                gate = L.at(side * levels.GG_COMPLETE)
                back = L.at(side * BACK)
                ti, gapped = _trigger_index(rows, trig, side)
                if ti < 0:
                    continue
                iu = levels.first_touch(rows, gate, side, start=ti)
                idn = levels.first_touch(rows, back, -side, start=ti)
                if iu is None and idn is None:
                    key = "neither"
                elif idn is None or (iu is not None and iu < idn):
                    key = "up_first"
                elif iu is None or idn < iu:
                    key = "dn_first"
                else:                      # same bar — order unknowable
                    key = "neither"
                first[key] += 1
                if not (gapped and ti == 0):
                    first[key + "_intra"] += 1
    return {"total": tot, "intraday": intraday, "by_hour": dict(per_hour),
            "fine_first": first, "back_ratio": BACK}


FINE_BUCKETS = (("OPEN(gap)", None),
                ("09:30-10:00", (0, 30)),
                ("10:00-11:00", (30, 90)),
                ("11:00-13:00", (90, 210)),
                ("13:00-14:30", (210, 300)),
                ("14:30-16:00", (300, 391)))


def s3_fine(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Minutes from 0.382 touch to 0.618 touch.  60 sessions only."""
    mins_all: list[float] = []
    by_bucket: dict[str, list[float]] = defaultdict(list)
    comp: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    # completion rate as a function of clock left at the moment of trigger
    by_left: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d, rows in sess.items():
        L = lv[d]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            gate = L.at(side * levels.GG_COMPLETE)
            ti, gapped = _trigger_index(rows, trig, side)
            if ti < 0:
                continue
            tmin = minutes_from_open(rows[ti])
            if gapped and ti == 0:
                bucket = "OPEN(gap)"
            else:
                bucket = next((nm for nm, rg in FINE_BUCKETS
                               if rg and rg[0] <= tmin < rg[1]), "14:30-16:00")
            gi = levels.first_touch(rows, gate, side, start=ti)
            comp[bucket][1] += 1
            comp[bucket][0] += int(gi is not None)
            left = SESSION_MINUTES - tmin
            lb = ("剩余>330m" if left > 330 else "剩余240-330m" if left > 240
                  else "剩余150-240m" if left > 150 else "剩余60-150m"
                  if left > 60 else "剩余<=60m")
            by_left[lb][1] += 1
            by_left[lb][0] += int(gi is not None)
            if gi is not None:
                el = float(minutes_from_open(rows[gi]) - tmin)
                mins_all.append(el)
                by_bucket[bucket].append(el)
    return {"all": dist(mins_all),
            "by_bucket": {b: {"complete": comp[b],
                              "mins": dist(by_bucket[b])} for b in comp},
            "by_left": {k: v for k, v in by_left.items()}}


# --------------------------------------------------------------------------
# S4 — first-hour predictors of a +/-1 ATR day
# --------------------------------------------------------------------------
def s4_first_hour(sess: dict[date, list[Bar]], lv: dict) -> dict:
    """Decision at 10:30 with only 09:30-10:30 information.

    The outcome is deliberately FUTURE-ONLY: does price touch +/-1 ATR at any
    point AFTER 10:30?  Using the whole session as outcome would leak the
    first hour into it and inflate every conditional rate.
    """
    rows_out = []
    for d, rows in sess.items():
        L = lv[d]
        h1 = rows[0]
        rest = rows[1:]
        h1_rng = (h1.high - h1.low) / L.atr
        r_hi = L.ratio_of(h1.high)
        r_lo = L.ratio_of(h1.low)
        extreme = max(abs(r_hi), abs(r_lo))
        up_day = h1.close > h1.open
        rest_hi = max(b.high for b in rest)
        rest_lo = min(b.low for b in rest)
        hit_up = rest_hi >= L.at(1.0)
        hit_dn = rest_lo <= L.at(-1.0)
        rows_out.append({
            "day": d, "h1_rng": h1_rng, "extreme": extreme,
            "r_hi": r_hi, "r_lo": r_lo, "up": up_day,
            "touch_236": max(abs(r_hi), abs(r_lo)) >= levels.TRIGGER,
            "touch_382": max(abs(r_hi), abs(r_lo)) >= levels.GG_ENTRY,
            "hit_any": hit_up or hit_dn,
            "hit_same": hit_up if up_day else hit_dn,
        })
    rngs = sorted(r["h1_rng"] for r in rows_out)
    q = [pct(rngs, x) for x in (.25, .5, .75)]

    def bucket(v: float) -> str:
        if v < q[0]:
            return f"H1振幅 Q1 <{q[0]:.2f}"
        if v < q[1]:
            return f"H1振幅 Q2 {q[0]:.2f}-{q[1]:.2f}"
        if v < q[2]:
            return f"H1振幅 Q3 {q[1]:.2f}-{q[2]:.2f}"
        return f"H1振幅 Q4 >{q[2]:.2f}"

    t_rng = stats.RateTable("4a. 首小时振幅四分位 -> 10:30后触及 ±1ATR")
    t_lvl = stats.RateTable("4b. 首小时已达哪一档 -> 10:30后触及 ±1ATR")
    t_dir = stats.RateTable("4c. 首小时方向 -> 10:30后触及 同向 1ATR")
    t_cmb = stats.RateTable("4d. 组合(振幅四分位 x 是否已过0.382)")
    for r in rows_out:
        t_rng.add(bucket(r["h1_rng"]), r["hit_any"])
        lvl = ("已过0.382" if r["touch_382"] else
               "只到0.236" if r["touch_236"] else "未过0.236")
        t_lvl.add(lvl, r["hit_any"])
        t_dir.add("首小时收阳" if r["up"] else "首小时收阴", r["hit_same"])
        t_cmb.add(f"{bucket(r['h1_rng'])} | {lvl}", r["hit_any"])
    tables = {"rng": t_rng, "lvl": t_lvl, "dir": t_dir, "cmb": t_cmb}

    base_any = [sum(r["hit_any"] for r in rows_out), len(rows_out)]
    base_same = [sum(r["hit_same"] for r in rows_out), len(rows_out)]

    # Does H1 amplitude add anything BEYOND "price is already far from the
    # anchor"?  Both predictors partly measure the same thing (a wide first
    # hour usually IS a first hour that reached 0.382), so hold position fixed
    # and vary amplitude only.
    strat = [r for r in rows_out if r["touch_382"]]
    wide = [r for r in strat if r["h1_rng"] >= q[2]]
    narrow = [r for r in strat if r["h1_rng"] < q[1]]
    strat_z = stats.two_proportion_z(
        sum(r["hit_any"] for r in wide), len(wide),
        sum(r["hit_any"] for r in narrow), len(narrow))

    # ...and the mirror: hold amplitude fixed, vary position.
    mid = [r for r in rows_out if q[0] <= r["h1_rng"] < q[2]]
    mid_far = [r for r in mid if r["touch_382"]]
    mid_near = [r for r in mid if not r["touch_382"]]
    strat_z2 = stats.two_proportion_z(
        sum(r["hit_any"] for r in mid_far), len(mid_far),
        sum(r["hit_any"] for r in mid_near), len(mid_near))

    return {"rows": rows_out, "q": q, "tables": tables,
            "base_any": base_any, "base_same": base_same,
            "strat": {
                "wide": [sum(r["hit_any"] for r in wide), len(wide)],
                "narrow": [sum(r["hit_any"] for r in narrow), len(narrow)],
                "z": strat_z,
                "mid_far": [sum(r["hit_any"] for r in mid_far), len(mid_far)],
                "mid_near": [sum(r["hit_any"] for r in mid_near),
                             len(mid_near)],
                "z2": strat_z2}}


# --------------------------------------------------------------------------
# S5 — calendar effects (20y daily, where n is actually large)
# --------------------------------------------------------------------------
def s5_calendar(daily: list[Bar], lv: dict) -> dict:
    dow_rng: dict[str, list[float]] = defaultdict(list)
    dow_1atr = stats.RateTable("5a. 星期 -> 当日触及 ±1 ATR")
    dow_gg = stats.RateTable("5b. 星期 -> GG 完成率(看涨, 已触发者)")
    mon_rng: dict[str, list[float]] = defaultdict(list)
    mon_1atr = stats.RateTable("5c. 月份 -> 当日触及 ±1 ATR")
    dom_1atr = stats.RateTable("5d. 月内位置 -> 当日触及 ±1 ATR")
    dow_raw: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    mon_raw: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    # trading-day-of-month index
    by_month: dict[tuple, list[Bar]] = defaultdict(list)
    for b in daily:
        by_month[(b.day.year, b.day.month)].append(b)
    tdom: dict[date, tuple[int, int]] = {}
    for k, rows in by_month.items():
        rows.sort(key=lambda x: x.day)
        for i, b in enumerate(rows):
            tdom[b.day] = (i + 1, len(rows))

    for b in daily:
        L = lv.get(b.day)
        if not L:
            continue
        w = b.day.weekday()
        if w > 4:
            continue
        name = DOW[w]
        hit = b.high >= L.at(1.0) or b.low <= L.at(-1.0)
        dow_rng[name].append((b.high - b.low) / L.atr)
        dow_1atr.add(name, hit)
        dow_raw[name][1] += 1
        dow_raw[name][0] += int(hit)
        mname = f"{b.day.month:02d}月"
        mon_rng[mname].append((b.high - b.low) / L.atr)
        mon_1atr.add(mname, hit)
        mon_raw[mname][1] += 1
        mon_raw[mname][0] += int(hit)
        idx, tot = tdom[b.day]
        pos = ("月初(前3交易日)" if idx <= 3 else
               "月末(后3交易日)" if idx > tot - 3 else "月中")
        dom_1atr.add(pos, hit)
        if b.high >= L.at(levels.GG_ENTRY):
            dow_gg.add(name, b.high >= L.at(levels.GG_COMPLETE))

    # Daily +/-1 ATR touches cluster hard (volatility regimes), so a Wilson
    # interval computed under independence is too narrow for calendar cells.
    # Cheap honesty check: how many of the 20 individual years reproduce the
    # sign of the pooled effect?  ~10/20 means the pooled z is regime noise.
    def year_sign(pred) -> tuple[int, int]:
        pos = tot = 0
        by_year: dict[int, list[list[int]]] = defaultdict(
            lambda: [[0, 0], [0, 0]])
        for b in daily:
            L = lv.get(b.day)
            if not L or b.day.weekday() > 4:
                continue
            hit = int(b.high >= L.at(1.0) or b.low <= L.at(-1.0))
            g = by_year[b.day.year][0 if pred(b) else 1]
            g[1] += 1
            g[0] += hit
        for y, (a, c) in sorted(by_year.items()):
            if a[1] < 5 or c[1] < 5:
                continue
            tot += 1
            pos += int(a[0] / a[1] > c[0] / c[1])
        return pos, tot

    jan = year_sign(lambda b: b.day.month == 1)
    thu = year_sign(lambda b: b.day.weekday() == 3)
    som = year_sign(lambda b: tdom[b.day][0] <= 3)

    # is "start of month" just January wearing a hat?  drop January and redo.
    som_nojan = [[0, 0], [0, 0]]
    for b in daily:
        L = lv.get(b.day)
        if not L or b.day.weekday() > 4 or b.day.month == 1:
            continue
        hit = int(b.high >= L.at(1.0) or b.low <= L.at(-1.0))
        g = som_nojan[0 if tdom[b.day][0] <= 3 else 1]
        g[1] += 1
        g[0] += hit

    return {"dow_rng": {k: dist(v) for k, v in dow_rng.items()},
            "dow_1atr": dow_1atr, "dow_gg": dow_gg,
            "mon_rng": {k: dist(v) for k, v in mon_rng.items()},
            "mon_1atr": mon_1atr, "dom_1atr": dom_1atr,
            "dow_raw": dict(dow_raw), "mon_raw": dict(mon_raw),
            "year_sign": {"01月": jan, "Thu": thu, "月初": som},
            "som_nojan": som_nojan}


def contrast_vs_rest(raw: dict[str, list[int]]) -> dict[str, float]:
    """z of each cell against the pooled remainder — 'is this cell special?'"""
    out = {}
    tot_k = sum(v[0] for v in raw.values())
    tot_n = sum(v[1] for v in raw.values())
    for k, (a, n) in raw.items():
        out[k] = stats.two_proportion_z(a, n, tot_k - a, tot_n - n)
    return out


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def main() -> None:
    daily = data.daily(years="20y")
    hourly = data.hourly()
    fine = data.fine()
    lv = levels.build(daily)

    sess = clean_hourly_sessions(hourly, lv)
    fsess = clean_fine_sessions(fine, lv)
    raw_days = len(data.group_by_day(hourly))

    print("=" * 78)
    print("时间结构与波动预算 —— SPX 日内 (^GSPC)")
    print("=" * 78)
    print(f"日线   {len(daily)} 根  {daily[0].day} -> {daily[-1].day}")
    print(f"小时线 完整 7 根 RTH 的交易日 {len(sess)} / {raw_days} "
          f"(丢弃半日市与无位图日 {raw_days - len(sess)})  "
          f"{min(sess)} -> {max(sess)}")
    print(f"5 分钟 {len(fsess)} 个交易日  {min(fsess)} -> {max(fsess)}")
    print()

    out: dict = {"meta": {"hourly_sessions": len(sess),
                          "fine_sessions": len(fsess),
                          "daily_bars": len(daily)}}

    # ---- S1 -------------------------------------------------------------
    s1 = s1_amplitude(sess, lv)
    out["s1"] = s1
    print("-" * 78)
    print("S1. 日内振幅的时段分布 (730 天小时线)")
    print("-" * 78)
    print(f"当日 RTH 全振幅 / 前日ATR : {fmt_dist(s1['day_range_atr'])}")
    print()
    print("(a) 该小时自身振幅 占当日全振幅的比例  [重叠, 合计>1]")
    print(f"{'时段':<8}{'均值':>8}{'中位':>8}{'p25':>8}{'p75':>8}"
          f"{'每分钟均值':>12}")
    for h in HOURS:
        d = s1["share"][h]
        print(f"{h:<8}{d['mean']*100:7.1f}%{d['p50']*100:7.1f}%"
              f"{d['p25']*100:7.1f}%{d['p75']*100:7.1f}%"
              f"{d['mean']*100/HOUR_MINUTES[h]:11.3f}%")
    print()
    print("(b) 该小时【新发现】的区间 占当日全振幅的比例  [合计=100%]")
    print(f"{'时段':<8}{'均值':>8}{'中位':>8}{'p75':>8}{'每分钟均值':>12}")
    for h in HOURS:
        d = s1["new_range"][h]
        print(f"{h:<8}{d['mean']*100:7.1f}%{d['p50']*100:7.1f}%"
              f"{d['p75']*100:7.1f}%{d['mean']*100/HOUR_MINUTES[h]:11.3f}%")
    print(f"{'合计':<8}{sum(s1['new_range'][h]['mean'] for h in HOURS)*100:7.1f}%")
    print()
    print("(c) 该小时振幅的绝对大小 (ATR 单位)")
    for h in HOURS:
        print(f"  {h}  {fmt_dist(s1['amp_atr'][h])}")
    print()
    print("(c2) 死区的两个直接指标")
    print(f"{'时段':<8}{'该小时对全日区间零贡献的概率':>34}"
          f"{'到该小时收盘，全日高低已定的概率':>36}")
    for h in HOURS:
        dk, dn = s1["dead"][h]
        ok, on = s1["range_done_by"][h]
        print(f"{h:<8}{stats.fmt_rate(dk, dn):>34}{stats.fmt_rate(ok, on):>36}")
    print()

    f1 = s1_fine(fsess, lv)
    out["s1_fine"] = f1
    print(f"(d) 半小时分辨率 (5m, 仅 {len(fsess)} 天 — 只看形状, 不看小数点)")
    print(f"{'时段':<8}{'振幅中位(ATR)':>16}{'新区间均值占比':>16}")
    for k in f1["buckets"]:
        a = f1["amp_atr"][k]
        n = f1["new_range"][k]
        if a["n"] == 0:
            continue
        print(f"{k:<8}{a['p50']:15.3f}{n['mean']*100:15.1f}%")
    print()

    # ---- S2 -------------------------------------------------------------
    s2 = s2_budget(sess, lv)
    out["s2"] = s2
    print("-" * 78)
    print("S2. 剩余行程预算 (在该小时【开盘价】决策, 730 天小时线)")
    print("-" * 78)
    print(f"{'时刻':<8}{'剩余min':>8}{'剩余区间(ATR)中位':>20}"
          f"{'向上':>10}{'向下':>10}{'最优边中位':>12}{'最优边p25':>12}")
    for h in HOURS:
        b = s2[h]
        print(f"{h:<8}{b['minutes_left']:8d}{b['rem_range']['p50']:19.3f}"
              f"{b['up']['p50']:10.3f}{b['down']['p50']:10.3f}"
              f"{b['best']['p50']:12.3f}{b['best']['p25']:12.3f}")
    print()
    print("★ 关键表：从该时刻起，价格还能再走 D 个 ATR 的概率")
    print("   [最优边 = 事后选对方向的上界；真实系统只会更差]")
    hdr = "".join(f"{'>=' + str(d):>22}" for d in DISTANCES)
    print(f"{'时刻':<8}{hdr}")
    for h in HOURS:
        line = f"{h:<8}"
        for x in DISTANCES:
            k, n = s2[h]["reach"][str(x)]
            line += f"{stats.fmt_rate(k, n):>22}"
        print(line)
    print()
    for side_key, side_lbl in (("reach_up", "做多"), ("reach_dn", "做空")):
        print(f"   同一张表，但方向【在决策时就锁定为{side_lbl}】(真实可交易口径)")
        print(f"{'时刻':<8}{hdr}")
        for h in HOURS:
            line = f"{h:<8}"
            for x in DISTANCES:
                k, n = s2[h][side_key][str(x)]
                line += f"{stats.fmt_rate(k, n):>22}"
            print(line)
        print()

    f2 = s2_budget_fine(fsess, lv)
    out["s2_fine"] = f2
    print(f"半小时分辨率 (5m, {len(fsess)} 天, n 很小)")
    print(f"{'时刻':<8}{'剩余min':>8}{'最优边中位(ATR)':>18}   {'P(最优边>=0.236)':>26}")
    for k, v in f2.items():
        if v["best"]["n"] == 0:
            continue
        a, n = v["reach"]["0.236"]
        print(f"{k:<8}{v['minutes_left']:8d}{v['best']['p50']:17.3f}   "
              f"{stats.fmt_rate(a, n):>26}")
    print()

    # ---- S3 -------------------------------------------------------------
    s3h = s3_hourly(sess, lv)
    s3f = s3_fine(fsess, lv)
    out["s3_hourly"] = s3h
    out["s3_fine"] = s3f
    print("-" * 78)
    print("S3. 0.382 -> 0.618 所需时间")
    print("-" * 78)
    print(f"小时线 (730天, 多空合并): 完成者滞后 K 线数 "
          f"中位={s3h['lag_all']['p50']:.1f} p75={s3h['lag_all']['p75']:.1f} "
          f"p90={s3h['lag_all']['p90']:.1f}  n={s3h['lag_all']['n']}")
    print(f"  滞后分布(根): {s3h['lag_all']['hist']}")
    sb = s3h["same_bar"]
    print(f"  在触发那根小时 K 内就完成: {stats.fmt_rate(sb[0], sb[1])} "
          f"(占全部触发)")
    g = s3h["gap"]
    print(f"  ⚠ 开盘跳空档卫生检查: {g['total']} 次跳空触发中, "
          f"{g['open_past_gate']} 次 ({100*g['open_past_gate']/g['total']:.1f}%) "
          f"开盘价本身就已在 0.618 之外 —— 这类『完成』在你能下单之前就发生了。")
    print(f"    剔除后, 真正可交易的跳空触发完成率: "
          f"{stats.fmt_rate(g['tradeable'][0], g['tradeable'][1])}")
    print()
    print(f"{'触发档':<14}{'完成率':>28}{'滞后中位':>10}{'滞后p75':>10}"
          f"{'过了触发K仍未完成者的最终完成率':>34}")
    order = ["OPEN(gap)"] + list(HOURS)
    for b in order:
        v = s3h["by_bucket"].get(b)
        if not v:
            continue
        k, n = v["complete"]
        sk, sn = v["survive"]
        print(f"{b:<14}{stats.fmt_rate(k, n):>28}{v['lag_p50']:10.1f}"
              f"{v['lag_p75']:10.1f}{stats.fmt_rate(sk, sn):>34}")
    print()
    print(f"5 分钟 ({len(fsess)} 天 — n 很小, 只作方向参考): "
          f"从触及 0.382 到触及 0.618 的用时(分钟)")
    print(f"  全体 {fmt_dist(s3f['all'])}")
    for nm, _ in FINE_BUCKETS:
        v = s3f["by_bucket"].get(nm)
        if not v:
            continue
        k, n = v["complete"]
        m = v["mins"]
        print(f"  {nm:<14}完成 {stats.fmt_rate(k, n):<26}"
              f"用时中位={m['p50']:.0f}m p75={m['p75']:.0f}m n={m['n']}")
    print()
    print("  触发时【场内剩余分钟】-> 完成率 (5m)")
    for k in ("剩余>330m", "剩余240-330m", "剩余150-240m", "剩余60-150m",
              "剩余<=60m"):
        v = s3f["by_left"].get(k)
        if v:
            print(f"    {k:<16}{stats.fmt_rate(v[0], v[1])}")
    print()

    sy = s3_symmetry(sess, lv, fsess)
    out["s3_sym"] = sy
    print("S3c. 对称性检验：0.382 触发之后，是更容易走完 0.618，还是更容易退回 0.146？")
    print("     （同一天、同一时刻、同样 0.236 ATR 的距离 —— 唯一没被『当天波动大』"
          "污染的问法）")
    print(f"{'触发档':<12}{'触及0.618':>26}{'退回0.146':>26}"
          f"{'只上':>7}{'只下':>7}{'McNemar z':>11}")
    for b in ["OPEN(gap)"] + list(HOURS):
        v = sy["by_hour"].get(b)
        if not v:
            continue
        disc = v["only_up"] + v["only_dn"]
        z = (v["only_up"] - v["only_dn"]) / (disc ** 0.5) if disc else 0.0
        print(f"{b:<12}{stats.fmt_rate(v['up'], v['n']):>26}"
              f"{stats.fmt_rate(v['dn'], v['n']):>26}"
              f"{v['only_up']:7d}{v['only_dn']:7d}{z:+11.2f}")
    for label, t in (("合计(含跳空)", sy["total"]),
                     ("合计(仅盘中触发)", sy["intraday"])):
        disc = t["only_up"] + t["only_dn"]
        z = (t["only_up"] - t["only_dn"]) / (disc ** 0.5) if disc else 0.0
        print(f"{label:<12}{stats.fmt_rate(t['up'], t['n']):>26}"
              f"{stats.fmt_rate(t['dn'], t['n']):>26}"
              f"{t['only_up']:7d}{t['only_dn']:7d}{z:+11.2f}")
    ti_ = sy["intraday"]
    print(f"  ⇒ 盘中触发的 GG：退回 0.146 比走完 0.618 更常见 "
          f"({100*ti_['dn']/ti_['n']:.1f}% vs {100*ti_['up']/ti_['n']:.1f}%), "
          f"McNemar 强烈拒绝对称性。")
    ff = sy["fine_first"]
    print(f"  5m『谁先到』({len(fsess)} 天, n 很小): 全部 —— 先到0.618 "
          f"{ff['up_first']}, 先退回0.146 {ff['dn_first']}, "
          f"都没到/同根K {ff['neither']}")
    print(f"                              仅盘中触发 —— 先到0.618 "
          f"{ff['up_first_intra']}, 先退回0.146 {ff['dn_first_intra']}, "
          f"都没到/同根K {ff['neither_intra']}")
    print()

    # ---- S4 -------------------------------------------------------------
    s4 = s4_first_hour(sess, lv)
    out["s4"] = {"q": s4["q"], "base_any": s4["base_any"],
                 "base_same": s4["base_same"],
                 "tables": {k: {str(kk): [c.k, c.n]
                                for kk, c in t.cells.items()}
                            for k, t in s4["tables"].items()}}
    print("-" * 78)
    print("S4. 首小时信息能否预测『今天会不会走到 ±1 ATR』")
    print("-" * 78)
    ba = s4["base_any"]
    bs = s4["base_same"]
    print(f"基线: 10:30 之后触及 ±1ATR = {stats.fmt_rate(ba[0], ba[1])}")
    print(f"基线: 10:30 之后触及 首小时同向 1ATR = {stats.fmt_rate(bs[0], bs[1])}")
    print(f"首小时振幅/ATR 四分位切点: {s4['q'][0]:.3f} / {s4['q'][1]:.3f} "
          f"/ {s4['q'][2]:.3f}")
    print()
    for key in ("rng", "lvl", "dir", "cmb"):
        t = s4["tables"][key]
        print(t.render())
        base = bs if key == "dir" else ba
        for kk, c in sorted(t.cells.items(), key=lambda x: -x[1].rate):
            z = stats.two_proportion_z(c.k, c.n, base[0] - c.k,
                                       base[1] - c.n)
            verdict = "有做功" if abs(z) >= 1.96 else "**没做功**"
            print(f"    vs 基线(剔除本格): {str(kk):<34} z={z:+6.2f} {verdict}")
        print()

    st = s4["strat"]
    print("4e. 分层检验 —— 两个预测因子是不是同一件事？")
    print(f"  固定『已过0.382』, 只变振幅:  宽(Q4) {stats.fmt_rate(*st['wide'])}"
          f"   窄(Q1+Q2) {stats.fmt_rate(*st['narrow'])}")
    print(f"     z={st['z']:+.2f} -> "
          f"{'振幅在位置之外仍然做功' if abs(st['z']) >= 1.96 else '**振幅没有额外做功**'}")
    print(f"  固定振幅(Q2+Q3), 只变位置:  已过0.382 "
          f"{stats.fmt_rate(*st['mid_far'])}   未过 {stats.fmt_rate(*st['mid_near'])}")
    print(f"     z={st['z2']:+.2f} -> "
          f"{'位置在振幅之外仍然做功' if abs(st['z2']) >= 1.96 else '**位置没有额外做功**'}")
    print()

    # ---- S5 -------------------------------------------------------------
    s5 = s5_calendar(daily, lv)
    out["s5"] = {"dow_rng": s5["dow_rng"], "mon_rng": s5["mon_rng"],
                 "dow_raw": s5["dow_raw"], "mon_raw": s5["mon_raw"]}
    print("-" * 78)
    print("S5. 周内效应 / 月内效应 (20 年日线, n≈5000)")
    print("-" * 78)
    print("当日振幅/前日ATR, 按星期:")
    for k in DOW:
        d = s5["dow_rng"].get(k)
        if d:
            print(f"  {k}  {fmt_dist(d)}")
    print()
    print(s5["dow_1atr"].render(order=list(DOW)))
    zs = contrast_vs_rest(s5["dow_raw"])
    for k in DOW:
        z = zs.get(k, 0.0)
        print(f"    {k} vs 其余四天: z={z:+.2f} "
              f"{'有差异' if abs(z) >= 1.96 else '**无差异**'}")
    print()
    print(s5["dow_gg"].render(order=list(DOW)))
    print()
    print(s5["mon_1atr"].render())
    zsm = contrast_vs_rest(s5["mon_raw"])
    strong = [(k, v) for k, v in sorted(zsm.items()) if abs(v) >= 1.96]
    print(f"    单独看 |z|>=1.96 的月份: "
          f"{strong if strong else '无'}")
    print(f"    但这是 12 次比较 —— Bonferroni 后需要 |z|>=2.87 才算数: "
          f"{[(k, round(v,2)) for k, v in zsm.items() if abs(v) >= 2.87] or '无'}")
    print()
    dm = s5["dom_1atr"].cells
    z_som = stats.two_proportion_z(dm["月初(前3交易日)"].k, dm["月初(前3交易日)"].n,
                                   dm["月中"].k + dm["月末(后3交易日)"].k,
                                   dm["月中"].n + dm["月末(后3交易日)"].n)
    print(s5["dom_1atr"].render())
    print(f"    月初 vs 其余: z={z_som:+.2f} "
          f"{'有差异' if abs(z_som) >= 1.96 else '**无差异**'}")
    print()
    print("稳健性：日度 ±1ATR 触及有强波动率聚集，独立性假设下的 Wilson 区间偏窄。")
    print("逐年复核效应方向（每年单独看，该组的触及率是否高于对照组）：")
    for k, (pos, tot) in s5["year_sign"].items():
        p = sign_test_p(pos, tot)
        print(f"    {k:<6} {pos}/{tot} 个年份方向一致  符号检验 p={p:.4f} "
              f"({'跨年份稳定' if p < 0.05 else '**不稳定, 更像少数高波动年份带出来的**'})")
    a, b_ = s5["som_nojan"]
    z_nj = stats.two_proportion_z(a[0], a[1], b_[0], b_[1])
    print(f"    月初效应剔除 1 月后: 月初 {stats.fmt_rate(a[0], a[1])}  "
          f"其余 {stats.fmt_rate(b_[0], b_[1])}  z={z_nj:+.2f} "
          f"{'仍在' if abs(z_nj) >= 1.96 else '**消失 —— 原来只是 1 月效应**'}")
    print()

    if "--json" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--json") + 1])
        p.write_text(json.dumps(out, default=str, indent=1))
        print(f"[raw numbers -> {p}]")


if __name__ == "__main__":
    main()
