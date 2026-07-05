"""美股重大訊息(Form 8-K)連接器(信息差引擎美股信息源第四件)。
us_insider.py docstring/curriculum.md B 節點名「10-Q/8-K 尚未做,留待下輪評估」——8-K 是台股
「重大訊息」(mops_watch.py)的美股對應版。SEC atom feed 本身就內建 `<items-desc>` 欄位
(如 "items 2.02 and 9.01"),不需要像 Form 4 一樣額外下載解析 XML 主文件,比 us_insider.py
更輕量(已用真實 curl 對 Apple CIK 驗證過該欄位存在)。
資料鏈:ticker→CIK(復用 us_insider._load_cik_map/build_watchlist)→8-K filing atom feed
(items-desc 直接可讀)→依 item 編號分級。
訊號定義(過濾雜訊——每股每季固定會發 Item 2.02+9.01 財報 8-K,若照單全收就是資料堆不是訊號):
  🔴 稀有且高風險:1.03 破產/接管、2.04 觸發事件加速/增加直接財務義務(covenant 違約前兆)、
     3.01 下市通知/未達上市標準、4.01 簽證會計師異動、4.02 重編財報/既往財報不可信賴、
     5.01 控制權變動
  🟡 中等關注:1.01 重大合約、2.01 完成收購/處分資產、2.03 產生直接財務義務(如新增借款)、
     2.05/2.06 退出成本/資產減損、5.02 董事/高層人事異動(**方向不明,誠實標註**——同一
     item 編號同時涵蓋離職與新任,無法只靠 item 編號判斷方向,不硬猜)
  忽略(雜訊,每季/每次財報都固定出現,照單全收=資料堆):2.02 財報結果、5.07 股東會表決結果、
     7.01 Reg FD 揭露、8.01 其他事件(過於廣泛需讀內文才有意義)、9.01 附件清單(從不單獨成訊號)
一份 8-K 常同時掛多個 item(如同一份揭露會計師異動的filing常同時掛 4.01+4.02)——`poll()`
**每份 filing 合併成一則訊號**(取最高 severity+items 標籤合併),不是每個 item 各發一則,
避免同一份 filing 被拆成多筆訊號後,patrol.py/main.py 的 by-source 去重機制(見
`_inject_intel_signals::best_by_source`)只留下其中一筆造成另一筆真實的紅燈遺失
(仿 us_insider.py::aggregate_transactions() 同款「合併同一事件的多筆記錄」精神)。
用法:
  輪詢一次(累積記帳,回傳本次新訊號): python3 -m intel.us_8k_events poll
  今日/近N日訊號(供 patrol.py 併入夜間簡報): intel.us_8k_events.todays_signals(days=2)
"""
import os
import sys
import re
import json
import time
import datetime
import urllib.request
import xml.etree.ElementTree as ET

from intel import us_insider as _ui

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_CACHE = os.path.join(HERE, ".us_8k_seen.json")
SIGNALS_LOG = os.path.join(HERE, "us_8k_signals.jsonl")

SEC = "https://www.sec.gov"
UA = "MarketDaily research contact@marketdaily.ai"
REQ_DELAY = 0.35
# 8-K 比 Form 4 少見(每季+偶發事件),不需要看太多筆。實測 SEC browse-edgar atom feed
# 的 count 參數對此表格是下限非上限(count=4 實測仍回 10 筆)——無害,seen cache 照樣
# 正確去重,只是初次/每次輪詢會多檢查幾筆舊 filing,故意不強行截斷。
FILINGS_PER_SYMBOL = 4

# item 編號 → (level, 中文說明);未列在此表的 item(2.02/5.07/7.01/8.01/9.01 等)視為雜訊跳過。
ITEM_MEANING = {
    "1.01": ("yellow", "重大合約"),
    "1.02": ("yellow", "終止重大合約"),
    "1.03": ("red", "聲請破產/接管"),
    "2.01": ("yellow", "完成收購或處分資產"),
    "2.03": ("yellow", "產生直接財務義務"),
    "2.04": ("red", "觸發事件加速/增加直接財務義務(covenant違約前兆)"),
    "2.05": ("yellow", "退出/處分活動成本"),
    "2.06": ("yellow", "資產減損"),
    "3.01": ("red", "下市通知/未達上市標準"),
    "4.01": ("red", "簽證會計師異動"),
    "4.02": ("red", "重編財報/既往財報不可信賴"),
    "5.01": ("red", "控制權變動"),
    "5.02": ("yellow", "董事/高層人事異動(方向待個案判斷)"),
}

_ITEM_RE = re.compile(r"\b(\d\.\d{2})\b")


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    finally:
        time.sleep(REQ_DELAY)
    return data


def parse_items_desc(items_desc):
    """"items 2.02 and 9.01" / "item 4.01" → ["2.02","9.01"]。純函式,離線可測。"""
    if not items_desc:
        return []
    return _ITEM_RE.findall(items_desc)


