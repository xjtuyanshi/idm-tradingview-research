# Experiment: source-aware Saty second-rejection advisory

Status: specified, not implemented in the frozen v11 release.

## Hypothesis

A second confirmed rejection of the same static daily-ATR level, after price clearly departed from it, may provide more useful position-risk context than a generic source-less `Level Rejection` flag.

This is initially an advisory hypothesis. It must not trade.

## Required level identity

Every tracked level must retain:

- anchor session/date;
- ATR ratio/id, for example `+0.618`;
- absolute price;
- initial side (support or resistance);
- first-test confirmation time;
- invalidation price;
- expiry.

Moving EMA/Cloud values cannot impersonate the same static level.

## State machine

```text
IDLE
  └─ confirmed first rejection → WATCH(level_id)

WATCH(level_id)
  ├─ close through invalidation → IDLE
  ├─ anchor/session changes → IDLE
  ├─ expiry reached → IDLE
  └─ price departs by configured ATR distance → DEPARTED(level_id)

DEPARTED(level_id)
  ├─ invalidation/expiry/session reset → IDLE
  └─ same level retested and rejection confirmed
       → AdvisoryEvent(SATY_SECOND_REJECTION) → IDLE
```

Repeated touches without a departure do not count as two tests. Adjacent ATR ratios cannot be joined into one episode.

## Event behavior

- Chart: `Saty 二拒↑` below a bullish rejection or `Saty 二拒↓` above a bearish rejection.
- Tooltip: level price, ratio/id, first test, departure, second-test confirmation, invalidation.
- Phone: natural Chinese, for example `IDM｜Saty +0.618 出现第二次看空拒绝；这是风险提醒，不是自动做空。`
- 10m: relay the same 3m advisory id and confirmation time.
- Orders: none.
- Plan: no mutation.

## Acceptance tests

- First rejection creates WATCH but no SignalEvent, Plan, or order.
- No departure means no second-rejection advisory.
- Both tests must share the same level id.
- A confirmed close through invalidation clears state immediately.
- Long and short behavior is symmetrical.
- Turning the advisory off leaves every v11 SignalEvent id, order count, and Strategy Tester result unchanged.
- 3m and 10m display the same advisory id/time/level.
- Reload and Replay do not move or duplicate the event.
- A fact confirmed at 15:51 is never plotted at 15:50.

## Promotion gate

To promote this advisory into a setup, create a new version and require:

- a de-duplicated event ledger;
- a price-structure trigger after the second rejection;
- OOS results net of instrument-specific costs;
- comparison against a same-location baseline;
- a report of both favorable and failed events.
