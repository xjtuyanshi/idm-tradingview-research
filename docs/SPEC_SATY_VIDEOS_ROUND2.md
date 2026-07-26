# Saty Mahajan 四集教学视频 —— 原作者逐字规则（第二轮，2026-07-26）

> **取回方式**：yt-dlp 2026.07.04（`--write-auto-subs`，en，json3）。
> YouTube 的 InnerTube player API、timedtext 端点、get_transcript 端点、
> Invidious / Piped / 各类第三方逐字稿站点在 2026-07 全部被 PO-token 机制挡死
> （返回 `FAILED_PRECONDITION` 或 HTTP 200 + 0 字节）；只有 yt-dlp 仍能通过。
> 逐字稿为 **YouTube 自动生成字幕（ASR）**，非人工校对 —— 见 §0 关于 ASR 误识的警告。
>
> **证据等级 [A]：原作者本人口述。**
> 本文所有【原话】均为 ASR 逐字稿原文（英文小写、无标点即 ASR 原样），带时间码。
> 标【转述】的是我的归纳；标【未知】的是四集里**没有说**的，不填空。

| # | 标题 | ID | 时长 | 播放 | 发布 |
|---|---|---|---|---|---|
| 1 | Day Trading with Saty ATR Levels and Ripster EMA Clouds including Setups, Entries, and Exits | `OP14Aee5au8` | 24:33 | 29,011 | 2022-05-02 |
| 2 | Ripster EMA Clouds Tutorial and the Golden Rule of Trend | `aTxbUec7rMo` | 26:14 | 57,771 | 2022-04-16 |
| 3 | Saty ATR Levels & Pivot Ribbon: Scalping and Day Trading SPX and SPY with Time Warp | `k8yKdDDqN-M` | 25:41 | 25,830 | 2023-01-30 |
| 4 | Making a SPY Day Trade Plan Using Saty ATR Levels and Saty Pivot Ribbon during Pre-market | `9FtVMpKFZPs` | 20:29 | 28,304 | 2023-04-24 |

---

## 0. 先说三条读本文必须知道的前提

**0.1 ASR 误识清单**（不校正会读出错误规则）
- `3450` = "34/50 云"（three-four-fifty）；`512` = "5/12 云"；`89` / `8 9` = "8/9 云"；`2021` = "20/21 云"。
- `1348` = "13/48"（第 3 集 17:24 的 conviction arrow）。
- Vomy 被 ASR 写成 `vomi` / `vami` / `avami` / `fomi` / **`follow me`** / **`zombie`** / **`mommies`**。
  第 4 集 8:33 的 "possible follow me forming here" = "possible **Vomy** forming here"；
  13:37 的 "possible zombie set up" = "possible **Vomy** setup"；3:12 的 "wedges mommies" = "wedges, **Vomies**"。
- `Saudi ATR levels`（第 4 集 20:12）= "**Saty** ATR levels"。
- `VWOP` = VWAP；`dogee` = doji；`0 DT` / `0 GT` / `1 DT` = 0DTE / 1DTE；`Vic` = VIX。

**0.2 时间跨度导致工具换代（这是本轮最重要的发现之一，见 §5）**
2022 两集用的是 **Ripster 云（5/12, 8/9, 20/21, 34/50, 180/200）**；
2023 两集用的是 **Saty Pivot Ribbon（8/13/21/34/48）**。不是同一套周期。

**0.3 本文不引用任何第三方博客/摘要站。**
搜索时确实出现了 toolify.ai 之类的二手总结页，**一律未采用**。

---

## 1. 第 2 集：Golden Rule of Trend（`aTxbUec7rMo`）

### 1.1 Golden Rule 的确切表述 —— 这就是要找的东西

【原话】17:22
> 「it's real simple ... the **the stock is bullish if it's over the 3450 ema and it's bearish
> under the 3450 ema**」

【原话】17:59（同段收尾，他自己重复了一遍作为定论）
> 「the **golden rule of trend is** uh **bullish over 3450 ema bearish under 3450 ema**」

**归属**：【原话】17:15「so the golden rule of trend so this is **ripster's golden rule**」
—— 这是 **Ripster 的规则**，Saty 只是转述并采用。

**用在哪个周期**：【原话】17:43
> 「that **10 minute and one hour** are really helpful ... **intraday trades you're using that
> 10 minute** ... and then the same thing with the **one hour** for one hour in the **daily for
> swing trades**」

**它的全部内容就到此为止。** 这条规则**没有**入场价、**没有**止损、**没有**目标 —— 它只是一个
二值的方向状态机。第 2 集全程没有出现 ATR 位，也没有任何一句给出止损。
（把入场/止损/目标补上的是第 1 集，见 §2。）

### 1.2 Ripster 五朵云各自的分工（9:41–14:25）

