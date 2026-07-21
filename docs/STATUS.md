# Status: frozen negative-expectancy research baseline

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
