"""進貨雷達:每日比對日本落札行情 vs 台灣實際刊登行情,淨利達標即推播。

用法:
    ./.venv/bin/python -m arb.radar            # 全跑 + 達標推播
    ./.venv/bin/python -m arb.radar --dry      # 不推播
    ./.venv/bin/python -m arb.radar --only shaft_tour_ad_di6

成本模型(日本→台灣):
    落地成本 = 落札價×匯率 + 日本國內運費 + 國際運費 + 關稅 + 營業稅
    營業稅基數 = (CIF + 關稅),CIF 含國際運費
淨利兩軌並列(通路決定生死,見 sales_playbook):
    蝦皮 = 售價×(1 - 手續費率) - 落地成本
    面交 = 售價 - 落地成本
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import requests  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from arb import sources  # noqa: E402

ENV = {**dotenv_values(os.path.join(REPO, ".env")), **os.environ}
HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger.jsonl")

# 蝦皮 2026/1/1 起:成交 5.5% + 金流 2.5% + 免運方案二(高單價品固定 NT$60)
SHOPEE_PCT = 0.08
SHOPEE_FLAT = 60


def push(msg):
    tok = (ENV.get("MARKETDAILY_ALERT_TOKEN") or "").strip()
    if not tok:
        return False, "no_token"
    try:
        r = requests.post(
            "https://marketdaily-alert-worker.delvin-12345678.workers.dev"
            "/internal/admin-line-push",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json",
                     "User-Agent": "md-arb-radar"},
            json={"message": msg}, timeout=30)
        return r.status_code == 200, f"http_{r.status_code}"
    except Exception as e:
        return False, f"exc:{e}"


def landed_cost(jpy, rate, item):
    """日圓落札價 → 台灣落地成本(NTD)。"""
    goods = jpy * rate
    cif = goods + item["intl_ship"]
    duty = cif * item.get("duty", 0.05)
    vat = (cif + duty) * 0.05
    return round(goods + item["jp_ship"] + item["intl_ship"] + duty + vat)


def evaluate(item, page, rate):
    jp = sources.jp_sold(item["jp_kw"])
    tw = sources.tw_listings(page, item["tw_kw"], price_floor=item.get("floor", 0))
    row = {"id": item["id"], "name": item["name"], "line": item["line"],
           "jp": jp, "tw": tw, "rate": rate}

    if "error" in jp:
        row["status"] = "jp_source_error"
        return row
    if "error" in tw:
        row["status"] = "tw_source_error"
        return row

    cost = landed_cost(jp["avg_jpy"], rate, item)
    row["landed_cost"] = cost

    # 流動性:日拍件數少=補不到穩定貨源,只能做一次性;台灣刊登少=可能賣不掉。
    # 毛利再高,買得到但出不掉一樣是死錢。
    row["jp_liquidity"] = jp["count"]
    row["thin_supply"] = jp["count"] < 10

    if not tw.get("count"):
        # 台灣零刊登 = 市場空白。不是壞掉,是機會(但無售價錨,需人工定價)
        row["status"] = "tw_market_blank"
        row["note"] = "台灣無刊登可比,無售價錨——空白市場需人工定價"
        return row

    # 售價錨:median=樂觀、p25=保守。用 p25 是因為刊登裡混有「代購掛牌」,
    # 實查證實代購掛牌比現貨行情高約 16%(NEMO Hornet 15,000 代購 vs 12,900 現貨),
    # 拿它當錨會第二次高估毛利。保守錨過關才算真機會。
    row["anchor"] = tw["median"]
    row["anchor_conservative"] = tw["p25"]
    thresh = item.get("min_margin", 1000)

    for tag, anchor in (("", tw["median"]), ("_cons", tw["p25"])):
        row[f"margin_shopee{tag}"] = round(anchor * (1 - SHOPEE_PCT) - SHOPEE_FLAT - cost)
        row[f"margin_facetoface{tag}"] = round(anchor - cost)

    # 型號混雜偵測:同關鍵字下價格帶過寬 = 中位數混了不同版本/成色,錨不可信
    spread = tw["max"] / max(tw["p25"], 1)
    row["spread_ratio"] = round(spread, 1)
    row["anchor_reliable"] = spread <= 4

    passes = [ch for ch in ("shopee", "facetoface")
              if row[f"margin_{ch}_cons"] >= thresh]
    row["passing_channels"] = passes
    if not passes:
        row["status"] = "below_threshold"
    elif row["thin_supply"]:
        row["status"] = "HIT_thin_supply"
    elif not row["anchor_reliable"]:
        row["status"] = "HIT_anchor_unreliable"
    elif len(passes) == 1:
        row["status"] = "HIT_single_channel"
    else:
        row["status"] = "HIT"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="不推播")
    ap.add_argument("--only", help="只跑指定 id")
    args = ap.parse_args()

    with open(os.path.join(HERE, "watchlist.json"), encoding="utf-8") as f:
        items = json.load(f)["items"]
    if args.only:
        items = [i for i in items if i["id"] == args.only]
        if not items:
            print(f"找不到 id={args.only}")
            return 1

    fx = sources.jpy_twd_rate()
    rate = fx["rate"]
    if fx["source"].endswith("STALE"):
        print(f"⚠️ 匯率抓取失敗,用 fallback {rate}(數字僅供參考)")

    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(user_agent=sources.UA)
        for it in items:
            rows.append(evaluate(it, page, rate))
        b.close()

    stamp = datetime.now(timezone.utc).isoformat()
    with open(LEDGER, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"ts": stamp, **r}, ensure_ascii=False) + "\n")

    hits, errors, blanks = [], [], []
    for r in rows:
        st = r["status"]
        if st.startswith("HIT"):
            hits.append(r)
        elif st.endswith("_source_error"):
            errors.append(r)
        elif st == "tw_market_blank":
            blanks.append(r)
        mark = {"HIT": "🟢", "HIT_single_channel": "🟡",
                "HIT_anchor_unreliable": "🟠", "HIT_thin_supply": "🟤",
                "below_threshold": "·",
                "tw_market_blank": "⬜", "jp_source_error": "🔴",
                "tw_source_error": "🔴"}.get(st, "?")
        line = f"{mark} {r['name']} [{st}]"
        if "jp" in r and "count" in r.get("jp", {}):
            line += f" 日拍{r['jp']['count']}筆/¥{r['jp']['avg_jpy']:,}"
        if "landed_cost" in r:
            line += f" 落地={r['landed_cost']}"
        if "anchor" in r:
            line += (f" 台灣中位={int(r['anchor'])}/保守={int(r['anchor_conservative'])}"
                     f" 保守淨利:蝦皮={r['margin_shopee_cons']}"
                     f" 面交={r['margin_facetoface_cons']}"
                     f" spread={r['spread_ratio']}x")
        print(line)

    if args.dry:
        print("\n--dry:不推播")
        return 0

    msgs = []
    if hits:
        body = "\n".join(
            f"・{r['name']}({'/'.join(r['passing_channels'])}"
            + (",錨不可靠" if not r["anchor_reliable"] else "") + ")"
            f":日拍均價¥{r['jp']['avg_jpy']:,}({r['jp']['count']}筆)"
            f" 落地NT${r['landed_cost']:,} 台灣保守錨NT${int(r['anchor_conservative']):,}"
            f" → 保守淨利 面交NT${r['margin_facetoface_cons']:,}"
            f"/蝦皮NT${r['margin_shopee_cons']:,}"
            for r in hits)
        msgs.append(f"🟢 進貨雷達 {len(hits)} 個標的達標(保守錨計)\n{body}")
    if errors:
        # 訊源壞掉一定要看得見——不然「沒機會」和「雷達死了」長得一樣
        msgs.append("🔴 進貨雷達訊源異常:" + "、".join(
            f"{r['name']}({r['status']})" for r in errors))
    for m in msgs:
        ok, why = push(m)
        print(f"推播 {'成功' if ok else '失敗:' + why}")
    if not msgs:
        print("\n無達標標的、訊源健康——不推播(不製造噪音)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
