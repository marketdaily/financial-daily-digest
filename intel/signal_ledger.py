"""信息差訊號回測帳本(P2.6 第四步·回測軸:把「預測→記帳→對答案」骨架複製到 CB/估值之外)。
12 個 intel connector 每晚產出 by_code 紅黃訊號,但從未被記下來——不知道這些訊號事後有沒有
價格反應。仿 valuation/ledger.py+score_ledger.py 同款紀律:
- record() 只 append,不重寫舊列(讀全檔重建已出現過的 (code, source, level) 組合集合,同一
  組合持續中不重複記,沿用 patrol.py::_red_pairs 同款去重精神,只是擴及 yellow 並存下訊號當下
  股價)。**key 必須到 level 這層,不能只到 (code, source)**:同一 source 對同一 code 可能同時
  發出多筆不同 level 訊號(例如 us_insider 同一天有人買有人賣),曾踩過只到 source 層級的 key
  被兩筆訊號輪流覆蓋成對方 level、判定成「無限次都是新變化」的坑,見 record() 內註解。
- score() 是純函式(不改帳本),對滿齡的列即時查現價算事後報酬,依 source×level 分組回報
  平均/中位數/正報酬比例。**故意不下「有沒有 edge」結論**:red/yellow 是「訊號強度」,不是
  「看多/看空」——不同來源方向語意差很多(例如 us_insider 的 red 是內部人群聚買進偏多方,
  tw_institutional 的 red 常是法人連賣偏空方),誤加統一方向標籤反而製造假結論,方向判斷留給
  人工逐 source 深攻。

CLI: python3 -m intel.signal_ledger score
"""
import os
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "signal_ledger.jsonl")
MIN_AGE_DAYS = 5  # 近似交易日(日曆日),同 score_ledger.py 慣例不強求精確交易日曆

try:
    from valuation.ledger import price_now
except Exception:
    price_now = None


def _load_seen_keys():
    """回 {(code, source, level)} 已寫入過的組合。key 必須到 level 這層——踩過的坑:若只到
    (code, source),同一 source 對同一 code 同時發出多筆不同 level 的訊號時(例如美股內部人
    同一天有人買有人賣,us_insider 對同一 code 一次給 red+yellow 兩筆),兩筆會輪流把「最後狀態」
    覆蓋成對方的 level,導致每次巡邏都被誤判成「有變化」而無限重複寫入同一組合。"""
    seen = set()
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    seen.add((r["code"], r["source"], r["level"]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seen


def record(by_code, date=None, price_fn=price_now):
    """由 patrol.py 每晚呼叫。絕不拋錯——任何失敗只回 0,不拖垮呼叫端。
    回傳這次新寫入的列數。"""
    if not by_code or price_fn is None:
        return 0
    date = date or datetime.date.today().isoformat()
    try:
        seen = _load_seen_keys()
    except Exception:
        seen = set()
    new_rows = []
    for code, items in by_code.items():
        for item in items:
            source = item.get("source")
            level = item.get("level")
            if not source or level not in ("red", "yellow"):
                continue
            key = (code, source, level)
            if key in seen:
                continue  # 這個 (code,source,level) 組合已記過(持續中或曾出現過),不重複記
            try:
                price = price_fn(code)
            except Exception:
                price = None
            new_rows.append({
                "date": date, "code": code, "source": source, "level": level,
                "signal": item.get("signal", ""), "price_at_signal": price,
            })
            seen.add(key)
    if not new_rows:
        return 0
    try:
        with open(LEDGER, "a", encoding="utf-8") as f:
            for r in new_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return len(new_rows)


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


def score(min_age_days=MIN_AGE_DAYS, rows=None, price_fn=price_now, today=None):
    """純函式,不改帳本——每次呼叫即時查現價算事後報酬。樣本不足誠實回 n=0。"""
    rows = rows if rows is not None else load_rows()
    today = today or datetime.date.today()
    detail = []
    for r in rows:
        if r.get("price_at_signal") is None:
            continue
        try:
            d = datetime.date.fromisoformat(r["date"])
        except Exception:
            continue
        age = (today - d).days
        if age < min_age_days:
            continue
        try:
            cur = price_fn(r["code"]) if price_fn else None
        except Exception:
            cur = None
        if cur is None:
            continue
        pct = round((cur - r["price_at_signal"]) / r["price_at_signal"] * 100, 2)
        detail.append({
            "code": r["code"], "source": r["source"], "level": r["level"],
            "date": r["date"], "age_days": age,
            "price_at_signal": r["price_at_signal"], "price_now": cur, "outcome_pct": pct,
        })
    groups = {}
    for row in detail:
        groups.setdefault(f"{row['source']}|{row['level']}", []).append(row["outcome_pct"])
    summary = {}
    for k, vals in groups.items():
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        summary[k] = {
            "n": n,
            "mean_pct": round(sum(vals_sorted) / n, 2),
            "median_pct": vals_sorted[n // 2],
            "pct_positive": round(sum(1 for v in vals_sorted if v > 0) / n * 100, 1),
        }
    return {"min_age_days": min_age_days, "n_scored": len(detail), "groups": summary, "detail": detail}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "score":
        result = score()
        summary = {k: v for k, v in result.items() if k != "detail"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if result["n_scored"] == 0:
            print(f"(n=0,尚無 >= {MIN_AGE_DAYS} 天齡且有 price_at_signal 的紀錄可計分)")
    else:
        print("usage: python3 -m intel.signal_ledger score")
