"""site_scan 第三方/自家來源分流迴歸(2026-08-16,夜巡事件 E29)。

事故形狀:08-13 00:21 site_scan 判 /pricing 🔴「console errors: Failed to load resource 404」,
自動修復改不動(那是 fonts.gstatic.com 字型檔的暫時 404),於是升級成「需人工深修」。
08-16 用同一支掃描器/同一個 UA/真 Chrome 連掃三頁 0 失敗 —— 不可重現的第三方抖動。

這支釘住的不變量,每一條都對應一個【已經發生過或差點發生】的失誤:
  ① 第三方 4xx 不得判 fail(誤告來源)
  ② 自家 4xx 仍然必須判 fail(**放行方向的反向控制**——沒有這條,把全部都歸第三方也會綠)
  ③ 認不得的 host 一律當自家(fail-closed;這條 guard 只准降級「確定是別人家的」)
  ④ URL 不得再被砍在 80 字元(原 bug 讓報告裡的 gstatic URL 連 .woff2 都不見,
     診斷第一眼會以為是我們自己寫死了壞路徑)

零網路:直接呼叫純函式與 router,用假的 console/response 物件。
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_ss", os.path.join(_HERE, "site_scan.py"))
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")
        print(f"  ✗ {name}: got={got!r} want={want!r}")
    else:
        print(f"  ✓ {name}")


class Resp:
    def __init__(self, status, url):
        self.status, self.url = status, url


class Msg:
    def __init__(self, text, url=None, type="error"):
        self.text, self.type = text, type
        self.location = {"url": url} if url else None


# E29 的真實肇事 URL(完整版,80 字元處正好切在 `...SjIw2boKoduKmM`)
GSTATIC = ("https://fonts.gstatic.com/s/inter/v20/"
           "UcCB3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMxbfmLjBTaWpVE.woff2")

print("── _own_origin 歸屬判定 ──")
check("自家主域", ss._own_origin("https://marketdaily.ai/pricing"), True)
check("自家子域", ss._own_origin("https://api.marketdaily.ai/x"), True)
check("自家 worker", ss._own_origin("https://marketdaily-webhook.delvin-12345678.workers.dev/y"), True)
check("第三方 gstatic", ss._own_origin(GSTATIC), False)
check("第三方 googleapis", ss._own_origin("https://fonts.googleapis.com/css2?family=Inter"), False)
# fail-closed:認不得一律當自家,否則這條 guard 會變成「看不懂就放行」
check("空字串→當自家(fail-closed)", ss._own_origin(""), True)
check("非 URL 垃圾→當自家(fail-closed)", ss._own_origin("not a url at all"), True)
check("data: URI→當自家(fail-closed)", ss._own_origin("data:image/png;base64,AAAA"), True)
# ⚠️ 反向控制:名字裡含自家字樣但不是自家網域,不准被當自家
check("釣魚型 host 不得誤判為自家", ss._own_origin("https://marketdaily.ai.evil.com/x"), False)
check("尾綴黏著不算子域", ss._own_origin("https://notmarketdaily.ai/x"), False)

print("\n── _response_router 分流 ──")
own, third = [], []
r = ss._response_router(own, third)
r(Resp(404, GSTATIC))
check("① 第三方 404 進第三方桶", (len(own), len(third)), (0, 1))
r(Resp(404, "https://marketdaily.ai/assets/stocks.js"))
# ② 反向控制:沒有這條,把所有東西都歸第三方一樣會全綠
check("② 自家 404 仍進 fail 桶", (len(own), len(third)), (1, 1))
r(Resp(500, "https://marketdaily-webhook.delvin-12345678.workers.dev/api"))
check("② 自家 worker 5xx 也進 fail 桶", len(own), 2)
r(Resp(200, "https://marketdaily.ai/ok.js"))
check("2xx 不進任何桶", (len(own), len(third)), (2, 1))
r(Resp(404, "https://marketdaily.ai/favicon.ico"))
check("favicon 照舊豁免", (len(own), len(third)), (2, 1))

print("\n── ④ URL 不得再被砍在 80 字元 ──")
check("完整 URL 留到 .woff2", third[0].endswith(".woff2"), True)
check("長度超過舊上限 80", len(third[0]) > 80 + len("404 "), True)

print("\n── _console_router 分流 ──")
cown, cthird = [], []
c = ss._console_router(cown, cthird)
c(Msg("Failed to load resource: the server responded with a status of 404 ()", url=GSTATIC))
check("① 第三方資源的 console error 進第三方桶", (len(cown), len(cthird)), (0, 1))
c(Msg("TypeError: x is not a function", url="https://marketdaily.ai/ui-pro.js"))
check("② 自家 JS 例外仍進 fail 桶", (len(cown), len(cthird)), (1, 1))
# location 缺席(pageerror 型)→ fail-closed 當自家,不可被靜默丟掉
c(Msg("Uncaught (in promise) Error: boom", url=None))
check("③ 無 location 的 error 當自家(fail-closed)", len(cown), 2)
c(Msg("just a warning", url=GSTATIC, type="warning"))
check("非 error 級別不進任何桶", (len(cown), len(cthird)), (2, 1))

print("\n── info 級別不得計入 fail(否則降級等於沒做)──")
ss.RESULTS.clear()
ss.check("page/pricing_thirdparty", True, "第三方資源失敗", severity="info")
ss.check("page/pricing_requests", False, "自家 404", severity="med")
fails = [x for x in ss.RESULTS if not x["ok"]]
check("info+ok=True 不算 fail", len(fails), 1)
check("自家的仍算 fail", fails[0]["check"], "page/pricing_requests")
ss.RESULTS.clear()

if FAILS:
    print(f"\n✗ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("\n✅ 全部通過")
