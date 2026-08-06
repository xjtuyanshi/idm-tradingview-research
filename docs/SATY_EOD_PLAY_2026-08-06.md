# Saty 的 EOD 剧本：2026-08-06 收盘前 20 分钟全程逐字

> 来源：Saty+ Discord #notes 与 #chat，2026-08-06。时间已换算为 **ET**（原始显示 PT+3）。
> 这是他当天**唯一**的一笔交易，+352.94%。用户原话：「他最后那 10 分钟的操作非常好，
> 人家就很会选这个时间。你这个能不能消化一点？」——本文就是消化。

## 一、时间线（逐字）

| ET | 原话 / 事件 |
|---|---|
| 09:59 | #notes：「**Saving yourself from Chopzilla is just as good as having a nice trade**」 |
| 10:04 | 「There are spicier variants of this in chat, but **when the Ribbon is Thin, it's harder to Win**」 |
| 11:31 | 「@everyone **No trades for me this morning.** Definitely some tradable action, but **nothing I loved**. …**regroup for EOD in chat** and see if there is something worthwhile.」 |
| 15:19 | #chat：「You like trigger boxes? **How about a trigger box inside your trigger box?**」+ 图（全天压缩套在更大压缩里）|
| 15:22 | 「**As long as you manage expectations you can trade anything**」「it's when we don't manage those expectations things get bad」 |
| 15:27 | 「Current LB」+ 图 → 「**shaken**」（他在盯 Volume Leaderboard）|
| 15:32 | 发 **VIX 10m 图**（全下午走低）|
| 15:36 | 「Can't wait for **nothing to happen until the last 30 seconds** and then everyone posting 69k%ers on twitter」（他清楚 EOD 的脾气，先拿它开玩笑）|
| ~15:40 | **入场 SPXW 0DTE 7710C**（他叫它「10c」；当时 SPX ≈ 7700–7705，轻虚值）|
| 15:42 | 「**It's working**」 |
| 15:44 | 「**1m accum**」+ 1 分钟图（吸筹形态）；「Wanted that but happened too fast」 |
| 15:54 | 仓位卡截图：**SPXW260806C7710，+352.94%**；「not bad」 |
| 15:58 | 「**Scale longs again**」 |
| 15:59 | 「**runners only**」 |
| 16:02 | 「**10c was my one and only trade today**」 |
| 16:03 | 群友：「you honestly **stepped out at the perfect time and then came back when things pick up**」 |

当日背景：SPX 全天窄幅（我们 3m 数据：高 7742.8@10:21，低 7697.8@12:15，午后一路
阴跌到 ~7700），收盘拉回 7715.6。**7710 整十位一档成交近 100 万张**
（群友：「I don't know if I ever seen almost 1,000,000 volume on one strike」）。

历史佐证（这不是孤例，是他的常规剧本）：
- 07-24：「Solid plan. **10c probably better than 20c.** But worked well!」
- 07-27 15:28 ET：「**Maybe 10c gets a shake before the end of the day**」

## 二、这笔交易的解剖：为什么"会选时间"不是玄学

**1. 时间选择 = theta 表的另一面。**
我们 07-28 用真实 0DTE 链算过：距收盘 3.5 小时持仓的 theta 表，拖 3 小时吃掉 89% 权利金。
他反着用同一张表：**15:40 的 0DTE 轻虚值 call 已经被 theta 榨到地板价**——
买它的人几乎不付时间价值。此时的期权不再是"会衰减的资产"，是**便宜的凸性彩票**：
15 分钟里 SPX +15 点 → +353%。我们的 theta 时钟说"别把中午的仓拖进下午"；
他的 EOD 剧本说"等 theta 把票价打完再上车"。**两者是同一条物理定律的两面，不矛盾。**

**2. 方向不是猜的，是四个可观察事实的合取：**
- **全天压缩**（trigger box inside trigger box）= 能量攒着没放；
- **VIX 全下午走低**（15:32 他专门发图）= 波动率不抵抗上行；
- **1m 吸筹**（15:44 "1m accum"）= 微观结构在买；
- **LB：7710 一档 ~100 万张** = 收盘磁吸位在**上方**。
四件事都是入场前可见的。没有一件是预测。

**3. 仓位天然小，期望值天然管理。**
几美元的票，全亏就是全亏但绝对额小——这就是他 15:22 说的
"manage expectations"。赔率结构：亏 1 赚 3.5，靠的不是胜率是凸性。

**4. 纪律闭环：**
早上「nothing I loved」→ 全天 **0 笔** → 只在 EOD 出手 **1 笔** →
15:58 scale → 15:59 runners only → 16:02 复盘。
加上我们 07-28 的观察（他 11:37 收工），完整图景是：
**他只在开盘后与收盘前两个窗口出手，中间那四个小时他在讲课、带孩子、发梗图。**
「会选时间」的全部内容就是：**不在没有脾气的时段跟市场耗。**

## 三、消化进系统的方式（诚实边界）

**能做的（已做，v15.6.2）：**
- 面板的 theta 时钟行在 **15:30 ET 后切换成「EOD 窗口」**：距收盘分钟数、
  今日振幅占日 ATR 百分比（压缩判定的代理）、上下最近**整十位**（磁吸候选）。
  不加新行、不加信号——只把他入场前看的那几个事实摆出来。
- 本文档入库，作为语料。

**不做的（以及为什么）：**
- **不做 EOD 自动信号**。四合取里最关键的两件（LB 的百万张成交、1m 吸筹的判读）
  一个拿不到数据（期权链）、一个是主观判读。剩下两件（压缩+VIX）单独不构成入场。
  把它做成信号 = 又一个未经验证的 setup，这个项目刚为此付过学费。
- **theta 时钟的 30 分钟强平不放松**。它保护的是"中午的括号单别拖死"；
  他的 EOD 票是**在 15:40 新开的、几块钱的、买定离手的彩票**——两码事。
  如果用户想手动打 EOD，面板会把事实给他，决策留给人。

## 四、给用户的一句话

他"会选时间"，选的不是时刻，是**期权结构最有利、且事实（压缩/VIX/LB/吸筹）
恰好排成一排的那 20 分钟**。系统能替你把事实摆好，扣扳机的那个判断——
「今天这个 EOD 有没有脾气」——目前还只有人做得了。
