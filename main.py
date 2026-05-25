import os
import re
import json
import time
import secrets
import logging
import cssutils

cssutils.log.setLevel(logging.CRITICAL)

from datetime import datetime, timezone, timedelta
from data_fetcher import fetch_all
from fake_news_filter import filter_us_news, filter_tw_news
from analyzer import generate_report, generate_weekend_report, generate_monday_report, DIGEST_EMAIL_MAX_HOLDINGS
from publisher import publish_to_brevo


# 週六晨間(TWT)走 weekend recap、週一晨間走 monday outlook、其他平日走預設版
def _is_saturday_tw() -> bool:
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
    return tw_now.weekday() == 5  # Monday=0, Saturday=5


def _is_monday_tw() -> bool:
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
    return tw_now.weekday() == 0


def _report_fn():
    if _is_saturday_tw():
        return generate_weekend_report
    if _is_monday_tw():
        return generate_monday_report
    return generate_report


def _report_variant_label() -> str:
    if _is_saturday_tw():
        return "週末回顧"
    if _is_monday_tw():
        return "週一展望"
    return "預設"


CSS = """
:root { color-scheme: light dark; supported-color-schemes: light dark; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif; background: #f2f2f7; color: #1d1d1f; }
.wrapper { max-width: 620px; margin: 0 auto; background: #fff; }

.header { background: #ffffff; color: #1d1d1f; padding: 26px 24px 20px; border-bottom: 3px solid #6366f1; }
.header-meta { font-size: 11px; color: #6b7280; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 6px; }
.header-tagline { font-size: 12px; color: #6b7280; margin-top: 4px; }

.tldr { background: #fff9f0; border-left: 3px solid #ff9500; margin: 18px 20px 0; padding: 13px 15px; border-radius: 0 10px 10px 0; }
.tldr-title { font-size: 11px; font-weight: 700; color: #c25e00; margin-bottom: 8px; letter-spacing: 0.8px; text-transform: uppercase; }
.tldr ul { list-style: none; }
.tldr ul li { font-size: 14px; color: #3a3a3c; padding: 3px 0 3px 14px; position: relative; line-height: 1.6; }
.tldr ul li::before { content: "→"; position: absolute; left: 0; color: #ff9500; font-weight: 600; font-size: 12px; }

.section-label { font-size: 10px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #8e8e93; padding: 20px 20px 9px; }

.market-summary { padding: 0 20px 14px; font-size: 14px; color: #3a3a3c; line-height: 1.75; }

.news-card { margin: 0 20px 10px; padding: 13px 15px; border: 1px solid #e5e5ea; border-radius: 10px; background: #fff; }
.news-tag { display: inline-block; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 20px; margin-bottom: 7px; letter-spacing: 0.3px; }
.news-tag.verified { background: #e3f9e5; color: #1a6b30; }
.news-tag.single { background: #fff4e0; color: #8a4500; }
.news-headline { font-size: 14px; font-weight: 700; color: #1d1d1f; line-height: 1.45; margin-bottom: 7px; }
.news-why { font-size: 13px; color: #48484a; line-height: 1.55; background: #f2f2f7; padding: 7px 10px; border-radius: 8px; }
.read-more { display: inline-block; margin-top: 8px; font-size: 12px; font-weight: 600; color: #0066cc; text-decoration: none; }
.read-more:hover { text-decoration: underline; }

.news-impact { margin: 9px 0 0; }
.impact-label { display: inline-block; font-size: 10px; font-weight: 700; color: #8e8e93; letter-spacing: 0.5px; margin-right: 6px; }
.impact-stock { display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 20px; margin: 3px 4px 0 0; white-space: nowrap; }
.impact-stock.up { background: #dcfce7; color: #166534; }
.impact-stock.down { background: #ffe4e6; color: #9f1239; }

.stock-card { display: flex; align-items: flex-start; gap: 10px; margin: 0 20px 8px; padding: 11px 13px; border-radius: 10px; background: #f2f2f7; border: 1px solid #e5e5ea; }
.ticker { font-size: 13px; font-weight: 800; color: #0a0a0a; min-width: 56px; padding-top: 2px; font-family: "SF Mono", ui-monospace, monospace; }
.stock-move { font-size: 14px; font-weight: 700; min-width: 76px; padding-top: 2px; }
.stock-move.up { color: #30d158; }
.stock-move.down { color: #ff3b30; }
.stock-comment { font-size: 13px; color: #48484a; line-height: 1.55; flex: 1; }

.macro-list { padding: 0 20px 14px; }
.macro-item { font-size: 14px; color: #3a3a3c; padding: 6px 0; border-bottom: 1px solid #f2f2f7; line-height: 1.65; }

.verdict { margin: 0 20px 12px; padding: 15px; border-radius: 12px; }
.verdict.bullish { background: #f0fdf4; border: 1px solid #bbf7d0; }
.verdict.bearish { background: #fff1f2; border: 1px solid #fecdd3; }
.verdict.neutral { background: #f2f2f7; border: 1px solid #e5e5ea; }
.verdict-emoji { font-size: 24px; margin-bottom: 8px; }
.verdict-text { font-size: 14px; color: #3a3a3c; line-height: 1.75; }

.watch-list { margin: 0 20px 22px; padding: 13px 15px; background: #f2f2f7; border-radius: 10px; }
.watch-title { font-size: 10px; font-weight: 700; color: #8e8e93; margin-bottom: 8px; letter-spacing: 1.2px; text-transform: uppercase; }
.watch-item { font-size: 13px; color: #3a3a3c; padding: 5px 0; border-bottom: 1px solid #e5e5ea; }
.watch-item:last-child { border-bottom: none; }

.indicator-bar { display: flex; gap: 8px; margin: 0 20px 14px; flex-wrap: wrap; }
.indicator-item { flex: 0 0 calc(20% - 7px); min-width: 88px; padding: 11px 10px; background: #f2f2f7; border: 1px solid #e5e5ea; border-radius: 10px; text-align: center; }
.indicator-label { font-size: 9px; font-weight: 700; color: #8e8e93; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 4px; }
.indicator-value { font-size: 16px; font-weight: 800; color: #1d1d1f; }
.indicator-sub { font-size: 10px; color: #8e8e93; margin-top: 2px; }
.indicator-fear { color: #ff3b30; }
.indicator-greed { color: #30d158; }
.indicator-neutral { color: #ff9500; }

.second-order { margin: 0 20px 14px; padding: 13px 15px; background: #f0f0ff; border-left: 3px solid #5e5ce6; border-radius: 0 10px 10px 0; font-size: 13px; color: #3a3a3c; line-height: 1.75; }

.crypto-bar { display: flex; gap: 8px; margin: 0 20px 14px; }
.crypto-item { flex: 1; padding: 12px; background: #f2f2f7; border: 1px solid #e5e5ea; border-radius: 10px; text-align: center; }
.crypto-name { font-size: 10px; font-weight: 700; color: #8e8e93; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.crypto-price { font-size: 17px; font-weight: 800; }
.crypto-price.up { color: #30d158; }
.crypto-price.down { color: #ff3b30; }
.crypto-change { font-size: 11px; color: #8e8e93; margin-top: 2px; }

.sector-bar { padding: 0 20px 14px; }
.sector-item { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f2f2f7; }
.sector-name { font-size: 13px; font-weight: 600; color: #1d1d1f; min-width: 110px; }
.sector-move { font-size: 13px; font-weight: 700; min-width: 68px; }
.sector-move.up { color: #30d158; }
.sector-move.down { color: #ff3b30; }
.sector-comment { font-size: 12px; color: #8e8e93; flex: 1; }

.earnings-list { padding: 0 20px 14px; }
.earnings-item { display: flex; align-items: baseline; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f2f2f7; }
.earnings-ticker { font-size: 13px; font-weight: 800; color: #0a0a0a; min-width: 52px; font-family: "SF Mono", ui-monospace, monospace; }
.earnings-date { font-size: 12px; color: #8e8e93; min-width: 80px; }
.earnings-note { font-size: 13px; color: #48484a; flex: 1; }

.stock-news-item { margin: 0 20px 10px; padding: 13px 15px; border: 1px solid #e0e0ff; border-radius: 10px; background: #f8f8ff; display: flex; gap: 12px; align-items: flex-start; }
.stock-news-ticker { font-size: 12px; font-weight: 800; color: #5e5ce6; min-width: 52px; padding-top: 2px; font-family: "SF Mono", ui-monospace, monospace; }
.stock-news-content { flex: 1; }
.stock-news-headline { font-size: 14px; font-weight: 600; color: #1d1d1f; line-height: 1.4; margin-bottom: 6px; }
.stock-news-impact { font-size: 13px; color: #48484a; background: #ebebff; padding: 6px 10px; border-radius: 8px; line-height: 1.55; }
.stock-news-empty { margin: 0 20px 14px; font-size: 13px; color: #aeaeb2; padding: 8px 0; }

.signal-header { margin: 14px 20px 8px; padding: 14px 16px; background: #eef0ff; border: 1px solid #c7d2fe; border-radius: 12px; }
.signal-header-title { font-size: 11px; font-weight: 700; color: #4338ca; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 3px; }
.signal-header-subtitle { font-size: 11px; color: #6366f1; }
.signal-grid { padding: 0 20px 4px; }
.signal-card { padding: 13px 14px; border-radius: 12px; border: 1px solid; margin-bottom: 10px; }
.signal-card.buy { background: #f0fdf4; border-color: #bbf7d0; }
.signal-card.hold { background: #fffbeb; border-color: #fde68a; }
.signal-card.sell { background: #fff1f2; border-color: #fecdd3; }
.signal-card.wait { background: #f8fafc; border-color: #e2e8f0; }
.signal-card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.signal-day-move { font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
.signal-day-move.up { background: #dcfce7; color: #166534; }
.signal-day-move.down { background: #ffe4e6; color: #9f1239; }
.signal-ticker { font-size: 14px; font-weight: 800; color: #0a0a0a; font-family: "SF Mono", ui-monospace, monospace; }
.signal-score-block { display: flex; align-items: baseline; gap: 1px; margin-left: auto; }
.signal-score { font-size: 20px; font-weight: 900; color: #1d1d1f; line-height: 1; }
.signal-score-label { font-size: 11px; color: #8e8e93; }
.signal-bias { font-size: 10px; font-weight: 800; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.5px; white-space: nowrap; }
.signal-bias.bullish { background: #dcfce7; color: #166534; }
.signal-bias.neutral { background: #fef3c7; color: #92400e; }
.signal-bias.bearish { background: #ffe4e6; color: #9f1239; }
.signal-body { }
.signal-reason { font-size: 13px; color: #3a3a3c; line-height: 1.55; margin-bottom: 9px; }
.signal-battle-plan { background: rgba(0,0,0,0.03); border-radius: 8px; padding: 9px 12px; margin-bottom: 9px; }
.signal-watch { font-size: 12px; color: #4b5563; line-height: 1.55; margin-bottom: 9px; background: rgba(99,102,241,0.07); padding: 7px 11px; border-radius: 8px; }
.battle-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.battle-label { font-size: 10px; font-weight: 700; color: #8e8e93; letter-spacing: 0.5px; min-width: 52px; }
.battle-val { font-size: 13px; font-weight: 700; color: #1d1d1f; }
.battle-val.up { color: #30d158; }
.battle-val.down { color: #ff3b30; }
.signal-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.signal-badge { font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }
.signal-badge.buy { background: #dcfce7; color: #166534; }
.signal-badge.hold { background: #fef3c7; color: #92400e; }
.signal-badge.sell { background: #ffe4e6; color: #9f1239; }
.signal-badge.wait { background: #f1f5f9; color: #475569; }
.signal-confidence { font-size: 11px; color: #6b7280; }
.signal-horizon { font-size: 11px; color: #6b7280; background: #f3f4f6; padding: 2px 8px; border-radius: 20px; }
.signal-disclaimer { margin: 4px 20px 14px; font-size: 10px; color: #aeaeb2; text-align: center; line-height: 1.6; }

.action-board { margin: 16px 20px 6px; }
.action-board-title { font-size: 14px; font-weight: 900; color: #1d1d1f; margin-bottom: 11px; }
.action-item { border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; border: 1px solid; }
.action-item.buy { background: #f0fdf4; border-color: #bbf7d0; }
.action-item.hold { background: #fffbeb; border-color: #fde68a; }
.action-item.sell { background: #fff1f2; border-color: #fecdd3; }
.action-item.wait { background: #f8fafc; border-color: #e2e8f0; }
.action-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.action-name { font-size: 14px; font-weight: 800; color: #1d1d1f; }
.action-move { font-size: 11px; font-weight: 800; padding: 2px 7px; border-radius: 6px; white-space: nowrap; }
.action-move.up { background: #dcfce7; color: #166534; }
.action-move.down { background: #ffe4e6; color: #9f1239; }
.action-verdict { margin-left: auto; font-size: 13px; font-weight: 900; padding: 5px 13px; border-radius: 20px; white-space: nowrap; }
.action-verdict.buy { background: #16a34a; color: #ffffff; }
.action-verdict.hold { background: #f59e0b; color: #ffffff; }
.action-verdict.sell { background: #e11d48; color: #ffffff; }
.action-verdict.wait { background: #94a3b8; color: #ffffff; }
.action-reason { font-size: 13px; color: #48484a; line-height: 1.6; }
.action-legend { font-size: 11px; color: #8e8e93; line-height: 1.8; margin-top: 9px; padding: 10px 13px; background: #f2f2f7; border-radius: 10px; }

.rookie-pick { margin: 0 20px 10px; padding: 14px 16px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; }
.rookie-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 7px; }
.rookie-name { font-size: 15px; font-weight: 800; color: #1d1d1f; }
.rookie-verdict { margin-left: auto; font-size: 12px; font-weight: 900; padding: 4px 12px; border-radius: 20px; background: #16a34a; color: #ffffff; white-space: nowrap; }
.rookie-why { font-size: 13px; color: #3a3a3c; line-height: 1.65; margin-bottom: 8px; }
.rookie-tip { font-size: 12px; color: #6b7280; line-height: 1.6; background: rgba(255,255,255,0.7); padding: 8px 11px; border-radius: 8px; }

.mood-box { margin: 0 20px 14px; padding: 14px 16px; background: #f0f6ff; border: 1px solid #c7d8fe; border-radius: 12px; }
.mood-emoji { font-size: 30px; line-height: 1; margin-bottom: 6px; }
.mood-text { font-size: 14px; color: #1d1d1f; line-height: 1.65; font-weight: 600; }

.rookie-guide { margin: 0 20px 14px; }
.rg-block { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
.rg-head { font-size: 13px; font-weight: 800; color: #1d1d1f; margin-bottom: 9px; }
.rg-step { font-size: 13px; color: #3a3a3c; line-height: 1.7; padding: 4px 0; }
.rg-term { font-size: 12px; color: #48484a; line-height: 1.65; padding: 3px 0; }
.rg-disclaimer { font-size: 10px; color: #aeaeb2; text-align: center; line-height: 1.5; padding: 2px 8px; }

.footer { background: #0a0a0a; color: rgba(255,255,255,0.28); text-align: center; padding: 18px 20px; font-size: 11px; line-height: 2; }
"""


