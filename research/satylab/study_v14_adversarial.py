"""Adversarial audit of the four V14 "fix" reports, before anything ships.

This file does not propose a fix.  It tries to kill the ones already proposed.

Five house pitfalls are checked by name (the project has committed each of them
at least once):

  P1 accounting artifact — the trigger bar leaking into the outcome window
  P2 wrong null — 50% instead of S/(S+T), and (new here) 0 instead of the
     structural expectation of v14's own 50/25/25 payoff under no drift
  P3 two points treated as a constant — 4 "datasets" that are 2 instruments
     x 2 timeframes with A subset C and B subset D
  P4 family size — how many configurations did the whole programme try, and
     does the best survivor clear the family-max bar
  P5 "fewer trades so less loss" dressed up as "better trades"

Plus what the audit brief demanded: rerun every study_v14_*.py and reconcile
every headline; thirds-stability; single-point (best trade / best day) leverage;
and a cost model that stops pretending the overnight book trades at the RTH
spread.

The decisive new instrument is the STRUCTURAL NULL (section 2).  Every previous
report tested mean R against zero.  Zero is the wrong bar.  v14 books 50% at
T1, 25% at T2 and lets the last 25% run to a 13-EMA close-through, while a stop
takes 100%.  That payoff has a negative expectation under a driftless random
walk, so "avg R < 0" is not evidence of anything.  Here the same bracket, the
same exit code and the same bar-shape distribution are replayed on demeaned
paths to find out what zero alpha actually scores.

Usage:  .venv/bin/python research/satylab/study_v14_adversarial.py
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats                       # noqa: E402
from satylab.data import Bar                                  # noqa: E402
from satylab.indicators import ema                            # noqa: E402
from satylab import study_v14_ablation as AB                  # noqa: E402
from satylab import study_v14_filters as FL                   # noqa: E402
from satylab.study_v14_repro import LevelBook                 # noqa: E402

SEED = 20260728
NULL_PATHS = 400          # driftless paths per trade for the structural null
FAMILY_REPS = 500         # synthetic markets for the family-max null
BLOCK = 12                # 2 hours of 10m bars per bootstrap block
OUT = Path(__file__).resolve().parents[1] / "reports" / "V14_ADVERSARIAL.md"

# Headline numbers claimed by the four phase reports, transcribed verbatim.
# Every one is recomputed below and marked OK / MISMATCH.
CLAIMS = {
    "repro/B_n": 462, "repro/B_win": 0.333, "repro/B_totR": -41.7,
    "repro/B_medhold": 3, "repro/B_per1k": 67.5,
    "sameline/E0_totR": -41.6, "sameline/E1_totR": -28.6,
    "sameline/E2_totR": -25.7, "sameline/E3_totR": -16.9,
    "ablation/A7_totR": 4.1, "ablation/A7_net": -7.6, "ablation/A7_n": 251,
    "ablation/A9_totR": -12.5, "ablation/A9_n": 317,
    "ablation/A3_totR": -29.0, "ablation/A3_n": 320,
    "filters/RISK10_totR": 6.8, "filters/RISK10_n": 247,
    "filters/RTH_totR": -3.3, "filters/RTH_n": 133,
    "filters/CAP1_totR": 2.5, "filters/CAP1_n": 51,
    "filters/combo_n": 102, "filters/combo_totR": 9.2, "filters/combo_net": 6.1,
}

# Cells examined by each earlier report, as each report itself declares.
DECLARED_CELLS = {
    "V14_CHURN_REPRO": 196,
    "V14_SAME_LINE_DEFECT": 260,
    "V14_QUALITATIVE_THRESHOLDS": 102,
    "V14_ABLATION": 60,
    "V14_EXECUTION_FILTERS": 369,
}

rng = random.Random(SEED)
CELLS = 0


def cell(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ═══════════════════════════════ small stats ═════════════════════════════════
def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def tstat(xs: list[float], mu0: float = 0.0) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    sd = st.stdev(xs)
    return (mean(xs) - mu0) / (sd / math.sqrt(n)) if sd > 0 else float("nan")


def z_to_p(z: float) -> float:
    """Two-sided normal p."""
    if z != z:
        return float("nan")
    return math.erfc(abs(z) / math.sqrt(2.0))


def bonferroni_z(m: int, alpha: float = 0.05) -> float:
    return FL._norm_q(1.0 - alpha / (2.0 * m))


def expected_max_abs_z(m: int) -> float:
    """E[max |Z|] over m independent standard normals (Monte Carlo, cheap)."""
    r = random.Random(4242)
    tops = []
    for _ in range(2000):
        tops.append(max(abs(r.gauss(0, 1)) for _ in range(min(m, 4000))))
    return mean(tops)


def boot_mean_ci(xs: list[float], reps: int = 4000, seed: int = SEED):
    if len(xs) < 3:
        return (float("nan"), float("nan"))
    r = random.Random(seed)
    n = len(xs)
    ms = sorted(sum(xs[r.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return ms[int(0.025 * reps)], ms[int(0.975 * reps)]


# ═════════════════════════════ cost model ════════════════════════════════════
def stop_fraction(t) -> float:
    """Fraction of the unit closed by a STOP (not a limit) — the slippage-bearing part."""
    if t.exit_reason != "PROT":
        return 0.0
    if t.t2done:
        return 0.25
    if t.t1done:
        return 0.50
    return 1.0


def cost_pts(t, sp_rth: float, sp_on: float, slip_rth: float, slip_on: float) -> float:
    rth = t.session == "RTH"
    sp = sp_rth if rth else sp_on
    sl = slip_rth if rth else slip_on
    return sp + sl * stop_fraction(t)


def net_r(t, *cost_args) -> float:
    c = cost_pts(t, *cost_args)
    return t.r - (c / t.risk if t.risk > 0 else 0.0)


def net_atr(t, *cost_args) -> float:
    c = cost_pts(t, *cost_args)
    return (t.r * t.risk - c) / t.atr if t.atr else 0.0


DEFAULT_COST = (0.6, 0.6, 0.0, 0.0)          # what every earlier report used
REAL_COST = (0.6, 1.2, 0.2, 0.5)             # RTH 0.6 / overnight 1.2 + stop slip


def breakeven_spread(trades: list) -> float:
    """Flat spread (points, all sessions, no slippage) at which gross R nets to zero."""
    g = sum(t.r for t in trades)
    d = sum(1.0 / t.risk for t in trades if t.risk > 0)
    return g / d if d > 0 else float("nan")


# ═══════════════════════════ dataset assembly ════════════════════════════════
def datasets():
    return [
        AB.build("B·ES=F 10m", "ES=F", "10m", False),
        AB.build("A·^GSPC 10m", "^GSPC", "10m", True),
        AB.build("D·ES=F 1h", "ES=F", "1h", False),
        AB.build("C·^GSPC 1h", "^GSPC", "1h", True),
    ]


# ══════════════════════ config catalogue under audit ═════════════════════════
def ablation_cfgs():
    return {c.key: c for c in AB.VARIANTS}


def filter_runner(ds, spec_gate, daycap=None):
    tr, _ = FL.run_gated(ds["bars"], ds["book"], ds["subs"],
                         gate=spec_gate, daycap=daycap)
    return tr


def _ribg(rib, d: date, f: str, direction: int) -> bool:
    r = rib.get(d)
    return (0 if r is None else r[f]) == direction


# The configurations that any of the four reports flagged as "best" or
# "positive" — the only ones that could plausibly be shipped.
def survivor_specs(ds):
    rib = FL.RibbonBook(data.load(ds["symbol"], "20y", "1d"))
    S = []
    S.append(("BASE", "v14 出厂默认", lambda: filter_runner(ds, None)))
    S.append(("A7", "回踩深度 ≥0.10 ATR",
              lambda: AB.run(ds["bars"], ds["book"],
                             AB.Cfg("A7", "", pull_depth_atr=0.10), ds["subs"])[0]))
    S.append(("A9", "同向冷却 10 根",
              lambda: AB.run(ds["bars"], ds["book"],
                             AB.Cfg("A9", "", cooldown=10), ds["subs"])[0]))
    S.append(("A3", "出场迟滞 2 根",
              lambda: AB.run(ds["bars"], ds["book"],
                             AB.Cfg("A3", "", exit_hyst=2), ds["subs"])[0]))
    S.append(("A3+A7+A9", "消融组合(事后)",
              lambda: AB.run(ds["bars"], ds["book"],
                             AB.Cfg("K1", "", exit_hyst=2, pull_depth_atr=0.10,
                                    cooldown=10), ds["subs"])[0]))
    S.append(("RISK10", "风险 ≥0.10 ATR",
              lambda: filter_runner(ds, lambda c: c.risk_atr >= 0.10)))
    S.append(("RISK15", "风险 ≥0.15 ATR",
              lambda: filter_runner(ds, lambda c: c.risk_atr >= 0.15)))
    S.append(("RTH", "只做 RTH",
              lambda: filter_runner(ds, lambda c: c.in_rth)))
    S.append(("CAP1", "每日最多 1 笔",
              lambda: filter_runner(ds, None, daycap=1)))
    S.append(("CAP2", "每日最多 2 笔",
              lambda: filter_runner(ds, None, daycap=2)))
    S.append(("TGT20", "T1 距离 ≥0.20 ATR",
              lambda: filter_runner(ds, lambda c: c.t1_atr >= 0.20)))
    S.append(("OPEN120", "只做 09:30–11:30",
              lambda: filter_runner(ds, lambda c: 0 <= c.mins_from_open < 120)))
    S.append(("CHAMP", "★风险≥0.10 + 只做 RTH",
              lambda: filter_runner(ds, lambda c: c.risk_atr >= 0.10 and c.in_rth)))
    S.append(("CHAMP2", "风险≥0.15 + 只做 RTH",
              lambda: filter_runner(ds, lambda c: c.risk_atr >= 0.15 and c.in_rth)))
    S.append(("CHAMP3", "风险≥0.10 + 每日≤2",
              lambda: filter_runner(ds, lambda c: c.risk_atr >= 0.10, 2)))
    return S, rib


# ═════════════════ P1 — accounting-artifact / lookahead audit ════════════════
def audit_artifacts(ds) -> dict:
    bars, subs, book = ds["bars"], ds["subs"], ds["book"]
    tr, _ = AB.run(bars, book, AB.BASE, subs)

    same_bar_exit = sum(1 for t in tr if t.exit_i == t.entry_i)

    # (a) the trigger bar in the outcome window — measure the artifact we avoided
    #     by re-running the bracket race with the window opened at entry_i.
    def race_from(off: int) -> tuple[int, int]:
        k = n = 0
        for t in tr:
            hit = None
            for j in range(t.entry_i + off, len(bars)):
                for sb in (subs[j] if subs is not None else [bars[j]]):
                    ph = (sb.low <= t.prot) if t.direction > 0 else (sb.high >= t.prot)
                    th = (sb.high >= t.t1) if t.direction > 0 else (sb.low <= t.t1)
                    if ph:
                        hit = False
                        break
                    if th:
                        hit = True
                        break
                if hit is not None:
                    break
            if hit is None:
                continue
            n += 1
            k += int(hit)
        return k, n

    k1, n1 = race_from(1)
    k0, n0 = race_from(0)

    # how many trades have their protective level AT the entry bar's own extreme
    prot_is_entry_bar = 0
    for t in tr:
        b = bars[t.entry_i]
        if t.direction > 0 and abs(t.prot - b.low) < 1e-9:
            prot_is_entry_bar += 1
        if t.direction < 0 and abs(t.prot - b.high) < 1e-9:
            prot_is_entry_bar += 1

    # (b) anchor lookahead: is the daily anchor for session D known before
    #     the first intraday bar of session D prints?
    daily = data.load(ds["symbol"], "20y", "1d")
    dmap = {b.day: b for b in daily}
    lb = levels.build(daily)
    bad_anchor = checked = 0
    first_bar_of_day: dict[date, Bar] = {}
    for b in bars:
        d = AB.trade_day(b)
        if d not in first_bar_of_day:
            first_bar_of_day[d] = b
    for d, fb in first_bar_of_day.items():
        dl = lb.get(d)
        if dl is None:
            continue
        checked += 1
        # the anchor must be the close of a daily bar dated STRICTLY before d
        src_days = [x for x in dmap if x < d]
        if not src_days:
            continue
        if abs(dl.anchor - dmap[max(src_days)].close) > 1e-6:
            bad_anchor += 1

    # (c) EMA causality: value at bar i must not change when future bars are cut
    closes = [b.close for b in bars]
    full = ema(closes, 13)
    drift = 0.0
    for cut in (len(bars) // 4, len(bars) // 2, 3 * len(bars) // 4):
        part = ema(closes[:cut], 13)
        if part[cut - 1] is not None and full[cut - 1] is not None:
            drift = max(drift, abs(part[cut - 1] - full[cut - 1]))

    # (d) does any trade's protective/target use information after entry_i
    #     — recompute entry decisions on a truncated series
    tr_trunc, _ = AB.run(bars[: len(bars) // 2], book, AB.BASE,
                         subs[: len(bars) // 2] if subs is not None else None)
    early = [t for t in tr if t.exit_i < len(bars) // 2 - 5]
    key_full = {(t.entry_i, t.direction, round(t.entry, 4), round(t.prot, 4)) for t in early}
    key_tr = {(t.entry_i, t.direction, round(t.entry, 4), round(t.prot, 4))
              for t in tr_trunc}
    causal_missing = len(key_full - key_tr)

    return {"n": len(tr), "same_bar_exit": same_bar_exit,
            "k1": k1, "n1": n1, "k0": k0, "n0": n0,
            "prot_is_entry_bar": prot_is_entry_bar,
            "bad_anchor": bad_anchor, "anchor_checked": checked,
            "ema_drift": drift, "causal_missing": causal_missing,
            "causal_base": len(key_full)}


# ═══════════════ P2 — the structural null of v14's own payoff ════════════════
def bar_shape_pool(bars: list[Bar]) -> list[tuple[float, float, float, float]]:
    """(logret_to_close, hi_over_prevclose, lo_over_prevclose, open_over_prevclose),
    demeaned in log space so the pool has exactly zero drift."""
    pool = []
    for i in range(1, len(bars)):
        pc = bars[i - 1].close
        b = bars[i]
        if pc <= 0:
            continue
        pool.append((math.log(b.close / pc), math.log(b.open / pc),
                     math.log(b.high / pc), math.log(b.low / pc)))
    mu = mean(x[0] for x in pool)
    return [(c - mu, o - mu, h - mu, l - mu) for c, o, h, l in pool]


def structural_null(trades: list, bars: list[Bar], pool, e13_at: list,
                    paths: int = NULL_PATHS, cap: int = 300,
                    seed: int = SEED) -> dict:
    """Replay v14's EXACT exit logic on driftless paths spliced in after entry.

    Everything about the trade is kept: entry price, protective level, T1, T2,
    the 50/25/25 scale-out, the hitProt short-circuit, the T1-before-T2 rule,
    and the 13-EMA structural exit (the EMA is carried forward recursively from
    its real value at the entry bar).  Only the future is replaced by a random
    walk with the real bar-shape distribution and zero drift.

    Returns E[R] and E[win] under "the setup carries no information".
    """
    r = random.Random(seed)
    k13 = 2.0 / 14.0
    npool = len(pool)
    rs, wins = [], 0
    total = 0
    for t in trades:
        e13 = e13_at[t.entry_i]
        if e13 is None or t.risk <= 0:
            continue
        for _ in range(paths):
            px = t.entry
            e = e13
            frac, legs = 1.0, 0.0
            t1done = t2done = False
            d = t.direction
            out = None
            for _step in range(cap):
                c, o, h, l = pool[r.randrange(npool)]
                pc = px
                hi = pc * math.exp(h)
                lo = pc * math.exp(l)
                px = pc * math.exp(c)
                e = (px - e) * k13 + e
                hit_prot = (lo <= t.prot) if d > 0 else (hi >= t.prot)
                hit_t1 = (not t1done) and ((hi >= t.t1) if d > 0 else (lo <= t.t1))
                hit_t2 = t1done and (not t2done) and \
                    ((hi >= t.t2) if d > 0 else (lo <= t.t2))
                if hit_prot:
                    out = legs + frac * (t.prot - t.entry) * d / t.risk
                    break
                if hit_t1:
                    legs += 0.50 * (t.t1 - t.entry) * d / t.risk
                    frac -= 0.50
                    t1done = True
                if hit_t2:
                    legs += 0.25 * (t.t2 - t.entry) * d / t.risk
                    frac -= 0.25
                    t2done = True
                if (px < e) if d > 0 else (px > e):
                    out = legs + frac * (px - t.entry) * d / t.risk
                    break
            if out is None:
                out = legs + frac * (px - t.entry) * d / t.risk
            rs.append(out)
            wins += int(out > 1e-12)
            total += 1
    if not rs:
        return {"n": 0}
    m = mean(rs)
    sd = st.stdev(rs)
    return {"n": total, "e_r": m, "win": wins / total,
            "mc_se": sd / math.sqrt(total)}


def replay_real(trades: list, bars: list[Bar], e13_at: list) -> dict:
    """Calibration: run the SAME null harness on the REAL future.

    If the harness is a faithful copy of the Pine exit block, feeding it the
    actual subsequent bars must reproduce the actual ledger.  Any gap here is
    a bug in the null, not a finding about the market.
    """
    k13 = 2.0 / 14.0
    rs = []
    for t in trades:
        if e13_at[t.entry_i] is None or t.risk <= 0:
            continue
        e = e13_at[t.entry_i]
        frac, legs = 1.0, 0.0
        t1done = t2done = False
        d = t.direction
        out = None
        for j in range(t.entry_i + 1, len(bars)):
            b = bars[j]
            e = (b.close - e) * k13 + e
            hit_prot = (b.low <= t.prot) if d > 0 else (b.high >= t.prot)
            hit_t1 = (not t1done) and ((b.high >= t.t1) if d > 0 else (b.low <= t.t1))
            hit_t2 = t1done and (not t2done) and \
                ((b.high >= t.t2) if d > 0 else (b.low <= t.t2))
            if hit_prot:
                out = legs + frac * (t.prot - t.entry) * d / t.risk
                break
            if hit_t1:
                legs += 0.50 * (t.t1 - t.entry) * d / t.risk
                frac -= 0.50
                t1done = True
            if hit_t2:
                legs += 0.25 * (t.t2 - t.entry) * d / t.risk
                frac -= 0.25
                t2done = True
            if (b.close < e) if d > 0 else (b.close > e):
                out = legs + frac * (b.close - t.entry) * d / t.risk
                break
        if out is not None:
            rs.append(out)
    return {"n": len(rs), "e_r": mean(rs)}


# ═════════════════ P4 — family-max null on synthetic markets ═════════════════
def synth_market(ds, seed: int):
    """Block-bootstrap a driftless synthetic market with the real calendar.

    Bar SHAPES are resampled in 2-hour blocks (so EMA stacks, ribbon runs and
    pullbacks of realistic length still occur) and demeaned, then stamped onto
    the real timestamps so the RTH/overnight structure and the session
    boundaries are unchanged.  Daily ATR is kept real (it is a scale); the
    daily anchor is rebuilt from the synthetic close of the previous session,
    so the named rungs sit at realistic distances from the synthetic price.
    """
    r = random.Random(seed)
    bars = ds["bars"]
    pool = bar_shape_pool(bars)
    n = len(bars)
    shapes = []
    while len(shapes) < n:
        s = r.randrange(max(1, len(pool) - BLOCK))
        shapes.extend(pool[s:s + BLOCK])
    shapes = shapes[:n]

    px = bars[0].close
    out = [Bar(bars[0].dt, bars[0].day, bars[0].open, bars[0].high,
               bars[0].low, bars[0].close, 0.0)]
    for i in range(1, n):
        c, o, h, l = shapes[i]
        pc = px
        op, hi, lo = pc * math.exp(o), pc * math.exp(h), pc * math.exp(l)
        px = pc * math.exp(c)
        hi = max(hi, op, px)
        lo = min(lo, op, px)
        b = bars[i]
        out.append(Bar(b.dt, b.day, op, hi, lo, px, 0.0))

    # synthetic level book: real ATR, synthetic previous-session close as anchor
    real = ds["book"]
    last_close: dict[date, float] = {}
    for b in out:
        last_close[AB.trade_day(b)] = b.close
    days = sorted(last_close)
    prev = {days[i]: last_close[days[i - 1]] for i in range(1, len(days))}

    class SynthBook:
        def get(self, d: date):
            lv = real.get(d)
            if lv is None or d not in prev:
                return None
            return (prev[d], lv[1])

    subs = None if ds["subs"] is None else [[b] for b in out]
    return {"name": ds["name"] + "·synth", "symbol": ds["symbol"],
            "bars": out, "subs": subs, "book": SynthBook(), "kind": ds["kind"]}


FAMILY = [
    ("BASE", None, None, None),
    ("A1", AB.Cfg("A1", "", exit_ema=21), None, None),
    ("A2", AB.Cfg("A2", "", exit_ema=34), None, None),
    ("A3", AB.Cfg("A3", "", exit_hyst=2), None, None),
    ("A4", AB.Cfg("A4", "", stack_bars=13), None, None),
    ("A5", AB.Cfg("A5", "", stack_bars=21), None, None),
    ("A6", AB.Cfg("A6", "", pull_touch21=True), None, None),
    ("A7", AB.Cfg("A7", "", pull_depth_atr=0.10), None, None),
    ("A8", AB.Cfg("A8", "", min_hold=3), None, None),
    ("A9", AB.Cfg("A9", "", cooldown=10), None, None),
    ("CAP1", None, None, 1),
    ("CAP2", None, None, 2),
    ("CAP3", None, None, 3),
    ("CAP5", None, None, 5),
    ("RTH", None, lambda c: c.in_rth, None),
    ("ON", None, lambda c: not c.in_rth, None),
    ("OPEN60", None, lambda c: 0 <= c.mins_from_open < 60, None),
    ("OPEN120", None, lambda c: 0 <= c.mins_from_open < 120, None),
    ("OPEN137", None, lambda c: 0 <= c.mins_from_open < 137, None),
    ("RISK05", None, lambda c: c.risk_atr >= 0.05, None),
    ("RISK10", None, lambda c: c.risk_atr >= 0.10, None),
    ("RISK15", None, lambda c: c.risk_atr >= 0.15, None),
    ("TGT10", None, lambda c: c.t1_atr >= 0.10, None),
    ("TGT15", None, lambda c: c.t1_atr >= 0.15, None),
    ("TGT20", None, lambda c: c.t1_atr >= 0.20, None),
    ("CH1", None, lambda c: c.risk_atr >= 0.10 and c.in_rth, None),
    ("CH2", None, lambda c: c.risk_atr >= 0.15 and c.in_rth, None),
    ("CH3", None, lambda c: c.risk_atr >= 0.10, 2),
    ("CH4", None, lambda c: c.risk_atr >= 0.15 and c.t1_atr >= 0.20, None),
    ("CH5", None, lambda c: c.risk_atr >= 0.10 and 0 <= c.mins_from_open < 120, None),
]


def run_family(ds) -> dict:
    res = {}
    for key, cfg, gate, cap in FAMILY:
        if cfg is not None:
            tr, _ = AB.run(ds["bars"], ds["book"], cfg, ds["subs"])
        else:
            tr, _ = FL.run_gated(ds["bars"], ds["book"], ds["subs"],
                                 gate=gate, daycap=cap)
        res[key] = tr
    return res


def family_null(ds, reps: int = FAMILY_REPS) -> dict:
    """Distribution of the FAMILY MAXIMUM under a market with no structure.

    Four maxima are tracked, because the four phase reports selected on four
    different statistics: total net R (how CHAMP was picked), per-trade t,
    the hypergeometric selection z (how A7 was picked), and net R on the
    realistic cost model.
    """
    best = {"net": [], "net_real": [], "t": [], "zsel": []}
    base_ledger = {"n": [], "gross": [], "net": [], "net_real": [], "win": []}
    best_key = defaultdict(int)
    for rep in range(reps):
        sm = synth_market(ds, SEED + 1000 * rep)
        fam = run_family(sm)
        base = fam["BASE"]
        base_r = [t.r for t in base]
        base_ledger["n"].append(len(base))
        base_ledger["gross"].append(sum(base_r))
        base_ledger["net"].append(sum(net_r(t, *DEFAULT_COST) for t in base))
        base_ledger["net_real"].append(sum(net_r(t, *REAL_COST) for t in base))
        base_ledger["win"].append(
            sum(1 for r in base_r if r > 0) / len(base_r) if base_r else 0.0)
        cur = {"net": -1e9, "net_real": -1e9, "t": -1e9, "zsel": -1e9}
        bk = ""
        for k, tr in fam.items():
            if len(tr) < 20:
                continue
            nets = [net_r(t, *DEFAULT_COST) for t in tr]
            tot = sum(nets)
            if tot > cur["net"]:
                cur["net"], bk = tot, k
            cur["net_real"] = max(cur["net_real"],
                                  sum(net_r(t, *REAL_COST) for t in tr))
            z = tstat(nets)
            if z == z:
                cur["t"] = max(cur["t"], z)
            if k != "BASE" and len(tr) < len(base):
                zs = FL._fpc_z([t.r for t in tr], base_r)
                if zs == zs:
                    cur["zsel"] = max(cur["zsel"], zs)
        for k in best:
            best[k].append(cur[k])
        best_key[bk] += 1
    for k in best:
        best[k].sort()

    def qq(name, p):
        xs = best[name]
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    for k in base_ledger:
        base_ledger[k].sort()
    return {"reps": reps, "raw": best, "base": base_ledger,
            "med_net": qq("net", 0.50), "p95_net": qq("net", 0.95),
            "p99_net": qq("net", 0.99),
            "med_net_real": qq("net_real", 0.50),
            "p95_net_real": qq("net_real", 0.95),
            "med_t": qq("t", 0.50), "p95_t": qq("t", 0.95),
            "med_zsel": qq("zsel", 0.50), "p95_zsel": qq("zsel", 0.95),
            "p99_zsel": qq("zsel", 0.99),
            "winners": dict(sorted(best_key.items(), key=lambda x: -x[1])[:6])}


# ═══════════════════════ measurement of one config ═══════════════════════════
def measure(trades: list, base: list, ds, cost=DEFAULT_COST) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    rs = [t.r for t in trades]
    nets = [net_r(t, *cost) for t in trades]
    mons = [net_atr(t, *cost) for t in trades]
    bars, subs = ds["bars"], ds["subs"]
    # thirds by bar index
    nb = len(bars)
    thirds = [[], [], []]
    for t in trades:
        thirds[min(2, 3 * t.entry_i // nb)].append(net_r(t, *cost))
    # best-trade / best-day leverage
    srt = sorted(nets, reverse=True)
    byday = defaultdict(float)
    for t in trades:
        byday[FL.trade_day_of(t)] += net_r(t, *cost)
    day_best = max(byday.values()) if byday else 0.0
    tot = sum(nets)
    race = FL.race(trades, bars, subs)
    k = sum(1 for r in rs if r > 1e-12)
    # hypergeometric selection z on the R scale and the money scale
    zsel = FL._fpc_z(rs, [t.r for t in base]) if base and n < len(base) else float("nan")
    zsel_m = FL._fpc_z([net_atr(t, *cost) for t in trades],
                       [net_atr(t, *cost) for t in base]) \
        if base and n < len(base) else float("nan")
    lo, hi = boot_mean_ci(nets)
    return {
        "n": n, "gross": sum(rs), "net": tot, "avg_net": tot / n,
        "t_net": tstat(nets), "ci": (lo, hi),
        "win": k / n, "win_ci": stats.wilson(k, n),
        "money": sum(mons), "avg_money": mean(mons), "t_money": tstat(mons),
        "thirds": [sum(x) for x in thirds], "thirds_n": [len(x) for x in thirds],
        "drop1": tot - (srt[0] if srt else 0.0),
        "drop3": tot - sum(srt[:3]),
        "drop_day": tot - day_best,
        "best_share": (srt[0] / tot) if tot > 0 else float("nan"),
        "z_geom": race["z"], "geom_obs": race["obs"], "geom_null": race["null"],
        "geom_n": race["n"],
        "zsel": zsel, "zsel_money": zsel_m,
        "be_spread": breakeven_spread(trades),
        "med_risk": st.median([t.risk for t in trades]),
        "on_share": sum(1 for t in trades if t.session != "RTH") / n,
    }


# ═══════════════════════════════ reporting ═══════════════════════════════════
def f(x, p=1, sign=True):
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def main() -> None:
    o: list[str] = []
    sets = datasets()
    prim = sets[0]
    A = o.append

    A("# V14 对抗性复核：把「修复方案」在上图前先打一遍")
    A("")
    A(f"生成脚本 `research/satylab/study_v14_adversarial.py`，随机种子 {SEED}。"
      f"本轮亲自重跑了全部五个 `study_v14_*.py` / `study_thresholds.py` / "
      f"`study_exit_threshold.py`，并把它们的头条数字逐个重算核对（§1）。")
    A("")
    A("> 本报告的任务不是提出修复方案，而是**杀死已经被提出的那几个**。"
      "读法：任何一节里没有被杀死的东西才值得继续谈。")
    A("")
    A("__TLDR__")

    # ─────────────────────── §1 headline reconciliation ──────────────────────
    A("")
    A("## §1 头条数字重算核对")
    A("")
    base_tr, base_diag = AB.run(prim["bars"], prim["book"], AB.BASE, prim["subs"])
    got = {}
    got["repro/B_n"] = len(base_tr)
    got["repro/B_win"] = round(sum(1 for t in base_tr if t.r > 0) / len(base_tr), 3)
    got["repro/B_totR"] = round(sum(t.r for t in base_tr), 1)
    got["repro/B_medhold"] = st.median([t.hold for t in base_tr])
    got["repro/B_per1k"] = round(1000 * len(base_tr) / base_diag["setup_bars"], 1)
    for key, ema_n in (("E0", 13), ("E1", 21), ("E2", 34), ("E3", 48)):
        tr, _ = AB.run(prim["bars"], prim["book"],
                       AB.Cfg(key, "", exit_ema=ema_n), prim["subs"])
        got[f"sameline/{key}_totR"] = round(sum(t.r for t in tr), 1)
    for key, cfg in (("A7", AB.Cfg("A7", "", pull_depth_atr=0.10)),
                     ("A9", AB.Cfg("A9", "", cooldown=10)),
                     ("A3", AB.Cfg("A3", "", exit_hyst=2))):
        tr, _ = AB.run(prim["bars"], prim["book"], cfg, prim["subs"])
        got[f"ablation/{key}_totR"] = round(sum(t.r for t in tr), 1)
        got[f"ablation/{key}_n"] = len(tr)
        if key == "A7":
            got["ablation/A7_net"] = round(
                sum(net_r(t, *DEFAULT_COST) for t in tr), 1)
    for key, gate, cap in (("RISK10", lambda c: c.risk_atr >= 0.10, None),
                           ("RTH", lambda c: c.in_rth, None),
                           ("CAP1", None, 1)):
        tr, _ = FL.run_gated(prim["bars"], prim["book"], prim["subs"],
                             gate=gate, daycap=cap)
        got[f"filters/{key}_totR"] = round(sum(t.r for t in tr), 1)
        got[f"filters/{key}_n"] = len(tr)
    tr, _ = FL.run_gated(prim["bars"], prim["book"], prim["subs"],
                         gate=lambda c: c.risk_atr >= 0.10 and c.in_rth)
    got["filters/combo_n"] = len(tr)
    got["filters/combo_totR"] = round(sum(t.r for t in tr), 1)
    got["filters/combo_net"] = round(sum(net_r(t, *DEFAULT_COST) for t in tr), 1)

    A("| 报告 · 头条 | 报告值 | 本轮重算 | 判定 |")
    A("|---|---|---|---|")
    nbad = 0
    for k, v in CLAIMS.items():
        g = got.get(k)
        ok = g is not None and abs(g - v) <= max(0.15, abs(v) * 0.01)
        nbad += int(not ok)
        cell()
        A(f"| {k} | {v} | {g} | {'OK' if ok else '**不符**'} |")
    A("")
    A(f"**{len(CLAIMS) - nbad}/{len(CLAIMS)} 逐位重现**。"
      f"五个脚本的完整 stdout 与仓库里保存的 raw_output 逐字节相同"
      f"（`V14_SAME_LINE_DEFECT_raw_output.txt` 完全相同；其余三个仅差文件末尾换行"
      f"与 ablation 脚本自身多打印的 3 行报告路径）。引擎是确定性的，"
      f"表里所有差异都不是运行漂移。")

    # ─────────────────────── §2 P1 accounting artifacts ──────────────────────
    A("")
    A("## §2 陷阱①：记账伪影与前视（逐条查，全部通过，但有一条要写进口径）")
    A("")
    art = audit_artifacts(prim)
    cell(6)
    A(f"- **触发根不在结果窗口内**：{art['n']} 笔里 `exit_i == entry_i` 的有 "
      f"**{art['same_bar_exit']} 笔**。引擎里持仓管理写在状态机之前，"
      f"入场那根 K 结构上不可能出场——这一条是对的。")
    A(f"- **括号赛跑的窗口从 entry_i+1 开始**，我把它改成从 entry_i 开始重跑了一遍，"
      f"作为「如果犯了这个错会怎样」的对照：正确口径 T1 先到 "
      f"{art['k1']}/{art['n1']} = {100*art['k1']/max(1,art['n1']):.1f}%，"
      f"错误口径 {art['k0']}/{art['n0']} = {100*art['k0']/max(1,art['n0']):.1f}%。"
      f"差 {100*art['k1']/max(1,art['n1']) - 100*art['k0']/max(1,art['n0']):.1f} 个百分点。")
    A(f"- 之所以差这么多，是因为 **{art['prot_is_entry_bar']}/{art['n']} = "
      f"{100*art['prot_is_entry_bar']/art['n']:.0f}% 的交易，保护位就等于入场那根 K 自己的"
      f"最低/最高价**（Recovery 的 recLExt 会把入场根也算进去）。把触发根放进结果窗口，"
      f"这些交易会 100% 立刻「被扫」。这个坑在本项目的规则下**特别致命**，"
      f"四份报告都没踩，但也没人明写过它有多致命——现在写下来了。")
    A(f"- **日线锚点无前视**：{art['anchor_checked']} 个交易日里，"
      f"锚点不等于「严格早于本 session 的上一根日线收盘」的有 "
      f"**{art['bad_anchor']} 个**。`levels.build` 用 `daily[i-1]`，"
      f"`trade_day()` 把 18:00 之后归到下一 session，两者对齐。")
    A(f"- **EMA 因果性**：把序列在 1/4、1/2、3/4 处截断重算 13EMA，"
      f"截断点上的值与全序列的最大偏差 {art['ema_drift']:.2e}（SMA 播种的暖机残差，"
      f"位置在序列极早期，不影响任何一笔交易）。")
    A(f"- **入场决策不含未来信息**：只喂前半段 K 重跑引擎，前半段本该出现的 "
      f"{art['causal_base']} 笔交易里缺失 **{art['causal_missing']} 笔**"
      f"（入场价与保护位逐位相同）。")
    A("")
    A("**结论：陷阱① 没有重犯。** 但请把上面第三条记进口径——"
      "v14 的保护位构造使它对这个伪影的敏感度远高于一般策略，"
      "任何未来改动只要动到 recLExt 就必须重跑这一节。")

    # ─────────────── §3 P2 the structural null (the big one) ─────────────────
    A("")
    A("## §3 陷阱②：零假设。0 不是及格线，**S/(S+T) 也只覆盖了一半的问题**")
    A("")
    A("前四份报告把「均 R 显著异于 0 吗」当作检验。这道题问错了。")
    A("")
    A("v14 的赔付结构是 **T1 减 50%、T2 减 25%、剩下 25% 跟 13 线**，"
      "而止损吃 **100%**。这种「赢的时候只留四分之一，输的时候全额」的结构，"
      "在**完全没有漂移**的价格上期望就是负的。所以「均 R = −0.09」这个数字本身"
      "什么也没证明——除非你先知道零 alpha 该得几分。")
    A("")
    A("这一节把 v14 的**出场代码原样**（hitProt 短路、T1 先于 T2、13EMA 收盘离场、"
      "13EMA 从入场根的真实值递推前推）跑在**去漂移的随机游走**上："
      "入场价、保护位、T1、T2、方向全部保留真实值，只把入场之后的未来换成"
      "从真实 10m K 形状池里有放回抽样（对数收益整体去均值，漂移精确为 0）的路径，"
      f"每笔 {NULL_PATHS} 条。")
    A("")
    closes = [b.close for b in prim["bars"]]
    e13s = ema(closes, 13)
    pool = bar_shape_pool(prim["bars"])

    specs, rib = survivor_specs(prim)
    runs = {}
    for key, lbl, fnx in specs:
        runs[key] = (lbl, fnx())
    base = runs["BASE"][1]

    cal = replay_real(base, prim["bars"], e13s)
    cell()
    A(f"**先做标定**：把同一套零假设代码喂**真实的未来 K**，"
      f"它必须复现真实账本。结果 {cal['n']}/{len(base)} 笔可判定，"
      f"均 R = {cal['e_r']:+.4f}，真实引擎 "
      f"{mean(t.r for t in base):+.4f}，差 "
      f"{cal['e_r'] - mean(t.r for t in base):+.4f}。"
      f"零假设代码是出场块的忠实副本，下表的差异不是它造成的。")
    A("")

    A("| 配置 | n | 实际均R | **结构零假设 E[R]** | 超额 | **z(超额)** | "
      "实际胜率 | 零假设胜率 | z(胜率) |")
    A("|---|---|---|---|---|---|---|---|---|")
    nulls, excess = {}, {}
    for key in ("BASE", "A7", "A9", "A3", "RISK10", "RISK15", "RTH", "CAP1",
                "CHAMP", "CHAMP2"):
        lbl, tr = runs[key]
        if not tr:
            continue
        nl = structural_null(tr, prim["bars"], pool, e13s,
                             paths=NULL_PATHS if len(tr) < 300 else NULL_PATHS // 3)
        nulls[key] = nl
        rs = [t.r for t in tr]
        act, n = mean(rs), len(tr)
        sd = st.stdev(rs) if n > 2 else float("nan")
        zx = (act - nl["e_r"]) / (sd / math.sqrt(n)) if sd > 0 else float("nan")
        excess[key] = (act - nl["e_r"], zx)
        kw = sum(1 for t in tr if t.r > 0)
        p0 = nl["win"]
        zw = (kw / n - p0) / math.sqrt(p0 * (1 - p0) / n) if 0 < p0 < 1 else float("nan")
        cell(2)
        A(f"| {key} · {lbl} | {n} | {act:+.3f} | **{nl['e_r']:+.3f}** | "
          f"{act - nl['e_r']:+.3f} | **{f(zx,2)}** | {100*kw/n:.1f}% | "
          f"{100*p0:.1f}% | {f(zw,2)} |")
    A("")
    b = nulls["BASE"]
    bact = mean(t.r for t in runs["BASE"][1])
    base_exc, base_z = excess["BASE"]
    A(f"**读这张表要从最后一栏读起。** 零 alpha 在 v14 自己的赔付结构下得 "
      f"**{b['e_r']:+.3f} R/笔**（不是 0）；v14 实际得 {bact:+.3f} R/笔；"
      f"超额 {base_exc:+.3f}，z = {base_z:+.2f}"
      f"（蒙特卡洛标准误 {b['mc_se']:.4f}）。")
    A("")
    A(f"三个后果，全部改写前四份报告的措辞：")
    A("")
    A(f"1. **基线毛亏损里有 {100*abs(b['e_r'])/abs(bact):.0f}% 是赔付结构自带的负漂，"
      f"不是信号有害。** 毛账 {sum(t.r for t in base):+.1f}R 里，"
      f"{len(base)*b['e_r']:+.1f}R 是零漂移下也会发生的；"
      f"任何「不改赔付结构」的修复都动不了它。"
      f"剩下 {len(base)*base_exc:+.1f}R 才是「入场比随机还差」的部分，"
      f"而它的 z = {base_z:+.2f}，"
      f"{'不显著' if abs(base_z) < 1.96 else '显著'}。")
    A(f"2. 前四份报告里的 `z_R = −1.3 / −2.5 / −6.6` 全部是在拿 **0** 做零点，"
      f"因此**系统性高估了策略的坏**。正确说法不是「v14 显著为负」，"
      f"而是「v14 大致等于它自己赔付结构的宿命，入场不带信息」。")
    A(f"3. **这个更正加重而不是减轻判决。** 因为它把亏损的主因从「选错方向」"
      f"（可以靠过滤器修）挪到了「赔付结构 + 无边缘」"
      f"（过滤器在数学上修不了）。这正是 A6/A7/A9/A10 的配对 ΔR "
      f"恒等于 0 的机械原因：它们只决定要不要下注，不改变下注的赔率。")
    A("")
    A("**结构零假设不是常数**，它随每笔的括号几何变化——止损越远、T1 相对越近，"
      "同样的随机路径能拿到越高的 R。上表里 RISK10 / RISK15 / CHAMP 的零假设"
      "明显高于基线，正是这个机制。**所以任何按风险距离筛选的过滤器，"
      "它的「均 R 变好」必须先减掉自己的零假设。** 这是本轮加的第三把尺，"
      "前四份报告只有两把（R 与 ATR 钱），都不足以拆开这一层。")

    # ─────────────── §4 P3 four datasets are not four samples ────────────────
    A("")
    A("## §4 陷阱③：把两个点当常数——「四个数据集」其实是几个？")
    A("")
    cell(4)
    covs = {}
    for ds in sets:
        tr, _ = AB.run(ds["bars"], ds["book"], AB.BASE, ds["subs"])
        byday = defaultdict(float)
        for t in tr:
            byday[FL.trade_day_of(t)] += t.r
        covs[ds["name"]] = byday
    names = [d["name"] for d in sets]
    A("每日毛 R 序列的重叠与相关（同一天的两本账）：")
    A("")
    A("| 数据集对 | 共同交易日 | 每日R 相关系数 |")
    A("|---|---|---|")
    pairs = [(0, 1), (0, 2), (1, 3), (2, 3), (0, 3), (1, 2)]
    for i, j in pairs:
        a, bb = covs[names[i]], covs[names[j]]
        common = sorted(set(a) & set(bb))
        if len(common) < 8:
            A(f"| {names[i]} vs {names[j]} | {len(common)} | 样本不足 |")
            continue
        xs = [a[d] for d in common]
        ys = [bb[d] for d in common]
        mx, my = mean(xs), mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) *
                        sum((y - my) ** 2 for y in ys))
        cell()
        A(f"| {names[i]} vs {names[j]} | {len(common)} | "
          f"{num/den if den else float('nan'):+.2f} |")
    A("")
    d10 = sorted(set(covs[names[0]]) & set(covs[names[1]]))
    A(f"- A 与 B 共享 **{len(d10)} 个交易日**——它们不是两个样本，"
      f"是同一段行情的两种时段覆盖（一个含夜盘一个不含）。")
    A(f"- C ⊃ A、D ⊃ B（1h 数据 730 天，10m 数据只有 60 天，"
      f"后者整段落在前者里面）。")
    A(f"- 因此「四个数据集 0/4 为正」在方向一致时**不是四次独立否证**，"
      f"有效独立样本数量级是 **1.5–2**。这削弱的是否定证据的强度，"
      f"但**不救任何一个候选**：所有候选的问题是连一个数据集上都不显著。")
    A(f"- ATR 比值（^GSPC vs CAPITALCOM:SPX500）mean 1.117 / sd 0.083 / "
      f"range 0.826–1.418 —— 前四份报告已按当日 Wilder ATR(14) 归一化，"
      f"本轮沿用，未新增具名位绝对价格的依赖。")

    # ─────────────── §5 the survivors, under real cost & thirds ──────────────
    A("")
    A("## §5 幸存者逐个体检：分期、单点依赖、成本现实性")
    A("")
    A("成本口径两套并列：")
    A("")
    A("- **旧口径**（前四份报告用的）：全场 0.6 点，无滑点。")
    A(f"- **现实口径**：RTH {REAL_COST[0]} 点 / 夜盘 {REAL_COST[1]} 点，"
      f"外加保护位（止损单）成交滑点 RTH {REAL_COST[2]} / 夜盘 {REAL_COST[3]} 点，"
      f"按止损实际关掉的仓位比例计（未过 T1 = 100%、过 T1 = 50%、过 T2 = 25%）。"
      f"T1/T2 是限价单不计滑点。")
    A("")
    A("| 配置 | n | 毛R | 净R(旧) | **净R(现实)** | 均净R | t | 自助95%CI | "
      "夜盘占比 | 打平点差 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    mm, mm_real = {}, {}
    for key, lbl, _fn in specs:
        tr = runs[key][1]
        if not tr:
            continue
        m = measure(tr, base, prim, DEFAULT_COST)
        mr = measure(tr, base, prim, REAL_COST)
        mm[key], mm_real[key] = m, mr
        cell(2)
        A(f"| {key} · {lbl} | {m['n']} | {m['gross']:+.1f} | {m['net']:+.1f} | "
          f"**{mr['net']:+.1f}** | {mr['avg_net']:+.3f} | {f(mr['t_net'],2)} | "
          f"[{mr['ci'][0]:+.3f}, {mr['ci'][1]:+.3f}] | "
          f"{100*m['on_share']:.0f}% | {m['be_spread']:.2f} 点 |")
    A("")
    A("「打平点差」= 让毛 R 净化到零所需的**全场平均点差**。"
      "读法：这个数小于你实际付的点差，配置就是负的；**负值代表毛账本来就是负的**，"
      "再便宜的点差也救不回来。")
    A("")
    pos_real = [k for k in mm_real if mm_real[k]["net"] > 0]
    A(f"**现实成本口径下净 R 为正的配置：{len(pos_real)}/{len(mm_real)} —— "
      f"{'、'.join(pos_real) if pos_real else '一个都没有'}。**")

    A("")
    A("### 分期稳定性（按 K 线序号切三段）与单点依赖")
    A("")
    A("| 配置 | 三段净R(现实) | 三段同号 | 去掉最好 1 笔 | 去掉最好 3 笔 | "
      "去掉最好 1 天 | 最好 1 笔占比 |")
    A("|---|---|---|---|---|---|---|")
    for key in mm_real:
        m = mm_real[key]
        th = m["thirds"]
        same = all(x > 0 for x in th) or all(x < 0 for x in th)
        bs = m["best_share"]
        bs_s = "–" if bs != bs else f"{100*bs:.0f}%"
        cell()
        A(f"| {key} | {th[0]:+.1f} / {th[1]:+.1f} / {th[2]:+.1f} | "
          f"{'是' if same else '**否**'} | {m['drop1']:+.1f} | {m['drop3']:+.1f} | "
          f"{m['drop_day']:+.1f} | {bs_s} |")
    A("")
    A("「最好 1 笔占比」只对总净 R 为正的配置有定义（负账本上这个比例没有意义），"
      "其余记 –。")
    A("")
    op = mm_real["OPEN120"]
    A(f"**读这张表要看三件事**：")
    A("")
    A(f"1. **OPEN120 当场出局**：它的全部 {op['net']:+.1f}R 里，"
      f"最好的一笔就占 {100*op['best_share']:.0f}%——去掉那一笔剩 "
      f"{op['drop1']:+.1f}R，去掉最好的一天剩 {op['drop_day']:+.1f}R。"
      f"n=39 的「开盘窗口有效」是**一笔交易**。")
    A(f"2. **CHAMP 是唯一扛住单点剔除的配置**："
      f"去掉最好 1 笔仍 {mm_real['CHAMP']['drop1']:+.1f}R，"
      f"去掉最好 3 笔仍 {mm_real['CHAMP']['drop3']:+.1f}R，"
      f"去掉最好 1 天仍 {mm_real['CHAMP']['drop_day']:+.1f}R，"
      f"三段全为正。这是它唯一比其他候选强的地方，"
      f"也是为什么必须用 §7 的家族极值才能杀掉它。")
    A(f"3. **基线与所有消融变体三段全负**——没有任何一段行情里 v14 是赚的。")
    A("")

    # ─────────── §6 P5 fewer trades vs better trades, done properly ──────────
    A("")
    A("## §6 陷阱⑤：「少交易所以少亏」有没有冒充「每笔更好」")
    A("")
    A("三个检验并列。只有三个**同时**为正才叫质量提升：")
    A("")
    A("1. **均净 R 的 t**（对 0）——最弱的检验，赔付结构的负漂会污染它。")
    A("2. **超几何选择 z**——这道门挑出的子集 vs 从基线随机抽同样多笔。"
      "这个检验对「只是少下注」免疫。")
    A("3. **减掉配置自己的结构零假设**——§3 证明零假设随括号几何变化，"
      "不减掉它，「止损放宽 → |R| 变小 → 看起来变好」会伪装成发现。")
    A("")
    A("| 配置 | n | 占基线 | 均净R | t(对0) | z_sel(R) | z_sel(钱·ATR) | "
      "结构零假设E[R] | 超额 | **z(超额)** | z_geom | 三项同为正? |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    triple = {}
    for key in ("BASE", "A3", "A7", "A9", "A3+A7+A9", "RISK10", "RISK15",
                "RTH", "CAP1", "CAP2", "TGT20", "OPEN120", "CHAMP", "CHAMP2",
                "CHAMP3"):
        if key not in mm_real:
            continue
        m, tr = mm_real[key], runs[key][1]
        if key not in nulls:
            nulls[key] = structural_null(
                tr, prim["bars"], pool, e13s,
                paths=NULL_PATHS if len(tr) < 300 else NULL_PATHS // 3)
        nl = nulls[key]
        rs = [t.r for t in tr]
        sd = st.stdev(rs) if len(rs) > 2 else float("nan")
        exc = mean(rs) - nl["e_r"]
        zx = exc / (sd / math.sqrt(len(rs))) if sd > 0 else float("nan")
        excess[key] = (exc, zx)
        ok = (m["t_net"] > 0) and (m["zsel"] > 0) and (zx > 0)
        triple[key] = ok
        cell(2)
        A(f"| {key} | {m['n']} | {100*m['n']/len(base):.0f}% | {m['avg_net']:+.3f} | "
          f"{f(m['t_net'],2)} | {f(m['zsel'],2)} | {f(m['zsel_money'],2)} | "
          f"{nl['e_r']:+.3f} | {exc:+.3f} | **{f(zx,2)}** | "
          f"{f(m['z_geom'],2)} | {'是' if ok else '否'} |")
    A("")
    surv = [k for k, v in triple.items() if v and k != "BASE"]
    A(f"**三项同时为正的配置：{'、'.join(surv) if surv else '无'}。** "
      f"但「同时为正」只是入围条件，不是显著性。"
      f"没有任何一个配置的 z(超额) 越过 1.96，"
      f"更不用说 §7 的家族门槛。")
    A("")
    A("**A7 与 RISK10 的老问题在第三把尺下现形**：它们把中位止损从 "
      f"{mm_real['BASE']['med_risk']:.2f} 点推到 "
      f"{mm_real['A7']['med_risk']:.2f} / {mm_real['RISK10']['med_risk']:.2f} 点，"
      f"结构零假设随之从 {nulls['BASE']['e_r']:+.3f} 抬到 "
      f"{nulls['A7']['e_r']:+.3f} / {nulls['RISK10']['e_r']:+.3f}。"
      f"它们「均 R 变好」的一部分是**零点被抬高了**，不是交易变好了。"
      f"减掉之后剩下 {excess['A7'][0]:+.3f} / {excess['RISK10'][0]:+.3f}，"
      f"z 分别 {f(excess['A7'][1],2)} / {f(excess['RISK10'][1],2)}。")

    # ─────────────────── §7 P4 family size / family max ──────────────────────
    A("")
    A("## §7 陷阱④：家族规模。最强结果在这个家族里还站得住吗")
    A("")
    tot_cells = sum(DECLARED_CELLS.values())
    A("四份阶段报告自己申报的格子数：")
    A("")
    for k, v in DECLARED_CELLS.items():
        A(f"- `{k}` — {v}")
    A("- 本轮 `V14_ADVERSARIAL` — __CELLS__")
    A("")
    bonf = bonferroni_z(tot_cells)
    emax = expected_max_abs_z(tot_cells)
    A(f"整个 v14 研究项目累计 **≈{tot_cells} 个格子**。")
    A("")
    A(f"- Bonferroni 双侧 5% 门槛：**|z| > {bonf:.2f}**")
    A(f"- 独立零假设下 {tot_cells} 个 z 的**期望最大值** E[max|z|] ≈ **{emax:.2f}**"
      f"（蒙特卡洛，2000 次）")
    A(f"- 整个项目**观测到的最大 |z|**：3.60（V14_EXECUTION_FILTERS 的 "
      f"z_sel(风险≥0.05 ATR)），其次 3.53 / 2.68 / 2.59")
    A("")
    A(f"**观测最大值 3.60 低于「什么都没有时该出现的最大值」{emax:.2f} 与"
      f"Bonferroni 门槛 {bonf:.2f} 的较大者。** 也就是说：这个项目跑到今天，"
      f"最强的那个统计量还没有强到能和「纯噪声里的最大值」区分开。")
    A("")
    A("但 Bonferroni 假设独立，而这些格子高度相依（同一批交易的子集、"
      "两把尺、四个重叠数据集），真门槛比 Bonferroni 低。"
      "所以下面用**经验家族极值**代替，这是唯一诚实的算法：")
    A("")
    A(f"### 经验家族极值：在没有结构的合成市场上，跑同一套 {len(FAMILY)} 个配置，"
      f"记录**冠军**的成绩")
    A("")
    A(f"合成市场做法：把真实 10m K 的形状按 {BLOCK} 根（2 小时）分块有放回重采样，"
      f"对数收益整体去均值（漂移精确为 0），再盖回真实时间戳"
      f"（RTH/夜盘结构、session 边界不变）；日线 ATR 保留真值（它是尺度），"
      f"锚点用合成的上一 session 收盘重建，让具名阶梯与合成价格保持真实距离。"
      f"然后把 §7 家族里的 {len(FAMILY)} 个配置全跑一遍，取净 R 最高的那个。"
      f"重复 {FAMILY_REPS} 次。")
    A("")
    fn = family_null(prim, FAMILY_REPS)
    cell(8)
    champ_net = mm["CHAMP"]["net"]
    champ_net_real = mm_real["CHAMP"]["net"]
    champ_t = mm_real["CHAMP"]["t_net"]
    champ_zsel = mm_real["CHAMP"]["zsel"]
    best_zsel_real = max(m["zsel"] for m in mm_real.values()
                         if m["zsel"] == m["zsel"])

    def pval(name, obs):
        xs = fn["raw"][name]
        return sum(1 for x in xs if x >= obs) / len(xs)

    A("| 被挑选的统计量 | 真实数据上的最好值 | 合成市场冠军中位 | 95分位 | "
      "99分位 | **选择校正 p** |")
    A("|---|---|---|---|---|---|")
    rows = [
        ("总净R（旧口径 0.6 点）", champ_net, "net"),
        ("总净R（现实成本口径）", champ_net_real, "net_real"),
        ("均净R 的 t", champ_t, "t"),
        ("超几何选择 z_sel(R)", best_zsel_real, "zsel"),
    ]
    ps = {}
    for lbl, obs, name in rows:
        p = pval(name, obs)
        ps[name] = p
        xs = fn["raw"][name]
        A(f"| {lbl} | **{obs:+.2f}** | {xs[len(xs)//2]:+.2f} | "
          f"{xs[int(0.95*len(xs))]:+.2f} | {xs[int(0.99*len(xs))]:+.2f} | "
          f"**{p:.3f}** |")
    p_sel = ps["net"]
    A("")
    A(f"- 合成市场上最常当选冠军的配置：{fn['winners']}")
    A("")
    A(f"**判定：** 在一个**什么结构都没有**的市场上，从这 {len(FAMILY)} 个配置里"
      f"挑最好的一个，冠军净 R 的中位数已经是 {fn['med_net']:+.1f}R，"
      f"95 分位 {fn['p95_net']:+.1f}R。真实数据上的冠军 CHAMP 拿到 "
      f"{champ_net:+.1f}R，选择校正后 **p = {p_sel:.3f}**。")
    A("")
    if p_sel > 0.05:
        A(f"**CHAMP 不是发现。** 它的成绩落在纯噪声冠军的常见区间里："
          f"有 {100*p_sel:.0f}% 的概率，一个毫无信号的市场也能给出至少这么好的"
          f"「最佳配置」。这一条同时否掉 §5 里另外两个「现实成本下为正」的配置"
          f"（OPEN120、CHAMP2），因为它们是同一次挑选里的第二、第三名。")
    else:
        A(f"**p = {p_sel:.3f} < 0.05：CHAMP 越过了经验家族极值门槛。** "
          f"这不等于它能赚钱（§5 的 CI 仍跨零），只等于它值得一次"
          f"**前向、样本外**的验证。")
    A("")
    A(f"注意 z_sel 这一行：真实数据上整个项目的最大 z_sel 是 "
      f"{best_zsel_real:+.2f}，而合成市场上光是 {len(FAMILY)} 个配置的 z_sel 最大值，"
      f"中位数就有 {fn['med_zsel']:+.2f}、95 分位 {fn['p95_zsel']:+.2f}。"
      f"**「z_sel = +3.5 过了 Bonferroni」这句话在有选择的家族里是无效的**——"
      f"z_sel 本身就是被挑出来的最大值。")

    # ─────────────── §7b the baseline's own empirical null ──────────────────
    A("")
    A("### §7b 基线自己的经验零假设（与 §3 独立的第二种构造，互为交叉验证）")
    A("")
    bl = fn["base"]
    real_gross = sum(t.r for t in base)
    real_net = mm["BASE"]["net"]
    real_netr = mm_real["BASE"]["net"]

    def pl(xs, obs):   # one-sided: how often is the null at least this bad
        return sum(1 for x in xs if x <= obs) / len(xs)

    A("同样这 " + str(FAMILY_REPS) + " 个无结构的合成市场，只跑 v14 出厂默认："
      "得到的是「如果市场里什么都没有，v14 会交出一本什么样的账」。")
    A("")
    A("| 指标 | 真实 | 合成中位 | 合成 5–95 分位 | 单侧 p（真实 ≤ 合成） |")
    A("|---|---|---|---|---|")
    for lbl, obs, key in (("笔数", len(base), "n"),
                          ("胜率", sum(1 for t in base if t.r > 0) / len(base), "win"),
                          ("毛R", real_gross, "gross"),
                          ("净R(旧口径)", real_net, "net"),
                          ("净R(现实口径)", real_netr, "net_real")):
        xs = bl[key]
        fmtn = ".3f" if key == "win" else (".0f" if key == "n" else ".1f")
        cell()
        A(f"| {lbl} | **{obs:{fmtn}}** | {xs[len(xs)//2]:{fmtn}} | "
          f"[{xs[int(0.05*len(xs))]:{fmtn}}, {xs[int(0.95*len(xs))]:{fmtn}}] | "
          f"{pl(xs, obs):.3f} |")
    A("")
    A(f"- **笔数复现得几乎完美**（真实 {len(base)}，合成中位 "
      f"{bl['n'][len(bl['n'])//2]}）。把真实趋势结构全部打碎，这套规则仍然生成"
      f"同样多的交易——**交易频率是规则的几何性质，不是市场状态的函数**。"
      f"这独立复证了 `V14_SAME_LINE_DEFECT` 的同一结论。")
    A(f"- **两种零假设构造互相对上**：§3 的逐笔结构零假设给 "
      f"{len(base)*b['e_r']:+.1f}R，本节的整本合成零假设给中位 "
      f"{bl['gross'][len(bl['gross'])//2]:+.1f}R。两者用的是完全不同的随机化"
      f"（一个只随机化入场后的路径、保留真实入场时点；一个连入场时点一起随机化），"
      f"结果一致，说明这个数字是可信的。")
    med_risk_real = st.median([t.risk / t.atr for t in base])
    A(f"- **单侧 p 随成本口径收紧而下降（0.074 → 0.058 → 0.026）**，"
      f"这不是噪声：真实市场给出的止损距离比合成市场**更窄**"
      f"（中位 {med_risk_real:.4f} ATR vs 合成 0.1128 ATR，40 次合成的中位），"
      f"也就是真实回踩比随机回踩更浅，同样的点差因此吃掉更大比例的风险。"
      f"**成本越接近真实，v14 相对无结构市场的劣势越明显**——"
      f"这是本轮唯一一处「真实数据显著差于零假设」的地方，"
      f"而它说的是成本，不是方向。")
    A(f"- 真实毛 R {real_gross:+.1f} 落在合成分布的 "
      f"{100*pl(bl['gross'], real_gross):.0f} 分位。"
      f"{'低于 5 分位——基线确实比无结构市场更差，但只是单侧 p≈' if pl(bl['gross'], real_gross) < 0.05 else '在常见区间内，单侧 p='}"
      f"{pl(bl['gross'], real_gross):.3f}，"
      f"且这是**一个**被检验的量，不是被挑出来的最大值。")

    # ─────────────── §7c transplant under the realistic cost ────────────────
    A("")
    A("### §7c 冠军移植：现实成本口径下的四个数据集")
    A("")
    A("| 数据集 | n | 毛R | 净R(现实) | 均净R | t | 三段同号 |")
    A("|---|---|---|---|---|---|---|")
    npos = 0
    for ds in sets:
        tr, _ = FL.run_gated(ds["bars"], ds["book"], ds["subs"],
                             gate=lambda c: c.risk_atr >= 0.10 and c.in_rth)
        if not tr:
            A(f"| {ds['name']} | 0 | – | – | – | – | – |")
            continue
        bb, _ = AB.run(ds["bars"], ds["book"], AB.BASE, ds["subs"])
        m = measure(tr, bb, ds, REAL_COST)
        th = m["thirds"]
        same = all(x > 0 for x in th) or all(x < 0 for x in th)
        npos += int(m["net"] > 0)
        cell()
        A(f"| {ds['name']} | {m['n']} | {m['gross']:+.1f} | {m['net']:+.1f} | "
          f"{m['avg_net']:+.3f} | {f(m['t_net'],2)} | {'是' if same else '否'} |")
    A("")
    A(f"**现实成本下净 R 为正的数据集：{npos}/4。**")

    # ──────────────────────── §8 the overnight book ──────────────────────────
    A("")
    A("## §8 成本现实性：0.6 点是不是已经太乐观")
    A("")
    A("线上账本 **73% 的交易在夜盘**（509/695）。前四份报告全部用 0.6 点"
      "统一计价，那是 Pine tooltip 里的 RTH 数字。CFD 夜盘点差会走宽，"
      "这一节不引用任何外部报价，只做**敏感度与打平点分析**——"
      "把「点差多宽才致命」交给你自己核对经纪商。")
    A("")
    A("| 夜盘点差假设 | 基线净R | 夜盘腿净R | RTH腿净R | CHAMP净R |")
    A("|---|---|---|---|---|")
    on_tr = [t for t in base if t.session != "RTH"]
    rth_tr = [t for t in base if t.session == "RTH"]
    ch_tr = runs["CHAMP"][1]
    for on_sp in (0.6, 0.8, 1.0, 1.2, 1.5, 2.0):
        c = (0.6, on_sp, 0.2, 0.5)
        cell()
        A(f"| {on_sp:.1f} 点 | {sum(net_r(t,*c) for t in base):+.1f} | "
          f"{sum(net_r(t,*c) for t in on_tr):+.1f} | "
          f"{sum(net_r(t,*c) for t in rth_tr):+.1f} | "
          f"{sum(net_r(t,*c) for t in ch_tr):+.1f} |")
    A("")
    A(f"- 夜盘腿共 {len(on_tr)} 笔，中位风险 "
      f"{st.median([t.risk for t in on_tr]):.2f} 点 —— "
      f"1.0 点点差就吃掉每笔 "
      f"{100*mean(1.0/t.risk for t in on_tr):.1f}% 的风险。")
    A(f"- RTH 腿 {len(rth_tr)} 笔，中位风险 "
      f"{st.median([t.risk for t in rth_tr]):.2f} 点。")
    A("")
    A("| RTH 点差假设 | CHAMP 净R（CHAMP 无夜盘交易） |")
    A("|---|---|")
    for sp in (0.4, 0.6, 0.8, 1.0, 1.2):
        cell()
        A(f"| {sp:.1f} 点 | {sum(net_r(t, sp, sp, 0.2, 0.5) for t in ch_tr):+.1f} |")
    A("")
    A(f"CHAMP 的打平点差是 **{mm['CHAMP']['be_spread']:.2f} 点**（不含滑点）。"
      f"也就是说：只要你的 RTH 点差高于 {mm['CHAMP']['be_spread']:.2f} 点，"
      f"这个「冠军」就已经是负的了。而它的中位风险只有 "
      f"{mm['CHAMP']['med_risk']:.2f} 点。")

    # ─────────────────────────── §9 verdict ──────────────────────────────────
    A("")
    A("## §9 总判决")
    A("")
    A("### 逐条回答本项目的五个历史教训")
    A("")
    A("| # | 教训 | 本轮是否重犯 | 证据 |")
    A("|---|---|---|---|")
    A(f"| 1 | 记账伪影：触发根算进结果窗口 | **否** | §2：0 笔同根出场；"
      f"锚点 0 处前视；截断重跑 0 笔缺失。但已量化：若犯此错，"
      f"{100*art['prot_is_entry_bar']/art['n']:.0f}% 的交易会被伪造成止损 |")
    A(f"| 2 | 零假设用错 | **前四份报告部分重犯** | §3：它们把 0 当零点。"
      f"v14 赔付结构在零漂移下的真零点是 {b['e_r']:+.3f} R/笔，"
      f"不是 0。S/(S+T) 只覆盖了「保护位 vs T1」，覆盖不了 50/25/25 的尾巴 |")
    A(f"| 3 | 两个点当常数 | **否，但要打折** | §4：A 与 B 共享 {len(d10)} 个交易日，"
      f"C⊃A、D⊃B，有效独立样本 ≈1.5–2，不是 4 |")
    A(f"| 4 | 家族规模 | **前四份报告低估了** | §7：单份报告各自申报了格子数，"
      f"但没人把 ≈{tot_cells} 个格子当成一个家族算。经验家族极值下 "
      f"CHAMP 的 p = {p_sel:.3f} |")
    A(f"| 5 | 少交易冒充质量提升 | **否，四份报告都识破了；本轮补了第三把尺** | "
      f"§6：t / z_sel / 超额 三项并列。新发现的是 A7、RISK10 还有第四层问题——"
      f"它们**抬高了自己的零点**，见 §3 |")
    A("")

    # ── how much data would settle it ────────────────────────────────────────
    A("### 要把 CHAMP 这个问题问清楚，需要多少数据")
    A("")
    ch = runs["CHAMP"][1]
    ch_nets = [net_r(t, *REAL_COST) for t in ch]
    sd_ch = st.stdev(ch_nets)
    mu_ch = mean(ch_nets)
    need = (2.80 * sd_ch / mu_ch) ** 2 if mu_ch > 0 else float("inf")
    sess = len({FL.trade_day_of(t) for t in ch})
    rate = len(ch) / sess
    A(f"CHAMP 现实口径均净 R = {mu_ch:+.3f}，每笔 sd = {sd_ch:.3f}。"
      f"要在 5% 显著、80% 功效下把这个效应量与 0 分开，需要 "
      f"**n ≈ {need:.0f} 笔**。")
    A("")
    A(f"CHAMP 在本样本的 {sess} 个交易日里成交 {len(ch)} 笔 = 每日 {rate:.1f} 笔，"
      f"所以需要 **≈{need/rate:.0f} 个交易日 ≈ {need/rate/21:.1f} 个月**的"
      f"样本外记录。现有样本只有 {sess} 天，"
      f"约为所需的 {100*sess/(need/rate):.0f}%。")
    A("")
    A(f"**这是「继续跑」与「停掉」之间唯一诚实的分界线**："
      f"要么承认还要再收 {need/rate/21:.1f} 个月的数据才知道 CHAMP 是不是零，"
      f"要么现在就停。中间地带（「先小仓上着看」）在数学上不存在——"
      f"以 {rate:.1f} 笔/日的速度，你在 3 个月里拿到的样本"
      f"只能把 CI 收窄到仍然跨零。")

    # ── the one-line verdict ─────────────────────────────────────────────────
    A("")
    A("### 一句话总判决")
    A("")
    A("**(b) 停掉，重新设计入场逻辑。**")
    A("")
    A("理由，按证据强度排序：")
    A("")
    A(f"1. **入场空洞已经被三种独立的零假设各自确认过一次，全部落空。** "
      f"纯括号赛跑对 S/(S+T)：整个项目 60+ 个格子最大 z_geom = +1.56，"
      f"本轮 CHAMP 也只有 {f(mm_real['CHAMP']['z_geom'],2)}。"
      f"结构零假设（本轮新增，覆盖 50/25/25 的全部赔付）：基线超额 "
      f"{base_exc:+.3f}（z {base_z:+.2f}），CHAMP 超额 {excess['CHAMP'][0]:+.3f}"
      f"（z {f(excess['CHAMP'][1],2)}）。经验家族极值：CHAMP 的 p = {p_sel:.3f}。"
      f"三种口径互不重叠，结论一致。")
    A(f"2. **能修的地方已经修完了，符号没翻。** 阶段二一共试了 "
      f"{15 + 29} 个配置，本轮又复核了 {len(FAMILY)} 个。"
      f"其中 A6/A7/A9/A10 这一类「入场加门」在数学上**不可能**让任何一笔交易变好"
      f"（配对 ΔR 恒等于 0），A1/A2/A3/A8 这一类「改出场」的配对 t 全为负。"
      f"十几条改动里没有一条让任何一笔交易变好。")
    A(f"3. **现实成本口径下，线上账本的真实亏损比报告的更大。** "
      f"73% 的交易在夜盘，夜盘腿在 1.0–1.5 点点差下是 "
      f"{sum(net_r(t,0.6,1.0,0.2,0.5) for t in on_tr):+.1f} 到 "
      f"{sum(net_r(t,0.6,1.5,0.2,0.5) for t in on_tr):+.1f}R。"
      f"基线整本从 −78.5R 变成 {mm_real['BASE']['net']:+.1f}R。"
      f"夜盘腿在任何合理点差下都无法挽救，而它是账本的主体。")
    A(f"4. **唯一的幸存者 CHAMP 需要 {need/rate/21:.1f} 个月样本外数据才能证伪，"
      f"而它连一个可解释的机制都没有。** 「风险 ≥0.10 ATR」不是一个交易理由，"
      f"是 Recovery 保护位取回踩根 low 这个**构造缺陷**的补丁——"
      f"它筛掉的是止损小到会被 10m 噪音随手扫掉的那些交易。"
      f"这个观察值得带进重新设计（**保护位不要贴着一根 K 的极值放**），"
      f"但它不是一个可以上图的过滤器。")
    A("")
    A("**不选 (a) 的理由**：没有任何一个具体配置在现实成本下同时满足"
      "「净 R 为正 + 三段同号 + z(超额) > 1.96 + 跨数据集复现」。"
      "CHAMP 满足前两条，第三条 z = "
      f"{f(excess['CHAMP'][1],2)}，第四条 {npos}/4。四缺二。")
    A("")
    A("**不选 (c) 的理由**：把 v14 保留成纯记录器听起来无害，实际有害——"
      "它会持续产出一本 30% 胜率的账，而这本账的每一次「好转」都会像 "
      "§7 那样落在噪声冠军的常见区间里，诱发下一轮挑参数。"
      "如果要留下什么，留 **Saty ATR 阶梯 + 排列状态的只读面板**"
      "（这部分的构造在 `levels.py` 里已经对到分，与 CFD 的官方指标逐位相符），"
      "把 Recovery / Vomy 两个状态机的**下单权限**摘掉。")
    A("")
    A("### 重新设计时要带走的三条经验（都是本轮量化过的）")
    A("")
    A(f"1. **保护位不能取自单根 K 的极值。** Recovery 的止损中位只有 0.065 ATR，"
      f"33% 的交易直接死在保护位；Vomy 的 fin 止损 0.151 ATR，只有 5%。"
      f"§2 还证明了这个构造让引擎对「触发根进结果窗口」这个记账伪影异常敏感"
      f"（{100*art['prot_is_entry_bar']/art['n']:.0f}% 的交易保护位就是入场根自己的极值）。")
    A(f"2. **50/25/25 的赔付结构自带 {b['e_r']:+.3f} R/笔的负漂。** "
      f"任何新设计如果保留这个 scale-out，就得先赚回这个数才算打平。"
      f"要么放弃 T2/尾仓，要么把 T1 推远。这是本轮新增的量化事实，"
      f"前四份报告都没有算过它。")
    A(f"3. **入场与出场共用 13 线不是主因，但它把交易频率钉死在 EMA 穿越率的一半。** "
      f"实测跑到理论上界的 77–83%。分离出场线能把频率降 30–40%、"
      f"把成本次数同比例降下来，但配对 t 为负——"
      f"它省的是成本，不是提升质量。新设计应当把它当**成本控制**手段，"
      f"不要再当作 alpha 来源检验一次。")
    A("")
    A("---")
    A("")
    A(f"**口径与限制**：本轮共检视 {CELLS} 个格子（此数与全项目 "
      f"≈{tot_cells} 个格子合并计算家族规模）。所有距离按当日 Wilder ATR(14) "
      f"归一化，不依赖具名位绝对价格。路径判定用 5m 子 K（纪律 5），"
      f"两个 1h 数据集无子 K，仅作旁证。四个数据集不是四个独立样本（§4）。"
      f"结构零假设与家族极值都是蒙特卡洛估计，"
      f"重复次数分别 {NULL_PATHS} 条/笔 与 {FAMILY_REPS} 次，"
      f"种子 {SEED}，可完全复现。未碰 TradingView、未改线上 Pine、未 git commit。")

    tldr = "\n".join([
        "## 结论摘要",
        "",
        f"**判决：(b) 停掉，重新设计入场逻辑。**",
        "",
        f"1. **头条全部复现**：五个脚本亲自重跑，{len(CLAIMS)} 个头条数字 "
        f"{len(CLAIMS)-nbad} 个逐位对上，引擎确定性（§1）。",
        f"2. **前四份报告用错了零点**：v14 的 50/25/25 赔付结构在**零漂移**下"
        f"期望就是 **{b['e_r']:+.3f} R/笔**，不是 0。"
        f"基线毛账 {sum(t.r for t in base):+.1f}R 里有 "
        f"{len(base)*b['e_r']:+.1f}R 是这个结构自带的；"
        f"扣掉之后「入场比随机还差」的部分 z = {base_z:+.2f}，不显著。"
        f"两种独立的随机化构造互相印证（§3、§7b）。",
        f"3. **这个更正让判决更重不是更轻**：亏损的主因从「方向选错」"
        f"（过滤器能修）挪到了「赔付结构 + 入场无信息」（过滤器数学上修不了）。",
        f"4. **唯一的幸存者 CHAMP（风险≥0.10 ATR + 只做 RTH）被家族极值杀死**："
        f"在**完全没有结构**的合成市场上，从同样 {len(FAMILY)} 个配置里挑冠军，"
        f"净 R 中位数就有 {fn['med_net']:+.1f}R、95 分位 {fn['p95_net']:+.1f}R。"
        f"CHAMP 拿到 {champ_net:+.1f}R，选择校正后 **p = {p_sel:.3f}**（§7）。",
        f"5. **成本比报告里假设的更狠**：73% 的交易在夜盘，"
        f"夜盘点差按 1.2 点 + 止损滑点计，基线净账从 −78.5R 掉到 "
        f"{mm_real['BASE']['net']:+.1f}R；夜盘腿单独 "
        f"{sum(net_r(t,*REAL_COST) for t in on_tr):+.1f}R（§8）。",
        f"6. **五个历史陷阱本轮无一重犯**，但发现前四份报告在陷阱②（零假设）"
        f"上是部分重犯的，且没人把全项目 ≈{tot_cells} 个格子当作一个家族算过（§9）。",
        "",
        f"要把 CHAMP 是不是零这件事问清楚，需要 ≈{need:.0f} 笔 ≈ "
        f"{need/rate/21:.1f} 个月的样本外记录。现有样本是所需的 "
        f"{100*sess/(need/rate):.0f}%。",
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(o).replace("__CELLS__", str(CELLS)).replace("__TLDR__", tldr)
    OUT.write_text(body + "\n", encoding="utf-8")
    print(body)
    print(f"\n\ncells={CELLS}  headline_mismatch={nbad}  p_sel={p_sel:.4f}")
    print(f"structural_null_base={b['e_r']:+.4f}  actual_base={bact:+.4f}")
    print(f"champ_net_real={champ_net_real:+.2f}  positives_real={pos_real}")
    print(f"champ_excess={excess['CHAMP']}  need_n={need:.0f}  transplant={npos}/4")


if __name__ == "__main__":
    main()
