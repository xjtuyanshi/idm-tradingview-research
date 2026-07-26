# 一手教学材料勘查：satyland.com 全站 + Ripster (ripster47) 方法论 + 几何对照

> 日期：2026-07-25　脚本：`research/satylab/study_ribbon_vs_cloud.py`
> 抓取范围：satyland.com 全部 8 个页面（含 Wayback 校验）、ripstereducation.com 全部 20+ 个可读页面、
> 两位作者的 TradingView 脚本说明页原文、Saty YouTube 频道全部视频标题+描述。
> 本文只做"作者说了什么"的取证与几何对照，**不做盈利结论**。

---

## 0. 三句话摘要

1. **satyland.com 上不存在你要找的东西。** 全站 8 页、Wayback 全历史 URL 清单核对完毕：
   官网只有"这是什么指标 / 去哪下载 / 线挤在一起怎么办"。**没有 setup 清单、没有入场/止损/目标规则、
   没有反面清单。** 唯一一条接近规则的原话在 Phase Oscillator 页（见 §1.4）。教学 100% 在 YouTube 与付费 Discord。
2. **Ripster 那边相反：他把规则写成了文字，而且写得很硬。** ripstereducation.com 上有逐条的
   "Chop vs Trend"六判据、"10 AM Trend Time"概念、R 纪律、以及一条明确的反面清单
   （"If you cannot find Good Risk Reward, Ignore and move on."）。**这是本次收获最大的一批一手材料。**
3. **几何对照的答案是：冗余，不是互补。** 跨作者配对（Saty 8/21 vs Ripster 5/12 = 87.8%；
   Saty 13/48 vs Ripster 34/50 = 90.9%）**比作者自己体系内部的配对更一致**
   （Ripster 5/12 vs 34/50 只有 66.3%）。两套指标是同一个一维物件（EMA 间距符号）
   在不同时间尺度上的采样；真正的自由度是**尺度**，不是作者。

---

## 1. PART A — satyland.com 全站抓取

### 1.1 站点结构（已用 Wayback CDX 全量核对，不存在隐藏教学页）

| 页面 | URL | 性质 |
|---|---|---|
| Home | `/home` | 落地页 + 防骗声明 |
| Saty ATR Levels | `/atrlevels` | 功能列表 + 下载链接 |
| Saty Pivot Ribbon | `/pivotribbon` | **两个产品**：Pro（5 EMA）与 OG（3 EMA） |
| Saty Volume Stack | `/volumestack` | 买卖量代理指标（新，之前未收录） |
| Saty Phase Oscillator | `/phaseoscillator` | 唯一含方法论文字的页 |
| Scanners | `/scanners` | **他自己的扫描名单 = 他的 setup 分类学** |
| FAQ | `/faq` | 纯安装排障 |
| Terms / Discord | `/terms` `/discord` | 免责 / 引流 |

Wayback CDX（`url=satyland.com*`）返回的全部历史路径只有上述 8 页 + 静态资源。
**不存在 `/strategy`、`/lessons`、`/system` 之类的页面，历史上也没有过。**

### 1.2 `/atrlevels` 页面原文（全部）

> ATR Levels can be used with price, volume, and trend analysis as part of a trading system.
> Features include: Scalp (thinkorswim only), Day, Multiday, Swing, Position, and Long-term Modes /
> Central pivot level that indicates the previous period close / Potential long/short triggers with Data Labels /
> Potential targets based on ATR and key fibonacci levels / Full 2 ATR extension levels / Trend Label / Range Label

TradingView 脚本说明页补充（作者本人撰写）：级别体系 = 触发 23.6 / 中段 61.8 / 满幅 ±1 ATR /
扩展 161.8；信息表显示 trend、range utilization、long/short 数值；并明确写着
**"functions optimally when paired with fundamental technical analysis rather than used in isolation"**
（即：作者自己就说这东西不能单独用）。

注意用词：**"Potential long/short triggers"、"Potential targets"** —— 他自己全程用 "potential"，
从未在官网上声称任何胜率或概率。**"60% 到 61.8"这个数字不在官网上，只在 YouTube 视频里**（见 §2.1）。

### 1.3 `/pivotribbon` —— 这里有一个之前没有收录的产品

**Saty Pivot Ribbon Pro（5 EMA）**：

> 5 EMA Trend Ribbon (**8, 13, 21, 48, 200** default) / 2 color system for showing bullish trend (green + blue) /
> 2 color system for showing bearish trend (red + orange) / **Ribbon folding visual indicates EMA crossover** /
> **13 EMA pullback overlap to help with entries and holds in trend.** / Conviction Arrows based on 13/48 EMA crossover /
> Biased 2 color 21 EMA (against the 8 EMA cross) / Biased 2 color 200 EMA (against the 21 EMA cross) /
> Bias Candles / **Compression Candles (optional) - Saty Phase Oscillator Compression applied to Bias Candles** /
> Time Warp (optional)

