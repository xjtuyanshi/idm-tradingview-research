# Saty 剧本文法规范 v1.1（2026-08-08）

> **性质声明**：描述性规范——记录他 43 个交易日（#notes 广播频道）里怎么做，
> **不是已验证的优势宣称**。语料为其自选发布，交易也发生在未采集的 #chat；
> 午盘 12-15 ET 存在系统性欠采样。一切"从不/总是"只在 #notes 语料范围内成立。
>
> **审计结论**：覆盖率验收 91.4%（64/70 笔可表达；补 E11-E13 后 ~100%）。
> 对抗审查抽查 40 条引证全部属实、零造假；下列修订**覆盖正文冲突处**。

## v1.1 审计修订（覆盖正文）

### 新增文法（覆盖率验收员）
- **E11【软】动量续势突破**：flag/压缩/箱体收口后破高（或 10m 21/200 cross）顺势入场，
  目标=下一具名位，仍受 E2 位挂靠与 E3 晨报分支约束（06-30 3m flagging→7500；06-18 10m 21/200 cross）。
- **E12【例外】YOLO 豁免白名单**：本人自标 YOLO/极小仓娱乐单=文法外豁免，不算违规（06-17）。
- **E13【硬】亏损后重进**：吃 L 后重进必须重新满足 E1 合取并挂靠同一或更优具名位，
  禁止情绪回本单（06-03 反例自评；07-22 正例"同样的关键位+alert 流程"）。

### 降级与更正（对抗审查员）
1. **删 07-30 作"缺席/情绪日"例证**——他当天早盘有完整空单（含 4 周期 recap）；情绪日降预期≠不交易。
2. **频次<3 的"规则"全部降级为个案观察**：backtest 失败反打（n=1）、IPO 不接盘（n=1 且是持股观点）、
   高周期扩张时回避 3m 逆势背离（原话 "often"≠never，改"通常回避"）、Vomy 独立触发。
3. **绿转红零容忍**：明文仅 07-09 一条 + 2 条"保绿点"同族，不得写成"贯穿性纪律≥3 次明文"。
4. 基数更正：43 个交易日（非"约 46"）；Weekly Note 9 份；晨报时段 8:03-9:05 ET 有弹性。
5. **#chat 盲区专节**：58 笔与全部"从不"仅覆盖 #notes；已证 chat 内另有交易（06-26 "We traded this PDC short in chat"）。
6. 窗口统计带采样警告："22 天首笔在 9:31-9:50""中午收工"受午盘欠采样系统性抬升，证据等级=采样受限。
7. "无双分支晨报=降频信号"降级为观察相关性（6 例成因异质，反推发布行为是过拟合）。
8. OPEX 模板 n=2 且方向相反（07-17 零交易 vs 06-18 午后照做）；"半仓以下"降为引语级建议。

---

# Saty 剧本文法规范 v1

> **性质声明：本文档是对 Saty（Saty Mahajan 风格盘口语料）2026-05-29 至 2026-08-04 约 46 个交易日 + 7 份 Weekly Note 的【描述性规范】——只陈述"他实际怎么做"的语法结构与频次，不构成任何已验证的统计优势宣称。所有战果引语均为其本人自述（claimed），未经独立对账。**
>
> 语料：`docs/saty_corpus/BY_DAY.md`（ET 已换算、四类标注）、`docs/saty_corpus/RAW_notes.md`（PT 原文）。旁证：`SATY_RIPSTER_METHOD_STUDY.md`、`SATY_PLAYBOOK_CORPUS.md`、`SATY_WEEK_2026-08-05_07.md`、`SATY_EOD_PLAY_2026-08-06.md`。
> 统计基座：晨报采到 33 份（`key level` 在 RAW 中 37 处命中）；交易记录约 58 笔（含个人单与实时喊单，喊单已在引证中注明）。

---

## §0 总文法（一句话版）

**周报定语境 → 晨报给双向剧本（VIX 开关 + strike 对 + if-then 位链）→ 开盘窗在具名位上等触发形态 → 顺兑现分支 level-to-level 分批 → 留 runner 移止损 → 反向信号或时间点到即走 → 绿点必须活过今天。**

---

## §1 三层输出节律（硬结构）

| 层 | 时点 | 内容 | 频次 |
|---|---|---|---|
| Weekly Note | 周日 13:43–15:03 ET | 周级位 + 双分支 + 事件日历 + 个股清单 | 7/7 个周末 |
| Morning Plan | 8:26–9:05 ET | VIX key level + strike 对 + 双向 if-then + 事件 + Ideas | 33 份采到 |
| EOD/复盘 | 收盘前后 | 复盘 + 个股分析，常转 chat | 高频但不保证 |

