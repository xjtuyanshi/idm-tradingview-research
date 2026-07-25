"""Shared market-data layer for the Saty method study.

Everything downstream — level maps, ribbon states, base-rate tables — reads
bars through here so that every study in `research/satylab` is looking at the
same numbers.  Responses are cached on disk (gitignored) so a fan-out of
studies does not hammer the provider or drift between runs.

Provider limits that shape every study built on this module:

    interval   max history      bars/session (RTH)
    1d         decades          1
    1h         730 days         7   (09:30, 10:30 ... 15:30)
    30m/15m    60 days          13 / 26
    5m         60 days          78

So: long-horizon questions must be answered on 1h or 1d, and anything that
depends on intraday path order has to be cross-checked on the 60-day 5m
window and reported as such.  Do not silently mix the two.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CACHE_DIR = Path(__file__).resolve().parent / "cache"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


@dataclass(frozen=True, slots=True)
class Bar:
    dt: datetime
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def hhmm(self) -> str:
        return self.dt.strftime("%H:%M")


def _cache_path(symbol: str, rng: str, interval: str) -> Path:
    safe = symbol.replace("^", "IDX_").replace(":", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}__{rng}__{interval}.json"


def _download(symbol: str, rng: str, interval: str, tries: int = 4) -> dict:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range={rng}&interval={interval}")
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.load(r)
            if payload.get("chart", {}).get("error"):
                raise RuntimeError(payload["chart"]["error"])
            return payload
        except Exception as exc:                     # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed for {symbol} {rng} {interval}: {last}")


def load(symbol: str, rng: str, interval: str,
         refresh: bool = False) -> list[Bar]:
    """Return RTH bars, cached on disk.  Bars with null OHLC are dropped."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol, rng, interval)
    if path.exists() and not refresh:
        payload = json.loads(path.read_text())
    else:
        payload = _download(symbol, rng, interval)
        path.write_text(json.dumps(payload))

    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    vols = q.get("volume") or [0] * len(res["timestamp"])
    out: list[Bar] = []
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        dt = datetime.fromtimestamp(ts, ET)
        out.append(Bar(dt, dt.date(), float(o), float(h), float(l), float(c),
                       float(vols[i] or 0)))
    out.sort(key=lambda b: b.dt)
    return out


def group_by_day(bars: list[Bar]) -> dict[date, list[Bar]]:
    sessions: dict[date, list[Bar]] = {}
    for b in bars:
        sessions.setdefault(b.day, []).append(b)
    for rows in sessions.values():
        rows.sort(key=lambda x: x.dt)
    return sessions


# Canonical datasets every study should use, so results stay comparable.
SPX = "^GSPC"


def daily(symbol: str = SPX, years: str = "20y", **kw) -> list[Bar]:
    return load(symbol, years, "1d", **kw)


def hourly(symbol: str = SPX, **kw) -> list[Bar]:
    return load(symbol, "730d", "1h", **kw)


def fine(symbol: str = SPX, **kw) -> list[Bar]:
    """5-minute bars — only the trailing 60 days exist."""
    return load(symbol, "60d", "5m", **kw)
