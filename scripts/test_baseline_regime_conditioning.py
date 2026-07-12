#!/usr/bin/env python3
"""迴歸測試:零技能基線的 regime 條件化(2026-07-13 P1.5 follow-up)。

守住兩件事:
 1. build_track_record._zero_skill_baseline 產出 by_regime 子表,逐 regime 逐 verdict_class
    的無腦全標命中率正確(對照手算)。
 2. kpi_pull 端的 _subset_null 混合公式:子集 null = 逐筆 (regime,verdict_class) 基線的平均。

必須用 repo .venv 跑(build_track_record 頂層 import bs4):
    .venv/bin/python3 scripts/test_baseline_regime_conditioning.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import build_track_record as b  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got} want {want}")


# chg=±0.5 遠超所有 5d 緩衝(hold 0.03/wait 0.02),四類 label 皆確定:
#   +0.5 → buy=win hold=win sell=loss wait=loss
#   -0.5 → buy=loss hold=loss sell=win wait=win
def rec(t, d, rg, chg):
    return {"ticker": t, "date": d, "regime": rg, "chg": chg,
            "label": "win", "verdict_class": "buy"}  # label 只需 win/loss 才計入


# up regime: 3×+0.5, 1×-0.5 (n=4) → buy 75 hold 75 sell 25 wait 25
# down regime: 1×+0.5, 3×-0.5 (n=4) → buy 25 hold 25 sell 75 wait 75
recs = [
    rec("AAA", "2026-06-20", "up", 0.5),
    rec("BBB", "2026-06-21", "up", 0.5),
    rec("CCC", "2026-06-22", "up", 0.5),
    rec("DDD", "2026-06-23", "up", -0.5),
    rec("EEE", "2026-06-24", "down", 0.5),
    rec("FFF", "2026-06-25", "down", -0.5),
    rec("GGG", "2026-06-26", "down", -0.5),
    rec("HHH", "2026-06-27", "down", -0.5),
]

bl = b._zero_skill_baseline(recs)
byr = bl.get("by_regime") or {}
check("by_regime keys", sorted(byr), ["down", "up"])
check("up.n_pairs", byr["up"]["n_pairs"], 4)
check("up.buy", byr["up"]["buy"], 75.0)
check("up.hold", byr["up"]["hold"], 75.0)
check("up.sell", byr["up"]["sell"], 25.0)
check("up.wait", byr["up"]["wait"], 25.0)
check("down.buy", byr["down"]["buy"], 25.0)
check("down.sell", byr["down"]["sell"], 75.0)

# 既有(全 regime)鍵不受影響:buy win=4/8=50, sell win=4/8=50
check("overall.buy", bl["buy"], 50.0)
check("overall.sell", bl["sell"], 50.0)

# regime 缺失時 by_regime 只收有 regime 的 pair(None 不建組)
recs_none = recs + [{"ticker": "ZZZ", "date": "2026-06-28", "regime": None,
                     "chg": 0.5, "label": "win", "verdict_class": "buy"}]
bl2 = b._zero_skill_baseline(recs_none)
check("none excluded from by_regime up.n", bl2["by_regime"]["up"]["n_pairs"], 4)
check("none counted in overall n_pairs", bl2["n_pairs"], 9)


# --- _subset_null 混合公式(對齊 kpi_pull.py block 4b)---
def subset_null(recs_sub, bl_era, bl_rg):
    vals = []
    for r in recs_sub:
        cls, rg = r.get("verdict_class"), r.get("regime")
        v = (bl_rg.get(rg) or {}).get(cls) if (rg and cls) else None
        if v is None and cls:
            v = bl_era.get(cls)
        if v is not None:
            vals.append(v)
    return (sum(vals) / len(vals) / 100.0) if vals else 0.5


bl_era = {"buy": 43.4, "hold": 57.3, "sell": 56.6, "wait": 66.7}
bl_rg = {"up": {"buy": 36.1, "hold": 50.6, "sell": 63.9, "wait": 75.3},
         "down": {"buy": 64.6, "hold": 75.7, "sell": 35.4, "wait": 44.4}}

# 純 up-regime buy 子集(=chase_high)→ null = 36.1
sub_chase = [{"verdict_class": "buy", "regime": "up"}] * 3
check("chase_high null == up.buy", round(subset_null(sub_chase, bl_era, bl_rg) * 100, 1), 36.1)

# 混合子集:2 筆 up-buy(36.1) + 1 筆 down-buy(64.6) → (36.1+36.1+64.6)/3 = 45.6
sub_mix = [{"verdict_class": "buy", "regime": "up"},
           {"verdict_class": "buy", "regime": "up"},
           {"verdict_class": "buy", "regime": "down"}]
check("mixed regime buy null", round(subset_null(sub_mix, bl_era, bl_rg) * 100, 1), 45.6)

# C 類混合 verdict_class:2 筆 up-wait(75.3) + 1 筆 down-sell(35.4) → (75.3+75.3+35.4)/3=62.0
sub_c = [{"verdict_class": "wait", "regime": "up"},
         {"verdict_class": "wait", "regime": "up"},
         {"verdict_class": "sell", "regime": "down"}]
check("C mixed class×regime null", round(subset_null(sub_c, bl_era, bl_rg) * 100, 1), 62.0)

# regime 缺失 → 退回全 regime 該類基線(hold=57.3)
sub_norg = [{"verdict_class": "hold", "regime": None}]
check("missing regime falls back to class null", round(subset_null(sub_norg, bl_era, bl_rg) * 100, 1), 57.3)

# 全缺 → 0.5 保底
check("empty falls back to 0.5", subset_null([], bl_era, bl_rg), 0.5)

if FAILS:
    print("FAIL:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL PASS (regime-conditioned zero-skill baseline + subset_null blending)")