| 云 | 他的原话定位 | 用途 |
|---|---|---|
| **5/12** | 9:41「that's my **fluid trend cloud**」 | 持仓时盯的"流动趋势"；11:28 绿=5 在 12 上，红=12 在 5 上 |
| **8/9** | 9:56「typically where i want to do my **pullback adds**」 | 加仓位（不是首次入场位） |
| **20/21** | 10:00「sort of **the mean the pivot**」 | 21 EMA 是均值回归锚；10:16「as price action moves further away from the 21 it will tend to **revert to the mean**」；13:00「i like to have that on **all charts**」 |
| **34/50** | 10:33「the **trend cloud**」 | **Golden Rule 用的就是这朵**；13:06 蓝=34 在 50 上，橙=50 在 34 上 |
| **180/200** | 10:48「**long-term trend cloud** ... i typically use this just on the **daily or higher**」 | 只在日线以上；13:26 他把它保持灰色不分色 |
| 72/89 | 9:29「maybe a longer term trend **i don't use that one**」 | **他明确不用** |

**颜色翻转意味着什么**（回答任务里的问题）：
- 【原话】8:08 云的着色规则本身：快线在慢线之上=多头色，反之=空头色。
- 【原话】12:09 5/12 的意义：「since those are faster emas they'll typically **switch from one
  color to the other faster** ... giving you a **near-term trend change** understanding」
- 【原话】23:18 34/50 翻色的意义：「you can kind of see where **the trend flips** ... that 3450
  flips from **orange to blue** so it's a nice visual representation of what's going on when
  you see **trend change**」
- 【转述】所以：**5/12 翻色 = 近端趋势变化（快、噪声大）；34/50 翻色 = 体制变化（慢、是 Golden
  Rule 的判决线）。** 两者的分工就是"信号 vs. 前提"。

### 1.3 堆叠 / 扇形 / 交叉（6:18–6:46）

【原话】6:18
> 「when they're **stacked** on top of each other or below each other and then they're spread out
> meaning they're **fanned** out the more of that you see it typically indicates a **stronger
> trend**」

【原话】6:33（**这是一条可编码的均值回归预期**）
> 「when it gets to a certain point where it's **so fanned out and price action is so far away**
> from stacked moving averages **typically you're going to get a pullback to those moving
> averages**」

【原话】6:46
> 「the **crossing** of moving averages will indicate a **weaker trend a trend change or chop**」

### 1.4 周期（14:25–18:15）

【原话】14:41「with extended hours there's typically the **three minute and the 10 minute**」
【原话】14:59「the **10 minute is really the intraday trend** ... if you're day trading that's
kind of the one that you want to be on and then of course you can go down to the **three minute
for entry exits**」
【原话】15:32（为什么是 10 分钟 —— 可编码的取舍陈述）
> 「for trend confirmation having a 10 minute **you may lose a little bit of the juice on a move
> but that's okay at least you're not getting faked out**」

【原话】16:10「**10 minute the one hour and the daily** ... the **daily of course is the most
important chart**」；16:27 晚上看 daily/weekly/monthly，"start zoomed out and then zoom in"。

【原话】17:02（重要的通用性主张，可检验）
> 「the clouds apply the **same way regardless of time frame** ... everything that i talk about on
> any time frame really is **applicable to the other time frames**」

### 1.5 Chop 的判据（20:32–22:13）

【转述】他给的 chop 视觉判据：5/12 在短时间内**反复**红绿互换，且 34/50 也翻过去又翻回来。
【原话】21:16「it's **quickly flipping through from red to green on the 512** ... that's chop」
【原话】21:16「**it's a hard trade to hold on to** it's really fine for **scalping** probably
**not something you want to trade intraday**」

---

## 2. 第 1 集：Setups / Entries / Exits（`OP14Aee5au8`）—— 四集中最可编码的一集

### 2.1 Trend Mantra —— 他每天早上读的 7 条（2:26–6:06）

【原话】2:30「these are ... **seven statements i like to read every morning**」（存在 Apple Notes 里）

1. 2:49「**i am not long or short biased i just play the trend**」
2. 2:55「**trend gives me conviction** and with **solid trend you tend to get those bigger
   winners**」+ 3:09「often with a really really solid trend you're going to get to **at least the
   mid-range level** on atr levels **if not full atr**」← **这是他给出的目标期望值**
3. 3:28「**i don't trade the opening 10 minutes** this is just a rule i have」
4. 4:13「**i don't trade in a sideways market** ... **chopzilla is hungry loves to eat your
   premiums**」
5. 4:28「**i wait for trend confirmation i'm looking for price above emas**」
6. 4:34「**i never chase the trend once i get it i wait for a pullback to execute my trade** ...
   **there's always a pullback**」+ 4:47「**there's always another trade**」
