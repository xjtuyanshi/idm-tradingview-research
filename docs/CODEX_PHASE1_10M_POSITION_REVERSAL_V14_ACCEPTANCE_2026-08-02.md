# Phase 1｜10m 位置反转 v1.4 验收记录

日期：2026-08-02

## 当前裁决

- 源码、生成器、Oracle、专项合同与全仓离线门禁：**PASS**。
- Trader 可读性复审：**PASS**。
- 对抗性 alert/因果复审：**PASS**。
- TradingView 在线编译、暗色实图、拖动缩放、Replay 与 Alerts Manager：**PENDING**。
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

## 在线门禁与 alert 创建规则

在线状态没有通过前，不创建 alerts。通过顺序固定为：

1. 在干净 Pine Editor 中粘贴 commit 对应源码并 clean compile。
2. 在 `CAPITALCOM:SPX500` 标准 K 线、原生 10m 上删除旧实例后重新添加。
3. 配置 fresh、盘前已发布且在 bar close 仍有效的当日位置与上一完成日 ATR。
4. 暗色主题检查文字、位置带和卡片；拖动与缩放检查价格锚定。
5. Replay 正例及 accepted break、无目标、空间不足、stale/reset 等反例。
6. Condition 下拉确认恰好四项。
7. 四项均使用 `Once Per Bar Close`；不配置 webhook 或 order action。
8. 在 Alerts Manager 核对四项 active。daily source 更新后删除旧 snapshot 并重建。

## 仍不能声称的结论

当前没有逐日 append-only 的 SATy/ATR source snapshot，因此不能把一组今天的手工位置套到 30/90 天历史 K 线上并称为无后视镜回测。132 项专项测试证明规则、消息、身份、生命周期和 fail-closed 门禁按合同运行；它们不证明胜率、盈利、真实成交或手机通知送达。
