"""主動式 ETF 持股監控:每日抓全部 00xxA 主動式 ETF 的全持股(MoneyDJ,資料日 T-1),
存快照到 .etf_holdings/,與前一份快照 diff → 新進/剔除/加碼/減碼事件(events.jsonl)。
CB 分析端用 stock_summary(code) 查「哪些主動式 ETF 持有這檔 + 近期異動」——讀本地帳本零網路。

  python3 cb_etf_watch.py --update        抓今天全部主動式 ETF → diff → 印新事件(cron 用)
  python3 cb_etf_watch.py 8112            查單一股票的主動式 ETF 持有/異動
ETF 清單動態拉 FinMind TaiwanStockInfo(^00\\d+A$),新發行自動納入,不寫死。
異動門檻:權重 ±0.5pt 或股數 ±20% 才算加碼/減碼(小額調整不洗版)。"""
import os
import re
import ssl
import sys
import json
import time
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_DIR = os.path.join(HERE, ".etf_holdings")
EVENTS_PATH = os.path.join(LEDGER_DIR, "events.jsonl")
SNAP_PATH = os.path.join(LEDGER_DIR, "latest.json")
ETF_LIST_PATH = os.path.join(LEDGER_DIR, "etf_list.json")

FINMIND = "https://api.finmindtrade.com/api/v4/data"
MDJ = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={etf}.TW"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

W_THRESH = 0.5     # 權重變化 ≥0.5pt 算加碼/減碼
S_THRESH = 0.20    # 或股數變化 ≥20%


# MoneyDJ 憑證缺 Subject Key Identifier,Python 3.13+ 預設嚴格驗證會拒;
# 只放寬 strict 旗標,憑證鏈與主機名驗證照常(不是關閉驗證)。
_CTX = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    _CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", errors="ignore")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(LEDGER_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def active_etf_list(max_age_days=7):
    """全部主動式 ETF {code: name}。快取 7 天;FinMind 掛掉用舊快取(誠實標示)。"""
    cached = _load(ETF_LIST_PATH, None)
    today = datetime.date.today().isoformat()
    if cached and (datetime.date.fromisoformat(today)
                   - datetime.date.fromisoformat(cached["date"])).days < max_age_days:
        return cached["etfs"]
    try:
        j = json.loads(_get(f"{FINMIND}?dataset=TaiwanStockInfo"))
        etfs = {}
        for x in j.get("data", []):
            sid = x.get("stock_id", "")
            if re.match(r"^00\d{2,3}A$", sid):
                etfs[sid] = x.get("stock_name", sid)
        if etfs:
            _save(ETF_LIST_PATH, {"date": today, "etfs": etfs})
            return etfs
    except Exception:
        pass
    return cached["etfs"] if cached else {}


ROW_RE = re.compile(
    r">([^<>]+?)\((\d{4,6})\.(?:TW|TWO)\)</a></td>"
    r"<td[^>]*>([\d.]+)</td>"
    r"<td[^>]*>([\d,]+)</td>", re.S)
DATE_RE = re.compile(r"資料日期[:：]\s*(\d{4})/(\d{2})/(\d{2})")


def fetch_holdings(etf_code):
    """單一 ETF 全持股。回 {date, holdings:{code:{name,weight,shares}}} 或 None。
    只留台股(4碼)持股;海外/債券持倉自然被排除。"""
    try:
        h = _get(MDJ.format(etf=etf_code))
    except Exception:
        return None
    h = re.sub(r"\s+", "", h)
    md = DATE_RE.search(h)
    if not md:
        return None
    holdings = {}
    for name, code, w, shares in ROW_RE.findall(h):
        if len(code) != 4:
            continue
        try:
            holdings[code] = {"name": name.strip(), "weight": float(w),
                              "shares": float(shares.replace(",", ""))}
        except ValueError:
            continue
    # 資料日期有解析到但無台股持股 = 海外型主動式 ETF,回有效空快照(不算失敗)
    return {"date": f"{md.group(1)}-{md.group(2)}-{md.group(3)}", "holdings": holdings}


