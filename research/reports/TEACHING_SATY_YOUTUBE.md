# Saty Mahajan 本人 YouTube 教学的原话记录

**日期**：2026-07-25
**目的**：修补第一轮 SPEC_PIVOT_RIBBON 的致命缺口——"正片未取得逐字稿"，Yummy/Vomy 只能靠第三方博客猜。
**结论**：**逐字稿已全部取得**。第一轮的三个候选 Vomy 定义全部可以作废，作者本人有明确、可编码的定义。

---

## 0. 取回方式与证据等级说明

### 取回路径（任务给的 1-3 全部失败，第 4 类变体成功）

| 路径 | 结果 |
|---|---|
| 1. WebFetch watch 页 | 页面能拿到 `captionTracks[].baseUrl`，**但该 URL 现在返回 HTTP 200 + 空 body**（YouTube 已对 timedtext 加 PoT/proof-of-origin 门禁） |
| 2. InnerTube `/youtubei/v1/player` ANDROID | `FAILED_PRECONDITION`（需 attestation）。另试 IOS / WEB / MWEB / TVHTML5 / ANDROID_VR / WEB_EMBEDDED 六个 client，全部 `UNPLAYABLE` / `ERROR` / `LOGIN_REQUIRED` / 0 tracks |
| 3. 直接 GET `/api/timedtext` | 空 body（同路径 1） |
| 4. **yt-dlp 2026.07.04**（scratchpad 独立 venv）| **成功**。走 `android vr player API`，拿到 `en` 自动字幕 json3 |

**没有用第三方镜像站**，所以不存在"镜像站篡改内容"的污染风险；字幕直接来自 YouTube 自己的 ASR。

### 证据等级（本文档全程标注）

- **【原话】** = YouTube 自动字幕（ASR）的逐字输出，带视频内时间码。
- **【原话·ASR 有误】** = ASR 明显听错的专有名词，我按上下文修正并标出原始拼写。
- **【转述】** = 我的归纳，不是他说的。
- **【推论】** = 我从原话推出的、他没明说的东西。

**重要 ASR 提示**：ASR 把 "Vomy" 一律听成 **"vomi"**，偶尔听成 "wami / balmy / zombie / fomi / avami"。视频**官方标题**的拼写是 `The "Vomy" Setup`，所以 **Vomy 是作者的正式拼写**。下文引用保留 ASR 原文 `vomi`，读时按 Vomy 理解。

### 落盘位置

- 逐字稿（13 个视频，带时间码）：`/Users/lukegogogo/claude code projects/idm-tradingview-research/research/satylab/transcripts/<video_id>.txt`
- json3→带时间码文本 的转换脚本：`/Users/lukegogogo/claude code projects/idm-tradingview-research/research/satylab/j3_to_txt.py`

### 已取回的 13 个视频

| video_id | 上传日 | 标题 | 本轮价值 |
|---|---|---|---|
| `eYeUS5wRwKg` | 2023-04-25 | The "Vomy" Setup… | ★★★ Vomy 全定义 |
| `d43HaLb765k` | 2024-01-28 | The Golden Gate Strat… | ★★★ GG 入场/概率来源 |
| `QMJ_rg3phPA` | 2023-01-30 | Conviction Arrows and Time Warp | ★★★ 13/48、TimeWarp |
| `k8yKdDDqN-M` | — | Scalping/Day Trading SPX & SPY with Time Warp | ★★★ 0DTE 实操 |
| `h1CStzLuRrY` | 2022-05-22 | Pivot Ribbon Indicator Tutorial | ★★ dolphin 出处 |
| `9FtVMpKFZPs` | — | Making a SPY Day Trade Plan… Pre-market | ★★ 盘前计划里写 Vomy |
| `kTmQc5eZzzc` | — | ATR Levels Precision Levels, Extensions, Modes | ★ |
| `tGS2-KI1VUA` | — | ATR Levels Overview and Tutorial | ★ |
| `9NO3dyWej38` | — | Phase Oscillator Overview | ★ |
| `O1W7EHzkizs` | — | My Favorite Timeframes / MTF | ★ |
| `OP14Aee5au8` | — | Day Trading with ATR Levels + Ripster Clouds | ★ |
| `aTxbUec7rMo` | — | Ripster EMA Clouds Tutorial | ★ |
| `p51XpVttZy8` | — | Pivot Ribbon Bias Candles Quick Start | ★ |

---

## 1. Vomy 的精确定义

### 1.1 名字的来历（终结所有猜测）

