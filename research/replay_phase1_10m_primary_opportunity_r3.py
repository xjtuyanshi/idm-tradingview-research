#!/usr/bin/env python3
"""Replay the R3 native-10m contract on the supplied 337-bar SPX CSV.

The output is an audit trail, not a performance study.  It reports every
non-NONE state-machine event and separately explains the two correction-task
candidates.  It creates no order, alert, recommendation, or profitability
claim.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
from pathlib import Path
import sys
from typing import Iterable
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.phase1_10m_primary_opportunity_oracle import (
    Direction,
    NamedLevelCandidate,
    PrimaryEvent,
    PrimaryObservation,
    TenMinuteBar,
    run_primary,
)

NEW_YORK = ZoneInfo("America/New_York")
EMA21_COLUMN = "Phase1 EMA21｜close｜回踩/均值参考"
EMA48_COLUMN = "Phase1 EMA48｜close｜慢速结构保护"
EMA5_COLUMN = "Ripster EMA5｜hl2｜快线"
EMA12_COLUMN = "Ripster EMA12｜hl2｜慢线"
EXPECTED_ROWS = 337
DECISION_EVENTS = {
    PrimaryEvent.WATCH_LONG,
    PrimaryEvent.WATCH_SHORT,
    PrimaryEvent.MAIN_LONG,
    PrimaryEvent.MAIN_SHORT,
    PrimaryEvent.DONT_CHASE,
    PrimaryEvent.SPACE_UNKNOWN,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _et(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, NEW_YORK).strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def _f(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _direction(value: Direction) -> str:
    return "LONG" if value == Direction.LONG else "SHORT" if value == Direction.SHORT else "NONE"


def _candidate_text(candidates: Iterable[NamedLevelCandidate]) -> str:
    return ";".join(
        "@".join(
            (
                f"{candidate.price:.4f}",
                candidate.source.value,
                "" if candidate.provenance_time_ms is None else str(candidate.provenance_time_ms),
                "consumed" if candidate.consumed else "open",
            )
        )
        for candidate in candidates
    )


def load_bars(path: Path) -> list[TenMinuteBar]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {
            "time",
            "open",
            "high",
            "low",
            "close",
            EMA21_COLUMN,
            EMA48_COLUMN,
            EMA5_COLUMN,
            EMA12_COLUMN,
        }
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing CSV columns: {sorted(missing)}")
        bars = [
            TenMinuteBar(
                timestamp_ms=int(row["time"]) * 1000,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                ema5=float(row[EMA5_COLUMN]),
                ema12=float(row[EMA12_COLUMN]),
                ema21=float(row[EMA21_COLUMN]),
                ema48=float(row[EMA48_COLUMN]),
            )
            for row in reader
        ]
    if len(bars) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} bars, found {len(bars)}")
    return bars


def event_row(index: int, bar: TenMinuteBar, observation: PrimaryObservation) -> dict[str, str | int]:
    plan = observation.plan
    return {
        "bar_index": index,
        "time_et": _et(bar.timestamp_ms),
        "timestamp_ms": bar.timestamp_ms,
        "open": _f(bar.open, 1),
        "high": _f(bar.high, 1),
        "low": _f(bar.low, 1),
        "close": _f(bar.close, 1),
        "slow_direction": _direction(observation.slow_direction),
        "fast_direction": _direction(observation.fast_direction),
        "state": observation.state.value,
        "event": observation.event.value,
        "reason_code": observation.reason_code.value,
        "epoch_id": observation.epoch_id or "",
        "episode_id": observation.episode_id or "",
        "outcome": observation.outcome.value,
        "outcome_direction": _direction(observation.outcome_direction),
        "opportunity_active": int(observation.opportunity_active),
        "opportunity_id": "" if plan is None else plan.opportunity_id,
        "entry_reference": "" if plan is None else _f(plan.entry_reference),
        "invalidation": "" if plan is None else _f(plan.invalidation),
        "target": "" if plan is None else _f(plan.next_named_level),
        "target_source": "" if plan is None else plan.next_named_level_source.value,
        "target_provenance_time_ms": ""
        if plan is None or plan.next_named_level_provenance_time_ms is None
        else plan.next_named_level_provenance_time_ms,
        "risk": "" if plan is None else _f(plan.risk),
        "space": "" if plan is None else _f(plan.space),
        "space_R": "" if plan is None else _f(plan.space_r, 6),
        "marker_price": _f(observation.marker_price),
        "frozen_candidates": _candidate_text(observation.frozen_candidates),
    }


def _write_event_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _counter_line(counter: Counter[str]) -> str:
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter))


def _find(
    bars: list[TenMinuteBar],
    observations: list[PrimaryObservation],
    timestamp_text: str,
) -> tuple[TenMinuteBar, PrimaryObservation]:
    for bar, observation in zip(bars, observations, strict=True):
        if _et(bar.timestamp_ms).startswith(timestamp_text):
            return bar, observation
    raise RuntimeError(f"candidate not found: {timestamp_text}")


def _episode_trace_lines(
    bars: list[TenMinuteBar],
    observations: list[PrimaryObservation],
    candidate: PrimaryObservation,
) -> list[str]:
    if candidate.episode_id is None:
        raise RuntimeError("candidate is missing episode identity")
    columns = (
        "bar_index",
        "time_et",
        "OHLC",
        "EMA5/12",
        "EMA21/48",
        "slow/fast",
        "state",
        "event",
        "reason",
        "prior_excursion",
        "reaction_high/low",
        "frozen_candidates",
    )
    lines = ["\t".join(columns)]
    for index, (bar, observation) in enumerate(
        zip(bars, observations, strict=True)
    ):
        if observation.timestamp_ms > candidate.timestamp_ms:
            break
        if observation.episode_id != candidate.episode_id:
            continue
        lines.append(
            "\t".join(
                (
                    str(index),
                    _et(bar.timestamp_ms),
                    f"{bar.open:.1f}/{bar.high:.1f}/{bar.low:.1f}/{bar.close:.1f}",
                    f"{bar.ema5:.4f}/{bar.ema12:.4f}",
                    f"{bar.ema21:.4f}/{bar.ema48:.4f}",
                    f"{_direction(observation.slow_direction)}/{_direction(observation.fast_direction)}",
                    observation.state.value,
                    observation.event.value,
                    observation.reason_code.value,
                    _f(observation.prior_excursion),
                    f"{_f(observation.reaction_high)}/{_f(observation.reaction_low)}",
                    _candidate_text(observation.frozen_candidates),
                )
            )
        )
    return lines


def build_log(
    csv_path: Path,
    bars: list[TenMinuteBar],
    observations: list[PrimaryObservation],
    event_rows: list[dict[str, str | int]],
) -> str:
    events = Counter(observation.event.value for observation in observations)
    states = Counter(observation.state.value for observation in observations)
    reasons = Counter(observation.reason_code.value for observation in observations)
    decision_names = {item.value for item in DECISION_EVENTS}
    decisions = [row for row in event_rows if row["event"] in decision_names]

    lines = [
        "Phase 1 native-10m 主机会 R3｜337 根真实 10m 逐事件回放",
        "",
        "范围：仅使用随包 CAPITALCOM:SPX500 10m CSV；这是状态机审计，不是胜率、订单或盈利研究。",
        f"csv={csv_path.name}",
        f"csv_bytes={csv_path.stat().st_size}",
        f"csv_sha256={_sha256(csv_path)}",
        f"bars={len(bars)}",
        f"first_bar_et={_et(bars[0].timestamp_ms)}",
        f"last_bar_et={_et(bars[-1].timestamp_ms)}",
        "confirmed_contract=任务包把 337 行作为已确认 10m K；CSV 本身不含 TradingView barstate 字段",
        "",
        "计数",
        f"events: {_counter_line(events)}",
        f"states: {_counter_line(states)}",
        f"reasons: {_counter_line(reasons)}",
        f"non_none_events={len(event_rows)}",
        f"decision_events={len(decisions)}",
        "",
        "逐决策事件（WATCH / MAIN / DONT_CHASE / SPACE_UNKNOWN）",
    ]
    decision_columns = (
        "bar_index",
        "time_et",
        "event",
        "state",
        "reason_code",
        "episode_id",
        "entry_reference",
        "invalidation",
        "target",
        "target_source",
        "space_R",
        "frozen_candidates",
    )
    lines.append("\t".join(decision_columns))
    for row in decisions:
        lines.append("\t".join(str(row[column]) for column in decision_columns))

    lines.extend(("", "全部非 NONE 生命周期事件"))
    all_columns = (
        "bar_index",
        "time_et",
        "open",
        "high",
        "low",
        "close",
        "slow_direction",
        "fast_direction",
        "state",
        "event",
        "reason_code",
        "epoch_id",
        "episode_id",
        "opportunity_id",
        "entry_reference",
        "invalidation",
        "target",
        "target_source",
        "space_R",
        "marker_price",
        "frozen_candidates",
    )
    lines.append("\t".join(all_columns))
    for row in event_rows:
        lines.append("\t".join(str(row[column]) for column in all_columns))

    bar_a, obs_a = _find(bars, observations, "2026-07-29 09:40:00")
    bar_b, obs_b = _find(bars, observations, "2026-07-30 07:10:00")
    plan_a = obs_a.plan
    plan_b = obs_b.plan
    if plan_a is None or plan_b is None:
        raise RuntimeError("required candidate observations are missing plans")

    lines.extend(
        (
            "",
            "候选 A｜2026-07-29 09:40 ET SHORT：逐根 episode trace",
        )
    )
    lines.extend(_episode_trace_lines(bars, observations, obs_a))
    lines.extend(
        (
            "",
            f"confirmation_ohlc={bar_a.open:.1f}/{bar_a.high:.1f}/{bar_a.low:.1f}/{bar_a.close:.1f}",
            f"entry_reference={plan_a.entry_reference:.4f}",
            f"invalidation={plan_a.invalidation:.4f}",
            f"risk={plan_a.risk:.4f}",
            f"frozen_candidates={_candidate_text(obs_a.frozen_candidates)}",
            "解释：09:20 首触时，router 只能冻结当时位于 touch K 完整 low 下方的 causal prior-excursion 7418.1。09:40 确认 K 的 low=7411.5，已用整根确认 K 消费该最近水平。2026-07-29 是样本首个 ET 日，因此没有上一完整日低点；touch 前也没有另一个已完成 right=2 的、尚未消费且位于确认 K 下方的 10m pivot low。候选集合删除 7418.1 后为空，故必须输出 SPACE_UNKNOWN｜无大机会。这里不能跳过障碍，也不能凭空补一个更远目标；因为没有可信 target，无法诚实计算 <1R，所以不是强行改写为 DONT_CHASE。",
            f"result={obs_a.event.value}",
            "",
            "候选 B｜2026-07-30 07:10 ET LONG：逐根 episode trace",
        )
    )
    lines.extend(_episode_trace_lines(bars, observations, obs_b))
    lines.extend(
        (
            "",
            f"confirmation_ohlc={bar_b.open:.1f}/{bar_b.high:.1f}/{bar_b.low:.1f}/{bar_b.close:.1f}",
            f"entry_reference={plan_b.entry_reference:.4f}",
            f"invalidation={plan_b.invalidation:.4f}",
            f"risk={plan_b.risk:.4f}",
            f"frozen_candidates={_candidate_text(obs_b.frozen_candidates)}",
            "解释：06:50 首触时，episode 的 prior excursion 约 7361.5 已落在 touch K 的完整范围内，不能充当前方 target。touch 前已确认的两个 pivot high 为 7361.8 与 7450.2。2026-07-29 的输入从 06:00 ET 才开始，不满足 00:00–23:50 连续 144 根的完整日合同，因此 7454.2 不再被误晋升为 PREVIOUS_COMPLETED_DAY_HIGH。07:10 确认 K high=7364.9 先消费 7361.8；剩余最近未消费 named level 是 7450.2。space=7450.2-7362.6=87.6，risk=7362.6-7345.7384=16.8616，space_R=5.195248，满足 >=1.0 的硬门禁，故产生 MAIN_LONG，并且只授权后续 3m 择时。",
            f"selected_target={plan_b.next_named_level:.4f}",
            f"selected_source={plan_b.next_named_level_source.value}",
            f"space_R={plan_b.space_r:.6f}",
            f"result={obs_b.event.value}",
            "",
            "限制",
            "- 本回放只覆盖 2026-07-29 至 2026-07-31 的 337 根输入行。",
            "- 它不是三个月验证、walk-forward、胜率、交易成本、订单或盈利证明。",
            "- Python 回放没有执行 TradingView Pine 在线编译、历史/实时一致性或双窗视觉对位。",
        )
    )
    return "\n".join(lines) + "\n"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--events-csv", type=Path, required=True)
    args = parser.parse_args()

    bars = load_bars(args.csv)
    observations = run_primary(bars)
    rows = [
        event_row(index, bar, observation)
        for index, (bar, observation) in enumerate(
            zip(bars, observations, strict=True)
        )
        if observation.event != PrimaryEvent.NONE
    ]
    if not rows:
        raise RuntimeError("replay unexpectedly produced no events")
    _write_event_csv(args.events_csv, rows)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(
        build_log(args.csv, bars, observations, rows), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
