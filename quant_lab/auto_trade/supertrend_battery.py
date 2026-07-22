"""SuperTrend 日內 battery:零售流行預設整批過三關(公司同事策略型的可程式化替身)。
網格:timeframe {5,15,30,60}分 × period {7,10,14,21} × mult {1.5,2,3} = 48 套。
規則:日盤內翻多翻空,13:44 強制平倉(採納的免費執行規則),成本 1.5 點/來回。
指標跨日連續計算(隔夜跳空在序列裡,標準做法)。三關:train 選 → DSR(48) → oos → lockbox。
用法:python3 supertrend_battery.py
"""
import math
from collections import defaultdict

import intraday_data
from engine import sharpe, deflated_sharpe

COST = 1.5
TX_POINT = 200


def resample(bars, n_min):
    """1分K(結束標籤)→ N分K,日盤內對齊。回 [(date, end_hm, o, h, l, c)]"""
    by_day = defaultdict(list)
    for t, o, h, l, c, v in bars:
        by_day[t.date()].append((t, o, h, l, c))
    out = []
    for d in sorted(by_day):
        rows = by_day[d]
        for i in range(0, len(rows), n_min):
            ch = rows[i:i + n_min]
            out.append((d, ch[-1][0].strftime("%H:%M"), ch[0][1],
                        max(x[2] for x in ch), min(x[3] for x in ch), ch[-1][4]))
    return out


def run_st(nbars, period, mult):
    """SuperTrend 翻倉+13:44 強平。回 per-trade pnl(點,含成本)。"""
    atr = None
    prev_close = None
    fu = fl = None
    trend = 0
    pos = 0
    entry = 0.0
    pnls = []
    cur_day = None
    for day, hm, o, h, l, c in nbars:
        if cur_day != day:
            cur_day = day
        pc = prev_close if prev_close is not None else c
        tr = max(h - l, abs(h - pc), abs(l - pc))
        atr = tr if atr is None else (atr * (period - 1) + tr) / period
        prev_close = c
        mid = (h + l) / 2
        bu, bl = mid + mult * atr, mid - mult * atr
        fu = bu if (fu is None or bu < fu or pc > fu) else fu
        fl = bl if (fl is None or bl > fl or pc < fl) else fl
        new = trend
        if c > fu:
            new = 1
        elif c < fl:
            new = -1
        eod = hm >= "13:44"
        if pos != 0 and (eod or (new != trend and new != 0)):
            pnls.append(pos * (c - entry) - COST)
            pos = 0
        if new != trend and new != 0:
            trend = new
        if pos == 0 and not eod and trend != 0 and new == trend:
            pos, entry = trend, c
    return pnls


def main():
    bars = intraday_data.load(day_session_only=True)
    dates = sorted({b[0].date() for b in bars})
    n = len(dates)
    d_train, d_oos = dates[int(n * .6)], dates[int(n * .85)]
    print(f"{n} 個交易日;train→{d_train} | oos→{d_oos} | lockbox 之後\n")

    grid = [(tf, p, m) for tf in (5, 15, 30, 60) for p in (7, 10, 14, 21) for m in (1.5, 2.0, 3.0)]
    cache = {tf: resample(bars, tf) for tf in (5, 15, 30, 60)}

    def seg(nb, lo, hi):
        return [x for x in nb if lo <= x[0] < hi]

    import datetime
    far = datetime.date(2099, 1, 1)
    scored = []
    for tf, p, m in grid:
        pnls = run_st(seg(cache[tf], dates[0], d_train), p, m)
        if len(pnls) >= 30:
            scored.append(((tf, p, m), sharpe(pnls), len(pnls), sum(pnls)))
    scored.sort(key=lambda x: -x[1])
    print(f"train 網格 {len(grid)} 套(≥30筆者 {len(scored)}),前5:")
    for (tf, p, m), sh, cnt, tot in scored[:5]:
        print(f"  {tf}分 p={p} m={m}: Sharpe/筆 {sh:+.3f}  {cnt}筆  {tot*TX_POINT:+,.0f} 元/口")
    if not scored:
        print("全部樣本不足")
        return
    (btf, bp, bm), bsh, bn, _ = scored[0]
    print(f"\n最佳 {btf}分 p={bp} m={bm}:DSR = {deflated_sharpe(bsh, len(grid), bn):.3f}")

    for label, lo, hi in [("oos", d_train, d_oos), ("lockbox", d_oos, far)]:
        pnls = run_st(seg(cache[btf], lo, hi), bp, bm)
        if pnls:
            wr = sum(1 for x in pnls if x > 0) / len(pnls)
            print(f"{label:>8}: n={len(pnls)} 均 {sum(pnls)/len(pnls):+.1f} 點 勝率 {wr:.0%} "
                  f"Sharpe/筆 {sharpe(pnls):+.3f} 總 {sum(pnls)*TX_POINT:+,.0f} 元/口")


if __name__ == "__main__":
    main()
