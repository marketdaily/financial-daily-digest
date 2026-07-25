"""回歸測試:_yf_guard 防 yfinance/Yahoo 無 timeout 呼叫永久卡死。

2026-07-25 週六早報 06:34 卡死:yf.Ticker(sym).history(period='5d') 連上 Yahoo(e1-bmr.ycpi)
後伺服器不回應→永久卡 socket poll 1.5h、digest 未寄。修:所有 yf history/news/calendar
經 _yf_guard(daemon thread + join(timeout)),逾時回 default、卡死 thread 不擋主程序退出。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_fetcher as d  # noqa: E402


def run():
    # 1) 正常呼叫直接回值
    assert d._yf_guard(lambda: 42) == 42, "[FAIL] 正常值"
    assert d._yf_guard(lambda: {"a": 1}) == {"a": 1}, "[FAIL] 正常物件"

    # 2) 呼叫拋例外 → 回 default(不外洩例外)
    assert d._yf_guard(lambda: 1 / 0, default="X") == "X", "[FAIL] 例外未回 default"
    assert d._yf_guard(lambda: [][5], default=[]) == [], "[FAIL] IndexError 未回 default"

    # 3) 核心:永久卡死的呼叫 → timeout 內回 default(模擬 Yahoo poll 卡死)
    t0 = time.time()
    r = d._yf_guard(lambda: time.sleep(9999), timeout=2, default="TIMEOUT")
    dt = time.time() - t0
    assert r == "TIMEOUT", f"[FAIL] 逾時未回 default: {r}"
    assert 1.8 < dt < 4.5, f"[FAIL] 逾時時間不對(應~2s): {dt:.1f}s"

    # 4) default 預設為 None(呼叫端視同無資料)
    assert d._yf_guard(lambda: time.sleep(9999), timeout=1) is None, "[FAIL] 預設 default 非 None"

    print(f"✅ _yf_guard 回歸測試全過(卡死呼叫 {dt:.1f}s 內回 default、主程序不卡)")


if __name__ == "__main__":
    run()
