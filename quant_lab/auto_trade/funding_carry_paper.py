"""Crypto 資金費率套利 paper 前測(Delvin 2026-07-27 拍板「要」;家規=先模擬考再正式考)。

規格(凍結 2026-07-27,不得調參):
- 虛擬底倉 US$15,000(≈NT$48萬,300萬資金池的閒置端);BTC 單一標的(研究驗證主場)
- 部位規則:近7日平均 funding > 0 → 持有(現貨多+永續空 1x delta中性);否則空手
- 收益:持有期間每個 8h funding × notional;轉換部位成本=0.15% notional(taker 現貨+永續)
- 資料:Binance 公開 API(fundingRate,無金鑰);帳本 .funding_carry/ledger.jsonl
- 60 天後對照研究基準(+4.7%/年淨carry):偏離過大=執行/資料問題,查因
真錢上線前置(只有 Delvin 能做):交易所開戶+API key+入金;paper 驗過執行前不動真錢。
用法:python3 funding_carry_paper.py(winrig cron 每晚)
"""
import os
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, ".funding_carry")
LEDGER = os.path.join(DIR, "ledger.jsonl")
NOTIONAL = 15_000.0
SWITCH_COST = 0.0015
SYM = "BTCUSDT"


def fetch_recent(limit=60):
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={SYM}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read().decode())
    return [(int(x["fundingTime"]), float(x["fundingRate"])) for x in rows]


def load_ledger():
    try:
        return [json.loads(l) for l in open(LEDGER, encoding="utf-8")]
    except FileNotFoundError:
        return []


def main():
    os.makedirs(DIR, exist_ok=True)
    evs = load_ledger()
    last_ts = evs[-1]["last_ts"] if evs else 0
    pos = evs[-1]["pos"] if evs else 0
    cum = evs[-1]["cum_usd"] if evs else 0.0
    rates = fetch_recent()
    new = [(t, r) for t, r in rates if t > last_ts]
    if not new and evs:
        print("無新 funding 期,收工")
        return
    avg7 = sum(r for _, r in rates[-21:]) / max(1, len(rates[-21:]))  # 7天×3期
    want = 1 if avg7 > 0 else 0
    carry = sum(r for _, r in new) * NOTIONAL if pos else 0.0
    cost = SWITCH_COST * NOTIONAL if want != pos else 0.0
    cum += carry - cost
    ev = {"date": datetime.date.today().isoformat(), "sym": SYM,
          "n_periods": len(new), "avg7_8h": round(avg7, 6),
          "pos": want, "carry_usd": round(carry, 2), "cost_usd": round(cost, 2),
          "cum_usd": round(cum, 2), "last_ts": rates[-1][0] if rates else last_ts}
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")
    ann = ""
    if evs:
        d0 = datetime.date.fromisoformat(evs[0]["date"])
        days = max(1, (datetime.date.today() - d0).days)
        ann = f" 年化 {cum / NOTIONAL / days * 365:+.1%}"
    print(f"carry paper:{'持有' if want else '空手'} 新期{len(new)} "
          f"本期 {carry - cost:+.2f} 累積 {cum:+.2f} USD{ann}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"funding_carry_paper 跳過本次:{type(e).__name__} {e}")