**硬规则 H1：晨报必含 VIX key level。** 33/33（06-01「15.75 key level」…08-04「15.5 key level」）。
**硬规则 H2：晨报必含双 strike 对（SPX+SPY、call+put 四腿）。** 32/33；唯一例外 06-15（只给 VIX 16.5 与 750-752 区间）。
**软倾向 S1：晨报默认双向 if-then。** 27/33；6 个例外全部以**姿态声明**替代——06-03「Will wait for setups after 10am」、06-10「Play by ear. OTM strikes selected for volatility」、06-16「Might be an inside day…Good day to be very selective」、06-18 结构描述+OPEX 警告、06-25 缺席声明、07-28「sit on hands / be more picky today」。**推论：无双分支 = 当日降频信号，本身可交易信息。**

---

## §2 入场文法（合取式）

### 2.1 规范形

```
ENTRY := 位(必要) ∧ 形态(触发) ∧ 环境(门控) ∧ 窗口(许可) ∧ 方向(晨报分支)
```

### 2.2 硬规则

- **H3 无位不入**（≥50/58 笔有具名挂靠位）。引证：07-13「I bought that 10m 21 like it was going out of style」；06-29「Testing overnight pivot support / Scaled」；07-10 连风险都用位定义「a worthy spot to try with PDC risk」。反例自证：06-03 无位提前进场 →「Took the L!」+「I should have been more patient」。
- **H4 入场 = 晨报分支兑现**，且**剧本优先级 > 单一指标**。06-05「if you followed the plan and ignored the 3m SPX PO, it worked haha」；07-27「Nice confluence of higher timeframe analysis with lower timeframe execution」。
- **H5 事件门**：数据/发布会前不开仓。08-04「wait until after 10am to trade」；06-17「wait until presser to do anything」；违反样本 06-03 当场受罚。
- **H6 不追高**：08-03「7600c 1 to 6 / I am not going to chase this」；06-22「if (you.have(FOMO)) { wait.until(retest); }」；07-15「not chasing…ribbon test」；07-01「I didn't get in, so am not chasing」。

### 2.3 形态触发清单（按确信度排序）

1. **多周期 PO 极值共振**（最高确信，07-23「3m extreme / 10m extreme / H accumulation」+「I will long this shit…almost 100% of the time」；07-08、06-23 同构）。
2. **10m 21 回踩**（顺势日默认，07-02「Beautiful 10m 21 pullback entry」、07-13、06-22、07-30）。
3. **GG open 顺势**（≥10 天；但非充分条件——08-03「I'm not convinced, despite having GG open」）。
4. **Vomy/均值回归**（07-28「10m looking Vomy→10m Vomy indeed」区间顶到底；06-02 Evening star + bilbo box 顶）。
5. **箱体/trigger 破位**（06-22 trigger box 突破「instabanger」、07-13「SPX flag break」）。
6. **backtest 失败反打**（06-26「Backtesting resistance→Scale PM low / demand」）。
7. **EOD LB 洗位**（独立文法：LB 前排 strike + 1m 形态 + MOC，06-08、07-13、07-20）。
8. **个股 Ideas**（IV Flush/ER 剧本，07-13 AAPL、07-24 INTC——挂牌≠胜率，INTC「Gross so far」）。

---

## §3 出场文法（阶梯）

- **H7 Level-to-level 分批，零 R 语言**（~30 笔 scale 指令，0 笔 R 倍数）。08-03「Level-to-level perfection today」；06-26「Scale PM low / demand」；07-23「Scale 10m 13」。
- **S2 Free-trade 阶梯**：1/2 → free trade；2/3 → can't-lose；尾仓按更高周期出（06-10 原文完整定义「take off half…for a free trade. 2/3 for can't lose trade. Exit for a 10m workday」；06-22 NVDA「Sold 2/3…for a free trade」）。例外：快速全出型（06-08、07-31「Closing last of my 7400p」）。
- **S3 Runner + 移动止损**：house-money 止损 100%→自我修正 50%/保本（06-15）；07-30「leave runners / move stops on runners」。**归零可接受**：07-20「they are 0…profits from profits from profits」。
- **H8 反向信号即走、宁早勿贪**：07-31「Little early on my exit / but…Was good enough signal for me」；06-24「oh shit / Saty out.」。
- **H9 绿转红零容忍**：07-09「There should be no green to red trades」；06-15「Make sure your green dot survives the day」。
- **S4 时间性硬停**：06-05「Hard stop at 11:30am」；07-31 午后休假；06-23「Called it a morning 1/1」。
- **S5 不确定性前清仓**：06-17 FOMC「Didn't hold anything for MOC」。

---

## §4 环境状态机

