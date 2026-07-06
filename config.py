import os
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BEEHIIV_API_KEY = os.getenv("BEEHIIV_API_KEY")
BEEHIIV_PUBLICATION_ID = os.getenv("BEEHIIV_PUBLICATION_ID")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "hello@marketdaily.ai")
SENDER_NAME = os.getenv("SENDER_NAME", "財經日報")

US_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "TSM", "ARM",
    "JPM", "GS", "BRK-B"
]

TW_STOCKS = [
    {"symbol": "2330", "name": "台積電"},
    {"symbol": "2454", "name": "聯發科"},
    {"symbol": "2317", "name": "鴻海"},
]

US_INDICES = ["^GSPC", "^IXIC", "^DJI", "DX-Y.NYB"]
TW_INDICES = ["^TWII"]

NEWS_WHITELIST_DOMAINS = [
    "reuters.com", "bloomberg.com", "wsj.com", "cnbc.com",
    "apnews.com", "ft.com", "marketwatch.com",
    "finance.yahoo.com", "investing.com", "seekingalpha.com",
    "businessinsider.com", "forbes.com", "barrons.com",
    "thestreet.com", "benzinga.com", "zacks.com",
    "livemint.com", "economictimes.indiatimes.com"
]

TW_NEWS_WHITELIST_DOMAINS = [
    "cna.com.tw", "udn.com", "ctee.com.tw", "anue.com.tw",
    "cnyes.com", "moneydj.com", "technews.tw", "bnext.com.tw",
    "yahoo.com", "ltn.com.tw", "chinatimes.com", "ettoday.net",
    "businesstoday.com.tw", "wealth.com.tw", "digitimes.com", "sinotrade.com.tw",
]

VAGUE_KEYWORDS = [
    "聽說", "消息人士稱", "據悉", "傳聞", "內部消息", "匿名人士",
    "rumored", "sources say", "reportedly", "allegedly", "unconfirmed"
]
