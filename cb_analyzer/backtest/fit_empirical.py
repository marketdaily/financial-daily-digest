"""經驗觸及曲線校準 v3:座標 z=ln(b)/(σ√T)(標準化距離)、m=ν√T/σ(drift項),
logistic[1,z,z²,m,z·m] 直接學真實觸及率形狀(=學 barrier 的厚尾 smile),
λ 在 logit 空間向原始 GBM 收縮(保低機率區的抬升)+2022 空頭約束。
協議:fit≤2021 → λ@2022 → refit≤2022 → OOS 2023+ 四門檻 → 全過才寫生產參數。"""
import csv, json, math, os, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "calib_rows.csv"))))
B = np.array([float(r["barrier"]) for r in rows])
T = np.array([float(r["T"]) for r in rows])
SIG = np.array([float(r["vol_blend"]) for r in rows])
Y = np.array([int(r["touched_high"]) for r in rows], dtype=float)
P_RAW = np.clip(np.array([float(r["p_prod"]) for r in rows]), 1e-4, 1 - 1e-4)
DATES = np.array([r["date"] for r in rows])
DRIFT = 0.07

Z = np.log(B) / (SIG * np.sqrt(T))
NU = (DRIFT - 0.5 * SIG**2) * np.sqrt(T) / SIG
X_ALL = np.column_stack([np.ones(len(Y)), Z, Z**2, NU, Z * NU])
L_RAW = np.log(P_RAW / (1 - P_RAW))


def fit(mask):
    X, y = X_ALL[mask], Y[mask]
    w = np.zeros(X.shape[1])
    for _ in range(80):
        mu = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (mu - y)
        H = X.T @ (X * (mu * (1 - mu) + 1e-9)[:, None])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    return w


def pred_logit(mask, w):
    return X_ALL[mask] @ w


def blend(mask, w, lam):
    z = (1 - lam) * L_RAW[mask] + lam * pred_logit(mask, w)
    return np.clip(1 / (1 + np.exp(-z)), 0.02, 0.95)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


tr1 = DATES <= "2021-12-31"
m22 = np.char.startswith(DATES.astype(str), "2022")
tr2 = DATES <= "2022-12-31"
te = DATES > "2022-12-31"

w1 = fit(tr1)
print(f"step1 fit(≤2021) w={np.round(w1, 3).tolist()}  Brier={brier(blend(tr1, w1, 1.0), Y[tr1]):.4f} raw={brier(P_RAW[tr1], Y[tr1]):.4f}")

# 單調性檢查:z 上升 p 必須下降(固定 σ=0.35, T=1)
sig0, t0 = 0.35, 1.0
zs = np.linspace(0.1, 3.5, 12)
nu0 = (DRIFT - 0.5 * sig0**2) * math.sqrt(t0) / sig0
pz = 1 / (1 + np.exp(-(w1[0] + w1[1] * zs + w1[2] * zs**2 + w1[3] * nu0 + w1[4] * zs * nu0)))
mono = bool(np.all(np.diff(pz) < 1e-9))
print(f"  單調性(σ0.35,T1): {'OK' if mono else 'FAIL'}  p(z)={np.round(pz, 3).tolist()}")

best_lam = None
for lam in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
    pb = blend(m22, w1, lam)
    over = float(pb.mean() - Y[m22].mean())
    br = brier(pb, Y[m22])
    print(f"  λ={lam}: 2022 Brier={br:.4f} 高估={over:+.4f}{' over!' if over > 0.02 else ''}")
    if over <= 0.02 and (best_lam is None or br < best_lam[1]):
        best_lam = (lam, br)
lam = best_lam[0]
print(f"→ λ={lam}")

w2 = fit(tr2)
pcal = blend(te, w2, lam)
base = float(Y[te].mean())
g = {"oos_n": int(te.sum()),
     "oos_brier_raw": round(brier(P_RAW[te], Y[te]), 4),
     "oos_brier_cal": round(brier(pcal, Y[te]), 4),
     "oos_brier_base": round(brier(np.full(int(te.sum()), base), Y[te]), 4),
     "oos_gap_raw": round(float(P_RAW[te].mean() - base), 4),
     "oos_gap_cal": round(float(pcal.mean() - base), 4)}
print(f"step2 fit(≤2022) w={np.round(w2, 3).tolist()}")
print(json.dumps(g, indent=1))

yt = Y[te]
worst, bins_out = 0.0, []
print(" OOS 分桶:")
for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
    m = (pcal >= lo) & (pcal < hi)
    if m.sum() >= 50:
        dev = float(yt[m].mean() - pcal[m].mean())
        worst = max(worst, abs(dev))
        bins_out.append({"bin": f"{lo}-{hi}", "n": int(m.sum()),
                         "pred": round(float(pcal[m].mean()), 3), "real": round(float(yt[m].mean()), 3)})
        print(f"  {lo:.1f}-{hi:.1f}: n={int(m.sum())} pred={pcal[m].mean():.3f} real={yt[m].mean():.3f} dev={dev:+.3f}")

print(" OOS 分水位×年期 cell 最大偏差:")
worst_cell = 0.0
for bb in sorted(set(B[te])):
    for tt in sorted(set(T[te])):
        m = te & (B == bb) & (T == tt)
        if m.sum() >= 100:
            pc = blend(m, w2, lam)
            dev = float(Y[m].mean() - pc.mean())
            worst_cell = max(worst_cell, abs(dev))
print(f"  worst_cell={worst_cell:.3f}")

gates = {"beats_raw": g["oos_brier_cal"] < g["oos_brier_raw"],
         "beats_base": g["oos_brier_cal"] < g["oos_brier_base"],
         "gap_shrunk": abs(g["oos_gap_cal"]) < abs(g["oos_gap_raw"]),
         "bins_le_10pp": worst <= 0.10,
         "monotone_z": mono}
print("GATES:", gates, f"worst_bin={worst:.3f}")

if all(gates.values()):
    wf = fit(np.ones(len(Y), dtype=bool))
    calib = {
        "updated": datetime.date.today().isoformat(),
        "model": "empirical_touch_v3",
        "w": [round(float(x), 6) for x in wf], "lam": lam, "drift": DRIFT,
        "features": "logit(p)=(1-λ)·logit(p_gbm)+λ·(w·[1, z, z², m, z·m]), z=ln(b)/(σ√T), m=(drift-σ²/2)√T/σ",
        "clamp": [0.02, 0.95],
        "domain": {"z": [0.0, 4.0], "T": [0.3, 3.5], "sigma": [0.15, 1.2],
                   "note": "超出 domain → fallback 原始 GBM(拒外插)"},
        "provenance": {
            "source": "walk-forward 2019-02..2025-06, 55 CB issuers, 66380 forecasts, "
                      "barriers 1.05-1.5 × horizons 0.5-3y, dividend-adjusted intraday-high touch",
            "protocol": "fit≤2021 → λ@2022 bear (over≤2pp) → refit≤2022 → OOS 2023+ gates",
            "oos": g, "oos_bins": bins_out, "gates": {k: bool(v) for k, v in gates.items()},
            "worst_cell_dev": round(worst_cell, 4),
            "caveat": "universe=現存發行公司(倖存者偏差,λ+2022約束對沖);live 帳本持續對答案",
        },
        "n_rows": 9, "n_interim": 0, "n_final": 0, "details": [],
    }
    json.dump(calib, open(os.path.join(HERE, "..", "calibration.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"ALL GATES PASS → calibration.json 已寫(w={np.round(wf, 3).tolist()} λ={lam})")
else:
    print("GATES FAILED — 不上線")