> **【原话】eYeUS5wRwKg [1:11]**
> "…the elephant gets sick uh sort of vomits down some red candles and uh thus the vomit dolphin or vomi was created"

**【转述】** Vomy = **Vomit Dolphin（呕吐的海豚）**。ribbon 在大趋势里形状像海豚（背鳍 = 那几个高点），趋势末端"海豚吐了"，吐出红蜡烛。上游出处在 2022 年的 ribbon 教程里：

> **【原话】h1CStzLuRrY [18:36]**
> "…you can see this dolphin pattern uh emerges on the ribbon i've been noticing that it look always looks like a dolphin when it's about to when it has these big moves and it's about to then um flip"

**注意**：ASR 在 [1:11] 把 elephant 和 dolphin 混在一句里，是 ASR 的错乱（"elephant gets sick" 应为 "dolphin gets sick"）。**【推论】** 但不影响定义。

### 1.2 他自己的一句话总结

> **【原话】eYeUS5wRwKg [0:48]**
> "the vomi setup uh in a nutshell is effectively a EMA multi-ema crossover set up a reversal setup that is um fairly straightforward to see when you're using the pivot ribbon"

### 1.3 完整解剖（按他讲的顺序）

**前置条件 1 —— 必须先有清晰趋势、EMA 必须堆叠。答案是「是」。**

> **【原话】eYeUS5wRwKg [1:34]**
> "typically it'll happen when you have some nice clear Trend so you have stacked EMAs eight above 13 13 above 21 21 above 34 34 above 48"

→ 对应可编码条件：`EMA8 > EMA13 > EMA21 > EMA34 > EMA48`（看跌 Vomy 的前置态）。

**前置条件 2 —— 必须在某个位附近遇阻。答案是「是，但他讲得比条件更弱」。**

> **【原话】eYeUS5wRwKg [1:59]**
> "you'll get these moves up and then eventually you'll reach some form of resistance usually you'll get a double top or sometimes you'll even just get a Single Fin here where it'll just meet resistance"

> **【原话】eYeUS5wRwKg [2:22]**
> "you know you get clear trend forms these fins you meet resistance so at this point it's the 38.2 level"

**【转述】** 他要求的是"遇到某种阻力"（double top 或 single fin），**在他举的那个例子里**那个阻力恰好是 ATR 的 38.2 位。他**没有**把"必须在 ATR 位上"写成硬条件——是"some form of resistance"，ATR 位只是他的例子。这个区别对我们建模很关键：**位是可选的 confluence，不是必要条件。**

**触发序列（这是核心）**

> **【原话】eYeUS5wRwKg [1:59]**
> "and then you'll start to break down the 13 EMA the 8 and the 13 EMAs maybe even test down as far as the 21."

> **【原话】eYeUS5wRwKg [2:47]**
> "you'll get a breakdown of the 8 and the 13 a test of the 48 retest of the 13. and this retest of the 13 is often a really good spot to get in"

> **【原话】eYeUS5wRwKg [3:12]**
> "you'll get a break of the 48 in order to actually have a vomi be confirmed you have to get this break of the 48 it's a break and hold of the 48 confirms the move"

**独立交叉验证**（另一个视频里他反过来用"没发生 Vomy"来解释）：

> **【原话】d43HaLb765k [8:02]**
> "so we didn't get a vomi right vomi is break down at the 48 held the 48 Consolidated and then it broke out"

**【转述】** 解析这句：价格**守住了** 48 而不是跌破 → 所以"没有 Vomy"。**这句话是决定性的：Vomy 的定义硬绑在「跌破并守在 48 下方」上。**

### 1.4 ★ 与用户理解的偏差（本轮最重要的一条修正）

用户给的理解是：

> 「上涨时 cloud 是绿的；价格滞涨甚至微微向下时绿带越来越窄；**直到它变成红色的那一瞬间**」

**核对结果：方向对，但时点错了一整拍，而且错在"太晚"这一侧。**

> **【原话】eYeUS5wRwKg [3:59]**
> "as that's happening we start to get this multi EMA crossover where the 8 the 13 the 21 34 and the 48 all cross over each other and now form a bearish ribbon so **to anticipate that is what the vomi setup really does** right gives you the ability to anticipate a really really bigger than expected move"

