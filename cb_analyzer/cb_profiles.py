"""公司營運簡介:curated company_profiles.json(準確、人工查證)為主,
FinMind TaiwanStockInfo 產業分類為自動退路。輸入代碼 → 產業/主營/上下游/客戶/合作。"""
import os, json, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(HERE, "company_profiles.json")
_INDUSTRY_CACHE = os.path.join(HERE, ".industry_cache.json")

_profiles = None
_industry = None


def _load():
    global _profiles, _industry
    if _profiles is None:
        try:
            with open(PROFILES_PATH, encoding="utf-8") as f:
                _profiles = json.load(f)
        except Exception:
            _profiles = {}
    if _industry is None:
        try:
            with open(_INDUSTRY_CACHE, encoding="utf-8") as f:
                _industry = json.load(f)
        except Exception:
            _industry = {}


def _finmind_industry(code):
    """FinMind 產業分類(自動退路),結果快取。"""
    _load()
    if code in _industry:
        return _industry[code]
    try:
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&data_id={code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read().decode()).get("data", [])
        ind = ""
        for x in rows:
            if x.get("stock_id") == code and x.get("industry_category"):
                ind = x["industry_category"]
                break
        _industry[code] = ind
        try:
            with open(_INDUSTRY_CACHE, "w", encoding="utf-8") as f:
                json.dump(_industry, f, ensure_ascii=False)
        except Exception:
            pass
        return ind
    except Exception:
        return ""


def get_profile(code):
    """回 dict(含 industry/business/products/upstream/downstream/customers/partners/note/curated 旗標)。
    curated 有就用,否則只回 FinMind 產業分類 + curated=False。"""
    _load()
    code = str(code).strip()
    p = _profiles.get(code)
    if p:
        out = dict(p)
        out.setdefault("industry", _finmind_industry(code))
        out["curated"] = True
        return out
    return {"industry": _finmind_industry(code), "business": "", "products": [],
            "upstream": "", "downstream": "", "customers": "", "partners": "",
            "note": "", "curated": False}
