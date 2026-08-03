# ChatGPT Pro package receipt｜POSITION_REVERSAL 3m 预实现审查

日期：2026-08-02

```text
Baseline commit: a4aa41466da38a32287c93a6ca155f85ea146fad
Archive: idm-position-reversal-3m-preimplementation-a4aa414-20260802.zip
Size: 165245 bytes
Entries: 34
SHA-256: dbd2fcd99aa4e228e93f9058fc2ee64670a6470f95395a3dd214521ed17429a6
```

打包方式：对上面 commit 使用 `git archive` 白名单，只包含本任务的 handoff、架构/合同、
两个 10m producer、现有 3m timing 参考、两个 Oracle、generator、fixtures 与相关测试。
没有从 dirty working tree 复制文件。

排除边界：`.git`、`.env`、浏览器状态、Cookie、登录数据、API key、token、私钥、数据库、
缓存、构建产物、运行状态、`companion_app` 和与本任务无关的未跟踪/已修改文件均未进入包。

验证：

```text
ZIP CRC/test: PASS
Forbidden credential/browser/database filename scan: PASS (no matches)
High-confidence secret/token/private-key scan: PASS (no matches)
POSITION_REVERSAL generator/Pine byte parity: PASS
POSITION_REVERSAL targeted tests: 132 passed
```

本包用于 ChatGPT Pro 预实现架构审查，不授权推送、PR、部署、webhook、订单、自动交易或
盈利声明。最终实现仍以 Codex 独立源码审查、测试和 TradingView 在线门禁为准。
