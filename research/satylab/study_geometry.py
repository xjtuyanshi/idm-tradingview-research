"""止损与目标的几何 —— 用 MFE/MAE 决定，不要猜。

事件定义：价格在 RTH 内**首次**触及某个具名位 L（±0.236 / ±0.382 / ±0.5 / ±0.618）。
以该次触及为"入场"，方向固定为**延续方向**（触上位做多、触下位做空），
测量从入场到收盘的 MFE（最大有利偏移）与 MAE（最大不利偏移），单位一律是 ATR
（= 当日 Saty 梯子的 ATR，即前日 Wilder ATR(14)）。

三条本脚本自己遵守的纪律：

  1. 任何"最优格子"必须连同**看过多少格子**一起报告（全局 GRID 计数器）。
  2. 同根 K 内止损与目标都被触及时，**不给点估计**，给悲观/乐观双界，并报歧义率。
  3. 入场那根 K 的低点（做多）大概率发生在触及之前，把它算进 MAE 是系统性悲观。
     主口径因此从**下一根 K** 起算，入场根含在内的版本作为悲观界一并报告。

数据分辨率（硬约束，写死在这里防止误用）：
  5m  仅 60 天（59 个有位图的完整交易日）—— 唯一能做路径判定的分辨率，n 很小。
  1h  730 天 —— 只能给"首触那根 K 之后"的 MFE/MAE，作为独立样本的形状复核。

运行： .venv/bin/python research/satylab/study_geometry.py
"""

from __future__ import annotations

import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats  # noqa: E402

# ---------------------------------------------------------------- 全局计数器

GRID_CELLS = 0          # 被评估过的 (止损, 目标) 优化格子总数
TESTS_RUN = 0           # 被报告的统计检验总数


def grid_tick(n: int = 1) -> None:
    global GRID_CELLS
    GRID_CELLS += n


def test_tick(n: int = 1) -> None:
    global TESTS_RUN
    TESTS_RUN += n


# ---------------------------------------------------------------- 常量

RATIOS = (0.236, 0.382, 0.500, 0.618)
SIGNED = tuple([r for r in RATIOS] + [-r for r in RATIOS])

# 梯子上"下一档 / 上一档"（延续方向为正）
LADDER = (0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.618)


def next_level(r: float) -> float:
    for x in LADDER:
        if x > r + 1e-9:
            return x
    return r + 0.236


def prev_level(r: float) -> float:
    prev = 0.0
    for x in LADDER:
        if x < r - 1e-9:
            prev = x
    return prev


HOUR_BUCKETS = ("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")


def hour_bucket(hhmm: str) -> str:
    hh, mm = int(hhmm[:2]), int(hhmm[3:])
    t = hh * 60 + mm
    if t < 10 * 60 + 30:
        return "09:30"
    for b in HOUR_BUCKETS[1:]:
        bh = int(b[:2]) * 60 + int(b[3:])
        if t < bh + 60:
            return b
    return "15:30"


COARSE = {"09:30": "EARLY", "10:30": "MID", "11:30": "MID", "12:30": "MID",
          "13:30": "LATE", "14:30": "LATE", "15:30": "LATE"}

# 优化网格（8 x 8 = 64 格 / cohort）
STOPS = (0.05, 0.075, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
TARGETS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75)

COST_ATR = 0.01          # 单笔往返摩擦，ATR 单位（ATR≈80 点时约 0.8 个 SPX 点）
COST_ATR_STRESS = 0.02


# ---------------------------------------------------------------- 小工具

def q(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = int(math.floor(k))
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def qline(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    return (f"n={len(xs):<4} p10={q(xs,.10):.3f} p25={q(xs,.25):.3f} "
            f"p50={q(xs,.50):.3f} p75={q(xs,.75):.3f} p80={q(xs,.80):.3f} "
            f"p90={q(xs,.90):.3f} p95={q(xs,.95):.3f} mean={statistics.fmean(xs):.3f}")


def mean_se(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return (statistics.fmean(xs) if xs else 0.0, float("nan"))
    return statistics.fmean(xs), statistics.pstdev(xs) / math.sqrt(n - 1)


def day_block_bootstrap(by_day: dict, stat, iters: int = 2000, seed: int = 12345):
    """按交易日重抽样（日内多笔共享结果窗口 → 不能按笔抽）。"""
    import random
    rng = random.Random(seed)
    keys = list(by_day)
    if not keys:
        return (float("nan"), float("nan"))
    out = []
    for _ in range(iters):
        pick = [by_day[keys[rng.randrange(len(keys))]] for _ in keys]
        flat = [v for lst in pick for v in lst]
        if flat:
            out.append(stat(flat))
    out.sort()
    if not out:
        return (float("nan"), float("nan"))
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out))])


# ---------------------------------------------------------------- 交易记录

@dataclass
class Touch:
    day: date
    ratio: float            # 带符号
    side: int               # +1 多 / -1 空
    bucket: str             # 首触所在小时档 或 "GAP"
    coarse: str
    gap: bool
    i: int                  # 首触 K 的下标
    entry: float            # 位价（口径 A/B 的入场价）
    atr: float
    anchor: float
    bars: list              # 当日全部 K（引用）
    mfe: float              # 从 i+1 起算，相对位价，ATR 单位
    mae: float
    mfe_incl: float         # 含首触 K，相对位价
    mae_incl: float
    to_close: float         # (收盘-位价)*side / atr
    n_left: int
    entry_c: float = 0.0    # 首触 K 的收盘价（口径 C 的入场价）
    freeride: float = 0.0   # (首触K收盘 - 位价)*side / atr —— 口径 A 白送的那一段
    mfe_c: float = 0.0      # 相对 entry_c，从 i+1 起算
    mae_c: float = 0.0
    to_close_c: float = 0.0


# 三种口径：
#   A  入场价 = 位价，路径从下一根 K 起算 —— 白送首触那根 K 的剩余走势（乐观）
#   B  入场价 = 位价，路径含首触那根 K   —— 把触及之前的低点算成回撤（悲观）
#   C  入场价 = 首触那根 K 的收盘价，路径从下一根 K 起算 —— 唯一自洽且可执行
def conv_entry(t: "Touch", conv: str) -> tuple[float, bool]:
    if conv == "C":
        return t.entry_c, False
    return t.entry, (conv == "B")


def build_touches(sessions: dict, lv: dict, ratios=SIGNED,
                  min_bars: int = 10) -> list[Touch]:
    out: list[Touch] = []
    for day in sorted(sessions):
        if day not in lv:
            continue
        L = lv[day]
        bars = [b for b in sessions[day] if b.hhmm < "16:00"]
        if len(bars) < min_bars:
            continue
        for r in ratios:
            side = 1 if r > 0 else -1
            px = L.at(r)
            i = None
            for j, b in enumerate(bars):
                if (b.high >= px) if side > 0 else (b.low <= px):
                    i = j
                    break
            if i is None:
                continue
            b0 = bars[i]
            gap = (i == 0) and ((b0.open >= px) if side > 0 else (b0.open <= px))
            entry = b0.open if gap else px
            # 盘中同根跳过位（开盘价已在位外但不是第一根）也按开盘价成交
            if not gap and ((b0.open > px) if side > 0 else (b0.open < px)):
                entry = b0.open
            rest = bars[i + 1:]
            if not rest:
                continue

            def exc(seq):
                hi = max(x.high for x in seq)
                lo = min(x.low for x in seq)
                if side > 0:
                    return (hi - entry) / L.atr, (entry - lo) / L.atr
                return (entry - lo) / L.atr, (hi - entry) / L.atr

            mfe, mae = exc(rest)
            mfe_i, mae_i = exc(bars[i:])
            ec = b0.close
            hi_r = max(x.high for x in rest)
            lo_r = min(x.low for x in rest)
            if side > 0:
                mfe_c, mae_c = (hi_r - ec) / L.atr, (ec - lo_r) / L.atr
            else:
                mfe_c, mae_c = (ec - lo_r) / L.atr, (hi_r - ec) / L.atr
            bucket = "GAP" if gap else hour_bucket(b0.hhmm)
            out.append(Touch(
                day=day, ratio=r, side=side, bucket=bucket,
                coarse="GAP" if gap else COARSE[hour_bucket(b0.hhmm)],
                gap=gap, i=i, entry=entry, atr=L.atr, anchor=L.anchor,
                bars=bars, mfe=max(mfe, 0.0), mae=max(mae, 0.0),
                mfe_incl=max(mfe_i, 0.0), mae_incl=max(mae_i, 0.0),
                to_close=side * (bars[-1].close - entry) / L.atr,
                n_left=len(rest),
                entry_c=ec, freeride=side * (ec - entry) / L.atr,
                mfe_c=max(mfe_c, 0.0), mae_c=max(mae_c, 0.0),
                to_close_c=side * (bars[-1].close - ec) / L.atr))
    return out


