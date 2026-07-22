"""台股基本面日更(cron 14:35 平日):TWSE BWIBBU_ALL(上市)+TPEx peratio_analysis(上櫃)
→ {code:{pe,dy,pb}} → worker KV watch:fundamentals(看盤頁個股詳情用)。官方免費源,免 token。"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = "https://api.marketdaily.ai"
TWSE = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"


def _env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception:
        # TPEx 憑證鏈缺 SKI 擴充,python3.14 嚴格驗證拒收(curl 的 CA 處理可過)→ subprocess fallback
        import subprocess
        out = subprocess.run(["curl", "-s", "--max-time", "30", "-H", "User-Agent: Mozilla/5.0",
                              "-H", "Accept: application/json", url], capture_output=True, timeout=40)
        return json.loads(out.stdout.decode())


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def main():
    by_code, date = {}, None
    try:
        for r in _fetch(TWSE):
            c = str(r.get("Code", "")).strip()
            if c:
                date = r.get("Date") or date
                by_code[c] = {"pe": _num(r.get("PEratio")), "dy": _num(r.get("DividendYield")), "pb": _num(r.get("PBratio"))}
    except Exception as ex:
        print(f"TWSE 失敗:{ex}")
    try:
        for r in _fetch(TPEX):
            c = str(r.get("SecuritiesCompanyCode", "")).strip()
            if c:
                by_code[c] = {"pe": _num(r.get("PriceEarningRatio")), "dy": _num(r.get("YieldRatio")), "pb": _num(r.get("PriceBookRatio"))}
    except Exception as ex:
        print(f"TPEx 失敗:{ex}")
    if not by_code:
        print("兩源全空,不推送")
        return 1
    token = os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or _env(os.path.join(ROOT, ".env")).get("MARKETDAILY_INTERNAL_TOKEN", "")
    req = urllib.request.Request(
        f"{WORKER}/internal/watch-fundamentals",
        data=json.dumps({"date": date, "by_code": by_code}).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "User-Agent": "marketdaily-fundamentals-push/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read().decode())
    print(f"pushed {out.get('n_codes')} codes")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
