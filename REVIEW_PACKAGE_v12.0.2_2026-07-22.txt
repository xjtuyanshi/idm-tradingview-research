# IDM v12 Follower — 外部代码审查包（Review Package）

生成于 2026-07-22 · 版本 12.0.2-follower（TradingView 端 v15.0，SHA-256 前16位 `39611b31ebbf8478`）
用途：交给外部 AI/专家做独立代码与方法论审查。本文件自包含：现状说明 + 全部核心代码。

---

## 1. 这是什么

SPX500（CAPITALCOM，CFD，近 24 小时行情）日内决策辅助的 TradingView Pine v6 策略脚本（仅提示，**从不下单**；
strategy.* 订单模块默认关闭仅作研究脚手架）。运行形态：同一脚本挂在 2×2 布局的两个窗格——
3 分钟图（执行/事实源）与 10 分钟图（同源镜像）；另有手机推送（TV alert，alert() 调用流）。

三层结构：
1. **冻结引擎 v11**（信号/计划/事件的唯一裁决，字节级冻结）：四类信号（关键位拒绝/回踩延续/突破/趋势启动）
   × A/B/C 等级 × 顺势/逆势路由；每根 3 分钟收盘确认后产出 SignalEvent 与交易计划（Entry/Stop/T1/T2）。
2. **v12 跟单模块（follower）**：预登记规则的执行层——只跟 LEVEL_REJECTION 信号、默认早午盘 09:30–14:00 ET、
   同一时间只持一单、止损全程不动（绝不移保本）、T1 兑现 50%/T2 兑现 25%/剩余 25% 持到日终或原止损、
   全额止损后同向冷却 30 分钟。图上画开/平仓标签与四条线，面板记分板（毛 R + 按 0.5 点/往返成本的费后 R），
   推送【v12跟单】事件。
3. **显示/推送层**：Ripster 风格三组云、静态 Saty 日 ATR 梯位、四行中文面板、10m 状态镜像、分层推送流。

## 2. 必须尊重的硬约束（review 时请勿建议违反）

- **字节冻结区**：`f_v11_engine(bool processConfirmedClose) =>` 到 `// Dense state + sparse primitive event relay`
  之间的引擎文本被测试逐字节断言，不可改（这是从旧版本继承的回归保护：改引擎必须走独立的 Python 复刻
  replica + 逐事件 parity 验证流程，不在本次 review 范围）。
- **冻结洞（已知，review 可指出但別建议轻动）**：引擎喂给函数（f_pick_*、f_candidate_*、f_nearest_saty、
  f_setup_priority）与引擎参数输入定义在冻结切片之外——改它们不触发字节测试但改变引擎行为。
- **v12 跟单交易规则已预登记**（记分板只进不改，改规则=前向样本清零）：决策逻辑（吃哪些信号、时段、冷却、
  止损/T1/T2/日终结算算式、50/25/25 比例）不可变；其显示/文案/组织可改。
- **CE10057 污染纪律**：任何写入跟单状态（f12.*）或被 request.security_lower_tf 表达式引用的变量的作用域，
  禁止出现 alert()/label.new()（TradingView 会顺数据流报 CE10057 编译错）。现文件合规。
- 订单模块语义冻结（默认关）；【v12跟单】推送语义保持。

## 3. 统计现状（诚实版——请不要被样本内数字迷惑）

13-14 天全量回演中"拒绝类·早午盘·单仓·止损不动"组合 31 笔、均 +0.093R——**但独立对抗性统计审查判定
该数字为选择噪声+单笔彩票**：~880 个被检视统计量的三层同数据择优（家族极值零假设 p=0.87，纯噪声期望冠军
+0.18 高于观测值）；净值几乎全部来自一笔 +2.90R（其余 30 笔合计 −0.02R）；前 5 大赢单全为"尾仓持到日终强平"
所得；经验贝叶斯收缩权重 0，对折检验样本外为负；成本断点 0.39 点/往返低于该 CFD 常态点差（0.5 点下全样本
−0.85R）。**前向点估计 ≈ −0.15R/笔；系统定位=预登记试验品**，淘汰制协议：60 笔一批，累计净 ≤ −10R 淘汰、
前 20 笔实测摩擦 > 0.4 点淘汰、60 笔无一笔 ≥+1.5R 日终 runner 淘汰；"验证"需 ≥385 笔且费后 t ≥ 1.645。
仍然可信的机械事实（全量、不靠择优）：旧引擎"T1 后立即保本"把均赢封死在 +0.80R（打平需 53.3% 胜率）；
取消保本把打平线降到 37-39%；趋势启动类 57% 秒杀率（n=124）。

## 4. 已知问题 / 设计边界（按重要度；review 重点可放这里）

1. 3m 不整除 10m：10m 主机上的 request.security_lower_tf **实时**稀疏脉冲可能丢/迟约 20%（历史致密状态完整；
   状态类中继每次刷新自愈，跟单镜像不受累积影响；3m 图上的 alert 主机不受影响）。
2. 两窗「累计R」基数不同：3m 主机 calc_bars_count=1500（≈3 天 3m K），10m 镜像 lower_tf 覆盖 4000 根 3m
   （≈8 天）——已声明设计，前向记分以 3m 窗为准。
3. 订单模块若被打开，执行的是**旧引擎**计划几何（含保本移动），与 v12 跟单"止损不动"不一致（默认关+文档警告）。
4. 跟单状态机的时序边界：同 bar 止损优先（歧义保守）；日终=CAPITALCOM 日界（time("D") 变更时按前收平仓）；
   同 bar 平仓后不再开新仓；冷却仅在"未到 T1 的全额止损"后触发。
5. 10m 镜像的平仓标签位置取整根 10m K（金额精确）；净R 读 10m 现价（与 3m 差 tick 级瞬时值）。
6. 中继端 Saty 二拒文案是 f_advisory_message 的手工内联副本（中继无首测/离开时间戳），两处需人工同步。
7. varip 双游标（alert 用 varip、显示用 var）与引擎同款竞态特征（罕见 tick 时序）。
8. 绘图预算：plot 类 50/64、线对象稳态 24/30、标签上限 400——扩展前需先扩预算。

## 5. 想请外部 reviewer 回答的问题

1. 逻辑正确性：跟单状态机（§13-15 代码）在边界条件下是否有漏洞？（同 bar 开+日终、冷却窗跨日、
   T1/T2 同 bar、镜像 prev* 对比、na 传播）
2. CE10057 纪律是否还有隐患路径（间接依赖）？
3. 双窗一致性方案（状态中继 + last-value）是否有更稳的 Pine 惯用法？
4. Pine v6 性能/资源：security 调用、数组消费循环、islast 重建模式有无更优写法？
5. 显示层还有哪些冗余/矛盾（我们已做过两轮清理，欢迎再挑）？
6. 统计方法论：对第 3 节的对抗审查结论有无异议或补充检验建议？
7. 在不违反第 2 节约束的前提下，你会优先重构什么？

---

## 6. 完整代码

### 6.1 主脚本 intraday_decision_map_v11_2_clear.pine（Pine v6，运行于 TradingView）