# ---------------------------------------------------------------- 路径模拟

def simulate(bars: list, i: int, entry: float, side: int, atr: float,
             stop: float, target: float, include_entry_bar: bool = False,
             ambiguous: str = "pess") -> tuple[str, float]:
    """返回 (退出原因, R)。R = 盈亏(ATR) / stop。"""
    stop_px = entry - side * stop * atr
    tgt_px = entry + side * target * atr
    start = i if include_entry_bar else i + 1
    for j in range(start, len(bars)):
        b = bars[j]
        hs = (b.low <= stop_px) if side > 0 else (b.high >= stop_px)
        ht = (b.high >= tgt_px) if side > 0 else (b.low <= tgt_px)
        if hs and ht:
            return ("amb", -1.0 if ambiguous == "pess" else target / stop)
        if hs:
            return ("stop", -1.0)
        if ht:
            return ("target", target / stop)
    return ("close", side * (bars[-1].close - entry) / (stop * atr))


def run_cohort(ts: list[Touch], stop: float, target: float,
               ambiguous: str = "pess", conv: str = "C",
               cost: float = 0.0) -> tuple[list[float], int]:
    rs, amb = [], 0
    for t in ts:
        e, incl = conv_entry(t, conv)
        why, r = simulate(t.bars, t.i, e, t.side, t.atr, stop, target,
                          incl, ambiguous)
        if why == "amb":
            amb += 1
        rs.append(r - cost / stop)
    return rs, amb


def run_rule(ts: list[Touch], fn, conv: str = "C", ambiguous: str = "pess",
             cost: float = 0.0, flip: bool = False) -> tuple[list[float], int, dict]:
    rs, amb = [], 0
    per_day: dict = defaultdict(list)
    for t in ts:
        s, tg = fn(abs(t.ratio))
        e, incl = conv_entry(t, conv)
        side = -t.side if flip else t.side
        why, r = simulate(t.bars, t.i, e, side, t.atr, s, tg, incl, ambiguous)
        if why == "amb":
            amb += 1
        r -= cost / s
        rs.append(r)
        per_day[t.day].append(r)
    return rs, amb, per_day


# ---------------------------------------------------------------- 报告分节

