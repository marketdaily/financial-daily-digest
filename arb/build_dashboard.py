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
    {"id": "putter_sc_special_select", "name": "Scotty Cameron Special Select 推桿",
     "jp_kw": "スコッティキャメロン スペシャルセレクト", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 15000,
     "tw_note": "台灣刊登價格帶集中(spread 1.0x),錨可靠", "grade": "A"},
    {"id": "putter_sc_newport2", "name": "Scotty Cameron Newport 2 推桿",
     "jp_kw": "スコッティキャメロン ニューポート2", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 16800,
     "tw_note": "⚠️ spread 5.3x:各年份版本混雜,新手易買錯,建議有手感再進", "grade": "B"},
    {"id": "shaft_speeder_nx_green", "name": "Speeder NX Green 桿身",
     "jp_kw": "スピーダー NX グリーン", "jp_floor": 8000,
     "jp_ship": 250, "intl_ship": 400, "duty": 0.05, "sell": 10000,
     "tw_note": "唯一台灣有掛牌的桿身,錨可靠(spread 1.0x)", "grade": "A"},
    {"id": "putter_sc_super_select", "name": "Scotty Cameron Super Select 推桿",
     "jp_kw": "スコッティキャメロン スーパーセレクト", "jp_floor": 15000,
     "jp_ship": 400, "intl_ship": 900, "duty": 0.05, "sell": 15120,
     "tw_note": "日拍 30 日僅 10 筆,補貨較慢", "grade": "B"},
    {"id": "shaft_tour_ad_di6", "name": "Tour AD DI-6 桿身(市場測試彈)",
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


def load_audited_anchors():
    """讀 anchor_audit.json:只採用「樣本足夠且不混雜」的錨,其餘視為無錨。"""
    path = os.path.join(HERE, "anchor_audit.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = {}
    for r in d.get("results", []):
        c = r.get("chosen")
        if c:
            out[r["item"]] = {"kw": c["kw"], "anchor": c["p25"],
                              "median": c["median"], "n": c["count"],
                              "spread": c["spread"]}
    return out


def main():
    fx = sources.jpy_twd_rate()
    rate = fx["rate"]
    audited = load_audited_anchors()
    from playwright.sync_api import sync_playwright

    golf = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        # ⚠️ 必須指定 locale:verify_listing 用「好評比例/可否下標」等中文字樣做判準,
        # 沒設 locale 時 Buyee 會回別的語言 → 評價抓不到 → fail-closed 把全部貨擋掉,
        # 看起來像「今天沒好貨」,其實是抓取壞了(2026-08-05 實際發生,15/15 全誤擋)。
        ctx = b.new_context(user_agent=sources.UA, locale="zh-TW")
        page = ctx.new_page()
        for g in GOLF:
            a = audited.get(g["id"])
            if a:
                # 用校正過的錨(足量樣本的 p25)取代先前手填值
                g = {**g, "sell": a["anchor"], "tw_kw": a["kw"],
                     "tw_note": f"錨已校正:{a['kw']} n={a['n']} p25={a['anchor']:,} "
                                f"spread={a['spread']}x"}
            elif g["sell"]:
                # 沒通過校正 = 台灣無可靠行情,不可用舊錨算毛利
                g = {**g, "sell": None,
                     "tw_note": "⚠️ 台灣無可靠行情(樣本不足或型號混雜)——不計毛利"}
            sell = g["sell"] or 0
            live = scout.scout(page, g, rate, sell, limit=6)
            # 四道閘門的第 3、4 道:賣家評價 + 可否下標(只在商品頁看得到)
            verified = []
            for it in live.get("items", [])[:3]:
                v = scout.verify_listing(page, it["buyee"])
                verified.append({**it, **v})
            live["items"] = verified + live.get("items", [])[3:]
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
            row["audited"] = bool(a)
            golf.append(row)
            checked = [x for x in live.get("items", []) if "biddable" in x]
            rating_ok = [x for x in checked if x.get("seller_rating") is not None]
            if checked and not rating_ok:
                # 全部都抓不到評價 = 抓取管線壞了,不是「賣家都不合格」
                row["verify_broken"] = True
                print(f"  🔴 {g['name']}: 賣家評價 {len(checked)} 支全部抓取失敗"
                      f" —— 這是抓取故障不是沒好貨")
            else:
                buyable = sum(1 for x in live.get("items", [])
                              if x.get("ok_to_buy") and x.get("margin_f2f"))
                print(f"  {g['name']}: 現貨 {live.get('count', 0)} 件,"
                      f"四關全過 {buyable} 件"
                      + ("" if a else " (⚠️ 無可靠錨)"))
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
