"""資金管理層:Kelly 口數、風險上限、回撤煞車。engine 三模式共用。

原則(老闆:資金管理也很重要——數學上它是驗證的延伸):
- Kelly N* = μE/σ²(μ,σ=每口損益;E=權益)。μ≤0 → N*=0,沒有下注資格。
- 短 vol / 肥尾策略違反 Kelly 的常態假設 → 一律取分數 Kelly(預設 1/4)再疊 worst-case 上限。
- 任何策略同時受三道閘:分數 Kelly、單筆風險上限(worst-case 損失 ≤ r% 權益)、回撤煞車。
"""
import math


def trade_stats(pnls):
    """每口損益序列 → (μ, σ, worst)。n<8 視為樣本不足回 None(小樣本 Kelly=雜訊)。"""
    n = len(pnls)
    if n < 8:
        return None
    m = sum(pnls) / n
    var = sum((x - m) ** 2 for x in pnls) / (n - 1)
    return m, math.sqrt(var), min(pnls)


def kelly_contracts(pnls, equity, fraction=0.25, max_risk=0.02):
    """回 (口數, 說明)。三道閘取最小:
    ①分數 Kelly:N = fraction × μE/σ²(μ≤0 → 0)
    ②單筆風險:N ≤ max_risk × E / |歷史最差單筆|
    ③向下取整,最少 0 口。"""
    st = trade_stats(pnls)
    if st is None:
        return 0, "樣本<8筆,不給口數(小樣本Kelly=雜訊)"
    mu, sd, worst = st
    if mu <= 0 or sd <= 0:
        return 0, f"μ={mu:,.0f}≤0:無edge,Kelly=0,沒有下注資格"
    n_kelly = fraction * mu * equity / (sd * sd)
    n_risk = max_risk * equity / abs(worst) if worst < 0 else n_kelly
    n = int(min(n_kelly, n_risk))
    gate = "Kelly" if n_kelly <= n_risk else f"風險上限(worst {worst:,.0f})"
    return max(n, 0), (f"{fraction:.0%}Kelly={n_kelly:.1f}口, 風險閘={n_risk:.1f}口 → "
                       f"{max(n,0)}口(綁定閘:{gate})")


class DrawdownBrake:
    """權益回撤煞車:回撤過 soft → 口數減半;過 hard → 全停,人工複核才重啟。
    這道閘擋的是「模型失效但你還在下注」的情境——回測驗不到的那種死法。"""
    def __init__(self, soft=0.10, hard=0.20):
        self.soft, self.hard = soft, hard
        self.peak = None
        self.halted = False

    def scale(self, equity):
        self.peak = equity if self.peak is None else max(self.peak, equity)
        dd = 1 - equity / self.peak
        if dd >= self.hard:
            self.halted = True
        if self.halted:
            return 0.0, dd
        if dd >= self.soft:
            return 0.5, dd
        return 1.0, dd


def ruin_check(pnls, contracts, equity, n_paths=2000, horizon=250, seed=11):
    """自助法(bootstrap)壓力測試:抽歷史損益重組未來,回 P(回撤>50%)。
    無 numpy 的 LCG 抽樣(可重現)。"""
    st = trade_stats(pnls)
    if st is None or contracts <= 0:
        return 0.0
    s, ruin = seed, 0
    for _ in range(n_paths):
        eq, peak = equity, equity
        for _ in range(horizon):
            s = (1103515245 * s + 12345) & 0x7FFFFFFF
            eq += contracts * pnls[s % len(pnls)]
            peak = max(peak, eq)
            if eq < peak * 0.5:
                ruin += 1
                break
    return ruin / n_paths
