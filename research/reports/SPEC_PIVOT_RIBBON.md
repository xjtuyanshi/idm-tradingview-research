# Saty Pivot Ribbon 精确定义规格书（2026-07-25）

> 脚本：`research/satylab/ribbon_spec.py`（参考实现 + 自检）
> 　　　`research/ribbon_session_probe.py`（ETH/RTH 会话保真度实测）
> 目的：把 Saty 体系里缺失的**趋势层**从"传说"变成"可编码的定义"，
> 并且**明确区分哪几条是原作者源码里写死的、哪几条是我推断的**。

## 证据等级（全文标注，不许混用）

| 级别 | 含义 |
|---|---|
| **[A]** | 原作者**自己发布的源码**（github.com/satymahajan/saty_pivot_ribbon 的 `.pine` / `.tosts`）。这是最高等级，等同于机器可执行的定义。 |
| **[B]** | 原作者**自己写的公开文字**（TradingView 指标说明、satyland.com、他本人的 X 帖子）。 |
| **[C]** | **第三方**转述（付费社区博客、TradingView 第三方脚本说明、社区论坛）。可能失真。 |
| **[D]** | **我的推断**。没有公开出处，只是从 [A]/[B]/[C] 外推。**默认当成未验证的假设。** |

---

## 0. 一页结论

| 问题 | 答案 | 等级 |
|---|---|---|
| 哪几条 EMA？ | **8 / 21 / 34**（ribbon 主体）+ **13 / 48**（conviction，独立一层） | **[A]** |
| 用 close 还是 hl2？ | **close**，五条全部 | **[A]** |
| TimeWarp 是重采样还是前推？ | **在上级周期上算 EMA，然后按"最近一根已收上级 K"阶梯前推**；不是重采样，闭合 K 不重绘 | **[A]** |
| 有重绘吗？ | ribbon 层无（`lookahead_off` + 实时 `[1]` 偏移）；**conviction 层用了 `lookahead_on`，存疑，见 §3.4** | **[A]/[D]** |
| Yummy / Vomy 的确切定义？ | **Vomy 只有 [C] 级证据，Yummy 公开网络上零文献**。给出 3 个候选定义 | **[C]/[D]** |
| H21 / D21 / W21？ | = 小时 / 日 / 周线的 **21 EMA**，即 ribbon 的 pivot 线 | **[B]** 已由 Saty 本人 X 帖直接确证 D21 |
| ribbon 用来干什么？ | **主用途 = 趋势/偏向过滤 + 动态支撑阻力**；入场触发只在与位/极端叠加时成立 | **[B]/[C]** |

**三个必须先记住的坑：**

1. **三个候选 Vomy 定义几乎从不在同一根 K 上触发**（实测 v1∩v2 = 0、v1∩v3 = 0、
   v2∩v3 = 9/21）。**"随便挑一个"等于换了一个策略**，不是换了一个参数。
   这个必须去 Discord 问原作者，不能拿回测择优来定。
2. **会话（ETH vs RTH）不是细节，是一等参数**。实测 SPY 10m ribbon 状态
   ETH 与 RTH 只有 **73.6%** 一致，**开盘第一小时只有 48.8%**。
   Saty 模板全部标注 `(ETH)`，而我们 `satylab.data` 只有 RTH。
3. **我们现有的 `indicators.timewarp()` 是对的**（"取上一根已收上级 K"），
   但 `RibbonState.label()` 的四态（bull_trend/bear_trend/in_ribbon/conflict）
   **是我们发明的**，不是 Saty 的。Saty 的原生状态是**两朵云的颜色对**（§2.3）。

---

## 1. 一手来源清单

