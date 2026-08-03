from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from hashlib import sha256
from pathlib import Path

import pytest

from research.generate_phase1_10m_position_reversal_pine_v1 import (
    PINE_SOURCE as REVERSAL_PINE_SOURCE,
    embedded_source_fragments,
)
from research.generate_phase1_10m_primary_pine_r3 import (
    PRIMARY_TEMPLATE,
    TIMING_TEMPLATE,
    render as render_trend,
)
from research.generate_phase1_3m_global_owner_pine_v1 import (
    EXPECTED_FROZEN_PINE_HASHES,
    PINE_SOURCE,
    PINE_SHA256,
    _input_names,
    _render_reversal_adapter,
    _request_components,
    render_pine,
)
from research.phase1_10m_position_reversal_oracle import (
    Direction as ReversalDirection,
    OpportunityPayload,
)
from research.phase1_10m_primary_opportunity_oracle import (
    Direction as TrendDirection,
    NamedLevelSource,
    OpportunityPlan,
)
from research.phase1_3m_global_owner_oracle import (
    Direction,
    LaneId,
    PLAN_FINGERPRINT_VERSION,
    PlanEnvelope,
    ProducerTerminalKind,
    ReversalAdapter,
    SCHEMA_VERSION,
    TrendAdapter,
    canonical_plan_fingerprint,
)
from research.tests.fixture_phase1_3m_global_owner import bar3, et_ms

ROOT = Path(__file__).resolve().parents[2]
GLOBAL_PINE = ROOT / "idm_phase1_3m_global_owner_v1.pine"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _top_level_declarations(source: str) -> list[str]:
    declarations: list[str] = []
    excluded = (
        "if ",
        "else",
        "for ",
        "while ",
        "switch ",
        "plot",
        "fill",
        "alertcondition",
        "table.",
        "array.",
        "//",
        "[",
    )
    for raw in source.splitlines():
        if not raw or raw[0].isspace():
            continue
        line = raw.strip()
        if not line or line.startswith(excluded):
            continue
        if line.startswith("type "):
            declarations.append(line.split()[1])
        elif "=>" in line and "(" in line:
            declarations.append(line.split("(", 1)[0].split()[-1])
        elif "=" in line and ":=" not in line:
            name = line.split("=", 1)[0].split()[-1]
            if name and (name[0].isalpha() or name[0] == "_"):
                declarations.append(name)
    return declarations


def test_global_generator_is_byte_exact_and_frozen_pines_are_unchanged() -> None:
    assert render_pine() == PINE_SOURCE
    assert GLOBAL_PINE.read_text(encoding="utf-8") == PINE_SOURCE
    assert sha256(PINE_SOURCE.encode("utf-8")).hexdigest() == PINE_SHA256
    for relative_path, expected in EXPECTED_FROZEN_PINE_HASHES.items():
        assert _sha(ROOT / relative_path) == expected


def test_existing_standalone_generators_remain_byte_exact() -> None:
    assert (ROOT / "idm_phase1_10m_position_reversal_v1.pine").read_text(
        encoding="utf-8"
    ) == REVERSAL_PINE_SOURCE
    assert (ROOT / "idm_phase1_10m_primary_opportunity_v3.pine").read_text(
        encoding="utf-8"
    ) == render_trend(PRIMARY_TEMPLATE)
    assert (ROOT / "idm_phase1_3m_opportunity_timing_v3.pine").read_text(
        encoding="utf-8"
    ) == render_trend(TIMING_TEMPLATE)


def test_reversal_embedded_fragments_are_exact_canonical_slices_not_a_third_copy() -> None:
    constants, inputs, core = embedded_source_fragments()
    for fragment in (constants, inputs, core):
        assert fragment in REVERSAL_PINE_SOURCE
    generated_constants, generated_inputs, input_names, generated_core = (
        _render_reversal_adapter()
    )
    assert generated_constants
    assert generated_inputs
    assert generated_core
    assert input_names == _input_names(inputs)
    generator_source = (
        ROOT / "research/generate_phase1_3m_global_owner_pine_v1.py"
    ).read_text(encoding="utf-8")
    assert "import re" not in generator_source
    assert "re.sub" not in generator_source


