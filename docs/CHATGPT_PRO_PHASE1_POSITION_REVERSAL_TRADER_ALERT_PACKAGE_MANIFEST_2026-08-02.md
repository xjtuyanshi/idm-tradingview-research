# ChatGPT Pro package manifest：POSITION_REVERSAL Trader UI / alert

日期：2026-08-02
仓库：`github.com/xjtuyanshi/idm-tradingview-research`
分支：`codex/minimal-signal-rebuild`
ChatGPT Pro 对话：<https://chatgpt.com/c/6a6f8178-a308-83e8-bdc6-584f886deca0>

## 权威完整包

- 文件：`idm-position-reversal-trader-alert-db760ee-complete-20260802.zip`
- 源码 commit：`db760ee3511f660e6878ffc95d2aabb0d73296ba`
- 文件数：22
- 解压后总字节：403,475
- ZIP 字节：99,576
- SHA-256：`96e90c3d2297af6cfc8a52c6a97c8de3f4bf0e343a75ad329867c3959af07c53`
- 生成方式：对上述 commit 的明确 allowlist 使用 `git archive --format=zip`；未使用 `git add .`，未包含未列入 allowlist 的工作树文件。
- 密钥扫描：PASS。扫描范围为包内 allowlist；检查 private-key header、OpenAI/GitHub/AWS/Slack 常见 token 形态。扫描只输出可疑文件名，不输出匹配内容；本包没有候选文件。

完整包补入两份只读 R3.2 presentation source：

- `idm_phase1_10m_primary_opportunity_v3.pine`
- `idm_phase1_3m_opportunity_timing_v3.pine`

它们只用于 `test_current_r32_presentation_sources_are_byte_identical`，禁止由 POSITION_REVERSAL 任务修改。

## 首次提交给 Pro 的非权威包

- 文件：`idm-position-reversal-trader-alert-4b8aa10-20260802.zip`
- 当时记录的 commit：`4b8aa100bd4922963e9d5b318c1e8f427e37c547`
- ZIP 字节：81,542
- SHA-256：`7cd41b0e3cbb44ca3b8d0f7b828875a5ca127bca672bad732642ac3eb92e554d`
- 密钥扫描：PASS

该包没有包含上述两份 R3.2 presentation source。因此 Pro 在隔离包中复现为 `103 passed, 1 skipped`；skip 是 package completeness 问题，不是 position detector 测试失败。仓库/权威完整包中的相同专项命令为 `104 passed`。

首次包只保留为对话输入审计证据，后续隔离复验和交付哈希一律以权威完整包或 commit `db760ee` 为基线。

## 明确排除

- `.git`
- `.env` 与任何凭据文件
- `node_modules`、`.venv`
- build/cache/test cache
- 数据库、运行状态、浏览器状态、Cookie
- unrelated companion app 与历史 handoff 大包
- 私有 TradingView CSV/浏览器导出

## 外部传输边界

用户明确授权把本次任务所需的已扫描源码包发送给已登录的 ChatGPT Pro。未向 GitHub push，未创建 PR，未部署，未发送 webhook，未提供 API key、Cookie、登录凭据或真实用户数据。
