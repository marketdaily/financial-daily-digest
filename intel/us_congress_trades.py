"""us_congress_trades 連接器——美國會議員股票交易揭露訊號(信息差引擎美股籌碼面補源)。

資料源(2026-07-30 晚間改為官方優先):
  **主源=House Clerk 官方揭露**(disclosures-clerk.house.gov,免 key):年度索引 ZIP 內是
  TSV(含 FilingType/FilingDate/DocID),取 FilingType=='P'(交易申報書)→ 逐份抓 PTR PDF
  → PyMuPDF 抽字 → regex 解出 (TICKER)/[資產型別]/買賣別/金額區間。實測 lag 僅 3-4 天。
  **備源=CongressInvests 免費快取 API**:官方源失敗或回空才用;它凍在 2026-06-01
  (lag ~58 天,宣稱 6h 更新但 next_refresh 卡 0,POST /cache/refresh 要 Pro key),
  會被 scan() 的源級守衛判為過期而回空——**這就是這個連接器上線當天到 07-30 晚間為止
  實際產出一直是零的原因**。
與 us_13f(季度機構)/us_insider(公司內部人)互補的第三條獨立籌碼訊號:國會議員有立法/聽證
資訊優勢,揭露依法可遲至 45 天。

訊號定義(用 disclosed 揭露日算窗口——tx_date 上游爬蟲有髒值不可信):
  🔴 群聚買進:同 ticker 30 天內 ≥2 位不同議員申報買進(跨黨派/跨院更罕見,不分)
  🔴 大額買進:單筆申報區間下限 ≥ $50,001 且 14 天內揭露(多數國會交易是 $1k-$15k 小額)
  🟡 一般買進:14 天內有任何議員申報買進
  🟡 大額賣出:區間下限 ≥ $50,001 且 14 天內揭露(賣出雜訊多,小額不記)
  ⚪ 其他(只記錄不打擾)
⭐**代操再平衡過濾**(BULK_MIN/BULK_EXEMPT_MIN,見常數區):拿到真實資料後才發現 89% 的申報
是 $1,001 最小級距、且單一議員一天可申報 49 檔——那是理財顧問代操的整批再平衡,不是判斷。
不過濾的話 152 筆會產生 5 red + 17 yellow,而**那 5 個 red 全是假的**(兩位大批申報者在同
一檔上剛好重疊);過濾後是 0 red + 2 yellow。訊號要是訊號,不是資料堆。

⚠️ 已知限制:**只涵蓋眾議院**。參議院要另外爬 Senate EFD(efdsearch.senate.gov,得先 POST
同意條款拿 cookie),所以 chamber 一律標 "House",群聚訊號的覆蓋面小於「全國會」。
scan() 的源級新鮮度守衛保留:資料緣超過 STALE_DAYS 即回空+印警告,不拿舊申報冒充近況。
status() 已內建,接情報部 liveness 總表。

用法:
  單檔:   python3 -m intel.us_congress_trades NVDA
  源健康: python3 -m intel.us_congress_trades --status
  patrol: us_congress_trades.scan(watchlist) → {sym: {date, level, signal}}
"""
import os
import json
import datetime
import collections
import csv
import re
import subprocess
import time
import urllib.request

try:
    import fitz  # PyMuPDF:PTR PDF 文字抽取(venv 已裝,pypdf/pdfplumber 皆未裝)
except Exception:  # noqa: BLE001
    fitz = None

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".us_congress_trades_cache.json")
PTR_CACHE = os.path.join(HERE, ".us_congress_ptr_cache.json")

