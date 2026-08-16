#!/usr/bin/env python3
"""記憶索引預算守衛(2026-08-16 建,Delvin 核可)。

為什麼:MEMORY.md 每個 session 自動注入,~17100 字元是實務上限(見 memory
capability_memory_two_level_index)。它會被各 session 持續追加而**單調成長**,
超過上限的症狀是「索引尾端被靜默截斷」——沒有任何人會收到通知,而索引正是
每個 session 判斷「我知不知道自己有這東西」的唯一入口。08-16 那次是撐到
22,525(超標 31.6%)才被人工發現,中間沒有任何一天有人知道。

做什麼:每天量一次,逼近上限就推 admin。順帶把兩個同源診斷帶進訊息(孤兒數、
hubify --verify --strict 結果),因為「該做一輪兩層化了」的判斷需要它們。

告警紀律(見 capability_alert_storm_dedup / hub_alerting):同一狀態只推一次,
持續超標最多每 COOLDOWN_DAYS 天再推一次;回到安全區會推一則「已解除」再靜音。
"""
import io, os, re, json, glob, subprocess, datetime, sys

MEM_DIR = os.path.expanduser("~/.claude/projects/-home-userdelvin-Delvin-agent/memory")
HUBIFY = os.path.expanduser("~/autonomous/capabilities/memory_hubify/hubify.py")
PLAN = os.path.expanduser("~/autonomous/capabilities/memory_hubify/plan.json")
STATE = os.path.expanduser("~/.marketdaily-fallback/.memory_index_budget.json")
NOTIFY = os.path.expanduser("~/.marketdaily-fallback/notify_admin.py")
PY = os.path.expanduser("~/Delvin-agent/.venv/bin/python")
HARD, WARN, COOLDOWN_DAYS = 17100, 16500, 3

_rd = lambda p: io.open(p, "rb").read().decode("utf-8", "replace")
WL = re.compile(r"\[\[([^\]]+?)\]\]")
MD = re.compile(r"\]\(([^)]+?)\.md\)")


def measure():
    mem = _rd(os.path.join(MEM_DIR, "MEMORY.md"))
    files = {os.path.basename(f)[:-3] for f in glob.glob(MEM_DIR + "/*.md")
             if not os.path.basename(f).startswith("._")}

    def out(n):
        p = os.path.join(MEM_DIR, n + ".md")
        s = _rd(p) if os.path.exists(p) else ""
        t = {x.split("|")[0].split("\\")[0].strip() for x in WL.findall(s)} | set(MD.findall(s))
        return {x for x in t if x in files}

    seen, q = {"MEMORY"}, ["MEMORY"]
    while q:
        for m in out(q.pop()):
            if m not in seen:
                seen.add(m); q.append(m)
    # MEMORY_INBOX_MAC 是 Mac 的外送匣機制檔,本來就不該進索引,不計為孤兒
    orph = files - seen - {"MEMORY", "MEMORY_INBOX_MAC"}
    strict = -1
    if os.path.exists(HUBIFY) and os.path.exists(PLAN):
        try:
            strict = subprocess.run([sys.executable, HUBIFY, "--plan", PLAN, "--min-links", "2",
                                     "--verify", "--strict"], capture_output=True, timeout=180).returncode
        except Exception:
            strict = -1
    return {"chars": len(mem), "lines": mem.count("\n"),
            "hubs": len(glob.glob(MEM_DIR + "/hub_*.md")),
            "orphans": len(orph), "strict_rc": strict}


def level(chars):
    return "HARD" if chars >= HARD else ("WARN" if chars >= WARN else "OK")


def main():
    m = measure()
    lv = level(m["chars"])
    st = {}
    if os.path.exists(STATE):
        try:
            st = json.load(io.open(STATE, encoding="utf-8"))
        except Exception:
            st = {}          # 壞帳本只影響去重,不阻斷量測
    today = datetime.date.today().isoformat()
    last_lv, last_push = st.get("level", "OK"), st.get("last_push", "")
    push = False
    if lv != "OK":
        if lv != last_lv:
            push = True                                   # 狀態改變:一定推
        elif last_push:
            age = (datetime.date.today() - datetime.date.fromisoformat(last_push)).days
            push = age >= COOLDOWN_DAYS                   # 持續超標:每 N 天再提醒一次
        else:
            push = True
    elif last_lv != "OK":
        push = True                                       # 回到安全區:推一則解除
    head = {"HARD": "🔴 記憶索引已超過上限", "WARN": "🟠 記憶索引逼近上限",
            "OK": "✅ 記憶索引已回到安全區"}[lv]
    msg = ("%s\nMEMORY.md %d 字元 / 上限 %d(警戒 %d)、%d 行、%d 個 hub\n"
           "孤兒記憶 %d 則、hubify --verify --strict rc=%s\n"
           "處置:再做一輪兩層化(把個別 bullet 折成群行交給 "
           "~/autonomous/capabilities/memory_hubify/hubify.py --apply),"
           "作法與三個已知陷阱見 memory capability_memory_index_groom_20260816") % (
        head, m["chars"], HARD, WARN, m["lines"], m["hubs"], m["orphans"], m["strict_rc"])
    sent = False
    if push or "--force" in sys.argv:
        try:
            sent = subprocess.run([PY, NOTIFY, msg], capture_output=True, timeout=60).returncode == 0
        except Exception:
            sent = False
    if push and sent:
        st["last_push"] = today
    st.update({"level": lv, "checked": today, **m})
    io.open(STATE, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False, indent=1))
    print("%s chars=%d lv=%s push=%s sent=%s orphans=%d strict_rc=%s"
          % (today, m["chars"], lv, push, sent, m["orphans"], m["strict_rc"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
