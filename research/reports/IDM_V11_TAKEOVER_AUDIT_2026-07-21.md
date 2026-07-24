# IDM v11 接手审计（Claude Fable，2026-07-21）

审计范围：只读审计，未修改任何代码。冻结源 `intraday_decision_map_v11_aggressive_clean.pine`（下称 **pine**）与 `research/v11_oracle.py`（下称 **oracle**）逐行比对；全部指定文档按顺序完整读毕。

本机已执行的验证：

| 项目 | 结果 |
|---|---|
| 仓库克隆 | 单 commit `e1dd03e`，无 tag，与"清洁交接"描述一致 |
| 冻结 Pine SHA-256 | `77c6fb40…b80cd03`，与 `release-manifest.json` 一致 |
| 公共测试套件 | `53 passed, 4 skipped`（跳过项均为私有 fixture 缺失，符合文档） |
| 私有 fixture | 不在仓库内（符合发布契约） |

未能在本机执行的验证：TradingView 重新编译（P0 第 2 步需要用户账号操作）；Strategy Tester 快照复现（依赖私有数据窗口）。

---

## A. 执行结论（Executive verdict）

1. **冻结基线完好、可复现。** SHA 一致、公共测试全绿。v11.0.0-clean 可以继续作为"失败但可运行"的对照组，不应改动。
2. **oracle 目前不是 Pine 的复刻，而是第二套规则。** 逐行比对确认了 24 处语义不一致（见 B 表），其中至少 9 处会直接改变"某根 K 是否出信号"（阈值组、关键位池、拒绝 K 型、逆势路由、去重模型、仲裁顺序、10m 边界时序、预热期、反手语义）。在这种状态下，任何"oracle 回放得到 X"的结论都不能代表 Pine 的行为。
3. **7/21 私有 fixture 只能证明两件事**：v10.1R 当天全零信号是规则真实输出；以及在因果规则下当天存在可识别机会。它**不能**证明 v11 parity（原因见 C）。
4. **策略收益门槛照旧未通过**（PF 0.638、期望 -$0.33），且本审计不改变该结论。在 parity 与事件账本建立之前，任何调参都无法归因，属于禁止动作。
5. **方向建议：让 oracle 向冻结 Pine 对齐，而不是反过来。** Pine 是唯一在真实 TradingView 上运行过的行为载体；oracle 里"更合理"的部分（如按等级优先仲裁、显式 no-chase）应记为**候选改进**，进入新版本流程，不能借 parity 之名混入。
6. 唯一首个实验维持既定选择：**source-aware Saty 二次拒绝 AdvisoryEvent**，只画图、只提醒、不下单、不动冻结计划（见 G）。
7. 建议执行顺序：P0（用户在 TV 重新编译冻结源并留证）→ P1（唯一配置契约 + 真 v11 导出 fixture + oracle 对齐 + 事件账本）→ P2（Saty 二拒 advisory）→ P3（凭账本数据选一个行为变量）。**本审计到此为止，等待批准后才动代码。**

---

## B. Pine ↔ oracle 不一致总表

图例：`pine:N` = 冻结 Pine 第 N 行；`oracle:N` = v11_oracle.py 第 N 行。"影响"标注 ★ = 会改变信号存在性/几何，☆ = 改变展示、计数或标签但不改变触发。

