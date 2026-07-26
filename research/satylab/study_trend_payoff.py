"""趋势条件下的位：赔率结构检验（第二轮）

第一轮只测了"频率/方向"，从来没测过"赔率结构"。本脚本逐条检验用户的两条主张：

  主张一  「趋势肯定是主导的，一旦有趋势的时候它就有价值。」
          → 趋势状态下，顺趋势方向的位突破，是否跑赢**几何零假设**？
          → 趋势状态下，位的穿越是否更"干净"（假突破更少）？

  主张二  「趋势在关键位出现反转，往往能带来很高的盈亏比，胜率不需要高。」
          → 用**期望值**判定，不用胜率判定。

三个必须同时守住的统计学事实，写死在本脚本的检验逻辑里：

  (1) 无漂移随机游走、止损 S 目标 T 时 P(先到目标) = S/(S+T)，
      而该几何的打平胜率也恰好是 S/(S+T)。所以**高盈亏比本身不产生期望值**。
      正确零假设是 S/(S+T)，不是 0.50。S 与 T 逐笔不同 → 逐笔算 p0，
      用 Poisson-binomial 而不是单一比例检验。

  (2) 更强的一条：对**任何有界停时规则**（含"收盘平仓"这种时间止损），
      鞅的可选停时定理给出 **E[R] = 0**。所以本脚本的**判决量是 E[R]**，
      不是胜率。胜率对 S/(S+T) 的比较只作为诊断（因为有收盘时间限制，
      实际到达率必然低于无时限的 S/(S+T)，直接比会系统性低估）。

  (3) 因此还需要一个**时间匹配的经验零假设**：同一交易日、同一方向、
      同样的 S/T（ATR 单位）、同样的收盘时限，但**入场时刻随机**。
      这条安慰剂同时吃掉了"当天有没有行情"和"收盘时限"两个混淆项，
      是判断"位本身有没有特殊性"的唯一干净基准。

数据分辨率（硬约束）：
  路径判定**只能**用 5 分钟数据。本样本 SPY 5m，59 个有位图的完整 RTH 交易日。
  5m 单根 K 振幅中位 0.073 ATR、p90 0.162 ATR，与梯子相邻档间距 0.118~0.168 ATR
  同量级 → 即使 5m 也有同根 K 歧义，全部报告悲观/乐观双界与歧义率。
  1h 单根 K 振幅中位 0.270 ATR —— **大于整个止损距离**，不能用于路径判定，
  只在 §5 作为"双界都同号才算数"的粗查。
  日线一律用 SPY（^GSPC 日线开盘价已证实分段失真，本脚本任何地方都不碰）。

运行： .venv/bin/python research/satylab/study_trend_payoff.py
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, indicators, levels, stats  # noqa: E402

SEED = 20260726
COST_ATR = 0.01          # 单笔往返摩擦（标的口径），ATR 单位
PLACEBO_M = 40           # 每笔真实交易配多少个随机入场安慰剂

# 风险下限。位锚定的止损（stop = 位价 ± S·ATR）在"首触 K 收盘正好贴着止损"时
# 会把 S_eff 压到接近 0，R = 盈亏/S 随之爆炸（首轮实测出现过单笔 +194R）。
# 那种成交在真实盘口里不存在（点差/滑点就吃掉整个风险）。因此设地板：
# 任何交易的实际风险不得小于 MIN_S ATR；地板生效的次数逐格报告。
MIN_S = 0.05
MIN_T = 0.05

# 全局家族计数器 —— 任何"最优格子"必须连同看过多少格子一起报告
CELLS = 0
TESTS = 0


def cell(n: int = 1) -> None:
    global CELLS
    CELLS += n


def test(n: int = 1) -> None:
    global TESTS
    TESTS += n


# ---------------------------------------------------------------- 梯子

LADDER = (0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.618)
FULL_LADDER = tuple(sorted({r for x in LADDER for r in (x, -x)}))
ENTRY_RATIOS = (0.236, 0.382, 0.500, 0.618, 0.786)


def rung_beyond(ratio: float, side: int, gap: float) -> float:
    """从**入场价所在的比例** ratio 出发，沿 side 方向至少 gap ATR 之外的第一个梯级。

    为什么不是简单的"位的下一档"：首触那根 K 常常直接冲过整整一档收在下一档附近，
    此时"下一档"已被入场价越过，那笔交易就会被丢弃 —— 而被丢掉的恰好是**最干净的
    趋势突破**。首版脚本因此丢了 33% 的事件，方向上系统性不利于用户的主张。
    改成"入场价之外的第一个梯级"后不再丢事件。

    必须在**带符号的完整梯子**上找（0 两侧都要），否则从 +0.39 往下找会直接跳过
    +0.236 落到锚上 —— 这个错误让 T1(反向下一梯级) 与 T2(锚) 变成同一个目标。
    """
    a = side * ratio                       # 入场价沿方向的坐标
    for c in FULL_LADDER:                  # FULL_LADDER 对称，side 变换后仍是它自己
        if c > a + gap - 1e-9:
            return side * c
    c = FULL_LADDER[-1]
    while c <= a + gap:
        c += 0.236
    return side * c


# ---------------------------------------------------------------- 小工具

def q(xs, p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = int(math.floor(k))
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def cluster_mean_se(rs: list[float], days: list) -> tuple[float, float]:
    """按交易日聚类的均值标准误（日内多笔共享同一段行情，不能当独立样本）。"""
    n = len(rs)
    if n == 0:
        return (float("nan"), float("nan"))
    m = statistics.fmean(rs)
    by = defaultdict(float)
    for r, d in zip(rs, days):
        by[d] += (r - m)
    if len(by) < 2:
        return (m, float("nan"))
    var = sum(v * v for v in by.values()) / (n * n)
    # 小样本自由度修正
    G = len(by)
    var *= G / (G - 1)
    return (m, math.sqrt(var))


def day_block_boot(rs: list[float], days: list, iters: int = 4000,
                   seed: int = SEED) -> tuple[float, float]:
    by = defaultdict(list)
    for r, d in zip(rs, days):
        by[d].append(r)
    keys = list(by)
    if len(keys) < 3:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        flat = []
        for _ in keys:
            flat.extend(by[keys[rng.randrange(len(keys))]])
        if flat:
            out.append(statistics.fmean(flat))
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out))])


def poisson_binomial_z(hits: int, p0s: list[float]) -> tuple[float, float]:
    """H0: 每笔以 p0_i 独立命中（几何零假设）。返回 (期望命中数, z)。"""
    if not p0s:
        return (0.0, 0.0)
    mu = sum(p0s)
    var = sum(p * (1 - p) for p in p0s)
    if var <= 0:
        return (mu, 0.0)
    return (mu, (hits - mu) / math.sqrt(var))


def rank_test(reals: list[float], plcs: list[list[float]], days: list,
              label: str) -> tuple[float, float, float]:
    """可交换性秩检验 —— 比"真实 vs 安慰剂两比例 z"正确得多。

    每个真实事件，取它**自己那天、自己那个趋势态**里 M 个随机入场的分布，
    算真实值在其中的分位（并列各算一半）。若"位上这一刻"与同日同态的任意一刻
    可交换，该分位在 [0,1] 上均匀 → 均值 = 0.5。
    检验统计量按交易日聚类，样本量是**真实事件数**，不是被放大 M 倍的安慰剂数。
    """
    ranks, dd = [], []
    for v, pl, d in zip(reals, plcs, days):
        if not pl or v != v:
            continue
        lt = sum(1 for x in pl if x < v)
        eq = sum(1 for x in pl if x == v)
        ranks.append((lt + 0.5 * eq) / len(pl))
        dd.append(d)
    if len(ranks) < 5:
        print(f"  {label:<34} n<5，不检验")
        return (float("nan"),) * 3
    m, se = cluster_mean_se(ranks, dd)
    z = (m - 0.5) / se if se > 0 else float("nan")
    print(f"  {label:<34} 平均分位={m:.3f} (H0=0.500, 日聚类SE={se:.3f}, "
          f"z={z:+.2f}, n={len(ranks)})")
    return (m, se, z)


def rdist(rs: list[float]) -> str:
    if not rs:
        return "n=0"
    tot = sum(rs)
    mx = max(rs)
    share = f"{100*mx/tot:5.1f}%" if tot > 1e-9 else "n/a(总R≤0)"
    return (f"n={len(rs):<4} 均={statistics.fmean(rs):+.3f}R 中位={q(rs,.5):+.3f}R "
            f"p25={q(rs,.25):+.3f} p75={q(rs,.75):+.3f} p90={q(rs,.90):+.3f} "
            f"max={mx:+.2f}R 总={tot:+.1f}R 最大单笔占比={share}")


def sec(t: str) -> None:
    print("\n" + "=" * 84)
    print(t)
    print("=" * 84)


def sub(t: str) -> None:
    print("\n--- " + t + " " + "-" * max(0, 78 - len(t)))


# ---------------------------------------------------------------- 数据层

@dataclass
class Session:
    day: date
    bars: list
    L: object
    trend_ribbon: list       # 每根 K 的 ribbon 趋势态（用 i-1 的 EMA，无前视）
    trav_1030: float | None  # 10:30 时的 (close-anchor)/atr
    state_1030: dict         # 阈值 -> 'up'/'dn'/'chop'
    ema8: list = field(default_factory=list)   # 每根 K 收盘时的 EMA8（当根可用）


TRAV_THRESH = (0.15, 0.236, 0.382)


def build_sessions(sym: str = "SPY") -> tuple[dict, dict]:
    d = data.daily(sym, years="20y")
    lv = levels.build(d)
    f = [b for b in data.load(sym, "60d", "5m") if "09:30" <= b.hhmm < "16:00"]
    grp = data.group_by_day(f)
    days = [k for k in sorted(grp) if k in lv and len(grp[k]) >= 70]

    # ribbon 在**连续** RTH 序列上算（TradingView RTH 图就是这样），只在最开头预热
    flat = [b for day in days for b in grp[day]]
    closes = [b.close for b in flat]
    e8 = indicators.ema(closes, 8)
    e21 = indicators.ema(closes, 21)
    e34 = indicators.ema(closes, 34)

    def rib(k: int) -> str:
        """用 k-1 根的 EMA 判定，供第 k 根使用 —— 严格无前视。"""
        j = k - 1
        if j < 0 or e34[j] is None:
            return "na"
        a, b, c, px = e8[j], e21[j], e34[j], closes[j]
        if a > b > c and px > a:
            return "up"
        if a < b < c and px < a:
            return "dn"
        return "chop"

    out: dict[date, Session] = {}
    g = 0
    for day in days:
        bars = grp[day]
        tr = [rib(g + i) for i in range(len(bars))]
        g += len(bars)
        L = lv[day]
        pre = [b for b in bars if b.hhmm < "10:30"]
        trav = ((pre[-1].close - L.anchor) / L.atr) if pre else None
        st = {}
        for th in TRAV_THRESH:
            if trav is None:
                st[th] = "na"
            elif trav >= th:
                st[th] = "up"
            elif trav <= -th:
                st[th] = "dn"
            else:
                st[th] = "chop"
        out[day] = Session(day, bars, L, tr, trav, st,
                           e8[g - len(bars):g])
    return out, lv


# ---------------------------------------------------------------- 路径模拟

def simulate(bars, start: int, entry: float, side: int, stop_px: float,
             tgt_px: float) -> tuple[str, float, float]:
    """返回 (退出原因, 盈亏(价格单位), 歧义标记 1/0)。start 起算（不含入场根）。"""
    for j in range(start, len(bars)):
        b = bars[j]
        hs = (b.low <= stop_px) if side > 0 else (b.high >= stop_px)
        ht = (b.high >= tgt_px) if side > 0 else (b.low <= tgt_px)
        if hs and ht:
            return ("amb", 0.0, 1.0)
        if hs:
            return ("stop", side * (stop_px - entry), 0.0)
        if ht:
            return ("target", side * (tgt_px - entry), 0.0)
    return ("close", side * (bars[-1].close - entry), 0.0)


@dataclass
class Trade:
    day: date
    side: int
    S: float                 # ATR 单位，逐笔（已过地板）
    T: float
    p0: float                # 几何零假设 S/(S+T)
    why: str
    r_pess: float            # 歧义按止损
    r_opt: float             # 歧义按目标
    amb: float
    hit: int | None          # 1 目标 / 0 止损 / None 未解决（收盘或歧义）
    floored: int = 0         # 风险地板是否生效
    tag: str = ""


# 被 make_trade 丢弃的事件计数（按原因），逐格报告，不许静默
DROPS: dict = defaultdict(int)


def make_trade(sess: Session, i: int, entry: float, side: int,
               stop_px: float, tgt_px: float, tag: str = "",
               cost: float = COST_ATR) -> Trade | None:
    """side=+1 做多（止损在下、目标在上），side=-1 做空。

    风险地板：若 |入场-止损| < MIN_S·ATR，把止损推到 MIN_S 处。
    这样**不丢事件**（否则不同 S 的样本量不同 → 选择性偏差），
    同时杜绝 S→0 造成的 R 爆炸。
    """
    atr = sess.L.atr
    if i + 1 >= len(sess.bars):
        DROPS[tag + ":无后续K"] += 1
        return None
    floor_px = entry - side * MIN_S * atr
    if side > 0:
        stop_px = min(stop_px, floor_px)
    else:
        stop_px = max(stop_px, floor_px)
    floored = int(abs(stop_px - (entry - side * MIN_S * atr)) < 1e-12)
    T = side * (tgt_px - entry) / atr
    if T < MIN_T:
        DROPS[tag + ":目标已被入场价越过或过近"] += 1
        return None
    S = abs(entry - stop_px) / atr
    why, pnl, amb = simulate(sess.bars, i + 1, entry, side, stop_px, tgt_px)
    if why == "amb":
        rp, ro = -1.0, T / S
    else:
        rp = ro = pnl / (S * atr)
    rp -= cost / S
    ro -= cost / S
    hit = 1 if why == "target" else (0 if why == "stop" else None)
    return Trade(sess.day, side, S, T, S / (S + T), why, rp, ro, amb, hit,
                 floored, tag)


def summarize(trades: list[Trade], label: str, use: str = "pess",
              show_dist: bool = True) -> dict:
    """报告一个 cohort：E[R]（判决量）、几何零假设诊断、R 分布。"""
    if not trades:
        print(f"  {label:<34} n=0")
        return {"n": 0}
    rs = [(t.r_pess if use == "pess" else t.r_opt) for t in trades]
    days = [t.day for t in trades]
    m, se = cluster_mean_se(rs, days)
    lo, hi = day_block_boot(rs, days)
    res = [t for t in trades if t.hit is not None]
    hits = sum(t.hit for t in res)
    mu, z = poisson_binomial_z(hits, [t.p0 for t in res])
    amb = sum(t.amb for t in trades) / len(trades)
    flr = sum(t.floored for t in trades) / len(trades)
    drag = statistics.fmean([COST_ATR / t.S for t in trades])
    tval = m / se if se and se == se and se > 0 else float("nan")
    print(f"  {label:<34} n={len(trades):<4} E[R]={m:+.3f} "
          f"(日聚类SE={se:.3f}, t={tval:+.2f}, boot95=[{lo:+.3f},{hi:+.3f}]) "
          f"毛E[R]={m+drag:+.3f}")
    if res:
        print(f"  {'':34} 已解决 {len(res)}: 命中 {hits} = "
              f"{stats.fmt_rate(hits, len(res))} | 几何零假设期望命中 "
              f"{mu:.1f} (均p0={mu/len(res):.3f}) → z={z:+.2f}")
    print(f"  {'':34} 未解决(收盘/歧义) "
          f"{len(trades)-len(res)}/{len(trades)} | 同根K歧义率 {100*amb:.1f}%"
          f" | 风险地板生效 {100*flr:.1f}%")
    if show_dist:
        print(f"  {'':34} {rdist(rs)}")
    test(2)
    return {"n": len(trades), "mean_r": m, "se": se, "t": tval,
            "boot": (lo, hi), "hits": hits, "nres": len(res),
            "mu0": mu, "z0": z, "rs": rs, "days": days}


# ---------------------------------------------------------------- 事件构造

@dataclass
class Touch:
    day: date
    ratio: float
    side: int          # 延续方向
    i: int             # 首触 K 下标
    lvl_px: float
    close_i: float     # 首触 K 收盘（口径 C 的入场价）
    hhmm: str
    state_rib: str
    sess: Session = field(repr=False, default=None)


def first_touches(sessions: dict, ratios=ENTRY_RATIOS) -> list[Touch]:
    out = []
    for day in sorted(sessions):
        s = sessions[day]
        for r in list(ratios) + [-x for x in ratios]:
            side = 1 if r > 0 else -1
            px = s.L.at(r)
            for i, b in enumerate(s.bars):
                if (b.high >= px) if side > 0 else (b.low <= px):
                    out.append(Touch(day, r, side, i, px, b.close, b.hhmm,
                                     s.trend_ribbon[i], s))
                    break
    return out


# ---------------------------------------------------------------- 安慰剂

def placebo(sess: Session, side: int, S: float, T: float,
            state_filter: str | None, rng: random.Random,
            m: int = PLACEBO_M) -> list[Trade]:
    """同一天、同方向、同 S/T、同收盘时限，但入场时刻随机。"""
    idx = [i for i in range(len(sess.bars) - 2)]
    if state_filter is not None:
        idx = [i for i in idx if sess.trend_ribbon[i] == state_filter]
    if not idx:
        return []
    atr = sess.L.atr
    out = []
    for _ in range(m):
        i = idx[rng.randrange(len(idx))]
        e = sess.bars[i].close
        t = make_trade(sess, i, e, side, e - side * S * atr,
                       e + side * T * atr, tag="placebo")
        if t:
            out.append(t)
    return out


# ================================================================== 主体

def main() -> None:
    print("趋势条件下的位：赔率结构检验")
    print("确定性脚本（bootstrap / 安慰剂固定 seed=%d）" % SEED)

    sessions, lv = build_sessions("SPY")
    days = sorted(sessions)

    # ------------------------------------------------------------ §0
    sec("§0  数据与口径")
    allbars = [b for d in days for b in sessions[d].bars]
    rng5 = sorted((b.high - b.low) / sessions[b.day].L.atr for b in allbars)
    n5 = len(rng5)
    print(f"SPY 5m RTH: {len(allbars)} 根 / {len(days)} 个有位图交易日  "
          f"{days[0]} → {days[-1]}")
    print(f"5m 单根振幅/ATR: p50={rng5[n5//2]:.4f} p75={rng5[int(.75*n5)]:.4f} "
          f"p90={rng5[int(.90*n5)]:.4f} p99={rng5[int(.99*n5)]:.4f}")
    print("梯子间距(ATR): 0.236→0.382=0.146  0.382→0.500=0.118  "
          "0.500→0.618=0.118  0.618→0.786=0.168  0.786→1.000=0.214")
    print(">>> 5m 的 p90 振幅 0.162 ATR ≈ 一个档距 → 同根 K 歧义不可避免，"
          "全部给悲观/乐观双界。")
    print(f"摩擦: 每笔往返扣 {COST_ATR} ATR（≈SPY 5~7 分 / SPX 0.6~0.8 点）。"
          "注意 0DTE 期权的真实摩擦远大于此，本脚本测的是**标的结构**。")
    print("日线一律 SPY —— 全脚本不出现 ^GSPC 日线开盘价。")

    touches = first_touches(sessions)
    print(f"首触事件（±0.236/0.382/0.5/0.618/0.786，共 10 个位）: "
          f"{len(touches)}  平均 {len(touches)/len(days):.1f}/天")

    # ------------------------------------------------------------ §1
    sec("§1  两套趋势定义与它们的分布")

    sub("定义 D1 = ribbon 8/21/34（5m，用前一根的 EMA，逐根判定）")
    tb = stats.RateTable("ribbon 态在全部 5m K 上的占比")
    cnt = defaultdict(int)
    for d in days:
        for st in sessions[d].trend_ribbon:
            cnt[st] += 1
    tot = sum(cnt.values())
    for k in ("up", "dn", "chop", "na"):
        print(f"  {k:<6} {cnt[k]:>6}  {100*cnt[k]/tot:5.1f}%")
    print("  注：ribbon 态在**首触那一刻**的分布见 §2。")

    sub("定义 D2 = 10:30 已走幅度 (close_10:30 - 锚)/ATR")
    trav = [sessions[d].trav_1030 for d in days if sessions[d].trav_1030 is not None]
    print(f"  |已走幅度| 分布: p25={q([abs(x) for x in trav],.25):.3f} "
          f"p50={q([abs(x) for x in trav],.50):.3f} "
          f"p75={q([abs(x) for x in trav],.75):.3f} "
          f"p90={q([abs(x) for x in trav],.90):.3f}")
    for th in TRAV_THRESH:
        c = defaultdict(int)
        for d in days:
            c[sessions[d].state_1030[th]] += 1
        print(f"  阈值 {th:.3f}: 上趋势 {c['up']:>3} 天  下趋势 {c['dn']:>3} 天  "
              f"震荡 {c['chop']:>3} 天")
        cell()
    print("  D2 只用 10:30 之前的信息 → 只对 10:30 及之后的首触有效（无前视）。")

    # 两套定义彼此一致吗
    agree = tot_pair = 0
    for t in touches:
        s2 = t.sess.state_1030[0.236]
        if s2 == "na" or t.state_rib in ("na",):
            continue
        tot_pair += 1
        want = "up" if t.side > 0 else "dn"
        agree += int((t.state_rib == want) == (s2 == want))
    print(f"  D1 与 D2(0.236) 在首触时刻对『顺趋势与否』的判定一致率: "
          f"{stats.fmt_rate(agree, tot_pair)}")
    test()

    # ------------------------------------------------------------ §2
    sec("§2  主张一：趋势时，顺趋势的位突破跑赢几何零假设吗？")
    print("交易构造（口径 C，唯一自洽可执行）：")
    print("  入场 = 首触那根 5m K 的**收盘价**（不是位价 —— 位价成交是白送首触根的走势）")
    print("  目标 = 延续方向的下一档梯级")
    print("  止损两种，都报告：")
    print("    LVL  位锚定：stop = 位价 ∓ S·ATR  ← 用户主张里『位提供便宜证伪点』的那一种")
    print("    ENT  入场锚定：stop = 入场价 ∓ S·ATR  ← 无选择性、几何零假设最干净的一种")
    print("  零假设 = 逐笔 S/(S+T)，Poisson-binomial 汇总；判决量 = E[R]")

    STOPS = (0.05, 0.10, 0.15, 0.20)
    rngp = random.Random(SEED)

    def cont_target(t: Touch) -> float:
        er = t.sess.L.ratio_of(t.close_i)
        return t.sess.L.at(rung_beyond(er, t.side, MIN_T))

    def build_cont(ts: list[Touch], S: float, mode: str = "LVL") -> list[Trade]:
        out = []
        for t in ts:
            s = t.sess
            base = t.lvl_px if mode == "LVL" else t.close_i
            stop = base - t.side * S * s.L.atr
            tr = make_trade(s, t.i, t.close_i, t.side, stop, cont_target(t),
                            tag="cont")
            if tr:
                out.append(tr)
        return out

    # ---- 2.1 无条件基线
    sub("2.1  无条件（不分趋势）—— 先看基线")
    for mode in ("LVL", "ENT"):
        for S in STOPS:
            tr = build_cont(touches, S, mode)
            summarize(tr, f"全部首触  {mode} S={S:.2f}")
            cell()
    print(f"  丢弃事件: {dict(DROPS)}")

    # ---- 2.2 D1 分层
    sub("2.2  按 D1(ribbon 8/21/34) 分层：顺趋势 vs 逆趋势 vs 震荡")
    for S in STOPS:
        groups = {"顺趋势(ribbon同向)": [], "逆趋势(ribbon反向)": [], "震荡/未定": []}
        for t in touches:
            want = "up" if t.side > 0 else "dn"
            other = "dn" if t.side > 0 else "up"
            if t.state_rib == want:
                groups["顺趋势(ribbon同向)"].append(t)
            elif t.state_rib == other:
                groups["逆趋势(ribbon反向)"].append(t)
            else:
                groups["震荡/未定"].append(t)
        print(f"\n  [S={S:.2f}]")
        res = {}
        for k, ts in groups.items():
            res[k] = summarize(build_cont(ts, S), k)
            cell()
        a, b = res["顺趋势(ribbon同向)"], res["震荡/未定"]
        if a["n"] and b["n"]:
            za = stats.two_proportion_z(a["hits"], a["nres"], b["hits"], b["nres"])
            dm = a["mean_r"] - b["mean_r"]
            sed = math.sqrt((a["se"] or 0) ** 2 + (b["se"] or 0) ** 2)
            print(f"  → 顺趋势 vs 震荡: 命中率 z={za:+.2f} | "
                  f"ΔE[R]={dm:+.3f} (SE={sed:.3f}, z={dm/sed if sed>0 else 0:+.2f})")
            test(2)

    # ---- 2.3 D2 分层（只用 10:30 之后的首触）
    sub("2.3  按 D2(10:30 已走幅度) 分层：只取 10:30 及之后的首触")
    late = [t for t in touches if t.hhmm >= "10:30"]
    print(f"  10:30 及之后的首触: {len(late)} / {len(touches)}")
    for th in TRAV_THRESH:
        print(f"\n  [D2 阈值 {th:.3f}]")
        for S in (0.10, 0.15):
            groups = {"趋势日·顺向": [], "趋势日·逆向": [], "震荡日": []}
            for t in late:
                st = t.sess.state_1030[th]
                want = "up" if t.side > 0 else "dn"
                if st == "chop":
                    groups["震荡日"].append(t)
                elif st == want:
                    groups["趋势日·顺向"].append(t)
                elif st != "na":
                    groups["趋势日·逆向"].append(t)
            print(f"   S={S:.2f}")
            r = {}
            for k, ts in groups.items():
                r[k] = summarize(build_cont(ts, S), "   " + k)
                cell()
            a, b = r["趋势日·顺向"], r["震荡日"]
            if a["n"] and b["n"] and a["se"] and b["se"]:
                dm = a["mean_r"] - b["mean_r"]
                sed = math.sqrt(a["se"] ** 2 + b["se"] ** 2)
                print(f"   → 趋势日顺向 vs 震荡日: ΔE[R]={dm:+.3f} "
                      f"(z={dm/sed if sed>0 else 0:+.2f}) | 命中率 z="
                      f"{stats.two_proportion_z(a['hits'],a['nres'],b['hits'],b['nres']):+.2f}")
                test(2)

    # ---- 2.4 安慰剂：位到底特不特殊
    sub("2.4  时间匹配安慰剂 —— 同日同态同 S/T，入场时刻随机")
    print("  这一条回答的是：趋势里赚到的（如果有）是**位**给的，还是**当天有行情**给的。")
    print("  判决用**可交换性秩检验**（每笔与自己那天同态的 40 个随机入场比），")
    print("  不用两比例 z —— 安慰剂样本被放大 40 倍，两比例 z 的分母是假的。")
    for S in (0.10, 0.15):
        for want_state in ("up", "dn"):
            real, plc, plists = [], [], []
            for t in touches:
                if t.state_rib != want_state:
                    continue
                if (t.side > 0) != (want_state == "up"):
                    continue
                s = t.sess
                tgt = cont_target(t)
                stop = t.lvl_px - t.side * S * s.L.atr
                tr = make_trade(s, t.i, t.close_i, t.side, stop, tgt)
                if not tr:
                    continue
                pl = placebo(s, t.side, tr.S, tr.T, want_state, rngp)
                real.append(tr)
                plc.extend(pl)
                plists.append([x.r_pess for x in pl])
            lab = "顺势多头" if want_state == "up" else "顺势空头"
            print(f"\n  [S={S:.2f}] {lab}")
            a = summarize(real, "   位上真实入场")
            b = summarize(plc, "   同日同态随机入场(安慰剂)", show_dist=False)
            cell(2)
            rank_test([x.r_pess for x in real], plists,
                      [x.day for x in real], "   → R 的可交换性秩检验")
            test()

    # ---- 2.5 穿越干净度
    sub("2.5  穿越的『干净度』：趋势里假突破更少吗？")
    print("  干净 := 首触后，先到达下一档，而不是先回撤穿回位价 B ATR。")
    print("  （这就是 S=B 的赛跑，但这里单独报告，因为『假突破率』是用户的原话主张。）")
    for B in (0.05, 0.10, 0.15):
        rows = {}
        for lab, pick in (
                ("顺趋势(D1)", lambda t: t.state_rib == ("up" if t.side > 0 else "dn")),
                ("震荡/逆势(D1)", lambda t: t.state_rib != ("up" if t.side > 0 else "dn"))):
            k = n = 0
            p0s = []
            for t in touches:
                if not pick(t):
                    continue
                s = t.sess
                tgt = cont_target(t)
                stop = t.lvl_px - t.side * B * s.L.atr
                tr = make_trade(s, t.i, t.close_i, t.side, stop, tgt)
                if tr is None or tr.hit is None:
                    continue
                n += 1
                k += tr.hit
                p0s.append(tr.p0)
            mu, z = poisson_binomial_z(k, p0s)
            var = sum(p * (1 - p) for p in p0s)
            rows[lab] = (k, n, mu, z, var)
            print(f"  B={B:.2f}  {lab:<16} 干净穿越 {stats.fmt_rate(k, n)}  "
                  f"几何零假设 {100*mu/n if n else 0:5.1f}%  z={z:+.2f}")
            cell()
        (k1, n1, m1, _, v1) = rows["顺趋势(D1)"]
        (k2, n2, m2, _, v2) = rows["震荡/逆势(D1)"]
        raw = stats.two_proportion_z(k1, n1, k2, n2)
        # 几何调整后的差：两组的 S/(S+T) 本来就不同（趋势组首触 K 冲得更远 →
        # T 更大 → 零假设本来就更低）。直接比原始比例等于把几何差当成干净度差。
        d1, d2 = k1 - m1, k2 - m2
        num = d1 / n1 - d2 / n2
        den = math.sqrt(v1 / (n1 * n1) + v2 / (n2 * n2))
        print(f"        → 原始两比例 z={raw:+.2f}  ← 但两组零假设 "
              f"{100*m1/n1:.1f}% vs {100*m2/n2:.1f}%，几何本来就不同")
        print(f"        → **几何调整后**（各减自己的零假设）差 "
              f"{100*num:+.1f}pp, z={num/den if den>0 else 0:+.2f}  ← 这才是干净度检验")
        test(2)

    # ------------------------------------------------------------ §3
    sec("§3  主张二：趋势中在关键位反转 —— 用期望值判决，不用胜率")
    print("构造：趋势方向上（D1 ribbon 同向）触及位 L → **反手**做反方向。")
    print("  F1 即时反手：入场 = 首触 K 收盘，止损 = 位价外侧 S ATR")
    print("  F2 确认反手：等第一根**收回位内**的 5m K，入场 = 该 K 收盘，")
    print("               止损 = 触及以来的极值 + 0.02 ATR（这就是『便宜的证伪点』）")
    print("目标三档：T1 = 回撤方向上一梯级；T2 = 锚(PDC)；T3 = 反向 1.0 ATR")

    def rev_targets(t: Touch, entry: float) -> dict:
        """反向目标三档，全部相对**入场价**定义（同 §2，避免丢事件）。"""
        s = t.sess
        er = s.L.ratio_of(entry)
        return {"T1=反向下一梯级": s.L.at(rung_beyond(er, -t.side, MIN_T)),
                "T2=锚(PDC)": s.L.anchor,
                "T3=反向1ATR": entry - t.side * 1.0 * s.L.atr}

    trend_touch = [t for t in touches
                   if t.state_rib == ("up" if t.side > 0 else "dn")]
    print(f"\n顺趋势首触事件（D1）: {len(trend_touch)} / {len(touches)}")

    sub("3.1  F1 即时反手")
    f1_store = {}
    for S in (0.10, 0.15, 0.236):
        for tname in ("T1=反向下一梯级", "T2=锚(PDC)", "T3=反向1ATR"):
            trs = []
            for t in trend_touch:
                s = t.sess
                tgt = rev_targets(t, t.close_i)[tname]
                stop = t.lvl_px + t.side * S * s.L.atr
                tr = make_trade(s, t.i, t.close_i, -t.side, stop, tgt,
                                tag="F1")
                if tr:
                    trs.append(tr)
            f1_store[(S, tname)] = trs
            summarize(trs, f"S={S:.3f}  {tname}")
            cell()

    sub("3.2  F2 确认反手（结构止损 = 触及以来极值）")

    def confirm_bar(t: Touch, max_wait: int = 12) -> int | None:
        """首触之后第一根收回位内的 K。"""
        s = t.sess
        for j in range(t.i, min(t.i + max_wait + 1, len(s.bars) - 1)):
            c = s.bars[j].close
            if (c < t.lvl_px) if t.side > 0 else (c > t.lvl_px):
                return j
        return None

    f2_store = {}
    for wait in (6, 12):
        for tname in ("T1=反向下一梯级", "T2=锚(PDC)", "T3=反向1ATR"):
            trs = []
            nconf = 0
            for t in trend_touch:
                j = confirm_bar(t, wait)
                if j is None:
                    continue
                nconf += 1
                s = t.sess
                ext = (max(b.high for b in s.bars[t.i:j + 1]) if t.side > 0
                       else min(b.low for b in s.bars[t.i:j + 1]))
                stop = ext + t.side * 0.02 * s.L.atr
                tgt = rev_targets(t, s.bars[j].close)[tname]
                tr = make_trade(s, j, s.bars[j].close, -t.side, stop, tgt,
                                tag="F2")
                if tr:
                    trs.append(tr)
            f2_store[(wait, tname)] = trs
            summarize(trs, f"确认≤{wait}根  {tname}")
            print(f"  {'':34} 确认发生 {nconf}/{len(trend_touch)} = "
                  f"{100*nconf/max(1,len(trend_touch)):.1f}%")
            cell()

    sub("3.3  F3 ribbon 确认反手 —— 最贴近用户实际交易的那一种")
    print("  Saty 的 Vomy 第一步是『收盘跌破 8/13 EMA』，不是位本身。")
    print("  F3 = 顺趋势触位 → 等第一根**同时收在位内且收破 EMA8** 的 5m K → 反手。")

    def confirm_bar_rib(t: Touch, max_wait: int = 12) -> int | None:
        s = t.sess
        for j in range(t.i, min(t.i + max_wait + 1, len(s.bars) - 1)):
            c = s.bars[j].close
            e = s.ema8[j]
            if e is None:
                continue
            inside = (c < t.lvl_px) if t.side > 0 else (c > t.lvl_px)
            brk = (c < e) if t.side > 0 else (c > e)
            if inside and brk:
                return j
        return None

    f3_store = {}
    for wait in (6, 12):
        for tname in ("T1=反向下一梯级", "T2=锚(PDC)", "T3=反向1ATR"):
            trs, nconf = [], 0
            for t in trend_touch:
                j = confirm_bar_rib(t, wait)
                if j is None:
                    continue
                nconf += 1
                s = t.sess
                ext = (max(b.high for b in s.bars[t.i:j + 1]) if t.side > 0
                       else min(b.low for b in s.bars[t.i:j + 1]))
                stop = ext + t.side * 0.02 * s.L.atr
                tgt = rev_targets(t, s.bars[j].close)[tname]
                tr = make_trade(s, j, s.bars[j].close, -t.side, stop, tgt,
                                tag="F3")
                if tr:
                    trs.append(tr)
            f3_store[(wait, tname)] = trs
            summarize(trs, f"F3 确认≤{wait}根  {tname}")
            print(f"  {'':34} 确认发生 {nconf}/{len(trend_touch)} = "
                  f"{100*nconf/max(1,len(trend_touch)):.1f}%")
            cell()

    sub("3.4  F2 的止损/目标几何 —— 『便宜的证伪点』到底有多便宜")
    for wait in (6, 12):
        trs = f2_store[(wait, "T2=锚(PDC)")]
        if not trs:
            continue
        Ss = [t.S for t in trs]
        Ts = [t.T for t in trs]
        rr = [t.T / t.S for t in trs]
        p0 = [t.p0 for t in trs]
        print(f"  确认≤{wait}根 → S(ATR): p25={q(Ss,.25):.3f} p50={q(Ss,.50):.3f} "
              f"p75={q(Ss,.75):.3f}")
        print(f"  {'':16} T(ATR): p25={q(Ts,.25):.3f} p50={q(Ts,.50):.3f} "
              f"p75={q(Ts,.75):.3f}")
        print(f"  {'':16} 名义 R:R = T/S: p25={q(rr,.25):.2f} p50={q(rr,.50):.2f} "
              f"p75={q(rr,.75):.2f} p90={q(rr,.90):.2f}")
        print(f"  {'':16} 几何零假设胜率 p0 = S/(S+T): 均值 "
              f"{statistics.fmean(p0):.3f} → 这就是**打平线**")

    sub("3.5  反解：观测胜率要求的盈亏比 vs 实际拿到的盈亏比")
    print("  打平所需 R:R = (1-w)/w，w = 观测胜率（已解决样本）。")
    print("  ⚠ 关键更正：『实得 R:R』必须只在**赢的那些笔**上算 mean(T/S | 赢)。")
    print("     把 T/S 在全部已解决样本上取均值会系统性高估 —— 目标越近越容易赢，")
    print("     赢家天生是 T/S 小的那一批。下表把两者都印出来，差距本身就是证据。")
    print("  末列 E[R|已解决] = w·mean(T/S|赢) − (1−w)，这才是这一格真正的期望。")
    for key, store in (("F1", f1_store), ("F2", f2_store), ("F3", f3_store)):
        for k, trs in store.items():
            res = [t for t in trs if t.hit is not None]
            wins = [t for t in res if t.hit == 1]
            if len(res) < 15:
                continue
            w = len(wins) / len(res)
            need = (1 - w) / w if w > 0 else float("inf")
            got = statistics.fmean([t.T / t.S for t in wins]) if wins else 0.0
            naive = statistics.fmean([t.T / t.S for t in res])
            er = w * got - (1 - w)
            p0m = statistics.fmean([t.p0 for t in res])
            print(f"  {key} {str(k):<24} w={100*w:5.1f}% 打平需R:R={need:6.2f} "
                  f"赢家R:R={got:5.2f} (全样本均值{naive:5.2f}) "
                  f"E[R|已解决]={er:+.3f} 几何零假设w={100*p0m:5.1f}% "
                  f"→ {'过线' if er > 0 else '不过线'}")
            test()

    sub("3.6  完整 R 分布（不只是均值）—— 主张二自己要求的东西")
    for key, store, pick in (("F1", f1_store, (0.15, "T2=锚(PDC)")),
                             ("F2", f2_store, (12, "T2=锚(PDC)")),
                             ("F3", f3_store, (12, "T2=锚(PDC)"))):
        trs = store[pick]
        if not trs:
            continue
        rs = [t.r_pess for t in trs]
        ro = [t.r_opt for t in trs]
        print(f"  {key} {pick}")
        print(f"    悲观界 {rdist(rs)}")
        print(f"    乐观界 {rdist(ro)}")
        srt = sorted(rs, reverse=True)
        tot = sum(rs)
        if abs(tot) > 1e-9:
            print(f"    前 1 / 3 / 5 笔占总 R 的比例: "
                  f"{100*srt[0]/tot:.1f}% / {100*sum(srt[:3])/tot:.1f}% / "
                  f"{100*sum(srt[:5])/tot:.1f}%")
        print(f"    去掉最好 1 笔后 E[R] = "
              f"{statistics.fmean(srt[1:]) if len(srt)>1 else float('nan'):+.3f}")

    sub("3.7  对照：同样几何、同样趋势态，但入场时刻随机（安慰剂）")
    for S in (0.15,):
        for tname in ("T2=锚(PDC)",):
            real, plc, plists, rdays, rvals = [], [], [], [], []
            for t in trend_touch:
                s = t.sess
                tgt = rev_targets(t, t.close_i)[tname]
                stop = t.lvl_px + t.side * S * s.L.atr
                tr = make_trade(s, t.i, t.close_i, -t.side, stop, tgt,
                                tag="F1")
                if not tr:
                    continue
                pl = placebo(s, -t.side, tr.S, tr.T,
                             "up" if t.side > 0 else "dn", rngp)
                real.append(tr)
                plc.extend(pl)
                plists.append([x.r_pess for x in pl])
                rdays.append(tr.day)
                rvals.append(tr.r_pess)
            summarize(real, f"F1 位上反手 S={S} {tname}")
            summarize(plc, "   同日同态随机入场反手", show_dist=False)
            cell(2)
            rank_test(rvals, plists, rdays, "   → R 的可交换性秩检验")
            test()

    sub("3.8  不选止损也不选目标：位后的『逆行幅度』—— 带三重对照")
    print("  用户原话：『一旦到达这个位置，它带来的波动幅度很大』。")
    print("  这句话能在**完全不选 S/T** 的前提下检验：顺趋势触位之后，")
    print("  价格逆趋势方向最多走多远（ATR 单位）？")
    print("  但两个混淆项必须先掐死，否则任何正结果都是假的：")
    print("   (混淆 A) 剩余时间。触位时刻与随机时刻的『离收盘还有多久』不同，")
    print("            而逆行幅度随剩余时间单调增 → 固定窗口 H 根 K，两边都要求 H 根可用。")
    print("   (混淆 B) 触位=当日新极值。这是构造性的：在新高之后回撤当然比在随机点大。")
    print("            → 安慰剂 P2 只从**同样是当日新极值**的 K 里抽。")
    print("   另加 (对照 C) 安慰剂梯子：把整条梯子平移到非斐波那契比例，重跑同一检验。")
    print("            若平移后效应不变，那它测的是『新极值』，不是『位』。")

    def exc_h(sess: Session, i: int, entry: float, side: int, H: int,
              rev: bool) -> float:
        seg = sess.bars[i + 1:i + 1 + H]
        if len(seg) < H:
            return float("nan")
        if (side > 0) == rev:              # 多头的逆行 = 向下
            return (entry - min(b.low for b in seg)) / sess.L.atr
        return (max(b.high for b in seg) - entry) / sess.L.atr

    def new_extreme_idx(sess: Session, side: int) -> set:
        """当日截至该根为止的新高（side>0）/ 新低（side<0）。"""
        out, run = set(), None
        for k, b in enumerate(sess.bars):
            v = b.high if side > 0 else b.low
            if run is None or ((v > run) if side > 0 else (v < run)):
                run = v
                out.add(k)
        return out

    def touch_set(ratios) -> list[Touch]:
        ts = first_touches(sessions, ratios)
        return [t for t in ts if t.state_rib == ("up" if t.side > 0 else "dn")]

    def run_exc(ts: list[Touch], H: int, mode: str, rev: bool):
        """mode: P1 同态任意 K / P2 同态且当日新极值 / P3 同态且时刻相近(±6根)"""
        rr, ll, dd = [], [], []
        rg = random.Random(SEED + 7)
        for t in ts:
            s = t.sess
            v = exc_h(s, t.i, t.close_i, t.side, H, rev)
            if v != v:
                continue
            want = "up" if t.side > 0 else "dn"
            idx = [k for k in range(len(s.bars) - H - 1)
                   if s.trend_ribbon[k] == want]
            if mode == "P2":
                ex = new_extreme_idx(s, t.side)
                idx = [k for k in idx if k in ex]
            elif mode == "P3":
                idx = [k for k in idx if abs(k - t.i) <= 6 and k != t.i]
            if len(idx) < 3:
                continue
            pl = []
            for _ in range(PLACEBO_M):
                k = idx[rg.randrange(len(idx))]
                pl.append(exc_h(s, k, s.bars[k].close, t.side, H, rev))
            pl = [x for x in pl if x == x]
            if not pl:
                continue
            rr.append(v)
            ll.append(pl)
            dd.append(t.day)
        return rr, ll, dd

    print("\n  首触是不是当日新极值？（混淆 B 的严重程度）")
    isext = sum(1 for t in trend_touch
                if t.i in new_extreme_idx(t.sess, t.side))
    print(f"    顺趋势首触落在当日新极值 K 上的比例: "
          f"{stats.fmt_rate(isext, len(trend_touch))}  ← 接近 100% 就说明混淆 B 是致命的")

    for H in (12, 24):
        print(f"\n  [固定窗口 H={H} 根 5m = {H*5} 分钟]")
        for mode, desc in (("P1", "同态任意时刻"),
                           ("P2", "同态且同为当日新极值"),
                           ("P3", "同态且时刻相近(±30分钟)")):
            rr, ll, dd = run_exc(trend_touch, H, mode, rev=True)
            rank_test(rr, ll, dd, f"    逆行 vs {desc}")
            cell(); test()
        rr, ll, dd = run_exc(trend_touch, H, "P2", rev=False)
        rank_test(rr, ll, dd, "    顺行 vs 同态且同为当日新极值")
        cell(); test()

    print("\n  对照 C —— 安慰剂梯子（整条梯子平移，位不再是斐波那契数）")
    for shift, tag in ((0.0, "真梯子 0.236/0.382/0.500/0.618/0.786"),
                       (+0.05, "平移 +0.05"), (-0.04, "平移 -0.04"),
                       (+0.09, "平移 +0.09")):
        rs2 = tuple(round(r + shift, 4) for r in ENTRY_RATIOS)
        ts2 = touch_set(rs2)
        rr, ll, dd = run_exc(ts2, 24, "P2", rev=True)
        rank_test(rr, ll, dd, f"    {tag}")
        cell(); test()

    # ------------------------------------------------------------ §4
    sec("§4  功效：这个样本能查出多大的效应？")
    ref = f1_store[(0.15, "T2=锚(PDC)")]
    if ref:
        rs = [t.r_pess for t in ref]
        days_ = [t.day for t in ref]
        _, se = cluster_mean_se(rs, days_)
        print(f"  参考 cohort n={len(rs)}，日聚类 SE(E[R]) = {se:.3f}")
        print(f"  → 80% 功效下最小可测效应 (2.8×SE) ≈ {2.8*se:.3f} R/笔")
        print(f"  → 换句话说：小于 {2.8*se:.2f} R/笔的真实优势，本样本**测不出来**，"
              f"『没显著』不等于『没有』。")
    cont = build_cont(touches, 0.15)
    if cont:
        rs = [t.r_pess for t in cont]
        _, se = cluster_mean_se(rs, [t.day for t in cont])
        print(f"  §2 主 cohort n={len(rs)}，SE={se:.3f} → MDE ≈ {2.8*se:.3f} R/笔")

    # ------------------------------------------------------------ §5
    sec("§5  小时线粗查（730 天）—— 只看双界是否同号，不作判决")
    print("1h 单根振幅中位 0.270 ATR > 全部止损距离 → 路径判定不可信。")
    print("此处只做一件事：把 §2 的构造搬到 1h，看悲观界与乐观界是否同号。")
    dh = data.daily("SPY", years="20y")
    lvh = levels.build(dh)
    hb = [b for b in data.hourly("SPY") if "09:30" <= b.hhmm < "16:00"]
    hg = data.group_by_day(hb)
    hdays = [k for k in sorted(hg) if k in lvh and len(hg[k]) >= 6]
    closesh = [b.close for day in hdays for b in hg[day]]
    h8, h21, h34 = (indicators.ema(closesh, 8), indicators.ema(closesh, 21),
                    indicators.ema(closesh, 34))
    hsess = {}
    g = 0
    for day in hdays:
        bars = hg[day]
        tr = []
        for i in range(len(bars)):
            j = g + i - 1
            if j < 0 or h34[j] is None:
                tr.append("na")
            elif h8[j] > h21[j] > h34[j] and closesh[j] > h8[j]:
                tr.append("up")
            elif h8[j] < h21[j] < h34[j] and closesh[j] < h8[j]:
                tr.append("dn")
            else:
                tr.append("chop")
        g += len(bars)
        hsess[day] = Session(day, bars, lvh[day], tr, None, {})
    htouch = first_touches(hsess)
    print(f"  1h 首触事件: {len(htouch)} / {len(hdays)} 天")
    for lab, pick in (("顺趋势(1h ribbon)",
                       lambda t: t.state_rib == ("up" if t.side > 0 else "dn")),
                      ("其余", lambda t: t.state_rib != ("up" if t.side > 0 else "dn"))):
        for S in (0.15,):
            trs = []
            for t in htouch:
                if not pick(t):
                    continue
                s = t.sess
                tgt = cont_target(t)
                stop = t.lvl_px - t.side * S * s.L.atr
                tr = make_trade(s, t.i, t.close_i, t.side, stop, tgt)
                if tr:
                    trs.append(tr)
            if not trs:
                continue
            rp = [t.r_pess for t in trs]
            ro = [t.r_opt for t in trs]
            mp, sp = cluster_mean_se(rp, [t.day for t in trs])
            mo, so = cluster_mean_se(ro, [t.day for t in trs])
            amb = statistics.fmean([t.amb for t in trs])
            same = "同号" if mp * mo > 0 else "**变号 → 无结论**"
            print(f"  {lab:<18} S={S} n={len(trs):<5} 悲观E[R]={mp:+.3f}(SE{sp:.3f})  "
                  f"乐观E[R]={mo:+.3f}(SE{so:.3f})  歧义率={100*amb:.1f}%  {same}")
            cell()
            test()

    # ------------------------------------------------------------ §6
    sec("§6  家族计数")
    print(f"  本脚本共评估 {CELLS} 个格子，报告 {TESTS} 个统计检验。")
    print(f"  Bonferroni 门槛（双侧 5%，家族 {TESTS}）: |z| > "
          f"{abs(_norm_q(0.025 / max(1, TESTS))):.2f}")
    print("  全部格子已在上文逐一打印，无择优。")


def _norm_q(p: float) -> float:
    """标准正态分位（Acklam 近似，够用）。"""
    if p <= 0 or p >= 1:
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q_ = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q_+c[1])*q_+c[2])*q_+c[3])*q_+c[4])*q_+c[5]) / \
               ((((d[0]*q_+d[1])*q_+d[2])*q_+d[3])*q_+1)
    if p > 1 - pl:
        q_ = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q_+c[1])*q_+c[2])*q_+c[3])*q_+c[4])*q_+c[5]) / \
                ((((d[0]*q_+d[1])*q_+d[2])*q_+d[3])*q_+1)
    q_ = p - 0.5
    r = q_ * q_
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q_ / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


if __name__ == "__main__":
    main()
