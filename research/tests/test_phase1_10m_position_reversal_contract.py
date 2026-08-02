"""Static Pine/source contract and generator parity for POSITION_REVERSAL v1.3."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import sys

import pytest

from research.generate_phase1_10m_position_reversal_pine_v1 import (
    CANONICAL_BLOCK,
    CANONICAL_BLOCK_SHA256,
    PINE_SOURCE,
)
from research.phase1_10m_position_reversal_oracle import (
    BAR_INTERVAL_MS,
    CANONICAL_CONTRACT_SHA256,
    DAILY_TIMEFRAME,
    DEFAULT_STALE_AFTER_MS,
    EXPECTED_SYMBOL,
    IDENTITY_ASCII_ALNUM,
    IDENTITY_COMPONENT_MAX_LENGTH,
    IDENTITY_COMPONENT_SAFE_CHARS,
    IDENTITY_ENCODING_VERSION,
    LANE_ID,
    MARKER_TEXTS,
    MAX_REACTION_BARS,
    MINIMUM_TICK,
    MINIMUM_SPACE_R,
    OPPORTUNITY_LIFETIME_BARS,
    PROTOCOL_VERSION,
    REARM_ATR,
    ReversalConfig,
    SourceKind,
    STOP_BUFFER_ATR,
    canonical_source_identity,
)

from research.tests.fixture_phase1_10m_position_reversal import (
    prior_atr,
    resistance_band,
    support_band,
)

ROOT = Path(__file__).resolve().parents[2]
PINE = ROOT / "idm_phase1_10m_position_reversal_v1.pine"
ORACLE = ROOT / "research/phase1_10m_position_reversal_oracle.py"
GENERATOR = ROOT / "research/generate_phase1_10m_position_reversal_pine_v1.py"
FROZEN_PRIMARY = ROOT / "idm_phase1_10m_primary_opportunity_v3.pine"
FROZEN_TIMING = ROOT / "idm_phase1_3m_opportunity_timing_v3.pine"
CANONICAL_SHA256 = "52e29ddefc34d02e4f2ac3675329d6d78d062a795c8dcb8b0f45d8200e66805b"
HISTORICAL_R31_PRIMARY_SHA256 = (
    "ec2f8eee96960d8f95c6a2035181bfa0e319e498bdd12a988f2a9678bde138ba"
)
HISTORICAL_R31_TIMING_SHA256 = (
    "f349baa860124a386396b173780567cc842a3591f894b99d97381d6726af6c8f"
)
CURRENT_R32_PRIMARY_PRESENTATION_SHA256 = (
    "aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2"
)
CURRENT_R32_TIMING_PRESENTATION_SHA256 = (
    "f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e"
)
START = f"// POSITION_REVERSAL_10M_CANONICAL_BEGIN {PROTOCOL_VERSION}"
END = f"// POSITION_REVERSAL_10M_CANONICAL_END {PROTOCOL_VERSION}"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_comments(code: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in code.splitlines())


def _canonical_block(code: str) -> str:
    start = code.index(START)
    end = code.index(END) + len(END)
    return code[start:end]


def test_delivery_files_protocol_and_frozen_constants_exist() -> None:
    for path in (PINE, ORACLE, GENERATOR):
        assert path.is_file()
    assert PROTOCOL_VERSION == "phase1-10m-position-reversal-1.3"
    assert LANE_ID == "POSITION_REVERSAL"
    assert EXPECTED_SYMBOL == "CAPITALCOM:SPX500"
    assert BAR_INTERVAL_MS == 600_000
    assert MAX_REACTION_BARS == 3
    assert MINIMUM_SPACE_R == 1.0
    assert STOP_BUFFER_ATR == 0.002
    assert REARM_ATR == 0.12
    assert OPPORTUNITY_LIFETIME_BARS == 12
    assert DEFAULT_STALE_AFTER_MS == 36 * 60 * 60 * 1000
    assert MINIMUM_TICK == 0.1
    assert DAILY_TIMEFRAME == "D"
    assert IDENTITY_ENCODING_VERSION == "CID1"
    assert IDENTITY_COMPONENT_MAX_LENGTH == 64
    assert IDENTITY_ASCII_ALNUM == (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    )
    assert IDENTITY_COMPONENT_SAFE_CHARS == (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
    )
    assert canonical_source_identity("SATY:Map_Level-1", "v1.2") == (
        "CID1:SATY:Map_Level-1@v1.2"
    )
    assert SourceKind.SATY_ATR_MAP_LEVEL.value == "SATY_ATR_MAP_LEVEL"
    assert (
        SourceKind.PREVIOUS_COMPLETED_DAILY_ATR.value
        == "PREVIOUS_COMPLETED_DAILY_ATR"
    )
    assert MARKER_TEXTS == ("支撑观察", "反弹确认", "阻力观察", "压回确认")
    assert len(CANONICAL_CONTRACT_SHA256) == 64


def test_generator_direct_check_reproduces_pine_byte_for_byte() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _source(PINE) == PINE_SOURCE


def test_canonical_block_is_exact_and_hash_pinned() -> None:
    block = _canonical_block(_source(PINE))
    assert block == CANONICAL_BLOCK
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == CANONICAL_SHA256
    assert CANONICAL_BLOCK_SHA256 == CANONICAL_SHA256
    assert f'string CANONICAL_CONTRACT_SHA256 = "{CANONICAL_CONTRACT_SHA256}"' in block


def test_current_r32_presentation_sources_are_byte_identical() -> None:
    missing = [
        path.name for path in (FROZEN_PRIMARY, FROZEN_TIMING) if not path.is_file()
    ]
    if missing:
        pytest.skip(
            "R3.2 presentation-source verification requires overlay onto the handoff/full "
            f"repository; missing: {', '.join(missing)}"
        )
    assert HISTORICAL_R31_PRIMARY_SHA256 != CURRENT_R32_PRIMARY_PRESENTATION_SHA256
    assert HISTORICAL_R31_TIMING_SHA256 != CURRENT_R32_TIMING_PRESENTATION_SHA256
    assert _sha(FROZEN_PRIMARY) == CURRENT_R32_PRIMARY_PRESENTATION_SHA256
    assert _sha(FROZEN_TIMING) == CURRENT_R32_TIMING_PRESENTATION_SHA256


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_symbol", "OTHER:SPX"),
        ("stop_buffer_atr", 0.01),
        ("rearm_atr", 0.25),
        ("opportunity_lifetime_bars", 3),
        ("minimum_tick", 0.01),
    ),
)
def test_python_rejects_noncanonical_values_pine_cannot_express(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        ReversalConfig(**{field: value})  # type: ignore[arg-type]
    assert ReversalConfig() == ReversalConfig(
        expected_symbol=EXPECTED_SYMBOL,
        interval_ms=BAR_INTERVAL_MS,
        max_reaction_bars=MAX_REACTION_BARS,
        minimum_space_r=MINIMUM_SPACE_R,
        stop_buffer_atr=STOP_BUFFER_ATR,
        rearm_atr=REARM_ATR,
        opportunity_lifetime_bars=OPPORTUNITY_LIFETIME_BARS,
        minimum_tick=MINIMUM_TICK,
    )


def test_indicator_is_native_standard_10m_and_confirmed_only() -> None:
    code = _source(PINE)
    assert code.startswith("//@version=6\n")
    assert 'indicator("IDM Phase 1｜10m 位置反转 v1.3", overlay=true)' in code
    assert "scale=" not in code
    assert 'ticker.standard(syminfo.tickerid) == EXPECTED_SYMBOL' in code
    assert 'timeframe.period == "10"' in code
    assert "chart.is_standard" in code
    assert "barstate.isconfirmed" in code
    assert "bool outwardSurfaceOk = sourceSurfaceOk and barstate.isconfirmed" in code


def test_no_3m_mtf_vix_divergence_alert_order_strategy_or_dynamic_objects() -> None:
    code = _strip_comments(_source(PINE))
    forbidden_patterns = (
        r"\brequest\.security(?:_lower_tf)?\s*\(",
        r"\balertcondition\s*\(",
        r"\balert\s*\(",
        r"\bstrategy\s*\(",
        r"\bstrategy\.(?:entry|exit|order|close|cancel)\s*\(",
        r"\blabel\.new\s*\(",
        r"\bline\.new\s*\(",
        r"\bbox\.new\s*\(",
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, code, flags=re.IGNORECASE) is None
    for token in ("VIX", "divergence", "MACD", 'timeframe.period == "3"'):
        assert token not in code


def test_only_four_short_price_anchored_plotshapes_exist() -> None:
    code = _source(PINE)
    lines = [line.strip() for line in code.splitlines() if "plotshape(" in line]
    assert len(lines) == 4
    for marker, line in zip(MARKER_TEXTS, lines, strict=True):
        assert f'text="{marker}"' in line
        assert "location=location.absolute" in line
        assert "markerPrice : na" in line
    assert re.search(r"(?<!shape)\bplot\s*\(", _strip_comments(code)) is None
    assert "plotchar(" not in code
    assert "plotarrow(" not in code


def test_card_is_fixed_to_five_rows_and_has_no_marker_spam() -> None:
    code = _source(PINE)
    assert 'bool showCard = input.bool(false, "显示五行状态卡"' in code
    assert "table.new(position.bottom_right, 2, 5" in code
    assert "table.new(position.top_right" not in code
    assert 'table.cell(card, 0, 2, "有效期"' in code
    assert 'string validityText = "SATy至 "' in code
    assert 'str.format_time(value, "MM-dd HH:mm", "America/New_York") + " ET"' in code
    row_numbers = [int(item) for item in re.findall(r"table\.cell\(card,\s*[01],\s*(\d+)", code)]
    assert row_numbers
    assert min(row_numbers) == 0
    assert max(row_numbers) == 4
    assert set(row_numbers) == {0, 1, 2, 3, 4}
    assert "table.clear(card, 0, 0, 1, 4)" in code


def test_manual_source_contract_is_allowlisted_absolute_and_provenance_complete() -> None:
    code = _source(PINE)
    required = (
        'string SOURCE_KIND_SATY_ATR_MAP_LEVEL = "SATY_ATR_MAP_LEVEL"',
        'string SOURCE_KIND_PREVIOUS_COMPLETED_DAILY_ATR = "PREVIOUS_COMPLETED_DAILY_ATR"',
        'string DAILY_TIMEFRAME = "D"',
        "f_band_kind_allowed",
        "f_atr_kind_allowed",
        "source_id",
        "source_version",
        "lower_bound",
        "upper_bound",
        "published_at",
        "level_known_at",
        "valid_until",
        "stability",
        "publishedAt <= barOpen",
        "knownAt <= barOpen",
        "barOpen < validUntil",
        "publishedAt < validUntil",
        "knownAt < validUntil",
        "barOpen - math.max(publishedAt, knownAt) <= staleMs",
        "stability == STABILITY_PRIOR",
        "duplicateIdentityConflict",
        "atrStabilityInput",
        "stability == STABILITY_PRIOR",
        "atrPublishedAtInput",
        "atrKnownAtInput",
        "atrValidUntilInput",
        "atrSourceTimeframeInput",
        "atrCompletedSourceOpenInput",
        "atrCompletedSourceCloseInput",
        "sourceClose <= knownAt",
        "sourceClose > sourceOpen",
        "int DEFAULT_STALE_AFTER_MS = 129600000",
        "int staleMs = DEFAULT_STALE_AFTER_MS",
        "DEFAULT_STALE_AFTER_MS == 129600000",
        'string IDENTITY_ENCODING_VERSION = "CID1"',
        "int IDENTITY_COMPONENT_MAX_LENGTH = 64",
        'string IDENTITY_COMPONENT_SAFE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"',
        "f_identity_component_ok",
        "value == str.trim(value)",
        "str.contains(IDENTITY_ASCII_ALNUM, firstCharacter)",
        "str.contains(IDENTITY_ASCII_ALNUM, lastCharacter)",
        "str.contains(IDENTITY_COMPONENT_SAFE_CHARS, character)",
        "f_canonical_identity_component",
        "f_identity_key",
        'IDENTITY_ENCODING_VERSION + ":" + sourceId + "@" + sourceVersion',
        "anyBandIdentityInvalid ? SURFACE_BAND_CONTRACT",
    )
    for token in required:
        assert token in code
    assert "sourceFreshnessHours" not in code
    assert "DEFAULT_STALE_HOURS" not in code
    assert "STABILITY_FORMING" in code
    assert "STABILITY_UNSTABLE" in code
    assert "sourceSurfaceOk" in code
    assert "latestPlanSuppressed := true" in code


def test_python_effective_material_matches_generated_pine_field_order() -> None:
    assert support_band().effective_fingerprint == (
        "CID1|B|SATY_ATR_MAP_LEVEL|CID1:SATY-ATR-LOWER-TRIGGER@v1|SUPPORT|"
        "74212045905010|74212045905010|1785441600000|1785441600000|"
        "1785528000000"
    )
    assert resistance_band().effective_fingerprint == (
        "CID1|B|SATY_ATR_MAP_LEVEL|CID1:SATY-ATR-UPPER-TRIGGER@v1|RESISTANCE|"
        "74677954094990|74677954094990|1785441600000|1785441600000|"
        "1785528000000"
    )
    assert prior_atr().effective_fingerprint == (
        "CID1|A|PREVIOUS_COMPLETED_DAILY_ATR|"
        "CID1:SATY-ATR-MAP@2026-07-31-v1|"
        "987093622839|1785441600000|1785441600000|1785528000000|D|"
        "1785384000000|1785441600000"
    )


def test_pine_effective_identity_host_reasons_and_same_side_gate_are_explicit() -> None:
    code = _source(PINE)
    required = (
        "f_identity_component_ok",
        "f_canonical_identity_component",
        "f_identity_key",
        "f_band_effective_key",
        "f_atr_effective_key",
        "bandCanonicalSourceId",
        "bandCanonicalSourceVersion",
        "bandIdentityKey",
        "atrCanonicalSourceId",
        "atrCanonicalSourceVersion",
        "atrIdentityKey",
        "episodeSourceIdentityKey",
        "episodeSourceEffectiveKey",
        "frozenTargetIdentityKey",
        "frozenTargetEffectiveKey",
        "frozenAtrIdentityKey",
        "frozenAtrEffectiveKey",
        '"PR-EP-"',
        '"PR-OP-"',
        "仅支持 CAPITALCOM:SPX500",
        "仅支持原生 10m",
        "仅支持标准 K 线",
        "SATy/ATR 来源未启用",
        "SATy/ATR 来源未知",
        "SATy/ATR 来源已过期",
        "ATR 上一完成日合同无效",
        "int EV_MULTIPLE_SAME_SIDE = 10",
        "int RS_MULTIPLE_SAME_SIDE = 13",
        'string touchedEffectiveMaterial = ""',
        '"#" + touchedEffectiveMaterial + "|" + atrEffectiveKey',
        "bool multipleSameSide =",
        '"PR-MULTIPLE-SAME-SIDE-"',
        "同向多位置同时触及｜NO_PERMISSION",
    )
    for token in required:
        assert token in code
    assert 'not sourceSurfaceOk ? f_surface_reason_text(sourceSurfaceReason)' in code
    assert "outwardSurfaceOk and showMarkers" in code
    assert 'IDENTITY_ENCODING_VERSION + "|B|" + str.trim(sourceKind)' in code
    assert 'IDENTITY_ENCODING_VERSION + "|A|" + str.trim(sourceKind)' in code
    assert "int EFFECTIVE_NUMBER_SCALE = 10000000000" in code
    assert "f_scaled(float value)" in code
    assert "if array.get(bandValid, i)\n        if array.get(bandValid, i)" not in code
    assert (
        "array.get(bandIdentityKey, i) == array.get(bandIdentityKey, j)"
        in code
    )
    assert "array.get(bandSourceId, i) == array.get(bandSourceId, j)" not in code
    assert "array.get(bandSourceVersion, i) == array.get(bandSourceVersion, j)" not in code
    assert (
        "itemValid ? f_band_effective_key(itemKind, itemIdentityKey"
        in code
    )
    assert "atrValid ? f_atr_effective_key(atrSourceKindInput, atrIdentityKey" in code
    assert 'episodeSourceId + "@" + episodeSourceVersion' not in code
    assert 'frozenTargetSourceId + "@" + frozenTargetSourceVersion' not in code
    assert (
        '"PR-EP-" + (side == ROLE_SUPPORT ? "L-" : "S-") + '
        'episodeSourceIdentityKey + "#"'
    ) in code
    assert code.count(
        '"PR-OP-" + (side == ROLE_SUPPORT ? "L-" : "S-") + '
        'episodeSourceIdentityKey + "#"'
    ) == 2
    assert "latestTargetSource := frozenTargetIdentityKey" in code
    assert "str.trim(sourceId)" not in code
    assert "str.trim(sourceVersion)" not in code


def test_first_valid_contiguous_bar_after_disabled_state_is_not_discarded() -> None:
    block = _canonical_block(_source(PINE))
    reset_branch = block.index("if not sourceSurfaceOk or gapReset or not sourceContextOk")
    valid_branch = block.index("else\n        // A source/gap reset consumes only the reset bar", reset_branch)
    restore = block.index("if st == ST_DISABLED", valid_branch)
    restore_wait = block.index("st := ST_WAIT_CLEAR", restore)
    terminal_roll = block.index(
        "if st == ST_READY or st == ST_FAILED or st == ST_EXPIRED", restore_wait
    )
    eligible_wait = block.index("else if st == ST_WAIT_CLEAR", terminal_roll)
    assert reset_branch < valid_branch < restore < restore_wait < terminal_roll < eligible_wait
    assert "else if st == ST_DISABLED" not in block
    assert "resetThisBar" not in block


def test_fixed_state_machine_and_accepted_break_priority_are_mechanical() -> None:
    block = _canonical_block(_source(PINE))
    for token in (
        "int ST_WAIT_CLEAR = 0",
        "int ST_APPROACH = 1",
        "int ST_REACTION = 2",
        "int ST_READY = 3",
        "int ST_FAILED = 4",
        "int ST_EXPIRED = 5",
        "if needsClear",
        "else if st == ST_APPROACH",
        "else if st == ST_WAIT_CLEAR",
    ):
        assert token in block

    approach = block.index("else if st == ST_APPROACH")
    approach_break = block.index("if acceptedBreak", approach)
    approach_reaction = block.index("else if confirmedReaction", approach_break)
    approach_expiry = block.index("else if reactionBarsSeen >= MAX_REACTION_BARS", approach_reaction)
    touch = block.index("else if touchedCount == 1", approach_expiry)
    touch_break = block.index("if acceptedBreak", touch)
    touch_reaction = block.index("else if confirmedReaction", touch_break)
    assert approach_break < approach_reaction < approach_expiry < touch
    assert touch_break < touch_reaction
    assert block.count("ev := EV_ACCEPTED_BREAK") == 2
    assert block.count("needsClear := true") >= 5


def test_target_is_frozen_at_touch_nearest_first_and_never_skips_consumed_target() -> None:
    block = _canonical_block(_source(PINE))
    touch = block.index("else if touchedCount == 1")
    freeze_loop = block.index("for i = 0 to 3", touch)
    candidate = block.index("float candidatePrice", freeze_loop)
    better = block.index("bool better =", candidate)
    freeze = block.index("frozenTargetPrice := candidatePrice", better)
    reaction = block.index("bool confirmedReaction", freeze)
    plan_gate = block.index("f_plan_gate", reaction)
    assert touch < freeze_loop < candidate < better < freeze < reaction < plan_gate
    assert "candidatePrice < frozenTargetPrice" in block
    assert "candidatePrice > frozenTargetPrice" in block
    assert "candidatePrice == frozenTargetPrice and i < frozenTargetOrder" in block
    assert "bool targetConsumed = targetPresent" in block
    assert (
        "side == ROLE_SUPPORT ? episodeHigh >= targetPrice : "
        "episodeLow <= targetPrice"
    ) in block
    assert "targetConsumed ? ST_FAILED" in block
    assert "spaceR < MINIMUM_SPACE_R ? ST_FAILED : ST_READY" in block
    assert block.count("frozenTargetPrice := candidatePrice") == 1


def test_same_bar_reaction_visible_at_close_and_payload_is_frozen_once() -> None:
    block = _canonical_block(_source(PINE))
    same_bar = block.index("else if confirmedReaction", block.index("else if touchedCount == 1"))
    reaction_state = block.index("st := ST_REACTION", same_bar)
    gate = block.index("f_plan_gate", reaction_state)
    ready = block.index("if planState == ST_READY", gate)
    visible = block.index("latestVisibleAt := time_close", ready)
    expiry = block.index(
        "latestExpiresAt := time_close + OPPORTUNITY_LIFETIME_BARS * BAR_INTERVAL_MS",
        visible,
    )
    assert same_bar < reaction_state < gate < ready < visible < expiry
    for field in (
        "latestOpportunityId",
        "latestEpisodeId",
        "latestDirection",
        "latestTrigger",
        "latestInvalidation",
        "latestTarget",
        "latestTargetSource",
        "latestConfirmationTime",
        "latestVisibleAt",
        "latestExpiresAt",
        "latestRisk",
        "latestReward",
        "latestSpaceR",
    ):
        assert f"var " in block[: block.index(field) + len(field)]
    assert "latestTrigger := trigger" in block
    assert "latestInvalidation := invalidation" in block
    assert "latestTarget := frozenTargetPrice" in block


def test_wait_clear_requires_a_strictly_later_whole_bar_and_point_twelve_atr() -> None:
    block = _canonical_block(_source(PINE))
    terminal_state_roll = block.index("if st == ST_READY or st == ST_FAILED or st == ST_EXPIRED")
    wait_clear = block.index("if needsClear", terminal_state_roll)
    distance = block.index("float clearDistance = REARM_ATR * frozenAtr", wait_clear)
    whole_support = block.index("low > frozenUpper and close >= frozenUpper + clearDistance", distance)
    whole_resistance = block.index("high < frozenLower and close <= frozenLower - clearDistance", distance)
    clear_event = block.index("ev := EV_WAIT_CLEAR_COMPLETED", whole_resistance)
    next_episode = block.index("else if st == ST_WAIT_CLEAR", clear_event)
    assert terminal_state_roll < wait_clear < distance < whole_support < whole_resistance < clear_event < next_episode
    assert block.count("needsClear := true") >= 5
    # `needsClear` is set on a terminal bar.  On the strictly later evaluation,
    # the mutually exclusive clear branch consumes the whole clear bar; only a
    # later bar can reach the new-touch branch.
    assert "else if st == ST_WAIT_CLEAR" in block


def test_python_oracle_exposes_stable_serializable_payload_and_canonical_ids() -> None:
    code = _source(ORACLE)
    required = (
        "@dataclass(frozen=True, slots=True)\nclass OpportunityPayload",
        "def to_dict(self) -> dict[str, object]:",
        "def to_json(self) -> str:",
        '"B",',
        '"A",',
        'IDENTITY_ENCODING_VERSION: Final[str] = "CID1"',
        "IDENTITY_COMPONENT_MAX_LENGTH: Final[int] = 64",
        'IDENTITY_COMPONENT_SAFE_CHARS: Final[str] = IDENTITY_ASCII_ALNUM + "._:-"',
        "def canonical_identity_component(value: str) -> str:",
        "def canonical_source_identity(source_id: str, source_version: str) -> str:",
        "self.identity,",
        "EFFECTIVE_NUMBER_SCALE",
        "str(_scaled_number(self.lower_bound))",
        "str(_scaled_number(self.value))",
        "source_fingerprint",
        "target_fingerprint",
        "atr_fingerprint",
        "source_valid_until_ms",
        "target_valid_until_ms",
        "atr_valid_until_ms",
        "self._opportunities.append(opportunity)",
        "return tuple(self._opportunities)",
        "visible_at_ms = bar.visible_at_ms",
        "target_candidate = self._frozen_target",
        "self._episode_high >= target",
        "self._episode_low <= target",
        "if consumed:",
        "if space_r < self.config.minimum_space_r:",
    )
    for token in required:
        assert token in code
    assert "self.source_id.strip()" not in code
    assert "self.source_version.strip()" not in code
