# Phase 1 下一独立层：位置反应 / 反转预实现合同

日期：2026-08-01
基线：`c6f1017df1655d932f5d834737cdac66cc292988`
状态：只冻结下一步交易合同；尚未编码、尚未上图、尚未创建 Alert

## 为什么这层必须独立

当前 R3 只负责 `TREND_CONTINUATION`：10 分钟给出趋势续行观察和许可，3 分钟只做
择时与已入场计划管理。它不应该为了覆盖 2026-07-31 的两个关键转折而临时改变 EMA
owner 或增加一堆 3 分钟标签。

下一层单独负责 `POSITION_REVERSAL`：

```text
prior-confirmed 具名位置 -> confirmed 10m 反应 -> immutable opportunity
  -> 3m adopt-only -> later entry / frozen-plan management
```

核心交易法则是用户提出的：**有反应才考虑，没反应不买卖。** 位置、VIX 极值或背离
本身都只能提高注意等级，不能单独授权新仓。

## 盘面职责

| 窗口 | 只负责什么 | 默认显示 |
|---|---|---|
| SPX 10m 主图 | 位置、反应方向、与慢结构关系、最近阻力/支撑 | `支撑观察`、`反弹确认`、`阻力观察`、`压回确认` |
| SPX 3m | later entry timing 和已入场计划管理 | `多入`、`空入`、`失效`、`达标` |
| VIX 10m | 关键位反应的逆向 advisory | 卡片一行 `配合 / 缺失 / 冲突 / 不可用`，不画交易信号 |

3 分钟不得重复 10 分钟的观察标签；10 分钟不得隐藏大机会、只把所有信息塞到 3 分钟。

## 允许进入状态机的位置

正式位置必须携带 `source_id + source_version + lower_bound + upper_bound + published_at`
以及 `level_known_at + stability`。`level_known_at` 必须不晚于 touch/reaction K 的
bar-open；当前 K 最终计算出的 EMA 或 Cloud 不得解释同一 K 早先的 high/low。

正式 producer allowlist：

1. 当日 SATy/ATR 具名位与上下 trigger；
2. 夜盘前高 / 前低；
3. previous close / previous completed day high-low；
4. previous-completed 且精确版本化的 MTF Cloud，例如 `MTF-D50_55-PC` 或
   `MTF-D20_21-PC`；
5. prior-confirmed 10 分钟 EMA21/48；其他长周期 Cloud 必须先进入显式 allowlist，只作为
   具名阻力/支撑来源，不冒充 Ripster 5/12，也不再次投票决定慢方向。

SATy/手工位还必须携带 `published_at + version`；若发布时间晚于 touch，直接排除。
previous-day high/low 继承完整、连续 144 根 ET 10m K 的资格门禁。夜盘 high/low 必须携带
唯一 `cluster_id`、预先冻结的 bounds 和 `constructed_at`。

形成中的 MTF 值永久为 `ADVISORY_ONLY`：可以在 live 卡片显示“形成中/可漂移”，但不得
推进 reaction、生成 opportunity、授权 entry 或进入历史 replay。正式 producer 在 live、
reload 和 replay 中一律只用 previous-completed；除非将来另有外部 append-only snapshot
ledger，否则不开放 forming MTF producer。

## 10m immutable opportunity 与状态机

confirmed 10m reaction 负责一次性生成完整、不可变 payload：

```text
lane_id + opportunity_id + episode_id + source_id + source_version
direction + trigger + invalidation + target + target_source
confirmation_time + visible_at + expires_at
```

3 分钟只能 adopt 该 payload、按同一 stop/target 重新核算 entry 时 remaining `R`、产生
later entry 和处理 terminal；不得自行改造 stop/target，也不得从另一个 source 拼计划。

状态固定为：

```text
WAIT_CLEAR -> APPROACH -> REACTION -> READY / FAILED / EXPIRED -> WAIT_CLEAR
```

- 支撑 band 为预先冻结的 `[lower_bound, upper_bound]`。`low <= upper_bound` 构成 touch；
  touch 后最多 `MAX_REACTION_BARS = 3` 根 confirmed 10m K 内，`close > upper_bound` 才是
  reclaim；`close < lower_bound` 是 accepted break / `FAILED`。
- 阻力对称：`high >= lower_bound` 构成 touch；`close < lower_bound` 才是 rejection；
  `close > upper_bound` 是 accepted break / `FAILED`。
- close 留在 band 内时只保持 `APPROACH`，不称确认。第 3 根仍无 reclaim/rejection 时
  `EXPIRED`。同 K 可以 touch + reaction，但绝不能同 K 3m entry。
- terminal 后，只有一整根 confirmed 10m K 完全离开旧 band 的原反应侧，且 close 至少
  离 band `0.12 ATR`，才完成 `WAIT_CLEAR`；回到旧位才可建立新 episode。
- 每个 episode 最多一次 watch、一次 terminal，不得复用旧 source/version。

## Long：支撑反应链

