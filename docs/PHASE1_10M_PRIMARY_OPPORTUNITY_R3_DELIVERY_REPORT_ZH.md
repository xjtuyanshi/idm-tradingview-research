# Phase 1 native 10m 主机会 correction R3 交付报告

日期：2026-08-01
源码基线：`c6f1017df1655d932f5d834737cdac66cc292988`
最终裁决：**PASS（严格限于本 clean package 的静态合同、Python oracle、package tests、337 根 native-10m replay 与 supplied 10m→3m replay）**

该 PASS 不代表 TradingView 已在线编译、remove/re-add、历史/实时一致、图面视觉验收、live market 验证或盈利 edge。上述外部项仍为 `NOT RUN`。

## 1. 输入身份

### 1.1 R2 clean baseline

```text
filename=idm-phase1-10m-primary-correction-r2-c6f1017-20260801-clean.zip
bytes=134616
SHA-256=f968c7f0466c2883c4482142c40dab0f8debe6579913cf049ea99895e73b20df
entries=32
CRC=PASS
path traversal=PASS
symlink=PASS
encryption=PASS
duplicate name=PASS
```

### 1.2 R3 correction submission

```text
filename=CHATGPT_PRO_PHASE1_10M_PRIMARY_R3_CORRECTION_SUBMISSION_2026-08-01.md
bytes=8198
SHA-256=1a1f70c57fb6f716c8d7b8697346b6c42403d80fce8973d9108239c3808ee42f
```

### 1.3 10m evidence

```text
filename=SPX500-10m-337-bars-2026-07-29-to-2026-07-31.csv
rows=337
bytes=162588
SHA-256=037ed7a18f93ae20ebca7cf755ff675086207f8f00110766975679d56245aa74
first=2026-07-29 06:00 ET
last=2026-07-31 14:00 ET
```

### 1.4 Supplied private 3m replay input

```text
rows=11815
bytes=5294757
SHA-256=d5c915b99f2f813ffcb0308059a7fb9ed1b7589a893e6b6ff9a3493fc8237436
bundled in clean R3 ZIP=NO
```

原 CSV 只由 caller path 传入 replay CLI。Clean source ZIP 仅包含派生事件日志和事件账本，不包含私有 3m 原始行情。

## 2. P1-A 关闭：entry permission 与 entered management 分离

### 2.1 R2 缺陷

R2 3m timing 在 `active_plan=None` 时无条件清除当前 plan。它没有区分：

```text
WAIT_PULLBACK / WAIT_TRIGGER：仍在等待 entry permission
ENTERED：已经入场，必须管理冻结 stop/target
```

因此真实路径中：

```text
10m MAIN_LONG confirmation = 2026-07-30 07:10 ET
3m adoption                = 07:21
3m first touch             = 07:24
frozen trigger             = 7366.9
LONG_ENTRY                 = 07:36, close=7368.3
10m ACTIVE_EXPIRED handoff = 09:30
frozen target              = 7450.2
actual target touch        = 16:00
```

R2 在 09:30 把已经 entered 的 plan 错误清为 `OPPORTUNITY_ENDED`，导致冻结保护/目标管理提前终止。

### 2.2 R3 修正

Python 与 generated Pine 都先对旧 owner 做 terminal 仲裁，再处理 permission/adoption：

```text
old invalidation
> old target reached
> ENTERED old-owner retention
> no entry permission
> new-plan adoption/replacement
> pullback/trigger
```

`ENTERED` 后保留：

```text
opportunity identity
10m direction
frozen invalidation
frozen target
frozen target source
frozen trigger audit value
```

以下输入不会替换或清除 entered old owner：

```text
primary ACTIVE_EXPIRED / EXPIRED
active_plan=None
different new 10m opportunity
later same-slow-epoch episodes
```

终止只允许：

```text
confirmed 3m close breaks frozen invalidation
3m high/low reaches frozen target
identity-matching primary INVALIDATED pulse
identity-matching primary TARGET_REACHED pulse
existing fail-closed 3m data/host reset
```

同 K invalidation 优先于 target。不同 opportunity 的 terminal pulse 不得误杀旧 owner。不同新 plan 不能在旧 entered plan 仍被管理时替换或反手。

### 2.3 P1-A 回归

新增并通过：

