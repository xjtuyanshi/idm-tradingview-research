# Failures and limits

## The strategy currently loses money

The preserved TradingView snapshot is not ambiguous: Profit Factor 0.638, expected payoff -$0.33, and total P&L -$175.41 over the recorded 2026-07-16 to 2026-07-21 window. Execution fixes reduced an earlier larger reported loss, but they did not create a positive edge.

The data window is short and does not prove the strategy will always lose. It is nevertheless enough to forbid claims that the present version is profitable.

## The displayed count is not a win rate

TradingView reported 535 partial exit legs. T1, T2, and runner exits from one plan can generate several rows. The 182 profitable rows therefore cannot be interpreted as 182 winning signals.

## Probability is missing, not hidden

No calibrated historical Confidence exists. A probability feature requires:

- a de-duplicated candidate ledger;
- true v11 event exports;
- instrument/session/cost definitions;
- time-ordered training, calibration, validation, and final OOS sets;
- sample count, confidence interval, model version, and cutoff date.

Until then the UI must say `历史概率：未校准` or show no percentage.

## Pine/oracle mismatch

The Python oracle is not a proven byte-for-byte replay of Pine. Known differences include body thresholds, breakout buffers, level tolerance, compression width, wick requirements, extension grading, level construction, target selection, and event de-duplication.

The private July 21 fixture contains old v10.1R indicator columns. The oracle uses its OHLC data to demonstrate causal opportunities, but that does not prove Pine v11 emitted identical events.

## Method fidelity limit

The Pine Phase value is a local EMA/ATR proxy. It is not verified against a third-party proprietary oscillator. The repository does not include or claim to reproduce private indicator source code.

The ATR map is an independent implementation of a prior-close plus daily-ATR ladder. It must not be described as a licensed copy of another script.

## Data and publication limits

Private TradingView/Capital.com CSV exports, chart screenshots, community posts, usernames, links, and message text are not in this repository. The corresponding four fixture-dependent tests skip in the public checkout.

## Execution model limits

- Commission defaults to zero because the source can run on different instruments.
- Slippage is a generic two-tick assumption.
- A CFD, ES, MES, SPX index, and ETF do not share the same fill or fee model.
- Bar-close backtests cannot determine intrabar target/stop ordering without lower-timeframe or tick data.
- Strategy Tester results are not live fills.

## UI/runtime evidence limit

Existing notes record that TradingView revision 13 loaded without runtime error. This public release has not been freshly recompiled inside TradingView during repository creation. Static Python tests cannot replace that check.

## Failure patterns not to repeat

1. Do not respond to zero signals by blindly increasing signal frequency.
2. Do not change UI, entry, exit, order model, and statistics in one experiment.
3. Do not optimize from one selected day or private screenshots.
4. Do not let S1/R1 lose their source identity.
5. Do not let Cloud information vote repeatedly under different names.
6. Do not overwrite a failed baseline with a later result.
