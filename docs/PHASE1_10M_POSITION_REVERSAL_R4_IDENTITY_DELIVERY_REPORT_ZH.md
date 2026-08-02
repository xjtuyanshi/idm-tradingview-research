# Phase 1｜10m POSITION_REVERSAL R4 身份编码修正交付报告

日期：2026-08-02
基线身份：`c6f1017df1655d932f5d834737cdac66cc292988`
唯一源码输入：`idm-phase1-10m-position-reversal-r3-source-contract-c6f1017-20260802-clean.zip`
输入 identity：`50,996 bytes` / `d3d87d8737f84c8d8cbaa9336df3a596041e3e6f52aed106ac3e918bf49d4363`
本轮协议：`phase1-10m-position-reversal-1.3`

## 1. 裁决与范围

**本 R4 identity correction scope：PASS 候选。**

本轮只修改 POSITION_REVERSAL 10m lane 的 Python oracle、Pine generator、generated Pine、相关测试与本报告。R3 的 producer allowlist、absolute `valid_until`、previous-completed daily ATR provenance、effective material、accepted-break、target earlier-consumed、nearest-first、WAIT_CLEAR、恢复首根 eligible bar、同向多位置 no-permission、五行卡和四类 marker 语义均保留。

R3 clean ZIP 是唯一源码输入。原始 handoff ZIP 只作为 fresh-overlay 测试容器及冻结 R3 10m/3m 文件来源，没有从中取代码回填本 lane，也没有修改其中冻结文件。

未接入 3m、VIX、divergence、forming MTF、alert、order 或 strategy；未添加 marker、卡片行、consumer 或交易功能。

## 2. 两个 P1 的直接修正

### 2.1 不再 trim 后静默接受 identity

R4 采用 **fail closed、无 silent normalization** 的同一 Python/Pine grammar。每个 `source_id` 和 `source_version` 必须同时满足：

```text
1 <= length <= 64
raw == trim(raw)
首字符和末字符属于 ASCII [A-Za-z0-9]
全部字符属于 ASCII [A-Za-z0-9._:-]
```

因此以下内容均被拒绝：

```text
首尾或内部空白
非 ASCII 字符
|  @  #
以 . _ : - 开头或结尾
其他未列入有限字符集的字符
```

合法 identity 的唯一序列化为：

```text
CID1:<source_id>@<source_version>
```

由于 `@` 不允许出现在 component 中，且 component 本身必须通过同一 grammar，这一 outward identity 无歧义。空格 padded identity 不会在一个位置 trim、另一个位置保留 raw；它在 Python 与 Pine source surface 都直接 fail closed。

### 2.2 关闭 `|`、`@`、`#` 拼接碰撞

Band effective material 固定为：

```text
CID1|B|source_kind|CID1:<id>@<version>|role|
scaled(lower)|scaled(upper)|published|known|valid_until
```

ATR effective material 固定为：

```text
CID1|A|source_kind|CID1:<id>@<version>|scaled(value)|
published|known|valid_until|D|completed_open|completed_close
```

自由 identity component 在进入上述 fixed-arity material 之前已经拒绝 `| @ #` 与所有空白；kind/role/timeframe 又由固定 allowlist/枚举约束，数值和时间使用机械整数表示。因此不同的已接受字段序列不能再通过移动分隔符产生相同 material。

R3 与 R4 outward episode/opportunity identity 不能混用：协议升级为 `1.3`，所有合法 identity 与 effective material 均带 `CID1` 域标记，R4 ID 必然不同于 R3 的旧编码。

## 3. Canonical identity 的所有使用点

Python 与 Pine 统一复用同一规则，覆盖：

1. `source_id/source_version` validation；
2. band duplicate detection 与 Python runtime source registry；
3. ATR runtime registry；
4. band/target/ATR effective material；
5. active episode continuation 的 source/target/ATR identity 比较；
6. `episode_id`；
7. `opportunity_id`；
8. outward `source_id/source_version`、`target_source` 与 `atr_source`；
9. Pine 卡片中的当前位置和目标来源；
10. multi-touch effective material。

Pine 仍保留 raw input arrays 仅用于 validation；duplicate loop、episode/outward ID 和 target source 不再读取未经 canonical validation 的 raw identity。Python 在 episode 启动和 target freeze 时也只保存已验证的 canonical component。

## 4. Exact reproducer 结果

### `DUP` 与 padded `DUP`

