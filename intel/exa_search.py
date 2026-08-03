"""exa_search 連接器——Exa 語意搜尋深度事件雷達(市場級,2026-08-03 API/MCP 部接線)。

資料源:Exa /search(LLM 原生語意搜尋,免費層每月自動送 $10≈1400 次 basic search;
帳號=delvin.12345678@gmail.com,EXA_API_KEY 在 .env)。

為什麼是信息差:RSS/NewsAPI 只給「媒體推什麼」,Exa 神經搜尋能撈「語意相關但不在
feed 裡」的內容(冷門產業刊物/官方文件評述)。每日 4 個固定主題查詢,補 news_signals
的盲區,產市場級 broad themes。

額度紀律(部門紅線=零付費,免費額度也要守):每日 patrol 只跑 1 輪 × 4 查詢,
月計數器硬上限 MONTHLY_CAP,超了整月靜默休眠(fail-open 回 None,不打擾)。

用法:
  patrol 夜巡呼叫 market_signal();手動: python3 -m intel.exa_search --dry
"""
import os
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "exa_search_ledger.jsonl")
BUDGET = os.path.join(HERE, ".exa_budget.json")

MONTHLY_CAP = 800          # 免費層 ~1400/月,只用一半留餘裕給互動查詢
QUERIES = [
    ("semis", "semiconductor supply chain disruption or export controls this week"),
    ("rates", "Federal Reserve policy shift or surprise inflation data this week"),
    ("taiwan", "Taiwan stock market foreign investor flows or TSMC major news this week"),
    ("ai_capex", "AI datacenter capex cuts or major cloud spending change this week"),
]
RESULTS_PER_QUERY = 5


def _month():
    return datetime.date.today().strftime("%Y-%m")


def _budget_used():
    try:
        with open(BUDGET, encoding="utf-8") as f:
            b = json.load(f)
        return b.get("used", 0) if b.get("month") == _month() else 0
    except Exception:
        return 0


def _budget_add(n):
    try:
        with open(BUDGET, "w", encoding="utf-8") as f:
            json.dump({"month": _month(), "used": _budget_used() + n}, f)
    except Exception:
        pass


def _seen_urls():
    urls = set()
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    urls.add(json.loads(line).get("url"))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return urls


def _search(query):
    key = os.environ.get("EXA_API_KEY")
    if not key:
        raise RuntimeError("未設定 EXA_API_KEY")
    payload = json.dumps({
        "query": query, "type": "auto", "category": "news",
        "numResults": RESULTS_PER_QUERY,
        "contents": {"highlights": True, "maxAgeHours": 48},
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/search", data=payload,
        headers={"x-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("results", [])


def classify(results, seen):
    """純函式:結果列表 → 新鮮條目(去重過)。可測。"""
    fresh = []
    for r in results:
        url = r.get("url")
        if not url or url in seen:
            continue
        hl = r.get("highlights") or []
        fresh.append({"url": url, "title": (r.get("title") or "")[:160],
                      "highlight": (hl[0] if hl else "")[:300],
                      "published": (r.get("publishedDate") or "")[:10]})
    return fresh


def market_signal(dry=False):
    """每日一輪 4 主題查詢 → {"themes": {tag: [新條目...]}, "new": N}。額度不足/無 key → None。"""
    if _budget_used() + len(QUERIES) > MONTHLY_CAP:
        print(f"  [exa] 月額度已用 {_budget_used()}/{MONTHLY_CAP},本月休眠")
        return None
    seen = _seen_urls()
    themes, new_items = {}, []
    calls = 0
    for tag, q in QUERIES:
        try:
            results = _search(q)
            calls += 1
        except Exception as e:
            print(f"  [exa] {tag} 查詢失敗(fail-open): {e}")
            continue
        fresh = classify(results, seen)
        if fresh:
            themes[tag] = fresh
            new_items.extend({"tag": tag, **it} for it in fresh)
    if not dry:
        _budget_add(calls)
        if new_items:
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            with open(LEDGER, "a", encoding="utf-8") as f:
                for it in new_items:
                    f.write(json.dumps({"ts": ts, **it}, ensure_ascii=False) + "\n")
    return {"themes": themes, "new": len(new_items),
            "budget_used": _budget_used(), "budget_cap": MONTHLY_CAP}


def _selftest():
    seen = {"https://a.com/1"}
    res = [{"url": "https://a.com/1", "title": "dup"},
           {"url": "https://b.com/2", "title": "fresh", "highlights": ["hi"], "publishedDate": "2026-08-03T00:00:00Z"},
           {"title": "no-url"}]
    out = classify(res, seen)
    assert len(out) == 1 and out[0]["url"] == "https://b.com/2" and out[0]["published"] == "2026-08-03"
    assert classify([], set()) == []
    print("selftest ok")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sig = market_signal(dry="--dry" in sys.argv)
        print(json.dumps(sig, ensure_ascii=False, indent=1) if sig else "None")