def build_email_html(date: str, html_report: str) -> str:
    full = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>財經日報 {date}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td width="50" valign="middle" style="padding-right:14px;">
          <img src="https://marketdaily.ai/logo-icon.svg" width="46" height="46" alt="MD" style="display:block;border-radius:12px;">
        </td>
        <td valign="middle">
          <div style="font-size:20px;font-weight:800;color:#312e81;letter-spacing:-0.5px;line-height:1.2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">MarketDaily</div>
          <div style="font-size:10px;color:#6366f1;letter-spacing:3px;text-transform:uppercase;margin-top:3px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">AI 財經日報</div>
        </td>
      </tr>
    </table>
    <div class="header-meta">{date}</div>
    <div class="header-tagline">AI 精選 · 假訊息過濾 · 美股 + 台股</div>
  </div>
  {html_report}

  <div style="margin:20px 20px 4px;background:#f0f0ff;border:1px solid #c7d2fe;border-radius:12px;padding:18px 20px;text-align:center;">
    <p style="font-size:13px;font-weight:800;color:#4338ca;margin:0 0 6px;">📊 客製化你的每日日報</p>
    <p style="font-size:12px;color:#6b7280;line-height:1.7;margin:0 0 14px;">前往個人專區選擇你追蹤的美股 / 台股，<br>AI 每天只幫你分析你在乎的持倉動態。</p>
    <a href="https://marketdaily.ai/dashboard.html" style="display:inline-block;background:#6366f1;color:#fff;font-size:13px;font-weight:700;padding:10px 24px;border-radius:8px;text-decoration:none;">⚙️ 前往設定我的股票偏好 →</a>
  </div>

  <div class="footer">
    財經日報 · AI 精選 · 假訊息過濾<br>
    ✅ 多源確認 = 2個以上白名單媒體報導 &nbsp;|&nbsp; ⚠️ 單一來源 = 請自行查證<br>
    本報告為 AI 生成，僅供參考，不構成投資建議<br><br>
    <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">🌐 marketdaily.ai</a> &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/dashboard.html" style="color:#a5b4fc;text-decoration:none;">⚙️ 我的專區</a>
  </div>
