"""V15 对抗性复核（混淆变量）—— 生成 research/reports/V15_ADVERSARIAL_CONFOUND.md 的全部计算。

只调用仓库既有模块的生成器，不重写任何状态机：
  study_entry_location.build       517 个 v14 信号（与被复核的报告同一批）
  study_retest_divergence          S2「位被反复拒绝」的事件与交易
  study_simple_vs_elaborate        五个选手 + 随机池 E

核心怀疑：本轮多个假设会不会全部塌缩成「止损距离」。答案是——止损距离本身也不是一个
效应，它是一个记账口径。纯括号净 R = 毛R − 0.6/S，分母就是被分层的那个变量。所以每一
个「按 S 分层再看 R」的表都在测 1/S。对照口径是 `Sig.money = 净R × (风险距离/日ATR)`，
即固定名义敞口下每 1 单位本金的日 ATR 盈亏，对 S 免疫。

四节：
  1  ρ(|MAE|/风险, D4) 的独立性置换零分布；夜盘 §3.1b 的 2×2 换钱口径；
     D4 闸门与五分位的 R/钱对照；控制 D4 后的「夜盘 − RTH」
  2  分时段 D4 效应；0.12 ATR 闸门；点差恒等式；五个位置变量的 R/钱对照；
     控制 D4 五层后 D1/D2r/D2b/D3 的钱效应
  3  S2 的穿透深度 vs 止损距离（共线性 + 控制后是否还在）
  4  极简对决 §4 的自助带换成钱口径重跑

Usage:  .venv/bin/python research/satylab/audit_v15_confound.py [1|2|3|4|all]
"""

from __future__ import annotations

import math
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satylab.study_entry_location import (                       # noqa: E402
    build, cond_spearman_z, cond_trend_z, spearman, z_geom, SPREAD,
)

SEED = 20260728


