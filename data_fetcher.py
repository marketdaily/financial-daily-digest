import yfinance as yf
import requests
import feedparser
from datetime import datetime, timedelta
from config import (
    NEWS_API_KEY, US_STOCKS, TW_STOCKS, US_INDICES, TW_INDICES,
    NEWS_WHITELIST_DOMAINS, TW_NEWS_WHITELIST_DOMAINS
)

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
    for domain, url in RSS_FEEDS:
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


def fetch_us_market():
    result = {}
    for symbol in US_INDICES + US_STOCKS:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                last_close = hist["Close"].iloc[-1]
                change_pct = (last_close - prev_close) / prev_close * 100
                result[symbol] = {
                    "price": round(last_close, 2),
                    "change_pct": round(change_pct, 2)
                }
        except Exception:
            continue
    return result


def fetch_tw_market():
    result = {}
    try:
        ticker = yf.Ticker("^TWII")
        hist = ticker.history(period="2d")
        if len(hist) >= 2:
            prev_close = hist["Close"].iloc[-2]
            last_close = hist["Close"].iloc[-1]
            change_pct = (last_close - prev_close) / prev_close * 100
            result["^TWII"] = {
                "price": round(last_close, 2),
                "change_pct": round(change_pct, 2)
            }
    except Exception:
        pass

    for stock in TW_STOCKS:
        try:
            symbol = f"{stock['symbol']}.TW"
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                last_close = hist["Close"].iloc[-1]
                change_pct = (last_close - prev_close) / prev_close * 100
                result[stock["symbol"]] = {
                    "name": stock["name"],
                    "price": round(last_close, 2),
                    "change_pct": round(change_pct, 2)
                }
        except Exception:
            continue
    return result


def fetch_custom_stocks(symbols: list) -> dict:
    result = {}
    for symbol in symbols:
        try:
            yf_symbol = f"{symbol}.TW" if symbol.isdigit() or (len(symbol) == 4 and symbol.isdigit()) else symbol
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                last_close = hist["Close"].iloc[-1]
                change_pct = (last_close - prev_close) / prev_close * 100
                result[symbol] = {
                    "price": round(last_close, 2),
                    "change_pct": round(change_pct, 2)
                }
        except Exception:
            continue
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
    domains = ",".join(NEWS_WHITELIST_DOMAINS)
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


def fetch_tw_rss_news() -> list:
    articles = []
    cutoff = datetime.now() - timedelta(hours=36)
    for domain, url in TW_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
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
    indicators = {}

    for key, symbol in [("vix", "^VIX"), ("us10y", "^TNX")]:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) >= 1:
                indicators[key] = round(hist["Close"].iloc[-1], 2)
        except Exception:
            pass

    for key, symbol in [("gold", "GC=F"), ("oil", "CL=F")]:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) >= 2:
                prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
                indicators[key] = {"price": round(last, 2), "change_pct": round((last - prev) / prev * 100, 2)}
        except Exception:
            pass

    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        if len(hist) >= 2:
            prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
            indicators["usdtwd"] = {"rate": round(last, 3), "change_pct": round((last - prev) / prev * 100, 3)}
    except Exception:
        pass

    if "vix" in indicators:
        vix = indicators["vix"]
        if vix > 30:
            score, rating = 15, "Extreme Fear"
        elif vix > 25:
            score, rating = 30, "Fear"
        elif vix > 20:
            score, rating = 45, "Neutral"
        elif vix > 15:
            score, rating = 65, "Greed"
        else:
            score, rating = 80, "Extreme Greed"
        indicators["fear_greed"] = {"score": score, "rating": rating}

    return indicators


def fetch_crypto() -> dict:
    result = {}
    for key, symbol in [("btc", "BTC-USD"), ("eth", "ETH-USD")]:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) >= 2:
                prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
                result[key] = {
                    "price": round(last, 2),
                    "change_pct": round((last - prev) / prev * 100, 2)
                }
        except Exception:
            pass
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
    for symbol, name in SECTOR_ETFS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) >= 2:
                prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
                change_pct = round((last - prev) / prev * 100, 2)
                sectors.append({"symbol": symbol, "name": name, "change_pct": change_pct})
        except Exception:
            continue
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
        "date": datetime.now().strftime("%Y-%m-%d")
    }