</div>
</body>
</html>"""
    try:
        from premailer import transform
        return transform(full, remove_classes=False, preserve_internal_links=True)
    except Exception:
        return full


def save_local(date: str, html_report: str):
    os.makedirs("output", exist_ok=True)
    os.makedirs("docs/output", exist_ok=True)
    path = f"output/digest_{date}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>財經日報 {date}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td width="50" valign="middle" style="padding-right:14px;">
          <img src="https://marketdaily.ai/logo-icon.svg" width="46" height="46" alt="MD" style="display:block;border-radius:12px;">
        </td>
        <td valign="middle">
          <div style="font-size:20px;font-weight:800;color:#312e81;letter-spacing:-0.5px;line-height:1.2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">MarketDaily</div>
          <div style="font-size:10px;color:#6366f1;letter-spacing:3px;text-transform:uppercase;margin-top:3px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">AI 財經日報</div>
        </td>
      </tr>
    </table>
    <div class="header-meta">{date}</div>
    <div class="header-tagline">AI 精選 · 假訊息過濾 · 美股 + 台股</div>
  </div>
  {html_report}

  <div style="margin:20px 20px 4px;background:#f0f0ff;border:1px solid #c7d2fe;border-radius:12px;padding:18px 20px;text-align:center;">
    <p style="font-size:13px;font-weight:800;color:#4338ca;margin:0 0 6px;">📊 客製化你的每日日報</p>
    <p style="font-size:12px;color:#6b7280;line-height:1.7;margin:0 0 14px;">前往個人專區選擇你追蹤的美股 / 台股，<br>AI 每天只幫你分析你在乎的持倉動態。</p>
    <a href="https://marketdaily.ai/dashboard.html" style="display:inline-block;background:#6366f1;color:#fff;font-size:13px;font-weight:700;padding:10px 24px;border-radius:8px;text-decoration:none;">⚙️ 前往設定我的股票偏好 →</a>
  </div>

  <div class="footer">
    財經日報 · AI 精選 · 假訊息過濾<br>
    ✅ 多源確認 = 2個以上白名單媒體報導 &nbsp;|&nbsp; ⚠️ 單一來源 = 請自行查證<br>
    本報告為 AI 生成，僅供參考，不構成投資建議<br><br>
    <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">🌐 marketdaily.ai</a> &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/dashboard.html" style="color:#a5b4fc;text-decoration:none;">⚙️ 我的專區</a>
  </div>
</div>
</body>
</html>""")
    import shutil
    shutil.copy(path, f"docs/output/digest_{date}.html")
    _update_manifest(date)
    print(f"   本地預覽已儲存：{path}")
    return path


