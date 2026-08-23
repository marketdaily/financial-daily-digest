"""Higgsfield CLI token → Claude Code MCP header 同步(2026-08-23)。

Higgsfield 的 OAuth 伺服器回的 iss 是 clerk.higgsfield.ai,和探索文件宣告的
issuer 不符(RFC 9207),Claude Code 拒收 ⇒ 原生 /mcp 授權走不通。CLI 自己的
PKCE 不經過那道檢查,所以拿 CLI 的 access_token 當 Bearer header 用。

鐵則:
  - fail-closed —— 新 token 必須先實打兩台 MCP 都回 200 才寫進設定;
    沒過就保留舊設定並以非零 exit 讓 cron_run_and_alert 推播。
  - 快到期而 CLI 換不出新的 ⇒ 需要人重跑 `higgsfield auth login`,這種
    「只有人能解」的狀態要主動推播,不能等到明天兩台一起啞掉才發現。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

CRED = os.path.expanduser("~/.config/higgsfield/credentials.json")
CFG = os.path.expanduser("~/.claude.json")
SERVERS = {
    "higgsfield": "https://mcp.higgsfield.ai/mcp",
    "higgsfield-bridge": "https://bridge.higgsfield.ai/mcp",
}
RENEW_MARGIN = 6 * 3600


def cli_token():
    out = subprocess.run(["higgsfield", "auth", "token"], capture_output=True, text=True, timeout=60)
    return out.stdout.strip() if out.returncode == 0 else ""


def expires_at():
    try:
        with open(CRED) as fh:
            return int(json.load(fh).get("expires_at", 0))
    except (OSError, ValueError, KeyError):
        return 0


def probe(url, token):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "token-sync", "version": "1"}},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        # ⚠️ UA 必填:Cloudflare 擋預設的 python-urllib,回 403。首版沒帶就把一台
        #    健康的伺服器判成打不通(intel/doctor.py 首版同一個坑,誤報 4 個渠道)。
        "User-Agent": "higgsfield-token-sync/1.0 (winrig)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  探測 {url} 失敗:{exc}")
        return False


def main():
    remaining = expires_at() - time.time()
    print(f"CLI token 剩餘 {remaining / 3600:.1f} 小時")

    if remaining < RENEW_MARGIN:
        # 逼 CLI 走一次認證呼叫,看它會不會自己用 refresh_token 換新的
        subprocess.run(["higgsfield", "account", "status"], capture_output=True, timeout=60)
        remaining = expires_at() - time.time()
        print(f"  觸發 refresh 後剩餘 {remaining / 3600:.1f} 小時")
        if remaining < RENEW_MARGIN:
            print("❌ CLI 換不出新 token —— 需要人重跑 `higgsfield auth login`(瀏覽器 PKCE)")
            return 1

    token = cli_token()
    if len(token) < 20:
        print("❌ higgsfield auth token 取不到 token(CLI 可能已登出)")
        return 1

    for name, url in SERVERS.items():
        if not probe(url, token):
            print(f"❌ 新 token 打不通 {name},fail-closed:不動設定")
            return 1
    print("✅ 新 token 對兩台都回 200")

    with open(CFG) as fh:
        cfg = json.load(fh)
    servers = cfg.setdefault("mcpServers", {})
    changed = []
    for name, url in SERVERS.items():
        entry = servers.setdefault(name, {"type": "http", "url": url})
        headers = entry.setdefault("headers", {})
        want = f"Bearer {token}"
        if headers.get("Authorization") != want:
            headers["Authorization"] = want
            entry["url"] = url
            entry["type"] = "http"
            changed.append(name)

    if not changed:
        print("設定裡已是同一把 token,不用動")
        return 0

    backup = CFG + ".bak-hftoken"
    with open(backup, "w") as fh:
        json.dump(cfg, fh)
    tmp = CFG + ".tmp-hftoken"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, CFG)
    print(f"✅ 已更新 {', '.join(changed)} 的 Authorization header")
    return 0


if __name__ == "__main__":
    sys.exit(main())