```text
DUP + " DUP "
→ DATA_RESET / DISABLED / SOURCE_NOT_READY
→ episode_id=None
→ opportunity=None
```

R4 选择 reject，而不是把 padded value silent-normalize 成 duplicate。两个运行时都先因 non-canonical identity 禁用 source surface。

### Padded identity 两根 continuation bar

```text
bar 1 → DATA_RESET / DISABLED / SOURCE_NOT_READY / no ID
bar 2 → DATA_RESET / DISABLED / SOURCE_NOT_READY / no ID
```

不再出现 Python 首根 watch、续根 reset 或 Python/Pine active identity 漂移。

### Exact delimiter collision

以下 band/target 输入全部在 fingerprint/READY 之前拒绝：

```text
TARGET|X + Y
TARGET + X|Y
A@B + C
A + B@C
A#B + C
A + B#C
```

结果均为：

```text
DATA_RESET / DISABLED / SOURCE_NOT_READY / no ID / no opportunity
```

ATR 的 `| @ #` 与 padded identity 对称返回：

```text
DATA_RESET / DISABLED / ATR_NOT_READY / no ID / no opportunity
```

合法安全 identity 正例仍为：

```text
BOUNCE_CONFIRMED / READY
source      = CID1:SATY:Map_Level-1@v1.2
target      = CID1:SATY:Map_Target-2@v1.2
ATR context = CID1:SATY:ATR_Context-2026.07.31@2026-07-31-v1
```

## 5. Canonical identities

| 项目 | SHA-256 |
|---|---|
| Python canonical contract | `89a8657da6c1ae9323720e841a12d49fa8ba0dd89e3485f2b13265ae99999beb` |
| Generated Pine canonical block | `52e29ddefc34d02e4f2ac3675329d6d78d062a795c8dcb8b0f45d8200e66805b` |
| Generated Pine full source | `c205aef662bf900c43dc6f2af3a9e100afda3f5425a12fe4e879194f6de1f06d` |

## 6. 测试与门禁

### Exact reproducer

使用独立 Python 命令直接执行 `DUP`/padded continuation、band/target `| @ #`、ATR `| @ #` 和合法正例：`exit 0`。所有无效输入均 fail closed 且没有 episode/opportunity ID；合法正例仍 READY。

### Clean ZIP standalone 专项

```bash
python3 -m pytest research/tests/test_phase1_10m_position_reversal_*.py -q -rs
```

最终 clean ZIP 解压目录实跑为 `exit 0`，`98 passed, 1 skipped, 0 failed`。唯一 skip 是 clean ZIP 有意不携带两份冻结 R3 Pine，未计为 pass。

### Fresh handoff overlay 专项

同一命令在全新 handoff 解压目录 overlay R4 lane 文件后：

```text
exit 0
99 passed, 0 skipped, 0 failed
```

冻结 SHA 测试在此布局真实执行。

### R3 adversarial 指定回归

显式运行以下六项：producer spoof allowlist、expiry equality、completed-D ATR metadata、same-side multi-touch、earlier-target-consumed long、earlier-target-consumed short。

```text
exit 0
6 passed, 0 skipped, 0 failed
```

### POSITION_REVERSAL + 冻结 R3 scoped regression

```bash
python3 -m pytest \
  research/tests/test_phase1_10m_position_reversal_*.py \
  research/tests/test_phase1_10m_primary_opportunity_*.py \
  research/tests/test_phase1_10m_to_3m_r3_replay.py \
  -q -rs
```

结果：

```text
exit 0
178 passed, 7 skipped, 0 failed
```

7 个 skip 全部来自包外 private 337-bar TradingView fixture：冻结 R3 10m replay 4 个、10m→3m R3 replay 3 个；均未计为 pass。

### Generator parity 与 Python compile

```bash
python3 research/generate_phase1_10m_position_reversal_pine_v1.py --check
python3 -m compileall -q research
```

均为 `exit 0`。Generator 报告：Pine `44,257 bytes`，full SHA `c205aef662bf900c43dc6f2af3a9e100afda3f5425a12fe4e879194f6de1f06d`，canonical block SHA `52e29ddefc34d02e4f2ac3675329d6d78d062a795c8dcb8b0f45d8200e66805b`。

### Whitespace、archive 与安全边界