**【转述】** 在 Saty 的框架里，**"带子变红"是 Vomy 的结果，不是 Vomy 的触发**。Vomy 这个 setup 存在的全部意义就是让你**在带子变红之前**进场。用户描述的"变红那一瞬间"，在他的序列里已经是第 5 步之后了——8/13 跌破（第 1 步）、13 回抽（第 2 步，他的首选入场）、跌破 48（第 3 步，确认）、48 下方站稳（第 4 步）、然后才是五条 EMA 全部交叉完成、带子转红（第 5 步）。

**【推论】** 用户观察到的"绿带越来越窄"确实对应他讲的东西，但他把窄带归到 consolidation/chop 那一类，而不是当 Vomy 触发器用：

> **【原话】QMJ_rg3phPA [4:45]**
> "you can see the EMAs are really thin so this is you know classic consolidation chop breaking through up and down through the the EMAs"

**这条对我们的意义**：第一轮那三个"几乎从不同时触发"的候选定义，很可能都锚在了**交叉那一刻**。作者本人锚的是**更早的 13 回抽 + 48 破位**。如果我们要测 Vomy，测点应该是 48 破位，不是 ribbon 变色。

### 1.5 Yummy 是不是镜像？—— 是镜像，但 **"Yummy" 这个词根本不是 Saty 说的**

> **【原话】eYeUS5wRwKg [5:32]**
> "and then the inverse is conceptually the same uh you know you get a move here a little fin meets support instead of resistance pulls back starts to break the 13. and you know potentially get a move to the other side"

> **【原话】d43HaLb765k [12:18]**
> "you know we got nice Trend you got an **inverse vomi** right ribbons flipping"

**【原话·检索证据】** 我对全部 13 份逐字稿 + 4 份视频描述做了大小写不敏感的全文检索，正则 `\b(yummy|yumi|yummi|gummy|jimmy)\b`：**命中 0 次**。而 `vomi` 命中 18 次（3 个视频）。

**【转述】** 所以：
1. 多头版**确实是空头版的严格镜像**（作者原话 "conceptually the same"、"inverse vomi"）。
2. 但作者**从不叫它 Yummy**，他叫它 **"inverse vomy"**。"Yummy" 是社区/第三方博客的造词。
3. **【推论】** 第一轮从第三方博客抄来的 "Yummy" 定义，其权威性等于零——连名字都不是原作者的。凡是基于"Yummy"检索到的定义细节，都应当降级到"第三方"证据等级。

### 1.6 可编码的 Vomy（看跌）——作者原意

**【转述】** 我把上面的原话翻成条件序列（这是我的转述，不是他的原话）：

```
S0 前置：EMA8 > EMA13 > EMA21 > EMA34 > EMA48   （clear trend, stacked）
S1 遇阻：价格在前高/双顶/single fin 处受阻      （可选 confluence：某 ATR 位）
S2 破位：收盘跌破 EMA8 与 EMA13（可下探 EMA21）
S3 入场A：回抽 EMA13 失败（第 1 次或第 2 次回抽）  ← 作者首选入场
S4 确认：跌破 EMA48 且「break and hold」（收盘站在 48 下方）
S5 入场B/C：48 破位当下，或 48 下方站稳后的下一次回抽
S6 结果：8/13/21/34/48 全部交叉，ribbon 转红      ← 不是触发器，是结果
```

**Confluence（他明说的加分项，不是必要条件）**

> **【原话】eYeUS5wRwKg [4:21]**
> "usually that'll be in Confluence with some sort of squeeze as well right and usually you'll be in sort of over bought or oversold conditions"

> **【原话】eYeUS5wRwKg [4:44]**
> "that's the ultimate scenario is when you have over uh bot conditions squeeze momentum moving to the downside you've got the break of the 13 retest of the 13 break of the 48"

---

## 2. Vomy 之后怎么做：入场 / 止损 / 目标

这是第一轮最缺的三样。作者对这三样的**明确程度是不对称的**：入场很具体，止损是"结构性的、由你的仓位大小决定"，目标是 ATR 位。

### 2.1 入场（三个档位，他全部明说）

> **【原话·入场 A，最早】eYeUS5wRwKg [2:47]**
> "this retest of the 13 is often a really good spot to get in so you can definitely get in on this first retest or second retest of the 13."

> **【原话·入场 A 的理由】eYeUS5wRwKg [3:12]**
> "if it is an actual [vomi] setup that 13 is a really Elite spot to get in because you're going to get most of the move down"
> （ASR 此处把 vomi 听成 "zombie"）

> **【原话·入场 B/C，确认后】eYeUS5wRwKg [3:36]**
> "you can actually wait for the break of the 48 and you can also get in on the 48. don't get in after the 48 break you know after you've confirmed full close below the 48 you can get it on the next pullback"

