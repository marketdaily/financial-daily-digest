"""生產校準參數擬合(嚴格 walk-forward 協議):
1) 2019-21 擬合 (a,b) → 2022 空頭年選收縮係數 λ(對沖倖存者偏差,寧可少修不過修)
2) 2019-22 重擬合 → 2023+ 全樣本外驗收(門檻:Brier 贏原始+贏基準率、各分桶誤差、空頭不高估>5pp)
3) 全過 → 全數據重擬合 + 選定 λ 寫進 calibration.json 供 cb_ledger.apply_calibration。"""
import csv, json, math, os, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "calib_rows.csv"))))
for r in rows:
    r["p"] = float(r["p_prod"])
    r["y"] = int(r["touched_high"])


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def fit(sub):
    X = np.array([[1.0, logit(r["p"])] for r in sub])
    y = np.array([r["y"] for r in sub], dtype=float)
    w = np.zeros(2)
    for _ in range(60):
        mu = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (mu - y)
        H = X.T @ (X * (mu * (1 - mu) + 1e-9)[:, None])
        try:
            w -= np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
    return float(w[0]), float(w[1])


def apply_map(ps, a, b, lam):
    pc = 1 / (1 + np.exp(-(a + b * np.array([logit(p) for p in ps]))))
    out = (1 - lam) * np.asarray(ps) + lam * pc
    return np.clip(out, 0.02, 0.95)


def brier(ps, ys):
    return float(np.mean((np.asarray(ps) - np.asarray(ys, dtype=float)) ** 2))


def rel_bins(ps, ys, edges=(0, .2, .3, .4, .5, .6, .7, .8, .9, 1.01)):
    ps = np.asarray(ps)
    ys = np.asarray(ys, dtype=float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (ps >= lo) & (ps < hi)
        if m.sum() >= 50:
            out.append((f"{lo:.1f}-{hi:.1f}", int(m.sum()),
                        float(ps[m].mean()), float(ys[m].mean())))
    return out


# ── 步驟 1:選 λ ──
tr1 = [r for r in rows if r["date"] <= "2021-12-31"]
te22 = [r for r in rows if "2022" == r["date"][:4]]
a1, b1 = fit(tr1)
p22 = [r["p"] for r in te22]
y22 = [r["y"] for r in te22]
print(f"step1 fit(≤2021): a={a1:.4f} b={b1:.4f}   2022 real={np.mean(y22):.4f}")
best = None
for lam in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
    pc = apply_map(p22, a1, b1, lam)
    over = float(pc.mean() - np.mean(y22))
    br = brier(pc, y22)
    flag = "OK" if over <= 0.02 else "over!"
    print(f"  λ={lam}: 2022 Brier={br:.4f} 高估={over:+.4f} {flag}")
    if over <= 0.02 and (best is None or br < best[1]):
        best = (lam, br)
lam = best[0]
print(f"→ 選 λ={lam}(2022 空頭年高估 ≤2pp 下 Brier 最低)")

# ── 步驟 2:2019-22 擬合 → 2023+ 樣本外驗收 ──
tr2 = [r for r in rows if r["date"] <= "2022-12-31"]
te = [r for r in rows if r["date"] > "2022-12-31"]
a2, b2 = fit(tr2)
pt = [r["p"] for r in te]
yt = [r["y"] for r in te]
pcal = apply_map(pt, a2, b2, lam)
base = float(np.mean(yt))
g = {
    "oos_n": len(te),
    "oos_brier_raw": round(brier(pt, yt), 4),
    "oos_brier_cal": round(brier(pcal, yt), 4),
    "oos_brier_base": round(brier([base] * len(yt), yt), 4),
    "oos_gap_raw": round(float(np.mean(pt) - base), 4),
    "oos_gap_cal": round(float(pcal.mean() - base), 4),
}
print(f"step2 fit(≤2022): a={a2:.4f} b={b2:.4f}")
print(json.dumps(g, indent=1))
print(" OOS 分桶(校準後): bin, n, pred, real")
worst = 0.0
for bin_, n, pm, rm in rel_bins(pcal, yt):
    dev = rm - pm
    worst = max(worst, abs(dev))
    print(f"  {bin_}: n={n} pred={pm:.3f} real={rm:.3f} dev={dev:+.3f}")

gate1 = g["oos_brier_cal"] < g["oos_brier_raw"]
gate2 = g["oos_brier_cal"] < g["oos_brier_base"]
gate3 = abs(g["oos_gap_cal"]) < abs(g["oos_gap_raw"])
gate4 = worst <= 0.10
print(f"GATES: 校準勝原始={gate1} 勝基準率={gate2} 總偏差縮小={gate3} 最大分桶偏差≤10pp={gate4}(worst={worst:.3f})")

if all((gate1, gate2, gate3, gate4)):
    a3, b3 = fit(rows)
    calib = {
        "updated": datetime.date.today().isoformat(),
        "model": "logit_blend_v2",
        "a": round(a3, 4), "b": round(b3, 4), "lam": lam,
        "clamp": [0.02, 0.95],
        "provenance": {
            "source": "historical walk-forward backtest 2019-02..2025-06, 55 CB issuers, "
                      "66380 forecasts, barriers 1.05-1.5, horizons 0.5-3y, div-adjusted touch",
            "protocol": "λ chosen on 2022 bear-year holdout (fit≤2021); OOS validated 2023+ (fit≤2022)",
            "oos": g,
            "caveat": "universe=current issuers → survivorship; λ-shrink + 2022 stress guards it; "
                      "live ledger (predictions.jsonl) remains the ongoing arbiter",
        },
        # 舊欄位保留:live 帳本記分照舊累積,n_interim/details 由 cb_score.py 維護
        "n_rows": 9, "n_interim": 0, "n_final": 0, "details": [],
    }
    out = os.path.join(HERE, "..", "calibration.json")
    json.dump(calib, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"ALL GATES PASS → wrote {out} (final fit a={a3:.4f} b={b3:.4f} λ={lam})")
else:
    print("GATES FAILED — 不寫生產參數,回頭修")
