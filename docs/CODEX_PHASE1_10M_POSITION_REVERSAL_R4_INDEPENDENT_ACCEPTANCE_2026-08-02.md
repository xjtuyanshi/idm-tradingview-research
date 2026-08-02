# Codex Phase 1｜10m POSITION_REVERSAL R4 独立验收

日期：2026-08-02
仓库：`github.com/xjtuyanshi/idm-tradingview-research`
工作树：本地隔离工作树（绝对路径不随公共源码分发）
分支：`codex/minimal-signal-rebuild`
源码基线：`c6f1017df1655d932f5d834737cdac66cc292988`
ChatGPT Pro 对话：<https://chatgpt.com/c/6a6eecbc-77a8-83e8-8fc1-d435ba017d32>

## 裁决

**离线源码与合同：ACCEPT。TradingView 在线门禁：PENDING。**

R4 关闭了 R3 的两个身份合同 P1：

1. Python 使用 trim 后 identity、Pine 某些路径使用 raw identity，导致 duplicate、continuation 和 outward ID 不一致；
2. 自由 id/version 直接用 `|`、`@`、`#` 拼接，可构造不同来源但相同 effective fingerprint / opportunity ID。

R4 采用 fail-closed CID1 编码：

```text
长度 1..64
raw == trim(raw)
首尾为 ASCII 字母或数字
内部仅允许 ASCII [A-Za-z0-9._:-]
拒绝 | @ #、全部空白、非 ASCII 与首尾标点
identity = CID1:<source_id>@<source_version>
```

内部冒号是可接受的合同选择：`@` 是唯一 id/version 分隔符，`|` 是固定 material 分隔符，二者都不能进入 component；因此 `A:B@C` 与 `A@B:C` 仍是不同编码。

## 本步实际实现

本 lane 只处理“位置不破后反转”，不处理破位后的反抽：

- `支撑观察`：10m K 触及 prior-known 支撑，但尚未授权；
- `反弹确认`：10m 收盘重新站回支撑上方；只有冻结目标空间 `>= 1R` 才发布 READY；
- `阻力观察`：10m K 触及 prior-known 阻力，但尚未授权；
- `压回确认`：10m 收盘重新落回阻力下方；只有冻结目标空间 `>= 1R` 才发布 READY；
- `accepted break` 优先：支撑下方或阻力上方收盘视为位置失效，后续 reclaim 不倒填旧机会；
- 同向多位置同时触及、支撑/阻力冲突、来源过期或身份异常全部 NO_PERMISSION / fail closed；
- marker 只有四类价格锚定 `plotshape`，无 `label.new`、`line.new`、`box.new`；卡片默认关闭且固定右下五行。

本 lane 没有接入 3m、VIX、MACD/divergence、forming MTF cloud、alert、order 或 strategy。

## 交付与来源身份

### 初始 handoff

- 文件：`idm-phase1-10m-position-reversal-handoff-c6f1017-20260801.zip`
- bytes：`1,572,174`
- SHA-256：`458dc21e15167dffa8fadd475e3f0a3c29f59737f667aa087cc99cfe6d1d9b7d`

### Pro R4 clean ZIP

- 文件：`idm-phase1-10m-position-reversal-r4-identity-c6f1017-20260802-clean.zip`
- bytes：`56,964`
- SHA-256：`1e2d3f409f2896f30495fb1b8e2a8fef909bd30bfa8f7199c6889379bdaee829`
- entries：`11`
- CRC、relative path、普通文件 mode、无加密、无 symlink：PASS
- 高置信 credential/private-key/token scan：`0 findings`

关键文件：

| 文件 | SHA-256 |
|---|---|
| `idm_phase1_10m_position_reversal_v1.pine` | `c205aef662bf900c43dc6f2af3a9e100afda3f5425a12fe4e879194f6de1f06d` |
| `research/generate_phase1_10m_position_reversal_pine_v1.py` | `aabcf72baf2f637f7f4e92c688523ffdf5ef6b55a6b090bebc15f93f2055f9f9` |
| `research/phase1_10m_position_reversal_oracle.py` | `55f5909de0a99ed25508136e4c5c9051804686443770e7c61e73702cbba28207` |
| Pro identity tests | `09e297427a3cfb77c8f619d08ae895f4e727431a5753dde80a34bdbf8b8172b0` |
| Pro 原始报告 | `abb5919bbe63b693f5975bf30f4e4f042e31cf2553b2277ab03e491cb01879e2` |

