"""CB 掛牌警戒器(2026-07-27,CB 執行計畫 v1.1 配套):
未掛牌便宜券一出現在 Shioaji 合約(=掛牌可交易)就推播,附限價上限——便宜度只存在於
掛牌初期,錯過窗口就沒了(實證:一詮七掛牌後市價 128.8,承銷價便宜度+64.7%→-92pt 反轉)。

watch 清單與限價上限(理論價下方留 margin,超過=便宜度已被吃,不追):
記在 WATCHLIST;掛牌偵測到後推播一次(state 防重),之後人工跑 cb.py <code> 核價再下單。
用法:python3 cb_listing_watch.py(winrig cron 平日 08:50)
"""
import os
import json
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".listing_watch_state.json")
sys.path.insert(0, os.path.join(HERE, "..", "quant_lab", "auto_trade"))

# code → (名稱, 債券代碼, 限價上限=理論價−安全邊際, 備註)
WATCHLIST = {
    "47642": ("雙鍵二", "47642", 110.0, "理論117.1/承銷102;+67vol pt"),
    "84381": ("昶昕一", "84381", 101.0, "理論104.5/承銷100;+20.5vol pt;3億小規模單券減半"),
}


def push(msg):
    from paper_daily import push as _p
    _p(msg)


def main():
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        st = {"alerted": []}
    pending = {k: v for k, v in WATCHLIST.items() if k not in st["alerted"]}
    if not pending:
        print("watch 清單全數已掛牌/已通知,收工")
        return
    from shioaji_adapter import login_env
    api = login_env(simulation=False)
    time.sleep(3)
    for code, (name, bond, cap, note) in pending.items():
        c = None
        for ex in ("OTC", "TSE", "OES"):
            try:
                c = getattr(api.Contracts.Stocks, ex)[code]
                if c:
                    break
            except Exception:
                pass
        if c:
            msg = (f"💎 CB 掛牌警戒:{name}({code})已可交易!"
                   f"限價上限 {cap}(超過=便宜度被吃,不追)。{note}。"
                   f"下一步:python3 cb.py {code[:4]} 核實價後依執行計畫下單")
            print(msg)
            push(msg)
            st["alerted"].append(code)
        else:
            print(f"{name}({code}) 尚未掛牌")
    api.logout()
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"cb_listing_watch 跳過本次:{type(e).__name__} {e}")
