"""TXO 裸賣跨式(short straddle)真資料誠實驗證:train 網格 → DSR → walk-forward → lockbox。

交易模擬(誠實口徑):
- 進場:ATM IV − EWMA 已實現波動 > entry_thr 且 dte ∈ [min_dte+2, 40] → 賣出「當天那組
  真實 ATM 跨式」(記下 contract/K/兩腿市價)
- 持有:之後每天用**同一張合約、同一 K** 的真實市價 mark(txo_data 存了 ±8% 窗)
- 出場:edge < exit_thr、持有 > max_days、跨式市價 > 進場價 × stop_mult(停損)、
  或近月換倉(資料窗盡頭)→ 用最後可得市價強制出場
- 成本:每腿每邊過半價差 spread_pts/2 + 每腿費稅 fee_pts;跨式來回共 4 腿邊
- ⚠️ 無 delta 對沖(裸賣);Shioaji 上線後可加期貨對沖腿再驗一次
損益單位:點 × NT$50(TXO 每點 50 元)。
用法:python3 txo_vol_wf.py
"""
import math
import argparse

import txo_data
import tx_data
from engine import sharpe, deflated_sharpe, split_lockbox, walk_forward

POINT = 50            # NT$/點
SPREAD_PTS = 0.6      # 每腿單邊過半價差(ATM 近月約 0.5~1 點的一半,取保守)
FEE_PTS = 0.5         # 每腿單邊手續費+期交稅(約 NT$25/50)


def ewma_vol_by_date(lam=0.94):
    rows = tx_data.load("2020-01-01")
    out, var = {}, None
    prev = None
    for r in rows:
        c = r["close"]
        if prev:
            ret = math.log(c / prev)
            var = ret * ret if var is None else lam * var + (1 - lam) * ret * ret
            out[r["date"]] = math.sqrt(var * 252)
        prev = c
    return out


def _px(v):
    return v["px"] if isinstance(v, dict) else v


def straddle(day_rec, K):
    s = day_rec["strikes"].get(str(K))
    if not s or "C" not in s or "P" not in s:
        return None
    return _px(s["C"]) + _px(s["P"])


def simulate(dates, days, vols, entry_thr, exit_thr, max_days, stop_mult):
    """回傳 trade_pnls(點,已扣成本)。一次只持一組跨式。"""
    pnls, held = [], None
    cost_rt = 4 * (SPREAD_PTS + FEE_PTS)      # 跨式來回 4 腿邊
    for d in dates:
        rec = days[d]
        rv = vols.get(d)
        if held:
            same = rec["contract"] == held["contract"]
            mark = straddle(rec, held["K"]) if same else None
            edge_now = (rec["atm_iv"] - rv) if rv else None
            held["age"] += 1
            stop = mark is not None and mark > held["entry_px"] * stop_mult
            timeout = held["age"] >= max_days
            converged = edge_now is not None and edge_now < exit_thr
            if (not same) or mark is None or stop or timeout or converged:
                exit_px = mark if mark is not None else held["last_mark"]
                pnls.append(held["entry_px"] - exit_px - cost_rt)
                held = None
            else:
                held["last_mark"] = mark
        if held is None and rv is not None:
            edge = rec["atm_iv"] - rv
            if edge > entry_thr and rec["dte"] >= 10 and rec["dte"] <= 40:
                px = straddle(rec, rec["atm_K"])
                if px:
                    held = {"contract": rec["contract"], "K": rec["atm_K"],
                            "entry_px": px, "last_mark": px, "age": 0}
    return pnls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    a = ap.parse_args()
    days = txo_data.load(a.start)
    vols = ewma_vol_by_date()
    dates = sorted(days)
    print(f"TXO 近月 ATM IV 日資料 {len(dates)} 天({dates[0]} → {dates[-1]})")
    with_rv = [d for d in dates if d in vols]
    edges = [days[d]["atm_iv"] - vols[d] for d in with_rv]
    pos = sum(1 for e in edges if e > 0)
    print(f"IV−EWMA 溢酬:平均 {sum(edges)/len(edges):+.1%},為正比例 {pos/len(edges):.0%} ← 波動率風險溢酬存在性\n")

    train, oos, lockbox = split_lockbox(dates)
    grid = [(et, md, sm) for et in (0.03, 0.05, 0.07) for md in (5, 10) for sm in (1.5, 2.0)]
    scored = []
    for et, md, sm in grid:
        p = simulate(train, days, vols, et, 0.01, md, sm)
        if len(p) >= 10:
            scored.append(((et, md, sm), sharpe(p), len(p), sum(p)))
    if not scored:
        print("train 上沒有參數組達到最少交易數,無法評估。")
        return
    scored.sort(key=lambda x: -x[1])
    print(f"train 網格 {len(grid)} 套(≥10筆者 {len(scored)} 套),前3名:")
    for (et, md, sm), sh, n, tot in scored[:3]:
        print(f"  entry={et:.0%} max_hold={md}d stop={sm}x  Sharpe/筆={sh:+.3f}  {n}筆  {tot*POINT:+,.0f} 元/組")
    (bet, bmd, bsm), bsh, bn, _ = scored[0]
    dsr = deflated_sharpe(bsh, len(grid), bn)
    print(f"\n最佳:DSR = P(真edge>0 | 試{len(grid)}套) = {dsr:.3f}")

    wf = []
    for ins, seg in walk_forward(oos, window=120, step=60):
        wf += simulate(ins[-15:] + seg, days, vols, bet, 0.01, bmd, bsm)
    print(f"walk-forward OOS:{len(wf)} 筆,Sharpe/筆 {sharpe(wf):+.3f},{sum(wf)*POINT:+,.0f} 元/組")

    lb = simulate(oos[-15:] + lockbox, days, vols, bet, 0.01, bmd, bsm)
    if lb:
        wr = sum(1 for x in lb if x > 0) / len(lb)
        print(f"lockbox(最終一次):{len(lb)} 筆,Sharpe/筆 {sharpe(lb):+.3f},{sum(lb)*POINT:+,.0f} 元/組,"
              f"勝率 {wr:.0%},最大單筆 {min(lb)*POINT:+,.0f} 元")
    print("\n口徑:裸賣跨式無delta對沖、同合約同K真實市價mark、成本含價差/費稅、單組。")
    print("⚠️ 短vol=撿壓路機銅板:勝率高但尾巴肥,單筆最大虧損才是重點,別只看勝率。")


if __name__ == "__main__":
    main()