1. **接近**：价格进入支撑 band，10 分钟显示 `支撑观察｜停止追空`；不发布买入。
2. **反应**：按上述机械 band 合同 confirmed reclaim；10 分钟显示 `反弹确认`，卡片动作
   为 `停止追空 / 保护已有空头`，并生成完整 immutable long opportunity。
3. **3m later confirmation**：只能发生在上述反应最早可见之后；later 3 分钟 5/12
   方向转多并收过冻结触发 K 高点，且到最近阻力仍有至少 `1R`，才显示 `多入`。
4. **保护**：由 10 分钟 opportunity 冻结在同一反应 episode 的低点下方。
5. **目标**：由 10 分钟 causal nearest-first router 冻结当时已经可见的最近未消费阻力；
   10m 生成 plan 时与 3m 实际 entry 时都必须满足 `>=1R`。目标触及后显示 `达标 / 前方阻力`，
   不能继续写“无条件持多”。

若价格只是触及支撑后继续 confirmed close 接受在其下方，则直接 `支撑失效`，不出现
反弹确认或多入。

## Short：阻力反应链

1. **接近**：价格进入阻力 band，10 分钟显示 `阻力观察｜停止追多`；不发布卖空。
2. **反应**：按上述机械 band 合同 confirmed rejection；10 分钟显示 `压回确认`，卡片动作
   为 `停止追多 / 保护已有多头`，并生成完整 immutable short opportunity。
3. **3m later confirmation**：只能发生在上述反应最早可见之后；later 3 分钟 5/12
   方向转空并收破冻结触发 K 低点，且到最近支撑仍有至少 `1R`，才显示 `空入`。
4. **保护**：由 10 分钟 opportunity 冻结在同一反应 episode 的高点上方。
5. **目标**：由同一 causal nearest-first router 冻结最近未消费支撑；10m plan 与 3m entry
   都必须满足 `>=1R`。触及时显示 `达标 / 前方支撑`。

若价格在阻力上方 confirmed close 接受，则直接 `阻力失效`，不出现压回确认或空入。

## SATy、VIX 与 divergence 的边界

- SATy/ATR 或 previous-completed MTF Cloud 可以拥有“位置”，不能凭一次触及直接拥有方向。
- VIX 到上方阻力后拒绝，可为 SPX 支撑反弹提供 `配合`；VIX 接受突破则为 `冲突`。
- VIX 到下方支撑后反弹，可为 SPX 阻力压回提供 `配合`。
- divergence 当前固定为 `NOT_IMPLEMENTED / UNAVAILABLE`。只有另立 causal prior-pivot、
  confirmed-at 和 no-backfill 规格并独立通过后，才可显示 `同在 / 缺失 / 冲突`；该字段
  必须物理排除在 permission、arbiter 和 space 计算之外。
- 任一 advisory 数据不可用时只禁用该行，不得估值，也不得让整个价格状态机静默改向。

## 全局冲突与所有权

优先级固定：

```text
host/data fail-closed reset（保留 suppression）
  > 已 ENTERED 计划失效
  > 已 ENTERED 计划达标
  > 已 ENTERED 计划继续管理
  > 已 adopt、尚未入场的现有 plan
  > 新 permission 的确定性仲裁
  > 观察 / advisory
```

- 全局任一时刻只允许一个 outward/adopted/entered plan。已入场计划的完整 immutable payload
  在 terminal 前不可被新 lane 替换、追加第二仓或自动反转。
- 已 adopt、尚未入场的 plan 同样保持 owner 至失效/达标/许可到期；不同新 id 不替换。
- 没有现有 owner 时，趋势续行与位置反转同 K 反向固定 `CONFLICT / NO_NEW_ENTRY`；同向只
  选择 `visible_at` 最早者，完全同时时按固定 allowlist `TREND_CONTINUATION` 再
  `POSITION_REVERSAL`，不以证据数量投票。
- 新 opportunity 到达的 3m K 只 adopt，不得同 K entry；entry 必须发生在 later confirmed K。
- 同一 3m K 同时碰到 stop 和 target 时，invalidation 优先；primary invalidation/target pulse
  仍能结算其原 owner，permission expiry 只结束未入场 plan，不清除 ENTERED 管理。
- 同向证据只写在原因行，不能自动跳过 3 分钟确认或 `>=1R` 门槛。
- 所有 marker 使用 bar-bound plotshape 或绝对价格锚点；禁止动态漂浮 label/line/box。
- 10m 所有 lane 合计每根 confirmed K 最多一个 outward marker，每 episode 一次 watch 和
  一次 terminal；3m 所有 lane 合计每根 K 最多一个 `多入/空入/失效/达标`。VIX 与
  divergence 永不画 SPX marker；10m/3m 卡片各最多 4–5 行。

图上短词固定为 `支撑观察 / 反弹确认 / 阻力观察 / 压回确认`。`停止追多/空`、
`保护已有仓` 只写卡片，不再产生额外 marker。

## 2026-07-31 两个必须复现的正例

### A. 上方阻力压回

- 上方 trigger：`7467.7954`；09:30 ET 10m K 高点 `7486.3`、收盘 `7465.1`，到
  `09:40` 才可见。
