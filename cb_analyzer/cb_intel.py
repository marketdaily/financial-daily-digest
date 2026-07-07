"""市場情報:把外資/投信買賣超(FinMind,即時可靠)+ 法說會/外資目標價(研究快取 company_intel.json)
接到 CB 分析,強化「為什麼會漲」論點與校準成長率。缺研究快取時只用法人流向。"""
import os
import json
import datetime
import urllib.request

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


def _tp_age_days(r):
    """目標價資料齡(天)。依序取 target_date > updated > conference_date;無日期回 None。"""
    ds = r.get("target_date") or r.get("updated") or r.get("conference_date")
    if not ds:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            d = datetime.datetime.strptime(str(ds).strip(), fmt).date()
            return (datetime.date.today() - d).days
        except ValueError:
            continue
    return None


def intel_lines(code, spot=None):
    """給報告用的情報行 list(法人流向 + 研究快取重點)。上檔空間依現價動態計算。
    券商目標價紀律:來源券商+日期是強制欄位,缺了就明示「來源不明勿引用」;
    逾 90 天標過期;非原始報告(新聞轉述)且無出處連結也明示——確認狀態永遠可見。"""
    lines = []
    fn = flow_narrative(code)
    if fn:
        lines.append(fn)
    r = research(code)
    if r:
        tp = r.get("target_price")
        if tp:
            up = (tp / spot - 1) * 100 if spot else None
            seg = f"券商目標價 {tp}"
            age = _tp_age_days(r)
            if r.get("broker"):
                seg += f"({r['broker']}" + (f",{age}天前" if age is not None else ",日期不明") + ")"
            else:
                seg += "(⚠ 來源券商不明,勿引用)"
            if up is not None:
                seg += (f",隱含上檔 {up:+.0f}%" if up > 0
                        else f",⚠現價已超越目標價 {abs(up):.0f}%(目標偏保守/落後)")
            if age is not None and age > 90:
                seg += f" ⚠已逾{age}天未確認,需重查"
            if not r.get("source_url"):
                seg += "(新聞轉述,未附出處連結)"
            lines.append(seg)
            if r.get("source_url"):
                lines.append(f"目標價出處:{r['source_url']}")
        if r.get("conference_date"):
            lines.append(f"最近法說會:{r['conference_date']}")
        for t in (r.get("takeaways") or [])[:3]:
            lines.append(f"法說重點:{t}")
        for c in (r.get("catalysts") or [])[:2]:
            lines.append(f"催化劑:{c}")
        if r.get("note"):
            lines.append(f"⚠ {r['note']}")
    return lines
