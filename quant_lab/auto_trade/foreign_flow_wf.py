"""外資淨部位跟隨:正式三關(train 網格 → DSR → walk-forward → lockbox)。
⚠️ 誠實揭露:初篩(foreign_flow_study)已看過全樣本描述統計,lockbox 純度已折損;
此處 train-only 選門檻是最好的補救,但真正乾淨的裁決=7/21 起 paper 前測。
用法:python3 foreign_flow_wf.py
"""
import math

import tx_data
from foreign_flow_study import fetch_foreign, COST_PTS
from engine import sharpe, deflated_sharpe, split_lockbox, walk_forward

TX_POINT = 200


def build_deltas(bars, net_oi):
    deltas, prev = {}, None
    for b in bars:
        d = b["date"]
        if d in net_oi:
            if prev is not None:
                deltas[d] = net_oi[d] - prev
            prev = net_oi[d]
    return deltas


def trade(seg_bars, deltas, thr_abs):
    """T日|Δ|≥thr → T+1 開到收跟隨。回損益(點,含成本)。"""
    pnls = []
    for i in range(len(seg_bars) - 1):
        d = seg_bars[i]["date"]
        dl = deltas.get(d)
        if dl is None or dl == 0 or abs(dl) < thr_abs:
            continue
        b1 = seg_bars[i + 1]
        pnls.append((1 if dl > 0 else -1) * (b1["close"] - b1["open"]) - COST_PTS)
    return pnls


def q_threshold(seg_bars, deltas, q):
    mags = sorted(abs(deltas[b["date"]]) for b in seg_bars if b["date"] in deltas and deltas[b["date"]] != 0)
    if not mags:
        return 0
    return mags[min(int(len(mags) * q), len(mags) - 1)] if q > 0 else 0


def main():
    bars = tx_data.load("2020-01-01")
    deltas = build_deltas(bars, fetch_foreign())
    train, oos, lockbox = split_lockbox(bars)
    print(f"三關:train {len(train)} / oos {len(oos)} / lockbox {len(lockbox)}(門檻只從 train 算)\n")

    grid = [0.0, 0.5, 0.7, 0.85]
    scored = []
    for q in grid:
        thr = q_threshold(train, deltas, q)
        p = trade(train, deltas, thr)
        if len(p) >= 30:
            scored.append((q, thr, sharpe(p), len(p), sum(p)))
    print("train 網格(信念分位 → 門檻口數):")
    for q, thr, sh, n, tot in sorted(scored, key=lambda x: -x[2]):
        print(f"  q={q:.2f} (|Δ|≥{thr:,.0f}口)  Sharpe/筆={sh:+.3f}  n={n}  {tot*TX_POINT:+,.0f} 元/口")
    if not scored:
        print("樣本不足"); return
    bq, bthr, bsh, bn, _ = max(scored, key=lambda x: x[2])
    dsr = deflated_sharpe(bsh, len(grid), bn)
    print(f"\n最佳 q={bq}:DSR = P(真edge>0 | 試{len(grid)}套) = {dsr:.3f}")

    wf = []
    for ins, seg in walk_forward(oos, window=200, step=100):
        thr = q_threshold(ins, deltas, bq)          # 門檻隨窗滾動重算,只用過去
        wf += trade(seg, deltas, thr)
    print(f"walk-forward OOS:n={len(wf)},Sharpe/筆 {sharpe(wf):+.3f},{sum(wf)*TX_POINT:+,.0f} 元/口")

    thr_lb = q_threshold(train + oos, deltas, bq)   # lockbox 門檻用其之前全部資料
    lb = trade(lockbox, deltas, thr_lb)
    if lb:
        wr = sum(1 for x in lb if x > 0) / len(lb)
        print(f"lockbox(最終一次):n={len(lb)},Sharpe/筆 {sharpe(lb):+.3f},"
              f"{sum(lb)*TX_POINT:+,.0f} 元/口,勝率 {wr:.0%},最大單筆 {min(lb)*TX_POINT:+,.0f} 元")
    print("\n口徑:T日15:00後公布的外資Δ淨OI→T+1開到收,含成本1.5點,無前視;lockbox純度因初篩折損,真裁決=paper。")


if __name__ == "__main__":
    main()