生成产物 canonical block SHA-256：`52e29ddefc34d02e4f2ac3675329d6d78d062a795c8dcb8b0f45d8200e66805b`。

合成合同图（不是实际行情或回测）：

- 文件：`position-reversal-r4-synthetic-contract.png`
- bytes：`43,139`
- SHA-256：`95eb5b23a55b5ff9514be294441fac39f6b793f646f4d2b7e265378021f61558`
- 持久位置：外部 evidence 目录 `chatgpt-pro-position-reversal-20260801/visual/position-reversal-r4-synthetic-contract.png`

## 独立验收证据

| 门禁 | 结果 |
|---|---|
| R4 ZIP standalone 专项 | `98 passed, 1 skipped`；skip 仅因 clean ZIP 不含冻结 R3 Pine |
| Fresh handoff overlay 专项 | `99 passed` |
| Codex 额外 identity/Unicode/分隔符/恢复 reproducer | PASS |
| R4 落地后 POSITION_REVERSAL 专项 | `104 passed` |
| POSITION_REVERSAL + 冻结 10m/3m scoped | `183 passed, 7 skipped` |
| 仓库原样 `scripts/validate.sh` | `1063 passed, 130 skipped` |
| Generator byte parity | PASS；`44,257 bytes` |
| Python `compileall` | PASS |
| `git diff --check` | PASS |
| Pine 禁止项 | `plotshape=4`；无 request.security/label/line/box/alert/order/strategy |

130 个全仓 skip 均是既有外部/private evidence 门禁，没有计为通过；本轮没有把模拟测试描述成 TradingView 在线或真实 feed 验证。

R4 验收本身未改 10m/3m canonical engine。此验收之后的独立 trader-utility
UI 修订只改标题、默认 marker 可见性、文案与卡片；当前完整文件 hash 为：

| 文件 | SHA-256 |
|---|---|
| `idm_phase1_10m_primary_opportunity_v3.pine` | `ec2f8eee96960d8f95c6a2035181bfa0e319e498bdd12a988f2a9678bde138ba` |
| `idm_phase1_3m_opportunity_timing_v3.pine` | `f349baa860124a386396b173780567cc842a3591f894b99d97381d6726af6c8f` |

## Codex/Review Agent 增补门禁

Review Agent 对 R4 给出 `ACCEPT-WITH-GATES`。Codex 已将以下三项独立 reproducer 固化为正式测试：

1. enabled identity-invalid extra band 必须全局 DATA_RESET；disabled bad optional band 可以豁免且不得成为 producer；
2. READY 后当前 bar identity-invalid 必须清 active outward snapshot，但 Python immutable opportunity ledger 不得删除旧 payload；
3. WATCH 后 invalid reset，下一根连续且合法的 10m K 当根即可重新 eligible，不额外丢一根。

另补充冒号注入性测试，以及 Python runtime 从 `D` 漂移到 `" D "` 时保守返回 `ATR_IDENTITY_DRIFT` 的边界测试。

## 已知边界与文档勘误

- `source_kind` 与 `source_timeframe` 仍采用 trim-normalization；相同固定输入下 Python/Pine acceptance 与 outward material 一致。Python streaming runtime 对 raw timeframe 漂移会 fail closed；TradingView input 修改会全历史重算。这是明确的 runtime/reload 边界，不是跨 reload append-only ledger。
- Pro 报告中的合法 ATR 示例文字写成 `...@2026-07-31-v1`，实际测试使用的是 `...@v1`；代码与测试一致，报告原件保留不改以维持交付 SHA。
- 当前没有 TradingView 原生 10m 在线编译、输入配置、pan/zoom 锚定或 July 31 回放截图；macOS 仍锁屏。在线门禁完成前不能把本裁决升级为端到端 PASS。
- 没有真实 feed cross-check、三个月 walk-forward、实时前向或盈利 edge 证明。

## Git / 外部状态

所有修改仅在现有本地 dirty worktree。未 commit、未 push、未创建 PR、未 deploy、未创建 alert、未下单。
