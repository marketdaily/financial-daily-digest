"""現貨偵察:抓雅虎拍賣「正在拍」的實際商品,算出每件的落地成本與 ROI。

與 radar.py 的分工:
  radar = 行情層(近30日成交中位 vs 台灣刊登),回答「這個型號值不值得做」
  scout = 現貨層(現在拍場上有什麼),回答「現在這一支該不該買」

⭐ 雅拍商品 id 可直接組成 Buyee 下標連結:
   auctions.yahoo.co.jp/jp/auction/<id>  →  buyee.jp/item/yahoo/auction/<id>
   老闆不懂日文也不必自己搜,點按鈕即到下標頁。
"""
import re
import urllib.parse as up

from arb.radar import SHOPEE_FLAT, SHOPEE_PCT, landed_cost

AUC_ID = re.compile(r"auctions\.yahoo\.co\.jp/jp/auction/([A-Za-z0-9]+)")

# Scotty Cameron 各世代:同一個「ニューポート2」關鍵字會撈到所有世代,
# 但它們在台灣是完全不同價位帶(Studio Select 台灣幾乎零刊登、Special Select 中位 15,000)。
# 拿型號中位當現貨售價錨 = 錨用錯,毛利會虛胖(實測某支被算成 ROI 238%,實際無錨可算)。
GENERATIONS = {
    "studio": ("スタジオセレクト", "スタジオ セレクト", "STUDIO SELECT", "STUDIO STYLE",
               "スタジオスタイル", "スタジオステンレス"),
    "special": ("スペシャルセレクト", "スペシャル セレクト", "SPECIAL SELECT"),
    "super": ("スーパーセレクト", "スーパー セレクト", "SUPER SELECT"),
    "phantom": ("ファントム", "PHANTOM"),
    "futura": ("フューチュラ", "FUTURA"),
}


def detect_generation(title):
    """從標題判斷世代。回 None 表示無法判斷。"""
    up = title.upper()
    for gen, kws in GENERATIONS.items():
        if any(k.upper() in up for k in kws):
            return gen
    return None


def _cards(page):
    """回傳 [(title, price_jpy, auction_id)]。"""
    js = """
    () => {
      const out = [];
      document.querySelectorAll('a[href*="auctions.yahoo.co.jp/jp/auction/"]').forEach(a => {
        const box = a.closest('li') || a.closest('div');
        if (!box) return;
        const txt = (box.innerText || '').trim();
        // 標題 = 區塊內最長的一行,排除「送料無料 / New!! / ウォッチ」等徽章與純數字行
        const BADGE = /^(送料無料|New!!|新品|ウォッチ|入札|即決|残り|[0-9,円日時分秒 ]+)$/;
        const line = txt.split('\\n')
          .map(s => s.trim())
          .filter(s => s.length > 8 && !BADGE.test(s))
          .sort((x, y) => y.length - x.length)[0];
        const title = line || (a.innerText || '').trim();
        out.push({href: a.href, title: (title || '').slice(0, 90), block: txt.slice(0, 300)});
      });
      return out;
    }"""
    rows, seen = [], set()
    for r in page.evaluate(js):
        m = AUC_ID.search(r["href"])
        if not m or m.group(1) in seen:
            continue
        prices = [int(x.replace(",", ""))
                  for x in re.findall(r"([0-9,]{3,})\s*円", r["block"])]
        if not prices or not r["title"]:
            continue
        seen.add(m.group(1))
        rows.append((r["title"], min(prices), m.group(1)))
    return rows


