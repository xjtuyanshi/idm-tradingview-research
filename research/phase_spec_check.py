"""Numerical audit of the Saty Phase Oscillator spec.

Answers the only question that matters after pinning a formula off a webpage:
does the ported number behave like the thing on the chart?

Checks run
  1. the `above_pivot ? ... : ...` branch in the compression code is a no-op
  2. quantile profile of the corrected oscillator on 1d / 1h / 5m
  3. same profile for the OLD guess in satylab.indicators, to size the error
  4. zone occupancy with Wilson intervals (satylab.stats.fmt_rate)
  5. compression duty cycle, plus a biased-vs-unbiased stdev sensitivity
  6. how often the corrected reading is "extreme" (|osc| >= 100) by session hour

No parameter is searched anywhere in this file.  Every number printed is a
descriptive statistic of a fully pinned formula.

    cd <repo> && .venv/bin/python research/phase_spec_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from satylab import data, indicators, stats                      # noqa: E402
from satylab import phase_fix as pf                              # noqa: E402

QS = (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100)


def quantiles(xs: list[float]) -> dict[int, float]:
    s = sorted(xs)
    out = {}
    for q in QS:
        if not s:
            out[q] = float("nan")
            continue
        i = min(len(s) - 1, max(0, int(round(q / 100 * (len(s) - 1)))))
        out[q] = s[i]
    return out


def qline(tag: str, xs: list[float]) -> str:
    q = quantiles(xs)
    cells = "".join(f"{q[k]:>9.1f}" for k in QS)
    return f"  {tag:<26}n={len(xs):<6}{cells}"


def qhead() -> str:
    cells = "".join(f"{('p'+str(k)):>9}" for k in QS)
    return f"  {'series':<26}{'':<8}{cells}"


def zone_table(title: str, osc: list[float | None]) -> str:
    t = stats.RateTable(title)
    vals = [v for v in osc if v is not None]
    for v in vals:
        z = pf.phase_zone(v)
        for name in pf.ZONE_ORDER:
            t.add(name, z == name)
    return t.render(order=list(pf.ZONE_ORDER))


def run(name: str, bars: list) -> None:
    print("=" * 100)
    print(f"{name}   bars={len(bars)}   {bars[0].day} -> {bars[-1].day}")
    print("=" * 100)

    fixed = pf.phase_oscillator(bars)
    raw = pf.phase_raw(bars)
    old = indicators.phase_oscillator(bars)

    fv = [v for v in fixed if v is not None]
    rv = [v for v in raw if v is not None]
    ov = [v for v in old if v is not None]

    print("\n[2/3] quantile profile (oscillator units; rails at +/-23.6/61.8/100)")
    print(qhead())
    print(qline("FIXED  ema3((c-e21)/3atr)", fv))
    print(qline("  raw (unsmoothed)", rv))
    print(qline("OLD guess (c-e21)/atr", ov))

    def outside(xs: list[float], lim: float) -> tuple[int, int]:
        return sum(1 for v in xs if abs(v) >= lim), len(xs)

    print("\n  share of bars outside each rail")
    for lim in (23.6, 61.8, 100.0):
        kf, nf = outside(fv, lim)
        ko, no = outside(ov, lim)
        z = stats.two_proportion_z(kf, nf, ko, no)
        print(f"    |osc| >= {lim:5.1f}   FIXED {stats.fmt_rate(kf, nf)}"
              f"   |   OLD {stats.fmt_rate(ko, no)}   z={z:+7.1f}")

    print("\n[4] zone occupancy, corrected implementation")
    print(zone_table(f"{name} — Saty phase zones", fixed))

    print("\n[5] compression duty cycle")
    comp = pf.compression_tracker(bars, biased_stdev=True)
    cb = [c for c in comp if c is not None]
    k1, n1 = sum(cb), len(cb)
    comp_u = pf.compression_tracker(bars, biased_stdev=False)
    cu = [c for c in comp_u if c is not None]
    k2, n2 = sum(cu), len(cu)
    print(f"    Pine default (population stdev)  {stats.fmt_rate(k1, n1)}")
    print(f"    sample stdev (n-1) variant       {stats.fmt_rate(k2, n2)}")
    print(f"    two-proportion z between them    {stats.two_proportion_z(k1, n1, k2, n2):+.2f}"
          "   (sensitivity of the flag to the stdev convention)")

    runs, cur = [], 0
    for c in comp:
        if c:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    if runs:
        srt = sorted(runs)
        print(f"    compression episodes: {len(runs)}  "
              f"median length {srt[len(srt)//2]} bars, max {srt[-1]} bars")

    xs = pf.crossovers(fixed)
    counts = {n: sum(1 for e in xs if n in e) for n in pf.CROSS_NAMES}
    print("\n  yellow-light crossover dots (counts over the whole window)")
    for k, v in counts.items():
        print(f"    {k:<24}{v}")


def by_hour(bars: list) -> None:
    print("=" * 100)
    print("[6] hourly: how often is the corrected reading 'extreme' (|osc| >= 100), by ET bar")
    print("=" * 100)
    osc = pf.phase_oscillator(bars)
    comp = pf.compression_tracker(bars)
    t_ext = stats.RateTable("extreme rate by bar open (1h, RTH)")
    t_cmp = stats.RateTable("compression rate by bar open (1h, RTH)")
    for b, v, c in zip(bars, osc, comp):
        if v is None:
            continue
        t_ext.add(b.hhmm, pf.is_extreme(v))
        if c is not None:
            t_cmp.add(b.hhmm, c)
    order = sorted(t_ext.cells)
    print(t_ext.render(order=order))
    print()
    print(t_cmp.render(order=order))
    print("\n  NOTE: 7 cells per table, inspected as a full sweep, not picked. "
          "No claim is attached to any single cell.")


def primitive_parity(bars: list) -> None:
    """phase_fix's Pine primitives must agree with the already-vetted ones in
    satylab.indicators, so this port inherits their parity evidence."""
    closes = [b.close for b in bars]
    a = pf.ta_ema(closes, 21)
    b = indicators.ema(closes, 21)
    de = max((abs(x - y) for x, y in zip(a, b) if x is not None and y is not None),
             default=0.0)
    a2 = pf.ta_atr(bars, 14)
    b2 = indicators.atr_series(bars, 14)
    da = max((abs(x - y) for x, y in zip(a2, b2) if x is not None and y is not None),
             default=0.0)
    n_a = sum(1 for x in a if x is None)
    n_b = sum(1 for x in b if x is None)
    print(f"    ema21 max abs diff vs indicators.ema        {de:.3e}"
          f"   (warm-up Nones: {n_a} vs {n_b})")
    print(f"    atr14 max abs diff vs indicators.atr_series {da:.3e}")


def pins(bars: list, label: str, k: int = 8) -> None:
    """Hand-checkable rows: load the official Pine on the same symbol/timeframe
    and these numbers must match to rounding."""
    closes = [b.close for b in bars]
    piv = pf.ta_ema(closes, pf.PIVOT_LEN)
    atr = pf.ta_atr(bars, pf.ATR_LEN)
    sd = pf.ta_stdev(closes, pf.STDEV_LEN)
    osc = pf.phase_oscillator(bars)
    comp = pf.compression_tracker(bars)
    print(f"\n  {label}")
    print(f"    {'bar':<17}{'close':>10}{'ema21':>10}{'atr14':>9}"
          f"{'stdev21':>9}{'osc':>9}  {'zone':<14}compressed")
    for i in range(len(bars) - k, len(bars)):
        b = bars[i]
        stamp = b.dt.strftime("%Y-%m-%d %H:%M")
        print(f"    {stamp:<17}{b.close:>10.2f}{piv[i]:>10.2f}{atr[i]:>9.2f}"
              f"{sd[i]:>9.2f}{osc[i]:>9.2f}  {pf.phase_zone(osc[i]):<14}"
              f"{comp[i]}")


def main() -> None:
    d = data.daily(years="20y")
    h = data.hourly()
    f = data.fine()

    print("[0] primitive parity with the already-vetted satylab helpers")
    primitive_parity(d)
    print()

    print("[1] compression branch equivalence (above_pivot ternary is a no-op)")
    for nm, bars in (("daily", d), ("hourly", h), ("5m", f)):
        r = pf.verify_compression_branches(bars)
        print(f"    {nm:<8} checked={r['checked']:<6} mismatches={r['mismatch']}")
    print()

    run("DAILY  ^GSPC 20y", d)
    print()
    run("HOURLY ^GSPC 730d (RTH, 7 bars/session)", h)
    print()
    run("5-MIN  ^GSPC 60d  (short window — descriptive only)", f)
    print()
    by_hour(h)

    print()
    print("=" * 100)
    print("[7] hand-checkable pins — put the official Pine on the same symbol/TF "
          "and compare")
    print("=" * 100)
    pins(d, "^GSPC daily (should match SP:SPX 1D closely)")
    pins(h, "^GSPC 1h RTH (bar boundaries may differ slightly from TradingView)")


if __name__ == "__main__":
    main()
