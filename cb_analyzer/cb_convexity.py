"""CB 凸性彈藥清單:找「內嵌選擇權被低估=便宜凸性」的可轉債(老闆高信念集中壓的彈藥)。
90% 複用 cb_core.analyze(已算 vol_edge=標的實現波動−內嵌隱波,正=便宜)+ cb_data.get_stock。
本工具只換角度輸出:過老闆硬門檻(TCRI∈{3,4}且規模≥10億)→ 依凸性便宜度排序。
誠實限制:只 12/68 檔有轉換價可定價;CB 次級市價覆蓋薄(多用承銷價反解隱波)。
用法:python3 cb_convexity.py [--tcri N 對缺評等者帶入]
"""
import os, json, argparse

import cb_core
import cb_data

HERE = os.path.dirname(os.path.abspath(__file__))


def load_market_prices():
    """.yuanta_quotes.json → {bond_code: cb_price}(次級市價,有就用市場隱波)。"""
    fp = os.path.join(HERE, ".yuanta_quotes.json")
    out = {}
    try:
        data = json.load(open(fp, encoding="utf-8"))
        rows = data.values() if isinstance(data, dict) else data
        for q in rows:
            code = str(q.get("bond_code") or q.get("code") or "")
            if code and q.get("cb_price"):
                out[code] = float(q["cb_price"])
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcri", type=int, default=None, help="對缺 TCRI 者帶入評等試算")
    ap.add_argument("--json", action="store_true", help="寫 cb_convexity.json 供儀表板讀")
    a = ap.parse_args()

    db = json.load(open(os.path.join(HERE, "cb_database.json"), encoding="utf-8"))
    items = db["items"]
    mkt = load_market_prices()

    rows = []
    skipped = {"無轉換價": 0, "取價失敗": 0}
    for it in items:
        if a.tcri is not None and it.get("tcri") is None:
            it = {**it, "tcri": a.tcri}
        if not cb_core.conv_price(it):
            skipped["無轉換價"] += 1
            continue
        st = None
        try:
            st = cb_data.get_stock(it["stock_code"])
        except Exception:
            pass
        if not st or not st.get("spot"):
            skipped["取價失敗"] += 1
            continue
        mp = mkt.get(str(it.get("bond_code")))
        hv = st.get("vol_blend") or st.get("v60")
        m = cb_core.analyze(it, st["spot"], hv, market_price=mp)
        if not m.get("ok"):
            continue
        rows.append({
            "name": it.get("name"), "code": it.get("stock_code"),
            "tcri": it.get("tcri"), "size": it.get("size_yi"),
            "elig": m["eligible"], "spot": m["spot"], "K": m["conv_price"],
            "parity": m["parity"], "floor": m["bond_floor"], "opt": m["option_value"],
            "iv": m["implied_vol"], "iv_src": m["iv_source"],
            "hv": hv, "v60": st.get("v60"), "v120": st.get("v120"),
            "vol_edge": m["vol_edge"], "delta": m["eff_delta"], "gamma": m["gamma"],
            "vega": m["vega"], "lev": m["leverage"],
            "theo": m["theoretical"], "buy": m["buy_price"], "buy_src": m["buy_source"],
            "edge_theo": m["edge_theo"],
        })

    # 凸性便宜度排序:vol_edge 高=內嵌選擇權相對標的實現波動便宜。無 vol_edge 者殿後。
    rows.sort(key=lambda r: (r["vol_edge"] is not None, r["vol_edge"] or -9), reverse=True)
    # 誠實三層:①過硬門檻(TCRI∈{3,4}且≥10億) ②過規模但信用弱(TCRI≥5) ③其餘/小規模
    def tier(r):
        t, s = r["tcri"], r["size"]
        if r["elig"]:
            return 1
        if s and s >= 10:
            return 2
        return 3
    for r in rows:
        r["tier"] = tier(r)
    t1 = [r for r in rows if r["tier"] == 1]
    t2 = [r for r in rows if r["tier"] == 2]
    t3 = [r for r in rows if r["tier"] == 3]

    if a.json:
        out = {"generated": db.get("parsed_at"), "source": db.get("source_file"),
               "n_total": len(items), "n_priced": len(rows), "skipped": skipped,
               "rows": rows}
        outp = os.path.join(HERE, "cb_convexity.json")
        json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ 已寫 {outp}({len(rows)} 檔)")
        return

    print(f"CB 凸性彈藥清單:{len(items)} 檔中 {len(rows)} 檔可定價"
          f"(跳過:{skipped})\n")
    print("凸性便宜度 = 標的實現波動 − 內嵌選擇權隱波(vol_edge,正=選擇權便宜);"
          "老闆硬門檻=TCRI∈{3,4}且規模≥10億\n")

    def fmt(r):
        ve = f"{r['vol_edge']*100:+.1f}%" if r["vol_edge"] is not None else "  —"
        iv = f"{r['iv']*100:.0f}%" if r["iv"] else "—"
        hv = f"{r['hv']*100:.0f}%" if r["hv"] else "—"
        return (f"  {r['name'][:6]:<7}{r['code']:>5} | 現{r['spot']:>7.1f} K{r['K']:>7.1f} "
                f"parity{r['parity']:>6.0f} 債底{r['floor']:>5.0f} 選擇權{r['opt']:>5.1f} | "
                f"實波{hv:>4}/內隱{iv:>4}({r['iv_src'][:2]}) 便宜度{ve:>6} | "
                f"Δ{r['delta']:>5.2f} 理論vs買價{r['edge_theo']:>+5.1f}")

    print(f"── ①符合老闆硬門檻 TCRI∈{{3,4}}且≥10億({len(t1)} 檔)──")
    for r in t1:
        print(fmt(r))
    if not t1:
        print("  (無:12 檔可拆 CB 全是 TCRI 5-7 中弱信用,無一達投資級門檻——現階段可拆池信用偏弱)")
    print(f"\n── ②過規模≥10億但信用弱 TCRI≥5({len(t2)} 檔,可接受信用風險時的候選)──")
    for r in t2:
        print(fmt(r))
    print(f"\n── ③小規模/其餘({len(t3)} 檔,參考)──")
    for r in t3[:10]:
        print(fmt(r))

    print("\n誠實提醒:①vol_edge 用『CB承銷價/市價反解隱波』非交易所選擇權IV(中小型標的多無掛牌選擇權)")
    print("  ②只 12/68 有轉換價;次級市價僅少數(其餘承銷價反解,時效差)③BS 未含股利率 q,配息股會略高估選擇權")


if __name__ == "__main__":
    main()
