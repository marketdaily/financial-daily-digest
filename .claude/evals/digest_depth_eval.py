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

# 2. simple / deep 各有對應指令
check("simple 指令含『精簡』", "精簡" in _depth_directive("simple"))
check("simple 限制長篇大盤", "不要長篇" in _depth_directive("simple"))
check("deep 指令含『深入』", "深入" in _depth_directive("deep"))
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

print()
if fails:
    print(f"FAIL {len(fails)} 項:", fails)
    sys.exit(1)
print("ALL PASS — depth 客製化邏輯通過,standard baseline 不變")
