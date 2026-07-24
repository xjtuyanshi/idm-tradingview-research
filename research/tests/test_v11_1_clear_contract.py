"""Static contracts for the v11.1 Clear artifact.

The core promise of 11.1: the signal/plan/order engine is BYTE-IDENTICAL to
the frozen 11.0.0-clean release, so every SignalEvent id, plan and Strategy
Tester result is unchanged by construction.  11.1 only changes presentation
and adds one informational Saty second-rejection AdvisoryEvent.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FROZEN = (ROOT / "intraday_decision_map_v11_aggressive_clean.pine").read_text(
    encoding="utf-8"
)
CLEAR = (ROOT / "intraday_decision_map_v11_1_clear.pine").read_text(
    encoding="utf-8"
)

ENGINE_START = "f_v11_engine(bool processConfirmedClose) =>"
ENGINE_END = "// Dense state + sparse primitive event relay"


def _engine_region(source: str) -> str:
    start = source.index(ENGINE_START)
    end = source.index(ENGINE_END)
    return source[start:end]


def test_identity() -> None:
    assert 'strategy("IDM v11.1 Clear"' in CLEAR
    assert 'const string VERSION_ID = "11.1.0-clear"' in CLEAR
    assert 'strategy("IDM v11 Aggressive Clean"' not in CLEAR


def test_frozen_engine_text_is_verbatim_in_clear() -> None:
    """The entire frozen engine (helpers included) appears byte-for-byte."""

    frozen_engine = _engine_region(FROZEN)
    assert frozen_engine in CLEAR


def _without_comments(source: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in source.splitlines())


def test_advisory_never_trades_or_touches_the_plan() -> None:
    start = CLEAR.index("// Saty second-rejection advisory")
    end = CLEAR.index("// Dense state + sparse primitive event relay")
    advisory = _without_comments(CLEAR[start:end])
    assert "strategy.entry" not in advisory
    assert "strategy.exit" not in advisory
    assert "strategy.close" not in advisory
    assert "plan." not in advisory
    assert "lastSignal" not in advisory
    # Advisory fire path outside the module must also stay order-free.
    fire = _without_comments(
        CLEAR[CLEAR.index("bool newAdvisory"):CLEAR.index("// Optional broker emulator")]
    )
    assert "strategy." not in fire


def test_relay_tuple_extended_to_twenty_and_wired() -> None:
    assert CLEAR.count("advPulse.id, advPulse.level,") == 1
    assert "advisoryIds, advisoryLevels," in CLEAR
    assert "relayAdvisoryIds := advisoryIds" in CLEAR
    assert "lastRelayedAlertAdvisoryId" in CLEAR
    assert "varip int lastRelayedAlertAdvisoryId" in CLEAR


def test_marker_declutter_filters_exist() -> None:
    assert 'input.bool(false, "显示加仓参考小点"' in CLEAR
    assert 'input.bool(true, "显示逆势短打小标"' in CLEAR
    assert "bool markerPrimary = (displaySignal.role == ROLE_INITIAL or" in CLEAR
    assert 'text="逆多"' in CLEAR
    assert 'text="逆空"' in CLEAR
    assert 'text="加"' in CLEAR
    # full-size labels remain for all six grade glyphs
    for glyph in ("买A", "买B", "买C", "卖A", "卖B", "卖C"):
        assert f'text="{glyph}"' in CLEAR


def test_advisory_ui_and_alerts_are_chinese_and_gated() -> None:
    assert '"Saty二拒↑" : "Saty二拒↓"' in CLEAR
    assert "这是位置/风险提醒，不是交易信号" in CLEAR
    assert 'input.bool(true, "启用 Saty 二次拒绝提醒"' in CLEAR
    assert "enableSatyAdvisory and hostIsCanonical3m" in CLEAR
    assert re.search(r"if enableAlerts and enableSatyAlerts\b", CLEAR)


def test_advisory_id_scheme_and_states() -> None:
    assert "time_close + 300 + advRatioIdxLong" in CLEAR
    assert "time_close + 350 + advRatioIdxShort" in CLEAR
    assert "const int ADV_IDLE = 0" in CLEAR
    assert "const int ADV_WATCH = 1" in CLEAR
    assert "const int ADV_DEPARTED = 2" in CLEAR
    assert "satyDepartureAtr * advDailyAtr" in CLEAR
    assert CLEAR.count('"Saty advisory id"') == 1


def test_frozen_release_file_is_untouched() -> None:
    from hashlib import sha256

    digest = sha256(
        (ROOT / "intraday_decision_map_v11_aggressive_clean.pine").read_bytes()
    ).hexdigest()
    assert digest == "77c6fb4014f3ba93d741bbe445438db0664609326145c82fafe9403b8b80cd03"
