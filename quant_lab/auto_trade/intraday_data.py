"""Shioaji TXFR1 1分K 落地管線:逐月抓 → .tx1m/ 磁碟快取(json.gz),中斷可續。
回補深度實測約 1.5 年+(2025-01 起有;更早 404)。含夜盤,研究端自行過濾時段。
注意 API 日流量 500MB,抓過的月份不重抓(當月除外)。
用法:python3 intraday_data.py [--start 2025-01]
"""
import os
import json
import gzip
import time
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, ".tx1m")


def month_path(key):
    return os.path.join(DIR, f"{key}.json.gz")


def fetch_all(start="2025-01"):
    from shioaji_adapter import _load_env
    _load_env()
    import shioaji as sj
    api = sj.Shioaji()
    api.login(api_key=os.environ["SHIOAJI_API_KEY"],
              secret_key=os.environ["SHIOAJI_SECRET_KEY"], fetch_contract=True)
    time.sleep(4)
    r1 = api.Contracts.Futures.TXF["TXFR1"]
    os.makedirs(DIR, exist_ok=True)
    today = datetime.date.today().isoformat()

    # 坑:kbars 起訖若落在非交易日會 404 → 分段一律對齊交易日(來源:tx_data 日曆)
    import sys
    sys.path.insert(0, HERE)
    import tx_data
    tdays = [b["date"] for b in tx_data.load("2020-01-01")
             if f"{start}-01" <= b["date"] <= today]
    # 雙上限:≤15 交易日 且 ≤28 曆日(春節等長假會讓 15 交易日跨過 30 曆日 → 400)
    chunks, cur = [], []
    for d in tdays:
        if cur and (len(cur) >= 15 or
                    (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(cur[0])).days > 27):
            chunks.append(cur)
            cur = []
        cur.append(d)
    if cur:
        chunks.append(cur)

    by_month = {}
    for ch in chunks:
        t0 = time.time()
        try:
            kb = api.kbars(r1, start=ch[0], end=ch[-1])
            rows = list(zip([int(t) for t in kb.ts], kb.Open, kb.High, kb.Low, kb.Close, kb.Volume))
        except Exception as ex:
            print(f"  {ch[0]}~{ch[-1]}: {'超出回補深度' if 'not found' in str(ex).lower() else ex}")
            continue
        for r in rows:
            key = datetime.datetime.fromtimestamp(r[0] / 1e9).strftime("%Y-%m")
            by_month.setdefault(key, {})[r[0]] = r
        print(f"  {ch[0]}~{ch[-1]}: {len(rows):,} 根({time.time()-t0:.1f}s)")
    for key, d in sorted(by_month.items()):
        with gzip.open(month_path(key), "wt") as f:
            json.dump(sorted(d.values()), f)
    print("用量:", api.usage())
    api.logout()


def load(day_session_only=True):
    """讀全部快取 → [(datetime, o, h, l, c, v)] 排序;day_session_only=只留 08:45-13:45。"""
    out = []
    if not os.path.isdir(DIR):
        return out
    for fn in sorted(os.listdir(DIR)):
        if not fn.endswith(".json.gz"):
            continue
        with gzip.open(os.path.join(DIR, fn), "rt") as f:
            for ts, o, h, l, c, v in json.load(f):
                # Shioaji kbar ts=台北牆鐘時間直接當 epoch 存 → 用 utcfromtimestamp 取回字面時間
                t = datetime.datetime.utcfromtimestamp(ts / 1e9)
                if day_session_only:
                    hm = t.hour * 60 + t.minute
                    if not (8 * 60 + 45 <= hm <= 13 * 60 + 45):
                        continue
                out.append((t, o, h, l, c, v))
    out.sort(key=lambda x: x[0])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01")
    a = ap.parse_args()
    fetch_all(a.start)
    bars = load()
    if bars:
        days = len({b[0].date() for b in bars})
        print(f"\n日盤 1分K 共 {len(bars):,} 根,{days} 個交易日({bars[0][0].date()} → {bars[-1][0].date()})")
