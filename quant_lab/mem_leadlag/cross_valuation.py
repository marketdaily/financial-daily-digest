#!/usr/bin/env python3
"""跨市場記憶體族群【估值倍數】對照 + 每日帳本(老闆 2026-08-18 交辦的另一半)。

lead-lag 那一半量的是【價格】傳導;這一半量的是【評價方式】——市場願意給同一條
產業鏈上的美股與台股各幾倍。兩者答案不一定一致(實測也確實不一致)。

資料源(全部免費、無需 OAuth):
  台股上市 = TWSE openapi exchangeReport/BWIBBU_ALL   (Code/PEratio/PBratio/DividendYield)
  台股上櫃 = TPEx openapi tpex_mainboard_peratio_analysis
             ⚠ 群聯 8299、旺矽 6223、威剛 3260、宜鼎 5289 都在上櫃,只查 TWSE 會全部漏掉
  美股     = Alpha Vantage OVERVIEW (PERatio/ForwardPE/PriceToBookRatio)
             ⚠ 免費層 25 req/日;FMP 的 /v3/quote 已於 2025-08-31 停用(legacy),別再用

誠實邊界(必須跟著數字一起出現,否則就是在挖坑):
  · 台股兩個來源給的都是 **trailing PE**(過去四季),沒有 forward。
    記憶體是強週期股 → **獲利高峰時 trailing PE 看起來最便宜**,這是經典的週期股 PE 陷阱。
    低 PE 可能是「便宜」,也可能是「市場認為這是最後一季好賺的」。單看數字分不出來。
  · TWSE/TPEx 各股的 EPS 基準季度不同期(intel/pe_ratio_ledger.py 已勘查過此方法論問題),
    跨股比較是近似,不是嚴格同基準。
  · 單日快照無法回答「倍數傳導有沒有時間落後」——那需要序列。故本檔每跑一次寫一行帳本,
    序列從今天開始累積;約三個月後即可對倍數本身跑 lead_lag。

不下單、不寄信。純量測。
"""
import os
import sys
import json
import time
import fcntl
import ssl
import urllib.request
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "valuation_ledger.jsonl")

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
AV_URL = "https://www.alphavantage.co/query?function=OVERVIEW&symbol={s}&apikey={k}"

# 產業線 -> (美股對照組, 台股對照組[(代號, 名稱, 市場)])
LINES = {
    "NAND / 控制器 / 模組": {
        "us": ["SNDK", "WDC"],
        "tw": [("8299", "群聯", "TPEx"), ("3260", "威剛", "TPEx"), ("5289", "宜鼎", "TPEx"),
               ("8088", "品安", "TPEx"), ("4967", "十銓", "TWSE"), ("2451", "創見", "TWSE")],
    },
    "DRAM / HBM": {
        "us": ["MU"],
        "tw": [("2408", "南亞科", "TWSE"), ("2344", "華邦電", "TWSE"),
               ("2337", "旺宏", "TWSE"), ("6770", "力積電", "TWSE")],
    },
    "測試 / 探針卡": {
        "us": ["FORM", "TER"],
        "tw": [("6223", "旺矽", "TPEx"), ("6510", "精測", "TPEx"), ("6515", "穎崴", "TPEx")],
    },
}


# TPEx 的憑證缺 Subject Key Identifier,Python 3.13+ 預設開啟的 VERIFY_X509_STRICT
# 會直接拒連(curl 可以,所以很容易誤判成「網路壞了」)。這裡只關掉 RFC 嚴格旗標,
# **憑證鏈驗證與主機名檢查全部保留**(CERT_REQUIRED / check_hostname 不動)。
_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout, context=_CTX).read())


