"""NVIDIA NIM 免費 API key 自動守望(2026-08-02)。

Delvin 親令:「你自己去註冊自己去拿 key,不要每次等我講」。08-02 已由 session 完成
帳號重設密碼 → 裝置 email 驗證 → 建立 NVIDIA Cloud Account「MarketDaily」,登入完全通,
**但 NVIDIA 端把新帳號的 API 存取擋在自家審核後**(API Keys 頁顯示 "API Access
Unavailable / Please contact support to verify your account access")。那是他們的閘,
不繞、不代解——改成每天自動回去看一次,一開通就自己把 key 生出來、寫進 .env、推播通知。

登入態存在持久 profile `state/nvidia_profile`(已 gitignore,含 cookie 不進版控)。
拿到 key 後:端點 https://integrate.api.nvidia.com/v1(OpenAI 相容),接線前一律先跑
`scripts/probe_llm_provider.py` 過品質閘才准進 analyzer._llm_generate 鏈。

用法:
    .venv/bin/python scripts/nvidia_key_watch.py            # 查一次;開通就抓 key
    .venv/bin/python scripts/nvidia_key_watch.py --quiet    # 沒進展就完全靜默(給 cron)
"""
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import requests  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ENV = {**dotenv_values(os.path.join(REPO, ".env")), **os.environ}
PROFILE = os.path.join(REPO, "state", "nvidia_profile")
QUIET = "--quiet" in sys.argv
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def log(*a):
    if not QUIET:
        print(*a, flush=True)


def push(msg):
    tok = (ENV.get("MARKETDAILY_ALERT_TOKEN") or "").strip()
    if not tok:
        return False
    try:
        r = requests.post(
            "https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                     "User-Agent": "md-nvidia-key-watch"},
            json={"message": msg}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def write_env_key(key):
    """把 key 寫進 .env(已有就換掉)。.env 已 gitignore,不會進版控。"""
    path = os.path.join(REPO, ".env")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, found = [], False
    for ln in lines:
        if ln.startswith("NVIDIA_API_KEY="):
            out.append(f"NVIDIA_API_KEY={key}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"NVIDIA_API_KEY={key}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    if (ENV.get("NVIDIA_API_KEY") or "").strip():
        log("已有 NVIDIA_API_KEY,守望結束(要重抓先清掉 .env 那行)")
        return 0
    if not os.path.isdir(PROFILE):
        print("✗ 缺登入 profile:", PROFILE, "— 先跑 scripts/nvidia_nim_signup.py 建立")
        return 2

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True, viewport={"width": 1280, "height": 900}, user_agent=UA)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def dismiss():
            for n in ("Reject Optional", "Accept All"):
                try:
                    page.get_by_role("button", name=n).click(timeout=3000)
                    time.sleep(1)
                    return
                except Exception:
                    continue

        # ⚠️ NVIDIA 的登入 session cookie 不跨瀏覽器啟動存活(08-02 實測:profile 有
        # Cookies 檔但每次啟動都是登出態)→ 每輪都要重登。好消息是 consent 與 Cloud
        # Account 已完成,現在只要 email → Next 就會一路重導回 build(免密碼、免信件驗證)。
        page.goto("https://build.nvidia.com/?modal=signin",
                  timeout=60000, wait_until="domcontentloaded")
        time.sleep(3)
        dismiss()
        try:
            page.fill('input[placeholder*="email" i]', "delvin.12345678@gmail.com", timeout=8000)
            page.get_by_role("button", name="Next").click(timeout=8000)
        except Exception as e:
            log("email step:", str(e)[:60])
        # ⚠️ 不可用 networkidle:NVIDIA 這幾頁長輪詢永遠 idle 不了(08-02 卡過),改輪詢 URL
        for _ in range(30):
            time.sleep(4)
            u = page.url
            b = page.inner_text("body") if page else ""
            if "Security Challenge" in b:
                msg = ("🔑 NVIDIA NIM 守望:又要 email 裝置驗證(換 IP/清 cookie 會觸發)。"
                       "需在 Claude session 用 Gmail 撈最新 VerifyEmail 連結,"
                       "跑 scripts/nvidia_nim_signup.py 完成。")
                print(msg)
                push(msg)
                ctx.close()
                return 3
            if "Almost done" in b:
                try:
                    page.get_by_role("button", name="Submit").click(timeout=8000)
                except Exception:
                    pass
                continue
            if "build.nvidia.com" in u and "Login" not in b[:300]:
                break

        page.goto("https://build.nvidia.com/settings/api-keys",
                  timeout=60000, wait_until="domcontentloaded")
        time.sleep(8)
        dismiss()
        body = page.inner_text("body")

        if "Login" in body[:300]:
            msg = "🔑 NVIDIA NIM 守望:自動重登失敗,需人工看 scripts/nvidia_nim_signup.py"
            print(msg)
            push(msg)
            ctx.close()
            return 3

        if "API Access Unavailable" in body or "contact support to verify" in body:
            log("⏳ 仍在 NVIDIA 帳號審核中(API Access Unavailable),明天再看")
            ctx.close()
            return 0

        for label in ("Generate API Key", "Create API Key", "Generate Key", "Create Key"):
            try:
                page.get_by_role("button", name=label).click(timeout=5000)
                log("clicked:", label)
                time.sleep(8)
                break
            except Exception:
                continue
        m = re.search(r"nvapi-[A-Za-z0-9_\-]{20,}", page.inner_text("body"))
        ctx.close()

    if not m:
        log("⚠️ 審核似乎已過但沒抓到 nvapi- 金鑰,需人工看一眼 build.nvidia.com/settings/api-keys")
        return 4
    write_env_key(m.group(0))
    msg = ("🎉 NVIDIA NIM 免費 API key 已自動取得並寫入 .env(帳號審核通過)。\n"
           "下一步(自動排入 backlog):跑 probe_llm_provider.py 驗品質,過閘才進日報 LLM 鏈。")
    print(msg)
    push(msg)
    backlog = os.path.expanduser("~/autonomous/backlog.md")
    if os.path.isdir(os.path.dirname(backlog)):
        with open(backlog, "a", encoding="utf-8") as f:
            f.write("\n## [算力] NVIDIA NIM key 已到手,實測並接線\n"
                    "- [ ] 把 nvidia 候選加進 scripts/probe_llm_provider.py 的 CANDIDATES"
                    "(端點 https://integrate.api.nvidia.com/v1,OpenAI 相容,免費層 40 RPM),"
                    "兩種 prompt 形狀都跑;過閘(卡數齊/reason≥70字/零捏造)才進 "
                    "analyzer._llm_generate,並更新 memory capability_free_llm_capacity_sourcing\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
