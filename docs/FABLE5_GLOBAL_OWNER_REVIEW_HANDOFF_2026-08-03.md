# Fable 5 review handoff — IDM 10m/3m global owner candidate

Date: 2026-08-03
Review branch: `codex/fable5-global-owner-review`
Package baseline: `0fe6faa529832cc36fc8ec377ce2620e8ed9b388`
Status: **FAIL / REVISE — public review candidate only; not installed in TradingView**

## 1. Product goal

Build a trader-facing SPX decision aid based on the user's Ripster/SATy workflow without mixing every idea into one unreadable indicator:

1. 10m determines the larger setup: trend continuation or reaction/reversal at a named location.
2. 3m confirms timing and owns at most one active plan.
3. The chart should show only a small number of actionable states with a clear reason, invalidation, target and do-not-chase boundary.
4. A valid signal must be anchored to price and bar time, use completed higher-timeframe data, and remain stable when the chart is panned or zoomed.
5. Alerts are decision support only; there are no orders, webhooks or profitability claims.

The intended fast Ripster cloud is EMA 5/12. EMA 21/48 is slower 10m context inside the trend producer; it is not intended to replace the 5/12 cloud. The current global chart surface displays the 3m EMA 5/12 pair.

## 2. What this branch contains

The candidate combines two independent 10m producers with one 3m owner:

- `TREND_CONTINUATION`: direction, trigger, invalidation, target and space are frozen from a previous-completed 10m plan.
- `POSITION_REVERSAL`: a named support/resistance or SATy ATR-map location must react and confirm; it is not a break-then-reverse rule.
- `GlobalOwnerHost`: consumes one previous-completed 10m transport, arbitrates conflicts, and permits one 3m owner.
- TradingView surface: two entry markers (`多入` / `空入`), four entry-only alerts, a fixed five-line decision card, 3m EMA 5/12, and frozen protection/target lines. There are no dynamic labels, boxes or lines.

Primary implementation files:

- `idm_phase1_3m_global_owner_v1.pine`
- `research/phase1_3m_global_owner_oracle.py`
- `research/generate_phase1_3m_global_owner_pine_v1.py`
- `research/tests/test_phase1_3m_global_owner_*.py`
- `docs/CHATGPT_PRO_PHASE1_3M_GLOBAL_OWNER_IMPLEMENTATION_REPORT_2026-08-02.md`

## 3. Current distance from the real goal

### 3.1 The live chart is still the old system

This candidate has not passed final review and has not been installed in TradingView. Any current TradingView labels, “观察” text or old levels are not evidence that this branch works online.

### 3.2 Named ATR/support/resistance data is not live

The position-reversal producer currently accepts explicit source metadata, values and validity windows. It does not fetch the current SATy ATR map automatically. A level such as 7499 can therefore remain visible after price has moved above 7530 if the old indicator/input snapshot is still on the chart. This is a product failure, not a meaningful current resistance call.

A production design must choose one honest update path:

- a small daily/manual publish flow with visible source time and hard expiry; or
- a companion service/app that updates validated levels and disables dependent conclusions when data is unavailable.

Silent stale fallback must not be allowed.

### 3.3 The tool is not yet a real-time trading companion

The current candidate focuses on confirmed entry events and lifecycle correctness. It does not yet provide a reliable current-market answer such as:

- where price is relative to the current 10m cloud and named levels;
- whether to wait, prepare, enter, reduce risk or invalidate;
- what evidence is present now (cloud hold/reject, ATR reaction, divergence, VIX confirmation);
- which evidence is missing and what exact event would change the decision.

### 3.4 VIX, divergence and live context are not integrated

VIX support/resistance, 3m oscillator/MACD divergence, session high/low and event context are not part of this global owner candidate. They should not be added until the minimal 10m/3m path is accepted, but the product gap must remain visible.

### 3.5 There is no 30/90-day edge validation

The public test data proves state-machine behavior only. Private TradingView fixtures are not distributed and are skipped. There is no completed 30- or 90-day bar-by-bar trader review demonstrating useful entries, exits, false positives, R distribution or profitability.

## 4. Known blocking defects in this exact candidate

Independent adversarial review result: **P0=0, P1=1, P2=2**.

### P1 — a host-bound manager remains publicly mutable