**Saty Pivot Ribbon（OG，3 EMA）**：8/21/34，Conviction Arrows 13/48，Time Warp，Bias Candles。
署名原文：**"Inspired by Ripster EMA Clouds."**

**⚠️ 必须在写码前解决的口径冲突（我无法从公开材料判定）**：

| 来源 | Pro 的 Conviction Arrows |
|---|---|
| satyland.com `/pivotribbon` | 13/48 |
| TradingView Pro 说明页正文 | **8/48** |
| TradingView Pro 更新日志 | **"Reverted back to 13/48 crossover"** |

更新日志晚于正文，所以**当前实际行为大概率是 13/48，正文是过期的**。
若要在 Pine 里复刻 Pro，必须以脚本源码为准，不能信任任一段文字。

另一条只在 Pro 里出现、以前没记录过的功能：**Compression Candles = 把 Phase Oscillator 的
布林压缩状态染到 K 线上**。这意味着 Saty 自己把"压缩"当成一个跨指标的**共享状态**，
而不是振荡器的局部装饰 —— 这对我们做闸门设计是有用的一手信号。

### 1.4 `/phaseoscillator` —— 官网上唯一一条接近"规则"的原话

区带定义（作者原文）：

```
+100    Extreme
+61.8   Distribution Zone
+23.6   Neutral / Launch Zone
   0    Zero-line where momentum shifts
-23.6   Neutral / Launch Zone
-61.8   Accumulation Zone
-100    Extreme
```

配 Wyckoff 四相：**"the 4 phases that align with the typical Wyckoff phases of
Accumulation, Mark Up, Distribution, and Mark Down."**

三色系统与**本页唯一的因果句**：

> The 3-color system allows you to see momentum strength (green), weakness (red), and Bollinger compression
> (grey or magenta), giving you actionable signals to use against your trade.
> **"A compression signal followed by either green or red gives you a very clear indication of directional
> price expansion."**

以及 "Compass"（平滑信号的前端 = 短期趋势）和黄点：

> "Yellow light" momentum slowing signals upon PO +/- 61.8 and +/- 100 crossovers. Can help confirm mean reversions.

极值区：

> Outside of +/- 100 indicates extreme momentum and will typically result in some cooling off after momentum wanes.
> Great for signaling to look for divergences and mean reversion.

**可编码的三条**（全部来自本页逐字）：
- `compression_release_up  = compression[1] and color == green`
- `compression_release_down = compression[1] and color == red`
- `mean_reversion_watch = crossunder(PO, 61.8) or crossover(PO, -61.8) or |PO| 从 >100 回落`

### 1.5 `/scanners` —— 他的 setup 分类学（比任何教学页都直接）

他在 Discord `#tools` 频道提供的扫描器名单本身就是他的 setup 目录：

```
Volume        Vomy        ATR Levels Trigger
ATR Levels Golden Gate    Mean Reversion       Squeeze
```

**这份名单是本次抓取里信息密度最高的一项**：它说明 Saty 认定为"可扫描的可重复事件"只有 6 类，
其中两类（Vomy、Golden Gate）是他的具名 setup，两类（Trigger、Squeeze/Mean Reversion）是状态闸门。
**不存在"ribbon 四态"这样的 setup —— ribbon 在他的目录里根本不是一个可扫描事件。**
这与我们第一轮"ribbon 四态方向性检验全零"的否定结论是**一致**的，而不是矛盾的：
他自己也没把 ribbon 当信号源，ribbon 是背景。

### 1.6 `/faq` —— 排障为主，但有一条被隐藏的关键条目

现行 FAQ 的 12 条全部是安装/显示问题（Fit Studies、Scale Price Chart Only、Scalp 级别在 TV 不可用等），
**零条方法论**。

但现行页面的 DOM 里残留了一条被删掉问题文本的答案片段，Wayback 2024 版还完整：

> **"Can I still get your version of Ripster EMA Clouds?"**
> "Yes they are available here: https://tos.mx/mSHeSlZ — Ripster EMA Clouds are available widely
> on many platforms and my version for ThinkorSwim here:"

**即：Saty 自己维护并分发一份 Ripster EMA Clouds 的 ToS 移植版。**
这是两套体系之间最硬的一手关联证据 —— 不是"风格相似"，是同一个人同时发布两者。

### 1.7 `/volumestack`（新收录）

买卖量为**价格代理**，非真实 tape：
`Buy% = (close − low) / (high − low)`，`Sell% = (high − close) / (high − low)`，
高的一侧堆在上面。作者自己声明 **"this is a proxy metric ... it is not going to match up exactly
with actual buy/sell volume that can be found on tape."**

---

## 2. Saty 的具名 setup（官网之外，标注证据等级）

### 2.1 Golden Gate（证据：作者视频标题+描述 = author_verbatim；数字本身 = third_party）

视频 `The Golden Gate Strat Using Saty ATR Levels & Pivot Ribbon`（d43HaLb765k）描述原文：

> "In this video I discuss ATR Levels Probabilities and the Golden Gate Strat which can help you
> **stay in a trend trade**."
> Robert Tezak's Information — He is @tesrak on X ... His YouTube Channel: @roberttezak2948