| 状态 | 判据 | 行为影响 | 引证 |
|---|---|---|---|
| S1 压缩 | 10m/H(ETH) 乃至四周期 compression | 等破位；破前 choppy 预期、降仓 | 07-28 四周期压缩；07-24「compression living up to its choppy expectations」 |
| S2 趋势日 | demand 连守 + EMA 阶梯接力 | 持仓不折腾、runner 到 GG complete/+1ATR、可跳过 power hour | 06-04「Demand until proven otherwise!」；07-09 |
| S3 Chop/Grind | 低 VIX + 无跟随区间 | **降频到零**或转个股 | 07-17「No interest in trading this chop」（零交易日）；07-22 弃 SPX 做 NVDA |
| S4 PO 极值 | 3m/10m PO ±170/200 | (a)逆向不开新仓 (b)落支撑+高周期吸筹=最高确信入场 (c)持仓中=兑现信号；但**剧本>PO**（06-05） | 06-05「hard to go short here for me」；07-23；07-20「Can pullback/consolidate」 |
| S5 事件窗 | CPI/PPI/NFP/JOLTS/FOMC/拍卖 | 落地前不交易；strike 更 OTM；FOMC 后做标准回落 | 08-04；06-10「OTM strikes selected for volatility」；07-29「YOU KNEW IT WAS COMING」 |
| S6 OPEX | OPEX/三巫及前一日 | 轻仓或零交易 + 尾盘看 pin | 06-18「clean trend days and choppy nightmare days. Size appropriately」；07-17「CHOPEX…pin 7500」 |
| S7 VIX 门控 | VIX vs 当日 key level | VIX 拒门槛 → 剧本终止；低 VIX → grind 预期 | 07-30「Held gap, rejected VIX 19」；07-27「Over 20 things can get spicy」 |
| S8 护盈 | 大赚周/日之后 | 硬停、轻仓、半天休 | 06-05；07-17「Let's not give back gains from AAPL」；07-31 |
| S9 缺席 | 家事/情绪预告 | 不交易，只远程点评 | 06-25「Emotional day!」当日不交易；07-30「hangover from adrenaline」 |
| S10 模式切换 | easy↔hard mode 多周感知 | 全局降预期、强调纪律 | 06-08「many weeks of easy mode. Now the market has changed」；07-24「hard mode」 |

---

## §5 窗口纪律

- **主战窗 9:31–10:30 ET**：约 22 个交易日首笔动作落在 9:31–9:50。晨报固定 8:26–9:05 发布。
- **EOD/LB 窗 15:40–16:00 ET**：独立文法（§2.3-7）；常「skip most of power hour」只看最后 15-20 分钟（08-03、07-29）。
- **午间窗**机会性（06-02、06-30「Flight 7500c」、07-07 一击）。
- **默认节奏「call it a morning」**：多数日中午收工（06-23「1/1」、06-09 12:04、07-31 10:12），午后 class/chat。
- **窗外机会不追**：07-16「nice shorts this afternoon…Grindy af though」只评不做；07-17 14:21「Didn't trade it but cleanest move since the morning」。

---

## §6 日型分类

标准双分支日 / 事件待命日 / OPEX 日 / 趋势日 / Chop-Grind 日 / 收官护盈日 / Inside day / GFT / 缺席日 / 周日周报日。判据与引证见 day_types 字段；可执行模板如下。

---

## §7 双向剧本模板（可直接填我方梯位）

### 7-A 标准双分支日（主模板，样本：06-09/07-06/07-20/08-03）

```
VIX {VIX_KEY} key level（当日风险开关：站错侧=剧本存疑）
上行合约: SPX {C}c / SPY {c}c ｜ 下行合约: SPX {P}p / SPY {p}p（strike≈两侧首个目标位）

IF 10m 趋势延续 + 突破 {T_up ∈ PM高|盘前阻力|long trigger|昨HOD|ATH}
  → 目标链 {L1 ∈ PDC|midrange} → {L2 ∈ 昨HOD|+1 ATR|整数关} → {L3 ∈ +1 ATR|周高|月枢轴}
  出场：L1 首兑(1/2 free trade) → L2 再兑(至2/3) → runner 移止损至保本，GG complete/L3 清仓

IF 失守 {T_dn ∈ PDC|10m 200|short trigger|overnight pivot|盘前低}
  → 目标链 {L1' ∈ overnight lows|昨LOD} → {L2' ∈ -1 ATR|demand 区}
  出场：镜像同上
```
原型引证：06-09「IF 10m continuation → yesterday HOD / IF break of 10m 200 and long trigger → back to PDC」；07-20「IF continuation through Friday resistance and PM high / 7500 → golden gate opens move to midrange, SPY 750, then +1 ATR / IF lose this 10m trend → Vomy down to PDC…then SPY 740」。

### 7-B 事件待命日

```
IF {事件} 未落地 → 零交易，只观察（08-04；06-17）
IF 落地 → 转 7-A，strike 更 OTM（06-10），FOMC 加一条：发布会后回踩 10m 21 为标准剧本（07-29）
```

