# ChatGPT Pro handoff：10m 关键位置不破反转的 Trader UI 与安全 alert

日期：2026-08-02
本地基线 commit：`4b8aa100bd4922963e9d5b318c1e8f427e37c547`
目标 lane：`POSITION_REVERSAL`
当前协议：`phase1-10m-position-reversal-1.3`
当前 Pine SHA-256：`c205aef662bf900c43dc6f2af3a9e100afda3f5425a12fe4e879194f6de1f06d`

## 1. 背景与目标

现有 R3.2 是一条已经独立验收的趋势延续 lane：10m 负责主计划，3m 只做择时/管理。本任务不能修改或合并 R3.2。

本任务只把另一条独立逻辑做成真实 trader 看得懂、能及时收到提醒的 TradingView 指标：

```text
prior-published SATy/ATR 具名支撑或阻力
    -> confirmed 10m 触及观察
    -> 最多三根 confirmed 10m 内出现站回/压回
    -> 只有冻结 stop/最近 prior-known opposite target 的空间 >= 1R 才成为 READY
```

这是“位置不破后的反应”，不是破位反转，也不是碰到位置立即下单。

## 2. 当前架构与不可破坏边界

唯一可修改范围：

- `idm_phase1_10m_position_reversal_v1.pine`（generator 生成物，禁止手改）；
- `research/generate_phase1_10m_position_reversal_pine_v1.py`；
- `research/phase1_10m_position_reversal_oracle.py`；
- `research/tests/test_phase1_10m_position_reversal_*.py`；
- 本 lane 的规范、验收和 Trader review 文档。

必须保留：

- Pine v6 indicator，标准 K 线 `CAPITALCOM:SPX500`，原生 10m；
- `barstate.isconfirmed` 后才允许产生 outward event；
- prior-published/stable source、absolute validity、previous-completed daily ATR provenance；
- source/target/ATR identity 与 effective-material 冻结；
- accepted break 优先，不能事后把破位改写为反转；
- nearest-first prior-known opposite target，已提前消耗目标不能跳远；
- `MAX_REACTION_BARS=3`、`MINIMUM_SPACE_R=1.0`、`REARM_ATR=0.12`；
- 同 K 支撑/阻力冲突、同向多位置、stale/invalid/gap/source drift 全部 fail closed；
- 每 episode 最多一个 watch 和一个 terminal，完成完整离位前不得重建；
- 无 strategy、无订单、无 broker、无 webhook、无自动交易。

本轮禁止加入：

- 3m consumer、VIX、MACD/divergence；
- forming MTF cloud；
- overnight/previous-day/EMA 等新 producer；
- 盈利能力、30/90 天 edge 或实盘成交声明。

## 3. 已确认的 Trader 语义缺陷

当前源码把所有 `EV_BOUNCE_CONFIRMED` 和 `EV_REJECTION_CONFIRMED` 都画成大号“反弹确认/压回确认”，即使 `reason != RS_READY`（例如无目标、目标已消耗、空间不足、风险无效）。

这会让 trader 把“形态反应已确认但没有交易授权”误读成“可执行确认”。必须修正：

- 主图大号确认 marker 只允许 `reason == RS_READY`；
- 默认界面不能把未授权反应伪装成交易信号；
- 如保留诊断显示，必须默认关闭并明确写成“反应但不做”，且不能产生交易 alert。

## 4. 需要研究并给出最小完整方案

### 4.1 图上最小信息层级

Trader 必须在不打开源码的情况下回答：

1. 这是支撑观察还是阻力观察？
2. 现在只是等待反应，还是已经形成可执行确认？
3. 若可执行，trigger、保护位、最近目标和空间是多少？
4. 若不可执行，唯一主因是什么？

请评估以下建议并给出明确取舍：

- 小号观察：`支撑观察` / `阻力观察`；
- 大号 actionable marker：`多头确认` / `空头确认`，仅 READY；
- 非 READY 的 confirmed reaction 默认不画大号 marker；
- 使用价格锚定的 `plot`/`plotshape(location.absolute)`，禁止 label/line/box；
- 可选显示当前有效具名 band，但不得制造与 R3.2 重复、无法辨认的线；
- 五行状态卡默认关闭，若开启必须使用高对比度中文且不与 R3.2 卡片重叠。

### 4.2 Alert 事件

