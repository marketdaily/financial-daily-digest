"""CB 次級市場成交價(可插拔多來源)。
台股個別 CB 收盤價沒有穩定免費源,所以依序嘗試,全失敗就回 None(分析端透明退回承銷價):
  1) FinMind CB dataset —— 需 FINMIND_TOKEN(免費註冊 finmindtrade.com 即可解鎖)
  2) TPEx 債券電腦議價揭示板 —— 當日有報價時可得(多數 CB 無)
拿到價就用『市場隱波』取代承銷價隱波(更即時)。"""
import os, json, datetime, urllib.request

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
           "Referer": "https://www.tpex.org.tw/"}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _from_finmind(bond_code, today):
    if not TOKEN:
        return None
    start = (today - datetime.timedelta(days=20)).isoformat()
    for ds in ("TaiwanStockConvertibleBondDaily", "TaiwanStockConvertibleBondPrice"):
        try:
            url = f"{FINMIND}?dataset={ds}&data_id={bond_code}&start_date={start}&token={TOKEN}"
            j = json.loads(_get(url))
            data = j.get("data", [])
            if data:
                last = data[-1]
                px = last.get("close") or last.get("Close") or last.get("price")
                if px:
                    return {"price": float(px), "date": last.get("date"), "src": f"FinMind/{ds}"}
        except Exception:
            continue
    return None


def _tpex_dates(today, back=6):
    for i in range(back):
        d = today - datetime.timedelta(days=i)
        if d.weekday() < 5:
            yield d


def _from_tpex(bond_code, today):
    for d in _tpex_dates(today):
        try:
            url = f"https://www.tpex.org.tw/www/zh-tw/bond/cbQuotes?date={d.strftime('%Y/%m/%d')}"
            j = json.loads(_get(url))
            for t in j.get("tables", []):
                for row in t.get("data", []):
                    if row and str(row[0]).strip() == str(bond_code):
                        # 欄位:代號,名稱,買進殖利率/百元價,賣出殖利率/百元價
                        bid, ask = _ppval(row[2]), _ppval(row[3])
                        mid = next((x for x in [_avg(bid, ask), bid, ask] if x), None)
                        if mid:
                            return {"price": mid, "date": d.isoformat(), "src": "TPEx議價板"}
        except Exception:
            continue
    return None


def _ppval(cell):
    """'1.85/103.20' 取百元價 103.20;純數字直接回。"""
    if cell is None:
        return None
    s = str(cell).replace(",", "")
    if "/" in s:
        s = s.split("/")[-1]
    try:
        v = float(s)
        return v if 50 <= v <= 300 else None
    except ValueError:
        return None


def _avg(a, b):
    return (a + b) / 2 if a and b else None


def get_cb_price(bond_code, today=None):
    """回 {price, date, src} 或 None。"""
    today = today or datetime.date.today()
    for fn in (_from_finmind, _from_tpex):
        r = fn(bond_code, today)
        if r:
            return r
    return None
