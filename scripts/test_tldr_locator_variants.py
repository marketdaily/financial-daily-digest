#!/usr/bin/env python3
"""2026-08-24 週一早報事故迴歸測試(老闆本人 + tiffany 收到閹割備援版)。

【根因:tldr_section_missing 是誤判,不是真的沒有 TLDR】
digest_audit 定位 .tldr 用的是 `<div class="tldr"` —— 隱含三個沒人寫下來的要求:
class 必須是**第一個屬性**、標籤必須是 **div**、tldr 必須是**唯一 class**。
跑完整條生產鏈(main._repair_undefined_classes → premailer 內聯)實測:

    <section class="tldr">        → .tldr 樣式正常內聯,信是好的 → 判 MISSING ❌
    <div class="tldr news-card">  → .tldr 樣式正常內聯,信是好的 → 判 MISSING ❌
    <div id="x" class="tldr">     → .tldr 樣式正常內聯,信是好的 → 判 MISSING ❌

08-24 早報三位第一輪中招(全部是 groq:gpt-oss-120b 這支模型寫的),兩位連 retry 都中,
→ deterministic fallback。同班次沒有任何其他 check 失分 = 內容其實是好的。
而 analyzer._pp_tldr_structure(08-17 補的死防線)用同一條 regex 定位 ⇒ 兩層**同時失明**。

修法(收緊誤判,不放寬防線):
  ①digest_audit._tldr_open/_tldr_block —— 改用瀏覽器/CSS 同一套判準:區塊級標籤
    (div/section)+ class token 命中 "tldr"(單雙引號、屬性順序、多 class 皆可)。
  ②analyzer._pp_tldr_structure 用同一個定位器,並把變體容器正規化回 <div class="tldr">。

**防線不可被弱化**:token 必須正好是 "tldr"。容器被改名(tldr-box)或被
_repair_undefined_classes 剝成 class="" —— 那是真的掉樣式 —— 仍然定位不到 → 照樣 HIGH;
定位到但一條 <li> 都沒有 → tldr_too_short HIGH 照樣把它打成備援。本檔兩個方向都凍結。

用法: .venv/bin/python scripts/test_tldr_locator_variants.py   (exit 0=全過)
⚠️ 零真實 API、零 .env 依賴、零寄信:只 import analyzer/digest_audit/main 的純函式。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyzer  # noqa: E402
import digest_audit  # noqa: E402
import main  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


BODY = ('<div class="tldr-title">📅 週一展望</div>'
        '<ul><li>週末最大事件</li><li>今早開盤 gap 方向</li><li>持股怎麼動</li></ul>')

# 「信其實是好的」的容器變體 —— 全部必須被認得
GOOD = {
    "canonical":      ('<div class="tldr">', "</div>"),
    "section 標籤":    ('<section class="tldr">', "</section>"),
    "多 class 在後":   ('<div class="tldr news-card">', "</div>"),
    "多 class 在前":   ('<div class="news-card tldr">', "</div>"),
    "id 排在 class 前": ('<div id="top" class="tldr">', "</div>"),
    "style 排 class 前": ('<div style="margin:0" class="tldr">', "</div>"),
    "單引號":          ("<div class='tldr'>", "</div>"),
    "class = 有空白":   ('<div class = "tldr">', "</div>"),
}
# 定位器本身大小寫不敏感,但生產鏈上游 main._escape_stray_lt 的標籤白名單是**大小寫敏感**的
# ⇒ <DIV> 會被整段跳脫成 &lt;DIV ...> 純文字,那封信是真的壞掉。所以大寫標籤只在 A 段
# (定位器單元)當正例,B 段(生產鏈)必須仍是 HIGH。這是另一個獨立的既存缺陷,不在本次
# 修復範圍(改 _escape_stray_lt 的 re.I 會動到整份日報的跳脫行為,要另開任務驗)。
UPPER = ('<DIV CLASS="tldr">', "</DIV>")
# 「真的沒有 TLDR / 真的掉了樣式」—— 全部必須仍判 MISSING
BAD = {
    "整區不見":        ('<div class="market-summary">', "</div>"),
    "容器被改名":      ('<div class="tldr-box">', "</div>"),
    "class 被剝成空":  ('<div class="">', "</div>"),
    "只剩 tldr-title": ('<div class="section-label">', "</div>"),
}


# ══ A. 定位器單元 ═══════════════════════════════════════════════════
for name, (open_tag, close_tag) in GOOD.items():
    block = digest_audit._tldr_block(open_tag + BODY + close_tag)
    check(f"A 定位得到:{name}", block and "tldr-title" in block and block.endswith(close_tag))
for name, (open_tag, close_tag) in BAD.items():
    check(f"A 仍判 MISSING:{name}", not digest_audit._tldr_block(open_tag + BODY + close_tag))

# 巢狀:內層 div 不可以提早切斷 .tldr 區塊
nested = ('<section class="tldr"><div class="tldr-title">T</div><ul><li><div>x</div>a</li></ul>'
          '</section><div class="market-summary">後面這段不算 TLDR</div>')
nb = digest_audit._tldr_block(nested)
check("A 巢狀不提早收尾", nb.endswith("</section>") and "market-summary" not in nb)

# _section 重構後行為不變(signal-card 那種 regex class 名 + 巢狀切分照舊)
cards = ('<div class="signal-card up"><div class="battle-row"><div>x</div></div></div>'
         '<div class="signal-card down"><div class="battle-row"></div></div>')
secs = digest_audit._all_sections(cards, r"signal-card[^\"]*")
check("A _section 重構等價(2 張卡各自配對)",
      len(secs) == 2 and secs[0].endswith("</div>") and "signal-card down" not in secs[0])


# ══ B. 生產鏈端到端:build_email_html → audit_digest ═══════════════
def chain_checks(inner):
    html = main.build_email_html("2026-08-24", inner)
    fails = digest_audit.audit_digest(html, "2026-08-24", [], [],
                                      {"tw_will_open_today": True}, market="tw",
                                      base_css=main.CSS)
    return {f["check"]: f["severity"] for f in fails}, html


for name, (open_tag, close_tag) in GOOD.items():
    fails, html = chain_checks(open_tag + BODY + close_tag)
    # premailer 把 .tldr 的樣式內聯進去了嗎?(屬性順序不固定:模型自帶 style 時
    # premailer 會就地合併,style 可能排在 class 前面 → 兩個屬性各自找,不綁順序)
    tag = re.search(r'<(?:div|section)[^>]*class="[^"]*\btldr\b[^"]*"[^>]*>', html) \
        or re.search(r'<(?:div|section)[^>]*style="[^"]*"[^>]*class="[^"]*\btldr\b[^"]*"[^>]*>', html)
    styled = bool(tag and "border-left" in tag.group(0))
    check(f"B 不再誤判備援:{name}", "tldr_section_missing" not in fails)
    check(f"B 樣式確實有內聯(信是好的):{name}", styled)

for name, (open_tag, close_tag) in BAD.items():
    fails, _ = chain_checks(open_tag + BODY + close_tag)
    check(f"B 真問題仍 HIGH:{name}",
          fails.get("tldr_section_missing") == "high")

# 大寫標籤:定位器認得(A 段),但生產鏈把它跳脫成文字 → 信是壞的 → HIGH 才對
check("A 定位得到:大寫標籤", bool(digest_audit._tldr_block(UPPER[0] + BODY + UPPER[1])))
upper_fails, upper_html = chain_checks(UPPER[0] + BODY + UPPER[1])
check("B 大寫標籤被上游跳脫成文字 → 仍 HIGH(既存另一缺陷)",
      upper_fails.get("tldr_section_missing") == "high" and "&lt;DIV" in upper_html)

# 定位得到但一條 <li> 都沒有 = 空殼 TLDR,仍要被 HIGH 打成備援(鑑別力沒被換掉)
empty_fails, _ = chain_checks('<section class="tldr"><div class="tldr-title">T</div></section>')
check("B 空殼 TLDR 仍 HIGH(tldr_too_short)",
      empty_fails.get("tldr_too_short") == "high")
two_fails, _ = chain_checks('<div class="tldr news-card"><div class="tldr-title">T</div>'
                            "<ul><li>a</li><li>b</li></ul></div>")
check("B 只有 2 條仍 MED(不多不少)", two_fails.get("tldr_too_short") == "med")


# ══ C. 死防線 _pp_tldr_structure ════════════════════════════════════
# C1 變體容器 + 條目不是 <li>(08-17 那種寫法)→ 搬進 <ul><li> 且容器正規化
messy = ('<section class="tldr"><div class="section-label">📅 週一展望</div>'
         '<div class="tldr-item">重點一</div><div class="tldr-item">重點二</div>'
         '<div class="tldr-item">重點三</div></section>')
fixed = analyzer._pp_tldr_structure(messy)
check("C1 變體容器正規化成 <div class=\"tldr\">", fixed.startswith('<div class="tldr">'))
check("C1 條目搬進 <li>(3 條)", len(re.findall(r"<li>", fixed)) == 3)
check("C1 標題正規化回 tldr-title 且保留原字",
      '<div class="tldr-title">📅 週一展望</div>' in fixed)
check("C1 沒有殘留 </section>", "</section>" not in fixed)
check("C1 修完 audit 過關",
      "tldr_section_missing" not in chain_checks(fixed)[0])

# C2 變體容器但條目已經是 <li> → 只換容器,條目原樣不動
sect_li = '<section class="tldr">' + BODY + "</section>"
fixed2 = analyzer._pp_tldr_structure(sect_li)
check("C2 section+已有 li → 容器換掉、3 條原樣",
      fixed2.startswith('<div class="tldr">') and len(re.findall(r"<li>", fixed2)) == 3
      and "今早開盤 gap 方向" in fixed2)

# C3 已經是標準骨架 → 一個 byte 都不准動(不製造 golden churn)
canon = '<div class="tldr">' + BODY + "</div>"
check("C3 標準骨架原樣 passthrough", analyzer._pp_tldr_structure(canon) == canon)

# C4 真的空的 TLDR → 不生內容(搬不出東西就原樣不動)
empty = '<section class="tldr"><div class="tldr-title">T</div></section>'
check("C4 空 TLDR 不無中生有", "<li>" not in analyzer._pp_tldr_structure(empty))

# C5 沒有 TLDR 區塊 → 原樣不動(不會把別的區塊誤認成 TLDR)
noneish = '<div class="market-summary">大盤</div><div class="tldr-title">孤兒標題</div>'
check("C5 無 TLDR 容器時原樣不動", analyzer._pp_tldr_structure(noneish) == noneish)

# C6 正規化後 chip hoist 接得上(08-17 週一 tldr-chip 全班消失的那條下游)
with_verdict = (sect_li + '<div class="verdict bullish"><div class="verdict-emoji">📈 偏多</div>'
                "<div class=\"verdict-text\">x</div></div>")
hoisted = analyzer._pp_hoist_verdict_chip(analyzer._pp_tldr_structure(with_verdict))
check("C6 正規化後 verdict chip 掛得上 tldr-title", 'class="tldr-chip bullish"' in hoisted)


# C7 容器沒收尾 → 死防線寧可不動(重寫會把整封信後半段全吞進 TLDR)
unclosed = ('<section class="tldr"><div class="tldr-title">T</div><div>重點一</div>'
            '<div class="section-label">📰 週末重點新聞</div>'
            '<div class="news-card"><div class="news-headline">H</div></div>')
check("C7 容器未收尾時不重寫(不吞掉後面的新聞卡)",
      analyzer._pp_tldr_structure(unclosed) == unclosed)

bad = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 通過")
if bad:
    print("❌ 失敗:" + " · ".join(bad))
sys.exit(1 if bad else 0)
