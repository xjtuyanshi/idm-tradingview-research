# Copy/paste prompt for Claude Fable

```text
You are taking over a personal TradingView intraday decision-assistant project named IDM.

Before changing anything, read these files completely in order:

1. README.md
2. docs/STATUS.md
3. docs/ARCHITECTURE.md
4. docs/SIGNAL_AND_PLAN_CONTRACT.md
5. docs/FAILURES_AND_LIMITS.md
6. docs/SATY_OBSERVATIONS_2026-07-21.md
7. docs/EXPERIMENT_SATY_LEVEL_ADVISORY.md
8. docs/CLAUDE_FABLE_HANDOFF.md
9. research/reports/IDM_V11_2026-07-21_FIXTURE_AUDIT.md
10. intraday_decision_map_v11_aggressive_clean.pine
11. research/v11_oracle.py and all research/tests/test_v11_*.py files

The current v11 is a failed but runnable frozen baseline, not a profitable system:

- recorded window: 2026-07-16 through 2026-07-21
- 535 partial exit legs, not 535 independent signals
- profitable exit legs: 34.02%
- Profit Factor: 0.638
- expected payoff: -$0.33
- maximum drawdown: $205.46
- total P&L: -$175.41
- historical Confidence: not calibrated

Do not overwrite the frozen v11.0.0 source. Do not tune parameters or add indicators in your first pass.

User intent:

- Mainly view SPX500 on 10m and occasionally switch/use 3m.
- The 3m engine is the sole formal event source; 10m must relay the same event id, time, Entry, Stop, T1, and T2.
- Signals must be timely and readable, but location comes first: do not short into support or buy into resistance.
- Ripster-style Clouds handle context/pace.
- Saty-style ATR levels handle location/targets/space.
- Oscillator/divergence handles risk and deterioration.
- Confirmed price structure handles the final trigger.
- Existing positions need HOLD/PROTECT/EXIT guidance.
- Historical markers remain visible; newest events get short Chinese text plus detailed hover information.
- Phone notifications must be natural Chinese.
- A/B/C is rule completeness, never probability.
- Probability may only appear after genuine OOS calibration with sample size, interval, model version, and cutoff date.

Your first task is an audit only. Produce:

A. Executive verdict.
B. A complete Pine-versus-oracle mismatch table with file/line evidence.
C. An explanation of why the existing July 21 fixture cannot prove v11 parity.
D. A proposed single authoritative rule/configuration contract.
E. A true v11 parity-fixture design and event-ledger schema.
F. A review of the sanitized SATy observations using Location → State → Trigger → Management.
G. Exactly one first experiment. Prefer the source-aware Saty second-rejection AdvisoryEvent already specified; it must not trade.
H. Positive, negative, boundary, reload, replay, and 3m/10m identity acceptance tests.
I. A list of unknown or unverifiable items.

Hard constraints:

- no future data or repainting;
- no second 10m signal engine;
- marker = alert = plan = optional order event id;
- Advisory never places an order or changes a frozen plan;
- no probability from private posts, one selected day, or subjective weights;
- no repeated counting of correlated EMA/Cloud evidence;
- no simultaneous UI + entry + exit + execution + model rewrite;
- no private Discord text, screenshots, member names, links, or proprietary market exports in the public repository;
- no claim of edge until an event-level OOS report supports it.

Stop after the audit and wait for user approval before implementing code.
```
