"""对抗性复核 · 口径审计：把本轮报告里按【风险距离】分层的表，全部换成「钱」重报。

为什么有这个文件
----------------
`study_entry_location.Sig.money` 的 docstring（本轮 8 份报告里 5 份 import 的
同一个模块）写着：

    R 不是货币：风险 0.03 ATR 的一笔和风险 0.30 ATR 的一笔，同样报 −1R，
    亏的钱差十倍。任何按风险距离分层的表，R 那一列的分母是被分层变量本身
    改动过的，**不能**用来比较跨档的钱。这一列才能。

但 `study_overnight_anatomy.py` 与 `study_retest_divergence.py` 全文 **0 次**
引用 money，而这两份报告的核心分层变量恰好就是风险距离本身
（S<0.12ATR vs S≥0.12ATR；穿透深度 = 止损距离的组成部分）。
`study_simple_vs_elaborate.py` 有 money，但 §4 的自助带跑在总净R 上。

本脚本不引入任何新假设、不换样本、不换裁决规则，只做一件事：
**同一批信号、同一套裁决，把 R 那一列旁边补上钱那一列。**

复跑：.venv/bin/python research/satylab/audit_v15_units.py
"""
from __future__ import annotations

import math
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab import data                                             # noqa: E402
from satylab.study_v14_repro import LevelBook, load_10m              # noqa: E402
from satylab.study_entry_location import (                           # noqa: E402
    location_vars, isolated_trade, spearman,
)
from satylab.study_overnight_anatomy import harvest2, race           # noqa: E402

SPREAD = 0.6


def welch(a: list[float], b: list[float]) -> float:
    return (st.mean(a) - st.mean(b)) / math.sqrt(
        st.variance(a) / len(a) + st.variance(b) / len(b))


