"""Geometry audit: Saty Pivot Ribbon (8/21/34) vs Ripster EMA Cloud (5/12, 34/50).

Question asked by the user: are these two the *same object* at different
parameters, and is running both redundant or complementary?

This script does not test profitability.  It measures pure geometry:

  * how often the two "trigger" clouds agree on sign, bar by bar;
  * how many flip events each produces (churn);
  * the signed lead/lag, in bars, between a Ripster 5/12 flip and the nearest
    Saty 8/21 flip;
  * the same three things for the two "structure" clouds (Saty 21/34 vs
    Ripster 34/50);
  * conditional agreement P(one | other) so that "complementary" can mean
    something checkable: a second cloud is only informative if its state
    still varies once the first one is fixed.

Path resolution uses 5m bars resampled to 10m, because 10m is the timeframe
both authors name (Ripster: "focus is on 10 min chart"; Saty: Time Warp shows
the 10m ribbon on a 3m chart).  Hourly is run as a robustness pass.

Usage:  .venv/bin/python -m research.satylab.study_ribbon_vs_cloud
        (or: python research/satylab/study_ribbon_vs_cloud.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats  # noqa: E402
from satylab.data import Bar  # noqa: E402
from satylab.indicators import ema  # noqa: E402

# EMA "center of mass" (average age of the data in the average), in bars.
# For an EMA of length N with alpha = 2/(N+1), COM = (N-1)/2.
COM = lambda n: (n - 1) / 2.0  # noqa: E731


def resample(bars: list[Bar], k: int) -> list[Bar]:
    """Group k consecutive intraday bars inside one session into one bar.

    Anchored at the session open, so 5m -> 10m gives 09:30, 09:40, ...
    Incomplete tail groups are dropped (no partial bars).
    """
    out: list[Bar] = []
    for _day, rows in sorted(data.group_by_day(bars).items()):
        for i in range(0, len(rows) - k + 1, k):
            chunk = rows[i:i + k]
            out.append(Bar(chunk[0].dt, chunk[0].day, chunk[0].open,
                           max(c.high for c in chunk),
                           min(c.low for c in chunk),
                           chunk[-1].close,
                           sum(c.volume for c in chunk)))
    return out


def cloud_sign(bars: list[Bar], fast: int, slow: int) -> list[int | None]:
    """+1 when the fast EMA is above the slow EMA (green cloud), else -1."""
    closes = [b.close for b in bars]
    ef, es = ema(closes, fast), ema(closes, slow)
    return [None if (ef[i] is None or es[i] is None)
            else (1 if ef[i] > es[i] else -1) for i in range(len(bars))]


def flips(sig: list[int | None]) -> list[int]:
    """Indices where the sign changed relative to the previous defined bar."""
    out, prev = [], None
    for i, s in enumerate(sig):
        if s is None:
            continue
        if prev is not None and s != prev:
            out.append(i)
        prev = s
    return out


def agreement(a: list[int | None], b: list[int | None]) -> tuple[int, int]:
    k = n = 0
    for x, y in zip(a, b):
        if x is None or y is None:
            continue
        n += 1
        k += int(x == y)
    return k, n


def conditional(a: list[int | None], b: list[int | None]) -> str:
    """P(b bull | a bull) and P(b bull | a bear) — the honest 'does the second
    cloud still move once the first is fixed' question."""
    kb = nb = kr = nr = 0
    for x, y in zip(a, b):
        if x is None or y is None:
            continue
        if x == 1:
            nb += 1
            kb += int(y == 1)
        else:
            nr += 1
            kr += int(y == 1)
    z = stats.two_proportion_z(kb, nb, kr, nr)
    return (f"    P(B bull | A bull) = {stats.fmt_rate(kb, nb)}\n"
            f"    P(B bull | A bear) = {stats.fmt_rate(kr, nr)}\n"
            f"    two-proportion z    = {z:+.2f}")


