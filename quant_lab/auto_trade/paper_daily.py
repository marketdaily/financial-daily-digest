"""Paper 前測日跑器(winrig cron 每晚執行;僅 FinMind 免費源,不需 Shioaji):
- 魚B 外資高信念跟隨:|Δ淨OI|≥85分位(擴張窗,只用過去)→ 次日開→收,成本1.5點
- 魚A 條件賣跨式:IV−EWMA>3% 且 10≤dte≤40 且 GEX≥近60日中位 → 賣ATM跨式;
  出場=edge<1%/持有≥5天/mark>1.5×進場/換月,成本4.4點(價差+費稅雙腿來回)
狀態 .paper/state.json;帳本 .paper/ledger.jsonl(事件流,唯一真源)。
這是兩條魚的「真 OOS 裁決」:訊號規格 2026-07-17 凍結,不得再調參。
用法:python3 paper_daily.py
"""
import os
import json
import datetime

import tx_data
import txo_data
from foreign_flow_study import fetch_foreign
from gex_study import build_gex
from txo_vol_wf import ewma_vol_by_date, straddle

HERE = os.path.dirname(os.path.abspath(__file__))
PDIR = os.path.join(HERE, ".paper")
STATE = os.path.join(PDIR, "state.json")
LEDGER = os.path.join(PDIR, "ledger.jsonl")
COST_B = 1.5
COST_A = 4.4
TX_POINT, TXO_POINT = 200, 50


def log_ev(ev):
    ev["logged_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    print(" ", json.dumps(ev, ensure_ascii=False, default=str))


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fishB": {"pending": None}, "fishA": {"held": None}}


def main():
    os.makedirs(PDIR, exist_ok=True)
    st = load_state()
    bars = tx_data.load("2020-01-01", refresh=True)
    by_date = {b["date"]: b for b in bars}
    today = bars[-1]["date"]
    print(f"paper_daily @ {today}")

    # ---- 魚B:先結算,再產訊號 ----
    pend = st["fishB"]["pending"]
    if pend and today > pend["signal_date"]:
        b = bars[-1] if bars[-1]["date"] > pend["signal_date"] else None
        # 執行日=訊號日後第一個交易日(當前最後一根若比訊號日新,即為執行日)
        exec_bar = next((x for x in bars if x["date"] > pend["signal_date"]), None)
        if exec_bar:
            pnl = pend["side"] * (exec_bar["close"] - exec_bar["open"]) - COST_B
            log_ev({"fish": "B", "type": "fill+close", "signal_date": pend["signal_date"],
                    "exec_date": exec_bar["date"], "side": pend["side"],
                    "pnl_pts": round(pnl, 1), "pnl_ntd": round(pnl * TX_POINT)})
            st["fishB"]["pending"] = None
    net = fetch_foreign()
    ds = sorted(d for d in net if d in by_date)
    if ds and ds[-1] == today and st["fishB"]["pending"] is None:
        deltas = [net[ds[i]] - net[ds[i - 1]] for i in range(1, len(ds))]
        d_today = deltas[-1]
        hist = sorted(abs(x) for x in deltas[:-1] if x != 0)
        thr = hist[int(len(hist) * 0.85)] if hist else 0
        if d_today != 0 and abs(d_today) >= thr:
            st["fishB"]["pending"] = {"signal_date": today, "side": 1 if d_today > 0 else -1}
            log_ev({"fish": "B", "type": "signal", "date": today,
                    "delta_oi": d_today, "thr": round(thr), "side": st["fishB"]["pending"]["side"]})

    # ---- 魚A:先管持倉,再看進場 ----
    days = txo_data.load("2023-01-01")
    vols = ewma_vol_by_date()
    gex = build_gex(days)
    held = st["fishA"]["held"]
    if today in days:
        rec = days[today]
        rv = vols.get(today)
        edge = (rec["atm_iv"] - rv) if rv else None
        if held:
            same = rec["contract"] == held["contract"]
            mark = straddle(rec, held["K"]) if same else None
            held["age"] += 1
            reason = None
            if not same or mark is None:
                reason, exit_px = "roll", held["last_mark"]
            elif mark > held["entry_px"] * 1.5:
                reason, exit_px = "stop", mark
            elif held["age"] >= 5:
                reason, exit_px = "timeout", mark
            elif edge is not None and edge < 0.01:
                reason, exit_px = "converged", mark
            if reason:
                pnl = held["entry_px"] - exit_px - COST_A
                log_ev({"fish": "A", "type": "exit", "reason": reason, "date": today,
                        "entry": held["entry_px"], "exit": exit_px,
                        "pnl_pts": round(pnl, 1), "pnl_ntd": round(pnl * TXO_POINT)})
                st["fishA"]["held"] = None
            else:
                held["last_mark"] = mark
                log_ev({"fish": "A", "type": "mark", "date": today, "mark": mark,
                        "u_pnl_pts": round(held["entry_px"] - mark, 1), "age": held["age"]})
        if st["fishA"]["held"] is None and edge is not None:
            gs = sorted(gex[d]["mag"] for d in sorted(gex)[-60:])
            g_med = gs[len(gs) // 2]
            if edge > 0.03 and 10 <= rec["dte"] <= 40 and gex[today]["mag"] >= g_med:
                px = straddle(rec, rec["atm_K"])
                if px:
                    st["fishA"]["held"] = {"contract": rec["contract"], "K": rec["atm_K"],
                                           "entry_px": px, "last_mark": px, "age": 0,
                                           "entry_date": today}
                    log_ev({"fish": "A", "type": "entry", "date": today, "K": rec["atm_K"],
                            "straddle_px": px, "iv": rec["atm_iv"], "edge": round(edge, 3),
                            "dte": rec["dte"]})
    else:
        print("  魚A:今日 TXO 資料尚未可得(FinMind 更新中),下次補")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, default=str)

    # ---- 累計摘要 ----
    try:
        evs = [json.loads(l) for l in open(LEDGER, encoding="utf-8")]
        for fish in ("A", "B"):
            pnls = [e["pnl_ntd"] for e in evs if e.get("fish") == fish and "pnl_ntd" in e]
            if pnls:
                wr = sum(1 for x in pnls if x > 0) / len(pnls)
                print(f"  魚{fish} 累計:{len(pnls)}筆 {sum(pnls):+,} 元 勝率 {wr:.0%}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # FinMind 限流/網路瞬斷等:不炸 cron,明天自然補跑(魚B結算用「訊號日後第一根」不會漏)
        print(f"paper_daily 跳過本次:{type(e).__name__} {e}")