- fixture 必须预先冻结唯一 cluster bounds；若 overnight high 的 `constructed_at` 晚于
  09:30 bar-open，则 causal fixture 只准使用此前已知 upper trigger，overnight high 仅保留
  为描述性背景。
- 10m 可在 09:40 生成 `压回确认` opportunity。第一个可完整消费它的 3m bar-open 是
  `09:42`，该 K 只能 adopt；理论最早 entry bar-open 是 `09:45`（09:48 confirmed）。
- 最近下方障碍必须参与空间计算；不能在已经接近下方 trigger 时继续追空。

### B. 下方支撑收回

- source 固定为单线 band `SATY-ATR-LOWER-TRIGGER-v1`：`lower_bound = upper_bound =
  7421.2046`，并要求 `published_at / level_known_at <= 2026-07-31 11:30 ET`；不能从
  事后 MTF 值加宽。
- 10:00 close `7415.5`、10:10 close `7409.3` 属于 accepted break，前一个 episode 必须
  `FAILED`，不能被 10:20 close `7428.1` 倒填成同一“不破反转”正例。
- 10:30 K low `7424.3`、close `7435.8` 已整根回到 trigger 上方，且 close 距 trigger
  超过 `0.12 ATR`；到 10:40 可完成旧 episode 的 `WAIT_CLEAR`。
- 新的 11:30 ET 10m K low `7420.9`、close `7443.5`，在同 K 轻扫单线 band 后收回，
  到 `11:40` 才可见；这才是本 lane 必过的 `反弹确认` 正例。
- 第一个可消费新 opportunity 的 3m K 是 `11:42`，只准 adopt；理论最早 entry 是
  11:45 K（11:48 confirmed），且到 `7444.5` / prior-confirmed 慢结构等 frozen target
  仍须 `>=1R`。若最近目标在 adoption 前已被消费，则必须 no-entry，不能跳远找目标。
- 目标抵达慢线或上方 Cloud 后，应切换成 `达标 / 前方阻力`，不再盲目持多。

## SATy 三窗截图的证据边界

SATy 截图显示的是 `SPY`，当前生产标的是 `CAPITALCOM:SPX500`，不能混成同一个价格
fixture。截图中的 `18.43–18.75` 也没有出现在冻结的 VIX CSV source contract，因此只保留
为未验证的视觉启发，不进入测试或正式位。

当前同源 VIX 数据只支持：10:20 K close `17.87`（10:30 known）、11:20 K high `17.93`
（11:30 known）、11:30 K close `17.29`（11:40 known）。特别是 11:30 VIX 不能倒填为
11:33/11:36 的 SPX 确认。VIX 只能读取 confirmed、fresh snapshot；stale/unavailable 固定为
`UNAVAILABLE`，不进入任何 predicate。

## 必须同时保留的反例

1. 触及支撑但没有 reclaim，继续向下接受：无多入；
2. 触及阻力但在其上方接受：无空入；
3. 未实现 causal divergence 规则前：固定 `NOT_IMPLEMENTED`，不得事后补标签；
4. VIX 极值但 SPX 没有价格反应：不产生方向；
5. 价格反应成立但最近目标 `<1R`：只管理/观察，不追价；
6. trend lane 与 reversal lane 反向冲突：`NO_NEW_ENTRY`；
7. 形成中 MTF 看似完美：仍是 advisory，不能生成正式 episode 或算正例。
8. 10:00→10:20 的深度 accepted break 后 reclaim：属于以后单独的 `BREAK_RECLAIM`
   研究，不得塞进本轮“位置不破反转”。

## 实施与停机顺序

1. 先完成并实图验收 R3 `TREND_CONTINUATION`；未通过则不编码本层。
2. 只实现 SPX 10m `named position -> reaction -> immutable opportunity`，用正反 fixtures
   和 7 月 31 日 exact known-at replay 验收。
3. 再接 3m adopt-only、later confirmation 和 entered ownership；不得在 3m 再冻结 plan。
4. 再以只读字段接入 VIX；最后才接 divergence。
5. 每一步只允许上述稀疏 marker，并提供一张实际图和一张正反时间线。

任一步出现前视、漂浮、跨 episode 拼计划、同一 3m K adopt+entry、同 K 反手或标签密度
失控，立即停止，回退到上一个已经验收的独立层。10m 同 K touch+reaction 仍按机械 close
规则允许，但只能在该 10m K confirmed 后发布。三天/33 天 replay 只能验证机械行为，
不能证明盈利或胜率。

## 图上元素不代表什么

| 元素 | 代表 | 不代表 |
|---|---|---|
| 支撑观察 / 阻力观察 | 已到 prior-known 位置 | 已入场、已确认反转 |
| 反弹确认 / 压回确认 | confirmed 10m reaction 与完整 plan | 已成交、盈利保证 |
| 多入 / 空入 | 3m later timing 通过 | 自动下单、第二仓 |
| VIX / oscillator / forming MTF | advisory 状态 | permission、方向 owner |
