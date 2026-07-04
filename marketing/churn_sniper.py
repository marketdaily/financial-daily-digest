"""Brevo 訂閱者開信熱度稽核 + 個人化挽回信草稿產生器(P2.5 打法5·Churn Sniper)。

只讀 Brevo API(contacts + smtp/statistics/events),不寄信、不寫 Brevo、不動 KV。
輸出草稿只給 Delvin 人工審閱,寄送與否由他決定——本腳本本身不觸發任何寄送動作,
守死線「禁止手動寄信」(feedback_no_manual_send)。

使用:
  cd marketing && python3 churn_sniper.py

輸出:
  marketing/churn_drafts.json(含訂閱者 email,禁止進 git,見 .gitignore)
"""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = Path(__file__).parent / "churn_drafts.json"
HISTORY_PATH = Path(__file__).parent / "churn_summary_history.jsonl"  # 不含 PII,可進 git,供 KPI 趨勢追蹤

# 排除非日報類信件(內部告警測試/邀請碼確認等),只算真正的財經日報寄送
EXCLUDE_SUBJECT_PATTERNS = re.compile(r"Agent Team|告警系統|邀請碼確認|系統測試")
MIN_SENDS_FOR_JUDGMENT = 3  # 少於這個數,樣本太少不下判斷(新訂戶)
STREAK_THRESHOLD = 5  # 連續 N 期未開視為 at_risk(對應 tactic 5-7 天語意,用「期數」比「日曆天」更貼近實際寄送節奏)