### B1. 阈值与常量

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 1 | 强确认 K 实体占比 | 0.34（`pine:111`） | 0.45（`oracle:144`） | ★ oracle 更严，同一根 K 两边判定可不同 |
| 2 | 突破确认缓冲 | 0.02 ATR，且有 `max(2*mintick, …)` 下限（`pine:109,420`） | 0.03 ATR，无 mintick 下限（`oracle:147`） | ★ 边界 K 判定不同 |
| 3 | 触碰容差 | 0.10 ATR（`pine:107`） | 0.12 ATR（`oracle:148`） | ★ |
| 4 | 压缩箱宽度上限 | 2.20 ATR，**或 Phase 压缩即可**（`pine:113,518`；`phaseCompression` = stdev(close,21) ≤ 1.10×ATR，`pine:391-392`） | 2.25 ATR，无 Phase 替代口径（`oracle:149,789`） | ★ Pine 的箱体门槛有第二条豁免通道 |
| 5 | 回踩同 bar 确认下影线 | ≥ 0.24×range（`pine:487,510`） | ≥ 0.22×range（`oracle:146`） | ★ |
| 6 | 拒绝扫过下影线 | ≥ 0.38×range 且只要求 `close > open`，**不要求强实体**（`pine:535-538`） | ≥ 0.22×range 且要求 `bull_strong`（0.45 实体 + 0.32 收盘边缘）（`oracle:628-633`） | ★ Pine 接受小实体长针；oracle 要求大实体。同一根锤子线两边结论相反 |
| 7 | A 级"未过度延伸" | `|close − EMA5| ≤ 1.20 ATR`（`pine:724,727`） | `max(0, entry − anchor_high)/ATR ≤ 1.00`（`oracle:156,963-967`） | ★（仅影响 A/B 分级）参照物和阈值都不同 |
| 8 | 成交量证据 | 完全不用 volume | A 级需 `volume ≥ 1.05×均量` 或 setup 属拒绝/回踩（`oracle:157,968-974`） | ★（分级）Capital.com 导出常无量，oracle 会退化 |
| 9 | no-chase 硬规则 | 无显式规则；只靠 spaceR≥0.55 间接体现，且障碍物要求距入场 > tolerance（0.10 ATR）才计入（`pine:234-236,556-562`） | 显式 blocker：距压力/支撑 ≤ 0.35 ATR 直接 `LONG_INTO_RESISTANCE` / `SHORT_INTO_SUPPORT`（`oracle:150,918-925`） | ★ "压力就在 0.08 ATR 上方"这类 K：Pine 因障碍不计入而放行（spaceR=1），oracle 直接封锁 |

### B2. 关键位（S1/R1）与目标池

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 10 | 支撑/压力来源 | 六源混合取最近：Saty 日 ATR 梯（23 档）、确认 pivot(3,3)、昨日高低、**3m 5/12 EMA**、3m 34/50、确认 10m 34/50（`pine:426-441`） | fixture 提供值，否则滚动 20 根最低/最高（`oracle:143,552-561,582-587`） | ★★ 两边的 S1/R1 根本不是同一个数；Pine 还让移动 EMA 冒充静态位（交接文档已知冲突 #1、#3 的根源） |
| 11 | Saty 梯 / pivot / 昨日高低 | 有（`pine:260-272,401-404,422-425`），日线锚 `close[1]`+`ATR[1]` lookahead_on | 完全没有 | ★ |
| 12 | T1 障碍池 | 六源（同 #10 全部）取入场上方最近（`pine:556-562,685-688`） | 只有 resistance/support 一个数（`oracle:943-956`） | ★ 冻结 T1 价不同 |
| 13 | T2 | `min(entry+2R, 第二障碍)`，第二障碍只取 Saty/pivot/昨日（`pine:689-702`） | 恒等于 `entry ± 2R`，从不封顶（`oracle:958`） | ★ 冻结 T2 价不同 → 退出腿完全不同 |

### B3. Setup 谓词

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 14 | 拒绝-重复测试路径 | `sweptSupport[1]` + 更高低点 + `close > high[1]+buffer`（`pine:531-536`） | 近 4 根中 ≥2 根"触碰且收住" + `close > prev.high+eps`，无更高低点要求（`oracle:624-639`) | ★ 触发集合不同 |
| 15 | 回踩触碰源 | 3m 5/12、3m 34/50、确认 10m Cloud、S1 混合位 四类（`pine:471-478`） | 仅 3m 5/12 与 3m 34/50（`oracle:679-693`） | ★ Pine 回踩可由 10m Cloud/S1 触发，oracle 不会 |
| 16 | 趋势启动（cross 分支） | `crossover(5,12) 且 close > anchorUpper`（`pine:460-463`） | `cross_long` 分支**不要求** close > anchor_high（`oracle:830-849`） | ★ |
| 17 | 启动止损 | 恒 `max(low, anchorUpper) − buffer`（`pine:578,584`） | cross 分支 = `low − buffer`；仅 reclaim 分支用 anchor（`oracle:855-861`） | ★ 风险距离不同 → ready/blocked 不同 |
| 18 | 逆势路由 | 拒绝恒放行；**启动实际恒放行**（`longIgnitionRoute = longTrendRoute or close > anchorUpper`，而启动已保证 close > anchorUpper，`pine:614-615`）→ 10m 反向时可出 C 级逆势启动 | 除拒绝外一律 `OPPOSITE_10M_CONTEXT` 封锁（`oracle:933-938`） | ★★ Pine 存在 oracle 不允许的逆势 Ignition 信号类 |

