"""校準回測統計:reliability 分桶、Brier vs 基準率、雙向 cluster bootstrap CI、
時間切分樣本外驗證 + 擬合 logit 校準映射(給 cb_ledger.apply_calibration 用)。"""
import os, csv, json, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(HERE, "calib_rows.csv")
OUT = os.path.join(HERE, "calib_report.json")

TRAIN_END = "2022-12-31"   # 樣本外切分:2023 起全是 OOS


def load():
    rows = []
    with open(ROWS) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def inv_logit(x):
    return 1 / (1 + math.exp(-x))


def fit_logistic(ps, ys):
    """y ~ sigmoid(a + b*logit(p)),Newton 法。回 (a, b)。"""
    X = np.array([[1.0, logit(p)] for p in ps])
    y = np.array(ys, dtype=float)
    w = np.zeros(2)
    for _ in range(50):
        z = X @ w
        mu = 1 / (1 + np.exp(-z))
        g = X.T @ (mu - y)
        W = mu * (1 - mu) + 1e-9
        H = X.T @ (X * W[:, None])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    return float(w[0]), float(w[1])


def brier(ps, ys):
    ps = np.asarray(ps, dtype=float)
    ys = np.asarray(ys, dtype=float)
    return float(np.mean((ps - ys) ** 2))


def reliability(ps, ys, edges=(0, .2, .3, .4, .5, .6, .7, .8, .9, 1.01)):
    ps = np.asarray(ps, dtype=float)
    ys = np.asarray(ys, dtype=float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (ps >= lo) & (ps < hi)
        if m.sum() >= 20:
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()),
                        "p_mean": round(float(ps[m].mean()), 4),
                        "realized": round(float(ys[m].mean()), 4)})
    return out


def cluster_boot_gap(rows, pcol, by, nboot=800, seed=7):
    """mean(p) - mean(y) 的 cluster bootstrap CI(by='month' 或 'code')。"""
    clusters = {}
    for r in rows:
        key = r["date"][:7] if by == "month" else r["code"]
        clusters.setdefault(key, []).append((float(r[pcol]), int(r["touched_high"])))
    keys = list(clusters)
    rng = np.random.default_rng(seed)
    gaps = []
    for _ in range(nboot):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        ps, ys = [], []
        for i in pick:
            for p, y in clusters[keys[i]]:
                ps.append(p)
                ys.append(y)
        gaps.append(float(np.mean(ps)) - float(np.mean(ys)))
    gaps.sort()
    return {"gap": round(float(np.mean(gaps)), 4),
            "ci95": [round(gaps[int(.025 * nboot)], 4), round(gaps[int(.975 * nboot)], 4)],
            "n_clusters": len(keys)}


def cell_stats(rows, pcol):
    cells = {}
    for r in rows:
        cells.setdefault((r["T"], r["barrier"]), []).append(r)
    out = []
    for (T, b), rs in sorted(cells.items()):
        ps = [float(r[pcol]) for r in rs]
        ys = [int(r["touched_high"]) for r in rs]
        base = float(np.mean(ys))
        out.append({"T": T, "barrier": b, "n": len(rs),
                    "p_mean": round(float(np.mean(ps)), 4), "realized": round(base, 4),
                    "brier": round(brier(ps, ys), 4),
                    "brier_base": round(brier([base] * len(ys), ys), 4)})
    return out


def main():
    rows = load()
    print(f"loaded {len(rows)} rows")
    train = [r for r in rows if r["date"] <= TRAIN_END]
    test = [r for r in rows if r["date"] > TRAIN_END]

    rep = {"n_rows": len(rows), "n_train": len(train), "n_test": len(test)}
    for pcol in ("p_prod", "p_zero", "p_rf"):
        ps = [float(r[pcol]) for r in rows]
        ys = [int(r["touched_high"]) for r in rows]
        base = float(np.mean(ys))
        rep[pcol] = {
            "overall": {"p_mean": round(float(np.mean(ps)), 4), "realized": round(base, 4),
                        "brier": round(brier(ps, ys), 4),
                        "brier_base": round(brier([base] * len(ys), ys), 4)},
            "reliability": reliability(ps, ys),
            "gap_boot_month": cluster_boot_gap(rows, pcol, "month"),
            "gap_boot_code": cluster_boot_gap(rows, pcol, "code"),
            "cells": cell_stats(rows, pcol),
        }

    # 校準映射:train 擬合,test 樣本外驗證(對生產欄 p_prod)
    a, b = fit_logistic([float(r["p_prod"]) for r in train],
                        [int(r["touched_high"]) for r in train])
    ps_t = [float(r["p_prod"]) for r in test]
    ys_t = [int(r["touched_high"]) for r in test]
    ps_cal = [inv_logit(a + b * logit(p)) for p in ps_t]
    base_t = float(np.mean(ys_t))
    rep["recalib"] = {
        "a": round(a, 4), "b": round(b, 4),
        "oos_brier_raw": round(brier(ps_t, ys_t), 4),
        "oos_brier_cal": round(brier(ps_cal, ys_t), 4),
        "oos_brier_base": round(brier([base_t] * len(ys_t), ys_t), 4),
        "oos_reliability_raw": reliability(ps_t, ys_t),
        "oos_reliability_cal": reliability(ps_cal, ys_t),
    }
    json.dump(rep, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: rep[k] for k in ("n_rows", "n_train", "n_test")}, indent=1))
    for pcol in ("p_prod", "p_zero", "p_rf"):
        o = rep[pcol]["overall"]
        print(f"{pcol}: p_mean={o['p_mean']} realized={o['realized']} "
              f"brier={o['brier']} base={o['brier_base']} "
              f"gap_month_ci={rep[pcol]['gap_boot_month']['ci95']}")
    print("recalib:", json.dumps(rep["recalib"], ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
