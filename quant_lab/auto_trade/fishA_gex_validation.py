"""B:驗魚A 的 GEX 濾網能否隔離正 VRP + 縮小尾部(魚A 自己的尺=尾部感知,非勝率)。
比較:①只 IV-EWMA 濾(基準) ②+GEX≥中位(魚A 全規則) ③GEX<中位(對照組)。
重點指標=最大單筆虧損 + 最差5%均值(CVaR),不是勝率。
"""
import sys, statistics as st
sys.path.insert(0, ".")
import txo_data, tx_data
from txo_vol_wf import ewma_vol_by_date, straddle, POINT, SPREAD_PTS, FEE_PTS
from gex_study import build_gex


def simulate_filtered(dates, days, vols, gex, gmed, entry_thr=0.03, exit_thr=0.01,
                      max_days=5, stop_mult=1.5, gex_gate=None):
    """gex_gate: None=不濾, 'high'=只GEX≥中位, 'low'=只GEX<中位。回 trade_pnls(點)。"""
    pnls, held = [], None
    cost_rt = 4 * (SPREAD_PTS + FEE_PTS)
    for d in dates:
        rec = days[d]; rv = vols.get(d)
        if held:
            same = rec["contract"] == held["contract"]
            mark = straddle(rec, held["K"]) if same else None
            edge_now = (rec["atm_iv"] - rv) if rv else None
            held["age"] += 1
            stop = mark is not None and mark > held["entry_px"] * stop_mult
            if (not same) or mark is None or stop or held["age"] >= max_days or \
               (edge_now is not None and edge_now < exit_thr):
                exit_px = mark if mark is not None else held["last_mark"]
                pnls.append(held["entry_px"] - exit_px - cost_rt); held = None
            else:
                held["last_mark"] = mark
        if held is None and rv is not None:
            edge = rec["atm_iv"] - rv
            g = gex.get(d, {}).get("mag")
            gate_ok = (gex_gate is None or g is None) or \
                      (gex_gate == "high" and g >= gmed) or (gex_gate == "low" and g < gmed)
            if edge > entry_thr and 10 <= rec["dte"] <= 40 and gate_ok:
                px = straddle(rec, rec["atm_K"])
                if px:
                    held = {"contract": rec["contract"], "K": rec["atm_K"],
                            "entry_px": px, "last_mark": px, "age": 0}
    return pnls


def report(name, pnls):
    if not pnls:
        print(f"{name}: 0 筆"); return
    n = len(pnls); tot = sum(pnls) * POINT
    wr = sum(1 for x in pnls if x > 0) / n
    worst = min(pnls) * POINT
    tail_n = max(1, n // 20)
    cvar = sum(sorted(pnls)[:tail_n]) / tail_n * POINT   # 最差5%均值
    mean = st.mean(pnls) * POINT
    print(f"{name}: {n}筆 勝率{wr:.0%} 每筆均{mean:+,.0f}元 總{tot:+,.0f}元")
    print(f"       ⭐尾部:最大單筆虧損{worst:+,.0f}元  最差5%均值(CVaR){cvar:+,.0f}元  賺賠={'撐不住' if worst<-mean*n*0.5 else 'ok'}")


def main():
    days = txo_data.load("2023-01-01")
    vols = ewma_vol_by_date()
    gex = build_gex(days)
    dates = sorted(days)
    gmags = sorted(gex[d]["mag"] for d in dates if d in gex and gex[d].get("mag") is not None)
    gmed = gmags[len(gmags) // 2]
    print(f"樣本 {len(dates)} 天  GEX mag 中位={gmed:,.0f}\n")
    print("魚A 自己的尺:賣方勝率天生高,關鍵看『最大單筆虧損/CVaR 撐不撐得住』——\n")
    report("①基準(只IV-EWMA濾,裸賣)", simulate_filtered(dates, days, vols, gex, gmed, gex_gate=None))
    report("②+GEX≥中位(魚A全規則)", simulate_filtered(dates, days, vols, gex, gmed, gex_gate="high"))
    report("③GEX<中位(對照:行情沒被壓)", simulate_filtered(dates, days, vols, gex, gmed, gex_gate="low"))
    print("\n判定(魚A的尺):GEX濾網若把『最大單筆虧損/CVaR』明顯縮小=濾網真的隔離出被壓抑的尾部=魚A賭注成立;")
    print("           若筆數太少(<15)=無法判定,forward 累積前禁止放大;高勝率不能當通過條件。")


if __name__ == "__main__":
    main()
