# IDM v12 代码结构地图（2026-07-22，对应 12.1.0-follower / TV v17.0）

> 12.1 重构：§13-15 改为**纯核心架构**——`f_f12_core(processBar, sig, planGate, OHLC, 时间)` 自持状态
> （函数级 var，每调用点一个实例），3m 本机与 10m 的 lower-tf 请求各自调用同一核心做确定性重演；
> 事件以 primitive 元组返回（24 字段），10m 镜像按行消费事件（真实 3m 时间/价格画标签）+ 末行 dense 状态。
> 前向协议常量 F12_PROTOCOL_ID / F12_FORWARD_START_MS；推送带 META 幂等行；参数指纹 f12OfficialConfigOk。

> 依据独立代码审查（`research/reports/IDM_V12_CODE_REVIEW_2026-07-22.md`）整理；行号以 v12.0.1 为准（±5 行漂移属正常）。
> 两条铁律：①字节冻结区（§6）绝不可改，契约测试逐字比对；②跟单交易规则（§13 决策逻辑）预登记冻结，改=记分板清零。

## 分段地图

| # | 段 | 起始锚 | 职责 | 保护级别 |
|---|---|---|---|---|
| 1 | 文件头 + strategy() | `// IDM v11.2 Clear → IDM v12 Follower` | 版本契约叙述；max_labels 400 / max_lines 30 | 12.0 契约注释 |
| 2 | 常量 | `// Constants` | VERSION_ID、SIDE/SETUP/GRADE/ROLE/EVENT 码表 | — |
| 3 | 输入（组 01–07）+ 主机判定 | `string G_SYSTEM =` | 全部 input；hostIsCanonical3m/hostIs10m/f12HostOk/engineEventsVisible | ⚠ 引擎参数输入=行为敏感 |
| 4 | 类型 + 空构造 | `type V11Signal` | V11Signal/Plan/Snapshot | 等效冻结（引擎按字段序构造） |
| 5 | 纯助手（两类混居） | `// Pure helpers` | **引擎喂给**（f_pick_*、f_candidate_*、f_nearest_saty、f_setup_priority）+ 展示文案（f_*_zh、f_signal_message） | ⚠ 冻结洞：喂给函数改动不触发字节测试却改行为——动前必须过 replica 回归 |
| 6 | **冻结引擎** | `f_v11_engine(bool processConfirmedClose) =>` | 信号/计划/事件唯一裁决 | **字节冻结**（测试逐字比对） |
| 7 | Saty 二拒 advisory + f_alert_pass | `// Saty second-rejection advisory (11.1)` | 二拒状态机、提醒过滤 | 行为契约（`f_alert_pass(`×3 钉死） |
| 8 | 中继层 | `// Dense state + sparse primitive event relay` | 稀疏脉冲元组、10m 端消费、历史标签（v12.0.1 起带三道显示遮罩）、中继推送（信号/计划事件均带 f12 闸门） | `= request.security_lower_tf(`×2 钉死 |
| 9 | 3m 本机推送 | `// Natural-language alerts:` | 旧信号流/旧计划事件流（默认被 f12 闸门关闭）、Saty 二拒 | — |
| 10 | 订单模块（默认关） | `// Optional broker emulator.` | strategy.* 研究脚手架 | 语义冻结 |
| 11 | 云层 + 数据窗价位 | `// Minimal price-attached chart` | Ripster 式三组云；S1/R1 仅数据窗 | plot 文案有钉 |
| 12 | GC 助手 + 旧计划四线 | `// GC-immunity:` | f_fresh_label/line、planLn*（v12 模式隐藏） | islast 重建模式 |
| 13 | **v12 跟单状态机** | `// v12 跟单模块 (follower)` | F12State、决策块（纯计算，零 alert/label——CE10057 纪律） | **规则冻结**；`f12.stop :=`×1 钉死 |
| 14 | v12 效果块 | `// Effects: labels and the push queue.` | 开/平/T1/T2 标签 + 【v12跟单】队列（毛/费后双轨） | 只读 f12 |
| 15 | 10m 状态镜像 | `// ── v12 状态镜像（10m 窗）──` | f_f12_state_snapshot → m12*；10m 开/平标签 | 镜像区禁回写 f12（regex 钉死） |
| 16 | 统一显示值 + 跟单四线 | `// unified display values:` | dispF12*；f12Ln* | `f12Vis` 行钉死 |
| 17 | Saty 日梯 | `// ── Static Saty daily ladder` | 梯位线/标签（按日锚重建） | 线预算 24/30，扩梯先升上限 |
| 18 | 3m 标记 + 引擎事件形状 | `// 11.1 declutter:` | 买/卖 A/B/C 等 plotshape；引擎事件形状（v12 默认隐藏，showEngineEvents 恢复） | — |
| 19 | 最新信号卡 + 右缘价签 | `// Latest detailed signal` | 卡（跟单持仓期隐藏）；三价签（v12 模式隐藏） | — |
| 20 | 四行面板 | `// Four-row dashboard.` | 现在=跟单叙事(v12)/引擎叙事(旧)；背景=10m 语境+日锚；下一步=引擎触发参考；计划=跟单状态+毛/费后记分板 | `"IDM v12｜"+hostText` 钉死 |
| 21 | 数据窗审计 | `// Data Window audit fields` | 审计 plot | — |

## 推送流一览（v12 默认）

| 流 | 默认 | 开关 |
|---|---|---|
| 【v12跟单】开/平/T1/T2（毛+费后） | **开** | f12Enable |
| Saty 二拒位置提醒 | 开 | enableSatyAdvisory |
| 旧·每信号推送（3m + 10m 中继） | 关 | f12SignalAlertsToo |
| 旧·计划事件推送（3m + 10m 中继，两路同闸） | 关 | f12EnginePushes |
| 订单成交（orders 模式） | 关 | enableOrders |

## 资源预算（v12.0.1 实测）

plot 类 50/64；线对象稳态 24/30；标签 400 上限（中继标签已遮罩减洪）；security 8/40。

## 已知设计边界

- 3m 主机跟单状态算在 calc_bars_count=1500（≈3 天）上，10m 镜像的 lower_tf 请求覆盖 4000 根 3m（≈8 天）→ 两窗「累计R」基数可不同（属已声明设计）；前向记分以 3m 窗为准。
- 10m 镜像的平仓标签位置取整根 10m K（金额精确）；开仓标签用真实 3m 开仓时间。
- 中继端 Saty 二拒文案是 f_advisory_message 的手工内联副本，两处需人工同步。
