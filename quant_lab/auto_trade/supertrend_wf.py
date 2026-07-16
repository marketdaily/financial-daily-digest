"""SuperTrend 在真實台指期日線上的誠實驗證:train 網格 → DSR → walk-forward → lockbox。
成本口徑:TX 一點 NT$200;spread 0.5 點 + 滑價 0.5bp + 費稅 0.3bp/邊(手續費+期交稅)。
用法:python3 supertrend_wf.py [--start 2020-01-01]
"""
import argparse

import tx_data
from engine import (Bar, DataAdapter, Engine, Mode, FillModel,
                    sharpe, deflated_sharpe, split_lockbox, walk_forward)
from strategies import SuperTrend

POINT_VALUE = 200  # NT$/點


class TXAdapter(DataAdapter):
    def __init__(self, rows, spread_pts=0.5):
        self.rows, self.half = rows, spread_pts / 2

    def stream(self):
        for i, r in enumerate(self.rows):
            c = r["close"]
            yield Bar(t=i, symbol="TX", bid=c - self.half, ask=c + self.half, last=c,
                      extra={"high": r["high"], "low": r["low"], "date": r["date"]})


def bt(rows, period, mult):
    eng = Engine(SuperTrend(period, mult), TXAdapter(rows), Mode.BACKTEST,
                 fill_model=FillModel(slippage_bps=0.5), fee_bps=0.3)
    return eng.run()["trade_pnls"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    a = ap.parse_args()
    rows = tx_data.load(a.start)
    train, oos, lockbox = split_lockbox(rows)
    print(f"台指期連續近月日線 {len(rows)} 根({rows[0]['date']} → {rows[-1]['date']})")
    print(f"切分:train {len(train)} / oos {len(oos)} / lockbox {len(lockbox)}(絕不看,最後一次)\n")

    grid = [(p, m) for p in (7, 10, 14, 21) for m in (1.5, 2.0, 2.5, 3.0)]
    scored = []
    for p, m in grid:
        pnls = bt(train, p, m)
        if len(pnls) >= 15:
            scored.append(((p, m), sharpe(pnls), len(pnls), sum(pnls)))
    scored.sort(key=lambda x: -x[1])
    print(f"train 網格 {len(grid)} 套(至少15筆交易者 {len(scored)} 套),前3名:")
    for (p, m), sh, n, tot in scored[:3]:
        print(f"  period={p:>2} mult={m}  Sharpe/筆={sh:+.3f}  {n}筆  總損益 {tot*POINT_VALUE:+,.0f} 元/口")
    (bp, bm), bsh, bn, btot = scored[0]
    dsr = deflated_sharpe(bsh, len(grid), bn)
    print(f"\n最佳 (period={bp}, mult={bm}):DSR = P(真edge>0 | 試{len(grid)}套) = {dsr:.3f}")

    warm = 60
    wf = []
    for ins, seg in walk_forward(oos, window=200, step=100):
        wf += bt(ins[-warm:] + seg, bp, bm)
    print(f"walk-forward OOS:{len(wf)} 筆,Sharpe/筆 {sharpe(wf):+.3f},總損益 {sum(wf)*POINT_VALUE:+,.0f} 元/口")

    lb = bt(oos[-warm:] + lockbox, bp, bm)
    print(f"lockbox(最終一次):{len(lb)} 筆,Sharpe/筆 {sharpe(lb):+.3f},總損益 {sum(lb)*POINT_VALUE:+,.0f} 元/口")
    wr = sum(1 for x in lb if x > 0) / len(lb) if lb else 0
    print(f"                 勝率 {wr:.0%},單口最大單筆虧損 {min(lb)*POINT_VALUE:+,.0f} 元" if lb else "")
    print("\n口徑:日K收盤成交(含輕微同根look-ahead)、換月未回溯調整、單口、成本已含價差/滑價/費稅。")


if __name__ == "__main__":
    main()