### B4. 分级与封锁

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 19 | A 级条件 | 10m 趋势+10m 节奏严格同向 + 3m 节奏同向 + Phase 门 + EMA5 距离 + spaceR≥1（`pine:722-727`） | context_aligned（10m 节奏可 FLAT）+ 3m 5/12 同向 + 3m 34/50 不反向 + 延伸≤1 ATR + spaceR≥1 + 额外证据（`oracle:976-986`） | ★（分级） |
| 20 | Phase 门有效性 | `bullPhase = 上升 or ≥ −23.6`（`pine:456-457`）——第二个条件几乎恒真，Phase 门形同虚设 | 无 Phase | ☆ 但说明 Pine 的 Phase 只是装饰位，A 级实际不受它约束 |
| 21 | 最低档语义 | C 是兜底档，任何满足风险/空间的触发都至少 C，不存在"完整度不足"封锁 | 有 X 档 + `RULE_COMPLETENESS_BELOW_C` blocker（`oracle:997-1004`） | ★ 计数口径不同 |
| 22 | 预热期 | 无 ready 门槛；数据首根起即可触发（10m context 为 na 时按 FLAT 放行） | `ready = index+1 ≥ max(50,14,5)` 前不产生候选；无 10m context 时 `NO_CONFIRMED_10M_CONTEXT` 封锁（`oracle:569-573,909-910`） | ★ 窗口前 ~50 根行为完全不同 |

### B5. 去重、仲裁、事件身份

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 23 | 去重模型 | 每 setup 独立边沿 `ready and not ready[1]`（`pine:635-642`）；有持仓时同向新触发照发 **ADD SignalEvent**（role=ADD，`pine:828-865`） | 无边沿概念；空仓时任何 tradable 候选立即成交，持仓时同向候选只写进 HOLD 文案，不产生事件（`oracle:464-498,1224-1242`） | ★★ 两边的 SignalEvent 流在定义层面就不同构 |
| 24 | 同 bar 仲裁 | 先 setup 优先级（拒绝>回踩>突破>启动），再等级，再 K 方向（`pine:274-278,749-761`） | 先 tradable，再**等级**，再 setup 优先级，再对齐、空间（`oracle:1023-1040`） | ★ 同 bar 多候选时两边选择可相反。ARCHITECTURE.md 承认 Pine 顺序是设计风险，但 parity 阶段必须先按 Pine 冻结口径 |
| 25 | 事件 id | `time_close + side*100 + setup*10 + grade`（`pine:854-855`）；计划事件 `time_close + eventType` | 自增整数 1,2,3…（`oracle:439,470-482`） | ☆ 账本需显式映射规则 |
| 26 | 逆势试仓对着持仓 | 记为 SignalEvent（role=COUNTERTREND_ADVISORY），计划不动（`pine:831-834`） | 不产生 SignalEvent，产生 `COUNTERTREND_ADVISORY` PlanEvent + PROTECT（`oracle:1140-1154`） | ☆ 计数口径 |

### B6. 计划管理与执行层

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 27 | 反向确认 | 结束旧计划（EVENT_REVERSE）并**同 bar 开新反向计划**（`pine:835-865`） | 只 `OPPOSITE_EXIT` 平仓，当根不反手（`oracle:1155-1171`） | ★ 持仓路径分叉后不可再收敛 |
| 28 | 同 bar 止损后再进场 | 生命周期先算，止损后同 bar 仍可被新信号开仓（`pine:769-866` 顺序） | 每根 K 只有一个动作；止损 bar 上的候选被丢弃（`oracle:464-468`） | ★ |
| 29 | 结构性退出 | `close 破 3m 34/50 ± 0.08 ATR` **且** 3m 节奏反向（`pine:779-781`） | anchor 完整破位（无 0.08 缓冲）**且** 破近 4 根结构极值（`oracle:1176-1199`） | ★ |
| 30 | 保护事件 | 仅 3m 节奏反向触发 PROTECT（`pine:821-826`）；10m 翻转不触发任何事件 | PACE_PROTECT 与 CONTEXT_PROTECT 两类（`oracle:1200-1222`） | ☆/★ 事件流不同 |
| 31 | 执行/成本层 | strategy.entry + T1 50% / T2 25% / RUN 25%→100% 三重 bracket、逆势半仓、佣金 0、滑点 2 tick（`pine:1079-1136`） | 完全没有订单、腿、成本模型 | ★★ oracle 永远无法复现 535 腿口径；它只是决策 oracle |

### B7. 时序与上下文

