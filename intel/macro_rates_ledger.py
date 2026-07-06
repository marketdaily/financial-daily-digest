"""Fed 政策利率 + 美元/新台幣匯率歷史帳本(backlog.md P2.6「深研究夜課路線2·總經溫度計儀表板」
後續待辦之二:regime_ledger.py 已把 VIX/SPX/NDX/TWII 接成歷史帳本,這裡補兩個正交的總經數據源
——同樣是「只在需要當下算一次就丟,從未存下來」的缺口)。

跟 regime_ledger.py 分開成獨立檔案(而非塞進同一份):regime_ledger 專注 `_market_regime()`
risk_on/neutral/risk_off 標籤本身的輸入,這裡的兩個數字不參與那個標籤計算,是正交的總經溫度計
讀數,同 intel/ 既有慣例(tw_margin.py/tw_sbl.py 等同類但不同訊號的連接器各自獨立成檔)。

資料源(皆免 key/免申請,real_estate_radar 已驗證過的 FRED fredgraph.csv 端點手法):
- Fed 政策利率:DFEDTARU/DFEDTARL(Federal Funds Target Range Upper/Lower Limit),FOMC 決議
  當天才變動的階梯函數,平常每天回傳同一個值。
- USD/TWD:DEXTAUS(標題已核實為 "Taiwan Dollars to U.S. Dollar Spot Exchange Rate",不是泰銖)。

`fred.stlouisfed.org` 的 WAF 會把裸 `-A "Mozilla/5.0"` 當機器人特徵 tarpit 連線,故用 curl 預設
UA(不手動指定),見 state/lessons/fred_stlouisfed_blocked.md。

刻意不做的事(留給之後真正要建前端頁面時再評估):
- 「距下次 FOMC 會議倒數」:需要維護一份逐年更新的會議日期靜態表(或即時爬 federalreserve.gov
  官方 calendar 頁),年年要維護,本輪不做;FRED 序列本身是階梯函數,要看「上次變動距今幾天/
  漲跌方向」可以之後直接對累積的本帳本或 FRED 全歷史序列做 diff,不需要另外猜日期。
- 大盤本益比河流圖:查無現成免費連接器,留待後續研究。

CLI: python3 -m intel.macro_rates_ledger
"""
import os
import sys
import json
import math
import fcntl
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "macro_rates_ledger.jsonl")

FED_UPPER_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
FED_LOWER_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL"
USDTWD_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXTAUS"


def _get_text(url, timeout=15):
    """curl 子行程抓取,不手動指定 UA(見上方模組說明的 WAF 坑)。"""
    last_err = None
    for attempt in range(2):
        proc = subprocess.run(
            ["curl", "-sL", "--http1.1", "--max-time", str(timeout), url],
            capture_output=True, timeout=timeout + 5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8-sig")
        last_err = f"curl exit={proc.returncode} stderr={proc.stderr.decode(errors='replace')[:200]}"
    raise RuntimeError(f"fetch failed after retry: {last_err}")


def _latest_value(csv_text):
    """FRED fredgraph.csv 格式:`observation_date,<series_id>` 標頭 + 逐日資料列,缺值那天該欄
    是字面字串 `.`(FRED 官方缺值標記,非空字串)。由後往前找第一個能轉成 float 的值,回
    (date_str, value);全部都是缺值或格式異常回 None。"""
    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    for line in reversed(lines[1:]):
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date_str, raw = parts
        if raw == ".":
            continue
        try:
            return date_str, float(raw)
        except ValueError:
            continue
    return None


def fetch_macro_inputs() -> dict:
    """任一段抓價失敗就該段回 None,不拋錯——完整性由 `_is_usable()` 把關。"""
    result = {"fed_upper": None, "fed_lower": None, "usdtwd": None}
    try:
        parsed = _latest_value(_get_text(FED_UPPER_URL))
        if parsed:
            result["fed_upper"] = parsed[1]
    except Exception:
        pass
    try:
        parsed = _latest_value(_get_text(FED_LOWER_URL))
        if parsed:
            result["fed_lower"] = parsed[1]
    except Exception:
        pass
    try:
        parsed = _latest_value(_get_text(USDTWD_URL))
        if parsed:
            result["usdtwd"] = parsed[1]
    except Exception:
        pass
    return result


def _is_usable(data: dict) -> bool:
    """三個數字皆非 None 且為正數才算完整——寧可整天不記,不要記一筆有欄位是 None/0 的偽造列
    (同 regime_ledger.py 的教訓:局部抓價失敗不能靜默退化成看起來合法的資料)。"""
    fed_upper = data.get("fed_upper")
    fed_lower = data.get("fed_lower")
    usdtwd = data.get("usdtwd")
    if fed_upper is None or fed_lower is None or usdtwd is None:
        return False
    if not all(math.isfinite(v) for v in (fed_upper, fed_lower, usdtwd)):
        return False  # float() accepts literal "inf"/"Infinity"; a real value is never non-finite
    if not (fed_upper > 0 and fed_lower > 0 and usdtwd > 0):
        return False
    return fed_upper >= fed_lower


def _load_seen_dates():
    seen = set()
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line).get("date")
                    if d:
                        seen.add(d)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seen


def record(date_str: str, data: dict) -> bool:
    """回 True=真的新寫入一筆,False=當天已記過(跳過)。絕不拋錯。check-then-append 用
    `fcntl.flock` 包成臨界區,防手動重跑跟 cron 同時觸發產生同一天重複列(同 regime_ledger.py
    已用並發實測重現過的 TOCTOU race)。"""
    try:
        os.makedirs(os.path.dirname(LEDGER) or ".", exist_ok=True)
        lock_path = LEDGER + ".lock"
        with open(lock_path, "a") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                if date_str in _load_seen_dates():
                    return False
                row = {
                    "date": date_str,
                    "fed_upper": data.get("fed_upper"),
                    "fed_lower": data.get("fed_lower"),
                    "usdtwd": data.get("usdtwd"),
                }
                with open(LEDGER, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                return True
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
    except Exception:
        return False


def run() -> dict:
    date_str = datetime.date.today().isoformat()
    if date_str in _load_seen_dates():
        return {"date": date_str, "status": "already_logged"}
    data = fetch_macro_inputs()
    if not _is_usable(data):
        return {"date": date_str, "status": "fetch_failed", **data}
    written = record(date_str, data)
    return {"date": date_str, "status": "written" if written else "skipped", **data}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
