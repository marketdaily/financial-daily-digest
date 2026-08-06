"""信息差巡邏中樞:每晚把 watchlist 掃一遍(法人動向+重訊+月營收+新聞事件),產出訊號簡報。
watchlist = cb_database 全部標的 ∪ cb_analyzer/holdings.json ∪ intel/watchlist.json extras。
同場加映:①觸發 CB 每日預測快照(餵 predictions.jsonl,就算沒人開網頁帳本也天天長)
②跑 cb_score 記分 → 校準表。輸出 intel/briefs/<日期>.md + latest.json(機器可讀,日報之後接這裡)。
news_signals(2026-07-04 curriculum I 節收尾)補上「新聞+社群訊號整合」——免費新聞源(NEWS_API+
cnyes)規則式分級比對 watchlist,political/macro 廣域主題另闢區塊(社群/X 訊號詳見該模組 docstring
說明為何免費路徑下不需要 XAI key 也能覆蓋大半市場衝擊)。
用法:cd Delvin-agent && python3 -m intel.patrol
"""
import os
import sys
import json
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CBDIR = os.path.join(ROOT, "cb_analyzer")
BRIEFS = os.path.join(HERE, "briefs")

from intel import tw_institutional, mops_watch, us_analyst, us_insider, us_8k_events, tw_margin, tw_sbl, tw_holders, tw_investor_conf, tw_investor_materials, tw_surveillance, tw_fsc, us_sec_regulatory, news_signals, signal_ledger, us_13f_ledger, tw_financials, tw_leadflow, tw_analyst_ratings, tw_broker_calls, tw_rank_scanner, us_congress_trades, gold_macro, exa_search
# confluence 刻意【不】在此 import——改在 confluence_section 內 lazy import,
# 讓 confluence.py 萬一 import-time 壞掉也只降級成 fallback 段,不會整個 patrol 崩掉害 latest.json 沒產出餓死日報(驗證者 LOW-1)。

MAX_MATERIALS_PER_RUN = 5  # 法說會簡報下載+Ollama摘要較耗時,單次巡邏封頂避免跑太久


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


_CJK_DIGITS = "零一二三四五六七八九"
_ISSUE_CHARS = set("一二三四五六七八九十")
_TAIL_MARKERS = ("-KY", "KY", "創")  # 期別號【之後】的板別/KY 尾標,先剝出待會補回