7. 5:04「**i never play the opposite of trend when there's momentum**」
   - 他给的唯一例外（5:07）：「probability of getting a **bounce when you've gone one atr** either
     direction ... you can **play those probabilities you can hedge them**」
   - 但 5:37 立刻收回：有动量时逆势"**it's probably going to go against you**"
   - 5:52 他对"有动量"的定义：「**you're never seeing it retest those 3450 emas** it's just kind
     of clear headed to the sky or headed to the abyss」

### 2.2 多头设定清单 —— 3 条必要 + 3 条理想（6:06–9:54）

**【必要 E1】趋势为多**
> 【原话】6:47「i'm looking for a bullish trend and what this means is using **ripster's emas and
> ripster's golden rule of trend** ... to see that it's **above the 3450 cloud**」
> 【原话】7:02「if it's **above the 3450 AND above the 512** that's a little extra bullish ...
> that in fact is when the **label for atr levels the trend label will go green**」

**【必要 E2】10 分钟收盘价站上 call / long trigger**
> 【原话】7:26「we're looking for a **10-minute close above that call or long trigger**」
> （trigger 的中英标签可在设置里切换 call/long —— 期权用 call，正股用 long。）

**【必要 E3】ATR 覆盖率 < 70%**
> 【原话】7:36「and then we're looking for **less than 70% atr covered**」
> 【原话】7:50 range indicator 的三档配色：「**below 70% it'll be green** ... **above 70% but
> below 90% it'll be yellow** ... **above 90% it'll turn red**」
> 【原话】8:08「that doesn't mean it necessarily won't be able to go higher but typically once
> you've covered the range **the probabilities are now against you**」

**【理想 I1】"Super bullish" = 全部 EMA 堆叠**
> 【原话】8:23「**super bullish** is in my book defined as when you not only are above the 3450
> but you're **above all of the emas the five the 8 the 12 the 21 the 3450 and they're all
> stacked**」（注意：这里是 Ripster 的 5/8/12/21/34/50，**不是** Pivot Ribbon 的 8/13/21/34/48）

**【理想 I2】挤压（squeeze）方向向上**
> 【原话】9:01「we're in a **squeeze to the upside**」

**【理想 I3】RSI 超卖**
> 【原话】9:01「and we're **oversold on rsi** or i use **ready aim fire**」

**合取的效力（他自己的说法）**
> 【原话】9:15「**if you have all six of these man that's a good setup it's a high probability
> setup**」

**空头设定 = 完全镜像**（18:30–19:29）
> 【原话】18:32「we're looking for a **bearish trend** uh the **price below the 3450 ema** and
> we're looking for a **close below the put short trigger** and again **less than 70% atr
> covered**」
> 【原话】19:06 理想项：「the **emas are stacked above the price** ... and we're looking for a
> **squeeze to the downside** and we're looking for **overbought signals on our rsi**」

### 2.3 入场 / 止损 / 目标（9:54–18:30）

**周期选择**
> 【原话】1:20「i primarily use the **10-minute for my trend** i do enter trades on the 10-minute
> particularly **if they're not fast moving** ... if they're **super fast moving** i like to zoom
> in to the **3 minute**」

**入场：突破之后不许进，必须等回抽**
> 【原话】12:15（这是本集最关键的一句）
> 「**at this point we don't want to get in because if we get in we're pretty far from the emas
> it's likely that it's going to retest**」
> 【原话】12:27「it's likely that it's going to come **retest this 8/9 ema** ... it may even go
> back to the **21 that's the pivot that's the mean** ... often it will come back and retest that
> 21」
> 【原话】12:41「so now i will look for **adding a position at the 8/9**」

→ **入场锚点：10 分钟图上，回抽到 8/9 云（首选）或 21 EMA（次选）。**

**3 分钟图上锚点整体上移一级**
> 【原话】16:08「although you have fast and slow emas each one of these is much faster than the
> emas on the 10-minute and typically **i'm no longer really looking at cutting at a 21 or cutting
> at a 8/9 or cutting at a 512** um i'm looking at this **3450 basically that is my pivot for the
> 3 minute**」
> 【原话】16:44「**as long as it stays above that 3450 i'm pretty happy**」
> 【原话】17:16 总结：「if it's **above the 3450 on the 3 minute** you can look for a **pullback to
> the 8/9** add the position continue to add and scale in and look at that **3450 as your stopping
> point**」

**止损（他给出的全部候选锚点，都是技术位，且他明说没有唯一解）**
> 【原话】17:46「we could have **cut it as soon as it dropped below the 3450** ... or we could have
> put a **stop at the call trigger** we could have put a **stop at previous close**」
> 【原话】18:01「**it really depends on your risk and that depends on your strike and your
> expiration**」
> 空头例（23:27）：「maybe you have a **tight stop** here on the **minus one atr level** maybe
> you're keeping a **stop at the 34 at the 50 ema** uh you could keep a **stop at the vwap** ...
> you could keep a **stop at break even**」

