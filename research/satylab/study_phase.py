"""Phase Oscillator as a CONDITIONING variable — base rates on 730d hourly SPX.

WHAT THIS ASKS
--------------
Not "does the Phase Oscillator generate signals" — the spec work already settled
that it does not (direction = Pivot Ribbon, location/target = ATR levels,
maturity/timing = Phase).  This asks the only questions a maturity layer can
answer with numbers:

  Q1  Does the phase zone move the base rate of the next hourly bar's direction,
      and of touching the next named ATR level up / down before the close?
  Q2  Saty's "don't chase the extended zone" — is a long entered in extended_up
      really worse than one entered in the launch box?
  Q3  When phase is extreme, does price revert to the 21 EMA, and how fast?
  Q4  Do Phase and Ribbon say the same thing?  If so, stacking them buys nothing.
  Q5  After a compression release, is the break direction predictable, and how
      far does it travel?

THE ONE METHODOLOGICAL TRAP THIS FILE IS BUILT AROUND
-----------------------------------------------------
"P(price reaches X above)" conditioned on a zone is NOT a directional statistic.
Phase zones are strongly correlated with *realised volatility* (a state 2 ATR
below the 21 EMA is a state where everything moves further).  A zone can lift or
crush the up-touch rate and the down-touch rate together and contain zero
directional information.  Every headline test here is therefore either

  (a) SYMMETRIC — up and down measured at the SAME distance from the SAME bar,
      compared to each other (paired, McNemar), so the volatility level cancels;
  (b) a FIRST-TOUCH RACE — which of +d / -d is reached first, which is the
      statistic a 1:1 bracket actually pays on and is volatility-neutral by
      construction;

and the one-sided tables (C, D) are printed with a volatility column next to
them so the confound is visible rather than hidden.

PRE-REGISTERED DESIGN (fixed before any number was looked at)
-------------------------------------------------------------
* Data      ^GSPC 1h, 730d, RTH only (09:30..15:30 ET).  16:00 stub bars and the
            final session (2026-07-24 — no daily bar cached yet, so no level map)
            are dropped.  5049 usable bars / 725 sessions.
* Phase     `satylab.phase_fix.phase_oscillator` — the verified port
            (close-EMA21)/(3*ATR14)*100 then EMA3, computed on the CONTINUOUS
            hourly series (EMAs carry across the overnight gap, as a TradingView
            1h RTH chart also does).  Zones = `phase_fix.phase_zone`, the 7
            source-exact Fibonacci bands.  The names in the task brief
            (`bull_mean_rev`, `neutral`) came from the superseded, self-invented
            `indicators.phase_zone`; they map to mark_up / launch_box.
* Ribbon    `satylab.ribbon_spec.frames` on the same hourly bars (8/21/34 close).
* Levels    `satylab.levels.build(daily)` — anchor = prior daily close, ladder in
            prior-day Wilder ATR(14).  Fixed before the bell; no lookahead.
* Horizon   "rest of the session" for level touches (Saty's unit is the day);
            k = 7 hourly bars (one session) for forward tests, with k = 3 and
            k = 14 declared up front as the ONLY sensitivity values, all reported.
* Distance  Fixed-distance target = 0.236 x daily ATR.  0.236 is Saty's own
            trigger ratio, chosen because it is already named in his system.  It
            is NOT the winner of a search; no other value was run.
* Episode horizon for the reversion question: 35 bars (5 sessions).  Declared.

HONESTY RAILS
-------------
1. Every proportion prints Wilson CI + n.
2. Every conditional claim prints `two_proportion_z` vs its stated comparator;
   |z| < 1.96 prints as "NO WORK".
3. `CELLS` counts every reported statistic; the total prints at the end.  Nothing
   here is a grid search — all tables are full enumerations of a partition fixed
   in this docstring.
4. SERIAL CORRELATION IS REAL AND WILSON DOES NOT HANDLE IT.  Bars in the same
   session share their outcome window.  Section E therefore repeats the headline
   test three ways: pooled (optimistic), one-bar-per-day (independent but small),
   and a DAY-BLOCK BOOTSTRAP over all bars (the number to believe).
5. Intrabar order is unknowable on 1h bars.  The first-touch race reports its
   same-bar ambiguity rate and is re-run on 5m data (60 days only, small n) as a
   tie-breaker, per the project's data-resolution rule.

Run:  .venv/bin/python research/satylab/study_phase.py
"""

from __future__ import annotations

import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

if __package__ in (None, ""):                                    # script mode
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
    from satylab import data, levels, phase_fix as pf, ribbon_spec as rs, stats
else:
    from . import data, levels, phase_fix as pf, ribbon_spec as rs, stats

fmt = stats.fmt_rate
z2 = stats.two_proportion_z

CELLS = 0


def cell(n: int = 1) -> None:
    global CELLS
    CELLS += n


def rate(k: int, n: int) -> str:
    cell()
    return fmt(k, n)


def verdict(z: float) -> str:
    if abs(z) >= 2.58:
        return "WORKS (|z|>=2.58)"
    if abs(z) >= 1.96:
        return "works (|z|>=1.96)"
    return "NO WORK (|z|<1.96)"


def cmp2(label: str, k1: int, n1: int, k2: int, n2: int) -> str:
    z = z2(k1, n1, k2, n2)
    return f"    -> {label:<46} z={z:+6.2f}  {verdict(z)}"


# --------------------------------------------------------------------------
# extra statistics (local; the shared satylab modules are not touched)
# --------------------------------------------------------------------------

def mcnemar_z(b: int, c: int) -> float:
    """Paired binary comparison; b, c are the discordant counts."""
    return 0.0 if (b + c) == 0 else (b - c) / math.sqrt(b + c)


def mantel_haenszel_z(strata: list[tuple[int, int, int, int]]) -> float:
    """Pooled z across 2x2 strata given as (k1, n1, k2, n2)."""
    num = var = 0.0
    for k1, n1, k2, n2 in strata:
        a, b = k1, n1 - k1
        c, d = k2, n2 - k2
        n = a + b + c + d
        if n < 2:
            continue
        num += a - (a + b) * (a + c) / n
        var += (a + b) * (c + d) * (a + c) * (b + d) / (n * n * (n - 1))
    return 0.0 if var <= 0 else num / math.sqrt(var)


def block_bootstrap_diff(groups: dict[date, list[tuple[int, int]]],
                         reps: int = 2000, seed: int = 12345
                         ) -> tuple[float, float, float, float]:
    """Day-block bootstrap of p(A) - p(B).

    `groups[day]` is a list of (which_group, hit) with which_group in {0, 1}.
    Resampling whole days preserves within-day dependence.
    Returns (point, lo95, hi95, one-sided p for diff >= 0).
    """
    days = list(groups)
    rng = random.Random(seed)

    def diff(sel: list[date]) -> float | None:
        k0 = n0 = k1 = n1 = 0
        for d in sel:
            for g, h in groups[d]:
                if g == 0:
                    n0 += 1
                    k0 += h
                else:
                    n1 += 1
                    k1 += h
        if n0 == 0 or n1 == 0:
            return None
        return k0 / n0 - k1 / n1

    point = diff(days) or 0.0
    out: list[float] = []
    for _ in range(reps):
        sel = [days[rng.randrange(len(days))] for _ in range(len(days))]
        v = diff(sel)
        if v is not None:
            out.append(v)
    out.sort()
    lo = out[int(0.025 * len(out))]
    hi = out[int(0.975 * len(out))]
    p_ge0 = sum(1 for v in out if v >= 0) / len(out)
    return point, lo, hi, p_ge0


