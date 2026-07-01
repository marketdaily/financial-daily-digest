"""市場情報:把外資/投信買賣超(FinMind,即時可靠)+ 法說會/外資目標價(研究快取 company_intel.json)
接到 CB 分析,強化「為什麼會漲」論點與校準成長率。缺研究快取時只用法人流向。"""
import os, json, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
INTEL_PATH = os.path.join(HERE, "company_intel.json")
FLOW_CACHE = os.path.join(HERE, ".flow_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _finmind(dataset, code, start):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data", [])


def _cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def institutional_flow(code, today=None):
    """外資+投信近5/20日淨買賣(張)。回 dict 或 None。快取當日。"""
    today = today or datetime.date.today()
    c = _cache(FLOW_CACHE)
    ck = f"{code}:{today.isoformat()}"
    if ck in c:
        return c[ck]
    start = (today - datetime.timedelta(days=45)).isoformat()
    try:
        d = _finmind("TaiwanStockInstitutionalInvestorsBuySell", code, start)
    except Exception:
        return None
    if not d:
        return None
    def net(name, k):
        rows = [x for x in d if x.get("name") == name]
        return sum((x.get("buy", 0) - x.get("sell", 0)) for x in rows[-k:]) / 1000.0
    out = {
        "foreign_5d": round(net("Foreign_Investor", 5)),
        "foreign_20d": round(net("Foreign_Investor", 20)),
        "trust_20d": round(net("Investment_Trust", 20)),
        "date": d[-1].get("date"),
    }
    tot = out["foreign_20d"] + out["trust_20d"]
    out["signal"] = "法人買超(認同)" if tot > 200 else ("法人賣超(短線逆風)" if tot < -200 else "法人中性")
    c[ck] = out
    try:
        with open(FLOW_CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception:
        pass
    return out


def flow_narrative(code):
    f = institutional_flow(code)
    if not f:
        return ""
    return (f"法人流向:外資近20日淨{'買' if f['foreign_20d']>=0 else '賣'}{abs(f['foreign_20d']):,}張、"
            f"投信淨{'買' if f['trust_20d']>=0 else '賣'}{abs(f['trust_20d']):,}張 → {f['signal']}")


def research(code):
    """讀研究快取(法說會重點/外資目標價/催化劑)。無則回 None。
    company_intel.json 由研究 agent 產,格式:{code:{target_price, target_upside_pct,
      broker, conference_date, takeaways:[...], catalysts:[...], updated}}。"""
    return _cache(INTEL_PATH).get(str(code))


def implied_drift(code, spot):
    """若研究快取有外資目標價 → 反推年化隱含報酬(校準模擬漂移用)。回 float 或 None。"""
    r = research(code)
    if not r:
        return None
    tp = r.get("target_price")
    horizon = r.get("target_horizon_year", 1.0)
    if tp and spot and spot > 0:
        return (tp / spot) ** (1 / max(horizon, 0.25)) - 1
    return None


def intel_lines(code, spot=None):
    """給報告用的情報行 list(法人流向 + 研究快取重點)。"""
    lines = []
    fn = flow_narrative(code)
    if fn:
        lines.append(fn)
    r = research(code)
    if r:
        if r.get("target_price"):
            up = r.get("target_upside_pct")
            lines.append(f"外資目標價:{r['target_price']}"
                         + (f"(隱含上檔 {up:+.0f}%" + (f",{r['broker']}" if r.get('broker') else "") + ")" if up is not None else "")
                         + (f",約 {r.get('target_horizon_year',1)} 年" if r.get('target_horizon_year') else ""))
        if r.get("conference_date"):
            lines.append(f"最近法說會:{r['conference_date']}")
        for t in (r.get("takeaways") or [])[:3]:
            lines.append(f"法說重點:{t}")
        for c in (r.get("catalysts") or [])[:3]:
            lines.append(f"催化劑:{c}")
    return lines
