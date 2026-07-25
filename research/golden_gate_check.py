#!/usr/bin/env python3
"""Independent reproduction of the Saty Golden Gate completion statistics.

Reference figures (posted by Saty in #lessons, computed by @tesrak from ten
years of SPX data) claim that once price triggers the Golden Gate — crossing
0.382 x daily ATR away from the previous close — the probability of reaching
0.618 x ATR the same day starts near 91% for an open trigger and decays to
single digits for a 15:00 trigger.

This script rebuilds those numbers from scratch on Yahoo ^GSPC data so we can
check two things before trusting the setup:

  1. Level math: does our anchor/ATR/gate construction produce a sane
     unconditional completion rate on a decade of daily bars?
  2. Decay shape: does completion probability fall monotonically with the
     trigger hour, as the reference claims?

Nothing here is fitted.  There are no free parameters: the anchor is the prior
daily close, the ATR is Wilder's 14-period ATR as of the prior close (matching
`ta.atr(14)[1]` in the Pine engine), and the gates are fixed Fibonacci ratios.

Usage: python research/golden_gate_check.py
"""

from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TRIGGER_RATIO = 0.382
GATE_RATIO = 0.618
ATR_LEN = 14
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(symbol: str, rng: str, interval: str) -> dict:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={rng}&interval={interval}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def bars(payload: dict) -> list[dict]:
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        dt = datetime.fromtimestamp(ts, ET)
        out.append({"dt": dt, "day": dt.date(), "open": o, "high": h,
                    "low": l, "close": c})
    return out


def wilder_atr(daily: list[dict], length: int = ATR_LEN) -> list[float | None]:
    """Wilder's ATR, aligned so atr[i] is the value as of bar i's close."""
    trs = []
    for i, b in enumerate(daily):
        if i == 0:
            trs.append(b["high"] - b["low"])
        else:
            pc = daily[i - 1]["close"]
            trs.append(max(b["high"] - b["low"], abs(b["high"] - pc),
                           abs(b["low"] - pc)))
    atr: list[float | None] = [None] * len(daily)
    if len(daily) < length:
        return atr
    seed = sum(trs[:length]) / length
    atr[length - 1] = seed
    prev = seed
    for i in range(length, len(daily)):
        prev = (prev * (length - 1) + trs[i]) / length
        atr[i] = prev
    return atr


def build_levels(daily: list[dict]) -> dict:
    """day -> anchor/atr/gate levels, using ONLY prior-close information."""
    atr = wilder_atr(daily)
    levels = {}
    for i in range(1, len(daily)):
        a, prev_atr = daily[i - 1]["close"], atr[i - 1]
        if prev_atr is None or prev_atr <= 0:
            continue
        levels[daily[i]["day"]] = {
            "anchor": a,
            "atr": prev_atr,
            "bull_trigger": a + TRIGGER_RATIO * prev_atr,
            "bull_gate": a + GATE_RATIO * prev_atr,
            "bear_trigger": a - TRIGGER_RATIO * prev_atr,
            "bear_gate": a - GATE_RATIO * prev_atr,
        }
    return levels


def daily_unconditional(daily: list[dict], levels: dict) -> dict:
    """P(reach 0.618 | reached 0.382) using daily highs/lows only."""
    stats = {"bull": [0, 0], "bear": [0, 0]}
    for b in daily:
        lv = levels.get(b["day"])
        if not lv:
            continue
        if b["high"] >= lv["bull_trigger"]:
            stats["bull"][0] += 1
            if b["high"] >= lv["bull_gate"]:
                stats["bull"][1] += 1
        if b["low"] <= lv["bear_trigger"]:
            stats["bear"][0] += 1
            if b["low"] <= lv["bear_gate"]:
                stats["bear"][1] += 1
    return stats


