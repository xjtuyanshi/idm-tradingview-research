#!/usr/bin/env python3
"""Render the only two available real R3 10m-to-3m linked cases.

This is a causal visual audit of the limited Jul-30 sample, not a win-rate or
profitability report. Bar labels state the first closed-bar time when each event
could have been known.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from research.render_trader_utility_casebook_20260802 import (
    BG,
    BLUE,
    DOWN,
    F_SUB,
    F_TITLE,
    GOLD,
    INK,
    MUTED,
    UP,
    _panel,
    _read_rows,
    _select,
)


def render(csv_path: Path, output: Path) -> None:
    rows = _read_rows(csv_path)
    image = Image.new("RGB", (1920, 850), BG)
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "当前 R3｜仅有的两条真实 10m → 3m 联动链", fill=INK, font=F_TITLE)
    draw.text(
        (70, 88),
        "样本只有约 2.5 天：一条空计划失败，一条多计划到达；只能验语义，不能估胜率。",
        fill=MUTED,
        font=F_SUB,
    )

    _panel(
        image,
        _select(rows, "2026-07-30", "02:00", "03:24"),
        (50, 145, 945, 790),
        "A｜空计划：链条完整，但这笔 timing 很差",
        "10m plan 02:20 known｜3m 空入 02:33 known｜空失 03:03 known",
        [
            {
                "time": "02:21",
                "color": GOLD,
                "box": (55, 86, 300, 174),
                "lines": ["10m 空计划", "02:20 known", "等 3m 空入"],
            },
            {
                "time": "02:30",
                "color": DOWN,
                "box": (315, 86, 555, 174),
                "lines": ["3m 空入", "02:33 known", "entry 7332.0"],
            },
            {
                "time": "03:00",
                "color": BLUE,
                "box": (570, 86, 840, 174),
                "lines": ["3m 空失", "03:03 known", "保护 7347.6"],
            },
        ],
        protection=7347.569479,
        target=7291.7,
    )

    _panel(
        image,
        _select(rows, "2026-07-30", "07:00", "16:09"),
        (975, 145, 1870, 790),
        "B｜多计划：10m 给方向，3m 给入场，原 owner 管到目标",
        "10m plan 07:20 known｜3m 多入 07:39 known｜多达 16:03 known",
        [
            {
                "time": "07:21",
                "color": GOLD,
                "box": (55, 86, 300, 174),
                "lines": ["10m 多计划", "07:20 known", "等 3m 多入"],
            },
            {
                "time": "07:36",
                "color": UP,
                "box": (315, 86, 555, 174),
                "lines": ["3m 多入", "07:39 known", "entry 7368.3"],
            },
            {
                "time": "16:00",
                "color": BLUE,
                "box": (570, 86, 840, 174),
                "lines": ["3m 多达", "16:03 known", "目标 7450.2"],
            },
        ],
        protection=7345.738437,
        target=7450.2,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.csv, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
