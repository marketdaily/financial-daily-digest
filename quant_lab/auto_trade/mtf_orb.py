"""用戶哲學的可測版本:「看長做短、一天一單、贏大輸小」。
- 看長:日線 EMA 排列閘(9>21>50 只做多、50>21>9 只做空、糾結不交易;只用昨日以前資料)
- 做短:開盤區間(OR)突破,只順日線方向進,一天最多一單
- 贏大輸小:停損=OR 另一側(小);沒被掃就抱到 13:44(讓贏單跑完整天)
成本 1.5 點/來回。三關:train 選 OR 窗長 → DSR → oos → lockbox。
用法:python3 mtf_orb.py
"""
import math
from collections import defaultdict

import tx_data
import intraday_data
from engine import sharpe, deflated_sharpe

COST = 1.5
TX_POINT = 200


def daily_gate():
    """date → +1/-1/0(用截至前一日收盤的 EMA9/21/50 排列,無前視)。"""
    bars = tx_data.load("2020-01-01")
    closes = [(b["date"], b["close"]) for b in bars]
    emas = {}
    state = {}
    for n in (9, 21, 50):
        e = None
        k = 2 / (n + 1)
        seq = {}
        for d, c in closes:
            e = c if e is None else c * k + e * (1 - k)
            seq[d] = e
        emas[n] = seq
    gate = {}
    for i in range(1, len(closes)):
        d_prev, d = closes[i - 1][0], closes[i][0]
        e9, e21, e50 = emas[9][d_prev], emas[21][d_prev], emas[50][d_prev]
        gate[d] = 1 if e9 > e21 > e50 else (-1 if e9 < e21 < e50 else 0)
    return gate


def run(days_bars, gate, or_min):
    """回 per-trade pnl(點,含成本)。days_bars: {date:[(hm,o,h,l,c)…]}"""
    pnls = []
    for d in sorted(days_bars):
        g = gate.get(d.isoformat(), 0)
        if g == 0:
            continue
        rows = days_bars[d]
        if len(rows) < or_min + 5:
            continue
        orh = max(x[2] for x in rows[:or_min])
        orl = min(x[3] for x in rows[:or_min])
        pos = 0
        entry = stop = 0.0
        for hm, o, h, l, c in rows[or_min:]:
            if pos == 0:
                if hm >= "13:30":            # 太晚不進(避開強平窗)
                    break
                if g > 0 and c > orh:
                    pos, entry, stop = 1, c, orl
                elif g < 0 and c < orl:
                    pos, entry, stop = -1, c, orh
                continue
            if (pos > 0 and l <= stop) or (pos < 0 and h >= stop):
                pnls.append(pos * (stop - entry) - COST)   # 輸小:OR 另一側停損
                pos = 0
                break
            if hm >= "13:44":
                pnls.append(pos * (c - entry) - COST)      # 贏大:抱到尾盤前
                pos = 0
                break
        if pos != 0:                                        # 資料尾端保護
            pnls.append(pos * (rows[-1][4] - entry) - COST)
    return pnls


def main():
    bars = intraday_data.load(day_session_only=True)
    days_bars = defaultdict(list)
    for t, o, h, l, c, v in bars:
        days_bars[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    gate = daily_gate()
    dates = sorted(days_bars)
    n = len(dates)
    d_tr, d_oos = dates[int(n * .6)], dates[int(n * .85)]
    tradable = sum(1 for d in dates if gate.get(d.isoformat(), 0) != 0)
    print(f"{n} 天;日線閘放行 {tradable} 天({tradable/n:.0%});train→{d_tr}|oos→{d_oos}\n")

    grid = [15, 30, 60]
    seg = lambda lo, hi: {d: v for d, v in days_bars.items() if lo <= d < hi}
    import datetime
    far = datetime.date(2099, 1, 1)
    scored = []
    for orm in grid:
        p = run(seg(dates[0], d_tr), gate, orm)
        if len(p) >= 20:
            wins = [x for x in p if x > 0]
            losses = [x for x in p if x <= 0]
            rr = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else 0
            scored.append((orm, sharpe(p), len(p), sum(p), rr))
    for orm, sh, cnt, tot, rr in sorted(scored, key=lambda x: -x[1]):
        print(f"  OR{orm}分: Sharpe/筆 {sh:+.3f}  {cnt}筆  {tot*TX_POINT:+,.0f} 元/口  盈虧比 {rr:.1f}")
    if not scored:
        print("樣本不足")
        return
    borm, bsh, bn, _, _ = max(scored, key=lambda x: x[1])
    print(f"\n最佳 OR{borm}分:DSR = {deflated_sharpe(bsh, len(grid), bn):.3f}")
    for label, lo, hi in [("oos", d_tr, d_oos), ("lockbox", d_oos, far)]:
        p = run(seg(lo, hi), gate, borm)
        if p:
            wr = sum(1 for x in p if x > 0) / len(p)
            wins = [x for x in p if x > 0]; losses = [x for x in p if x <= 0]
            rr = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else 0
            print(f"{label:>8}: n={len(p)} 均 {sum(p)/len(p):+.1f} 點 勝率 {wr:.0%} 盈虧比 {rr:.1f} "
                  f"總 {sum(p)*TX_POINT:+,.0f} 元/口")


if __name__ == "__main__":
    main()
