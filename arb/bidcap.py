"""出價上限:由目標 ROI 反推「最高能出多少日圓」。

拍賣不是「看到便宜就買」,是「先算出上限,出到上限為止」。
別人出得比上限高 → 讓掉,因為超過那個價這筆生意就不賺錢了。

⚠️ 成本算式**不在這裡** —— 正解與反解同源於 `arb/costs.py`。
   2026-08-05 之前這支自己手刻了一份反解,和 radar 的正解各漏同一批 Buyee 費用,
   於是「毛利」與「出價上限」一起高估卻互相對得起來。不要再在這裡刻第二份。
"""
from arb import costs

landed_from_jpy = costs.landed_from_jpy


def cap_for_target_landed(target_landed, rate, item):
    """給定可接受的落地成本,回推最高日圓出價。不可行回 0。"""
    if rate <= 0:
        return 0
    return int(costs.jpy_for_landed(target_landed, rate, item))


def cap_by_roi(sell_price, target_roi_pct, rate, item):
    """出價上限:讓 (售價-落地)/落地 >= target_roi 的最高日圓價。"""
    if sell_price <= 0:
        return 0
    target_landed = sell_price / (1 + target_roi_pct / 100.0)
    return cap_for_target_landed(target_landed, rate, item)


def cap_by_margin(sell_price, min_margin, rate, item):
    """出價上限:讓絕對淨利 >= min_margin 的最高日圓價。"""
    if sell_price <= 0:
        return 0
    return cap_for_target_landed(sell_price - min_margin, rate, item)


def plan(sell_price, rate, item, target_roi=80, min_margin=None):
    """回傳完整出價計畫。兩個上限取較嚴格者,避免單一指標失效。"""
    caps = {"roi": cap_by_roi(sell_price, target_roi, rate, item)}
    if min_margin:
        caps["margin"] = cap_by_margin(sell_price, min_margin, rate, item)
    cap = min(v for v in caps.values() if v > 0) if any(caps.values()) else 0
    landed = landed_from_jpy(cap, rate, item) if cap else 0
    return {
        "cap_jpy": cap,
        "caps_detail": caps,
        "binding": min(caps, key=lambda k2: caps[k2]) if caps else None,
        "landed_at_cap": round(landed),
        "margin_at_cap": round(sell_price - landed),
        "roi_at_cap": round((sell_price - landed) / landed * 100) if landed else 0,
        "sell": sell_price,
        "cost_model": costs.COST_MODEL,
    }
