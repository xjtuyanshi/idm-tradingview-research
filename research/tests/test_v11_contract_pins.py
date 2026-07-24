"""Three-way pins: frozen Pine source <-> v11_contract.json <-> ReplicaConfig.

The contract file is only trustworthy if every number it declares can be found
verbatim in the frozen Pine release and equals the replica's loaded config.
A mismatch in any direction is a release failure, not a soft warning.
"""

from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = ROOT / "research"
sys.path.insert(0, str(RESEARCH_DIR))

from v11_pine_replica import ReplicaConfig  # noqa: E402

PINE = (ROOT / "intraday_decision_map_v11_aggressive_clean.pine").read_text(
    encoding="utf-8"
)
CONTRACT = json.loads(
    (RESEARCH_DIR / "config" / "v11_contract.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (ROOT / "release-manifest.json").read_text(encoding="utf-8")
)


def _pine_input(pattern: str) -> float:
    match = re.search(pattern, PINE)
    assert match, f"pattern not found in frozen Pine: {pattern}"
    return float(match.group(1))


def test_contract_identity_matches_release_manifest() -> None:
    assert CONTRACT["engine_version"] == MANIFEST["release"]
    assert CONTRACT["pine_sha256"] == MANIFEST["pine_sha256"]
    assert CONTRACT["pine_file"] == MANIFEST["pine_file"]


def test_lengths_match_pine_input_defaults() -> None:
    lengths = CONTRACT["lengths"]
    assert _pine_input(r'input\.int\((\d+), "Ripster 节奏快线"') == lengths["pace_fast"]
    assert _pine_input(r'input\.int\((\d+), "Ripster 节奏慢线"') == lengths["pace_slow"]
    assert _pine_input(r'input\.int\((\d+), "Ripster 趋势快线"') == lengths["anchor_fast"]
    assert _pine_input(r'input\.int\((\d+), "Ripster 趋势慢线"') == lengths["anchor_slow"]
    assert _pine_input(r'input\.int\((\d+), "ATR 长度"') == lengths["atr"]
    assert _pine_input(r'input\.int\((\d+), "确认结构左右 K 数"') == lengths["pivot"]
    assert _pine_input(r'input\.int\((\d+), "结构突破回看 K 数"') == lengths["structure_lookback"]
    assert _pine_input(r'input\.int\((\d+), "压缩箱回看 K 数"') == lengths["compression_lookback"]


def test_thresholds_match_pine_defaults_and_hardcoded_constants() -> None:
    th = CONTRACT["thresholds"]
    assert _pine_input(r'input\.float\(([\d.]+), "触碰容差 ATR"') == th["touch_atr"]
    assert _pine_input(r'input\.float\(([\d.]+), "突破确认 ATR"') == th["trigger_atr"]
    assert _pine_input(r'input\.float\(([\d.]+), "确认 K 实体占比"') == th["strong_body_ratio"]
    assert _pine_input(r'input\.float\(([\d.]+), "压缩箱最大 ATR"') == th["compression_atr"]
    assert _pine_input(r'input\.float\(([\d.]+), "结构止损缓冲 ATR"') == th["stop_buffer_atr"]
    assert _pine_input(r'input\.float\(([\d.]+), "单笔最大风险 ATR"') == th["max_risk_atr"]
    assert _pine_input(r'input\.float\(([\d.]+), "最低目标空间 R"') == th["min_space_r"]
    # Hard-coded (non-input) rule constants.
    assert PINE.count("0.32 * candleRange") == 2, "close-edge fraction"
    assert PINE.count("0.24 * candleRange") == 2, "pullback same-bar wick"
    assert PINE.count("0.38 * candleRange") == 2, "rejection wick"
    assert th["close_edge_fraction"] == 0.32
    assert th["pullback_wick_fraction"] == 0.24
    assert th["rejection_wick_fraction"] == 0.38
    assert "math.max(2.0 * syminfo.mintick, triggerAtr * atrSeries)" in PINE
    assert th["trigger_buffer_min_ticks"] == 2
    assert PINE.count("longSpaceR >= 0.75") + PINE.count("shortSpaceR >= 0.75") == 2
    assert th["b_space_r"] == 0.75
    assert PINE.count("Series) <= 1.20 * atrSeries") == 2 or PINE.count("1.20 * atrSeries") == 2
    assert th["a_max_ema5_distance_atr"] == 1.20
    assert PINE.count("longSpaceR >= 1.0") == 1 and PINE.count("shortSpaceR >= 1.0") == 1
    assert th["a_space_r"] == 1.00
    assert PINE.count("0.08 * atrSeries") == 2
    assert th["hard_structure_break_atr"] == 0.08
    # Rejection accepts a small body: the immediate branch requires only
    # close-versus-open direction, never strongBull (pine:535-538).
    assert "sweptSupport and lowerWick >= 0.38 * candleRange and\n         close > open" in PINE
    assert th["rejection_requires_strong_body"] is False


def test_phase_constants_match_pine() -> None:
    ph = CONTRACT["phase"]
    assert "ta.ema(close, 21)" in PINE
    assert ph["base_ema_length"] == 21
    assert "(3.0 * safeAtr)" in PINE
    assert ph["atr_normalization_multiple"] == 3.0
    assert "ta.ema(phaseRaw, 3)" in PINE
    assert ph["smoothing_ema_length"] == 3
    assert "phaseSeries >= -23.6" in PINE
    assert ph["bull_floor"] == -23.6
    assert "phaseSeries <= 23.6" in PINE
    assert ph["bear_ceiling"] == 23.6
    assert "ta.stdev(close, 21)" in PINE
    assert ph["stdev_length"] == 21
    assert "phaseDeviation <= 1.10 * atrSeries" in PINE
    assert ph["compression_stdev_atr"] == 1.10


def test_saty_ratios_match_pine_array() -> None:
    match = re.search(r"array\.from\(([-\d.,\s]+)\)", PINE)
    assert match
    pine_ratios = [float(x) for x in match.group(1).replace("\n", " ").split(",")]
    assert pine_ratios == CONTRACT["levels"]["saty_ratios"]


def test_identity_and_execution_pins() -> None:
    ident = CONTRACT["identity"]
    assert "time_close + (chosenSide == SIDE_LONG ? 100 : 200) +" in PINE
    assert "chosenSetup * 10 + chosenGrade" in PINE
    assert ident["signal_id"].startswith("close_time_ms")
    execution = CONTRACT["execution"]
    assert "commission_value=0.0, slippage=2" in PINE
    assert execution["commission_value"] == 0.0
    assert execution["slippage_ticks"] == 2
    assert "default_qty_value=2" in PINE
    assert execution["default_qty"] == 2
    assert "orderQty * 0.5 : orderQty" in PINE
    assert execution["countertrend_qty_multiplier"] == 0.5
    assert PINE.count("qty_percent=50") == 2
    assert PINE.count("qty_percent=25") == 2
    assert PINE.count("qty_percent=engine.plan.t2Reached ? 100 : 25") == 2
    runtime = CONTRACT["runtime"]
    assert "const int ENGINE_CALC_BARS = 1500" in PINE
    assert runtime["engine_calc_bars"] == 1500
    assert "const int RELAY_CALC_BARS = 4000" in PINE
    assert runtime["relay_calc_bars"] == 4000


def test_replica_config_defaults_equal_contract_load() -> None:
    default = ReplicaConfig()
    loaded = ReplicaConfig.from_contract()
    for item in fields(ReplicaConfig):
        assert getattr(default, item.name) == getattr(loaded, item.name), item.name
    th = CONTRACT["thresholds"]
    lengths = CONTRACT["lengths"]
    assert loaded.touch_atr == th["touch_atr"]
    assert loaded.strong_body_ratio == th["strong_body_ratio"]
    assert loaded.max_risk_atr == th["max_risk_atr"]
    assert loaded.pace_fast == lengths["pace_fast"]
    assert loaded.anchor_slow == lengths["anchor_slow"]
    assert loaded.saty_ratios == tuple(CONTRACT["levels"]["saty_ratios"])
