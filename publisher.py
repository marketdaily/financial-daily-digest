import requests
from config import BREVO_API_KEY, SENDER_EMAIL, SENDER_NAME

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
            emails.extend(c["email"] for c in contacts if c.get("email"))
            if len(contacts) < limit:
                break
            offset += limit
    except Exception as e:
        print(f"   無法取得訂閱者名單：{e}")
    return emails


def send_transactional_email(email: str, date: str, html_content: str, api_key: str) -> bool:
    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": email}],
        "subject": f"📊 財經日報 {date} — AI 精選美股 + 台股",
        "htmlContent": html_content,
    }
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=15
        )
        return resp.ok
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