```pine
//@version=6
//@strategy_alert_message {{strategy.order.alert_message}}
// IDM v11.2 Clear → IDM v12 Follower
//
// 12.0 增补契约：v12 跟单模块是「预登记试验品」（对抗审查 2026-07-22）——
// 交易规则冻结（拒绝类·早午盘·单仓·止损不动·V1 分批·冷却），记分板只进
// 不改，改规则=清零重计；记分板另按成本假设记「费后」净值。引擎与订单
// 模块零改动；跟单状态经状态中继镜像到 10m 窗，两窗同一事实源。
//
// 11.2 CONTRACT (delta over 11.1; engine still byte-identical to frozen 11.0)
//   * Ledger-driven defaults (13-day plan ledger, n=657): countertrend and
//     Trend-Ignition signals are hidden and silenced by default (T1-first
//     26.9% / 14.7%, avg R -0.44 / -0.71); alerts default to US regular
//     hours.  Display/alert filters only - the engine, orders and Strategy
//     Tester results are untouched.
//   * The sawtooth S1/R1 and historical plan-line plots moved to the Data
//     Window; the chart instead shows the static Saty daily ladder plus
//     PDH/PDL rails and four clean lines for the CURRENT plan only.
//
// 11.1 CONTRACT (delta over the frozen 11.0.0-clean)
//   * The signal/plan/order engine below is byte-identical to the frozen
//     release.  11.1 changes PRESENTATION and adds one informational
//     AdvisoryEvent; it must never alter SignalEvent ids, plans or orders.
//   * Saty second-rejection advisory: first confirmed rejection of one
//     static daily-ATR level -> real departure -> second confirmed
//     rejection of the SAME level -> chart mark + Chinese alert only.
//   * Marker declutter: full labels only for trend-side entries and
//     reversals; countertrend probes shrink to 逆多/逆空 tags; ADD
//     references are hidden unless explicitly enabled.
//
// CLEAN-SLATE CONTRACT
//   * The 3-minute tape is the only signal engine.
//   * The previous fully-confirmed 10-minute bar supplies context.
//   * Four direct setups may fire on the bar that proves them.  There is no
//     FIRST_TEST / DEPARTED / RETEST episode state machine, global cooldown,
//     daily quota, session gate, or fixed timeout exit.
//   * A/B/C are transparent rule grades.  They are NOT win probabilities.
//   * Entry, initial Stop, T1 and T2 are frozen when a SignalEvent is created.
//   * A 10-minute host is a read-only view of the same 3-minute ledger.
//
// SCALE CONTRACT
//   overlay=true; every Cloud and plan line uses the symbol's price scale.
strategy("IDM v12 Follower", shorttitle="IDM v12",
     overlay=true, pyramiding=0, calc_on_every_tick=true,
     // Entry and every frozen bracket are declared in the same confirmed-close
     // execution.  A fill-triggered recalculation is unnecessary here and can
     // roll ordinary `var` engine state back inside the same bar, producing a
     // historical/realtime fork or duplicate order side effects.
     calc_on_order_fills=false, process_orders_on_close=true,
     dynamic_requests=true,
     calc_bars_count=1500,
     default_qty_type=strategy.fixed, default_qty_value=2,
     // CAPITALCOM:SPX500 is a spread-priced CFD, not an ES futures
     // contract.  A hard-coded ES cash-per-contract fee made every two-unit
     // round trip pay $9 before price P&L and turned small winning T1 legs
     // into reported losses.  Keep the cross-symbol default neutral; users
     // testing ES/MES must set their actual broker commission in Properties.
     commission_type=strategy.commission.cash_per_contract,
     commission_value=0.0, slippage=2,
     max_labels_count=400, max_lines_count=30)

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const string VERSION_ID = "12.0.2-follower"
const string TF_ENGINE = "3"
const string TF_CONTEXT = "10"
// Bound every cross-timeframe dataset.  In particular, a 10m host must not
// retain lower-TF array IDs across an unlimited chart history.
const int ENGINE_CALC_BARS = 1500
const int RELAY_CALC_BARS = 4000
const int SIDE_SHORT = -1
const int SIDE_FLAT = 0
const int SIDE_LONG = 1
const string ACTION_BUY = "买"
const string ACTION_SELL = "卖"

const int SETUP_NONE = 0
const int SETUP_LEVEL_REJECTION = 1
const int SETUP_PULLBACK_CONTINUATION = 2
const int SETUP_BREAKOUT = 3
const int SETUP_IGNITION = 4

const int GRADE_NONE = 0
const int GRADE_C = 1
const int GRADE_B = 2
const int GRADE_A = 3

const int ROLE_INITIAL = 1
const int ROLE_ADD = 2
const int ROLE_REVERSE = 3
const int ROLE_COUNTERTREND_ADVISORY = 4

const int PLAN_FLAT = 0
const int PLAN_HOLD = 1
const int PLAN_PROTECT = 2
const int PLAN_EXIT = 3

const int EVENT_NONE = 0
const int EVENT_T1 = 1
const int EVENT_T2 = 2
const int EVENT_STOP = 3
const int EVENT_PROTECT = 4
const int EVENT_STRUCTURE_EXIT = 5
const int EVENT_REVERSE = 6

const int BLOCK_READY = 0
const int BLOCK_TRIGGER = 1
const int BLOCK_CONTEXT = 2
const int BLOCK_RISK = 3
const int BLOCK_SPACE = 4
const int BLOCK_COUNTERTREND = 5

// ─────────────────────────────────────────────────────────────────────────────
// Inputs
// ─────────────────────────────────────────────────────────────────────────────
// Shared display palette (display layer only; engine has no colors).
const color COL_BULL = color.rgb(0, 168, 132)
const color COL_BEAR = color.rgb(214, 55, 74)
const color COL_ENTRY = color.rgb(227, 192, 92)
const color COL_T2 = color.rgb(58, 111, 232)
const color COL_WIN = color.rgb(0, 130, 100)
const color COL_LOSS = color.rgb(160, 45, 60)
const color COL_ADV = color.rgb(255, 152, 0)
const color COL_CT = color.rgb(155, 89, 182)
const color COL_STRUCT_BULL = color.rgb(33, 150, 243)
const color COL_STRUCT_BEAR = color.rgb(255, 183, 77)
const color COL_CTX_BULL = color.rgb(33, 113, 243)
const color COL_CTX_BEAR = color.rgb(218, 139, 28)

string G_SYSTEM = "01 · 同一套 3m / 10m 系统"
string G_TRIGGER = "02 · 直接触发"
string G_RISK = "03 · 计划与回测"
string G_VIEW = "04 · 极简显示"

int paceFastLen = input.int(5, "Ripster 节奏快线", minval=2, group=G_SYSTEM)
int paceSlowLen = input.int(12, "Ripster 节奏慢线", minval=3, group=G_SYSTEM)
int anchorFastLen = input.int(34, "Ripster 趋势快线", minval=8, group=G_SYSTEM)
int anchorSlowLen = input.int(50, "Ripster 趋势慢线", minval=13, group=G_SYSTEM)
int atrLen = input.int(14, "ATR 长度", minval=5, group=G_SYSTEM)
int pivotLen = input.int(3, "确认结构左右 K 数", minval=2, maxval=8, group=G_SYSTEM)

int structureLookback = input.int(4, "结构突破回看 K 数", minval=3, maxval=12,
     group=G_TRIGGER)
int compressionLookback = input.int(8, "压缩箱回看 K 数", minval=5, maxval=20,
     group=G_TRIGGER)
float touchAtr = input.float(0.10, "触碰容差 ATR", minval=0.02,
     maxval=0.30, step=0.01, group=G_TRIGGER)
float triggerAtr = input.float(0.02, "突破确认 ATR", minval=0.0,
     maxval=0.12, step=0.01, group=G_TRIGGER)
float strongBodyRatio = input.float(0.34, "确认 K 实体占比", minval=0.20,
     maxval=0.70, step=0.01, group=G_TRIGGER)
float compressionAtr = input.float(2.20, "压缩箱最大 ATR", minval=1.0,
     maxval=4.0, step=0.1, group=G_TRIGGER)

float stopBufferAtr = input.float(0.10, "结构止损缓冲 ATR", minval=0.03,
     maxval=0.30, step=0.01, group=G_RISK)
float maxRiskAtr = input.float(1.30, "单笔最大风险 ATR", minval=0.50,
     maxval=2.00, step=0.05, group=G_RISK)
float minimumSpaceR = input.float(0.55, "最低目标空间 R", minval=0.30,
     maxval=1.00, step=0.05, group=G_RISK)
float orderQty = input.float(2.0, "回测合约数", minval=0.25,
     step=0.25, group=G_RISK)
bool enableOrders = input.bool(false, "启用 3分钟策略订单", group=G_RISK,
     tooltip="仅 3 分钟图可以下回测订单；10 分钟图永远只读。")
bool enableAlerts = input.bool(true, "启用中文动态提醒", group=G_RISK)

bool showPaceCloud = input.bool(true, "显示 3分钟 5/12 Cloud", group=G_VIEW)
bool showStructureCloud = input.bool(true, "显示 3分钟 34/50 结构 Cloud", group=G_VIEW,
     tooltip="Ripster 式结构云：3m 34/50，判断执行周期的趋势结构。")
bool showContextCloud = input.bool(true, "显示确认 10分钟 34/50 Cloud", group=G_VIEW)
bool showPlan = input.bool(true, "显示 Entry / Stop / T1 / T2", group=G_VIEW)
bool showHistory = input.bool(true, "保留历史 BUY / SELL", group=G_VIEW)
bool showLatestLabel = input.bool(true, "显示最新信号说明", group=G_VIEW)
bool showDashboard = input.bool(true, "显示四行面板", group=G_VIEW)
bool showAddMarkers = input.bool(false, "显示加仓参考小点", group=G_VIEW,
     tooltip="同向加仓参考不改变原计划；默认隐藏以保持图面干净。")
bool showCountertrendMarkers = input.bool(true, "显示逆势短打小标", group=G_VIEW,
     tooltip="修正后的 13 日账本：逆势关键位拒绝 T1 先达 45.0%、均 -0.03R，与顺势相当，恢复显示（小号标记）。")
bool showIgnitionSignals = input.bool(false, "显示趋势启动信号", group=G_VIEW,
     tooltip="修正后的 13 日账本：启动类 T1 先达 29.8%、均 -0.33R、秒杀率 57%——仍是最差信号类，默认隐藏；引擎与回测不受影响。")
bool showEngineEvents = input.bool(false, "显示引擎计划事件标记 (T1/T2/止/护/反/退)", group=G_VIEW,
     tooltip="引擎自身的计划推演事件。v12 跟单开启时默认隐藏，避免与『止损不动』规则打架；" +
         "关闭 v12 跟单时始终显示。")
bool showSatyLadder = input.bool(true, "显示 Saty 日 ATR 梯位", group=G_VIEW,
     tooltip="静态日内梯位（锚=昨收，间距=昨日 ATR 比例）+ 昨日高低。这是图上的位置标尺。")

string G_SATY = "05 · Saty 二拒提醒"
bool enableSatyAdvisory = input.bool(true, "启用 Saty 二次拒绝提醒", group=G_SATY,
     tooltip="只画图和推送提醒；绝不下单，也不修改任何已冻结计划。")
float satyDepartureAtr = input.float(0.05, "离开距离（日 ATR 倍数）", minval=0.02,
     maxval=0.20, step=0.01, group=G_SATY,
     tooltip="第一次拒绝后，价格离开该位至少这么远，之后的再次拒绝才算第二次测试。")
bool enableSatyAlerts = input.bool(true, "Saty 提醒推送", group=G_SATY)

string G_ALERTF = "06 · 提醒过滤（不影响引擎）"
bool alertTrendOnly = input.bool(false, "只推送顺势信号", group=G_ALERTF,
     tooltip="修正后的账本显示逆势拒绝质量与顺势相当，默认不过滤方向；加仓参考与逆势提示类角色始终不推送。")
bool alertSkipIgnition = input.bool(true, "不推送趋势启动类", group=G_ALERTF)
bool alertRthOnly = input.bool(true, "只在美股常规时段推送 (09:30-16:00 ET)", group=G_ALERTF,
     tooltip="盘外时段占信号量 73% 且质量更差；关闭本开关可恢复全天推送。")
string G_F12 = "07 · v12 跟单模块（13天账本验证）"
bool f12Enable = input.bool(true, "启用 v12 跟单（拒绝类·单仓·止损不动）", group=G_F12,
     tooltip="按 13 天全量账本回演选定的执行规则：只跟关键位拒绝信号，同一时间只持一单，" +
         "止损全程保持原位（绝不移保本），目标1兑现50%、目标2兑现25%，剩余25%持到日终或止损，" +
         "全额止损后同向冷却。冻结引擎与旧计划逻辑完全不受影响。")
string f12Session = input.string("早午盘 09:30-14:00", "跟单时段 (ET)",
     options=["早午盘 09:30-14:00", "全时段 09:30-16:00", "24小时"], group=G_F12,
     tooltip="账本：早午盘期望最好，尾盘 14:00-16:00 全场最差（-0.35R/单）。")
int f12CooldownMin = input.int(30, "全额止损后同向冷却（分钟）", minval=0, maxval=240, group=G_F12,
     tooltip="治『卖A卖A卖A一路涨』：同方向刚被打止损，冷却期内不再跟同向新信号。")
bool f12TakeCountertrend = input.bool(true, "跟随逆势拒绝", group=G_F12,
     tooltip="账本：逆势关键位拒绝质量与顺势相当（-0.031 vs -0.049）。关闭则只跟顺势。")
float f12CostPts = input.float(0.5, "成本假设（点/往返，记分板净值用）",
     minval=0.0, maxval=5.0, step=0.1, group=G_F12,
     tooltip="只影响记分板的『费后』净值，不影响任何交易规则。0.5 点≈US500 CFD 常态点差。")
bool f12SignalAlertsToo = input.bool(true, "同步推送图上信号（买A/卖A/逆多逆空）", group=G_F12,
     tooltip="开：图上出现的主信号同时推送到手机，内容含等级/类型/入场/止损/T1/T2 全套价格" +
         "（受 06 组过滤：默认不推启动类、只在 RTH 推）。关：手机只收【v12跟单】与 Saty 二拒。")
bool f12EnginePushes = input.bool(false, "保留旧版计划事件推送", group=G_F12,
     tooltip="默认关：旧引擎的保本移动/结构离场叙事与 v12『止损不动』规则矛盾，避免打架。")

bool hostIsCanonical3m = timeframe.in_seconds(timeframe.period) == 180
bool hostIs10m = timeframe.in_seconds(timeframe.period) == 600
bool hostUsesLowerTfRelay = timeframe.isminutes and
     timeframe.in_seconds(timeframe.period) > 180
bool ordersAllowed = hostIsCanonical3m and barstate.isconfirmed
bool f12HostOk = hostIsCanonical3m or hostIs10m
bool engineEventsVisible = not f12Enable or showEngineEvents

// ─────────────────────────────────────────────────────────────────────────────
// Immutable event views
// ─────────────────────────────────────────────────────────────────────────────
type V11Signal
    int id
    int eventTime
    int side
    int setup
    int grade
    int role
    float entry
    float stop
    float t1
    float t2
    float spaceR
    int reasonMask

type V11Plan
    bool active
    int side
    int status
    int signalId
    int startTime
    float entry
    float stop
    float effectiveStop
    float t1
    float t2
    bool countertrend
    bool t1Reached
    bool t2Reached
    int eventId
    int eventTime
    int eventType
    float eventPrice

type V11Snapshot
    int canonicalTime
    float canonicalOpen
    float canonicalHigh
    float canonicalLow
    float canonicalClose
    float canonicalAtr
    float phase
    bool compression
    float ema5
    float ema12
    float ema34
    float ema50
    int contextTime
    float contextClose
    float contextEma5
    float contextEma12
    float contextEma34
    float contextEma50
    int contextDirection
    int contextPace
    float support
    float resistance
    float nextLongTrigger
    float nextShortTrigger
    int longBlocker
    int shortBlocker
    V11Signal signal
    V11Plan plan

f_empty_signal() =>
    V11Signal.new(0, na, SIDE_FLAT, SETUP_NONE, GRADE_NONE, ROLE_INITIAL,
         na, na, na, na, na, 0)

f_empty_plan() =>
    V11Plan.new(false, SIDE_FLAT, PLAN_FLAT, 0, na,
         na, na, na, na, na, false, false, false,
         0, na, EVENT_NONE, na)

f_empty_snapshot() =>
    V11Snapshot.new(na, na, na, na, na, na, na, false,
         na, na, na, na, na, na, na, na, na, na,
         SIDE_FLAT, SIDE_FLAT, na, na, na, na,
         BLOCK_TRIGGER, BLOCK_TRIGGER, f_empty_signal(), f_empty_plan())

// ─────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ─────────────────────────────────────────────────────────────────────────────
f_pick_support(float reference, float current, float candidate, float tolerance) =>
    bool eligible = not na(candidate) and candidate <= reference + tolerance
    eligible and (na(current) or candidate > current) ? candidate : current

f_pick_resistance(float reference, float current, float candidate, float tolerance) =>
    bool eligible = not na(candidate) and candidate >= reference - tolerance
    eligible and (na(current) or candidate < current) ? candidate : current

f_pick_above(float reference, float current, float candidate, float tolerance) =>
    bool eligible = not na(candidate) and candidate > reference + tolerance
    eligible and (na(current) or candidate < current) ? candidate : current

f_pick_below(float reference, float current, float candidate, float tolerance) =>
    bool eligible = not na(candidate) and candidate < reference - tolerance
    eligible and (na(current) or candidate > current) ? candidate : current

f_candidate_space(int side, float entry, float stop, float obstacle) =>
    float risk = (entry - stop) * side
    float obstacleDistance = na(obstacle) ? risk : (obstacle - entry) * side
    float targetDistance = math.min(risk, math.max(0.0, obstacleDistance))
    risk > syminfo.mintick ? targetDistance / risk : 0.0

f_candidate_ready(bool proof, bool routeAllowed, float risk,
     float spaceR, float atrValue) =>
    proof and routeAllowed and risk > syminfo.mintick and
         risk <= maxRiskAtr * atrValue and spaceR >= minimumSpaceR

f_candidate_blocker(bool proof, bool routeAllowed, float risk,
     float spaceR, float atrValue) =>
    not proof ? BLOCK_TRIGGER :
     not routeAllowed ? BLOCK_COUNTERTREND :
     (risk <= syminfo.mintick or risk > maxRiskAtr * atrValue) ? BLOCK_RISK :
     spaceR < minimumSpaceR ? BLOCK_SPACE : BLOCK_READY

f_nearest_saty(float anchor, float dailyAtr, float reference) =>
    var array<float> ratios = array.from(-3.0, -2.618, -2.0, -1.618,
         -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236,
         0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272,
         1.618, 2.0, 2.618, 3.0)
    float below = na
    float above = na
    if not na(anchor) and not na(dailyAtr) and dailyAtr > 0
        for i = 0 to array.size(ratios) - 1
            float level = anchor + dailyAtr * array.get(ratios, i)
            below := level <= reference and (na(below) or level > below) ? level : below
            above := level >= reference and (na(above) or level < above) ? level : above
    [below, above]

f_setup_priority(int setup) =>
    setup == SETUP_LEVEL_REJECTION ? 4 :
     setup == SETUP_PULLBACK_CONTINUATION ? 3 :
     setup == SETUP_BREAKOUT ? 2 :
     setup == SETUP_IGNITION ? 1 : 0

f_setup_zh(int setup) =>
    setup == SETUP_LEVEL_REJECTION ? "关键位拒绝" :
     setup == SETUP_PULLBACK_CONTINUATION ? "回踩续涨/续跌" :
     setup == SETUP_BREAKOUT ? "压缩/结构突破" :
     setup == SETUP_IGNITION ? "趋势启动" : "暂无触发"

f_grade_zh(int grade) =>
    grade == GRADE_A ? "A" : grade == GRADE_B ? "B" :
     grade == GRADE_C ? "C" : "—"

f_grade_color(int grade) =>
    grade == GRADE_A ? color.rgb(0, 184, 148) :
     grade == GRADE_B ? color.rgb(20, 140, 210) :
     grade == GRADE_C ? COL_CT : color.gray

f_context_zh(int direction, int pace) =>
    direction == SIDE_LONG ?
         (pace == SIDE_LONG ? "10m 多头同向" : "10m 多头·节奏回踩") :
     direction == SIDE_SHORT ?
         (pace == SIDE_SHORT ? "10m 空头同向" : "10m 空头·节奏反抽") :
     pace == SIDE_LONG ? "10m 中性·节奏向上" :
     pace == SIDE_SHORT ? "10m 中性·节奏向下" : "10m 中性"

f_plan_status_zh(V11Plan plan) =>
    not plan.active ? "空仓" :
     plan.countertrend ?
          (plan.side == SIDE_LONG ? "逆势短打多仓" : "逆势短打空仓") :
     plan.t2Reached ?
          (plan.side == SIDE_LONG ? "持有多头 runner｜Stop=T1" :
               "持有空头 runner｜Stop=T1") :
     plan.status == PLAN_PROTECT ?
          (plan.t1Reached ?
               (plan.side == SIDE_LONG ? "保护多仓｜T1后止损=入场" :
                    "保护空仓｜T1后止损=入场") :
               (plan.side == SIDE_LONG ? "多仓风险警戒｜止损未上移" :
                    "空仓风险警戒｜止损未上移")) :
     plan.side == SIDE_LONG ? "持有多仓" : "持有空仓"

f_blocker_zh(int blocker, int side, float trigger) =>
    string directionWord = side == SIDE_LONG ? "多" : "空"
    blocker == BLOCK_CONTEXT ? "10m 反向，只接受关键位反转" :
     blocker == BLOCK_RISK ? "止损距离超过 1.30 ATR" :
     blocker == BLOCK_SPACE ? "前方真实空间小于 0.55R" :
     blocker == BLOCK_COUNTERTREND ? "逆势缺少关键位拒绝" :
     blocker == BLOCK_READY ? directionWord + "方条件已完成" :
     directionWord + "方尚缺确认，看" +
          (side == SIDE_LONG ? "上破参考位" : "下破参考位")

f_event_zh(int eventType, int side) =>
    eventType == EVENT_T1 ? "目标 T1 到达，开始保护" :
     eventType == EVENT_T2 ? "目标 T2 到达；趋势仍同向时保留保护 runner" :
     eventType == EVENT_STOP ? "失效位触及，计划止损" :
     eventType == EVENT_PROTECT ?
          (side == SIDE_LONG ? "多头节奏转弱：仅风险警戒，止损未上移" :
               "空头节奏转弱：仅风险警戒，止损未上移") :
     eventType == EVENT_STRUCTURE_EXIT ? "结构破坏，退出计划" :
     eventType == EVENT_REVERSE ? "反向信号确认，原计划结束" : ""

f_event_glyph(int eventType) =>
    eventType == EVENT_T1 ? "T1" :
     eventType == EVENT_T2 ? "T2" :
     eventType == EVENT_STOP ? "止" :
     eventType == EVENT_PROTECT ? "护" :
     eventType == EVENT_REVERSE ? "反" :
     eventType == EVENT_STRUCTURE_EXIT ? "退" : "·"

f_event_color(int eventType) =>
    eventType == EVENT_T1 ? color.aqua :
     eventType == EVENT_T2 ? color.blue :
     eventType == EVENT_STOP ? color.red :
     eventType == EVENT_PROTECT ? color.orange :
     eventType == EVENT_REVERSE ? color.purple : color.gray

f_signal_message(V11Signal signal, int contextDirection, int contextPace) =>
    bool countertrend = signal.reasonMask >= 128
    string action = countertrend ?
         (signal.side == SIDE_LONG ? "出现逆势短打做多参考" :
          "出现逆势短打做空参考") : signal.side == SIDE_LONG ?
         (signal.role == ROLE_ADD ? "已有多仓：新增做多参考，不改原计划" :
          signal.role == ROLE_REVERSE ? "空仓结束：反手做多" : "出现做多信号") :
         (signal.role == ROLE_ADD ? "已有空仓：新增做空参考，不改原计划" :
          signal.role == ROLE_REVERSE ? "多仓结束：反手做空" : "出现做空信号")
    "IDM v12｜" + action + " " + f_grade_zh(signal.grade) +
         "｜" + f_setup_zh(signal.setup) +
         "｜价格 " + str.tostring(signal.entry, format.mintick) +
         "｜止损 " + str.tostring(signal.stop, format.mintick) +
         "｜目标1 " + str.tostring(signal.t1, format.mintick) +
         "｜目标2 " + str.tostring(signal.t2, format.mintick) +
         "｜" + f_context_zh(contextDirection, contextPace) +
         "。A/B/C 是规则完整度，不是历史胜率。"

// ─────────────────────────────────────────────────────────────────────────────
// The one canonical 3-minute engine
// ─────────────────────────────────────────────────────────────────────────────
// `processConfirmedClose` is supplied by the caller because TradingView states
// that `barstate.isconfirmed` is not reliable inside request.*() expressions.
// The canonical 3m host passes barstate.isconfirmed; requested 3m contexts use
// their scheduled close time so an open realtime intrabar cannot create a
// SignalEvent that later disappears after reload.
f_v11_engine(bool processConfirmedClose) =>
    // Every fact below is computed on the canonical 3-minute tape.
    float ema5Series = ta.ema(hl2, paceFastLen)
    float ema12Series = ta.ema(hl2, paceSlowLen)
    float ema34Series = ta.ema(hl2, anchorFastLen)
    float ema50Series = ta.ema(hl2, anchorSlowLen)
    float atrSeries = ta.atr(atrLen)
    float safeAtr = math.max(atrSeries, syminfo.mintick)
    float phaseBase = ta.ema(close, 21)
    float phaseRaw = ((close - phaseBase) / (3.0 * safeAtr)) * 100.0
    float phaseSeries = ta.ema(phaseRaw, 3)
    float phaseDeviation = ta.stdev(close, 21)
    bool phaseCompression = phaseDeviation <= 1.10 * atrSeries

    [contextTime, contextClose, contextEma5, contextEma12,
     contextEma34, contextEma50] = request.security(
         syminfo.tickerid, TF_CONTEXT,
         [time_close[1], close[1], ta.ema(hl2, paceFastLen)[1],
          ta.ema(hl2, paceSlowLen)[1], ta.ema(hl2, anchorFastLen)[1],
          ta.ema(hl2, anchorSlowLen)[1]],
         gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)
    [dailyAnchor, dailyAtr, priorDayHigh, priorDayLow] = request.security(
         syminfo.tickerid, "D",
         [close[1], ta.atr(atrLen)[1], high[1], low[1]],
         gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)

    int contextDirection = contextEma34 > contextEma50 ? SIDE_LONG :
         contextEma34 < contextEma50 ? SIDE_SHORT : SIDE_FLAT
    int contextPace = contextEma5 > contextEma12 ? SIDE_LONG :
         contextEma5 < contextEma12 ? SIDE_SHORT : SIDE_FLAT
    int paceDirection = ema5Series > ema12Series ? SIDE_LONG :
         ema5Series < ema12Series ? SIDE_SHORT : SIDE_FLAT

    float fastLower = math.min(ema5Series, ema12Series)
    float fastUpper = math.max(ema5Series, ema12Series)
    float anchorLower = math.min(ema34Series, ema50Series)
    float anchorUpper = math.max(ema34Series, ema50Series)
    float contextAnchorLower = math.min(contextEma34, contextEma50)
    float contextAnchorUpper = math.max(contextEma34, contextEma50)
    float tolerance = touchAtr * atrSeries
    float triggerBuffer = math.max(2.0 * syminfo.mintick, triggerAtr * atrSeries)

    float pivotLowValue = ta.pivotlow(low, pivotLen, pivotLen)
    float pivotHighValue = ta.pivothigh(high, pivotLen, pivotLen)
    float knownPivotLow = ta.valuewhen(not na(pivotLowValue), pivotLowValue, 0)
    float knownPivotHigh = ta.valuewhen(not na(pivotHighValue), pivotHighValue, 0)
    [satyBelow, satyAbove] = f_nearest_saty(dailyAnchor, dailyAtr, close)

    float support = na
    support := f_pick_support(close, support, satyBelow, tolerance)
    support := f_pick_support(close, support, knownPivotLow, tolerance)
    support := f_pick_support(close, support, priorDayLow, tolerance)
    support := f_pick_support(close, support, fastLower, tolerance)
    support := f_pick_support(close, support, anchorLower, tolerance)
    support := f_pick_support(close, support, contextAnchorLower, tolerance)
    float resistance = na
    resistance := f_pick_resistance(close, resistance, satyAbove, tolerance)
    resistance := f_pick_resistance(close, resistance, knownPivotHigh, tolerance)
    resistance := f_pick_resistance(close, resistance, priorDayHigh, tolerance)
    resistance := f_pick_resistance(close, resistance, fastUpper, tolerance)
    resistance := f_pick_resistance(close, resistance, anchorUpper, tolerance)
    resistance := f_pick_resistance(close, resistance, contextAnchorUpper, tolerance)

    float priorStructureHigh = ta.highest(high[1], structureLookback)
    float priorStructureLow = ta.lowest(low[1], structureLookback)
    float priorBoxHigh = ta.highest(high[1], compressionLookback)
    float priorBoxLow = ta.lowest(low[1], compressionLookback)
    float priorBoxRange = priorBoxHigh - priorBoxLow
    float candleRange = math.max(high - low, syminfo.mintick)
    float candleBody = math.abs(close - open)
    float lowerWick = math.min(open, close) - low
    float upperWick = high - math.max(open, close)
    bool strongBull = close > open and candleBody / candleRange >= strongBodyRatio and
         close >= high - 0.32 * candleRange
    bool strongBear = close < open and candleBody / candleRange >= strongBodyRatio and
         close <= low + 0.32 * candleRange
    bool bullPhase = phaseSeries > phaseSeries[1] or phaseSeries >= -23.6
    bool bearPhase = phaseSeries < phaseSeries[1] or phaseSeries <= 23.6

    // 1. Trend Ignition: the direction changes and price proves it immediately.
    bool ignitionLong = ((ta.crossover(ema5Series, ema12Series) and
         close > anchorUpper) or
         (close[1] <= anchorUpper[1] and close > anchorUpper)) and
         close > priorStructureHigh + triggerBuffer and strongBull
    bool ignitionShort = ((ta.crossunder(ema5Series, ema12Series) and
         close < anchorLower) or
         (close[1] >= anchorLower[1] and close < anchorLower)) and
         close < priorStructureLow - triggerBuffer and strongBear

    // 2. Pullback Continuation: current rejection can confirm on the same bar;
    // a plain test confirms when the next bar breaks the test candle.
    bool fastTouchLong = low <= fastUpper + tolerance and close > fastUpper
    bool anchorTouchLong = low <= anchorUpper + tolerance and close > anchorUpper
    bool contextTouchLong = low <= contextAnchorUpper + tolerance and
         close > contextAnchorUpper
    bool levelTouchLong = not na(support) and low <= support + tolerance and
         close > support
    bool touchLongNow = fastTouchLong or anchorTouchLong or
         contextTouchLong or levelTouchLong
    bool priorTestLong = low[1] <= fastUpper[1] + tolerance[1] or
         low[1] <= anchorUpper[1] + tolerance[1] or
         low[1] <= contextAnchorUpper[1] + tolerance[1] or
         (not na(support[1]) and low[1] <= support[1] + tolerance[1])
    bool establishedLongBefore = close[2] > fastUpper[2] + tolerance[2] or
         close[3] > fastUpper[3] + tolerance[3] or
         close[4] > fastUpper[4] + tolerance[4]
    bool sameBarPullbackLong = touchLongNow and strongBull and
         lowerWick >= 0.24 * candleRange
    bool nextBarPullbackLong = priorTestLong and establishedLongBefore and
         close > high[1] + triggerBuffer and strongBull
    bool pullbackLong = paceDirection == SIDE_LONG and
         (contextDirection != SIDE_SHORT or contextPace == SIDE_LONG) and
         (sameBarPullbackLong or nextBarPullbackLong)

    bool fastTouchShort = high >= fastLower - tolerance and close < fastLower
    bool anchorTouchShort = high >= anchorLower - tolerance and close < anchorLower
    bool contextTouchShort = high >= contextAnchorLower - tolerance and
         close < contextAnchorLower
    bool levelTouchShort = not na(resistance) and high >= resistance - tolerance and
         close < resistance
    bool touchShortNow = fastTouchShort or anchorTouchShort or
         contextTouchShort or levelTouchShort
    bool priorTestShort = high[1] >= fastLower[1] - tolerance[1] or
         high[1] >= anchorLower[1] - tolerance[1] or
         high[1] >= contextAnchorLower[1] - tolerance[1] or
         (not na(resistance[1]) and high[1] >= resistance[1] - tolerance[1])
    bool establishedShortBefore = close[2] < fastLower[2] - tolerance[2] or
         close[3] < fastLower[3] - tolerance[3] or
         close[4] < fastLower[4] - tolerance[4]
    bool sameBarPullbackShort = touchShortNow and strongBear and
         upperWick >= 0.24 * candleRange
    bool nextBarPullbackShort = priorTestShort and establishedShortBefore and
         close < low[1] - triggerBuffer and strongBear
    bool pullbackShort = paceDirection == SIDE_SHORT and
         (contextDirection != SIDE_LONG or contextPace == SIDE_SHORT) and
         (sameBarPullbackShort or nextBarPullbackShort)

    // 3. Compression / Structure Breakout.
    bool compactBox = priorBoxRange <= compressionAtr * atrSeries or phaseCompression
    bool breakoutLong = compactBox and
         close > priorStructureHigh + triggerBuffer and
         strongBull and paceDirection == SIDE_LONG
    bool breakoutShort = compactBox and
         close < priorStructureLow - triggerBuffer and
         strongBear and paceDirection == SIDE_SHORT

    // 4. Level Rejection.  This is the only normal countertrend route.
    bool sweptSupport = not na(support) and low <= support + tolerance and
         close > support + triggerBuffer
    bool sweptResistance = not na(resistance) and high >= resistance - tolerance and
         close < resistance - triggerBuffer
    bool repeatedSupport = sweptSupport[1] and low >= low[1] - tolerance and
         close > high[1] + triggerBuffer
    bool repeatedResistance = sweptResistance[1] and high <= high[1] + tolerance and
         close < low[1] - triggerBuffer
    bool rejectionLong = (sweptSupport and lowerWick >= 0.38 * candleRange and
         close > open) or (repeatedSupport and strongBull)
    bool rejectionShort = (sweptResistance and upperWick >= 0.38 * candleRange and
         close < open) or (repeatedResistance and strongBear)

    // Direct proofs are evaluated every bar.  De-duplication happens only
    // after risk/space validation, so a setup that was initially too wide can
    // still fire on a later bar when it becomes executable.
    bool proofRejectionLong = rejectionLong
    bool proofRejectionShort = rejectionShort
    bool proofPullbackLong = pullbackLong
    bool proofPullbackShort = pullbackShort
    bool proofBreakoutLong = breakoutLong
    bool proofBreakoutShort = breakoutShort
    bool proofIgnitionLong = ignitionLong
    bool proofIgnitionShort = ignitionShort

    // Every setup owns its own invalidation and is validated independently.
    // A blocked higher-priority Pullback must not hide a valid Breakout on the
    // same bar (the exact failure that caused the 10:27 morning drought).
    float longEntry = close
    float longObstacle = na
    longObstacle := f_pick_above(longEntry, longObstacle, satyAbove, tolerance)
    longObstacle := f_pick_above(longEntry, longObstacle, knownPivotHigh, tolerance)
    longObstacle := f_pick_above(longEntry, longObstacle, priorDayHigh, tolerance)
    longObstacle := f_pick_above(longEntry, longObstacle, fastUpper, tolerance)
    longObstacle := f_pick_above(longEntry, longObstacle, anchorUpper, tolerance)
    longObstacle := f_pick_above(longEntry, longObstacle, contextAnchorUpper, tolerance)
    float shortEntry = close
    float shortObstacle = na
    shortObstacle := f_pick_below(shortEntry, shortObstacle, satyBelow, tolerance)
    shortObstacle := f_pick_below(shortEntry, shortObstacle, knownPivotLow, tolerance)
    shortObstacle := f_pick_below(shortEntry, shortObstacle, priorDayLow, tolerance)
    shortObstacle := f_pick_below(shortEntry, shortObstacle, fastLower, tolerance)
    shortObstacle := f_pick_below(shortEntry, shortObstacle, anchorLower, tolerance)
    shortObstacle := f_pick_below(shortEntry, shortObstacle, contextAnchorLower, tolerance)

    float buffer = stopBufferAtr * atrSeries
    float longRejectionStop =
         (repeatedSupport ? math.min(low, low[1]) : low) - buffer
    float longPullbackStop =
         (nextBarPullbackLong ? math.max(low[1], low) : low) - buffer
    float longBreakoutStop = math.max(low, priorStructureHigh) - buffer
    float longIgnitionStop = math.max(low, anchorUpper) - buffer
    float shortRejectionStop =
         (repeatedResistance ? math.max(high, high[1]) : high) + buffer
    float shortPullbackStop =
         (nextBarPullbackShort ? math.min(high[1], high) : high) + buffer
    float shortBreakoutStop = math.min(high, priorStructureLow) + buffer
    float shortIgnitionStop = math.min(high, anchorLower) + buffer

    float longRejectionRisk = longEntry - longRejectionStop
    float longPullbackRisk = longEntry - longPullbackStop
    float longBreakoutRisk = longEntry - longBreakoutStop
    float longIgnitionRisk = longEntry - longIgnitionStop
    float shortRejectionRisk = shortRejectionStop - shortEntry
    float shortPullbackRisk = shortPullbackStop - shortEntry
    float shortBreakoutRisk = shortBreakoutStop - shortEntry
    float shortIgnitionRisk = shortIgnitionStop - shortEntry

    float longRejectionSpace = f_candidate_space(
         SIDE_LONG, longEntry, longRejectionStop, longObstacle)
    float longPullbackSpace = f_candidate_space(
         SIDE_LONG, longEntry, longPullbackStop, longObstacle)
    float longBreakoutSpace = f_candidate_space(
         SIDE_LONG, longEntry, longBreakoutStop, longObstacle)
    float longIgnitionSpace = f_candidate_space(
         SIDE_LONG, longEntry, longIgnitionStop, longObstacle)
    float shortRejectionSpace = f_candidate_space(
         SIDE_SHORT, shortEntry, shortRejectionStop, shortObstacle)
    float shortPullbackSpace = f_candidate_space(
         SIDE_SHORT, shortEntry, shortPullbackStop, shortObstacle)
    float shortBreakoutSpace = f_candidate_space(
         SIDE_SHORT, shortEntry, shortBreakoutStop, shortObstacle)
    float shortIgnitionSpace = f_candidate_space(
         SIDE_SHORT, shortEntry, shortIgnitionStop, shortObstacle)

    bool longTrendRoute = contextDirection != SIDE_SHORT
    bool shortTrendRoute = contextDirection != SIDE_LONG
    bool longIgnitionRoute = longTrendRoute or close > anchorUpper
    bool shortIgnitionRoute = shortTrendRoute or close < anchorLower
    bool longRejectionReady = f_candidate_ready(proofRejectionLong, true,
         longRejectionRisk, longRejectionSpace, atrSeries)
    bool longPullbackReady = f_candidate_ready(proofPullbackLong, longTrendRoute,
         longPullbackRisk, longPullbackSpace, atrSeries)
    bool longBreakoutReady = f_candidate_ready(proofBreakoutLong, longTrendRoute,
         longBreakoutRisk, longBreakoutSpace, atrSeries)
    bool longIgnitionReady = f_candidate_ready(proofIgnitionLong,
         longIgnitionRoute, longIgnitionRisk, longIgnitionSpace, atrSeries)
    bool shortRejectionReady = f_candidate_ready(proofRejectionShort, true,
         shortRejectionRisk, shortRejectionSpace, atrSeries)
    bool shortPullbackReady = f_candidate_ready(proofPullbackShort, shortTrendRoute,
         shortPullbackRisk, shortPullbackSpace, atrSeries)
    bool shortBreakoutReady = f_candidate_ready(proofBreakoutShort, shortTrendRoute,
         shortBreakoutRisk, shortBreakoutSpace, atrSeries)
    bool shortIgnitionReady = f_candidate_ready(proofIgnitionShort,
         shortIgnitionRoute, shortIgnitionRisk, shortIgnitionSpace, atrSeries)

    // Per-setup de-dup edges.  A new Breakout can fire while an older Pullback
    // proof remains true; there is no shared time cooldown.
    bool longRejectionEdge = longRejectionReady and not longRejectionReady[1]
    bool longPullbackEdge = longPullbackReady and not longPullbackReady[1]
    bool longBreakoutEdge = longBreakoutReady and not longBreakoutReady[1]
    bool longIgnitionEdge = longIgnitionReady and not longIgnitionReady[1]
    bool shortRejectionEdge = shortRejectionReady and not shortRejectionReady[1]
    bool shortPullbackEdge = shortPullbackReady and not shortPullbackReady[1]
    bool shortBreakoutEdge = shortBreakoutReady and not shortBreakoutReady[1]
    bool shortIgnitionEdge = shortIgnitionReady and not shortIgnitionReady[1]

    int longFireSetup = longRejectionEdge ? SETUP_LEVEL_REJECTION :
         longPullbackEdge ? SETUP_PULLBACK_CONTINUATION :
         longBreakoutEdge ? SETUP_BREAKOUT :
         longIgnitionEdge ? SETUP_IGNITION : SETUP_NONE
    int shortFireSetup = shortRejectionEdge ? SETUP_LEVEL_REJECTION :
         shortPullbackEdge ? SETUP_PULLBACK_CONTINUATION :
         shortBreakoutEdge ? SETUP_BREAKOUT :
         shortIgnitionEdge ? SETUP_IGNITION : SETUP_NONE
    int longBestReadySetup = longRejectionReady ? SETUP_LEVEL_REJECTION :
         longPullbackReady ? SETUP_PULLBACK_CONTINUATION :
         longBreakoutReady ? SETUP_BREAKOUT :
         longIgnitionReady ? SETUP_IGNITION : SETUP_NONE
    int shortBestReadySetup = shortRejectionReady ? SETUP_LEVEL_REJECTION :
         shortPullbackReady ? SETUP_PULLBACK_CONTINUATION :
         shortBreakoutReady ? SETUP_BREAKOUT :
         shortIgnitionReady ? SETUP_IGNITION : SETUP_NONE
    int longEvidenceSetup = proofRejectionLong ? SETUP_LEVEL_REJECTION :
         proofPullbackLong ? SETUP_PULLBACK_CONTINUATION :
         proofBreakoutLong ? SETUP_BREAKOUT :
         proofIgnitionLong ? SETUP_IGNITION : SETUP_NONE
    int shortEvidenceSetup = proofRejectionShort ? SETUP_LEVEL_REJECTION :
         proofPullbackShort ? SETUP_PULLBACK_CONTINUATION :
         proofBreakoutShort ? SETUP_BREAKOUT :
         proofIgnitionShort ? SETUP_IGNITION : SETUP_NONE
    int longSetup = longFireSetup != SETUP_NONE ? longFireSetup :
         longBestReadySetup != SETUP_NONE ? longBestReadySetup : longEvidenceSetup
    int shortSetup = shortFireSetup != SETUP_NONE ? shortFireSetup :
         shortBestReadySetup != SETUP_NONE ? shortBestReadySetup : shortEvidenceSetup

    float longStop = longSetup == SETUP_LEVEL_REJECTION ? longRejectionStop :
         longSetup == SETUP_PULLBACK_CONTINUATION ? longPullbackStop :
         longSetup == SETUP_BREAKOUT ? longBreakoutStop : longIgnitionStop
    float shortStop = shortSetup == SETUP_LEVEL_REJECTION ? shortRejectionStop :
         shortSetup == SETUP_PULLBACK_CONTINUATION ? shortPullbackStop :
         shortSetup == SETUP_BREAKOUT ? shortBreakoutStop : shortIgnitionStop
    float longRisk = longEntry - longStop
    float shortRisk = shortStop - shortEntry
    float longSpaceR = f_candidate_space(
         SIDE_LONG, longEntry, longStop, longObstacle)
    float shortSpaceR = f_candidate_space(
         SIDE_SHORT, shortEntry, shortStop, shortObstacle)
    float longT1 = not na(longObstacle) ?
         math.min(longEntry + longRisk, longObstacle) : longEntry + longRisk
    float shortT1 = not na(shortObstacle) ?
         math.max(shortEntry - shortRisk, shortObstacle) : shortEntry - shortRisk
    float longSecondObstacle = na
    longSecondObstacle := f_pick_above(longT1, longSecondObstacle, satyAbove, tolerance)
    longSecondObstacle := f_pick_above(longT1, longSecondObstacle, knownPivotHigh, tolerance)
    longSecondObstacle := f_pick_above(longT1, longSecondObstacle, priorDayHigh, tolerance)
    float longT2 = not na(longSecondObstacle) ?
         math.min(longEntry + 2.0 * longRisk, longSecondObstacle) :
         longEntry + 2.0 * longRisk
    float shortSecondObstacle = na
    shortSecondObstacle := f_pick_below(shortT1, shortSecondObstacle, satyBelow, tolerance)
    shortSecondObstacle := f_pick_below(shortT1, shortSecondObstacle, knownPivotLow, tolerance)
    shortSecondObstacle := f_pick_below(shortT1, shortSecondObstacle, priorDayLow, tolerance)
    float shortT2 = not na(shortSecondObstacle) ?
         math.max(shortEntry - 2.0 * shortRisk, shortSecondObstacle) :
         shortEntry - 2.0 * shortRisk
    bool longSelectedProof = longSetup == SETUP_LEVEL_REJECTION ? proofRejectionLong :
         longSetup == SETUP_PULLBACK_CONTINUATION ? proofPullbackLong :
         longSetup == SETUP_BREAKOUT ? proofBreakoutLong :
         longSetup == SETUP_IGNITION ? proofIgnitionLong : false
    bool shortSelectedProof = shortSetup == SETUP_LEVEL_REJECTION ? proofRejectionShort :
         shortSetup == SETUP_PULLBACK_CONTINUATION ? proofPullbackShort :
         shortSetup == SETUP_BREAKOUT ? proofBreakoutShort :
         shortSetup == SETUP_IGNITION ? proofIgnitionShort : false
    bool longSelectedRoute = longSetup == SETUP_LEVEL_REJECTION ? true :
         longSetup == SETUP_IGNITION ? longIgnitionRoute : longTrendRoute
    bool shortSelectedRoute = shortSetup == SETUP_LEVEL_REJECTION ? true :
         shortSetup == SETUP_IGNITION ? shortIgnitionRoute : shortTrendRoute
    int longBlocker = longBestReadySetup != SETUP_NONE ? BLOCK_READY :
         f_candidate_blocker(longSelectedProof, longSelectedRoute,
              longRisk, longSpaceR, atrSeries)
    int shortBlocker = shortBestReadySetup != SETUP_NONE ? BLOCK_READY :
         f_candidate_blocker(shortSelectedProof, shortSelectedRoute,
              shortRisk, shortSpaceR, atrSeries)

    bool longA = contextDirection == SIDE_LONG and contextPace == SIDE_LONG and
         paceDirection == SIDE_LONG and bullPhase and
         math.abs(close - ema5Series) <= 1.20 * atrSeries and longSpaceR >= 1.0
    bool shortA = contextDirection == SIDE_SHORT and contextPace == SIDE_SHORT and
         paceDirection == SIDE_SHORT and bearPhase and
         math.abs(close - ema5Series) <= 1.20 * atrSeries and shortSpaceR >= 1.0
    int longGrade = longA ? GRADE_A :
         (contextDirection != SIDE_SHORT and longSpaceR >= 0.75 ? GRADE_B : GRADE_C)
    int shortGrade = shortA ? GRADE_A :
         (contextDirection != SIDE_LONG and shortSpaceR >= 0.75 ? GRADE_B : GRADE_C)

    // Same-bar arbitration: setup priority, then grade, then candle direction.
    bool longReadyCandidate = longBestReadySetup != SETUP_NONE
    bool shortReadyCandidate = shortBestReadySetup != SETUP_NONE
    bool longReady = longFireSetup != SETUP_NONE
    bool shortReady = shortFireSetup != SETUP_NONE
    int chosenSide = SIDE_FLAT
    int chosenSetup = SETUP_NONE
    int chosenGrade = GRADE_NONE
    if longReady and not shortReady
        chosenSide := SIDE_LONG
        chosenSetup := longSetup
        chosenGrade := longGrade
    else if shortReady and not longReady
        chosenSide := SIDE_SHORT
        chosenSetup := shortSetup
        chosenGrade := shortGrade
    else if longReady and shortReady
        int longPriority = f_setup_priority(longSetup)
        int shortPriority = f_setup_priority(shortSetup)
        if longPriority > shortPriority or
             (longPriority == shortPriority and longGrade > shortGrade) or
             (longPriority == shortPriority and longGrade == shortGrade and close >= open)
            chosenSide := SIDE_LONG
            chosenSetup := longSetup
            chosenGrade := longGrade
        else
            chosenSide := SIDE_SHORT
            chosenSetup := shortSetup
            chosenGrade := shortGrade

    varip int lastProcessedTime = na
    var V11Signal lastSignal = f_empty_signal()
    var V11Plan plan = f_empty_plan()
    bool processBar = processConfirmedClose and not na(time_close) and
         (na(lastProcessedTime) or time_close != lastProcessedTime)

    if processBar
        // Existing plan lifecycle: Stop-first on ambiguous OHLC bars.
        if plan.active
            bool stopped = plan.side == SIDE_LONG ?
                 low <= plan.effectiveStop : high >= plan.effectiveStop
            bool reachedT2 = not plan.t2Reached and
                 (plan.side == SIDE_LONG ? high >= plan.t2 : low <= plan.t2)
            bool reachedT1 = plan.side == SIDE_LONG ? high >= plan.t1 : low <= plan.t1
            bool paceAgainst = plan.side == SIDE_LONG ?
                 paceDirection == SIDE_SHORT : paceDirection == SIDE_LONG
            bool hardStructureBreak = plan.side == SIDE_LONG ?
                 close < anchorLower - 0.08 * atrSeries and paceAgainst :
                 close > anchorUpper + 0.08 * atrSeries and paceAgainst
            if stopped
                plan.eventId := time_close + EVENT_STOP
                plan.eventTime := time_close
                plan.eventType := EVENT_STOP
                plan.eventPrice := plan.effectiveStop
                plan.active := false
                plan.status := PLAN_EXIT
            else if reachedT2
                bool runnerIntact = contextDirection == plan.side and
                     paceDirection == plan.side
                plan.eventId := time_close + EVENT_T2
                plan.eventTime := time_close
                plan.eventType := EVENT_T2
                plan.eventPrice := plan.t2
                if runnerIntact
                    plan.t1Reached := true
                    plan.t2Reached := true
                    plan.status := PLAN_PROTECT
                    plan.effectiveStop := plan.side == SIDE_LONG ?
                         math.max(plan.effectiveStop, plan.t1) :
                         math.min(plan.effectiveStop, plan.t1)
                else
                    plan.active := false
                    plan.status := PLAN_EXIT
            else if reachedT1 and not plan.t1Reached
                plan.t1Reached := true
                plan.status := PLAN_PROTECT
                plan.effectiveStop := plan.entry
                plan.eventId := time_close + EVENT_T1
                plan.eventTime := time_close
                plan.eventType := EVENT_T1
                plan.eventPrice := plan.t1
            else if hardStructureBreak
                plan.eventId := time_close + EVENT_STRUCTURE_EXIT
                plan.eventTime := time_close
                plan.eventType := EVENT_STRUCTURE_EXIT
                plan.eventPrice := close
                plan.active := false
                plan.status := PLAN_EXIT
            else if paceAgainst and plan.status != PLAN_PROTECT
                plan.status := PLAN_PROTECT
                plan.eventId := time_close + EVENT_PROTECT
                plan.eventTime := time_close
                plan.eventType := EVENT_PROTECT
                plan.eventPrice := close

        if chosenSide != SIDE_FLAT
            bool sameSidePlan = plan.active and plan.side == chosenSide
            bool oppositePlan = plan.active and plan.side == -chosenSide
            bool chosenCountertrend = contextDirection == -chosenSide
            bool countertrendAdvisory = oppositePlan and chosenCountertrend
            int role = countertrendAdvisory ? ROLE_COUNTERTREND_ADVISORY :
                 sameSidePlan ? ROLE_ADD : oppositePlan ? ROLE_REVERSE : ROLE_INITIAL
            if oppositePlan and not countertrendAdvisory
                plan.eventId := time_close + EVENT_REVERSE
                plan.eventTime := time_close
                plan.eventType := EVENT_REVERSE
                plan.eventPrice := close
                plan.active := false
            int reasonMask = (chosenSetup == SETUP_LEVEL_REJECTION ? 1 : 0) +
                 (chosenSetup == SETUP_PULLBACK_CONTINUATION ? 2 : 0) +
                 (chosenSetup == SETUP_BREAKOUT ? 4 : 0) +
                 (chosenSetup == SETUP_IGNITION ? 8 : 0) +
                 (contextDirection == chosenSide ? 16 : 0) +
                 (contextPace == chosenSide ? 32 : 0) +
                 ((chosenSide == SIDE_LONG ? bullPhase : bearPhase) ? 64 : 0) +
                 (contextDirection == -chosenSide ? 128 : 0)
            float signalEntry = chosenSide == SIDE_LONG ? longEntry : shortEntry
            float signalStop = chosenSide == SIDE_LONG ? longStop : shortStop
            float signalT1 = chosenSide == SIDE_LONG ? longT1 : shortT1
            float signalT2 = chosenSide == SIDE_LONG ? longT2 : shortT2
            float signalSpace = chosenSide == SIDE_LONG ? longSpaceR : shortSpaceR
            int signalId = time_close + (chosenSide == SIDE_LONG ? 100 : 200) +
                 chosenSetup * 10 + chosenGrade
            lastSignal := V11Signal.new(signalId, time_close, chosenSide,
                 chosenSetup, chosenGrade, role, signalEntry, signalStop,
                 signalT1, signalT2, signalSpace, reasonMask)
            // An independent same-side signal remains visible as ADD, but it
            // never silently overwrites the original frozen plan.
            if not sameSidePlan and not countertrendAdvisory
                plan := V11Plan.new(true, chosenSide, PLAN_HOLD, signalId,
                     time_close, signalEntry, signalStop, signalStop,
                     signalT1, signalT2, chosenCountertrend, false, false,
                     plan.eventId, plan.eventTime, plan.eventType, plan.eventPrice)
        lastProcessedTime := time_close

    float nextLongTrigger = priorStructureHigh + triggerBuffer
    float nextShortTrigger = priorStructureLow - triggerBuffer
    V11Snapshot.new(time_close, open, high, low, close, atrSeries,
         phaseSeries, phaseCompression,
         ema5Series, ema12Series, ema34Series, ema50Series,
         contextTime, contextClose, contextEma5, contextEma12,
         contextEma34, contextEma50, contextDirection, contextPace,
         support, resistance, nextLongTrigger, nextShortTrigger,
         longBlocker, shortBlocker, lastSignal, plan)

// ─────────────────────────────────────────────────────────────────────────────
// Saty second-rejection advisory (11.1) — informational only.
// State machine per side: IDLE → first confirmed rejection of the nearest
// static daily-ATR level → WATCH(level) → price departs by a configured
// share of the daily ATR → DEPARTED → second confirmed rejection of the SAME
// level → AdvisoryEvent → IDLE.  A confirmed close through the level or a
// daily anchor change resets the machine.  It never calls strategy.*() and
// never touches the engine, SignalEvents or the frozen plan.
// ─────────────────────────────────────────────────────────────────────────────
const int ADV_IDLE = 0
const int ADV_WATCH = 1
const int ADV_DEPARTED = 2

type V11Advisory
    int id
    int eventTime
    int side
    float level
    float ratio
    int ratioIdx
    int firstTime
    int departTime
    int stateLong
    int stateShort

f_empty_advisory() =>
    V11Advisory.new(0, na, SIDE_FLAT, na, na, 0, na, na, ADV_IDLE, ADV_IDLE)

f_saty_ratio_value(int idx) =>
    var array<float> advRatioTable = array.from(-3.0, -2.618, -2.0, -1.618,
         -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236,
         0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272,
         1.618, 2.0, 2.618, 3.0)
    idx >= 0 and idx < array.size(advRatioTable) ?
         array.get(advRatioTable, idx) : na

f_nearest_saty_indexed(float anchor, float dailyAtr, float reference) =>
    var array<float> advRatios = array.from(-3.0, -2.618, -2.0, -1.618,
         -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236,
         0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272,
         1.618, 2.0, 2.618, 3.0)
    float below = na
    int belowIdx = -1
    float above = na
    int aboveIdx = -1
    if not na(anchor) and not na(dailyAtr) and dailyAtr > 0
        for i = 0 to array.size(advRatios) - 1
            float level = anchor + dailyAtr * array.get(advRatios, i)
            if level <= reference and (na(below) or level > below)
                below := level
                belowIdx := i
            if level >= reference and (na(above) or level < above)
                above := level
                aboveIdx := i
    [below, belowIdx, above, aboveIdx]

f_saty_advisory(bool processConfirmedClose, float atrValue) =>
    [advAnchor, advDailyAtr, advPdh, advPdl] = request.security(
         syminfo.tickerid, "D",
         [close[1], ta.atr(atrLen)[1], high[1], low[1]],
         gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)
    float advTolerance = touchAtr * atrValue
    float advTrigger = math.max(2.0 * syminfo.mintick, triggerAtr * atrValue)
    float advCandleRange = math.max(high - low, syminfo.mintick)
    float advLowerWick = math.min(open, close) - low
    float advUpperWick = high - math.max(open, close)
    [nearBelow, nearBelowIdx, nearAbove, nearAboveIdx] =
         f_nearest_saty_indexed(advAnchor, advDailyAtr, close)

    varip int advProcessedTime = na
    var float advAnchorSeen = na
    var int advStateLong = ADV_IDLE
    var float advLevelLong = na
    var float advRatioLong = na
    var int advRatioIdxLong = -1
    var int advFirstLong = na
    var int advDepartLong = na
    var int advStateShort = ADV_IDLE
    var float advLevelShort = na
    var float advRatioShort = na
    var int advRatioIdxShort = -1
    var int advFirstShort = na
    var int advDepartShort = na

    V11Advisory fired = f_empty_advisory()
    bool advProcess = processConfirmedClose and not na(time_close) and
         (na(advProcessedTime) or time_close != advProcessedTime)
    if advProcess
        // A new daily anchor is a new level ladder: reset both machines.
        bool anchorChanged = not na(advAnchor) and
             (na(advAnchorSeen) or advAnchor != advAnchorSeen)
        if anchorChanged
            advStateLong := ADV_IDLE
            advStateShort := ADV_IDLE
            advAnchorSeen := advAnchor

        // Bullish machine: rejections at the nearest level BELOW price.
        if advStateLong == ADV_IDLE
            bool firstRejLong = not na(nearBelow) and
                 low <= nearBelow + advTolerance and
                 close > nearBelow + advTrigger and close > open and
                 advLowerWick >= 0.38 * advCandleRange
            if firstRejLong
                advStateLong := ADV_WATCH
                advLevelLong := nearBelow
                advRatioIdxLong := nearBelowIdx
                advRatioLong := advDailyAtr > 0 ?
                     (nearBelow - advAnchor) / advDailyAtr : na
                advFirstLong := time_close
                advDepartLong := na
        else if close < advLevelLong - advTrigger
            advStateLong := ADV_IDLE
        else if advStateLong == ADV_WATCH
            if high >= advLevelLong + satyDepartureAtr * advDailyAtr
                advStateLong := ADV_DEPARTED
                advDepartLong := time_close
        else if advStateLong == ADV_DEPARTED
            bool secondRejLong = low <= advLevelLong + advTolerance and
                 close > advLevelLong + advTrigger and close > open and
                 advLowerWick >= 0.38 * advCandleRange
            if secondRejLong
                fired := V11Advisory.new(
                     time_close + 300 + advRatioIdxLong, time_close,
                     SIDE_LONG, advLevelLong, advRatioLong, advRatioIdxLong,
                     advFirstLong, advDepartLong, ADV_IDLE, advStateShort)
                advStateLong := ADV_IDLE

        // Bearish machine: rejections at the nearest level ABOVE price.
        if advStateShort == ADV_IDLE
            bool firstRejShort = not na(nearAbove) and
                 high >= nearAbove - advTolerance and
                 close < nearAbove - advTrigger and close < open and
                 advUpperWick >= 0.38 * advCandleRange
            if firstRejShort
                advStateShort := ADV_WATCH
                advLevelShort := nearAbove
                advRatioIdxShort := nearAboveIdx
                advRatioShort := advDailyAtr > 0 ?
                     (nearAbove - advAnchor) / advDailyAtr : na
                advFirstShort := time_close
                advDepartShort := na
        else if close > advLevelShort + advTrigger
            advStateShort := ADV_IDLE
        else if advStateShort == ADV_WATCH
            if low <= advLevelShort - satyDepartureAtr * advDailyAtr
                advStateShort := ADV_DEPARTED
                advDepartShort := time_close
        else if advStateShort == ADV_DEPARTED
            bool secondRejShort = high >= advLevelShort - advTolerance and
                 close < advLevelShort - advTrigger and close < open and
                 advUpperWick >= 0.38 * advCandleRange
            if secondRejShort
                fired := V11Advisory.new(
                     time_close + 350 + advRatioIdxShort, time_close,
                     SIDE_SHORT, advLevelShort, advRatioShort, advRatioIdxShort,
                     advFirstShort, advDepartShort, advStateLong, ADV_IDLE)
                advStateShort := ADV_IDLE
        advProcessedTime := time_close
    fired.stateLong := advStateLong
    fired.stateShort := advStateShort
    fired

f_ratio_zh(float ratio) =>
    na(ratio) ? "?" : (ratio >= 0 ? "+" : "") + str.tostring(ratio, "#.###")

f_advisory_message(V11Advisory adv) =>
    string directionText = adv.side == SIDE_LONG ? "看多" : "看空"
    "IDM｜Saty " + f_ratio_zh(adv.ratio) + " 出现第二次" + directionText +
         "拒绝｜位置 " + str.tostring(adv.level, format.mintick) +
         "｜首测 " + str.format_time(adv.firstTime, "HH:mm", syminfo.timezone) +
         " · 离开 " + str.format_time(adv.departTime, "HH:mm", syminfo.timezone) +
         " · 二拒 " + str.format_time(adv.eventTime, "HH:mm", syminfo.timezone) +
         "。这是位置/风险提醒，不是交易信号，也不改变任何计划。"

f_alert_pass(int sigRole, int sigSetup, int sigMask, int barCloseMs) =>
    bool roleOk = sigRole == ROLE_INITIAL or sigRole == ROLE_REVERSE
    bool ctOk = not alertTrendOnly or sigMask < 128
    bool setupOk = not alertSkipIgnition or sigSetup != SETUP_IGNITION
    int etMinutes = hour(barCloseMs, "America/New_York") * 60 +
         minute(barCloseMs, "America/New_York")
    bool sessionOk = not alertRthOnly or
         (etMinutes > 570 and etMinutes <= 960)
    roleOk and ctOk and setupOk and sessionOk

// ─────────────────────────────────────────────────────────────────────────────
// Dense state + sparse primitive event relay
// ─────────────────────────────────────────────────────────────────────────────
// Dense state answers "what is true now".  Sparse pulses answer "what happened
// on this exact 3m close".  The 10m host reads every available canonical 3m
// intrabar directly.  This keeps the one-ledger contract without the former
// 10m -> 1m -> 3m -> 10m/D nested-request chain, whose tuple-of-arrays history
// could exhaust TradingView runtime memory before the chart rendered.
f_sparse_3m_event_pulse() =>
    V11Snapshot pulse = f_v11_engine(time_close <= timenow)
    V11Advisory advPulse = f_saty_advisory(time_close <= timenow, pulse.canonicalAtr)
    int pulseSignalId = pulse.signal.id
    int pulsePlanId = pulse.plan.eventId
    bool signalIsNew = pulseSignalId > 0 and
         pulseSignalId != nz(pulseSignalId[1], 0)
    bool planEventIsNew = pulsePlanId > 0 and
         pulse.plan.eventType != EVENT_NONE and
         pulsePlanId != nz(pulsePlanId[1], 0)
    [signalIsNew ? pulseSignalId : 0,
     pulse.signal.eventTime, pulse.signal.side, pulse.signal.setup,
     pulse.signal.grade, pulse.signal.role, pulse.signal.entry,
     pulse.signal.stop, pulse.signal.t1, pulse.signal.t2,
     pulse.signal.spaceR, pulse.signal.reasonMask,
     planEventIsNew ? pulsePlanId : 0,
     pulse.plan.eventTime, pulse.plan.eventType, pulse.plan.eventPrice,
     pulse.plan.side,
     advPulse.id, advPulse.level,
     advPulse.side == SIDE_LONG ? 100 + advPulse.ratioIdx :
          advPulse.side == SIDE_SHORT ? 200 + advPulse.ratioIdx : 0]

// The canonical host executes its engine directly.  Only higher hosts request
// that same 3m object; copying a UDT through a same-timeframe request wastes
// memory and was part of the line-less TradingView runtime failure.  A higher
// host can receive `na` before its first mapped 3m object exists, so start from
// a typed empty snapshot and replace it only when the request is defined.
V11Snapshot engine = f_empty_snapshot()
V11Advisory advisory = f_empty_advisory()
if hostIsCanonical3m
    engine := f_v11_engine(barstate.isconfirmed)
    advisory := f_saty_advisory(barstate.isconfirmed, engine.canonicalAtr)
else
    V11Snapshot requestedEngine = request.security(
         syminfo.tickerid, TF_ENGINE,
         f_v11_engine(time_close <= timenow),
         gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off,
         calc_bars_count=ENGINE_CALC_BARS)
    if not na(requestedEngine)
        engine := requestedEngine

array<int> relaySignalIds = array.new<int>()
array<int> relaySignalTimes = array.new<int>()
array<int> relaySignalSides = array.new<int>()
array<int> relaySignalSetups = array.new<int>()
array<int> relaySignalGrades = array.new<int>()
array<int> relaySignalRoles = array.new<int>()
array<float> relaySignalEntries = array.new<float>()
array<float> relaySignalStops = array.new<float>()
array<float> relaySignalT1s = array.new<float>()
array<float> relaySignalT2s = array.new<float>()
array<float> relaySignalSpaces = array.new<float>()
array<int> relaySignalReasons = array.new<int>()
array<int> relayPlanIds = array.new<int>()
array<int> relayPlanTimes = array.new<int>()
array<int> relayPlanTypes = array.new<int>()
array<float> relayPlanPrices = array.new<float>()
array<int> relayPlanSides = array.new<int>()
array<int> relayAdvisoryIds = array.new<int>()
array<float> relayAdvisoryLevels = array.new<float>()
array<int> relayAdvisoryMetas = array.new<int>()
if hostUsesLowerTfRelay
    [signalIds, signalTimes, signalSides, signalSetups, signalGrades,
     signalRoles, signalEntries, signalStops, signalT1s, signalT2s,
     signalSpaces, signalReasons, planIds, planTimes, planTypes,
     planPrices, planSides, advisoryIds, advisoryLevels,
     advisoryMetas] = request.security_lower_tf(
         syminfo.tickerid, TF_ENGINE, f_sparse_3m_event_pulse(),
         ignore_invalid_symbol=true, ignore_invalid_timeframe=true,
         calc_bars_count=RELAY_CALC_BARS)
    relaySignalIds := signalIds
    relaySignalTimes := signalTimes
    relaySignalSides := signalSides
    relaySignalSetups := signalSetups
    relaySignalGrades := signalGrades
    relaySignalRoles := signalRoles
    relaySignalEntries := signalEntries
    relaySignalStops := signalStops
    relaySignalT1s := signalT1s
    relaySignalT2s := signalT2s
    relaySignalSpaces := signalSpaces
    relaySignalReasons := signalReasons
    relayPlanIds := planIds
    relayPlanTimes := planTimes
    relayPlanTypes := planTypes
    relayPlanPrices := planPrices
    relayPlanSides := planSides
    relayAdvisoryIds := advisoryIds
    relayAdvisoryLevels := advisoryLevels
    relayAdvisoryMetas := advisoryMetas

V11Signal displaySignal = engine.signal
int displayPlanEventId = engine.plan.eventId
int displayPlanEventTime = engine.plan.eventTime
int displayPlanEventType = engine.plan.eventType
float displayPlanEventPrice = engine.plan.eventPrice
int displayPlanEventSide = engine.plan.side
int signalId = engine.signal.id
int planEventId = engine.plan.eventId
var int lastCanonicalSignalId = 0
var int lastCanonicalPlanEventId = 0
var int lastRelayedSignalId = 0
var int lastRelayedPlanEventId = 0
// Visual labels on an open 10m bar must be rebuilt after Pine rollback, so the
// two visual cursors above deliberately remain ordinary `var`.  Alerts are
// external side effects and survive rollback; separate `varip` cursors prevent
// the same closed 3m event from notifying again on every 10m realtime tick.
varip int lastRelayedAlertSignalId = 0
varip int lastRelayedAlertPlanEventId = 0
var int lastCanonicalAdvisoryId = 0
var int lastRelayedAdvisoryId = 0
varip int lastRelayedAlertAdvisoryId = 0
var V11Advisory displayAdvisory = f_empty_advisory()
bool newSignal = hostIsCanonical3m and barstate.isconfirmed and
     signalId > lastCanonicalSignalId
bool newPlanEvent = hostIsCanonical3m and barstate.isconfirmed and
     planEventId > lastCanonicalPlanEventId
if newSignal
    lastCanonicalSignalId := signalId
if newPlanEvent
    lastCanonicalPlanEventId := planEventId
int relaySignalCount = 0
int relayPlanCount = 0
int relayRows = array.size(relaySignalIds)
if hostUsesLowerTfRelay and relayRows > 0
    for relayIndex = 0 to relayRows - 1
        int relayedSignalId = array.get(relaySignalIds, relayIndex)
        int relayedPlanId = array.get(relayPlanIds, relayIndex)
        if relayedSignalId > lastRelayedSignalId
            relaySignalCount += 1
            displaySignal := V11Signal.new(relayedSignalId,
                 array.get(relaySignalTimes, relayIndex),
                 array.get(relaySignalSides, relayIndex),
                 array.get(relaySignalSetups, relayIndex),
                 array.get(relaySignalGrades, relayIndex),
                 array.get(relaySignalRoles, relayIndex),
                 array.get(relaySignalEntries, relayIndex),
                 array.get(relaySignalStops, relayIndex),
                 array.get(relaySignalT1s, relayIndex),
                 array.get(relaySignalT2s, relayIndex),
                 array.get(relaySignalSpaces, relayIndex),
                 array.get(relaySignalReasons, relayIndex))
            bool relayCt = displaySignal.reasonMask >= 128
            bool relaySetupOk = displaySignal.setup != SETUP_IGNITION or
                 showIgnitionSignals
            bool relayVisible = relaySetupOk and (relayCt ?
                 (showCountertrendMarkers and displaySignal.role != ROLE_ADD) :
                 displaySignal.role == ROLE_ADD ? showAddMarkers : true)
            if showHistory and relayVisible
                // A 10m pane is a context map, not a second execution chart.
                // Keep every relayed BUY/SELL, but render it as unboxed text so
                // several 3m events inside one 10m candle do not form a wall of
                // overlapping label backgrounds.  The full explanation remains
                // available in the hover tooltip.
                label.new(displaySignal.eventTime, displaySignal.entry,
                     relayCt ? (displaySignal.side == SIDE_LONG ? "逆多" : "逆空") :
                          (displaySignal.side == SIDE_LONG ? "买" : "卖") +
                          f_grade_zh(displaySignal.grade),
                     xloc=xloc.bar_time, yloc=yloc.price,
                     style=label.style_none,
                     color=color.new(relayCt ? COL_CT :
                          f_grade_color(displaySignal.grade), 100),
                     textcolor=relayCt ? COL_CT :
                          f_grade_color(displaySignal.grade), size=size.tiny,
                     tooltip=f_signal_message(displaySignal,
                          engine.contextDirection, engine.contextPace) +
                          "｜10分钟同源事件 #" +
                          str.tostring(displaySignal.id))
            if enableAlerts and (not f12Enable or f12SignalAlertsToo) and
                 relayedSignalId > lastRelayedAlertSignalId and
                 f_alert_pass(displaySignal.role, displaySignal.setup,
                      displaySignal.reasonMask, displaySignal.eventTime)
                alert(f_signal_message(displaySignal,
                     engine.contextDirection, engine.contextPace), alert.freq_all)
                lastRelayedAlertSignalId := relayedSignalId
            lastRelayedSignalId := relayedSignalId
        if relayedPlanId > lastRelayedPlanEventId
            relayPlanCount += 1
            displayPlanEventId := relayedPlanId
            displayPlanEventTime := array.get(relayPlanTimes, relayIndex)
            displayPlanEventType := array.get(relayPlanTypes, relayIndex)
            displayPlanEventPrice := array.get(relayPlanPrices, relayIndex)
            displayPlanEventSide := array.get(relayPlanSides, relayIndex)
            if showHistory and engineEventsVisible
                // Plan events remain available on 10m as tiny colored glyphs.
                // Removing the filled label body preserves the event history
                // without competing visually with the BUY/SELL tape.
                label.new(displayPlanEventTime, displayPlanEventPrice,
                     f_event_glyph(displayPlanEventType),
                     xloc=xloc.bar_time, yloc=yloc.price,
                     style=label.style_none,
                     color=color.new(f_event_color(displayPlanEventType), 100),
                     textcolor=f_event_color(displayPlanEventType), size=size.tiny,
                     tooltip=f_event_zh(displayPlanEventType,
                          displayPlanEventSide) + "｜10分钟同源计划事件 #" +
                          str.tostring(displayPlanEventId))
            if enableAlerts and (not f12Enable or f12EnginePushes) and
                 relayedPlanId > lastRelayedAlertPlanEventId
                alert("IDM v11｜" + f_event_zh(displayPlanEventType,
                     displayPlanEventSide) + "｜价格 " +
                     str.tostring(displayPlanEventPrice, format.mintick) +
                     "｜标的 " + syminfo.ticker + "。", alert.freq_all)
                lastRelayedAlertPlanEventId := relayedPlanId
            lastRelayedPlanEventId := relayedPlanId
        int relayedAdvisoryId = array.get(relayAdvisoryIds, relayIndex)
        if enableSatyAdvisory and relayedAdvisoryId > lastRelayedAdvisoryId
            int advMeta = array.get(relayAdvisoryMetas, relayIndex)
            int advSideRelayed = advMeta >= 200 ? SIDE_SHORT :
                 advMeta >= 100 ? SIDE_LONG : SIDE_FLAT
            int advIdxRelayed = advMeta >= 200 ? advMeta - 200 :
                 advMeta >= 100 ? advMeta - 100 : -1
            int advTimeRelayed = relayedAdvisoryId -
                 (relayedAdvisoryId % 1000)
            displayAdvisory := V11Advisory.new(relayedAdvisoryId,
                 advTimeRelayed, advSideRelayed,
                 array.get(relayAdvisoryLevels, relayIndex),
                 f_saty_ratio_value(advIdxRelayed), advIdxRelayed,
                 na, na, ADV_IDLE, ADV_IDLE)
            if showHistory
                label.new(displayAdvisory.eventTime, displayAdvisory.level,
                     displayAdvisory.side == SIDE_LONG ? "Saty二拒↑" : "Saty二拒↓",
                     xloc=xloc.bar_time, yloc=yloc.price,
                     style=displayAdvisory.side == SIDE_LONG ?
                          label.style_label_up : label.style_label_down,
                     color=color.new(COL_ADV, 100),
                     textcolor=COL_ADV, size=size.small,
                     tooltip="IDM｜Saty " + f_ratio_zh(displayAdvisory.ratio) +
                          " 第二次" +
                          (displayAdvisory.side == SIDE_LONG ? "看多" : "看空") +
                          "拒绝｜位置 " +
                          str.tostring(displayAdvisory.level, format.mintick) +
                          "｜10分钟同源提醒 #" + str.tostring(relayedAdvisoryId))
            if enableAlerts and enableSatyAlerts and
                 relayedAdvisoryId > lastRelayedAlertAdvisoryId
                alert("IDM｜Saty " + f_ratio_zh(displayAdvisory.ratio) +
                     " 出现第二次" +
                     (displayAdvisory.side == SIDE_LONG ? "看多" : "看空") +
                     "拒绝｜位置 " +
                     str.tostring(displayAdvisory.level, format.mintick) +
                     "。这是位置/风险提醒，不是交易信号。", alert.freq_all)
                lastRelayedAlertAdvisoryId := relayedAdvisoryId
            lastRelayedAdvisoryId := relayedAdvisoryId
newSignal := newSignal or relaySignalCount > 0
newPlanEvent := newPlanEvent or relayPlanCount > 0

// ─────────────────────────────────────────────────────────────────────────────
// Natural-language alerts: the phone receives a readable Chinese sentence.
// v11.2 alert filter: display/notification layer only, engine untouched.
// ─────────────────────────────────────────────────────────────────────────────
if enableAlerts and (not f12Enable or f12SignalAlertsToo) and
     hostIsCanonical3m and newSignal and barstate.isconfirmed and
     f_alert_pass(displaySignal.role, displaySignal.setup,
          displaySignal.reasonMask, displaySignal.eventTime)
    alert(f_signal_message(displaySignal, engine.contextDirection,
         engine.contextPace), alert.freq_once_per_bar_close)
if enableAlerts and (not f12Enable or f12EnginePushes) and
     hostIsCanonical3m and newPlanEvent and
     displayPlanEventType != EVENT_NONE and barstate.isconfirmed
    alert("IDM v11｜" + f_event_zh(displayPlanEventType, displayPlanEventSide) +
         "｜价格 " + str.tostring(displayPlanEventPrice, format.mintick) +
         "｜标的 " + syminfo.ticker + "。",
         alert.freq_once_per_bar_close)

// Saty second-rejection advisory on the canonical 3m host: mark and notify.
bool newAdvisory = enableSatyAdvisory and hostIsCanonical3m and
     barstate.isconfirmed and advisory.id > lastCanonicalAdvisoryId
if newAdvisory
    displayAdvisory := advisory
    lastCanonicalAdvisoryId := advisory.id
    if showHistory
        label.new(advisory.eventTime, advisory.level,
             advisory.side == SIDE_LONG ? "Saty二拒↑" : "Saty二拒↓",
             xloc=xloc.bar_time, yloc=yloc.price,
             style=advisory.side == SIDE_LONG ?
                  label.style_label_up : label.style_label_down,
             color=color.new(COL_ADV, 100),
             textcolor=COL_ADV, size=size.small,
             tooltip=f_advisory_message(advisory))
    if enableAlerts and enableSatyAlerts
        alert(f_advisory_message(advisory), alert.freq_once_per_bar_close)

// ─────────────────────────────────────────────────────────────────────────────
// Optional broker emulator.  Orders never run from the 10m read-only host.
// ─────────────────────────────────────────────────────────────────────────────
string orderMessage = newSignal ?
     f_signal_message(displaySignal, engine.contextDirection, engine.contextPace) : ""
var int lastBrokerSignalId = 0
bool dispatchSignalOrder = newSignal and displaySignal.id > 0 and
     displaySignal.id != lastBrokerSignalId and
     // ADD is a visible reference only: the frozen plan and broker size stay
     // unchanged.  Do not rely on pyramiding=0 to silently reject the order.
     displaySignal.role != ROLE_ADD and
     displaySignal.role != ROLE_COUNTERTREND_ADVISORY
if enableOrders and ordersAllowed and dispatchSignalOrder
    bool brokerCountertrend = displaySignal.reasonMask >= 128
    float dispatchedQty = brokerCountertrend ? orderQty * 0.5 : orderQty
    if displaySignal.side == SIDE_LONG
        strategy.entry("V11-L", strategy.long, qty=dispatchedQty,
             alert_message=orderMessage)
    else
        strategy.entry("V11-S", strategy.short, qty=dispatchedQty,
             alert_message=orderMessage)
    lastBrokerSignalId := displaySignal.id

if enableOrders and hostIsCanonical3m and engine.plan.active
    if engine.plan.side == SIDE_LONG
        if not engine.plan.t1Reached
            strategy.exit("V11-L-T1", from_entry="V11-L",
                 stop=engine.plan.stop, limit=engine.plan.t1,
                 qty_percent=50,
                 alert_message="IDM v11｜多仓到达目标1或止损成交。")
        if not engine.plan.t2Reached
            strategy.exit("V11-L-T2", from_entry="V11-L",
                 stop=engine.plan.effectiveStop, limit=engine.plan.t2,
                 qty_percent=25,
                 alert_message="IDM v11｜多仓到达目标2，保留趋势 runner。")
        // Reserve and protect the final 25% from the moment the plan opens.
        // Previously this bracket existed only after T2, so a pre-T2 stop
        // closed 75% at Stop and leaked the runner to the bar-close price.
        strategy.exit("V11-L-RUN", from_entry="V11-L",
             stop=engine.plan.effectiveStop,
             qty_percent=engine.plan.t2Reached ? 100 : 25,
             alert_message="IDM v11｜多仓趋势 runner 保护退出。")
    else
        if not engine.plan.t1Reached
            strategy.exit("V11-S-T1", from_entry="V11-S",
                 stop=engine.plan.stop, limit=engine.plan.t1,
                 qty_percent=50,
                 alert_message="IDM v11｜空仓到达目标1或止损成交。")
        if not engine.plan.t2Reached
            strategy.exit("V11-S-T2", from_entry="V11-S",
                 stop=engine.plan.effectiveStop, limit=engine.plan.t2,
                 qty_percent=25,
                 alert_message="IDM v11｜空仓到达目标2，保留趋势 runner。")
        strategy.exit("V11-S-RUN", from_entry="V11-S",
             stop=engine.plan.effectiveStop,
             qty_percent=engine.plan.t2Reached ? 100 : 25,
             alert_message="IDM v11｜空仓趋势 runner 保护退出。")
else if enableOrders and hostIsCanonical3m and not engine.plan.active and
     strategy.position_size != 0
    strategy.close_all(comment="V11 plan exit",
         alert_message="IDM v11｜交易计划结束，平掉剩余仓位。")

// ─────────────────────────────────────────────────────────────────────────────
// Minimal price-attached chart
// ─────────────────────────────────────────────────────────────────────────────
// Ripster-style cloud stack: bold fills, faint edges.  5/12 = momentum
// cloud, 3m 34/50 = structure cloud, confirmed 10m 34/50 = regime band.
color paceColor = engine.ema5 >= engine.ema12 ?
     COL_BULL : COL_BEAR
// Ripster's original Trend Cloud palette for 34/50: blue bull, light
// orange bear (#2196f3 / #ffb74d) — same family as the 10m regime band so
// "34/50 = blue/orange" reads consistently across timeframes.
color structColor = engine.ema34 >= engine.ema50 ?
     COL_STRUCT_BULL : COL_STRUCT_BEAR
color contextColor = engine.contextEma34 >= engine.contextEma50 ?
     COL_CTX_BULL : COL_CTX_BEAR

pPaceFast = plot(showPaceCloud ? engine.ema5 : na, "3m EMA 5",
     color=color.new(paceColor, 55), linewidth=1)
pPaceSlow = plot(showPaceCloud ? engine.ema12 : na, "3m EMA 12",
     color=color.new(paceColor, 70), linewidth=1)
fill(pPaceFast, pPaceSlow, color=showPaceCloud ? color.new(paceColor, 76) : na,
     title="3m 5/12 动量 Cloud")

pStructFast = plot(showStructureCloud ? engine.ema34 : na, "3m EMA 34",
     color=color.new(structColor, 60), linewidth=1)
pStructSlow = plot(showStructureCloud ? engine.ema50 : na, "3m EMA 50",
     color=color.new(structColor, 72), linewidth=1)
fill(pStructFast, pStructSlow,
     color=showStructureCloud ? color.new(structColor, 82) : na,
     title="3m 34/50 结构 Cloud")

pContextFast = plot(showContextCloud ? engine.contextEma34 : na,
     "Confirmed 10m EMA 34", color=color.new(contextColor, 40), linewidth=2)
pContextSlow = plot(showContextCloud ? engine.contextEma50 : na,
     "Confirmed 10m EMA 50", color=color.new(contextColor, 58), linewidth=2)
fill(pContextFast, pContextSlow,
     color=showContextCloud ? color.new(contextColor, 92) : na,
     title="Confirmed 10m 34/50 Cloud")

// v11.2: the per-bar blended S1/R1 sawtooth and historical plan segments
// live in the Data Window only; the visible location scale is the static
// Saty ladder below, and the current plan is drawn with clean line objects.
plot(engine.support, "S1 最近支撑", color=na, display=display.data_window)
plot(engine.resistance, "R1 最近压力", color=na, display=display.data_window)

float planEntry = showPlan and engine.plan.active ? engine.plan.entry : na
float planInitialStop = showPlan and engine.plan.active ? engine.plan.stop : na
float planStop = showPlan and engine.plan.active ? engine.plan.effectiveStop : na
float planT1 = showPlan and engine.plan.active ? engine.plan.t1 : na
float planT2 = showPlan and engine.plan.active ? engine.plan.t2 : na
plot(planEntry, "计划 Entry", color=na, display=display.data_window)
plot(planInitialStop, "初始 Stop 参考", color=na, display=display.data_window)
plot(planStop, "计划 Stop", color=na, display=display.data_window)
plot(planT1, "计划 T1", color=na, display=display.data_window)
plot(planT2, "计划 T2", color=na, display=display.data_window)

// GC-immunity: on the 10m relay host the per-event relay labels can exceed
// max_labels_count, and Pine deletes oldest-first — which would silently kill
// the once-created var UI singletons.  Recreating them on every render tick
// keeps them the newest objects, out of the collector's reach.
f_fresh_label(label stale, string sizeName, string xlocName) =>
    if not na(stale)
        label.delete(stale)
    label.new(xlocName == "time" ? time : bar_index, close, "",
         xloc=xlocName == "time" ? xloc.bar_time : xloc.bar_index,
         yloc=yloc.price, style=label.style_label_left,
         color=color.new(color.gray, 100),
         textcolor=color.new(color.white, 100),
         size=sizeName == "normal" ? size.normal : size.tiny)

f_fresh_line(line stale, int lineWidth) =>
    if not na(stale)
        line.delete(stale)
    line.new(time, close, time, close, xloc=xloc.bar_time,
         color=color.new(color.gray, 100), width=lineWidth)

// ── Current-plan lines: four clean segments from plan start to now ──
var line planLnEntry = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(COL_ENTRY, 100), width=1)
var line planLnStop = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.red, 100), width=2)
var line planLnT1 = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.aqua, 100), width=2)
var line planLnT2 = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(COL_T2, 100), width=2)
f_plan_line(line ln, bool visible, int startT, int endT, float lv, color c, int transp) =>
    line.set_xy1(ln, visible ? startT : time, visible ? lv : close)
    line.set_xy2(ln, visible ? endT : time, visible ? lv : close)
    line.set_color(ln, color.new(c, visible ? transp : 100))
if barstate.islast
    planLnEntry := f_fresh_line(planLnEntry, 1)
    planLnStop := f_fresh_line(planLnStop, 2)
    planLnT1 := f_fresh_line(planLnT1, 2)
    planLnT2 := f_fresh_line(planLnT2, 2)
    bool planVisible = showPlan and not f12Enable and engine.plan.active and
         not na(engine.plan.startTime)
    int planEndT = time_close + 6 * 60 * 1000
    f_plan_line(planLnEntry, planVisible, engine.plan.startTime, planEndT,
         engine.plan.entry, COL_ENTRY, 20)
    f_plan_line(planLnStop, planVisible, engine.plan.startTime, planEndT,
         engine.plan.effectiveStop, color.red, 10)
    f_plan_line(planLnT1, planVisible, engine.plan.startTime, planEndT,
         engine.plan.t1, color.aqua, 10)
    f_plan_line(planLnT2, planVisible, engine.plan.startTime, planEndT,
         engine.plan.t2, COL_T2, 10)

// ─────────────────────────────────────────────────────────────────────────────
// v12 跟单模块 (follower) — 出场实验室 (research/exit_lab2.py) 定案的执行层
// Rules fixed by the 13-day full-ledger replay: LEVEL_REJECTION plans only,
// one position at a time, stop NEVER tightens (no breakeven), T1 banks 50%,
// T2 banks 25%, the last 25% rides to the daily boundary or the untouched
// stop, and a FULL stop-out (no T1) starts a same-side cooldown.  Reads the
// frozen engine's signals; never touches engine or plan state.
type F12State
    int dir = 0
    float entry = na
    float stop = na
    float t1 = na
    float t2 = na
    float rem = 0.0
    float runR = 0.0
    bool t1done = false
    bool t2done = false
    int openT = 0
    int cdSide = 0
    int cdUntil = 0
    float totR = 0.0
    float totRNet = 0.0
    int trades = 0
    int wins = 0

var F12State f12 = F12State.new()

f_f12_unit_r(F12State s, float px) =>
    float riskAbs = s.dir == 0 or na(s.entry) or na(s.stop) ? na :
         math.abs(s.entry - s.stop)
    na(riskAbs) or riskAbs < syminfo.mintick ? 0.0 :
         (px - s.entry) * s.dir / riskAbs

f_f12_flat(F12State s, float px, bool coolAfter) =>
    float net = s.runR + s.rem * f_f12_unit_r(s, px)
    float riskPts = math.abs(s.entry - s.stop)
    s.totR += net
    s.totRNet += riskPts < syminfo.mintick ? net : net - f12CostPts / riskPts
    s.trades += 1
    if net > 0
        s.wins += 1
    if coolAfter
        s.cdSide := s.dir
        s.cdUntil := time_close + f12CooldownMin * 60 * 1000
    s.dir := 0
    s.rem := 0.0
    s.runR := 0.0
    s.t1done := false
    s.t2done := false
    net

bool f12NewDay = ta.change(time("D")) != 0

// Per-bar event records.  The state machine below stays free of alert() and
// label.new() so its vars remain legal inside request.security_lower_tf
// (CE10057 taints the whole dataflow of a security expression); every side
// effect renders in the effects block after it.
string f12EvCloseWhy = ""
float f12EvClosePx = na
float f12EvCloseNet = na
int f12EvCloseDir = 0
bool f12EvT1 = false
bool f12EvT2 = false
bool f12EvOpen = false
bool f12EvOpenCt = false
int f12EvOpenId = 0

if f12Enable and hostIsCanonical3m and barstate.isconfirmed
    bool f12ExitedNow = false
    if f12.dir != 0 and f12NewDay
        f12EvCloseDir := f12.dir
        f12EvClosePx := close[1]
        f12EvCloseWhy := "日终平仓"
        f12EvCloseNet := f_f12_flat(f12, close[1], false)
        f12ExitedNow := true
    if f12.dir != 0
        bool f12StopHit = f12.dir == 1 ? low <= f12.stop : high >= f12.stop
        if f12StopHit
            bool f12FullLoss = not f12.t1done
            f12EvCloseDir := f12.dir
            f12EvClosePx := f12.stop
            f12EvCloseWhy := f12FullLoss ? "止损离场，同向冷却 " +
                 str.tostring(f12CooldownMin) + " 分钟" : "T1 后回落止损离场"
            f12EvCloseNet := f_f12_flat(f12, f12.stop, f12FullLoss)
            f12ExitedNow := true
        else
            if not f12.t1done and
                 (f12.dir == 1 ? high >= f12.t1 : low <= f12.t1)
                f12.runR += 0.5 * f_f12_unit_r(f12, f12.t1)
                f12.rem -= 0.5
                f12.t1done := true
                f12EvT1 := true
            if f12.t1done and not f12.t2done and
                 (f12.dir == 1 ? high >= f12.t2 : low <= f12.t2)
                f12.runR += 0.25 * f_f12_unit_r(f12, f12.t2)
                f12.rem -= 0.25
                f12.t2done := true
                f12EvT2 := true
    if f12.dir == 0 and not f12ExitedNow and newSignal and
         displaySignal.setup == SETUP_LEVEL_REJECTION and
         engine.plan.active and engine.plan.signalId == displaySignal.id
        bool f12CtSig = displaySignal.reasonMask >= 128
        int f12EtMin = hour(time_close, "America/New_York") * 60 +
             minute(time_close, "America/New_York")
        bool f12SessOk = f12Session == "24小时" or
             (f12EtMin > 570 and
              f12EtMin <= (f12Session == "早午盘 09:30-14:00" ? 840 : 960))
        bool f12CdOk = not (displaySignal.side == f12.cdSide and
             time_close <= f12.cdUntil)
        if (f12TakeCountertrend or not f12CtSig) and f12SessOk and f12CdOk
            f12.dir := displaySignal.side
            f12.entry := displaySignal.entry
            f12.stop := displaySignal.stop
            f12.t1 := displaySignal.t1
            f12.t2 := displaySignal.t2
            f12.rem := 1.0
            f12.runR := 0.0
            f12.t1done := false
            f12.t2done := false
            f12.openT := time
            f12EvOpen := true
            f12EvOpenCt := f12CtSig
            f12EvOpenId := displaySignal.id

// Effects: labels and the push queue.  Reads follower state, never writes it.
string f12AlertQueue = ""
if f12Enable and hostIsCanonical3m and barstate.isconfirmed
    if f12EvCloseWhy != ""
        label.new(time, f12EvClosePx,
             (f12EvCloseDir == 1 ? "平多 " : "平空 ") +
                  (f12EvCloseNet >= 0 ? "+" : "") +
                  str.tostring(f12EvCloseNet, "#.##") + "R",
             xloc=xloc.bar_time,
             style=f12EvCloseDir == 1 ? label.style_label_down :
                  label.style_label_up,
             color=color.new(f12EvCloseNet >= 0 ? COL_WIN :
                  COL_LOSS, 16),
             textcolor=color.white, size=size.small,
             tooltip="v12 跟单｜" + f12EvCloseWhy)
        f12AlertQueue += "【v12跟单】" + f12EvCloseWhy + "｜本笔 " +
             (f12EvCloseNet >= 0 ? "+" : "") +
             str.tostring(f12EvCloseNet, "#.##") + "R｜累计 " +
             (f12.totR >= 0 ? "+" : "") + str.tostring(f12.totR, "#.#") +
             "R（费后 " + (f12.totRNet >= 0 ? "+" : "") +
             str.tostring(f12.totRNet, "#.#") + "R，" +
             str.tostring(f12.wins) + "/" + str.tostring(f12.trades) + " 胜）"
    if f12EvT1
        f12AlertQueue += (f12AlertQueue == "" ? "" : "\n") +
             "【v12跟单】目标1到达，兑现 50%。止损保持 " +
             str.tostring(f12.stop, format.mintick) + " 不动，让剩余仓位呼吸。"
    if f12EvT2
        f12AlertQueue += (f12AlertQueue == "" ? "" : "\n") +
             "【v12跟单】目标2到达，再兑现 25%；剩余 25% 持到日终或原止损。"
    if f12EvOpen
        label.new(time, f12.entry, f12.dir == 1 ? "跟多" : "跟空",
             xloc=xloc.bar_time,
             style=f12.dir == 1 ? label.style_label_up :
                  label.style_label_down,
             color=color.new(f12.dir == 1 ? COL_BULL :
                  COL_BEAR, 8),
             textcolor=color.white, size=size.small,
             tooltip="v12 跟单开仓｜" + (f12EvOpenCt ? "逆势" : "顺势") +
                  "关键位拒绝｜入场 " +
                  str.tostring(f12.entry, format.mintick) + "｜止损 " +
                  str.tostring(f12.stop, format.mintick) + "（不动）")
        f12AlertQueue += (f12AlertQueue == "" ? "" : "\n") +
             "【v12跟单】" + (f12.dir == 1 ? "开多 " : "开空 ") +
             syminfo.ticker + " @ " +
             str.tostring(f12.entry, format.mintick) + "｜止损 " +
             str.tostring(f12.stop, format.mintick) + "（全程不动）｜目标1 " +
             str.tostring(f12.t1, format.mintick) + " 兑现50%｜目标2 " +
             str.tostring(f12.t2, format.mintick) + " 兑现25%｜" +
             (f12EvOpenCt ? "逆势拒绝，快进快出" : "顺势拒绝") + "｜#" +
             str.tostring(f12EvOpenId)
if enableAlerts and f12AlertQueue != ""
    alert(f12AlertQueue, alert.freq_once_per_bar_close)

// ── v12 状态镜像（10m 窗）──
// The follower's single source of truth lives on the 3m canonical host.
// The 10m pane renders the SAME position through a lower-tf STATE relay:
// last completed 3m value inside each 10m bar.  Unlike event pulses, state
// re-reads on every refresh, so a missed realtime update self-heals within
// one 3m bar — the two panes cannot drift apart.
f_f12_state_snapshot() =>
    [f12.dir, f12.entry, f12.stop, f12.t1, f12.t2,
         f12.t1done ? 1 : 0, f12.t2done ? 1 : 0, f12.openT, f12.cdUntil,
         f12.totR, f12.totRNet, f12.trades, f12.wins]

var int m12Dir = 0
var float m12Entry = na
var float m12Stop = na
var float m12T1 = na
var float m12T2 = na
var bool m12T1done = false
var bool m12T2done = false
var int m12OpenT = 0
var int m12CdUntil = 0
var float m12TotR = 0.0
var float m12TotRNet = 0.0
var int m12Trades = 0
var int m12Wins = 0
if f12Enable and hostIs10m
    [mDirs, mEntries, mStops, mT1s, mT2s, mT1ds, mT2ds, mOpenTs,
         mCds, mTotRs, mTotRNets, mTradeNs, mWinNs] = request.security_lower_tf(
         syminfo.tickerid, TF_ENGINE, f_f12_state_snapshot(),
         ignore_invalid_symbol=true, ignore_invalid_timeframe=true,
         calc_bars_count=RELAY_CALC_BARS)
    if array.size(mDirs) > 0
        int prevMDir = m12Dir
        int prevMOpenT = m12OpenT
        float prevMTotR = m12TotR
        int prevMTrades = m12Trades
        m12Dir := array.last(mDirs)
        m12Entry := array.last(mEntries)
        m12Stop := array.last(mStops)
        m12T1 := array.last(mT1s)
        m12T2 := array.last(mT2s)
        m12T1done := array.last(mT1ds) > 0
        m12T2done := array.last(mT2ds) > 0
        m12OpenT := array.last(mOpenTs)
        m12CdUntil := array.last(mCds)
        m12TotR := array.last(mTotRs)
        m12TotRNet := array.last(mTotRNets)
        m12Trades := array.last(mTradeNs)
        m12Wins := array.last(mWinNs)
        if barstate.isconfirmed
            if m12Trades > prevMTrades
                float mirrorNet = m12TotR - prevMTotR
                label.new(time, close,
                     (prevMDir == 1 ? "平多 " : prevMDir == -1 ? "平空 " : "平仓 ") +
                          (mirrorNet >= 0 ? "+" : "") +
                     str.tostring(mirrorNet, "#.##") + "R",
                     xloc=xloc.bar_time, style=label.style_label_down,
                     color=color.new(mirrorNet >= 0 ? COL_WIN :
                          COL_LOSS, 16),
                     textcolor=color.white, size=size.small,
                     tooltip="v12 跟单（10m 镜像）：按 3m 结算，标签位置取 10m 收盘")
            if m12Dir != 0 and (prevMDir == 0 or m12OpenT != prevMOpenT)
                label.new(m12OpenT, m12Entry, m12Dir == 1 ? "跟多" : "跟空",
                     xloc=xloc.bar_time,
                     style=m12Dir == 1 ? label.style_label_up :
                          label.style_label_down,
                     color=color.new(m12Dir == 1 ? COL_BULL :
                          COL_BEAR, 8),
                     textcolor=color.white, size=size.small,
                     tooltip="v12 跟单开仓（10m 镜像，位置取真实 3m 开仓时间）")

// unified display values: 3m reads the follower directly, 10m reads the mirror
int dispF12Dir = hostIsCanonical3m ? f12.dir : m12Dir
float dispF12Entry = hostIsCanonical3m ? f12.entry : m12Entry
float dispF12Stop = hostIsCanonical3m ? f12.stop : m12Stop
float dispF12T1 = hostIsCanonical3m ? f12.t1 : m12T1
float dispF12T2 = hostIsCanonical3m ? f12.t2 : m12T2
bool dispF12T1done = hostIsCanonical3m ? f12.t1done : m12T1done
bool dispF12T2done = hostIsCanonical3m ? f12.t2done : m12T2done
int dispF12OpenT = hostIsCanonical3m ? f12.openT : m12OpenT
int dispF12CdUntil = hostIsCanonical3m ? f12.cdUntil : m12CdUntil
float dispF12TotR = hostIsCanonical3m ? f12.totR : m12TotR
float dispF12TotRNet = hostIsCanonical3m ? f12.totRNet : m12TotRNet
int dispF12Trades = hostIsCanonical3m ? f12.trades : m12Trades

var line f12LnEntry = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.gray, 100), width=1)
var line f12LnStop = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.gray, 100), width=2)
var line f12LnT1 = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.gray, 100), width=2)
var line f12LnT2 = line.new(time, close, time, close, xloc=xloc.bar_time,
     color=color.new(color.gray, 100), width=2)
if barstate.islast
    f12LnEntry := f_fresh_line(f12LnEntry, 1)
    f12LnStop := f_fresh_line(f12LnStop, 2)
    f12LnT1 := f_fresh_line(f12LnT1, 2)
    f12LnT2 := f_fresh_line(f12LnT2, 2)
    bool f12Vis = f12Enable and (hostIsCanonical3m or hostIs10m) and
         dispF12Dir != 0
    int f12EndT = time_close + 6 * 60 * 1000
    f_plan_line(f12LnEntry, f12Vis, dispF12OpenT, f12EndT, dispF12Entry,
         COL_ENTRY, 20)
    f_plan_line(f12LnStop, f12Vis, dispF12OpenT, f12EndT, dispF12Stop,
         color.red, 0)
    f_plan_line(f12LnT1, f12Vis and not dispF12T1done, dispF12OpenT, f12EndT,
         dispF12T1, color.aqua, 10)
    f_plan_line(f12LnT2, f12Vis and not dispF12T2done, dispF12OpenT, f12EndT,
         dispF12T2, COL_T2, 10)

// ── Static Saty daily ladder + PDH/PDL: the visible location scale ──
[ladderAnchor, ladderAtr, ladderPdh, ladderPdl] = request.security(
     syminfo.tickerid, "D",
     [close[1], ta.atr(atrLen)[1], high[1], low[1]],
     gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)
var array<line> ladderLines = array.new<line>()
var array<label> ladderTags = array.new<label>()
var float ladderSeen = na
var array<float> ladderRatios = array.from(-1.0, -0.786, -0.618, -0.5,
     -0.382, -0.236, 0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
if showSatyLadder and barstate.islast and not na(ladderAnchor) and
     not na(ladderAtr) and ladderAtr > 0
    if na(ladderSeen) or ladderSeen != ladderAnchor or
         array.size(ladderLines) == 0
        while array.size(ladderLines) > 0
            line.delete(array.pop(ladderLines))
        while array.size(ladderTags) > 0
            label.delete(array.pop(ladderTags))
        int ladderStart = time_close
        for i = 0 to array.size(ladderRatios) - 1
            float ratio = array.get(ladderRatios, i)
            float lv = ladderAnchor + ladderAtr * ratio
            bool axis = ratio == 0.0
            bool keyRung = axis or math.abs(ratio) == 0.618 or
                 math.abs(ratio) == 1.0
            color lc = ratio > 0 ? COL_BEAR :
                 ratio < 0 ? COL_BULL : color.gray
            array.push(ladderLines, line.new(ladderStart, lv,
                 ladderStart + 1, lv, xloc=xloc.bar_time,
                 extend=extend.both,
                 color=color.new(lc, axis ? 55 : keyRung ? 76 : 88),
                 style=axis ? line.style_solid : line.style_dotted,
                 width=1))
            if keyRung
                array.push(ladderTags, label.new(time_close, lv,
                     (ratio > 0 ? "+" : "") + str.tostring(ratio, "#.###"),
                     xloc=xloc.bar_time, style=label.style_label_left,
                     color=color.new(lc, 100),
                     textcolor=color.new(lc, axis ? 30 : 48), size=size.small))
        array.push(ladderLines, line.new(ladderStart, ladderPdh,
             ladderStart + 1, ladderPdh, xloc=xloc.bar_time,
             extend=extend.both, color=color.new(COL_BEAR, 62),
             style=line.style_dashed, width=1))
        array.push(ladderTags, label.new(time_close, ladderPdh, "昨高",
             xloc=xloc.bar_time, style=label.style_label_left,
             color=color.new(COL_BEAR, 100),
             textcolor=color.new(COL_BEAR, 40), size=size.small))
        array.push(ladderLines, line.new(ladderStart, ladderPdl,
             ladderStart + 1, ladderPdl, xloc=xloc.bar_time,
             extend=extend.both, color=color.new(COL_BULL, 62),
             style=line.style_dashed, width=1))
        array.push(ladderTags, label.new(time_close, ladderPdl, "昨低",
             xloc=xloc.bar_time, style=label.style_label_left,
             color=color.new(COL_BULL, 100),
             textcolor=color.new(COL_BULL, 40), size=size.small))
        ladderSeen := ladderAnchor
    for i = 0 to array.size(ladderTags) - 1
        label.set_x(array.get(ladderTags, i), time_close + 8 * 60 * 1000)
else if not showSatyLadder and array.size(ladderLines) > 0
    while array.size(ladderLines) > 0
        line.delete(array.pop(ladderLines))
    while array.size(ladderTags) > 0
        label.delete(array.pop(ladderTags))

// 11.1 declutter: full-size labels only for trend-side entries/reversals.
// Countertrend probes shrink to 逆多/逆空 tags; ADD is hidden by default.
bool displayedCountertrend = displaySignal.reasonMask >= 128
bool markerSetupOk = displaySignal.setup != SETUP_IGNITION or showIgnitionSignals
bool markerPrimary = (displaySignal.role == ROLE_INITIAL or
     displaySignal.role == ROLE_REVERSE) and not displayedCountertrend and
     markerSetupOk
float longMarkerY = newSignal and markerPrimary and
     displaySignal.side == SIDE_LONG ? displaySignal.entry : na
float shortMarkerY = newSignal and markerPrimary and
     displaySignal.side == SIDE_SHORT ? displaySignal.entry : na
float addMarkerY = newSignal and showAddMarkers and markerSetupOk and
     displaySignal.role == ROLE_ADD ? displaySignal.entry : na
float ctLongMarkerY = newSignal and showCountertrendMarkers and
     displayedCountertrend and displaySignal.role != ROLE_ADD and
     markerSetupOk and displaySignal.side == SIDE_LONG ?
     displaySignal.entry : na
float ctShortMarkerY = newSignal and showCountertrendMarkers and
     displayedCountertrend and displaySignal.role != ROLE_ADD and
     markerSetupOk and displaySignal.side == SIDE_SHORT ?
     displaySignal.entry : na
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_A ? longMarkerY : na,
     title="买A SignalEvent", text="买A", style=shape.labelup,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 8),
     textcolor=color.white, size=size.small)
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_B ? longMarkerY : na,
     title="买B SignalEvent", text="买B", style=shape.labelup,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 8),
     textcolor=color.white, size=size.small)
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_C ? longMarkerY : na,
     title="买C SignalEvent", text="买C", style=shape.labelup,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 22),
     textcolor=color.white, size=size.tiny)
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_A ? shortMarkerY : na,
     title="卖A SignalEvent", text="卖A", style=shape.labeldown,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 8),
     textcolor=color.white, size=size.small)
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_B ? shortMarkerY : na,
     title="卖B SignalEvent", text="卖B", style=shape.labeldown,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 8),
     textcolor=color.white, size=size.small)
plotshape(showHistory and hostIsCanonical3m and
          displaySignal.grade == GRADE_C ? shortMarkerY : na,
     title="卖C SignalEvent", text="卖C", style=shape.labeldown,
     location=location.absolute,
     color=color.new(f_grade_color(displaySignal.grade), 22),
     textcolor=color.white, size=size.tiny)
plotshape(showHistory and hostIsCanonical3m ? addMarkerY : na,
     title="加仓参考", text="加", style=shape.circle,
     location=location.absolute, color=color.new(color.gray, 42),
     textcolor=color.new(color.white, 20), size=size.tiny)
plotshape(showHistory and hostIsCanonical3m ? ctLongMarkerY : na,
     title="逆势短打多", text="逆多", style=shape.labelup,
     location=location.absolute, color=color.new(COL_CT, 78),
     textcolor=color.rgb(200, 162, 219), size=size.tiny)
plotshape(showHistory and hostIsCanonical3m ? ctShortMarkerY : na,
     title="逆势短打空", text="逆空", style=shape.labeldown,
     location=location.absolute, color=color.new(COL_CT, 78),
     textcolor=color.rgb(200, 162, 219), size=size.tiny)

plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_T1 ? displayPlanEventPrice : na,
     title="T1 reached", text="T1", style=shape.circle,
     location=location.absolute, color=color.new(color.aqua, 25),
     textcolor=color.black, size=size.small)
plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_T2 ? displayPlanEventPrice : na,
     title="T2 reached", text="T2", style=shape.diamond,
     location=location.absolute, color=color.new(color.blue, 18),
     textcolor=color.white, size=size.small)
plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_STOP ? displayPlanEventPrice : na,
     title="Stop reached", text="止", style=shape.xcross,
     location=location.absolute, color=color.new(color.red, 10),
     textcolor=color.white, size=size.small)
plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_PROTECT ? displayPlanEventPrice : na,
     title="Risk protect", text="护", style=shape.diamond,
     location=location.absolute, color=color.new(color.orange, 18),
     textcolor=color.white, size=size.small)
plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_REVERSE ? displayPlanEventPrice : na,
     title="Plan reverse", text="反", style=shape.diamond,
     location=location.absolute, color=color.new(color.purple, 12),
     textcolor=color.white, size=size.small)
plotshape(showHistory and engineEventsVisible and hostIsCanonical3m and newPlanEvent and
          displayPlanEventType == EVENT_STRUCTURE_EXIT ?
          displayPlanEventPrice : na,
     title="Structure exit", text="退", style=shape.diamond,
     location=location.absolute, color=color.new(color.gray, 20),
     textcolor=color.white, size=size.small)

// Latest detailed signal is a reusable right-side callout, connected to the
// exact SignalEvent price.  It never sits on top of the source candle.
var bool latestSignalKnown = false
var int latestSignalEventTime = na
var float latestSignalEntry = na
var string latestSignalText = ""
var string latestSignalTip = ""
var color latestSignalColor = color.gray
if newSignal and markerPrimary
    latestSignalKnown := true
    latestSignalEventTime := displaySignal.eventTime
    latestSignalEntry := displaySignal.entry
    string gradeGlyph =
         (displaySignal.side == SIDE_LONG ? ACTION_BUY : ACTION_SELL) +
         f_grade_zh(displaySignal.grade)
    string actionText = displayedCountertrend ?
         gradeGlyph + "｜逆势短打" :
         displaySignal.role == ROLE_ADD ?
              "加仓参考 " + gradeGlyph + "｜不改原计划" :
         displaySignal.role == ROLE_REVERSE ? "反手" + gradeGlyph : gradeGlyph
    latestSignalText := actionText + "｜" + f_setup_zh(displaySignal.setup) +
         "\nE " + str.tostring(displaySignal.entry, format.mintick) +
         " · S " + str.tostring(displaySignal.stop, format.mintick) +
         " · T1 " + str.tostring(displaySignal.t1, format.mintick)
    latestSignalTip := f_signal_message(displaySignal, engine.contextDirection,
         engine.contextPace)
    latestSignalColor := f_grade_color(displaySignal.grade)

var label latestSignalLabel = label.new(time, close, "",
     xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_left,
     color=color.new(color.gray, 100), textcolor=color.new(color.white, 100),
     size=size.normal)
var line latestSignalConnector = line.new(time, close, time, close,
     xloc=xloc.bar_time, extend=extend.none, color=color.new(color.gray, 100),
     width=1)
if barstate.islast
    latestSignalLabel := f_fresh_label(latestSignalLabel, "normal", "time")
    latestSignalConnector := f_fresh_line(latestSignalConnector, 1)
    // The detailed callout belongs to the 3m execution pane.  The 10m pane
    // already shows the same current plan in its four-line status panel, so a
    // second large card merely duplicates information and obscures price.
    bool latestSignalVisible = showLatestLabel and latestSignalKnown and
         not hostIs10m and not (f12Enable and dispF12Dir != 0)
    int latestRightTime = time_close + 12 * 60 * 1000
    label.set_xy(latestSignalLabel, latestRightTime,
         latestSignalVisible ? latestSignalEntry : close)
    label.set_text(latestSignalLabel,
         latestSignalVisible ? latestSignalText : "")
    label.set_color(latestSignalLabel, latestSignalVisible ?
         color.new(latestSignalColor, 12) : color.new(latestSignalColor, 100))
    label.set_textcolor(latestSignalLabel, latestSignalVisible ?
         color.white : color.new(color.white, 100))
    label.set_tooltip(latestSignalLabel,
         latestSignalVisible ? latestSignalTip : "")
    line.set_xy1(latestSignalConnector,
         latestSignalVisible ? latestSignalEventTime : time,
         latestSignalVisible ? latestSignalEntry : close)
    line.set_xy2(latestSignalConnector, latestRightTime,
         latestSignalVisible ? latestSignalEntry : close)
    line.set_color(latestSignalConnector, latestSignalVisible ?
         color.new(latestSignalColor, 42) : color.new(latestSignalColor, 100))

// Latest-only right-edge level captions; three reusable objects, no label flood.
f_update_caption(label caption, bool visible, float value, string textValue,
     color bg, color fg, string tip) =>
    label.set_xy(caption, bar_index + 2, visible ? value : close)
    label.set_text(caption, visible ? textValue : "")
    label.set_color(caption, visible ? bg : color.new(bg, 100))
    label.set_textcolor(caption, visible ? fg : color.new(fg, 100))
    label.set_tooltip(caption, visible ? tip : "")

var label stopCaption = label.new(bar_index, close, "",
     xloc=xloc.bar_index, yloc=yloc.price, style=label.style_label_left,
     color=color.new(color.red, 100), textcolor=color.new(color.white, 100),
     size=size.tiny)
var label t1Caption = label.new(bar_index, close, "",
     xloc=xloc.bar_index, yloc=yloc.price, style=label.style_label_left,
     color=color.new(color.aqua, 100), textcolor=color.new(color.black, 100),
     size=size.tiny)
var label t2Caption = label.new(bar_index, close, "",
     xloc=xloc.bar_index, yloc=yloc.price, style=label.style_label_left,
     color=color.new(color.blue, 100), textcolor=color.new(color.white, 100),
     size=size.tiny)
if barstate.islast
    stopCaption := f_fresh_label(stopCaption, "tiny", "index")
    t1Caption := f_fresh_label(t1Caption, "tiny", "index")
    t2Caption := f_fresh_label(t2Caption, "tiny", "index")
    f_update_caption(stopCaption, showPlan and not f12Enable and engine.plan.active,
         engine.plan.effectiveStop,
         "当前 Stop " +
              str.tostring(engine.plan.effectiveStop, format.mintick),
         color.new(color.red, 10), color.white,
         "当前有效止损；初始 Stop " +
              str.tostring(engine.plan.stop, format.mintick) +
              "。T1 后当前 Stop 可能已经移动到入场价。")
    f_update_caption(t1Caption, showPlan and not f12Enable and engine.plan.active,
         engine.plan.t1, "T1 " + str.tostring(engine.plan.t1, format.mintick),
         color.new(color.aqua, 10), color.black, "冻结的第一目标。")
    f_update_caption(t2Caption, showPlan and not f12Enable and engine.plan.active,
         engine.plan.t2, "T2 " + str.tostring(engine.plan.t2, format.mintick),
         color.new(color.blue, 10), color.white, "冻结的第二目标。")

// Four-row dashboard.  Structure prices are references, never promises that a
// trade will fire there; the primary route always names its current blocker.
string f12NowText = dispF12Dir != 0 ?
     (dispF12Dir == 1 ? "持多单" : "持空单") +
          (dispF12T2done ? "｜已兑75%·余仓到日终" :
           dispF12T1done ? "｜已兑50%·看T2" : "｜看T1") + "｜损不动" :
     time_close <= dispF12CdUntil ? "空仓｜同向冷却，不追新单" :
     "空仓｜等关键位拒绝信号"
string currentText = f12Enable and f12HostOk ? f12NowText :
     engine.plan.active ? f_plan_status_zh(engine.plan) :
     engine.contextDirection == SIDE_LONG ? "寻找回踩做多 / 向上突破" :
     engine.contextDirection == SIDE_SHORT ? "寻找反抽做空 / 向下突破" :
     "等待先破结构，再跟方向"
int primarySide = engine.plan.active ? engine.plan.side :
     engine.contextDirection != SIDE_FLAT ? engine.contextDirection :
     engine.contextPace != SIDE_FLAT ? engine.contextPace :
     close >= engine.ema12 ? SIDE_LONG : SIDE_SHORT
int primaryBlocker = primarySide == SIDE_LONG ?
     engine.longBlocker : engine.shortBlocker
float primaryTrigger = primarySide == SIDE_LONG ?
     engine.nextLongTrigger : engine.nextShortTrigger
string breakoutReferenceText = "上破参考 " +
     str.tostring(engine.nextLongTrigger, format.mintick) +
     "｜下破参考 " + str.tostring(engine.nextShortTrigger, format.mintick)
string nextText = breakoutReferenceText + "\n主" +
     (primarySide == SIDE_LONG ? "多：" : "空：") +
     f_blocker_zh(primaryBlocker, primarySide, primaryTrigger)
// Saty-style stable day readout: anchor and how much of the daily ATR has
// been used.  These change slowly through the session — no per-tick flicker.
[dayHighNow, dayLowNow] = request.security(syminfo.tickerid, "D",
     [high, low], gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)
float dayRangeUsed = not na(ladderAtr) and ladderAtr > 0 and
     not na(dayHighNow) and not na(dayLowNow) ?
     (dayHighNow - dayLowNow) / ladderAtr * 100.0 : na
string levelText = "日锚 " +
     (na(ladderAnchor) ? "—" : str.tostring(ladderAnchor, format.mintick)) +
     "｜已走 " + (na(dayRangeUsed) ? "—" : str.tostring(dayRangeUsed, "#")) +
     "% 日ATR"
string hostText = hostIsCanonical3m ? "3m 执行" : hostIs10m ? "10m 同源只读" : "3m 引擎投影"
string f12SessShort = f12Session == "24小时" ? "24h" :
     f12Session == "早午盘 09:30-14:00" ? "早午盘" : "RTH"
// identical net-R math on both hosts, rebuilt from relayable state only:
// banked = 0.5×T1 (if hit) + 0.25×T2 (if hit); the remainder floats.
float dispF12Risk = math.abs(dispF12Entry - dispF12Stop)
f_f12_disp_r(float px) =>
    dispF12Dir == 0 or na(dispF12Risk) or dispF12Risk < syminfo.mintick ?
         0.0 : (px - dispF12Entry) * dispF12Dir / dispF12Risk
float dispF12Rem = dispF12T2done ? 0.25 : dispF12T1done ? 0.5 : 1.0
float f12NetNow = dispF12Dir != 0 ?
     (dispF12T1done ? 0.5 * f_f12_disp_r(dispF12T1) : 0.0) +
     (dispF12T2done ? 0.25 * f_f12_disp_r(dispF12T2) : 0.0) +
     dispF12Rem * f_f12_disp_r(close) : 0.0
string dashboardPlanText = f12Enable and f12HostOk and dispF12Dir != 0 ?
     (dispF12Dir == 1 ? "跟多 @" : "跟空 @") +
          str.tostring(dispF12Entry, format.mintick) + "｜损 " +
          str.tostring(dispF12Stop, format.mintick) + "(不动)｜已兑 " +
          (dispF12T2done ? "75%" : dispF12T1done ? "50%" : "0%") + "｜净 " +
          (f12NetNow >= 0 ? "+" : "") + str.tostring(f12NetNow, "#.##") + "R" :
     f12Enable and f12HostOk ?
     "跟单待命（拒绝类·" + f12SessShort + "）" +
          (dispF12Trades > 0 ? "｜累计 " + (dispF12TotR >= 0 ? "+" : "") +
               str.tostring(dispF12TotR, "#.#") + "R｜费后 " +
               (dispF12TotRNet >= 0 ? "+" : "") +
               str.tostring(dispF12TotRNet, "#.#") + "R" : "") :
     f12Enable ? "跟单状态请看 3m / 10m 图" :
     engine.plan.active ?
     "E " + str.tostring(engine.plan.entry, format.mintick) +
          "｜当前S " +
               str.tostring(engine.plan.effectiveStop, format.mintick) +
          "｜T1 " + str.tostring(engine.plan.t1, format.mintick) +
          "｜T2 " + str.tostring(engine.plan.t2, format.mintick) : "暂无活动计划"

var table dash = table.new(position.bottom_right, 2, 4,
     border_width=1, border_color=color.new(color.silver, 58),
     frame_width=1, frame_color=color.new(color.silver, 58))
if barstate.islast and showDashboard
    color panel = color.rgb(8, 17, 28)
    color muted = color.rgb(188, 198, 210)
    table.cell(dash, 0, 0, "现在", bgcolor=color.rgb(12, 57, 86),
         text_color=color.white, text_size=size.small)
    table.cell(dash, 1, 0, "IDM v12｜" + hostText + "｜" + currentText,
         bgcolor=color.rgb(12, 57, 86),
         text_color=f12Enable and f12HostOk ?
              (dispF12Dir == 1 ? color.aqua :
               dispF12Dir == -1 ? color.orange : color.white) :
              engine.plan.active ?
              (engine.plan.side == SIDE_LONG ? color.aqua : color.orange) :
              color.white, text_size=size.small)
    table.cell(dash, 0, 1, "背景", bgcolor=panel, text_color=muted,
         text_size=size.small)
    table.cell(dash, 1, 1, f_context_zh(engine.contextDirection,
         engine.contextPace) + "｜" + levelText, bgcolor=panel, text_color=color.white,
         text_size=size.small)
    table.cell(dash, 0, 2, "下一步", bgcolor=panel, text_color=muted,
         text_size=size.small)
    table.cell(dash, 1, 2, nextText, bgcolor=panel,
         text_color=color.yellow, text_size=size.small)
    table.cell(dash, 0, 3, "计划", bgcolor=panel, text_color=muted,
         text_size=size.small)
    table.cell(dash, 1, 3, dashboardPlanText, bgcolor=panel,
         text_color=color.white, text_size=size.small)
else if barstate.islast and not showDashboard
    table.clear(dash, 0, 0, 1, 3)

// Data Window audit fields (machine-readable lifecycle mirrors of the chart).
plot(engine.canonicalTime, "Canonical 3m time", color=na,
     display=display.data_window)
plot(engine.contextTime, "Confirmed 10m source time", color=na,
     display=display.data_window)
plot(engine.contextDirection, "10m context direction state", color=na,
     display=display.data_window)
plot(engine.contextPace, "10m context pace state", color=na,
     display=display.data_window)
plot(newSignal ? displaySignal.id : na, "SignalEvent id", color=na,
     display=display.data_window)
plot(newSignal ? displaySignal.setup : na, "Signal setup code", color=na,
     display=display.data_window)
plot(newSignal ? displaySignal.grade : na, "Signal rule grade", color=na,
     display=display.data_window)
plot(newSignal ? displaySignal.reasonMask : na, "Signal reason mask", color=na,
     display=display.data_window)
plot(engine.plan.active ? engine.plan.entry : na, "Frozen Entry", color=na,
     display=display.data_window)
plot(engine.plan.active ? engine.plan.stop : na, "Frozen initial Stop", color=na,
     display=display.data_window)
plot(engine.plan.active ? engine.plan.effectiveStop : na, "Effective Stop", color=na,
     display=display.data_window)
plot(engine.plan.active ? engine.plan.t1 : na, "Frozen T1", color=na,
     display=display.data_window)
plot(engine.plan.active ? engine.plan.t2 : na, "Frozen T2", color=na,
     display=display.data_window)
plot(newPlanEvent ? displayPlanEventType : na, "Plan event code", color=na,
     display=display.data_window)
int advisoryIdSeries = displayAdvisory.id
bool advisoryPulse = advisoryIdSeries > 0 and
     advisoryIdSeries != nz(advisoryIdSeries[1], 0)
plot(advisoryPulse ? advisoryIdSeries : na, "Saty advisory id", color=na,
     display=display.data_window)
plot(advisoryPulse ? displayAdvisory.level : na,
     "Saty advisory level", color=na, display=display.data_window)
plot(advisoryPulse ? displayAdvisory.side : na,
     "Saty advisory side", color=na, display=display.data_window)
plot(hostIsCanonical3m ? advisory.stateLong : na,
     "Saty watch state long", color=na, display=display.data_window)
plot(hostIsCanonical3m ? advisory.stateShort : na,
     "Saty watch state short", color=na, display=display.data_window)
```

