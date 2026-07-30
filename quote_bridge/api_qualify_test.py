"""永豐 API 開通測試(simulation 模式的 login + place_order),cron 每工作日 08:05 跑到過為止。

背景:Delvin 已在簽署中心簽署,但帳號仍 signed=false——永豐開通是兩步,簽署之外還要在
模擬環境留下登入測試與下單測試紀錄(約 5 分鐘審核)。本腳本補的就是第二步。
證券/期貨各別測試、各自落 marker;期貨帳號若永豐根本沒掛上(=期貨那份還沒簽署)就跳過並回報。
測試單一律掛跌停價,且模擬環境不進真實市場——不會成交、不動真錢。
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
M_STOCK = os.path.join(HERE, ".qualify_stock_done")
M_FUTOPT = os.path.join(HERE, ".qualify_futopt_done")
ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"
TEST_STOCK = "2330"
REVIEW_WAIT_SEC = 330


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


def in_test_window(now):
    """永豐測試服務:週一至五 08:00~20:00(18-20 限台灣IP)。留 20 分鐘尾巴給審核。"""
    return now.weekday() < 5 and 8 <= now.hour and (now.hour, now.minute) < (19, 40)


def order_stock(api, sj):
    contract = api.Contracts.Stocks[TEST_STOCK]
    order = api.Order(
        price=contract.limit_down, quantity=1, action=sj.Action.Buy,
        price_type=sj.StockPriceType.LMT, order_type=sj.OrderType.ROD,
        account=api.stock_account)
    return api.place_order(contract, order)


def _front_month(api):
    """近月 TXF。排除 R1/R2 連續月合約(那是行情用的合成商品,不可下單)。"""
    fut = api.Contracts.Futures["TXF"]
    mapping = getattr(fut, "_code2contract", None) or {}
    codes = sorted(c for c in mapping if not c.endswith(("R1", "R2")))
    return mapping[codes[0]] if codes else None


def order_futopt(api, sj):
    contract = _front_month(api)
    if contract is None:
        raise RuntimeError("找不到 TXF 合約")
    order = api.Order(
        price=contract.limit_down, quantity=1, action=sj.Action.Buy,
        price_type=sj.FuturesPriceType.LMT, order_type=sj.OrderType.ROD,
        octype=sj.FuturesOCType.Auto, account=api.futopt_account)
    return api.place_order(contract, order)


def live_signed_states():
    """正式模式回查權威狀態,沿用偵測器同一支判準函式。"""
    import check_signed
    import shioaji as sj
    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    api = sj.Shioaji(simulation=False)
    accounts = api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"],
                        fetch_contract=False)
    try:
        return check_signed.account_states(accounts)
    finally:
        try:
            api.logout()
        except Exception:
            pass


def claim_already_live(states):
    """已生效的那一邊直接落 marker——絕不對已 signed=true 的帳號再送測試單。"""
    claimed = []
    for key, marker, label in (("stock", M_STOCK, "證券"), ("futopt", M_FUTOPT, "期貨")):
        if states.get(key) is True and not os.path.exists(marker):
            open(marker, "w").write("already signed=true, test not needed\n")
            claimed.append(label)
    return claimed


def main():
    if os.path.exists(M_STOCK) and os.path.exists(M_FUTOPT):
        return 0
    now = datetime.now()
    if not in_test_window(now):
        print(f"不在永豐測試窗口(週一至五 08:00-19:40),現在 {now:%a %H:%M},跳過")
        return 0

    pre = live_signed_states()
    claim_already_live(pre)
    if os.path.exists(M_STOCK) and os.path.exists(M_FUTOPT):
        print(f"兩邊都已 signed=true,無需測試 states={pre}")
        return 0

    E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    import shioaji as sj
    api = sj.Shioaji(simulation=True)
    api.login(api_key=E["SINOPAC_API_KEY"], secret_key=E["SINOPAC_SECRET_KEY"],
              fetch_contract=True)
    done, failed, skipped = [], [], []
    try:
        if not os.path.exists(M_STOCK):
            try:
                t = order_stock(api, sj)
                open(M_STOCK, "w").write(f"{now:%F %T} {t.status.status}\n")
                done.append("證券")
            except Exception as ex:
                failed.append(f"證券下單測試失敗:{ex}")
        time.sleep(2)
        if not os.path.exists(M_FUTOPT):
            if getattr(api, "futopt_account", None) is None:
                skipped.append("期貨:API 端尚未掛上此帳號(2153016 已簽署+已自測,等永豐系統過檔)")
            else:
                try:
                    t = order_futopt(api, sj)
                    open(M_FUTOPT, "w").write(f"{now:%F %T} {t.status.status}\n")
                    done.append("期貨")
                except Exception as ex:
                    failed.append(f"期貨下單測試失敗:{ex}")
    finally:
        try:
            api.logout()
        except Exception:
            pass

    lines = [f"📋 永豐 API 開通測試({now:%m-%d %H:%M})"]
    if done:
        lines.append(f"✅ 已送出測試單:{'、'.join(done)}(模擬環境,跌停價,不成交)")
    if skipped:
        lines += [f"⏭️ {s}" for s in skipped]
    if failed:
        lines += [f"❌ {f}" for f in failed]

    if done:
        time.sleep(REVIEW_WAIT_SEC)
        try:
            states = live_signed_states()
            lines.append("審核後正式帳號狀態 → " + " / ".join(
                f"{label}:" + ("✅已生效" if states[k] is True else "❌仍未生效" if states[k] is False
                               else "⚠️未掛此帳號")
                for k, label in (("stock", "證券"), ("futopt", "期貨"))))
            if states["stock"] is not True:
                lines.append("證券仍 false 屬正常:永豐是隔日「系統過檔」才生效(營業員口徑),"
                             "非即時。測試紀錄已留,明早自動再查一次。")
        except Exception as ex:
            lines.append(f"⚠️ 回查 signed 失敗:{ex}")

    msg = "\n".join(lines)
    tok = E.get("MARKETDAILY_ALERT_TOKEN", "")
    if tok:
        try:
            push(msg, tok)
        except Exception as ex:
            print("push failed:", ex)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.exit(main())