→ **本集从未给出唯一止损规则。** 他给的是一个候选集：
`{3450 云下沿, call/put trigger, previous close, ±1 ATR 位, VWAP, 保本}`，
并把选择权交给"你的行权价与到期日"。**这是本集与 Vomy 那集最大的差别** —— Vomy 有唯一止损
（收盘站回 EMA13），本集没有。

**目标：分批，第一目标是 mid-range**
> 【原话】13:42「**my first profit target here is going to be this mid-range**  that's always
> what i'm looking for」
> 【原话】14:11「you can also just **start to scale out** ... this could be the **first scale out
> point** if you have multiple contracts maybe you're **adding at each one of these pullbacks**」
> 【原话】14:49「and then **leave runners** ... it just sort of continues to ride this 512 all the
> way up and it **hits atr at the end of the day**」

→ **目标阶梯：mid-range（±0.5）→ 回到 21 加回 → 再到 mid-range 减 → full ATR（±1.0）留 runner。**

**风控心法**
> 【原话】13:28「which is why **i never look at my p&l i just look at the trade and focus on the
> trade and trade the plan**」
> 【原话】10:35（关于开盘第一根，呼应 Mantra 第 3 条）：「**that opening candle can be kind of
> dangerous**」；20:11「this is a **great example why you don't want to take the first candle**」

---

## 3. 第 3 集：SPX / SPY + Time Warp（`k8yKdDDqN-M`）—— 用户标的直接相关

### 3.1 Time Warp 是什么，以及三种组合

【原话】0:36「**time warp** which is super useful for having **trend on a higher time frame while
surgically entering on a lower time frame**」

| 组合 | 标的 / 到期 | 位模式 | 他的原话 |
|---|---|---|---|
| **1 分钟 K + 3 分钟 ribbon** | **SPX 0DTE** | Day levels | 2:20「scalping spx using **day levels with the one three time warp**」 |
| 1 分钟 K + 3 分钟 ribbon | SPX 精细 | **Scalp levels** | 2:29「**not available on tradingview**」（仅 ToS） |
| **3 分钟 K + 10 分钟 ribbon** | **SPY 1DTE** | Day levels | 2:43「day trading **spy using day levels with 310 time warp**」 |

【原话】3:14「**310 allows me to have surgical entries on a day trade and hold with a 10 minute
ribbon**」——【转述】即：**入场分辨率来自低周期，持仓判决来自高周期。**

### 3.2 0DTE / 日内的具体建议（这是任务点名要的）

**他自己做什么**
> 【原话】1:22「**spx i've been trading a lot of zero dte spy i've been trading a lot of one
> dte**」

**给还没练成的人的明确劝退**
> 【原话】1:22「**there's a ton of risk there so you still got to get really really good with the
> execution**」
> 【原话】1:38「the percentage gains look great especially when you see them on twitter but
> **there's a tremendous amount of execution skill that's required**」
> 【原话】1:47（**可执行的降级路径**）：「if you're **still working on execution** focus on
> **10 minute** and maybe **spy 2 to 4 dte or even further** ... **give yourself some time to
> learn how to execute**」

**禁止追高（0DTE 专属加重）**
> 【原话】4:27「**you should always wait for a pullback** ... especially if an **spx 0dte you do
> not want to start chasing these**」
> 【原话】4:40「if you chase up here ... and it comes back down here **you're probably going to
> lose 50% of your premiums just off the bat**」

**止损太紧在 0DTE 上会被震出（重要的反直觉提醒）**
> 【原话】4:53「and if you do have a stop and it's **too tight let's say 30 or even 50 on spx
> 0dte it will take you out of the trade**」

**入场锚点：3 分钟 13 EMA**
> 【原话】5:00「this **entry on the three minute 13 ema is actually pretty optimal** ... you can
> use let's say **the 34 or this call trigger as risk**」
> 【原话】7:58「you can get **surgical entries at the 13 ema between the 8 and 13 or even down to
> the 21** perfectly fine」
> 【原话】8:20（**可编码的通则**）：「the **good guideline is if you get those entries into 8/13
> in trend usually it'll be fine**」

**明确禁止：极度伸展处不是入场**
> 【原话】8:20「**when you get super extended like this though that's not an entry that's a
> pullback**」
> 【原话】8:35「**you don't want to be buying in here after a deep pullback** ... **wait for it to
> recover the 13** and then consider **entering above a breakout of resistance**」

**持仓规则**
> 【原话】6:25「you held it all the way through because it **didn't break the 13 or break and hold
> the 13 below 13**」
> 【原话】7:09「you can hold it **as long as it doesn't break the 13 ema**」

**行权价选择**
> 【原话】9:21「what's the closest **five dollar strike** just above or below so **if it's puts you
> want it to be above if it's calls you want to be below**」
> 【原话】9:52「**you don't want to go too far out especially with spx end of day** ... if it's too
> far out of the money **you'll be in serious trouble with theta**」

