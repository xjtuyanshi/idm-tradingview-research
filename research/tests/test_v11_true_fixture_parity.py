"""Event-level parity guard against the private true-v11 TradingView export.

The fixture triple lives OUTSIDE the repository (hard publication constraint:
no proprietary market exports in the public tree).  Default location below;
override with the ``IDM_FIXTURE_DIR`` environment variable.  The test skips
in any checkout without the private data — exactly like the legacy v10.1R
fixture tests.

Asserted parity floor (established 2026-07-21, see
research/reports/IDM_V11_PARITY_2026-07-21.md):

* every Pine SignalEvent id/setup/grade/mask is reproduced by the replica;
* every Pine plan-event pulse is reproduced;
* the eleven feature series (EMAs, confirmed-10m context, S1/R1, breakout
  references) are exactly equal on every compared bar;
* replica-only extras are tolerated up to a small bound: each investigated
  case sits on a sub-1e-11 float boundary where Pine's own 3m and 10m hosts
  can disagree with each other.  Blocker codes share that boundary class and
  are reported by parity_check but not gated here.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

RESEARCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_DIR))

DEFAULT_FIXTURE_DIR = Path.home() / "claude code projects" / "idm-fixtures" / "2026-07-21"
FIXTURE_DIR = Path(os.environ.get("IDM_FIXTURE_DIR", DEFAULT_FIXTURE_DIR))

EXACT_FIELDS = (
    "ema5", "ema12", "ctx_ema34", "ctx_ema50", "ctx_time",
    "ctx_dir", "ctx_pace", "support", "resistance",
    "next_buy_trigger", "next_sell_trigger",
)


@unittest.skipUnless(
    FIXTURE_DIR.is_dir() and any(FIXTURE_DIR.glob("*_3M_*.csv")),
    "private true-v11 TradingView fixtures are not redistributed",
)
class TrueFixtureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from parity_check import run

        cls.stats = run(str(FIXTURE_DIR))

    def test_every_pine_signal_is_reproduced(self) -> None:
        self.assertEqual(self.stats["missing"], 0, self.stats["missing_detail"])
        self.assertEqual(self.stats["wrong_meta"], 0)
        self.assertGreaterEqual(self.stats["matched"], 200)

    def test_every_pine_plan_event_is_reproduced(self) -> None:
        self.assertEqual(self.stats["event_missing"], 0, self.stats["event_detail"])

    def test_feature_series_are_bit_exact(self) -> None:
        bad = {
            name: diff.mismatched
            for name, diff in self.stats["diffs"].items()
            if name in EXACT_FIELDS and diff.mismatched
        }
        self.assertEqual(bad, {})

    def test_replica_extras_stay_within_float_boundary_bound(self) -> None:
        self.assertLessEqual(len(self.stats["extra"]), 4, [
            (s.close_ms // 1000 - 180, s.id) for s in self.stats["extra"]
        ])


if __name__ == "__main__":
    unittest.main()