优先使用四个独立、可在 TradingView “Condition” 下拉中选择的 `alertcondition()`：

1. `位置反转｜支撑观察`：唯一新 support episode 的 confirmed touch；
2. `位置反转｜多头确认 READY`：confirmed bounce 且 `RS_READY`；
3. `位置反转｜阻力观察`：唯一新 resistance episode 的 confirmed touch；
4. `位置反转｜空头确认 READY`：confirmed rejection 且 `RS_READY`。

必须满足：

- 四个 alert 条件本身显式包含有效 source surface 与 confirmed bar；
- watch 是观察提醒，不得写“买入/卖出”；
- READY 是条件计划，不得写成订单或保证盈利；
- no-target、target-consumed、space `<1R`、risk-invalid、accepted-break、expiry、conflict、same-side multi-touch、WAIT_CLEAR、data reset、wrong host/timeframe/chart 不得触发 READY alert；
- 事件为单根 pulse，不能用持续状态每根重复提醒；
- 创建 alert 时采用 `Once Per Bar Close`；
- 不使用 webhook；
- 消息至少包含 `{{exchange}}:{{ticker}}`、`{{interval}}`、`{{time}}`、OHLC，并在可靠可编译时通过 hidden numeric plots 带出 band/trigger/invalidation/target/spaceR；
- 必须记录 TradingView 的 alert snapshot 边界：指标 input 后续修改不会自动更新已创建 alert 的旧配置，因此 fresh daily source 更新后要重新创建或显式更新 alert。

官方行为依据：

- <https://www.tradingview.com/pine-script-docs/concepts/alerts/>
- <https://www.tradingview.com/support/solutions/43000595315-how-to-set-up-alerts/>
- <https://www.tradingview.com/support/solutions/43000474415-differences-between-alert-frequencies/>

## 5. 明确交付物

请返回：

1. 先给 `PASS / REVISE / REJECT` 设计裁决和理由；
2. 说明当前源码所有 Trader 误读风险、因果/重绘/重复风险；
3. 最小完整 patch，包含 generator、generated Pine、oracle（若 outward contract 改变）和 tests；
4. 精确列出四个 alertcondition 的 condition、title、message；
5. 图面层级与中文文案表；
6. TradingView 在线验收步骤；
7. Alert 创建/更新/删除 runbook；
8. 明确列出仍未验证的风险。

不要只给伪代码；若建议改源码，必须给完整可应用 diff 或完整文件。

## 6. 必须执行的测试

最低要求：

```bash
python3 research/generate_phase1_10m_position_reversal_pine_v1.py --check
PYTHONPATH=. ./.venv/bin/pytest -q research/tests/test_phase1_10m_position_reversal_*.py
git diff --check
```

新增测试至少覆盖：

- 四类 alertcondition 存在且标题/消息稳定；
- watch alert 与 watch marker 同 pulse；
- READY marker/alert 必须同时满足 `reason == RS_READY`；
- confirmed reaction 但无目标/空间不足等负例不产生 READY marker/alert；
- accepted break/conflict/multiple/data reset/wrong host 等不得 alert；
- generator/Pine byte parity；
- Python/Pine 事件语义不分叉；
- alert 中无 webhook/order/strategy 语义。

在线门禁必须另外执行，离线测试不能冒充：

- Pine Editor clean compile；
- remove/re-add；
- 标准 `CAPITALCOM:SPX500` 10m；
- fresh source 配置；
- 平移/缩放后 band 与 marker 仍锚定 K 线价格；
- 至少一个 support 正例、一个 resistance 正例、两个关键负例的 replay/截图；
- TradingView alert 条件下拉存在四项；
- 创建后 Alerts Manager 显示 active，且没有 webhook/order action。

## 7. 验收标准

只有以下全部为真，才可创建真实 alert：

- 源码合同通过；
- 独立对抗审查通过；
- Trader 能在截图上不看源码正确解释观察、确认、保护、目标和不做原因；
- 真实 TradingView compile/re-add/pan/zoom/replay 通过；
- 当前 daily SATy/ATR source 身份、时间和有效期可审计；
- alertcondition 与图上 event 一一对应；
- 没有模糊大号标签、持续重复提醒或历史倒填；
- 明确承认这不是盈利 edge、不是成交验证、不是自动交易。
