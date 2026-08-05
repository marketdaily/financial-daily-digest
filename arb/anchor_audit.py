"""台灣售價錨校正:對每個標的試多組關鍵字,找「樣本夠 + 不混雜」的那一組。

為什麼需要這支(2026-08-05 第五次踩「錨」的坑):
    錨可靠度原本只看 spread=max/p25,但**樣本只有 1 筆時 max 必然等於 p25**,
    spread=1.0 反而被判成「價格極度集中、錨完美」。實例:台灣 'speeder nx green'
    僅 1 筆 10,000 被標綠燈;換 'fujikura speeder nx' 有 33 筆,p25 只有 6,843,
    錨高估 46%,連帶把 ROI 從 77% 誇大成 159%。

取捨:關鍵字太窄→樣本不足;太寬→混入別的型號使 spread 爆掉。
合格條件同時要求 樣本>=MIN_SAMPLES 且 spread<=MAX_SPREAD,兩者都過才採用。
兩者都過不了 → 誠實標記「台灣無可靠錨」,該標的不進推薦。
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import time  # noqa: E402

from arb import sources  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_SAMPLES = 5
MAX_SPREAD = 4.0
THROTTLE_S = 4.0         # 每次查詢後停頓,避免觸發 BigGo 反爬(實測連查 40 次會被擋)

# 每個標的的關鍵字候選,由窄到寬。窄的優先(混雜少),不足量才往寬的退。
CANDIDATES = {
    "shaft_tour_ad_di6": ["tour ad di-6", "tour ad di", "graphite design tour ad", "tour ad 桿身"],
    "shaft_tour_ad_vr6": ["tour ad vr-6", "tour ad vr", "graphite design tour ad", "tour ad 桿身"],
    "shaft_ventus_blue_6s": ["ventus blue 6s", "ventus blue", "fujikura ventus", "ventus 桿身"],
    "shaft_ventus_black_6s": ["ventus black 6s", "ventus black", "fujikura ventus", "ventus 桿身"],
    "shaft_diamana_tb60": ["diamana tb60", "diamana tb", "三菱 diamana", "diamana 桿身"],
    "shaft_speeder_nx_green": ["speeder nx green", "fujikura speeder nx", "speeder nx", "speeder 桿身"],
    "putter_sc_newport2": ["scotty cameron newport 2", "scotty cameron newport", "卡麥隆 推桿"],
    "putter_sc_super_select": ["scotty cameron super select", "scotty cameron select", "卡麥隆 推桿"],
    "putter_sc_special_select": ["scotty cameron special select", "scotty cameron select", "卡麥隆 推桿"],
    "putter_sc_phantom": ["scotty cameron phantom", "cameron phantom", "卡麥隆 推桿"],
    "reel_shimano_twinpower_c3000xg": ["twin power c3000xg", "shimano twin power", "twin power 捲線器"],
    "reel_daiwa_certate_lt3000": ["daiwa certate lt3000", "daiwa certate", "certate 捲線器"],
}

FLOORS = {"shaft": 3000, "putter": 6000, "reel": 5000}


def floor_for(item_id):
    for k, v in FLOORS.items():
        if item_id.startswith(k):
            return v
    return 0


def audit_one(page, item_id, keywords, floor):
    """逐一試關鍵字,回傳每組結果與最終採用者。"""
    tried = []
    for kw in keywords:
        r = sources.tw_listings_resilient(page, kw, price_floor=floor)
        if "error" in r:
            # 訊源壞掉(多為反爬限流)絕不能當成「沒刊登」——直接中止整輪,
            # 否則後續標的會全部誤報零刊登、再被解讀成「空白市場=機會」
            return {"item": item_id, "chosen": None, "tried": tried,
                    "aborted": r["error"]}
        time.sleep(THROTTLE_S)      # 節流,降低觸發反爬
        if not r.get("count"):
            tried.append({"kw": kw, "count": 0, "note": r.get("note") or r.get("error")})
            continue
        spread = round(r["max"] / max(r["p25"], 1), 1)
        row = {"kw": kw, "count": r["count"], "p25": r["p25"],
               "median": int(r["median"]), "max": r["max"], "spread": spread,
               "src": r.get("src", "biggo"),
               "ok": r["count"] >= MIN_SAMPLES and spread <= MAX_SPREAD}
        tried.append(row)
        if row["ok"]:
            return {"item": item_id, "chosen": row, "tried": tried}
    return {"item": item_id, "chosen": None, "tried": tried}


def main():
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(user_agent=sources.UA)
        for item_id, kws in CANDIDATES.items():
            res = audit_one(page, item_id, kws, floor_for(item_id))
            out.append(res)
            if res.get("aborted"):
                print(f"🔴 訊源異常中止:{res['aborted']} — 已完成 {len(out)-1} 個,"
                      f"其餘未查(不當成零刊登)")
                break
            c = res["chosen"]
            if c:
                print(f"✅ {item_id:<30} kw='{c['kw']}' n={c['count']} "
                      f"p25={c['p25']:,} 中位={c['median']:,} spread={c['spread']}x "
                      f"[{c.get('src')}]")
            else:
                best = max((t for t in res["tried"] if t.get("count")),
                           key=lambda x: x["count"], default=None)
                detail = (f"最多樣本 n={best['count']} spread={best.get('spread')}x"
                          if best else "全部零刊登")
                print(f"❌ {item_id:<32} 無可靠錨 — {detail}")
        b.close()

    path = os.path.join(HERE, "anchor_audit.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"min_samples": MIN_SAMPLES, "max_spread": MAX_SPREAD,
                   "results": out}, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in out if r["chosen"])
    print(f"\n{ok}/{len(out)} 個標的有可靠錨 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
