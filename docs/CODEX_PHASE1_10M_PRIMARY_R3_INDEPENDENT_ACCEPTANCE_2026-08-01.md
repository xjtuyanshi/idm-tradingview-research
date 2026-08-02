# Codex Phase 1 10m-primary R3 独立验收

日期：2026-08-01
状态：**源码、隔离仓库、真实 CSV replay、独立代码审查与 TradingView Desktop 在线编译/布局/锚定门禁 PASS；实时前向和盈利 edge 未验证**
权限状态：本地未提交修改；未 stage、未 commit、未 push、未建 PR、未部署、未启用订单或真实 alert。

## 1. 本轮真正实现的功能

R3 把界面和状态职责拆成两层：

1. `idm_phase1_10m_primary_opportunity_v3.pine` 是主图：
   - Ripster EMA5/12 快云；
   - EMA21/48 慢结构；
   - 方向、首次 later 触云反应、冻结失效位、具名目标与至少 `1R` 空间；
   - 仅显示 `观多 / 观空 / 主多 / 主空` 四类价格锚定 marker；
   - `WATCH` 不授权 3m，`MAIN` 才能建立不可变 plan。
2. `idm_phase1_3m_opportunity_timing_v3.pine` 是辅图：
   - 只消费 previous-completed 10m plan；
   - 采用新 plan 的同一根 3m K 禁止入场；
   - 等 3m 5/12 回踩和 later confirmed trigger；
   - 仅显示 `多入 / 空入 / 失 / 达` 四类执行 marker；
   - 已入场 plan 持续拥有冻结保护和目标，直至真正 terminal event。
3. 两个脚本均为 `overlay=true`，无独立 `scale`，无 `label.new`、`line.new`、`box.new`、orders、alerts 或 `strategy.*`。
4. 位置不破反转、divergence 和 VIX confluence 未混入 R3。它们保留为下一条独立 lane，避免与本轮顺势主线冲突。

## 2. 基线、Pro 对话与交付包

- 仓库基线 commit：`c6f1017df1655d932f5d834737cdac66cc292988`
- 当前分支：`codex/minimal-signal-rebuild`
- ChatGPT Pro 对话：<https://chatgpt.com/c/6a6e33d9-9ac4-83e8-9e70-38b774edfcad>
- R3 clean ZIP：`idm-phase1-10m-primary-correction-r3-c6f1017-20260801-clean.zip`
- R3 ZIP bytes：`163232`
- R3 ZIP SHA-256：`e976599a9f6c1c1c1dc9ddca59a55cc19c769f17c75717295baefc66d8281dff`
- 持久位置（仓库外）：`~/Documents/idm-tradingview-signal-evidence/chatgpt-pro-10m-primary-20260801/`

独立 ZIP 检查：CRC PASS；37/37 manifest entries PASS；无 duplicate name、unsafe path、symlink、encrypted entry、VCS/cache、凭据或绝对本机路径。

## 3. 要求 Pro 修正的问题

### R1：拒收

R1 的具名空间 router 使真实 337 根 10m replay 得到零个 `MAIN_LONG/MAIN_SHORT`，无法满足“10m 主图应给大机会”的任务目标。

### R2 P1-A：许可和已入场计划生命周期混淆

真实 2026-07-30 ET 链路：

- 07:10：10m `MAIN_LONG`；
- 07:21：3m 采用；
- 07:24：冻结回踩 trigger；
- 07:36：`LONG_ENTRY`；
- 09:30：10m `EXPIRED`；
- 16:00：价格到达冻结目标 `7450.20`。

R2 在 09:30 把许可到期错误翻译为 `OPPORTUNITY_ENDED`，丢掉已经进场的 plan，因而无法在 16:00 发布目标到达。R3 将 entry permission 与 entered-plan management 分离。

### R2 P1-B：残缺日冒充完整 prior day

R2 会在 ET 日切换时把残缺日状态晋升为 previous-day high/low。R3 只有在紧邻 ET 日期、严格 144 根、首根 00:00、末根 23:50、相邻 10 分钟无 gap 时才发布完整前一日水平。

## 4. Codex 独立真实 replay

输入：

- 10m：337 rows / 162588 bytes / SHA-256 `037ed7a18f93ae20ebca7cf755ff675086207f8f00110766975679d56245aa74`
- 3m：11815 rows / 5294757 bytes / SHA-256 `d5c915b99f2f813ffcb0308059a7fb9ed1b7589a893e6b6ff9a3493fc8237436`
- 因果重叠区：1121 根 3m K；10m 只在 `bar open + 10m` 后可见；source event 每个新 10m source 只交付一次。