| 来源 | 等级 | 用途 |
|---|---|---|
| `github.com/satymahajan/saty_pivot_ribbon` → `saty_pivot_ribbon.pine`（6473 B）、`saty_pivot_ribbon.tosts`（5018 B）、`saty_pivot_ribbon.webull`（1187 B） | **A** | EMA 长度、来源、TimeWarp 实现、conviction 逻辑 |
| TradingView 指标页 `Saty Pivot Ribbon`（script/I4VXGe18） | **B** | 官方功能描述、颜色语义、bias candles |
| satyland.com/pivotribbon | **B** | 免费版 3 EMA(8/21/34) vs Pro 版 5 EMA(8/13/21/48/200) |
| Saty 本人 X 帖（"Rejected at the Daily 21 EMA on #ES_F…"） | **B** | 确证 D21 = 日线 21 EMA 的用法 |
| Saty 本人 X 帖（"Candle Bias is now an option…"） | **B** | bias candle 概念 |
| `getthatcashmoney.com/blog/strategy-vomy/` "The Dolphin Vomit" + TradingView `Cash Saty Vomy (STRATEGY)` 说明页 | **C** | 目前唯一一份公开的 Vomy 规则描述 |
| YouTube `The "Vomy" Setup…`(eYeUS5wRwKg)、`Conviction Arrows and Time Warp`(QMJ_rg3phPA)、`The Golden Gate Strat…`(d43HaLb765k) | **C** | 仅取得标题/摘要，**正片未取得逐字稿**（见 §8 未决项） |
| `docs/SATY_RIPSTER_METHOD_STUDY.md`（本仓库，Discord 一手摘录） | **B** | Saty 的实盘语言样本 |

**取不到的**：Saty 的 Discord 原文（非公开）、YouTube 逐字稿、
`ratemyfuru.com/satyland`（DNS 解析失败）、`getthatcashmoney.com` 正文
（TLS 证书链错误，只能通过搜索引擎摘要间接读到）。

---

## 2. 问题 1：Ribbon 由哪几条 EMA 组成

### 2.1 组成 [A]

| 输入名（Pine） | 默认 | 角色 | 层 |
|---|---:|---|---|
| `fast_ema` | **8** | 快线 | Ribbon |
| `pivot_ema` | **21** | **枢轴线**——就是 H21/D21/W21 里那个 21 | Ribbon |
| `slow_ema` | **34** | 慢线 / 结构线 | Ribbon |
| `fast_conviction_ema` | **13** | 确信快线 | Conviction（独立） |
| `slow_conviction_ema` | **48** | 确信慢线 | Conviction（独立） |

**是 8/21/34，不是 8/21。** 34 是 ribbon 的第三条腿，构成第二朵云。
13/48 **不属于 ribbon 本体**，是叠在上面的独立"确信层"，只用来出箭头
（TradingView 说明原文：Conviction Arrows based on 13/48 EMA crossover [B]）。

> Pro 版是 5 条 **8/13/21/48/200** [B]——即把 conviction 的 13/48 也画成线，再加 200。
> 我们只需实现免费版的 8/21/34 + 13/48，语义完全等价。

### 2.2 价格来源 [A]

**全部是 `close`。** `.pine` 里五条都是 `ta.ema(close, len)`；
`.tosts` 里是 `ExpAverage(price, 8/21/34/13/48)`，其中 `price` = 该聚合周期的 `close`。
**没有 hl2、没有 ohlc4、没有 source 输入项。**

> 这一条要特别记：我们过去用 Ripster 云（5/12、34/50）替代，
> 那套是别人的尺子；而且不少 EMA 云实现默认 hl2，会产生持续性偏移。

### 2.3 原生状态 = 两朵云的颜色对 [A]

源码里只有两个布尔量决定填色：

```
fast_cloud_bull = ema8  >= ema21      # 绿 / 红
slow_cloud_bull = ema21 >= ema34      # 青(aqua) / 橙
```

TradingView 说明把它表述为"看涨=绿+蓝、看跌=红+橙" [B]（源码里的 aqua 即说明里的 blue）。
于是 ribbon 只有 3 个可编码状态：

| 状态 | 条件 | 含义 |
|---|---|---|
| `full_bull` | `ema8 >= ema21 >= ema34` | 绿 + 青，多头排列 |
| `full_bear` | `ema8 < ema21 < ema34` | 红 + 橙，空头排列 |
| `folded` | 两朵云颜色不一致 | **"ribbon folding"**，即交叉/转换中 |

**"Ribbon folding" 是官方术语，官方定义就是"EMA 交叉的视觉表现" [B]**，
对应四个事件：`fast_fold_up/down`（8×21）、`slow_fold_up/down`（21×34）。

实测（SPX 10m，60 天 2308 根）：`full_bull` 48.3% / `full_bear` 34.4% / `folded` 17.3%。

### 2.4 Bias Candles [B]

