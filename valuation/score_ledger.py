"""估值帳本計分:回頭驗證「當時記下的 DCF 合理價區間,有沒有真的框住之後的股價」。
DCF 是中長期估值(兩階段折現假設 5 年+永續),不是短線訊號,min_age_days 預設 90 天,
樣本不足(帳本剛起步/尚未滿齡)一律誠實回報 n=0,絕不硬湊數字。
CLI: python3 valuation/score_ledger.py [min_age_days=90]
"""
import os
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ledger import LEDGER, price_now  # noqa: E402


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
        if lo is None or hi is None:
            continue
        try:
            cur = price_fn(r["symbol"])
        except Exception:
            cur = None
        if cur is None:
            continue
        hit = lo <= cur <= hi
        detail.append({
            "symbol": r["symbol"], "date": r["date"], "age_days": age,
            "dcf_low": lo, "dcf_high": hi,
            "price_then": r.get("price_now"), "price_now": cur, "hit": hit,
        })
    n = len(detail)
    hits = sum(1 for x in detail if x["hit"])
    return {
        "min_age_days": min_age_days, "n": n,
        "hit_rate": round(hits / n, 4) if n else None,
        "detail": detail,
    }


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
