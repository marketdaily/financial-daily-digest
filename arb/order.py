"""Buyee 代客出價/下單。預設 dry-run,要 --confirm 才會真的動錢。

安全設計(這支程式會花老闆的錢,閘門優先於功能):
  1. 預設 dry-run。沒有 --confirm 就只印計畫,絕不送出。
  2. 出價上限由 bidcap 依目標 ROI 反算,**程式硬性拒絕超過上限的出價**,不接受手動覆寫。
  3. 總預算上限(--budget),累計超過即停,不會「只差一點就買完了」。
  4. 解析不確定即拒絕(fail-closed):抓不到現價/即決價就不出價,不猜。
  5. 未登入即停:代理瀏覽器沒有 Buyee session 就不動作。
  6. 每次動作寫 orders.jsonl 帳本。

⚠️ 信用卡:本程式**永不輸入卡號**。付款方式須由 Delvin 事先在 Buyee 網站綁定,
   下單時只選用已存的付款方式。

用法:
  python -m arb.order --plan                        # 看所有標的的出價上限
  python -m arb.order --item <buyee_url> --sell 15000 --dry
  python -m arb.order --item <buyee_url> --sell 15000 --confirm --budget 40000
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from arb import bidcap, sources  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "orders.jsonl")
PROFILE = Path.home() / ".claude-browser" / "profile"

TARGET_ROI = 80          # 出價上限的目標 ROI(%)
MIN_MARGIN = 3000        # 同時要求的絕對淨利下限(NT$)

PRICE_RE = re.compile(r"([0-9][0-9,]{2,})\s*(?:YEN|円|JPY)", re.I)


def log(row):
    row = {"ts": datetime.now(timezone.utc).isoformat(), **row}
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def is_logged_in(page):
    """代理瀏覽器是否已有 Buyee session。沒有就不該動作。"""
    try:
        page.goto("https://buyee.jp/mypage/index", timeout=45_000)
        page.wait_for_timeout(2500)
        if "/signup/login" in page.url or "/login" in page.url:
            return False
        return page.query_selector(
            "a[href*='logout'], a[href*='/mypage/'], a[href*='/signup/logout']") is not None
    except Exception:
        return False


def parse_item(page, url):
    """抓商品現況。任何關鍵欄位缺失即回 error(fail-closed,不猜)。"""
    try:
        page.goto(url, timeout=60_000)
        page.wait_for_timeout(3500)
        txt = page.inner_text("body")
    except Exception as e:
        return {"error": f"fetch_failed:{e}"}

    if any(k in txt for k in ("オークションは終了", "This auction has ended", "終了しました")):
        return {"error": "auction_ended"}

    prices = [int(x.replace(",", "")) for x in PRICE_RE.findall(txt)]
    prices = [p for p in prices if 100 <= p <= 5_000_000]
    if not prices:
        return {"error": "price_parse_failed"}

    buyout = None
    m = re.search(r"即決価格[^0-9]{0,40}([0-9][0-9,]{2,})", txt)
    if m:
        buyout = int(m.group(1).replace(",", ""))

    tm = re.search(r"(?:Time Remaining|残り時間|終了まで)[\s\S]{0,40}?"
                   r"([0-9]+\s*(?:Days?|日|Hours?|時間|Min|分))", txt)
    return {
        "url": url,
        "current_jpy": min(prices),
        "buyout_jpy": buyout,
        "time_left": tm.group(1).strip() if tm else None,
        "raw_prices": prices[:6],
    }


def decide(item_data, cap_plan, strategy="buyout"):
    """回傳 (action, bid_jpy, reason)。任何超過上限的情況一律 skip。

    strategy:
      buyout — 即決在上限內就買斷。**確定拿到**,但現價遠低於即決時會多付錢。
      bid    — 一律代理出價到上限。可能以遠低於即決的價格得標(省錢),
               但可能被別人超過而拿不到,且要等到結標。
    首批建議 buyout(目的是驗證整條鏈,確定性 > 省錢);量產後改 bid。
    """
    cap = cap_plan["cap_jpy"]
    if cap <= 0:
        return ("skip", 0, "無法算出出價上限(缺售價錨)")
    cur = item_data["current_jpy"]
    if cur > cap:
        return ("skip", 0, f"現價 ¥{cur:,} 已超過上限 ¥{cap:,}")
    bo = item_data.get("buyout_jpy")
    if strategy == "buyout" and bo and bo <= cap:
        return ("buyout", bo, f"即決 ¥{bo:,} 在上限 ¥{cap:,} 內,直接買斷(確定拿到)")
    return ("bid", cap, f"代理出價到上限 ¥{cap:,}(現價 ¥{cur:,},可能以更低價得標)")


def run(args):
    item_cfg = {"jp_ship": args.jp_ship, "intl_ship": args.intl_ship, "duty": 0.05}
    rate = sources.jpy_twd_rate()["rate"]
    cap_plan = bidcap.plan(args.sell, rate, item_cfg,
                           target_roi=args.roi, min_margin=MIN_MARGIN)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # dry-run 不需要登入,用一般 context(快、且不去鎖住代理瀏覽器的 profile);
        # 只有真的要送出時才開持久化 profile。
        if args.confirm:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), channel="chrome", headless=True,
                locale="ja-JP", timezone_id="Asia/Tokyo",
                args=["--disable-blink-features=AutomationControlled"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            logged = is_logged_in(page)
        else:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=sources.UA,
                                      locale="ja-JP", timezone_id="Asia/Tokyo")
            page = ctx.new_page()
            logged = False

        data = parse_item(page, args.item)

        if "error" in data:
            print(f"🔴 {data['error']} — 不出價(fail-closed)")
            log({"action": "abort", "reason": data["error"], "url": args.item})
            ctx.close()
            return 1

        action, bid, reason = decide(data, cap_plan, args.strategy)
        print(f"商品:{args.item}")
        print(f"  現價 ¥{data['current_jpy']:,}"
              + (f" / 即決 ¥{data['buyout_jpy']:,}" if data.get("buyout_jpy") else "")
              + (f" / 剩餘 {data['time_left']}" if data.get("time_left") else ""))
        print(f"  出價上限 ¥{cap_plan['cap_jpy']:,}(ROI {args.roi}% 綁定={cap_plan['binding']})"
              f" → 落地 NT${cap_plan['landed_at_cap']:,}、淨利 NT${cap_plan['margin_at_cap']:,}")
        print(f"  決策:{action} — {reason}")

        if action == "skip":
            log({"action": "skip", "reason": reason, **data})
            ctx.close()
            return 0

        landed = bidcap.landed_from_jpy(bid, rate, item_cfg)
        if landed > args.budget:
            print(f"🔴 落地 NT${landed:,.0f} 超過本次預算 NT${args.budget:,} — 停手")
            log({"action": "budget_stop", "landed": landed, "budget": args.budget, **data})
            ctx.close()
            return 0

        if not args.confirm:
            bo = data.get("buyout_jpy")
            if bo and bo <= cap_plan["cap_jpy"] and data["current_jpy"] < bo:
                lo = bidcap.landed_from_jpy(data["current_jpy"], rate, item_cfg)
                print(f"  ↔ 兩種策略:買斷 ¥{bo:,}(落地 {round(landed):,}) "
                      f"vs 競標若以現價 ¥{data['current_jpy']:,} 得標(落地 {round(lo):,},"
                      f"多賺 {round(landed - lo):,})——競標省錢但可能被搶走")
            print("\n【DRY-RUN】未送出。確認無誤後加 --confirm 才會真的出價。")
            log({"action": "dry_run", "would": action, "bid_jpy": bid, **data})
            ctx.close()
            return 0

        if not logged:
            print("🔴 代理瀏覽器沒有 Buyee 登入 session — 拒絕動作。\n"
                  "   先跑:python3 scripts/agent_browser_login.py buyee")
            log({"action": "abort", "reason": "not_logged_in", **data})
            ctx.close()
            return 1

        # === 真的送出 ===
        print("\n送出中…")
        ok, detail = submit(page, action, bid)
        print(("✅ " if ok else "🔴 ") + detail)
        log({"action": action, "submitted": ok, "detail": detail,
             "bid_jpy": bid, "landed_ntd": round(landed), **data})
        ctx.close()
        return 0 if ok else 1


def submit(page, action, bid_jpy):
    """在 Buyee 商品頁送出出價/即決。⚠️ 尚未在生產驗證過(需真實登入+真實花錢)。"""
    try:
        sel = ("a[href*='/bid'], button.btn_bid, .bidBtn"
               if action == "bid" else
               "a[href*='/buyout'], button.btn_buyout, .buyoutBtn")
        btn = page.query_selector(sel)
        if not btn:
            return False, f"找不到{'出價' if action == 'bid' else '即決'}按鈕(版面可能改版)—— 未送出"
        btn.click()
        page.wait_for_timeout(3000)

        if action == "bid":
            box = page.query_selector("input[name*='price'], input#bid_price, input.bidPrice")
            if not box:
                return False, "找不到出價金額欄位 —— 未送出"
            box.fill(str(bid_jpy))
            page.wait_for_timeout(800)

        confirm = page.query_selector(
            "button[type='submit'], input[type='submit'], .btn_confirm")
        if not confirm:
            return False, "找不到確認送出按鈕 —— 未送出"
        confirm.click()
        page.wait_for_timeout(4000)
        body = page.inner_text("body")
        if any(k in body for k in ("完了", "Completed", "受け付け", "Thank you")):
            return True, f"已送出({action} ¥{bid_jpy:,})"
        return False, f"送出後未見成功字樣,請人工確認:{page.url}"
    except Exception as e:
        return False, f"送出失敗:{e}"


def show_plans():
    """列出所有標的的出價上限,不觸網下單。"""
    rate = sources.jpy_twd_rate()["rate"]
    with open(os.path.join(HERE, "dashboard_data.json"), encoding="utf-8") as f:
        d = json.load(f)
    print(f"匯率 {rate:.4f}｜目標 ROI {TARGET_ROI}%｜最低淨利 NT${MIN_MARGIN:,}\n")
    print(f"{'標的':<34}{'台灣售價':>9}{'出價上限¥':>11}{'上限落地':>9}{'上限淨利':>9}")
    for g in d["golf"]:
        if not g.get("sell"):
            print(f"{g['name'][:32]:<34}{'無錨':>9}{'—':>11}{'—':>9}{'—':>9}")
            continue
        cfg = {"jp_ship": g["jp_ship"], "intl_ship": g["intl_ship"], "duty": 0.05}
        p = bidcap.plan(g["sell"], rate, cfg, TARGET_ROI, MIN_MARGIN)
        print(f"{g['name'][:32]:<34}{g['sell']:>9,}{p['cap_jpy']:>11,}"
              f"{p['landed_at_cap']:>9,}{p['margin_at_cap']:>9,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只列出價上限,不下單")
    ap.add_argument("--item", help="Buyee 商品 URL")
    ap.add_argument("--sell", type=int, help="台灣售價錨(NT$)")
    ap.add_argument("--roi", type=int, default=TARGET_ROI)
    ap.add_argument("--jp-ship", dest="jp_ship", type=int, default=400)
    ap.add_argument("--intl-ship", dest="intl_ship", type=int, default=900)
    ap.add_argument("--budget", type=int, default=15000, help="本筆落地成本上限 NT$")
    ap.add_argument("--strategy", choices=("buyout", "bid"), default="buyout",
                    help="buyout=即決買斷(確定拿到);bid=代理出價(可能更便宜但可能拿不到)")
    ap.add_argument("--dry", action="store_true", help="明示 dry-run(預設就是)")
    ap.add_argument("--confirm", action="store_true", help="真的送出(會花錢)")
    args = ap.parse_args()

    if args.plan or not args.item:
        show_plans()
        if not args.item:
            print("\n(要下單:--item <buyee_url> --sell <台灣售價>;預設 dry-run)")
        return 0
    if not args.sell:
        print("需要 --sell(台灣售價錨),否則算不出出價上限")
        return 1
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