当前 TradingView 版本有一个可选项：**按收盘价相对 bias EMA（默认 21）的位置给 K 线上色**。
GitHub 上那份 `.pine`/`.tosts` **没有**这个功能（版本较旧）[A]。

```
bias_bull = close >= ema(bias_len=21)
```

这就是 **"holding H21"、"holding the 21" 语言的图形化来源**——他看的是 K 线颜色。

---

## 3. 问题 2：TimeWarp 的确切机制

### 3.1 可选周期 [A]

`off, 1m, 2m, 3m, 4m, 5m, 10m, 15m, 20m, 30m, 1h, 2h, 4h, D, W, M, Y`
（映射到 `"1","2",…,"10","15","20","30","60","120","240","D","W","M","12M"`）。
`off` → `timeframe.period`（即图表自身周期）。

Saty 的 "Day 3/10" 模板 = 3m 图 + TimeWarp 设为 `10m`，正好在列表里。

### 3.2 机制：上级周期上算 EMA，然后阶梯前推 [A]

关键一行（Pine）：

```
fast_ema_value = request.security(syminfo.tickerid, timeframe_func(),
                                  ta.ema(close, fast_ema)[barstate.isrealtime ? 1 : 0],
                                  gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)
```

拆解，三条都很重要：

1. **`ta.ema(close, 8)` 写在 `request.security` 内部** → EMA 是在**上级周期的 K 序列**上
   算的。**不是**把执行周期的 EMA 重采样，**也不是**把上级周期的收盘价拉下来再在
   执行周期上算 EMA。
   → 我们过去"把 3m 的 EMA 降采样后画在 10m 图上"是**错的**，这条源码直接判死。
2. **`gaps=barmerge.gaps_off`** → 上级 K 未收时不返回 `na`，而是**保持上一个值**。
   所以画在 3m 图上是一条**阶梯线**：同一根 10m K 内的 3～4 根 3m K 上，
   ribbon 完全水平，到 10m K 收盘才跳一级。
   **自检口径：如果你实现出来的 TimeWarp ribbon 是平滑的，那就一定实现错了。**
3. **`lookahead=barmerge.lookahead_off`** → 只有**已收盘**的上级 K 才被合并进来。
   历史 K 上，执行 K 读到的是**"包含它的那根上级 K 的前一根"**的 EMA 值；
   新值在上级 K 收盘后的**第一根执行 K** 上才出现。

### 3.3 重绘：ribbon 层没有 [A]

`[barstate.isrealtime ? 1 : 0]` 是 Pine 的标准防重绘惯用法：

- 历史 K：`barstate.isrealtime = false` → 偏移 0，配合 `lookahead_off` 得到"最近一根已收上级 K"。
- 实时 K：`request.security` 本来会返回**正在形成中**的上级 K 的值（会随 tick 变动）；
  偏移 `[1]` 把它推回上一根已收 K。

两者对齐 → **闭合 K 上的 ribbon 值不会事后改变**。这是可以直接拿来做回测的。

### 3.4 ⚠️ conviction 层的 `lookahead_on` 存疑 [A 部分 / D 部分]

源码里有一个独立变量：

```
price = request.security(ticker, timeframe_func(), close,
                         gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on)
```

两点：

- 这个 `ticker` 是 `ticker.new(..., session=session.extended)` 造出来的，
  **强制使用延长时段（ETH）**，与 ribbon 三条线不同（那三条跟随图表会话）。
- 它用的是 **`lookahead_on`**，而 conviction 的 13/48 EMA 建立在它之上。

**我没能确认最终表达式里的偏移是否把这个 lookahead 抵消掉了**（网页抓取工具拒绝
逐字返回源码，只能问答式提取，而 Pine v5 不允许 `request.security` 嵌套，
所以工具返回的那行结构本身可疑）。

> **行动项**：在把 conviction arrows 用于任何回测之前，
> 必须人工打开 `saty_pivot_ribbon.pine` 读那 3 行。
> 在此之前，**conviction arrows 一律按"可能含未来函数"处理**。
> ribbon 三条线不受影响，可以放心用。

### 3.5 我们现有实现的核验

`satylab/indicators.py::timewarp()` 用 `hi_states[j-1]`（j = 包含该执行 K 的上级 K）
→ **与 §3.2 第 3 条一致，是对的，不要改。**

