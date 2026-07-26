"""位作为【风险定义点】的赔率结构检验 —— 对几何零假设与随机锚安慰剂。

第一轮问的是"位能否预测方向"（答案：不能）。本轮问的是一个完全不同、
而且第一轮从未测过的问题：

    在具名 ATR 位 L 上建仓、把止损放到位的另一侧 S，把目标放到下一个具名位 T，
    其【赔率结构】是否优于在任意价格上建同样几何的仓？

这个问题必须同时对两个基准检验，缺一不可：

  对照一 —— 几何零假设。
      对无漂移随机游走，P(先到目标) = S / (S + T)，且该几何下的打平胜率
      恒等于 S / (S + T)。所以"高盈亏比 + 低胜率"本身不产生任何期望值。
      任何"位有价值"的主张必须跑赢 S/(S+T)，不是跑赢 50%。
      因为每笔交易的 S、T 都不同，零假设是异质的 —— 用 Poisson-binomial
      正态近似做检验：mu = Σp_i，sigma = sqrt(Σp_i(1-p_i))，z = (k - mu)/sigma。

  对照二 —— 随机锚安慰剂。
      第一轮的安慰剂只换了比例（把 0.382 换成 0.40），没有换"是不是位"。
      本轮：同一天、同一条 5 分钟路径、同样的 S 和 T（绝对价格距离完全相同），
      把入场锚 L 换成 L' = L ± U(0.05, 0.30) * ATR，并强制 L' 距离任何具名
      比例至少 0.04 ATR（保证它确实不是位）。每个真实交易配 200 次重抽。
      这个安慰剂是【逐笔配对】的：真实交易 i 的零假设概率就是它自己那 200 次
      重抽的命中率 q_i，因此时间预算、当日波动率、盘中时段全部自动匹配。

      这条对照还顺带解决了一个真实的方法论问题：几何零假设 S/(S+T) 假设
      无限时间，而 0DTE 收盘强制平仓。安慰剂用的是同一个时间预算，所以它是
      【经验校准过的】零假设。报告同时给出安慰剂自己对 S/(S+T) 的 z ——
      如果安慰剂也同向偏离，那就是时间预算的假象，不是位的功劳。

参数全部预先定死，不许搜索：
    位 L      ±0.236 / ±0.382 / ±0.5 / ±0.618 / ±1.0
    止损 S    {0.08, 0.15} ATR —— 两个值都报告，不挑
    目标 T    到下一个具名位的距离（结构性定义，非搜索）
    方向      cont（顺着离开锚点的方向）/ rev（回归锚点的方向）—— 两个都报告
    路径判定  5 分钟 60 天为主；小时线 730 天为低分辨率对照，标注局限

盘中歧义（同一根 K 内同时触及止损与目标）无法用 5 分钟数据解决。
因此三种判定策略全部报告：
    P1 悲观   含入场 K，歧义算止损（主口径，对"位有用"假说最不利）
    P2 乐观   含入场 K，歧义算目标
    P3 跳过   从入场 K 的下一根开始判定，歧义算止损
安慰剂用完全相同的判定策略，所以【位 vs 安慰剂】的比较对判定策略免疫；
只有【位 vs S/(S+T)】的比较受它影响。这是把安慰剂当主判据的又一个理由。
"""

from __future__ import annotations

import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data, levels, stats  # noqa: E402

# ---------------------------------------------------------------- 预注册参数

ENTRY_RATIOS: tuple[float, ...] = (
    -1.0, -0.618, -0.5, -0.382, -0.236, 0.236, 0.382, 0.5, 0.618, 1.0,
)
S_ATR: tuple[float, ...] = (0.08, 0.15)
DIRS: tuple[str, ...] = ("cont", "rev")

# 目标的"下一个具名位"用 Saty 自己的完整梯子（含 0.786），结构性定义。
NAMED_LADDER: tuple[float, ...] = tuple(sorted(
    {0.0}
    | {r for r in (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)}
    | {-r for r in (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618)}
))

PLACEBO_DRAWS = 200
PLACEBO_MIN_OFFSET = 0.05      # ATR
PLACEBO_MAX_OFFSET = 0.30      # ATR
PLACEBO_KEEPOUT = 0.04         # 距任何具名比例至少这么远，保证"不是位"
PLACEBO_MIN_VALID = 20         # 有效重抽少于这个数就不进配对检验
TIME_WINDOW_BARS = 6           # 时间匹配安慰剂：触及时刻距真实触及 ≤ 这么多根 K
SEED = 20260726

# 安慰剂变体（同一检验的对照列，全部报告）：
#   all   ±U(0.05,0.30) ATR 全部抽样（任务书原始口径）
#   near  只取比真实位更靠近 PDC 锚点的一侧
#   far   只取比真实位更远离 PDC 锚点的一侧
#   pair  近侧 + 远侧成对、各半权重 —— 距离受控的主对照
#   time  只取触及时刻与真实触及相差 ≤ TIME_WINDOW_BARS 根 K 的抽样
PLACEBO_VARIANTS = ("all", "near", "far", "pair", "time")

COST_SPX_POINTS = 0.4          # SPX 往返摩擦，折算成 R 时除以 S 的点数


def next_named(r: float, sign: int) -> float | None:
    if sign > 0:
        c = [x for x in NAMED_LADDER if x > r + 1e-9]
        return min(c) if c else None
    c = [x for x in NAMED_LADDER if x < r - 1e-9]
    return max(c) if c else None


def near_named(r: float, tol: float = PLACEBO_KEEPOUT) -> bool:
    return any(abs(r - x) < tol for x in NAMED_LADDER)


# ---------------------------------------------------------------- 路径判定


class Session:
    __slots__ = ("day", "H", "L", "C", "open0", "n")

    def __init__(self, day, bars):
        self.day = day
        self.H = [b.high for b in bars]
        self.L = [b.low for b in bars]
        self.C = [b.close for b in bars]
        self.open0 = bars[0].open        # 盘中首根 K 的开盘（非日线 open 字段）
        self.n = len(bars)


