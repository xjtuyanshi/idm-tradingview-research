#!/usr/bin/env python3
"""Generate the Phase 1 Pine v6 3m global-owner host.

The host consumes one previous-completed 10m raw superset transport, runs the
accepted TREND_CONTINUATION and POSITION_REVERSAL producer cores independently,
adapts complete immutable PlanEnvelope candidates, and exposes one OwnerManager
surface.  The existing standalone generators remain the sole producer truths:
this generator imports the trend canonical block and token-namespaces exact
reversal canonical fragments rather than copying or regex-patching generated
Pine.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.generate_phase1_10m_position_reversal_pine_v1 import (
    embedded_source_fragments,
)
from research.generate_phase1_10m_primary_pine_r3 import CANONICAL_BLOCK as TREND_CORE
from research.phase1_3m_global_owner_oracle import (
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
)

DEFAULT_OUTPUT = ROOT / "idm_phase1_3m_global_owner_v1.pine"
EXPECTED_FROZEN_PINE_HASHES = {
    "idm_phase1_10m_position_reversal_v1.pine": "5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421",
    "idm_phase1_10m_primary_opportunity_v3.pine": "aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2",
    "idm_phase1_3m_opportunity_timing_v3.pine": "f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e",
}


def _valid_identifier(value: str) -> bool:
    return bool(value) and (value[0].isalpha() or value[0] == "_") and all(
        character.isalnum() or character == "_" for character in value
    )


def _top_level_symbols(source: str) -> set[str]:
    """Collect exact top-level Pine declarations without regular expressions."""

    symbols: set[str] = set()
    excluded_starts = (
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
    )
    for raw_line in source.splitlines():
        if not raw_line or raw_line[0].isspace():
            continue
        line = raw_line.strip()
        if not line or line.startswith(excluded_starts):
            continue
        if "=>" in line and "(" in line:
            before = line.split("(", 1)[0].strip()
            name = before.split()[-1]
            if _valid_identifier(name):
                symbols.add(name)
            continue
        if "=" not in line or ":=" in line:
            continue
        left = line.split("=", 1)[0].strip()
        if not left:
            continue
        name = left.split()[-1]
        if _valid_identifier(name):
            symbols.add(name)
    return symbols


def _input_names(source: str) -> list[str]:
    names: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or "input." not in line or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip().split()[-1]
        if not _valid_identifier(name):
            raise RuntimeError(f"invalid canonical input declaration: {raw_line}")
        names.append(name)
    if not names:
        raise RuntimeError("canonical reversal data-input fragment is empty")
    return names


def _replace_code_fragments(source: str, replacements: dict[str, str]) -> str:
    """Replace exact code fragments while preserving strings and comments."""

    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            output.append(character)
            if character == "\\" and index + 1 < len(source):
                index += 1
                output.append(source[index])
            elif character == quote:
                quote = None
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index)
            if newline < 0:
                output.append(source[index:])
                break
            output.append(source[index:newline])
            index = newline
            continue
        if character in ('"', "'"):
            quote = character
            output.append(character)
            index += 1
            continue
        matched = False
        for old, new in ordered:
            if source.startswith(old, index):
                output.append(new)
                index += len(old)
                matched = True
                break
        if matched:
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _transform_identifiers(source: str, mapping: dict[str, str]) -> str:
    """Token-aware Pine identifier mapping; strings/comments remain byte-exact."""

    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            output.append(character)
            if character == "\\" and index + 1 < len(source):
                index += 1
                output.append(source[index])
            elif character == quote:
                quote = None
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index)
            if newline < 0:
                output.append(source[index:])
                break
            output.append(source[index:newline])
            index = newline
            continue
        if character in ('"', "'"):
            quote = character
            output.append(character)
            index += 1
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] == "_"
            ):
                end += 1
            token = source[index:end]
            output.append(mapping.get(token, token))
            index = end
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _render_reversal_adapter() -> tuple[str, str, list[str], str]:
    constants, data_inputs, producer_core = embedded_source_fragments()
    input_names = _input_names(data_inputs)
    top_level = _top_level_symbols(constants + "\n" + producer_core)
    namespace = {name: f"r_{name}" for name in top_level}

    input_block = _transform_identifiers(data_inputs, namespace)
    core_mapping = dict(namespace)
    core_mapping.update({name: f"r_{name}" for name in input_names})
    core_mapping.update(
        {
            "time": "e_time",
            "time_close": "e_timeClose",
            "open": "e_open",
            "high": "e_high",
            "low": "e_low",
            "close": "e_close",
        }
    )
    constants_block = _transform_identifiers(constants, namespace)
    prepared_core = _replace_code_fragments(
        producer_core,
        {
            "barstate.isconfirmed": "r_processNow",
            "timeframe.period": '"10"',
        },
    )
    core_block = _transform_identifiers(prepared_core, core_mapping)
    return constants_block.rstrip(), input_block.rstrip(), input_names, core_block.rstrip()


def _request_components(input_names: list[str]) -> tuple[list[str], list[str]]:
    lhs = [
        "e_time",
        "e_timeClose",
        "e_dayKey",
        "e_open",
        "e_high",
        "e_low",
        "e_close",
        "e_ema5",
        "e_ema12",
        "e_ema21",
        "e_ema48",
        "e_newPivotHigh",
        "e_newPivotHighTime",
        "e_newPivotLow",
        "e_newPivotLowTime",
    ] + [f"r_{name}" for name in input_names]
    expressions = [
        "time[1]",
        "time_close[1]",
        'time("D", "0000-2359", "America/New_York")[1]',
        "open[1]",
        "high[1]",
        "low[1]",
        "close[1]",
        "ta.ema(hl2, 5)[1]",
        "ta.ema(hl2, 12)[1]",
        "ta.ema(close, 21)[1]",
        "ta.ema(close, 48)[1]",
        "f_strict_pivot_high_2_2()[1]",
        "f_strict_pivot_high_time_2_2()[1]",
        "f_strict_pivot_low_2_2()[1]",
        "f_strict_pivot_low_time_2_2()[1]",
    ] + [f"{name}[1]" for name in input_names]
    if len(lhs) != len(expressions):
        raise RuntimeError("HTF request transport width mismatch")
    if len(lhs) > 127:
        raise RuntimeError(f"Pine tuple width exceeds 127: {len(lhs)}")
    return lhs, expressions


def _request_transport(input_names: list[str]) -> str:
    lhs, expressions = _request_components(input_names)
    return (
        "["
        + ", ".join(lhs)
        + "] = request.security(syminfo.tickerid, \"10\", ["
        + ", ".join(expressions)
        + "], gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)"
    )


GLOBAL_OWNER_TAIL = dedent(
    r'''
    // GLOBAL_OWNER_CANONICAL_BEGIN phase1-3m-global-owner-1.0
    int GO_LANE_NONE = 0
    int GO_LANE_TREND = 1
    int GO_LANE_REVERSAL = 2
    int GO_DIRECTION_SHORT = -1
    int GO_DIRECTION_NONE = 0
    int GO_DIRECTION_LONG = 1

    int GO_WAIT_10M = 0
    int GO_WAIT_PULLBACK = 1
    int GO_WAIT_TRIGGER = 2
    int GO_WAIT_IMMEDIATE_CONFIRM = 3
    int GO_WAIT_FRESH_CROSS = 4
    int GO_ENTERED = 5

    int GO_EVENT_NONE = 0
    int GO_EVENT_LONG_ENTRY = 1
    int GO_EVENT_SHORT_ENTRY = -1
    int GO_EVENT_INVALIDATED = 2
    int GO_EVENT_TARGET_REACHED = 3
    int GO_EVENT_EXPIRED = 4
    int GO_EVENT_MISSED = 5
    int GO_EVENT_CONFLICT = 6
    int GO_EVENT_DATA_RESET = 7

    int GO_TERM_NONE = 0
    int GO_TERM_INVALIDATED = 1
    int GO_TERM_TARGET_REACHED = 2
    int GO_TERM_EXPIRED = 3
    int GO_TERM_ACTIVE_NONE = 4
    int GO_TERM_PERMISSION_EXPIRED = 5
    int GO_TERM_CONTEXT_EXPIRED = 6
    int GO_TERM_SOURCE_INVALID = 7
    int GO_TERM_IDENTITY_DRIFT = 8
    int GO_TERM_SUPPRESSED = 9
    int GO_TERM_CONTEXT_RESET = 10
    int GO_TERM_DATA_RESET = 11

    string GO_REASON_WAIT_10M = "等待 10m 可用计划"
    string GO_REASON_NEW_TREND = "采用 10m 趋势续行｜本根不追"
    string GO_REASON_NEW_REVERSAL = "采用 10m 位置反转｜本根不追"
    string GO_REASON_WAIT_PULLBACK = "等待 3m 回踩 5/12 云"
    string GO_REASON_PULLBACK_FROZEN = "已记录 3m 触发价｜等后续收盘确认"
    string GO_REASON_WAIT_TRIGGER = "等后续收盘确认"
    string GO_REASON_WAIT_IMMEDIATE = "仅看紧接下一根 3m 收盘"
    string GO_REASON_WAIT_CROSS = "等待首次收盘穿越触发价"
    string GO_REASON_ENTRY = "本根 3m 收盘条件确认｜不是成交"
    string GO_REASON_OWNER_RETAINED = "入场条件已触发｜仅监控原保护/目标"
    string GO_REASON_SPACE = "剩余空间不足 1R｜本计划错过"
    string GO_REASON_MISSED = "首次确认未通过｜本计划错过"
    string GO_REASON_EXPIRED = "有效时间已过｜本计划结束"
    string GO_REASON_INVALIDATED = "冻结保护已触发｜本计划结束"
    string GO_REASON_TARGET = "冻结目标已触达｜本计划结束"
    string GO_REASON_CONFLICT = "新旧方向冲突｜本根不做"
    string GO_REASON_COLLISION = "同一机会数据不一致｜停止提醒"
    string GO_REASON_SUPPRESSED = "该机会已处理或被阻断｜不再提醒"
    string GO_REASON_RESET = "图表/时间/数据异常｜停止提醒"

    type PlanEnvelope
        string schemaVersion
        int laneId
        string opportunityId
        string episodeId
        string payloadFingerprint
        int direction
        float producerTrigger
        float invalidation
        float target
        string targetSourceKey
        int confirmationTimeMs
        int visibleAtMs
        int permissionExpiresAtMs
        int contextValidUntilMs

    f_lp(string value) =>
        str.tostring(str.length(value)) + ":" + value

    f_scaled_number(float value) =>
        na(value) ? "N" : str.tostring(int(math.round(value * 10000000000.0)))

    f_plan_fingerprint(int laneId, string opportunityId, string episodeId, int direction, float trigger, float invalidation, float target, string targetSourceKey, int confirmationTimeMs, int visibleAtMs, int permissionExpiresAtMs, int contextValidUntilMs, string sourceContextKey) =>
        "GOFP1" + f_lp(str.tostring(laneId)) + f_lp(opportunityId) + f_lp(episodeId) + f_lp(str.tostring(direction)) + f_lp(f_scaled_number(trigger)) + f_lp(f_scaled_number(invalidation)) + f_lp(f_scaled_number(target)) + f_lp(targetSourceKey) + f_lp(str.tostring(confirmationTimeMs)) + f_lp(str.tostring(visibleAtMs)) + f_lp(str.tostring(permissionExpiresAtMs)) + f_lp(na(contextValidUntilMs) ? "N" : str.tostring(contextValidUntilMs)) + f_lp(sourceContextKey)

    f_full_key(PlanEnvelope plan) =>
        f_lp(str.tostring(plan.laneId)) + f_lp(plan.opportunityId) + f_lp(plan.payloadFingerprint)

    f_base_key(PlanEnvelope plan) =>
        f_lp(str.tostring(plan.laneId)) + f_lp(plan.opportunityId)

    f_array_contains(array<string> values, string value) =>
        bool found = false
        if array.size(values) > 0
            for index = 0 to array.size(values) - 1
                found := found or array.get(values, index) == value
        found

    f_suppress(array<string> values, PlanEnvelope plan) =>
        string key = f_full_key(plan)
        if not f_array_contains(values, key)
            array.push(values, key)

    // Return 1 for accepted existing/new identity, 0 for tombstoned/collision.
    // The registry and tombstone arrays persist across owner/global resets.
    f_register_identity(PlanEnvelope plan, array<string> baseKeys, array<string> baseFingerprints, array<string> tombstones, array<string> suppressed) =>
        string baseKey = f_base_key(plan)
        int result = 1
        if f_array_contains(tombstones, baseKey)
            f_suppress(suppressed, plan)
            result := 0
        else
            int priorIndex = array.indexof(baseKeys, baseKey)
            if priorIndex < 0
                array.push(baseKeys, baseKey)
                array.push(baseFingerprints, plan.payloadFingerprint)
            else
                string priorFingerprint = array.get(baseFingerprints, priorIndex)
                if priorFingerprint != plan.payloadFingerprint
                    if not f_array_contains(tombstones, baseKey)
                        array.push(tombstones, baseKey)
                    string priorFullKey = f_lp(str.tostring(plan.laneId)) + f_lp(plan.opportunityId) + f_lp(priorFingerprint)
                    if not f_array_contains(suppressed, priorFullKey)
                        array.push(suppressed, priorFullKey)
                    f_suppress(suppressed, plan)
                    result := 0
        result

    f_stop_hit(PlanEnvelope plan, float barHigh, float barLow, float barClose) =>
        plan.laneId == GO_LANE_TREND ? (plan.direction == GO_DIRECTION_LONG ? barClose < plan.invalidation : barClose > plan.invalidation) : (plan.direction == GO_DIRECTION_LONG ? barLow <= plan.invalidation : barHigh >= plan.invalidation)

    f_target_hit(PlanEnvelope plan, float barHigh, float barLow) =>
        plan.direction == GO_DIRECTION_LONG ? barHigh >= plan.target : barLow <= plan.target

    // 1=stop, 2=target, 0=still alive. Stop is always first.
    f_terminal_code(PlanEnvelope plan, float barHigh, float barLow, float barClose) =>
        f_stop_hit(plan, barHigh, barLow, barClose) ? 1 : f_target_hit(plan, barHigh, barLow) ? 2 : 0

    f_remaining_r(PlanEnvelope plan, float observedClose) =>
        float risk = plan.direction == GO_DIRECTION_LONG ? observedClose - plan.invalidation : plan.invalidation - observedClose
        float reward = plan.direction == GO_DIRECTION_LONG ? plan.target - observedClose : observedClose - plan.target
        risk > 0 and reward > 0 and not na(risk) and not na(reward) ? reward / risk : na

    f_exact_terminal_matches(PlanEnvelope plan, int terminalLane, string terminalId, string terminalFingerprint) =>
        terminalLane == plan.laneId and terminalId == plan.opportunityId and terminalFingerprint == plan.payloadFingerprint

    f_price(float value) =>
        na(value) ? "—" : str.tostring(value, format.mintick)

    f_time(int value) =>
        na(value) ? "—" : str.format_time(value, "MM-dd HH:mm", "America/New_York")

    string trendOpportunityId = e_opportunityDirection == DIRECTION_LONG ? "10M-TC-L-" + str.tostring(e_opportunityTime) : "10M-TC-S-" + str.tostring(e_opportunityTime)
    string trendEpochId = e_opportunityDirection == DIRECTION_LONG ? "10M-EPOCH-L-" + str.tostring(e_epochStartTime) : "10M-EPOCH-S-" + str.tostring(e_epochStartTime)
    string trendEpisodeId = e_opportunityDirection == DIRECTION_LONG ? "10M-EP-L-" + str.tostring(e_episodeStartTime) : "10M-EP-S-" + str.tostring(e_episodeStartTime)
    string trendTargetSourceKey = f_source_text(e_nextNamedLevelSource) + "@" + (na(e_nextNamedLevelProvenanceTime) ? "N" : str.tostring(e_nextNamedLevelProvenanceTime))
    string trendSourceContextKey = f_lp(trendEpochId) + f_lp(trendEpisodeId) + f_lp(trendTargetSourceKey)
    int trendVisibleAt = e_opportunityTime + PRIMARY_INTERVAL_MS
    int trendPermissionExpires = trendVisibleAt + MAX_ACTIVE_BARS * PRIMARY_INTERVAL_MS
    string trendFingerprint = f_plan_fingerprint(GO_LANE_TREND, trendOpportunityId, trendEpisodeId, e_opportunityDirection, e_entryReference, e_invalidation, e_nextNamedLevel, trendTargetSourceKey, e_opportunityTime, trendVisibleAt, trendPermissionExpires, na, trendSourceContextKey)
    bool trendCandidatePulse = go_processPayload and e_opportunityActive and (e_eventPulse == EVENT_MAIN_LONG or e_eventPulse == EVENT_MAIN_SHORT) and not na(e_nextNamedLevel)
    PlanEnvelope trendCandidate = trendCandidatePulse ? PlanEnvelope.new(GLOBAL_SCHEMA_VERSION, GO_LANE_TREND, trendOpportunityId, trendEpisodeId, trendFingerprint, e_opportunityDirection, e_entryReference, e_invalidation, e_nextNamedLevel, trendTargetSourceKey, e_opportunityTime, trendVisibleAt, trendPermissionExpires, na) : na

    int reversalDirection = r_latestDirection == r_ROLE_SUPPORT ? GO_DIRECTION_LONG : r_latestDirection == r_ROLE_RESISTANCE ? GO_DIRECTION_SHORT : GO_DIRECTION_NONE
    int reversalContextValidUntil = math.min(r_episodeValidUntil, math.min(r_frozenTargetValidUntil, r_frozenAtrValidUntil))
    string reversalSourceContextKey = f_lp(r_latestSourceEffectiveKey) + f_lp(r_latestTargetEffectiveKey) + f_lp(r_latestAtrEffectiveKey)
    string reversalFingerprint = f_plan_fingerprint(GO_LANE_REVERSAL, r_latestOpportunityId, r_latestEpisodeId, reversalDirection, r_latestTrigger, r_latestInvalidation, r_latestTarget, r_latestTargetEffectiveKey, r_latestConfirmationTime, r_latestVisibleAt, r_latestExpiresAt, reversalContextValidUntil, reversalSourceContextKey)
    bool reversalCandidatePulse = go_processPayload and (r_longReadyPulse or r_shortReadyPulse)
    PlanEnvelope reversalCandidate = reversalCandidatePulse ? PlanEnvelope.new(GLOBAL_SCHEMA_VERSION, GO_LANE_REVERSAL, r_latestOpportunityId, r_latestEpisodeId, reversalFingerprint, reversalDirection, r_latestTrigger, r_latestInvalidation, r_latestTarget, r_latestTargetEffectiveKey, r_latestConfirmationTime, r_latestVisibleAt, r_latestExpiresAt, reversalContextValidUntil) : na

    // Adapter terminal identity is frozen only when the producer publishes a
    // candidate. Producer state may clear epoch/context fields on a later terminal
    // bar; terminal binding must never rebuild identity from that mutated state.
    var string trendPublishedOpportunityId = ""
    var string trendPublishedFingerprint = ""
    if trendCandidatePulse
        trendPublishedOpportunityId := trendOpportunityId
        trendPublishedFingerprint := trendFingerprint

    int trendTerminalKind = e_eventPulse == EVENT_INVALIDATED ? GO_TERM_INVALIDATED : e_eventPulse == EVENT_TARGET_REACHED ? GO_TERM_TARGET_REACHED : e_eventPulse == EVENT_EXPIRED ? GO_TERM_EXPIRED : e_eventPulse == EVENT_CONTEXT_RESET ? GO_TERM_CONTEXT_RESET : e_eventPulse == EVENT_DATA_RESET ? GO_TERM_DATA_RESET : GO_TERM_NONE
    bool trendTerminalPulse = go_processPayload and trendTerminalKind != GO_TERM_NONE and str.length(trendPublishedOpportunityId) > 0 and str.length(trendPublishedFingerprint) > 0
    int trendTerminalLane = GO_LANE_TREND
    string trendTerminalId = trendPublishedOpportunityId
    string trendTerminalFingerprint = trendPublishedFingerprint

    var string reversalPublishedOpportunityId = ""
    var string reversalPublishedFingerprint = ""
    if reversalCandidatePulse
        reversalPublishedOpportunityId := r_latestOpportunityId
        reversalPublishedFingerprint := reversalFingerprint

    bool reversalPlanStatusChanged = go_processPayload and r_latestPlanStatus != r_latestPlanStatus[1]
    int reversalTerminalKind = r_latestPlanStatus == r_PLAN_INVALIDATED ? GO_TERM_INVALIDATED : r_latestPlanStatus == r_PLAN_TARGET_REACHED ? GO_TERM_TARGET_REACHED : r_latestPlanStatus == r_PLAN_EXPIRED ? GO_TERM_EXPIRED : r_latestPlanStatus == r_PLAN_SUPPRESSED ? GO_TERM_SUPPRESSED : GO_TERM_NONE
    bool reversalTerminalPulse = reversalPlanStatusChanged and reversalTerminalKind != GO_TERM_NONE and str.length(reversalPublishedOpportunityId) > 0 and str.length(reversalPublishedFingerprint) > 0
    int reversalTerminalLane = GO_LANE_REVERSAL
    string reversalTerminalId = reversalPublishedOpportunityId
    string reversalTerminalFingerprint = reversalPublishedFingerprint

    float fast3Ema5 = ta.ema(hl2, 5)
    float fast3Ema12 = ta.ema(hl2, 12)
    float fast3Upper = math.max(fast3Ema5, fast3Ema12)
    float fast3Lower = math.min(fast3Ema5, fast3Ema12)
    bool goCurrentDataOk = not na(open) and not na(high) and not na(low) and not na(close) and not na(fast3Ema5) and not na(fast3Ema12) and high >= low and high >= math.max(open, close) and low <= math.min(open, close)

    var PlanEnvelope goOwner = na
    var int goState = GO_WAIT_10M
    var int goAdoptionOpenMs = na
    var float goAdoptionHigh = na
    var float goAdoptionLow = na
    var float goFrozenTrigger = na
    var int goTrendTriggerAge = 0
    var float goPreviousConfirmedClose = na
    var float goEntryPrice = na
    var float goEntryR = na
    var string goLastReason = GO_REASON_WAIT_10M
    var array<string> goSuppressed = array.new_string(0)
    var array<string> goBaseKeys = array.new_string(0)
    var array<string> goBaseFingerprints = array.new_string(0)
    var array<string> goCollisionTombstones = array.new_string(0)

    int goEventPulse = GO_EVENT_NONE
    float goMarkerPrice = na
    int goEventLane = GO_LANE_NONE
    float goEventStop = na
    float goEventTarget = na
    float goEventEntryR = na
    bool goBarDone = false
    string goReason = not na(goOwner) ? (goState == GO_ENTERED ? GO_REASON_OWNER_RETAINED : goLastReason) : GO_REASON_WAIT_10M

    bool hasTrendCandidate = trendCandidatePulse and not na(trendCandidate)
    bool hasReversalCandidate = reversalCandidatePulse and not na(reversalCandidate)
    int trendRegistration = hasTrendCandidate ? f_register_identity(trendCandidate, goBaseKeys, goBaseFingerprints, goCollisionTombstones, goSuppressed) : 1
    int reversalRegistration = hasReversalCandidate ? f_register_identity(reversalCandidate, goBaseKeys, goBaseFingerprints, goCollisionTombstones, goSuppressed) : 1
    bool collisionOnOwner = not na(goOwner) and ((hasTrendCandidate and trendRegistration == 0 and f_base_key(trendCandidate) == f_base_key(goOwner)) or (hasReversalCandidate and reversalRegistration == 0 and f_base_key(reversalCandidate) == f_base_key(goOwner)))

    bool globalReset = not goHostContractOk or not goCurrentDataOk or goBackward3m or goGap3m or goRawReset
    if barstate.isconfirmed
        if globalReset
            // A reset breaks the association between a later high[1]/low[1]/close[1]
            // and the chart bar that actually crossed an older HTF visible_at.
            // The monotonic cutoff permanently rejects those stale payloads.
            int goResetBoundaryMs = na(goLast3mTime) ? time : math.max(time, goLast3mTime)
            goResetVisibleCutoffMs := na(goResetVisibleCutoffMs) ? goResetBoundaryMs : math.max(goResetVisibleCutoffMs, goResetBoundaryMs)
            if not na(goOwner)
                f_suppress(goSuppressed, goOwner)
                goEventLane := goOwner.laneId
                goEventStop := goOwner.invalidation
                goEventTarget := goOwner.target
                goEventEntryR := goEntryR
            if hasTrendCandidate
                f_suppress(goSuppressed, trendCandidate)
            if hasReversalCandidate
                f_suppress(goSuppressed, reversalCandidate)
            goOwner := na
            goState := GO_WAIT_10M
            goEntryPrice := na
            goEntryR := na
            goAdoptionOpenMs := na
            goAdoptionHigh := na
            goAdoptionLow := na
            goFrozenTrigger := na
            goTrendTriggerAge := 0
            goPreviousConfirmedClose := na
            goEventPulse := GO_EVENT_DATA_RESET
            goReason := GO_REASON_RESET
            goBarDone := true
            goLast3mTime := goGap3m ? time : na
        else if goDuplicate3m
            goBarDone := true
        else
            goLast3mTime := time

            // Existing owner price terminal always wins; stop precedes target.
            if not na(goOwner) and f_stop_hit(goOwner, high, low, close)
                f_suppress(goSuppressed, goOwner)
                if hasTrendCandidate
                    f_suppress(goSuppressed, trendCandidate)
                if hasReversalCandidate
                    f_suppress(goSuppressed, reversalCandidate)
                goEventLane := goOwner.laneId
                goEventStop := goOwner.invalidation
                goEventTarget := goOwner.target
                goEventEntryR := goEntryR
                goMarkerPrice := goOwner.invalidation
                goOwner := na
                goState := GO_WAIT_10M
                goEntryPrice := na
                goEntryR := na
                goEventPulse := GO_EVENT_INVALIDATED
                goReason := GO_REASON_INVALIDATED
                goBarDone := true
            else if not na(goOwner) and f_target_hit(goOwner, high, low)
                f_suppress(goSuppressed, goOwner)
                if hasTrendCandidate
                    f_suppress(goSuppressed, trendCandidate)
                if hasReversalCandidate
                    f_suppress(goSuppressed, reversalCandidate)
                goEventLane := goOwner.laneId
                goEventStop := goOwner.invalidation
                goEventTarget := goOwner.target
                goEventEntryR := goEntryR
                goMarkerPrice := goOwner.target
                goOwner := na
                goState := GO_WAIT_10M
                goEntryPrice := na
                goEntryR := na
                goEventPulse := GO_EVENT_TARGET_REACHED
                goReason := GO_REASON_TARGET
                goBarDone := true

            bool exactTrendTerminal = not na(goOwner) and trendTerminalPulse and f_exact_terminal_matches(goOwner, trendTerminalLane, trendTerminalId, trendTerminalFingerprint)
            bool exactReversalTerminal = not na(goOwner) and reversalTerminalPulse and f_exact_terminal_matches(goOwner, reversalTerminalLane, reversalTerminalId, reversalTerminalFingerprint)
            bool exactInvalidated = (exactTrendTerminal and trendTerminalKind == GO_TERM_INVALIDATED) or (exactReversalTerminal and reversalTerminalKind == GO_TERM_INVALIDATED)
            bool exactTarget = (exactTrendTerminal and trendTerminalKind == GO_TERM_TARGET_REACHED) or (exactReversalTerminal and reversalTerminalKind == GO_TERM_TARGET_REACHED)
            int exactOtherKind = exactTrendTerminal ? trendTerminalKind : exactReversalTerminal ? reversalTerminalKind : GO_TERM_NONE

            if not goBarDone and not na(goOwner) and exactInvalidated
                f_suppress(goSuppressed, goOwner)
                if hasTrendCandidate
                    f_suppress(goSuppressed, trendCandidate)
                if hasReversalCandidate
                    f_suppress(goSuppressed, reversalCandidate)
                goEventLane := goOwner.laneId
                goEventStop := goOwner.invalidation
                goEventTarget := goOwner.target
                goEventEntryR := goEntryR
                goMarkerPrice := goOwner.invalidation
                goOwner := na
                goState := GO_WAIT_10M
                goEntryPrice := na
                goEntryR := na
                goEventPulse := GO_EVENT_INVALIDATED
                goReason := GO_REASON_INVALIDATED
                goBarDone := true
            else if not goBarDone and not na(goOwner) and exactTarget
                f_suppress(goSuppressed, goOwner)
                if hasTrendCandidate
                    f_suppress(goSuppressed, trendCandidate)
                if hasReversalCandidate
                    f_suppress(goSuppressed, reversalCandidate)
                goEventLane := goOwner.laneId
                goEventStop := goOwner.invalidation
                goEventTarget := goOwner.target
                goEventEntryR := goEntryR
                goMarkerPrice := goOwner.target
                goOwner := na
                goState := GO_WAIT_10M
                goEntryPrice := na
                goEntryR := na
                goEventPulse := GO_EVENT_TARGET_REACHED
                goReason := GO_REASON_TARGET
                goBarDone := true

            // Entered owner ignores every producer event except exact invalidated/target.
            if not goBarDone and not na(goOwner) and goState == GO_ENTERED
                if hasTrendCandidate
                    f_suppress(goSuppressed, trendCandidate)
                if hasReversalCandidate
                    f_suppress(goSuppressed, reversalCandidate)
                goReason := GO_REASON_OWNER_RETAINED
                goBarDone := true

            if not goBarDone and not na(goOwner)
                bool exactUnenteredEnding = exactOtherKind == GO_TERM_EXPIRED or exactOtherKind == GO_TERM_ACTIVE_NONE or exactOtherKind == GO_TERM_PERMISSION_EXPIRED or exactOtherKind == GO_TERM_CONTEXT_EXPIRED or exactOtherKind == GO_TERM_SOURCE_INVALID or exactOtherKind == GO_TERM_IDENTITY_DRIFT or exactOtherKind == GO_TERM_SUPPRESSED or exactOtherKind == GO_TERM_CONTEXT_RESET or exactOtherKind == GO_TERM_DATA_RESET
                bool permissionExpired = time >= goOwner.permissionExpiresAtMs
                bool contextExpired = not na(goOwner.contextValidUntilMs) and time_close >= goOwner.contextValidUntilMs
                if collisionOnOwner or f_array_contains(goCollisionTombstones, f_base_key(goOwner))
                    f_suppress(goSuppressed, goOwner)
                    if hasTrendCandidate
                        f_suppress(goSuppressed, trendCandidate)
                    if hasReversalCandidate
                        f_suppress(goSuppressed, reversalCandidate)
                    goEventLane := goOwner.laneId
                    goEventStop := goOwner.invalidation
                    goEventTarget := goOwner.target
                    goEventEntryR := goEntryR
                    goOwner := na
                    goState := GO_WAIT_10M
                    goEntryPrice := na
                    goEntryR := na
                    goEventPulse := GO_EVENT_MISSED
                    goReason := GO_REASON_COLLISION
                    goBarDone := true
                else if exactUnenteredEnding or permissionExpired or contextExpired
                    f_suppress(goSuppressed, goOwner)
                    if hasTrendCandidate
                        f_suppress(goSuppressed, trendCandidate)
                    if hasReversalCandidate
                        f_suppress(goSuppressed, reversalCandidate)
                    goEventLane := goOwner.laneId
                    goEventStop := goOwner.invalidation
                    goEventTarget := goOwner.target
                    goEventEntryR := goEntryR
                    goOwner := na
                    goState := GO_WAIT_10M
                    goEntryPrice := na
                    goEntryR := na
                    goEventPulse := GO_EVENT_EXPIRED
                    goReason := GO_REASON_EXPIRED
                    goBarDone := true
                else
                    // A new, still-eligible opposite plan conflicts with an
                    // unentered owner before the old timing branch can enter.
                    bool laterTrendOppositeUsable = hasTrendCandidate and trendRegistration == 1 and trendCandidate.direction != goOwner.direction and not f_array_contains(goSuppressed, f_full_key(trendCandidate)) and (na(goResetVisibleCutoffMs) or trendCandidate.visibleAtMs > goResetVisibleCutoffMs) and trendCandidate.visibleAtMs <= time and time < trendCandidate.permissionExpiresAtMs and (na(trendCandidate.contextValidUntilMs) or time_close < trendCandidate.contextValidUntilMs)
                    bool laterReversalOppositeUsable = hasReversalCandidate and reversalRegistration == 1 and reversalCandidate.direction != goOwner.direction and not f_array_contains(goSuppressed, f_full_key(reversalCandidate)) and (na(goResetVisibleCutoffMs) or reversalCandidate.visibleAtMs > goResetVisibleCutoffMs) and reversalCandidate.visibleAtMs <= time and time < reversalCandidate.permissionExpiresAtMs and (na(reversalCandidate.contextValidUntilMs) or time_close < reversalCandidate.contextValidUntilMs)
                    bool laterTrendPreStop = laterTrendOppositeUsable and (f_stop_hit(trendCandidate, high[1], low[1], close[1]) or f_stop_hit(trendCandidate, high, low, close))
                    bool laterTrendPreTarget = laterTrendOppositeUsable and not laterTrendPreStop and (f_target_hit(trendCandidate, high[1], low[1]) or f_target_hit(trendCandidate, high, low))
                    bool laterReversalPreStop = laterReversalOppositeUsable and (f_stop_hit(reversalCandidate, high[1], low[1], close[1]) or f_stop_hit(reversalCandidate, high, low, close))
                    bool laterReversalPreTarget = laterReversalOppositeUsable and not laterReversalPreStop and (f_target_hit(reversalCandidate, high[1], low[1]) or f_target_hit(reversalCandidate, high, low))
                    if laterTrendPreStop or laterTrendPreTarget
                        f_suppress(goSuppressed, trendCandidate)
                        laterTrendOppositeUsable := false
                    if laterReversalPreStop or laterReversalPreTarget
                        f_suppress(goSuppressed, reversalCandidate)
                        laterReversalOppositeUsable := false

                    // All newly seen candidates remain no-queue/no-replacement.
                    if hasTrendCandidate
                        f_suppress(goSuppressed, trendCandidate)
                    if hasReversalCandidate
                        f_suppress(goSuppressed, reversalCandidate)

                    bool laterOppositeConflict = laterTrendOppositeUsable or laterReversalOppositeUsable
                    if laterOppositeConflict
                        f_suppress(goSuppressed, goOwner)
                        goEventLane := goOwner.laneId
                        goEventStop := goOwner.invalidation
                        goEventTarget := goOwner.target
                        goEventEntryR := goEntryR
                        goOwner := na
                        goState := GO_WAIT_10M
                        goEntryPrice := na
                        goEntryR := na
                        goEventPulse := GO_EVENT_CONFLICT
                        goReason := GO_REASON_CONFLICT
                        goBarDone := true
                    else if goState == GO_WAIT_PULLBACK
                        bool touched = goOwner.direction == GO_DIRECTION_LONG ? low <= fast3Upper : high >= fast3Lower
                        if touched
                            goFrozenTrigger := goOwner.direction == GO_DIRECTION_LONG ? high : low
                            goTrendTriggerAge := 0
                            goState := GO_WAIT_TRIGGER
                            goReason := GO_REASON_PULLBACK_FROZEN
                        else
                            goReason := GO_REASON_WAIT_PULLBACK
                        goBarDone := true
                    else if goState == GO_WAIT_TRIGGER
                        goTrendTriggerAge += 1
                        if goTrendTriggerAge > MAX_TIMING_TRIGGER_BARS
                            f_suppress(goSuppressed, goOwner)
                            goEventLane := goOwner.laneId
                            goEventStop := goOwner.invalidation
                            goEventTarget := goOwner.target
                            goEventEntryR := goEntryR
                            goOwner := na
                            goState := GO_WAIT_10M
                            goEntryPrice := na
                            goEntryR := na
                            goEventPulse := GO_EVENT_EXPIRED
                            goReason := GO_REASON_EXPIRED
                        else
                            bool trendLongEntry = goOwner.direction == GO_DIRECTION_LONG and fast3Ema5 > fast3Ema12 and close > goFrozenTrigger and close > fast3Upper
                            bool trendShortEntry = goOwner.direction == GO_DIRECTION_SHORT and fast3Ema5 < fast3Ema12 and close < goFrozenTrigger and close < fast3Lower
                            if trendLongEntry or trendShortEntry
                                float remainingR = f_remaining_r(goOwner, close)
                                if na(remainingR) or remainingR < 1.0
                                    f_suppress(goSuppressed, goOwner)
                                    goEventLane := goOwner.laneId
                                    goEventStop := goOwner.invalidation
                                    goEventTarget := goOwner.target
                                    goEventEntryR := goEntryR
                                    goOwner := na
                                    goState := GO_WAIT_10M
                                    goEntryPrice := na
                                    goEntryR := na
                                    goEventPulse := GO_EVENT_MISSED
                                    goReason := GO_REASON_SPACE
                                else
                                    goState := GO_ENTERED
                                    goEntryPrice := close
                                    goEntryR := remainingR
                                    goMarkerPrice := close
                                    goEventPulse := goOwner.direction == GO_DIRECTION_LONG ? GO_EVENT_LONG_ENTRY : GO_EVENT_SHORT_ENTRY
                                    goReason := GO_REASON_ENTRY
                            else
                                goReason := GO_REASON_WAIT_TRIGGER
                        goBarDone := true
                    else if goState == GO_WAIT_IMMEDIATE_CONFIRM
                        bool exactNext = time == goAdoptionOpenMs + 180000
                        bool immediateEligible = exactNext and (goOwner.direction == GO_DIRECTION_LONG ? close > goOwner.producerTrigger and close <= goAdoptionHigh and fast3Ema5 > fast3Ema12 : close < goOwner.producerTrigger and close >= goAdoptionLow and fast3Ema5 < fast3Ema12)
                        if immediateEligible
                            float remainingR = f_remaining_r(goOwner, close)
                            if na(remainingR) or remainingR < 1.0
                                f_suppress(goSuppressed, goOwner)
                                goEventLane := goOwner.laneId
                                goEventStop := goOwner.invalidation
                                goEventTarget := goOwner.target
                                goEventEntryR := goEntryR
                                goOwner := na
                                goState := GO_WAIT_10M
                                goEntryPrice := na
                                goEntryR := na
                                goEventPulse := GO_EVENT_MISSED
                                goReason := GO_REASON_SPACE
                            else
                                goState := GO_ENTERED
                                goEntryPrice := close
                                goEntryR := remainingR
                                goMarkerPrice := close
                                goEventPulse := goOwner.direction == GO_DIRECTION_LONG ? GO_EVENT_LONG_ENTRY : GO_EVENT_SHORT_ENTRY
                                goReason := GO_REASON_ENTRY
                        else
                            f_suppress(goSuppressed, goOwner)
                            goEventLane := goOwner.laneId
                            goEventStop := goOwner.invalidation
                            goEventTarget := goOwner.target
                            goEventEntryR := goEntryR
                            goOwner := na
                            goState := GO_WAIT_10M
                            goEntryPrice := na
                            goEntryR := na
                            goEventPulse := GO_EVENT_MISSED
                            goReason := GO_REASON_MISSED
                        goBarDone := true
                    else if goState == GO_WAIT_FRESH_CROSS
                        bool freshCross = goOwner.direction == GO_DIRECTION_LONG ? goPreviousConfirmedClose <= goOwner.producerTrigger and close > goOwner.producerTrigger : goPreviousConfirmedClose >= goOwner.producerTrigger and close < goOwner.producerTrigger
                        goPreviousConfirmedClose := close
                        if freshCross
                            bool emaOk = goOwner.direction == GO_DIRECTION_LONG ? fast3Ema5 > fast3Ema12 : fast3Ema5 < fast3Ema12
                            float remainingR = f_remaining_r(goOwner, close)
                            if not emaOk or na(remainingR) or remainingR < 1.0
                                f_suppress(goSuppressed, goOwner)
                                goEventLane := goOwner.laneId
                                goEventStop := goOwner.invalidation
                                goEventTarget := goOwner.target
                                goEventEntryR := goEntryR
                                goOwner := na
                                goState := GO_WAIT_10M
                                goEntryPrice := na
                                goEntryR := na
                                goEventPulse := GO_EVENT_MISSED
                                goReason := not emaOk ? GO_REASON_MISSED : GO_REASON_SPACE
                            else
                                goState := GO_ENTERED
                                goEntryPrice := close
                                goEntryR := remainingR
                                goMarkerPrice := close
                                goEventPulse := goOwner.direction == GO_DIRECTION_LONG ? GO_EVENT_LONG_ENTRY : GO_EVENT_SHORT_ENTRY
                                goReason := GO_REASON_ENTRY
                        else
                            goReason := GO_REASON_WAIT_CROSS
                        goBarDone := true

            // No owner: pre-adoption terminal suppression then arbitration/adoption.
            if not goBarDone and na(goOwner)
                bool trendUsable = hasTrendCandidate and trendRegistration == 1 and not f_array_contains(goSuppressed, f_full_key(trendCandidate)) and (na(goResetVisibleCutoffMs) or trendCandidate.visibleAtMs > goResetVisibleCutoffMs) and trendCandidate.visibleAtMs <= time and time < trendCandidate.permissionExpiresAtMs and (na(trendCandidate.contextValidUntilMs) or time_close < trendCandidate.contextValidUntilMs)
                bool reversalUsable = hasReversalCandidate and reversalRegistration == 1 and not f_array_contains(goSuppressed, f_full_key(reversalCandidate)) and (na(goResetVisibleCutoffMs) or reversalCandidate.visibleAtMs > goResetVisibleCutoffMs) and reversalCandidate.visibleAtMs <= time and time < reversalCandidate.permissionExpiresAtMs and (na(reversalCandidate.contextValidUntilMs) or time_close < reversalCandidate.contextValidUntilMs)
                bool trendPreStop = trendUsable and (f_stop_hit(trendCandidate, high[1], low[1], close[1]) or f_stop_hit(trendCandidate, high, low, close))
                bool trendPreTarget = trendUsable and not trendPreStop and (f_target_hit(trendCandidate, high[1], low[1]) or f_target_hit(trendCandidate, high, low))
                bool reversalPreStop = reversalUsable and (f_stop_hit(reversalCandidate, high[1], low[1], close[1]) or f_stop_hit(reversalCandidate, high, low, close))
                bool reversalPreTarget = reversalUsable and not reversalPreStop and (f_target_hit(reversalCandidate, high[1], low[1]) or f_target_hit(reversalCandidate, high, low))
                if trendPreStop or trendPreTarget
                    f_suppress(goSuppressed, trendCandidate)
                    trendUsable := false
                if reversalPreStop or reversalPreTarget
                    f_suppress(goSuppressed, reversalCandidate)
                    reversalUsable := false

                if trendUsable and reversalUsable and trendCandidate.direction != reversalCandidate.direction
                    f_suppress(goSuppressed, trendCandidate)
                    f_suppress(goSuppressed, reversalCandidate)
                    goEventPulse := GO_EVENT_CONFLICT
                    goReason := GO_REASON_CONFLICT
                    goBarDone := true
                else
                    PlanEnvelope winner = na
                    PlanEnvelope loser = na
                    if trendUsable and reversalUsable
                        bool trendWins = trendCandidate.visibleAtMs < reversalCandidate.visibleAtMs or trendCandidate.visibleAtMs == reversalCandidate.visibleAtMs
                        winner := trendWins ? trendCandidate : reversalCandidate
                        loser := trendWins ? reversalCandidate : trendCandidate
                    else if trendUsable
                        winner := trendCandidate
                    else if reversalUsable
                        winner := reversalCandidate

                    if not na(loser)
                        f_suppress(goSuppressed, loser)
                    if not na(winner)
                        goOwner := winner
                        f_suppress(goSuppressed, winner)
                        goAdoptionOpenMs := time
                        goAdoptionHigh := high
                        goAdoptionLow := low
                        goFrozenTrigger := na
                        goTrendTriggerAge := 0
                        goPreviousConfirmedClose := close
                        goEntryPrice := na
                        goEntryR := na
                        if winner.laneId == GO_LANE_TREND
                            goState := GO_WAIT_PULLBACK
                            goReason := GO_REASON_NEW_TREND
                        else
                            bool beyond = winner.direction == GO_DIRECTION_LONG ? close > winner.producerTrigger : close < winner.producerTrigger
                            goState := beyond ? GO_WAIT_IMMEDIATE_CONFIRM : GO_WAIT_FRESH_CROSS
                            goReason := GO_REASON_NEW_REVERSAL
                        goBarDone := true
                    else
                        goReason := hasTrendCandidate or hasReversalCandidate ? GO_REASON_SUPPRESSED : GO_REASON_WAIT_10M
                        goBarDone := true

    if barstate.isconfirmed and goPayloadNewObservation
        // Observation is a raw continuity audit only; it cannot grant consumption.
        goLastObserved10mTime := e_time

    if barstate.isconfirmed and not na(e_time) and (goRawReset or goPayloadRejectedByReset)
        // Explicit rejection survives observation rebaselining. Reset cutoff covers
        // all older/equal visible_at values; this ledger also closes rejected raw
        // timestamps that could otherwise reappear above the cutoff.
        if array.indexof(goRejected10mSourceTimes, e_time) < 0
            array.push(goRejected10mSourceTimes, e_time)

    if barstate.isconfirmed and go_processPayload
        // Only successful shared-adapter delivery advances consumption identity.
        goLastConsumed10mTime := e_time

    if barstate.isconfirmed
        // Terminal/missed/conflict/reset explanations are one-bar snapshots.
        // Only an active owner may persist a reason into the next chart bar.
        goLastReason := not na(goOwner) ? goReason : GO_REASON_WAIT_10M

    bool longEntryPulse = goEventPulse == GO_EVENT_LONG_ENTRY
    bool shortEntryPulse = goEventPulse == GO_EVENT_SHORT_ENTRY
    bool trendLongAlert = barstate.isconfirmed and longEntryPulse and not na(goOwner) and goOwner.laneId == GO_LANE_TREND
    bool trendShortAlert = barstate.isconfirmed and shortEntryPulse and not na(goOwner) and goOwner.laneId == GO_LANE_TREND
    bool reversalLongAlert = barstate.isconfirmed and longEntryPulse and not na(goOwner) and goOwner.laneId == GO_LANE_REVERSAL
    bool reversalShortAlert = barstate.isconfirmed and shortEntryPulse and not na(goOwner) and goOwner.laneId == GO_LANE_REVERSAL

    plotshape(longEntryPulse ? goMarkerPrice : na, title="3m 多入", text="多入", style=shape.labelup, location=location.absolute, color=color.rgb(0, 200, 83), textcolor=color.rgb(5, 9, 17), size=size.large)
    plotshape(shortEntryPulse ? goMarkerPrice : na, title="3m 空入", text="空入", style=shape.labeldown, location=location.absolute, color=color.rgb(255, 111, 0), textcolor=color.rgb(5, 9, 17), size=size.large)

    bool ownsPlan = not na(goOwner)
    plot(goShowPlanLevels and ownsPlan ? goOwner.invalidation : na, title="当前冻结保护", color=color.rgb(255, 82, 82), linewidth=2, style=plot.style_linebr)
    plot(goShowPlanLevels and ownsPlan ? goOwner.target : na, title="当前冻结目标", color=color.rgb(0, 229, 255), linewidth=2, style=plot.style_linebr)
    plot(goShowFastCloud ? fast3Ema5 : na, title="3m EMA5", color=color.rgb(0, 200, 83), linewidth=1)
    plot(goShowFastCloud ? fast3Ema12 : na, title="3m EMA12", color=color.rgb(255, 82, 82), linewidth=1)

    plot(longEntryPulse or shortEntryPulse ? goEntryPrice : na, title="GO_ENTRY", display=display.none)
    plot(longEntryPulse or shortEntryPulse ? goOwner.invalidation : na, title="GO_STOP", display=display.none)
    plot(longEntryPulse or shortEntryPulse ? goOwner.target : na, title="GO_TARGET", display=display.none)
    plot(longEntryPulse or shortEntryPulse ? goEntryR : na, title="GO_REMAINING_R", display=display.none)
    plot(longEntryPulse or shortEntryPulse ? goOwner.confirmationTimeMs : na, title="GO_10M_CONFIRMATION_MS", display=display.none)
    plot(goState, title="AUDIT｜owner state", display=display.data_window)
    plot(goEventPulse, title="AUDIT｜owner event", display=display.data_window)
    plot(array.size(goSuppressed), title="AUDIT｜suppressed identities", display=display.data_window)
    plot(array.size(goCollisionTombstones), title="AUDIT｜collision tombstones", display=display.data_window)
    plot(goLastObserved10mTime, title="AUDIT｜last observed 10m", display=display.data_window)
    plot(goLastConsumed10mTime, title="AUDIT｜last consumed 10m", display=display.data_window)
    plot(goResetVisibleCutoffMs, title="AUDIT｜reset visible cutoff", display=display.data_window)
    plot(array.size(goRejected10mSourceTimes), title="AUDIT｜rejected 10m timestamps", display=display.data_window)

    alertcondition(trendLongAlert, title="3m | 趋势续行 | 多入", message='标的={{exchange}}:{{ticker}}｜周期={{interval}}｜趋势续行｜多头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单')
    alertcondition(trendShortAlert, title="3m | 趋势续行 | 空入", message='标的={{exchange}}:{{ticker}}｜周期={{interval}}｜趋势续行｜空头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单')
    alertcondition(reversalLongAlert, title="3m | 位置反转 | 多入", message='标的={{exchange}}:{{ticker}}｜周期={{interval}}｜位置反转｜多头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单')
    alertcondition(reversalShortAlert, title="3m | 位置反转 | 空入", message='标的={{exchange}}:{{ticker}}｜周期={{interval}}｜位置反转｜空头条件确认｜K线时间(UTC)={{time}}｜确认价={{plot("GO_ENTRY")}}｜保护={{plot("GO_STOP")}}｜目标={{plot("GO_TARGET")}}｜剩余R={{plot("GO_REMAINING_R")}}｜10m确认审计时间戳(ms)={{plot("GO_10M_CONFIRMATION_MS")}}｜仅对应本根3m收盘；若未参与请勿追价；不是订单')

    string cardAction = goEventPulse == GO_EVENT_CONFLICT ? "冲突不做" : longEntryPulse ? "本根多头确认" : shortEntryPulse ? "本根空头确认" : goEventPulse == GO_EVENT_INVALIDATED or goEventPulse == GO_EVENT_TARGET_REACHED or goEventPulse == GO_EVENT_EXPIRED or goEventPulse == GO_EVENT_MISSED or goEventPulse == GO_EVENT_DATA_RESET ? "本计划结束" : goState == GO_ENTERED and not na(goOwner) ? (goOwner.direction == GO_DIRECTION_LONG ? "多头计划监控｜勿追" : "空头计划监控｜勿追") : (goState == GO_WAIT_TRIGGER or goState == GO_WAIT_IMMEDIATE_CONFIRM or goState == GO_WAIT_FRESH_CROSS) and not na(goOwner) ? (goOwner.direction == GO_DIRECTION_LONG ? "等待多头确认" : "等待空头确认") : "等待"
    int cardLane = not na(goOwner) ? goOwner.laneId : goEventLane
    string cardSource = cardLane == GO_LANE_TREND ? "10m 趋势续行" : cardLane == GO_LANE_REVERSAL ? "10m 位置反转" : "—"
    float cardStop = not na(goOwner) ? goOwner.invalidation : goEventStop
    float cardTarget = not na(goOwner) ? goOwner.target : goEventTarget
    float cardRemainingR = not na(goOwner) ? f_remaining_r(goOwner, close) : goEventEntryR
    string cardTargetText = f_price(cardTarget) + "｜剩余 " + (na(cardRemainingR) ? "—" : str.tostring(cardRemainingR, "#0.00") + "R")
    var table goCard = table.new(position.bottom_right, 2, 5, bgcolor=color.rgb(5, 9, 17), frame_color=color.rgb(148, 163, 184), frame_width=1, border_color=color.rgb(71, 85, 105), border_width=1)
    f_card_row(int row, string label, string value, color valueColor) =>
        table.cell(goCard, 0, row, label, text_color=color.rgb(203, 213, 225), bgcolor=color.rgb(15, 23, 42), text_halign=text.align_left)
        table.cell(goCard, 1, row, value, text_color=valueColor, bgcolor=color.rgb(5, 9, 17), text_halign=text.align_right)

    if barstate.islast
        if goShowCard
            f_card_row(0, "现在做", cardAction, longEntryPulse ? color.rgb(0, 255, 128) : shortEntryPulse ? color.rgb(255, 171, 64) : goEventPulse == GO_EVENT_CONFLICT ? color.rgb(255, 214, 10) : color.white)
            f_card_row(1, "来源", cardSource, color.rgb(125, 211, 252))
            f_card_row(2, "为什么", goReason, color.white)
            f_card_row(3, "保护", f_price(cardStop), color.rgb(255, 138, 128))
            f_card_row(4, "目标", cardTargetText, not na(cardRemainingR) and cardRemainingR >= 1.0 ? color.rgb(0, 255, 128) : color.white)
        else
            table.clear(goCard, 0, 0, 1, 4)
    // GLOBAL_OWNER_CANONICAL_END phase1-3m-global-owner-1.0
    '''
).strip()


def render_pine() -> str:
    reversal_constants, reversal_inputs, input_names, reversal_core = (
        _render_reversal_adapter()
    )
    request_line = _request_transport(input_names)
    header = dedent(
        f'''\
        //@version=6
        indicator("IDM Phase 1｜3m 全局计划 owner v1", shorttitle="IDM 3m Global Owner", overlay=true, explicit_plot_zorder=true)

        // Generated by research/generate_phase1_3m_global_owner_pine_v1.py.
        // One previous-completed 10m transport feeds two independent accepted
        // producer cores.  This indicator places no order and exposes no webhook.
        string GLOBAL_PROTOCOL_VERSION = "{PROTOCOL_VERSION}"
        string GLOBAL_SCHEMA_VERSION = "{SCHEMA_VERSION}"
        string GLOBAL_EXPECTED_SYMBOL = "CAPITALCOM:SPX500"
        int GLOBAL_3M_INTERVAL_MS = 180000
        int GLOBAL_10M_INTERVAL_MS = 600000

        string GO_GROUP_VIEW = "显示"
        bool goShowFastCloud = input.bool(true, "显示 3m EMA5/12", group=GO_GROUP_VIEW)
        bool goShowPlanLevels = input.bool(true, "显示冻结保护/目标", group=GO_GROUP_VIEW)
        bool goShowCard = input.bool(true, "显示五行卡", group=GO_GROUP_VIEW)
        '''
    ).rstrip()
    transport = dedent(
        f'''\
        f_strict_pivot_high_2_2() =>
            not na(high[4]) and high[2] > high[4] and high[2] > high[3] and high[2] > high[1] and high[2] > high ? high[2] : na

        f_strict_pivot_low_2_2() =>
            not na(low[4]) and low[2] < low[4] and low[2] < low[3] and low[2] < low[1] and low[2] < low ? low[2] : na

        f_strict_pivot_high_time_2_2() =>
            not na(high[4]) and high[2] > high[4] and high[2] > high[3] and high[2] > high[1] and high[2] > high ? time[2] : na

        f_strict_pivot_low_time_2_2() =>
            not na(low[4]) and low[2] < low[4] and low[2] < low[3] and low[2] < low[1] and low[2] < low ? time[2] : na

        bool goHostContractOk = ticker.standard(syminfo.tickerid) == GLOBAL_EXPECTED_SYMBOL and timeframe.isintraday and timeframe.period == "3" and chart.is_standard
        float goPreEma5 = ta.ema(hl2, 5)
        float goPreEma12 = ta.ema(hl2, 12)
        bool goPreDataOk = not na(open) and not na(high) and not na(low) and not na(close) and not na(goPreEma5) and not na(goPreEma12) and high >= low and high >= math.max(open, close) and low <= math.min(open, close)
        var int goLast3mTime = na
        bool goDuplicate3m = barstate.isconfirmed and goHostContractOk and goPreDataOk and not na(goLast3mTime) and time == goLast3mTime
        bool goBackward3m = barstate.isconfirmed and not na(goLast3mTime) and time < goLast3mTime
        bool goGap3m = barstate.isconfirmed and not na(goLast3mTime) and time > goLast3mTime and time - goLast3mTime != GLOBAL_3M_INTERVAL_MS
        bool goConsumerBarEligible = barstate.isconfirmed and goHostContractOk and goPreDataOk and not goDuplicate3m and not goBackward3m and not goGap3m

        // Exactly one previous-completed 10m superset request for both adapters.
        // The transported input.* values are static source/target/ATR configuration
        // and canonical identity inputs required by freeze section 3. They are
        // producer truth, not mutable producer UI/output state; no source-typed
        // selector input is transported.
        {request_line}

        var int goLastObserved10mTime = na
        var int goLastConsumed10mTime = na
        var int goResetVisibleCutoffMs = na
        var array<int> goRejected10mSourceTimes = array.new_int(0)
        bool goPayloadVisible = goConsumerBarEligible and not na(e_time) and not na(e_timeClose) and e_timeClose <= time
        bool goPayloadNewObservation = goPayloadVisible and (na(goLastObserved10mTime) or e_time != goLastObserved10mTime)
        bool goPayloadUnconsumed = goPayloadVisible and (na(goLastConsumed10mTime) or e_time != goLastConsumed10mTime)
        bool goPayloadRejectedByLedger = goPayloadVisible and array.indexof(goRejected10mSourceTimes, e_time) >= 0
        bool goPayloadRejectedByReset = goPayloadVisible and not na(goResetVisibleCutoffMs) and e_timeClose <= goResetVisibleCutoffMs
        bool goRaw10mDataOk = not na(e_time) and not na(e_timeClose) and not na(e_dayKey) and not na(e_open) and not na(e_high) and not na(e_low) and not na(e_close) and not na(e_ema5) and not na(e_ema12) and not na(e_ema21) and not na(e_ema48) and e_timeClose - e_time == GLOBAL_10M_INTERVAL_MS and e_high >= e_low and e_high >= math.max(e_open, e_close) and e_low <= math.min(e_open, e_close)
        bool goRaw10mMissingAfterStart = goConsumerBarEligible and not na(goLastObserved10mTime) and (na(e_time) or na(e_timeClose) or na(e_dayKey) or na(e_open) or na(e_high) or na(e_low) or na(e_close) or na(e_ema5) or na(e_ema12) or na(e_ema21) or na(e_ema48))
        bool goRaw10mBackward = goPayloadNewObservation and not na(goLastObserved10mTime) and e_time < goLastObserved10mTime
        bool goRaw10mGap = goPayloadNewObservation and not na(goLastObserved10mTime) and e_time > goLastObserved10mTime and e_time - goLastObserved10mTime != GLOBAL_10M_INTERVAL_MS
        bool goRawReset = goRaw10mMissingAfterStart or (goPayloadNewObservation and (not goRaw10mDataOk or goRaw10mBackward or goRaw10mGap))
        bool go_processPayload = goPayloadUnconsumed and goRaw10mDataOk and not goRaw10mBackward and not goRaw10mGap and not goPayloadRejectedByLedger and not goPayloadRejectedByReset

        bool e_transportRepeatAllowed = false
        float e_minimumTick = syminfo.mintick
        bool e_sourceAvailable = go_processPayload
        bool e_modeOk = goHostContractOk
        '''
    ).rstrip()
    reversal_header = dedent(
        '''\
        // Exact canonical POSITION_REVERSAL producer core, namespaced and fed by
        // the same transported raw 10m tuple.  No standalone UI/alerts are copied.
        bool r_processNow = go_processPayload
        '''
    ).rstrip()
    sections = [
        header,
        reversal_constants,
        dedent(
            '''\
            // POSITION_REVERSAL source inputs remain the accepted standalone defaults.
            // They are transported with [1] inside the single 10m request below.
            '''
        ).rstrip(),
        reversal_inputs,
        transport,
        TREND_CORE.strip(),
        reversal_header,
        reversal_core,
        GLOBAL_OWNER_TAIL,
    ]
    return "\n\n".join(section for section in sections if section).rstrip() + "\n"


PINE_SOURCE = render_pine()
PINE_SHA256 = sha256(PINE_SOURCE.encode("utf-8")).hexdigest()


def _verify_frozen_pines() -> None:
    for relative_path, expected in EXPECTED_FROZEN_PINE_HASHES.items():
        path = ROOT / relative_path
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"frozen Pine SHA mismatch: {relative_path}: {actual} != {expected}"
            )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    _verify_frozen_pines()
    if args.check:
        if not args.output.is_file():
            print(f"missing generated Pine: {args.output}", file=sys.stderr)
            return 1
        actual = args.output.read_text(encoding="utf-8")
        if actual != PINE_SOURCE:
            print(f"generated Pine byte mismatch: {args.output}", file=sys.stderr)
            return 1
        print(
            "3m global-owner Pine byte parity PASS | "
            f"bytes={len(PINE_SOURCE.encode('utf-8'))} | sha256={PINE_SHA256}"
        )
        return 0
    args.output.write_text(PINE_SOURCE, encoding="utf-8")
    print(f"wrote {args.output} | bytes={len(PINE_SOURCE.encode('utf-8'))} | sha256={PINE_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
