import requests
from config import BREVO_API_KEY, SENDER_EMAIL, SENDER_NAME
from unsubscribe import unsub_url

BREVO_SEND_URL = "https://api.brevo.com/v3/emailCampaigns"
SUBSCRIBER_WARN_THRESHOLD = 250
OWNER_EMAIL = "delvin.12345678@gmail.com"


def get_list_id() -> int:
    resp = requests.get(
        "https://api.brevo.com/v3/contacts/lists",
        headers={"api-key": BREVO_API_KEY},
        timeout=10
    )
    lists = resp.json().get("lists", [])
    return lists[0]["id"] if lists else 2


def check_subscriber_count(list_id: int):
    try:
        resp = requests.get(
            f"https://api.brevo.com/v3/contacts/lists/{list_id}",
            headers={"api-key": BREVO_API_KEY},
            timeout=10
        )
        count = resp.json().get("uniqueSubscribers", 0)
        print(f"   目前訂閱人數：{count}")
        if count >= SUBSCRIBER_WARN_THRESHOLD:
            _send_warning_email(count)
    except Exception as e:
        print(f"   無法取得訂閱人數：{e}")


def _send_warning_email(count: int):
    payload = {
        "sender": {"name": "財經日報系統", "email": SENDER_EMAIL},
        "to": [{"email": OWNER_EMAIL}],
        "subject": f"⚠️ 財經日報警告：訂閱人數已達 {count} 人",
        "htmlContent": f"""
        <p>你好，</p>
        <p>財經日報的訂閱人數目前已達 <strong>{count} 人</strong>，即將超過 Brevo 免費版每日 300 封的寄送上限。</p>
        <p>請盡快升級 Brevo 方案，避免部分訂閱者收不到日報：</p>
        <p><a href="https://app.brevo.com/subscription/list">前往 Brevo 升級方案 →</a></p>
        <p>— 財經日報自動系統</p>
        """
    }
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            timeout=10
        )
        if resp.ok:
            print(f"   ⚠️ 已寄出訂閱人數警告信（{count} 人）")
    except Exception:
        pass


def get_all_subscribers(list_id: int) -> list:
    emails = []
    offset = 0
    limit = 500
    try:
        while True:
            resp = requests.get(
                f"https://api.brevo.com/v3/contacts/lists/{list_id}/contacts",
                headers={"api-key": BREVO_API_KEY},
                params={"limit": limit, "offset": offset},
                timeout=15
            )
            contacts = resp.json().get("contacts", [])
            if not contacts:
                break
            # 退訂第二層(2026-08-17 #396):Brevo 端被標黑名單的人不再放進寄送名單。
            # 欄位不存在時 c.get() 回 None=照寄 —— 刻意 fail-open:欄位改名不該讓整批漏信,
            # 真正保證退訂生效的是 main.py 那層 KV 名單(我們自己控的那半)。
            emails.extend(c["email"] for c in contacts
                          if c.get("email") and not c.get("emailBlacklisted"))
            if len(contacts) < limit:
                break
            offset += limit
    except Exception as e:
        print(f"   無法取得訂閱者名單：{e}")
    return emails


def send_transactional_email(email: str, date: str, html_content: str, api_key: str, subject: str = None) -> bool:
    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": email}],
        "subject": subject or f"📊 財經日報 {date} — AI 精選美股 + 台股",
        "htmlContent": html_content,
    }
    # 一鍵退訂 header(RFC 8058,2026-08-17 #396):Gmail/Apple Mail 會把它變成信件頂端的
    # 「取消訂閱」按鈕 —— 這是收信人最先看到的退訂路徑,比 footer 連結更顯眼。
    u = unsub_url(email)
    if u:
        payload["headers"] = {
            "List-Unsubscribe": f"<{u}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=15
        )
        if resp.ok:
            return True
        # 400 = Brevo 驗證失敗(=確定沒進寄送佇列,不會雙寄)。多半只可能是 headers 這塊被嫌,
        # 而「有沒有退訂 header」永遠不值得拿一封信去換 → 拔掉 header 重試一次。
        # 5xx / timeout 曖昧(可能已收下),維持原本行為直接回 False,不重試。
        if resp.status_code == 400 and "headers" in payload:
            print(f"   ⚠️ Brevo 400 退回,拔掉 List-Unsubscribe header 重試 → {email}")
            payload.pop("headers", None)
            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                timeout=15
            )
            return resp.ok
        return False
    except Exception:
        return False


def publish_to_brevo(date: str, html_content: str) -> bool:
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json"
    }
    list_id = get_list_id()
    payload = {
        "name": f"財經日報 {date}",
        "subject": f"📊 財經日報 {date} — AI 精選美股 + 台股",
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "type": "classic",
        "htmlContent": html_content,
        "recipients": {"listIds": [list_id]}
    }
    try:
        resp = requests.post(BREVO_SEND_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        campaign_id = resp.json().get("id", "")
        send_resp = requests.post(
            f"{BREVO_SEND_URL}/{campaign_id}/sendNow",
            headers={"api-key": BREVO_API_KEY},
            timeout=30
        )
        send_resp.raise_for_status()
        print(f"發布成功：campaign_id={campaign_id}")
        return True
    except requests.HTTPError as e:
        print(f"發布失敗：{e.response.status_code} {e.response.text}")
        return False
    except Exception as e:
        print(f"發布失敗：{e}")
        return False
