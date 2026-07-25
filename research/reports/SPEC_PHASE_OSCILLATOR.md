# SPEC — Saty Phase Oscillator：精确定义、分区、Compression 触发条件与数值验算

> 日期：2026-07-25
> 代码：`research/satylab/phase_fix.py`（新增，未改动 `indicators.py`）
> 验算脚本：`research/phase_spec_check.py`
> 结论等级：**公式=已钉死（一手源码）**；**用法=作者公开表述转述**；**数值分布=描述性统计，非边缘证据**

---

## 0. 一句话结论

我们原来的猜测实现 **错了两处**，导致数值约 **3 倍过热且未平滑**：

| | 我们的猜测（`indicators.phase_oscillator`） | 官方真实定义 |
|---|---|---|
| 分母 | `ATR(14)` | **`3.0 × ATR(14)`** |
| 输出 | 原始比值 | **原始比值再取 `EMA(3)`** |

后果可量化：**旧实现有 60.1% 的日线 K 落在 ±100 轨之外**（`n=5010`），
轨线形同虚设；**修正后只有 2.2%**（`n=5008`，两比例 `z=−62.6`）。
这直接印证了你的抱怨"图上看不到有用价值"——我们画的那条线和你 TradingView 上
那条线根本不是同一个量。

---

## 1. 证据链与出处等级（先说我凭什么这么讲）

| # | 来源 | 取得方式 | 等级 |
|---|---|---|---|
| S1 | **TradingView 线上已发布脚本的 Pine 源码本体**，`PUB;f27506d00fc64f30b880835f6847ac6e`，`created 2026-01-11T02:16:53Z`，脚本头 `// Saty Phase Oscillator / Copyright (C) 2022-2026 Saty Mahajan` | 直接调用 TradingView 自家 `pine-facade` 公开端点取回（脚本 access = `open_no_auth`） | **一手、权威、当前线上版** |
| S2 | `rishid/thinkscripts` 的 thinkScript 版 `saty_phase_oscillator.tosts`（脚本头同为 Saty 版权声明） | GitHub raw | 一手移植，独立于 S1 |
| S3 | `krithin98/Whispr` 里的 Pine 副本（`Copyright (C) 2022-2024`，即 S1 的前一代） | GitHub 代码搜索 | 独立副本 |
| S4 | useThinkScript 论坛 2025-01-18 帖子中粘贴的同一段公式 | 网页 | 第四份独立副本 |
| S5 | 官方产品页 `satyland.com/phaseoscillator` 的分区命名与用法文案 | 网页 | 作者本人表述 |
| S6 | TradingView 脚本页的 Release Notes（2024-06→2026-01 共 6 条） | 网页 | 作者本人变更记录 |
| S7 | Saty 的 Discord 实盘用语（2026-07-24 #notes），已记录于 `docs/SATY_RIPSTER_METHOD_STUDY.md` §1.4 | 用户一手抄录 | 作者本人用法 |

**S1–S4 四份独立来源在公式上逐字一致。** 这一条不是猜测，是钉死的。

依 `NOTICE.md`「不分发第三方指标源码」的约定，本报告**只引用承载定义的那几行**，
不在仓库内保存完整副本。任何审查者可自行取回全文：

```bash
curl -sL -A "Mozilla/5.0" \
  "https://pine-facade.tradingview.com/pine-facade/get/PUB%3Bf27506d00fc64f30b880835f6847ac6e/last" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['source'])"
```

**Release Notes 显示公式自 2024-06 起未再变动**（6 条更新分别是：加 alert 标签、
加 ±61.8 均值回归信号、加 ±100 交叉点、Time Warp、Clean 配色、修 ETH/RTH bug），
所以 S2/S3/S4 的旧副本与 S1 在数值上等价。

---

## 2. 精确公式（回答问题 1）

官方源码承载定义的四行（逐字，Pine v5）：

```pine
pivot      = ta.ema(close, 21)
atr        = ta.atr(14)
raw_signal = ((price - pivot) / (3.0 * atr)) * 100
oscillator = ta.ema(raw_signal, 3)
```

逐项钉死：

