"""永豐 API 簽署生效偵測器(cron 每小時 08-17 平日)。

判準=登入後帳號物件的 `signed` 欄位(永豐權威回報),不是猜 406——406 只說「不給你」,
signed 欄位才分得出證券/期貨各自的狀態,也才能在只解鎖一半時講清楚缺哪一邊。
證券解鎖即落 .signed_ok 標記自動停走(一次性過渡偵測,生效後 cron 變 no-op)。
"""
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
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "User-Agent": "marketdaily-internal/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200


def account_states(accounts):
    """{'stock': True/False/None, 'futopt': True/False/None} —— None=永豐根本沒掛這個帳號。"""
    out = {"stock": None, "futopt": None}
    for a in accounts:
        kind = "futopt" if "Fut" in type(a).__name__ else "stock"
        out[kind] = bool(getattr(a, "signed", False))
    return out


def build_message(states, n_pos):
    parts = []
    for kind, label in (("stock", "證券"), ("futopt", "期貨")):
        v = states[kind]
        parts.append(f"{label}:" + ("✅已生效" if v is True else "❌未生效" if v is False else "⚠️API 未掛此帳號"))
    line = " / ".join(parts)
    msg = f"✅ 永豐 API 簽署生效!帳務已解鎖(現有 {n_pos} 檔部位),看盤頁「我的部位」會自動顯示。{line}。此偵測器已自動停走。"
    if states["futopt"] is not True:
        msg += "\n⚠️ 期貨端尚未解鎖(證券/期貨需分開簽署+分開測試),期貨帳務仍取不到。"
    return msg


def main():
    if os.path.exists(MARKER):
        return 0
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    accounts = api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"],
                         fetch_contract=False)
    states = account_states(accounts)
    try:
        if states["stock"] is not True:
            print(f"尚未生效 states={states}")
            return 0
        pos = api.list_positions(api.stock_account)
    finally:
        try:
            api.logout()
        except Exception:
            pass
    open(MARKER, "w").write(f"signed ok {states}\n")
    msg = build_message(states, len(pos))
    tok = E.get("MARKETDAILY_ALERT_TOKEN", "")
    if tok:
        push(msg, tok)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
