#!/usr/bin/env python3
"""Adversarial audit of the Saty-method weekend research.

Default stance: every "finding" is noise until it survives an attack that was
designed to kill it.  Nothing in this file re-uses the study scripts' own
helpers except the shared data/level layer, so a bug in a study cannot hide
inside this audit.

Run:  .venv/bin/python research/satylab/audit_adversarial.py
"""

from __future__ import annotations

import math
import random
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, __file__.rsplit("/satylab/", 1)[0])

from satylab import data, levels, stats  # noqa: E402

SEED = 20260725
LINE = "=" * 78


def hdr(t: str) -> None:
    print(f"\n{LINE}\n{t}\n{LINE}")


def z_vs_half(k: int, n: int) -> float:
    if n == 0:
        return 0.0
    return (k / n - 0.5) / math.sqrt(0.25 / n)


def mcnemar_z(b: int, c: int) -> float:
    """b = only-A, c = only-B.  z>0 means A more common."""
    if b + c == 0:
        return 0.0
    return (b - c) / math.sqrt(b + c)


# --------------------------------------------------------------------------
# A1.  The single directional path finding of the weekend, re-tested with the
#      trigger bar excluded from the outcome window.
# --------------------------------------------------------------------------
def a1_gg_symmetry() -> None:
    hdr("A1  GG 对称性检验：触发根是否被算进了结果窗口（study_time.py:414-416）")
    d = data.daily(years="20y")
    lv = levels.build(d)
    h = data.hourly()
    sess = data.group_by_day(h)
    BACK = levels.GG_ENTRY - (levels.GG_COMPLETE - levels.GG_ENTRY)  # 0.146

    def run(start_offset: int, only_intraday: bool):
        tot = {"n": 0, "up": 0, "dn": 0, "b": 0, "c": 0,
               "trigbar_dn": 0, "trigbar_up": 0}
        for day, rows in sess.items():
            L = lv.get(day)
            if L is None or len(rows) != 7:
                continue
            for side in (+1, -1):
                trig = L.at(side * levels.GG_ENTRY)
                gate = L.at(side * levels.GG_COMPLETE)
                back = L.at(side * BACK)
                gapped = (rows[0].open >= trig) if side > 0 else \
                         (rows[0].open <= trig)
                ti = None
                for i, b in enumerate(rows):
                    if (b.high >= trig) if side > 0 else (b.low <= trig):
                        ti = i
                        break
                if ti is None:
                    continue
                if only_intraday and (gapped and ti == 0):
                    continue
                tb = rows[ti]
                tb_dn = (tb.low <= back) if side > 0 else (tb.high >= back)
                tb_up = (tb.high >= gate) if side > 0 else (tb.low <= gate)
                s = ti + start_offset
                up = any((b.high >= gate) if side > 0 else (b.low <= gate)
                         for b in rows[s:])
                dn = any((b.low <= back) if side > 0 else (b.high >= back)
                         for b in rows[s:])
                tot["n"] += 1
                tot["up"] += up
                tot["dn"] += dn
                tot["b"] += up and not dn
                tot["c"] += dn and not up
                tot["trigbar_dn"] += tb_dn
                tot["trigbar_up"] += tb_up
        return tot

    for label, off in (("含触发根 (report 口径)", 0), ("剔除触发根", 1)):
        for scope, intra in (("全部触发", False), ("仅盘中触发", True)):
            t = run(off, intra)
            if t["n"] == 0:
                continue
            zz = mcnemar_z(t["b"], t["c"])
            print(f"  {label:<22}{scope:<10} n={t['n']:<5} "
                  f"到0.618={100*t['up']/t['n']:5.1f}%  "
                  f"退0.146={100*t['dn']/t['n']:5.1f}%  "
                  f"只上={t['b']:<4} 只下={t['c']:<4} McNemar z={zz:+.2f}")
    t = run(0, True)
    print(f"\n  机制：仅盘中触发的 {t['n']} 个触发根里，触发根自身的 low 就已经"
          f"跌破 0.146 的有 {t['trigbar_dn']} 个 "
          f"({100*t['trigbar_dn']/t['n']:.1f}%)，")
    print(f"  而触发根自身的 high 就已经到 0.618 的有 {t['trigbar_up']} 个 "
          f"({100*t['trigbar_up']/t['n']:.1f}%)。")
    print("  触发根的下影线按构造发生在触发【之前】（价格是从下面上来的），"
          "把它算成『退回』就是把触发前的路径记成触发后的结果。")


