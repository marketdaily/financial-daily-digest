import os
import re
import json
import time
import secrets
import logging
import cssutils

cssutils.log.setLevel(logging.CRITICAL)

from datetime import datetime, timezone, timedelta
from config_loader import WORKER_URL
from data_fetcher import fetch_all
from fake_news_filter import filter_us_news, filter_tw_news
from analyzer import generate_report, generate_weekend_report, generate_monday_report, DIGEST_EMAIL_MAX_HOLDINGS


def _resolve_market() -> str:
    """雙班次:tw=早 7:00 台股盤前 / us=晚 20:00 美股盤前 / both=合併(預設,手動 fallback)。
    來源優先序:CLI --market=xx > 環境變數 MARKET > both。"""
    import sys as __sys
    for a in __sys.argv:
        if a.startswith("--market="):
            v = a.split("=", 1)[1].strip().lower()
            if v in ("tw", "us", "both"):
                return v
    v = (os.environ.get("MARKET") or "both").strip().lower()
    return v if v in ("tw", "us", "both") else "both"


MARKET = _resolve_market()


# 週六晨間(TWT)走 weekend recap、週一晨間走 monday outlook、其他平日走預設版
def _is_saturday_tw() -> bool:
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
    return tw_now.weekday() == 5  # Monday=0, Saturday=5


def _is_monday_tw() -> bool:
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
    return tw_now.weekday() == 0


def _report_fn():
    # us 晚報(美股盤前)一律走標準版:週末/週一框架是早報台股盤前語境,
    # 美股當晚是自己的正常交易 session,不需要「週末 gap」那套。
    if MARKET == "us":
        return generate_report
    if _is_saturday_tw():
        return generate_weekend_report
    if _is_monday_tw():
        return generate_monday_report
    return generate_report


def _report_variant_label() -> str:
    if MARKET == "us":
        return "美股晚報"
    if MARKET == "tw":
        if _is_saturday_tw():
            return "台股週末回顧"
        if _is_monday_tw():
            return "台股週一展望"
        return "台股早報"
    if _is_saturday_tw():
        return "週末回顧"
    if _is_monday_tw():
        return "週一展望"
    return "預設"


# 2026-07-04 修復:email_digest.css 曾有一個 0x11 控制字元(歷史 bug:Python 把
# content:"\2192" 的 \21 吃成八進位跳脫),讓 premailer 的 lxml 一直 ValueError →
# build_email_html 靜默走「不內聯」路徑,premailer 從未真的內聯過任何一封信。
# 已改回字面箭頭字元 "→"(同檔 .tldr ul li::before 既有寫法)修復,premailer 現在正常運作;
# 同時修 digest_audit.undefined_css_class 誤判(見 digest_audit.py base_css 參數) ——
# premailer 會把成功內聯的 class 規則從 <style> 移除,審查需比對原始樣板 CSS 才不會誤判。
_CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "templates", "email_digest.css")
with open(_CSS_PATH, encoding="utf-8") as _f:
    CSS = _f.read()

# 2026-07-06 週一版事故防線:LLM(不分模型)會把「沿用平日 CSS class」自由發揮成近似名
# (news-title/summary-item/watch-date…),樣板 CSS 沒這些規則 → 區塊無樣式,
# undefined_css_class HIGH audit 全員命中 → retry 也同病 → 12/12 打成 deterministic fallback。
# 這裡在 premailer 內聯【之前】做確定性修復:已知近似名對映回既有 class(恢復原本想要的樣式),
# 其餘未定義 class 直接拿掉(CSS 本來就沒對應規則,拿掉是視覺 no-op)。audit 檢查保留當最後防線。
_CSS_CLASSES = frozenset(re.findall(r"\.([A-Za-z_][\w-]*)", CSS))
_CLASS_ALIASES = {
    "news-title": "news-headline",
    "news-content": "news-why",
    "impact-stocks": "news-impact",
    "summary-item": "market-summary-item",
    "summary-label": "market-summary-label",
    "summary-content": "market-summary-note",
    "summary-value": "market-summary-value",
    "watch-date": "watch-list-date",
    "watch-event": "watch-list-event",
    "watch-impact": "watch-list-impact",
    "verdict-playbook": "verdict-content",
    "playbook-title": "verdict-title",
}
_CLASS_ATTR_RE = re.compile(r'class\s*=\s*"([^"]*)"')


def _repair_undefined_classes(html_report: str) -> str:
    def _fix(m):
        kept = [_CLASS_ALIASES.get(t, t) for t in m.group(1).split()]
        return 'class="' + " ".join(t for t in kept if t in _CSS_CLASSES) + '"'
    return _CLASS_ATTR_RE.sub(_fix, html_report)


# 日報 inner 內容合法會用到的標籤白名單。凡是 < 後面不接白名單標籤(開/閉)、
# 也不是註解/DOCTYPE(<!) 的,一律視為 LLM 文字裡的裸「小於號」(如「價<MA20」「殖利率<3%」),
# 轉成 &lt; 才不會被瀏覽器當標籤吞掉→整張卡之後的 markup 連環被喀掉(反覆咬人的老 bug)。
_ALLOWED_INNER_TAGS = (
    "div|span|a|b|i|u|s|em|strong|br|hr|p|small|sup|sub|mark|"
    "ul|ol|li|table|thead|tbody|tfoot|tr|td|th|img|h[1-6]|font|"
    "style|section|article|header|footer|figure|figcaption|caption|colgroup|col"
)
_STRAY_LT_RE = re.compile(r"<(?!/?(?:" + _ALLOWED_INNER_TAGS + r")(?=[\s/>])|!)")


def _escape_stray_lt(html_report: str) -> str:
    """把 inner 報告文字裡的裸 < 跳脫(白名單標籤與註解不動),防止 LLM 生成的
    「價<MA20」之類把後續卡片 HTML 吃掉。只處理 inner,不碰外層固定 wrapper/CSS。"""
    return _STRAY_LT_RE.sub("&lt;", html_report)


def _fix_closed_market_wording(date: str, html_report: str) -> str:
    """休市日措辭確定性防線(2026-07-10 颱風停市事故):台股休市日不可殘留
    「今早 9:00 開盤」類字眼,美股休市夜不可殘留「今晚開盤」。不依賴 LLM 聽話,
    audit 的 tw_holiday_open_tense/us_holiday_tonight_tense 是這層的獨立驗證者。
    開市日 no-op,_market_status 失敗 fail-open 維持原文。"""
    try:
        from analyzer import _market_status
        mkt = _market_status(date)
    except Exception:
        return html_report
    if mkt.get("tw_will_open_today") is False:
        html_report = re.sub(r"今早\s*9\s*[:：]?\s*00\s*開盤", "下一個交易日開盤", html_report)
        html_report = re.sub(r"今早開盤", "下一個交易日開盤", html_report)
        html_report = re.sub(r"今日早盤", "下一個交易日早盤", html_report)
    if mkt.get("us_will_open_tonight") is False:
        nxt = mkt.get("us_next_trading_date") or "下個交易日"
        html_report = re.sub(r"今晚美股開盤", f"美股 {nxt} 開盤", html_report)
        html_report = re.sub(r"今晚開盤", f"{nxt} 開盤", html_report)
    return html_report


# signal-card 區塊切分(同 analyzer._pp_* 系列的邊界慣例:下一張卡 / disclaimer / section-label / 結尾)
_SIGNAL_CARD_BLOCK_RE = re.compile(
    r'<div class="signal-card[ "].*?'
    r'(?=<div class="signal-card[ "]|<div class="signal-disclaimer|<div class="section-label|$)',
    re.S)


def _fix_tw_morning_action_wording(date: str, html_report: str) -> str:
    """台股早報動作窗口確定性防線(audit#15 tw_morning_action_missing 根治,2026-07-17)。
    prompt 已要求台股卡講「今早 9:00 開盤後」動作,但 LLM 遵從隨機(07-13/17 實鍋 5 封),
    且 med severity 不觸發 retry → 不依賴 LLM 聽話:
    ①台股卡裡「明日/明天開盤」= 時序錯亂(這封信在今早開盤前寄出)→ 改寫「今早開盤」
    ②整批台股卡皆無晨間窗口字眼 → 第一張帶 signal-reason 的台股卡開頭補「今早 9:00 開盤後:」。
    只在台股開盤日的非 us 班次生效;美股卡(h-mark 首字非數字)零觸碰;已合規日報 no-op。
    台股判別=首字數字(同 analyzer 慣例):00981A 這類帶字母尾碼的主動式 ETF 也是台股卡,
    07-22/07-27 兩鍋皆因舊 `\\d+` 全數字判別把它誤當美股卡跳過(hfks996 實鍋)。
    audit#15 是這層的獨立驗證者(TW_MORNING_ACTION_RE 兩邊共用,不會 guard 過了 audit 卻紅)。"""
    if MARKET == "us":
        return html_report
    try:
        from analyzer import _market_status
        from digest_audit import TW_MORNING_ACTION_RE
        mkt = _market_status(date)
    except Exception:
        return html_report
    if not mkt.get("tw_will_open_today"):
        return html_report

    def _tw_blocks(html: str):
        return [m for m in _SIGNAL_CARD_BLOCK_RE.finditer(html)
                if re.search(r"<!--h:\d[A-Z0-9.]*-->", m.group(0))]

    # ① 時序錯字修正(從後往前替換,前面 match 的 offset 不失效)。
    #    只修「整塊沒有任何晨間窗口字眼」的卡(驗證者第14案 F1):已合規卡裡的
    #    「明日開盤前重新評估」是合法的收盤後前瞻,不可改寫製造新時序錯亂。
    #    pattern 要求 明+日/天/早(F2:涵蓋「明早開盤」),不吃「說明開盤」這類複合詞。
    for m in reversed(_tw_blocks(html_report)):
        blk = m.group(0)
        if TW_MORNING_ACTION_RE.search(blk):
            continue
        fixed = re.sub(r"明(?:[日天]\s*(?:一早\s*)?|早)開盤", "今早開盤", blk)
        fixed = re.sub(r"明[日天]\s*早盤", "今日早盤", fixed)
        if fixed != blk:
            html_report = html_report[:m.start()] + fixed + html_report[m.end():]

    # ② 樓地板保證:整批台股卡仍無晨間窗口 → 首張有 reason 的台股卡補開場
    blocks = _tw_blocks(html_report)
    if blocks and not any(TW_MORNING_ACTION_RE.search(m.group(0)) for m in blocks):
        for m in blocks:
            injected = re.sub(r'(<div class="signal-reason"[^>]*>)',
                              r"\g<1>今早 9:00 開盤後:", m.group(0), count=1)
            if injected != m.group(0):
                html_report = html_report[:m.start()] + injected + html_report[m.end():]
                break
    return html_report