def hourly_by_trigger_bucket(hourly: list[dict], levels: dict) -> dict:
    """Completion rate split by the bar in which the gate was triggered.

    An 'Open' trigger means the session's first bar opened already beyond the
    trigger level (a gap through the gate); otherwise the bucket is the bar
    whose high/low first crossed it.
    """
    by_day: dict = defaultdict(list)
    for b in hourly:
        by_day[b["day"]].append(b)

    res = {"bull": defaultdict(lambda: [0, 0]),
           "bear": defaultdict(lambda: [0, 0])}
    for day, session in sorted(by_day.items()):
        lv = levels.get(day)
        if not lv or len(session) < 4:
            continue
        session.sort(key=lambda x: x["dt"])
        for side in ("bull", "bear"):
            trig = lv[f"{side}_trigger"]
            gate = lv[f"{side}_gate"]
            hit = None
            for i, b in enumerate(session):
                crossed = (b["high"] >= trig) if side == "bull" \
                    else (b["low"] <= trig)
                if crossed:
                    gapped = (b["open"] >= trig) if side == "bull" \
                        else (b["open"] <= trig)
                    hit = (i, "Open" if (i == 0 and gapped)
                           else b["dt"].strftime("%H:%M"))
                    break
            if hit is None:
                continue
            i0, bucket = hit
            done = any((b["high"] >= gate) if side == "bull"
                       else (b["low"] <= gate) for b in session[i0:])
            res[side][bucket][0] += 1
            res[side][bucket][1] += int(done)
    return res


BUCKET_ORDER = ["Open", "09:30", "10:30", "11:30", "12:30", "13:30",
                "14:30", "15:30"]

STOP_RATIO = 0.236  # the named Saty call/put trigger level — not invented


def path_aware_r(hourly: list[dict], levels: dict,
                 buckets: set[str] | None = None) -> dict:
    """Conservative R simulation: does the completion rate survive the path?

    A completion statistic says nothing about whether the stop was hit first.
    Here we walk the session bar by bar from the trigger, stop at the 0.236
    level, target the 0.618 gate, and resolve any bar that contains BOTH as a
    stop (worst case, matching the exit-lab convention).  Unresolved positions
    settle at the session close.  Gap-through entries fill at the open, which
    widens risk exactly as it would in practice.
    """
    by_day: dict = defaultdict(list)
    for b in hourly:
        by_day[b["day"]].append(b)

    out = {"bull": [], "bear": []}
    skipped = {"bull": 0, "bear": 0}
    for day, session in sorted(by_day.items()):
        lv = levels.get(day)
        if not lv or len(session) < 4:
            continue
        session.sort(key=lambda x: x["dt"])
        for side in ("bull", "bear"):
            sign = 1 if side == "bull" else -1
            trig, gate = lv[f"{side}_trigger"], lv[f"{side}_gate"]
            stop = lv["anchor"] + sign * STOP_RATIO * lv["atr"]
            idx = None
            for i, b in enumerate(session):
                if (b["high"] >= trig) if side == "bull" else (b["low"] <= trig):
                    gapped = (b["open"] >= trig) if side == "bull" \
                        else (b["open"] <= trig)
                    idx = (i, "Open" if (i == 0 and gapped)
                           else b["dt"].strftime("%H:%M"))
                    break
            if idx is None:
                continue
            i0, bucket = idx
            if buckets is not None and bucket not in buckets:
                continue
            first = session[i0]
            entry = (max(first["open"], trig) if side == "bull"
                     else min(first["open"], trig))
            # gapped clean through the whole gate: no entry was available
            if (entry >= gate) if side == "bull" else (entry <= gate):
                skipped[side] += 1
                continue
            risk = abs(entry - stop)
            if risk <= 1e-9:
                continue
            r = None
            for b in session[i0:]:
                hit_stop = (b["low"] <= stop) if side == "bull" \
                    else (b["high"] >= stop)
                hit_tgt = (b["high"] >= gate) if side == "bull" \
                    else (b["low"] <= gate)
                if hit_stop:            # conservative: stop wins ties
                    r = -1.0
                    break
                if hit_tgt:
                    r = abs(gate - entry) / risk
                    break
            if r is None:
                r = sign * (session[-1]["close"] - entry) / risk
            out[side].append(r)
    return {"r": out, "skipped": skipped}


def report_r(tag: str, res: dict) -> None:
    print(f"\n  {tag}")
    for side, label in (("bull", "Bullish GG"), ("bear", "Bearish GG")):
        rs = res["r"][side]
        if not rs:
            print(f"    {label}: no trades")
            continue
        n = len(rs)
        wins = [x for x in rs if x > 1e-9]
        losses = [x for x in rs if x < -1e-9]
        avg = sum(rs) / n
        aw = sum(wins) / len(wins) if wins else 0.0
        al = sum(losses) / len(losses) if losses else 0.0
        print(f"    {label}: n={n:<4} 均R={avg:+.3f}  胜率={100*len(wins)/n:.1f}%"
              f"  均赢={aw:+.2f}  均亏={al:+.2f}  总R={sum(rs):+.1f}"
              f"  (跳过{res['skipped'][side]}笔跳空穿透)")


