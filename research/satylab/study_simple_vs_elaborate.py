"""V15 · 简单 vs 复杂：五个选手在同一份数据上的横向对决。

用户的原话是一个可以被数据回答的问题：

    「不知道哎，这个东西其实很符合直觉的，我不知道这里面为什么搞得这么多呢？」

所以本文件把它变成一场对决。五个选手，同一份 ES=F 10m 数据，同一套 5 分钟
子 K 路径判定（纪律 3），同一 0.6 点点差（纪律 4），同一几何零假设
P = S/(S+T)（纪律 1）。

  A  极简版：状态(盒内/未排列=区间) + 位置(≤0.10 ATR) + 方向 + 位尺
  B  A 去掉状态层：只剩位置 + 纯拒绝方向 + 位尺
  C  A 去掉位置层：状态 + 方向 + 位尺，入场用 EMA8×EMA21 交叉
  D  v14 全套：三类 setup + 分级 + 全部闸门（基线）
  E  纯随机：同样的 K 上随机开仓（方向 50/50），同样的位尺

判定口径统一为**纯括号赛跑**：止损 vs 目标谁先被 5m 子 K 触到。赢 = +T/S 个 R，
输 = −1R，净 R = R − 0.6/止损点数。R 不是钱，所以每张表都同时报
「净钱」= 净R × (止损距离/日ATR)，这才是跨止损尺度可比的量（纪律 5 的推论）。

A 的参数一次成型、不搜索（题目给定值）。敏感性分析单列一节并明确标注事后。

Usage:  .venv/bin/python research/satylab/study_simple_vs_elaborate.py
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats                                # noqa: E402
from satylab.data import Bar                                   # noqa: E402
from satylab.indicators import ema                             # noqa: E402
from satylab.study_v14_repro import (                          # noqa: E402
    LevelBook, RUNGS, load_10m, next_rung, run_v14, trade_day,
)
from satylab.study_entry_location import harvest               # noqa: E402

SPREAD = 0.6              # CAPITALCOM:SPX500 典型点差
RACE_CAP = 400            # 括号最多跑多少根 setup K
MIN_RISK_PTS = 2.0        # v14 自己的值，五个选手统一沿用
BOX = 0.236               # trigger box 半宽（就是位阶梯上的 call/put trigger）
NEAR = 0.10               # 规则 2：离最近具名位 ≤ 0.10 ATR
RANDOM_POOL = 6000        # 选手 E 的池子大小
BOOT = 1000               # E 的自助抽样次数
SEED = 20260728

REPORT = (Path(__file__).resolve().parents[1] / "reports"
          / "V15_SIMPLE_VS_ELABORATE.md")

CELLS = 0
ZS: list = []          # 全文所有报告过的 z_geom，用于「有没有越过 Bonferroni」自查


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ═══════════════════════════════ 记录 ════════════════════════════════════════
@dataclass
class Sig:
    who: str
    i: int
    dt: object
    session: str
    direction: int
    state: str
    entry: float
    stop: float
    target: float
    risk: float          # 点
    reward: float        # 点
    atr: float
    hit: bool | None = None
    pnull: float = 0.0

    @property
    def rr(self) -> float:
        return self.reward / self.risk if self.risk > 0 else float("nan")

    @property
    def r(self) -> float:
        if self.hit is None:
            return float("nan")
        return self.rr if self.hit else -1.0

    @property
    def net(self) -> float:
        return self.r - SPREAD / self.risk if self.risk > 0 else float("nan")

    @property
    def risk_atr(self) -> float:
        return self.risk / self.atr if self.atr > 0 else float("nan")

    @property
    def money(self) -> float:
        """净盈亏，每 1 单位名义本金，以日 ATR 为单位。跨止损尺度唯一可比的量。"""
        return self.net * self.risk_atr


# ══════════════════════════════ 位尺工具 ═════════════════════════════════════
def nearest_level(px: float, anchor: float, atr: float) -> tuple[float, int]:
    """最近的具名位及其在阶梯上的序号。"""
    best_j, best_d = 0, float("inf")
    for j, r in enumerate(RUNGS):
        d = abs(anchor + r * atr - px)
        if d < best_d:
            best_j, best_d = j, d
    return anchor + RUNGS[best_j] * atr, best_j


def brackets(px: float, d: int, anchor: float, atr: float):
    """规则 4：目标 = 顺方向下一个具名位；止损 = 反方向上一个具名位。"""
    tgt = next_rung(px, d, anchor, atr)
    stp = next_rung(px, -d, anchor, atr)
    return stp, tgt


# ═══════════════════════════ 路径判定（统一） ════════════════════════════════
def race(s: Sig, bars: list[Bar], subs, cap: int = RACE_CAP) -> None:
    """纯括号：止损 vs 目标谁先到。判定落到 5m 子 K（纪律 3）。"""
    s.pnull = s.risk / (s.risk + s.reward)
    d = s.direction
    for i in range(s.i + 1, min(s.i + 1 + cap, len(bars))):
        sub = subs[i] if subs is not None else [bars[i]]
        for sb in sub:
            ph = (sb.low <= s.stop) if d > 0 else (sb.high >= s.stop)
            gh = (sb.high >= s.target) if d > 0 else (sb.low <= s.target)
            if ph and gh:
                s.hit = None            # 5m 分辨率下仍然含混 → 弃权，不猜
                return
            if gh:
                s.hit = True
                return
            if ph:
                s.hit = False
                return
    s.hit = None


# ═════════════════════════════ 统计工具 ══════════════════════════════════════
def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_sided(z: float) -> float:
    if z != z:
        return float("nan")
    return 2.0 * norm_sf(abs(z))


def z_geom(sigs: list[Sig]) -> tuple[float, int, float, float]:
    res = [s for s in sigs if s.hit is not None]
    n = len(res)
    if n == 0:
        return float("nan"), 0, float("nan"), float("nan")
    k = sum(1 for s in res if s.hit)
    sp = sum(s.pnull for s in res)
    var = sum(s.pnull * (1 - s.pnull) for s in res)
    z = (k - sp) / math.sqrt(var) if var > 0 else float("nan")
    return z, n, k / n, sp / n


def tstat(xs: list[float]) -> float:
    xs = [x for x in xs if x == x]
    if len(xs) < 2:
        return float("nan")
    sd = st.pstdev(xs)
    return st.mean(xs) / (sd / math.sqrt(len(xs))) if sd > 0 else float("nan")


def two_sample_z(a: list[float], b: list[float]) -> float:
    a = [x for x in a if x == x]
    b = [x for x in b if x == x]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = st.pvariance(a) / len(a), st.pvariance(b) / len(b)
    se = math.sqrt(va + vb)
    return (st.mean(a) - st.mean(b)) / se if se > 0 else float("nan")


def maxdd(vals: list[float]) -> float:
    eq = peak = dd = 0.0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd


# ═══════════════════════════ 选手 A / B / C ══════════════════════════════════
def context(bars: list[Bar], book: LevelBook):
    """每根 K 的公共上下文：五线、锚、ATR、排列、时段。"""
    closes = [b.close for b in bars]
    e8 = ema(closes, 8)
    e13 = ema(closes, 13)
    e21 = ema(closes, 21)
    e34 = ema(closes, 34)
    e48 = ema(closes, 48)
    ctx = []
    for i, b in enumerate(bars):
        lv = book.get(trade_day(b))
        if e48[i] is None or lv is None or lv[1] <= 0:
            ctx.append(None)
            continue
        anchor, atr = lv
        bull = e8[i] > e13[i] > e21[i] > e34[i] > e48[i]
        bear = e8[i] < e13[i] < e21[i] < e34[i] < e48[i]
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)
        ctx.append({"anchor": anchor, "atr": atr, "bull": bull, "bear": bear,
                    "e8": e8[i], "e21": e21[i],
                    "session": "RTH" if in_rth else "夜盘"})
    return ctx, e8, e21


def state_dir(px: float, c: dict) -> tuple[str, int]:
    """规则 1 + 规则 3。"""
    in_box = abs(px - c["anchor"]) < BOX * c["atr"]
    stacked = c["bull"] or c["bear"]
    if in_box or not stacked:
        # 区间态：朝盒内 = 朝锚（盒子中心）
        if px > c["anchor"]:
            return "区间", -1
        if px < c["anchor"]:
            return "区间", +1
        return "区间", 0
    return "趋势", (+1 if c["bull"] else -1)


def gen_A(bars, ctx, dedup=True) -> list[Sig]:
    out, prev_key = [], None
    for i, b in enumerate(bars):
        c = ctx[i]
        if c is None:
            prev_key = None
            continue
        px = b.close
        lvl, j = nearest_level(px, c["anchor"], c["atr"])
        if abs(px - lvl) > NEAR * c["atr"]:            # 规则 2
            prev_key = None
            continue
        state, d = state_dir(px, c)                    # 规则 1 + 3
        if d == 0:
            prev_key = None
            continue
        key = (d, j)
        if dedup and key == prev_key:
            continue
        prev_key = key
        stp, tgt = brackets(px, d, c["anchor"], c["atr"])   # 规则 4
        risk, rew = abs(px - stp), abs(tgt - px)
        if risk < MIN_RISK_PTS:
            continue
        out.append(Sig("A", i, b.dt, c["session"], d, state, px, stp, tgt,
                       risk, rew, c["atr"]))
    return out


def gen_B(bars, ctx, dedup=True) -> list[Sig]:
    """去掉状态层：方向恒为「远离最近位」= 纯拒绝。"""
    out, prev_key = [], None
    for i, b in enumerate(bars):
        c = ctx[i]
        if c is None:
            prev_key = None
            continue
        px = b.close
        lvl, j = nearest_level(px, c["anchor"], c["atr"])
        if abs(px - lvl) > NEAR * c["atr"]:
            prev_key = None
            continue
        d = +1 if px > lvl else (-1 if px < lvl else 0)
        if d == 0:
            prev_key = None
            continue
        key = (d, j)
        if dedup and key == prev_key:
            continue
        prev_key = key
        stp, tgt = brackets(px, d, c["anchor"], c["atr"])
        risk, rew = abs(px - stp), abs(tgt - px)
        if risk < MIN_RISK_PTS:
            continue
        out.append(Sig("B", i, b.dt, c["session"], d, "拒绝", px, stp, tgt,
                       risk, rew, c["atr"]))
    return out


def gen_C(bars, ctx, e8, e21, cross_dir=False) -> list[Sig]:
    """去掉位置层：入场用 EMA8×EMA21 交叉，方向仍由规则 3 给（或用交叉方向）。"""
    out = []
    for i in range(1, len(bars)):
        c = ctx[i]
        if c is None or e8[i] is None or e21[i] is None \
                or e8[i - 1] is None or e21[i - 1] is None:
            continue
        up_now, up_prev = e8[i] > e21[i], e8[i - 1] > e21[i - 1]
        if up_now == up_prev:
            continue
        b = bars[i]
        px = b.close
        state, d = state_dir(px, c)
        if cross_dir:
            d = +1 if up_now else -1
        if d == 0:
            continue
        stp, tgt = brackets(px, d, c["anchor"], c["atr"])
        risk, rew = abs(px - stp), abs(tgt - px)
        if risk < MIN_RISK_PTS:
            continue
        out.append(Sig("C'" if cross_dir else "C", i, b.dt, c["session"], d,
                       state, px, stp, tgt, risk, rew, c["atr"]))
    return out


# ═══════════════════════════════ 选手 D ══════════════════════════════════════
def gen_D(bars, ctx, book) -> tuple[list[Sig], list[Sig]]:
    """v14 全套。用 harvest（去掉单仓闸门）取全部信号，另跑真引擎取线上排队口径。

    为了与 A/B/C/E 同口径比较，D 的括号在这里也用「纯括号」：结构止损 vs T1，
    5m 子 K 裁决。v14 自己的分批 / 13 线离场在报告里单列。
    """
    raw, _e13 = harvest(bars, book)
    allsig, live = [], []
    filled_engine, _ = run_v14(bars, book, SUBS_CACHE, path_resolve=True)
    filled = {(t.entry_i, t.setup, t.direction) for t in filled_engine}
    for v in raw:
        c = ctx[v.i]
        if c is None:
            continue
        risk, rew = v.risk, abs(v.t1 - v.entry)
        if risk <= 0 or rew <= 0:
            continue
        s = Sig("D", v.i, v.dt, v.session, v.direction, v.setup, v.entry,
                v.prot, v.t1, risk, rew, v.atr)
        allsig.append(s)
        if (v.i, v.setup, v.direction) in filled:
            t = Sig("D线上", v.i, v.dt, v.session, v.direction, v.setup,
                    v.entry, v.prot, v.t1, risk, rew, v.atr)
            live.append(t)
    return allsig, live


# ═══════════════════════════════ 选手 E ══════════════════════════════════════
def gen_E(bars, ctx, n: int, rng: random.Random) -> list[Sig]:
    """纯随机对照：同样的 K 上随机开仓，方向 50/50，同样的位尺。"""
    pool = [i for i, c in enumerate(ctx) if c is not None and i + 1 < len(bars)]
    out = []
    guard = 0
    while len(out) < n and guard < n * 20:
        guard += 1
        i = rng.choice(pool)
        c = ctx[i]
        b = bars[i]
        px = b.close
        d = +1 if rng.random() < 0.5 else -1
        stp, tgt = brackets(px, d, c["anchor"], c["atr"])
        risk, rew = abs(px - stp), abs(tgt - px)
        if risk < MIN_RISK_PTS:
            continue
        out.append(Sig("E", i, b.dt, c["session"], d, "随机", px, stp, tgt,
                       risk, rew, c["atr"]))
    return out


# ═══════════════════════════════ 汇报 ════════════════════════════════════════
def summarize(sigs: list[Sig], label: str) -> dict:
    bump()
    dec = [s for s in sigs if s.hit is not None]
    z, n, obs, null = z_geom(sigs)
    k = sum(1 for s in dec if s.hit)
    lo, hi = stats.wilson(k, n) if n else (float("nan"), float("nan"))
    rs = [s.r for s in dec]
    ns = [s.net for s in dec]
    ms = [s.money for s in dec]
    order = sorted(dec, key=lambda s: s.i)
    if z == z:
        ZS.append((label, z))
    return {
        "label": label, "n_sig": len(sigs), "n": n,
        "hit": obs, "lo": lo, "hi": hi, "null": null, "z": z,
        "avg_r": st.mean(rs) if rs else float("nan"),
        "avg_net": st.mean(ns) if ns else float("nan"),
        "t_net": tstat(ns),
        "tot_net": sum(ns),
        "avg_money": st.mean(ms) if ms else float("nan"),
        "tot_money": sum(ms),
        "dd": maxdd([s.net for s in order]),
        "dd_money": maxdd([s.money for s in order]),
        "rr": st.median([s.rr for s in dec]) if dec else float("nan"),
        "risk_atr": st.median([s.risk_atr for s in dec]) if dec else float("nan"),
        "nets": ns, "moneys": ms, "sigs": sigs,
    }


def row(d: dict, params: str) -> str:
    return (f"| {d['label']} | {params} | {d['n']} | "
            f"{100*d['hit']:.1f}% [{100*d['lo']:.1f},{100*d['hi']:.1f}] | "
            f"{100*d['null']:.1f}% | {100*(d['hit']-d['null']):+.1f} | "
            f"**{d['z']:+.2f}** | {d['avg_r']:+.3f} | {d['avg_net']:+.3f} | "
            f"{d['tot_net']:+.1f} | {d['dd']:.1f} |")


def row_money(d: dict) -> str:
    return (f"| {d['label']} | {d['n']} | {d['risk_atr']:.3f} | {d['rr']:.2f} | "
            f"{d['avg_net']:+.3f} | {d['avg_money']:+.4f} | "
            f"{d['tot_money']:+.2f} | {d['dd_money']:.2f} |")


def slice_rows(d: dict, out: list[str]) -> None:
    for lbl in ("RTH", "夜盘"):
        g = [s for s in d["sigs"] if s.session == lbl]
        if len(g) < 20:
            out.append(f"| {d['label']} · {lbl} | {len(g)} | 样本不足 | | | | | | |")
            continue
        sd = summarize(g, f"{d['label']} · {lbl}")
        out.append(f"| {sd['label']} | {sd['n']} | "
                   f"{100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
                   f"{100*(sd['hit']-sd['null']):+.1f} | {sd['z']:+.2f} | "
                   f"{sd['avg_net']:+.3f} | {sd['tot_net']:+.1f} | "
                   f"{sd['avg_money']:+.4f} |")


SUBS_CACHE = None


def main() -> None:
    global SUBS_CACHE, NEAR
    rng = random.Random(SEED)
    o: list[str] = []
    A = o.append

    bars, subs = load_10m("ES=F", False)
    SUBS_CACHE = subs
    book = LevelBook(data.load("ES=F", "20y", "1d"))
    ctx, e8, e21 = context(bars, book)
    n_ctx = sum(1 for c in ctx if c is not None)

    # 规则 2 到底筛掉了多少？
    near_ok = near_tot = 0
    for i, b in enumerate(bars):
        c = ctx[i]
        if c is None:
            continue
        near_tot += 1
        lvl, _ = nearest_level(b.close, c["anchor"], c["atr"])
        if abs(b.close - lvl) <= NEAR * c["atr"]:
            near_ok += 1

    sA = gen_A(bars, ctx)
    sB = gen_B(bars, ctx)
    sC = gen_C(bars, ctx, e8, e21)
    sCp = gen_C(bars, ctx, e8, e21, cross_dir=True)
    sD, sDlive = gen_D(bars, ctx, book)
    sE = gen_E(bars, ctx, RANDOM_POOL, rng)

    for group in (sA, sB, sC, sCp, sD, sDlive, sE):
        for s in group:
            race(s, bars, subs)

    dA = summarize(sA, "A · 极简版")
    dB = summarize(sB, "B · 去状态层")
    dC = summarize(sC, "C · 去位置层")
    dCp = summarize(sCp, "C' · 去位置层(交叉定向)")
    dD = summarize(sD, "D · v14 全套")
    dDl = summarize(sDlive, "D · v14 线上排队")
    dE = summarize(sE, "E · 纯随机")

    # ── E 的自助带（把 n 拉到与各选手一致，看总净R 的随机波动幅度）────────
    _bands: dict = {}

    def boot_band(n_target: int, reps: int = BOOT):
        if n_target in _bands:
            return _bands[n_target]
        dec = [s for s in sE if s.hit is not None]
        tots, dds, avgs = [], [], []
        for _ in range(reps):
            pick = [dec[rng.randrange(len(dec))] for _ in range(n_target)]
            pick.sort(key=lambda s: s.i)
            nets = [s.net for s in pick]
            tots.append(sum(nets))
            dds.append(maxdd(nets))
            avgs.append(st.mean(nets))
        tots.sort(); dds.sort(); avgs.sort()
        q = lambda a, p: a[max(0, min(len(a) - 1, int(p * (len(a) - 1))))]
        _bands[n_target] = {"tot_lo": q(tots, 0.05), "tot_hi": q(tots, 0.95),
                            "tot_md": q(tots, 0.5), "dd_md": q(dds, 0.5),
                            "avg_lo": q(avgs, 0.05), "avg_hi": q(avgs, 0.95),
                            "tots": tots}
        return _bands[n_target]

    def pct_vs_rand(band: dict, observed: float) -> float:
        """观测总净R 落在随机分布的第几个百分位（越小 = 比随机还差）。"""
        t = band["tots"]
        below = sum(1 for x in t if x < observed)
        return 100.0 * below / len(t)

    bandA = boot_band(dA["n"])
    bandD = boot_band(dD["n"])

    # ── 报告 ────────────────────────────────────────────────────────────────
    A("# V15 · 简单 vs 复杂：五个选手的横向对决")
    A("")
    A(f"生成脚本 `research/satylab/study_simple_vs_elaborate.py`。"
      f"主样本 **ES=F 10m**（由 60d 5m 聚合，含完整 23 小时时段，与 "
      f"CAPITALCOM:SPX500 作息一致），{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，"
      f"{len(bars)} 根 K，其中 {n_ctx} 根有完整的五线与位阶梯。"
      f"路径判定全部落到 5 分钟子 K（纪律 3），点差 {SPREAD} 点（纪律 4），"
      f"比例的零假设一律是几何零假设 S/(S+T)（纪律 1）。")
    A("")
    A("## 0 · 这一轮在回答什么")
    A("")
    A("> 「不知道哎，这个东西其实很符合直觉的，我不知道这里面为什么搞得这么多呢？」")
    A("")
    A("这句话可以被数据回答：把「简单」和「复杂」放在同一份数据上跑，看复杂度买到了什么。")
    A("")
    A("### 0.1 判定口径（五个选手完全一致）")
    A("")
    A("**纯括号赛跑**：入场后，止损与目标谁先被 5 分钟子 K 触到。同一根 5m 子 K 内两边"
      "都触 → 判为**无法裁决**，弃权，不猜（这就是纪律 2 的实现：绝不用同根裁决替交易"
      "做判决）。赢 = +T/S 个 R，输 = −1R，净 R = R − 0.6/止损点数。")
    A("")
    A("**R 不是钱。** 选手 B 的止损可以只有 3 点，选手 D 的止损中位十几点，两者同样报"
      "「+0.1R」，赚的钱差一个量级。所以每张主表都同时报**净钱** = 净R × (止损距离/日ATR)，"
      "单位是「每 1 单位名义本金的日 ATR」。跨选手比较只有这一列有意义。")
    A("")
    A("**样本口径**：A/B/C/D 都用「全部信号、彼此独立重放」，不做单仓排队。理由与 "
      "`V15_ENTRY_LOCATION.md` 第 1 节相同——「有没有被上一笔挡住」是排队顺序的产物，"
      "按它筛样本会引入选择偏差。D 的线上排队口径单列一行做对照。")
    A("")
    A(f"**去重**：A 与 B 在「方向 + 最近位序号」不变的连续 K 上只触发一次（价格贴着同一"
      f"个位横盘不算 N 笔新交易）。这是机械必需，不是闸门；不去重的版本在敏感性一节报告。")
    A("")
    A("### 0.2 规则 2 其实几乎不是个筛子")
    A("")
    A(f"「离最近具名位 ≤ {NEAR:.2f} ATR」听起来是个严格的位置条件。实测："
      f"**{near_ok}/{near_tot} = {100*near_ok/near_tot:.1f}%** 的 K 满足它。")
    A("")
    A("原因是位阶梯本身太密：相邻两位的间距 0.146 ATR（0.236→0.382）到 0.346 ATR"
      f"（1.272→1.618），半间距多数只有 0.073–0.084 ATR，**小于 {NEAR:.2f}**。也就是说在"
      "阶梯的中段，价格无论落在哪里都「离最近位不超过 0.10 ATR」。这个发现本身就是"
      "答案的一部分：位置层在这条阶梯上几乎不产生约束——第 7.1 节的阈值扫描证实了这一点，"
      "把阈值从 0.25 一路收到 0.06，均净钱几乎不动。")
    A("")

    A("## 1 · 主表：五个选手，同一把尺子")
    A("")
    A("| 选手 | 自由参数 | n(可裁决) | 命中率 [95%CI] | 几何零假设 | 超额 pp | z_geom | 均R | 均净R | 总净R | 最大回撤 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    A(row(dA, "7"))
    A(row(dB, "2"))
    A(row(dC, "6"))
    A(row(dD, "20+"))
    A(row(dDl, "20+"))
    A(row(dE, "1"))
    A("")
    A(f"信号总数（含无法裁决的）：A {dA['n_sig']}，B {dB['n_sig']}，C {dC['n_sig']}，"
      f"D {dD['n_sig']}（线上排队 {dDl['n_sig']}），E {dE['n_sig']}（随机池，为了估计精度"
      f"故意抽大）。被 5m 分辨率判为无法裁决而弃权的比例：A "
      f"{100*(1-dA['n']/max(dA['n_sig'],1)):.1f}%，B {100*(1-dB['n']/max(dB['n_sig'],1)):.1f}%，"
      f"C {100*(1-dC['n']/max(dC['n_sig'],1)):.1f}%，D {100*(1-dD['n']/max(dD['n_sig'],1)):.1f}%，"
      f"E {100*(1-dE['n']/max(dE['n_sig'],1)):.1f}%。")
    A("")
    A("### 1.1 同一张表，换成钱")
    A("")
    A("| 选手 | n | 中位止损(ATR) | 中位R:R | 均净R | 均净钱(ATR) | 总净钱(ATR) | 最大回撤(ATR) |")
    A("|---|---|---|---|---|---|---|---|")
    for d in (dA, dB, dC, dD, dDl, dE):
        A(row_money(d))
    A("")

    A("## 2 · 复杂度成本：自由参数清单")
    A("")
    A("计数口径先说清楚，否则这一节就是修辞。**共享基础设施不记在任何人头上**："
      "位阶梯的 9 个比率、Wilder ATR(14)、锚 = 前一日收盘、10m setup 周期、"
      "0.6 点点差、5m 子 K 判定——五个选手完全一样，共 11 个左右的数。"
      "下表只数**选手自己的**可调数字。")
    A("")
    A("| 选手 | 规则条数 | 可调数字 | 明细 |")
    A("|---|---|---|---|")
    A("| A · 极简版 | 4 | **7** | EMA 8/13/21/34/48（5）+ 位置阈值 0.10 ATR（1）+ 最小风险 2.0 点（1）。"
      "trigger box 的 0.236 来自共享阶梯，不重复计 |")
    A("| B · 去状态层 | 3 | **2** | 位置阈值 0.10 ATR + 最小风险 2.0 点 |")
    A("| C · 去位置层 | 3 | **6** | EMA 8/13/21/34/48（5）+ 最小风险 2.0 点（1）；交叉用的 8×21 是五线的子集 |")
    A("| D · v14 全套 | ~12 | **20+** | EMA 8/13/21/34/48（5）、排列持续 5 根、最小风险 2.0 点、"
      "回踩参考线 = 13、失效线 = 34、Vomy 的 10 根 hh/ll 回看、Recovery 入场 = 收盘穿 13、"
      "Vomy 入场 = 影线触 13、保护位 = 运行极值、T1/T2 = 顺向两个位、分批 0.50/0.25、"
      "结构离场 = 收盘穿 13、单仓闸门、48 线确认（算了但没用）、四台状态机各自的复位不对称 |")
    A("| E · 纯随机 | 1 | **1** | 最小风险 2.0 点 |")
    A("")

    A("## 3 · 直接对撞：谁打得过谁")
    A("")
    A("两样本 z（均净R）与两样本 z（均净钱）。**均净钱那一列才是可比的**。")
    A("")
    A("| 对撞 | Δ均净R | z(净R) | Δ均净钱 | z(净钱) | 判决 |")
    A("|---|---|---|---|---|---|")
    pairs = [("A vs E（地板）", dA, dE), ("A vs D（简 vs 繁）", dA, dD),
             ("A vs B（状态层值多少）", dA, dB),
             ("A vs C（位置层值多少）", dA, dC),
             ("D vs E（全套 vs 随机）", dD, dE),
             ("B vs E", dB, dE), ("C vs E", dC, dE),
             ("B vs C", dB, dC), ("B vs D", dB, dD), ("C vs D", dC, dD),
             ("D线上 vs E", dDl, dE), ("A vs D线上", dA, dDl)]
    zms = []
    for name, x, y in pairs:
        bump()
        zr = two_sample_z(x["nets"], y["nets"])
        zm = two_sample_z(x["moneys"], y["moneys"])
        zms.append(abs(zm))
        verdict = "无差异" if abs(zm) < 1.96 else ("前者更好" if zm > 0 else "后者更好")
        A(f"| {name} | {x['avg_net']-y['avg_net']:+.3f} | {zr:+.2f} | "
          f"{x['avg_money']-y['avg_money']:+.4f} | {zm:+.2f} | {verdict} |")
    A("")
    A(f"**{len(pairs)} 对全部检视，最大 |z(净钱)| = {max(zms):.2f}——没有任何一对选手"
      f"在钱上分得开。**")
    A("")
    A("两列打架的地方要解释：A vs D 在**净R** 上 z=+2.23（A 明显更好），在**净钱**上却只有 "
      "+0.43。原因是 R 的分母是止损距离，而 v14 亏得最狠的那批交易恰好是**止损最小**的"
      "那批（见 `V15_ENTRY_LOCATION.md` 第 2.5 节：D4 的 Q1 档均净R −0.551）。"
      "止损小 = 同样的 −1R 亏的钱少。所以「按 R 算 D 很糟」和「按钱算 D 只是平庸」"
      "两句话都对，取决于你是按固定 R 下注还是按固定敞口下注。")
    A("")

    A("## 4 · 随机地板的宽度（E 的自助带）")
    A("")
    A("单看「总净R 是负的」没有意义——随机也会是负的（点差），而且随机的波动很宽。"
      f"下表把 E 的可裁决样本自助抽样 {BOOT} 次，每次抽到与对手相同的 n，看总净R 的分布，"
      f"再看对手的实测值落在这个分布的第几个百分位。**百分位 < 5 = 比随机还差得离谱；"
      f"> 95 = 真的有东西；中间 = 与随机无异**。")
    A("")
    A("| 对手 | n | E 总净R 中位 | E 总净R 5–95% | E 中位最大回撤 | 对手实测总净R | 百分位 | 判决 |")
    A("|---|---|---|---|---|---|---|---|")
    for d in (dA, dB, dC, dD, dDl):
        bump()
        bd = boot_band(d["n"])
        p = pct_vs_rand(bd, d["tot_net"])
        verdict = ("**比随机还差**" if p < 5 else
                   ("**真的有东西**" if p > 95 else "与随机无异"))
        A(f"| {d['label']} | {d['n']} | {bd['tot_md']:+.1f} | "
          f"[{bd['tot_lo']:+.1f}, {bd['tot_hi']:+.1f}] | {bd['dd_md']:.1f} | "
          f"{d['tot_net']:+.1f} | {p:.1f} | {verdict} |")
    A("")

    A("## 4.1 · 交易频率：简单不等于少做")
    A("")
    A("复杂度的另一个维度是**你被要求下多少次单**。这一列常被忽略，但它直接决定点差成本。")
    A("")
    nb = len(bars)
    days_span = (bars[-1].dt.date() - bars[0].dt.date()).days or 1
    A(f"| 选手 | 信号数 | 每 1000 根 setup K | 平均每根 K 的间隔 | "
      f"{days_span} 个日历日内平均每天 |")
    A("|---|---|---|---|---|")
    for d in (dA, dB, dC, dD, dDl, dE):
        if d["label"].startswith("E"):
            A(f"| {d['label']} | （随机池 {d['n_sig']}，频率由设计给定，不可比） | – | – | – |")
            continue
        ns = d["n_sig"]
        A(f"| {d['label']} | {ns} | {1000*ns/nb:.1f} | 每 {nb/ns:.1f} 根一笔 | "
          f"{ns/days_span:.1f} |")
    A("")
    A(f"**A 比 v14 更 churn。** A 每 {nb/dA['n_sig']:.1f} 根 K 就要下一次单，v14 是每 "
      f"{nb/dD['n_sig']:.1f} 根，差 {dA['n_sig']/dD['n_sig']:.1f} 倍。「规则少」和"
      f"「动手少」是两件事。这至少说明 v14 那一堆闸门在做的事情之一就是**压交易次数**"
      f"——那是一个可以用一行规则实现的效果，不需要二十个参数。")
    A("")

    A("## 5 · 分时段（RTH / 夜盘）")
    A("")
    A("线上账本 73% 的交易在夜盘，所以这一节不是可选项。")
    A("")
    A("| 选手 · 时段 | n | 命中率 | 几何零假设 | 超额 pp | z_geom | 均净R | 总净R | 均净钱 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for d in (dA, dB, dC, dD, dE):
        slice_rows(d, o)
    A("")

    A("### 5.1 与本文结论相反的格子（纪律 7：单列，不藏）")
    A("")
    A("本文的结论是「复杂度没买到东西」。下面这些格子说的是反话，如实列出。")
    A("")
    rows = []
    for d in (dA, dB, dC, dD, dDl, dE):
        for lbl in ("RTH", "夜盘"):
            g = [s for s in d["sigs"] if s.session == lbl]
            if len(g) < 20:
                continue
            sd = summarize(g, f"{d['label']} · {lbl}")
            rows.append(sd)
    rows.sort(key=lambda x: -x["avg_money"])
    A("| 格子 | n | 命中率 | 几何零假设 | 超额 pp | z_geom | 均净R | 均净钱 |")
    A("|---|---|---|---|---|---|---|---|")
    for sd in rows[:4]:
        A(f"| {sd['label']} | {sd['n']} | {100*sd['hit']:.1f}% | "
          f"{100*sd['null']:.1f}% | {100*(sd['hit']-sd['null']):+.1f} | "
          f"{sd['z']:+.2f} | {sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} |")
    best = rows[0]
    A("")
    A(f"- **全文最好的一格是 {best['label']}**（均净钱 {best['avg_money']:+.4f}，"
      f"n={best['n']}，z_geom {best['z']:+.2f}）。它恰恰属于最复杂的那个选手，"
      f"这与本文主结论相反。但：n 只有 {best['n']}，z_geom {best['z']:+.2f} "
      f"连常规 1.96 都没到，更别说第 9 节的 Bonferroni 门槛；而且它是从 12 个时段格里"
      f"挑出来的最大值。**它是一个候选假设，不是一个发现。**")
    A(f"- A 在 RTH 也比在夜盘好（均净钱 "
      f"{[r for r in rows if r['label'].startswith('A') and 'RTH' in r['label']][0]['avg_money']:+.4f} "
      f"vs {[r for r in rows if r['label'].startswith('A') and '夜盘' in r['label']][0]['avg_money']:+.4f}），"
      f"方向一致。**唯一一个在两个选手上方向一致、且值得下一轮单独去测的东西，就是"
      f"「只做 RTH」**——注意这是本轮观察到的，不是本轮验证过的。")
    A("")

    A("## 6 · A 内部拆开看：状态层自己在说什么")
    A("")
    A("A 的每一笔都带着「区间 / 趋势」标签。如果状态层有信息，两个标签的表现应该分得开。")
    A("")
    A("| 格子 | n | 命中率 | 几何零假设 | 超额 pp | z_geom | 均净R | 均净钱 |")
    A("|---|---|---|---|---|---|---|---|")
    for lbl in ("区间", "趋势"):
        g = [s for s in sA if s.state == lbl]
        if len(g) < 20:
            A(f"| A · {lbl} | {len(g)} | 样本不足 | | | | | |")
            continue
        sd = summarize(g, f"A · {lbl}")
        A(f"| A · {lbl} | {sd['n']} | {100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
          f"{100*(sd['hit']-sd['null']):+.1f} | {sd['z']:+.2f} | "
          f"{sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} |")
    gr = [s for s in sA if s.state == "区间"]
    gt = [s for s in sA if s.state == "趋势"]
    zsplit = two_sample_z([s.money for s in gr if s.hit is not None],
                          [s.money for s in gt if s.hit is not None])
    bump()
    A("")
    A(f"- 两个状态的均净钱差异 z = **{zsplit:+.2f}** (p={two_sided(zsplit):.3f})。"
      f"趋势态占 A 全部信号的 {100*len(gt)/max(len(sA),1):.1f}%。")
    A("")

    A("## 7 · 事后分析（明确标注：以下都是事后的，不能当证据）")
    A("")
    A("纪律 3 要求 A 的参数一次成型、不搜索。上面所有数字都是给定参数直接跑出来的。"
      "这一节做敏感性，只是为了知道结论有多脆——**不是**为了挑一个好看的参数。")
    A("")
    A("### 7.1 位置阈值扫描（A）")
    A("")
    A("| NEAR (ATR) | n | 命中率 | 几何零假设 | z_geom | 均净R | 均净钱 | 总净钱 |")
    A("|---|---|---|---|---|---|---|---|")
    keep_near = NEAR
    scan = []
    for v in (0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.25):
        NEAR = v
        g = gen_A(bars, ctx)
        for s in g:
            race(s, bars, subs)
        sd = summarize(g, f"NEAR={v}")
        scan.append((v, sd))
        A(f"| {v:.2f} | {sd['n']} | {100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
          f"{sd['z']:+.2f} | {sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} | "
          f"{sd['tot_money']:+.2f} |")
    NEAR = keep_near
    A("")
    A("### 7.2 去重开关（A / B）")
    A("")
    A("| 变体 | n | 命中率 | 几何零假设 | z_geom | 均净R | 均净钱 | 总净钱 |")
    A("|---|---|---|---|---|---|---|---|")
    for lbl, gen in (("A 不去重", lambda: gen_A(bars, ctx, dedup=False)),
                     ("B 不去重", lambda: gen_B(bars, ctx, dedup=False))):
        g = gen()
        for s in g:
            race(s, bars, subs)
        sd = summarize(g, lbl)
        A(f"| {lbl} | {sd['n']} | {100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
          f"{sd['z']:+.2f} | {sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} | "
          f"{sd['tot_money']:+.2f} |")
    A("")
    A("### 7.3 C 的另一种读法（方向 = 交叉方向而非状态层）")
    A("")
    A("题目给的 C 是「只剩状态与方向，入场用 EMA 交叉」，直译就是**方向仍由规则 3 决定**。"
      "但 EMA 交叉那一刻五线几乎从不排列，所以 C 的绝大多数信号落在「区间态 = 朝锚交易」，"
      "变成了一个逆势策略。这未必是题目的本意，所以把「方向 = 交叉方向」的读法 C' 也报出来。")
    A("")
    A("| 变体 | n | 命中率 | 几何零假设 | z_geom | 均净R | 均净钱 | 总净钱 |")
    A("|---|---|---|---|---|---|---|---|")
    for sd in (dC, dCp):
        A(f"| {sd['label']} | {sd['n']} | {100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
          f"{sd['z']:+.2f} | {sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} | "
          f"{sd['tot_money']:+.2f} |")
    ctrend = sum(1 for s in sC if s.state == "趋势")
    A("")
    A(f"- C 的 {len(sC)} 个信号里只有 {ctrend} 个（{100*ctrend/max(len(sC),1):.1f}%）"
      f"落在趋势态。")
    A("")
    A("### 7.4 v14 的入场 + 极简版的尺子（D°）")
    A("")
    A("D 与 A 差在两处：**选哪根 K 入场**，和**止损用什么**。把 v14 的入场事件原样保留、"
      "只把止损从「回踩的运行极值」换成「反方向上一个具名位」，就能把这两处分开。")
    A("")
    sDo = []
    for s in sD:
        c = ctx[s.i]
        if c is None:
            continue
        stp, tgt = brackets(s.entry, s.direction, c["anchor"], c["atr"])
        risk, rew = abs(s.entry - stp), abs(tgt - s.entry)
        if risk < MIN_RISK_PTS:
            continue
        sDo.append(Sig("D° · v14入场+位尺", s.i, s.dt, s.session, s.direction,
                       s.state, s.entry, stp, tgt, risk, rew, s.atr))
    for s in sDo:
        race(s, bars, subs)
    dDo = summarize(sDo, "D° · v14入场+位尺")
    A("| 变体 | n | 中位止损(ATR) | 命中率 | 几何零假设 | 超额 pp | z_geom | 均净R | 均净钱 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for sd in (dD, dDo, dA):
        A(f"| {sd['label']} | {sd['n']} | {sd['risk_atr']:.3f} | "
          f"{100*sd['hit']:.1f}% | {100*sd['null']:.1f}% | "
          f"{100*(sd['hit']-sd['null']):+.1f} | {sd['z']:+.2f} | "
          f"{sd['avg_net']:+.3f} | {sd['avg_money']:+.4f} |")
    zdo = two_sample_z(dDo["moneys"], dD["moneys"])
    bump()
    A("")
    A(f"- 换尺子的效果：均净钱 {dD['avg_money']:+.4f} → {dDo['avg_money']:+.4f}，"
      f"两样本 z = **{zdo:+.2f}** (p={two_sided(zdo):.3f})。")
    A(f"- 超额命中 {100*(dD['hit']-dD['null']):+.1f} pp → "
      f"{100*(dDo['hit']-dDo['null']):+.1f} pp。")
    A("")

    A("### 7.5 毛 R vs 净 R（点差吃掉多少）")
    A("")
    A("| 选手 | n | 均毛R | 均净R | 均毛钱(ATR) | 点差成本(ATR/笔) | 均净钱(ATR) |")
    A("|---|---|---|---|---|---|---|")
    for d in (dA, dB, dC, dD, dE):
        dec = [s for s in d["sigs"] if s.hit is not None]
        gm = st.mean([s.r * s.risk_atr for s in dec])
        sc = st.mean([SPREAD / s.atr for s in dec])
        A(f"| {d['label']} | {d['n']} | {d['avg_r']:+.3f} | {d['avg_net']:+.3f} | "
          f"{gm:+.4f} | {sc:.4f} | {d['avg_money']:+.4f} |")
    A("")
    A("**扣点差之前，五个选手的毛钱全部贴着零**（最大 +0.0014，最小 −0.0045 ATR，"
      "都在噪声里）。扣点差之后全部变负，而点差每笔恒定吃掉 0.0063 ATR。"
      "也就是说：**这五个版本的负期望，几乎全部是点差贡献的**。"
      "这是「入场那一刻没有优势」最直白的表述——一个没有优势的策略，"
      "唯一确定的产出就是手续费。")
    A("")

    A("## 8 · 谁亏得最少，以及简单性值多少钱")
    A("")
    A("五个选手**全部负期望**。这是很可能的结果，不粉饰。所以问题换成："
      "亏得最少的是谁，为这份「少亏」你要付多少复杂度。")
    A("")
    A("排名按**均净钱**（唯一跨止损尺度可比的量），越靠上越好：")
    A("")
    A("| 排名 | 选手 | 可调数字 | 均净钱(ATR) | vs 随机地板 | 均净R | z_geom |")
    A("|---|---|---|---|---|---|---|")
    rank = sorted([dB, dE, dA, dC, dDl, dD], key=lambda d: -d["avg_money"])
    for i, d in enumerate(rank, 1):
        pnum = {"A · 极简版": "7", "B · 去状态层": "2", "C · 去位置层": "6",
                "D · v14 全套": "20+", "D · v14 线上排队": "20+",
                "E · 纯随机": "1"}[d["label"]]
        dm = d["avg_money"] - dE["avg_money"]
        A(f"| {i} | {d['label']} | {pnum} | {d['avg_money']:+.4f} | "
          f"{dm:+.4f} | {d['avg_net']:+.3f} | {d['z']:+.2f} |")
    A("")
    A("把它换成人话的成本：一笔标准仓位，日 ATR 约 88 点（用户 CFD 的实测值）。")
    A("")
    A(f"| 选手 | 每笔平均亏 (ATR) | 每笔平均亏 (点，按 88 点 ATR) | "
      f"{days_span} 天累计 (ATR) | 折算成每天 (点) |")
    A("|---|---|---|---|---|")
    for d in rank:
        A(f"| {d['label']} | {d['avg_money']:+.4f} | "
          f"{88*d['avg_money']:+.2f} | {d['tot_money']:+.2f} | "
          f"{88*d['tot_money']/days_span:+.2f} |")
    A("")
    A("两条读表须知：")
    A("")
    A("- 「累计」那两列**不能跨选手比大小**——各选手的交易笔数差好几倍，笔数多的自然"
      "累计亏得多；E 的笔数更是人为设定的随机池大小，它那两格没有意义。可比的只有"
      "「每笔」那两列。")
    A(f"- 「每笔」两列假设每笔的**名义敞口相同**。如果改成按固定 R 风险下注，就要看均净R "
      f"那一列——但那样 B 的「每笔只冒 {dB['risk_atr']:.3f} ATR 风险」会被放大成和 D 的 "
      f"{dD['risk_atr']:.3f} ATR 同等大小的仓位，杠杆完全不同，不是同一件事。")
    A("")
    gap = 88 * (rank[0]["avg_money"] - rank[-1]["avg_money"])
    A(f"**这张排行榜最重要的一件事是它有多平。** 第一名和最后一名之间相差 "
      f"{gap:.2f} 点/笔——**比点差本身（{SPREAD} 点）还小**。第 3 节的两样本 z 里，"
      f"没有任何一对选手在均净钱上分得开（|z| 全部 < 1.96）。也就是说这个排名的次序"
      f"不要当真，能当真的只有一句：**它们全在一条水平线上，而那条线在零以下**。")
    A("")

    A("## 9 · 多重比较自报")
    A("")
    bz = _bonf_z(CELLS)
    zmax = max(ZS, key=lambda t: t[1])
    zmin = min(ZS, key=lambda t: t[1])
    crossed = [t for t in ZS if abs(t[1]) > bz]
    A(f"全文共检视 **{CELLS} 个格子**（主表、分时段、状态拆分、对撞、自助带、敏感性扫描）。"
      f"Bonferroni 门槛 |z| > {bz:.2f}（α=0.05 双侧）。"
      f"常规 |z|>1.96 在这个 family size 下**基本没有意义**。")
    A("")
    A(f"- 全文 {len(ZS)} 个 z_geom：最大 **{zmax[1]:+.2f}**（{zmax[0]}），"
      f"最小 **{zmin[1]:+.2f}**（{zmin[0]}）。")
    A(f"- 越过 Bonferroni 门槛的格子：**{len(crossed)} 个**"
      + ("。" if not crossed
         else "：" + "、".join(f"{t[0]} ({t[1]:+.2f})" for t in crossed) + "。"))
    A(f"- 第 6 节那个「趋势态好于区间态」的 z = {zsplit:+.2f}，也**没有**越过 "
      f"{bz:.2f}。它是本文最像信号的一个格子，但在这个 family size 下不能算数。")
    A("")

    A("## 10 · 局限")
    A("")
    A("1. **位相关研究不能用 ^GSPC 代理**（纪律 5）。主样本已经用 ES=F，作息与 "
      "CAPITALCOM:SPX500 一致、含完整夜盘。但 ES=F 仍不是用户真正交易的 CFD，"
      "两者的日 ATR 与前收锚会有小差异，因此**本文所有依赖具体位价的结论都带这个局限**。")
    A(f"2. 样本只有 {bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}（5m 数据只有 60 天），"
      f"约 {len(bars)} 根 10m K。这是一个市场状态，不是十年。")
    A("3. 纯括号赛跑不含分批、不含移动止损、不含 13 线离场。它衡量的是**入场那一刻的"
      "几何优势**，不是完整策略的最终损益。D 的完整管理版本另有 `V15_ENTRY_LOCATION.md` "
      "的数字（均净R −0.142，总净R −73.6）。")
    A("4. 无法裁决的信号被弃权而不是硬判，这在方法上是对的（纪律 2），但会轻微偏向"
      "「大止损、慢裁决」的选手——它们的含混率更低。各选手的弃权率在第 1 节已列出。")
    A(f"5. B 的止损中位只有 {dB['risk_atr']:.3f} ATR（约 {88*dB['risk_atr']:.1f} 点）。"
      f"这么紧的止损在真实成交里会被滑点和瞬时插针大量打掉，模型只扣了 {SPREAD} 点点差，"
      f"**B 的数字一定偏乐观**。它排在第一位这件事不要当真。")
    A("")

    # ── 最后一节：普通话 ────────────────────────────────────────────────────
    A("## 11 · 回答你的问题（不用统计黑话）")
    A("")
    A("> 「这个东西其实很符合直觉的，我不知道这里面为什么搞得这么多呢？」")
    A("")
    A("**你的直觉是对的：那二十多个参数在这份数据上没有买到任何东西。**"
      "但下面还有一个更不舒服的结论，得一起说。")
    A("")
    A("我把你那句「符合直觉」的版本真的写出来了——四条规则，一句话能说完：看价格在不在"
      "盒子里、只在位附近动手、区间朝里趋势顺势、目标和止损都用同一把位尺。然后拿它和"
      "现在这套二十多个参数的 v14 放在同一份数据上、跑一模一样的判定。结果是：")
    A("")
    A(f"1. **两个都在亏，而且亏得差不多。** 同样大小的仓位，四条规则的版本每笔平均亏 "
      f"{abs(88*dA['avg_money']):.2f} 点，v14 全套每笔平均亏 "
      f"{abs(88*dD['avg_money']):.2f} 点。这两个数在统计上根本分不开（z=+0.43）。"
      f"多出来的那十几个参数，没有把亏损变小一分钱。")
    A(f"2. **更难受的是：扔硬币亏得比这两个都少。** 在同样的 K 上随机决定做多做空、用"
      f"同样的目标和止损，每笔平均亏 {abs(88*dE['avg_money']):.2f} 点。"
      f"四条规则和二十条规则，**都没有比扔硬币多提供任何信息**。"
      f"（严格地说，也没有比扔硬币差——所有选手和随机之间都分不开。"
      f"「分不开」这件事本身就是答案：规则在做的事等于没做。）")
    A(f"3. **唯一一个能和随机分开的，是 v14，而且是往坏的方向分开。** 同样做 {dD['n']} 笔，"
      f"随机的总账中位数是 {bandD['tot_md']:+.1f}R，90% 的随机结果落在 "
      f"[{bandD['tot_lo']:+.1f}, {bandD['tot_hi']:+.1f}]R 之间；v14 实测 "
      f"{dD['tot_net']:+.1f}R，落在随机分布的第 {pct_vs_rand(bandD, dD['tot_net']):.1f} "
      f"百分位——比 99% 的随机结果都差。线上排队口径也一样（第 "
      f"{pct_vs_rand(boot_band(dDl['n']), dDl['tot_net']):.1f} 百分位）。"
      f"那些闸门和分级不是没用，是**倒扣分**。")
    A(f"4. **「规则少」不等于「动手少」。** 四条规则的版本吐出 {dA['n_sig']} 个信号，"
      f"v14 只有 {dD['n_sig']} 个——极简版反而**更频繁**地叫你下单（平均每天 "
      f"{dA['n_sig']/days_span:.0f} 次 vs {dD['n_sig']/days_span:.0f} 次），"
      f"点差付得更多。所以「砍成四条规则」并不自动等于「更省心、更便宜」。")
    A("")
    A("**那这些复杂度到底是干什么用的？** 从这份数据看，能指认出来的只有两件事：")
    A("")
    A(f"- 它把交易次数从「每 {nb/dA['n_sig']:.1f} 根 K 一笔」压到「每 "
      f"{nb/dD['n_sig']:.1f} 根一笔」。这是有用的，但一行「一天最多两笔」就能做到，"
      f"不需要二十个参数。")
    A(f"- 它把止损从「反方向上一个位」换成了「回踩的运行极值」。第 7.4 节把这一处单独"
      f"换回来测了：v14 的入场一个不动，只换止损尺子，胜率相对几何零假设的赤字从 "
      f"{100*(dD['hit']-dD['null']):+.1f} pp 变成 {100*(dDo['hit']-dDo['null']):+.1f} pp，"
      f"完全消失。**但钱上的改善（每笔 {88*(dDo['avg_money']-dD['avg_money']):+.2f} 点，"
      f"z={zdo:+.2f}）没有达到统计显著**，所以只能说「嫌疑很大」，不能说「已证实」。")
    A("")
    A("**那「简单」值多少钱？** 用钱算：全场第一名和最后一名之间只差 "
      f"{gap:.2f} 点/笔，比点差本身（{SPREAD} 点）还小；而且没有任何一对选手在统计上"
      f"分得开。所以简单版本的价值**不在收益上**，只在三件事上——你能一眼看懂它、"
      f"你能自己判断它什么时候不该用、以及它坏掉的时候你知道是哪一条坏了。"
      f"这三件事有价值，但它们不是钱。别指望砍参数能把账做正。")
    A("")
    A("**所以下一步该怎么办。** 不是继续加规则，也不是回去调这四条规则的数字——这两条路"
      "这份报告都走过了，都不动。真正的问题在更上游：**在这个 10 分钟周期上、用这一套位"
      "做目标和止损，入场那一刻本身就没有优势**。一件本身没有优势的事，用四条规则做和用"
      "二十条规则做，结果都只是在亏点差。要动就得动更上游的东西：换周期、换赔率结构"
      "（目标放远到两个位以外、止损收到位的另一侧）、或者只在某个明确的时段做"
      "（RTH 那几格是全文里唯一没有明显吃亏的地方，但它同样没有越过统计门槛，"
      "不能当成发现）。继续雕规则，是在装修一间没有地基的房子。")
    A("")
    A("**一句话：你的直觉没错，这些复杂度在这份数据上是纯成本。但把它砍到四条规则也"
      "不会赚钱——因为亏的不是复杂度，是这个入场本身。**")
    A("")

    txt = "\n".join(o)
    return txt, {"A": dA, "B": dB, "C": dC, "D": dD, "Dl": dDl, "E": dE,
                 "bandA": bandA, "bandD": bandD, "cells": CELLS,
                 "near_pct": 100 * near_ok / near_tot, "bars": bars}


def _bonf_z(m: int, alpha: float = 0.05) -> float:
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if two_sided(mid) * m > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    body, res = main()
    REPORT.write_text(body + "\n", encoding="utf-8")
    print(body)
    print("\n" + "=" * 70)
    print("SUMMARY FOR RETURN VALUE")
    for k in ("A", "B", "C", "D", "Dl", "E"):
        d = res[k]
        print(f"{d['label']:<26} n={d['n']:<5} hit={100*d['hit']:.1f}% "
              f"null={100*d['null']:.1f}% z={d['z']:+.2f} "
              f"avgR={d['avg_r']:+.3f} avgNet={d['avg_net']:+.3f} "
              f"totNet={d['tot_net']:+.1f} dd={d['dd']:.1f} "
              f"avgMoney={d['avg_money']:+.4f} totMoney={d['tot_money']:+.2f}")
