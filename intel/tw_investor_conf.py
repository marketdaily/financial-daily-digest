"""台股法說會時程連接器(信息差引擎積木 #7,curriculum I 節「內容型」信息源第一項)。
tw_institutional/tw_margin/tw_sbl/tw_holders 抓的是「籌碼動了沒」,這裡抓「波動事件窗口在哪」:
法說會逼近本身就是股價/選擇權隱含波動率容易被推升的時間點(CB 玩家、選擇權玩家都該提前知道),
公司主動揭露營運展望的場合,常是財測/財務數字修正的第一手來源。

資料源:公開資訊觀測站(MOPS)法人說明會日程一覽表
https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1 (POST year=民國年&month=月&TYPEK=sii/otc&co_id=空)。
免token、純 urllib 直連即可(不像 TDCC 有憑證鏈/CSRF 坑),回傳 HTML table,一次查詢回全市場當月排程,
逐筆過濾 watchlist(同 mops_watch 套路)。

⚠️坑(2026-07-03 探測記錄,省後人重踩):
1. 這個 MOPS 子網域(mopsov.twse.com.tw)urllib 直連沒有 TDCC 那種憑證鏈驗證問題,不需要 curl 子行程。
2. 查詢是「以月為單位」,不是「以公司為單位」——必須抓當月+未來 2 個月(月初排程常常還沒登記),
   TYPEK=sii(上市)與 otc(上櫃)要分開各查一次,共 6 次請求;禁止假設 co_id 查詢單一公司會比較準
   (實測 co_id 查詢是給前端「歷年」按鈕用的複雜互動,直接查全市場+本地過濾更穩定)。
3. 日期欄位可能是「範圍」格式,如 `115/07/13 至 115/07/14`(海外法說會常見),用起始日算天數;
   不可假設固定 `115/07/02` 單日格式,regex 要同時吃兩種。
4. 該月份若尚無任何公司登記會回傳 0 筆(HTTP 200 空 table),不是錯誤,不可當例外處理。
5. 民國年轉換是 `+1911`,月份用 zfill(2);跨年時 month=13 要轉成隔年 month=1(用 divmod 處理,別手刻 if)。

訊號定義(v1 啟發式門檻,同其餘籌碼類積木方法論——先建可行動訊號,精確門檻後續用 edge_audit 回測校準):
  🔴 法說會於 5 天內召開(波動事件窗口逼近,CB/選擇權部位該留意)
  🟡 法說會於 6-20 天內召開(留意但不急)
  ⚪ 中性(>20 天、已過去、或查無排程)
  附註:主旨含「財測」「重大」等關鍵字時額外標註(財測發布常是股價轉折點)。
"""
import os, re, json, datetime, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".investor_conf_cache.json")
UA = "Mozilla/5.0"
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
MONTHS_AHEAD = 2  # 抓當月 + 未來幾個月
KW_NOTE = ["財測", "重大訊息", "私募", "增資", "減資", "合併", "收購"]

