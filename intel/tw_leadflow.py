"""先行異動雷達(信息差引擎:抓「量價走在新聞前面」的全市場掃描)。
起源:環球晶(6488)2026-07-01/02 無消息連續漲停、7/6 天量,7/9 晚間才公告美光 10 年長約
+5 億美元策略資金,日報 7/11 才推——先行資金領先公告 8 天;回頭看 7/1-7/3 三根漲停時
投信還在賣、外資僅小買,法人籌碼類 connector 抓不到,且既有 connector 全掛在 watchlist 上,
沒有一支看全市場量價。這支補這個洞:
  每晚全市場(上市+上櫃)掃「近漲停」→ 對照重訊(mops)→ 無消息者查歷史量價:
  🔴 無消息 且(5 日內第 2 根以上近漲停 或 量能≥3×20 日中位)→ 疑先行資金,行動級
  🔴 無消息 且 5 日累計漲幅≥25% → 同上
  🟡 無消息單根近漲停(量能≥1.5× 或 一價鎖死無量)→ 觀察
  有重訊的近漲停=正常新聞反應,不發訊號(那正是我們慢人一步的舊世界)。
方向警語:先行異動≠必漲,可能是誘多/出貨前拉抬;訊號只餵觀察與 reason 素材,
絕不直接給買賣建議,事後報酬交 signal_ledger 對答案。
資料源全免費免金鑰:TWSE/TPEx openapi 當日全市場收盤、Yahoo chart 個股歷史(僅無消息候選股,
帶磁碟快取)、mops 重訊(重用 mops_watch)、FinMind 法人(紅燈加註「法人未同步」,失敗不擋)。
CLI:python3 -m intel.tw_leadflow            # 正式掃描,寫 leadflow_latest.json
    python3 -m intel.tw_leadflow --probe 6488  # 用歷史資料回放某檔會在哪些日觸發(不含重訊過濾)
"""
import os
import json
import time
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LATEST = os.path.join(HERE, "leadflow_latest.json")
NEWS_SEEN = os.path.join(HERE, "leadflow_news_seen.json")

TWSE_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_ALL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"

NEAR_LIMIT_PCT = 8.5    # 台股漲停 10%,收在 +8.5% 以上視為「近漲停」(含尾盤打開)
VOL_SPIKE = 3.0         # 量能 ≥3×20 日中位 → 紅
VOL_MILD = 1.5          # 量能 ≥1.5× → 單根也給黃
RET5_RED = 25.0         # 5 日累計 ≥25% 無消息 → 紅
MAX_CANDIDATES = 40     # 瘋狂日封頂,超出部分記在 dropped 不裝沒看到


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _num(v):
    """TWSE Change 欄除權息日會變文字(reference_tw_exdividend_change_gotcha),壞值回 None。"""
    try:
        x = float(str(v).replace(",", "").replace("+", ""))
        return x
    except Exception:
        return None


def _is_common_stock(code):
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def snapshot():
    """當日全市場收盤 → list[{code,name,market,close,change_pct,volume}](僅 4 碼正股)。"""
    rows = []
    try:
        for x in _get(TWSE_ALL):
            code = str(x.get("Code", "")).strip()
            if not _is_common_stock(code):
                continue
            close, chg = _num(x.get("ClosingPrice")), _num(x.get("Change"))
            vol = _num(x.get("TradeVolume"))
            if close and chg is not None and close - chg > 0:
                rows.append({"code": code, "name": x.get("Name", ""), "market": "twse",
                             "close": close, "change_pct": round(chg / (close - chg) * 100, 2),
                             "volume": int(vol or 0)})
    except Exception as e:
        print(f"leadflow: TWSE snapshot 失敗 {e}")
    try:
        for x in _get(TPEX_ALL):
            code = str(x.get("SecuritiesCompanyCode", "")).strip()
            if not _is_common_stock(code):
                continue
            close, chg = _num(x.get("Close")), _num(x.get("Change"))
            vol = _num(x.get("TradingShares"))
            if close and chg is not None and close - chg > 0:
                rows.append({"code": code, "name": x.get("CompanyName", ""), "market": "tpex",
                             "close": close, "change_pct": round(chg / (close - chg) * 100, 2),
                             "volume": int(vol or 0)})
    except Exception as e:
        print(f"leadflow: TPEx snapshot 失敗 {e}")
    return rows