**【转述】** 三档：
- **A（激进）**：8/13 跌破后，第 1 次或第 2 次回抽 13 EMA。他说这里能吃到"most of the move down"。
- **B（确认）**：跌破 48 的那一下。
- **C（保守）**：等到有一根 K **完整收在 48 下方**之后，进下一次 pullback。

**【推论·重要】** 他在 [3:36] 那句里明确警告"don't get in after the 48 break"——**【推论】** 结合上下文，他的意思是不要在 48 破位后直接追空（追的是已经跑掉的价格），而要等回抽。**这是一条明确的"禁止追价"规则**，和他在 0DTE 视频里的说法完全一致：

> **【原话】k8yKdDDqN-M [4:13]**
> "you should always wait for a pullback right if it's starting to go away from you especially if an SPX 0 DT you do not want to start chasing these"

### 2.2 止损 / 风险位

> **【原话·Vomy 视频里唯一一次讲止损】eYeUS5wRwKg [2:47]**
> "use the level above or use the actual 13 [EMA] as your risk closing above that all right get out you can reevaluate"
> （ASR 把 "13 EMA" 听成 "13 Emir"）

> **【原话·Vomy 视频结尾】eYeUS5wRwKg [5:54]**
> "you just need to wait for your confirmation uh but you can always get in early and you know have some tight risk on there uh to make sure that you don't get on the wrong side of the trade"

**跨视频的通用止损规则（比 Vomy 视频里讲得细）**

> **【原话】QMJ_rg3phPA [2:21]**
> "adding the 13 EMA allows us to take Precision entries between the 8 and 13… it also allows you to stay in the position you can use that 13[EMA] often as risk or 13 to 21 zone is risk um you know if it closes below that zone then you can exit your position"

> **【原话】QMJ_rg3phPA [2:45]**
> "adding the 48 [EMA] allows us to have a clear point where Trend is likely to change if broken"
> （ASR: "the 4080 emulator"）

> **【原话·他明说没有唯一答案】k8yKdDDqN-M [18:38]**
> "the risk the stop it should be related to your risk your contract your sizing all those things there's no definitive way to do this it's very much based on how you set up the trade"

> **【原话·候选风险位清单】k8yKdDDqN-M [18:15]**
> "you could use the 21 or the 34 or the 48 or you could use the pre the the put trigger right or you could use the low of the day the the um um pre-market low right so any of those are work"

**【转述】止损位候选集（按由紧到松）**：`EMA13` → `EMA13–21 zone` → `EMA21` → `EMA34` → `EMA48` → 结构位（call/put trigger、当日高/低、盘前高/低）。判定方式是**收盘价穿越**（"closing above that"、"if it closes below that zone"），不是盘中刺穿。

**【推论·对本轮研究极重要】** 他给的是一个**结构性止损**，不是固定距离止损。这意味着：
- 止损距离 S 是**随波动率和入场时机变化的随机变量**，不是常数；
- 入场 A（13 回抽）的 S 极小（价格就贴着 13），入场 C（48 下方回抽）的 S 也小（就在 48 附近）；
- 而目标 T 是 ATR 位，距离固定得多。
- **→ 这正是"高盈亏比"的机械来源，也正是本轮必须用 S/(S+T) 零假设去检验的那个几何。** 他的方法论天然产生小 S、大 T；问题是这个几何是否**跑赢** S/(S+T)。

### 2.3 目标

> **【原话】eYeUS5wRwKg [5:08]**
> "and of course you can pair it with ATR levels to take profit at these levels so here we're taking profit at the previous close here we're taking profit at the put trigger"

**【原话·盘前计划里的真实用例】9FtVMpKFZPs [15:47]**
> "we were looking for 417 calls above the 38.2 level on consolidation breakout to the upside looking for 414 puts on a potential vomi setup breakdown of the call trigger and potentially the 4080 EMA"
（ASR "4080 EMA" = 48 EMA）

> **【原话·同一笔交易的结果】9FtVMpKFZPs [16:34] / [17:20]**
> "typical uh vomi setup where you've got you know these these fins into resistance uh then a breakdown of the 13 retest to the 13 break of the 48 and down"
> "hit our first Target came down to our second target so didn't make it to the third target but made it to the second target by noon"

