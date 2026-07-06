"""大盤 regime 歷史帳本(backlog.md P2.6「深研究夜課路線2·總經溫度計儀表板」第一步)。
`analyzer.py::_market_regime()` 只在日報生成當下即時算一次給 signal-card 信心校準用,算完就
丟——從未被存起來,沒有歷史資料就畫不出「regime 時間軸」。這裡每天記一筆
{date, label, vix, spx_chg, ndx_chg, twii_chg},dedup by date(同一天重跑只跳過,不重複追加;
故意不做「覆蓋」——覆蓋需要重寫整個檔案,而 `_is_usable()` 已經在資料不完整時擋下寫入,
覆蓋語意帶來的複雜度沒有對應的必要性),不引入新資料源、不碰 analyzer.py/main.py 本身
(唯讀 import `_market_regime`)。

抓價刻意走輕量路徑:不呼叫 `data_fetcher.fetch_us_market()`/`fetch_tw_market()`(會連帶抓
config.US_STOCKS/TW_STOCKS 整批個股,對只要 3 個指數 symbol 的用途太浪費),直接組
`_market_regime()` 需要的最小 data dict(`fetch_indicators()` 拿 VIX + `_batch_prices()` 拿
^GSPC/^IXIC/^TWII),同一套免費 yahooquery/yfinance 資料源,零新增依賴零新增 API key。

CLI: python3 -m intel.regime_ledger
"""
import os
import sys
import json
import fcntl
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "regime_ledger.jsonl")


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


def fetch_regime_inputs() -> dict:
    """組 `_market_regime()` 需要的最小 data dict,不拉整批個股。指標/指數任一段抓價失敗就該
    段回空,不拋錯——完整性由呼叫端的 `_is_usable()` 把關,這裡只管「盡量抓、缺就留空」。"""
    import data_fetcher
    try:
        indicators = data_fetcher.fetch_indicators()
    except Exception:
        indicators = {}
    try:
        raw = data_fetcher._batch_prices(["^GSPC", "^IXIC", "^TWII"])
    except Exception:
        raw = {}
    us_market = {s: raw[s] for s in ("^GSPC", "^IXIC") if s in raw}
    tw_market = {"^TWII": raw["^TWII"]} if "^TWII" in raw else {}
    return {"indicators": indicators, "us_market": us_market, "tw_market": tw_market}


def _is_usable(data: dict) -> bool:
    """抓價失敗(全部或部分)時 `_market_regime()` 會對缺的 symbol 靜默退化成 0.0% 變動——
    這跟真實「這個指數今天平盤」長得一樣,若照樣寫進帳本,regime 時間軸會混入無法分辨的假
    資料。真實 VIX 不會是 0,且三個指數 symbol(^GSPC/^IXIC/^TWII)缺任何一個都代表這次抓價
    不完整——寧可整天不記(下次排程再試),不要記一筆有部分欄位是偽造 0% 的行。"""
    ind = data.get("indicators") or {}
    vix = ind.get("vix")
    us = data.get("us_market") or {}
    tw = data.get("tw_market") or {}
    return bool(vix) and "^GSPC" in us and "^IXIC" in us and "^TWII" in tw


def record(date_str: str, regime: dict) -> bool:
    """回 True=真的新寫入一筆,False=當天已記過(跳過)。絕不拋錯。
    check-then-append 用 `fcntl.flock` 包成一段臨界區:單一每日 cron 本身不會撞(見
    `cron_daily_lock`),但手動重跑跟 cron 同時觸發時,若沒有這層鎖,兩邊各自讀到「今天還沒
    記過」再各自寫入,會產生同一天兩筆重複列(已用兩個並發呼叫實測重現過)。"""
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
                    "label": regime.get("label", "neutral"),
                    "vix": regime.get("vix"),
                    "spx_chg": regime.get("spx_chg"),
                    "ndx_chg": regime.get("ndx_chg"),
                    "twii_chg": regime.get("twii_chg"),
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
    data = fetch_regime_inputs()
    if not _is_usable(data):
        return {"date": date_str, "status": "fetch_failed"}
    try:
        from analyzer import _market_regime
        regime = _market_regime(data)
    except Exception:
        return {"date": date_str, "status": "fetch_failed"}
    written = record(date_str, regime)
    return {"date": date_str, "status": "written" if written else "skipped", **regime}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
