"""結構性校準:p = touch_prob(b, T, κ·σ, 0.07+δ) — 修輸入(厚尾→有效波動),非事後掰機率。
協議同前:≤2021 擬合(κ,δ) → 2022 空頭選保守收縮 λ → ≤2022 重擬合 → 2023+ 樣本外門檻驗收。"""
import csv
import json
import math
import os
import datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "calib_rows.csv"))))
D = {k: np.array([float(r[k]) for r in rows]) for k in ("barrier", "T", "vol_blend")}
Y = np.array([int(r["touched_high"]) for r in rows], dtype=float)
P_RAW = np.array([float(r["p_prod"]) for r in rows])
DATES = np.array([r["date"] for r in rows])


def touch_np(b, T, sigma, drift):
    """向量化反射原理觸及機率。"""
    a = np.log(b)
    nu = drift - 0.5 * sigma**2
    st = sigma * np.sqrt(T)
    from math import erf
    cdf = lambda x: 0.5 * (1 + np.vectorize(erf)(x / math.sqrt(2)))
    with np.errstate(over="ignore"):
        p = cdf((-a + nu * T) / st) + np.exp(np.clip(2 * nu * a / sigma**2, -50, 50)) * cdf((-a - nu * T) / st)
    return np.clip(p, 0.0, 1.0)


def model_p(mask, kappa, delta):
    return touch_np(D["barrier"][mask], D["T"][mask], np.maximum(D["vol_blend"][mask] * kappa, 1e-4), 0.07 + delta)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


tr1 = DATES <= "2021-12-31"
m22 = np.char.startswith(DATES.astype(str), "2022")
te = DATES > "2022-12-31"
tr2 = DATES <= "2022-12-31"

# ── κ, δ 網格(≤2021 Brier)──
best = None
for kappa in np.arange(1.0, 1.85, 0.05):
    for delta in np.arange(-0.02, 0.13, 0.01):
        b = brier(model_p(tr1, kappa, delta), Y[tr1])
        if best is None or b < best[0]:
            best = (b, round(float(kappa), 2), round(float(delta), 3))
b1, k1, d1 = best
print(f"step1 fit(≤2021): κ={k1} δ={d1:+.3f} Brier={b1:.4f} (raw={brier(P_RAW[tr1], Y[tr1]):.4f})")
# 參數敏感度(backtest-validation:要平台不要尖峰)
print("  敏感度(κ±0.1, δ±0.01 的 Brier):")
for kk in (k1 - 0.1, k1, k1 + 0.1):
    line = "   "
    for dd in (d1 - 0.01, d1, d1 + 0.01):
        line += f" κ{kk:.2f}/δ{dd:+.2f}:{brier(model_p(tr1, kk, dd), Y[tr1]):.4f}"
    print(line)

# ── λ 收縮:2022 空頭年(高估 ≤2pp 下 Brier 最低)──
p22s = model_p(m22, k1, d1)
best_lam = None
for lam in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
    pb = (1 - lam) * P_RAW[m22] + lam * p22s
    over = float(pb.mean() - Y[m22].mean())
    br = brier(pb, Y[m22])
    print(f"  λ={lam}: 2022 Brier={br:.4f} 高估={over:+.4f}{' over!' if over > 0.02 else ''}")
    if over <= 0.02 and (best_lam is None or br < best_lam[1]):
        best_lam = (lam, br)
lam = best_lam[0]
print(f"→ λ={lam}")

# ── ≤2022 重擬合 → 2023+ 樣本外 ──
best = None
for kappa in np.arange(1.0, 1.85, 0.05):
    for delta in np.arange(-0.02, 0.13, 0.01):
        b = brier(model_p(tr2, kappa, delta), Y[tr2])
        if best is None or b < best[0]:
            best = (b, round(float(kappa), 2), round(float(delta), 3))
_, k2, d2 = best
pcal = (1 - lam) * P_RAW[te] + lam * model_p(te, k2, d2)
pcal = np.clip(pcal, 0.02, 0.95)
base = float(Y[te].mean())
g = {"oos_n": int(te.sum()),
     "oos_brier_raw": round(brier(P_RAW[te], Y[te]), 4),
     "oos_brier_cal": round(brier(pcal, Y[te]), 4),
     "oos_brier_base": round(brier(np.full(int(te.sum()), base), Y[te]), 4),
     "oos_gap_raw": round(float(P_RAW[te].mean() - base), 4),
     "oos_gap_cal": round(float(pcal.mean() - base), 4)}
print(f"step2 fit(≤2022): κ={k2} δ={d2:+.3f}")
print(json.dumps(g, indent=1))
worst = 0.0
print(" OOS 分桶: bin, n, pred, real, dev")
yt = Y[te]
for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
    m = (pcal >= lo) & (pcal < hi)
    if m.sum() >= 50:
        dev = float(yt[m].mean() - pcal[m].mean())
        worst = max(worst, abs(dev))
        print(f"  {lo:.1f}-{hi:.1f}: n={int(m.sum())} pred={pcal[m].mean():.3f} real={yt[m].mean():.3f} dev={dev:+.3f}")

gates = {"beats_raw": g["oos_brier_cal"] < g["oos_brier_raw"],
         "beats_base": g["oos_brier_cal"] < g["oos_brier_base"],
         "gap_shrunk": abs(g["oos_gap_cal"]) < abs(g["oos_gap_raw"]),
         "bins_le_10pp": worst <= 0.10}
print("GATES:", gates, f"worst_bin={worst:.3f}")

if all(gates.values()):
    # 全數據最終擬合
    allm = np.ones(len(Y), dtype=bool)
    best = None
    for kappa in np.arange(1.0, 1.85, 0.05):
        for delta in np.arange(-0.02, 0.13, 0.01):
            b = brier(model_p(allm, kappa, delta), Y)
            if best is None or b < best[0]:
                best = (b, round(float(kappa), 2), round(float(delta), 3))
    _, kf, df = best
    calib = {
        "updated": datetime.date.today().isoformat(),
        "model": "structural_v2",
        "kappa": kf, "delta": df, "lam": lam, "clamp": [0.02, 0.95],
        "provenance": {
            "source": "walk-forward backtest 2019-02..2025-06, 55 CB issuers, 66380 forecasts, "
                      "barriers 1.05-1.5, horizons 0.5-3y, dividend-adjusted intraday-high touch",
            "protocol": "fit≤2021 → λ on 2022 bear holdout (over≤2pp) → refit≤2022 → OOS 2023+ gates",
            "oos": g, "gates": {k: bool(v) for k, v in gates.items()},
            "interpretation": "GBM(120d歷史vol)薄尾:有效波動 ×κ、drift 微調 δ;λ 收縮對沖倖存者偏差",
            "caveat": "universe=現存發行公司(倖存者偏差);live 帳本 predictions.jsonl 持續對答案",
        },
        "n_rows": 9, "n_interim": 0, "n_final": 0, "details": [],
    }
    json.dump(calib, open(os.path.join(HERE, "..", "calibration.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"ALL GATES PASS → calibration.json (κ={kf} δ={df:+.3f} λ={lam})")
else:
    print("GATES FAILED — 不上線")