| 项 | 答案 | 备注 |
|---|---|---|
| 分子 | `close − EMA(close, 21)` | 是的，就是 close 减 21EMA。`price` 在 Time Warp 关闭时即 `close` |
| 分母 | **`3.0 × ATR(14)`** | `ta.atr` = `ta.rma(ta.tr(true), 14)`，即 **Wilder/RMA 平滑**，与我们 `atr_series` 一致 |
| ATR 周期 | 14 | |
| ATR 用哪个周期的？ | **与图表同周期**（或 Time Warp 选定的周期），**不是日线 ATR** | 见下方"最关键的一条" |
| 缩放 | `× 100` | 于是 **±100 ⇔ 收盘价距 21EMA 恰好 3 个 ATR** |
| 平滑 | 对 `raw_signal` 再取 **EMA(3)** | 官方页称这层平滑提供"信号前端的短期趋势"，叫 **Compass** |
| 取整 | thinkScript 版 `Round(..., 2)`；Pine 版不取整 | 仅显示差异 |

### 最关键的一条：分母的 ATR 是"本周期 ATR"，不是日线 ATR

Saty ATR Levels 用的是**日线 ATR + 前收锚点**；Phase Oscillator 用的是
**当前图表周期自己的 ATR(14) 与自己的 EMA(21)**。二者是两把完全不同的尺子。

这正是「**3m extreme, 10m has room**」这句话能成立的机制：3m 图上 PO 用 3m ATR，
10m 图上 PO 用 10m ATR，两者可以同时给出完全不同的读数。
如果分母是同一个日线 ATR，这句话在数学上就不可能成立——**这本身就是对我们
修正版的一次逻辑自洽性检验**。

### Time Warp（2026-01-04 新增）

`time_warp` 是一个下拉输入（`off / 1m / 2m / 3m / 4m / 5m / 10m / 15m / 20m / 30m / 1h / 2h / 4h / D / W / M / Y`）。
选中后 `price / atr / stdev / pivot / oscillator` 全部通过 `request.security` 到该周期取值。
**Saty 的 "Day 3/10" 模板就是：3m 图上挂两份 PO，一份 `off`（=3m），一份 `10m`。**

> ⚠️ **回测警告**：官方 Time Warp 用的是
> `request.security(..., lookahead = barmerge.lookahead_on)`。
> 这在**历史 K 上会前视**（高周期 K 从它的第一根低周期 K 起就显示该 K 的最终值）。
> 实盘看盘无害（当前 HTF K 本来就在发展中），但**任何用带 Time Warp 的历史序列做统计
> 都会得到虚高的结果**。我们的研究代码一律**不要**复制这个行为——
> `satylab.indicators.timewarp` 已经是「只读上一根已完成的高周期 K」，是对的，保持。

---

## 3. 分区的官方名称与含义（回答问题 2）

命名有两个一手出处，互相一致：官方产品页文案（S5）与 Saty 自己 thinkScript 版里的
扫描用变量名（S2）。**边界的开闭以源码为准**：

| 官方分区 | 变量名（Saty 源码） | 区间 | `phase` 编码 | 含义 |
|---|---|---|---|---|
| Extreme（上） | `extended_up` | `osc ≥ 100` | 3 | 极端动能，"通常会在动能耗尽后冷却"；找背离与均值回归 |
| **Distribution Zone** | `in_distribution` | `61.8 ≤ osc < 100` | 2 | Wyckoff 派发 |
| Mark Up | `in_mark_up` | `23.6 < osc < 61.8` | 1 | Wyckoff 上升推进 |
| **Neutral / Launch Zone**（源码内叫 launch box） | `in_launch_box` | `−23.6 ≤ osc ≤ 23.6` | 0 | 中性/待发；0 轴是"动能切换线" |
| Mark Down | `in_mark_down` | `−61.8 < osc < −23.6` | −1 | Wyckoff 下降推进 |
| **Accumulation Zone** | `in_accumulation` | `−100 < osc ≤ −61.8` | −2 | Wyckoff 吸筹 |
| Extreme（下） | `extended_down` | `osc ≤ −100` | −3 | 同上，反向 |

官方页原话（S5，转述其结构）：网格是 **Fibonacci 分格**，位置对应
**Wyckoff 四相：Accumulation / Mark Up / Distribution / Mark Down**；
`0` 是动能切换的零轴；`±100` 之外是"极端动能"。

