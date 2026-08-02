"""Fixed regression checks for the supplied 337-bar confirmed 10m replay."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys

import pytest

from research.phase1_10m_primary_opportunity_oracle import (
    NamedLevelSource,
    PrimaryEvent,
    PrimaryState,
    ReasonCode,
    run_primary,
)
from research.replay_phase1_10m_primary_opportunity_r3 import load_bars

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "evidence/SPX500-10m-337-bars-2026-07-29-to-2026-07-31.csv"
A_TIMESTAMP_MS = 1_785_332_400_000  # 2026-07-29 09:40 ET
B_TIMESTAMP_MS = 1_785_409_800_000  # 2026-07-30 07:10 ET
pytestmark = pytest.mark.skipif(
    not CSV.is_file(),
    reason="private 337-bar TradingView fixture is intentionally external",
)


def _replay():
    bars = load_bars(CSV)
    observations = run_primary(bars)
    return bars, observations


def _at(observations, timestamp_ms: int):
    return next(item for item in observations if item.timestamp_ms == timestamp_ms)


def test_supplied_337_bar_replay_has_pinned_event_state_and_reason_counts() -> None:
    bars, observations = _replay()
    assert len(bars) == len(observations) == 337

    assert Counter(item.event.value for item in observations) == Counter(
        {
            "NONE": 275,
            "WATCH_LONG": 17,
            "WATCH_SHORT": 9,
            "MAIN_LONG": 1,
            "MAIN_SHORT": 1,
            "DONT_CHASE": 7,
            "SPACE_UNKNOWN": 6,
            "INVALIDATED": 1,
            "EXPIRED": 10,
            "CONTEXT_RESET": 10,
        }
    )
    assert Counter(item.state.value for item in observations) == Counter(
        {
            "WAIT_TREND": 46,
            "WAIT_CLEAR": 106,
            "ARMED": 65,
            "WAIT_REACTION": 102,
            "ACTIVE": 18,
        }
    )
    assert Counter(item.reason_code.value for item in observations) == Counter(
        {
            "WAIT_SLOW_TREND": 35,
            "EPOCH_STARTED": 12,
            "WAIT_FULL_CLEAR": 71,
            "EPISODE_ARMED": 26,
            "WAIT_FIRST_PULLBACK": 39,
            "FIRST_PULLBACK_WATCH": 26,
            "WAIT_LATER_RECLAIM": 76,
            "REACTION_EXPIRED": 9,
            "SLOW_CONTEXT_LOST": 11,
            "SPACE_UNKNOWN": 6,
            "SPACE_LT_1R": 7,
            "MAIN_OPPORTUNITY_ACTIVE": 18,
            "ACTIVE_EXPIRED": 1,
        }
    )


def test_2026_07_29_0940_short_remains_honest_space_unknown() -> None:
    _, observations = _replay()
    observation = _at(observations, A_TIMESTAMP_MS)
    assert observation.event == PrimaryEvent.SPACE_UNKNOWN
    assert observation.reason_code == ReasonCode.SPACE_UNKNOWN
    assert observation.state == PrimaryState.WAIT_CLEAR
    assert not observation.opportunity_active
    assert observation.plan is not None
    assert observation.plan.entry_reference == pytest.approx(7414.3)
    assert observation.plan.invalidation == pytest.approx(7437.12382281287)
    assert observation.plan.risk == pytest.approx(22.823822812869366)
    assert observation.plan.next_named_level is None
    assert observation.plan.next_named_level_source == NamedLevelSource.UNKNOWN
    assert observation.plan.space_r is None
    assert len(observation.frozen_candidates) == 1
    candidate = observation.frozen_candidates[0]
    assert candidate.price == pytest.approx(7418.1)
    assert candidate.source == NamedLevelSource.PRIOR_EXCURSION_10M
    assert candidate.consumed


def test_2026_07_30_0710_long_routes_to_nearest_unconsumed_pivot_and_main() -> None:
    _, observations = _replay()
    observation = _at(observations, B_TIMESTAMP_MS)
    assert observation.event == PrimaryEvent.MAIN_LONG
    assert observation.reason_code == ReasonCode.MAIN_OPPORTUNITY_ACTIVE
    assert observation.state == PrimaryState.ACTIVE
    assert observation.opportunity_active
    assert observation.plan is not None
    assert observation.plan.entry_reference == pytest.approx(7362.6)
    assert observation.plan.invalidation == pytest.approx(7345.73843697133)
    assert observation.plan.risk == pytest.approx(16.86156302867039)
    assert observation.plan.next_named_level == pytest.approx(7450.2)
    assert (
        observation.plan.next_named_level_source
        == NamedLevelSource.CONFIRMED_PIVOT_10M
    )
    assert observation.plan.space == pytest.approx(87.6)
    assert observation.plan.space_r == pytest.approx(5.195247905016259)

    frozen = list(observation.frozen_candidates)
    assert [(item.price, item.source, item.consumed) for item in frozen] == [
        (pytest.approx(7361.8), NamedLevelSource.CONFIRMED_PIVOT_10M, True),
        (pytest.approx(7450.2), NamedLevelSource.CONFIRMED_PIVOT_10M, False),
    ]
    assert all(
        item.source != NamedLevelSource.PREVIOUS_COMPLETED_DAY_HIGH
        for item in frozen
    )


def test_replay_cli_runs_directly_from_clean_source_root(tmp_path: Path) -> None:
    script = ROOT / "research/replay_phase1_10m_primary_opportunity_r3.py"
    log = tmp_path / "replay.log"
    events = tmp_path / "events.csv"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--csv",
            str(CSV),
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
    assert "bars=337" in text
    assert "result=SPACE_UNKNOWN" in text
    assert "result=MAIN_LONG" in text
