# ChatGPT Pro preimplementation review: POSITION_REVERSAL 10m → 3m

Date: 2026-08-02

Conversation: <https://chatgpt.com/c/6a6fe94a-415c-83e8-8be7-8176004b626c>

Package baseline: `a4aa41466da38a32287c93a6ca155f85ea146fad`

Package SHA-256:
`dbd2fcd99aa4e228e93f9058fc2ee64670a6470f95395a3dd214521ed17429a6`

External verdict: **REVISE**

Status of this document: external evidence only. Codex has not accepted every
recommendation; the HTF transport and reversal chase policy are under a targeted
follow-up review.

## A. Why Pro returned REVISE

Pro found five implementation blockers:

1. The frozen global-owner contract says an adopted unentered plan cannot be
   replaced, while the existing R3.2 Pine and Python timing engine implement a
   `REPLACED` path.
2. The two lanes have different accepted stop semantics:
   - `TREND_CONTINUATION`: confirmed-close stop breach;
   - `POSITION_REVERSAL`: high/low stop touch.
3. A lane source/ATR/target/permission failure must end only an unentered plan;
   it must not evict an entered owner whose stop and target are frozen.
4. Candidates observed behind an existing owner cannot be queued and revived
   after that owner ends.
5. A synthetic July 31 long fixture is still named as a required real replay
   positive even though the accepted real 11:40 state was `<1R`, with no ACTIVE
   plan.

## Reproduced package evidence

Pro reported:

- ZIP size: 165,245 bytes;
- SHA-256 matched;
- ZIP comment matched the package baseline;
- 34 entries; CRC, path traversal, symlink and encryption checks passed;
- reversal generator/Pine byte parity passed;
- reversal targeted tests: 132 passed;
- independently collectable R3.2 lifecycle/space/causality tests: 54 passed;
- `compileall research`: passed;
- the three Pine hashes matched the v1.4 acceptance record.

The review package omitted the trend generator and private replay loader, so Pro
could not independently reproduce the handoff's full `1094 passed, 130 skipped`
claim. The package also did not contain the local TradingView screenshots cited
by the v1.4 acceptance report.

Pro did not run TradingView, a live market, phone delivery, orders, fills, or a
profitability test.

## B. Recommended production topology

Pro rejected separate production indicators joined by `input.source`. It
recommended one 3m host:

```text
one completed-10m raw transport
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

The two detectors remain independent. They do not vote, combine confidence, or
read state from another chart instance. A narrow envelope/manager interface is
used inside this host; this step must not become a generic plugin framework.

## Minimum immutable PlanEnvelope

Pro proposed:

```text
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

`payload_fingerprint` covers lane, identity, direction, geometry, source context
and times. Timing state, adopted/entered times, actual entry, and suppression are
mutable OwnerManager state, not envelope fields.

At entry, the manager recomputes actual remaining R from the confirmed 3m close:

```text
long:  risk = close - stop; reward = target - close
short: risk = stop - close; reward = close - target
require finite risk/reward, risk > 0, reward > 0, reward/risk >= 1.0
```

The equality boundary `1.000R` passes.

## Fixed lane policies

| Policy | TREND_CONTINUATION | POSITION_REVERSAL |
|---|---|---|
| after adoption | `WAIT_PULLBACK` | `WAIT_TRIGGER` |
| trigger | later pullback bar high/low | frozen 10m reaction trigger |
| EMA | retain R3.2 predicate | EMA5/12 directional relation |
| fresh crossover | no | Pro initially said no |
| stop | confirmed close breach | high/low touch |
| target | high/low touch | high/low touch |
| stop plus target same bar | stop-first | stop-first |

Pro also said reversal must not inherit trend's second pullback or extra fast-cloud
close condition without a separate reviewed trading contract.

## Owner invariants accepted in principle

- One adopted or entered owner at a time.
- Adoption bar never enters.
- Owner copies and freezes the whole envelope.
- An adopted unentered owner is not replaced in the v1 host.
- An entered owner survives producer/source/permission expiry and new plans.
- No queue: blocked plans and arbitration losers cannot revive later.
- Same-direction candidates choose earlier `visible_at`; an exact tie chooses
  trend first. Opposite-direction candidates conflict and choose neither.
- Loser/conflict identities are suppressed.
- Terminal pulses must match lane, opportunity ID, and payload fingerprint.
- Terminal/conflict bars cannot adopt, enter, reverse, or emit a second marker.
- UI, alert and Data Window consume only OwnerManager outward pulses.

## C. Priority order

Pro recommended this per-confirmed-3m-bar order:

1. Unconfirmed bar: no state advancement.
2. Invalid host/symbol/timeframe/chart/OHLC/EMA, backward time or gap: global
   fail-closed reset and suppress current owner.
3. Exact duplicate timestamp: no-op after host/data checks.
4. Advance both adapters at most once for a newly completed 10m timestamp.
5. Existing-owner stop, then target.
6. Entered owner retention; suppress new candidates.
7. Adopted unentered owner permission/context/timing checks.
8. Trend `WAIT_PULLBACK`, then later `WAIT_TRIGGER`; reversal uses its own timing
   policy.
9. A valid trigger with `<1R` becomes `MISSED/LOCKED`; it cannot wait for price
   to improve.
10. With no owner, arbitrate candidates; adoption only.
11. WATCH/advisory/UI updates occur last and never affect ownership.

Global host/clock/OHLC failure is distinct from lane-source expiry. Only the
former may fail closed an entered owner without fabricating a price terminal.

## D. Minimum proposed files

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

Minimal generator changes may expose canonical embedded producer fragments, but
the generated standalone Pine bytes and hashes must remain unchanged. The three
accepted standalone Pine files remain frozen regression references.

