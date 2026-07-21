# Claude Fable handoff

## Mission

Take over IDM as a personal TradingView decision assistant without inheriting the old version sprawl. Preserve the frozen v11 failure baseline, establish reproducible Pine/oracle parity, and change one behavioral variable at a time.

## Current truth

- The runnable source is `intraday_decision_map_v11_aggressive_clean.pine`.
- It is 1,473 lines and should be treated as a distribution artifact, not an invitation to keep appending unrelated logic.
- The Python oracle is 1,454 lines and is not yet equivalent to Pine.
- The preserved Strategy Tester snapshot is negative: PF 0.638, expected payoff -$0.33, total P&L -$175.41.
- 535 rows are partial exit legs, not 535 signals.
- Historical Confidence is uncalibrated.
- Private data and Discord material have intentionally not been published.

## User intent

- Primarily view 10m; occasionally use 3m.
- Both timeframes must show the same signal, location, Entry, Stop, T1, and T2.
- Signals should be visible and timely, but must respect location.
- Do not short into support or buy into resistance.
- Ripster-style Clouds handle trend/pace.
- Saty-style ATR handles location/target/space.
- Oscillator/divergence handles risk and deterioration.
- Price structure provides the final trigger.
- Existing positions need HOLD, PROTECT, and EXIT guidance.
- Historical markers stay visible; the newest event gets readable Chinese detail and hover text.
- Phone alerts use natural Chinese.
- Confidence eventually comes from OOS calibration, never from renaming a subjective score.

## Highest-priority audit

Before tuning performance, reconcile Pine and Python for:

- thresholds;
- confirmed 10m timing;
- level source and identity;
- all setup predicates;
- same-bar arbitration;
- per-setup de-duplication;
- Entry/Stop/T1/T2 geometry;
- plan events and order mapping.

Export a true v11 Data Window/event fixture. The existing private July 21 CSV was produced by v10.1R and cannot establish parity.

## Known code conflicts

1. Saty, pivots, prior-day levels, and moving Clouds collapse into source-less `support`/`resistance` floats.
2. The existing repeated-support/repeated-resistance logic compares adjacent bars but does not prove the same level or a real departure.
3. A generic Level Rejection can bypass 10m routing and may be nothing more than a moving-Cloud wick.
4. Cloud facts participate in context, trigger, level, target-space, and grading, creating repeated evidence.
5. The Phase proxy is not verified against a third-party oscillator.
6. Fixed setup priority may let a C-grade rejection hide a better A/B trend setup.

## Phased work

### P0 — Preserve and reproduce

- Verify release SHA and public tests.
- Recompile the exact frozen Pine in TradingView.
- Record the result without modifying the release.

### P1 — Parity and ledger

- Define one authoritative configuration contract.
- Export actual v11 event/data-window fields.
- Compare Pine and oracle bar-by-bar.
- Create a ledger that separately counts candidate episodes, SignalEvents, Plans, and exit legs.

### P2 — One experiment

Implement only the source-aware Saty second-rejection `AdvisoryEvent` specified in `EXPERIMENT_SATY_LEVEL_ADVISORY.md`. It must not place orders and must leave the frozen v11 signal/order results unchanged.

### P3 — Choose one behavior change

Only after parity, choose one of:

- source-aware rejection logic;
- active protection after T1;
- repeated resistance plus divergence as a long-exit advisory;
- 3m pace-support pullback entry in a confirmed 10m trend.

Do not change all four together.

## Required deliverables for every change

1. Hypothesis.
2. Files changed and line-level rationale.
3. Data fields required.
4. Synthetic positive, negative, and boundary cases.
5. TradingView compile/reload/replay evidence.
6. Event-level before/after report net of declared costs.
7. Known unknowns.
8. Rollback commit.

## Non-regression rules

- Do not overwrite v11.0.0.
- Do not use future data or pivot backfill.
- Do not generate separate 10m signals.
- Do not let Advisory place orders.
- Do not call A/B/C probability.
- Do not count correlated Cloud facts repeatedly.
- Do not put private community content or proprietary data in Git.
- Do not claim profitability while PF remains below 1.
