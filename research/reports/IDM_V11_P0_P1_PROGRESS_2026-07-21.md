# IDM v11 接手进度报告：P0 复现验收 + P1 契约与复刻引擎（2026-07-21）

前置文档：`IDM_V11_TAKEOVER_AUDIT_2026-07-21.md`（接手审计，A–I 九项）。本报告记录审计获批后的第一批执行结果。冻结源 `intraday_decision_map_v11_aggressive_clean.pine` 未改动任何字节（SHA 复验见下）。

## P0：TradingView 重新编译验收 —— 通过

执行方式：经用户授权，通过用户本机 Chrome 的实际 TradingView 会话操作；未修改用户任何已保存脚本、参数或正式布局。验证在用户的 `daytrade_codex_trest` 测试布局上进行，结束后已将验证用策略从图上移除。

| # | 验证项 | 方法 | 结果 |
|---|---|---|---|
| 1 | 云端修订 13 ≡ 仓库冻结源 | 经 TradingView pine-facade 只读接口取回用户已保存脚本 `IDM v11 Aggressive Clean`（版本 13.0）源码，在页面内计算 SHA-256 | 原始文本为 CRLF 行尾（76,654 字符）；按 CRLF→LF + 去每行行尾空白规范化后，SHA-256 = `77c6fb40…b80cd03`，与 `release-manifest.json` **逐字节一致**。manifest 的"修订 13 即冻结源"声明成立 |
| 2 | 3m 主机重新编译/运行 | 图表切至 `CAPITALCOM:SPX500` 3 分钟，从 Pine Editor 将该脚本 Add to chart（2026-07-21 美东下午，实时行情下） | 编辑器日志 `Added to chart.`，无编译错误；经 TradingView 图表 API 读取 study 状态：**`failed: false`**，参数元组确认为冻结默认值 `(5, 12, 34, 50, 14, 3, 4, 8, 0.1, 0.02, 0.34, 2.2, 0.1, 1.3, 0.55, 2, false, true, …, 1500, false)`（订单开关为 false） |
| 3 | 10m relay 主机 | 同一窗格周期切换到 10 分钟，重新读取 study 状态 | `resolution: "10"`，**`failed: false`**，无 runtime error |
| 4 | 现场还原 | 通过图表 API 移除验证用策略 | 移除成功；窗格恢复为用户原有 10 个指标。注：该测试布局的符号/周期由 TSLA·10m 改为了 SPX500·10m（属测试布局，未还原符号） |

附带发现（与 IDM 无关）：用户 VIX 窗格上有一个**本来就存在**的第三方指标报错（红色感叹号在本次加载任何东西之前已出现），未处理。

P0 结论：冻结源在当前 TradingView Pine v6 上编译、3m/10m 双主机运行均无错误。审计未知项 I-1 关闭；I-2（:00/:30 边界实测）仍待真 fixture 阶段用 Data Window 验证。

## P1（代码半程）：唯一配置契约 + 冻结 Pine 复刻引擎 —— 完成

新增文件（均为新文件，未改动任何既有代码与测试）：

| 文件 | 作用 |
|---|---|
| `research/config/v11_contract.json` | contract_version 1。以冻结 Pine 实际行为为唯一权威的机器可读契约：全部长度/阈值/Phase 常量、六源关键位池定义、路由（含"启动实际恒放行"的如实记录）、仲裁顺序、去重边沿、计划生命周期、:00/:30 边界语义、事件 id 公式、执行层参数 |
| `research/v11_pine_replica.py` | **冻结 Pine 的逐行 Python 复刻**（带 `pine:N` 行号引用）。与保留不动的 `v11_oracle.py` 定位不同：oracle 是"因果机会研究引擎"，replica 是 parity 工件。实现了审计 B 表全部 24 处 Pine 语义，包括：na 传播（无预热闸门）、containing-bar `[1]` 边界、小实体锤子拒绝、逆势 Ignition、setup 优先级仲裁、`ready and not ready[1]` 边沿去重、STOP→T2→T1→结构→保护的生命周期顺序、同 bar 止损再进场、同 bar 反手、ADD/逆势 advisory 角色、id 公式 |
| `research/tests/test_v11_contract_pins.py` | 三方钉死：冻结 Pine 源码（正则逐项）↔ 契约 JSON ↔ `ReplicaConfig` 默认值/加载值；含 manifest SHA 一致性 |
| `research/tests/test_v11_pine_replica.py` | 行为测试，逐条对准审计 B 表差异：小实体拒绝（B#6）、无 10m 上下文照发（B#22）、逆势 Ignition C 级 + mask 128（B#18）、边沿去重与 ADD 不改冻结计划（B#23）、同 bar 反手（B#27/28）、stop-first、T2 对齐 runner 抬损到 T1、:00/:30 边界读上一根 10m（B#32）、Saty 盖子 0.55R 空间封锁（B#9 的 Pine 侧语义）、优先级映射 |

验证状态：

```text
71 passed, 4 skipped（跳过项 = 私有 fixture 缺失，与冻结发布契约一致）
frozen Pine SHA verified: 77c6fb40…b80cd03
```

（本机系统 python 无 pytest；用 `uv venv` + `.venv/bin/python -m pytest research/tests -q` 运行，CI 脚本未改。）

除测试外，五个关键场景的引擎内部路径已用调试脚本逐值核对（proof 集合、support 取 anchorLower=99.9729、reason mask 65/200、short space 0.7382、runner effStop=T1=101.6021 等均与手算一致）。

## 与审计结论的对应关系

- 审计 D（唯一权威契约）→ `v11_contract.json` + pins 测试落地；
- 审计 B（24 处差异）→ 全部以"Pine 为准"实现进 replica，oracle 保留原样作历史工件；其中 oracle 独有的"改进"（显式 no-chase、等级优先仲裁、CONTEXT_PROTECT 等）继续留在候选改进清单，未混入；
- 审计 C/E（真 fixture）→ **仍是下一步**：replica 是代码级对齐，事件级 parity 必须等真 v11 TradingView 导出（manifest 的 `pine_oracle_parity` 保持 false，未动）。

## 下一步（按获批顺序）

1. **真 v11 fixture 导出**（审计 E1 第 1–3 步，零代码）：3m/10m 挂冻结版导出完整历史 CSV（含 ≥3 个交易日预热）。导出动作需要在 TradingView 界面触发文件下载，将在执行前向用户逐项确认文件名与保存位置。
2. 用 `load_tradingview_csv` + replica 逐 bar 对账，出首份事件级 parity 报告；:00/:30 边界（审计 I-2）与 pivot 平局语义（replica 注记）在此步实证。
3. parity 确认后进 P2：`11.1.0-advisory` 实现 Saty 二次拒绝 AdvisoryEvent（独立新文件，零扰动回归按审计 H2 执行）。
