# ChatGPT Pro 预实现审查：POSITION_REVERSAL 10m → 3m timing / owner

日期：2026-08-02
仓库：`git@github.com:xjtuyanshi/idm-tradingview-research.git`
本地分支：`codex/minimal-signal-rebuild`
审查前基线：`2d012893e2d40f9cde6b18ff03703100d436ebd8`
性质：预实现架构与交易合同审查；本包不授权下单、webhook、部署、推送或盈利声明

## 背景和目标

已经独立验收的 `POSITION_REVERSAL` v1.4 在 native SPX500 10m 上完成：prior-known
SATy/ATR 具名位置、confirmed reaction、immutable opportunity、accepted-break 不倒填、最近
目标与 `>=1R` 门禁、四项 bar-close alerts、暗色图面、Replay 和 fail-closed source/identity
合同。

下一步只实现：**将 v1.4 的 ACTIVE 10m opportunity 交给 confirmed-only 3m timing
consumer，输出一次清楚的入场触发或放弃，并与现有 R3.2 `TREND_CONTINUATION` 共用唯一
plan owner。**

本轮不加入 VIX、MACD、divergence、AI score、订单或自动交易，也不修改 10m
`POSITION_REVERSAL` 的交易判断。

## 当前架构与不可破坏边界

### 已验收 10m producer

- Pine：`idm_phase1_10m_position_reversal_v1.pine`
- Generator：`research/generate_phase1_10m_position_reversal_pine_v1.py`
- Oracle：`research/phase1_10m_position_reversal_oracle.py`
- 协议：`phase1-10m-position-reversal-1.4`
- `OpportunityPayload` 已冻结：lane/opportunity/episode/source identity、direction、trigger、
  invalidation、target、visible/confirmation/expiry、ATR、risk/reward/space-R。
- READY plan 只在 10m confirmed reaction、source 在 bar-open 因果可知且到 bar-close 仍可交付、
  最近目标未消耗、risk 有效、space `>=1R` 时发布。
- accepted break、source/ATR/target identity 漂移或过期会 fail closed；不得倒填。

### 已有 R3.2 trend timing

- 10m：`idm_phase1_10m_primary_opportunity_v3.pine`
- 3m：`idm_phase1_3m_opportunity_timing_v3.pine`
- Oracle：`research/phase1_10m_primary_opportunity_oracle.py::OpportunityTimingEngine`
- R3.2 timing 已锁定 adoption-bar 禁入、later pullback/trigger、remaining `>=1R`、suppression、
  entered plan 独立管理、identity-bound terminal 和 invalidation-first。
- `POSITION_REVERSAL` 不能被塞进 R3.2 trend producer，也不能把同向两条 lane 当成两票。

### 全局 owner 合同

优先级必须保持：

```text
host/data/source fail-closed
> 已 ENTERED owner invalidation
> 已 ENTERED owner target
> 已 ENTERED owner management
> 已 adopt、未入场 owner
> 新 plan arbitration
> WATCH / advisory
```

- 同一时刻最多一个 outward/adopted/entered owner。
- 现有 owner 在 terminal 前不能被新 lane 替换、加仓或反手。
- 无 owner 且两条 lane 同 K 反向：`CONFLICT / NO_NEW_ENTRY`。
- 无 owner且同向：只选 `visible_at` 较早者；完全同时时按冻结 allowlist
  `TREND_CONTINUATION` → `POSITION_REVERSAL`，不计算“共振加分”。
- 新 opportunity 到达的 3m K 只能 adopt，entry 必须来自 strictly later confirmed 3m K。

## 建议的最小 3m POSITION_REVERSAL timing

位置反转与趋势续行不能共用完全相同的 timing predicate。10m 位置反转已经完成位置触及和
confirmed reaction，因此 3m 不再强制等待第二次 pullback：

```text
WAIT_PLAN
  -> adopt ACTIVE POSITION_REVERSAL plan；adoption K 禁入
WAIT_TRIGGER
  -> strictly later confirmed 3m
  -> long: EMA5 > EMA12 AND close > frozen 10m trigger
  -> short: EMA5 < EMA12 AND close < frozen 10m trigger
  -> 用同一 frozen invalidation/target 按实际 3m close 重算 remaining R
  -> remaining R >= 1 才发一次 entry
ENTERED
  -> 继续管理同一 immutable stop/target；permission expiry 不驱逐 entered owner
LOCKED
  -> invalidated / target / missed / expired / conflict / source reset 后 suppression 同 ID
```

尚未入场时，保护先破、目标先到、permission/source 结束或 remaining `<1R` 都必须 no-entry。
同一 3m K 同时碰保护与目标，invalidation 优先。任何 replacement/terminal K 禁止反手。

需要 Pro 判断的实现架构不是交易规则，而是 Pine transport：

1. 是否生成新的 `idm_phase1_3m_position_reversal_timing_v1.pine`，先保持 lane 独立，再用小型
   global owner arbiter 汇总；或