def test_one_uniform_previous_completed_10m_transport() -> None:
    _, inputs, _, _ = _render_reversal_adapter()
    input_names = _input_names(inputs)
    lhs, expressions = _request_components(input_names)
    assert len(lhs) == len(expressions) == 71
    assert len(lhs) <= 127
    assert all(expression.endswith("[1]") for expression in expressions)
    assert PINE_SOURCE.count("request.security(") == 1
    assert "gaps=barmerge.gaps_off" in PINE_SOURCE
    assert "lookahead=barmerge.lookahead_on" in PINE_SOURCE
    assert "lookahead_off" not in PINE_SOURCE
    assert "barstate.isrealtime" not in PINE_SOURCE
    assert "request.security_lower_tf" not in PINE_SOURCE
    assert "input.source" not in PINE_SOURCE
    assert "timenow" not in PINE_SOURCE
    assert "varip" not in PINE_SOURCE
    request_line = next(
        line for line in PINE_SOURCE.splitlines() if "request.security(" in line
    )
    for expression in expressions:
        assert expression in request_line


def test_transport_visibility_continuity_and_strict_expiry_are_mechanical() -> None:
    required = (
        "e_timeClose <= time",
        "e_time != goLastObserved10mTime",
        "e_time != goLastConsumed10mTime",
        "goPayloadNewObservation",
        "goPayloadUnconsumed",
        "goPayloadRejectedByLedger",
        "goPayloadRejectedByReset",
        "goRaw10mMissingAfterStart",
        "time - goLast3mTime != GLOBAL_3M_INTERVAL_MS",
        "time == goAdoptionOpenMs + 180000",
        "time >= goOwner.permissionExpiresAtMs",
        "time_close >= goOwner.contextValidUntilMs",
        "time < trendCandidate.permissionExpiresAtMs",
        "time_close < trendCandidate.contextValidUntilMs",
    )
    for text in required:
        assert text in PINE_SOURCE
    process_line = next(
        line.strip()
        for line in PINE_SOURCE.splitlines()
        if line.strip().startswith("bool go_processPayload =")
    )
    assert "goPayloadUnconsumed" in process_line
    assert "goPayloadNewObservation" not in process_line
    assert "goLastObserved10mTime" not in process_line
    assert "goPayloadRejectedByLedger" in process_line
    assert "goPayloadRejectedByReset" in process_line
    assert "goLastObserved10mTime := e_time" in PINE_SOURCE
    consumed_block = (
        "if barstate.isconfirmed and go_processPayload\n"
        "    // Only successful shared-adapter delivery advances consumption identity.\n"
        "    goLastConsumed10mTime := e_time"
    )
    assert consumed_block in PINE_SOURCE
    assert PINE_SOURCE.index("goLastObserved10mTime := e_time") < PINE_SOURCE.index(
        "goLastConsumed10mTime := e_time"
    )


def test_reset_cutoff_and_rejected_timestamp_ledger_are_persistent_pine_guards() -> None:
    required = (
        "var int goResetVisibleCutoffMs = na",
        "var array<int> goRejected10mSourceTimes = array.new_int(0)",
        "int goResetBoundaryMs = na(goLast3mTime) ? time : math.max(time, goLast3mTime)",
        "goResetVisibleCutoffMs := na(goResetVisibleCutoffMs) ? goResetBoundaryMs : math.max(goResetVisibleCutoffMs, goResetBoundaryMs)",
        "array.indexof(goRejected10mSourceTimes, e_time) >= 0",
        "array.push(goRejected10mSourceTimes, e_time)",
        "trendCandidate.visibleAtMs > goResetVisibleCutoffMs",
        "reversalCandidate.visibleAtMs > goResetVisibleCutoffMs",
        'plot(goResetVisibleCutoffMs, title="AUDIT｜reset visible cutoff"',
        'plot(array.size(goRejected10mSourceTimes), title="AUDIT｜rejected 10m timestamps"',
    )
    for text in required:
        assert text in PINE_SOURCE


def test_terminal_event_audit_state_is_wait_10m_in_generated_pine() -> None:
    for event in (
        "GO_EVENT_INVALIDATED",
        "GO_EVENT_TARGET_REACHED",
        "GO_EVENT_EXPIRED",
        "GO_EVENT_MISSED",
        "GO_EVENT_DATA_RESET",
    ):
        needle = f"goEventPulse := {event}"
        positions: list[int] = []
        start_at = 0
        while True:
            position = PINE_SOURCE.find(needle, start_at)
            if position < 0:
                break
            positions.append(position)
            start_at = position + len(needle)
        assert positions, event
        for position in positions:
            assert "goState := GO_WAIT_10M" in PINE_SOURCE[max(0, position - 900) : position]
    assert 'plot(goState, title="AUDIT｜owner state"' in PINE_SOURCE