`GlobalOwnerHost.manager` is a read-only property, but it returns the full mutable `OwnerManager`. A caller can invoke `host.manager.ingest(...)` without the canonical host transaction when no transport outcome is supplied.

Two confirmed consequences:

1. A candidate can become a 3m owner without passing through the completed-10m transport.
2. Direct manager calls at 10:06 and 10:09 can advance the clock so that a real 10:03-to-10:12 data gap is treated as continuous; a 10:12 reversal payload is then delivered and adopted instead of producing `DATA_GAP_RESET`.

Required invariant: standalone, unbound `OwnerManager` may retain its direct test/research API, but once bound to `GlobalOwnerHost`, every mutation path must require host authority or the public host must expose only an immutable manager audit view.

### P2 — failed host construction is not atomic

Constructing a host with a fresh manager and an already-bound transport fails after the fresh manager has already been bound to an orphan authority. A failed constructor must leave both supplied components reusable and unchanged.

### P2 — invalid payload type mutates state before failure

`process_bar(..., completed_ten_minute_payload="not-a-payload")` raises `TypeError` only after staging the bad value, setting `raw_snapshot_dirty`, and issuing an authority record. Type validation must occur before any staging, nonce or permit mutation.

## 5. What has passed

The three earlier public API defects are closed:

- forged public consumer decisions cannot mutate transport;
- `host.manager` / `host.transport` cannot be rebound;
- public assignment to observed/consumed audit clocks fails, and the next continuous 10m payload still delivers.

Independent offline results on this exact branch before this handoff:

```text
focused transport      44 passed
global owner          111 passed
position reversal     132 passed
10m primary            81 passed, 4 skipped
full repository       415 passed, 11 skipped, 1 failed
```

The one full-repository failure is an older public-release check: 15 baseline documents contain local absolute paths. This branch did not add those files, but the repository gate is objectively not all green.

Frozen Pine evidence:

```text
position reversal  5beaa2827e73449a83e73f13c52fd1cf82529340e63d970f03a45f515419b421
10m primary        aa00d266964bd2cc6f8ac2776eb4ffe06e8966d5ce93b9a439d4139bfac8aeb2
3m timing          f0ec01d812a3663e4fe3f5ab3d4c8675a238100f91d3046c11e412c35563b76e
global owner       6b5ff2adbbee10dd1f53554bf9ca8d917debd9bcf7c9e8e0b6efbcbef11bf6c8
```

Global Pine static surface:

```text
request.security  1
plotshape         2
alertcondition    4
label.new         0
line.new          0
box.new           0
```

## 6. Main diagnosis

The work over-invested in defensive transport/owner correctness before closing the user-visible loop. Each review found another mutable Python API seam, while the live product still used stale manual levels and an older chart script. This produced a technically elaborate but trader-incomplete result.

The next implementation should not add more indicators. It should first simplify ownership boundaries and define one observable, live MVP:

1. one honest source-of-truth policy for current levels;
2. one 10m decision with reason/invalidation/target;
3. one 3m confirmation or explicit wait state;
4. one concise chart card and at most two entry markers;
5. a small historical casebook with positives, false positives and missed opportunities.

## 7. Questions for Fable 5

Please review the actual code rather than assuming the current architecture is correct.

1. Is the global owner abstraction worth keeping, or should the Python oracle and Pine implementation be simplified around immutable snapshots and a single pure transition function?
2. What is the smallest fix for the P1/P2 defects that mechanically prevents all non-host mutation without adding another capability layer?
3. Should current SATy ATR/named levels remain explicit daily inputs with expiry, or does the product require a companion service before it can be called useful?
4. Which current states should be removed so a trader sees only actionable information?
5. What exact 30-day bar-by-bar acceptance sample would distinguish a useful warning/entry system from hindsight labeling?
6. What should be the next single milestone, with explicit stop conditions, before any VIX/divergence/AI expansion?

## 8. Boundaries

- This branch is a public review snapshot, not an accepted release.
- It has not passed TradingView cloud compilation, remove/re-add, reload, pan/zoom, Replay or live alert delivery.
- It does not prove trading edge, win rate, P&L or suitability for live orders.
- No push to `main`, PR, deployment, webhook, broker or order action is included.
