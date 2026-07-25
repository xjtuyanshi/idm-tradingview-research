"""How much does the Pivot Ribbon change when computed on ETH vs RTH bars?

Saty's published chart templates are annotated "(ETH)", and his own trade notes
say things like "the H21 (RTH)" -- i.e. the session used to build the EMAs is a
first-class parameter in his language, not a detail.  Our `satylab.data` layer
loads RTH-only bars.  This script measures what that costs.

SPY is used because ^GSPC (the index) has no extended session at all -- the
index is only computed 09:30-16:00 ET, so for SPX charts RTH is the only option
and this question is moot.  It is NOT moot for SPY / ES / any ETH-enabled proxy,
which is what Saty is usually looking at.

Network: one Yahoo chart request per session mode (30d of 5m bars).  Nothing is
written to the shared satylab cache.

    .venv/bin/python research/ribbon_session_probe.py
"""

from __future__ import annotations

import json
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from satylab.indicators import ema  # noqa: E402

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def pull(symbol: str, rng: str, interval: str, prepost: bool) -> list[tuple[datetime, float]]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range={rng}&interval={interval}"
           f"&includePrePost={'true' if prepost else 'false'}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        payload = json.load(r)
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = [(datetime.fromtimestamp(ts, ET), float(q["close"][i]))
            for i, ts in enumerate(res["timestamp"]) if q["close"][i] is not None]
    rows.sort()
    return rows


def to_10m(rows: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """Clock-aligned 10m buckets (09:30, 09:40, ...), last close wins.

    Clock alignment -- not 'every 2nd bar' -- is required: the ETH feed has gaps
    in the thin pre-market hours, so index-based chunking desynchronises the two
    series and silently compares different timestamps.
    """
    buckets: dict[datetime, float] = {}
    for dt, c in rows:
        buckets[dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)] = c
    return sorted(buckets.items())


def ribbon_state(rows: list[tuple[datetime, float]]) -> dict[datetime, tuple[str | None, float | None]]:
    closes = [c for _, c in rows]
    e8, e21, e34 = ema(closes, 8), ema(closes, 21), ema(closes, 34)
    out: dict[datetime, tuple[str | None, float | None]] = {}
    for i, (dt, _) in enumerate(rows):
        a, b, c = e8[i], e21[i], e34[i]
        if a is None or b is None or c is None:
            out[dt] = (None, None)
        else:
            s = "full_bull" if (a >= b >= c) else ("full_bear" if (a < b < c) else "folded")
            out[dt] = (s, b)
    return out


def main(symbol: str = "SPY") -> None:
    eth = to_10m(pull(symbol, "30d", "5m", True))
    rth = to_10m(pull(symbol, "30d", "5m", False))
    E, R = ribbon_state(eth), ribbon_state(rth)
    common = [dt for dt in R if dt in E]

    both = [dt for dt in common if E[dt][0] and R[dt][0]]
    early = [dt for dt in both if dt.strftime("%H:%M") <= "10:30"]
    agree = sum(1 for dt in both if E[dt][0] == R[dt][0])
    agree_e = sum(1 for dt in early if E[dt][0] == R[dt][0])

    print(f"{symbol}: ETH 10m bars {len(eth)}, RTH 10m bars {len(rth)}, "
          f"comparable stamps {len(both)}")
    print(f"10m ribbon STATE agreement ETH vs RTH : "
          f"{agree}/{len(both)} = {100 * agree / max(1, len(both)):.1f}%")
    print(f"   restricted to the first hour (<=10:30): "
          f"{agree_e}/{len(early)} = {100 * agree_e / max(1, len(early)):.1f}%")

    d = [abs(E[dt][1] - R[dt][1]) for dt in both]
    de = [abs(E[dt][1] - R[dt][1]) for dt in early]
    px = rth[-1][1]
    print(f"|ETH 21EMA - RTH 21EMA|  all day : median ${statistics.median(d):.3f} "
          f"p90 ${sorted(d)[int(0.9 * len(d))]:.3f}   ({symbol} ~${px:.0f})")
    print(f"                       first hour: median ${statistics.median(de):.3f} "
          f"p90 ${sorted(de)[int(0.9 * len(de))]:.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SPY")
