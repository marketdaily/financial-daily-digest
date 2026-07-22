"""每日收盤前排行快照(cron 13:50 台股交易日):Shioaji scanners 5 榜 top50 →
intel/rank_scan_ledger.jsonl(一天一行)。訊號判讀在 intel/tw_rank_scanner.py(零依賴讀 ledger)。"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(os.path.dirname(HERE), "intel", "rank_scan_ledger.jsonl")
RANK_TYPES = {"change": "ChangePercentRank", "volume": "VolumeRank", "amount": "AmountRank",
              "range": "DayRangeRank", "tick": "TickCountRank"}


def _env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def capture(api):
    import shioaji as sj
    out = {}
    for key, tname in RANK_TYPES.items():
        st = getattr(sj.constant.ScannerType, tname)
        rows = []
        for d in api.scanners(scanner_type=st, count=50):
            prev = d.close - d.change_price
            rows.append({"code": d.code, "name": (d.name or "").strip(), "close": d.close,
                         "change_pct": round(d.change_price / prev * 100, 2) if prev else None,
                         "volume": d.total_volume})
        out[key] = rows
    return out


def main(out_path=None):
    path = out_path or LEDGER
    today = datetime.date.today().isoformat()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("date") == today:
                        print(f"{today} 已有紀錄,跳過(冪等)")
                        return 0
                except Exception:
                    continue
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"], fetch_contract=False)
    try:
        ranks = capture(api)
    finally:
        try:
            api.logout()
        except Exception:
            pass
    if not any(ranks.values()):
        print("scanners 全空(休市日?),不寫入")
        return 0
    entry = {"date": today, "captured_at": datetime.datetime.now().strftime("%H:%M"), "ranks": ranks}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"{today} 寫入 {sum(len(v) for v in ranks.values())} 列({path})")
    return 0


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    sys.exit(main(out))
