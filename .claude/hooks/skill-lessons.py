#!/usr/bin/env python3
"""skill 自主學習迴圈 hook(PostToolUse on Skill,Delvin 2026-07-29 親令)。
每次任何 skill 被呼叫:①把該 skill 目錄的 LESSONS.md(歷史教訓帳本)注入上下文
②附上「用完撞到坑要回寫」的強制指令。找不到 skill 目錄(內建 skill)則靜默跳過。
"""
import json
import os
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
skill = str((data.get("tool_input") or {}).get("skill", ""))
name = skill.split(":")[-1].strip()
if not name or "/" in name or ".." in name:
    sys.exit(0)

# skill 使用率統計(2026-07-29 經營體檢⑥):每次呼叫記一行,30 天後可盤點殭屍 skill 退役
try:
    from datetime import datetime, timezone
    with open(os.path.expanduser("~/.claude/skill_usage.jsonl"), "a", encoding="utf-8") as _f:
        _f.write(json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "skill": name}, ensure_ascii=False) + "\n")
except OSError:
    pass

BASES = [
    os.path.expanduser("~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills"),
    os.path.expanduser("~/.claude/skills"),
    os.path.join(os.getcwd(), ".claude", "skills"),
]
d = next((os.path.join(b, name) for b in BASES if os.path.isdir(os.path.join(b, name))), None)
if not d:
    sys.exit(0)

# 帳本不一定在 skill 根目錄:website-design-team 的在 references/design-material/LESSONS.md,
# 舊版只找根目錄 → 對「示範用的那個 skill」永遠回報「尚無帳本」(2026-07-30 抓到)。
# 先找根目錄,找不到再往下最多 3 層搜第一個 LESSONS.md。
lp = os.path.join(d, "LESSONS.md")
if not os.path.exists(lp):
    base_depth = d.rstrip(os.sep).count(os.sep)
    found = None
    for root, dirs, files in os.walk(d):
        if root.rstrip(os.sep).count(os.sep) - base_depth >= 3:
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__")]
        if "LESSONS.md" in files:
            found = os.path.join(root, "LESSONS.md")
            break
    if found:
        lp = found
if os.path.exists(lp):
    try:
        text = open(lp, encoding="utf-8", errors="replace").read().strip()
    except OSError:
        text = ""
    if len(text) > 6000:
        text = "(前段較舊,略)…\n" + text[-6000:]
    lessons = f"📒 skill「{name}」的歷史教訓帳本({lp},先讀再做,別重蹈覆轍):\n{text}" if text else f"📒 {name} 的 LESSONS.md 是空的。"
else:
    lessons = f"📒 skill「{name}」尚無 LESSONS.md(還沒踩過記錄在案的坑)。"

inst = (f"⚠️ skill 自主學習鐵則(老闆 2026-07-29 親令,全 skill 適用):這次使用「{name}」的過程中,"
        f"凡撞到門檻/bug/限制,或發現更好的做法,**解決之後、收尾之前必須回寫** {lp} "
        f"——append 一節(### YYYY-MM-DD 一句話標題 + 坑是什麼/怎麼修/下次怎麼避,≤6 行);"
        f"若證實既有條目已過時,順手修正。沒有新教訓就不寫,不准灌水。")
# Mac=大腦唯讀鏡像(2026-07-30 B級改制):改「既有」檔不會同步出去,只會被存證到 ~/.brain-local-edits。
# 新建檔案不受限(brain_collect_mac.sh 只收新增)。所以 Mac 上對既有帳本的回寫要指路經 winrig MCP。
if sys.platform == "darwin" and os.path.exists(lp):
    try:
        rel = os.path.relpath(lp, os.path.expanduser("~"))
    except ValueError:
        rel = ""
    if rel and not rel.startswith(".."):
        inst += (f"\n⚠️ 本機是 Mac(大腦唯讀鏡像):直接在本地 append 這本**既有**帳本不會同步出去。"
                 f"回寫請用 mcp__winrig__run_bash 在 winrig 端 append 到 ~/{rel}(帳本尚不存在時才可在 Mac 本地新建)。")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                          "additionalContext": lessons + "\n\n" + inst}},
                 ensure_ascii=False))
