#!/usr/bin/env python3
"""Render four causal trader-review cases from the 33-day TradingView export.

This is a visual audit aid, not a strategy backtest or profitability study.
Signal times are bar-open times; each annotation also states the first time the
closed-bar event could have been known.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


ET = ZoneInfo("America/New_York")
BG = "#0d1422"
PANEL = "#111c2d"
GRID = "#344054"
INK = "#f5f7fb"
MUTED = "#aab4c5"
UP = "#22c7b8"
DOWN = "#f05b63"
GOLD = "#f6b73c"
BLUE = "#4f8cff"
MAGENTA = "#db68ff"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    )
    for path in candidates:
        if Path(path).is_file():
            try:
                # PingFang's second TTC face renders as missing glyphs on some
                # macOS/Pillow builds. Use the verified CJK face for every
                # weight; legibility matters more than synthetic bold here.
                return ImageFont.truetype(path, size=size, index=0)
            except OSError:
                continue
    return ImageFont.load_default()


F_TITLE = _font(36, True)
F_SUB = _font(20)
F_PANEL = _font(25, True)
F_SMALL = _font(17)
F_TINY = _font(15)


def _parse_time(row: dict[str, str]) -> datetime:
    return datetime.fromtimestamp(int(row["time"]), timezone.utc).astimezone(ET)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["_dt"] = _parse_time(row).isoformat()
    return rows


def _select(
    rows: list[dict[str, str]], day: str, start: str, end: str
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row["_dt"][:10] == day and start <= row["_dt"][11:16] <= end
    ]


def _time(row: dict[str, str]) -> str:
    return row["_dt"][11:16]


def _value(row: dict[str, str], key: str) -> float | None:
    text = row.get(key, "").strip()
    return None if not text else float(text)


def _event_index(rows: list[dict[str, str]], hhmm: str) -> int:
    return next(i for i, row in enumerate(rows) if _time(row) == hhmm)


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: str,
    outline: str,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(xy, radius=10, fill=fill, outline=outline, width=width)


def _callout(
    draw: ImageDraw.ImageDraw,
    anchor: tuple[int, int],
    box: tuple[int, int, int, int],
    lines: list[str],
    color: str,
) -> None:
    x0, y0, x1, y1 = box
    draw.line((anchor[0], anchor[1], (x0 + x1) // 2, y1), fill=color, width=2)
    _rounded_rect(draw, box, "#0b1220", color, 2)
    y = y0 + 9
    for index, line in enumerate(lines):
        draw.text((x0 + 12, y), line, fill=INK if index else color, font=F_TINY)
        y += 21


def _panel(
    image: Image.Image,
    rows: list[dict[str, str]],
    bounds: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    events: list[dict[str, object]],
    protection: float | None = None,
    target: float | None = None,
) -> None:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = bounds
    _rounded_rect(draw, bounds, PANEL, "#26354b", 2)
    draw.text((x0 + 22, y0 + 16), title, fill=INK, font=F_PANEL)
    draw.text((x0 + 22, y0 + 50), subtitle, fill=MUTED, font=F_SMALL)

    plot_left, plot_right = x0 + 62, x1 - 24
    plot_top, plot_bottom = y0 + 126, y1 - 58
    lows = [float(row["low"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    pad = max(2.0, (max(highs) - min(lows)) * 0.10)
    lo, hi = min(lows) - pad, max(highs) + pad

    def sx(index: int) -> int:
        return int(plot_left + index * (plot_right - plot_left) / max(1, len(rows) - 1))

    def sy(value: float) -> int:
        return int(plot_bottom - (value - lo) * (plot_bottom - plot_top) / (hi - lo))

    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        price = lo + fraction * (hi - lo)
        y = sy(price)
        draw.line((plot_left, y, plot_right, y), fill=GRID, width=1)
        draw.text((x0 + 9, y - 9), f"{price:,.0f}", fill=MUTED, font=F_TINY)

    if protection is not None:
        y = sy(protection)
        draw.line((plot_left, y, plot_right, y), fill=GOLD, width=2)
        draw.text((plot_right - 120, y - 21), f"保护 {protection:.1f}", fill=GOLD, font=F_TINY)

    if target is not None:
        y = sy(target)
        draw.line((plot_left, y, plot_right, y), fill=BLUE, width=2)
        draw.text((plot_right - 120, y - 21), f"目标 {target:.1f}", fill=BLUE, font=F_TINY)

    candle_width = max(4, int((plot_right - plot_left) / max(1, len(rows)) * 0.55))
    for i, row in enumerate(rows):
        x = sx(i)
        open_, high, low, close = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
        color = UP if close >= open_ else DOWN
        draw.line((x, sy(high), x, sy(low)), fill=color, width=2)
        top, bottom = sorted((sy(open_), sy(close)))
        if bottom - top < 2:
            bottom = top + 2
        draw.rectangle(
            (x - candle_width // 2, top, x + candle_width // 2, bottom),
            fill=color,
        )

    for key, color in (("3m EMA5", UP), ("3m EMA12", DOWN)):
        points = [
            (sx(i), sy(float(row[key])))
            for i, row in enumerate(rows)
            if row.get(key, "").strip()
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=2)

    tick_indices = sorted({0, len(rows) // 4, len(rows) // 2, 3 * len(rows) // 4, len(rows) - 1})
    for i in tick_indices:
        draw.text((sx(i) - 20, plot_bottom + 10), _time(rows[i]), fill=MUTED, font=F_TINY)
    draw.text((plot_right - 22, plot_bottom + 31), "ET", fill=MUTED, font=F_TINY)

    for event in events:
        i = _event_index(rows, str(event["time"]))
        price_key = str(event.get("price", "close"))
        anchor = (sx(i), sy(float(rows[i][price_key])))
        color = str(event["color"])
        draw.ellipse((anchor[0] - 6, anchor[1] - 6, anchor[0] + 6, anchor[1] + 6), fill=color, outline=INK, width=1)
        box_rel = event["box"]
        assert isinstance(box_rel, tuple)
        box = (
            x0 + int(box_rel[0]),
            y0 + int(box_rel[1]),
            x0 + int(box_rel[2]),
            y0 + int(box_rel[3]),
        )
        _callout(draw, anchor, box, list(event["lines"]), color)


def render(csv_path: Path, output: Path) -> None:
    rows = _read_rows(csv_path)
    image = Image.new("RGB", (1920, 1500), BG)
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "33 天旧信号｜四个无后视镜 Trader 案例", fill=INK, font=F_TITLE)
    draw.text(
        (70, 88),
        "每个信号只在该 K 收盘后可知；MFE/MAE 为 SPX 点数，不含点差、滑点、期权价格与成交。",
        fill=MUTED,
        font=F_SUB,
    )

    panels = (
        (
            _select(rows, "2026-07-30", "08:30", "11:00"),
            (50, 145, 945, 790),
            "A｜有效例：趋势多确实帮助跟随",
            "09:00 bar 事件 09:03 才可知｜next-open MFE +44.5 / MAE -3.3",
            [
                {"time": "09:00", "color": BLUE, "box": (120, 86, 415, 153), "lines": ["趋势多｜09:03 known", "计划 owner 清楚，可改变动作"]},
                {"time": "10:45", "color": GOLD, "box": (560, 86, 842, 153), "lines": ["多头退｜10:48 known", "入场与退出链条完整"]},
            ],
            7362.2924061789345,
        ),
        (
            _select(rows, "2026-07-20", "07:00", "08:15"),
            (975, 145, 1870, 790),
            "B｜坏例：大绿 K 顶部追多",
            "07:30 bar 事件 07:33 才可知｜next-open MFE +3.2 / MAE -20.3",
            [
                {"time": "07:30", "color": DOWN, "box": (115, 86, 430, 153), "lines": ["趋势多｜07:33 known", "位置/空间未前置，容易追涨"]},
                {"time": "08:03", "color": GOLD, "box": (560, 86, 842, 153), "lines": ["多头退｜08:06 known", "退出正确，但已经明显滞后"]},
            ],
            7483.4,
        ),
        (
            _select(rows, "2026-07-29", "09:00", "12:45"),
            (50, 825, 945, 1468),
            "C｜断链例：没显示空计划，却显示空头退",
            "底层 09:27 空 plan 09:30 可知｜主图被“冲突”遮住｜MFE +82.1 / MAE -4.0",
            [
                {"time": "09:27", "color": MAGENTA, "box": (95, 86, 445, 174), "lines": ["底层空 plan｜09:30 known", "主图只画“方向冲突”", "Trader 没收到可执行入口"]},
                {"time": "12:24", "color": GOLD, "box": (555, 86, 850, 174), "lines": ["空头退｜12:27 known", "孤立退出对实盘没有意义", "这是 lifecycle/UI 硬缺陷"]},
            ],
            7430.815022259778,
        ),
        (
            _select(rows, "2026-07-31", "11:00", "12:10"),
            (975, 825, 1870, 1468),
            "D｜冲突例：支撑证据出现后，空计划退出太晚",
            "所有时间均为 bar open；括号内为最早 known time",
            [
                {"time": "11:24", "price": "low", "color": GOLD, "box": (80, 86, 350, 174), "lines": ["空计划 + 近支撑", "11:27 known", "此刻应停止追空"]},
                {"time": "11:36", "color": BLUE, "box": (365, 86, 625, 174), "lines": ["反弹确认", "11:39 known", "应否决旧空场景"]},
                {"time": "11:51", "color": DOWN, "box": (640, 86, 858, 174), "lines": ["空头退", "11:54 known", "管理信号滞后"]},
            ],
            7421.204591,
        ),
    )
    for args in panels:
        _panel(image, *args)

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