def first_touch(s: Session, price: float, side: int, start: int = 0) -> int:
    """首次触及 price 的 K 下标；side=+1 从下方上来，-1 从上方下去。-1 表示未触及。"""
    if side > 0:
        H = s.H
        for i in range(start, s.n):
            if H[i] >= price:
                return i
        return -1
    L = s.L
    for i in range(start, s.n):
        if L[i] <= price:
            return i
    return -1


def race(s: Session, i0: int, up: float, dn: float) -> tuple[int, bool, bool]:
    """从 i0 开始跑赛跑。返回 (解决的 K 下标, 是否触上轨, 是否触下轨)。

    一旦某根 K 触及任意一轨即返回：若只触一轨，另一轨必然更晚（或永不）；
    若同一根同时触两轨，那就是盘中歧义，交给上层的判定策略处理。
    """
    H, L, n = s.H, s.L, s.n
    for i in range(i0, n):
        hu = H[i] >= up
        hd = L[i] <= dn
        if hu or hd:
            return i, hu, hd
    return -1, False, False


# 结果编码：0 = 目标, 1 = 止损, 2 = 超时（收盘平）
TARGET, STOP, TIMEOUT = 0, 1, 2


def adjudicate(s: Session, ti: int, entry: float, dsign: int,
               s_pts: float, t_pts: float) -> tuple[int, int, int, bool]:
    """返回 (P1 悲观, P2 乐观, P3 跳过入场K, 是否出现盘中歧义)。"""
    if dsign > 0:
        up, dn = entry + t_pts, entry - s_pts
        up_is_target = True
    else:
        up, dn = entry + s_pts, entry - t_pts
        up_is_target = False

    i1, hu, hd = race(s, ti, up, dn)
    if i1 < 0:
        p1 = p2 = TIMEOUT
        tie = False
    elif hu and hd:
        tie = True
        p1, p2 = STOP, TARGET
    else:
        tie = False
        hit_target = (hu == up_is_target)
        p1 = p2 = TARGET if hit_target else STOP

    # P3：跳过入场 K
    if i1 == ti:
        i2, hu2, hd2 = race(s, ti + 1, up, dn)
        if i2 < 0:
            p3 = TIMEOUT
        elif hu2 and hd2:
            p3 = STOP
        else:
            p3 = TARGET if ((hu2 == up_is_target)) else STOP
    else:
        p3 = p1
    return p1, p2, p3, tie


def r_multiple(outcome: int, s: Session, entry: float, dsign: int,
               s_pts: float, t_pts: float, cost_pts: float) -> float:
    cost_r = cost_pts / s_pts
    if outcome == TARGET:
        return t_pts / s_pts - cost_r
    if outcome == STOP:
        return -1.0 - cost_r
    return dsign * (s.C[-1] - entry) / s_pts - cost_r


# ---------------------------------------------------------------- 统计工具


def poisson_binomial_z(k: int, ps: list[float]) -> tuple[float, float, float]:
    """异质零假设下的 z。返回 (z, 期望率, n)。"""
    n = len(ps)
    if n == 0:
        return 0.0, 0.0, 0
    mu = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    if var <= 0:
        return 0.0, mu / n, n
    return (k - mu) / math.sqrt(var), mu / n, n


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------- 主流程


class Arm:
    """一条数据臂（5m 或 1h）上的完整结果容器。"""

    def __init__(self, tag: str, note: str):
        self.tag = tag
        self.note = note
        self.rows: list[dict] = []          # 每笔真实交易
        self.touch_real = defaultdict(lambda: [0, 0])   # |r| -> [touched, days]
        self.touch_plac = defaultdict(lambda: [0, 0])
        self.ti_real: list[float] = []      # 触及时刻在盘中的相对位置
        self.ti_plac: list[float] = []
        self.n_sessions = 0
        self.ties_real = 0
        self.races_real = 0
        self.curve: dict = {}


