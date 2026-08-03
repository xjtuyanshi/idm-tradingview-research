# Phase 1 — 3m Global Owner R7 实现与验收映射

## 1. 工件身份与范围

- Package baseline：`0fe6faa529832cc36fc8ec377ce2620e8ed9b388`
- 权威输入 ZIP：`idm-phase1-3m-global-owner-implementation-0fe6faa-20260802.zip`
- 输入大小：`201876 bytes`
- 输入 SHA-256：`0ebb7fd4a4e3354c76a48f10d358eea749e16a5c9f02cd4e60f6e8a72b8d7258`
- 输入条目：`41`
- 本轮：R7，完整 baseline-relative 12 文件替换候选
- R6→R7 只修改：Oracle、transport tests、本报告，共 3 个 repo 文件

本轮没有修改任何 Pine、Pine generator、交易规则、lane timing、UI、marker 或 alert。

## 2. R7 唯一 P1

R6 已经封闭 `GlobalOwnerHost.manager` 与 `GlobalOwnerHost.transport` 的公开重绑定，但 `SharedCompletedTenMinuteTransport.last_observed_source_time` 和 `last_consumed_source_time` 仍是公开可写实例字段。调用者可以通过普通属性赋值回拨两个审计时钟，把下一条严格连续的 10m payload 伪造成 raw gap，破坏“公开调用者只能读取 audit state”的合同。

R7 只修复该公开写入口，不改变 transport 的真实连续性、duplicate、raw gap/backward/reset、cutoff 或 recovery 语义。

## 3. 最小实现

### 3.1 私有存储与只读属性

`SharedCompletedTenMinuteTransport` 改为内部保存：

```text
_last_observed_source_time
_last_consumed_source_time
```

对外继续暴露同名只读 properties：

```text
last_observed_source_time
last_consumed_source_time
```

两项 property 都没有 setter。普通公开赋值会立即抛出 `AttributeError`，发生在 pending、observed、consumed、rejected ledger、cutoff、manager clock 或 host staged raw snapshot 的任何 mutation 之前。

内部 host-authorized `_consume_core()` 只更新私有存储，因此合法 delivery、duplicate detection、raw continuity audit 与 reset/recovery 行为保持不变。

### 3.2 其余公开只读 audit surface

R7 同步锁定并回归以下已声称只读的公开属性：

Transport：

```text
pending_payload
last_observed_source_time
last_consumed_source_time
rejected_source_times
reset_visible_at_cutoff_ms
```

Host：

```text
manager
transport
staged_raw_snapshot
raw_snapshot_dirty
```

普通公开赋值均须立即失败，不得成为状态修改入口。Private-name 或 `object.__setattr__` tamper 不属于本轮 public threat model。

## 4. 精确 exploit 回归

完整复现序列：

1. 09:42：source=09:30、visible=09:40，正常 `DELIVERED`；
2. 09:45、09:48：连续有效 3m bar；
3. 尝试公开写入两个 audit clocks 为 09:20；
4. 两次赋值均立即失败，transport audit tuple、manager clock、staged raw snapshot 完全不变；
5. 09:51：source=09:40、visible=09:50，结果仍为 `DELIVERED / DELIVERED`，不会伪造 `RAW_10M_GAP`。

另外覆盖：

- 未播种 transport 的公开赋值；
- 已播种 transport 的公开赋值；
- 读取另一 host 的 audit clock 后赋给当前 transport；
- `pending_payload`、`rejected_source_times`、`reset_visible_at_cutoff_ms` 的公开赋值；
- host `staged_raw_snapshot`、`raw_snapshot_dirty` 的公开赋值；
- 每条失败路径均逐项断言 transport audit tuple、manager clock 和 staged raw snapshot 不变。

## 5. R6 合同保持

R7 保留 R6 的全部边界：

- `GlobalOwnerHost.process_bar()` 是唯一正常 mutation path；
- host-bound、manager-bound、transport-bound、timestamp-bound、single-use permit；
- exact outcome receipt-equivalent binding；
- `manager` / `transport` 构造后只读且 identity prevalidation 在 staging 前；
- public transport `offer` / `consume_for` / `record_reset_boundary` pre-mutation fail closed；
- forged public `ConsumerBarDecision` 无 transport authority；
- cross-host、wrong timestamp、permit reuse、ineligible host bar均不能修改 audit state；
- 09:54→10:00 gap→10:12 gap→10:15 raw reset→strict recovery；
- 连续有效 3m bar上的 raw reset优先于 stop、target、producer terminal、timing、entry 和 adoption；
- reset cutoff、explicit rejected ledger、last-observed/last-consumed 分离；
- no replacement/no queue、stop-first、strict 180000ms、expiry equality；
- 2 个 marker、4 个 entry-only alerts、无 label/line/box。

## 6. 修改文件