| # | 主题 | Pine | oracle | 影响 |
|---|---|---|---|---|
| 32 | 确认 10m 边界语义 | `request.security("10", […][1], lookahead_on)`（`pine:394-400`）：3m K 归属于**包含它的** 10m K，所以收盘恰逢 10m 收盘的 3m K（每小时 :00/:30）拿到的是**再上一根** 10m | `bisect_right` 含等号：`confirmed_at ≤ bar.confirmed_at` 即可用（`oracle:368-376`），:00/:30 的 3m K 直接拿到刚收的 10m | ★★ 每 30 分钟一根 K 的 context 两边相差一整根 10m。7/21 审计报告第 5 节的手工口径与 Pine 一致、与 oracle 不一致 |
| 33 | EMA/ATR 种子 | `ta.ema` 首值种子 + `ta.atr`=RMA（SMA 种子）；且 `calc_bars_count=1500` 意味着 EMA 状态取决于加载窗口起点 | 首值种子 EMA + 首 TR 种子的 Wilder ATR（`oracle:336-341,547-550`） | ★ 预热差异衰减慢（RMA 记忆长），单日 fixture 从冷启动重算必然偏离 Pine 实盘值 |

> 未列入表中的次要差异：oracle 的 established/tolerance 用当前 bar 的 ATR 回看历史（`oracle:601,700-710`），Pine 用各历史 bar 自己的 `tolerance[n]`（`pine:483-485`）；`_side_of` 的 1e-12 epsilon；两边 blocker 文案枚举不同。均为 ☆ 级。

---

## C. 为什么现有 7/21 fixture 证明不了 v11 parity

1. **产生者错了。** 两份 CSV 是 v10.1R 挂图时导出的：全部 v10 信号列为零（报告 §1 已核验），且**不含任何 v11 输出列**。它记录的是"v10.1R 说了什么"，对"v11 会说什么"没有一个字节的证据。
2. **OHLC 无法重建 Pine 的内部状态。** v11 的判定依赖：EMA/ATR 状态（受 `calc_bars_count=1500` 与图表历史起点影响）、日线 Saty 锚与日 ATR、昨日高低、确认 pivot 流、六源 S1/R1 混合值、Phase 与压缩位。这些全都没有导出。从 CSV 首行冷启动重算 EMA/ATR（B 表 #33）在数学上就不会等于 Pine 挂图时的取值。
3. **拿 oracle 回放 fixture 不能代表 Pine。** B 表列了 24 处差异，其中 9+ 处改变触发本身。oracle 在这份数据上产出的入场（10:12/10:27/10:42/11:09 等）只证明"某套因果规则可以做到"，不证明"冻结 Pine 会做到"。
4. **fixture 测试锁的是 oracle 自己。** `test_v11_oracle.py:485-673` 的四个跳过测试断言的是 oracle 决策（含 stop_basis、riskATR 等 oracle 专有字段），它们是 oracle 的回归护栏，不是 parity 证据。
5. **边界时序未定。** B 表 #32 的 :00/:30 差异意味着即使其余全对齐，每 30 分钟仍有一根 K 的 context 分歧，必须先在 TV Data Window 实证并写进契约。
6. **单日样本。** 就算逐根全对，也只是 1 个交易日、无 OOS，不能外推任何统计结论（原报告 §7 已自我声明）。

结论：7/21 fixture 保留为**历史诊断证据**；parity 需要 E 节定义的"由冻结 v11 本身导出"的新 fixture。

---

## D. 唯一权威规则/配置契约（提案）

**原则：冻结 Pine 11.0.0-clean 的实际行为就是 v11 契约。** oracle、文档、测试全部向它对齐；`docs/V11_CLEAN_SLATE_SPEC_ZH.md` 保留为历史设计稿（其头部已自我声明漂移，如 1.25 vs 1.30 ATR）。任何"oracle 的写法更好"（等级优先仲裁、显式 no-chase、CONTEXT_PROTECT 等）一律登记为候选改进，走新版本 + 新报告，不得在 parity 期混入。

**载体：** 新增 `research/config/v11_contract.json`（机器可读、带 `contract_version`），三方绑定：

- oracle：`EngineConfig.from_contract()` 加载，不再散落默认值；
- Pine：冻结源不动；新增契约测试用精确字符串断言每个 `input.*` 默认值与硬编码常量（扩展 `test_v11_aggressive_clean_contract.py` 的风格）；
- 文档：引用数值必须写 `contract_version`。

