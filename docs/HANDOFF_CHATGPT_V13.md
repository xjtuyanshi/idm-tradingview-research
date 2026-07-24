# IDM v13 交接/外审文档（写给下一位审查者，2026-07-24）

> 读者假定：你是一个强推理模型（ChatGPT Pro / 同级），第一次接触本仓库，
> 需要在**不破坏两条铁律**的前提下审查并提出改进。上一轮外审（2026-07-22）
> 的意见与处置记录在 `research/reports/IDM_V12_CHATGPT_REVIEW_2026-07-22.md`。

## 1. 你需要知道的最少上下文

- 标的：CAPITALCOM:SPX500（CFD，24h 报价，RTH 09:30–16:00 ET）。
- 主文件：`intraday_decision_map_v11_2_clear.pine`（Pine v6，~2450 行，
  VERSION_ID `13.1.0-declutter`，TV 云端 v25.0 编译通过）。
- 系统 = 冻结引擎（研究信号流）+ 预登记跟单模块（前向试验品）。
- 完整系统说明：`docs/SYSTEM_V13.md`；分段地图：`docs/ARCHITECTURE_V12.md`。
- 统计立场（必须先读）：`research/reports/IDM_V12_ADVERSARIAL_REVIEW_2026-07-22.md`
  ——样本内 +0.093R/笔 弱于噪声冠军（家族极值 p=0.87），费后点估计 ≈ −0.15R/笔，
  一切前向数据用于**淘汰或证实**，不用于讲故事。

## 2. 两条铁律（审查建议不得违反）

1. `f_v11_engine` 字节冻结：契约测试逐字比对。你可以批评它，但改它的建议
   请单独列为"需要用户明示解冻"类。
2. v13 跟单规则预登记冻结（规则清单见 SYSTEM_V13.md §2）：改规则=记分板清零。
   优化建议请区分【显示/工程类：可直接做】与【规则类：登记为 v14 提案，等当前
   批次走完】。

## 3. 如何复现数字

```bash
python -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest research/tests -q   # 期望 92 passed, 4 skipped
```
- 4 个 skip 依赖私有行情夹具（TradingView 导出 CSV，不入公共仓库）。要跑全量
  回放/跟单仿真（`research/exit_lab.py`、`exit_lab2.py`），向用户索要夹具目录。
- `exit_lab2.simulate_follower` 是跟单唯一 oracle（单循环返回 r/flat_i/full_stop），
  与 Pine 核心在 7 组配置逐位一致（合并版复核记录见 EXIT_LAB 报告 §7）。

## 4. 悬而未决的问题（按优先级，欢迎你先打这些）

1. **P0 推送零触发疑案**：07-23 图上有 2 笔真实跟单（标签+记分板俱在），但绑定
   v23 的警报全天零触发（面板无触发时间戳）。服务端实例与图表实例同码同参。
   已删旧重建（绑 v25）并加每日心跳自检。请给出你的差分诊断树：服务端实例
   为何可能不产生 alert() 而图表实例产生？（提示方向：alert 快照的输入集、
   calc_bars_count、服务端 session/时区、alert 创建时实例已被删除的边缘态。）
2. **P1 外部账本的可靠性**：TV `list_fires` 只回最近 2000 条，被用户另一系统的
   webhook 失败重试刷穿（每十几秒一条）。META 幂等行作为账本的抓取窗口因此
   不可靠。请评估：(a) 用 TV webhook 直接把【v12跟单】推到用户可控端点的
   最小方案；(b) 或每日日结推送内嵌当日全部 META 的方案。约束：不能改跟单规则。
3. **P1 多单精确回填**：07-23 跟多的入场/止损被图上标签遮挡未能读出（空单已核：
   E 7407.3 / S 7414.1）。给出从 TV 侧一次性补录的最短路径（提示：警报日志
   CSV 导出已被刷穿；图上 tooltip 需要 hover 命中）。
4. **P2 显示预算**：plot 类 50/64、线 24/30、标签环形缓冲 330/400。若你建议
   新增可视元素，请先说明挤掉谁。
5. **P2 统计流程**：淘汰制协议（60 笔批次/−10R/摩擦/runner 三闸）与 385 笔
   单次检验是否有你不同意的地方？如有，请给可预登记的替代方案，而非事后调整。

## 5. 修改礼仪（如果你产出代码补丁）

- 版本号必须 bump（`VERSION_ID`），契约测试同步更新钉子；新推送行为=新警报
  （删旧建新，核对条件下拉里的版本号）。
- Pine v6 注意：无 `dayofyear()`；函数先定义后使用（CE10271）；alert() 不进
  security 数据流（CE10057）；中文字符串占 UTF-8 三字节（云端另存 CRLF，
  SHA 验证前先 LF 归一化）。
- 显示默认值改动要写进 `test_ledger_driven_defaults`。
- 任何触碰 `f_pick_*` / `f_candidate_*` / `f_nearest_saty` / `f_setup_priority`
  的改动（冻结洞：不在字节区但改行为）必须附 replica 回归结果。

## 6. 当前前向账本（你接手时的起点）

| 日期 | 笔 | 毛R | 费后R | 备注 |
|---|---|---|---|---|
| 07-23 | 2（多止损、空止损） | −2.0 | −2.2 | VIX +19% 恐慌日；冷却闸门拦下 13:53 卖A ✓ |

- 判决点：60 笔或 −10R 先到者；期望节奏 ~2 笔/日（实验室 27 笔/14 日）。
- 心跳自检自 07-24 起每交易日 09:33 ET 前后一条；缺席=通道故障，请先修通道
  再谈策略。

## 7. 目录速查

```
intraday_decision_map_v11_2_clear.pine   # 唯一 Pine 真源（v13.1.0）
docs/SYSTEM_V13.md                       # 系统全览（先读）
docs/ARCHITECTURE_V12.md                 # 分段地图
docs/STATUS.md                           # 状态入口（指向本文）
research/tests/                          # 契约测试（92+4）
research/v11_pine_replica.py             # Python 复刻引擎
research/exit_lab.py / exit_lab2.py      # 出场实验室 / 跟单仿真 oracle
research/reports/                        # 全部研究与审查报告（含对抗审查）
```