实测这个惯例的敏感度（SPX，10m→5m，4613 根可比执行 K）：
若改用 `lag=0`（用包含它的那根上级 K，即引入未来函数），
**ribbon 状态会在 5.9% 的执行 K 上变化**。不算大，但足以翻转边缘统计，
所以任何结论都必须声明用的是哪个惯例。`ribbon_spec.timewarp(lag=...)` 把它做成了显式参数。

---

## 4. 问题 3：Yummy / Vomy

### 4.1 诚实的证据盘点

| 项 | 公开证据 |
|---|---|
| **Vomy** | 有，但**全部是 [C] 级第三方转述**。原作者本人的 YouTube 视频《The "Vomy" Setup and How to Spot and Trade it Using Saty Pivot Ribbon》确实存在，但正片内容我没取到；他的 X 帖只有一句"How to trade Vomy with Pivot Ribbon Pro. $SPX"。**指标源码里完全没有 Vomy 字样** [A]。 |
| **Yummy** | **公开网络上零结果。** 多轮检索（含 X / TradingView / YouTube / 论坛）没有任何一条把 "Yummy" 作为 Saty 术语的文献。它只存在于本仓库的 Discord 摘录里。 |

**因此：Vomy = [C]，Yummy = [D]。任何声称"Yummy 就是 X"的说法目前都没有出处。**

### 4.2 唯一一份公开的 Vomy 规则描述 [C]

来自 `getthatcashmoney.com` 的 "The Dolphin Vomit"（又名 SATY VOMY）及其
TradingView 收费脚本 `Cash Saty Vomy (STRATEGY)` 的说明页，两处口径一致：

> 1. 在 **10m** 图上等一个**清晰的、粗的（thick）**趋势成形，基于 **8/21/34** EMA
> 2. 价格开始**回撤**，ribbon 形成一个 **"Dolphin"（海豚）形状**
> 3. **10m 的 48 EMA 被击穿** → 入场信号，"告诉我们趋势正在破坏"
> 4. 该脚本跑在 **3m 图上、叠 10m ribbon**（正是 Saty 的 "Day 3/10" 模板）
> 5. 警告：附近若有关键 S/R，会出现假突破，必须先确认关键位已破

对照 Saty 本人的实盘语言（本仓库 Discord 摘录，[B]）：

> 「If trend breaks look for a **10m Vomy** down to PDC and then toward 200 key support」

两者吻合：**Vomy = 上涨趋势被破坏后的下行结构**，方向明确是**空头**，
且发生在 **10m** 上，目标是**下一个具名的位**（PDC / 关键支撑）。

→ **由此推断 [D]：Yummy = Vomy 的多头镜像**（下跌趋势被破坏后的上行结构）。
这是最自然的读法（"vomit / yummy" 的助记对仗），但**没有任何直接出处**。

### 4.3 三个候选定义（互斥，必须择一确认，不能靠回测挑）

三个都实现在 `ribbon_spec.py` 里，可以直接画到图上做人眼比对。

**候选 V1 — CONVICTION BREAK（第三方描述的直译，证据最强）**

```
vomy_v1(i):
    # 近 lookback 根内出现过"粗的多头排列"
    trend_was_bull = ∃ k ∈ [i-lookback, i) :
                        state[k] == full_bull  and  |ema8[k]-ema34[k]| / atr[k] >= min_thick
    # 现在已经不是多头排列了（ribbon 折了）
    and state[i] != full_bull
    # 且本根首次收在 48 conviction EMA 之下
    and close[i-1] >= ema48[i-1]  and  close[i] < ema48[i]
```

**候选 V2 — CONVICTION ARROW（只用指标自带原语，最简）**

```
vomy_v2(i):  ema13[i-1] >= ema48[i-1]  and  ema13[i] < ema48[i]      # 空头确信箭头
yummy_v2(i): ema13[i-1] <  ema48[i-1]  and  ema13[i] >= ema48[i]     # 多头确信箭头
```

理由：指标里唯一"会画箭头的事件"就是它 [A]；如果 Saty 说"a 10m Vomy"指的是
"10m 上出现了一个空头 conviction arrow"，这是最省事也最自洽的解释。

**候选 V3 — FULL RIBBON FLIP（纯形态，不看 48）**

```
vomy_v3(i):
    trend_was_bull(i, lookback, min_thick)
    and state[i-1] != full_bear  and  state[i] == full_bear     # 折叠彻底完成
```