### 6.2 契约测试 research/tests/test_v11_2_clear_contract.py（定义全部"钉死"约束）

```python
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
    assert 'const string VERSION_ID = "12.0.2-follower"' in CLEAR2


def test_frozen_engine_text_is_verbatim() -> None:
    frozen_engine = FROZEN[FROZEN.index(ENGINE_START):FROZEN.index(ENGINE_END)]
    assert frozen_engine in CLEAR2


def test_ledger_driven_defaults() -> None:
    assert 'input.bool(true, "显示逆势短打小标"' in CLEAR2
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
    assert module.count("f12.stop :=") == 1
    assert module.count("s.stop :=") == 0  # flat helper never rewrites the stop
    # follower takes rejections only
    assert "displaySignal.setup == SETUP_LEVEL_REJECTION" in module
    # v12 defaults: enabled, morning+midday, 30-min cooldown, countertrend on
    assert 'input.bool(true, "启用 v12 跟单' in CLEAR2
    assert 'input.string("早午盘 09:30-14:00", "跟单时段' in CLEAR2
    assert 'input.int(30, "全额止损后同向冷却' in CLEAR2
    assert 'input.bool(true, "跟随逆势拒绝"' in CLEAR2
    assert 'input.bool(true, "同步推送图上信号（买A/卖A/逆多逆空）"' in CLEAR2
    assert 'input.bool(false, "保留旧版计划事件推送"' in CLEAR2
    # 12.0.1: cost dual-track is display-only; engine-event marks hidden in v12
    assert 'input.float(0.5, "成本假设' in CLEAR2
    assert 'input.bool(false, "显示引擎计划事件标记' in CLEAR2
    # both push paths for legacy plan events carry the f12 gate (3m + relay)
    assert CLEAR2.count("not f12Enable or f12EnginePushes") == 2

def test_v12_pane_consistency_mirror():
    """3m and 10m must render the same follower state (state relay mirror)."""
    import re
    assert "f_f12_state_snapshot" in CLEAR2
    assert CLEAR2.count("= request.security_lower_tf(") == 2  # events + state
    # both hosts render through the unified disp values
    assert "int dispF12Dir = hostIsCanonical3m ? f12.dir : m12Dir" in CLEAR2
    assert ("bool f12Vis = f12Enable and (hostIsCanonical3m or hostIs10m) and"
            in CLEAR2)
    assert 'table.cell(dash, 1, 0, "IDM v12｜" + hostText' in CLEAR2
    # the mirror never writes follower state back (one source of truth)
    mirror = CLEAR2.split("v12 状态镜像")[1].split("var line f12LnEntry")[0]
    assert not re.search(r"f12\.\w+ :=", mirror)
```