**尾盘 SPX 的定性（他自己的风险陈述）**
> 【原话】14:12「generally when i'm playing **end of day spx i've already made profit** so if i'm
> gonna trade it at all it's **very high risk it's basically i assume that it's going to go to
> zero**」
> 【原话】9:09 尾盘急跌的解释：「**bulls are taking their profit into the weekend**」

### 3.3 Trigger Box —— 一条他自己承认没有统计支持的可检验主张

【原话】11:45（定义）
> 「the **trigger box** is the box that's formed **between the call trigger and the put trigger**
> or the long trigger and the short trigger」

【原话】20:12（**这是本轮最值得做研究的一条**）
> 「often you'll see if you **start down at the put trigger** ... often you'll see a **move at
> least to the previous close if not to the call trigger** and often the reverse is also true if
> it's basing below the call trigger **rejects the call trigger** often you'll get back to the
> **previous close and then down to the put trigger** — **that happens more often than not
> i don't know the statistics behind it yet but i will get those** as i work out the white paper」

→ **他明说自己没有统计。** 这是一条干净的、可用现有分钟数据直接检验的条件转移概率假设：
`P(触及 previous close | 从 put trigger 起步) ` 与 `P(触及 call trigger | 已触 previous close)`。

### 3.4 Conviction Arrow = 13/48 交叉

【原话】17:24「we got a **conviction arrow firing** showing that we did a **13/48 crossover**」
【原话】17:40 ToS 因周期比（10/3）会画出 4 个箭头，TradingView 只画 1 个 —— 他认为
「**trading view will only show you one arrow which i think is actually better**」。

【原话】18:06（**交叉后的入场与风控，注意他排除了 8 和 13**）
> 「we got the crossover **pull back to the ribbon** you could have bought calls here ... or you
> could have bought calls on the **break of the opening range** ... **use the ribbon as your
> risk** ... **i probably wouldn't use the 8 or the 13** but you could use the **21 or the 34 or
> the 48** or you could use the **put trigger** or the **low of the day / pre-market low**」

【原话】18:23「the **stop should be related to your risk your contract your sizing** ... **there's
no definitive way to do this**」

### 3.5 离场：结构破坏（22:16）

【原话】22:16
> 「nothing really should scare you out of this trade until we get to the point where we get to
> this **higher high and this higher low** and then **this lower low after the higher low** and
> then we start to sort of **shift structure** ... at that point you **probably want to get out**」

【原话】22:51 两种管理法二选一：**逐级 scale out**，或 **逐级上移止损**
（「as you break through some of these levels you can **move stops**」）。

---

## 4. 第 4 集：盘前剧本完整流程（`9FtVMpKFZPs`）

### 4.1 一份好交易计划的五要素（2:23–7:41）

| # | 要素 | 【原话】 |
|---|---|---|
| 1 | **Setup / Thesis** | 2:37「need to have a **setup or a thesis**」；2:54「**if you don't know why you're in the trade then why are you in the trade**」 |
| 2 | **Trigger** | 3:12「then you need a **trigger** so some sort of **level or trend line** that allows you to know hey i should get into this trade right now」 |
| 3 | **Entry** | 3:32「you can get in **on a break** you can get in **on a retest** you can get in **on continuation** but generally you should look for some sort of **confirmation**」；4:07「having an entry ... **will eliminate chasing and eliminate fomo**」；4:41「if it's **past your confirmation criteria you want to wait for a pullback**」 |
| 4 | **Exits / 移动止损点** | 5:18「you need to have **spots to get out or to move stops**」；5:35「**scale out scale in scale out** so that you can **mechanically eliminate this concept of greed**」；5:35「it's a **long marathon not a one trade sprint**」 |
| 5 | **Stop / 风险** | 6:35「you can use **technical stops which is my preference** so you pick a **level or an ema** ... and then you determine **relative to your entry how far away that is** ... and then you can **position size relative to your risk**」 |

### 4.2 他每天开盘前依次做的事（7:41–15:40，实录）

【原话】7:41 时间与工具：
> 「i'm in **apple's preview taking a screenshot** this is what i usually do every morning take a
> screenshot right around **8:15** somewhere between **8:10 and 8:15 after i drop my son off at
> school**」
【原话】0:00 耗时：「if it's a **super clear setup** pre-market then maybe **5-10 minutes** up to
potentially **30 minutes**」；有 CPI / PPI / jobless 等新闻则拉长或事后调整。

**流程（【转述】按录像里的实际顺序归纳，每步附他的原话锚点）**

1. **载入图表，看盘前 + 昨日盘后**，标出昨天的 put/call trigger
   —— 8:00「the **put trigger from yesterday was the low**」
2. **定方向偏好** —— 8:15「right now we can kind of see **clear trend to the upside** so i'm kind
   of **favoring the upside**」
