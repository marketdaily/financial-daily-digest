import yfinance as yf
from yahooquery import Ticker as YQTicker
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from config import (
    NEWS_API_KEY, US_STOCKS, TW_STOCKS, US_INDICES, TW_INDICES,
    NEWS_WHITELIST_DOMAINS, TW_NEWS_WHITELIST_DOMAINS
)
from config_loader import get_us_stocks, get_tw_stocks, get_us_feeds, get_tw_feeds, get_domains

RSS_FEEDS = [
    # 美股財經
    ("reuters.com",     "https://feeds.reuters.com/reuters/businessNews"),
    ("cnbc.com",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("cnbc.com",        "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("cnbc.com",        "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("marketwatch.com", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("marketwatch.com", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("finance.yahoo.com","https://finance.yahoo.com/news/rssindex"),
    ("investing.com",   "https://www.investing.com/rss/news.rss"),
    ("investing.com",   "https://www.investing.com/rss/stock_market_news.rss"),
    ("seekingalpha.com","https://seekingalpha.com/market_currents.xml"),
    ("ft.com",          "https://www.ft.com/?format=rss"),
]

TW_RSS_FEEDS = [
    # 台股中文財經
    ("cnyes.com",       "https://news.cnyes.com/rss/category/tw_stock"),
    ("cnyes.com",       "https://news.cnyes.com/rss/category/headline"),
    ("moneydj.com",     "https://www.moneydj.com/KMDJ/RSS/RSSFeed.aspx?svc=NW"),
    ("cna.com.tw",      "https://feeds.feedburner.com/cnafinance"),
    ("udn.com",         "https://udn.com/rssfeed/news/2/6638?ch=news"),
]

def fetch_rss_news() -> list:
    articles = []
    cutoff = datetime.now() - timedelta(hours=36)
    feeds = get_us_feeds() or RSS_FEEDS
    for domain, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if published and published < cutoff:
                    continue
                articles.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", "")[:200],
                    "url": entry.get("link", f"https://{domain}"),
                    "source": {"name": domain},
                    "publishedAt": published.isoformat() if published else "",
                })
        except Exception:
            continue
    return articles


def _batch_prices(symbols: list) -> dict:
    """Batch fetch via yahooquery — one HTTP call, no rate limit issues"""
    if not symbols:
        return {}
    try:
        data = YQTicker(symbols).price
        result = {}
        for sym in symbols:
            p = data.get(sym, {})
            price = p.get("regularMarketPrice")
            prev = p.get("regularMarketPreviousClose")
            if price and prev and prev != 0:
                result[sym] = {
                    "price": round(float(price), 2),
                    "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 2),
                }
        return result
    except Exception:
        return {}


def _get_cached_price(symbol: str) -> dict:
    return _batch_prices([symbol]).get(symbol, {})


# TWSE OpenAPI — 一次取全部台股收盤，官方數據無 rate limit
_TWSE_CACHE: dict = {}
_TWSE_CACHE_TIME: datetime = None

def _fetch_twse_all() -> dict:
    """Return {stock_code: {name, price, change_pct}} for all TWSE listed stocks"""
    global _TWSE_CACHE, _TWSE_CACHE_TIME
    now = datetime.now()
    if _TWSE_CACHE and _TWSE_CACHE_TIME and (now - _TWSE_CACHE_TIME).seconds < 3600:
        return _TWSE_CACHE
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=15
        )
        data = resp.json()
        result = {}
        for row in data:
            code = row.get("Code", "")
            if not code.isdigit():
                continue
            try:
                close = float(row["ClosingPrice"])
                change = float(row["Change"])
                prev = close - change
                change_pct = (change / prev * 100) if prev != 0 else 0
                result[code] = {
                    "name": row.get("Name", code),
                    "price": round(close, 2),
                    "change_pct": round(change_pct, 2),
                }
            except (ValueError, ZeroDivisionError):
                continue
        _TWSE_CACHE = result
        _TWSE_CACHE_TIME = now
        return result
    except Exception:
        return _TWSE_CACHE


def fetch_us_market():
    active_stocks = get_us_stocks()
    symbols = US_INDICES + [s if isinstance(s, str) else s["symbol"] for s in active_stocks]
    result = {}
    for sym in symbols:
        d = _get_cached_price(sym)
        if d:
            result[sym] = d
    return result


def fetch_tw_market():
    twse = _fetch_twse_all()
    result = {}
    d = _get_cached_price("^TWII")
    if d:
        result["^TWII"] = d
    for stock in get_tw_stocks():
        code = stock["symbol"] if isinstance(stock, dict) else stock
        if code in twse:
            result[code] = twse[code]
    return result


def fetch_custom_stocks(symbols: list) -> dict:
    twse = _fetch_twse_all()
    result = {}
    for sym in symbols:
        if sym.isdigit() or (len(sym) == 4 and sym.isdigit()):
            if sym in twse:
                result[sym] = twse[sym]
        else:
            d = _get_cached_price(sym)
            if d:
                result[sym] = d
    return result


def fetch_ticker_news(extra_symbols: list = None) -> list:
    articles = []
    seen = set()
    base = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "TSM", "AMD"]
    all_symbols = list(dict.fromkeys(base + (extra_symbols or [])))
    for symbol in all_symbols:
        try:
            ticker = yf.Ticker(symbol)
            for item in ticker.news[:5]:
                title = item.get("title", "")
                if title in seen:
                    continue
                seen.add(title)
                url = item.get("link", "")
                domain = url.split("/")[2].replace("www.", "") if url else "finance.yahoo.com"
                articles.append({
                    "title": title,
                    "description": item.get("summary", ""),
                    "url": url,
                    "source": {"name": domain},
                    "publishedAt": "",
                    "relatedTicker": symbol,
                })
        except Exception:
            continue
    return articles


