#!/usr/bin/env python3
"""Brevo 每日寄信用量守衛(2026-08-09,老闆:天機不可與 MarketDaily 搶額度)。

免費層 300 封/日共池(日報+歡迎信+天機報告信)。每日 21:15 查當日 requests,
≥ 門檻(預設 200)即推播 admin 預警,留升級/分家的提前量;平日完全靜默。
唯讀統計端點,無任何寄信能力。
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

MD_REPO = Path.home() / "Delvin-agent"
THRESHOLD = int(os.environ.get("EMAIL_QUOTA_ALERT_AT", "200"))
NOTIFY = [str(MD_REPO / ".venv" / "bin" / "python"),
          str(Path.home() / ".marketdaily-fallback" / "notify_admin.py")]


def env_val(key):
    for line in (MD_REPO / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/statistics/aggregatedReport?days=1",
        headers={"api-key": env_val("BREVO_API_KEY"), "User-Agent": "marketdaily-quota-guard/1.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    sent = int(d.get("requests") or 0)
    print(f"今日寄信 {sent} 封(門檻 {THRESHOLD}/300)")
    if sent >= THRESHOLD:
        subprocess.run(NOTIFY + [
            f"📮 Brevo 今日已寄 {sent}/300 封(免費層)——天機與 MarketDaily 共池,"
            f"逼近上限。選項:①Brevo 升級 ②天機分家(CF Email Sending 需 Workers Paid $5/月)"],
            timeout=60, capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
