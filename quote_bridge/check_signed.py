"""永豐 API 簽署生效偵測器(cron 每小時 08-17 平日):list_positions 一旦不再 406 →
web push 通知 admin+落 .signed_ok 標記自動停走(一次性過渡偵測,生效後 cron 變 no-op)。"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(HERE, ".signed_ok")
ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"


def _env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def push(msg, token):
    req = urllib.request.Request(
        f"{ALERT_WORKER}/internal/admin-line-push",
        data=json.dumps({"message": msg}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200


def main():
    if os.path.exists(MARKER):
        return 0
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"], fetch_contract=False)
    try:
        pos = api.list_positions(api.stock_account)
    except Exception as ex:
        if "406" in str(ex) or "Not Acceptable" in str(ex):
            print("尚未生效(仍406)")
            return 0
        raise
    finally:
        try:
            api.logout()
        except Exception:
            pass
    open(MARKER, "w").write("signed ok\n")
    n = len(pos)
    tok = E.get("MARKETDAILY_ALERT_TOKEN", "")
    msg = f"✅ 永豐 API 簽署生效!帳務已解鎖(現有 {n} 檔部位),看盤頁「我的部位」會自動顯示。此偵測器已自動停走。"
    if tok:
        push(msg, tok)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