理由：如果 "Dolphin" 指的是 ribbon 本身翻面的形状，那 48 只是第三方作者加的确认。

**实测触发频率（SPX 10m，60 个交易日，`lookback=20`、`min_thick=1.0 ATR`）：**

| 候选 | Vomy 次数 | 次/日 | Yummy 次数 | 次/日 |
|---|---:|---:|---:|---:|
| V1 conviction break | 31 | 0.52 | 29 | 0.48 |
| V2 conviction arrow | 21 | 0.35 | 20 | 0.33 |
| V3 full ribbon flip | 15 | 0.25 | 16 | 0.27 |

**重叠度（同一根 K 同时触发的次数）：V1∩V2 = 0，V1∩V3 = 0，V2∩V3 = 9。**

> **这就是本节最重要的一句话：三个定义几乎完全不重叠。**
> 它们不是"同一件事的三种写法"，而是**三个不同的策略**。
> 在没有确认哪个是对的之前跑任何基准率统计，得到的数字都不能归因给 "Vomy"。
> 而且 `lookback` 与 `min_thick` 是我为了让 "clear thick trend" 可编码而**引入的自由参数**，
> 目前用的是 20 根 / 1.0 ATR，**未经任何搜索**——一旦开始搜它们，就必须报格子数。

### 4.4 反对"Yummy/Vomy = ribbon 的多空状态"这一读法

`docs/SATY_RIPSTER_METHOD_STUDY.md` 的术语表把它写成
"Pivot Ribbon 的多头/空头结构态"。**这条应当降级。**
理由：Saty 的原句是 "look for **a** 10m Vomy"——带不定冠词、是**可数的事件**，
而不是一个持续存在的**状态**。状态用不着"look for"。
→ Yummy/Vomy 是**事件/setup**，不是 `full_bull`/`full_bear` 的别名。**[D]，但推理链清楚。**

---

## 5. 问题 4："holding H21" / "rejected bearish daily ribbon"

### 5.1 命名 [B]

**H21 / D21 / W21 = 小时线 / 日线 / 周线的 21 EMA**，也就是 ribbon 的 **pivot 线**。

直接证据：Saty 本人 X 帖 —— "Rejected at the **Daily 21 EMA** on #ES_F to open 2023.
We are (still) in a box."（他用全称写了一次，日常缩写成 D21）[B]。
TradingView 说明也把 21 叫做 "pivot EMA" [B]。

**另外一条极重要的细节**：本仓库 Discord 摘录里他写的是
「Clear resistance from Friday overhead which is also the **H21 (RTH)**」——
**他会显式标注这个 EMA 是按 RTH 还是 ETH 算的**。这直接证明会话选择是他方法的一部分，
不是实现细节（见 §6）。

### 5.2 机械化条件 [D]（语义清楚，阈值是我定的）

```
# "holding H21"：回踩 21 EMA 但收回其上（在小时线上判）
holding_pivot(bar, tol_atr=0):
    return bar.low <= ema21 + tol_atr*atr  and  bar.close > ema21

# 空头镜像 "losing H21"
losing_pivot(bar, tol_atr=0):
    return bar.high >= ema21 - tol_atr*atr  and  bar.close < ema21

# "rejected bearish daily ribbon"：日线 ribbon 空头排列，价格从下方戳进 ribbon 体后被打回
rejected_bearish_ribbon(bar):
    return state == full_bear
       and bar.high  >= min(ema8, ema21, ema34)      # 触到 ribbon 下沿
       and bar.close <  min(ema8, ema21, ema34)      # 收在 ribbon 之外
```

"ribbon body" = `[min(e8,e21,e34), max(e8,e21,e34)]`，这是他说 "into the ribbon" 时指的区域。

实测频率（口径：RTH，我们的 `satylab.data`）：

- 小时线 5090 根（预热后 5057 根可判）：`holding H21` **538 根 = 10.6%**
- 日线 5030 根（20 年）：`rejected bearish daily ribbon` **249 次**；
  日线 ribbon 状态分布 `full_bull 3130 / full_bear 1119 / folded 748`
  → **20 年里 SPX 日线 ribbon 有 62% 的时间是多头排列**。
  这本身就是一条有用的基准率：**"日线 ribbon 看空"是一个相对罕见（22%）的状态**，
  不应该被当成常态过滤器随手用。

