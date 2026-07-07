"""台股 CB 拆解分析系統 — CLI。
  python cb.py 8112          單檔全套分析(老闆 Excel 管線;股票/債券代碼/公司名)
  python cb.py 11011         現有可轉債(找不到就自動查全市場 TPEx,如台泥一永 11011)
  python cb.py 11011 --tcri 4    現有 CB 帶入 TCRI 判定老闆準則
  python cb.py 11011 --live      額外抓 FinMind/TPEx議價板深源(MIS 即時價一律自動抓)
  python cb.py 8112 --premium 5.5 --interest 2.2
                             券商 CBAS 報價單輸入:百元報價(權利金/per100)+每年利息%,
                             全鏈路以真實報價為準(零誤差)
  python cb.py 8112 --watch [秒]  盤中即時監看:每 N 秒(預設20)刷新報價重算全套
  python cb.py --rank        老闆 Excel 已定價 CB → 拆解吸引力排序(三區)
  python cb.py --rank --html     另出玻璃卡片儀表板 report.html
  python cb.py --calendar [天數]  事件日曆:詢圈/掛牌/可拆解日/賣回/到期 倒數(預設60天)
  python cb.py --set-conv 811211 95.3 [備註]
                             人工覆寫最新轉換價(除權息/重設調整後;MOPS 重訊掃描會提醒何時該查)
  python cb.py --list        列出老闆 Excel 所有案件
  python cb.py --update x.xlsx   換新 Excel 重建資料庫
現股/CB 百元報價=TWSE MIS 即時(免token,盤中即時、收盤後=當日收盤);
現有 CB 資料源=TPEx OpenAPI(免token);缺 TCRI 用 --tcri 帶入。假設在 cb_core.ASSUMPTIONS。"""
import sys
import os
import json
import time
import datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cb_core
import cb_data
import cb_market
import cb_quote
import cb_profiles
import cb_existing
import cb_simulate
import cb_intel
import cb_etf_watch
import cb_conv_watch
from parse_excel import parse, DB_PATH, DEFAULT_XLSX

