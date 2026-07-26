# Vomy 设定 —— 原作者逐字定义（2026-07-26）

> 来源：Saty Mahajan YouTube，《The "Vomy" Setup and How to Spot and Trade it
> Using Saty Pivot Ribbon》（视频 ID `eYeUS5wRwKg`，6:33，30K 播放，3 年前）。
> 逐字稿由浏览器取回（314 段）。**证据等级 [A]：原作者本人口述。**
> 此前所有关于 Vomy 的记载都是三手推测；本文取代它们。

---

## 一、原话摘录（逐字，带时间码）

**是什么**
> 0:40「the vomi setup in a nutshell is effectively a **EMA multi-EMA crossover
> setup, a reversal setup**, that is fairly straightforward to see when you're
> using the pivot ribbon」

（名字来源：1:21「**vomit dolphin** or vomi」——形态像海豚：两个背鳍=双顶，
鼻子=回抽，然后"吐出来"=破位下跌。）

**前置条件：必须先有清晰趋势，五条 EMA 全排列**
> 1:46「typically it'll happen when you have some **nice clear trend** so you have
> **stacked EMAs: 8 above 13, 13 above 21, 21 above 34, 34 above 48**」

**衰竭发生在一个具名位上（关键！）**
> 2:34「you get clear trend, forms these fins, **you meet resistance — so at this
> point it's the 38.2 level**」
> 2:03「usually you'll get a **double top**, or sometimes you'll even just get a
> **single fin** here where it'll just meet resistance」

**破位序列**
> 2:13「and then you'll start to **break down the 8 and the 13 EMAs**, maybe even
> **test down as far as the 21**, **retest the 8 and the 13**, and then break down
> and **test the 48**」

**入场（这是我们缺了几周的东西）**
> 2:51「and this **retest of the 13 is often a really good spot to get in**, so you
> can definitely get in on this **first retest or second retest of the 13**」
> 3:15「usually if it is an actual vomy setup, **that 13 is a really elite spot to
> get in because you're going to get most of the move down**」

**止损**
> 3:03「and you know use **the level above** or use **the actual 13 EMA as your
> risk** — **closing above that, alright, get out**, you can reevaluate」

**确认（第二个入场点）**
> 3:34「in order to actually have a vomy be **confirmed** you have to get this
> **break of the 48** — it's a **break and hold of the 48 confirms the move**,
> so you can actually wait for the break of the 48 and you can also get in on the 48」
> 3:49「**don't get in after the 48 break** … after you've confirmed **full close
> below the 48** you can get in on the **next pullback**」

**它到底在做什么**
> 4:03「as that's happening we start to get this **multi-EMA crossover where the 8,
> the 13, the 21, 34 and the 48 all cross over each other and now form a bearish
> ribbon** — so **to anticipate that is what the vomy setup really does**, gives you
> the ability to **anticipate a really really bigger than expected move**」

**共振条件**
> 4:23「and usually that'll be **in confluence with some sort of squeeze** as well,
> and usually you'll be in sort of **overbought or oversold conditions**」
> 4:44「**that's the ultimate scenario**: when you have overbought conditions,
> squeeze, momentum moving to the downside, you've got the **break of the 13,
> retest of the 13, break of the 48** — that really kind of puts things together」

**目标 = ATR 位**
> 5:24「and of course you can **pair it with ATR levels to take profit at these
> levels** — so here we're taking profit at the **previous close**, here we're
> taking profit at the **put trigger**」

**为什么在 SPX/SPY 上做空侧特别好（与 0DTE 直接相关）**
> 5:02「downside moves are really nice … this is why everybody likes puts so much on
> SPY and SPX, because you get the benefit of the underlying moving and your premium
> is moving with the underlying, **but you also get the benefit of the VIX usually
> rising, so that'll boost the premiums**」

**Yummy = 完全镜像**
> 5:38「the inverse is conceptually the same: you get a move here, a little fin,
> **meets support instead of resistance**, pulls back, starts to break the 13」

**风控口吻**
> 6:04「you just need to **wait for your confirmation**, but you can always get in
> early and have some **tight risk** on there」

---

## 二、可编码规则（完整）

