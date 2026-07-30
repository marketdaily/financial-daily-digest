"""永豐 API 簽署生效偵測器(cron 每小時 08-17 平日)。

判準=登入後帳號物件的 `signed` 欄位(永豐權威回報),不是猜 406——406 只說「不給你」,
signed 欄位才分得出證券/期貨各自的狀態,也才能在只解鎖一半時講清楚缺哪一邊。
證券解鎖即落 .signed_ok 標記自動停走(一次性過渡偵測,生效後 cron 變 no-op)。
"""
import json
import os
import sys
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(HERE, ".signed_ok")
WATCH = os.path.join(HERE, ".signed_watch.json")
OVERDUE_BIZ_DAYS = 2
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


def biz_days_between(a, b):
    """a→b 之間的工作日數(不含 a 當天)。過檔是營業日批次,用日曆天會在週末誤報。"""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def overdue_alert(states, today, tok):
    """過檔逾期主動告警——沒生效就靜默 = 沉默的守衛 = 沒有守衛。只推一次,不洗頻。"""
    try:
        st = json.load(open(WATCH))
    except Exception:
        st = {}
    first = date.fromisoformat(st.get("first_seen", today.isoformat()))
    st.setdefault("first_seen", first.isoformat())
    if not st.get("alerted") and biz_days_between(first, today) >= OVERDUE_BIZ_DAYS:
        pending = [label for k, label in (("stock", "證券"), ("futopt", "期貨"))
                   if states[k] is not True]
        msg = (f"⚠️ 永豐 API 過檔逾期:{'/'.join(pending)}自 {first} 起已過 "
               f"{biz_days_between(first, today)} 個營業日仍未生效(簽署+測試皆已完成)。"
               "該找營業員 Norris 查是否卡在系統過檔。")
        if tok:
            try:
                push(msg, tok)
                st["alerted"] = True
            except Exception as ex:
                print("push failed:", ex)
        print(msg)
    json.dump(st, open(WATCH, "w"))


def main():
    if os.path.exists(MARKER):
        return 0
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    accounts = api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"],
                         fetch_contract=False)
    states = account_states(accounts)
    tok = E.get("MARKETDAILY_ALERT_TOKEN", "")
    try:
        if states["stock"] is not True:
            print(f"尚未生效 states={states}")
            overdue_alert(states, date.today(), tok)
            return 0
        pos = api.list_positions(api.stock_account)
    finally:
        try:
            api.logout()
        except Exception:
            pass
    open(MARKER, "w").write(f"signed ok {states}\n")
    msg = build_message(states, len(pos))
    if tok:
        push(msg, tok)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
