# Sanitized method observations — 2026-07-21 morning

## Source and privacy boundary

This document is a paraphrased research note made from ordinary, read-only review of a private community feed and the accompanying charts. It contains no copied messages, usernames, screenshots, message links, or membership details. It does not estimate the author's win rate.

Posts are selective and can be published after price has already moved. They are useful for extracting a process, not for proving same-price execution or historical probability.

## What happened at a high level

The morning began with price beneath an important hourly/10-minute resistance area. An early downside trade was managed profitably. Price then repeatedly held smaller-range and premarket support, while volatility stopped confirming additional downside. A bullish trigger invalidated the simple short thesis.

After that change, price still had to work through 10-minute resistance. The first upside was choppy, but completion of the larger Cloud/range transition was followed by a trend in which shallow 3-minute pullbacks were repeatedly bought. Near the 7500 area, price compressed and showed momentum deterioration; that was useful for long management and mean-reversion awareness, not an automatic permission to short a still-intact uptrend.

Later, a 10-minute bullish expansion confirmed what the 3-minute tape had already been showing. The clearest missed opportunity was not a lack of indicators; it was remaining skeptical after support and pace repeatedly confirmed the same direction.

## Location → State → Trigger → Management

| Phase | Location | State | Price trigger | Correct management lesson |
|---|---|---|---|---|
| Opening weakness | Higher-timeframe/10m resistance | Weak, but near smaller-range support | Support loss and failed reclaim | Short may be valid; take profit into known support rather than demand continuation |
| Downside stalls | Premarket/smaller-range low, volatility pivot | Repeated failure to extend lower | Reclaim of the long trigger / local structure | Stop pressing shorts; prepare for a directional switch |
| Early upside chop | 10m 21-area resistance and incomplete Cloud transition | Bullish attempt, not yet clean trend | Range/Cloud completion | Small probes are acceptable; repeated countertrend shorts need rapid exits |
| Trend established | 3m 21/fast Cloud repeatedly holds | Higher lows and shallow bought dips | Reclaim or break of the pullback candle | Dip-buy/HOLD logic; absence of a new BUY must not become `禁止做多` |
| Round-number pressure | Near 7500 plus known resistance | Compression and weaker oscillator peak | Actual structure failure is still required | Scale/protect longs or wait; divergence alone is not a naked short |
| 10m expansion | 3m support intact, 10m compression resolves up | Context and execution align | Confirmed 10m expansion / 3m continuation | Hold existing long; do not chase an extended candle without a reset |
| Late grind | Above value and far from better entry | Trend intact but poor new reward/risk | A fresh 10m pullback is needed | Keep runners protected; allow a no-trade decision instead of chasing |

## Rules worth testing

1. **Support response outranks a weak-direction opinion.** If an opening short reaches a known support that has already held, continuation must be re-proven. Otherwise protect or exit.
2. **A bullish invalidation changes the route.** Once the short invalidation/long trigger is reclaimed, new shorts require a fresh failed rally rather than reuse of the opening thesis.
3. **Repeated 3m pace support matters.** In a confirmed bullish 10m context, repeated 3m 21/fast-Cloud holds should permit a pullback BUY or at least `HOLD LONG`.
4. **Divergence is management-first.** Bearish divergence near resistance means protect longs and wait for price damage. It does not independently create a short.
5. **Do not chase mature extension.** Once price is far above the 10m value area, a valid trend can coexist with a poor new entry.
6. **Static levels need identity.** The system must say whether a rejection occurred at a Saty ATR ratio, prior high/low, or a moving Cloud. A source-less `R1` is insufficient.

## One integration experiment

The smallest honest integration is a source-aware Saty-level advisory:

```text
first rejection of one static ATR level
→ clear departure from that exact level
→ second test of the same level
→ confirmed rejection
→ AdvisoryEvent only
```

It should draw `Saty 二拒↑` or `Saty 二拒↓`, include the level ratio and times in Data Window/tooltip, and send natural Chinese text. It must not place an order or change A/B/C until a separate event dataset demonstrates value.

The complete contract is in [EXPERIMENT_SATY_LEVEL_ADVISORY.md](EXPERIMENT_SATY_LEVEL_ADVISORY.md).

## What cannot be concluded

- No win rate or probability can be calculated from this morning.
- A posted profitable position does not prove a follower could enter at the same price.
- The 7500-area percentage mentioned by the source was a contemporaneous opinion, not a calibrated model output.
- These observations do not validate the current IDM order logic.
