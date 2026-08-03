# Fable 5 独立审查任务书 — IDM R7 GitHub + TradingView 现状

日期：2026-08-03

状态：**公开审查候选；已装入 TradingView；未创建 Alerts；未证明交易优势**

这份任务书替换本文件的旧版本。旧版本写着“尚未装入 TradingView”，现在已经不再准确。

## 1. 请先给结论，不要直接继续堆功能

请站在一个盘中交易者的角度，独立判断当前系统是否真的有用，而不是只检查代码是否复杂、测试是否多。

你首先要回答：

1. 当前已部署版本在没有正式计划时，是否仍能清楚回答“现在是什么状态、下一步等什么、什么情况不能追”？
2. 当前版本是否有现实路径在当天形成完整的 10m 计划，并传递给 3m 产生可执行提醒？
3. 当前架构是否为了内部协议正确性牺牲了交易者可理解性？
4. 哪一个最小节点完成后，才值得创建 TradingView Alerts？

在给出审查结论前，请不要重写系统、创建/删除 Alerts、覆盖 TradingView 脚本或修改用户的主布局。

## 2. GitHub 权威信息

公开仓库：

- Repo: <https://github.com/xjtuyanshi/idm-tradingview-research>
- Visibility: `PUBLIC`
- Default branch: `main`
- 本轮审查分支: `codex/fable5-global-owner-review`
- 分支 URL: <https://github.com/xjtuyanshi/idm-tradingview-research/tree/codex/fable5-global-owner-review>
- 当前代码基线 commit: `d5b58835afd79d4bb045b715f68562eee8339e3b`
- Commit URL: <https://github.com/xjtuyanshi/idm-tradingview-research/commit/d5b58835afd79d4bb045b715f68562eee8339e3b>
- 与 `origin/main` 的 merge-base: `c6f1017df1655d932f5d834737cdac66cc292988`
- 审查分支比 `main` 多 13 个 commits；branch diff 为 60 files / 30,163 insertions。
- 当前没有 Pull Request；不要误以为它已进入 `main`。
- 本文件后续可能由一个纯文档 commit 更新；交易代码权威基线仍是上面的 `d5b588...`。

当前 GitHub Actions：**FAIL**

- Run: <https://github.com/xjtuyanshi/idm-tradingview-research/actions/runs/30802528966>
- Job: <https://github.com/xjtuyanshi/idm-tradingview-research/actions/runs/30802528966/job/91650213008>
- Result: `411 passed, 15 skipped, 1 failed`
- 唯一失败：`test_public_text_has_no_local_or_private_conversation_routes`
- 原因：15 份旧文档仍含本机绝对路径；这是公开发布卫生缺陷，不是交易规则通过。
- 15 项 skip 是未公开的 TradingView/Capital.com fixtures；不能计为通过，也不能据此声称 30/90 天有效。

本次纯文档修订后的隔离本地复跑为 `415 passed, 11 skipped, 1 failed`；唯一 failure 仍是同一 15-file public-text gate。本机具备部分 GitHub runner 不含的外部 fixture，因此本地与 CI 的 skip 数不同，不能互相替代。

注意：仓库里 `docs/STATUS.md`、`docs/TODO_AND_LIMITS.md`、`docs/TRADINGVIEW_SETUP_ZH.md` 等旧文档仍描述 v11/v13/v15 历史系统，不能当作 R7 当前状态。当前审查入口应以本文件和下面列出的 Phase 1 文档为准。

## 3. 当前应读的文件

主实现：

- [`idm_phase1_3m_global_owner_v1.pine`](../idm_phase1_3m_global_owner_v1.pine)
- [`idm_phase1_10m_primary_opportunity_v3.pine`](../idm_phase1_10m_primary_opportunity_v3.pine)
- [`idm_phase1_10m_position_reversal_v1.pine`](../idm_phase1_10m_position_reversal_v1.pine)
- [`research/phase1_3m_global_owner_oracle.py`](../research/phase1_3m_global_owner_oracle.py)

合同与验收：

- [`docs/CODEX_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_FREEZE_2026-08-02.md`](CODEX_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_FREEZE_2026-08-02.md)
- [`docs/CHATGPT_PRO_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_REPORT_2026-08-02.md`](CHATGPT_PRO_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_REPORT_2026-08-02.md)
- [`docs/TRADER_UTILITY_REVIEW_2026-08-02.md`](TRADER_UTILITY_REVIEW_2026-08-02.md)
- [`docs/INDEPENDENT_TRADER_REVIEW_2026-08-02.md`](INDEPENDENT_TRADER_REVIEW_2026-08-02.md)
- [`docs/CODEX_PHASE1_10M_PRIMARY_R3_INDEPENDENT_ACCEPTANCE_2026-08-01.md`](CODEX_PHASE1_10M_PRIMARY_R3_INDEPENDENT_ACCEPTANCE_2026-08-01.md)
- [`docs/CODEX_PHASE1_10M_POSITION_REVERSAL_V14_ACCEPTANCE_2026-08-02.md`](CODEX_PHASE1_10M_POSITION_REVERSAL_V14_ACCEPTANCE_2026-08-02.md)

