"""防雙發對稱閘迴歸(2026-07-30 晚報事故:21 位訂閱者每人收到兩封)。

事故形狀:watchdog 20:25 撲空派雲端備援 → 雲端 21:02 判 winrig 卡死代打寄出 →
winrig 21:35 生成完成,對雲端已交付一無所知,又寄一輪。
防線原本只裝在雲端單邊(_failover_send_clearance),擋得住「winrig 先寄」擋不住「雲端先寄」。

零網路:直接替換 main._archive_online,只驗裁決邏輯,不打 marketdaily.ai。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import urllib.request  # noqa: E402

import main  # noqa: E402

DATE = "2026-07-30"
FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got} want={want}")
        print(f"  ✗ {name}: got={got} want={want}")
    else:
        print(f"  ✓ {name}")


def run(market, archive_online, env=None):
    """在受控 env + 受控存檔狀態下取得 winrig 端裁決。"""
    saved = {k: os.environ.get(k) for k in ("MD_FAILOVER", "MD_FORCE_SEND")}
    orig_archive, orig_push = main._archive_online, main._push_admin_alert
    main._archive_online = lambda m, d: archive_online
    main._push_admin_alert = lambda *a, **k: None
    try:
        for k in saved:
            os.environ.pop(k, None)
        for k, v in (env or {}).items():
            os.environ[k] = v
        return main._local_send_clearance(market, DATE)
    finally:
        main._archive_online, main._push_admin_alert = orig_archive, orig_push
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


print("── winrig 端反向防雙發閘 ──")
# 正常日:winrig 是唯一交付者,寄出當下存檔還沒被自己推上去 → 照寄
check("正常班次(存檔未上線)→ 放行", run("us", False), True)
check("正常早報(存檔未上線)→ 放行", run("tw", False), True)
# 事故日:雲端已代打並推了存檔 → winrig 退場
check("雲端已代打(存檔已上線)→ 擋下", run("us", True), False)
check("雲端已代打(早報)→ 擋下", run("tw", True), False)
# 雲端自己跑的那份不受這條閘管(由 _failover_send_clearance 裁決)
check("MD_FAILOVER=1 不走本閘", run("us", True, {"MD_FAILOVER": "1"}), True)
# 人工補寄:不可被自己稍早推上去的存檔擋死
check("MARKET=both 手動班次放行", run("both", True), True)
check("MD_FORCE_SEND=1 強制放行", run("us", True, {"MD_FORCE_SEND": "1"}), True)

print("\n── _archive_online 語義(查不到=沒交付=照寄,死線是絕不缺信) ──")


def _urlopen_raises(*a, **k):
    raise OSError("network down")


_saved_urlopen = urllib.request.urlopen
try:
    urllib.request.urlopen = _urlopen_raises
    check("存檔查詢失敗 → 當作未交付(False)", main._archive_online("us", DATE), False)
finally:
    urllib.request.urlopen = _saved_urlopen

if FAILS:
    print(f"\n✗ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("\n✅ 全部通過")