def mae_study(fine: list[dict], levels: dict) -> dict:
    """Where does the stop have to sit?  Measured, not guessed.

    Section 3 could not answer this: an hourly bar is wider than the whole
    0.382->0.236 stop distance, so the stop-first convention decided almost
    every trade by itself.  Here we use 5m bars and record, for each trigger,
    the maximum adverse excursion (in ATR units below/above the anchor) before
    the gate completes — i.e. how deep a pullback a winner had to survive.
    """
    by_day: dict = defaultdict(list)
    for b in fine:
        by_day[b["day"]].append(b)

    out = {"bull": [], "bear": []}
    for day, session in sorted(by_day.items()):
        lv = levels.get(day)
        if not lv or len(session) < 20:
            continue
        session.sort(key=lambda x: x["dt"])
        for side in ("bull", "bear"):
            sign = 1 if side == "bull" else -1
            trig, gate = lv[f"{side}_trigger"], lv[f"{side}_gate"]
            i0 = None
            for i, b in enumerate(session):
                if (b["high"] >= trig) if side == "bull" else (b["low"] <= trig):
                    i0 = i
                    break
            if i0 is None:
                continue
            worst = trig  # most adverse price seen after the trigger
            done = False
            for b in session[i0:]:
                adverse = b["low"] if side == "bull" else b["high"]
                worst = min(worst, adverse) if side == "bull" \
                    else max(worst, adverse)
                if (b["high"] >= gate) if side == "bull" else (b["low"] <= gate):
                    done = True
                    break
            # express the worst excursion as a ratio of ATR from the anchor
            ratio = sign * (worst - lv["anchor"]) / lv["atr"]
            out[side].append((done, ratio))
    return out


def report_mae(res: dict) -> None:
    for side, label in (("bull", "Bullish GG"), ("bear", "Bearish GG")):
        rows = res[side]
        if not rows:
            continue
        winners = [r for done, r in rows if done]
        losers = [r for done, r in rows if not done]
        print(f"\n  {label}: 触发 {len(rows)} 次，完成 {len(winners)} 次 "
              f"({100 * len(winners) / len(rows):.1f}%)")
        if winners:
            ws = sorted(winners)
            print("    完成者(赢单)在完成前的最深回撤位（ATR 比例，0=前收锚）:")
            print(f"      中位 {ws[len(ws)//2]:.3f}   最深 {ws[0]:.3f}")
            for lvl in (0.300, 0.236, 0.150, 0.000):
                survived = sum(1 for r in winners if r < lvl)
                print(f"      止损放 {lvl:.3f} 会打掉 {survived:>3}/"
                      f"{len(winners)} 笔赢单 "
                      f"({100 * survived / len(winners):.1f}%)")
        if losers:
            ls = sorted(losers)
            print(f"    未完成者(输单) 最深回撤中位 {ls[len(ls)//2]:.3f}")


def simulate_fine(fine: list[dict], levels: dict, stop_ratio: float,
                  buckets: set[str] | None = None) -> dict:
    """Same trade as section 3 but resolved on 5m bars (no tie ambiguity)."""
    by_day: dict = defaultdict(list)
    for b in fine:
        by_day[b["day"]].append(b)
    out = {"bull": [], "bear": []}
    skipped = {"bull": 0, "bear": 0}
    for day, session in sorted(by_day.items()):
        lv = levels.get(day)
        if not lv or len(session) < 20:
            continue
        session.sort(key=lambda x: x["dt"])
        for side in ("bull", "bear"):
            sign = 1 if side == "bull" else -1
            trig, gate = lv[f"{side}_trigger"], lv[f"{side}_gate"]
            stop = lv["anchor"] + sign * stop_ratio * lv["atr"]
            i0 = None
            for i, b in enumerate(session):
                if (b["high"] >= trig) if side == "bull" else (b["low"] <= trig):
                    i0 = i
                    break
            if i0 is None:
                continue
            hhmm = session[i0]["dt"].strftime("%H:%M")
            bucket = "Open" if i0 == 0 else ("09:30" if hhmm < "10:30"
                                             else "late")
            if buckets is not None and bucket not in buckets:
                continue
            first = session[i0]
            entry = (max(first["open"], trig) if side == "bull"
                     else min(first["open"], trig))
            if (entry >= gate) if side == "bull" else (entry <= gate):
                skipped[side] += 1
                continue
            risk = abs(entry - stop)
            if risk <= 1e-9:
                continue
            r = None
            for b in session[i0:]:
                if (b["low"] <= stop) if side == "bull" else (b["high"] >= stop):
                    r = -1.0
                    break
                if (b["high"] >= gate) if side == "bull" else (b["low"] <= gate):
                    r = abs(gate - entry) / risk
                    break
            if r is None:
                r = sign * (session[-1]["close"] - entry) / risk
            out[side].append(r)
    return {"r": out, "skipped": skipped}