def test_transport_static_configuration_fields_are_freeze_required_not_ui_state() -> None:
    _, inputs, input_names, _ = _render_reversal_adapter()
    assert len(input_names) == 56
    input_lines = {
        line.split("=", 1)[0].split()[-1]
        for line in inputs.splitlines()
        if "input." in line and "=" in line
    }
    assert set(input_names) == input_lines
    _, expressions = _request_components(input_names)
    for name in input_names:
        assert f"{name}[1]" in expressions
    assert "static source/target/ATR configuration" in PINE_SOURCE
    assert "producer truth, not mutable producer UI/output state" in PINE_SOURCE
    assert "input.source" not in PINE_SOURCE


def test_later_opposite_conflict_precedes_unentered_owner_timing() -> None:
    required = (
        "bool laterTrendOppositeUsable",
        "bool laterReversalOppositeUsable",
        "bool laterOppositeConflict",
        "if laterOppositeConflict",
        "goEventPulse := GO_EVENT_CONFLICT",
    )
    for text in required:
        assert text in PINE_SOURCE
    start = PINE_SOURCE.index("bool laterTrendOppositeUsable")
    conflict = PINE_SOURCE.index("if laterOppositeConflict", start)
    old_timing = PINE_SOURCE.index("else if goState == GO_WAIT_PULLBACK", conflict)
    assert start < conflict < old_timing
    assert "trendCandidate.direction != goOwner.direction" in PINE_SOURCE[start:old_timing]
    assert "reversalCandidate.direction != goOwner.direction" in PINE_SOURCE[start:old_timing]


def test_overlap_and_adoption_bar_terminal_checks_are_stop_first() -> None:
    assert "f_stop_hit(trendCandidate, high[1], low[1], close[1])" in PINE_SOURCE
    assert "f_stop_hit(trendCandidate, high, low, close)" in PINE_SOURCE
    assert "f_stop_hit(reversalCandidate, high[1], low[1], close[1])" in PINE_SOURCE
    assert "f_stop_hit(reversalCandidate, high, low, close)" in PINE_SOURCE
    assert "trendPreTarget = trendUsable and not trendPreStop" in PINE_SOURCE
    assert "reversalPreTarget = reversalUsable and not reversalPreStop" in PINE_SOURCE
    assert PINE_SOURCE.index("bool trendPreStop") < PINE_SOURCE.index(
        "bool trendPreTarget"
    )
    assert PINE_SOURCE.index("bool reversalPreStop") < PINE_SOURCE.index(
        "bool reversalPreTarget"
    )


def test_base_identity_registry_collision_tombstone_and_third_variant_guard_exist() -> None:
    for text in (
        "goBaseKeys",
        "goBaseFingerprints",
        "goCollisionTombstones",
        "f_register_identity",
        "if f_array_contains(tombstones, baseKey)",
        "priorFingerprint != plan.payloadFingerprint",
        "f_array_contains(goCollisionTombstones, f_base_key(goOwner))",
    ):
        assert text in PINE_SOURCE


def test_producer_terminal_vocabulary_is_closed_and_identity_is_frozen_at_publish() -> None:
    expected = {
        "INVALIDATED",
        "TARGET_REACHED",
        "EXPIRED",
        "ACTIVE_NONE",
        "PERMISSION_EXPIRED",
        "CONTEXT_EXPIRED",
        "SOURCE_INVALID",
        "IDENTITY_DRIFT",
        "SUPPRESSED",
        "CONTEXT_RESET",
        "DATA_RESET",
    }
    assert {item.value for item in ProducerTerminalKind} == expected
    for name in expected:
        assert f"GO_TERM_{name}" in PINE_SOURCE
    for text in (
        "trendPublishedOpportunityId",
        "trendPublishedFingerprint",
        "reversalPublishedOpportunityId",
        "reversalPublishedFingerprint",
        "f_exact_terminal_matches",
        "trendTerminalId = trendPublishedOpportunityId",
        "reversalTerminalId = reversalPublishedOpportunityId",
    ):
        assert text in PINE_SOURCE
    assert PINE_SOURCE.index("exactInvalidated") < PINE_SOURCE.index("exactTarget")