**我们旧实现的分区名（`bull_mean_rev` / `neutral` / `distribution` 边界错位）是自造的，全部作废。**
`phase_fix.phase_zone()` 已按上表逐字重写，含闭区间方向。

### "黄灯"交叉点（2024-10-04 / 2024-10-30 加入）

四个事件，源码逐字：

```pine
leaving_accumulation = oscillator[1] <= -61.8 and oscillator >  -61.8
leaving_extreme_down = oscillator[1] <= -100  and oscillator >  -100
leaving_distribution = oscillator[1] >=  61.8 and oscillator <   61.8
leaving_extreme_up   = oscillator[1] >=  100  and oscillator <   100
```

作者本人对它的定位（Twitter/X 更新公告，经搜索结果标题取得，未能直接抓取 x.com 页面，
故标为**二手可信度**）：
> 加了一些细微的均值回归信号（基于 ±61.8 交叉），可以帮助做均值回归、反转等。

官方页表述为 **"Yellow light" 动能放缓信号**，"可帮助确认均值回归"。
注意措辞：是**确认（confirm）**，不是**触发**。

---

## 4. Compression 标签的触发条件（回答问题 3）

**它不是 Bilbo Box 的一部分。** Bilbo Box 是"数 5 根压缩蜡烛画区间"的**手工流程**；
Compression 是 Phase Oscillator 内置的一个**布林带被凯尔特纳通道包住**的挤压判定
（TTM Squeeze 家族）。两者概念同源、实现无关。

源码逐字（Pine）：

```pine
bband_offset               = 2.0 * stdev              // stdev = ta.stdev(close, 21)
compression_threshold_up   = pivot + (2.0   * atr)
expansion_threshold_up     = pivot + (1.854 * atr)
compression       = above_pivot ? (bband_up - compression_threshold_up) : (compression_threshold_down - bband_down)
in_expansion_zone = above_pivot ? (bband_up - expansion_threshold_up)   : (expansion_threshold_down - bband_down)
expansion = compression[1] <= compression[0]
compression_tracker = false
if expansion and in_expansion_zone > 0
    compression_tracker := false
else if compression <= 0
    compression_tracker := true
else
    compression_tracker := false
```

### 4.1 `above_pivot` 三元分支是恒等式（已在真实数据上验证）

上分支 `(pivot+2σ) − (pivot+2·ATR) = 2σ − 2·ATR`；
下分支 `(pivot−2·ATR) − (pivot−2σ) = 2σ − 2·ATR`。**完全相同。**
`phase_fix.verify_compression_branches()` 在 daily/hourly/5m 上逐根走：

```
daily    checked=5010   mismatches=0
hourly   checked=5070   mismatches=0
5m       checked=4661   mismatches=0
```

**所以 `above_pivot` 对 Compression 标签毫无影响**——源码里那个三元只是写法冗余。
（这条很重要：任何人若照抄源码结构去"优化"，会误以为多空侧有区别。没有。）

### 4.2 化简后的真实触发条件

令 `σ = stdev(close, 21)`（**population，除以 N**，见 4.3），`A = ATR(14)`：

```
Compression = ON   ⟺   σ ≤ A   且   ¬( σ > 0.927·A  且  (2σ − 2A) 相对前一根未下降 )
```

也就是：
1. **主条件**：`σ ≤ A` —— 2σ 布林带宽被 2×ATR 凯尔特纳带宽包住（挤压）。
2. **提前释放**：一旦 `σ` 越过 `0.927·A`（即 `1.854/2`）**且**带宽差正在扩大，
   标签提前熄灭，不等真正穿越。这是一段迟滞（hysteresis）。

`phase_spec_check.py` 用这个化简式与逐字移植逐根对拍：

```
daily    checked=5010  mismatches=0
hourly   checked=5070  mismatches=0
5m       checked=4661  mismatches=0
```

### 4.3 一个必须标注的实现细节：stdev 的除数

Pine `ta.stdev(source, length)` 默认 `biased = true`，即**总体标准差（除以 N）**，
且围绕 **SMA(21)** 而非 EMA(21) 计算。thinkScript 的 `StDev` 惯例不同（样本，除以 N−1）。
两者对标签占空比的影响已量化（`phase_spec_check.py` §5）：

