# Phase 1：native 10m 主机会 + 3m 择时/管理冻结规范 R3

日期：2026-08-01
源码基线：`c6f1017df1655d932f5d834737cdac66cc292988`
10m 协议：`phase1-10m-primary-opportunity-3.0`
3m 协议：`phase1-3m-opportunity-timing-3.0`
适用宿主：标准 K 线 `CAPITALCOM:SPX500`；native 10m producer 与窄 3m companion
性质：只读、confirmed-only、无订单、无 alert、无盈利或方向 edge 声明

## 1. R3 冻结裁决

本版本只启用：

```text
TREND_CONTINUATION = enabled
POSITION_REVERSAL  = disabled
```

职责不可交换：

```text
native confirmed 10m
    决定慢方向、pullback episode、WATCH、主机会、entry permission、冻结 plan 与 primary terminal

confirmed 3m
    只消费一个 10m opportunity_id；做同向入场择时；入场后管理同一冻结 stop/target

VIX / SATy / ATR / divergence / overnight / AI score
    advisory-only 或未接入；本轮不 grant、不 veto、不投票、不加权
```

空间门禁继续硬冻结：

```text
可信具名目标不存在       -> SPACE_UNKNOWN / 无大机会
可信目标存在但 space_R<1 -> DONT_CHASE / 不追
space_R>=1                -> 才能 MAIN_LONG / MAIN_SHORT
```

R3 不以取消 1R、跳过较近障碍、使用未来水平或放宽 confirmed-only 来增加信号密度。

## 2. R3 两个纠正项

### 2.1 entry permission 与 entered-plan management 分离

10m primary 的 `MAX_ACTIVE_BARS=12` 只定义 **entry permission** 的最长寿命。它回答的是：尚未入场的 3m companion 是否还能接纳该机会并产生一次择时入场。

3m 已进入 `ENTERED` 后，切换到独立的 **entered-plan management** 生命周期：

```text
固定 owner          = 已入场的原 opportunity_id
固定 direction      = 原 10m direction
固定 invalidation   = 原 frozen invalidation
固定 target         = 原 frozen named level
固定 target source  = 原 source identity
```

以下事实不得驱逐 `ENTERED`：

```text
10m ACTIVE_EXPIRED / EXPIRED pulse
后续 active_plan=None
后续出现不同的新 10m opportunity_id
10m 慢 epoch 后续 rearm 或发出另一机会
```

`ENTERED` 只在以下终止：

```text
1. 同一冻结 plan 的 confirmed-close invalidation；
2. 同一冻结 target 被 3m high/low 触及；
3. 与当前 owner identity 匹配的 primary INVALIDATED pulse；
4. 与当前 owner identity 匹配的 primary TARGET_REACHED pulse；
5. 已冻结的 fail-closed 3m 数据/宿主 reset。
```

同 K 同时满足 invalidation 与 target 时，invalidation 优先。不同 opportunity 的 primary pulse 不得终止当前 owner。

对尚未进入 `ENTERED` 的 plan，10m permission expiry 仍会结束该 permission，并把同一 ID 放入 suppression；`same ID active again -> OPPORTUNITY_SUPPRESSED`。

### 2.2 previous completed ET day 必须完整

`PREVIOUS_COMPLETED_DAY_HIGH/LOW` 只有在上一 ET calendar day 满足全部条件时才发布：

```text
first observed timestamp = ET 00:00
last observed timestamp  = ET 23:50
bar count                = 144
每个相邻 timestamp       = 600 秒
rollover date            = 紧邻的下一 ET calendar date
```

以下任一情况使该 ET 日永久不合格：

```text
midday initialization
same-day 10m gap
backward timestamp
invalid OHLC/EMA
host/data reset
未从 ET 00:00 开始
未连续观察到 ET 23:50
不是在紧邻下一 ET 日 rollover
```

不合格日发布：

```text
previous_day_high = null / na
previous_day_low  = null / na
```

它也不得进入后续 touch-time candidate set。日期计算使用 `America/New_York`；Pine 用 ET day key 与 23/24/25 小时 UTC-midnight 差识别紧邻 ET 日期，Python 用 ET `date + 1 day`。在 DST 切换日若实际序列不能同时满足严格 144 根和连续 600 秒，则按本合同 fail closed，不把部分日冒充 completed day。

## 3. EMA 角色

固定计算：

```pine
EMA5  = ta.ema(hl2, 5)
EMA12 = ta.ema(hl2, 12)
EMA21 = ta.ema(close, 21)
EMA48 = ta.ema(close, 48)
```

角色：

