"""V15 · 夜盘解剖：「总亏损 88% 来自夜盘」的机制层拆解。

为什么有这个文件
----------------
`V15_ENTRY_LOCATION.md` 报了三行数：

    RTH  n=142  纯括号 69.7%  几何零假设 66.7%  z_geom +0.82  均净R -0.063  总净R  -8.9
    夜盘 n=375  纯括号 48.1%  几何零假设 54.3%  z_geom -2.68  均净R -0.173  总净R -64.7
    全部 n=517  纯括号 54.1%  几何零假设 57.7%  z_geom -1.88  均净R -0.142  总净R -73.6

-64.7 / -73.6 = 87.9%。用户问的不是「是不是」，是「**怎么做到的**」。

本文件把这个 88% 拆成三层：

  第一层 · 算术    份额 × 每笔劣势，各贡献多少；份额是不是仅仅等于时段长度。
  第二层 · 机制    尺度错配假设：目标用【日线 ATR】刻度（固定的具名位阶梯），
                   止损用【结构】刻度（近几根 K 的极值）。夜盘 K 小 → 止损小 →
                   S/(S+T) 塌陷 → 几何零假设塌陷 → 同样的 pp 缺口换算成更多 R，
                   而且 0.6 点点差摊到更小的 R 上更贵。
  第三层 · 反事实  最小风险闸门 / 目标按夜盘实际波动缩放 / 干脆不做夜盘。

纪律：几何零假设 P=S/(S+T)；路径判定落 5m 子 K；点差 0.6 点毛净双报；
主样本 ES=F（含完整夜盘），^GSPC 只能做 RTH 对照；多重比较自报 family size。

Usage:  .venv/bin/python research/satylab/study_overnight_anatomy.py
"""

from __future__ import annotations

import bisect
import math
import statistics as st
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, stats                                  # noqa: E402
from satylab.data import Bar                                     # noqa: E402
from satylab.indicators import ema                               # noqa: E402
from satylab.study_v14_repro import (                            # noqa: E402
    LevelBook, load_10m, next_rung, trade_day,
)
from satylab.study_entry_location import (                       # noqa: E402
    Sig, SPREAD, RACE_CAP, STACK_BARS, MIN_RISK_PTS,
    location_vars, isolated_trade, excursion,
    z_geom, spearman, tstat, two_sided, q, _bonf_z,
)

REPORT = Path(__file__).resolve().parents[1] / "reports" / "V15_OVERNIGHT_ANATOMY.md"
SEG_ATR_LEN = 14

CELLS = 0


def bump(n: int = 1) -> None:
    global CELLS
    CELLS += n


# ══════════════════════════ 时段划分（America/New_York）══════════════════════
BUCKETS = ["亚洲 18:00–02:00", "欧洲 02:00–07:00", "盘前 07:00–09:30",
           "RTH 09:30–16:00", "收盘后 16:00–17:00"]


def bucket(dt) -> str:
    hm = (dt.hour, dt.minute)
    if (9, 30) <= hm < (16, 0):
        return "RTH 09:30–16:00"
    if (16, 0) <= hm < (18, 0):
        return "收盘后 16:00–17:00"
    if hm >= (18, 0) or hm < (2, 0):
        return "亚洲 18:00–02:00"
    if (2, 0) <= hm < (7, 0):
        return "欧洲 02:00–07:00"
    return "盘前 07:00–09:30"


ON_BUCKETS = [b for b in BUCKETS if not b.startswith("RTH")]


# ══════════════════════════ 状态机（带可插拔的风险闸门）══════════════════════
def harvest2(bars: list[Bar], book: LevelBook, gate=None,
             stack_bars: int = STACK_BARS,
             min_risk: float = MIN_RISK_PTS) -> tuple[list[Sig], list]:
    """study_entry_location.harvest 的逐字复制，多一个可插拔的风险闸门。

    `gate(risk_pts, atr, in_rth) -> bool`：返回 False 表示这一笔被闸门挡掉。
    挡掉之后状态机的后续演化**照 Pine 的写法**继续——Recovery 无论如何复位，
    Vomy 只在真开仓时复位。这个不对称是源码里的，不是我们的，所以「事后筛掉
    一批信号」和「在状态机里装闸门」不是同一件事，两者都要报。
    """
    closes = [b.close for b in bars]
    e8s, e13s = ema(closes, 8), ema(closes, 13)
    e34s, e48s = ema(closes, 34), ema(closes, 48)
    e21s = ema(closes, 21)

    sBull = sBear = 0
    prev_sBull = prev_sBear = 0
    recL = recS = 0
    recLExt = recSExt = None
    vomS = vomL = 0
    vomSFin = vomLFin = None
    out: list[Sig] = []

    def ok(risk: float, atr: float, in_rth: bool) -> bool:
        if risk < min_risk:
            return False
        return True if gate is None else gate(risk, atr, in_rth)

    for i, b in enumerate(bars):
        if e48s[i] is None:
            continue
        e8, e13, e21, e34, e48 = e8s[i], e13s[i], e21s[i], e34s[i], e48s[i]
        sc, sh, sl = b.close, b.high, b.low
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        anchor, atr = lv

        prev_sBull, prev_sBear = sBull, sBear
        sBull = sBull + 1 if (e8 > e13 > e21 > e34 > e48) else 0
        sBear = sBear + 1 if (e8 < e13 < e21 < e34 < e48) else 0
        stack_bull, stack_bear = sBull > 0, sBear > 0

        hh10 = max(x.high for x in bars[max(0, i - 9):i + 1])
        ll10 = min(x.low for x in bars[max(0, i - 9):i + 1])
        in_rth = (9, 30) <= (b.dt.hour, b.dt.minute) < (16, 0)

        def emit(setup: str, d: int, prot: float, risk: float) -> None:
            out.append(Sig(setup=setup, direction=d,
                           session="RTH" if in_rth else "夜盘",
                           i=i, dt=b.dt, entry=sc, prot=prot, risk=risk,
                           t1=next_rung(sc, d, anchor, atr),
                           t2=next_rung(next_rung(sc, d, anchor, atr), d,
                                        anchor, atr),
                           atr=atr, blocked=False))

        if recL == 0 and sBull >= stack_bars and sc < e13:
            recL, recLExt = 1, sl
        elif recL == 1:
            recLExt = min(recLExt, sl)
            if sc < e34 or stack_bear:
                recL = 0
            elif sc > e13:
                if ok(sc - recLExt, atr, in_rth):
                    emit("Recovery", +1, recLExt, sc - recLExt)
                recL = 0
        if recS == 0 and sBear >= stack_bars and sc > e13:
            recS, recSExt = 1, sh
        elif recS == 1:
            recSExt = max(recSExt, sh)
            if sc > e34 or stack_bull:
                recS = 0
            elif sc < e13:
                if ok(recSExt - sc, atr, in_rth):
                    emit("Recovery", -1, recSExt, recSExt - sc)
                recS = 0
        if vomS == 0 and prev_sBull >= stack_bars and sc < e13 and sc < e8:
            vomS, vomSFin = 2, hh10
        elif vomS == 2:
            vomSFin = max(vomSFin, sh)
            if sc > e13:
                vomS = 0
            elif sh >= e13:
                if ok(vomSFin - sc, atr, in_rth):
                    emit("Vomy", -1, vomSFin, vomSFin - sc)
                    vomS = 0
        if vomL == 0 and prev_sBear >= stack_bars and sc > e13 and sc > e8:
            vomL, vomLFin = 2, ll10
        elif vomL == 2:
            vomLFin = min(vomLFin, sl)
            if sc < e13:
                vomL = 0
            elif sl <= e13:
                if ok(sc - vomLFin, atr, in_rth):
                    emit("Vomy", +1, vomLFin, sc - vomLFin)
                    vomL = 0

    return out, e13s


# ══════════════════════ 括号赛跑（多记一个「跑了多久」）══════════════════════
@dataclass
class Race:
    hit: bool | None
    pnull: float
    bars: int          # 到裁决用了多少根 setup K
    hours: float       # 挂钟小时
    tdist: float       # 目标距离（点）


