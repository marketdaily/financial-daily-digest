#!/usr/bin/env python3
"""audit#15(tw_morning_action_missing)三層修復迴歸測試(2026-07-17 根治)。

背景:失分榜首(digest_performance_loop 榜載 10 人次/5 日;本地 audit JSON 可取樣 6 人次),
KV 撈 7 封原始樣本分類=兩母體——
  真違規×5(07-13×3 整批無晨間框架 / 07-17×2 寫「明日開盤」時序錯亂)
  check 假陽性×1(07-15 darren「觀察9:00開盤後」— 舊 regex `9.{0,2}開盤`
                 吃不下 9 與開盤之間的「:00」3 字元)
三層修:
  ①digest_audit.TW_MORNING_ACTION_RE 放寬(9:00開盤/9點開盤/今日開盤)且維持
    「明日開盤」不收(時序錯亂是真違規)
  ②main._fix_tw_morning_action_wording 確定性防線:台股卡「明日/明天開盤」→「今早開盤」;
    整批台股卡無晨間窗口 → 首張卡 reason 補「今早 9:00 開盤後:」
  ③analyzer._mk_prompt 台股早盤強規則塊(LLM 端,無法確定性測,由①②兜底)
本檔凍結①②語意:假陽性類必 PASS、真違規經防線後必 PASS、防線 gate 之外零觸碰。

用法: .venv/bin/python scripts/test_tw_morning_action.py   (exit 0=全過)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from digest_audit import TW_MORNING_ACTION_RE

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


# ── ① regex 語意 ──────────────────────────────────────────────
# 07-15 darren 實鍋原文(舊 regex 假陽性 → 修後必命中)
check("R1 「觀察9:00開盤後能否守穩」必命中(07-15 實鍋假陽性)",
      TW_MORNING_ACTION_RE.search("下一步:觀察9:00開盤後能否守穩1255.5元"))
check("R2 「9:30 開盤」帶空格命中", TW_MORNING_ACTION_RE.search("等 9:30 開盤再看"))
check("R3 「9點開盤」命中", TW_MORNING_ACTION_RE.search("9點開盤後觀察量能"))
check("R4 「今早 9:00 開盤後」命中(tiffany 07-17 合規原文)",
      TW_MORNING_ACTION_RE.search("今早 9:00 開盤後請「絕對不要急著進場」"))
check("R5 「今日開盤」命中", TW_MORNING_ACTION_RE.search("今日開盤若跳空先觀望"))
check("R6 「明日開盤」不可命中(時序錯亂=真違規)",
      not TW_MORNING_ACTION_RE.search("觀察明日開盤能否守住 1295 元"))
check("R7 「收盤站穩」不可命中(晚間框架≠晨間窗口)",
      not TW_MORNING_ACTION_RE.search("等收盤站穩 373 元再進場"))
check("R8 「早盤」命中", TW_MORNING_ACTION_RE.search("今日早盤策略以觀望為主"))
# 驗證者第14案 F2/F3:時序錯亂近義詞與價格數字不可假合規
check("R9 「明日早盤」不可命中(F2a:時序錯亂近義詞)",
      not TW_MORNING_ACTION_RE.search("明日早盤觀察量能,現價勿追"))
check("R10 「昨日早盤」不可命中(回顧非動作窗口)",
      not TW_MORNING_ACTION_RE.search("昨日早盤爆量下殺,持續觀望"))
check("R11 「以1090開盤」價格不可命中(F3:數字前綴)",
      not TW_MORNING_ACTION_RE.search("昨天以1090開盤走低,現價勿追"))
check("R12 「199開盤」不可命中(F3)", not TW_MORNING_ACTION_RE.search("199開盤價"))
check("R13 「09:00開盤」命中(0?9 分支)", TW_MORNING_ACTION_RE.search("等09:00開盤再看"))

# ── ② main 確定性防線 ─────────────────────────────────────────
os.environ.setdefault("MD_SKIP_ADHOC_FETCH", "1")
import main  # noqa: E402  (main 模組級只 resolve MARKET/CSS,不寄信)

TW_OPEN_DAY = "2026-07-17"   # 週五,台股開盤
TW_CLOSED_DAY = "2026-07-12" # 週日,台股休市


def card(sym, reason, cls="wait"):
    return (f'<div class="signal-card {cls}"><div class="signal-card-top">'
            f'<span class="signal-ticker">{sym}</span></div>'
            f'<div class="signal-body"><div class="signal-reason">{reason}</div></div>'
            f'<!--h:{sym}--></div>')


def fixed(html, date=TW_OPEN_DAY, market="tw"):
    old = main.MARKET
    main.MARKET = market
    try:
        return main._fix_tw_morning_action_wording(date, html)
    finally:
        main.MARKET = old


# M1: 07-17 darren 台燿卡實鍋 — 明日開盤 → 今早開盤
h = card("2383", "觀察明日開盤能否守住 1295 元,若跌破則需防範下探。")
out = fixed(h)
check("M1 台股卡「明日開盤」改寫「今早開盤」(07-17 實鍋)",
      "今早開盤" in out and "明日開盤" not in out)
check("M1b 改寫後過 audit regex", TW_MORNING_ACTION_RE.search(out))

# M2: 07-17 maxine 實鍋 — 整批無晨間窗口 → 首張卡補開場
h = (card("8299", "目前處於空頭結構,現價勿追。建議等待回測 1955 元支撐不破。")
     + card("3260", "現價勿追。需等待股價回測 382.5 元支撐確認止穩。"))
out = fixed(h)
check("M2 整批缺窗口→首張補「今早 9:00 開盤後:」",
      out.count("今早 9:00 開盤後:") == 1 and
      out.index("今早 9:00 開盤後:") < out.index("3260"))
check("M2b 補後過 audit regex", TW_MORNING_ACTION_RE.search(out))

# M3: 已合規(tiffany 07-17 風格)→ 一字不動
h = card("2330", "今早 9:00 開盤後「已有部位者續抱,無部位者現價勿追」。")
check("M3 已合規日報 no-op", fixed(h) == h)

# M4: 美股卡(h-mark 非數字)零觸碰,即使缺窗口也不注入
h = card("NVDA", "今晚開盤後若回測 $201.95 不破,可分批低接。")
check("M4 美股卡零觸碰", fixed(h) == h)

# M5: MARKET=us 班次整體 no-op(晚報)
h = card("2330", "觀察明日開盤能否守住 2434 元。")
check("M5 us 班次 no-op(明日開盤保留)", fixed(h, market="us") == h)

# M6: 台股休市日 no-op(週六/週日/假日不可注入「今早開盤」)
check("M6 休市日 no-op", fixed(h, date=TW_CLOSED_DAY) == h)

# M7: 混合批(both 班次):美股卡有「今晚開盤」不算晨間窗口,台股卡仍要補
h = (card("NVDA", "今晚開盤後若回測 $201.95 不破,可分批低接。")
     + card("8299", "現價勿追,等待回測 1955 元支撐不破。"))
out = fixed(h, market="both")
check("M7 混合批只在台股卡注入", "今早 9:00 開盤後:現價勿追" in out
      and "今早 9:00 開盤後:今晚" not in out)

# M8: 台股卡有「9:00開盤」(修後 regex 認得)→ 不重複注入(07-15 案修後自然過)
h = card("2383", "下一步:觀察9:00開盤後能否守穩1255.5元。")
check("M8 「9:00開盤」已合規不重複注入", fixed(h) == h)

# ── 驗證者第14案 F1/F2/F3 防線層迴歸 ─────────────────────────
# V1(F1): 已合規卡裡「明日開盤前重新評估」=合法收盤後前瞻,不可被改寫
h = card("2330", "今早 9:00 開盤後守穩 1000 元則續抱;若今日收盤跌破,明日開盤前重新評估減碼。")
check("V1 已合規卡的「明日開盤」合法前瞻保留(F1)", fixed(h) == h)

# V2(F2a): 「明日早盤」單獨出現 → 改寫「今日早盤」且過 audit,無殘留時序錯亂
h = card("8299", "明日早盤觀察量能,現價勿追。")
out = fixed(h)
check("V2 「明日早盤」→「今日早盤」(F2a)",
      "今日早盤" in out and "明日早盤" not in out and TW_MORNING_ACTION_RE.search(out))

# V3(F2b): 「明早開盤」→「今早開盤」,不再注入矛盾前綴
h = card("2383", "觀察明早開盤能否守穩 1000 元。")
out = fixed(h)
check("V3 「明早開盤」→「今早開盤」且無矛盾注入(F2b)",
      "今早開盤" in out and "明早開盤" not in out and "今早 9:00 開盤後:" not in out)

# V4(F3): 價格「1090開盤」不算合規 → 樓地板注入照常發生
h = card("2451", "昨天以1090開盤走低,現價勿追,等待止穩。")
out = fixed(h)
check("V4 價格開盤回顧不擋樓地板注入(F3)", "今早 9:00 開盤後:" in out)

# V5: 「說明開盤」複合詞不可被改寫(pattern 要求 明+日/天/早)
h = card("2330", "以下說明開盤後的操作邏輯:回測 950 不破分批。")
out = fixed(h)
check("V5 「說明開盤」複合詞零觸碰", "說明開盤" in out and "說今早開盤" not in out)

# M9: audit#15 端到端 — 修防線後的 html 過 audit(共用 regex 無 drift)
import digest_audit  # noqa: E402
h = card("8299", "現價勿追,等待回測 1955 元支撐不破。")
out = fixed(h)
fails = digest_audit.audit_digest("<html><body>" + out + "</body></html>",
                                  TW_OPEN_DAY, [], ["8299"],
                                  {"tw_will_open_today": True}, market="tw")
check("M9 防線輸出過 audit#15(端到端)",
      not [f for f in fails if f["check"] == "tw_morning_action_missing"])
# M9b: 未修前同樣輸入必 FAIL(check 鑑別力不可退化)
fails_old = digest_audit.audit_digest("<html><body>" + h + "</body></html>",
                                      TW_OPEN_DAY, [], ["8299"],
                                      {"tw_will_open_today": True}, market="tw")
check("M9b 無防線的缺窗口日報 audit 必抓(鑑別力錨點)",
      [f for f in fails_old if f["check"] == "tw_morning_action_missing"])

ok = all(r for _, r in RESULTS)
print(f"\n{'✅ 全過' if ok else '❌ 有失敗'} ({sum(1 for _, r in RESULTS if r)}/{len(RESULTS)})")
sys.exit(0 if ok else 1)