**契约必须显式记录的条目**（值 = 冻结 Pine 实际值）：

| 组 | 条目 |
|---|---|
| 长度 | ema 5/12/34/50，atr 14，pivot 3/3，structureLookback 4，compressionLookback 8 |
| 阈值 | touchAtr 0.10；triggerAtr 0.02 + `max(2*mintick,·)` 下限；strongBody 0.34；closeEdge 0.32；pullbackWick 0.24；rejectionWick 0.38（仅要求 close>open）；compressionAtr 2.20 或 phase 压缩（stdev21 ≤ 1.10×ATR）；stopBuffer 0.10；maxRisk 1.30；minSpace 0.55；B 档 space 0.75（硬编码）；A 档 space 1.00；A 档 `|close−EMA5| ≤ 1.20 ATR`；Phase 公式与 ±23.6 门（含"实际近似恒真"的注记） |
| 关键位 | 六源池及各源资格条件（B 表 #10）；Saty 23 档比例表；日线锚 = `close[1]`/`ATR[1]` lookahead_on；障碍资格 = 距参考 > tolerance |
| 几何 | 各 setup 止损公式（`pine:572-584`）；T1 = min(1R, 六源最近障碍)；T2 = min(2R, Saty/pivot/昨日第二障碍)；spaceR 封顶 1.0 |
| 路由 | 拒绝恒放行；回踩/突破需 10m 不反向；**启动实际恒放行**（如实记录，标注为已知设计风险） |
| 仲裁 | setup 优先级 → 等级 → K 方向；多空同 bar 规则（`pine:749-761`） |
| 去重 | 每 setup `ready and not ready[1]` 边沿；ADD/REVERSE/COUNTERTREND_ADVISORY role 语义 |
| 计划 | 生命周期顺序 Stop→T2→T1→结构退出→节奏保护；stop-first 歧义规则；T2 runner 条件与 stop 上移到 T1；反向同 bar 换仓 |
| 时序 | 10m context = 包含式 `[1]` 语义（:00/:30 边界以 TV 实证为准，见 I-2）；3m 唯一事件源；`time_close ≤ timenow` 的 relay 确认口径 |
| 身份 | signal id / plan event id 公式；oracle 侧的映射函数 |
| 执行 | qty 2；T1 50%/T2 25%/RUN 25%→100%；逆势半仓；commission 0；slippage 2；process_orders_on_close |

**变更规则：** 改任何条目 = `contract_version` +1 = 新 Pine 版本号 = 新报告。合成测试允许用短周期构造器，但必须显式声明偏离契约。

---

## E. 真 v11 parity fixture 设计与事件账本 schema

### E1. Fixture 采集（不改冻结源的部分先行）

冻结 v11 已经在 Data Window 输出了 19 个审计字段（`pine:1436-1473`），且 S1/R1/EMA/计划线都是可导出的 plot。TradingView "Export chart data" 会带出全部 plot 列，因此**第一份真 fixture 不需要改任何代码**：

1. 3m 图挂冻结 v11（订单关），导出完整可见历史（含评估窗前 ≥3 个完整交易日预热，覆盖 10m EMA50 与 RMA ATR 的记忆）；
2. 10m 图同参数导出一份，用于验证 relay 同一性；
3. 订单开启后单独再导 3m 一份 + Strategy Tester 明细（List of trades），用于腿级对账；
4. 每份导出记录：symbol、时区、日期范围、脚本修订号、参数快照、导出时间。私有数据照旧不入库，只入 `research/fixtures/`（gitignore）并在 manifest 记 SHA。

现有 Data Window 的缺口（**信号 bar 的 E/S/T1/T2、spaceR、ATR、S1/R1 来源身份、Saty 锚/日 ATR、pivot 值、phase**）留待 P1 后半程：出一个 `11.0.1-export` 附加版（新文件，仅追加 `display.data_window` plot，UI/信号/订单零改动），验收标准是 SignalEvent id 序列与 Strategy Tester 结果和 11.0.0 逐项相等。

### E2. 事件账本 schema（JSONL，每行一个事件）

