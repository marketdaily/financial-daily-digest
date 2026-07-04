"""CB 預測帳本:模型每次輸出的機率都被記下來,cb_score.py 之後對答案(Brier)。
沒有帳本,模型講「中途獲利機率 72%」永遠不用負責;有帳本才有回測→校準→進步。
紀律:每檔每天只記一筆;記錄絕不拋錯(帳本壞了不能拖垮分析);
校準因子 n≥20 才啟動且有界(quant-math:小樣本校準=雜訊)。"""
import os
import json
import math
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "predictions.jsonl")
CALIB = os.path.join(HERE, "calibration.json")
_seen = None
_calib = None


def _load_seen():
    global _seen
    if _seen is None:
        _seen = set()
        try:
            with open(LEDGER, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        _seen.add((r.get("bond_code"), r.get("date")))
                    except Exception:
                        pass
        except FileNotFoundError:
            pass
    return _seen


def record(it, a, be_S, p_touch, p_term, extra=None):
    try:
        d = datetime.date.today().isoformat()
        key = (it.get("bond_code"), d)
        seen = _load_seen()
        if not it.get("bond_code") or key in seen:
            return
        row = {
            "date": d, "bond_code": it["bond_code"], "stock_code": it.get("stock_code"),
            "name": it.get("name"), "spot": round(a["spot"], 2), "be_S": round(be_S, 2),
            "T": round(a["T_opt"], 3), "vol": round(a["hist_vol"], 4), "drift": 0.07,
            "p_touch": round(p_touch, 4), "p_term": round(p_term, 4),
            "cbas_premium": round(a.get("cbas_premium") or 0, 2),
        }
        if extra:
            row.update({k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in extra.items() if v is not None})
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        seen.add(key)
    except Exception:
        pass


def _load_calib():
    global _calib
    if _calib is None:
        try:
            with open(CALIB, encoding="utf-8") as f:
                _calib = json.load(f)
        except Exception:
            _calib = {}
    return _calib


def apply_calibration(p):
    """舊介面(live 帳本 shrink 因子,n≥20 才動)。v4 經驗校準請用 calibrate_touch。"""
    c = _load_calib()
    try:
        if c.get("n_interim", 0) >= 20 and c.get("shrink"):
            k = max(0.6, min(1.1, float(c["shrink"])))
            return max(0.01, min(0.97, p * k))
    except Exception:
        pass
    return p


def calibrate_touch(p_raw, S=None, be_S=None, T=None, sigma=None):
    """v4 經驗校準(2019-25 歷史回測,walk-forward 驗證,見 backtest/fit_v4_band.py):
    回 dict(p=校準點估計, lo/hi=七年 regime 區間, floor=判定下限=pooled−margin, method)。
    參數缺、出 domain、或參數檔非 v4 → 原樣返回(拒外插,寧可保守)。"""
    c = _load_calib()
    out_raw = {"p": apply_calibration(p_raw), "lo": None, "hi": None,
               "floor": None, "method": "raw"}
    try:
        if (c.get("model") != "empirical_band_v4" or not all([S, be_S, T, sigma])
                or be_S <= S or sigma <= 0 or T <= 0):
            return out_raw
        b = be_S / S
        z = math.log(b) / (sigma * math.sqrt(T))
        dom = c.get("domain") or {}
        if not (dom["z"][0] <= z <= dom["z"][1] and dom["T"][0] <= T <= dom["T"][1]
                and dom["sigma"][0] <= sigma <= dom["sigma"][1]):
            out_raw["method"] = "raw_out_of_domain"
            return out_raw
        drift = c.get("drift", 0.07)
        m = (drift - 0.5 * sigma * sigma) * math.sqrt(T) / sigma
        x = (1.0, z, z * z, m, z * m)
        dot = lambda w: sum(wi * xi for wi, xi in zip(w, x))
        sig = lambda v: 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, v))))
        lo_c, hi_c = c.get("clamp", [0.02, 0.95])
        pool = dot(c["w_pooled"])
        pr = min(max(p_raw, 1e-4), 1 - 1e-4)
        p = (1 - c["lam"]) * math.log(pr / (1 - pr)) + c["lam"] * pool
        years = [sig(dot(w)) for w in c["w_years"].values()]
        return {"p": min(max(sig(p), lo_c), hi_c),
                "lo": min(max(min(years), lo_c), hi_c),
                "hi": min(max(max(years), lo_c), hi_c),
                "floor": min(max(sig(pool) - c.get("floor_margin", 0.11), lo_c), hi_c),
                "method": "empirical_band_v4"}
    except Exception:
        return out_raw