def _cjk_numeral(n):
    """阿拉伯數字→中文數字(1-99;CB 期別實務不會更大)。無法表示回空字串。"""
    if n <= 0 or n >= 100:
        return ""
    if n < 10:
        return _CJK_DIGITS[n]
    if n < 20:
        return "十" + (_CJK_DIGITS[n % 10] if n % 10 else "")
    return _CJK_DIGITS[n // 10] + "十" + (_CJK_DIGITS[n % 10] if n % 10 else "")


def _stock_display_name(it):
    """CB 資料庫的 `name` 是【可轉債名】(創見二/宏致四/聚賢研發一創=公司+期別[+板別]),
    但 stock-level 訊號要顯示【股票名】。優先用 bond_code 減 stock_code 得精確期別號,只剝除
    (KY/創 尾標前的)與該期別吻合的中文數字;bond_code 缺損【或與名期別不符】時退回剝單一結尾
    期別字(本 db 每個 name 恆為債名=公司+期別,此保底安全)。尾字非期別 numeral→原樣返回
    (fail-safe,不 over-strip,如「台積電」numeral="二" 但尾"電"不動)。"""
    name = str(it.get("name") or "").strip()
    if not name:
        return name
    stock = str(it.get("stock_code") or "")
    bond = str(it.get("bond_code") or "")
    tail = ""
    for mk in _TAIL_MARKERS:
        if name.endswith(mk):
            name, tail = name[:-len(mk)], (mk if mk.startswith("-") else "-" + mk)
            break
    issue = bond[len(stock):] if stock and bond.startswith(stock) else ""
    numeral = _cjk_numeral(int(issue)) if issue.isdigit() and issue else ""
    if numeral and len(name) > len(numeral) and name.endswith(numeral):
        name = name[:-len(numeral)]
    elif len(name) > 1 and name[-1] in _ISSUE_CHARS:
        # 保底剝單一結尾期別字:①bond_code 缺損(issue=="")②bond_code 與名期別不符
        # (如 邑昇二 stock=5291/bond=52911→numeral="一" 但名尾為"二",精確路徑落空)。
        # 本 db 每個 name 恆為債名=公司+期別,尾字為期別 numeral 即可安全剝除。
        name = name[:-1]
    return name + tail


def build_watchlist():
    """回 {stock_code: 顯示名}。"""
    wl = {}
    db = _load_json(os.path.join(CBDIR, "cb_database.json"), {})
    for it in db.get("items", []):
        if it.get("stock_code"):
            wl.setdefault(str(it["stock_code"]), _stock_display_name(it))
    holdings = _load_json(os.path.join(CBDIR, "holdings.json"), [])
    items = holdings.get("items", []) if isinstance(holdings, dict) else holdings
    for h in items if isinstance(items, list) else []:
        c = str(h.get("stock_code") or h.get("code") or "")
        c = c[:4] if len(c) >= 5 else c
        if c:
            wl.setdefault(c, h.get("name", ""))
    extra = _load_json(os.path.join(HERE, "watchlist.json"), {})
    for x in extra.get("extra", []):
        wl.setdefault(str(x.get("code")), x.get("name", ""))
    # tcri_overrides = 老闆實際在做/問過的標的,一律列入盯梢
    for c in _load_json(os.path.join(CBDIR, "tcri_overrides.json"), {}):
        if str(c).isdigit():
            wl.setdefault(str(c), "")
    return wl


def _cb_snapshot():
    """每日預測快照:所有「有定價」的 CB(含模型判不要碰的——拒絕判定也要被記分對答案)
    + tcri_overrides 裡老闆在做的現存 CB,全部跑一次分析,經 _outlook 寫進預測帳本。"""
    code = (
        "import sys, json, os; sys.path.insert(0, %r); import cb_server\n"
        "codes = sorted({it['bond_code'] for it in cb_server.DB['items']\n"
        "                if it.get('conv_price') and it.get('premium_mid')})\n"
        "try:\n"
        "    ov = json.load(open(os.path.join(%r, 'tcri_overrides.json')))\n"
        "    codes += sorted(c for c in ov if str(c).isdigit())\n"
        "except Exception: pass\n"
        "for c in codes:\n"
        "    try: cb_server.analyze_fragment(c)\n"
        "    except Exception as e: print('skip', c, e)\n"
        "print('snapshot ok', len(codes))" % (CBDIR, CBDIR))
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=900, cwd=CBDIR)


def _cb_score():
    return subprocess.run([sys.executable, "cb_score.py"], capture_output=True,
                          text=True, timeout=900, cwd=CBDIR)


LV = {"red": "🔴", "yellow": "🟡", "plain": "⚪"}


def _red_pairs(by_code):
    """{(code, source)} 集合,只取 red 級——用來跟前一次巡邏結果比對「有沒有新的行動級訊號」。"""
    return {(code, item["source"]) for code, items in (by_code or {}).items()
            for item in items if item.get("level") == "red"}


def confluence_section(by_code, top=15):
    """跨源信念榜 markdown 段(唯讀 by_code,fail-safe——絕不擋巡邏/簡報寫出)。
    多個獨立信息源指向同一標的=最高信息差(Delvin 哲學#11);confluence.py 唯讀分類聚合,無 LLM。
    lazy import 連同 rank/render 全包在 try 內,任何失敗只降級成 fallback 段。"""
    try:
        from intel import confluence
        ranked = confluence.rank(by_code)
        md = confluence.render_markdown(ranked, top=top)
        if len(ranked) > top:  # 不靜默砍尾(feedback_no_silent_limits):列出被截筆數+全量指令
            md += (f"\n\n> …另有 {len(ranked) - top} 檔較低信念的匯流/背離未列"
                   f"（`python3 -m intel.confluence` 看全部）。")
        return md
    except Exception as e:
        return f"## 🎯 跨源信念榜\n（本段生成失敗，不影響其餘簡報：{e}）"


