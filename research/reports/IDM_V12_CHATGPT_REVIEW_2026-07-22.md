# ChatGPT Pro 独立审查（2026-07-22，Pro 深度推理 49m20s）——原文存档

> 由 Claude 操控网页版 ChatGPT Pro 完成投递与回收（附件=REVIEW_PACKAGE_v12.0.2）。
> 本文件为回答原文的纯文本存档（网页提取，代码块缩进有损）；处置状态见文末追注。

## 总体结论（原文摘录）

- v12 跟单状态机的主干算术基本正确：止损优先、同bar T1/T2 顺序、冷却端点、成本算式、同bar平仓不重开——均与 Python 原型一致，无核心 P0。
- 真正严重的问题在外围：
  - P0-1 当前 Pine 面板不是真正的前向、追加式记分板（加载回演/刷新重算/1500根窗口滚动；无法承载 60/385 笔长期验证）→ 需协议起点常量+协议ID+外部 append-only 账本（alert META 行）。
  - P0-2 预登记配置仍可被输入项静默改变（时段/冷却/逆势/成本，及冻结洞里的引擎参数）→ 建议 Official/Lab 双构建 + 引擎参数 fingerprint + "UNREGISTERED" 降级显示。
  - P0-3 字节冻结测试只查子串存在，不是活动切片等值 → 已当场落地（见追注）。
- P1：跟单核心与 displaySignal/newSignal 显示层耦合（CE10057 脆弱边界 + request 上下文中 barstate.isconfirmed 不可依赖）→ 建议纯核心 f_f12_core(processClose, snapshot) 重构；10m 镜像 last-value 会折叠 10m 内多事件 → 跟单事件也要走稀疏脉冲中继（OPEN/T1/T2/CLOSE + 单调ID）；当日高低 lookahead_on 是明确历史前视泄漏（官方定义的 future leak）；日终结算推送晚一根K（提议日界执行提醒）；openT 用 bar 开盘时间锚点偏移；异常几何可能把费后累计 na 化（fail-closed 防护）；Python oracle 日界等号边界（bisect_left）与 simulate/exit_bar 双实现漂移风险（合并为单一 Outcome）。
- P1-7 统计脚本口径：0R 计入亏损稀释均亏（EPS 三分类）；按日表用错配置（拒绝+突破）；"最大回撤"实为闭合权益口径。
- P2：islast 每 tick 删建 singleton（改 setter+历史标签环形缓冲）；ladder 只比对 anchor（ATR/PDH/PDL 变化不重建）；多处文案与规则不一致（"13天账本验证"组名、"净R"实为毛、逆势"快进快出"与 runner 矛盾、冷却无方向/截止显示、10m平仓标签位置注释与实现不符）；重复的 5 个 Frozen 计划 data-window plot；20 个 relay 空数组无条件创建；latest 卡不可达分支与平仓后复活；Saty relay 手工文案缺 firstTime/departTime、signal relay 用当前 context 而非事件时 context。
- 统计独立意见：同意"无正期望证据"方向（单笔 +2.90R 超过总收益 2.88R；~880 统计量择优后冠军为正几乎必然；成本断点 0.39 < 0.5 假设）。补充要求：按日 block bootstrap 且在每个重采样内完整重跑时序跟单流；贡献集中度指标放首屏；runner 机制单独建模（腿分解/存活率/条件概率/EOD 点差）；"60笔无≥+1.5R runner 即淘汰"在真实命中率 3%/2% 时误杀率 16%/30%，应定位为经济可行性门槛而非显著性检验；385笔+t≥1.645 必须预登记停止规则（否则 optional stopping，需 alpha spending / anytime-valid CS），且聚类使有效样本 < 笔数；验证标准应含经济下界（如费后均值单侧95%下界>0 且点估计≥+0.05R）；模型账本与真实成交账本分离（model_R vs actual_fill_R，摩擦淘汰必须基于 actual fills）。
- 明确不建议：动冻结引擎；改 50/25/25、止损不动、冷却、时段规则；去掉 plan gate（只跟新建冻结计划的拒绝信号，ADD/advisory 不进跟单——与 Python build_plans 一致）。

## 处置追注（Claude，2026-07-22 当日）

- ✅ 已落地（当场）：P0-3 冻结测试硬化（_unique_slice + 活动切片前缀等值 + 引擎文本唯一 + 余段必须是已记录的 Saty 插入段——上线即抓住并澄清了"活动切片≠冻结切片"的真实结构）；P1-6a bisect_left；P1-7 全部（EPS 三分类/按日表配置/回撤命名）——**修正后定案配置真实均亏 −0.88R、打平线 43.1% vs 正收益率 41.9%：样本内毛收益低于自身打平线**；P1-3 前视泄漏（v12.0.3）；P2 文案三处（组名/浮动毛/回放累计）；重复 Frozen plots 删除（v12.0.3）。
- ✅ v12.1.0 已落地（同日下午，TV v17.0，SHA `9d46911e`）：P0-1 协议起点常量（F12_FORWARD_START_MS=2026-07-22 09:30 ET，记分板只计前向开仓）+F12_PROTOCOL_ID+推送 META 幂等行；P0-2 参数指纹（19 项预登记默认+标的检查，偏离时面板"⚠未登记配置"降级）；P1-1 纯核心 f_f12_core（自持 var 状态/游标，输入仅 engine.signal+纯参数，零 alert/label，双实例=3m 本机+10m security 上下文各自确定性重演）；P1-2 镜像改事件中继（10m 从每行事件字段按真实 3m 时间/价格画开平仓标签，dense state 取末行自愈，彻底停用累计差值反推）；P1-4 日界执行提醒+事件时间锚（openT=eventTime，平仓标签=真实事件时刻）；P1-5 几何 fail-closed（f_f12_geometry_ok+dataErrors）；P1-6c Python 单一 simulate_follower（三合一返回 r/flat_i/full_stop，日界 busy 对齐 Pine，7 组数字复现逐位一致，顺带消灭旧 exit_bar 的 remaining>0.30 漂移）；P2：ladder 四值签名、冷却精确语义 tooltip、订单模块冲突警告、审计 plot ×5。
- ✅ v12.2.0 已落地（同日晚，TV v19.0，SHA `9c04423f`）：P2-1 全套——f_fresh_label/f_fresh_line 删除，13 个 var 单例改"一次创建+setter"，历史事件标签 8 处全部经 `f_keep_label` 环形缓冲（上限 330；加单例~13+梯位~22 恒低于 400 预算，GC 永不触发——GC 防护从"跑得快"变成"结构上不可能被回收"）；P2-7 latest 卡死分支删除+被跟单执行过的信号卡不再复活（latestConsumedSigId）。
- ❌ 明确不做（记录理由）：P2-6a relay 20 数组进分支——消费循环在顶层是设计（canonical 主机上数组恒空、开销为每根 K 20 个空数组分配，微不足道），搬结构风险>收益；P2-6b 两条 lower_tf 合并——省 1 个请求名额（现 8/40 不稀缺）但要把整个跟单核心搬到中继段之前，结构性大动作，收益不成比例；P2-5 Saty relay 完整上下文——只影响 10m 图挂 alert 的场景（当前 alert 在 3m），维持"手工同步"注记，列入远期。Official/Lab 双构建维持"单构建+指纹降级"方案。
- 统计协议修订：淘汰规则第三条改定位为"经济可行性门槛"；385笔检验补预登记停止规则与聚类方差；记分板双轨补 model_R/actual_fill_R 区分说明。