BASE = "https://congressinfor-production.up.railway.app"
HOUSE_BASE = "https://disclosures-clerk.house.gov/public_disc"
PTR_MAX_NEW_DOCS = 80        # 單輪最多抓幾份新 PTR(冷快取時防一次抓幾百份)
# 代操再平衡過濾(2026-07-30 首次拿到真實資料後校準):同一議員同一揭露日申報 ≥ BULK_MIN 檔
# 且金額在最小級距的,是理財顧問代操的整批再平衡,不是判斷 → 不當訊號。
# 實測依據:152 筆裡 136 筆(89%)是 $1,001 最小級距;單一議員同日筆數 = 49/19/16/10/7/7/…,
# 而有判斷含量的申報通常一天 1-3 檔 → 5 是分離點。金額 ≥ BULK_EXEMPT_MIN 的即使在整批裡也保留
# (大額本身就是判斷,只是罕見:全期只有 15 筆 ≥ $15,001)。
BULK_MIN = 5
BULK_EXEMPT_MIN = 15001
# 壓平空白後的一列交易:資產名 (TICKER) [資產型別] 買賣別 交易日 通知日 $下限 - $上限
_PTR_ROW = re.compile(
    r"\(([A-Z][A-Z.\-]{0,6})\)\s*\[(\w{2,3})\]\s*([A-Z])\s*"
    r"\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}\s*(\$[\d,]+)"
)
PAGE_LIMIT = 1000
MAX_PAGES = 8
BIG_AMOUNT_MIN = 50001       # 申報區間下限 ≥ 此值算大額
FRESH_DAYS = 14              # 「近期」揭露窗口
CLUSTER_DAYS = 30            # 群聚買進窗口
CLUSTER_MIN_MEMBERS = 2
STALE_DAYS = 21              # 資料緣(最新揭露日)距今超過此天數=殭屍源,scan 回空+警告


def _fetch_curl(url, timeout=20):
    """.gov / .gov.tw 等憑證鏈驗證失敗的網域用這個,不要用 urllib。"""
    r = subprocess.run(["curl", "-s", "--max-time", str(timeout), url],
                        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"curl failed rc={r.returncode} url={url}")
    return r.stdout


