import os
from data_fetcher import fetch_all
from fake_news_filter import filter_us_news, filter_tw_news
from analyzer import generate_report
from publisher import publish_to_brevo


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f0f2f5; color: #1a1a1a; }
.wrapper { max-width: 640px; margin: 0 auto; background: #fff; }

.header { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); color: #fff; padding: 32px 28px 24px; }
.header-meta { font-size: 11px; color: rgba(255,255,255,0.5); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 10px; }
.header h1 { font-size: 24px; font-weight: 800; letter-spacing: -0.5px; }
.header-tagline { font-size: 12px; color: rgba(255,255,255,0.45); margin-top: 6px; }

.tldr { background: #fffbeb; border-left: 4px solid #f59e0b; margin: 20px 28px; padding: 16px 18px; border-radius: 0 10px 10px 0; }
.tldr-title { font-size: 13px; font-weight: 800; color: #92400e; margin-bottom: 10px; letter-spacing: 0.5px; }
.tldr ul { list-style: none; }
.tldr ul li { font-size: 14px; color: #444; padding: 4px 0; padding-left: 16px; position: relative; line-height: 1.5; }
.tldr ul li::before { content: "→"; position: absolute; left: 0; color: #f59e0b; font-weight: 700; }

.section-label { font-size: 11px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase; color: #888; padding: 24px 28px 12px; }

.market-summary { padding: 0 28px 20px; font-size: 14px; color: #444; line-height: 1.7; }

.news-card { margin: 0 28px 12px; padding: 14px 16px; border: 1px solid #eee; border-radius: 12px; background: #fafafa; }
.news-tag { display: inline-block; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; margin-bottom: 8px; }
.news-tag.verified { background: #dcfce7; color: #166534; }
.news-tag.single { background: #fef9c3; color: #854d0e; }
.news-headline { font-size: 15px; font-weight: 700; color: #111; line-height: 1.4; margin-bottom: 8px; }
.news-why { font-size: 13px; color: #555; line-height: 1.5; background: #f0f7ff; padding: 8px 12px; border-radius: 8px; }
.read-more { display: inline-block; margin-top: 10px; font-size: 12px; font-weight: 700; color: #3b82f6; text-decoration: none; letter-spacing: 0.3px; }
.read-more:hover { text-decoration: underline; }

.stock-card { display: flex; align-items: flex-start; gap: 12px; margin: 0 28px 10px; padding: 12px 16px; border-radius: 12px; background: #fafafa; border: 1px solid #eee; }
.ticker { font-size: 14px; font-weight: 800; color: #1a1a2e; min-width: 52px; padding-top: 2px; }
.stock-move { font-size: 14px; font-weight: 700; min-width: 72px; padding-top: 2px; }
.stock-move.up { color: #16a34a; }
.stock-move.down { color: #dc2626; }
.stock-comment { font-size: 13px; color: #555; line-height: 1.5; flex: 1; }

.macro-list { padding: 0 28px 20px; }
.macro-item { font-size: 14px; color: #444; padding: 6px 0; border-bottom: 1px solid #f5f5f5; line-height: 1.6; }

.verdict { margin: 0 28px 16px; padding: 20px; border-radius: 14px; }
.verdict.bullish { background: #f0fdf4; border: 1.5px solid #86efac; }
.verdict.bearish { background: #fef2f2; border: 1.5px solid #fca5a5; }
.verdict.neutral  { background: #f8fafc; border: 1.5px solid #cbd5e1; }
.verdict-emoji { font-size: 28px; margin-bottom: 10px; }
.verdict-text { font-size: 14px; color: #333; line-height: 1.7; }

.watch-list { margin: 0 28px 28px; padding: 16px; background: #f8fafc; border-radius: 12px; }
.watch-title { font-size: 12px; font-weight: 700; color: #666; margin-bottom: 10px; letter-spacing: 1px; }
.watch-item { font-size: 13px; color: #444; padding: 5px 0; border-bottom: 1px dashed #e5e7eb; }
.watch-item:last-child { border-bottom: none; }

.indicator-bar { display: flex; gap: 10px; margin: 0 28px 20px; flex-wrap: wrap; }
.indicator-item { flex: 1; min-width: 110px; padding: 12px 14px; background: #fafafa; border: 1px solid #eee; border-radius: 12px; text-align: center; }
.indicator-label { font-size: 10px; font-weight: 800; color: #888; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.indicator-value { font-size: 17px; font-weight: 800; color: #1a1a2e; }
.indicator-sub { font-size: 11px; color: #888; margin-top: 2px; }
.indicator-fear { color: #dc2626; }
.indicator-greed { color: #16a34a; }
.indicator-neutral { color: #f59e0b; }

.second-order { margin: 0 28px 20px; padding: 14px 16px; background: #f0f4ff; border-left: 4px solid #6366f1; border-radius: 0 10px 10px 0; font-size: 13px; color: #444; line-height: 1.7; }

.crypto-bar { display: flex; gap: 10px; margin: 0 28px 20px; }
.crypto-item { flex: 1; padding: 14px 16px; background: #fafafa; border: 1px solid #eee; border-radius: 12px; text-align: center; }
.crypto-name { font-size: 11px; font-weight: 800; color: #888; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.crypto-price { font-size: 18px; font-weight: 800; }
.crypto-price.up { color: #16a34a; }
.crypto-price.down { color: #dc2626; }
.crypto-change { font-size: 12px; color: #888; margin-top: 3px; }

.sector-bar { padding: 0 28px 20px; }
.sector-item { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f5f5f5; }
.sector-name { font-size: 13px; font-weight: 700; color: #333; min-width: 100px; }
.sector-move { font-size: 13px; font-weight: 700; min-width: 68px; }
.sector-move.up { color: #16a34a; }
.sector-move.down { color: #dc2626; }
.sector-comment { font-size: 12px; color: #666; flex: 1; }

.earnings-list { padding: 0 28px 20px; }
.earnings-item { display: flex; align-items: baseline; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f5f5f5; }
.earnings-ticker { font-size: 14px; font-weight: 800; color: #1a1a2e; min-width: 52px; }
.earnings-date { font-size: 12px; color: #888; min-width: 78px; }
.earnings-note { font-size: 13px; color: #555; flex: 1; }

.stock-news-item { margin: 0 28px 12px; padding: 14px 16px; border: 1px solid #eef2ff; border-radius: 12px; background: #f8faff; display: flex; gap: 12px; align-items: flex-start; }
.stock-news-ticker { font-size: 14px; font-weight: 800; color: #4338ca; min-width: 52px; padding-top: 2px; }
.stock-news-content { flex: 1; }
.stock-news-headline { font-size: 14px; font-weight: 700; color: #111; line-height: 1.4; margin-bottom: 6px; }
.stock-news-impact { font-size: 13px; color: #555; background: #eef2ff; padding: 7px 10px; border-radius: 8px; line-height: 1.5; }
.stock-news-empty { margin: 0 28px 20px; font-size: 13px; color: #aaa; padding: 10px 0; }

.footer { background: #1a1a2e; color: rgba(255,255,255,0.35); text-align: center; padding: 20px 28px; font-size: 11px; line-height: 2; }
"""


def save_local(date: str, html_report: str):
    os.makedirs("output", exist_ok=True)
    path = f"output/digest_{date}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>財經日報 {date}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div class="header-meta">{date}</div>
    <h1>📊 財經日報</h1>
    <div class="header-tagline">AI 精選 · 假訊息過濾 · 美股 + 台股</div>
  </div>
  {html_report}
  <div class="footer">
    財經日報 · AI 精選 · 假訊息過濾<br>
    ✅ 多源確認 = 2個以上白名單媒體報導 &nbsp;|&nbsp; ⚠️ 單一來源 = 請自行查證<br>
    本報告為 AI 生成，僅供參考，不構成投資建議
  </div>
</div>
</body>
</html>""")
    print(f"   本地預覽已儲存：{path}")
    return path


WORKER_URL = "https://marketdaily-webhook.delvin-12345678.workers.dev"


def get_user_preferences(email: str) -> dict:
    import requests
    try:
        res = requests.post(
            f"{WORKER_URL}/get-preferences",
            json={"email": email},
            timeout=5
        )
        if res.ok:
            return res.json()
    except Exception:
        pass
    return {"us_stocks": [], "tw_stocks": []}


def run():
    print("① 抓取市場數據與新聞...")
    data = fetch_all()

    print("② 過濾假訊息...")
    data["us_news"] = filter_us_news(data["us_news"])
    data["tw_news"] = filter_tw_news(data["tw_news"])
    print(f"   美股新聞：{len(data['us_news'])} 則通過過濾")
    print(f"   台股新聞：{len(data['tw_news'])} 則通過過濾")

    from config import BREVO_API_KEY
    from publisher import get_list_id, check_subscriber_count, get_all_subscribers, send_transactional_email

    if not BREVO_API_KEY:
        print("   Brevo API key 尚未設定，只生成本地預覽")
        print("③ AI 生成報告（預設版）...")
        html_report = generate_report(data)
        print("④ 儲存本地預覽...")
        save_local(data["date"], html_report)
        return

    print("③ 取得訂閱者名單...")
    list_id = get_list_id()
    check_subscriber_count(list_id)
    subscribers = get_all_subscribers(list_id)
    print(f"   共 {len(subscribers)} 位訂閱者")

    print("④ 儲存本地預覽（預設版）...")
    default_report = generate_report(data)
    save_local(data["date"], default_report)

    print("⑤ 個人化發送...")
    success_count = 0
    for email in subscribers:
        prefs = get_user_preferences(email)
        us_stocks = prefs.get("us_stocks") or []
        tw_stocks = prefs.get("tw_stocks") or []

        if us_stocks or tw_stocks:
            print(f"   {email} → 個人化報告（美股:{len(us_stocks)}, 台股:{len(tw_stocks)}）")
            html = generate_report(data, us_stocks or None, tw_stocks or None)
        else:
            html = default_report

        ok = send_transactional_email(email, data["date"], html, BREVO_API_KEY)
        if ok:
            success_count += 1
        else:
            print(f"   ❌ 發送失敗：{email}")

    print(f"✅ 今日財經日報發送完成！成功 {success_count}/{len(subscribers)} 位")


if __name__ == "__main__":
    run()