def test_plan_envelope_is_frozen_minimal_and_fingerprint_is_unambiguous() -> None:
    assert [field.name for field in fields(PlanEnvelope)] == [
        "schema_version",
        "lane_id",
        "opportunity_id",
        "episode_id",
        "payload_fingerprint",
        "direction",
        "producer_trigger",
        "invalidation",
        "target",
        "target_source_key",
        "confirmation_time_ms",
        "visible_at_ms",
        "permission_expires_at_ms",
        "context_valid_until_ms",
    ]
    plan = PlanEnvelope(
        schema_version=SCHEMA_VERSION,
        lane_id=LaneId.TREND_CONTINUATION,
        opportunity_id="A",
        episode_id="B",
        payload_fingerprint="C",
        direction=Direction.LONG,
        producer_trigger=100.0,
        invalidation=95.0,
        target=110.0,
        target_source_key="target",
        confirmation_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        permission_expires_at_ms=et_ms(11, 40),
    )
    with pytest.raises(FrozenInstanceError):
        plan.target = 120.0  # type: ignore[misc]

    common = dict(
        lane_id=LaneId.POSITION_REVERSAL,
        opportunity_id="OP|X",
        episode_id="EP@Y",
        direction=Direction.LONG,
        producer_trigger=100.0,
        invalidation=95.0,
        target=110.0,
        confirmation_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        permission_expires_at_ms=et_ms(11, 40),
        context_valid_until_ms=et_ms(12, 0),
    )
    left = canonical_plan_fingerprint(
        **common,
        target_source_key="TARGET|X",
        source_context_key="Y",
    )
    right = canonical_plan_fingerprint(
        **common,
        target_source_key="TARGET",
        source_context_key="X|Y",
    )
    assert left.startswith(PLAN_FINGERPRINT_VERSION)
    assert right.startswith(PLAN_FINGERPRINT_VERSION)
    assert left != right


def test_lane_adapters_build_complete_distinct_envelopes() -> None:
    overlap = bar3(9, 39)
    trend_plan = OpportunityPlan(
        opportunity_id="10M-TC-L-1",
        epoch_id="10M-EPOCH-L-1",
        episode_id="10M-EP-L-1",
        direction=TrendDirection.LONG,
        confirmation_time_ms=et_ms(9, 30),
        entry_reference=100.0,
        invalidation=95.0,
        next_named_level=110.0,
        next_named_level_source=NamedLevelSource.CONFIRMED_PIVOT_10M,
        next_named_level_provenance_time_ms=et_ms(9, 0),
        risk=5.0,
        space=10.0,
        space_r=2.0,
    )
    trend = TrendAdapter.envelope_from_plan(trend_plan, overlap_bar=overlap)
    assert trend.envelope.lane_id is LaneId.TREND_CONTINUATION
    assert trend.envelope.visible_at_ms == et_ms(9, 40)
    assert trend.envelope.permission_expires_at_ms == et_ms(11, 40)
    assert trend.envelope.context_valid_until_ms is None
    assert trend.envelope.payload_fingerprint.startswith(PLAN_FINGERPRINT_VERSION)

    reversal_payload = OpportunityPayload(
        lane_id="POSITION_REVERSAL",
        opportunity_id="PR-L-1",
        episode_id="PR-EP-1",
        source_id="SOURCE",
        source_version="v1",
        source_kind="SATY_ATR_MAP_LEVEL",
        source_fingerprint="source|fingerprint",
        source_valid_until_ms=et_ms(12, 0),
        direction=ReversalDirection.LONG,
        trigger=100.0,
        invalidation=95.0,
        target=110.0,
        target_source="TARGET@v1",
        target_source_id="TARGET",
        target_source_version="v1",
        target_source_kind="SATY_ATR_MAP_LEVEL",
        target_source_fingerprint="target|fingerprint",
        target_valid_until_ms=et_ms(11, 30),
        confirmation_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        expires_at_ms=et_ms(11, 40),
        prior_atr=100.0,
        atr_source="ATR@v1",
        atr_source_kind="PREVIOUS_COMPLETED_DAILY_ATR",
        atr_source_fingerprint="atr|fingerprint",
        atr_valid_until_ms=et_ms(11, 45),
        risk=5.0,
        reward=10.0,
        space_r=2.0,
    )
    reversal = ReversalAdapter.envelope_from_payload(
        reversal_payload, overlap_bar=overlap
    )
    assert reversal.envelope.lane_id is LaneId.POSITION_REVERSAL
    assert reversal.envelope.context_valid_until_ms == et_ms(11, 30)
    assert reversal.envelope.payload_fingerprint.startswith(PLAN_FINGERPRINT_VERSION)
    assert reversal.envelope.payload_fingerprint != trend.envelope.payload_fingerprint


