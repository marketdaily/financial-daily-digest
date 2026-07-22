"""可操作性驗證:同特徵改預測「台股開盤→收盤」方向(讀者 09:00 才能進場,跳空吃不到)。"""
import math, datetime as dt
import daily_forecast_ceiling as m

# oc = (close/open - 1):由 cc 報酬與 gap 反推;Yahoo open 為 placeholder 的日子已被 load 濾掉
oc_map = {}
for d in m.twii_d:
    if d in m.twii_r and d in m.twii_g:
        cc, g = m.twii_r[d], m.twii_g[d]
        oc_map[d] = ((1 + cc / 100) / (1 + g / 100) - 1) * 100

def run_oc(label, use_gap):
    data = []
    for r in m.rows:
        d = r["date"]
        if d not in oc_map: continue
        x = [r["f"][k] for k in m.FEATS_A]
        if use_gap:
            if r["kg"] is None: continue
            x = x + [r["kg"], r["ng"] if r["ng"] is not None else 0.0]
        data.append((d, x, 1 if oc_map[d] > 0 else 0, oc_map[d]))
    preds = []
    for year in range(2015, 2027):
        train = [(x, y) for d, x, y, _ in data if d.year < year]
        test = [(d, x, y, ret) for d, x, y, ret in data if d.year == year]
        if len(train) < 500 or not test: continue
        mu = [sum(x[j] for x, _ in train) / len(train) for j in range(len(train[0][0]))]
        sd = [max(1e-9, math.sqrt(sum((x[j]-mu[j])**2 for x, _ in train) / len(train))) for j in range(len(mu))]
        Xtr = [[(x[j]-mu[j])/sd[j] for j in range(len(mu))] for x, _ in train]
        w = m.logistic_fit(Xtr, [y for _, y in train])
        for d, x, y, ret in test:
            xs = [(x[j]-mu[j])/sd[j] for j in range(len(mu))]
            preds.append((d, m.predict(w, xs), y, ret))
    n = len(preds)
    acc = sum(1 for _, p, y, _ in preds if (p > 0.5) == (y == 1)) / n * 100
    base = max(sum(y for *_, in [(y,) for _, _, y, _ in preds]) if False else sum(y for _, _, y, _ in preds),
               n - sum(y for _, _, y, _ in preds)) / n * 100
    print(f"{label}(開盤→收盤,OOS n={n}):整體 {acc:.1f}%(基礎 {base:.1f}%)")
    srt = sorted(preds, key=lambda t: abs(t[1] - 0.5))
    q = n // 5
    top = srt[4*q:]
    a = sum(1 for _, p, y, _ in top if (p > 0.5) == (y == 1)) / len(top) * 100
    mean_oc = sum(r for _, p, y, r in top if (p > 0.5)) and None
    # 高信心日的平均已實現 oc 報酬(按預測方向簽名)
    pnl = sum((r if p > 0.5 else -r) for _, p, _, r in top) / len(top)
    print(f"  最有把握20%:命中 {a:.1f}%,按方向日均 {pnl:+.2f}%(約 {len(top)/(n/250):.0f} 天/年)")

run_oc("A:06:20", use_gap=False)
run_oc("B:08:15", use_gap=True)
