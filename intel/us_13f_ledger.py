"""美股13F機構持股歷史帳本(信息差引擎美股第五件,curriculum.md I 節/backlog P2.6 兩處明文
點名「13F per-stock反查工程量遠大於Form4,留待未來評估」——2026-07-07 研究確認 SEC 官方季度
bulk data 真實可行,非假設,補上這個長期缺口)。

資料源:SEC 官方 Form 13F Data Sets(免費/免key,`sec.gov/data-research/sec-markets-data/
form-13f-data-sets`)。每季發布一次(該季結束後45天申報截止,資料集才穩定),每份 zip 內
`SUBMISSION.tsv`(申報後設資料:CIK/申報日期/申報類型/報告期別)+`INFOTABLE.tsv`(逐筆持股
明細:CUSIP/股數/股份類型)。

CUSIP 對照表(2026-07-07 建置時實測驗證,非憑記憶硬編——用該季 INFOTABLE.tsv 對每檔股票
以 SSHPRNAMTTYPE=='SH' + PUTCALL=='' 篩出多數決 CUSIP,例如 AAPL 9585 筆列都指向同一組
CUSIP,雜訊<0.1%):
  - 用 CUSIP 而非公司名稱比對是關鍵設計決策——NAMEOFISSUER 是申報人自由輸入欄位,同一檔股票
    有數百種拼法變體(含錯字/多餘空白),且名稱相似的完全不同公司會誤命中(如 AAPL vs
    "APPLE HOSPITALITY REIT"),CUSIP 才是穩定的唯一識別碼。
  - GOOGL(Class A)=02079K305,與 GOOG(Class C)=02079K107 是不同 CUSIP,已用真實資料交叉
    驗證分布避免誤取錯誤股份類別;BRK-B(Class B)=084670702 同理與 BRK-A(Class A)
    084670108 分開。

篩選規則(同樣以真實資料驗證過,非臆測):
  - SSHPRNAMTTYPE=='SH':排除面額(PRN,通常是債券部位)。
  - PUTCALL==''(空字串):排除選擇權合成部位,只算真實持有股份。
  - SUBMISSIONTYPE in {13F-HR, 13F-HR/A}:排除 13F-NT(通知書,無持股明細,只是「委託他人代
    申報」的聲明);同一 (CIK, PERIODOFREPORT) 若有多筆(原始+修正案),只留 FILING_DATE 最新
    一筆的 accession,防修正案被重複計入(2026Q1 資料實測 166 組重複)。

Ledger 鍵是 (ticker, period_of_report) 而非日期——13F 是季度資料,同一份 zip 可能混有其他
季度的遲交/修正案(絕大多數屬當季,但確實會混入),dedup by (ticker,period) 天然把這些歸位到
正確的歷史格子,immutable 不覆蓋(同 regime_ledger/macro_rates_ledger/pe_ratio_ledger 慣例)。

用法:
  抓最新一季(累積記帳,自動跳過已處理過的zip): python3 -m intel.us_13f_ledger run
  讀已記錄的季度變動訊號(供 patrol.py 併入夜間簡報,唯讀不觸網): intel.us_13f_ledger.active_signals()
"""
import os
import sys
import csv
import io
import re
import json
import math
import fcntl
import zipfile
import tempfile
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "us_13f_ledger.jsonl")
PROCESSED = os.path.join(HERE, ".us_13f_processed.json")

SEC = "https://www.sec.gov"
DATA_SETS_PAGE = f"{SEC}/data-research/sec-markets-data/form-13f-data-sets"
UA = "MarketDaily research contact@marketdaily.ai"

