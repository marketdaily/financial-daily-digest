"""Email 送達率診斷(週末託管任務②):只讀 Brevo domain 認證狀態 + 逐帳號事件明細,
產出診斷報告與修法草案。**不寄信、不改 DNS、不改 Brevo 設定**——任何動作留 Delvin 人工拍板
(feedback_no_manual_send)。

背景:churn_sniper.py 發現 3 位訂閱者連續 18-20 期日報 never_opened。本腳本進一步問
「是內容不合興趣,還是信根本沒送達收件匣」——只看 delivered/opened 兩種事件無法回答這題,
Brevo 事件還有 blocked/spam/softBounces/hardBounces/deferred,任何一種出現在這 3 個帳號上
都是「送達率」問題而非「興趣冷卻」問題,需要不同的修法。

使用:
  cd marketing && python3 deliverability_audit.py

輸出:
  marketing/deliverability_audit.json(含 email,禁止進 git,見 .gitignore 同 churn_drafts.json)
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from churn_sniper import load_env, fetch_events, is_digest_subject

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = Path(__file__).parent / "deliverability_audit.json"

# churn_sniper 目前已知 never_opened 帳號(2026-07-04 churn_drafts.json 快照);
# 若之後名單變動,此腳本仍可用——只是這裡先鎖定已知最可疑的 3 個做深度診斷。
NEVER_OPENED_EMAILS = ["maxine3345@gmail.com", "maxine3345@hotmail.com", "justinchang168@gmail.com"]

# Brevo 事件類型分類:哪些代表「送達率」問題(non-benign),哪些是正常生命週期事件
DELIVERABILITY_FAIL_EVENTS = {"blocked", "spam", "hardBounces", "softBounces", "invalid", "error", "deferred"}


def _get(url, api_key):
    req = urllib.request.Request(url, headers={"api-key": api_key, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_domain_auth(api_key):
    """Brevo 官方回報的 domain SPF/DKIM 認證狀態(非我方 DNS 猜測,是 Brevo 實際驗證結果)。"""
    try:
        data = _get("https://api.brevo.com/v3/senders/domains", api_key)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "raw": None}
    except Exception as e:
        return {"error": str(e), "raw": None}
    domains = data.get("domains", []) if isinstance(data, dict) else data
    target = None
    for d in domains or []:
        if d.get("domain_name") == "marketdaily.ai" or d.get("id") == "marketdaily.ai":
            target = d
            break
    return {"error": None, "raw": target if target else domains}


def full_event_breakdown(email, api_key, limit=200):
    """跟 churn_sniper.build_send_history 不同:不 filter 掉非日報信,且保留所有事件類型
    (blocked/spam/bounce 等),因為送達率問題不一定只發生在日報信上,系統信(歡迎信等)
    若也被擋,同樣是網域信譽問題的證據。"""
    events = fetch_events(email, api_key, limit=limit)
    by_type = {}
    fail_events = []
    for e in events:
        ev = e.get("event", "unknown")
        by_type[ev] = by_type.get(ev, 0) + 1
        if ev in DELIVERABILITY_FAIL_EVENTS:
            fail_events.append({
                "event": ev,
                "date": e.get("date"),
                "subject": e.get("subject"),
                "reason": e.get("reason") or e.get("tag"),
            })
    digest_events = [e for e in events if is_digest_subject(e.get("subject", ""))]
    return {
        "email": email,
        "total_events_seen": len(events),
        "event_type_counts": by_type,
        "deliverability_fail_events": fail_events,
        "has_deliverability_fail": len(fail_events) > 0,
        "digest_related_events": len(digest_events),
    }


def run():
    env = load_env(ROOT / ".env")
    api_key = env.get("BREVO_API_KEY")
    if not api_key:
        print("✗ BREVO_API_KEY missing in .env")
        return {"error": "missing_api_key"}

    domain_auth = fetch_domain_auth(api_key)
    account_breakdowns = [full_event_breakdown(email, api_key) for email in NEVER_OPENED_EMAILS]

    any_real_fail = any(b["has_deliverability_fail"] for b in account_breakdowns)

    out = {
        "_comment": (
            "送達率診斷(週末託管任務②)。只讀 Brevo API,不寄信、不改 DNS/Brevo 設定。"
            "含 email PII,禁止進 git(同 churn_drafts.json 慣例)。"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brevo_domain_auth": domain_auth,
        "never_opened_accounts": account_breakdowns,
        "verdict": {
            "any_hard_deliverability_fail_event": any_real_fail,
            "note": (
                "若 any_hard_deliverability_fail_event=False,代表 Brevo 端事件記錄裡這 3 個帳號"
                "從未出現 blocked/spam/bounce——信件本身有送達,問題落在收件匣分類(進了促銷/垃圾"
                "匣但使用者未曾開啟)或使用者根本不看,而非 Brevo/網域認證失敗;此時 DNS 修法"
                "(補 SPF include)仍值得做(治本、防未來擴大),但不是這 3 個帳號當下沒開信的"
                "直接病因。"
            ),
        },
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"brevo_domain_auth": domain_auth, "verdict": out["verdict"]}, ensure_ascii=False, indent=2))
    print(f"→ 完整診斷寫入 {OUT_PATH}")
    return out


if __name__ == "__main__":
    run()
