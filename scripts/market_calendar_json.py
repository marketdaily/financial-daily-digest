#!/usr/bin/env python3
"""把 analyzer 的休市日曆匯出成 JSON(給雲端守望犬用)。

存在的理由:digest-watchdog 在雲端,判「今天該不該有日報」時只認週末,
不認美股國定假日 ⇒ 2026-09-07(Labor Day)winrig 正確跳過晚報,守望犬卻推
🔴「日報極可能沒寄」還派了一輪雲端備援。同一個判斷手刻兩次、只有一份知道假日。

這支不重打日曆,只從 analyzer 的 _US_HOLIDAYS / _TW_HOLIDAYS 匯出 ⇒ 唯一真源。
"""
import json
import sys
from datetime import date

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from analyzer import _US_HOLIDAYS, _TW_HOLIDAYS  # noqa: E402


def build(today=None):
    today = today or date.today()
    # 只送今年起的部分:守望犬只問今天,舊年份純粹是 payload 肥肉
    keep = lambda s: {d for d in s if d[:4] >= str(today.year)}  # noqa: E731
    return {
        "generated": today.isoformat(),
        "us": sorted(keep(_US_HOLIDAYS)),
        "tw": sorted(keep(_TW_HOLIDAYS)),
    }


if __name__ == "__main__":
    print(json.dumps(build(), separators=(",", ":")))
