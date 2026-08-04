#!/usr/bin/env python3
"""_prewarm_card_pool 深度順序迴歸測試(2026-08-04 早報 deep 版淺卡事故根治)。

凍結語意:
- deep 用戶持股聯集最先生成(depth="deep"),再全聯集 standard,最後 simple 用戶聯集。
- 卡片快取鍵含 depth → 只暖 standard 時 deep/simple 用戶零命中,他們的卡被擠到
  per-user 迴圈(整班最後),council 預算與強模型配額已被燒完 → 深度版反而最淺。
- 無 deep/simple 用戶時只跑 standard 一批(行為與舊版一致)。
- 無市價標的照舊被濾掉;subscriber_prefs=None 完全向後相容。

用法: MARKET=tw .venv/bin/python scripts/test_card_pool_depth_order.py   (exit 0=全過)
"""
import os
import sys

os.environ.setdefault("MARKET", "tw")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer
import main

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


CALLS = []
_orig_render = analyzer._render_signal_cards_batched
_orig_status = analyzer._market_status
analyzer._render_signal_cards_batched = (
    lambda data, syms, mkt, depth="standard", **kw: CALLS.append((depth, list(syms))))
analyzer._market_status = lambda date: {}

DATA = {
    "date": "2026-08-04",
    "us_market": {},
    "tw_market": {"2330": {"price": 1400.0}, "2454": {"price": 1300.0},
                  "2317": {"price": 240.0}, "9999": {"price": None}},
}
PREFS = {
    "boss@x.com": {"digest_depth": "deep", "tw_stocks": ["2330", "2454", "9999"], "us_stocks": ["NVDA"]},
    "std@x.com": {"digest_depth": "standard", "tw_stocks": ["2317"], "us_stocks": []},
    "simp@x.com": {"digest_depth": "simple", "tw_stocks": ["2317"], "us_stocks": []},
}

try:
    CALLS.clear()
    main._prewarm_card_pool(DATA, set(), {"2330", "2454", "2317", "9999"}, PREFS)
    depths = [d for d, _ in CALLS]
    check("三批依 deep→standard→simple 順序", depths == ["deep", "standard", "simple"])
    check("deep 批=deep 用戶持股∩本班有市價", CALLS and sorted(CALLS[0][1]) == ["2330", "2454"])
    check("deep 批不含無市價標的(9999)", CALLS and "9999" not in CALLS[0][1])
    check("deep 批不含他市場持股(NVDA)", CALLS and "NVDA" not in CALLS[0][1])
    check("standard 批=全聯集", len(CALLS) > 1 and sorted(CALLS[1][1]) == ["2317", "2330", "2454"])
    check("simple 批=simple 用戶持股", len(CALLS) > 2 and CALLS[2][1] == ["2317"])

    CALLS.clear()
    main._prewarm_card_pool(DATA, set(), {"2330", "2317"},
                            {"std@x.com": PREFS["std@x.com"]})
    check("全 standard 用戶 → 只跑一批 standard(行為凍結)",
          [d for d, _ in CALLS] == ["standard"])

    CALLS.clear()
    main._prewarm_card_pool(DATA, set(), {"2330", "2317"}, None)
    check("subscriber_prefs=None 向後相容(只跑 standard)",
          [d for d, _ in CALLS] == ["standard"])
finally:
    analyzer._render_signal_cards_batched = _orig_render
    analyzer._market_status = _orig_status

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
