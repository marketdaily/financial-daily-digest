"""v4 最終校準:單點(pooled 經驗曲線)+ regime 區間(逐年曲線 min/max)+ 下限鐵則。
發現:遠尾非平穩,單點精度上限=年間散佈(±10pp);超過此精度的宣稱=假精確。
門檻(方向性):
  G1 單點 OOS Brier 贏原始 GBM + 贏基準率
  G2 下限鐵則:OOS 各 z 分桶×年,實際觸及率 ≥ band_lo−2pp 之桶數 ≥95%(下限絕不高估下檔)
  G3 部署域(b1.21/1.33×T2/3):單點偏差 ≤15pp 且下限成立
  G4 曲線對 z 單調遞減
全過 → calibration.json v4(pooled w + 7 條年度 w + λ + domain 防外插)。"""
import csv
import json
import math
import os
import datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "calib_rows.csv"))))
B = np.array([float(r["barrier"]) for r in rows])
T = np.array([float(r["T"]) for r in rows])
SIG = np.array([float(r["vol_blend"]) for r in rows])
Y = np.array([int(r["touched_high"]) for r in rows], dtype=float)
P_RAW = np.clip(np.array([float(r["p_prod"]) for r in rows]), 1e-4, 1 - 1e-4)
DATES = np.array([r["date"] for r in rows])
YEARS = np.array([d[:4] for d in DATES])
DRIFT = 0.07

Z = np.log(B) / (SIG * np.sqrt(T))
NU = (DRIFT - 0.5 * SIG**2) * np.sqrt(T) / SIG
X = np.column_stack([np.ones(len(Y)), Z, Z**2, NU, Z * NU])
L_RAW = np.log(P_RAW / (1 - P_RAW))
LAM = 0.8  # 沿用 2022 空頭 holdout 選出的收縮(fit_empirical.py)


def fit(mask):
    w = np.zeros(5)
    Xm, y = X[mask], Y[mask]
    for _ in range(80):
        mu = 1 / (1 + np.exp(-(Xm @ w)))
        g = Xm.T @ (mu - y)
        H = Xm.T @ (Xm * (mu * (1 - mu) + 1e-9)[:, None])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    return w


def point(mask, w, lam=LAM):
    z = (1 - lam) * L_RAW[mask] + lam * (X[mask] @ w)
    return np.clip(1 / (1 + np.exp(-z)), 0.02, 0.95)


def curve_p(mask, w):
    return np.clip(1 / (1 + np.exp(-(X[mask] @ w))), 0.02, 0.95)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


# ── OOS 驗證:≤2022 訓練(pooled+各年),2023-2025 驗 ──
tr = DATES <= "2022-12-31"
te = DATES > "2022-12-31"
w_pool_tr = fit(tr)
train_years = ("2019", "2020", "2021", "2022")
w_years_tr = {yr: fit(YEARS == yr) for yr in train_years}

pt = point(te, w_pool_tr)
base = float(Y[te].mean())
g1 = {"oos_brier_raw": round(brier(P_RAW[te], Y[te]), 4),
      "oos_brier_cal": round(brier(pt, Y[te]), 4),
      "oos_brier_base": round(brier(np.full(int(te.sum()), base), Y[te]), 4)}
gate1 = g1["oos_brier_cal"] < g1["oos_brier_raw"] and g1["oos_brier_cal"] < g1["oos_brier_base"]
print("G1", g1, gate1)

# G2 下限鐵則(嵌套協議):
# margin 由「≤2021 pooled 曲線 vs 2022 各 z 桶實際」的最大短差決定(不偷看 2023+),
# 下限 = pooled 曲線 − margin;OOS(2023-25)各 z 桶×年 realized ≥ 下限 之桶數 ≥95%。
w_pool_2021 = fit(DATES <= "2021-12-31")
m22all = YEARS == "2022"
z22 = Z[m22all]
e22 = np.quantile(z22, np.linspace(0, 1, 11))
deficits = []
for i in range(10):
    m = m22all.copy()
    m[m22all] = (z22 >= e22[i]) & (z22 < e22[i + 1] + 1e-9)
    if m.sum() >= 100:
        deficits.append(float(curve_p(m, w_pool_2021).mean()) - float(Y[m].mean()))
MARGIN = round(max(max(deficits), 0.0) + 0.01, 3)
print(f"margin(≤2021曲線 vs 2022 實際 最大短差+1pp)= {MARGIN}")

lo_curves = np.clip(curve_p(te, w_pool_tr) - MARGIN, 0.02, 0.95)
zt = Z[te]
edges = np.quantile(zt, np.linspace(0, 1, 11))
ok, tot, viol = 0, 0, []
for yr in ("2023", "2024", "2025"):
    ymask = YEARS[te] == yr
    for i in range(10):
        m = ymask & (zt >= edges[i]) & (zt < edges[i + 1] + 1e-9)
        if m.sum() >= 100:
            tot += 1
            r, lo = float(Y[te][m].mean()), float(lo_curves[m].mean())
            if r >= lo:
                ok += 1
            else:
                viol.append((yr, i, round(r, 3), round(lo, 3), int(m.sum())))
gate2 = tot > 0 and ok / tot >= 0.95
print(f"G2 下限鐵則: {ok}/{tot} 桶成立 → {gate2}  violations={viol[:5]}")

