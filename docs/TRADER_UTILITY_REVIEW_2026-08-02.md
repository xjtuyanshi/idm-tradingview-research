# IDM Trader Utility Review — 2026-08-02

## Verdict

**Accepted for the source/offline trader-facing contract; not yet accepted for the
TradingView online visual gate or live performance.** The old chart language was
not suitable as a live trader compass. R3.1 now implements the reduced language
and owner lifecycle described below without changing the canonical signal engine
or its thresholds. This remains a causal UI and decision review, not a
profitability claim.

Two independent reviews were used:

- ChatGPT Pro verdict: **partially useful**. It accepted the R3 10m-plan/3m-entry
  responsibility split and rejected ownerless `关多/关空/多头退/空头退` as
  standalone chart signals. Full report:
  `docs/CHATGPT_PRO_TRADER_UTILITY_REVIEW_2026-08-02.md`.
- A separate causal trader reviewer returned **ACCEPT for source/offline contract**
  after the final long/short WATCH invalidation-language correction. That reviewer
  explicitly did not accept TradingView online compile, actual-chart readability,
  or live forward performance. Durable verdict:
  `docs/INDEPENDENT_TRADER_REVIEW_2026-08-02.md`.

## Evidence boundary

- Old P6/R4/R5.1 export: 11,815 real 3-minute bars, 2026-06-28 18:00 through
  2026-07-31 16:57 ET, covering 30 ET dates.
- Current R3 export: 337 real 10-minute bars from 2026-07-29 through 2026-07-31.
  It contains only two 10m main opportunities and two linked 3m entries.
- There is no current-R3 30-day or 90-day export. Therefore this review does not
  claim three-month coverage, win rate, profitability, or live alert reliability.
- Event annotations use the earliest closed-bar time when the event could have
  been known. MFE/MAE are SPX points and exclude spread, slippage, option pricing,
  and execution.

## Trader rubric

A marker belongs on the default main chart only if it changes a trader's action and
answers these questions at the time it becomes known:

1. Is this observation, entry permission, entry timing, or management of an
   already-owned plan?
2. What is the trigger?
3. What invalidates it?
4. What is the target?
5. When is it first actionable after the bar closes?
6. Which visible plan owns a later invalidation or target marker?

Anything that does not change an action belongs in the current-state card or Data
Window, not in historical marker clutter.

## Hard lifecycle defect

The old default chart emitted 223 `趋势多`, 144 `趋势空`, 253 `多头退`,
154 `空头退`, and 431 direction-conflict events over the 33-day export. The
densest ET date contained 72 events. That volume is state-machine telemetry, not
a phone-readable trader compass.

The 33-day old export contains 431 inferred active plan runs. Only 336 began with a
visible entry marker. Ninety-five began without one, and 91 of those hidden plans
later printed a visible `多头退` or `空头退` marker.

That means a trader could receive an exit for a position the main chart never told
them to own. This is a lifecycle/UI defect, not merely a naming preference. Old
`关多/关空/多头退/空头退` semantics must not remain on the default chart.

## Marker decision

- 10m history: retain only `多计划` and `空计划`.
- 3m history: retain only `多入`, `空入`, `多失`, `空失`, `多达`, and `空达`.
- 10m WATCH: show in the current card plus one frozen price-anchored marker while
  the WATCH remains active; full WATCH history is off by default.
- `趋势多/趋势空/多续/空续`: move off the default chart. They are context, not a
  new trade action.
- `冲突/重置/到期`: audit/Data Window only.
- `近支撑/近阻力/反应`: current card or a single current warning, not a permanent
  historical wall.
- Every terminal marker must retain the direction and the frozen plan owner.

## Four causal chart cases

The companion chart is stored in the external evidence directory as
`trader_utility_33d_casebook_20260802.png` (172,859 bytes; SHA-256
`005b44d510782bd434e61493d943c9ccd519d1b0f081ea96fc54720f01b12fea`).
It is deliberately not redistributed in this public-source worktree.

1. **Useful trend continuation — 2026-07-30 09:00 ET.** `趋势多` became known at
   09:03. From the next open it had +44.5 MFE and -3.3 MAE before the reviewed
   window ended. The visible owner and later exit formed a coherent chain.
