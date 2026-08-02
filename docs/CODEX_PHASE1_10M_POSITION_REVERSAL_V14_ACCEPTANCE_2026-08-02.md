# Phase 1｜10m 位置反转 v1.4 验收记录

日期：2026-08-02

## 当前裁决

- 源码、生成器、Oracle、专项合同与全仓离线门禁：**PASS**。
- Trader 可读性复审：**PASS**。
- 对抗性 alert/因果复审：**PASS**。
- TradingView 在线编译、原生 10m 暗色实图、拖动缩放、Replay、四项 condition 与 Alerts Manager：**PASS**。
- 当前 SATy/ATR source 的在线运行快照与四项 bar-close alert：**PASS**；手机实际送达尚未验证。
- 真实 30/90 天逐日 source 快照回放、方向 edge 与盈利能力：**PENDING**。

本记录只验收独立的 `POSITION_REVERSAL` 10m lane。它没有接入 3m consumer、VIX、MACD/divergence、订单、webhook 或自动交易，也没有修改 R3.2 趋势延续 lane。

## Trader 实际看到什么

| 图面/提醒 | 含义 | 允许采取的理解 |
|---|---|---|
| 支撑观察 | 价格触及盘前已发布的支撑位置 | 仅观察，等待 10m 收盘反应；不是买入 |
| 阻力观察 | 价格触及盘前已发布的阻力位置 | 仅观察，等待 10m 收盘反应；不是卖空 |
| 多头确认 | 支撑未被收盘接受跌破，价格收回位置上方，并且最近目标仍有至少 1R 空间 | 得到一份条件计划：触发、保护、目标、空间；不是订单 |
| 空头确认 | 阻力未被收盘接受突破，价格压回位置下方，并且最近目标仍有至少 1R 空间 | 得到一份条件计划：触发、保护、目标、空间；不是订单 |

确认窗口最多包含触及 K 在内的三根已确认 10m K。支撑收盘低于位置下沿，或阻力收盘高于位置上沿，属于位置被接受突破，本轮终止且不倒填反转。最近反向具名位在触及时冻结为目标；无目标、目标已被消耗、风险无效或空间小于 1R 时不出现确认。

长方向触发为确认 K 高点，短方向触发为确认 K 低点。保护位使用本轮极值外侧 `max(0.2 点, 0.002 ATR)`；条件计划最多保留 12 根 10m K。若同一后续 K 同时触及保护与目标，因无法恢复盘中先后顺序，按保护先到处理。

## 图面和手机提醒合同

- 历史确认默认显示；历史观察默认隐藏，避免重新制造满图噪音。
- 最新一根观察仍可由最后一根 marker、冻结位置带和五行状态卡看到。
- marker 使用绝对价格坐标和白字；无动态 label、line 或 box。
- 四条 alert 均包含标的、周期、`K线时间(UTC)`、开高低收和位置带。
- 多头/空头确认另含触发、保护、目标与 `R` 空间。
- 提醒明确写明“不是订单”“位置计划尚未接入 3m”“R3.2 反向或已有计划时不执行”。
- 可选择的 `alertcondition()` 恰好四个：支撑观察、阻力观察、多头确认、空头确认。
- 图面显示开关不会扩大或缩小 alert 决策条件。

## 复审要求的实际修正

1. 补齐手机提醒的 symbol、interval、UTC K 线时间、OHLC、位置、触发、保护、目标和空间。
2. 移除“等待 3m 执行”的错误暗示，明确当前尚未接入 3m consumer 或全局 owner 仲裁。
3. 将用户可见 `READY` 改成“确认”，隐藏内部 identity 文案，并把历史观察默认关闭。
4. 统一 Oracle/Pine 对 stale extra band 的全局 fail-closed 语义。
5. ACTIVE plan 的 source、target 或 ATR 缺失/合法版本漂移时结束当前计划，不重写 immutable ledger。
6. outward 决策要求当前 plan 为 ACTIVE、未结束且 active owner 与本次 opportunity 完全一致。
7. wrong host/timeframe、非标准图、非法 OHLC、错误 protocol/lane 和 malformed source/ATR context 全部不提醒且不抛异常。
8. outward 决策核对完整当前 source surface；非法身份、重复身份、expired 或 stale 的 enabled extra band 会关闭全部提醒。

