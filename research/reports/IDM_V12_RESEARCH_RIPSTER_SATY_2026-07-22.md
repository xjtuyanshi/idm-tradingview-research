# 指标方法论研究报告：Ripster EMA Clouds、Saty 工具族与信号呈现最佳实践（供 IDM v12 参考）

> 由独立研究 agent 于 2026-07-22 完成；全部参数逐行核对自作者本人发布的源码（一手来源），
> 二手来源仅作交叉验证。本文件为 IDM v12 的视觉/规则依据存档。

## PART 1 — Ripster (Ripster47) EMA Clouds 精确方法论

原版脚本 "Ripster EMA Clouds"（© ripster47，MPL-2.0）默认参数（源码镜像
https://github.com/roscandra6/Ripstar ；原发布于 https://www.tradingview.com/u/ripster47/ ）：

| Cloud | EMA 对 | 角色（Saty 官方移植版命名） | 默认 |
|---|---|---|---|
| 1 | 8 / 9 | Pullback Cloud（回调买点云） | 开 |
| 2 | 5 / 13（TV 原版；ToS 移植版 5/12；教育站写"5-12 或 5-13"） | Fluid Trend（日内主趋势云） | 开 |
| 3 | 34 / 50 | Trend Cloud（方向偏置/结构云） | 开 |
| 4 | 72 / 89 | Mid-term Trend | 开 |
| 5 | 180 / 200 | Long-term Trend | 开 |
| 可选 | 20 / 21 | Pivot Cloud（MTF 工作流） | 教育站列可选 |

构造细节（源码原文）：**价格源默认 `hl2`**；MA 默认 EMA（可切 SMA）；EMA 线本身默认
**不显示**（只显示云带）。

周期工作流（Ripster 本人表述，https://www.ripstereducation.com/post/ema-clouds 及
Tenet 规则 PDF）：10 分钟图=日内主战场；34/50 云=任何周期的方向偏置与风险位
（"over 50 emas trend is bullish below is Bearish"）；8-9 云=回调挂单位；MTF 用法=图上叠加
日线 20/21 与 50/55 云；入场="Long when 5 cross 12 and short when 12 under 5"+ 开盘区间突破；
**出场原话："Intraday, let trend ride as long as 10 min candle rides 5-12 (5-13) cloud.
10 Min candle closes under → you get out intraday"**（结构跟踪，非固定目标）；
成交量确认=前 30 分钟量达日均量 20%；云的本质=支撑/阻力区，入场首选**云回踩**而非追突破。

视觉规范（原版源码色值）：

| 云 | 多头色 | 空头色 | transp |
|---|---|---|---|
| 8/9 | #036103 深绿 | #880e4f 酒红 | 45 |
| 5/13 | #4caf50 绿 | #f44336 红 | 65 |
| 34/50 | **#2196f3 蓝** | **#ffb74d 浅橙** | 70 |
| 72/89 | #009688 青绿 | #f06292 粉 | 65 |
| 180/200 | #05bed5 青 | #e65100 深橙 | 65 |

要点：触发云高饱和红绿、结构云蓝/浅橙且最淡；层次靠色相+透明度；线全部隐藏；
空头 34/50 刻意避开纯红以免与 5/13 冲突。

## PART 2 — Saty Mahajan 工具族精确方法论

### Saty ATR Levels（https://github.com/satymahajan/saty_atr_levels ）

- **锚 = 上一周期收盘**（extended session ticker，`close[1]` lookahead_on）；可选用当期收盘（默认关）。
- **ATR = `ta.atr(14)`（RMA）取 `[1]`**；Day 模式用日线 ATR14 昨值。
- 级别：触发 ±0.236（上=aqua 青/下=yellow 黄）；中间 ±0.382/±0.5/±0.786（灰）；
  **±0.618 关键目标（silver）**；±1.000 满幅（white）；扩展 ±1.236…±3.000 默认关。
- **Range 读数**：`(period_high−period_low)/ATR×100`，**≤70% 绿 / 70–90% 橙 / ≥90% 红**（幅度耗尽）。
- 趋势标签：8-21-34 EMA 完全堆叠判多空中性。
- 用法：Golden Gate（过 38.2 → 60%+ 概率到 61.8，https://www.youtube.com/watch?v=d43HaLb765k ）；
  级别到级别条件概率表（https://x.com/satymahajan/status/1837940467691859993 ）；
  ±23.6 之间=无倾向区；61.8 与 ±1 ATR 分批止盈；≥90% 后只剩均值回归或例外趋势日。