**两个必须记下的事实**：

1. Saty 自己给 Golden Gate 的定位是 **"help you stay in a trend trade"（持仓工具）**，
   而不是入场信号。我们第一轮把它当成入场事件来测，测的东西和作者的用法不是一回事。
2. **概率表不是 Saty 的原创，是 Robert Tezak（@tesrak）的。** Saty 在自己的视频描述里主动归因。
   → 如果要追问"61.8% 这个数字是在什么零假设下算出来的"，
   **该去查的是 Tezak，不是 Saty**。公开搜索找不到 Tezak 的方法论文档（可能只在他的 YouTube / 私域），
   这是本次调查最重要的一个**未闭合缺口**。

### 2.2 Vomy / iVomy（证据：具名存在=author_verbatim；规则细节=third_party）

**Vomy 是 Saty 的具名 setup，而且就是你描述的那个东西。** 证据链：

- Saty 本人视频：`The "Vomy" Setup and How to Spot and Trade it Using Saty Pivot Ribbon`（eYeUS5wRwKg）
  描述原文：*"We've talked a lot about the 'Vomy' setup. So here it is in all its glory.
  How to spot it, what to look for, and **possible entries**."*
  并附标注推文 `twitter.com/satymahajan/status/1648369109774614532`。
- Saty 本人推文标题：*"How to trade Vomy with Pivot Ribbon Pro. $SPX"*、
  *"Learn how to trade Vomy (and **inverse Vomy**) here"*、
  *"**3m ribbon flip and iVomy** at afternoon scalp levels"*、
  *"Looking like an **inverse Vomy** setting up on the daily."*
  → **iVomy = inverse Vomy，是他本人使用的缩写。**
- `/scanners` 页把 **Vomy 列为一个可扫描事件**（作者本人网站）。

**规则细节（来自第三方复刻脚本 "Cash Saty Vomy STRATEGY" 的说明页，非 Saty 亲笔，evidence=third_party）**：

> "the ribbon is in a clear (thick) trend. Price then starts to pull back, forming a **'Dolphin'** shape
> in the ribbon." 入场触发 = **"the 48ema on the 10m chart breaks"**；显示方式 = **"the 10m ribbon over a 3m chart"**。
> 该页自己声明未处理的失效条件：**"Key s/r level nearby, then you can experience fake outs"**、
> FOMC / Fed speakers 等事件。

**这个 setup 的结构值得注意，因为它正好是你说的那件事，但带三个前置条件**：

```
1) 先有一段 clear / thick trend（带宽必须先"厚"）
2) 回调把 ribbon 挤成 "Dolphin"（带宽收窄，但尚未翻色）
3) 48 EMA 被击穿 → 入场
```

也就是说：**在 Saty 的原始体系里，"绿带收窄"不是信号，"收窄 + 前置厚趋势 + 48EMA 破位"才是信号。**
裸的"收窄→变红"在他的目录里没有名字。

### 2.3 Time Warp 工作流（证据：author_verbatim）

视频 `Saty ATR Levels & Pivot Ribbon: Scalping and Day Trading SPX and SPY with Time Warp`（k8yKdDDqN-M）：

> "I walk you through 3 examples trading **SPX 0 dte and SPY 1 dte** using **Day and Scalp ATR Levels Modes**
> along with the brand new Pivot Ribbon **Time Warp**."

→ 他的 0DTE 工作流 = 3 分钟图 + 10 分钟 ribbon（Time Warp）+ Day 与 Scalp 两套 ATR 级别叠加。
Scalp 模式 **TradingView 上不可用**（FAQ 原文），所以 TV 用户拿不到他 0DTE 工作流的一半。

### 2.4 "My Trading System" 文档（证据：third_party，仅取到片段）

存在一份 Saty 本人写的 PDF《My Trading System by Saty Mahajan》，
被第三方（CourseHero / CourseSidekick）转载，两站均 403，**未能取得全文**。
经由搜索索引可确认的片段（标注为 third_party，任何一条在写码前都要复核）：

- 目标：*"Create an equity curve that goes up and to the right."*
- 纪律：*"The market pays you to be disciplined"*；100% 的时间、每一天、每一笔；
  *"stick to your trading system"*、*"make the same type of trades over and over again"*。
- 立场：*"You don't predict or speculate — you analyze, react, and trade."*
- **时段**：开盘小时与 power hour 量大；**9:30–11:30 与 15:00–16:00 为理想交易时段**。
- **月内节奏（仓位）**：月初激进 0–90%，月中放慢 0–50%，第三周 0–25%，月末回升。
- **反面清单（片段）**：*"don't over-analyze"、"don't procrastinate"、"don't hesitate"*。

**注意：这份文档里的"反面清单"是心理层面的，不是技术层面的。**
我在全部一手材料中**没有找到** Saty 的技术性反面清单
（例如"不要在 X 状态下交易"）。这是一个真实的缺口，不要编。

---