# --------------------------------------------------------------------------
# A2.  C1 rebuilt from scratch on 5m, then sliced in time and re-tested with
#      the same "exclude the entry bar" hygiene.
# --------------------------------------------------------------------------
def _fine_sessions():
    f = data.fine()
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(f)
    return {k: v for k, v in sorted(sess.items()) if k in lv}, lv


def a2_c1_rebuild() -> None:
    hdr("A2  C1 (GG FADE) 从零重建 + 时间切片 + 单点依赖")
    sess, lv = _fine_sessions()
    trades = []            # (day, side, R, exit_kind, entry_bar_idx)
    for day, rows in sess.items():
        L = lv[day]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            stop = L.at(side * levels.GG_COMPLETE)
            targ = L.at(side * levels.TRIGGER)
            # exclude gap-through and 09:30-bar triggers (pre-registered)
            first_bar = rows[0]
            if (first_bar.high >= trig) if side > 0 else (first_bar.low <= trig):
                continue
            ti = None
            for i, b in enumerate(rows):
                if (b.high >= trig) if side > 0 else (b.low <= trig):
                    ti = i
                    break
            if ti is None:
                continue
            if rows[ti].dt.hour * 60 + rows[ti].dt.minute >= 14 * 60 + 30:
                continue
            risk = abs(stop - trig)
            reward = abs(trig - targ)
            r_mult = reward / risk
            out = None
            for b in rows[ti:]:
                hit_stop = (b.high >= stop) if side > 0 else (b.low <= stop)
                hit_targ = (b.low <= targ) if side > 0 else (b.high >= targ)
                if hit_stop and hit_targ:
                    out = (-1.0, "ambig->stop")
                    break
                if hit_stop:
                    out = (-1.0, "stop")
                    break
                if hit_targ:
                    out = (+r_mult, "target")
                    break
            if out is None:
                last = rows[-1].close
                pnl = (trig - last) * side / risk
                out = (pnl, "close")
            trades.append((day, side, out[0], out[1], ti))
    rs = [t[2] for t in trades]
    e = stats.expectancy(rs)
    print(f"  重建结果 (口径同 study_trades): {stats.fmt_expectancy(e)}")
    print(f"  出场归因: " + "  ".join(
        f"{k}={sum(1 for t in trades if t[3] == k)}"
        for k in sorted({t[3] for t in trades})))

    # --- entry-bar hygiene: forbid the entry bar from resolving the target
    rs2 = []
    for day, side, r, kind, ti in trades:
        rows = sess[day]
        L = lv[day]
        trig = L.at(side * levels.GG_ENTRY)
        stop = L.at(side * levels.GG_COMPLETE)
        targ = L.at(side * levels.TRIGGER)
        risk = abs(stop - trig)
        rr = reward = abs(trig - targ) / risk
        out = None
        for b in rows[ti + 1:]:
            hs = (b.high >= stop) if side > 0 else (b.low <= stop)
            ht = (b.low <= targ) if side > 0 else (b.high >= targ)
            if hs:
                out = -1.0
                break
            if ht:
                out = rr
                break
        if out is None:
            out = (trig - rows[-1].close) * side / risk
        rs2.append(out)
    print(f"  剔除入场根判目标后:              {stats.fmt_expectancy(stats.expectancy(rs2))}")

    # --- time slices: three consecutive thirds of the 59-day window
    days = sorted({t[0] for t in trades})
    all_days = sorted(sess)
    third = len(all_days) // 3
    cuts = [all_days[0], all_days[third], all_days[2 * third], all_days[-1]]
    print(f"\n  三段时间切片（按交易日均分 {len(all_days)} 天）：")
    for i in range(3):
        lo, hi = cuts[i], (cuts[i + 1] if i < 2 else date(2100, 1, 1))
        seg = [t for t in trades if lo <= t[0] < hi] if i < 2 else \
              [t for t in trades if t[0] >= lo]
        if not seg:
            continue
        se = stats.expectancy([t[2] for t in seg])
        print(f"    段{i+1} {lo}→{max(t[0] for t in seg)}  "
              f"n={se['n']:<3} 均R={se['avg_r']:+.3f} "
              f"胜率={100*se['win_rate']:.1f}%")

    # --- drop-the-best-day / drop-the-best-trade
    by_day = defaultdict(list)
    for t in trades:
        by_day[t[0]].append(t[2])
    best_day = max(by_day, key=lambda k: sum(by_day[k]))
    kept = [r for k, v in by_day.items() if k != best_day for r in v]
    print(f"\n  剔除最好的 1 个交易日 ({best_day}, 贡献 {sum(by_day[best_day]):+.2f}R): "
          f"均R={sum(kept)/len(kept):+.3f} (n={len(kept)})")
    srt = sorted(rs, reverse=True)
    print(f"  剔除最好的 1 笔 ({srt[0]:+.2f}R): "
          f"均R={sum(srt[1:])/len(srt[1:]):+.3f} (n={len(srt)-1})")
    print(f"  剔除最好的 3 笔: 均R={sum(srt[3:])/len(srt[3:]):+.3f}")
    print(f"  剔除最差的 1 笔 ({srt[-1]:+.2f}R): "
          f"均R={sum(srt[:-1])/len(srt[:-1]):+.3f}")

    # --- what if the 0.62 R:R were paid honestly with 1 tick of slippage
    print("\n  注意 R:R 固定 = 0.62，所以打平需 62.2%；胜率的 Wilson 下界 "
          f"= {100*stats.wilson(e['n']-int(e['n']*(1-e['win_rate'])), e['n'])[0]:.1f}%")
    k = sum(1 for r in rs if r > 0)
    lo, hi = stats.wilson(k, len(rs))
    print(f"  胜率 {100*k/len(rs):.1f}% Wilson95 = [{100*lo:.1f}, {100*hi:.1f}] "
          f"—— 打平线 62.2% 落在区间内 ⇒ 无法拒绝『恰好打平』")


