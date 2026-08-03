# Phase 1 3m global owner implementation freeze

Date: 2026-08-02

Freeze baseline: `16ee5a1`

Status: **implementation-authorized contract; code and TradingView online gate
not yet complete**

This document supersedes conflicting 3m-owner, HTF-transport, July 31 positive,
and open-ended reversal timing text in earlier handoffs. It does not modify the
accepted 10m trading judgments.

## 1. This step has one job

Build one production 3m execution host that consumes already-confirmed 10m
opportunities from two independent lanes:

```text
one previous-completed 10m transport
              |
      +-------+-------+
      |               |
TrendAdapter     ReversalAdapter
      |               |
      +-- immutable PlanEnvelope candidates
                       |
                 OwnerManager
                       |
          one marker / card / alert surface
```

The host decides only whether and when one 10m plan earns one confirmed 3m entry.
It does not rediscover positions, vote between indicators, combine confidence,
place orders, or add VIX/MACD/divergence/AI scoring.

Production file:

```text
idm_phase1_3m_global_owner_v1.pine
```

The existing standalone 10m and 3m scripts remain frozen regression references;
they are not deployed beside the new host as competing decision outputs.

## 2. Immutable PlanEnvelope

Both adapters can submit only a complete immutable envelope:

```text
schema_version
lane_id
opportunity_id
episode_id
payload_fingerprint
direction
producer_trigger
invalidation
target
target_source_key
confirmation_time_ms
visible_at_ms
permission_expires_at_ms
context_valid_until_ms (optional)
```

The fingerprint covers lane, IDs, direction, geometry, source context and times.
Adoption time, entry time, actual entry, timing branch, owner state and suppression
are mutable `OwnerManager` fields and are never written back into the envelope.

The identity key is `(lane_id, opportunity_id, payload_fingerprint)`. Reuse of
the same lane/opportunity ID with a different fingerprint is an identity
collision: fail closed, suppress both forms, and emit no entry. `OwnerManager`
also maintains a persistent base-ID fingerprint registry and collision
tombstone keyed by `(lane_id, opportunity_id)`. Once any different fingerprint
appears for that base ID, every existing and future variant is rejected; a third
fingerprint cannot escape the collision.

## 3. One non-repainting completed-10m transport

The global host uses exactly one `request.security()` superset tuple for both
adapters. Every tuple/UDT field is offset **inside the 10m expression context**:

```text
request.security(
    syminfo.tickerid,
    "10",
    [all_required_10m_expressions[1]],
    gaps = barmerge.gaps_off,
    lookahead = barmerge.lookahead_on)
```

The generator must express the valid Pine tuple syntax without mixing offsets.
All transported time, `time_close`, OHLC, source/target/ATR metadata, identity
inputs and derived producer inputs refer to the same previous-completed 10m bar.

Forbidden:

- unoffset `lookahead_on`;
- `lookahead_off` realtime/historical dual-offset branches;
- `barstate.isrealtime` offset switching;
- applying `[1]` after values return to the 3m context;
- forming-10m payloads, `input.source`, `timenow`, `varip`, or UI state as
  transport;
- separate trend and reversal HTF requests that can disagree on source time.

The shared payload remains pending until both conditions are true:

```text
payload.visible_at_ms <= current confirmed 3m bar open time
payload.source_time != last_consumed_10m_source_time
```

`visible_at_ms` is the requested 10m `time_close`. A failed visibility check
must not advance the last-consumed identity. A successful consumption advances
both adapters at most once for that completed 10m timestamp.

Boundary examples:

- a 10m payload visible at 09:40 cannot be consumed by the 09:39–09:42 3m bar;
  09:42 is the first eligible adoption bar;
- a 10m payload visible at 11:40 cannot be consumed by the 11:39–11:42 3m bar;
  11:42 is the first eligible adoption bar;
- adoption is committed only on a confirmed 3m bar, and that same bar is always
  entry-ineligible; the next continuous confirmed 3m bar is the earliest entry.

Before candidate arbitration, the manager must conservatively test both the
3m overlap bar that crossed `visible_at_ms` and the eligible adoption bar for a
terminal that occurred before ownership could be established. The overlap bar
is checked as a whole because 3m OHLC cannot reconstruct whether its extreme
occurred before or after the embedded 10m close:

- Trend invalidation keeps its accepted confirmed-close rule; reversal
  invalidation uses high/low touch.
