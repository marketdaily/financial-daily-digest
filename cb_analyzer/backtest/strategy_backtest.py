"""CBAS 策略 EV 回測:判定閘門(p_floor≥0.35)到底有沒有在分好壞交易。
每月每檔 × OTM∈{10%,30%,50%} 開一筆合成 CBAS 部位(權利金=理論值+融資=按合理價買),
機械出場:①盤中觸及「內在價值=2×權利金」股價 → +100% 出場(保守:實際含時間價值更早)
②否則抱到期:P&L=max(parity−strike,0)−權利金,下檔以權利金為限。
看 p_floor 分桶的 EV 排序力 + 新舊 gate 對照。月 cluster bootstrap CI。"""
import os
import sys
import json
import math
import csv
import bisect
import datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import cb_core
import cb_ledger
from cb_data import _ann_vol, _ewma_vol, blend_vol
from calib_backtest import load_with_adj, month_starts

OTMS = (0.10, 0.30, 0.50)   # 10%=新發;30/50%=發行後股價下跌的深價外(群聯三/宜鼎二型)
T_OPT = 2.6
STRIKE = 100.0
TCRI = 4
FIN_SPREAD = cb_core.ASSUMPTIONS["asset_swap_spread"]


def simulate_one(s0, vol, otm, acloses, ahighs, ai, aj):
    K = s0 * (1 + otm)
    shares = 100.0 / K
    floor = STRIKE / ((1 + cb_core.credit_rate(TCRI)) ** T_OPT)
    call_px = cb_core.bs_call(s0, K, T_OPT, vol, cb_core.ASSUMPTIONS["rf"])[0]
    premium = shares * call_px + floor * FIN_SPREAD * T_OPT
    if premium <= 0.5:
        return None
    be_S = K * (STRIKE + premium) / 100.0
    dbl_S = K * (STRIKE + 2 * premium) / 100.0
    win_highs = ahighs[ai + 1:aj]
    if not win_highs:
        return None
    if any(h >= dbl_S for h in win_highs):
        ret, dbl = 1.0, 1
    else:
        sT = acloses[aj - 1]
        ret, dbl = (max(sT / K * 100.0 - STRIKE, 0.0) - premium) / premium, 0
    p_raw = cb_core.touch_prob(s0, be_S, T_OPT, vol, 0.07)
    cal = cb_ledger.calibrate_touch(p_raw, s0, be_S, T_OPT, vol)
    return {"otm": otm, "premium": round(premium, 2), "ret": round(ret, 4),
            "p_raw": round(p_raw, 4), "p_cal": round(cal["p"], 4),
            "p_floor": round(cal["floor"], 4) if cal.get("floor") else None,
            "touched_dbl": dbl}


def main():
    db = json.load(open(os.path.join(HERE, "..", "cb_database.json")))
    codes = sorted({it.get("stock_code") for it in db["items"] if it.get("stock_code")})
    out = []
    for code in codes:
        pair = load_with_adj(code)
        if not pair or len(pair[0]) < 300:
            continue
        unadj, adj = pair
        udates = [d for d, _, _ in unadj]
        ucloses = [c for _, c, _ in unadj]
        adates = [d for d, _, _ in adj]
        acloses = [c for _, c, _ in adj]
        ahighs = [h for _, _, h in adj]
        last = adates[-1]
        for i in month_starts(udates):
            t = udates[i]
            end = (datetime.date.fromisoformat(t)
                   + datetime.timedelta(days=int(T_OPT * 365.25))).isoformat()
            if end > last:
                continue
            cutoff = (datetime.date.fromisoformat(t) - datetime.timedelta(days=400)).isoformat()
            j0 = bisect.bisect_left(udates, cutoff)
            px = ucloses[j0:i + 1]
            if len(px) < 130:
                continue
            rets = [math.log(px[k] / px[k - 1]) for k in range(1, len(px)) if px[k - 1] > 0]
            vols = {"v20": _ann_vol(rets[-20:]), "v60": _ann_vol(rets[-60:]),
                    "v120": _ann_vol(rets[-120:]),
                    "ewma": _ewma_vol(rets[-120:] if len(rets) >= 120 else rets)}
            vol, _ = blend_vol(vols)
            if not vol or vol <= 0:
                continue
            ai = bisect.bisect_left(adates, t)
            if ai >= len(adates) or adates[ai] != t:
                continue
            aj = bisect.bisect_right(adates, end)
            for otm in OTMS:
                r = simulate_one(acloses[ai], vol, otm, acloses, ahighs, ai, aj)
                if r:
                    r.update({"code": code, "date": t})
                    out.append(r)
    with open(os.path.join(HERE, "strategy_rows.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} positions")

    def stats(rs, lbl):
        if not rs:
            print(f"{lbl}: n=0")
            return
        r = np.array([x["ret"] for x in rs])
        months = {}
        for x in rs:
            months.setdefault(x["date"][:7], []).append(x["ret"])
        keys = list(months)
        rng = np.random.default_rng(11)
        means = []
        for _ in range(1000):
            pick = rng.choice(len(keys), size=len(keys), replace=True)
            means.append(np.mean([v for k in pick for v in months[keys[k]]]))
        means.sort()
        print(f"{lbl}: n={len(rs)} EV={r.mean()*100:+.1f}% (月CI[{means[25]*100:+.1f},{means[974]*100:+.1f}]) "
              f"中位={np.median(r)*100:+.1f}% 勝率={np.mean(r > 0)*100:.0f}% 翻倍率={np.mean([x['touched_dbl'] for x in rs])*100:.0f}%")

    for otm in OTMS:
        sub = [x for x in out if x["otm"] == otm]
        print(f"\n== OTM {otm*100:.0f}% ==")
        stats(sub, " 全部")
        ok = [x for x in sub if x["p_floor"] is not None]
        stats([x for x in ok if x["p_floor"] >= 0.35], " v4下限gate 核准")
        stats([x for x in ok if x["p_floor"] < 0.35], " v4下限gate 拒絕")
        stats([x for x in sub if x["p_raw"] < 0.35], " 舊GBM會勸退的(對照)")
    print("\n== p_floor 分桶 EV 排序力(全 OTM 合併)==")
    ok = [x for x in out if x["p_floor"] is not None]
    for lo, hi in ((0, .35), (.35, .5), (.5, .65), (.65, .8), (.8, 1.01)):
        stats([x for x in ok if lo <= x["p_floor"] < hi], f" floor {lo:.2f}-{hi:.2f}")


if __name__ == "__main__":
    main()