## 3. PART B — Ripster (ripster47) 一手材料

### 3.1 `ripstereducation.com/post/ema-clouds` 全文（逐字，含作者原始错字）

这是 Ripster 体系最完整的公开文本。以下为原文关键段（`Jong` 是原文里 `Long` 的错字，`ho\` 同理）：

> Using EMA clouds on TrendSpider - 10 Min / 1Hr
> **NOTE: I Keep After Hour/ Premarket On on 10 Minute Charts. Other timeframes not needed**
> In Trendspider or TradingView Add below EMA Clouds: **5-12 or 5-13 / 34-50 / 8-9 (Optional) / 20-21 (Optional)**
>
> EMA Cloud System is Trading System Invented by Ripster. It is basically areas shaded between two EMAs.
> The concept that the EMA cloud area serves as **support or resistance** for Intraday & Swing Trading.
> Can be utilized effectively on **10 Min for day trading and 1Hr/Daily for Swings**.
>
> Ideally **5-12 or 5-13 EMA cloud acts as sold fluid Trendline** for day trades.
> **8-9 EMA Clouds can be used as pullback Levels** Clouds as well –(optional)
> Additionally at high level **price over under 34-50 EMA clouds confirms either bullish or bearish bias**
> on the price action for any timeframe
>
> **Intraday Hold Long as long as 5-12 EMA cloud holds or 10 min candle does not close or open under it**
> On swings 1 Hr Use 34-50 EMA for bullish over and bearish under.
>
> Here where to start. Import EMA clouds in ur platform setup 5-12 (or 5-13) 34-50 72-89 as ur EMAS.
> For now focus is on 10 min chart and **Focus first on 34-50 EMA cloud. These clouds act as support and resistance.
> Over 50 emas trend is bullish below is Bearish. When ever u long or short that 34-50 ema cloud is ur risk level.**
> Many a times a stock will change trend right on these clouds. **U have to be disciplined if stock crosses over
> the cloud [L]ong becomes short short becomes long.**
> On Gap Downs u want to short if they are under 10 min 50 ema cloud and get rejected, u wanna long if they move above.
> ... read 100s of chart just with 10 min candles and see how they behave with 34-50 clouds.
>
> Other things to consider
> **1. Higher high/lows on 10 min for long and lower lows lower highs for short**
> **2. 5-12 cloud cross is ur confirmation [L]ong when 5 cross 12 and short when 12 under 5 (combine with 50 ema 10 min)**
> **3. Volume is key if stock has done 20% vol in 1st 30 mins, it will trend in same direction.**
> **4. Add Opening Range Breaks to this system for intraday trades at open.**
> Another important update intraday, **Let trend ride as long as 10 min candle rides 5-12 (5-13) Cloud.
> 10 Min candle closes under you get out intraday.** For more conviction (u can create 8-9 mini cloud ribbon as well)

**云的分工（作者原话归纳）**：

| 云 | 角色 | 原话 |
|---|---|---|
| 5-12 / 5-13 | **流动趋势线 + 确认** | "acts as sold fluid Trendline"; "5-12 cloud cross is ur confirmation" |
| 8-9 | 回调挂单位（可选） | "can be used as pullback Levels" |
| 34-50 | **偏置 + 风险位** | "that 34-50 ema cloud is **ur risk level**"; "over 50 emas trend is bullish below is Bearish" |
| 20-21 / 72-89 | 可选层 | — |

### 3.2 关于"绿→红那一瞬间"在 Ripster 体系里的原名 —— 这是本节最重要的一条

**它有两个名字，而且分别属于两个不同的功能，绝不能混：**

1. **`5-12 cloud cross` = confirmation（确认）**。原话：
   *"5-12 cloud cross is ur confirmation Long when 5 cross 12 and short when 12 under 5
   (combine with 50 ema 10 min)"*
   —— 注意末尾的括号：**这个确认从来不是独立信号，它必须与 10 分钟 34-50 云的偏置合用。**
2. **`10 min candle closes under the 5-12 cloud` = 出场（不是入场）**。原话：
   *"10 Min candle closes under you get out intraday."*

**所以：你描述的"绿带收窄到变红那一瞬间"，在 Ripster 的原始体系里最接近的角色是
"多头持仓的出场触发"，而不是"空头的入场触发"。**
把它当反手入场用，是在他的规则之外的推广 —— 可能可行，但**不是他教的东西**，
因此不能借他的权威来免除检验。

而 **34-50 云的穿越才是他明确写了"反手"的那一个**：
*"U have to be disciplined if stock crosses over the cloud Long becomes short short becomes long."*
—— 反手的那条云是**慢云**，不是快云。

### 3.3 `10 AM Trend Time` 概念（作者原文，可编码，与我们 07-24 的 09:33 心跳直接相关）

> The **"10 AM Trend Time"** concept is crucial ... The first 30 minutes are typically volatile with significant
> moves, but **the period from 10 AM to 10:30 AM often determines the activity for the rest of the day.
> It decides whether the market will chop or trend.** Around 10 AM, you will often observe rejections, bounces,
> flag breaks, continuations, and reversals; this can occur at 10:15 or 10:30 ...
>
> Due to this concept, **we often take profits first at the "10 AM Trend Time" or decide the next step.
> We also frequently stop out at 10 AM if things are not working.**
> I define my trading strategy as focusing on **the opening three minutes and the post-10-minute trading period.**

→ 这是一条**时间闸门 + 时间止损**，完全可编码，且我们已有 5 分钟数据可测。

### 3.4 `Chop vs Trend` 六判据（作者原文，全部可编码）

> **I Often Teach that we should Go Full Size on Trend Day and be cautious on a Chop Day.**
>
> 1. **10 AM Concept** — New Highs or Lows by 10 to 10:30 AM: a clear indicator of a trend day is when the market
>    reaches a new high or low by 10 to 10:30 AM, moving beyond the range established during the opening hour
>    or first 30 minutes.
> 2. **PM Highs & Lows** — If, in the first 30 minutes to an hour, the market extends beyond the premarket highs
>    and lows, it suggests a likely trend day. In contrast, if the market action is confined within the premarket
>    high and low range, this typically leads to a more directionless or choppy trading session.
> 3. **Over Yesterday High & Lows** — A market that crosses beyond the previous day's highest or lowest points,
>    particularly following an inside day, often signals a trend.
> 4. **Movement of Stocks in Key Indices** — When most stocks within SPX/QQQ are making new highs (bullish) or
>    new lows (bearish) in the first hour, it strongly indicates a market-wide trend day.
> 5. **EMAs or EMA clouds** — In Chop Price moves up down the EMA, in trend either bearish or bullish
>    **Price rides the EMA clouds, for my system it rides 5-12 clouds making higher lows or lower highs**.
> 6. If Market makes a huge move at open and does not retrace all the way back to opening price but rather
>    **flags into 10-10:30 am and breaks that flag** either bear or bull flag we get the Trend.

**判据 2、3 我们已有数据可以直接测（premarket 高低、昨日高低）；判据 1、6 需要 5 分钟路径。
判据 5 是"价格骑住 5-12 云 + 抬高低点"，是一个可编码的持仓条件，不是入场条件。**

### 3.5 Risk / Reward 与 R 纪律（作者原文）—— **这是他的反面清单所在**

> Ask your self before you hit the button, what is "my risk and what is my reward".
> **If you are risking 2 dollars to make 1 dollar that is bad risk reward.**
> Most of time traders dnt care how much they will lose, they just want to make something,
> focus is all on reward, that is completely wrong and not consistent.
>
> **"If you cannot find Good Risk Reward, Ignore and move on."**
>
> 1st Rule for Newbies. Every Trade You Take, Try to "lose" (if you lose), a **FIXED AMT every time — "R"**.
> Then when you win, try to make **2R, 3R**. Dnt matter how many times u lose, **NEVER EVER lose more than "R"**.

`/newbie-tips`（同站）：

> Take 50 trades with 1 contract or 100 shares. Prove to yourself that you can **win 30 trades at least out of 50**,
> then scale.
> Once u can win 50/60% of your trades; find out **do u win big and lose small? Is your Win 2R 3R?**
> If after winning 60% times You are still down ... go back to drawing board.
> **"Does not matter you win 8 times out of 10 if u give all up in 2 loses."**
> Probability and Statistics of your System is what matters!
> Top 3 beginner tips: 1. clean charts, analyze 100 charts  2. find a system, each trade a repeatable process
> 3. **Always keep Loses, R (risk) same, understand Position Sizing**

**这正是用户直觉的作者版本**：Ripster 明确说胜率不是重点、R 结构才是重点。
但也请同时注意他给的**数量约束**：他要求的是 **胜率 ≥60% 且 R:R ≥ 2:1**，
不是"低胜率高赔率"。**他从没说过可以用高赔率换低胜率。**

### 3.6 Ripster 的其他一手页面（已抓取，内容摘要）

- `/spy-vix-trades`：SPY/VIX 策略。关键量化条件：**"most useful in high elevated VIX environments mostly over 18"**；
  **"When VIX goes under 18 ... specially under 16 ... its impact ... minimizes or goes away entirely;
  then in that case we rely on pure trend/levels."** VIX 关键位：18, 20, 22, 25, 28, 30, 32。
  → 一个明确的**制度闸门**，可直接编码。
- `/trading-styles`、`/small-cap-day-trades`、`/ath-breakout-swings`、`/journal-track`：分类学与流程，无阈值。
- `/ripster-option-rules`、`/ripster-cloud-trades`、`/reversal-swings`、`/swing-setups`、`/chop-vs-trend` 之外的
  recap 页：内容是图片/会员区，**文本层为空，未取得**。
- `Rip Rules (Tenet)` PDF 与 twunroll / threadreader 的 `#myoptionstradingrules` 长帖：
  **403 / 反爬验证页，未取得。**（该验证页是人机验证，我没有绕过。）

