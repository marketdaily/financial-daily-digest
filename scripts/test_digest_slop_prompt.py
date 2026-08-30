#!/usr/bin/env python3
"""open item #660 迴歸:日報 prompt 的反樣板句鐵則 + digest_slop_watch 判準。

凍結兩件事:
 A. analyzer._ANTI_SLOP_BLOCK 真的被四支 prompt 用到(平日 / 週末 / 週一 / signal-card),
    而且是「插值進 f-string」不是躺在註解或普通字串裡 —— 用 AST 看 JoinedStr 內有沒有
    Name(_ANTI_SLOP_BLOCK),不是 grep 檔案文字(grep 過得了註解,AST 過不了)。
 B. digest_slop_watch 的門檻真的會對 08-29 那種樣板日報變紅、對乾淨日報保持綠,
    且 lint 積木缺席 / EPOCH 後長期零日報這兩種「瞎掉」狀態也是紅。
    (B 用合成 fixture,不讀生產 output/,不打任何 LLM、不寄任何信。)

用法: python3 scripts/test_digest_slop_prompt.py   (exit 0 = 全過)
"""
import ast
import datetime as dt
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
R = []


def check(name, cond):
    R.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


# ── A. prompt 契約 ────────────────────────────────────────────────────────────
SRC = io.open(ROOT / "analyzer.py", encoding="utf-8").read()
TREE = ast.parse(SRC)

BLOCK_NAME = "_ANTI_SLOP_BLOCK"
block_val = None
for n in TREE.body:
    if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == BLOCK_NAME for t in n.targets):
        block_val = ast.literal_eval(n.value)
check("analyzer 有模組層 _ANTI_SLOP_BLOCK 常數(單一真源)", isinstance(block_val, str) and len(block_val) > 200)

if isinstance(block_val, str):
    # 負面清單:實測命中最兇的兩句必須被點名
    check("負面清單點名「顯示…信心」", "信心" in block_val and ("顯示" in block_val))
    check("負面清單點名「將是關注焦點」", "關注焦點" in block_val)
    # 正面規範:光有負面清單模型會改用別的樣板,必須有「要怎麼寫」
    check("同時給正面規範(具體數字/門檻)", "數字" in block_val and ("門檻" in block_val or "百分比" in block_val))
    check("正面規範要求每則收尾句型不同", "句型" in block_val)


def fstrings_using(func_name):
    """func_name 內所有 f-string 裡,有幾個插了 _ANTI_SLOP_BLOCK。"""
    hits = 0
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name:
            for m in ast.walk(n):
                if isinstance(m, ast.JoinedStr):
                    for v in m.values:
                        if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) \
                                and v.value.id == BLOCK_NAME:
                            hits += 1
    return hits


for fn, label in [("_gr_build_prompt", "平日日報"),
                  ("generate_weekend_report", "週末日報"),
                  ("generate_monday_report", "週一日報"),
                  ("_signal_card_format_rules", "signal-card 批次")]:
    check(f"{label} prompt({fn})有插值 {BLOCK_NAME}", fstrings_using(fn) >= 1)

# 端到端:真的呼叫得到的兩支,渲染後字面出現且沒有留下未插值的大括號
try:
    import analyzer as A
    card = A._signal_card_format_rules({"tw_will_open_today": True, "us_will_open_tonight": True})
    wd = A._gr_build_prompt("2026-08-30", ["2330"], True, "", "", "", "", "", "", "", "",
                            ["", "", "", ""], "", "", "", "", "")
    check("signal-card 規則渲染後含禁用清單且無 {_ANTI_SLOP_BLOCK} 字面殘留",
          "禁用樣板句" in card and "{" + BLOCK_NAME + "}" not in card)
    check("平日 prompt 渲染後含禁用清單且無字面殘留",
          "禁用樣板句" in wd and "{" + BLOCK_NAME + "}" not in wd)
except Exception as e:  # 缺 .env / 依賴時不假裝過關
    check(f"analyzer 可 import 並渲染 prompt(實際:{type(e).__name__}: {e})", False)