### 7-C OPEX 日

```
默认半仓以下；开盘窗若无 A+ 触发 → 转零交易观察日（07-17 实证）
尾盘：LB clear 早判 pin（07-27「大跳空日会早看是否早 pin」），只做 LB 洗位文法或不做
```

### 7-D 趋势日

```
确认口令：demand 连守 +「until proven otherwise」（06-04）
回踩 {3m 8/21 或 10m 21} 接力进；runner 持到 {GG complete | +1 ATR}
禁绿转红（07-09）；高位 PO 极值 = 兑现不加仓（07-09「Bound to be some profit taking…2 hours into bullish expansion」）
```

### 7-E EOD/LB 窗（独立小剧本）

```
15:40 起：读 LB 前排 strike → 判洗位方向（「10 and 15 could get shaken」06-08）
触发：1m 形态（1m vom / 1m 21/200 cross）+ MOC 数据时点
出场：翻倍即卖大半，runner 允许归零（07-20）
```

---

## §8 反模式（他从不做的事）

1. 从不给 R 倍数/百分比目标——一切目标与风险用具名位（0/58；07-10「with PDC risk」）。
2. 从不无位入场（例外均被自评错误或标 YOLO）。
3. 从不摊平亏损——「Took the L!」后可全新再进（06-03）。
4. 从不追展开的行情（08-03、06-22、07-15、07-01）。
5. 从不预测宏观（06-10「Not a macro expert so I'll just trade the chart」；05-31「Trade the charts not our hearts」）。
6. 从不在预定事件前开仓（08-04、06-17）。
7. 从不容忍绿转红（07-09、06-15）。
8. 从不在已识别的 chop 里硬做（07-17 零交易日）。
9. 从不公开仓位金额——只有定性词与比例阶梯（06-18「Size appropriately」）。
10. 从不按 IPO 发行价接盘（06-11 SPCX「lack of board control sounds like a bad idea」）。
11. 从不在缺席/情绪日勉强交易（06-25、07-30）。
12. 从不让单一指标凌驾晨报剧本（06-05 忽略 PO 按计划做）；反之单一 GG open 也不够（08-03）。
13. 从不在 hourly 尝试 bullish expansion 时做 3m 逆势背离（07-01 明文回避条款）。
14. 从不持仓过重大不确定性（06-17「Didn't hold anything for MOC」）。

---

## §9 硬规则 / 软倾向汇总

| 编号 | 规则 | 频次 | 例外 |
|---|---|---|---|
| H1 | 晨报必含 VIX key level | 33/33 | 无 |
| H2 | 晨报双 strike 对 | 32/33 | 06-15 |
| H3 | 无位不入 | ~50/58 | 语料缺口或自评错误 |
| H4 | 入场=晨报分支兑现；剧本>单指标 | 贯穿 | 无 |
| H5 | 事件门 | 3+ 明文 | 06-03 违反→受罚 |
| H6 | 不追高 | 6+ 明文 | 08-03 回踩后与社群补进（等回踩后进不算追） |
| H7 | Level-to-level、零 R 语言 | ~30 笔/0 笔 | 无 |
| H8 | 反向信号即走 | 4+ | 无 |
| H9 | 绿转红零容忍 | 3+ 明文 | 无 |
| S1 | 双向 if-then | 27/33 | 6 次姿态声明日 |
| S2 | Free-trade 阶梯 1/2→2/3 | 3+ 明文 | 快速全出型（06-08、07-31） |
| S3 | Runner+移止损、容忍归零 | 5+ | 06-17 MOC 前不留仓 |
| S4 | 开盘窗主战 | ~22 天 | 06-02 午间、07-07 午后一击、06-08 仅 EOD |
| S5 | 中午收工 | 多数日 | 07-09 全天趋势持仓、06-04 午后活跃 |
| S6 | OPEX 轻仓 | 07-17 零交易 | 06-18 仍做午后一笔 |
| S7 | GG complete 主兑现 | 6+ | 位链目标优先时按位兑现 |

---

## §10 语料缺口与置信度

- 晨报缺失日（06-02/06-04/07-09/07-16/07-22/07-29 等）多为**采集缺口而非确证无晨报**——07-16 有「Morning plan worked great today」反证当日实有晨报。
- 战果均为本人自述；07-30 明言「A lot of the scale outs were not placed on here for clarity」——出场梯明细存在系统性欠记录，X 节阶梯为下限刻画。
- 两处时间换算不一致已按 RAW 时戳为准（07-16 EOD 图 BY_DAY 标 14:32 ET，RAW 3:32PM PT=18:32 ET）。
- 本规范 v1 冻结于 2026-08-09；新增语料（SATY_WEEK_2026-08-05_07 起）应走 v2 增量校订，不回改本版频次。