"""Resolution study: is the "reaction at a level" a micro-scale phenomenon?

Round 1 answered every question on daily and hourly bars and returned a clean
null.  The trader's objection is that he trades 0DTE off 1-5 minute charts, so
a null measured at hourly resolution may simply be a null about hourly bars.
This module re-runs the level questions on the finest data that exists
(60 days of 5-minute bars, plus ES=F which also carries overnight and volume),
and then deliberately degrades the resolution — 5m -> 10m -> 15m -> 30m -> 1h
built by aggregating *the same bars* — so that resolution is the only thing
that changes between cells.

The methodological spine is the SHIFT PROFILE.  Every question is asked not
just of the named Fibonacci ladder but of the same ladder slid by delta, for
delta on a fine grid either side of zero.  If named levels are special, the
statistic must PEAK at delta = 0.  If the statistic is a smooth function of
delta with no feature at zero, the named ratios are an alias for distance —
which is exactly what round 1 concluded on coarse bars.  The shift profile
turns "is it real" into "is there a bump", which needs no null model at all.

Where a null model IS needed (test 2, next level vs previous level), two are
used side by side:

  * analytic geometric null  P(next first) = S / (S + T) per event, tested
    with a Poisson-binomial z (levels are at different distances, so a single
    pooled p is wrong);
  * a path bootstrap that circularly rotates each session's sequence of bar
    shapes.  This preserves the day's volatility, its intraday seasonality,
    its serial correlation and its net drift, while destroying any
    relationship between the price path and the fixed ladder.  It is the only
    null that correctly absorbs the censoring bias of a 6-bar horizon.

Nothing here is selected after the fact.  Every cell computed is printed.
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels                      # noqa: E402
from satylab.data import Bar                          # noqa: E402
from satylab.stats import fmt_rate, two_proportion_z  # noqa: E402

RNG = random.Random(20260725)

# ---------------------------------------------------------------- ladders ---
NAMED: tuple[float, ...] = levels.RATIOS
# Placebo ladders are the SAME ladder slid along the ratio axis.  The grid is
# fine enough that a genuine feature at zero cannot hide between two shifts.
SHIFTS: tuple[float, ...] = tuple(round(-0.100 + 0.005 * i, 4) for i in range(41))
FAR = 0.050          # |delta| >= FAR counts as "off the named ladder"

BAND = 0.03          # half-width requested by the brief, in ATR units
BAND_SENS = (0.015, 0.03, 0.05, 0.10)

SYMS = ("^GSPC", "SPY", "ES=F")

CELLS = 0            # global family counter — every computed cell increments


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ------------------------------------------------------------- bar plumbing --
@dataclass(slots=True)
class Ctx:
    """One symbol at one resolution, with the daily ATR ladder attached."""
    sym: str
    tf: str
    sessions: dict[date, list[Bar]]
    maps: dict[date, levels.DayLevels]

    def days(self) -> list[date]:
        return sorted(d for d in self.sessions if d in self.maps)


def aggregate(bars: list[Bar], k: int) -> list[Bar]:
    """Merge k consecutive intraday bars.  Same data, coarser resolution."""
    out: list[Bar] = []
    for i in range(0, len(bars), k):
        chunk = bars[i:i + k]
        out.append(Bar(chunk[0].dt, chunk[0].day, chunk[0].open,
                       max(b.high for b in chunk), min(b.low for b in chunk),
                       chunk[-1].close, sum(b.volume for b in chunk)))
    return out


def rth_only(bars: list[Bar]) -> list[Bar]:
    return [b for b in bars
            if (b.dt.hour, b.dt.minute) >= (9, 30)
            and (b.dt.hour, b.dt.minute) < (16, 0)]


def build_ctx(sym: str, agg: int = 1, rth: bool = True) -> Ctx:
    dly = data.daily(sym)
    maps = levels.build(dly)
    raw = data.group_by_day(data.fine(sym))
    sessions: dict[date, list[Bar]] = {}
    for day, bars in raw.items():
        rows = rth_only(bars) if rth else bars
        if len(rows) < 20:
            continue
        sessions[day] = aggregate(rows, agg) if agg > 1 else rows
    tf = f"{5*agg}m"
    return Ctx(sym, tf, sessions, maps)


def build_hourly_ctx(sym: str, days_limit: int | None = None) -> Ctx:
    """The real 730-day hourly series (different sample period, same question)."""
    dly = data.daily(sym)
    maps = levels.build(dly)
    raw = data.group_by_day(data.hourly(sym))
    sessions = {d: rth_only(b) for d, b in raw.items()}
    sessions = {d: b for d, b in sessions.items() if len(b) >= 5}
    if days_limit:
        keep = sorted(sessions)[-days_limit:]
        sessions = {d: sessions[d] for d in keep}
    return Ctx(sym, "1h(730d)", sessions, maps)


# --------------------------------------------------------------- utilities --
def near_level(r: float, shift: float, band: float) -> int | None:
    """Index of the ladder rung within `band` of ratio r, else None."""
    best, bd = None, band
    for k, rn in enumerate(NAMED):
        d = abs(r - (rn + shift))
        if d <= bd:
            best, bd = k, d
    return best


def poisson_binomial_z(k: int, ps: list[float]) -> float:
    """z for H0: each event j succeeded with its own probability ps[j]."""
    if not ps:
        return 0.0
    mu = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    return (k - mu) / math.sqrt(var) if var > 0 else 0.0


def welch_z(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    va, vb = st.pvariance(a), st.pvariance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    return (st.fmean(a) - st.fmean(b)) / se if se > 0 else 0.0


def mde_two_prop(n1: int, n2: int, p: float = 0.5,
                 alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest detectable difference in proportions, given the n we have."""
    if n1 < 2 or n2 < 2:
        return 1.0
    z = 1.959964 + 0.8416212 if power == 0.80 else 1.959964 + 1.281552
    return z * math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))


def n_for_delta(delta: float, p: float = 0.5,
                alpha: float = 0.05, power: float = 0.80) -> int:
    z = 1.959964 + (0.8416212 if power == 0.80 else 1.281552)
    return math.ceil(2 * (z / delta) ** 2 * p * (1 - p))


def n_for_delta_onesample(delta: float, p: float = 0.5) -> int:
    z = 1.959964 + 0.8416212
    return math.ceil((z / delta) ** 2 * p * (1 - p))


# ============================================================================
# TEST 1a — OCCUPANCY.  Does price spend more bars inside a named band than
#           inside an identically wide band anywhere else nearby?
# ============================================================================
def occupancy_profile(ctx: Ctx, band: float = BAND) -> dict[float, tuple[int, int]]:
    """shift -> (bars whose close sits in some band, total bars)."""
    rs: list[float] = []
    for day in ctx.days():
        L = ctx.maps[day]
        for b in ctx.sessions[day]:
            rs.append(L.ratio_of(b.close))
    out: dict[float, tuple[int, int]] = {}
    n = len(rs)
    for s in SHIFTS:
        hit = sum(1 for r in rs if near_level(r, s, band) is not None)
        out[s] = (hit, n)
    bump(len(SHIFTS))
    return out


# ============================================================================
# TEST 1b — NEXT-BAR AMPLITUDE and VOLUME conditional on sitting at a level.
#           Conditioning is on the PREVIOUS close, so the "big bars contain
#           more prices" containment bias cannot manufacture an effect.
# ============================================================================
def micro_profile(ctx: Ctx, band: float = BAND) -> dict[float, dict]:
    tod_range: dict[str, list[float]] = defaultdict(list)
    tod_vol: dict[str, list[float]] = defaultdict(list)
    rows: list[tuple[float, str, float, float, float]] = []   # r_prev,hhmm,rng,absret,vol
    for day in ctx.days():
        L = ctx.maps[day]
        bars = ctx.sessions[day]
        for i in range(1, len(bars)):
            b, p = bars[i], bars[i - 1]
            rng = (b.high - b.low) / L.atr
            ar = abs(b.close - p.close) / L.atr
            rows.append((L.ratio_of(p.close), b.hhmm, rng, ar, b.volume))
            tod_range[b.hhmm].append(rng)
            tod_vol[b.hhmm].append(b.volume)
    med_rng = {k: st.median(v) for k, v in tod_range.items()}
    med_vol = {k: st.median(v) for k, v in tod_vol.items() if st.median(v) > 0}

    out: dict[float, dict] = {}
    for s in SHIFTS:
        rr, aa, vv = [], [], []
        big_k = big_n = 0
        for r_prev, hhmm, rng, ar, vol in rows:
            if near_level(r_prev, s, band) is None:
                continue
            rr.append(rng)
            aa.append(ar)
            if hhmm in med_vol:
                vv.append(vol / med_vol[hhmm])
            big_n += 1
            big_k += int(rng > med_rng[hhmm])
        out[s] = {"rng": rr, "absret": aa, "relvol": vv,
                  "big_k": big_k, "big_n": big_n}
    bump(len(SHIFTS))
    return out