| 数据集 | population（Pine 默认） | sample (N−1) | 两比例 z |
|---|---|---|---|
| daily 20y | 27.7% [26.5, 29.0] n=5010 | 25.2% [24.0, 26.4] | +2.85 |
| hourly 730d | 25.3% [24.1, 26.5] n=5070 | 23.6% [22.5, 24.8] | +1.99 |
| 5m 60d | 36.5% [35.1, 37.9] n=4661 | 34.7% [33.4, 36.1] | +1.75 |

差异真实存在但很小。**`phase_fix` 默认用 Pine 惯例（population），与 TradingView 对齐。**

### 4.4 视觉与标签

- `compression_tracker == true` 时：0 轴那条线与振荡线本身变色。
  2026-01-10 起默认配色是 **"Clean"（浅灰）**，可切回 **"Classic"（洋红/粉）**。
  → **你图上那个 "Compression" 标签就是这个 tracker 为真时，画在右上角的 table cell。**
- 官方页原话（S5）：三色系统让你看到动能强（绿）、弱（红）、布林压缩（灰或洋红），
  且"**压缩信号之后接绿或接红，就非常清楚地指示了方向性的价格扩张**"。

---

## 5. Saty 本人怎么用它（回答问题 4）

按证据等级分三层列出，**不做合并、不做美化**。

### 5.1 官方产品页表述（S5，作者本人文案，转述）

- 定位：**ATR/EMA 基础的价格振荡器**，借用"Keltner 通道用 ATR 偏离 EMA"的概念，
  用价格相对波幅的差值构造一个**不封顶但通常在区间内**的信号；
  "让你像 RSI 一样看到区间内的相对强弱"。
- **±100 之外 = 极端动能**，"通常会在动能耗尽后出现一些降温"，
  是**寻找背离与均值回归**的信号。
- **Compass**：这层平滑（即 `EMA(raw, 3)`）给出"信号前端的短期趋势"，
  以及"相对价格的干净背离信号"。
- **Fibonacci 网格**的作用被明确写为："作为拐点、支撑/阻力，以及
  **类似 MACD 的交叉确认信号**"。
- 用法核心句：**"压缩信号之后接绿或接红，就非常清楚地指示了方向性的价格扩张。"**

### 5.2 Twitter/X（经搜索结果标题取得，**未能直接抓取 x.com 原页**，标为二手）

> 很简单的一个 TA 技巧，能替你省时间：如果你在 Saty Phase Oscillator 上看到 compression，
> 就把区间画出来。可以是趋势线也可以是水平位。找出定义这个区间的支撑与阻力。

**这句话把 Compression 和"画位"直接连起来了**——PO 的 compression 不产生入场，
它命令你**去把区间的两条边画出来**，然后区间边界才是入场/风险位。
这与 Bilbo Box 的做法在**结论上收敛**（区间边界即止损），但触发机制不同。

### 5.3 Discord 实盘用语（S7，2026-07-24 #notes，一手抄录，见 `SATY_RIPSTER_METHOD_STUDY.md` §1.4）

> 11:37 "3m extreme here. 10m has room, but maybe some consolidation, pullback possible"
> 11:47 "I think this bounce here with 3m extreme at demand/support makes a lot of sense."

解码出的用法结构（这是他真实的决策逻辑）：

1. **PO 是"成熟度/位置"读数，不是入场信号。** 他从不说"PO 极端所以我做多"，
   他说的是"3m 极端**在需求/支撑位上**，所以这个反弹说得通"。
   → **PO 极端 × 具名的位 = 理由；单独任何一个都不是。**
2. **双周期配对判定"整理 vs 反转"**：
   - 低周期极端 + 高周期还有空间 → **整理/回撤**（不是反转，顺势方向仍有效）
   - 两个周期都极端 → **反转候选**
3. **趋势过滤靠 Pivot Ribbon，不靠 PO。** PO 回答"走多远了"，Ribbon 回答"往哪走"。

### 5.4 综合结论：PO 在体系里的**层级**

