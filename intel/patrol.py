"""信息差巡邏中樞:每晚把 watchlist 掃一遍(法人動向+重訊+月營收),產出訊號簡報。
watchlist = cb_database 全部標的 ∪ cb_analyzer/holdings.json ∪ intel/watchlist.json extras。
同場加映:①觸發 CB 每日預測快照(餵 predictions.jsonl,就算沒人開網頁帳本也天天長)
②跑 cb_score 記分 → 校準表。輸出 intel/briefs/<日期>.md + latest.json(機器可讀,日報之後接這裡)。
用法:cd Delvin-agent && python3 -m intel.patrol
"""
import os, sys, json, datetime, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CBDIR = os.path.join(ROOT, "cb_analyzer")
BRIEFS = os.path.join(HERE, "briefs")

from intel import tw_institutional, mops_watch, us_analyst, us_insider, tw_margin, tw_sbl, tw_holders, tw_investor_conf, tw_investor_materials, tw_surveillance

MAX_MATERIALS_PER_RUN = 5  # 法說會簡報下載+Ollama摘要較耗時,單次巡邏封頂避免跑太久


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_watchlist():
    """回 {stock_code: 顯示名}。"""
    wl = {}
    db = _load_json(os.path.join(CBDIR, "cb_database.json"), {})
    for it in db.get("items", []):
        if it.get("stock_code"):
            wl.setdefault(str(it["stock_code"]), it.get("name", ""))
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
    marg = tw_margin.scan(codes)
    sbl_data = tw_sbl.scan(codes)
    holder_data = tw_holders.scan(codes)
    conf_data = tw_investor_conf.scan(codes)
    surv_data = tw_surveillance.scan(codes)

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
    for c in codes:
        m = marg.get(c)
        if not m or m["level"] == "plain":
            continue
        line = f"{wl[c]}({c}):{m['signal']}"
        _emit(c, m["level"], line, "margin")
    for c in codes:
        s = sbl_data.get(c)
        if not s or s["level"] == "plain":
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
        _emit(c, f2["level"], line, "investor_conf")

    os.makedirs(BRIEFS, exist_ok=True)
    md = [f"# 信息差簡報 {today}", ""]
    md.append(f"watchlist {len(codes)} 檔|法人資料 {len(inst)} 檔|重訊 {len(news)} 則|營收新公告 {len(revs)} 檔|美股分析師動向 {len(us_sigs)} 則|美股內部人交易 {len(us_insider_sigs)} 則|融資券 {len(marg)} 檔|借券賣出 {len(sbl_data)} 檔|股權分散 {len(holder_data)} 檔|法說會排程 {len(conf_data)} 檔|監理注意/處置 {len(surv_data)} 檔")
    md.append("")
    md.append("## 🔴 行動級訊號" if red else "## 🔴 行動級訊號:今日無")
    md += [f"- {x}" for x in red]
    md.append("")
    md.append("## 🟡 注意" if yellow else "## 🟡 注意:今日無")
    md += [f"- {x}" for x in yellow]
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

    path = os.path.join(BRIEFS, f"{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    new_pairs = _red_pairs(by_code) - prev_red_pairs
    new_red_lines = sorted({item["signal"] for code, items in by_code.items() for item in items
                             if item.get("level") == "red" and (code, item["source"]) in new_pairs})[:10]

    latest = {"date": today, "red": red, "yellow": yellow,
              "calibration": {k: v for k, v in calib.items() if k != "details"},
              "watchlist_n": len(codes), "by_code": by_code,
              "new_red_since_last_run": new_red_lines, "new_red_count": len(new_pairs)}
    with open(os.path.join(BRIEFS, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    print("\n".join(md))
    print(f"\n→ {path}")
    if new_pairs:
        print(f"\n⚡ 較上次巡邏新增 {len(new_pairs)} 則行動級(紅燈)訊號")
    return latest


if __name__ == "__main__":
    run()