# ticker -> CUSIP,見上方 docstring 驗證方法。QQQ/BRK-A 等非 watchlist 標的不收錄。
CUSIP_MAP = {
    "AAPL": "037833100",
    "MSFT": "594918104",
    "GOOGL": "02079K305",
    "AMZN": "023135106",
    "META": "30303M102",
    "NVDA": "67066G104",
    "TSLA": "88160R101",
    "AMD": "007903107",
    "TSM": "874039100",
    "ARM": "042068205",
    "JPM": "46625H100",
    "GS": "38141G104",
    "BRK-B": "084670702",
}
ACCEPTED_SUBMISSION_TYPES = {"13F-HR", "13F-HR/A"}
QOQ_NOTABLE_PCT = 10.0  # 季增減幅度達此門檻才算「notable」訊號,見 classify()


def _finite_positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _default_watchlist_tickers():
    try:
        import config
        return set(config.US_STOCKS) & set(CUSIP_MAP)
    except Exception:
        return set(CUSIP_MAP)


def _fetch_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_zip_url():
    """解析 SEC 13F data sets 頁面,回傳列表中第一個(最新)zip 的完整 URL;找不到回 None。"""
    try:
        html = _fetch_bytes(DATA_SETS_PAGE, timeout=20).decode("utf-8", errors="replace")
    except Exception:
        return None
    matches = re.findall(
        r'href="(/files/structureddata/data/form-13f-data-sets/[0-9a-zA-Z-]+_form13f\.zip)"',
        html,
    )
    if not matches:
        return None
    return SEC + matches[0]