def run_arm(tag: str, note: str, sessions: dict, lmap: dict,
            cost_pts: float, draws: int = PLACEBO_DRAWS) -> Arm:
    arm = Arm(tag, note)
    rng = random.Random(SEED)

    for day in sorted(sessions):
        s = sessions[day]
        dl = lmap.get(day)
        if dl is None or dl.atr <= 0:
            continue
        arm.n_sessions += 1
        anchor, atr = dl.anchor, dl.atr

        for r in ENTRY_RATIOS:
            key = abs(r)
            arm.touch_real[key][1] += 1
            Lp = anchor + r * atr
            side = 1 if Lp > s.open0 else -1
            ti = first_touch(s, Lp, side)
            if ti < 0:
                continue
            arm.touch_real[key][0] += 1
            arm.ti_real.append(ti / s.n)

            # --- 安慰剂锚：成对抽（近侧 / 远侧），四个 (dir,S) 格子共用 ---
            # 成对是为了压掉"触及概率随 |r| 单调下降"这个混淆：只抽单个偏移时，
            # 被触及的安慰剂锚会系统性地更靠近 PDC 锚点，而靠近锚点的价格天然
            # 更容易顺势延续、更不容易反转 —— 那会凭空造出一个假的"位反转优势"。
            sgn = 1.0 if r > 0 else -1.0
            pl: list[tuple[float, int, str]] = []   # (L', touch idx, near/far)
            pairs: list[tuple[tuple[float, int], tuple[float, int]]] = []
            tries = 0
            while len(pl) < draws * 2 and tries < draws * 12:
                tries += 1
                off = rng.uniform(PLACEBO_MIN_OFFSET, PLACEBO_MAX_OFFSET)
                r_near = r - sgn * off
                r_far = r + sgn * off
                if near_named(r_near) or near_named(r_far):
                    continue
                if abs(r_far) > 2.0 or abs(r_near) < 0.03:
                    continue
                got = []
                for rp, tagp in ((r_near, "near"), (r_far, "far")):
                    Lq = anchor + rp * atr
                    sideq = 1 if Lq > s.open0 else -1
                    arm.touch_plac[key][1] += 1
                    tq = first_touch(s, Lq, sideq)
                    if tq >= 0:
                        arm.touch_plac[key][0] += 1
                        arm.ti_plac.append(tq / s.n)
                    pl.append((Lq, tq, tagp))
                    got.append((Lq, tq))
                if got[0][1] >= 0 and got[1][1] >= 0:
                    pairs.append((got[0], got[1]))

            for dname in DIRS:
                dsign = (1 if r > 0 else -1) * (1 if dname == "cont" else -1)
                nxt = next_named(r, dsign)
                if nxt is None:
                    continue
                t_pts = abs(nxt - r) * atr
                for sa in S_ATR:
                    s_pts = sa * atr
                    p1, p2, p3, tie = adjudicate(s, ti, Lp, dsign,
                                                 s_pts, t_pts)
                    arm.races_real += 1
                    arm.ties_real += int(tie)
                    p0 = s_pts / (s_pts + t_pts)

                    # --- 五个安慰剂变体（同一检验的对照列，不是新格子）---
                    buckets: dict[str, list[list[int]]] = {
                        "all": [[], [], []], "near": [[], [], []],
                        "far": [[], [], []], "time": [[], [], []],
                    }
                    pl_r = {1: [], 2: [], 3: []}
                    tw = TIME_WINDOW_BARS
                    for Lq, tq, tagp in pl:
                        if tq < 0:
                            continue
                        q = adjudicate(s, tq, Lq, dsign, s_pts, t_pts)
                        for j in range(3):
                            buckets["all"][j].append(q[j])
                            buckets[tagp][j].append(q[j])
                            if abs(tq - ti) <= tw:
                                buckets["time"][j].append(q[j])
                            pl_r[j + 1].append(
                                r_multiple(q[j], s, Lq, dsign, s_pts,
                                           t_pts, cost_pts))

                    # 对称配对：每一对（近侧 + 远侧）各贡献 1/2 权重
                    pair_vals = {1: [], 2: [], 3: []}
                    pair_r = {1: [], 2: [], 3: []}
                    for (La, ta), (Lb, tb) in pairs:
                        qa = adjudicate(s, ta, La, dsign, s_pts, t_pts)
                        qb = adjudicate(s, tb, Lb, dsign, s_pts, t_pts)
                        for j, pol in enumerate((1, 2, 3)):
                            pair_r[pol].append(0.5 * (
                                r_multiple(qa[j], s, La, dsign, s_pts, t_pts, cost_pts)
                                + r_multiple(qb[j], s, Lb, dsign, s_pts, t_pts, cost_pts)))
                        for j, pol in enumerate((1, 2, 3)):
                            vals = [o for o in (qa[j], qb[j]) if o != TIMEOUT]
                            if vals:
                                pair_vals[pol].append(
                                    sum(1 for o in vals if o == TARGET) / len(vals))

                    def cond_rate(outs):
                        res = [o for o in outs if o != TIMEOUT]
                        if not res:
                            return None, 0
                        return (sum(1 for o in res if o == TARGET) / len(res),
                                len(res))

                    row = {
                        "day": day, "r": r, "dir": dname, "s_atr": sa,
                        "t_atr": abs(nxt - r), "next": nxt,
                        "s_pts": s_pts, "t_pts": t_pts, "p0": p0,
                        "side": side, "ti": ti, "tie": tie,
                        "o1": p1, "o2": p2, "o3": p3,
                        "R1": r_multiple(p1, s, Lp, dsign, s_pts, t_pts, cost_pts),
                        "R2": r_multiple(p2, s, Lp, dsign, s_pts, t_pts, cost_pts),
                        "R3": r_multiple(p3, s, Lp, dsign, s_pts, t_pts, cost_pts),
                        "rr": t_pts / s_pts,
                    }
                    for pol in (1, 2, 3):
                        row[f"qR{pol}"] = mean(pl_r[pol]) if pl_r[pol] else None
                        row[f"qR{pol}_pair"] = (mean(pair_r[pol])
                                                if pair_r[pol] else None)
                    for bname, bb in buckets.items():
                        for j, pol in enumerate((1, 2, 3)):
                            rate, nres = cond_rate(bb[j])
                            row[f"q{pol}_{bname}"] = rate
                            row[f"qn{pol}_{bname}"] = nres
                    for pol in (1, 2, 3):
                        vs = pair_vals[pol]
                        row[f"q{pol}_pair"] = mean(vs) if vs else None
                        row[f"qn{pol}_pair"] = len(vs)
                    arm.rows.append(row)
    return arm


def touch_curve(sessions: dict, lmap: dict, lo: float = -1.35,
                hi: float = 1.35, step: float = 0.002) -> dict:
    """|比例| -> 触及率，确定性细网格。用来看具名比例上有没有台阶。"""
    n = int(round((hi - lo) / step)) + 1
    grid = [round(lo + i * step, 3) for i in range(n)]
    out = {g: [0, 0] for g in grid}
    for day in sorted(sessions):
        s = sessions[day]
        dl = lmap.get(day)
        if dl is None or dl.atr <= 0:
            continue
        for g in grid:
            price = dl.anchor + g * dl.atr
            side = 1 if price > s.open0 else -1
            out[g][1] += 1
            if first_touch(s, price, side) >= 0:
                out[g][0] += 1
    return out


# ---------------------------------------------------------------- 报告


CELL_COUNT = 0


def bump(n: int = 1) -> None:
    global CELL_COUNT
    CELL_COUNT += n