### 6.3 跟单规则的仿真参考实现 research/exit_lab.py（出场变体）

```python
#!/usr/bin/env python3
"""Exit-geometry laboratory: same entries, alternative exits.

Replays the frozen replica to collect every plan (identical construction to
signal_stats.py), then re-simulates each plan's outcome under alternative
exit geometries using the actual 3m bar path.  Entries are held fixed (the
engine's own entry price on the signal bar), so differences between variants
isolate the exit design.  All variants use conservative stop-first accounting
on ambiguous bars and force a flat exit at the session boundary (last 3m bar
of the CAPITALCOM daily session that contains the entry).

This is in-sample exploration on one instrument and ~13 trading days; it
ranks exit designs, it does NOT prove edge.

Usage: python research/exit_lab.py <fixture_dir>
"""

from __future__ import annotations

import sys
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from signal_stats import ET, WARMUP_BARS, load, load_daily, session_bucket  # noqa: E402
from v11_pine_replica import (  # noqa: E402
    ReplicaConfig,
    SETUP_NAMES,
    SIDE_LONG,
    V11PineReplica,
)


def build_plans(root: Path):
    bars3 = load(next(root.glob("*_3M_*.csv")), 180)
    bars10 = load(next(root.glob("*_10M_*.csv")), 600)
    bars1d = load_daily(next(root.glob("*_1D_*.csv")))
    replica = V11PineReplica(bars_10m=bars10, bars_daily=bars1d,
                             config=ReplicaConfig.from_contract())
    snapshots = replica.replay(bars3)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}

    plans = []
    for snap in snapshots:
        if bar_index[snap.close_ms] < WARMUP_BARS:
            continue
        sig = snap.new_signal
        plan = snap.plan
        if sig is not None and plan.active and plan.signal_id == sig.id:
            plans.append({
                "id": sig.id, "open_ms": snap.close_ms, "side": sig.side,
                "setup": SETUP_NAMES[sig.setup],
                "grade": {3: "A", 2: "B", 1: "C"}.get(sig.grade, "?"),
                "countertrend": sig.reason_mask >= 128,
                "entry": sig.entry, "stop": sig.stop, "t1": sig.t1,
                "t2": sig.t2, "risk": (sig.entry - sig.stop) * sig.side,
                "session": session_bucket(snap.close_ms),
            })
    return plans, bars3, bars1d


def session_end_index(open_ms: int, bars3, bars1d, bar_index) -> int:
    """Index of the last 3m bar of the daily session containing open_ms."""
    closes = [b.close_ms for b in bars1d]
    k = bisect_right(closes, open_ms)
    cap_ms = closes[k] if k < len(closes) else bars3[-1].close_ms
    # last 3m bar whose close <= cap_ms
    ms_list = [b.close_ms for b in bars3]
    j = bisect_right(ms_list, cap_ms) - 1
    return max(j, bar_index[open_ms])


def simulate(plan, bars3, end_i, bar_index, variant: str):
    """Return realized R for the plan under the given exit variant, or None
    if the path runs off the data end while still holding."""
    side = plan["side"]
    entry = plan["entry"]
    risk = plan["risk"]
    if risk <= 1e-9:
        return None
    stop0 = plan["stop"]
    t1 = plan["t1"]
    t2 = plan["t2"]
    start_i = bar_index[plan["open_ms"]]
    if start_i >= end_i and variant != "V0":
        return 0.0  # entered on the session's last bar: flat immediately

    def pnl_r(price):
        return (price - entry) * side / risk

    legs = []          # (fraction, exit_price)
    remaining = 1.0
    stop = stop0
    t1_done = t2_done = False
    hh = entry         # best favorable extreme since entry (close basis high/low)
    ema12_prev = None

    for i in range(start_i + 1, end_i + 1):
        b = bars3[i]
        hi = (b.high - entry) * side
        lo = (b.low - entry) * side
        stop_hit = (b.low <= stop) if side == SIDE_LONG else (b.high >= stop)
        t1_hit = (b.high >= t1) if side == SIDE_LONG else (b.low <= t1)
        t2_hit = (b.high >= t2) if side == SIDE_LONG else (b.low <= t2)

        # conservative: stop first on ambiguous bars
        if stop_hit:
            legs.append((remaining, stop))
            remaining = 0.0
            break

        if variant == "V1":  # current fractions, stop never tightens
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
            if t2_hit and not t2_done and t1_done:
                legs.append((0.25, t2)); remaining -= 0.25; t2_done = True
        elif variant == "V2":  # BE delayed: after T1, stop -> entry - 0.25R
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
                stop = entry - 0.25 * risk * side
            if t2_hit and not t2_done and t1_done:
                legs.append((0.25, t2)); remaining -= 0.25; t2_done = True
                stop = entry  # runner protected at cost only after +2R
        elif variant == "V3":  # thirds + 1.2R trail after T1
            if t1_hit and not t1_done:
                legs.append((1 / 3, t1)); remaining -= 1 / 3; t1_done = True
            if t2_hit and not t2_done and t1_done:
                legs.append((1 / 3, t2)); remaining -= 1 / 3; t2_done = True
            if t1_done:
                trail = (hh - 1.2 * risk) if side == SIDE_LONG else (hh + 1.2 * risk)
                stop = max(stop, trail) if side == SIDE_LONG else min(stop, trail)
        elif variant == "V4":  # all-in all-out: 100% at T2 or stop
            if t2_hit:
                legs.append((remaining, t2)); remaining = 0.0
                break
        elif variant == "V5":  # 50% at T1, runner rides 3m close vs t1-level
            if t1_hit and not t1_done:
                legs.append((0.5, t1)); remaining -= 0.5; t1_done = True
            if t1_done:
                # runner exits when a 3m close gives back to entry level
                give_back = (b.close <= entry) if side == SIDE_LONG else (b.close >= entry)
                if give_back:
                    legs.append((remaining, b.close)); remaining = 0.0
                    break

        # update favorable extreme (price terms)
        if side == SIDE_LONG:
            hh = max(hh, b.high)
        else:
            hh = min(hh, b.low)

        if remaining <= 1e-9:
            break

    if remaining > 1e-9:
        if end_i >= len(bars3) - 1 and plan["open_ms"] >= bars3[-1].close_ms - 86400_000:
            return None  # data end, still holding: unsettled
        legs.append((remaining, bars3[end_i].close))
        remaining = 0.0
    return sum(f * pnl_r(px) for f, px in legs)


VARIANTS = {
    "V1": "现行分批50/25/25，但止损全程不动（无保本）",
    "V2": "保本延迟：T1后止损只到 入场−0.25R；T2后才到成本",
    "V3": "1/3制：T1/T2各1/3，末仓T1后1.2R跟踪",
    "V4": "不分批：100%仓位 T2或止损，二选一",
    "V5": "50%T1落袋，余仓收盘跌回入场价才走（无硬保本）",
}


def main(fixture_dir: str) -> None:
    root = Path(fixture_dir)
    plans, bars3, bars1d = build_plans(root)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}

    for p in plans:
        p["end_i"] = session_end_index(p["open_ms"], bars3, bars1d, bar_index)

    def agg(rs):
        rs = [r for r in rs if r is not None]
        n = len(rs)
        if n == 0:
            return dict(n=0, avg=0.0, win=0.0, aw=0.0, al=0.0, need=0.0, tot=0.0)
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        aw = sum(wins) / len(wins) if wins else 0.0
        al = sum(losses) / len(losses) if losses else 0.0
        need = 100.0 * (-al) / (aw - al) if aw - al > 1e-9 else 0.0
        return dict(n=n, avg=sum(rs) / n, win=100.0 * len(wins) / n,
                    aw=aw, al=al, need=need, tot=sum(rs))

    print(f"plans={len(plans)}  (entries identical across variants; "
          f"session-end flat; stop-first on ambiguous bars)")
    print(f"\n{'变体':4} {'n':>4} {'均R':>8} {'胜率%':>7} {'均赢R':>7} "
          f"{'均亏R':>7} {'打平需%':>8} {'总R':>8}   说明")

    results = {}
    for v, desc in VARIANTS.items():
        rs = [simulate(p, bars3, p["end_i"], bar_index, v) for p in plans]
        results[v] = rs
        a = agg(rs)
        print(f"{v:4} {a['n']:>4} {a['avg']:>8.3f} {a['win']:>7.1f} "
              f"{a['aw']:>7.3f} {a['al']:>7.3f} {a['need']:>8.1f} "
              f"{a['tot']:>8.1f}   {desc}")

    # entry-filter overlays on each variant
    filters = {
        "全部": lambda p: True,
        "非启动": lambda p: p["setup"] != "IGNITION",
        "非启动+RTH": lambda p: p["setup"] != "IGNITION"
        and p["session"] != "盘外时段",
        "非启动+RTH+非尾盘": lambda p: p["setup"] != "IGNITION"
        and p["session"] in ("开盘段0930-1130", "午间1130-1400"),
        "拒绝类+RTH+非尾盘": lambda p: p["setup"] == "LEVEL_REJECTION"
        and p["session"] in ("开盘段0930-1130", "午间1130-1400"),
    }
    print("\n== 变体 x 入场过滤（均R / n）==")
    hdr = f"{'过滤':16}" + "".join(f"{v:>16}" for v in VARIANTS)
    print(hdr)
    for fname, fn in filters.items():
        row = f"{fname:16}"
        for v in VARIANTS:
            rs = [r for p, r in zip(plans, results[v]) if fn(p) and r is not None]
            a = agg(rs)
            row += f"{a['avg']:>9.3f}/{a['n']:<6}"
        print(row)

    # best-variant slices
    best = max(VARIANTS, key=lambda v: agg(results[v])["avg"])
    print(f"\n== 最优变体 {best} 分切片（均R / n）==")
    for title, keyfn in [
        ("setup", lambda p: p["setup"]),
        ("grade", lambda p: p["grade"]),
        ("顺逆", lambda p: "逆势" if p["countertrend"] else "顺势"),
        ("时段", lambda p: p["session"]),
    ]:
        groups = defaultdict(list)
        for p, r in zip(plans, results[best]):
            if r is not None:
                groups[keyfn(p)].append(r)
        parts = [f"{k} {sum(v)/len(v):+.3f}/{len(v)}"
                 for k, v in sorted(groups.items())]
        print(f"  {title}: " + "  ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
```

