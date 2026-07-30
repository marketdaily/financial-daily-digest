#!/usr/bin/env python3
"""us_congress_trades 的離線迴歸測試(零網路呼叫)。

補既有 capabilities/tests/us_congress_trades.test.sh 測不到的兩塊新邏輯:
① PTR PDF 的 regex 解析(用壓平後的真實版面字串當 fixture,不放 PDF 進 repo)
② 代操再平衡過濾 drop_bulk_rebalance()

⭐ 為什麼這兩塊值得鎖:2026-07-30 首次拿到真實資料才發現 89% 的申報是 $1,001 最小級距、
單一議員一天可申報 49 檔。沒有過濾器的話 152 筆會生出 5 red + 17 yellow,而那 5 個 red
全是假的(兩位大批申報者剛好在同一檔重疊)。門檻是拿真實分佈校準出來的,不是猜的——
所以要有測試把它釘住,免得日後有人「順手放寬」。

跑法:.venv/bin/python intel/test_us_congress_trades.py  (exit 0 = 全過)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intel import us_congress_trades as uc  # noqa: E402

# 真實 PTR(Filing ID 20034945, Hon. Richard W. Allen)PyMuPDF 抽字後壓平空白的樣子
REAL_ROW = ("Fʋʎʇʔ Iʐʈʑʔʏʃʖʋʑʐ Name: Hon. Richard W. Allen Status: Member State/District: GA12 "
            "Tʔʃʐʕʃʅʖʋʑʐʕ ID Owner Asset Transaction Type Date Notification Date Amount "
            "SP Intuit Inc. - Common Stock (INTU) [ST] S 06/10/2026 07/07/2026 $15,001 - $50,000")

MULTI = ("A Corp - Common Stock (AAA) [ST] P 07/01/2026 07/10/2026 $1,001 - $15,000 "
         "B Corp - Common Stock (BBB) [ST] S 07/02/2026 07/10/2026 $50,001 - $100,000 "
         "C Fund (CCC) [OP] P 07/03/2026 07/10/2026 $1,001 - $15,000 "
         "D Corp - Common Stock (DDD) [ST] E 07/04/2026 07/10/2026 $1,001 - $15,000")


def parse_flat(flat):
    """跑 _PTR_ROW 那條 regex(繞過 PDF 抽字,直接餵壓平後的字串)。"""
    out = []
    for m in uc._PTR_ROW.finditer(flat):
        ticker, asset, ttype, amount = m.group(1), m.group(2), m.group(3), m.group(4)
        if asset != "ST":
            continue
        kind = {"P": "buy", "S": "sell"}.get(ttype)
        if not kind:
            continue
        out.append({"ticker": ticker, "trade_type": kind,
                    "amount_min": uc._parse_amount_min(amount)})
    return out


def check(name, got, want):
    ok = got == want
    print(f"  {'✅' if ok else '❌'} {name}")
    if not ok:
        print(f"      期望 {want}\n      實際 {got}")
    return ok


def main() -> int:
    ok = True

    # ── ① regex 解析 ──────────────────────────────────────────────
    ok &= check("真實 PTR 解出 INTU 賣出 $15,001",
                parse_flat(REAL_ROW),
                [{"ticker": "INTU", "trade_type": "sell", "amount_min": 15001}])
    # [OP] 選擇權要濾掉、E(exchange) 不當買賣、[ST] 的買賣都要收
    ok &= check("多筆:只收 [ST] 的 P/S,濾掉 [OP] 與 E",
                parse_flat(MULTI),
                [{"ticker": "AAA", "trade_type": "buy", "amount_min": 1001},
                 {"ticker": "BBB", "trade_type": "sell", "amount_min": 50001}])
    ok &= check("金額解析取區間下限", uc._parse_amount_min("$15,001 - $50,000"), 15001)
    ok &= check("金額解析失敗回 0(當小額,不誤升級)", uc._parse_amount_min("N/A"), 0)
    ok &= check("官方索引日期 M/D/YYYY", str(uc._parse_us_date("7/15/2026")), "2026-07-15")
    ok &= check("索引日期壞值回 None", uc._parse_us_date("2026-07-15"), None)

    # ── ② 代操再平衡過濾 ──────────────────────────────────────────
    def tx(member, day, ticker, amt):
        return {"member": member, "disclosed": day, "ticker": ticker, "amount_min": amt}

    bulk = [tx("Bulk Guy", "2026-07-02", f"T{i}", 1001) for i in range(9)]
    kept, dropped = uc.drop_bulk_rebalance(bulk)
    ok &= check(f"同議員同日 9 檔全小額 → 全丟(dropped={dropped})", (len(kept), dropped), (0, 9))

    focused = [tx("Focused", "2026-07-16", "NVDA", 1001)]
    kept, dropped = uc.drop_bulk_rebalance(focused)
    ok &= check("單檔小額 → 保留(這才是判斷)", (len(kept), dropped), (1, 0))

    # 中間帶:剛好在門檻上/下,以及整批裡的大額例外
    edge_below = [tx("Edge", "2026-07-16", f"T{i}", 1001) for i in range(uc.BULK_MIN - 1)]
    kept, _ = uc.drop_bulk_rebalance(edge_below)
    ok &= check(f"同日 {uc.BULK_MIN - 1} 檔(門檻下)→ 全保留", len(kept), uc.BULK_MIN - 1)

    edge_at = [tx("Edge2", "2026-07-16", f"T{i}", 1001) for i in range(uc.BULK_MIN)]
    kept, _ = uc.drop_bulk_rebalance(edge_at)
    ok &= check(f"同日 {uc.BULK_MIN} 檔(剛好門檻)→ 全丟", len(kept), 0)

    with_big = ([tx("Mixed", "2026-07-16", f"T{i}", 1001) for i in range(8)]
                + [tx("Mixed", "2026-07-16", "BIGONE", uc.BULK_EXEMPT_MIN)])
    kept, dropped = uc.drop_bulk_rebalance(with_big)
    ok &= check("整批裡的大額例外要留下(大額本身就是判斷)",
                ([t["ticker"] for t in kept], dropped), (["BIGONE"], 8))

    two_days = ([tx("Spread", "2026-07-10", f"A{i}", 1001) for i in range(3)]
                + [tx("Spread", "2026-07-20", f"B{i}", 1001) for i in range(3)])
    kept, dropped = uc.drop_bulk_rebalance(two_days)
    ok &= check("同議員但分兩天各 3 檔 → 不算整批(按日分組,非按人)",
                (len(kept), dropped), (6, 0))

    # ── ③ 源新鮮度必須量「上游」而非「過濾後」 ──────────────────
    # 2026-07-30 踩到:_edge 快取鍵被舊 cache 變數覆寫洗掉,source_edge() 的 fallback 讓它
    # 安靜退回過濾後的日期 → 守衛從此量錯東西且不報錯。
    import datetime
    import json as _json

    day = datetime.date(2026, 7, 30)
    filtered = {"NVDA": [{"disclosed": "2026-07-24"}]}      # 過濾後只剩較舊的
    saved = None
    if os.path.exists(uc.CACHE):
        with open(uc.CACHE, encoding="utf-8") as f:
            saved = f.read()
    try:
        with open(uc.CACHE, "w", encoding="utf-8") as f:
            _json.dump({f"_edge:{day.isoformat()}": "2026-07-27"}, f)
        ok &= check("source_edge 優先用源的日期,不用過濾後的",
                    uc.source_edge(day, filtered), "2026-07-27")
        with open(uc.CACHE, "w", encoding="utf-8") as f:
            f.write("{}")
        ok &= check("_edge 鍵不存在時才 fallback 到過濾後日期",
                    uc.source_edge(day, filtered), "2026-07-24")
    finally:
        with open(uc.CACHE, "w", encoding="utf-8") as f:
            f.write(saved if saved is not None else "{}")

    print()
    print("✅ us_congress_trades 離線迴歸全過" if ok else "❌ 有項目不符期望")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
