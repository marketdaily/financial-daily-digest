import sys
sys.path.insert(0, ".")

from config import BREVO_API_KEY
from data_fetcher import fetch_all
from fake_news_filter import filter_us_news, filter_tw_news
from analyzer import generate_report, get_personalized_subject
from publisher import send_transactional_email
from main import save_local, build_email_html
import shutil

US_STOCKS = ["NVDA", "TSLA", "AAPL"]
TW_STOCKS = ["2330", "2454"]
EMAIL = "delvin.12345678@gmail.com"
DATE_LABEL = "2026-05-20"

import json
import os

CACHE_FILE = "output/test_data_cache.json"

print("① 抓取市場數據（含個人持倉）...")
if os.path.exists(CACHE_FILE):
    print("   使用本地快取（避免 rate limit）")
    with open(CACHE_FILE, "r") as f:
        data = json.load(f)
else:
    data = fetch_all(extra_us_stocks=US_STOCKS, extra_tw_stocks=TW_STOCKS)
    data["date"] = DATE_LABEL
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   已快取至 {CACHE_FILE}")
data["date"] = DATE_LABEL

print("② 過濾假訊息...")
data["us_news"] = filter_us_news(data["us_news"])
data["tw_news"] = filter_tw_news(data["tw_news"])
print(f"   美股新聞：{len(data['us_news'])} 則 | 台股新聞：{len(data['tw_news'])} 則")
print(f"   美股個股數：{len(data['us_market'])} 支 | 台股：{len(data['tw_market'])} 支")

print("③ AI 生成個人化報告...")
inner = generate_report(data, US_STOCKS, TW_STOCKS)
subject = get_personalized_subject(data, US_STOCKS, TW_STOCKS, DATE_LABEL)
print(f"   主旨：{subject}")

print("④ 儲存本地預覽...")
path = save_local(DATE_LABEL, inner)
shutil.copy(path, "output/digest_2026-05-16_personal_delvin.html")

print("⑤ CSS inline 化並發送...")
email_html = build_email_html(DATE_LABEL, inner)
ok = send_transactional_email(EMAIL, DATE_LABEL, email_html, BREVO_API_KEY, subject=subject)
print(f"✅ 發送{'成功' if ok else '失敗'} → {EMAIL}")