def test_plan_envelope_rejects_open_lane_direction_and_missing_target_identity() -> None:
    common = dict(
        schema_version=SCHEMA_VERSION,
        lane_id=LaneId.TREND_CONTINUATION,
        opportunity_id="TC-validation",
        episode_id="TC-validation-episode",
        payload_fingerprint="TC-validation-fingerprint",
        direction=Direction.LONG,
        producer_trigger=100.0,
        invalidation=95.0,
        target=110.0,
        target_source_key="target",
        confirmation_time_ms=et_ms(9, 30),
        visible_at_ms=et_ms(9, 40),
        permission_expires_at_ms=et_ms(11, 40),
    )
    with pytest.raises(ValueError, match="closed lane"):
        PlanEnvelope(**{**common, "lane_id": "TREND_CONTINUATION"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="LONG or SHORT"):
        PlanEnvelope(**{**common, "direction": 1})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="target_source_key"):
        PlanEnvelope(**{**common, "target_source_key": ""})


def test_sparse_ui_has_two_entry_markers_five_rows_and_exactly_four_entry_alerts() -> None:
    code_lines = [line.strip() for line in PINE_SOURCE.splitlines()]
    plot_lines = [line for line in code_lines if line.startswith("plot(")]
    plotshape_lines = [line for line in code_lines if line.startswith("plotshape(")]
    alert_lines = [line for line in code_lines if line.startswith("alertcondition(")]
    fill_lines = [line for line in code_lines if line.startswith("fill(")]
    assert len(plotshape_lines) == 2
    assert all('text="多入"' in line or 'text="空入"' in line for line in plotshape_lines)
    assert all("textcolor=color.rgb(5, 9, 17)" in line for line in plotshape_lines)
    assert len(alert_lines) == 4
    expected_titles = (
        "3m | 趋势续行 | 多入",
        "3m | 趋势续行 | 空入",
        "3m | 位置反转 | 多入",
        "3m | 位置反转 | 空入",
    )
    for title in expected_titles:
        assert sum(f'title="{title}"' in line for line in alert_lines) == 1
    alert_guards = (
        "bool trendLongAlert = barstate.isconfirmed and longEntryPulse",
        "bool trendShortAlert = barstate.isconfirmed and shortEntryPulse",
        "bool reversalLongAlert = barstate.isconfirmed and longEntryPulse",
        "bool reversalShortAlert = barstate.isconfirmed and shortEntryPulse",
    )
    assert all(guard in PINE_SOURCE for guard in alert_guards)
    assert len(plot_lines) + len(plotshape_lines) + len(alert_lines) + len(fill_lines) < 64
    assert "table.new(position.bottom_right, 2, 5" in PINE_SOURCE
    for row, label in enumerate(("现在做", "来源", "为什么", "保护", "目标")):
        assert f'f_card_row({row}, "{label}"' in PINE_SOURCE
    for forbidden in ("label.new", "line.new", "box.new", "strategy(", "strategy.", "alert("):
        assert forbidden not in PINE_SOURCE
    for terminal_marker in ('text="多失"', 'text="空失"', 'text="多达"', 'text="空达"'):
        assert terminal_marker not in PINE_SOURCE


def test_entry_card_distinguishes_pulse_from_retained_monitoring_and_forbids_chasing() -> None:
    for text in (
        'longEntryPulse ? "本根多头确认"',
        'shortEntryPulse ? "本根空头确认"',
        '"多头计划监控｜勿追"',
        '"空头计划监控｜勿追"',
        'string GO_REASON_OWNER_RETAINED = "入场条件已触发｜仅监控原保护/目标"',
    ):
        assert text in PINE_SOURCE
    assert '"多入触发"' not in PINE_SOURCE
    assert '"空入触发"' not in PINE_SOURCE