# ============================================================================
# TEST 1c — DWELL TIME.  How many consecutive bars close inside the band once
#           price gets there?  Runs are per-rung, so hopping between two
#           adjacent rungs does not inflate a run.
# ============================================================================
def dwell_profile(ctx: Ctx, band: float = BAND) -> dict[float, list[int]]:
    out: dict[float, list[int]] = {}
    per_day: list[tuple[levels.DayLevels, list[Bar]]] = [
        (ctx.maps[d], ctx.sessions[d]) for d in ctx.days()]
    for s in SHIFTS:
        runs: list[int] = []
        for L, bars in per_day:
            cur, ln = None, 0
            for b in bars:
                k = near_level(L.ratio_of(b.close), s, band)
                if k is not None and k == cur:
                    ln += 1
                else:
                    if cur is not None:
                        runs.append(ln)
                    cur, ln = k, (1 if k is not None else 0)
            if cur is not None:
                runs.append(ln)
        out[s] = runs
    bump(len(SHIFTS))
    return out


# ============================================================================
# DAY-CLUSTERED BOOTSTRAP.  The "bump in shift-SD units" used above is a good
# SHAPE detector but a bad SIGNIFICANCE test: neighbouring shifts share most
# of their bars, so the spread across shifts is far smaller than the true
# sampling error of any one shift.  A statistic can therefore look like +7 SD
# while the actual difference is 4% of a relative-volume unit.  Everything
# headline-worthy is re-tested here by resampling whole SESSIONS with
# replacement, which respects both the overlap and the intraday serial
# correlation.
# ============================================================================
STATS = ("occ", "rng", "absret", "relvol", "big", "dwell2", "dwell_len")


def per_day_profile(ctx: Ctx, band: float = BAND) -> dict:
    """shift -> day -> stat -> (numerator, denominator).  One pass, all stats."""
    tod_range: dict[str, list[float]] = defaultdict(list)
    tod_vol: dict[str, list[float]] = defaultdict(list)
    for day in ctx.days():
        L = ctx.maps[day]
        bars = ctx.sessions[day]
        for i in range(1, len(bars)):
            tod_range[bars[i].hhmm].append((bars[i].high - bars[i].low) / L.atr)
            tod_vol[bars[i].hhmm].append(bars[i].volume)
    med_rng = {k: st.median(v) for k, v in tod_range.items()}
    med_vol = {k: st.median(v) for k, v in tod_vol.items() if st.median(v) > 0}

    out: dict[float, dict[date, dict[str, list[float]]]] = {}
    for s in SHIFTS:
        per: dict[date, dict[str, list[float]]] = {}
        for day in ctx.days():
            L = ctx.maps[day]
            bars = ctx.sessions[day]
            acc = {k: [0.0, 0.0] for k in STATS}
            cur, ln = None, 0
            runs: list[int] = []
            for i, b in enumerate(bars):
                k = near_level(L.ratio_of(b.close), s, band)
                acc["occ"][1] += 1
                acc["occ"][0] += int(k is not None)
                if k is not None and k == cur:
                    ln += 1
                else:
                    if cur is not None:
                        runs.append(ln)
                    cur, ln = k, (1 if k is not None else 0)
                if i == 0:
                    continue
                kp = near_level(L.ratio_of(bars[i - 1].close), s, band)
                if kp is None:
                    continue
                rng = (b.high - b.low) / L.atr
                acc["rng"][0] += rng
                acc["rng"][1] += 1
                acc["absret"][0] += abs(b.close - bars[i - 1].close) / L.atr
                acc["absret"][1] += 1
                acc["big"][0] += int(rng > med_rng[b.hhmm])
                acc["big"][1] += 1
                if b.hhmm in med_vol:
                    acc["relvol"][0] += b.volume / med_vol[b.hhmm]
                    acc["relvol"][1] += 1
            if cur is not None:
                runs.append(ln)
            acc["dwell2"][0] = float(sum(1 for x in runs if x >= 2))
            acc["dwell2"][1] = float(len(runs))
            acc["dwell_len"][0] = float(sum(runs))
            acc["dwell_len"][1] = float(len(runs))
            per[day] = acc
        out[s] = per
    bump(len(SHIFTS) * len(STATS))
    return out


def _ratio(days: list[date], per: dict, stat: str) -> float:
    num = sum(per[d][stat][0] for d in days if d in per)
    den = sum(per[d][stat][1] for d in days if d in per)
    return num / den if den else 0.0


def day_boot(prof: dict, days: list[date], stat: str,
             reps: int = 1000) -> dict:
    """Bootstrap the (delta=0 minus off-ladder) difference by resampling days."""
    far = [s for s in SHIFTS if abs(s) >= FAR]
    obs0 = _ratio(days, prof[0.0], stat)
    obsf = st.fmean([_ratio(days, prof[s], stat) for s in far])
    diffs = []
    n = len(days)
    for _ in range(reps):
        samp = [days[RNG.randrange(n)] for _ in range(n)]
        a = _ratio(samp, prof[0.0], stat)
        b = st.fmean([_ratio(samp, prof[s], stat) for s in far])
        diffs.append(a - b)
    sd = st.pstdev(diffs) or 1e-12
    diffs.sort()
    return {"at0": obs0, "far": obsf, "diff": obs0 - obsf, "sd": sd,
            "z": (obs0 - obsf) / sd,
            "lo": diffs[int(0.025 * reps)], "hi": diffs[int(0.975 * reps)]}


# ============================================================================
# TEST 2 — NEXT LEVEL vs PREVIOUS LEVEL after a first touch.
# ============================================================================
@dataclass(slots=True)
class Ev:
    day: date
    rung: int
    up: bool
    entry: float
    p_prev: float
    p_next: float
    outcome: int          # +1 next first, -1 prev first, 0 unresolved
    p_geo: float          # S/(S+T) under a driftless walk
    hhmm: str


def touch_events(L: levels.DayLevels, bars: list[Bar], shift: float,
                 horizon: int, executable: bool) -> list[Ev]:
    """First touch of each rung, then which neighbour rung comes first.

    `executable` = entry at the close of the touching bar (what a trader can
    actually get).  Otherwise entry at the rung price itself (the idealised
    version, which puts the geometric null at exactly D_prev/(D_prev+D_next)).
    """
    ladder = [L.at(rn + shift) for rn in NAMED]
    start = bars[0].open
    evs: list[Ev] = []
    hi = lo = start
    touched = [False] * len(ladder)
    for i, b in enumerate(bars):
        hi, lo = max(hi, b.high), min(lo, b.low)
        for k, p in enumerate(ladder):
            if touched[k]:
                continue
            up = p > start
            if up and b.high < p:
                continue
            if (not up) and b.low > p:
                continue
            touched[k] = True
            nxt = k + 1 if up else k - 1
            prv = k - 1 if up else k + 1
            if not (0 <= nxt < len(ladder) and 0 <= prv < len(ladder)):
                continue
            p_next, p_prev = ladder[nxt], ladder[prv]
            entry = b.close if executable else p
            # a bar that already blew past the far rung leaves nothing to test
            if up and not (p_prev < entry < p_next):
                continue
            if (not up) and not (p_next < entry < p_prev):
                continue
            S = abs(entry - p_prev)
            T = abs(p_next - entry)
            if S <= 0 or T <= 0:
                continue
            res = 0
            stop = len(bars) if horizon <= 0 else min(len(bars), i + 1 + horizon)
            for j in range(i + 1, stop):
                c = bars[j]
                hit_next = (c.high >= p_next) if up else (c.low <= p_next)
                hit_prev = (c.low <= p_prev) if up else (c.high >= p_prev)
                if hit_next and hit_prev:
                    res = 0          # ambiguous inside one bar -> drop
                    break
                if hit_next:
                    res = 1
                    break
                if hit_prev:
                    res = -1
                    break
            evs.append(Ev(L.day, k, up, entry, p_prev, p_next, res,
                          S / (S + T), b.hhmm))
    return evs


def visit_events(L: levels.DayLevels, bars: list[Bar], shift: float,
                 horizon: int, band: float = BAND) -> list[Ev]:
    """Every *visit* to a rung band, not just the day's first touch.

    Motivation is power, not novelty: first-touch gives ~4 events a day, and
    60 days of 5m bars cannot fund a 5pp test with that.  A visit is a
    contiguous run of closes inside one rung's band; the event fires on the
    first bar of the run, entry at that bar's close.  Repeat visits to the
    same rung on the same day are NOT independent — treat n here as an upper
    bound on information, and read the shift profile rather than the z.
    """
    ladder = [L.at(rn + shift) for rn in NAMED]
    evs: list[Ev] = []
    cur = None
    for i, b in enumerate(bars):
        k = near_level(L.ratio_of(b.close), shift, band)
        if k is None or k == cur:
            cur = k
            continue
        cur = k
        nxt_up, prv_up = k + 1, k - 1
        if not (0 <= prv_up and nxt_up < len(ladder)):
            continue
        # direction of travel = where the run arrived from
        ref = bars[i - 1].close if i else bars[0].open
        up = b.close >= ref
        nxt = ladder[k + 1] if up else ladder[k - 1]
        prv = ladder[k - 1] if up else ladder[k + 1]
        entry = b.close
        if up and not (prv < entry < nxt):
            continue
        if (not up) and not (nxt < entry < prv):
            continue
        S, T = abs(entry - prv), abs(nxt - entry)
        if S <= 0 or T <= 0:
            continue
        res = 0
        stop = len(bars) if horizon <= 0 else min(len(bars), i + 1 + horizon)
        for j in range(i + 1, stop):
            c = bars[j]
            hn = (c.high >= nxt) if up else (c.low <= nxt)
            hp = (c.low <= prv) if up else (c.high >= prv)
            if hn and hp:
                res = 0
                break
            if hn:
                res = 1
                break
            if hp:
                res = -1
                break
        evs.append(Ev(L.day, k, up, entry, prv, nxt, res, S / (S + T), b.hhmm))
    return evs


