"""跑一次證明:同一份策略程式碼 → backtest。
展示四道紀律:成交成本(價差+滑價+手續費)、walk-forward、lockbox、DSR 打折。
真接 Shioaji 前,先用合成資料證明骨架會跑、而且不會騙自己。
"""
import math

from engine import (Bar, Signal, Strategy, DataAdapter, Engine, Mode,
                    sharpe, deflated_sharpe, split_lockbox, walk_forward)


def synth_series(n=1500, seed=7, spread=0.15):
    """合成:一個溫和均值回歸的價格 + 買賣價差。無 numpy,LCG 自製亂數(可重現)。"""
    x, bars = 100.0, []
    s = seed
    for t in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        u = s / 0x7FFFFFFF - 0.5
        x += -0.05 * (x - 100.0) + 0.8 * u        # OU 均值回歸
        bars.append(Bar(t=t, symbol="DEMO", bid=x - spread / 2, ask=x + spread / 2, last=x))
    return bars


class ListAdapter(DataAdapter):
    def __init__(self, bars):
        self.bars = bars

    def stream(self):
        yield from self.bars


class MeanRevert(Strategy):
    """z-score 均值回歸:低買高賣。參數 lookback / entry_z 是要被 walk-forward 驗的東西。"""
    def __init__(self, lookback=50, entry_z=1.0, size=1.0):
        self.lb, self.z_in, self.size = lookback, entry_z, size
        self.win: list[float] = []
        self.pos = 0

    def on_bar(self, bar: Bar) -> list[Signal]:
        self.win.append(bar.mid)
        if len(self.win) > self.lb:
            self.win.pop(0)
        if len(self.win) < self.lb:
            return []
        m = sum(self.win) / self.lb
        var = sum((v - m) ** 2 for v in self.win) / (self.lb - 1)
        sd = math.sqrt(var) if var > 0 else 1e-9
        z = (bar.mid - m) / sd
        sigs = []
        if self.pos == 0 and z < -self.z_in:
            sigs.append(Signal("DEMO", +1, self.size, f"z={z:.2f} 進"))
            self.pos = 1
        elif self.pos == 0 and z > self.z_in:
            sigs.append(Signal("DEMO", -1, self.size, f"z={z:.2f} 進"))
            self.pos = -1
        elif self.pos != 0 and abs(z) < 0.2:
            sigs.append(Signal("DEMO", -self.pos, self.size, "回均值 平"))
            self.pos = 0
        return sigs


def bt(bars, **params):
    r = Engine(MeanRevert(**params), ListAdapter(bars), Mode.BACKTEST).run()
    return r["trade_pnls"]


def main():
    bars = synth_series()
    train, oos, lockbox = split_lockbox(bars)
    print(f"資料切分:train {len(train)} / oos {len(oos)} / lockbox {len(lockbox)}(絕不看,最後才跑)\n")

    # —— 在 train 上「試很多套參數挑最好」:這正是製造過度擬合的動作 ——
    grid = [(lb, z) for lb in (20, 35, 50, 65, 80) for z in (0.8, 1.0, 1.2, 1.5)]
    scored = []
    for lb, z in grid:
        pnls = bt(train, lookback=lb, entry_z=z)
        scored.append(((lb, z), sharpe(pnls), len(pnls)))
    scored.sort(key=lambda x: -x[1])
    (best_lb, best_z), best_sh, best_n = scored[0]
    n_trials = len(grid)
    print(f"在 train 上試了 {n_trials} 套參數,挑出最好:lookback={best_lb} entry_z={best_z}")
    print(f"  train 上的 Sharpe = {best_sh:.3f}  ← 看起來很棒,但這是『挑出來的』")
    dsr = deflated_sharpe(best_sh, n_trials, best_n)
    print(f"  DSR = P(真 edge>0 | 試了{n_trials}套) = {dsr:.3f}  ← <0.5 就很可能是運氣挑出來的\n")

    # —— walk-forward:每段 OOS 只評一次 ——
    # 前置 lookback 根暖機 bar(取自 in-sample 尾端):指標窗剛好在 OOS 第一根填滿,
    # 訊號從 OOS 開始產生,不浪費 OOS 樣本、也不偷看 OOS 之後的資料。
    wf_pnls = []
    for ins, oos_seg in walk_forward(oos, window=200, step=100):
        wf_pnls += bt(ins[-best_lb:] + oos_seg, lookback=best_lb, entry_z=best_z)
    print(f"walk-forward OOS:{len(wf_pnls)} 筆交易,Sharpe = {sharpe(wf_pnls):.3f}")

    # —— lockbox:最後只跑這一次 ——
    lb_pnls = bt(lockbox, lookback=best_lb, entry_z=best_z)
    print(f"lockbox 最終一次:{len(lb_pnls)} 筆,總損益(已扣價差+滑價+手續費) = {sum(lb_pnls):.3f}")
    print(f"                Sharpe = {sharpe(lb_pnls):.3f}")
    print("\n>>> 重點:train 的漂亮 Sharpe vs DSR/OOS/lockbox 的落差,就是『自欺 vs 真實』的差距。")
    print("    成交成本(價差+滑價)已內建 → 你看到的是實盤等級的損益,不是中價幻覺。")


if __name__ == "__main__":
    main()
