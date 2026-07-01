"""台股 CB 拆解分析系統 — CLI。
  python cb.py 8112          單檔全套分析(可給股票代碼或債券代碼或公司名)
  python cb.py --rank        把所有已定價 CB 算過一輪 → 拆解吸引力排序
  python cb.py --list        列出資料庫所有案件
  python cb.py --update x.xlsx   換新 Excel 重建資料庫
所有量化假設在 cb_core.ASSUMPTIONS,報告底部會印出來。"""
import sys, os, json, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cb_core
import cb_data
import cb_market
import cb_profiles
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


def find(db, key):
    key = key.strip()
    hits = [i for i in db["items"]
            if key in (i["stock_code"], i["bond_code"]) or key in i["name"]]
    return hits


def _bar(label, val, maxv, width=18):
    n = int(round(val / maxv * width)) if maxv else 0
    return f"{label} {'█'*n}{'░'*(width-n)} {val:.0f}/{maxv:.0f}"


def report(item, live=False):
    code = item["stock_code"]
    print(f"\n{C['bold']}{C['b']}━━ {item['name']}  (股 {code} / 債 {item['bond_code']}){C['x']}")
    print(f"{C['d']}{item['section']} · {item['underwriter']} · 發行 {item['size_yi']}億 · "
          f"TCRI{item['tcri']}/{item['collateral']} · {item['tenor_year']}年 · {item['put']['raw']}{C['x']}")
    elig, ereasons = cb_core.eligibility(item)
    if elig:
        print(f"  {C['g']}{C['bold']}✅ 符合老闆準則(TCRI 3-4 + 雙位數億)→ 值得拆解{C['x']}")
    else:
        print(f"  {C['r']}{C['bold']}❌ 不符老闆準則,不值得拆解{C['x']}{C['r']} — "
              f"{'；'.join(ereasons)}{C['x']}")

    if not item.get("conv_price") or not item.get("premium_mid"):
        print(f"{C['y']}⚠ 此案條件未定(無轉換價/溢價率),尚無法拆解定價分析。"
              f"備註:{item['note']}{C['x']}")
        return None

    sd = cb_data.get_stock(code, vol_weights=(cb_core.ASSUMPTIONS["vol_w_short"],
                                              cb_core.ASSUMPTIONS["vol_w_long"]))
    if not sd:
        print(f"{C['r']}✗ 抓不到 {code} 現股資料(可能停牌/代碼異常),跳過。{C['x']}")
        return None

    mp = cb_market.get_cb_price(item["bond_code"]) if live else None
    a = cb_core.analyze(item, sd["spot"], sd["vol_blend"],
                        market_price=(mp["price"] if mp else None))
    if not a["ok"]:
        print(f"{C['r']}✗ {a['reason']}{C['x']}")
        return None

    g = lambda v: (C['g'] if v > 0 else C['r']) + f"{v:+.2f}" + C['x']
    print(f"\n  現股價 {C['bold']}{sd['spot']:.2f}{C['x']}（{sd['date']}，近20日 "
          f"{g((sd['ret_20d'] or 0)*100)}%）  轉換價 {item['conv_price']}  "
          f"換股 {a['shares']:.2f}張/CB")
    print(f"  轉換價值 parity = {C['bold']}{a['parity']:.1f}{C['x']}  "
          f"（價內外 {a['moneyness']:.3f}×，{'價內' if a['moneyness']>1 else '價外'}）  "
          f"發行溢價率 {item['premium_mid']}%")
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
    print(f"  {C['bold']}真實清算價 {a['issue_price']:.2f}{C['x']}"
          f"（{a.get('pricing_method') or '—'}{am}）{flag}")

    print(f"\n  {C['bold']}── 拆解定價 ──{C['x']}")
    print(f"  債券底       {a['bond_floor']:6.2f}   (折現率 {a['credit_rate']*100:.2f}% = rf+TCRI利差)")
    print(f"  轉換選擇權   {a['option_value']:6.2f}   (Δ {a['delta']:.2f}, Γ {a['gamma']:.4f})")
    print(f"  理論 CB 價   {C['bold']}{a['theoretical']:6.2f}{C['x']}   vs 清算價 {a['issue_price']:.2f}"
          f"  → 理論edge {g(a['edge_theo'])}")
    if mp:
        print(f"  {C['g']}次級市場成交價 {mp['price']:.2f}（{mp['date']}，{mp['src']}）{C['x']}")
    elif live:
        print(f"  {C['d']}次級市場:無成交/無報價,退回承銷價隱波（設 FINMIND_TOKEN 可解鎖 CB 行情）{C['x']}")
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
    return a


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
    results = []
    for item in db["items"]:
        if not item.get("conv_price") or not item.get("premium_mid"):
            continue
        sd = cb_data.get_stock(item["stock_code"], vol_weights=vw)
        if not sd:
            continue
        mp = cb_market.get_cb_price(item["bond_code"]) if live else None
        a = cb_core.analyze(item, sd["spot"], sd["vol_blend"],
                            market_price=(mp["price"] if mp else None))
        if a["ok"]:
            results.append((item, sd, a))
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


def print_assumptions():
    a = cb_core.ASSUMPTIONS
    print(f"\n{C['d']}── 假設參數(可在 cb_core.ASSUMPTIONS 調整)──")
    print(f"  無風險利率 rf={a['rf']*100:.1f}% · 資產交換 spread={a['asset_swap_spread']*100:.1f}% · "
          f"前瞻波動加權 短{a['vol_w_short']:.0%}/長{a['vol_w_long']:.0%}")
    print(f"  TCRI 信用利差: " + ", ".join(f"{k}→{v*100:.1f}%" for k, v in a['tcri_spread'].items()))
    print(f"  ⚠ 隱含波動由真實承銷/競拍價反解;前瞻波動=EWMA(短)與120日(長)加權(均值回歸)。")
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
    cb_core.set_config(asset_swap_spread=swap, rf=rf, vol_w_short=ws, vol_w_long=wl)

    if args and args[0] == "--update":
        rebuild(args[1] if len(args) > 1 else DEFAULT_XLSX)
        return
    db = load_db()
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
            print(f"找不到「{args[0]}」。試 python cb.py --list 看全表。")
            return
        for item in hits:
            report(item, live=live)
        print_assumptions()


if __name__ == "__main__":
    main()