- **Ripster Cloud** 只指 EMA5/12；
- EMA21/48 是慢结构；
- 5/12 暂时反向只描述 pullback/rebound，不单独生产相反主方向。

慢多：

```text
EMA21 > EMA48
AND confirmed close >= EMA48
```

慢空镜像：

```text
EMA21 < EMA48
AND confirmed close <= EMA48
```

因此慢多 + 5/12 暂转空不得发 `MAIN_SHORT`；慢空镜像。

## 4. 10m 宿主、数据与时间合同

状态仅在以下条件全部成立时推进：

```text
symbol         = CAPITALCOM:SPX500
host timeframe = 10m
chart          = standard candles
bar            = confirmed
OHLC/EMA/tick  = finite and valid
```

forming 10m 不推进 timestamp、ET day、pivot、age、state、candidate、plan 或 event。

时间异常：

```text
same timestamp duplicate -> DATA_DUPLICATE_IGNORED；不推进、不消费、不重置
timestamp backward       -> DATA_NON_MONOTONIC；primary fail-closed 全重置
timestamp gap != 600s    -> DATA_GAP_RESET；当前 K 只重建 context，不建立 episode
```

10m gap/invalid/backward reset 会使当前 ET day 不合格，并清除 previous-day eligibility；不得跨 reset 拼成完整日。

## 5. 身份与状态边界

Python canonical identity：

```text
epoch_id       = direction + epoch start timestamp
episode_id     = direction + full-departure timestamp
opportunity_id = direction + 10m reclaim confirmation timestamp
```

Pine 运行时用 `direction + opportunity confirmation time` 表达同一 identity。

约束：

- 一个连续 slow epoch 可包含多个 pullback episodes；
- 每 episode 最多一个 WATCH 和一个最终决定；
- 每 opportunity_id 最多一个 3m entry marker；
- 每 opportunity_id 最多一个终止 marker；
- plan 的 direction、entry、invalidation、target、target source、confirmation time 必须同源复制，不得跨 ID 混配。

## 6. causal named-level router

### 6.1 允许来源

| Source | 因果可用时点 | 用途 |
|---|---|---|
| `PRIOR_EXCURSION_10M` | episode departure 后、touch 前，只沿趋势方向更新 | long 前方阻力 / short 前方支撑 |
| `CONFIRMED_PIVOT_10M` | strict left=2/right=2 的两个 right bars 都 confirmed 后 | long pivot high / short pivot low |
| `PREVIOUS_COMPLETED_DAY_HIGH` | 完整 144 根 ET 日在紧邻次日 rollover 后 | long 前方阻力 |
| `PREVIOUS_COMPLETED_DAY_LOW` | 同上 | short 前方支撑 |

forming 当前日 high/low 禁止进入 router。Pivot provenance time 是中心 K 时间，但只有两个 right bars 完成后才可用。

### 6.2 touch-time freeze

first touch 只冻结当时已经因果可见、尚未消费且位于 touch whole range 前方的 candidate：

```text
long  candidate.price > touch.high
short candidate.price < touch.low
```

冻结字段：

```text
price
source identity
provenance time
consumed=false
```

Touch 后才确认的新 pivot、后来才完成的日线或后来形成的任何水平，均不得回填当前 episode。

### 6.3 排序、消费与 nearest-first

确定性排序：

1. 方向前方最近价格：long 升序，short 降序；
2. 同价 source priority：`PRIOR_EXCURSION_10M` → `CONFIRMED_PIVOT_10M` → previous completed day；
3. 同价同 source：较早 provenance time。

从 touch 后第一根 strictly later confirmed K 开始：

```text
long  bar.high >= candidate.price -> consumed
short bar.low  <= candidate.price -> consumed
```

确认 K 也按 whole-bar high/low 先消费；选择时再次要求：

```text
long  candidate.price > confirmation.high
short candidate.price < confirmation.low
```

不得跳过较近未消费障碍去选更远目标制造 `>=1R`。若无可信候选或 risk 无效，必须 `SPACE_UNKNOWN`。

## 7. native 10m TREND_CONTINUATION 状态机

### 7.1 状态

| 状态 | 含义 |
|---|---|
| `DISABLED` | 宿主或数据合同不满足 |
| `WAIT_TREND` | 等待单一 EMA21/48 慢方向 |
| `WAIT_CLEAR` | epoch 初始或 episode terminal 后，等待 later full departure |
| `ARMED` | episode 已建立，等待第一次 later cloud touch |
| `WAIT_REACTION` | WATCH 已发，等待 later reclaim / invalidation / expiry |
| `ACTIVE` | 10m entry permission active，允许尚未入场的 3m companion 择时 |

Primary 不使用永久 `LOCKED`。

### 7.2 Episode 顺序

