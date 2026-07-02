"""CB 預測帳本:模型每次輸出的機率都被記下來,cb_score.py 之後對答案(Brier)。
沒有帳本,模型講「中途獲利機率 72%」永遠不用負責;有帳本才有回測→校準→進步。
紀律:每檔每天只記一筆;記錄絕不拋錯(帳本壞了不能拖垮分析);
校準因子 n≥20 才啟動且有界(quant-math:小樣本校準=雜訊)。"""
import os, json, datetime

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


def record(it, a, be_S, p_touch, p_term):
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
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        seen.add(key)
    except Exception:
        pass


def apply_calibration(p):
    """有實證校準因子(n≥20)才調整顯示機率,否則原樣返回。因子有界 [0.6, 1.1],結果夾 [0.01, 0.97]。"""
    global _calib
    if _calib is None:
        try:
            with open(CALIB, encoding="utf-8") as f:
                _calib = json.load(f)
        except Exception:
            _calib = {}
    try:
        if _calib.get("n_interim", 0) >= 20 and _calib.get("shrink"):
            k = max(0.6, min(1.1, float(_calib["shrink"])))
            return max(0.01, min(0.97, p * k))
    except Exception:
        pass
    return p