C = {"g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "b": "\033[96m",
     "d": "\033[2m", "bold": "\033[1m", "x": "\033[0m"}


def load_db():
    if not os.path.exists(DB_PATH):
        rebuild(DEFAULT_XLSX)
    with open(DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def rebuild(xlsx):
    data = parse(xlsx)
    db = {"source_file": os.path.basename(xlsx),
          "parsed_at": datetime.date.today().isoformat(),
          "count": len(data), "items": data}
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"已重建資料庫:{len(data)} 檔 ← {os.path.basename(xlsx)}")
    return db


def _tcri_overrides():
    """tcri_overrides.json:免費資料查不到 TEJ TCRI 時的人工/推定評等
    (例:銀行已實際承作該檔拆解 → 信用達標反推)。"""
    try:
        with open(os.path.join(HERE, "tcri_overrides.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def find(db, key):
    """先找老闆 Excel 管線;找不到再查全市場現有可轉債(TPEx)。"""
    key = key.strip()
    hits = [i for i in db["items"]
            if key in (i["stock_code"], i["bond_code"]) or key in i["name"]]
    if hits:
        return [cb_conv_watch.apply_override(h)[0] for h in hits]
    ex = cb_existing.lookup(key)
    ex = [cb_conv_watch.apply_override(it)[0] for it in ex]
    ov = _tcri_overrides()
    for it in ex:
        if it.get("tcri") is None:      # 現有 CB 無 TCRI → 沿用同股票在 Excel 的評等
            same = [d for d in db["items"] if d["stock_code"] == it["stock_code"] and d.get("tcri")]
            if same:
                it["tcri"] = same[0]["tcri"]
        if it.get("tcri") is None and it["stock_code"] in ov:   # 再查人工/推定 override
            o = ov[it["stock_code"]]
            it["tcri"] = o.get("tcri")
            it["tcri_src"] = "override"
            it["tcri_note"] = o.get("note", "")
    return ex


def _bar(label, val, maxv, width=18):
    n = int(round(val / maxv * width)) if maxv else 0
    return f"{label} {'█'*n}{'░'*(width-n)} {val:.0f}/{maxv:.0f}"


def report(item, live=False, premium=None):
    code = item["stock_code"]
    tcri_s = f"TCRI{item['tcri']}" if item.get("tcri") else "TCRI?"
    print(f"\n{C['bold']}{C['b']}━━ {item['name']}  (股 {code} / 債 {item['bond_code']}){C['x']}")
    print(f"{C['d']}{item['section']} · {item['underwriter']} · 發行 {item['size_yi']}億 · "
          f"{tcri_s}/{item['collateral']} · 剩 {item['tenor_year']}年 · {item['put']['raw']}{C['x']}")
    elig, ereasons = cb_core.eligibility(item)
    if elig:
        print(f"  {C['g']}{C['bold']}✅ 符合老闆準則(TCRI 3-4 + 雙位數億)→ 值得拆解{C['x']}")
    else:
        print(f"  {C['r']}{C['bold']}❌ 不符老闆準則,不值得拆解{C['x']}{C['r']} — "
              f"{'；'.join(ereasons)}{C['x']}")

    if not item.get("conv_price"):
        print(f"{C['y']}⚠ 此案條件未定(無轉換價),尚無法拆解定價分析。"
              f"備註:{item['note']}{C['x']}")
        return None
    if item.get("is_existing"):
        print(f"  {C['d']}現有 CB:用剩餘年限計價;轉換價為發行時價可能已調整。{C['x']}")

    sd = cb_data.get_stock(code, vol_weights=(cb_core.ASSUMPTIONS["vol_w_short"],
                                              cb_core.ASSUMPTIONS["vol_w_long"]))
    if not sd:
        print(f"{C['r']}✗ 抓不到 {code} 現股資料(可能停牌/代碼異常),跳過。{C['x']}")
        return None

    mp = cb_market.get_cb_price(item["bond_code"], deep=live)
    a = cb_core.analyze(item, sd["spot"], sd["vol_blend"],
                        market_price=(mp["price"] if mp else None),
                        premium_quote=premium)
    if not a["ok"]:
        print(f"{C['r']}✗ {a['reason']}{C['x']}")
        return None

    g = lambda v: (C['g'] if v > 0 else C['r']) + f"{v:+.2f}" + C['x']
    spot_tag = (f"{C['g']}即時 {sd.get('spot_time') or ''}{C['x']}" if sd.get("spot_rt")
                else f"收盤 {sd['date']}")
    print(f"\n  現股價 {C['bold']}{sd['spot']:.2f}{C['x']}（{spot_tag}，近20日 "
          f"{g((sd['ret_20d'] or 0)*100)}%）  轉換價 {item['conv_price']}  "
          f"換股 {a['shares']:.2f}張/CB")
    if premium is not None:
        print(f"  {C['b']}📋 券商報價單輸入:權利金百元報價 {premium} · "
              f"利息 {cb_core.ASSUMPTIONS['asset_swap_spread']*100:.2f}%/年 → 全鏈路以報價為準{C['x']}")
    ov = item.get("conv_override")
    if ov:
        print(f"  {C['b']}轉換價 {item['conv_price']} = 人工覆寫({ov['date']}"
              f"{(',' + ov['note']) if ov.get('note') else ''};原值 {item.get('conv_price_orig')}){C['x']}")
    for al in cb_conv_watch.pending_alerts(code)[-1:]:
        if not ov or al.get("date_iso", "") > ov.get("date", ""):
            print(f"  {C['r']}⚠ {al['date_iso']} 轉換價調整公告:{al['subject'][:46]}…"
                  f"轉換價可能已變,查最新價後 --set-conv {item['bond_code']} <新價>{C['x']}")
    prem = f"發行溢價率 {item['premium_mid']}%" if item.get("premium_mid") else ""
    print(f"  轉換價值 parity = {C['bold']}{a['parity']:.1f}{C['x']}  "
          f"（價內外 {a['moneyness']:.3f}×，{'價內' if a['moneyness']>1 else '價外'}）  {prem}")
    vd = sd["vols"]
    vstr = "  ".join(f"{k}={v*100:.0f}%" for k, v in
                     [("20日", vd['v20']), ("60日", vd['v60']),
                      ("120日", vd['v120']), ("EWMA", vd['ewma'])] if v)
    print(f"  {C['d']}波動率 {vstr} → 前瞻估計 {C['x']}{a['hist_vol']*100:.0f}%"
          f"{C['d']}（短{cb_core.ASSUMPTIONS['vol_w_short']:.0%}/長{cb_core.ASSUMPTIONS['vol_w_long']:.0%}加權）{C['x']}")
    am = ""
    if a.get("auction_low"):
        am = f"，競拍區間 {a['auction_low']}~{a['auction_high']}"
    flag = "" if a["clearing_known"] else f" {C['y']}(未定，暫用面額100){C['x']}"
    clr = item.get("clearing_price")
    extra = (f"；承銷/清算 {clr:.2f}·{a.get('pricing_method') or '—'}{am}"
             if clr and abs(clr - a["issue_price"]) > 1e-9
             else f"·{a.get('pricing_method') or '—'}{am}")
    print(f"  {C['bold']}買價基準 {a['issue_price']:.2f}{C['x']}"
          f"（{a['buy_source']}{extra}）{flag}")
    exi = item if item.get("is_existing") else (cb_existing.by_bond(item["bond_code"]) or {})
    if exi.get("outstanding_yi") is not None:
        seg = f"  籌碼:流通餘額 {exi['outstanding_yi']}億/發行 {exi.get('size_yi')}億"
        if exi.get("converted_pct") is not None:
            cp = exi["converted_pct"]
            hot = f" {C['y']}(轉換中,籌碼在減){C['x']}" if cp >= 20 else ""
            seg += f" · 已轉換 {cp:.1f}%{hot}"
        if exi.get("coupon_rate") is not None:
            seg += f" · 票面 {exi['coupon_rate']:g}%"
        print(seg)
    nxt = [(d, lab) for d, lab in _events_for(item) if d >= datetime.date.today()][:2]
    if nxt:
        print("  ⏳ 近期事件:" + " · ".join(
            f"{lab} {d.isoformat()}(D-{(d - datetime.date.today()).days})" for d, lab in nxt))

    print(f"\n  {C['bold']}── 拆解定價 ──{C['x']}")
    print(f"  債券底       {a['bond_floor']:6.2f}   (折現率 {a['credit_rate']*100:.2f}% = rf+TCRI利差)")
    print(f"  轉換選擇權   {a['option_value']:6.2f}   (Δ {a['delta']:.2f}, Γ {a['gamma']:.4f})")
    print(f"  理論 CB 價   {C['bold']}{a['theoretical']:6.2f}{C['x']}   vs 買價 {a['issue_price']:.2f}"
          f"（{a['buy_source']}）  → 理論edge {g(a['edge_theo'])}")
    if mp:
        q = mp.get("quote") or {}
        ba = (f"，買 {q['bid']:.2f}/賣 {q['ask']:.2f}" if q.get("bid") and q.get("ask") else "")
        print(f"  {C['g']}CB 百元報價 {C['bold']}{mp['price']:.2f}{C['x']}{C['g']}"
              f"（{mp['src']}{ba}，{mp['date']}）{C['x']}")
    else:
        print(f"  {C['d']}CB 百元報價:MIS 無此債券即時報價"
              f"{'' if live else '(加 --live 可試 FinMind/TPEx 深源)'},退回承銷價隱波{C['x']}")
    if a["implied_vol"]:
        ve = a["vol_edge"]
        col = C['g'] if ve and ve > 0 else C['y']
        print(f"  隱含波動({a['iv_source']}) {a['implied_vol']*100:5.1f}%   前瞻波動 {a['hist_vol']*100:.1f}%"
              f"  → {col}價差 {ve*100:+.1f}pt（{'選擇權便宜' if ve>0 else '選擇權偏貴'}）{C['x']}")

    print(f"\n  {C['bold']}── 拆解槓桿 ──{C['x']}")
    print(f"  權利金成本   {a['cbas_premium']:6.2f}  （拆解後實付本金 ≈ 發行價−債券底+融資）")
    if a["leverage"]:
        print(f"  槓桿倍數     {C['bold']}{a['leverage']:.1f}×{C['x']}    "
              f"（parity {a['parity']:.0f} ÷ 權利金 {a['cbas_premium']:.1f}）")
    print(f"  下檔風險     最多賠光權利金 {a['cbas_premium']:.1f}（≈ 投入本金，債券底已賣斷給銀行保護）")

    print(f"\n  {C['bold']}── 情境損益（對權利金本金）──{C['x']}")
    print(f"  {'股價':>6} {'parity':>8} {'選擇權':>7} {'損益/CB':>8} {'報酬率':>8}")
    for s in a["scenarios"]:
        ror = s["return_on_premium"]
        col = C['g'] if (ror or 0) > 0 else C['r']
        print(f"  {s['move']*100:+5.0f}% {s['spot']:8.1f} {s['parity']:8.1f} "
              f"{s['option_value']:7.2f} {s['pnl_per_cb']:+8.2f} "
              f"{col}{(ror or 0)*100:+7.0f}%{C['x']}")

    print(f"\n  {C['bold']}── 綜合評分 {_score_color(a['score'])}{a['score']:.0f}/100{C['x']} ──{C['x']}")
    for rr in a["score_reasons"]:
        print(f"    · {rr}")
    print(f"  {C['bold']}結論:{verdict(a['score'])}{C['x']}")
    _print_profile(code)
    _print_etf(code)
    return a


def _print_etf(code):
    """主動式 ETF 持股狀況+近期異動(讀本地帳本,不打網路;帳本由每日 cron 更新)。"""
    try:
        info = cb_etf_watch.stock_summary(code)
    except Exception:
        return
    if not info or (not info["holders"] and not info["events"]):
        return
    print(f"\n  {C['bold']}── 🎯 主動式 ETF ──{C['x']}  "
          f"{C['d']}(持股資料日 {info.get('data_date') or '—'}){C['x']}")
    for h in info["holders"][:6]:
        sh = "（{:,.0f} 股）".format(h["shares"]) if h.get("shares") else ""
        print(f"  {h['etf_name']}({h['etf']}) 持 {h['weight']:.2f}%{sh}")
    for e in info["events"][:5]:
        col = C['g'] if e["kind"] in ("新進", "加碼") else C['r']
        print(f"  {col}⚡ {e['date']} {e['etf_name']} {e['kind']}"
              f"{('' if e.get('note') is None else ' ' + e['note'])}{C['x']}")


def _print_profile(code):
    p = cb_profiles.get_profile(code)
    ind = p.get("industry") or "—"
    print(f"\n  {C['bold']}── 🏢 公司 ──{C['x']}  {C['b']}{ind}{C['x']}")
    if not p.get("curated"):
        print(f"  {C['d']}(產業分類 FinMind;詳細營運待補進 company_profiles.json){C['x']}")
        return
    if p.get("business"):
        print(f"  {p['business']}")
    if p.get("products"):
        print(f"  {C['d']}產品:{C['x']}{'、'.join(p['products'])}")
    for label, key in [("上游", "upstream"), ("下游", "downstream"),
                       ("客戶", "customers"), ("合作", "partners")]:
        if p.get(key):
            print(f"  {C['d']}{label}:{C['x']}{p[key]}")
    if p.get("note"):
        print(f"  {C['y']}💡 {p['note']}{C['x']}")


def watch(item, interval=20, live=False, premium=None):
    """盤中即時監看:每 interval 秒刷新 MIS 報價、重算全套拆解,一行一快照。Ctrl+C 停。"""
    code, bond = item["stock_code"], item["bond_code"]
    vw = (cb_core.ASSUMPTIONS["vol_w_short"], cb_core.ASSUMPTIONS["vol_w_long"])
    print(f"\n{C['bold']}{C['b']}👁 盤中監看 {item['name']}(股 {code}/債 {bond}) "
          f"每 {interval:.0f}s 刷新,Ctrl+C 停{C['x']}", flush=True)
    print(f"  {'時間':<9}{'現股':>8}{'CB價':>8}{'parity':>7}{'權利金':>7}"
          f"{'理論':>7}{'隱波':>6}{'Δ':>5}{'評分':>5}", flush=True)
    last = None
    try:
        while True:
            try:
                cb_quote.get_quotes([code, bond], ttl=max(5, interval - 2))
                sd = cb_data.get_stock(code, vol_weights=vw)
                mp = cb_market.get_cb_price(bond, deep=False)
                a = cb_core.analyze(item, sd["spot"], sd["vol_blend"],
                                    market_price=(mp["price"] if mp else None),
                                    premium_quote=premium) if sd else {"ok": False}
            except Exception:
                a = {"ok": False}
            if a.get("ok"):
                t = (sd.get("spot_time") or datetime.datetime.now().strftime("%H:%M:%S"))[:8]
                iv = f"{a['implied_vol']*100:.0f}%" if a.get("implied_vol") else "—"
                cbp = f"{mp['price']:.2f}" if mp else "—"
                mark = ""
                if last is not None and sd["spot"] != last:
                    mark = C['g'] + "▲" + C['x'] if sd["spot"] > last else C['r'] + "▼" + C['x']
                last = sd["spot"]
                print(f"  {t:<9}{sd['spot']:>8.2f}{mark}{cbp:>8}{a['parity']:>7.1f}"
                      f"{a['cbas_premium']:>7.2f}{a['theoretical']:>7.2f}{iv:>6}"
                      f"{a['delta']:>5.2f}{a['score']:>5.0f}", flush=True)
            else:
                print(f"  {datetime.datetime.now().strftime('%H:%M:%S')}  (本輪抓價/計算失敗,續盯)",
                      flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{C['d']}監看結束。{C['x']}")


def _score_color(s):
    return C['g'] if s >= 65 else (C['y'] if s >= 50 else C['r'])


def verdict(s):
    if s >= 70:
        return f"{C['g']}強力候選,值得拆解進場{C['x']}"
    if s >= 58:
        return f"{C['g']}有吸引力,可納入觀察並議價{C['x']}"
    if s >= 48:
        return f"{C['y']}中性,需更好的進場價或更高波動才划算{C['x']}"
    return f"{C['r']}吸引力低,暫不建議拆解{C['x']}"


def rank(db, live=False):
    print(f"\n{C['bold']}{C['b']}═══ 全表 CB 拆解吸引力排序 ═══{C['x']}  "
          f"{C['d']}(來源 {db['source_file']}, {db.get('parsed_at','')}){C['x']}\n")
    vw = (cb_core.ASSUMPTIONS["vol_w_short"], cb_core.ASSUMPTIONS["vol_w_long"])
    priced = [i for i in db["items"] if i.get("conv_price") and i.get("premium_mid")]
    # 一次批次抓全部現股+CB 即時報價進快取,後面逐檔分析全走快取(不重複打 MIS)
    try:
        cb_quote.get_quotes([i["stock_code"] for i in priced] + [i["bond_code"] for i in priced])
    except Exception:
        pass
    results = []
    for item in priced:
        sd = cb_data.get_stock(item["stock_code"], vol_weights=vw)
        if not sd:
            continue
        mp = cb_market.get_cb_price(item["bond_code"], deep=live)
        a = cb_core.analyze(item, sd["spot"], sd["vol_blend"],
                            market_price=(mp["price"] if mp else None))
        if a["ok"]:
            results.append((item, sd, a))
    rt = [sd for _, sd, _ in results if sd.get("spot_rt")]
    if rt:
        print(f"  {C['g']}報價:MIS 即時({rt[0].get('spot_time') or ''},{len(rt)}/{len(results)} 檔即時)"
              f"{C['x']}{C['d']} · 其餘退回收盤價{C['x']}\n" if len(rt) < len(results) else
              f"  {C['g']}報價:MIS 即時({rt[0].get('spot_time') or ''}){C['x']}\n")
    results.sort(key=lambda x: x[2]["score"], reverse=True)
    elig = [r for r in results if r[2]["eligible"]]
    other = [r for r in results if not r[2]["eligible"]]

    def _row(n, item, sd, a):
        iv = f"{a['implied_vol']*100:.0f}%" if a['implied_vol'] else "—"
        lev = f"{a['leverage']:.1f}x" if a['leverage'] else "—"
        col = _score_color(a['score'])
        v = "買" if a['score'] >= 58 else ("觀望" if a['score'] >= 48 else "避")
        print(f"  {n:>2} {col}{a['score']:>4.0f}{C['x']} {item['name']:<10} {item['stock_code']:<6} "
              f"TCRI{item['tcri']} {str(item['size_yi'])+'億':<6} "
              f"{sd['spot']:>7.1f} {a['parity']:>6.1f} {a['issue_price']:>5.0f} "
              f"{iv:>5} {a['hist_vol']*100:>4.0f}% {lev:>5} {col}{v}{C['x']}")

    hdr = (f"  {'#':>2} {'評分':>4} {'名稱':<10} {'代碼':<6} {'評等':<5} {'量':<6} "
           f"{'現價':>7} {'parity':>6} {'清算':>5} {'隱波':>5} {'歷波':>5} {'槓桿':>5} {'結論'}")
    print(f"{C['g']}{C['bold']}✅ 符合老闆準則(TCRI 3-4 + 雙位數億)= 值得拆解{C['x']}")
    if elig:
        print(hdr)
        for n, (item, sd, a) in enumerate(elig, 1):
            _row(n, item, sd, a)
    else:
        print(f"  {C['y']}(本期已定價案件無一符合){C['x']}")

    _watchlist(db)
    print(f"\n  {C['d']}已定價符合準則 {len(elig)} 檔"
          f"(另 {len(other)} 檔不符準則已略過、{db['count']-len(results)} 檔條件未定/無股價)。{C['x']}")
    print_assumptions()
    return elig


def _watchlist(db):
    """未定價但已符合老闆 TCRI+量 準則的管線案件 → 值得盯著等定價。"""
    a = cb_core.ASSUMPTIONS
    watch = [i for i in db["items"]
             if (not i.get("conv_price") or not i.get("premium_mid"))
             and i.get("tcri") in a["elig_tcri"]
             and (i.get("size_yi") or 0) >= a["elig_min_size"]]
    if not watch:
        return
    watch.sort(key=lambda i: -(i.get("size_yi") or 0))
    print(f"\n{C['b']}{C['bold']}👀 待定價觀察清單(符合準則但條件未定,盯著等承銷價){C['x']}")
    for i in watch:
        ind = cb_profiles.get_profile(i["stock_code"]).get("industry") or ""
        print(f"  · {i['name']:<12} {i['stock_code']:<6} TCRI{i['tcri']} "
              f"{str(i['size_yi'])+'億':<6} {i['tenor_year']}年 · {C['d']}{ind}{C['x']}")


def _pdate(s):
    try:
        return datetime.date.fromisoformat(str(s).strip()[:10])
    except (ValueError, TypeError, AttributeError):
        return None


def _events_for(item, ref_year=None):
    """單一 CB 的關鍵日期 list[(date, label)](排序)。Excel 管線+現有 CB 都吃。
    ≈ 開頭的 label 表示推算值(掛牌日+賣回年數),非公告精確日。"""
    ev = []
    def add(d, label):
        if d:
            ev.append((d, label))
    add(_pdate(item.get("effective_date")), "申報生效")
    add(_pdate(item.get("listing_date")), "掛牌")
    add(_pdate(item.get("split_date")), "🔑可拆解日")
    add(_pdate(item.get("conv_start")), "開始可轉換")
    add(_pdate(item.get("conv_end")), "轉換截止")
    add(_pdate(item.get("maturity_date")), "到期")
    # 詢圈/競拍:bookbuild 文字如「詢圈 6/9-6/10」「競拍 6/16」;年份用申報生效/公告年推
    bb = item.get("bookbuild") or ""
    m = __import__("re").search(r"(\d{1,2})/(\d{1,2})", bb)
    if m:
        yr = (ref_year or (_pdate(item.get("effective_date")) or _pdate(item.get("announce_date"))
                           or datetime.date.today()).year)
        try:
            add(datetime.date(yr, int(m.group(1)), int(m.group(2))),
                ("競拍" if "競拍" in bb else "詢圈"))
        except ValueError:
            pass
    # 提前賣回:現有 CB put.raw 帶精確日;Excel 管線用 掛牌+年數 推算
    put = item.get("put") or {}
    m = __import__("re").search(r"@(\d{4}-\d{2}-\d{2})", put.get("raw") or "")
    if m:
        add(_pdate(m.group(1)), f"提前賣回@{put.get('redeem_price') or 100:g}")
    elif put.get("year") and item.get("listing_date"):
        ld = _pdate(item["listing_date"])
        if ld:
            try:
                add(ld.replace(year=ld.year + int(put["year"])), "≈提前賣回")
            except ValueError:
                pass
    return sorted(ev)


def calendar_view(db, days=60):
    """老闆 Excel 管線全案件 → 未來 N 天事件日曆(倒數排序)。"""
    today = datetime.date.today()
    rows = []
    for item in db["items"]:
        for d, lab in _events_for(item):
            if today <= d <= today + datetime.timedelta(days=days):
                rows.append((d, lab, item))
    rows.sort(key=lambda x: x[0])
    print(f"\n{C['bold']}{C['b']}📅 CB 事件日曆(未來 {days} 天,{len(rows)} 件){C['x']}  "
          f"{C['d']}來源 {db['source_file']};≈為推算日{C['x']}\n")
    if not rows:
        print(f"  {C['d']}(窗口內無事件){C['x']}")
        return
    for d, lab, item in rows:
        dd = (d - today).days
        col = C['r'] if dd <= 3 else (C['y'] if dd <= 7 else "")
        elig = "✅" if cb_core.eligibility(item)[0] else "  "
        print(f"  {col}D-{dd:<3}{C['x']} {d.isoformat()}  {lab:<10} {elig} "
              f"{item['name']:<12}(股 {item['stock_code']}/債 {item['bond_code']}) "
              f"{C['d']}TCRI{item.get('tcri') or '?'} {item.get('size_yi') or '?'}億{C['x']}")


def _parse_capital(s):
    s = str(s).strip().replace(",", "").replace("$", "").replace("NT", "")
    mult = 1
    if s.endswith("億"):
        mult, s = 1e8, s[:-1]
    elif s.endswith("萬"):
        mult, s = 1e4, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _analyzed_candidates(db, codes=None):
    """回 [(item, a)] 可模擬標的。codes 有指定就用(含現有CB),否則用老闆Excel符合準則+已定價。"""
    vw = (cb_core.ASSUMPTIONS["vol_w_short"], cb_core.ASSUMPTIONS["vol_w_long"])
    items = []
    if codes:
        for c in codes:
            items += find(db, c)
    else:
        items = [i for i in db["items"]
                 if i.get("conv_price") and i.get("premium_mid") and cb_core.eligibility(i)[0]]
    out = []
    for it in items:
        sd = cb_data.get_stock(it["stock_code"], vol_weights=vw)
        if not sd:
            continue
        mp = cb_market.get_cb_price(it["bond_code"])
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"],
                            market_price=(mp["price"] if mp else None))
        if a.get("ok"):
            out.append((it, a))
    return out


def _why_grow(code, spot=None):
    p = cb_profiles.get_profile(code)
    bits = []
    if p.get("curated"):
        if p.get("business"):
            bits.append(p["business"])
        if p.get("downstream"):
            bits.append(f"下游需求:{p['downstream']}")
        if p.get("note"):
            bits.append(f"題材/地位:{p['note']}")
    else:
        bits.append(f"產業:{p.get('industry') or '—'}(詳細營運待補)")
    lines = [f"      · {ln}" for ln in cb_intel.intel_lines(code, spot)]
    base = "  ".join(bits)
    return base + ("\n" + "\n".join(lines) if lines else "")


def sim_report(db, capital, codes=None, drift=0.07):
    cands = _analyzed_candidates(db, codes)
    if not cands:
        print(f"{C['r']}找不到可模擬標的(符合準則且已定價,或用 --sim 本金 代碼… 指定現有CB){C['x']}")
        return
    single = capital < 1_000_000 or len(cands) == 1
    print(f"\n{C['bold']}{C['b']}💰 資金模擬  本金 NT${capital:,.0f}{C['x']}  "
          f"{C['d']}({'小資單押' if single else '分散投組'}模式,標的池 {len(cands)} 檔){C['x']}")

    # 小資單押:挑評分最高一檔
    if single:
        cands = sorted(cands, key=lambda x: x[1]["score"], reverse=True)[:1]
    scen = cb_simulate.multi_drift(cands, capital, base_drift=drift)
    base = next((r for r in scen if r["ok"] and abs(r["drift"] - drift) < 1e-9), None)
    if not base or not base["ok"]:
        print(f"{C['r']}✗ {(base or {}).get('reason','本金不足買進任一口(每口權利金×1000)')}{C['x']}")
        return

    for L in base["legs"]:
        it, a = L["item"], L["a"]
        print(f"\n  {C['bold']}▶ 買進 {it['name']}(股 {it['stock_code']} / 債 {it['bond_code']}){C['x']}")
        print(f"    投入 {C['bold']}{L['units']} 口{C['x']}(每口權利金 NT${L['unit_cap']:,.0f})"
              f" = NT${L['deployed']:,.0f}  現股價 {L['spot']:.1f} / 轉換價 {L['K']}")
        print(f"    {C['g']}📈 為什麼會漲:{C['x']}{_why_grow(it['stock_code'], L['spot'])}")
        # 為什麼要等(量化)
        oob = (L['spot']/L['K'] - 1)*100
        pos = "價內" if oob >= 0 else "價外"
        bey = ("約 %.1f 年" % L['be_years']) if L['be_years'] else "抱到期中位數到不了(需高於預期漲勢)"
        print(f"    {C['y']}⏳ 為什麼要等:{C['x']}現價距轉換價 {oob:+.0f}%({pos});"
              f"要獲利股票需漲到 {L['be_S']:.1f}(+{L['be_move']*100:.0f}%);"
              f"以前瞻波動 {L['vol']*100:.0f}% 估,中位數{bey}才到回本點")
        r = cb_intel.research(it["stock_code"])
        if r and r.get("target_price"):
            tup = (r["target_price"] / L["spot"] - 1) * 100
            if tup < L["be_move"] * 100:
                print(f"    {C['r']}⚠ 現實檢查:券商目標價僅隱含 {tup:+.0f}%,<回本所需 +{L['be_move']*100:.0f}%"
                      f" → 即使達標仍回不了本,這檔不適合單押,宜換近價平標的{C['x']}")
        print(f"    {C['b']}⌛ 預期回本期間:{C['x']}"
              f"{('約 '+format(L['be_years'],'.1f')+' 年') if L['be_years'] else '需靠波動,非中位數'}"
              f"(部位可抱到 {L['T']:.1f} 年到期);"
              f"抱到期獲利機率 {C['bold']}{L['prob_profit']*100:.0f}%{C['x']}")
        print(f"    下檔:最多賠光權利金 NT${L['deployed']:,.0f}(債券底已賣斷給銀行,不會賠更多)")

    print(f"\n  {C['bold']}── 蒙地卡羅結果({base['n']:,}次模擬,抱到期 {base['horizon']:.1f}年)──{C['x']}")
    print(f"    投入本金 NT${base['deployed']:,.0f}  剩現金 NT${base['cash_left']:,.0f}")
    print(f"    {'情境(股票年報酬)':<18}{'預期賺賠':>14}{'年化':>8}{'賺錢機率':>9}")
    for r in scen:
        if not r["ok"]:
            continue
        col = C['g'] if r['exp_pnl'] > 0 else C['r']
        print(f"    {r['drift_label']+'('+format(r['drift']*100,'.0f')+'%)':<18}"
              f"{col}NT${r['exp_pnl']:>+12,.0f}{C['x']}{r['ann_return']*100:>7.0f}%"
              f"{r['prob_profit']*100:>8.0f}%")
    b = base
    print(f"\n    基準情境分佈:悲觀(P5) NT${b['p5']:+,.0f} · 中位 NT${b['p50']:+,.0f} · "
          f"樂觀(P95) NT${b['p95']:+,.0f}")
    print(f"  {C['d']}假設:GBM 股價路徑、前瞻波動、標的相關性 ρ={b['rho']}、下檔封頂於權利金。"
          f"漂移是關鍵假設(用 --drift 調);未計稅費/資產交換利差變動/提前贖回。{C['x']}")


def print_assumptions():
    a = cb_core.ASSUMPTIONS
    print(f"\n{C['d']}── 假設參數(可在 cb_core.ASSUMPTIONS 調整)──")
    print(f"  無風險利率 rf={a['rf']*100:.1f}% · 資產交換 spread={a['asset_swap_spread']*100:.1f}% · "
          f"前瞻波動加權 短{a['vol_w_short']:.0%}/長{a['vol_w_long']:.0%}")
    print("  TCRI 信用利差: " + ", ".join(f"{k}→{v*100:.1f}%" for k, v in a['tcri_spread'].items()))
    print("  ⚠ 隱含波動由真實承銷/競拍價反解;前瞻波動=EWMA(短)與120日(長)加權(均值回歸)。")
    print(f"     融資/稅費/賣回時點/流動性折價未精算,評分供篩選排序,進場前仍須人工核對承銷與資產交換報價。{C['x']}")


def list_all(db):
    print(f"\n{C['bold']}資料庫 {db['count']} 檔 (來源 {db['source_file']}){C['x']}\n")
    sect = None
    for i in db["items"]:
        if i["section"] != sect:
            sect = i["section"]
            print(f"\n{C['b']}【{sect}】{C['x']}")
        priced = "●" if (i.get("conv_price") and i.get("premium_mid")) else "○"
        cp = f"轉{i['conv_price']}" if i.get('conv_price') else "未定"
        print(f"  {priced} {i['stock_code']:<6} {i['name']:<12} TCRI{i['tcri']} "
              f"{str(i['size_yi'])+'億':<6} 溢{i.get('premium_mid') or '—'} {cp} {i['put']['raw']}")


CONFIG_PATH = os.path.join(HERE, "cb_config.json")


def load_config():
    """讀 cb_config.json 覆寫假設參數;不存在就用內建預設。"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cb_core.set_config(**json.load(f))
        except Exception as e:
            print(f"{C['y']}config 讀取失敗,用預設:{e}{C['x']}")


def pop_flag(args, name, cast=float):
    """從 args 取出 --name value,回 value 或 None,並原地移除。"""
    if name in args:
        i = args.index(name)
        try:
            val = cast(args[i + 1])
            del args[i:i + 2]
            return val
        except (IndexError, ValueError):
            del args[i:i + 1]
    return None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    load_config()
    # CLI 旗標覆寫(優先於 config 檔)
    swap = pop_flag(args, "--swap")
    rf = pop_flag(args, "--rf")
    ws = pop_flag(args, "--vol-short")
    wl = pop_flag(args, "--vol-long")
    want_html = "--html" in args
    if "--html" in args:
        args.remove("--html")
    live = "--live" in args
    if "--live" in args:
        args.remove("--live")
    tcri_override = pop_flag(args, "--tcri", int)
    drift = pop_flag(args, "--drift")
    premium = pop_flag(args, "--premium")          # 券商 CBAS 報價單:權利金百元報價
    interest = pop_flag(args, "--interest")        # 券商 CBAS 報價單:每年利息(%)
    watch_iv = None
    if "--watch" in args:
        i = args.index("--watch")
        watch_iv = 20.0
        if i + 1 < len(args):
            try:
                v = float(args[i + 1])
                if 5 <= v <= 600:                   # 5~600 秒視為間隔;更大(如 8112)視為代碼
                    watch_iv = v
                    del args[i + 1]
            except ValueError:
                pass
        args.remove("--watch")
    if interest is not None:                        # --interest 一律是百分比:2.2 → 0.022
        interest /= 100.0
    cb_core.set_config(asset_swap_spread=(swap if swap is not None else interest),
                       rf=rf, vol_w_short=ws, vol_w_long=wl)

    if args and args[0] == "--update":
        rebuild(args[1] if len(args) > 1 else DEFAULT_XLSX)
        return
    if args and args[0] == "--set-conv":
        if len(args) < 3:
            print("用法:python cb.py --set-conv <債券或股票代碼> <最新轉換價> [備註]")
            return
        r = cb_conv_watch.set_override(args[1], float(args[2]), " ".join(args[3:]))
        print(f"已覆寫 {args[1]} 轉換價 = {r['conv_price']}({r['date']});該公司待核警示已標記解決")
        return
    db = load_db()
    if args and args[0] == "--calendar":
        calendar_view(db, days=int(args[1]) if len(args) > 1 else 60)
        return
    if args and args[0] == "--sim":
        cap = _parse_capital(args[1]) if len(args) > 1 else None
        if not cap:
            print("用法:python cb.py --sim 1000萬  或  --sim 500000 [代碼…] [--drift 0.07]")
            return
        sim_report(db, cap, codes=args[2:] or None, drift=(drift if drift is not None else 0.07))
        return
    if not args or args[0] == "--rank":
        results = rank(db, live=live)
        if want_html:
            import cb_report
            path = cb_report.write_report(db, results)
            print(f"\n{C['g']}HTML 報告已輸出 → {path}{C['x']}")
    elif args[0] == "--list":
        list_all(db)
    else:
        hits = find(db, args[0])
        if not hits:
            print(f"找不到「{args[0]}」。試 python cb.py --list 看全表,或確認代碼(現有CB用債券代碼如 11011)。")
            return
        if tcri_override:
            for it in hits:
                it["tcri"] = tcri_override
        if watch_iv:
            target = next((h for h in hits if h.get("conv_price")), None)
            if not target:
                print(f"{C['y']}⚠ 此案條件未定(無轉換價),無法監看。{C['x']}")
                return
            watch(target, interval=watch_iv, live=live, premium=premium)
            return
        for item in hits:
            report(item, live=live, premium=premium)
        print_assumptions()


if __name__ == "__main__":
    main()
