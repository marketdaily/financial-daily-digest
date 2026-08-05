"""雙端價格源:日本落札行情(aucfree) + 台灣實際刊登行情(BigGo)。

設計鐵則(踩過的坑):
- 台灣端一律取「實際刊登價」,絕不用代理商定價當售價錨。2026-08-05 用公司貨定價
  當錨導致捲線器毛利被高估三倍,實際水貨行情早被現有賣家壓低。
- 抓不到就回 error,不回 0/None 混充。靜默失敗會讓雷達看起來「沒有機會」而不是「壞了」。
"""
import re
import statistics

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

AUCFREE_AVG = re.compile(r"全部で([0-9,]+)件あります。平均落札価格は([0-9,]+)円")


def _num(s):
    return int(str(s).replace(",", ""))


def jp_sold(keyword, jp_floor=0, timeout=25):
    """日本雅虎拍賣近 30 日落札行情。回 dict 或 {'error': ...}。

    ⚠️ meta 的「平均落札価格」會被配件污染:同關鍵字下頭套/握把/配重等小物
    也算進平均。實例:SC Special Select meta 均價 ¥18,451,但逐筆分布是
    低段 ¥3,000-5,000(配件)、高段 ¥27,000-33,000(整支推桿)——均價低估近一半,
    會讓落地成本算得太便宜、毛利虛胖。故同時解析逐筆成交價並取分位數。
    """
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