```text
entered -> primary expiry -> later target
entered -> primary expiry -> later confirmed-close invalidation
entered -> different new plan -> old plan remains owner
matching primary TARGET_REACHED pulse -> terminal without local 3m touch
matching primary INVALIDATED pulse -> terminal without local close break
unrelated primary pulse -> old owner retained
waiting, not entered -> primary expiry ends and suppresses permission
all sequences -> no duplicate entry marker
```

### 2.4 真实双周期结果

```text
2026-07-30 07:21  NEW_OPPORTUNITY
2026-07-30 07:24  PULLBACK_FROZEN, trigger=7366.9
2026-07-30 07:36  LONG_ENTRY, close=7368.3
2026-07-30 09:30  primary EXPIRED, timing remains ENTERED
                    reason=ENTERED_PLAN_MANAGEMENT
                    invalidation=7345.738437
                    target=7450.200000
2026-07-30 16:00  LONG_TARGET_REACHED
```

Known plan：

```text
opportunity_id=10M-TC-L-1785409800000
LONG_ENTRY count=1
premature OPPORTUNITY_ENDED between entry and target=0
```

16:00 后下一根 3m 才清理 terminal runtime；target marker 只发一次。

## 3. P1-B 关闭：partial ET day 不得发布 previous-day range

### 3.1 R2 缺陷

R2 在任何 ET date rollover 时直接发布当前累计 high/low。若引擎从中午启动，半天数据会在次日错误晋升为：

```text
PREVIOUS_COMPLETED_DAY_HIGH
PREVIOUS_COMPLETED_DAY_LOW
```

R2 的 337-bar replay 实际把从 2026-07-29 06:00 ET 才开始的部分日错误发布为：

```text
high=7454.2
low=7291.7
```

### 3.2 R3 完整日合同

上一 ET 日只有在全部满足时才可发布：

```text
first timestamp = ET 00:00
last timestamp  = ET 23:50
bar count       = 144
all deltas      = 600 seconds
rollover        = immediate next ET calendar date
```

以下任何情况使当日不合格：

```text
midday initialization
same-day 10m gap
backward time
invalid data
host/data reset
missing first or last expected bar
skipped ET date
```

Python 使用 `America/New_York` date 加一天判断紧邻日期；Pine 使用 ET day key，并允许相邻 ET midnight 的 UTC 差为 23/24/25 小时。严格 `144 + continuous 600s` 意味着 DST transition day 若不能满足该序列，会 fail closed，而不会发布部分日。

### 3.3 P1-B 回归

新增并通过：

```text
midday start -> no previous-day high/low
same-day missing 10m bar -> no publication
complete 144-bar ET day -> exact high/low only on next-day rollover
complete day followed by skipped date -> no publication
Python/Pine/generator contract parity
```

### 3.4 337-bar replay 变化

R2 固定输出：

```text
replay log SHA-256=af31733dada7b863c5eab69b2e7f5c788625b85e4ea170899a1a324a0f225124
event CSV SHA-256=996d4d0cbd817d365f72b00303af27d7f51ea7ad9bfee5da109650c369eaffe7
```

R3 固定输出：

```text
replay log SHA-256=0f5c5e23c096dc909e0cf3e7d4b6eb27e1941bc00044a5d3387a93863cf0cb3a
event CSV SHA-256=95e2dc47ed4da7590a50534931d2a1fcacb3a47bcec2000a613a350959cb35d0
```

比较：

```text
event rows: R2=62, R3=62
MAIN_LONG:   R2=1,  R3=1
MAIN_SHORT:  R2=1,  R3=1
event/state/reason counts: unchanged
changed common-field rows: 16
changed field: frozen_candidates only
```

R3 删除 2026-07-29 partial-day high/low 后，两个 MAIN 决策不变：

```text
2026-07-30 02:10 MAIN_SHORT
  target=7291.7
  source=CONFIRMED_PIVOT_10M
  space_R=2.455243

2026-07-30 07:10 MAIN_LONG
  target=7450.2
  source=CONFIRMED_PIVOT_10M
  space_R=5.195248
```

R2 07:10 candidate set 中多余的 partial-day high `7454.2` 被删除；nearest target 仍是已确认 pivot `7450.2`。

完整 144 根的 2026-07-30 ET 日在 2026-07-31 rollover 后仍可合法发布 previous-day high/low，证明本修正不是完全禁用该 source。

## 4. 保留的 R2 合同

R3 没有取消：

