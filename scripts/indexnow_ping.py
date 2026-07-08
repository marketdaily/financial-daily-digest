"""IndexNow ping — 部署後通知 Bing/Yandex 系搜尋引擎收錄新頁面。

key 檔 = docs/<32hex>.txt(內容=檔名),部署後在站根可驗證。
用法:
  python3 scripts/indexnow_ping.py                # 最新 2 份公版日報 + 高更動核心頁
  python3 scripts/indexnow_ping.py --recent 5
  python3 scripts/indexnow_ping.py --urls https://marketdaily.ai/pricing
  python3 scripts/indexnow_ping.py --dry
失敗不 raise(exit 0),不能影響日報 pipeline。
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HOST = "marketdaily.ai"
BASE = f"https://{HOST}"
ENDPOINT = "https://api.indexnow.org/indexnow"
CORE = ["/", "/track-record", "/blog/"]
KEY_RE = re.compile(r"^[0-9a-f]{32}$")
DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})\.html$")


def find_key():
    for p in DOCS.glob("*.txt"):
        if KEY_RE.match(p.stem) and p.read_text().strip() == p.stem:
            return p.stem
    return None


def recent_digest_urls(n):
    digests = []
    for p in (DOCS / "output").glob("digest_*.html"):
        if "_personal_" in p.name:
            continue
        m = DATE_RE.search(p.name)
        if m:
            digests.append((m.group(1), p.stem))
    return [f"{BASE}/output/{stem}" for _, stem in sorted(digests, reverse=True)[:n]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=2)
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    key = find_key()
    if not key:
        print("[indexnow] key 檔不存在,略過")
        return 0

    urls = args.urls or ([BASE + p for p in CORE] + recent_digest_urls(args.recent))
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"{BASE}/{key}.txt",
        "urlList": urls,
    }
    if args.dry:
        print(json.dumps(payload, indent=2))
        return 0

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[indexnow] {resp.status} — {len(urls)} URLs 已提交")
    except Exception as e:
        print(f"[indexnow] 提交失敗(不影響流程): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