两次独立运行输出字节级一致：

- JSON SHA-256：`e583d89fffdbdfaebd62218035e6ad160053ae298f26ad4ba7f57d34b28e7a2d`
- `LONG_ENTRY=1`
- `LONG_TARGET_REACHED=1`
- `SHORT_ENTRY=1`
- `SHORT_INVALIDATED=1`
- `NONE=1117`

关键回归：

| ET | 10m source | 3m state/event | 冻结 plan |
|---|---|---|---|
| 07:36 | active | `ENTERED / LONG_ENTRY` | stop `7345.7384`, target `7450.2` |
| 09:30 | `EXPIRED`, active plan 不再提供 | `ENTERED / ENTERED_PLAN_MANAGEMENT` | 同一 stop/target 继续保留 |
| 16:00 | no active permission | `LOCKED / LONG_TARGET_REACHED` | 同一 plan 正常结束 |

独立输出位于仓库外：

`~/Documents/idm-tradingview-signal-evidence/chatgpt-pro-10m-primary-20260801/codex-r2-independent-verification/`

## 5. 独立 Review Agent

最终裁决：**PASS，无 P0/P1**。它独立核对：

- 10m permission 与 3m entered owner 分离；
- terminal arbitration 先处理旧 owner 的冻结 invalidation/target；
- complete ET day 的 144-bar 连续性合同；
- 3m 方向只能来自 10m plan；
- source event 一次性 transport 与 plan identity 匹配；
- 10m/3m 各四个 marker、五行卡片、无动态漂移对象和交易副作用。

非阻断 P2：dual replay 人类可读日志包含输入文件名，因此同内容 CSV 改名后日志 SHA 会改变；事件 ledger 不受影响并与包内字节一致。若未来要求日志内容寻址，应规范化显示名或只记录内容 SHA。

## 6. 当前代码门禁

### Pro clean package

- package tests：`86 passed`
- generator `--check`：PASS
- canonical block SHA-256：`c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2`

### Codex 隔离完整仓库

- `scripts/validate.sh`：`959 passed, 130 skipped`
- frozen v11 SHA：PASS
- public release contract：`5 passed`
- generator byte parity：PASS
- Python compileall（外部 cache）：PASS
- `git diff --check`：PASS

### Codex 当前脏工作树

- `scripts/validate.sh`：`959 passed, 130 skipped`
- frozen v11 SHA：PASS
- public release contract：`5 passed`
- generator byte parity：PASS
- Python compileall（外部 cache）：PASS
- 高置信凭据扫描：0 hits
- 新增 CSV：0

130 个 skip 是未随公开仓库分发的私有行情 evidence，其中 R3 新增 7 个 fixture-dependent skip。真实 R3 10m+3m 链路已在仓库外单独执行，不能把 skip 说成 pass。

核心落地文件哈希：

- 10m Pine：`4f345a5f4b92a791ba7f3282f26b32a0014d0e1264bf9e84dc72e4838768807b`
- 3m Pine：`33127269ef841633dc9f82bf2d611369d753bc4d7ba4207d52fa437796c5f72b`
- Python oracle：`341a80e72af1c1ea4c2df48ab3f03576ddf0aeb8cdd8d35b6b1ee779f93dd91c`
- Pine generator：`7c9d0e4e8c788e9538aa93828eecc7d391cb4e0b143fd7fc5f791f35bc31582d`

## 7. TradingView Desktop 在线门禁

2026-08-01 已在登录账号 `shyan94689` 的 TradingView Desktop 实机执行，活动 layout 为 `IDM R1｜3m执行·10m结构`，图表时区为 `UTC-4`（ET）。本次未创建 alert、订单或策略交易。

### 7.1 在线编译与插入

- 左侧 `CAPITALCOM:SPX500` 10m：把本报告所列 SHA-256 对应的完整 10m Pine 源码粘贴至 Pine Editor，在线编译无错误，保存为 `IDM Phase 1｜10m 主机会 v3.0` 并加入图表；indicator count 从 9 增至 10。
- 右上 `CAPITALCOM:SPX500` 3m：把本报告所列 SHA-256 对应的完整 3m Pine 源码粘贴至 Pine Editor，在线编译无错误，保存为 `IDM Phase 1｜3m 机会择时 v3.0` 并加入图表；indicator count 从 5 增至 6。
- 两个脚本加入后均进入 `Update on chart` 状态；layout 显示 `All changes saved`。
- TradingView 账号已达到 10 个 layout 上限，因此没有新建 layout 副本；本轮在现有 layout 内修改并自动保存，没有删除任何 layout。

