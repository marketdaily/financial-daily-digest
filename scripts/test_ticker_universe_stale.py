#!/usr/bin/env python3
"""ticker_universe_stale 迴歸測試(2026-09-16)。

守的災難:`portfolio_lens_foreign_ticker`(個人化區塊只准列真實持股)的正確性整個架在
台股代號白名單上,而稽核這一側是**直接開磁碟**、不走 data_fetcher.tw_name_map() 的重抓路徑。
上游連續抓失敗時(2026-07-09 certifi 過期害 TPEx SSL 全滅就是一次),名表會凍住,於是
**新上市的標的查不到 ⇒ 判定非證券 ⇒ 放行** ⇒ 防線在它最該作用的地方先瞎掉,而且無聲。

判準對著災難寫:量的是「白名單多舊了」,不是「白名單有幾筆」(筆數變多變少都不代表新鮮)。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest_audit as A  # noqa: E402

FAILS = []


def ck(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


def stale_findings(**kw):
    A._TW_TICKER_UNIVERSE = None
    html = ('<html><body><div class="section-label">組合透視</div>'
            '<div class="news-card">你的持股:台積電(2330)配置偏高,2026 年目標價 1085。</div>'
            '</body></html>')
    out = A.audit_digest(html, "2026-09-16", us_holdings=[], tw_holdings=["2330"], **kw)
    return [f for f in out if f["check"] == "ticker_universe_stale"]


def main():
    path = A._tw_universe_path()
    if not path:
        print("FAIL: 白名單檔不存在,無法測(這本身就是本檢查要抓的狀態之一)")
        return 1
    orig_mtime = os.path.getmtime(path)
    try:
        # ① 新鮮 → 不報
        os.utime(path, (time.time(), time.time()))
        ck("新鮮的白名單不報(不製造每日噪音)", stale_findings() == [])

        # ② 過期 → MED,而且理由要指名「放行」這個後果,不是只說「舊了」
        old = time.time() - (A.TICKER_UNIVERSE_STALE_DAYS + 3) * 86400
        os.utime(path, (old, old))
        got = stale_findings()
        ck("過期白名單要報", len(got) == 1, str(got))
        if got:
            ck("severity=med(不擋寄信、不進 retry 鏈)", got[0]["severity"] == "med", got[0]["severity"])
            ck("訊息講出後果(放行/半瞎)而不只是『舊了』",
               ("放行" in got[0]["msg"]) and ("瞎" in got[0]["msg"]), got[0]["msg"])

        # ③ 邊界:剛好等於門檻不報(> 才報,不要在門檻上忽紅忽綠)
        edge = time.time() - (A.TICKER_UNIVERSE_STALE_DAYS * 86400) + 120
        os.utime(path, (edge, edge))
        ck("剛好在門檻內不報", stale_findings() == [])

        # ④ 純公版報告(無持股)不檢查 —— 它根本沒用到白名單,不該被噪音打到
        os.utime(path, (old, old))
        A._TW_TICKER_UNIVERSE = None
        pub = A.audit_digest('<html><body><div>組合透視</div></body></html>', "2026-09-16",
                             us_holdings=[], tw_holdings=[])
        ck("無持股的公版報告不報這條", [f for f in pub if f["check"] == "ticker_universe_stale"] == [])

        # ⑤ 突變:把門檻改成天文數字 ⇒ ② 必須紅(證明這條斷言真的在量門檻)
        keep = A.TICKER_UNIVERSE_STALE_DAYS
        A.TICKER_UNIVERSE_STALE_DAYS = 10 ** 6
        os.utime(path, (old, old))
        mutated_silent = stale_findings() == []
        A.TICKER_UNIVERSE_STALE_DAYS = keep
        ck("突變(門檻放到無限大)會讓它安靜 ⇒ 本測試有鑑別力", mutated_silent)
    finally:
        os.utime(path, (orig_mtime, orig_mtime))
        A._TW_TICKER_UNIVERSE = None

    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 條沒過:{FAILS}")
        return 1
    print("✅ ticker_universe_stale 全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
