"""Deterministic fixtures for the R3 10m-primary / 3m-timing contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from research.phase1_10m_primary_opportunity_oracle import (
    Direction,
    NamedLevelSource,
    OpportunityPlan,
    TenMinuteBar,
    ThreeMinuteBar,
)

NEW_YORK = ZoneInfo("America/New_York")
BASE_10M = datetime(2026, 8, 3, 9, 30, tzinfo=NEW_YORK)
BASE_3M = datetime(2026, 8, 3, 10, 12, tzinfo=NEW_YORK)


def ten_time(index: int, *, base: datetime = BASE_10M) -> int:
    return int((base + timedelta(minutes=10 * index)).timestamp() * 1000)


def three_time(index: int, *, base: datetime = BASE_3M) -> int:
    return int((base + timedelta(minutes=3 * index)).timestamp() * 1000)


def ten_bar(
    index: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    ema5: float,
    ema12: float,
    ema21: float,
    ema48: float,
    symbol: str = "CAPITALCOM:SPX500",
    timeframe_seconds: int = 600,
    confirmed: bool = True,
    standard: bool = True,
    base: datetime = BASE_10M,
) -> TenMinuteBar:
    return TenMinuteBar(
        timestamp_ms=ten_time(index, base=base),
        open=open_,
        high=high,
        low=low,
        close=close,
        ema5=ema5,
        ema12=ema12,
        ema21=ema21,
        ema48=ema48,
        symbol=symbol,
        timeframe_seconds=timeframe_seconds,
        is_confirmed=confirmed,
        is_standard=standard,
    )


def long_bar(
    index: int,
    *,
    open_: float = 104.0,
    high: float = 106.0,
    low: float = 103.0,
    close: float = 105.0,
    ema5: float = 104.0,
    ema12: float = 103.5,
    ema21: float = 103.0,
    ema48: float = 102.0,
    **kwargs: object,
) -> TenMinuteBar:
    return ten_bar(
        index,
        open_=open_,
        high=high,
        low=low,
        close=close,
        ema5=ema5,
        ema12=ema12,
        ema21=ema21,
        ema48=ema48,
        **kwargs,
    )


def short_bar(
    index: int,
    *,
    open_: float = 96.0,
    high: float = 97.0,
    low: float = 94.0,
    close: float = 95.0,
    ema5: float = 96.0,
    ema12: float = 96.5,
    ema21: float = 97.0,
    ema48: float = 98.0,
    **kwargs: object,
) -> TenMinuteBar:
    return ten_bar(
        index,
        open_=open_,
        high=high,
        low=low,
        close=close,
        ema5=ema5,
        ema12=ema12,
        ema21=ema21,
        ema48=ema48,
        **kwargs,
    )


def long_episode(
    *,
    target: float = 112.0,
    base_index: int = 0,
    confirmation_confirmed: bool = True,
    base: datetime = BASE_10M,
) -> list[TenMinuteBar]:
    """Epoch -> full departure -> first touch WATCH -> later reclaim."""

    return [
        long_bar(
            base_index,
            open_=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            ema5=100.0,
            ema12=99.8,
            ema21=99.0,
            ema48=98.0,
            base=base,
        ),
        long_bar(
            base_index + 1,
            open_=103.0,
            high=target,
            low=102.5,
            close=105.0,
            ema5=102.0,
            ema12=101.5,
            ema21=102.5,
            ema48=101.5,
            base=base,
        ),
        long_bar(
            base_index + 2,
            open_=104.5,
            high=106.0,
            low=101.8,
            close=103.0,
            ema5=104.0,
            ema12=103.0,
            ema21=103.0,
            ema48=102.0,
            base=base,
        ),
        long_bar(
            base_index + 3,
            open_=104.0,
            high=107.2,
            low=103.5,
            close=106.8,
            ema5=105.8,
            ema12=105.4,
            ema21=103.5,
            ema48=102.2,
            confirmed=confirmation_confirmed,
            base=base,
        ),
    ]


def short_episode(
    *,
    target: float = 88.0,
    base_index: int = 0,
    confirmation_confirmed: bool = True,
    base: datetime = BASE_10M,
) -> list[TenMinuteBar]:
    return [
        short_bar(
            base_index,
            open_=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            ema5=100.0,
            ema12=100.2,
            ema21=101.0,
            ema48=102.0,
            base=base,
        ),
        short_bar(
            base_index + 1,
            open_=97.0,
            high=97.5,
            low=target,
            close=95.0,
            ema5=98.0,
            ema12=98.5,
            ema21=97.5,
            ema48=98.5,
            base=base,
        ),
        short_bar(
            base_index + 2,
            open_=95.5,
            high=98.2,
            low=94.0,
            close=97.0,
            ema5=96.0,
            ema12=97.0,
            ema21=97.0,
            ema48=98.0,
            base=base,
        ),
        short_bar(
            base_index + 3,
            open_=96.0,
            high=96.5,
            low=92.8,
            close=93.2,
            ema5=94.2,
            ema12=94.6,
            ema21=96.5,
            ema48=97.8,
            confirmed=confirmation_confirmed,
            base=base,
        ),
    ]


def three_bar(
    index: int,
    *,
    open_: float = 106.0,
    high: float = 106.4,
    low: float = 105.6,
    close: float = 106.0,
    ema5: float = 106.0,
    ema12: float = 105.7,
    symbol: str = "CAPITALCOM:SPX500",
    timeframe_seconds: int = 180,
    confirmed: bool = True,
    standard: bool = True,
    base: datetime = BASE_3M,
) -> ThreeMinuteBar:
    return ThreeMinuteBar(
        timestamp_ms=three_time(index, base=base),
        open=open_,
        high=high,
        low=low,
        close=close,
        ema5=ema5,
        ema12=ema12,
        symbol=symbol,
        timeframe_seconds=timeframe_seconds,
        is_confirmed=confirmed,
        is_standard=standard,
    )


def active_long_plan(
    *,
    opportunity_id: str = "10M-TC-L-1785778200000",
    confirmation_time_ms: int = 1_785_778_200_000,
    target: float = 114.0,
) -> OpportunityPlan:
    entry = 106.8
    invalidation = 101.6
    risk = entry - invalidation
    space = target - entry
    return OpportunityPlan(
        opportunity_id=opportunity_id,
        epoch_id="10M-EPOCH-L-1785776400000",
        episode_id="10M-EP-L-1785777000000",
        direction=Direction.LONG,
        confirmation_time_ms=confirmation_time_ms,
        entry_reference=entry,
        invalidation=invalidation,
        next_named_level=target,
        next_named_level_source=NamedLevelSource.CONFIRMED_PIVOT_10M,
        next_named_level_provenance_time_ms=confirmation_time_ms - 3_600_000,
        risk=risk,
        space=space,
        space_r=space / risk,
    )


def active_short_plan(
    *,
    opportunity_id: str = "10M-TC-S-1785778800000",
    confirmation_time_ms: int = 1_785_778_800_000,
    target: float = 86.0,
) -> OpportunityPlan:
    entry = 93.2
    invalidation = 98.4
    risk = invalidation - entry
    space = entry - target
    return OpportunityPlan(
        opportunity_id=opportunity_id,
        epoch_id="10M-EPOCH-S-1785776400000",
        episode_id="10M-EP-S-1785777000000",
        direction=Direction.SHORT,
        confirmation_time_ms=confirmation_time_ms,
        entry_reference=entry,
        invalidation=invalidation,
        next_named_level=target,
        next_named_level_source=NamedLevelSource.CONFIRMED_PIVOT_10M,
        next_named_level_provenance_time_ms=confirmation_time_ms - 3_600_000,
        risk=risk,
        space=space,
        space_r=space / risk,
    )


def shifted_plan(plan: OpportunityPlan, *, opportunity_id: str) -> OpportunityPlan:
    return replace(
        plan,
        opportunity_id=opportunity_id,
        confirmation_time_ms=plan.confirmation_time_ms + 600_000,
        episode_id=plan.episode_id + "-NEXT",
    )