def _yahoo_history(code, market):
    """(dates, closes, volumes) 近 3 個月,失敗回 None。僅對候選股呼叫,量小不快取。"""
    sym = f"{code}.TW" if market == "twse" else f"{code}.TWO"
    try:
        d = _get(YAHOO.format(sym=sym))["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        dates, closes, vols = [], [], []
        for t, c, v in zip(d["timestamp"], q["close"], q["volume"]):
            if c is None:
                continue
            dates.append(datetime.date.fromtimestamp(t))
            closes.append(c)
            vols.append(v or 0)
        return dates, closes, vols
    except Exception:
        return None


def _classify_from_series(closes, vols, i):
    """對序列第 i 天(i>=21)套規則,回 (level, 描述欄位 dict) 或 (None, None)。
    純函式,scan 與 probe 共用同一套判定,回測=實盤同邏輯。"""
    chg = (closes[i] / closes[i - 1] - 1) * 100
    if chg < NEAR_LIMIT_PCT:
        return None, None
    prior_vols = sorted(v for v in vols[max(0, i - 20):i] if v > 0)
    med = prior_vols[len(prior_vols) // 2] if prior_vols else 0
    vol_ratio = round(vols[i] / med, 1) if med else 0.0
    locked = vols[i] < med * 0.3 if med else False  # 一價鎖死:量縮到 3 成以下的漲停
    streak = sum(1 for j in range(max(1, i - 4), i + 1)
                 if (closes[j] / closes[j - 1] - 1) * 100 >= NEAR_LIMIT_PCT)
    ret5 = (closes[i] / closes[i - 5] - 1) * 100 if i >= 5 else 0.0
    fields = {"chg": round(chg, 1), "vol_ratio": vol_ratio, "streak": streak,
              "ret5": round(ret5, 1), "locked": locked}
    if streak >= 2 or vol_ratio >= VOL_SPIKE or ret5 >= RET5_RED:
        return "red", fields
    if vol_ratio >= VOL_MILD or locked:
        return "yellow", fields
    return None, None


def _inst_note(code):
    """近 3 日外資+投信合計買賣超(張)。量價異常但法人沒大買=隱形買盤,更可疑。失敗回空。"""
    try:
        from intel import tw_institutional
        start = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        rows = tw_institutional._fetch("TaiwanStockInstitutionalInvestorsBuySell", code, start)
        by_date = {}
        for r in rows:
            if r.get("name") in ("Foreign_Investor", "Investment_Trust"):
                by_date[r["date"]] = by_date.get(r["date"], 0) + (r["buy"] - r["sell"]) // 1000
        last3 = [by_date[d] for d in sorted(by_date)[-3:]]
        net = sum(last3)
        if net < 500:
            return f"|外資+投信近3日僅{net:+d}張,法人未同步=隱形買盤"
        return f"|外資+投信近3日{net:+d}張"
    except Exception:
        return ""


def _news_seen_recent(days=4):
    """mops openapi 只穩定涵蓋當日重訊 → 每晚把全市場當日重訊代碼記進滾動記憶檔,
    排除窗=近 N 日內發過重訊者(新聞後的動能漲停不是「先行」)。失敗回既有記憶,寧多勿漏。"""
    try:
        with open(NEWS_SEEN, encoding="utf-8") as f:
            mem = json.load(f)
    except Exception:
        mem = {}
    today = datetime.date.today()
    try:
        from intel.mops_watch import _iter_news_rows
        for code, _name, d, _subj in _iter_news_rows(days=2):
            if _is_common_stock(code):
                mem.setdefault(d.isoformat(), [])
                if code not in mem[d.isoformat()]:
                    mem[d.isoformat()].append(code)
    except Exception as e:
        print(f"leadflow: mops 重訊記憶更新失敗,沿用既有記憶 {e}")
    mem = {d: v for d, v in mem.items()
           if (today - datetime.date.fromisoformat(d)).days <= 7}
    with open(NEWS_SEEN, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False)
    return {c for d, v in mem.items()
            if (today - datetime.date.fromisoformat(d)).days <= days for c in v}


def scan():
    """全市場先行異動掃描 → {code: {level, signal, source, ...}},並寫 leadflow_latest.json。"""
    today = datetime.date.today().isoformat()
    rows = snapshot()
    cands = sorted((r for r in rows if r["change_pct"] >= NEAR_LIMIT_PCT),
                   key=lambda r: -r["change_pct"])
    dropped = max(0, len(cands) - MAX_CANDIDATES)
    cands = cands[:MAX_CANDIDATES]

    newsed = _news_seen_recent(days=4)

    out = {}
    for r in cands:
        if r["code"] in newsed:
            continue  # 有重訊的漲停=新聞反應,不是先行
        hist = _yahoo_history(r["code"], r["market"])
        time.sleep(0.3)
        if not hist or len(hist[1]) < 22:
            continue
        dates, closes, vols = hist
        i = len(closes) - 1
        if dates[i].isoformat() != today:  # Yahoo 尚未含今日 → 用快照補一天
            dates.append(datetime.date.today())
            closes.append(r["close"])
            vols.append(r["volume"])
            i += 1
        level, f = _classify_from_series(closes, vols, i)
        if not level:
            continue
        tag = ("連%d根" % f["streak"] if f["streak"] >= 2 else
               "一價鎖死" if f["locked"] else f"量能{f['vol_ratio']}×")
        sig = (f"{r['name']}({r['code']}) 無消息近漲停{f['chg']:+.1f}%({tag}"
               f",5日{f['ret5']:+.1f}%),疑資訊先行資金")
        if level == "red":
            sig += _inst_note(r["code"])
        out[r["code"]] = {"level": level, "signal": sig, "source": "leadflow",
                          "name": r["name"], "price": r["close"], **f}

    latest = {"date": today, "n_market": len(rows), "n_candidates": len(cands),
              "dropped_over_cap": dropped, "by_code": out}
    with open(LATEST, "w", encoding="utf-8") as fp:
        json.dump(latest, fp, ensure_ascii=False, indent=1)
    print(f"leadflow: 全市場 {len(rows)} 檔|近漲停 {len(cands)} 檔(超掃描上限被略過 {dropped})"
          f"|有重訊排除 {len(newsed & {c['code'] for c in cands})}|訊號 {len(out)} 檔")
    return out


def probe(code, market=None):
    """歷史回放:這檔股票近 3 個月哪些日子會觸發(不含重訊過濾,人工對照新聞日期用)。"""
    market = market or ("tpex" if _yahoo_history(code, "tpex") else "twse")
    hist = _yahoo_history(code, market)
    if not hist:
        print(f"probe: 抓不到 {code} 歷史")
        return
    dates, closes, vols = hist
    for i in range(21, len(closes)):
        level, f = _classify_from_series(closes, vols, i)
        if level:
            print(f"{dates[i]} {'🔴' if level == 'red' else '🟡'} "
                  f"{f['chg']:+.1f}% 量{f['vol_ratio']}× 連{f['streak']}根 5日{f['ret5']:+.1f}%"
                  f"{' 一價鎖死' if f['locked'] else ''}")


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        probe(sys.argv[sys.argv.index("--probe") + 1])
    else:
        scan()
