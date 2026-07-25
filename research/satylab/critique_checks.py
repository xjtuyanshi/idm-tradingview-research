#!/usr/bin/env python3
"""Completeness-critique checks — measurements the seven finished studies never made.

This file exists to make a *critique* falsifiable.  Every claim in
`research/reports/COMPLETENESS_CRITIQUE.md` that carries a number comes from
here.  It imports the shared satylab modules read-only and defines nothing that
other studies depend on.

Blocks
------
A  Instrument transfer   cash RTH (^GSPC) vs a 24h instrument (ES=F) — do the
                         published base rates survive when the ladder is built
                         from 24h bars, which is what CAPITALCOM:SPX500 shows?
B  Where the day starts  on a 24h instrument, when is the named level FIRST
                         touched?  The "45.8% of days gap through the trigger"
                         fact is defined only on a cash instrument.
C  Resolution budget     measured bar ranges vs the TradingView export budget,
                         so the 3m/10m export recommendation is arithmetic and
                         not a guess.
D  Volatility regime     the panel's headline rates are pooled over 20y.  Are
                         they stable across ATR-percentile terciles?  No report
                         has ever conditioned on this.
E  Execution sizing      what one bar of alert-to-fill latency costs, in R.
                         Only the spread was ever modelled.
F  The untested P4       SPEC_SATY_PLAYBOOK §9 called it "the cheapest test,
                         do it first" — how often does a day trigger BOTH
                         branches of the two-sided script?  Nobody ran it.

Everything here is an exhaustive, pre-specified cross-tab: 104 proportion cells
and 13 two-proportion tests, all printed.  Bonferroni 5% over 13 tests is
|z| >= 2.88.  There is no cell-picking step anywhere in this file.

Usage: .venv/bin/python research/satylab/critique_checks.py
"""

from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402

RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def build_ladder(daily: list[Bar]) -> dict[date, levels.DayLevels]:
    return levels.build(daily)


# --------------------------------------------------------------- block A ---
def block_a() -> None:
    hr("A. INSTRUMENT TRANSFER — cash RTH ladder vs 24h ladder (20y daily)")

    g = data.daily("^GSPC", "20y")
    e = data.daily("ES=F", "20y")
    lg, le = build_ladder(g), build_ladder(e)

    gd = {b.day: b for b in g}
    ed = {b.day: b for b in e}
    common = sorted(set(lg) & set(le) & set(gd) & set(ed))
    print(f"overlapping sessions: n={len(common)}  {common[0]} -> {common[-1]}")

    # A1 — how much wider is the 24h ATR?
    ratios = []
    for d in common:
        a_g = lg[d].atr / lg[d].anchor
        a_e = le[d].atr / le[d].anchor
        ratios.append(a_e / a_g)
    ratios.sort()
    print("\nA1  ATR(14) as %% of price, 24h / cash ratio")
    print(f"    median {st.median(ratios):.3f}   "
          f"p10 {ratios[len(ratios)//10]:.3f}   "
          f"p90 {ratios[9*len(ratios)//10]:.3f}   "
          f"share >1.0: {sum(r > 1 for r in ratios)/len(ratios):.1%}")

    # A1b — is the widening real range, or a continuous-futures roll artifact?
    # Roll gaps enter the TR only through the |H-pc| / |L-pc| terms, so a
    # high-low-only comparison isolates the genuine overnight range.
    hl_g = st.median([(gd[d].high - gd[d].low) / gd[d].close for d in common])
    hl_e = st.median([(ed[d].high - ed[d].low) / ed[d].close for d in common])
    print(f"    high-low only (roll-immune): cash {hl_g:.5f}  24h {hl_e:.5f}  "
          f"ratio {hl_e/hl_g:.3f}")

    # A2 — touch rates for the same named ratio on each instrument's own ladder
    print("\nA2  P(day touches +r) on each instrument's own map "
          "(cash = RTH range, 24h = full session range)")
    print(f"    {'r':>7} {'cash':>22} {'24h':>22} {'z':>7}")
    for r in RATIOS:
        kg = sum(1 for d in common if gd[d].high >= lg[d].at(r))
        ke = sum(1 for d in common if ed[d].high >= le[d].at(r))
        z = stats.two_proportion_z(ke, len(common), kg, len(common))
        print(f"    {r:>+7.3f} {stats.fmt_rate(kg, len(common)):>22} "
              f"{stats.fmt_rate(ke, len(common)):>22} {z:>+7.2f}")

    # A3 — Golden Gate completion, daily resolution, both instruments
    print("\nA3  Golden Gate at daily resolution "
          "(monotone, so daily high/low is exact)")
    for name, bars, lv in (("cash RTH  ", gd, lg), ("24h       ", ed, le)):
        for sign, tag in ((+1, "bull"), (-1, "bear")):
            trig = comp = 0
            for d in common:
                b, L = bars[d], lv[d]
                hit = (b.high >= L.at(0.382)) if sign > 0 else (b.low <= L.at(-0.382))
                if not hit:
                    continue
                trig += 1
                done = (b.high >= L.at(0.618)) if sign > 0 else (b.low <= L.at(-0.618))
                comp += bool(done)
            print(f"    {name} {tag}  GG completion {stats.fmt_rate(comp, trig)}")

    # A4 — does the 24h session's own open sit outside the trigger box?
    print("\nA4  |open - anchor| > 0.236 ATR at the session open "
          "(2017+ only; ^GSPC open is a known artifact before that)")
    for name, bars, lv in (("cash 09:30", gd, lg), ("24h  18:00", ed, le)):
        days = [d for d in common if d.year >= 2017]
        k = sum(1 for d in days if abs(lv[d].ratio_of(bars[d].open)) > 0.236)
        print(f"    {name}: {stats.fmt_rate(k, len(days))}")


