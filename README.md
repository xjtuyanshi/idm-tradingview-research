# IDM TradingView Research

> **Current verdict:** IDM v11 fixes signal visibility and keeps the 3-minute and 10-minute views on one event ledger, but it has **not** demonstrated a trading edge. The recorded 2026-07-16 to 2026-07-21 TradingView snapshot has Profit Factor **0.638**, expected payoff **-$0.33**, and total P&L **-$175.41**. Historical probability is **not calibrated**.

This repository is a clean, public handoff of a personal intraday decision-assistant research project. It intentionally excludes old versions, private Discord material, proprietary chart screenshots, broker exports, local paths, and the previous repository history.

## Start here

1. Read [docs/STATUS.md](docs/STATUS.md).
2. Read [docs/TRADINGVIEW_SETUP_ZH.md](docs/TRADINGVIEW_SETUP_ZH.md).
3. Paste [intraday_decision_map_v11_aggressive_clean.pine](intraday_decision_map_v11_aggressive_clean.pine) into the TradingView Pine Editor.
4. Use the 3-minute pane as the canonical signal/order host and the 10-minute pane as a synchronized read-only view.
5. Keep `启用 3分钟策略订单` **off** for normal chart use. Turn it on only when deliberately running Strategy Tester.

If another AI is taking over, give it [docs/CLAUDE_FABLE_START_PROMPT.md](docs/CLAUDE_FABLE_START_PROMPT.md) and require it to read the files listed there before editing code.

## What is frozen

- Pine release: `11.0.0-clean`
- Source file: `intraday_decision_map_v11_aggressive_clean.pine`
- Frozen source SHA-256: `77c6fb4014f3ba93d741bbe445438db0664609326145c82fafe9403b8b80cd03`
- Original source commit: `8a5f03a6a321733df8fb330bf8ad685691ba357d`
- TradingView evidence: revision 13 previously loaded without a runtime error on `CAPITALCOM:SPX500` 3m and 10m

The exact frozen source is preserved as a failed-but-runnable baseline. Do not overwrite it. New behavior belongs in a new version and must receive a new report.

## Architecture in one minute

```text
previous confirmed 10m context
              ↓
canonical confirmed 3m engine
              ↓
four setup families + risk/space checks
              ↓
SignalEvent → frozen Plan → chart / Chinese alert / optional order
              ↓
10m displays the same 3m event; it does not create another signal
```

The four setup families are Level Rejection, Pullback Continuation, Compression/Structure Breakout, and Trend Ignition. A/B/C indicate rule completeness and suggested risk tier; they are **not win probabilities**.

## SATy-method observation boundary

A sanitized, paraphrased review of the 2026-07-21 morning is in [docs/SATY_OBSERVATIONS_2026-07-21.md](docs/SATY_OBSERVATIONS_2026-07-21.md). It produced one proposed advisory experiment: a source-aware, second-rejection warning at the same static ATR level. That experiment is specified in [docs/EXPERIMENT_SATY_LEVEL_ADVISORY.md](docs/EXPERIMENT_SATY_LEVEL_ADVISORY.md), but it is deliberately **not allowed to place orders** and is not hidden inside this frozen release.

## Validation

```bash
python3 -m pip install pytest
./scripts/validate.sh
```

The public suite runs source-contract and synthetic-oracle tests. Four tests that require private Capital.com/TradingView CSV exports are retained but skipped when those files are absent. The private data is not redistributed.

Static tests do not prove Pine compilation, live alert delivery, order-fill parity, profitability, or calibrated probability. See [docs/FAILURES_AND_LIMITS.md](docs/FAILURES_AND_LIMITS.md).

## Repository map

```text
intraday_decision_map_v11_aggressive_clean.pine  frozen TradingView release
research/v11_oracle.py                           independent research oracle
research/tests/                                  public contract/synthetic tests
research/reports/                                preserved validation report
docs/                                             architecture, setup, failures, handoff
release-manifest.json                             immutable release identity
```

## License and disclaimer

Repository-authored code and documentation are released under the MIT License. Method names such as Ripster and Saty identify independent, from-scratch research inspired by publicly discussed concepts; this project is not affiliated with or endorsed by those authors. It does not redistribute private community posts or third-party indicator source code.

This is research software, not financial advice or a promise of profitability.