2. 是否生成一个新的 3m global decision host，分别嵌入两个 10m producer adapter，只在 owner
   层汇合；或
3. 是否能抽出通用 `PlanEnvelope + OwnerManager` generator，同时保留 trend 的
   `WAIT_PULLBACK` 和 reversal 的直接 `WAIT_TRIGGER` policy。

禁止以手填“R3 是否冲突”、跨图 `input.source`、forming 10m、当前 K 10m 值或不可复算的 UI
状态代替真实 owner transport。

## Trader 图面合同

默认只允许一个大 decision marker：`多入` 或 `空入`。失效/目标 marker 默认隐藏，只在卡片
更新，避免重现“多续、空退、关多、关空”满图术语。

3m 卡片固定五行：

```text
现在做  等待 / 多入触发 / 空入触发 / 冲突不做 / 本计划结束
来源    10m 趋势续行 / 10m 位置反转
触发    3m confirmed close 与冻结价、5/12 条件
保护    frozen invalidation
目标    frozen target 与 entry-time remaining R
```

不得显示内部 ID、protocol、source fingerprint 或 `READY/ENTERED/LOCKED` 英文状态。marker、
plan level 均使用绝对价格锚定；无 dynamic label/line/box。

Alerts 在 TradingView online gate 前不得创建。预期最小 selectable surface 请 Pro 判断：只保留
`3m 多头触发 / 3m 空头触发`，还是另加 `计划失效 / 目标到达`；无论哪种都必须 Once Per Bar
Close、消息含 owner lane、10m opportunity time、3m bar time、entry、stop、target、remaining R，
并明确“不是订单”。

## 强制正反例

### Synthetic positive

- long 与 short 各一条：10m plan 在某 3m K 开盘前已可见；该 K 只 adopt；strictly later 3m
  5/12 同向并收过冻结 trigger；remaining `>=1R`；只发一次 entry。

### 必须 fail closed

1. adoption K 已经越过 trigger：仍禁止同 K entry。
2. forming/未完成 10m、source close time 晚于 3m open：不得 adopt。
3. 保护或目标在 entry 前已经到达：no-entry；同 K stop+target 时 stop-first。
4. entry-time remaining `<1R`：no-entry，不跳过最近目标。
5. permission expired、source/ATR/target identity 漂移、invalid/missing：no-entry。
6. duplicate 3m timestamp no-op；backward/gap/invalid host reset 且 suppression 保留。
7. R3.2 owner 已 adopt/entered：新 reversal 不替换；反向新 plans 同 K冲突。
8. entered owner 不因 10m permission expiry、新 plan 或同向“共振”而被驱逐。
9. 一根 3m K 最多一个 outward marker；terminal/replacement K 不反手。
10. reload、Replay 与 live 路径必须相同；禁止 lookahead/backfill。

### 2026-07-31 真实负例边界

早期合同曾把 11:30 ET 支撑反应当成预期 long opportunity；但 v1.4 在真实 TradingView
Replay 的约 11:40 状态显示最近目标空间 `<1R`，因此没有 ACTIVE 10m plan。新 3m 系统必须
继续 no-entry，不能为了复现“看起来后来上涨”而手工注入 plan。真实正例必须来自 producer
实际发布的 causal plan；没有逐日 append-only source ledger 时只能用 synthetic positive 证明
state-machine contract，不能声称 30/90 天 edge。

## 交付物

本轮请先交付预实现审查，不要直接扩大重写：

1. 对三种 Pine transport/owner 架构的明确选择和理由；
2. 最小 `PlanEnvelope` 字段与两个 lane adapter 合同；
3. global arbiter + reversal timing + entered management 的逐状态优先级表；
4. `request.security`/completed-10m/no-lookahead 的具体实现方案；
5. Pine/generator/Python Oracle/tests 的最小文件变更清单；
6. 必须补充的正反测试及 TradingView online 验收步骤；
7. 对本 handoff 中任何矛盾、过度复杂或会导致漏信号/晚信号之处提出最小修订。

## 禁止执行或禁止声称

- 不推送、不建 PR、不部署、不下单、不启用策略订单、不配置 webhook。
- 不把 VIX/MACD/divergence/AI score 加入 permission 或 arbiter。
- 不修改冻结 v11，不把 position detector 合并进 R3.2 trend detector。
- 不以 synthetic 测试、单日 Replay 或视觉 hindsight 声称胜率、盈利或 30/90 天 edge。
- 不覆盖 working tree 中与本任务无关的用户改动。

## 当前验证基线

```text
POSITION_REVERSAL targeted: 132 passed
Full repository: 1094 passed, 130 skipped
TradingView v1.4 clean compile / pan-zoom / Replay / four alerts: PASS
Phone delivery / real fills / profitability: NOT VERIFIED
```

最终是否采纳由 Codex 根据源码、合同、测试和 TradingView 实图独立验收决定；Pro 输出不是
新的源码权威。
