#!/usr/bin/env python3
"""audit#14(us_tonight_action_missing)確定性防線迴歸測試(2026-07-29 根治)。

背景:07-27 起免費配額枯竭掉弱模(cf:llama),med fail 不觸發 retry → 三天 11/7/11 位
失分全是這條(quality war room 上線第一天抓到的榜首)。#15 台股版 07-17 已有同款防線,
本檔凍結美股鏡射版 main._fix_us_tonight_action_wording 語意:
  ①美股卡「明晚/明日晚間開盤」→「今晚開盤」(僅限整卡無今晚/盤後字眼者)
  ②全卡皆無「今晚/盤後」→ 首張美股卡 reason 補「今晚美股開盤後:」
  ③gate 之外零觸碰:tw 班次 no-op、已合規卡 no-op、台股卡(h-mark 首字數字)零觸碰

用法: .venv/bin/python scripts/test_us_tonight_action.py   (exit 0=全過)
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MD_SKIP_ADHOC_FETCH", "1")
os.environ["MD_MARKET"] = "us"
import main  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


def card(hmark, reason):
    return (f'<div class="signal-card"><!--h:{hmark}-->'
            f'<div class="signal-reason">{reason}</div></div>')


DISC = '<div class="signal-disclaimer">僅供參考</div>'
MKT_OPEN = {"us_will_open_tonight": True, "tw_will_open_today": True}
MKT_CLOSED = {"us_will_open_tonight": False, "tw_will_open_today": True}


def run(html, mkt=MKT_OPEN, market="us"):
    with patch.object(main, "MARKET", market), \
         patch("analyzer._market_status", return_value=mkt):
        return main._fix_us_tonight_action_wording("2026-07-29", html)


# ── ② 樓地板注入 ──────────────────────────────────────────────
h = card("AAPL", "量能收斂,觀望為主") + DISC
out = run(h)
check("G1 全卡無今晚/盤後 → 首張美股卡補「今晚美股開盤後:」", "今晚美股開盤後:" in out)
check("G1b 注入後 audit#14 判準通過(含「今晚」)", "今晚" in out)

h = card("2330", "台股卡不該被注入") + card("AAPL", "美股卡") + DISC
out = run(h)
check("G2 有台股卡時只注入美股卡", "今晚美股開盤後:" in out.split("<!--h:AAPL-->")[1]
      and "今晚" not in out.split("<!--h:AAPL-->")[0])

# ── ① 時序錯字修正 ────────────────────────────────────────────
h = card("TSLA", "觀察明晚開盤能否站回 250") + DISC
out = run(h)
check("F1 「明晚開盤」→「今晚開盤」", "今晚開盤" in out and "明晚開盤" not in out)

h = card("NVDA", "明日晚間開盤前不動作") + DISC
out = run(h)
check("F2 「明日晚間開盤」→「今晚開盤」", "今晚開盤" in out)

h = card("AAPL", "今晚開盤後守穩 210 再加碼") + card("TSLA", "觀察明晚開盤量能") + DISC
out = run(h)
check("F3 已合規整體(有「今晚」卡)→ 不合規卡的明晚仍修但不重複注入",
      out.count("今晚美股開盤後:") == 0)

# ── ③ gate 之外零觸碰 ─────────────────────────────────────────
h = card("AAPL", "盤後公布財報,先觀望") + DISC
check("Z1 已有「盤後」→ 完全零觸碰", run(h) == h)

h = card("AAPL", "量能收斂,觀望為主") + DISC
check("Z2 美股今晚休市 → no-op", run(h, mkt=MKT_CLOSED) == h)
check("Z3 tw 班次 → no-op", run(h, market="tw") == h)

h = card("2330", "台股卡") + card("00981A", "字母尾碼台股卡") + DISC
check("Z4 純台股卡(含 00981A 型)→ 零注入", "今晚" not in run(h))

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'✅ 全過' if not failed else '❌ FAIL: ' + ', '.join(failed)}({len(RESULTS)} 檢查)")
sys.exit(1 if failed else 0)