def summarize(rows: list[dict], pol: int = 1) -> dict:
    """一组交易的完整统计。pol 1/2/3 对应三种判定策略。"""
    ok, rk = f"o{pol}", f"R{pol}"
    n = len(rows)
    if n == 0:
        return {"n": 0}
    res = [x for x in rows if x[ok] != TIMEOUT]
    k = sum(1 for x in res if x[ok] == TARGET)
    z_geo, exp_geo, _ = poisson_binomial_z(k, [x["p0"] for x in res])

    out = {
        "n": n, "n_res": len(res), "k": k,
        "timeout": (n - len(res)) / n,
        "rate": k / len(res) if res else 0.0,
        "ci": stats.wilson(k, len(res)),
        "geo": exp_geo, "z_geo": z_geo,
        "rr": mean([x["rr"] for x in rows]),
        "tie_rate": mean([1.0 if x["tie"] else 0.0 for x in rows]),
    }
    for v in PLACEBO_VARIANTS:
        qk, nk = f"q{pol}_{v}", f"qn{pol}_{v}"
        sub = [x for x in res
               if x.get(qk) is not None and x.get(nk, 0) >= PLACEBO_MIN_VALID]
        kp = sum(1 for x in sub if x[ok] == TARGET)
        z, exp, npl = poisson_binomial_z(kp, [x[qk] for x in sub])
        out[f"plac_{v}"] = exp
        out[f"z_{v}"] = z
        out[f"n_{v}"] = npl
        out[f"obs_{v}"] = kp / npl if npl else 0.0

    e = stats.expectancy([x[rk] for x in rows])
    qrs = [x[f"qR{pol}"] for x in rows if x.get(f"qR{pol}") is not None]
    qrp = [x[f"qR{pol}_pair"] for x in rows
           if x.get(f"qR{pol}_pair") is not None]
    out.update({"avg_r": e["avg_r"], "total_r": e["total_r"],
                "mdd": e["max_dd"], "avg_r_plac": mean(qrs),
                "avg_r_pair": mean(qrp),
                "win_rate": e["win_rate"], "breakeven": e["breakeven_wr"]})
    return out


def fmt_cell(label: str, d: dict) -> str:
    """主口径行：命中 / 几何零 / 距离受控安慰剂(pair) / 原始安慰剂(all)。"""
    if d["n"] == 0:
        return f"  {label:<22} n=0"
    lo, hi = d["ci"]
    return (f"  {label:<22} n={d['n']:<5} 超时={100*d['timeout']:4.1f}% "
            f"R:R={d['rr']:4.2f} | 命中 {100*d['rate']:5.1f}% "
            f"[{100*lo:4.1f},{100*hi:5.1f}] n={d['n_res']:<5}"
            f"| 几何零 {100*d['geo']:5.1f}% z={d['z_geo']:+6.2f}"
            f" | 安慰剂pair {100*d['plac_pair']:5.1f}% z={d['z_pair']:+6.2f}"
            f" | 安慰剂all {100*d['plac_all']:5.1f}% z={d['z_all']:+6.2f}"
            f" | 均R={d['avg_r']:+.3f} vs pair {d['avg_r_pair']:+.3f}")


def fmt_variants(label: str, d: dict) -> str:
    """安慰剂五变体全览行。"""
    if d["n"] == 0:
        return f"  {label:<22} n=0"
    parts = []
    for v in PLACEBO_VARIANTS:
        parts.append(f"{v}={100*d[f'plac_{v}']:5.1f}% z={d[f'z_{v}']:+6.2f} "
                     f"(配对n={d[f'n_{v}']})")
    return (f"  {label:<22} 命中 {100*d['rate']:5.1f}% | "
            + " | ".join(parts))