# --------------------------------------------------------------------------
# A3.  Out-of-sample for the C1 *edge claim* using the hourly 730d window,
#      with entry-bar hygiene, split into three periods.
# --------------------------------------------------------------------------
def a3_c1_hourly_oos() -> None:
    hdr("A3  C1 的方向主张在 730 天小时线上的三段稳定性（上下界）")
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    rows_by_seg: dict[int, list[tuple[int, int]]] = defaultdict(list)
    days = sorted(k for k in sess if k in lv and len(sess[k]) == 7)
    third = len(days) // 3
    seg_of = {dd: min(2, i // third) for i, dd in enumerate(days)}
    for day in days:
        rows, L = sess[day], lv[day]
        for side in (+1, -1):
            trig = L.at(side * levels.GG_ENTRY)
            stop = L.at(side * levels.GG_COMPLETE)
            targ = L.at(side * levels.TRIGGER)
            if (rows[0].open >= trig) if side > 0 else (rows[0].open <= trig):
                continue
            ti = None
            for i, b in enumerate(rows):
                if (b.high >= trig) if side > 0 else (b.low <= trig):
                    ti = i
                    break
            if ti is None or ti == 0:
                continue
            res_opt = res_pes = None
            for b in rows[ti + 1:]:
                hs = (b.high >= stop) if side > 0 else (b.low <= stop)
                ht = (b.low <= targ) if side > 0 else (b.high >= targ)
                if hs and ht:
                    res_pes = res_pes if res_pes is not None else 0
                    res_opt = res_opt if res_opt is not None else 1
                    break
                if hs:
                    res_pes = res_opt = 0
                    break
                if ht:
                    res_pes = res_opt = 1
                    break
            if res_pes is None:
                continue      # closed out, not a decided race
            rows_by_seg[seg_of[day]].append((res_pes, res_opt))
    allp = [x for v in rows_by_seg.values() for x in v]
    print("  『目标 0.236 先到』的比例（入场根不参与判定，未分胜负剔除）")
    print(f"  打平线 = 62.2%")
    for seg in sorted(rows_by_seg) + ["ALL"]:
        v = allp if seg == "ALL" else rows_by_seg[seg]
        n = len(v)
        kp = sum(a for a, _ in v)
        ko = sum(b for _, b in v)
        lab = "全样本" if seg == "ALL" else f"段{seg+1}"
        print(f"    {lab:<6} n={n:<5} 悲观={100*kp/n:5.1f}% "
              f"{stats.fmt_rate(kp, n)}   乐观={100*ko/n:5.1f}%")


# --------------------------------------------------------------------------
# A4.  Family-wide extreme-value arithmetic.
# --------------------------------------------------------------------------
def a4_family() -> None:
    hdr("A4  全周末家族规模与极值 z 的期望")
    fam = {
        "BASERATE_LEVEL_TRANSITIONS": 447,
        "BASERATE_OPENING_TYPE": 409,
        "BASERATE_RIBBON": 306,
        "BASERATE_PHASE": 283,
        "BASERATE_TIME_STRUCTURE": 385,
        "TRADE_CONSTRUCTIONS": 74,
        "GEOMETRY_MFE_MAE": 3788,
        "PROBABILITY_PANEL_SPEC": 651,
    }
    tot = sum(fam.values())
    for k, v in fam.items():
        print(f"    {k:<32}{v:>6}")
    print(f"    {'合计':<32}{tot:>6}")
    for m, lab in ((tot, "全周末"), (tot - 3788 - 651, "只算基准率+构造"),
                   (447, "单份最大的基准率报告")):
        e_max = math.sqrt(2 * math.log(2 * m))
        bonf = _z_for_two_sided_p(0.05 / m)
        print(f"  {lab}: m={m}  独立假设下 E[max|z|] ≈ {e_max:.2f}   "
              f"Bonferroni 5% 门槛 |z| ≥ {bonf:.2f}")
    print("\n  说明：格子高度相关（同一批日子、嵌套结果），所以独立假设下的"
          "E[max|z|] 偏高、Bonferroni 偏保守；两者都只是量级参照。")


def _z_for_two_sided_p(p: float) -> float:
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 2 * (1 - _norm_cdf(mid)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# --------------------------------------------------------------------------
# A5.  Data-defect sweep on the cached feeds.
# --------------------------------------------------------------------------
def a5_data_defects() -> None:
    hdr("A5  数据缺陷逐项体检")
    d = data.daily(years="20y")
    print(f"  日线 ^GSPC: n={len(d)}  {d[0].day} → {d[-1].day}")
    # (a) open == prev close exactly / near-exactly
    by_year = defaultdict(lambda: [0, 0, 0])
    lv = levels.build(d)
    for i in range(1, len(d)):
        y = d[i].day.year
        pc = d[i - 1].close
        by_year[y][1] += 1
        if abs(d[i].open - pc) < 1e-9:
            by_year[y][0] += 1
        L = lv.get(d[i].day)
        if L and abs(d[i].open - pc) < 0.01 * L.atr:
            by_year[y][2] += 1
    print("  (a) open ≈ prev_close 的比例（开盘价失真指纹）")
    print("      年份  精确相等   |开盘-前收|<0.01ATR   n")
    for y in sorted(by_year):
        ex, n, near = by_year[y]
        print(f"      {y}   {ex:>4} ({100*ex/n:4.1f}%)   "
              f"{near:>4} ({100*near/n:5.1f}%)          {n}")
    # (b) hourly session shapes
    sess = data.group_by_day(data.hourly())
    shapes = defaultdict(int)
    for day, rows in sess.items():
        shapes[(len(rows), rows[0].hhmm, rows[-1].hhmm)] += 1
    print("\n  (b) 小时线的『会话形状』分布 (根数, 首根, 末根)")
    for k, v in sorted(shapes.items(), key=lambda x: -x[1]):
        print(f"      {k}  ×{v}")
    odd = [dd for dd, r in sess.items() if len(r) != 7]
    print(f"      非 7 根的交易日 {len(odd)} 个: "
          f"{', '.join(str(x) for x in sorted(odd)[:12])}")
    # (c) hourly vs daily high/low agreement
    diffs_h, diffs_l, nboth = [], [], 0
    for day, rows in sess.items():
        L = lv.get(day)
        db = next((b for b in d if b.day == day), None)
        if L is None or db is None or len(rows) != 7:
            continue
        nboth += 1
        hh = max(b.high for b in rows)
        ll = min(b.low for b in rows)
        diffs_h.append(abs(hh - db.high) / L.atr)
        diffs_l.append(abs(ll - db.low) / L.atr)
    diffs_h.sort()
    diffs_l.sort()
    print(f"\n  (c) 重叠 {nboth} 天，小时线合成 high/low vs 日线 high/low")
    print(f"      |Δhigh|/ATR: 中位 {diffs_h[len(diffs_h)//2]:.4f}  "
          f"95分位 {diffs_h[int(0.95*len(diffs_h))]:.4f}  "
          f"max {diffs_h[-1]:.4f}  >0.05ATR 的天数 "
          f"{sum(1 for x in diffs_h if x > 0.05)}")
    print(f"      |Δlow| /ATR: 中位 {diffs_l[len(diffs_l)//2]:.4f}  "
          f"95分位 {diffs_l[int(0.95*len(diffs_l))]:.4f}  "
          f"max {diffs_l[-1]:.4f}  >0.05ATR 的天数 "
          f"{sum(1 for x in diffs_l if x > 0.05)}")
    # (d) volume
    zerov = sum(1 for b in d if b.volume == 0)
    print(f"\n  (d) 日线 volume==0 的根数 = {zerov}（指数无真实成交量，"
          f"任何量能条件都不可做）")
    # (e) 5m coverage
    f = data.fine()
    fs = data.group_by_day(f)
    cnt = defaultdict(int)
    for day, rows in fs.items():
        cnt[len(rows)] += 1
    print(f"  (e) 5m: {len(fs)} 个交易日 {min(fs)} → {max(fs)}；"
          f"每日根数分布 {dict(sorted(cnt.items()))}")
    short = sorted(dd for dd, r in fs.items() if len(r) < 78)
    print(f"      不足 78 根的日子: {short}")
    # (f) daily bars whose OHLC violates high>=max(o,c)
    bad = [b.day for b in d if b.high < max(b.open, b.close) - 1e-6
           or b.low > min(b.open, b.close) + 1e-6]
    print(f"  (f) OHLC 自洽性违例的日线根数 = {len(bad)}"
          + (f"  例: {bad[:5]}" if bad else ""))


# --------------------------------------------------------------------------
# A6.  Golden Gate: what does the 90% actually contain?
# --------------------------------------------------------------------------
def a6_gg_audit() -> None:
    hdr("A6  Golden Gate 复现的信息含量审查")
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    # (a) reproduce, then decompose the OPEN bucket
    buckets = defaultdict(lambda: [0, 0])
    open_already_past = 0
    open_total = 0
    for day in sorted(sess):
        L = lv.get(day)
        rows = sess[day]
        if L is None or len(rows) != 7:
            continue
        for side in (+1,):
            trig, gate = L.at(side * 0.382), L.at(side * 0.618)
            gapped = rows[0].open >= trig
            ti = None
            for i, b in enumerate(rows):
                if b.high >= trig:
                    ti = i
                    break
            if ti is None:
                continue
            key = "OPEN(gap)" if (gapped and ti == 0) else rows[ti].hhmm
            done = any(b.high >= gate for b in rows[ti:])
            buckets[key][0] += done
            buckets[key][1] += 1
            if key == "OPEN(gap)":
                open_total += 1
                if rows[0].open >= gate:
                    open_already_past += 1
    print("  (a) 多头 GG 完成率（本审查独立实现）")
    for k in ["OPEN(gap)", "09:30", "10:30", "11:30", "12:30", "13:30",
              "14:30", "15:30"]:
        if k in buckets:
            kk, nn = buckets[k]
            print(f"      {k:<10}{stats.fmt_rate(kk, nn)}")
    print(f"  (b) OPEN 档 {open_total} 次里，开盘价【本身已在 0.618 之外】"
          f"的有 {open_already_past} 次 "
          f"({100*open_already_past/open_total:.1f}%) —— "
          f"这些是既成事实，不是行情")
    # (c) same-distance placebo: from 0.382, reach 0.618 vs reach 0.146,
    #     and the pure "did the day move 0.618 at all" baseline
    n_day = comp = 0
    for day in sorted(sess):
        L = lv.get(day)
        rows = sess[day]
        if L is None or len(rows) != 7:
            continue
        n_day += 1
        comp += any(b.high >= L.at(0.618) for b in rows)
    print(f"  (c) 无条件（不要求触发）P(当日触及 +0.618) = "
          f"{stats.fmt_rate(comp, n_day)}")
    print("      GG 的 66% 是【条件于已经走了 0.382】，两者不能直接比，"
          "但它说明分母被选择过。")
    # (d) reference-table alignment
    print("\n  (d) 参考表的时段标签是 09:00/10:00/…/15:00（7 行 + 开盘档），")
    print("      我们的小时线标签是 09:30/10:30/…/15:30（7 根 + 开盘档）。")
    print("      行数一致所以被逐行对齐，但 09:00–10:00 与 09:30–10:30 "
          "不是同一个窗口。")
    # (e) how close is 'too close'
    for ours, ref, n in ((0.897, 0.9086, 117), (0.708, 0.7022, 168),
                         (0.951, 0.9106, 81), (0.695, 0.6967, 118)):
        se = math.sqrt(ours * (1 - ours) / n)
        print(f"      ours={100*ours:.1f}% ref={100*ref:.2f}% n={n:<4} "
              f"SE={100*se:.2f}pp  差={100*abs(ours-ref)/ (100*se):.2f} SE")


# --------------------------------------------------------------------------
# A7.  Three-way time stability for the headline 730d hourly claims.
# --------------------------------------------------------------------------
def a7_time_slices() -> None:
    hdr("A7  730 天窗口三等分后，各头条结论是否同号")
    d = data.daily(years="20y")
    lv = levels.build(d)
    sess = data.group_by_day(data.hourly())
    days = sorted(k for k in sess if k in lv and len(sess[k]) == 7)
    third = len(days) // 3
    seg_of = {dd: min(2, i // third) for i, dd in enumerate(days)}
    bounds = [(days[0], days[third - 1]), (days[third], days[2 * third - 1]),
              (days[2 * third], days[-1])]
    print("  段界: " + "  ".join(f"段{i+1} {a}→{b}"
                                 for i, (a, b) in enumerate(bounds)))

    # (1) time decay of "0.236 ATR still available", best-side
    avail = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    # (2) GG completion by bucket
    ggc = defaultdict(lambda: [0, 0])
    # (3) first-hour veto
    veto = defaultdict(lambda: [0, 0])
    for day in days:
        rows, L = sess[day], lv[day]
        s = seg_of[day]
        for i, b in enumerate(rows):
            ref = b.close
            up = any(x.high >= ref + 0.236 * L.atr for x in rows[i + 1:])
            dn = any(x.low <= ref - 0.236 * L.atr for x in rows[i + 1:])
            c = avail[b.hhmm][s]
            c[0] += int(up or dn)
            c[1] += 1
        # GG bull, intraday trigger only
        trig, gate = L.at(0.382), L.at(0.618)
        if not rows[0].open >= trig:
            ti = next((i for i, b in enumerate(rows) if b.high >= trig), None)
            if ti is not None:
                ggc[s][0] += any(b.high >= gate for b in rows[ti:])
                ggc[s][1] += 1
        # first-hour veto: |ratio| never beyond 0.236 in bar 0
        r_hi = L.ratio_of(rows[0].high)
        r_lo = L.ratio_of(rows[0].low)
        quiet = max(r_hi, -r_lo) < 0.236
        if quiet:
            hit = any(b.high >= L.at(1.0) or b.low <= L.at(-1.0)
                      for b in rows[1:])
            veto[s][0] += hit
            veto[s][1] += 1
    print("\n  (1) P(此刻之后还能再走 0.236 ATR，任一方向) — 三段")
    for hh in ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]:
        cells = [avail[hh][s] for s in range(3)]
        print(f"      {hh}  " + "   ".join(
            f"段{s+1} {100*c[0]/c[1]:5.1f}% (n={c[1]})"
            for s, c in enumerate(cells)))
    print("\n  (2) 盘中触发的多头 GG 完成率 — 三段")
    for s in range(3):
        k, n = ggc[s]
        print(f"      段{s+1} {stats.fmt_rate(k, n)}")
    print("\n  (3) 首小时未越 0.236 → 当日之后触及 ±1 ATR — 三段")
    for s in range(3):
        k, n = veto[s]
        print(f"      段{s+1} {stats.fmt_rate(k, n)}")


# --------------------------------------------------------------------------
# A8.  20y daily claims: five-year blocks for the tail asymmetry.
# --------------------------------------------------------------------------
def a8_tail_blocks() -> None:
    hdr("A8  20 年日线尾部转移的分块稳定性 + 单点依赖")
    d = data.daily(years="20y")
    lv = levels.build(d)
    rows = [(b.day, lv[b.day], b) for b in d if b.day in lv]
    blocks = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for day, L, b in rows:
        blk = (day.year - 2006) // 5
        for side, name in ((+1, "多"), (-1, "空")):
            for frm, to in ((0.382, 0.618), (0.618, 0.786), (0.786, 1.0),
                            (1.0, 1.272), (1.272, 1.618)):
                pf = L.at(side * frm)
                pt = L.at(side * to)
                got_f = (b.high >= pf) if side > 0 else (b.low <= pf)
                if not got_f:
                    continue
                got_t = (b.high >= pt) if side > 0 else (b.low <= pt)
                blocks[(name, frm, to)][blk][0] += got_t
                blocks[(name, frm, to)][blk][1] += 1
    print("  每格：五年块 1(2006-10) 2(2011-15) 3(2016-20) 4(2021-26)")
    for key in sorted(blocks, key=lambda k: (k[0], k[1])):
        name, frm, to = key
        cells = blocks[key]
        tk = sum(c[0] for c in cells.values())
        tn = sum(c[1] for c in cells.values())
        line = f"    {name} {frm:.3f}→{to:.3f}  合计 {100*tk/tn:5.1f}% (n={tn:4})  "
        line += " ".join(f"{100*cells[b][0]/cells[b][1]:5.1f}%(n={cells[b][1]:3})"
                         if cells[b][1] else "   n/a   " for b in range(4))
        line += f"   z50={z_vs_half(tk, tn):+.2f}"
        print(line)


# --------------------------------------------------------------------------
# A9.  The +1 ATR bull/bear asymmetry: is it just the lagged-ATR ruler?
# --------------------------------------------------------------------------
def a9_atr_ruler() -> None:
    hdr("A9  多空尾部不对称 = 滞后 ATR 尺子？（直接检验）")
    d = data.daily(years="20y")
    lv = levels.build(d)
    up_r, dn_r = [], []
    for b in d:
        L = lv.get(b.day)
        if L is None:
            continue
        tr = max(b.high - b.low, abs(b.high - L.anchor),
                 abs(b.low - L.anchor))
        touched_up = b.high >= L.at(1.0)
        touched_dn = b.low <= L.at(-1.0)
        if touched_up:
            up_r.append(tr / L.atr)
        if touched_dn:
            dn_r.append(tr / L.atr)
    up_r.sort()
    dn_r.sort()
    print(f"  触及 +1ATR 的日子: n={len(up_r)} 当日真实波幅/滞后ATR 中位 "
          f"{up_r[len(up_r)//2]:.3f}")
    print(f"  触及 -1ATR 的日子: n={len(dn_r)} 当日真实波幅/滞后ATR 中位 "
          f"{dn_r[len(dn_r)//2]:.3f}")
    print("  ⇒ 触及 -1 ATR 的日子波动更大，所以『再多走 0.272 ATR』也更容易。"
          "这不是空头优势，是尺子过期。")
    # same-day realised-range normalisation
    cont_up = [0, 0]
    cont_dn = [0, 0]
    for b in d:
        L = lv.get(b.day)
        if L is None:
            continue
        rng = b.high - b.low
        if rng <= 0:
            continue
        if b.high >= L.at(1.0):
            cont_up[0] += b.high >= L.at(1.272)
            cont_up[1] += 1
        if b.low <= L.at(-1.0):
            cont_dn[0] += b.low <= L.at(-1.272)
            cont_dn[1] += 1
    print(f"  复核: 多 1.0→1.272 {stats.fmt_rate(*cont_up)}")
    print(f"        空 1.0→1.272 {stats.fmt_rate(*cont_dn)}")
    print(f"  两比例 z = {stats.two_proportion_z(cont_dn[0], cont_dn[1], cont_up[0], cont_up[1]):+.2f}")


def main() -> None:
    random.seed(SEED)
    print(f"ADVERSARIAL AUDIT  —  {datetime.now():%Y-%m-%d %H:%M}")
    a5_data_defects()
    a6_gg_audit()
    a1_gg_symmetry()
    a2_c1_rebuild()
    a3_c1_hourly_oos()
    a7_time_slices()
    a8_tail_blocks()
    a9_atr_ruler()
    a4_family()


if __name__ == "__main__":
    main()
