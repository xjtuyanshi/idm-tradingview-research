from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PINE = ROOT / "intraday_decision_map_v11_aggressive_clean.pine"
SOURCE = PINE.read_text(encoding="utf-8")


def test_v11_is_a_new_direct_trigger_engine():
    assert 'strategy("IDM v11 Aggressive Clean"' in SOURCE
    assert 'const string VERSION_ID = "11.0.0-clean"' in SOURCE
    for setup in (
        "SETUP_IGNITION",
        "SETUP_PULLBACK",
        "SETUP_BREAKOUT",
        "SETUP_LEVEL_REJECTION",
    ):
        assert setup in SOURCE
    for legacy_episode_term in (
        "EPISODE_FIRST_TEST",
        "EPISODE_DEPARTED",
        "EPISODE_RETEST_HELD",
        "episodeExpiryBars",
        "departureAtr",
    ):
        assert legacy_episode_term not in SOURCE


def test_three_minute_is_canonical_and_ten_minute_is_confirmed_context():
    assert 'const string TF_ENGINE = "3"' in SOURCE
    assert 'const string TF_CONTEXT = "10"' in SOURCE
    assert "syminfo.tickerid, TF_ENGINE," in SOURCE
    assert "f_v11_engine(time_close <= timenow)" in SOURCE
    assert "if hostIsCanonical3m\n    engine := f_v11_engine(barstate.isconfirmed)" in SOURCE
    assert "V11Snapshot requestedEngine = request.security(" in SOURCE
    assert "if not na(requestedEngine)\n        engine := requestedEngine" in SOURCE
    assert "not na(rawEngine)" not in SOURCE
    assert "time_close[1], close[1]" in SOURCE
    assert "lookahead=barmerge.lookahead_on" in SOURCE
    assert 'bool ordersAllowed = hostIsCanonical3m and barstate.isconfirmed' in SOURCE
    assert "if enableOrders and ordersAllowed and dispatchSignalOrder" in SOURCE


def test_ten_minute_relay_keeps_middle_three_minute_events():
    assert "f_sparse_3m_event_pulse()" in SOURCE
    assert "request.security_lower_tf(" in SOURCE
    assert "syminfo.tickerid, TF_ENGINE, f_sparse_3m_event_pulse()" in SOURCE
    assert "f_sparse_event_bridge()" not in SOURCE
    assert "relaySignalTimes" in SOURCE
    assert "displaySignal.eventTime" in SOURCE
    assert "10分钟同源事件 #" in SOURCE


def test_runtime_budget_avoids_unbounded_nested_lower_tf_collections():
    # Returning 17 lower-TF arrays for every bar in an unlimited host dataset
    # was the likely cause of TradingView's line-less "Unknown error" on 10m.
    assert "calc_bars_count=1500" in SOURCE
    assert "const int ENGINE_CALC_BARS = 1500" in SOURCE
    assert "const int RELAY_CALC_BARS = 4000" in SOURCE
    assert "calc_bars_count=ENGINE_CALC_BARS" in SOURCE
    assert "calc_bars_count=RELAY_CALC_BARS" in SOURCE

    relay_start = SOURCE.index("request.security_lower_tf(")
    relay_end = SOURCE.index(")", relay_start)
    relay_call_head = SOURCE[relay_start:relay_end]
    assert 'syminfo.tickerid, "1"' not in relay_call_head
    assert "f_sparse_event_bridge" not in SOURCE


def test_no_global_signal_starvation_gates_returned():
    lower = SOURCE.lower()
    for forbidden in (
        "daily signal quota",
        "signalsperday",
        "maxsignalsperday",
        "session.ismarket",
        "time(\"0930-1600",
    ):
        assert forbidden not in lower
    assert "cooldownbars" not in lower
    assert "reassessbars" not in lower
    assert 'input.int(40, "plan timeout' not in lower


def test_only_transparent_safety_limits_can_block_a_completed_setup():
    assert "risk <= maxRiskAtr * atrValue" in SOURCE
    assert "spaceR >= minimumSpaceR" in SOURCE
    assert 'input.float(1.30, "单笔最大风险 ATR"' in SOURCE
    assert 'input.float(0.55, "最低目标空间 R"' in SOURCE
    assert "BLOCK_RISK" in SOURCE
    assert "BLOCK_SPACE" in SOURCE