def m(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def welch(a, b) -> float:
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    se = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    return (m(a) - m(b)) / se if se else float("nan")


def strat_pool(items, sval, sel, key, k: int = 5):
    """按 sval 分 k 层，层内比较 sel/非 sel 的 key 均值差，逆方差汇总。"""
    srt = sorted(items, key=sval)
    n = len(srt)
    num = den = 0.0
    rows = []
    for i in range(k):
        g = srt[i * n // k:(i + 1) * n // k]
        A = [key(x) for x in g if sel(x)]
        B = [key(x) for x in g if not sel(x)]
        if len(A) < 2 or len(B) < 2:
            continue
        d = m(A) - m(B)
        v = st.variance(A) / len(A) + st.variance(B) / len(B)
        if v <= 0:
            continue
        rows.append((len(A), len(B), d))
        num += d / v
        den += 1 / v
    dj = num / den if den else float("nan")
    return dj, (dj * math.sqrt(den) if den else float("nan")), rows


# ═══════════════════════════════ 第 1 节 ═══════════════════════════════════
def section_1() -> None:
    ds = build("ES=F", rth_only=False)
    S = ds["sigs"]
    print(f"signals={len(S)}  decidable={sum(1 for s in S if s.hit is not None)}")

    # ── 1.1 ρ(|MAE|/风险, D4) 的独立性置换零分布 ──────────────────────────
    d4 = [s.d4 for s in S]
    mae = [abs(s.mae) for s in S]
    maer = [abs(s.mae) / s.d4 for s in S]
    r_obs, z_obs = spearman(d4, maer)
    r_raw, z_raw = spearman(d4, mae)
    print("\n=== 1.1 ρ(|MAE|/风险, D4) 是不是恒等式 ===")
    print(f"观测  ρ(|MAE|/S, S) = {r_obs:+.3f} (z={z_obs:+.2f})   [报告: -0.505 / -11.47]")
    print(f"      ρ(|MAE|,   S) = {r_raw:+.3f} (z={z_raw:+.2f})   [报告: +0.136 / +3.08]")
    rng = random.Random(SEED)
    null = []
    for _ in range(2000):
        p = mae[:]
        rng.shuffle(p)                       # 破坏 MAE 与 S 的一切真实关系
        null.append(spearman(d4, [a / b for a, b in zip(p, d4)])[0])
    null.sort()
    print(f"独立置换零分布 ρ: 均值 {m(null):+.3f}  5%={null[100]:+.3f}  "
          f"50%={null[1000]:+.3f}  95%={null[1900]:+.3f}")
    print(f"观测值在零分布的百分位: "
          f"{100 * sum(1 for x in null if x < r_obs) / len(null):.1f}%")

    # ── 1.2 夜盘报告 §3.1b 的 2×2，换成钱 ────────────────────────────────
    print("\n=== 1.2 夜盘 §3.1b 的 2×2：R 口径 vs 钱口径 ===")
    print(f"{'格子':<22}{'n':>5}{'均净R':>9}{'均净钱':>10}{'均毛钱':>10}"
          f"{'点差(R)':>9}{'中位S':>8}")
    cells = {}
    for sess in ("RTH", "ON"):
        for tag, fn in (("窄 S<0.12", lambda s: s.d4 < 0.12),
                        ("宽 S>=0.12", lambda s: s.d4 >= 0.12)):
            g = [s for s in S
                 if (s.session == "RTH") == (sess == "RTH") and fn(s)]
            cells[(sess, tag)] = g
            print(f"{sess + ' · ' + tag:<22}{len(g):>5}"
                  f"{m(s.net for s in g):>9.3f}{m(s.money for s in g):>10.5f}"
                  f"{m(s.r * s.d4 for s in g):>10.5f}"
                  f"{m(SPREAD / s.risk for s in g):>9.3f}"
                  f"{st.median([s.d4 for s in g]):>8.3f}")
    print("\n效应对比（正 = 前者更好）:")
    for lbl, a, b in (
        ("RTH: 宽−窄", cells[("RTH", "宽 S>=0.12")], cells[("RTH", "窄 S<0.12")]),
        ("夜盘: 宽−窄", cells[("ON", "宽 S>=0.12")], cells[("ON", "窄 S<0.12")]),
        ("窄格: RTH−夜盘", cells[("RTH", "窄 S<0.12")], cells[("ON", "窄 S<0.12")]),
        ("宽格: RTH−夜盘", cells[("RTH", "宽 S>=0.12")], cells[("ON", "宽 S>=0.12")]),
    ):
        for nm, key in (("R", lambda s: s.net), ("净钱", lambda s: s.money),
                        ("毛钱", lambda s: s.r * s.d4)):
            A_, B_ = [key(s) for s in a], [key(s) for s in b]
            end = "\n" if nm == "毛钱" else "   "
            head = f"  {lbl:<16} " if nm == "R" else ""
            print(f"{head}Δ{nm}={m(A_) - m(B_):+.5f} (t={welch(A_, B_):+.2f})",
                  end=end)

    # ── 1.3 D4 ≥ 中位 闸门 ───────────────────────────────────────────────
    print("\n=== 1.3 D4 ≥ 中位 闸门：R 口径 vs 钱口径 ===")
    med = st.median(d4)
    hi = [s for s in S if s.d4 >= med]
    lo = [s for s in S if s.d4 < med]
    for lbl, key in (("均净R", lambda s: s.net), ("均净钱", lambda s: s.money),
                     ("均毛R", lambda s: s.r), ("均毛钱", lambda s: s.r * s.d4)):
        A_, B_ = [key(s) for s in hi], [key(s) for s in lo]
        print(f"  {lbl:<8} 大止损 {m(A_):+.4f}   小止损 {m(B_):+.4f}"
              f"   Δ={m(A_) - m(B_):+.4f}  Welch t={welch(A_, B_):+.2f}")

    # ── 1.4 D4 五分位 ───────────────────────────────────────────────────
    print("\n=== 1.4 D4 五分位分层：R vs 钱 ===")
    srt = sorted(S, key=lambda s: s.d4)
    n = len(srt)
    print(f"{'档':<4}{'n':>5}{'S区间':>16}{'均净R':>10}{'均净钱':>11}"
          f"{'均毛钱':>11}{'超额pp':>9}{'z_geom':>8}")
    for i in range(5):
        g = srt[i * n // 5:(i + 1) * n // 5]
        res = [s for s in g if s.hit is not None]
        z, _, obs, nul = z_geom([s.hit for s in res], [s.pnull for s in res])
        print(f"Q{i + 1:<3}{len(g):>5}{f'{g[0].d4:.3f}-{g[-1].d4:.3f}':>16}"
              f"{m(s.net for s in g):>10.3f}{m(s.money for s in g):>11.5f}"
              f"{m(s.r * s.d4 for s in g):>11.5f}{100 * (obs - nul):>9.1f}{z:>8.2f}")
    for nm, key in (("净R", lambda s: s.net), ("净钱", lambda s: s.money),
                    ("毛钱", lambda s: s.r * s.d4)):
        r, z = spearman(d4, [key(s) for s in S])
        print(f"  秩相关 D4 vs {nm:<4} ρ={r:+.3f} (z={z:+.2f})")

    # ── 1.5 控制 D4 之后的「夜盘 − RTH」 ─────────────────────────────────
    print("\n=== 1.5 控制 D4（5 层）之后：夜盘 − RTH ===")
    for nm, key in (("钱", lambda s: s.money), ("净R", lambda s: s.net)):
        A_ = [key(s) for s in S if s.session != "RTH"]
        B_ = [key(s) for s in S if s.session == "RTH"]
        dj, zj, rows = strat_pool(S, lambda s: s.d4,
                                  lambda s: s.session != "RTH", key)
        print(f"  {nm:<4} 未控制 Δ={m(A_) - m(B_):+.5f} (t={welch(A_, B_):+.2f})"
              f"   控制后 Δ={dj:+.5f} (z={zj:+.2f})   层内n={[(x, y) for x, y, _ in rows]}")


# ═══════════════════════════════ 第 2 节 ═══════════════════════════════════
def section_2() -> None:
    ds = build("ES=F", rth_only=False)
    S = ds["sigs"]

    print("=== 2.1 D4 的钱效应：分时段 ===")
    for lbl, sel in (("全样本", lambda s: True),
                     ("RTH", lambda s: s.session == "RTH"),
                     ("夜盘", lambda s: s.session != "RTH")):
        g = [s for s in S if sel(s)]
        d4 = [s.d4 for s in g]
        rR, zR = spearman(d4, [s.net for s in g])
        rM, zM = spearman(d4, [s.money for s in g])
        med = st.median(d4)
        hi = [s for s in g if s.d4 >= med]
        lo = [s for s in g if s.d4 < med]
        print(f"{lbl:<8} n={len(g):>4}  ρ(D4,净R)={rR:+.3f}(z={zR:+.2f})  "
              f"ρ(D4,净钱)={rM:+.3f}(z={zM:+.2f})   "
              f"闸门Δ净钱={m(s.money for s in hi) - m(s.money for s in lo):+.5f}"
              f"(t={welch([s.money for s in hi], [s.money for s in lo]):+.2f})"
              f"   闸门Δ净R={m(s.net for s in hi) - m(s.net for s in lo):+.3f}"
              f"(t={welch([s.net for s in hi], [s.net for s in lo]):+.2f})")

    print("\n=== 2.2 0.12 ATR 闸门（夜盘报告 §3.1 那把刀）在钱口径下 ===")
    for lbl, sel in (("全样本", lambda s: True),
                     ("RTH", lambda s: s.session == "RTH"),
                     ("夜盘", lambda s: s.session != "RTH")):
        g = [s for s in S if sel(s)]
        a = [s for s in g if s.d4 >= 0.12]
        b = [s for s in g if s.d4 < 0.12]
        print(f"{lbl:<8} 宽 n={len(a):>3} 均净钱={m(s.money for s in a):+.5f}   "
              f"窄 n={len(b):>3} 均净钱={m(s.money for s in b):+.5f}   "
              f"Δ={m(s.money for s in a) - m(s.money for s in b):+.5f} "
              f"(t={welch([s.money for s in a], [s.money for s in b]):+.2f})"
              f"   [ΔR={m(s.net for s in a) - m(s.net for s in b):+.3f}]")

    print("\n=== 2.3 逐笔恒等式：净R 与 1/S 的机械关系 ===")
    sp = [SPREAD / s.risk for s in S]
    r1, z1 = spearman([s.d4 for s in S], sp)
    print(f"ρ(D4, 点差成本R) = {r1:+.3f} (z={z1:+.2f})   点差成本均 {m(sp):.4f}R"
          f"   （全样本均净R = {m(s.net for s in S):+.4f}）")

    print("\n=== 2.4 五个位置变量：R 口径 vs 钱口径 ===")
    VARS = (("D1", lambda s: s.d1), ("D2r", lambda s: s.d2r),
            ("D2b", lambda s: s.d2b), ("D3", lambda s: s.d3),
            ("D4", lambda s: s.d4))
    for nm, g in VARS:
        xs = [g(s) for s in S]
        a, za = spearman(xs, [s.net for s in S])
        b, zb = spearman(xs, [s.money for s in S])
        print(f"  {nm:<4} 净R ρ={a:+.3f}(z={za:+.2f})   净钱 ρ={b:+.3f}(z={zb:+.2f})")

    print("\n=== 2.5 控制 D4 五层之后（study_entry_location §3.1，报告未渲染）===")
    for nm, g in VARS[:-1]:
        cz = cond_trend_z(S, g, lambda s: s.d4)
        rm, zm = cond_spearman_z(S, g, lambda s: s.money, lambda s: s.d4)
        rn, zn = cond_spearman_z(S, g, lambda s: s.net, lambda s: s.d4)
        print(f"  {nm:<5} 超额趋势z={cz:+.2f}   层内 净钱 ρ={rm:+.3f} (z={zm:+.2f})"
              f"   层内 净R ρ={rn:+.3f} (z={zn:+.2f})")
    cz4 = cond_trend_z(S, lambda s: s.d4, lambda s: s.d3)
    rm4, zm4 = cond_spearman_z(S, lambda s: s.d4, lambda s: s.money, lambda s: s.d3)
    rn4, zn4 = cond_spearman_z(S, lambda s: s.d4, lambda s: s.net, lambda s: s.d3)
    print(f"  D4(控制D3) 超额趋势z={cz4:+.2f}   净钱 ρ={rm4:+.3f} (z={zm4:+.2f})"
          f"   净R ρ={rn4:+.3f} (z={zn4:+.2f})")

    print("\n=== 2.6 状态层 §5「边缘拒绝是反例」的止损配对复核 ===")
    for lo, hi in ((0.08, 0.11), (0.06, 0.13)):
        g = [s for s in S if lo <= s.d4 <= hi]
        print(f"  v14 信号 S∈[{lo},{hi}]: n={len(g):>3} 均S={m(s.d4 for s in g):.3f} "
              f"均净R={m(s.net for s in g):+.3f} 均净钱={m(s.money for s in g):+.5f}")
    print("  对照（V15_REGIME_LAYER §5）：边缘拒绝 n=277 均S=0.093 "
          "均净R=-0.092 均净钱=-0.00560")


# ═══════════════════════════════ 第 3 节 ═══════════════════════════════════
def section_3() -> None:
    from satylab.study_retest_divergence import (                # noqa: E402
        build_5m, named_ratios, run_scan, s2_trades,
    )
    DS = build_5m("ES=F 5m", "ES=F", False)
    EPS = run_scan(DS, lambda d: named_ratios())
    TR = s2_trades(DS, EPS)
    res = [t for t in TR if t["hit"] is not None]
    print(f"事件 {len(EPS)}  可交易并判定 {len(res)}")

    def money(t):
        return t["net"] * t["risk_atr"]

    dep = [t["ep"].depth for t in res]
    rsk = [t["risk_atr"] for t in res]
    r, z = spearman(dep, rsk)
    md, mr = m(dep), m(rsk)
    pr = (sum((a - md) * (b - mr) for a, b in zip(dep, rsk)) /
          math.sqrt(sum((a - md) ** 2 for a in dep) *
                    sum((b - mr) ** 2 for b in rsk)))
    slope = pr * st.stdev(rsk) / st.stdev(dep)
    print("\n=== 3.1 穿透深度 vs 止损距离 ===")
    print("构造：stop = L − a·(depth + 0.02·ATR)，entry 离 L ≥0.05·ATR "
          "⇒ S/ATR ≈ |close−L|/ATR + depth + 0.02")
    print(f"Spearman ρ = {r:+.3f} (z={z:+.2f})    Pearson r = {pr:+.3f}")
    print(f"深度 均值 {md:.4f} ATR，止损 均值 {mr:.4f} ATR；"
          f"深度占止损的均比例 {m(a / b for a, b in zip(dep, rsk)):.1%}")
    print(f"止损 sd {st.stdev(rsk):.4f} → 回归掉深度后残差 sd "
          f"{st.stdev([b - slope * (a - md) for a, b in zip(dep, rsk)]):.4f}")

    print("\n=== 3.2 各口径：R vs 钱 ===")
    print(f"{'分组':<28}{'n':>6}{'均净R':>10}{'均净钱':>12}{'均S(ATR)':>10}")

    def blk(lbl, g):
        g = [t for t in g if t["hit"] is not None]
        print(f"{lbl:<28}{len(g):>6}{m(t['net'] for t in g):>10.4f}"
              f"{m(money(t) for t in g):>12.5f}"
              f"{m(t['risk_atr'] for t in g):>10.4f}")

    dec = [t for t in res if t["ep"].k >= 2
           and t["ep"].prev_depth == t["ep"].prev_depth
           and t["ep"].depth < t["ep"].prev_depth]
    inc = [t for t in res if t["ep"].k >= 2
           and t["ep"].prev_depth == t["ep"].prev_depth
           and t["ep"].depth >= t["ep"].prev_depth]
    z0 = [t for t in res if t["ep"].depth <= 1e-9]
    zp = [t for t in res if t["ep"].depth > 1e-9]
    blk("全部", res)
    blk("k = 1", [t for t in res if t["ep"].k == 1])
    blk("k >= 2", [t for t in res if t["ep"].k >= 2])
    blk("深度递减", dec)
    blk("深度未递减", inc)
    blk("本次深度 = 0", z0)
    blk("本次深度 > 0", zp)

    print("\n对比（正 = 前者更好）:")
    for lbl, a, b in (("k=1 − k>=2", [t for t in res if t["ep"].k == 1],
                       [t for t in res if t["ep"].k >= 2]),
                      ("递减 − 未递减", dec, inc),
                      ("深度>0 − 深度=0", zp, z0)):
        print(f"  {lbl:<16} "
              f"ΔR={m(t['net'] for t in a) - m(t['net'] for t in b):+.4f} "
              f"(t={welch([t['net'] for t in a], [t['net'] for t in b]):+.2f})   "
              f"Δ钱={m(money(t) for t in a) - m(money(t) for t in b):+.5f} "
              f"(t={welch([money(t) for t in a], [money(t) for t in b]):+.2f})   "
              f"ΔS={m(t['risk_atr'] for t in a) - m(t['risk_atr'] for t in b):+.4f}")

    print("\n=== 3.3 控制止损距离（5 层）后：深度>0 vs 深度=0（钱口径）===")
    dj, zj, rows = strat_pool(res, lambda t: t["risk_atr"],
                              lambda t: t["ep"].depth > 1e-9, money)
    for i, (na, nb, d) in enumerate(rows):
        print(f"  S层{i + 1}  n={na}/{nb}  Δ钱={d:+.5f}")
    print(f"  汇总 Δ钱 = {dj:+.5f}  z = {zj:+.2f}   ← 效应在控制之后没有消失")


# ═══════════════════════════════ 第 4 节 ═══════════════════════════════════
def section_4(reps: int = 4000) -> None:
    import satylab.study_simple_vs_elaborate as M                # noqa: E402
    from satylab import data                                     # noqa: E402
    from satylab.study_v14_repro import LevelBook, load_10m      # noqa: E402

    rng = random.Random(M.SEED)
    bars, subs = load_10m("ES=F", False)
    M.SUBS_CACHE = subs
    book = LevelBook(data.load("ES=F", "20y", "1d"))
    ctx, e8, e21 = M.context(bars, book)
    sA = M.gen_A(bars, ctx)
    sB = M.gen_B(bars, ctx)
    sC = M.gen_C(bars, ctx, e8, e21)
    sD, sDlive = M.gen_D(bars, ctx, book)
    sE = M.gen_E(bars, ctx, M.RANDOM_POOL, rng)
    for g in (sA, sB, sC, sD, sDlive, sE):
        for s in g:
            M.race(s, bars, subs)

    decE = [s for s in sE if s.hit is not None]

    def band(n, key):
        tots = [sum(key(decE[rng.randrange(len(decE))]) for _ in range(n))
                for _ in range(reps)]
        tots.sort()
        return tots

    def pctile(t, x):
        return 100.0 * sum(1 for v in t if v < x) / len(t)

    print("极简对决 §4 的自助带：R 口径（报告用的）vs 钱口径（报告 §0.1 规定的）")
    print(f"{'选手':<20}{'n':>5}{'总净R':>10}{'R百分位':>10}{'总净钱':>11}{'钱百分位':>10}")
    for lbl, g in (("A · 极简版", sA), ("B · 去状态层", sB),
                   ("C · 去位置层", sC), ("D · v14 全套", sD),
                   ("D · v14 线上排队", sDlive)):
        dec = [s for s in g if s.hit is not None]
        n = len(dec)
        tR, tM = band(n, lambda s: s.net), band(n, lambda s: s.money)
        oR, oM = sum(s.net for s in dec), sum(s.money for s in dec)
        print(f"{lbl:<20}{n:>5}{oR:>10.1f}{pctile(tR, oR):>10.1f}"
              f"{oM:>11.2f}{pctile(tM, oM):>10.1f}")
        if lbl == "D · v14 全套":
            print(f"    随机 总净R  中位 {tR[len(tR) // 2]:+.1f} "
                  f"[5-95%: {tR[int(.05 * len(tR))]:+.1f}, {tR[int(.95 * len(tR))]:+.1f}]")
            print(f"    随机 总净钱 中位 {tM[len(tM) // 2]:+.2f} "
                  f"[5-95%: {tM[int(.05 * len(tM))]:+.2f}, {tM[int(.95 * len(tM))]:+.2f}]")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for k, fn in (("1", section_1), ("2", section_2),
                  ("3", section_3), ("4", section_4)):
        if which in ("all", k):
            print(f"\n{'=' * 28} 第 {k} 节 {'=' * 28}")
            fn()
