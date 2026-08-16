"""Cloudflare Browser Run (Kitesurf) 共用積木 — serverless 瀏覽器渲染抓頁。

用途:JS-heavy 頁面抓取(cnyes/SPA 類),取代本機 Playwright 的輕量場景。
Kitesurf beta 期間免費(額度未公布);datacenter IP 出口,會擋機房 IP 的站(IG 等)不適用。
token 來源:env CLOUDFLARE_BROWSER_RUN_TOKEN / CLOUDFLARE_API_TOKEN,
fallback 讀 wrangler OAuth(短效,只適合互動測試,cron 要用正式 scoped token)。

CLI: python3 -m intel.browser_run <url> [--browser kitesurf|chromium] [--endpoint markdown|content|links] [--wait networkidle0]
"""
import json
import os
import pathlib
import re
import sys
import urllib.request

ACCOUNT_ID = "a92082d84f08b1d4883facbf1a1dc445"
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/browser-run"


def _wrangler_oauth_token():
    """2026-08-16:這裡原本是全機第 7 份手刻的「開 default.toml、regex 挖 oauth_token」。
    收斂到唯一解析器(env → ~/Delvin-agent/.env → OAuth 檔,且會看 expiration_time)。
    解析器不在時才退回原本那段,退回不靜默。"""
    import sys
    caps = str(pathlib.Path.home() / "autonomous" / "capabilities")
    if caps not in sys.path:
        sys.path.append(caps)
    try:
        from cf_token.resolve import cf_token_or_none
        return cf_token_or_none()
    except Exception as e:  # noqa: BLE001
        print(f"[browser_run] cf_token 解析器不可用({e}),退回直讀 OAuth 檔", file=sys.stderr)
        cfg = pathlib.Path.home() / ".config/.wrangler/config/default.toml"
        if not cfg.exists():
            return None
        m = re.search(r'oauth_token = "([^"]+)"', cfg.read_text())
        return m.group(1) if m else None


def _env_file_token():
    for env in (pathlib.Path(__file__).resolve().parent.parent / ".env",
                pathlib.Path.home() / "Delvin-agent/.env"):
        if env.exists():
            m = re.search(r"^CLOUDFLARE_BROWSER_RUN_TOKEN=(\S+)", env.read_text(), re.M)
            if m:
                return m.group(1)
    return None


def get_token():
    tok = (os.environ.get("CLOUDFLARE_BROWSER_RUN_TOKEN")
           or os.environ.get("CLOUDFLARE_API_TOKEN")
           or _env_file_token())
    if tok:
        return tok
    tok = _wrangler_oauth_token()
    if not tok:
        raise RuntimeError("no Cloudflare token: set CLOUDFLARE_BROWSER_RUN_TOKEN or wrangler login")
    return tok


def fetch(url, browser="kitesurf", endpoint="markdown", wait=None, timeout=90):
    """回傳 (success, result_or_errors)。wait='networkidle0' 給 SPA 用(較慢)。"""
    body = {"url": url}
    if wait:
        body["gotoOptions"] = {"waitUntil": wait, "timeout": min(timeout, 60) * 1000}
    req = urllib.request.Request(
        f"{API}/{endpoint}?browser={browser}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return d.get("success", False), d.get("result") if d.get("success") else d.get("errors")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    url = args[0]
    opts = dict(zip(args[1::2], args[2::2]))
    ok, result = fetch(
        url,
        browser=opts.get("--browser", "kitesurf"),
        endpoint=opts.get("--endpoint", "markdown"),
        wait=opts.get("--wait"),
    )
    if not ok:
        print(f"FAIL: {result}", file=sys.stderr)
        sys.exit(1)
    print(result)


if __name__ == "__main__":
    main()
