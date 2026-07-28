#!/usr/bin/env python3
"""任务 2：把「入场与出场共用一条 13 EMA」这个嫌疑量化到底。

v14 的 Recovery 与 Vomy 都用同一条线做门：收盘站上 13 入场、收盘跌破 13 出场。
在 EMA 附近震荡时，这在结构上保证了反复进出。本脚本量化三件事：

  Q1  穿越频率基准 —— 多头排列时收盘穿 13 EMA 的平均间隔（3m / 10m / 1h）。
      这直接给出「同线进出」能造成的交易频率上界（= 穿越率 / 2）。
  Q2  同线 vs 分离阈值 —— 入场规则逐字不变，只换出场阈值：
      E0 收盘穿 13（现状）/ E1 穿 21 / E2 穿 34 / E3 穿 48 /
      E4 只用保护位，到 T2 后才用 13 跟踪 / E5 ATR 追踪止损（1.0 与 1.5）。
      六个候选全部报告。
  Q3  迟滞 —— 出场仍用 13，但要求连续 2（及 3）根收盘在 13 之外。
  Q4  归因 —— 同线进出贡献了多少笔 churn、多少 R 的损失。

零假设纪律
----------
几何零假设 S/(S+T) 只是「无漂移随机游走 + 纯括号单」的特例。一旦出场是路径
依赖的（收盘穿某条 EMA、ATR 追踪），正确的推广是**鞅零假设 E[R]=0**：任何
停时规则作用在无漂移价格上，期望 R 都是 0。因此每个变体报告两个 z：
  z_geom  —— 纯括号单（保护位 vs T1）的先到概率 vs Σ S/(S+T1)，用泊松二项。
             它只刻画**入场质量**，与出场规则无关。
  z_R     —— 实际 R 的 mean/(sd/√n)，对 E[R]=0。
外加一个**经验零假设**：对 10m 收益率做循环分块自助（去均值），重建合成价格
序列，把同一套入场+出场机器跑在随机游走上，得到每个变体总 R 的经验分布。

标的与口径
----------
  主样本  ES=F 10m（由缓存 60d 5m 聚合）—— 唯一带完整夜盘的缓存数据，
          与线上账本 CAPITALCOM:SPX500 10m 的时段结构一致（约 137 根/日）。
  对照    ^GSPC 10m（RTH-only，60d 5m 聚合）。
  Q1      ^GSPC 为准（任务指定），ES=F 并列。3m 由 1m 分块下载聚合。

位相关声明：^GSPC / CAPITALCOM:SPX500 的 ATR 比值 mean 1.117 sd 0.083，不是
常数（见 levels.py）。所以本脚本**不**依赖具名位的精确位置：T1/T2 的距离一律
按当日 ATR 归一化后报告，并附一个「不吸附阶梯、固定 0.236 ATR 步长」的稳健性
变体，用来隔离阶梯吸附本身是否影响结论。

用法: python research/satylab/study_exit_threshold.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, indicators, levels, stats  # noqa: E402

ET = data.ET
CACHE = Path(__file__).resolve().parent / "cache"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

STACK_BARS = 5
MIN_RISK_PTS = 2.0
RUNGS = (-1.618, -1.272, -1.0, -0.786, -0.618, -0.5, -0.382, -0.236, 0.0,
         0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)


# ══ bar plumbing ═══════════════════════════════════════════════════════════

def resample(bars: list[data.Bar], seconds: int,
             with_subs: bool = False):
    """Aggregate to a coarser interval by epoch bucket (TradingView-style).

    with_subs also returns, per coarse bar, its constituent fine bars — used to
    resolve intrabar path order (discipline rule 5: path questions get 5-minute
    data, never a single coarse bar's high/low).
    """
    out: list[data.Bar] = []
    subs: list[list[data.Bar]] = []
    cur_key = None
    o = h = l = c = v = 0.0
    dt0 = None
    cur: list[data.Bar] = []
    for b in bars:
        k = int(b.dt.timestamp()) // seconds
        if k != cur_key:
            if cur_key is not None:
                out.append(data.Bar(dt0, dt0.date(), o, h, l, c, v))
                subs.append(cur)
            cur_key, dt0 = k, b.dt
            o, h, l, c, v = b.open, b.high, b.low, b.close, b.volume
            cur = [b]
        else:
            h = max(h, b.high)
            l = min(l, b.low)
            c = b.close
            v += b.volume
            cur.append(b)
    if cur_key is not None:
        out.append(data.Bar(dt0, dt0.date(), o, h, l, c, v))
        subs.append(cur)
    return (out, subs) if with_subs else out


def load_1m(symbol: str, weeks: int = 4) -> list[data.Bar]:
    """1m history in 7-day chunks (Yahoo caps 1m at ~30 days), cached."""
    path = CACHE / f"{symbol.replace('^','IDX_').replace('=','_')}__1m_chunks.json"
    if path.exists():
        rows = json.loads(path.read_text())
    else:
        now = int(time.time())
        merged: dict[int, list] = {}
        for k in range(1, weeks + 1):
            p2 = now - (k - 1) * 7 * 86400
            p1 = p2 - 7 * 86400
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(symbol)}?period1={p1}&period2={p2}"
                   f"&interval=1m&includePrePost=false")
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as r:
                    pl = json.load(r)
                res = pl["chart"]["result"][0]
                q = res["indicators"]["quote"][0]
                for i, ts in enumerate(res["timestamp"]):
                    o, hi, lo, c = (q["open"][i], q["high"][i],
                                    q["low"][i], q["close"][i])
                    if None in (o, hi, lo, c):
                        continue
                    merged[int(ts)] = [o, hi, lo, c]
            except Exception as exc:                       # noqa: BLE001
                print(f"    [1m {symbol} chunk {k} failed: {exc}]")
            time.sleep(0.8)
        rows = sorted([ts, *vals] for ts, vals in merged.items())
        path.write_text(json.dumps(rows))
    out = []
    for ts, o, hi, lo, c in rows:
        dt = datetime.fromtimestamp(ts, ET)
        out.append(data.Bar(dt, dt.date(), float(o), float(hi), float(lo),
                            float(c), 0.0))
    return out


def emas(bars: list[data.Bar]) -> dict[int, list[float | None]]:
    closes = [b.close for b in bars]
    return {n: indicators.ema(closes, n) for n in (8, 13, 21, 34, 48)}


def rolling_extreme(bars, n, hi=True):
    out, buf = [], []
    for b in bars:
        buf.append(b.high if hi else b.low)
        if len(buf) > n:
            buf.pop(0)
        out.append(max(buf) if hi else min(buf))
    return out


# ══ ATR ladder ═════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class Ladder:
    anchor: float
    atr: float


def build_ladder(daily: list[data.Bar], roll_hour: int | None):
    """bar -> (anchor, atr) from the PRIOR completed daily bar.

    roll_hour: for the 23h future the exchange session rolls at 18:00 ET, so a
    bar stamped 19:00 Monday belongs to Tuesday's daily bar (what Pine's
    request.security(..,"D",..) with session=extended returns).  None = index.
    """
    lv = levels.build(daily)
    days = sorted(lv)

    def for_bar(b: data.Bar) -> Ladder | None:
        d = b.day
        if roll_hour is not None and b.dt.hour >= roll_hour:
            d = d + timedelta(days=1)
        i = bisect_left(days, d)
        if i >= len(days):
            return None
        L = lv[days[i]]
        return Ladder(L.anchor, L.atr)

    return for_bar


def next_rung(px: float, direction: int, lad: Ladder, snap: bool = True) -> float:
    if not snap or lad.atr <= 0:
        return px + direction * 0.236 * lad.atr
    best = None
    for r in RUNGS:
        v = lad.anchor + r * lad.atr
        if direction > 0 and v > px + 1e-9 and (best is None or v < best):
            best = v
        if direction < 0 and v < px - 1e-9 and (best is None or v > best):
            best = v
    return best if best is not None else px + direction * 0.236 * lad.atr


# ══ exit rules ═════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class ExitRule:
    key: str
    label: str
    ema: int | None = 13
    hyst: int = 1
    after_t2_only: bool = False
    atr_mult: float | None = None


VARIANTS = [
    ExitRule("E0", "收盘穿 13（现状·同线进出）", ema=13),
    ExitRule("E1", "收盘穿 21", ema=21),
    ExitRule("E2", "收盘穿 34", ema=34),
    ExitRule("E3", "收盘穿 48", ema=48),
    ExitRule("E4", "保护位；到 T2 后才用 13 跟踪", ema=13, after_t2_only=True),
    ExitRule("E5a", "ATR 追踪止损 1.0×ATR(14,10m)", atr_mult=1.0),
    ExitRule("E5b", "ATR 追踪止损 1.5×ATR(14,10m)", atr_mult=1.5),
]
HYST = [
    ExitRule("H2", "收盘穿 13，需连续 2 根", ema=13, hyst=2),
    ExitRule("H3", "收盘穿 13，需连续 3 根", ema=13, hyst=3),
]


# ══ v14 replica engine ═════════════════════════════════════════════════════

@dataclass
class Trade:
    dir: int
    setup: str
    session: str
    i_in: int
    i_out: int = -1
    entry: float = 0.0
    prot: float = 0.0
    risk: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    t1done: bool = False
    t2done: bool = False
    r: float = 0.0
    reason: str = ""
    t1_atr: float = 0.0          # |T1-entry| in daily-ATR units


@dataclass
class Ctx:
    """Everything the engine needs, precomputed once per bar series."""
    bars: list
    e: dict
    hh10: list
    ll10: list
    atr10: list
    lad: list          # Ladder | None per bar
    rth: list
    subs: list | None = None      # 5m constituents per 10m bar
    amb: int = 0                  # counter: stop and target hit in one sub-bar


def make_ctx(bars, ladder_fn, subs=None) -> Ctx:
    e = emas(bars)
    return Ctx(bars=bars, e=e,
               hh10=rolling_extreme(bars, 10, True),
               ll10=rolling_extreme(bars, 10, False),
               atr10=indicators.atr_series(bars, 14),
               lad=[ladder_fn(b) for b in bars],
               rth=[(b.dt.hour * 60 + b.dt.minute) >= 570 and
                    (b.dt.hour * 60 + b.dt.minute) < 960 for b in bars],
               subs=subs)


def run_engine(ctx: Ctx, rule: ExitRule, snap: bool = True,
               path: str = "bar", amb: str = "stop",
               en_recovery: bool = True, en_vomy: bool = True) -> list[Trade]:
    """path='bar' reproduces Pine (protective wins the whole 10m bar);
    path='sub' walks the 5m constituents in order.  amb resolves a sub-bar in
    which BOTH the stop and a target trade: 'stop' or 'target'."""
    bars, e = ctx.bars, ctx.e
    e8, e13, e21, e34, e48 = e[8], e[13], e[21], e[34], e[48]
    line_src = {13: e13, 21: e21, 34: e34, 48: e48}

    trades: list[Trade] = []
    sBull = sBear = 0
    recL = recS = 0
    recLExt = recSExt = 0.0
    vomS = vomL = 0
    vomSFin = vomLFin = 0.0
    pos: Trade | None = None
    frac = 1.0
    legs = 0.0
    wrong_run = 0
    peak = trough = 0.0

    for i, b in enumerate(bars):
        if e48[i] is None or ctx.lad[i] is None or ctx.lad[i].atr <= 0:
            continue
        pb_bull, pb_bear = sBull, sBear
        stack_bull = e8[i] > e13[i] > e21[i] > e34[i] > e48[i]
        stack_bear = e8[i] < e13[i] < e21[i] < e34[i] < e48[i]
        sBull = sBull + 1 if stack_bull else 0
        sBear = sBear + 1 if stack_bear else 0
        c, hi, lo = b.close, b.high, b.low

        # ---- manage open position (Pine does this before the state machines)
        if pos is not None:
            d = pos.dir
            seq = (ctx.subs[i] if (path == "sub" and ctx.subs) else [b])
            for sb in seq:
                if pos is None:
                    break
                sh_, sl_ = sb.high, sb.low
                p_hit = sl_ <= pos.prot if d > 0 else sh_ >= pos.prot
                t1_hit = (not pos.t1done and
                          (sh_ >= pos.t1 if d > 0 else sl_ <= pos.t1))
                t2_hit = (pos.t1done and not pos.t2done and
                          (sh_ >= pos.t2 if d > 0 else sl_ <= pos.t2))
                if p_hit and (t1_hit or t2_hit):
                    ctx.amb += 1
                    if amb == "target":
                        if t1_hit:
                            legs += 0.50 * (pos.t1 - pos.entry) * d / pos.risk
                            frac -= 0.50
                            pos.t1done = True
                        if t2_hit:
                            legs += 0.25 * (pos.t2 - pos.entry) * d / pos.risk
                            frac -= 0.25
                            pos.t2done = True
                if p_hit:
                    legs += frac * (pos.prot - pos.entry) * d / pos.risk
                    pos.r, pos.reason, pos.i_out = legs, "protective", i
                    trades.append(pos)
                    pos = None
                    break
                if t1_hit:
                    legs += 0.50 * (pos.t1 - pos.entry) * d / pos.risk
                    frac -= 0.50
                    pos.t1done = True
                if t2_hit:
                    legs += 0.25 * (pos.t2 - pos.entry) * d / pos.risk
                    frac -= 0.25
                    pos.t2done = True
            if pos is not None:
                # structural exit, per variant
                if rule.atr_mult is not None:
                    a = ctx.atr10[i] or 0.0
                    if d > 0:
                        peak = max(peak, hi)
                        struct = c < peak - rule.atr_mult * a
                    else:
                        trough = min(trough, lo)
                        struct = c > trough + rule.atr_mult * a
                else:
                    ln = line_src[rule.ema][i]
                    wrong = (c < ln) if d > 0 else (c > ln)
                    if rule.after_t2_only and not pos.t2done:
                        wrong = False
                    wrong_run = wrong_run + 1 if wrong else 0
                    struct = wrong_run >= rule.hyst
                if pos is not None and struct:
                    legs += frac * (c - pos.entry) * d / pos.risk
                    pos.r, pos.reason, pos.i_out = legs, "struct", i
                    trades.append(pos)
                    pos = None

        def open_pos(d, setup, entry, prot, t1, t2):
            nonlocal pos, frac, legs, wrong_run, peak, trough
            risk = abs(entry - prot)
            pos = Trade(dir=d, setup=setup,
                        session="RTH" if ctx.rth[i] else "ON",
                        i_in=i, entry=entry, prot=prot, risk=risk,
                        t1=t1, t2=t2,
                        t1_atr=abs(t1 - entry) / ctx.lad[i].atr)
            frac, legs, wrong_run = 1.0, 0.0, 0
            peak, trough = hi, lo

        # ---- Recovery long ----
        if en_recovery:
            if recL == 0 and sBull >= STACK_BARS and c < e13[i]:
                recL, recLExt = 1, lo
            elif recL == 1:
                recLExt = min(recLExt, lo)
                if c < e34[i] or stack_bear:
                    recL = 0
                elif c > e13[i]:
                    if pos is None and c - recLExt >= MIN_RISK_PTS:
                        t1 = next_rung(c, 1, ctx.lad[i], snap)
                        open_pos(1, "Recovery", c, recLExt, t1,
                                 next_rung(t1, 1, ctx.lad[i], snap))
                    recL = 0
            # ---- Recovery short ----
            if recS == 0 and sBear >= STACK_BARS and c > e13[i]:
                recS, recSExt = 1, hi
            elif recS == 1:
                recSExt = max(recSExt, hi)
                if c > e34[i] or stack_bull:
                    recS = 0
                elif c < e13[i]:
                    if pos is None and recSExt - c >= MIN_RISK_PTS:
                        t1 = next_rung(c, -1, ctx.lad[i], snap)
                        open_pos(-1, "Recovery", c, recSExt, t1,
                                 next_rung(t1, -1, ctx.lad[i], snap))
                    recS = 0

        # ---- Vomy short / inverse Vomy long ----
        if en_vomy:
            if vomS == 0 and pb_bull >= STACK_BARS and c < e13[i] and c < e8[i]:
                vomS, vomSFin = 2, ctx.hh10[i]
            elif vomS == 2:
                vomSFin = max(vomSFin, hi)
                if c > e13[i]:
                    vomS = 0
                elif hi >= e13[i]:
                    if pos is None and vomSFin - c >= MIN_RISK_PTS:
                        t1 = next_rung(c, -1, ctx.lad[i], snap)
                        open_pos(-1, "Vomy", c, vomSFin, t1,
                                 next_rung(t1, -1, ctx.lad[i], snap))
                        vomS = 0
            if vomL == 0 and pb_bear >= STACK_BARS and c > e13[i] and c > e8[i]:
                vomL, vomLFin = 2, ctx.ll10[i]
            elif vomL == 2:
                vomLFin = min(vomLFin, lo)
                if c < e13[i]:
                    vomL = 0
                elif lo <= e13[i]:
                    if pos is None and c - vomLFin >= MIN_RISK_PTS:
                        t1 = next_rung(c, 1, ctx.lad[i], snap)
                        open_pos(1, "Vomy", c, vomLFin, t1,
                                 next_rung(t1, 1, ctx.lad[i], snap))
                        vomL = 0
    return trades


# ══ statistics ═════════════════════════════════════════════════════════════

def bracket_race(ctx: Ctx, trades: list[Trade]) -> tuple[int, int, float, float]:
    """Pure bracket: does T1 get touched before the protective?  Geometric null."""
    k = n = 0
    sp = spq = 0.0
    for t in trades:
        p = t.risk / (t.risk + abs(t.t1 - t.entry))
        hit = None
        for j in range(t.i_in + 1, len(ctx.bars)):
            b = ctx.bars[j]
            if t.dir > 0:
                if b.low <= t.prot:
                    hit = False
                    break
                if b.high >= t.t1:
                    hit = True
                    break
            else:
                if b.high >= t.prot:
                    hit = False
                    break
                if b.low <= t.t1:
                    hit = True
                    break
        if hit is None:
            continue
        n += 1
        k += int(hit)
        sp += p
        spq += p * (1 - p)
    z = (k - sp) / math.sqrt(spq) if spq > 0 else 0.0
    return k, n, sp, z


SPREAD_PTS = 0.6      # CAPITALCOM:SPX500 typical spread, per the Pine tooltip


def summarize(trades: list[Trade], nbars: int, spread: float = SPREAD_PTS) -> dict:
    rs = [t.r for t in trades]
    e = stats.expectancy(rs)
    holds = sorted(t.i_out - t.i_in for t in trades)
    n = len(trades)
    med = holds[n // 2] if n else 0
    sd = (math.sqrt(sum((r - e["avg_r"]) ** 2 for r in rs) / (n - 1))
          if n > 1 else 0.0)
    zr = e["avg_r"] / (sd / math.sqrt(n)) if n > 1 and sd > 0 else 0.0
    wins = sum(1 for r in rs if r > 1e-12)
    reasons: dict[str, list[float]] = {}
    for t in trades:
        reasons.setdefault(t.reason, []).append(t.r)
    risks = sorted(t.risk for t in trades)
    # one round trip costs one spread on the full position; the T1/T2 scale-outs
    # sum to the same size, so scaling does not add crossings in this model.
    cost = sum(spread / t.risk for t in trades if t.risk > 0)
    return {"n": n, "per1k": 1000.0 * n / nbars if nbars else 0.0,
            "med_risk": risks[n // 2] if n else 0.0,
            "cost_r": cost, "net_r": e.get("total_r", 0.0) - cost,
            "total_r": e.get("total_r", 0.0), "avg_r": e.get("avg_r", 0.0),
            "sd_r": sd, "z_r": zr, "win": wins,
            "win_rate": wins / n if n else 0.0,
            "win_ci": stats.wilson(wins, n),
            "med_hold": med,
            "mean_hold": sum(holds) / n if n else 0.0,
            "hold_le2": sum(1 for h in holds if h <= 2),
            "max_dd": e.get("max_dd", 0.0),
            "t1_rate": sum(1 for t in trades if t.t1done) / n if n else 0.0,
            "reasons": {k: (len(v), sum(v)) for k, v in reasons.items()},
            "t1_atr": (sorted(t.t1_atr for t in trades)[n // 2] if n else 0.0)}


def fmt_row(key: str, s: dict, label: str = "") -> str:
    lo, hi = s["win_ci"]
    return (f"  {key:<5}{label:<34} n={s['n']:<5} /1000K={s['per1k']:5.2f} "
            f"中位持仓={s['med_hold']:>3}根 总R={s['total_r']:+8.1f} "
            f"均R={s['avg_r']:+.3f} 胜率={100*s['win_rate']:4.1f}%"
            f"[{100*lo:.0f},{100*hi:.0f}] z_R={s['z_r']:+5.2f} "
            f"回撤={s['max_dd']:.0f}R")


# ══ Q1 · crossing frequency ════════════════════════════════════════════════

def crossing_stats(bars: list[data.Bar], mode: str, line: int = 13) -> dict:
    """Intervals (in bars) between closes crossing the `line` EMA.

    mode: 'stack5' = sBull>=5 (the actual v14 gate, both sides),
          'stack'  = stacked this bar, 'all' = unconditional.
    """
    e = emas(bars)
    e8, e13, e21, e34, e48 = e[8], e[13], e[21], e[34], e[48]
    el = e[line]
    sB = sS = 0
    qual: list[bool] = []
    side: list[int] = []
    for i, b in enumerate(bars):
        if e48[i] is None:
            qual.append(False)
            side.append(0)
            continue
        sb = e8[i] > e13[i] > e21[i] > e34[i] > e48[i]
        ss = e8[i] < e13[i] < e21[i] < e34[i] < e48[i]
        sB = sB + 1 if sb else 0
        sS = sS + 1 if ss else 0
        q = (sB >= STACK_BARS or sS >= STACK_BARS) if mode == "stack5" else \
            (sb or ss) if mode == "stack" else True
        qual.append(q)
        side.append(1 if b.close > el[i] else -1)

    ivals: list[int] = []
    nq = ncross = 0
    run_start = None
    prev_cross = None
    for i in range(len(bars)):
        if not qual[i]:
            run_start = None
            prev_cross = None
            continue
        nq += 1
        if run_start is None:
            run_start = i
            prev_cross = i
            continue
        if side[i] != side[i - 1]:
            ncross += 1
            ivals.append(i - prev_cross)
            prev_cross = i
    ivals.sort()
    return {"bars": nq, "cross": ncross,
            "mean_int": nq / ncross if ncross else float("inf"),
            "med_int": ivals[len(ivals) // 2] if ivals else 0,
            "p90_int": ivals[int(0.9 * len(ivals))] if ivals else 0,
            "per100": 100.0 * ncross / nq if nq else 0.0,
            "ci": stats.wilson(ncross, nq)}


# ══ bootstrap null ═════════════════════════════════════════════════════════

def synth(bars, daily_atr_of_bar, rng, block=24):
    """Circular block bootstrap of de-meaned log returns; bar shapes reused."""
    n = len(bars)
    lr = [0.0] * n
    for i in range(1, n):
        lr[i] = math.log(bars[i].close / bars[i - 1].close)
    mu = sum(lr[1:]) / (n - 1)
    idx: list[int] = []
    while len(idx) < n:
        s = rng.randrange(1, n)
        for k in range(block):
            idx.append(1 + (s - 1 + k) % (n - 1))
    idx = idx[:n]
    out = []
    c = bars[0].close
    for i, b in enumerate(bars):
        j = idx[i]
        c = c * math.exp(lr[j] - mu)
        sj = bars[j]
        out.append(data.Bar(b.dt, b.day, c * sj.open / sj.close,
                            c * sj.high / sj.close, c * sj.low / sj.close,
                            c, 0.0))
    return out


def synth_ladder(sbars, real_lad, roll_hour):
    """Anchor = synthetic prior-session close; ATR magnitude kept from the real
    tape (the bootstrap preserves volatility, so only level POSITION is nulled)."""
    key = []
    for b in sbars:
        d = b.day + timedelta(days=1) if (roll_hour is not None and
                                          b.dt.hour >= roll_hour) else b.day
        key.append(d)
    last_close: dict[date, float] = {}
    for b, k in zip(sbars, key):
        last_close[k] = b.close
    days = sorted(last_close)
    prev = {days[i]: last_close[days[i - 1]] for i in range(1, len(days))}
    out = []
    for b, k, rl in zip(sbars, key, real_lad):
        a = prev.get(k)
        out.append(Ladder(a, rl.atr) if (a and rl and rl.atr > 0) else None)
    return out


# ══ main ═══════════════════════════════════════════════════════════════════

def q1() -> None:
    print("\n" + "=" * 78)
    print("Q1 · 穿越频率基准：多头/空头排列时，收盘穿 13 EMA 的平均间隔")
    print("=" * 78)
    sets = []
    try:
        g1 = load_1m("^GSPC")
        if len(g1) > 2000:
            sets.append(("^GSPC 3m", resample(g1, 180)))
    except Exception as exc:                                # noqa: BLE001
        print(f"  [^GSPC 1m 不可用: {exc}]")
    sets.append(("^GSPC 10m", resample(data.load("^GSPC", "60d", "5m"), 600)))
    sets.append(("^GSPC 1h", data.load("^GSPC", "730d", "1h")))
    try:
        e1 = load_1m("ES=F")
        if len(e1) > 2000:
            sets.append(("ES=F 3m", resample(e1, 180)))
    except Exception as exc:                                # noqa: BLE001
        print(f"  [ES=F 1m 不可用: {exc}]")
    sets.append(("ES=F 10m", resample(data.load("ES=F", "60d", "5m"), 600)))
    sets.append(("ES=F 1h", data.load("ES=F", "730d", "1h")))

    print(f"\n  {'样本':<12}{'口径':<10}{'合格K':>7}{'穿越':>7}"
          f"{'平均间隔':>9}{'中位':>6}{'p90':>6}{'穿越/100K':>11}  95%CI")
    res = {}
    for name, bars in sets:
        for mode, ml in (("stack5", "排列≥5根"), ("stack", "排列中"),
                         ("all", "全部K")):
            s = crossing_stats(bars, mode)
            res[(name, mode)] = s
            lo, hi = s["ci"]
            print(f"  {name:<12}{ml:<10}{s['bars']:>7}{s['cross']:>7}"
                  f"{s['mean_int']:>9.2f}{s['med_int']:>6}{s['p90_int']:>6}"
                  f"{s['per100']:>11.2f}  [{100*lo:.2f},{100*hi:.2f}]")
    print("\n  【交易频率上界】同线进出需要 1 次上穿(入)+1 次下穿(出)，")
    print("  故 trades/1000K 上界 = 穿越/1000K ÷ 2：")
    for name, _ in sets:
        s = res[(name, "stack5")]
        print(f"    {name:<12}排列≥5根时 {10*s['per100']:6.1f} 穿越/1000K "
              f"→ 上界 {5*s['per100']:5.1f} 笔/1000K")

    print("\n  【为什么换出场线省不了多少笔】入场仍然要求穿 13。")
    print("  各条线在『排列≥5根』下的穿越率（穿越/1000K，平均间隔根）：")
    print(f"    {'样本':<12}{'13':>16}{'21':>16}{'34':>16}{'48':>16}")
    for name, bars in sets:
        if not name.endswith("10m"):
            continue
        cells = []
        for ln in (13, 21, 34, 48):
            s = crossing_stats(bars, "stack5", ln)
            cells.append(f"{10*s['per100']:7.1f}/{s['mean_int']:5.2f}根")
        print(f"    {name:<12}" + "".join(f"{c:>16}" for c in cells))
    print("  同线进出的频率由 min(入场线穿越, 出场线穿越) 决定 —— 入场线不动，")
    print("  上界最多只能降到入场穿越率的一半，这是 E1~E3 省不动笔数的机械原因。")
    return res


def run_instrument(name, bars5, daily, roll_hour, label, reps=0, seed=7):
    print("\n" + "=" * 78)
    print(f"Q2/Q3 · {label}")
    print("=" * 78)
    bars, subs = resample(bars5, 600, with_subs=True)
    lad_fn = build_ladder(daily, roll_hour)
    ctx = make_ctx(bars, lad_fn, subs)
    nb = sum(1 for x in ctx.lad if x is not None)
    d0, d1 = bars[0].day, bars[-1].day
    print(f"  10m K 线 {len(bars)} 根（可用 {nb}），{d0} → {d1}")

    allv = VARIANTS + HYST
    out = {}
    trades_by = {}
    for rule in allv:
        tr = run_engine(ctx, rule)
        trades_by[rule.key] = tr
        out[rule.key] = summarize(tr, nb)
    fidelity(trades_by, out)
    print("\n  ── 出场阈值对比（入场规则逐字不变，10m 分辨率＝Pine 口径）──")
    for rule in allv:
        print(fmt_row(rule.key, out[rule.key], rule.label))

    # ---- discipline rule 5: resolve the intrabar path on 5m data ----
    print("\n  ── 路径分辨率检验（5m 子K 定序；Pine 用 10m 一根 K，"
          "保护位无条件优先）──")
    print(f"    {'':5}{'10m保守':>10}{'5m保守':>10}{'5m乐观':>10}"
          f"{'伪影带宽':>10}   歧义K数(10m/5m)")
    path_out = {}
    for rule in allv:
        ctx.amb = 0
        run_engine(ctx, rule, path="bar")
        amb10 = ctx.amb
        ctx.amb = 0
        ts = run_engine(ctx, rule, path="sub", amb="stop")
        s_cons = summarize(ts, nb)
        na_ = f"{amb10}/{ctx.amb}"
        ctx.amb = 0
        to = run_engine(ctx, rule, path="sub", amb="target")
        s_opt = summarize(to, nb)
        path_out[rule.key] = (s_cons, s_opt)
        print(f"    {rule.key:<5}{out[rule.key]['total_r']:>10.1f}"
              f"{s_cons['total_r']:>10.1f}{s_opt['total_r']:>10.1f}"
              f"{s_opt['total_r']-s_cons['total_r']:>10.1f}{na_:>18}")

    # ---- friction ----
    print(f"\n  ── 交易成本（点差 {SPREAD_PTS} 点/往返，"
          f"成本R = 点差/风险距离）──")
    print(f"    {'':5}{'笔数':>6}{'中位风险(点)':>13}{'成本R':>9}"
          f"{'毛R':>9}{'净R':>9}")
    for rule in allv:
        s = out[rule.key]
        print(f"    {rule.key:<5}{s['n']:>6}{s['med_risk']:>13.1f}"
              f"{-s['cost_r']:>9.1f}{s['total_r']:>9.1f}{s['net_r']:>9.1f}")

    # entry quality: pure bracket vs geometric null (exit-rule independent)
    k, n, sp, z = bracket_race(ctx, trades_by["E0"])
    print(f"\n  ── 入场质量（纯括号单，与出场规则无关）──")
    print(f"    保护位 vs T1 先到：{k}/{n} = {100*k/n:.1f}% "
          f"[{100*stats.wilson(k,n)[0]:.1f},{100*stats.wilson(k,n)[1]:.1f}]，"
          f"几何零假设 ΣS/(S+T) = {100*sp/n:.1f}% → z_geom = {z:+.2f}")
    med_t1 = out["E0"]["t1_atr"]
    print(f"    T1 距离中位数 = {med_t1:.3f} 日ATR（按 ATR 归一化，"
          f"不依赖具名位的绝对价格）")

    # exit-reason decomposition
    print("\n  ── 出场原因分解（笔数 / 总R）──")
    for rule in allv:
        rs = out[rule.key]["reasons"]
        parts = "  ".join(f"{k}: {v[0]}笔 {v[1]:+.1f}R"
                          for k, v in sorted(rs.items()))
        print(f"    {rule.key:<5}{parts}")

    # period stability (halves)
    print("\n  ── 分期稳定性（样本前/后半）──")
    mid = len(bars) // 2
    for rule in allv:
        a = [t for t in trades_by[rule.key] if t.i_in < mid]
        b = [t for t in trades_by[rule.key] if t.i_in >= mid]
        sa, sb = summarize(a, mid), summarize(b, len(bars) - mid)
        print(f"    {rule.key:<5}前半 n={sa['n']:<4} {sa['total_r']:+7.1f}R "
              f"胜率{100*sa['win_rate']:4.1f}%  ｜ "
              f"后半 n={sb['n']:<4} {sb['total_r']:+7.1f}R "
              f"胜率{100*sb['win_rate']:4.1f}%")

    # robustness: no ladder snapping
    print("\n  ── 稳健性：目标不吸附具名阶梯，改用固定 0.236 ATR 步长 ──")
    for rule in allv:
        s = summarize(run_engine(ctx, rule, snap=False), nb)
        print(fmt_row(rule.key, s, rule.label))

    # setup split for the baseline
    print("\n  ── E0 分 setup / 分时段 ──")
    for tag, sel in (("Recovery", lambda t: t.setup == "Recovery"),
                     ("Vomy", lambda t: t.setup == "Vomy"),
                     ("RTH", lambda t: t.session == "RTH"),
                     ("夜盘", lambda t: t.session == "ON")):
        s = summarize([t for t in trades_by["E0"] if sel(t)], nb)
        print(fmt_row("", s, tag))

    # churn attribution
    paired(trades_by, allv)
    post_exit(ctx, trades_by)
    churn(trades_by, out, nb)

    if reps:
        bootstrap_null(ctx, allv, out, nb, roll_hour, reps, seed)
    return out, trades_by, ctx, nb


def paired(trades_by, allv) -> None:
    """Same entry bar in both variants → paired t on the R difference.

    Far more powerful than comparing two independent totals: entries are
    literally identical, so all the entry noise cancels.
    """
    base = {t.i_in: t for t in trades_by["E0"]}
    print("\n  ── 配对检验（同一入场 K 的两个出场规则，噪声抵消）──")
    print(f"    {'':5}{'配对数':>7}{'ΔR均值':>9}{'ΔR合计':>9}{'配对t':>8}"
          f"{'Δ持仓中位':>10}")
    shared = {}
    for rule in allv:
        if rule.key == "E0":
            continue
        d, dh, keys = [], [], set()
        for t in trades_by[rule.key]:
            b = base.get(t.i_in)
            if b is None or b.dir != t.dir:
                continue
            d.append(t.r - b.r)
            dh.append((t.i_out - t.i_in) - (b.i_out - b.i_in))
            keys.add(t.i_in)
        n = len(d)
        if n < 2:
            continue
        m = sum(d) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
        tstat = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
        dh.sort()
        shared[rule.key] = (keys, sum(d))
        print(f"    {rule.key:<5}{n:>7}{m:>9.3f}{sum(d):>9.1f}{tstat:>8.2f}"
              f"{dh[n//2]:>10}")

    print("\n  ── ΔR 的完整分解：改善究竟来自哪里 ──")
    print(f"    {'':5}{'避开的笔数':>11}{'避开笔的R':>11}"
          f"{'共同笔ΔR':>11}{'新增笔R':>10}{'合计ΔR':>9}")
    for rule in allv:
        if rule.key not in shared:
            continue
        keys, dsum = shared[rule.key]
        avoided = [t for t in trades_by["E0"] if t.i_in not in keys]
        newonly = [t for t in trades_by[rule.key] if t.i_in not in keys]
        av_r = sum(t.r for t in avoided)
        nw_r = sum(t.r for t in newonly)
        print(f"    {rule.key:<5}{len(avoided):>11}{-av_r:>11.1f}"
              f"{dsum:>11.1f}{nw_r:>10.1f}{-av_r + dsum + nw_r:>9.1f}")
    print("    读法：『避开笔的R』取负号 = 不做这些交易省下的钱；"
          "『共同笔ΔR』= 同一笔交易改了出场规则后的真实增量。")


def post_exit(ctx, trades_by, horizon: int = 10) -> None:
    """After a 13-line structural exit, does price keep going the trade's way?

    If the exit were informative, the forward move should be against the trade.
    Measured in R (units of the trade's own risk) so it is comparable.
    """
    bars = ctx.bars
    fwd: dict[int, list[float]] = {k: [] for k in (1, 3, horizon)}
    back = 0
    n = 0
    for t in trades_by["E0"]:
        if t.reason != "struct":
            continue
        j = t.i_out
        px = bars[j].close
        n += 1
        for k in fwd:
            if j + k < len(bars):
                fwd[k].append((bars[j + k].close - px) * t.dir / t.risk)
        ln = ctx.e[13][j]
        for k in range(1, 4):
            if j + k < len(bars) and ln is not None:
                c2, l2 = bars[j + k].close, ctx.e[13][j + k]
                if l2 is not None and ((c2 > l2) if t.dir > 0 else (c2 < l2)):
                    back += 1
                    break
    print(f"\n  ── 结构离场之后（E0，{n} 次收盘穿 13 离场）──")
    for k in sorted(fwd):
        v = sorted(fwd[k])
        if not v:
            continue
        m = sum(v) / len(v)
        print(f"    离场后 {k:>2} 根，按原方向的收盘位移：均值 {m:+.3f}R  "
              f"中位 {v[len(v)//2]:+.3f}R  正向占比 "
              f"{100*sum(1 for x in v if x > 0)/len(v):.1f}%")
    print(f"    离场后 3 根内价格又收回 13 线原侧（离场是噪声）："
          f"{back}/{n} = {100*back/max(n,1):.1f}% "
          f"[{100*stats.wilson(back,n)[0]:.1f},"
          f"{100*stats.wilson(back,n)[1]:.1f}]")


def churn(trades_by, out, nb) -> None:
    print("\n  ── Q4 · 同线进出的 churn 归因 ──")
    tr = trades_by["E0"]
    same, same_r, flip, flip_r = 0, 0.0, 0, 0.0
    for a, b in zip(tr, tr[1:]):
        if a.reason != "struct":
            continue
        gap = b.i_in - a.i_out
        if gap <= 3 and b.dir == a.dir:
            same += 1
            same_r += a.r + b.r
        elif gap <= 1 and b.dir == -a.dir:
            flip += 1
            flip_r += a.r + b.r
    n = out["E0"]["n"]
    print(f"    E0 总 {n} 笔。结构离场后 ≤3 根内**同向**再入场（撕票回环）："
          f"{same} 对 = {100*same/max(n,1):.0f}% 的笔数，两腿合计 {same_r:+.1f}R")
    print(f"    结构离场后 ≤1 根内**反向**开仓（同一根 13 线掉头）："
          f"{flip} 对，两腿合计 {flip_r:+.1f}R")
    le2 = out["E0"]["hold_le2"]
    print(f"    持仓 ≤2 根的交易：{le2} 笔 = {100*le2/max(n,1):.0f}%")
    base = out["E0"]
    print(f"\n    与现状相比（Δ笔数 = 同线进出多制造的交易，ΔR = 代价）：")
    print(f"      {'':5}{'Δ笔数':>8}{'Δ%':>9}{'Δ毛R':>9}{'Δ点差R':>9}"
          f"{'Δ净R':>9}{'Δ中位持仓':>10}")
    for k, s in out.items():
        if k == "E0":
            continue
        print(f"      {k:<5}{s['n']-base['n']:>8d}"
              f"{100*(s['n']-base['n'])/base['n']:>8.1f}%"
              f"{s['total_r']-base['total_r']:>9.1f}"
              f"{base['cost_r']-s['cost_r']:>9.1f}"
              f"{s['net_r']-base['net_r']:>9.1f}"
              f"{s['med_hold']-base['med_hold']:>9d}根")


def bootstrap_null(ctx, allv, out, nb, roll_hour, reps, seed) -> None:
    print(f"\n  ── 经验零假设：{reps} 次分块自助随机游走（去漂移）──")
    rng = random.Random(seed)
    acc = {r.key: [] for r in allv}
    accn = {r.key: [] for r in allv}
    for _ in range(reps):
        sb = synth(ctx.bars, None, rng)
        sl = synth_ladder(sb, ctx.lad, roll_hour)
        sc = make_ctx(sb, lambda b: None)
        sc.lad = sl
        for rule in allv:
            t = run_engine(sc, rule)
            acc[rule.key].append(sum(x.r for x in t))
            accn[rule.key].append(len(t))
    print(f"    {'':5}{'实际总R':>9}{'零假设总R均值':>15}{'sd':>8}"
          f"{'z':>7}{'实际笔数':>9}{'零假设笔数':>11}")
    for rule in allv:
        v = sorted(acc[rule.key])
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
        z = (out[rule.key]["total_r"] - m) / sd if sd > 0 else 0.0
        mn = sum(accn[rule.key]) / len(accn[rule.key])
        print(f"    {rule.key:<5}{out[rule.key]['total_r']:>9.1f}{m:>15.1f}"
              f"{sd:>8.1f}{z:>7.2f}{out[rule.key]['n']:>9}{mn:>11.0f}")


LIVE = {"all": (695, 0.32, -44.1), "RTH": (186, 0.38, -15.9),
        "ON": (509, 0.30, -28.2), "Recovery": (353, 0.30, -40.6),
        "Vomy": (342, 0.35, -3.5)}


def fidelity(trades_by, out) -> None:
    """Does the replica reproduce the live CAPITALCOM:SPX500 10m ledger?"""
    print("\n  ── 复现保真度 vs 线上账本（CAPITALCOM:SPX500 10m）──")
    tr = trades_by["E0"]
    sel = {"all": tr,
           "RTH": [t for t in tr if t.session == "RTH"],
           "ON": [t for t in tr if t.session == "ON"],
           "Recovery": [t for t in tr if t.setup == "Recovery"],
           "Vomy": [t for t in tr if t.setup == "Vomy"]}
    print(f"    {'':10}{'线上笔数':>9}{'复现笔数':>9}{'线上胜率':>9}"
          f"{'复现胜率':>9}{'线上R/笔':>10}{'复现R/笔':>10}")
    for k, (ln, lw, lr) in LIVE.items():
        v = sel[k]
        n = len(v)
        w = sum(1 for t in v if t.r > 0) / n if n else 0
        rp = sum(t.r for t in v) / n if n else 0
        print(f"    {k:<10}{ln:>9}{n:>9}{100*lw:>8.0f}%{100*w:>8.1f}%"
              f"{lr/ln:>10.3f}{rp:>10.3f}")
    n0 = out["E0"]["n"]
    print(f"    线上 695 笔 ÷ 本样本 {out['E0']['per1k']:.1f}笔/1000K "
          f"→ 隐含线上历史约 {1000*695/out['E0']['per1k']:.0f} 根 10m K "
          f"≈ {1000*695/out['E0']['per1k']/137:.0f} 个交易日（TradingView "
          f"10m 图常见的历史深度）。用户估的『每 7 根一笔』是把历史当成 "
          f"4865 根算出来的，本样本给的是每 {1000/out['E0']['per1k']:.1f} 根一笔。")


def main() -> None:
    q1()
    es5 = data.load("ES=F", "60d", "5m")
    esd = data.load("ES=F", "20y", "1d")
    run_instrument("ES", es5, esd, 18,
                   "ES=F 10m（主样本：带夜盘，时段结构≈线上 SPX500 账本）",
                   reps=60)
    gs5 = data.load("^GSPC", "60d", "5m")
    gsd = data.load("^GSPC", "20y", "1d")
    run_instrument("GSPC", gs5, gsd, None,
                   "^GSPC 10m（对照：RTH-only）", reps=0)


if __name__ == "__main__":
    main()