def scout(page, item, rate, sell_price, limit=6, expect_gen=None):
    """回傳當前拍場上、落地後仍有肉的標的(已排序,最賺的在前)。"""
    url = ("https://auctions.yahoo.co.jp/search/search?p="
           + up.quote(item["jp_kw"]) + "&n=50")
    try:
        page.goto(url, timeout=60_000)
        page.wait_for_timeout(3500)
    except Exception as e:
        return {"error": f"render_failed:{e}"}

    floor = item.get("jp_floor", 0)
    expect_gen = expect_gen or item.get("gen")
    out = []
    for title, jpy, aid in _cards(page):
        if jpy < floor:          # 配件雜訊(頭套/握把/配重)
            continue
        cost = landed_cost(jpy, rate, item)
        gen = detect_generation(title)
        # 世代不符 = 這支的台灣售價錨不適用(不同世代價位帶差很大),
        # 不能拿型號中位去算它的毛利,標記後由上層決定要不要信。
        gen_ok = (expect_gen is None) or (gen == expect_gen)
        row = {
            "title": title,
            "jpy": jpy,
            "landed": cost,
            "gen": gen,
            "anchor_applies": gen_ok,
            "buyee": f"https://buyee.jp/item/yahoo/auction/{aid}",
            "yahoo": f"https://auctions.yahoo.co.jp/jp/auction/{aid}",
        }
        if gen_ok and sell_price:
            f2f = sell_price - cost
            row.update({
                "margin_f2f": f2f,
                "margin_shopee": round(sell_price * (1 - SHOPEE_PCT) - SHOPEE_FLAT - cost),
                "roi": round(f2f / cost * 100) if cost else 0,
            })
        else:
            # 錨不適用就不產出毛利數字——寧可沒有,也不要一個會誤導決策的數
            row.update({"margin_f2f": None, "margin_shopee": None, "roi": None,
                        "note": f"世代 {gen or '不明'} 與售價錨({expect_gen})不符,無法計算毛利"})
        out.append(row)
    # 有毛利數字的排前面(依毛利),錨不適用的沉底
    out.sort(key=lambda x: (x["margin_f2f"] is None, -(x["margin_f2f"] or 0)))
    return {"count": len(out), "items": out[:limit], "search_url": url,
            "buyee_search": "https://buyee.jp/item/search/query/" + up.quote(item["jp_kw"])}


BLOCKED_MARKS = ("現在此商品不能下標", "この商品は入札できません",
                 "cannot be bid", "入札できません")
RATE_RE = re.compile(r"(?:好評比例|好評価率|Positive)\s*([0-9.]+)\s*%")
GOOD_RE = re.compile(r"(?:良好|良い)\s*([0-9,]+)")
BAD_RE = re.compile(r"(?:惡劣|悪い)\s*([0-9,]+)")


def verify_listing(page, buyee_url, min_rating=99.0):
    """下單前必查:能不能下標 + 賣家評價。

    ⚠️ 這兩項在搜尋結果頁完全看不到,只有進商品頁才有;而「低評價賣家」的警告
    更是只在結帳頁才出現(2026-08-05 老闆的截圖救回來的——首單差點從
    Buyee 標記低評價的賣家買二手 Scotty Cameron,而真偽問題 Buyee 明文不負責)。
    另有「投標者評價限制」會讓好賣家的貨根本下不了標,搜尋頁同樣看不出來。
    """
    try:
        page.goto(buyee_url, timeout=55_000)
        page.wait_for_timeout(4200)
        txt = re.sub(r"[ \t]+", " ", page.inner_text("body"))
    except Exception as e:
        return {"error": f"verify_failed:{e}", "biddable": False}

    m = RATE_RE.search(txt)
    g, bd = GOOD_RE.search(txt), BAD_RE.search(txt)
    rating = float(m.group(1)) if m else None
    blocked = any(k in txt for k in BLOCKED_MARKS)
    return {
        "biddable": not blocked,
        "seller_rating": rating,
        "seller_good": int(g.group(1).replace(",", "")) if g else None,
        "seller_bad": int(bd.group(1).replace(",", "")) if bd else None,
        # 兩個條件都過才算可買:能下標 + 賣家評價達標
        "ok_to_buy": (not blocked) and rating is not None and rating >= min_rating,
        "reason": ("不可下標(多為賣家設了投標者評價限制)" if blocked else
                   f"賣家好評率 {rating}% 低於門檻 {min_rating}%"
                   if rating is not None and rating < min_rating else
                   "評價抓取失敗,fail-closed 視為不可買" if rating is None else "可買"),
    }
