#!/usr/bin/env python3
"""Replay the R3 native-10m producer into the confirmed-only 3m timing engine.

Both input paths and both output paths are caller supplied.  The program uses a
10-minute source observation only after source_open + 10 minutes is no later
than the confirmed 3-minute bar open.  It writes a compact derived event ledger,
not a copy of the private 3-minute market export.

This is a deterministic state-machine audit.  It creates no alert, order,
strategy call, account change, recommendation, or profitability claim.
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
    PRIMARY_INTERVAL_SECONDS,
    Direction,
    OpportunityPlan,
    OpportunityTimingEngine,
    PrimaryEvent,
    PrimaryObservation,
    TenMinuteBar,
    ThreeMinuteBar,
    TimingEvent,
    TimingObservation,
    TimingReason,
    TimingState,
    run_primary,
)

NEW_YORK = ZoneInfo("America/New_York")
TEN_EMA21_COLUMN = "Phase1 EMA21｜close｜回踩/均值参考"
TEN_EMA48_COLUMN = "Phase1 EMA48｜close｜慢速结构保护"
TEN_EMA5_COLUMN = "Ripster EMA5｜hl2｜快线"
TEN_EMA12_COLUMN = "Ripster EMA12｜hl2｜慢线"
THREE_EMA5_COLUMN = "3m EMA5"
THREE_EMA12_COLUMN = "3m EMA12"

KNOWN_TEN_SHA256 = "037ed7a18f93ae20ebca7cf755ff675086207f8f00110766975679d56245aa74"
KNOWN_THREE_SHA256 = "d5c915b99f2f813ffcb0308059a7fb9ed1b7589a893e6b6ff9a3493fc8237436"
KNOWN_PLAN_ID = "10M-TC-L-1785409800000"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def et_text(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return ""
    return datetime.fromtimestamp(timestamp_ms / 1000, NEW_YORK).strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def f_number(value: float | None, digits: int = 6) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _float_or_nan(value: str) -> float:
    text = value.strip()
    return float(text) if text else float("nan")


def direction_text(value: Direction) -> str:
    if value == Direction.LONG:
        return "LONG"
    if value == Direction.SHORT:
        return "SHORT"
    return "NONE"


def _require_columns(reader: csv.DictReader, required: set[str], path: Path) -> None:
    missing = required.difference(reader.fieldnames or ())
    if missing:
        raise ValueError(f"{path.name}: missing CSV columns: {sorted(missing)}")


def _require_strictly_increasing(timestamps: Iterable[int], label: str) -> None:
    previous: int | None = None
    for index, value in enumerate(timestamps):
        if previous is not None and value <= previous:
            raise ValueError(
                f"{label}: timestamps must be strictly increasing; "
                f"row {index} has {value} after {previous}"
            )
        previous = value


def load_ten_minute_bars(path: Path) -> list[TenMinuteBar]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _require_columns(
            reader,
            {
                "time",
                "open",
                "high",
                "low",
                "close",
                TEN_EMA5_COLUMN,
                TEN_EMA12_COLUMN,
                TEN_EMA21_COLUMN,
                TEN_EMA48_COLUMN,
            },
            path,
        )
        bars = [
            TenMinuteBar(
                timestamp_ms=int(row["time"]) * 1000,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                ema5=float(row[TEN_EMA5_COLUMN]),
                ema12=float(row[TEN_EMA12_COLUMN]),
                ema21=float(row[TEN_EMA21_COLUMN]),
                ema48=float(row[TEN_EMA48_COLUMN]),
            )
            for row in reader
        ]
    if not bars:
        raise ValueError(f"{path.name}: no 10m rows")
    _require_strictly_increasing((bar.timestamp_ms for bar in bars), "10m")
    return bars


def load_three_minute_bars(path: Path) -> list[ThreeMinuteBar]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _require_columns(
            reader,
            {
                "time",
                "open",
                "high",
                "low",
                "close",
                THREE_EMA5_COLUMN,
                THREE_EMA12_COLUMN,
            },
            path,
        )
        bars = [
            ThreeMinuteBar(
                timestamp_ms=int(row["time"]) * 1000,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                ema5=_float_or_nan(row[THREE_EMA5_COLUMN]),
                ema12=_float_or_nan(row[THREE_EMA12_COLUMN]),
            )
            for row in reader
        ]
    if not bars:
        raise ValueError(f"{path.name}: no 3m rows")
    _require_strictly_increasing((bar.timestamp_ms for bar in bars), "3m")
    return bars


def _plan_id(plan: OpportunityPlan | None) -> str:
    return "" if plan is None else plan.opportunity_id


def _event_plan(
    source: PrimaryObservation, source_advanced: bool
) -> OpportunityPlan | None:
    if not source_advanced or source.event == PrimaryEvent.NONE:
        return None
    return source.plan


def _ledger_row(
    *,
    three_index: int,
    bar: ThreeMinuteBar,
    source_index: int,
    source_bar: TenMinuteBar,
    source: PrimaryObservation,
    source_advanced: bool,
    observation: TimingObservation,
) -> dict[str, str | int]:
    return {
        "three_index": three_index,
        "three_time_et": et_text(bar.timestamp_ms),
        "three_timestamp_ms": bar.timestamp_ms,
        "three_open": f_number(bar.open, 1),
        "three_high": f_number(bar.high, 1),
        "three_low": f_number(bar.low, 1),
        "three_close": f_number(bar.close, 1),
        "source_10m_index": source_index,
        "source_10m_time_et": et_text(source_bar.timestamp_ms),
        "source_10m_available_et": et_text(
            source_bar.timestamp_ms + PRIMARY_INTERVAL_SECONDS * 1000
        ),
        "source_advanced": int(source_advanced),
        "primary_event": source.event.value if source_advanced else PrimaryEvent.NONE.value,
        "primary_reason": source.reason_code.value,
        "primary_permission_active": int(source.opportunity_active),
        "primary_plan_id": _plan_id(source.plan),
        "timing_state": observation.state.value,
        "timing_event": observation.event.value,
        "timing_reason": observation.reason_code.value,
        "timing_plan_id": observation.opportunity_id or "",
        "timing_direction": direction_text(observation.direction),
        "timing_invalidation": f_number(observation.plan_invalidation),
        "timing_target": f_number(observation.plan_target),
        "timing_target_source": observation.plan_target_source.value,
        "timing_frozen_trigger": f_number(observation.frozen_trigger),
        "timing_marker_price": f_number(observation.marker_price),
        "suppressed_plan_id": observation.suppressed_opportunity_id or "",
    }


def replay(
    ten_bars: list[TenMinuteBar], three_bars: list[ThreeMinuteBar]
) -> tuple[list[dict[str, str | int]], list[dict[str, str | int]], dict[str, Counter[str] | int]]:
    primary = run_primary(ten_bars)
    timing_engine = OpportunityTimingEngine()
    all_rows: list[dict[str, str | int]] = []
    event_rows: list[dict[str, str | int]] = []
    source_index = -1
    last_delivered_source_index = -1
    previous_state: TimingState | None = None
    previous_reason: TimingReason | None = None
    previous_plan_id = ""

    first_usable = ten_bars[0].timestamp_ms + PRIMARY_INTERVAL_SECONDS * 1000
    # The final completed source bar remains the previous-completed 10m value
    # only until the next expected 10m close.  Stop before unavailable source
    # data would be required.
    coverage_end = ten_bars[-1].timestamp_ms + 2 * PRIMARY_INTERVAL_SECONDS * 1000

    for three_index, bar in enumerate(three_bars):
        if bar.timestamp_ms < first_usable or bar.timestamp_ms >= coverage_end:
            continue
        while (
            source_index + 1 < len(ten_bars)
            and ten_bars[source_index + 1].timestamp_ms
            + PRIMARY_INTERVAL_SECONDS * 1000
            <= bar.timestamp_ms
        ):
            source_index += 1
        if source_index < 0:
            continue

        source_bar = ten_bars[source_index]
        source = primary[source_index]
        source_advanced = source_index != last_delivered_source_index
        primary_event = source.event if source_advanced else PrimaryEvent.NONE
        event_plan = _event_plan(source, source_advanced)
        active_plan = source.plan if source.opportunity_active else None
        observation = timing_engine.ingest(
            bar,
            active_plan,
            primary_event,
            event_plan,
        )
        row = _ledger_row(
            three_index=three_index,
            bar=bar,
            source_index=source_index,
            source_bar=source_bar,
            source=source,
            source_advanced=source_advanced,
            observation=observation,
        )
        all_rows.append(row)

        current_plan_id = observation.opportunity_id or ""
        significant = (
            source_advanced and source.event != PrimaryEvent.NONE
            or observation.event != TimingEvent.NONE
            or observation.state != previous_state
            or observation.reason_code != previous_reason
            or current_plan_id != previous_plan_id
        )
        if significant:
            event_rows.append(row)
        previous_state = observation.state
        previous_reason = observation.reason_code
        previous_plan_id = current_plan_id
        last_delivered_source_index = source_index

    if not all_rows:
        raise RuntimeError("10m and 3m inputs have no completed-source overlap")

    counts: dict[str, Counter[str] | int] = {
        "processed_three_rows": len(all_rows),
        "event_ledger_rows": len(event_rows),
        "timing_events": Counter(str(row["timing_event"]) for row in all_rows),
        "timing_states": Counter(str(row["timing_state"]) for row in all_rows),
        "timing_reasons": Counter(str(row["timing_reason"]) for row in all_rows),
        "primary_pulses": Counter(
            str(row["primary_event"])
            for row in all_rows
            if row["primary_event"] != PrimaryEvent.NONE.value
        ),
    }
    return all_rows, event_rows, counts


def _write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    if not rows:
        raise RuntimeError("event ledger is unexpectedly empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _counter_line(value: Counter[str]) -> str:
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _find_row(
    rows: list[dict[str, str | int]],
    *,
    three_prefix: str | None = None,
    source_prefix: str | None = None,
    timing_event: str | None = None,
) -> dict[str, str | int]:
    for row in rows:
        if three_prefix is not None and not str(row["three_time_et"]).startswith(three_prefix):
            continue
        if source_prefix is not None and not str(row["source_10m_time_et"]).startswith(source_prefix):
            continue
        if timing_event is not None and row["timing_event"] != timing_event:
            continue
        return row
    raise RuntimeError(
        f"required replay row not found: three={three_prefix}, "
        f"source={source_prefix}, event={timing_event}"
    )


def _known_case_evidence(
    all_rows: list[dict[str, str | int]],
) -> list[str]:
    adoption = _find_row(all_rows, three_prefix="2026-07-30 07:21:00")
    touch = _find_row(all_rows, three_prefix="2026-07-30 07:24:00")
    entry = _find_row(
        all_rows,
        three_prefix="2026-07-30 07:36:00",
        timing_event=TimingEvent.LONG_ENTRY.value,
    )
    expiry_handoff = _find_row(
        all_rows,
        three_prefix="2026-07-30 09:30:00",
        source_prefix="2026-07-30 09:20:00",
    )
    target = _find_row(
        all_rows,
        three_prefix="2026-07-30 16:00:00",
        timing_event=TimingEvent.LONG_TARGET_REACHED.value,
    )

    assert adoption["timing_reason"] == TimingReason.NEW_OPPORTUNITY.value
    assert adoption["timing_plan_id"] == KNOWN_PLAN_ID
    assert touch["timing_reason"] == TimingReason.PULLBACK_FROZEN.value
    assert touch["timing_frozen_trigger"] == "7366.900000"
    assert entry["timing_state"] == TimingState.ENTERED.value
    assert entry["timing_plan_id"] == KNOWN_PLAN_ID
    assert entry["three_close"] == "7368.3"
    assert expiry_handoff["primary_event"] == PrimaryEvent.EXPIRED.value
    assert expiry_handoff["primary_permission_active"] == 0
    assert expiry_handoff["timing_state"] == TimingState.ENTERED.value
    assert expiry_handoff["timing_reason"] == TimingReason.ENTERED_PLAN_MANAGEMENT.value
    assert expiry_handoff["timing_plan_id"] == KNOWN_PLAN_ID
    assert expiry_handoff["timing_invalidation"] == "7345.738437"
    assert expiry_handoff["timing_target"] == "7450.200000"
    assert target["timing_state"] == TimingState.LOCKED.value
    assert target["timing_plan_id"] == KNOWN_PLAN_ID
    assert target["timing_target"] == "7450.200000"

    plan_entries = [
        row
        for row in all_rows
        if row["timing_plan_id"] == KNOWN_PLAN_ID
        and row["timing_event"] == TimingEvent.LONG_ENTRY.value
    ]
    if len(plan_entries) != 1:
        raise AssertionError(f"expected one LONG_ENTRY for {KNOWN_PLAN_ID}, got {len(plan_entries)}")
    premature_end = [
        row
        for row in all_rows
        if row["timing_plan_id"] == KNOWN_PLAN_ID
        and entry["three_timestamp_ms"] < row["three_timestamp_ms"] < target["three_timestamp_ms"]
        and row["timing_reason"] == TimingReason.OPPORTUNITY_ENDED.value
    ]
    if premature_end:
        raise AssertionError(f"entered plan ended before target: {premature_end[0]}")

    columns = (
        "three_time_et",
        "source_10m_time_et",
        "primary_event",
        "primary_permission_active",
        "timing_state",
        "timing_event",
        "timing_reason",
        "timing_plan_id",
        "timing_invalidation",
        "timing_target",
        "timing_frozen_trigger",
        "timing_marker_price",
    )
    selected = (adoption, touch, entry, expiry_handoff, target)
    lines = ["\t".join(columns)]
    lines.extend("\t".join(str(row[column]) for column in columns) for row in selected)
    lines.extend(
        (
            f"known_plan_id={KNOWN_PLAN_ID}",
            "entry_count_for_known_plan=1",
            "premature_OPPORTUNITY_ENDED_between_entry_and_target=0",
            "expiry_semantics=10m ACTIVE_EXPIRED ended entry permission only; ENTERED frozen plan remained owner",
            "replacement_semantics=different 10m plan cannot replace ENTERED old plan; covered by package unit/parity tests",
        )
    )
    return lines


def build_log(
    *,
    ten_path: Path,
    three_path: Path,
    ten_bars: list[TenMinuteBar],
    three_bars: list[ThreeMinuteBar],
    all_rows: list[dict[str, str | int]],
    event_rows: list[dict[str, str | int]],
    counts: dict[str, Counter[str] | int],
) -> str:
    ten_sha = sha256_path(ten_path)
    three_sha = sha256_path(three_path)
    known_case = ten_sha == KNOWN_TEN_SHA256 and three_sha == KNOWN_THREE_SHA256
    lines = [
        "Phase 1 R3｜native 10m → confirmed-only 3m 真实双周期回放",
        "",
        "范围：状态机与因果 transport 审计；无 alert、order、策略调用、胜率或盈利结论。",
        f"ten_minute_csv={ten_path.name}",
        f"ten_minute_bytes={ten_path.stat().st_size}",
        f"ten_minute_sha256={ten_sha}",
        f"ten_minute_rows={len(ten_bars)}",
        f"ten_minute_first_et={et_text(ten_bars[0].timestamp_ms)}",
        f"ten_minute_last_et={et_text(ten_bars[-1].timestamp_ms)}",
        f"three_minute_csv={three_path.name}",
        f"three_minute_bytes={three_path.stat().st_size}",
        f"three_minute_sha256={three_sha}",
        f"three_minute_rows={len(three_bars)}",
        f"three_minute_first_et={et_text(three_bars[0].timestamp_ms)}",
        f"three_minute_last_et={et_text(three_bars[-1].timestamp_ms)}",
        f"processed_three_rows={counts['processed_three_rows']}",
        f"derived_event_ledger_rows={counts['event_ledger_rows']}",
        "transport=10m bar is unavailable until source timestamp + 600000ms <= confirmed 3m bar open",
        "final_source_scope=stop before the next unavailable 10m close would be required",
        "private_3m_csv_bundled=NO",
        "",
        "计数",
        f"primary_pulses: {_counter_line(counts['primary_pulses'])}",
        f"timing_events: {_counter_line(counts['timing_events'])}",
        f"timing_states: {_counter_line(counts['timing_states'])}",
        f"timing_reasons: {_counter_line(counts['timing_reasons'])}",
        "",
        "已知输入身份与 R3 P1-A 证据",
        f"known_input_pair={int(known_case)}",
    ]
    if known_case:
        lines.extend(_known_case_evidence(all_rows))
    else:
        lines.append("known-case assertions=SKIPPED because input hashes differ")

    lines.extend(
        (
            "",
            "全部派生状态转换/事件行（不是原始 3m CSV）",
        )
    )
    columns = tuple(event_rows[0])
    lines.append("\t".join(columns))
    lines.extend("\t".join(str(row[column]) for column in columns) for row in event_rows)
    lines.extend(
        (
            "",
            "限制",
            "- 3m export 行按已确认历史行处理；原 CSV 不包含 TradingView barstate 字段。",
            "- 未执行 TradingView Pine v6 在线编译、历史/实时 Replay 或图面视觉验收。",
            "- 此回放不评价方向 edge、交易成本、胜率或盈利。",
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ten-minute-csv", type=Path, required=True)
    parser.add_argument("--three-minute-csv", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--events-csv", type=Path, required=True)
    args = parser.parse_args()

    for path in (args.ten_minute_csv, args.three_minute_csv):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.log.resolve() in {
        args.ten_minute_csv.resolve(),
        args.three_minute_csv.resolve(),
    } or args.events_csv.resolve() in {
        args.ten_minute_csv.resolve(),
        args.three_minute_csv.resolve(),
    }:
        raise ValueError("output path must not overwrite an input CSV")

    ten_bars = load_ten_minute_bars(args.ten_minute_csv)
    three_bars = load_three_minute_bars(args.three_minute_csv)
    all_rows, event_rows, counts = replay(ten_bars, three_bars)
    log = build_log(
        ten_path=args.ten_minute_csv,
        three_path=args.three_minute_csv,
        ten_bars=ten_bars,
        three_bars=three_bars,
        all_rows=all_rows,
        event_rows=event_rows,
        counts=counts,
    )
    _write_csv(args.events_csv, event_rows)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(log, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