def _update_manifest(date: str):
    manifest_path = "docs/output/manifest.json"
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        manifest = {"dates": []}
    if date not in manifest.get("dates", []):
        manifest.setdefault("dates", []).append(date)
        manifest["dates"].sort(reverse=True)
        manifest["dates"] = manifest["dates"][:30]
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)


WORKER_URL = "https://marketdaily-webhook.delvin-12345678.workers.dev"


def _extract_sentiment(inner_html: str) -> str:
    m = re.search(r'class="verdict\s+(bullish|bearish|neutral)"', inner_html)
    return m.group(1) if m else "neutral"


def _inject_ai_banner(inner_html: str, date: str) -> str:
    """Generate and inject a sentiment banner image. Non-fatal if Muapi unavailable."""
    try:
        from image_generator import generate_digest_banner, inject_banner_into_html
        sentiment = _extract_sentiment(inner_html)
        image_url = generate_digest_banner(sentiment, date)
        if image_url:
            return inject_banner_into_html(inner_html, image_url)
    except Exception as e:
        print(f"  [Banner] 略過（{e}）")
    return inner_html


def get_user_preferences(email: str) -> dict:
    """讀取用戶在「我的專區」設定的持倉偏好。失敗會重試，確保日報依個人設定客製化。"""
    import requests
    for attempt in range(3):
        try:
            res = requests.post(
                f"{WORKER_URL}/get-preferences",
                json={"email": email},
                timeout=10
            )
            if res.ok:
                d = res.json() or {}
                return {
                    "us_stocks": d.get("us_stocks") or [],
                    "tw_stocks": d.get("tw_stocks") or [],
                    "plan": d.get("plan") or "free",
                }
        except Exception:
            pass
        if attempt < 2:
            time.sleep(2)
    print(f"   ⚠️ 無法取得 {email} 的偏好設定（重試 3 次後仍失敗），本次改用預設版")
    return {"us_stocks": [], "tw_stocks": [], "plan": "free"}