def _f(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if x > 0 else None
    except Exception:
        return None


def fetch_tw():
    """回 {code: {pe, pb, yield, name, market}}。兩個交易所都抓,缺一即失敗(不靜默半套)。"""
    out = {}
    tw = _get(TWSE_URL)
    if len(tw) < 500:
        sys.exit(f"FATAL: TWSE 只回 {len(tw)} 檔(<500),疑似截斷,拒絕在殘缺樣本上出數字")
    for x in tw:
        out[x["Code"]] = {"pe": _f(x.get("PEratio")), "pb": _f(x.get("PBratio")),
                          "yld": _f(x.get("DividendYield")), "name": x.get("Name"),
                          "market": "TWSE", "date": x.get("Date")}
    tp = _get(TPEX_URL)
    if len(tp) < 500:
        sys.exit(f"FATAL: TPEx 只回 {len(tp)} 檔(<500),疑似截斷,拒絕在殘缺樣本上出數字")
    for x in tp:
        c = x.get("SecuritiesCompanyCode")
        out[c] = {"pe": _f(x.get("PriceEarningRatio")), "pb": _f(x.get("PriceBookRatio")),
                  "yld": _f(x.get("YieldRatio")), "name": x.get("CompanyName"),
                  "market": "TPEx", "date": x.get("Date")}
    return out


def fetch_us(symbols, key):
    out = {}
    for s in symbols:
        try:
            d = _get(AV_URL.format(s=s, k=key))
        except Exception as e:
            out[s] = {"error": str(e)[:80]}
            continue
        if "Symbol" not in d:
            out[s] = {"error": str(d)[:120]}   # 額度用完等,誠實留錯不填假值
        else:
            out[s] = {"pe": _f(d.get("PERatio")), "fwd_pe": _f(d.get("ForwardPE")),
                      "pb": _f(d.get("PriceToBookRatio")), "eps": _f(d.get("EPS")),
                      "name": d.get("Name"),
                      "mcap": _f(d.get("MarketCapitalization"))}
        time.sleep(1.0)
    return out


def append_ledger(row):
    """dedup by date + flock(同 intel/ 既有慣例的三件套)。"""
    with open(LEDGER, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        for line in f:
            try:
                if json.loads(line).get("date") == row["date"]:
                    fcntl.flock(f, fcntl.LOCK_UN)
                    return False
            except Exception:
                continue
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    return True


def main():
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        sys.exit("FATAL: 缺 ALPHAVANTAGE_API_KEY(請 source .env)")

    tw = fetch_tw()
    us_syms = sorted({s for v in LINES.values() for s in v["us"]})
    us = fetch_us(us_syms, key)

    today = dt.date.today().isoformat()
    report = {"date": today, "lines": {}}

    W = 96
    print("=" * W)
    print(f"跨市場記憶體族群 估值倍數對照   {today}")
    print("=" * W)

    for line, cfg in LINES.items():
        blk = {"us": [], "tw": []}
        print(f"\n■ {line}")
        print(f"  {'美股':<26}{'PE':>9}{'前瞻PE':>10}{'PB':>9}{'市值':>11}")
        for s in cfg["us"]:
            d = us.get(s, {})
            if d.get("error"):
                print(f"  {s:<26}{'資料未取得':>9}   ({d['error'][:40]})")
                continue
            mc = f"{d['mcap'] / 1e9:.0f}B" if d.get("mcap") else "-"
            print(f"  {s + ' ' + (d.get('name') or '')[:16]:<26}"
                  f"{d['pe'] if d.get('pe') else float('nan'):>9.2f}"
                  f"{d['fwd_pe'] if d.get('fwd_pe') else float('nan'):>10.2f}"
                  f"{d['pb'] if d.get('pb') else float('nan'):>9.2f}{mc:>11}")
            blk["us"].append({"sym": s, **{k: v for k, v in d.items() if k != "name"}})
        print(f"  {'台股':<26}{'PE':>9}{'前瞻PE':>10}{'PB':>9}{'殖利率':>11}")
        for code, name, mkt in cfg["tw"]:
            d = tw.get(code)
            if not d:
                print(f"  {code + ' ' + name:<26}{'查無':>9}")
                continue
            pe = d["pe"] if d["pe"] else float("nan")
            pb = d["pb"] if d["pb"] else float("nan")
            yl = f"{d['yld']:.2f}%" if d["yld"] else "-"
            print(f"  {code + ' ' + name + f' ({mkt})':<26}{pe:>9.2f}{'—':>10}{pb:>9.2f}{yl:>11}")
            blk["tw"].append({"code": code, "name": name, "market": mkt,
                              "pe": d["pe"], "pb": d["pb"], "yld": d["yld"]})

        # 倍數缺口:台股中位數 / 美股中位數
        up = [d["pe"] for d in blk["us"] if d.get("pe")]
        tp = [d["pe"] for d in blk["tw"] if d.get("pe")]
        if up and tp:
            import statistics as st
            mu_, mt = st.median(up), st.median(tp)
            blk["us_pe_median"], blk["tw_pe_median"] = round(mu_, 2), round(mt, 2)
            blk["tw_over_us"] = round(mt / mu_, 2)
            arrow = "台股折價" if mt < mu_ else "台股溢價"
            print(f"  → PE 中位數:美股 {mu_:.1f} vs 台股 {mt:.1f}   "
                  f"倍數比 {mt / mu_:.2f}x   【{arrow}】")
        report["lines"][line] = blk

    print("\n" + "=" * W)
    print("⚠ 誠實邊界:兩地皆為 trailing PE(過去四季),記憶體是強週期股——")
    print("  獲利高峰時 trailing PE 必然看起來最便宜。低 PE 可能是便宜,也可能是")
    print("  市場認為這是最後一季好賺的。單靠這張表分不出來,要配獲利動能一起看。")
    print("=" * W)

    fresh = append_ledger(report)
    print(f"\n帳本 {'已寫入' if fresh else '今日已存在,略過'} {LEDGER}")
    with open(os.path.join(HERE, "valuation_latest.json"), "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("快照 -> valuation_latest.json")


if __name__ == "__main__":
    main()
