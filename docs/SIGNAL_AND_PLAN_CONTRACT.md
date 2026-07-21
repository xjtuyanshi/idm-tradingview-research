# Signal and plan contract

These invariants are release gates, not suggestions.

## Time and causality

- A formal event is created only from confirmed data.
- The 10m context is the previous fully confirmed 10m value.
- A fact learned at 15:51 cannot be backfilled to 15:50.
- Reload and Replay must not move, erase, or duplicate a historical event.

## Identity

- One 3m event id owns marker, alert, plan, and optional order.
- A 10m view relays that same id; it never generates a second event.
- Entry, Stop, T1, and T2 remain identical across 3m and 10m.

## Location before direction

- Do not chase a short immediately above support.
- Do not chase a long immediately below resistance.
- A static ATR level or Cloud touch has no direction until price shows acceptance, rejection, reclaim, or confirmed break.
- First touch is information. A trade still requires a price trigger.

## Roles

- Ripster-style Clouds: context and pace.
- Saty-style ATR levels: location and target map.
- Oscillator/divergence: risk and deterioration.
- Price structure: formal trigger and invalidation.

No evidence family may be repeated as multiple independent votes.

## Grades and probability

- A/B/C is a deterministic completeness/risk grade.
- A/B/C is not a win rate and must not carry a percent sign.
- Probability must remain absent until an out-of-sample calibration report exists.

## Advisory isolation

- An advisory can draw and notify.
- An advisory cannot call `strategy.entry`, change position size, rewrite a plan, or bypass a setup.
- Promoting an advisory to trading logic requires a new version, a new experiment report, and new OOS validation.

## Reporting

Always report separately:

- de-duplicated candidate episodes;
- SignalEvents;
- Plans;
- partial exit legs.

Never calculate a signal win rate from partial exit legs.
