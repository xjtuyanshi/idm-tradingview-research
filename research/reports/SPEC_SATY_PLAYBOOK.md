# SPEC — Saty 完整交易剧本（playbook）还原

> 任务：搞清楚 **Saty Mahajan 到底怎么做决策**，而不是他用什么指标。
> 日期：2026-07-25。作者：research agent（方法论重建线）。
> 本文不含任何回测、不含任何参数搜索、不含任何"新发现"。它是一份**来源分级的规格书**。
> 配套可复现脚本：`research/saty_playbook_data_gap_check.py`（只做数据盘点，不做统计）。

---

## 0. 怎么读这份文档（证据分级，强制）

我们上一次失败的根因之一是**把推断当成事实**。所以本文每一条都带标签：

| 标签 | 含义 | 可信度 |
|---|---|---|
| **[A]** | Saty 本人**公开可核**的原话/原文（X 推文、TradingView 脚本说明、GitHub 仓库描述、他署名的 PDF） | 最高。外部审查者可自行打开链接 |
| **[B]** | Saty 本人在**付费 Discord** 里的原话，已由本仓库此前逐字记录（`docs/SATY_RIPSTER_METHOD_STUDY.md`） | 高，但**外部不可核**。单一转录源 |
| **[B-p]** | Discord 内容的**转述/脱敏**（`docs/SATY_OBSERVATIONS_2026-07-21.md` 明确声明是 paraphrase，不含原文） | 中。**这不是他的话**，是我们的复述 |
| **[C]** | 第三方描述（社区脚本作者、论坛、搜索引擎对 PDF 的摘录） | 中低。可能已经变形 |
| **[D]** | **我的推断**。凡此标签，都是我从上面几档拼出来的，不是任何人说过的 | 最低。**必须被当成假设对待** |

⚠️ 一个必须先说的事实：**关于"他到底怎么下单"，公开网络上几乎没有可核材料。**
他的 satyland.com、TradingView 脚本页、GitHub README **全部只描述指标功能，不描述交易规则**
（FAQ 页全是"线被压扁了怎么办"这种）。我逐个抓过 satyland 首页 / atrlevels / pivotribbon / faq、
TradingView 三个脚本页、GitHub profile、useThinkScript 主帖，**均无入场/止损/仓位规则**。
真正含方法论的是三类：①他每天公开发的 Day Trade Idea 推文（[A]，本次最大收获）；
②他署名的 PDF《My Trading System》（[A]，但只能通过搜索摘要拿到片段，全文在付费墙后）；
③付费 Discord（[B]，只能靠本仓库已有的转录）。
**因此本文第 1、5、6 节证据较硬，第 4 节（止损）证据最软——那恰恰是我们最需要的一节。这一点必须诚实标出。**

---

## 1. 盘前流程

### 1.1 核心发现：他的"双向 if-then 剧本"有一个**固定模板**，而且是**公开的**

此前仓库只有一个 Discord 的 NVDA 例子 [B]。本次在 X 上找到**大量同格式的公开原文**，
可以把模板钉死。他每个交易日盘前（美东约 08:30–09:20）发一条 `Day Trade Idea` 推文。

**逐字模板**（结构取自 6 条真实推文的交集，字段名是他自己的用词）[A]：

```
Day Trade Idea: $SPX | $SPY            ← 标的对（指数 + ETF 双写）
Upside:   SPX <strike>c | SPY <strike>c   ← 看涨路线要买的期权（行权价，不是价位）
Downside: SPX <strike>p | SPY <strike>p   ← 看跌路线要买的期权
VIX <number> key level                    ← 当日 VIX 的分水岭

<1–3 句盘前语境>                          ← 隔夜发生了什么、现在贴着什么位、有无压缩

- If <条件 A>, <目标位 1> and then <目标位 2>.
- If <条件 B>, <目标位 3>, and then <目标位 4>.
```

**一条完整原文示例**（2026-07-09，公开推文，可自行核对）[A]：

> Day Trade Idea: $SPX | $SPY
> Upside: SPX 7530c | SPY 750c
> Downside: SPX 7470p | SPY 744p
> VIX 16.5 key level
> - If we get continuation over long trigger and pre-market highs, we can head back toward the
>   SPX daily trendline / SPY 750 and then the midrange.
> - If we get a breakdown of H21 (ETH) and lose PDC, we can visit overnight lows, and then the short trigger.
>
> — https://x.com/satymahajan/status/2075210819596394531

其余可核的同格式样本（片段，链接均可打开）[A]：