## 机械门禁

```text
Generator/Pine byte parity: PASS
Position reversal targeted: 132 passed
Full repository: 1094 passed, 130 skipped
git diff --check: PASS
```

130 个 skip 都有仓库内明确理由：私有 TradingView fixture、外部 CSV 或未随公开源码分发的历史证据；没有失败项。

## ChatGPT Pro 最终外部复核

ChatGPT Pro 基于它先前的 Pro130 完整包，对 outward alert 首层又完成了一次最小 Guardfix：owner/status、host/context、malformed fingerprint 和完整 current source surface 均按 fail-closed 处理。其最终包与补丁独立验收结果：

```text
Patch: 19,232 bytes
  SHA-256 318c67899831de496865439d30c1afa38ff13dca1b8bf44c95fe75d829bf8c89
Complete ZIP: 117,020 bytes
  SHA-256 d257025bfe7a1a3fa86205fc30676203bbd687a36e79da1fee643f7ad7b910df
Validation log: 3,670 bytes
  SHA-256 3fce74c0c382da2e6d7f21b06b69bd5b82e951aa0de9e930fb76a42d7d59c7c1
Fresh ZIP targeted tests: 132 passed
Fresh Pro130 + patch targeted tests: 132 passed
Patch-applied tree vs final ZIP: byte-identical
ZIP CRC/path traversal/symlink/encryption/high-confidence secret scan: PASS
```

该 Pro 包的 Pine 是它实际收到的旧基线 `5c8ee32b…`，不是本仓库最终提交的 `5beaa282…`。因此没有将 Pro 包或补丁覆盖到本仓库；本仓库保留已经通过本地 132 项专项测试、全仓门禁、Trader 复审和对抗复审的最终版本。Pro132 在这里用作独立的同语义复核证据，不作为新的源码权威。

## 冻结身份

```text
Git commit: dbb571d feat: add v1.4 position reversal alerts
POSITION_REVERSAL Pine SHA-256:
  5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421
Canonical Pine block SHA-256:
  7987577271b59eeca1106b5d56c5dd6b17fe426757224f2e8a8fb72fdca3a41c
Oracle SHA-256:
  5d9ed01bdda7f2ba3396fdb6200aabc66cfe28dd0cef025204942b363437dff6
Alert tests SHA-256:
  476c92c8a5f6567120befaf6043a470f7359d53e1767fe5cf9e0a54a4595c667
R3.2 10m SHA-256:
  aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2
R3.2 3m SHA-256:
  f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e
Task source ZIP SHA-256:
  ea59c58a09ba837f4940f261327a162d5e9079e9cf9c1712b98caf0527167ee8
```

任务源码 ZIP 为 116,982 bytes、23 entries；CRC、敏感文件名和凭据内容扫描均 PASS。

## TradingView 在线门禁：PASS

### 编译、布局和 source 快照

- 在 TradingView Pine Editor 中使用本记录冻结的源码完成 clean compile，并以 `IDM Phase 1｜10m 位置反转 v1.4` 保存、添加到图表。
- 实例只放在 Chart #1 的 `CAPITALCOM:SPX500` 标准 K 线、原生 10m；Chart #2 的 3m 与 Chart #3 的 VIX 10m 未被本 lane 改写。
- 暗色主题下状态卡、位置、失效原因和提醒文案可读；marker 与价格位置在拖动、缩放及 Replay 中保持 K 线锚定。
- 最终在线 source 版本为 `2026-08-03-observed1904ET-v1`。SATy 值在 2026-08-02 19:04 ET 首次实际观察；TradingView 时间输入只支持 15 分钟粒度，因此 `published_at` 与 `known_at` 保守向后设为 19:15 ET，禁止 19:15 前历史 K 线倒填使用。
- source 值：Previous Close `7475.6`、Lower Trigger/support `7452.1`、Upper Trigger/resistance `7499.1`、`-1 ATR 7376.0`、`+1 ATR 7575.2`、ATR `99.6`；有效至 2026-08-03 16:00 ET。
- ATR 身份是上一完成日 `2026-07-31` 的 completed daily ATR。source fingerprint 更新后，状态机按设计先 fail-closed 重置一根确认 K；下一根 10m K 收盘后恢复。
- 恢复后的当前状态为“本轮不做｜阻力 7499.1–7499.1｜位置已被接受突破｜不倒填”。价格已经由 10m 收盘接受突破阻力，系统不会在突破后补发一个过时空头确认。