- Both lanes use target high/low touch.
- If both are present, stop is first.
- Any hit suppresses the candidate and forbids adoption. The host must not adopt
  an already-finished plan merely because its payload became visible later.

This whole-overlap-bar check is intentionally conservative and may reject a
case whose extreme occurred before `visible_at_ms`; without lower-timeframe
event ordering it cannot safely claim the opposite.

## 4. Lane policies remain different

### TREND_CONTINUATION

- Preserve the accepted R3.2 `WAIT_PULLBACK -> WAIT_TRIGGER` sequence.
- The pullback bar only freezes the 3m trigger; it never enters.
- Preserve the existing EMA/cloud predicate and eight-3m-bar trigger lifetime.
- Stop semantics remain the exact accepted confirmed-close invalidation rule.
- Target semantics remain price touch.

### POSITION_REVERSAL

- The 10m producer already proved prior-known location plus confirmed reaction.
- The 3m consumer does not demand a second pullback or the trend lane's cloud
  predicate.
- Stop semantics remain high/low price touch.
- Target semantics remain high/low price touch.
- Stop and target on the same bar are always stop-first.
- Adoption chooses one of the following timing branches once; it cannot switch.

#### WAIT_IMMEDIATE_CONFIRM

Choose this branch when:

```text
long:  adoption_close > frozen_trigger
short: adoption_close < frozen_trigger
```

Only the immediately following continuous confirmed 3m bar is eligible.
Continuity is exact:

```text
candidate_bar_open_ms == adoption_bar_open_ms + 180000
```

Any other timestamp is a global gap/backward-time failure before timing logic,
with no entry and suppression preserved.

Long must satisfy all of:

```text
close > frozen_trigger
close <= frozen_adoption_high
EMA5 > EMA12
stop and target not touched first
finite positive risk and reward
remaining R >= 1.0
```

Short mirrors the rule:

```text
close < frozen_trigger
close >= frozen_adoption_low
EMA5 < EMA12
stop and target not touched first
finite positive risk and reward
remaining R >= 1.0
```

Any failed condition immediately locks the plan as `MISSED`. It cannot wait for
another bar or fall back to `WAIT_FRESH_CROSS`.

#### WAIT_FRESH_CROSS

Choose this branch when the adoption close is on the safe side of, or equal to,
the trigger. Wait only for the first post-adoption confirmed-close cross event:

```text
long:  previous confirmed close <= trigger and current close > trigger
short: previous confirmed close >= trigger and current close < trigger
```

The first cross bar must also pass the directional EMA relation, stop-first and
target checks, finite positive geometry, and entry-time remaining `R >= 1.0`.
If any gate fails on that first cross, lock `MISSED`; a second cross cannot enter.
If permission or context validity ends before a cross, lock `EXPIRED`.

For every unentered candidate bar, validity is strict:

```text
bar_open_ms < permission_expires_at_ms
context_valid_until_ms is absent OR bar_close_ms < context_valid_until_ms
```

Equality is expired. Permission/context expiry and any allowed terminal on the
same bar are processed before immediate-confirm or fresh-cross entry. Thus an
expiry-plus-cross bar cannot enter.

This is a discrete-event wait, not an open-ended state condition. It prevents a
plan that has sat beyond the trigger for many bars from becoming a late chase.

## 5. Entry geometry

At the eligible confirmed 3m entry close, recompute against the same frozen stop
and nearest target:

```text
long:  risk = close - stop; reward = target - close
short: risk = stop - close; reward = close - target
```

Risk and reward must be finite and strictly positive. `reward / risk >= 1.0` is
required; exact `1.000R` passes and any value below one fails permanently for
that plan. The consumer cannot skip the frozen nearest target to manufacture
space.

The entry close is a condition-observation price, not a promised fill price.

## 6. One owner, no replacement and no queue

- At most one adopted or entered owner exists globally.
- A newly adopted owner is frozen and cannot be replaced before terminal.
- An entered owner survives producer permission/source expiry, `ACTIVE=None`,
  identity drift and newer opportunities; frozen stop/target management remains.
- A blocked new candidate is not queued for later adoption.
- Candidates blocked by an owner, same-direction arbitration losers, and both
  sides of an opposite-direction conflict are suppressed by full identity.
- With no owner, same-direction candidates choose earlier `visible_at`; an exact
  tie chooses `TREND_CONTINUATION` before `POSITION_REVERSAL`.
- With no owner, opposite directions on the same bar become conflict; adopt
  neither and suppress both.