Pine 身份：

```text
5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421  idm_phase1_10m_position_reversal_v1.pine
aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2  idm_phase1_10m_primary_opportunity_v3.pine
f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e  idm_phase1_3m_opportunity_timing_v3.pine
6b5ff2adbbee10dd1f53554bf9ca8d917debd9bcf7c9e8e0b6efbcbef11bf6c8  idm_phase1_3m_global_owner_v1.pine
```

Global Owner Pine 当前为 142,998 bytes、2,257 行。静态表面为 1 个 `request.security`、2 个 `plotshape`、4 个 `alertcondition`，无 `label.new`、`line.new`、`box.new`。

## 4. TradingView 当前真实部署

Fable 已有用户的 TradingView access，请直接检查真实图，而不是只看 GitHub。

- Layout URL: <https://www.tradingview.com/chart/ONCgqrJ3/>
- Layout: `IDM R1｜3m执行·10m结构`
- 左侧：`CAPITALCOM:SPX500` 10m
- 右上：`CAPITALCOM:SPX500` 3m
- 右下：`TVC:VIX` 10m
- 显示时区：New York / UTC-4
- 新保存脚本名：`IDM Phase 1｜3m 全局计划｜Fable审查 R7`
- Pine 内部标题：`IDM Phase 1｜3m 全局计划 owner v1`
- TradingView 已在线 `Compiled` 并 `Added to chart`
- 布局已保存，桌面端显示 `All changes saved`
- 旧 `IDM Phase 1｜3m 入场管理 v3.2` 已隐藏
- 旧 `IDM Phase 1｜10m 位置反转 v1.4` 已隐藏，因为它仍显示已过时且自相矛盾的 7499 卡片
- 旧脚本没有被删除，便于审计对比
- 当前没有创建四个 entry-only Alert 实例

如果要做实验，请复制布局；不要改用户正在看的主布局。检查脚本时先核对名称、行数和输入设置，避免把旧 v11/v15/R3.2 当成 R7。

## 5. 2026-08-03 约 10:05 ET 的真实屏幕状态

10m 卡片：

```text
现在做  等待 10m 计划
原因    已离云｜等首次回踩
触发    —
失效    —
目标    —
```

3m 卡片：

```text
现在做  等待
来源    —
为什么  等待 10m 可用计划
保护    —
目标    —｜剩余 —
```

这些空值是当前代码的故意 fail-closed 行为，不是渲染丢失：只有正式 10m 计划存在时才冻结触发、保护和目标。当前 10m 已经离开 5/12 云，但还没出现“后续首次回踩 → 后续确认收回 → 空间至少 1R”的完整计划，所以 3m 没有 owner。

请分别判断两件事，不要混为一谈：

1. **交易正确性**：没有计划时不伪造止损和目标是否正确？
2. **产品可用性**：只显示一排 `—`，是否足以当作盘中指北针？

## 6. 首先必须解决的问题

### P0-A：确认当前部署是否真的能形成用户要求的两类实时机会

当前 Global Owner 名义上包含：

1. `TREND_CONTINUATION`：10m 方向/位置/空间，3m 择时；
2. `POSITION_REVERSAL`：在事先已知的支撑/阻力或 SATy ATR level 反应后确认，不是破位反转。

但当前刚加入 TradingView 的 R7 使用默认 inputs：

- `atrEnabled = false`
- `l1Enabled` 至 `l4Enabled = false`
- 默认 source/level validity 截止 2026-07-31

因此当前部署的 `POSITION_REVERSAL` lane 实际上不可用；它不会产生用户最关心的 ATR/关键位反转计划。趋势 lane 仍可使用内部已确认 10m pivot 作为目标，但整个“两类机会”产品目标尚未完成。

请先沿当前日期的真实运行链证明：

```text
当前输入/来源
-> previous-completed 10m payload
-> trend/reversal producer outcome
-> PlanEnvelope
-> 3m owner
-> marker/card/alertcondition
```

必须明确指出哪一步会产生值、哪一步必然为空，以及为什么。不要只说“逻辑上支持”。

请给出最小且诚实的 source-of-truth 方案：

- 每日人工发布 ATR/关键位，带 source time、known time 和 hard expiry；或
- 一个外部 companion service 更新已验证位置；或
- 如果 R7 MVP 暂时只保留趋势 lane，就必须在名称、卡片和验收范围中明确写出，不得继续声称两类机会都已上线。

禁止静默沿用过期位置，禁止把 7499 之类旧输入继续当作当前阻力。

### P0-B：把“无计划”变成有用但不伪造的等待状态

在不捏造 stop/target 的前提下，当前卡片至少应回答：

