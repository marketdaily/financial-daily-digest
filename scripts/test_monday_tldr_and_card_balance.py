#!/usr/bin/env python3
"""2026-08-17 週一班事故迴歸測試(9 位收到閹割備援版,含老闆本人)。

同一班次兩個獨立根因,本檔各凍結一組:

【A】tldr_too_short / tldr_section_missing(12 人中招)
  週一/週末 prompt 只用白話寫「.tldr 區改成「📅 週一展望」標題,列 3-4 條」,而平日 prompt
  給的是逐字 <div class="tldr">…<ul><li> 骨架。各家模型於是把重點寫成 <div class="tldr-item">
  /<p>/<br> 分行 → audit 數 <li> 得 0 → tldr_too_short HIGH → retry 換模型還自創整個容器
  class(被 main._repair_undefined_classes 剝成 class="")→ tldr_section_missing → 備援版。
  日期分布佐證:08-03(週日)/08-10(週一)/08-17(週一)三班全中,平日五天零中。
  修法 ①analyzer._tldr_skeleton 把逐字骨架補回週一/週末 prompt(根因)
       ②analyzer._pp_tldr_structure 死防線:.tldr 在但無 <li> → 把條目原樣搬進 <ul><li>,
         **只搬結構不生內容**(真空的 TLDR 仍 0 條、2 條的仍 2 條 → audit 鑑別力不變)

【B】holdings_uncovered(老闆本人,attempt 與 retry 都中 → 硬錯,護盾救不了)
  _collect 用 seg.rfind('</div>') 當卡尾 ⇒ LLM 多吐一個 </div> 就被吃進卡片 ⇒ 卡片 div 不配對
  ⇒ digest_audit._section 巢狀配對提前收尾,剛好切掉卡尾 <!--h:SYM--> 標記;台股卡經
  _pp_expand_tickers 展開公司名後**只剩這個標記帶代號** ⇒ 判定該支沒卡。壞卡還會進跨用戶
  快取被全班次共用,retry 讀同一份 ⇒ 必再中。
  修法 ①analyzer._card_close_idx 改抓卡片自己配對的 </div>
       ②_div_balanced 進 _card_passes_audit 與「盡力卡」快取入口(繞過閘的那條路徑)

用法: .venv/bin/python scripts/test_monday_tldr_and_card_balance.py   (exit 0=全過)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyzer  # noqa: E402
import digest_audit  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


def tldr_bullets(html):
    return len(re.findall(r"<li[^>]*>", digest_audit._section(html, "tldr")))


def audit_checks(html, us=None, tw=None):
    fails = digest_audit.audit_digest(html, "2026-08-17", us or [], tw or [],
                                      {"tw_will_open_today": True}, market="tw")
    return {f["check"]: f["severity"] for f in fails}


# ══ A. TLDR ══════════════════════════════════════════════════════
# A1-A3: prompt 端 — 週一/週末格式必須帶逐字骨架(結構與平日 prompt 同款)
SKEL = analyzer._tldr_skeleton("T", ["a", "b"])
check("A1 骨架含 .tldr + .tldr-title + <ul> + <li> 四件套",
      '<div class="tldr">' in SKEL and '<div class="tldr-title">' in SKEL
      and "<ul>" in SKEL and "<li>a</li>" in SKEL)


def monday_prompts():
    """攔截 _llm_generate 取回四條週末/週一 prompt(不打任何 API)。"""
    seen = []
    real = analyzer._llm_generate
    analyzer._llm_generate = lambda p, *a, **k: (seen.append(p), '<div class="tldr"></div>')[1]
    try:
        for fn, kw in ((analyzer.generate_monday_report, {}),
                       (analyzer.generate_monday_report, {"depth": "simple"}),
                       (analyzer.generate_weekend_report, {}),
                       (analyzer.generate_weekend_report, {"depth": "simple"})):
            try:
                fn({"date": "2026-08-17", "us_market": {}, "tw_market": {},
                    "us_news": [], "tw_news": []}, [], [], **kw)
            except Exception as e:      # 生成鏈其餘部分不是本測範圍,prompt 已攔到就夠
                if not seen:
                    raise AssertionError(f"prompt 未攔到: {e}")
    finally:
        analyzer._llm_generate = real
    return seen


PROMPTS = monday_prompts()
# 只取「日報主 prompt」:TLDR 指示必在其中,而且骨架版(<div class="tldr">)與舊白話版
# (「.tldr 區改成…」)都含 tldr 字樣 ⇒ 退回白話寫法時這條仍被選中而判紅,鑑別力不流失。
# 同一次呼叫還會攔到 signal-card 等其他 _llm_generate 的 prompt,它們本來就不該有 TLDR 骨架
# (2026-08-17 首版把它們一起算 ⇒ A3 恆紅,而 guard 根本沒跑這支測試所以沒人發現)。
MAIN_PROMPTS = [p for p in PROMPTS if "tldr" in p]
check("A2 週一/週末主 prompt 全部攔到(4 條)", len(MAIN_PROMPTS) >= 4)
_with_skel = [p for p in MAIN_PROMPTS
              if '<div class="tldr">' in p and '<div class="tldr-title">' in p
              and re.search(r'<ul>\s*\n\s*<li>', p)]
check("A3 每條週一/週末 prompt 都給逐字 TLDR 骨架(舊版白話寫法會 FAIL)",
      bool(MAIN_PROMPTS) and len(_with_skel) == len(MAIN_PROMPTS))
check("A3b 舊版白話寫法已絕跡(不再只寫「.tldr 區改成…列 3-4 條」)",
      not any(re.search(r"\.tldr 區改成.{0,20}標題,列", p) for p in MAIN_PROMPTS))

# A4-A7: _pp_tldr_structure 死防線
BROKEN = (  # 08-17 實際型態:條目寫成 tldr-item,一條 <li> 都沒有
    '<div class="tldr"><div class="tldr-title">📅 週一展望</div>'
    '<div class="tldr-item">週末台積電 ADR 收跌 0.96%。</div>'
    '<div class="tldr-item">上週五加權指數跌 0.46%。</div>'
    '<div class="tldr-item">今早開盤偏空,重點在紀律。</div>'
    '<div class="tldr-item">⚠️ 避坑:別追高。</div></div>'
)
check("A4 修前:tldr-item 型態 audit 見到 0 條 <li>(HIGH,即實鍋)",
      tldr_bullets(BROKEN) == 0
      and audit_checks(BROKEN).get("tldr_too_short") == "high")
FIXED = analyzer._pp_tldr_structure(BROKEN)
check("A5 修後:4 條 <li>,tldr_too_short 不再失分", tldr_bullets(FIXED) == 4
      and "tldr_too_short" not in audit_checks(FIXED))
check("A5b 修後條目文字原樣保留(只搬結構不改內容)",
      "上週五加權指數跌 0.46%。" in FIXED and "⚠️ 避坑:別追高。" in FIXED
      and "tldr-item" not in FIXED)

# 鑑別力錨點:防線不得把「真的內容不足」變成假過關
EMPTY = '<div class="tldr"><div class="tldr-title">📅 週一展望</div></div>'
check("A6 真空 TLDR 修不出東西 → 仍 0 條 HIGH(防線不弱化)",
      tldr_bullets(analyzer._pp_tldr_structure(EMPTY)) == 0
      and audit_checks(analyzer._pp_tldr_structure(EMPTY)).get("tldr_too_short") == "high")
TWO = ('<div class="tldr"><div class="tldr-title">📅 週一展望</div>'
       '<p>只有一條重點。</p><p>還有第二條。</p></div>')
check("A7 只有 2 條的仍然只有 2 條(MED 照樣失分,不會被補成 3 條)",
      tldr_bullets(analyzer._pp_tldr_structure(TWO)) == 2
      and audit_checks(analyzer._pp_tldr_structure(TWO)).get("tldr_too_short") == "med")
OK4 = ('<div class="tldr"><div class="tldr-title">t</div><ul>'
       + "".join(f"<li>x{i}</li>" for i in range(4)) + "</ul></div>")
check("A8 已合規的 TLDR 零觸碰(no-op)", analyzer._pp_tldr_structure(OK4) == OK4)

# A9: 標題 class 正規化 → 偏多/偏空 chip 才注得進去(08-17 公版實鍋:整份零 tldr-chip)
SECLBL = ('<div class="tldr"><div class="section-label">📅 週一展望</div>'
          '<ul><li>a</li><li>b</li><li>c</li></ul></div>'
          '<div class="verdict bearish"><div class="verdict-emoji">📉 偏空</div></div>')
check("A9 修前:標題寫成 section-label → chip 注入 miss(實鍋)",
      "tldr-chip" not in analyzer._pp_hoist_verdict_chip(SECLBL))
check("A9b 修後:正規化回 tldr-title,chip 注得進去且 <li> 沒被動到",
      "tldr-chip" in analyzer._pp_hoist_verdict_chip(analyzer._pp_tldr_structure(SECLBL))
      and tldr_bullets(analyzer._pp_tldr_structure(SECLBL)) == 3)

# ══ B. signal-card div 配對 → holdings_uncovered ══════════════════
def raw_card(sym, extra_close=False, wrapped=False):
    # ⚠️ reason 必須自己就過 _card_passes_audit 的 ≥70 字深度底線(2026-08-17 首版只有 67 字 ⇒
    # 不論 div 配不配對都不會過 ⇒ B3「壞卡不得過」根本沒測到 _div_balanced,是裝飾性斷言;
    # B2b「切出來的卡仍完整」也因此恆紅)。改動這段文字時務必重跑 B2b/B3 確認兩邊都還有鑑別力。
    body = (f'<div class="signal-card buy"><div class="signal-card-top">'
            f'<span class="signal-ticker">{sym}</span></div>'
            f'<div class="signal-body"><div class="signal-reason">'
            f'上週五收在均線之上,今早 9:00 開盤後若守穩 1000 元可續抱,跌破 980 元先減碼,'
            f'目標看 1080 元;量能與外資買賣超是關鍵觀察點,盤中另留意 1020 元附近的賣壓。</div>'
            + ('</div>' if extra_close else '') +
            '<div class="signal-battle-plan">'
            '<div class="battle-row">建議買價</div><div class="battle-row">賺錢目標</div>'
            '<div class="battle-row">止損賣價</div></div></div></div>')
    return f'<div class="signal-grid">{body}</div>' if wrapped else body


def collect_card(raw):
    """複刻 _collect 的切卡步驟(舊版=rfind,新版=_card_close_idx)。"""
    seg = raw
    start = seg.find('<div class="signal-card')
    end = analyzer._card_close_idx(seg, start)
    return seg[start:end].strip() if end > 0 else ""


# B0:fixture 前提錨。乾淨卡若自己就不合格,B3 的「壞卡不得過」會因為別的門檻而恆綠(假綠)。
check("B0 fixture 前提:乾淨卡本身就過 _card_passes_audit(否則 B2b/B3 失去鑑別力)",
      analyzer._card_passes_audit(raw_card("2330")))
check("B1 _div_balanced:正常卡 True、多一個 </div> False、少一個 False",
      analyzer._div_balanced(raw_card("2330"))
      and not analyzer._div_balanced(raw_card("2330", extra_close=True))
      and not analyzer._div_balanced(raw_card("2330")[:-6]))

# B2:切卡只吃卡片自己的 </div> —— 整批被多包一層容器時,舊 rfind 會把容器的 </div> 吃進來
WRAPPED = raw_card("2330", wrapped=True)
check("B2 外層多包容器:新切法不吃容器 </div>(舊 rfind 會吃 → 卡片不配對)",
      analyzer._div_balanced(collect_card(WRAPPED))
      and not analyzer._div_balanced(
          WRAPPED[WRAPPED.find('<div class="signal-card'):WRAPPED.rfind("</div>") + 6]))
check("B2b 切出來的卡仍完整(3 條 battle-row 沒被切掉)",
      analyzer._card_passes_audit(collect_card(WRAPPED)))

# B3:卡片內部多一個 </div> → 被閘門擋下(改用 deterministic 卡),不再進跨用戶快取
check("B3 卡內多 </div> 的壞卡不得過 _card_passes_audit(修前會過)",
      not analyzer._card_passes_audit(raw_card("2330", extra_close=True)))

# B4:端到端 —— 壞卡放行時 holdings_uncovered 誤判(實鍋),擋掉後不再誤判
def digest(cards_html):
    return ('<html><body><div class="tldr"><div class="tldr-title">t</div><ul>'
            '<li>a</li><li>b</li><li>c</li></ul></div>'
            '<div class="signal-grid">' + cards_html + '</div>'
            '<div class="signal-disclaimer">x</div></body></html>')


def marked(sym, extra_close=False):
    """模擬生產:台股卡展開公司名後只剩 <!--h:SYM--> 帶代號(代號不出現在可見文字)。"""
    c = raw_card(sym, extra_close=extra_close).replace(
        f'<span class="signal-ticker">{sym}</span>', '<span class="signal-ticker">台積電</span>')
    return analyzer._mark_card(c, sym)


check("B4 壞卡放行 → holdings_uncovered 誤判(凍結實鍋,證明機制)",
      audit_checks(digest(marked("2330", extra_close=True)), tw=["2330"])
      .get("holdings_uncovered") == "high")
check("B4b 同一支改走 deterministic 卡(閘門擋下後的實際路徑)→ 不再誤判",
      "holdings_uncovered" not in audit_checks(digest(marked("2330")), tw=["2330"]))
# 鑑別力錨點:真的漏掉一支仍要被抓
check("B5 真的漏一支持股仍必抓(檢查不被弱化)",
      audit_checks(digest(marked("2330")), tw=["2330", "2454"])
      .get("holdings_uncovered") == "high")

ok = all(r for _, r in RESULTS)
print(f"\n{'✅ 全過' if ok else '❌ 有失敗'} ({sum(1 for _, r in RESULTS if r)}/{len(RESULTS)})")
sys.exit(0 if ok else 1)