def save_hosted_digest(html: str, date: str = "") -> str:
    """把完整日報 HTML 上傳到 Worker KV，回傳可分享的網頁連結；失敗回 None。
    date 若有值會同步寫進 digest_idx:{date}:{token},供 track-record builder 列舉所有
    當日個人化日報、算進跨用戶總勝率。"""
    import requests
    token = secrets.token_urlsafe(12)
    try:
        payload = {"token": token, "html": html}
        if date:
            payload["date"] = date
        res = requests.post(
            f"{WORKER_URL}/save-digest",
            json=payload,
            timeout=20,
        )
        if res.ok:
            return res.json().get("url")
        print(f"   ⚠️ 網頁版上傳失敗（HTTP {res.status_code}）")
    except Exception as e:
        print(f"   ⚠️ 網頁版上傳失敗（{e}）")
    return None


def _web_view_banner(url: str, total_holdings: int = 0, shown: int = 0) -> str:
    """email 頂部的「看網頁完整版」按鈕。"""
    note = ""
    if total_holdings and shown and total_holdings > shown:
        note = (
            '<div style="font-size:11px;color:#6b7280;margin-top:5px;line-height:1.6;">'
            f'這封信顯示變動最大的 {shown} 支持倉；完整 {total_holdings} 支請看網頁版</div>'
        )
    return (
        '<div style="margin:14px 20px 0;padding:13px 16px;background:#eef0ff;'
        'border:1px solid #c7d2fe;border-radius:12px;text-align:center;">'
        f'<a href="{url}" style="font-size:13px;font-weight:800;color:#4338ca;'
        'text-decoration:none;">📱 在網頁上看完整日報（不會被截斷、可分享）→</a>'
        f'{note}</div>'
    )


