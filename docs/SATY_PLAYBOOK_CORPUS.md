# Saty 剧本语料库（#ideas 频道原文逐字，2026-07-24 采集）

> 这不是转述。下面每一条都是 Saty 本人在 Saty+ Discord `#ideas` 发的**盘前帖原文**，
> 用来反向工程他的决策格式。项目此前的失败是"发明信号"，这份语料的作用是证明
> **他根本不发明信号——他写的是双向剧本**。

## 一、原文（按时间倒序）

**INTC IV Flush 7/24/2026**（本周五，最新）
> Upside more interesting on this one. **If** we continue to **hold pre-market support**
> and **break trend back over pre-market highs**, we can **head toward 110 and ER AH highs**.
> **Break of the pre-market support** and we can **head back to PDC**.

**QQQ Day Trade 7/20/26 705c | 695p** ✅Complete
> Marginally stronger looking in pre-market compared to SPY but similar look.
> **In 10m continuation** can **head to the midrange on a GG play**.
> **Break of long trigger and Vomy** takes us **back down to PDC and 695 key level**.

**NVDA Day Trade 7/20/26** ✅Complete
> Similar to SPY in PM. Almost an identical look. **Possible GG open if we open here or above.**
> Clear resistance from Friday overhead which is also the **H21 (RTH)**.
> **In 10m continuation** can look for a **GG completion** using 207.5c or 210c.
> **If trend breaks** look for a **10m Vomy down to PDC** and then toward 200 key support and Friday LOD.

**SOFI 19.5c/20c | 18.5p** ✅Complete
> Nice **10m trend** pre-market. Can **revisit Friday's highs in continuation**.
> **Break of trend** and we can **head back to PDC and overnight lows**.

**AAPL 320c 7/17**（波段）✅Complete
> We have some **hourly RTH compression** with a ascending triangle resistance around
> **+1 Monthly ATR / ATH**. **Holding H21**. **Breakout from ATH** this week and we can see 320.

**PANW IV Flush 6/3/2026** ✅Complete
> Some **tight consolidation** heading into open. **Breakout and continuation** of this recovery
> trend and we can **head back to PDC and 300 psych and higher**.
> **Failure of -1 ATR** and we can **revisit overnight lows**.

**AMZN 245c | 247.5c** ✅Complete
> AMZN nice setup pre-market. Can get to **+1 ATR** pretty quickly if it breaks out.

**AMZN Daily IHS**（波段）❌Invalidated
> Amazon has a nice IHS look on the daily. **Measured moves** takes us into the **daily gap above around 270**.

**NVDA 220c 6/26**（波段）❌Invalidated
> Looking to **breakout from this hourly supply** for a move to **220 by EOM**.

## 二、结构提取：每一篇都是同一个模板

```
[1] 语境        当前结构状态（盘前趋势 / 压缩 / 相对大盘强弱 / 是否已在 GG 内）
[2] 多头分支    IF  <守住某具名位 or 上破某具名位 or 10m 延续>
                THEN 目标 = <下一个具名位>, <再下一个具名位>
[3] 空头分支    IF  <跌破某具名位 or 趋势破坏(Vomy)>
                THEN 目标 = <下方具名位>, <再下方具名位>
```

**铁律级观察（这三条直接否定了我们旧系统的设计）：**

1. **目标永远是具名位，从来不是 R 倍数。** 他说 "head toward 110 and ER AH highs"、
   "back to PDC and 695 key level"、"+1 ATR"——**没有一次**说"目标 2R"。
   我们旧系统用 T1/T2 = 风险的倍数，方向就错了。
2. **条件永远是结构性的**："hold X"、"break of X"、"trend breaks"、"10m continuation"。
   没有一次是"某指标金叉"或"评级 A/B/C"。
3. **永远两个分支，事先写好。** 他不预测方向，他把两个方向的剧本都写完，然后看市场选哪条。
   这正是用户说"图上看不到价值"的解药：**没有信号的时候，剧本本身就是价值。**

## 三、具名位词表（他实际使用的全部位类型）

| 术语 | 含义 | 我们有吗 |
|---|---|---|
| PDC | previous day close = ATR 锚 | ✅ 有 |
| long/short trigger | ±0.236 ATR | ✅ 有 |
| GG / GG completion | 0.382 → 0.618 ATR | ✅ 有 |
| midrange | 0.5 ATR | ✅ 有 |
| ±1 ATR | 全 ATR 幅 | ✅ 有 |
| +1 Monthly ATR | **月线级** ATR 位 | ❌ 缺（只有日线级） |
| **H21 (RTH)** | **小时 21 EMA，只用 RTH 数据算** | ❌ 缺 |
| pre-market high/low | 盘前高低 | ❌ 缺 |
| overnight low/high | 夜盘高低 | ❌ 缺 |
| PDH / PDL / Friday's high / LOD | 前日与上一交易日高低 | 部分有 |
| psych level | 整数关口（300、200） | ❌ 缺 |
| ATH / 日线缺口 | 历史新高、未补缺口 | ❌ 缺 |