# ── B. digest_slop_watch 判準 ────────────────────────────────────────────────
import digest_slop_watch as W  # noqa: E402

SLOPPY = ("<html><body>" + "".join(
    f"<p>{c}的表現顯示市場對其信心充足,雲端業務將是關注焦點。</p>"
    for c in ["谷歌", "微軟", "特斯拉", "蘋果"]) + "</body></html>")
CLEAN = ("<html><body><p>台積電（2330）收 1,085 元,外資買超 1.2 萬張。"
         "10/16 法說會看 N2 稼動率;跌破 1,040 元(20 日線)就減碼。</p></body></html>")


def _scan(html, name):
    with tempfile.TemporaryDirectory() as d:
        io.open(os.path.join(d, name), "w", encoding="utf-8").write(html)
        return W.collect(d, epoch="2026-01-01", window=14)


rows_slop = _scan(SLOPPY, "digest_2026-09-01.html")
rows_clean = _scan(CLEAN, "digest_2026-09-01.html")
check("樣板日報被算出 ≥ 門檻的命中次數", rows_slop and rows_slop[0][2] >= W.MAX_PER_DIGEST)
check("乾淨日報零命中", rows_clean and rows_clean[0][2] == 0)
check("judge 對樣板日報回紅", not W.judge(rows_slop, "2026-01-01", dt.date(2026, 9, 2))[0])
check("judge 對乾淨日報回綠", W.judge(rows_clean, "2026-01-01", dt.date(2026, 9, 2))[0])

# 慢性回流:每份都只有 2 次(單份不超標)但平均超門檻 → 仍要紅
chronic = [(f"d{i}.html", "2026-09-0%d" % (i + 1), 2, 0.7, []) for i in range(5)]
check("慢性回流(單份不超標但平均超門檻)也回紅",
      not W.judge(chronic, "2026-01-01", dt.date(2026, 9, 9))[0])

# 瞎掉的兩種形狀
check("EPOCH 後長期零日報 = 紅(不是沒事)",
      not W.judge([], "2026-08-30", dt.date(2026, 9, 20))[0])
check("EPOCH 後幾天內零日報 = 寬限期綠",
      W.judge([], "2026-08-30", dt.date(2026, 8, 31))[0])

_real = W.LINT_DIR
try:
    W.LINT_DIR = "/nonexistent/ai_slop_lint"
    try:
        W.collect(str(ROOT / "output"))
        blind = False
    except RuntimeError:
        blind = True
finally:
    W.LINT_DIR = _real
check("lint 積木缺席 = 前提錯拋出(不 fail-open 假綠)", blind)

# 生產 output/ 現況(不判斷內容,只確認掃得到檔、路徑沒寫死錯)
check("生產 output/ 目錄存在且掃得到 digest 檔",
      len(W.collect(str(ROOT / "output"), epoch="2026-01-01", window=5)) == 5)