def _fix_us_tonight_action_wording(date: str, html_report: str) -> str:
    """美股晚報動作窗口確定性防線(audit#14 us_tonight_action_missing 根治,2026-07-29)。
    #15 台股版(07-17)的對稱缺口:07-27 起配額枯竭掉弱模,med fail 不觸發 retry,
    prompt 遵從隨機 → 三天 11/7/11 位失分全是這條。鏡射 #15 兩層修,不依賴 LLM 聽話:
    ①美股卡「明晚/明日晚間開盤」= 時序錯亂(晚報在今晚開盤前寄出)→ 改寫「今晚開盤」;
      只修整塊沒有任何今晚/盤後字眼的卡(已合規卡裡的前瞻句不可改寫製造新錯亂,同 #15 F1)
    ②全部 signal-card 皆無「今晚/盤後」→ 首張帶 signal-reason 的美股卡開頭補
      「今晚美股開盤後:」(判準與 audit#14 完全同字眼,audit 是本層的獨立驗證者)。
    只在 us_will_open_tonight 的非 tw 班次生效;台股卡(h-mark 首字數字)零觸碰;
    美股卡判別=h-mark 首字字母(AAPL/TSLA…),與 #15 的台股判別互補。"""
    if MARKET == "tw":
        return html_report
    try:
        from analyzer import _market_status
        mkt = _market_status(date)
    except Exception:
        return html_report
    if not mkt.get("us_will_open_tonight"):
        return html_report

    def _us_blocks(html: str):
        return [m for m in _SIGNAL_CARD_BLOCK_RE.finditer(html)
                if re.search(r"<!--h:[A-Za-z]", m.group(0))]

    # ① 時序錯字修正(從後往前替換;只修無合規字眼的卡)
    for m in reversed(_us_blocks(html_report)):
        blk = m.group(0)
        if "今晚" in blk or "盤後" in blk:
            continue
        fixed = re.sub(r"明(?:[日天]\s*)?晚(?:間|上)?\s*開盤", "今晚開盤", blk)
        if fixed != blk:
            html_report = html_report[:m.start()] + fixed + html_report[m.end():]

    # ② 樓地板保證:判準鏡射 audit#14(全卡 joined 無「今晚」且無「盤後」才注入)
    all_cards = _SIGNAL_CARD_BLOCK_RE.findall(html_report)
    joined = " ".join(all_cards)
    us_blocks = _us_blocks(html_report)
    if us_blocks and "今晚" not in joined and "盤後" not in joined:
        for m in us_blocks:
            injected = re.sub(r'(<div class="signal-reason"[^>]*>)',
                              r"\g<1>今晚美股開盤後:", m.group(0), count=1)
            if injected != m.group(0):
                html_report = html_report[:m.start()] + injected + html_report[m.end():]
                break
    return html_report


def render_email_shell(date: str, html_report: str) -> str:
    """Email/本地存檔共用的完整 HTML 骨架(原 build_email_html 與 save_local 各持
    一份逐字節相同的複本,2026-07-03 P3 收斂)。<style> 內容 byte 級凍結於 golden。"""
    html_report = _fix_closed_market_wording(date, html_report)
    html_report = _fix_tw_morning_action_wording(date, html_report)
    html_report = _fix_us_tonight_action_wording(date, html_report)
    # 週六早報=週末回顧,媒體產線週末不產語音(video_brief_runner 週末防線)→
    # header 不放「3 分鐘語音版」承諾,footer 連結拿掉 ?date= 改聽最新一集,
    # 否則 audio.html?date=週六 會顯示等不到的「生成中」。
    weekend_no_audio = MARKET != "us" and _is_saturday_tw()
    audio_qs = "" if weekend_no_audio else f"?date={date}&amp;ed={'us' if MARKET == 'us' else 'tw'}"
    audio_header_line = "" if weekend_no_audio else f'''<div style="margin-top:10px;font-size:11px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"><a href="https://marketdaily.ai/audio.html{audio_qs}" style="color:#6366f1;text-decoration:none;font-weight:700;">🎙 沒空看?3 分鐘語音版(免費) →</a></div>'''
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
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
    {audio_header_line}
  </div>
  {html_report}

  <div style="margin:20px 12px 4px;background:#f0f0ff;border:1px solid #c7d2fe;border-radius:12px;padding:18px 20px;text-align:center;">
    <p style="font-size:13px;font-weight:800;color:#4338ca;margin:0 0 6px;">📊 客製化你的每日日報</p>
    <p style="font-size:12px;color:#6b7280;line-height:1.7;margin:0 0 14px;">前往個人專區選擇你追蹤的美股 / 台股，<br>AI 每天只幫你分析你在乎的持倉動態。</p>
    <a href="https://marketdaily.ai/dashboard.html" style="display:inline-block;background:#6366f1;color:#fff;font-size:13px;font-weight:700;padding:10px 24px;border-radius:8px;text-decoration:none;">⚙️ 前往設定我的股票偏好 →</a>
  </div>

  <div class="footer">
    財經日報 · AI 精選 · 假訊息過濾<br>
    ✅ 多源確認 = 2個以上白名單媒體報導 &nbsp;|&nbsp; ⚠️ 單一來源 = 請自行查證<br>
    本報告為 AI 生成之一般性資訊整理，僅供參考，不構成投資建議；MarketDaily 非證券投資顧問事業<br>所有分析內容對免費與付費用戶完全相同，不因付費而異；投資有風險，決策請自行判斷<br><br>
    <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">🌐 marketdaily.ai</a> &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/dashboard.html" style="color:#6366f1;text-decoration:none;">⚙️ 我的專區</a> &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/audio.html{audio_qs}" style="color:#6366f1;text-decoration:none;">🎙 語音快報</a>
  </div>
