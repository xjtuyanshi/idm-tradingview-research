"""0DTE SPX execution reality — what the option layer does to every statistic
we measured on the underlying.

Every prior study in `research/satylab` measured the *index*.  The user trades
0DTE SPX options.  Those are not the same instrument and the mapping between
them is neither linear nor time-invariant:

  * P&L is delta*dS + 0.5*gamma*dS^2 + theta*dt, and all three coefficients
    move by an order of magnitude between 09:30 and 15:45.
  * The option has a *drift* the index does not have: the variance risk
    premium.  A statement like "this level is a coin flip on the index" maps
    to "this level is a losing trade in long premium" unless the edge is
    bigger than the premium being paid.

This module measures, from data actually on disk plus ^VIX1D (Cboe 1-day
implied vol, live since 2023-04-24):

  1. the intraday variance clock (what fraction of the session's variance is
     left at each minute)  -> the true shape of theta for 0DTE
  2. implied (VIX1D) vs realized 1-day vol  -> the size of the headwind
  3. Black-Scholes greeks and P&L for a 0.236-ATR move at open / midday / close
  4. the breakeven move-rate (points per hour) by entry time
  5. option-layer R:R vs underlying R:R for a symmetric level trade
  6. empirical travel time: how long SPX actually takes to move 0.236 ATR
  7. execution cost as a fraction of the payoff

Conventions
-----------
r = q = 0.  Over 6.5 hours at 4% that is ~0.22 index points on a 7400 index,
which is inside the bid-ask spread; carrying it would add false precision.

Vol is carried as `M` = the 1-sigma remaining move **in index points**
(M = S * sigma * sqrt(T)).  This keeps every number readable and sidesteps
the annualization blow-up that makes quoted 0DTE IV meaningless after 15:00.

Rule 5 of the project charter is honoured: no ^GSPC daily open anywhere.
Opens come from SPY or from the 5-minute grid.
"""

from __future__ import annotations

import math
import statistics as st
from collections import defaultdict
from datetime import date

from . import data, levels
from .stats import fmt_rate, wilson

# ---------------------------------------------------------------- BS engine

