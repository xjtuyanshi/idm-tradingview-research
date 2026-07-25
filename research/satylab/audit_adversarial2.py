#!/usr/bin/env python3
"""Adversarial audit, part 2 — mechanism digs and cross-report consistency.

Run:  .venv/bin/python research/satylab/audit_adversarial2.py
"""

from __future__ import annotations

import math
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats  # noqa: E402

LINE = "=" * 78


def hdr(t: str) -> None:
    print(f"\n{LINE}\n{t}\n{LINE}")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def z_vs(k: int, n: int, p0: float) -> float:
    if n == 0:
        return 0.0
    return (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def hourly_days():
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    days = sorted(k for k in sess if k in lv and len(sess[k]) == 7)
    return days, sess, lv


# --------------------------------------------------------------------------
def b1_open_artifact() -> None:
    hdr("B1  S3c『退回 0.146』在 09:30 档是机械必然吗？")
    days, sess, lv = hourly_days()
    BACK = 0.146
    cnt = defaultdict(lambda: [0, 0, 0])   # bucket -> [n, open_already_past, dn]
    for day in days:
        rows, L = sess[day], lv[day]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            back = L.at(side * BACK)
            gapped = (rows[0].open >= trig) if side > 0 else \
                     (rows[0].open <= trig)
            ti = next((i for i, b in enumerate(rows)
                       if ((b.high >= trig) if side > 0 else (b.low <= trig))),
                      None)
            if ti is None:
                continue
            bucket = "OPEN(gap)" if (gapped and ti == 0) else rows[ti].hhmm
            # was the session's OPENING PRICE already on the far side of 0.146?
            open_past = (rows[0].open <= back) if side > 0 else \
                        (rows[0].open >= back)
            dn = any((b.low <= back) if side > 0 else (b.high >= back)
                     for b in rows[ti:])
            c = cnt[bucket]
            c[0] += 1
            c[1] += int(open_past)
            c[2] += int(dn)
    print("  『退回 0.146』被记为 True 的触发里，有多少其实是【开盘价本身就在"
          "0.146 之外】——")
    print("  也就是价格是从那里【上来】的，退回从未发生。")
    print(f"  {'档':<12}{'n':>5}{'开盘已在0.146之外':>20}{'记为退回':>12}"
          f"{'其中开盘即已成立':>18}")
    tot = [0, 0, 0]
    for k in ["OPEN(gap)", "09:30", "10:30", "11:30", "12:30", "13:30",
              "14:30", "15:30"]:
        if k not in cnt:
            continue
        n, op, dn = cnt[k]
        print(f"  {k:<12}{n:>5}{100*op/n:>19.1f}%{100*dn/n:>11.1f}%"
              f"{'':>10}")
        if k != "OPEN(gap)":
            tot[0] += n
            tot[1] += op
            tot[2] += dn
    print(f"  {'盘中合计':<12}{tot[0]:>5}{100*tot[1]/tot[0]:>19.1f}%"
          f"{100*tot[2]/tot[0]:>11.1f}%")
    print("\n  ⇒ 盘中触发的『退回 0.146 = 74.4%』里，"
          f"{100*tot[1]/tot[0]:.1f}pp 是开盘价就已经在 0.146 之外造成的，"
          "不是触发之后的行情。")


# --------------------------------------------------------------------------
def b2_clock_stability() -> None:
    hdr("B2  时钟表（S2 口径：该小时【开盘价】起算，含本根）三段稳定性")
    days, sess, lv = hourly_days()
    third = len(days) // 3
    seg = {dd: min(2, i // third) for i, dd in enumerate(days)}
    tbl = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for day in days:
        rows, L = sess[day], lv[day]
        s = seg[day]
        for i, b in enumerate(rows):
            ref = b.open
            hi = max(x.high for x in rows[i:])
            lo = min(x.low for x in rows[i:])
            best = max(hi - ref, ref - lo) / L.atr
            c = tbl[b.hhmm][s]
            c[0] += int(best >= 0.236)
            c[1] += 1
            c2 = tbl[b.hhmm]["all"]
            c2[0] += int(best >= 0.236)
            c2[1] += 1
    print("  P(最优边 >= 0.236 ATR)")
    print(f"  {'时刻':<8}{'全样本':>22}{'段1':>10}{'段2':>10}{'段3':>10}"
          f"{'  极差(pp)':>10}")
    for hh in ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]:
        a = tbl[hh]["all"]
        segs = [tbl[hh][s] for s in range(3)]
        vals = [100 * c[0] / c[1] for c in segs]
        print(f"  {hh:<8}{stats.fmt_rate(*a):>22}"
              + "".join(f"{v:>9.1f}%" for v in vals)
              + f"{max(vals)-min(vals):>10.1f}")


# --------------------------------------------------------------------------
def b3_c1_correct_null() -> None:
    hdr("B3  C1 的正确零假设：无漂移随机游走下的赢面 = 止损距离/(止损+目标)")
    stop_d = levels.GG_COMPLETE - levels.GG_ENTRY     # 0.236
    targ_d = levels.GG_ENTRY - levels.TRIGGER         # 0.146
    p0 = stop_d / (stop_d + targ_d)
    rr = targ_d / stop_d
    be = 1 / (1 + rr)
    print(f"  止损距离 = {stop_d:.3f} ATR，目标距离 = {targ_d:.3f} ATR")
    print(f"  无漂移随机游走 P(目标先到) = {stop_d:.3f}/{stop_d+targ_d:.3f} "
          f"= {100*p0:.1f}%")
    print(f"  R:R = {rr:.3f}，打平所需胜率 = 1/(1+R:R) = {100*be:.1f}%")
    print("  ⇒ 两者按定义相等（可选停时定理：无漂移过程上任何止损/目标组合期望 0）。")
    print(f"\n  报告用『vs 抛硬币 50%』检验赛跑比例。50% 不是这个构造的零假设，"
          f"{100*p0:.1f}% 才是。")
    for k, n, lab in ((20, 26, "5m 赛跑 (已分胜负)"), (21, 27, "5m 胜率 (全部)")):
        print(f"  {lab:<22} {k}/{n} = {100*k/n:.1f}%  "
              f"z vs 50% = {z_vs(k, n, 0.5):+.2f}   "
              f"z vs {100*p0:.1f}% = {z_vs(k, n, p0):+.2f}   "
              f"p(单尾) = {1-_norm_cdf(z_vs(k, n, p0)):.3f}")
    print("\n  同样地检验 C3（顺势：止损 0.382，目标 0.236）：")
    p0c = 0.382 / (0.382 + 0.236)
    print(f"    随机游走 P(目标先到) = {100*p0c:.1f}%；实测 63.6% (14/22) "
          f"z = {z_vs(14, 22, p0c):+.2f}")


# --------------------------------------------------------------------------
def b4_opening_claims() -> None:
    hdr("B4  开盘形态报告的两条主张独立复核 (SPY 20y 日线)")
    spy = data.daily("SPY", years="20y")
    lv = levels.build(spy)
    rows = [(b, lv[b.day]) for b in spy if b.day in lv]
    # (1) |gap| -> P(day range >= 1 ATR)
    buckets = [("<0.1", 0, 0.1), ("0.1-0.236", 0.1, 0.236),
               ("0.236-0.5", 0.236, 0.5), (">0.5", 0.5, 99)]
    tab = defaultdict(lambda: [0, 0])
    for b, L in rows:
        g = abs(L.ratio_of(b.open))
        rng = (b.high - b.low) / L.atr
        for name, lo, hi in buckets:
            if lo <= g < hi:
                tab[name][0] += int(rng >= 1.0)
                tab[name][1] += 1
    print("  (1) |跳空| -> P(当日振幅 >= 1 ATR)")
    for name, *_ in buckets:
        k, n = tab[name]
        print(f"      {name:<12}{stats.fmt_rate(k, n)}")
    # (2) within the big-gap bucket, open vs prior range
    sub = defaultdict(lambda: [0, 0])
    for b, L in rows:
        g = abs(L.ratio_of(b.open))
        if g <= 0.5:
            continue
        rng = (b.high - b.low) / L.atr
        if b.open < L.prev_low:
            key = "开在前日低之下"
        elif b.open > L.prev_high:
            key = "开在前日高之上"
        else:
            key = "在前日区间内"
        sub[key][0] += int(rng >= 1.0)
        sub[key][1] += 1
    print("  (2) |跳空|>0.5 内部，按开盘 vs 前日区间")
    for k in ["开在前日低之下", "在前日区间内", "开在前日高之上"]:
        kk, nn = sub[k]
        print(f"      {k:<16}{stats.fmt_rate(kk, nn)}")
    a, b_ = sub["开在前日低之下"], sub["开在前日高之上"]
    print(f"      两比例 z = "
          f"{stats.two_proportion_z(a[0], a[1], b_[0], b_[1]):+.2f}")
    # sub-period stability
    print("  (2b) 四个不重叠子期（低之下 vs 高之上）")
    for lo_y, hi_y in ((2006, 2011), (2011, 2016), (2016, 2021), (2021, 2027)):
        s2 = defaultdict(lambda: [0, 0])
        for b, L in rows:
            if not (lo_y <= b.day.year < hi_y):
                continue
            if abs(L.ratio_of(b.open)) <= 0.5:
                continue
            rng = (b.high - b.low) / L.atr
            if b.open < L.prev_low:
                s2["dn"][0] += int(rng >= 1.0); s2["dn"][1] += 1
            elif b.open > L.prev_high:
                s2["up"][0] += int(rng >= 1.0); s2["up"][1] += 1
        if s2["dn"][1] and s2["up"][1]:
            print(f"      {lo_y}-{hi_y-1}: 低之下 "
                  f"{100*s2['dn'][0]/s2['dn'][1]:5.1f}% (n={s2['dn'][1]:3})  "
                  f"高之上 {100*s2['up'][0]/s2['up'][1]:5.1f}% "
                  f"(n={s2['up'][1]:3})  z="
                  f"{stats.two_proportion_z(*s2['dn'], *s2['up']):+.2f}")
    # (3) gap direction does NOT predict direction — verify with McNemar
    print("  (3) 跳空>+0.5 时，上行/下行 >=0.382 的配对检验")
    b_only_up = b_only_dn = n_big = 0
    for b, L in rows:
        r = L.ratio_of(b.open)
        if r <= 0.5:
            continue
        n_big += 1
        up = (b.high - b.open) / L.atr >= 0.382
        dn = (b.open - b.low) / L.atr >= 0.382
        b_only_up += up and not dn
        b_only_dn += dn and not up
    zz = (b_only_up - b_only_dn) / math.sqrt(b_only_up + b_only_dn)
    print(f"      n={n_big}  只上={b_only_up} 只下={b_only_dn}  "
          f"McNemar z={zz:+.2f}")


# --------------------------------------------------------------------------
def b5_gspc_open_artifact() -> None:
    hdr("B5  ^GSPC 开盘价失真 — 独立复核（这是报告里最重要的一条数据结论）")
    g = {b.day: b for b in data.daily(years="20y")}
    s = {b.day: b for b in data.daily("SPY", years="20y")}
    gl = levels.build(data.daily(years="20y"))
    sl = levels.build(data.daily("SPY", years="20y"))
    common = sorted(set(g) & set(s) & set(gl) & set(sl))
    xs, ys = [], []
    for dd in common:
        if dd.year < 2017:
            continue
        xs.append(sl[dd].ratio_of(s[dd].open))
        ys.append(gl[dd].ratio_of(g[dd].open))
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    slope = sxy / sxx
    corr = sxy / math.sqrt(sxx * syy)
    print(f"  2017+ 共同交易日 n={n}")
    print(f"  回归 GSPC跳空(ATR) ~ SPY跳空(ATR): 斜率={slope:.3f} "
          f"corr={corr:.3f}")
    print(f"  ⇒ 斜率 <1 表示 ^GSPC 的开盘价被系统性压向前收（约压缩 "
          f"{100*(1-slope):.0f}%）")
    # McNemar on the same days: SPY-defined big up gaps
    only_g = only_s = nn = 0
    for dd in common:
        if dd.year < 2017:
            continue
        if sl[dd].ratio_of(s[dd].open) < 0.5:
            continue
        nn += 1
        gu = (g[dd].high - g[dd].open) / gl[dd].atr >= 0.382
        su = (s[dd].high - s[dd].open) / sl[dd].atr >= 0.382
        only_g += gu and not su
        only_s += su and not gu
    print(f"  SPY 定义的 gap>=+0.5 日 (2017+) n={nn}: "
          f"^GSPC 说上行>=0.382 而 SPY 说没有 = {only_g}，反之 = {only_s}，"
          f"McNemar z={(only_g-only_s)/math.sqrt(max(1,only_g+only_s)):+.2f}")


# --------------------------------------------------------------------------
def b6_bar_alignment() -> None:
    hdr("B6  小时/5m K 线对齐与假期体检")
    h = data.hourly()
    sess = data.group_by_day(h)
    weird = {dd: r for dd, r in sess.items() if len(r) != 7}
    for dd, r in sorted(weird.items()):
        print(f"  {dd}  {len(r)} 根: " + " ".join(b.hhmm for b in r))
    # DST: does the first bar ever shift?
    firsts = defaultdict(int)
    for dd, r in sess.items():
        firsts[r[0].hhmm] += 1
    print(f"  首根时间分布: {dict(firsts)}")
    f = data.group_by_day(data.fine())
    for dd, r in sorted(f.items()):
        if len(r) != 78:
            print(f"  5m {dd}: {len(r)} 根，首={r[0].hhmm} 末={r[-1].hhmm}")
    # is the daily bar's day-set the same as the hourly day-set?
    dset = {b.day for b in data.daily(years="20y")}
    hset = set(sess)
    print(f"  小时线有而日线无的交易日: {sorted(hset - dset)}")
    print(f"  5m 有而日线无的交易日: {sorted(set(f) - dset)}")


# --------------------------------------------------------------------------
def b7_phase_headline() -> None:
    hdr("B7  Phase 头条（唯一正面发现）独立复核 + 三段稳定性")
    days, sess, lv = hourly_days()
    bars = [b for dd in days for b in sess[dd]]
    # rebuild EMA21 / phase oscillator the same way indicators.py does
    from satylab import indicators
    st = indicators.phase_oscillator(bars)
    idx = {b.dt: i for i, b in enumerate(bars)}
    from satylab.indicators import ribbon
    rb = ribbon(bars)
    third = len(days) // 3
    seg = {dd: min(2, i // third) for i, dd in enumerate(days)}
    cells = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for dd in days:
        rows = sess[dd]
        L = lv[dd]
        b1030 = next((b for b in rows if b.hhmm == "10:30"), None)
        if b1030 is None:
            continue
        i = idx[b1030.dt]
        if rb[i] is None or rb[i].label() != "bull_trend":
            continue
        osc = st[i]
        if osc is None:
            continue
        rest = rows[rows.index(b1030) + 1:]
        if not rest:
            continue
        ref = b1030.close
        hi = max(b.high for b in rest)
        lo = min(b.low for b in rest)
        dead = max(hi - ref, ref - lo) / L.atr < 0.236
        if 61.8 <= osc < 100:
            key = "distribution"
        elif -61.8 < osc < 61.8:
            key = "launch_box"
        elif osc >= 100:
            key = "extended_up"
        else:
            key = "other"
        cells[key]["all"][0] += dead
        cells[key]["all"][1] += 1
        cells[key][seg[dd]][0] += dead
        cells[key][seg[dd]][1] += 1
    print("  ribbon=bull_trend 时，10:30 的 Phase 分区 -> P(当日剩余 <0.236 ATR)")
    for k in ["launch_box", "distribution", "extended_up", "other"]:
        if k not in cells:
            continue
        a = cells[k]["all"]
        segs = [cells[k][s] for s in range(3)]
        print(f"    {k:<14}{stats.fmt_rate(*a):<26}" + "  ".join(
            f"段{s+1} {100*c[0]/c[1]:5.1f}%(n={c[1]:3})" if c[1] else
            f"段{s+1}   n=0   " for s, c in enumerate(segs)))
    a, b_ = cells["distribution"]["all"], cells["launch_box"]["all"]
    print(f"    两比例 z (distribution vs launch_box) = "
          f"{stats.two_proportion_z(*a, *b_):+.2f}")


# --------------------------------------------------------------------------
def b8_c2_attack() -> None:
    hdr("B8  C2 (跳空穿透 GG 延续) 的构造缺陷")
    d = data.daily("SPY", years="20y")
    lv = levels.build(d)
    fs = data.group_by_day(data.fine("SPY"))
    trades = []
    for dd in sorted(fs):
        if dd not in lv:
            continue
        rows, L = fs[dd], lv[dd]
        o = rows[0].open
        r = L.ratio_of(o)
        for side in (+1, -1):
            if not (levels.GG_ENTRY <= side * r < levels.GG_COMPLETE):
                continue
            stop = L.at(side * levels.TRIGGER)
            targ = L.at(side * levels.GG_COMPLETE)
            risk = abs(o - stop)
            rew = abs(targ - o)
            rr = rew / risk
            res = None
            for b in rows:
                hs = (b.low <= stop) if side > 0 else (b.high >= stop)
                ht = (b.high >= targ) if side > 0 else (b.low <= targ)
                if hs and ht:
                    res = -1.0
                    break
                if hs:
                    res = -1.0
                    break
                if ht:
                    res = rr
                    break
            if res is None:
                res = (rows[-1].close - o) * side / risk
            trades.append((dd, side, res, rr))
    rs = [t[2] for t in trades]
    print(f"  重建: {stats.fmt_expectancy(stats.expectancy(rs))}")
    rrs = sorted(t[3] for t in trades)
    print(f"  逐笔 R:R = {[f'{x:.2f}' for x in rrs]}")
    print(f"  随机游走零假设下每笔期望 = 0；实测总R 全部来自 R:R 高的那几笔？")
    hi = [t[2] for t in trades if t[3] >= 0.6]
    lo = [t[2] for t in trades if t[3] < 0.6]
    print(f"    R:R>=0.6 的笔: n={len(hi)} 均R={sum(hi)/len(hi):+.3f}")
    print(f"    R:R <0.6 的笔: n={len(lo)} 均R={sum(lo)/len(lo):+.3f}")
    print("  排除最好的一笔后: "
          f"均R={sum(sorted(rs)[:-1])/(len(rs)-1):+.3f}")
    print("  排除最好的两笔后: "
          f"均R={sum(sorted(rs)[:-2])/(len(rs)-2):+.3f}")
    # out-of-sample on SPY 730d hourly
    hs = data.group_by_day(data.hourly("SPY"))
    hd = sorted(k for k in hs if k in lv and len(hs[k]) == 7)
    third = len(hd) // 3
    seg = {dd: min(2, i // third) for i, dd in enumerate(hd)}
    out = defaultdict(list)
    for dd in hd:
        rows, L = hs[dd], lv[dd]
        o = rows[0].open
        r = L.ratio_of(o)
        for side in (+1, -1):
            if not (levels.GG_ENTRY <= side * r < levels.GG_COMPLETE):
                continue
            stop = L.at(side * levels.TRIGGER)
            targ = L.at(side * levels.GG_COMPLETE)
            rr = abs(targ - o) / abs(o - stop)
            pes = opt = None
            for b in rows:
                hs_ = (b.low <= stop) if side > 0 else (b.high >= stop)
                ht = (b.high >= targ) if side > 0 else (b.low <= targ)
                if hs_ and ht:
                    pes, opt = -1.0, rr
                    break
                if hs_:
                    pes = opt = -1.0
                    break
                if ht:
                    pes = opt = rr
                    break
            if pes is None:
                v = (rows[-1].close - o) * side / abs(o - stop)
                pes = opt = v
            out[seg[dd]].append((pes, opt))
    allv = [x for v in out.values() for x in v]
    print(f"\n  样本外 SPY 730天小时线 (同构造, 上下界):")
    for s in sorted(out) + ["ALL"]:
        v = allv if s == "ALL" else out[s]
        lab = "全样本" if s == "ALL" else f"段{s+1}"
        print(f"    {lab:<6} n={len(v):<4} 悲观均R="
              f"{sum(a for a, _ in v)/len(v):+.3f}  乐观均R="
              f"{sum(b for _, b in v)/len(v):+.3f}")



# --------------------------------------------------------------------------
def b9_gap_sign_confound() -> None:
    hdr("B9  『开盘位置』是不是只是『跳空符号』换名？（杠杆效应混淆）")
    spy = data.daily("SPY", years="20y")
    lv = levels.build(spy)
    rows = [(b, lv[b.day]) for b in spy if b.day in lv]
    def cell(pred):
        k = n = 0
        for b, L in rows:
            if not pred(b, L):
                continue
            n += 1
            k += int((b.high - b.low) / L.atr >= 1.0)
        return k, n
    up = cell(lambda b, L: L.ratio_of(b.open) > 0.5)
    dn = cell(lambda b, L: L.ratio_of(b.open) < -0.5)
    print(f"  跳空 > +0.5 (不看前日区间): {stats.fmt_rate(*up)}")
    print(f"  跳空 < -0.5 (不看前日区间): {stats.fmt_rate(*dn)}")
    print(f"  两比例 z = {stats.two_proportion_z(*dn, *up):+.2f}")
    print("  报告的『开在前日低之下 57.4% vs 高之上 32.1%, z=+7.18』")
    print("  与上面这条『下跳 vs 上跳』几乎是同一个数 —— 在 |跳空|>0.5 里，")
    print("  『开在前日低之下』基本等价于『向下跳空』。")
    both = {"dn_below": [0, 0], "dn_inside": [0, 0],
            "up_above": [0, 0], "up_inside": [0, 0]}
    for b, L in rows:
        r = L.ratio_of(b.open)
        if abs(r) <= 0.5:
            continue
        big = (b.high - b.low) / L.atr >= 1.0
        if r < 0:
            key = "dn_below" if b.open < L.prev_low else "dn_inside"
        else:
            key = "up_above" if b.open > L.prev_high else "up_inside"
        both[key][0] += big
        both[key][1] += 1
    print("\n  在【固定跳空符号】之后，前日区间位置还剩多少增量？")
    for k in ["dn_below", "dn_inside", "up_above", "up_inside"]:
        print(f"    {k:<12}{stats.fmt_rate(*both[k])}")
    print(f"    下跳: 破前低 vs 未破  z = "
          f"{stats.two_proportion_z(*both['dn_below'], *both['dn_inside']):+.2f}")
    print(f"    上跳: 破前高 vs 未破  z = "
          f"{stats.two_proportion_z(*both['up_above'], *both['up_inside']):+.2f}")


# --------------------------------------------------------------------------
def b10_trigger_bar_only() -> None:
    hdr("B10  『退回 0.146』有多少是【只靠触发根本身】成立的")
    days, sess, lv = hourly_days()
    BACK = 0.146
    only_trigbar = dn_any = n = 0
    up_only_trigbar = up_any = 0
    for day in days:
        rows, L = sess[day], lv[day]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            gate = L.at(side * levels.GG_COMPLETE)
            back = L.at(side * BACK)
            gapped = (rows[0].open >= trig) if side > 0 else \
                     (rows[0].open <= trig)
            ti = next((i for i, b in enumerate(rows)
                       if ((b.high >= trig) if side > 0 else (b.low <= trig))),
                      None)
            if ti is None or (gapped and ti == 0):
                continue
            n += 1
            dn0 = any((b.low <= back) if side > 0 else (b.high >= back)
                      for b in rows[ti:])
            dn1 = any((b.low <= back) if side > 0 else (b.high >= back)
                      for b in rows[ti + 1:])
            up0 = any((b.high >= gate) if side > 0 else (b.low <= gate)
                      for b in rows[ti:])
            up1 = any((b.high >= gate) if side > 0 else (b.low <= gate)
                      for b in rows[ti + 1:])
            dn_any += dn0
            up_any += up0
            only_trigbar += dn0 and not dn1
            up_only_trigbar += up0 and not up1
    print(f"  盘中触发 n={n}")
    print(f"  记为『退回 0.146』= {dn_any} ({100*dn_any/n:.1f}%)，"
          f"其中【只有触发根成立】= {only_trigbar} "
          f"({100*only_trigbar/dn_any:.1f}% 的退回事件)")
    print(f"  记为『到 0.618』  = {up_any} ({100*up_any/n:.1f}%)，"
          f"其中【只有触发根成立】= {up_only_trigbar} "
          f"({100*up_only_trigbar/up_any:.1f}% 的完成事件)")
    print("  ⇒ 触发根对『退回』的贡献是对『完成』贡献的 "
          f"{ (only_trigbar/max(1,dn_any)) / (up_only_trigbar/max(1,up_any)):.1f} 倍。"
          "这就是 z=-4.62 的来源。")


# --------------------------------------------------------------------------
def b11_power() -> None:
    hdr("B11  C1 需要多少笔才能把 61.8% 的零假设推翻到 5% 水平")
    p0 = 0.236 / 0.382
    for p1 in (0.70, 0.75, 0.778, 0.80):
        # one-sided, alpha .05, power .8
        za, zb = 1.645, 0.842
        num = (za * math.sqrt(p0 * (1 - p0)) + zb * math.sqrt(p1 * (1 - p1))) ** 2
        n = num / (p1 - p0) ** 2
        print(f"    若真实胜率 = {100*p1:.1f}%  需要 n ≈ {math.ceil(n)} 笔"
              f"（当前 27 笔，约 {math.ceil(n)/27:.1f} 倍）")
    print("  按每 59 个交易日产生 27 笔的速度，"
          f"{math.ceil(((1.645*math.sqrt(p0*(1-p0))+0.842*math.sqrt(0.778*0.222))**2)/(0.778-p0)**2)}"
          " 笔需要约 "
          f"{math.ceil(((1.645*math.sqrt(p0*(1-p0))+0.842*math.sqrt(0.778*0.222))**2)/(0.778-p0)**2)/27*59/21:.1f}"
          " 个月的前向数据 —— 且这还没算 74 个配置的择优膨胀。")


# --------------------------------------------------------------------------
def b12_ribbon_null_recheck() -> None:
    hdr("B12  Ribbon『方向零结论』复核（否定结论也要能复现）")
    from satylab.indicators import ribbon
    days, sess, lv = hourly_days()
    bars = [b for dd in days for b in sess[dd]]
    rb = ribbon(bars)
    idx = {b.dt: i for i, b in enumerate(bars)}
    cells = defaultdict(lambda: [0, 0])
    base = [0, 0]
    for dd in days:
        rows, L = sess[dd], lv[dd]
        for j, b in enumerate(rows[:-1]):
            i = idx[b.dt]
            if rb[i] is None:
                continue
            ref = b.close
            up = any(x.high >= ref + 0.236 * L.atr for x in rows[j + 1:])
            dn = any(x.low <= ref - 0.236 * L.atr for x in rows[j + 1:])
            if up == dn:
                continue          # both or neither: no verdict
            lab = rb[i].label()
            cells[lab][0] += int(up)
            cells[lab][1] += 1
            base[0] += int(up)
            base[1] += 1
    print(f"  无条件基准 P(只摸到上方) = {stats.fmt_rate(*base)}")
    for k in sorted(cells):
        c = cells[k]
        print(f"    {k:<14}{stats.fmt_rate(*c)}  z vs 基准 = "
              f"{stats.two_proportion_z(c[0], c[1], base[0]-c[0], base[1]-c[1]):+.2f}")


def main() -> None:
    random.seed(20260725)
    print(f"ADVERSARIAL AUDIT part 2  —  {datetime.now():%Y-%m-%d %H:%M}")
    b3_c1_correct_null()
    b1_open_artifact()
    b2_clock_stability()
    b6_bar_alignment()
    b5_gspc_open_artifact()
    b4_opening_claims()
    b7_phase_headline()
    b8_c2_attack()
    b9_gap_sign_confound()
    b10_trigger_bar_only()
    b12_ribbon_null_recheck()
    b11_power()


if __name__ == "__main__":
    main()