# --------------------------------------------------------------- block B ---
def block_b() -> None:
    hr("B. WHERE THE DAY STARTS — first touch on a 24h instrument (ES 1h, 730d)")

    e_daily = data.daily("ES=F", "20y")
    lv = build_ladder(e_daily)
    h = data.load("ES=F", "730d", "1h")

    by_day: dict[date, list[Bar]] = defaultdict(list)
    for b in h:
        by_day[b.day].append(b)
    days = sorted(by_day)

    # overnight = prior day's >=18:00 plus this day's <09:00
    # openhour  = the 09:00 bar (straddles the 09:30 cash open — reported apart)
    # rth       = 10:00 .. 16:00
    counted = 0
    first_bucket: dict[float, dict[str, int]] = {r: defaultdict(int) for r in RATIOS}
    on_range_share: list[float] = []

    for i, d in enumerate(days):
        if d not in lv or i == 0:
            continue
        rows = sorted(by_day[d], key=lambda x: x.dt)
        prev = sorted(by_day[days[i - 1]], key=lambda x: x.dt)
        overnight = [b for b in prev if b.hhmm >= "18:00"] + \
                    [b for b in rows if b.hhmm < "09:00"]
        openhour = [b for b in rows if b.hhmm == "09:00"]
        rth = [b for b in rows if "10:00" <= b.hhmm <= "16:00"]
        if len(overnight) < 6 or len(rth) < 5 or not openhour:
            continue
        counted += 1
        L = lv[d]
        seq = [("overnight", overnight), ("open_hour", openhour), ("rth", rth)]
        for r in RATIOS:
            price = L.at(r)
            for tag, group in seq:
                if any(b.high >= price for b in group):
                    first_bucket[r][tag] += 1
                    break
            else:
                first_bucket[r]["never"] += 1
        allbars = overnight + openhour + rth
        full = max(b.high for b in allbars) - min(b.low for b in allbars)
        rth_only = max(b.high for b in rth + openhour) - min(b.low for b in rth + openhour)
        if full > 0:
            on_range_share.append(1 - rth_only / full)

    print(f"sessions counted: n={counted}  ({days[0]} -> {days[-1]})")
    print("\nB1  When is the UPSIDE level first touched, on a 24h instrument?")
    print(f"    {'r':>7} {'overnight':>12} {'09:00 bar':>12} {'10:00+':>12} {'never':>12}")
    for r in RATIOS:
        row = first_bucket[r]
        tot = sum(row.values())
        print(f"    {r:>+7.3f} " + " ".join(
            f"{row[t]/tot:>11.1%}" for t in ("overnight", "open_hour", "rth", "never")))

    on_range_share.sort()
    print(f"\nB2  share of the 24h session range made outside 09:00-16:00: "
          f"median {st.median(on_range_share):.1%}  "
          f"p25 {on_range_share[len(on_range_share)//4]:.1%}  "
          f"p75 {on_range_share[3*len(on_range_share)//4]:.1%}  n={len(on_range_share)}")