```json
{
  "schema_version": 1,
  "engine_version": "11.0.0-clean",
  "contract_version": 1,
  "symbol": "CAPITALCOM:SPX500",
  "tf_engine": "3m",
  "bar_open_utc": "…",
  "bar_close_utc": "…",
  "event_class": "CANDIDATE | SIGNAL | PLAN_EVENT | ADVISORY | ORDER_LEG",
  "event_id": 0,
  "side": -1,
  "setup": "LEVEL_REJECTION | PULLBACK | BREAKOUT | IGNITION",
  "grade": "A | B | C",
  "role": "INITIAL | ADD | REVERSE | COUNTERTREND_ADVISORY",
  "entry": 0, "stop": 0, "t1": 0, "t2": 0,
  "space_r": 0, "risk_atr": 0, "reason_mask": 0,
  "blocker": "READY | TRIGGER | CONTEXT | RISK | SPACE | COUNTERTREND",
  "context_10m_close_utc": "…", "context_dir": 1, "context_pace": 1,
  "support": 0, "resistance": 0,
  "level_source": "SATY_+0.618 | PIVOT | PDH/PDL | EMA_FAST | EMA_ANCHOR | CTX_ANCHOR | null",
  "plan_id": 0, "plan_event_type": "T1|T2|STOP|PROTECT|STRUCT_EXIT|REVERSE",
  "plan_event_price": 0,
  "leg": {"exit_kind": "T1|T2|RUN|STOP|CLOSE_ALL", "qty": 0, "pnl_usd": 0}
}
```

`level_source` 在 11.0.0 里必然是 `null`（六源混合后无身份，STATUS 已声明）；字段先占位，供 Saty advisory 与未来 source-aware 版本填写。

### E3. 四层分账（对应 SIGNAL_AND_PLAN_CONTRACT.md 的 Reporting 条款）

| 层 | 定义 | 唯一键 |
|---|---|---|
| 候选 episode | 同一 (setup, side) 的 ready 连续段（边沿到失效） | ready-edge 起始 bar |
| SignalEvent | role ∈ {INITIAL, REVERSE} 的事件（ADD、逆势 advisory 分开计数） | `event_id` |
| Plan | 计划开启到 active=false | `plan_id` = 开仓 signal id |
| 退出腿 | Strategy Tester 每行 | 订单 id |

**parity 判定标准：** oracle 对齐后，用同一 fixture 逐 bar 比对：SIGNAL 行 id/时间/side/setup/grade/E/S/T1/T2 全等；PLAN_EVENT 序列全等；不允许"总数接近"式的模糊通过。3m 导出与 10m 导出的 SIGNAL/PLAN_EVENT id 集合必须完全一致（relay 同一性）。

---

## F. SATY 观察复盘（Location → State → Trigger → Management）

对照 `docs/SATY_OBSERVATIONS_2026-07-21.md` 的七个阶段与六条候选规则，用四角色契约（Cloud=背景/节奏、Saty=位置/空间、振荡=风险、结构=扳机）逐条评估 v11 现状：

| 观察规则 | 契约角色归属 | v11 现状 | 差距定性 |
|---|---|---|---|
| 1. 支撑响应优先于弱方向观点 | 位置→管理 | 部分具备：shortT1 = max(1R, 支撑障碍) 会在已知支撑前止盈；stop-first 保守 | 支撑处"必须重新证明续跌"没有显式状态；靠 T1 几何间接实现 |
| 2. 多头失效被收回后换路线 | 结构→触发 | 不具备路线记忆；新空仍可由拒绝随时出现 | 拒绝 setup 恰要求"失败反抽"形态，方向大体一致，但无"旧论点作废"约束 |
| 3. 3m 节奏反复撑住 → 回踩 BUY / HOLD LONG | 节奏→触发/管理 | 具备：Pullback setup + 持仓 HOLD + ADD 参考；fixture 审计验收 §6-4 与此一致 | 与观察吻合度最高的一条 |
| 4. 背离先管理、不裸做空 | 振荡→风险 | **缺失**：无背离引擎（STATUS 声明）；Phase 门近似恒真（B 表 #20） | 这正是"振荡角色"完全空缺的证据；只能靠 advisory 路线补，不能进扳机 |
| 5. 成熟延伸不追 | 位置→风险 | 仅 A 级有 EMA5 距离限制；B/C 无延伸约束、无 no-chase 硬规则（B 表 #9） | oracle 的 no_chase/extension 是候选改进，须走 P3，不得混入 parity |
| 6. 静态位必须有身份 | 位置 | **违背**：六源坍缩成无名 S1/R1，移动 EMA 可冒充静态位（B 表 #10） | 已知冲突 #1；G 实验就是最小的身份化切口 |

七阶段叙事与产品映射的两个补充教训：