3. **同时找反向的设定** —— 8:33「if we get a downside move we kind of see maybe a **possible
   Vomy forming** here ... **we'll want to be able to play that as well**」
   （8:33 他当场指出"**two fins here forming**"，即 Vomy 的双鳍 —— 与 `SPEC_VOMY_FROM_AUTHOR.md` 一致）
4. **两个方向各出一个行权价** —— 8:33「**i always play two strikes** that i'll sort of give as an
   idea for an **upside trade or a downside trade**」
5. **画触发箭头**：上行 = 突破 38.2 位（9:58「we're going to use the **38.2 level 415.85 as our
   break to the upside**」）；下行 = 丢失 call trigger（10:09「**the call trigger as our put
   trigger**」）
6. **标目标位**：上行 mid-range（50%）→ full ATR；下行 previous close → put trigger
   —— 11:07「targeting the upside this **mid-range level** or breakout of the 38.2 and **if we
   lose the call trigger i'm expecting us to gap fill go back to previous close** if we break
   that ... should probably get down to this **put trigger**」
7. **用文本工具把行权价打在图上**（11:07）
8. **发布**：贴 Discord，行权价贴 Twitter（13:16）

### 4.3 行权价选择的硬规则（18:47–19:35）

【原话】19:02
> 「my **out of the money strike selections** tend to be pretty decent it's because i'm using **no
> more than one or two atr levels away** ... if you look at the **main atr levels typically not
> more than one main** and if you're looking at the **intermediates not more than two
> intermediates**」
【原话】19:35「**as vix starts to get lower you can also go closer to the money**」

### 4.4 VIX Pivot 的构造法（13:52–15:38）

【原话】14:15
> 「when i select a pivot i'm looking for the **atr level that it's closest to** and then the
> **closest sort of 0.5 value next to that**」
【原话】14:40
> 「**if vix goes above 17 we want to look at downside on spy or spx** and if vix continues to
> break down we'd be looking for **calls**」
【原话】15:10 收束：「basic concept **closest atr level closest whole value or 0.5 value** ...
**above is bearish below is bullish**」

### 4.5 方向反转时的换手规则（12:55）

【原话】12:55
> 「if we **broke the put trigger** this downside **i'd cut my calls and switch to puts** ...
> likewise if we were in puts and we come back up and maybe **break out from the 38.2 level** ...
> i'll probably **cut puts and start to take calls**」

### 4.6 复盘：Vomy 在真实盘中的完整序列（16:16–18:13）

【原话】16:22
> 「the **Vomy played out** ... typical Vomy setup where you've got these **fins into resistance**
> then a **breakdown of the 13 retest to the 13 break of the 48 and down**」
【原话】16:42「that happened to be **right around where the call trigger was**」
→ **这独立印证了 `SPEC_VOMY_FROM_AUTHOR.md` 的四步序列，并补上一条新信息：
衰竭那个"具名位"这次是 call trigger（+0.236），Vomy 集里举的例子是 +0.382。
即"具名位"是变量，不是常量。**

【原话】17:02（入场的周期问题 —— **注意此处有 ASR 歧义**）
> 「it's kind of hard to take an entry on this **10 minute** chart ... but early confirmation if
> you look at the **3/10** okay **close above the call trigger** and then **continuation below the
> 48** so there's a good entry right there」
> ⚠️ 这是做空交易，"close **above** the call trigger"在语境上应为"close **below**"，
> **疑似 ASR 误识**。我不替他改口 —— 标为存疑。

【原话】17:43 持仓与移动止损：
> 「if you wanted to hold all the way through **it never broke the 10 minute 13** so you could have
> held through that **moved your stops** you know once you **broke past the previous close you're
> gonna move the stops to the previous close** so **no matter what you're going to take profit in
> the money**」

---

## 5. 交叉问题的回答

### 5.1 Saty Pivot Ribbon（8/13/21/34/48）和 Ripster 云（5/12+34/50）是同一类工具吗？他同时用两个吗？

**同一类工具 —— 是。** 都是多条 EMA 组成的趋势带，用途都是"趋势状态 + 回抽入场锚 + 结构止损锚"。

**同时使用 —— 【四集里没有任何一处同时出现两套】。** 实际情况是**换代**：

| 期间 | 视频 | 用的是 | 他口中的 EMA 数字 |
|---|---|---|---|
| 2022-04 | 第 2 集 | Ripster 云 | 5, 8/9, 12, 20/21, 34, 50, 180/200 |
| 2022-05 | 第 1 集 | Ripster 云 + ATR 位 | 「the five the 8 the 12 the 21 the 3450」(8:23) |
| 2023-01 | 第 3 集 | **Saty Pivot Ribbon** | 8, 13, 21, 34, 48 |
| 2023-04 | 第 4 集 | **Saty Pivot Ribbon** | 13, 48（"10 minute 13"、"break of the 48"） |

**【转述】功能映射（这是我的推断，不是他的原话）：**

