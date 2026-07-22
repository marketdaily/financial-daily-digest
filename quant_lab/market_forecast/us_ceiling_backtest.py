"""美股版每日方向預判天花板量測(2026-07-22,0721美股大漲晚報沒預判到而起)。
目標:S&P500 收盤對收盤方向。特徵全部是晚報 19:25 TW(07:25 ET)生成時已定案的資訊:
美股昨收(spx/sox)、VIX 昨收水位+變化、S&P 5日動能、亞洲當日收盤(台/韓/日/港,已收盤)。
消融:US-only vs US+Asia,檢驗亞洲當日收盤對美股當晚有無增量(反向 lead 的誠實檢驗)。
方法與台股版 ceiling_backtest.py 同:逐年 expanding walk-forward、標準化只用訓練段、L2 logistic。"""
import numpy as np, pandas as pd, yfinance as yf

px = yf.download(["^GSPC","^SOX","^VIX","^TWII","^KS11","^N225","^HSI"],
                 start="2009-06-01", progress=False, auto_adjust=False)["Close"]
r = px.pct_change() * 100

df = pd.DataFrame(index=px.index)
df["spx_prev"] = r["^GSPC"].shift(1)
df["sox_prev"] = r["^SOX"].shift(1)
df["vix_lvl"]  = px["^VIX"].shift(1)
df["vix_chg"]  = r["^VIX"].shift(1)
df["spx_m5"]   = (px["^GSPC"].shift(1) / px["^GSPC"].shift(6) - 1) * 100
for col, sym in [("twii_td","^TWII"),("kospi_td","^KS11"),("n225_td","^N225"),("hsi_td","^HSI")]:
    df[col] = r[sym].fillna(0.0)   # 亞洲當日收盤;休市=0(無新資訊,production 同法)
df["y"] = (r["^GSPC"] > 0).astype(int)
df = df[df["spx_prev"].notna() & df["vix_lvl"].notna() & df["spx_m5"].notna()]
df = df[r["^GSPC"].notna()]   # 只留美股交易日
df = df.dropna(subset=["sox_prev","vix_chg"])

US_ONLY = ["spx_prev","sox_prev","vix_lvl","vix_chg","spx_m5"]
FULL    = US_ONLY + ["twii_td","kospi_td","n225_td","hsi_td"]

def fit_logistic(X, y, l2=1.0, iters=200):
    X = np.hstack([np.ones((len(X),1)), X])
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1/(1+np.exp(-X @ w))
        g = X.T @ (p - y) + l2*np.r_[0, w[1:]]
        W = p*(1-p)
        H = (X * W[:,None]).T @ X + l2*np.eye(X.shape[1]); H[0,0] -= l2
        try: step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError: break
        w -= step
        if np.abs(step).max() < 1e-8: break
    return w


def walkforward(feats):
    preds = []
    for year in range(2015, 2027):
        tr = df[df.index.year < year]
        te = df[df.index.year == year]
        if len(te) == 0 or len(tr) < 500: continue
        mu, sd = tr[feats].mean(), tr[feats].std().replace(0, 1)
        w = fit_logistic(((tr[feats]-mu)/sd).values, tr["y"].values)
        Xte = np.hstack([np.ones((len(te),1)), ((te[feats]-mu)/sd).values])
        p = 1/(1+np.exp(-Xte @ w))
        preds.append(pd.DataFrame({"p":p, "y":te["y"].values, "ret":r.loc[te.index,"^GSPC"].values}, index=te.index))
    return pd.concat(preds)

for name, feats in [("US-only", US_ONLY), ("US+Asia", FULL)]:
    o = walkforward(feats)
    hit = ((o.p>0.5)==(o.y==1)).mean()*100
    brier = ((o.p-o.y)**2).mean()
    conf = (o.p-0.5).abs()
    top = o[conf >= conf.quantile(0.8)]
    top_hit = ((top.p>0.5)==(top.y==1)).mean()*100
    dir_ret = np.where(top.p>0.5, top.ret, -top.ret).mean()
    print(f"{name}: n={len(o)} 基礎率(收漲)={o.y.mean()*100:.1f}% | OOS命中={hit:.1f}% | Brier={brier:.4f}"
          f" | 最有把握20%日: 命中={top_hit:.1f}% 按方向日均{dir_ret:+.2f}% (n={len(top)})")

o = walkforward(FULL)
conf = (o.p-0.5).abs()
print("\n信心五層(US+Asia):")
for i,(lo,hi) in enumerate(zip([0,.2,.4,.6,.8],[.2,.4,.6,.8,1.0])):
    b = o[(conf>=conf.quantile(lo))&((conf<conf.quantile(hi)) if hi<1 else (conf<=conf.quantile(hi)))]
    print(f"  Q{i+1}: 命中 {((b.p>0.5)==(b.y==1)).mean()*100:5.1f}%  n={len(b)}")
# 年度穩定性(top20%桶)
print("\n年度穩定性(US+Asia 全體/高信心桶):")
for yr, g in o.groupby(o.index.year):
    c = (g.p-0.5).abs(); t = g[c>=c.quantile(0.8)]
    print(f"  {yr}: 全體 {((g.p>0.5)==(g.y==1)).mean()*100:5.1f}% (n={len(g)}) | top20% {((t.p>0.5)==(t.y==1)).mean()*100:5.1f}% (n={len(t)})")
# open-to-close 但書:高信心桶的命中是不是全靠隔夜跳空
op = yf.download("^GSPC", start="2009-06-01", progress=False, auto_adjust=False)["Open"]["^GSPC"]
oc = (px["^GSPC"]/op - 1) * 100
top = o[(o.p-0.5).abs() >= (o.p-0.5).abs().quantile(0.8)]
occ = oc.loc[top.index]
oc_hit = ((top.p>0.5)==(occ>0)).mean()*100
oc_ret = np.where(top.p>0.5, occ, -occ).mean()
print(f"\nopen-to-close 但書(top20%桶): oc方向命中 {oc_hit:.1f}% | 按方向 oc 日均 {oc_ret:+.2f}%")
d = o.index[-1]
print(f"\n最近一筆 {d.date()}: p_up={o.p.iloc[-1]:.2f} 實際{'漲' if o.y.iloc[-1] else '跌'} {o.ret.iloc[-1]:+.2f}%")
if "2026-07-21" in o.index.strftime("%Y-%m-%d").tolist():
    row = o.loc["2026-07-21"]
    print(f"0721 回放: p_up={float(row.p):.2f} → 實際 {float(row.ret):+.2f}%")
