"""Does the Saty Pivot Ribbon actually carry information?  An adversarial test.

This study exists to answer one question with a number instead of an opinion:
if we condition on ribbon state, do forward outcomes move enough to matter, or
is the ribbon a picture that happens to be drawn on top of a random walk?

Design commitments made BEFORE any number was looked at (so that a sceptical
reader can check we did not fit):

  * Ribbon definition comes from `satylab.ribbon_spec` (8/21/34 EMA on close,
    transcribed from the author's published source), NOT from the invented
    4-state `indicators.RibbonState.label()`.  We report `state` (EMA stacking,
    3 levels) and `price_zone` (close vs ribbon body, 3 levels) SEPARATELY,
    because they are orthogonal and the old label mixed them.  The legacy label
    is reported once, for continuity with earlier work.
  * The barrier distance is 0.236 x day-ATR.  That is Saty's own ladder step
    (the call/put trigger), not a searched parameter.  No other distance was
    tried.
  * Two forward horizons, both fixed in advance:
        NEXT3   the next 3 hourly bars (fixed length -> immune to the
                "late-day bars have less time left" confound)
        REST    the remainder of the RTH session (what a day trader actually
                has), always reported alongside an hour-of-day breakdown so
                the confound is visible rather than hidden.
  * Every rate carries a Wilson interval and n.  Every conditional rate carries
    a two-proportion z against the unconditional baseline.  |z| < 1.96 is
    reported in words as "did no work".
  * Hourly bars inside one session are NOT independent, so the headline
    comparisons additionally get a day-block bootstrap (resample whole
    sessions with replacement).  Where the bootstrap interval for the
    difference straddles zero, the Wilson/z picture is treated as optimistic.
  * The number of rate cells inspected is counted by the program itself and
    printed at the end.  Nothing here is a search; every table is exhaustive.

Run:  .venv/bin/python research/satylab/study_ribbon.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

if __package__ in (None, ""):
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
    from satylab import data, indicators, levels          # noqa: E402
    from satylab import ribbon_spec as R                  # noqa: E402
    from satylab.data import Bar                          # noqa: E402
    from satylab.stats import fmt_rate, two_proportion_z   # noqa: E402
else:
    from . import data, indicators, levels
    from . import ribbon_spec as R
    from .data import Bar
    from .stats import fmt_rate, two_proportion_z

# ------------------------------------------------------------------ constants
BARRIER = 0.236          # Saty's trigger step, in day-ATR units. Not searched.
NEXT_N = 3               # fixed forward horizon, in hourly bars
BOOT = 2000              # bootstrap resamples
SEED = 20260725

STATES = ("full_bull", "folded", "full_bear")
ZONES = ("above", "inside", "below")

_CELLS = 0               # every rate cell printed anywhere increments this


def cell(k: int, n: int) -> str:
    global _CELLS
    _CELLS += 1
    return fmt_rate(k, n)


def zline(name: str, k: int, n: int, bk: int, bn: int, width: int = 30) -> str:
    """One conditional row: rate, CI, n, and the z against the baseline."""
    txt = cell(k, n)
    if n == 0:
        return f"  {name:<{width}}{txt}"
    z = two_proportion_z(k, n, bk, bn)
    tag = "" if abs(z) >= 1.96 else "   <- no work"
    return f"  {name:<{width}}{txt}   z={z:+5.2f}{tag}"


# ------------------------------------------------------------------ bootstrap
def block_bootstrap_diff(groups: list[tuple[int, int, int, int]],
                         b: int = BOOT, seed: int = SEED) -> tuple[float, float, float]:
    """Day-block bootstrap of (cell rate - baseline rate).

    `groups` is one tuple per session: (k_cell, n_cell, k_base, n_base).
    Whole sessions are resampled with replacement, which preserves the
    within-day dependence that makes the naive Wilson interval too narrow.
    Returns (lo, hi, share_of_resamples_with_diff<=0).
    """
    rng = random.Random(seed)
    m = len(groups)
    if m == 0:
        return (0.0, 0.0, 1.0)
    diffs: list[float] = []
    le0 = 0
    for _ in range(b):
        kc = nc = kb = nb = 0
        for _ in range(m):
            g = groups[rng.randrange(m)]
            kc += g[0]; nc += g[1]; kb += g[2]; nb += g[3]
        if nc == 0 or nb == 0:
            continue
        d = kc / nc - kb / nb
        diffs.append(d)
        le0 += int(d <= 0)
    if not diffs:
        return (0.0, 0.0, 1.0)
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    return (lo, hi, le0 / len(diffs))


def boot_line(label: str, recs: list, key, hit, b: int = BOOT) -> str:
    """Bootstrap the difference between `key`-selected records and everything."""
    per_day: dict = defaultdict(lambda: [0, 0, 0, 0])
    for r in recs:
        g = per_day[r.day]
        h = int(hit(r))
        if key(r):
            g[0] += h; g[1] += 1
        g[2] += h; g[3] += 1
    groups = [tuple(v) for v in per_day.values()]
    lo, hi, _ = block_bootstrap_diff(groups, b)
    straddle = "  STRADDLES 0" if lo <= 0 <= hi else ""
    return (f"  {label:<30}diff vs baseline  "
            f"[{100*lo:+5.1f}, {100*hi:+5.1f}] pp (day-block boot, B={b})"
            f"{straddle}")


def moving_block_bootstrap_diff(seq: list[tuple[int, int, int, int]],
                                block: int = 21, b: int = BOOT,
                                seed: int = SEED) -> tuple[float, float]:
    """Moving-block bootstrap for the daily series (block ~= one month)."""
    rng = random.Random(seed)
    n = len(seq)
    if n < block:
        return (0.0, 0.0)
    nb = n // block
    diffs: list[float] = []
    for _ in range(b):
        kc = nc = kb = nbase = 0
        for _ in range(nb):
            s = rng.randrange(0, n - block)
            for r in seq[s:s + block]:
                kc += r[0]; nc += r[1]; kb += r[2]; nbase += r[3]
        if nc == 0 or nbase == 0:
            continue
        diffs.append(kc / nc - kb / nbase)
    if not diffs:
        return (0.0, 0.0)
    diffs.sort()
    return (diffs[int(0.025 * len(diffs))],
            diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))])


# ------------------------------------------------------------------ records
@dataclass
class HRec:
    """One hourly bar, with its ribbon reading and its forward outcomes."""
    i: int
    day: date
    hhmm: str
    idx_in_day: int
    close: float
    atr: float
    state: str
    zone: str
    legacy: str
    d_state: str            # daily ribbon via TimeWarp
    d_zone: str
    # forward outcomes (None = not evaluable)
    y_next_up: bool | None = None
    y_up3: bool | None = None
    y_dn3: bool | None = None
    y_uponly3: bool | None = None
    y_up_rest: bool | None = None
    y_dn_rest: bool | None = None
    y_uponly_rest: bool | None = None
    mfe3: float | None = None      # max favourable excursion, ATR units
    mae3: float | None = None      # max adverse excursion, ATR units
    rv3: float | None = None       # BACKWARD realised range, prior 3 bars / ATR
    # named-level variants (rest of session)
    lvl_up_dist: float | None = None
    lvl_dn_dist: float | None = None
    y_lvl_up: bool | None = None
    y_lvl_dn: bool | None = None
    y_lvl_uponly: bool | None = None
    # setup flags
    reclaim_up: bool = False
    reclaim_dn: bool = False
    hold_pivot: bool = False
    lose_pivot: bool = False
    reclaim_up_bull: bool = False


def build_hourly_records() -> tuple[list[HRec], list[Bar], dict]:
    d = data.daily(years="20y")
    h_raw = data.hourly()
    lv = levels.build(d)

    # Yahoo appends a stub 16:00 bar on the live session; drop it, and drop any
    # session we have no prior-day level map for.
    h = [b for b in h_raw if b.hhmm != "16:00" and b.day in lv]

    fs = R.frames(h)                       # hourly ribbon (8/21/34 on close)
    legacy = indicators.ribbon(h)          # the old 4-state label, for continuity
    tw = R.timewarp(h, d, lag=1)           # daily ribbon held flat across the day

    sessions = data.group_by_day(h)
    day_start: dict[date, int] = {}
    for i, b in enumerate(h):
        day_start.setdefault(b.day, i)

    # ---- zone run history for the pullback/reclaim setup
    zones = [f.price_zone if f else None for f in fs]

    recs: list[HRec] = []
    n_h = len(h)
    for i, b in enumerate(h):
        f = fs[i]
        if f is None:
            continue
        dl = lv[b.day]
        tf = tw[i]
        rec = HRec(
            i=i, day=b.day, hhmm=b.hhmm,
            idx_in_day=i - day_start[b.day],
            close=b.close, atr=dl.atr,
            state=f.state, zone=f.price_zone,
            legacy=(legacy[i].label() if legacy[i] else "na"),
            d_state=(tf.state if tf else "na"),
            d_zone=(tf.price_zone if tf else "na"),
        )

        U = b.close + BARRIER * dl.atr
        L = b.close - BARRIER * dl.atr

        # backward-looking volatility proxy: the dumbest thing that could work
        if i >= NEXT_N:
            w0 = h[i - NEXT_N + 1:i + 1]
            rec.rv3 = sum(x.high - x.low for x in w0) / dl.atr

        # --- NEXT3: fixed horizon, crosses sessions on purpose (no time-of-day bias)
        if i + NEXT_N < n_h:
            w = h[i + 1:i + 1 + NEXT_N]
            up = any(x.high >= U for x in w)
            dn = any(x.low <= L for x in w)
            rec.y_up3, rec.y_dn3, rec.y_uponly3 = up, dn, (up and not dn)
            rec.mfe3 = (max(x.high for x in w) - b.close) / dl.atr
            rec.mae3 = (b.close - min(x.low for x in w)) / dl.atr

        # --- REST: remainder of this RTH session
        rest = [x for x in sessions[b.day] if x.dt > b.dt]
        if rest:
            up = any(x.high >= U for x in rest)
            dn = any(x.low <= L for x in rest)
            rec.y_up_rest, rec.y_dn_rest, rec.y_uponly_rest = up, dn, (up and not dn)
            rec.y_next_up = rest[0].close > b.close

            # --- named-ladder variant: next Saty level above vs below
            ups = [r for r in levels.RATIOS if dl.at(r) > b.close]
            dns = [r for r in levels.RATIOS if dl.at(r) < b.close]
            if ups and dns:
                pu, pl = dl.at(min(ups)), dl.at(max(dns))
                rec.lvl_up_dist = (pu - b.close) / dl.atr
                rec.lvl_dn_dist = (b.close - pl) / dl.atr
                lu = any(x.high >= pu for x in rest)
                ld = any(x.low <= pl for x in rest)
                rec.y_lvl_up, rec.y_lvl_dn = lu, ld
                rec.y_lvl_uponly = lu and not ld

        # --- setups (definitions fixed in advance, see module docstring)
        if i >= 2 and zones[i] == "above" and zones[i - 1] == "inside":
            j = i - 1
            while j >= 0 and zones[j] == "inside":
                j -= 1
            if j >= 0 and zones[j] == "above":
                rec.reclaim_up = True
                rec.reclaim_up_bull = (f.state == "full_bull")
        if i >= 2 and zones[i] == "below" and zones[i - 1] == "inside":
            j = i - 1
            while j >= 0 and zones[j] == "inside":
                j -= 1
            if j >= 0 and zones[j] == "below":
                rec.reclaim_dn = True
        rec.hold_pivot = R.holding_pivot(f)
        rec.lose_pivot = (f.high >= f.e21 and f.close < f.e21)

        recs.append(rec)
    return recs, h, lv


# ------------------------------------------------------------------ sections
def sec(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def rate_of(recs: list[HRec], attr: str) -> tuple[int, int]:
    k = n = 0
    for r in recs:
        v = getattr(r, attr)
        if v is None:
            continue
        n += 1
        k += int(v)
    return k, n


def table(recs: list[HRec], keyfn, keys, outcomes: list[tuple[str, str]],
          title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for attr, label in outcomes:
        bk, bn = rate_of(recs, attr)
        print(f"\n  outcome: {label}")
        print(f"  {'BASELINE (all bars)':<30}{cell(bk, bn)}")
        for kv in keys:
            sub = [r for r in recs if keyfn(r) == kv]
            k, n = rate_of(sub, attr)
            print(zline(str(kv), k, n, bk, bn))


# ------------------------------------------------------------------ main
def main() -> None:
    print("=" * 78)
    print("PIVOT RIBBON — does it carry information?  (adversarial base-rate study)")
    print("=" * 78)

    recs, h, lv = build_hourly_records()
    d = data.daily(years="20y")
    print(f"\nhourly bars usable: {len(recs)} / {len(h)}   "
          f"sessions: {len({r.day for r in recs})}   "
          f"span: {recs[0].day} .. {recs[-1].day}")
    print(f"barrier = {BARRIER} x day-ATR (Saty's trigger step; not searched)")
    print(f"horizons: NEXT{NEXT_N} hourly bars (fixed) and REST-of-session")

    # ---------------------------------------------------------------- SECTION 1
    sec("1.  STATE OCCUPANCY — is the ribbon even selective?")
    n = len(recs)
    print("\n  hourly ribbon `state` (EMA stacking 8/21/34):")
    cs = Counter(r.state for r in recs)
    for s in STATES:
        print(f"    {s:<12}{cs[s]:5d}   {100*cs[s]/n:5.1f}%")
    print("\n  hourly `price_zone` (close vs ribbon body):")
    cz = Counter(r.zone for r in recs)
    for z in ZONES:
        print(f"    {z:<12}{cz[z]:5d}   {100*cz[z]/n:5.1f}%")
    print("\n  joint state x zone:")
    cj = Counter((r.state, r.zone) for r in recs)
    for s in STATES:
        for z in ZONES:
            print(f"    {s+'/'+z:<20}{cj[(s, z)]:5d}   {100*cj[(s, z)]/n:5.1f}%")
    print("\n  legacy indicators.RibbonState.label() (4-state, mixes the two axes):")
    cl = Counter(r.legacy for r in recs)
    for k2, v in cl.most_common():
        print(f"    {k2:<12}{v:5d}   {100*v/n:5.1f}%")
    print("\n  daily ribbon seen through TimeWarp (state on the hourly bars):")
    cd = Counter(r.d_state for r in recs)
    for s in STATES:
        print(f"    {s:<12}{cd[s]:5d}   {100*cd[s]/n:5.1f}%")

    # ---------------------------------------------------------------- SECTION 2
    sec("2.  HOURLY RIBBON AS A CONDITIONER — forward outcomes")
    OUT = [
        ("y_next_up", f"next hourly bar closes up (same session)"),
        ("y_up3", f"touches +{BARRIER} ATR within next {NEXT_N} bars"),
        ("y_dn3", f"touches -{BARRIER} ATR within next {NEXT_N} bars"),
        ("y_uponly3", f"+{BARRIER} ATR touched and -{BARRIER} NOT (next {NEXT_N})"),
        ("y_up_rest", f"touches +{BARRIER} ATR in rest of session"),
    ]
    table(recs, lambda r: r.state, STATES, OUT, "2a. by ribbon `state`")
    table(recs, lambda r: r.zone, ZONES, OUT, "2b. by `price_zone`")
    table(recs, lambda r: f"{r.state}/{r.zone}",
          [f"{s}/{z}" for s in STATES for z in ZONES], OUT,
          "2c. by state x zone (joint)")

    # directional skew summary
    print("\n2d. directional skew  P(up-only) - P(down-only), next %d bars" % NEXT_N)
    print("    (down-only = -%.3f touched and +%.3f not)" % (BARRIER, BARRIER))
    def skew(sub: list[HRec]) -> str:
        up = sum(1 for r in sub if r.y_uponly3 is True)
        dn = sum(1 for r in sub if r.y_up3 is False and r.y_dn3 is True)
        m = sum(1 for r in sub if r.y_up3 is not None)
        if m == 0:
            return "n=0"
        return (f"up-only {100*up/m:5.1f}%   down-only {100*dn/m:5.1f}%   "
                f"skew {100*(up-dn)/m:+5.1f}pp   n={m}")
    print(f"    {'ALL BARS':<22}{skew(recs)}")
    for s in STATES:
        print(f"    {s:<22}{skew([r for r in recs if r.state == s])}")
    for z in ZONES:
        print(f"    {z:<22}{skew([r for r in recs if r.zone == z])}")

    # ---- THE DECISIVE DECOMPOSITION -------------------------------------
    print("\n2e. DIRECTION vs VOLATILITY decomposition (next %d bars)" % NEXT_N)
    print("    Four mutually exclusive outcomes.  `both` and `neither` are pure")
    print("    volatility; only the split between up-only and down-only is")
    print("    direction.  A direction indicator must move the LAST column.")
    print(f"    {'':<14}{'up-only':>9}{'down-only':>10}{'both':>8}{'neither':>9}"
          f"{'  P(up | exactly one side)':>28}")

    def quad(sub: list[HRec]) -> tuple[int, int, int, int]:
        uo = do = bo = ne = 0
        for r in sub:
            if r.y_up3 is None:
                continue
            if r.y_up3 and not r.y_dn3:
                uo += 1
            elif r.y_dn3 and not r.y_up3:
                do += 1
            elif r.y_up3 and r.y_dn3:
                bo += 1
            else:
                ne += 1
        return uo, do, bo, ne

    buo, bdo, bbo, bne = quad(recs)
    btot = buo + bdo + bbo + bne
    print(f"    {'ALL BARS':<14}{100*buo/btot:8.1f}%{100*bdo/btot:9.1f}%"
          f"{100*bbo/btot:7.1f}%{100*bne/btot:8.1f}%      {cell(buo, buo+bdo)}")
    dirrows = []
    for lbl, sel in ([(s, lambda r, s=s: r.state == s) for s in STATES]
                     + [(z, lambda r, z=z: r.zone == z) for z in ZONES]):
        sub = [r for r in recs if sel(r)]
        uo, do, bo, ne = quad(sub)
        tot = max(1, uo + do + bo + ne)
        z = two_proportion_z(uo, uo + do, buo, buo + bdo)
        tag = "" if abs(z) >= 1.96 else "  <- no work"
        print(f"    {lbl:<14}{100*uo/tot:8.1f}%{100*do/tot:9.1f}%"
              f"{100*bo/tot:7.1f}%{100*ne/tot:8.1f}%      {cell(uo, uo+do)}"
              f"  z={z:+5.2f}{tag}")
        dirrows.append((lbl, uo, do, z))

    print("\n2e-bis. median excursion over the next %d bars (ATR units) —" % NEXT_N)
    print("    the same story in continuous form: MFE and MAE move TOGETHER,")
    print("    which is a volatility signature, not a direction signature.")
    for lbl, sel in ([("ALL BARS", lambda r: True)]
                     + [(s, lambda r, s=s: r.state == s) for s in STATES]
                     + [(z, lambda r, z=z: r.zone == z) for z in ZONES]):
        sub = [r for r in recs if sel(r) and r.mfe3 is not None]
        if not sub:
            continue
        mfe = sorted(r.mfe3 for r in sub)
        mae = sorted(r.mae3 for r in sub)
        m1, m2 = mfe[len(mfe)//2], mae[len(mae)//2]
        print(f"    {lbl:<14}MFE {m1:.3f}   MAE {m2:.3f}   "
              f"MFE-MAE {m1-m2:+.3f}   sum {m1+m2:.3f}   n={len(sub)}")

    # bootstrap on the headline outcome
    print(f"\n2g. day-block bootstrap on the headline outcome "
          f"(up-only, next {NEXT_N} bars)")
    for s in STATES:
        print(boot_line(s, [r for r in recs if r.y_uponly3 is not None],
                        lambda r, s=s: r.state == s, lambda r: r.y_uponly3))
    for z in ZONES:
        print(boot_line(z, [r for r in recs if r.y_uponly3 is not None],
                        lambda r, z=z: r.zone == z, lambda r: r.y_uponly3))

    # hour-of-day control for the REST outcome
    # ---- is the ribbon's ONLY real signal already free? ------------------
    print("\n2h. IS THE VOLATILITY SIGNAL FREE?  Ribbon vs the dumbest possible")
    print("    volatility proxy: rv3 = (sum of the previous %d hourly bar ranges)"
          % NEXT_N)
    print("    / day-ATR.  Backward looking, one line of code, no indicator.")
    print("    Tercile cut-points are computed on the whole sample (in-sample")
    print("    boundaries only — a minor optimism that favours the PROXY, i.e.")
    print("    it makes the ribbon look better than this test says, not worse).")
    pool = [r for r in recs if r.rv3 is not None and r.y_up3 is not None]
    vals = sorted(r.rv3 for r in pool)
    q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]

    def terc(r: HRec) -> str:
        return "vol_low" if r.rv3 < q1 else ("vol_mid" if r.rv3 < q2 else "vol_high")

    print(f"\n    tercile cut-points: rv3 < {q1:.3f} / < {q2:.3f} / else")
    print(f"    outcome: touches +{BARRIER} ATR within next {NEXT_N} bars")
    bk, bn = rate_of(pool, "y_up3")
    print(f"    {'BASELINE':<22}{cell(bk, bn)}")
    print("    -- spread produced by the RIBBON --")
    for s in STATES:
        k, m = rate_of([r for r in pool if r.state == s], "y_up3")
        print("  " + zline(s, k, m, bk, bn, 22))
    print("    -- spread produced by the FREE PROXY --")
    for t in ("vol_low", "vol_mid", "vol_high"):
        k, m = rate_of([r for r in pool if terc(r) == t], "y_up3")
        print("  " + zline(t, k, m, bk, bn, 22))
    print("\n    -- ribbon INSIDE each volatility tercile (the real question) --")
    for t in ("vol_low", "vol_mid", "vol_high"):
        sub = [r for r in pool if terc(r) == t]
        tk, tn = rate_of(sub, "y_up3")
        print(f"    {t} baseline        {cell(tk, tn)}")
        for s in STATES:
            k, m = rate_of([r for r in sub if r.state == s], "y_up3")
            print("    " + zline("  " + s, k, m, tk, tn, 22))

    print(f"\n2i. hour-of-day control (outcome: touches +{BARRIER} ATR in rest of "
          f"session) — shows the REST horizon's built-in time confound")
    hours = sorted({r.hhmm for r in recs})
    for hh in hours:
        sub = [r for r in recs if r.hhmm == hh]
        bk, bn = rate_of(sub, "y_up_rest")
        if bn < 30:
            continue
        row = f"    {hh}  all {cell(bk, bn)}"
        for s in STATES:
            k, m = rate_of([r for r in sub if r.state == s], "y_up_rest")
            z = two_proportion_z(k, m, bk, bn) if m else 0.0
            cell(k, m)   # counted in the family total
            row += f" | {s[:9]} {100*k/m if m else 0:4.1f}% (z={z:+4.1f})"
        print(row)

    # ---------------------------------------------------------------- SECTION 3
    sec("3.  THE PRACTICAL QUESTION — next named level above vs below")
    print("\n  Definition: from the close of an hourly bar, the next Saty ladder")
    print("  level above and the next one below.  Which gets touched in the rest")
    print("  of the session?  Distances are NOT equal, so the median distance to")
    print("  each is printed as a confound control.")
    for name, keyfn, keys in (("state", lambda r: r.state, STATES),
                              ("zone", lambda r: r.zone, ZONES)):
        print(f"\n  by {name}:")
        for attr, label in (("y_lvl_up", "touches next level ABOVE"),
                            ("y_lvl_dn", "touches next level BELOW"),
                            ("y_lvl_uponly", "ABOVE touched, BELOW not")):
            bk, bn = rate_of(recs, attr)
            print(f"\n    outcome: {label}")
            print(f"    {'BASELINE':<30}{cell(bk, bn)}")
            for kv in keys:
                sub = [r for r in recs if keyfn(r) == kv]
                k, m = rate_of(sub, attr)
                print("  " + zline(str(kv), k, m, bk, bn))
        print(f"\n    normalised direction: P(ABOVE-only | exactly one side), by {name}")
        print("    (the raw 'ABOVE-only' row above is contaminated by volatility —")
        print("     when both levels get hit, 'only' falls for reasons of range,")
        print("     not of direction.  This row removes that.)")

        def lquad(sub: list[HRec]) -> tuple[int, int]:
            uo = do = 0
            for r in sub:
                if r.y_lvl_up is None:
                    continue
                if r.y_lvl_up and not r.y_lvl_dn:
                    uo += 1
                elif r.y_lvl_dn and not r.y_lvl_up:
                    do += 1
            return uo, do

        buo, bdo = lquad(recs)
        print(f"      {'BASELINE':<14}{cell(buo, buo + bdo)}")
        for kv in keys:
            uo, do = lquad([r for r in recs if keyfn(r) == kv])
            z = two_proportion_z(uo, uo + do, buo, buo + bdo)
            tag = "   <- no work" if abs(z) < 1.96 else ""
            print(f"      {str(kv):<14}{cell(uo, uo + do)}   z={z:+5.2f}{tag}")

        print(f"\n    distance control (median ATR to the level), by {name}:")
        for kv in keys:
            sub = [r for r in recs if keyfn(r) == kv and r.lvl_up_dist is not None]
            if not sub:
                continue
            du = sorted(r.lvl_up_dist for r in sub)
            dd = sorted(r.lvl_dn_dist for r in sub)
            print(f"      {str(kv):<14}up {du[len(du)//2]:.3f} ATR   "
                  f"down {dd[len(dd)//2]:.3f} ATR   n={len(sub)}")

    # ---------------------------------------------------------------- SECTION 4
    sec("4.  TIMEWARP — does daily ribbon + hourly ribbon beat either alone?")
    print("\n  Alignment check: `ribbon_spec.timewarp(hourly, daily, lag=1)` gives")
    print("  every hourly bar of day D the daily ribbon as of the close of D-1.")
    tw_i = indicators.timewarp(h, d)
    tw_s = R.timewarp(h, d, lag=1)
    both = [(a, b) for a, b in zip(tw_i, tw_s) if a is not None and b is not None]
    same = sum(1 for a, b in both
               if (a.fast > a.slow) == (b.e8 >= b.e21))
    print(f"  parity with `indicators.timewarp`: fast/slow ordering agrees on "
          f"{same}/{len(both)} bars ({100*same/max(1,len(both)):.2f}%)")

    OUT4 = [("y_uponly3", f"up-only, next {NEXT_N} bars"),
            ("y_up_rest", f"touches +{BARRIER} ATR rest of session")]
    for attr, label in OUT4:
        bk, bn = rate_of(recs, attr)
        print(f"\n  outcome: {label}")
        print(f"  {'BASELINE (all bars)':<30}{cell(bk, bn)}")
        # marginals
        for s in STATES:
            k, m = rate_of([r for r in recs if r.state == s], attr)
            print(zline(f"hourly={s}", k, m, bk, bn))
        for s in STATES:
            k, m = rate_of([r for r in recs if r.d_state == s], attr)
            print(zline(f"daily={s}", k, m, bk, bn))
        print("  --- conjunctions ---")
        for ds in STATES:
            for hs in STATES:
                sub = [r for r in recs if r.d_state == ds and r.state == hs]
                k, m = rate_of(sub, attr)
                print(zline(f"daily={ds[:9]} & hourly={hs[:9]}", k, m, bk, bn, 34))
        # does the conjunction beat the better single?
        kh, nh = rate_of([r for r in recs if r.state == "full_bull"], attr)
        kd, nd = rate_of([r for r in recs if r.d_state == "full_bull"], attr)
        kb, nb2 = rate_of([r for r in recs
                           if r.state == "full_bull" and r.d_state == "full_bull"],
                          attr)
        print(f"  incremental test: bull&bull vs hourly-bull-alone   "
              f"z={two_proportion_z(kb, nb2, kh, nh):+5.2f}")
        print(f"  incremental test: bull&bull vs daily-bull-alone    "
              f"z={two_proportion_z(kb, nb2, kd, nd):+5.2f}")

    # ---------------------------------------------------------------- SECTION 5
    sec("5.  PULLBACK-INTO-RIBBON AND RECLAIM — the candidate entry signal")
    print("\n  Four pre-registered event definitions (no thresholds searched):")
    print("    reclaim_up   zone above -> inside (any length) -> above")
    print("    reclaim_up & state==full_bull   (the same, trend-filtered)")
    print("    hold_pivot   bar's low tags the 21 EMA and it closes above it")
    print("                 ('holding H21' in Saty's own words)")
    print("    reclaim_dn / lose_pivot  the bearish mirrors")
    print("\n  Baselines: (B0) all bars, (B1) all bars with zone==above — the")
    print("  second is the one that matters: does the RECLAIM add anything over")
    print("  simply being above the ribbon?")

    above = [r for r in recs if r.zone == "above"]
    below = [r for r in recs if r.zone == "below"]

    for attr, label in (("y_up3", f"touches +{BARRIER} ATR next {NEXT_N} bars"),
                        ("y_uponly3", f"up-only next {NEXT_N} bars"),
                        ("y_up_rest", f"touches +{BARRIER} ATR rest of session"),
                        ("y_lvl_up", "touches next named level ABOVE (rest)")):
        b0k, b0n = rate_of(recs, attr)
        b1k, b1n = rate_of(above, attr)
        print(f"\n  outcome: {label}")
        print(f"  {'B0 all bars':<30}{cell(b0k, b0n)}")
        print(f"  {'B1 zone==above':<30}{cell(b1k, b1n)}")
        for nm, sel in (("reclaim_up", lambda r: r.reclaim_up),
                        ("reclaim_up & full_bull", lambda r: r.reclaim_up_bull),
                        ("hold_pivot (holding H21)", lambda r: r.hold_pivot)):
            sub = [r for r in recs if sel(r)]
            k, m = rate_of(sub, attr)
            txt = cell(k, m)
            z0 = two_proportion_z(k, m, b0k, b0n) if m else 0.0
            z1 = two_proportion_z(k, m, b1k, b1n) if m else 0.0
            tag = "" if max(abs(z0), abs(z1)) >= 1.96 else "   <- no work"
            print(f"  {nm:<30}{txt}   z_vs_B0={z0:+5.2f}  z_vs_B1={z1:+5.2f}{tag}")

    for attr, label in (("y_dn3", f"touches -{BARRIER} ATR next {NEXT_N} bars"),
                        ("y_lvl_dn", "touches next named level BELOW (rest)")):
        b0k, b0n = rate_of(recs, attr)
        b1k, b1n = rate_of(below, attr)
        print(f"\n  outcome: {label}")
        print(f"  {'B0 all bars':<30}{cell(b0k, b0n)}")
        print(f"  {'B1 zone==below':<30}{cell(b1k, b1n)}")
        for nm, sel in (("reclaim_dn", lambda r: r.reclaim_dn),
                        ("lose_pivot (losing H21)", lambda r: r.lose_pivot)):
            sub = [r for r in recs if sel(r)]
            k, m = rate_of(sub, attr)
            txt = cell(k, m)
            z0 = two_proportion_z(k, m, b0k, b0n) if m else 0.0
            z1 = two_proportion_z(k, m, b1k, b1n) if m else 0.0
            tag = "" if max(abs(z0), abs(z1)) >= 1.96 else "   <- no work"
            print(f"  {nm:<30}{txt}   z_vs_B0={z0:+5.2f}  z_vs_B1={z1:+5.2f}{tag}")

    print("\n  --- setup DIRECTION vs VOLATILITY decomposition (next %d bars) ---"
          % NEXT_N)
    print("  A continuation ENTRY has to move the last column.  If it only moves")
    print("  `both`/`neither`, it is a volatility filter wearing a setup's name.")
    print(f"  {'':<24}{'up-only':>9}{'down-only':>10}{'both':>8}{'neither':>9}"
          f"{'  P(up | exactly one side)':>28}")
    buo, bdo, bbo, bne = quad(recs)
    btot = buo + bdo + bbo + bne
    print(f"  {'B0 all bars':<24}{100*buo/btot:8.1f}%{100*bdo/btot:9.1f}%"
          f"{100*bbo/btot:7.1f}%{100*bne/btot:8.1f}%      {cell(buo, buo+bdo)}")
    for nm, sel in (("B1 zone==above", lambda r: r.zone == "above"),
                    ("reclaim_up", lambda r: r.reclaim_up),
                    ("reclaim_up & full_bull", lambda r: r.reclaim_up_bull),
                    ("hold_pivot (H21 hold)", lambda r: r.hold_pivot),
                    ("B1' zone==below", lambda r: r.zone == "below"),
                    ("reclaim_dn", lambda r: r.reclaim_dn),
                    ("lose_pivot (H21 lost)", lambda r: r.lose_pivot)):
        sub = [r for r in recs if sel(r)]
        uo, do, bo, ne = quad(sub)
        tot = max(1, uo + do + bo + ne)
        z = two_proportion_z(uo, uo + do, buo, buo + bdo)
        tag = "  <- no work" if abs(z) < 1.96 else ""
        print(f"  {nm:<24}{100*uo/tot:8.1f}%{100*do/tot:9.1f}%"
              f"{100*bo/tot:7.1f}%{100*ne/tot:8.1f}%      {cell(uo, uo+do)}"
              f"  z={z:+5.2f}{tag}")

    print("\n  day-block bootstrap for the reclaim setups (vs all-bars baseline):")
    for nm, sel, attr in (("reclaim_up", lambda r: r.reclaim_up, "y_uponly3"),
                          ("reclaim_up&bull", lambda r: r.reclaim_up_bull, "y_uponly3"),
                          ("hold_pivot", lambda r: r.hold_pivot, "y_uponly3"),
                          ("reclaim_up", lambda r: r.reclaim_up, "y_up_rest"),
                          ("hold_pivot", lambda r: r.hold_pivot, "y_up_rest")):
        pool = [r for r in recs if getattr(r, attr) is not None]
        print(boot_line(f"{nm} [{attr}]", pool, sel,
                        lambda r, a=attr: getattr(r, a)))

    # ---- is the pivot EMA a LEVEL, or would any line do? ----------------
    print("\n5b. IS THE 21 EMA A REAL LEVEL?  Placebo test.")
    print("  Saty's third documented use of the ribbon is as dynamic support /")
    print("  resistance ('holding H21').  If the 21 EMA has that property, bars")
    print("  that straddle it should close on the trend side MORE often than")
    print("  bars straddling a PLACEBO line built the same way but stale — the")
    print("  same EMA21 series lagged by 21 bars.  Same construction, same")
    print("  neighbourhood, no claim to being 'the pivot'.")
    fh = R.frames([b for b in h])
    lag = 21
    real_k = real_n = plac_k = plac_n = 0
    for i, f in enumerate(fh):
        if f is None:
            continue
        if f.low <= f.e21 <= f.high:
            real_n += 1
            real_k += int(f.close > f.e21)
        g = fh[i - lag] if i - lag >= 0 else None
        if g is not None and f.low <= g.e21 <= f.high:
            plac_n += 1
            plac_k += int(f.close > g.e21)
    print(f"\n  {'bar straddles the real H21':<38}P(close above) {cell(real_k, real_n)}")
    print(f"  {'bar straddles the stale (lag 21) H21':<38}P(close above) "
          f"{cell(plac_k, plac_n)}")
    print(f"  two-proportion z (real vs placebo): "
          f"{two_proportion_z(real_k, real_n, plac_k, plac_n):+5.2f}"
          + ("" if abs(two_proportion_z(real_k, real_n, plac_k, plac_n)) >= 1.96
             else "    <- the real pivot does no more work than a stale line"))

    # event counts + dip length
    print("\n  event counts:")
    for nm, sel in (("reclaim_up", lambda r: r.reclaim_up),
                    ("reclaim_up & full_bull", lambda r: r.reclaim_up_bull),
                    ("reclaim_dn", lambda r: r.reclaim_dn),
                    ("hold_pivot", lambda r: r.hold_pivot),
                    ("lose_pivot", lambda r: r.lose_pivot)):
        c = sum(1 for r in recs if sel(r))
        print(f"    {nm:<26}{c:5d}   {c/len({r.day for r in recs}):.3f}/session")

    # ---------------------------------------------------------------- SECTION 6
    sec("6.  DAILY RIBBON (20 years) — day-level outcomes")
    print("\n  Conditioner: the daily ribbon as of the close of day D-1.")
    print("  Outcome: what day D does against its own level map (anchor = D-1")
    print("  close, ATR = D-1 Wilder ATR14).  GG completion here is the")
    print("  monotone-high definition: P(high >= +0.618 | high >= +0.382).")
    print("  That needs no intraday path, so daily bars are legitimate for it.")

    fd = R.frames(d)
    lvd = levels.build(d)
    rows: list[dict] = []
    for i in range(1, len(d)):
        f = fd[i - 1]
        if f is None or d[i].day not in lvd:
            continue
        dl = lvd[d[i].day]
        b = d[i]
        rows.append({
            "state": f.state, "zone": f.price_zone, "day": b.day,
            "bull_trig": b.high >= dl.at(0.382),
            "bull_comp": b.high >= dl.at(0.618),
            "bear_trig": b.low <= dl.at(-0.382),
            "bear_comp": b.low <= dl.at(-0.618),
            "up1": b.high >= dl.at(1.0),
            "dn1": b.low <= dl.at(-1.0),
        })
    print(f"\n  daily rows: {len(rows)}   {rows[0]['day']} .. {rows[-1]['day']}")
    cs = Counter(r["state"] for r in rows)
    cz = Counter(r["zone"] for r in rows)
    print("  daily state occupancy: " +
          "  ".join(f"{s} {100*cs[s]/len(rows):.1f}%" for s in STATES))
    print("  daily zone  occupancy: " +
          "  ".join(f"{z} {100*cz[z]/len(rows):.1f}%" for z in ZONES))

    def drate(sub: list[dict], key: str, cond: str | None = None) -> tuple[int, int]:
        if cond:
            sub = [r for r in sub if r[cond]]
        return sum(1 for r in sub if r[key]), len(sub)

    DOUT = [("bull_trig", None, "bullish GG trigger (high >= +0.382 ATR)"),
            ("bull_comp", "bull_trig", "bullish GG COMPLETION | triggered"),
            ("bear_trig", None, "bearish GG trigger (low <= -0.382 ATR)"),
            ("bear_comp", "bear_trig", "bearish GG COMPLETION | triggered"),
            ("up1", None, "touches +1 ATR"),
            ("dn1", None, "touches -1 ATR")]

    for keyname, keyfn, keys in (("state", lambda r: r["state"], STATES),
                                 ("zone", lambda r: r["zone"], ZONES)):
        print(f"\n  --- conditioned on prior-day daily ribbon `{keyname}` ---")
        for key, cond, label in DOUT:
            bk, bn = drate(rows, key, cond)
            print(f"\n    outcome: {label}")
            print(f"    {'BASELINE (all days)':<30}{cell(bk, bn)}")
            for kv in keys:
                sub = [r for r in rows if keyfn(r) == kv]
                k, m = drate(sub, key, cond)
                print("  " + zline(str(kv), k, m, bk, bn))

    print("\n  --- daily DIRECTION vs VOLATILITY decomposition ---")
    print("  Same logic as 2e: a day that triggers BOTH GG sides, or neither,")
    print("  carries no direction.  Only the one-sided days do.")
    print(f"  {'':<14}{'up-only':>9}{'down-only':>10}{'both':>8}{'neither':>9}"
          f"{'  P(up | exactly one side)':>28}")

    def dquad(sub: list[dict]) -> tuple[int, int, int, int]:
        uo = do = bo = ne = 0
        for r in sub:
            if r["bull_trig"] and not r["bear_trig"]:
                uo += 1
            elif r["bear_trig"] and not r["bull_trig"]:
                do += 1
            elif r["bull_trig"] and r["bear_trig"]:
                bo += 1
            else:
                ne += 1
        return uo, do, bo, ne

    buo, bdo, bbo, bne = dquad(rows)
    btot = buo + bdo + bbo + bne
    print(f"  {'ALL DAYS':<14}{100*buo/btot:8.1f}%{100*bdo/btot:9.1f}%"
          f"{100*bbo/btot:7.1f}%{100*bne/btot:8.1f}%      {cell(buo, buo+bdo)}")
    for lbl, sel in ([(s, lambda r, s=s: r["state"] == s) for s in STATES]
                     + [(z, lambda r, z=z: r["zone"] == z) for z in ZONES]):
        sub = [r for r in rows if sel(r)]
        uo, do, bo, ne = dquad(sub)
        tot = max(1, uo + do + bo + ne)
        z = two_proportion_z(uo, uo + do, buo, buo + bdo)
        tag = "  <- no work" if abs(z) < 1.96 else ""
        print(f"  {lbl:<14}{100*uo/tot:8.1f}%{100*do/tot:9.1f}%"
              f"{100*bo/tot:7.1f}%{100*ne/tot:8.1f}%      {cell(uo, uo+do)}"
              f"  z={z:+5.2f}{tag}")

    print("\n  moving-block bootstrap (block=21 trading days) on the two outcomes")
    print("  that a trader would actually act on:")
    for key, cond, label in (("bull_comp", "bull_trig", "bull GG completion|trig"),
                             ("up1", None, "touches +1 ATR")):
        for s in STATES:
            seq = []
            for r in rows:
                use = (not cond) or r[cond]
                inc = int(use and r[key])
                seq.append((inc if r["state"] == s else 0,
                            int(use) if r["state"] == s else 0,
                            inc, int(use)))
            lo, hi = moving_block_bootstrap_diff(seq)
            straddle = "  STRADDLES 0" if lo <= 0 <= hi else ""
            print(f"    {label:<26}{s:<12}[{100*lo:+5.1f}, {100*hi:+5.1f}] pp"
                  f"{straddle}")

    # ---------------------------------------------------------------- SECTION 7
    sec("7.  5-MINUTE CROSS-CHECK — the only place a first-touch race is legal")
    print("\n  60 days only.  n is small and is stated on every line.  The point")
    print("  is the ORDER of the two touches, which an hourly bar cannot resolve")
    print("  (one hourly bar's range routinely spans both barriers).")
    f5 = data.fine()
    b10 = R.resample(f5, 2)
    fs10 = R.frames(b10)
    lv5 = levels.build(d)
    s5 = data.group_by_day(f5)

    races: dict[str, list[int]] = defaultdict(list)   # state -> outcomes
    setup_races: dict[str, list[int]] = defaultdict(list)
    zones10 = [f.price_zone if f else None for f in fs10]
    for j, b in enumerate(b10):
        f = fs10[j]
        if f is None or b.day not in lv5:
            continue
        # a 10m bar is stamped with the open of its first 5m bar, so it CLOSES
        # 10 minutes later; only 5m bars starting at or after that are forward.
        end = b.dt
        rest = [x for x in s5[b.day]
                if (x.dt - end).total_seconds() >= 600]
        if len(rest) < 2:
            continue
        atr = lv5[b.day].atr
        U, L = b.close + BARRIER * atr, b.close - BARRIER * atr
        out = 0
        for x in rest:
            hit_u, hit_d = x.high >= U, x.low <= L
            if hit_u and hit_d:
                out = 3       # ambiguous even at 5m
                break
            if hit_u:
                out = 1
                break
            if hit_d:
                out = 2
                break
        races[f.state].append(out)
        races["ALL"].append(out)
        races[f.price_zone].append(out)
        if (j >= 2 and zones10[j] == "above" and zones10[j - 1] == "inside"):
            k = j - 1
            while k >= 0 and zones10[k] == "inside":
                k -= 1
            if k >= 0 and zones10[k] == "above":
                setup_races["reclaim_up(10m)"].append(out)
        if R.holding_pivot(f):
            setup_races["hold_pivot(10m)"].append(out)

    print(f"\n  10m bars: {len(b10)}   sessions: {len({b.day for b in b10})}")
    print("  first barrier touched (rest of session, 5m resolution):")
    base = races["ALL"]
    bk = sum(1 for o in base if o == 1)
    bn2 = sum(1 for o in base if o in (1, 2))
    print(f"    {'ALL 10m bars':<24}P(up first | resolved) {cell(bk, bn2)}"
          f"   unresolved-or-ambiguous {sum(1 for o in base if o in (0,3))}")
    for k2 in list(STATES) + list(ZONES) + sorted(setup_races):
        seq = races.get(k2) or setup_races.get(k2) or []
        if not seq:
            continue
        kk = sum(1 for o in seq if o == 1)
        nn = sum(1 for o in seq if o in (1, 2))
        z = two_proportion_z(kk, nn, bk, bn2) if nn else 0.0
        tag = "" if abs(z) >= 1.96 else "   <- no work"
        print(f"    {k2:<24}P(up first | resolved) {cell(kk, nn)}"
              f"   z={z:+5.2f}{tag}")

    # ---------------------------------------------------------------- FAMILY
    sec("8.  FAMILY SIZE")
    print(f"\n  Rate cells computed and printed by this program: {_CELLS}")
    print(f"  Expected |z|>1.96 by chance alone at this family size: "
          f"{0.05*_CELLS:.0f}")
    print(f"  Bonferroni |z| threshold for family-wise alpha=0.05: "
          f"{_bonf_z(_CELLS):.2f}")
    print("\n  Nothing above was selected.  Every table is an exhaustive cross-tab")
    print("  fixed before the data was read; no threshold, distance, horizon or")
    print("  lookback was tuned.  The family size is stated so that a reader can")
    print("  discount any single cell accordingly.")


def _bonf_z(m: int, alpha: float = 0.05) -> float:
    """Two-sided Bonferroni z threshold, via a bisection on the normal tail."""
    import math
    target = alpha / max(1, m) / 2.0

    def tail(z: float) -> float:
        return 0.5 * math.erfc(z / math.sqrt(2.0))
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if tail(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    main()
