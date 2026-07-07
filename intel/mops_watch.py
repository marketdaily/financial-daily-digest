"""MOPS 巡邏連接器(信息差引擎積木 #2):重大訊息 + 月營收,上市+上櫃全覆蓋。
免費 JSON、免金鑰,一次抓全市場再過濾 watchlist——別人懶得逐日看,機器天天看=最便宜的信息差。
訊號定義:
  重訊 🔴:庫藏股/併購/私募/增資/發可轉債/減資/財測/下市(結構性事件,CB 玩家必須第一時間知道)
  重訊 🟡:處分或取得資產/資金貸與/背書保證/高層異動/訴訟
  月營收:新公告即報,YoY ±20% 標 🔴,其餘 🟡;同時給 MoM 與累計 YoY 對照
"""
import os
import re
import json
import datetime
import urllib.request

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
# 「新合作/新供應關係」類(供應鏈事件守望 supply_chain_watch 用;也算 yellow 級進 patrol/日報插卡)
PARTNER_KW = ["策略聯盟", "合作備忘錄", "合作協議", "合作意向", "合作契約", "業務合作",
              "技術合作", "產業合作", "共同開發", "合資", "結盟", "聯盟", "MOU",
              "供貨合約", "供應合約", "採購合約", "銷售合約", "長期供應", "訂單"]

# 對手方公司名最佳努力擷取:「…與○○(股份有限)公司簽訂/簽署/締結…」;擷取不到=None 誠實留空。
# 「及」進排除字元+錨點:多方合約(與A公司及B公司…)只抓第一方,不會抓出「A公司及B」這種殘串
_PARTNER_CP_RE = re.compile(
    r"與([^,、;;::()()「」『』及]{2,30}?)(?:股份有限公司|有限公司|公司|集團)?"
    r"(?:簽訂|簽署|締結|成立|合作|共同|進行|展開|攜手|及|策略聯盟|合資|結盟)")

# 「合併」出現在會計合併報表用語(合併營收/合併營業收入/合併月營收/合併自結損益/合併財報…)
# 不是併購——別誤報 red
_MERGER_FP_RE = re.compile(r"合併(自結)?月?(營業)?(收入|營收|損益|財務|財報|報表|報告)")

# 負向詞:終止/解除合作是重大事件(patrol yellow 仍收),但絕不是「新合作」——推播管道必須排除
_PARTNER_NEG_RE = re.compile(r"終止|解除|取消|停止|解約|中止")


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
            if kw == "合併" and "合併" not in _MERGER_FP_RE.sub("", subject):
                continue
            return "red", kw
    if "澄清" not in subject and "更正" not in subject:
        kw = _partner_kw(subject)
        if kw:
            return "yellow", kw
    for kw in YELLOW_KW:
        if kw in subject:
            return "yellow", kw
    return "plain", ""


def _partner_kw(subject):
    for kw in PARTNER_KW:
        if kw in subject:
            return kw
    return ""


def extract_counterparty(subject):
    m = _PARTNER_CP_RE.search(subject)
    return m.group(1).strip() if m else None


def _iter_news_rows(days):
    """撈全市場(上市+上櫃)近 N 日重大訊息原始列,yield (code, name, date, subject)。"""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for url in ENDPOINTS_NEWS:
        try:
            rows = _get(url)
        except Exception:
            continue
        for x in rows:
            code = str(x.get("公司代號") or x.get("SecuritiesCompanyCode") or "").strip()
            d = _roc_to_date(x.get("發言日期") or x.get("Date"))
            if not d or d < cutoff:
                continue
            subject = " ".join((x.get("主旨 ") or x.get("主旨") or "").split())
            name = (x.get("公司名稱") or x.get("CompanyName") or "").strip()
            yield code, name, d, subject


def major_news(codes, days=3):
    """近 N 日 watchlist 公司的重大訊息,附分級。回 list[dict] 新到舊。"""
    codes = {str(c) for c in codes}
    out = []
    for code, name, d, subject in _iter_news_rows(days):
        if code not in codes:
            continue
        level, kw = _news_level(subject)
        out.append({
            "code": code, "name": name,
            "date": d.isoformat(), "subject": subject, "level": level, "keyword": kw,
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def partnership_news(days=2, codes=None):
    """全市場「新合作/新供應關係」類重大訊息(策略聯盟/備忘錄/合資/供貨合約/訂單等)。
    codes=None 掃全市場(供應鏈事件守望用);傳集合則只留該集合。回 list[dict] 新到舊。"""
    codes = {str(c) for c in codes} if codes else None
    out = []
    for code, name, d, subject in _iter_news_rows(days):
        if codes is not None and code not in codes:
            continue
        if "澄清" in subject or "更正" in subject or _PARTNER_NEG_RE.search(subject):
            continue
        kw = _partner_kw(subject)
        if not kw:
            continue
        # 「訂單」單獨出現太廣(展望說明/狀況報告都有):必須是「取得/接獲/簽訂/新增…訂單」才算新供應關係
        if kw == "訂單" and not re.search(r"(取得|接獲|簽訂|新增)[^,、;;]{0,10}訂單", subject):
            continue
        out.append({
            "code": code, "name": name, "date": d.isoformat(), "subject": subject,
            "keyword": kw, "counterparty": extract_counterparty(subject),
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
