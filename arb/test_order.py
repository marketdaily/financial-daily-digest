"""下單安全閘門自測。零網路。

這支程式會花老闆的錢,所以鎖的不是功能而是「什麼情況下必須不動作」。
"""
import sys

from arb import bidcap
from arb.order import decide
from arb.radar import landed_cost

FAILED = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(name)


ITEM = {"jp_ship": 400, "intl_ship": 900, "duty": 0.05}
RATE = 0.2056


def main():
    print("出價上限:正反解必須一致")
    cap = bidcap.cap_by_roi(15000, 80, RATE, ITEM)
    fwd = landed_cost(cap, RATE, ITEM)
    target = 15000 / 1.8
    check("反解上限的落地成本 = 目標落地(±2)", abs(fwd - target) <= 2,
          f"fwd={fwd} target={target:.0f}")
    check("上限處 ROI 確為 80%(±1)",
          abs((15000 - fwd) / fwd * 100 - 80) <= 1)

    print("上限必須隨成本參數收緊")
    cheap = bidcap.cap_by_roi(15000, 80, RATE, ITEM)
    dear = bidcap.cap_by_roi(15000, 80, RATE, {**ITEM, "intl_ship": 3000})
    check("國際運費變貴→出價上限必須下降", dear < cheap, f"{dear} vs {cheap}")
    high_roi = bidcap.cap_by_roi(15000, 150, RATE, ITEM)
    check("要求更高 ROI→出價上限必須下降", high_roi < cheap)

    print("兩個上限取較嚴格者")
    p = bidcap.plan(15000, RATE, ITEM, target_roi=10, min_margin=9000)
    check("ROI 寬鬆時由 margin 綁定", p["binding"] == "margin", f"得 {p['binding']}")
    check("採用的上限 = 較小者",
          p["cap_jpy"] == min(v for v in p["caps_detail"].values() if v > 0))

    print("決策閘門:超過上限一律不出價")
    plan80 = bidcap.plan(15000, RATE, ITEM, 80, 3000)
    over = {"current_jpy": plan80["cap_jpy"] + 1}
    act, bid, _ = decide(over, plan80)
    check("現價高於上限 1 円即 skip", act == "skip" and bid == 0, f"得 {act}")

    at = {"current_jpy": plan80["cap_jpy"]}
    act2, bid2, _ = decide(at, plan80)
    check("現價剛好等於上限仍可出價", act2 == "bid")
    check("出價金額永不超過上限", bid2 <= plan80["cap_jpy"])

    print("即決價的處理")
    d = decide({"current_jpy": 10000, "buyout_jpy": plan80["cap_jpy"] - 5000}, plan80)
    check("即決在上限內→買斷", d[0] == "buyout" and d[1] == plan80["cap_jpy"] - 5000)
    d2 = decide({"current_jpy": 10000, "buyout_jpy": plan80["cap_jpy"] + 5000}, plan80)
    check("即決超過上限→退回一般出價(不買斷)", d2[0] == "bid")
    check("退回出價時金額仍為上限而非即決價", d2[1] == plan80["cap_jpy"])

    print("缺售價錨時不得出價")
    nocap = bidcap.plan(0, RATE, ITEM, 80, 3000)
    check("沒有售價錨→cap 為 0", nocap["cap_jpy"] == 0)
    check("cap 為 0 時決策必為 skip",
          decide({"current_jpy": 100}, nocap)[0] == "skip")

    print("負毛利情境")
    tiny = bidcap.plan(1200, RATE, ITEM, 80, 3000)   # 售價低於固定運費即不可行
    check("售價不足以覆蓋固定成本→cap 0 或負,不得出價",
          tiny["cap_jpy"] <= 0 or decide({"current_jpy": 1}, tiny)[0] == "skip")

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗:{FAILED}")
        return 1
    print("✅ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