| 层 | 工具 | 回答的问题 |
|---|---|---|
| 方向 | Pivot Ribbon（8/21 EMA）+ TimeWarp | 往哪走？ |
| 位置/目标 | ATR Levels（日线 ATR + 前收） | 现在在哪两个具名位之间？下一个位是什么？概率多少（GG 基准率）？ |
| **成熟度/时机** | **Phase Oscillator** | **这一段走多远了？还有没有空间？是不是该缩手/找反转？** |
| 压缩/扩张 | PO 的 Compression | 现在是不是箱体？箱体边在哪？ |

**换句话说：PO 不是我们缺的那个"入场层"。**
本次研究的另一条任务（GG 是目标层、入场层缺失）不会被 PO 填上。
PO 能做的是**入场的否决位与出场的成熟度提示**——
"3m 已经 extreme 了，此处不要追多"、"两个周期都 extreme，考虑反转/减仓"。
把它当信号发生器用，就会重蹈"自造信号"的覆辙。

---

## 6. 数值验算（回答问题 5）

复现：`cd <repo> && .venv/bin/python research/phase_spec_check.py`

### 6.0 前置：原语对齐

`phase_fix.ta_ema / ta_atr` 与仓库已有的 `indicators.ema / atr_series`
在 20 年日线上 **最大绝对差 = 0.000e+00**，暖机 None 数一致（20 个）。
所以本移植继承了仓库既有的 EMA/ATR 校验证据，新增的只有 `ta_stdev`。

### 6.1 分位数分布（振荡器单位；轨线 ±23.6 / ±61.8 / ±100）

**DAILY ^GSPC 20y（2006-07-25 → 2026-07-23）**

| 序列 | n | p1 | p5 | p25 | p50 | p75 | p95 | p99 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **修正版**（EMA3 of /3ATR） | 5008 | −93.7 | −65.0 | −13.2 | **25.6** | 54.1 | 83.8 | 105.4 | −155.1 | 153.8 |
| 未平滑 raw | 5010 | −102.7 | −71.9 | −14.5 | 26.0 | 56.0 | 88.7 | 112.9 | −183.2 | 162.9 |
| 旧猜测（/1ATR，无平滑） | 5010 | −308.2 | −215.7 | −43.5 | 78.1 | 168.0 | 266.2 | 338.8 | −549.6 | 488.7 |

**HOURLY ^GSPC 730d（RTH，7 根/日）**

| 序列 | n | p1 | p5 | p25 | p50 | p75 | p95 | p99 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **修正版** | 5068 | −112.4 | −76.8 | −22.9 | **17.4** | 53.1 | 98.5 | 137.3 | −161.4 | 162.9 |
| 旧猜测 | 5070 | −373.1 | −249.3 | −70.1 | 54.5 | 166.4 | 309.6 | 425.2 | −641.3 | 519.7 |

**5-MIN ^GSPC 60d（窗口短，仅描述性）**

| 序列 | n | p1 | p5 | p25 | p50 | p75 | p95 | p99 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **修正版** | 4659 | −116.2 | −77.1 | −29.4 | **6.7** | 40.2 | 87.6 | 125.2 | −232.3 | 201.0 |
| 旧猜测 | 4661 | −381.0 | −242.6 | −91.2 | 20.4 | 123.7 | 274.5 | 390.4 | −751.6 | 692.6 |

### 6.2 出轨率：这是判定公式对错的决定性一栏

| 数据集 | 阈值 | **修正版** | 旧猜测 | 两比例 z |
|---|---|---|---|---:|
| daily | \|osc\| ≥ 23.6 | 70.5% [69.2, 71.7] n=5008 | 91.5% [90.7, 92.3] n=5010 | −26.8 |
| daily | \|osc\| ≥ 61.8 | 24.2% [23.0, 25.4] | 76.0% [74.8, 77.2] | −51.9 |
| daily | **\|osc\| ≥ 100** | **2.2% [1.8, 2.6]** | **60.1% [58.8, 61.5]** | **−62.6** |
| hourly | \|osc\| ≥ 100 | 6.6% [5.9, 7.3] n=5068 | 60.6% [59.3, 61.9] n=5070 | −57.6 |
| 5m | \|osc\| ≥ 100 | 5.2% [4.6, 5.8] n=4659 | 54.3% [52.8, 55.7] n=4661 | −51.9 |

