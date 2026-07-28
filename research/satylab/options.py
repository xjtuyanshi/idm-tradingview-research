"""0DTE 期权口径 —— 把「标的 R」翻译成「期权 %」。

这个模块补的是项目里最大的一条裂缝：**账本记的是标的 R，用户交易的是 0DTE 期权。**
在 2026-07-28 拿到 Unusual Whales 的真实 SPXW 0DTE 链之前，这条裂缝从未被量化过。

核心结论（用当日真实链算出来的，见 research/fixtures/spxw_0dte_2026-07-28.json）：

    7440C（Saty 当日盘前点名的上行标的）：价 9.20，delta 0.473，gamma 0.016，
    theta −9.736（到到期）。距收盘 3.5 小时 → **每小时吃掉约 30% 权利金**。

    标的 +13.9 点（到 +0.382 位）= +1.31R  →  期权 +88%
    标的 −10.6 点（打保护位）   = −1.00R  →  期权 −45%

    但把 theta 加进去：
        半小时打完：  +73% / −60%   → 盈亏比 1.22:1
        拖两小时：    +28% / −105%  → 盈亏比 0.27:1   ← 同一笔交易

**时间是 0DTE 的主导变量，而 v14/v15 的规则里没有任何时间维度。**
这解释了 Saty 为什么 11:37 收工、为什么永远 "scale out, leave runners"。

用法::

    chain = load_chain("research/fixtures/spxw_0dte_2026-07-28.json")
    q = quote(chain, 7440, "call")
    r = trade_pnl(q, spot=7437.8, target=7451.7, stop=7427.2,
                  hours_held=0.5, hours_to_close=3.5)
    r.pnl_pct_win, r.pnl_pct_loss, r.effective_rr
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 0DTE 的 theta 不是线性的——越接近收盘衰减越快。UW 给的 theta 是「到到期」的
# 总额。把它摊到剩余时间上时，用一个凸性因子近似加速：t^ACCEL 的导数形式。
# ACCEL = 1.0 就是线性摊销（保守，低估后段损耗）。
# 我们用 1.0 并在报告里明说这是【低估】，因为高估会让系统看起来比实际好。
THETA_ACCEL = 1.0


@dataclass(frozen=True, slots=True)
class Quote:
    strike: float
    right: str          # "call" | "put"
    price: float        # last
    delta: float
    gamma: float
    theta_to_expiry: float   # 负数，UW 口径 = 到到期的总衰减
    iv: float
    volume: int
    oi: int

    def value_at(self, spot_now: float, spot_then: float) -> float:
        """二阶泰勒：ΔV ≈ δ·ΔS + ½γ·ΔS²（不含 theta，不含 vega）。"""
        ds = spot_then - spot_now
        dv = self.delta * ds + 0.5 * self.gamma * ds * ds
        return max(0.0, self.price + dv)

    def theta_cost(self, hours_held: float, hours_to_close: float) -> float:
        """持仓 hours_held 小时的 theta 成本（正数 = 损失的权利金）。"""
        if hours_to_close <= 0:
            return abs(self.theta_to_expiry)
        frac = min(1.0, max(0.0, hours_held / hours_to_close)) ** THETA_ACCEL
        return abs(self.theta_to_expiry) * frac


@dataclass(frozen=True, slots=True)
class TradeResult:
    r_win: float            # 标的口径的盈亏比（目标距离/止损距离）
    pnl_pct_win: float      # 期权口径，含 theta
    pnl_pct_loss: float
    pnl_pct_win_no_theta: float
    pnl_pct_loss_no_theta: float
    theta_pct: float        # theta 单独吃掉的百分比

    @property
    def effective_rr(self) -> float:
        """期权口径的真实盈亏比。这是唯一该看的那个数。"""
        if self.pnl_pct_loss >= 0:
            return float("inf")
        return self.pnl_pct_win / abs(self.pnl_pct_loss)

    @property
    def breakeven_winrate(self) -> float:
        """期权口径下的打平胜率。与标的口径的差距就是裂缝大小。"""
        rr = self.effective_rr
        return 1.0 / (1.0 + rr) if rr > 0 else 1.0


def trade_pnl(q: Quote, *, spot: float, target: float, stop: float,
              hours_held: float, hours_to_close: float) -> TradeResult:
    """一笔交易在期权口径下的真实结果。

    hours_held 是【到达目标或止损所花的时间】，不是计划持仓时间。
    赢单和输单可以用不同的 hours_held —— 现实中输单往往拖得更久。
    """
    v_t = q.value_at(spot, target)
    v_s = q.value_at(spot, stop)
    th = q.theta_cost(hours_held, hours_to_close)

    win_nt = (v_t - q.price) / q.price * 100
    los_nt = (v_s - q.price) / q.price * 100
    win = (v_t - th - q.price) / q.price * 100
    los = (v_s - th - q.price) / q.price * 100

    risk = abs(spot - stop)
    reward = abs(target - spot)
    return TradeResult(
        r_win=reward / risk if risk > 0 else float("nan"),
        pnl_pct_win=win, pnl_pct_loss=los,
        pnl_pct_win_no_theta=win_nt, pnl_pct_loss_no_theta=los_nt,
        theta_pct=th / q.price * 100,
    )


# ── 链的读写 ──────────────────────────────────────────────────────────────

def load_chain(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def quote(chain: dict, strike: float, right: str) -> Quote:
    row = next(r for r in chain["rows"] if abs(r["strike"] - strike) < 0.01)
    side = row[right]
    return Quote(strike=row["strike"], right=right, price=side["last"],
                 delta=side["delta"], gamma=side["gamma"],
                 theta_to_expiry=side["theta"], iv=side["iv"],
                 volume=side["volume"], oi=side["oi"])


# ── LB：Saty 的成交量榜 / 钉价判据 ────────────────────────────────────────

def leaderboard(chain: dict, spot: float, top: int = 10) -> list[dict]:
    """前 N 大成交合约，标注是否 ITM。

    Saty 原话（2026-07-27 14:29）：
      "LB = SPX Volume Leaderboard … LB is clear = none of the top 10 contracts
       are currently ITM, i.e. risk of closing at 0. Generally I don't look at
       this until later in the day, but when we have big gap ups/downs I will
       look earlier to see if there is potential for pinning early."
    """
    items = []
    for r in chain["rows"]:
        for right in ("call", "put"):
            side = r.get(right)
            if not side or not side.get("volume"):
                continue
            itm = (spot > r["strike"]) if right == "call" else (spot < r["strike"])
            items.append({"strike": r["strike"], "right": right,
                          "volume": side["volume"], "itm": itm})
    items.sort(key=lambda x: -x["volume"])
    return items[:top]


def lb_is_clear(chain: dict, spot: float, top: int = 10) -> bool:
    return not any(i["itm"] for i in leaderboard(chain, spot, top))


# ── 隐含日内波动 vs 我们的位梯 ───────────────────────────────────────────

def rungs_vs_implied(anchor: float, atr: float, implied_move: float,
                     ratios: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 1.0),
                     ) -> list[dict]:
    """每一档位距锚多远，以及它是否落在今日 0DTE 隐含波动之内。

    2026-07-28 实例：隐含 ±17.51 点，ATR 88.21。
    → 0.236 档 = 20.8 点，**已经在隐含波动之外**。
    也就是说我们的【第一目标】默认设在市场认为今天走不到的地方。
    """
    out = []
    for r in ratios:
        dist = r * atr
        out.append({"ratio": r, "level_up": anchor + dist,
                    "level_dn": anchor - dist, "dist": dist,
                    "inside_implied": dist <= implied_move,
                    "pct_of_implied": dist / implied_move if implied_move else None})
    return out