### 7.2 三窗与可读性整理

- 左侧保留 10m K 线、R3 5/12 快云、21/48 慢结构、SATy ATR 水平和 MTF 位置；隐藏旧 `IDM｜10m 大势卡 v0.2 R5.1`。
- SATy 只关闭顶端 Info Label，ATR 水平仍保留。
- 从左图移除 `Saty Phase Oscillator` 图表实例以收回空白副窗；脚本未删除，仍可重新加入。
- 右上保留 3m K 线、R3 5/12 快云和原 MTF 位置带；关闭旧指标的统一 MTF 管理卡，避免与 R3 五行状态卡叠放。
- 右下保留 `TVC:VIX` 10m 原有 cloud，当前仍是上下文窗，不参与 R3 入场 gate。

三窗实机截图：

![R3 TradingView 三窗布局](../../idm-tradingview-signal-evidence/tradingview-online-acceptance-20260801/phase1_r3_tradingview_three_pane_2026-08-01.jpeg)

- 持久证据：`../../idm-tradingview-signal-evidence/tradingview-online-acceptance-20260801/phase1_r3_tradingview_three_pane_2026-08-01.jpeg`
- 尺寸：1340 × 768；bytes：223283
- SHA-256：`a807af7bdd9609214e0bcdfe90cb2b88078c22d29aa20c607da65628224d63b3`

### 7.3 锚定与历史事件对位

- 在 10m 窗水平拖动时间轴后，5/12 cloud、21/48 结构线、ATR/MTF 水平仍随 K 线/时间轴移动，R3 状态卡保持角落锚定。
- 在 3m 窗水平拖动时间轴后，5/12 cloud 仍贴合 K 线，价格 marker 随对应 bar 移动，状态卡保持右下角锚定。
- 用 TradingView `Go to` 定位到 2026-07-30 07:30 ET，在相邻 07:36 bar 上在线看到绿色 `多入`，与独立 CSV replay 的 `LONG_ENTRY` 对位。它是 `plotshape(..., location.absolute)` 的价格/bar 锚定事件，不是 `label.new` 漂浮对象。
- 状态卡显示的是整张图最新 bar 的当前状态，不会随历史十字光标回到 07:36；因此历史 `多入` 可见时，卡片仍可能显示当前的 `等待 10m 主机会`，两者不是矛盾状态。

![R3 3m 07:36 多入](../../idm-tradingview-signal-evidence/tradingview-online-acceptance-20260801/phase1_r3_tradingview_3m_long_entry_2026-07-30_0736_et_crop.jpeg)

- 完整截图：`../../idm-tradingview-signal-evidence/tradingview-online-acceptance-20260801/phase1_r3_tradingview_3m_long_entry_2026-07-30_0736_et.jpeg`，1340 × 768，SHA-256 `c794af8a1e83515e1f0abc3bcccfd9b2361804bd5ca3c6eed50f8aac87b98150`
- 裁剪图：`../../idm-tradingview-signal-evidence/tradingview-online-acceptance-20260801/phase1_r3_tradingview_3m_long_entry_2026-07-30_0736_et_crop.jpeg`，520 × 260，SHA-256 `c3742b858f995ddb298988feae6d9873f474ec3efe3ae6a3af3310e6ddf7fe49`

## 8. 尚未通过或不能声称的内容

以下内容仍不能从本轮源码、replay、在线编译和截图推断：

- realtime 开盘期间的前向观察、跨 bar 更新和 market-data latency；
- Data Window 的逐字段人工审计与 TradingView Bar Replay 全链路录屏；
- remove/re-add 后所有用户自定义 input 的恢复行为；
- alert delivery、订单、券商连接或任何自动交易；
- 最近三个月 walk-forward 的胜率、期望值、盈亏比稳定性或真实盈利 edge；
- 位置不破反转、ATR 反应、oscillator/MACD divergence 与 VIX confluence；这些属于下一条独立 lane，尚未混入 R3。

本轮 `PASS` 的含义仅限：相同源码通过离线合同和真实 CSV replay，并已在 TradingView Desktop 在线编译、保存、插入正确窗格，视觉锚定和一条历史 `LONG_ENTRY` 对位通过。它不是盈利证明。
