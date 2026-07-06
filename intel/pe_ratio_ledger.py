"""S&P 500 本益比歷史帳本(backlog.md P2.6「深研究夜課路線2·總經溫度計儀表板」第三步——
「大盤本益比河流圖」缺口)。

TW 側先研究過:TWSE openapi(exchangeReport/BWIBBU_ALL、BWIBBU_d)只提供「個股」本益比,
沒有官方發布的大盤加權本益比序列。要自算加權平均本益比需要:①每檔市值(還要另外抓股數)
②處理負獲利股票(本益比顯示為空字串,排除規則無官方依據)③各股「財報年/季」基準不同期
(BWIBBU_d 回應裡每檔的 EPS 來自不同季度,同一天用不同基準的本益比直接加權平均在方法論上
不嚴謹)。硬做出來的數字很可能跟外部常見「台股大盤本益比」對不上——寧可不做,不要生產一個
看起來像真的但方法論站不住腳、跟其他來源對不上的「大盤本益比」誤導 Delvin。此為誠實的
研究負結果,非放棄——若之後找到 TWSE 官方發布的加權大盤本益比序列(非個股)再補。

US 側:multpl.com `/s-p-500-pe-ratio` 首頁有乾淨的「Current S&P 500 PE Ratio」即時數字
(免 key、無 CF 擋、robots.txt 只列 sitemap 沒有 Disallow),用一般瀏覽器 UA 即可讀到,
故先做這半個——S&P 500 估值溫度計仍是總經儀表板的正交輸入之一(全球風險情緒指標)。

跟 regime_ledger.py / macro_rates_ledger.py 分開成獨立檔案,同 intel/ 既有慣例(one-file-
per-signal-type)。同樣的三件套(dedup by date + fcntl.flock 防 TOCTOU race + `_is_usable()`
完整性守門)。

CLI: python3 -m intel.pe_ratio_ledger
"""
import os
import sys
import json
import math
import fcntl
import re
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "pe_ratio_ledger.jsonl")

SP500_PE_URL = "https://www.multpl.com/s-p-500-pe-ratio"

_CURRENT_RE = re.compile(r'<div id="current">.*?</b>\s*([\d.]+)', re.S)


def _get_html(url, timeout=15):
    """curl 子行程抓取,一般瀏覽器 UA(multpl.com 未見 WAF 擋無 UA/裸 UA 請求,跟 FRED
    不同,見 macro_rates_ledger.py 模組說明的 WAF 坑——這裡不套用那個特例)。"""
    last_err = None
    for attempt in range(2):
        proc = subprocess.run(
            ["curl", "-sL", "--http1.1", "-A", "Mozilla/5.0", "--max-time", str(timeout), url],
            capture_output=True, timeout=timeout + 5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
        last_err = f"curl exit={proc.returncode} stderr={proc.stderr.decode(errors='replace')[:200]}"
    raise RuntimeError(f"fetch failed after retry: {last_err}")


def _parse_current_pe(html):
    """從 `<div id="current">...</b>32.44` 區塊擷取當前 S&P 500 本益比。格式改版/擷取
    失敗回 None,不拋錯——完整性由 `_is_usable()` 把關。"""
    m = _CURRENT_RE.search(html)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def fetch_pe_inputs() -> dict:
    result = {"sp500_pe": None}
    try:
        result["sp500_pe"] = _parse_current_pe(_get_html(SP500_PE_URL))
    except Exception:
        pass
    return result


def _is_usable(data: dict) -> bool:
    """本益比非 None、有限值、且落在寬鬆合理區間才算完整——同 macro_rates_ledger.py 教訓,
    寧可整天不記,不要記一筆抓到 None/inf/頁面改版誤擷取的偽造列。歷史上 S&P 500 trailing
    本益比 2009 年獲利崩潰時衝到 ~123,區間上限故意抓寬(500)避免未來極端行情誤判成抓價
    失敗,但仍要擋掉 0/負值/非有限值這類明顯的擷取失敗。"""
    pe = data.get("sp500_pe")
    if pe is None:
        return False
    if not math.isfinite(pe):
        return False
    return 0 < pe < 500


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
    `fcntl.flock` 包成臨界區,防手動重跑跟 cron 同時觸發產生同一天重複列(同
    regime_ledger.py/macro_rates_ledger.py 已用並發實測重現過的 TOCTOU race)。"""
    try:
        os.makedirs(os.path.dirname(LEDGER) or ".", exist_ok=True)
        lock_path = LEDGER + ".lock"
        with open(lock_path, "a") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                if date_str in _load_seen_dates():
                    return False
                row = {"date": date_str, "sp500_pe": data.get("sp500_pe")}
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
    data = fetch_pe_inputs()
    if not _is_usable(data):
        return {"date": date_str, "status": "fetch_failed", **data}
    written = record(date_str, data)
    return {"date": date_str, "status": "written" if written else "skipped", **data}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
