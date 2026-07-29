"""gold_macro 連接器——黃金現貨宏觀訊號(risk-off 雷達,市場級非個股)。

資料源:goldprice.dev 匿名層(https://api.goldprice.dev/v1/prices,免 key,
免費層 30 req/min / 1000 req/月,XAU spot;本連接器每日只打 1 次綽綽有餘)。
2026-07-30 GitHub 星海挖礦(public-apis)發現。多源交叉驗證的金價聚合器。

為什麼是信息差:黃金單日大動=避險資金劇烈換手,常領先或伴隨股市 risk regime 轉換;
macro_rates(Fed/匯率)之外的獨立避險溫度計。ledger 記日價才算得出變動(同 macro_rates 模式)。

訊號定義(classify 純函式):
  🔴 單日 |漲跌| ≥ 3%(黃金年化波動僅 ~15%,3% 日變動=重大避險事件級)
  🟡 單日 |漲跌| ≥ 1.5%,或創 30 日新高/新低(趨勢突破,留意 regime)
  ⚪ 其他(只記錄不打擾)

用法:
  每日記帳+訊號: python3 -m intel.gold_macro          (patrol 夜巡呼叫 market_signal())
  只看不寫:      python3 -m intel.gold_macro --dry
"""
import os
import json
import fcntl
import datetime
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "gold_macro_ledger.jsonl")

PRICES_URL = "https://api.goldprice.dev/v1/prices"
RED_PCT = 3.0
YELLOW_PCT = 1.5
BREAKOUT_DAYS = 30


def _fetch_curl(url, timeout=20):
    r = subprocess.run(["curl", "-s", "--max-time", str(timeout), url],
                        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"curl failed rc={r.returncode} url={url}")
    return r.stdout


def _fetch_urllib(url, timeout=20):
    """UA 用完整版本字串——裸 "Mozilla/5.0" 會被部分 WAF(如 FRED)當機器人特徵擋下。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def fetch_xau_usd():
    """回 float(XAU-USD 現貨)或 None。回應是全幣別列表,取 quote_currency=USD 且非 stale 那列。"""
    try:
        raw = json.loads(_fetch_urllib(PRICES_URL))
        for row in raw.get("symbols", []):
            if (row.get("symbol") in ("XAU", "XAU-USD-SPOT")
                    and row.get("quote_currency") == "USD"
                    and row.get("contract_type") == "spot"
                    and not row.get("is_stale")):
                return float(row["price"])
    except Exception:
        pass
    return None


def _load_rows():
    rows = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("date") and r.get("xau_usd") is not None:
                        rows.append(r)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return sorted(rows, key=lambda r: r["date"])


def record(date_str, price):
    """回 True=新寫入,False=當天已記過/失敗。check-then-append 用 flock 包臨界區
    (同 macro_rates_ledger.py,防手動重跑撞 cron 的 TOCTOU race)。絕不拋錯。"""
    try:
        lock_path = LEDGER + ".lock"
        with open(lock_path, "a") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                if any(r["date"] == date_str for r in _load_rows()):
                    return False
                with open(LEDGER, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"date": date_str, "xau_usd": price}) + "\n")
                return True
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
    except Exception:
        return False


def classify(price_now, price_prior, hi_30d=None, lo_30d=None):
    """純函式。price_prior 為 None(首日)只記錄。hi/lo 是【不含今天】的近30日極值。"""
    if price_now is None:
        return {"level": "unknown", "signal": "金價抓取失敗"}
    if not price_prior:
        return {"level": "plain", "signal": f"金價 ${price_now:,.0f}(首日記帳,無比較基準)"}
    chg = (price_now - price_prior) / price_prior * 100
    arrow = "漲" if chg >= 0 else "跌"
    base = f"金價 ${price_now:,.0f},單日{arrow} {abs(chg):.1f}%"
    if abs(chg) >= RED_PCT:
        return {"level": "red", "signal": f"{base}——重大避險事件級變動,留意 risk regime 轉換"}
    if abs(chg) >= YELLOW_PCT:
        return {"level": "yellow", "signal": f"{base}——避險溫度計異常升溫"}
    if hi_30d and price_now > hi_30d:
        return {"level": "yellow", "signal": f"{base},創 {BREAKOUT_DAYS} 日新高(${hi_30d:,.0f})——避險需求趨勢升"}
    if lo_30d and price_now < lo_30d:
        return {"level": "yellow", "signal": f"{base},創 {BREAKOUT_DAYS} 日新低(${lo_30d:,.0f})——避險需求退潮"}
    return {"level": "plain", "signal": base}


def market_signal(today=None, write=True):
    """抓今日金價→記 ledger→回市場級訊號 dict(patrol 夜巡入口)。失敗回 None,絕不拋錯。"""
    try:
        today = today or datetime.date.today()
        date_str = today.isoformat()
        price = fetch_xau_usd()
        if price is None:
            rows = _load_rows()
            if rows and rows[-1]["date"] == date_str:
                price = rows[-1]["xau_usd"]  # 今天稍早已記過,API 暫時掛掉仍可出訊號
            else:
                return None
        if write:
            record(date_str, price)
        prior_rows = [r for r in _load_rows() if r["date"] < date_str]
        prior = prior_rows[-1]["xau_usd"] if prior_rows else None
        cut = (today - datetime.timedelta(days=BREAKOUT_DAYS)).isoformat()
        window = [r["xau_usd"] for r in prior_rows if r["date"] >= cut]
        out = {"date": date_str, "xau_usd": price}
        out.update(classify(price, prior,
                            hi_30d=max(window) if window else None,
                            lo_30d=min(window) if window else None))
        return out
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    print(json.dumps(market_signal(write=not dry), ensure_ascii=False, indent=1))