- 使用 R3 clean ZIP 构造临时 Git index 后运行 `git diff --check`：`exit 0`，无 whitespace diagnostics；未创建 commit。
- 相同排序 payload、固定 ZIP timestamp/mode 与 DEFLATE level 9 重建两次：bytes 与 SHA-256 完全相同。
- ZIP CRC、relative-path、symlink、encryption 与 entry-count 检查：PASS。
- 高置信 private-key/token/credential/local-path scan：`0 findings`。

### Pine surface 与禁止项

静态检查结果：

```text
plotshape = 4
request.security = 0
label.new / line.new / box.new = 0
alert / alertcondition = 0
strategy / order = 0
```

### 原样 `scripts/validate.sh`

结果：`exit 2`，pytest collection `4 errors`。作为 test harness 的原始 handoff ZIP 仍缺少：

```text
research/fixtures/phase1_p6_episode_ledger_cases.json
release-manifest.json
research/config/v11_contract.json
```

对应：

```text
research/tests/test_phase1_p6_episode_ledger.py
research/tests/test_public_release_contract.py
research/tests/test_v11_contract_pins.py
research/tests/test_v11_pine_replica.py
```

本轮没有伪造全仓资源、修改无关测试或将 collection error 改成 skip。

## 7. 冻结 R3 未改

| 文件 | SHA-256 |
|---|---|
| `idm_phase1_10m_primary_opportunity_v3.pine` | `4f345a5f4b92a791ba7f3282f26b32a0014d0e1264bf9e84dc72e4838768807b` |
| `idm_phase1_3m_opportunity_timing_v3.pine` | `33127269ef841633dc9f82bf2d611369d753bc4d7ba4207d52fa437796c5f72b` |

两者不进入本轮 clean ZIP。

## 8. Clean ZIP payload 文件身份

报告自身与最终 ZIP 的 bytes/SHA 在交付消息中给出，避免递归自哈希。

| 文件 | Bytes | SHA-256 |
|---|---:|---|
| `idm_phase1_10m_position_reversal_v1.pine` | 44,257 | `c205aef662bf900c43dc6f2af3a9e100afda3f5425a12fe4e879194f6de1f06d` |
| `research/generate_phase1_10m_position_reversal_pine_v1.py` | 49,125 | `aabcf72baf2f637f7f4e92c688523ffdf5ef6b55a6b090bebc15f93f2055f9f9` |
| `research/phase1_10m_position_reversal_oracle.py` | 57,309 | `55f5909de0a99ed25508136e4c5c9051804686443770e7c61e73702cbba28207` |
| `research/tests/fixture_phase1_10m_position_reversal.py` | 5,258 | `6bd39d6f1ebab667d16da3cf2fcefbf3884574ebc9169e6dbdf57c4d3b296282` |
| `research/tests/test_phase1_10m_position_reversal_causality.py` | 18,848 | `6376de91f0077628bdf9243a2aa9a55502cc351f81ab3dba0ad9a220f7a92f8d` |
| `research/tests/test_phase1_10m_position_reversal_contract.py` | 21,541 | `86cf703b2bc9425f94c94afbe14597a8c76f3f1ed10decb7bba674e0680411ab` |
| `research/tests/test_phase1_10m_position_reversal_identity.py` | 10,559 | `09e297427a3cfb77c8f619d08ae895f4e727431a5753dde80a34bdbf8b8172b0` |
| `research/tests/test_phase1_10m_position_reversal_lifecycle.py` | 7,236 | `4fcaffb234a475914066d879c8c5e8f38584bb2fa55ffbd403e636a3cbe39af3` |
| `research/tests/test_phase1_10m_position_reversal_negative.py` | 10,915 | `94479a8f6ada48a68dbe81a4737cdf3b6095d73549879ffb08210700166002a9` |
| `research/tests/test_phase1_10m_position_reversal_positive.py` | 3,844 | `38ff0e24f3f42bb43ab68109a39c6bae01413e512fc16882963eebcc5834d679` |

## 9. 未验证与未执行

未执行或未声称：TradingView 在线编译、保存、加入图表或替换真实版本；真实 feed cross-check；实时前向；三个月 walk-forward；跨 TradingView input reload 的 append-only 历史；盈利或方向 edge。

TradingView 修改 inputs 仍会触发全历史重算；本轮只保证同一次生成代码和同一组 validated inputs 下的 Python/Pine identity grammar、effective material 与 outward ID 机械一致。真正跨 reload 的不可变历史仍需要未来独立 external snapshot ledger。

未 commit、push、创建 PR、deploy、创建 alert 或下单。