# ── C. _pp_despam_filler 確定性後製層 ────────────────────────────────────────
# 為什麼要有這一段:A/B 實測(gemini-2.5-flash,同一支週末 prompt + 同一份輸入各 5 輪)
# 顯示光靠 prompt 負面清單擋不住「將是關鍵/觀察重點」變體(5 輪中 4 輪仍出現),
# 真正把數字壓到 0 的是這一層。它壞掉 = #660 就回來了,所以要逐條凍結。
try:
    import analyzer as _A

    PP = [
        # (輸入, 必須消失的字, 必須留下的字)
        ("<p>雲端業務和廣告收入將是關注焦點。</p>", "將是關注焦點", "雲端業務和廣告收入"),
        ("<p>下週財報將是觀察重點,若營收未達預期,可能影響股價。</p>", "將是觀察重點", "若營收未達預期"),
        ("<p>微軟 Azure 增長率將是關鍵。若財報良好,有望突破 517.78。</p>", "將是關鍵", "517.78"),
        ("<p>台幣連五週升值，顯示外資對台灣市場仍具信心。</p>", "信心", "台幣連五週升值"),
        ("<p>此舉影響其服務營收，並反映公司對其內容價值的信心。</p>", "信心", "此舉影響其服務營收"),
        ("<p>鴻海上漲 0.40%。新能源專案有助於提升其企業形象與長期發展潛力。</p>", "有助於提升", "鴻海上漲 0.40%"),
    ]
    for src, gone, keep in PP:
        out = _A._pp_despam_filler(src)
        check(f"後製清除「{gone}」且保留「{keep[:10]}」", gone not in out and keep in out)

    # 版面標籤前綴不可被吃掉(首版真的吃掉過)
    lbl = "<div class='news-why'>💡 為什麼重要：昨晚那斯達克大漲 2.07%，顯示市場對科技股的信心增強。這對今天台股開盤有帶動作用。</div>"
    o = _A._pp_despam_filler(lbl)
    check("後製保留「💡 為什麼重要：」標籤前綴", "為什麼重要：" in o and "信心" not in o and "帶動作用" in o)

    # 乾淨內容 / 連結 / 純代號 一個字都不准動(誤殺面)
    for untouched in ["<p>台積電收 NT$2,420，站上 MA20，跌破 NT$2,389 減碼。</p>",
                      '<a class="read-more" href="https://x.com/a?b=1&c=2">閱讀原文 →</a>',
                      "<span class=\"signal-ticker\">2330</span>",
                      "<div class=\"signal-reason\">輝達回測 $207.23 不破再分批接,跌破 $200.35 停損。</div>"]:
        check(f"乾淨內容原樣不動:{untouched[:34]}…", _A._pp_despam_filler(untouched) == untouched)

    # 絕不把任何原本有字的元素清空
    import re as _re
    holes = 0
    for src, _g, _k in PP:
        t0 = [x for x in _re.findall(r">([^<>]+)<", src) if x.strip()]
        t1 = [x for x in _re.findall(r">([^<>]+)<", _A._pp_despam_filler(src)) if x.strip()]
        holes += max(0, len(t0) - len(t1))
    check("後製不會把任何原本有字的元素清空", holes == 0)

    # 已接進 _postprocess_html(只寫函式沒接線 = 生產完全沒跑到)
    import inspect
    import re as _re_mod
    pp_src = inspect.getsource(_A._postprocess_html)
    check("_pp_despam_filler 已接進 _postprocess_html", "_pp_despam_filler(html)" in pp_src)
    # 比「呼叫點」的先後,不是比原文出現位置——註解裡提到名字會讓後者判錯(首版就中了)
    _calls = [m.group(1) for m in _re_mod.finditer(r"^\s*html = (_pp_\w+)\(", pp_src, _re_mod.M)]
    check("_pp_despam_filler 呼叫點排在 _pp_markdown_bold 之前(** → <strong> 會讓 [^<] 漏網)",
          "_pp_despam_filler" in _calls and "_pp_markdown_bold" in _calls
          and _calls.index("_pp_despam_filler") < _calls.index("_pp_markdown_bold"))

    # 判準漂移:analyzer 手上這三條 pattern 必須跟 ai_slop_lint 的 ZH_STRUCT 逐字相同。
    # (生產熱路徑不能 import ~/autonomous 的積木,所以必然有兩份;兩份不一致就是這裡紅。)
    LINT = os.path.expanduser("~/autonomous/capabilities/ai_slop_lint")
    if os.path.isdir(LINT):
        sys.path.insert(0, LINT)
        import logic as _lint
        zh = {pat for pat, *_rest in (e if isinstance(e, tuple) else (e,) for e in _lint.ZH_STRUCT)}
        for name, pat in [("_SLOP_FILLER_TAIL", _A._SLOP_FILLER_TAIL),
                          ("_SLOP_CONFIDENCE", _A._SLOP_CONFIDENCE),
                          ("_SLOP_PUFF", _A._SLOP_PUFF)]:
            check(f"{name} 與 ai_slop_lint ZH_STRUCT 逐字一致(無漂移)", pat in zh)
    else:
        check("ai_slop_lint 積木在(才比得了漂移)", False)
except Exception as e:
    check(f"_pp_despam_filler 區段可執行(實際:{type(e).__name__}: {e})", False)


bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} 過")
sys.exit(1 if bad else 0)