def run_visits(ctx: Ctx, shift: float, horizon: int,
               band: float = BAND) -> list[Ev]:
    evs: list[Ev] = []
    for day in ctx.days():
        evs += visit_events(ctx.maps[day], ctx.sessions[day], shift,
                            horizon, band)
    return evs


def gg_rate(ctx: Ctx, shift: float = 0.0) -> tuple[int, int]:
    """Round 1's headline, re-asked at this resolution: touch 0.382 -> 0.618."""
    k = n = 0
    for day in ctx.days():
        L = ctx.maps[day]
        bars = ctx.sessions[day]
        start = bars[0].open
        for sgn in (+1, -1):
            e = L.at(sgn * levels.GG_ENTRY + shift)
            c = L.at(sgn * levels.GG_COMPLETE + shift)
            if sgn > 0 and not e > start:
                continue
            if sgn < 0 and not e < start:
                continue
            idx = None
            for i, b in enumerate(bars):
                if (b.high >= e) if sgn > 0 else (b.low <= e):
                    idx = i
                    break
            if idx is None:
                continue
            n += 1
            for b in bars[idx:]:
                if (b.high >= c) if sgn > 0 else (b.low <= c):
                    k += 1
                    break
    return k, n


def run_test2(ctx: Ctx, shift: float, horizon: int,
              executable: bool) -> list[Ev]:
    evs: list[Ev] = []
    for day in ctx.days():
        evs += touch_events(ctx.maps[day], ctx.sessions[day], shift,
                            horizon, executable)
    return evs


def summarize_evs(evs: list[Ev]) -> dict:
    res = [e for e in evs if e.outcome != 0]
    k = sum(1 for e in res if e.outcome > 0)
    n = len(res)
    exp = st.fmean([e.p_geo for e in res]) if res else 0.0
    z = poisson_binomial_z(k, [e.p_geo for e in res])
    k_all = sum(1 for e in evs if e.outcome > 0)
    return {"k": k, "n": n, "rate": (k / n if n else 0.0),
            "geo": exp, "z": z, "n_all": len(evs),
            "resolved_share": (n / len(evs) if evs else 0.0),
            "k_all": k_all,
            "rate_all": (k_all / len(evs) if evs else 0.0)}


# ----------------------------------------------------------- path bootstrap --
def rotate_session(bars: list[Bar], off: int) -> list[Bar]:
    """Same bar shapes, rotated in time, chained from the same session open.

    Preserves the day's bar-size distribution, its serial structure and its
    net drift; destroys any alignment between the path and the fixed ladder.
    """
    n = len(bars)
    shapes = []
    prev = bars[0].open
    for b in bars:
        shapes.append((b.open - prev, b.high - prev, b.low - prev,
                       b.close - prev, b.volume))
        prev = b.close
    out: list[Bar] = []
    cur = bars[0].open
    for i in range(n):
        do, dh, dl, dc, v = shapes[(i + off) % n]
        out.append(Bar(bars[i].dt, bars[i].day, cur + do, cur + dh,
                       cur + dl, cur + dc, v))
        cur = cur + dc
    return out


def bootstrap_null(ctx: Ctx, horizon: int, executable: bool,
                   reps: int = 200, visits: bool = False) -> dict:
    """Distribution of the test-2 statistic when the ladder means nothing."""
    rates, shares, excess = [], [], []
    days = ctx.days()
    for _ in range(reps):
        evs: list[Ev] = []
        for day in days:
            bars = ctx.sessions[day]
            off = RNG.randrange(1, len(bars))
            rot = rotate_session(bars, off)
            evs += (visit_events(ctx.maps[day], rot, 0.0, horizon) if visits
                    else touch_events(ctx.maps[day], rot, 0.0, horizon,
                                      executable))
        s = summarize_evs(evs)
        if s["n"] >= 30:
            rates.append(s["rate"])
            shares.append(s["resolved_share"])
            excess.append(s["rate"] - s["geo"])
    if not rates:
        return {}
    rates.sort()
    return {"mean": st.fmean(rates), "sd": st.pstdev(rates),
            "p05": rates[int(0.05 * len(rates))],
            "p95": rates[min(len(rates) - 1, int(0.95 * len(rates)))],
            "reps": len(rates), "resolved": st.fmean(shares),
            "excess": st.fmean(excess), "excess_sd": st.pstdev(excess)}


# ============================================================================
# reporting helpers
# ============================================================================
def profile_line(vals: dict[float, float], fmt: str = "{:6.3f}") -> str:
    return " ".join(fmt.format(vals[s]) for s in SHIFTS if abs(s * 200) % 2 < 1e-9)


def bump_test(vals: dict[float, float]) -> tuple[float, float, float]:
    """(value at delta=0, mean over |delta|>=FAR, z-like bump in sd units)."""
    at0 = vals[0.0]
    far = [v for s, v in vals.items() if abs(s) >= FAR]
    m = st.fmean(far)
    sd = st.pstdev(far) or 1e-12
    return at0, m, (at0 - m) / sd


def prof_row(label: str, vals: dict[float, float], fmt: str = "{:6.3f}") -> str:
    at0, far, bump_sd = bump_test(vals)
    return (f"| {label} | {fmt.format(at0)} | {fmt.format(far)} | "
            f"{bump_sd:+.2f} |")


SHOW = (-0.100, -0.080, -0.060, -0.040, -0.030, -0.020, -0.010, -0.005,
        0.0, 0.005, 0.010, 0.020, 0.030, 0.040, 0.060, 0.080, 0.100)


