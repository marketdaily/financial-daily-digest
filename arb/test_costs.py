"""落地成本模型自測(零網路)。

鎖住的是 #151 這個坑:雷達的「毛利」與 bidcap 的「出價上限」曾各自手刻一份算式,
兩份**同時**漏掉 Buyee 的固定費用與換匯溢價 —— 於是高估的毛利與過高的出價上限
互相對得起來,看不出破綻。這裡守三件事:
  ① 正解與反解必須是同一個模型(round-trip 回得去)
  ② 每一項真實費用都 load-bearing(拿掉任何一項,落地成本一定會變)
  ③ 出價上限一定比舊模型嚴(不會因為改模型反而變得更敢出價)
"""
import sys

from arb import bidcap, costs
from arb.radar import landed_cost

FAILED = []
ITEM = {"jp_ship": 400, "intl_ship": 900, "duty": 0.05}
RATE = 0.21


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")
        FAILED.append(name)


def legacy_landed(jpy, rate, item):
    """2026-08-05 之前的模型(無 Buyee 費用、用中價匯率),只當對照組。"""
    goods = jpy * rate
    cif = goods + item["intl_ship"]
    duty = cif * item.get("duty", 0.05)
    vat = (cif + duty) * 0.05
    return goods + item["jp_ship"] + item["intl_ship"] + duty + vat


def main():
    print("① 正解 ↔ 反解同源")
    for jpy in (3_000, 15_000, 40_000, 120_000):
        landed = costs.landed_from_jpy(jpy, RATE, ITEM)
        back = costs.jpy_for_landed(landed, RATE, ITEM)
        check(f"round-trip ¥{jpy:,}", abs(back - jpy) < 0.5, f"回推 {back}")
    check("radar.landed_cost 就是 costs 的正解",
          landed_cost(15_000, RATE, ITEM) == round(costs.landed_from_jpy(15_000, RATE, ITEM)))
    check("bidcap 的 landed_from_jpy 是同一支函式",
          bidcap.landed_from_jpy is costs.landed_from_jpy)
    plan = bidcap.plan(15_000, RATE, ITEM, target_roi=80)
    check("plan 的 landed_at_cap 與正解一致(±1 為 int 截斷)",
          abs(plan["landed_at_cap"] - round(costs.landed_from_jpy(plan["cap_jpy"], RATE, ITEM))) <= 1)
    check("plan 在上限出價時 ROI 不低於目標", plan["roi_at_cap"] >= 80,
          f"roi={plan['roi_at_cap']}")

    print("①b 封閉解反解 vs 數值二分搜尋(獨立驗算,不共用代數推導)")
    for target in (5_000, 9_000, 20_000):
        lo, hi = 0.0, 500_000.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if costs.landed_from_jpy(mid, RATE, ITEM) < target:
                lo = mid
            else:
                hi = mid
        closed = costs.jpy_for_landed(target, RATE, ITEM)
        check(f"封閉解 ≈ 二分搜尋 @NT${target:,}", abs(closed - lo) < 1.0,
              f"封閉 {closed:.2f} vs 二分 {lo:.2f}")

    print("② 每項費用都 load-bearing(突變:拿掉就必須變便宜)")
    base = costs.landed_from_jpy(15_000, RATE, ITEM)
    no_inspect = costs.landed_from_jpy(15_000, RATE, {**ITEM, "inspect": False})
    check("關掉檢品 → 成本下降", no_inspect < base - 50, f"{no_inspect} vs {base}")
    no_fee = costs.landed_from_jpy(15_000, RATE, {**ITEM, "buyee_fee_jpy": 0, "inspect": False})
    check("再拿掉代標手續費 → 又更低", no_fee < no_inspect - 50, f"{no_fee} vs {no_inspect}")
    saved = costs.FX_PREMIUM
    try:
        costs.FX_PREMIUM = 0.0
        no_fx = costs.landed_from_jpy(15_000, RATE, {**ITEM, "buyee_fee_jpy": 0, "inspect": False})
        check("再拿掉換匯溢價 → 退化成舊模型", abs(no_fx - legacy_landed(15_000, RATE, ITEM)) < 0.5,
              f"{no_fx} vs {legacy_landed(15_000, RATE, ITEM)}")
    finally:
        costs.FX_PREMIUM = saved

    print("③ 新模型只會更保守,絕不更敢出價")
    for jpy in (5_000, 15_000, 40_000):
        check(f"落地成本 ≥ 舊模型 ¥{jpy:,}",
              costs.landed_from_jpy(jpy, RATE, ITEM) > legacy_landed(jpy, RATE, ITEM))
    legacy_cap = int((15_000 / 1.8 - ITEM["jp_ship"]
                      - (1 + 0.05 + 1.05 * 0.05) * ITEM["intl_ship"])
                     / (1 + 0.05 + 1.05 * 0.05) / RATE)
    check("同樣目標 ROI 下,新出價上限比舊的低",
          plan["cap_jpy"] < legacy_cap, f"新 {plan['cap_jpy']} vs 舊 {legacy_cap}")

    print("④ 邊界")
    check("目標落地成本太低 → 回 0 不出價", bidcap.cap_for_target_landed(500, RATE, ITEM) == 0)
    check("匯率 0 → 回 0 不出價", bidcap.cap_for_target_landed(10_000, 0, ITEM) == 0)
    check("售價 0 → 回 0", bidcap.cap_by_roi(0, 80, RATE, ITEM) == 0)
    bd = costs.breakdown(15_000, RATE, ITEM)
    check("breakdown 各項加總 = landed",
          abs(bd["goods"] + bd["buyee_fees"] + bd["jp_ship"] + bd["intl_ship"]
              + bd["duty"] + bd["vat"] - bd["landed"]) <= 2)
    check("breakdown 標明模型版本", bd["cost_model"] == costs.COST_MODEL)

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗:{FAILED}")
        return 1
    print("✅ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