# ══════════════ 第一部分 · V15_ENTRY_LOCATION / OVERNIGHT_ANATOMY ════════════
def part1() -> None:
    bars, subs = load_10m("ES=F", False)
    book = LevelBook(data.load("ES=F", "20y", "1d"))
    sigs, e13s = harvest2(bars, book)
    sigs = location_vars(sigs, bars, e13s)
    for s in sigs:
        rc = race(s.entry, s.prot, s.risk, s.t1, s.direction, s.i, bars, subs)
        s.hit, s.pnull = rc.hit, rc.pnull
        isolated_trade(s, bars, subs, e13s)

    def bnet(s):                      # 纯括号净R
        return (abs(s.t1 - s.entry) / s.risk if s.hit else -1.0) - SPREAD / s.risk

    def bmon(s):                      # 纯括号净钱
        return bnet(s) * s.d4

    print(f"\n[1] 复现基线：n={len(sigs)}，可裁决 {sum(1 for s in sigs if s.hit is not None)}")

    def row(lbl, g, pure=False):
        if pure:
            g = [s for s in g if s.hit is not None]
            nr, mo = [bnet(s) for s in g], [bmon(s) for s in g]
        else:
            nr, mo = [s.net for s in g], [s.money for s in g]
        print(f"  {lbl:<26} n={len(g):>4} 均S/ATR={st.mean([s.d4 for s in g]):.3f} "
              f"均净R={st.mean(nr):+.3f} 总净R={sum(nr):+8.1f} "
              f"均净钱×1e3={1000*st.mean(mo):+7.2f} 总净钱={sum(mo):+7.3f}")

    RTH = [s for s in sigs if s.in_rth]
    ON = [s for s in sigs if not s.in_rth]
    print("\n  -- 时段（v14 完整管理，= OVERNIGHT 第一节）--")
    for lbl, g in (("RTH", RTH), ("夜盘", ON), ("全部", sigs)):
        row(lbl, g)
    print("  -- 时段（纯括号，= OVERNIGHT 2.2b / SIMPLE 第 5 节）--")
    for lbl, g in (("RTH", RTH), ("夜盘", ON), ("全部", sigs)):
        row(lbl, g, True)

    print("\n  -- OVERNIGHT §3.1b 的 2×2（完整管理）--")
    for lbl, g in (("RTH", RTH), ("夜盘", ON)):
        row(f"{lbl}·S<0.12ATR", [s for s in g if s.d4 < 0.12])
        row(f"{lbl}·S>=0.12ATR", [s for s in g if s.d4 >= 0.12])

    print("\n  -- 两个差：R 口径 vs 钱口径 --")
    cell = lambda g, narrow: [s for s in g if (s.d4 < 0.12) == narrow]
    for lbl, g in (("RTH", RTH), ("夜盘", ON)):
        n_, w_ = cell(g, True), cell(g, False)
        print(f"  {lbl} 窄−宽    ΔR={st.mean([s.net for s in n_])-st.mean([s.net for s in w_]):+.3f} "
              f"t={welch([s.net for s in n_], [s.net for s in w_]):+.2f}   "
              f"Δ钱×1e3={1000*(st.mean([s.money for s in n_])-st.mean([s.money for s in w_])):+7.2f} "
              f"t={welch([s.money for s in n_], [s.money for s in w_]):+.2f}")
    for narrow, lbl in ((True, "窄止损"), (False, "宽止损")):
        a, b = cell(ON, narrow), cell(RTH, narrow)
        print(f"  {lbl} 夜−RTH  ΔR={st.mean([s.net for s in a])-st.mean([s.net for s in b]):+.3f} "
              f"t={welch([s.net for s in a], [s.net for s in b]):+.2f}   "
              f"Δ钱×1e3={1000*(st.mean([s.money for s in a])-st.mean([s.money for s in b])):+7.2f} "
              f"t={welch([s.money for s in a], [s.money for s in b]):+.2f}")

    print("\n  -- ENTRY_LOCATION §2.5 / §8 的 D4：R 口径 vs 钱口径 --")
    rr, zr = spearman([s.d4 for s in sigs], [s.net for s in sigs])
    rm, zm = spearman([s.d4 for s in sigs], [s.money for s in sigs])
    print(f"  ρ(D4, 净R) ={rr:+.3f} z={zr:+.2f}    ρ(D4, 净钱)={rm:+.3f} z={zm:+.2f}")
    med = st.median([s.d4 for s in sigs])
    lo = [s for s in sigs if s.d4 <= med]
    hi = [s for s in sigs if s.d4 > med]
    print(f"  D4>中位 闸门  ΔR={st.mean([s.net for s in hi])-st.mean([s.net for s in lo]):+.3f} "
          f"t={welch([s.net for s in hi], [s.net for s in lo]):+.2f}   "
          f"Δ钱×1e3={1000*(st.mean([s.money for s in hi])-st.mean([s.money for s in lo])):+.2f} "
          f"t={welch([s.money for s in hi], [s.money for s in lo]):+.2f}")
    ss = sorted(sigs, key=lambda s: s.d4)
    k = len(ss) // 5
    for j in range(5):
        g = ss[j*k:(j+1)*k] if j < 4 else ss[4*k:]
        print(f"  Q{j+1} D4∈[{g[0].d4:.3f},{g[-1].d4:.3f}] n={len(g):>3} "
              f"均净R={st.mean([s.net for s in g]):+.3f} "
              f"均净钱×1e3={1000*st.mean([s.money for s in g]):+7.2f}")
    return bars, subs, book


# ══════════════ 第二部分 · SIMPLE_VS_ELABORATE §4 的自助带 ═══════════════════
def part2(bars, subs, book) -> None:
    import satylab.study_simple_vs_elaborate as SE
    SE.SUBS_CACHE = subs
    ctx, _e8, _e21 = SE.context(bars, book)
    E = SE.gen_E(bars, ctx, 6000, random.Random(SE.SEED))
    A = SE.gen_A(bars, ctx)
    D, Dlive = SE.gen_D(bars, ctx, book)
    for grp in (E, A, D, Dlive):
        for s in grp:
            SE.race(s, bars, subs)
    Eok = [s for s in E if s.hit is not None]
    print(f"\n[2] 随机地板 E 可裁决 n={len(Eok)}  均净R={st.mean([s.net for s in Eok]):+.4f}"
          f"  均净钱={st.mean([s.money for s in Eok]):+.5f}")
    for lbl, grp in (("A 极简版", A), ("D v14全套", D), ("D 线上排队", Dlive)):
        ok = [s for s in grp if s.hit is not None]
        print(f"  --- {lbl}  n={len(ok)} ---")
        for name, f in (("总净R ", lambda s: s.net), ("总净钱", lambda s: s.money)):
            pool = [f(s) for s in Eok]
            obs = sum(f(s) for s in ok)
            r2 = random.Random(12345)
            tots = sorted(sum(r2.choice(pool) for _ in range(len(ok)))
                          for _ in range(4000))
            pct = 100 * sum(1 for t in tots if t < obs) / len(tots)
            print(f"    {name}: 实测={obs:+9.3f} 随机中位={st.median(tots):+9.3f} "
                  f"5–95%=[{tots[200]:+.3f},{tots[3800]:+.3f}] 百分位={pct:.1f}")