### Replay 和反例

- 使用 2026-07-31 当日历史 source：ATR `98.70936228387525`、support `7421.204590501005`、resistance `7467.795409498995`，其 published/known time 为 2026-07-30 16:00 ET、valid-until 为 2026-07-31 16:00 ET。
- TradingView 实际 Replay 中出现过一笔可见的历史“空头确认”；其后阻力被收盘接受突破时，本轮结束且没有倒填新的反转。
- 约 11:40 的支撑反应没有被误报成多头确认：真实 TradingView K 线下最近目标空间不足 1R，状态卡明确显示“最近目标空间 < 1R｜不做”。这说明离线 synthetic contract 的多头正例不能冒充该时段真实行情结果。
- Replay 后完成拖动与缩放检查，历史 marker 仍固定在原始 K 线上，没有出现随视窗漂浮的 label。

### 最终 alerts

- condition 下拉恰好四项：`位置反转｜支撑观察`、`位置反转｜阻力观察`、`位置反转｜多头确认`、`位置反转｜空头确认`。
- Alerts Manager 中最终恰好四项本 lane alert，均为 `SPX500, 10m`、`Active`；逐项按相同创建流程设置，另抽查“空头确认”显示 Interval `10m`、Trigger `Once per bar close`。
- 通知渠道为 TradingView 的 App、Toasts、Sound；没有 webhook、order action 或自动交易。尚未观察到真实手机送达，因此不能声称手机链路已验收。
- 在 source 时间纠正过程中曾创建的 16:00/18:00 快照均已删除；最终仅保留基于 19:04 实际观察、19:15 保守 known-time 的四项 snapshot。
- alert 对象虽然可继续显示 Active，但 Pine source 在 2026-08-03 16:00 ET 后会 fail-closed；daily source 更新后仍必须删除旧 snapshot 并重建。

### 在线证据

证据保存在 `/Users/lukegogogo/Documents/idm-tradingview-signal-evidence/tradingview_online/`：

| 证据 | SHA-256 |
|---|---|
| `position_reversal_v14_live_recovered_20260802.jpg` | `441c856938a3b272271670f61b0657982c24731630afdc4c11b86f10b1f17c70` |
| `position_reversal_v14_alerts_final_20260802.jpg` | `a3636a1b6973a936dfe0fa783ab0dcf360eb60c93374836a900729ce62228e3e` |
| `position_reversal_v14_once_per_bar_close_final_20260802.jpg` | `a32521de3f2508f98546e3d7875e5b9b4a9677360211daa1231be0259d8a5a09` |
| `position_reversal_v14_replay_1140_20260731.png` | `556f0edccf78cff6a01d1350dbfe75e595f767e24eabe25e08c9c1fc4c904363` |
| `position_reversal_v14_pan_zoom_anchor_20260731.png` | `1797780f94cae594d35398a21f30858ab981383fe6a929a0b22df10b8ce8ff36` |

## 仍不能声称的结论

当前没有逐日 append-only 的 SATy/ATR source snapshot，因此不能把一组今天的手工位置套到 30/90 天历史 K 线上并称为无后视镜回测。132 项专项测试和本次在线门禁证明规则、消息、身份、生命周期、图面锚定与 fail-closed 门禁按合同运行；它们不证明胜率、盈利、真实成交或手机通知送达。