**判读**：官方文案说这是一个"不封顶但**通常落在区间内**"的信号，
`±100` 之外代表"**极端**动能"。
修正版在日线上 2.2%、小时线 6.6%、5m 5.2% 越过 ±100 —— **"极端"确实极端**。
旧猜测让"极端"成为**六成时间的常态**，那条轨线在图上等于不存在。
这就是"从图表里看不到任何有用的价值"的一个具体、可量化的来源。

同时注意：修正版**也没有被压扁**——它不是"绝大多数时间在 ±23.6 内"
（日线仅 29.5% 在 launch box），振幅铺满了整个网格。两侧都不错位，公式站得住。

### 6.3 分区占空比（修正版，含 Wilson 区间）

| 分区 | daily 20y (n=5008) | hourly 730d (n=5068) | 5m 60d (n=4659) |
|---|---|---|---|
| extended_down | 0.7% [0.5, 0.9] | 1.8% [1.5, 2.2] | 2.2% [1.8, 2.7] |
| accumulation | 4.9% [4.4, 5.6] | 6.6% [6.0, 7.3] | 6.7% [6.1, 7.5] |
| mark_down | 13.4% [12.5, 14.4] | 16.2% [15.2, 17.3] | 20.0% [18.9, 21.2] |
| **launch_box** | 29.5% [28.3, 30.8] | 29.7% [28.5, 31.0] | 33.5% [32.2, 34.9] |
| mark_up | 32.9% [31.6, 34.2] | 26.0% [24.9, 27.3] | 25.1% [23.9, 26.4] |
| distribution | 17.1% [16.0, 18.1] | 14.8% [13.9, 15.8] | 9.5% [8.7, 10.3] |
| extended_up | 1.5% [1.2, 1.9] | 4.7% [4.2, 5.4] | 2.9% [2.5, 3.5] |

*（7 格全表扫描，非择优；不对任何单格附加论断。）*
日线分布有明显的多头偏斜（mark_up 32.9% vs mark_down 13.4%），
这与 20 年 SPX 长期上行一致，是**合理性佐证**而非发现。

### 6.4 Compression 占空比与持续时长

| 数据集 | 占空比（Pine 惯例） | 压缩段数 | 中位长度 | 最长 |
|---|---|---:|---:|---:|
| daily 20y | 27.7% [26.5, 29.0] n=5010 | 226 | 4 根 | 40 根 |
| hourly 730d | 25.3% [24.1, 26.5] n=5070 | 180 | 5 根 | 55 根 |
| 5m 60d | 36.5% [35.1, 37.9] n=4661 | 192 | 5 根 | 44 根 |

**约四分之一到三分之一的时间处于压缩** —— 这与"挤压指标"的常识量级相符
（TTM Squeeze 家族同量级）。它是一个**常见状态，不是稀有事件**，
因此"看到 Compression 就交易"没有任何选择性，必须配合区间边界。

### 6.5 小时线按时段（全表扫描，7 个正常格 + 2 个数据异常格）

| ET 开盘 | 极端率 \|osc\|≥100 | 压缩率 |
|---|---|---|
| 09:30 | 6.6% [5.0, 8.7] n=726 | 31.4% [28.1, 34.9] |
| 10:30 | 7.3% [5.6, 9.4] n=727 | 25.7% [22.7, 29.0] |
| 11:30 | 7.4% [5.7, 9.6] n=727 | 23.4% [20.5, 26.6] |
| 12:30 | 6.9% [5.3, 9.0] n=720 | 23.3% [20.4, 26.6] |
| 13:30 | 6.0% [4.5, 7.9] n=720 | 22.8% [19.9, 26.0] |
| 14:30 | 6.0% [4.5, 7.9] n=720 | 23.6% [20.7, 26.8] |
| 15:30 | 5.4% [4.0, 7.3] n=720 | 27.2% [24.1, 30.6] |

（另有 `13:00` n=7、`16:00` n=1 两格，是半日市/数据边缘产物，忽略。）