def lead_lag(ref: list[int], other: list[int], window: int = 12) -> str:
    """For each flip in `ref`, signed distance to the nearest flip in `other`.

    Negative = `other` flipped first (other leads).  Flips with no partner
    inside +/- `window` bars are counted as unmatched.
    """
    if not ref or not other:
        return "    (no flips)"
    deltas, unmatched = [], 0
    for i in ref:
        best = min(other, key=lambda j: abs(j - i))
        d = best - i
        if abs(d) > window:
            unmatched += 1
        else:
            deltas.append(d)
    deltas.sort()
    med = deltas[len(deltas) // 2] if deltas else float("nan")
    mean = sum(deltas) / len(deltas) if deltas else float("nan")
    lo = deltas[int(0.25 * len(deltas))] if deltas else float("nan")
    hi = deltas[int(0.75 * len(deltas))] if deltas else float("nan")
    same = sum(1 for d in deltas if d == 0)
    return (f"    matched {len(deltas)}/{len(ref)} (unmatched at +/-{window} bars: {unmatched})\n"
            f"    median delta = {med:+.1f} bars, mean = {mean:+.2f}, IQR = [{lo:+.0f}, {hi:+.0f}]\n"
            f"    exact same bar: {stats.fmt_rate(same, len(deltas))}")


def run(bars: list[Bar], label: str) -> None:
    print(f"\n{'=' * 72}\n{label}   n_bars = {len(bars)}\n{'=' * 72}")

    saty_trig = cloud_sign(bars, 8, 21)     # Saty green/red pivot cloud
    saty_struct = cloud_sign(bars, 21, 34)  # Saty aqua/orange context cloud
    rip_trig = cloud_sign(bars, 5, 12)      # Ripster fluid trendline cloud
    rip_struct = cloud_sign(bars, 34, 50)   # Ripster bias / risk cloud
    saty_conv = cloud_sign(bars, 13, 48)    # Saty Conviction Arrows pair

    named = [("Saty 8/21 (trigger)", saty_trig),
             ("Ripster 5/12 (trigger)", rip_trig),
             ("Saty 21/34 (structure)", saty_struct),
             ("Ripster 34/50 (structure)", rip_struct),
             ("Saty 13/48 (conviction)", saty_conv)]

    print("\n-- churn: flips per 1000 bars, and EMA center-of-mass separation")
    for name, sig in named:
        f = flips(sig)
        n = sum(1 for s in sig if s is not None)
        a, b = [int(x) for x in name.split()[1].split("/")]
        print(f"  {name:<28} flips={len(f):>4}  per1000={1000 * len(f) / max(n, 1):6.2f}"
              f"  COM_sep={COM(b) - COM(a):5.1f} bars")

    pairs = [("Saty 8/21", saty_trig, "Ripster 5/12", rip_trig),
             ("Saty 21/34", saty_struct, "Ripster 34/50", rip_struct),
             ("Saty 8/21", saty_trig, "Saty 21/34", saty_struct),
             ("Ripster 5/12", rip_trig, "Ripster 34/50", rip_struct),
             ("Saty 13/48", saty_conv, "Ripster 34/50", rip_struct)]

    for na, a, nb, b in pairs:
        k, n = agreement(a, b)
        print(f"\n-- A = {na}   vs   B = {nb}")
        print(f"    bar-by-bar sign agreement = {stats.fmt_rate(k, n)}")
        print(conditional(a, b))
        print("    lead/lag of B's flips relative to A's flips:")
        print(lead_lag(flips(a), flips(b)))


def main() -> None:
    spy5 = data.fine("SPY")
    run(resample(spy5, 2), "SPY 10-minute (5m x2, RTH, trailing 60 days)")
    run(spy5, "SPY 5-minute (RTH, trailing 60 days)")
    run(data.hourly("SPY"), "SPY 1-hour (RTH, trailing 730 days)")


# ---------------------------------------------------------------------------
# Appendix: is "the green band narrows, then turns red" informative, or a
# tautology?  A sign flip REQUIRES the gap to reach zero, so narrowing always
# precedes a flip.  The only non-trivial question is the converse:
#   given the band is narrow, how often does it actually complete the flip
#   inside a fixed horizon, versus the unconditional flip rate?
# Pre-registered spec: 10m SPY, bull-stacked bars, |EMA8-EMA21| below its own
# trailing 100-bar 25th percentile, horizon 6 bars (one hour).  The robustness
# grid below is printed in full -- every cell, no cherry-picking.
# ---------------------------------------------------------------------------

def narrowing_study(bars: list[Bar], fast: int, slow: int, label: str,
                    pcts=(10, 25, 40), horizons=(3, 6, 12),
                    lookback: int = 100) -> None:
    closes = [b.close for b in bars]
    ef, es = ema(closes, fast), ema(closes, slow)
    gap = [None if (ef[i] is None or es[i] is None) else abs(ef[i] - es[i])
           for i in range(len(bars))]
    sign = [None if (ef[i] is None or es[i] is None)
            else (1 if ef[i] > es[i] else -1) for i in range(len(bars))]

    def flips_within(i: int, h: int) -> bool:
        s = sign[i]
        for j in range(i + 1, min(i + 1 + h, len(sign))):
            if sign[j] is not None and sign[j] != s:
                return True
        return False

    print(f"\n{'-' * 72}\nnarrowing -> flip, {label} ({fast}/{slow}), "
          f"cells examined = {len(pcts) * len(horizons)}\n{'-' * 72}")
    for h in horizons:
        base_k = base_n = 0
        for i in range(lookback, len(bars) - h):
            if sign[i] is None:
                continue
            base_n += 1
            base_k += int(flips_within(i, h))
        print(f"  horizon {h:>2} bars  unconditional P(flip) = {stats.fmt_rate(base_k, base_n)}")
        for p in pcts:
            k = n = 0
            for i in range(lookback, len(bars) - h):
                if gap[i] is None:
                    continue
                hist = [g for g in gap[i - lookback:i] if g is not None]
                if len(hist) < lookback // 2:
                    continue
                hist.sort()
                thr = hist[int(p / 100 * len(hist))]
                if gap[i] > thr:
                    continue
                n += 1
                k += int(flips_within(i, h))
            z = stats.two_proportion_z(k, n, base_k, base_n)
            print(f"      | gap <= p{p:<2} : {stats.fmt_rate(k, n)}   z vs base = {z:+.2f}")


def main_appendix() -> None:
    spy10 = resample(data.fine("SPY"), 2)
    narrowing_study(spy10, 8, 21, "SPY 10m Saty pivot cloud")
    narrowing_study(spy10, 5, 12, "SPY 10m Ripster trigger cloud")


if __name__ == "__main__":
    main()
    main_appendix()
