"""Statistics helpers with the honesty rails this project keeps needing.

Two rules encoded here, both learned the expensive way:

  1. A base rate without an interval is a story.  `wilson` is used everywhere
     so every reported percentage carries its own uncertainty.
  2. A cell picked out of a grid is not a finding.  `family_note` records how
     many cells were inspected so the reader can discount accordingly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion — sane at small n and at 0/1."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


def fmt_rate(k: int, n: int) -> str:
    if n == 0:
        return "    n=0"
    lo, hi = wilson(k, n)
    return f"{100*k/n:5.1f}%  [{100*lo:4.1f},{100*hi:5.1f}]  n={n}"


@dataclass
class RateCell:
    k: int = 0
    n: int = 0

    def add(self, hit: bool) -> None:
        self.n += 1
        self.k += int(hit)

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.k, self.n)

    def __str__(self) -> str:
        return fmt_rate(self.k, self.n)


@dataclass
class RateTable:
    """A named grid of base rates that remembers how big the family was."""
    title: str
    cells: dict = field(default_factory=dict)

    def add(self, key, hit: bool) -> None:
        self.cells.setdefault(key, RateCell()).add(hit)

    def render(self, order: list | None = None, min_n: int = 1) -> str:
        keys = order or sorted(self.cells)
        lines = [f"{self.title}", "-" * len(self.title)]
        for k in keys:
            c = self.cells.get(k)
            if not c or c.n < min_n:
                continue
            lines.append(f"  {str(k):<28}{c}")
        lines.append(f"  [family: {len(self.cells)} cells inspected]")
        return "\n".join(lines)


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> float:
    """Z for H0: p1 == p2.  Use to check whether a split is doing any work."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se > 0 else 0.0


def expectancy(rs: list[float]) -> dict:
    """R-multiple summary with the flats separated out (0R != loss)."""
    eps = 1e-12
    n = len(rs)
    if n == 0:
        return {"n": 0}
    wins = [r for r in rs if r > eps]
    losses = [r for r in rs if r < -eps]
    flats = n - len(wins) - len(losses)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    breakeven = (-al / (aw - al)) if (aw - al) else 0.0
    return {"n": n, "avg_r": sum(rs) / n, "total_r": sum(rs),
            "win_rate": len(wins) / n, "flats": flats,
            "avg_win": aw, "avg_loss": al, "breakeven_wr": breakeven,
            "max_dd": mdd}


def fmt_expectancy(e: dict) -> str:
    if e.get("n", 0) == 0:
        return "n=0"
    return (f"n={e['n']:<4} 均R={e['avg_r']:+.3f} 总R={e['total_r']:+.1f} "
            f"胜率={100*e['win_rate']:.1f}% (平局{e['flats']}) "
            f"均赢={e['avg_win']:+.2f} 均亏={e['avg_loss']:+.2f} "
            f"打平需={100*e['breakeven_wr']:.1f}% 回撤={e['max_dd']:.1f}R")
