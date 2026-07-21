"""台股「單一券商喊單」連接器(信息差引擎積木,2026-07-21)。

分工(治理裁決,與 tw_analyst_ratings 一條任務兩個互補源,不重疊):
  - tw_analyst_ratings = FactSet【共識】速報(cnyes tw_forecast 分類,鉅亨自動化文,格式固定)
  - 本模組 = 【單一券商】敘事標題(大摩調升川湖目標價至10000元/里昂首評…/降評…)——
    共識速報吃不到的第一手大行動作,升降評與首評往往先於共識移動。
靈感=永豐金證券法人部每日「台股重要個股評等調整」表(TP Old→New+潛在幅度,LINE 群觀察所得,
只學格式不轉載內容——該資料為投顧會員專屬權益);資料源=cnyes 免 key(分類新聞+關鍵字搜尋),
規則式抽取,零 LLM。

抽取邏輯:
  1. 標題含券商名(外資大行/本土投顧,含「外資/美系外資」泛稱)+動作詞(調升/上修/調降/首評…)
     +評等語境詞(目標價/評等/首評/覆蓋/上看),排除「外資買超」等籌碼新聞
  2. 標的優先抓標題自帶的「公司(1234)」代碼(cnyes 慣例,全市場覆蓋);沒有代碼才退回
     watchlist 公司名 substring 比對
  3. 目標價數字(目標價/上看/上調至…N元)+ Yahoo 現價算隱含幅度(fail→None,不擋訊號)
訊號分級:
  🔴 評等升降級/首評;TP 隱含幅度 ≥ +30% / ≤ -15%(單一券商喊價要夠極端才行動級)
  🟡 一般目標價上修/下修
用法:
  python3 -m intel.tw_broker_calls           # demo:掃近30小時+印彙整表
  scan(wl, hours=30) -> {code: {level, signal, source}}   # patrol.py 夜巡接口
  render_table(days=N)                       # 近N日帳本→永豐式 markdown 彙整表(自用晨掃)
  帳本:intel/tw_broker_calls_ledger.jsonl(append+dedup;事後可用 signal_ledger 思路驗報酬)
"""
import os
import re
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_CACHE = os.path.join(HERE, ".tw_broker_calls_seen.json")
LEDGER = os.path.join(HERE, "tw_broker_calls_ledger.jsonl")

UA = "Mozilla/5.0"

# 券商/機構名(標題比對用;長名在前避免「摩根士丹利」被「摩根」截胡)
BROKERS = [
    "摩根士丹利", "摩根大通", "高盛", "瑞銀", "瑞士信貸", "花旗", "美銀證券", "美銀美林", "美林",
    "野村", "麥格理", "大和", "里昂", "匯豐", "巴克萊", "德意志", "傑富瑞", "Jefferies",
    "大摩", "小摩", "UBS", "KGI", "凱基投顧", "元大投顧", "富邦投顧", "永豐投顧", "國泰證期",
    "群益投顧", "統一投顧", "兆豐投顧", "台新投顧", "康和證券", "宏遠投顧", "中信投顧",
    "美系外資", "日系外資", "亞系外資", "歐系外資", "外資",
]
_BROKER_PAT = re.compile("(" + "|".join(re.escape(b) for b in BROKERS) + ")")

_UP_WORDS = ("調升", "上修", "上調", "調高", "升評", "升至買進", "重申買進", "重申優於", "喊多")
_DOWN_WORDS = ("調降", "下修", "下調", "調低", "降評", "降至")
_INIT_WORDS = ("首評", "首予", "首次覆蓋", "納入研究", "開啟研究", "首度給予")
_ACTION_PAT = re.compile("(" + "|".join(_UP_WORDS + _DOWN_WORDS + _INIT_WORDS) + ")")
# 評等升降級(比純目標價調整更重)
_RATING_PAT = re.compile("(升評|降評|評等(?:調升|調降|上調|下調)|(?:調升|調降|上調|下調)(?:至|評等)|"
                         "首評|首予|升至(?:買進|優於|增持)|降至(?:中立|賣出|劣於|減持))")
# 目標價數字:目標價(至/為/上修至…)N元 / 上看N元 / 喊到N元
_TP_PATS = [
    re.compile(r"目標價[^0-9]{0,8}([0-9][0-9,]*(?:\.[0-9]+)?)\s*元"),
    re.compile(r"(?:上看|喊到|上調至|調升至|升至|下修至|調降至|降至)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元"),
]
# 目標價 Old→New(少數標題會寫「自X元上修至Y元」)
_TP_OLDNEW_PAT = re.compile(r"(?:自|從)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元[^0-9]{0,10}"
                            r"(?:至|到)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元")
