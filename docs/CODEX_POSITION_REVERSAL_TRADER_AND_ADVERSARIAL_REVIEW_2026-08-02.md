# POSITION_REVERSAL v1.3 独立 Trader / 对抗审查

日期：2026-08-02
审查输入 commit：`db760ee3511f660e6878ffc95d2aabb0d73296ba`
审查性质：只读源码、合同和测试审查；不是 TradingView 在线验收、实盘前向或盈利证明

## 裁决

**REVISE。**

现有 detector 的因果/source/identity baseline 是 PASS 候选：

```text
python3 research/generate_phase1_10m_position_reversal_pine_v1.py --check
PYTHONPATH=. ./.venv/bin/pytest -q research/tests/test_phase1_10m_position_reversal_*.py
```

结果：generator/Pine parity PASS；`104 passed`。

但 v1.3 不能直接作为 trader 信号或创建真实 alert。

## Trader 阻塞项

1. **READY 与非 READY 误用同一个大标签。** 当前所有 `EV_BOUNCE_CONFIRMED` / `EV_REJECTION_CONFIRMED` 都画“反弹确认/压回确认”，没有要求 `reason == RS_READY`。无目标、目标已消耗、空间 `<1R` 或风险无效的反应会被误读为可执行信号。
2. **图上看不到信号所依据的位置。** v1.3 只有四个 `plotshape`，没有显示当前 frozen band。Trader 无法从图上核对“为什么这里是关键位置”。
3. **默认静默空白。** ATR 与四个 band 默认关闭，默认时间已过期，状态卡默认关闭。加载到当前图表时既无信号也无明确的“未配置/已过期”提示。
4. **深色背景可读性不合格。** WATCH marker 使用黑字；状态卡包含 `READY / accepted break / prior-known / trigger / identity` 等内部词，完整 CID1 还会撑宽小窗。
5. **旧计划可能被冒充为当前计划。** Pine 的 `latestPlanFresh` 只检查 12 根寿命与 reset。后续已经到 target 或破 invalidation 时，卡片仍可能展示旧 trigger/stop/target；Python 则在 terminal 后下一根清掉 current opportunity。

最小 Trader 层级：

- 小号：`位置·支撑观察` / `位置·阻力观察`，含义是停止追价并等待，不是入场；
- 大号：`位置·多头确认` / `位置·空头确认`，只允许 READY；
- 非 READY confirmed reaction 默认不画大号 marker，状态卡写清唯一“不做”原因；
- 只显示当前 frozen band 的上下沿与淡 fill；价格锚定，不使用 label/line/box；
- 所有 marker 使用高对比白字；
- 卡片行固定为 `现在做 / 原因 / 位置 / 失效 / 目标`，内部 identity 留给 Data Window/alert evidence。

## 因果与 alert 阻塞项

1. **exact duplicate 分叉。** Python 对重复 confirmed timestamp 返回 `DATA_DUPLICATE_IGNORED` 且不改状态；Pine 的 `time - lastConfirmedTime != 600000` 会把 delta `0` 当 gap reset。上线前必须把 exact duplicate 明确做成 no-op，并把 backward 与 forward gap 分开。
2. **bar-close liveness 缺口。** source/ATR/band 只按 bar-open 验证。事件到 `time_close` 才对外可见，因此还要保证相关 source、target、ATR 在 `time_close` 仍满足 exclusive `valid_until` 与 freshness。`published/known <= bar-open` 的因果约束必须保留，不能整体改用 close time。
3. Alert 只能由当前 bar 的 `ev` pulse 加 state/reason/identity guard 触发；禁止使用持续的 `lastEvent`、`latestPlanFresh`、`st == READY` 或 marker 可见性单独触发。
4. same-bar touch+confirm 只允许一个 READY confirm，不先发 WATCH。
5. `accepted break / reaction expired / wait clear / conflict / multiple same-side / data reset / duplicate / backward / gap / wrong host / invalid source / no target / consumed target / risk invalid / space <1R` 均不得触发 READY alert。
6. Indicator input/source version 变化后，既有 TradingView alert 仍使用创建时快照；必须停掉旧实例并重新创建，不能假设自动继承新配置。

## 四个 outward alertcondition 合同

代码可提供恰好四个、互斥且 confirmed-only 的条件：

1. `位置反转｜支撑观察`
2. `位置反转｜阻力观察`
3. `位置反转｜多头确认 READY`
4. `位置反转｜空头确认 READY`

WATCH 消息必须写“观察，禁止直接入场”。READY 消息必须写“10m 条件计划候选，检查 3m/现价空间与 R3.2 是否冲突”；不能写成 BUY/SELL、订单或盈利保证。

## 与 R3.2 的边界

- POSITION WATCH 永远不改变 R3.2 permission。
- 两条 lane 同向不等于胜率加成，不能重复发第二个入场指令。
- 两条 lane 反向时，在没有 combined arbiter 前只能写“方向冲突，暂停新增”；不能自动平仓或反手。
- R3.2 已进入计划仍由它自己的冻结保护/目标管理。
- 本轮不把 3m/VIX/MACD/divergence 或 R3.2 状态读入 position detector。

因此，本轮可以实现四个**纯提醒事件**，但在图面、online compile/replay、fresh daily source 与 Trader 复审通过前不能创建真实 alert；创建后也只是观察/条件候选，不是自动交易。

## 升级为 PASS 的门禁

- 修复上述五个 Trader 阻塞与两个因果分叉；
- generator、generated Pine、oracle、tests 同步升级为新 outward protocol；
- 负例证明只有 READY 会有大号确认 marker/READY alert；
- TradingView clean compile、remove/re-add、pan/zoom、标准 SPX500 10m、fresh source 配置通过；
- 至少 support 正例、resistance 正例和两个关键负例在图上逐根核对；
- Trader 不看源码也能正确解释观察、确认、失效、目标和不做原因；
- Create Alert 下拉恰好出现四个条件；实际实例使用 Once Per Bar Close、无 webhook、无订单；
- 明确保留：真实触发、手机通知、30/90 天覆盖、成交和 edge 均需后续证据。
