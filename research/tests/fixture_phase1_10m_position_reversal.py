"""Synthetic, source-timed fixtures for the 10m POSITION_REVERSAL v1 lane."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from research.phase1_10m_position_reversal_oracle import (
    DEFAULT_STALE_AFTER_MS,
    BandRole,
    NamedBand,
    PriorAtrContext,
    SourceKind,
    Stability,
    TenMinuteBar,
)

NEW_YORK = ZoneInfo("America/New_York")
SESSION_DATE = (2026, 7, 31)
DAY_ATR = 98.70936228387525
LOWER_TRIGGER = 7421.204590501005
UPPER_TRIGGER = 7467.795409498995


def et_ms(
    hour: int,
    minute: int,
    *,
    year: int = SESSION_DATE[0],
    month: int = SESSION_DATE[1],
    day: int = SESSION_DATE[2],
) -> int:
    value = datetime(year, month, day, hour, minute, tzinfo=NEW_YORK)
    return int(value.timestamp() * 1000)


PUBLISHED_AT_MS = et_ms(16, 0, year=2026, month=7, day=30)
VALID_UNTIL_MS = et_ms(16, 0, year=2026, month=7, day=31)
ATR_SOURCE_OPEN_MS = et_ms(0, 0, year=2026, month=7, day=30)
ATR_SOURCE_CLOSE_MS = PUBLISHED_AT_MS


def bar(
    hour: int,
    minute: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    **overrides: object,
) -> TenMinuteBar:
    values: dict[str, object] = {
        "timestamp_ms": et_ms(hour, minute),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }
    values.update(overrides)
    return TenMinuteBar(**values)  # type: ignore[arg-type]


def support_band(**overrides: object) -> NamedBand:
    values: dict[str, object] = {
        "source_id": "SATY-ATR-LOWER-TRIGGER",
        "source_version": "v1",
        "role": BandRole.SUPPORT,
        "lower_bound": LOWER_TRIGGER,
        "upper_bound": LOWER_TRIGGER,
        "published_at_ms": PUBLISHED_AT_MS,
        "level_known_at_ms": PUBLISHED_AT_MS,
        "source_kind": SourceKind.SATY_ATR_MAP_LEVEL,
        "valid_until_ms": VALID_UNTIL_MS,
        "stability": Stability.PRIOR_PUBLISHED,
        "stale_after_ms": DEFAULT_STALE_AFTER_MS,
        "enabled": True,
    }
    values.update(overrides)
    return NamedBand(**values)  # type: ignore[arg-type]


def resistance_band(**overrides: object) -> NamedBand:
    values: dict[str, object] = {
        "source_id": "SATY-ATR-UPPER-TRIGGER",
        "source_version": "v1",
        "role": BandRole.RESISTANCE,
        "lower_bound": UPPER_TRIGGER,
        "upper_bound": UPPER_TRIGGER,
        "published_at_ms": PUBLISHED_AT_MS,
        "level_known_at_ms": PUBLISHED_AT_MS,
        "source_kind": SourceKind.SATY_ATR_MAP_LEVEL,
        "valid_until_ms": VALID_UNTIL_MS,
        "stability": Stability.PRIOR_PUBLISHED,
        "stale_after_ms": DEFAULT_STALE_AFTER_MS,
        "enabled": True,
    }
    values.update(overrides)
    return NamedBand(**values)  # type: ignore[arg-type]


def prior_atr(**overrides: object) -> PriorAtrContext:
    values: dict[str, object] = {
        "value": DAY_ATR,
        "source_id": "SATY-ATR-MAP",
        "source_version": "2026-07-31-v1",
        "published_at_ms": PUBLISHED_AT_MS,
        "known_at_ms": PUBLISHED_AT_MS,
        "source_kind": SourceKind.PREVIOUS_COMPLETED_DAILY_ATR,
        "source_timeframe": "D",
        "completed_source_open_ms": ATR_SOURCE_OPEN_MS,
        "completed_source_close_ms": ATR_SOURCE_CLOSE_MS,
        "valid_until_ms": VALID_UNTIL_MS,
        "stability": Stability.PRIOR_PUBLISHED,
        "stale_after_ms": DEFAULT_STALE_AFTER_MS,
        "enabled": True,
    }
    values.update(overrides)
    return PriorAtrContext(**values)  # type: ignore[arg-type]


def standard_bands() -> tuple[NamedBand, NamedBand]:
    return support_band(), resistance_band()


def synthetic_dual_ready_replay() -> tuple[
    tuple[TenMinuteBar, ...],
    tuple[tuple[NamedBand, ...], ...],
    tuple[PriorAtrContext, ...],
]:
    """Synthetic short/long READY chain for producer state-machine coverage."""

    bars = (
        # Synthetic short READY, visible only at 09:40 ET.
        bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1),
        # Strictly later full clear below the old resistance band.
        bar(9, 40, 7450.0, 7454.0, 7440.0, 7448.0),
        bar(9, 50, 7440.0, 7442.0, 7425.0, 7430.0),
        # Required accepted-break counterexample.
        bar(10, 0, 7430.0, 7432.0, 7412.0, 7415.5),
        bar(10, 10, 7415.5, 7418.0, 7405.0, 7409.3),
        # Reclaim still crosses the old support and cannot backfill it.
        bar(10, 20, 7410.0, 7432.0, 7408.0, 7428.1),
        # Required full clear above support; this bar cannot re-touch/rearm.
        bar(10, 30, 7428.5, 7438.0, 7424.3, 7435.8),
        bar(10, 40, 7435.8, 7440.0, 7428.0, 7436.0),
        bar(10, 50, 7436.0, 7442.0, 7430.0, 7438.0),
        bar(11, 0, 7438.0, 7441.0, 7431.0, 7439.0),
        bar(11, 10, 7439.0, 7440.0, 7429.0, 7434.0),
        bar(11, 20, 7434.0, 7438.0, 7426.0, 7431.0),
        # Synthetic long READY, visible at 11:40 ET.  This is not the accepted
        # real July 31 11:40 replay, whose producer result was SPACE_LT_1R.
        bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5),
    )
    bands = tuple(standard_bands() for _ in bars)
    atrs = tuple(prior_atr() for _ in bars)
    return bars, bands, atrs