---

## 4. PART C — 几何对照：Saty Pivot Ribbon vs Ripster EMA Cloud

脚本：`research/satylab/study_ribbon_vs_cloud.py`　数据：SPY（**不用 ^GSPC 日线开盘价**，遵守纪律 5）
10 分钟由 5 分钟按 session 对齐重采样（60 天，n=2340 bars）；5 分钟（60 天，n=4681）；
1 小时（730 天，n=5090）作稳健性。

**格子数披露：配对分析 = 3 个时间框 × 5 个配对 = 15 个格子，下面全部列出，无挑选。**

### 4.1 先看纯代数：这两套东西是不是同一个物件

一个"云"= `sign(EMA_a − EMA_b)`。EMA 长度 N 的重心（数据平均年龄）为 `COM = (N−1)/2`。
两条 EMA 的 **COM 间距**就是这个云的时间尺度：

| 云 | COM 间距（bars） | 归属 |
|---|---|---|
| Ripster 5/12 | **3.5** | 最快 |
| Saty 8/21 | **6.5** | |
| Saty 21/34 | **6.5** | 与 8/21 尺度**相同**，只是整体后移 |
| Ripster 34/50 | **8.0** | |
| Saty 13/48 | **17.5** | 最慢 |

**第一个结论（纯代数，不需要数据）**：Saty 的 8/21 与 21/34 有**完全相同的 COM 间距 6.5**。
所以 Saty 的三线 ribbon 不是"两个不同尺度的滤波器"，而是**同一个尺度的滤波器被平移了一次**。
真正给他体系带来第二个尺度的，是 Conviction 的 13/48（17.5）。
—— 这也解释了为什么 Pro 版把 48 和 200 加进主 ribbon：OG 版的尺度覆盖是不够的。

