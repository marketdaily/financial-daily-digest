#!/usr/bin/env python3
"""Meta token 重發/加 scope 工具(比照 get_youtube_token.py 慣例)。

用法:
    python get_meta_token.py            印出 OAuth 授權連結(手機點開→同意→複製跳轉後網址)
    python get_meta_token.py "<跳轉後的完整網址>"
                                        換長期 user token + 粉專 page token,備份並更新 .env
"""
import json
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
GRAPH = "https://graph.facebook.com/v21.0"
REDIRECT = "https://www.facebook.com/connect/login_success.html"
SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,"
          "instagram_basic,instagram_content_publish,business_management,"
          "ads_management")


def load_env():
    env = {}
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def auth_url(env):
    return ("https://www.facebook.com/v21.0/dialog/oauth?"
            + urllib.parse.urlencode({
                "client_id": env["APP_ID"], "redirect_uri": REDIRECT,
                "response_type": "token", "scope": SCOPES}))


def extract_token(pasted):
    frag = urllib.parse.urlparse(pasted).fragment
    params = urllib.parse.parse_qs(frag)
    tok = (params.get("access_token") or [""])[0]
    if not tok:
        sys.exit("網址裡找不到 access_token —— 要貼「同意授權後」跳轉到 login_success.html 的完整網址(含 # 後面那串)")
    return tok


def update_env(env_file, updates):
    backup = env_file.with_name(f".env.bak-{datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(env_file, backup)
    lines = env_file.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ .env 已更新(舊值備份:{backup.name})")


def main():
    env = load_env()
    if len(sys.argv) < 2:
        print("① 手機(已登入 FB 的瀏覽器)打開這個連結 → 按「繼續/同意」全部權限:\n")
        print(auth_url(env))
        print("\n② 跳轉到白底 Success 頁後,複製網址列的完整網址,整串貼回給 Claude")
        return
    short_tok = extract_token(sys.argv[1])
    print("換長期 user token...")
    d = get(f"{GRAPH}/oauth/access_token?grant_type=fb_exchange_token"
            f"&client_id={env['APP_ID']}&client_secret={env['APP_SECRET']}"
            f"&fb_exchange_token={urllib.parse.quote(short_tok)}")
    user_tok = d["access_token"]
    print("拿粉專 page token...")
    accounts = get(f"{GRAPH}/me/accounts?access_token={urllib.parse.quote(user_tok)}")
    page = next((p for p in accounts.get("data", [])
                 if p.get("id") == env.get("FB_PAGE_ID")), None)
    if not page:
        sys.exit(f"me/accounts 裡找不到粉專 {env.get('FB_PAGE_ID')}:{accounts}")
    app_tok = urllib.parse.quote(f"{env['APP_ID']}|{env['APP_SECRET']}")
    scopes = get(f"{GRAPH}/debug_token?input_token={urllib.parse.quote(page['access_token'])}"
                 f"&access_token={app_tok}").get("data", {}).get("scopes", [])
    print(f"新 page token scopes:{', '.join(scopes)}")
    if "ads_management" not in scopes:
        sys.exit("⚠️ 新 token 沒有 ads_management —— 授權時可能沒勾到,重跑一次連結並確認全部權限打勾")
    update_env(HERE / ".env",
               {"FB_USER_TOKEN": user_tok, "META_ACCESS_TOKEN": page["access_token"]})
    print("完成。接著跑:python auto_post.py check")


if __name__ == "__main__":
    main()
