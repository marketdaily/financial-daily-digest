"""NVIDIA NIM(build.nvidia.com)免費 API key 取得——續跑腳本(2026-08-02)。

背景:Delvin 親令「不要叫我自己去註冊,這是你的工作」。NVIDIA NIM 是目前少數還沒被
政策關門的免費推理層(OpenAI 相容、含 nemotron-ultra-550b/deepseek/glm 等大模型),
且**不需要解 CAPTCHA**——只要 email + 密碼 + 點信裡的裝置驗證連結。

已完成(2026-08-02):帳號 delvin.12345678@gmail.com 的密碼已由本 session 重設並存進
`.env` 的 `NVIDIA_ACCOUNT_PW`,登入本身會過。**卡在最後一步**:NVIDIA 對每個新裝置
要 email 驗證,而當天連續嘗試 6 次後觸發寄信冷卻(不再發新驗證信,但畫面仍停在
Security Challenge)。冷卻過了跑這支一次即可完成。

⚠️ 一次跑完就好,不要連打——每按一次 Log In 就消耗一封驗證信配額,打爆就是再等一輪冷卻。

流程(半自動,因為讀 Gmail 需要 MCP,cron 環境沒有):
  1. `python scripts/nvidia_nim_signup.py` → 它登入並停在 Security Challenge,印出 CHALLENGE_ACTIVE
  2. 這時在 Claude session 用 Gmail MCP 撈 **最新一封** `from:account@nvidia.com`
     主旨 `Authenticate Your Email Address`,取出 `VerifyEmail?q=...` 連結
     ⚠️ 一定要「這次登入觸發的那一封」——用舊的會回 "You are not authorized for this action"
  3. 把連結寫進 `--verify-file` 指的檔案(預設 state/nvidia_verify_url.txt)
  4. 腳本自己點開、回到 build.nvidia.com、抓 API key 印出來
  5. 把 key 填進 .env 的 `NVIDIA_API_KEY`,鏈上接線見 memory
     capability_free_llm_capacity_sourcing(端點 https://integrate.api.nvidia.com/v1,OpenAI 相容)

⚠️ 紅線:圖形 CAPTCHA 一律不解。NVIDIA 這條路目前沒有 CAPTCHA;哪天加了就停手回報。
"""
import argparse
import os
import re
import sys
import time

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {**dotenv_values(os.path.join(REPO, ".env")), **os.environ}
EMAIL = "delvin.12345678@gmail.com"


def dismiss_cookie(page):
    for name in ("Reject Optional", "Accept All"):
        try:
            page.get_by_role("button", name=name).click(timeout=4000)
            time.sleep(1)
            return
        except Exception:
            continue


def body(page):
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(REPO, "state", "nvidia_profile"))
    ap.add_argument("--verify-file", default=os.path.join(REPO, "state", "nvidia_verify_url.txt"))
    ap.add_argument("--wait-verify", type=int, default=300, help="等驗證連結被寫入的秒數")
    args = ap.parse_args()

    pw_val = (ENV.get("NVIDIA_ACCOUNT_PW") or "").strip()
    if not pw_val:
        print("✗ .env 缺 NVIDIA_ACCOUNT_PW(帳號密碼由 2026-08-02 session 重設並存入)")
        return 2
    os.makedirs(os.path.dirname(args.verify_file), exist_ok=True)
    if os.path.exists(args.verify_file):
        os.remove(args.verify_file)   # 舊連結是失效的,留著只會誤用

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, headless=True, viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://build.nvidia.com/?modal=signin", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        dismiss_cookie(page)   # ⚠️ cookie 橫幅會攔截點擊,不關掉 Next/Log In 全部點不到

        if "Login" in body(page)[:400]:
            page.fill('input[placeholder*="email" i]', EMAIL, timeout=15000)
            page.get_by_role("button", name="Next").click(timeout=10000)
            page.wait_for_load_state("networkidle", timeout=45000)
            time.sleep(3)
            page.fill('input[type="password"]', pw_val, timeout=15000)
            try:
                page.get_by_role("button", name="Log In").click(timeout=8000)
            except Exception:
                page.press('input[type="password"]', "Enter")
            time.sleep(6)

        # 裝置驗證:URL 不會變(仍是 /login/password),只有畫面內容變 → 必須用內容判斷
        if "Security Challenge" in body(page):
            print("CHALLENGE_ACTIVE — 請把【這次登入】觸發的最新驗證信連結寫進:",
                  args.verify_file, flush=True)
            deadline = time.time() + args.wait_verify
            while time.time() < deadline:
                if os.path.exists(args.verify_file):
                    url = open(args.verify_file, encoding="utf-8").read().strip()
                    vp = ctx.new_page()
                    vp.goto(url, timeout=60000)
                    time.sleep(4)
                    vtxt = vp.inner_text("body")[:150].replace("\n", " ")
                    print("verify page:", vtxt, flush=True)
                    vp.close()
                    if "not authorized" in vtxt.lower():
                        print("✗ 連結已失效——那是舊的一封。等冷卻後重跑,並取【最新】那封。")
                        ctx.close()
                        return 3
                    break
                time.sleep(3)
            for _ in range(40):
                if "Security Challenge" not in body(page):
                    break
                time.sleep(3)
            else:
                print("✗ 驗證未完成(逾時或 NVIDIA 寄信冷卻中,今日已連續嘗試多次)。等 1 小時再跑一次。")
                ctx.close()
                return 4

        page.goto("https://build.nvidia.com/settings/api-keys", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=45000)
        time.sleep(3)
        dismiss_cookie(page)
        txt = body(page)
        if "Login" in txt[:400]:
            print("✗ 仍未登入,金鑰頁拿不到。檢查密碼或裝置驗證。")
            ctx.close()
            return 5

        for label in ("Generate API Key", "Create API Key", "Generate Key"):
            try:
                page.get_by_role("button", name=label).click(timeout=6000)
                time.sleep(4)
                break
            except Exception:
                continue
        full = body(page)
        m = re.search(r"nvapi-[A-Za-z0-9_\-]{20,}", full)
        if m:
            print("NVIDIA_API_KEY=" + m.group(0))
            print("→ 貼進 .env,再跑 scripts/free_capacity_radar.py 確認 nvidia 進入雷達")
        else:
            print("⚠️ 已登入但沒抓到 nvapi- 金鑰,頁面前 600 字供判讀:\n", full[:600])
        page.screenshot(path=os.path.join(REPO, "state", "nvidia_keys_page.png"))
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