```
【前提】五条 EMA 多头排列：EMA8 > EMA13 > EMA21 > EMA34 > EMA48
        （注意：是 5 条，不是我们之前以为的 8/21/34 三条）

【1 衰竭】价格在一个具名 ATR 位处遇阻（原话举例 = +0.382），
        形成双顶（two fins）或单顶（single fin）

【2 首破】收盘跌破 EMA8 与 EMA13；可能下探 EMA21

【3 回抽】价格回抽 EMA13（自下方）
        ├─ 入场A（激进）：第一次或第二次回抽 EMA13 时做空
        └─ 止损A：收盘站回 EMA13 上方（或位于其上的那个具名位）

【4 确认】收盘跌破并站稳 EMA48（break AND hold）
        ├─ 入场B（确认）：破 48 当时，或"完整收盘于 48 下方后的下一次回抽"
        └─ 明确禁止：48 破位之后【追】（"don't get in after the 48 break"）

【目标】ATR 位，逐级止盈：PDC（锚）→ put trigger（−0.236）→ 更低具名位

【共振加分】squeeze 压缩 + 超买（Phase 极端）同时出现 = "ultimate scenario"

【Yummy】以上全部镜像（支撑代替阻力，做多）
```

---

## 三、这如何改写我们的研究结论

### 3.1 用户的两条主张，被原作者的规则逐条印证

用户说：
> 「1. 趋势肯定是主导的。2. 趋势在关键位出现反转，往往能带来很高的盈亏比，
> 胜率不需要特别高。」

原作者的规则：**前提是趋势（五条 EMA 排列），触发是关键位（0.382）处的衰竭反转，
止损是 EMA13 收盘价（很紧），目标是 PDC 与 put trigger（很远）。**
——这就是"高盈亏比、不要求高胜率"的字面实现。

### 3.2 我上一轮的研究为什么什么都没测出来

**因为我把一个五重合取拆成单项分别测了。**

| 我测的 | 结论 | 问题 |
|---|---|---|
| ribbon 状态 → 方向 | z≈0，无 | 测的是"趋势存在时价格往哪走"，而 Vomy 用趋势做**前提**，用**趋势破坏**做信号 |
| 位 → 穿越/拒绝 | 平滑曲线，无台阶 | 测的是所有触位事件，其中绝大多数**不在趋势末端**，也没有 EMA 破位与回抽 |
| 安慰剂梯子 | 具名比例不特殊 | 只证明了"孤立地看，0.382 不比 0.40 特殊"——**没有证明"趋势衰竭发生在 0.382"这件事不特殊** |

**合取从未被测过。** 这是一个真实的研究缺口，不是狡辩：
测"字母 q 能否预测单词"当然得零，但这不能证明 "qu" 无意义。

### 3.3 必须同时守住的诚实

1. **规则现在是清楚的，但仍然一次都没被检验过。** 原作者说它好用，
   用户直觉它好用，两者都不是证据。
2. **正确的零假设仍然是几何零假设**（止损距离/(止损+目标)），不是 50%。
   目标远、止损近本身不产生期望值——必须跑赢几何基准。
3. **样本会很少**：五重合取在 60 天 5 分钟数据上可能只有个位数事件。
   需要更长的分钟级数据（TradingView 导出）才能定论。
4. 视频是 3 年前的；`SPEC_PIVOT_RIBBON` 指出免费版 ribbon 是 8/21/34、
   Pro 版才有 13 与 48。**Vomy 规则依赖 13 和 48，所以必须用 5 条 EMA 的版本。**

---

## 四、下一步（已在跑的第二轮工作流之外新增）

1. 用**本文的完整合取规则**重做 Vomy 检验，对几何零假设（正在跑的那个
   agent 用的是用户的简化描述，覆盖不到"回抽 13"与"破并站稳 48"两步）。
2. 补看另外三集：《Day Trading with Saty ATR Levels and **Ripster EMA Clouds**
   including **Setups, Entries, and Exits**》（24:33）、
   《**Ripster EMA Clouds Tutorial and the Golden Rule of Trend**》（26:14）、
   《Saty ATR Levels & Pivot Ribbon: **Scalping and Day Trading SPX and SPY**
   with Time Warp》（25:42）——后两集直接对应用户的标的与工具。
3. 取更长的分钟级历史（TradingView 导出 CAPITALCOM:SPX500）以获得足够样本。
