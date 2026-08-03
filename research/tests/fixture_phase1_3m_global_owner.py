"""Synthetic fixtures for the Phase 1 3m global-owner contract.

The July 31 helper below encodes only the accepted public boundary
``SPACE_LT_1R -> no envelope``.  It is not a substitute for the unavailable
private TradingView replay export and is never described as a real positive.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from research.phase1_10m_position_reversal_oracle import (
    BandRole,
    PositionReversalEngine,
    ReasonCode as ReversalReason,
)
from research.phase1_3m_global_owner_oracle import (
    AdapterCandidate,
    Direction,
    LaneId,
    PlanEnvelope,
    SCHEMA_VERSION,
    ThreeMinuteBar,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    bar as reversal_bar,
    prior_atr,
    resistance_band,
    support_band,
)

NEW_YORK = ZoneInfo("America/New_York")


def et_ms(hour: int, minute: int, *, day: int = 31) -> int:
    return int(
        datetime(2026, 7, day, hour, minute, tzinfo=NEW_YORK).timestamp() * 1000
    )


def bar3(
    hour: int,
    minute: int,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    ema5: float = 100.5,
    ema12: float = 99.5,
    **overrides: object,
) -> ThreeMinuteBar:
    values: dict[str, object] = {
        "timestamp_ms": et_ms(hour, minute),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "ema5": ema5,
        "ema12": ema12,
    }
    values.update(overrides)
    return ThreeMinuteBar(**values)  # type: ignore[arg-type]


def envelope(
    lane: LaneId,
    direction: Direction,
    *,
    opportunity_id: str | None = None,
    fingerprint: str | None = None,
    trigger: float = 100.0,
    stop: float | None = None,
    target: float | None = None,
    confirmation_time_ms: int | None = None,
    visible_at_ms: int | None = None,
    permission_expires_at_ms: int | None = None,
    context_valid_until_ms: int | None = None,
) -> PlanEnvelope:
    confirmation = et_ms(9, 30) if confirmation_time_ms is None else confirmation_time_ms
    visible = et_ms(9, 40) if visible_at_ms is None else visible_at_ms
    expires = et_ms(11, 40) if permission_expires_at_ms is None else permission_expires_at_ms
    if stop is None:
        stop = 95.0 if direction is Direction.LONG else 105.0
    if target is None:
        target = 110.0 if direction is Direction.LONG else 90.0
    lane_text = "TC" if lane is LaneId.TREND_CONTINUATION else "PR"
    side_text = "L" if direction is Direction.LONG else "S"
    oid = opportunity_id or f"{lane_text}-{side_text}-1"
    fp = fingerprint or f"fp-{lane_text}-{side_text}-1"
    return PlanEnvelope(
        schema_version=SCHEMA_VERSION,
        lane_id=lane,
        opportunity_id=oid,
        episode_id=f"episode-{oid}",
        payload_fingerprint=fp,
        direction=direction,
        producer_trigger=trigger,
        invalidation=stop,
        target=target,
        target_source_key=f"target-{oid}",
        confirmation_time_ms=confirmation,
        visible_at_ms=visible,
        permission_expires_at_ms=expires,
        context_valid_until_ms=context_valid_until_ms,
    )


def candidate(
    lane: LaneId,
    direction: Direction,
    *,
    adoption_time: tuple[int, int] = (9, 42),
    overlap: ThreeMinuteBar | None = None,
    **envelope_overrides: object,
) -> AdapterCandidate:
    adoption_hour, adoption_minute = adoption_time
    if overlap is None:
        # The 09:39 bar overlaps the 09:40 completed-10m close.
        overlap = bar3(9, 39, 99.0, 100.0, 98.0, 99.5)
    plan = envelope(lane, direction, **envelope_overrides)
    assert plan.visible_at_ms <= et_ms(adoption_hour, adoption_minute)
    return AdapterCandidate(envelope=plan, overlap_bar=overlap)


def accepted_july31_1140_space_lt_1r_boundary() -> tuple[object, object]:
    """Return accepted producer-negative evidence and its engine.

    The raw private TradingView replay is not bundled.  This public fixture uses
    the accepted 11:30 reaction geometry with an explicitly nearer frozen target
    to reproduce the contractual outcome: SPACE_LT_1R and no opportunity payload.
    """

    near = resistance_band(
        source_id="SATY-ATR-NEAR-RESISTANCE",
        lower_bound=7445.0,
        upper_bound=7445.0,
    )
    far = resistance_band(
        source_id="SATY-ATR-FAR-RESISTANCE",
        source_version="v2",
        lower_bound=7540.0,
        upper_bound=7540.0,
    )
    engine = PositionReversalEngine()
    observation = engine.ingest(
        reversal_bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5),
        (support_band(), near, far),
        prior_atr(),
    )
    assert observation.reason_code is ReversalReason.SPACE_LT_1R
    assert observation.opportunity is None
    return observation, engine


def with_envelope(candidate_value: AdapterCandidate, **changes: object) -> AdapterCandidate:
    return replace(candidate_value, envelope=replace(candidate_value.envelope, **changes))
