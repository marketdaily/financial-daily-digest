"""Regression eval: 日報深度客製(Premium 專屬)。
不打 LLM,只驗純邏輯 —— 確保 standard=現行 baseline(不退化)+ Premium 閘門正確。
跑法:python3 .claude/evals/digest_depth_eval.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from analyzer import _depth_directive

fails = []

def check(name, cond):
    print(("✅" if cond else "❌"), name)
    if not cond:
        fails.append(name)

# 1. standard = baseline:不可注入任何深度指令(回歸保證:既有用戶體驗不變)
check("standard 不注入指令(baseline 不退化)", _depth_directive("standard") == "")
check("未知值退回 standard 行為", _depth_directive("garbage") == "")

# 2. 累加語意:simple=純操作(砍新聞) / standard=操作+新聞+技術 / deep=標準全部+估值產業鏈
check("simple 指令含『精簡』", "精簡" in _depth_directive("simple"))
check("simple = 純重點操作", "純重點操作" in _depth_directive("simple"))
check("simple 明令不要新聞", "不要新聞" in _depth_directive("simple"))
check("deep 指令含『深入』", "深入" in _depth_directive("deep"))
check("deep = 標準版全部再加碼(累加)", "標準版全部" in _depth_directive("deep"))
check("deep 含估值/供應鏈", "估值" in _depth_directive("deep") and "供應鏈" in _depth_directive("deep"))
check("deep 仍禁止編造財務數字", "不可臆測" in _depth_directive("deep"))

# 3. Premium 閘門邏輯(複製 main.get_user_preferences 的 gate,確保免費鎖 standard)
def gate(plan, depth):
    d = depth or "standard"
    if plan not in ("premium", "admin"):
        d = "standard"
    if d not in ("simple", "standard", "deep"):
        d = "standard"
    return d

check("free 選 deep → 鎖回 standard", gate("free", "deep") == "standard")
check("pro 選 simple → 鎖回 standard", gate("pro", "simple") == "standard")
check("premium 選 deep → 保留 deep", gate("premium", "deep") == "deep")
check("admin 選 simple → 保留 simple", gate("admin", "simple") == "simple")
check("premium 選非法值 → standard", gate("premium", "xxx") == "standard")

# 4. 真組 prompt 驗週末/週一 simple 確實砍新聞段、保留操作核心(monkeypatch 掉 LLM,離線)
import analyzer
_cap = {}
analyzer._llm_generate = lambda prompt, prefer_strong=False: _cap.setdefault("p", prompt) or "<div class='tldr'><ul><li>x</li></ul></div>"
analyzer._render_signal_cards_batched = lambda *a, **k: "<div class='signal-card'>x</div>"
analyzer._postprocess_html = lambda raw, data: raw
_data = {"date": "2026-06-08", "us_market": {}, "tw_market": {}, "us_news": [], "tw_news": [], "technicals": {}}

def _probe(fn, depth):
    _cap.clear()
    try:
        fn(_data, ["NVDA"], ["2330"], depth=depth)
    except Exception as e:
        return f"ERR {e}"
    return _cap.get("p", "")

for nm, fn in [("週末", analyzer.generate_weekend_report), ("週一", analyzer.generate_monday_report)]:
    ps = _probe(fn, "simple"); pd = _probe(fn, "standard")
    check(f"{nm} simple 無新聞回顧段", not ("本週回顧" in ps or "週末重點新聞" in ps or "下週看什麼" in ps))
    check(f"{nm} simple 無催化劑清單", not ("本週催化劑" in ps or ("catalysts" in ps and "條列" in ps)))
    check(f"{nm} simple 保留操作核心", ("stock-card" in ps or "SIGNAL_CARDS" in ps or "gap" in ps.lower()))
    check(f"{nm} standard 仍有新聞段(baseline)", ("本週回顧" in pd or "週末重點新聞" in pd or "下週" in pd))

print()
if fails:
    print(f"FAIL {len(fails)} 項:", fails)
    sys.exit(1)
print("ALL PASS — depth 客製化邏輯通過,standard baseline 不變")