# --------------------------------------------------------------- block C ---
def block_c() -> None:
    hr("C. RESOLUTION BUDGET — measured bar ranges vs the TradingView export cap")

    g5 = data.fine()
    gl = build_ladder(data.daily())
    rngs = [(b.high - b.low) / gl[b.day].atr for b in g5 if b.day in gl]
    rngs.sort()
    print(f"^GSPC 5m bar range / daily ATR   n={len(rngs)}  "
          f"median {st.median(rngs):.4f}  p90 {rngs[9*len(rngs)//10]:.4f}  "
          f"p99 {rngs[99*len(rngs)//100]:.4f}")

    h = data.hourly()
    hl = [(b.high - b.low) / gl[b.day].atr for b in h if b.day in gl]
    hl.sort()
    print(f"^GSPC 1h bar range / daily ATR   n={len(hl)}  "
          f"median {st.median(hl):.4f}  p90 {hl[9*len(hl)//10]:.4f}")

    # synthetic 10m / 15m, so the export recommendation rests on a measurement
    sess = data.group_by_day(g5)
    for k, label in ((2, "10m"), (3, "15m")):
        r = []
        for day, bars in sess.items():
            if day not in gl:
                continue
            for i in range(0, len(bars) - k + 1, k):
                grp = bars[i:i + k]
                r.append((max(b.high for b in grp) - min(b.low for b in grp))
                         / gl[day].atr)
        r.sort()
        print(f"^GSPC {label} bar range / daily ATR  n={len(r)}  "
              f"median {st.median(r):.4f}  p90 {r[9*len(r)//10]:.4f}   "
              f"(synthesised from 5m)")

    e5 = data.load("ES=F", "60d", "5m")
    el = build_ladder(data.daily("ES=F", "20y"))
    er = [(b.high - b.low) / el[b.day].atr for b in e5 if b.day in el]
    er.sort()
    print(f"ES=F  5m bar range / daily ATR   n={len(er)}  "
          f"median {st.median(er):.4f}  p90 {er[9*len(er)//10]:.4f}")

    print("\nC2  TradingView export arithmetic (20 000 bars, CFD trades ~23h/day)")
    for tf, minutes in (("1m", 1), ("3m", 3), ("5m", 5), ("10m", 10),
                        ("15m", 15), ("1h", 60)):
        per_day_24 = int(23 * 60 / minutes)
        per_day_rth = max(1, int(6.5 * 60 / minutes))
        print(f"    {tf:>4}  bars/day 24h={per_day_24:>4}  "
              f"=> {20000/per_day_24:>7.0f} sessions   "
              f"(RTH-only equivalent {20000/per_day_rth:>6.0f} sessions)")


