# Status（入口，2026-07-24 更新）

当前版本：**13.1.0-declutter**（TV 云端 v25.0，compileOk，LF 归一化 SHA 前缀 `9c212821287d1365`）。
系统全览与运维手册：`docs/SYSTEM_V13.md`；外审交接：`docs/HANDOFF_CHATGPT_V13.md`；
分段地图：`docs/ARCHITECTURE_V12.md`。

**一句话状态**：冻结的 v11 引擎之上，v13 跟单模块自 2026-07-22 18:00 ET 起做
预登记前向试验（只跟关键位拒绝、早午盘、单仓、止损不动、≥3 点风险；毛/费后双轨；
60 笔批次淘汰制，≤−10R 硬淘汰）。对抗审查的费后点估计 ≈ −0.15R/笔——前向数据说话。

| 项 | 状态（07-24 凌晨） |
|---|---|
| 前向账本 | Day 1（07-23）：2 笔全额止损，毛 −2R / 费后 −2.2R |
| 推送警报 | "IDM v13.1 Forward" 00:42 ET 重建（绑 v25，App 通知/24小时日程已核对） |
| 通道自检 | 13.1 新增：每交易日 09:33 ET 心跳；缺席=通道故障 |
| 契约测试 | 92 passed / 4 skipped |
| TV 库 | 21 个 IDM 中间版本已删；仅存 IDM v13 Forward（+无关脚本） |
| 已知风险 | 用户 DS Bridge webhook 全天失败刷屏（SYSTEM_V13 §8；未触碰） |

---

# 历史基线：Status: frozen negative-expectancy research baseline

Date frozen: 2026-07-21

## Executive verdict

IDM v11 is usable as a chart and event-logging research baseline. It is not a validated trading system.

| Item | Status |
|---|---|
| Pine source | Frozen as `11.0.0-clean` |
| 3m/10m event identity | Implemented by a canonical 3m engine and 10m relay |
| Chinese chart/phone copy | Implemented in source contracts |
| TradingView runtime evidence | Revision 13 previously loaded on SPX500 3m/10m |
| Pine compilation in this public checkout | Not independently recompiled here |
| Pine ↔ Python event parity | Not established |
| Historical Confidence | Not calibrated; must remain hidden |
| Strategy edge | Failed on the recorded short window |

## Recorded Strategy Tester snapshot

Window: 2026-07-16 through 2026-07-21.

| Metric | Result |
|---|---:|
| Partial exit legs | 535 |
| Profitable exit legs | 182 / 535 (34.02%) |
| Profit Factor | 0.638 |
| Expected payoff | -$0.33 |
| Maximum drawdown | $205.46 |
| Total P&L | -$175.41 |

`535` is the number of T1/T2/runner exit legs, not the number of independent signals or plans. Therefore `182/535` is not a signal win rate.

## Exact release identity

- Pine version: `11.0.0-clean`
- Pine SHA-256: `77c6fb4014f3ba93d741bbe445438db0664609326145c82fafe9403b8b80cd03`
- Original source commit: `8a5f03a6a321733df8fb330bf8ad685691ba357d`
- Frozen fixture commit: `f3d5dcd`
- Prior TradingView revision: `IDM v11 Aggressive Clean · 13.0`

## What v11 fixed

- Removed the serial episode/cooldown chain that starved v10 signals.
- Made confirmed 3m bars the only formal signal source.
- Made 10m a synchronized read-only projection of the same event.
- Preserved Entry, Stop, T1, and T2 when a plan is created.
- Kept A/B/C as rule grades instead of pretending they are probability.
- Replaced JSON-looking phone text with natural Chinese message construction.
- Kept optional strategy orders off by default.

## What remains broken or unproved

- The strategy result is negative.
- Pine and the Python oracle use different thresholds, level pools, target rules, and de-duplication details.
- Existing private fixture CSVs came from the old v10.1R export, not from a true v11 event ledger.
- S1/R1 collapse several possible sources into one unnamed number.
- The Phase value is an internal proxy, not a verified reproduction of Saty Phase.
- There is no formal divergence engine, VIX/NDX model, critical-time model, or historical probability model in this release.
- TradingView execution assumptions remain instrument- and broker-dependent.

The next developer must complete Pine/oracle parity and event-level accounting before optimizing performance.

## Takeover addendum — 2026-07-21 (Claude Fable)

The frozen release above is unchanged (SHA re-verified). Progress since the handoff:

| Item | Status |
|---|---|
| Takeover audit (A–I) | `research/reports/IDM_V11_TAKEOVER_AUDIT_2026-07-21.md` |
| P0 recompile on TradingView | **Passed**: saved revision 13 verified byte-identical to the frozen source after CRLF/trailing-space normalization; fresh Add-to-chart on `CAPITALCOM:SPX500` ran with `failed:false` on both 3m and 10m. Evidence: `research/reports/IDM_V11_P0_P1_PROGRESS_2026-07-21.md` |
| Single authoritative config contract | `research/config/v11_contract.json` (contract_version 1) + three-way pin tests |
| Frozen-Pine replica engine | `research/v11_pine_replica.py` — line-referenced replica of the frozen Pine; `v11_oracle.py` is preserved unchanged as the causal-opportunity study engine and is **not** the parity artifact |
| Pine ↔ Python event-level parity | **Established for the replica** on a true v11 export (2026-07-16→21, CAPITALCOM:SPX500): 242/242 Pine SignalEvents and 291/291 plan events reproduced, all eleven feature series bit-exact, 3m↔10m relay identity 211/212; residual replica-only extras (≤4) are dissected sub-1e-11 float-boundary cases where Pine's own two hosts can disagree. Report: `research/reports/IDM_V11_PARITY_2026-07-21.md`; guard: `research/tests/test_v11_true_fixture_parity.py` (skips without the private fixture). Four empirically pinned micro-semantics (HTF open-time [1] mapping, SMA-seeded ta.ema, left-tie/right-strict pivots, session-chained daily closes) are recorded in the contract. The manifest's `pine_oracle_parity` describes the frozen-release oracle and stays false. |
| Strategy edge | Unchanged: still failed on the recorded window |
| v11.1 Clear delivered | `intraday_decision_map_v11_1_clear.pine` (`11.1.0-clear`): engine byte-identical to the frozen release, Saty second-rejection AdvisoryEvent (draw/alert only, never trades), layered marker declutter (full labels only for trend entries/reversals). Saved to the user's TradingView library as **IDM v11.1 Clear** (v2.0, cloud content SHA-verified, Chinese intact) and compiled/running on SPX500. Details: `research/reports/IDM_V11_1_DELIVERY_2026-07-21.md`; user manual: claude.ai artifact `856d1f1d` |