| Ripster（2022） | Saty Ribbon（2023） | 角色 |
|---|---|---|
| 5/12 fluid cloud | 8（ribbon 最快线） | 流动趋势 / 持仓紧跟 |
| 8/9 pullback cloud | **13** | **回抽入场锚** |
| 20/21 pivot | 21 | 均值 / 枢轴 |
| 34/50 trend cloud | **34 / 48** | **趋势判决线（Golden Rule 的位置）** |

→ **Golden Rule 在换代后事实上变成了"48 的破与守"**：Vomy 的确认是「break and hold of the 48」，
第 3 集的 conviction arrow 是「13/48 crossover」，第 4 集的 Vomy 复盘是「break of the 48 and down」。
**48 接替了 34/50 云成为体制判决线。**

**【未知】**：四集里他**从未说过**"我把 Ripster 云换掉了"或"我两个都挂"。
上表是按视频时间线与他实际口述的 EMA 数字推断的。若要确认，需要更晚期的视频或他的 satyland 文档。

### 5.2 Ripster 的云在他体系里怎么用 —— 5/12 与 34/50 的分工

**【原话】层面的答案（第 1 集 7:02，最清楚的一句）：**
> 「if it's **above the 3450 and above the 512** that's a **little extra bullish** and that'll give
> you a little bit more confidence. that in fact is when the **trend label will go green**」

→ **34/50 = 体制（regime），是必要条件；5/12 = 时机（timing），是加分项。**
两者同向 → ATR Levels 指标的 trend label 变绿。这是一条**指标内部已实现的、可直接读取的合取**。

---

## 6. 汇总：可编码布尔规则

### 6.1 日内多头（第 1 集，10 分钟图，2022 Ripster 版）

```
【必要 E1】close > EMA34/50 云上沿        （Golden Rule；Ripster 34/50）
【必要 E2】10m close > call_trigger       （+0.236）
【必要 E3】atr_covered_pct < 0.70

【理想 I1】close > EMA5 > EMA8 > EMA12 > EMA21 > EMA34 > EMA50   （全堆叠 = "super bullish"）
【理想 I2】squeeze_on 且方向向上
【理想 I3】RSI 超卖

【入场】禁止在突破当根进场。等回抽：
        入场A（首选）= 触及 EMA8/9 云
        入场B（次选）= 触及 EMA21（均值枢轴）
        （3 分钟图上锚点上移：pivot 与止损锚都变成 EMA34/50）

【止损】他给的是候选集，非唯一解，且明说取决于行权价/到期日：
        {EMA34/50 云下沿, call_trigger, previous_close, -1.0 ATR 位, VWAP, 保本}
        3 分钟图上的默认表述 = "跌破 34/50 就砍"

【目标】T1 = mid_range (+0.5)  → 部分止盈
        回抽 EMA21 → 可加回
        T2 = mid_range 二次    → 再减
        T3 = full ATR (+1.0)   → runner
        （他给的期望：「solid trend 至少到 mid-range，不然就是 full ATR」）

【空头】以上全部镜像（put/short trigger、超买、squeeze 向下、-0.5 / -1.0 ATR）

【明确禁止】
  × 开盘前 10 分钟不交易
  × 横盘/chop 不交易（5/12 反复翻色 且 34/50 翻回 = chop）
  × 突破后追（"never chase ... wait for a pullback"）
  × 有动量时逆势（动量定义：价格根本不回测 34/50）
  × ATR 覆盖 > 70% 后开新仓（>90% 变红）
  × 不看 P&L，只看图
```

### 6.2 SPX 0DTE 剥头皮（第 3 集，1 分钟 K + 3 分钟 ribbon，2023 Pivot Ribbon 版）

```
【前提】3 分钟 ribbon 处于趋势（8/13/21/34/48 排列），且在 Day levels 的 trigger 之上/之下
【入场】回抽至 3 分钟 EMA13（最优）；EMA8–EMA13 区间内均可；下探 EMA21 也可接受
        通则："entries into 8/13 in trend usually it'll be fine"
【止损】EMA34，或 call/put trigger
        ⚠ 明确警告：0DTE 上 30%–50% 的百分比止损"会把你震出去"
【持仓】只要不"break and hold below the 13"就继续持有
【目标】下一个具名位（他示范：从 4083 进 → mid-range → 4090 减）；逐级 scale out
【行权价】最近的 $5 整数位；puts 取上方、calls 取下方；尾盘 SPX 不许远虚（theta）

【明确禁止】
  × 0DTE 追高（"do not want to start chasing"；追了再回来 ≈ 亏掉 50% 权利金）
  × 极度伸展处入场（"that's not an entry, that's a pullback"）
  × 深度回撤后直接抄底 —— 必须先"recover the 13"，再等突破阻力
  × 尾盘 SPX 当成正常交易（他自己按"归零"定价）
  × 执行力不够就别做 0DTE —— 降级到 10 分钟 + SPY 2–4DTE
```