- 视觉：级别线 `plot.style_stepline` + 40 transp + 线宽 2；白=锚/整数 ATR、青/黄=触发、银=61.8 系。

### Saty Phase Oscillator（源码镜像 https://github.com/rishid/thinkscripts/blob/master/saty_phase_oscillator.tosts ）

```
pivot = EMA(close, 21)
osc = EMA(((close − pivot) / (3.0 × ATR14)) × 100, 3)
```
区带：+100 Extended Up / +61.8 Distribution / ±23.6 Launch Pad（中性）/ −61.8 Accumulation /
−100 Extended Down。**压缩检测：布林(21,2.0) 收进 2.0×ATR 通道=压缩（品红），
1.854×ATR 为解除阈值（滞回双阈值防抖）**。黄点=穿越 ±61.8/±100 的回归信号。

### Saty Pivot Ribbon（https://github.com/satymahajan/saty_pivot_ribbon ）

EMA 8/21/34（close）双云：8-21 green/red、21-34 aqua/orange，transp 60，线隐藏；
Conviction Arrows = 13/48 EMA 交叉；**Time Warp：3 分钟图上显示 10 分钟 ribbon
（Saty 的 SPX 剥头皮工作流，https://www.youtube.com/watch?v=k8yKdDDqN-M ）**。
代码注释原文致谢 Ripster："Special thanks to Ripster for his education and EMA Clouds…"

## PART 3 — 信号呈现最佳实践（清单）

防刷屏：状态机而非条件流（同状态期不重发）；one-per-swing（需反向 re-arm 事件）；
one-per-zone-touch（首次触区一次，破区永久失效）；滞回双阈值；同向最小间隔/最小位移；
分级替代重复（LuxAlgo 普通/强信号）。

呈现：信号=触发 bar 一个标签 + SL/TP 线段（非整屏水平线）；右角持仓面板（方向/入场/R/止损/下一目标）；
诚实披露（"信号于 K 线收盘确认，未收盘可变"；`barstate.isconfirmed`；MTF 用 `[1]`+lookahead_off；
TV 官方：>95% 指标存在某种重绘，https://www.tradingview.com/pine-script-docs/concepts/repainting/ ）。

出场：固定 R 目标 / ATR 跟踪（Chandelier 22,3×ATR）/ 结构跟踪（Ripster 云出场）三主流；
Chandelier 回测综合表现最好（https://volatilitybox.com/research/volatility-adjusted-stop-losses/ ）；
**保本陷阱：浮盈 ≥ +1R 前不动初始止损**（多来源一致）；50%@1R+立即保本必然把均赢封在
0.5–0.8R 而均亏 ≈ −1R——与 IDM r2 账本 +0.797/−0.911 完全吻合。

## 对 IDM v12 的建议（10 条）与采纳状态

1. 方向 episode 状态机（同 episode 最多 1 入场）→ **v12 跟单以"单仓+冷却"实现**（更强形式）。
2. 10m 34/50 偏置闸门、云内中性禁发 → v12.1 候选（引擎级）。
3. Range≥90% 耗尽闸门停发顺势新信号 → v12.1 候选（面板已显示 已走% 读数）。
4. 滞回双阈值 → v12.1 候选。
5. 信号≠入场：入场区带 + 回踩挂单 → v12.1 候选（不追价）。
6. 追高保护 distance filter → v12.1 候选。
7. **保本延迟/取消** → **v12 已实现**（跟单止损全程不动；实测正期望的必要条件）。
8. 1/3 分批 + ATR 级别目标 + Chandelier runner → 实验室已测（V3 不如 V1，未采纳）。
9. 趋势日例外（取消 T2 封顶交给跟踪）→ v12.1 候选。
10. 视觉系统：两层云 + stepline 级别 + 单列信息表 + 固定披露 → **大部分已实现**
    （5/12 高饱和红绿 + 34/50 蓝/浅橙 Ripster 原版色、静态 Saty 梯位、四行面板、跟单行）。