# G3 部署域
dep = te & np.isin(B, [1.21, 1.33]) & np.isin(T, [2.0, 3.0])
pd_ = point(dep, w_pool_tr)
dev = float(Y[dep].mean() - pd_.mean())
lo_dep = np.clip(curve_p(dep, w_pool_tr) - MARGIN, 0.02, 0.95)
floor_ok = float(Y[dep].mean()) >= float(lo_dep.mean())
gate3 = abs(dev) <= 0.15 and floor_ok
print(f"G3 部署域: n={int(dep.sum())} point={pd_.mean():.3f} real={Y[dep].mean():.3f} dev={dev:+.3f} "
      f"floor={lo_dep.mean():.3f} floor_ok={floor_ok} → {gate3}")

# G4 單調性(pooled,σ=0.35/T=1)
zs = np.linspace(0.1, 3.5, 12)
nu0 = (DRIFT - 0.5 * 0.35**2) * 1.0 / 0.35
pz = 1 / (1 + np.exp(-(w_pool_tr[0] + w_pool_tr[1] * zs + w_pool_tr[2] * zs**2 + w_pool_tr[3] * nu0 + w_pool_tr[4] * zs * nu0)))
gate4 = bool(np.all(np.diff(pz) < 1e-9))
print(f"G4 單調: {gate4}")

if all((gate1, gate2, gate3, gate4)):
    # 生產參數:全數據 pooled + 7 條年度曲線
    w_pool = fit(np.ones(len(Y), dtype=bool))
    all_years = sorted(set(YEARS))
    w_yr = {yr: fit(YEARS == yr) for yr in all_years if (YEARS == yr).sum() >= 3000}
    calib = {
        "updated": datetime.date.today().isoformat(),
        "model": "empirical_band_v4",
        "lam": LAM, "drift": DRIFT, "clamp": [0.02, 0.95], "floor_margin": MARGIN,
        "w_pooled": [round(float(x), 6) for x in w_pool],
        "w_years": {yr: [round(float(x), 6) for x in w] for yr, w in w_yr.items()},
        "features": "x=[1, z, z², m, z·m]; z=ln(b)/(σ√T), m=(drift−σ²/2)√T/σ; "
                    "point: logit=(1−λ)·logit(p_gbm)+λ·(w_pooled·x); "
                    "floor: sigmoid(w_pooled·x)−floor_margin; band顯示: min/max over w_years",
        "domain": {"z": [0.05, 3.0], "T": [0.4, 3.2], "sigma": [0.15, 1.0],
                   "note": "出界→回傳原始 GBM+標記不可信"},
        "provenance": {
            "source": "walk-forward 2019-02..2025-06, 55 CB issuers, 66380 forecasts, "
                      "barriers 1.05-1.5 × horizons 0.5-3y, div-adjusted intraday-high touch",
            "finding": "GBM(歷史vol)七年全期系統性低估觸及率(-10.7pp,月cluster CI[-12.9,-8.6]);"
                       "遠尾非平穩→單點精度上限=年間散佈±10pp→改交付 點+regime區間+下限",
            "gates": {"G1_brier": g1, "G2_floor_buckets": f"{ok}/{tot}",
                      "G3_deploy_dev": round(dev, 4), "G4_monotone": gate4},
            "caveat": "universe=現存發行公司(倖存者偏差);判定閘門一律用 band_lo(最差年份);"
                      "live 帳本 predictions.jsonl 持續對答案",
        },
    }
    # 合併寫入:live 帳本記分欄位(n_rows/n_interim/shrink/details…)是 cb_score.py 的資產,保留
    path = os.path.join(HERE, "..", "calibration.json")
    try:
        merged = json.load(open(path, encoding="utf-8"))
    except Exception:
        merged = {}
    merged.update(calib)
    json.dump(merged, open(path, "w"), ensure_ascii=False, indent=1)
    print("ALL GATES PASS → calibration.json v4 已寫(合併保留 live 記分欄位)")
    # 部署示例:群聯三口徑(z≈1.0, σ.38, T2.6)
    for (bb, tt, ss) in ((1.23, 2.6, 0.38), (1.33, 2.6, 0.38), (1.5, 1.0, 0.30)):
        z = math.log(bb) / (ss * math.sqrt(tt))
        m = (DRIFT - 0.5 * ss * ss) * math.sqrt(tt) / ss
        x = np.array([1, z, z * z, m, z * m])
        sys_path_hack = os.path.join(HERE, "..")
        import sys as _sys
        if sys_path_hack not in _sys.path:
            _sys.path.insert(0, sys_path_hack)
        from cb_core import touch_prob
        praw = touch_prob(1.0, bb, tt, ss, DRIFT)
        lp = (1 - LAM) * math.log(praw / (1 - praw)) + LAM * float(x @ w_pool)
        p = 1 / (1 + math.exp(-lp))
        band = [float(1 / (1 + math.exp(-(x @ np.array(w))))) for w in w_yr.values()]
        print(f"  例 b={bb} T={tt} σ={ss}: GBM={praw:.2f} → 點={p:.2f} 區間=[{min(band):.2f},{max(band):.2f}]")
else:
    print("GATES FAILED")