# 標題自帶代碼:川湖(2059-TW) / 川湖(2059) / 川湖（2059）
_CODE_PAT = re.compile(r"([一-鿿A-Za-z0-9\-*]{2,10})\s*[(（](\d{4})(?:-TW)?[)）]")
_RATING_WORDS_PAT = re.compile("(買進|增持|中立|持有|減持|賣出|優於大盤|劣於大盤|逢低買進)")
_TAG_PAT = re.compile(r"<[^>]+>")
# 鉅亨速報(Factset 共識)歸 tw_analyst_ratings 管,這裡明確跳過防雙記
_FACTSET_SKIP_PAT = re.compile("鉅亨速報|Factset")


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _fetch_articles(hours=30):
    """cnyes 分類新聞(tw_stock+headline)。回 [{title, url, date}]。"""
    cutoff = _utcnow() - datetime.timedelta(hours=hours)
    out, seen = [], set()
    for cat in ("tw_stock", "headline"):
        try:
            data = json.loads(_fetch(
                f"https://news.cnyes.com/api/v3/news/category/{cat}?limit=100", timeout=15))
        except Exception:
            continue
        for item in data.get("items", {}).get("data", []):
            title = (item.get("title") or "").strip()
            if not title or title in seen:
                continue
            pub_ts = item.get("publishAt", 0)
            d = (datetime.datetime.fromtimestamp(pub_ts, datetime.timezone.utc)
                 .replace(tzinfo=None)) if pub_ts else None
            if d and d < cutoff:
                continue
            seen.add(title)
            news_id = item.get("newsId", "")
            url = f"https://news.cnyes.com/news/id/{news_id}" if news_id else "https://news.cnyes.com"
            out.append({"title": title, "url": url, "date": d or _utcnow()})
    return out


def _fetch_search(hours=30):
    """cnyes 關鍵字搜尋 API(免 key):敘事喊單新聞散在全站,分類流量抓不全,
    搜「目標價/評等」召回率高一個量級。標題帶 <mark> 高亮要剝掉。"""
    cutoff = _utcnow() - datetime.timedelta(hours=hours)
    out, seen = [], set()
    for q in ("%E7%9B%AE%E6%A8%99%E5%83%B9", "%E8%A9%95%E7%AD%89"):  # 目標價 / 評等
        try:
            data = json.loads(_fetch(
                f"https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={q}&limit=50", timeout=15))
        except Exception:
            continue
        for item in (data.get("data") or {}).get("items", []):
            title = _TAG_PAT.sub("", (item.get("title") or "")).strip()
            if not title or title in seen:
                continue
            pub_ts = item.get("publishAt") or item.get("newsPublishAt") or 0
            d = (datetime.datetime.fromtimestamp(pub_ts, datetime.timezone.utc)
                 .replace(tzinfo=None)) if pub_ts else None
            if d and d < cutoff:
                continue
            seen.add(title)
            news_id = item.get("newsId", "")
            url = f"https://news.cnyes.com/news/id/{news_id}" if news_id else "https://news.cnyes.com"
            out.append({"title": title, "url": url, "date": d or _utcnow()})
    return out


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def _yahoo_price(code):
    """現價(算 TP 隱含幅度用)。上市 .TW → 上櫃 .TWO;失敗回 None 不擋訊號。"""
    for suffix in (".TW", ".TWO"):
        try:
            data = json.loads(_fetch(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}"
                "?range=1d&interval=1d", timeout=10))
            meta = data["chart"]["result"][0]["meta"]
            p = meta.get("regularMarketPrice")
            if p:
                return float(p)
        except Exception:
            continue
    return None


def _extract(title, wl=None):
    """從單一標題抽 {code, name, broker, action, tp, tp_old, rating}。抽不出券商+動作回 None。
    純函式(不觸網),離線可測。"""
    if _FACTSET_SKIP_PAT.search(title):
        return None
    mb = _BROKER_PAT.search(title)
    ma = _ACTION_PAT.search(title)
    if not mb or not ma:
        return None
    # 動作要跟「目標價/評等/研究覆蓋」語境同現,排除「外資調升持股」等籌碼新聞
    if not re.search("目標價|評等|首評|首予|覆蓋|納入研究|上看|喊到", title):
        return None
    action_word = ma.group(1)
    direction = ("init" if action_word in _INIT_WORDS
                 else "down" if action_word in _DOWN_WORDS else "up")
    code, name = None, None
    mc = _CODE_PAT.search(title)
    if mc:
        name, code = mc.group(1), mc.group(2)
    elif wl:
        for c, n in wl.items():
            n = (n or "").strip()
            if len(n) >= 2 and n in title:
                code, name = c, n
                break
    if not code:
        return None
    tp_old, tp = None, None
    mo = _TP_OLDNEW_PAT.search(title)
    if mo:
        tp_old, tp = _num(mo.group(1)), _num(mo.group(2))
    else:
        for p in _TP_PATS:
            mt = p.search(title)
            if mt:
                tp = _num(mt.group(1))
                break
    mr = _RATING_WORDS_PAT.search(title)
    return {"code": code, "name": name, "broker": mb.group(1), "action": direction,
            "action_word": action_word, "tp": tp, "tp_old": tp_old,
            "rating": mr.group(1) if mr else None,
            "is_rating_change": bool(_RATING_PAT.search(title))}


