"""MOPS 巡邏連接器(信息差引擎積木 #2):重大訊息 + 月營收,上市+上櫃全覆蓋。
免費 JSON、免金鑰,一次抓全市場再過濾 watchlist——別人懶得逐日看,機器天天看=最便宜的信息差。
訊號定義:
  重訊 🔴:庫藏股/併購/私募/增資/發可轉債/減資/財測/下市(結構性事件,CB 玩家必須第一時間知道)
  重訊 🟡:處分或取得資產/資金貸與/背書保證/高層異動/訴訟
  月營收:新公告即報,YoY ±20% 標 🔴,其餘 🟡;同時給 MoM 與累計 YoY 對照
"""
import os, json, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REV_CACHE = os.path.join(HERE, ".rev_cache.json")

ENDPOINTS_NEWS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
]
ENDPOINTS_REV = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
]

RED_KW = ["庫藏股", "合併", "收購", "公開收購", "私募", "現金增資", "轉換公司債", "減資", "下市", "財務預測", "分割"]
YELLOW_KW = ["處分", "取得", "資金貸與", "背書保證", "總經理", "董事長", "財務主管", "訴訟", "異動"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def _roc_to_date(s):
    """ROC 日期字串 '1150701' → date(2026,7,1)。壞格式回 None。"""
    s = str(s or "").strip()
    if len(s) != 7 or not s.isdigit():
        return None
    try:
        return datetime.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None


def _news_level(subject):
    for kw in RED_KW:
        if kw in subject:
            return "red", kw
    for kw in YELLOW_KW:
        if kw in subject:
            return "yellow", kw
    return "plain", ""


def major_news(codes, days=3):
    """近 N 日 watchlist 公司的重大訊息,附分級。回 list[dict] 新到舊。"""
    codes = {str(c) for c in codes}
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out = []
    for url in ENDPOINTS_NEWS:
        try:
            rows = _get(url)
        except Exception:
            continue
        for x in rows:
            code = str(x.get("公司代號") or x.get("SecuritiesCompanyCode") or "").strip()
            if code not in codes:
                continue
            d = _roc_to_date(x.get("發言日期") or x.get("Date"))
            if not d or d < cutoff:
                continue
            subject = " ".join((x.get("主旨 ") or x.get("主旨") or "").split())
            level, kw = _news_level(subject)
            out.append({
                "code": code, "name": (x.get("公司名稱") or x.get("CompanyName") or "").strip(),
                "date": d.isoformat(), "subject": subject, "level": level, "keyword": kw,
            })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def revenue_updates(codes):
    """月營收新公告偵測:資料年月比快取新的才回報(=真的剛公告)。回 list[dict]。"""
    codes = {str(c) for c in codes}
    try:
        with open(REV_CACHE, encoding="utf-8") as f:
            seen = json.load(f)
    except Exception:
        seen = {}
    out = []
    for url in ENDPOINTS_REV:
        try:
            rows = _get(url)
        except Exception:
            continue
        for x in rows:
            code = str(x.get("公司代號") or "").strip()
            if code not in codes:
                continue
            ym = str(x.get("資料年月") or "").strip()
            if not ym or seen.get(code) == ym:
                continue
            yoy = _to_float(x.get("營業收入-去年同月增減(%)"))
            mom = _to_float(x.get("營業收入-上月比較增減(%)"))
            cum = _to_float(x.get("累計營業收入-前期比較增減(%)"))
            level = "red" if yoy is not None and abs(yoy) >= 20 else "yellow"
            out.append({
                "code": code, "name": (x.get("公司名稱") or "").strip(), "ym": ym,
                "yoy": yoy, "mom": mom, "cum_yoy": cum, "level": level,
                "signal": _rev_signal(ym, yoy, mom, cum),
            })
            seen[code] = ym
    if out:
        try:
            with open(REV_CACHE, "w", encoding="utf-8") as f:
                json.dump(seen, f, ensure_ascii=False)
        except Exception:
            pass
    return out


def _rev_signal(ym, yoy, mom, cum):
    m = f"{int(ym[:3]) + 1911}/{ym[3:]}" if len(ym) == 5 else ym
    parts = [f"{m} 營收公告"]
    if yoy is not None:
        parts.append(f"YoY {yoy:+.1f}%" + ("(強勁)" if yoy >= 20 else ("(衰退)" if yoy <= -20 else "")))
    if mom is not None:
        parts.append(f"MoM {mom:+.1f}%")
    if cum is not None and yoy is not None and (cum > 0) != (yoy > 0):
        parts.append("⚠️ 當月與累計 YoY 方向相反=可能轉折")
    return "、".join(parts)