**【转述】** 目标 = **ATR 位阶梯**，多级（first/second/third target），分批出场。Vomy 视频里点名的两个目标是 **previous close** 和 **put trigger**。**【推论】** 注意这是一个**多目标 scale-out** 结构，不是单一 T——所以纯 S/(S+T) 的双结局模型其实低估了他的实际操作；本轮若要严格检验，应该同时测「首个目标命中率」和「MFE 分布」。

### 2.4 ★ 一个必须记录的诚实声明

> **【原话】eYeUS5wRwKg [0:23]**
> "this presentation is not Financial advice and I'm not a financial advisor"

**【转述】** 他每个视频开头都念这句。更重要的是 Golden Gate 视频里他主动说要 back test（见 §4.4）。

---

## 3. TimeWarp：他在 3m 图上看 10m ribbon 时，具体在等什么

### 3.1 定义与动机

> **【原话】QMJ_rg3phPA [12:06]**
> "basic idea candles on Lower time frame trend on higher time frame"

> **【原话】QMJ_rg3phPA [12:29]**
> "what if I shifted the entire ribbon like what if I could see Precision candle entries on like a three minute but I can see the 10 minute Trend"

> **【原话】QMJ_rg3phPA [12:52]**
> "it allows you to achieve two time frames on a single chart so you can enter a day trade using three minute candles but um you know using a useful 10 minute Trend"

### 3.2 ★ 他在等的具体东西（直接回答问题 3）

> **【原话】QMJ_rg3phPA [13:37]**
> "let's say you break above the 13 EMA above the eight it starts to hold the ribbon there is a surgical entry"

> **【原话】QMJ_rg3phPA [14:23]**
> "pulls back to the 13. so here's that 13 EMA test recovers the 13 that's a good entry right there"

> **【原话】k8yKdDDqN-M [8:08]**
> "you can get surgical entries at the 13 EMA between the 8 and 13 uh or even down to the 21 perfectly fine"

> **【原话·反例，什么时候不进】k8yKdDDqN-M [8:32]**
> "when you get super extended like this though that's not an entry right that's a pullback and it's likely… if you do not recover it uh successfully"
> "wait for it to recover the 13 and then you know consider entering above a breakout of uh resistance"

**【转述】等的是三件事，缺一不可**：
1. **高周期 ribbon 提供方向**（10m ribbon 堆叠 = 只做那个方向）；
2. **低周期蜡烛回抽到高周期 ribbon 的 8/13 区**（或最深到 21）；
3. **回抽后「收复并守住」13**（"recovers the 13"、"starts to hold the ribbon"）——这是扣扳机的那一下。

**明确的负面规则**：价格已经**远离** ribbon（super extended）时**不是入场**，必须等它回到 13 再说。

### 3.3 他推荐的组合

> **【原话】QMJ_rg3phPA [16:17]**
> "the one three combo the 310 combo the 10 30 combo for like multi-day levels you know um hourly daily daily weekly those are all really good um combos"
> "you can even do things as wild and crazy as like a 110 or a 330 330 can often work really well for extended uh price action that reverses usually you'll get a reversal back to that 30 minute ribbon"

> **【原话·具体到标的】k8yKdDDqN-M [2:20] / [2:42]**
> "scalping SPX using day levels with the one three time warp"
> "day trading SPY using day levels with 310 Time Warp"

**【转述】** 组合表：

| 蜡烛 | Ribbon | 配套 ATR mode | 用途 |
|---|---|---|---|
| 1m | 3m | day | SPX 0DTE scalp |
| 3m | 10m | day | SPY day trade（1DTE）|
| 10m | 30m | multi-day | — |
| 1h | daily | swing | — |
| daily | weekly | position | — |
| 3m | 30m | — | 极端延伸后的反转，"回到 30m ribbon" |

**【转述·视觉识别】** 他说时间扭曲后的 ribbon "looks like an alligator"（`k8yKdDDqN-M [3:28]`），因为高周期 EMA 画在低周期网格上会呈阶梯状。

### 3.4 Conviction Arrows（顺带，因为和 Vomy 强相关）

> **【原话】QMJ_rg3phPA [0:23]**
> "conviction arrows first which are essentially the 1348 EMA crossover up and down"

> **【原话·选择 13/48 的理由】QMJ_rg3phPA [2:45]**
> "the 1348 have the reason why I selected those two values is there's uh some research on this dating back until I think 2011. talks about how they've been they're statistically the best crossover particularly on higher time frames I think the study was done against the daily"