- "开盘弱势→下探失速→反转"段落里，正确输出是**先保护空单、等收回确认**，对应 v11 的 PROTECT/EXIT 事件族——但 v11 没有 10m 翻转保护（B 表 #30），阶段二的"波动不再确认下行"在事件流里没有着落点；
- "最清晰的错失不是缺指标，而是支撑与节奏反复同向确认后仍持怀疑"——对应的产品要求是 fixture 审计 §6-4 的持续 `HOLD LONG` 显示，这属于展示契约，v11 已实现（计划活跃时面板显示持仓状态）。

隐私边界复查：该文档为转述、无引用原文/用户名/截图/链接、不声称胜率，符合发布契约；7500 附近的百分比被正确标注为"当时观点，非校准输出"。**没有任何一条观察可以在本仓库转化为概率或胜率声明。**

---

## G. 唯一首个实验：source-aware Saty 二次拒绝 AdvisoryEvent

采纳 `docs/EXPERIMENT_SATY_LEVEL_ADVISORY.md` 原契约，不扩容。以下是把它变成可实现规格时的补充决定（全部留在新版本 `11.1.0-advisory`，冻结源零改动）：

- **假设**：同一条静态日 ATR 位、先确认拒绝、真实离开、再次测试并确认拒绝，作为持仓风险语境，比无名 `Level Rejection` 更有用。仅 advisory，不交易。
- **级别身份**：沿用 Pine 已有的 23 档 Saty 梯（`pine:261-264`）+ 日锚 `close[1]`。level_id = (anchor_date, ratio)。锚变（新交易日）即全清。移动 EMA/Cloud 触碰**永不**参与此状态机。
- **状态机**：IDLE → 首次确认拒绝 → WATCH(level_id) → 离开该位 ≥ `departure_atr`（契约新参数，初值建议 0.50×3m ATR 的等效距离，进契约后冻结）→ DEPARTED → 同一 level_id 再测且确认拒绝 → 发 `AdvisoryEvent(SATY_SECOND_REJECTION)` → IDLE。收盘穿越失效价 / 换锚 / 到期 → IDLE。相邻档位不得拼接为一个 episode；未离开的反复触碰只算一次测试。
- **事件身份**：advisory id = `time_close + 300 + ratioIndex`，与 signal/plan id 流不冲突；3m 唯一事件源，10m 经同一 sparse pulse 通道 relay 同 id/同时间（pulse 元组只允许**追加**字段，既有 17 个字段顺序不变）。
- **呈现**：图上 `Saty 二拒↑ / Saty 二拒↓`；tooltip 含级别价、ratio、首测/离开/二测确认时间、失效价；手机自然中文（示例照原契约）；Data Window 增加 advisory id/ratio/level 三个字段。
- **红线**：不调用任何 `strategy.*`；不读写 plan；不改 A/B/C；开关关闭时，SignalEvent id 序列、订单数、Strategy Tester 结果与 11.0.0 逐项相等（这是硬验收，见 H）。
- **成功度量（研究性，不做任何盈利声明）**：账本记录每个 advisory 后 N 根 K 的 MFE/MAE 分布，与"同位置无二拒"基线对照；样本、区间、截止日期齐全后才允许讨论是否升级为 setup（升级 = 又一个新版本 + OOS 报告）。

---

## H. 验收测试清单

### H1. Parity 阶段（P1）

| 类别 | 测试 |
|---|---|
| 正向 | 合成序列上，对齐后的 oracle 与契约中每个 setup 的最小触发例逐一相符（四 setup × 双向共 8 例，含各自止损公式与 T1/T2 封顶） |
| 负向 | 六源池中每一源单独制造"恰好差 1 tick / 差 0.01 ATR"的不触发例；spaceR=0.549 拒发、0.55 放行；risk=1.301 ATR 拒发 |
| 边界 | :00/:30 的 10m 边界 K：oracle 采用契约敲定的包含式语义后，与 TV Data Window 实测逐值相等（I-2 先行）；预热期第 1–50 根不产生与 Pine 不同的事件 |
| Reload | 同一 fixture 重放两次，事件账本字节级相同（oracle 决定性）；TV 侧：移除并重新挂载冻结脚本，历史 SignalEvent id/时间/几何不变（人工核对 Data Window 抽样 ≥10 个事件） |
| Replay | TV Bar Replay 从窗口起点逐根步进至终点，产生的事件集合与整段历史一次性计算完全一致（重点覆盖 :00/:30 边界 K 与开仓/止损同 bar 情形） |
| 3m/10m 同一性 | 两份导出的 SIGNAL/PLAN_EVENT id 集合全等；10m 图任一 relay 标签的 tooltip id 能在 3m 账本找到同 id 同时间同 E/S/T1/T2；10m 图零 `strategy.*` 副作用 |

