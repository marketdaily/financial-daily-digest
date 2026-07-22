"""產生 docs/agents.html 用的公開戰情室資料 docs/data/board.json。

⚠️ 安全邊界(2026-07-08 設計時的核心考量,勿破壞):
本檔只准輸出「彙整數字/列舉狀態」,絕不輸出任何內部自由文字
(git commit message 原文、backlog.md/current_task.md 任務描述、autonomous_log
失敗細節皆不可原樣外露)——這些內容含公司內部對自己失誤的坦承(捏造數字、
用戶信件未送達等事故記錄),原樣公開到 marketdaily.ai 是真實信譽風險。
agent 的 name/emoji/desc 這類語言相關顯示文案不放在這裡,唯一來源是
docs/agents.html 自己的 i18n dict(依 key 對照)——避免又長出一條「後端吐
中文字串,前端 EN 模式忘記翻」的漏網之魚。新增欄位前,先問:「這個值有沒有
可能夾帶內部自由文字?」沒有才准加。
"""
import os
import re
import json
import subprocess
from datetime import datetime, timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(REPO, "docs", "data", "board.json")
AUTONOMOUS = os.path.expanduser("~/autonomous")
TPE = timezone(timedelta(hours=8))

# name/emoji/desc 故意不放在這裡——那是語言相關的顯示文案,唯一來源是
# docs/agents.html 的 i18n dict(zh.agents[key] / en.agents[key])。這裡的 key
# 順序與集合必須跟那份 dict 的 5 個 key 保持一致,否則前端會退回顯示裸 key
# (agents.html render() 的 `L.agents[a.key]||{...}` fallback)。
AGENTS = [
    {"key": "digest_ops", "accent": "#6366f1",
     "scopes": {"digest", "dashboard", "admin", "alerts", "alert", "alert-worker",
                "quotes", "cron", "signup", "watchboard", "push", "stocks",
                "analytics", "auth", "positions"}},
    {"key": "intel", "accent": "#22d3ee",
     "scopes": {"intel", "news", "political"}},
    {"key": "quant", "accent": "#34d399",
     "scopes": {"track-record", "track", "cb", "valuation", "analyzer", "council"}},
    {"key": "growth", "accent": "#fb923c",
     "scopes": {"marketing", "seo-blog", "seo", "blog", "social", "landing",
                "supply-chain", "video"}},
    {"key": "engine", "accent": "#f472b6",
     "scopes": set()},  # 兜底:非以上任何 scope 的一律歸這裡
]
SCOPE_TO_KEY = {}
for a in AGENTS:
    for s in a["scopes"]:
        SCOPE_TO_KEY[s] = a["key"]
ENGINE_KEY = "engine"

SCOPE_RE = re.compile(r"^[a-zA-Z]+\(([^)]+)\)")


def classify(subject):
    m = SCOPE_RE.match(subject)
    if not m:
        return ENGINE_KEY
    return SCOPE_TO_KEY.get(m.group(1).strip(), ENGINE_KEY)


def git_commits_since(days):
    """回傳 [(date_str, key)],只取 scope 分類結果,不帶原文 subject。"""
    try:
        raw = subprocess.run(
            ["git", "log", f"--since={days}.days", "--format=%cI\x1f%s"],
            cwd=REPO, capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return []
    out = []
    for line in raw.strip().splitlines():
        parts = line.split("\x1f", 1)
        if len(parts) != 2:
            continue
        iso, subject = parts
        date_str = iso[:10]
        out.append((date_str, classify(subject)))
    return out


def failed_count_7d():
    """cycle 失敗次數(engine bucket,不外露失敗原因細節)。"""
    path = os.path.join(AUTONOMOUS, "autonomous_log.md")
    if not os.path.exists(path):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    ts_re = re.compile(r"^\- \[(\d{4}-\d{2}-\d{2}T[\d:]+)Z\] \[cycle 失敗\]")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = ts_re.match(line)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts >= cutoff:
                n += 1
    return n


def current_task_active_key():
    """回傳目前 in_progress 任務大致對應哪個 agent key(只回 key,不外露任務文字)。"""
    path = os.path.join(AUTONOMOUS, "state", "current_task.md")
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    first_line = text.splitlines()[0].strip() if text else ""
    if first_line.lower().startswith("status:") and "idle" in first_line.lower():
        return None
    body = text.lower()
    hits = {}
    keyword_map = {
        "digest_ops": ["dashboard", "digest", "日報", "推播", "alert"],
        "intel": ["intel", "信息差", "connector", "連接器"],
        "quant": ["track-record", "戰績", "cb ", "valuation", "估值", "analyzer"],
        "growth": ["seo", "marketing", "行銷", "社群", "blog"],
        "engine": ["site.py", "site_scan", "capabilities", "cron", "board.json", "agents.html"],
    }
    for key, kws in keyword_map.items():
        hits[key] = sum(1 for kw in kws if kw in body)
    best = max(hits, key=hits.get)
    return best if hits[best] > 0 else ENGINE_KEY


def capabilities_total():
    path = os.path.join(AUTONOMOUS, "capabilities", "INDEX.md")
    if not os.path.exists(path):
        return 0
    text = open(path, encoding="utf-8").read()
    return len(re.findall(r"^### ", text, flags=re.MULTILINE))


def build():
    commits = git_commits_since(7)
    per_agent_total = {a["key"]: 0 for a in AGENTS}
    per_day = {}
    for date_str, key in commits:
        per_agent_total[key] = per_agent_total.get(key, 0) + 1
        per_day.setdefault(date_str, {a["key"]: 0 for a in AGENTS})
        per_day[date_str][key] = per_day[date_str].get(key, 0) + 1

    failed_total = failed_count_7d()
    active_key = current_task_active_key()

    # name/emoji/desc 故意不放進 board.json——那是要依語言顯示的靜態行銷文案,
    # 由 docs/agents.html 自己的 i18n dict(依 key 對照)負責,避免又長出一條
    # 「後端吐中文字串,前端 EN 模式忘記翻」的 i18n 動態渲染漏網之魚。
    agents_out = []
    for a in AGENTS:
        agents_out.append({
            "key": a["key"],
            "accent": a["accent"],
            "status": "working" if a["key"] == active_key else "idle",
            "done_7d": per_agent_total.get(a["key"], 0),
            "failed_7d": failed_total if a["key"] == ENGINE_KEY else 0,
        })

    activity_daily = []
    for date_str in sorted(per_day.keys(), reverse=True)[:7]:
        row = per_day[date_str]
        activity_daily.append({
            "date": date_str,
            "total": sum(row.values()),
            "by_agent": row,
        })

    now = datetime.now(timezone.utc)
    board = {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_display": now.astimezone(TPE).strftime("%Y-%m-%d %H:%M") + " 台北",
        "stats": {
            "active_now": 1 if active_key else 0,
            "done_7d": sum(per_agent_total.values()),
            "failed_7d": failed_total,
            "capabilities_total": capabilities_total(),
        },
        "agents": agents_out,
        "activity_daily": activity_daily,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    # temp+rename 原子寫入:mid-write 死掉不可留下截斷 board.json(會被 runner persist 進庫,
    # 再被任一 runner 的 docs deploy 帶上站——2026-07-18 fleet_deploy_gate 驗證者 F1)
    tmp_path = OUT_JSON + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=None)
    os.replace(tmp_path, OUT_JSON)
    print(f"✅ board.json 已更新 — 近7天完成 {board['stats']['done_7d']} 項 · "
          f"能力庫 {board['stats']['capabilities_total']} 個 · 失敗 {failed_total}")
    return board


if __name__ == "__main__":
    build()