def _fetch_urllib(url, timeout=20):
    """一般網域用這個。UA 用完整版本字串——裸 "Mozilla/5.0" 會被部分 WAF(如 FRED)當機器人特徵擋下。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


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


def _parse_amount_min(amount_str):
    """'$1,001 - $15,000' → 1001;解析失敗回 0(當小額,不誤升級)。"""
    try:
        low = str(amount_str).split("-")[0]
        return int(low.replace("$", "").replace(",", "").strip())
    except Exception:
        return 0


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _parse_us_date(s):
    """官方索引的 'M/D/YYYY' → date;解析失敗回 None(該列略過,不猜)。"""
    try:
        m, d, y = str(s).strip().split("/")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None


def _fetch_curl_bytes(url, timeout=60):
    """binary 版 _fetch_curl(ZIP/PDF 用)。text=True 會把二進位內容弄壞,必須拿 bytes。"""
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout),
         "-A", "Mozilla/5.0 (compatible; MarketDaily/1.0; +https://marketdaily.ai)", url],
        capture_output=True,
    )
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"curl failed rc={r.returncode} url={url}")
    return r.stdout


def _load_ptr_cache():
    try:
        with open(PTR_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ptr_cache(cache):
    try:
        with open(PTR_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _house_ptr_index(year):
    """官方年度揭露索引(TSV in ZIP)→ FilingType=='P'(交易申報書)的列。"""
    import io
    import zipfile

    raw = _fetch_curl_bytes(f"{HOUSE_BASE}/financial-pdfs/{year}FD.ZIP")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if not names:
            raise RuntimeError(f"{year}FD.ZIP 內沒有 .txt 索引(內容:{z.namelist()})")
        text = z.read(names[0]).decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    return [r for r in rows if (r.get("FilingType") or "").strip() == "P"]


def _parse_ptr_pdf(pdf_bytes):
    """PTR PDF → [{ticker, trade_type, amount_min}]。PyMuPDF 抽字後壓平空白再 regex。

    版面實例(壓平前是多行):
        Intuit Inc. - Common Stock (INTU) [ST] S 06/10/2026 07/07/2026 $15,001 - $50,000
    只收 [ST](股票);選擇權/債券/基金等其他資產型別對「議員在買什麼股票」這個訊號沒用,
    而且欄位格式不同,硬解只會產生髒值。
    """
    if fitz is None:
        return []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "\n".join(p.get_text() for p in doc)
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in _PTR_ROW.finditer(flat):
        ticker, asset, ttype, amount = m.group(1), m.group(2), m.group(3), m.group(4)
        if asset != "ST":
            continue
        kind = {"P": "buy", "S": "sell"}.get(ttype)
        if not kind:            # E=exchange 之類,不當買賣訊號
            continue
        out.append({"ticker": ticker, "trade_type": kind,
                    "amount_min": _parse_amount_min(amount)})
    return out


def drop_bulk_rebalance(flat):
    """純函式:濾掉理財顧問代操的整批再平衡 → (保留清單, 丟棄筆數)。

    flat: [{member, disclosed, amount_min, ticker, ...}](跨 ticker 的平坦清單)。
    判準=同一議員同一揭露日申報 ≥ BULK_MIN 檔,且該筆金額 < BULK_EXEMPT_MIN。

    為什麼不能放在 classify() 裡:那是單一 ticker 的純函式,看不到「這位議員今天總共報了幾檔」
    ——而那正是區分「判斷」與「再平衡」的唯一線索。
    """
    batch = collections.Counter((t.get("member"), t.get("disclosed")) for t in flat)
    kept, dropped = [], 0
    for t in flat:
        if (batch[(t.get("member"), t.get("disclosed"))] >= BULK_MIN
                and t.get("amount_min", 0) < BULK_EXEMPT_MIN):
            dropped += 1
            continue
        kept.append(t)
    return kept, dropped


def _fetch_house_clerk(today):
    """官方 House Clerk 源 → {ticker: [{member, chamber, trade_type, amount_min, disclosed}]}。

    2026-07-30 加入:原本唯一的 CongressInvests 免費快取凍在 2026-06-01(lag 58 天),
    整個連接器實際產出為零(源級守衛正確地回空)。官方源實測 lag 僅 3 天。

    ⚠️ 已知限制:**只涵蓋眾議院**。參議院要另外爬 Senate EFD(efdsearch.senate.gov,
    要先 POST 同意條款拿 cookie,是另一個工),所以 chamber 一律標 "House"。
    群聚訊號因此只算眾議員,門檻語義不變(≥2 位不同議員)但覆蓋面小於「全國會」。

    PTR 文件一旦申報就不會變 → 用獨立的永久快取(依 DocID),不受主快取「每日清空」影響。
    """
    idx = _house_ptr_index(today.year)
    cut = (today - datetime.timedelta(days=CLUSTER_DAYS)).isoformat()
    recent = []
    for r in idx:
        fd = _parse_us_date(r.get("FilingDate"))
        if fd and fd.isoformat() >= cut:
            recent.append((r, fd))
    recent.sort(key=lambda x: x[1], reverse=True)

    ptr_cache = _load_ptr_cache()
    fetched = misses = 0
    by_ticker, flat = {}, []
    for r, fd in recent:
        doc_id = (r.get("DocID") or "").strip()
        if not doc_id:
            continue
        if doc_id not in ptr_cache:
            if fetched >= PTR_MAX_NEW_DOCS:
                continue
            try:
                pdf = _fetch_curl_bytes(f"{HOUSE_BASE}/ptr-pdfs/{r.get('Year', today.year)}/{doc_id}.pdf")
                ptr_cache[doc_id] = _parse_ptr_pdf(pdf)
            except Exception:
                misses += 1
                continue
            fetched += 1
            time.sleep(0.2)
        name = " ".join(x for x in ((r.get("First") or "").strip(), (r.get("Last") or "").strip()) if x)
        for t in ptr_cache.get(doc_id) or []:
            flat.append({
                "member": name or None,
                "chamber": "House",
                "trade_type": t["trade_type"],
                "amount_min": t["amount_min"],
                "disclosed": fd.isoformat(),
                "ticker": t["ticker"],
            })
    if fetched:
        _save_ptr_cache(ptr_cache)

    if recent:
        # 源的最新申報日取自索引本身(過濾之前),供 source_edge() 判斷上游活著沒有。
        c = _load_cache()
        c[f"_edge:{today.isoformat()}"] = max(fd for _, fd in recent).isoformat()
        _save_cache(c)

    kept, dropped = drop_bulk_rebalance(flat)
    for t in kept:
        by_ticker.setdefault(t.pop("ticker"), []).append(t)
    if dropped:
        print(f"ℹ️ us_congress_trades: 濾掉 {dropped}/{len(flat)} 筆代操再平衡"
              f"(同議員同日 ≥{BULK_MIN} 檔且 <${BULK_EXEMPT_MIN:,})")
    if misses:
        # 不靜默:抓不到的文件數要看得見,否則「產出變少」會被誤讀成「議員沒交易」。
        print(f"⚠️ us_congress_trades: {misses} 份 PTR 文件抓取/解析失敗(本輪略過)")
    return by_ticker


def _fetch_all_by_ticker(today):
    """分頁抓完整快取(~5-6k 筆),本地按 ticker 分組。同日重複呼叫走檔案快取。

    2026-07-30 起先試官方 House Clerk 源(lag ~3 天),失敗或產出為空才退回
    CongressInvests 免費快取(lag ~58 天,會被 scan() 的源級守衛判為過期而回空)。
    """
    cache = _load_cache()
    ck = f"_all:{today.isoformat()}"
    if ck in cache:
        return cache[ck]

    try:
        house = _fetch_house_clerk(today)
    except Exception as e:
        print(f"⚠️ us_congress_trades 官方源失敗({type(e).__name__}: {str(e)[:80]}),退回 CongressInvests 快取")
        house = {}
    if house:
        # ⚠️ 必須重讀:_fetch_house_clerk() 已經把 _edge:<today> 寫進檔案,若沿用函式開頭那份
        # 舊 cache 變數存回去,會把它洗掉。source_edge() 有 fallback,所以洗掉不會報錯——
        # 只會安靜地退回「過濾後的日期」,守衛從此量錯東西(2026-07-30 當場踩到)。
        cache = _load_cache()
        cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
        cache[ck] = house
        _save_cache(cache)
        return house

    rows = []
    offset = 0
    for _ in range(MAX_PAGES):
        raw = json.loads(_fetch_urllib(f"{BASE}/trades?limit={PAGE_LIMIT}&offset={offset}"))
        rows.extend(raw.get("trades", []))
        if not raw.get("has_more"):
            break
        offset += PAGE_LIMIT
        time.sleep(0.4)

    by_ticker = {}
    for t in rows:
        sym = str(t.get("ticker", "")).upper().strip()
        if not sym:
            continue
        by_ticker.setdefault(sym, []).append({
            "member": t.get("member"),
            "chamber": t.get("chamber"),
            "trade_type": t.get("trade_type"),
            "amount_min": _parse_amount_min(t.get("amount")),
            "disclosed": str(t.get("disclosed", ""))[:10],
        })

    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = by_ticker
    _save_cache(cache)
    return by_ticker


def classify(trades, today):
    """純函式:單一 ticker 的申報清單 → red/yellow/plain。
    trades: [{member, trade_type, amount_min, disclosed}],today: datetime.date。"""
    fresh_cut = (today - datetime.timedelta(days=FRESH_DAYS)).isoformat()
    cluster_cut = (today - datetime.timedelta(days=CLUSTER_DAYS)).isoformat()

    cluster_buyers, fresh_buys, big_fresh_buys, big_fresh_sells = set(), [], [], []
    for t in trades:
        d = t.get("disclosed", "")
        if not _parse_date(d):
            continue
        if t.get("trade_type") == "buy":
            if d >= cluster_cut:
                cluster_buyers.add(t.get("member"))
            if d >= fresh_cut:
                fresh_buys.append(t)
                if t.get("amount_min", 0) >= BIG_AMOUNT_MIN:
                    big_fresh_buys.append(t)
        elif t.get("trade_type") == "sell" and d >= fresh_cut and t.get("amount_min", 0) >= BIG_AMOUNT_MIN:
            big_fresh_sells.append(t)

    if len(cluster_buyers) >= CLUSTER_MIN_MEMBERS and fresh_buys:
        names = "、".join(sorted(x for x in cluster_buyers if x)[:3])
        return {"level": "red",
                "signal": f"國會群聚買進:{CLUSTER_DAYS}天內 {len(cluster_buyers)} 位議員申報買進({names})"}
    if big_fresh_buys:
        t = max(big_fresh_buys, key=lambda x: x.get("amount_min", 0))
        return {"level": "red",
                "signal": f"國會大額買進:{t.get('member')}({t.get('chamber')}) 申報 ≥${t.get('amount_min'):,}({t.get('disclosed')} 揭露)"}
    if fresh_buys:
        t = fresh_buys[0]
        return {"level": "yellow",
                "signal": f"國會議員買進:{t.get('member')}({t.get('chamber')}) {t.get('disclosed')} 揭露"}
    if big_fresh_sells:
        t = max(big_fresh_sells, key=lambda x: x.get("amount_min", 0))
        return {"level": "yellow",
                "signal": f"國會大額賣出:{t.get('member')}({t.get('chamber')}) 申報 ≥${t.get('amount_min'):,}({t.get('disclosed')} 揭露)"}
    return {"level": "plain", "signal": f"近{FRESH_DAYS}天無國會申報買賣"}


def congressinvests(key, today=None):
    """單一標的查詢,回 dict(含 date + classify() 結果)或 None(抓不到/查無資料)。"""
    today = today or datetime.date.today()
    key = str(key).upper().strip()
    cache = _load_cache()
    ck = f"{key}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]

    try:
        by_ticker = _fetch_all_by_ticker(today)
    except Exception:
        return None
    trades = by_ticker.get(key)
    if trades is None:
        return None

    out = {"date": today.isoformat()}
    out.update(classify(trades, today))

    cache = _load_cache()
    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    _save_cache(cache)
    return out


def data_edge(by_ticker):
    """全表最新揭露日(str)或 None。"""
    dates = [t["disclosed"] for ts in by_ticker.values() for t in ts if _parse_date(t.get("disclosed", ""))]
    return max(dates) if dates else None


def source_edge(today, by_ticker):
    """**源**的最新申報日(未經任何過濾),優先於 data_edge()。

    為什麼不能直接用 data_edge:代操再平衡過濾之後,by_ticker 的最新日期會比源本身舊
    (實測當天:源 07-26 → 過濾後 07-24)。若某段時間的申報恰好全是整批再平衡而被濾光,
    data_edge 會顯得過期 → scan() 的源級守衛誤判「源過期」把整個連接器關掉,而且印出來的
    理由是錯的(源好得很,是我們自己濾掉的)。守衛要衡量的是**上游還活著嗎**,不是我們留下幾筆。
    """
    edge = _load_cache().get(f"_edge:{today.isoformat()}")
    return edge or data_edge(by_ticker)


def status(today=None):
    """源健康:{data_edge, lag_days, stale}。接情報部 liveness 總表用。"""
    today = today or datetime.date.today()
    try:
        by = _fetch_all_by_ticker(today)
        edge = source_edge(today, by)
    except Exception:
        return {"data_edge": None, "lag_days": None, "stale": True}
    lag = (today - datetime.date.fromisoformat(edge)).days if edge else None
    return {"data_edge": edge, "lag_days": lag, "stale": lag is None or lag > STALE_DAYS}


def scan(keys, pause=0.0):
    """批次掃描,回 {key: result}。整包快取已在本地,逐 key 純查表,不再打 API(pause 保留介面相容)。
    源級新鮮度守衛:資料緣過期直接回空+印警告,不拿舊申報冒充近況(殭屍連接器要可見)。"""
    today = datetime.date.today()
    try:
        by_ticker = _fetch_all_by_ticker(today)
    except Exception:
        return {}
    edge = source_edge(today, by_ticker)
    if not edge or (today - datetime.date.fromisoformat(edge)).days > STALE_DAYS:
        print(f"⚠️ us_congress_trades 源過期:資料緣 {edge},超過 {STALE_DAYS} 天,本輪跳過(升級路徑見模組 docstring)")
        return {}
    out = {}
    for k in keys:
        sym = str(k).upper().strip()
        trades = by_ticker.get(sym)
        if trades is None:
            continue
        r = {"date": today.isoformat()}
        r.update(classify(trades, today))
        out[sym] = r
        if pause:
            time.sleep(pause)
    return out


if __name__ == "__main__":
    import sys
    if "--status" in sys.argv:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    else:
        key = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
        print(json.dumps(congressinvests(key), ensure_ascii=False, indent=1))