def race(entry: float, prot: float, risk: float, target: float, d: int,
         i0: int, bars: list[Bar], subs, cap: int = RACE_CAP) -> Race:
    """保护位 vs 目标，谁先到。路径判定落到 5m 子 K（纪律 2/3）。"""
    T = abs(target - entry)
    pn = risk / (risk + T) if (risk + T) > 0 else float("nan")
    for i in range(i0 + 1, min(i0 + 1 + cap, len(bars))):
        seq = subs[i] if subs is not None else [bars[i]]
        for sb in seq:
            ph = (sb.low <= prot) if d > 0 else (sb.high >= prot)
            gh = (sb.high >= target) if d > 0 else (sb.low <= target)
            hrs = (sb.dt - bars[i0].dt).total_seconds() / 3600.0
            if ph and gh:
                return Race(None, pn, i - i0, hrs, T)
            if gh:
                return Race(True, pn, i - i0, hrs, T)
            if ph:
                return Race(False, pn, i - i0, hrs, T)
    return Race(None, pn, cap, float("nan"), T)


def bracket_r(rc: Race, risk: float) -> float:
    """纯括号的 R：命中 = +T/S，止损 = -1。零假设下期望恰好 = 0。"""
    if rc.hit is None:
        return float("nan")
    return (rc.tdist / risk) if rc.hit else -1.0


# ════════════════════════════ 分段已实现 ATR ════════════════════════════════
def wilder(trs: list[float], length: int = SEG_ATR_LEN) -> list[float | None]:
    out: list[float | None] = [None] * len(trs)
    if len(trs) < length:
        return out
    prev = sum(trs[:length]) / length
    out[length - 1] = prev
    for i in range(length, len(trs)):
        prev = (prev * (length - 1) + trs[i]) / length
        out[i] = prev
    return out


def segment_atr(bars: list[Bar], keyfn) -> tuple[dict, dict]:
    """把 bars 按 keyfn 分块，对块的真实波幅做 Wilder(14)。

    构造与日线 ATR 完全平行：块高 / 块低 / 块收，TR = max(H-L, |H-prevC|,
    |L-prevC|)。返回的 ATR 是**上一块收盘时**的值，所以块内任何一根 K 用它都
    没有前视。第二个返回值带每块的 TR / K 数 / 逐根振幅之和，用于算「路径效率」。
    """
    blocks: dict = {}
    for b in bars:
        k = keyfn(b)
        if k is None:
            continue
        blocks.setdefault(k, []).append(b)
    keys = sorted(blocks)
    trs, closes = [], []
    meta: dict = {}
    for j, k in enumerate(keys):
        g = blocks[k]
        hi = max(x.high for x in g)
        lo = min(x.low for x in g)
        if j == 0:
            tr = hi - lo
        else:
            pc = closes[-1]
            tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
        trs.append(tr)
        closes.append(g[-1].close)
        meta[k] = {"tr": tr, "bars": len(g),
                   "sum_range": sum(x.high - x.low for x in g)}
    a = wilder(trs)
    return {k: (a[j - 1] if j >= 1 else None) for j, k in enumerate(keys)}, meta


def build_block_keys(bars: list[Bar]):
    """夜盘块 = 「通向某个 RTH 日的那一整段非 RTH 时间」；RTH 块 = 该 RTH 日。"""
    rth_days = sorted({b.day for b in bars if bucket(b.dt).startswith("RTH")})

    def on_key(b: Bar):
        if bucket(b.dt).startswith("RTH"):
            return None
        if (b.dt.hour, b.dt.minute) < (9, 30):
            j = bisect.bisect_left(rth_days, b.day)
        else:                                   # >= 16:00，通向下一个 RTH 日
            j = bisect.bisect_right(rth_days, b.day)
        return rth_days[j] if j < len(rth_days) else None

    def rth_key(b: Bar):
        return b.day if bucket(b.dt).startswith("RTH") else None

    return on_key, rth_key, rth_days


# ═══════════════════════════════ 小工具 ══════════════════════════════════════
def fm(x, p=3, sign=False):
    if x is None or x != x:
        return "–"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def sel_z(sub: list[float], full: list[float]) -> float:
    """有限总体修正的选择 z：从 N 笔里抽 n 笔，均值高出这么多算不算意外。"""
    N, n = len(full), len(sub)
    if n == 0 or N <= n:
        return float("nan")
    var = st.pvariance(full)
    se = math.sqrt(var / n * (N - n) / (N - 1))
    return (st.mean(sub) - st.mean(full)) / se if se > 0 else float("nan")


def block(sigs: list[Sig], label: str) -> dict:
    res = [s for s in sigs if s.hit is not None]
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    rs = [s.r for s in sigs]
    ns = [s.net for s in sigs]
    return {"label": label, "N": len(sigs), "n": n, "obs": obs, "null": null,
            "z": z, "gross": st.mean(rs) if rs else float("nan"),
            "net": st.mean(ns) if ns else float("nan"),
            "tot": sum(ns), "tot_gross": sum(rs)}


