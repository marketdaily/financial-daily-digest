"""雙端價格源:日本落札行情(aucfree) + 台灣實際刊登行情(BigGo)。

設計鐵則(踩過的坑):
- 台灣端一律取「實際刊登價」,絕不用代理商定價當售價錨。2026-08-05 用公司貨定價
  當錨導致捲線器毛利被高估三倍,實際水貨行情早被現有賣家壓低。
- 抓不到就回 error,不回 0/None 混充。靜默失敗會讓雷達看起來「沒有機會」而不是「壞了」。
"""
import re
import statistics

import requests

from arb import cache

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

AUCFREE_AVG = re.compile(r"全部で([0-9,]+)件あります。平均落札価格は([0-9,]+)円")


def _num(s):
    return int(str(s).replace(",", ""))


def jp_sold(keyword, jp_floor=0, timeout=25, use_cache=True):
    """日本雅虎拍賣近 30 日落札行情。回 dict 或 {'error': ...}。

    ⚠️ meta 的「平均落札価格」會被配件污染:同關鍵字下頭套/握把/配重等小物
    也算進平均。實例:SC Special Select meta 均價 ¥18,451,但逐筆分布是
    低段 ¥3,000-5,000(配件)、高段 ¥27,000-33,000(整支推桿)——均價低估近一半,
    會讓落地成本算得太便宜、毛利虛胖。故同時解析逐筆成交價並取分位數。
    """
    if use_cache:
        return cache.cached("aucfree", keyword, jp_floor,
                            fetch=lambda: jp_sold(keyword, jp_floor, timeout,
                                                  use_cache=False))
    url = "https://aucfree.com/search?q=" + requests.utils.quote(keyword)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    except Exception as e:
        return {"error": f"fetch_failed:{e}"}
    if r.status_code != 200:
        return {"error": f"http_{r.status_code}"}
    m = AUCFREE_AVG.search(r.text)
    if not m:
        if "件あります" in r.text or "落札" in r.text:
            return {"error": "parse_failed_layout_changed"}
        return {"error": "no_results"}

    out = {"count": _num(m.group(1)), "avg_jpy": _num(m.group(2)), "url": url}

    raw = [_num(x) for x in re.findall(r"([0-9,]{3,})\s*円", r.text)]
    vals = sorted(v for v in raw if jp_floor <= v <= 3_000_000)
    if len(vals) >= 4:
        out["sample"] = len(vals)
        out["median_jpy"] = int(statistics.median(vals))
        out["p25_jpy"] = vals[len(vals) // 4]
        out["p75_jpy"] = vals[(len(vals) * 3) // 4]
        # 進貨成本一律用 median(抗配件雜訊),而非 meta 均價
        out["cost_jpy"] = out["median_jpy"]
        # 低段離群佔比高 = 混了配件,標記給上層決定要不要信
        out["contaminated"] = out["median_jpy"] > out["avg_jpy"] * 1.25
    else:
        out["cost_jpy"] = out["avg_jpy"]
        out["sample"] = len(vals)
        out["contaminated"] = None      # 樣本太少無法判斷,不能當作乾淨
    return out


# BigGo 反爬頁的特徵。⚠️ 這條路徑一定要獨立成 error:
# 若把「被擋」當成 count=0,在本系統裡會被解讀成「台灣零刊登=空白市場=機會」,
# 一次限流就會讓全部標的變成假機會(2026-08-05 錨校正實測:連查 40 次後 12/12 全誤報零刊登)。
ANTIBOT_MARKS = ("驗證你不是機器人", "搜尋行為異常", "驗證並繼續",
                 "not a robot", "Too Many Requests")


def tw_listings(page, keyword, price_floor=0, price_cap=500_000, settle_ms=3500):
    """台灣實際刊登行情(BigGo 聚合蝦皮/露天/Yahoo)。需傳入 playwright page。

    price_floor 用來濾掉同關鍵字下的配件雜訊(如搜推桿會混進 NT$810 的配重螺絲)。
    """
    url = "https://biggo.com.tw/s/" + requests.utils.quote(keyword) + "/"
    try:
        page.goto(url, timeout=60_000)
        page.wait_for_timeout(settle_ms)
        txt = page.inner_text("body")
    except Exception as e:
        return {"error": f"render_failed:{e}"}
    if any(k in txt for k in ANTIBOT_MARKS):
        return {"error": "blocked_by_antibot", "url": url}
    # 正常結果頁動輒數千字;極短頁面通常是攔截頁/空殼,不可當成「沒有刊登」
    if len(txt) < 300 and "搜尋不到符合" not in txt:
        return {"error": f"suspicious_short_page:{len(txt)}", "url": url}
    if "搜尋不到符合" in txt:
        return {"count": 0, "url": url, "note": "no_listings"}
    raw = [_num(x) for x in re.findall(r"\$\s?([0-9,]{3,})", txt)]
    prices = sorted(p for p in raw if price_floor <= p <= price_cap)
    if not prices:
        return {"count": 0, "url": url, "note": "all_filtered",
                "raw_seen": len(raw)}
    return {
        "count": len(prices),
        "min": prices[0],
        "p25": prices[len(prices) // 4],
        "median": statistics.median(prices),
        "max": prices[-1],
        "url": url,
    }


def _ruten_listings(page, keyword, price_floor=0, price_cap=500_000):
    """備援台灣行情源:露天。BigGo 被反爬擋住時自動改走這條。

    露天價格是純數字(無 $ 或「元」前綴),故只取**含千分位逗號**的數字——
    商品編號/分類計數不帶逗號,這條規則同時濾掉它們。需等 7s 才渲染完。
    """
    url = "https://www.ruten.com.tw/find/?q=" + requests.utils.quote(keyword)
    try:
        page.goto(url, timeout=60_000)
        page.wait_for_timeout(7000)
        txt = page.inner_text("body")
    except Exception as e:
        return {"error": f"ruten_render_failed:{e}"}
    if len(txt) < 300:
        return {"error": f"ruten_suspicious_short_page:{len(txt)}"}
    raw = [_num(x) for x in re.findall(r"\b([0-9]{1,3}(?:,[0-9]{3})+)\b", txt)]
    prices = sorted(p for p in raw if price_floor <= p <= price_cap)
    if not prices:
        return {"count": 0, "url": url, "note": "no_listings", "src": "ruten"}
    return {
        "count": len(prices), "min": prices[0], "p25": prices[len(prices) // 4],
        "median": statistics.median(prices), "max": prices[-1],
        "url": url, "src": "ruten",
    }


def tw_listings_resilient(page, keyword, price_floor=0, price_cap=500_000,
                          use_cache=True):
    """先 BigGo,被擋則自動退到露天。回傳含 src 標示用了哪個源。

    ⚠️ 兩源都壞才回 error——絕不因為單一源被擋就說「沒有刊登」。
    快取:行情不需分鐘級更新,20h TTL;兩源都被擋時回退過期快取並標 stale。
    """
    if use_cache:
        return cache.cached(
            "tw_listings", keyword, price_floor,
            fetch=lambda: tw_listings_resilient(page, keyword, price_floor,
                                                price_cap, use_cache=False))
    r = tw_listings(page, keyword, price_floor, price_cap)
    if "error" not in r:
        return {**r, "src": r.get("src", "biggo")}
    first_err = r["error"]
    r2 = _ruten_listings(page, keyword, price_floor, price_cap)
    if "error" not in r2:
        return {**r2, "primary_error": first_err}
    return {"error": f"all_sources_failed(biggo:{first_err}; ruten:{r2['error']})"}


def jpy_twd_rate(fallback=0.21, timeout=15):
    """JPY→TWD 匯率。抓失敗回 fallback 並標記,不靜默。"""
    for url, path in (
        ("https://open.er-api.com/v6/latest/JPY", ("rates", "TWD")),
        ("https://api.frankfurter.app/latest?from=JPY&to=TWD", ("rates", "TWD")),
    ):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code != 200:
                continue
            v = r.json()
            for k in path:
                v = (v or {}).get(k)
            if v and 0.1 < v < 0.5:
                return {"rate": v, "source": url.split("/")[2]}
        except Exception:
            continue
    return {"rate": fallback, "source": "fallback_STALE"}