Long：

```text
confirmed slow-long
-> strictly later confirmed full departure above 5/12 cloud
-> ARMED
-> first later pullback touch
-> WATCH_LONG；冻结 reaction/invalidation/candidates
-> strictly later confirmed reclaim
-> consume candidates with whole-bar ranges
-> nearest valid named-level route
-> calculate risk and space_R
-> MAIN_LONG only when space_R>=1
```

Short 完全镜像。

Full departure：

```text
long : fast direction long AND low > cloud upper AND close > cloud upper
short: fast direction short AND high < cloud lower AND close < cloud lower
```

Touch K 只发 WATCH，不能自行确认。`WATCH 不创建 `OpportunityPlan``；`opportunity_active=false`，绝不授权 3m 入场。

### 7.3 WATCH、确认与失效

Long WATCH 冻结：

```text
reaction_high       = touch.high
reaction_low        = touch.low
frozen invalidation = min(touch.low, touch EMA48) - 2 ticks
```

Short 镜像。

Later long reclaim 必须同时满足：

```text
EMA5 > EMA12
close > frozen reaction_high
close > current cloud upper
```

Short 镜像。确认必须来自 strictly later confirmed 10m K。

### 7.4 1R gate

确认 K close 是 entry reference：

```text
risk_long  = entry - invalidation
space_long = target - entry
risk_short = invalidation - entry
space_short= entry - target
space_R    = space / risk
```

```text
risk<=0 或 target 不可信 -> SPACE_UNKNOWN
0 <= space_R < 1.0       -> DONT_CHASE
space_R >= 1.0           -> MAIN
```

等号属于许可侧。

### 7.5 Terminal 与 rearm

`WAIT_REACTION` 优先级：

```text
frozen invalidation break
> slow-context loss
> candidate consumption
> reaction expiry
> later reclaim/router/1R
```

`ACTIVE` 优先级：

```text
invalidation
> target reached
> slow-context loss
> entry permission expiry
```

同 K stop 与 target 同时出现，invalidation 优先。

任何 episode terminal 后：

```text
terminal
-> WAIT_CLEAR
-> strictly later confirmed full departure
-> new episode_id
-> ARMED
```

**terminal 同 K 绝不 rearm**。没有 later full-clear/departure 就不能在同一 slow epoch 新建 episode；不使用任意 cooldown 代替该因果条件。

## 8. primary entry permission 生命周期

`MAIN_LONG/MAIN_SHORT` 激活后：

```text
opportunity_active=true
MAX_ACTIVE_BARS=12
```

该期限只约束“尚未入场”的 3m permission。Primary 在自身层继续按 confirmed 10m 处理：

```text
INVALIDATED
TARGET_REACHED
ACTIVE_EXPIRED
slow context lost
```

Primary `ACTIVE_EXPIRED` 后可进入 `WAIT_CLEAR` 并在 later full departure 建新 episode；这不会撤销已进入 `ENTERED` 的旧 3m owner。

## 9. 3m completed-10m transport

3m companion 只处理 standard confirmed 3m K。其 embedded 10m source 采用：

```text
request.security(..., lookahead=barmerge.lookahead_off)
completed-source offset
source close time <= current confirmed 3m open time
source timestamp strictly newer than last processed source timestamp
```

因此形成中的 10m 不可用于 3m permission。跨越 10m close 边界但可能已触及 stop/target 的区间采用 fail-closed handoff 信息，不假装目标仍未到达。

3m 接收的 frozen unit：

```text
opportunity identity
direction
entry reference
invalidation
target
target source
confirmation time
primary terminal pulse + matching plan identity
```

## 10. 3m entry permission 状态机

状态：

```text
DISABLED
WAIT_10M
WAIT_PULLBACK
WAIT_TRIGGER
ENTERED
LOCKED
```

尚未入场时：

```text
adopt new active 10m plan
-> adoption K 禁止入场
-> later first 3m 5/12 touch
-> freeze touch high/low trigger
-> strictly later confirmed directional trigger
-> fast 5/12 direction agrees
-> recalculate remaining space_R against same frozen stop/target
-> remaining space_R>=1
-> at most one LONG_ENTRY / SHORT_ENTRY
```

Trigger 最多等待 8 根 confirmed 3m K；到期后锁定并 suppress 同一 ID。实际 entry close 处若剩余空间未知或 `<1R`，也锁定并 suppress。

尚未入场的旧 plan 可由不同新 plan 替换；replacement K 只 adopt，不入场。旧 plan 的 invalidation/target 终止优先于 replacement，退出/失效 K 不反手。

## 11. 3m entered-plan management

一旦 entry confirmed：

