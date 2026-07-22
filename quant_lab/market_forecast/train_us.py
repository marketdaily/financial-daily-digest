"""美股版凍結權重訓練(2026-07-22):全樣本 logistic → model_us 寫進 intel/market_forecast_model.json。
特徵=晚報 19:25 TW 已定案資訊(美股昨收+VIX+動能+亞洲當日收盤)。回測依據 us_ceiling_backtest.py:
OOS 2015-2026 命中 58.1%(基礎率 54.3%)、top20% 信心日 66.7%;US-only 無 edge(54.2%),增量全來自亞洲當日。"""
import json, numpy as np, pandas as pd, yfinance as yf
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
FEATS = ["spx_prev","sox_prev","vix_lvl","vix_chg","spx_m5","twii_td","kospi_td","n225_td","hsi_td"]

px = yf.download(["^GSPC","^SOX","^VIX","^TWII","^KS11","^N225","^HSI"],
                 start="2009-06-01", progress=False, auto_adjust=False)["Close"]
r = px.pct_change() * 100
df = pd.DataFrame(index=px.index)
df["spx_prev"] = r["^GSPC"].shift(1); df["sox_prev"] = r["^SOX"].shift(1)
df["vix_lvl"] = px["^VIX"].shift(1);  df["vix_chg"] = r["^VIX"].shift(1)
df["spx_m5"] = (px["^GSPC"].shift(1) / px["^GSPC"].shift(6) - 1) * 100
for col, sym in [("twii_td","^TWII"),("kospi_td","^KS11"),("n225_td","^N225"),("hsi_td","^HSI")]:
    df[col] = r[sym].fillna(0.0)
df["y"] = (r["^GSPC"] > 0).astype(int)
df = df[r["^GSPC"].notna()].dropna(subset=["spx_prev","sox_prev","vix_lvl","vix_chg","spx_m5"])

def fit_logistic(X, y, l2=1.0, iters=200):
    X = np.hstack([np.ones((len(X),1)), X]); w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1/(1+np.exp(-X @ w))
        g = X.T @ (p - y) + l2*np.r_[0, w[1:]]
        H = (X * (p*(1-p))[:,None]).T @ X + l2*np.eye(X.shape[1]); H[0,0] -= l2
        step = np.linalg.solve(H, g); w -= step
        if np.abs(step).max() < 1e-8: break
    return w

mu, sd = df[FEATS].mean(), df[FEATS].std().replace(0,1)
w = fit_logistic(((df[FEATS]-mu)/sd).values, df["y"].values)
mp = REPO / "intel" / "market_forecast_model.json"
model_all = json.loads(mp.read_text())
model_all["model_us"] = {"mu": mu.round(6).tolist(), "sd": sd.round(6).tolist(),
                         "w": np.round(w,6).tolist(), "feats": FEATS}
model_all["trained_through_us"] = str(df.index[-1].date())
mp.write_text(json.dumps(model_all, ensure_ascii=False, indent=1))
print(f"model_us 已寫入 (n={len(df)}, through {df.index[-1].date()})")
