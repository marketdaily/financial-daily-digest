"""進貨雷達判定邏輯自測。零網路,純算術與分支。

鎖住的是三個踩過的坑:
1. 售價錨不能用代理定價(高估三倍)
2. 保守錨(p25)才算數——代購掛牌比現貨貴約 16%,用 median 會二次高估
3. 訊源壞掉必須與「沒機會」區分開
"""
import sys

from arb.radar import SHOPEE_FLAT, SHOPEE_PCT, evaluate, landed_cost

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")
        FAILED.append(name)


class FakePage:
    """假 playwright page,不觸網。"""


def stub_sources(jp, tw):
    import arb.radar as R
    R.sources.jp_sold = lambda kw, **k: jp
    R.sources.tw_listings = lambda page, kw, **k: tw


ITEM = {"id": "t", "name": "T", "line": "l", "jp_kw": "x", "tw_kw": "y",
        "duty": 0.05, "jp_ship": 300, "intl_ship": 500, "min_margin": 1000}


def main():
    print("成本模型")
    # 10000 JPY @0.21 = 2100 貨值; CIF=2100+500=2600; 關稅130; 營業稅=(2600+130)*.05=136.5
    # 總 = 2100+300+500+130+136.5 = 3166.5 -> 3166 or 3167
    c = landed_cost(10_000, 0.21, ITEM)
    check("落地成本含關稅與營業稅複合", 3166 <= c <= 3167, f"得 {c}")
    check("營業稅基數含關稅(不是只課貨值)",
          landed_cost(10_000, 0.21, {**ITEM, "duty": 0.0}) < c)

    print("保守錨:代購掛牌不得抬高判定")
    # median 高(混代購掛牌) 但 p25 低(現貨) -> 應以 p25 判定
    # 落地成本約 7797;median 15000 過關、p25 8300 不過關 → 必須以 p25 為準
    stub_sources({"count": 50, "avg_jpy": 30_000},
                 {"count": 20, "min": 8000, "p25": 8300, "median": 15000,
                  "max": 16000})
    r = evaluate(ITEM, FakePage(), 0.21)
    check("保守淨利嚴格低於樂觀淨利",
          r["margin_facetoface_cons"] < r["margin_facetoface"])
    check("樂觀錨本來會過關(確認這題有鑑別力)",
          r["margin_facetoface"] >= ITEM["min_margin"])
    check("判定用保守錨(高 median 不足以過關)",
          r["status"] == "below_threshold",
          f"得 {r['status']} cons={r['margin_facetoface_cons']}")

    print("型號混雜偵測")
    stub_sources({"count": 50, "avg_jpy": 20_000},
                 {"count": 30, "min": 8000, "p25": 12000, "median": 17000,
                  "max": 90000})   # spread 7.5x
    r = evaluate(ITEM, FakePage(), 0.21)
    check("價格帶過寬標記錨不可靠", r["status"] == "HIT_anchor_unreliable",
          f"得 {r['status']}")
    check("spread_ratio 有算出來", r["spread_ratio"] > 4)

    print("單通路 vs 雙通路")
    # 讓面交過、蝦皮不過
    stub_sources({"count": 10, "avg_jpy": 30_000},
                 {"count": 10, "min": 8000, "p25": 8300, "median": 8600,
                  "max": 9000})
    r = evaluate({**ITEM, "min_margin": 100}, FakePage(), 0.21)
    check("僅單一通路達標時標記 single_channel",
          r["status"] == "HIT_single_channel", f"得 {r['status']}")
    check("蝦皮扣費算式正確",
          r["margin_shopee_cons"] ==
          round(8300 * (1 - SHOPEE_PCT) - SHOPEE_FLAT - r["landed_cost"]))
    check("蝦皮淨利必然低於面交", r["margin_shopee_cons"] < r["margin_facetoface_cons"])

    print("fail-loud:訊源壞掉不得偽裝成沒機會")
    stub_sources({"error": "http_503"},
                 {"count": 5, "min": 1, "p25": 2, "median": 3, "max": 4})
    r = evaluate(ITEM, FakePage(), 0.21)
    check("日本訊源錯誤獨立成狀態", r["status"] == "jp_source_error")
    check("訊源錯誤時不產出毛利數字", "margin_facetoface_cons" not in r)

    stub_sources({"count": 5, "avg_jpy": 10_000}, {"error": "render_failed"})
    r = evaluate(ITEM, FakePage(), 0.21)
    check("台灣訊源錯誤獨立成狀態", r["status"] == "tw_source_error")

    print("空白市場 != 沒機會")
    stub_sources({"count": 5, "avg_jpy": 10_000}, {"count": 0, "note": "no_listings"})
    r = evaluate(ITEM, FakePage(), 0.21)
    check("台灣零刊登標記為空白市場", r["status"] == "tw_market_blank")
    check("空白市場仍算出落地成本(供人工定價)", r.get("landed_cost", 0) > 0)

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗:{FAILED}")
        return 1
    print("✅ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