**缺口清单就是 v14 的工作量清单。** 其中 **H21(RTH)**、**盘前高低**、**夜盘高低**
三项出现频率最高，优先级最高。

## 四、其他可操作观察

- **他记分**：每篇帖子带 ✅Complete / ❌Invalidated 标签，公开追踪结果。
  这是我们"前向账本"的同类物，但他的口径是"剧本有没有兑现"，不是"赚了多少 R"。
- **"Possible GG open if we open here or above"** —— 直接对应 tesrak 统计里
  开盘触发档 90.9% 的完成率。他是在用基准率下注，不是在猜。
- **IV Flush** 是他反复使用的一个 setup 名（财报后隐波塌缩），属于个股专用，与 SPX 无关。
- **注意标的差异**：他 #ideas 里绝大多数是个股（INTC/NVDA/AMZN/AAPL/SOFI/PANW），
  SPX/SPY 出现较少。我们做的是纯 SPX500——**他的个股 setup 未必平移得过来**，
  但 ATR 位地图 + 双向剧本这个**框架**是标的无关的。

---

## 五、2026-07-24 当日一手补充（#notes 实盘解说 + 周报）

### 5.1 他的实盘解说（11:25–11:50 ET，逐字）

> 11:28 「PDC and LOD test possible if this continues」
> 11:34 「Here's PDC」　11:35 「Approaching LOD」
> 11:35 「**Can leave runners, good scale out here**」
> 11:37 「**3m extreme here. 10m has room**, but maybe some consolidation, pullback possible」
> 11:41 「We lose LOD, **put trigger** can happen quickly. Expecting demand/support here but this looks selly」
> 11:47 「I think this bounce here with **3m extreme at demand/support** makes a lot of sense.
> 　　　 Can watch for 3m resistance again. **I'm going to call it here.**」
> 11:50 「@everyone Last two weeks have been on **hard mode**. Once this daily box resolves, should get a little easier.」

**四条可编码的观察：**

1. **「3m extreme / 10m has room」= 双周期 Phase Oscillator 读数。** 这是他判断
   "该减仓还是该拿住"的核心句式：执行周期极端 → 减仓；上级周期仍有空间 → 留 runner。
   我们有 3m/10m 这一对，但**从来没把 Phase 读数配对呈现**。
2. **减仓语言是「scale out + leave runners」**，与我们 T1/T2/runner 的三段结构一致，
   但他的触发是**到达具名位 + 执行周期极端**，不是 R 倍数。
3. **他 11:47 收工**，与 #orientation 里自述的
   「I focus mostly on trading the **first couple hours off the open**,
   aiming to be able to be **done for the day by 12pm EST**」完全一致。
4. 目标全部是具名位：PDC、LOD、put trigger、demand/support。

### 5.2 周报 7/26 的 SPX 段（逐字）

> "We are still in the **monthly trigger box** roughly between 7400 and 7600.
> Weaker stance going into next week **under D21 and H200**. I'm leaning bearish
> as long as we stay **under the bearish D21 and the monthly pivot**. On further
> weakness **below the Swing short trigger** we have a **clear path level-to-level
> down to recent demand. This is also the Weekly 21.** Selling exhaustion can set up
> an **hourly (RTH) divergence** for some mean reversion."

QQQ 段："Bounced **−1 Monthly ATR**, rejected **bearish daily ribbon** … near the **W21** …
Below that can see **−1 Quarterly ATR**."

**下周关键事件（他列的）**：周二 Consumer Confidence；**周三 FOMC 利率决议（62.1% 按兵不动）+ Fed Chair Warsh**；
周四 PCE/GDP/失业；周五 Chicago PMI。财报：周三盘后 MSFT/META/ARM/QCOM，周四盘后 AAPL/AMZN。

### 5.3 由此新增的词表缺口（比第三节更严重）

| 术语 | 含义 | 我们有吗 |
|---|---|---|
| monthly trigger box / monthly pivot | **月线** ATR 锚 ±0.236 | ✅ 已补（`mtf_levels.py`） |
| −1 Monthly ATR / −1 Quarterly ATR | **月/季线** ATR 位 | ✅ 已补 |
| W21 / D21 / H200 / H21(RTH) | 周/日 21 EMA、小时 200/21 EMA | ❌ **仍缺** |
| Swing short trigger | 波段周期的触发位 | ❌ 仍缺 |
| demand / supply zone | 需求/供给区 | ❌ 仍缺（非 ATR 类） |
| hourly (RTH) divergence | 小时线 RTH 背离 | ❌ 仍缺 |
| 「3m extreme / 10m has room」 | **双周期 Phase 配对读数** | ⚠ 有指标无配对呈现 |

**注意**：`REGIME_MONTHLY_BOX_2026-07-25.md` 已证明「月线箱内 = 难做」**在 20 年样本上不成立**。
多周期位应当作为**地图与目标**使用，不要据此建 regime 过滤器。
