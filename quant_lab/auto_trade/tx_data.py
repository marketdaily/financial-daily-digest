"""FinMind 免費層 → 台指期(TX)連續近月日線,餵引擎跑真資料回測(不用等 Shioaji)。

- 只取日盤(trading_session=position)、排除價差合約(contract_date 含 '/')
- 換月:每日取成交量最大的單一合約(標準 volume roll)
- ⚠️ 換月日有跳價未回溯調整(back-adjust);TX 基差小,對趨勢策略影響有限,先誠實標注
- 磁碟快取 .tx_daily.json;--refresh 重抓
用法:python3 tx_data.py --start 2020-01-01
"""
import os
import json
import argparse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".tx_daily.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def fetch_tx(start, end=None):
    url = f"{FINMIND}?dataset=TaiwanFuturesDaily&data_id=TX&start_date={start}"
    if end:
        url += f"&end_date={end}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode()).get("data", [])


def continuous_near_month(rows):
    """每日挑成交量最大的單一合約 → [{date, open, high, low, close, volume, contract}]"""
    by_date = {}
    for x in rows:
        cd = x.get("contract_date", "")
        if "/" in cd or x.get("trading_session") != "position":
            continue
        if not x.get("close"):
            continue
        d = x["date"]
        if d not in by_date or x.get("volume", 0) > by_date[d].get("volume", 0):
            by_date[d] = x
    out = []
    for d in sorted(by_date):
        x = by_date[d]
        out.append({"date": d, "open": x["open"], "high": x["max"], "low": x["min"],
                    "close": x["close"], "volume": x["volume"],
                    "contract": x["contract_date"]})
    return out


def load(start="2020-01-01", refresh=False):
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("start") == start:
            return c["bars"]
    bars = continuous_near_month(fetch_tx(start))
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump({"start": start, "bars": bars}, f, ensure_ascii=False)
    return bars


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    bars = load(a.start, a.refresh)
    rolls = sum(1 for i in range(1, len(bars)) if bars[i]["contract"] != bars[i - 1]["contract"])
    print(f"連續近月日線:{len(bars)} 根({bars[0]['date']} → {bars[-1]['date']}),換月 {rolls} 次")
    print("最新5根:")
    for b in bars[-5:]:
        print(f"  {b['date']} {b['contract']} O{b['open']:.0f} H{b['high']:.0f} "
              f"L{b['low']:.0f} C{b['close']:.0f} V{b['volume']:,}")