def main() -> None:
    print("Fetching ^GSPC daily (10y) and hourly (730d) from Yahoo ...\n")
    daily = bars(fetch("%5EGSPC", "10y", "1d"))
    hourly = bars(fetch("%5EGSPC", "730d", "1h"))
    levels = build_levels(daily)

    print(f"Daily bars: {len(daily)}  ({daily[0]['day']} -> {daily[-1]['day']})")
    print(f"Hourly bars: {len(hourly)} ({hourly[0]['day']} -> "
          f"{hourly[-1]['day']})\n")

    print("=" * 68)
    print("1. UNCONDITIONAL completion rate  P(0.618 | 0.382)  — daily bars")
    print("=" * 68)
    st = daily_unconditional(daily, levels)
    for side, label in (("bull", "Bullish GG"), ("bear", "Bearish GG")):
        n, k = st[side]
        rate = 100 * k / n if n else 0.0
        base = 100 * n / len(levels)
        print(f"  {label}:  triggered {n:>5} days ({base:.1f}% of sessions)"
              f"   completed {k:>5}   -> {rate:.1f}%")

    print()
    print("=" * 68)
    print("2. Completion rate BY TRIGGER BUCKET — hourly bars (~2 years)")
    print("   Reference (tesrak, 10y): bull 90.9% at open -> 9.1% at 15:00")
    print("=" * 68)
    hb = hourly_by_trigger_bucket(hourly, levels)
    for side, label in (("bull", "Bullish GG"), ("bear", "Bearish GG")):
        print(f"\n  {label}")
        print(f"    {'trigger':<9}{'n':>6}{'completed':>11}{'rate':>9}")
        tot_n = tot_k = 0
        for b in BUCKET_ORDER:
            n, k = hb[side].get(b, [0, 0])
            if n == 0:
                continue
            tot_n += n
            tot_k += k
            print(f"    {b:<9}{n:>6}{k:>11}{100 * k / n:>8.1f}%")
        if tot_n:
            print(f"    {'ALL':<9}{tot_n:>6}{tot_k:>11}"
                  f"{100 * tot_k / tot_n:>8.1f}%")

    print()
    print("=" * 68)
    print("3. PATH-AWARE R — completion rate is not an edge until the stop")
    print("   survives.  Entry 0.382 (or the open on a gap), stop 0.236,")
    print("   target 0.618, ties resolved as stop-first, close-out at EOD.")
    print("=" * 68)
    report_r("全部触发时段", path_aware_r(hourly, levels))
    report_r("只做 Open + 09:30（高基准率窗口）",
             path_aware_r(hourly, levels, {"Open", "09:30"}))
    report_r("只做 10:30 之后（低基准率窗口，对照组）",
             path_aware_r(hourly, levels,
                          {"10:30", "11:30", "12:30", "13:30", "14:30",
                           "15:30"}))
    print("\n  ⚠ 上面这一节不可信：1 小时 K 的振幅通常大于 0.382->0.236 的整个")
    print("    止损距离，'同根K撞到止损算止损' 的保守规则等于替所有交易做了裁决。")
    print("    真正的答案需要更细的数据，见第 4 节。")

    print()
    print("=" * 68)
    print("4. 止损该放哪 — 5 分钟 K 实测最大不利偏移（近 60 天）")
    print("=" * 68)
    fine = bars(fetch("%5EGSPC", "60d", "5m"))
    print(f"  5m bars: {len(fine)} ({fine[0]['day']} -> {fine[-1]['day']})")
    report_mae(mae_study(fine, levels))

    print()
    print("=" * 68)
    print("5. 5 分钟 K 重做交易模拟（无同根K歧义）")
    print("=" * 68)
    for sr in (0.236, 0.150, 0.000):
        report_r(f"止损 {sr:.3f} ATR · 全时段",
                 simulate_fine(fine, levels, sr))
    report_r("止损 0.000 ATR(前收锚) · 只做 Open+09:30",
             simulate_fine(fine, levels, 0.0, {"Open", "09:30"}))


if __name__ == "__main__":
    main()
