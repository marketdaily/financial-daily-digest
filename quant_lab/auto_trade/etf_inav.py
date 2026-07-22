"""ETF 盤中折溢價資料源(證交所 MIS all_etf.txt,官方預估淨值 iNAV)。
欄位解碼:a=代碼 b=名稱 e=市價 f=預估淨值 g=折溢價% i/j=日期時間。
用途:①ETF 折溢價魚的資料層(POND Tier D)②即時掃描異常折溢價。
⚠️ 「期貨信託基金」類(正2/反1/商品)最易發生申贖受限=溢價不收斂陷阱(原油正2事件),
掃描標注;進場魚須先確認申贖開放,本工具只供觀測。
用法:python3 etf_inav.py [--top 8]
"""
import json
import argparse
import urllib.request

URL = "https://mis.twse.com.tw/stock/data/all_etf.txt"


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://mis.twse.com.tw/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.loads(r.read().decode("utf-8", "ignore"))
    out = {}
    for grp in j.get("a1", []):
        for x in grp.get("msgArray", []):
            try:
                out[x["a"]] = {"name": x["b"], "price": float(x["e"]),
                               "inav": float(x["f"]), "prem_pct": float(x["g"]),
                               "time": f'{x.get("i","")} {x.get("j","")}',
                               "futures_type": "期貨" in x["b"]}
            except (KeyError, ValueError, TypeError):
                continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    data = fetch()
    rows = sorted(data.items(), key=lambda kv: kv[1]["prem_pct"])
    print(f"ETF 折溢價快照:{len(rows)} 檔(來源:證交所 MIS 官方 iNAV)\n")
    print(f"{'代碼':<8}{'折溢價%':>8}{'市價':>9}{'淨值':>9}  名稱")
    print("-" * 60)
    print("〔最深折價〕")
    for c, v in rows[:a.top]:
        tag = " ⚠️期貨型" if v["futures_type"] else ""
        print(f"{c:<8}{v['prem_pct']:>+8.2f}{v['price']:>9.2f}{v['inav']:>9.2f}  {v['name'][:18]}{tag}")
    print("〔最高溢價〕")
    for c, v in rows[-a.top:][::-1]:
        tag = " ⚠️期貨型(申贖受限陷阱高風險)" if v["futures_type"] else ""
        print(f"{c:<8}{v['prem_pct']:>+8.2f}{v['price']:>9.2f}{v['inav']:>9.2f}  {v['name'][:18]}{tag}")


if __name__ == "__main__":
    main()