def classify_items(item_codes):
    """回傳這份 filing 裡命中的 [(item, level, label), ...],依 ITEM_MEANING 過濾雜訊。
    一份 8-K 常同時掛多個 item(如 2.02+9.01),分別判斷各自要不要成訊號,不是全有全無。"""
    out = []
    for code in item_codes:
        meta = ITEM_MEANING.get(code)
        if meta:
            out.append((code, meta[0], meta[1]))
    return out


def recent_8k_filings(cik, count=FILINGS_PER_SYMBOL):
    """回該 CIK 最近幾筆 8-K filing:[{accession, filing_date, href, items}]。"""
    cik10 = str(cik).zfill(10)
    url = (f"{SEC}/cgi-bin/browse-edgar?action=getcompany&CIK={cik10}"
           f"&type=8-K&dateb=&owner=include&count={count}&output=atom")
    raw = _fetch(url)
    root = ET.fromstring(raw)
    out = []
    for entry in root:
        if _ui._strip_ns(entry.tag) != "entry":
            continue
        content = _ui._local(entry, "content")
        if content is None:
            continue
        acc = _ui._local(content, "accession-number")
        fdate = _ui._local(content, "filing-date")
        href = _ui._local(content, "filing-href")
        items_el = _ui._local(content, "items-desc")
        if acc is None or fdate is None:
            continue
        out.append({
            "accession": acc.text.strip(),
            "filing_date": fdate.text.strip(),
            "href": href.text.strip() if href is not None else "",
            "items": parse_items_desc(items_el.text if items_el is not None else ""),
        })
    return out


def _load_seen(path=SEEN_CACHE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_seen(seen, path=SEEN_CACHE):
    """故意不做以時間為準的 prune:`recent_8k_filings()` 回傳的是「最近 N 筆」而非固定
    行事曆窗口,對低頻申報公司,較舊的 accession 可能在超過任何 prune 期限後仍留在「最近
    N 筆」結果裡——若那時被 prune 掉,下次輪詢會誤判成「沒見過」而重複觸發同一則舊訊號當
    新訊號(us_insider.py 的 30 天版本有同款理論缺陷,不在本次範圍內修,見 backlog)。
    accession 字串量體極小(全 watchlist 數十年份頂多數千筆),永久保留無實際成本。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def _append_signal(sig, path=SIGNALS_LOG):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig, ensure_ascii=False) + "\n")


def _combine_filing_signal(sym, filing, classified, today):
    """一份 filing 的多個 classified item 合併成一則訊號:取最高 severity(red 蓋過 yellow),
    items/labels 各自保留清單供程式化存取,item_label 組合成一句話供顯示。純函式,離線可測。"""
    level = "red" if any(c[1] == "red" for c in classified) else "yellow"
    items = [c[0] for c in classified]
    label = "、".join(f"Item {c[0]}:{c[2]}" for c in classified)
    return {
        "date": today, "type": "form_8k", "symbol": sym,
        "items": items, "item_label": label, "level": level,
        "filing_date": filing["filing_date"], "source": filing["href"],
    }


def poll(seen_path=SEEN_CACHE, log_path=SIGNALS_LOG):
    """打每檔 watchlist 最近 8-K filing,新的才依 item 分類。回傳本次新增訊號 list——
    每份 filing 最多產生一則訊號(合併該 filing 內所有 classified item),不是每個 item 各發一則。"""
    wl = _ui.build_watchlist()
    cik_map = _ui._load_cik_map()
    seen = _load_seen(seen_path)
    today = datetime.date.today().isoformat()
    new_signals = []

    for sym in sorted(wl):
        cik = _ui.symbol_to_cik(sym, cik_map)
        if not cik:
            continue
        try:
            filings = recent_8k_filings(cik)
        except Exception as e:
            print(f"{sym} 8-k feed fail: {e}", file=sys.stderr)
            continue
        for filing in filings:
            key = f"{sym}:{filing['accession']}"
            if key in seen:
                continue
            seen[key] = today
            classified = classify_items(filing["items"])
            if not classified:
                continue
            sig = _combine_filing_signal(sym, filing, classified, today)
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


def todays_signals(days=2, log_path=SIGNALS_LOG):
    """讀 us_8k_signals.jsonl,回最近 N 天訊號(供 patrol.py 併入夜間簡報)。"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    return [row for row in _read_log(log_path) if row.get("date", "") >= cutoff]


def format_line(sig):
    return f"🇺🇸 {sig['symbol']} 8-K {sig['item_label']}(申報日{sig['filing_date']})"


if __name__ == "__main__":
    sigs = poll()
    if sigs:
        for s in sigs:
            print(format_line(s))
    else:
        print("no new signals this poll")