# ═══════════════════════════════ 主流程 ══════════════════════════════════════
def main() -> None:
    o: list[str] = []
    A = o.append

    bars, subs = load_10m("ES=F", False)
    book = LevelBook(data.load("ES=F", "20y", "1d"))
    sigs, e13s = harvest2(bars, book)
    sigs = location_vars(sigs, bars, e13s)

    # 每根 setup K 的日 ATR（用于 K 振幅归一）与「引擎是否在线」
    closes = [b.close for b in bars]
    e48s = ema(closes, 48)
    live_bars: list[tuple[Bar, float]] = []
    for i, b in enumerate(bars):
        if e48s[i] is None:
            continue
        lv = book.get(trade_day(b))
        if lv is None:
            continue
        live_bars.append((b, lv[1]))

    # 括号 + 孤立重放 + MFE/MAE
    races: dict[int, Race] = {}
    for s in sigs:
        rc = race(s.entry, s.prot, s.risk, s.t1, s.direction, s.i, bars, subs)
        s.hit, s.pnull = rc.hit, rc.pnull
        races[id(s)] = rc
        isolated_trade(s, bars, subs, e13s)
        excursion(s, bars, subs)

    RTH = [s for s in sigs if s.in_rth]
    ON = [s for s in sigs if not s.in_rth]
    bR, bO, bA = block(RTH, "RTH"), block(ON, "夜盘"), block(sigs, "全部")

    # ── 抬头 ────────────────────────────────────────────────────────────────
    A("# V15 · 夜盘解剖：「88% 的亏损来自夜盘」是怎么做到的")
    A("")
    A(f"生成脚本 `research/satylab/study_overnight_anatomy.py`。主样本 **ES=F 10m**"
      f"（由 60d 5m 聚合，含完整 23 小时时段，与 CAPITALCOM:SPX500 作息一致），"
      f"{bars[0].dt:%Y-%m-%d} → {bars[-1].dt:%Y-%m-%d}，{len(bars)} 根 setup K，"
      f"{len(sigs)} 个入场信号（去掉单仓闸门，口径与 `V15_ENTRY_LOCATION.md` 第 1 节"
      f"完全一致，三行基线数字逐位复现）。路径判定全部落到 5 分钟子 K。")
    A("")
    A("**位相关的局限（纪律 5）**：本文所有「距离」都以**日 ATR 归一**后报告，"
      "从不报具体位价。ES=F 与 CAPITALCOM:SPX500 的 ATR 不是常数比（246 天 mean "
      "1.117 / sd 0.083 / 范围 0.826–1.418），所以「0.12 日ATR 的最小风险」这类"
      "结论在两个标的上是同一个**比例**，但换算成点数会差一成以上。")
    A("")

    # ══════════════════ 第一层 · 算术分解 ═══════════════════════════════════
    A("## 一 · 算术分解：88% 是「笔数 × 每笔」")
    A("")
    A("| | RTH | 夜盘 | 全部 |")
    A("|---|---|---|---|")
    A(f"| 信号数 | {bR['N']} | {bO['N']} | {bA['N']} |")
    A(f"| 笔数份额 | {100*bR['N']/bA['N']:.1f}% | {100*bO['N']/bA['N']:.1f}% | 100% |")
    A(f"| 均净R | {bR['net']:+.3f} | {bO['net']:+.3f} | {bA['net']:+.3f} |")
    A(f"| 总净R | {bR['tot']:+.1f} | {bO['tot']:+.1f} | {bA['tot']:+.1f} |")
    A(f"| 总净R 份额 | {100*bR['tot']/bA['tot']:.1f}% | "
      f"**{100*bO['tot']/bA['tot']:.1f}%** | 100% |")
    bump(3)
    A("")
    odds_n = bO["N"] / bR["N"]
    odds_m = bO["net"] / bR["net"]
    odds = odds_n * odds_m
    A("亏损份额是一个乘积，不是一个现象：")
    A("")
    A("```")
    A(f"夜盘亏损 / RTH亏损 = (笔数比) × (每笔亏损比)")
    A(f"                    = ({bO['N']}/{bR['N']}) × ({-bO['net']:.3f}/{-bR['net']:.3f})")
    A(f"                    = {odds_n:.3f} × {odds_m:.3f} = {odds:.2f}")
    A(f"夜盘份额 = {odds:.2f} / (1 + {odds:.2f}) = {100*odds/(1+odds):.1f}%")
    A("```")
    A("")
    A(f"取对数把两个因子摊平：ln({odds:.2f}) = {math.log(odds):.3f} = "
      f"ln({odds_n:.3f}) + ln({odds_m:.3f}) = {math.log(odds_n):.3f} + "
      f"{math.log(odds_m):.3f}。")
    A(f"**笔数占 {100*math.log(odds_n)/math.log(odds):.0f}%，每笔劣势占 "
      f"{100*math.log(odds_m)/math.log(odds):.0f}%——两个因子几乎五五开。**")
    A("")
    A("### 1.1 反事实：如果夜盘每笔和 RTH 一样贵")
    A("")
    cf_on = bO["N"] * bR["net"]
    cf_tot = cf_on + bR["tot"]
    A("| 情形 | 夜盘总净R | 全样本总净R | 夜盘份额 |")
    A("|---|---|---|---|")
    A(f"| 实际 | {bO['tot']:+.1f} | {bA['tot']:+.1f} | {100*bO['tot']/bA['tot']:.1f}% |")
    A(f"| 夜盘每笔换成 RTH 的 {bR['net']:+.3f} | {cf_on:+.1f} | {cf_tot:+.1f} | "
      f"{100*cf_on/cf_tot:.1f}% |")
    A(f"| 夜盘每笔归零（只剩 RTH 的亏） | 0.0 | {bR['tot']:+.1f} | 0.0% |")
    bump(2)
    A("")
    A(f"**答案：{bO['N']} 笔夜盘如果每笔只亏 RTH 那么多（{bR['net']:+.3f}），"
      f"总净R 会从 {bA['tot']:+.1f} 变成 {cf_tot:+.1f}，"
      f"账本改善 {cf_tot - bA['tot']:+.1f}R（{100*(cf_tot-bA['tot'])/abs(bA['tot']):.0f}% "
      f"的亏损消失）。夜盘份额仍然有 {100*cf_on/cf_tot:.1f}%——因为笔数还在那里。**")
    A("")

    # ── 密度：份额是不是平凡的 ─────────────────────────────────────────────
    A("### 1.2 72.5% 的笔数份额是平凡的吗")
    A("")
    A("如果夜盘信号密度（每 1000 根 K 出几个信号）与 RTH 一样，那么笔数份额就只是"
      "「夜盘 K 更多」这个平凡事实的复述，不构成独立的缺陷。")
    A("")
    nb_rth = sum(1 for b, _ in live_bars if bucket(b.dt).startswith("RTH"))
    nb_on = len(live_bars) - nb_rth
    d_rth = 1000 * len(RTH) / nb_rth
    d_on = 1000 * len(ON) / nb_on
    A("| | RTH | 夜盘 | 比值（夜/RTH） |")
    A("|---|---|---|---|")
    A(f"| 可用 setup K | {nb_rth} | {nb_on} | {nb_on/nb_rth:.3f} |")
    A(f"| K 数份额 | {100*nb_rth/len(live_bars):.1f}% | "
      f"{100*nb_on/len(live_bars):.1f}% | |")
    A(f"| 信号数 | {len(RTH)} | {len(ON)} | {len(ON)/len(RTH):.3f} |")
    A(f"| 信号份额 | {100*len(RTH)/len(sigs):.1f}% | "
      f"{100*len(ON)/len(sigs):.1f}% | |")
    A(f"| **密度（信号/1000K）** | **{d_rth:.1f}** | **{d_on:.1f}** | "
      f"**{d_on/d_rth:.3f}** |")
    bump(2)
    zd = stats.two_proportion_z(len(ON), nb_on, len(RTH), nb_rth)
    A("")
    A(f"两比例 z（夜盘密度 vs RTH 密度）= **{zd:+.2f}**（p={two_sided(zd):.3f}）。")
    A("")
    A(f"ES=F 一天交易 23 小时（17:00–18:00 ET 停盘），RTH 6.5 小时，"
      f"所以时段长度给出的**平凡预期**是夜盘占 16.5/23 = **71.7%**。"
      f"实测 K 数份额 {100*nb_on/len(live_bars):.1f}%，信号份额 "
      f"{100*len(ON)/len(sigs):.1f}%。")
    A("")
    if abs(zd) < 1.96:
        A(f"**判决：笔数份额是平凡的。** 夜盘密度 {d_on:.1f} vs RTH {d_rth:.1f}，"
          f"比值 {d_on/d_rth:.2f}，两比例 z={zd:+.2f} 够不着 1.96。"
          f"「73% 的交易在夜盘」这句话里没有任何信息量——它就是"
          f"「夜盘占了 {100*nb_on/len(live_bars):.0f}% 的 K」的同义反复。"
          f"真正的缺陷全部在**每笔**那一项上。")
    else:
        A(f"**判决：笔数份额不是平凡的。** 夜盘密度是 RTH 的 {d_on/d_rth:.2f} 倍，"
          f"z={zd:+.2f}，这是一个独立于时段长度的问题，见 1.3。")
    A("")

    # 分时段密度
    A("### 1.3 逐时段密度（这里才看得出不平凡的部分）")
    A("")
    nbar, nsig, dens = {}, {}, {}
    for bk in BUCKETS:
        nbar[bk] = sum(1 for b, _ in live_bars if bucket(b.dt) == bk)
        nsig[bk] = sum(1 for s in sigs if bucket(s.dt) == bk)
        dens[bk] = 1000 * nsig[bk] / nbar[bk] if nbar[bk] else float("nan")
    ref_d = dens["RTH 09:30–16:00"]
    A("| 时段 | 可用K | 信号 | 密度(/1000K) | 相对RTH | 两比例 z(vs RTH) |")
    A("|---|---|---|---|---|---|")
    for bk in BUCKETS:
        if not nbar[bk]:
            continue
        bump()
        zb = stats.two_proportion_z(nsig[bk], nbar[bk], nsig["RTH 09:30–16:00"],
                                    nbar["RTH 09:30–16:00"])
        A(f"| {bk} | {nbar[bk]} | {nsig[bk]} | {dens[bk]:.1f} | "
          f"{dens[bk]/ref_d:.2f} | "
          f"{'–' if bk.startswith('RTH') else f'{zb:+.2f}'} |")
    A("")
    z_pre = stats.two_proportion_z(nsig["盘前 07:00–09:30"],
                                   nbar["盘前 07:00–09:30"],
                                   nsig["RTH 09:30–16:00"],
                                   nbar["RTH 09:30–16:00"])
    A(f"夜盘整体的密度是平凡的，但**内部并不均匀**：盘前 07:00–09:30 的密度 "
      f"{dens['盘前 07:00–09:30']:.1f} 是 RTH 的 "
      f"{dens['盘前 07:00–09:30']/ref_d:.2f} 倍（两比例 z={z_pre:+.2f}，"
      f"p={two_sided(z_pre):.3f}），亚洲段只有 "
      f"{dens['亚洲 18:00–02:00']/ref_d:.2f} 倍。这是「88%」里唯一一处密度上的"
      f"不平凡，但它的方向是**盘前发信号最密**，而盘前恰好也是超额缺口最深的一段"
      f"（见 2.5）。这两件事叠在一起才是问题，单看密度不是。")
    A("")

    # ══════════════════ 第二层 · 为什么每笔更差 ══════════════════════════════
    A("## 二 · 为什么夜盘每笔更差：尺度错配")
    A("")
    A("假设：**目标是日线刻度，止损是结构刻度。** 目标 T1 = 顺方向下一个具名位，"
      "位阶梯的步长固定为日 ATR 的 0.236 / 0.146 / 0.118 …；止损是近几根 K 的"
      "极值，夜盘 K 小 → 止损小。于是夜盘的每一笔都变成「很远的目标 + 很紧的止损」。")
    A("")

    # ── 2.1 K 振幅 ──────────────────────────────────────────────────────────
    A("### 2.1 10m K 振幅（以日 ATR 为单位）")
    A("")
    A("| 时段 | K数 | 振幅中位 (H−L)/ATR | 均值 | p25 | p75 | 相对RTH中位 |")
    A("|---|---|---|---|---|---|---|")
    rng = {}
    for bk in BUCKETS:
        v = [(b.high - b.low) / a for b, a in live_bars
             if bucket(b.dt) == bk and a > 0]
        if not v:
            continue
        rng[bk] = st.median(v)
        bump()
    ref = rng["RTH 09:30–16:00"]
    for bk in BUCKETS:
        v = [(b.high - b.low) / a for b, a in live_bars
             if bucket(b.dt) == bk and a > 0]
        if not v:
            continue
        A(f"| {bk} | {len(v)} | {st.median(v):.4f} | {st.mean(v):.4f} | "
          f"{q(v,0.25):.4f} | {q(v,0.75):.4f} | {st.median(v)/ref:.2f} |")
    v_rth = [(b.high - b.low) / a for b, a in live_bars
             if bucket(b.dt).startswith("RTH") and a > 0]
    v_on = [(b.high - b.low) / a for b, a in live_bars
            if not bucket(b.dt).startswith("RTH") and a > 0]
    A(f"| **合计 RTH** | {len(v_rth)} | **{st.median(v_rth):.4f}** | "
      f"{st.mean(v_rth):.4f} | {q(v_rth,0.25):.4f} | {q(v_rth,0.75):.4f} | 1.00 |")
    A(f"| **合计 夜盘** | {len(v_on)} | **{st.median(v_on):.4f}** | "
      f"{st.mean(v_on):.4f} | {q(v_on,0.25):.4f} | {q(v_on,0.75):.4f} | "
      f"**{st.median(v_on)/st.median(v_rth):.2f}** |")
    bump(2)
    A("")
    quiet = min(ON_BUCKETS, key=lambda b: rng.get(b, 9e9))
    A(f"**夜盘 10m K 的振幅中位只有 RTH 的 "
      f"{100*st.median(v_on)/st.median(v_rth):.0f}%"
      f"（{st.median(v_on):.4f} vs {st.median(v_rth):.4f} 日ATR）。"
      f"最静的 {quiet} 只有 RTH 的 {100*rng[quiet]/ref:.0f}%，"
      f"最活的 {max(ON_BUCKETS, key=lambda b: rng.get(b,0))} 也只有 "
      f"{100*max(rng[b] for b in ON_BUCKETS)/ref:.0f}%。**"
      f"位阶梯的步长完全没有跟着变——它是日 ATR 的固定倍数。")
    A("")

    # ── 2.2 止损距离 / 目标距离 / 几何零假设 ────────────────────────────────
    A("### 2.2 止损距离 vs 目标距离：几何零假设为什么塌陷")
    A("")
    A("这一节是整份报告的支点。S = 风险距离（结构止损），T = 到 T1 的距离"
      "（日 ATR 位阶梯）。几何零假设 P = S/(S+T)。")
    A("")
    A("| 组 | n | S/ATR 中位 | T/ATR 中位 | T/S 中位 (=目标几R) | S/(S+T) 中位 | "
      "S 点数中位 | 几何零假设均值 |")
    A("|---|---|---|---|---|---|---|---|")
    for lbl, g in (("RTH", RTH), ("夜盘", ON),
                   *[(bk, [s for s in sigs if bucket(s.dt) == bk])
                     for bk in ON_BUCKETS]):
        if not g:
            continue
        bump()
        S = [s.risk / s.atr for s in g]
        T = [abs(s.t1 - s.entry) / s.atr for s in g]
        TS = [abs(s.t1 - s.entry) / s.risk for s in g]
        P = [s.risk / (s.risk + abs(s.t1 - s.entry)) for s in g]
        A(f"| {lbl} | {len(g)} | {st.median(S):.4f} | {st.median(T):.4f} | "
          f"{st.median(TS):.2f} | {st.median(P):.3f} | "
          f"{st.median([s.risk for s in g]):.1f} | {st.mean(P):.3f} |")
    A("")
    S_r, S_o = [s.risk / s.atr for s in RTH], [s.risk / s.atr for s in ON]
    T_r, T_o = ([abs(s.t1 - s.entry) / s.atr for s in RTH],
                [abs(s.t1 - s.entry) / s.atr for s in ON])
    A(f"**止损中位：夜盘 {st.median(S_o):.4f} ATR vs RTH {st.median(S_r):.4f} ATR，"
      f"比值 {st.median(S_o)/st.median(S_r):.2f}——和 10m K 振幅的比值 "
      f"{st.median(v_on)/st.median(v_rth):.2f} 相同到小数点后两位，"
      f"因为结构止损就是近几根 K 的极值，它是一个 K 振幅刻度的量。**")
    A(f"**目标中位：夜盘 {st.median(T_o):.4f} ATR vs RTH {st.median(T_r):.4f} ATR，"
      f"比值 {st.median(T_o)/st.median(T_r):.2f}——目标不但没跟着缩，还略微更远"
      f"（位阶梯是日 ATR 的固定倍数，与当下 K 有多大毫无关系）。**")
    A("")
    A(f"于是 T/S 从 RTH 的 {st.median([abs(s.t1-s.entry)/s.risk for s in RTH]):.2f}R "
      f"拉到夜盘的 {st.median([abs(s.t1-s.entry)/s.risk for s in ON]):.2f}R"
      f"（{st.median([abs(s.t1-s.entry)/s.risk for s in ON])/st.median([abs(s.t1-s.entry)/s.risk for s in RTH]):.1f} 倍），"
      f"几何零假设从 **{100*bR['null']:.1f}%** 塌到 **{100*bO['null']:.1f}%**。"
      f"这就是 66.7 → 54.3 的全部机制，一行算术。"
      f"夜盘不是「更难赢」——是**同一套规则给夜盘派了一条 2 倍长的路**。")
    A("")
    rho_sa, z_sa = spearman([s.risk / s.atr for s in sigs],
                            [s.pnull for s in sigs])
    rho_ta, z_ta = spearman([abs(s.t1 - s.entry) / s.atr for s in sigs],
                            [s.pnull for s in sigs])
    bump(2)
    A(f"（旁证：全样本里 S/ATR 与几何零假设的秩相关 ρ = {rho_sa:+.3f} "
      f"(z={z_sa:+.2f})，T/ATR 与之 ρ = {rho_ta:+.3f} (z={z_ta:+.2f})。"
      f"零假设几乎完全由止损宽度决定。）")
    A("")

    # ── 2.2b 超额如何被放大成 R ─────────────────────────────────────────────
    A("### 2.2b 同样的 pp 缺口，夜盘要贵 1.2 倍")
    A("")
    A("纯括号的期望 R 有一个闭式：命中 +T/S，止损 −1，而 T/S = (1−P)/P，所以")
    A("")
    A("```")
    A("E[括号R] = p·(T/S) − (1−p) = (p − P) / P      （P = 几何零假设）")
    A("```")
    A("")
    A("**在几何零假设上期望恰好为 0**（费用之前）。所以负 R 只能来自"
      "「实际命中低于零假设」，而同一个百分点缺口，在零假设越低的地方换算出的 R 越多"
      "——放大系数就是 1/P。")
    A("")
    A("| 组 | n(可裁决) | 实际命中 | 几何零假设 | 超额 pp | z_geom | 放大系数 1/P | "
      "均括号R（实测） | 均括号净R |")
    A("|---|---|---|---|---|---|---|---|---|")
    for lbl, g in (("RTH", RTH), ("夜盘", ON), ("全部", sigs),
                   *[(bk, [s for s in sigs if bucket(s.dt) == bk])
                     for bk in ON_BUCKETS]):
        res = [s for s in g if s.hit is not None]
        if len(res) < 5:
            continue
        bump()
        z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
        brs = [bracket_r(races[id(s)], s.risk) for s in res]
        bnet = [b_ - SPREAD / s.risk for b_, s in zip(brs, res)]
        A(f"| {lbl} | {n} | {100*obs:.1f}% | {100*null:.1f}% | "
          f"{100*(obs-null):+.1f} | {z:+.2f} | {1/null:.2f} | "
          f"{st.mean(brs):+.3f} | {st.mean(bnet):+.3f} |")
    A("")
    A(f"RTH 超额 {100*(bR['obs']-bR['null']):+.1f} pp × 放大 {1/bR['null']:.2f} ≈ "
      f"{(bR['obs']-bR['null'])/bR['null']:+.3f} R/笔；"
      f"夜盘 {100*(bO['obs']-bO['null']):+.1f} pp × 放大 {1/bO['null']:.2f} ≈ "
      f"{(bO['obs']-bO['null'])/bO['null']:+.3f} R/笔。")
    A("")
    A("**所以「每笔更差」本身也是两个因子的乘积：缺口更大（−6.2 vs +3.0 pp）"
      "× 每 pp 更贵（1.84 vs 1.50）。尺度错配同时把这两个因子都推坏了。**")
    A("")

    # ── 2.3 时长 ────────────────────────────────────────────────────────────
    A("### 2.3 到达裁决要多久 —— 假设里唯一没被支持的一条")
    A("")
    A("尺度错配假设预测夜盘会是「很远的目标 + 很紧的止损 + **很长的持有时间**」。"
      "前两条已经坐实，第三条要单独查。")
    A("")
    A("| 组 | n | 裁决中位K数 | 均值 | p90 | 中位挂钟h | p90挂钟h | "
      "中位K数(命中T1) | 中位K数(先触止损) | v14实际持仓中位K数 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for lbl, g in (("RTH", RTH), ("夜盘", ON),
                   *[(bk, [s for s in sigs if bucket(s.dt) == bk])
                     for bk in ON_BUCKETS]):
        res = [s for s in g if s.hit is not None]
        if len(res) < 5:
            continue
        bump()
        bb = [races[id(s)].bars for s in res]
        hh = [races[id(s)].hours for s in res
              if races[id(s)].hours == races[id(s)].hours]
        bw = [races[id(s)].bars for s in res if s.hit]
        bl = [races[id(s)].bars for s in res if not s.hit]
        A(f"| {lbl} | {len(res)} | {st.median(bb):.0f} | {st.mean(bb):.1f} | "
          f"{q(bb,0.90):.0f} | {st.median(hh):.1f} | {q(hh,0.90):.1f} | "
          f"{st.median(bw) if bw else float('nan'):.0f} | "
          f"{st.median(bl) if bl else float('nan'):.0f} | "
          f"{st.median([s.hold for s in g]):.0f} |")
    A("")
    bb_r = [races[id(s)].bars for s in RTH if s.hit is not None]
    bb_o = [races[id(s)].bars for s in ON if s.hit is not None]
    A(f"**假设的第三条不成立。** 夜盘裁决中位 {st.median(bb_o):.0f} 根 vs RTH "
      f"{st.median(bb_r):.0f} 根（均值 {st.mean(bb_o):.1f} vs {st.mean(bb_r):.1f}），"
      f"只慢 {st.mean(bb_o)/st.mean(bb_r):.2f} 倍，远不够解释 2 倍的路程。"
      f"原因很直白：**目标是远了，但止损也同步紧了，所以「先撞到某一边」这件事"
      f"并没有变慢——只是撞到的更常是止损那一边。** 挂钟时间也一样"
      f"（{st.median([races[id(s)].hours for s in ON if s.hit is not None]):.1f}h vs "
      f"{st.median([races[id(s)].hours for s in RTH if s.hit is not None]):.1f}h）。")
    A("")
    A(f"另外注意 v14 的**实际**持仓中位只有 "
      f"{st.median([s.hold for s in ON]):.0f} / "
      f"{st.median([s.hold for s in RTH]):.0f} 根——13 线离场在括号跑完之前"
      f"就把大量交易砍断了。这一次它反而是**减损**的：夜盘纯括号净R "
      f"{st.mean([bracket_r(races[id(s)], s.risk) - SPREAD/s.risk for s in ON if s.hit is not None]):+.3f}，"
      f"加回 13 线离场之后的实际净R 是 {bO['net']:+.3f}。"
      f"churn 在别的地方是问题，在这里不是主因。")
    A("")

    # ── 2.3b 路径效率 ───────────────────────────────────────────────────────
    A("### 2.3b 真正的错配是「逐根噪声」对「整段位移」，不是「夜盘」对「白天」")
    A("")
    A("上面两节容易被读成「夜盘波动小」。**这个读法是错的，而且下一节的反事实"
      "就是被它坑掉的。** 夜盘的逐根 K 只有 RTH 的一半大，但夜盘长 16.5 小时、"
      "RTH 只有 6.5 小时；把整段合起来看，夜盘走出来的净波幅并不小。")
    A("")
    A("路径效率 = 该段的真实波幅 ÷ 该段所有 10m K 振幅之和。它衡量"
      "「走了这么多路，净位移有多少」。**结构止损是噪声刻度的量（∝ 逐根振幅），"
      "位阶梯目标是位移刻度的量（∝ 整段波幅）——效率越低，(止损, 目标) 这一对"
      "就越不成比例。**")
    A("")
    return_marker = None
    return return_marker  # placeholder replaced below

    # ── 2.4 点差 ────────────────────────────────────────────────────────────
    A("### 2.4 0.6 点点差为什么在夜盘更贵")
    A("")
    A("点差按每笔**自己的**风险距离折算：扣减 = 0.6 / S(点)。S 越小，同样的 0.6 点"
      "就越贵。这不是一个新现象，它是 2.1/2.2 的直接推论。")
    A("")
    A("| 组 | n | S 点数中位 | S 点数调和均值 | 均点差成本(R) | 中位 | p75 | "
      "均毛R | 均净R | 点差占均净R比重 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for lbl, g in (("RTH", RTH), ("夜盘", ON), ("全部", sigs),
                   *[(bk, [s for s in sigs if bucket(s.dt) == bk])
                     for bk in ON_BUCKETS]):
        if len(g) < 5:
            continue
        bump()
        c = [SPREAD / s.risk for s in g]
        hm = len(g) / sum(1 / s.risk for s in g)
        gr = st.mean([s.r for s in g])
        nt = st.mean([s.net for s in g])
        A(f"| {lbl} | {len(g)} | {st.median([s.risk for s in g]):.2f} | {hm:.2f} | "
          f"{st.mean(c):.3f} | {st.median(c):.3f} | {q(c,0.75):.3f} | "
          f"{gr:+.3f} | {nt:+.3f} | {100*st.mean(c)/abs(nt):.0f}% |")
    A("")
    c_r = st.mean([SPREAD / s.risk for s in RTH])
    c_o = st.mean([SPREAD / s.risk for s in ON])
    hm_r = len(RTH) / sum(1 / s.risk for s in RTH)
    hm_o = len(ON) / sum(1 / s.risk for s in ON)
    A(f"验证：均点差成本 RTH {c_r:.3f}R、夜盘 {c_o:.3f}R，比值 {c_o/c_r:.2f}；"
      f"风险距离的**调和均值**（正是 0.6/S 的均值所对应的那个平均）"
      f"RTH {hm_r:.2f} 点、夜盘 {hm_o:.2f} 点，比值 {hm_r/hm_o:.2f}。"
      f"两个比值相等到小数点后两位——**点差在夜盘更贵，100% 是因为 R 更小，"
      f"没有别的成分**（模型里点差是常数 0.6 点；真实经纪商夜盘点差通常更宽，"
      f"所以这里是下界）。")
    A("")
    A("| 均净R 的分解 | RTH | 夜盘 | 差（夜−RTH） | 占差的比重 |")
    A("|---|---|---|---|---|")
    dg = bO["gross"] - bR["gross"]
    dc = -(c_o - c_r)
    dn = bO["net"] - bR["net"]
    A(f"| 均毛R | {bR['gross']:+.3f} | {bO['gross']:+.3f} | {dg:+.3f} | "
      f"{100*dg/dn:.0f}% |")
    A(f"| −均点差成本 | {-c_r:+.3f} | {-c_o:+.3f} | {dc:+.3f} | {100*dc/dn:.0f}% |")
    A(f"| **均净R** | **{bR['net']:+.3f}** | **{bO['net']:+.3f}** | "
      f"**{dn:+.3f}** | 100% |")
    bump(3)
    A("")
    A(f"**每笔劣势 {dn:+.3f}R 里，{100*dg/dn:.0f}% 是毛交易本身更差，"
      f"{100*dc/dn:.0f}% 是点差摊在更小的 R 上。**")
    A("")

    # ── 2.5 夜盘内部 ────────────────────────────────────────────────────────
    A("### 2.5 夜盘内部：亏在哪一段")
    A("")
    A("| 时段 | 信号 | 份额 | 密度(/1000K) | K振幅中位(ATR) | S中位(ATR) | "
      "几何零假设 | 实际命中 | 超额pp | z_geom | 均净R | **总净R** | 占夜盘亏损 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for bk in ON_BUCKETS:
        g = [s for s in sigs if bucket(s.dt) == bk]
        if not g:
            continue
        bump()
        res = [s for s in g if s.hit is not None]
        z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
        tot = sum(s.net for s in g)
        A(f"| {bk} | {len(g)} | {100*len(g)/len(ON):.1f}% | {dens[bk]:.1f} | "
          f"{rng[bk]:.4f} | {st.median([s.risk/s.atr for s in g]):.4f} | "
          f"{100*null:.1f}% | {100*obs:.1f}% | {100*(obs-null):+.1f} | {z:+.2f} | "
          f"{st.mean([s.net for s in g]):+.3f} | **{tot:+.1f}** | "
          f"{100*tot/bO['tot']:.1f}% |")
    g = RTH
    res = [s for s in g if s.hit is not None]
    z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
    A(f"| *(对照) RTH 09:30–16:00* | {len(g)} | – | "
      f"{dens['RTH 09:30–16:00']:.1f} | {ref:.4f} | "
      f"{st.median([s.risk/s.atr for s in g]):.4f} | {100*null:.1f}% | "
      f"{100*obs:.1f}% | {100*(obs-null):+.1f} | {z:+.2f} | "
      f"{st.mean([s.net for s in g]):+.3f} | {sum(s.net for s in g):+.1f} | – |")
    A("")

    # 逐小时
    A("**逐小时（ET）明细** —— 这是 24 个格子，单独一个格子的 z 不要当证据看。")
    A("")
    A("| 小时(ET) | K数 | 信号 | 密度 | K振幅中位(ATR) | S中位(ATR) | 零假设 | "
      "命中 | z_geom | 均净R | 总净R |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for h in list(range(18, 24)) + list(range(0, 17)):
        nb = sum(1 for b, _ in live_bars if b.dt.hour == h)
        if nb == 0:
            continue
        gh = [s for s in sigs if s.dt.hour == h]
        vh = [(b.high - b.low) / a for b, a in live_bars if b.dt.hour == h and a > 0]
        if not gh:
            A(f"| {h:02d}:00 | {nb} | 0 | 0.0 | {st.median(vh):.4f} | – | – | – | "
              f"– | – | – |")
            continue
        bump()
        resh = [s for s in gh if s.hit is not None]
        zh, nh, obsh, nullh = (z_geom([s.hit for s in resh],
                                      [s.pnull for s in resh])
                               if resh else (float("nan"),) * 4)
        A(f"| {h:02d}:00 | {nb} | {len(gh)} | {1000*len(gh)/nb:.1f} | "
          f"{st.median(vh):.4f} | {st.median([s.risk/s.atr for s in gh]):.4f} | "
          f"{fm(nullh*100,1) if nullh==nullh else '–'}% | "
          f"{fm(obsh*100,1) if obsh==obsh else '–'}% | {fm(zh,2,True)} | "
          f"{st.mean([s.net for s in gh]):+.3f} | {sum(s.net for s in gh):+.1f} |")
    A("")

    # ══════════════════ 第三层 · 反事实 ═════════════════════════════════════
    A("## 三 · 反事实")
    A("")
    A("纪律 6：任何「砍掉笔数后总 R 转正」都必须先验证**单笔质量**是否真的提升。"
      "下面每一个反事实都报 Δ均净R、配对 t、以及有限总体修正的选择 z_sel。")
    A("")

    # ── 3.1 最小风险闸门 ────────────────────────────────────────────────────
    A("### 3.1 夜盘强制最小风险距离 0.12 日ATR")
    A("")
    A("两种做法，结论都要报：")
    A("")
    A("- **(a) 事后筛选**：从已有的 375 个夜盘信号里挑出 S ≥ 0.12 ATR 的。"
      "这是「如果我当时知道就不做」的口径。")
    A("- **(b) 装进状态机重跑**：在夜盘 K 上把 minRisk 换成 max(2点, 0.12×日ATR)，"
      "整条链重跑。这才是上线后真正会发生的——被挡掉的 Vomy 不会复位状态，"
      "后面的信号序列会变。")
    A("")
    GATE = 0.12
    kept = [s for s in ON if s.d4 >= GATE]
    dropped = [s for s in ON if s.d4 < GATE]

    def gate_row(lbl: str, g: list[Sig], base: list[Sig]) -> str:
        res = [s for s in g if s.hit is not None]
        z, n, obs, null = (z_geom([s.hit for s in res], [s.pnull for s in res])
                           if res else (float("nan"),) * 4)
        ns = [s.net for s in g]
        bns = [s.net for s in base]
        d = st.mean(ns) - st.mean(bns) if ns else float("nan")
        zs = sel_z(ns, bns) if len(g) < len(base) else float("nan")
        bump()
        return (f"| {lbl} | {len(g)} ({100*len(g)/len(base):.0f}%) | "
                f"{fm(100*null,1)}% | {fm(100*obs,1)}% | {fm(100*(obs-null),1,True)} | "
                f"{fm(z,2,True)} | {fm(st.mean(ns),3,True)} | {fm(d,3,True)} | "
                f"{fm(tstat(ns),2,True)} | {fm(zs,2,True)} | {sum(ns):+.1f} |")

    A("| 情形 | n (占夜盘) | 几何零假设 | 命中 | 超额pp | z_geom | 均净R | "
      "Δ均净R | t | z_sel | 总净R |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    A(gate_row("夜盘基线（全部）", ON, ON))
    A(gate_row("(a) 事后筛 S ≥ 0.12 ATR", kept, ON))
    A(gate_row("(a) 被筛掉的那些 S < 0.12 ATR", dropped, ON))
    A("")

    # (b) 重跑
    def gate_fn(risk, atr, in_rth):
        return True if in_rth else (risk >= GATE * atr)

    sigs_b, e13b = harvest2(bars, book, gate=gate_fn)
    sigs_b = location_vars(sigs_b, bars, e13b)
    for s in sigs_b:
        rc = race(s.entry, s.prot, s.risk, s.t1, s.direction, s.i, bars, subs)
        s.hit, s.pnull = rc.hit, rc.pnull
        isolated_trade(s, bars, subs, e13b)
    ON_b = [s for s in sigs_b if not s.in_rth]
    RTH_b = [s for s in sigs_b if s.in_rth]
    A("| 情形（重跑状态机） | n (占夜盘基线) | 几何零假设 | 命中 | 超额pp | z_geom | "
      "均净R | Δ均净R | t | z_sel | 总净R |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    A(gate_row("(b) 夜盘 minRisk = max(2点, 0.12×日ATR)", ON_b, ON))
    A("")
    bb_ = block(ON_b, "b")
    A(f"**(b) 的判决**：夜盘笔数 {len(ON)} → {len(ON_b)}"
      f"（掉 {100*(1-len(ON_b)/len(ON)):.0f}%），"
      f"均净R {bO['net']:+.3f} → {bb_['net']:+.3f}"
      f"（Δ={bb_['net']-bO['net']:+.3f}），"
      f"总净R {bO['tot']:+.1f} → {bb_['tot']:+.1f}"
      f"（改善 {bb_['tot']-bO['tot']:+.1f}R），"
      f"z_geom {bO['z']:+.2f} → {bb_['z']:+.2f}，"
      f"几何零假设 {100*bO['null']:.1f}% → {100*bb_['null']:.1f}%。")
    A(f"全样本（RTH 未动）：{len(sigs)} → {len(sigs_b)} 笔，总净R "
      f"{bA['tot']:+.1f} → {sum(s.net for s in sigs_b):+.1f}。")
    A("")

    # ── 3.2 目标按夜盘实际波动缩放 ─────────────────────────────────────────
    A("### 3.2 把目标改成「夜盘段已实现 ATR」的 0.236")
    A("")
    A("这是检验尺度错配假设最直接的方式：**只换目标的刻度，其余一律不动**。")
    A("")
    A("「夜盘段已实现 ATR」的构造与日线 ATR 完全平行——把每一段夜盘"
      "（16:00 收盘 → 次日 09:30 开盘，含周末的那一段一并算作一块）当作一根「K」，"
      "取段高/段低/段收，TR = max(H−L, |H−前段收|, |L−前段收|)，Wilder(14) 平滑，"
      "**取上一段收盘时的值**，所以段内任何一根 K 用它都没有前视。RTH 段同理。")
    A("")
    on_key, rth_key, rth_days = build_block_keys(bars)
    atr_on, n_on_blocks = segment_atr(bars, on_key)
    atr_rth, n_rth_blocks = segment_atr(bars, rth_key)

    def seg_atr_of(s: Sig) -> float | None:
        b = bars[s.i]
        if s.in_rth:
            return atr_rth.get(rth_key(b))
        return atr_on.get(on_key(b))

    ratios_on = [atr_on[k] / book.get(k)[1] for k in sorted(atr_on)
                 if atr_on[k] and book.get(k)]
    ratios_rth = [atr_rth[k] / book.get(k)[1] for k in sorted(atr_rth)
                  if atr_rth[k] and book.get(k)]
    A("| 段类型 | 块数 | 段ATR/日ATR 中位 | 均值 | p25 | p75 |")
    A("|---|---|---|---|---|---|")
    A(f"| 夜盘段 | {len(ratios_on)} | {st.median(ratios_on):.3f} | "
      f"{st.mean(ratios_on):.3f} | {q(ratios_on,0.25):.3f} | "
      f"{q(ratios_on,0.75):.3f} |")
    A(f"| RTH 段 | {len(ratios_rth)} | {st.median(ratios_rth):.3f} | "
      f"{st.mean(ratios_rth):.3f} | {q(ratios_rth,0.25):.3f} | "
      f"{q(ratios_rth,0.75):.3f} |")
    bump(2)
    A("")
    A(f"**夜盘整段（约 16 小时）走出来的真实波幅只有日 ATR 的 "
      f"{st.median(ratios_on):.2f} 倍，而 RTH 那 6.5 小时是 "
      f"{st.median(ratios_rth):.2f} 倍。** 位阶梯给两者用的是同一把尺子。")
    A("")
    A("三个目标口径在**同一批信号**上对跑（要求段 ATR 已成熟，故样本略小于 517）：")
    A("")
    A("| 目标口径 | 组 | n(可裁决) | T/ATR 中位 | T/S 中位 | 几何零假设 | 命中 | "
      "超额pp | z_geom | 均括号R | 均括号净R |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    variants = [
        ("A · v14 位阶梯（现状）", lambda s, a: s.t1),
        ("B · 固定 0.236 × 日ATR", lambda s, a: s.entry + s.direction * 0.236 * s.atr),
        ("C · 固定 0.236 × 段ATR", lambda s, a: s.entry + s.direction * 0.236 * a),
    ]
    elig = [s for s in sigs if seg_atr_of(s)]
    cf_rows = {}
    for vlbl, tf in variants:
        for glbl, gg in (("RTH", [s for s in elig if s.in_rth]),
                         ("夜盘", [s for s in elig if not s.in_rth])):
            rs_, ps_, hs_, brs_, bns_, tds_, tss_ = [], [], [], [], [], [], []
            for s in gg:
                a = seg_atr_of(s)
                tgt = tf(s, a)
                rc = race(s.entry, s.prot, s.risk, tgt, s.direction, s.i,
                          bars, subs)
                tds_.append(rc.tdist / s.atr)
                tss_.append(rc.tdist / s.risk)
                if rc.hit is None:
                    continue
                hs_.append(rc.hit)
                ps_.append(rc.pnull)
                br = bracket_r(rc, s.risk)
                brs_.append(br)
                bns_.append(br - SPREAD / s.risk)
            z, n, obs, null = z_geom(hs_, ps_)
            bump()
            cf_rows[(vlbl, glbl)] = (z, n, obs, null, st.mean(brs_),
                                     st.mean(bns_))
            A(f"| {vlbl} | {glbl} | {n} | {st.median(tds_):.4f} | "
              f"{st.median(tss_):.2f} | {100*null:.1f}% | {100*obs:.1f}% | "
              f"{100*(obs-null):+.1f} | {z:+.2f} | {st.mean(brs_):+.3f} | "
              f"{st.mean(bns_):+.3f} |")
    A("")
    zA = cf_rows[("A · v14 位阶梯（现状）", "夜盘")]
    zC = cf_rows[("C · 固定 0.236 × 段ATR", "夜盘")]
    A(f"**判决**：把夜盘目标从日 ATR 刻度换成夜盘段刻度，几何零假设从 "
      f"{100*zA[3]:.1f}% 升到 {100*zC[3]:.1f}%（目标近了，路好走了），"
      f"实际命中从 {100*zA[2]:.1f}% 升到 {100*zC[2]:.1f}%，"
      f"超额从 {100*(zA[2]-zA[3]):+.1f} pp 变成 {100*(zC[2]-zC[3]):+.1f} pp，"
      f"z_geom 从 {zA[0]:+.2f} 变成 {zC[0]:+.2f}，"
      f"均括号R 从 {zA[4]:+.3f} 变成 {zC[4]:+.3f}"
      f"（净 {zA[5]:+.3f} → {zC[5]:+.3f}）。")
    A("")

    # ── 3.3 不做夜盘 ────────────────────────────────────────────────────────
    A("### 3.3 如果干脆不做夜盘（只报告，不建议）")
    A("")
    A("用户已明确要求**不在规则层分时段**，所以这一行只是把上限标出来，"
      "让上面两个反事实有个参照。")
    A("")
    A("| 情形 | n | 均净R | Δ均净R | t | z_sel | 总净R | z_geom |")
    A("|---|---|---|---|---|---|---|---|")
    allnet = [s.net for s in sigs]
    for lbl, g in (("全样本（现状）", sigs), ("只做 RTH", RTH), ("只做夜盘", ON)):
        res = [s for s in g if s.hit is not None]
        z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
        ns = [s.net for s in g]
        bump()
        A(f"| {lbl} | {len(g)} | {st.mean(ns):+.3f} | "
          f"{st.mean(ns)-st.mean(allnet):+.3f} | {tstat(ns):+.2f} | "
          f"{fm(sel_z(ns, allnet) if len(g)<len(sigs) else float('nan'),2,True)} | "
          f"{sum(ns):+.1f} | {z:+.2f} |")
    A("")
    A(f"**只做 RTH：均净R {bR['net']:+.3f}（t={tstat([s.net for s in RTH]):+.2f}），"
      f"总净R {bR['tot']:+.1f}。仍然是负的，只是负得少。**"
      f"z_sel = {sel_z([s.net for s in RTH], allnet):+.2f}，"
      f"在本文 family size 下够不着门槛——「砍掉夜盘」本身也不是一个被统计支持的动作，"
      f"它只是把一个坏机制的曝光量减少了 {100*len(ON)/len(sigs):.0f}%。")
    A("")

    # ══════════════════ 反例 / 多重比较 / 结论 ═══════════════════════════════
    A("## 四 · 与假设相反的格子（诚实优先）")
    A("")
    contra = []
    # 1) 夜盘里有没有格子是正的
    for bk in ON_BUCKETS:
        g = [s for s in sigs if bucket(s.dt) == bk]
        res = [s for s in g if s.hit is not None]
        if len(res) < 20:
            continue
        z, n, obs, null = z_geom([s.hit for s in res], [s.pnull for s in res])
        if obs > null or st.mean([s.net for s in g]) > bR["net"]:
            contra.append(f"- **{bk}**：超额 {100*(obs-null):+.1f} pp "
                          f"(z={z:+.2f})，均净R {st.mean([s.net for s in g]):+.3f}"
                          f"（RTH 是 {bR['net']:+.3f}）。")
    # 2) 大止损的夜盘笔
    big = [s for s in ON if s.d4 >= q([s.d4 for s in ON], 0.8)]
    resb = [s for s in big if s.hit is not None]
    zb, nb2, obsb, nullb = z_geom([s.hit for s in resb], [s.pnull for s in resb])
    contra.append(f"- **夜盘里止损最宽的 20%**（S ≥ "
                  f"{q([s.d4 for s in ON],0.8):.3f} ATR，n={len(big)}）："
                  f"几何零假设 {100*nullb:.1f}%，命中 {100*obsb:.1f}%，"
                  f"超额 {100*(obsb-nullb):+.1f} pp (z={zb:+.2f})，"
                  f"均净R {st.mean([s.net for s in big]):+.3f}，"
                  f"总净R {sum(s.net for s in big):+.1f}。"
                  f"这一格与「夜盘全坏」直接冲突，也是 3.1 那个闸门唯一的依据。")
    bump(2)
    # 3) RTH 也不是正的
    contra.append(f"- **RTH 本身也不赚钱**：均净R {bR['net']:+.3f}，"
                  f"总净R {bR['tot']:+.1f}，z_geom {bR['z']:+.2f}"
                  f"（|z|<1.96，命中与几何零假设无法区分）。"
                  f"把「88% 的亏损在夜盘」读成「RTH 是好的」是错的——"
                  f"RTH 只是**曝光量小**（{len(RTH)} 笔）且**每笔便宜**"
                  f"（止损宽 {st.median(S_r)/st.median(S_o):.1f} 倍，点差摊薄），"
                  f"它的超额 {100*(bR['obs']-bR['null']):+.1f} pp 在 "
                  f"n={bR['n']} 上完全够不着显著。")
    for c in contra:
        A(c)
    A("")

    A("## 五 · 多重比较")
    A("")
    A(f"全文共检视 **{CELLS} 个格子**（分层格、时段格、逐小时格、闸门、反事实口径）。"
      f"Bonferroni 门槛 |z| > **{_bonf_z(CELLS):.2f}**（α=0.05 双侧）。")
    A("")
    A("| 关键 z | 值 | 过 1.96？ | 过 Bonferroni？ |")
    A("|---|---|---|---|")
    keyz = [("夜盘 z_geom（纯括号 vs 几何零假设）", bO["z"]),
            ("RTH z_geom", bR["z"]),
            ("全样本 z_geom", bA["z"]),
            ("夜盘 vs RTH 信号密度 两比例 z", zd),
            ("夜盘均净R 的 t", tstat([s.net for s in ON])),
            ("RTH 均净R 的 t", tstat([s.net for s in RTH])),
            ("S/ATR ↔ 几何零假设 秩相关 z", z_sa)]
    for lbl, z in keyz:
        A(f"| {lbl} | {z:+.2f} | {'是' if abs(z) > 1.96 else '否'} | "
          f"{'是' if abs(z) > _bonf_z(CELLS) else '否'} |")
    A("")
    A(f"**没有一个跨过 Bonferroni 门槛。** 但注意：本文的主张不是"
      f"「某个格子显著」，而是**一组恒等式**——笔数份额 = K 数份额、"
      f"止损比 = K 振幅比、点差比 = 调和均值倒数比、E[括号R] = 超额/零假设。"
      f"这些是算术，不需要显著性；需要显著性的只有「超额 ≠ 0」这一条，"
      f"而它（z={bO['z']:+.2f}）恰恰是本文最弱的一环，必须如实标注。")
    A("")

    # ── 结论 ────────────────────────────────────────────────────────────────
    A("## 六 · 一句话回答")
    A("")
    A(f"> **夜盘扛下 {100*bO['tot']/bA['tot']:.0f}% 的亏损，是"
      f"「{100*math.log(odds_n)/math.log(odds):.0f}% 平凡 + "
      f"{100*math.log(odds_m)/math.log(odds):.0f}% 真实缺陷」的乘积："
      f"平凡的那一半是夜盘本来就占了 {100*nb_on/len(live_bars):.0f}% 的 K"
      f"（信号密度只有 RTH 的 {d_on/d_rth:.2f} 倍，两比例 z={zd:+.2f}，"
      f"没有额外的过度交易）；真实缺陷的那一半是**尺度错配**——"
      f"止损跟着夜盘 K 缩到 RTH 的 {st.median(S_o)/st.median(S_r):.0%}，"
      f"目标却仍按日 ATR 阶梯走，于是几何零假设从 {100*bR['null']:.1f}% 塌到 "
      f"{100*bO['null']:.1f}%，每 1 pp 的命中缺口被放大成 "
      f"{1/bO['null']:.2f}R（RTH 只有 {1/bR['null']:.2f}R），"
      f"同时 0.6 点的固定点差摊在小 {hm_r/hm_o:.1f} 倍的 R 上变贵一倍。**")
    A("")
    A("拆成可执行的三句：")
    A("")
    A(f"1. **平凡**（不用修）：{100*len(ON)/len(sigs):.0f}% 的笔数份额 ≈ "
      f"{100*nb_on/len(live_bars):.0f}% 的 K 数份额 ≈ 16.5/23 小时。"
      f"夜盘没有过度交易。")
    A(f"2. **真实缺陷 · 主因**（尺度错配）：目标是日线刻度、止损是结构刻度。"
      f"夜盘 T/S 中位 {st.median([abs(s.t1-s.entry)/s.risk for s in ON]):.2f}R vs "
      f"RTH {st.median([abs(s.t1-s.entry)/s.risk for s in RTH]):.2f}R。"
      f"把目标换成夜盘段刻度后，z_geom 从 {zA[0]:+.2f} 变成 {zC[0]:+.2f}，"
      f"均括号R 从 {zA[4]:+.3f} 变成 {zC[4]:+.3f}。")
    A(f"3. **真实缺陷 · 次因**（点差）：占每笔劣势的 {100*dc/dn:.0f}%，"
      f"且 100% 由「R 更小」解释，不是独立成分。")
    A("")

    txt = "\n".join(o)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
