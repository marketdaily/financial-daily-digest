"""估值帳本:DCF 合理價區間輸出從未被記下來過,等於永遠無法回測(backlog P1.5 誠實旗發現的
最大盲點——CB/股票都有帳本+校準,唯獨估值是黑箱)。每天替固定觀察清單記一筆
{date, symbol, dcf_low, dcf_high, price_now},1-3 個月後 score_ledger.py 可回頭驗證
「當時的合理價區間,有沒有真的框住之後的股價」。
紀律(仿 cb_analyzer/cb_ledger.py):每檔每天只記一筆;任何單檔失敗只跳過,絕不拋錯拖垮呼叫端;
只記錄 compute_dcf 有算出結果的檔(FCF 不穩定/資料不足本來就回 None,不強記空值)。
CLI: python3 valuation/ledger.py [symbols...]  (預設 config.US_STOCKS + config.TW_STOCKS)
"""
import os, sys, json, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

LEDGER = os.path.join(HERE, "valuation_ledger.jsonl")
FMP = "https://financialmodelingprep.com/stable"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
FMP_KEY = os.environ.get("FMP_API_KEY", "").strip()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()

try:
    from valuation.dcf import compute_dcf
except Exception:
    compute_dcf = None

_seen = None


def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _load_seen():
    global _seen
    if _seen is None:
        _seen = set()
        try:
            with open(LEDGER, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        _seen.add((r.get("symbol"), r.get("date")))
                    except Exception:
                        pass
        except FileNotFoundError:
            pass
    return _seen


def tw_price(stock_id):
    """FinMind 最近收盤價(同 valuation/dcf.py 的資料源,不引入新依賴)。"""
    try:
        end = datetime.date.today().isoformat()
        start = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        url = f"{FINMIND}?dataset=TaiwanStockPrice&data_id={stock_id}&start_date={start}&end_date={end}"
        if FINMIND_TOKEN:
            url += f"&token={FINMIND_TOKEN}"
        rows = _http_json(url).get("data", [])
        if not rows:
            return None
        latest = sorted(rows, key=lambda r: r.get("date", ""))[-1]
        return float(latest["close"])
    except Exception:
        return None


def us_price(symbol):
    """FMP quote(同 valuation/dcf.py 的美股資料源)。無 key 回 None,不硬猜。"""
    if not FMP_KEY:
        return None
    try:
        rows = _http_json(f"{FMP}/quote?symbol={symbol}&apikey={FMP_KEY}")
        if isinstance(rows, list) and rows:
            p = rows[0].get("price")
            return float(p) if p is not None else None
    except Exception:
        return None
    return None


def price_now(symbol):
    return tw_price(symbol) if str(symbol).isdigit() else us_price(symbol)


def record(symbol, date_str, dcf, price):
    """回 True=真的新寫入一筆,False=跳過(重複/無 dcf)。絕不拋錯。"""
    try:
        if not dcf or dcf.get("dcf_low") is None or dcf.get("dcf_high") is None:
            return False
        seen = _load_seen()
        key = (symbol, date_str)
        if key in seen:
            return False
        row = {
            "date": date_str, "symbol": symbol,
            "dcf_low": round(float(dcf["dcf_low"]), 2),
            "dcf_high": round(float(dcf["dcf_high"]), 2),
            "price_now": round(float(price), 2) if price is not None else None,
        }
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        seen.add(key)
        return True
    except Exception:
        return False


def default_watchlist():
    import config
    return list(config.US_STOCKS) + [s["symbol"] for s in config.TW_STOCKS]


def run(symbols=None):
    symbols = symbols or default_watchlist()
    today = datetime.date.today()
    date_str = today.isoformat()
    written, no_dcf, already_logged = [], [], []
    for sym in symbols:
        if (sym, date_str) in _load_seen():
            already_logged.append(sym)
            continue
        try:
            dcf = compute_dcf(sym, today)
        except Exception:
            dcf = None
        if not dcf:
            no_dcf.append(sym)
            continue
        price = price_now(sym)
        if record(sym, date_str, dcf, price):
            written.append(sym)
    return {"date": date_str, "written": written, "no_dcf": no_dcf, "already_logged": already_logged}


if __name__ == "__main__":
    result = run(sys.argv[1:] or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
