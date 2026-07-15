"""可 Shioaji 執行的策略,全部插同一個引擎(engine.Strategy 介面)。
每個都把『不 blow up 的部位上限 + 出場/停損』內建——短 vol / 折溢價都是短尾,
紀律在程式裡,不靠自制力。TXO 的隱含/前瞻波動之後接你 cb_core 的同一套。
"""
from engine import Bar, Signal, Strategy


class OptionVolSeller(Strategy):
    """賣波動率:市場隱含波動 IV 明顯 > 前瞻波動 FV → 賣選擇權收 vol 溢酬。
    delta 交給避險腿(這裡只發選擇權賣/回補訊號)。
    bar.extra 需含:implied_vol、forward_vol、dte(到期天數)。
    風控:近月不賣(min_dte)、部位硬上限(max_contracts)、溢酬吃完就回補。
    """
    def __init__(self, edge_vol=0.05, exit_vol=0.01, min_dte=7, max_contracts=5, size=1.0):
        self.edge_vol, self.exit_vol = edge_vol, exit_vol
        self.min_dte, self.max, self.size = min_dte, max_contracts, size
        self.pos = 0

    def on_bar(self, bar: Bar) -> list[Signal]:
        iv, fv = bar.extra.get("implied_vol"), bar.extra.get("forward_vol")
        dte = bar.extra.get("dte", 0)
        if iv is None or fv is None:
            return []
        edge = iv - fv
        if self.pos == 0:
            if edge > self.edge_vol and dte >= self.min_dte:
                # 依 edge 放大,但硬封在上限內(短尾:寧可小)
                n = min(self.max, max(1, int(self.size * edge / self.edge_vol)))
                self.pos = -n
                return [Signal(bar.symbol, -1, n, f"IV {iv:.0%}>FV {fv:.0%} 賣vol")]
        else:
            if edge < self.exit_vol or dte < self.min_dte:
                n = abs(self.pos)
                self.pos = 0
                return [Signal(bar.symbol, +1, n, "溢酬吃完/近月 回補")]
        return []


class ETFPremiumConverge(Strategy):
    """ETF 折溢價收斂:溢價 > 門檻 → 放空賭跌回 NAV;折價 < -門檻 → 做多。
    ⚠️ 只在申贖『開放』時進場——申贖受限的溢價可能永不收斂(原油正2 = 這裡爆的)。
    bar.extra 需含:nav、creation_open(bool)。
    風控:收斂就平、背離超過 stop 就砍(不凹單)。
    """
    def __init__(self, entry=0.02, exit=0.005, stop=0.06, size=1.0):
        self.entry, self.exit, self.stop, self.size = entry, exit, stop, size
        self.pos = 0

    def on_bar(self, bar: Bar) -> list[Signal]:
        nav = bar.extra.get("nav")
        if not nav:
            return []
        prem = bar.mid / nav - 1.0
        open_ = bar.extra.get("creation_open", False)
        if self.pos == 0:
            if not open_:
                return []                       # 申贖關閉 = 陷阱,不碰
            if prem > self.entry:
                self.pos = -1
                return [Signal(bar.symbol, -1, self.size, f"溢價 {prem:+.1%} 放空收斂")]
            if prem < -self.entry:
                self.pos = +1
                return [Signal(bar.symbol, +1, self.size, f"折價 {prem:+.1%} 做多收斂")]
        else:
            converged = abs(prem) < self.exit
            diverged = (self.pos < 0 and prem > self.stop) or (self.pos > 0 and prem < -self.stop)
            if converged or diverged:
                side = -self.pos
                reason = "收斂 平" if converged else "背離超停損 砍"
                self.pos = 0
                return [Signal(bar.symbol, side, self.size, reason)]
        return []
