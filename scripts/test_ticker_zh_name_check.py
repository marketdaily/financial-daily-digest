#!/usr/bin/env python3
"""digest_audit check#11(ticker_no_zh_name)迴歸測試。

背景(2026-07-17 根治):07-10~16 復發失分兩類根因——
  Pattern A: analyzer._portfolio_lens_block 四清單裸代號(真違規,已改 stock_names 展開)
  Pattern B: 「Meta（META）」內容正確但舊 check 只認 ±12 字內 ≥2 連續 CJK,
             Meta/Alphabet 拉丁字母慣用名結構性假陽性(已改為同時接受 US_NAMES 中/英名)
本檔凍結修後語意:假陽性類必 PASS、真裸代號類必 FAIL(鑑別力不可退化)。

用法: .venv/bin/python scripts/test_ticker_zh_name_check.py   (exit 0=全過)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest_audit


def run_check11(text):
    html = "<html><body>" + text + "</body></html>"
    fails = digest_audit.audit_digest(html, "2026-07-17", [], [], {}, market="us")
    return [f for f in fails if f.get("check") == "ticker_no_zh_name"]


# (名稱, 內文, 修後預期要不要 FAIL)
CASES = [
    ("B1 Meta（META）英文名在旁=正確內容,不可誤判",
     "US close: tech up. Meta（META）+3.07% on ads strength.", False),
    ("B2 Alphabet（GOOGL）英文名在旁,不可誤判",
     "Earnings watch: Alphabet（GOOGL）2026-07-23, cloud + ads.", False),
    ("A1 裸代號清單(組合透視舊格式)=真違規,必抓",
     "risk: AAPL, MSFT, GOOGL, META, NVDA overvalued vs DCF band.", True),
    ("A2 真裸代號無任何名字,必抓(鑑別力錨點)",
     "watchlist: GOOGL +2.1% 585.25 MA200 test.", True),
    ("C1 中文名在旁(既有正確路徑不可回歸)",
     "quote: 輝達（NVDA）+0.33% strong AI demand.", False),
    ("C2 AMD en 名==代號,不得拿代號自己當名字,必抓",
     "chips: AMD +1.2% 165.30 breakout watch.", True),
    ("C3 METALS 子字串不可誤掃",
     "commodities: METALS index +0.5% on supply.", False),
    ("C4 METALS 在前+正確 Meta（META）在後(find 誤位案),不可誤判",
     "METALS index +0.5% steady. Meta（META）+3.07% on ads.", False),
]


def main():
    ok = True
    for name, text, want_fail in CASES:
        fails = run_check11(text)
        got = bool(fails)
        status = "✅" if got == want_fail else "❌"
        if got != want_fail:
            ok = False
        print(f"{status} {name}: got={'FAIL' if got else 'PASS'} "
              f"預期={'FAIL' if want_fail else 'PASS'}"
              + (f" | {fails[0]['msg']}" if fails else ""))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