2. **Bad chase — 2026-07-20 07:30 ET.** `趋势多` became known at 07:33 after a
   large green candle. From the next open it had only +3.2 MFE against -20.3 MAE.
   Direction alone did not justify entry because position and space were not
   screened first.
3. **Hidden owner — 2026-07-29 09:27 ET.** The internal short plan became knowable
   at 09:30 and later had +82.1 favorable versus -4.0 adverse excursion, but the
   UI showed conflict instead of a usable short-plan entry. At 12:27 it displayed
   `空头退` without a visible entry chain.
4. **Support conflict — 2026-07-31 11:24 ET.** The chart simultaneously produced
   a short context and near-support evidence. At 11:27 the correct action was to
   stop chasing short. The bounce was confirmable by 11:39, while the old short
   exit did not become known until 11:54.

## Current R3 boundary

The current 10m/3m responsibility split is coherent:

```text
10m direction + position + space -> create one plan
3m pullback + later trigger       -> one entry marker
frozen invalidation / target      -> manage that same plan
```

The two available linked R3 examples are one poor short and one strong long. That
is enough to inspect semantics, but far too little to estimate edge. The next data
gate is a current-R3 30-day export, followed by the same causal review on 10m plan
creation, 3m entry timing, and plan-owned terminal events.

The two linked cases are rendered in the external evidence directory as
`r3_linked_cases_20260802.png` (95,911 bytes; SHA-256
`7350cf84d81d75f3d69298b561dab3e6dc81c6e568f8473463587f47048375f7`).

## Minimal implementation scope

1. Remove gray action text: card labels and actionable values use white or a clear
   direction/status color; silver is restricted to non-action audit metadata.
2. Hide historical 10m WATCH markers by default while keeping the active WATCH
   visible at its frozen first-touch price.
3. Rename `主多/主空` to `多计划/空计划`.
4. Split generic `失/达` into direction-owned terminal markers.
5. Reduce each R3 card to four trader questions: `现在做`, `触发`, `失效`, `目标`.
6. Show a terminal result only on its actual event bar; afterward show
   `本计划结束｜等新 10m` and suppress stale stop/target values.
7. Do not change signal thresholds in this UI/lifecycle revision.

## Implemented R3.1 contract

- 10m history is reduced to `多计划/空计划`; the active WATCH is a single frozen
  price-anchored `多观察/空观察`, while WATCH history is off by default.
- 3m history is reduced to `多入/空入/多失/空失/多达/空达`.
- `失/达` require the matching entered owner and never imply a reversal.
- A WATCH invalidation is called `多观察失效/空观察失效`; it cannot impersonate
  a plan terminal or display a fabricated plan stop/target.
- The current card answers only `现在做/触发/失效/目标`. Action text uses white or
  directional high-contrast colors; silver remains audit-only.
- Terminal information appears on the event bar only. On the next bar the card
  becomes `本计划结束｜等新 10m`, and stale stop/target fields become `—`.
- MTF action-facing `到达/接近` text and the main card field labels were changed
  from black/gray to white for the dark chart theme.

## Final offline validation

- Generator parity: `research/generate_phase1_10m_primary_pine_r3.py --check`
  passed.
- Full repository gate: **1,066 passed, 130 skipped**. The skipped tests are
  explicitly external/private replay-fixture gates and are not counted as passes.
- The available real 33-day P6 export was supplied separately to its fixture gate:
  **139 passed**.
- Python compile checks and targeted `git diff --check` passed.
- Generated source SHA-256:
  - 10m R3.1: `ec2f8eee96960d8f95c6a2035181bfa0e319e498bdd12a988f2a9678bde138ba`
  - 3m R3.1: `f349baa860124a386396b173780567cc842a3591f894b99d97381d6726af6c8f`

## Remaining gate

The Mac was locked during final acceptance, so the target TradingView Desktop
chart could not be compiled, panned/zoomed, or captured after this source change.
The code/offline result must not be described as visual acceptance or a live-use
signal edge until that separate gate is completed.