> **【原话·★ 他自己否认这是买卖信号】QMJ_rg3phPA [3:35]**
> "I want to make it clear these are not buy and sell signals"
> "hopefully you're buying at the at an earlier crossover or at Key support or resistance and then the conviction [arrows] are saying hey it's probably going to go in this direction maybe"

> **【原话】QMJ_rg3phPA [3:56]**
> "typically it'll pull back after the arrow fires um before it continues higher continues lower"

> **【原话·他自己承认的失败模式】QMJ_rg3phPA [4:21]**
> "in chop like any EMA crossover there's going to be um false signals so you have to be careful with that"
> "the ribbon is is just a tool helping you manage uh trend it's a lagging indicator like all EMAs"

**【推论】** 注意 conviction arrow（13/48 交叉）和 Vomy 的确认（跌破 48）是**两个不同的事件**，且 13/48 交叉通常**晚于** 48 破位。他把 arrow 当"事后确认 + 预期回抽"，不当入场。第一轮如果把 conviction arrow 当信号测，测的是错的东西。

---

## 4. Golden Gate 视频里他怎么讲入场（而不只是概率）

### 4.1 概率是别人做的，他明确署名

> **【原话】d43HaLb765k [1:12]**
> "I want to give a shout out to my good friend Robert tesak uh who's Tess Rak on X… he has done a whole bunch of work on ATR levels probabilities and um uh things like the Golden Gate Strat uh cannot exist without Robert"

**【转述】** 概率作者 = **Robert Tezak，@tesrak**（视频描述里给了 X 和 YouTube 链接）。**【推论】** 我们真正要证伪的统计口径应该去他那边找，Saty 只是转述者。

### 4.2 两条被引用的概率

> **【原话】d43HaLb765k [3:59]**
> "there is a 60% chance if price reaches the 382 level and that's the ATR level uh that it reaches the 61.8 ATR level"

> **【原话】d43HaLb765k [6:25]**
> "there is over 70% chance when an ATR level is hit that you're going to get to the next level so if you're in an uptrend that would be the next level above and if you're in a downtrend that would be the next level below"

> **【原话·Golden Gate 命名】d43HaLb765k [4:45] / [5:09]**
> "618 is the golden FIB… the idea here was to come up with a name that uh connected uh breaking through that level to get to the golden fib and so Golden Gate is what came out of that"
> "the plus[/minus] 382 level is what we call the Golden Gate and that leads us to the golden FIB which is the 618 level"

**【转述·对照第一轮】** 我们第一轮测出 64.6% 完成率，**和他说的 60% 完全吻合**——数字上我们复现了他。分歧不在数字，在于这个数字算不算 edge。

> **【原话·他确实把 60% 当成 edge，这是可证伪的原始主张】d43HaLb765k [5:34]**
> "this just knowing this alone 60% chance that you're going to hit it is in itself a strategy that you could just trade exclusively if you wanted to right it is a strategy that you can trade uh you know when you have a higher chance that something's going to work out than it's not going to work out that's an edge you have an edge on on the market at that point"

**【推论·本轮的靶心】** 这句是他最强、也最脆弱的主张。"60% > 50% 所以是 edge" —— 这**正好**是第一轮 CLAUDE.md 里点名的错误：正确的零假设是 S/(S+T)，不是 50%。从 0.382 到 0.618 的目标距离是 0.236 ATR；如果止损放在 0.382 下方 0.236 ATR 处，随机游走下的先到概率就是 50%，60% 才是真 edge；但如果止损更近（他实际就是更近），零假设会**高于** 60%。**这是本轮必须算清楚的第一件事。**

### 4.3 ★ 他怎么讲入场（直接回答问题 4）

> **【原话·核心那段】d43HaLb765k [9:12]**
> "the bullish case is it hits the 382 level ideally you've got clear Trend now **this is something that's not part of the statistics but this is just something that I've added that I'm looking for** generally I want to see clear Trend because it provides better entries right **we're looking for pullback entries so looking for an entry at the ribbon if if possible**"

**【转述】这段是整份文档信息密度最高的一句。** 他**主动承认**："clear trend 这个条件不在统计里，是我自己加的。"——所以那 60% 是**无条件基准率**，而他实际交易的是一个**加了自选过滤器的子集**，这个子集的胜率**从来没被统计过**。

> **【原话·合格的回抽位】d43HaLb765k [8:26]**
> "pullbacks to a trending ribbon when you've got this nice beautiful stacked trending ribbon get a pullback and it holds let's say the 48 the 34 the 21 any of those or even pullback to the 13 those are viable dips those are b[uya]ble dips"