def report(arm: Arm, out) -> None:
    p = lambda *a: print(*a, file=out)          # noqa: E731

    p("")
    p("=" * 132)
    p(f"数据臂：{arm.tag}")
    p(f"  {arm.note}")
    p(f"  交易日 {arm.n_sessions}，真实赛跑 {arm.races_real} 场，"
      f"其中盘中歧义（同一根 K 同时触及止损与目标）"
      f"{100*arm.ties_real/max(1,arm.races_real):.1f}%")
    p("=" * 132)

    # --- 磁铁检验：触及率是不是 |比例| 的平滑函数，具名位上有没有台阶 ---
    p("")
    p("【0】磁铁检验 —— 触及率沿比例梯子是否平滑？具名位上有没有台阶？")
    p("     用确定性细网格（步长 0.002 ATR，具名比例全部落在网格上），不是抽样。")
    p("     局部基线 = 对同侧、|距离| 在 0.03~0.15 ATR 的非具名邻居做局部线性拟合")
    p("     后外推到该比例；σ = 邻居围绕该拟合的残差 RMS。台阶存在 ⇔ 残差 >> 1σ。")
    p("     （邻居之间高度相关，σ 只是尺度参考，不是严格检验；严格版第一轮已在 20 年"
      "日线上做过，结论是 |残差| < 0.8σ。）")
    p(f"  {'比例':<9}{'触及率':<32}{'局部拟合':<11}{'残差(pp)':<11}{'残差/σ':<11}"
      f"{'折算成天数'}")
    for r in ENTRY_RATIOS:
        k, n = arm.curve.get(round(r, 3), [0, 0])
        if n == 0:
            continue
        rate = k / n
        xs, ys = [], []
        for g, (gk, gn) in arm.curve.items():
            if gn == 0 or g * r <= 0:
                continue
            d = abs(abs(g) - abs(r))
            if 0.03 <= d <= 0.15 and not near_named(g, 0.025):
                xs.append(abs(g))
                ys.append(gk / gn)
        if len(xs) < 8:
            continue
        mx, my = mean(xs), mean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        b = sxy / sxx if sxx > 0 else 0.0
        a = my - b * mx
        pred = a + b * abs(r)
        res = [y - (a + b * x) for x, y in zip(xs, ys)]
        sd = math.sqrt(sum(e * e for e in res) / (len(res) - 2))
        resid = rate - pred
        bump()
        p(f"  {r:<+9.3f}{stats.fmt_rate(k, n):<32}{100*pred:7.1f}%    "
          f"{100*resid:+8.2f}   {resid/sd if sd > 0 else 0:+7.2f}"
          f"    (= {resid*n:+.1f} 天)")
    p("")
    p("  触及率曲线（每 0.05 ATR 抽样打印；* 标记具名比例）：")
    line = []
    for i in range(-27, 28):
        g = round(i * 0.05, 3)
        cell = arm.curve.get(g)
        if not cell or cell[1] == 0:
            continue
        mark = "*" if near_named(g, 1e-6) else " "
        line.append(f"{g:+.2f}{mark}{100*cell[0]/cell[1]:5.1f}%")
    for i in range(0, len(line), 6):
        p("    " + "  ".join(line[i:i + 6]))
    p("")
    p("  【诊断】真实位触及时刻 vs 安慰剂锚触及时刻（盘中相对位置，0=开盘 1=收盘）：")
    p(f"    真实位 均值 {mean(arm.ti_real):.3f} (n={len(arm.ti_real)})   "
      f"安慰剂锚 均值 {mean(arm.ti_plac):.3f} (n={len(arm.ti_plac)})")
    p("    注：安慰剂 near 侧天生触及更早、far 侧更晚 —— 这正是必须用 pair / time")
    p("        变体做距离与时间控制的原因。")

    # --- 主表 ---
    for pol, pname in ((1, "P1 悲观（主口径）"), (2, "P2 乐观"), (3, "P3 跳过入场K")):
        head = "【1】" if pol == 1 else "【S】"
        p("")
        p(f"{head} 逐格结果 —— 判定策略 {pname}")
        p("     位 = 入场，止损 = 位反向 S，目标 = 下一个具名位")
        p("     命中 = P(先到目标 | 已解决)；几何零 = 均值 S/(S+T)；安慰剂 = 逐笔配对随机锚")
        for dname in DIRS:
            for sa in S_ATR:
                p("")
                kind = "离开锚点/顺势延续" if dname == "cont" else "回归锚点/反转"
                p(f"  --- 方向 {dname}（{kind}）  止损 S = {sa} ATR ---")
                for r in ENTRY_RATIOS:
                    rows = [x for x in arm.rows
                            if x["r"] == r and x["dir"] == dname
                            and x["s_atr"] == sa]
                    d = summarize(rows, pol)
                    if pol == 1:
                        bump()
                    p(fmt_cell(f"r={r:+.3f}", d))
                agg = summarize([x for x in arm.rows
                                 if x["dir"] == dname and x["s_atr"] == sa], pol)
                p(fmt_cell("  合计", agg))
        p("")
        p("  === 跨方向/跨止损合计 ===")
        for dname in DIRS:
            p(fmt_cell(f"全部 {dname}",
                       summarize([x for x in arm.rows if x["dir"] == dname], pol)))
        for sa in S_ATR:
            p(fmt_cell(f"全部 S={sa}",
                       summarize([x for x in arm.rows if x["s_atr"] == sa], pol)))
        p(fmt_cell("全部交易", summarize(arm.rows, pol)))

        p("")
        p(f"  === 安慰剂五变体全览（判定策略 {pname}）===")
        p("     all=原始 ±U(0.05,0.30)；near=只取更靠近锚点一侧；far=只取更远离一侧；")
        p("     pair=近远成对各半权重（距离受控，主对照）；time=触及时刻匹配。")
        for dname in DIRS:
            for sa in S_ATR:
                rows = [x for x in arm.rows
                        if x["dir"] == dname and x["s_atr"] == sa]
                p(fmt_variants(f"{dname} S={sa}", summarize(rows, pol)))
        for dname in DIRS:
            p(fmt_variants(f"全部 {dname}",
                           summarize([x for x in arm.rows if x["dir"] == dname], pol)))
        p(fmt_variants("全部交易", summarize(arm.rows, pol)))

        if pol == 1:
            p("")
            p("  【诊断】安慰剂自己 vs 几何零假设 —— 若安慰剂也同向偏离 S/(S+T)，"
              "说明偏离来自时间预算/盘中歧义，不是位。")
            for sa in S_ATR:
                rows = [x for x in arm.rows if x["s_atr"] == sa
                        and x.get("q1_pair") is not None
                        and x.get("qn1_pair", 0) >= PLACEBO_MIN_VALID]
                if not rows:
                    continue
                qbar = mean([x["q1_pair"] for x in rows])
                p0bar = mean([x["p0"] for x in rows])
                p(f"    S={sa}: 安慰剂(pair)条件命中 {100*qbar:5.1f}%  "
                  f"几何零 {100*p0bar:5.1f}%  差 {100*(qbar-p0bar):+5.1f}pp  "
                  f"(n={len(rows)} 笔配对)")

    # --- 接近方向拆分（仅合计层，避免网格择优） ---
    p("")
    p("【2】接近方向拆分（仅在合计层报告；P1 与 P3 都给出）")
    for pol in (1, 3):
        p(f"  --- P{pol} ---")
        for sa in S_ATR:
            for side, sn in ((1, "自下而上触及"), (-1, "自上而下触及")):
                rows = [x for x in arm.rows
                        if x["s_atr"] == sa and x["side"] == side]
                if pol == 1:
                    bump()
                p(fmt_cell(f"S={sa} {sn}", summarize(rows, pol)))

    # --- 分期稳定性 ---
    p("")
    p("【3】分期稳定性（按交易日中位数切两半；P1 与 P3 都给出）")
    days = sorted({x["day"] for x in arm.rows})
    if days:
        mid = days[len(days) // 2]
        for pol in (1, 3):
            p(f"  --- P{pol} ---")
            for lab, sel in (("前半段", lambda d: d < mid),
                             ("后半段", lambda d: d >= mid)):
                for sa in S_ATR:
                    rows = [x for x in arm.rows
                            if sel(x["day"]) and x["s_atr"] == sa]
                    if pol == 1:
                        bump()
                    p(fmt_cell(f"{lab} S={sa}", summarize(rows, pol)))

    # --- 期望值明细 ---
    p("")
    p("【4】实际期望 R（含成本；超时按收盘 mark-to-market）")
    p("     打平胜率一栏就是几何零假设的另一种写法 —— 它恒等于 S/(S+T)。")
    p("     P1 与 P3 都给出：见【校准】，P1 在 K振幅/S 大时系统性低估，P3 近似无偏。")
    for pol in (1, 3):
        p(f"  --- 判定策略 P{pol} ---")
        for dname in DIRS:
            for sa in S_ATR:
                rows = [x for x in arm.rows
                        if x["dir"] == dname and x["s_atr"] == sa]
                if not rows:
                    continue
                d = summarize(rows, pol)
                e = stats.expectancy([x[f"R{pol}"] for x in rows])
                p(f"    {dname} S={sa}: {stats.fmt_expectancy(e)}")
                p(f"        安慰剂 pair 均R = {d['avg_r_pair']:+.3f} "
                  f"(差 {d['avg_r']-d['avg_r_pair']:+.3f}R)；"
                  f"all 均R = {d['avg_r_plac']:+.3f} "
                  f"(差 {d['avg_r']-d['avg_r_plac']:+.3f}R)")
        d_all = summarize(arm.rows, pol)
        e_all = stats.expectancy([x[f"R{pol}"] for x in arm.rows])
        p(f"    全部交易: {stats.fmt_expectancy(e_all)}")
        p(f"        安慰剂 pair 均R = {d_all['avg_r_pair']:+.3f} "
          f"(差 {d_all['avg_r']-d_all['avg_r_pair']:+.3f}R)；"
          f"all 均R = {d_all['avg_r_plac']:+.3f} "
          f"(差 {d_all['avg_r']-d_all['avg_r_plac']:+.3f}R)")

    # --- 日级 block bootstrap：修正同一天内多笔交易的相关性 ---
    p("")
    p("【4b】日级 block bootstrap —— Poisson-binomial 的 z 假设逐笔独立，")
    p("      但同一天的多个位共用同一条路径，独立单位其实是【天】不是【笔】。")
    p("      这里按天有放回重抽 2000 次，给出以天为单位的标准误和修正后的 z。")
    p(f"  {'组':<18}{'判定':<6}{'比较':<22}{'差(pp)':<11}"
      f"{'朴素z':<9}{'block z'}")
    groups = [("全部交易", arm.rows)]
    for dname in DIRS:
        groups.append((f"全部 {dname}", [x for x in arm.rows if x["dir"] == dname]))
    for sa in S_ATR:
        groups.append((f"全部 S={sa}", [x for x in arm.rows if x["s_atr"] == sa]))
    for gname, rows in groups:
        for pol in (1, 3):
            ok = f"o{pol}"
            for bk, blab, use_plac in (("p0", "位 vs 几何零", False),
                                       (f"q{pol}_pair", "位 vs 安慰剂pair", False),
                                       ("p0", "安慰剂pair vs 几何零", True)):
                qk, nk = f"q{pol}_pair", f"qn{pol}_pair"
                sel = [x for x in rows if x[ok] != TIMEOUT
                       and x.get(bk) is not None
                       and (bk == "p0" and not use_plac
                            or x.get(nk, 0) >= PLACEBO_MIN_VALID
                            and x.get(qk) is not None)]
                if not sel:
                    continue
                byday: dict = {}
                for x in sel:
                    a = byday.setdefault(x["day"], [0.0, 0.0, 0])
                    a[0] += x[qk] if use_plac else int(x[ok] == TARGET)
                    a[1] += x[bk]
                    a[2] += 1
                days = list(byday.values())
                K = sum(a[0] for a in days)
                MU = sum(a[1] for a in days)
                NN = sum(a[2] for a in days)
                obs = K / NN - MU / NN
                var = sum(x[bk] * (1 - x[bk]) for x in sel)
                naive = ((K - MU) / math.sqrt(var)
                         if (var > 0 and not use_plac) else float("nan"))
                brng = random.Random(SEED + pol)
                diffs = []
                nd = len(days)
                for _ in range(2000):
                    k = mu = n = 0.0
                    for _ in range(nd):
                        a = days[int(brng.random() * nd)]
                        k += a[0]
                        mu += a[1]
                        n += a[2]
                    if n:
                        diffs.append(k / n - mu / n)
                m = mean(diffs)
                sd = math.sqrt(sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1))
                bz = obs / sd if sd > 0 else 0.0
                nstr = "   n/a " if naive != naive else f"{naive:+7.2f}"
                p(f"  {gname:<18}P{pol:<5}{blab:<22}{100*obs:+9.2f}   "
                  f"{nstr}  {bz:+7.2f}")
    p("      注意 block z 不一定小于朴素 z：同一天里上下两侧的位方向相反，")
    p("      日内偏离是负相关的，所以按天重抽有时反而缩小标准误。两者都报告。")
    p("      读法：只有当【位 vs 安慰剂pair】显著时，才是位本身在做功；")
    p("      如果【位 vs 几何零】和【安慰剂pair vs 几何零】一起显著，那是这段行情")
    p("      的共同属性（漂移/趋势持续性），任何入场点都拿得到，与位无关。")

    # --- 家族级防择优：40 个主格子的 z 分布 ---
    p("")
    p("【5】家族级防择优 —— 40 个主格子（10 位 × 2 方向 × 2 止损）的 z 分布")
    p("     若位不携带信息，这 40 个 z 应当近似标准正态：|z|>1.96 的期望个数 = 2.0，")
    p("     |z| 最大值的期望 ≈ 2.7。任何单格'发现'必须与这个尺度比较。")
    for pol in (1, 2, 3):
        for kind, lab in (("pair", "距离受控安慰剂"), ("all", "原始安慰剂"),
                          ("geo", "几何零假设")):
            zs = []
            for r in ENTRY_RATIOS:
                for dname in DIRS:
                    for sa in S_ATR:
                        rows = [x for x in arm.rows if x["r"] == r
                                and x["dir"] == dname and x["s_atr"] == sa]
                        if not rows:
                            continue
                        d = summarize(rows, pol)
                        z = d["z_geo"] if kind == "geo" else d[f"z_{kind}"]
                        zs.append(z)
            if not zs:
                continue
            big = sum(1 for z in zs if abs(z) > 1.96)
            p(f"    P{pol} vs {lab:<8}: 格子={len(zs):<3} "
              f"均z={mean(zs):+5.2f} |z|>1.96 的格子={big:<2} "
              f"最大|z|={max(abs(z) for z in zs):4.2f}")