> ⚠️ `tol_atr=0` 是我选的默认值，不是文献值。它一动就是一个可择优参数。

---

## 6. 会话（ETH vs RTH）：实测的保真度风险

这一节是我在做核验时**发现的、原任务没问到但会毁掉一切的东西**。

- Saty 公布的模板全部写着 `10m (ETH)` / `3m (ETH)` —— **他的图默认走延长时段**。
- 源码里 conviction 层**强制** `session.extended`；ribbon 三条线**跟随图表设置** [A]。
- 我们的 `satylab.data` 只有 **RTH** 数据。

`research/ribbon_session_probe.py` 实测（SPY，30 天 5m → 时钟对齐的 10m）：

| 口径 | ribbon 状态一致率 | \|ETH21 − RTH21\| 中位 | p90 |
|---|---:|---:|---:|
| 全天 | **73.6%**（837/1138） | $0.244 | $1.915 |
| **开盘第一小时（≤10:30）** | **48.8%**（99/203） | **$1.189** | **$4.687** |

（SPY ≈ $739，故第一小时的 p90 偏差 ≈ **0.63% 的价格**——比一整天的 ATR 档距还大。）

**结论：**
1. **开盘第一小时，RTH ribbon 与 ETH ribbon 几乎是在掷硬币级别的不一致（48.8%）。**
   而 Golden Gate 的高胜率档（开盘触发 ~90%、09:30 档 ~70%）**恰好全部落在这一小时**。
   如果我们用 RTH ribbon 去过滤开盘 GG，我们过滤用的根本不是 Saty 看到的那条线。
2. **对 SPX 本身这个问题不存在**：`^GSPC` 是指数，只在 09:30–16:00 计算，没有延长时段。
   所以我们现有的 SPX ribbon 在**符号内部是自洽的**。
3. 但 **Saty 本人多半在看 SPY / ES 的 ETH 图**（他会特意标 "(RTH)" 说明 ETH 是默认）。
   所以"我们的 SPX RTH ribbon" ≠ "他嘴里的 H21"。
   **在跨 symbol 引用他的判断时必须先对齐会话，否则是在比两条不同的线。**

**行动项**：如果要复现他的读数，数据层需要一个 ETH 通道（SPY 或 ES 的 `includePrePost=true`）。
这需要改 `satylab.data`，属于共享模块，**留给主线决定，我没有动。**

---

## 7. 问题 5：Saty 拿 ribbon 做什么决策

按证据强度排序：

### 7.1 趋势 / 方向过滤（主用途）[B]

他的 Golden Gate 教学视频说明原话大意：价格穿过 38.2% 后有 60%+ 概率到 61.8%，
**"The ribbon is used to add conviction with trend"**（ribbon 用来给趋势加确信）[B/C]。
→ **ribbon 不产生 GG 信号，它决定这个 GG 值不值得做、往哪个方向做。**
这与本仓库 GG 复核报告的结论完全一致：**GG 是目标/概率层，ribbon 是方向层。**

### 7.2 动态支撑阻力（第二用途）[B]

"holding H21"、"rejected at the Daily 21 EMA"、"rejected bearish daily ribbon" —
这些句子里 ribbon **本身就是一个具名的位**，和 PDC、±ATR 档、心理整数位并列。
**这正好补上了 IDM 缺的东西**：我们的位池里没有 EMA 族。
TradingView 官方说明也把它定位成 "trend **and support/resistance**" [B]。

### 7.3 入场触发（第三用途，且从不单独成立）[B/C]

Saty 的入场语言永远是**叠加**的：
「3m extreme **at demand/support**」「10m has room」——
**ribbon 提供"趋势是否完好"这一票，位提供"在哪"这一票，Phase 提供"是否极端"这一票。**
唯一一个以 ribbon 为主触发的 setup 就是 Vomy（趋势破坏），而它恰恰是**反趋势**的。

### 7.4 止损位置 [C/D]

第三方 Vomy 描述里没有给止损。但从 §7.2 的用法可以直接推出自然止损：
**ribbon body 的对侧**（多头：`ema21` 或 `body_lo` 之下；空头：`body_hi` 之上）。
这与 Bilbo Box "区间本身就是止损"的思路同构——**用结构做止损，不发明缓冲**。
**[D]，但与他的其它 setup 一致。**

