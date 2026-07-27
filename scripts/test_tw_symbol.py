#!/usr/bin/env python3
"""台股/美股代碼判別單一事實來源迴歸測試(2026-07-27 isdigit 家族根治)。

背景:00981A(字母尾碼主動式 ETF)被「全數字」判別 str.isdigit() 誤當美股 →
①prompt 層台股早盤鐵則不注入(hfks996 07-22/27 兩鍋第一層根因)
②deterministic fallback 卡/精簡卡去 us_market 查表 → 拿不到報價變「無即時報價」卡
③tw_n/us_n 計數與美股清單過濾皆錯。
根治:analyzer._is_tw_symbol()(首字數字=台股,同原 L1236 權威慣例)收斂全部 6 處
錯誤判別+4 處既有首字判別。本檔凍結 helper 語意與行情路由行為。

用法: .venv/bin/python scripts/test_tw_symbol.py   (exit 0=全過)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MD_SKIP_ADHOC_FETCH", "1")
import analyzer  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


# ── ① helper 真值表 ──────────────────────────────────────────
check("T1 00981A=台股(字母尾碼主動式ETF,實鍋案例)", analyzer._is_tw_symbol("00981A"))
check("T2 2330=台股", analyzer._is_tw_symbol("2330"))
check("T3 0050=台股(ETF)", analyzer._is_tw_symbol("0050"))
check("T4 AAPL=美股", not analyzer._is_tw_symbol("AAPL"))
check("T5 BRK.B=美股(帶點)", not analyzer._is_tw_symbol("BRK.B"))
check("T6 空字串非台股", not analyzer._is_tw_symbol(""))
check("T7 None 非台股", not analyzer._is_tw_symbol(None))

# ── ② deterministic fallback 卡行情路由(舊 bug:00981A 查 us_market 變無報價卡) ──
DATA = {
    "tw_market": {"00981A": {"price": 15.2, "change_pct": 1.3, "name": "統一台股增長主動式"}},
    "us_market": {"NVDA": {"price": 180.0, "change_pct": 0.5, "name": "NVIDIA"}},
    "technicals": {},
}
card = analyzer._deterministic_signal_card("00981A", DATA, {"tw_will_open_today": True})
check("D1 00981A fallback 卡拿到 tw_market 報價(非「無即時報價」)",
      "無即時報價" not in card and "15.2" in card)
check("D2 00981A fallback 卡走台股措辭(元+今早開盤窗口)",
      "元" in card and "今早 9:00 開盤" in card)
card_us = analyzer._deterministic_signal_card("NVDA", DATA, {"us_will_open_tonight": True})
check("D3 美股卡路由不受影響(NVDA 走 us_market,$ 計價有報價)",
      "$180" in card_us and "無即時報價" not in card_us)

# ── ③ 精簡卡同路由 ──
compact = analyzer._compact_overflow_card("00981A", DATA, {"tw_will_open_today": True})
check("C1 00981A 精簡卡拿到 tw_market 報價", "15.2" in compact)

ok = all(r for _, r in RESULTS)
print(f"\n{'✅ 全過' if ok else '❌ 有失敗'} ({sum(1 for _, r in RESULTS if r)}/{len(RESULTS)})")
sys.exit(0 if ok else 1)
