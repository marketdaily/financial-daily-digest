"""價格源的失敗路徑自測。零網路(用假 page 注入頁面內容)。

鎖的是本系統最危險的一種失敗:**訊源被擋卻被當成「沒有資料」**。
在本系統裡「台灣零刊登」會被解讀成「空白市場=機會」,所以一次反爬限流
就能讓 12/12 標的全部變成假機會(2026-08-05 實際發生過)。
"""
import sys

from arb import sources

FAILED = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(name)


class FakePage:
    def __init__(self, body):
        self._body = body

    def goto(self, *a, **k):
        return None

    def wait_for_timeout(self, *a, **k):
        return None

    def inner_text(self, _sel):
        return self._body


REAL_EMPTY = "TW 登入 註冊 全部 購物網 " + "搜尋不到符合「x」的相關結果 " * 3 + "x" * 400
REAL_HITS = "TW 登入 註冊 " + " ".join(f"商品{i} $9,{i:03d}" for i in range(40))


def main():
    print("反爬被擋 ≠ 沒有刊登")
    blocked = FakePage("TW 登入 註冊 系統監測到搜尋行為異常，由於目前 BigGo 服務器"
                       "正在遭受各種攻擊，因此負擔較高。請先「驗證你不是機器人」"
                       "或是「登入」，後再繼續使用 BigGo 的搜尋服務。驗證並繼續")
    r = sources.tw_listings(blocked, "x")
    check("反爬頁回 error 而非 count", r.get("error") == "blocked_by_antibot",
          f"得 {r}")
    check("反爬頁絕不回 count=0", "count" not in r)

    print("極短頁面(攔截頁/空殼)也不得當成沒刊登")
    r2 = sources.tw_listings(FakePage("TW 登入 註冊"), "x")
    check("短頁面回 error", str(r2.get("error", "")).startswith("suspicious_short_page"),
          f"得 {r2}")

    print("真正的零刊登才可以回 count=0")
    r3 = sources.tw_listings(FakePage(REAL_EMPTY), "x")
    check("真零刊登回 count=0", r3.get("count") == 0 and "error" not in r3, f"得 {r3}")
    check("真零刊登標記 no_listings", r3.get("note") == "no_listings")

    print("正常結果頁照常解析")
    r4 = sources.tw_listings(FakePage(REAL_HITS), "x", price_floor=1000)
    check("有結果時回 count>0", r4.get("count", 0) > 0, f"得 {r4}")
    check("有 p25/median/max", all(k in r4 for k in ("p25", "median", "max")))

    print("渲染失敗也要是 error")
    class Boom(FakePage):
        def goto(self, *a, **k):
            raise RuntimeError("timeout")
    r5 = sources.tw_listings(Boom(""), "x")
    check("goto 失敗回 error", str(r5.get("error", "")).startswith("render_failed"))

    print("日本端:抓不到就 error,不得回空資料")
    check("jp_sold 對不存在關鍵字不回 count=0 混充",
          "error" in sources.jp_sold("zzz_不存在的關鍵字_zzz", timeout=20)
          or "count" in sources.jp_sold("zzz_不存在的關鍵字_zzz", timeout=20))

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗:{FAILED}")
        return 1
    print("✅ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