def test_terminal_card_snapshot_is_ephemeral_and_next_no_owner_surface_is_blank() -> None:
    for forbidden in (
        "goLastEvent",
        "goLastLane",
        "goLastDirection",
        "goLastStop",
        "goLastTarget",
        "goLastEntryR",
    ):
        assert forbidden not in PINE_SOURCE
    for required in (
        "int goEventLane = GO_LANE_NONE",
        "float goEventStop = na",
        "float goEventTarget = na",
        "float goEventEntryR = na",
        "goLastReason := not na(goOwner) ? goReason : GO_REASON_WAIT_10M",
        "int cardLane = not na(goOwner) ? goOwner.laneId : goEventLane",
        "float cardStop = not na(goOwner) ? goOwner.invalidation : goEventStop",
        "float cardTarget = not na(goOwner) ? goOwner.target : goEventTarget",
        "float cardRemainingR = not na(goOwner) ? f_remaining_r(goOwner, close) : goEventEntryR",
        'string cardTargetText = f_price(cardTarget) + "｜剩余 "',
    ):
        assert required in PINE_SOURCE
    adoption = PINE_SOURCE.index("goOwner := winner")
    adoption_tail = PINE_SOURCE[adoption : adoption + 700]
    assert "goEntryPrice := na" in adoption_tail
    assert "goEntryR := na" in adoption_tail


def test_alert_messages_are_exact_self_explanatory_entry_only_contract() -> None:
    expected = {
        "3m | 趋势续行 | 多入": '标的={{exchange}}:{{ticker}}｜周期={{interval}}｜趋势续行｜多头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单',
        "3m | 趋势续行 | 空入": '标的={{exchange}}:{{ticker}}｜周期={{interval}}｜趋势续行｜空头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单',
        "3m | 位置反转 | 多入": '标的={{exchange}}:{{ticker}}｜周期={{interval}}｜位置反转｜多头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单',
        "3m | 位置反转 | 空入": '标的={{exchange}}:{{ticker}}｜周期={{interval}}｜位置反转｜空头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单',
    }
    alert_lines = [
        line.strip()
        for line in PINE_SOURCE.splitlines()
        if line.strip().startswith("alertcondition(")
    ]
    for title, message in expected.items():
        line = next(line for line in alert_lines if f'title="{title}"' in line)
        assert f"message='{message}'" in line
    for forbidden in (
        "GO_3M_BAR_MS",
        "10m确认ms",
        "3m确认ms",
        "观察入场",
    ):
        assert forbidden not in PINE_SOURCE


def test_trader_visible_reasons_use_intraday_chinese_not_engineering_terms() -> None:
    reason_surface = "\n".join(
        line.strip()
        for line in PINE_SOURCE.splitlines()
        if line.strip().startswith("string GO_REASON_")
    )
    required = (
        "本根不追",
        "等后续收盘确认",
        "等待首次收盘穿越触发价",
        "有效时间已过",
        "首次确认未通过",
        "同一机会数据不一致｜停止提醒",
        "图表/时间/数据异常｜停止提醒",
    )
    assert all(text in reason_surface for text in required)
    for forbidden in (
        "later confirmed",
        "confirmed close cross",
        "permission/context",
        "timing gate",
        "base ID",
        "fingerprint",
        "fail closed",
    ):
        assert forbidden not in reason_surface


def test_generated_pine_has_no_duplicate_top_level_declarations() -> None:
    declarations = _top_level_declarations(PINE_SOURCE)
    duplicates = sorted({name for name in declarations if declarations.count(name) > 1})
    assert duplicates == []


def test_synthetic_july31_positive_name_was_removed() -> None:
    fixture_source = (
        ROOT / "research/tests/fixture_phase1_10m_position_reversal.py"
    ).read_text(encoding="utf-8")
    test_source = (
        ROOT / "research/tests/test_phase1_10m_position_reversal_positive.py"
    ).read_text(encoding="utf-8")
    assert "july31_mandatory_replay" not in fixture_source + test_source
    assert "synthetic_dual_ready_replay" in fixture_source + test_source
    assert "not the accepted" in fixture_source
