"""估值帳本計分:回頭驗證「當時記下的 DCF 合理價區間,有沒有真的框住之後的股價」。
DCF 是中長期估值(兩階段折現假設 5 年+永續),不是短線訊號,min_age_days 預設 90 天,
樣本不足(帳本剛起步/尚未滿齡)一律誠實回報 n=0,絕不硬湊數字。
CLI: python3 valuation/score_ledger.py [min_age_days=90]
"""
import os
import sys
import json
import math
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ledger import LEDGER, price_now  # noqa: E402

MIN_SAMPLES = 5  # 樣本 < 此門檻不給確切 hit_rate,只回 n(同 cb-desk alert_ledger/intel signal_ledger 誠實鐵則:
# 小樣本比率=雜訊,舊版 round(hits/n,4) 對 n=1 也會印出 100% 或 0%,見 lesson calibration_honesty_subgroup_and_null_baseline.md)


def _finite_positive(x):
    """髒值防呆(同 intel/signal_ledger.py):股價/估值區間為 0、負數(下市/停牌 API 常見異常回傳)
    或字面 NaN/inf,絕不能被當成合法值比大小——否則 hit 判定會靜默腐化或拋未捕捉例外。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def load_rows():
    rows = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return rows


def score(min_age_days=90, rows=None, price_fn=price_now, today=None):
    rows = rows if rows is not None else load_rows()
    today = today or datetime.date.today()
    detail = []
    for r in rows:
        try:
            d = datetime.date.fromisoformat(r["date"])
        except Exception:
            continue
        age = (today - d).days
        if age < min_age_days:
            continue
        lo, hi = r.get("dcf_low"), r.get("dcf_high")
        if not _finite_positive(lo) or not _finite_positive(hi):
            continue
        try:
            cur = price_fn(r["symbol"])
        except Exception:
            cur = None
        # 髒值防呆:外部 API 若回傳 0/負數(下市股常見)或字面 "nan"/"inf",float() 不會拋例外
        # 卻會讓 hit 恆假(靜默拉低 hit_rate 不留痕跡),見 lesson calibration_honesty_subgroup_and_null_baseline.md
        if not _finite_positive(cur):
            continue
        hit = lo <= cur <= hi
        detail.append({
            "symbol": r["symbol"], "date": r["date"], "age_days": age,
            "dcf_low": lo, "dcf_high": hi,
            "price_then": r.get("price_now"), "price_now": cur, "hit": hit,
        })
    n = len(detail)
    hits = sum(1 for x in detail if x["hit"])
    result = {
        "min_age_days": min_age_days, "n": n,
        "hit_rate": round(hits / n, 4) if n >= MIN_SAMPLES else None,
        "detail": detail,
    }
    if 0 < n < MIN_SAMPLES:
        result["status"] = "insufficient_data"
        result["reason"] = f"樣本數 {n} < 門檻 {MIN_SAMPLES},hit_rate 暫不採信"
    return result


if __name__ == "__main__":
    min_age = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    result = score(min_age)
    summary = {k: v for k, v in result.items() if k != "detail"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result["n"] == 0:
        print(f"(n=0,尚無 >= {min_age} 天齡的帳本紀錄可計分,累積足夠樣本後重跑)")
    else:
        for row in result["detail"]:
            mark = "✅" if row["hit"] else "❌"
            print(f"  {mark} {row['symbol']} {row['date']}(age={row['age_days']}d) "
                  f"區間[{row['dcf_low']},{row['dcf_high']}] 現價={row['price_now']}")