def validate(out) -> None:
    """在合成的【无漂移随机游走】上校准整套机器，用连续路径当 ground truth。

    合成得和真实研究的机制完全一样：路径从 100 出发，位 L = 100 + d；
    入场 = 路径【首次触及 L】的那一刻（所以入场必然发生在某根 K 的中间）；
    然后跑 L+T / L-S 的赛跑。

    因为底层路径是连续的（步长远小于止损距离），可以直接在路径上跑出【正确答案】，
    再把同一条路径聚合成不同粗细的 K 线、用主脚本的 adjudicate 去判，两者一比就知道：

      (A) 正确答案是否等于 S/(S+T) —— 验证可选停时定理 + 本文的检验实现；
      (B) K 线粗细造成多少判错、判错往哪一边偏 —— 这直接给出主表里
          【位 vs S/(S+T)】那一列的系统误差有多大。

    真实 5 分钟数据上「K 振幅 / S」的中位数是 0.87（S=0.08 ATR）和 0.47（S=0.15 ATR），
    小时线上是 3.29 和 1.76 —— 拿这两个数去查下表就知道各自的可信度。

    结论提前说：这就是为什么【位 vs 安慰剂】才是主判据 —— 安慰剂吃同一份判错，
    差值里它约掉了；而【位 vs S/(S+T)】里它约不掉。
    """
    p = lambda *a: print(*a, file=out)          # noqa: E731
    rng = random.Random(SEED)
    from datetime import datetime as _dt, date as _d

    TOTAL = 4800                          # 每条路径总步数
    SIGMA = 8.0 / math.sqrt(TOTAL)        # 整条路径总 sigma = 8.0
    LEVEL_D = 1.0                         # 位在起点上方 1.0
    GRAINS = (2, 6, 12, 24, 48, 96, 192)  # 每根 K 聚合多少步
    N = 4000

    def bars_from(path, k):
        out = []
        for i in range(0, len(path) - 1, k):
            seg = path[i:i + k + 1]
            out.append(data.Bar(_dt(2026, 1, 1), _d(2026, 1, 1),
                                seg[0], max(seg), min(seg), seg[-1], 0))
        return Session(_d(2026, 1, 1), out)

    def truth(path, e, up, dn):
        """连续路径上的正确答案。"""
        for i in range(e, len(path)):
            if path[i] >= up:
                return TARGET
            if path[i] <= dn:
                return STOP
        return TIMEOUT

    paths, entries = [], []
    while len(paths) < N:
        px = 100.0
        path = [px]
        for _ in range(TOTAL):
            px += rng.gauss(0, SIGMA)
            path.append(px)
        lvl = 100.0 + LEVEL_D
        e = next((i for i, v in enumerate(path) if v >= lvl), -1)
        if e < 0 or e > TOTAL - 200:      # 要留下足够的剩余预算
            continue
        paths.append(path)
        entries.append(e)

    p("")
    p("=" * 132)
    p("【校准】在合成无漂移随机游走上验证整套机器（连续路径 = ground truth）")
    p(f"  {N} 条路径 x {TOTAL} 步（总 sigma=8.0）。入场 = 首次触及 L=101.0 的那一刻，")
    p("  所以入场必然落在某根 K 的中间 —— 和真实研究的机制一致。")
    p("  所有粒度共用同一批路径和同一个入场点，唯一变化的是 K 线的粗细。")
    p("=" * 132)
    p("")
    p("(A) 连续路径上的正确答案 vs S/(S+T)")
    p(f"  {'几何':<26}{'正确答案命中率':<32}{'S/(S+T)':<11}{'z':<8}{'超时'}")
    for S, T in ((0.5, 1.5), (1.0, 2.0), (1.0, 1.0), (2.0, 1.0), (1.5, 0.5)):
        k = res = to = 0
        for path, e in zip(paths, entries):
            o = truth(path, e, path[e] + T, path[e] - S)
            if o == TIMEOUT:
                to += 1
            else:
                res += 1
                k += int(o == TARGET)
        p0 = S / (S + T)
        z = (k - res * p0) / math.sqrt(res * p0 * (1 - p0)) if res else 0.0
        p(f"  S={S} T={T} R:R={T/S:<15.2f}{stats.fmt_rate(k, res):<32}"
          f"{100*p0:6.2f}%    {z:+5.2f}   {to}")
    p("  全部落在 S/(S+T) 上 ⇒ 可选停时定理成立，本文的 Poisson-binomial 检验实现正确。")

    p("")
    p("(B) 把同一条路径聚合成 K 线后，主脚本的判定错多少、往哪偏")
    p("    S=1.0 T=2.0（R:R=2），正确答案见上表（33.3%）。")
    p(f"  {'K振幅/S中位数':<15}{'P1命中率':<11}{'P1判错率':<10}{'P1偏差(pp)':<12}"
      f"{'P2命中率':<11}{'P2偏差':<10}{'P3命中率':<11}{'P3偏差':<10}{'歧义率'}")
    S, T = 1.0, 2.0
    truths = [truth(path, e, path[e] + T, path[e] - S)
              for path, e in zip(paths, entries)]
    tk = sum(1 for o in truths if o == TARGET)
    tres = sum(1 for o in truths if o != TIMEOUT)
    trate = tk / tres
    for g in GRAINS:
        cnt = {1: [0, 0, 0], 2: [0, 0, 0], 3: [0, 0, 0]}
        wrong = ties = 0
        rngs = []
        for path, e, tr in zip(paths, entries, truths):
            s = bars_from(path, g)
            ei = e // g
            rngs.extend(h - l for h, l in zip(s.H, s.L))
            o1, o2, o3, tie = adjudicate(s, ei, path[e], +1, S, T)
            ties += int(tie)
            wrong += int(o1 != tr)
            for pol, o in ((1, o1), (2, o2), (3, o3)):
                cnt[pol][o] += 1

        def rate(pol):
            k, st, _ = cnt[pol]
            return k / (k + st) if (k + st) else 0.0
        rngs.sort()
        ratio = rngs[len(rngs) // 2] / S
        p(f"  {ratio:<15.2f}{100*rate(1):<11.2f}{100*wrong/N:<10.1f}"
          f"{100*(rate(1)-trate):<+12.2f}{100*rate(2):<11.2f}"
          f"{100*(rate(2)-trate):<+10.2f}{100*rate(3):<11.2f}"
          f"{100*(rate(3)-trate):<+10.2f}{100*ties/N:5.1f}%")
    p("  判错率随 K 线变粗单调上升；P1（悲观）系统性低估命中率，P2（乐观）系统性高估。")
    p("  真实 5 分钟臂的「K振幅/S 中位数」= 0.87 (S=0.08) / 0.47 (S=0.15)；")
    p("  真实小时线臂 = 3.29 (S=0.08) / 1.76 (S=0.15)。查表读各自的系统误差。")


def measure_bar_to_stop(sessions: dict, lmap: dict) -> dict:
    """真实数据里「K 线振幅 / 止损距离」到底是多少 —— 用来读上表。"""
    out = {}
    for sa in S_ATR:
        vals = []
        for day, s in sessions.items():
            dl = lmap.get(day)
            if dl is None or dl.atr <= 0:
                continue
            spts = sa * dl.atr
            for h, l in zip(s.H, s.L):
                vals.append((h - l) / spts)
        vals.sort()
        out[sa] = (vals[len(vals) // 2], mean(vals)) if vals else (0.0, 0.0)
    return out


def build_sessions(bars, min_bars: int) -> dict:
    out = {}
    for day, rows in data.group_by_day(bars).items():
        if len(rows) >= min_bars:
            out[day] = Session(day, rows)
    return out


def main() -> None:
    out = sys.stdout
    p = lambda *a: print(*a, file=out)          # noqa: E731

    p("位作为【风险定义点】的赔率结构检验")
    p("=" * 132)
    p(f"预注册参数：位 {ENTRY_RATIOS}")
    p(f"            止损 S ∈ {S_ATR} ATR（两个都报告，不挑）")
    p(f"            目标 T = 到下一个具名位的距离，具名梯子 = {NAMED_LADDER}")
    p(f"            方向 {DIRS}；成本 {COST_SPX_POINTS} SPX 点（折算 R = 成本/S点数）")
    p(f"            安慰剂 {PLACEBO_DRAWS} 次/笔，偏移 ±U({PLACEBO_MIN_OFFSET},"
      f"{PLACEBO_MAX_OFFSET}) ATR，距任何具名比例 ≥ {PLACEBO_KEEPOUT} ATR；seed={SEED}")

    dly = data.daily("^GSPC")
    lmap = levels.build(dly)     # anchor = 前日收盘，ATR = Wilder(14)，不含任何 open 字段

    fine = build_sessions(data.fine("^GSPC"), 40)
    arm5 = run_arm("^GSPC 5 分钟 / 60 天（主）",
                   "路径判定用 5 分钟 K。日线位图 anchor=前日收盘、ATR=Wilder(14)，"
                   "不使用任何日线 open 字段；盘中参考价用当日首根 5 分钟 K 的开盘。",
                   fine, lmap, COST_SPX_POINTS)
    arm5.curve = touch_curve(fine, lmap)
    report(arm5, out)
    p("")
    p("  【真实数据里的 K 线振幅 / 止损距离】—— 用来读【校准】(B) 表")
    for sa, (med, avg) in measure_bar_to_stop(fine, lmap).items():
        p(f"    5 分钟 K，S={sa} ATR：中位数 {med:.2f}，均值 {avg:.2f}")

    hourly = build_sessions(data.hourly("^GSPC"), 5)
    arm1h = run_arm("^GSPC 小时线 / 730 天（低分辨率对照）",
                    "小时线一根 K 的振幅通常大于整个止损距离（S=0.08 ATR ≈ 6 SPX 点），"
                    "所以这条臂的盘中歧义率极高，命中率几乎全部由判定策略决定 —— "
                    "它只用来看样本量放大 10 倍后【位 vs 安慰剂】的差是否仍然是零。",
                    hourly, lmap, COST_SPX_POINTS)
    arm1h.curve = touch_curve(hourly, lmap)
    report(arm1h, out)
    p("")
    p("  【真实数据里的 K 线振幅 / 止损距离】—— 用来读【校准】(B) 表")
    for sa, (med, avg) in measure_bar_to_stop(hourly, lmap).items():
        p(f"    小时 K，S={sa} ATR：中位数 {med:.2f}，均值 {avg:.2f}")

    validate(out)

    p("")
    p("=" * 132)
    p(f"本次一共检视 {CELL_COUNT} 个格子（两条臂合计，含磁铁检验、逐位主表、"
      f"接近方向拆分、分期稳定性）。全部报告，无一挑选。")
    p("=" * 132)


if __name__ == "__main__":
    main()
