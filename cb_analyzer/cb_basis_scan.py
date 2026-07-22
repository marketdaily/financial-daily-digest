"""拆解活動偵測器:掃全部 CB 標的的個股期貨基差,逆價差異常=CBAS 拆解者
(或其他空方)正在用期貨對沖建倉的足跡。

原理:拆解者買 CB 拆出選擇權後,delta 對沖=放空個股期貨 → 對沖壓力壓出逆價差。
⚠️ 除權息前的逆價差是「股利效應」非對沖壓力(期貨價=現貨-預期股利),7-9月除息旺季
要人工對照除息日;本工具附 FinMind 近期除息註記輔助判讀。
用法:cd cb_analyzer && python3 cb_basis_scan.py [--min-pct 0.3]
"""
import os
import json
import argparse
import datetime

import cb_derivatives as cd

HERE = os.path.dirname(os.path.abspath(__file__))


def cb_universe():
    db = json.load(open(os.path.join(HERE, "cb_database.json"), encoding="utf-8"))
    out = {}
    for x in db.get("items", []):
        c = str(x.get("stock_code") or "").strip()
        if c:
            out[c] = x.get("name") or c
    return out


def upcoming_exdiv(codes):
    """近 45 天內將除息的標的(股利效應會壓出「正常」逆價差)。失敗回空。"""
    today = datetime.date.today()
    out = {}
    for c in codes:
        try:
            rows = cd._finmind("TaiwanStockDividend", c, (today - datetime.timedelta(days=200)).isoformat())
        except Exception:
            continue
        for r in rows:
            d = (r.get("CashExDividendTradingDate") or "").strip()
            if d:
                try:
                    dd = datetime.date.fromisoformat(d)
                    if 0 <= (dd - today).days <= 45:
                        out[c] = d
                except ValueError:
                    pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pct", type=float, default=0.3, help="逆價差幅度門檻(%)")
    a = ap.parse_args()
    uni = cb_universe()
    fmap = cd._stockfut_map()
    scan = {c: n for c, n in uni.items() if c in fmap and fmap[c].get("fut")}
    print(f"CB 標的 {len(uni)} 檔,其中 {len(scan)} 檔有個股期貨 → 掃基差\n")

    rows = []
    for c, n in scan.items():
        fb = cd.futures_basis(c)
        if fb:
            rows.append({"code": c, "name": n, **fb})
    rows.sort(key=lambda r: r["basis_pct"])

    flagged = [r for r in rows if r["basis_pct"] <= -a.min_pct]
    exdiv = upcoming_exdiv([r["code"] for r in flagged]) if flagged else {}

    print(f"{'代號':<6}{'名稱':<8}{'期貨':>8}{'現貨':>8}{'基差%':>8}  註記")
    print("-" * 52)
    for r in rows:
        mark = ""
        if r["basis_pct"] <= -a.min_pct:
            mark = "🔴 逆價差異常" + (f"(⚠️ {exdiv[r['code']]} 除息,可能為股利效應)" if r["code"] in exdiv else "(無近期除息→疑似對沖壓力)")
        print(f"{r['code']:<6}{r['name']:<8}{r['fut_px']:>8.1f}{r['spot']:>8.1f}{r['basis_pct']:>+8.2f}  {mark}")
    print(f"\n🔴 {len(flagged)} 檔逆價差 ≤ -{a.min_pct}%;無除息註記者=值得查:誰在對沖?"
          f"(CBAS 同業建倉/借券空/大戶避險)")


if __name__ == "__main__":
    main()
