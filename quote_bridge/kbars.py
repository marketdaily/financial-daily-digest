"""台股 1 分 K 歷史資料積木(Shioaji kbars,2020-03-02 起)——回測資料源升級用。
月分片 CSV 快取,重跑只補缺月;每日行情流量 500MB 上限,剩 <60MB 自動停止。
用法:
  ~/.venvs/shioaji-bridge/bin/python kbars.py 2330 --start 2024-01 --end 2024-03
  ~/.venvs/shioaji-bridge/bin/python kbars.py 2330 --verify   # 抓近 5 日與 snapshot 對帳
資料落點:~/Delvin-agent/quant_lab/data/kbars/{sym}/{YYYY-MM}.csv(ts,open,high,low,close,volume,amount)
"""
import argparse
import calendar
import csv
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "quant_lab", "data", "kbars")
MIN_REMAIN_BYTES = 60 * 1024 * 1024


def _env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def login():
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"],
              fetch_contract=True, contracts_timeout=60000)
    return api


def usage_guard(api):
    try:
        u = api.usage()
        if u.remaining_bytes < MIN_REMAIN_BYTES:
            print(f"⚠️ 今日行情流量剩 {u.remaining_bytes//1024//1024}MB(<60MB 地板),停止抓取")
            return False
    except Exception:
        pass
    return True


def month_iter(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def fetch_month(api, sym, ym):
    """抓一個月 1 分 K,寫 CSV;已存在且非當月跳過。回傳寫入筆數(-1=跳過)。"""
    outdir = os.path.join(DATA, sym)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{ym}.csv")
    cur_ym = datetime.date.today().strftime("%Y-%m")
    if os.path.exists(out) and ym != cur_ym:
        return -1
    if not usage_guard(api):
        raise SystemExit(2)
    y, m = map(int, ym.split("-"))
    start = f"{ym}-01"
    end = f"{ym}-{calendar.monthrange(y, m)[1]:02d}"
    contract = api.Contracts.Stocks[sym]
    if contract is None:
        raise SystemExit(f"找不到合約:{sym}")
    kb = api.kbars(contract, start=start, end=end)
    rows = list(zip(kb.ts, kb.Open, kb.High, kb.Low, kb.Close, kb.Volume, kb.Amount))
    tmp = out + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume", "amount"])
        for ts, o, h, lo, c, v, a in rows:
            # Shioaji kbars ts=台灣牆鐘時間存成 UTC epoch(2026-07-22 實測:09:01 K 棒 fromtimestamp 顯示 17:01)
            iso = datetime.datetime.fromtimestamp(ts / 1e9, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
            w.writerow([iso, o, h, lo, c, v, a])
    os.replace(tmp, out)
    return len(rows)


def verify(api, sym):
    """近 5 日 kbars 最後一根收盤 vs snapshot 現價對帳(容差:盤中會動,只驗同量級)。"""
    today = datetime.date.today()
    kb = api.kbars(api.Contracts.Stocks[sym],
                   start=(today - datetime.timedelta(days=5)).isoformat(), end=today.isoformat())
    if not kb.ts:
        print("kbars 無資料")
        return 1
    last_close = kb.Close[-1]
    last_ts = datetime.datetime.fromtimestamp(kb.ts[-1] / 1e9, datetime.timezone.utc)
    snap = api.snapshots([api.Contracts.Stocks[sym]])[0]
    drift = abs(last_close - snap.close) / snap.close * 100 if snap.close else 999
    print(f"{sym} kbars 最後一根:{last_ts:%m-%d %H:%M} close={last_close} | snapshot={snap.close} | 差 {drift:.2f}%")
    print("✅ 對帳通過(同量級)" if drift < 3 else "⚠️ 偏差 >3%,檢查資料")
    return 0 if drift < 3 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sym")
    ap.add_argument("--start", help="YYYY-MM")
    ap.add_argument("--end", help="YYYY-MM")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    api = login()
    try:
        if args.verify:
            return verify(api, args.sym)
        if not (args.start and args.end):
            ap.error("需要 --start/--end(YYYY-MM)或 --verify")
        total = 0
        for ym in month_iter(args.start, args.end):
            n = fetch_month(api, args.sym, ym)
            print(f"{args.sym} {ym}: {'快取已存在,跳過' if n < 0 else f'{n} 根'}")
            total += max(n, 0)
        print(f"完成,共 {total} 根 → {os.path.join(DATA, args.sym)}")
        return 0
    finally:
        try:
            api.logout()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