### 6.3 盘前剧本（第 4 集）

```
T-75min（约 8:10–8:15）：截图 → Apple Preview
1. 标昨日 call/put trigger 与盘后高低
2. 定主方向（trend bias）
3. 同时找反向设定（Vomy / 双顶双底）
4. 双向各选 1 个行权价：距现价 ≤ 1 个主 ATR 位，或 ≤ 2 个中间位
   （VIX 越低越靠近平值）
5. 画触发箭头：上行 = 破 +0.382；下行 = 丢 call trigger
6. 标目标：上 = mid_range → full ATR；下 = previous_close → put_trigger
7. 算 VIX pivot = VIX 最近的 ATR 位 → 取最近的整数或 .5
   VIX > pivot ⇒ 偏空；VIX < pivot ⇒ 偏多
8. 把行权价打在图上，发布

盘中：
- 破 put trigger ⇒ 砍 calls 换 puts；破 +0.382 ⇒ 砍 puts 换 calls
- 冲过 previous close 后，止损上移到 previous close（锁定实值）
- 只要没破 10 分钟 13 EMA 就可以一直持有
```

---

## 7. 这四集对本项目研究的直接影响

### 7.1 得到了三条以前没有的、硬的、可编码的过滤条件

1. **ATR 覆盖率 < 70%** —— 一个明确的数值门槛，指标里已有实现（绿/黄/红）。
   以前我们从没把它当过滤器测过。
2. **开盘前 10 分钟不交易** —— 一个明确的时间窗排除。
3. **"trend label 变绿" = (close > 34/50) ∧ (close > 5/12)** —— 一个已实现的合取。

### 7.2 得到了一条他自己承认没验证过的、可直接检验的统计主张

第 3 集 20:12 的 **trigger box 遍历假设**，他原话「**i don't know the statistics behind it
yet**」。这是本轮最好的研究标的：不需要复杂合取，不需要 EMA 形态，只需要 ATR 位与分钟价格序列，
样本量会很大。建议列为下一个实验。

### 7.3 修正了上一轮的一个隐含假设

`SPEC_VOMY_FROM_AUTHOR.md` 记的衰竭位是 +0.382。第 4 集 16:42 的实盘复盘里，
衰竭位是 **call trigger（+0.236）**。
→ **"具名位"是变量而非常量**，Vomy 检验时不能把 0.382 写死。

### 7.4 必须同时守住的诚实

1. **这些规则依然一次都没被检验过。** 四集都是"讲解 + 事后挑选的样例图"，
   没有任何一集给出胜率、样本量或回测。他 2023-01 提到要写 white paper，
   **四集里没有任何一处给出统计数字**。
2. **止损在第 1 集里不是唯一的** —— 他给的是候选集并把选择推给"你的行权价与到期"。
   这意味着**这套方法在止损维度上不是一个完整的机械系统**，我们做检验时必须自己钉死一个
   止损定义，并明说那是我们钉的，不是他说的。
3. **2022 与 2023 的 EMA 周期不同**（5/12+34/50 vs 8/13/21/34/48）。
   合并两代规则会造出一个他从未使用过的混合系统。**要么按 2022 版测，要么按 2023 版测。**
4. 他明确的通用性主张（第 2 集 17:02，"所有周期同理"）是可证伪的，也值得单独测。

---

## 8. 附：本轮取回失败与成功的方法记录（供下次复用）

| 方法 | 结果 |
|---|---|
| InnerTube `player` API（ANDROID / IOS / TVHTML5 / ANDROID_VR / WEB_CREATOR 等 10 种客户端） | ✗ `FAILED_PRECONDITION` 或 `LOGIN_REQUIRED` |
| 网页 HTML 抽 `ytInitialPlayerResponse` → `captionTracks[].baseUrl` | 拿得到 URL，但 GET 该 URL 返回 **HTTP 200 + 0 字节**（含 fmt=json3/srv3/vtt、带 cookie jar、带 Referer 均无效） |
| InnerTube `get_transcript` 端点（含完整 ytcfg INNERTUBE_CONTEXT + API key + 全套头） | ✗ `FAILED_PRECONDITION` |
| Invidious（inv.nadeko.net 等 6 个实例） | API 通，但 captions 返回 0 字节（同样撞 PO-token） |
| Piped（3 个实例） | ✗ 502/526/subtitles=null |
| 第三方站（youtubetotranscript / tactiq / downsub / notegpt / kome / youtubetranscript.com） | ✗ Cloudflare 挑战 / App Check / 522 / login expired |
| r.jina.ai reader | ✗ 401（IP 段被封） |
| **yt-dlp 2026.07.04（venv pip 安装）`--skip-download --write-auto-subs --sub-format json3`** | **✓ 四集全部成功** |

→ **结论：2026-07 起，取 YouTube 逐字稿只有 yt-dlp 这一条路可靠。** 手写 InnerTube 请求已全面失效。
