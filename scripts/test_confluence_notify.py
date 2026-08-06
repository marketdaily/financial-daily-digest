#!/usr/bin/env python3
"""intel/patrol.py `_confluence_notify_selection` 迴歸測試(2026-08-06)。

confluence.rank() 的跨源信念榜(Delvin 哲學#11 核心)原本只寫進 markdown,沒有任何推播/
下游消費(automation_scorecard「confluence 匯流評分」B⚠️)。本輪把它接進 intel_patrol_runner.sh
的推播,新增的「跟哪次比對算新」邏輯是本檔測的對象。

驗證者分離(全新 context,general-purpose agent)第一版就抓到真 bug:單純「(code,kind) 不在
前一晚快照」會讓 kind 因易變來源(如 mops_watch 3 天新聞視窗到期)每晚微幅震盪時反覆判定
「新」,同一情勢每晚重推,違背推播防洪本意。改成 ledger(記每個 (code,kind) 上次「真的推播」
的日期+conviction),自我 dogfooding 時又抓到第二個 bug:ledger 寫入時機錯放在「每次出現」
而非「真的被選中推播時」,會讓被冷卻壓下的訊號把「最後一次看到」誤當「最後一次推播」,
冷卻期永遠續不完(day3/day4 皆判定為 stale 的原始版本)。

凍結語意:
- 首次出現的 (code,kind) 一律推播。
- 距上次「真的推播」< CONFLUENCE_NOTIFY_COOLDOWN_DAYS(3 天)且 conviction 未升級 → 壓下,
  不重複推播(反震盪核心行為)。
- 距上次推播 >= 冷卻天數 → 即使 kind 沒變,也視為值得再提醒一次。
- conviction 比上次推播時升高(訊號變強)→ 即使在冷卻窗內也推播(升級不可被靜音)。
- 被壓下的出現「不」更新 ledger 時間戳(這是本輪抓到的真 bug,凍結成迴歸測試防再犯)。
- ledger 的 date 欄位壞掉(非合法 ISO 字串)→ 該筆直接丟棄,不 fail-open 讓垃圾永遠留著。
- by_code 為空(第一次跑/watchlist 全乾淨)不崩潰,回傳空清單。

用法: python3 scripts/test_confluence_notify.py   (exit 0=全過)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intel import patrol, confluence

FAILS = []


def check(label, cond):
    print(("PASS" if cond else "FAIL") + f": {label}")
    if not cond:
        FAILS.append(label)


def _bull_and_maybe_bear(code, extra_bear=False, extra_bull_src=False):
    sigs = [
        {"source": "institutional", "level": "red", "signal": f"{code}:買超"},
        {"source": "holders", "level": "yellow", "signal": f"{code}:加碼"},
    ]
    if extra_bear:
        sigs.append({"source": "sbl", "level": "yellow", "signal": f"{code}:放空"})
    if extra_bull_src:
        sigs.append({"source": "revenue", "level": "yellow", "signal": f"{code}:強勁"})
    return {code: sigs}


def run():
    tmp = tempfile.mktemp(suffix=".json")
    patrol.NOTIFY_LEDGER = tmp
    kinds = lambda sel: [(s["code"], s["kind"]) for s in sel]

    # 1) 首次出現 → 推播
    sel1 = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("AAPL")), "2026-08-01")
    check("首次出現的 confluence_bull 推播", ("AAPL", "confluence_bull") in kinds(sel1))

    # 2) 換方向(flip 到 divergence)→ 不同 kind,推播
    sel2 = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("AAPL", extra_bear=True)), "2026-08-02")
    check("反轉成 divergence 推播", ("AAPL", "divergence") in kinds(sel2))

    # 3) 隔天源老化,回到原本的 bull——距上次「bull 被推播」(day1)只差 2 天,冷卻中,不推
    sel3 = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("AAPL")), "2026-08-03")
    check("震盪回原 kind,冷卻窗內不重推(反震盪核心 bug)",
          ("AAPL", "confluence_bull") not in kinds(sel3))

    # 4) 冷卻壓下的出現不可更新時間戳:day4 距 day1 剛好 3 天(>=冷卻天數)才該過線
    sel4 = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("AAPL")), "2026-08-04")
    check("冷卻期滿(距首次推播 3 天)才重推,證明 day3 沒有偷改時間戳",
          ("AAPL", "confluence_bull") in kinds(sel4))

    # 5) day4 剛推播過,day5 立刻又壓下(冷卻重新計時)
    sel5 = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("AAPL")), "2026-08-05")
    check("剛推播完隔天立刻壓下(冷卻從新推播時刻重算)",
          ("AAPL", "confluence_bull") not in kinds(sel5))

    # 6) conviction 升級:即使在冷卻窗內也要推播
    sel6a = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("TSLA")), "2026-08-10")
    check("TSLA 首次推播", ("TSLA", "confluence_bull") in kinds(sel6a))
    sel6b = patrol._confluence_notify_selection(
        confluence.rank(_bull_and_maybe_bear("TSLA", extra_bull_src=True)), "2026-08-11")
    check("conviction 升級(2→3源)在冷卻窗內仍推播",
          ("TSLA", "confluence_bull") in kinds(sel6b))

    # 7) 空 by_code(第一次跑/今晚全乾淨)不崩潰
    sel7 = patrol._confluence_notify_selection(confluence.rank({}), "2026-08-01")
    check("空 by_code 回傳空清單不崩潰", sel7 == [])

    # 8) 壞掉的日期字串會被 prune 丟棄,不會 fail-open 永久卡在 ledger 裡
    import json
    tmp2 = tempfile.mktemp(suffix=".json")
    patrol.NOTIFY_LEDGER = tmp2
    with open(tmp2, "w", encoding="utf-8") as f:
        json.dump({"OLD|confluence_bull": {"date": "2025-01-01", "conviction": 2},
                   "BAD|divergence": {"date": "not-a-date", "conviction": 1},
                   "BAD2|confluence_bull": "not-a-dict"}, f)
    patrol._confluence_notify_selection(confluence.rank({}), "2026-08-06")
    with open(tmp2, encoding="utf-8") as f:
        ledger_after = json.load(f)
    check("過期/壞掉的 ledger entry 被 prune 清掉",
          "OLD|confluence_bull" not in ledger_after
          and "BAD|divergence" not in ledger_after
          and "BAD2|confluence_bull" not in ledger_after)

    for p in (tmp, tmp2):
        try:
            os.remove(p)
        except OSError:
            pass

    print(f"\n{len(FAILS)} FAIL / {8} checks")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(run())