### 4.2 SPY 10 分钟（作者们指定的时间框）

churn（每 1000 根 K 的翻色次数）：

| 云 | flips | per 1000 |
|---|---|---|
| Saty 8/21 | 96 | 41.4 |
| **Ripster 5/12** | **166** | **71.3** |
| Saty 21/34 | 48 | 20.8 |
| Ripster 34/50 | 25 | 10.9 |
| Saty 13/48 | 39 | 17.0 |

配对结果（全部 5 个格子）：

| A | B | 逐 K 符号一致率 | P(B多\|A多) | P(B多\|A空) | z | B 相对 A 的翻色时滞（中位） |
|---|---|---|---|---|---|---|
| Saty 8/21 | Ripster 5/12 | **87.8% [86.5,89.1] n=2320** | 89.2% | 13.9% | +36.3 | **−1.0 bar（Ripster 先翻）**，95/96 配上 |
| Saty 21/34 | Ripster 34/50 | **90.1% [88.8,91.3] n=2291** | 90.8% | 10.8% | +38.3 | +5.0 bars（Saty 先翻），仅 24/48 配上 |
| Saty 8/21 | Saty 21/34 | 82.5% [80.9,84.0] n=2307 | 84.8% | 20.4% | +31.0 | +4.0 bars，53/96 配上 |
| **Ripster 5/12** | **Ripster 34/50** | **66.3% [64.4,68.3] n=2291** | 70.1% | 38.4% | +15.2 | 仅 25/166 配上 |
| Saty 13/48 | Ripster 34/50 | **90.9% [89.7,92.0] n=2291** | 91.3% | 9.6% | +39.0 | +5.0 bars，23/39 配上 |

5 分钟与 1 小时的稳健性完全同向（8/21 vs 5/12：88.0% / 87.1%；13/48 vs 34/50：90.1% / 90.0%；
5/12 vs 34/50：67.0% / 66.6%）。**三个时间框、15 个格子，无一例外。**

### 4.3 判决

**（1）是不是同一个东西？—— 是。**
Saty 8/21 与 Ripster 5/12 逐 K 同号 87.8%，且 95/96 次翻色在 ±12 根内配对成功，
中位时滞 **−1 根**（Ripster 快一根，因为它的 COM 间距 3.5 < 6.5）。
Saty 13/48 与 Ripster 34/50 同号 90.9%。**两套指标是同一族的不同参数化。**

**（2）同时看两套是冗余还是互补？—— 在同一时间尺度上是冗余，而且是最坏的一种冗余。**

决定性证据是这一行对比：

```
跨作者、同尺度：  Saty 8/21   vs Ripster 5/12  → 87.8% 一致
跨作者、同尺度：  Saty 13/48  vs Ripster 34/50 → 90.9% 一致
作者内部、跨尺度：Ripster 5/12 vs Ripster 34/50 → 66.3% 一致   ←← 唯一真正携带新信息的配对
```

**跨作者配对比作者体系内部配对一致得多。** 换句话说：
"是谁设计的"不携带信息，"什么尺度"才携带信息。
你同时看 Saty ribbon 和 Ripster clouds，得到的不是两个观点，是**同一个观点被念了两遍**，
而且两遍之间还有 1 根 K 的错位 —— 这个错位不给你信息，只给你**犹豫**。