```text
TREND_CONTINUATION only
POSITION_REVERSAL disabled
confirmed-only native 10m
EMA5/12 = Ripster fast cloud
EMA21/48 = slow structure
causal touch-time named-level router
confirmed 2/2 pivots
nearest-first target selection
whole-bar candidate consumption
space_R >= 1.0 hard gate
same slow epoch terminal -> WAIT_CLEAR -> later full departure -> rearm
one WATCH per episode
WATCH never grants 3m entry
same-ID suppression across 3m reset
no same-bar adoption + entry
invalidation before target
```

VIX、SATy、ATR、divergence、overnight 与 AI scoring 本轮没有成为正式 producer、permission 或 veto。

## 5. 图面合同

### 5.1 Native 10m

```text
overlay=true
EMA5/12 width=2
cloud transparency=72
EMA21=gold, width=2
EMA48=blue, width=3
default markers=观多、观空、主多、主空 only
WATCH=small price-anchored triangle, light text
card=2 columns x 5 rows
visible rows=结论/行动、结构、保护、目标、原因/空间
visible internal IDs=none
```

### 5.2 3m timing/management

```text
EMA5/12 width=2
cloud transparency=72
previous-completed 10m cloud default=off
frozen stop/target lines default=on only while plan is owned
plan line width=1
default markers=多入、空入、一个失效、一个目标到达
card=2 columns x 5 rows
ENTERED action=已入场｜管理冻结保护/目标
```

未创建 dynamic labels、dynamic lines 或 boxes。图面静态合同由 generator/Pine tests 锁定，但 TradingView 实际视觉验收为 `NOT RUN`。

## 6. 源码工件

关键文件：

| Path | Bytes | SHA-256 |
|---|---:|---|
| `idm_phase1_10m_primary_opportunity_v3.pine` | 47323 | `4f345a5f4b92a791ba7f3282f26b32a0014d0e1264bf9e84dc72e4838768807b` |
| `idm_phase1_3m_opportunity_timing_v3.pine` | 67923 | `33127269ef841633dc9f82bf2d611369d753bc4d7ba4207d52fa437796c5f72b` |
| `research/phase1_10m_primary_opportunity_oracle.py` | 68460 | `341a80e72af1c1ea4c2df48ab3f03576ddf0aeb8cdd8d35b6b1ee779f93dd91c` |
| `research/generate_phase1_10m_primary_pine_r3.py` | 83449 | `7c9d0e4e8c788e9538aa93828eecc7d391cb4e0b143fd7fc5f791f35bc31582d` |
| `research/replay_phase1_10m_primary_opportunity_r3.py` | 14806 | `2b15e74561c8a106727941139a175c48554a7093622dd76090fa3c98ccbf159e` |
| `research/replay_phase1_10m_to_3m_r3.py` | 20265 | `1b011575f789da5b6bf09511c28ff56c5459e9526fcb62a456ac4643455b30ea` |
| `docs/PHASE1_10M_PRIMARY_OPPORTUNITY_SPEC_ZH.md` | 16940 | `74522eb425fb05c6b406c8522752feb84c0c86694e9807789f9c9c1840e6ebbe` |

两份 Pine 的 native-10m canonical block 完全一致：

```text
SHA-256=c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2
```

生成后的 Pine 不是手工分叉版本；generator `--check` 验证二者与模板一致。

完整 payload bytes/SHA-256 在 `FILE_INVENTORY.tsv`；标准相对路径 manifest 在 `MANIFEST.sha256`。外层最终 ZIP 的 bytes/SHA-256 在最终交付消息中报告，因为 ZIP 无法在自身 payload 内稳定自哈希。

## 7. Tests

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
python3 -m pytest -q -p no:cacheprovider research/tests
```

结果：

```text
86 passed in 2.30s
exit_code=0
```

覆盖类别：

```text
positive
negative
duplicate
causality
space
same-slow-epoch rearm
R3 split lifetime
identity-bound terminal pulse
strict completed ET day
Python/Pine/generator contract parity
native replay
caller-path dual replay
visual marker/card budget
forbidden alerts/orders/dynamic objects/advisory producers
```

## 8. Replay evidence

### 8.1 Native 337-bar replay

```text
events:
CONTEXT_RESET=10
DONT_CHASE=7
EXPIRED=10
INVALIDATED=1
MAIN_LONG=1
MAIN_SHORT=1
NONE=275
SPACE_UNKNOWN=6
WATCH_LONG=17
WATCH_SHORT=9
```

固定输出：

```text
docs/test_logs/phase1_10m_primary_r3_337_bar_replay.log
  SHA-256=0f5c5e23c096dc909e0cf3e7d4b6eb27e1941bc00044a5d3387a93863cf0cb3a