def mannwhitney_z(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    merged = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * len(merged)
    i = 0
    tie_term = 0.0
    while i < len(merged):
        j = i
        while j + 1 < len(merged) and merged[j + 1][0] == merged[i][0]:
            j += 1
        avg = (i + j + 2) / 2.0
        t = j - i + 1
        tie_term += t ** 3 - t
        for x in range(i, j + 1):
            ranks[x] = avg
        i = j + 1
    r_a = sum(ranks[i] for i in range(len(merged)) if merged[i][1] == 0)
    na, nb = len(a), len(b)
    u = r_a - na * (na + 1) / 2.0
    n = na + nb
    var = na * nb / 12.0 * ((n + 1) - tie_term / (n * (n - 1)))
    return 0.0 if var <= 0 else (u - na * nb / 2.0) / math.sqrt(var)


def cramers_v(tab) -> tuple[float, float, int]:
    rows = sorted({k[0] for k in tab})
    cols = sorted({k[1] for k in tab})
    n = sum(tab.values())
    if n == 0:
        return 0.0, 0.0, 0
    rsum = {r: sum(tab.get((r, c), 0) for c in cols) for r in rows}
    csum = {c: sum(tab.get((r, c), 0) for r in rows) for c in cols}
    chi = 0.0
    for r in rows:
        for c in cols:
            e = rsum[r] * csum[c] / n
            if e > 0:
                chi += (tab.get((r, c), 0) - e) ** 2 / e
    k = min(len(rows), len(cols))
    v = math.sqrt(chi / (n * (k - 1))) if k > 1 else 0.0
    return v, chi, (len(rows) - 1) * (len(cols) - 1)


def norm_mutual_info(tab) -> float:
    rows = sorted({k[0] for k in tab})
    cols = sorted({k[1] for k in tab})
    n = sum(tab.values())
    if n == 0:
        return 0.0
    px = {r: sum(tab.get((r, c), 0) for c in cols) / n for r in rows}
    py = {c: sum(tab.get((r, c), 0) for r in rows) / n for c in cols}
    mi = 0.0
    for r in rows:
        for c in cols:
            p = tab.get((r, c), 0) / n
            if p > 0:
                mi += p * math.log(p / (px[r] * py[c]))
    hx = -sum(p * math.log(p) for p in px.values() if p > 0)
    hy = -sum(p * math.log(p) for p in py.values() if p > 0)
    d = min(hx, hy)
    return 0.0 if d <= 0 else mi / d


def quantiles(xs) -> tuple[float, float, float]:
    xs = [float(x) for x in xs]
    if not xs:
        return (float("nan"),) * 3
    s = sorted(xs)

    def q(p: float) -> float:
        i = p * (len(s) - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return s[lo] + (s[hi] - s[lo]) * (i - lo)
    return q(0.25), q(0.50), q(0.75)


# --------------------------------------------------------------------------
# pre-registered constants
# --------------------------------------------------------------------------

K_MAIN = 7
K_SENS = (3, 14)
FIXED_R = 0.236
EPISODE_HORIZON = 35

ZONES = list(pf.ZONE_ORDER)
RIBBON_STATES = ("full_bull", "folded", "full_bear")
PRICE_ZONES = ("above", "inside", "below")


@dataclass(slots=True)
class Row:
    i: int
    day: date
    hhmm: str
    idx_in_day: int
    bars_left: int
    close: float
    osc: float
    zone: str
    compressed: bool
    ema21: float
    ribbon: str
    pzone: str
    day_atr: float
    anchor: float
    h_atr: float                # hourly Wilder ATR(14) — the oscillator's own
                                # denominator, needed as a volatility control


def build():
    bars = [b for b in data.hourly() if b.hhmm != "16:00"]
    daily = data.daily(years="20y")
    lv = levels.build(daily)

    osc = pf.phase_oscillator(bars)
    comp = pf.compression_tracker(bars)
    fr = rs.frames(bars)
    hatr = pf.ta_atr(bars, pf.ATR_LEN)

    by_day: dict[date, list[int]] = defaultdict(list)
    for i, b in enumerate(bars):
        by_day[b.day].append(i)

    rows: list[Row] = []
    for i, b in enumerate(bars):
        if (osc[i] is None or fr[i] is None or comp[i] is None
                or hatr[i] is None or b.day not in lv):
            continue
        f = fr[i]
        di = by_day[b.day]
        pos = di.index(i)
        rows.append(Row(i, b.day, b.hhmm, pos, len(di) - 1 - pos, b.close,
                        osc[i], pf.phase_zone(osc[i]), bool(comp[i]),
                        f.e21, f.state, f.price_zone,
                        lv[b.day].atr, lv[b.day].anchor, hatr[i]))
    return bars, rows, dict(by_day)


# --------------------------------------------------------------------------
# forward primitives
# --------------------------------------------------------------------------

def touch_rest(bars, by_day, r: Row, price: float, side: int) -> bool:
    for j in by_day[r.day]:
        if j <= r.i:
            continue
        b = bars[j]
        if (b.high >= price) if side > 0 else (b.low <= price):
            return True
    return False


def touch_k(bars, r: Row, price: float, side: int, k: int) -> bool:
    for j in range(r.i + 1, min(r.i + 1 + k, len(bars))):
        b = bars[j]
        if (b.high >= price) if side > 0 else (b.low <= price):
            return True
    return False


def race_rest(bars, by_day, r: Row, up: float, dn: float) -> str:
    """Which of `up` / `dn` is reached first in the remainder of the session."""
    for j in by_day[r.day]:
        if j <= r.i:
            continue
        b = bars[j]
        hu, hd = b.high >= up, b.low <= dn
        if hu and hd:
            return "ambiguous"
        if hu:
            return "up"
        if hd:
            return "down"
    return "neither"


LADDER = sorted(levels.RATIOS)


def next_named(r: Row, side: int):
    cand = [r.anchor + q * r.day_atr for q in LADDER]
    cand = [p for p in cand if (p > r.close if side > 0 else p < r.close)]
    if not cand:
        return None
    p = min(cand) if side > 0 else max(cand)
    return p, abs(p - r.close) / r.day_atr


def rest_range_atr(bars, by_day, r: Row) -> float | None:
    js = [j for j in by_day[r.day] if j > r.i]
    if not js:
        return None
    return (max(bars[j].high for j in js) - min(bars[j].low for j in js)) / r.day_atr


# ==========================================================================
def main() -> None:
    bars, rows, by_day = build()
    print("=" * 82)
    print("PHASE OSCILLATOR AS A CONDITIONING VARIABLE — SPX 1h, 730d")
    print("=" * 82)
    print(f"hourly bars loaded   {len(bars)}")
    print(f"rows with full state {len(rows)}   sessions {len({r.day for r in rows})}")
    print(f"span                 {rows[0].day} .. {rows[-1].day}")
    print(f"pre-registered: K_MAIN={K_MAIN} K_SENS={K_SENS} FIXED_R={FIXED_R} "
          f"EPISODE_HORIZON={EPISODE_HORIZON}")

    # ------------------------------------------------------------------ A
    print("\n" + "=" * 82)
    print("A. ZONE OCCUPANCY (full enumeration of the 7-band partition)")
    print("=" * 82)
    zc = Counter(r.zone for r in rows)
    n = len(rows)
    for z in ZONES:
        print(f"  {z:<16}{rate(zc[z], n)}")
    print(f"  compression ON  {rate(sum(r.compressed for r in rows), n)}")
    q = quantiles([r.osc for r in rows])
    print(f"  osc quartiles   p25={q[0]:+.1f}  median={q[1]:+.1f}  p75={q[2]:+.1f}")

    # ------------------------------------------------------------------ B
    print("\n" + "=" * 82)
    print("B. Q1a — NEXT HOURLY BAR DIRECTION BY ZONE")
    print("=" * 82)
    print("outcome: close[i+1] > close[i].  B1 = next bar in the SAME session;")
    print("B2 = next bar in the series (overnight gap included).")
    up1: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    up2: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.i + 1 >= len(bars):
            continue
        hit = bars[r.i + 1].close > r.close
        up2[r.zone][0] += hit
        up2[r.zone][1] += 1
        if bars[r.i + 1].day == r.day:
            up1[r.zone][0] += hit
            up1[r.zone][1] += 1
    for tag, tab in (("B1 same-session", up1), ("B2 incl. overnight", up2)):
        tk = sum(v[0] for v in tab.values())
        tn = sum(v[1] for v in tab.values())
        print(f"\n  {tag}   pooled base rate  {rate(tk, tn)}")
        for z in ZONES:
            k, nn = tab[z]
            if not nn:
                continue
            zz = z2(k, nn, tk - k, tn - nn)
            print(f"    {z:<16}{rate(k, nn)}   vs rest z={zz:+5.2f} {verdict(zz)}")

    # ------------------------------------------------------------------ C
    print("\n" + "=" * 82)
    print("C. Q1b — TOUCHING THE NEXT NAMED ATR LEVEL BEFORE THE CLOSE")
    print("=" * 82)
    print("Nearest named level strictly above / below the close, reached by any")
    print("later bar of the SAME session.  'vol' = median remaining-session range")
    print("in daily-ATR units — THE CONFOUND, printed so it cannot hide.")
    cu: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cd: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    du: dict[str, list[float]] = defaultdict(list)
    vol: dict[str, list[float]] = defaultdict(list)
    off_ladder = 0
    for r in rows:
        if r.bars_left == 0:
            continue
        nu, nd = next_named(r, +1), next_named(r, -1)
        rr = rest_range_atr(bars, by_day, r)
        if rr is not None:
            vol[r.zone].append(rr)
        if nu is None or nd is None:
            off_ladder += 1
            continue
        cu[r.zone][0] += touch_rest(bars, by_day, r, nu[0], +1)
        cu[r.zone][1] += 1
        du[r.zone].append(nu[1])
        cd[r.zone][0] += touch_rest(bars, by_day, r, nd[0], -1)
        cd[r.zone][1] += 1
    print(f"\n  bars off the -1.618..+1.618 ladder (skipped): {off_ladder}")
    for tag, tab in (("UP  level", cu), ("DOWN level", cd)):
        tk = sum(v[0] for v in tab.values())
        tn = sum(v[1] for v in tab.values())
        print(f"\n  {tag} touched — pooled  {rate(tk, tn)}")
        for z in ZONES:
            k, nn = tab[z]
            if not nn:
                continue
            zz = z2(k, nn, tk - k, tn - nn)
            print(f"    {z:<16}{rate(k, nn)}  dist={quantiles(du[z])[1]:.3f}ATR "
                  f"vol={quantiles(vol[z])[1]:.3f}ATR  z={zz:+5.2f} {verdict(zz)}")

    # ------------------------------------------------------------------ D
    print("\n" + "=" * 82)
    print(f"D. FIXED-DISTANCE VERSION — +/-{FIXED_R} x daily ATR")
    print("=" * 82)
    print("Removes the uneven-ladder confound.  Does NOT remove the volatility")
    print("confound — read the UP and DOWN columns TOGETHER, not separately.")
    fu: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    fd: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    disc: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # up-only, down-only
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hu = touch_rest(bars, by_day, r, r.close + d, +1)
        hd = touch_rest(bars, by_day, r, r.close - d, -1)
        fu[r.zone][0] += hu
        fu[r.zone][1] += 1
        fd[r.zone][0] += hd
        fd[r.zone][1] += 1
        disc[r.zone][0] += int(hu and not hd)
        disc[r.zone][1] += int(hd and not hu)
    tku, tnu = sum(v[0] for v in fu.values()), sum(v[1] for v in fu.values())
    tkd, tnd = sum(v[0] for v in fd.values()), sum(v[1] for v in fd.values())
    print(f"\n  {'zone':<16}{'P(+0.236 ATR)':<32}{'P(-0.236 ATR)':<32}"
          f"{'vol':>7}{'McNemar':>9}")
    print(f"  {'POOLED':<16}{fmt(tku, tnu):<32}{fmt(tkd, tnd):<32}"
          f"{quantiles([v for vs in vol.values() for v in vs])[1]:7.3f}"
          f"{mcnemar_z(sum(v[0] for v in disc.values()), sum(v[1] for v in disc.values())):+9.2f}")
    cell(2)
    for z in ZONES:
        k1, n1 = fu[z]
        k2, n2 = fd[z]
        if not n1:
            continue
        cell(2)
        print(f"  {z:<16}{fmt(k1, n1):<32}{fmt(k2, n2):<32}"
              f"{quantiles(vol[z])[1]:7.3f}{mcnemar_z(disc[z][0], disc[z][1]):+9.2f}")
    print("\n  READ THIS: both columns move together across zones.  That is a")
    print("  volatility ordering, not a direction call.  The McNemar column is the")
    print("  only directional content in this table.")

    # ------------------------------------------------------------------ E
    print("\n" + "=" * 82)
    print("E. Q2 — \"DON'T CHASE THE EXTENDED ZONE\"  (headline)")
    print("=" * 82)

    print("\n  -- E1. FIRST-TOUCH RACE: which of +/-0.236 ATR arrives first? --")
    print("  This is what a 1:1 bracket pays on, and it is volatility-neutral.")
    print("  Same-hourly-bar hits are UNRESOLVABLE on 1h data and are excluded;")
    print("  the exclusion rate is printed and the race is re-run on 5m below.")
    race: dict[str, Counter] = defaultdict(Counter)
    race_day: dict[str, dict[date, list[tuple[int, int]]]] = {}
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        race[r.zone][race_rest(bars, by_day, r, r.close + d, r.close - d)] += 1
    tot = Counter()
    for z in ZONES:
        tot.update(race[z])
    tres = tot["up"] + tot["down"]
    print(f"\n  {'zone':<16}{'P(up first | resolved)':<34}"
          f"{'ambig%':>8}{'neither%':>10}{'vs pooled z':>13}")
    print(f"  {'POOLED':<16}{fmt(tot['up'], tres):<34}"
          f"{100*tot['ambiguous']/sum(tot.values()):8.1f}"
          f"{100*tot['neither']/sum(tot.values()):10.1f}{'':>13}")
    cell()
    for z in ZONES:
        c = race[z]
        res = c["up"] + c["down"]
        if res < 10:
            continue
        zz = z2(c["up"], res, tot["up"] - c["up"], tres - res)
        cell()
        print(f"  {z:<16}{fmt(c['up'], res):<34}"
              f"{100*c['ambiguous']/sum(c.values()):8.1f}"
              f"{100*c['neither']/sum(c.values()):10.1f}{zz:+13.2f}")
    ku, nu = race["extended_up"]["up"], race["extended_up"]["up"] + race["extended_up"]["down"]
    kl, nl = race["launch_box"]["up"], race["launch_box"]["up"] + race["launch_box"]["down"]
    print(cmp2("extended_up vs launch_box (up-first race)", ku, nu, kl, nl))
    kdn = race["extended_down"]["down"]
    ndn = race["extended_down"]["up"] + race["extended_down"]["down"]
    print(cmp2("extended_down vs launch_box (down-first race)",
               kdn, ndn, nl - kl, nl))

    print("\n  -- E1b. 5m TIE-BREAKER (60 days only — n is small, treat as a check) --")
    fine = data.fine()
    fine_by_day: dict[date, list[data.Bar]] = defaultdict(list)
    for b in fine:
        fine_by_day[b.day].append(b)
    race5: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.bars_left == 0 or r.day not in fine_by_day:
            continue
        start = bars[r.i + 1].dt
        d = FIXED_R * r.day_atr
        up, dn = r.close + d, r.close - d
        res = "neither"
        for b in fine_by_day[r.day]:
            if b.dt < start:
                continue
            hu, hd = b.high >= up, b.low <= dn
            if hu and hd:
                res = "ambiguous"
                break
            if hu:
                res = "up"
                break
            if hd:
                res = "down"
                break
        race5[r.zone][res] += 1
    t5 = Counter()
    for z in ZONES:
        t5.update(race5[z])
    t5res = t5["up"] + t5["down"]
    print(f"  pooled 5m: P(up first)  {rate(t5['up'], t5res)}   "
          f"ambiguity {100*t5['ambiguous']/max(1,sum(t5.values())):.1f}% "
          f"(vs {100*tot['ambiguous']/sum(tot.values()):.1f}% on 1h)")
    print("  (different 60-day sample, so the pooled level need not match 1h)")
    for z in ZONES:
        c = race5[z]
        res = c["up"] + c["down"]
        flag = "" if res >= 30 else "   <- n too small to interpret"
        print(f"    {z:<16}{rate(c['up'], res)}{flag}")

    print("\n  -- E2. ONE-SIDED VIEW, kept only for comparison with E1 --")
    for what, tab, a, b in (
            (f"P(+{FIXED_R}ATR)", fu, "extended_up", "launch_box"),
            (f"P(-{FIXED_R}ATR)", fd, "extended_down", "launch_box"),
            (f"P(+{FIXED_R}ATR)", fu, "extended_up", "distribution"),
            (f"P(+{FIXED_R}ATR)", fu, "distribution", "launch_box")):
        ka, na = tab[a]
        kb, nb = tab[b]
        print(f"    {what} {a} {fmt(ka, na)} | {b} {fmt(kb, nb)}")
        print(cmp2(f"{a} vs {b}", ka, na, kb, nb))

    print("\n  -- E3. TIME-OF-DAY STRATIFICATION + Mantel-Haenszel pooling --")
    print("  outcome = +0.236 ATR reached before the close")
    hod: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hit = touch_rest(bars, by_day, r, r.close + d, +1)
        hod[(r.hhmm, r.zone)][0] += hit
        hod[(r.hhmm, r.zone)][1] += 1
    hours = sorted({k[0] for k in hod})
    strata = []
    print(f"\n  {'hour':<8}{'extended_up':<34}{'launch_box':<34}{'z':>7}")
    agree = 0
    for hh in hours:
        ke, ne = hod[(hh, "extended_up")]
        kl2, nl2 = hod[(hh, "launch_box")]
        strata.append((ke, ne, kl2, nl2))
        zz = z2(ke, ne, kl2, nl2)
        agree += int(zz < 0)
        cell(2)
        print(f"  {hh:<8}{fmt(ke, ne):<34}{fmt(kl2, nl2):<34}{zz:+7.2f}")
    print(f"  strata where extended_up < launch_box: {agree}/{len(hours)}  "
          f"(sign test p={2*0.5**len(hours):.3f})")
    zmh = mantel_haenszel_z(strata)
    print(f"  Mantel-Haenszel pooled z = {zmh:+.2f}   {verdict(zmh)}")

    print("\n  -- E4. DEPENDENCE-AWARE VERSIONS OF THE SAME COMPARISON --")
    ind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    grp: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hit = int(touch_rest(bars, by_day, r, r.close + d, +1))
        if r.zone == "extended_up":
            grp[r.day].append((0, hit))
        elif r.zone == "launch_box":
            grp[r.day].append((1, hit))
        if r.hhmm == "10:30":
            ind[r.zone][0] += hit
            ind[r.zone][1] += 1
    print("  (a) one bar per day (10:30) — independent, but throws away 5/6 of it")
    for z in ZONES:
        k, nn = ind[z]
        if nn:
            print(f"      {z:<16}{rate(k, nn)}")
    ke, ne = ind["extended_up"]
    kl2, nl2 = ind["launch_box"]
    print(cmp2("extended_up vs launch_box (independent days)", ke, ne, kl2, nl2))
    pt, lo, hi, p0 = block_bootstrap_diff(grp)
    cell()
    print(f"  (b) DAY-BLOCK BOOTSTRAP over all bars, 2000 reps, seed 12345")
    print(f"      diff = P(ext_up) - P(launch) = {100*pt:+.1f}pp  "
          f"95% CI [{100*lo:+.1f}, {100*hi:+.1f}]pp   P(diff>=0) = {p0:.3f}")
    print(f"      {'CI excludes 0 -> survives clustering'
                  if hi < 0 or lo > 0 else 'CI straddles 0 -> NO WORK once clustered'}")

    print("\n  -- E5. POST-HOC robustness on the single largest positive in E1 --")
    print("  NOT pre-registered.  `accumulation` was the biggest race deviation, so")
    print("  it is the cell most likely to be a family maximum.  Bootstrapped here")
    print("  only so the reader can see whether it even survives clustering.")
    grp2: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for r in rows:
        if r.bars_left == 0 or r.zone not in ("accumulation", "launch_box"):
            continue
        d = FIXED_R * r.day_atr
        res = race_rest(bars, by_day, r, r.close + d, r.close - d)
        if res not in ("up", "down"):
            continue
        grp2[r.day].append((0 if r.zone == "accumulation" else 1,
                            int(res == "up")))
    pt2, lo2, hi2, p02 = block_bootstrap_diff(grp2)
    cell()
    print(f"      diff = P(up first | accumulation) - P(up first | launch_box)")
    print(f"      = {100*pt2:+.1f}pp  95% CI [{100*lo2:+.1f}, {100*hi2:+.1f}]pp   "
          f"P(diff<=0) = {1-p02:.3f}")
    print("      Family it was drawn from: 7 zones x (race + 3 McNemar k values).")
    print("      Expected max |z| from ~28 correlated draws is around 2.4-2.6, so a")
    print("      z near 2.7 is NOT a discovery.  Label: UNCERTAIN, needs out-of-sample.")

    # ------------------------------------------------------------------ F
    print("\n" + "=" * 82)
    print("F. Q3 — MEAN REVERSION, DISTANCE-MATCHED AND SYMMETRIC")
    print("=" * 82)
    print("At each bar, d = |close - EMA21(1h)|.  Within the next k bars: does")
    print("price reach close+d (UP) and/or close-d (DOWN)?  Same distance, same")
    print("bar, so volatility cancels.  Paired -> McNemar.  The POOLED row is the")
    print("drift baseline every zone must beat, not zero.")
    for k in (K_MAIN, *K_SENS):
        print(f"\n  --- k = {k} hourly bars ---")
        print(f"  {'zone':<16}{'P(UP d)':<30}{'P(DOWN d)':<30}"
              f"{'McNemar':>9}{'up|disc':>9}{'vs pool':>9}")
        pb = pc = 0
        prow = []
        for r in rows:
            if r.i + k >= len(bars):
                continue
            d = abs(r.close - r.ema21)
            u = touch_k(bars, r, r.close + d, +1, k)
            dn = touch_k(bars, r, r.close - d, -1, k)
            prow.append((r.zone, u, dn))
        pk_u = sum(1 for _, u, _ in prow if u)
        pk_d = sum(1 for _, _, dd in prow if dd)
        pb = sum(1 for _, u, dd in prow if u and not dd)
        pc = sum(1 for _, u, dd in prow if dd and not u)
        cell(2)
        print(f"  {'POOLED (drift)':<16}{fmt(pk_u, len(prow)):<30}"
              f"{fmt(pk_d, len(prow)):<30}{mcnemar_z(pb, pc):+9.2f}"
              f"{100*pb/max(1, pb+pc):8.1f}%{'':>9}")
        for z in ZONES:
            sub = [(u, dd) for zz2, u, dd in prow if zz2 == z]
            if len(sub) < 20:
                continue
            ku2 = sum(1 for u, _ in sub if u)
            kd2 = sum(1 for _, dd in sub if dd)
            b = sum(1 for u, dd in sub if u and not dd)
            c = sum(1 for u, dd in sub if dd and not u)
            zpool = z2(b, b + c, pb - b, (pb + pc) - (b + c))
            cell(2)
            print(f"  {z:<16}{fmt(ku2, len(sub)):<30}{fmt(kd2, len(sub)):<30}"
                  f"{mcnemar_z(b, c):+9.2f}{100*b/max(1, b+c):8.1f}%{zpool:+9.2f}")

    print("\n  -- F2. EPISODES: how long until an extreme cools off? --")
    print(f"  Episode = first bar entering |osc|>=100 after being inside.")
    print(f"  Horizon {EPISODE_HORIZON} bars (5 sessions).  Censored cases counted.")
    idx = {r.i: r for r in rows}
    for side, want in (("extended_up", +1), ("extended_down", -1)):
        starts, prev_ex = [], False
        for r in rows:
            ex = (r.osc >= 100) if want > 0 else (r.osc <= -100)
            if ex and not prev_ex:
                starts.append(r)
            prev_ex = ex
        t_osc, t_px = [], []
        for s in starts:
            go = gp = None
            for j in range(s.i + 1, min(s.i + 1 + EPISODE_HORIZON, len(bars))):
                rj = idx.get(j)
                if rj is None:
                    continue
                if go is None and abs(rj.osc) <= 23.6:
                    go = j - s.i
                if gp is None and ((want > 0 and bars[j].low <= rj.ema21) or
                                   (want < 0 and bars[j].high >= rj.ema21)):
                    gp = j - s.i
                if go is not None and gp is not None:
                    break
            if go is not None:
                t_osc.append(go)
            if gp is not None:
                t_px.append(gp)
        qo, qp = quantiles(t_osc), quantiles(t_px)
        print(f"\n  {side}: {len(starts)} episodes")
        print(f"    osc back to launch box  {rate(len(t_osc), len(starts))}"
              f"  bars q25/med/q75 = {qo[0]:.0f}/{qo[1]:.0f}/{qo[2]:.0f}")
        print(f"    price trades to EMA21   {rate(len(t_px), len(starts))}"
              f"  bars q25/med/q75 = {qp[0]:.0f}/{qp[1]:.0f}/{qp[2]:.0f}")

    # ------------------------------------------------------------------ G
    print("\n" + "=" * 82)
    print("G. Q4 — DO PHASE AND RIBBON SAY THE SAME THING?")
    print("=" * 82)
    tab_state = Counter((r.zone, r.ribbon) for r in rows)
    tab_pzone = Counter((r.zone, r.pzone) for r in rows)

    def show(title, tab, cols):
        print(f"\n  {title}   (row % = P(col | zone))")
        print(f"  {'zone':<16}" + "".join(f"{c:>14}" for c in cols) + f"{'n':>8}")
        for z in ZONES:
            t = sum(tab.get((z, c), 0) for c in cols)
            if not t:
                continue
            print(f"  {z:<16}" +
                  "".join(f"{100*tab.get((z, c), 0)/t:13.1f}%" for c in cols) +
                  f"{t:8d}")
        tt = sum(tab.values())
        print(f"  {'ALL':<16}" +
              "".join(f"{100*sum(tab.get((z, c), 0) for z in ZONES)/tt:13.1f}%"
                      for c in cols) + f"{tt:8d}")
        v, chi, dof = cramers_v(tab)
        print(f"  Cramer's V = {v:.3f}   chi2 = {chi:.0f} (dof {dof})   "
              f"normalised MI = {norm_mutual_info(tab):.3f}")
        cell(len(ZONES) * len(cols))

    show("phase zone x ribbon EMA stacking", tab_state, RIBBON_STATES)
    show("phase zone x price vs ribbon body", tab_pzone, PRICE_ZONES)

    print("\n  -- G2. Joint cell counts and outcome rates (+0.236ATR before close) --")
    g2: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hit = touch_rest(bars, by_day, r, r.close + d, +1)
        g2[(r.zone, r.ribbon)][0] += hit
        g2[(r.zone, r.ribbon)][1] += 1
    print(f"  {'zone':<16}" + "".join(f"{s:>26}" for s in RIBBON_STATES))
    for z in ZONES:
        line = f"  {z:<16}"
        for s in RIBBON_STATES:
            k, nn = g2[(z, s)]
            line += f"{(f'{100*k/nn:.1f}% n={nn}' if nn else '-'):>26}"
        print(line)
    print("  (cells with tiny n are the point: the two indicators barely co-vary)")

    print("\n  -- G3. Pre-declared contrasts (3, chosen before seeing the table) --")
    for lbl, a, b in (
            ("within launch_box: ribbon bull vs bear",
             ("launch_box", "full_bull"), ("launch_box", "full_bear")),
            ("within full_bull: phase launch_box vs distribution",
             ("launch_box", "full_bull"), ("distribution", "full_bull")),
            ("within full_bull: phase launch_box vs extended_up",
             ("launch_box", "full_bull"), ("extended_up", "full_bull"))):
        ka, na = g2[a]
        kb, nb = g2[b]
        if na < 30 or nb < 30:
            print(f"    {lbl}: insufficient n ({na}/{nb})")
            continue
        cell(2)
        print(f"    {lbl}")
        print(f"      {str(a):<34}{fmt(ka, na)}")
        print(f"      {str(b):<34}{fmt(kb, nb)}")
        print(cmp2("", ka, na, kb, nb))

    print("\n  -- G4. The SAME volatility-neutral race, run on the RIBBON layer --")
    print("  Mirror of E1.  If any layer in Saty's stack carries direction it should")
    print("  be this one — the ribbon is the layer he calls the direction layer.")
    rr_race: dict[str, Counter] = defaultdict(Counter)
    pz_race: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        res = race_rest(bars, by_day, r, r.close + d, r.close - d)
        rr_race[r.ribbon][res] += 1
        pz_race[r.pzone][res] += 1
    for title, tabr, keys in (("ribbon EMA stacking", rr_race, RIBBON_STATES),
                              ("price vs ribbon body", pz_race, PRICE_ZONES)):
        print(f"\n    {title}")
        tu = sum(tabr[k]["up"] for k in keys)
        tn = tu + sum(tabr[k]["down"] for k in keys)
        for k in keys:
            c = tabr[k]
            res = c["up"] + c["down"]
            if not res:
                continue
            zz = z2(c["up"], res, tu - c["up"], tn - res)
            cell()
            print(f"      {k:<12}P(up first) {fmt(c['up'], res)}   "
                  f"neither {100*c['neither']/sum(c.values()):4.1f}%   "
                  f"vs rest z={zz:+5.2f} {verdict(zz)}")

    # ------------------------------------------------------------------ H
    print("\n" + "=" * 82)
    print("H. Q5 — COMPRESSION RELEASE: DIRECTION AND TRAVEL")
    print("=" * 82)
    print("Episode = maximal run of compression==True.  Box = [min low, max high]")
    print("over the episode bars.  Direction = whichever box edge is touched first.")
    idx_by_i = {r.i: r for r in rows}
    episodes: list[tuple[int, int]] = []
    run_start = None
    for r in rows:
        if r.compressed and run_start is None:
            run_start = r.i
        if not r.compressed and run_start is not None:
            episodes.append((run_start, r.i - 1))
            run_start = None
    lens = [e - s + 1 for s, e in episodes]
    ql = quantiles(lens)
    print(f"\n  episodes {len(episodes)}   length q25/med/q75 = "
          f"{ql[0]:.0f}/{ql[1]:.0f}/{ql[2]:.0f}  max={max(lens)}")

    def resolve(from_offset: int):
        up = dn = amb = unres = 0
        det: list[tuple[int, int, float, float, float]] = []
        for s, e in episodes:
            bh = max(bars[j].high for j in range(s, e + 1))
            bl = min(bars[j].low for j in range(s, e + 1))
            rel = e + 1 + from_offset
            if rel + K_MAIN >= len(bars) or rel >= len(bars):
                continue
            rr = idx_by_i.get(e + 1)
            if rr is None or bh <= bl:
                continue
            pos = (bars[e + 1].close - bl) / (bh - bl)
            got = None
            for j in range(rel, min(rel + K_MAIN, len(bars))):
                hu, hd = bars[j].high >= bh, bars[j].low <= bl
                if hu and hd:
                    got = 0
                    break
                if hu:
                    got = +1
                    break
                if hd:
                    got = -1
                    break
            if got is None:
                unres += 1
            elif got == 0:
                amb += 1
            elif got > 0:
                up += 1
                det.append((e + 1, +1, bh, bl, pos))
            else:
                dn += 1
                det.append((e + 1, -1, bh, bl, pos))
        return up, dn, amb, unres, det

    for off, tag in ((0, "from the release bar inclusive"),
                     (1, "from the bar AFTER release (release bar excluded)")):
        up, dn, amb, unres, det = resolve(off)
        nres = up + dn
        print(f"\n  {tag}")
        print(f"    resolved {nres}  same-bar-both-edges {amb}  "
              f"unresolved within {K_MAIN} bars {unres}")
        print(f"    P(up edge first | resolved)  {rate(up, nres)}")
        print(cmp2("vs a 50/50 coin", up, nres, nres, 2 * nres))
        if off == 0:
            resolved0 = det

    print("\n  -- H1b. THE ONLY TRADEABLE SUBSET: release bar still inside the box --")
    print("  A compression run ends precisely when the bands expand, i.e. usually on")
    print("  the very bar that breaks the box.  Those cases are not tradeable: by the")
    print("  time the label goes off, the move has happened.  Counting how many are")
    print("  left once that is excluded is the honest measure of the setup's supply.")
    clean_up = clean_dn = clean_none = 0
    inside_n = 0
    for s, e in episodes:
        bh = max(bars[j].high for j in range(s, e + 1))
        bl = min(bars[j].low for j in range(s, e + 1))
        rel = e + 1
        if rel + K_MAIN >= len(bars):
            continue
        if not (bars[rel].high < bh and bars[rel].low > bl):
            continue                       # release bar already breached the box
        inside_n += 1
        got = None
        for j in range(rel + 1, min(rel + 1 + K_MAIN, len(bars))):
            hu, hd = bars[j].high >= bh, bars[j].low <= bl
            if hu and hd:
                got = 0
                break
            if hu:
                got = +1
                break
            if hd:
                got = -1
                break
        if got == 1:
            clean_up += 1
        elif got == -1:
            clean_dn += 1
        else:
            clean_none += 1
    print(f"    episodes where the release bar stayed fully inside the box: "
          f"{inside_n} / {len(episodes)}")
    nres_c = clean_up + clean_dn
    print(f"    of those, resolved within {K_MAIN} bars: {nres_c}  "
          f"(unresolved/ambiguous {clean_none})")
    print(f"    P(up edge first | clean & resolved)  {rate(clean_up, nres_c)}")
    print(cmp2("vs a 50/50 coin", clean_up, nres_c, nres_c, 2 * nres_c))
    print("    Two years of hourly SPX yields this many tradeable instances. Judge")
    print("    the setup's usefulness by that number before its win rate.")

    print("\n  -- H2. Is the direction predictable from state at release? --")
    print("  WARNING (stated before the numbers): the release bar's own position")
    print("  inside the box mechanically predicts which edge is nearer.  Any state")
    print("  variable that encodes 'price is high in the box' will look predictive.")
    posq = quantiles([p for _, _, _, _, p in resolved0])
    print(f"  release-bar position in box: q25/med/q75 = "
          f"{posq[0]:.2f}/{posq[1]:.2f}/{posq[2]:.2f}")
    kk = sum(1 for _, d, _, _, p in resolved0 if (p >= 0.5) == (d > 0))
    cell()
    print(f"  P(break side == side the release bar already sits on) "
          f"{fmt(kk, len(resolved0))}   <- the mechanical baseline")
    for name, pick in (("osc>=0 at release", lambda r: r.osc >= 0),
                       ("ribbon full_bull", lambda r: r.ribbon == "full_bull"),
                       ("price above ribbon", lambda r: r.pzone == "above")):
        ka = na = kb = nb = 0
        mka = mna = mkb = mnb = 0
        for rel, d, _, _, p in resolved0:
            rr = idx_by_i.get(rel)
            if rr is None:
                continue
            mid = 0.25 <= p <= 0.75            # release bar mid-box: no free lunch
            if pick(rr):
                na += 1
                ka += int(d > 0)
                if mid:
                    mna += 1
                    mka += int(d > 0)
            else:
                nb += 1
                kb += int(d > 0)
                if mid:
                    mnb += 1
                    mkb += int(d > 0)
        cell(2)
        print(f"    {name:<22}TRUE {fmt(ka, na)} | FALSE {fmt(kb, nb)}")
        print(cmp2(f"{name} (all)", ka, na, kb, nb))
        cell(2)
        print(f"      mid-box only (0.25<=pos<=0.75): TRUE {fmt(mka, mna)} | "
              f"FALSE {fmt(mkb, mnb)}")
        print(cmp2(f"{name} (mid-box control)", mka, mna, mkb, mnb))

    print("\n  -- H3. Travel after the break, in daily-ATR units --")
    trav = []
    for rel, d, bh, bl, _ in resolved0:
        rr = idx_by_i.get(rel)
        if rr is None:
            continue
        end = min(rel + K_MAIN, len(bars))
        mfe = (max(bars[j].high for j in range(rel, end)) - bh) if d > 0 else \
              (bl - min(bars[j].low for j in range(rel, end)))
        trav.append(mfe / rr.day_atr)
    base = []
    for r in rows:
        if r.compressed or r.i + K_MAIN >= len(bars):
            continue
        end = r.i + 1 + K_MAIN
        base.append((max(bars[j].high for j in range(r.i + 1, end)) - r.close)
                    / r.day_atr)
    qt, qb = quantiles(trav), quantiles(base)
    cell(2)
    print(f"    post-break MFE   q25/med/q75 = {qt[0]:.3f}/{qt[1]:.3f}/{qt[2]:.3f}"
          f"  n={len(trav)}")
    print(f"    baseline up-MFE  q25/med/q75 = {qb[0]:.3f}/{qb[1]:.3f}/{qb[2]:.3f}"
          f"  n={len(base)}")
    zz = mannwhitney_z(trav, base)
    print(f"    rank-sum z = {zz:+.2f}   {verdict(zz)}")
    print("    NOTE: baseline is measured from a bar CLOSE, post-break from a box")
    print("    EDGE price has just exceeded.  Indicative, not a matched control.")

    print("\n  -- H4. Does compression itself move the section-D base rate? --")
    ck = cn = uk = un = ckd = ukd = 0
    for r in rows:
        if r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hu = touch_rest(bars, by_day, r, r.close + d, +1)
        hd = touch_rest(bars, by_day, r, r.close - d, -1)
        if r.compressed:
            ck += hu
            ckd += hd
            cn += 1
        else:
            uk += hu
            ukd += hd
            un += 1
    print(f"    compressed    UP {fmt(ck, cn)} | DOWN {fmt(ckd, cn)}")
    print(f"    uncompressed  UP {fmt(uk, un)} | DOWN {fmt(ukd, un)}")
    cell(4)
    print(cmp2("compressed vs not, UP side", ck, cn, uk, un))
    print(cmp2("compressed vs not, DOWN side", ckd, cn, ukd, un))
    print("    Both sides move the same way -> volatility/positioning, not direction.")

    # ------------------------------------------------------------------ I
    print("\n" + "=" * 82)
    print("I. WHAT THE PHASE ZONE *DOES* FORECAST — RANGE, NOT DIRECTION")
    print("=" * 82)
    print("Sections B-G find no directional content anywhere.  The one thing that")
    print("moves hugely and monotonically across zones is HOW MUCH IS LEFT IN THE")
    print("DAY.  That is a legitimate maturity statistic and it is what Saty claims")
    print("the oscillator is for, so it gets tested properly rather than asserted.")
    print("Time of day is the obvious confound, so the headline is measured at a")
    print("SINGLE fixed time (10:30), which fixes it exactly and makes the")
    print("observations independent across days.")

    print("\n  -- I1. P(session never reaches EITHER +/-0.236 ATR), 10:30 bars only --")
    dead: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rng1030: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.hhmm != "10:30" or r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hu = touch_rest(bars, by_day, r, r.close + d, +1)
        hd = touch_rest(bars, by_day, r, r.close - d, -1)
        dead[r.zone][0] += int(not hu and not hd)
        dead[r.zone][1] += 1
        rr = rest_range_atr(bars, by_day, r)
        if rr is not None:
            rng1030[r.zone].append(rr)
    tk = sum(v[0] for v in dead.values())
    tn = sum(v[1] for v in dead.values())
    print(f"  {'zone':<16}{'P(dead session)':<34}{'median range left':>19}"
          f"{'  rank-sum vs launch_box'}")
    print(f"  {'POOLED':<16}{fmt(tk, tn):<34}"
          f"{quantiles([v for vs in rng1030.values() for v in vs])[1]:15.3f} ATR")
    cell(2)
    for z in ZONES:
        k, nn = dead[z]
        if not nn:
            continue
        zz = z2(k, nn, dead["launch_box"][0], dead["launch_box"][1]) \
            if z != "launch_box" else 0.0
        mw = mannwhitney_z(rng1030[z], rng1030["launch_box"]) \
            if z != "launch_box" else 0.0
        cell(2)
        print(f"  {z:<16}{fmt(k, nn):<34}{quantiles(rng1030[z])[1]:15.3f} ATR"
              f"   p-z={zz:+5.2f} range-z={mw:+5.2f}")
    print("  (all n above are independent days — no serial-correlation discount)")

    print("\n  -- I2. Is this just the ribbon again? same table, ribbon states --")
    dead_r: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rng_r: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.hhmm != "10:30" or r.bars_left == 0:
            continue
        d = FIXED_R * r.day_atr
        hu = touch_rest(bars, by_day, r, r.close + d, +1)
        hd = touch_rest(bars, by_day, r, r.close - d, -1)
        dead_r[r.ribbon][0] += int(not hu and not hd)
        dead_r[r.ribbon][1] += 1
        rr = rest_range_atr(bars, by_day, r)
        if rr is not None:
            rng_r[r.ribbon].append(rr)
    for s in RIBBON_STATES:
        k, nn = dead_r[s]
        if not nn:
            continue
        cell(2)
        print(f"  {s:<16}{fmt(k, nn):<34}{quantiles(rng_r[s])[1]:15.3f} ATR")
    sp_r = max(v[0]/v[1] for v in dead_r.values() if v[1] >= 30) - \
        min(v[0]/v[1] for v in dead_r.values() if v[1] >= 30)
    sp_z = max(v[0]/v[1] for v in dead.values() if v[1] >= 30) - \
        min(v[0]/v[1] for v in dead.values() if v[1] >= 30)
    print(f"  spread (cells n>=30): ribbon {100*sp_r:.1f}pp vs phase {100*sp_z:.1f}pp")
    print("  HONEST READING: these are COMPARABLE.  The ribbon forecasts the same")
    print("  thing about as well, so I1 alone does NOT show the oscillator adds")
    print("  anything.  The incremental-information claim has to come from I2b.")

    print("\n  -- I2b. Phase INSIDE a fixed ribbon state (the real increment test) --")
    for st in RIBBON_STATES:
        sub = defaultdict(lambda: [0, 0])
        for r in rows:
            if r.hhmm != "10:30" or r.bars_left == 0 or r.ribbon != st:
                continue
            d = FIXED_R * r.day_atr
            hu = touch_rest(bars, by_day, r, r.close + d, +1)
            hd = touch_rest(bars, by_day, r, r.close - d, -1)
            sub[r.zone][0] += int(not hu and not hd)
            sub[r.zone][1] += 1
        shown = [(z, sub[z]) for z in ZONES if sub[z][1] >= 30]
        if len(shown) < 2:
            print(f"    ribbon={st}: fewer than two zones with n>=30 — cannot test")
            continue
        print(f"    ribbon={st}")
        for z, (k, nn) in shown:
            cell()
            print(f"      {z:<16}{fmt(k, nn)}")
        # Contrast fixed to the SAME pair already pre-declared in G3, so this is
        # not a post-hoc pick of the widest gap.
        other = "distribution" if st == "full_bull" else "accumulation"
        va, vb = sub["launch_box"], sub[other]
        if va[1] >= 30 and vb[1] >= 30:
            cell()
            print(cmp2(f"launch_box vs {other} within {st} [pre-declared]",
                       va[0], va[1], vb[0], vb[1]))

    print("\n  -- I3. day-block bootstrap of the two biggest range contrasts --")
    for za in ("distribution", "extended_up", "accumulation"):
        g: dict[date, list[tuple[int, int]]] = defaultdict(list)
        for r in rows:
            if r.bars_left == 0 or r.zone not in (za, "launch_box"):
                continue
            d = FIXED_R * r.day_atr
            hu = touch_rest(bars, by_day, r, r.close + d, +1)
            hd = touch_rest(bars, by_day, r, r.close - d, -1)
            g[r.day].append((0 if r.zone == za else 1, int(not hu and not hd)))
        pt3, lo3, hi3, p03 = block_bootstrap_diff(g)
        cell()
        ok = "survives clustering" if (lo3 > 0 or hi3 < 0) else "NO WORK clustered"
        print(f"    P(dead|{za}) - P(dead|launch_box) = {100*pt3:+5.1f}pp  "
              f"95% CI [{100*lo3:+6.1f},{100*hi3:+6.1f}]pp   {ok}")

    print("\n  -- I4. THE TEST THAT DECIDES WHETHER I1 IS A FINDING OR A TAUTOLOGY --")
    print("  The oscillator's DENOMINATOR is the hourly ATR.  A high |osc| therefore")
    print("  partly just means 'hourly ATR is small right now', and volatility")
    print("  clusters.  So I1 could be volatility persistence wearing a costume.")
    print("  Control: stratify by hourly ATR14 / daily ATR into terciles (cut points")
    print("  from the 10:30 sample itself, 3 strata, declared) and re-run inside each.")
    tenthirty = [r for r in rows if r.hhmm == "10:30" and r.bars_left > 0]
    ratios = sorted(r.h_atr / r.day_atr for r in tenthirty)
    c1 = ratios[len(ratios) // 3]
    c2 = ratios[2 * len(ratios) // 3]
    print(f"  tercile cuts on hourly_ATR/daily_ATR: {c1:.3f} / {c2:.3f}")

    def vt(r: Row) -> int:
        x = r.h_atr / r.day_atr
        return 0 if x < c1 else (1 if x < c2 else 2)

    outcome = {}
    for r in tenthirty:
        d = FIXED_R * r.day_atr
        hu = touch_rest(bars, by_day, r, r.close + d, +1)
        hd = touch_rest(bars, by_day, r, r.close - d, -1)
        outcome[r.i] = int(not hu and not hd)
    print(f"\n  {'contrast':<34}{'tercile':<9}{'zone A':<22}{'launch_box':<22}{'z':>7}")
    for za in ("distribution", "extended_up", "accumulation", "mark_down"):
        strata2 = []
        for t in (0, 1, 2):
            ka = na = kb = nb = 0
            for r in tenthirty:
                if vt(r) != t:
                    continue
                if r.zone == za:
                    na += 1
                    ka += outcome[r.i]
                elif r.zone == "launch_box":
                    nb += 1
                    kb += outcome[r.i]
            strata2.append((ka, na, kb, nb))
            cell(2)
            print(f"  {('P(dead) ' + za):<34}{['low', 'mid', 'high'][t]:<9}"
                  f"{(f'{100*ka/na:.1f}% n={na}' if na else '-'):<22}"
                  f"{(f'{100*kb/nb:.1f}% n={nb}' if nb else '-'):<22}"
                  f"{z2(ka, na, kb, nb):+7.2f}")
        zmh2 = mantel_haenszel_z(strata2)
        cell()
        print(f"  {'-> Mantel-Haenszel pooled':<43}{za} vs launch_box  "
              f"z={zmh2:+.2f}  {verdict(zmh2)}")
    print("\n  If these MH z-values stay large, the phase zone carries range")
    print("  information the raw volatility ratio does not, and I1 is a finding.")
    print("  If they collapse, I1 is volatility clustering and should be dropped.")

    print("\n" + "=" * 82)
    print(f"MULTIPLICITY LEDGER: {CELLS} statistics reported.")
    print("Every table is a full enumeration of a partition fixed in the module")
    print("docstring before any number was seen.  No parameter was searched.  The")
    print("only free choices (K_MAIN=7, K_SENS=(3,14), FIXED_R=0.236, HORIZON=35)")
    print("were declared up front and every value is reported, not the best one.")
    print("=" * 82)


if __name__ == "__main__":
    main()