The fixture/test currently named as a real July 31 positive must be renamed as
synthetic. No test may inject a plan into the real 11:40 `<1R` case.

## E. Required gates

Offline:

- reversal 132 remain green;
- complete R3.2 suite remains collectable and green;
- three frozen Pine hashes unchanged;
- global generator/Pine byte parity;
- completed-10m visibility and duplicate advancement tests;
- synthetic reversal long/short and trend non-regression;
- exact `1.000R` pass and `0.999...R` fail;
- stop/target pre-entry and stop-first cases;
- no replacement/no queue/conflict/suppression tests;
- exact terminal identity binding;
- no terminal-bar adoption/reversal;
- one outward event/marker/alert per bar;
- end-to-end real July 31 11:40 adapter output `None` and no later entry.

TradingView online, not performed by Pro:

- `CAPITALCOM:SPX500`, standard 3m, clean compile and remove/re-add;
- inspect 09:40 → 09:42 and 11:40 → 11:42 visibility bar by bar;
- adoption bar no entry; only a strictly later confirmed bar may mark entry;
- actual July 31 11:40 remains no-plan/no-entry;
- compare lane, fingerprint, times, stop/target, owner and pulse across reload,
  Replay and live;
- dark mode, pan/zoom, price anchoring, five-row card, one marker per bar;
- verify Pine plot, request and compiled-size budgets;
- rebuild alerts after any source/input snapshot update.

## Alert recommendation

Pro proposed four selectable entry-only conditions:

```text
3m | trend continuation | long entry
3m | trend continuation | short entry
3m | position reversal | long entry
3m | position reversal | short entry
```

Each is Once Per Bar Close and carries symbol, interval, 10m confirmation time,
3m bar time, lane, entry close, frozen stop/target, remaining R, and the statement
that it is a condition alert, not an order. Terminal state updates the card/Data
Window by default and does not create a selectable alert in v1.

## G. Unverified risks explicitly retained

- A reversal trigger may still be late or extended.
- No-queue intentionally misses some later opportunities; the cost is unknown.
- OHLC cannot recover intrabar stop/target/trigger order; stop-first is
  conservative.
- Different lane stop semantics make raw outcome counts incomparable.
- Confirmed close is not a fill price and excludes spread/slippage.
- EMA5/12 is a timing relation, not a second vote or confidence score.
- Standalone 10m and global 3m input/alert snapshots can drift operationally.
- Public evidence has no real causal reversal positive chain yet.
- Combined Pine compile/runtime and historical/live parity are unverified.
- Phone delivery, orders, fills and profitability are unverified.

## Codex follow-up sent to Pro

Codex requested a correction on two points:

1. Pro initially recommended the legacy `lookahead_off` dual-offset transport,
   while current official TradingView documentation recommends an offset HTF
   expression (`[1]`) with `barmerge.lookahead_on` for confirmed non-repainting
   historical/realtime behavior.
2. Pro's open-ended reversal state condition could wait for most of a two-hour
   producer permission and then chase. Codex requested a bounded, non-arbitrary
   first-legal-bar/fresh-cross rule or another explicit chase gate.

## Targeted correction returned by Pro

Pro accepted both corrections after a second official-document review.

### HTF transport

Pro withdrew the legacy R3.2 dual-offset plus `lookahead_off` recommendation.
The new global host must use one canonical higher-timeframe request in which
every transported 10m expression field is offset inside the 10m context with
`[1]`, together with `barmerge.lookahead_on` and `barmerge.gaps_off`. It must not
branch on `barstate.isrealtime`, mix offsets, or offset the returned 3m series.

The transport also needs an explicit consumer gate:

```text
payload.visible_at_ms <= current_3m_bar_open_time
AND payload.source_time != last_consumed_10m_source_time
```

The consumed identity advances only after that gate succeeds. Thus a 10m bar
whose `time_close` is 11:40 cannot be adopted by the overlapping 11:39–11:42
3m bar. The 11:42 bar is the first eligible adoption bar; if state transitions
are committed on confirmed 3m bars, adoption commits when that bar confirms, and
the adoption bar remains permanently entry-ineligible.

### Reversal late/chase control

Pro accepted the independent reviewer's two one-shot branches. The branch is
frozen from the confirmed adoption bar and can never switch later:

- Long adoption close above trigger, or short adoption close below trigger:
  `WAIT_IMMEDIATE_CONFIRM`.
- Otherwise, including equality: `WAIT_FRESH_CROSS`.

`WAIT_IMMEDIATE_CONFIRM` allows only the immediately following continuous,
confirmed 3m bar. Long requires close above trigger, close no higher than the
frozen adoption high, and EMA5 above EMA12. Short is mirrored against the frozen
adoption low. The same bar must also pass stop-first/target, finite geometry and
entry-time remaining `R >= 1.0`. Any failure becomes `MISSED`; there is no later
retry and no fallback to the fresh-cross branch.

`WAIT_FRESH_CROSS` waits only for the first discrete confirmed-close cross after
adoption:

```text
long:  previous close <= trigger and current close > trigger
short: previous close >= trigger and current close < trigger
```

That first cross must also pass EMA direction, stop-first/target, finite geometry
and remaining `R >= 1.0`. If it fails, the plan becomes `MISSED`; a second cross
cannot enter. If permission or context validity ends first, it becomes `EXPIRED`.

This correction was architecture/contract review only. Pro still did not write
the global-host code, run TradingView, validate phone delivery, place an order,
or establish profitability.

The final implementation contract must incorporate the correction response; this
first response alone is not implementation approval.
