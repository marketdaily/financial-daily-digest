#!/usr/bin/env python3
"""MarketDaily 社群自動發文 — IG / FB / Threads / LINE / X / YouTube / TikTok。

一次性設定見 SETUP_AUTOPOST.md;把權杖填進 marketing/.env。
用法:
    python auto_post.py check                   驗證 .env 權杖是否有效
    python auto_post.py stage                   貼文圖轉 JPEG → docs/social/ → 部署(取得公開網址)
    python auto_post.py list                    列出 social_posts.json 裡的貼文
    python auto_post.py post teaser              發單篇(發到該篇設定的平台)
    python auto_post.py post launch --only instagram,facebook
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
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
            "LINE_CHANNEL_ACCESS_TOKEN", "LINE_ADD_URL", "SITE_BASE",
            "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET",
            "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
            "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
            "TIKTOK_ACCESS_TOKEN", "TIKTOK_REFRESH_TOKEN")


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
    # 行銷貼文改 multicast 排除 premium:從 alert-worker 拉「非 premium 已綁 LINE」清單,
    # 切批 500 推送。未設定 ALERT_WORKER_URL/INTERNAL_TOKEN → fail-closed 跳過。
    worker_url = env.get("MARKETDAILY_ALERT_WORKER_URL")
    internal_tok = env.get("MARKETDAILY_INTERNAL_TOKEN")
    if not worker_url or not internal_tok:
        return False, "skip:未設 MARKETDAILY_ALERT_WORKER_URL/MARKETDAILY_INTERNAL_TOKEN(避免誤發 premium)"
    ok, r = http(f"{worker_url.rstrip('/')}/internal/marketing-line-targets",
                 headers={"Authorization": f"Bearer {internal_tok}"})
    if not ok:
        return False, f"取 targets 失敗: {r}"
    targets = r.get("targets", [])
    if not targets:
        return True, f"no non-premium LINE users (scanned={r.get('scanned',0)} excluded={r.get('excludedPremium',0)})"
    msgs = [
        {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url},
        {"type": "text", "text": caption},
    ]
    headers = {"Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}"}
    sent = 0
    for i in range(0, len(targets), 500):
        chunk = targets[i:i + 500]
        ok, r2 = http("https://api.line.me/v2/bot/message/multicast", "POST",
                      json_body={"to": chunk, "messages": msgs}, headers=headers)
        if not ok:
            return False, f"multicast 第 {i//500+1} 批失敗 (已發 {sent}): {r2}"
        sent += len(chunk)
    return True, f"multicast sent to {sent} non-premium users (excluded premium={r.get('excludedPremium',0)})"


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


# ── X / Twitter(OAuth 1.0a)──

def _pe(s):
    return urllib.parse.quote(str(s), safe="~")


def _oauth1_header(method, url, env, params=None):
    oauth = {
        "oauth_consumer_key": env["X_API_KEY"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": env["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    sig = dict(oauth, **(params or {}))
    base = "&".join(f"{_pe(k)}={_pe(sig[k])}" for k in sorted(sig))
    base_str = "&".join([method.upper(), _pe(url), _pe(base)])
    key = f"{_pe(env['X_API_SECRET'])}&{_pe(env['X_ACCESS_SECRET'])}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base_str.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pe(k)}="{_pe(oauth[k])}"' for k in sorted(oauth))


def _fetch_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "marketdaily-social"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def _multipart(fields):
    boundary = "----md" + secrets.token_hex(8)
    body = b""
    for name, filename, content, ctype in fields:
        body += f"--{boundary}\r\n".encode()
        disp = f'form-data; name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        body += f"Content-Disposition: {disp}\r\n".encode()
        if ctype:
            body += f"Content-Type: {ctype}\r\n".encode()
        body += b"\r\n" + content + b"\r\n"
    return boundary, body + f"--{boundary}--\r\n".encode()


def _x_fit(text, limit=280):
    """X 加權長度:CJK / emoji 算 2;超長先丟 hashtag 段,再硬截。"""
    def wlen(s):
        return sum(2 if ord(c) > 0x1100 else 1 for c in s)
    if wlen(text) <= limit:
        return text
    head, sep, tail = text.rstrip().rpartition("\n\n")
    if sep and tail.lstrip().startswith("#") and wlen(head) <= limit:
        return head
    out = ""
    for c in text:
        if wlen(out) + wlen(c) + 1 > limit:
            break
        out += c
    return out + "…"


def _x_create_tweet(env, text, media_ids=None):
    url = "https://api.twitter.com/2/tweets"
    payload = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    auth = _oauth1_header("POST", url, env)
    ok, r = http(url, "POST", json_body=payload, headers={"Authorization": auth})
    return (True, (r.get("data") or {}).get("id")) if ok else (False, r)


def _x_upload_media(env, data, ctype):
    url = "https://upload.twitter.com/1.1/media/upload.json"
    boundary, body = _multipart([("media", "media", data, ctype)])
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": _oauth1_header("POST", url, env),
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode()).get("media_id_string")
    except Exception:  # noqa: BLE001
        return None


def post_x(env, image_url, caption):
    text = _x_fit(caption)
    media_ids = None
    img = _fetch_bytes(image_url)
    if img:
        ctype = "image/png" if image_url.lower().endswith(".png") else "image/jpeg"
        mid = _x_upload_media(env, img, ctype)
        if mid:
            media_ids = [mid]
    ok, detail = _x_create_tweet(env, text, media_ids)
    if not ok and media_ids:  # 圖片可能不被免費層支援 → 退回純文字
        ok, detail = _x_create_tweet(env, text, None)
    return ok, detail


def post_x_reel(env, video_url, caption):
    # X 影片 chunked upload 較脆弱;影片貼文發純文字(文案已含連結)。
    return _x_create_tweet(env, _x_fit(caption), None)


# ── YouTube(OAuth 2.0 refresh token)──

def _yt_access_token(env):
    ok, r = http("https://oauth2.googleapis.com/token", "POST", form={
        "client_id": env.get("YT_CLIENT_ID", ""),
        "client_secret": env.get("YT_CLIENT_SECRET", ""),
        "refresh_token": env.get("YT_REFRESH_TOKEN", ""),
        "grant_type": "refresh_token"})
    return r.get("access_token") if ok else None


def _yt_title_desc(caption):
    text = caption.strip()
    first, _, rest = text.partition("\n")
    rest = rest.strip()
    if first.startswith("標題"):
        if rest.startswith("說明"):
            rest = rest[2:].lstrip(":：\n ").strip()
        title = first[2:].lstrip(":： ").strip()
    else:
        title = first.strip()
        rest = text
    # YouTube Shorts 認定靠 #Shorts:標題或說明含 hashtag + 垂直 ≤ 60s 即可。
    if "#Shorts" not in title and "#shorts" not in title:
        suffix = " #Shorts"
        title = (title[: 100 - len(suffix)].rstrip() + suffix) if len(title) + len(suffix) > 100 else title + suffix
    if "#Shorts" not in rest and "#shorts" not in rest:
        rest = (rest + "\n\n#Shorts").strip()
    return title[:100], rest


def post_youtube(env, video_url, caption):
    token = _yt_access_token(env)
    if not token:
        return False, "YouTube 權杖刷新失敗(檢查 YT_CLIENT_ID / SECRET / REFRESH_TOKEN)"
    video = _fetch_bytes(video_url)
    if not video:
        return False, f"無法下載影片:{video_url}"
    title, desc = _yt_title_desc(caption)
    meta = json.dumps({
        "snippet": {"title": title, "description": desc, "categoryId": "25",
                    "tags": ["美股", "台股", "財經", "投資理財", "股市"]},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }).encode()
    boundary = "----md" + secrets.token_hex(8)
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + meta + f"\r\n--{boundary}\r\nContent-Type: video/*\r\n\r\n".encode()
            + video + f"\r\n--{boundary}--\r\n".encode())
    url = ("https://www.googleapis.com/upload/youtube/v3/videos"
           "?uploadType=multipart&part=snippet,status")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return True, f"https://youtu.be/{json.loads(r.read().decode()).get('id')}"
    except urllib.error.HTTPError as e:
        return False, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ── TikTok(Content Posting API,PULL_FROM_URL 模式)──
# 沒設 secrets 時安全跳過,不打斷其他平台。app 設置流程見 TIKTOK_SETUP.md。

def _tiktok_access_token(env):
    """優先用現有 access_token;若有 refresh_token,失敗時自動換新。"""
    tok = env.get("TIKTOK_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    rt = env.get("TIKTOK_REFRESH_TOKEN", "").strip()
    ck = env.get("TIKTOK_CLIENT_KEY", "").strip()
    cs = env.get("TIKTOK_CLIENT_SECRET", "").strip()
    if not (rt and ck and cs):
        return None
    ok, r = http("https://open.tiktokapis.com/v2/oauth/token/", "POST", form={
        "client_key": ck, "client_secret": cs,
        "grant_type": "refresh_token", "refresh_token": rt})
    return r.get("access_token") if ok else None


def _tiktok_caption(caption):
    # TikTok 文案上限 2200 字元(含 hashtag);URL 會自動縮短但仍占字元。
    return caption[:2200]


def post_tiktok(env, video_url, caption):
    if not (env.get("TIKTOK_ACCESS_TOKEN") or env.get("TIKTOK_REFRESH_TOKEN")):
        return False, "TikTok 未設定 secrets,跳過(見 TIKTOK_SETUP.md)"
    token = _tiktok_access_token(env)
    if not token:
        return False, "TikTok 權杖刷新失敗(檢查 TIKTOK_CLIENT_KEY / SECRET / REFRESH_TOKEN)"
    payload = {
        "post_info": {
            "title": _tiktok_caption(caption),
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
    }
    ok, r = http("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
                 "POST", json_body=payload,
                 headers={"Authorization": f"Bearer {token}"})
    if ok:
        pid = ((r.get("data") or {}).get("publish_id")) or r.get("publish_id")
        if pid:
            return True, f"publish_id={pid}(影片由 TikTok async 拉取上架)"
    return False, r


PLATFORMS = {"facebook": post_facebook, "instagram": post_instagram,
             "threads": post_threads, "line": post_line, "x": post_x}

REEL_PLATFORMS = {"instagram": post_instagram_reel, "facebook": post_facebook_reel,
                  "youtube": post_youtube, "x": post_x_reel,
                  "tiktok": post_tiktok}


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
    if env.get("X_API_KEY"):
        # 免費層讀取額度極少,不花在健檢;發文用獨立額度,實際發文時才驗證金鑰。
        ready = all(env.get(k) for k in
                    ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
        print(f"  X / Twitter:  {'✅ 4 把金鑰齊全(發文時驗證)' if ready else '❌ 金鑰不齊'}")
    if env.get("YT_REFRESH_TOKEN"):
        # 只授權 youtube.upload(最小權限),故僅驗證 refresh token 能換到 access token。
        token = _yt_access_token(env)
        print(f"  YouTube:      "
              f"{'✅ refresh token 有效(youtube.upload)' if token else '❌ 換取失敗,重跑 get_youtube_token.py'}")
    if env.get("TIKTOK_ACCESS_TOKEN") or env.get("TIKTOK_REFRESH_TOKEN"):
        token = _tiktok_access_token(env)
        if not token:
            print("  TikTok:       ❌ 換取 access token 失敗,重跑 get_tiktok_token.py")
        else:
            ok, r = http("https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name",
                         headers={"Authorization": f"Bearer {token}"})
            info = (r.get("data") or {}).get("user") or {}
            name = info.get("display_name") or info.get("open_id")
            print(f"  TikTok:       {'✅ @' + str(name) if ok and name else '❌ ' + str(r)}")
    else:
        print("  TikTok:       ⏸️ 未設定(見 TIKTOK_SETUP.md)")


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


UTM_SRC = {"instagram": "ig", "facebook": "fb", "threads": "threads",
           "line": "line", "x": "x", "tiktok": "tiktok", "youtube": "youtube"}


def caption_for(caption, plat, line_url):
    # Per-platform UTM source swap so attribution can tell which network drove the click
    src = UTM_SRC.get(plat, "social")
    caption = caption.replace("utm_source=social&", f"utm_source={src}&")
    if plat in ("line", "x") or not line_url:
        return caption
    if plat == "instagram":
        # IG 貼文 / 留言的網址不可點 —— 導向可點的個人簡介連結。
        cta = "📲 加 LINE 即時提醒 — 連結在個人簡介 🔗"
    else:
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
            print(f"  ⚠️ {plat}:此貼文型態不支援此平台")
            continue
        try:
            ok, detail = fn(env, media_url, caption_for(post["caption"], plat, line_url))
        except KeyError as e:
            ok, detail = False, f".env 缺少 {e}"
        # X 未充值、TikTok 未設定 secrets → 軟略過,不打斷其他平台。
        soft = (not ok) and (plat == "x"
                             or (plat == "tiktok"
                                 and not (env.get("TIKTOK_ACCESS_TOKEN") or env.get("TIKTOK_REFRESH_TOKEN"))))
        results[plat] = {"ok": ok, "skipped": soft, "detail": str(detail)}
        mark = "✅" if ok else ("⏭️" if soft else "❌")
        soft_note = ""
        if soft and plat == "x":
            soft_note = "(X 改手動,略過)"
        elif soft and plat == "tiktok":
            soft_note = "(TikTok 未設定 secrets,略過)"
        print(f"  {mark} {plat}: {soft_note}{detail}")
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