def fetch_us_news(extra_tickers: list = None):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    domains = ",".join(get_domains() or NEWS_WHITELIST_DOMAINS)
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=stock+market+economy+fed+earnings"
        f"&domains={domains}"
        f"&from={yesterday}"
        f"&language=en"
        f"&sortBy=relevancy"
        f"&pageSize=20"
        f"&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        api_articles = data.get("articles", [])
    except Exception:
        api_articles = []

    rss_articles = fetch_rss_news()
    ticker_articles = fetch_ticker_news(extra_tickers)
    return api_articles + rss_articles + ticker_articles


def _fetch_cnyes_tw_news(limit: int = 15) -> list:
    """Fetch TW stock news from cnyes.com API."""
    categories = ["tw_stock", "headline"]
    articles = []
    cutoff = datetime.now() - timedelta(hours=36)
    seen = set()
    for cat in categories:
        try:
            resp = requests.get(
                f"https://news.cnyes.com/api/v3/news/category/{cat}",
                params={"limit": limit},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            items = resp.json().get("items", {}).get("data", [])
            for item in items:
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                pub_ts = item.get("publishAt", 0)
                published = datetime.fromtimestamp(pub_ts) if pub_ts else None
                if published and published < cutoff:
                    continue
                news_id = item.get("newsId", "")
                url = f"https://news.cnyes.com/news/id/{news_id}" if news_id else "https://news.cnyes.com"
                seen.add(title)
                articles.append({
                    "title": title,
                    "description": item.get("summary", "")[:200],
                    "url": url,
                    "source": {"name": "cnyes.com"},
                    "publishedAt": published.isoformat() if published else "",
                    "lang": "zh",
                })
        except Exception:
            continue
    return articles


def fetch_tw_rss_news() -> list:
    articles = _fetch_cnyes_tw_news()
    cutoff = datetime.now() - timedelta(hours=36)
    seen_titles = {a["title"] for a in articles}

    fallback_feeds = [
        ("moneydj.com", "https://www.moneydj.com/KMDJ/RSS/RSSFeed.aspx?svc=NW"),
        ("cna.com.tw",  "https://feeds.feedburner.com/cnafinance"),
    ]
    for domain, url in fallback_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if published and published < cutoff:
                    continue
                seen_titles.add(title)
                articles.append({
                    "title": title,
                    "description": entry.get("summary", "")[:200],
                    "url": entry.get("link", f"https://{domain}"),
                    "source": {"name": domain},
                    "publishedAt": published.isoformat() if published else "",
                    "lang": "zh",
                })
        except Exception:
            continue
    return articles


def fetch_tw_news():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=Taiwan+stock+TSMC+TWD+Taiwan+economy"
        f"&from={yesterday}"
        f"&language=en"
        f"&sortBy=relevancy"
        f"&pageSize=20"
        f"&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        api_articles = data.get("articles", [])
    except Exception:
        api_articles = []
    tw_rss = fetch_tw_rss_news()
    return api_articles + tw_rss


def fetch_indicators() -> dict:
    ind_syms = ["^VIX", "^TNX", "GC=F", "CL=F", "TWD=X"]
    raw = _batch_prices(ind_syms)
    indicators = {}

    if "^VIX" in raw:
        indicators["vix"] = raw["^VIX"]["price"]
    if "^TNX" in raw:
        indicators["us10y"] = raw["^TNX"]["price"]
    if "GC=F" in raw:
        indicators["gold"] = {"price": raw["GC=F"]["price"], "change_pct": raw["GC=F"]["change_pct"]}
    if "CL=F" in raw:
        indicators["oil"] = {"price": raw["CL=F"]["price"], "change_pct": raw["CL=F"]["change_pct"]}
    if "TWD=X" in raw:
        indicators["usdtwd"] = {"rate": raw["TWD=X"]["price"], "change_pct": raw["TWD=X"]["change_pct"]}

    if "vix" in indicators:
        vix = indicators["vix"]
        if vix > 30:   score, rating = 15, "Extreme Fear"
        elif vix > 25: score, rating = 30, "Fear"
        elif vix > 20: score, rating = 45, "Neutral"
        elif vix > 15: score, rating = 65, "Greed"
        else:          score, rating = 80, "Extreme Greed"
        indicators["fear_greed"] = {"score": score, "rating": rating}

    return indicators


def fetch_crypto() -> dict:
    raw = _batch_prices(["BTC-USD", "ETH-USD"])
    result = {}
    if "BTC-USD" in raw:
        result["btc"] = raw["BTC-USD"]
    if "ETH-USD" in raw:
        result["eth"] = raw["ETH-USD"]
    return result


SECTOR_ETFS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "醫療",
    "XLY": "非必需消費",
    "XLC": "通訊",
    "XLI": "工業",
    "XLP": "必需消費",
}