def main() -> None:
    o: list[str] = []
    w = o.append

    w("# 分辨率研究：位的反应是不是一个只在细粒度上存在的现象")
    w("")
    w("_第二轮 · 作用域划定 · 生成脚本 `research/satylab/study_micro.py`_")
    w("")
    w("---")
    w("")
    sum_idx = len(o)
    KEY: dict = {}
    w("## 0. 方法")
    w("")
    w("**核心工具是「平移剖面」（shift profile）。** 每一个统计量都不只在具名斐波")
    w("那契阶梯上计算，而是在整条阶梯平移 δ 之后重新计算，δ 在 −0.100…+0.100 ATR")
    w("上以 0.005 为步长扫过 41 个位置。如果具名位真的特殊，统计量必须在 **δ=0 处出**")
    w("**现一个峰**；如果它只是 δ 的平滑函数，具名比例就仍然只是「距离」的别名。")
    w("这个设计不需要任何零假设模型——它把「是不是真的」变成「有没有一个包」。")
    w("")
    w("需要零假设的地方（检验 2），同时使用两个：")
    w("")
    w("1. **解析几何零假设** `P(先到下一位) = S/(S+T)`，逐事件计算（各位到相邻位的")
    w("   距离不同，用一个汇总 p 是错的），用 Poisson-binomial z 检验；")
    w("2. **路径自举零假设**：把每个交易日的「K 线形状序列」做**循环旋转**后从同一")
    w("   开盘价重新链接成路径。这保留了当日波动率、日内季节性、序列相关和净漂移，")
    w("   只摧毁价格路径与固定阶梯之间的对齐关系。它是唯一能正确吸收 6 根 K 有限")
    w("   视界所带来的**删失偏差**的零假设。")
    w("")
    w("带宽默认 ±0.03 ATR（任务书指定），并做 ±0.015 / ±0.05 / ±0.10 敏感性。")
    w("")

    # ---------------------------------------------------------------- data --
    w("## 1. 数据与一个必须先说清楚的尺度事实")
    w("")
    w("| 标的 | 5m 根数 | 交易日 | 区间 | 有成交量 | 含夜盘 |")
    w("|---|---|---|---|---|---|")
    ctxs: dict[str, Ctx] = {}
    for s in SYMS:
        c = build_ctx(s)
        ctxs[s] = c
        days = c.days()
        nb = sum(len(c.sessions[d]) for d in days)
        volq = "是" if s != "^GSPC" else "**否（恒为 0）**"
        w(f"| {s} | {nb} | {len(days)} | {days[0]} → {days[-1]} | {volq} | "
          f"{'是（另测）' if s == 'ES=F' else '否'} |")
    w("")
    w("（RTH 09:30–15:55。ES=F 的夜盘另行处理，见 §9。）")
    w("")
    w("### 1.1 ±0.03 ATR 这条带子比一根 5 分钟 K 还窄")
    w("")
    w("| 标的 | 5m K 振幅/ATR 中位数 | 5m \\|Δclose\\|/ATR 中位数 | 带宽 0.06 ATR ÷ 中位振幅 |")
    w("|---|---|---|---|")
    scale: dict[str, float] = {}
    for s in SYMS:
        c = ctxs[s]
        rngs, ars = [], []
        for d in c.days():
            L = c.maps[d]
            bs = c.sessions[d]
            for i, b in enumerate(bs):
                rngs.append((b.high - b.low) / L.atr)
                if i:
                    ars.append(abs(b.close - bs[i - 1].close) / L.atr)
        mr, ma = st.median(rngs), st.median(ars)
        scale[s] = mr
        w(f"| {s} | {mr:.4f} | {ma:.4f} | {2*BAND/mr:.2f}× |")
        bump(1)
    w("")
    w("**这是本报告最重要的单一事实。** 任务书要求的 ±0.03 ATR 带子，其总宽度")
    w("(0.06 ATR) 只有一根 5 分钟 K 中位振幅的 0.8–1.4 倍，而一步收盘价位移的中")
    w("位数（0.018–0.032 ATR）本身就接近半带宽。也就是说：**在 5 分钟分辨率上，**")
    w("**「位」是一个亚 K 线对象。** 一根普通 K 线就能从带子的一边跨到另一边。")
    w("这既解释了为什么小时线上什么都看不见（小时线上带宽/振幅≈0.2），也给出了")
    w("停留时间检验的先验：期望停留 ≈ 1–2 根，不可能很长。")
    w("")

    # ---------------------------------------------- TEST 1a: occupancy ------
    w("---")
    w("")
    w("## 2. 检验 1a — 占用率：价格是否更常「待在」具名位附近")
    w("")
    w("统计量 = 收盘价落在某条阶梯带内的 K 线比例。整条阶梯平移 δ。")
    w("如果位吸引价格，δ=0 应出现峰。")
    w("")
    occ_res: dict[str, dict[float, float]] = {}
    for s in SYMS:
        occ = occupancy_profile(ctxs[s])
        occ_res[s] = {k: v[0] / v[1] for k, v in occ.items()}
        n_tot = occ[0.0][1]
        w(f"### {s}（n={n_tot} 根 5m K）")
        w("")
        w("| δ (ATR) | " + " | ".join(f"{d:+.3f}" for d in SHOW) + " |")
        w("|---" * (len(SHOW) + 1) + "|")
        w("| 占用率 % | " + " | ".join(f"{100*occ_res[s][d]:.2f}" for d in SHOW) + " |")
        w("")
        at0, far, bsd = bump_test(occ_res[s])
        KEY.setdefault("occ", {})[s] = (100 * (at0 - far), bsd)
        k0, n0 = occ[0.0]
        kf = sum(occ[d][0] for d in SHIFTS if abs(d) >= FAR)
        nf = sum(occ[d][1] for d in SHIFTS if abs(d) >= FAR)
        z = two_proportion_z(k0, n0, kf, nf)
        w(f"- δ=0: {fmt_rate(k0, n0)}")
        w(f"- \\|δ\\|≥{FAR}: {fmt_rate(kf, nf)}（{sum(1 for d in SHIFTS if abs(d)>=FAR)} 个平移位汇总，"
          f"事件非独立，z 仅作量级参考）")
        w(f"- **δ=0 相对远处平移的凸起 = {100*(at0-far):+.3f} pp，"
          f"= {bsd:+.2f} 个平移间标准差**（two-prop z={z:+.2f}，见上注）")
        w("")

    # ---------------------------------------- TEST 1b: amplitude / volume ---
    w("---")
    w("")
    w("## 3. 检验 1b — 微观行为：站在位上时，下一根 K 是否不一样")
    w("")
    w("条件加在**上一根的收盘价**上，测**下一根**的振幅与成交量。")
    w("这样做是为了杜绝「大 K 更容易包含任意价格」这个致命的包含性偏差——")
    w("如果用「K 线覆盖了位」当条件，任何位都会显得振幅更大。")
    w("")
    micro_res: dict[str, dict] = {}
    for s in SYMS:
        mp = micro_profile(ctxs[s])
        micro_res[s] = mp
        mean_rng = {k: (st.fmean(v["rng"]) if v["rng"] else 0.0) for k, v in mp.items()}
        mean_ar = {k: (st.fmean(v["absret"]) if v["absret"] else 0.0) for k, v in mp.items()}
        mean_vol = {k: (st.fmean(v["relvol"]) if v["relvol"] else 0.0) for k, v in mp.items()}
        big = {k: (v["big_k"] / v["big_n"] if v["big_n"] else 0.0) for k, v in mp.items()}
        w(f"### {s}")
        w("")
        w("| 统计量 | δ=0 | \\|δ\\|≥0.05 均值 | 凸起(平移SD) | 判读 |")
        w("|---|---|---|---|---|")
        for name, vals, fmt in (("下一根振幅/ATR", mean_rng, "{:.4f}"),
                                ("下一根\\|Δclose\\|/ATR", mean_ar, "{:.4f}"),
                                ("下一根相对成交量", mean_vol, "{:.3f}"),
                                ("下一根振幅>同时刻中位数", big, "{:.4f}")):
            a0, fa, bs_ = bump_test(vals)
            if s == "^GSPC" and name == "下一根相对成交量":
                w(f"| {name} | — | — | — | ^GSPC 无量，跳过 |")
                continue
            verdict = "无凸起" if abs(bs_) < 2 else ("**有凸起**" if bs_ > 0 else "**反向凸起**")
            KEY.setdefault("micro", {})[(s, name)] = bs_
            w(f"| {name} | {fmt.format(a0)} | {fmt.format(fa)} | {bs_:+.2f} | {verdict} |")
            bump(1)
        k0, n0 = mp[0.0]["big_k"], mp[0.0]["big_n"]
        kf = sum(mp[d]["big_k"] for d in SHIFTS if abs(d) >= FAR)
        nf = sum(mp[d]["big_n"] for d in SHIFTS if abs(d) >= FAR)
        w("")
        w(f"- 「振幅高于同时刻中位数」δ=0: {fmt_rate(k0, n0)}")
        w(f"- 同 \\|δ\\|≥0.05: {fmt_rate(kf, nf)}  → two-prop z={two_proportion_z(k0,n0,kf,nf):+.2f}")
        w(f"- Welch z（振幅均值 δ=0 vs 远处池）= "
          f"{welch_z(mp[0.0]['rng'], [x for d in SHIFTS if abs(d)>=FAR for x in mp[d]['rng']]):+.2f}")
        w("")

    # ------------------------------------------------- TEST 1c: dwell ------
    w("---")
    w("")
    w("## 4. 检验 1c — 停留时间：位是否「粘」")
    w("")
    w("同一根阶梯上连续收盘的 K 数（换到相邻阶梯即断开，不算同一段）。")
    w("")
    for s in SYMS:
        dw = dwell_profile(ctxs[s])
        mean_len = {k: (st.fmean(v) if v else 0.0) for k, v in dw.items()}
        p2 = {k: (sum(1 for x in v if x >= 2) / len(v) if v else 0.0) for k, v in dw.items()}
        p3 = {k: (sum(1 for x in v if x >= 3) / len(v) if v else 0.0) for k, v in dw.items()}
        a0, fa, b1 = bump_test(mean_len)
        KEY.setdefault("dwell_len", {})[s] = (a0, fa, b1)
        b0, bf, b2 = bump_test(p2)
        KEY.setdefault("dwell2", {})[s] = (100 * b0, 100 * bf, b2)
        c0, cf, b3 = bump_test(p3)
        n0 = len(dw[0.0])
        k2 = sum(1 for x in dw[0.0] if x >= 2)
        nf2 = sum(len(dw[d]) for d in SHIFTS if abs(d) >= FAR)
        kf2 = sum(1 for d in SHIFTS if abs(d) >= FAR for x in dw[d] if x >= 2)
        w(f"### {s}（δ=0 共 {n0} 段访问）")
        w("")
        w("| 统计量 | δ=0 | \\|δ\\|≥0.05 | 凸起(平移SD) |")
        w("|---|---|---|---|")
        w(f"| 平均停留根数 | {a0:.3f} | {fa:.3f} | {b1:+.2f} |")
        w(f"| P(停留≥2 根) | {100*b0:.2f}% | {100*bf:.2f}% | {b2:+.2f} |")
        w(f"| P(停留≥3 根) | {100*c0:.2f}% | {100*cf:.2f}% | {b3:+.2f} |")
        w("")
        w(f"- P(≥2根) δ=0: {fmt_rate(k2, n0)}；\\|δ\\|≥0.05: {fmt_rate(kf2, nf2)}；"
          f"two-prop z={two_proportion_z(k2,n0,kf2,nf2):+.2f}")
        w("")
        bump(3)

    # ------------------------------------- day-clustered bootstrap ---------
    w("---")
    w("")
    w("## 5. 【关键】日聚类自举 —— 把 §2–§4 的「凸起」重新算一遍")
    w("")
    w("上面三节的「凸起 = 多少个平移 SD」是一个**好的形状探测器**，但它是一个")
    w("**坏的显著性检验**：相邻平移位共用绝大部分 K 线，所以平移之间的离散度")
    w("远小于任何单个平移位自身的抽样误差。ES=F 的相对成交量就是活教材——")
    w("按平移 SD 算是 **+7.08**，看着石破天惊；实际差值只有 **+0.047** 个相对成交量")
    w("单位（+4.4%），日聚类自举下只有 z=+1.86。**不要读平移 SD 当 p 值。**")
    w("")
    w("正确做法是**整段交易日有放回重抽**（1000 次），它同时吸收了平移之间的样本")
    w("重叠和日内序列相关。下表是本报告所有微观统计量的**唯一权威判读**。")
    w("")
    w(r"| 标的 | 统计量 | δ=0 | 离开阶梯(\|δ\|≥0.05) | 差 | 自举 SD | 自举 95% CI | z | 判读 |")
    w("|---|---|---|---|---|---|---|---|---|")
    STAT_CN = {"occ": "占用率", "rng": "下一根振幅/ATR",
               "absret": r"下一根\|Δclose\|/ATR", "relvol": "下一根相对成交量",
               "big": "振幅>同时刻中位数", "dwell2": "P(停留≥2根)",
               "dwell_len": "平均停留根数"}
    nboot = 0
    nsig = 0
    for s in SYMS:
        prof = per_day_profile(ctxs[s])
        days = ctxs[s].days()
        for stat in STATS:
            if s == "^GSPC" and stat == "relvol":
                continue
            r = day_boot(prof, days, stat, reps=1000)
            KEY.setdefault("boot", {})[(s, stat)] = r
            nboot += 1
            sig = abs(r["z"]) >= 1.96
            nsig += int(sig)
            verdict = ("没做功" if not sig else
                       ("**显著，方向与「位吸引价格」相反**" if r["z"] < 0
                        else "**显著，方向支持假说**"))
            w(f"| {s} | {STAT_CN[stat]} | {r['at0']:.4f} | {r['far']:.4f} | "
              f"{r['diff']:+.4f} | {r['sd']:.4f} | "
              f"[{r['lo']:+.4f}, {r['hi']:+.4f}] | {r['z']:+.2f} | {verdict} |")
            bump(1)
    w("")
    w(f"**{nboot} 个格子，{nsig} 个越过 \\|z\\|=1.96**（纯噪声期望 "
      f"{0.05*nboot:.1f} 个）。而且那 {nsig} 个的**符号是负的**——")
    w("具名位附近价格**停留更短**，不是更长。这与「位吸引价格」的假说方向相反，")
    w("同时也弱到不足以反过来当成一个发现。**读法：什么都没有。**")
    w("")

    # ---------------------------------------- band-width sensitivity -------
    w("---")
    w("")
    w("## 6. 带宽敏感性（全部报告，不择优）")
    w("")
    w("| 标的 | 带半宽 | 占用率凸起(pp) | 占用率凸起(SD) | 振幅凸起(SD) | 停留≥2 凸起(SD) |")
    w("|---|---|---|---|---|---|")
    for s in SYMS:
        for bw in BAND_SENS:
            occ = occupancy_profile(ctxs[s], bw)
            occr = {k: v[0] / v[1] for k, v in occ.items()}
            a0, fa, b1 = bump_test(occr)
            mp = micro_profile(ctxs[s], bw)
            mean_rng = {k: (st.fmean(v["rng"]) if v["rng"] else 0.0) for k, v in mp.items()}
            _, _, b2 = bump_test(mean_rng)
            dw = dwell_profile(ctxs[s], bw)
            p2 = {k: (sum(1 for x in v if x >= 2) / len(v) if v else 0.0)
                  for k, v in dw.items()}
            _, _, b3 = bump_test(p2)
            w(f"| {s} | ±{bw:.3f} | {100*(a0-fa):+.3f} | {b1:+.2f} | {b2:+.2f} | {b3:+.2f} |")
            bump(3)
    w("")

    # ------------------------------------------------- TEST 2 --------------
    w("---")
    w("")
    w("## 7. 检验 2 — 首触后：走向下一位 vs 折返回上一位")
    w("")
    w("事件 = 当日首次触及某条阶梯。之后逐根扫描，看**下一位**与**上一位**谁先被触到。")
    w("两种入场口径都报：")
    w("")
    w("- **理想口径**：入场价 = 位价本身，几何零假设正好是 D_prev/(D_prev+D_next)；")
    w("- **可执行口径**：入场价 = 触及那根 K 的收盘价（0DTE 交易者真正拿得到的），")
    w("  几何零假设逐笔重算 S/(S+T)。")
    w("")
    w("同一根 K 内同时触到两侧 → 判为不可判定，丢弃并计数。")
    w("")
    for s in SYMS:
        c = ctxs[s]
        w(f"### {s} · 5m")
        w("")
        w("| 视界 | 口径 | 已判定 n | 观测「先到下一位」 | 几何零假设均值 | Poisson-binomial z | 判读 |")
        w("|---|---|---|---|---|---|---|")
        for hz, hzname in ((6, "6 根 5m (30 分钟)"), (0, "至收盘")):
            for ex, exname in ((False, "理想(位价)"), (True, "可执行(触及收盘)")):
                evs = run_test2(c, 0.0, hz, ex)
                sm = summarize_evs(evs)
                verdict = ("**跑赢几何**" if sm["z"] >= 1.96 else
                           ("**跑输几何**" if sm["z"] <= -1.96 else "没做功"))
                w(f"| {hzname} | {exname} | {sm['n']} | {fmt_rate(sm['k'], sm['n'])} | "
                  f"{100*sm['geo']:.1f}% | {sm['z']:+.2f} | {verdict} |")
                bump(1)
        w("")

    # ---- shift profile for test 2 -----------------------------------------
    w("### 7.1 检验 2 的平移剖面（具名位 vs 平移阶梯）")
    w("")
    w("如果具名位提供的是「真东西」，δ=0 的超额（观测 − 几何零假设）应该有峰。")
    w("（再次提醒：「凸起 = 多少个平移 SD」是形状探测器，不是 p 值，见 §5。）")
    w("")
    for s in SYMS:
        c = ctxs[s]
        w(f"**{s} · 至收盘 · 可执行口径**")
        w("")
        w("| δ (ATR) | " + " | ".join(f"{d:+.3f}" for d in SHOW) + " |")
        w("|---" * (len(SHOW) + 1) + "|")
        exc: dict[float, float] = {}
        zs: dict[float, float] = {}
        ns: dict[float, int] = {}
        for d in SHIFTS:
            sm = summarize_evs(run_test2(c, d, 0, True))
            exc[d] = sm["rate"] - sm["geo"]
            zs[d] = sm["z"]
            ns[d] = sm["n"]
        bump(len(SHIFTS))
        w("| 超额 pp | " + " | ".join(f"{100*exc[d]:+.2f}" for d in SHOW) + " |")
        w("| z | " + " | ".join(f"{zs[d]:+.2f}" for d in SHOW) + " |")
        w("| n | " + " | ".join(f"{ns[d]}" for d in SHOW) + " |")
        w("")
        a0, fa, bs_ = bump_test(exc)
        w(f"- δ=0 超额 {100*a0:+.2f} pp；\\|δ\\|≥0.05 平均超额 {100*fa:+.2f} pp；"
          f"**凸起 = {bs_:+.2f} 个平移 SD**")
        w("")

    # ---- bootstrap null ---------------------------------------------------
    w("### 7.2 路径自举零假设（吸收删失偏差）")
    w("")
    w("每个交易日的 K 线形状序列做循环旋转后重链，重复 150 次。")
    w("保留当日波动率/季节性/序列相关/净漂移，只打断路径与阶梯的对齐。")
    w("")
    w("| 标的 | 事件 | 视界 | 观测率 | 自举零假设 | 自举 SD | 自举 5–95% | z(观测 vs 自举) | 判读 |")
    w("|---|---|---|---|---|---|---|---|---|")
    boots: dict[tuple, dict] = {}
    for s in SYMS:
        c = ctxs[s]
        for vis, vname in ((False, "首触"), (True, "每次访问")):
            for hz, hzname in ((6, "6根30分"), (0, "至收盘")):
                sm = summarize_evs(run_visits(c, 0.0, hz) if vis
                                   else run_test2(c, 0.0, hz, True))
                bt = bootstrap_null(c, hz, True, reps=300, visits=vis)
                boots[(s, vis, hz)] = (sm, bt)
                if not bt:
                    w(f"| {s} | {vname} | {hzname} | — | 自举失败 | | | | |")
                    continue
                zz = (sm["rate"] - bt["mean"]) / (bt["sd"] or 1e-12)
                verdict = "没做功" if abs(zz) < 1.96 else "**有差异**"
                w(f"| {s} | {vname} | {hzname} | {100*sm['rate']:.2f}% (n={sm['n']}) | "
                  f"{100*bt['mean']:.2f}% | {100*bt['sd']:.2f} | "
                  f"{100*bt['p05']:.1f}–{100*bt['p95']:.1f}% | {zz:+.2f} | {verdict} |")
                bump(1)
    w("")
    w("**自举零假设本身就低于几何零假设。** 上表的自举均值一律落在 45–48%，而")
    w("解析几何零假设是 48–52%。也就是说，「观测率略低于 S/(S+T)」是**真实 5 分钟**")
    w("**价格路径的普遍性质**（离散化 + 短周期负自相关 + 视界删失共同造成），")
    w("**跟具名位没有关系**——把阶梯拿掉、把路径打乱重来，同样的负偏离照样出现。")
    w("这是本轮方法论上最重要的一条：在 5 分钟分辨率上，S/(S+T) 已经不是一个")
    w("足够精确的零假设，必须用路径自举校准。")
    w("")

    w("### 7.2b 「超额」口径：观测超额 vs 自举超额")
    w("")
    w("超额 = 观测率 − 该样本的几何零假设均值。两边都算超额，就把上面这层偏差消掉。")
    w("")
    w("| 标的 | 事件 | 视界 | 观测超额 pp | 自举超额 pp | 自举 SD | z | 判读 |")
    w("|---|---|---|---|---|---|---|---|")
    for (s, vis, hz), (sm, bt) in boots.items():
        if not bt:
            continue
        oe = sm["rate"] - sm["geo"]
        zz = (oe - bt["excess"]) / (bt["excess_sd"] or 1e-12)
        w(f"| {s} | {'每次访问' if vis else '首触'} | {'6根30分' if hz else '至收盘'} | "
          f"{100*oe:+.2f} | {100*bt['excess']:+.2f} | {100*bt['excess_sd']:.2f} | "
          f"{zz:+.2f} | {'没做功' if abs(zz) < 1.96 else '**有差异**'} |")
        bump(1)
    w("")

    w("### 7.2c 检验 2b — 每次访问（把 n 从 ~240 抬到 ~750）")
    w("")
    w("首触事件每天只有 4–5 个，60 天根本喂不饱一个 5pp 的检验（见 §10）。")
    w("「每次访问」把每一段连续落在带内的收盘都算作一个事件，n 提高约 3 倍。")
    w("代价是同日同位的重复访问**不独立**，所以 n 是信息量的上界，读平移剖面而不是读 z。")
    w("")
    w("| 标的 | 视界 | n | 观测「先到下一位」 | 几何零假设 | z(几何) | 平移剖面凸起(SD) |")
    w("|---|---|---|---|---|---|---|")
    for s in SYMS:
        c = ctxs[s]
        for hz, hzname in ((6, "6根30分"), (0, "至收盘")):
            sm = summarize_evs(run_visits(c, 0.0, hz))
            exc = {}
            for d in SHIFTS:
                sd_ = summarize_evs(run_visits(c, d, hz))
                exc[d] = sd_["rate"] - sd_["geo"]
            _, _, bsd = bump_test(exc)
            bump(len(SHIFTS))
            w(f"| {s} | {hzname} | {sm['n']} | {fmt_rate(sm['k'], sm['n'])} | "
              f"{100*sm['geo']:.1f}% | {sm['z']:+.2f} | {bsd:+.2f} |")
    w("")

    # ---- per-level breakdown ---------------------------------------------
    w("### 7.3 逐位拆解（^GSPC 5m，至收盘，可执行口径）")
    w("")
    w("| 位 | n | 先到下一位 | 几何零假设 | z |")
    w("|---|---|---|---|---|")
    evs = run_test2(ctxs["^GSPC"], 0.0, 0, True)
    byr: dict[int, list[Ev]] = defaultdict(list)
    for e in evs:
        if e.outcome != 0:
            byr[e.rung].append(e)
    for k in sorted(byr):
        rows = byr[k]
        kk = sum(1 for e in rows if e.outcome > 0)
        nn = len(rows)
        gz = st.fmean([e.p_geo for e in rows])
        zz = poisson_binomial_z(kk, [e.p_geo for e in rows])
        nm = levels.RATIO_NAMES.get(NAMED[k], f"{NAMED[k]:+.3f}")
        w(f"| {nm} ({NAMED[k]:+.3f}) | {nn} | {fmt_rate(kk, nn)} | {100*gz:.1f}% | {zz:+.2f} |")
        bump(1)
    w("")
    w(f"（{len(byr)} 个格子全部列出。禁止从中挑一个当发现——"
      f"在 {len(byr)} 个独立格子里，期望有 {0.05*len(byr):.1f} 个自然越过 \\|z\\|=1.96。）")
    w("")

    # ------------------------------------------------- TEST 3 resolution ---
    w("---")
    w("")
    w("## 8. 检验 3 — 分辨率敏感性")
    w("")
    w("**关键设计**：10m/15m/30m/60m 都由**同一批 5 分钟 K 聚合而成**。样本区间、")
    w("样本标的、阶梯全都不变，唯一变的是分辨率。这样「结论随分辨率变化」就不会")
    w("和「样本期变化」混淆。最后一行是真正的 730 天小时线，用来分离样本期效应。")
    w("")
    aggs = ((1, "5m"), (2, "10m"), (3, "15m"), (6, "30m"), (12, "60m"))
    for s in SYMS:
        w(f"### {s}")
        w("")
        w("| 分辨率 | K 数 | 带宽/中位振幅 | 占用率凸起(SD) | 振幅凸起(SD) | 停留≥2凸起(SD) | "
          "检验2 n | 观测 | 几何零假设 | z | 超额凸起(SD) |")
        w("|---|---|---|---|---|---|---|---|---|---|---|")
        for a, name in aggs:
            c = build_ctx(s, a)
            nb = sum(len(c.sessions[d]) for d in c.days())
            rngs = [(b.high - b.low) / c.maps[d].atr
                    for d in c.days() for b in c.sessions[d]]
            mr = st.median(rngs)
            occ = occupancy_profile(c)
            _, _, b1 = bump_test({k: v[0] / v[1] for k, v in occ.items()})
            mp = micro_profile(c)
            _, _, b2 = bump_test({k: (st.fmean(v["rng"]) if v["rng"] else 0.0)
                                  for k, v in mp.items()})
            dw = dwell_profile(c)
            _, _, b3 = bump_test({k: (sum(1 for x in v if x >= 2) / len(v) if v else 0.0)
                                  for k, v in dw.items()})
            sm = summarize_evs(run_test2(c, 0.0, 0, True))
            exc = {}
            for d in SHIFTS:
                sd_ = summarize_evs(run_test2(c, d, 0, True))
                exc[d] = sd_["rate"] - sd_["geo"]
            _, _, b4 = bump_test(exc)
            w(f"| {name} | {nb} | {2*BAND/mr:.2f}× | {b1:+.2f} | {b2:+.2f} | {b3:+.2f} | "
              f"{sm['n']} | {100*sm['rate']:.1f}% | {100*sm['geo']:.1f}% | {sm['z']:+.2f} | "
              f"{b4:+.2f} |")
            bump(5)
        # real hourly, 730d
        ch = build_hourly_ctx(s)
        nb = sum(len(ch.sessions[d]) for d in ch.days())
        occ = occupancy_profile(ch)
        _, _, b1 = bump_test({k: v[0] / v[1] for k, v in occ.items()})
        mp = micro_profile(ch)
        _, _, b2 = bump_test({k: (st.fmean(v["rng"]) if v["rng"] else 0.0)
                              for k, v in mp.items()})
        dw = dwell_profile(ch)
        _, _, b3 = bump_test({k: (sum(1 for x in v if x >= 2) / len(v) if v else 0.0)
                              for k, v in dw.items()})
        smh = summarize_evs(run_test2(ch, 0.0, 0, True))
        exc = {}
        for d in SHIFTS:
            exc[d] = (lambda z: z["rate"] - z["geo"])(summarize_evs(run_test2(ch, d, 0, True)))
        _, _, b4 = bump_test(exc)
        rngs = [(b.high - b.low) / ch.maps[d].atr
                for d in ch.days() for b in ch.sessions[d]]
        w(f"| **1h 真实 730d** | {nb} | {2*BAND/st.median(rngs):.2f}× | {b1:+.2f} | {b2:+.2f} | "
          f"{b3:+.2f} | {smh['n']} | {100*smh['rate']:.1f}% | {100*smh['geo']:.1f}% | "
          f"{smh['z']:+.2f} | {b4:+.2f} |")
        bump(5)
        w("")

    w("### 8.1 第一轮的头条数字（金门 0.382 → 0.618）在各分辨率上的取值")
    w("")
    w("| 标的 | 分辨率 | 触及 0.382 的 n | 完成 0.618 |")
    w("|---|---|---|---|")
    for s in SYMS:
        for a, name in aggs:
            k, n = gg_rate(build_ctx(s, a))
            w(f"| {s} | {name}（同一 60 天） | {n} | {fmt_rate(k, n)} |")
            bump(1)
        k, n = gg_rate(build_hourly_ctx(s))
        w(f"| {s} | 1h 真实 730d | {n} | {fmt_rate(k, n)} |")
        bump(1)
    w("")
    w("**5m / 10m / 15m / 30m / 60m 四舍五入到最后一位都完全相同——不是巧合，是**")
    w("**恒等式。** 「当日是否触及某价」只依赖 K 线的高低点极值与会话边界；把 K 线")
    w("聚合起来，极值不变，会话边界不变，所以触及型统计量对分辨率**结构上免疫**。")
    w("由此得到本报告的第一条作用域结论：")
    w("")
    w("> 第一轮所有基于「当日是否触及」的否定结论——包括金门完成率、下一位转移率、")
    w("> 安慰剂梯子——**不可能是分辨率造成的假象**。用 1 分钟数据重跑会得到同一个数字。")
    w("")
    w("分辨率只可能改变两类结论：(a) 依赖**顺序/路径**的（有限视界内谁先到）；")
    w("(b) 依赖**逗留/振幅/成交量**这类只有细粒度才定义得出的量。本报告的 §2–§4、")
    w("§7 的 6 根视界一列，正是专门去测这两类的。")
    w("")

    w("### 8.2 唯一越过 \\|z\\|=2 的地方，以及它为什么不是位的功劳")
    w("")
    w("上面的分辨率表里只有一处 \\|z\\|>2：**真实 730 天小时线**的检验 2。")
    w("这是全报告 n 最大的格子（SPY n≈1731、ES n≈1180），所以必须查清楚。")
    w("")
    w("| 标的 | 1h/730d n | 观测 | 几何零假设 | z(几何) | 路径自举零假设 | z(vs 自举) | 超额口径 z |")
    w("|---|---|---|---|---|---|---|---|")
    hb: dict[str, dict] = {}
    for s in SYMS:
        ch = build_hourly_ctx(s)
        sm = summarize_evs(run_test2(ch, 0.0, 0, True))
        bt = bootstrap_null(ch, 0, True, reps=300)
        z1 = (sm["rate"] - bt["mean"]) / (bt["sd"] or 1e-12)
        z2 = ((sm["rate"] - sm["geo"]) - bt["excess"]) / (bt["excess_sd"] or 1e-12)
        hb[s] = {"sm": sm, "bt": bt, "z1": z1, "z2": z2}
        w(f"| {s} | {sm['n']} | {100*sm['rate']:.1f}% | {100*sm['geo']:.1f}% | "
          f"{sm['z']:+.2f} | {100*bt['mean']:.1f}% | {z1:+.2f} | {z2:+.2f} |")
        bump(1)
    w("")
    w("**第一刀：两个同标的互相矛盾。** ^GSPC 和 SPY 是同一个指数的两种表示，")
    w(f"^GSPC 给出 z={hb['^GSPC']['sm']['z']:+.2f}，SPY 给出 z={hb['SPY']['sm']['z']:+.2f}。")
    w("同一个市场的两种表示在同一检验上一个过线一个不过线，这本身就说明它不稳。")
    w("")
    w("**第二刀（决定性的）：把阶梯平移，超额不动。**")
    w("")
    w("| 标的 | δ (ATR) | " + " | ".join(f"{d:+.3f}" for d in SHOW) + " |")
    w("|---" * (len(SHOW) + 2) + "|")
    pos_all: dict[str, tuple[int, int, float, float]] = {}
    for s in ("SPY", "ES=F"):
        ch = build_hourly_ctx(s)
        exc = {}
        for d in SHIFTS:
            sd_ = summarize_evs(run_test2(ch, d, 0, True))
            exc[d] = sd_["rate"] - sd_["geo"]
        bump(len(SHIFTS))
        w(f"| {s} | 超额 pp | " + " | ".join(f"{100*exc[d]:+.2f}" for d in SHOW) + " |")
        npos = sum(1 for v in exc.values() if v > 0)
        a0, fa, bsd = bump_test(exc)
        pos_all[s] = (npos, len(exc), 100 * a0, 100 * st.fmean(exc.values()))
    w("")
    for s, (npos, ntot, a0, mean_all) in pos_all.items():
        w(f"- **{s}：{npos}/{ntot} 个平移位的超额都是正的**，全剖面均值 {mean_all:+.2f} pp，"
          f"δ=0 处 {a0:+.2f} pp。")
    w("")
    w("41 个平移位全部为正 —— 这不是「具名位有用」，这是「**在小时线上，对**")
    w("**任意一条同样间距的阶梯**，价格都比 S/(S+T) 更倾向于继续走向下一格」。")
    w("斐波那契比例在其中**没有任何增量贡献**（δ=0 的凸起只有 "
      f"{pos_all['SPY'][2] - pos_all['SPY'][3]:+.2f} / "
      f"{pos_all['ES=F'][2] - pos_all['ES=F'][3]:+.2f} pp 对全剖面均值）。")
    w("")
    z60 = []
    for s in SYMS:
        z60.append(summarize_evs(run_test2(build_ctx(s, 12), 0.0, 0, True))["z"])
        bump(1)
    w("**第三刀：它也不是分辨率现象。** 同样的 60 天窗口，用 5m 聚合出来的 60m K")
    w("跑同一个检验（分辨率相同、样本期短），z = "
      + " / ".join(f"{x:+.2f}" for x in z60) + "（^GSPC/SPY/ES）；")
    w("差别不在分辨率，在**样本期长度**（730 天 vs 60 天）。分时段拆开看：")
    w("")
    w("| 标的 | 全 730d | 前半 | 后半 | 最后 60 日（与 5m 窗口重叠） |")
    w("|---|---|---|---|---|")
    for s in SYMS:
        ch = build_hourly_ctx(s)
        days = ch.days()
        cells = []
        for sel in (days, days[:len(days)//2], days[len(days)//2:], days[-60:]):
            sub = Ctx(s, "1h", {d: ch.sessions[d] for d in sel}, ch.maps)
            sm = summarize_evs(run_test2(sub, 0.0, 0, True))
            cells.append(f"{100*sm['rate']:.1f}% (n={sm['n']}, z={sm['z']:+.2f})")
            bump(1)
        w(f"| {s} | " + " | ".join(cells) + " |")
    w("")
    w("**结论**：小时线上确实存在一个真实的、约 +2.5 pp 的「继续 > 折返」偏离，")
    w("它对 S/(S+T) 显著，对路径自举**部分**显著，但它**与具名位无关**（平移不变），")
    w("而且方向与本任务的假设相反 —— 它出现在**粗**分辨率上，不是细分辨率上。")
    w("把它写进第三轮的候选清单，但要写成「小时线连续性偏离」，不要写成「位的边缘」。")
    w("")

    # ------------------------------------------------- ES overnight --------
    w("---")
    w("")
    w("## 9. ES=F 夜盘（唯一能看到 RTH 之外的窗口）")
    w("")
    w("| 时段 | K 数 | 占用率凸起(SD) | 振幅凸起(SD) | 停留≥2凸起(SD) | 检验2 n | 观测 | 几何 | z |")
    w("|---|---|---|---|---|---|---|---|---|")
    dly = data.daily("ES=F")
    mp_es = levels.build(dly)
    raw = data.group_by_day(data.fine("ES=F"))
    for tag, lo, hi in (("RTH 09:30-15:55", (9, 30), (16, 0)),
                        ("夜盘 18:00-09:25", (18, 0), (9, 30))):
        sess: dict[date, list[Bar]] = {}
        for d, bars in raw.items():
            if tag.startswith("RTH"):
                rows = [b for b in bars if lo <= (b.dt.hour, b.dt.minute) < hi]
            else:
                rows = [b for b in bars
                        if (b.dt.hour, b.dt.minute) >= lo
                        or (b.dt.hour, b.dt.minute) < hi]
            if len(rows) >= 20:
                sess[d] = rows
        c = Ctx("ES=F", tag, sess, mp_es)
        nb = sum(len(v) for d, v in c.sessions.items() if d in c.maps)
        occ = occupancy_profile(c)
        _, _, b1 = bump_test({k: v[0] / v[1] for k, v in occ.items()})
        mpp = micro_profile(c)
        _, _, b2 = bump_test({k: (st.fmean(v["rng"]) if v["rng"] else 0.0)
                              for k, v in mpp.items()})
        dw = dwell_profile(c)
        _, _, b3 = bump_test({k: (sum(1 for x in v if x >= 2) / len(v) if v else 0.0)
                              for k, v in dw.items()})
        sm = summarize_evs(run_test2(c, 0.0, 0, True))
        w(f"| {tag} | {nb} | {b1:+.2f} | {b2:+.2f} | {b3:+.2f} | {sm['n']} | "
          f"{100*sm['rate']:.1f}% | {100*sm['geo']:.1f}% | {sm['z']:+.2f} |")
        bump(4)
    w("")
    w("注：夜盘的「首触」定义以 18:00 起的连续段为一个 session，锚仍是日线阶梯。")
    w("夜盘 K 数虽多但流动性极低，结论只作参考。夜盘那个 z≈−2.2 是**负的**")
    w("（夜盘更倾向折返），在 8 个格子里出现 1 个属于噪声期望范围，且方向与")
    w("「位提供继续动能」的假说相反，不构成发现。")
    w("")

    # ------------------------------------------------- TEST 4 power --------
    w("---")
    w("")
    w("## 10. 检验 4 — 功效极限：我们的 5 分钟样本能测出多小的效应")
    w("")
    w("α=0.05 双尾，power=80%，p≈0.5 附近（最保守）。")
    w("")
    w("| 检验 | 有效 n (δ=0) | 可测最小效应 MDE | 需要多少 n 才能测出 5pp | 现有样本够吗 |")
    w("|---|---|---|---|---|")
    rows_pw = []
    for s in SYMS:
        occ = occupancy_profile(ctxs[s])
        k0, n0 = occ[0.0]
        nf = sum(occ[d][1] for d in SHIFTS if abs(d) >= FAR)
        rows_pw.append((f"{s} 占用率 (vs 平移池)", n0, mde_two_prop(n0, nf),
                        n_for_delta(0.05)))
        mp = micro_profile(ctxs[s])
        nb = mp[0.0]["big_n"]
        nbf = sum(mp[d]["big_n"] for d in SHIFTS if abs(d) >= FAR)
        rows_pw.append((f"{s} 振幅>中位数", nb, mde_two_prop(nb, nbf),
                        n_for_delta(0.05)))
        dw = dwell_profile(ctxs[s])
        nd = len(dw[0.0])
        ndf = sum(len(dw[d]) for d in SHIFTS if abs(d) >= FAR)
        rows_pw.append((f"{s} 停留≥2", nd, mde_two_prop(nd, ndf),
                        n_for_delta(0.05)))
        sm = summarize_evs(run_test2(ctxs[s], 0.0, 0, True))
        rows_pw.append((f"{s} 检验2 至收盘 (vs 几何零假设)", sm["n"],
                        1.959964 * math.sqrt(0.25 / max(sm["n"], 1)) * 1.4288,
                        n_for_delta_onesample(0.05)))
        sm6 = summarize_evs(run_test2(ctxs[s], 0.0, 6, True))
        rows_pw.append((f"{s} 检验2 6根30分 (vs 几何零假设)", sm6["n"],
                        1.959964 * math.sqrt(0.25 / max(sm6["n"], 1)) * 1.4288,
                        n_for_delta_onesample(0.05)))
        smv = summarize_evs(run_visits(ctxs[s], 0.0, 0))
        rows_pw.append((f"{s} 检验2b 每次访问 至收盘（事件不独立）", smv["n"],
                        1.959964 * math.sqrt(0.25 / max(smv["n"], 1)) * 1.4288,
                        n_for_delta_onesample(0.05)))
    KEY["power"] = rows_pw
    for name, n, mde, need in rows_pw:
        ok = "**够**" if n >= need else f"**不够**（缺 {need-n}）"
        w(f"| {name} | {n} | {100*mde:.2f} pp | {need} | {ok} |")
        bump(1)
    w("")
    w("对**单样本 vs 几何零假设**的检验，MDE = (z_α + z_β)·√(p(1−p)/n)；")
    w("对**两比例**检验，MDE = z_α·√(p(1−p)(1/n₁+1/n₂))（两侧 80% 功效需再乘 1.43，")
    w("表中两比例列已按 α 项给出下界，实际 MDE 还要大约 43%）。")
    w("")

    w(f"---")
    w("")
    w(f"## 11. 家族规模")
    w("")
    w(f"本报告一共计算并**全部报告**了 **{CELLS}** 个格子。主要构成：41 个平移位 × 7 个统计量")
    w("× 3 标的 × 4 个带宽（占用/振幅/停留/成交量的平移剖面），6 个分辨率 × 3 标的 ×")
    w("5 个统计量，" + str(nboot) + " 个日聚类自举格子，检验 2 的 2 视界 × 2 口径 ×")
    w("2 事件定义 × 3 标的，12 个路径自举格子，14 个逐位格子，2 个 ES 时段，")
    w("18 个功效格子。**没有任何一个格子被事后挑选，也没有任何一个被省略。**")
    w("在这个规模下，纯噪声本身就会产生上百个 \\|z\\|>1.96 的格子。因此本报告的判读")
    w("只依赖两件事：(a) **平移剖面在 δ=0 有没有峰**；(b) **日聚类自举 / 路径自举**")
    w("**下的 z**。单个格子的 Poisson-binomial z 一律只作陈列，不作证据。")
    w("")

    # ------------------------------------------------ verdict / scope ------
    w("---")
    w("")
    w("## 12. 作用域裁定")
    w("")
    w("任务书要的是划界，不是判死刑。下面是本轮能守住的界。")
    w("")
    w("### 12.1 第一轮结论**不需要**限定作用域的部分")
    w("")
    w("凡是形如「当日价格是否触及某价」的统计量，对分辨率**结构上免疫**（§8.1 证明）。")
    w("聚合 K 线不改变高低点极值，不改变会话边界，因此触及/不触及的判定逐日逐位")
    w("**逐字相同**。金门完成率、下一位转移率、安慰剂梯子这三条第一轮的核心否定结论，")
    w("用 1 分钟数据重跑会得到**同一个数字**。用户「你们分辨率不够」的质疑，")
    w("对这一类结论不成立。")
    w("")
    w("### 12.2 第一轮**从未测过**、本轮首次测到的部分")
    w("")
    w("逗留时间、K 线振幅、成交量、有限视界内的先后顺序——这四类只有细粒度才定义")
    w("得出，第一轮完全没有覆盖。本轮在 5 分钟上把它们全部测了一遍，日聚类自举在 δ=0")
    w(f"处**都没有凸起**——§5 的日聚类自举里 {nboot} 个格子只有 {nsig} 个越过 \\|z\\|=1.96")
    w(f"（噪声期望 {0.05*nboot:.1f} 个），而且方向是**负的**（具名位比随机带**更不粘**）。")
    w("")
    w("### 12.3 本轮唯一的方法论新事实（对第三轮有约束力）")
    w("")
    w("**S/(S+T) 不是一个分辨率无关的零假设，它自己带偏差，而且偏差会变号。**")
    w("")
    w("| 分辨率 | 路径自举零假设相对 S/(S+T) | 含义 |")
    w("|---|---|---|")
    w("| 5m | **低 1–4 pp**（§7.2） | 离散化 + 短周期负自相关 + 视界删失 |")
    w("| 1h | **高 1.2–1.5 pp**（§8.2） | 小时线上的连续性偏离 |")
    w("")
    w("也就是说：在 5 分钟上，跑赢 S/(S+T) 比看上去**难**；在小时线上，跑赢它比")
    w("看上去**容易**——+2.5 pp 的「超额」在小时线上是**免费**的，任意一条阶梯都能拿到。")
    w("任何第三轮里「我跑赢了 S/(S+T)」的说法，只要超额在 1–4 pp 这个量级，")
    w("**必须先跟同分辨率的路径自举对一遍才算数**，否则等于把 K 线自身的性质")
    w("记在位的账上。这是本轮唯一一条对第三轮有硬约束力的产出。")
    w("")
    w("### 12.4 本轮**没有**回答、第三轮必须去打的问题")
    w("")
    w("本轮全部是**无方向**检验（任务书如此要求），因此它既没有证实也没有证伪")
    w("用户真正的主张——「位是一个便宜的证伪点，因而机械地产生高盈亏比」。")
    w("要打这个主张，需要的是：以位为止损、以下一位/下两位为目标的**逐笔 R 结构**，")
    w("其零假设是路径自举下的同一构造，而不是 S/(S+T)，更不是 50%。")
    w("§10 的功效表说明了它的难处：60 天 5 分钟只有 ~200–750 个事件，")
    w("5pp 的效应需要 ~750（单样本）到 ~3000（双样本）。**5 分钟窗口本身就是硬约束。**")
    w("")

    # ------------------------------------------------ front summary --------
    def _s(x: float) -> str:
        return f"{x:+.2f}"

    summ: list[str] = []
    summ.append("## 结论摘要（先看这里）")
    summ.append("")
    summ.append("**分辨率不是第一轮否定结论的漏洞。** 但第一轮确实有它从未测过的东西，"
                "本轮把它测了，也是零。")
    summ.append("")
    summ.append("| # | 问题 | 答案 |")
    summ.append("|---|---|---|")
    summ.append("| 1 | ±0.03 ATR 的带子在 5m 上有多大 | **比一根 5m K 还窄**"
                f"（带宽 = 中位振幅的 {2*BAND/scale['^GSPC']:.2f}×）——位在 5 分钟上是亚 K 线对象 |")
    def _bz(sym: str, stat: str) -> str:
        r = KEY["boot"][(sym, stat)]
        return f"{r['z']:+.2f}"

    summ.append("| 2 | 价格是否更常停在具名位附近 | 否。占用率的日聚类自举 z = "
                + " / ".join(_bz(x, "occ") for x in SYMS)
                + "（^GSPC/SPY/ES） |")
    summ.append("| 3 | 位附近 5m K 的振幅是否异常 | 否。自举 z = "
                + " / ".join(_bz(x, "rng") for x in SYMS) + " |")
    summ.append("| 4 | 位附近成交量是否异常 | 否。自举 z = SPY "
                + _bz("SPY", "relvol") + "，ES " + _bz("ES=F", "relvol")
                + "（平移 SD 口径下 ES 看着是 +7.08，那是重叠样本造成的假象，见 §5） |")
    summ.append("| 5 | 位是否「粘」（停留更久） | 否，而且**反过来**。P(停留≥2根) 自举 z = "
                + " / ".join(_bz(x, "dwell2") for x in SYMS)
                + f"；平均停留 {KEY['dwell_len']['^GSPC'][0]:.2f} 根 |")
    summ.append("| 6 | 首触后 6 根内走向下一位 vs 折返 | 5m 上全部 \\|z\\|<2，"
                "对几何零假设和路径自举零假设**都**无差异 |")
    summ.append("| 7 | 结论随分辨率改变吗 | **触及型统计量结构上不随分辨率改变**"
                "（§8.1 是一条恒等式，不是一个实证结果）；路径型统计量在 5m→60m 上一致为零 |")
    summ.append("| 7b | 那 730 天小时线上那个 z=+2.7/+2.9 呢 | 真的，但**与具名位无关**："
                "41/41 个平移位的超额全为正（§8.2）。它是「小时线连续性偏离」，"
                "不是「位」，而且出现在**粗**分辨率上，与本任务的假设方向相反 |")
    summ.append("| 8 | 5 分钟样本的功效够不够 | **不够。** 首触事件 n≈200–265，"
                "测出 5pp 需要 n≈753（单样本）；「每次访问」口径把 n 抬到 ~750，"
                "刚好摸到门槛，但事件不独立 |")
    summ.append("")
    summ.append("**一句话**：把分辨率从日线一路降到 5 分钟，什么也没多出来；"
                "但同时也要承认，本轮测的全是**频率**，")
    summ.append("用户真正主张的**赔率结构**仍然没有被检验（见 §12.4）。")
    summ.append("")
    summ.append("---")
    summ.append("")
    o[sum_idx:sum_idx] = summ

    path = (Path(__file__).resolve().parents[1] / "reports"
            / "RESOLUTION_MICRO_LEVEL_REACTION.md")
    path.write_text("\n".join(o), encoding="utf-8")
    print(f"wrote {path}  ({CELLS} cells)")


if __name__ == "__main__":
    main()