NOTIFY_LEDGER = os.path.join(HERE, ".confluence_notify_ledger.json")
CONFLUENCE_NOTIFY_COOLDOWN_DAYS = 3  # 對齊 mops_news 3 天視窗等易變來源的典型震盪週期


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def _confluence_notify_selection(conf_ranked, today):
    """挑出真的值得推播的匯流/背離,用 ledger(非單純跟前一晚比對)。

    驗證者分離抓到:單純「(code,kind) 不在前一晚快照」會讓 kind 因易變來源(如 3 天新聞視窗
    到期)每晚微幅震盪時反覆判定「新」,同一情勢每晚重推(反而違背推播防洪的本意)。改成:
    每個 (code,kind) 記上次推播日期+conviction,只在①首次出現 ②距上次推播≥冷卻天數
    ③conviction 比上次推播時升級 三者之一才算「值得推」。conf_ranked 已依 rank() 排序
    (陣營數>源數>紅燈數),遍歷保留原序=優先度,不再用集合+字母序 truncate(會把 emoji
    排序意外洗掉高信念的 bull 訊號)。"""
    ledger = _load_json(NOTIFY_LEDGER, {})
    today_d = _parse_date(today) or datetime.date.today()
    selected = []
    for s in conf_ranked:
        key = f"{s['code']}|{s['kind']}"
        prev = ledger.get(key) if isinstance(ledger.get(key), dict) else None
        is_new = prev is None
        is_stale = False
        is_escalated = False
        if prev:
            last_date = _parse_date(prev.get("date", ""))
            is_stale = last_date is None or (today_d - last_date).days >= CONFLUENCE_NOTIFY_COOLDOWN_DAYS
            is_escalated = s["conviction"] > prev.get("conviction", 0)
        if is_new or is_stale or is_escalated:
            selected.append(s)
            ledger[key] = {"date": today, "conviction": s["conviction"]}  # 只在真的推播時蓋掉時間戳,
            # 否則每天照樣出現卻被冷卻壓下的訊號會把「最後一次看到」誤當「最後一次推播」,冷卻期永遠續不完
    cutoff = today_d - datetime.timedelta(days=CONFLUENCE_NOTIFY_COOLDOWN_DAYS * 5)
    def _keep(v):
        if not isinstance(v, dict):
            return False
        d = _parse_date(v.get("date", ""))
        return d is not None and d >= cutoff  # 壞掉的日期字串直接丟棄,不 fail-open 讓垃圾永遠留著
    ledger = {k: v for k, v in ledger.items() if _keep(v)}
    try:
        with open(NOTIFY_LEDGER, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # ledger 是推播降噪輔助,寫不進去不擋巡邏(同全模組 fail-safe 原則)
    return selected


def run():
    today = datetime.date.today().isoformat()
    prev_latest = _load_json(os.path.join(BRIEFS, "latest.json"), {})
    prev_red_pairs = _red_pairs(prev_latest.get("by_code"))
    wl = build_watchlist()
    codes = sorted(wl)
    print(f"watchlist {len(codes)} 檔,開掃…")

    inst = tw_institutional.scan(codes)
    news = mops_watch.major_news(codes, days=3)
    revs = mops_watch.revenue_updates(codes)
    us_sigs = us_analyst.todays_signals(days=2)
    us_insider_sigs = us_insider.todays_signals(days=2)
    us_8k_sigs = us_8k_events.todays_signals(days=2)
    marg = tw_margin.scan(codes)
    sbl_data = tw_sbl.scan(codes)
    holder_data = tw_holders.scan(codes)
    conf_data = tw_investor_conf.scan(codes)
    surv_data = tw_surveillance.scan(codes)
    fsc_data = tw_fsc.scan()  # 自成一套上市金控/銀行/證券/保險名單,不受 CB watchlist(codes)過濾
    sec_enf = us_sec_regulatory.scan_enforcement()  # 自成一套美股 watchlist,同 fsc_data 不受 codes 過濾
    sec_rules = us_sec_regulatory.scan_rule_changes()  # 市場級規則變化,非個股,不進 by_code
    news_us = news_signals.scan_us()  # 自成一套美股 watchlist(us_insider),同 sec_enf 不受 codes 過濾
    news_tw = news_signals.scan_tw(wl)  # 用 codes 對應的公司名(wl)做中文新聞比對
    news_broad = news_signals.broad_themes()  # 政治/總經市場級主題,非個股,不進 by_code(curriculum I 節收尾)
    us13f_data = us_13f_ledger.active_signals()  # 唯讀讀ledger,不觸網(季度資料抓取由獨立cron runner負責)
    tw_fin_data = tw_financials.active_signals(codes)  # 唯讀讀ledger,不觸網(快照抓取由獨立cron runner負責)
    try:
        leadflow_data = tw_leadflow.scan()  # 全市場先行異動雷達,自成一套不受 codes 過濾(6488 美光事件教訓)
    except Exception as e:
        print(f"leadflow 掃描失敗(不擋巡邏):{e}")
        leadflow_data = {}
    try:
        ratings_tw = tw_analyst_ratings.scan(wl)  # FactSet 共識目標價/EPS 速報(cnyes tw_forecast,內容型)
    except Exception as e:
        print(f"tw_analyst_ratings 掃描失敗(不擋巡邏):{e}")
        ratings_tw = []
    try:
        broker_calls = tw_broker_calls.scan(wl)  # 單一券商敘事喊單(共識速報的互補源),標題自帶代碼=全市場
    except Exception as e:
        print(f"tw_broker_calls 掃描失敗(不擋巡邏):{e}")
        broker_calls = {}
    try:
        rank_data = tw_rank_scanner.active_signals(codes)  # 唯讀讀ledger(quote_bridge/rank_scan.py 13:50 cron快照),不觸網
    except Exception as e:
        print(f"tw_rank_scanner 判讀失敗(不擋巡邏):{e}")
        rank_data = []
    try:
        congress_data = us_congress_trades.scan(sorted(us_insider.build_watchlist()))  # 內建源新鮮度守衛,快取凍結時自動回空
    except Exception as e:
        print(f"us_congress_trades 掃描失敗(不擋巡邏):{e}")
        congress_data = {}
    try:
        gold_sig = gold_macro.market_signal()  # 市場級非個股,每日 1 call 記 ledger
    except Exception as e:
        print(f"gold_macro 判讀失敗(不擋巡邏):{e}")
        gold_sig = None
    try:
        exa_sig = exa_search.market_signal()  # 市場級語意事件雷達,每日 4 查詢+月額度守衛
    except Exception as e:
        print(f"exa_search 判讀失敗(不擋巡邏):{e}")
        exa_sig = None

    snap = _cb_snapshot()
    snap_ok = snap.returncode == 0 and "snapshot ok" in (snap.stdout or "")
    sc = _cb_score()
    calib = _load_json(os.path.join(CBDIR, "calibration.json"), {})

    red, yellow, by_code = [], [], {}

    def _emit(code, level, line, source):
        (red if level == "red" else yellow).append(line)
        if code:
            by_code.setdefault(str(code).upper(), []).append(
                {"source": source, "level": level, "signal": line})

    for c in codes:
        f = inst.get(c)
        if not f:
            continue
        line = f"{wl[c]}({c}):{f['signal']}"
        if f["level"] == "red":
            red.append(line)
        elif f["level"] == "yellow":
            yellow.append(line)
        if f["level"] in ("red", "yellow"):
            by_code.setdefault(c, []).append({"source": "institutional", "level": f["level"], "signal": line})
    for n in news:
        line = f"{n['name']}({n['code']}) 重訊[{n['date']}]:{n['subject'][:60]}"
        _emit(n["code"], n["level"], line, "mops_news")
    for r in revs:
        line = f"{r['name']}({r['code']}):{r['signal']}"
        _emit(r["code"], r["level"], line, "revenue")
    for s in us_sigs:
        line = us_analyst.format_line(s)
        _emit(s["symbol"], s["level"], line, "us_analyst")
    for s in us_insider_sigs:
        line = us_insider.format_line(s)
        _emit(s["symbol"], s["level"], line, "us_insider")
    for s in us_8k_sigs:
        line = us_8k_events.format_line(s)
        _emit(s["symbol"], s["level"], line, "us_8k")
    for sym, s in congress_data.items():
        if s["level"] in ("plain", "unknown"):
            continue
        _emit(sym, s["level"], f"🏛️ {sym} {s['signal']}", "us_congress")
    for s in rank_data:
        _emit(s["code"], s["level"], s["signal"], "tw_rank")
    for c in codes:
        m = marg.get(c)
        if not m or m["level"] in ("plain", "unknown"):
            continue
        line = f"{wl[c]}({c}):{m['signal']}"
        _emit(c, m["level"], line, "margin")
    for c in codes:
        s = sbl_data.get(c)
        if not s or s["level"] in ("plain", "unknown"):
            continue
        line = f"{wl[c]}({c}):{s['signal']}"
        _emit(c, s["level"], line, "sbl")
    for c in codes:
        h = holder_data.get(c)
        if not h or h["level"] == "plain":
            continue
        line = f"{wl[c]}({c}):{h['signal']}"
        _emit(c, h["level"], line, "holders")
    for c in codes:
        sv = surv_data.get(c)
        if not sv:
            continue
        line = f"{wl[c]}({c}):{sv['signal']}"
        _emit(c, sv["level"], line, sv["source"])
    for c, f3 in fsc_data.items():
        _emit(c, f3["level"], f3["signal"], f3["source"])
    for c, f4 in sec_enf.items():
        _emit(c, f4["level"], f4["signal"], f4["source"])
    for c, f5 in news_us.items():
        _emit(c, f5["level"], f5["signal"], f5["source"])
    for c, f6 in news_tw.items():
        _emit(c, f6["level"], f6["signal"], f6["source"])
    for c, f7 in us13f_data.items():
        _emit(c, f7["level"], us_13f_ledger.format_line(f7), "us_13f")
    for c, f8 in tw_fin_data.items():
        _emit(c, f8["level"], tw_financials.format_line(f8), "tw_financials")
    for c, f9 in leadflow_data.items():
        _emit(c, f9["level"], f9["signal"], "leadflow")
    for s in ratings_tw:
        _emit(s["code"], s["level"], tw_analyst_ratings.format_line(s), "tw_analyst")
    for c, f11 in broker_calls.items():
        _emit(c, f11["level"], f11["signal"], "tw_broker_calls")
    materials_fetched = 0
    for c in codes:
        f2 = conf_data.get(c)
        if not f2 or f2["level"] == "plain":
            continue
        line = f"{wl[c]}({c}):{f2['signal']}"
        if materials_fetched < MAX_MATERIALS_PER_RUN and (f2.get("pdf_zh") or f2.get("pdf_en")):
            try:
                summ = tw_investor_materials.fetch_materials(c, wl[c], f2)
            except Exception:
                summ = None
            materials_fetched += 1
            if summ and summ.get("highlights"):
                line += "|簡報摘要:" + "、".join(summ["highlights"][:3])
            if summ and summ.get("chart_facts"):
                line += "|圖表:" + "、".join(summ["chart_facts"])
        _emit(c, f2["level"], line, "investor_conf")

    try:
        n_new_ledger = signal_ledger.record(by_code, today)
    except Exception:
        n_new_ledger = 0

    os.makedirs(BRIEFS, exist_ok=True)
    md = [f"# 信息差簡報 {today}", ""]
    md.append(f"watchlist {len(codes)} 檔|法人資料 {len(inst)} 檔|重訊 {len(news)} 則|營收新公告 {len(revs)} 檔|美股分析師動向 {len(us_sigs)} 則|美股內部人交易 {len(us_insider_sigs)} 則|美股8-K重大事件 {len(us_8k_sigs)} 則|融資券 {len(marg)} 檔|借券賣出 {len(sbl_data)} 檔|股權分散 {len(holder_data)} 檔|法說會排程 {len(conf_data)} 檔|監理注意/處置 {len(surv_data)} 檔|金管會裁罰 {len(fsc_data)} 檔|美股SEC行政程序 {len(sec_enf)} 檔|美股規則變化 {len(sec_rules)} 則|新聞事件(美){len(news_us)} 檔|新聞事件(台){len(news_tw)} 檔|市場級主題 {len(news_broad)} 則|美股13F機構持股 {len(us13f_data)} 檔|台股財報結構化 {len(tw_fin_data)} 檔|先行異動雷達 {len(leadflow_data)} 檔|台股共識評等 {len(ratings_tw)} 則|券商喊單 {len(broker_calls)} 檔|國會交易 {len(congress_data)} 檔|黃金宏觀 {'✓' if gold_sig else '—'}")
    md.append("")
    md.append(confluence_section(by_code))
    md.append("")
    md.append("## 🔴 行動級訊號" if red else "## 🔴 行動級訊號:今日無")
    md += [f"- {x}" for x in red]
    md.append("")
    md.append("## 🟡 注意" if yellow else "## 🟡 注意:今日無")
    md += [f"- {x}" for x in yellow]
    md.append("")
    md.append("## 📜 美股 SEC 規則變化(近30日,市場級非個股)" if sec_rules else "## 📜 美股 SEC 規則變化:近30日無")
    md += [f"- {us_sec_regulatory.format_rule_change_line(rc)}" for rc in sec_rules]
    md.append("")
    md.append("## 🌐 市場級主題(政治/總經,近1.5日非個股)" if news_broad else "## 🌐 市場級主題:近1.5日無")
    md += [f"- {news_signals.format_broad_line(b)}" for b in news_broad]
    if gold_sig:
        md.append(f"- 🥇 {gold_sig['signal']}" + ("" if gold_sig["level"] == "plain" else f"({'🔴' if gold_sig['level'] == 'red' else '🟡'})"))
    md.append("")
    md.append("## 📒 回測帳本(CB 預測記分)")
    md.append(f"- 每日快照:{'✅' if snap_ok else '❌ ' + (snap.stderr or '')[-120:]}")
    if calib:
        md.append(f"- 帳本 {calib.get('n_rows', 0)} 筆|可記分 {calib.get('n_interim', 0)} 筆"
                  + (f"|Brier {calib.get('brier_interim')}(丟銅板=0.25)" if calib.get("brier_interim") is not None else ""))
        if calib.get("shrink"):
            md.append(f"- ⚠️ 校準閘門已開:顯示機率 × {calib['shrink']}(實證 {calib.get('realized_interim')} vs 預測 {calib.get('avg_pred_interim')})")
        elif calib.get("note"):
            md.append(f"- {calib['note']}")
    else:
        md.append("- 尚無記分(帳本累積中,滿 14 天開始對答案)")
    md.append(f"- 信息差訊號帳本(P2.6第四步):今晚新增 {n_new_ledger} 筆(`python3 -m intel.signal_ledger score` 查事後報酬分布)")

    path = os.path.join(BRIEFS, f"{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    new_pairs = _red_pairs(by_code) - prev_red_pairs
    new_red_lines = sorted({item["signal"] for code, items in by_code.items() for item in items
                             if item.get("level") == "red" and (code, item["source"]) in new_pairs})[:10]

    # 跨源信念榜(confluence)下游接線:之前只寫進 markdown 段落沒人推播/消費(automation_scorecard
    # B⚠️「下游接線非全自動」)。這裡比照紅燈訊號的「跟前一次比對」pattern,把新出現的匯流/背離
    # 也算出來讓 runner 推播,並存一份輕量快照(confluence_top)供未來下游(日報/交易)直接讀。
    try:
        from intel import confluence
        conf_ranked = confluence.rank(by_code)
        notify_worthy = _confluence_notify_selection(conf_ranked, today)
        new_confluence_count = len(notify_worthy)
        new_confluence_lines = [confluence.format_summary(s) for s in notify_worthy][:10]
    except Exception:
        conf_ranked = []
        new_confluence_count = 0
        new_confluence_lines = []
    confluence_top = [{"code": s["code"], "name": s["name"], "kind": s["kind"],
                        "conviction": s["conviction"], "n_camps": s["n_camps"]}
                       for s in conf_ranked[:20]]

    latest = {"date": today, "red": red, "yellow": yellow,
              "calibration": {k: v for k, v in calib.items() if k != "details"},
              "watchlist_n": len(codes), "by_code": by_code,
              "new_red_since_last_run": new_red_lines, "new_red_count": len(new_pairs),
              "confluence_top": confluence_top,
              "new_confluence_since_last_run": new_confluence_lines,
              "new_confluence_count": new_confluence_count,
              "sec_rule_changes": sec_rules, "news_broad_themes": news_broad,
              "gold_macro": gold_sig,
              "exa_events": exa_sig,
              "signal_ledger_new": n_new_ledger}
    with open(os.path.join(BRIEFS, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    print("\n".join(md))
    print(f"\n→ {path}")
    if new_pairs:
        print(f"\n⚡ 較上次巡邏新增 {len(new_pairs)} 則行動級(紅燈)訊號")
    return latest


if __name__ == "__main__":
    run()