> **【原话·另一种入场】d43HaLb765k [9:12]**
> "you can of course use you know break of this support turns you know this turned into this was resistance this the call trigger resistance turned back into resistance turned back into support and that's pretty confident uh confidence inspiring"

> **【原话·目标】d43HaLb765k [9:34]**
> "generally looking at an entry at the at the ribbon and then you have a takeprofit level of course you can take profit at the 50 you can take profit at the 618 and then you can leave Runners"

> **【原话·止损，他在 swing 例子里唯一一次说了具体价】d43HaLb765k [17:17]**
> "you enter let's say the put[…] pull back to the put trigger 13 Zone let's say here for good risk you know uh take out uh 240 is your risk maybe for that uh For That Swing"

**【转述】Golden Gate 的实际交易结构（作者版）**：

| 要素 | 内容 |
|---|---|
| 触发 | 价格触及 ±0.382（Golden Gate）|
| 自加过滤 | clear trend / stacked ribbon（**他明说不在统计里**）|
| **入场** | **不是在 0.382 触及时入场**，而是**等回抽到 ribbon**（13 / 21 / 34 / 48 任一）后入场；或用 call/put trigger 的"阻力转支撑"回踩入场 |
| 止损 | 结构位（ribbon 层 / trigger 位），**无固定距离** |
| 目标 | 0.5（mid-range）→ 0.618（golden fib）→ 留 runner |
| 失败率 | 他明说会输 |

**【推论·这是本轮研究应该测的真正假设】** 第一轮把 GG 当成"触及 0.382 → 是否到 0.618"的**路径统计**来测，测出它是距离的别名。但作者本人的交易**不是在 0.382 入场的**——他在**回抽到 ribbon 之后**才入场，入场价比 0.382 更差（做多时更低）。这带来两个第一轮完全没测的结构性后果：
1. **入场价更好 → S 更小、T 更大 → 赔率结构被改写**。触及 0.382 到 0.618 只有 0.236 ATR，但从回抽到 EMA21/34 的位置到 0.618，距离明显更大。
2. **"等回抽"本身是一个筛子**：不回抽就跑掉的那些行情，他根本没进场——这会系统性地删掉一部分赢家，也删掉一部分输家，**改变的是分布形状而不只是均值**。
3. **→ 本轮必须测的格子是「0.382 触及 + 回抽到 ribbon 层 X + 结构止损」的 MFE/MAE 联合分布，零假设用该几何下的 S/(S+T)。**

### 4.4 他自己承认的局限（必须记录，这是对他有利的诚实）

> **【原话】d43HaLb765k [0:25]**
> "anything that you learn from this video that you start implementing on your own is uh those trades are your trades and your trades only so **make sure you back test everything** uh and fully understand what you're getting into manage your risk"

> **【原话】d43HaLb765k [8:49]**
> "then it could be part of the the 40% or 35% case where it doesn't work out and that happens that does happen uh so you have to be okay with the fact that sometimes it's just not going to work out in your favor"

> **【原话】d43HaLb765k [11:53]**
> "this is not perfect ATR level is never perfect pretty good though um pretty well respected by the market"

> **【原话·失败案例他也放进视频了】d43HaLb765k [18:52]**
> "hit the Golden Gate hit the golden FIB hit the Golden Gate hit the golden FIB failure hit the Golden Gate did not hit the golden FIB right so there's a failure example right there"

> **【原话·他自己说 GG 不是独立 swing setup】d43HaLb765k [19:15]**
> "I mostly use it for day tra[d]ing but I have been starting to use it a lot more for staying in swings **I don't use it particularly as a straightup swing setup I use it in conjunction**"

**【转述】** 他把 GG 定位成**「持仓依据」而不是「入场信号」**——"an awesome way to **stay in trades**"（`[6:00]`）。**【推论】** 这和第一轮把它当入场信号来证伪，其实打偏了。他的主张是"这个统计让我敢拿住"，那对应的可检验命题是**条件持有的 MFE 分布**，不是入场胜率。

### 4.5 fractal / 多 mode

> **【原话】d43HaLb765k [16:09] / [16:54] / [18:05]**
> "day mode is daily candles uh ATR daily ATR multi-day is weekly ATR"
> "swing mode is monthly ATR"
> "Tesla position mode these are quarterly ATR levels"

**【转述】** mode 表：day = 日 ATR，multi-day = 周 ATR，swing = 月 ATR，position = 季 ATR。他声称同一个 60% 在四个 mode 上都成立（`[3:12]`：他说这是 Robert 已经评估过的）。

