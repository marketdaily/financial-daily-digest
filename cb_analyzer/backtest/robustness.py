"""校準偏差的穩健性拆解:分年、分大盤 regime、分水位/年期、分股票、
以及最嚴苛的 2022 空頭年壓力測試(校準修正在空頭會不會反向爆掉)。"""
import csv, math, os
import numpy as np
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "calib_rows.csv"))))
for r in rows:
    r["p"] = float(r["p_prod"])
    r["y"] = int(r["touched_high"])


def gap(rs):
    if not rs:
        return None
    ps = np.array([r["p"] for r in rs])
    ys = np.array([r["y"] for r in rs])
    return len(rs), float(ps.mean()), float(ys.mean())


print("── 分「取樣年」(預測發出的年份)──")
for yr in sorted({r["date"][:4] for r in rows}):
    g = gap([r for r in rows if r["date"][:4] == yr])
    if g:
        print(f"  {yr}: n={g[0]:>6} pred={g[1]:.3f} real={g[2]:.3f} gap={g[2]-g[1]:+.3f}")

print("── 分大盤位置(取樣日 TAIEX 是否站上 MA200)──")
for flag, lbl in (("1", "多頭(>MA200)"), ("0", "空頭(<MA200)")):
    g = gap([r for r in rows if r["taiex_up"] == flag])
    if g:
        print(f"  {lbl}: n={g[0]:>6} pred={g[1]:.3f} real={g[2]:.3f} gap={g[2]-g[1]:+.3f}")

print("── 分水位×年期 ──")
cells = defaultdict(list)
for r in rows:
    cells[(r["barrier"], r["T"])].append(r)
for (b, T), rs in sorted(cells.items()):
    g = gap(rs)
    print(f"  b={b} T={T}: n={g[0]:>5} pred={g[1]:.3f} real={g[2]:.3f} gap={g[2]-g[1]:+.3f}")

print("── 分股票(gap 分佈:低估是不是少數飆股撐起來的)──")
per = []
for code in sorted({r["code"] for r in rows}):
    g = gap([r for r in rows if r["code"] == code])
    if g and g[0] >= 200:
        per.append((code, g[0], g[2] - g[1]))
gaps = sorted(x[2] for x in per)
n = len(gaps)
neg = sum(1 for x in gaps if x < 0)
print(f"  {n} 檔;低估(gap>0)佔 {n - neg}/{n};中位數 gap={gaps[n // 2]:+.3f};"
      f"P10={gaps[int(n * .1)]:+.3f} P90={gaps[int(n * .9)]:+.3f}")

print("── 壓力測試:只用 2019-2021 擬合校準,拿 2022(空頭年取樣)驗 ──")


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def fit(train):
    X = np.array([[1.0, logit(r["p"])] for r in train])
    y = np.array([r["y"] for r in train], dtype=float)
    w = np.zeros(2)
    for _ in range(60):
        mu = 1 / (1 + np.exp(-(X @ w)))
        gvec = X.T @ (mu - y)
        H = X.T @ (X * (mu * (1 - mu) + 1e-9)[:, None])
        try:
            w -= np.linalg.solve(H, gvec)
        except np.linalg.LinAlgError:
            break
    return w


tr = [r for r in rows if r["date"] <= "2021-12-31"]
te22 = [r for r in rows if "2022-01-01" <= r["date"] <= "2022-12-31"]
w = fit(tr)
print(f"  fit(2019-21): a={w[0]:.3f} b={w[1]:.3f}")
for lbl, sub in (("2022 空頭年", te22),):
    ps = np.array([r["p"] for r in sub])
    ys = np.array([r["y"] for r in sub], dtype=float)
    pc = 1 / (1 + np.exp(-(w[0] + w[1] * np.array([logit(p) for p in ps]))))
    print(f"  {lbl}: n={len(sub)} raw_pred={ps.mean():.3f} calib_pred={pc.mean():.3f} real={ys.mean():.3f}")
    print(f"    Brier raw={np.mean((ps - ys) ** 2):.4f} calib={np.mean((pc - ys) ** 2):.4f} "
          f"base={np.mean((ys.mean() - ys) ** 2):.4f}")

print("── 倖存者偏差量化:55 檔樣本期年化報酬分佈(還原) ──")
import json, bisect
rets = []
for code in sorted({r["code"] for r in rows}):
    import calib_backtest as CB
    pair = CB.load_with_adj(code)
    if not pair:
        continue
    _, adj = pair
    a0, a1 = adj[0][1], adj[-1][1]
    yrs = (len(adj)) / 252
    if a0 > 0 and yrs > 2:
        rets.append((code, (a1 / a0) ** (1 / yrs) - 1))
vals = sorted(x[1] for x in rets)
print(f"  中位數年化 {vals[len(vals) // 2] * 100:+.1f}%  P25 {vals[len(vals) // 4] * 100:+.1f}%  "
      f"P75 {vals[3 * len(vals) // 4] * 100:+.1f}%  (drift 假設 7%)")
