"""从基准率到可执行构造 — 5 分钟路径解析 + 诚实期望值评估.

================================================================================
预登记区（PRE-REGISTRATION）— 写于任何回测运行之前
================================================================================
纪律：本文件的三个构造在跑第一行回测代码之前就已经完整写死在这个 docstring 里。
任何后续改动都必须以 CHANGE LOG 形式追加在文末，不允许原地修改。

选择依据（只从 likely_real 的条件里挑，最多 3 个）：

  C1  <- BASERATE_TIME_STRUCTURE §S3c：「盘中触发的 Golden Gate 是轻微均值回归的，
         不是延续的：从触及 0.382 起，退回 0.146 (74.4%) 比走完 0.618 (59.8%) 更常见。
         配对 McNemar z=-4.62」。这是整个语料库里唯一一条带路径方向性的 likely_real。
  C2  <- BASERATE_OPENING_TYPE §副产品：「开盘就跳空穿透 0.382 的日子 GG 完成率
         85.9%(n=936, 20y SPY)」，并按 BASERATE_TIME_STRUCTURE 的修正剔除
         「开盘价本身已在 0.618 之外」的 40.9%（那是既成事实不是行情）。
  C3  <- GOLDEN_GATE_REPRODUCTION：「赢单最深回撤中位 0.303 ATR，而报酬只有 0.236 ATR，
         止损放 0.236 会洗掉 33% 赢单」。C3 是「把止损放宽到覆盖中位回撤之后，
         GG 延续是否变成可交易」的直接检验。C3 与 C1 是同一触发器上的相反方向 ——
         刻意成对预登记，防止「只测了看起来会赢的那一边」。

公共口径（三个构造共用，全部事前定死）：
  数据      ^GSPC 5 分钟，60 天（59 个有位图的交易日，2026-04-29 → 2026-07-23）；
            C2 主标的改用 SPY 5m（理由见下），^GSPC 作为对照。
  位图      levels.build(daily 20y)：anchor=前日收盘，ATR=前日 Wilder ATR(14)。
  时段      RTH 09:30–15:55，5m K，共 78 根/日。
  路径解析  逐 5m K；同一根 K 内同时含止损与目标 → 判止损（保守）。
            入场那根 K 也参与路径判定（同样止损优先）。
  成交假设  在具名位挂限价单，触及即以该位的价格成交（不给有利滑点，也不给不利滑点）。
  时间止损  当日 15:55 收盘价平仓（不留隔夜）。最大持仓 = 到收盘。
  R 定义    R = |入场 − 止损|，按 ATR 折算；盈亏用 R 计。0R 平局不算亏损
            （satylab.stats.expectancy 已分离）。
  多空      每个构造都做多空镜像；同一天两侧都触发时算两笔独立交易，
            但统计的独立单位是「交易日」，因此所有区间用按日区块自助法复核。

--------------------------------------------------------------------------------
C1  GG FADE（在金门入口反手）
--------------------------------------------------------------------------------
  触发   当日 5m 序列中第一次触及 +0.382 位（多头侧；空头侧镜像 −0.382），
         且该次触及**不发生在 09:30 那根 K**（09:30 K 的最高价已 ≥ 0.382 的日子整日剔除
         —— 这既排除了跳空穿透，也避开了 ^GSPC 开盘印刷失真的已知数据缺陷），
         且触发 K 的开始时间 < 14:30（BASERATE_TIME_STRUCTURE：14:30 之后
         0.236 ATR 的剩余行程即便事后选对方向也只有 49.7%）。
  方向   在 +0.382 做空（多头侧）／在 −0.382 做多（空头侧）。
  入场   0.382 位的价格。
  止损   0.618 位（GG 完成位）。风险 = 0.236 ATR。
  目标   0.236 位（trigger 位）。报酬 = 0.146 ATR = 0.619 R。
  时段   入场截止 14:25 那根 K（含）；15:55 收盘平仓。
  最大持仓 至当日收盘。
  事前预期 盈亏比 0.62:1 → 打平需 61.7% 胜率。基准率给的是「曾经退回 74.4% /
         曾经走完 59.8%」，但那不是赛跑口径，所以本测试的结果无法从基准率推出。

--------------------------------------------------------------------------------
C2  跳空穿透 GG 延续（唯一一条高胜率基准率）
--------------------------------------------------------------------------------
  触发   09:30 开盘价的 ratio ∈ [+0.382, +0.618)（空头镜像 (−0.618, −0.382]）。
         上界是硬性的：开盘已在 0.618 之外的日子不是交易机会。
  方向   开盘做多（多头侧）。
  入场   09:30 那根 5m K 的开盘价（市价单）。
  止损   +0.236 位。风险 = (开盘 ratio − 0.236) × ATR，介于 0.146–0.382 ATR。
  目标   +0.618 位。报酬 = (0.618 − 开盘 ratio) × ATR，介于 0.236–0.000 ATR。
         → 盈亏比逐笔变化，报告里必须给出 R:R 的分布，不能只给均值。
  时段   09:30 入场；15:55 收盘平仓。
  最大持仓 至当日收盘。
  主标的 SPY 5m（BASERATE_OPENING_TYPE 已证明 ^GSPC 的开盘印刷是滞后伪影、
         09:30 不可成交，SPY 才是真值）。^GSPC 同时跑一遍作为对照。
  事前预期 n 会非常小：跳空穿透 0.382 约占 15–19% 的交易日，再剔除 40.9% 已过 0.618，
         59 天窗口预计只有个位数样本 → 无论结果如何都不可能给 tradeable。

--------------------------------------------------------------------------------
C3  GG 延续 + 覆盖中位回撤的宽止损（C1 的反向对照）
--------------------------------------------------------------------------------
  触发   与 C1 完全相同（同一批触发器，逐笔一一对应）。
  方向   在 +0.382 做多（多头侧）／在 −0.382 做空（空头侧）。
  入场   0.382 位的价格。
  止损   0.000 位（PDC 锚）。风险 = 0.382 ATR。
         选锚而不选「0.303 ATR」这个数字，是为了避免引入一个从统计量里抠出来的
         自由参数；锚是具名位，且 0.382 > 0.303 满足「覆盖赢单中位最深回撤」的要求。
  目标   0.618 位（GG 完成）。报酬 = 0.236 ATR = 0.618 R。
  时段   与 C1 相同（截止 14:25，15:55 平仓）。
  事前预期 打平需 61.7%。SPY 20y 的「盘中才触发」完成率是 51.5%（不是赛跑口径），
         所以事前预期是 reject；测它是为了把「入场层能否靠放宽止损救回来」这个
         公开问题关掉，以及作为 C1 的对照防止单边择优。

================================================================================
成本口径：SPX CFD 点差 0.4 / 0.5 / 0.8 点三档。
  基准折算：一次往返 = 1 × 点差（买在 ask、卖在 bid）。
  R 扣减 = 点差点数 / 风险点数，逐笔计算（因为 C2 的风险逐笔不同）。
  另报悲观口径 2 × 点差（含滑点）。
================================================================================
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import date, time

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats  # noqa: E402

# ---------------------------------------------------------------------------
# 配置计数器：本研究一共动过多少个格子，必须原样印出来
# ---------------------------------------------------------------------------
CONFIG_LOG: list[str] = []


def log_config(tag: str) -> None:
    CONFIG_LOG.append(tag)


# ---------------------------------------------------------------------------
# 交易对象
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    day: date
    side: int            # +1 多  -1 空
    entry_hhmm: str
    entry: float
    stop: float
    target: float
    exit_hhmm: str
    exit: float
    reason: str          # target / stop / close
    risk_pts: float
    r: float
    rr: float            # 目标 R 倍数
    mae_r: float
    mfe_r: float
    bars_held: int
    risk_atr: float = 0.0   # 风险的 ATR 归一化值（成本折算必须用它，见 CHANGE LOG #1）


def _binom_z(k: int, n: int, p0: float) -> float:
    if n == 0 or p0 <= 0 or p0 >= 1:
        return 0.0
    return (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def simulate(session: list, entry_idx: int, entry_px: float, stop_px: float,
             target_px: float, side: int, day: date, atr: float = 1.0,
             skip_entry_bar_target: bool = False) -> Trade:
    """从 entry_idx 那根 K 开始逐根解析；同根同时含止损与目标 → 止损优先。

    skip_entry_bar_target=True 时启用最保守读法：入场那根 K 只允许判止损、
    不允许判目标（因为入场触发与目标触及在同一根 K 内的先后顺序不可知）。
    """
    risk = abs(entry_px - stop_px)
    reward = abs(target_px - entry_px)
    mae = mfe = 0.0
    for j in range(entry_idx, len(session)):
        b = session[j]
        adverse = (entry_px - b.low) if side > 0 else (b.high - entry_px)
        favorable = (b.high - entry_px) if side > 0 else (entry_px - b.low)
        mae = max(mae, adverse)
        mfe = max(mfe, favorable)
        hit_stop = (b.low <= stop_px) if side > 0 else (b.high >= stop_px)
        hit_tgt = (b.high >= target_px) if side > 0 else (b.low <= target_px)
        if skip_entry_bar_target and j == entry_idx:
            hit_tgt = False
        if hit_stop:                       # 止损优先（保守）
            return Trade(day, side, session[entry_idx].hhmm, entry_px, stop_px,
                         target_px, b.hhmm, stop_px, "stop", risk, -1.0,
                         reward / risk, mae / risk, mfe / risk,
                         j - entry_idx + 1, risk / atr)
        if hit_tgt:
            return Trade(day, side, session[entry_idx].hhmm, entry_px, stop_px,
                         target_px, b.hhmm, target_px, "target", risk,
                         reward / risk, reward / risk, mae / risk, mfe / risk,
                         j - entry_idx + 1, risk / atr)
    last = session[-1]
    r = side * (last.close - entry_px) / risk
    return Trade(day, side, session[entry_idx].hhmm, entry_px, stop_px,
                 target_px, last.hhmm, last.close, "close", risk, r,
                 reward / risk, mae / risk, mfe / risk,
                 len(session) - entry_idx, risk / atr)


def simulate_bounds(session: list, entry_idx: int, entry_px: float,
                    stop_px: float, target_px: float, side: int,
                    optimistic: bool) -> tuple[str, float]:
    """低分辨率（小时线）专用：同根 K 同时含止损与目标时给上下界两种读法。

    返回 (reason, R)。optimistic=True 时歧义根判目标，False 时判止损。

    悲观读法额外禁止「入场那根 K 达成目标」：入场是在该 K 内触及 0.382 的瞬间，
    而该 K 的最低价完全可能出现在触及之前（1h K 的振幅中位 0.27 ATR，
    大于 0.146 ATR 的目标距离，所以这不是理论顾虑）。不禁止就是前视偏差。
    """
    risk = abs(entry_px - stop_px)
    reward = abs(target_px - entry_px)
    for j in range(entry_idx, len(session)):
        b = session[j]
        hit_stop = (b.low <= stop_px) if side > 0 else (b.high >= stop_px)
        hit_tgt = (b.high >= target_px) if side > 0 else (b.low <= target_px)
        if not optimistic and j == entry_idx:
            hit_tgt = False
        if hit_stop and hit_tgt:
            return ("target", reward / risk) if optimistic else ("stop", -1.0)
        if hit_stop:
            return ("stop", -1.0)
        if hit_tgt:
            return ("target", reward / risk)
    last = session[-1]
    return ("close", side * (last.close - entry_px) / risk)


def _hhmm_lt(bar, cutoff: time) -> bool:
    return bar.dt.time() < cutoff


def hourly_bounds(days, sessions, lvmap, kind: str):
    """在低分辨率数据上给一个构造的上下界。kind ∈ {c1, c3, c2}。

    C1/C3 是盘中触发 → 悲观读法禁止入场根判目标（前视）。
    C2 是开盘入场 → 入场根之后的目标是真的，只有同根双触才是歧义。
    """
    rs_lo, rs_hi, amb, n = [], [], 0, 0
    for day in days:
        lv, s = lvmap.get(day), sessions.get(day)
        if lv is None or not s:
            continue
        if kind == "c2":
            r0 = lv.ratio_of(s[0].open)
            for side in (+1, -1):
                lo_b, hi_b = side * levels.GG_ENTRY, side * levels.GG_COMPLETE
                inside = (lo_b <= r0 < hi_b) if side > 0 else (hi_b < r0 <= lo_b)
                if not inside:
                    continue
                stop, tgt = lv.at(side * levels.TRIGGER), lv.at(side * levels.GG_COMPLETE)
                a = simulate_bounds(s, 0, s[0].open, stop, tgt, side, False)
                b = simulate_bounds(s, 0, s[0].open, stop, tgt, side, True)
                rs_lo.append((day, a[1]))
                rs_hi.append(b[1])
                amb += int(a[0] != b[0])
                n += 1
            continue
        is_fade = kind == "c1"
        stop_r = levels.GG_COMPLETE if is_fade else 0.0
        tgt_r = levels.TRIGGER if is_fade else levels.GG_COMPLETE
        for side in (+1, -1):
            lvl = lv.at(side * levels.GG_ENTRY)
            if (s[0].high >= lvl) if side > 0 else (s[0].low <= lvl):
                continue
            idx = levels.first_touch(s, lvl, side, start=1)
            if idx is None or not _hhmm_lt(s[idx], time(14, 30)):
                continue
            stop, tgt = lv.at(side * stop_r), lv.at(side * tgt_r)
            tside = -side if is_fade else side
            a = simulate_bounds(s, idx, lvl, stop, tgt, tside, False)
            b = simulate_bounds(s, idx, lvl, stop, tgt, tside, True)
            rs_lo.append((day, a[1]))
            rs_hi.append(b[1])
            amb += int(a[0] != b[0])
            n += 1
    return n, amb, rs_lo, rs_hi


# ---------------------------------------------------------------------------
# C1 / C3 触发器：盘中首次触及 ±0.382，09:30 那根 K 未触及，截止 14:30
# ---------------------------------------------------------------------------
def gg_intraday_triggers(sessions, lvmap, cutoff=time(14, 30)):
    """returns list of (day, side, idx, entry_px, DayLevels)."""
    out = []
    for day in sorted(sessions):
        lv = lvmap.get(day)
        if lv is None:
            continue
        s = sessions[day]
        if len(s) < 20:
            continue
        for side in (+1, -1):
            lvl = lv.at(side * levels.GG_ENTRY)
            # 09:30 那根 K 已经触及 → 整日该侧剔除（跳空穿透 / 开盘印刷污染）
            first_bar = s[0]
            if (first_bar.high >= lvl) if side > 0 else (first_bar.low <= lvl):
                continue
            idx = levels.first_touch(s, lvl, side, start=1)
            if idx is None:
                continue
            if not _hhmm_lt(s[idx], cutoff):
                continue
            out.append((day, side, idx, lvl, lv))
    return out


def run_c1(sessions, lvmap, stop_ratio=levels.GG_COMPLETE,
           target_ratio=levels.TRIGGER, cutoff=time(14, 30),
           strict=False) -> list[Trade]:
    trades = []
    for day, side, idx, entry_px, lv in gg_intraday_triggers(sessions, lvmap,
                                                             cutoff):
        stop = lv.at(side * stop_ratio)
        tgt = lv.at(side * target_ratio)
        # C1 是反手：在 +0.382 做空 → 交易方向 = -side
        trades.append(simulate(sessions[day], idx, entry_px, stop, tgt,
                               -side, day, lv.atr, strict))
    return trades


def run_c3(sessions, lvmap, stop_ratio=0.0, target_ratio=levels.GG_COMPLETE,
           cutoff=time(14, 30), strict=False) -> list[Trade]:
    trades = []
    for day, side, idx, entry_px, lv in gg_intraday_triggers(sessions, lvmap,
                                                             cutoff):
        stop = lv.at(side * stop_ratio)
        tgt = lv.at(side * target_ratio)
        trades.append(simulate(sessions[day], idx, entry_px, stop, tgt,
                               side, day, lv.atr, strict))
    return trades


def run_c2(sessions, lvmap, stop_ratio=levels.TRIGGER,
           target_ratio=levels.GG_COMPLETE, strict=False) -> list[Trade]:
    trades = []
    for day in sorted(sessions):
        lv = lvmap.get(day)
        if lv is None:
            continue
        s = sessions[day]
        if len(s) < 20:
            continue
        r0 = lv.ratio_of(s[0].open)
        for side in (+1, -1):
            lo, hi = side * levels.GG_ENTRY, side * levels.GG_COMPLETE
            inside = (lo <= r0 < hi) if side > 0 else (hi < r0 <= lo)
            if not inside:
                continue
            entry = s[0].open
            stop = lv.at(side * stop_ratio)
            tgt = lv.at(side * target_ratio)
            trades.append(simulate(s, 0, entry, stop, tgt, side, day,
                                   lv.atr, strict))
    return trades


# ---------------------------------------------------------------------------
# 报告工具
# ---------------------------------------------------------------------------
SPREADS = (0.4, 0.5, 0.8)

# 成本折算必须在 ATR 归一空间里做（CHANGE LOG #1）：点差是以 SPX 指数点报的，
# 而 SPY 计价的构造其风险以美元计。把点差先换成「当日 SPX ATR 的百分之几」，
# 再除以该笔交易的 risk_atr，两个标的才是同一把尺子。
SPX_ATR_BY_DAY: dict[date, float] = {}


def cost_adjusted(trades: list[Trade], spread_pts: float,
                  multiple: float = 1.0) -> list[float]:
    out = []
    for t in trades:
        atr_pts = SPX_ATR_BY_DAY.get(t.day)
        if atr_pts is None or t.risk_atr <= 0:
            out.append(t.r)
            continue
        out.append(t.r - multiple * (spread_pts / atr_pts) / t.risk_atr)
    return out


def day_block_bootstrap(trades: list[Trade], iters: int = 5000,
                        seed: int = 20260725) -> tuple[float, float]:
    """按交易日重抽（同一天的多笔一起走），返回均 R 的 95% 区间。"""
    if not trades:
        return (0.0, 0.0)
    by_day: dict[date, list[float]] = {}
    for t in trades:
        by_day.setdefault(t.day, []).append(t.r)
    days = list(by_day)
    rng = random.Random(seed)
    means = []
    for _ in range(iters):
        pool: list[float] = []
        for _ in range(len(days)):
            pool.extend(by_day[days[rng.randrange(len(days))]])
        if pool:
            means.append(sum(pool) / len(pool))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def report(name: str, trades: list[Trade], out) -> dict:
    e = stats.expectancy([t.r for t in trades])
    p = out.append
    p(f"### {name}")
    p("")
    if not trades:
        p("  无样本（n=0）")
        p("")
        return {"n": 0}
    p(f"  毛（零成本）: {stats.fmt_expectancy(e)}")
    n_days = len({t.day for t in trades})
    p(f"  独立交易日 = {n_days}，交易笔数 = {len(trades)}")
    reasons = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    p(f"  出场归因: " + "  ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    k_t = reasons.get("target", 0)
    resolved = k_t + reasons.get("stop", 0)
    if resolved:
        p(f"  赛跑口径 P(目标先到 | 已分胜负) = {stats.fmt_rate(k_t, resolved)}")
    be = e["breakeven_wr"]
    kw = sum(1 for t in trades if t.r > 1e-12)
    p(f"  打平所需胜率 = {100*be:.1f}%，实测胜率 = {stats.fmt_rate(kw, len(trades))}")
    p(f"  胜率 vs 打平线 z = {_binom_z(kw, len(trades), be):+.2f}"
      f"（正态近似，n 小时只作参考）")
    lo, hi = day_block_bootstrap(trades)
    p(f"  均 R 的按日区块自助 95% CI = [{lo:+.3f}, {hi:+.3f}]"
      f"（{n_days} 个交易日重抽 5000 次，seed=20260725）")
    # 留一日刀切：上一次失败的研究里 100% 的净值来自单笔 +2.90R，必须查这个
    days_ = sorted({t.day for t in trades})
    if len(days_) > 2:
        jk = []
        for dd in days_:
            rest = [t.r for t in trades if t.day != dd]
            jk.append(sum(rest) / len(rest))
        p(f"  留一日刀切：去掉任意单个交易日后的均R 落在 "
          f"[{min(jk):+.3f}, {max(jk):+.3f}]（原值 {e['avg_r']:+.3f}）")
        best = max(trades, key=lambda t: t.r)
        share = (f"，占总R的 {100*best.r/e['total_r']:.1f}%"
                 if e["total_r"] > 0 else "（总R为负，占比无意义）")
        p(f"  单笔最大贡献 = {best.r:+.2f}R{share}")
    p(f"  中位 MAE = {statistics.median(t.mae_r for t in trades):.2f} R，"
      f"中位 MFE = {statistics.median(t.mfe_r for t in trades):.2f} R，"
      f"中位持仓 = {statistics.median(t.bars_held for t in trades):.0f} 根 5m K")
    rrs = sorted(t.rr for t in trades)
    p(f"  目标 R 倍数: 中位 {statistics.median(rrs):.2f}，"
      f"范围 [{rrs[0]:.2f}, {rrs[-1]:.2f}]")
    p(f"  中位风险 = {statistics.median(t.risk_pts for t in trades):.1f} 点")
    p("")
    p("  成本敏感性（逐笔扣 点差/风险点数）:")
    p("")
    p("  | 点差 | 往返×1 均R | 往返×1 总R | 往返×2 均R | 往返×2 总R |")
    p("  |---|---|---|---|---|")
    for sp in SPREADS:
        e1 = stats.expectancy(cost_adjusted(trades, sp, 1.0))
        e2 = stats.expectancy(cost_adjusted(trades, sp, 2.0))
        p(f"  | {sp} 点 | {e1['avg_r']:+.3f} | {e1['total_r']:+.1f} | "
          f"{e2['avg_r']:+.3f} | {e2['total_r']:+.1f} |")
    p("")
    return e


def grid_line(tag: str, trades: list[Trade]) -> str:
    log_config(tag)
    if not trades:
        return f"  | {tag} | 0 | – | – | – | – |"
    e = stats.expectancy([t.r for t in trades])
    e5 = stats.expectancy(cost_adjusted(trades, 0.5, 1.0))
    kw = sum(1 for t in trades if t.r > 1e-12)
    lo, hi = wilson_pct(kw, len(trades))
    return (f"  | {tag} | {e['n']} | {100*e['win_rate']:.1f}% [{lo:.0f},{hi:.0f}] "
            f"| {100*e['breakeven_wr']:.1f}% | {e['avg_r']:+.3f} | "
            f"{e5['avg_r']:+.3f} |")


def wilson_pct(k, n):
    lo, hi = stats.wilson(k, n)
    return 100 * lo, 100 * hi


# ---------------------------------------------------------------------------
def main() -> None:
    out: list[str] = []
    p = out.append

    d_gspc = data.daily()
    lv_gspc = levels.build(d_gspc)
    s_gspc = data.group_by_day(data.fine())
    d_spy = data.daily("SPY")
    lv_spy = levels.build(d_spy)
    s_spy = data.group_by_day(data.fine("SPY"))

    usable_gspc = [k for k in s_gspc if k in lv_gspc]
    usable_spy = [k for k in s_spy if k in lv_spy]
    SPX_ATR_BY_DAY.update({k: lv_gspc[k].atr for k in usable_gspc})

    p("# 交易构造与诚实期望值评估 — TRADE_CONSTRUCTIONS")
    p("")
    p(f"生成脚本 `research/satylab/study_trades.py`（预登记见文件头 docstring）。")
    p("")
    p("## §0 数据与口径")
    p("")
    p(f"- ^GSPC 5m: {len(s_gspc)} 个交易日，其中有位图的 {len(usable_gspc)} 个，"
      f"{min(usable_gspc)} → {max(usable_gspc)}")
    p(f"- SPY  5m: {len(s_spy)} 个交易日，其中有位图的 {len(usable_spy)} 个")
    p(f"- ^GSPC 前日 ATR(14) 中位 = "
      f"{statistics.median(lv_gspc[k].atr for k in usable_gspc):.1f} 点；"
      f"锚（前收）中位 = "
      f"{statistics.median(lv_gspc[k].anchor for k in usable_gspc):.0f}")
    p(f"- SPY 前日 ATR(14) 中位 = "
      f"{statistics.median(lv_spy[k].atr for k in usable_spy):.2f} 美元")
    p("- 最后一个 5m 交易日没有位图（日线缓存少一天），已剔除。")
    p("")
    p("**成本换算的量级感**：0.236 ATR 的止损 = "
      f"{0.236*statistics.median(lv_gspc[k].atr for k in usable_gspc):.1f} 点，"
      "所以 0.5 点的点差 ≈ "
      f"{0.5/(0.236*statistics.median(lv_gspc[k].atr for k in usable_gspc)):.3f} R；"
      "0.382 ATR 的止损上，同样点差 ≈ "
      f"{0.5/(0.382*statistics.median(lv_gspc[k].atr for k in usable_gspc)):.3f} R。")
    p("")

    # ---- 预登记三构造 ----
    p("## §1 三个预登记构造的结果（先写死再测，见文件头）")
    p("")

    c1 = run_c1(s_gspc, lv_gspc)
    log_config("C1 预登记：入 0.382 / 止 0.618 / 目标 0.236 / 截止 14:30 / GSPC")
    e1 = report("C1  GG FADE（在 +0.382 反手，止 0.618，目标 0.236）", c1, out)

    c3 = run_c3(s_gspc, lv_gspc)
    log_config("C3 预登记：入 0.382 / 止 0.000 / 目标 0.618 / 截止 14:30 / GSPC")
    e3 = report("C3  GG 延续（在 +0.382 顺势，止 PDC 锚，目标 0.618）", c3, out)

    c2_spy = run_c2(s_spy, lv_spy)
    log_config("C2 预登记：开盘入 / 止 0.236 / 目标 0.618 / SPY（主）")
    e2 = report("C2  跳空穿透 GG 延续（SPY 主标的）", c2_spy, out)

    c2_gspc = run_c2(s_gspc, lv_gspc)
    log_config("C2 对照：同上但用 ^GSPC（开盘价已知失真）")
    e2g = report("C2b 同一构造用 ^GSPC 开盘价（已知失真，仅作对照）", c2_gspc, out)

    # ---- C1/C3 配对 ----
    p("## §2 C1 与 C3 的配对关系（同一批触发器）")
    p("")
    trig = gg_intraday_triggers(s_gspc, lv_gspc)
    p(f"- 触发器总数 = {len(trig)}（多头侧 "
      f"{sum(1 for t in trig if t[1] > 0)}，空头侧 "
      f"{sum(1 for t in trig if t[1] < 0)}），覆盖 "
      f"{len({t[0] for t in trig})} 个交易日 / {len(usable_gspc)} 个可用日")
    both = {(t.day, t.side) for t in c1} & {(t.day, -t.side) for t in c3}
    p(f"- C1 与 C3 逐笔一一对应（{len(c1)} vs {len(c3)}），方向相反。"
      "两者不是互补事件（止损与目标位不同），但一方看起来好通常意味着另一方看起来差 —— "
      "这正是成对预登记要暴露的东西。")
    p("")
    # 触发器账目
    n_gap = n_none = 0
    for day in usable_gspc:
        lv, s = lv_gspc[day], s_gspc[day]
        for side in (+1, -1):
            lvl = lv.at(side * levels.GG_ENTRY)
            if (s[0].high >= lvl) if side > 0 else (s[0].low <= lvl):
                n_gap += 1
            elif levels.first_touch(s, lvl, side, start=1) is None:
                n_none += 1
    total_sides = 2 * len(usable_gspc)
    p(f"- 触发器账目（{total_sides} 个「日 × 侧」）：09:30 那根 K 已触及 0.382 而被整侧剔除 "
      f"= {n_gap}（{100*n_gap/total_sides:.1f}%）；全天从未触及 = {n_none}；"
      f"盘中触及但已过 14:30 = {total_sides - n_gap - n_none - len(trig)}；"
      f"进入构造 = {len(trig)}")
    p("")
    # 赛跑：0.618 与 0.236 谁先到（不带止损口径，纯路径统计）
    first_up = first_dn = neither = 0
    for day, side, idx, entry_px, lv in trig:
        s = s_gspc[day]
        up = levels.first_touch(s, lv.at(side * levels.GG_COMPLETE), side, idx)
        dn = levels.first_touch(s, lv.at(side * levels.TRIGGER), -side, idx)
        if up is None and dn is None:
            neither += 1
        elif dn is None or (up is not None and up < dn):
            first_up += 1
        elif up is None or dn < up:
            first_dn += 1
        else:
            neither += 1
    tot = first_up + first_dn + neither
    p(f"- 纯路径赛跑（从触及 0.382 起，0.618 与 0.236 谁先到，5m 分辨率）："
      f"先到 0.618 = {first_up}，先退回 0.236 = {first_dn}，"
      f"到收盘都没到 = {neither}，合计 {tot}")
    if first_up + first_dn:
        p(f"  P(先退回 0.236 | 已分胜负) = "
          f"{stats.fmt_rate(first_dn, first_up + first_dn)}；"
          f"vs 50% 的 z = {_binom_z(first_dn, first_up + first_dn, 0.5):+.2f}")
    p("")

    # ---- 敏感性网格：全部印出 ----
    p("## §3 敏感性网格（全部格子照登，没有任何一格被提升为发现）")
    p("")
    p("列：n / 胜率[Wilson 95%] / 打平所需胜率 / 毛均R / 扣 0.5 点往返后的均R")
    p("")
    p("### C1 族（反手方向）")
    p("")
    p("  | 配置 | n | 胜率 | 打平需 | 毛均R | 净均R(0.5) |")
    p("  |---|---|---|---|---|---|")
    for stop_r in (0.5, 0.618, 0.786):
        for tgt_r in (0.236, 0.0):
            for cut, cname in ((time(12, 0), "12:00"), (time(14, 30), "14:30"),
                               (time(16, 0), "无截止")):
                t = run_c1(s_gspc, lv_gspc, stop_r, tgt_r, cut)
                p(grid_line(f"C1 止{stop_r} 目标{tgt_r} 截止{cname}", t))
    p("")
    p("### C3 族（顺势方向）")
    p("")
    p("  | 配置 | n | 胜率 | 打平需 | 毛均R | 净均R(0.5) |")
    p("  |---|---|---|---|---|---|")
    for stop_r in (0.236, 0.0, -0.236):
        for tgt_r in (0.618, 0.786, 1.0):
            for cut, cname in ((time(12, 0), "12:00"), (time(14, 30), "14:30"),
                               (time(16, 0), "无截止")):
                t = run_c3(s_gspc, lv_gspc, stop_r, tgt_r, cut)
                p(grid_line(f"C3 止{stop_r} 目标{tgt_r} 截止{cname}", t))
    p("")
    p("### C2 族")
    p("")
    p("  | 配置 | n | 胜率 | 打平需 | 毛均R | 净均R(0.5) |")
    p("  |---|---|---|---|---|---|")
    for sym, ss, ll in (("SPY", s_spy, lv_spy), ("GSPC", s_gspc, lv_gspc)):
        for stop_r in (0.236, 0.0):
            for tgt_r in (0.618, 1.0):
                t = run_c2(ss, ll, stop_r, tgt_r)
                p(grid_line(f"C2 {sym} 止{stop_r} 目标{tgt_r}", t))
    p("")

    # ---- 稳健性 1：入场根的盘内先后顺序 ----
    p("## §3.5 稳健性 A：入场那根 K 的盘内先后顺序")
    p("")
    p("C1 的目标只有 0.146 ATR 远（中位 11.7 点），一根 5m K 常常能同时装下"
      "「触及 0.382」和「回到 0.236」。这两件事在同一根 K 内谁先发生，5m 分辨率无法回答。"
      "最保守读法：入场那根 K 只允许判止损、不允许判目标。")
    p("")
    same_bar = sum(1 for t in c1 if t.bars_held == 1 and t.reason == "target")
    p(f"- C1 有 {same_bar}/{len(c1)} 笔的目标是在入场那根 K 内达成的"
      f"（{stats.fmt_rate(same_bar, len(c1))}）")
    p("")
    p("  | 读法 | n | 胜率 | 毛均R | 净均R(0.5点往返) | 按日区块 95% CI |")
    p("  |---|---|---|---|---|---|")
    for tag, strict in (("宽松（入场根可判目标，§1 用的就是这个）", False),
                        ("最保守（入场根只判止损）", True)):
        for cname, runner in (("C1", run_c1), ("C3", run_c3)):
            t = runner(s_gspc, lv_gspc, strict=strict)
            log_config(f"{cname} 入场根读法={'保守' if strict else '宽松'}")
            e = stats.expectancy([x.r for x in t])
            e5 = stats.expectancy(cost_adjusted(t, 0.5, 1.0))
            blo, bhi = day_block_bootstrap(t)
            kw = sum(1 for x in t if x.r > 1e-12)
            p(f"  | {cname} {tag} | {e['n']} | "
              f"{100*e['win_rate']:.1f}% | {e['avg_r']:+.3f} | {e5['avg_r']:+.3f} "
              f"| [{blo:+.3f}, {bhi:+.3f}] |")
    p("")

    # ---- 稳健性 2：730 天小时线上下界复核 ----
    p("## §3.6 稳健性 B：730 天小时线的上下界复核（样本 10 倍，但分辨率不足）")
    p("")
    p("纪律第 5 条禁止用小时线做路径判定的**点估计**。这里只做**上下界**："
      "同一根 1h K 内同时含止损与目标时，乐观读法判目标、悲观读法判止损。"
      "如果连乐观上界都低于打平线，那是一个决定性的否定结论；"
      "如果连悲观下界都高于打平线，那是决定性的肯定结论；两者之间则不可判。")
    p("")
    h_sess = data.group_by_day(data.hourly())
    h_days = [k for k in sorted(h_sess) if k in lv_gspc and len(h_sess[k]) == 7]
    p(f"- 小时线可用交易日 = {len(h_days)}（{min(h_days)} → {max(h_days)}，"
      "只保留 7 根的完整 RTH 日，剔除半日市）")
    p("")
    p("  | 构造 | n | 歧义根占比 | 悲观胜率 | 乐观胜率 | 打平需 | 悲观均R | 乐观均R |")
    p("  |---|---|---|---|---|---|---|---|")
    hourly_rs: dict[str, list[tuple[date, float]]] = {}
    for cname, is_fade, stop_r, tgt_r in (
            ("C1 (fade 止0.618 目标0.236)", True, levels.GG_COMPLETE,
             levels.TRIGGER),
            ("C3 (顺势 止0.000 目标0.618)", False, 0.0, levels.GG_COMPLETE)):
        rs_lo, rs_hi, amb, n = [], [], 0, 0
        for day in h_days:
            lv, s = lv_gspc[day], h_sess[day]
            for side in (+1, -1):
                lvl = lv.at(side * levels.GG_ENTRY)
                if (s[0].high >= lvl) if side > 0 else (s[0].low <= lvl):
                    continue
                idx = levels.first_touch(s, lvl, side, start=1)
                if idx is None or not _hhmm_lt(s[idx], time(14, 30)):
                    continue
                stop = lv.at(side * stop_r)
                tgt = lv.at(side * tgt_r)
                tside = -side if is_fade else side
                r_lo = simulate_bounds(s, idx, lvl, stop, tgt, tside, False)
                r_hi = simulate_bounds(s, idx, lvl, stop, tgt, tside, True)
                rs_lo.append((day, r_lo[1]))
                rs_hi.append((day, r_hi[1]))
                amb += int(r_lo[0] != r_hi[0])
                n += 1
        log_config(f"小时线上下界复核 {cname}")
        hourly_rs[cname] = rs_lo
        e_lo = stats.expectancy([r for _, r in rs_lo])
        e_hi = stats.expectancy([r for _, r in rs_hi])
        k_lo = sum(1 for _, r in rs_lo if r > 1e-12)
        k_hi = sum(1 for _, r in rs_hi if r > 1e-12)
        p(f"  | {cname} | {n} | {100*amb/n:.1f}% | "
          f"{stats.fmt_rate(k_lo, n).strip()} | {stats.fmt_rate(k_hi, n).strip()} | "
          f"{100*e_lo['breakeven_wr']:.1f}% | {e_lo['avg_r']:+.3f} | "
          f"{e_hi['avg_r']:+.3f} |")
    p("")
    p("**口径警告（重要）**：小时线的触发器与 5m 的不是同一批。小时线上「09:30 那根 K "
      "未触及」意味着 0.382 是在 **10:30 之后**才第一次被触及；5m 上只要求 **09:35 之后**。"
      "所以小时线样本是 5m 样本的一个更晚、更慢的子集，两者不能直接比数字。"
      "下面给出把 5m 也限制到 10:30 之后的对照行。")
    p("")
    c1_late = run_c1(s_gspc, lv_gspc, cutoff=time(14, 30))
    c1_late = [t for t in c1_late if t.entry_hhmm >= "10:30"]
    log_config("C1 口径对照：5m 但入场时刻限制到 10:30 之后（为与小时线可比）")
    e_late = stats.expectancy([t.r for t in c1_late])
    p(f"- 5m / 入场 ≥10:30 / C1 预登记参数：{stats.fmt_expectancy(e_late)}")
    p("")
    p("**分期稳定性（悲观读法，三段不重叠年块）**：")
    p("")
    p("  | 构造 | 2023-08→2024-07 | 2024-08→2025-07 | 2025-08→2026-07 |")
    p("  |---|---|---|---|")
    for cname, rows in hourly_rs.items():
        cuts = []
        for y0, y1 in ((2023, 2024), (2024, 2025), (2025, 2026)):
            sel = [r for d, r in rows
                   if (d.year, d.month) >= (y0, 8) and (d.year, d.month) < (y1, 8)]
            e = stats.expectancy(sel)
            cuts.append(f"{e['avg_r']:+.3f} (n={e['n']})" if sel else "–")
        log_config(f"小时线分期稳定性 {cname}（3 个年块）")
        p(f"  | {cname} | " + " | ".join(cuts) + " |")
    p("")

    # ---- 稳健性 3：C2 的小时线上下界（这一个的入场没有盘内顺序歧义）----
    p("## §3.7 稳健性 C：C2 在 730 天 SPY 小时线上的上下界")
    p("")
    p("C2 与 C1/C3 有一个关键差别：它的入场是 **09:30 那根 K 的开盘价**，"
      "不是盘中触发。所以「入场时刻」在该 K 内是确定的（就是第一秒），"
      "该 K 之后出现的目标是真的目标，不存在 §3.6 里那种前视问题。"
      "只有「同一根 K 内止损与目标都被触及」才是歧义。因此 C2 的小时线上下界"
      "比 C1/C3 的信息量大得多。")
    p("")
    h_spy = data.group_by_day(data.hourly("SPY"))
    h_spy_days = [k for k in sorted(h_spy) if k in lv_spy and len(h_spy[k]) == 7]
    p(f"- SPY 小时线可用交易日 = {len(h_spy_days)}"
      f"（{min(h_spy_days)} → {max(h_spy_days)}）")
    p("")
    p("  | 构造 | n | 歧义根占比 | 悲观胜率 | 乐观胜率 | 打平需 | 悲观均R | 乐观均R |")
    p("  |---|---|---|---|---|---|---|---|")
    c2_rows_lo: list[tuple[date, float]] = []
    for label, stop_r, tgt_r in (("C2 预登记 (止0.236 目标0.618)",
                                  levels.TRIGGER, levels.GG_COMPLETE),):
        rs_lo, rs_hi, amb, n = [], [], 0, 0
        for day in h_spy_days:
            lv, s = lv_spy[day], h_spy[day]
            r0 = lv.ratio_of(s[0].open)
            for side in (+1, -1):
                lo_b, hi_b = side * levels.GG_ENTRY, side * levels.GG_COMPLETE
                inside = (lo_b <= r0 < hi_b) if side > 0 else (hi_b < r0 <= lo_b)
                if not inside:
                    continue
                stop = lv.at(side * stop_r)
                tgt = lv.at(side * tgt_r)
                a = simulate_bounds(s, 0, s[0].open, stop, tgt, side, False)
                b = simulate_bounds(s, 0, s[0].open, stop, tgt, side, True)
                rs_lo.append((day, a[1]))
                rs_hi.append(b[1])
                amb += int(a[0] != b[0])
                n += 1
        log_config(f"SPY 小时线上下界 {label}")
        c2_rows_lo = rs_lo
        e_lo = stats.expectancy([r for _, r in rs_lo])
        e_hi = stats.expectancy(rs_hi)
        k_lo = sum(1 for _, r in rs_lo if r > 1e-12)
        k_hi = sum(1 for r in rs_hi if r > 1e-12)
        p(f"  | {label} | {n} | {100*amb/n:.1f}% | "
          f"{stats.fmt_rate(k_lo, n).strip()} | {stats.fmt_rate(k_hi, n).strip()} | "
          f"{100*e_lo['breakeven_wr']:.1f}% | {e_lo['avg_r']:+.3f} | "
          f"{e_hi['avg_r']:+.3f} |")
    p("")
    if c2_rows_lo:
        p("**分期稳定性（悲观读法）**：")
        cuts = []
        for y0, y1 in ((2023, 2024), (2024, 2025), (2025, 2026)):
            sel = [r for d, r in c2_rows_lo
                   if (d.year, d.month) >= (y0, 8) and (d.year, d.month) < (y1, 8)]
            e = stats.expectancy(sel)
            cuts.append(f"{y0}-08→{y1}-07: {e['avg_r']:+.3f} (n={e['n']})"
                        if sel else "–")
        log_config("SPY 小时线 C2 分期稳定性（3 个年块）")
        p("  " + "；".join(cuts))
        p("")
        by_d: dict[date, list[float]] = {}
        for d_, r in c2_rows_lo:
            by_d.setdefault(d_, []).append(r)
        dr = [sum(v) / len(v) for v in by_d.values()]
        if len(dr) > 2:
            sd = statistics.stdev(dr)
            mu = statistics.mean(dr)
            half = 1.96 * sd / math.sqrt(len(dr))
            p(f"  悲观读法的均 R = {mu:+.3f}，正态 95% ≈ "
              f"[{mu-half:+.3f}, {mu+half:+.3f}]（{len(dr)} 个交易日）")
        p("")

    # ---- 稳健性 4：60 天窗口有没有代表性 ----
    p("## §3.8 稳健性 D：这 60 天窗口本身有没有代表性")
    p("")
    p("§1 的所有数字都来自 2026-04-29 → 2026-07-23 这 59 个交易日。"
      "在同一把（分辨率不足但口径一致的）小时线尺子下，把这 59 天与整个 2 年窗口"
      "并排放，可以看出这段窗口是不是特别友好。上下界读法与 §3.6/§3.7 相同。")
    p("")
    p("  | 构造 | 窗口 | n | 歧义% | 悲观均R | 乐观均R |")
    p("  |---|---|---|---|---|---|")
    win5m = set(usable_gspc)
    for kind, label, sess_h, lvm, days_all in (
            ("c1", "C1", h_sess, lv_gspc, h_days),
            ("c3", "C3", h_sess, lv_gspc, h_days),
            ("c2", "C2", h_spy, lv_spy, h_spy_days)):
        for wlabel, dsel in (("全部 2 年", days_all),
                             ("仅 5m 那 59 天", [d for d in days_all
                                                 if d in win5m])):
            n_, amb_, lo_, hi_ = hourly_bounds(dsel, sess_h, lvm, kind)
            log_config(f"小时线上下界 {label} / {wlabel}")
            if not n_:
                continue
            e_lo = stats.expectancy([r for _, r in lo_])
            e_hi = stats.expectancy(hi_)
            p(f"  | {label} | {wlabel} | {n_} | {100*amb_/n_:.0f}% | "
              f"{e_lo['avg_r']:+.3f} | {e_hi['avg_r']:+.3f} |")
    p("")

    # ---- 几何复核 ----
    p("## §4 几何复核：5 分钟分辨率下的 MAE / MFE")
    p("")
    p("GG 复现报告给出的是「赢单最深回撤中位 0.303 ATR」。这里用 5m 重算同一个量，"
      "以 ATR 为单位（不是 R），只针对 C1/C3 的触发器总体：")
    p("")
    wins3 = [t for t in c3 if t.reason == "target"]
    if wins3:
        p(f"- C3 赢单（走完 0.618，n={len(wins3)}）的最深逆行中位 = "
          f"{statistics.median(t.mae_r * 0.382 for t in wins3):.3f} ATR，"
          f"75 分位 = "
          f"{statistics.quantiles([t.mae_r*0.382 for t in wins3], n=4)[2]:.3f} ATR")
        washed = sum(1 for t in wins3 if t.mae_r * 0.382 > 0.146)
        p(f"- 其中有 {washed}/{len(wins3)} 笔的逆行超过 0.146 ATR，"
          f"即把止损放在 0.236 位会洗掉 {stats.fmt_rate(washed, len(wins3))}"
          " —— 与 GG 复现报告的「洗掉 33% 赢单」对照。")
    p("")

    # ---- 需要多少样本才能定论 ----
    p("## §4.5 要多少样本才能定论")
    p("")
    for cname, t in (("C1", c1), ("C3", c3), ("C2(SPY)", c2_spy)):
        by_day: dict[date, list[float]] = {}
        for x in t:
            by_day.setdefault(x.day, []).append(x.r)
        daily_r = [sum(v) / len(v) for v in by_day.values()]
        if len(daily_r) < 3:
            continue
        sd = statistics.stdev(daily_r)
        mu = statistics.mean(daily_r)
        need = (1.96 * sd / abs(mu)) ** 2 if mu else float("inf")
        p(f"- {cname}：按日均 R = {mu:+.3f}，日间标准差 = {sd:.3f}，"
          f"现有 {len(daily_r)} 个交易日。若真实效应恰等于当前点估计，"
          f"要让 95% 区间排除 0 需要约 **{need:.0f} 个交易日**"
          f"（≈ {need/21:.0f} 个月的交易日）。")
    p("")
    p("这是最乐观的算法（假定点估计就是真值，且忽略择优膨胀）。"
      f"真实所需样本只会更多，因为当前点估计本身就是 {len(CONFIG_LOG)} 个格子里的一个。")
    p("")

    # ---- C2 出场时点 ----
    p("## §4.6 C2 的出场时点（判断它是不是开盘印刷伪影）")
    p("")
    for tag, tl in (("SPY", c2_spy), ("^GSPC", c2_gspc)):
        if not tl:
            continue
        b1 = sum(1 for t in tl if t.bars_held == 1)
        p(f"- {tag}: {b1}/{len(tl)} 笔在 09:30 那根 5m K 之内就结束了；"
          f"持仓根数分布 = {sorted(t.bars_held for t in tl)}")
    p("")

    # ---- 配置计数 ----
    p("## §5 配置计数（我一共试了多少个格子）")
    p("")
    p(f"**总计 {len(CONFIG_LOG)} 个配置**，逐条列出：")
    p("")
    for i, tag in enumerate(CONFIG_LOG, 1):
        p(f"{i:3d}. {tag}")
    p("")

    text = "\n".join(out)
    print(text)
    return text


if __name__ == "__main__":
    main()

# ==============================================================================
# CHANGE LOG（预登记之后的任何改动都必须记在这里）
# ==============================================================================
# 第一次运行之后做了以下修改，逐条如实记录：
#
# #1  [BUG FIX，会改变已发布数字]  成本折算原来写成 spread_pts / risk_pts。
#     对 ^GSPC 这是对的（点差与风险都以 SPX 指数点计），但 C2 的主标的是 SPY，
#     它的 risk_pts 是美元（SPY≈SPX/10），于是同一个 0.5 点差被当成 0.5 美元，
#     把 SPY 的成本高估了约 10 倍。改为先把点差换算成「当日 SPX ATR 的比例」，
#     再除以该笔的 risk_atr。受影响的只有 C2/SPY 的成本行；C1/C3/C2b 的
#     ^GSPC 数字不变（已核对）。这是修一个错误，不是调一个参数。
#
# #2  [新增稳健性检验，不改动任何构造定义]  §3.5 入场根盘内先后顺序的最保守读法
#     （入场那根 K 只判止损不判目标）。加它的原因是 C1 的目标只有 0.146 ATR，
#     一根 5m K 装得下整段行程，先后顺序在该分辨率上不可知。
#
# #3  [新增稳健性检验]  §3.6 730 天小时线的上下界复核。只给上下界、不给点估计，
#     符合纪律第 5 条。它把样本从 26 个交易日扩到 700+，代价是分辨率。
#
# #4  [新增诊断]  §2 触发器账目、§4.5 所需样本量、§4.6 C2 出场时点分布。
#
# 三个构造的触发条件 / 入场 / 止损 / 目标 / 时段 / 最大持仓，自预登记以来
# 一个字都没有改过。§3 的敏感性网格是事前就打算全印的，不是事后加的。
