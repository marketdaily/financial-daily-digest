"""美股內部人交易(Form 4)連接器(信息差引擎美股信息源第三件)。
FMP 免費層 insider-trading 端點回 402 Payment Required 不可用(見 curriculum.md I 節);
SEC EDGAR 本身完全免費、無需 key,是美股籌碼面唯一免費路徑。
資料鏈:ticker→CIK(company_tickers.json)→個股 Form 4 filing 清單(browse-edgar atom feed)
→ filing index.json 找出 primary XML 檔名 → 解析 ownershipDocument 拿真實交易明細
(transactionCode/股數/價格/內部人職稱)。
訊號定義(過濾雜訊——多數 Form 4 交易是選擇權行使/獎酬/稅款代扣,不是真金白銀進出場):
  🔴 內部人「公開市場買進」(transactionCode=P) —— 罕見且高信號(內部人自願掏錢買,無稅務誘因)
  🔴 群聚買進:同股票 10 天內 ≥2 位不同內部人買進 —— 比單一買進更強的訊號
  🟡 內部人「公開市場賣出」(transactionCode=S)且金額 ≥ $50,000 —— 賣出雜訊多(常規分散/10b5-1),小額不記
  忽略:M(選擇權行使)/A(獎酬取得)/F(稅款代扣)/G(贈與)/C(轉換) 等非公開市場交易
用法:
  輪詢一次(累積記帳,回傳本次新訊號): python3 -m intel.us_insider poll
  今日/近N日訊號(供 patrol.py 併入夜間簡報,含群聚買進合成訊號): intel.us_insider.todays_signals(days=2)
"""
import os, sys, json, time, datetime, urllib.request, urllib.error
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CIK_CACHE = os.path.join(HERE, ".us_cik_map.json")
SEEN_CACHE = os.path.join(HERE, ".us_insider_seen.json")
SIGNALS_LOG = os.path.join(HERE, "us_insider_signals.jsonl")
WATCHLIST_EXTRA = os.path.join(HERE, "us_watchlist.json")

SEC = "https://www.sec.gov"
UA = "MarketDaily research contact@marketdaily.ai"
REQ_DELAY = 0.35  # SEC 節流建議:別打太快被 ban
CIK_MAP_TTL_DAYS = 30
MIN_SELL_VALUE = 50000  # 低於此金額的公開市場賣出視為雜訊不記
FILINGS_PER_SYMBOL = 6  # 每檔每次輪詢看最近幾筆 Form 4(dedup 後大多數輪次是 0 新增)