- Every candidate observed on an owner terminal, conflict, or global-reset bar
  is recorded as seen/suppressed before the bar ends. It cannot be adopted on
  the next bar by persisting with the same identity; a changed fingerprint for
  the same base ID activates the collision tombstone.
- Wrong-lane, wrong-ID, wrong-fingerprint and unrelated producer terminal pulses
  cannot settle an owner.
- No terminal, conflict or global-reset bar may adopt, enter, reverse, or emit a
  second outward marker.

The v1 host deliberately does not implement reviewer-proposed replacement. That
would add another trading policy before owner starvation has been measured. The
later 30/90-day review must count opportunities suppressed or missed by this
choice; it may not silently change the live rule.

## 7. Confirmed-bar event priority

Each 3m timestamp can produce at most one outward event, one marker and one
alert. Apply this order:

```text
unconfirmed bar -> no state advancement
invalid global host / symbol / timeframe / clock / OHLC / EMA,
backward time or disallowed gap -> fail-closed owner reset, no price terminal
exact duplicate timestamp -> no-op after host/data validation
advance both adapters once for a newly eligible completed 10m timestamp
existing owner stop
existing owner target
exact-bound producer INVALIDATED
exact-bound producer TARGET_REACHED
entered owner retention and suppression of new candidates
unentered owner exact producer EXPIRED, lane-source/permission/context validity,
then timing policy
pre-adoption overlap/adoption-bar terminal checks
new candidate arbitration and adoption-only
advisory/UI projection
```

Lane source/ATR/target/permission expiry ends only an unentered owner. It cannot
evict an entered frozen plan. A global data reset may end an entered owner but
must not fabricate `失效` or `达标`; the suppression ledger survives the reset.

Producer terminal handling is closed, not extensible by inference:

- For either unentered or entered owners, only exact lane/opportunity/fingerprint
  `INVALIDATED` and `TARGET_REACHED` pulses may settle the owner. Invalidation
  remains before target.
- An exact `EXPIRED` pulse may end an unentered owner only. An entered owner
  ignores producer `EXPIRED`.
- An entered owner also ignores producer/lane `ACTIVE=None`, permission expiry,
  context expiry, source/ATR/target validity or identity drift, `SUPPRESSED`,
  lane `CONTEXT_RESET`, lane `DATA_RESET`, and any newer plan.
- A raw shared-transport host/clock/OHLC backward/gap failure is a global reset,
  not a lane producer terminal, and may fail closed an entered owner without a
  price-terminal marker.
- An unentered owner whose frozen source/ATR/target identity is missing, stale,
  invalid or no longer permitted ends before timing; it cannot emit entry on the
  same bar.

## 8. Trader-visible surface

Default chart output is intentionally sparse:

- one large bar-anchored `多入` or `空入` marker only when an entry pulse fires;
- terminal markers hidden by default;
- no dynamic `label`, `line`, or `box` objects;
- any plotted plan levels use price-series plots, so pan/zoom cannot detach them;
- no internal state abbreviations such as `多续`, `空退`, `READY`, `LOCKED`, IDs,
  hashes or protocol versions on the chart.

The fixed five-row dark-mode card is:

```text
现在做  等待 / 多入触发 / 空入触发 / 冲突不做 / 本计划结束
来源    10m 趋势续行 / 10m 位置反转
为什么  confirmed 3m 触发与 5/12 条件；或当前仍缺什么
保护    frozen invalidation
目标    frozen target 与 entry-time remaining R
```

Text and background colors must be explicit and readable on a black chart.

Selectable alerts are exactly four entry-only conditions:

```text
3m | 趋势续行 | 多入
3m | 趋势续行 | 空入
3m | 位置反转 | 多入
3m | 位置反转 | 空入
```

They fire only from the OwnerManager entry pulse, Once Per Bar Close. Message
content includes symbol, 3m interval, lane, 10m opportunity/confirmation time,
confirmed 3m bar time, observed entry close, frozen stop/target, entry-time R,
and `条件提醒，不是订单`. Terminal state updates the card/Data Window only in v1.

## 9. Required implementation files

New:

```text
idm_phase1_3m_global_owner_v1.pine
research/generate_phase1_3m_global_owner_pine_v1.py
research/phase1_3m_global_owner_oracle.py
research/tests/fixture_phase1_3m_global_owner.py
research/tests/test_phase1_3m_global_owner_contract.py
research/tests/test_phase1_3m_global_owner_transport.py
research/tests/test_phase1_3m_global_owner_timing.py
research/tests/test_phase1_3m_global_owner_arbitration_lifecycle.py
```