def test_each_setup_uses_its_own_invalidation_basis():
    assert "longSetup == SETUP_LEVEL_REJECTION" in SOURCE
    assert "longSetup == SETUP_PULLBACK_CONTINUATION" in SOURCE
    assert "longBreakoutStop = math.max(low, priorStructureHigh) - buffer" in SOURCE
    assert "longIgnitionStop = math.max(low, anchorUpper) - buffer" in SOURCE
    assert "shortSetup == SETUP_LEVEL_REJECTION" in SOURCE
    assert "shortSetup == SETUP_PULLBACK_CONTINUATION" in SOURCE
    assert "shortBreakoutStop = math.min(high, priorStructureLow) + buffer" in SOURCE
    assert "shortIgnitionStop = math.min(high, anchorLower) + buffer" in SOURCE
    assert "longBreakoutReady = f_candidate_ready" in SOURCE
    assert "longPullbackReady = f_candidate_ready" in SOURCE
    assert "ta.lowest(low[1], 3)" not in SOURCE
    assert "ta.highest(high[1], 3)" not in SOURCE


def test_setup_edges_are_independent_not_a_shared_cooldown():
    for proof in (
        "proofRejectionLong",
        "proofPullbackLong",
        "proofBreakoutLong",
        "proofIgnitionLong",
        "proofRejectionShort",
        "proofPullbackShort",
        "proofBreakoutShort",
        "proofIgnitionShort",
    ):
        assert proof in SOURCE
    assert "longReadyCandidate" in SOURCE
    assert "shortReadyCandidate" in SOURCE
    assert "lastSignalBar" not in SOURCE
    assert "cooldownBars" not in SOURCE


def test_plan_is_frozen_and_same_side_opportunities_remain_visible():
    assert "sameSidePlan ? ROLE_ADD" in SOURCE
    assert "if not sameSidePlan and not countertrendAdvisory" in SOURCE
    assert "never silently overwrites the original frozen plan" in SOURCE
    assert "plan.stop :=" not in SOURCE
    assert "plan.t1 :=" not in SOURCE
    assert "plan.t2 :=" not in SOURCE
    assert "plan.effectiveStop := plan.entry" in SOURCE
    assert "TIMEOUT" not in SOURCE


def test_trend_runner_and_countertrend_probe_are_not_conflated():
    assert "bool t2Reached" in SOURCE
    assert "bool runnerIntact" in SOURCE
    assert "ROLE_COUNTERTREND_ADVISORY" in SOURCE
    assert 'title="卖C SignalEvent", text="卖C"' in SOURCE
    assert 'gradeGlyph + "｜逆势短打"' in SOURCE
    assert "displaySignal.role != ROLE_COUNTERTREND_ADVISORY" in SOURCE
    assert "qty=dispatchedQty" in SOURCE


def test_cross_symbol_default_does_not_charge_es_commission_to_spx500_cfd():
    # Commission is broker/instrument specific and remains editable in the
    # strategy Properties.  The script must not silently charge the ES
    # per-contract fee while the default chart is CAPITALCOM:SPX500.
    assert "commission_type=strategy.commission.cash_per_contract" in SOURCE
    assert "commission_value=0.0" in SOURCE
    assert "commission_value=2.25" not in SOURCE
    assert "slippage=2" in SOURCE


def test_runner_quarter_is_stop_protected_before_t2():
    # T1 and T2 reserve only 75% of the initial entry.  The last 25% needs its
    # own bracket immediately; otherwise a frozen Stop closes 75% at Stop and
    # leaks the runner to a later bar-close market fill.
    for side in ("L", "S"):
        runner = f'strategy.exit("V11-{side}-RUN"'
        assert runner in SOURCE
    assert SOURCE.count("qty_percent=engine.plan.t2Reached ? 100 : 25") == 2
    assert SOURCE.count("stop=engine.plan.effectiveStop") >= 4


def test_visible_add_reference_does_not_mutate_broker_position():
    assert "displaySignal.role != ROLE_ADD" in SOURCE
    assert "displaySignal.role != ROLE_COUNTERTREND_ADVISORY" in SOURCE
    assert "pyramiding=0" in SOURCE


def test_phone_alerts_are_human_chinese_not_json_payloads():
    assert '"IDM v11｜" + action' in SOURCE
    assert '"｜止损 "' in SOURCE
    assert '"｜目标1 "' in SOURCE
    assert "alert(f_signal_message" in SOURCE
    assert 'alert("IDM v11｜" + f_event_zh' in SOURCE
    assert '"event_family"' not in SOURCE
    assert '"event_id"' not in SOURCE
    assert '{"event' not in SOURCE.lower()