- 10m 慢方向和 5/12 快云方向；
- 当前价格是在云上、触云、收回还是跌破；
- 下一件可操作事件是什么，例如“勿追；等首次回踩 5/12 后收回”；
- 哪个条件会取消这一观察；
- 为什么当前没有 plan。

请判断这应该是一个精简五行卡，还是拆成“市场状态”和“正式计划”两层。不要重新加入一墙历史 labels，也不要把观察态包装成买卖信号。

### P1：封闭已确认的 Oracle/Host mutation 缺陷

当前独立对抗审查确认：

1. `GlobalOwnerHost.manager` 返回完整 mutable `OwnerManager`，host-bound 后仍能被调用者绕过 canonical transaction 直接 `ingest(...)`；
2. host 构造失败不原子，fresh manager 可能被绑定到 orphan authority；
3. 无效 payload type 在抛 `TypeError` 前已经 staged 并修改 audit state。

请给出最小修复，优先 immutable audit view / prevalidation / atomic bind；不要再叠一层复杂 capability architecture。修复后必须加入针对真实 exploit 的回归测试。

### P1：修复公开分支的可复现性与文档身份

- 处理 15 个本机绝对路径，使 GitHub Actions 真正全绿；
- 建立一个当前 `README/STATUS` 入口，明确 main、review branch、TradingView deployed candidate 的关系；
- 将 v11/v13/v15 文档标成 historical，防止 reviewer 和用户继续混淆版本；
- skipped private fixtures 继续明确报告，不能把 skip 当 pass。

## 7. Trader review：必须避免后视镜

请使用 TradingView 的 10m + 3m 联动视图和 Bar Replay，按时间推进，不隐藏失败案例。

目标样本：最近 30 个 ET 交易日；如果当前脚本或数据合同不允许，请明确停在实际可审计的天数，并把“为什么不能做 30 天”列为产品缺陷，不能用旧 v15 或不同脚本的历史事件代替。

每一个潜在机会记录：

```text
日期/时间（ET）
当时已知的 10m 方向、5/12 状态和关键位
当时是否存在有效且未过期的位置来源
系统当时显示了什么
系统是否给出预警、计划、3m 入场或拒绝
触发、保护、最近目标、entry-time R
后续 MFE/MAE（SPX 点数）
分类：有用 / 太晚 / 错边 / 追价 / 漏掉 / 合理拒绝 / 数据不可用
一个真人 trader 当时是否看得懂并能采取行动
```

必须专门找：

- 沿 5/12 cloud 上行或下行的趋势延续；
- 第一次回踩 cloud 后收回；
- cloud 变窄再翻色；
- 到 ATR/前高/前低/MTF cloud 后有反应的反转；
- 同样到位但没有反应、直接穿透的反例；
- 3m 背离或 VIX 位置能否作为预警证据，但不得先偷偷加入最终 entry gate。

评审不是要证明“看起来有用”，而是要区分：提前可知、确认后可知和事后才看得出来。

## 8. Fable 必须交付的内容

请提交一份结构化审查结果：

1. `ACCEPT / REVISE / REJECT` 总结，分别评价交易逻辑、实时数据合同、TradingView UX、代码架构和验证证据；
2. P0/P1/P2 issue 列表，包含具体文件、函数/行号、复现步骤和影响；
3. 对当前空白卡片的明确裁决：哪些 `—` 必须保留，哪些应改成有意义的“下一步”；
4. 当前 R7 能否在 2026-08-03 的真实配置下产生 trend plan、reversal plan 和 3m entry 的逐步证明；
5. 最小修复方案，明确保留什么、删除什么、绝对不要再加什么；
6. 30 天因果 trader review 结果，或无法完成的精确数据阻塞；
7. 下一节点的可验收标准与 stop condition；
8. 在通过前是否允许创建四个 TradingView Alerts 的明确结论。

如果建议改代码，请先给最小 patch plan，不要直接大重写。任何 TradingView 修改都要先在复制布局中完成，并提供前后截图与实际 online compile/reload/pan/zoom/Replay 证据。

## 9. 当前边界

- 已确认：R7 Pine 在线编译、加入 3m 图、布局保存；用户可看到卡片。
- 未确认：remove/re-add 后的完整 parity、Replay 全链路、pan/zoom 全交互、真实 Alert delivery、手机通知。
- 未证明：30/90 天 edge、胜率、P&L、期权收益、真实 fill、滑点后结果。
- 不允许：订单、broker、webhook、真实用户数据、部署、合并到 `main`。
- 目前不要创建 Alerts；四个 `alertcondition` 只是源码能力，不是已经配置的提醒。

## 10. 给 Fable 的一句话任务

> 请先证明当前公开 R7 分支和 TradingView 实际部署是否组成一个能在今天生成完整 10m→3m 决策链的产品；然后从无后视镜 trader 视角审查空白等待状态、漏掉的 cloud/ATR 机会和架构缺陷，给出一个最小、可验收、不会继续堆复杂度的下一节点。
