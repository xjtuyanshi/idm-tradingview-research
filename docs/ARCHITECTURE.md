# Architecture

## Product contract

The product is a personal intraday decision assistant. It should answer four questions without forcing the user to decode a wall of lines:

1. What is the confirmed 10-minute context?
2. What did the 3-minute price actually prove?
3. Where are Entry, invalidation, T1, and T2?
4. If already in a position, should the user hold, protect, or exit?

## Canonical timeline

```text
confirmed market data
    ├─ previous fully confirmed 10m bar → context only
    └─ confirmed 3m bar → setup facts and formal events
                                  ↓
                          deterministic arbitration
                                  ↓
                SignalEvent(id, side, setup, grade, geometry)
                                  ↓
                  frozen Plan(entry, stop, t1, t2)
                                  ↓
              chart + alert + optional 3m strategy order
                                  ↓
                    10m reads the same event ledger
```

There must never be separate 3m and 10m BUY/SELL engines. Switching chart timeframe must not rewrite the event, its confirmation time, or its geometry.

## Evidence responsibilities

| Evidence family | Responsibility | Must not do |
|---|---|---|
| 10m 34/50 Cloud | Directional background | Generate a standalone entry |
| 10m and 3m 5/12 | Pace and pullback state | Count as several independent votes |
| Saty-style ATR map | Static location, target, and room | Predict direction by first touch |
| Phase/oscillator | Compression or momentum deterioration | Open a trade by itself |
| Confirmed price structure | Final trigger and invalidation | Use future pivots or repaint |

Cloud slope, price relative to Cloud, and EMA cross are one correlated family. They must not be counted three times and presented as higher confidence.

## Setup families

1. **Level Rejection** — price sweeps and reclaims a visible level, or confirms a rejection on the following structure break.
2. **Pullback Continuation** — compatible context, a real pullback into a relevant area, and a confirmed reclaim.
3. **Compression / Structure Breakout** — a completed box/structure boundary is broken by a confirmed directional close.
4. **Trend Ignition** — pace/anchor state changes and price simultaneously proves structure.

Current same-bar priority is Rejection → Pullback → Breakout → Ignition. This is a known design risk because a weak C-grade generic rejection may hide a better A/B trend setup. The next implementation should rank complete candidates rather than hard-code family priority.

## Signal, plan, advisory

- `SignalEvent` may create a plan and, when enabled on 3m, an order.
- `PlanEvent` manages T1, T2, Stop, protect, exit, and reverse state.
- `AdvisoryEvent` is informational. It may draw or alert, but it must never create an order or silently modify a frozen plan.

The proposed Saty second-rejection work belongs to `AdvisoryEvent` until separate data proves it should become a setup.

## Management model

- Entry, initial Stop, T1, and T2 freeze at SignalEvent creation.
- T1 exits 50% and moves the effective Stop to Entry.
- T2 exits 25%.
- The remaining 25% is a protected runner.
- Without lower-timeframe/tick sequencing, an ambiguous same-bar Stop/Target result is treated Stop-first.
- `ADD?` is a reference only; it does not mutate the original plan or broker position.

## Maintenance boundary

TradingView ultimately needs one Pine file, but that does not justify keeping every research concern in one source file. A future build should maintain modules for context, levels, setups, plans, relay, alerts, and UI, then generate a single distributable Pine artifact. The current 1,473-line release remains frozen for reproducibility.
