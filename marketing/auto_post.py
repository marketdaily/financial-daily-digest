#!/usr/bin/env python3
"""MarketDaily 社群自動發文 — Instagram / Facebook / Threads / LINE。

一次性設定見 SETUP_AUTOPOST.md;把權杖填進 marketing/.env。
用法:
    python auto_post.py check                   驗證 .env 權杖是否有效
    python auto_post.py stage                   貼文圖轉 JPEG → docs/social/ → 部署(取得公開網址)
    python auto_post.py list                    列出 social_posts.json 裡的貼文
    python auto_post.py post teaser              發單篇(發到該篇設定的平台)
    python auto_post.py post launch --only instagram,facebook
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
GRAPH = "https://graph.facebook.com/v21.0"
THREADS = "https://graph.threads.net/v1.0"
POSTS_FILE = HERE / "social_posts.json"
LOG_FILE = HERE / "social_out" / "post_log.jsonl"


ENV_KEYS = ("META_ACCESS_TOKEN", "FB_PAGE_ID", "IG_USER_ID", "THREADS_ACCESS_TOKEN",
            "THREADS_USER_ID", "LINE_CHANNEL_ID", "LINE_CHANNEL_SECRET",
            "LINE_CHANNEL_ACCESS_TOKEN", "LINE_ADD_URL", "SITE_BASE")


def load_env():
    env, f = {}, HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    else:
        env = {k: os.environ[k] for k in ENV_KEYS if os.environ.get(k)}
        if not env:
            sys.exit("找不到 marketing/.env,環境變數也沒設 —— 請參考 SETUP_AUTOPOST.md")
    if env.get("LINE_CHANNEL_ID") and env.get("LINE_CHANNEL_SECRET"):
        ok, r = http("https://api.line.me/v2/oauth/accessToken", "POST",
                     form={"grant_type": "client_credentials",
                           "client_id": env["LINE_CHANNEL_ID"],
                           "client_secret": env["LINE_CHANNEL_SECRET"]})
        if ok and r.get("access_token"):
            env["LINE_CHANNEL_ACCESS_TOKEN"] = r["access_token"]
    return env


def http(url, method="GET", form=None, json_body=None, headers=None):
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            status, body = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}
    try:
        parsed = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        parsed = {"raw": body}
    return 200 <= status < 300, parsed


def post_facebook(env, image_url, caption):
    ok, r = http(f"{GRAPH}/{env['FB_PAGE_ID']}/photos", "POST",
                 form={"url": image_url, "caption": caption,
                       "access_token": env["META_ACCESS_TOKEN"]})
    if ok and (r.get("post_id") or r.get("id")):
        return True, r.get("post_id") or r.get("id")
    return False, r


def post_instagram(env, image_url, caption):
    ig, tok = env["IG_USER_ID"], env["META_ACCESS_TOKEN"]
    ok, c = http(f"{GRAPH}/{ig}/media", "POST",
                 form={"image_url": image_url, "caption": caption, "access_token": tok})
    if not ok or "id" not in c:
        return False, c
    cid, qtok = c["id"], urllib.parse.quote(tok)
    for _ in range(20):
        time.sleep(3)
        _, st = http(f"{GRAPH}/{cid}?fields=status_code&access_token={qtok}")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            return False, st
    ok, p = http(f"{GRAPH}/{ig}/media_publish", "POST",
                 form={"creation_id": cid, "access_token": tok})
    return (True, p["id"]) if ok and "id" in p else (False, p)


def post_threads(env, image_url, caption):
    uid, tok = env["THREADS_USER_ID"], env["THREADS_ACCESS_TOKEN"]
    ok, c = http(f"{THREADS}/{uid}/threads", "POST",
                 form={"media_type": "IMAGE", "image_url": image_url,
                       "text": caption, "access_token": tok})
    if not ok or "id" not in c:
        return False, c
    time.sleep(20)
    ok, p = http(f"{THREADS}/{uid}/threads_publish", "POST",
                 form={"creation_id": c["id"], "access_token": tok})
    return (True, p["id"]) if ok and "id" in p else (False, p)


def post_line(env, image_url, caption):
    ok, r = http("https://api.line.me/v2/bot/message/broadcast", "POST",
                 json_body={"messages": [
                     {"type": "image", "originalContentUrl": image_url,
                      "previewImageUrl": image_url},
                     {"type": "text", "text": caption}]},
                 headers={"Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}"})
    return (True, "broadcast sent") if ok else (False, r)


def post_instagram_reel(env, video_url, caption):
    ig, tok = env["IG_USER_ID"], env["META_ACCESS_TOKEN"]
    ok, c = http(f"{GRAPH}/{ig}/media", "POST",
                 form={"media_type": "REELS", "video_url": video_url,
                       "caption": caption, "access_token": tok})
    if not ok or "id" not in c:
        return False, c
    cid, qtok = c["id"], urllib.parse.quote(tok)
    for _ in range(60):
        time.sleep(5)
        _, st = http(f"{GRAPH}/{cid}?fields=status_code&access_token={qtok}")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            return False, st
    else:
        return False, {"error": "Reel 處理逾時"}
    ok, p = http(f"{GRAPH}/{ig}/media_publish", "POST",
                 form={"creation_id": cid, "access_token": tok})
    return (True, p["id"]) if ok and "id" in p else (False, p)


def post_facebook_reel(env, video_url, caption):
    page, tok = env["FB_PAGE_ID"], env["META_ACCESS_TOKEN"]
    ok, r = http(f"{GRAPH}/{page}/video_reels", "POST",
                 form={"upload_phase": "start", "access_token": tok})
    if not ok or "video_id" not in r:
        return False, r
    vid = r["video_id"]
    upload_url = r.get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{vid}"
    ok, u = http(upload_url, "POST",
                 headers={"Authorization": f"OAuth {tok}", "file_url": video_url})
    if not ok:
        return False, u
    qtok = urllib.parse.quote(tok)
    for _ in range(50):
        time.sleep(6)
        _, st = http(f"{GRAPH}/{vid}?fields=status&access_token={qtok}")
        status = st.get("status") or {}
        if status.get("video_status") in ("ready", "upload_complete"):
            break
        if status.get("video_status") == "error":
            return False, st
    ok, p = http(f"{GRAPH}/{page}/video_reels", "POST",
                 form={"video_id": vid, "upload_phase": "finish",
                       "video_state": "PUBLISHED", "description": caption,
                       "access_token": tok})
    return (True, vid) if ok and p.get("success") else (False, p)


PLATFORMS = {"facebook": post_facebook, "instagram": post_instagram,
             "threads": post_threads, "line": post_line}

REEL_PLATFORMS = {"instagram": post_instagram_reel, "facebook": post_facebook_reel}


def load_posts():
    return json.loads(POSTS_FILE.read_text(encoding="utf-8"))["posts"]


def cmd_list():
    for p in load_posts():
        kind = "Reel" if p.get("type") == "reel" else "圖卡"
        print(f"  [{p['id']:<10}] day {p['day']} · {kind} · {p.get('image') or p.get('video')} · {', '.join(p['platforms'])}")


def cmd_check(env):
    print("驗證權杖中...\n")
    qt = urllib.parse.quote(env.get("META_ACCESS_TOKEN", ""))
    ok, r = http(f"{GRAPH}/me?fields=id,name&access_token={qt}")
    print(f"  Meta (FB/IG): {'✅ ' + r.get('name', '?') if ok and 'id' in r else '❌ ' + str(r)}")
    if env.get("IG_USER_ID"):
        ok, r = http(f"{GRAPH}/{env['IG_USER_ID']}?fields=username&access_token={qt}")
        print(f"  Instagram:    {'✅ @' + r['username'] if ok and 'username' in r else '❌ ' + str(r)}")
    if env.get("THREADS_ACCESS_TOKEN"):
        qtt = urllib.parse.quote(env["THREADS_ACCESS_TOKEN"])
        ok, r = http(f"{THREADS}/me?fields=username&access_token={qtt}")
        print(f"  Threads:      {'✅ @' + r['username'] if ok and 'username' in r else '❌ ' + str(r)}")
    if env.get("LINE_CHANNEL_ACCESS_TOKEN"):
        ok, r = http("https://api.line.me/v2/bot/info",
                     headers={"Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}"})
        print(f"  LINE OA:      {'✅ ' + r.get('displayName', '?') if ok else '❌ ' + str(r)}")


def cmd_stage(env):
    src, dst = HERE / "assets" / "posts", ROOT / "docs" / "social"
    dst.mkdir(parents=True, exist_ok=True)
    pngs = sorted(src.glob("*.png"))
    if not pngs:
        sys.exit("assets/posts/ 沒有圖檔")
    for png in pngs:
        jpg = dst / (png.stem + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png), "--out", str(jpg)], capture_output=True, check=True)
        print(f"  ✓ {jpg.name}")
    print("\n部署 docs/ 中...")
    subprocess.run(["npx", "wrangler", "pages", "deploy", "docs",
                    "--project-name", "marketdaily", "--commit-dirty=true"], cwd=ROOT)
    base = env.get("SITE_BASE", "https://marketdaily.ai")
    print(f"\n完成 —— 圖片公開網址例:{base}/social/00_teaser.jpg")


def caption_for(caption, plat, line_url):
    if plat == "line" or not line_url:
        return caption
    cta = f"📲 加 LINE 不錯過 MarketDaily 👉 {line_url}"
    if "\n\n" in caption:
        head, _, tail = caption.rpartition("\n\n")
        return f"{head}\n\n{cta}\n\n{tail}"
    return f"{caption}\n\n{cta}"


def cmd_post(env, post_id, only=None):
    posts = {p["id"]: p for p in load_posts()}
    if post_id not in posts:
        sys.exit(f"找不到貼文 id:{post_id}(用 list 看清單)")
    post = posts[post_id]
    base = env.get("SITE_BASE", "https://marketdaily.ai")
    is_reel = post.get("type") == "reel"
    if is_reel:
        media_url = f"{base}/social/{post['video']}"
        table = REEL_PLATFORMS
    else:
        media_url = f"{base}/social/{Path(post['image']).stem}.jpg"
        table = PLATFORMS
    targets = only or post["platforms"]
    line_url = env.get("LINE_ADD_URL", "")
    print(f"發布 [{post_id}]{' (Reel)' if is_reel else ''} → {media_url}\n平台:{', '.join(targets)}\n")
    results = {}
    for plat in targets:
        fn = table.get(plat)
        if not fn:
            print(f"  ⚠️ {plat}:{'此貼文型態不支援此平台' if is_reel else '不支援(TikTok 需官方審核)'}")
            continue
        try:
            ok, detail = fn(env, media_url, caption_for(post["caption"], plat, line_url))
        except KeyError as e:
            ok, detail = False, f".env 缺少 {e}"
        results[plat] = {"ok": ok, "detail": str(detail)}
        print(f"  {'✅' if ok else '❌'} {plat}: {detail}")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(), "post": post_id,
                            "results": results}, ensure_ascii=False) + "\n")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "list":
        cmd_list()
        return
    env = load_env()
    if cmd == "check":
        cmd_check(env)
    elif cmd == "stage":
        cmd_stage(env)
    elif cmd == "post":
        if len(args) < 2:
            sys.exit("用法:post <id> [--only instagram,facebook]")
        only = args[args.index("--only") + 1].split(",") if "--only" in args else None
        cmd_post(env, args[1], only)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
