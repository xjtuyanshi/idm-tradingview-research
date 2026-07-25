"""Reproducible evidence for the data-coverage table in
research/reports/SPEC_SATY_PLAYBOOK.md.

Saty's public pre-market playbook routinely conditions on levels that live
*outside* the regular session (overnight high/low, pre-market high/low,
H21 computed on the extended session).  This script simply prints what our
cached data pipeline actually contains, so the "we cannot compute X" claims
in the spec are checkable rather than asserted.

    cd "<repo>" && .venv/bin/python research/saty_playbook_data_gap_check.py

Writes nothing.  Reads only the existing satylab cache.  No parameters,
no fitting, no statistics — this is an inventory, not a study.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from satylab import data, indicators, levels  # noqa: E402


def _session_span(bars, label: str) -> None:
    times = collections.Counter(b.dt.strftime("%H:%M") for b in bars)
    keys = sorted(times)
    print(f"{label:>10}: n={len(bars):>6}  {bars[0].day} -> {bars[-1].day}")
    print(f"{'':>10}  bar times {keys[0]}..{keys[-1]}  ({len(keys)} distinct)")
    if len(keys) <= 10:
        print(f"{'':>10}  {[(k, times[k]) for k in keys]}")
    pre = [k for k in keys if k < "09:30"]
    post = [k for k in keys if k > "16:00"]
    print(f"{'':>10}  pre-09:30 buckets: {pre or 'NONE'}   post-16:00 buckets: {post or 'NONE'}")


def main() -> None:
    d = data.daily(years="20y")
    h = data.hourly()
    f = data.fine()

    print("=== session coverage (does our data contain ETH / pre-market?) ===")
    _session_span(h, "hourly")
    _session_span(f, "5m")
    print(f"{'daily':>10}: n={len(d)}  {d[0].day} -> {d[-1].day}")

    print()
    print("=== what a Saty pre-market plan references, vs what we can compute ===")
    lv = levels.build(d)
    last_day = max(lv)
    dl = lv[last_day]
    rows = [
        ("PDC / anchor",              "YES", f"{dl.anchor:.2f}"),
        ("Day-mode ATR ladder",       "YES", f"ATR={dl.atr:.2f}  0.236={dl.at(0.236):.2f}"),
        ("prior-day high / low",      "YES", f"{dl.prev_high:.2f} / {dl.prev_low:.2f}"),
        ("prior-day RTH HOD/LOD",     "YES", "= prev_high/prev_low (RTH-only feed)"),
        ("overnight high / low",      "NO",  "no ETH bars in cache"),
        ("pre-market high / low",     "NO",  "no bars before 09:30"),
        ("H21 (RTH)",                 "YES", "indicators.ribbon(hourly)"),
        ("H21 (ETH)",                 "NO",  "would need extended-session hourly"),
        ("D21 / W21",                 "YES", "indicators.ribbon(daily) / weekly resample"),
        ("13/48 conviction EMAs",     "NO",  "indicators exposes 8/21/34 only"),
        ("Weekly/Monthly ATR ladder", "NO",  "levels.build is Day mode only"),
        ("VIX key level",             "NO",  "no VIX series in data module"),
        ("sector-ETF breadth",        "NO",  "no sector data in cache"),
        ("round psychological levels","N/A", "trivial to derive, but discretionary"),
        ("daily trendline",           "NO",  "discretionary hand-drawn object"),
    ]
    print(f"{'plan input':<28} {'have?':<6} note")
    for name, have, note in rows:
        print(f"{name:<28} {have:<6} {note}")

    print()
    print("=== resolution ceiling for path-dependent questions ===")
    print("daily   : 20y  -> level-touch order WITHIN a day: unknowable")
    print("hourly  : 730d -> one bar's range usually exceeds a whole stop distance;")
    print("                  'which came first' on 1h is NOT decidable (see GG report §3)")
    print(f"5-minute: {len(set(b.day for b in f))} sessions -> the ONLY feed that can adjudicate")
    print("                  intrabar sequence.  Any path claim must be built here and")
    print("                  reported with n, which will be small.")

    print()
    ribbon_h = indicators.ribbon(h)
    labels = collections.Counter(r.label() for r in ribbon_h if r is not None)
    print("=== hourly ribbon state census (sanity check only, not a finding) ===")
    total = sum(labels.values())
    for k, v in labels.most_common():
        print(f"  {k:<12} {v:>5}  {v / total:6.1%}")


if __name__ == "__main__":
    main()
