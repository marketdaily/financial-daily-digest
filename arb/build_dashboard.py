"""產生後台資料:行情層(radar) + 現貨層(scout) + 樂高線,輸出 arb/dashboard_data.json。

用法: ./.venv/bin/python -m arb.build_dashboard
"""
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from arb import scout, sources  # noqa: E402
from arb.radar import SHOPEE_FLAT, SHOPEE_PCT, landed_cost  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# 已用 BigGo 實查的台灣售價錨(保守錨 p25)。⚠️ 一律用實際刊登行情,不用代理定價。
GOLF = [
    {"id": "sc_special_select", "name": "Scotty Cameron Special Select 推桿",
     "jp_kw": "スコッティキャメロン スペシャルセレクト", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 15000,
     "tw_note": "台灣刊登價格帶集中(spread 1.0x),錨可靠", "grade": "A"},
    {"id": "sc_newport2", "name": "Scotty Cameron Newport 2 推桿",
     "jp_kw": "スコッティキャメロン ニューポート2", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 16800,
     "tw_note": "⚠️ spread 5.3x:各年份版本混雜,新手易買錯,建議有手感再進", "grade": "B"},
    {"id": "speeder_nx_green", "name": "Speeder NX Green 桿身",
     "jp_kw": "スピーダー NX グリーン", "jp_floor": 8000,
     "jp_ship": 250, "intl_ship": 400, "duty": 0.05, "sell": 10000,
     "tw_note": "唯一台灣有掛牌的桿身,錨可靠(spread 1.0x)", "grade": "A"},
    {"id": "sc_super_select", "name": "Scotty Cameron Super Select 推桿",
     "jp_kw": "スコッティキャメロン スーパーセレクト", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 15120,
     "tw_note": "日拍 30 日僅 10 筆,補貨較慢", "grade": "B"},
    {"id": "tour_ad_di6", "name": "Tour AD DI-6 桿身(市場測試彈)",
     "jp_kw": "ツアーAD DI-6", "jp_floor": 8000,
     "jp_ship": 250, "intl_ship": 400, "duty": 0.05, "sell": None,
     "tw_note": "台灣零刊登=空白市場。買 1 支測「是沒人賣還是沒人要」", "grade": "TEST"},
]

# 樂高線:美國清倉→台灣。⚠️ 需美國友人代收;CPU 線已判死不列入。
LEGO = [
    {"id": "lego_21226", "name": "LEGO 21226 Art Project(扁平盒)",
     "pieces": 4138, "weight_kg": 1.85, "box": "40.2×37.6×5.2cm",
     "msrp_usd": 119.99, "target_usd": 35.99, "online_usd": 71.99,
     "tw_sell": 3496,
     "note": "⭐扁平盒=樂高裡少數按實重計費的異類,運費最划算",
     "links": [
         ("Walmart 樂高清倉", "https://www.walmart.com/browse/toys/lego/4171_4191_1004230"),
         ("Amazon 搜尋", "https://www.amazon.com/s?k=lego+21226"),
         ("BrickLink 規格", "https://www.bricklink.com/v2/catalog/catalogitem.page?S=21226-1"),
     ]},
    {"id": "lego_10497", "name": "LEGO 10497 Galaxy Explorer(中型盒)",
     "pieces": 1219, "weight_kg": 1.76, "box": "53.4×27.7×8.9cm",
     "msrp_usd": 99.99, "target_usd": 36.00, "online_usd": 60.00,
     "tw_sell": 3300,
     "note": "材積重 2.63kg > 實重,按材積計費;甜蜜點尺寸",
     "links": [
         ("Walmart 樂高清倉", "https://www.walmart.com/browse/toys/lego/4171_4191_1004230"),
         ("Amazon 搜尋", "https://www.amazon.com/s?k=lego+10497"),
         ("BrickLink 規格", "https://www.bricklink.com/v2/catalog/catalogitem.page?S=10497-1"),
     ]},
]

USD_TWD = 32.4
AIR_PER_KG = 375      # 空運估值,待實測校準
SEA_PER_KG = 125      # 海運估值(Buyandship NT$170/磅 ≈ NT$375/kg 為空運價)


def lego_rows():
    rows = []
    for L in LEGO:
        vol_kg = None
        try:
            d = [float(x) for x in L["box"].replace("cm", "").split("×")]
            vol_kg = round(d[0] * d[1] * d[2] / 5000, 2)
        except Exception:
            pass
        bill_kg = max(L["weight_kg"], vol_kg or 0)
        out = {**L, "vol_kg": vol_kg, "bill_kg": bill_kg, "scenarios": []}
        for label, usd in (("店內深折 -70%", L["target_usd"]),
                           ("線上清倉 -40%", L["online_usd"])):
            goods = usd * USD_TWD
            for mode, per_kg in (("空運", AIR_PER_KG), ("海運", SEA_PER_KG)):
                ship = bill_kg * per_kg
                # 樂高 HS9503 玩具類台灣關稅多為 0%,僅營業稅 5%
                vat = (goods + ship) * 0.05
                landed = round(goods + ship + vat)
                f2f = L["tw_sell"] - landed
                out["scenarios"].append({
                    "label": f"{label} × {mode}", "usd": usd,
                    "ship": round(ship), "landed": landed,
                    "margin": f2f, "roi": round(f2f / landed * 100) if landed else 0,
                })
        rows.append(out)
    return rows


def main():
    fx = sources.jpy_twd_rate()
    rate = fx["rate"]
    from playwright.sync_api import sync_playwright

    golf = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(user_agent=sources.UA)
        for g in GOLF:
            sell = g["sell"] or 0
            live = scout.scout(page, g, rate, sell, limit=5) if sell else \
                scout.scout(page, g, rate, 0, limit=5)
            jp = sources.jp_sold(g["jp_kw"], jp_floor=g["jp_floor"])
            row = {**g, "live": live}
            if "error" not in jp:
                cost = landed_cost(jp.get("cost_jpy", jp["avg_jpy"]), rate, g)
                row["market"] = {
                    "count30d": jp["count"],
                    "median_jpy": jp.get("cost_jpy"),
                    "landed": cost,
                    "margin_f2f": (sell - cost) if sell else None,
                    "margin_shopee": round(sell * (1 - SHOPEE_PCT) - SHOPEE_FLAT - cost)
                    if sell else None,
                    "roi": round((sell - cost) / cost * 100) if sell and cost else None,
                }
            golf.append(row)
            print(f"  {g['name']}: 現貨 {live.get('count', 0)} 件")
        b.close()

    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "rate_jpy_twd": rate, "rate_source": fx["source"], "rate_usd_twd": USD_TWD,
        "golf": golf, "lego": lego_rows(),
        "shopee_pct": SHOPEE_PCT, "shopee_flat": SHOPEE_FLAT,
    }
    out = os.path.join(HERE, "dashboard_data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
