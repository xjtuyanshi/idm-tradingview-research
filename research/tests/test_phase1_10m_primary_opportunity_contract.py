"""Static source, visual, and generator parity contract for the R3 artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import sys

from research.generate_phase1_10m_primary_pine_r3 import CANONICAL_BLOCK
from research.phase1_10m_primary_opportunity_oracle import (
    MINIMUM_SPACE_R,
    POSITION_REVERSAL_ENABLED,
    PROTOCOL_VERSION,
    TIMING_PROTOCOL_VERSION,
    NamedLevelSource,
)

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_PINE = ROOT / "idm_phase1_10m_primary_opportunity_v3.pine"
TIMING_PINE = ROOT / "idm_phase1_3m_opportunity_timing_v3.pine"
ORACLE = ROOT / "research/phase1_10m_primary_opportunity_oracle.py"
GENERATOR = ROOT / "research/generate_phase1_10m_primary_pine_r3.py"
NATIVE_REPLAY = ROOT / "research/replay_phase1_10m_primary_opportunity_r3.py"
DUAL_REPLAY = ROOT / "research/replay_phase1_10m_to_3m_r3.py"
SPEC = ROOT / "docs/PHASE1_10M_PRIMARY_OPPORTUNITY_SPEC_ZH.md"
CANONICAL_SHA256 = "c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2"
START = "// PRIMARY10M_CANONICAL_R3_BEGIN phase1-10m-primary-opportunity-3.0"
END = "// PRIMARY10M_CANONICAL_R3_END phase1-10m-primary-opportunity-3.0"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _canonical_block(code: str) -> str:
    start = code.index(START)
    end = code.index(END) + len(END)
    return code[start:end]


def _strip_comments(code: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in code.splitlines())


def _plotshape_lines(code: str) -> list[str]:
    return [line.strip() for line in code.splitlines() if "plotshape(" in line]


def test_r3_delivery_files_and_protocol_versions_exist() -> None:
    for path in (
        PRIMARY_PINE,
        TIMING_PINE,
        ORACLE,
        GENERATOR,
        NATIVE_REPLAY,
        DUAL_REPLAY,
        SPEC,
    ):
        assert path.is_file()
    assert PROTOCOL_VERSION == "phase1-10m-primary-opportunity-3.0"
    assert TIMING_PROTOCOL_VERSION == "phase1-3m-opportunity-timing-3.0"
    assert MINIMUM_SPACE_R == 1.0
    assert POSITION_REVERSAL_ENABLED is False


def test_generator_reproduces_both_pines_byte_for_byte() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_full_canonical_contract_block_is_identical_and_pinned() -> None:
    primary_block = _canonical_block(_source(PRIMARY_PINE))
    timing_block = _canonical_block(_source(TIMING_PINE))
    assert primary_block == timing_block == CANONICAL_BLOCK
    assert hashlib.sha256(primary_block.encode("utf-8")).hexdigest() == CANONICAL_SHA256


def test_canonical_hash_scope_includes_router_rearm_watch_and_complete_day_engine() -> None:
    block = _canonical_block(_source(PRIMARY_PINE))
    required = (
        'string PRIMARY_PROTOCOL_VERSION = "phase1-10m-primary-opportunity-3.0"',
        "bool POSITION_REVERSAL_ENABLED = false",
        "int PIVOT_LEFT_BARS = 2",
        "int STATE_WAIT_CLEAR = 1",
        "int EVENT_WATCH_LONG = 1",
        "int LEVEL_CONFIRMED_PIVOT_10M = 2",
        "var int e_currentDayFirstTime = na",
        "var int e_currentDayBarCount = 0",
        "bool e_rollsToImmediateNextEtDay",
        "e_currentDayBarCount == 144",
        "var array<float> e_frozenCandidatePrices",
        "if e_state == STATE_WAIT_REACTION",
        "else if e_state == STATE_ACTIVE",
        "else if e_state == STATE_WAIT_CLEAR",
        "else if e_state == STATE_ARMED",
    )
    for token in required:
        assert token in block


def test_position_reversal_is_disabled_and_only_trend_continuation_is_present() -> None:
    for path in (PRIMARY_PINE, TIMING_PINE):
        code = _source(path)
        assert "bool POSITION_REVERSAL_ENABLED = false" in code
        assert "POSITION_REVERSAL_ENABLED = true" not in code
        assert "REVERSAL_READY" not in code
        assert "REVERSAL_ACTIVE" not in code


def test_ema_roles_host_contracts_and_main_pane_visual_priority_are_exact() -> None:
    primary = _source(PRIMARY_PINE)
    timing = _source(TIMING_PINE)
    for token in (
        "float e_ema5 = ta.ema(hl2, 5)",
        "float e_ema12 = ta.ema(hl2, 12)",
        "float e_ema21 = ta.ema(close, 21)",
        "float e_ema48 = ta.ema(close, 48)",
        'timeframe.period == "10"',
        "ticker.standard(syminfo.tickerid) == EXPECTED_SYMBOL",
        "chart.is_standard",
        'indicator("IDM Phase 1｜10m 交易计划 v3.2"',
        "overlay=true",
        "color.new(color.green, 72)",
        'plot(shownEma21, "慢结构 EMA21｜close", color=color.rgb(255, 193, 7), linewidth=2)',
        'plot(shownEma48, "慢结构 EMA48｜close", color=color.blue, linewidth=3)',
    ):
        assert token in primary
    assert "scale=" not in primary
    assert 'timeframe.period == "3"' in timing
    assert 'request.security(syminfo.tickerid, "10"' in timing
    for token in (
        "ta.ema(hl2, 5)[e_requestOffset]",
        "ta.ema(hl2, 12)[e_requestOffset]",
        "ta.ema(close, 21)[e_requestOffset]",
        "ta.ema(close, 48)[e_requestOffset]",
        "color.new(color.green, 72)",
    ):
        assert token in timing


def test_python_and_both_pines_use_strict_confirmed_2_2_pivots() -> None:
    for path in (PRIMARY_PINE, TIMING_PINE):
        code = _source(path)
        for token in (
            "f_strict_pivot_high_2_2()",
            "f_strict_pivot_low_2_2()",
            "high[2] > high[4]",
            "high[2] > high[3]",
            "high[2] > high[1]",
            "high[2] > high",
            "low[2] < low[4]",
            "low[2] < low[3]",
            "low[2] < low[1]",
            "low[2] < low",
        ):
            assert token in code
        assert "ta.pivothigh" not in code
        assert "ta.pivotlow" not in code


def test_prior_excursion_provenance_tracks_the_actual_latest_extreme() -> None:
    block = _canonical_block(_source(PRIMARY_PINE))
    assert "var int e_priorExcursionTime = na" in block
    assert "e_priorExcursionTime := e_time" in block
    assert "array.push(e_frozenCandidateTimes, e_priorExcursionTime)" in block
    assert "array.push(e_frozenCandidateTimes, e_episodeStartTime)" not in block


def test_companion_uses_completed_10m_transport_without_future_lookahead() -> None:
    timing = _source(TIMING_PINE)
    stripped = _strip_comments(timing)
    assert timing.count("request.security(") == 1
    assert "lookahead=barmerge.lookahead_off" in timing
    assert "lookahead_on" not in stripped
    assert "int e_requestOffset = barstate.isrealtime ? 1 : 0" in timing
    assert "int e_chartOffset = barstate.isrealtime ? 0 : 1" in timing
    assert "time[e_requestOffset]" in timing
    assert "time_close[e_requestOffset]" in timing
    assert "e_timeRaw[e_chartOffset]" in timing
    assert "e_timeCloseRaw[e_chartOffset]" in timing
    assert "time >= e_timeClose" in timing
    assert "time_close >= e_timeClose" not in timing
    assert "barstate.isconfirmed" in timing
    assert "handoffOverlap" in timing
    assert "handoffCloseInvalid" in timing
    assert "handoffTargetTouched" in timing


def test_named_level_router_allowlist_and_source_identity_are_frozen() -> None:
    assert list(NamedLevelSource) == [
        NamedLevelSource.PRIOR_EXCURSION_10M,
        NamedLevelSource.CONFIRMED_PIVOT_10M,
        NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH,
        NamedLevelSource.PREVIOUS_COMPLETED_DAY_LOW,
        NamedLevelSource.UNKNOWN,
    ]
    for code in (_source(PRIMARY_PINE), _source(TIMING_PINE)):
        for token in (
            "LEVEL_PRIOR_EXCURSION_10M",
            "LEVEL_CONFIRMED_PIVOT_10M",
            "LEVEL_PREVIOUS_COMPLETED_DAY_HIGH",
            "LEVEL_PREVIOUS_COMPLETED_DAY_LOW",
            "e_nextNamedLevelSource",
            "f_source_text",
        ):
            assert token in code
    primary = _source(PRIMARY_PINE)
    assert 'cardPlanContext ? f_price(e_nextNamedLevel) + "｜" + f_source_card_text(e_nextNamedLevelSource)' in primary


def test_router_freezes_at_touch_consumes_before_selection_and_never_skips_nearer() -> None:
    block = _canonical_block(_source(PRIMARY_PINE))
    touch = block.index("bool e_firstTouch")
    freeze = block.index("array.push(e_frozenCandidatePrices", touch)
    wait_reaction = block.index("if e_state == STATE_WAIT_REACTION")
    consume = block.index("array.set(e_frozenCandidateConsumed", wait_reaction)
    select = block.index("float e_selectedPrice = na", consume)
    space_gate = block.index("e_spaceR < MINIMUM_SPACE_R", select)
    assert touch < freeze
    assert wait_reaction < consume < select < space_gate
    assert "bool priceBefore = direction == DIRECTION_LONG ? leftPrice < rightPrice : leftPrice > rightPrice" in block
    assert "leftPriority < rightPriority" in block
    assert "leftPriority == rightPriority and f_provenance_rank(leftTime) < f_provenance_rank(rightTime)" in block
    assert "e_candidatePrice > e_high" in block
    assert "e_candidatePrice < e_low" in block
    assert "e_nextNamedLevel := na" in block
    assert "e_nextNamedLevelSource := LEVEL_UNKNOWN" in block


def test_complete_previous_day_is_strict_full_144_bar_et_day_only() -> None:
    block = _canonical_block(_source(PRIMARY_PINE))
    required = (
        "e_currentDayBarCount == 144",
        'hour(e_currentDayFirstTime, "America/New_York") == 0',
        'minute(e_currentDayFirstTime, "America/New_York") == 0',
        'hour(e_currentDayLastTime, "America/New_York") == 23',
        'minute(e_currentDayLastTime, "America/New_York") == 50',
        "e_currentDayContiguous := e_currentDayContiguous and e_time - e_currentDayLastTime == PRIMARY_INTERVAL_MS",
        "bool e_rollsToImmediateNextEtDay",
        "e_dayRolloverMs >= 23 * 60 * 60 * 1000",
        "e_dayRolloverMs <= 25 * 60 * 60 * 1000",
        "e_previousDayHigh := e_previousDayComplete ? e_currentDayHigh : na",
        "e_previousDayLow := e_previousDayComplete ? e_currentDayLow : na",
        "e_currentDayContiguous := hour(e_time",
    )
    for token in required:
        assert token in block
    assert "e_previousDayHigh := e_currentDayHigh" not in block
    assert "e_previousDayLow := e_currentDayLow" not in block
    oracle = _source(ORACLE)
    assert "_current_day_bar_count != 144" in oracle
    assert "+ timedelta(days=1)" in oracle
    assert "first.hour == 0" in oracle
    assert "last.hour == 23" in oracle and "last.minute == 50" in oracle


def test_wait_reaction_terminal_priority_and_later_full_clear_rearm_are_frozen() -> None:
    block = _canonical_block(_source(PRIMARY_PINE))
    reaction = block.index("if e_state == STATE_WAIT_REACTION")
    invalidation = block.index("if e_reactionInvalidated", reaction)
    slow_loss = block.index("else if e_slowDirection != e_epochDirection", invalidation)
    assert invalidation < slow_loss
    assert "e_state := STATE_WAIT_CLEAR" in block
    wait_clear = block.index("else if e_state == STATE_WAIT_CLEAR")
    departure = block.index("bool e_fullDeparture", wait_clear)
    new_episode = block.index("e_episodeStartTime := e_time", departure)
    assert wait_clear < departure < new_episode
    assert "cooldown" not in block.lower()


def test_watch_is_observation_only_and_never_grants_3m_permission() -> None:
    primary = _source(PRIMARY_PINE)
    timing = _source(TIMING_PINE)
    block = _canonical_block(primary)
    watch_branch = block[
        block.index("bool e_firstTouch") : block.index(
            "Finalize the current ET day", block.index("bool e_firstTouch")
        )
    ]
    assert "EVENT_WATCH_LONG" in watch_branch
    assert "EVENT_WATCH_SHORT" in watch_branch
    assert "e_opportunityActive := true" not in watch_branch
    assert "e_opportunityTime := e_time" not in watch_branch
    assert "bool newPlanAvailable = e_opportunityActive" in timing
    assert "EVENT_WATCH_LONG" not in timing[timing.index("bool newPlanAvailable") :]


def test_hard_one_r_gate_precedes_main_and_3m_entry() -> None:
    primary_block = _canonical_block(_source(PRIMARY_PINE))
    gate = primary_block.index("else if e_spaceR < MINIMUM_SPACE_R")
    main = primary_block.index("e_state := STATE_ACTIVE", gate)
    assert gate < main
    timing = _source(TIMING_PINE)
    timing_gate = timing.index("timingSpaceRNow < MINIMUM_SPACE_R")
    timing_entry = timing.index("timingEventPulse := timingLongEntry", timing_gate)
    assert timing_gate < timing_entry


def test_entry_permission_and_entered_management_lifetimes_are_split_in_pine() -> None:
    timing = _source(TIMING_PINE)
    identity = timing.index("bool primaryEventMatchesOld")
    old_invalid = timing.index("if oldInvalidated", identity)
    old_target = timing.index("else if oldTargetReached", old_invalid)
    entered = timing.index("else if timingState == TIMING_ENTERED and hasOldPlan", old_target)
    no_permission = timing.index("else if not newPlanAvailable", entered)
    adoption = timing.index("else if isNewPlan", no_permission)
    touch = timing.index("else if timingState == TIMING_WAIT_PULLBACK", adoption)
    assert identity < old_invalid < old_target < entered < no_permission < adoption < touch
    for token in (
        "primaryEventMatchesOld and e_eventPulse == EVENT_INVALIDATED",
        "primaryEventMatchesOld and e_eventPulse == EVENT_TARGET_REACHED",
        "TIMING_REASON_ENTERED_PLAN_MANAGEMENT",
        "ACTIVE_EXPIRED, active_plan=None, or a different plan cannot evict ENTERED",
        "TIMING_EVENT_LONG_TARGET_REACHED",
        "TIMING_EVENT_SHORT_TARGET_REACHED",
    ):
        assert token in timing


def test_space_r_has_dedicated_r_formatter_not_price_format() -> None:
    primary = _source(PRIMARY_PINE)
    assert 'str.tostring(value, "#0.00") + "R"' in primary
    assert "str.tostring(e_spaceR, format.mintick)" not in primary


def test_default_marker_language_is_plan_owned_and_watch_history_is_opt_in() -> None:
    primary_lines = _plotshape_lines(_source(PRIMARY_PINE))
    timing_lines = _plotshape_lines(_source(TIMING_PINE))
    assert len(primary_lines) == 4
    assert len(timing_lines) == 6
    assert {re.search(r'title="([^"]+)"', line).group(1) for line in primary_lines} == {
        "10m 多观察",
        "10m 空观察",
        "10m 多计划",
        "10m 空计划",
    }
    assert {re.search(r'title="([^"]+)"', line).group(1) for line in timing_lines} == {
        "3m 多入场",
        "3m 空入场",
        "3m 多计划失效",
        "3m 空计划失效",
        "3m 多计划到达",
        "3m 空计划到达",
    }
    assert 'showWatchHistory = input.bool(false, "显示历史观察点（默认关闭）"' in _source(PRIMARY_PINE)
    assert "barstate.islast and e_state == STATE_WAIT_REACTION and e_outcome == OUTCOME_WATCH_LONG ? e_reactionLow" in primary_lines[0]
    assert "barstate.islast and e_state == STATE_WAIT_REACTION and e_outcome == OUTCOME_WATCH_SHORT ? e_reactionHigh" in primary_lines[1]
    for line in primary_lines + timing_lines:
        assert "location=location.absolute" in line
    assert "style=shape.triangleup" in primary_lines[0]
    assert "style=shape.triangledown" in primary_lines[1]
    assert all("textcolor=color.black" not in line for line in primary_lines + timing_lines)


def test_cards_are_dark_five_row_action_cards_without_gray_action_text() -> None:
    primary = _source(PRIMARY_PINE)
    timing = _source(TIMING_PINE)
    assert "table.new(position.top_right, 2, 5" in primary
    assert "table.new(position.bottom_right, 2, 5" in timing
    for token in ('"现在做"', '"触发"', '"失效"', '"目标"', '"原因"'):
        assert token in primary
    for token in ('"现在做"', '"触发"', '"失效"', '"目标"', '"原因"'):
        assert token in timing
    assert 'f_reason_card_text()' in primary
    assert 'f_timing_reason_card_text()' in timing
    assert 'e_reason == REASON_ACTIVE_EXPIRED ? "计划超时｜等重新离云" : "未知原因"' in primary
    for approved in (
        "21/48 方向已识别",
        "等后续首次回踩 5/12",
        "计划超时｜等重新离云",
    ):
        assert approved in primary
    for approved in (
        "10m 尚无可用主计划",
        "入场信号已触发｜跟踪保护/目标",
    ):
        assert approved in timing
    for rejected in (
        "等首次 later 回踩 5/12",
        "计划超时｜等新 episode",
        "10m 尚无 active 主计划",
        "已触发｜只管保护/目标",
    ):
        assert rejected not in primary
        assert rejected not in timing

    primary_reason_constants = set(re.findall(r"int (REASON_[A-Z0-9_]+) =", primary))
    primary_card_mapper = primary.split("f_reason_card_text() =>", 1)[1].split(
        "bool uiInvalidatedWasPlan", 1
    )[0]
    assert primary_reason_constants
    assert all(name in primary_card_mapper for name in primary_reason_constants)

    timing_reason_constants = set(
        re.findall(r"int (TIMING_REASON_[A-Z0-9_]+) =", timing)
    )
    timing_card_mapper = timing.split("f_timing_reason_card_text() =>", 1)[1].split(
        "f_timing_action_text() =>", 1
    )[0]
    assert timing_reason_constants
    assert all(name in timing_card_mapper for name in timing_reason_constants)
    visible_primary = primary[primary.index("var table card") :]
    visible_timing = timing[timing.index("var table timingCard") :]
    for forbidden in ("epoch / episode", "opportunity", "suppressed ID", "target source"):
        assert forbidden not in visible_primary
        assert forbidden not in visible_timing
    assert "多入已触发｜按计划管理" in timing
    assert "空入已触发｜按计划管理" in timing
    assert "text_color=color.silver" not in visible_primary
    assert "text_color=color.silver" not in visible_timing
    assert "text_color=color.white" in visible_primary
    assert "text_color=color.white" in visible_timing
    assert "bool cardPlanContext = e_opportunityActive or not na(e_opportunityTime) and" in primary
    assert 'cardPlanContext ? f_price(e_invalidation) : "—"' in primary
    assert "bool timingTerminalPulse = timingEventPulse == TIMING_EVENT_LONG_INVALIDATED" in timing
    assert "bool timingCardPlanContext = timingOwnsPlan or timingTerminalPulse" in timing
    assert 'timingCardPlanContext ? f_price(timingPlanInvalidation) : "—"' in timing
    assert "timingEventPulse == TIMING_EVENT_LONG_TARGET_REACHED ? \"多计划到达｜结束\"" in timing
    assert 'timingState == TIMING_LOCKED ? "本计划结束｜等新 10m"' in timing


def test_watch_terminal_ui_does_not_mislabel_observation_as_opposite_plan() -> None:
    primary = _source(PRIMARY_PINE)
    assert "bool uiInvalidatedWasPlan = e_eventPulse == EVENT_INVALIDATED and not na(e_opportunityTime)" in primary
    assert "e_close < e_frozenInvalidation ? DIRECTION_LONG" in primary
    assert "e_close > e_frozenInvalidation ? DIRECTION_SHORT" in primary
    for text in (
        "多观察失效｜结束",
        "空观察失效｜结束",
        "多计划失效｜结束",
        "空计划失效｜结束",
        "观察到期｜等新机会",
    ):
        assert text in primary
    assert "uiInvalidatedWasPlan ?" in primary
    assert "not na(e_opportunityTime) and (e_eventPulse == EVENT_INVALIDATED" in primary


def test_plan_line_and_previous_cloud_defaults_match_trader_contract() -> None:
    primary = _source(PRIMARY_PINE)
    timing = _source(TIMING_PINE)
    assert 'input.bool(false, "显示当前冻结 entry / invalidation / target"' in primary
    assert 'input.bool(true, "显示当前 10m 保护 / 目标"' in timing
    assert 'input.bool(false, "显示 previous-completed 10m EMA5/12"' in timing
    assert "bool timingOwnsPlan" in timing
    assert 'linewidth=1, style=plot.style_linebr' in timing


def test_no_order_alert_dynamic_object_or_future_offset_primitives() -> None:
    forbidden_patterns = (
        r"\bstrategy\s*\(",
        r"\bstrategy\.",
        r"\balertcondition\s*\(",
        r"\balert\s*\(",
        r"\blabel\.new\s*\(",
        r"\bline\.new\s*\(",
        r"\bbox\.new\s*\(",
        r"\boffset\s*=",
    )
    for path in (PRIMARY_PINE, TIMING_PINE):
        code = _source(path)
        for pattern in forbidden_patterns:
            assert re.search(pattern, code) is None, (path.name, pattern)


def test_advisory_inputs_do_not_vote_or_gate() -> None:
    for path in (PRIMARY_PINE, TIMING_PINE):
        code = _strip_comments(_source(path)).lower()
        for token in ("vix", "saty", "divergence", "ta.atr(", "score", "overnight"):
            assert token not in code
        assert "allow_long" not in code
        assert "allow_short" not in code


def test_3m_persistent_suppression_survives_reset_and_blocks_same_id() -> None:
    timing = _source(TIMING_PINE)
    required = (
        "var int timingSuppressedDirection",
        "var int timingSuppressedTime",
        "timingGapReset",
        "timingSuppressedDirection := timingPlanDirection",
        "bool sameAsSuppressed",
        "TIMING_REASON_SUPPRESSED",
        "timingSuppressedDirection := DIRECTION_NONE",
        "Adoption is terminal for this 3m K",
    )
    for token in required:
        assert token in timing
    gap = timing.index("if timingGapReset")
    suppress = timing.index("timingSuppressedDirection := timingPlanDirection", gap)
    clear_plan = timing.index("timingPlanDirection := DIRECTION_NONE", suppress)
    assert suppress < clear_plan


def test_target_source_is_copied_with_the_same_plan_unit_into_3m() -> None:
    timing = _source(TIMING_PINE)
    plan_assignments = (
        "timingPlanDirection := e_opportunityDirection",
        "timingPlanTime := e_opportunityTime",
        "timingPlanEntry := e_entryReference",
        "timingPlanInvalidation := e_invalidation",
        "timingPlanTarget := e_nextNamedLevel",
        "timingPlanTargetSource := e_nextNamedLevelSource",
    )
    positions = [timing.index(token) for token in plan_assignments]
    assert positions == sorted(positions)


def test_replay_cli_is_path_driven_and_private_3m_csv_is_not_bundled() -> None:
    dual = _source(DUAL_REPLAY)
    for token in (
        'parser.add_argument("--ten-minute-csv"',
        'parser.add_argument("--three-minute-csv"',
        'parser.add_argument("--log"',
        'parser.add_argument("--events-csv"',
        "source_bar.timestamp_ms + PRIMARY_INTERVAL_SECONDS * 1000",
        "private_3m_csv_bundled=NO",
    ):
        assert token in dual
    forbidden_name = "CAPITALCOM_SPX500-3-P6-v1.2-33d-export-20260731(1).csv"
    assert not any(path.name == forbidden_name for path in ROOT.rglob("*"))


def test_chinese_spec_freezes_r3_lifetimes_complete_day_and_visual_contract() -> None:
    spec = _source(SPEC)
    required = (
        "phase1-10m-primary-opportunity-3.0",
        "phase1-3m-opportunity-timing-3.0",
        "CONFIRMED_PIVOT_10M",
        "PREVIOUS_COMPLETED_DAY_HIGH",
        "PREVIOUS_COMPLETED_DAY_LOW",
        "00:00",
        "23:50",
        "144",
        "entry permission",
        "entered-plan management",
        "terminal 同 K 绝不 rearm",
        "WATCH 不创建 `OpportunityPlan`",
        "same ID active again -> OPPORTUNITY_SUPPRESSED",
        "多入已触发｜按计划管理",
        "空入已触发｜按计划管理",
        CANONICAL_SHA256,
    )
    for token in required:
        assert token in spec
    assert "POSITION_REVERSAL  = disabled" in spec