def _load_seen():
    try:
        with open(SEEN_CACHE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_seen(seen):
    try:
        with open(SEEN_CACHE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen)[-800:], f, ensure_ascii=False)
    except Exception:
        pass


def _level(rec, potential):
    if rec["is_rating_change"] or rec["action"] == "init":
        return "red"
    if potential is not None and (potential >= 30 or potential <= -15):
        return "red"
    return "yellow"


def format_line(rec):
    """永豐法人部三欄精神:券商+動作+TP(Old→New)+隱含幅度。"""
    arrow = {"up": "↑", "down": "↓", "init": ""}[rec["action"]]
    tp_part = ""
    if rec.get("tp"):
        tp_part = (f" TP {rec['tp_old']:g}→{rec['tp']:g}" if rec.get("tp_old")
                   else f" TP {rec['tp']:g}")
    pot = rec.get("potential_pct")
    pot_part = f"(隱含{pot:+.1f}%)" if pot is not None else ""
    rating_part = f",{rec['rating']}" if rec.get("rating") else ""
    return (f"{rec.get('name') or rec['code']}({rec['code']}) 券商喊單:"
            f"{rec['broker']}{rec['action_word']}{arrow}{tp_part}{pot_part}{rating_part}")


def scan(wl=None, hours=30, fetch_price=True):
    """patrol.py 夜巡接口:回 {code: {level, signal, source}}(同碼取最嚴重再取最新)。
    同時把新抽到的記錄 append 進帳本(dedup by 標題)。wl 僅作「標題無代碼」時的退路比對。"""
    articles = _fetch_articles(hours) + _fetch_search(hours)
    seen = _load_seen()
    out, new_records = {}, []
    dedup_titles = set()
    for a in articles:
        if a["title"] in seen or a["title"] in dedup_titles:
            continue
        dedup_titles.add(a["title"])
        rec = _extract(a["title"], wl)
        if not rec:
            continue
        seen.add(a["title"])
        potential = None
        if fetch_price and rec.get("tp"):
            price = _yahoo_price(rec["code"])
            if price:
                potential = round((rec["tp"] / price - 1) * 100, 1)
        rec["potential_pct"] = potential
        rec["date"] = (a["date"].date() if isinstance(a["date"], datetime.datetime)
                       else _utcnow().date()).isoformat()
        rec["title"] = a["title"]
        rec["url"] = a["url"]
        level = _level(rec, potential)
        rec["level"] = level
        new_records.append(rec)
        line = format_line(rec)
        existing = out.get(rec["code"])
        if existing is not None:
            if existing["_rank"] >= (2 if level == "red" else 1):
                continue
        out[rec["code"]] = {"level": level, "signal": line, "source": "tw_broker_calls",
                            "_rank": 2 if level == "red" else 1}
    if new_records:
        try:
            with open(LEDGER, "a", encoding="utf-8") as f:
                for r in new_records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:
            pass
    _save_seen(seen)
    return {c: {k: v for k, v in d.items() if not k.startswith("_")} for c, d in out.items()}


def render_table(days=1):
    """近 N 日帳本 → 永豐式 markdown 彙整表(自用晨掃)。"""
    cutoff = (_utcnow().date() - datetime.timedelta(days=days)).isoformat()
    rows = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("date", "") >= cutoff:
                    rows.append(r)
    except Exception:
        pass
    if not rows:
        return "(近期無單一券商喊單記錄)"
    md = ["| 日期 | 代號 | 股票 | 券商 | 動作 | 評等 | TP | 隱含幅度 |",
          "|------|------|------|------|------|------|----|----------|"]
    for r in sorted(rows, key=lambda x: (x.get("date", ""), x.get("code", "")), reverse=True):
        tp = (f"{r['tp_old']:g}→{r['tp']:g}" if r.get("tp_old") and r.get("tp")
              else f"{r['tp']:g}" if r.get("tp") else "—")
        pot = f"{r['potential_pct']:+.1f}%" if r.get("potential_pct") is not None else "—"
        md.append(f"| {r.get('date', '—')} | {r.get('code', '—')} | {r.get('name') or '—'} | "
                  f"{r.get('broker', '—')} | {r.get('action_word', '—')} | {r.get('rating') or '—'} | "
                  f"{tp} | {pot} |")
    return "\n".join(md)


if __name__ == "__main__":
    demo_wl = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2059": "川湖"}
    sigs = scan(demo_wl)
    print(f"— 台股單一券商喊單訊號 {len(sigs)} 檔 —")
    for c, d in sigs.items():
        print(f"[{d['level']}] {d['signal']}")
    print("\n— 近1日彙整表 —")
    print(render_table(days=1))
