"""touch_prob 歷史校準回測。
逐月 walk-forward:在每個取樣日只用當時可得的數據,複製生產端 vol 估計
(EWMA λ0.94 × 0.35 + 120d × 0.65)算 touch_prob,對照之後 T 年內還原股價高點
是否真的觸及水位。輸出逐筆預測 CSV 供 analyze_calib.py 統計。
波動用未調整價(生產端同款)、實際觸及用還原價(CB 轉換價會隨除息調降,
還原序列的倍數路徑才貼近真實回本點觸及)。"""
import os
import json
import math
import csv
import datetime
import bisect
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cb_core import touch_prob
from cb_data import _ann_vol, _ewma_vol, blend_vol

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "calib_rows.csv")

BARRIERS = (1.05, 1.10, 1.21, 1.33, 1.50)
HORIZONS = (0.5, 1.0, 2.0, 3.0)
DRIFT_PROD = 0.07
RF = 0.013


def load(code, suffix=""):
    path = os.path.join(DATA, f"{code}{suffix}.json")
    if not os.path.exists(path):
        return None
    rows = json.load(open(path))
    out = []
    for r in rows:
        c = r.get("close")
        h = r.get("max") or r.get("high") or c
        if c in (None, 0):
            continue
        out.append((r["date"], float(c), float(h or c)))
    out.sort()
    return out


def load_with_adj(code):
    """未調整序列 + 除息還原序列(A(t)=P(t)/cumfac(t))。
    除息日轉換價按 after/before 同步調降 → A(t)/A(t0) ≥ b ⟺ 真實回本點觸及,數學等價。"""
    unadj = load(code)
    if not unadj:
        return None
    factors = {}
    dpath = os.path.join(DATA, f"{code}_div.json")
    if os.path.exists(dpath):
        for r in json.load(open(dpath)):
            bp, ap = r.get("before_price"), r.get("after_price")
            if bp and ap and float(bp) > 0 and 0 < float(ap) <= float(bp):
                factors[r["date"]] = float(ap) / float(bp)
    cf = 1.0
    adj = []
    for d, c, h in unadj:
        if d in factors:
            cf *= factors[d]
        adj.append((d, c / cf, h / cf))
    return unadj, adj


def month_starts(dates, first="2019-02-01"):
    seen, out = set(), []
    for i, d in enumerate(dates):
        if d < first:
            continue
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(i)
    return out


def taiex_ma200_flags():
    rows = load("TAIEX")
    if not rows:
        return {}
    flags = {}
    closes = [c for _, c, _ in rows]
    for i, (d, c, _) in enumerate(rows):
        if i >= 200:
            ma = sum(closes[i - 200:i]) / 200
            flags[d] = 1 if c > ma else 0
    return flags


def main():
    db = json.load(open(os.path.join(HERE, "..", "cb_database.json")))
    codes = sorted({it.get("stock_code") for it in db["items"] if it.get("stock_code")})
    tflags = taiex_ma200_flags()
    n_rows = 0
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "date", "T", "barrier", "vol_blend", "v120", "v60", "ewma",
                    "p_prod", "p_zero", "p_rf", "touched_high", "touched_close",
                    "taiex_up", "max_ratio"])
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
            last_date = adates[-1]
            for i in month_starts(udates):
                t = udates[i]
                # 生產端:近 400 「日曆日」收盤 → log return
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
                s0 = acloses[ai]
                if s0 <= 0:
                    continue
                for T in HORIZONS:
                    end = (datetime.date.fromisoformat(t)
                           + datetime.timedelta(days=int(T * 365.25))).isoformat()
                    if end > last_date:
                        continue  # 結果窗未走完 → 剔除,不能拿未完成的窗當 0
                    aj = bisect.bisect_right(adates, end)
                    win_high = max(ahighs[ai + 1:aj], default=None)
                    win_close = max(acloses[ai + 1:aj], default=None)
                    if win_high is None:
                        continue
                    mr = win_high / s0
                    for b in BARRIERS:
                        w.writerow([code, t, T, b,
                                    round(vol, 4), round(vols["v120"] or 0, 4),
                                    round(vols["v60"] or 0, 4), round(vols["ewma"] or 0, 4),
                                    round(touch_prob(1.0, b, T, vol, DRIFT_PROD), 4),
                                    round(touch_prob(1.0, b, T, vol, 0.0), 4),
                                    round(touch_prob(1.0, b, T, vol, RF), 4),
                                    1 if mr >= b else 0,
                                    1 if (win_close / s0) >= b else 0,
                                    tflags.get(t, ""),
                                    round(mr, 4)])
                        n_rows += 1
    print(f"wrote {n_rows} rows -> {OUT}")


if __name__ == "__main__":
    main()