**（3）冗余的代价是可量化的。**
Ripster 5/12 在 10 分钟上每 1000 根翻色 71.3 次，Saty 8/21 是 41.4 次 —— **1.72 倍**。
两者同号 87.8%，即 12.2% 的时间它们互相矛盾。这 12.2% 绝大部分落在翻色前后 1–2 根内，
正是最需要果断的时刻。**同时挂两套的净效果 = 在每个决策点上引入一个 1.7:1 的分歧源。**

**（4）唯一真实的互补维度是尺度阶梯，而这个阶梯 Saty 的 Pro 版已经自带了。**
Saty Pivot Ribbon Pro 的 EMA 集合是 8/13/21/48/200，已经覆盖 Ripster 的 5–50 全区间，
且 13/48 与 Ripster 34/50 有 90.9% 的同号率。**若你已在用 Pro，Ripster 的 34/50 是 ~91% 冗余的。**

### 4.4 三条可检验的判断（给下一轮）

> **H1（冗余量化）**：在同一 bar 上，"Ripster 5/12 与 Saty 8/21 分歧"这个状态，
> 对随后 N 根的方向没有增量信息。零假设 = 分歧组与一致组的方向分布相同，做两比例检验。
> 若 z<1.96 → 正式判定"同时看两套 = 零信息增益"，并建议只留一套。

> **H2（尺度才是自由度）**：把 (a,b) 参数化为单一变量 `COM_sep = (b−a)/2`，
> 对 COM_sep ∈ {2, 3.5, 5, 6.5, 8, 11, 17.5} 各建一个云，检验"任意两个具名云的行为差异
> 是否被 COM_sep 完全解释"（即残差是否落在具名/非具名的安慰剂梯子内）。
> **这是第一轮安慰剂梯子方法的正确移植对象** —— 上一轮用它证伪了斐波那契具名位，
> 这一轮应该用它检验"作者具名"是否也只是尺度的别名。我预测：是。

> **H3（Ripster 的原始用法 vs 用户的推广）**：`5-12 cloud cross` 在作者体系里是
> **多头出场**触发；把它当**空头入场**是外推。检验：以 10m 5/12 下穿为事件，
> 分别测（a）作为平多的出场质量、（b）作为开空的入场质量，
> **入场那一侧必须用几何零假设 S/(S+T) 而不是 50%**。
> 若 (a) 显著而 (b) 不显著 → 用户的用法应回退到作者原意。

---

## 5. 附录：预登记检验 —— "绿带收窄到变红"到底是信息还是同义反复

**这是你描述的那个事件本身，先把它的逻辑拆开：**
符号翻转在数学上**要求**带宽先归零。所以"收窄先于翻色"是**同义反复，零信息**。
唯一非平凡的问题是**反向**：**带宽已经很窄时，它有多大概率真的完成翻转，而不是弹回去？**

预登记规格：SPY 10 分钟，`|EMA_fast − EMA_slow|` 相对自身**滚动 100 根**的分位数，
分位 ∈ {p10, p25, p40}，水平线 ∈ {3, 6, 12} 根。
**格子数披露：2 个云 × 3 分位 × 3 水平 = 18 个格子 + 6 个基准，下面全部列出。**

### Saty 8/21（10m）

| 水平 | 无条件 P(翻色) | \|gap\|≤p10 | ≤p25 | ≤p40 |
|---|---|---|---|---|
| 3 根 | 12.1% [10.8,13.5] n=2237 | 40.1% n=277 (z=+12.2) | 33.2% n=635 (z=+12.6) | 25.3% n=935 (z=+9.3) |
| 6 根 | 22.7% [21.0,24.5] n=2234 | 49.8% n=277 (z=+9.7) | 46.8% n=635 (z=+11.9) | 40.6% n=935 (z=+10.2) |
| 12 根 | 39.5% [37.5,41.5] n=2228 | 63.4% n=276 (z=+7.6) | 61.7% n=632 (z=+9.9) | 57.7% n=931 (z=+9.4) |

### Ripster 5/12（10m）

| 水平 | 无条件 P(翻色) | ≤p10 | ≤p25 | ≤p40 |
|---|---|---|---|---|
| 3 根 | 19.4% n=2237 | 53.8% n=266 (z=+12.6) | 43.7% n=586 (z=+12.2) | 36.0% n=914 (z=+9.9) |
| 6 根 | 34.8% n=2234 | 65.0% n=266 (z=+9.6) | 57.5% n=586 (z=+10.0) | 52.4% n=914 (z=+9.2) |
| 12 根 | 57.0% n=2228 | 79.7% n=266 (z=+7.1) | 74.5% n=585 (z=+7.7) | 71.3% n=913 (z=+7.5) |

**18/18 个格子全部 z>7，方向一致。** 结论：

**做功的部分**：带宽窄确实把"一小时内翻色"的概率从 22.7% 抬到 46.8%（Saty 8/21, p25, 6 根）。
这不是同义反复 —— 它是一个真实的、稳健的条件概率提升。
**你的直觉在"这个位置会发生变化"这一点上是对的，而且这是第一轮从没测过的量。**

