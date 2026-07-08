"""CB 次級市場成交價(可插拔多來源)。依序嘗試,全失敗回 None(分析端透明退回承銷價):
  0) TWSE MIS 即時報價(cb_quote)—— 免費免 token,盤中即時、收盤後=當日收盤,首選
  1) FinMind CB dataset —— 需 FINMIND_TOKEN(deep=True 才試)
  2) TPEx 債券電腦議價揭示板 —— 當日有報價時可得(deep=True 才試)
拿到價就用『市場隱波』取代承銷價隱波(更即時)。"""
import os
import json
import datetime
import urllib.request

import cb_quote

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
                try:
                    v = float(px)
                except (TypeError, ValueError):
                    v = None
                # 與 _from_mis/_ppval 同一百元價範圍防呆:dataset 欄位改名/回傳殖利率或比率等非百元價
                # 時,不可當真實 CB 市價吃進來(否則下游偏離掃描對非市價報「市場狀態」=假訊號)
                if v is not None and 50 <= v <= 300:
                    return {"price": v, "date": last.get("date"), "src": f"FinMind/{ds}"}
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


def _from_mis(bond_code, today):
    try:
        q = cb_quote.get_quote(bond_code)
    except Exception:
        return None
    if q and q.get("price") and 50 <= q["price"] <= 300:
        src = "MIS即時" + (f" {q['time']}" if q.get("time") else "")
        return {"price": q["price"], "date": q.get("date"), "src": src, "quote": q}
    return None


def get_cb_price(bond_code, today=None, deep=False):
    """回 {price, date, src} 或 None。預設只打 MIS 即時(快);deep=True 加試 FinMind/TPEx議價板。"""
    today = today or datetime.date.today()
    fns = (_from_mis, _from_finmind, _from_tpex) if deep else (_from_mis,)
    for fn in fns:
        r = fn(bond_code, today)
        if r:
            return r
    return None
