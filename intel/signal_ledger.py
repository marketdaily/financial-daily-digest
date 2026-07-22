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
- 結算端 CA 守衛(2026-07-17,price_integrity 稽核前置):price_at_signal→price_now 皆 raw
  未還原價,持有窗跨分割/減資/大額配股=假報酬(0050 分割 raw -74.8% 假懸崖同款)。score()
  預設逐列掃窗內 CA(intel/ca_settlement_guard.py),嫌疑/無法核實列排除統計但分開計數可見
  (feedback_no_silent_limits:不靜默丟)。

CLI: python3 -m intel.signal_ledger score
"""
import os
import sys
import json
import math
import random
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "signal_ledger.jsonl")
MIN_AGE_DAYS = 5  # 近似交易日(日曆日),同 score_ledger.py 慣例不強求精確交易日曆
MIN_SUBGROUP = 8  # source×level 子分組最小樣本數,不足只回 n(同 cb-desk alert_ledger 誠實鐵則)
MIN_DISTINCT_DAYS = 15  # 日多樣性閘門下限,比對的是「有效獨立日」eff_days=(Σn)²/Σn²(非原始日期數):
                        # 樣本再多若集中在極少數重日,事後報酬≈那幾天大盤 beta 被同一天多檔量 n 次,
                        # 有效獨立樣本是「日」不是 n。用 Herfindahl 有效日而非原始 distinct_days,才擋得掉
                        # 「15 個日期但一天灌爆」的假多樣性(驗證者 HIGH-1)。對齊
                        # capability_daycluster_degenerate_guard 的 TRUST_FLOOR=15(同一小樣本假信心根因)。


def _finite_positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0

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


def _daycluster_ci(day_buckets, n_boot=2000, seed=1729, lo=5, hi=95):
    """對「平均事後報酬」做日叢集(block)bootstrap 90% CI。
    day_buckets: list[list[float]]——每個內層 list = 同一訊號日的 outcome_pct 們。
    **重抽的是「日」不是「單筆訊號」**:同一個大盤日不可假冒成多個獨立觀測(這正是
    naive 點估計對日叢集資料失真的根因)。同 capability_daycluster_degenerate_guard 的
    區塊重抽精神。固定 seed → 可重現(deterministic)。日數 <2 無法重抽,回 (None, None)。"""
    days = [b for b in day_buckets if b]
    k = len(days)
    if k < 2:
        return None, None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        pooled = []
        for _ in range(k):
            pooled.extend(days[rng.randrange(k)])
        if pooled:
            means.append(sum(pooled) / len(pooled))
    if not means:
        return None, None
    means.sort()
    m = len(means)

    def _pct(p):
        idx = min(m - 1, max(0, int(round(p / 100.0 * (m - 1)))))
        return round(means[idx], 2)
    lo_v, hi_v = _pct(lo), _pct(hi)
    if hi_v - lo_v < 1e-9:
        # 退化守衛:寬度≈0 的點 CI 不可採信(這正是 capability_daycluster_degenerate_guard
        # 命名的「假性收窄成確定點」塌縮;零變異=每個 bootstrap 均值都一樣)。誠實回 None。
        return None, None
    return lo_v, hi_v


_CA_GUARD_DEFAULT = object()  # sentinel:預設接真守衛;顯式傳 None=關(輸出會標 ca_guard=off)


def score(min_age_days=MIN_AGE_DAYS, rows=None, price_fn=price_now, today=None,
          min_distinct_days=MIN_DISTINCT_DAYS, ca_check_fn=_CA_GUARD_DEFAULT):
    """純函式,不改帳本——每次呼叫即時查現價算事後報酬。樣本不足誠實回 n=0。

    三道誠實閘(缺一就會用小樣本假信心誤導判斷):
    1. n<MIN_SUBGROUP → insufficient_data(子分組樣本太少)。
    2. eff_days<min_distinct_days → insufficient_day_diversity:有效獨立日(Herfindahl (Σn)²/Σn²)
       不足,mean/pct_positive 其實只是「那幾天大盤 beta」量了 n 次,不呈現為有效數字;naive 值
       降級標示保留(不靜默丟)。通過兩閘的組另附日叢集 bootstrap 90% CI(零寬退化時回 None)。
    3. 結算端 CA 守衛:持有窗內有分割/減資/大額配股簽名(suspect)或無法核實(unknown)的列
       排除統計——raw 價跨 CA 的報酬是機械假象非市場反應。排除列仍留在 detail(帶 ca_status)
       且逐組計數 n_ca_suspect/n_ca_unknown,絕不靜默丟。ca_check_fn 顯式傳 None=關守衛
       (輸出 ca_guard=off,列標 unchecked);預設自動接 intel/ca_settlement_guard(ca_guard=on;
       建構失敗=unavailable,同樣可見)。"""
    rows = rows if rows is not None else load_rows()
    today = today or datetime.date.today()
    guard_mode = "on"
    if ca_check_fn is _CA_GUARD_DEFAULT:
        try:
            from intel.ca_settlement_guard import make_ca_check_fn
            ca_check_fn = make_ca_check_fn(today=today)
        except Exception:
            ca_check_fn, guard_mode = None, "unavailable"
    elif ca_check_fn is None:
        guard_mode = "off"
    detail = []
    for r in rows:
        if not _finite_positive(r.get("price_at_signal")):
            continue  # 髒值防呆:0/負數/NaN 的訊號當下股價會讓報酬率除零或炸出離譜%,寧可跳過不算
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
        if not _finite_positive(cur):
            continue
        pct = round((cur - r["price_at_signal"]) / r["price_at_signal"] * 100, 2)
        ca_status = "unchecked"
        if ca_check_fn is not None:
            try:
                ca = ca_check_fn(r["code"], r["date"])
                ca_status = ca.get("status") if isinstance(ca, dict) else "unknown"
            except Exception:
                ca_status = "unknown"
            if ca_status not in ("clean", "suspect", "unknown"):
                ca_status = "unknown"  # 守衛回怪值不可默認乾淨(fail-closed)
        detail.append({
            "code": r["code"], "source": r["source"], "level": r["level"],
            "date": r["date"], "age_days": age,
            "price_at_signal": r["price_at_signal"], "price_now": cur, "outcome_pct": pct,
            "ca_status": ca_status,
        })
    groups = {}
    ca_excluded = {}  # key -> {"suspect": n, "unknown": n}(排除統計但逐組可見)
    for row in detail:
        k = f"{row['source']}|{row['level']}"
        if row["ca_status"] in ("suspect", "unknown"):
            c = ca_excluded.setdefault(k, {"suspect": 0, "unknown": 0})
            c[row["ca_status"]] += 1
            continue
        groups.setdefault(k, []).append(row)
    summary = {}
    for k, rowset in groups.items():
        vals = sorted(r["outcome_pct"] for r in rowset)
        n = len(vals)
        # 依訊號日分桶(下方 CI 取 sorted(buckets) → CI 是資料多重集的純函式,與列順序無關)。
        buckets = {}
        for r in rowset:
            buckets.setdefault(r["date"], []).append(r["outcome_pct"])
        distinct_days = len(buckets)
        day_sizes = [len(v) for v in buckets.values()]
        # 有效獨立日(Herfindahl (Σn)²/Σn²):量測不只「幾個日期」而是「日集中度」。單日灌爆時
        # eff_days≪distinct_days,擋掉「15 個日期但其實一天 50 檔」的假多樣性——否則單日假信心只是
        # 從『1 日 n 檔』位移到『多日期但 1 重日』(驗證者 HIGH-1)。點估計 count-weighted,eff_days
        # 閘確保沒有單日能主宰它。
        eff_days = round(sum(day_sizes) ** 2 / sum(s * s for s in day_sizes), 2) if day_sizes else 0.0
        naive_mean = round(sum(vals) / n, 2)
        naive_median = round((vals[(n - 1) // 2] + vals[n // 2]) / 2, 2)  # 偶數 n 取兩中位平均
        naive_pos = round(sum(1 for v in vals if v > 0) / n * 100, 1)
        base = {"n": n, "distinct_days": distinct_days, "eff_days": eff_days}
        if n < MIN_SUBGROUP:
            # 子分組樣本閘門(VERIFIER 教訓,lesson calibration_honesty_subgroup_and_null_baseline.md):
            # 舊版 n=1 也會印 pct_positive=100.0 像有把握的訊號——樣本不足只回 n。
            summary[k] = {**base, "status": "insufficient_data",
                          "mean_pct": None, "median_pct": None, "pct_positive": None, "ci90_pct": None}
            continue
        if eff_days < min_distinct_days:
            # 日多樣性閘門:有效獨立日不足 → mean/pct_positive 只是那幾天大盤 beta 被同一天多檔量了
            # n 次,有效獨立樣本≈天數而非 n。不呈現為有效數字(避免 authoritative 假信心),naive 值
            # 降級標示保留(feedback_no_silent_limits)。
            summary[k] = {**base, "status": "insufficient_day_diversity",
                          "mean_pct": None, "median_pct": None, "pct_positive": None, "ci90_pct": None,
                          "naive_mean_pct": naive_mean, "naive_pct_positive": naive_pos}
            continue
        ci_lo, ci_hi = _daycluster_ci([buckets[d] for d in sorted(buckets)])
        summary[k] = {
            **base, "status": "ok",
            "mean_pct": naive_mean, "median_pct": naive_median, "pct_positive": naive_pos,
            "ci90_pct": [ci_lo, ci_hi] if ci_lo is not None else None,  # None=退化零寬,見 _daycluster_ci
        }
    for k, c in ca_excluded.items():
        if k not in summary:  # 該組全數被守衛排除:仍要有條目,計數不可消失
            summary[k] = {"n": 0, "distinct_days": 0, "eff_days": 0.0,
                          "status": "insufficient_data", "mean_pct": None,
                          "median_pct": None, "pct_positive": None, "ci90_pct": None}
        summary[k]["n_ca_suspect"] = c["suspect"]
        summary[k]["n_ca_unknown"] = c["unknown"]
    for k in summary:
        summary[k].setdefault("n_ca_suspect", 0)
        summary[k].setdefault("n_ca_unknown", 0)
    n_included = sum(1 for r in detail if r["ca_status"] in ("clean", "unchecked"))
    return {"min_age_days": min_age_days, "min_distinct_days": min_distinct_days,
            "ca_guard": guard_mode,
            "n_scored": n_included,
            "n_ca_suspect": sum(c["suspect"] for c in ca_excluded.values()),
            "n_ca_unknown": sum(c["unknown"] for c in ca_excluded.values()),
            "groups": summary, "detail": detail}


def audit(rows=None, today=None, min_age_days=MIN_AGE_DAYS):
    """唯讀 hygiene 稽核:回報各 source 的 price_at_signal 涵蓋率、可驗證(滿齡+有價)筆數、
    與獨立訊號日數——回答「哪些源做得到驗真 / 還差多少獨立日」。不改帳本。
    (揭露：price_at_signal=null 的源永遠算不出事後報酬,例如 revenue/us_* 目前全 null。)"""
    rows = rows if rows is not None else load_rows()
    today = today or datetime.date.today()
    by_src = {}
    for r in rows:
        s = r.get("source", "?")
        d = by_src.setdefault(s, {"total": 0, "has_price": 0, "mature_priced": 0, "days": set()})
        d["total"] += 1
        has_price = _finite_positive(r.get("price_at_signal"))
        if has_price:
            d["has_price"] += 1
        try:
            age = (today - datetime.date.fromisoformat(r["date"])).days
        except Exception:
            age = -1
        if has_price and age >= min_age_days:
            d["mature_priced"] += 1
            d["days"].add(r["date"])
    out = {}
    for s, d in by_src.items():
        out[s] = {
            "total": d["total"], "has_price": d["has_price"],
            "price_coverage_pct": round(d["has_price"] / d["total"] * 100, 1) if d["total"] else 0.0,
            "mature_priced": d["mature_priced"], "distinct_mature_days": len(d["days"]),
        }
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "score":
        result = score()
        summary = {k: v for k, v in result.items() if k != "detail"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if result.get("ca_guard") != "on":
            print(f"(⚠️ CA 守衛未生效(ca_guard={result.get('ca_guard')}):事後報酬未經"
                  f"公司行動核實,跨分割/減資/大額配股的列是假報酬,勿據此下結論。)")
        if result.get("n_ca_suspect") or result.get("n_ca_unknown"):
            print(f"(🛡️ CA守衛:{result['n_ca_suspect']} 筆持有窗內有公司行動嫌疑"
                  f"+{result['n_ca_unknown']} 筆無法核實,已排除統計(raw 價跨分割/減資/大額配股"
                  f"=假報酬)。unknown 多半是資料源暫時抓不到,下次執行自動重試。)")
        if result["n_scored"] == 0:
            print(f"(n=0,尚無 >= {MIN_AGE_DAYS} 天齡且有 price_at_signal 的紀錄可計分)")
        else:
            nd = sum(1 for v in result["groups"].values()
                     if v.get("status") == "insufficient_day_diversity")
            if nd:
                print(f"(⚠️ {nd} 組樣本足但擠在 <{MIN_DISTINCT_DAYS} 個獨立訊號日 → 事後報酬只是那幾天"
                      f"大盤 beta,不足採信;待帳本累積更多獨立日才有意義。這是誠實閘,非 bug。"
                      f" 用 `audit` 看各源涵蓋率與還差多少獨立日。)")
    elif cmd == "audit":
        print(json.dumps(audit(), ensure_ascii=False, indent=2))
    else:
        print("usage: python3 -m intel.signal_ledger score|audit")