ROW_RE = re.compile(r"<tr class='(?:even|odd)' data-type='body' ?>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(r"(\d{3})/(\d{2})/(\d{2})")


def _clean(cell):
    return re.sub(r"\s+", " ", TAG_RE.sub("", cell)).strip()


def _fetch_month(typek, year_roc, month):
    data = urllib.parse.urlencode({
        "encodeURIComponent": "1", "step": "1", "firstin": "1",
        "TYPEK": typek, "year": str(year_roc), "month": f"{month:02d}", "co_id": "",
    }).encode()
    req = urllib.request.Request(URL, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def _roc_date_range(s):
    """'115/07/02' 或 '115/07/13 至 115/07/14' → (start_iso, end_iso)。壞格式回 (None, None)。"""
    ms = DATE_RE.findall(s or "")
    if not ms:
        return None, None
    dates = []
    for y, m, d in ms:
        try:
            dates.append(datetime.date(int(y) + 1911, int(m), int(d)))
        except ValueError:
            continue
    if not dates:
        return None, None
    start, end = dates[0], dates[-1]
    return start.isoformat(), end.isoformat()


def _parse_rows(html):
    out = []
    for row_html in ROW_RE.findall(html):
        cells = CELL_RE.findall(row_html)
        if len(cells) < 6:
            continue
        code = _clean(cells[0])
        name = _clean(cells[1])
        date_start, date_end = _roc_date_range(_clean(cells[2]))
        if not code or not date_start:
            continue
        out.append({
            "code": code, "name": name,
            "date_start": date_start, "date_end": date_end,
            "time": _clean(cells[3]), "location": _clean(cells[4]),
            "subject": _clean(cells[5]),
        })
    return out


def _month_seq(today, n_ahead):
    y, m = today.year, today.month
    seq = []
    for i in range(n_ahead + 1):
        ym = m + i
        yy = y + (ym - 1) // 12
        mm = (ym - 1) % 12 + 1
        seq.append((yy - 1911, mm))
    return seq


def _fetch_all_rows(today):
    rows = []
    for typek in ("sii", "otc"):
        for year_roc, month in _month_seq(today, MONTHS_AHEAD):
            try:
                html = _fetch_month(typek, year_roc, month)
            except Exception:
                continue
            rows.extend(_parse_rows(html))
    return rows


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(obj):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def _all_rows(today=None):
    today = today or datetime.date.today()
    cache = _load_cache()
    if cache.get("date") == today.isoformat():
        return cache.get("rows", [])
    rows = _fetch_all_rows(today)
    _save_cache({"date": today.isoformat(), "rows": rows})
    return rows


def classify(days_until, subject=""):
    """回 {level, signal}。純數字判斷,不叫網路。"""
    note = ""
    for kw in KW_NOTE:
        if kw in (subject or ""):
            note = f",主旨含「{kw}」"
            break
    if days_until is None:
        return {"level": "plain", "signal": "查無法說會排程"}
    if days_until < 0:
        return {"level": "plain", "signal": f"法說會已於{-days_until}天前召開{note}"}
    if days_until <= 5:
        return {"level": "red", "signal": f"法說會{days_until}天內召開(波動事件窗口逼近{note})"}
    if days_until <= 20:
        return {"level": "yellow", "signal": f"法說會{days_until}天後召開{note}"}
    return {"level": "plain", "signal": f"法說會{days_until}天後召開(尚遠){note}"}


def _pick(matches, today):
    """同一公司可能多筆(跨月重疊查詢去重前)——優先選「最近的未來場」,沒有未來場則選最近的過去場。"""
    dedup = {(m["date_start"], m["subject"]): m for m in matches}.values()
    upcoming = sorted((m for m in dedup if m["date_start"] >= today.isoformat()), key=lambda m: m["date_start"])
    if upcoming:
        return upcoming[0]
    return sorted(dedup, key=lambda m: m["date_start"], reverse=True)[0]


def investor_conf(code, today=None):
    """回 dict:該公司最近一筆法說會排程+訊號分級。查無資料回 None。"""
    today = today or datetime.date.today()
    matches = [r for r in _all_rows(today) if r["code"] == str(code)]
    if not matches:
        return None
    chosen = _pick(matches, today)
    days_until = (datetime.date.fromisoformat(chosen["date_start"]) - today).days
    out = dict(chosen, days_until=days_until)
    out.update(classify(days_until, chosen["subject"]))
    return out


def scan(codes):
    """批次掃描,回 {code: investor_conf_dict}。單次共用月份抓取,不逐檔打網路。"""
    today = datetime.date.today()
    rows = _all_rows(today)
    by_code = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r)
    out = {}
    for c in codes:
        matches = by_code.get(str(c))
        if not matches:
            continue
        chosen = _pick(matches, today)
        days_until = (datetime.date.fromisoformat(chosen["date_start"]) - today).days
        entry = dict(chosen, days_until=days_until)
        entry.update(classify(days_until, chosen["subject"]))
        out[c] = entry
    return out


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(json.dumps(investor_conf(code), ensure_ascii=False, indent=1))
