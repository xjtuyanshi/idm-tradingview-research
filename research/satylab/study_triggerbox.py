#!/usr/bin/env python3
"""Two claims Saty makes on video that nobody has ever measured.

Claim 1 — trigger-box traversal (SPX video, 20:12).  He says the box between
the put trigger and the call trigger tends to be traversed: put trigger ->
previous close -> call trigger, and the reverse.  He then says outright that
he does not know the statistics behind it.  That makes it the cleanest research
target found in four videos: one condition, one outcome, no conjunction, and a
large sample.

Note this is a DIFFERENT geometry from the placebo-ladder test that killed
round 1.  That test measured moving further AWAY from the anchor and found a
smooth function of distance.  This one measures crossing THROUGH the anchor,
which the ladder never touched.

Claim 2 — "ATR covered < 70%" (Setups/Entries/Exits video).  One of his three
non-negotiable entry conditions: do not enter once the day has already used up
70% of its ATR.  This is his version of the travel budget we measured
independently, so it is worth checking whether his threshold is where the data
puts it.

Both get a shifted-box placebo, because the round-1 lesson is that a named
level has to beat an unnamed one at the same geometry before it means anything.

Usage: python research/satylab/study_triggerbox.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satylab import data, levels, stats  # noqa: E402

TRIG = levels.TRIGGER          # 0.236


def traversal(sessions, lv, lo_r: float, hi_r: float, label: str) -> dict:
    """From first touch of one edge, does price reach the anchor, then the far edge?"""
    res = {
        "up_anchor": stats.RateCell(), "up_far": stats.RateCell(),
        "dn_anchor": stats.RateCell(), "dn_far": stats.RateCell(),
    }
    mid = (lo_r + hi_r) / 2.0
    for day, rows in sorted(sessions.items()):
        L = lv.get(day)
        if not L or len(rows) < 5:
            continue
        lo, hi, anchor = L.at(lo_r), L.at(hi_r), L.at(mid)

        i = levels.first_touch(rows, lo, -1)
        if i is not None:
            after = rows[i:]
            hit_anchor = any(b.high >= anchor for b in after)
            res["up_anchor"].add(hit_anchor)
            if hit_anchor:
                j = levels.first_touch(after, anchor, +1)
                res["up_far"].add(any(b.high >= hi for b in after[j:]))

        i = levels.first_touch(rows, hi, +1)
        if i is not None:
            after = rows[i:]
            hit_anchor = any(b.low <= anchor for b in after)
            res["dn_anchor"].add(hit_anchor)
            if hit_anchor:
                j = levels.first_touch(after, anchor, -1)
                res["dn_far"].add(any(b.low <= lo for b in after[j:]))
    return res


def show(label: str, r: dict) -> None:
    print(f"\n  {label}")
    print(f"    自下沿 → 锚      {r['up_anchor']}")
    print(f"    再 → 上沿(完整穿越) {r['up_far']}")
    print(f"    自上沿 → 锚      {r['dn_anchor']}")
    print(f"    再 → 下沿(完整穿越) {r['dn_far']}")


def main() -> None:
    daily = data.daily("^GSPC", years="20y")
    hourly = data.hourly("^GSPC")
    lv = levels.build(daily)
    sess = data.group_by_day(hourly)
    print(f"小时线 {len(sess)} 个交易日 ({min(sess)} → {max(sess)})")

    print("\n" + "=" * 72)
    print("主张一：trigger box 穿越（他说『我还不知道这个的统计』）")
    print("=" * 72)
    real = traversal(sess, lv, -TRIG, TRIG, "真 trigger box")
    show("真 trigger box (±0.236，锚=PDC)", real)

    print("\n  —— 安慰剂：同宽度的箱子，平移到非具名位置 ——")
    placebos = []
    for shift in (0.15, 0.30, -0.15, -0.30):
        p = traversal(sess, lv, -TRIG + shift, TRIG + shift, f"shift{shift}")
        placebos.append((shift, p))
        show(f"平移 {shift:+.2f} ATR（锚变成 {shift:+.2f}，非具名）", p)

    print("\n  —— 判决：真箱 vs 安慰剂平均 ——")
    for key in ("up_anchor", "up_far", "dn_anchor", "dn_far"):
        pk = sum(p[key].k for _, p in placebos)
        pn = sum(p[key].n for _, p in placebos)
        z = stats.two_proportion_z(real[key].k, real[key].n, pk, pn)
        mark = "**真箱更强**" if z >= 1.96 else ("**真箱更弱**" if z <= -1.96
                                                else "无差别")
        print(f"    {key:<11} 真 {100*real[key].rate:5.1f}% (n={real[key].n:<5})"
              f"  安慰剂 {100*pk/pn:5.1f}% (n={pn:<5})  z={z:+6.2f}  {mark}")

    print("\n" + "=" * 72)
    print("主张二：ATR 已走 < 70% 才可入场（他的三条硬性条件之一）")
    print("=" * 72)
    print("  口径：以每根小时 K 的开盘为决策点，当时『当日已走幅度/日ATR』分档，")
    print("        测此后当日是否还能再走 0.236 ATR（任一方向）")
    tbl = stats.RateTable("当日已走 ATR 占比 → 之后还能再走 0.236 ATR")
    for day, rows in sorted(sess.items()):
        L = lv.get(day)
        if not L or len(rows) < 5:
            continue
        for i in range(len(rows) - 1):
            hi = max(b.high for b in rows[:i + 1])
            lo = min(b.low for b in rows[:i + 1])
            covered = (hi - lo) / L.atr
            after = rows[i + 1:]
            px = rows[i].close
            moved = (max(b.high for b in after) - px >= 0.236 * L.atr or
                     px - min(b.low for b in after) >= 0.236 * L.atr)
            b = ("<30%" if covered < 0.30 else "30-50%" if covered < 0.50
                 else "50-70%" if covered < 0.70 else "70-100%" if covered < 1.0
                 else ">100%")
            tbl.add(b, moved)
    print()
    print(tbl.render(order=["<30%", "30-50%", "50-70%", "70-100%", ">100%"]))

    lo_k = sum(c.k for k, c in tbl.cells.items() if k in ("<30%", "30-50%", "50-70%"))
    lo_n = sum(c.n for k, c in tbl.cells.items() if k in ("<30%", "30-50%", "50-70%"))
    hi_k = sum(c.k for k, c in tbl.cells.items() if k in ("70-100%", ">100%"))
    hi_n = sum(c.n for k, c in tbl.cells.items() if k in ("70-100%", ">100%"))
    z = stats.two_proportion_z(lo_k, lo_n, hi_k, hi_n)
    print(f"\n  他的 70% 门槛两侧：<70% = {stats.fmt_rate(lo_k, lo_n)}")
    print(f"                      ≥70% = {stats.fmt_rate(hi_k, hi_n)}")
    print(f"  两比例检验 z={z:+.2f}  "
          f"{'**门槛有效**' if abs(z) >= 1.96 else '无差别'}")

    print("\n  —— 门槛位置扫描（他选 70%，数据把它放在哪？）——")
    for thr in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        lk = ln = hk = hn = 0
        for day, rows in sorted(sess.items()):
            L = lv.get(day)
            if not L or len(rows) < 5:
                continue
            for i in range(len(rows) - 1):
                hi_ = max(b.high for b in rows[:i + 1])
                lo_ = min(b.low for b in rows[:i + 1])
                covered = (hi_ - lo_) / L.atr
                after = rows[i + 1:]
                px = rows[i].close
                moved = (max(b.high for b in after) - px >= 0.236 * L.atr or
                         px - min(b.low for b in after) >= 0.236 * L.atr)
                if covered < thr:
                    ln += 1
                    lk += moved
                else:
                    hn += 1
                    hk += moved
        if ln and hn:
            zz = stats.two_proportion_z(lk, ln, hk, hn)
            print(f"    门槛 {thr:.0%}: 下方 {100*lk/ln:5.1f}% (n={ln:<5}) "
                  f"上方 {100*hk/hn:5.1f}% (n={hn:<5}) 差 "
                  f"{100*(lk/ln-hk/hn):+5.1f}pp  z={zz:+6.2f}")


if __name__ == "__main__":
    main()