### 7.5 多周期语境 = TimeWarp [A/B]

"Day 3/10" 模板：执行在 3m，趋势层看 10m。
他的实盘句「3m extreme here. **10m has room**」就是这个模板的直接读法。
**一张图两层，不需要两个窗口互相镜像。**

---

## 8. 可直接实现的伪代码（汇总）

已实现于 `research/satylab/ribbon_spec.py`。核心：

```python
# ---------- 层 1：ribbon（在【ribbon 周期】的 K 上算，来源 close）----------
e8, e21, e34 = ema(close, 8), ema(close, 21), ema(close, 34)
e13, e48     = ema(close, 13), ema(close, 48)        # conviction 层

fast_cloud_bull = e8  >= e21          # 绿 / 红
slow_cloud_bull = e21 >= e34          # 青 / 橙

state = "full_bull" if (fast_cloud_bull and slow_cloud_bull) else \
        "full_bear" if (not fast_cloud_bull and not slow_cloud_bull) else "folded"

body_lo, body_hi = min(e8,e21,e34), max(e8,e21,e34)
price_zone = "above" if close > body_hi else "below" if close < body_lo else "inside"
thickness  = abs(e8 - e34) / atr      # "thick / clear trend" 的可编码代理

conviction_bull  = e13 >= e48
conviction_arrow = "bullish" if (conviction_bull and not prev_conviction_bull) else \
                   "bearish" if (prev_conviction_bull and not conviction_bull) else None

fold_event = "fast_fold_up"   if (not prev.fast_cloud_bull and fast_cloud_bull) else \
             "fast_fold_down" if (prev.fast_cloud_bull and not fast_cloud_bull) else \
             "slow_fold_up"   if (not prev.slow_cloud_bull and slow_cloud_bull) else \
             "slow_fold_down" if (prev.slow_cloud_bull and not slow_cloud_bull) else None

# ---------- 层 2：TimeWarp（把上面整包投影到执行周期）----------
# 关键：EMA 在【上级】K 上算完，再按"最近一根【已收】上级 K"阶梯前推。
for each exec_bar b:
    j = index of the HTF bar CONTAINING b
    frame(b) = htf_frame[j - 1]        # -1 = lookahead_off 的语义；不是 j
    # 结果必然是阶梯状：同一根 HTF K 内的所有执行 K 共用一个值

# ---------- 层 3：Saty 语言 ----------
holding_pivot   = (low  <= e21) and (close >  e21)      # "holding H21"
losing_pivot    = (high >= e21) and (close <  e21)
rejected_bear_ribbon = (state == "full_bear") and (high >= body_lo) and (close < body_lo)
rejected_bull_ribbon = (state == "full_bull") and (low  <= body_hi) and (close > body_hi)
bias_bull       = close >= e21                          # bias candle 上色

# ---------- 层 4：Yummy / Vomy —— 三选一，尚未确认 ----------
# 见 §4.3；vomy_v1 / vomy_v2 / vomy_v3 与各自的 yummy_ 镜像
```

---

## 9. 与本仓库现有代码的差异清单

| 现有 | 判定 | 说明 |
|---|---|---|
| `indicators.FAST/SLOW/CONTEXT = 8/21/34` | ✅ **正确** | 与 [A] 一致 |
| `indicators.ema()` SMA 播种 | ✅ **正确** | 与 TradingView `ta.ema` 预热一致 |
| `indicators.ribbon()` 用 `close` | ✅ **正确** | [A] |
| `indicators.timewarp()` 取 `hi_states[j-1]` | ✅ **正确** | 与 `lookahead_off` 语义一致；敏感度实测 5.9% |
| `RibbonState.label()` 四态 | ⚠️ **是我们发明的** | Saty 原生只有两朵云的颜色对（3 态）。`in_ribbon`/`conflict` 混合了"价格位置"和"EMA 排列"两个正交维度，**建议拆开报告**（`state` × `price_zone` = 3×3），不要再用一个合成标签 |
| conviction 13/48 层 | ❌ **完全缺失** | 这是 Vomy 三个候选定义里两个的核心；必须补 |
| ribbon 的粗细（thickness） | ❌ **缺失** | "clear thick trend" 需要它 |
| ribbon body 作为位 | ❌ **缺失** | §7.2 的主用途，应进入位池 |
| ETH 会话通道 | ❌ **缺失** | §6，开盘第一小时不一致率 51% |
| `phase_oscillator` 用 21 EMA + ATR 归一 | ⚠️ **未在本次任务范围内核实** | Phase Oscillator 是另一个指标，另有源码，需单独钉定义 |

