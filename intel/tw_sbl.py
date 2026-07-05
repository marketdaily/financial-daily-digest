"""台股借券賣出(SBL)連接器(信息差引擎積木 #5)。
tw_margin.py 抓的是散戶融資融券;這裡抓機構透過證券商「借券賣出」放空的餘額——
不同主體、不同資料集,是比散戶更聰明的籌碼面情緒指標(法人/避險基金卡位,散戶不會逐日盯這個數字)。
資料源 FinMind(TaiwanDailyShortSaleBalances,免 token 可用);當日快取。

⚠️坑(2026-07-03 探測記錄,省後人重踩):SBLShortSalesQuota「當日限額」不是固定天花板,
會逐日大幅波動(同檔股票隔日限額可差 10%+),且 balance/quota 使用率在不同股票間落差極大
(TSMC ~86-89% vs 群聯 ~380-420% vs 大聯大3596 ~590-630%,都是常態非異常)——
這欄位**不能**當「近滿水位=籌碼緊俏」的訊號閾值用(不像 tw_margin 的融資使用率那樣可靠)。
真正有訊號意義的是**餘額 5 日變動率**(絕對水位變化,不受限額雜訊干擾)。

訊號定義(v1 啟發式門檻,同 tw_margin 方法論——先建可行動訊號,精確門檻後續用 edge_audit 回測校準):
  🔴 SBL 餘額 5 日遽增 ≥20%(機構加碼借券放空,對照股價:同期下跌=空頭訊號確認,逆勢上漲=提前卡位/留意後續壓力)
  🟡 SBL 餘額 5 日遽減 ≥20%(機構回補潮,空頭力道減弱,留意止跌)
  🟡 SBL 餘額 5 日增 ≥10%(溫和加碼放空)
  ⚪ 中性(只記錄不打擾)
"""
import os
import json
import datetime
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".sbl_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _fetch(dataset, code, start):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data", [])


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def pct_change(new, old):
    if not old or new is None:
        return 0.0
    return (new - old) / old * 100.0


def classify(sbl_bal, sbl_5d_ago, price_now=None, price_5d_ago=None):
    """回 {level, signal}。純數字判斷,不叫網路。"""
    sbl_chg = pct_change(sbl_bal, sbl_5d_ago) if sbl_5d_ago and sbl_bal is not None else 0.0
    price_chg = pct_change(price_now, price_5d_ago) if price_5d_ago and price_now is not None else None

    if sbl_chg >= 20:
        if price_chg is not None and price_chg <= -3:
            note = "股價同期續跌,空頭訊號確認"
        elif price_chg is not None and price_chg >= 0:
            note = "股價逆勢上漲,留意提前卡位/後續壓力"
        else:
            note = "股價走勢待確認"
        return {"level": "red", "signal": f"機構借券賣出5日遽增{sbl_chg:.1f}%(聰明錢加碼放空,{note})",
                "sbl_chg_5d": round(sbl_chg, 1)}
    if sbl_chg <= -20:
        return {"level": "yellow", "signal": f"機構借券賣出5日遽減{sbl_chg:.1f}%(回補潮,空頭力道減弱)",
                "sbl_chg_5d": round(sbl_chg, 1)}
    if sbl_chg >= 10:
        return {"level": "yellow", "signal": f"機構借券賣出5日增{sbl_chg:.1f}%(溫和加碼放空)",
                "sbl_chg_5d": round(sbl_chg, 1)}
    return {"level": "plain", "signal": "借券賣出中性", "sbl_chg_5d": round(sbl_chg, 1)}


def sbl(code, today=None):
    """回 dict:借券賣出餘額/5日變動+訊號分級。抓不到回 None。"""
    today = today or datetime.date.today()
    cache = _load_cache()
    ck = f"{code}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]
    start = (today - datetime.timedelta(days=20)).isoformat()
    try:
        rows = _fetch("TaiwanDailyShortSaleBalances", code, start)
        prices = _fetch("TaiwanStockPrice", code, start)
    except Exception:
        return None
    if not rows:
        return None
    rows.sort(key=lambda x: x["date"])
    prices.sort(key=lambda x: x["date"])
    price_by_date = {p["date"]: p.get("close") for p in prices if p.get("close")}

    last = rows[-1]
    sbl_bal = last.get("SBLShortSalesCurrentDayBalance", 0)

    idx_5d = -6 if len(rows) >= 6 else 0
    sbl_5d_ago = rows[idx_5d].get("SBLShortSalesCurrentDayBalance", 0)
    date_5d_ago = rows[idx_5d].get("date")

    price_now = price_by_date.get(last["date"])
    price_5d_ago = price_by_date.get(date_5d_ago)

    out = {
        "date": last["date"],
        "sbl_balance": sbl_bal,
        "sbl_quota": last.get("SBLShortSalesQuota", 0),
    }
    out.update(classify(sbl_bal, sbl_5d_ago, price_now, price_5d_ago))

    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    _save_cache(cache)
    return out


def scan(codes, pause=0.4):
    """批次掃描,回 {code: sbl_dict}。禮貌節流。"""
    out = {}
    for c in codes:
        r = sbl(c)
        if r:
            out[c] = r
        time.sleep(pause)
    return out


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(json.dumps(sbl(code), ensure_ascii=False, indent=1))
