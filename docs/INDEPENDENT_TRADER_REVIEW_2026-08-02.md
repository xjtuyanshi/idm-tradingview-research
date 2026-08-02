# Independent Trader Review — 2026-08-02

## Final verdict

**ACCEPT for the source/offline trader-facing contract.**

The reviewer approached the chart as a trader seeing each event only after its
bar closed. It did not treat later price movement as justification for an earlier
ambiguous label and did not evaluate profitability.

## Accepted behavior

- WATCH long/short invalidation and WATCH expiry use observation language.
- A WATCH never impersonates a formed plan and never exposes fabricated plan
  stop/target values.
- Terminal stop/target context is visible on the event bar and cleared afterward.
- The current WATCH remains price anchored; historical WATCH is off by default.
- 10m publishes a plan; 3m publishes entry timing; matching owner `失/达` ends
  that same lifecycle and never means automatic reversal.
- The canonical signal block and thresholds were not changed.
- Generator parity passed.

## Reviewer-discovered defect and correction

The first implementation inferred every ownerless WATCH invalidation from the
plan direction field. WATCH has no opportunity owner, so a long WATCH could be
mislabelled `空计划失效`. The UI-only derivation was corrected:

- an event with `opportunityTime` is a plan terminal;
- an ownerless event is a WATCH terminal;
- strict close-versus-frozen-invalidation relation determines long/short WATCH
  context, with a neutral fallback when direction cannot be proved;
- fixture mirrors now pin both long and short WATCH invalidation cases.

## Reviewer verification

- Reviewer-scoped run: `100 passed, 7 skipped`.
- The seven skips were external private 337-bar replay fixtures absent from that
  repository-scoped run; they were not counted as passes.
- The reviewer changed no files.

## Explicit boundary

This verdict is not TradingView online compilation, actual chart visual
acceptance, live forward performance, execution quality, or evidence of a
profitable edge.