**但必须同时说清楚三件事，否则又会重蹈第一轮 C1 的覆辙**：

1. **这测的是"会不会动"，不是"往哪动"，更不是"值不值得下注"。**
   翻色是一个**几乎对称**的事件：带宽窄同样抬高了"翻过去再翻回来"的概率。
   本表**完全没有**排除双向抖动。
2. **46.8% 是一个频率，不是一个边缘。** 要变成钱，必须配一个止损距离 S 和目标距离 T，
   然后跑赢 **S/(S+T)**，不是跑赢 50%，也不是跑赢 22.7%。
   带宽窄的时候 S 天然很小（止损可以放在带子另一侧），T 却不会自动变小 ——
   **这恰恰是"便宜的证伪点"的几何**，也正是它可能真的有价值的地方。
3. **所以下一步该测的不是这张表，是这张表的下一层**：
   把样本按翻色时的带宽分位切成两组（窄带翻色 vs 宽带翻色），
   量各自的 **MFE/MAE 分布**与在同一 (S,T) 几何下的**实际到达率 vs S/(S+T)**。
   **窄带翻色若真有价值，它必须表现为"同样的 S/(S+T) 下实际到达率显著更高"，
   而不是表现为"R:R 更好看"。** 这一条留给几何/赔率工作线，本报告不做结论。

---

## 6. 证据等级与未闭合缺口

| 项 | 等级 |
|---|---|
| satyland.com 全部页面文本、Wayback URL 全集 | author_verbatim |
| TradingView 两位作者的脚本说明与更新日志 | author_verbatim |
| ripstereducation.com/post/ema-clouds、/10-am-trading-concept、/chop-vs-trend、/risk-reward、/newbie-tips、/spy-vix-trades | author_verbatim |
| Saty YouTube 视频标题与描述 | author_verbatim |
| Vomy 的三条具体规则（thick trend / Dolphin / 48EMA break / 10m-on-3m） | **third_party**（第三方复刻脚本说明） |
| 《My Trading System》片段（时段、月内仓位节奏、反面清单） | **third_party**（搜索索引，原文 403） |
| Golden Gate 的 61.8% 概率 | **third_party**，且原始出处是 Robert Tezak 而非 Saty |

**未取得（明确记录，不要假装有）**：
1. **Saty YouTube 全部视频的逐字转录** —— timedtext 接口对本环境返回空，innertube 400，
   本机无 yt-dlp。**Vomy 与 Golden Gate 的精确规则只能靠看视频获得，这是目前最大的缺口。**
2. **《My Trading System》PDF 全文** —— CourseHero / CourseSidekick 均 403。
3. **Ripster 的 `Rip Rules (Tenet)` PDF 与 `#myoptionstradingrules` 推特长帖** ——
   站点 403 / 需通过人机验证；我没有绕过验证。
4. **Robert Tezak 的概率方法论** —— 公开搜索无结果。
   **这是最该补的一条**：Golden Gate 的 61.8% 到底在什么零假设下算出来的，答案在他那里。
5. **Saty 的技术性反面清单** —— 在全部一手材料中不存在。他的"don't"只有心理层面的三条。
   **Ripster 有技术性反面清单（"If you cannot find Good Risk Reward, Ignore and move on"），Saty 没有。**

---

## 7. 来源清单

satyland.com：`/home` `/atrlevels` `/pivotribbon` `/phaseoscillator` `/volumestack` `/scanners` `/faq`；
Wayback CDX `url=satyland.com*`；Wayback 2024 版 `/faq`。
TradingView：`Ty6CMBw9-Saty-ATR-Levels`、`I4VXGe18-Saty-Pivot-Ribbon`、`0AvaIFxw-Saty-Pivot-Ribbon-Pro`、
`AkgbmvVa-Saty-Phase-Oscillator`、`JkEYzo3X-Saty-Volume-Stack`、`7LPOiiMN-Ripster-EMA-Clouds`、
`0L91NSeh-Ripster-MTF-Clouds`、`DS4RZxw2-Cash-Saty-Vomy-STRATEGY`（第三方）。
YouTube（标题+描述）：`d43HaLb765k` `eYeUS5wRwKg` `k8yKdDDqN-M` `QMJ_rg3phPA` `kTmQc5eZzzc`
`p51XpVttZy8` `9NO3dyWej38` `9FtVMpKFZPs`；频道 RSS `UCF3YBU7CfOLrQ7u1DjaxNRQ`。
ripstereducation.com：`/post/ema-clouds` `/10-am-trading-concept` `/chop-vs-trend` `/risk-reward`
`/newbie-tips` `/trading-styles` `/spy-vix-trades` `/small-cap-day-trades` `/journal-track`
`/ath-breakout-swings` `/trading-resources` `/sessions`；Wayback CDX `url=ripstereducation.com*`。
本地计算：`research/satylab/study_ribbon_vs_cloud.py`（SPY 5m/10m/1h，缓存数据）。
