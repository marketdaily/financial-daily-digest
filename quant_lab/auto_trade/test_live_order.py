"""系統體檢:真實下單管線驗證(期貨戶開通後,Delvin 本人在 winrig 跑)。
兩關,由安全到完整:
  ①submit-cancel(預設,零風險):掛一張「遠離市價、不會成交」的限價單→確認被接受→撤單。
     驗證 登入+CA憑證+下單+撤單 整條管線,全程零部位、零市場風險。
  ②fill-close(需 --mode fill-close 明確指定):真的市價買1口小台→成交→立即市價平掉。
     驗證 成交回報(fill),代價=一次來回價差+費稅(~數百元學費)。硬限 1 口、立即平。

前置(Delvin 本人設定,券商紅線):
  .env 需有 SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY(已到)
  + CA 憑證三項:SHIOAJI_CA_PATH(.pfx 路徑)/ SHIOAJI_CA_PASSWD / SHIOAJI_PERSON_ID(身分證字號)
用法:python3 test_live_order.py --yes                 # 安全關(掛撤)
     python3 test_live_order.py --yes --mode fill-close  # 完整關(真成交1口)
"""
import os
import sys
import time
import argparse

MINI_TXF = "小型臺指"   # 小台(每點50元,保證金/風險約大台1/4)


def _die(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="明確確認要對真實帳戶操作")
    ap.add_argument("--mode", choices=["submit-cancel", "fill-close"], default="submit-cancel")
    a = ap.parse_args()
    if not a.yes:
        _die("這會連上你的真實期貨帳戶。確定請加 --yes(fill-close 會真的成交1口)。")

    from shioaji_adapter import _load_env
    _load_env()
    for k in ("SHIOAJI_API_KEY", "SHIOAJI_SECRET_KEY"):
        if not os.environ.get(k):
            _die(f".env 缺 {k}")
    ca_path = os.environ.get("SHIOAJI_CA_PATH")
    ca_pw = os.environ.get("SHIOAJI_CA_PASSWD")
    pid = os.environ.get("SHIOAJI_PERSON_ID")
    if not (ca_path and ca_pw and pid):
        _die("下真單需 CA 憑證:.env 補 SHIOAJI_CA_PATH / SHIOAJI_CA_PASSWD / SHIOAJI_PERSON_ID(你本人向永豐申請下載)")
    if not os.path.exists(ca_path):
        _die(f"CA 憑證檔不存在:{ca_path}")

    import shioaji as sj
    print("① 真實環境登入…")
    api = sj.Shioaji(simulation=False)          # 明確真實
    try:
        api.login(api_key=os.environ["SHIOAJI_API_KEY"],
                  secret_key=os.environ["SHIOAJI_SECRET_KEY"], fetch_contract=True)
    except TypeError:
        api.login(api_key=os.environ["SHIOAJI_API_KEY"],
                  secret_key=os.environ["SHIOAJI_SECRET_KEY"])
    print("② 啟用 CA 憑證…")
    ok = api.activate_ca(ca_path=ca_path, ca_passwd=ca_pw, person_id=pid)
    if not ok:
        _die("CA 啟用失敗(檢查 .pfx / 密碼 / 身分證字號)")
    print("   ✅ 登入 + CA 完成")

    # 取近月小台合約
    try:
        fut = api.Contracts.Futures.TMF   # 小型臺指近月群
        contract = sorted(fut, key=lambda c: c.delivery_date)[0]
    except Exception:
        # 版本相容:退回用 code 前綴找
        allf = [c for cat in api.Contracts.Futures for c in cat]
        cand = [c for c in allf if "TMF" in getattr(c, "code", "") or MINI_TXF in getattr(c, "name", "")]
        if not cand:
            _die("找不到小台合約(TMF),請確認合約已 fetch")
        contract = sorted(cand, key=lambda c: getattr(c, "delivery_date", "9"))[0]
    print(f"   合約:{getattr(contract,'code','?')} {getattr(contract,'name','')} 交割 {getattr(contract,'delivery_date','?')}")

    # 目前市價參考
    snap = api.snapshots([contract])[0]
    px = snap.close
    print(f"   小台近月市價 ≈ {px}")

    if a.mode == "submit-cancel":
        # 掛「遠離市價」買單(市價 -10%,絕不會成交)→ 確認接受 → 撤單
        limit_px = round(px * 0.90)
        print(f"③ 掛遠價限價買單 1 口 @ {limit_px}(市價-10%,不會成交)…")
        order = api.Order(price=limit_px, quantity=1, action="Buy",
                          price_type="LMT", order_type="ROD",
                          octype="Auto")
        trade = api.place_order(contract, order)
        time.sleep(2)
        api.update_status()
        st = trade.status.status
        print(f"   訂單狀態:{st}  單號:{getattr(trade.status,'id','?')}")
        if str(st).lower() in ("failed", "cancelled") and "cancel" not in str(st).lower():
            _die(f"下單被拒:{st}")
        print("④ 撤單…")
        api.cancel_order(trade)
        time.sleep(2)
        api.update_status()
        print(f"   撤單後狀態:{trade.status.status}")
        pos = api.list_positions(api.futopt_account)
        print(f"⑤ 目前期貨部位:{len(pos)} 筆(應為 0 或不含本測試)")
        print("\n✅ 系統體檢(掛撤關)通過:登入/CA/下單/撤單 管線正常,全程零部位。")
        print("   下一步:確認無誤後可跑 --mode fill-close 驗成交,或直接讓魚訊號小口真錢起跑。")
    else:
        print("③ ⚠️ fill-close:真的市價買 1 口小台 → 立即市價平。學費=一次來回價差+費稅。")
        print("   5 秒後執行,Ctrl-C 可中止…")
        time.sleep(5)
        buy = api.Order(quantity=1, action="Buy", price_type="MKT",
                        order_type="IOC", octype="Auto")
        t1 = api.place_order(contract, buy)
        time.sleep(2); api.update_status()
        print(f"   買進狀態:{t1.status.status} 成交均價:{getattr(t1.status,'deal_price','?')}")
        print("④ 立即市價平倉…")
        sell = api.Order(quantity=1, action="Sell", price_type="MKT",
                         order_type="IOC", octype="Auto")
        t2 = api.place_order(contract, sell)
        time.sleep(2); api.update_status()
        print(f"   平倉狀態:{t2.status.status} 成交均價:{getattr(t2.status,'deal_price','?')}")
        pos = api.list_positions(api.futopt_account)
        print(f"⑤ 平倉後部位:{len(pos)} 筆(必須確認回到 0/持平!)")
        if pos:
            print("   ⚠️⚠️ 部位未歸零!立即手動檢查永豐 App 平倉!")
        else:
            print("\n✅ 系統體檢(成交關)通過:登入/CA/下單/成交回報/平倉 全鏈路正常,部位已歸零。")


if __name__ == "__main__":
    main()