research/reports/phase1_10m_primary_r3_337_bar_events.csv
  SHA-256=95e2dc47ed4da7590a50534931d2a1fcacb3a47bcec2000a613a350959cb35d0
```

两次独立输出 byte-for-byte identical。

### 8.2 Real 10m→3m replay

```text
10m rows=337
supplied 3m rows=11815
overlap processed 3m rows=1121
derived event-ledger rows=80
```

Timing events：

```text
LONG_ENTRY=1
LONG_TARGET_REACHED=1
SHORT_ENTRY=1
SHORT_INVALIDATED=1
NONE=1117
```

Timing states：

```text
ENTERED=178
LOCKED=5
WAIT_10M=930
WAIT_PULLBACK=2
WAIT_TRIGGER=6
```

固定输出：

```text
docs/test_logs/phase1_10m_to_3m_r3_real_replay.log
  SHA-256=3aa681b7268dc616b1bb4d8f67068de5549e229279f771497b641000cf5b4145

research/reports/phase1_10m_to_3m_r3_real_events.csv
  SHA-256=0ae38e36630cfd9f3eba3dd0f8c56e86b0c19f0fd74f016b1ba503cebbf476de
```

两次独立输出 byte-for-byte identical。CLI 的四个输入/输出路径均由 caller 提供；不会覆盖输入 CSV，也不复制原始 private 3m 行到 release。

## 9. Generator 与 compileall

Generator：

```bash
PYTHONDONTWRITEBYTECODE=1 \
python3 research/generate_phase1_10m_primary_pine_r3.py --check
```

```text
exit_code=0
canonical SHA-256=c76aa9f2c27a2a8f59db4f9740dacf733793cf987d1eca465a8a2af99f1743a2
```

Compileall：

```bash
PYTHONPYCACHEPREFIX=<external> \
python3 -m compileall -q research
```

```text
exit_code=0
source-tree cache dirs=0
stdout=<empty>
stderr=<empty>
```

## 10. Source/package safety scan

最终 clean root 与最终 ZIP 验证必须覆盖：

```text
no path traversal
no absolute archive path
no duplicate entry
no symlink
no encrypted member
CRC PASS
no .git/.pytest_cache/__pycache__/pyc in source tree
no private 3m market CSV
no local absolute filesystem route
no credential/private-key pattern
no runtime alertcondition/alert/strategy/order/dynamic label/line/box
```

Staged clean root 扫描结果：`overall=PASS`。最终 ZIP 仍须在新鲜解压目录重复相同检查。

详细结果记录于：

```text
docs/test_logs/phase1_10m_primary_r3_source_scan.log
```

## 11. NOT RUN

```text
TradingView Pine v6 online compile
TradingView remove/re-add
historical vs realtime request.security alignment
pan/zoom/Replay/Data Window visual acceptance
10m + 3m + VIX actual layout capture
full dirty-repository gate
full repository scripts/validate.sh
old P7-R owner/state/frozen-artifact gates not present in this package
Ruff: tool not installed
Pyright: tool not installed
live market validation
alerts/orders/account changes/deployment
win-rate/P&L/profitability analysis
```

本报告不把静态 Pine tests 或 Python replay 冒充 TradingView 在线验收。

## 12. 剩余风险

1. Pine v6 语法与 runtime 行为仍必须在 TradingView 当前 compiler 中独立验证。
2. `request.security(..., lookahead_off)` completed-source transport 已由静态合同和 Python replay镜像，但历史/实时对位仍需 TradingView Replay 证据。
3. 严格 144 根完整日会在 DST transition day fail closed；这是当前明确合同，不是自动适配 23/25 小时日的 previous-day producer。
4. 3m entered owner 遇到 host/data gap、invalid 或 backward reset 时仍 fail closed 释放；这是 submission 要求保留的 existing reset 边界，实盘可用性需图上评估。
5. Clean correction package 不包含完整仓库旧依赖，不能声称运行 P7-R owner/state 或全仓门禁。
6. 337 根 10m 与其重叠 1121 根 3m 只证明这些路径可复现，不证明信号方向或盈利 edge。

## 13. 禁止动作确认

本轮没有执行：

```text
git commit
git push
pull request
deploy
TradingView alert
strategy/order/broker action
credential read
real account setting change
parameter optimization
profitability claim
```
