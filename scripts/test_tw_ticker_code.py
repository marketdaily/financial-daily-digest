#!/usr/bin/env python3
"""台股「名稱(代號)」顯示規則迴歸測試(2026-08-18,open #421 的結案)。

2026-07-01(684824c9)為了擋 LLM 掰錯代號,把內文所有「名稱(2330)」的括號代號**一律剝掉**,
副作用是整份日報的台股完全沒有代號可下單(而確定性備援版 generate_deterministic_fallback
反而寫「台積電 TSMC(2330)」=同一封信裡兩套規則),也與 CLAUDE.md「台股顯示要同時有
代碼+公司名」相衝。本檔凍結新規則:**查表驗證後保留**,而不是看到就砍。

  ① 名稱與代號對得上 → 原樣保留(台積電(2330))
  ② 名稱在表裡但代號錯 → 改成該名稱的正確代號(台積電(2454) → 台積電(2330));LLM 掰的代號
     一樣射不出去,但用戶拿到的是**正確資訊**而不是沒有資訊
  ③ 前後文找不到任何已知台股名 → 維持 2026-07-01 的舊行為剝掉(無從驗證不放行)
  ④ 不是台股代號的四位數(年份/價位)→ 不碰
  ⑤ 美股括號代號(輝達(NVDA))→ 不碰

用法: .venv/bin/python scripts/test_tw_ticker_code.py   (exit 0=全過)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyzer  # noqa: E402
import digest_audit  # noqa: E402
import stock_names  # noqa: E402

RESULTS = []
HINT = {"2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2025": "千興"}


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


def pp(html):
    return analyzer._pp_expand_tickers(html, HINT)


# ① 對得上就留
check("正確的名稱+代號原樣保留",
      "台積電(2330)" in pp("<p>台積電(2330)昨日收平,量縮整理。</p>"))
check("全形括號同樣保留",
      "台積電（2330）" in pp("<p>台積電（2330）昨日收平。</p>"))
check("名稱與代號之間隔一個空白也算對得上",
      "台積電 (2330)" in pp("<p>台積電 (2330)昨日收平。</p>"))

# ② 代號錯 → 改正,不是剝掉
fixed = pp("<p>台積電(2454)今日走勢平穩。</p>")
check("LLM 寫錯代號被改正成正確代號", "台積電(2330)" in fixed and "2454" not in fixed)
fixed2 = pp("<p>鴻海（2330）法說會後量能放大。</p>")
check("全形括號的錯代號也被改正", "鴻海（2317）" in fixed2 and "2330" not in fixed2)
# 舊版只在「代號本身在名稱表裡」時才動手 ⇒ 掰出來的 9999 這種假代號原封不動寄出去,
# 這是 2026-07-01 那版就有的洞(剝掉真代號、放行假代號)。名字認得出來就一律以名字為準。
fixed3 = pp("<p>台積電(9999)昨日收平。</p>")
check("名稱表裡根本沒有的假代號也被改正(舊版會原樣放行)",
      "台積電(2330)" in fixed3 and "9999" not in fixed3)

# ③ 無從驗證 → 沿用舊行為剝掉
stripped = pp("<p>加權指數(2330)量縮整理。</p>")
check("前後文沒有已知台股名 → 代號剝掉(不放行未驗證數字)",
      "2330" not in stripped and "加權指數" in stripped)

# ④/⑤ 不誤傷
check("非台股代號的四位數不碰", "(1999)" in pp("<p>自 (1999) 年以來最大跌幅。</p>"))
check("美股括號代號不碰", "輝達(NVDA)" in pp("<p>輝達(NVDA)昨夜收紅。</p>"))

# ⑥ signal-card 徽章:台股要看得到代號(下單用),且不是裸代號
badge = stock_names.badge_html("2330", HINT)
check("台股徽章同時有中文名與代號", "台積電" in badge and "2330" in badge)
check("美股徽章維持原樣(公司名+小灰代號)",
      "輝達" in stock_names.badge_html("NVDA") and "NVDA" in stock_names.badge_html("NVDA"))
card = '<div class="signal-card hold"><span class="signal-ticker">2330</span></div>'
expanded = pp(card)
check("卡片裸代號仍會展開成名稱+代號", "台積電" in expanded and "2330" in expanded)
check("展開後不再被 audit 判為裸代號",
      not any(f["check"] == "tw_ticker_bare_code" for f in digest_audit.audit_digest(
          expanded, "2026-08-18", tw_holdings=["2330"])))
check("卡片真的裸代號時 audit 仍抓得到(反對照,防守衛被我改瞎)",
      any(f["check"] == "tw_ticker_bare_code" for f in digest_audit.audit_digest(
          card, "2026-08-18", tw_holdings=["2330"])))

# ⑦ 名稱表為空(TWSE/TPEx 全滅)時不可把代號吃掉 —— 那是 07-09 事故的情境,
#    此時保留原文比清成無資訊更安全(audit 的 tw_ticker_bare_code 仍會抓卡片裸代號)。
check("名稱表全滅時不動內文括號代號",
      "台積電(2330)" in analyzer._pp_expand_tickers("<p>台積電(2330)昨日收平。</p>", {}))

bad = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 通過")
if bad:
    print("失敗:", bad)
sys.exit(1 if bad else 0)