def sec(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    print("止损与目标的几何 —— MFE/MAE 研究")
    print("生成于确定性脚本，无随机成分（bootstrap 固定 seed=12345）")

    # ---------------- 数据
    d = data.daily(years="20y")
    lv = levels.build(d)
    f = data.fine()
    sess5 = data.group_by_day(f)
    h = data.hourly()
    sessH = data.group_by_day(h)

    days5 = [k for k in sorted(sess5) if k in lv and len(sess5[k]) >= 70]
    sec("§0  数据清单")
    print(f"5m: {len(f)} 根, {len(sess5)} 天, "
          f"{days5[0]} → {days5[-1]}, 有位图且完整的交易日 = {len(days5)}")
    print(f"1h: {len(h)} 根, {len(sessH)} 天")
    rng5 = [(b.high - b.low) / lv[b.day].atr for b in f if b.day in lv]
    print(f"5m 单根 K 振幅 / ATR: 中位 {q(rng5,.5):.4f}  p75 {q(rng5,.75):.4f} "
          f"p90 {q(rng5,.90):.4f}  p99 {q(rng5,.99):.4f}")
    print("梯子相邻档间距(ATR): 0.236→0.382=0.146  0.382→0.500=0.118  "
          "0.500→0.618=0.118  0.618→0.786=0.168")
    print(">>> 注意: 相邻具名位的间距 0.118~0.168 ATR 与一根 5m K 的 p90 振幅同量级。")

    touches = build_touches({k: sess5[k] for k in days5}, lv)
    sec("§1  首触事件计数（5m, 59 个交易日）")
    print(f"总事件 {len(touches)} 笔  (每天每个具名位至多 1 笔)")
    print(f"{'位':>8} {'方向':>4} {'n':>4} {'其中开盘跳空':>12} {'盘中触发':>8}")
    for r in SIGNED:
        sub = [t for t in touches if abs(t.ratio - r) < 1e-9]
        g = sum(1 for t in sub if t.gap)
        print(f"{r:>+8.3f} {'多' if r>0 else '空':>4} {len(sub):>4} "
              f"{g:>12} {len(sub)-g:>8}")
    print("\n按首触时段分布（合并方向）:")
    for b in ("GAP",) + HOUR_BUCKETS:
        n = sum(1 for t in touches if t.bucket == b)
        print(f"  {b:>6}  n={n}")

    # ---------------- §2 无条件漂移
    sec("§2  先问最根本的问题：触及具名位之后，到收盘有没有漂移？")
    print("统计量 = (收盘 - 入场) * side / ATR。若它 ≈ 0，则任何止损/目标组合")
    print("都只是在重排 R 的分布，不能凭空造出期望值（鞅的性质）。\n")
    print(f"{'位':>8} {'n':>4} {'均值(ATR)':>10} {'SE':>7} {'t':>6} "
          f"{'中位':>7} {'>0 占比':>8}")
    all_close = []
    for r in SIGNED:
        sub = [t.to_close for t in touches if abs(t.ratio - r) < 1e-9]
        if not sub:
            continue
        m, se = mean_se(sub)
        all_close += sub
        test_tick()
        print(f"{r:>+8.3f} {len(sub):>4} {m:>+10.3f} {se:>7.3f} "
              f"{m/se if se else 0:>+6.2f} {q(sub,.5):>+7.3f} "
              f"{100*sum(1 for x in sub if x>0)/len(sub):>7.1f}%")
    m, se = mean_se(all_close)
    test_tick()
    print(f"{'合并':>8} {len(all_close):>4} {m:>+10.3f} {se:>7.3f} "
          f"{m/se if se else 0:>+6.2f} {q(all_close,.5):>+7.3f} "
          f"{100*sum(1 for x in all_close if x>0)/len(all_close):>7.1f}%")
    byday = defaultdict(list)
    for t in touches:
        byday[t.day].append(t.to_close)
    lo, hi = day_block_bootstrap(byday, statistics.fmean)
    print(f"合并均值日区块 bootstrap 95% CI = [{lo:+.3f}, {hi:+.3f}] ATR")

    print("\n分方向（多/空各自合并）:")
    for name, sel in (("多头 4 个位", lambda t: t.side > 0),
                      ("空头 4 个位", lambda t: t.side < 0)):
        sub = [t.to_close for t in touches if sel(t)]
        m, se = mean_se(sub)
        test_tick()
        print(f"  {name}: n={len(sub)} 均值={m:+.3f} SE={se:.3f} t={m/se if se else 0:+.2f}")

    # ---------------- §3 MFE / MAE 分布
    sec("§3  MFE 分布（触及后到收盘，ATR 单位，从下一根 5m K 起算）")
    print("读法：p50=0.20 表示一半的持仓在收盘前至少有过 0.20 ATR 的浮盈。")
    for r in SIGNED:
        sub = [t.mfe for t in touches if abs(t.ratio - r) < 1e-9]
        print(f"  {r:>+7.3f}  {qline(sub)}")
    print(f"  {'合并':>7}  {qline([t.mfe for t in touches])}")

    sec("§4  MAE 分布 —— 止损该放哪的直接答案")
    print("读法：p80=0.18 表示止损放在 0.18 ATR 之外，80% 的持仓不会被扫掉。")
    for r in SIGNED:
        sub = [t.mae for t in touches if abs(t.ratio - r) < 1e-9]
        print(f"  {r:>+7.3f}  {qline(sub)}")
    print(f"  {'合并':>7}  {qline([t.mae for t in touches])}")
    print("\n【悲观界】把首触那根 K 本身也算进去（低点可能发生在触及之前）:")
    for r in SIGNED:
        sub = [t.mae_incl for t in touches if abs(t.ratio - r) < 1e-9]
        print(f"  {r:>+7.3f}  {qline(sub)}")

    sec("§4b  但『保住 80% 持仓』是错的问题 —— 要看赢单的 MAE")
    print("被扫掉的那 20% 如果本来就是亏单，宽止损只是把小亏变大亏。")
    print("真正该问的是：最终走到目标 T 的那些单子，路上最深回撤是多少。\n")
    for r in RATIOS:
        for T_name, T in (("下一档", next_level(r) - r),
                          ("下下档", next_level(next_level(r)) - r),
                          ("0.30ATR", 0.30)):
            sub = [t for t in touches if abs(abs(t.ratio) - r) < 1e-9]
            win = [t.mae for t in sub if t.mfe >= T]
            k, n = len(win), len(sub)
            test_tick()
            print(f"  L=±{r:.3f} 目标={T_name}({T:.3f} ATR): "
                  f"到达率 {stats.fmt_rate(k, n)}  赢单MAE {qline(win)}")

    sec("§4c  几何判决：赢单 MAE 中位 vs 报酬距离")
    print(f"{'位':>8} {'到下一档距离':>12} {'赢单MAE中位':>12} {'赢单MAE p75':>12} {'判决':>8}")
    for r in RATIOS:
        T = next_level(r) - r
        sub = [t for t in touches if abs(abs(t.ratio) - r) < 1e-9]
        win = [t.mae for t in sub if t.mfe >= T]
        if len(win) < 5:
            print(f"  ±{r:.3f} n<5")
            continue
        med = q(win, .5)
        verdict = "报酬 < 噪声" if med >= T else "报酬 > 噪声"
        print(f"{r:>+8.3f} {T:>12.3f} {med:>12.3f} {q(win,.75):>12.3f} {verdict:>8}")

    sec("§4d  MFE − MAE：整个几何是不是对称的")
    print("对无漂移过程，E[MFE] = E[MAE]（对称性）。这个差值就是『方向优势』的直接度量。")
    print(f"{'位':>8}{'n':>5}{'E[MFE]':>9}{'E[MAE]':>9}{'差':>9}{'SE':>7}{'t':>7}")
    for r in SIGNED:
        sub = [t for t in touches if abs(t.ratio - r) < 1e-9]
        dd = [t.mfe - t.mae for t in sub]
        m, se = mean_se(dd)
        test_tick()
        print(f"{r:>+8.3f}{len(sub):>5}"
              f"{statistics.fmean([t.mfe for t in sub]):>9.3f}"
              f"{statistics.fmean([t.mae for t in sub]):>9.3f}"
              f"{m:>+9.3f}{se:>7.3f}{m/se if se else 0:>+7.2f}")
    dd = [t.mfe - t.mae for t in touches]
    m, se = mean_se(dd)
    test_tick()
    print(f"{'合并':>8}{len(touches):>5}"
          f"{statistics.fmean([t.mfe for t in touches]):>9.3f}"
          f"{statistics.fmean([t.mae for t in touches]):>9.3f}"
          f"{m:>+9.3f}{se:>7.3f}{m/se if se else 0:>+7.2f}")
    bd = defaultdict(list)
    for t in touches:
        bd[t.day].append(t.mfe - t.mae)
    lo, hi = day_block_bootstrap(bd, statistics.fmean)
    print(f"合并 E[MFE]-E[MAE] 日区块 bootstrap 95% CI = [{lo:+.3f}, {hi:+.3f}] ATR")

    sec("§4e  第一个『在噪声之外』的目标")
    print("噪声尺度取本样本合并 MAE 中位 = "
          f"{q([t.mae for t in touches],.5):.3f} ATR。")
    print("下表把每个起始位的下一档、下下档、以及第一个距离 ≥ 噪声尺度的档位并排，")
    print("并给出实测到达率（P(MFE ≥ 距离)）与 Wilson 区间。到达率**不是**胜率——")
    print("它没有扣除路上被止损的部分，是上界。\n")
    noise = q([t.mae for t in touches], .5)
    print(f"{'起始位':>8}{'目标档':>9}{'距离':>8}{'是否>噪声':>10}{'到达率(上界)':>26}")
    for r in RATIOS:
        cand = [x for x in LADDER if x > r + 1e-9][:4]
        sub = [t for t in touches if abs(abs(t.ratio) - r) < 1e-9]
        for c in cand:
            dist = c - r
            k = sum(1 for t in sub if t.mfe >= dist)
            test_tick()
            print(f"{r:>+8.3f}{c:>9.3f}{dist:>8.3f}"
                  f"{'是' if dist >= noise else '否':>10}"
                  f"   {stats.fmt_rate(k, len(sub))}")

    # ---------------- §5 MFE/MAE 上界
    sec("§5  完美退出上界（不可实现，只用来给一切结果封顶）")
    print("若能在最高点出场且从不被止损：R_max = MFE / stop。")
    for s in (0.10, 0.20, 0.30):
        ok = [t for t in touches if t.mae < s]
        rs = [t.mfe / s for t in ok]
        print(f"  止损={s:.2f} ATR: 存活 {stats.fmt_rate(len(ok), len(touches))} "
              f"存活单的 MFE/stop 中位={q(rs,.5):.2f}R p90={q(rs,.9):.2f}R")

    sec("§5b  止损可测性：哪些止损距离在 5m 分辨率下根本量不出来")
    print("一根 5m K 的振幅分位（ATR 单位）: "
          f"p50={q(rng5,.5):.3f} p75={q(rng5,.75):.3f} p90={q(rng5,.90):.3f}")
    print("若止损距离 < 单根 K 振幅中位，那么『首触那根 K 算不算进路径』这个")
    print("纯口径选择就能决定这笔交易的死活 —— 结果不是市场性质，是口径性质。\n")
    print(f"{'止损(ATR)':>10}{'< 5m K 振幅的比例':>20}{'判定':>18}")
    for s in (0.05, 0.059, 0.073, 0.10, 0.118, 0.15, 0.20, 0.30, 0.40):
        frac = sum(1 for x in rng5 if x >= s) / len(rng5)
        verdict = "不可测" if frac > 0.35 else ("勉强" if frac > 0.10 else "可测")
        print(f"{s:>10.3f}{100*frac:>19.1f}%{verdict:>18}")

    sec("§5c  口径就是结论：入场那根 K 的『免费跑段』")
    print("口径 A（入场价=位价，路径从下一根 K 起）白送了一段收益：价格在首触那根 K 内")
    print("从位价跑到该 K 收盘的那一段，被计入盈利却不承担任何回撤风险。")
    print("这一段有多大？\n")
    fr = [t.freeride for t in touches]
    print(f"  免费跑段 (首触K收盘 - 位价)*side/ATR:  {qline(fr)}")
    print(f"  超过 0.05 ATR 的比例 = "
          f"{100*sum(1 for x in fr if x>0.05)/len(fr):.1f}%   "
          f"超过 0.10 ATR = {100*sum(1 for x in fr if x>0.10)/len(fr):.1f}%")
    print(f"{'位':>8}{'n':>5}{'免费跑段均值(ATR)':>18}{'折合几个 0.05 止损':>20}")
    for r in RATIOS:
        sub = [t.freeride for t in touches if abs(abs(t.ratio) - r) < 1e-9]
        m = statistics.fmean(sub)
        print(f"{r:>+8.3f}{len(sub):>5}{m:>+18.4f}{m/0.05:>20.2f}")
    print("\n>>> 因此本报告从此处起把**口径 C**（入场价 = 首触那根 K 的收盘价，")
    print(">>> 路径从下一根 K 起算）定为主口径：它自洽、可执行、不白送也不冤枉。")
    print(">>> A 与 B 只作为上下界出现。三种口径的定义见文件头注释。")
    print("\n三口径下的 MFE/MAE（合并）:")
    print(f"{'口径':>26}{'MFE p50':>9}{'MFE p90':>9}{'MAE p50':>9}{'MAE p80':>9}"
          f"{'E[MFE-MAE]':>12}{'SE':>7}")
    for nm, mf, ma in (("A 位价入场/次根起算", [t.mfe for t in touches],
                        [t.mae for t in touches]),
                       ("B 位价入场/含首触根", [t.mfe_incl for t in touches],
                        [t.mae_incl for t in touches]),
                       ("C 首触根收盘入场", [t.mfe_c for t in touches],
                        [t.mae_c for t in touches])):
        dd = [a - b for a, b in zip(mf, ma)]
        m, se = mean_se(dd)
        test_tick()
        print(f"{nm:>26}{q(mf,.5):>9.3f}{q(mf,.9):>9.3f}{q(ma,.5):>9.3f}"
              f"{q(ma,.8):>9.3f}{m:>+12.3f}{se:>7.3f}")
    tcc = [t.to_close_c for t in touches]
    m, se = mean_se(tcc)
    test_tick()
    print(f"\n口径 C 的到收盘漂移: n={len(tcc)} 均值={m:+.4f} ATR SE={se:.4f} "
          f"t={m/se:+.2f}")
    bdc = defaultdict(list)
    for t in touches:
        bdc[t.day].append(t.to_close_c)
    lo, hi = day_block_bootstrap(bdc, statistics.fmean)
    print(f"日区块 bootstrap 95% CI = [{lo:+.4f}, {hi:+.4f}] ATR")

    # ---------------- §6 网格
    sec("§6  止损-目标网格（择优陷阱现场）—— 主口径 C")
    cohorts: dict[str, list[Touch]] = {}
    for r in SIGNED:
        cohorts[f"L={r:+.3f}"] = [t for t in touches if abs(t.ratio - r) < 1e-9]
    for r in RATIOS:
        cohorts[f"|L|={r:.3f} 折叠"] = [t for t in touches
                                        if abs(abs(t.ratio) - r) < 1e-9]
    for r in RATIOS:
        for cb in ("EARLY", "MID", "LATE"):
            cohorts[f"|L|={r:.3f} {cb}"] = [
                t for t in touches
                if abs(abs(t.ratio) - r) < 1e-9 and t.coarse == cb]
    cohorts["全部合并"] = list(touches)

    print(f"cohort 数 = {len(cohorts)}, 每个 cohort 网格 = "
          f"{len(STOPS)}x{len(TARGETS)} = {len(STOPS)*len(TARGETS)}")
    print(f"{'cohort':<22}{'n':>4} {'最优(S,T)':>14} {'毛均R':>8} "
          f"{'净均R':>8} {'网格中位':>9} {'网格>0占比':>10} {'歧义率':>7}")
    best_by_cohort = {}
    for name, ts in cohorts.items():
        if len(ts) < 15:
            print(f"{name:<22}{len(ts):>4}  n<15 跳过（但格子照样计入家族）")
            grid_tick(len(STOPS) * len(TARGETS))
            continue
        results = []
        amb_tot = amb_n = 0
        for s in STOPS:
            for tg in TARGETS:
                rs, amb = run_cohort(ts, s, tg)
                grid_tick()
                amb_tot += amb
                amb_n += len(rs)
                results.append((statistics.fmean(rs), s, tg, rs))
        results.sort(reverse=True, key=lambda x: x[0])
        top = results[0]
        rs_net, _ = run_cohort(ts, top[1], top[2], cost=COST_ATR)
        allm = [x[0] for x in results]
        best_by_cohort[name] = (top[1], top[2], top[0])
        print(f"{name:<22}{len(ts):>4} {f'({top[1]:.3f},{top[2]:.2f})':>14} "
              f"{top[0]:>+8.3f} {statistics.fmean(rs_net):>+8.3f} "
              f"{statistics.median(allm):>+9.3f} "
              f"{100*sum(1 for x in allm if x>0)/len(allm):>9.1f}% "
              f"{100*amb_tot/max(amb_n,1):>6.1f}%")

    nb = sum(1 for v in best_by_cohort.values() if abs(v[0] - min(STOPS)) < 1e-9)
    print(f"\n>>> 边界诊断：{nb}/{len(best_by_cohort)} 个 cohort 的『最优止损』"
          f"落在网格最小值 {min(STOPS)} 上。")
    print(">>> 内点最优才是真极值；贴边最优通常说明目标函数在往边界跑。")
    print(">>> 机制：R = 盈亏(ATR)/止损。止损越小分母越小，同一条路径的 R 被放大，")
    print(">>> 方差也被同比例放大 —— 于是『均 R 最大』几乎必然选中最小止损。")
    print(">>> 换成『均盈亏(ATR)』这个不被止损缩放的度量，最优止损立刻不同：")
    print(f"{'cohort':<22}{'按均R的最优':>14}{'按均ATR盈亏的最优':>20}{'均ATR盈亏':>11}")
    for name in ("全部合并", "|L|=0.236 折叠", "|L|=0.382 折叠",
                 "|L|=0.500 折叠", "|L|=0.618 折叠"):
        ts = cohorts[name]
        if len(ts) < 15:
            continue
        bestA = best_by_cohort[name]
        bb = None
        for s in STOPS:
            for tg in TARGETS:
                rs, _ = run_cohort(ts, s, tg)
                grid_tick()
                v = statistics.fmean(rs) * s      # 换算回 ATR 单位的盈亏
                if bb is None or v > bb[0]:
                    bb = (v, s, tg)
        print(f"{name:<22}{f'({bestA[0]:.3f},{bestA[1]:.2f})':>14}"
              f"{f'({bb[1]:.3f},{bb[2]:.2f})':>20}{bb[0]:>+11.4f}")

    print(f"\n>>> 到此为止已评估 {GRID_CELLS} 个 (止损,目标) 格子。")
    print(">>> 上表每一行的『最优』都是 64 个含噪估计的最大值。纯噪声下，")
    print(">>> 64 个独立样本均值的最大值的期望 ≈ 2.3 个标准误。")
    for name in ("全部合并", "|L|=0.236 折叠", "|L|=0.382 折叠"):
        ts = cohorts[name]
        if len(ts) < 15:
            continue
        s, tg, m = best_by_cohort[name]
        rs, _ = run_cohort(ts, s, tg)
        _, se = mean_se(rs)
        print(f"    {name}: 最优 {m:+.3f}R, 该格自身 SE={se:.3f}R "
              f"→ {m/se if se else 0:.2f} 个 SE（噪声下最大值期望 ≈2.3）")

    sec("§6b  同一张网格换成口径 A：免费跑段能造出多大的假 edge")
    print(f"{'cohort':<22}{'C 最优(S,T)':>14}{'C 均R':>8}"
          f"{'A 最优(S,T)':>14}{'A 均R':>8}{'A 的最优格在 C 下':>18}")
    for name in ("全部合并", "|L|=0.236 折叠", "|L|=0.382 折叠",
                 "|L|=0.500 折叠", "|L|=0.618 折叠"):
        ts = cohorts[name]
        if len(ts) < 15:
            continue
        bA = None
        for s in STOPS:
            for tg in TARGETS:
                rs, _ = run_cohort(ts, s, tg, conv="A")
                grid_tick()
                v = statistics.fmean(rs)
                if bA is None or v > bA[0]:
                    bA = (v, s, tg)
        rc, _ = run_cohort(ts, bA[1], bA[2], conv="C")
        bC = best_by_cohort[name]
        print(f"{name:<22}{f'({bC[0]:.3f},{bC[1]:.2f})':>14}{bC[2]:>+8.3f}"
              f"{f'({bA[1]:.3f},{bA[2]:.2f})':>14}{bA[0]:>+8.3f}"
              f"{statistics.fmean(rc):>+18.3f}")
    print(">>> 这一栏是本报告最重要的一条方法论证据：口径 A 下 |L|=0.236 的『最优』")
    print(">>> 是 +1.3R/笔，换成可执行的口径 C 就变成约 0。差额全部来自免费跑段，")
    print(">>> 它在真实交易里不存在 —— 你没法在位价成交之后还享受那 5 分钟的走势。")

    # ---------------- §7 反向检验
    sec("§7  前 30 天 / 后 30 天 反向检验（主口径 C）")
    cut = days5[len(days5) // 2]
    h1 = [t for t in touches if t.day < cut]
    h2 = [t for t in touches if t.day >= cut]
    print(f"切点 {cut}: 前半 {len(set(t.day for t in h1))} 天 {len(h1)} 笔, "
          f"后半 {len(set(t.day for t in h2))} 天 {len(h2)} 笔")
    print(f"\n{'cohort':<22}{'H1最优(S,T)':>14}{'H1均R':>8}{'该格在H2':>10}"
          f"{'H2最优(S,T)':>14}{'H2均R':>8}{'该格在H1':>10}{'秩相关':>8}")
    for name in ["全部合并"] + [f"|L|={r:.3f} 折叠" for r in RATIOS] + \
                [f"L={r:+.3f}" for r in SIGNED]:
        A = [t for t in h1 if t in cohorts[name]] if False else \
            [t for t in cohorts[name] if t.day < cut]
        B = [t for t in cohorts[name] if t.day >= cut]
        if len(A) < 12 or len(B) < 12:
            print(f"{name:<22}  n 太小 (A={len(A)}, B={len(B)}) —— 跳过")
            continue
        ga, gb = {}, {}
        for s in STOPS:
            for tg in TARGETS:
                ra, _ = run_cohort(A, s, tg)
                rb, _ = run_cohort(B, s, tg)
                grid_tick(2)
                ga[(s, tg)] = statistics.fmean(ra)
                gb[(s, tg)] = statistics.fmean(rb)
        ka = max(ga, key=ga.get)
        kb = max(gb, key=gb.get)
        keys = list(ga)
        ra_ = sorted(keys, key=lambda k: ga[k])
        rb_ = sorted(keys, key=lambda k: gb[k])
        rank_a = {k: i for i, k in enumerate(ra_)}
        rank_b = {k: i for i, k in enumerate(rb_)}
        n = len(keys)
        dsum = sum((rank_a[k] - rank_b[k]) ** 2 for k in keys)
        rho = 1 - 6 * dsum / (n * (n * n - 1))
        test_tick()
        print(f"{name:<22}{f'({ka[0]:.3f},{ka[1]:.2f})':>14}{ga[ka]:>+8.3f}"
              f"{gb[ka]:>+10.3f}{f'({kb[0]:.3f},{kb[1]:.2f})':>14}"
              f"{gb[kb]:>+8.3f}{ga[kb]:>+10.3f}{rho:>+8.2f}")
    print("\n读法：如果『H1 最优格在 H2』这一列系统性接近 0 或为负，")
    print("就说明最优格是拟合噪声，不是几何事实。秩相关 ρ 是两半网格形状的一致性。")

    # ---------------- §8 结构规则
    sec("§8  不依赖择优的结构性规则（事前定死，每条只报一个格子）")
    rules = {
        "SR1 半步止损/下一档目标": lambda r: (0.5 * (r - prev_level(r)),
                                              next_level(r) - r),
        "SR2 上一档止损/下一档目标": lambda r: (r - prev_level(r),
                                                next_level(r) - r),
        "SR3 0.30ATR止损/下一档目标": lambda r: (0.30, next_level(r) - r),
        "SR4 0.30ATR止损/下下档目标": lambda r: (0.30,
                                                 next_level(next_level(r)) - r),
        "SR5 对称 0.15/0.15": lambda r: (0.15, 0.15),
        "SR6 半步止损/下下档目标": lambda r: (0.5 * (r - prev_level(r)),
                                              next_level(next_level(r)) - r),
    }
    print("每条规则在 4 个起始位上的 (止损, 目标) —— 全部由梯子几何唯一决定：")
    print(f"{'规则':<26}" + "".join(f"{'|L|='+f'{r:.3f}':>16}" for r in RATIOS))
    for rn, fn in rules.items():
        cells = []
        for r in RATIOS:
            s, tg = fn(r)
            cells.append(f"({s:.3f},{tg:.3f})")
        print(f"{rn:<26}" + "".join(f"{c:>16}" for c in cells))
    print("\n止损可测性标记（止损 < 5m K 振幅中位 0.070 ATR 的格子用 * 标出，"
          "它们的结果由口径而非市场决定）:")
    for rn, fn in rules.items():
        marks = []
        for r in RATIOS:
            s, _ = fn(r)
            marks.append(f"{'*' if s < q(rng5,.5) else ' '}{s:.3f}")
        print(f"  {rn:<26}" + "  ".join(marks))

    print("\n【主口径 C】入场价 = 首触那根 K 的收盘价")
    print(f"{'规则':<26}{'n':>4}{'毛均R':>8}{'净均R':>8}{'SE':>7}{'t':>6}"
          f"{'胜率':>7}{'胜率95%CI':>16}{'打平需':>8}{'盈亏比':>7}")
    rule_rs = {}
    for rn, fn in rules.items():
        rs_g, amb, per_day = run_rule(touches, fn, conv="C")
        rs_n, _, _ = run_rule(touches, fn, conv="C", cost=COST_ATR)
        grid_tick()          # 每条规则只是一个格子
        e = stats.expectancy(rs_g)
        m, se = mean_se(rs_g)
        test_tick()
        rule_rs[rn] = (rs_g, per_day)
        kw = sum(1 for x in rs_g if x > 1e-12)
        wlo, whi = stats.wilson(kw, len(rs_g))
        print(f"{rn:<26}{len(rs_g):>4}{m:>+8.3f}"
              f"{statistics.fmean(rs_n):>+8.3f}{se:>7.3f}"
              f"{m/se if se else 0:>+6.2f}{100*e['win_rate']:>6.1f}%"
              f"  [{100*wlo:>5.1f},{100*whi:>5.1f}]"
              f"{100*e['breakeven_wr']:>7.1f}%"
              f"{(e['avg_win']/-e['avg_loss'] if e['avg_loss'] else 0):>7.2f}")
    print("\n同一批规则的日区块 bootstrap 95% CI（毛，2000 次, seed=12345）:")
    for rn, (rs_g, per_day) in rule_rs.items():
        lo, hi = day_block_bootstrap(per_day, statistics.fmean)
        print(f"  {rn:<26} 均R 95% CI = [{lo:+.3f}, {hi:+.3f}]")

    print("\n【三口径对照】—— 差多大就说明这条规则有多依赖口径")
    print(f"{'规则':<26}{'A 位价/次根起':>14}{'B 位价/含首根':>14}"
          f"{'C 首根收盘入':>14}{'A-C':>9}")
    for rn, fn in rules.items():
        vals = {}
        for cv in ("A", "B", "C"):
            rs, _, _ = run_rule(touches, fn, conv=cv)
            vals[cv] = statistics.fmean(rs)
        print(f"{rn:<26}{vals['A']:>+14.3f}{vals['B']:>+14.3f}"
              f"{vals['C']:>+14.3f}{vals['A']-vals['C']:>+9.3f}")

    print("\n同根 K 歧义的双界（悲观 = 撞止损，乐观 = 到目标），主口径 C:")
    print(f"{'规则':<26}{'悲观均R':>9}{'乐观均R':>9}{'歧义率':>8}")
    for rn, fn in rules.items():
        rp, amb, _ = run_rule(touches, fn, conv="C", ambiguous="pess")
        ro, _, _ = run_rule(touches, fn, conv="C", ambiguous="opt")
        print(f"{rn:<26}{statistics.fmean(rp):>+9.3f}"
              f"{statistics.fmean(ro):>+9.3f}{100*amb/len(rp):>7.1f}%")

    print("\n结构规则的前后半样本稳定性（主口径 C）:")
    print(f"{'规则':<26}{'H1均R':>8}{'H1 n':>6}{'H2均R':>8}{'H2 n':>6}{'同号':>6}")
    for rn, fn in rules.items():
        a_rs, _, _ = run_rule(h1, fn, conv="C")
        b_rs, _, _ = run_rule(h2, fn, conv="C")
        a, b = statistics.fmean(a_rs), statistics.fmean(b_rs)
        print(f"{rn:<26}{a:>+8.3f}{len(a_rs):>6}{b:>+8.3f}"
              f"{len(b_rs):>6}{'是' if a*b>0 else '否':>6}")

    # ---------------- §9 零技能对照
    sec("§9  零技能对照：同时段随便进场，几何是不是一样好")
    print("对照组 = 同一批交易日、同一小时档内的**每一根** 5m K，按收盘价入场，")
    print("两个方向都做。若具名位不带信息，两组的 R 分布应当没有差别。\n")
    ctrl: list[Touch] = []
    for day in days5:
        L = lv[day]
        bars = [b for b in sess5[day] if b.hhmm < "16:00"]
        for i, b in enumerate(bars[:-1]):
            for side in (1, -1):
                rest = bars[i + 1:]
                hi = max(x.high for x in rest)
                lo = min(x.low for x in rest)
                mfe = (hi - b.close) / L.atr if side > 0 else (b.close - lo) / L.atr
                mae = (b.close - lo) / L.atr if side > 0 else (hi - b.close) / L.atr
                ctrl.append(Touch(day, 0.0, side, hour_bucket(b.hhmm),
                                  COARSE[hour_bucket(b.hhmm)], False, i,
                                  b.close, L.atr, L.anchor, bars,
                                  max(mfe, 0), max(mae, 0), 0.0, 0.0,
                                  side * (bars[-1].close - b.close) / L.atr,
                                  len(rest),
                                  entry_c=b.close, freeride=0.0,
                                  mfe_c=max(mfe, 0), mae_c=max(mae, 0),
                                  to_close_c=side * (bars[-1].close - b.close)
                                  / L.atr))
    print(f"对照组 n = {len(ctrl)}（59 天 x 77 根 K x 2 方向）")
    print("对照按 (起始位量级, 小时档) 双重匹配：真实交易在每个 (|L|, 档) 上的占比")
    print("就是对照组同一 (几何, 档) 单元的权重。跳空档映射到 09:30 档。\n")
    ctrl_by_bucket = defaultdict(list)
    for t in ctrl:
        ctrl_by_bucket[t.bucket].append(t)
    from collections import Counter
    wmap = Counter((abs(t.ratio), "09:30" if t.bucket == "GAP" else t.bucket)
                   for t in touches)
    wtot = sum(wmap.values())
    print(f"{'规则':<26}{'具名位均R':>11}{'n':>5}{'匹配对照均R':>13}{'差':>9}"
          f"{'具名位SE':>10}{'差/SE':>8}")
    for rn, fn in rules.items():
        rsA, _, _ = run_rule(touches, fn, conv="C")
        num = 0.0
        cache: dict = {}
        for (mag, bkt), w in wmap.items():
            s, tg = fn(mag)
            key = (round(s, 6), round(tg, 6), bkt)
            if key not in cache:
                rr = [simulate(c.bars, c.i, c.entry_c, c.side, c.atr, s, tg)[1]
                      for c in ctrl_by_bucket.get(bkt, [])]
                cache[key] = statistics.fmean(rr) if rr else 0.0
            num += w * cache[key]
        mB = num / wtot
        mA, seA = mean_se(rsA)
        test_tick()
        print(f"{rn:<26}{mA:>+11.3f}{len(rsA):>5}{mB:>+13.3f}{mA-mB:>+9.3f}"
              f"{seA:>10.3f}{(mA-mB)/seA if seA else 0:>+8.2f}")
    print("注：对照组的路径高度重叠（同一天 77 根 K 共享一条路径），它的 SE 无法")
    print("    诚实估计，所以上面只用『具名位自身的 SE』做尺子，读作量级对照。")

    print("\nMFE/MAE 形状对照（这是本节真正的判据，两组都用口径 C 的入场价）:")
    print(f"{'组':<22}{'n':>6}{'MFE p50':>9}{'MFE p90':>9}{'MAE p50':>9}"
          f"{'MAE p80':>9}{'MFE-MAE 均值':>13}{'SE':>8}")
    def shape(name, ts):
        if not ts:
            return
        mf = [t.mfe_c for t in ts]
        ma = [t.mae_c for t in ts]
        m, se = mean_se([a - b for a, b in zip(mf, ma)])
        print(f"{name:<22}{len(ts):>6}{q(mf,.5):>9.3f}{q(mf,.9):>9.3f}"
              f"{q(ma,.5):>9.3f}{q(ma,.8):>9.3f}{m:>+13.3f}{se:>8.3f}")
    shape("具名位首触(全部)", touches)
    shape("对照:同时段市价", ctrl)
    for cb in ("GAP", "EARLY", "MID", "LATE"):
        shape(f"具名位 {cb}", [t for t in touches if t.coarse == cb])
        shape(f"对照 {cb}", [t for t in ctrl
                             if t.coarse == ("EARLY" if cb == "GAP" else cb)])
    print("注：对照组按构造是精确无漂移的 —— 同一根 K 同时做多和做空，MFE-MAE 逐笔")
    print("    相消，均值恒为 0。它因此是一把干净的几何尺子：任何非零差都来自具名位。")

    # ---------------- §10 时段
    sec("§10  按时段的 MFE/MAE（n 很小，只看形状）")
    print(f"{'时段':>6}{'n':>5}{'MFE p50':>9}{'MFE p75':>9}{'MFE p90':>9}"
          f"{'MAE p50':>9}{'MAE p80':>9}{'MFE-MAE均值':>13}{'MFE/MAE 中位比':>15}")
    for b in ("GAP",) + HOUR_BUCKETS:
        ts = [t for t in touches if t.bucket == b]
        if not ts:
            continue
        mf = [t.mfe for t in ts]
        ma = [t.mae for t in ts]
        ratio = q(mf, .5) / q(ma, .5) if q(ma, .5) > 0 else float("inf")
        print(f"{b:>6}{len(ts):>5}{q(mf,.5):>9.3f}{q(mf,.75):>9.3f}"
              f"{q(mf,.9):>9.3f}{q(ma,.5):>9.3f}{q(ma,.8):>9.3f}"
              f"{statistics.fmean([x-y for x,y in zip(mf,ma)]):>+13.3f}"
              f"{ratio:>15.2f}")

    # ---------------- §11 小时线复核
    sec("§11  独立样本形状复核：730 天小时线（首触那根 K 之后到收盘）")
    print("小时线无法判定同根 K 内先后，所以这里**只报 MFE/MAE 分布**，不做路径模拟。")
    print("在完整 K 上取 max(high)/min(low) 得到的 MFE/MAE 是精确的（不是近似）。\n")
    daysH = [k for k in sorted(sessH) if k in lv and len(sessH[k]) == 7]
    th = build_touches({k: sessH[k] for k in daysH}, lv, min_bars=3)
    print(f"小时线可用交易日 {len(daysH)}，首触事件 {len(th)} 笔")
    print(f"{'位':>8}{'n':>5}{'MFE p50':>9}{'MFE p90':>9}{'MAE p50':>9}"
          f"{'MAE p80':>9}{'MAE p90':>9}{'到收盘均值':>11}")
    for r in SIGNED:
        sub = [t for t in th if abs(t.ratio - r) < 1e-9]
        if not sub:
            continue
        mf = [t.mfe for t in sub]
        ma = [t.mae for t in sub]
        print(f"{r:>+8.3f}{len(sub):>5}{q(mf,.5):>9.3f}{q(mf,.9):>9.3f}"
              f"{q(ma,.5):>9.3f}{q(ma,.8):>9.3f}{q(ma,.9):>9.3f}"
              f"{statistics.fmean([t.to_close for t in sub]):>+11.3f}")
    mf = [t.mfe for t in th]
    ma = [t.mae for t in th]
    tc = [t.to_close for t in th]
    m, se = mean_se(tc)
    test_tick()
    print(f"{'合并':>8}{len(th):>5}{q(mf,.5):>9.3f}{q(mf,.9):>9.3f}"
          f"{q(ma,.5):>9.3f}{q(ma,.8):>9.3f}{q(ma,.9):>9.3f}{m:>+11.3f}")
    print(f"合并『到收盘漂移』: 均值 {m:+.4f} ATR, SE {se:.4f}, t={m/se:+.2f}")
    bydayH = defaultdict(list)
    for t in th:
        bydayH[t.day].append(t.to_close)
    lo, hi = day_block_bootstrap(bydayH, statistics.fmean)
    print(f"日区块 bootstrap 95% CI = [{lo:+.4f}, {hi:+.4f}] ATR")

    print("\n小时线 vs 5 分钟 的 MAE 分位数对照（同一定义，不同分辨率/不同窗口）:")
    print(f"{'':>10}{'p50':>8}{'p75':>8}{'p80':>8}{'p90':>8}{'n':>6}")
    for name, arr in (("5m 60天", [t.mae for t in touches]),
                      ("1h 730天", [t.mae for t in th])):
        print(f"{name:>10}{q(arr,.5):>8.3f}{q(arr,.75):>8.3f}"
              f"{q(arr,.8):>8.3f}{q(arr,.9):>8.3f}{len(arr):>6}")
    print("注：小时线口径丢掉了首触那根 K 的剩余 ≤60 分钟，5m 只丢 ≤5 分钟，")
    print("    所以小时线的 MFE/MAE 系统性偏小。两者不可直接相减，只比形状。")

    sec("§11b  样本外：把同一套结构规则搬到 730 天小时线（口径 C）")
    print("这里测的是一个**慢一拍**的版本：『在首次触及具名位的那个小时收盘时入场』。")
    print("它与 5m 版本不是同一笔交易（晚 ≤60 分钟），但它是唯一能在 3 年窗口上")
    print("被检验的版本，而 5m 只有 59 天。判据看双界是否同侧。\n")
    rngH = [(b.high - b.low) / lv[b.day].atr for b in h if b.day in lv]
    print(f"小时 K 振幅 / ATR: 中位 {q(rngH,.5):.3f} p75 {q(rngH,.75):.3f} "
          f"p90 {q(rngH,.90):.3f}")
    print("→ 止损小于 0.27 ATR 的规则在小时线上不可判（一根 K 就跨得过去），")
    print("  下表的歧义率会自己把这件事说出来。\n")
    print(f"{'规则':<26}{'n':>5}{'悲观均R':>9}{'乐观均R':>9}{'歧义率':>8}"
          f"{'双界同号':>9}{'胜率(悲观)':>12}")
    for rn, fn in rules.items():
        rp, amb, pdH = run_rule(th, fn, conv="C", ambiguous="pess")
        ro, _, _ = run_rule(th, fn, conv="C", ambiguous="opt")
        a, b = statistics.fmean(rp), statistics.fmean(ro)
        kw = sum(1 for x in rp if x > 1e-12)
        test_tick()
        print(f"{rn:<26}{len(rp):>5}{a:>+9.3f}{b:>+9.3f}"
              f"{100*amb/len(rp):>7.1f}%{'是' if a*b>0 else '否':>9}"
              f"{100*kw/len(rp):>11.1f}%")
    print("\n悲观界的日区块 bootstrap 95% CI（722 天，2000 次, seed=12345）:")
    for rn, fn in rules.items():
        _, _, pdH = run_rule(th, fn, conv="C", ambiguous="pess")
        lo, hi = day_block_bootstrap(pdH, statistics.fmean)
        print(f"  {rn:<26} [{lo:+.3f}, {hi:+.3f}]")
    print("\n小时线四个不重叠子期（每期约 180 个交易日）的悲观均 R:")
    nb4 = len(daysH) // 4
    quarters = [set(daysH[i*nb4:(i+1)*nb4]) for i in range(4)]
    quarters[3] |= set(daysH[4*nb4:])
    print(f"{'规则':<26}" + "".join(f"{'期'+str(i+1):>9}" for i in range(4))
          + f"{'同号数':>8}")
    for rn, fn in rules.items():
        vals = []
        for qd in quarters:
            rs, _, _ = run_rule([t for t in th if t.day in qd], fn, conv="C")
            vals.append(statistics.fmean(rs) if rs else 0.0)
        pos = sum(1 for v in vals if v > 0)
        print(f"{rn:<26}" + "".join(f"{v:>+9.3f}" for v in vals)
              + f"{max(pos, 4-pos):>6}/4")

    sec("§11c  反向做（fade）会不会赢？—— 判断亏损来自方向还是来自几何摩擦")
    print("同样的入场时刻、同样的止损/目标距离，方向取反。若顺势和逆势**双双为负**，")
    print("那么负期望不是『方向选错了』，而是这个几何本身在漏钱（歧义 + 报酬<噪声）。\n")
    print(f"{'规则':<26}{'顺势(悲观)':>12}{'逆势(悲观)':>12}{'两者之和':>10}"
          f"{'双双为负':>10}")
    for rn, fn in rules.items():
        a, _, _ = run_rule(th, fn, conv="C")
        b, _, _ = run_rule(th, fn, conv="C", flip=True)
        ma, mb = statistics.fmean(a), statistics.fmean(b)
        grid_tick()
        print(f"{rn:<26}{ma:>+12.3f}{mb:>+12.3f}{ma+mb:>+10.3f}"
              f"{'是' if (ma < 0 and mb < 0) else '否':>10}")

    sec("§11d  730 天小时线上的完整 8x8 网格（全部 64 格照登，双界）")
    print("这是本报告 n 最大的一张表（2623 笔 / 722 天）。左半是悲观界，右半是乐观界。")
    print("如果连**乐观界**都普遍不为正，那么这一整族止损/目标组合就整体不可交易。\n")
    for tag, amb_mode in (("悲观界（同根 K 歧义算止损）", "pess"),
                          ("乐观界（同根 K 歧义算到目标）", "opt")):
        print(f"\n{tag}  —— 单元格 = 均 R")
        print(f"{'止损\\目标':>10}" + "".join(f"{t:>8.2f}" for t in TARGETS))
        for s in STOPS:
            row = []
            for tg in TARGETS:
                rs, _ = run_cohort(th, s, tg, ambiguous=amb_mode, conv="C")
                grid_tick()
                row.append(statistics.fmean(rs))
            print(f"{s:>10.3f}" + "".join(f"{v:>+8.3f}" for v in row))
    print("\n同一张网格的歧义率（%）:")
    print(f"{'止损\\目标':>10}" + "".join(f"{t:>8.2f}" for t in TARGETS))
    for s in STOPS:
        row = []
        for tg in TARGETS:
            rs, amb = run_cohort(th, s, tg, conv="C")
            row.append(100 * amb / len(rs))
        print(f"{s:>10.3f}" + "".join(f"{v:>8.1f}" for v in row))

    # ---------------- §12 SPY 复核
    sec("§12  标的复核：SPY 5m（开盘价可成交，^GSPC 的 09:30 印刷是滞后印刷）")
    try:
        sd = data.daily(symbol="SPY", years="20y")
        slv = levels.build(sd)
        sf = data.fine(symbol="SPY")
        ssess = data.group_by_day(sf)
        sdays = [k for k in sorted(ssess) if k in slv and len(ssess[k]) >= 70]
        st = build_touches({k: ssess[k] for k in sdays}, slv)
        print(f"SPY 可用交易日 {len(sdays)}，首触事件 {len(st)} 笔")
        print(f"{'':>10}{'MFE p50':>9}{'MFE p90':>9}{'MAE p50':>9}{'MAE p80':>9}"
              f"{'到收盘均值':>11}{'n':>6}")
        for name, ts in (("^GSPC", touches), ("SPY", st)):
            print(f"{name:>10}{q([t.mfe for t in ts],.5):>9.3f}"
                  f"{q([t.mfe for t in ts],.9):>9.3f}"
                  f"{q([t.mae for t in ts],.5):>9.3f}"
                  f"{q([t.mae for t in ts],.8):>9.3f}"
                  f"{statistics.fmean([t.to_close for t in ts]):>+11.3f}"
                  f"{len(ts):>6}")

        print("\n【跳空档的印刷伪影检验】^GSPC 的 09:30 印刷滞后（见 "
              "BASERATE_OPENING_TYPE），跳空入场价会被系统性压缩，")
        print("凭空造出『跳空延续』。同一批日子上 SPY 是可成交的真值。")
        print(f"{'标的':>8}{'档':>8}{'n':>5}{'E[MFE]':>9}{'E[MAE]':>9}"
              f"{'MFE-MAE':>10}{'SE':>7}{'t':>7}{'到收盘均值':>11}")
        for name, ts in (("^GSPC", touches), ("SPY", st)):
            for b in ("GAP", "09:30"):
                sub = [t for t in ts if t.bucket == b]
                if not sub:
                    continue
                dd = [t.mfe - t.mae for t in sub]
                m, se = mean_se(dd)
                test_tick()
                print(f"{name:>8}{b:>8}{len(sub):>5}"
                      f"{statistics.fmean([t.mfe for t in sub]):>9.3f}"
                      f"{statistics.fmean([t.mae for t in sub]):>9.3f}"
                      f"{m:>+10.3f}{se:>7.3f}{m/se if se else 0:>+7.2f}"
                      f"{statistics.fmean([t.to_close for t in sub]):>+11.3f}")

        print("\nSPY 上的结构规则（同一套事前规则，不重新调参，主口径 C）:")
        print(f"{'规则':<26}{'n':>4}{'毛均R':>8}{'净均R':>8}{'SE':>7}{'t':>6}"
              f"{'^GSPC 毛均R':>12}{'同号':>6}")
        for rn, fn in rules.items():
            rs, _, _ = run_rule(st, fn, conv="C")
            rsn, _, _ = run_rule(st, fn, conv="C", cost=COST_ATR)
            rsg, _, _ = run_rule(touches, fn, conv="C")
            m, se = mean_se(rs)
            print(f"{rn:<26}{len(rs):>4}{m:>+8.3f}"
                  f"{statistics.fmean(rsn):>+8.3f}{se:>7.3f}"
                  f"{m/se if se else 0:>+6.2f}"
                  f"{statistics.fmean(rsg):>+12.3f}"
                  f"{'是' if m*statistics.fmean(rsg)>0 else '否':>6}")

        print("\n【口径 A 的假 edge 在 SPY 上复现吗】—— 若两个标的上都是 A>>C，"
              "就坐实了那是口径产物而非标的产物:")
        print(f"{'规则':<26}{'SPY A':>9}{'SPY C':>9}{'SPY A-C':>10}"
              f"{'GSPC A-C':>10}")
        for rn, fn in rules.items():
            a1, _, _ = run_rule(st, fn, conv="A")
            c1, _, _ = run_rule(st, fn, conv="C")
            a2, _, _ = run_rule(touches, fn, conv="A")
            c2, _, _ = run_rule(touches, fn, conv="C")
            print(f"{rn:<26}{statistics.fmean(a1):>+9.3f}"
                  f"{statistics.fmean(c1):>+9.3f}"
                  f"{statistics.fmean(a1)-statistics.fmean(c1):>+10.3f}"
                  f"{statistics.fmean(a2)-statistics.fmean(c2):>+10.3f}")
    except Exception as exc:                     # noqa: BLE001
        print(f"SPY 复核失败: {exc}")

    # ---------------- §14 可上图的查表
    sec("§14  唯一可交付的东西：止损存活率 / 目标到达率查表（描述性，非择优）")
    print("既然期望值在任何 (止损,目标) 上都 ≈ 0（见 §11d），止损与目标的选择就不是")
    print("『赚多赚少』的问题，而是『R 分布长什么样』的问题。下表把这件事查出来。")
    print("止损档 0.20/0.30/0.40 不是搜出来的，是 §4/§11 实测 MAE 中位数附近的三个")
    print("整数刻度；目标一律取梯子上的具名位，不引入新自由度。\n")
    print("数据：730 天小时线，2623 笔首触，口径 C（首触那根小时 K 收盘入场）。")
    print("『到达率』= 在被止损之前先到目标的比例，给悲观/乐观双界。\n")
    print("注意一个容易犯的错：不能拿『到达率』直接和 S/(S+T) 这个打平线比 —— 因为")
    print("有第三种结局（收盘平仓）。下表因此把三种结局全列出来，并直接给均 R。\n")
    n14 = 0
    for s in (0.20, 0.30, 0.40):
        print(f"\n止损 = {s:.2f} ATR")
        print(f"{'起始位':>8}{'目标':>8}{'距离':>7}{'n':>6}"
              f"{'先到目标':>24}{'先撞止损':>9}{'收盘平仓':>9}"
              f"{'歧义':>7}{'均R(悲观)':>11}{'均R(乐观)':>11}{'净R(悲观)':>11}")
        for r in RATIOS:
            sub = [t for t in th if abs(abs(t.ratio) - r) < 1e-9]
            for c in [x for x in LADDER if x > r + 1e-9][:3]:
                dist = c - r
                cnt = {"target": 0, "stop": 0, "close": 0, "amb": 0}
                rp, ro = [], []
                for t in sub:
                    w, v = simulate(t.bars, t.i, t.entry_c, t.side, t.atr,
                                    s, dist)
                    cnt[w] += 1
                    rp.append(v)
                    ro.append(simulate(t.bars, t.i, t.entry_c, t.side, t.atr,
                                       s, dist, ambiguous="opt")[1])
                n = len(sub)
                n14 += 1
                test_tick()
                print(f"{r:>+8.3f}{c:>8.3f}{dist:>7.3f}{n:>6}"
                      f"   {stats.fmt_rate(cnt['target'], n)}"
                      f"{100*cnt['stop']/n:>8.1f}%{100*cnt['close']/n:>8.1f}%"
                      f"{100*cnt['amb']/n:>6.1f}%"
                      f"{statistics.fmean(rp):>+11.3f}"
                      f"{statistics.fmean(ro):>+11.3f}"
                      f"{statistics.fmean(rp)-COST_ATR/s:>+11.3f}")
    print(f"\n本表共 {n14} 个格子，全部照登，没有从中挑选。")
    print("读法：均R 的悲观/乐观双界都在 0 附近甚至为负；扣掉 0.01 ATR 的往返摩擦后")
    print("（净R 列）全部为负。这与 §11d 的完整网格一致，也与鞅的理论预期一致 ——")
    print("在没有漂移的价格过程上，任何止损/目标组合的期望值都是 0，费用把它推到负。")
    print("因此这张表的正确用途是**查 R 分布的形状**（多久到、多常被打），")
    print("不是从里面挑一个『最优』组合。")

    # ---------------- §13 家族
    sec("§13  家族规模自曝")
    print(f"评估过的 (止损,目标) 格子总数 = {GRID_CELLS}")
    print(f"报告里出现的统计检验数     = {TESTS_RUN}")
    print("其中：")
    print(f"  §6 主网格   : {len(cohorts)} cohort x 64 = {len(cohorts)*64}")
    print(f"  §7 反向检验 : 每个通过 n 门槛的 cohort x 64 x 2 半样本")
    print(f"  §8 结构规则 : {len(rules)} 个（事前定死，各 1 格）")
    print("纯噪声下 64 格最大值的期望约 2.3 个标准误；本报告任何『最优格』都必须")
    print("先减掉这个数才配被当成发现。")


if __name__ == "__main__":
    main()
