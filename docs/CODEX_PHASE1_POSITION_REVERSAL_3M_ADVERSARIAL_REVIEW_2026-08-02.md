# Phase 1 POSITION_REVERSAL 10m → 3m adversarial review

Date: 2026-08-02

Reviewed baseline: `a4aa41466da38a32287c93a6ca155f85ea146fad`

Review type: read-only independent architecture review

Verdict: **REVISE**

## What passed

- Keep `TREND_CONTINUATION` and `POSITION_REVERSAL` as independent lanes.
- Put both lanes behind one production 3m host with one immutable `PlanEnvelope`,
  lane-specific adapters, one `OwnerManager`, and one marker/card/alert surface.
- Keep the July 31 11:40 `SPACE_LT_1R` observation as an end-to-end negative case:
  no envelope, no adoption, no entry, no marker, and no alert even if later 3m bars
  satisfy direction and price conditions.

## P1 corrections required before implementation

1. **Adoption-after-trigger chase control**
   - Adoption bar remains no-entry.
   - The contract must explicitly choose either a fresh post-adoption crossing, or
     a state-based trigger with a frozen maximum extension / risk-inflation gate.
   - `remaining >= 1R` alone is not a chase-control rule.

2. **Suppression ledger**
   - Suppression key is `(lane_id, opportunity_id)`.
   - Candidates blocked by an owner, same-direction arbitration losers, and both
     sides of an opposite-direction conflict are permanently suppressed.
   - Terminal/release/conflict bars cannot adopt. A later bar may adopt only a
     genuinely new, unsuppressed ID.

3. **Lane-specific terminal policy**
   - Trend timing keeps its accepted confirmed-close stop semantics.
   - Position reversal must explicitly preserve its accepted stop-touch and
     stop-first semantics unless a separately reviewed contract changes it.
   - Both lanes use target-touch; same-bar stop plus target is stop-first.

4. **Completed-10m transport**
   - Only previous-completed 10m data may be transported.
   - Adoption requires `visible_at <= current confirmed 3m bar open`.
   - A 10m close at 11:40 cannot be consumed by the 11:39–11:42 3m bar; the
     first eligible adoption bar is 11:42.
   - Each `(lane_id, opportunity_id, payload_fingerprint)` is delivered once.
   - Historical, Replay, and realtime use the same offset/lookahead semantics.
   - If the overlap bar may already have touched stop or target and ordering
     cannot be proven from OHLC, fail closed and do not adopt.

5. **Entered-owner lifecycle**
   - Before entry, invalid permission/source/identity means no-entry.
   - After entry, producer expiry/reset, identity drift, or a newer plan cannot
     rewrite the frozen owner.
   - Only the owner's trusted stop/target terminal, or a fail-closed host/data
     reset, can end management. A reset must not fabricate a stop/target marker.

## Production topology

```text
completed 10m transport
  ├─ TrendAdapter ───────┐
  └─ ReversalAdapter ────┤
                         v
                candidate arbitration
                         v
                  one OwnerManager
                         v
       lane-specific timing / terminal policy
                         v
             one marker/card/alert surface
```

Separate lane indicators may remain as developer/oracle regression references,
but must not be deployed beside the global host as competing production output.

## Minimum envelope fields

```text
schema_version
lane_id
opportunity_id
payload_fingerprint
direction
confirmation_time
visible_at
permission_expires_at
producer_reference_or_trigger
invalidation
target
initial_risk
minimum_remaining_r
timing_policy
terminal_policy
```

Mutable owner fields (`adopted_at`, `entered_at`, actual entry, timing state, and
suppression ledger) belong to `OwnerManager`, not the immutable envelope.

## UI and alert boundary

- Default chart: only `多入` or `空入` as the large decision marker.
- Terminal markers remain hidden by default; the five-row card remains visible.
- No dynamic label/line/box objects.
- Alert set must be frozen before implementation. A selectable four-event set
  (long entry, short entry, invalidated, target reached) is acceptable while the
  default chart still shows entry markers only.

## Evidence boundary

This review did not implement code, run TradingView, validate live/replay parity,
send a phone notification, place an order, or establish profitability.

## Official Pine references independently checked

- [Other timeframes and data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/):
  confirmed non-repainting HTF transport uses an offset expression such as
  `[1]` together with `barmerge.lookahead_on`.
- [Pine limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/):
  the production host still requires an online compile gate because Pine does
  not expose compiled-token usage before compilation; request tuple and unique
  request limits also remain applicable.
