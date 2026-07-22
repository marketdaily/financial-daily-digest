"""看盤頁 intel 訊號燈推送:briefs/latest.json by_code(紅黃)→ worker KV watch:signals。
合規:訊號內容全體用戶免費同內容(個股功能不與付費掛鉤);cron 21:40(patrol 21:30 後)。"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = "https://api.marketdaily.ai"


def _env(path):
    d = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    except FileNotFoundError:
        pass
    return d


def main():
    try:
        brief = json.load(open(os.path.join(HERE, "briefs", "latest.json"), encoding="utf-8"))
    except Exception as ex:
        print(f"latest.json 讀取失敗:{ex}")
        return 1
    by_code = {}
    for code, items in (brief.get("by_code") or {}).items():
        keep = [{"source": it.get("source"), "level": it.get("level"), "signal": it.get("signal")}
                for it in items if it.get("level") in ("red", "yellow")]
        if keep:
            by_code[str(code).upper()] = keep
    token = os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or _env(
        os.path.join(os.path.dirname(HERE), ".env")).get("MARKETDAILY_INTERNAL_TOKEN", "")
    if not token:
        print("MARKETDAILY_INTERNAL_TOKEN 未設")
        return 1
    payload = json.dumps({"date": brief.get("date"), "by_code": by_code}).encode()
    req = urllib.request.Request(
        f"{WORKER}/internal/watch-signals", data=payload, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "User-Agent": "marketdaily-intel-push/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode())
    print(f"pushed {out.get('n_codes')} codes (date={brief.get('date')})")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
