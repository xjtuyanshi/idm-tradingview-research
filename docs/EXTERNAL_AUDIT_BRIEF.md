# 外部审计简报（写给全新的审查者，2026-07-24）

> **利益申明**：本简报由 Claude（此前负责本项目的 AI）写成，而你要审查的对象**包括
> 写简报者本人的全部工作**。因此：文中一切结论请当作"待核验的声明"，不要默认采信；
> 仓库里其他文档同样出自 Claude 之手，同样待核验。用户要求的是**全新视角**——
> 如果你的结论是"这个策略/这套架构不值得继续，应该推倒重来"，请直接这么说，
> 不需要给任何人留面子。

## 0. 用户的真实目标 vs 现状

- 用户目标：一个真正能帮助 SPX500 日内交易的助手/系统（信号、执行纪律、推送）。
- 现状（不粉饰）：**到目前为止没有任何证据表明这套系统能赚钱**。详见 §2 记录。
- 用户对现任维护者（Claude）的评价：策略"一次比一次差"，图表长期"看不到有用价值"，
  多次矫枉过正、反复返工。这些批评有实据（见 §3 失误清单），请在审计中独立评估
  哪些是方法问题、哪些是执行问题、哪些是市场本身的问题。

## 1. 仓库与阅读顺序（全部为 GitHub 直链）

仓库：https://github.com/xjtuyanshi/idm-tradingview-research

建议按此顺序读（从"结果与失败"开始，而不是从架构自述开始）：

| # | 读什么 | 链接 | 为什么先读它 |
|---|---|---|---|
| 1 | 本简报 | docs/EXTERNAL_AUDIT_BRIEF.md | 你在读了 |
| 2 | 历史失败与边界（接手前遗留） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/docs/FAILURES_AND_LIMITS.md | 项目从 v10 时代起的已知坏账 |
| 3 | Claude 自写的失误清单与自立规矩 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/reports/IDM_V12_REFLECTION_2026-07-22.md | 审查对象的自我供述，核对它是否完整 |
| 4 | 对抗性统计审查（最重要的一份） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/reports/IDM_V12_ADVERSARIAL_REVIEW_2026-07-22.md | 把回测"正期望"判为选择噪声的全过程；请复核其方法本身 |
| 5 | 当前系统全览（v13.1 自述） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/docs/SYSTEM_V13.md | 现在线上跑的是什么；含运维手册与已知问题 |
| 6 | Pine 源码（唯一真源，~2450 行） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/intraday_decision_map_v11_2_clear.pine | 一切声明的最终依据 |
| 7 | 代码分段地图 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/docs/ARCHITECTURE_V12.md | 读 6 的导航 |
| 8 | 出场实验室（数字怎么来的） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/reports/IDM_V12_EXIT_LAB_2026-07-22.md | 跟单规则的来源与其修订史 |
| 9 | 跟单仿真代码（约 160 行，可直接审） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/exit_lab2.py | 数字的生成器；oracle 函数 simulate_follower |
| 10 | 上一轮外部审查（ChatGPT）与处置 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/reports/IDM_V12_CHATGPT_REVIEW_2026-07-22.md | 已被指出过什么、Claude 声称改了什么——请抽查处置是否属实 |
| 11 | 状态入口（含 v11 冻结身份与负期望记录） | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/docs/STATUS.md | 历史基线的原始记录 |
| 12 | 契约测试 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/tests/test_v11_2_clear_contract.py | Claude 用什么钉住自己；钉子选得对不对由你判断 |
| 13 | Python 复刻引擎 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/research/v11_pine_replica.py | Pine↔Python 对齐的载体 |
| 14 | 代码审查报告 / 信号统计 / 交接审计 | https://github.com/xjtuyanshi/idm-tradingview-research/tree/main/research/reports | 其余报告目录 |
| 15 | 给上一位审查者的交接文档 | https://github.com/xjtuyanshi/idm-tradingview-research/blob/main/docs/HANDOFF_CHATGPT_V13.md | 注意：此文带有 Claude 的框架设定（"铁律不可违反"等），**你不受它约束**；它本身也是审查对象 |