</div>
</body>
</html>"""


def build_email_html(date: str, html_report: str) -> str:
    html_report = _escape_stray_lt(html_report)
    html_report = _repair_undefined_classes(html_report)
    full = render_email_shell(date, html_report)
    try:
        from premailer import transform
        return transform(full, remove_classes=False, preserve_internal_links=True)
    except Exception:
        return full


def save_local(date: str, html_report: str, suffix: str = ""):
    # suffix:us 晚報用 "_us" → 寫 digest_<date>_us.html,不進 manifest、
    # 也不會被 track-record 的 digest_<date>.html 嚴格 regex 掃到(避免雙算/clobber 早報公版)。
    os.makedirs("output", exist_ok=True)
    os.makedirs("docs/output", exist_ok=True)
    path = f"output/digest_{date}{suffix}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_email_shell(date, html_report))
    import shutil
    shutil.copy(path, f"docs/output/digest_{date}{suffix}.html")
    if not suffix:
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


def _inject_political_signals(inner_html: str, data: dict, user_holdings=None) -> str:
    """把政壇市場訊號(Grok 抓的政治人物 X 貼文)組成卡片區塊,插在報告最前面。
    純 deterministic 組裝(不經 LLM),缺資料時原樣返回 —— 不影響零錯誤防線。"""
    import html as _html
    signals = (data or {}).get("political_signals") or []
    if not signals:
        return inner_html
    try:
        names = (data or {}).get("tw_names_all") or {}
        held = set(user_holdings or [])
        dir_meta = {
            "bullish": ("📈 偏多", "#1a6b30", "#e3f9e5"),
            "bearish": ("📉 偏空", "#b3261e", "#fde8e6"),
            "mixed":   ("↔️ 分歧", "#8a4500", "#fff4e0"),
        }
        cards = []
        for s in signals:
            label, color, bg = dir_meta.get(s.get("direction"), dir_meta["mixed"])
            tags = []
            for t in s.get("affected") or []:
                disp = f"{t} {names[t]}" if t in names else t
                star = "⭐" if t in held else ""
                tags.append(
                    f'<span style="display:inline-block;font-size:11px;font-weight:700;'
                    f'color:#3730a3;background:#eef2ff;border-radius:6px;padding:2px 7px;'
                    f'margin:2px 4px 0 0;">{star}{_html.escape(disp)}</span>'
                )
            tags_html = "".join(tags)
            who = _html.escape(s.get("name_zh") or s.get("handle") or "政治人物")
            headline = _html.escape(s.get("headline_zh") or "")
            impact = _html.escape(s.get("impact_zh") or "")
            url = _html.escape(s.get("post_url") or "https://x.com")
            cards.append(
                '<div class="news-card" style="border-color:#dfe3ff;">'
                f'<span class="news-tag" style="background:{bg};color:{color};">🏛️ {who}｜{label}</span>'
                f'<div class="news-headline">{headline}</div>'
                + (f'<div class="news-why">{impact}</div>' if impact else "")
                + (f'<div style="margin-top:8px;">{tags_html}</div>' if tags_html else "")
                + f'<div style="margin-top:8px;font-size:11px;"><a href="{url}" '
                'style="color:#5e5ce6;text-decoration:none;">🔗 看原文貼文 →</a></div>'
                '</div>'
            )
        block = (
            '<div class="section-label">🏛️ 政壇市場訊號</div>'
            '<div style="margin:0 12px 6px;font-size:12px;color:#8a8a8e;">'
            '川普 / 白宮 / 財政部 / Fed / 商務部等的即時發言,可能牽動關稅、利率與你的持股。</div>'
            + "".join(cards)
        )
        marker = '<div class="section-label">'
        idx = inner_html.find(marker)
        if idx == -1:
            return block + inner_html
        return inner_html[:idx] + block + inner_html[idx:]
    except Exception as e:
        print(f"  [政壇訊號] 注入略過（{e}）")
        return inner_html


def _inject_intel_signals(inner_html: str, data: dict, user_holdings=None) -> str:
    """把信息差引擎夜間簡報(法人/融資融券/借券/集保大戶/法說會/美股分析師+內部人)裡跟這位
    用戶「實際持股」相符的訊號組成卡片,插在報告最前面。純 deterministic 查表(不經 LLM),
    只顯示紅/黃兩種行動級訊號(plain 略過);沒有持股命中就原樣返回 —— 不影響零錯誤防線。"""
    import html as _html
    by_code = (data or {}).get("intel_signals") or {}
    held = list(dict.fromkeys([str(h).upper() for h in (user_holdings or []) if h]))
    if not by_code or not held:
        return inner_html
    try:
        names = (data or {}).get("tw_names_all") or {}
        rows = []
        for tk in held:
            entries = [e for e in (by_code.get(tk) or []) if e.get("level") in ("red", "yellow")]
            if not entries:
                continue
            # 同一來源(如美股內部人在 2 天窗口內多筆例行申報)只留最嚴重一則,
            # 避免重訊股每天洗版式重複——一個 source 一句話,信息密度優先於覆蓋率
            best_by_source = {}
            for e in entries:
                src = e.get("source") or ""
                cur = best_by_source.get(src)
                if cur is None or (e["level"] == "red" and cur["level"] != "red"):
                    best_by_source[src] = e
            entries = list(best_by_source.values())
            disp = f"{tk} {names[tk]}" if tk in names else tk
            for e in entries:
                color, bg = ("#b3261e", "#fde8e6") if e["level"] == "red" else ("#8a4500", "#fff4e0")
                dot = "🔴" if e["level"] == "red" else "🟡"
                sig = _html.escape(str(e.get("signal") or ""))
                rows.append(
                    '<div class="news-card" style="border-color:#dfe3ff;">'
                    f'<span class="news-tag" style="background:{bg};color:{color};">{dot} {_html.escape(disp)}</span>'
                    f'<div class="news-headline">{sig}</div>'
                    '</div>'
                )
        if not rows:
            return inner_html
        block = (
            '<div class="section-label">🔎 你的持股籌碼情報</div>'
            '<div style="margin:0 12px 6px;font-size:12px;color:#8a8a8e;">'
            '法人動向 / 融資融券 / 借券賣出 / 集保大戶 / 法說會排程等信息差引擎夜間巡邏訊號,'
            '只列出你有持股的標的。</div>'
            + "".join(rows)
        )
        marker = '<div class="section-label">'
        idx = inner_html.find(marker)
        if idx == -1:
            return block + inner_html
        return inner_html[:idx] + block + inner_html[idx:]
    except Exception as e:
        print(f"  [持股籌碼情報] 注入略過（{e}）")
        return inner_html


def get_user_preferences(email: str) -> dict:
    """讀取用戶在「我的專區」設定的持倉偏好。失敗會重試，確保日報依個人設定客製化。
    server-to-server 帶 INTERNAL_TOKEN 跳過 password gate（用戶已設密碼後 endpoint 預設拒絕匿名讀）。"""
    import requests
    tok = os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN") or ""
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    last_status = None
    for attempt in range(3):
        try:
            res = requests.post(
                f"{WORKER_URL}/get-preferences",
                json={"email": email},
                headers=headers,
                timeout=10
            )
            last_status = res.status_code
            if res.ok:
                d = res.json() or {}
                plan = d.get("plan") or "free"
                # 日報深度全體用戶可選(合規結構 COMPLIANCE_STRUCTURE.md:個股分析內容不得依付費分級)
                depth = d.get("digest_depth") or "standard"
                if depth not in ("simple", "standard", "deep"):
                    depth = "standard"
                return {
                    "us_stocks": d.get("us_stocks") or [],
                    "tw_stocks": d.get("tw_stocks") or [],
                    "plan": plan,
                    "digest_depth": depth,
                    # 持倉成本(選填):{sym:{entry_price,entry_date}} → 持有者框架建議
                    "positions": d.get("positions") if isinstance(d.get("positions"), dict) else {},
                }
        except Exception:
            pass
        if attempt < 2:
            time.sleep(2)
    print(f"   ⚠️ 無法取得 {email} 的偏好設定（重試 3 次後仍失敗 status={last_status}），本次改用預設版")
    if last_status == 403:
        reason = "INTERNAL_TOKEN 未設" if not tok else "INTERNAL_TOKEN 與 worker env 不匹配"
        print(f"      → 原因：{reason}，server-to-server bypass 失效")
    return {"us_stocks": [], "tw_stocks": [], "plan": "free", "digest_depth": "standard", "positions": {}, "_fetch_failed": True, "_status": last_status}


def save_hosted_digest(html: str, date: str = "", email: str = "") -> str:
    """把完整日報 HTML 上傳到 Worker KV，回傳可分享的網頁連結；失敗回 None。
    date 若有值會同步寫進 digest_idx:{date}:{token},供 track-record builder 列舉所有
    當日個人化日報、算進跨用戶總勝率。
    email 若有值,worker 會寫 digest_email:{token} 對應,供 admin 後台把模擬跟單歸戶
    (只存 KV、admin 認證才讀得到,不影響日報內容與寄送)。"""
    import requests
    token = secrets.token_urlsafe(12)
    try:
        payload = {"token": token, "html": html}
        if date:
            payload["date"] = date
        if email:
            payload["email"] = email
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
        '<div style="margin:14px 12px 0;padding:13px 16px;background:#eef0ff;'
        'border:1px solid #c7d2fe;border-radius:12px;text-align:center;">'
        f'<a href="{url}" style="font-size:13px;font-weight:800;color:#4338ca;'
        'text-decoration:none;">📱 在網頁上看完整日報（不會被截斷、可分享）→</a>'
        f'{note}</div>'
    )


def _picks_display_names(data: dict, market: str, syms: list) -> list:
    """精選標的顯示名:台股用中文名(主旨/文案不可露裸代號),美股用 ticker。"""
    if market == "us":
        return list(syms or [])
    tw = data.get("tw_market", {}) or {}
    names_all = data.get("tw_names_all", {}) or {}
    return [((tw.get(s) or {}).get("name") or names_all.get(s) or s) for s in (syms or [])]


def _picks_intro_banner(market: str, names: list) -> str:
    """精選模式信件頂部說明卡:講清楚這是 AI 委員會公版精選、非用戶持股。"""
    label = "美股" if market == "us" else "台股"
    return (
        '<div style="background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:1px solid #c7d2fe;'
        'border-radius:12px;padding:16px 18px;margin:0 0 16px;">'
        f'<div style="font-size:15px;font-weight:800;color:#3730a3;margin-bottom:6px;">🤖 AI 委員會今日精選{label}</div>'
        f'<div style="font-size:13px;color:#4338ca;line-height:1.7;">你還沒設定{label}持股偏好,'
        f'今天由多個 AI 模型組成的投資委員會投票,選出目前最有潛力的 {len(names)} 檔{label}:'
        f'<b>{"、".join(names)}</b>。完整分析在下方,推薦你研究看看。'
        '想改收自己持股的專屬分析,到 <a href="https://marketdaily.ai/dashboard.html" '
        'style="color:#6366f1;font-weight:700;">我的專區</a> 設定股票就行。</div></div>'
    )


def _picks_subject(market: str, names: list, date: str) -> str:
    label = "美股" if market == "us" else "台股"
    return f"🤖 AI 精選{label}:{'、'.join(names)}｜MarketDaily {date}"


def _sanitize_picks_wording(html: str) -> str:
    """精選模式安全網:LLM/備援模板若仍把精選標的寫成持股,後處理統一改口。"""
    return (html.replace("你的持股", "AI 精選標的")
                .replace("你的部位", "AI 精選標的")
                .replace("持倉深度追蹤", "精選標的深度追蹤")
                .replace("你的組合透視", "精選組合透視"))


def _newbie_guide_footer() -> str:
    """新手等級的訂閱者:日報底部附新手教學連結。"""
    return (
        '<div style="margin:18px 12px 4px;padding:14px 16px;background:#f6f7fb;'
        'border:1px solid #e2e8f0;border-radius:12px;text-align:center;">'
        '<div style="font-size:13px;color:#444;line-height:1.7;">'
        '剛開始用 MarketDaily？不熟悉怎麼操作？</div>'
        '<a href="https://marketdaily.ai/guide.html" style="display:inline-block;'
        'margin-top:6px;font-size:13px;font-weight:800;color:#4338ca;'
        'text-decoration:none;">📖 看 3 分鐘新手教學 →</a>'
        '</div>'
    )


def _run_no_brevo_preview():
    """無 BREVO_API_KEY(本地開發)→ 只產公版預覽,不碰訂閱者。"""
    print("① 抓取市場數據與新聞...")
    data = fetch_all()
    print("② 過濾假訊息...")
    data["us_news"] = filter_us_news(data["us_news"])
    data["tw_news"] = filter_tw_news(data["tw_news"])
    print(f"③ AI 生成報告（{_report_variant_label()}版）...")
    inner = _report_fn()(data, market=MARKET)
    print("④ 生成 AI 市場情緒 Banner...")
    inner = _inject_ai_banner(inner, data["date"])
    inner = _inject_political_signals(inner, data)
    print("⑤ 儲存本地預覽...")
    save_local(data["date"], inner, suffix=("_us" if MARKET == "us" else ""))


def _prewarm_card_pool(data, all_us_extra, all_tw_extra):
    """用全體訂閱者的標的聯集跑滿批卡片生成,暖 analyzer 的跨用戶快取(零邊際成本的關鍵)。

    為什麼要在 per-user 迴圈之前做:每位用戶只缺零星幾支時,批次會很小,而每次呼叫都要
    重付約 2,400 token 的規則區塊 → 呼叫數被「用戶數」推高而不是「標的數」。
    先跑滿批 → 呼叫數 = ceil(不重複標的/批次大小),加人幾乎不增加成本。

    fail-soft:這裡失敗不影響正確性(per-user 迴圈照原路徑生成),只是回到舊的成本曲線。
    只暖「本班次該市場」的標的:另一市場的資料當班未必抓齊,硬生會拿到殘缺數據。
    ⚠️ MARKET 有三個值(tw/us/both,both=手動合併跑),漏掉 both 會只暖一半——實測抓到。
    """
    try:
        from analyzer import _render_signal_cards_batched, _market_status
        if MARKET == "tw":
            wanted = set(all_tw_extra)
        elif MARKET == "us":
            wanted = set(all_us_extra)
        else:
            wanted = set(all_tw_extra) | set(all_us_extra)
        syms = sorted(wanted)
        if not syms:
            return
        mkt = _market_status(data["date"])
        avail = {**data.get("us_market", {}), **data.get("tw_market", {})}
        syms = [s for s in syms if (avail.get(s) or {}).get("price") is not None]
        if not syms:
            print("   [card-pool] 聯集標的皆無市價,略過預生成")
            return
        print(f"   [card-pool] 預生成 {len(syms)} 檔(全體訂閱者聯集,{MARKET} 班)→ 後面用戶共用")
        _render_signal_cards_batched(data, syms, mkt, depth="standard")
    except Exception as e:
        print(f"   ⚠️ [card-pool] 預生成失敗({str(e)[:80]}),改回逐用戶生成(成本較高但功能不受影響)")


def _load_subscriber_prefs(subscribers):
    """抓每位訂閱者偏好;附 zero-error gate(抓取失敗 ≥30% → 推 admin 告警)。
    回傳 (subscriber_prefs, all_us_extra, all_tw_extra)。"""
    subscriber_prefs = {}
    all_us_extra, all_tw_extra = set(), set()
    for email in subscribers:
        prefs = get_user_preferences(email)
        subscriber_prefs[email] = prefs
        for s in prefs.get("us_stocks") or []:
            all_us_extra.add(s)
        for s in prefs.get("tw_stocks") or []:
            all_tw_extra.add(s)

    # zero-error gate：prefs 抓取失敗 ≥ 30% → 所有人都會收到預設版（=「跟昨天一樣」的事故）
    # 2026-05-27 出包過：endpoint 加 password gate 但 daily job 沒帶 INTERNAL_TOKEN → 10/10 全部 403
    failed = [em for em, p in subscriber_prefs.items() if p.get("_fetch_failed")]
    if failed and len(failed) / max(len(subscribers), 1) >= 0.3:
        msg = (
            f"🚨 [PREFS-FETCH] {len(failed)}/{len(subscribers)} 位訂閱者的偏好抓取失敗，"
            f"將收到預設版（無個人化）\n"
            f"sample status：{subscriber_prefs[failed[0]].get('_status')}\n"
            f"修法：確認 worker INTERNAL_TOKEN 與 GH Actions secret 同步，再重 deploy stripe-webhook"
        )
        print(f"   🚨 {msg}")
        try:
            _push_admin_halt_alert(time.strftime("%Y-%m-%d"),
                                   det_fallbacks=[], perso_fails=[(e, "prefs_403") for e in failed],
                                   dry_run=DRY_RUN)
        except Exception as e:
            print(f"   (admin alert push 失敗：{e})")
    return subscriber_prefs, all_us_extra, all_tw_extra


def _fetch_and_filter_data(all_us_extra, all_tw_extra):
    """抓市場數據+過濾假訊息;美股晚報遇休市夜回傳 None(整輪不發)。"""
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

    # 美股晚報遇美股休市夜(美國國定假日,worker 判不到的)→ 整輪不發,
    # 純美股用戶不被「美股今晚沒開盤」的空版打擾。週末已由 worker 擋掉。
    from analyzer import _market_status as _mkt_status_fn
    if MARKET == "us" and _mkt_status_fn(data["date"]).get("us_will_open_tonight") is False:
        print("🛑 MARKET=us 但今晚美股休市 → 跳過本輪美股晚報(不發信)")
        return None
    return data


def _build_default_report(data):
    """公版報告:生成→banner/政壇注入→本地存檔→上傳網頁。
    死防線:全 LLM 失效改 deterministic 版,絕不拋例外(絕不讓用戶缺信)。
    回傳 (default_report, default_web_url)。"""
    local_suffix = "_us" if MARKET == "us" else ""
    variant_label = _report_variant_label()
    print(f"④ 生成 AI 市場情緒 Banner（{variant_label}版）...")
    try:
        default_report = _report_fn()(data, market=MARKET)
        default_report = _inject_ai_banner(default_report, data["date"])
        default_report = _inject_political_signals(default_report, data)
    except Exception as e:
        # 死防線:全 LLM provider 同時失效(2026-06-25 美股晚報事故:Gemini 503 + Claude key 401
        # + 無 OpenAI key)時,預設版生成會整個拋例外 → 原本害 main.py exit=1、一封都寄不出。
        # 改用無 LLM 的 deterministic 版墊底,確保晚報照常寄出(絕不讓用戶缺信)。
        print(f"   🛡️ 預設版 AI 生成全失敗,改用 deterministic 備援版:{e}")
        from analyzer import _market_status, generate_deterministic_fallback, _postprocess_html
        _mkt = _market_status(data["date"])
        default_report = _postprocess_html(
            generate_deterministic_fallback(data, [], [], _mkt), data)
    print("⑤ 儲存本地預覽（預設版）...")
    save_local(data["date"], default_report, suffix=local_suffix)

    print("⑥ 上傳預設版網頁...")
    default_web_url = save_hosted_digest(build_email_html(data["date"], default_report), data["date"])
    return default_report, default_web_url


def _route_shift_content(data, us_stocks, tw_stocks, get_picks):
    """雙班次收信對象(按持股決定內容,但每天保證兩封、絕不跳過任何訂閱者):
    沒選本班次市場持股的用戶 → 改收「AI 委員會今日精選」公版推薦
    (所有用戶內容完全相同且免費,合規:個股內容不依付費/偏好差異化)。
    回傳 (gen_us, gen_tw, picks_mode, picks_banner, picks_market, pk_names)。"""
    no_holdings = not us_stocks and not tw_stocks
    # 週末回顧是「一週一封」跨雙市場總結(美台股皆已收盤),涵蓋用戶全部持股。
    weekly_recap = _is_saturday_tw() and MARKET in ("tw", "both")
    # 個人化只生成本班次市場的 signal-card;對面市場在新聞/大盤區做收盤回顧。
    picks_mode = False
    if weekly_recap:
        gen_us, gen_tw = us_stocks, tw_stocks
        if no_holdings:
            gen_tw = get_picks("tw")
            picks_mode = bool(gen_tw)
    elif MARKET == "tw":
        if tw_stocks:
            gen_us, gen_tw = None, tw_stocks
        else:
            gen_us, gen_tw = None, get_picks("tw")
            picks_mode = bool(gen_tw)
    elif MARKET == "us":
        if us_stocks:
            gen_us, gen_tw = us_stocks, None
        else:
            gen_us, gen_tw = get_picks("us"), None
            picks_mode = bool(gen_us)
    else:
        gen_us, gen_tw = us_stocks, tw_stocks
        if no_holdings:
            gen_tw = get_picks("tw")
            picks_mode = bool(gen_tw)
    picks_market = "us" if MARKET == "us" else "tw"
    picks_banner = ""
    pk_names = []
    if picks_mode:
        pk_names = _picks_display_names(data, picks_market, (gen_us or []) + (gen_tw or []))
        picks_banner = _picks_intro_banner(picks_market, pk_names)
    return gen_us, gen_tw, picks_mode, picks_banner, picks_market, pk_names


def _generate_user_email(data, email, gen_us, gen_tw, depth, is_premium, picks_mode,
                         picks_banner, picks_market, pk_names, exp_tier, exp_score, total,
                         default_report, default_web_url, ai_calls, personalization_failures,
                         positions=None):
    """單一用戶的個人化內容生成:完整版上傳網頁、email 版超上限裁切、個人化失敗
    走顯著告知 banner + 公版(絕不偷偷把通用版當個人化寄)。
    回傳 (inner, subject, web_url, shown, ai_calls)。"""
    from analyzer import get_personalized_subject
    subject = None
    web_url = default_web_url
    shown = total
    if gen_us or gen_tw:
        mode_tag = "AI 精選" if picks_mode else "個人化"
        print(f"   {email} → {mode_tag}（本班次 {MARKET}｜美股:{len(gen_us or [])}, 台股:{len(gen_tw or [])}）· {exp_tier}（{exp_score}）")
        try:
            if ai_calls > 0:
                time.sleep(5)  # 輕度間隔，避免觸發 Gemini 免費層每分鐘上限
            full_inner = _report_fn()(data, gen_us or None, gen_tw or None, depth=depth, market=MARKET, is_premium=is_premium, picks_mode=picks_mode, positions=positions)
            ai_calls += 1
            full_inner = _inject_ai_banner(full_inner, data["date"])
            if depth != "simple":
                full_inner = _inject_political_signals(full_inner, data, (gen_us or []) + (gen_tw or []))
                if not picks_mode:
                    full_inner = _inject_intel_signals(full_inner, data, (gen_us or []) + (gen_tw or []))
            if picks_mode:
                full_inner = picks_banner + _sanitize_picks_wording(full_inner)
            # 完整版（含全部持倉）上傳網頁
            web_url = save_hosted_digest(build_email_html(data["date"], full_inner), data["date"], email=email) or default_web_url
            # email 版：持倉超過上限時縮減，避免被 Gmail 截斷
            if total > DIGEST_EMAIL_MAX_HOLDINGS:
                time.sleep(5)
                inner = _report_fn()(data, gen_us or None, gen_tw or None, email_safe=True, depth=depth, market=MARKET, is_premium=is_premium, picks_mode=picks_mode, positions=positions)
                ai_calls += 1
                inner = _inject_ai_banner(inner, data["date"])
                if depth != "simple":
                    inner = _inject_political_signals(inner, data, (gen_us or []) + (gen_tw or []))
                    if not picks_mode:
                        inner = _inject_intel_signals(inner, data, (gen_us or []) + (gen_tw or []))
                if picks_mode:
                    inner = picks_banner + _sanitize_picks_wording(inner)
                shown = DIGEST_EMAIL_MAX_HOLDINGS
            else:
                inner = full_inner
            if picks_mode:
                subject = _picks_subject(picks_market, pk_names, data["date"])
            else:
                subject = get_personalized_subject(data, gen_us or [], gen_tw or [], data["date"])
        except Exception as e:
            print(f"   ⚠️ {email} 個人化失敗，改用預設版（{e}）")
            # fallback 不能偷偷把通用版當個人化日報寄,用戶會以為自己的持股被忽略。
            # 加顯著 banner 告知 + 累計推 admin 讓我下一輪知道誰沒拿到完整版。
            personalization_failures.append((email, str(e)[:120]))
            fail_banner = ('<div style="background:#fff3cd;border:2px solid #ffc107;'
                           'padding:14px;margin:16px 0;border-radius:8px;color:#856404">'
                           '⚠️ <b>今天你的個人化日報生成異常</b>,以下是大盤通用版本(你的持股股票未在內)。'
                           '主編已收到通知,明天會修復;暫時請看網頁完整版或主動聯絡。</div>')
            inner = fail_banner + default_report
            subject = None
            web_url = default_web_url
            shown = total
    else:
        inner = default_report
    return inner, subject, web_url, shown, ai_calls


# 👑 老闆護盾(2026-07-24 Delvin 親令「絕對不要再看到閹割版」):把 HIGH 檢查分兩類——
# 「軟錯」= 內容完整且正確、只是不夠深(理由偏短/偏籠統/TLDR 偏短);其餘全是「硬錯」
# (版面壞/假數字/裸代號/截斷/漏持股/時序錯/真洩漏,寄出=壞或錯的信)。老闆本人的日報
# 若只因軟錯要被閹割 → 改寄 AI 完整版(寧可完整帶小瑕,不要閹割);硬錯仍走備援。
_SOFT_HIGH_CHECKS = {"signal_reason_shallow", "signal_reason_vague", "tldr_too_short"}


def _owner_emails():
    return {e.strip().lower() for e in os.environ.get(
        "MARKETDAILY_OWNER_EMAIL", "delvin.12345678@gmail.com").split(",") if e.strip()}


def _owner_shield_applies(high_checks, email):
    """老闆護盾:是老闆本人 + 剩餘 HIGH 全為軟錯 → 該寄 AI 完整版取代閹割備援版。"""
    return (bool(high_checks) and all(c in _SOFT_HIGH_CHECKS for c in high_checks)
            and str(email).strip().lower() in _owner_emails())


def _audit_with_retry(data, email, inner, gen_us, gen_tw, depth, is_premium, picks_mode,
                      picks_banner, ai_calls, deterministic_fallbacks,
                      systemic_high_counts=None, positions=None):
    """使用者視角 audit:HIGH severity → retry 一次(強制換更強模型),仍 fail →
    deterministic fallback,絕不寄錯誤內容,也絕不讓用戶收不到信。MED/LOW 直接寄。
    回傳 (html, fails, ai_calls)。"""
    html = build_email_html(data["date"], inner)
    from digest_audit import audit_digest
    from analyzer import _market_status, generate_deterministic_fallback, _postprocess_html
    mkt = _market_status(data["date"])
    _earn_est = any((e or {}).get("eps_est") is not None for e in (data.get("earnings") or []))
    try:
        fails = audit_digest(html, data["date"], gen_us or [], gen_tw or [], mkt, market=MARKET,
                             earnings_estimates=_earn_est, base_css=CSS)
    except Exception as e:
        fails = []
        print(f"   ⚠️ audit 異常: {e}")
    if any(f.get("severity") == "high" for f in fails) and (gen_us or gen_tw):
        high_checks = sorted({f["check"] for f in fails if f.get("severity") == "high"})
        print(f"   ⚠️ {email} HIGH audit fail({','.join(high_checks)}),retry 一次")
        # 系統性失敗熔斷告警:同一 HIGH check 連中 3 位 = 幾乎必是 prompt/樣板層 bug,
        # 不是個別內容偶發(2026-07-06 週一版 12/12 全中,admin 卻寄完才知道)。
        # outbox 等整點才寄,這則會趕在寄出前送達;寄送本身不擋——死線是絕不缺信。
        if systemic_high_counts is not None:
            for _c in high_checks:
                systemic_high_counts[_c] = systemic_high_counts.get(_c, 0) + 1
                if systemic_high_counts[_c] == 3:
                    _push_systemic_alert(data["date"], _c, email)
        try:
            # 60s:Groq 免費層是 TPM(每分鐘 token)限制,首輪生成若 429 過,5s 後 retry
            # 必然還在同一分鐘窗口內再撞 429 → 掉到更弱模型 → 白 retry(07-27 八位掉
            # deterministic 的共犯)。等滿一個 TPM 窗口讓最強免費模型復活;只有 HIGH fail
            # 才走到這裡,量少,寄出死線由 MD_SEND_DEADLINE_HM 閘把關。
            time.sleep(60)
            # retry 強制換更強模型(Claude/OpenAI 先於 Gemini),否則又從 Gemini 起跑 = 白 retry
            retry_inner = _report_fn()(data, gen_us or None, gen_tw or None, prefer_strong=True, depth=depth, market=MARKET, is_premium=is_premium, picks_mode=picks_mode, positions=positions)
            ai_calls += 1
            retry_inner = _inject_ai_banner(retry_inner, data["date"])
            if depth != "simple":
                retry_inner = _inject_political_signals(retry_inner, data, (gen_us or []) + (gen_tw or []))
                if not picks_mode:
                    retry_inner = _inject_intel_signals(retry_inner, data, (gen_us or []) + (gen_tw or []))
            if picks_mode:
                retry_inner = picks_banner + _sanitize_picks_wording(retry_inner)
            retry_html = build_email_html(data["date"], retry_inner)
            retry_fails = audit_digest(retry_html, data["date"], gen_us or [], gen_tw or [], mkt, market=MARKET, earnings_estimates=_earn_est, base_css=CSS)
            if not any(f.get("severity") == "high" for f in retry_fails):
                print("   ✅ retry pass")
                html = retry_html
                fails = retry_fails
            else:
                retry_high_checks = sorted({f["check"] for f in retry_fails if f.get("severity") == "high"})
                # 👑 老闆護盾:你本人 + 剩下的 HIGH 全是軟錯 → 寄 AI 完整版而非閹割備援版。
                if _owner_shield_applies(retry_high_checks, email):
                    print(f"   👑 老闆護盾:僅軟性 HIGH({','.join(retry_high_checks)}) → 寄 AI 完整版(不閹割,睡著也生效)")
                    html = retry_html
                    fails = retry_fails
                else:
                    print(f"   🛡️ retry 仍 HIGH fail({','.join(retry_high_checks)}) → 切 deterministic fallback")
                    det_inner = _postprocess_html(generate_deterministic_fallback(data, gen_us or [], gen_tw or [], mkt), data)
                    if picks_mode:
                        det_inner = picks_banner + _sanitize_picks_wording(det_inner)
                    html = build_email_html(data["date"], det_inner)
                    fails = audit_digest(html, data["date"], gen_us or [], gen_tw or [], mkt, market=MARKET, earnings_estimates=_earn_est, base_css=CSS)
                    deterministic_fallbacks.append(email)
        except Exception as e:
            print(f"   🛡️ retry 異常 → deterministic fallback ({e})")
            det_inner = _postprocess_html(generate_deterministic_fallback(data, gen_us or [], gen_tw or [], mkt), data)
            if picks_mode:
                det_inner = picks_banner + _sanitize_picks_wording(det_inner)
            html = build_email_html(data["date"], det_inner)
            fails = audit_digest(html, data["date"], gen_us or [], gen_tw or [], mkt, market=MARKET,
                                 earnings_estimates=_earn_est, base_css=CSS)
            deterministic_fallbacks.append(email)
    return html, fails, ai_calls


def _audio_personalize(html, email, date, picks_mode):
    """個人語音快報:audit 後的最終 HTML → audio 連結加專屬 token+抽個股進 manifest。
    fail-open:任何失敗回(原 html, None),信件維持公版連結,絕不影響寄送。"""
    try:
        from audio_brief.manifest import personalize_email_audio
        return personalize_email_audio(html, email, date,
                                       "us" if MARKET == "us" else "tw", picks_mode)
    except Exception as e:
        print(f"   ⚠️ 語音個人化跳過({e})")
        return html, None


def run():
    from config import BREVO_API_KEY
    from publisher import get_list_id, check_subscriber_count, get_all_subscribers, send_transactional_email

    if not BREVO_API_KEY:
        _run_no_brevo_preview()
        return

    print("① 取得訂閱者名單與持倉偏好...")
    list_id = get_list_id()
    check_subscriber_count(list_id)
    subscribers = get_all_subscribers(list_id)
    print(f"   共 {len(subscribers)} 位訂閱者")

    subscriber_prefs, all_us_extra, all_tw_extra = _load_subscriber_prefs(subscribers)

    data = _fetch_and_filter_data(all_us_extra, all_tw_extra)
    if data is None:
        return

    default_report, default_web_url = _build_default_report(data)

    print("⑦ 個人化發送...")
    from experience import experience_tier
    success_count = 0
    processed = 0  # 本班次實際納入的收信者(分流後 < 總訂閱數)
    ai_calls = 0
    tier_counts = {"新手": 0, "一般": 0, "老手": 0}
    audit_failures_by_email = {}  # 寄送前的使用者視角 audit 結果,寄完彙總推給 admin
    personalization_failures = []  # AI 個人化失敗的 (email, reason),寄完一起推給 admin
    deterministic_fallbacks = []  # retry 仍 HIGH fail → 用 deterministic 模板(無 LLM)寄出
    systemic_high_counts = {}  # HIGH check 名 → 命中用戶數(連中 3 位即熔斷告警,見 _audit_with_retry)
    outbox = []  # (email, html, subject):先全部生成,等班次整點一齊寄(修「日報固定遲到20分」)
    audio_entries = []  # 個人語音快報 manifest(每人 token+實收個股),寄送前寫檔給 personal.py

    # AI 委員會公版精選:沒選本班次市場持股的用戶,改收委員會投票選出的今日最有潛力標的。
    # council_top_picks 內部有快取(每輪只投一次票)+動能保底,絕不拋例外。
    def _get_picks(mk: str) -> list:
        try:
            from analyzer import council_top_picks
            return council_top_picks(data, mk, n=3)
        except Exception as e:
            print(f"   ⚠️ AI 精選選股失敗({e}),該用戶改收預設版")
            return []

    # ── 卡片池預生成(2026-07-30 Delvin 零邊際成本令:「1 個用戶到 200 個用戶都是免費」)──
    # 沒有這個 pass 時,每位用戶各自把「自己缺的那幾支」湊成小批次呼叫 LLM,
    # 每次都重付一遍約 2,400 token 的規則區塊 → 實測 290 檔要 142 次呼叫(理論只需 29 次)。
    # 先用全體訂閱者的標的聯集跑滿批(10 檔/批)暖 analyzer 的跨用戶快取,
    # 後面的 per-user 迴圈就幾乎全命中 → 成本 = ceil(不重複標的/10),與用戶數無關。
    # 品質不打折:走的是同一條生成+品質閘+重生迴圈路徑,且合規鐵則本就要求
    # 「個股分析對全體用戶完全相同」——共用一份反而更合規。
    _prewarm_card_pool(data, all_us_extra, all_tw_extra)

    picks_email_cache = {}  # (depth, exp_tier) -> (html, subject):精選版全用戶內容相同,共用生成結果
    for email in subscribers:
        prefs = subscriber_prefs[email]
        us_stocks = prefs.get("us_stocks") or []
        tw_stocks = prefs.get("tw_stocks") or []
        positions = prefs.get("positions") or {}  # 持倉成本(選填)→持有者框架,全體用戶可用
        # 總本金(選填,2026-07-22 資金體檢):以特殊鍵搭 positions 順風車進 analyzer,
        # 免動三個 generate_*_report 簽名;卡片渲染只迭代持股代號,此鍵不會變成卡。
        _cap = prefs.get("capital")
        if isinstance(_cap, (int, float)) and _cap > 0:
            positions = {**positions, "__capital__": float(_cap)}
        depth = prefs.get("digest_depth") or "standard"  # 日報深度全體用戶可選(合規結構:不依付費分級)
        is_premium = prefs.get("plan") in ("premium", "admin")  # 僅供統計/tier 標籤;禁止用來分級日報內容(COMPLIANCE_STRUCTURE.md)

        gen_us, gen_tw, picks_mode, picks_banner, picks_market, pk_names = \
            _route_shift_content(data, us_stocks, tw_stocks, _get_picks)

        processed += 1
        total = len(gen_us or []) + len(gen_tw or [])  # 本班次實際出卡的持股數
        exp_score, exp_tier = experience_tier(len(us_stocks), len(tw_stocks), prefs.get("plan"))
        tier_counts[exp_tier] = tier_counts.get(exp_tier, 0) + 1

        # 精選版對所有用戶內容完全相同 → 同(深度,tier)共用同一封,不重複燒 LLM
        picks_key = (depth, exp_tier) if picks_mode else None
        if picks_key and picks_key in picks_email_cache:
            html, subject = picks_email_cache[picks_key]
            print(f"   {email} → AI 精選版(共用今日精選,快取)")
            if DRY_RUN:
                print(f"   [DRY-RUN] 略過寄信 → {email}")
                success_count += 1
            else:
                html, _a_entry = _audio_personalize(html, email, data["date"], picks_mode)
                if _a_entry:
                    audio_entries.append(_a_entry)
                outbox.append((email, html, subject))
                print(f"   📦 生成完成,進寄送佇列 → {email}")
            continue

        inner, subject, web_url, shown, ai_calls = _generate_user_email(
            data, email, gen_us, gen_tw, depth, is_premium, picks_mode, picks_banner,
            picks_market, pk_names, exp_tier, exp_score, total,
            default_report, default_web_url, ai_calls, personalization_failures,
            positions=positions)

        if web_url:
            inner = _web_view_banner(web_url, total, shown) + inner
        if exp_tier == "新手":
            inner = inner + _newbie_guide_footer()

        try:
            html, fails, ai_calls = _audit_with_retry(
                data, email, inner, gen_us, gen_tw, depth, is_premium,
                picks_mode, picks_banner, ai_calls, deterministic_fallbacks,
                systemic_high_counts, positions=positions)
            if fails:
                audit_failures_by_email[email] = fails
            # 只快取成功生成的精選版(subject=None 表示走了個人化失敗 fallback,別讓一人失敗全體共用)
            if picks_key and subject:
                picks_email_cache[picks_key] = (html, subject)
            if DRY_RUN:
                print(f"   [DRY-RUN] 略過寄信 → {email}")
                success_count += 1
            else:
                html, _a_entry = _audio_personalize(html, email, data["date"], picks_mode)
                if _a_entry:
                    audio_entries.append(_a_entry)
                outbox.append((email, html, subject))
                print(f"   📦 生成完成,進寄送佇列 → {email}")
        except Exception as e:
            print(f"   ❌ 生成異常：{email}（{e}）")

    if audio_entries and not DRY_RUN:
        try:
            from audio_brief.manifest import write_manifest
            _mp = write_manifest(audio_entries, data["date"], "us" if MARKET == "us" else "tw")
            print(f"🎙 個人語音 manifest:{len(audio_entries)} 份 → {_mp}")
        except Exception as e:
            print(f"   ⚠️ 語音 manifest 寫檔失敗({e})")

    success_count += _flush_outbox(outbox, data["date"], send_transactional_email, BREVO_API_KEY)

    _emit_run_report(data, subscribers, processed, success_count, tier_counts,
                     deterministic_fallbacks, personalization_failures, audit_failures_by_email)


def _flush_outbox(outbox, date, send_fn, api_key):
    """全部生成完 → 等到班次整點(tw 07:00 / us 20:00 TW)一齊寄出。
    cron 已提早觸發(06:20/19:25)只為留生成時間;寄出時間釘在整點,不再固定遲到 20 分。
    回傳成功寄出數。"""
    if not outbox:
        return 0
    sent_ok = 0
    _hold_until_send_time(MARKET)
    if not _failover_send_clearance(MARKET, date):   # 雲端備援才有作用;winrig 已交付→整批不寄
        return 0
    if not _local_send_clearance(MARKET, date):      # winrig 才有作用;雲端已代打→整批不寄
        return 0
    _enforce_send_deadline(MARKET)   # 補班才有作用;放在 hold 之後=用「真正要寄的那一刻」判定
    # MD_SUBJECT_NOTE:人工補寄修正版時標注主旨(例:「(更新版) 」),平常不設=無作用
    note = os.environ.get("MD_SUBJECT_NOTE", "")
    for email, html, subject in outbox:
        if note:
            subject = note + (subject or f"📊 財經日報 {date} — AI 精選美股 + 台股")
        try:
            ok = send_fn(email, date, html, api_key, subject=subject)
        except Exception as e:
            ok = False
            print(f"   ❌ 發送異常：{email}（{e}）")
        if ok:
            sent_ok += 1
        else:
            print(f"   ❌ 發送失敗：{email}")
    return sent_ok


def _emit_run_report(data, subscribers, processed, success_count, tier_counts,
                     deterministic_fallbacks, personalization_failures, audit_failures_by_email):
    """收尾:寄送統計 + 守門/覆蓋率/preflight 告警 + audit 彙整寫報告檔(下一輪我會看)。"""
    print(f"✅ 今日財經日報發送完成（班次 {MARKET}）！成功 {success_count}/{processed} 位（總訂閱 {len(subscribers)}）")
    print(f"   經驗分布 → 🌱新手 {tier_counts['新手']} · 📈一般 {tier_counts['一般']} · 🎯老手 {tier_counts['老手']}")

    # 守門通知:deterministic fallback 或個人化失敗 → 即時 LINE 推 admin
    if deterministic_fallbacks or personalization_failures:
        print(f"🛡️ {len(deterministic_fallbacks)} 位走 deterministic fallback")
        try:
            _push_admin_halt_alert(data["date"], deterministic_fallbacks, personalization_failures,
                                   dry_run=DRY_RUN)
        except Exception as e:
            print(f"   ⚠️ admin LINE 推失敗:{e}")

    # 覆蓋率守門:主源+Yahoo 都救不回的台股(除權息文字欄、下市、端點漏)→ 推 admin(web push)
    try:
        import data_fetcher as _df
        if _df._LAST_TW_MISSING:
            print(f"🕳️ {len(_df._LAST_TW_MISSING)} 支台股無報價救不回:{_df._LAST_TW_MISSING}")
            _push_admin_coverage_alert(data["date"], _df._LAST_TW_MISSING, dry_run=DRY_RUN)
    except Exception as e:
        print(f"   ⚠️ 覆蓋率告警推失敗:{e}")

    # Pre-flight 額外:任何 HIGH audit fail 即時 LINE 推 admin(寄信前 30 分跑時用),
    # 讓 admin 有時間在真實 cron 跑前修 prompt。
    if DRY_RUN:
        all_high_fails = []
        for em, fs in audit_failures_by_email.items():
            highs = [f for f in fs if f.get("severity") == "high"]
            if highs:
                all_high_fails.append((em, highs))
        if all_high_fails:
            try:
                _push_preflight_alert(data["date"], all_high_fails, len(subscribers))
            except Exception as e:
                print(f"   ⚠️ preflight LINE 推失敗:{e}")
        else:
            print(f"✅ [PRE-FLIGHT] {len(subscribers)} 位用戶日報無 HIGH fail,可放心讓主 cron 跑")

    # 個人化失敗的用戶 → 寫進 audit 報告主檔
    if personalization_failures:
        print(f"⚠️ 個人化失敗 {len(personalization_failures)} 位:")
        for em, err in personalization_failures:
            print(f"   - {em}: {err}")

    # audit 結果彙整 → 印 cron log + 寫報告檔(下一輪我會看)
    # 2026-07-24:掉 deterministic 備援版是最嚴重的使用者可見後果(收到閹割版),但原本
    # 完全沒寫進報告(備援版重稽核 fails=空 → 不進 by_email),也不觸發寫檔 →「報告全綠、
    # 實際收到備援版」的落差(delvin 實鍋)。三類失敗(備援/個人化拋錯/audit失分)都要浮上來。
    if audit_failures_by_email or personalization_failures or deterministic_fallbacks:
        all_checks = {}
        for em, fs in audit_failures_by_email.items():
            for f in fs:
                all_checks.setdefault(f["check"], []).append((em, f))
        summary_lines = []
        if deterministic_fallbacks:
            summary_lines.append(
                f"🛡️ [deterministic_fallback] {len(deterministic_fallbacks)} 位收到備援版"
                f"(個人化生成連 retry 都失敗):{', '.join(deterministic_fallbacks)}")
        if personalization_failures:
            summary_lines.append(
                f"❌ [personalization_failed] {len(personalization_failures)} 位個人化生成拋錯:"
                f"{', '.join(em for em, _ in personalization_failures)}")
        if audit_failures_by_email:
            summary_lines.append(f"🚨 日報 audit:{len(audit_failures_by_email)}/{len(subscribers)} 位用戶的日報失分")
        for check, items in sorted(all_checks.items(), key=lambda x: -len(x[1])):
            sev = items[0][1].get("severity", "med")
            tag = {"high": "🔴", "med": "🟡", "low": "🔵"}.get(sev, "🟡")
            summary_lines.append(f"{tag} [{check}] {len(items)} 人:{items[0][1]['msg']}")
        summary = "\n".join(summary_lines)
        print(summary)
        # 寫報告檔給下一輪 review;commit 進 repo 讓 Claude 開新 session 也看得到
        try:
            import json as _json
            import os as _os
            _os.makedirs("output", exist_ok=True)
            report_path = f"output/digest_audit_{data['date']}.json"
            with open(report_path, "w", encoding="utf-8") as f:
                _json.dump({
                    "date": data["date"],
                    "total_subscribers": len(subscribers),
                    "personalization_failed_count": len(personalization_failures),
                    "personalization_failures": personalization_failures,
                    "deterministic_fallback_count": len(deterministic_fallbacks),
                    "deterministic_fallbacks": list(deterministic_fallbacks),
                    "audit_failed_count": len(audit_failures_by_email),
                    "summary": summary,
                    "by_email": {em: fs for em, fs in audit_failures_by_email.items()},
                }, f, ensure_ascii=False, indent=2)
            print(f"📋 audit 報告寫到 {report_path}")
        except Exception as e:
            print(f"   ⚠️ audit 報告寫檔失敗: {e}")


def _push_admin_alert(msg):
    """通用 admin web push(alert-worker /internal/admin-line-push,路徑名沿用但只發 web push)。"""
    import json as _json
    import urllib.request
    worker = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                            "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    tok = (os.environ.get("MARKETDAILY_ALERT_TOKEN")
           or os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN"))
    if not tok:
        print("   (skip admin push:MARKETDAILY_ALERT_TOKEN/INTERNAL_TOKEN 未設)")
        return
    try:
        req = urllib.request.Request(
            f"{worker.rstrip('/')}/internal/admin-line-push",
            data=_json.dumps({"message": msg}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                     "User-Agent": "md-digest-alert/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"   📣 admin push status={resp.status}")
    except Exception as e:
        print(f"   ⚠️ admin push 失敗:{e}")


def _alert_if_late(market, late_sec):
    """生成拖過班次整點:照寄(遲到比不寄好),但遲到不准隱形(2026-07-11 早報遲 55 分無人知,
    Delvin 問了才發現;07-07→07-11 完成時間 07:02→07:59 連五天劣化)。
    遲 15 分~3 小時=本班次真遲到,推 admin;更久=人工補寄/異常時段,不吵。"""
    late_min = int(late_sec // 60)
    if not (15 <= late_min <= 180):
        return
    label = "早報(整點 07:00 TW)" if market == "tw" else "晚報(整點 20:00 TW)"
    _push_admin_alert(f"⏰ {label} 遲到 {late_min} 分鐘才寄出——生成拖過整點,照寄但要查慢因"
                      f"(近日 Gemini 429 全滅逐戶 fallback 是主嫌)。若為人工補寄可忽略。"
                      f"log: logs/fallback_*.log")


def _archive_online(market, date):
    """公版存檔(docs/output/,git push 後由 Cloudflare Pages 服務)是否已上線。

    語義關鍵:這個檔案是【寄完之後】才被推上去的(winrig 由 run.sh 在 main.py 結束後 commit
    +push;雲端備援由 workflow 的 "Persist public digest archive" 步驟)。所以
    「我還沒寄、它就已經在線上」= 這一班已經被另一邊交付過了。
    step ⑥ 的 save_hosted_digest 走的是另一條(Worker/KV 網頁版),不會污染這個判準。
    查不到一律當作沒交付 → 照寄:死線是絕不缺信,寧可重寄也不可缺信。"""
    import urllib.request
    suffix = "_us" if market == "us" else ""
    url = f"https://marketdaily.ai/output/digest_{date}{suffix}.html"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "md-failover-guard"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def _local_send_clearance(market, date):
    """winrig 端的反向防雙發閘(2026-07-30 事故)。

    07-28 事故只補了雲端那一邊:雲端寄出前會等 winrig 交付。但 07-30 晚報反過來——
    免費 LLM 全層見底(Gemini 雙 key RPD 429 / Groq TPM / CF neuron 超上限)導致 winrig
    退到 OpenRouter 550b(~144s/次)一路拖到 21:35;watchdog 20:25 第一檢撲空派了雲端備援,
    雲端等到自己的死線前緣 21:02 判定「winrig 卡死」代打寄出(全員 deterministic 備援版),
    winrig 21:35 完工時【毫無察覺】又寄了一輪 → 21 位訂閱者每人兩封。
    防線只裝單邊就只擋得住單一方向;這裡把它對稱化:winrig 寄出前也查一次公版存檔。

    只管正常班次(tw/us);MARKET=both 的手動補寄與 MD_FORCE_SEND=1 一律放行,
    否則人工補寄修正版會被自己的存檔擋死。回傳 False=本輪不得寄出。"""
    if os.environ.get("MD_FAILOVER") == "1":
        return True                      # 雲端那邊由 _failover_send_clearance 管
    if market not in ("tw", "us"):
        return True                      # both/手動班次不受閘
    if os.environ.get("MD_FORCE_SEND") == "1":
        return True
    if not _archive_online(market, date):
        return True
    label = "早報" if market == "tw" else "晚報"
    msg = (f"🟠 {label} {date}:winrig 生成完成時公版存檔【已在線上】= 雲端備援已代打交付,"
           f"winrig 退場不重寄(防雙發對稱閘)。訂閱者收到的是雲端備援版(多半是 deterministic "
           f"降級版),查 GitHub Actions failover run 與本機 logs/fallback_{date}.log 的遲滯根因。")
    print(f"   {msg}")
    _push_admin_alert(msg)
    return False


def _failover_send_clearance(market, date):
    """雲端備援(MD_FAILOVER=1)寄出前的防雙發終極閘(2026-07-28 事故)。

    當天實況:winrig 補班正在跑但還沒寄完,watchdog 07:30 檢查公版存檔撲空→派發雲端備援;
    備援 workflow 的起跑閘那一刻存檔也還沒上線→放行;40 分鐘生成後 08:06 直接開寄——
    winrig 08:02 已寄出正常版,訂閱者一天收到兩封,第二封還是雲端弱模降級版。
    起跑時的一次性檢查天生擋不住「winrig 在雲端生成期間交付完成」,裁決必須放在
    「真正要寄的那一刻」:
      公版存檔已上線 → winrig 已交付 → 退場不寄;
      未上線但 winrig 心跳新鮮 → 它活著(多半補班中),每 60 秒重查等它交付,
        等到=退場;拖到內容誠實死線前緣仍沒有 → winrig pipeline 卡死,由雲端代打;
      心跳過期 → winrig 真缺席(斷電/當機),立刻代打。
    winrig 本機從不設 MD_FAILOVER,行為零改變。回傳 False=本輪不得寄出。"""
    if os.environ.get("MD_FAILOVER") != "1":
        return True
    import urllib.request
    from zoneinfo import ZoneInfo
    status_url = "https://watchdog.marketdaily.ai/status"

    def _archived():
        return _archive_online(market, date)

    def _winrig_alive():
        try:
            req = urllib.request.Request(status_url, headers={"User-Agent": "md-failover-guard"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                hb = (json.load(resp) or {}).get("hb") or {}
            return not hb.get("stale", True)
        except Exception:
            return True   # watchdog 看不到→假設 winrig 活著繼續等:寧可晚寄,不可重寄

    raw = os.environ.get("MD_SEND_DEADLINE_HM", "").strip()
    if not (raw.isdigit() and len(raw) == 4):
        raw = "0840" if market == "tw" else "2110"
    # 輪詢到死線前 8 分就得裁決:留時間給 21+ 封實際寄送,且不可撞 _enforce_send_deadline
    cutoff_min = int(raw[:2]) * 60 + int(raw[2:]) - 8
    while True:
        if _archived():
            msg = f"☁️ 雲端備援 {date} {market} 寄出前偵測到公版存檔已上線(winrig 已交付)→ 退場不重寄"
            print(f"   {msg}")
            _push_admin_alert(msg)
            return False
        if not _winrig_alive():
            print("   ☁️ 備援閘:winrig 心跳過期(真缺席)→ 雲端代打寄出")
            return True
        now_tw = datetime.now(ZoneInfo("Asia/Taipei"))
        if now_tw.hour * 60 + now_tw.minute >= cutoff_min:
            _push_admin_alert(f"🟠 雲端備援 {date} {market}:winrig 心跳存活但日報遲未交付,"
                              f"已到死線前緣({now_tw:%H:%M} TW)改由雲端代打。查 winrig 日報 pipeline。")
            return True
        print("   ☁️ 備援閘:winrig 存活且尚未交付,60 秒後重查(等它交付,不搶寄)")
        time.sleep(60)


def _enforce_send_deadline(market):
    """補班專用的寄出端死線閘(2026-07-20)。

    為什麼需要它:班次窗口只閘得到「起跑」時刻,而生成實測 40-99 分鐘(Gemini 全 429 走 claude
    慢路徑那天跑了 99 分),兩者差一整個生成時間。補班把合法起跑時刻往後推到 08:00 TW 之後,
    光靠起跑閘就再也保證不了「寄出時仍在盤前」——會變成開盤後寄一封講盤前的信,那是內容錯誤。
    所以真正的保證放在這裡:寄出前一刻比對台北時間,過線寧可不寄。

    只有 run.sh 補班模式會設 MD_SEND_DEADLINE_HM(格式 HHMM,台北時間);正常班次完全不經過
    這條路徑,行為零改變。
    """
    raw = os.environ.get("MD_SEND_DEADLINE_HM", "").strip()
    if not raw.isdigit() or len(raw) != 4:
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_tw = datetime.now(ZoneInfo("Asia/Taipei"))
    if now_tw.hour * 60 + now_tw.minute <= int(raw[:2]) * 60 + int(raw[2:]):
        return
    label = "早報" if market == "tw" else "晚報"
    msg = (f"🟡 {label} 補班放棄寄出:生成完成時已是台北 {now_tw:%H:%M},超過內容誠實死線 "
           f"{raw[:2]}:{raw[2:]}。此時寄出等於開盤後發一封講盤前的信,故刻意不寄。")
    print(msg)
    _push_admin_alert(msg + " (main.py exit=3;內容留在 logs/ 可人工檢視)")
    raise SystemExit(3)   # 模組層沒有 import sys(只有 1321 行的區域 import),用內建例外最穩


def _hold_until_send_time(market):
    """提早觸發只為先把日報生成好;寄出時間釘在班次整點(tw 07:00 TW=23:00 UTC / us 20:00 TW=12:00 UTC)。
    生成若拖過整點 → 不等,立刻寄(遲到比不寄好),但遲到>15分推 admin 告警。both/手動班次不等。"""
    from datetime import datetime, timezone
    hm = {"tw": (23, 0), "us": (12, 0)}.get(market)
    if not hm:
        return
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    wait = (target - now).total_seconds()
    # UTC 跨日校正(2026-07-20 驗證者 F2):tw 的整點 07:00 TW = 23:00 UTC,只離 UTC 換日一小時。
    # 生成若拖到 08:00 TW 之後就已跨進隔天 UTC,`now.replace(hour=23)` 會指到【今晚】而不是今早,
    # wait 變成 +23h,late_min 變成大負數 → 遲到告警在「補班最危險的那段」必然靜音。
    # 差一整天就把它減回來;只影響已經 return 的那條分支,不碰 sleep 路徑。
    if wait > 12 * 3600:
        wait -= 24 * 3600
    # 只在「距整點 60 分內」才等:>60 分 = 手動補發/異常時段,直接寄,不白等
    if wait <= 0 or wait > 60 * 60:
        _alert_if_late(market, -wait)
        return
    print(f"⏸️ 全員生成完畢,等 {int(wait // 60)} 分 {int(wait % 60)} 秒到班次整點一齊寄出")
    time.sleep(wait)


def _push_systemic_alert(date_str, check, sample_email):
    """同一 HIGH audit check 生成中連中 3 位用戶 → 立刻推 admin(不等寄完)。
    這種模式幾乎必是 prompt/樣板層系統性 bug:retry 換模型也救不回(同 prompt 同病),
    受影響用戶會拿到 fallback 降級版。05:30 preflight 已隨 GitHub Actions 停擺退役,
    這條熔斷是它的接替防線(零額外 LLM 成本,靠 outbox 整點寄的時間差跑在寄出前)。"""
    import json as _json
    import urllib.request
    worker = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                            "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    tok = (os.environ.get("MARKETDAILY_ALERT_TOKEN")
           or os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN"))
    if not tok:
        print("   (skip systemic push:MARKETDAILY_ALERT_TOKEN/INTERNAL_TOKEN 未設)")
        return
    msg = (f"🚨 [系統性] 日報 {date_str} audit HIGH [{check}] 生成中已連中 3 位用戶(如 {sample_email})\n"
           f"= prompt/樣板層 bug,非個別內容偶發;中招用戶將收到 retry/fallback 降級版。\n"
           f"整點寄出前仍有時間介入,速查 logs/fallback_{date_str}.log")
    try:
        req = urllib.request.Request(
            f"{worker.rstrip('/')}/internal/admin-line-push",
            data=_json.dumps({"message": msg}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                     "User-Agent": "md-digest-alert/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"   🚨 systemic alert push status={resp.status}")
    except Exception as e:
        print(f"   ⚠️ systemic alert 推失敗:{e}")


def _push_preflight_alert(date_str, high_fails, total_subscribers):
    """Pre-flight 跑出 HIGH fail → 立刻推 admin,他有 30 分鐘修。"""
    import os
    import json as _json
    import urllib.request
    worker = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                            "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    tok = (os.environ.get("MARKETDAILY_ALERT_TOKEN")
           or os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN"))
    if not tok:
        print("   (skip preflight push:MARKETDAILY_ALERT_TOKEN/INTERNAL_TOKEN 未設)")
        return
    lines = [f"🚨 [PRE-FLIGHT] 日報 {date_str} 有 HIGH 品質問題 — 寄信前必修"]
    lines.append(f"影響:{len(high_fails)}/{total_subscribers} 位訂閱者")
    sample_checks = {}
    for em, highs in high_fails:
        for h in highs:
            sample_checks.setdefault(h["check"], []).append(em)
    for check, ems in sorted(sample_checks.items(), key=lambda x: -len(x[1]))[:5]:
        lines.append(f"  🔴 [{check}] {len(ems)} 位:{ems[0]}…")
    lines.append("\n主 cron 30 分後跑,把握時間修 prompt + 重 deploy")
    msg = "\n".join(lines)[:4900]
    req = urllib.request.Request(
        f"{worker.rstrip('/')}/internal/admin-line-push",
        data=_json.dumps({"message": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                     "User-Agent": "md-digest-alert/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"   preflight LINE push status={resp.status}")


def _push_admin_halt_alert(date_str, det_fallbacks, perso_fails, dry_run=False):
    """日報品質守門:走 deterministic fallback / personalization fail → LINE 即時推 admin。
    用戶不會缺信(都有寄),但 admin 需要立刻知道哪些用戶今天拿到的是降級版,趕快查 prompt 問題。"""
    import os
    import json as _json
    import urllib.request
    worker = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                            "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    # admin 推播用 alert-worker 專屬 token(它的 INTERNAL_TOKEN 與主 worker 不同把);
    # 退回 MARKETDAILY_INTERNAL_TOKEN 只為相容,真正能過 alert-worker auth 的是 ALERT_TOKEN。
    tok = (os.environ.get("MARKETDAILY_ALERT_TOKEN")
           or os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN"))
    if not tok:
        print("   (skip:MARKETDAILY_ALERT_TOKEN/INTERNAL_TOKEN 未設,無法推 admin)")
        return
    prefix = "🧪 [PRE-FLIGHT]" if dry_run else "🛡️"
    lines = [f"{prefix} MarketDaily 日報品質告警 {date_str}"]
    # 老闆本人掉降級/備援版 = 紅色 canary(2026-07-24:delvin 掉 portfolio_lens 誤殺備援,
    # 舊告警只說「1 位掉備援」跟其他品質告警一模一樣→淹沒沒被抓到)。老闆是老手多持股,
    # 他掉多半是系統性問題的金絲雀;最上方插刺眼獨立警示,不可能再與雜訊混淆。
    owner_emails = _owner_emails()
    owner_hit = sorted({em for em in (list(det_fallbacks) + [e for e, _ in perso_fails])
                        if str(em).strip().lower() in owner_emails})
    if owner_hit:
        lines.insert(0, "🚨🚨🚨 老闆本人今天收到降級/備援版日報 — 幾乎必是系統性問題的金絲雀,務必當天查根因!")
    if det_fallbacks:
        lines.append(f"⬇️ {len(det_fallbacks)} 位走 deterministic fallback(retry 仍 HIGH fail):")
        for em in det_fallbacks[:8]:
            lines.append(f"  • {em}" + ("  ← 老闆本人" if str(em).strip().lower() in owner_emails else ""))
        if len(det_fallbacks) > 8:
            lines.append(f"  …另 {len(det_fallbacks) - 8} 位")
    if perso_fails:
        lines.append(f"⚠️ {len(perso_fails)} 位個人化失敗(顯著 banner 已加):")
        for em, err in perso_fails[:3]:
            lines.append(f"  • {em}: {err[:60]}")
    lines.append("\n見 output/digest_audit_*.json 詳細報告")
    msg = "\n".join(lines)[:4900]
    req = urllib.request.Request(
        f"{worker.rstrip('/')}/internal/admin-line-push",
        data=_json.dumps({"message": msg}).encode("utf-8"),
        # User-Agent 不可省:預設 Python-urllib 會被 Cloudflare WAF/bot 規則擋成 403,
        # 告警永遠送不出(2026-06-27 查出的「admin 推播 403」真兇)。
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                 "User-Agent": "md-digest-alert/1.0"},
        method="POST",
    )
    # 重試 3 次:間歇 403(WAF)/timeout 不再讓告警默默蒸發。全敗 = 守衛掛掉也要看得見,
    # 大聲印到 cron log(尤其含老闆本人時),再往上拋讓呼叫端記錄。
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"   admin push status={resp.status}"
                      + ("  🚨含老闆本人掉備援" if owner_hit else ""))
                return
        except Exception as e:
            last_err = e
            print(f"   ⚠️ admin push 第 {attempt + 1}/3 次失敗:{e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    print("🚨🚨 ADMIN 日報品質告警推播 3 次全失敗,這則告警沒送出去!"
          + ("(且含老闆本人掉備援!)" if owner_hit else "")
          + f" last_err={last_err}")
    raise last_err if last_err else RuntimeError("admin push failed after 3 retries")


def _push_admin_coverage_alert(date_str, missing_codes, dry_run=False):
    """持股覆蓋率告警:某些台股主源+Yahoo 都抓不到報價(除權息文字欄殘留、下市、端點漏),
    日報那張卡會缺。推 admin(alert-worker 優先 web push)去查,不是只默默少一張卡。"""
    import os
    import json as _json
    import urllib.request
    worker = os.environ.get("MARKETDAILY_ALERT_WORKER_URL",
                            "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    tok = (os.environ.get("MARKETDAILY_ALERT_TOKEN")
           or os.environ.get("MARKETDAILY_INTERNAL_TOKEN") or os.environ.get("INTERNAL_TOKEN"))
    if not tok:
        print("   (skip 覆蓋率告警:token 未設)")
        return
    try:
        import data_fetcher as _df
        names = _df.tw_name_map()
    except Exception:
        names = {}
    prefix = "🧪 [PRE-FLIGHT]" if dry_run else "🕳️"
    lines = [f"{prefix} MarketDaily 台股報價缺漏 {date_str}",
             f"以下 {len(missing_codes)} 支主源+Yahoo 都抓不到,日報卡片會缺,請查:"]
    for c in missing_codes[:20]:
        nm = names.get(c, "")
        lines.append(f"  • {c} {nm}".rstrip())
    msg = "\n".join(lines)[:4900]
    req = urllib.request.Request(
        f"{worker.rstrip('/')}/internal/admin-line-push",
        data=_json.dumps({"message": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                 "User-Agent": "md-digest-alert/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"   coverage push status={resp.status}")


import sys as _sys
DRY_RUN = "--dry-run" in _sys.argv


if __name__ == "__main__":
    run()