```text
state = ENTERED
reason = ENTERED_PLAN_MANAGEMENT
visible action = 多入已触发｜按计划管理 或 空入已触发｜按计划管理
```

每根后续 confirmed valid 3m K 都使用原 owner 的 stop/target：

```text
long invalidation : close < frozen invalidation
short invalidation: close > frozen invalidation
long target       : high >= frozen target
short target      : low <= frozen target
```

Primary terminal pulse 只有在 `primary_event_plan.opportunity_id == current owner` 时生效。不同新 10m plan 不能替换已 `ENTERED` 的旧 plan，也不能在 replacement K 反手。

Entered terminal：

```text
LONG_INVALIDATED / SHORT_INVALIDATED
LONG_TARGET_REACHED / SHORT_TARGET_REACHED
```

每个 owner 最多一个 entry marker 与一个 terminal marker。进入 `LOCKED` 后不重复 marker。

## 12. suppression 与 fail-closed reset

3m canonical suppression identity：

```text
direction + 10m confirmation time
```

以下 plan 结果都会 suppress 同一 ID：

```text
entry emitted
trigger expired
remaining space <1R
invalidated
target reached
permission ended
```

Suppression 跨以下 reset 保留：

```text
3m timestamp gap
invalid OHLC/EMA
host mismatch
non-standard chart
backward timestamp
```

这些 fail-closed reset 会释放当前 runtime owner，包括 `ENTERED`；这是 R3 唯一允许在没有 stop/target terminal 时清除 entered management 的数据安全边界。相同 ID 重新出现时不得 adopt；只有不同 ID 才能解除旧 suppression。

## 13. 默认图形合同

### 13.1 Native 10m 主图

```text
overlay=true
无独立 scale
EMA5/12 linewidth=2
Ripster cloud transparency=72
EMA21 gold linewidth=2
EMA48 blue linewidth=3
```

默认可见历史 marker 仅两类；两类 WATCH marker 保留为可选审计开关，默认关闭：

```text
多计划：紧凑 price-anchored label
空计划：紧凑 price-anchored label
多观察 / 空观察：当前最后一根可见；完整历史需 showWatchHistory=true
```

不默认画 approach、reaction、expiry、rearm、target、audit marker。

10m card 固定 `2 x 4`：

```text
现在做
触发
失效
目标
```

不显示内部 ID；深色背景；行动字段只使用 white 或明确方向色，silver 不得用于行动文本。

### 13.2 3m timing/management 主图

```text
EMA5/12 linewidth=2
3m Ripster cloud transparency=72
previous-completed 10m cloud overlay default=false
frozen invalidation/target lines default=true only while WAIT_PULLBACK/WAIT_TRIGGER/ENTERED owns plan
plan lines linewidth=1 and price anchored
```

默认 decision markers 仅：

```text
多入 / 空入
多失 / 空失
多达 / 空达
```

无 dynamic label/line/box。

3m card 固定 `2 x 4`：

```text
现在做
触发
失效
目标
```

`ENTERED` 时必须显示方向拥有者而不假装读取账户持仓：`多入已触发｜按计划管理` 或 `空入已触发｜按计划管理`。10m entry permission 到期后仍保持该 entered management 文案和冻结价格。

## 14. Python/Pine parity 与生成合同

两份 Pine 的 native-10m canonical block 必须由同一 generator 生成，并逐字节相同。R3 canonical block SHA-256：

```text
c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2
```

生成器是权威来源；不得只手改生成后的 Pine。`--check` 必须验证两份 Pine 与 generator 输出一致。

Python oracle、Pine canonical engine、3m timing Pine 和 tests 必须共同锁定：

```text
confirmed-only
causal named-level router
strict full-day publication
entry permission / entered-plan management split
identity-bound terminal pulses
invalidation-before-target
no same-bar confirmation/reversal
suppression across reset
1R hard gate
visual marker/card budget
```

## 15. 明确排除

本轮不实现：

```text
POSITION_REVERSAL
SATy / ATR / VIX / divergence / overnight producer
AI score or vote
alertcondition / alert()
strategy.* / order / broker action
parameter optimization
win rate / P&L / profitability claim
```

## 16. 外部验收边界

随包可验证：

```text
manifest
source scan
generator parity
Python tests
compileall
337-bar native 10m deterministic replay
caller-path 10m->3m deterministic replay
```

下列项目除非另有外部证据，否则必须记录 `NOT RUN`：

```text
TradingView Pine v6 online compile
remove/re-add, pan/zoom, Replay, Data Window visual acceptance
完整 dirty-repo / P7-R owner-state gates
live market validation
alerts/orders/deployment
profitability or trading edge validation
```