def _download_zip(url, timeout=180):
    """串流下載到暫存檔(zip ~95MB,不整份留在記憶體),回傳暫存檔路徑;呼叫端負責清理。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                tmp.write(chunk)
        tmp.close()
        return tmp.name
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise


def _dominant_accessions(zf):
    """讀 SUBMISSION.tsv,篩 ACCEPTED_SUBMISSION_TYPES,同一 (CIK,PERIODOFREPORT) 只留
    FILING_DATE 最新一筆 accession(防修正案雙重計算)。回傳 {accession: period_of_report}。"""
    best = {}  # (cik, period) -> (filing_date, accession)
    with zf.open("SUBMISSION.tsv") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
        for row in reader:
            if row.get("SUBMISSIONTYPE", "") not in ACCEPTED_SUBMISSION_TYPES:
                continue
            cik = row.get("CIK", "").strip()
            period = row.get("PERIODOFREPORT", "").strip()
            filing_date = row.get("FILING_DATE", "").strip()
            accession = row.get("ACCESSION_NUMBER", "").strip()
            if not (cik and period and filing_date and accession):
                continue
            key = (cik, period)
            prev = best.get(key)
            if prev is None or filing_date > prev[0]:
                best[key] = (filing_date, accession)
    return {accession: period for (_, period), (_, accession) in best.items()}


def _dominant_period(accession_to_period):
    """從 accession_to_period 選出出現次數最多的 period——這才是該 zip「真正代表」的當季
    完整快照。**2026-07-07 建置時實測抓到的真實資料坑**:每份 zip 除了當季主力(45天申報期
    內完成的絕大多數申報)外,還混著少量對舊季度的遲來修正案(見 module docstring),舊季度
    在該 zip 裡通常只有 1-2 個 filer——如果照單全收會把「AAPL 在 2013 年只有 1 家機構持股」
    這種明顯荒謬的假象寫進歷史帳本(真實情況是幾千家,只是那年的完整申報是在別份舊 zip 裡)。
    只保留真正完整的當季快照,其餘一律捨棄不記,寧可帳本某幾季空缺也不放假資料。"""
    counts = {}
    for period in accession_to_period.values():
        counts[period] = counts.get(period, 0) + 1
    if not counts:
        return None
    top_count = max(counts.values())
    top_periods = [p for p, c in counts.items() if c == top_count]
    if len(top_periods) > 1:
        return None  # 真平手,無從判斷哪一期才是完整快照(平手時原本靠TSV行序決定,非語意判準),寧可整份zip跳過不記
    return top_periods[0]


def _aggregate_holdings(zf, accession_to_period, target_period):
    """讀 INFOTABLE.tsv,只處理 kept accession 中屬於 target_period 者(見 _dominant_period)
    + CUSIP 命中 CUSIP_MAP + SSHPRNAMTTYPE=='SH' + PUTCALL==''(排除選擇權/債券部位,見
    module docstring 驗證過程)。回傳 {ticker: {"shares": int, "filers": set(accession)}}。"""
    cusip_to_ticker = {v: k for k, v in CUSIP_MAP.items()}
    kept_accessions = {a for a, p in accession_to_period.items() if p == target_period}
    agg = {}
    with zf.open("INFOTABLE.tsv") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
        for row in reader:
            cusip = row.get("CUSIP", "").strip()
            ticker = cusip_to_ticker.get(cusip)
            if not ticker:
                continue
            accession = row.get("ACCESSION_NUMBER", "").strip()
            if accession not in kept_accessions:
                continue  # 非採用的 accession(被更新的修正案取代/屬13F-NT/屬非目標季度雜訊)
            if row.get("SSHPRNAMTTYPE", "").strip() != "SH":
                continue
            if row.get("PUTCALL", "").strip():
                continue
            try:
                shares = int(float(row.get("SSHPRNAMT", "0") or 0))
            except (ValueError, OverflowError):
                continue  # 單一畸形列(如inf/超大數字字串觸發OverflowError)只跳過該列,不可讓整份zip彙總失敗
            if shares <= 0:
                continue
            slot = agg.setdefault(ticker, {"shares": 0, "filers": set()})
            slot["shares"] += shares
            slot["filers"].add(accession)
    return agg


def parse_zip(path) -> dict:
    """回傳 {(ticker, period): {"shares","filers"}},只含該 zip 真正代表的單一當季完整快照
    (見 _dominant_period)——不是每個出現過的 period 都收錄。"""
    with zipfile.ZipFile(path) as zf:
        accession_to_period = _dominant_accessions(zf)
        target_period = _dominant_period(accession_to_period)
        if target_period is None:
            return {}
        agg = _aggregate_holdings(zf, accession_to_period, target_period)
    return {(ticker, target_period): data for ticker, data in agg.items()}


def _load_seen_keys():
    seen = set()
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    seen.add((row.get("ticker"), row.get("period")))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seen


def record_snapshot(agg: dict) -> dict:
    """dedup by (ticker,period),check-then-append 用 fcntl.flock 包成臨界區(同其餘三個
    ledger 已驗證過的 TOCTOU 防護模式)。回傳 {"written": [...], "skipped": [...]}。"""
    written, skipped = [], []
    os.makedirs(os.path.dirname(LEDGER) or ".", exist_ok=True)
    lock_path = LEDGER + ".lock"
    with open(lock_path, "a") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            seen = _load_seen_keys()
            with open(LEDGER, "a", encoding="utf-8") as f:
                for key in sorted(agg.keys()):
                    ticker, period = key
                    if key in seen:
                        skipped.append(list(key))
                        continue
                    data = agg[key]
                    shares = data["shares"]
                    filer_count = len(data["filers"])
                    if shares <= 0 or filer_count <= 0:
                        skipped.append(list(key))
                        continue
                    row = {
                        "ticker": ticker,
                        "period": period,
                        "total_shares": shares,
                        "filer_count": filer_count,
                        "fetched_at": datetime.date.today().isoformat(),
                    }
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    seen.add(key)
                    written.append(list(key))
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
    return {"written": written, "skipped": skipped}


def _load_processed_urls():
    try:
        with open(PROCESSED, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _mark_processed(url):
    urls = _load_processed_urls()
    urls.add(url)
    try:
        with open(PROCESSED, "w", encoding="utf-8") as f:
            json.dump(sorted(urls), f)
    except Exception:
        pass


def run() -> dict:
    """檢查 SEC 頁面最新 zip 是否已處理過;沒有新的就是 already_processed(不下載,每日輪詢
    成本極低),真的有新一季才下載 95MB+解析(每年僅 4 次)。"""
    url = latest_zip_url()
    if not url:
        return {"status": "no_url_found"}
    if url in _load_processed_urls():
        return {"status": "already_processed", "url": url}
    path = None
    try:
        path = _download_zip(url, timeout=180)
        agg = parse_zip(path)
    except Exception as e:
        return {"status": "fetch_or_parse_failed", "url": url, "error": str(e)[:200]}
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass
    result = record_snapshot(agg)
    _mark_processed(url)
    return {"status": "done", "url": url, **result}


def _period_sort_key(period_str):
    try:
        return datetime.datetime.strptime(period_str, "%d-%b-%Y")
    except Exception:
        return datetime.datetime.min


def _rows_for_ticker(ticker):
    rows = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if row.get("ticker") == ticker:
                        rows.append(row)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    rows.sort(key=lambda r: _period_sort_key(r.get("period", "")))
    return rows


def classify(ticker: str) -> dict:
    """比較最近兩期機構總持股(shares)算 QoQ 變動%。樣本<2期誠實回 insufficient_data,
    不硬湊訊號(同其餘 ledger 完整性守門紀律)。方向不下多空判斷,只呈現變動幅度——機構加碼
    /減碼何者是「對」的訊號需靠 signal_backtest_harness 事後驗證,connector 本身只誠實記錄。"""
    rows = _rows_for_ticker(ticker)
    if len(rows) < 2:
        return {"ticker": ticker, "level": "insufficient_data", "periods_recorded": len(rows)}
    prev, latest = rows[-2], rows[-1]
    prev_shares, latest_shares = prev.get("total_shares"), latest.get("total_shares")
    # 髒值防呆(2026-07-09 VERIFIER 補):latest_shares 原本完全沒驗證,缺欄位時 `.get(...,0)`
    # 靜默退化成 0,會印出假的「減碼 -100.0%」確定性訊號而非誠實回報樣本不足。
    if not _finite_positive(prev_shares) or not _finite_positive(latest_shares):
        return {"ticker": ticker, "level": "insufficient_data", "periods_recorded": len(rows)}
    pct_change = (latest_shares - prev_shares) / prev_shares * 100.0
    if abs(pct_change) >= QOQ_NOTABLE_PCT:
        level = "yellow"
        direction = "加碼" if pct_change > 0 else "減碼"
        signal = f"機構季度持股{direction} {pct_change:+.1f}%({latest.get('filer_count')}家申報)"
    else:
        level = "plain"
        signal = f"機構季度持股變動 {pct_change:+.1f}%(變動不大)"
    return {
        "ticker": ticker,
        "level": level,
        "signal": signal,
        "pct_change": round(pct_change, 1),
        "latest_period": latest.get("period"),
        "prev_period": prev.get("period"),
        "filer_count": latest.get("filer_count"),
        "periods_recorded": len(rows),
    }


def active_signals(tickers=None) -> dict:
    """唯讀,不觸網——供 patrol.py 每晚呼叫。只回傳 level=='yellow'(notable QoQ變動)的
    ticker,plain/insufficient_data 不進 by_code(同 tw_margin/tw_sbl 慣例)。"""
    wl = tickers if tickers is not None else _default_watchlist_tickers()
    out = {}
    for ticker in sorted(wl):
        if ticker not in CUSIP_MAP:
            continue
        try:
            result = classify(ticker)
        except Exception:
            # 單一 ticker 的帳本列髒掉(如非數值 total_shares)不可讓整晚其餘 ticker 的訊號一起消失
            continue
        if result.get("level") == "yellow":
            out[ticker] = result
    return out


def format_line(sig: dict) -> str:
    return f"{sig['ticker']}:{sig['signal']}(較 {sig.get('prev_period')} 至 {sig.get('latest_period')})"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    elif cmd == "signals":
        print(json.dumps(active_signals(), ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