**必须说的话**：09:30 与 15:30 的极端率差 6.6% vs 5.4%，
两比例检验 z 远小于 1.96；压缩率 31.4% vs 22.8% 看起来像个形状，
但这是**一次 7 格全扫描**，且没有任何预登记假设。
**这里没有做功，不要当发现用。** 列出来只为证明分布没有病态结构。

---

## 7. 一个独立的外部佐证：2026-07 的日线压缩箱

这不是统计检验，是一次 **n=1 的定性对表**，但它很难用巧合解释：

- 我们的 `compression_tracker` 在 **^GSPC 日线上给出一段自 2026-06-29 起、
  到数据末端 2026-07-23 为止、连续 18 个交易日未中断的压缩**。
  该区间价格箱体：**7348.9 – 7581.5**。
- Saty 本人在 **2026-07-24** 的 Discord #notes 里说
  （`SATY_RIPSTER_METHOD_STUDY.md` §1.4 一手抄录）：
  > "Last two weeks have been on hard mode. Once this **daily box** resolves, should get a little easier."
- 同一份记录里，他提到的月度 trigger box 是 **7400–7600**。

我们在**完全不看他的话**的情况下，用刚从源码钉死的公式，
独立地在同一根日线上标出了同一个"daily box"，且箱体范围相容。

补充量化（描述性）：

| | 2026-06-29 → 07-23（n=18） | 此前 20 年（n=4990） | 两比例 z |
|---|---|---|---:|
| 压缩率 | **100.0% [82.4, 100.0]** | 27.5% [26.3, 28.7] | +6.86 |
| 落在 launch_box | **77.8% [54.8, 91.0]** | 29.3% [28.1, 30.6] | +4.50 |

20 年里日线压缩段共 226 段，中位长度 4 根、p90=14 根，**≥18 根的只有 17 段**。
所以这确实是一段偏长的压缩。

> **诚实边界**：这条只证明**实现落在正确的状态区**（compression 的定义、
> 阈值、迟滞都没写反），**不证明任何交易边缘**。
> 它是"我们的尺子和作者的尺子读数一致"的证据，不是"这把尺子能赚钱"的证据。
> 而且这是**事后**去对一句已知的话，若拿来当"预测成功"就是典型的事后叙事。

---

## 8. 交付物与接口

**`research/satylab/phase_fix.py`**（新增，未触碰 `indicators.py`）

```python
from satylab import phase_fix as pf

pf.phase_oscillator(bars)      # -> list[float|None]  图上画的那条线（已 EMA3 平滑）
pf.phase_raw(bars)             # -> 未平滑 raw_signal，仅诊断用
pf.compression_tracker(bars)   # -> list[bool|None]   "Compression" 标签
pf.phase_zone(v)               # -> extended_up/distribution/mark_up/launch_box/
                               #    mark_down/accumulation/extended_down
pf.phase_code(v)               # -> Saty 自己的 3/2/1/0/-1/-2/-3 编码
pf.is_extreme(v)               # -> |v| >= 100
pf.crossovers(osc)             # -> 每根 K 的黄灯事件元组
pf.phase_states(bars)          # -> list[PhaseState(value, zone, compressed, events)]

# Time Warp 等价物：直接把高周期 bars 喂进去
osc_10m = pf.phase_oscillator(bars_10m)     # 不要复制官方的 lookahead_on
```

原语（供审查者单独校验）：`ta_ema` / `ta_rma` / `ta_atr` / `ta_stdev`
自证工具：`verify_compression_branches(bars)`

**`research/phase_spec_check.py`** —— 本报告全部数字的生成脚本，无任何参数搜索。

---

## 9. 对现有代码的处置建议

| 对象 | 处置 |
|---|---|
| `satylab.indicators.phase_oscillator` | **标记为错误实现**。分母缺 3×、缺 EMA3 平滑，出轨率 60%。任何引用它的既有结论都要重跑 |
| `satylab.indicators.phase_zone` | **分区名与边界均为自造**，作废，改用 `phase_fix.phase_zone` |
| `satylab.indicators.PHASE_RAILS` | 轨线值本身是对的（100/61.8/23.6/…），保留 |
| `satylab.indicators.timewarp` | **是对的，保持**（读上一根已完成高周期 K，无前视）。不要为了"和官方一致"改成 lookahead_on |
| `docs/STATUS.md` 第 80 行 "The Phase value is an internal proxy, not a verified reproduction of Saty Phase." | 现在可以更新：公式已钉死并复现 |