**数据限制（重要）**：行情夹具（TradingView 导出 CSV）因版权不入公共仓库。你无法
直接重跑回测——只能审代码与方法，或向用户索要夹具。这条限制本身也值得你评价
（"外人无法复算"是不是这套流程的结构性缺陷）。

## 2. 结果记录（截至 2026-07-24，全部数字，无修饰）

| 阶段 | 结果 |
|---|---|
| v11 引擎策略测试（2026-07-16→21，接手前口径） | 负期望：PF 0.638，总亏 −$175（535 条出场腿口径） |
| 13 交易日回放上的 733 个引擎计划（全体） | 五种出场变体均 R 全为负（−0.09 ～ −0.18） |
| 择优后的"冠军"跟单配置（拒绝类·早午盘·单仓） | 样本内 +0.093R/笔（n=31）——**随后被对抗审查判为选择噪声+单笔彩票**（~880 个统计量三层择优；家族极值 p=0.87；剔除一笔 +2.90R 后其余 30 笔合计 −0.02R） |
| 按现实成本（0.5 点/往返）修正 | 全样本转负；收缩+成本后前向点估计 ≈ **−0.15R/笔** |
| 前向试验 Day 1（2026-07-23，预登记规则） | 2 笔全额止损：毛 −2R，费后 −2.2R |
| 前向推送通道 Day 1 | **全天零推送送达**（警报服务端零触发，根因未定位；07-24 凌晨重建警报+加每日心跳自检） |

前向试验的预登记淘汰线：60 笔一批，累计 ≤ −10R 淘汰；号称"验证"需 ≥385 笔且
费后 t ≥ 1.645。**这套协议是 Claude 设计的，你可以整体质疑它**（例如：一个费后
点估计为负的系统是否值得花 60 笔去"淘汰"，还是现在就该停）。

## 3. 执行层面的失误记录（用户不满的实据）

详细版在 REFLECTION 报告，此处列硬伤供快速核对：编译失败上线过（define-before-use
同类错误犯 3 次，最近一次 v19 用户直接看到红叹号）；粘贴事故 5 次把代码贴进图表
注释；警报与脚本版本绑定错位多次（其中一次导致研究推送泄漏给用户手机）；视觉
改动两次矫枉过正（研究标记淡化到不可见，被用户抓出）；07-23 警报零触发整整一天
才被发现（发现方式还是用户问"怎么没推送"）；微距离刮头皮信号曾被推送到用户手机
（止损 2.3 点级别）。**请评估：这些是流程缺陷（可修）还是能力边界（不可修）。**

## 4. 请你交付的东西（用户想要的审查产出）

1. **总判决**：这套东西（引擎 + 跟单试验 + 流程）值不值得继续？三选一并给理由：
   (a) 继续当前前向试验不动；(b) 大改（说明改什么）；(c) 停掉/重来（说明新起点）。
2. **策略层**：引擎信号逻辑与"只跟关键位拒绝"的取舍，站在日内交易实务角度是否
   成立；用户的直观不满（"该多的时候不多"——例如夜盘 07-24 凌晨双底反弹在
   预登记时段之外被跳过）应该用规则扩展回应还是维持纪律。
3. **统计层**：对抗审查的方法本身有没有错（它会不会把真实边缘也判成噪声）；
   淘汰制协议的参数是否合理。
4. **代码层**：Pine 架构（冻结引擎 + 纯核心跟单 + 双窗重演）是否过度工程化；
   契约测试钉的是不是要害。
5. **流程层**：§3 的失误模式下，应该给维护者（无论是谁）加什么硬性流程门。
6. 如果你只有 30 分钟：按 §1 顺序读 2、3、4、5 四份，然后直接给 §4.1 的总判决。

## 5. 硬约束（只此一条）

TradingView 侧现役实体：库脚本 **IDM v13 Forward**（云端 v25.0）、警报
**IDM v13.1 Forward**、以及用户另一套无关系统 DS Live Paper MTF Bridge V2 ×2。
你的建议若涉及改预登记规则，请注明"此改动将重置前向计数"即可——**是否重置由
用户决定，不由本简报的任何"铁律"决定**。
