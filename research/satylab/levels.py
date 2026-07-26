"""Saty ATR levels — the named price map every study measures against.

Construction (matches the Pine engine's `ta.atr(14)[1]` / `close[1]` on the
daily timeframe, and reproduces the on-chart Saty ATR Levels values):

    anchor = previous daily close
    atr    = Wilder ATR(14) as of the previous daily close
    level(r) = anchor + r * atr

Only prior-session information enters a day's map, so the whole ladder is
fixed before the opening bell — no lookahead anywhere downstream.

Named ratios follow Saty's own vocabulary:
    0.236  call/put trigger      0.382  golden-gate entrance
    0.500  midrange              0.618  golden-gate completion
    0.786  pre-extension         1.000  full ATR range
    >1.0   extensions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .data import Bar

ATR_LEN = 14

# ── Instrument caveat, measured 2026-07-26 ────────────────────────────────
# The official Saty ATR Levels indicator reads its symbol with
# `ticker.new(prefix, ticker, session=session.extended)`, so on a nearly-24h
# instrument the daily bar spans ~23h and its true range is wider than the
# 6.5h cash session.  Checked against two live readings of the indicator on
# CAPITALCOM:SPX500 (the user's actual chart):
#
#     map day     official anchor / ATR      ^GSPC ATR    ratio
#     2026-07-23  7503.90 / 84.81            77.61        0.9150
#     2026-07-24  7417.50 / 88.51            80.84        0.9134
#
# So ^GSPC understates the traded instrument's ATR by about 8.6%, and the
# ratio is stable to 0.16% across the two samples.  Every level built from
# ^GSPC therefore sits ~9% closer to the anchor than the one the user sees.
# Two readings do not certify a constant; treat this as a caveat to state,
# not a correction to silently apply.  Pine is unaffected — it reads the
# chart's own symbol and reproduces the official construction exactly.
SPX_CASH_TO_CFD_ATR = 1.094   # ^GSPC ATR * this ~= CAPITALCOM:SPX500 ATR

TRIGGER = 0.236
GG_ENTRY = 0.382
MIDRANGE = 0.500
GG_COMPLETE = 0.618
PRE_EXT = 0.786
FULL_ATR = 1.000

RATIOS: tuple[float, ...] = (
    -1.618, -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236,
    0.0,
    0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618,
)

RATIO_NAMES: dict[float, str] = {
    0.0: "PDC(锚)",
    0.236: "call trigger", -0.236: "put trigger",
    0.382: "GG入口", -0.382: "GG入口(空)",
    0.5: "midrange", -0.5: "midrange(空)",
    0.618: "GG完成", -0.618: "GG完成(空)",
    0.786: "0.786", -0.786: "0.786(空)",
    1.0: "+1 ATR", -1.0: "-1 ATR",
    1.272: "+1.272 ext", -1.272: "-1.272 ext",
    1.618: "+1.618 ext", -1.618: "-1.618 ext",
}


def wilder_atr(daily: list[Bar], length: int = ATR_LEN) -> list[float | None]:
    """atr[i] is the ATR value as of bar i's close (Wilder smoothing)."""
    trs: list[float] = []
    for i, b in enumerate(daily):
        if i == 0:
            trs.append(b.high - b.low)
        else:
            pc = daily[i - 1].close
            trs.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    atr: list[float | None] = [None] * len(daily)
    if len(daily) < length:
        return atr
    prev = sum(trs[:length]) / length
    atr[length - 1] = prev
    for i in range(length, len(daily)):
        prev = (prev * (length - 1) + trs[i]) / length
        atr[i] = prev
    return atr


@dataclass(frozen=True, slots=True)
class DayLevels:
    day: date
    anchor: float
    atr: float
    prev_high: float
    prev_low: float

    def at(self, ratio: float) -> float:
        return self.anchor + ratio * self.atr

    def ratio_of(self, price: float) -> float:
        """Where a price sits on the ladder, in ATR units from the anchor."""
        return (price - self.anchor) / self.atr

    def named(self) -> dict[str, float]:
        return {RATIO_NAMES.get(r, f"{r:+.3f}"): self.at(r) for r in RATIOS}


def build(daily: list[Bar]) -> dict[date, DayLevels]:
    """day -> level map, built only from the prior session."""
    atr = wilder_atr(daily)
    out: dict[date, DayLevels] = {}
    for i in range(1, len(daily)):
        prev, prev_atr = daily[i - 1], atr[i - 1]
        if prev_atr is None or prev_atr <= 0:
            continue
        out[daily[i].day] = DayLevels(daily[i].day, prev.close, prev_atr,
                                      prev.high, prev.low)
    return out


def first_touch(session: list[Bar], price: float, side: int,
                start: int = 0) -> int | None:
    """Index of the first bar reaching `price` (side=+1 above, -1 below)."""
    for i in range(start, len(session)):
        b = session[i]
        if (b.high >= price) if side > 0 else (b.low <= price):
            return i
    return None


def touched(session: list[Bar], price: float, side: int,
            start: int = 0) -> bool:
    return first_touch(session, price, side, start) is not None
