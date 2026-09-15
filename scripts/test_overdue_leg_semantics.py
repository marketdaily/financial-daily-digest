#!/usr/bin/env python3
"""逾期告警的兩種「未生效」不可混為一談(2026-09-16)。

守的災難:`account_states` 回三態,語義各不相同——
    True  = 已生效
    False = 帳號在、簽署完成,但過檔沒生效  → 該問「是不是卡在系統過檔」
    None  = 永豐端根本查無此帳號           → 該問「這帳戶有沒有開成、有沒有掛進 API」
舊文案用 `is not True` 把 False 與 None 收成同一句「證券/期貨…仍未生效」,
於是實際狀態 {'stock': False, 'futopt': None} 時,老闆會拿著那句去問營業員
**一個從來沒掛上來的期貨帳號為什麼還沒生效**。這是「拿錯的句子去找人」第二種形狀
(第一種是已生效卻被寫進逾期,check_signed 第 2 輪 F6 已擋)。

判準對著災難寫:量的是「這句話會不會讓人問錯問題」,所以斷言看的是**文案分沒分開**,
不是「有沒有推播」。
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "quote_bridge"))
import check_signed as C  # noqa: E402

FAILS = []


def ck(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


def render(states, settled_legs=()):
    """只跑文案那一段,不碰檔案系統/不推播。"""
    sent = {}
    orig_push, orig_settled = C._try_push, C.settled
    orig_load, orig_save = C._load_watch, C._save_watch
    C._try_push = lambda msg, tok: (sent.setdefault("msg", msg), (True, ""))[1]
    C.settled = lambda k: k in settled_legs
    C._load_watch = lambda: ({"first_seen": "2026-07-30"}, None)
    C._save_watch = lambda st: None
    try:
        C.overdue_alert(states, date(2026, 9, 16), "tok")
    finally:
        C._try_push, C.settled = orig_push, orig_settled
        C._load_watch, C._save_watch = orig_load, orig_save
    return sent.get("msg", "")


def main():
    fn = getattr(C, "overdue_alert", None)
    if fn is None:
        cand = [n for n in dir(C) if "overdue" in n.lower()]
        print(f"FAIL: 找不到 overdue_alert(候選 {cand})")
        return 1

    # ① 生產當下的真實狀態:證券未生效 + 期貨查無此帳號
    m = render({"stock": False, "futopt": None})
    ck("有推出文案", bool(m), repr(m)[:80])
    ck("證券那半講「仍未生效」並指向過檔", "證券" in m and "未生效" in m and "過檔" in m, m[:120])
    ck("期貨那半講「查無此帳號」", "期貨" in m and "查無此帳號" in m, m[:160])
    ck("⭐ 兩者不可被寫成同一個『證券/期貨…未生效』", "證券/期貨自" not in m, m[:160])

    # ② 兩腿都只是未簽署 → 可以合併成一句(這時合併是對的)
    m2 = render({"stock": False, "futopt": False})
    ck("兩腿同為 False 時合併成一句", "證券/期貨自" in m2 and "查無此帳號" not in m2, m2[:120])

    # ③ 兩腿都查無帳號 → 只講查無,不講「過檔慢」
    m3 = render({"stock": None, "futopt": None})
    ck("兩腿同為 None 時只講查無此帳號", "查無此帳號" in m3 and "仍未生效" not in m3, m3[:140])

    # ④ 已落 marker 的腿不進文案(沿用既有不變量,不可因本次改動而失效)
    m4 = render({"stock": False, "futopt": None}, settled_legs=("stock",))
    ck("已生效的腿不進逾期文案", "證券" not in m4 and "期貨" in m4, m4[:140])

    # ⑤ 全部已生效 → 完全不推
    ck("全生效不推播", render({"stock": True, "futopt": True}) == "")

    # ⑥ 突變對照:把判準改回 `is not True`(舊寫法)⇒ ① 的關鍵斷言必須紅
    src = open(os.path.join(HERE, "quote_bridge", "check_signed.py"), encoding="utf-8").read()
    ck("⭐ 生產碼真的分開判 False 與 None(不是又退回 is not True)",
       "states.get(k) is False" in src and "states.get(k) is None" in src)

    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 條沒過:{FAILS}")
        return 1
    print("✅ 逾期文案三態語義全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
