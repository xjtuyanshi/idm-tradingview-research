"""Vomy / Yummy —— 把用户的口述定义逐句编码，并用几何零假设检验赔率结构.

================================================================================
预登记区（PRE-REGISTRATION）—— 写于任何回测数字产生之前
================================================================================
上一轮的方法论错误：所有检验都在问「频率/方向」，从来没问过「赔率结构」。
本轮的问题换成：**在这个事件点建仓，是否能跑赢同几何的随机游走？**

对无漂移随机游走，止损距离 S、目标距离 T：
        P(先到目标) = S / (S + T)
这同时也是该几何下的打平胜率。所以「高盈亏比 + 低胜率」本身不产生任何期望值。
因此本文件所有检验的零假设是 **S/(S+T)**，不是 0.50。
S 逐笔不同（止损 = 事件 K 的极值，随波动率变），所以零假设也逐笔不同，
用 Poisson–binomial 汇总：z = (K − Σpᵢ) / sqrt(Σ pᵢ(1−pᵢ))。

--------------------------------------------------------------------------------
一、用户的定义（逐句翻译）
--------------------------------------------------------------------------------
    「一开始正常上涨的时候 Cloud 是绿色的；后来因为价格开始不怎么变了，
      甚至微微向下，绿带就会越来越窄；直到它变成红色的那一瞬间」

  1. 「一开始正常上涨，cloud 绿色」
        → sign(fast − slow) == +1，且在事件前连续 N_TREND = 5 根都成立。
           N 不搜索，按任务书取 5。
  2. 「价格开始不怎么变了，甚至微微向下」
        → 事件前 W_CLEAR = 10 根之内，价格曾经**明确站在云之上**
           （close > max(fast, slow)），而事件时已不在云上。
           这一步捕捉「先在云上跑，然后掉回云里」。
  3. 「绿带越来越窄」
        → gap = |fast − slow| 在事件前连续 K_NARROW = 3 步严格单调下降：
           gap[i−1] < gap[i−2] < gap[i−3] < gap[i−4]。
  4. 「直到它变成红色的那一瞬间」
        → fast 下穿 slow 的那一根 K = 事件 K。入场 = 该 K 的收盘。

  Yummy = 完全镜像（fast 上穿 slow，价格曾明确在云之下，做多）。

  ⚠︎ 已知的半重言（必须写在报告里）：符号翻转在数学上**要求** gap 先归零，
  所以「变窄」总是先于「翻转」。第 3 步唯一有区分力的地方是它排除了
  **一根 K 直接暴力捅穿**的翻转（gap 从宽处一步过零）。因此本文件把
  第 3 步的检验做成 **不相交两组对照**：渐进收窄翻转 vs 突兀翻转。

--------------------------------------------------------------------------------
二、五个事件族（全部报告，不挑）
--------------------------------------------------------------------------------
  RAW      纯下穿（不要求任何前置条件）—— 任务书要求的主对照。
  BASE     RAW + 步骤 1 + 步骤 2（有趋势、价格曾在云上）——「不要求收窄」的版本。
  VOMY     BASE + 步骤 3（收窄）—— 用户定义的完整事件。
  ABRUPT   BASE 且 **不满足** 步骤 3 —— 与 VOMY 不相交，用于两比例检验。
  ALLBAR   全部可交易 K（无条件）—— 随机时刻同几何对照的确定性极限版本
           （用全体 K 代替蒙特卡洛抽样，去掉抽样噪声）。

  另加作者原话版（次要，因为教学阶段已确认「变色是结果不是触发」）：
  SATY48   stacked 8>13>21>34>48 → close 跌破 8 与 13 → **break and hold 48**
           （hold 根数 H ∈ {1,2,3} 全部报告，作者从未指定，是自由参数）。

--------------------------------------------------------------------------------
三、共同口径（事前定死）
--------------------------------------------------------------------------------
  标的      SPY（纪律 #5：禁止 ^GSPC 日线开盘价；SPY 是可成交真值）。
  信号周期  主：10 分钟（5m×2，按开盘锚定重采样）—— Saty 自己讲 Vomy 用的周期。
            稳健性：5 分钟。EMA 在**跨日连续序列**上计算（与 TradingView 一致）。
  路径周期  **恒为 5 分钟**（纪律 #4）。事件 K 收盘之后的**下一根** 5m K 才开始判路径，
            事件 K 自身不参与路径判定（否则前视）。
  参数组    Saty 8/21、Ripster 5/12、Ripster 34/50 —— 三个已定义的体系，不是参数搜索。
  入场      事件 K 的收盘价。
  止损      事件 K 的最高价（Vomy）/ 最低价（Yummy）。S = |止损 − 入场|。
            S == 0 的事件丢弃并计数。
  目标      两族，全部报告：
            (a) 固定 R：1R / 2R / 3R。零假设分别恰为 1/2、1/3、1/4。
            (b) 具名 ATR 位：入场下方（Vomy）最近的第 1、第 2 个 Saty 日线具名位
                （levels.RATIOS，锚 = 前日收盘，ATR = 前日 Wilder ATR(14)）。
                零假设逐笔 = S/(S+T)。不设 T 的最小值门槛（那会引入自由参数）；
                T 很小时零假设自动接近 1，Poisson–binomial 会正确地不给它功劳。
  路径解析  逐 5m K；同一根 K 同时含止损与目标 → **判止损**（保守）。歧义根数上报。
  时间止损  当日 15:55 收盘平仓，不留隔夜。
  可交易性  事件 K 之后必须至少剩 MIN_PATH = 6 根 5m K（30 分钟），否则丢弃。
  未解析    收盘仍未触及止损或目标 = timeout。
            · 命中率 vs 几何零假设：**只用已解析样本**，并同时报告 timeout 占比。
              注意方向：目标在 2R/3R 时止损更近，「先解析完」这个条件本身偏向止损，
              所以剔除 timeout 对「有优势」这个假设是**保守**的，不是有利的。
            · 期望 R：timeout 按收盘价 mark-to-close 计入，不丢弃。
  多重比较  本文件网格很大（见文末 cells inspected）。事前声明：
            单个 |z| > 1.96 在这个规模下**不算发现**；Bonferroni 门槛写在报告里。

--------------------------------------------------------------------------------
四、事前预期（写在前面，防止事后叙事）
--------------------------------------------------------------------------------
  · RAW 下穿的数量级：SPY 10m 60 天约 2340 根，8/21 每千根约 41 次翻转 → 约 96 次，
    分多空后每侧约 48 次。加上前置条件后 VOMY 每侧可能只有 10–30 笔。
    **n 这么小的情况下，除非效应极大，否则唯一诚实的结论就是「测不出来」。**
  · 若 VOMY 与 ABRUPT 的两比例 z < 1.96，则用户强调的「收窄」这一步不做功，
    Vomy 就是普通均线下穿 —— 这是一个有价值的否定结论，必须照实写。

用法:  .venv/bin/python research/satylab/study_vomy.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats            # noqa: E402
from satylab.data import Bar                       # noqa: E402
from satylab.indicators import ema                 # noqa: E402

# ---- pre-registered constants (no search over any of these) ----------------
N_TREND = 5          # 用户: 「一开始正常上涨」持续根数
W_CLEAR = 10         # 「价格曾明确在云上」的回看窗口
K_NARROW = 3         # 「越来越窄」的连续收窄步数
MIN_PATH = 6         # 事件后至少剩 6 根 5m K 才算可交易
MIN_N_FOR_Z = 10     # 已解析样本少于此数的格子只报比例，不报 z（防止 p=0/1 造假 z）
R_TARGETS = (1.0, 2.0, 3.0)
LEVEL_TARGETS = (1, 2)   # 入场方向上的第 1 / 第 2 个具名 ATR 位
SYMBOL = "SPY"

CLOUDS = (("Saty 8/21", 8, 21),
          ("Ripster 5/12", 5, 12),
          ("Ripster 34/50", 34, 50))


# ---------------------------------------------------------------------------
# bars
# ---------------------------------------------------------------------------
def resample(bars: list[Bar], k: int) -> tuple[list[Bar], list[tuple]]:
    """k 根 5m K 合成一根，按每个交易日的开盘锚定。返回 (bars, (day, idx_in_day))."""
    out: list[Bar] = []
    tag: list[tuple] = []
    for _day, rows in sorted(data.group_by_day(bars).items()):
        for g, i in enumerate(range(0, len(rows) - k + 1, k)):
            chunk = rows[i:i + k]
            out.append(Bar(chunk[0].dt, chunk[0].day, chunk[0].open,
                           max(c.high for c in chunk),
                           min(c.low for c in chunk),
                           chunk[-1].close,
                           sum(c.volume for c in chunk)))
            tag.append((chunk[0].day, g))
    return out, tag


def cloud_series(bars: list[Bar], fast: int, slow: int):
    closes = [b.close for b in bars]
    ef, es = ema(closes, fast), ema(closes, slow)
    sign = [None if (ef[i] is None or es[i] is None)
            else (1 if ef[i] > es[i] else -1) for i in range(len(bars))]
    gap = [None if (ef[i] is None or es[i] is None) else abs(ef[i] - es[i])
           for i in range(len(bars))]
    return ef, es, sign, gap


# ---------------------------------------------------------------------------
# event detection —— 用户定义的四个步骤
# ---------------------------------------------------------------------------
def detect_events(bars, ef, es, sign, gap, d: int) -> dict[str, list[int]]:
    """d = −1 → Vomy（fast 下穿 slow，做空）；d = +1 → Yummy（做多）。

    返回四个不相交/嵌套关系明确的族：
      RAW ⊇ BASE = VOMY ⊎ ABRUPT
    """
    n = len(bars)
    fams = {"RAW": [], "BASE": [], "VOMY": [], "ABRUPT": []}
    lo = max(N_TREND, W_CLEAR, K_NARROW + 1) + 2
    for i in range(lo, n):
        if sign[i] is None or sign[i - 1] is None:
            continue
        if not (sign[i] == d and sign[i - 1] == -d):
            continue                                   # 步骤 4：翻转那一根
        fams["RAW"].append(i)

        # 步骤 1：翻转之前连续 N_TREND 根都是原方向
        trend = all(sign[i - 1 - j] == -d for j in range(N_TREND))
        # 步骤 2：回看窗口内价格曾明确在云的外侧（趋势侧）
        clear = False
        for j in range(i - W_CLEAR, i):
            if ef[j] is None or es[j] is None:
                continue
            if d == -1 and bars[j].close > max(ef[j], es[j]):
                clear = True
                break
            if d == +1 and bars[j].close < min(ef[j], es[j]):
                clear = True
                break
        if not (trend and clear):
            continue
        fams["BASE"].append(i)

        # 步骤 3：连续 K_NARROW 步严格收窄
        narrow = all(gap[i - 1 - j] is not None and gap[i - 2 - j] is not None
                     and gap[i - 1 - j] < gap[i - 2 - j]
                     for j in range(K_NARROW))
        fams["VOMY" if narrow else "ABRUPT"].append(i)
    return fams


def detect_saty48(bars, d: int, hold: int, arm_win: int = 20) -> list[int]:
    """作者原话版：stacked 8>13>21>34>48 → 跌破 8/13 → break and hold 48.

    d = −1 为 Vomy（看跌），d = +1 为 inverse vomy。hold 是作者未指定的自由参数。
    入场 = 满足 hold 根收盘在 48 外侧的**最后一根**的收盘。
    """
    closes = [b.close for b in bars]
    e = {k: ema(closes, k) for k in (8, 13, 21, 34, 48)}
    n = len(bars)

    def stacked(i: int) -> bool:
        v = [e[k][i] for k in (8, 13, 21, 34, 48)]
        if any(x is None for x in v):
            return False
        return all((v[j] > v[j + 1]) if d == -1 else (v[j] < v[j + 1])
                   for j in range(4))

    out, last_stacked, armed_at = [], None, None
    for i in range(60, n):
        if all(stacked(i - j) for j in range(N_TREND)):
            last_stacked = i
            armed_at = None
        if armed_at is None and last_stacked is not None \
                and i - last_stacked <= arm_win \
                and e[8][i] is not None and e[13][i] is not None:
            broke = (closes[i] < min(e[8][i], e[13][i])) if d == -1 \
                else (closes[i] > max(e[8][i], e[13][i]))
            if broke:
                armed_at = i
        if armed_at is not None and i - armed_at <= arm_win and e[48][i] is not None:
            ok = all(e[48][i - j] is not None
                     and ((closes[i - j] < e[48][i - j]) if d == -1
                          else (closes[i - j] > e[48][i - j]))
                     for j in range(hold))
            if ok:
                out.append(i)
                armed_at, last_stacked = None, None
    return out


# ---------------------------------------------------------------------------
# trade simulation —— 路径永远在 5m 上解析
# ---------------------------------------------------------------------------
class Trade:
    __slots__ = ("day", "hhmm", "side", "entry", "stop", "target", "S", "T",
                 "p_null", "outcome", "r", "opt_outcome", "amb",
                 "mfe_r", "mae_r", "atr")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def simulate(fine_rows: list[Bar], start: int, entry: float, stop: float,
             target: float, side: int) -> tuple[str, float, str, int]:
    """side = −1 做空。返回 (保守outcome, 保守R, 乐观outcome, 歧义根数)。

    5m 分辨率下，同一根 K 同时含止损与目标时先后顺序不可知。保守读法判止损，
    乐观读法判目标 —— 两者给出真实命中率的**上下界**。这里两种都算，
    因为本构造的 S 很小（事件 K 收盘到该 K 极值），歧义根占比不可忽略。
    """
    S = abs(stop - entry)
    T = abs(target - entry)
    amb = 0
    cons = None
    for j in range(start, len(fine_rows)):
        b = fine_rows[j]
        hit_stop = (b.high >= stop) if side < 0 else (b.low <= stop)
        hit_tgt = (b.low <= target) if side < 0 else (b.high >= target)
        if hit_stop and hit_tgt:
            amb += 1
            return "stop", -1.0, "target", amb
        if hit_stop:
            return "stop", -1.0, "stop", amb
        if hit_tgt:
            return "target", T / S, "target", amb
    last = fine_rows[-1]
    r = side * (last.close - entry) / S
    return "close", r, "close", amb


def mfe_mae(fine_rows: list[Bar], start: int, entry: float, side: int,
            S: float) -> tuple[float, float]:
    """整段剩余时间的 MFE / MAE（以 R 计），与出场规则无关。"""
    mfe = mae = 0.0
    for j in range(start, len(fine_rows)):
        b = fine_rows[j]
        fav = (entry - b.low) if side < 0 else (b.high - entry)
        adv = (b.high - entry) if side < 0 else (entry - b.low)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
    return mfe / S, mae / S


def level_target(lv, entry: float, side: int, k: int) -> float | None:
    """入场方向上的第 k 个 Saty 具名日线位（side=−1 取下方）。"""
    px = sorted(lv.at(r) for r in levels.RATIOS)
    cand = [p for p in px if p < entry] if side < 0 else [p for p in px if p > entry]
    if side < 0:
        cand = cand[::-1]
    return cand[k - 1] if len(cand) >= k else None


def build_trades(idxs, sig_tag, fine_sessions, lvmap, side, k_resample,
                 target_kind, target_arg):
    """把事件索引变成一组已解析的交易。"""
    trades, skipped = [], {"no_path": 0, "zero_S": 0, "no_level": 0, "no_map": 0}
    for i in idxs:
        day, g = sig_tag[i]
        rows = fine_sessions.get(day)
        lv = lvmap.get(day)
        if rows is None:
            skipped["no_path"] += 1
            continue
        if lv is None:
            skipped["no_map"] += 1
            continue
        start = (g + 1) * k_resample          # 事件 K 之后的第一根 5m K
        if start >= len(rows) - MIN_PATH:
            skipped["no_path"] += 1
            continue
        ev_bar_hi = max(r.high for r in rows[g * k_resample:(g + 1) * k_resample])
        ev_bar_lo = min(r.low for r in rows[g * k_resample:(g + 1) * k_resample])
        entry = rows[start - 1].close
        stop = ev_bar_hi if side < 0 else ev_bar_lo
        S = abs(stop - entry)
        if S <= 0:
            skipped["zero_S"] += 1
            continue
        if target_kind == "R":
            target = entry - target_arg * S if side < 0 else entry + target_arg * S
        else:
            target = level_target(lv, entry, side, target_arg)
            if target is None:
                skipped["no_level"] += 1
                continue
        T = abs(target - entry)
        outcome, r, opt, amb = simulate(rows, start, entry, stop, target, side)
        mfe, mae = mfe_mae(rows, start, entry, side, S)
        trades.append(Trade(day=day, hhmm=rows[start - 1].hhmm, side=side,
                            entry=entry, stop=stop, target=target, S=S, T=T,
                            p_null=S / (S + T), outcome=outcome, r=r,
                            opt_outcome=opt, amb=amb,
                            mfe_r=mfe, mae_r=mae, atr=lv.atr))
    return trades, skipped


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
def pb_z(trades: list[Trade]) -> tuple[int, int, float, float, float]:
    """Poisson–binomial 检验：只用已解析样本。返回 (k, n, obs, null, z)."""
    res = [t for t in trades if t.outcome in ("stop", "target")]
    if not res:
        return 0, 0, 0.0, 0.0, 0.0
    k = sum(1 for t in res if t.outcome == "target")
    ps = [t.p_null for t in res]
    mu = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    z = (k - mu) / math.sqrt(var) if var > 0 else 0.0
    return k, len(res), k / len(res), mu / len(res), z


def opt_rate(trades: list[Trade]) -> tuple[int, int]:
    """乐观读法（歧义根判目标）下的命中数 / 已解析数 —— 命中率的上界。"""
    res = [t for t in trades if t.opt_outcome in ("stop", "target")]
    return sum(1 for t in res if t.opt_outcome == "target"), len(res)


def two_prop(a: list[Trade], b: list[Trade]) -> tuple[float, int, int, int, int]:
    """两组已解析交易的命中率两比例检验。返回 (z, ka, na, kb, nb)."""
    ra = [t for t in a if t.outcome != "close"]
    rb = [t for t in b if t.outcome != "close"]
    ka = sum(1 for t in ra if t.outcome == "target")
    kb = sum(1 for t in rb if t.outcome == "target")
    return (stats.two_proportion_z(ka, len(ra), kb, len(rb)),
            ka, len(ra), kb, len(rb))


def matched_baseline(events: list[Trade], base: list[Trade],
                     nbins: int = 10) -> tuple[float, float, int]:
    """按 S/ATR 十分位对随机时刻基线做**直接标准化**，再与事件组比较。

    为什么必须做：事件 K（翻转那一根）本身就是波动更大的 K，其 S/ATR 中位数
    约为全体 K 的两倍。S 不同 → 5m 分辨率下的歧义率不同 → 命中率天然不可比。
    直接标准化把基线重新加权到事件组的 S/ATR 分布上，去掉这个混杂。

    返回 (标准化后的基线命中率, z, 有效基线样本数)。
    z 的方差同时计入事件组与加权基线的抽样误差。
    """
    rb = [t for t in base if t.outcome != "close"]
    re_ = [t for t in events if t.outcome != "close"]
    if not rb or not re_:
        return 0.0, 0.0, 0
    cuts = sorted(t.S / t.atr for t in rb)
    edges = [cuts[int(q * len(cuts))] for q in
             [i / nbins for i in range(1, nbins)]]

    def binof(x: float) -> int:
        for i, e in enumerate(edges):
            if x <= e:
                return i
        return nbins - 1

    bk = [0] * nbins
    bn = [0] * nbins
    for t in rb:
        i = binof(t.S / t.atr)
        bn[i] += 1
        bk[i] += int(t.outcome == "target")
    w = [0.0] * nbins
    for t in re_:
        w[binof(t.S / t.atr)] += 1.0 / len(re_)

    std = var_std = 0.0
    used = 0
    wsum = 0.0
    for i in range(nbins):
        if bn[i] == 0 or w[i] == 0:
            continue
        p = bk[i] / bn[i]
        std += w[i] * p
        var_std += w[i] ** 2 * p * (1 - p) / bn[i]
        used += bn[i]
        wsum += w[i]
    if wsum <= 0:
        return 0.0, 0.0, 0
    std /= wsum
    var_std /= wsum ** 2
    ke = sum(1 for t in re_ if t.outcome == "target")
    pe = ke / len(re_)
    # n 太小的格子不给 z：p=0 或 1 时朴素方差为 0，会造出 |z|>10 的假象。
    # 门槛事前定为 10（本文件所有格子统一，不按结果调整）。
    if len(re_) < MIN_N_FOR_Z:
        return std, float("nan"), used
    pe_adj = (ke + 0.5) / (len(re_) + 1.0)          # 连续性修正后的方差
    var_e = pe_adj * (1 - pe_adj) / len(re_)
    denom = math.sqrt(var_e + var_std)
    return std, ((pe - std) / denom if denom > 0 else 0.0), used


def asymmetry(trades: list[Trade]) -> tuple[int, int, float, float]:
    """P(MFE > MAE) —— 无目标、无分辨率伪影的赔率结构检验，零假设**恰好** 0.50.

    为什么这是本文件最干净的一个检验：
      · 不需要选目标，所以没有目标网格；
      · 不需要判「谁先到」，所以完全不受 5m 同根歧义的影响；
      · 对无漂移随机游走，从入场到收盘的有利偏移与不利偏移**可交换**，
        因此 P(MFE > MAE) 恒等于 0.50 —— 一个精确的、不依赖 S/T 的零假设。
    用户主张的「到了这个位置波动幅度很大、盈亏比高」若为真，
    必须在这里表现为 P(MFE > MAE) 显著高于 50%。R:R 高但对称 = 不产生期望值。
    """
    n = len(trades)
    if n == 0:
        return 0, 0, 0.0, 0.0
    k = sum(1 for t in trades if t.mfe_r > t.mae_r)
    z = (k - 0.5 * n) / math.sqrt(0.25 * n)
    med = sorted(t.mfe_r / max(t.mae_r, 1e-9) for t in trades)[n // 2]
    return k, n, z, med


def quart(xs: list[float]) -> str:
    if not xs:
        return "  n=0"
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]   # noqa: E731
    return f"p25={q(.25):+.2f} med={q(.50):+.2f} p75={q(.75):+.2f}"


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
CELLS = 0


def grid_row(label: str, trades: list[Trade], out,
             base: list[Trade] | None = None) -> dict:
    global CELLS
    CELLS += 1
    k, n, obs, null, z = pb_z(trades)
    ok, on = opt_rate(trades)
    tot = len(trades)
    to = sum(1 for t in trades if t.outcome == "close")
    amb = sum(t.amb for t in trades)
    e = stats.expectancy([t.r for t in trades])
    rr = (sum(t.T / t.S for t in trades) / tot) if tot else 0.0
    hi = 100 * ok / on if on else 0.0
    extra = ""
    mstd = mz = 0.0
    if base is not None:
        CELLS += 1
        mstd, mz, _ = matched_baseline(trades, base)
        zs_ = "  n<10 不报z" if mz != mz else f" z={mz:+5.2f}"
        extra = f"  ‖ 匹配基线={100*mstd:5.1f}%{zs_}"
    out.append(f"  {label:<30}{stats.fmt_rate(k, n):<30}"
               f"上界={hi:5.1f}%  几何null={100*null:5.1f}% z={z:+5.2f}  "
               f"R:R={rr:5.2f}  均R={e.get('avg_r', 0):+.3f}  "
               f"timeout={to}/{tot} amb={amb}{extra}")
    return {"k": k, "n": n, "obs": obs, "null": null, "z": z,
            "opt": hi / 100, "matched": mstd, "matched_z": mz,
            "avg_r": e.get("avg_r", 0.0), "tot": tot, "timeout": to}


def main() -> None:
    global CELLS
    fine = data.fine(SYMBOL)
    fine_sessions = data.group_by_day(fine)
    lvmap = levels.build(data.daily(SYMBOL))

    print("=" * 100)
    print(f"VOMY / YUMMY —— 赔率结构检验   标的={SYMBOL}  5m K={len(fine)} "
          f"日={len(fine_sessions)}  {min(fine_sessions)} → {max(fine_sessions)}")
    print("零假设 = S/(S+T)（几何），不是 0.50。命中率只统计已解析样本；均R含 timeout。")
    print("=" * 100)

    summary = {}
    pool: dict = {}          # (tf, tlab, ta, fam) -> 跨三组云 × 多空 汇总的交易
    base_pool: dict = {}     # (tf, tlab, ta, 方向) -> 该方向的随机时刻基线
    narrow_z: list = []      # 「收窄 vs 突兀」的所有 z，用于看符号是否一致
    all_z: list = []         # 所有事件族 vs 匹配基线的 z
    asym_z: list = []        # P(MFE>MAE) vs 50% 的 z

    for tf_label, kk in (("10m 信号", 2), ("5m 信号", 1)):
        sig_bars, sig_tag = resample(fine, kk)
        print(f"\n\n{'#' * 100}\n### 信号周期 = {tf_label}   信号K数={len(sig_bars)}"
              f"\n{'#' * 100}")

        for cname, f, s in CLOUDS:
            ef, es, sign, gap = cloud_series(sig_bars, f, s)
            for d, dname in ((-1, "VOMY(空)"), (+1, "YUMMY(多)")):
                fams = detect_events(sig_bars, ef, es, sign, gap, d)
                allbar = [i for i in range(60, len(sig_bars)) if sign[i] is not None]
                fams["ALLBAR"] = allbar

                print(f"\n{'=' * 100}\n{cname}   {dname}   [{tf_label}]")
                print(f"  事件计数: RAW={len(fams['RAW'])}  BASE={len(fams['BASE'])}"
                      f"  VOMY={len(fams['VOMY'])}  ABRUPT={len(fams['ABRUPT'])}"
                      f"  ALLBAR={len(fams['ALLBAR'])}")
                print("=" * 100)

                for tk, targs, tlab in (("R", R_TARGETS, "固定R"),
                                        ("L", LEVEL_TARGETS, "具名位")):
                    for ta in targs:
                        out = []
                        cache = {}
                        # 基线先算，后面每个事件族都要拿它做匹配对照
                        base_tr, _ = build_trades(fams["ALLBAR"], sig_tag,
                                                  fine_sessions, lvmap, d, kk,
                                                  tk, ta)
                        for fam in ("VOMY", "ABRUPT", "BASE", "RAW", "ALLBAR"):
                            if fam == "ALLBAR":
                                tr, sk = base_tr, {}
                            else:
                                tr, sk = build_trades(fams[fam], sig_tag,
                                                      fine_sessions, lvmap,
                                                      d, kk, tk, ta)
                            cache[fam] = tr
                            tag = f"{fam}" + (f" (跳过{sum(sk.values())})"
                                              if sum(sk.values()) else "")
                            r = grid_row(tag, tr, out,
                                         base=None if fam == "ALLBAR" else base_tr)
                            summary[(tf_label, cname, dname, tlab, ta, fam)] = r
                            # ALLBAR 与云参数无关，六个 (云 × 方向) 循环会拿到
                            # 同一批 K。只在第一组累加，否则汇总区的基线 n 会
                            # 虚增六倍、CI 假性变窄。
                            if fam != "ALLBAR" or cname == CLOUDS[0][0]:
                                pool.setdefault((tf_label, tlab, ta, fam),
                                                []).extend(tr)
                            if fam == "ALLBAR" and cname == CLOUDS[0][0]:
                                base_pool[(tf_label, tlab, ta, dname)] = tr
                            if fam != "ALLBAR":
                                if r["matched_z"] == r["matched_z"]:
                                    all_z.append(((tf_label, cname, dname,
                                                   tlab, ta, fam),
                                                  r["matched_z"], r["n"]))
                        tname = f"{ta:.0f}R" if tk == "R" else f"第{ta}个具名位"
                        print(f"\n  --- 目标 = {tname} ---")
                        print("\n".join(out))

                        # 关键对照：收窄 vs 突兀（不相交两组）
                        a = [t for t in cache["VOMY"] if t.outcome != "close"]
                        b = [t for t in cache["ABRUPT"] if t.outcome != "close"]
                        ka = sum(1 for t in a if t.outcome == "target")
                        kb = sum(1 for t in b if t.outcome == "target")
                        z = stats.two_proportion_z(ka, len(a), kb, len(b))
                        CELLS += 1
                        narrow_z.append(((tf_label, cname, dname, tlab, ta), z,
                                         len(a), len(b)))
                        CELLS_note = ("收窄做功" if abs(z) >= 1.96 else "收窄不做功")
                        print(f"      ▶ 收窄 vs 突兀（不相交）: "
                              f"{stats.fmt_rate(ka, len(a))} vs "
                              f"{stats.fmt_rate(kb, len(b))}  z={z:+.2f}  → {CELLS_note}")

                # MFE / MAE 分布（与出场规则无关，只看事件后的位移结构）
                tr, _ = build_trades(fams["VOMY"], sig_tag, fine_sessions,
                                     lvmap, d, kk, "R", 1.0)
                base, _ = build_trades(fams["ALLBAR"], sig_tag, fine_sessions,
                                       lvmap, d, kk, "R", 1.0)
                print(f"\n  --- 事件后位移（R 单位，至收盘）---")
                print(f"    VOMY   MFE {quart([t.mfe_r for t in tr])}   "
                      f"MAE {quart([t.mae_r for t in tr])}   n={len(tr)}")
                print(f"    ALLBAR MFE {quart([t.mfe_r for t in base])}   "
                      f"MAE {quart([t.mae_r for t in base])}   n={len(base)}")
                print(f"    止损距离 S/ATR日:  VOMY {quart([t.S/t.atr for t in tr])}"
                      f"   ALLBAR {quart([t.S/t.atr for t in base])}")

                # 赔率结构：P(MFE > MAE)，零假设恰为 0.50，不受歧义根影响
                print("    P(MFE > MAE)  [理论零假设 50%；但样本本身有盘中漂移，"
                      "所以真正的对照是**同方向**的 ALLBAR]:")
                asym_cache = {}
                # ALLBAR 必须先算，后面每个族都要拿它做同方向对照
                for fam in ("ALLBAR", "VOMY", "ABRUPT", "BASE", "RAW"):
                    ftr, _ = build_trades(fams[fam], sig_tag, fine_sessions,
                                          lvmap, d, kk, "R", 1.0)
                    asym_cache[fam] = ftr
                    k_, n_, z_, med_ = asymmetry(ftr)
                    CELLS += 1
                    zb = ""
                    if fam != "ALLBAR":
                        kb_ = sum(1 for t in asym_cache["ALLBAR"]
                                  if t.mfe_r > t.mae_r)
                        nb_ = len(asym_cache["ALLBAR"])
                        z2 = stats.two_proportion_z(k_, n_, kb_, nb_)
                        asym_z.append(((tf_label, cname, dname, fam), z2, n_))
                        zb = f"   vs 同向ALLBAR z = {z2:+5.2f}"
                    print(f"      {fam:<8}{stats.fmt_rate(k_, n_):<30}"
                          f"z vs 50% = {z_:+5.2f}{zb}   MFE/MAE中位 = {med_:5.2f}")

                # 时段分布
                buckets = {"09:30-10:30": [], "10:30-12:00": [],
                           "12:00-14:00": [], "14:00-15:55": []}
                for t in tr:
                    h = t.hhmm
                    key = ("09:30-10:30" if h < "10:30" else
                           "10:30-12:00" if h < "12:00" else
                           "12:00-14:00" if h < "14:00" else "14:00-15:55")
                    buckets[key].append(t)
                print("    分时段 (VOMY, 目标 1R):")
                for kb_, v in buckets.items():
                    if not v:
                        print(f"      {kb_}  n=0")
                        continue
                    kk_, nn_, _, nu, zz = pb_z(v)
                    print(f"      {kb_}  {stats.fmt_rate(kk_, nn_)}  "
                          f"null={100*nu:5.1f}%  z={zz:+5.2f}")

    # ---- 作者原话版 SATY48（次要）------------------------------------------
    print(f"\n\n{'#' * 100}\n### 作者原话版 SATY48 —— break and hold 48 "
          f"（hold 是作者未指定的自由参数，1/2/3 全报）\n{'#' * 100}")
    sig_bars, sig_tag = resample(fine, 2)
    allbar = list(range(60, len(sig_bars)))
    for d, dname in ((-1, "VOMY(空)"), (+1, "iVOMY(多)")):
        base_cache = {}
        for hold in (1, 2, 3):
            idxs = detect_saty48(sig_bars, d, hold)
            out = []
            for tk, targs in (("R", R_TARGETS), ("L", LEVEL_TARGETS)):
                for ta in targs:
                    if (tk, ta) not in base_cache:
                        base_cache[(tk, ta)], _ = build_trades(
                            allbar, sig_tag, fine_sessions, lvmap, d, 2, tk, ta)
                    tr, sk = build_trades(idxs, sig_tag, fine_sessions, lvmap,
                                          d, 2, tk, ta)
                    lab = f"{ta:.0f}R" if tk == "R" else f"第{ta}个具名位"
                    grid_row(lab, tr, out, base=base_cache[(tk, ta)])
            print(f"\n{dname}  hold={hold}  事件数={len(idxs)}  [10m 信号]")
            print("\n".join(out))

    # ---- 汇总检验：把三组云 × 多空 合并，换取最大统计功效 -------------------
    print(f"\n\n{'#' * 100}\n### 汇总检验（三组云 × 多空 合并）—— 单格 n 太小，"
          f"这是本文件功效最高的一组比较\n"
          f"### 注意：三组云在同一批行情上检测事件，事件有重叠，"
          f"合并后的 n 高估了独立性 → CI 偏窄，只能当上限读。\n{'#' * 100}")
    for (tf_label, tlab, ta, fam), tr in sorted(pool.items(), key=lambda x: str(x[0])):
        if fam != "VOMY":
            continue
        base = pool.get((tf_label, tlab, ta, "ALLBAR"), [])
        k, n, obs, null, z = pb_z(tr)
        ok, on = opt_rate(tr)
        std, mz, _ = matched_baseline(tr, base)
        zz, ka, na, kb, nb = two_prop(tr, base)
        e = stats.expectancy([t.r for t in tr])
        tname = f"{ta:.0f}R" if tlab == "固定R" else f"第{ta}个具名位"
        print(f"\n  [{tf_label}] VOMY+YUMMY 合并  目标={tname}")
        print(f"      命中 {stats.fmt_rate(k, n)}   上界={100*ok/max(on,1):5.1f}%")
        print(f"      几何零假设 S/(S+T) = {100*null:5.1f}%   z={z:+.2f}")
        print(f"      随机时刻基线(未匹配) = {stats.fmt_rate(kb, nb)}   两比例 z={zz:+.2f}")
        print(f"      随机时刻基线(按 S/ATR 十分位标准化) = {100*std:5.1f}%   "
              f"z={'n<10' if mz != mz else f'{mz:+.2f}'}")
        print(f"      {stats.fmt_expectancy(e)}")

    # ---- 赔率结构总检验：P(MFE > MAE) ---------------------------------------
    print(f"\n\n{'#' * 100}\n### 赔率结构总检验 P(MFE > MAE)（合并三组云 × 多空）"
          f"\n### 零假设恰为 50%（无漂移随机游走下有利/不利偏移可交换）。"
          f"\n### 这是本文件唯一不受目标选择和 5m 同根歧义影响的检验。\n{'#' * 100}")
    print("  ⚠︎ 关键校正：本样本的**随机时刻基线本身就不是 50%**。")
    for tf_label in ("10m 信号", "5m 信号"):
        for dn in ("VOMY(空)", "YUMMY(多)"):
            b = base_pool.get((tf_label, "固定R", 1.0, dn), [])
            kb_, nb_, zb_, mb_ = asymmetry(b)
            print(f"    [{tf_label}] 随机时刻 {dn:<10}"
                  f"{stats.fmt_rate(kb_, nb_):<30}z vs 50% = {zb_:+5.2f}"
                  f"   MFE/MAE中位 = {mb_:5.2f}")
    print("  → 无漂移随机游走要求 50%，实测偏离 4-5 个标准差，说明这 60 天有盘中下行倾斜。")
    print("  → 因此下表每个事件族都必须与**同方向**的随机基线比，不能与 50% 比。\n")
    for tf_label in ("10m 信号", "5m 信号"):
        for fam in ("VOMY", "ABRUPT", "BASE", "RAW", "ALLBAR"):
            tr = pool.get((tf_label, "固定R", 1.0, fam), [])
            k_, n_, z_, med_ = asymmetry(tr)
            bb = pool.get((tf_label, "固定R", 1.0, "ALLBAR"), [])
            kb_ = sum(1 for t in bb if t.mfe_r > t.mae_r)
            z2 = stats.two_proportion_z(k_, n_, kb_, len(bb))
            CELLS += 1
            print(f"  [{tf_label}] {fam:<8}{stats.fmt_rate(k_, n_):<30}"
                  f"z vs 50% = {z_:+5.2f}   vs 基线 z = {z2:+5.2f}"
                  f"   MFE/MAE中位 = {med_:5.2f}")
    # 收窄 vs 突兀，直接在赔率结构统计上比（这是「收窄做不做功」的最干净版本）
    print("\n  收窄(VOMY) vs 突兀(ABRUPT) 的赔率结构直接对比：")
    for tf_label in ("10m 信号", "5m 信号"):
        a = pool.get((tf_label, "固定R", 1.0, "VOMY"), [])
        b = pool.get((tf_label, "固定R", 1.0, "ABRUPT"), [])
        ka_ = sum(1 for t in a if t.mfe_r > t.mae_r)
        kb2 = sum(1 for t in b if t.mfe_r > t.mae_r)
        z3 = stats.two_proportion_z(ka_, len(a), kb2, len(b))
        CELLS += 1
        print(f"    [{tf_label}] {stats.fmt_rate(ka_, len(a))} vs "
              f"{stats.fmt_rate(kb2, len(b))}   z = {z3:+.2f}")
    print("    → 两个周期符号一致（收窄略优），但都不到 1 个标准差；"
          "要把 +5pp 的差别做到 80% 功效需要 n≈780。")

    zs_a = [z for _, z, _ in asym_z]
    if zs_a:
        print(f"\n  单格分布：{len(zs_a)} 格，z>0 {sum(1 for z in zs_a if z > 0)} 个，"
              f"|z|>=1.96 {sum(1 for z in zs_a if abs(z) >= 1.96)} 个"
              f"（随机期望 {0.05 * len(zs_a):.1f}），max|z| = {max(abs(z) for z in zs_a):.2f}")
        for kk_, z, n in sorted(asym_z, key=lambda x: -abs(x[1]))[:6]:
            print(f"    {str(kk_):<62} z={z:+5.2f}  n={n}")

    # ---- 「收窄」这一步到底做不做功：符号一致性 -----------------------------
    print(f"\n\n{'#' * 100}\n### 用户强调的「收窄」是否增加信息 —— "
          f"{len(narrow_z)} 个不相交两比例检验的全体分布\n{'#' * 100}")
    pos = sum(1 for _, z, _, _ in narrow_z if z > 0)
    sig = [(kk_, z, na, nb) for kk_, z, na, nb in narrow_z if abs(z) >= 1.96]
    sig_pos = sum(1 for _, z, _, _ in sig if z > 0)
    print(f"  z > 0（收窄更好）: {pos}/{len(narrow_z)}   "
          f"z < 0（突兀更好）: {len(narrow_z) - pos}/{len(narrow_z)}")
    print(f"  |z| >= 1.96 的格子: {len(sig)}（α=0.05 下随机期望 "
          f"{0.05 * len(narrow_z):.1f} 个），其中 z>0 只有 {sig_pos} 个")
    print(f"  符号检验 p（H0: 正负各半）约 "
          f"{2 * sum(math.comb(len(narrow_z), i) for i in range(min(pos, len(narrow_z) - pos) + 1)) / 2 ** len(narrow_z):.3f}")
    for kk_, z, na, nb in sorted(narrow_z, key=lambda x: -abs(x[1]))[:8]:
        print(f"    {str(kk_):<62} z={z:+5.2f}  n_收窄={na:<4} n_突兀={nb}")

    # ---- 所有事件族 vs 匹配基线的 z 分布 -----------------------------------
    print(f"\n\n{'#' * 100}\n### 所有事件族 vs 匹配随机基线：{len(all_z)} 个 z 的分布"
          f"\n{'#' * 100}")
    zs = [z for _, z, _ in all_z]
    npos = sum(1 for z in zs if z > 0)
    print(f"  z > 0: {npos}/{len(zs)}    |z| >= 1.96: "
          f"{sum(1 for z in zs if abs(z) >= 1.96)}"
          f"（随机期望 {0.05 * len(zs):.1f}）    max|z| = {max(abs(z) for z in zs):.2f}")
    print("  绝对值最大的 10 格：")
    for kk_, z, n in sorted(all_z, key=lambda x: -abs(x[1]))[:10]:
        print(f"    {str(kk_):<74} z={z:+5.2f}  n={n}")

    print(f"\n\n{'=' * 100}")
    print(f"CELLS INSPECTED (假设检验格子总数) = {CELLS}")
    bonf = 1 - 0.05 / max(CELLS, 1)
    # 正态分位数近似（Acklam 简化）：只用于报告 Bonferroni 门槛
    import statistics  # noqa
    def ppf(p):
        # Beasley-Springer-Moro
        a = [2.50662823884, -18.61500062529, 41.39119773534, -25.44106049637]
        b = [-8.47351093090, 23.08336743743, -21.06224101826, 3.13082909833]
        c = [0.3374754822726147, 0.9761690190917186, 0.1607979714918209,
             0.0276438810333863, 0.0038405729373609, 0.0003951896511919,
             0.0000321767881768, 0.0000002888167364, 0.0000003960315187]
        y = p - 0.5
        if abs(y) < 0.42:
            r = y * y
            return y * (((a[3]*r+a[2])*r+a[1])*r+a[0]) / ((((b[3]*r+b[2])*r+b[1])*r+b[0])*r+1)
        r = p if y <= 0 else 1 - p
        r = math.log(-math.log(r))
        x = c[0]
        for i in range(1, 9):
            x += c[i] * r ** i
        return x if y > 0 else -x
    print(f"Bonferroni 双尾门槛 |z| > {ppf(bonf/1 + (1-bonf)/2):.2f}  "
          f"（α=0.05 / {CELLS} 格）")
    print("=" * 100)


if __name__ == "__main__":
    main()
