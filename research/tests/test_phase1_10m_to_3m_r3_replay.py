"""Reusable R3 10m→3m replay CLI and completed-source transport tests."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from research.phase1_10m_primary_opportunity_oracle import (
    ThreeMinuteBar,
    TimingEvent,
    TimingReason,
)
from research.replay_phase1_10m_to_3m_r3 import (
    load_ten_minute_bars,
    replay,
)

ROOT = Path(__file__).resolve().parents[2]
TEN_CSV = ROOT / "evidence/SPX500-10m-337-bars-2026-07-29-to-2026-07-31.csv"
SCRIPT = ROOT / "research/replay_phase1_10m_to_3m_r3.py"
NY = ZoneInfo("America/New_York")
pytestmark = pytest.mark.skipif(
    not TEN_CSV.is_file(),
    reason="private 337-bar TradingView fixture is intentionally external",
)


def _timestamp(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=NY).timestamp() * 1000)


def _bar(text: str, open_: float, high: float, low: float, close: float, ema5: float, ema12: float) -> ThreeMinuteBar:
    return ThreeMinuteBar(
        timestamp_ms=_timestamp(text),
        open=open_,
        high=high,
        low=low,
        close=close,
        ema5=ema5,
        ema12=ema12,
    )


def _known_entry_rows() -> list[ThreeMinuteBar]:
    return [
        _bar("2026-07-30 07:21", 7361.9, 7362.9, 7360.6, 7362.4, 7361.6515, 7360.0405),
        _bar("2026-07-30 07:24", 7362.3, 7366.9, 7362.1, 7366.5, 7362.6010, 7360.7266),
        _bar("2026-07-30 07:27", 7366.8, 7367.0, 7365.1, 7366.9, 7363.9000, 7361.8000),
        _bar("2026-07-30 07:30", 7366.7, 7366.8, 7364.8, 7365.4, 7364.4000, 7362.4000),
        _bar("2026-07-30 07:33", 7365.4, 7366.7, 7364.9, 7366.2, 7365.0000, 7363.0000),
        _bar("2026-07-30 07:36", 7365.7, 7368.4, 7365.6, 7368.3, 7365.4521, 7363.3411),
    ]


def test_completed_10m_source_is_not_available_before_close() -> None:
    ten = load_ten_minute_bars(TEN_CSV)
    rows = [
        _bar("2026-07-30 07:18", 7360.0, 7361.0, 7359.0, 7360.5, 7360.0, 7359.0),
        *_known_entry_rows(),
    ]
    all_rows, _, _ = replay(ten, rows)
    before = all_rows[0]
    adopted = next(row for row in all_rows if str(row["three_time_et"]).startswith("2026-07-30 07:21:00"))
    assert str(before["source_10m_time_et"]).startswith("2026-07-30 07:00:00")
    assert before["primary_event"] == "NONE"
    assert str(adopted["source_10m_time_et"]).startswith("2026-07-30 07:10:00")
    assert adopted["primary_event"] == "MAIN_LONG"
    assert adopted["timing_reason"] == TimingReason.NEW_OPPORTUNITY.value


def test_replay_function_produces_one_entry_for_known_synthetic_slice() -> None:
    ten = load_ten_minute_bars(TEN_CSV)
    all_rows, event_rows, counts = replay(ten, _known_entry_rows())
    entries = [row for row in all_rows if row["timing_event"] == TimingEvent.LONG_ENTRY.value]
    assert len(entries) == 1
    assert str(entries[0]["three_time_et"]).startswith("2026-07-30 07:36:00")
    assert entries[0]["timing_plan_id"] == "10M-TC-L-1785409800000"
    assert int(counts["processed_three_rows"]) == 6
    assert event_rows


def test_replay_cli_accepts_caller_paths_and_writes_only_outputs(tmp_path: Path) -> None:
    three = tmp_path / "synthetic-3m.csv"
    with three.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "open", "high", "low", "close", "3m EMA5", "3m EMA12"])
        for bar in _known_entry_rows():
            writer.writerow(
                [
                    bar.timestamp_ms // 1000,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.ema5,
                    bar.ema12,
                ]
            )
    log = tmp_path / "out" / "replay.log"
    events = tmp_path / "out" / "events.csv"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--ten-minute-csv",
            str(TEN_CSV),
            "--three-minute-csv",
            str(three),
            "--log",
            str(log),
            "--events-csv",
            str(events),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.is_file() and events.is_file()
    text = log.read_text(encoding="utf-8")
    assert "known_input_pair=0" in text
    assert "private_3m_csv_bundled=NO" in text
    assert "LONG_ENTRY=1" in text
    assert three.read_text(encoding="utf-8").startswith("time,open,high")
