"""Static contracts for v11.2 Clear: engine still frozen, filters display-only."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN = (ROOT / "intraday_decision_map_v11_aggressive_clean.pine").read_text(
    encoding="utf-8"
)
CLEAR2 = (ROOT / "intraday_decision_map_v11_2_clear.pine").read_text(
    encoding="utf-8"
)

ENGINE_START = "f_v11_engine(bool processConfirmedClose) =>"
ENGINE_END = "// Dense state + sparse primitive event relay"


def _without_comments(source: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in source.splitlines())


def test_identity() -> None:
    assert 'strategy("IDM v12 Follower"' in CLEAR2
    assert 'const string VERSION_ID = "13.1.0-declutter"' in CLEAR2


def _unique_slice(source: str, start: str, end: str) -> str:
    assert source.count(start) == 1, f"start marker count != 1: {start!r}"
    assert source.count(end) == 1, f"end marker count != 1: {end!r}"
    i = source.index(start)
    j = source.index(end)
    assert i < j
    return source[i:j]


def test_frozen_engine_text_is_verbatim() -> None:
    # ChatGPT review P0-3: substring containment only proves the OLD slice
    # exists somewhere.  The real contract: the ACTIVE marker-to-marker span
    # must BEGIN with the frozen engine byte-for-byte (unique in the file),
    # and the only extra content in the span is the documented 11.1 Saty
    # advisory insert -- nothing else may creep in before the relay marker.
    frozen_engine = _unique_slice(FROZEN, ENGINE_START, ENGINE_END)
    current_span = _unique_slice(CLEAR2, ENGINE_START, ENGINE_END)
    assert current_span.startswith(frozen_engine)
    assert CLEAR2.count(frozen_engine) == 1
    remainder = current_span[len(frozen_engine):]
    assert "Saty second-rejection advisory" in remainder[:400]


def test_ledger_driven_defaults() -> None:
    assert 'input.bool(false, "显示逆势短打小标"' in CLEAR2
    # 13.1 declutter: C-grade research marks hidden by default, and the
    # C-toggle must gate exactly the two C plotshapes.
    assert 'input.bool(false, "显示 C 级研究标记"' in CLEAR2
    assert CLEAR2.count("showCGradeMarks and hostIsCanonical3m") == 2
    # 13.1 heartbeat: daily channel self-test push exists and is input-gated.
    assert 'input.bool(true, "每日 09:30 通道自检推送"' in CLEAR2
    assert CLEAR2.count("通道自检 OK") == 1
    assert 'input.bool(false, "显示趋势启动信号"' in CLEAR2
    assert 'input.bool(false, "显示加仓参考小点"' in CLEAR2
    assert 'input.bool(true, "显示 Saty 日 ATR 梯位"' in CLEAR2
    assert 'input.bool(false, "只推送顺势信号"' in CLEAR2
    assert 'input.bool(true, "不推送趋势启动类"' in CLEAR2
    assert 'input.bool(true, "只在美股常规时段推送 (09:30-16:00 ET)"' in CLEAR2


def test_alert_filter_is_notification_layer_only() -> None:
    # the filter helper must gate alert() calls but never orders
    assert CLEAR2.count("f_alert_pass(") == 3  # 1 def + 2 call sites
    code = _without_comments(CLEAR2)
    start = code.index("f_alert_pass(int")
    end = code.index("roleOk and ctOk and setupOk and sessionOk") + 50
    assert "strategy." not in code[start:end]
    # order dispatch remains ungated by the alert filter
    assert "if enableOrders and ordersAllowed and dispatchSignalOrder" in CLEAR2


def test_sawtooth_plots_moved_to_data_window() -> None:
    assert 'plot(engine.support, "S1 最近支撑", color=na, display=display.data_window)' in CLEAR2
    assert 'plot(planEntry, "计划 Entry", color=na, display=display.data_window)' in CLEAR2
    assert "style=plot.style_linebr" not in CLEAR2
    assert "planLnEntry" in CLEAR2 and "planLnT2" in CLEAR2
    assert "ladderLines" in CLEAR2 and '"昨高"' in CLEAR2 and '"昨低"' in CLEAR2


def test_marker_gating_includes_ignition_filter() -> None:
    assert "bool markerSetupOk = displaySignal.setup != SETUP_IGNITION or showIgnitionSignals" in CLEAR2


def test_frozen_release_untouched() -> None:
    digest = sha256(
        (ROOT / "intraday_decision_map_v11_aggressive_clean.pine").read_bytes()
    ).hexdigest()
    assert digest == "77c6fb4014f3ba93d741bbe445438db0664609326145c82fafe9403b8b80cd03"

def test_v12_follower_module_contract():
    """v12 follower: engine-untouched execution overlay invariants."""
    assert 'strategy("IDM v12 Follower"' in CLEAR2
    assert "type F12State" in CLEAR2
    # the follower never touches engine or plan state
    module = CLEAR2.split("v12 跟单模块 (follower)")[1].split(
        "Static Saty daily ladder")[0]
    assert "strategy." not in module
    assert "engine.plan.active" in module  # read-only plan gate
    # stop is assigned exactly once (at open); it is never tightened
    assert module.count("s.stop := sig.stop") == 1
    assert module.count("s.stop :=") == 1
    # 12.1: pre-registered forward protocol constants exist and are armed
    assert 'const string F12_PROTOCOL_ID = "F12-LR-AM-1POS-S0-T50/25/25-CD30-COST0.5-MINR3-v2"' in CLEAR2
    import re as _re
    m = _re.search(r"const int F12_FORWARD_START_MS = (\d+)", CLEAR2)
    assert m and int(m.group(1)) == 1784757600000
    assert 'const float F12_MIN_RISK_PTS = 3.0' in CLEAR2
    # pure core: one definition, exactly two call sites (canonical + relay)
    assert CLEAR2.count("f_f12_core(bool processBar") == 1
    assert CLEAR2.count("] = f_f12_core(") == 1
    assert CLEAR2.count("    f_f12_core(f12Enable and time_close <= timenow") == 1
    # the core stays free of side effects (CE10057 discipline)
    core = CLEAR2.split("f_f12_core(bool processBar")[1].split(
        "// Canonical 3m instance")[0]
    assert "alert(" not in core and "label.new" not in core
    assert "displaySignal" not in core and "newSignal" not in core
    # geometry guard exists and gates the open path
    assert "f_f12_geometry_ok(sig)" in core
    # follower takes rejections only
    assert "sig.setup == SETUP_LEVEL_REJECTION" in module
    # v12 defaults: enabled, morning+midday, 30-min cooldown, countertrend on
    assert 'input.bool(true, "启用 v12 跟单' in CLEAR2
    assert 'input.string("早午盘 09:30-14:00", "跟单时段' in CLEAR2
    assert 'input.int(30, "全额止损后同向冷却' in CLEAR2
    assert 'input.bool(true, "跟随逆势拒绝"' in CLEAR2
    assert 'input.bool(false, "同步推送研究信号（买A/卖A等，默认关）"' in CLEAR2
    assert 'input.bool(false, "保留旧版计划事件推送"' in CLEAR2
    # 12.0.1: cost dual-track is display-only; engine-event marks hidden in v12
    assert 'input.float(0.5, "成本假设' in CLEAR2
    assert 'input.bool(false, "显示引擎计划事件标记' in CLEAR2
    # both push paths for legacy plan events carry the f12 gate (3m + relay)
    assert CLEAR2.count("not f12Enable or f12EnginePushes") == 2

def test_v12_pane_consistency_mirror():
    """3m and 10m must render the same follower state (state relay mirror)."""
    import re
    assert "f_f12_relay_frame" in CLEAR2
    # 12.2: ring buffer discipline — every historical label goes through the
    # keeper; the old delete-and-recreate churn helpers are gone.
    assert "const int HISTORY_LABEL_CAP = 330" in CLEAR2
    assert CLEAR2.count("f_keep_label(label.new(") == 8
    assert "f_fresh_label" not in CLEAR2
    assert "f_fresh_line" not in CLEAR2
    assert CLEAR2.count("= request.security_lower_tf(") == 2  # events + state
    # both hosts render through the unified disp values
    assert "int dispF12Dir = hostIsCanonical3m ? frDir : m12Dir" in CLEAR2
    assert ("bool f12Vis = f12Enable and (hostIsCanonical3m or hostIs10m) and"
            in CLEAR2)
    assert 'table.cell(dash, 1, 0, "IDM v12｜" + hostText' in CLEAR2
    # the mirror never writes follower state back (one source of truth)
    mirror = CLEAR2.split("v12 状态镜像")[1].split("var line f12LnEntry")[0]
    assert not re.search(r"f12\.\w+ :=", mirror)
