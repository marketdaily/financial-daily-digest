"""超時自動加註盤前說明的迴歸(2026-07-30 Delvin 就 open item #16 拍板 B)。

背景:`_enforce_send_deadline` 只在 run.sh 補班模式生效,正常班次生成超時就直接寄——
07-30 晚報 21:35 才寄出而美股 21:30 已開盤,等於發了一封講盤前的信卻沒告訴讀者。
拍板:照寄(絕不讓用戶缺信),但誠實加註。

這支釘死三件事:
  ① 沒超時 → 一個字都不加(行為與過去逐字相同)
  ② 超時但**還沒開盤**的那幾十分鐘,不准寫「已開盤」——為了誠實加的註記反而造假,比不加更糟
  ③ 美股開盤時刻要跟著夏冬令走(夏令 21:30 TW / 冬令 22:30 TW),寫死任一個都有半年是錯的
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

TW = ZoneInfo("Asia/Taipei")
FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        FAILS.append(f"{name} {extra}")
        print(f"  ✗ {name} {extra}")


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TW)


SUMMER = "2026-07-30"   # 夏令(EDT):美股 9:30 ET = 21:30 TW
WINTER = "2026-12-10"   # 冬令(EST):美股 9:30 ET = 22:30 TW

print("── ① 沒超時就完全不動 ──")
check("晚報 20:00 準時 → 無加註", main._late_send_notice("us", SUMMER, at(f"{SUMMER} 20:00")) == "")
check("早報 07:00 準時 → 無加註", main._late_send_notice("tw", SUMMER, at(f"{SUMMER} 07:00")) == "")
check("死線前一分鐘仍不加註", main._late_send_notice("us", SUMMER, at(f"{SUMMER} 21:09")) == "")
check("both/手動班次不加註", main._late_send_notice("both", SUMMER, at(f"{SUMMER} 23:00")) == "")

print("\n── ② 超時但還沒開盤:不准謊稱已開盤 ──")
n = main._late_send_notice("us", SUMMER, at(f"{SUMMER} 21:15"))
check("21:15(過死線 21:10、未到 21:30)有加註", bool(n))
check("  不出現「已開盤」", "已開盤" not in n, n[:120])
check("  說明仍是盤前判斷", "盤前判斷" in n, n[:120])
check("  帶出正確開盤時刻 21:30", "21:30" in n, n[:120])

print("\n── ③ 真的開盤後:照實說,並要用戶確認現價 ──")
n = main._late_send_notice("us", SUMMER, at(f"{SUMMER} 21:35"))   # 07-30 實際寄出時刻
check("21:35 有加註", bool(n))
check("  明說已開盤", "已開盤" in n, n[:140])
check("  要求先確認現價", "確認現價" in n, n[:140])
check("  帶出實際寄出時刻 21:35", "21:35" in n, n[:140])

n = main._late_send_notice("tw", SUMMER, at(f"{SUMMER} 09:20"))
check("早報 09:20(台股 09:00 已開)明說已開盤", "已開盤" in n and "台股" in n, n[:140])

print("\n── ④ 美股開盤時刻跟著夏冬令走 ──")
check("夏令 = 21:30 TW", main._market_open_tw("us", SUMMER).strftime("%H:%M") == "21:30",
      main._market_open_tw("us", SUMMER).strftime("%H:%M"))
check("冬令 = 22:30 TW", main._market_open_tw("us", WINTER).strftime("%H:%M") == "22:30",
      main._market_open_tw("us", WINTER).strftime("%H:%M"))
check("台股恆 09:00", main._market_open_tw("tw", WINTER).strftime("%H:%M") == "09:00")
# 冬令時 21:35 其實**還沒開盤**(22:30 才開)→ 同一個時刻在不同季節要有不同措辭
nw = main._late_send_notice("us", WINTER, at(f"{WINTER} 21:35"))
check("冬令 21:35 不可寫已開盤", "已開盤" not in nw, nw[:140])

print("\n── ⑤ 插入錨點:三段 fallback,壞了寧可不插也不弄壞信 ──")
NOTE = "<div>NOTE</div>"
h1 = '<body><div class="wrapper"><div class="header">H</div><div class="tldr">T</div></body>'
out = main._inject_late_notice(h1, NOTE)
check("有 tldr → 插在 tldr 之前(header 之下)",
      out.index(NOTE) > out.index('class="header"') and out.index(NOTE) < out.index('class="tldr"'), out)
h2 = '<body><div class="wrapper"><div class="header">H</div></body>'
check("沒 tldr → 退回 wrapper", NOTE in main._inject_late_notice(h2, NOTE))
h3 = "<body><p>hi</p></body>"
check("只有 body → 仍插得進去", NOTE in main._inject_late_notice(h3, NOTE))
h4 = "<p>沒有任何錨點</p>"
check("錨點全無 → 原樣回傳不弄壞", main._inject_late_notice(h4, NOTE) == h4)
check("空 notice → 原樣回傳", main._inject_late_notice(h1, "") == h1)

if FAILS:
    print(f"\n✗ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("\n✅ 全部通過")