| 日期/链接 | 语境段要点 | A 路线条件 → 目标链 | B 路线条件 → 目标链 |
|---|---|---|---|
| [2061433201474580684](https://x.com/satymahajan/status/2061433201474580684) | gap up 后横盘；盘前守住周五 resistance 的 s/r flip | hold pre-market support → **golden gate** → 760 → midrange | lose pre-market support → PDC → 周五下方 demand |
| [2060347871971393755](https://x.com/satymahajan/status/2060347871971393755) | 隔夜上漂 + 盘前区间 = **10m compression**；已到 **+1 Monthly ATR**（周一就是这么说的目标） | breakout of long trigger resistance → +50% ATR / 7600 → midrange | （截断） |
| [1999480394349961518](https://x.com/satymahajan/status/1999480394349961518) | — | recovery of previous close **且** break of pre-market range → overnight highs / ATH | trend break → pre-market lows |
| [2009264987374502245](https://x.com/satymahajan/status/2009264987374502245) | — | hourly downside continuation → overnight lows → 6900 test | recovery of 昨日 LOD → … |
| [2074471222432129447](https://x.com/satymahajan/status/2074471222432129447) | 价格 **in the trigger box**，hourly + 10m 双压缩 | — | — |
| [2043659087762571761](https://x.com/satymahajan/status/2043659087762571761) | 隔夜 gap down **略小于 0.5 ATR**；VIX 重回 20 上方"如预期" | — | — |

### 1.2 从模板里能读出的硬结论

1. **每天固定两条路线，不多不少。**（没有"第三种可能"，没有"观望"作为一条路线。）[A]
2. **条件永远是"价格与某个具名对象的关系"**，不是指标数值。
   已出现的条件对象：long/short trigger（±0.236 ATR）、pre-market high/low、
   PDC（前收=ATR 锚）、H21(ETH)、昨日 LOD、trend（ribbon 结构）、hourly continuation、
   pre-market range。**没有一次是"RSI 超买"这类。**[A]
3. **目标永远是链式的具名位，且至少两级**（"toward X **and then** Y"）。[A]
   这解释了为什么他能分批：目标 1 减仓，目标 2 再减。
4. **两条路线的条件互为镜像**：A 路线是"守住/突破"，B 路线是"丢失/跌破"，
   而且 **B 路线的触发条件往往就在 A 路线入场位的下方一点**。[A]
5. **他给的是期权行权价，不是股价目标。**`Upside: SPX 7530c` 是"如果走 A 路线我买这张"。
   → 他的计划单位是**一笔可执行的交易**，不是一个方向观点。[A]
6. **VIX key level 是每日必填字段。**这是我们此前完全没注意到的一个环境闸门。[A]
7. **盘前语境段几乎每天都提"我们离锚多远（用 ATR 度量）"和"有没有压缩"**：
   "gapped down overnight a little less than 0.5 ATR"、"pre-market range setting up some
   10m compression"、"in the trigger box with hourly and 10m compression"。[A]

### 1.3 他盘前画/看的东西（工具层）

四件套固定：**ATR Levels + Pivot Ribbon + Phase Oscillator + Volume Stack**，
模板 `Day 3/10` = 3m(ETH) 图 + Day 模式 ATR 位 + **10m Pivot Ribbon 用 TimeWarp 叠上去**。[B]
（TimeWarp 功能在他自己的脚本说明里可核："Warp the Ribbon into a different timeframe than the chart" [A]。）

盘前还会看的**非图表**输入 [A，来自 PDF 片段]：
- **流动性在哪**——"Focus on the central banks and focus on the movement of liquidity"
- **关键位与枢轴**——"Find key levels and pivots. Look for it to make any breakout or breakdown moves"
- **板块 ETF 广度**——"The more sectors trending in a direction, the higher the probability of the
  market trending the same direction"
- **日历**——"Time is critical to trading. Understand important times and interesting events
  throughout the day, week, month, quarter, and year"

### 1.4 [D] 我的推断：这个模板真正的功能是什么

**推断（未经验证）**：这个格式的作用不是"预测"，而是**在情绪未启动时把两条路线的
入场、目标、失效全部写死**，从而让盘中只剩一个动作——认领哪条路线被触发了。
他 PDF 里那句 "Don't over-analyze. Don't procrastinate. Don't hesitate. If you do, you will lose." [A]
与这个格式是配套的：盘前把思考做完，盘中只做识别。

**这对我们的直接含义**：我们要生成的不是信号，是**这张纸**。用户说"从图表里看不到任何
有用的价值"——他要的就是这张纸上的东西：现在在哪两个具名位之间、A 路线的条件与目标链、
B 路线的条件与目标链、以及每一段的历史基准率。

---

## 2. 入场：他明确描述过的所有入场情形

按证据强度排序。**注意：没有任何一条是"某指标发出买信号"。**

### E1 — trigger 位（±0.236 ATR）的突破/延续 [A]
- 他自己的脚本说明：`trigger clouds for possibly going long/short @ 23.6 fib`，
  `Put and call trigger idea levels`。[A]
- 推文条件用语："continuation over **long trigger** and pre-market highs"、
  "breakout from **long trigger** resistance"、"in the **trigger box**"。[A]
- **注意"trigger box"这个词**：±0.236 之间是一个**盒子**，盒内=无倾向。
  这与仓库 V12 研究记录的"±23.6 之间=无倾向区"一致。[A/C]

### E2 — Golden Gate（穿过 0.382）[A]
- 他的公开表述：**price crosses 38.2% → 60%+ 概率到 61.8%**；
  他自己的视频标题/描述把它定位为 "can help you **stay in a trend trade**"，
  并说 "uses the ribbon to add conviction with trend"。[A]
- **关键**：他从没说"触到 0.382 就买"。Discord 的 NVDA 原文是
  「**In 10m continuation** can look for a **GG completion** using 207.5c or 210c」[B]
  ——前提是 10m 延续，GG 是**去哪里**。
- 与本仓库 `GOLDEN_GATE_REPRODUCTION_2026-07-24.md` 的结论一致：GG 是目标/概率层。
- 他还公开把概率工作归功于第三方：让人给 @tesrak 买杯咖啡 [A]
  （https://x.com/satymahajan/status/1836777825015119930）——即**基准率不是他造的，是引用的**。
  这正是我们要学的姿态。

### E3 — Vomy / Yummy（Pivot Ribbon 结构反转）[C + B]
- **Vomy 定义（第三方，标注"based on concepts by Saty Mahajan"）**[C]：
  10m 图上 ribbon 处于**清晰的粗趋势**（thick trend）→ 价格回撤，ribbon 形成 **"Dolphin"** 形状
  → **10m 的 48EMA 被击穿** = 入场信号，含义是"趋势正在破"。
  来源：https://www.tradingview.com/script/DS4RZxw2-Cash-Saty-Vomy-STRATEGY/
- 48EMA 的身份可核 [A]：他自己的 Pivot Ribbon 有 **13/48 Conviction EMAs**，
  Conviction Arrows = 13/48 交叉。所以"48EMA 破"= conviction 翻转，是他自己的部件。
- Discord 用法可核 [B]：「look for a **10m Vomy** down to PDC and then toward 200 key support」
  ——**Vomy 是入场结构，PDC/200 是目标**。
- **Yummy = Vomy 的多头镜像** [D 推断]。仓库术语表写 "Yummy/Vomy = Pivot Ribbon 的多头/空头
  结构态" [B]，但**没有任何来源给出 Yummy 的逐条定义**。不要假装我们知道。
- ⚠️ 第三方脚本自己声明的局限（值得抄进我们的免责）[C]：它不处理附近的支撑阻力
  （会导致假突破），也不处理 FOMC/联储讲话这类事件。

### E4 — Bilbo Box（压缩突破）[B]
见 §7 完整定义。**这是唯一一个他把"止损放哪"说死了的 setup。**

### E5 — 双周期扩张态 + 具名位（他 2026-07-24 本人实盘那笔）[B]
Discord 原话链：
> 11:37 「3m extreme here. 10m has room, but maybe some consolidation, pullback possible」
> 11:47 「I think this bounce here with 3m extreme **at demand/support** makes a lot of sense.」

解码 [B 原话 + D 结构解读]：
- **3m 极端 + 10m 尚有空间 → 判定为整理/回撤，不是反转**（两个周期都极端才是反转候选）[D]
- **必须"极端"与"具名的 demand/support"重合**才构成理由；单独任一个都不是 [B，他自己
  在句子里把两个条件并列]
- 他自己把这类归为**短打/减仓级别**，当天说完就 "I'm going to call it here" 收工 [B]

### E6 — 盘前区间 / 隔夜位的突破与夺回 [A]
推文条件原文：`break of pre-market range`、`recovery of previous close`、
`hold pre-market support`、`continuation over ... pre-market highs`、`recovery of the yesterday LOD`。[A]
**这是他公开剧本里出现频率最高的一类条件**，比 GG 还高。
⚠️ 我们**目前算不出来**（见 §8），这是最大的实现缺口。

### E7 — 压缩解除（compression → expansion）[A]
推文语境段反复出现 `10m compression`、`hourly and 10m compression`、
`pre-market range setting up some 10m compression`。[A]
压缩本身是 Phase Oscillator 的一个部件（布林 21/2.0 收进 2.0×ATR 通道=压缩，1.854×ATR 解除，
滞回双阈值）[C，来自仓库对源码的读取]。E4 和 E7 很可能是**同一件事的两种表述** [D]。

### E8 — 动能 + 旗形回踩进 ribbon [A]
一条公开推文原话极短但信息密度高：`Momo + Bullish flag into ribbon = 🤌`
（https://x.com/satymahajan/status/2044060690269282717）。[A]
即：**动能确认 + 回踩到 ribbon（8/21/34 带）内的旗形整理 = 他认可的顺势入场**。

### E9 — [D] 我从 E1–E8 里抽出的公共结构（**这是推断，不是他说的**）

> **入场 = 位置（具名位）× 状态（ribbon 趋势 / phase 扩张度 / 压缩）× 触发（价格对该位做出动作）**
> 三项缺一不可。

支持这个抽象的证据：E5 他把"极端"与"at demand/support"并列；E2 他把 GG 挂在
"in 10m continuation"下面；E3 Vomy 要求"ribbon 清晰粗趋势"再等 48EMA 破；
E6 条件全是"价格 vs 某个具名区间"。
**但请注意：他本人从未写下这条公式。** 它是我为了让我们能编码而做的归纳。
如果要用它，必须当成待检验假设，不能当成"Saty 的规则"。

---

## 3. 目标怎么定

### 3.1 规则（证据较硬）
- **目标永远是"下一个具名位"，并且成链**：`toward X and then Y`。[A，6/6 条推文都是这个句式]
- **具名位的完整菜单**（他推文里真实出现过的）[A]：
  ATR 梯位（long/short trigger ±0.236、golden gate 0.382、**midrange**、0.618、
  `+50% ATR`、`+1 Monthly ATR`）、PDC、pre-market high/low、overnight high/low、
  昨日 HOD/LOD、整数心理位（`SPY 750`、`SPX 6900`、`SPX 7600`）、
  H21(ETH)、日线趋势线、ATH、s/r flip（昨日阻力翻支撑）。
- **多周期 ATR 梯位是活的**：他会用 **Monthly / Quarterly ATR Levels**（Position Mode）
  给日内定目标（"+1 Monthly ATR, which we were looking for as a target Monday" [A]；
  "4H chart for $SPX Quarterly ATR Levels (Position Mode) That Golden Gate is still open" [A]）。
  → **GG 不只是日内概念，他在多日/波段/季度尺度上同样用**（"Multiday Golden Gate complete"、
  "Swing Golden Gate complete" [A]）。
- **他自己给 ATR Levels 的一句话定位**（GitHub 仓库描述，可核）[A]：
  > "…find levels useful for **scaling in and out of trades**."
  **注意 scaling IN**：位不只是出场目标，也是**加仓点**。
- **0.618 与 ±1 ATR 是分批止盈点；range ≥90% 后只剩均值回归** [C，来自仓库 V12 对其材料的整理，
  非本次可核原文]。`Range against ATR` 读数确实是他脚本的内建字段 [A]。

### 3.2 [D] 推断
目标链的第一段通常是"回到 A 路线被否定前的那个位"，第二段才是扩张目标。
这与他 "scale out here / can leave runners" [B] 的两段式出场对应：T1 = 链上第一位，
runner 交给第二位。**未验证。**

---

## 4. 止损放哪 —— ⚠️ 本节证据最弱，请特别小心

### 4.1 唯一一条他说死了的（Bilbo Box）[B]
> 区间本身就是止损位；"该区间可用于**加仓与风险管理**"。
即：**结构给出止损，不额外发明 ATR 缓冲。**

### 4.2 他公开剧本里止损是**隐式**的 [A + D]
关键观察 [A]：他从不写 "stop at X"。他写的是**另一条路线的触发条件**：
> A：If we get continuation over long trigger and pre-market highs → …
> B：If we get a breakdown of **H21 (ETH)** and **lose PDC** → …

**[D] 我的推断（重要，且必须被检验）**：
> **A 路线的失效条件 ≈ B 路线的触发条件。**
> 也就是说，止损不是一个数字，而是**"剧本翻页"事件**——当 B 路线的条件成立，
> A 路线的持仓就不该存在了。

这个推断有两个可直接检验的后果（见 §9-P4），**在检验之前不要写进任何执行代码**。

### 4.3 我们此前记录的"止损"来源必须澄清
- 仓库 `IDM_V12_RESEARCH_RIPSTER_SATY_2026-07-22.md` 里的
  「**保本陷阱：浮盈 ≥ +1R 前不动初始止损**」标注为"多来源一致"——
  **那是通用交易研究的结论，不是 Saty 说的。** 本次公开检索**没有找到**任何
  Saty 关于"止损不动 / 不提保本"的原话。
- 用户问"有没有'止损不动'的说法"：**答案是——在可核的公开材料里没有，
  在本仓库转录的 Discord 材料里也没有。** 这条要么去 Discord 补证，要么不要用他的名义说。
- 同理：`Ripster` 的"10m 收盘跌破 5-12 云就出场"是 **Ripster 的**结构出场，不是 Saty 的。[C]

### 4.4 我们自己已经证明的一条负面知识（本仓库原创，非 Saty）
`GOLDEN_GATE_REPRODUCTION_2026-07-24.md`：0.382 入场 + 0.236 止损会洗掉 **33%** 的赢单
（赢单最深回撤中位 0.303 ATR）。→ **把止损放进 0.236 是错的**，即使它是个具名位。
**具名位不等于合适的止损位。** 这条要写进我们的规则里。

---

## 5. 仓位与减仓

### 5.1 分批与 runner [B]
> 「Can leave runners, **good scale out here**」
→ 明确的**分批止盈 + 保留 runner** 结构。仓库现有的 T1/T2/runner 与之同构。

### 5.2 月度节律（**[A]，来自他署名 PDF，本次新增，此前仓库完全没有**）
> The month has a cadence:
> - 月初：**更激进**（例：0–90% invested）
> - 月中：**放慢**（例：0–50%）
> - 第三周：**大幅放慢**（例：0–25%）
> - 月末：**重新加码**（例：0–50%）

这是**账户级仓位调度**，不是单笔仓位。我们完全没有这一层。

### 5.3 时段节律 [A，同一 PDF]
> 09:30–11:30 与 15:00–16:00 通常是理想交易时段（开盘小时高量，power hour 有量能加成）。

**与 tesrak 的 GG 时间衰减表方向一致**（开盘触发 ~91%，15:00 后 9%），
也与我们自己的复现一致。→ **两个独立来源支持"时段不是均匀桶"**。
我们 v13 的 09:30–14:00 一刀切同时违背了这两条。

### 5.4 标的筛选 [A，同一 PDF]
> 只做高流动性的股票或指数：**tight spread、good volume、good interest**。
他公开说过 SPX/SPY 一辈子只做这个也够（"less is more; focus is underrated"）[C]。

### 5.5 收工纪律 [B]
> 「I'm going to call it here」——**主动宣布当日结束，不追加交易。**

### 5.6 他不给的东西（诚实标注）
**没有任何可核来源给出：单笔风险百分比、止损宽度、R 倍数目标、每日最大亏损、
连亏停手规则。** PDF 全文在付费墙后（Course Hero / Course Sidekick，均 403），
我只拿到搜索摘要片段。**不要编造这些数字。**

---

## 6. 反面清单 —— 他明确说过不要做什么

> 这一节对我们最重要：我们犯过"为了信号而信号"的错。

**来自他署名的 PDF（可核片段）[A]：**
1. **Don't over-analyze. Don't procrastinate. Don't hesitate. If you do, you will lose.**
2. **You don't predict or speculate.** You **analyze, react, and trade.**
3. **Be yourself. Don't try to be someone else.**
4. 不做流动性差的东西（spread 不紧、量不够、interest 不够的一律不碰）。
5. 不要不一致：「stick to your trading system and make the same type of trades over and over again」。
6. 不要不耐心：「Be patient. Wait for your setups **and the trend to be in your favor**」。
   → **趋势不站在你这边时，setup 本身不成立。**

**来自他自己的指标说明 [A]：**
7. **指标单独不构成决策**：
   > "this indicator is most beneficial when you **combine it with price, volume, and trend analysis**"
   → 他本人明确说 ATR Levels **不是**一个信号系统。

**来自 Discord [B]：**
8. **单一条件不是信号**：3m 极端本身不是信号，到支撑本身也不是信号，**必须重合**。
9. **两周都很难做的时候要承认**：「Last two weeks have been on hard mode」——
   **行情本身可以是不可做的**，这不是执行问题。
10. **做完就收工**（§5.5）。

**来自我们自己的转述记录 [B-p，注意这不是他的原话]：**
11. 背离不是做空理由（背离先用于管理已有多单，等价格结构真的坏了再说）。
12. 追已经走远的行情：趋势有效 ≠ 现在是好入场（"a valid trend can coexist with a poor new entry"）。
13. 没有新的 BUY ≠ 禁止做多（缺信号不等于反向信号）。

**来自第三方对 Vomy 的实现说明 [C]：**
14. 不处理附近 s/r 会导致假突破；事件日（FOMC / 联储讲话）setup 可能直接失效。

**来自 Bilbo Box 原话 [B]：**
15. **时间框架越低假突破越多**（"时间框架越高假突破越少"）→ 3m 上做压缩突破要格外谨慎。

**我们自己踩过、他没说但必须并列的 [本仓库]：**
16. 不要把具名位当止损位就以为安全（§4.4）。
17. 不要在没有基准率的东西上做参数搜索（v11/v12 教训）。

---

## 7. Bilbo Box — 完整定义

**唯一来源：Discord #lessons 2026-05-07，本仓库逐字记录 [B]。公开网络零结果**
（我搜过 "Saty Bilbo box compression breakout"，只返回 Pivot Ribbon 的 Bias/Compression Candles，
**没有任何公开材料提到 Bilbo Box**）。**这是单点来源，外部审查者无法核验，必须标注。**

### 7.1 他给的流程 [B]
1. 找 **5 根压缩蜡烛**。
2. **提前扩张则提前定型**：若第 5 根之前就出现扩张，就用**已成形**的区间——
   只有 4 根压缩第 5 根扩张，就用 4 根的区间；3 根同理。
3. **持续标记这些蜡烛的高低点**，区间成形过程中**随时更新**。
4. 5 根之后（或提前扩张时），**区间被突破即产生入场机会**。
5. **该区间可用于加仓与风险管理**（= 区间边界即止损，不另算 ATR 缓冲）。
6. **突破后接扩张能产生很好的交易。**
7. **时间框架越高假突破越少。**

### 7.2 形式化（可编码版本）[D 推断部分已标注]

```
输入: bars（某一执行周期）, N_MAX = 5
状态: box = None

对每根收盘 bar i:
    若 box 为空:
        用 bar i 起一个候选盒: hi=high[i], lo=low[i], k=1
    否则:
        若 is_expansion(bar i):                 # ← 定义缺失，见 7.3
            若 k >= K_MIN: 盒子定型（不含 bar i），进入 ARMED
            否则: 丢弃，重新起
        否则:
            hi = max(hi, high[i]); lo = min(lo, low[i]); k += 1
            若 k == N_MAX: 盒子定型，进入 ARMED

ARMED 状态:
    入场 = 价格突破 hi（做多）或 lo（做空）
    止损 = 盒子对侧边界（lo 做多 / hi 做空）        # [B] 他明说区间用于风险管理
    加仓 = 盒内回踩（他说区间可用于加仓）            # [B] 但加仓的具体触发未定义 [D]
    目标 = 下一个具名位                              # [B，Vomy/GG 同构；具体哪一个未定义 [D]
```

### 7.3 **定义缺口（必须诚实列出，不要用猜测填）**
| 未定义项 | 状态 |
|---|---|
| "压缩"的**量化定义** | ❌ 他没说。候选：Phase Oscillator 的压缩判定（布林21/2.0 收进 2.0×ATR，1.854×ATR 解除）[C]；或纯目视窄幅。**[D] 我倾向前者，因为压缩本来就是他自己指标里的部件，且他推文里的 "10m compression" 大概率就是指这个** |
| `K_MIN`（最少几根才算数） | ❌ 他举例到 3 根，未说 2 根算不算。**[D] 取 K_MIN=3** |
| "扩张"的量化定义 | ❌ 未定义。[D] 候选：该 bar 真实波幅 > 盒内 bar 波幅中位数 × c，或压缩状态解除 |
| 突破要**收盘确认**还是**触及即算** | ❌ 未定义。**这个选择会改变一切结论**，必须作为显式开关并两种都报 |
| 是否需要**回踩确认** | ❌ 未定义 |
| 目标位怎么选 | ❌ 未定义（只说"下一个具名位"是我们的归纳） |
| 盒子的**最大宽度**上限 | ❌ 未定义。宽盒 = 止损巨大，风险回报可能不成立 |
| 一天允许几个盒子 | ❌ 未定义 |

⚠️ **警告**：上表有 8 个自由度。**如果我们对每个自由度做网格搜索，就是又一次 880 统计量事件。**
正确做法：**每个自由度先用最保守/最自然的默认值预登记，只报这一个格子**；
若确实要看敏感性，必须把格子数写进报告标题。

---

## 8. 我们现在能实现多少（可复现的缺口盘点）

脚本：`research/saty_playbook_data_gap_check.py`，输出如下（2026-07-25 实跑）：

```
hourly: n=5090  2023-08-25 -> 2026-07-24   bar times 09:30..16:00
        pre-09:30 buckets: NONE   post-16:00 buckets: NONE
5m    : n=4681  2026-04-29 -> 2026-07-24   pre-09:30 buckets: NONE
```

| 剧本输入 | 有？ | 说明 |
|---|---|---|
| PDC / 锚 | ✅ | `DayLevels.anchor` |
| Day 模式 ATR 梯位 | ✅ | `levels.build` |
| 昨日高/低 | ✅ | `.prev_high / .prev_low` |
| **隔夜高/低** | ❌ | 缓存里**没有任何 09:30 之前的 K** |
| **盘前高/低** | ❌ | 同上 |
| **盘前区间突破** | ❌ | 同上 —— 而这是他公开剧本里**最高频**的条件（§2-E6） |
| H21 (RTH) | ✅ | `indicators.ribbon(hourly)` |
| **H21 (ETH)** | ❌ | 他推文里写的是 **ETH**；我们只有 RTH。**数值不同，不能冒充** |
| D21 / W21 | ✅ | 日线 ribbon / 周线重采样 |
| **13/48 Conviction EMAs** | ❌ | `indicators` 只暴露 8/21/34。Vomy 判定要 48 |
| **周/月/季 ATR 梯位** | ❌ | `levels.build` 只有 Day 模式；他日内会引用 +1 Monthly ATR |
| **VIX key level** | ❌ | data 模块无 VIX |
| **板块 ETF 广度** | ❌ | 无数据 |
| 整数心理位 | ⚠️ | 好推导，但"哪个整数算数"是自由裁量 |
| 日线趋势线 | ❌ | 手画对象，不可自动化 |
| Phase Oscillator | ✅ | `indicators.phase_oscillator / phase_zone` |
| 压缩检测 | ❌ | `indicators` 里没有压缩判定（Phase 的布林压缩未实现） |

**分辨率天花板**（同一脚本输出，也是纪律条款 5 的落地）：
- 日线 20y：日内谁先到，**不可知**
- 小时线 730d：一根 1h K 的振幅通常大于整个止损距离，**"谁先到"不可判定**
- **5 分钟只有 60 个交易日**：这是唯一能判路径的数据，**n 必然很小，任何路径结论必须标注**

### 8.1 [D] 优先级建议
1. **补 ETH（盘前/隔夜）数据** —— 没有它，他公开剧本里最高频的一类条件我们一条都做不了。
   这比再补任何指标都重要。
2. **补 13/48 conviction EMA + 压缩判定** —— Vomy 与 Bilbo Box 的前置件。
3. **补多周期 ATR 梯位（周/月/季）** —— 目标链经常跨周期。
4. VIX 与板块广度 —— 环境闸门，优先级低于上面三项但他每天都写。

---

## 9. 可证伪的命题清单（下一步该测什么，以及怎么测才不作弊）

> 全部遵循仓库纪律：Wilson 区间 + n、条件筛选做两比例检验、0R 不算亏、
> 路径类只在 5m 上做且标注 n、格子数必须报告。

**P1（最高价值，最贴近他的认识论）——位到位的条件转移矩阵。**
他公开引用的是"level-to-level 条件概率"，不是信号胜率。
产出应该是一张表：**给定 t 时刻价格首次触及位 L_i，当日随后触及 L_j 的概率**，
L ∈ {−1.0, −0.618, −0.5, −0.382, −0.236, 0, +0.236, +0.382, +0.5, +0.618, +1.0}，
按**触发时刻分层**。这不是择优——它是**穷举报告**，没有"最优格子"可挑。
GG（0.382→0.618）只是这张表里的一格，我们已经验证过它对得上，
**这给了整张表可信度**。日线 20y 可做"当日是否触及"，无需路径。

**P2 —— ribbon 状态是否对目标概率做功？**
对 P1 的每一格，加条件 `10m/hourly ribbon = bull_trend`，做 `two_proportion_z`。
**若 z < 1.96，明说"这个条件没有做功"**，不许因为点估计变好就宣称有效。
（参考：hourly ribbon 状态分布 bull 46.9% / bear 26.0% / conflict 13.7% / in_ribbon 13.3%，
样本充足，这个检验做得起来。）

**P3 —— 时段分层是否真的必要？**
把 P1 按 09:30–11:30 / 11:30–15:00 / 15:00+ 三段（他 PDF 的时段划分，**预先指定，不搜索**）
做两比例检验。若显著，我们 v13 的 09:30–14:00 一刀切就被正式证伪。

**P4 —— [D] 那条推断的检验：「A 路线失效条件 = B 路线触发条件」是否可执行？**
测量**同一天两条路线都被触发的比例**（先破 +0.236 后又破 −0.236，或反之）。
- 若这个比例很低 → 剧本是"翻页"式的，止损=对侧路线触发是可行的。
- 若这个比例很高 → **剧本每天要被撕两次**，这种止损等于系统性双亏，
  那么真正的止损一定另有其物（可能就是 Bilbo Box 那种结构区间）。
这条**便宜、可用日线+小时线做、且能直接证伪我最核心的推断**。**建议第一个做。**

**P5 —— Bilbo Box。** 只能在 5m（60 天）上做，n 会很小。
必须**预登记** §7.3 的 8 个自由度的默认值，**只报一个格子**。
如果做敏感性分析，格子数写进标题。

**不要做的**：不要在 60 天 5m 样本上搜索止损参数（上次就是这么翻的车）；
不要把 P1 表里最高的那一格拿出来当"发现"。

---

## 10. 开放问题（需要用户去 Discord 补证的）

这些**只有付费社区成员能拿到**，我在公开网络确认无解：
1. **止损到底放哪？** 除 Bilbo Box 外，他有没有说过通用止损规则？
   有没有"止损不动 / 不提保本 / 保本时机"的说法？（§4.3——这是我们最需要的一条）
2. **单笔风险 / 每日止损 / 连亏停手**有没有明说过？
3. **Yummy 的逐条定义**（我们现在只有 Vomy 的第三方版本）。
4. **"压缩"的量化定义**——是不是就用他 Phase Oscillator 的布林压缩？
5. **减仓比例**——"scale out" 是减多少？1/3？1/2？
6. **VIX key level 怎么定出来的**（每天那个数字是怎么算/怎么选的）？
7. **Day Trade Idea 的事后标签规则**——`✅ Complete / ❌ Invalidated` 的判定标准是什么？
   （如果他公开记录成败，那就是一个**现成的、他自己维护的前向账本**，
   我们可以直接拿来当外部基准，这比我们自己造账本强得多。）

---

## 11. 一句话结论

**Saty 的"系统"不是一个信号发生器，是一张每日重写的纸：
两条互斥路线、每条路线用具名位写死入场条件与目标链、用另一条路线的触发当失效、
用历史基准率给概率、用月度/时段节律调仓位、用"call it here"结束一天。**

我们过去做的是第 4 层（发信号），而他做的是第 1 层（写纸）。
**下一步不是补指标，是补两件事：①能算出他剧本里那些位（尤其是盘前/隔夜位）；
②P1 那张位到位的条件概率表。** 有了这两件，那张纸就能自动生成，
用户才会在图上"看到有用的价值"。

---

## 附录 A：来源清单

**[A] Saty 本人公开可核**
- 每日 Day Trade Idea 推文（本文核心发现）：
  https://x.com/satymahajan/status/2075210819596394531 ·
  [2061433201474580684](https://x.com/satymahajan/status/2061433201474580684) ·
  [2060347871971393755](https://x.com/satymahajan/status/2060347871971393755) ·
  [2009264987374502245](https://x.com/satymahajan/status/2009264987374502245) ·
  [1999480394349961518](https://x.com/satymahajan/status/1999480394349961518) ·
  [2074471222432129447](https://x.com/satymahajan/status/2074471222432129447) ·
  [2043659087762571761](https://x.com/satymahajan/status/2043659087762571761)
- 归功 tesrak 的概率工作：https://x.com/satymahajan/status/1836777825015119930
- 多周期 GG：https://x.com/satymahajan/status/1834379918798364938 ·
  https://twitter.com/satymahajan/status/1895485538205045014
- 旗形入 ribbon：https://x.com/satymahajan/status/2044060690269282717
- TradingView 脚本说明：[ATR Levels](https://www.tradingview.com/script/Ty6CMBw9-Saty-ATR-Levels/) ·
  [Pivot Ribbon](https://www.tradingview.com/script/I4VXGe18-Saty-Pivot-Ribbon/)
- GitHub：[satymahajan](https://github.com/satymahajan) ·
  [saty_atr_levels 源码](https://github.com/satymahajan/saty_atr_levels/blob/main/Saty%20ATR%20Levels.pine)
- 官网：[satyland.com](https://www.satyland.com/) · [atrlevels](https://www.satyland.com/atrlevels) ·
  [pivotribbon](https://www.satyland.com/pivotribbon) · [faq](https://www.satyland.com/faq)
- 他署名的《My Trading System》PDF（**全文在付费墙后，本文片段来自搜索引擎摘要，未能读全**）：
  [Course Hero](https://www.coursehero.com/file/200502393/Satys-Trading-Systempdf/) ·
  [Course Sidekick](https://www.coursesidekick.com/economics/164329)（两站均返回 403）
- 视频（**均无法取得字幕/描述全文**，本文只用搜索摘要里的描述句）：
  [Golden Gate Strat](https://www.youtube.com/watch?v=d43HaLb765k) ·
  [Vomy Setup](https://www.youtube.com/watch?v=eYeUS5wRwKg) ·
  [Scalping SPX with Time Warp](https://www.youtube.com/watch?v=k8yKdDDqN-M) ·
  [Pre-market SPY Day Trade Plan](https://www.youtube.com/watch?v=9FtVMpKFZPs) ← **这条标题直接对应本文 §1，值得用户自己看**

**[B] Discord 逐字转录（仓库内，外部不可核）**
- `docs/SATY_RIPSTER_METHOD_STUDY.md` §1.1（图表模板）、§1.3（Bilbo Box）、
  §1.4（2026-07-24 实盘语言）、§1.5（NVDA if-then 与术语表）

**[B-p] 转述（明确非原话）**
- `docs/SATY_OBSERVATIONS_2026-07-21.md`

**[C] 第三方**
- Vomy 定义：https://www.tradingview.com/script/DS4RZxw2-Cash-Saty-Vomy-STRATEGY/
- useThinkScript 主帖：https://usethinkscript.com/threads/saty-atr-levels-for-thinkorswim.14648/
- 仓库 `research/reports/IDM_V12_RESEARCH_RIPSTER_SATY_2026-07-22.md`（对源码与教育站的整理）

**本仓库自有证据**
- `research/reports/GOLDEN_GATE_REPRODUCTION_2026-07-24.md`（GG 复现 + 几何不利）
- `research/saty_playbook_data_gap_check.py`（§8 的数据盘点，可复跑）

## 附录 B：抓取失败记录（供后人省力）

| 目标 | 结果 |
|---|---|
| YouTube 视频页/字幕（直接、youtubetotranscript、youtubetranscript、r.jina.ai） | 403 / 401 / 只返回导航栏 |
| x.com 单条推文正文 | 402 Payment Required（**但搜索结果的标题里带全文，可用**） |
| Course Hero / Course Sidekick（《My Trading System》PDF） | 均 403；只能靠定向搜索逐段套摘要 |
| Scribd（Saty ATR Levels PDF） | 只返回预览摘要，无规则内容 |
| ratemyfuru.com | DNS 解析失败 |
| satyland.com 各页 / TradingView 脚本页 / GitHub | 抓到了，但**只有指标功能，无交易规则** |
