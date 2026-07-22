#!/usr/bin/env python3
"""順風追高閘 _pp_uptrend_chase_gate 迴歸測試(2026-07-21 dq-519171bfa5)。

背景:research/2026-07-13_buy_setup_conditional_edge——追強勢三 cut 全 certified
negative_edge(regime_up 23.1%/uptrend_above_ma20 31.7%/uptrend∧prob 23.6%,基線 47.3%),
與 KPI chase_high 稽核獨立收斂 → risk_on+站上 MA20 的 buy 降級 wait(wait 是唯一真 edge)。
凍結語意:只在 risk_on 動作、只動 p>MA20、techs 缺席 fail-open、
holder 卡經 _pp_holder_wording 換防守語、gated 標記符合 build_track_record 消費端契約。

用法: .venv/bin/python scripts/test_uptrend_chase_gate.py   (exit 0=全過)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer import _pp_uptrend_chase_gate, _pp_holder_wording

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


CARD = ('<div class="signal-card buy"><!--h:NVDA--><span class="signal-verdict-chip buy">🟢 建議買入</span>'
        '<div class="signal-reason">動能強勁</div></div><div class="signal-disclaimer">')
CARD_POS = CARD.replace("<!--h:NVDA-->", "<!--h:NVDA--><!--pos:120.5-->")
ABOVE = {"NVDA": {"price": 180.0, "ma20": 170.0, "ma50": 160.0}}
BELOW = {"NVDA": {"price": 160.0, "ma20": 170.0, "ma50": 160.0}}

out = _pp_uptrend_chase_gate(CARD, ABOVE, "risk_on")
check("risk_on+p>MA20 → 降級 wait", 'signal-card wait' in out and "多頭市況勿追強勢" in out)
check("降級帶 gated 標記", "<!--gated:buy:uptrend_chase-->" in out)
check("neutral 市況不動", _pp_uptrend_chase_gate(CARD, ABOVE, "neutral") == CARD)
check("risk_off 不動", _pp_uptrend_chase_gate(CARD, ABOVE, "risk_off") == CARD)
check("p<MA20 不動", _pp_uptrend_chase_gate(CARD, BELOW, "risk_on") == CARD)
check("techs 缺席 fail-open", _pp_uptrend_chase_gate(CARD, {}, "risk_on") == CARD)

held = _pp_holder_wording(_pp_uptrend_chase_gate(CARD_POS, ABOVE, "risk_on"))
check("holder 卡換防守語", "持股防守·多頭市況勿追高加碼" in held and "觀望·多頭市況勿追強勢" not in held)

# build_track_record.py 消費端契約:閘名 charset 含連字號(rebuy-bleed 2026-07-21 修復)
rx = re.compile(r"\s*gated:(buy|hold|sell|wait):([a-z_-]+)\s*$")
check("gated 標記契約(含 hyphen 閘名)",
      all(rx.match(m) for m in ("gated:buy:uptrend_chase", "gated:buy:rebuy-bleed",
                                "gated:buy:knife", "gated:sell:oversold", "gated:buy:chase")))

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