# ══════════════ 第三部分 · LEVEL_RETEST_AND_DIVERGENCE ══════════════════════
def part3() -> None:
    import satylab.study_retest_divergence as RD
    ds = RD.build_5m("ES=F 5m", "ES=F", False)
    NR = RD.named_ratios()
    tr = RD.s2_trades(ds, RD.run_scan(ds, lambda day: NR))
    res = [t for t in tr if t["hit"] is not None]
    print(f"\n[3] S2 可判定 n={len(res)}")

    def show(lbl, g):
        if len(g) < 5:
            return
        nr = [t["net"] for t in g]
        mo = [t["net"] * t["risk_atr"] for t in g]
        print(f"  {lbl:<20} n={len(g):>5} 均S/ATR={st.mean([t['risk_atr'] for t in g]):.3f}"
              f" 均净R={st.mean(nr):+.3f} 均净钱×1e3={1000*st.mean(mo):+7.2f}"
              f" 总净R={sum(nr):+8.1f} 总净钱={sum(mo):+7.3f}")

    def cmp2(lbl, a, b):
        ra, rb = [t["net"] for t in a], [t["net"] for t in b]
        ma = [t["net"] * t["risk_atr"] for t in a]
        mb = [t["net"] * t["risk_atr"] for t in b]
        print(f"  >> {lbl:<22} ΔR={st.mean(ra)-st.mean(rb):+.3f} t={welch(ra, rb):+.2f}"
              f"   Δ钱×1e3={1000*(st.mean(ma)-st.mean(mb)):+7.2f} t={welch(ma, mb):+.2f}")

    k1 = [t for t in res if t["ep"].k == 1]
    k2 = [t for t in res if t["ep"].k >= 2]
    show("k=1", k1)
    show("k>=2", k2)
    show("全部", res)
    cmp2("k=1 减 k>=2", k1, k2)
    d0 = [t for t in res if t["ep"].depth <= 1e-9]
    dp = [t for t in res if t["ep"].depth > 1e-9]
    show("深度=0", d0)
    show("深度>0", dp)
    cmp2("深度>0 减 深度=0", dp, d0)
    fin = lambda x: x == x
    dec = [t for t in res if fin(t["ep"].prev_depth) and t["ep"].depth < t["ep"].prev_depth]
    nod = [t for t in res if fin(t["ep"].prev_depth) and t["ep"].depth >= t["ep"].prev_depth]
    show("递减", dec)
    show("未递减", nod)
    cmp2("递减 减 未递减", dec, nod)

    # S3 背离边际：报告只报了 ΔR，这里并排给出 Δ钱
    b5 = data.load("ES=F", "60d", "5m")
    bars10, subs10 = RD.to_10m(b5)
    ph10 = RD.phase_oscillator(bars10)
    print("\n  -- S3 §B.4 背离边际：ΔR 与 Δ钱 并排 --")
    sr = sm = tot = 0
    for N in (10, 15, 20, 30):
        for kind in ("bull", "bear"):
            ex = RD.find_extremes(bars10, ph10, N, kind, ds.book, dedupe=max(2, N // 2))
            t3 = [t for t in RD.s3_trades(ex, bars10, subs10, ds.book, N)
                  if t["hit"] is not None]
            D1 = [t for t in t3 if t["ext"].div]
            D0 = [t for t in t3 if not t["ext"].div]
            if len(D1) < 5 or len(D0) < 5:
                continue
            rR = lambda g: [t["net"] for t in g]
            rM = lambda g: [t["net"] * t["risk_atr"] for t in g]
            dR = st.mean(rR(D1)) - st.mean(rR(D0))
            dM = st.mean(rM(D1)) - st.mean(rM(D0))
            tot += 1
            sr += dR > 0
            sm += dM > 0
            print(f"  N={N}·{'底' if kind == 'bull' else '顶'} "
                  f"S(D1)={st.mean([t['risk_atr'] for t in D1]):.3f} "
                  f"S(D0)={st.mean([t['risk_atr'] for t in D0]):.3f} "
                  f"ΔR={dR:+.3f} t={welch(rR(D1), rR(D0)):+.2f} "
                  f"Δ钱×1e3={1000*dM:+7.2f} t={welch(rM(D1), rM(D0)):+.2f}")
    print(f"  ΔR 为正 {sr}/{tot}；Δ钱 为正 {sm}/{tot}")


if __name__ == "__main__":
    bars, subs, book = part1()
    part2(bars, subs, book)
    part3()