def _newbie_guide_footer() -> str:
    """新手等級的訂閱者:日報底部附新手教學連結。"""
    return (
        '<div style="margin:18px 20px 4px;padding:14px 16px;background:#f6f7fb;'
        'border:1px solid #e2e8f0;border-radius:12px;text-align:center;">'
        '<div style="font-size:13px;color:#444;line-height:1.7;">'
        '剛開始用 MarketDaily？不熟悉怎麼操作？</div>'
        '<a href="https://marketdaily.ai/guide.html" style="display:inline-block;'
        'margin-top:6px;font-size:13px;font-weight:800;color:#4338ca;'
        'text-decoration:none;">📖 看 3 分鐘新手教學 →</a>'
        '</div>'
    )


def run():
    from config import BREVO_API_KEY
    from publisher import get_list_id, check_subscriber_count, get_all_subscribers, send_transactional_email

    if not BREVO_API_KEY:
        print("① 抓取市場數據與新聞...")
        data = fetch_all()
        print("② 過濾假訊息...")
        data["us_news"] = filter_us_news(data["us_news"])
        data["tw_news"] = filter_tw_news(data["tw_news"])
        print(f"③ AI 生成報告（{_report_variant_label()}版）...")
        inner = _report_fn()(data)
        print("④ 生成 AI 市場情緒 Banner...")
        inner = _inject_ai_banner(inner, data["date"])
        print("⑤ 儲存本地預覽...")
        save_local(data["date"], inner)
        return

    print("① 取得訂閱者名單與持倉偏好...")
    list_id = get_list_id()
    check_subscriber_count(list_id)
    subscribers = get_all_subscribers(list_id)
    print(f"   共 {len(subscribers)} 位訂閱者")

    subscriber_prefs = {}
    all_us_extra, all_tw_extra = set(), set()
    for email in subscribers:
        prefs = get_user_preferences(email)
        subscriber_prefs[email] = prefs
        for s in prefs.get("us_stocks") or []:
            all_us_extra.add(s)
        for s in prefs.get("tw_stocks") or []:
            all_tw_extra.add(s)

    print(f"② 抓取市場數據（含用戶個股：美股 +{len(all_us_extra)}，台股 +{len(all_tw_extra)}）...")
    data = fetch_all(
        extra_us_stocks=list(all_us_extra) if all_us_extra else None,
        extra_tw_stocks=list(all_tw_extra) if all_tw_extra else None
    )

    print("③ 過濾假訊息...")
    data["us_news"] = filter_us_news(data["us_news"])
    data["tw_news"] = filter_tw_news(data["tw_news"])
    print(f"   美股新聞：{len(data['us_news'])} 則通過過濾")
    print(f"   台股新聞：{len(data['tw_news'])} 則通過過濾")

    variant_label = _report_variant_label()
    print(f"④ 生成 AI 市場情緒 Banner（{variant_label}版）...")
    default_report = _report_fn()(data)
    default_report = _inject_ai_banner(default_report, data["date"])
    print("⑤ 儲存本地預覽（預設版）...")
    save_local(data["date"], default_report)

    print("⑥ 上傳預設版網頁...")
    default_web_url = save_hosted_digest(build_email_html(data["date"], default_report), data["date"])

    print("⑦ 個人化發送...")
    from analyzer import get_personalized_subject
    from experience import experience_tier
    success_count = 0
    ai_calls = 0
    tier_counts = {"新手": 0, "一般": 0, "老手": 0}
    for email in subscribers:
        prefs = subscriber_prefs[email]
        us_stocks = prefs.get("us_stocks") or []
        tw_stocks = prefs.get("tw_stocks") or []
        total = len(us_stocks) + len(tw_stocks)
        exp_score, exp_tier = experience_tier(len(us_stocks), len(tw_stocks), prefs.get("plan"))
        tier_counts[exp_tier] = tier_counts.get(exp_tier, 0) + 1

        subject = None
        web_url = default_web_url
        shown = total
        if us_stocks or tw_stocks:
            print(f"   {email} → 個人化（美股:{len(us_stocks)}, 台股:{len(tw_stocks)}）· {exp_tier}（{exp_score}）")
            try:
                if ai_calls > 0:
                    time.sleep(5)  # 輕度間隔，避免觸發 Gemini 免費層每分鐘上限
                full_inner = _report_fn()(data, us_stocks or None, tw_stocks or None)
                ai_calls += 1
                full_inner = _inject_ai_banner(full_inner, data["date"])
                # 完整版（含全部持倉）上傳網頁
                web_url = save_hosted_digest(build_email_html(data["date"], full_inner), data["date"]) or default_web_url
                # email 版：持倉超過上限時縮減，避免被 Gmail 截斷
                if total > DIGEST_EMAIL_MAX_HOLDINGS:
                    time.sleep(5)
                    inner = _report_fn()(data, us_stocks or None, tw_stocks or None, email_safe=True)
                    ai_calls += 1
                    inner = _inject_ai_banner(inner, data["date"])
                    shown = DIGEST_EMAIL_MAX_HOLDINGS
                else:
                    inner = full_inner
                subject = get_personalized_subject(data, us_stocks, tw_stocks, data["date"])
            except Exception as e:
                print(f"   ⚠️ {email} 個人化失敗，改用預設版（{e}）")
                inner = default_report
                subject = None
                web_url = default_web_url
                shown = total
        else:
            inner = default_report

        if web_url:
            inner = _web_view_banner(web_url, total, shown) + inner
        if exp_tier == "新手":
            inner = inner + _newbie_guide_footer()

        try:
            html = build_email_html(data["date"], inner)
            ok = send_transactional_email(email, data["date"], html, BREVO_API_KEY, subject=subject)
        except Exception as e:
            ok = False
            print(f"   ❌ 發送異常：{email}（{e}）")
        if ok:
            success_count += 1
        else:
            print(f"   ❌ 發送失敗：{email}")

    print(f"✅ 今日財經日報發送完成！成功 {success_count}/{len(subscribers)} 位")
    print(f"   經驗分布 → 🌱新手 {tier_counts['新手']} · 📈一般 {tier_counts['一般']} · 🎯老手 {tier_counts['老手']}")


if __name__ == "__main__":
    run()
