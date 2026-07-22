"""每日台股方向預判的天花板量測:walk-forward 樣本外 logistic。
兩個時點:A=06:20(日報生成,隔夜訊號) B=08:15(加韓/日開盤gap)。
輸出:整體 OOS 方向命中率 vs 基礎率、按模型信心分五層的命中率、Brier。"""
import json, os, math, datetime as dt

OUT = os.path.dirname(os.path.abspath(__file__))

def load(name):
    with open(os.path.join(OUT, f"{name}.json")) as f:
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

def mom5(d):
    idx = twii_d.index(d)
    if idx < 6: return None
    a, b = twii_c[twii_d[idx-1]], twii_c[twii_d[idx-6]]
    return (a / b - 1) * 100 if b else None

rows = []
for d in twii_d:
    if d < dt.date(2010, 3, 1) or d not in twii_r: continue
    f = {}
    ok = True
    for n in ["sox", "spx", "stoxx", "kospi", "n225", "hsi"]:
        dts, rets, gaps, _ = M[n]
        pd_ = last_before(dts, d)
        v = rets.get(pd_) if pd_ else None
        if v is None: ok = False; break
        f[n] = v
    if not ok: continue
    vd, vr, _, vc = M["vix"]
    pv = last_before(vd, d)
    if pv is None or pv not in vc or vr.get(pv) is None: continue
    f["vix_lvl"] = vc[pv]; f["vix_chg"] = vr[pv]
    m5 = mom5(d)
    tp = last_before(twii_d, d)
    if m5 is None or tp not in twii_r: continue
    f["twii_prev"] = twii_r[tp]; f["twii_m5"] = m5
    kg = M["kospi"][2].get(d); ng = M["n225"][2].get(d)
    rows.append({"date": d, "f": f, "kg": kg, "ng": ng,
                 "y": 1 if twii_r[d] > 0 else 0, "ret": twii_r[d]})

FEATS_A = ["sox", "spx", "stoxx", "kospi", "n225", "hsi", "vix_lvl", "vix_chg", "twii_prev", "twii_m5"]

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

def predict(w, xi):
    z = w[0] + sum(w[j+1] * xi[j] for j in range(len(xi)))
    return 1 / (1 + math.exp(-max(-30, min(30, z))))

def run(label, feats, use_gap):
    data = []
    for r in rows:
        x = [r["f"][k] for k in feats]
        if use_gap:
            if r["kg"] is None: continue
            x = x + [r["kg"], r["ng"] if r["ng"] is not None else 0.0]
        data.append((r["date"], x, r["y"], r["ret"]))
    preds = []
    for year in range(2015, 2027):
        train = [(x, y) for d, x, y, _ in data if d.year < year]
        test = [(d, x, y, ret) for d, x, y, ret in data if d.year == year]
        if len(train) < 500 or not test: continue
        mu = [sum(x[j] for x, _ in train) / len(train) for j in range(len(train[0][0]))]
        sd = [max(1e-9, math.sqrt(sum((x[j]-mu[j])**2 for x, _ in train) / len(train))) for j in range(len(mu))]
        Xtr = [[(x[j]-mu[j])/sd[j] for j in range(len(mu))] for x, _ in train]
        ytr = [y for _, y in train]
        w = logistic_fit(Xtr, ytr)
        for d, x, y, ret in test:
            xs = [(x[j]-mu[j])/sd[j] for j in range(len(mu))]
            preds.append((d, predict(w, xs), y, ret))
    n = len(preds)
    acc = sum(1 for _, p, y, _ in preds if (p > 0.5) == (y == 1)) / n * 100
    base = max(sum(y for _, _, y, _ in preds), n - sum(y for _, _, y, _ in preds)) / n * 100
    brier = sum((p - y) ** 2 for _, p, y, _ in preds) / n
    pbar = sum(y for _, _, y, _ in preds) / n
    brier0 = sum((pbar - y) ** 2 for _, p, y, _ in preds) / n
    print(f"\n=== {label}(OOS 2015-2026,n={n})===")
    print(f"整體方向命中率 {acc:.1f}%(無腦猜多數={base:.1f}%)  Brier {brier:.4f} vs 氣候基準 {brier0:.4f}")
    srt = sorted(preds, key=lambda t: abs(t[1] - 0.5))
    q = n // 5
    names = ["最沒把握20%", "次低", "中", "次高", "最有把握20%"]
    for i in range(5):
        seg = srt[i*q:(i+1)*q] if i < 4 else srt[4*q:]
        a = sum(1 for _, p, y, _ in seg if (p > 0.5) == (y == 1)) / len(seg) * 100
        mret = sum(abs(r) for _, _, _, r in seg) / len(seg)
        days_yr = len(seg) / (n / 250)
        print(f"  {names[i]:10s} 命中 {a:5.1f}%  日均波動 {mret:.2f}%  約 {days_yr:.0f} 天/年")
    hi = [t for t in srt if abs(t[1] - 0.5) >= 0.25]
    if hi:
        a = sum(1 for _, p, y, _ in hi if (p > 0.5) == (y == 1)) / len(hi) * 100
        print(f"  信心>=75/25 的日子:n={len(hi)}({len(hi)/(n/250):.0f}天/年)命中 {a:.1f}%")
    return preds

pa = run("A:06:20 隔夜訊號(進日報)", FEATS_A, use_gap=False)
pb = run("B:08:15 加韓/日開盤gap", FEATS_A, use_gap=True)

# 今天(2026-07-21)兩模型會說什麼?
last = [r for r in rows if r["date"] == dt.date(2026, 7, 21)]
if last:
    r = last[0]
    print(f"\n今天實際:TWII {r['ret']:+.2f}%,韓gap={r['kg']}, 特徵={ {k: round(v,2) for k,v in r['f'].items()} }")