### 6.4 research/exit_lab2.py（单仓+冷却的时序仿真——v12 跟单规则的账本原型）

```python
#!/usr/bin/env python3
"""v12 follower simulation: one-position-at-a-time + cooldown + exit variants.

Chronological simulation of the proposed v12 "跟单模块" on top of the frozen
engine's signals: take only selected setups during selected sessions, hold at
most ONE follower position at a time (new signals while busy are ignored),
and after a stop-out ignore same-side signals for a cooldown window.  Exits
per variant (V1 = current 50/25/25 fractions with the stop never tightened;
V4 = all-in/all-out at T2 or stop).  Conservative stop-first fills,
session-end flat.  In-sample, ~13 days, one instrument.

Usage: python research/exit_lab2.py <fixture_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_DIR))

from exit_lab import build_plans, session_end_index, simulate  # noqa: E402

COOLDOWN_MS = 30 * 60 * 1000


def exit_bar(plan, bars3, end_i, bar_index, variant):
    """Replicate simulate()'s path to find when the follower goes flat."""
    side = plan["side"]
    entry = plan["entry"]
    risk = plan["risk"]
    stop = plan["stop"]
    t1, t2 = plan["t1"], plan["t2"]
    start_i = bar_index[plan["open_ms"]]
    t1_done = False
    remaining = 1.0
    stopped = False
    for i in range(start_i + 1, end_i + 1):
        b = bars3[i]
        stop_hit = (b.low <= stop) if side == 1 else (b.high >= stop)
        t1_hit = (b.high >= t1) if side == 1 else (b.low <= t1)
        t2_hit = (b.high >= t2) if side == 1 else (b.low <= t2)
        if stop_hit:
            return i, (not t1_done)
        if variant == "V1":
            if t1_hit and not t1_done:
                remaining -= 0.5
                t1_done = True
            if t2_hit and t1_done and remaining > 0.30:
                remaining -= 0.25
        elif variant == "V4":
            if t2_hit:
                return i, False
    return end_i, False


def run(plans, bars3, bars1d, bar_index, variant, setups, sessions,
        cooldown=True, one_at_a_time=True):
    busy_until = -1
    cd_side = 0
    cd_until = -1
    taken = []
    for p in plans:
        if p["setup"] not in setups or p["session"] not in sessions:
            continue
        if one_at_a_time and p["open_ms"] <= busy_until:
            continue
        if cooldown and p["side"] == cd_side and p["open_ms"] <= cd_until:
            continue
        end_i = session_end_index(p["open_ms"], bars3, bars1d, bar_index)
        r = simulate(p, bars3, end_i, bar_index, variant)
        if r is None:
            continue
        xi, was_stop = exit_bar(p, bars3, end_i, bar_index, variant)
        busy_until = bars3[xi].close_ms
        if was_stop:
            cd_side = p["side"]
            cd_until = bars3[xi].close_ms + COOLDOWN_MS
        taken.append((p, r))
    return taken


def stats(taken):
    rs = [r for _, r in taken]
    n = len(rs)
    if n == 0:
        return "n=0"
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    eq = mdd = peak = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return (f"n={n:<4} 均R={sum(rs)/n:+.3f} 胜率={100*len(wins)/n:.1f}% "
            f"均赢={aw:+.2f} 均亏={al:+.2f} 总R={sum(rs):+.1f} 最大回撤={mdd:.1f}R")


def main(fixture_dir: str) -> None:
    root = Path(fixture_dir)
    plans, bars3, bars1d = build_plans(root)
    bar_index = {b.close_ms: i for i, b in enumerate(bars3)}
    plans.sort(key=lambda p: p["open_ms"])

    LR = {"LEVEL_REJECTION"}
    LRB = {"LEVEL_REJECTION", "BREAKOUT"}
    AM_MID = {"开盘段0930-1130", "午间1130-1400"}
    RTH = AM_MID | {"尾盘1400-1600"}

    cases = [
        ("拒绝 · 早午盘 · V1 · 冷却+单仓", "V1", LR, AM_MID, True, True),
        ("拒绝 · 早午盘 · V4 · 冷却+单仓", "V4", LR, AM_MID, True, True),
        ("拒绝+突破 · 早午盘 · V1 · 冷却+单仓", "V1", LRB, AM_MID, True, True),
        ("拒绝+突破 · 早午盘 · V4 · 冷却+单仓", "V4", LRB, AM_MID, True, True),
        ("拒绝 · 全RTH · V1 · 冷却+单仓", "V1", LR, RTH, True, True),
        ("拒绝 · 早午盘 · V1 · 无冷却无单仓", "V1", LR, AM_MID, False, False),
        ("拒绝+突破 · 早午盘 · V1 · 无冷却无单仓", "V1", LRB, AM_MID, False, False),
    ]
    for name, v, st, ss, cd, oaat in cases:
        taken = run(plans, bars3, bars1d, bar_index, v, st, ss, cd, oaat)
        print(f"{name:34} {stats(taken)}")

    # per-day equity for the headline case
    print("\n拒绝+突破 · 早午盘 · V1 · 冷却+单仓 —— 按日:")
    taken = run(plans, bars3, bars1d, bar_index, "V1", LRB, AM_MID, True, True)
    from collections import defaultdict
    from datetime import datetime
    from signal_stats import ET
    days = defaultdict(list)
    for p, r in taken:
        days[datetime.fromtimestamp(p["open_ms"] / 1000, ET).strftime("%m-%d")].append(r)
    for d in sorted(days):
        rs = days[d]
        print(f"  {d}  n={len(rs):<3} 日R={sum(rs):+.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
```