def test_ui_is_minimal_and_explains_the_next_trigger():
    assert "3m 5/12 Cloud" in SOURCE
    assert "Confirmed 10m 34/50 Cloud" in SOURCE
    assert '"S1 最近支撑"' in SOURCE
    assert '"R1 最近压力"' in SOURCE
    assert '"计划 Entry"' in SOURCE
    assert '"计划 Stop"' in SOURCE
    assert '"计划 T1"' in SOURCE
    assert '"计划 T2"' in SOURCE
    assert '"多方下一触发 "' not in SOURCE  # generated by one shared helper
    assert '"下一 BUY 触发 > "' not in SOURCE
    assert '"下一 SELL 触发 < "' not in SOURCE
    assert 'string breakoutReferenceText = "上破参考 "' in SOURCE
    assert "f_blocker_zh(primaryBlocker, primarySide, primaryTrigger)" in SOURCE
    assert '"下一步"' in SOURCE
    assert "等待位置" not in SOURCE
    assert "偏多观察" not in SOURCE
    assert "偏空观察" not in SOURCE


def test_grades_are_explicitly_not_probabilities():
    assert "A/B/C are transparent rule grades" in SOURCE
    assert "A/B/C 是规则完整度，不是历史胜率" in SOURCE
    assert "confidence" not in SOURCE.lower()
    assert "probabilities" in SOURCE.lower()  # only the disclaimer


def test_realtime_delivery_is_confirmed_and_event_id_deduplicated():
    assert "calc_on_every_tick=true" in SOURCE
    assert "calc_on_order_fills=false" in SOURCE
    for cursor in (
        "lastCanonicalSignalId",
        "lastCanonicalPlanEventId",
        "lastRelayedSignalId",
        "lastRelayedPlanEventId",
    ):
        assert cursor in SOURCE
    assert "signalId > lastCanonicalSignalId" in SOURCE
    assert "planEventId > lastCanonicalPlanEventId" in SOURCE
    assert "varip int lastRelayedAlertSignalId" in SOURCE
    assert "varip int lastRelayedAlertPlanEventId" in SOURCE
    assert "relayedSignalId > lastRelayedAlertSignalId" in SOURCE
    assert "relayedPlanId > lastRelayedAlertPlanEventId" in SOURCE
    assert "lastRelayedAlertSignalId := relayedSignalId" in SOURCE
    assert "lastRelayedAlertPlanEventId := relayedPlanId" in SOURCE


def test_engine_only_commits_confirmed_3m_closes_in_every_call_context():
    assert "f_v11_engine(bool processConfirmedClose)" in SOURCE
    assert "bool processBar = processConfirmedClose and not na(time_close)" in SOURCE
    assert "na(lastProcessedTime) or time_close != lastProcessedTime" in SOURCE
    assert "engine := f_v11_engine(barstate.isconfirmed)" in SOURCE
    assert SOURCE.count("f_v11_engine(time_close <= timenow)") == 2
    assert "f_v11_engine()" not in SOURCE


def test_relay_uses_separate_visual_and_alert_cursors_for_pine_rollback():
    assert "var int lastRelayedSignalId" in SOURCE
    assert "var int lastRelayedPlanEventId" in SOURCE
    assert "varip int lastRelayedAlertSignalId" in SOURCE
    assert "varip int lastRelayedAlertPlanEventId" in SOURCE
    assert "Visual labels on an open 10m bar must be rebuilt after Pine rollback" in SOURCE


def test_history_uses_complete_grade_glyphs_and_distinct_plan_events():
    for glyph in ("买A", "买B", "买C", "卖A", "卖B", "卖C"):
        assert f'text="{glyph}"' in SOURCE
    for glyph in ("T1", "T2", "止", "护", "反", "退"):
        assert f'text="{glyph}"' in SOURCE
    assert 'title="Plan exit", text="出"' not in SOURCE


def test_current_stop_and_latest_signal_callout_are_truthful():
    assert "engine.plan.effectiveStop" in SOURCE
    assert '"初始 Stop 参考"' in SOURCE
    assert '"当前 Stop "' in SOURCE
    assert '"｜当前S "' in SOURCE
    assert "latestSignalConnector" in SOURCE
    assert "latestRightTime = time_close + 12 * 60 * 1000" in SOURCE
    assert "label.delete(latestSignalLabel)" not in SOURCE


def test_ten_minute_read_only_history_is_compact_without_losing_signals():
    relay_start = SOURCE.index("if hostUsesLowerTfRelay and relayRows > 0")
    relay_end = SOURCE.index("newSignal := newSignal or relaySignalCount > 0")
    relay_ui = SOURCE[relay_start:relay_end]
    assert 'displaySignal.side == SIDE_LONG ? "买" : "卖"' in relay_ui
    assert "f_grade_zh(displaySignal.grade)" in relay_ui
    assert relay_ui.count("style=label.style_none") >= 2
    assert "tooltip=f_signal_message" in relay_ui
    assert "f_event_glyph(displayPlanEventType)" in relay_ui
    assert "showLatestLabel and latestSignalKnown and\n         not hostIs10m" in SOURCE