Existing producer generators may expose canonical embedded-core renderers only
if their standalone generated Pine remains byte-identical. Do not copy two
generated monoliths or use regex rewriting to create a third producer version.

Frozen artifacts must remain byte-identical:

```text
5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421  idm_phase1_10m_position_reversal_v1.pine
aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2  idm_phase1_10m_primary_opportunity_v3.pine
f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e  idm_phase1_3m_opportunity_timing_v3.pine
```

Any synthetic fixture whose name implies a real July 31 11:40 long positive must
be renamed. The real producer output at that time cannot be manually overridden.

## 10. Required offline gates

1. Existing reversal 132-test suite remains green.
2. Complete R3.2 suite remains collectable and green.
3. All three frozen Pine SHA-256 values remain unchanged.
4. New generator output is byte-identical to committed global Pine.
5. Static contract proves one HTF request, uniform `[1]`, `lookahead_on`, no
   realtime branch, no prohibited transport primitive, four alerts and sparse
   plot surface.
6. Transport tests cover 09:39/09:42 and 11:39/11:42, pending visibility,
   duplicate 10m values, forming values, wrong host, backward time and gaps.
7. Timing tests cover synthetic trend and reversal long/short; immediate-confirm
   pass/fail; equality selecting fresh-cross; first-cross pass/fail; no second
   cross; exact `1.000R`; sub-1R; stop/target before entry; stop-first; permission
   and context expiry; exact three-minute continuity; equality-at-expiry; and
   expiry/terminal plus cross on the same bar.
8. Arbitration/lifecycle tests cover no replacement, no queue, full suppression,
   persistent base-ID collision tombstones including a third fingerprint,
   same-direction order, exact tie, opposite conflict, entered retention, exact
   producer-terminal allowlist, ignored entered-owner lane expiry/reset events,
   terminal-bar candidate suppression, no adoption and one outward event per bar.
9. The real 2026-07-31 approximately 11:40 chain remains end-to-end negative:
   `<1R` producer output means no envelope, no adoption, no later entry.
10. Full repository test gate and Python compilation pass using the repository
    virtual environment.

Transport/timing fixtures must also cover a payload whose overlap or adoption
bar already touches stop, target, or both. Expected result is suppression with
no adoption, using lane-specific stop semantics and stop-first ordering.

## 11. Required TradingView and Trader gates

TradingView online acceptance must use `CAPITALCOM:SPX500`, standard 3m:

- clean compile, remove/re-add, reload and Replay;
- verify only one completed-10m transport exists;
- inspect 09:40->09:42 and 11:40->11:42 visibility bar by bar;
- adoption bar never marks entry; only the strictly later confirmed bar can;
- actual July 31 approximately 11:40 remains no-plan/no-entry;
- compare lane, identity, source/visible times, stop, target, owner and outward
  pulse before/after reload and Replay;
- verify dark text contrast, fixed five-row card, price anchoring, pan/zoom,
  marker density, plot count and compiled-resource budget;
- create the four selectable alerts only after source/input identity is checked;
  any later source/input change requires deleting and rebuilding alert snapshots.

Trader review then walks the available 3m/10m history without hiding future
bars and records, per opportunity: what was known, whether an alert existed,
why it entered or refused, stop/target, subsequent MFE/MAE, useful/late/missed/
wrong-side classification, and the cost of no-replacement/no-queue. Offline and
visual review cannot be called a fill, phone delivery, live execution, 30/90-day
edge or profitability proof.

## 12. Current evidence boundary

Accepted today:

- architecture and event contracts were independently reviewed;
- Pro corrected its HTF recommendation to match current TradingView guidance;
- Pro and the independent reviewer agree on the two one-shot reversal branches;
- global no-replacement/no-queue, lane-specific stop semantics and July 31
  negative boundary are frozen.
- the final independent contract review found no P0 and required four P1
  clarifications; overlap/adoption terminal checks, exact continuity/expiry,
  base-ID collision tombstones and a closed producer-terminal allowlist are now
  incorporated above.

Not yet accepted:

- global-host source code;
- combined Pine compilation and historical/Replay/live parity;
- actual entry markers or alert instances;
- phone delivery, orders, fills, slippage-adjusted results or profitability.

Official references:

- <https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/>
- <https://www.tradingview.com/pine-script-docs/writing/limitations/>
- <https://www.tradingview.com/pine-script-docs/faq/alerts/>
