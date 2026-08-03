# ChatGPT Pro implementation handoff: Phase 1 3m global owner v1

Date: 2026-08-02

Repository: `git@github.com:xjtuyanshi/idm-tradingview-research.git`

Implementation baseline: `c15f542`

Authority: local implementation and offline tests only. No push, PR, deployment,
webhook, order, strategy execution, phone-delivery claim, or profitability claim.

## 1. Background and goal

Two native SPX500 10m producer lanes already exist:

- `TREND_CONTINUATION`: accepted R3.2 slow-trend plus pullback/reclaim producer;
- `POSITION_REVERSAL`: accepted v1.4 prior-published named-position plus confirmed
  reaction producer.

The trader does not want more independent 3m labels. The next deliverable is one
production 3m decision host that consumes both lanes, owns exactly one plan,
shows only a clear `多入` or `空入` entry marker, explains the current state in
a five-row dark-mode card, and exposes four lane-by-direction entry alerts.

The controlling contract is:

```text
docs/CODEX_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_FREEZE_2026-08-02.md
```

Read that file completely before coding. It supersedes older conflicting owner,
HTF-transport, July 31 positive, and open-ended reversal-timing text.

## 2. Accepted architecture

Implement one deployable 3m Pine host:

```text
one previous-completed 10m raw superset transport
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

The two producer engines remain independent. They do not vote, add confidence,
read another indicator instance, or share detector state. They meet only through
the frozen `PlanEnvelope` and `OwnerManager` contract.

Do not create a generic plugin framework. Use the smallest explicit code that
keeps the two lane policies separate and testable.

## 3. Non-negotiable boundaries

### Frozen existing artifacts

These files must remain byte-identical:

```text
5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421  idm_phase1_10m_position_reversal_v1.pine
aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2  idm_phase1_10m_primary_opportunity_v3.pine
f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e  idm_phase1_3m_opportunity_timing_v3.pine
```

If an existing generator needs an embedded-core renderer, its current standalone
render must remain byte-identical. Do not patch generated Pine by regex, paste
two monoliths into a third file, or create a second copy of producer truth.

### Scope exclusions

Do not add or modify:

- VIX, MACD, divergence, oscillator, AI score or confidence voting;
- 21/48 or 5/12 trading semantics inside the accepted producers;
- new position sources, target routing or stop geometry;
- strategy/order/webhook/broker code;
- dynamic `label`, `line` or `box` objects;
- a second production 3m lane indicator or `input.source` bridge;
- any real July 31 11:40 long plan that the producer did not publish.

## 4. Required HTF transport

Use exactly one canonical `request.security()` raw superset transport for both
adapters. Every 10m expression field is offset inside the HTF context with
`[1]`, with `barmerge.gaps_off` and `barmerge.lookahead_on`.

Forbidden transport constructs include:

- unoffset `lookahead_on`;
- `lookahead_off` realtime/historical dual-offset logic;
- `barstate.isrealtime` offset switching;
- offsetting returned 3m series;
- forming 10m data, `input.source`, `timenow`, `varip`, or UI state;
- separate requests that let trend and reversal observe different source times.

The consumer advances both adapters only after:

```text
payload.visible_at_ms <= confirmed_3m_bar_open_ms
AND payload.source_time != last_consumed_10m_source_time
```

Do not advance last-consumed state while visibility fails. Cover non-divisible
10m/3m boundaries: 09:40 data cannot be adopted on the 09:39 bar; 09:42 is the
first eligible adoption bar. Repeat the same test for 11:40/11:42.

Before arbitration, fail closed if the overlap or adoption bar has already
terminated the candidate. Use confirmed-close stop for trend, touch stop for
reversal, touch target for both, and stop-first. Whole-overlap OHLC is a
deliberately conservative check.

## 5. Required timing and ownership

Preserve trend R3.2 timing exactly:

```text
WAIT_PULLBACK -> pullback freezes 3m trigger -> WAIT_TRIGGER
```

Preserve its current EMA/cloud predicate, eight-bar trigger lifetime,
confirmed-close stop and target-touch policy.

Position reversal uses only the two frozen one-shot branches:

- adoption already beyond trigger -> `WAIT_IMMEDIATE_CONFIRM`;
- adoption on safe side or exactly at trigger -> `WAIT_FRESH_CROSS`.

Immediate confirm allows only the exactly next continuous 3m bar
(`open_ms == adoption_open_ms + 180000`). Long must remain above trigger, close
no higher than adoption high and have EMA5 > EMA12; short is mirrored. Failure
is final `MISSED`.

Fresh cross accepts only the first discrete post-adoption close-cross event.
That bar must pass EMA direction, stop-first/target checks, finite geometry and
remaining `R >= 1.0`; failure is final `MISSED`, not a wait for recross.

Strict validity:

```text
bar_open_ms < permission_expires_at_ms
context absent OR bar_close_ms < context_valid_until_ms
```

Equality is expired. Expiry/terminal on the same bar precedes entry.

Implement one owner, no replacement and no queue. Include:

- full-identity suppression;
- persistent `(lane_id, opportunity_id)` fingerprint registry and collision
  tombstone so a third fingerprint cannot escape;
- same-direction earlier-visible arbitration, exact tie trend-first;
- opposite-direction conflict suppressing both;
- terminal/conflict/reset-bar candidate suppression;
- exact producer-terminal allowlist from the freeze document;
- entered-owner retention through lane expiry, source drift, `ACTIVE=None`,
  lane resets and newer plans;
- one outward event/marker/alert per confirmed 3m bar.

## 6. Trader-visible UI and alerts

Default chart surface:

- one large bar-anchored `多入` or `空入` only on an entry pulse;
- no watch/continue/retreat/close shorthand markers;
- terminal markers hidden by default;
- plan-price series may be plotted, but no detachable objects;
- explicit high-contrast colors for black background.

Fixed five-row card:

```text
现在做  等待 / 多入触发 / 空入触发 / 冲突不做 / 本计划结束
来源    10m 趋势续行 / 10m 位置反转
为什么  当前已满足什么、还缺什么
保护    frozen invalidation
目标    frozen target 与 entry-time remaining R
```

Exactly four selectable `alertcondition()` entry conditions:

```text
3m | 趋势续行 | 多入
3m | 趋势续行 | 空入
3m | 位置反转 | 多入
3m | 位置反转 | 空入
```

Each must be bar-close-only and include the frozen contract fields available
through Pine placeholders, plus `条件提醒，不是订单`. No selectable terminal
alerts in v1.

## 7. Required deliverables

New files:

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

Minimal existing-generator edits are allowed only if required to expose a
canonical embedded core and if all frozen standalone bytes stay unchanged.

Return all of:

1. A downloadable ZIP containing complete changed/new files at repository paths,
   not partial snippets.
2. A unified diff against package baseline.
3. `SHA256SUMS.txt` for every delivered file and the delivery ZIP.
4. A concise implementation report mapping every freeze section to source/tests.
5. Exact commands and unedited summaries for every test you actually ran.
6. Explicit list of anything not run or not verified.

If the interface cannot attach a ZIP, provide complete files in deterministic
chunks plus hashes; do not omit generated Pine due length.

## 8. Mandatory offline tests

Run at minimum:

```text
PYTHONPATH=. python -m pytest -q research/tests/test_phase1_10m_position_reversal_*.py
PYTHONPATH=. python -m pytest -q -rs research/tests/test_phase1_10m_primary_opportunity_*.py
python research/generate_phase1_10m_position_reversal_pine_v1.py --check
python research/generate_phase1_10m_primary_pine_r3.py --check
python research/generate_phase1_3m_global_owner_pine_v1.py --check
python -m compileall -q research
```

Also run all new global-owner tests and the complete collectable repository test
suite available inside the package. Do not count explicit private-fixture skips
as passes and do not claim files omitted from the package were tested.

The new tests must cover every item in freeze sections 10 and 11, especially:

- HTF uniform offset/lookahead and single-request static contract;
- 09:39/09:42 and 11:39/11:42 visibility;
- overlap/adoption terminal suppression;
- immediate-confirm and fresh-cross one-shot branches;
- exact continuity, equality-at-expiry, expiry-plus-cross;
- exact `1R` and sub-1R;
- no replacement/no queue and third-fingerprint tombstone;
- producer-terminal allowlist and entered-owner ignored events;
- terminal-bar candidate suppression;
- real July 31 11:40 `<1R` end-to-end no-envelope/no-entry;
- old Pine hashes and new generator/Pine byte parity.

## 9. Acceptance criteria

Codex will accept the delivery only if:

- every freeze invariant is directly represented by readable code and tests;
- generated Pine is canonical and compiles later in TradingView without source
  rewrites;
- the three old Pine hashes are unchanged;
- no prohibited construct, hidden fallback, mock-to-live claim or dependency is
  introduced;
- tests pass in an isolated worktree;
- independent review finds no P0/P1;
- TradingView clean compile, remove/re-add, Replay/reload parity, pan/zoom,
  dark-mode readability, sparse markers and four alert conditions pass;
- actual TradingView screenshots and durable evidence are saved by Codex.

Offline tests are not TradingView online acceptance, phone delivery, fill
validation, 30/90-day edge or profitability evidence.

## 10. Prohibited actions and claims

Do not push, create a PR, deploy, configure TradingView alerts, send a webhook,
place or simulate an order, alter live configuration, or access real user data.
Do not claim TradingView compilation, Replay/live parity, phone delivery, fills,
win rate, edge or profitability unless you actually performed the specific gate;
this package does not authorize those external operations.

Do not overwrite unrelated working-tree changes. Your delivery is advisory until
Codex independently applies, reviews and tests it.
