#!/usr/bin/env python3
"""bridge.py 純函數零網路測試(近月選擇/ATM 窗口/n 解析/ts 正規化/cp 正規化/snap_row)。

用法: python3 quote_bridge/test_bridge_pure.py   (exit 0=全過;不碰網路、不需 shioaji)
"""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridge

fails = []


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def fut(code, dd):
    return NS(code=code, delivery_date=dd)


# --- norm_snap_ts:牆鐘偽 epoch ns → 真 epoch 秒(-8h;實測樣本=2026-07-22 13:35:40 台北) ---
check("norm_snap_ts 實測樣本", bridge.norm_snap_ts(1784727340870000000) == 1784698540)
check("norm_snap_ts 0→None", bridge.norm_snap_ts(0) is None)
check("norm_snap_ts None→None", bridge.norm_snap_ts(None) is None)

# --- pick_near_next:排除 R1/R2、依 delivery_date 排序(1.5.6 實測群含 R1/R2 且日期與真月重複) ---
grp = [fut("TXFR1", "2026/08/19"), fut("TXFL6", "2026/12/16"), fut("TXFH6", "2026/08/19"),
       fut("TXFR2", "2026/09/16"), fut("TXFI6", "2026/09/16")]
near, nxt = bridge.pick_near_next(grp)
check("near=TXFH6(R1 同日期不搶位)", near.code == "TXFH6")
check("next=TXFI6", nxt.code == "TXFI6")
near, nxt = bridge.pick_near_next([fut("CDFH6", "2026/08/19")])
check("只剩一個月→next None", near.code == "CDFH6" and nxt is None)
near, nxt = bridge.pick_near_next([fut("TXFR1", "2026/08/19"), fut("TXFR2", "2026/09/16")])
check("全是連續合約→(None,None)", near is None and nxt is None)
near, nxt = bridge.pick_near_next([fut("XXFH6", ""), fut("XXFI6", "2026/09/16")])
check("空 delivery_date 被濾掉", near.code == "XXFI6" and nxt is None)
check("空群→(None,None)", bridge.pick_near_next([]) == (None, None))

# --- pick_atm_window ---
ss = [44600.0, 44700.0, 44800.0, 44900.0, 45000.0]
atm, win = bridge.pick_atm_window(ss, 44825.78, 1)
check("atm=最近履約價", atm == 44800.0)
check("窗口 ±1 檔", win == [44700.0, 44800.0, 44900.0])
atm, win = bridge.pick_atm_window(ss, 44850.0, 1)
check("tie 取低履約價", atm == 44800.0)
atm, win = bridge.pick_atm_window(ss, 44610.0, 3)
check("下緣 clamp 不越界", atm == 44600.0 and win == ss[0:4])
atm, win = bridge.pick_atm_window(ss, 99999.0, 2)
check("上緣 clamp", atm == 45000.0 and win == ss[2:])
atm, win = bridge.pick_atm_window(ss, 44800.0, 0)
check("n=0→只有 ATM", win == [44800.0])
atm, win = bridge.pick_atm_window({44800.0, 44700.0, 44800.0}, 44790.0, 8)
check("set 去重+排序", atm == 44800.0 and win == [44700.0, 44800.0])
check("無 spot→(None,[])", bridge.pick_atm_window(ss, None, 8) == (None, []))
check("spot=0→(None,[])(定不了 ATM)", bridge.pick_atm_window(ss, 0.0, 8) == (None, []))
check("空 strikes→(None,[])", bridge.pick_atm_window([], 44800.0, 8) == (None, []))

# --- parse_n 邊界 ---
check("n 未給→8", bridge.parse_n(None) == 8)
check("n 空字串→8", bridge.parse_n("") == 8)
check("n=0 合法", bridge.parse_n("0") == 0)
check("n=20 合法", bridge.parse_n("20") == 20)
check("n=21→截 20", bridge.parse_n("21") == 20)
check("n=999→截 20", bridge.parse_n("999") == 20)
check("n=-1→None", bridge.parse_n("-1") is None)
check("n=abc→None", bridge.parse_n("abc") is None)
check("n=8.5→None", bridge.parse_n("8.5") is None)
check("n=²(isdigit 陷阱)→None", bridge.parse_n("²") is None)

# --- norm_cp ---
check("enum value C", bridge.norm_cp(NS(value="C")) == "C")
check("enum value P", bridge.norm_cp(NS(value="P")) == "P")
check("字串 Call", bridge.norm_cp("Call") == "C")
check("字串 OptionRight.Put", bridge.norm_cp("OptionRight.Put") == "P")
check("垃圾→None", bridge.norm_cp("x") is None)

# --- snap_row:欄位對映+ts 走 norm_snap_ts ---
sn = NS(code="TXFH6", close=44631.0, buy_price=44621.0, sell_price=44627.0,
        total_volume=65896, ts=1784727340870000000)
r = bridge.snap_row(sn)
check("snap_row 欄位", r == {"code": "TXFH6", "price": 44631.0, "bid": 44621.0,
                            "ask": 44627.0, "volume": 65896, "ts": 1784698540})
sn.ts = 0
check("snap_row ts=0→None", bridge.snap_row(sn)["ts"] is None)

print()
if fails:
    print(f"FAIL {len(fails)}: {fails}")
    sys.exit(1)
print("ALL PASS")
