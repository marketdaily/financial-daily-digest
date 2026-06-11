"""LINE 推播給 admin(經 alert-worker /internal/admin-line-push)。CI 與本機共用。
用法:python3 scripts/notify_line.py "訊息" 或 echo 訊息 | python3 scripts/notify_line.py -
"""
import json
import os
import sys
import urllib.request

WORKER = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                        "https://marketdaily-alert-worker.delvin-12345678.workers.dev")


def push(message: str) -> bool:
    tok = os.environ.get("MARKETDAILY_ALERT_TOKEN")
    if not tok:
        print("(skip LINE:MARKETDAILY_ALERT_TOKEN 未設)")
        return False
    req = urllib.request.Request(
        f"{WORKER.rstrip('/')}/internal/admin-line-push",
        data=json.dumps({"message": message[:4900]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"LINE push status={resp.status}")
        return resp.status == 200


if __name__ == "__main__":
    msg = sys.stdin.read() if (len(sys.argv) > 1 and sys.argv[1] == "-") else " ".join(sys.argv[1:])
    if not msg.strip():
        sys.exit("empty message")
    push(msg.strip())