def _default_watchlist():
    try:
        sys.path.insert(0, ROOT)
        import config
        return set(config.US_STOCKS)
    except Exception:
        return {"AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                "AMD", "TSM", "ARM", "JPM", "GS", "BRK-B"}


def build_watchlist():
    wl = _default_watchlist()
    try:
        with open(WATCHLIST_EXTRA, encoding="utf-8") as f:
            extra = json.load(f)
        for x in extra.get("extra", []):
            sym = str(x.get("symbol", "")).upper().strip()
            if sym:
                wl.add(sym)
    except Exception:
        pass
    return wl


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    finally:
        time.sleep(REQ_DELAY)
    return data


def _load_cik_map(path=CIK_CACHE):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        age_days = (datetime.date.today() - datetime.date.fromisoformat(doc["_fetched"])).days
        if age_days <= CIK_MAP_TTL_DAYS:
            return doc["map"]
    except Exception:
        pass
    return _refresh_cik_map(path)


def _refresh_cik_map(path=CIK_CACHE):
    """全市場 ticker→CIK 對照表(SEC 靜態檔,無需 key)。只存我們用得到的欄位省空間。"""
    try:
        raw = json.loads(_fetch(f"{SEC}/files/company_tickers.json", timeout=30))
    except Exception as e:
        print(f"cik map fetch fail: {e}", file=sys.stderr)
        return {}
    m = {}
    for row in raw.values():
        t = str(row.get("ticker", "")).upper().strip()
        c = row.get("cik_str")
        if t and c is not None:
            m[t] = str(c)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_fetched": datetime.date.today().isoformat(), "map": m}, f)
    return m


def symbol_to_cik(symbol, cik_map=None):
    cik_map = cik_map if cik_map is not None else _load_cik_map()
    return cik_map.get(symbol.upper())


def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _local(elem, path):
    """namespace-agnostic 版 elem.find,path 用逗號分隔多層 local tag name。"""
    cur = elem
    for name in path.split("/"):
        nxt = None
        for child in cur:
            if _strip_ns(child.tag) == name:
                nxt = child
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def recent_form4_filings(cik, count=FILINGS_PER_SYMBOL):
    """回該 CIK 最近幾筆 Form 4 filing:[{accession, filing_date, href}]。"""
    cik10 = str(cik).zfill(10)
    url = (f"{SEC}/cgi-bin/browse-edgar?action=getcompany&CIK={cik10}"
           f"&type=4&dateb=&owner=include&count={count}&output=atom")
    raw = _fetch(url)
    root = ET.fromstring(raw)
    out = []
    for entry in root:
        if _strip_ns(entry.tag) != "entry":
            continue
        content = _local(entry, "content")
        if content is None:
            continue
        acc = _local(content, "accession-number")
        fdate = _local(content, "filing-date")
        href = _local(content, "filing-href")
        if acc is None or fdate is None:
            continue
        out.append({
            "accession": acc.text.strip(),
            "filing_date": fdate.text.strip(),
            "href": href.text.strip() if href is not None else "",
        })
    return out


def _pick_primary_doc(items):
    """從 filing index.json 的 item 清單挑出 ownership 主文件檔名(非 index 的 .xml)。純函式,離線可測。"""
    for it in items:
        name = it.get("name", "")
        if name.lower().endswith(".xml") and "index" not in name.lower():
            return name
    return None


def _filing_primary_doc_url(cik, accession):
    """filing index.json 找出非 index 的 .xml 檔(ownership 主文件),組完整 URL。"""
    accnodash = accession.replace("-", "")
    cik_nolead = str(int(cik))
    idx_url = f"{SEC}/Archives/edgar/data/{cik_nolead}/{accnodash}/index.json"
    idx = json.loads(_fetch(idx_url))
    name = _pick_primary_doc(idx.get("directory", {}).get("item", []))
    return f"{SEC}/Archives/edgar/data/{cik_nolead}/{accnodash}/{name}" if name else None


def _text(elem):
    return elem.text.strip() if elem is not None and elem.text else None


def _num(elem):
    t = _text(elem)
    if t is None:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_form4_xml(xml_bytes):
    """回 (owner_info dict, transactions list)。owner_info={name,title};
    transactions=[{code, acquired_disposed, shares, price, date}]。"""
    root = ET.fromstring(xml_bytes)
    owner_name = None
    owner_title = None
    rep = root.find("reportingOwner")
    if rep is not None:
        oid = rep.find("reportingOwnerId")
        if oid is not None:
            n = oid.find("rptOwnerName")
            owner_name = _text(n)
        rel = rep.find("reportingOwnerRelationship")
        if rel is not None:
            title = _text(rel.find("officerTitle"))
            flags = []
            if _text(rel.find("isDirector")) == "1":
                flags.append("董事")
            if _text(rel.find("isOfficer")) == "1":
                flags.append(title or "高管")
            if _text(rel.find("isTenPercentOwner")) == "1":
                flags.append("10%以上大股東")
            owner_title = "、".join(flags) if flags else None

    txs = []
    table = root.find("nonDerivativeTable")
    if table is not None:
        for tx in table.findall("nonDerivativeTransaction"):
            coding = tx.find("transactionCoding")
            code = _text(coding.find("transactionCode")) if coding is not None else None
            amounts = tx.find("transactionAmounts")
            shares = price = ad_code = None
            if amounts is not None:
                shares = _num(amounts.find("transactionShares/value"))
                price = _num(amounts.find("transactionPricePerShare/value"))
                ad_code = _text(amounts.find("transactionAcquiredDisposedCode/value"))
            tdate = _text(tx.find("transactionDate/value"))
            txs.append({"code": code, "acquired_disposed": ad_code,
                        "shares": shares, "price": price, "date": tdate})
    return {"name": owner_name, "title": owner_title}, txs


def classify_transaction(code, acquired_disposed):
    """回 'buy' / 'sell' / None(雜訊,例如選擇權行使 M、獎酬取得 A、稅款代扣 F、贈與 G)。"""
    if code == "P" and acquired_disposed == "A":
        return "buy"
    if code == "S" and acquired_disposed == "D":
        return "sell"
    return None


def aggregate_transactions(txs):
    """10b5-1 常規賣股計畫一天常拆成 10-30 筆不同執行價的交易列;逐列各發一則訊號=資料堆不是訊號。
    合併同一天同方向的交易列成一筆(股數加總、價格用股數加權平均),回傳
    [{code, acquired_disposed, shares, price, date}]。純函式,離線可測。"""
    groups = {}
    order = []
    for tx in txs:
        kind = classify_transaction(tx.get("code"), tx.get("acquired_disposed"))
        if kind is None:
            continue
        key = (tx.get("code"), tx.get("acquired_disposed"), tx.get("date"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(tx)
    out = []
    for key in order:
        rows = groups[key]
        code, ad, date = key
        total_shares = sum(r.get("shares") or 0 for r in rows)
        total_value = sum((r.get("shares") or 0) * (r.get("price") or 0) for r in rows)
        avg_price = (total_value / total_shares) if total_shares else 0
        out.append({"code": code, "acquired_disposed": ad, "date": date,
                    "shares": total_shares, "price": round(avg_price, 4), "tranches": len(rows)})
    return out


def _load_seen(path=SEEN_CACHE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_seen(seen, path=SEEN_CACHE):
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def _append_signal(sig, path=SIGNALS_LOG):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig, ensure_ascii=False) + "\n")


def poll(seen_path=SEEN_CACHE, log_path=SIGNALS_LOG):
    """打每檔 watchlist 最近 Form 4 filing,新的才解析內文。回傳本次新增訊號 list。"""
    wl = build_watchlist()
    cik_map = _load_cik_map()
    seen = _load_seen(seen_path)
    today = datetime.date.today().isoformat()
    new_signals = []

    for sym in sorted(wl):
        cik = symbol_to_cik(sym, cik_map)
        if not cik:
            continue
        try:
            filings = recent_form4_filings(cik)
        except Exception as e:
            print(f"{sym} form4 feed fail: {e}", file=sys.stderr)
            continue
        for filing in filings:
            key = f"{sym}:{filing['accession']}"
            if key in seen:
                continue
            seen[key] = today
            try:
                doc_url = _filing_primary_doc_url(cik, filing["accession"])
                if not doc_url:
                    continue
                owner, txs = parse_form4_xml(_fetch(doc_url))
            except Exception as e:
                print(f"{sym} {filing['accession']} parse fail: {e}", file=sys.stderr)
                continue
            for tx in aggregate_transactions(txs):
                kind = classify_transaction(tx["code"], tx["acquired_disposed"])
                shares, price = tx["shares"] or 0, tx["price"] or 0
                value = shares * price
                if kind == "sell" and value < MIN_SELL_VALUE:
                    continue
                sig = {
                    "date": today, "type": f"insider_{kind}", "symbol": sym,
                    "owner": owner["name"], "title": owner["title"],
                    "shares": shares, "price": price, "value": round(value),
                    "transaction_date": tx["date"], "filing_date": filing["filing_date"],
                    "tranches": tx["tranches"],
                    "level": "red" if kind == "buy" else "yellow",
                    "source": filing["href"],
                }
                new_signals.append(sig)
                _append_signal(sig, log_path)

    _save_seen(seen, seen_path)
    return new_signals


def _read_log(log_path=SIGNALS_LOG):
    out = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def detect_cluster_buys(window_days=10, log_path=SIGNALS_LOG):
    """同股票 window_days 天內 ≥2 位不同內部人買進 → 回 {symbol: sorted(owner名單)}。"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=window_days - 1)).isoformat()
    by_symbol = {}
    for row in _read_log(log_path):
        if row.get("type") == "insider_buy" and row.get("date", "") >= cutoff:
            by_symbol.setdefault(row["symbol"], set()).add(row.get("owner") or "?")
    return {sym: sorted(owners) for sym, owners in by_symbol.items() if len(owners) >= 2}


def todays_signals(days=2, log_path=SIGNALS_LOG):
    """讀 us_insider_signals.jsonl,回最近 N 天訊號 + 群聚買進合成訊號(供 patrol.py 併入夜間簡報)。"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    out = [row for row in _read_log(log_path) if row.get("date", "") >= cutoff]
    seen_syms_in_window = {row["symbol"] for row in out if row.get("type") == "insider_buy"}
    for sym, owners in detect_cluster_buys(log_path=log_path).items():
        if sym in seen_syms_in_window:
            out.append({
                "date": datetime.date.today().isoformat(), "type": "insider_cluster_buy",
                "symbol": sym, "owners": owners, "level": "red",
            })
    return out


def format_line(sig):
    sym = sig["symbol"]
    if sig["type"] == "insider_cluster_buy":
        return f"🇺🇸 {sym} 群聚買進:{len(sig['owners'])} 位內部人 10 天內同時買進({'、'.join(sig['owners'][:3])})"
    verb = "買進" if sig["type"] == "insider_buy" else "賣出"
    who = sig.get("owner") or "內部人"
    title = f"[{sig['title']}]" if sig.get("title") else ""
    value = sig.get("value") or 0
    tranches = sig.get("tranches") or 1
    tag = f"(分{tranches}筆執行)" if tranches > 1 else ""
    return (f"🇺🇸 {sym} 內部人{verb}:{who}{title} {int(sig.get('shares') or 0):,}股 "
            f"均價${sig.get('price')}{tag}(約${value:,.0f})")


if __name__ == "__main__":
    sigs = poll()
    if sigs:
        for s in sigs:
            print(format_line(s))
    else:
        print("no new signals this poll")
