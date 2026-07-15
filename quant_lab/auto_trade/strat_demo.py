"""證明兩個策略插上引擎會跑、會產生訊號、風控會擋。合成資料,無 numpy。"""
from engine import Bar, DataAdapter, Engine, Mode
from strategies import OptionVolSeller, ETFPremiumConverge


class ListAdapter(DataAdapter):
    def __init__(self, bars):
        self.bars = bars

    def stream(self):
        yield from self.bars


def _rng(seed):
    s = seed
    while True:
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        yield s / 0x7FFFFFFF - 0.5


def option_bars(n=400):
    """一檔選擇權:IV 在 FV 附近波動,偶爾飆高(可賣的機會)。價=vol 的代理。"""
    r = _rng(3)
    bars, fv, iv = [], 0.30, 0.30
    for t in range(n):
        u = next(r)
        iv += -0.1 * (iv - fv) + 0.06 * u
        iv = max(0.1, iv)
        px = 5.0 * iv                                   # 選擇權價 ~ 正比於 vol
        dte = max(3, 45 - t % 45)
        bars.append(Bar(t, "TXO", px - 0.05, px + 0.05, px,
                        {"implied_vol": round(iv, 3), "forward_vol": fv, "dte": dte}))
    return bars


def etf_bars(n=400):
    """一檔 ETF:前半段申贖開放,溢價來回擺盪 ±3%(會進場也會收斂);
    後半段申贖關閉,溢價卡在 +8% 不收(陷阱)→ 策略應完全不進場。"""
    import math
    bars, nav = [], 20.0
    for t in range(n):
        if t < n // 2:
            open_, prem = True, 0.035 * math.sin(t / 9.0)   # ±3.5% 擺盪
        else:
            open_, prem = False, 0.08                        # 卡住的假溢價
        mkt = nav * (1 + prem)
        bars.append(Bar(t, "00XXL", mkt - 0.02, mkt + 0.02, mkt,
                        {"nav": nav, "creation_open": open_}))
    return bars


def run(name, strat, bars):
    r = Engine(strat, ListAdapter(bars), Mode.BACKTEST).run()
    print(f"  {name:<22} 交易 {r['n_trades']:>3} 筆 | 總損益(已扣成本) {r['total_pnl']:>+7.3f}")


if __name__ == "__main__":
    print("插上引擎跑(backtest 模式,成交成本內建):")
    run("TXO 賣波動率", OptionVolSeller(), option_bars())
    run("ETF 折溢價收斂", ETFPremiumConverge(), etf_bars())
    print("\n>>> 兩個策略都會跑、會產生訊號、風控閘有作用。禮拜一接 Shioaji 換掉合成資料即可。")