SQRT2PI = math.sqrt(2 * math.pi)


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs(S: float, K: float, M: float, call: bool = True) -> dict:
    """Black-Scholes with r=q=0, parameterised by remaining 1-sigma move `M`
    in price units (M = S*sigma*sqrt(T)).

    Returns price and greeks in *practical* units:
        delta   : d(option) / d(index point)
        gamma   : d(delta)  / d(index point)
        vega_M  : d(option) / d(M)    -- sensitivity to remaining vol, in pts
    """
    if M <= 1e-9:
        intr = max(S - K, 0.0) if call else max(K - S, 0.0)
        return {"price": intr, "delta": (1.0 if S > K else 0.0) if call
                else (-1.0 if S < K else 0.0), "gamma": 0.0, "vega_M": 0.0}
    v = M / S                                   # total vol sigma*sqrt(T)
    d1 = (math.log(S / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if call:
        price = S * _ncdf(d1) - K * _ncdf(d2)
        delta = _ncdf(d1)
    else:
        price = K * _ncdf(-d2) - S * _ncdf(-d1)
        delta = _ncdf(d1) - 1.0
    gamma = _npdf(d1) / (S * v)
    return {"price": price, "delta": delta, "gamma": gamma,
            "vega_M": S * _npdf(d1) / S}        # dPrice/dM = phi(d1)


def strike_for_delta(S: float, M: float, target_delta: float,
                     call: bool = True) -> float:
    """Solve for the strike whose delta is `target_delta` (bisection)."""
    lo, hi = S * 0.90, S * 1.10
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        d = bs(S, mid, M, call)["delta"]
        if call:
            if d > target_delta:
                lo = mid
            else:
                hi = mid
        else:
            if abs(d) > abs(target_delta):
                hi = mid
            else:
                lo = mid
    return 0.5 * (lo + hi)


# ------------------------------------------------------- 1. variance clock

RTH_SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in range(0, 60, 5)]
RTH_SLOTS = [s for s in RTH_SLOTS if "09:30" <= s <= "15:55"]


def variance_clock(symbol: str = "SPY") -> dict:
    """Realized variance per 5-minute slot, as a fraction of the RTH session.

    Uses log(high/low)^2 / (4 ln 2)  (Parkinson) *and* squared 5m log returns,
    reported side by side.  Parkinson is ~5x more efficient per bar, which
    matters at n=60 sessions; squared returns are the unbiased benchmark.
    """
    bars = data.fine(symbol)
    sess = data.group_by_day(bars)
    park: dict[str, list[float]] = defaultdict(list)
    sqr: dict[str, list[float]] = defaultdict(list)
    ndays = 0
    for day, rows in sess.items():
        rows = [b for b in rows if "09:30" <= b.hhmm <= "15:55"]
        if len(rows) < 70:
            continue
        ndays += 1
        for i, b in enumerate(rows):
            if b.high > 0 and b.low > 0:
                park[b.hhmm].append(math.log(b.high / b.low) ** 2
                                    / (4 * math.log(2)))
            if i > 0 and rows[i - 1].close > 0:
                sqr[b.hhmm].append(math.log(b.close / rows[i - 1].close) ** 2)
    slots = sorted(park)
    pk = {s: st.mean(park[s]) for s in slots}
    sq = {s: st.mean(sqr[s]) for s in slots if sq_ok(sqr, s)}
    tot_pk = sum(pk.values())
    # cumulative *remaining* fraction of session variance at the START of slot
    remain: dict[str, float] = {}
    run = 0.0
    for s in slots:
        remain[s] = (tot_pk - run) / tot_pk
        run += pk[s]
    remain["16:00"] = 0.0
    return {"symbol": symbol, "ndays": ndays, "slots": slots,
            "park": pk, "sqr": sq, "total_park": tot_pk, "remain": remain}


def sq_ok(d, s) -> bool:
    return len(d.get(s, [])) > 0


def remaining_frac(clock: dict, hhmm: str) -> float:
    """Fraction of the session's variance still ahead at time `hhmm`."""
    if hhmm >= "16:00":
        return 0.0
    if hhmm <= "09:30":
        return 1.0
    slots = clock["slots"]
    for s in slots:
        if s >= hhmm:
            return clock["remain"][s]
    return 0.0


# -------------------------------------------------- 2. implied vs realized

def vrp_study() -> dict:
    """VIX1D (implied 1-day vol) vs what actually happened the next day.

    Two readings of VIX1D's close are tested because the index rolls to the
    next expiry late in the day:
        (a) close(t) -> |close(t+1)/close(t) - 1|      (close-to-close)
        (b) close(t) -> |close(t+1)/open(t+1) - 1|     (open-to-close only)
    SPY is used for prices (rule 5: never ^GSPC daily open).
    """
    vix1d = {b.day: b.close for b in data.load("^VIX1D", "5y", "1d")}
    spy = data.daily("SPY")
    spy = [b for b in spy if b.day >= min(vix1d)]
    out = {"cc": [], "oc": [], "days": []}
    for i in range(1, len(spy)):
        prev, cur = spy[i - 1], spy[i]
        iv = vix1d.get(prev.day)
        if iv is None or iv <= 0 or prev.close <= 0 or cur.open <= 0:
            continue
        sig_1d = (iv / 100.0) / math.sqrt(252.0)      # 1-day sigma, fractional
        rc = abs(math.log(cur.close / prev.close))
        ro = abs(math.log(cur.close / cur.open))
        out["cc"].append((sig_1d, rc))
        out["oc"].append((sig_1d, ro))
        out["days"].append(cur.day)
    return out


def ratio_summary(pairs: list[tuple[float, float]]) -> dict:
    """E|r| / (implied E|r|).  For a normal, E|r| = sigma*sqrt(2/pi)."""
    k = math.sqrt(2.0 / math.pi)
    exp_abs = [k * s for s, _ in pairs]
    act_abs = [r for _, r in pairs]
    n = len(pairs)
    ratio = sum(act_abs) / sum(exp_abs)
    # straddle P&L in sigma-normalised units: |r| - 0.7979*sigma
    pnl = [r - k * s for s, r in pairs]
    # ... and as a fraction of the premium paid
    pnl_pct = [(r - k * s) / (k * s) for s, r in pairs]
    wins = sum(1 for p in pnl if p > 0)
    return {"n": n, "ratio": ratio, "wins": wins,
            "win_rate": wins / n if n else 0.0,
            "mean_pnl_pct": st.mean(pnl_pct),
            "median_pnl_pct": st.median(pnl_pct),
            "se_pnl_pct": st.stdev(pnl_pct) / math.sqrt(n) if n > 2 else 0.0}


# --------------------------------------------------- 6. empirical travel time

def travel_time(symbol: str = "SPY", ratio: float = 0.236) -> dict:
    """From each 5-minute mark, how long until the index has moved `ratio`*ATR
    in *either* direction, and how often it never does before 16:00.

    ATR comes from the underlying's own daily bars (prior-session Wilder ATR),
    so SPY-in-SPY-points; the ratio is scale free.
    """
    dbars = data.daily(symbol)
    lv = levels.build(dbars)
    bars = data.fine(symbol)
    sess = data.group_by_day(bars)
    by_start: dict[str, list[float | None]] = defaultdict(list)
    for day, rows in sorted(sess.items()):
        L = lv.get(day)
        if L is None:
            continue
        rows = [b for b in rows if "09:30" <= b.hhmm <= "16:00"]
        if len(rows) < 70:
            continue
        dist = ratio * L.atr
        for i, b in enumerate(rows):
            if b.hhmm not in ("09:30", "10:00", "10:30", "11:00", "11:30",
                              "12:00", "12:30", "13:00", "13:30", "14:00",
                              "14:30", "15:00", "15:30"):
                continue
            ref = b.close
            hit = None
            for j in range(i + 1, len(rows)):
                if rows[j].high >= ref + dist or rows[j].low <= ref - dist:
                    hit = (rows[j].dt - b.dt).total_seconds() / 60.0
                    break
            by_start[b.hhmm].append(hit)
    return {"symbol": symbol, "ratio": ratio, "by_start": dict(by_start)}


# ------------------------------------------------------------ ATR context

def atr_context() -> dict:
    d = data.daily("^GSPC")
    lv = levels.build(d)
    recent = {k: v for k, v in lv.items() if k >= date(2026, 1, 1)}
    last_day = max(lv)
    L = lv[last_day]
    atrs = [v.atr for v in recent.values()]
    pcts = [v.atr / v.anchor for v in recent.values()]
    return {"last_day": last_day, "anchor": L.anchor, "atr": L.atr,
            "spot": d[-1].close,
            "atr_med_2026": st.median(atrs),
            "atr_pct_med_2026": st.median(pcts),
            "d236": 0.236 * L.atr, "d382": 0.382 * L.atr,
            "d618": 0.618 * L.atr}


# ------------------------------------------------------ overnight vs intraday

def overnight_split() -> dict:
    """What share of the 1-day variance happens outside RTH.

    VIX1D prices a ~24h horizon; an intraday 0DTE trade only owns the RTH
    slice.  Getting this wrong mis-states the premium by tens of percent.
    """
    spy = data.daily("SPY")
    spy = [b for b in spy if b.day >= date(2023, 4, 24)]
    on, dayr, cc = [], [], []
    for i in range(1, len(spy)):
        p, c = spy[i - 1], spy[i]
        if p.close <= 0 or c.open <= 0:
            continue
        on.append(math.log(c.open / p.close) ** 2)
        dayr.append(math.log(c.close / c.open) ** 2)
        cc.append(math.log(c.close / p.close) ** 2)
    return {"n": len(on), "var_on": st.mean(on), "var_day": st.mean(dayr),
            "var_cc": st.mean(cc),
            "share_on": st.mean(on) / (st.mean(on) + st.mean(dayr))}


# ------------------------------------------- 3. the ladder in sigma units

def ladder_in_sigma() -> dict:
    """Express the Saty ATR ladder in units of the day's *implied* move.

    This is the translation layer the whole project has been missing: option
    prices are quoted in sigma, the level map is drawn in ATR, and the ratio
    between them is neither 1 nor constant.
    """
    vix1d = {b.day: b.close for b in data.load("^VIX1D", "5y", "1d")}
    d = data.daily("^GSPC")
    lv = levels.build(d)
    on = overnight_split()["share_on"]
    rows = []
    prev_day = None
    for b in d:
        L = lv.get(b.day)
        iv = vix1d.get(prev_day) if prev_day else None
        prev_day = b.day
        if L is None or iv is None or iv <= 0:
            continue
        sig_1d_pts = L.anchor * (iv / 100.0) / math.sqrt(252.0)
        sig_rth_pts = sig_1d_pts * math.sqrt(1.0 - on)
        rows.append({"day": b.day, "atr": L.atr, "sig_1d": sig_1d_pts,
                     "sig_rth": sig_rth_pts,
                     "atr_over_sig_rth": L.atr / sig_rth_pts,
                     "atr_over_sig_1d": L.atr / sig_1d_pts})
    r_rth = [x["atr_over_sig_rth"] for x in rows]
    r_1d = [x["atr_over_sig_1d"] for x in rows]
    return {"n": len(rows), "rows": rows,
            "med_atr_over_sig_rth": st.median(r_rth),
            "p10": sorted(r_rth)[len(r_rth) // 10],
            "p90": sorted(r_rth)[9 * len(r_rth) // 10],
            "med_atr_over_sig_1d": st.median(r_1d),
            "overnight_share": on}


# --------------------------------- 4. 0DTE straddle P&L by entry time

ENTRY_SLOTS = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]


def straddle_by_entry(clock_symbol: str = "SPY") -> dict:
    """Buy an ATM 0DTE straddle at each hourly mark, hold to the 16:00 print.

    Cost  = 0.7979 * M(t),  M(t) = S_t * sqrt(rth_implied_var * remaining(t))
    Payoff= |S_close - S_t|

    Implied RTH variance is VIX1D (a ~24h number) scaled by the realized
    intraday share of variance.  That assumption is stress-tested by the
    `on_share` sweep in the driver.
    """
    clock = variance_clock(clock_symbol)
    vix1d = {b.day: b.close for b in data.load("^VIX1D", "5y", "1d")}
    dbars = data.daily("^GSPC")
    dclose = {b.day: b.close for b in dbars}
    prevday = {}
    for i in range(1, len(dbars)):
        prevday[dbars[i].day] = dbars[i - 1].day
    hb = data.hourly("^GSPC")
    sess = data.group_by_day(hb)
    on = overnight_split()["share_on"]
    out: dict[str, list[float]] = defaultdict(list)
    prem: dict[str, list[float]] = defaultdict(list)
    ndays = 0
    for day, rows in sorted(sess.items()):
        pd_ = prevday.get(day)
        iv = vix1d.get(pd_) if pd_ else None
        close = dclose.get(day)
        if iv is None or iv <= 0 or close is None:
            continue
        marks = {b.hhmm: b for b in rows}
        if "09:30" not in marks:
            continue
        ndays += 1
        S0 = marks["09:30"].open
        sig_rth = S0 * (iv / 100.0) / math.sqrt(252.0) * math.sqrt(1.0 - on)
        for slot in ENTRY_SLOTS:
            b = marks.get(slot)
            if b is None:
                continue
            S = b.open if slot == "09:30" else b.open
            M = sig_rth * math.sqrt(remaining_frac(clock, slot))
            if M <= 0.5:
                continue
            cost = 0.7979 * M
            payoff = abs(close - S)
            out[slot].append(payoff / cost - 1.0)
            prem[slot].append(cost)
    return {"ndays": ndays, "pnl": dict(out), "prem": dict(prem),
            "clock": clock, "on_share": on}


def summarize_slots(d: dict) -> list[dict]:
    res = []
    for slot in ENTRY_SLOTS:
        v = d["pnl"].get(slot)
        if not v:
            continue
        n = len(v)
        mean = st.mean(v)
        se = st.stdev(v) / math.sqrt(n)
        wins = sum(1 for x in v if x > 0)
        res.append({"slot": slot, "n": n, "mean": mean, "se": se,
                    "t": mean / se if se else 0.0,
                    "median": st.median(v), "win": wins,
                    "win_rate": wins / n,
                    "avg_prem": st.mean(d["prem"][slot])})
    return res


# ------------------------- 5. breakeven move & directional accuracy needed

def breakeven_table(clock: dict, S: float, sig_rth: float,
                    ratio_real_over_impl: float) -> list[dict]:
    """For a long ATM 0DTE call entered at each slot and held to the close:
    premium, delta, gamma, the underlying move needed to break even at expiry,
    and the directional hit-rate needed to break even.
    """
    rows = []
    for slot in ENTRY_SLOTS:
        rf = remaining_frac(clock, slot)
        M = sig_rth * math.sqrt(rf)
        g = bs(S, S, M, True)
        call = g["price"]
        # held to expiry: need S_close - K > premium
        be_move = call
        # required directional accuracy p:  p * E|dS| = premium
        e_abs = 0.7979 * M * ratio_real_over_impl
        p_req = call / e_abs if e_abs > 0 else float("nan")
        rows.append({"slot": slot, "remain_var": rf, "M": M,
                     "call": call, "straddle": 2 * call,
                     "delta": g["delta"], "gamma": g["gamma"],
                     "be_move": be_move, "p_req": p_req,
                     "e_abs": e_abs})
    return rows


def theta_profile(clock: dict, S: float, sig_rth: float) -> list[dict]:
    """Premium remaining and the hourly bleed, on the *empirical* clock."""
    slots = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30",
             "15:30", "16:00"]
    rows = []
    for i, slot in enumerate(slots):
        rf = remaining_frac(clock, slot)
        M = sig_rth * math.sqrt(rf)
        strad = 2 * bs(S, S, M, True)["price"] if M > 0 else 0.0
        prev = rows[-1]["straddle"] if rows else None
        rows.append({"slot": slot, "remain_var": rf, "M": M,
                     "straddle": strad,
                     "decay_pts": (prev - strad) if prev is not None else 0.0,
                     "decay_pct": ((prev - strad) / prev * 100.0)
                     if prev else 0.0})
    return rows


# ------------------------------ 7. the level-reaction trade, both layers

def level_trade(S: float, sig_rth: float, clock: dict, slot: str,
                stop_pts: float, target_pts: float,
                minutes_to_resolve: float, delta_target: float = 0.50,
                spread_pts: float = 0.30) -> dict:
    """A symmetric 'reaction at a level' trade priced in both layers.

    Underlying layer : risk `stop_pts`, reward `target_pts`  -> R:R fixed.
    Option layer     : buy a call of delta `delta_target`, hold until the
                       underlying resolves to +target or -stop after
                       `minutes_to_resolve`, then mark the option.

    The point of the function is that the option R:R is *not* the underlying
    R:R, and the difference is not free.
    """
    rf0 = remaining_frac(clock, slot)
    M0 = sig_rth * math.sqrt(rf0)
    K = strike_for_delta(S, M0, delta_target, True)
    entry = bs(S, K, M0, True)
    # clock forward
    hh, mm = int(slot[:2]), int(slot[3:])
    tot = hh * 60 + mm + minutes_to_resolve
    later = f"{int(tot // 60):02d}:{int(tot % 60):02d}"
    rf1 = remaining_frac(clock, later)
    M1 = sig_rth * math.sqrt(rf1)
    up = bs(S + target_pts, K, M1, True)
    dn = bs(S - stop_pts, K, M1, True)
    ep = entry["price"] + spread_pts / 2
    win = up["price"] - spread_pts / 2 - ep
    loss = ep - (dn["price"] - spread_pts / 2)
    return {"slot": slot, "later": later, "K": K, "entry": entry["price"],
            "entry_delta": entry["delta"], "entry_gamma": entry["gamma"],
            "M0": M0, "M1": M1,
            "opt_win": win, "opt_loss": loss,
            "opt_rr": win / loss if loss > 0 else float("inf"),
            "und_rr": target_pts / stop_pts,
            "be_wr_opt": loss / (win + loss) if (win + loss) > 0 else 1.0,
            "be_wr_und": stop_pts / (stop_pts + target_pts),
            "spread_frac_of_win": spread_pts / win if win > 0 else float("inf")}


# --------------------------- 8. the time limit the ATR ladder cannot show

def barrier_mc(clock: dict, S: float, sig_impl: float, slot: str,
               stop_pts: float, target_pts: float,
               vol_ratio: float = 0.901, n_paths: int = 200_000,
               seed: int = 12345) -> dict:
    """SUPERSEDED -- DO NOT USE.  Kept only so the report's audit trail is
    reproducible.  Use `barrier_deadline` instead.

    This version steps on the raw 5-minute grid with no Brownian-bridge
    correction.  Step sd is ~5.4 index points against an 18.3-point stop, so
    barrier touches inside a step are missed and P(target) comes out several
    points too low; the shrinking-barrier limit diverges to ~46% instead of
    converging to stop/(stop+target).  `barrier_deadline` fixes this and
    passes both validation hooks.

    First-passage with a HARD DEADLINE at 16:00.

    The optional-stopping identity P(target first) = stop/(stop+target) holds
    only with unlimited time.  A 0DTE session has ~6.5 hours of variance and
    then the instrument ceases to exist.  This measures how much of the
    ladder's implied probability the deadline removes.

    The path is simulated at *realized* vol (sig_impl * vol_ratio); the option
    is marked at *implied* vol.  That asymmetry is the variance risk premium,
    measured in `vrp_study`.
    """
    import random
    rnd = random.Random(seed)
    slots = [s for s in clock["slots"] if s >= slot]
    if not slots:
        return {}
    # per-slot variance shares of the *remaining* session
    shares = [clock["park"][s] for s in slots]
    tot = sum(shares)
    shares = [x / tot for x in shares]
    rf = remaining_frac(clock, slot)
    V_impl = (sig_impl ** 2) * rf
    V_real = V_impl * (vol_ratio ** 2)
    steps = [math.sqrt(V_real * w) for w in shares]

    hit_t = hit_s = neither = 0
    exit_slot_t: list[str] = []
    exit_slot_s: list[str] = []
    end_moves: list[float] = []
    for _ in range(n_paths):
        x = 0.0
        out = None
        for i, sd in enumerate(steps):
            x += rnd.gauss(0.0, sd)
            if x >= target_pts:
                out = ("T", slots[i]); break
            if x <= -stop_pts:
                out = ("S", slots[i]); break
        if out is None:
            neither += 1
            end_moves.append(x)
        elif out[0] == "T":
            hit_t += 1; exit_slot_t.append(out[1])
        else:
            hit_s += 1; exit_slot_s.append(out[1])
    n = n_paths
    naive = stop_pts / (stop_pts + target_pts)
    return {"slot": slot, "n": n, "p_target": hit_t / n, "p_stop": hit_s / n,
            "p_neither": neither / n, "naive_p_target": naive,
            "remain_var": rf, "M_impl": sig_impl * math.sqrt(rf),
            "exit_slot_t": exit_slot_t, "exit_slot_s": exit_slot_s,
            "end_moves": end_moves}


def barrier_option_ev(clock: dict, S: float, sig_impl: float, slot: str,
                      stop_pts: float, target_pts: float,
                      delta_target: float = 0.30, spread_pts: float = 0.30,
                      vol_ratio: float = 0.901, n_paths: int = 60_000,
                      seed: int = 999) -> dict:
    """SUPERSEDED -- DO NOT USE.  Use `option_on_barrier` instead.

    Same uncorrected 5-minute stepping as `barrier_mc`; it fails the
    no-arbitrage self-check (long-option expectancy came out +0.4% to +0.8%
    at vol_ratio=1.0 and zero spread, where it must be 0).  Kept for the
    audit trail only.

    Same trade, but marking a real option at every exit.

    Long a `delta_target` call.  Exit when the underlying touches +target or
    -stop, or hold to the 16:00 settlement.  Compare the option's expectancy
    with the underlying's expectancy over the identical path set.
    """
    import random
    rnd = random.Random(seed)
    slots = [s for s in clock["slots"] if s >= slot]
    shares = [clock["park"][s] for s in slots]
    tot = sum(shares)
    shares = [x / tot for x in shares]
    rf = remaining_frac(clock, slot)
    V_impl = (sig_impl ** 2) * rf
    steps = [math.sqrt(V_impl * (vol_ratio ** 2) * w) for w in shares]
    M0 = sig_impl * math.sqrt(rf)
    K = strike_for_delta(S, M0, delta_target, True)
    entry_px = bs(S, K, M0, True)["price"] + spread_pts / 2

    opt_r, und_r = [], []
    for _ in range(n_paths):
        x = 0.0
        done = False
        for i, sd in enumerate(steps):
            x += rnd.gauss(0.0, sd)
            if x >= target_pts or x <= -stop_pts:
                nxt = slots[i + 1] if i + 1 < len(slots) else "16:00"
                M1 = sig_impl * math.sqrt(remaining_frac(clock, nxt))
                px = bs(S + x, K, M1, True)["price"] - spread_pts / 2
                opt_r.append((px - entry_px) / entry_px)
                und_r.append(target_pts / stop_pts if x >= target_pts else -1.0)
                done = True
                break
        if not done:
            px = max(S + x - K, 0.0)          # cash settlement, no exit spread
            opt_r.append((px - entry_px) / entry_px)
            und_r.append(x / stop_pts)
    return {"slot": slot, "K": K, "entry_px": entry_px, "M0": M0,
            "opt_mean": st.mean(opt_r), "opt_median": st.median(opt_r),
            "opt_win": sum(1 for r in opt_r if r > 0) / len(opt_r),
            "und_mean_R": st.mean(und_r),
            "und_win": sum(1 for r in und_r if r > 0) / len(und_r),
            "n": len(opt_r)}


# ------------------------------- 9. how long a 0.236-ATR move actually takes

def travel_report(symbol: str = "SPY", ratio: float = 0.236) -> str:
    d = travel_time(symbol, ratio)
    lines = [f"travel to +/-{ratio} ATR  [{symbol}, 5m, 60d]",
             f"{'from':>6} {'n':>5} {'reached':>18} {'median min':>11} "
             f"{'p25':>6} {'p75':>6}"]
    for slot in ["09:30", "10:00", "10:30", "11:00", "11:30", "12:00",
                 "12:30", "13:00", "13:30", "14:00", "14:30", "15:00",
                 "15:30"]:
        v = d["by_start"].get(slot)
        if not v:
            continue
        got = [x for x in v if x is not None]
        n = len(v)
        if got:
            got.sort()
            med = got[len(got) // 2]
            p25 = got[len(got) // 4]
            p75 = got[3 * len(got) // 4]
        else:
            med = p25 = p75 = float("nan")
        lines.append(f"{slot:>6} {n:>5} {fmt_rate(len(got), n):>18} "
                     f"{med:>11.0f} {p25:>6.0f} {p75:>6.0f}")
    return "\n".join(lines)


# ------------------- 8b. barrier MC done properly (Brownian-bridge corrected)

def _bridge_mc(step_sd: list[float], slots: list[str], stop_pts: float,
               target_pts: float, n_paths: int, seed: int,
               sub: int = 1) -> dict:
    """First passage to +target / -stop with a hard deadline.

    Discrete-step MC misses barrier touches that happen *inside* a step; with
    5m steps (sd ~5 pts) against an 18-pt stop that bias is large enough to
    move P(target) by many points.  Each step therefore gets the exact
    Brownian-bridge crossing probability

        P(max >= a | x0, x1) = exp(-2 (a-x0)(a-x1) / s^2)

    on top of the endpoint test, and each 5m slot is split into `sub`
    sub-steps so the residual bias is negligible.
    """
    import random
    rnd = random.Random(seed)
    gauss, rand, exp = rnd.gauss, rnd.random, math.exp
    sds, sslot = [], []
    for sd, sl in zip(step_sd, slots):
        s = sd / math.sqrt(sub)
        for _ in range(sub):
            sds.append(s)
            sslot.append(sl)
    var = [s * s for s in sds]
    a, b = target_pts, stop_pts
    ht = hs = nz = both = 0
    t_slot, s_slot, ends = [], [], []
    for _ in range(n_paths):
        x = 0.0
        res = None
        for i, s in enumerate(sds):
            x1 = x + gauss(0.0, s)
            if x1 >= a:
                res = ("T", sslot[i]); break
            if x1 <= -b:
                res = ("S", sslot[i]); break
            v2 = var[i]
            pu = exp(-2.0 * (a - x) * (a - x1) / v2) if v2 > 0 else 0.0
            pd = exp(-2.0 * (x + b) * (x1 + b) / v2) if v2 > 0 else 0.0
            u, dn = rand() < pu, rand() < pd
            if u and dn:
                both += 1
                res = ("T", sslot[i]) if rand() < pu / (pu + pd) \
                    else ("S", sslot[i])
                break
            if u:
                res = ("T", sslot[i]); break
            if dn:
                res = ("S", sslot[i]); break
            x = x1
        if res is None:
            nz += 1; ends.append(x)
        elif res[0] == "T":
            ht += 1; t_slot.append(res[1])
        else:
            hs += 1; s_slot.append(res[1])
    n = n_paths
    return {"n": n, "p_target": ht / n, "p_stop": hs / n, "p_neither": nz / n,
            "both_in_one_step": both / n, "t_slot": t_slot, "s_slot": s_slot,
            "ends": ends}


def barrier_deadline(clock: dict, sig_impl: float, slot: str,
                     stop_pts: float, target_pts: float,
                     vol_ratio: float = 0.901, n_paths: int = 60_000,
                     seed: int = 4242, sub: int = 8,
                     var_mult: float = 1.0) -> dict:
    """Public wrapper: remaining-variance schedule from the empirical clock.

    `var_mult` inflates the remaining variance; setting it large makes the
    deadline non-binding and the result must then converge to the textbook
    stop/(stop+target).  That is the validation hook.
    """
    slots = [s for s in clock["slots"] if s >= slot]
    if not slots:
        return {}
    shares = [clock["park"][s] for s in slots]
    tot = sum(shares)
    rf = remaining_frac(clock, slot)
    V = (sig_impl ** 2) * rf * (vol_ratio ** 2) * var_mult
    sd = [math.sqrt(V * (w / tot)) for w in shares]
    out = _bridge_mc(sd, slots, stop_pts, target_pts, n_paths, seed, sub)
    out.update({"slot": slot, "remain_var": rf,
                "M_impl": sig_impl * math.sqrt(rf),
                "M_real": math.sqrt(V),
                "naive": stop_pts / (stop_pts + target_pts)})
    return out


def option_on_barrier(clock: dict, S: float, sig_impl: float, slot: str,
                      stop_pts: float, target_pts: float,
                      delta_target: float = 0.30, spread_pts: float = 0.30,
                      vol_ratio: float = 0.901, n_paths: int = 40_000,
                      seed: int = 2027, sub: int = 16) -> dict:
    """The same level trade, marked in BOTH layers on the SAME paths.

    Underlying: +target/-stop, and whatever partial the deadline leaves.
    Option    : long `delta_target` call, exited at the touch (paying spread)
                or cash-settled at 16:00.

    Set vol_ratio=1.0 and spread_pts=0.0 and the option expectancy must come
    out at ~0 -- that is the no-arbitrage self-check.
    """
    import random
    rnd = random.Random(seed)
    gauss, rand, exp = rnd.gauss, rnd.random, math.exp
    slots = [s for s in clock["slots"] if s >= slot]
    shares = [clock["park"][s] for s in slots]
    tot = sum(shares)
    rf = remaining_frac(clock, slot)
    V = (sig_impl ** 2) * rf * (vol_ratio ** 2)
    sds, sslot = [], []
    for w in shares:
        sd = math.sqrt(V * (w / tot) / sub)
        for _ in range(sub):
            sds.append(sd)
            sslot.append(w)
    # remaining-variance *after* each sub-step, as a fraction of the session
    rem_after: list[float] = []
    used = 0.0
    ses_tot = clock["total_park"]
    cum0 = sum(clock["park"][x] for x in clock["slots"] if x < slot)
    for w in shares:
        for j in range(sub):
            used += w / sub
            rem_after.append(max(0.0, (ses_tot - cum0 - used) / ses_tot))
    M0 = sig_impl * math.sqrt(rf)
    K = strike_for_delta(S, M0, delta_target, True)
    entry = bs(S, K, M0, True)["price"] + spread_pts / 2

    a, b = target_pts, stop_pts
    opt, und = [], []
    for _ in range(n_paths):
        x = 0.0
        res = None
        for i, sd in enumerate(sds):
            x1 = x + gauss(0.0, sd)
            v2 = sd * sd
            if x1 >= a:
                res = (a, i); break
            if x1 <= -b:
                res = (-b, i); break
            pu = exp(-2.0 * (a - x) * (a - x1) / v2)
            pd = exp(-2.0 * (x + b) * (x1 + b) / v2)
            u, d = rand() < pu, rand() < pd
            if u and d:
                res = (a, i) if rand() < pu / (pu + pd) else (-b, i); break
            if u:
                res = (a, i); break
            if d:
                res = (-b, i); break
            x = x1
        if res is None:
            opt.append((max(S + x - K, 0.0) - entry) / entry)
            und.append(x / stop_pts)
        else:
            xr, i = res
            M1 = sig_impl * math.sqrt(rem_after[i])
            px = bs(S + xr, K, M1, True)["price"] - spread_pts / 2
            opt.append((px - entry) / entry)
            und.append(target_pts / stop_pts if xr > 0 else -1.0)
    n = len(opt)
    so = st.stdev(opt) / math.sqrt(n)
    return {"slot": slot, "K": K, "entry": entry, "M0": M0, "n": n,
            "opt_mean": st.mean(opt), "opt_se": so,
            "opt_median": st.median(opt),
            "opt_win": sum(1 for r in opt if r > 0) / n,
            "opt_p90": sorted(opt)[int(0.90 * n)],
            "und_mean_R": st.mean(und),
            "und_win": sum(1 for r in und if r > 0) / n}


def option_on_barrier_drift(clock: dict, S: float, sig_impl: float, slot: str,
                            stop_pts: float, target_pts: float,
                            delta_target: float, spread_pts: float,
                            vol_ratio: float, drift_pts: float,
                            n_paths: int = 30_000, seed: int = 77,
                            sub: int = 16) -> dict:
    """`option_on_barrier` with a directional edge injected.

    `drift_pts` is the TOTAL expected move over the remaining session, in index
    points, in the direction the trade is betting on.  Bisecting it to the
    point where the option's expectancy hits zero converts "how good would a
    signal have to be" into a number the underlying studies can be tested
    against.
    """
    import random
    rnd = random.Random(seed)
    gauss, rand, exp = rnd.gauss, rnd.random, math.exp
    slots = [s for s in clock["slots"] if s >= slot]
    shares = [clock["park"][s] for s in slots]
    tot = sum(shares)
    rf = remaining_frac(clock, slot)
    V = (sig_impl ** 2) * rf * (vol_ratio ** 2)
    sds, mus, rem_after = [], [], []
    ses_tot = clock["total_park"]
    cum0 = sum(clock["park"][x] for x in clock["slots"] if x < slot)
    used = 0.0
    for w in shares:
        sd = math.sqrt(V * (w / tot) / sub)
        mu = drift_pts * (w / tot) / sub
        for _ in range(sub):
            sds.append(sd); mus.append(mu)
            used += w / sub
            rem_after.append(max(0.0, (ses_tot - cum0 - used) / ses_tot))
    M0 = sig_impl * math.sqrt(rf)
    K = strike_for_delta(S, M0, delta_target, True)
    entry = bs(S, K, M0, True)["price"] + spread_pts / 2
    a, b = target_pts, stop_pts
    opt, und = [], []
    ht = 0
    for _ in range(n_paths):
        x = 0.0
        res = None
        for i, sd in enumerate(sds):
            x1 = x + mus[i] + gauss(0.0, sd)
            v2 = sd * sd
            if x1 >= a:
                res = (a, i); break
            if x1 <= -b:
                res = (-b, i); break
            if rand() < exp(-2.0 * (a - x) * (a - x1) / v2):
                res = (a, i); break
            if rand() < exp(-2.0 * (x + b) * (x1 + b) / v2):
                res = (-b, i); break
            x = x1
        if res is None:
            opt.append((max(S + x - K, 0.0) - entry) / entry)
            und.append(x / stop_pts)
        else:
            xr, i = res
            M1 = sig_impl * math.sqrt(rem_after[i])
            px = bs(S + xr, K, M1, True)["price"] - spread_pts / 2
            opt.append((px - entry) / entry)
            und.append(target_pts / stop_pts if xr > 0 else -1.0)
            ht += int(xr > 0)
    n = len(opt)
    return {"opt_mean": st.mean(opt), "und_mean_R": st.mean(und),
            "p_target": ht / n, "entry": entry, "K": K, "n": n,
            "opt_win": sum(1 for r in opt if r > 0) / n}


def edge_required(clock: dict, S: float, sig_impl: float, slot: str,
                  stop_pts: float, target_pts: float, delta_target: float,
                  spread_pts: float, vol_ratio: float = 0.901,
                  n_paths: int = 30_000) -> dict:
    """Bisect the drift that brings the long-option expectancy to zero."""
    lo, hi = 0.0, 4.0 * sig_impl
    base = option_on_barrier_drift(clock, S, sig_impl, slot, stop_pts,
                                   target_pts, delta_target, spread_pts,
                                   vol_ratio, 0.0, n_paths, 5)
    for _ in range(18):
        mid = 0.5 * (lo + hi)
        r = option_on_barrier_drift(clock, S, sig_impl, slot, stop_pts,
                                    target_pts, delta_target, spread_pts,
                                    vol_ratio, mid, n_paths, 5)
        if r["opt_mean"] < 0:
            lo = mid
        else:
            hi = mid
    d = 0.5 * (lo + hi)
    fin = option_on_barrier_drift(clock, S, sig_impl, slot, stop_pts,
                                  target_pts, delta_target, spread_pts,
                                  vol_ratio, d, n_paths, 5)
    return {"slot": slot, "delta": delta_target, "drift_pts": d,
            "base_opt_ev": base["opt_mean"], "base_p_target": base["p_target"],
            "be_p_target": fin["p_target"], "und_R_at_be": fin["und_mean_R"],
            "M": sig_impl * math.sqrt(remaining_frac(clock, slot))}
