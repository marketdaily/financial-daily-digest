#!/usr/bin/env python3
"""一次性取得 TikTok Content Posting API 的 access_token + refresh_token。

前置:
1. 在 TikTok for Developers 註冊 app(類型 Web),scope 勾 `video.publish`、
   `video.upload`、`user.info.basic`。
2. Redirect URI 設定為 http://localhost:8724/。
3. 拿到 client_key / client_secret。

用法:
    python get_tiktok_token.py <client_key> <client_secret>

跑完會印出四行 secrets,貼進 marketing/.env 或設成 GH Actions secrets。
access_token 通常 24h 過期,refresh_token 約 365 天;auto_post.py 會自動
用 refresh_token 換新 access_token。
"""
import http.server
import json
import secrets as pysecrets
import sys
import urllib.parse
import urllib.request
import webbrowser

PORT = 8724
REDIRECT = f"http://localhost:{PORT}/"
SCOPE = "user.info.basic,video.upload,video.publish"


def main():
    if len(sys.argv) < 3:
        sys.exit("用法:python get_tiktok_token.py <client_key> <client_secret>")
    ck, cs = sys.argv[1], sys.argv[2]
    state = pysecrets.token_urlsafe(16)

    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": ck,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "state": state,
    })

    box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box["code"] = q.get("code", [None])[0]
            box["state"] = q.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("授權完成,可以關掉這個分頁回終端機。".encode())

        def log_message(self, *a):
            pass

    print(f"開啟瀏覽器授權中...\n沒自動開就手動貼:\n{auth_url}\n")
    webbrowser.open(auth_url)
    srv = http.server.HTTPServer(("localhost", PORT), Handler)
    while "code" not in box:
        srv.handle_request()
    if not box.get("code") or box.get("state") != state:
        sys.exit(f"沒拿到授權碼或 state 不符:{box}")

    data = urllib.parse.urlencode({
        "client_key": ck,
        "client_secret": cs,
        "code": box["code"],
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
    }).encode()
    req = urllib.request.Request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tok = json.loads(r.read().decode())

    at = tok.get("access_token")
    rt = tok.get("refresh_token")
    if not (at and rt):
        sys.exit(f"沒拿到 token:{tok}")
    print("\n✅ 取得成功 —— 把這四行填進 marketing/.env(也要設成 GH Secrets):\n")
    print(f"TIKTOK_CLIENT_KEY={ck}")
    print(f"TIKTOK_CLIENT_SECRET={cs}")
    print(f"TIKTOK_ACCESS_TOKEN={at}")
    print(f"TIKTOK_REFRESH_TOKEN={rt}")
    print(f"\n# access_token 約 {tok.get('expires_in', '?')} 秒過期、refresh_token 約 365 天;")
    print("# auto_post.py 會自動用 refresh_token 換新 access_token。")


if __name__ == "__main__":
    main()