def fetch_sector_performance() -> list:
    sectors = []
    raw = _batch_prices(list(SECTOR_ETFS.keys()))
    for symbol, name in SECTOR_ETFS.items():
        if symbol in raw:
            sectors.append({"symbol": symbol, "name": name, "change_pct": raw[symbol]["change_pct"]})
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    return sectors


def fetch_earnings_calendar() -> list:
    events = []
    watchlist = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "TSM"]
    for symbol in watchlist:
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if cal is None:
                continue
            if isinstance(cal, dict):
                date_val = cal.get("Earnings Date")
                if date_val:
                    if isinstance(date_val, list):
                        date_val = date_val[0]
                    events.append({"symbol": symbol, "date": str(date_val)[:10]})
            elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
                date_val = cal["Earnings Date"].iloc[0]
                events.append({"symbol": symbol, "date": str(date_val)[:10]})
        except Exception:
            continue
    events.sort(key=lambda x: x["date"])
    return events


def fetch_all(extra_us_stocks: list = None, extra_tw_stocks: list = None):
    us_market = fetch_us_market()
    if extra_us_stocks:
        missing = [s for s in extra_us_stocks if s not in us_market]
        if missing:
            us_market.update(fetch_custom_stocks(missing))

    tw_market = fetch_tw_market()
    if extra_tw_stocks:
        missing_tw = [s for s in extra_tw_stocks if s not in tw_market]
        if missing_tw:
            tw_market.update(fetch_custom_stocks(missing_tw))

    return {
        "us_market": us_market,
        "tw_market": tw_market,
        "us_news": fetch_us_news(extra_us_stocks),
        "tw_news": fetch_tw_news(),
        "indicators": fetch_indicators(),
        "crypto": fetch_crypto(),
        "sectors": fetch_sector_performance(),
        "earnings": fetch_earnings_calendar(),
        # 必用 TW 時區：GH Actions runner 在 UTC，06:55 TW 寄送時 UTC 還是前一天
        # 2026-05-27 出包過：runner UTC 22:55 (= TW 5/27 06:55) datetime.now()→5/26
        # 害 _market_status() 拿 5/26 算「昨晚」變成 5/25 Memorial Day 假，日報通篇寫錯
        "date": (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    }
