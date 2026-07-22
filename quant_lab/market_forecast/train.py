"""每日大盤預判模型訓練器:全樣本訓練 A(06:20 隔夜)/B(08:15 加韓日開盤gap)兩顆 logistic,
凍結權重輸出 intel/market_forecast_model.json。
資料:同目錄 *_o.json(用 ../crash_gate_night/fetch_global.py 抓,九市場 2010~ 日線 OHLC)。
天花板與可操作性驗證見 FORECAST.md;target=台股收盤對收盤方向(收盤預報,非進場訊號)。
用法:python3 train.py [資料目錄] [輸出路徑]
"""
import json, math, os, sys, datetime as dt

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "intel", "market_forecast_model.json")

def load(name):
    with open(os.path.join(DATA, f"{name}.json")) as f:
        arr = json.load(f)
    dates, opens, closes = [], {}, {}
    for a in arr:
        d = dt.date.fromisoformat(a["date"])
        dates.append(d); opens[d] = a["open"]; closes[d] = a["close"]
    rets, gaps = {}, {}
    for i in range(1, len(dates)):
        d, p = dates[i], dates[i-1]
        if closes[p]:
            rets[d] = (closes[d] / closes[p] - 1) * 100
            o = opens.get(d)
            if o and o > 0 and abs(o - closes[p]) > 1e-9:
                gaps[d] = (o / closes[p] - 1) * 100
    return dates, rets, gaps, closes

twii_d, twii_r, twii_g, twii_c = load("twii_o")
M = {n: load(f"{n}_o") for n in ["kospi", "n225", "sox", "spx", "vix", "stoxx", "hsi"]}

def last_before(dates, d):
    prev = None
    for x in dates:
        if x < d: prev = x
        else: break
    return prev

FEATS_A = ["sox", "spx", "stoxx", "kospi", "n225", "hsi", "vix_lvl", "vix_chg", "twii_prev", "twii_m5"]
FEATS_B = FEATS_A + ["kospi_gap", "n225_gap"]

rows = []
for idx, d in enumerate(twii_d):
    if d < dt.date(2010, 3, 1) or d not in twii_r: continue
    f, ok = {}, True
    for n in ["sox", "spx", "stoxx", "kospi", "n225", "hsi"]:
        dts, rets, _, _ = M[n]
        pd_ = last_before(dts, d)
        v = rets.get(pd_) if pd_ else None
        if v is None: ok = False; break
        f[n] = v
    if not ok: continue
    vd, vr, _, vc = M["vix"]
    pv = last_before(vd, d)
    if pv is None or pv not in vc or vr.get(pv) is None: continue
    f["vix_lvl"] = vc[pv]; f["vix_chg"] = vr[pv]
    if idx < 6: continue
    a, b = twii_c.get(twii_d[idx-1]), twii_c.get(twii_d[idx-6])
    tp = last_before(twii_d, d)
    if not a or not b or tp not in twii_r: continue
    f["twii_prev"] = twii_r[tp]; f["twii_m5"] = (a / b - 1) * 100
    rows.append({"date": d, "f": f, "kg": M["kospi"][2].get(d), "ng": M["n225"][2].get(d),
                 "y": 1 if twii_r[d] > 0 else 0})

def logistic_fit(X, y, l2=1.0, iters=300, lr=0.1):
    n, k = len(X), len(X[0])
    w = [0.0] * (k + 1)
    for _ in range(iters):
        g = [0.0] * (k + 1)
        for xi, yi in zip(X, y):
            z = w[0] + sum(w[j+1] * xi[j] for j in range(k))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            e = p - yi
            g[0] += e
            for j in range(k): g[j+1] += e * xi[j]
        for j in range(k + 1):
            g[j] = g[j] / n + (l2 / n) * (w[j] if j else 0)
            w[j] -= lr * g[j]
    return w

def train(feats, use_gap):
    data = []
    for r in rows:
        x = [r["f"][k] for k in FEATS_A]
        if use_gap:
            if r["kg"] is None: continue
            x = x + [r["kg"], r["ng"] if r["ng"] is not None else 0.0]
        data.append((x, r["y"]))
    k = len(data[0][0])
    mu = [sum(x[j] for x, _ in data) / len(data) for j in range(k)]
    sd = [max(1e-9, math.sqrt(sum((x[j]-mu[j])**2 for x, _ in data) / len(data))) for j in range(k)]
    X = [[(x[j]-mu[j])/sd[j] for j in range(k)] for x, _ in data]
    w = logistic_fit(X, [y for _, y in data])
    return {"feats": feats, "mu": mu, "sd": sd, "w": w, "n_train": len(data)}

model = {
    "model_a": train(FEATS_A, use_gap=False),
    "model_b": train(FEATS_B, use_gap=True),
    "trained_through": rows[-1]["date"].isoformat(),
    "target": "TWII close-to-close direction(收盤預報,非進場訊號;可操作性見 FORECAST.md)",
    "oos_reference": {"a_cc_acc": 66.6, "b_cc_acc": 69.7, "a_top20_cc": 84.9, "b_top20_cc": 88.3,
                      "a_oc_acc": 54.1, "b_oc_acc": 56.2, "b_top20_oc": 64.2},
}
with open(OUT, "w") as fo:
    json.dump(model, fo, indent=1)
print(f"trained_through={model['trained_through']} n_a={model['model_a']['n_train']} "
      f"n_b={model['model_b']['n_train']} -> {os.path.abspath(OUT)}")
