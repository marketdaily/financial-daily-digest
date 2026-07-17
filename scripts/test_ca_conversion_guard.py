#!/usr/bin/env python3
"""intel tw_margin/tw_sbl 公司行動守衛(ca_conversion_guard)迴歸測試。

背景(2026-07-17 訊號端 CA 污染稽核):margin/SBL 餘額以股數計,分割/減資在生效日
把既有部位原地換算 → 5 日變化率機械跳升 → 假 margin_surge/margin_plunge/sbl_* 訊號
(實錘:5536 2022-09-19 1:2 分割 raw +85% / 4967 2022-10-11 減資 raw -33%,調整後皆
不過門檻)。配股(除權)實證免疫:餘額在除權日與發放日皆不跳(3081/3128/5386 三重
證據,發放日 MarginPurchaseLimit 精確跳因子而餘額不動)。
守衛 v1=相鄰收盤 |變化|>10.5%(台股漲跌停物理上限)偵測原地換算 → suppress 為 plain。
守衛 v2(2026-07-17 驗證者第12案後):margin 側加 MarginPurchaseLimit 錨定——價格缺口
需限額單日|跳變|>5% 佐證(除息/興櫃/缺洞假缺口不再誤壓);限額單日下降>5%=減資專屬
簽名可獨立觸發(補 factor>0.905 小減資盲區);限額不可用退回 v1;util 錯位窗另擋。
SBL 側無錨定欄(quota 噪音大)維持 v1。
本檔凍結:①兩枚真實假訊號必被壓 ②配股有機訊號不可誤壓 ③rule 鍵語意 ④fail-open
⑤除息缺口不誤壓 ⑥髒資料不炸 ⑦小減資/util 錯位窗被壓。
fixture 除標注「合成」外全部取自 FinMind/Yahoo 真實歷史資料(離線,零網路)。

用法: python3 scripts/test_ca_conversion_guard.py   (exit 0=全過)
"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intel import tw_margin, tw_sbl

FX = json.loads(r'''{
"margin_5536": [
{
"date": "2022-08-24",
"MarginPurchaseTodayBalance": 287,
"ShortSaleTodayBalance": 22,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-08-25",
"MarginPurchaseTodayBalance": 291,
"ShortSaleTodayBalance": 20,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-08-26",
"MarginPurchaseTodayBalance": 311,
"ShortSaleTodayBalance": 20,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-08-29",
"MarginPurchaseTodayBalance": 313,
"ShortSaleTodayBalance": 20,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-08-30",
"MarginPurchaseTodayBalance": 366,
"ShortSaleTodayBalance": 27,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-08-31",
"MarginPurchaseTodayBalance": 372,
"ShortSaleTodayBalance": 8,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-01",
"MarginPurchaseTodayBalance": 388,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-02",
"MarginPurchaseTodayBalance": 507,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-05",
"MarginPurchaseTodayBalance": 512,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-06",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-07",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-08",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-12",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-13",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-14",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-15",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 14325
},
{
"date": "2022-09-16",
"MarginPurchaseTodayBalance": 465,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 28651
},
{
"date": "2022-09-19",
"MarginPurchaseTodayBalance": 860,
"ShortSaleTodayBalance": 122,
"MarginPurchaseLimit": 28651
}
],
"price_5536": [
{
"date": "2022-08-24",
"close": 196.0
},
{
"date": "2022-08-25",
"close": 197.5
},
{
"date": "2022-08-26",
"close": 203.5
},
{
"date": "2022-08-29",
"close": 208.0
},
{
"date": "2022-08-30",
"close": 211.5
},
{
"date": "2022-08-31",
"close": 212.5
},
{
"date": "2022-09-01",
"close": 213.5
},
{
"date": "2022-09-02",
"close": 215.0
},
{
"date": "2022-09-05",
"close": 210.5
},
{
"date": "2022-09-06",
"close": 206.0
},
{
"date": "2022-09-19",
"close": 106.0
}
],
"margin_4967": [
{
"date": "2022-09-20",
"MarginPurchaseTodayBalance": 8749,
"ShortSaleTodayBalance": 315,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-21",
"MarginPurchaseTodayBalance": 8719,
"ShortSaleTodayBalance": 100,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-22",
"MarginPurchaseTodayBalance": 8667,
"ShortSaleTodayBalance": 122,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-23",
"MarginPurchaseTodayBalance": 8590,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-26",
"MarginPurchaseTodayBalance": 8324,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-27",
"MarginPurchaseTodayBalance": 8264,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-28",
"MarginPurchaseTodayBalance": 8144,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-29",
"MarginPurchaseTodayBalance": 8143,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-09-30",
"MarginPurchaseTodayBalance": 8136,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-10-03",
"MarginPurchaseTodayBalance": 8135,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-10-04",
"MarginPurchaseTodayBalance": 8127,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-10-05",
"MarginPurchaseTodayBalance": 8124,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-10-06",
"MarginPurchaseTodayBalance": 8117,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 25553
},
{
"date": "2022-10-07",
"MarginPurchaseTodayBalance": 8112,
"ShortSaleTodayBalance": 0,
"MarginPurchaseLimit": 17887
},
{
"date": "2022-10-11",
"MarginPurchaseTodayBalance": 5444,
"ShortSaleTodayBalance": 9,
"MarginPurchaseLimit": 17887
}
],
"price_4967": [
{
"date": "2022-09-20",
"close": 29.2
},
{
"date": "2022-09-21",
"close": 28.9
},
{
"date": "2022-09-22",
"close": 28.05
},
{
"date": "2022-09-23",
"close": 28.15
},
{
"date": "2022-09-26",
"close": 26.85
},
{
"date": "2022-09-27",
"close": 26.7
},
{
"date": "2022-09-28",
"close": 26.05
},
{
"date": "2022-10-11",
"close": 30.15
}
],
"sbl_5289": [
{
"date": "2025-08-22",
"SBLShortSalesCurrentDayBalance": 1365373,
"SBLShortSalesQuota": 162882
},
{
"date": "2025-08-25",
"SBLShortSalesCurrentDayBalance": 1336373,
"SBLShortSalesQuota": 159605
},
{
"date": "2025-08-26",
"SBLShortSalesCurrentDayBalance": 1360373,
"SBLShortSalesQuota": 185761
},
{
"date": "2025-08-27",
"SBLShortSalesCurrentDayBalance": 1360373,
"SBLShortSalesQuota": 202338
},
{
"date": "2025-08-28",
"SBLShortSalesCurrentDayBalance": 1429373,
"SBLShortSalesQuota": 269862
},
{
"date": "2025-08-29",
"SBLShortSalesCurrentDayBalance": 1436373,
"SBLShortSalesQuota": 297783
},
{
"date": "2025-09-01",
"SBLShortSalesCurrentDayBalance": 1497373,
"SBLShortSalesQuota": 328194
}
],
"price_5289": [
{
"date": "2025-08-22",
"close": 242.5
},
{
"date": "2025-08-25",
"close": 246.0
},
{
"date": "2025-08-26",
"close": 270.5
},
{
"date": "2025-08-27",
"close": 297.5
},
{
"date": "2025-08-28",
"close": 291.5
},
{
"date": "2025-08-29",
"close": 290.5
},
{
"date": "2025-09-01",
"close": 282.5
}
],
"margin_3006": [
{"date": "2022-06-22", "MarginPurchaseTodayBalance": 26709, "ShortSaleTodayBalance": 1973, "MarginPurchaseLimit": 71539},
{"date": "2022-06-23", "MarginPurchaseTodayBalance": 26003, "ShortSaleTodayBalance": 1454, "MarginPurchaseLimit": 71539},
{"date": "2022-06-24", "MarginPurchaseTodayBalance": 26109, "ShortSaleTodayBalance": 949, "MarginPurchaseLimit": 71539},
{"date": "2022-06-27", "MarginPurchaseTodayBalance": 25446, "ShortSaleTodayBalance": 16, "MarginPurchaseLimit": 71539},
{"date": "2022-06-28", "MarginPurchaseTodayBalance": 25035, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 71539},
{"date": "2022-06-29", "MarginPurchaseTodayBalance": 25095, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 71539},
{"date": "2022-06-30", "MarginPurchaseTodayBalance": 23486, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 71539},
{"date": "2022-07-01", "MarginPurchaseTodayBalance": 22073, "ShortSaleTodayBalance": 4632, "MarginPurchaseLimit": 71539}
],
"price_3006": [
{"date": "2022-06-22", "close": 95.7},
{"date": "2022-06-23", "close": 97.4},
{"date": "2022-06-24", "close": 99.5},
{"date": "2022-06-27", "close": 101.5},
{"date": "2022-06-28", "close": 98.9},
{"date": "2022-06-29", "close": 96.4},
{"date": "2022-06-30", "close": 88.8},
{"date": "2022-07-01", "close": 74.1}
],
"margin_2451": [
{"date": "2022-06-27", "MarginPurchaseTodayBalance": 1672, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 107265},
{"date": "2022-06-28", "MarginPurchaseTodayBalance": 1672, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 107265},
{"date": "2022-06-29", "MarginPurchaseTodayBalance": 1669, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 107265},
{"date": "2022-06-30", "MarginPurchaseTodayBalance": 1647, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 107265},
{"date": "2022-07-01", "MarginPurchaseTodayBalance": 1556, "ShortSaleTodayBalance": 0, "MarginPurchaseLimit": 107265},
{"date": "2022-07-04", "MarginPurchaseTodayBalance": 1573, "ShortSaleTodayBalance": 160, "MarginPurchaseLimit": 107265},
{"date": "2022-07-05", "MarginPurchaseTodayBalance": 1577, "ShortSaleTodayBalance": 24, "MarginPurchaseLimit": 107265},
{"date": "2022-07-06", "MarginPurchaseTodayBalance": 1342, "ShortSaleTodayBalance": 42, "MarginPurchaseLimit": 107265}
],
"price_2451": [
{"date": "2022-06-27", "close": 70.8},
{"date": "2022-06-28", "close": 70.3},
{"date": "2022-06-29", "close": 70.1},
{"date": "2022-06-30", "close": 69.1},
{"date": "2022-07-01", "close": 68.5},
{"date": "2022-07-04", "close": 59.5},
{"date": "2022-07-05", "close": 58.8},
{"date": "2022-07-06", "close": 58.1}
]
}''')

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print(f"{'✅' if ok else '❌'} {name}: got={got!r} want={want!r}")


def stub_fetch(mod, price_key, bal_key):
    def _f(dataset, code, start):
        if dataset == "TaiwanStockPrice":
            return list(FX[price_key])
        return list(FX[bal_key])
    mod._fetch = _f


def main():
    tmp = tempfile.mkdtemp(prefix="ca_guard_test_")
    tw_margin.CACHE = os.path.join(tmp, "margin_cache.json")
    tw_sbl.CACHE = os.path.join(tmp, "sbl_cache.json")

    # ① classify rule 鍵語意(守衛依 rule 分流,免疫規則不可誤標)
    check("margin_surge rule", tw_margin.classify(1150, 1000, 0, 9999, 100, 100)["rule"], "margin_surge")
    check("margin_plunge rule", tw_margin.classify(800, 1000, 0, 9999, 100, 100)["rule"], "margin_plunge")
    check("short_ratio_high rule(免疫,不經守衛)", tw_margin.classify(1000, 1000, 200, 9999, 100, 100)["rule"], "short_ratio_high")
    check("margin neutral rule", tw_margin.classify(1000, 1000, 0, 9999, 100, 100)["rule"], "neutral")
    check("sbl_surge rule", tw_sbl.classify(1300, 1000)["rule"], "sbl_surge")
    check("sbl_mild rule", tw_sbl.classify(1120, 1000)["rule"], "sbl_mild_increase")
    check("sbl neutral rule", tw_sbl.classify(1000, 1000)["rule"], "neutral")

    # ② 守衛函式邊界
    g = tw_margin.ca_conversion_suspect
    check("分割日 -48.5% gap → True",
          g([{"date": "2022-09-06", "close": 206.0}, {"date": "2022-09-19", "close": 106.0}], "2022-09-08", "2022-09-19"), True)
    check("漲停 +10% 兩日連續 → False(≤上限非 CA)",
          g([{"date": "d1", "close": 100.0}, {"date": "d2", "close": 110.0}, {"date": "d3", "close": 121.0}], "", "d3"), False)
    check("CA 在窗前(d ≤ date_lo)→ False",
          g([{"date": "2022-09-06", "close": 206.0}, {"date": "2022-09-19", "close": 106.0}], "2022-09-19", "2022-09-30"), False)
    check("價格缺漏 → fail-open False", g([], "", "z"), False)
    check("close=None 列跳過不炸",
          g([{"date": "d1", "close": None}, {"date": "d2", "close": 100.0}], "", "z"), False)

    # ③ e2e:5536 分割日 margin_surge 必被壓(stub _fetch=真實歷史資料)
    stub_fetch(tw_margin, "price_5536", "margin_5536")
    r = tw_margin.margin("5536", today=datetime.date(2022, 9, 19))
    check("5536 分割日 level", r["level"], "plain")
    check("5536 分割日 rule", r["rule"], "ca_conversion_guard")
    # 守衛前確實會觸發 margin_surge(證明是守衛壓的,不是資料湊巧)
    raw = tw_margin.classify(860, 465, 122, 28651, 106.0, 206.0)
    check("5536 未經守衛=margin_surge(對照)", raw["rule"], "margin_surge")

    # ④ e2e:4967 減資落地日 margin_plunge 必被壓
    stub_fetch(tw_margin, "price_4967", "margin_4967")
    tw_margin.CACHE = os.path.join(tmp, "margin_cache2.json")
    r = tw_margin.margin("4967", today=datetime.date(2022, 10, 11))
    check("4967 減資日 level", r["level"], "plain")
    check("4967 減資日 rule", r["rule"], "ca_conversion_guard")

    # ⑤ e2e:5289 配股窗內有機 sbl_mild_increase 不可誤壓(除權價格缺口僅 ~-2%)
    stub_fetch(tw_sbl, "price_5289", "sbl_5289")
    r = tw_sbl.sbl("5289", today=datetime.date(2025, 9, 1))
    check("5289 配股窗 level(不誤壓)", r["level"], "yellow")
    check("5289 配股窗 rule", r["rule"], "sbl_mild_increase")

    # ⑥ v2/F1:大額除息缺口(限額全程平坦)不誤壓有機斷頭訊號(真實資料:3006 除息8元
    #    價 -16.6%、2451 除息6元價 -13.1%,v1 歷史重放此兩筆被誤壓=守衛觸發的 50%)
    stub_fetch(tw_margin, "price_3006", "margin_3006")
    tw_margin.CACHE = os.path.join(tmp, "margin_cache3.json")
    r = tw_margin.margin("3006", today=datetime.date(2022, 7, 1))
    check("3006 除息窗 rule(有機斷頭保留)", r["rule"], "margin_plunge")
    check("3006 除息窗 level", r["level"], "red")
    stub_fetch(tw_margin, "price_2451", "margin_2451")
    tw_margin.CACHE = os.path.join(tmp, "margin_cache4.json")
    r = tw_margin.margin("2451", today=datetime.date(2022, 7, 6))
    check("2451 除息窗 rule(有機斷頭保留)", r["rule"], "margin_plunge")

    # ⑦ v2/F6:非數值 close(字串)列跳過不炸巡邏,守衛照常運作
    check("字串 close 列跳過不炸", g([{"date": "d1", "close": "100"}, {"date": "d2", "close": 50.0}], "", "z"), False)
    dirty_prices = [dict(p) for p in FX["price_5536"]]
    dirty_prices[8]["close"] = "210.5"
    def _dirty(dataset, code, start):
        return dirty_prices if dataset == "TaiwanStockPrice" else list(FX["margin_5536"])
    tw_margin._fetch = _dirty
    tw_margin.CACHE = os.path.join(tmp, "margin_cache5.json")
    r = tw_margin.margin("5536", today=datetime.date(2022, 9, 19))
    check("5536 含髒列仍被壓不炸", r["rule"], "ca_conversion_guard")

    # ⑧ v2/F3:缺洞跨多日假缺口(1623 2025-04 形態)+限額平坦 → 不壓
    check("缺洞跨多日 -12.8% 限額平坦 → False",
          g([{"date": "2025-04-01", "close": 100.0}, {"date": "2025-04-07", "close": 87.2}],
            "2025-03-31", "2025-04-07",
            limit_rows=[{"date": "2025-04-01", "L": 5000}, {"date": "2025-04-07", "L": 5000}], limit_key="L"), False)

    # ⑨ v2/F5:小減資(factor 0.93)價格缺口 +7.5%<10.5% 但限額單日 -7%(專屬簽名)→ 壓
    check("小減資限額 -7% 單獨觸發 → True",
          g([{"date": "d1", "close": 93.0}, {"date": "d2", "close": 100.0}], "d0", "d2",
            limit_rows=[{"date": "d1", "L": 10000}, {"date": "d2", "L": 9300}], limit_key="L"), True)

    # ⑩ v2:配股發放日限額升(3128 形態 +9.7%)無價格缺口配套 → 不壓
    check("配股發放限額升無缺口 → False",
          g([{"date": "d1", "close": 100.0}, {"date": "d2", "close": 101.0}], "d0", "d2",
            limit_rows=[{"date": "d1", "L": 41000}, {"date": "d2", "L": 45000}], limit_key="L"), False)

    # ⑪ v2 fallback:限額資料不可用(全 None)→ 退回純價格缺口,5536 分割仍被壓
    rows_nolimit = [dict(rr, MarginPurchaseLimit=None) for rr in FX["margin_5536"]]
    def _nolimit(dataset, code, start):
        return list(FX["price_5536"]) if dataset == "TaiwanStockPrice" else rows_nolimit
    tw_margin._fetch = _nolimit
    tw_margin.CACHE = os.path.join(tmp, "margin_cache6.json")
    r = tw_margin.margin("5536", today=datetime.date(2022, 9, 19))
    check("5536 無限額欄 fallback 仍被壓", r["rule"], "ca_conversion_guard")

    # ⑫ v2/F2:util 錯位窗(合成,4967 名目→落地錯位形態)——限額已換算餘額未換算,
    #    util 灌水假觸發 margin_util_high → 壓;對照組限額平坦 → 保留
    bal = [6250, 6260, 6270, 6280, 6290, 6295, 6300]
    lim_drop = [10000, 10000, 10000, 10000, 10000, 7000, 7000]
    dts = [f"2025-06-{d:02d}" for d in range(2, 9)]
    rows_util = [{"date": d, "MarginPurchaseTodayBalance": b, "ShortSaleTodayBalance": 0,
                  "MarginPurchaseLimit": l} for d, b, l in zip(dts, bal, lim_drop)]
    prices_util = [{"date": d, "close": 100.0} for d in dts]
    def _util(dataset, code, start):
        return list(prices_util) if dataset == "TaiwanStockPrice" else list(rows_util)
    tw_margin._fetch = _util
    tw_margin.CACHE = os.path.join(tmp, "margin_cache7.json")
    r = tw_margin.margin("9998", today=datetime.date(2025, 6, 8))
    check("util 錯位窗(限額 -30%)被壓", r["rule"], "ca_conversion_guard")
    rows_util_flat = [dict(rr, MarginPurchaseLimit=7000) for rr in rows_util]
    def _util_flat(dataset, code, start):
        return list(prices_util) if dataset == "TaiwanStockPrice" else list(rows_util_flat)
    tw_margin._fetch = _util_flat
    tw_margin.CACHE = os.path.join(tmp, "margin_cache8.json")
    r = tw_margin.margin("9997", today=datetime.date(2025, 6, 8))
    check("util 限額平坦(真高檔)保留", r["rule"], "margin_util_high")

    n_ok = sum(RESULTS)
    print(f"\n{n_ok}/{len(RESULTS)} 段通過")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
