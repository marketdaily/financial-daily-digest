"""CB 預測記分器:把 predictions.jsonl 的每筆「曾觸及機率」對答案。
口徑(數學上公平):預測後經過 t 年,用同模型算「t 年內曾觸及機率」當預測值,
對照實際有沒有碰到回本點(當日最高價 >= be_S)→ Brier。這樣不用等 2-3 年到期,
幾週後就開始累積校準樣本;到期(T 滿)的另計最終命中率。
輸出 calibration.json:n≥20 才給 shrink 因子(顯示端 cb_ledger.apply_calibration 讀取)。
用法:cd cb_analyzer && python3 cb_score.py
"""
import os, json, datetime, time, urllib.request
import cb_core

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "predictions.jsonl")
CALIB = os.path.join(HERE, "calibration.json")
PRICE_CACHE = os.path.join(HERE, ".score_price_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
MIN_AGE_DAYS = 14


def _highs(code, start):
    """回 {date: 當日最高價}。當日快取。"""
    try:
        with open(PRICE_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    today = datetime.date.today().isoformat()
    ck = f"{code}:{start}"
    if cache.get("_day") == today and ck in cache:
        return cache[ck]
    url = f"{FINMIND}?dataset=TaiwanStockPrice&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read().decode()).get("data", [])
    except Exception:
        return None
    out = {x["date"]: x.get("max") for x in rows if x.get("max")}
    if cache.get("_day") != today:
        cache = {"_day": today}
    cache[ck] = out
    try:
        with open(PRICE_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return out


def score():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        print("帳本還是空的,等 cb_server 跑過分析就會有。")
        return None
    today = datetime.date.today()
    interim, finals, details = [], [], []
    highs_by_key = {}
    for r in rows:
        d0 = datetime.date.fromisoformat(r["date"])
        age_days = (today - d0).days
        if age_days < MIN_AGE_DAYS:
            continue
        key = (r["stock_code"], r["date"])
        if key not in highs_by_key:
            highs_by_key[key] = _highs(r["stock_code"], r["date"])
            time.sleep(0.4)
        highs = highs_by_key[key]
        if highs is None:
            continue
        touched = any(h >= r["be_S"] for dt, h in highs.items() if dt > r["date"])
        t_elapsed = min(age_days / 365.0, r["T"])
        p_interim = cb_core.touch_prob(r["spot"], r["be_S"], t_elapsed, r["vol"], r["drift"])
        o = 1 if touched else 0
        interim.append((p_interim, o))
        if touched or age_days / 365.0 >= r["T"]:
            finals.append((r["p_touch"], o))
        details.append({"bond": r["bond_code"], "date": r["date"], "age_d": age_days,
                        "p_interim": round(p_interim, 3), "touched": touched})
    out = {"updated": today.isoformat(), "n_rows": len(rows), "n_interim": len(interim),
           "n_final": len(finals)}
    if interim:
        n = len(interim)
        out["brier_interim"] = round(sum((p - o) ** 2 for p, o in interim) / n, 4)
        out["coin_flip_brier"] = 0.25
        out["avg_pred_interim"] = round(sum(p for p, _ in interim) / n, 4)
        out["realized_interim"] = round(sum(o for _, o in interim) / n, 4)
        if n >= 20 and out["avg_pred_interim"] > 0.05:
            out["shrink"] = round(max(0.6, min(1.1, out["realized_interim"] / out["avg_pred_interim"])), 3)
        else:
            out["shrink"] = None
            out["note"] = f"樣本 {n} 筆 <20,校準閘門未開(小樣本校準=雜訊)"
    if finals:
        out["final_hit_rate"] = round(sum(o for _, o in finals) / len(finals), 4)
        out["final_avg_pred"] = round(sum(p for p, _ in finals) / len(finals), 4)
    out["details"] = details[-40:]
    with open(CALIB, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "details"}, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    score()