### H2. Advisory 实验阶段（P2，对应原契约验收 + 补充）

| 类别 | 测试 |
|---|---|
| 正向 | 合成：首拒→离开→二拒 产生 advisory（多空对称各一例）；tooltip/alert 字段齐全 |
| 负向 | 无离开的反复触碰不发；相邻档位交叉测试不发；EMA 触碰伪装静态位不发；首拒本身不产生 SignalEvent/Plan/订单 |
| 边界 | 离开距离恰等于阈值（含/不含按契约定死）；二测 K 收盘恰在失效价；换锚 bar 上状态清空 |
| Reload/Replay | advisory id/时间在重挂与 Bar Replay 下不动、不重复、不提前（15:51 确认的事实不得画在 15:50） |
| 同一性 | 3m 与 10m 显示同 advisory id/时间/级别 |
| **零扰动回归** | advisory 开/关两种状态下：SignalEvent id 序列相同、订单数相同、Strategy Tester 全部汇总指标相同；公共 53 测试通过；冻结源 SHA 不变 |

---

## I. 未知或不可验证项

1. **冻结源在当前 TV Pine v6 上是否仍编译通过**：证据止于修订 13；本环境无 TV 账号，P0 需用户重新编译并截图/记录（不改一字）。
2. **:00/:30 边界的 `request.security(…[1], lookahead_on)` 实际取值**：B 表 #32 的分析基于 TV 文档语义，必须在图上用 Data Window 的 `Confirmed 10m source time` 字段实证后写进契约。
3. **`calc_bars_count=1500` 窗口效应**：EMA/ATR 状态随脚本加载时刻的历史起点漂移，同一天不同时间挂载可能得到不同事件；漂移幅度未量化，parity fixture 必须以导出值为准而非重算。
4. **CAPITALCOM:SPX500 的"D" 日线口径**：近 24 小时 CFD 的日线锚 `close[1]`、昨日高低与 Saty 方法惯用的现金时段锚是否一致未验证，直接影响 Saty 梯的忠实度。
5. **TV 导出是否含 volume**：oracle 的 A 级证据用到量能（B 表 #8）；若无量，两边分级永不可比。
6. **`strategy.exit` 的 `qty_percent` 结算基数**（当前仓位 vs 初始仓位）：50/25/25 的分腿设计依赖该语义，需要在 Strategy Tester 明细里逐腿核实；这也决定 535 腿的构成解释。
7. **535 腿快照不可复现**：依赖私有窗口数据 + TV 撮合模拟器内部行为；只可存档，不可对账。
8. **`varip` 提醒游标在 TV 提醒服务重启/快照下的行为**：文档警告旧提醒保存脚本快照；重复/漏发风险未实测。
9. **`request.security_lower_tf` 是否保证每根 3m intrabar 都在 10m 数组中**：TV 文档允许稀疏数据缺失；SPX500 流动性高，实际缺失率未测。
10. **RELAY_CALC_BARS=4000（≈200 小时）之外的 10m 历史**不再显示 relay 标签；对用户回看习惯是否够用未确认。
11. **原始仓库证据链**：`source_commit 8a5f03a…`、`fixture_commit f3d5dcd` 指向未发布的私有历史，公开仓库内不可验证，只能信任 manifest。
12. **背离/VIX/NDX/关键时间模型**：按设计不存在于本版本；SATY 观察规则 4 的"振荡角色"目前无承载物，除 advisory 路线外没有合规的实现位置。

---

## 下一步（待批准，未执行）

1. **P0（用户）**：TradingView 粘贴冻结源重新编译 3m/10m 各一次，记录修订号与无报错截图；不改任何字符。
2. **P1（我）**：建 `v11_contract.json` + 双侧契约测试 → 按 D 表把 oracle 对齐冻结 Pine（一次一组差异，B 表编号即工单号）→ 用户导出真 v11 fixture（E1 第 1–3 步，零代码）→ 逐 bar parity 对账 → 需要时再出 `11.0.1-export` 附加版。
3. **P2（我）**：`11.1.0-advisory` 实现 G 实验，跑 H2 全套。
4. **P3（凭账本数据，选且只选一个行为变量）**。

本报告为审计交付物；在得到批准之前，我不会修改 Pine、oracle 或测试。
