"""TWSE 集中市場監理公告連接器(信息差引擎 #9,curriculum I 節「法規監控」):
注意股 + 處置股 + 注意累計次數異常,免費 JSON、免金鑰。
跟 mops_watch.py(公司自己揭露的重訊)不同維度——這裡是交易所對「交易行為本身」開罰的監理措施,
命中=流動性/價格機制已被官方介入,是比公司自揭重訊更硬的風險訊號。
訊號定義:
  處置 🔴:目前落在處置期間內(人工管制撮合/預收全額價金),流動性驟降,持有者需高度警覺
  注意累計異常 🟡:短期內連續多次觸及注意標準,逼近下一步處置門檻(領先指標,punish 的前兆)
  當日注意股 🟡:當天剛觸及注意股標準(官方僅在有標的觸及時才有非空列,平時多為空)
四碼碼過濾:TWSE 這三個端點的 Code 欄位混雜權證(6碼,如 "059570")與正股(4碼),
只留 4 碼可排除絕大多數權證雜訊,對齊既有 watchlist(CB underlying 正股)慣例。
"""
import json
import datetime
import urllib.request

ENDPOINT_NOTICE = "https://openapi.twse.com.tw/v1/announcement/notice"
ENDPOINT_PUNISH = "https://openapi.twse.com.tw/v1/announcement/punish"
ENDPOINT_NOTETRANS = "https://openapi.twse.com.tw/v1/announcement/notetrans"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def _roc_range_active(period_str, today=None):
    """'115/07/03～115/07/16' -> True if today 落在 [start,end] 內。壞格式回 False。"""
    today = today or datetime.date.today()
    try:
        start_s, end_s = period_str.split("～")

        def parse(s):
            y, m, d = s.strip().split("/")
            return datetime.date(int(y) + 1911, int(m), int(d))

        return parse(start_s) <= today <= parse(end_s)
    except Exception:
        return False


def disposition_stocks(codes):
    """目前處於處置期間內的 watchlist 正股(4碼,排除權證)。回 list[dict],紅燈。"""
    codes = {str(c) for c in codes}
    out = []
    try:
        rows = _get(ENDPOINT_PUNISH)
    except Exception:
        return out
    for x in rows:
        code = str(x.get("Code") or "").strip()
        if len(code) != 4 or code not in codes:
            continue
        period = x.get("DispositionPeriod") or ""
        if not _roc_range_active(period):
            continue
        reason = x.get("ReasonsOfDisposition") or ""
        measure = x.get("DispositionMeasures") or ""
        out.append({
            "code": code, "name": (x.get("Name") or "").strip(),
            "level": "red", "reason": reason, "period": period, "measure": measure,
            "signal": f"處置中({measure}):{reason},期間 {period}",
        })
    return out


def notice_escalation(codes):
    """近期連續觸及注意標準、逼近處置門檻的 watchlist 正股。回 list[dict],黃燈(領先指標)。"""
    codes = {str(c) for c in codes}
    out = []
    try:
        rows = _get(ENDPOINT_NOTETRANS)
    except Exception:
        return out
    for x in rows:
        code = str(x.get("Code") or "").strip()
        if len(code) != 4 or code not in codes:
            continue
        criteria = x.get("RecentlyMetAttentionSecuritiesCriteria") or ""
        out.append({
            "code": code, "name": (x.get("Name") or "").strip(),
            "level": "yellow", "criteria": criteria,
            "signal": f"注意累計異常:{criteria}(逼近處置門檻)",
        })
    return out


def daily_attention(codes):
    """當日公布注意股票(即時,官方無標的觸及時回傳的是空白佔位列,非交易日常態)。回 list[dict],黃燈。"""
    codes = {str(c) for c in codes}
    out = []
    try:
        rows = _get(ENDPOINT_NOTICE)
    except Exception:
        return out
    for x in rows:
        code = str(x.get("Code") or "").strip()
        if len(code) != 4 or code not in codes:
            continue
        out.append({
            "code": code, "name": (x.get("Name") or "").strip(),
            "level": "yellow",
            "signal": f"當日觸及注意股標準(收盤{x.get('ClosingPrice','')}、本益比{x.get('PE','')})",
        })
    return out


def scan(codes):
    """三端點合併掃描,回 {code: {level, signal, source}} 取每檔最嚴重一則(punish > notetrans > notice)。"""
    codes = list(codes)
    out = {}
    for item in daily_attention(codes):
        out[item["code"]] = {"level": item["level"], "signal": item["signal"], "source": "twse_notice"}
    for item in notice_escalation(codes):
        out[item["code"]] = {"level": item["level"], "signal": item["signal"], "source": "twse_notetrans"}
    for item in disposition_stocks(codes):
        out[item["code"]] = {"level": item["level"], "signal": item["signal"], "source": "twse_punish"}
    return out


if __name__ == "__main__":
    import sys
    test_codes = sys.argv[1:] or ["1515", "2330", "4541", "3605"]
    result = scan(test_codes)
    print(json.dumps(result, ensure_ascii=False, indent=1))