def _diff(etf, etf_name, old, new):
    """兩份同一 ETF 快照 → 事件 list。old/new = {date, holdings}。"""
    ev = []
    oh, nh = old["holdings"], new["holdings"]
    for code, cur in nh.items():
        prev = oh.get(code)
        if not prev:
            ev.append({"stock": code, "stock_name": cur["name"], "kind": "新進",
                       "note": f"新增持股 {cur['weight']:.2f}%"})
        else:
            dw = cur["weight"] - prev["weight"]
            ds = (cur["shares"] - prev["shares"]) / prev["shares"] if prev["shares"] else 0
            if dw >= W_THRESH or ds >= S_THRESH:
                ev.append({"stock": code, "stock_name": cur["name"], "kind": "加碼",
                           "note": f"權重 {prev['weight']:.2f}%→{cur['weight']:.2f}%"
                                   f"(股數 {ds*100:+.0f}%)"})
            elif dw <= -W_THRESH or ds <= -S_THRESH:
                ev.append({"stock": code, "stock_name": cur["name"], "kind": "減碼",
                           "note": f"權重 {prev['weight']:.2f}%→{cur['weight']:.2f}%"
                                   f"(股數 {ds*100:+.0f}%)"})
    for code, prev in oh.items():
        if code not in nh:
            ev.append({"stock": code, "stock_name": prev["name"], "kind": "剔除",
                       "note": f"出清(原權重 {prev['weight']:.2f}%)"})
    for e in ev:
        e.update({"etf": etf, "etf_name": etf_name, "date": new["date"],
                  "prev_date": old["date"]})
    return ev


def update(verbose=True):
    """抓全部主動式 ETF → 與 latest.json diff → 事件落 events.jsonl → 覆寫 latest。
    回 (成功數, 失敗list, 新事件list)。同資料日重跑=冪等,不重複記事件。"""
    etfs = active_etf_list()
    if not etfs:
        print("✗ 拿不到主動式 ETF 清單(FinMind 掛且無快取)")
        return 0, list(etfs), []
    latest = _load(SNAP_PATH, {})
    ok, fails, new_events = 0, [], []
    for code, name in sorted(etfs.items()):
        snap = fetch_holdings(code)
        time.sleep(0.4)
        if not snap:
            fails.append(code)
            continue
        prev = latest.get(code)
        # 防呆:原本有持股突然全空 = 疑似來源異常,保留舊快照、不產生「全部剔除」假事件
        if prev and len(prev["holdings"]) >= 5 and not snap["holdings"]:
            fails.append(code + "(空表疑異常)")
            continue
        ok += 1
        if prev and prev["date"] < snap["date"]:
            new_events += _diff(code, name, prev, snap)
        if not prev or prev["date"] <= snap["date"]:
            latest[code] = snap
    _save(SNAP_PATH, latest)
    if new_events:
        os.makedirs(LEDGER_DIR, exist_ok=True)
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            for e in new_events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if verbose:
        print(f"主動式 ETF 更新:{ok}/{len(etfs)} 檔成功"
              + (f",失敗 {','.join(fails)}" if fails else "")
              + f";新事件 {len(new_events)} 筆")
        for e in new_events:
            print(f"  ⚡ {e['etf_name']}({e['etf']}) {e['kind']} "
                  f"{e['stock_name']}({e['stock']}) {e['note']}")
    return ok, fails, new_events


def stock_summary(stock_code, event_days=30):
    """單一股票視角:哪些主動式 ETF 現在持有 + 近 N 日異動事件。讀本地帳本,零網路。"""
    stock_code = str(stock_code).strip()
    latest = _load(SNAP_PATH, {})
    etfs = _load(ETF_LIST_PATH, {}).get("etfs", {})
    holders, data_date = [], None
    for etf, snap in latest.items():
        h = snap["holdings"].get(stock_code)
        data_date = max(data_date or snap["date"], snap["date"])
        if h:
            holders.append({"etf": etf, "etf_name": etfs.get(etf, etf),
                            "weight": h["weight"], "shares": h["shares"]})
    holders.sort(key=lambda x: -x["weight"])
    cutoff = (datetime.date.today() - datetime.timedelta(days=event_days)).isoformat()
    events = []
    try:
        with open(EVENTS_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("stock") == stock_code and e.get("date", "") >= cutoff:
                    events.append(e)
    except OSError:
        pass
    events.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"holders": holders, "events": events, "data_date": data_date}


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--update":
        ok, fails, ev = update()
        sys.exit(0 if ok else 1)
    info = stock_summary(args[0])
    if not info["holders"] and not info["events"]:
        print(f"{args[0]}:目前無主動式 ETF 持有、近30日無異動(帳本資料日 {info.get('data_date') or '尚未建立,先跑 --update'})")
        return
    print(f"{args[0]} 主動式 ETF 持有狀況(資料日 {info['data_date']}):")
    for h in info["holders"]:
        print(f"  {h['etf_name']}({h['etf']}) 權重 {h['weight']:.2f}% "
              f"{h['shares']:,.0f} 股")
    for e in info["events"]:
        print(f"  ⚡ {e['date']} {e['etf_name']}({e['etf']}) {e['kind']} {e['note']}")


if __name__ == "__main__":
    main()