# --------------------------------------------------------------- block D ---
def block_d() -> None:
    hr("D. VOLATILITY REGIME — are the pooled base rates stable? (20y daily ^GSPC)")

    g = data.daily()
    lv = build_ladder(g)
    gd = {b.day: b for b in g}
    days = sorted(lv)

    vol = {d: lv[d].atr / lv[d].anchor for d in days}
    cuts = sorted(vol.values())
    lo, hi = cuts[len(cuts) // 3], cuts[2 * len(cuts) // 3]

    def tercile(d: date) -> str:
        v = vol[d]
        return "low" if v <= lo else ("mid" if v <= hi else "high")

    groups: dict[str, list[date]] = defaultdict(list)
    for d in days:
        groups[tercile(d)].append(d)

    print(f"ATR%/price terciles: low <= {lo:.4f} < mid <= {hi:.4f} < high")
    print(f"{'metric':<34}{'low':>20}{'mid':>20}{'high':>20}{'z(hi-lo)':>10}")

    def report(name, fn_hit, fn_cond=None):
        cells = {}
        for gname in ("low", "mid", "high"):
            k = n = 0
            for d in groups[gname]:
                if fn_cond and not fn_cond(d):
                    continue
                n += 1
                k += bool(fn_hit(d))
            cells[gname] = (k, n)
        z = stats.two_proportion_z(*cells["high"], *cells["low"])
        print(f"{name:<34}" + "".join(
            f"{stats.fmt_rate(*cells[g]):>20}" for g in ("low", "mid", "high"))
            + f"{z:>+10.2f}")

    report("P(touch +1 ATR)", lambda d: gd[d].high >= lv[d].at(1.0))
    report("P(touch -1 ATR)", lambda d: gd[d].low <= lv[d].at(-1.0))
    report("P(day range >= 1 ATR)",
           lambda d: (gd[d].high - gd[d].low) >= lv[d].atr)
    report("P(GG done | GG entry, bull)",
           lambda d: gd[d].high >= lv[d].at(0.618),
           lambda d: gd[d].high >= lv[d].at(0.382))
    report("P(GG done | GG entry, bear)",
           lambda d: gd[d].low <= lv[d].at(-0.618),
           lambda d: gd[d].low <= lv[d].at(-0.382))
    report("P(touch +0.236)", lambda d: gd[d].high >= lv[d].at(0.236))
    report("P(no trigger either side)",
           lambda d: gd[d].high < lv[d].at(0.236) and gd[d].low > lv[d].at(-0.236))

    # year-by-year spread on the single most-quoted number
    print("\nD2  P(day range >= 1 ATR) by calendar year (the panel prints 33.0%)")
    per_year: dict[int, list[bool]] = defaultdict(list)
    for d in days:
        per_year[d.year].append((gd[d].high - gd[d].low) >= lv[d].atr)
    rows = [(y, sum(v) / len(v), len(v)) for y, v in sorted(per_year.items())]
    lo_y = min(rows, key=lambda x: x[1])
    hi_y = max(rows, key=lambda x: x[1])
    print("    " + "  ".join(f"{y}:{p:.0%}" for y, p, _ in rows))
    print(f"    min {lo_y[0]} {lo_y[1]:.1%} (n={lo_y[2]})   "
          f"max {hi_y[0]} {hi_y[1]:.1%} (n={hi_y[2]})")

    print("\nD3  year-by-year dispersion of the numbers the panel prints")
    print(f"    {'metric':<30}{'pooled':>22}{'min yr':>12}{'max yr':>12}"
          f"{'yr sd':>8}{'CI halfwidth':>14}")

    def yearly(name, fn_hit, fn_cond=None):
        per: dict[int, list[bool]] = defaultdict(list)
        K = N = 0
        for d in days:
            if fn_cond and not fn_cond(d):
                continue
            v = bool(fn_hit(d))
            per[d.year].append(v)
            K += v
            N += 1
        rates = [sum(v) / len(v) for v in per.values() if len(v) >= 30]
        lo_ci, hi_ci = stats.wilson(K, N) if hasattr(stats, "wilson") else (0, 0)
        half = (hi_ci - lo_ci) / 2 * 100 if hi_ci else float("nan")
        print(f"    {name:<30}{stats.fmt_rate(K, N):>22}"
              f"{min(rates):>11.1%}{max(rates):>12.1%}"
              f"{st.pstdev(rates)*100:>7.1f}pp{half:>12.1f}pp")

    yearly("P(day range >= 1 ATR)",
           lambda d: (gd[d].high - gd[d].low) >= lv[d].atr)
    yearly("P(GG done | entry, bull)",
           lambda d: gd[d].high >= lv[d].at(0.618),
           lambda d: gd[d].high >= lv[d].at(0.382))
    yearly("P(touch +1 ATR)", lambda d: gd[d].high >= lv[d].at(1.0))
    yearly("P(touch +0.236)", lambda d: gd[d].high >= lv[d].at(0.236))


# --------------------------------------------------------------- block E ---
def block_e() -> None:
    hr("E. EXECUTION SIZING — what a second of latency is worth (5m, 60d)")

    d = data.daily()
    lv = build_ladder(d)
    f = data.fine()
    sess = data.group_by_day(f)

    # For every first touch of +/-0.382, how far does price travel during the
    # NEXT 5m bar?  An alert that fires on the touch and a human who reacts
    # inside the following bar pays some fraction of this.
    adverse: list[float] = []
    favorable: list[float] = []
    signed_close: list[float] = []
    for day, bars in sorted(sess.items()):
        if day not in lv:
            continue
        L = lv[day]
        for sign in (+1, -1):
            price = L.at(sign * 0.382)
            idx = None
            for i, b in enumerate(bars):
                if (b.high >= price) if sign > 0 else (b.low <= price):
                    idx = i
                    break
            if idx is None or idx + 1 >= len(bars):
                continue
            nxt = bars[idx + 1]
            ref = bars[idx].close
            # "continuation" trade: sign is the trade direction
            fav = (nxt.high - ref) if sign > 0 else (ref - nxt.low)
            adv = (ref - nxt.low) if sign > 0 else (nxt.high - ref)
            favorable.append(fav / L.atr)
            adverse.append(adv / L.atr)
            signed_close.append(sign * (nxt.close - ref) / L.atr)

    n = len(favorable)
    print(f"first touches of +/-0.382 with a following 5m bar: n={n}")
    print(f"    next-bar favourable excursion  median {st.median(favorable):.4f} ATR")
    print(f"    next-bar adverse   excursion  median {st.median(adverse):.4f} ATR")
    print(f"    next-bar signed close change  median {st.median(signed_close):+.4f} ATR"
          f"   mean {st.mean(signed_close):+.4f} ATR")

    atr_med = st.median([lv[day].atr for day in sess if day in lv])
    print(f"\n    median daily ATR over the window: {atr_med:.1f} SPX points")
    risk_pts = 0.236 * atr_med
    print(f"    a 0.236 ATR stop = {risk_pts:.1f} points = 1R")
    for label, pts in (("研究里用的 0.4 点", 0.4), ("研究里用的 0.8 点", 0.8),
                       ("RTH CFD 点差 ~1.0", 1.0), ("夜盘 CFD 点差 ~2.4", 2.4),
                       ("1 根 5m K 的中位不利行程", st.median(adverse) * atr_med)):
        print(f"      {label:<28} {pts:>6.2f} pts = {pts/risk_pts:>6.3f} R")


# --------------------------------------------------------------- block F ---
def block_f() -> None:
    hr("F. THE UNTESTED P4 — how often does the day trigger BOTH branches? "
       "(20y daily)")
    print("SPEC_SATY_PLAYBOOK §9 called this 'the cheapest test, do it first'."
          "  No report did it.")

    g = data.daily()
    lv = build_ladder(g)
    gd = {b.day: b for b in g}
    days = sorted(lv)

    for r in (0.236, 0.382, 0.5, 0.618):
        both = up = dn = neither = 0
        for d in days:
            b, L = gd[d], lv[d]
            u = b.high >= L.at(r)
            v = b.low <= L.at(-r)
            both += u and v
            up += u and not v
            dn += v and not u
            neither += not u and not v
        n = len(days)
        print(f"  +/-{r:<6.3f}  both {stats.fmt_rate(both, n)}   "
              f"one-sided-up {up/n:>6.1%}  down {dn/n:>6.1%}  "
              f"neither {neither/n:>6.1%}")

    # same question on the 24h instrument, where the day is 23h long
    e = data.daily("ES=F", "20y")
    le = build_ladder(e)
    ed = {b.day: b for b in e}
    edays = sorted(set(le) & set(ed))
    print("\n  same test on the 24h instrument (its own ladder, its own day):")
    for r in (0.236, 0.382):
        both = sum(1 for d in edays
                   if ed[d].high >= le[d].at(r) and ed[d].low <= le[d].at(-r))
        print(f"  +/-{r:<6.3f}  both {stats.fmt_rate(both, len(edays))}")


if __name__ == "__main__":
    block_a()
    block_b()
    block_c()
    block_d()
    block_e()
    block_f()