**我没有修改 `indicators.py`**（按任务约定，多研究并行）。上述处置需要一次显式决定。

---

## 10. 未解决的问题

1. **没有拿到 TradingView 端的逐根数值做逐位对拍。** 本报告的公式来自源码本体
   （最强的一类证据），但"我们的 Yahoo `^GSPC` bar" 与 "你图上的 `SP:SPX` bar"
   在 1h/5m 的切分边界与 RTH/ETH 处理上可能有细微差异。
   `phase_spec_check.py` §7 已打印**可手工对拍的锚点行**（含 close / EMA21 / ATR14 /
   stdev21 / osc / zone / compressed）。**请在你的图上核对任意一根日线 K，
   若 osc 对不上小数点后一位以内，先怀疑数据源而不是公式。**
2. **"Compass" 是不是一条独立的绘图？** —— 基本可以定论为**不是**，但留一个小口子。
   查证过程：(a) 当前 Pine 源码里 **`plot` 一共 12 条**，全部有名字，
   **没有任何一条叫 Compass**；(b) `satyland.com/pivotribbon` 与
   `satyland.com/atrlevels` 两页**完全没有出现 "Compass" 一词**，
   所以它不是别的指标借过来的部件。
   结论：Compass 指的就是 `ta.ema(raw_signal, 3)` 这条线本身**前端的斜率/朝向**
   （官方原话是这层平滑"提供信号前端的短期趋势"），不是第二条线。
   唯一的残余不确定：Saty 可能在 Discord 里用 "Compass" 指代某个我们看不到的口头约定。
3. **Saty 是否用 PO 做"过滤入场"还有更细的规则？**（例如"PO 在 launch box 内
   才做突破"这类）—— 公开材料里**没有**这样的明文规则。
   Discord 里能看到的都是**位置 × 极端**的组合判断。
   若你在付费社区里见过更明确的成文规则，那是我拿不到的一手材料。
4. **ETH/RTH**：2026-01-11 的修复说明"修复了不论 TradingView 的 RTH/ETH 模式都强制
   使用盘后数据的问题"。Saty 模板全部标 **(ETH)**。我们的数据层是 **RTH-only**。
   **这意味着我们算的 3m/10m PO 与他图上的 PO 在开盘后前 21 根内会有系统性差异**
   （EMA21 与 ATR14 的暖机内容不同）。做任何开盘段研究前必须先处理这条。

---

## 附：外部审查者最短复现路径

```bash
# 1. 取回官方源码本体，自行核对第 2/4 节引用的那几行
curl -sL -A "Mozilla/5.0" \
  "https://pine-facade.tradingview.com/pine-facade/get/PUB%3Bf27506d00fc64f30b880835f6847ac6e/last" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['created']);print(d['source'])"

# 2. 重跑本报告的每一个数字
cd "/Users/lukegogogo/claude code projects/idm-tradingview-research"
.venv/bin/python research/phase_spec_check.py

# 3. 独立第三方移植（供交叉核对公式）
curl -sL https://raw.githubusercontent.com/rishid/thinkscripts/master/saty_phase_oscillator.tosts
```

**来源**

- [Satyland — Saty Phase Oscillator](https://www.satyland.com/phaseoscillator)
- [TradingView — Saty Phase Oscillator (satymahajan)](https://www.tradingview.com/script/AkgbmvVa-Saty-Phase-Oscillator/)
- [rishid/thinkscripts — saty_phase_oscillator.tosts](https://github.com/rishid/thinkscripts/blob/master/saty_phase_oscillator.tosts)
- [krithin98/Whispr — saty_phase_oscillator.pine](https://github.com/krithin98/Whispr/blob/ad19296f2c06180017a7ed0d310f48ad277011f4/Scripts/saty_phase_oscillator.pine)
- [useThinkScript — SATY Phase Oscillator scan 讨论帖](https://usethinkscript.com/threads/tweek-needed-for-saty-phase-oscillator-scan.20375/)
- [Satyland — FAQ](https://www.satyland.com/faq)