---

## 5. 对第一轮的四条硬性修正

| # | 第一轮的做法 | 原话证据 | 应该改成 |
|---|---|---|---|
| 1 | Vomy = ribbon 变色/快慢线交叉那一刻（三个候选定义） | `eYeUS5wRwKg [3:59]` "to anticipate that is what the vomi setup really does" | Vomy 的**确认点是「break and hold of EMA48」**，变色是结果。首选入场更早：13 回抽 |
| 2 | Yummy 定义取自第三方博客 | 全 13 份逐字稿 + 4 份描述检索 "yummy" = **0 命中** | 作者叫 **"inverse vomy"**，是严格镜像。"Yummy" 无原始出处，证据等级 = 第三方 |
| 3 | GG 当作"0.382 触及即入场"的路径统计 | `d43HaLb765k [9:12]` "we're looking for pullback entries so looking for an entry at the ribbon" | 入场在**回抽 ribbon 之后**，不在 0.382。S/T 几何完全不同 |
| 4 | 用 60% vs 50% 判断 edge | `d43HaLb765k [5:34]` 他确实这么说；但 `[9:12]` 他又承认 trend 过滤"not part of the statistics" | 60% 是**无条件基准率**；他实际交易的是未被统计的子集。零假设必须用 S/(S+T) |

---

## 6. 本轮研究可以直接开工的三个格子（由原话导出，非我杜撰）

**【推论】** 以下是我从原话导出的、可用 5 分钟数据检验的假设。**注意：这是三个预注册的格子，不是网格择优的结果。**

**G1 — Vomy 的赔率结构（作者定义版）**
- 触发：`EMA8>13>21>34>48` 成立 ≥N 根 → 收盘跌破 EMA13 → 跌破 EMA48 且**下一根收盘仍在 48 下方**（break and hold）
- 入场：48 破位确认后的**下一次回抽**（作者的入场 C，最保守也最可编码）
- 止损：收盘回到 EMA21 上方（作者原话候选之一）
- 目标：下一个 ATR 位（previous close / put trigger）
- **零假设：S/(S+T)，S 和 T 逐笔实测，不用常数**

**G2 — Golden Gate 的真实入场版**
- 触发：触及 +0.382
- 入场：回抽至 EMA21–34 区间（作者 "viable dips"）
- 止损：收盘跌破 EMA48
- 目标：+0.618
- **对照组：在 0.382 直接入场（第一轮的口径）。两组的 S/(S+T) 超额必须分别报告。**

**G3 — 「stay in trades」而不是「入场」**
- 作者的真实主张是持仓依据。检验：**已在趋势仓中**、价格触及某 ATR 位时，条件 MFE 分布是否右偏于无条件 MFE 分布。
- 这个格子第一轮完全没做，而它才是他原话的靶心。

**【纪律提醒】** 三个格子跑完必须报告**一共检视了多少格子**（含所有中途丢弃的），每个比例带 Wilson CI 和 n，条件筛选做两比例检验，z<1.96 直接写"没做功"。

---

## 7. 未解决 / 需要下一步

1. **Robert Tezak（@tesrak）的原始概率方法论没拿到**。Saty 只转述结论。他的 YouTube 频道 `@roberttezak2948` 有"原始概率视频"（`d43HaLb765k` 描述里给了链接）。**取他的逐字稿是下一个高价值动作**——我们要证伪的其实是他的口径（样本区间、是否含 gap、触及判定用什么周期）。
2. **Vomy 的原始推文图**：`https://twitter.com/satymahajan/status/1648369109774614532`（视频描述里给的"anatomy of a Vomy"标注图）。没取——X 需要登录。图里可能有比口述更精确的标注。
3. **ASR 质量**：数字类 ASR 有系统性错误（"4080 EMA" = 48 EMA，"20124" = 2024，"Android 8 trend" = 无意义）。所有**数字**引用我都按上下文核对过，但如果后续要引用更细的数字，建议回看视频。
4. **"break and hold" 的精确判定没有原话**：他说 "break and hold of the 48 confirms"，但**没说是 1 根收盘还是 2 根、用什么周期**。这是本轮建模必须自己做敏感性分析的一个自由参数——**必须报告在所有取值下的结果，不能只报最好的那个**。

---

*所有逐字稿：`research/satylab/transcripts/`。转换脚本：`research/satylab/j3_to_txt.py`。*
*未碰 TradingView，未碰浏览器，未改线上 Pine，未 git commit。*
