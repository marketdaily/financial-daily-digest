#!/usr/bin/env python3
"""卡級 reason 確定性增補層 _augment_shallow_reason 迴歸測試(2026-08-03)。

背景:archive:signal_reason_shallow 慢性失分根因——免費額全熔斷日只剩弱模型鏈,
reason median 79 字過卡級 70 字閘但輸掉 archive 級 80/60 期望,card-regen 重燒
慢模型(144s/次)到預算盡→5 位掉 deterministic fallback。
凍結語意:<100 字才補、只轉述 data dict 既有數字、零 LLM、不生成價位建議、
≥100 字絕不動、湊不出事實 fail-open、備援卡不動、冪等。

用法: .venv/bin/python scripts/test_shallow_reason_augment.py   (exit 0=全過)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer import _augment_shallow_reason, _card_passes_audit

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


def mk_card(reason):
    return ('<div class="signal-card buy"><div class="signal-reason">' + reason
            + '</div><div class="battle-row">a</div><div class="battle-row">b</div>'
            + '<div class="battle-row">c</div></div>')


DATA = {
    "us_market": {"NVDA": {"price": 180.0, "change_pct": 1.85}},
    "tw_market": {},
    "technicals": {"NVDA": {"price": 180.0, "ma20": 170.0, "rsi14": 62.3,
                            "vol_ratio": 1.4, "vol_state": "放量"}},
}

SHALLOW = ("動能延續但短線波動明顯放大,籌碼面仍偏多方,今晚開盤後若守住 $175 支撐可續抱,"
           "跌破則先減碼一半控風險,之後觀察一兩天價格走勢再決定是否回補部位。")
assert 70 <= len(SHALLOW) < 100, len(SHALLOW)

out = _augment_shallow_reason(mk_card(SHALLOW), "NVDA", DATA)
plain = re.sub(r"<[^>]+>", "", re.search(
    r'<div class="signal-reason">(.*?)</div>', out, re.S).group(1)).strip()
check("<100 字補上數據面補充", "數據面補充" in out)
check("補後長度 ≥100", len(plain) >= 100)
check("含 RSI14 事實", "RSI14 62.3" in plain)
check("含 MA20 距離事實", "高於 MA20 約 5.9%" in plain)
check("含當日漲跌幅", "+1.85%" in plain)
check("含相對量+狀態", "相對量 1.4x(放量)" in plain)
extra = plain[len(SHALLOW):]
check("增補段不含價位建議($/NT$/買/停損)",
      not re.search(r"\$|NT\$|買|停損|加碼|減碼", extra))

LONG = "這是一段已經超過一百字的完整分析理由," * 6
assert len(LONG) >= 100, len(LONG)
card_long = mk_card(LONG)
check("≥100 字絕不動(行為凍結)",
      _augment_shallow_reason(card_long, "NVDA", DATA) == card_long)

card_s = mk_card(SHALLOW)
check("無任何事實可湊 fail-open 不動",
      _augment_shallow_reason(card_s, "XXXX", DATA) == card_s)
check("冪等:補過的卡再跑不動",
      _augment_shallow_reason(out, "NVDA", DATA) == out)

fb = mk_card("此卡為備援內容,無即時報價。")
check("備援卡不動", _augment_shallow_reason(fb, "NVDA", DATA) == fb)

DUP = "RSI 已偏熱且量能放大,今晚開盤後守 $175 可續抱,破線減碼,先看一天再決定動作。"
out_dup = _augment_shallow_reason(mk_card(DUP), "NVDA", DATA)
check("reason 已提 RSI/量 → 不重複補該事實",
      "RSI14 62.3" not in out_dup and "相對量" not in out_dup)

TINY = "今晚開盤守 $175 續抱,破線減碼。"
assert len(TINY) < 70
out_tiny = _augment_shallow_reason(mk_card(TINY), "NVDA", DATA)
check("<70 字卡補後過 _card_passes_audit(不再進 regen 重燒)",
      not _card_passes_audit(mk_card(TINY)) and _card_passes_audit(out_tiny))

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
