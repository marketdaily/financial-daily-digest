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


def scout(page, item, rate, sell_price, limit=6):
    """回傳當前拍場上、落地後仍有肉的標的(已排序,最賺的在前)。"""
    url = ("https://auctions.yahoo.co.jp/search/search?p="
           + up.quote(item["jp_kw"]) + "&n=50")
    try:
        page.goto(url, timeout=60_000)
        page.wait_for_timeout(3500)
    except Exception as e:
        return {"error": f"render_failed:{e}"}

    floor = item.get("jp_floor", 0)
    out = []
    for title, jpy, aid in _cards(page):
        if jpy < floor:          # 配件雜訊(頭套/握把/配重)
            continue
        cost = landed_cost(jpy, rate, item)
        f2f = sell_price - cost
        out.append({
            "title": title,
            "jpy": jpy,
            "landed": cost,
            "margin_f2f": f2f,
            "margin_shopee": round(sell_price * (1 - SHOPEE_PCT) - SHOPEE_FLAT - cost),
            "roi": round(f2f / cost * 100) if cost else 0,
            "buyee": f"https://buyee.jp/item/yahoo/auction/{aid}",
            "yahoo": f"https://auctions.yahoo.co.jp/jp/auction/{aid}",
        })
    out.sort(key=lambda x: -x["margin_f2f"])
    return {"count": len(out), "items": out[:limit], "search_url": url,
            "buyee_search": "https://buyee.jp/item/search/query/" + up.quote(item["jp_kw"])}