def load_env(path):
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _get(url, api_key):
    req = urllib.request.Request(url, headers={"api-key": api_key, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_contacts(list_id, api_key):
    contacts = []
    offset = 0
    limit = 500
    while True:
        data = _get(
            f"https://api.brevo.com/v3/contacts/lists/{list_id}/contacts?limit={limit}&offset={offset}",
            api_key,
        )
        batch = data.get("contacts", [])
        if not batch:
            break
        contacts.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return contacts


def fetch_events(email, api_key, limit=100):
    data = _get(
        f"https://api.brevo.com/v3/smtp/statistics/events?email={email}&limit={limit}",
        api_key,
    )
    return data.get("events", [])


def is_digest_subject(subject):
    if not subject:
        return False
    return not EXCLUDE_SUBJECT_PATTERNS.search(subject)


def build_send_history(events):
    """events → 依 messageId 聚合成 [{message_id, requested_at, delivered_at, blocked, opened,
    opened_at, subject}],新到舊排序。

    **注意**:`requests` 只代表 Brevo 曾嘗試寄出,不代表真的送達收件端——過去版本把
    `requests` 當 `delivered_at` 的替代值,會把「每一封都被收件端 blocked」的帳號誤判成
    「有送達、只是沒開」。`blocked` 必須獨立追蹤,`delivered_at` 只認真正的 `delivered` 事件。
    """
    by_msg = {}
    for e in events:
        subj = e.get("subject", "")
        if not is_digest_subject(subj):
            continue
        mid = e.get("messageId")
        if not mid:
            continue
        rec = by_msg.setdefault(
            mid,
            {"message_id": mid, "requested_at": None, "delivered_at": None, "blocked": False,
             "opened": False, "opened_at": None, "subject": subj},
        )
        ev = e.get("event")
        if ev == "requests" and not rec["requested_at"]:
            rec["requested_at"] = e.get("date")
        if ev == "delivered" and not rec["delivered_at"]:
            rec["delivered_at"] = e.get("date")
        if ev == "blocked":
            rec["blocked"] = True
        if ev == "opened":
            rec["opened"] = True
            if not rec["opened_at"] or e.get("date") > rec["opened_at"]:
                rec["opened_at"] = e.get("date")
    history = [r for r in by_msg.values() if r["requested_at"] or r["delivered_at"]]
    history.sort(key=lambda r: r["delivered_at"] or r["requested_at"], reverse=True)
    return history


def score_contact(history):
    """回傳 dict:sends_seen/streak_missed/never_opened/days_since_last_open/status。"""
    sends_seen = len(history)
    if sends_seen < MIN_SENDS_FOR_JUDGMENT:
        return {"sends_seen": sends_seen, "status": "too_new"}

    blocked_count = sum(1 for r in history if r.get("blocked"))
    delivered_count = sum(1 for r in history if r.get("delivered_at"))
    if delivered_count == 0 and blocked_count == sends_seen:
        # 每一封都在收件端被擋下,連一次都沒真的送達過——這是送達率/網域信譽問題,
        # 不是「使用者冷卻」,寄挽回信大機率也會被同樣擋下,不該走 draft_winback。
        return {
            "sends_seen": sends_seen,
            "blocked_count": blocked_count,
            "status": "delivery_blocked",
        }

    streak_missed = 0
    for rec in history:
        if rec["opened"]:
            break
        streak_missed += 1

    ever_opened = any(r["opened"] for r in history)
    days_since_last_open = None
    if ever_opened:
        last_open = max(r["opened_at"] for r in history if r["opened"])
        try:
            dt = datetime.fromisoformat(last_open)
            days_since_last_open = (datetime.now(dt.tzinfo) - dt).days
        except Exception:
            days_since_last_open = None

    at_risk = streak_missed >= STREAK_THRESHOLD
    return {
        "sends_seen": sends_seen,
        "streak_missed": streak_missed,
        "never_opened": not ever_opened,
        "days_since_last_open": days_since_last_open,
        "blocked_count": blocked_count,
        "status": "at_risk" if at_risk else "engaged",
    }


def append_summary_history(summary, path=HISTORY_PATH):
    """同一天(台灣時間)只留一筆(用最新一次覆蓋),避免同日重跑汙染趨勢線。不含 email 等 PII。"""
    date = summary["tw_date"]
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    rows = [r for r in rows if r.get("date") != date]
    rows.append({
        "date": date,
        "total_contacts": summary.get("total_contacts"),
        "too_new": summary.get("too_new"),
        "engaged": summary.get("engaged"),
        "at_risk": summary.get("at_risk"),
        "never_opened_at_risk": summary.get("never_opened_at_risk"),
        "delivery_blocked": summary.get("delivery_blocked"),
    })
    rows.sort(key=lambda r: r["date"])
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return rows


def draft_winback(email, score):
    if score["never_opened"]:
        body = (
            "嗨,\n\n"
            f"我們注意到你加入 MarketDaily 之後,最近 {score['sends_seen']} 期財經日報似乎都沒有被打開過——\n"
            "有可能信件被歸類到「促銷」或「垃圾郵件」匣了,方便的話麻煩檢查一下,並把 hello@marketdaily.ai 加入聯絡人/白名單。\n\n"
            "你的個人化日報依然每天準時產生,隨時可以直接回來看:\n"
            "👉 https://marketdaily.ai/dashboard.html\n\n"
            "如果是內容不合需求,也歡迎直接回信告訴我們哪裡可以改進。\n\n"
            "MarketDaily 團隊"
        )
    else:
        body = (
            "嗨,\n\n"
            f"好一段時間沒看到你打開財經日報了(最近連續 {score['streak_missed']} 期都沒開)——\n"
            "不確定是不是最近比較忙,或者內容不再符合你的需求。\n\n"
            "你的個人化日報依然每天準時產生,隨時可以直接回來看:\n"
            "👉 https://marketdaily.ai/dashboard.html\n\n"
            "如果想調整追蹤的股票、收信深度,或有任何建議,直接回信告訴我們就好。\n\n"
            "MarketDaily 團隊"
        )
    return {
        "email": email,
        "streak_missed": score.get("streak_missed"),
        "never_opened": score.get("never_opened"),
        "days_since_last_open": score.get("days_since_last_open"),
        "draft_body_zh": body,
    }


def run():
    env = load_env(ROOT / ".env")
    api_key = env.get("BREVO_API_KEY")
    if not api_key:
        print("✗ BREVO_API_KEY missing in .env")
        return {"error": "missing_api_key"}
    list_id = env.get("BREVO_LIST_ID", "2")

    contacts = fetch_contacts(list_id, api_key)
    results = []
    drafts = []
    delivery_alerts = []
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        if not email:
            continue
        events = fetch_events(email, api_key, limit=100)
        history = build_send_history(events)
        score = score_contact(history)
        score["email"] = email
        results.append(score)
        if score.get("status") == "at_risk":
            drafts.append(draft_winback(email, score))
        elif score.get("status") == "delivery_blocked":
            # 每封都被收件端擋下,寄挽回信大機率也會被擋——不產草稿,改記需人工查明的送達率警訊。
            delivery_alerts.append({
                "email": email,
                "sends_seen": score.get("sends_seen"),
                "blocked_count": score.get("blocked_count"),
                "note": "每一封信皆在收件端被 blocked,從未真正送達過(非使用者冷卻);"
                        "寄挽回信同樣大機率被擋,勿寄,需人工查明(常見成因:寄件網域信譽/收件端"
                        "政策/信箱本身輸入有誤)。",
            })

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tw_date": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
        "total_contacts": len(results),
        "too_new": sum(1 for r in results if r.get("status") == "too_new"),
        "engaged": sum(1 for r in results if r.get("status") == "engaged"),
        "at_risk": sum(1 for r in results if r.get("status") == "at_risk"),
        "never_opened_at_risk": sum(1 for d in drafts if d.get("never_opened")),
        "delivery_blocked": len(delivery_alerts),
    }
    append_summary_history(summary)
    out = {
        "_comment": (
            "Brevo 開信熱度稽核(P2.5打法5 Churn Sniper)。drafts 含訂閱者 email,禁止進 git"
            "(見 .gitignore)。draft_body_zh 為草稿,寄送與否由 Delvin 人工決定,本腳本不觸發任何"
            "寄送動作(feedback_no_manual_send)。"
        ),
        "summary": summary,
        "drafts": drafts,
        "delivery_alerts": delivery_alerts,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"→ {len(drafts)} 篇草稿寫入 {OUT_PATH}")
    if delivery_alerts:
        print(f"⚠️ {len(delivery_alerts)} 位訂閱者送達率警訊(每封皆被 blocked,非冷卻,見 delivery_alerts)")
    return out


if __name__ == "__main__":
    run()