---

## 10. 未决问题（按优先级；前两条不解决就不要开始统计）

1. **Yummy / Vomy 到底是 V1、V2 还是 V3？**
   → 用户是 Saty+ Discord 付费成员。**直接问原作者或搜频道历史**，
   这比任何回测都便宜、都可靠。给出的三个候选可以直接贴图对照。
   *在确认之前，任何 "Vomy 基准率" 都是三选一的赌博。*
2. **conviction 层是否含未来函数？**（§3.4）
   → 人工打开 `saty_pivot_ribbon.pine`，读 `price` 与两条 conviction EMA 的那 3 行。
   如果 `lookahead_on` 没有被偏移抵消，**V2 候选直接作废**（它整个建立在 13/48 上）。
3. **我们要不要建 ETH 数据通道？**（§6）
   → 影响所有"用 ribbon 过滤开盘 GG"的结论。
4. **"clear thick trend" 的原始定义是什么？**
   → 我用 `|e8-e34| / ATR >= 1.0` 且回看 20 根做代理，**这是我编的**。
   Saty 大概率是目视判断。如果最终要量化，必须预登记阈值，不能搜。
5. **Dolphin 形状到底指什么？**
   → 第三方说是"回撤时 ribbon 形成的形状"，但没给几何定义。
   可能是快线下潜后回升的 V 形（"海豚入水"），也可能是整条 ribbon 的收敛-发散。
   YouTube 正片（eYeUS5wRwKg）应该有答案，本次未取到逐字稿。
6. **3m 数据源缺失。** Yahoo 不提供 3m K；我们能造的最细执行周期是 5m（仅 60 天）。
   → 我们**无法精确复现 "Day 3/10" 模板**。可行的替代是 **5m 执行 + 10m TimeWarp**
   （已在 `ribbon_spec.py` 自检里跑通），并明确标注这不是他的原始配置。

---

## 11. 复现方式

```bash
cd "/Users/lukegogogo/claude code projects/idm-tradingview-research"

# 参考实现自检：ribbon 状态分布、fold/conviction 事件数、
# 三个 Yummy/Vomy 候选的触发频率与重叠度、TimeWarp lag 敏感度、H21/D21 频率
.venv/bin/python research/satylab/ribbon_spec.py

# 会话保真度实测（需要联网，一次 Yahoo 请求 ×2）
.venv/bin/python research/ribbon_session_probe.py SPY
```

自检输出（2026-07-25，SPX 60 天 5m→10m）：

```
10m ribbon state distribution:  full_bull 48.3% / full_bear 34.4% / folded 17.3%
price vs ribbon body:           above 44.7% / inside 22.0% / below 33.3%
fold events on 10m: 137        conviction arrows on 10m: 41
vomy_v1 31 (0.52/日)  vomy_v2 21 (0.35/日)  vomy_v3 15 (0.25/日)
   v1&v2 同根 K: 0    v1&v3: 0    v2&v3: 9
TimeWarp lag=0 vs lag=1 状态差异: 274/4613 = 5.9%
hourly 'holding H21': 538/5057 = 10.6%
daily ribbon: full_bull 3130 / full_bear 1119 / folded 748
```

**未做的事**：没有碰 TradingView、没有开浏览器、没有改线上 Pine、
没有修改 `satylab` 既有模块、没有 git commit。
`ribbon_spec.py` 与 `ribbon_session_probe.py` 都是新增的独立文件。

---

## 附：一句话给主线

**Ribbon 的定义（8/21/34 close + 13/48 conviction + 阶梯式 TimeWarp）已经钉死到源码级，
可以直接实现；Yummy/Vomy 的定义没有钉死，而且三个候选互不重叠——
这一格必须靠 Discord 一手信息填，不能靠回测挑。
另外，开盘第一小时 RTH 与 ETH 的 ribbon 状态只有 48.8% 一致，
而这正是 Golden Gate 唯一有高胜率的时间段。**
