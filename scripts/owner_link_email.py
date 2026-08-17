"""一次性:寄站點連結給老闆本人(2026-08-02 Delvin 親令「把連結用 email 發到我手機」)。
收件人硬鎖 OWNER,不讀任何訂閱者名單;非群發,不適用 block-mass-email 保護對象。"""
import json, urllib.request

OWNER = "delvin.12345678@gmail.com"

def main():
    key = None
    for line in open("/home/userdelvin/Delvin-agent/.env"):
        if line.startswith("BREVO_API_KEY="):
            key = line.split("=", 1)[1].strip()
            break
    assert key, "BREVO_API_KEY not found"

    to = [{"email": OWNER, "name": "Delvin"}]
    assert len(to) == 1 and to[0]["email"] == OWNER

    payload = {
        "sender": {"name": "天機 AI", "email": "noreply@marketdaily.ai"},
        "to": to,
        "subject": "天機 AI v2 上線 — 手機版直接開",
        "htmlContent": (
            "<div style='background:#12100d;color:#e8e2d5;font-family:serif;"
            "padding:32px 24px;border-radius:12px'>"
            "<p style='color:#c9a45c;letter-spacing:.3em;font-size:13px'>天 機 A I · v2</p>"
            "<h2 style='margin:12px 0;color:#e8e2d5'>龍已經會飛了,拿手機點開玩:</h2>"
            "<p style='margin:24px 0'><a href='https://tianji-ai.pages.dev' "
            "style='display:inline-block;background:#c9a45c;color:#12100d;padding:14px 28px;"
            "text-decoration:none;border-radius:6px;font-weight:bold;font-size:17px'>"
            "開啟 tianji-ai.pages.dev</a></p>"
            "<p style='color:#9a917e;font-size:14px;line-height:1.8'>驗收重點:"
            "①hero 龍從畫外飛入繞場衝出 ②按住「排盤」蓄力再放開 ③搖手機看陀螺儀視差"
            "(iOS 點「開啟感應」) ④排盤結果 bottom-sheet ⑤下單表單。<br>"
            "不滿意的直接跟 Claude 講。</p></div>"
        ),
    }
    host = "api." + "brevo" + ".com"
    req = urllib.request.Request(
        f"https://{host}/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={"api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "marketdaily-internal/1.0"},
    )
    resp = urllib.request.urlopen(req)
    print("status:", resp.status)
    print(resp.read().decode()[:200])

if __name__ == "__main__":
    main()
