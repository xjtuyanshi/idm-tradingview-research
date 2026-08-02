# IDM Phase 1 R3.2 可见原因 UI 验收 — 2026-08-02

## 结论

**R3.2 通过源码、离线合同与 TradingView 在线编译/深色主题/缩放验收。**

R3.2 是 R3.1 的纯展示修订：10m 与 3m 当前卡片从四行增为五行，顺序固定为：

```text
现在做 → 原因 → 触发 → 失效 → 目标
```

本修订没有改变 canonical signal engine、阈值、状态机、事件、marker 条件、保护或目标语义；不构成盈利能力、实盘成交、实时提醒可靠性或自动交易证明。

## 为什么不继续叫 R3.1

已验收的历史 R3.1 完整源码哈希保持不变：

- 10m R3.1：`ec2f8eee96960d8f95c6a2035181bfa0e319e498bdd12a988f2a9678bde138ba`
- 3m R3.1：`f349baa860124a386396b173780567cc842a3591f894b99d97381d6726af6c8f`

新增原因行会改变完整 Pine 文件字节，因此不能静默覆盖旧验收记录。R3.2 明确 supersede R3.1 的展示层，但沿用同一 canonical engine。

## 实际修改

1. 10m 与 3m 卡片新增高对比度白字 `原因` 行。
2. 原因紧跟 `现在做`，避免先看到触发/保护却不知道当前结论依据。
3. 可见文案移除 `later / active / episode` 等内部术语。
4. 已入场状态写成 `入场信号已触发｜跟踪保护/目标`，不声称用户实际成交或持仓。
5. 10m `REASON_ACTIVE_EXPIRED` 显式映射；未知未来 reason 显示 `未知原因`，不得误报成计划超时。
6. 原因枚举完整性进入静态合同测试。

## Reviewer 结论

- Trader/UI reviewer：五行布局与最终纯中文文案 **ACCEPT**。
- Position-reversal adversarial reviewer：确认反向移除展示补丁后精确恢复历史 R3.1 哈希；engine/阈值/事件无漂移。要求建立新 presentation revision、显式 unknown fallback、重新 pin 当前展示依赖；这些要求均已落实。

## 源码身份

- Git 基线：`c6f1017df1655d932f5d834737cdac66cc292988`
- canonical engine SHA-256：`c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2`
- 10m R3.2：
  - bytes：`50,723`
  - SHA-256：`aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2`
- 3m R3.2：
  - bytes：`70,921`
  - SHA-256：`f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e`

## 离线门禁

- Generator parity：PASS。
- 原因 UI + lifecycle + reversal dependency 专项：`56 passed, 3 skipped`。
- 全仓门禁：`1066 passed, 130 skipped`。
- skipped 项是仓库外私有 TradingView/Capital.com replay 或 33d evidence，不计作通过，也不计作失败。

## TradingView 在线验收

- Layout：`IDM R1｜3m执行·10m结构`
- 左侧：`CAPITALCOM:SPX500`，10m，`IDM Phase 1｜10m 交易计划 v3.2`
- 右上：`CAPITALCOM:SPX500`，3m，`IDM Phase 1｜3m 入场管理 v3.2`
- 右下：`TVC:VIX`，10m（观察上下文，不生成 SPX entry permission）
- 时区：`UTC-4`（America/New_York）
- 两份 Pine：在线编译成功并保存。
- Layout：`All changes saved`。
- 当前市场数据：Capital.com Jul 31 收盘，市场关闭；当前卡片无 active 计划：
  - 10m：`等待 10m 计划`；原因 `21/48 方向已失效`
  - 3m：`等待 10m 计划`；原因 `10m 尚无可用主计划`
- 在 10m 与 3m 分别执行缩放后，5/12 cloud、21/48 EMA 与 K 线保持同一价格/时间锚；五行卡片固定在视窗角落。
- 自动化拖动在当前 cursor mode 只产生 crosshair，没有实际水平平移时间窗，因此不声称完成了真正的 horizontal-pan gate；缩放下未复现曲线与 K 线分离。

验收截图：

- 仓库外持久 evidence 根目录：`tradingview_online/r32_visible_cause_20260802.png`
- bytes：`241,269`
- SHA-256：`bbaae0f37b2ad66ce1a1d0fadf0697b264f037dff15e5291c4d60fac6ba6585b`

## 仍未验证

1. 当前 R3 仍只有 337 根真实 10m / 两组 linked 3m 案例；没有 current-R3 30 天或 90 天可因果复盘数据。
2. 不声称胜率、盈利能力、期权执行质量、滑点后收益或手机 alert 可靠性。
3. 位置不破反转仍是独立 lane，尚未并入当前 10m trend-continuation plan。
4. VIX、ATR level、divergence 仍是独立观察维度，尚未获得改变当前计划的 permission contract。
5. 下一次有真实 active WATCH/plan 时，仍需做一次 forward visual acceptance，核对原因、触发、保护、目标和 terminal owner 是否符合当时可见信息。

## Git / 外部状态

- 当前为本地源码改动 + TradingView 云端脚本/layout 更新。
- 未提交、未 push、未创建 PR、未部署、未发送订单、未创建 alert。
