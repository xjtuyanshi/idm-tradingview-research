"""Outward marker/alert and current-plan lifecycle contract for v1.4."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

import pytest

from research.phase1_10m_position_reversal_oracle import (
    ALERT_MESSAGES,
    ALERT_TITLES,
    DEFAULT_STALE_AFTER_MS,
    AlertDecisionReason,
    AlertKind,
    Event,
    PlanStatus,
    PositionReversalEngine,
    ReasonCode,
    State,
    TenMinuteBar,
    decide_outward_alert,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    UPPER_TRIGGER,
    bar,
    prior_atr,
    resistance_band,
    standard_bands,
    support_band,
)

ROOT = Path(__file__).resolve().parents[2]
PINE = ROOT / "idm_phase1_10m_position_reversal_v1.pine"


def _observe_and_decide(
    bar_value: TenMinuteBar,
    bands: tuple,
    atr,
):
    observation = PositionReversalEngine().ingest(bar_value, bands, atr)
    return observation, decide_outward_alert(observation, bar_value, bands, atr)


def _long_ready():
    bar_value = bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5)
    bands = standard_bands()
    atr = prior_atr()
    return bar_value, bands, atr


def _short_ready():
    bar_value = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    bands = standard_bands()
    atr = prior_atr()
    return bar_value, bands, atr


def test_exactly_four_selectable_alertconditions_have_stable_titles_and_messages() -> None:
    code = PINE.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("alertcondition(")
    ]
    assert len(lines) == 4
    pulse_names = (
        "supportWatchPulse",
        "resistanceWatchPulse",
        "longReadyPulse",
        "shortReadyPulse",
    )
    for line, pulse, title, message in zip(
        lines, pulse_names, ALERT_TITLES, ALERT_MESSAGES, strict=True
    ):
        assert line == (
            f'alertcondition({pulse}, title="{title}", message=\'{message}\')'
        )
        for placeholder in (
            "{{exchange}}:{{ticker}}",
            "{{interval}}",
            "{{time}}",
            "{{open}}",
            "{{high}}",
            "{{low}}",
            "{{close}}",
        ):
            assert placeholder in message
        assert "K线时间(UTC)={{time}}" in message
    for message in ALERT_MESSAGES[:2]:
        assert "仅观察，不是入场" in message
        assert "位置计划尚未接入3m" in message
        assert '{{plot("PR_BAND_LOWER")}}' in message
        assert '{{plot("PR_BAND_UPPER")}}' in message
    for message in ALERT_MESSAGES[2:]:
        assert "条件已确认，不是订单" in message
        assert "位置计划尚未接入3m" in message
        assert "R3.2反向或已有计划时不执行" in message
        assert '{{plot("PR_BAND_LOWER")}}' in message
        assert '{{plot("PR_BAND_UPPER")}}' in message
        for plot_title in (
            "PR_TRIGGER",
            "PR_INVALIDATION",
            "PR_TARGET",
            "PR_SPACE_R",
        ):
            assert f'{{{{plot("{plot_title}")}}}}' in message


def test_alert_pulses_are_current_event_guards_not_persistent_state_or_ui_toggles() -> None:
    code = PINE.read_text(encoding="utf-8")
    definitions = {
        name: next(
            line.strip()
            for line in code.splitlines()
            if line.strip().startswith(f"bool {name} =")
        )
        for name in (
            "supportWatchPulse",
            "resistanceWatchPulse",
            "longReadyPulse",
            "shortReadyPulse",
        )
    }
    for line in definitions.values():
        assert "outwardSurfaceOk" in line
        assert "ev ==" in line
        assert "reason ==" in line
        assert "st ==" in line
        assert "lastEvent" not in line
        assert "latestPlanFresh" not in line
        assert "showReadyHistory" not in line
        assert "showWatchHistory" not in line
        assert "showFrozenBand" not in line
        assert "showCard" not in line
    for name in ("supportWatchPulse", "resistanceWatchPulse"):
        assert "eventSourceDeliveryOk" in definitions[name]
        assert "eventAtrDeliveryOk" in definitions[name]
        assert "not terminalRegistered" in definitions[name]
    for name in ("longReadyPulse", "shortReadyPulse"):
        assert "reason == RS_READY" in definitions[name]
        assert "readyIdentityOk" in definitions[name]
        assert "readyNumbersOk" in definitions[name]
        assert "eventSourceDeliveryOk" in definitions[name]
        assert "eventTargetDeliveryOk" in definitions[name]
        assert "eventAtrDeliveryOk" in definitions[name]

    # Presentation uses the exact alert pulse, with only the marker visibility
    # toggle layered on top. It cannot broaden the event condition.
    assert "plotshape((showWatchHistory or barstate.islast) and supportWatchPulse ? markerPrice : na" in code
    assert "plotshape((showWatchHistory or barstate.islast) and resistanceWatchPulse ? markerPrice : na" in code
    assert "plotshape(showReadyHistory and longReadyPulse ? markerPrice : na" in code
    assert "plotshape(showReadyHistory and shortReadyPulse ? markerPrice : na" in code
    assert "bouncePulse" not in code
    assert "rejectionPulse" not in code


def test_oracle_alert_decision_is_independent_of_marker_presentation() -> None:
    watch_bar = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)
    bands = standard_bands()
    atr = prior_atr()
    watch = PositionReversalEngine().ingest(watch_bar, bands, atr)
    hidden_watch = replace(watch, marker_text=None, marker_price=None)
    watch_decision = decide_outward_alert(hidden_watch, watch_bar, bands, atr)
    assert watch_decision.fire is True
    assert watch_decision.alert_kind is AlertKind.SUPPORT_WATCH

    ready_bar, bands, atr = _long_ready()
    ready = PositionReversalEngine().ingest(ready_bar, bands, atr)
    hidden_ready = replace(ready, marker_text=None, marker_price=None)
    ready_decision = decide_outward_alert(hidden_ready, ready_bar, bands, atr)
    assert ready_decision.fire is True
    assert ready_decision.alert_kind is AlertKind.LONG_READY


def test_oracle_ready_alert_requires_exact_current_identity_and_numeric_payload() -> None:
    ready_bar, bands, atr = _long_ready()
    ready = PositionReversalEngine().ingest(ready_bar, bands, atr)
    opportunity = ready.opportunity
    assert opportunity is not None

    stale_event = replace(
        ready,
        opportunity=replace(
            opportunity,
            confirmation_time_ms=opportunity.confirmation_time_ms - 600_000,
        ),
    )
    stale_decision = decide_outward_alert(stale_event, ready_bar, bands, atr)
    assert stale_decision.fire is False
    assert stale_decision.decision_reason is AlertDecisionReason.EVENT_GUARD_FAILED

    wrong_source = replace(ready, source_fingerprint="CID1|B|wrong")
    wrong_source_decision = decide_outward_alert(wrong_source, ready_bar, bands, atr)
    assert wrong_source_decision.fire is False
    assert (
        wrong_source_decision.decision_reason
        is AlertDecisionReason.EVENT_GUARD_FAILED
    )

    invalid_numbers = replace(
        ready,
        opportunity=replace(opportunity, space_r=0.999999),
    )
    invalid_numbers_decision = decide_outward_alert(
        invalid_numbers, ready_bar, bands, atr
    )
    assert invalid_numbers_decision.fire is False
    assert (
        invalid_numbers_decision.decision_reason
        is AlertDecisionReason.EVENT_GUARD_FAILED
    )


def test_four_positive_event_types_fire_and_use_matching_marker_text() -> None:
    cases = (
        (
            bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
            standard_bands(),
            prior_atr(),
            Event.SUPPORT_WATCH,
            State.APPROACH,
            ReasonCode.WATCH_ONLY,
            "支撑观察",
            AlertKind.SUPPORT_WATCH,
        ),
        (
            bar(12, 0, 7460.0, 7468.0, 7458.0, UPPER_TRIGGER),
            standard_bands(),
            prior_atr(),
            Event.RESISTANCE_WATCH,
            State.APPROACH,
            ReasonCode.WATCH_ONLY,
            "阻力观察",
            AlertKind.RESISTANCE_WATCH,
        ),
        (*_long_ready(), Event.BOUNCE_CONFIRMED, State.READY, ReasonCode.READY, "多头确认", AlertKind.LONG_READY),
        (*_short_ready(), Event.REJECTION_CONFIRMED, State.READY, ReasonCode.READY, "空头确认", AlertKind.SHORT_READY),
    )
    for (
        bar_value,
        bands,
        atr,
        event,
        state,
        reason,
        marker,
        alert_kind,
    ) in cases:
        observation, decision = _observe_and_decide(bar_value, bands, atr)
        assert observation.event is event
        assert observation.state is state
        assert observation.reason_code is reason
        assert observation.marker_text == marker
        assert decision.fire is True
        assert decision.alert_kind is alert_kind
        assert decision.decision_reason is AlertDecisionReason.FIRE
        assert decision.source_delivery_ok is True
        assert decision.atr_delivery_ok is True
        assert decision.target_delivery_ok is True


def test_same_bar_touch_and_confirm_is_ready_only_not_double_watch() -> None:
    bar_value, bands, atr = _long_ready()
    observation, decision = _observe_and_decide(bar_value, bands, atr)
    assert observation.watch_registered is True
    assert observation.terminal_registered is True
    assert observation.event is Event.BOUNCE_CONFIRMED
    assert observation.marker_text == "多头确认"
    assert decision.alert_kind is AlertKind.LONG_READY
    assert decision.fire is True
    assert observation.event is not Event.SUPPORT_WATCH


def test_non_ready_reactions_keep_diagnostic_event_but_have_no_marker_or_alert() -> None:
    ready_bar, _, atr = _long_ready()
    missing_bands = (support_band(),)
    missing_observation, missing_decision = _observe_and_decide(
        ready_bar, missing_bands, atr
    )
    assert missing_observation.event is Event.BOUNCE_CONFIRMED
    assert missing_observation.reason_code is ReasonCode.TARGET_MISSING
    assert missing_observation.marker_text is None
    assert missing_observation.opportunity is None
    assert missing_decision.fire is False
    assert missing_decision.decision_reason is AlertDecisionReason.EVENT_GUARD_FAILED

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
    space_observation, space_decision = _observe_and_decide(
        ready_bar, (support_band(), near, far), atr
    )
    assert space_observation.event is Event.BOUNCE_CONFIRMED
    assert space_observation.reason_code is ReasonCode.SPACE_LT_1R
    assert space_observation.marker_text is None
    assert space_decision.fire is False
    assert space_decision.decision_reason is AlertDecisionReason.EVENT_GUARD_FAILED

    consumed_target = resistance_band(
        source_id="SATY-ATR-NEAR-CONSUMED",
        lower_bound=7445.0,
        upper_bound=7445.0,
    )
    consumed_bands = (support_band(), consumed_target)
    consumed_engine = PositionReversalEngine()
    consumed_engine.ingest(
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        consumed_bands,
        atr,
    )
    consumed_bar = bar(12, 10, 7421.4, 7446.0, 7421.0, 7435.0)
    consumed_observation = consumed_engine.ingest(
        consumed_bar, consumed_bands, atr
    )
    consumed_decision = decide_outward_alert(
        consumed_observation, consumed_bar, consumed_bands, atr
    )
    assert consumed_observation.reason_code is ReasonCode.TARGET_CONSUMED
    assert consumed_observation.marker_text is None
    assert consumed_decision.fire is False

    # Even a mechanically inconsistent READY-like observation with invalid
    # risk cannot cross the outward guard. This protects the decision contract
    # independently from the producer's current geometry checks.
    ready_observation, _ = _observe_and_decide(*_long_ready())
    risk_invalid = replace(
        ready_observation,
        state=State.FAILED,
        reason_code=ReasonCode.RISK_INVALID,
        marker_text=None,
        opportunity=None,
        active_opportunity=None,
        plan_status=PlanStatus.NONE,
    )
    risk_decision = decide_outward_alert(
        risk_invalid, *_long_ready()
    )
    assert risk_decision.fire is False
    assert risk_decision.decision_reason is AlertDecisionReason.EVENT_GUARD_FAILED


def test_ready_alert_requires_exact_active_owner_and_unended_plan() -> None:
    ready_bar, bands, atr = _long_ready()
    ready = PositionReversalEngine().ingest(ready_bar, bands, atr)
    assert ready.opportunity is not None
    assert decide_outward_alert(ready, ready_bar, bands, atr).fire is True

    wrong_owner = replace(ready.opportunity, opportunity_id="WRONG-OWNER")
    tampered = (
        replace(ready, plan_status=PlanStatus.SUPPRESSED),
        replace(ready, plan_status=PlanStatus.NONE),
        replace(ready, active_opportunity=None),
        replace(ready, active_opportunity=wrong_owner),
        replace(ready, plan_end_time_ms=ready_bar.visible_at_ms),
    )
    for observation in tampered:
        decision = decide_outward_alert(observation, ready_bar, bands, atr)
        assert decision.fire is False
        assert decision.decision_reason is AlertDecisionReason.EVENT_GUARD_FAILED


def test_outward_alert_fails_closed_on_wrong_host_or_malformed_context() -> None:
    ready_bar, bands, atr = _long_ready()
    ready = PositionReversalEngine().ingest(ready_bar, bands, atr)

    bad_bars = (
        replace(ready_bar, symbol="OTHER:SPX"),
        replace(ready_bar, timeframe_ms=180_000),
        replace(ready_bar, is_standard=False),
        replace(ready_bar, high=ready_bar.low - 1.0),
    )
    for bad_bar in bad_bars:
        decision = decide_outward_alert(ready, bad_bar, bands, atr)
        assert decision.fire is False
        assert decision.decision_reason is AlertDecisionReason.UNCONFIRMED_OR_INVALID

    malformed = (
        ((support_band(lower_bound=float("nan")), resistance_band()), atr),
        ((support_band(), resistance_band(upper_bound=float("nan"))), atr),
        (bands, prior_atr(value=float("nan"))),
        (bands, prior_atr(source_id=" invalid ")),
    )
    for malformed_bands, malformed_atr in malformed:
        decision = decide_outward_alert(
            ready, ready_bar, malformed_bands, malformed_atr
        )
        assert decision.fire is False
        assert decision.decision_reason in {
            AlertDecisionReason.SOURCE_NOT_DELIVERABLE_AT_CLOSE,
            AlertDecisionReason.TARGET_NOT_DELIVERABLE_AT_CLOSE,
            AlertDecisionReason.ATR_NOT_DELIVERABLE_AT_CLOSE,
        }


def test_outward_alert_requires_the_complete_current_source_surface() -> None:
    ready_bar, bands, atr = _long_ready()
    ready = PositionReversalEngine().ingest(ready_bar, bands, atr)
    stale_time = ready_bar.timestamp_ms - DEFAULT_STALE_AFTER_MS - 1
    problematic_extras = (
        resistance_band(
            source_id=" invalid ",
            source_version="v2",
            lower_bound=7520.0,
            upper_bound=7520.0,
        ),
        support_band(),
        resistance_band(
            source_id="SATY-ATR-EXPIRED-EXTRA",
            source_version="v2",
            lower_bound=7520.0,
            upper_bound=7520.0,
            valid_until_ms=ready_bar.timestamp_ms,
        ),
        resistance_band(
            source_id="SATY-ATR-STALE-EXTRA",
            source_version="v2",
            lower_bound=7520.0,
            upper_bound=7520.0,
            published_at_ms=stale_time,
            level_known_at_ms=stale_time,
        ),
    )
    for extra in problematic_extras:
        decision = decide_outward_alert(ready, ready_bar, (*bands, extra), atr)
        assert decision.fire is False
        assert decision.decision_reason is AlertDecisionReason.UNCONFIRMED_OR_INVALID


def test_accepted_break_conflict_multiple_reset_expiry_and_duplicate_never_alert() -> None:
    atr = prior_atr()
    cases: list[tuple[TenMinuteBar, tuple, object]] = []
    # Accepted break.
    cases.append(
        (
            bar(10, 0, 7430.0, 7432.0, 7412.0, 7415.5),
            standard_bands(),
            atr,
        )
    )
    # Opposite-side conflict.
    close_resistance = resistance_band(
        source_id="SATY-ATR-CLOSE-RESISTANCE",
        lower_bound=7425.0,
        upper_bound=7425.0,
    )
    cases.append(
        (
            bar(12, 0, 7423.0, 7426.0, 7420.0, 7423.0),
            (support_band(), close_resistance),
            atr,
        )
    )
    # Same-side multiple touch.
    second_support = support_band(
        source_id="SATY-ATR-SECOND-SUPPORT",
        source_version="v2",
        lower_bound=7422.0,
        upper_bound=7422.0,
    )
    cases.append(
        (
            bar(12, 0, 7423.0, 7430.0, 7420.9, 7423.0),
            (support_band(), second_support, resistance_band()),
            atr,
        )
    )
    # Wrong host produces a reset pulse, never a trader alert.
    cases.append(
        (
            bar(
                12,
                0,
                7425.0,
                7430.0,
                7420.9,
                LOWER_TRIGGER,
                symbol="OTHER:SPX",
            ),
            standard_bands(),
            atr,
        )
    )

    expected_events = (
        Event.ACCEPTED_BREAK,
        Event.POSITION_CONFLICT,
        Event.MULTIPLE_SAME_SIDE,
        Event.DATA_RESET,
    )
    for (bar_value, bands, atr_value), expected_event in zip(
        cases, expected_events, strict=True
    ):
        observation, decision = _observe_and_decide(bar_value, bands, atr_value)
        assert observation.event is expected_event
        assert observation.marker_text is None
        assert decision.fire is False
        assert decision.alert_kind is AlertKind.NONE
        assert decision.decision_reason is AlertDecisionReason.NO_CURRENT_EVENT

    # Reaction expiry is a multi-bar terminal and also cannot alert.
    engine = PositionReversalEngine()
    bands = standard_bands()
    first = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)
    second = bar(12, 10, 7421.2, 7430.0, 7420.9, LOWER_TRIGGER)
    third = bar(12, 20, 7421.2, 7430.0, 7420.9, LOWER_TRIGGER)
    engine.ingest(first, bands, atr)
    engine.ingest(second, bands, atr)
    expiry = engine.ingest(third, bands, atr)
    expiry_decision = decide_outward_alert(expiry, third, bands, atr)
    assert expiry.event is Event.REACTION_EXPIRED
    assert expiry.marker_text is None
    assert expiry_decision.fire is False

    # Exact duplicate is a no-op even when the duplicate OHLC would otherwise
    # be actionable.
    engine = PositionReversalEngine()
    watch_bar = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)
    engine.ingest(watch_bar, bands, atr)
    duplicate_bar = replace(
        watch_bar,
        high=7468.0,
        low=7420.0,
        close=7460.0,
    )
    duplicate = engine.ingest(duplicate_bar, bands, atr)
    duplicate_decision = decide_outward_alert(
        duplicate, duplicate_bar, bands, atr
    )
    assert duplicate.event is Event.NONE
    assert duplicate.reason_code is ReasonCode.DATA_DUPLICATE_IGNORED
    assert duplicate.marker_text is None
    assert duplicate_decision.fire is False


def test_delivery_gate_preserves_bar_open_causality_and_requires_close_validity() -> None:
    watch_bar = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)
    normal_target = resistance_band()
    normal_atr = prior_atr()

    source_expires_at_close = support_band(valid_until_ms=watch_bar.visible_at_ms)
    source_observation, source_decision = _observe_and_decide(
        watch_bar, (source_expires_at_close, normal_target), normal_atr
    )
    assert source_observation.event is Event.SUPPORT_WATCH
    assert source_decision.fire is False
    assert (
        source_decision.decision_reason
        is AlertDecisionReason.SOURCE_NOT_DELIVERABLE_AT_CLOSE
    )

    atr_expires_at_close = replace(normal_atr, valid_until_ms=watch_bar.visible_at_ms)
    atr_observation, atr_decision = _observe_and_decide(
        watch_bar, standard_bands(), atr_expires_at_close
    )
    assert atr_observation.event is Event.SUPPORT_WATCH
    assert atr_decision.fire is False
    assert (
        atr_decision.decision_reason
        is AlertDecisionReason.ATR_NOT_DELIVERABLE_AT_CLOSE
    )

    long_bar, _, _ = _long_ready()
    target_expires_at_close = resistance_band(valid_until_ms=long_bar.visible_at_ms)
    target_observation, target_decision = _observe_and_decide(
        long_bar, (support_band(), target_expires_at_close), normal_atr
    )
    assert target_observation.event is Event.BOUNCE_CONFIRMED
    assert target_observation.reason_code is ReasonCode.READY
    assert target_decision.fire is False
    assert (
        target_decision.decision_reason
        is AlertDecisionReason.TARGET_NOT_DELIVERABLE_AT_CLOSE
    )

    # Fresh at bar open but stale by confirmation is accepted by the producer
    # and blocked only at outward delivery.
    just_fresh_at_open = watch_bar.timestamp_ms - DEFAULT_STALE_AFTER_MS + 1
    stale_by_close = support_band(
        published_at_ms=just_fresh_at_open,
        level_known_at_ms=just_fresh_at_open,
    )
    stale_observation, stale_decision = _observe_and_decide(
        watch_bar, (stale_by_close, normal_target), normal_atr
    )
    assert stale_observation.event is Event.SUPPORT_WATCH
    assert stale_decision.fire is False
    assert (
        stale_decision.decision_reason
        is AlertDecisionReason.SOURCE_NOT_DELIVERABLE_AT_CLOSE
    )

    stale_atr = replace(
        normal_atr,
        published_at_ms=just_fresh_at_open,
        known_at_ms=just_fresh_at_open,
        completed_source_open_ms=just_fresh_at_open - 86_400_000,
        completed_source_close_ms=just_fresh_at_open,
    )
    stale_atr_observation, stale_atr_decision = _observe_and_decide(
        watch_bar, standard_bands(), stale_atr
    )
    assert stale_atr_observation.event is Event.SUPPORT_WATCH
    assert stale_atr_decision.fire is False
    assert (
        stale_atr_decision.decision_reason
        is AlertDecisionReason.ATR_NOT_DELIVERABLE_AT_CLOSE
    )

    target_fresh_at_open = long_bar.timestamp_ms - DEFAULT_STALE_AFTER_MS + 1
    stale_target = resistance_band(
        published_at_ms=target_fresh_at_open,
        level_known_at_ms=target_fresh_at_open,
    )
    stale_target_observation, stale_target_decision = _observe_and_decide(
        long_bar, (support_band(), stale_target), normal_atr
    )
    assert stale_target_observation.event is Event.BOUNCE_CONFIRMED
    assert stale_target_observation.reason_code is ReasonCode.READY
    assert stale_target_decision.fire is False
    assert (
        stale_target_decision.decision_reason
        is AlertDecisionReason.TARGET_NOT_DELIVERABLE_AT_CLOSE
    )

    # Information first known inside the 10m bar is never made causal by the
    # close check. The producer itself fails closed at bar open.
    future_known = support_band(
        published_at_ms=watch_bar.timestamp_ms + 60_000,
        level_known_at_ms=watch_bar.timestamp_ms + 60_000,
    )
    future_observation, future_decision = _observe_and_decide(
        watch_bar, (future_known, normal_target), normal_atr
    )
    assert future_observation.event is Event.NONE
    assert future_observation.data_valid is True
    assert any("FUTURE_PUBLICATION" in item for item in future_observation.source_rejections)
    assert future_decision.fire is False


def test_only_current_bar_event_can_alert_after_a_ready_plan_exists() -> None:
    ready_bar, bands, atr = _long_ready()
    engine = PositionReversalEngine()
    ready = engine.ingest(ready_bar, bands, atr)
    assert decide_outward_alert(ready, ready_bar, bands, atr).fire is True

    next_bar = bar(11, 40, 7443.5, 7450.0, 7438.0, 7448.0)
    later = engine.ingest(next_bar, bands, atr)
    later_decision = decide_outward_alert(later, next_bar, bands, atr)
    assert later.active_opportunity is not None
    assert later.plan_status is PlanStatus.ACTIVE
    assert later.event is Event.WAIT_CLEAR_COMPLETED
    assert later_decision.fire is False
    assert later_decision.decision_reason is AlertDecisionReason.NO_CURRENT_EVENT


def test_current_plan_ends_on_invalidation_target_expiry_or_reset_without_rewriting_ledger() -> None:
    ready_bar, bands, atr = _long_ready()

    def engine_with_ready() -> tuple[PositionReversalEngine, object]:
        engine = PositionReversalEngine()
        ready = engine.ingest(ready_bar, bands, atr)
        assert ready.opportunity is not None
        assert ready.plan_status is PlanStatus.ACTIVE
        return engine, ready.opportunity

    engine, ledger_item = engine_with_ready()
    target_bar = bar(11, 40, 7443.5, 7468.0, 7440.0, 7460.0)
    target = engine.ingest(target_bar, bands, atr)
    assert target.plan_status is PlanStatus.TARGET_REACHED
    assert target.active_opportunity is None
    assert target.plan_end_time_ms == target_bar.visible_at_ms
    assert engine.opportunities == (ledger_item,)

    engine, ledger_item = engine_with_ready()
    invalidation_bar = bar(11, 40, 7443.5, 7445.0, 7420.6, 7425.0)
    invalidated = engine.ingest(invalidation_bar, bands, atr)
    assert invalidated.plan_status is PlanStatus.INVALIDATED
    assert invalidated.active_opportunity is None
    assert invalidated.plan_end_time_ms == invalidation_bar.visible_at_ms
    assert engine.opportunities == (ledger_item,)

    # When both extremes are observed on one confirmed bar, fail-safe
    # invalidation has priority over claiming the target was reached first.
    engine, ledger_item = engine_with_ready()
    both_bar = bar(11, 40, 7443.5, 7468.0, 7420.6, 7440.0)
    both = engine.ingest(both_bar, bands, atr)
    assert both.plan_status is PlanStatus.INVALIDATED
    assert both.active_opportunity is None
    assert engine.opportunities == (ledger_item,)

    engine, ledger_item = engine_with_ready()
    wrong_host = bar(
        11,
        40,
        7443.5,
        7450.0,
        7438.0,
        7448.0,
        symbol="OTHER:SPX",
    )
    reset = engine.ingest(wrong_host, bands, atr)
    assert reset.event is Event.DATA_RESET
    assert reset.plan_status is PlanStatus.SUPPRESSED
    assert reset.active_opportunity is None
    assert engine.opportunities == (ledger_item,)


@pytest.mark.parametrize(
    ("case_name", "later_bands", "later_atr"),
    (
        ("source_missing", (resistance_band(),), prior_atr()),
        ("target_missing", (support_band(),), prior_atr()),
        (
            "source_valid_version_drift",
            (support_band(source_version="v2"), resistance_band()),
            prior_atr(),
        ),
        (
            "target_valid_version_drift",
            (support_band(), resistance_band(source_version="v2")),
            prior_atr(),
        ),
        (
            "atr_valid_version_drift",
            standard_bands(),
            prior_atr(source_version="2026-07-31-v2"),
        ),
    ),
)
def test_active_plan_fails_closed_when_frozen_context_disappears_or_changes(
    case_name: str,
    later_bands: tuple,
    later_atr,
) -> None:
    ready_bar, bands, atr = _long_ready()
    engine = PositionReversalEngine()
    ready = engine.ingest(ready_bar, bands, atr)
    assert ready.opportunity is not None
    ledger_item = ready.opportunity

    later_bar = bar(11, 40, 7443.5, 7450.0, 7438.0, 7448.0)
    later = engine.ingest(later_bar, later_bands, later_atr)
    decision = decide_outward_alert(later, later_bar, later_bands, later_atr)

    assert later.plan_status is PlanStatus.SUPPRESSED, case_name
    assert later.active_opportunity is None, case_name
    assert later.opportunity is None, case_name
    assert decision.fire is False, case_name
    assert engine.opportunities == (ledger_item,), case_name


def test_oracle_and_pine_check_active_plan_context_before_price_lifecycle() -> None:
    oracle = (
        ROOT / "research" / "phase1_10m_position_reversal_oracle.py"
    ).read_text(encoding="utf-8")
    oracle_context = oracle.index("if not self._active_plan_context_ok(validated.bands, atr):")
    oracle_price = oracle.index("self._advance_active_plan(bar)", oracle_context)
    assert oracle_context < oracle_price

    code = PINE.read_text(encoding="utf-8")
    pine_context = code.index("bool latestPlanContextOk =")
    pine_gate = code.index("if latestPlanStatus == PLAN_ACTIVE", pine_context)
    pine_reset = code.index("if not latestPlanContextOk", pine_gate)
    pine_price = code.index("bool planInvalidated =", pine_reset)
    assert pine_context < pine_gate < pine_reset < pine_price


def test_duplicate_does_not_end_active_plan_but_backward_and_gap_do() -> None:
    ready_bar, bands, atr = _long_ready()
    engine = PositionReversalEngine()
    ready = engine.ingest(ready_bar, bands, atr)
    assert ready.plan_status is PlanStatus.ACTIVE

    duplicate_that_hits_both = replace(
        ready_bar,
        high=7468.0,
        low=7420.6,
        close=7440.0,
    )
    duplicate = engine.ingest(duplicate_that_hits_both, bands, atr)
    assert duplicate.reason_code is ReasonCode.DATA_DUPLICATE_IGNORED
    assert duplicate.plan_status is PlanStatus.ACTIVE
    assert duplicate.active_opportunity is not None

    backward = replace(
        ready_bar,
        timestamp_ms=ready_bar.timestamp_ms - 600_000,
    )
    backward_result = engine.ingest(backward, bands, atr)
    assert backward_result.event is Event.DATA_RESET
    assert backward_result.reason_code is ReasonCode.DATA_NON_MONOTONIC
    assert backward_result.plan_status is PlanStatus.SUPPRESSED

    engine = PositionReversalEngine()
    engine.ingest(ready_bar, bands, atr)
    gap_bar = replace(
        ready_bar,
        timestamp_ms=ready_bar.timestamp_ms + 1_200_000,
    )
    gap_result = engine.ingest(gap_bar, bands, atr)
    assert gap_result.event is Event.DATA_RESET
    assert gap_result.reason_code is ReasonCode.DATA_GAP_RESET
    assert gap_result.plan_status is PlanStatus.SUPPRESSED


def test_active_plan_expires_at_first_bar_open_at_or_after_frozen_expiry() -> None:
    ready_bar, bands, atr = _long_ready()
    engine = PositionReversalEngine()
    ready = engine.ingest(ready_bar, bands, atr)
    opportunity = ready.opportunity
    assert opportunity is not None

    timestamp = ready_bar.timestamp_ms + 600_000
    latest = ready
    while timestamp <= opportunity.expires_at_ms:
        neutral = TenMinuteBar(
            timestamp_ms=timestamp,
            open=7445.0,
            high=7450.0,
            low=7440.0,
            close=7446.0,
        )
        latest = engine.ingest(neutral, bands, atr)
        timestamp += 600_000

    assert latest.bar_time_ms == opportunity.expires_at_ms
    assert latest.plan_status is PlanStatus.EXPIRED
    assert latest.active_opportunity is None
    assert latest.plan_end_time_ms == opportunity.expires_at_ms
    assert engine.opportunities == (opportunity,)


def test_pine_duplicate_branch_is_noop_and_backward_gap_are_separate_resets() -> None:
    code = PINE.read_text(encoding="utf-8")
    assert "bool hostSurfaceOk = symbolOk and timeframeOk and standardChartOk and paramsOk" in code
    assert (
        "bool duplicateConfirmed = barstate.isconfirmed and hostSurfaceOk and "
        "not na(lastConfirmedTime) and time == lastConfirmedTime"
    ) in code
    assert (
        "bool backwardReset = barstate.isconfirmed and not na(lastConfirmedTime) "
        "and time < lastConfirmedTime"
    ) in code
    assert (
        "bool gapReset = barstate.isconfirmed and not na(lastConfirmedTime) and "
        "time > lastConfirmedTime and time - lastConfirmedTime != BAR_INTERVAL_MS"
    ) in code
    duplicate_branch = re.search(
        r"if duplicateConfirmed\n(?P<body>(?:        .*\n)+?)    else if not sourceSurfaceOk",
        code,
    )
    assert duplicate_branch is not None
    body = duplicate_branch.group("body")
    assert "reason := RS_DATA_DUPLICATE" in body
    assert "ev := EV_DATA_RESET" not in body
    assert "latestPlanStatus :=" not in body
    assert "lastConfirmedTime :=" not in body
    assert "not hostSurfaceOk ? RS_DATA_RESET" in code
    assert "backwardReset ? RS_DATA_NON_MONOTONIC" in code
    assert "gapReset ? RS_DATA_GAP_RESET" in code
    assert "if not duplicateConfirmed" in code
    assert "lastConfirmedTime := backwardReset or not hostSurfaceOk ? na : time" in code


def test_wrong_host_at_exact_duplicate_timestamp_is_reset_not_noop() -> None:
    ready_bar, bands, atr = _long_ready()
    engine = PositionReversalEngine()
    engine.ingest(ready_bar, bands, atr)
    wrong_host_duplicate = replace(ready_bar, symbol="OTHER:SPX")
    result = engine.ingest(wrong_host_duplicate, bands, atr)
    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.DATA_SYMBOL_MISMATCH
    assert result.plan_status is PlanStatus.SUPPRESSED
    assert result.active_opportunity is None


def test_generated_pine_plan_gate_is_compile_safe_and_watch_text_is_black_chart_readable() -> None:
    code = PINE.read_text(encoding="utf-8")
    assert "float trigger = side == ROLE_SUPPORT ? barHigh : barLow" in code
    assert "float risk = side == ROLE_SUPPORT ? trigger - invalidation : invalidation - trigger" in code
    assert "float reward = targetPresent ? (side == ROLE_SUPPORT ? targetPrice - trigger : trigger - targetPrice) : na" in code
    assert "[outState, outReason, trigger, invalidation, risk, reward, spaceR]" in code
    assert "触发 =" not in code

    # Remove literals/comments, then require ASCII-only executable identifiers.
    executable = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", code)
    executable = re.sub(r"//.*", "", executable)
    assert re.search(r"[^\x00-\x7f]", executable) is None

    watch_lines = [
        line.strip()
        for line in code.splitlines()
        if "plotshape(" in line and "观察" in line
    ]
    assert len(watch_lines) == 2
    for line in watch_lines:
        assert "textcolor=color.white" in line
        assert "textcolor=color.black" not in line


def test_visual_surface_shows_only_current_frozen_band_and_explicit_setup_status() -> None:
    code = PINE.read_text(encoding="utf-8")
    assert 'input.bool(true, "显示当前冻结位置区间", group="图面")' in code
    assert 'input.bool(true, "显示五行状态卡", group="图面")' in code
    current_line = next(
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("bool currentFrozenBandVisible =")
    )
    assert "episodeSourceEffectiveKey" in current_line
    assert "frozenLower" in current_line and "frozenUpper" in current_line
    assert code.count('title="当前位置下沿"') == 1
    assert code.count('title="当前位置上沿"') == 1
    assert code.count('title="当前位置区间"') == 1
    assert "未配置/已过期｜见日更来源操作手册" in code
    assert "更新日更来源后重建四个提醒" in code
    latest_fresh = next(
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("bool latestPlanFresh =")
    )
    assert "latestPlanStatus == PLAN_ACTIVE" in latest_fresh
    assert "latestPlanSuppressed" in latest_fresh
    assert "latestPlanContextOk" not in latest_fresh


def test_pine_fails_closed_when_any_enabled_extra_band_is_stale() -> None:
    code = PINE.read_text(encoding="utf-8")
    assert "int SURFACE_BAND_STALE = 14" in code
    assert "bool anyBandStale = false" in code
    assert "bool itemStale = itemEnabled" in code
    assert "anyBandStale := anyBandStale or itemStale" in code
    source_reason = next(
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("int sourceSurfaceReason =")
    )
    assert "anyBandStale ? SURFACE_BAND_STALE" in source_reason
    assert "具名位已超 36 小时｜更新日更来源" in code