R6→R7 只修改：

```text
docs/CHATGPT_PRO_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_REPORT_2026-08-02.md
research/phase1_3m_global_owner_oracle.py
research/tests/test_phase1_3m_global_owner_transport.py
```

完整 R7 baseline-relative 12 文件范围：

```text
docs/CHATGPT_PRO_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_REPORT_2026-08-02.md
idm_phase1_3m_global_owner_v1.pine
research/generate_phase1_10m_position_reversal_pine_v1.py
research/generate_phase1_3m_global_owner_pine_v1.py
research/phase1_3m_global_owner_oracle.py
research/tests/fixture_phase1_10m_position_reversal.py
research/tests/fixture_phase1_3m_global_owner.py
research/tests/test_phase1_10m_position_reversal_positive.py
research/tests/test_phase1_3m_global_owner_arbitration_lifecycle.py
research/tests/test_phase1_3m_global_owner_contract.py
research/tests/test_phase1_3m_global_owner_timing.py
research/tests/test_phase1_3m_global_owner_transport.py
```

除上述 3 文件外，另外 9 个 repo 文件与 R6 byte-identical。

## 7. 测试与命令结果

环境：Python `3.13.5`；pytest `9.0.2`；隔离 HOME；`PYTHONDONTWRITEBYTECODE=1`。完整 command、stdout、stderr、UTC start/end 与 exit code 随 ZIP 保存在 `DELIVERY/test-logs/`。

### Focused transport

```text
python -m pytest -q research/tests/test_phase1_3m_global_owner_transport.py
44 passed
exit code 0
```

### Global owner

```text
python -m pytest -q research/tests/test_phase1_3m_global_owner_*.py
111 passed
exit code 0
```

### Reversal

```text
python -m pytest -q research/tests/test_phase1_10m_position_reversal_*.py
132 passed
exit code 0
```

### Trend

```text
python -m pytest -q -rs research/tests/test_phase1_10m_primary_opportunity_*.py
81 passed, 4 skipped
exit code 0
```

四项 skip 仍是包外 private 337-bar fixture。

### Reviewer-focused

R6 reviewer set 加入本轮四项 public read-only regressions：

```text
46 passed
exit code 0
```

### Package collectable

```text
python -m pytest -q -rs
324 passed, 4 skipped
exit code 0
```

### Generators 与 compileall

```text
position-reversal generator --check：PASS，exit code 0
trend generator --check：PASS，exit code 0
global-owner generator --check：PASS，exit code 0
python -m compileall -q research：PASS，exit code 0
```

## 8. Pine 与 generator 冻结

Global Pine：

```text
idm_phase1_3m_global_owner_v1.pine
bytes=142998
SHA-256=6b5ff2adbbee10dd1f53554bf9ca8d917debd9bcf7c9e8e0b6efbcbef11bf6c8
```

三份 frozen Pine：

```text
idm_phase1_10m_position_reversal_v1.pine
5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421

idm_phase1_10m_primary_opportunity_v3.pine
aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2

idm_phase1_3m_opportunity_timing_v3.pine
f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e
```

所有 Pine 与 Pine generator 均与 R6 byte-identical。

## 9. Full-repository 边界

权威输入是 41-entry package subset，不是 exact full repository；当前运行环境没有可验证的 exact full worktree，因此本轮不虚构 full-repository rerun，也不声称全仓全绿。

最近由 Codex 提供的独立完整候选结果保留为：

```text
399 passed, 11 skipped, 1 failed
```

唯一 failure 是 baseline 已存在的 public-release 本地路由门禁，涉及同一 15 份旧文档。R7 changed paths 相对 baseline 新增违规文件必须为 `0`。

## 10. Package / diff 验收合同

R7 打包必须验证：

- baseline identity、ZIP comment 与 CRC；
- baseline-relative changed paths 精确为 12；
- R6→R7 delta 精确为 3，另外 9 文件 byte-identical；
- `git diff --check`；
- `git apply --check`、apply 后 12/12 byte parity；
- `patch --dry-run -p1`、apply 后 12/12 byte parity；
- fresh applied tree 复跑 focused/global/reviewer/package 与 generators/compileall；
- ZIP unique names、无 encryption/symlink/traversal；
- internal SHA256SUMS；
- embedded/external diff byte parity 与 embedded diff round-trip；
- changed-path 与 whole-package credential/local-route scan；
- candidate forbidden leak set 相对 baseline 差集为空。

## 11. 未执行或未声明

本轮未执行或声明：

- TradingView 云端 compile；
- remove/re-add、Replay、reload/live parity；
- live/phone alert 或 alert 实例配置；
- webhook、broker、订单、成交；
- 盈利能力、胜率或交易 edge；
- push、commit、PR 或 deploy。

R7 是供 Codex 独立验收的完整替换候选，不代表已合并或上线。
