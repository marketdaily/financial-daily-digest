import re
import time
import requests
import stock_names
from config import GEMINI_API_KEY

# 免費 LLM 引擎：Gemini Flash 系列（免費，無需付費）。
# flash-latest 品質佳為主；flash-lite 免費層每日額度最高，作為備援確保不斷線。
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_SYSTEM_PROMPT = (
    "你是嚴謹的財經日報 HTML 生成器。必須完整輸出使用者要求的每一個 HTML 區塊與欄位，"
    "凡是標示「必填、強制、每一張都要」的內容一律不可省略。"
    "只輸出 HTML 本身，不要 markdown code block，不要任何多餘說明。"
)


def _call_gemini(prompt: str, model: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("未設定 GEMINI_API_KEY")
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 16000,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"
    resp = None
    for attempt in range(4):
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(12 if resp.status_code == 429 else 6)
            continue
        resp.raise_for_status()
        break
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _llm_generate(prompt: str) -> str:
    """免費 LLM 引擎鏈：依序嘗試各 Gemini 免費模型，全部失敗才報錯。"""
    last_err = None
    for model in GEMINI_MODELS:
        try:
            out = _call_gemini(prompt, model)
            print(f"  [LLM] 使用 {model}")
            return out
        except Exception as e:
            last_err = e
            print(f"  [LLM] {model} 失敗（{e}）")
    raise RuntimeError(f"所有免費 LLM 引擎都失敗：{last_err}")


def get_personalized_subject(data: dict, us_stocks: list, tw_stocks: list, date: str) -> str:
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    biggest_sym, biggest_pct = None, 0
    for sym in (us_stocks or []):
        if sym in us_market:
            pct = abs(us_market[sym]["change_pct"])
            if pct > biggest_pct:
                biggest_pct = pct
                biggest_sym = (sym, us_market[sym]["change_pct"])
    for sym in (tw_stocks or []):
        if sym in tw_market:
            pct = abs(tw_market[sym]["change_pct"])
            if pct > biggest_pct:
                biggest_pct = pct
                biggest_sym = (sym, tw_market[sym]["change_pct"])
    if biggest_sym and biggest_pct >= 2:
        sym, pct = biggest_sym
        direction = "漲" if pct > 0 else "跌"
        return f"📊 你的 {sym} 今天{direction}了 {abs(pct):.1f}%｜財經日報 {date}"
    return f"📊 財經日報 {date} — AI 精選美股 + 台股"


def _format_market_data(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None) -> str:
    lines = []
    us = data.get("us_market", {})
    tw = data.get("tw_market", {})
    ind = data.get("indicators", {})

    index_names = {
        "^GSPC": "S&P500", "^IXIC": "NASDAQ", "^DJI": "道瓊",
        "DX-Y.NYB": "美元指數", "^TWII": "台灣加權指數"
    }

    lines.append("【美股指數】")
    for sym in ["^GSPC", "^IXIC", "^DJI", "DX-Y.NYB"]:
        if sym in us:
            d = us[sym]
            lines.append(f"  {index_names[sym]}: {d['price']} ({d['change_pct']:+.2f}%)")

    lines.append("\n【台股指數】")
    if "^TWII" in tw:
        d = tw["^TWII"]
        lines.append(f"  台灣加權指數: {d['price']} ({d['change_pct']:+.2f}%)")

    if user_us_stocks or user_tw_stocks:
        lines.append("\n【⭐ 用戶持倉今日表現（最重要，優先分析）】")
        gainers, losers, no_data = [], [], []
        for sym in (user_us_stocks or []):
            if sym in us:
                d = us[sym]
                arrow = "▲" if d["change_pct"] >= 0 else "▼"
                entry = f"  {stock_names.display_name(sym)}（{sym}）: ${d['price']} {arrow}{d['change_pct']:+.2f}%"
                (gainers if d["change_pct"] >= 0 else losers).append(entry)
            else:
                no_data.append(f"  {stock_names.display_name(sym)}（{sym}）: 今日無數據")
        for sym in (user_tw_stocks or []):
            if sym in tw:
                d = tw[sym]
                arrow = "▲" if d["change_pct"] >= 0 else "▼"
                entry = f"  {stock_names.display_name(sym, d.get('name'))}（{sym}）: ${d['price']} {arrow}{d['change_pct']:+.2f}%"
                (gainers if d["change_pct"] >= 0 else losers).append(entry)
            else:
                no_data.append(f"  {stock_names.display_name(sym)}（{sym}）: 今日無數據")
        for line in gainers + losers + no_data:
            lines.append(line)

    lines.append("\n【美股個股（市場參考，最多12支）】")
    core_us = ["AAPL","MSFT","NVDA","TSLA","GOOGL","META","AMD","TSM"]
    show_us = list(dict.fromkeys((user_us_stocks or []) + core_us))[:12]
    for sym in show_us:
        if sym in us:
            d = us[sym]
            flag = " ⭐持倉" if user_us_stocks and sym in user_us_stocks else ""
            lines.append(f"  {stock_names.display_name(sym)}（{sym}）: {d['price']} ({d['change_pct']:+.2f}%){flag}")

    lines.append("\n【台股個股】")
    core_tw = ["2330", "2454", "2317"]
    show_tw = list(dict.fromkeys((user_tw_stocks or []) + core_tw))
    for sym in show_tw:
        d = tw.get(sym)
        if d:
            flag = " ⭐持倉" if user_tw_stocks and sym in user_tw_stocks else ""
            lines.append(f"  {stock_names.display_name(sym, d.get('name'))}（{sym}）: {d['price']} ({d['change_pct']:+.2f}%){flag}")

    lines.append("\n【風險指標】")
    if "vix" in ind:
        vix = ind["vix"]
        level = "極度恐慌" if vix > 30 else "警戒" if vix > 20 else "平靜"
        lines.append(f"  VIX 恐慌指數: {vix} ({level})")
    if "fear_greed" in ind:
        fg = ind["fear_greed"]
        lines.append(f"  CNN 恐貪指數: {fg['score']}/100 ({fg['rating']})")
    if "us10y" in ind:
        lines.append(f"  美國10年債殖利率: {ind['us10y']}%")
    if "gold" in ind:
        g = ind["gold"]
        lines.append(f"  黃金: ${g['price']} ({g['change_pct']:+.2f}%)")
    if "oil" in ind:
        o = ind["oil"]
        lines.append(f"  WTI 原油: ${o['price']} ({o['change_pct']:+.2f}%)")
    if "usdtwd" in ind:
        fx = ind["usdtwd"]
        lines.append(f"  USD/TWD 匯率: {fx['rate']} ({fx['change_pct']:+.3f}%)")

    crypto = data.get("crypto", {})
    if crypto:
        lines.append("\n【加密貨幣】")
        if "btc" in crypto:
            b = crypto["btc"]
            lines.append(f"  BTC: ${b['price']:,.0f} ({b['change_pct']:+.2f}%)")
        if "eth" in crypto:
            e = crypto["eth"]
            lines.append(f"  ETH: ${e['price']:,.0f} ({e['change_pct']:+.2f}%)")

    sectors = data.get("sectors", [])
    if sectors:
        lines.append("\n【板塊輪動（S&P 板塊 ETF 今日表現）】")
        for s in sectors:
            arrow = "▲" if s["change_pct"] >= 0 else "▼"
            lines.append(f"  {s['symbol']} {s['name']}: {arrow} {s['change_pct']:+.2f}%")

    earnings = data.get("earnings", [])
    if earnings:
        lines.append("\n【即將公布財報】")
        for e in earnings[:6]:
            lines.append(f"  {stock_names.display_name(e['symbol'])}（{e['symbol']}）: {e['date']}")

    return "\n".join(lines)


def _format_news(articles: list, max_items: int = 8) -> str:
    lines = []
    for a in articles[:max_items]:
        tag = "✅" if a.get("verified") else "⚠️"
        url = a.get("url", "")
        sources = ", ".join(a.get("sources", []))
        lines.append(f"  {tag} {a.get('title', '')} [{sources}] URL:{url}")
    return "\n".join(lines)


def _postprocess_html(html: str, data: dict) -> str:
    ind = data.get("indicators", {})

    vix = ind.get("vix", 15)
    html = html.replace("indicator-VIXCLASS", "indicator-fear" if vix > 20 else "indicator-neutral")

    fg = ind.get("fear_greed") or {}
    fg_score = fg.get("score", 50)
    html = html.replace("indicator-FGCLASS", "indicator-fear" if fg_score < 45 else "indicator-greed" if fg_score > 55 else "indicator-neutral")

    crypto = data.get("crypto", {})
    btc_dir = "up" if (crypto.get("btc") or {}).get("change_pct", 0) >= 0 else "down"
    eth_dir = "up" if (crypto.get("eth") or {}).get("change_pct", 0) >= 0 else "down"
    import re as _re
    html = _re.sub(r'\bBTCDIR(?:\s+(?:up|down))?\b', btc_dir, html)
    html = _re.sub(r'\bETHDIR(?:\s+(?:up|down))?\b', eth_dir, html)

    html = _re.sub(r'class="verdict SENTIMENT"', 'class="verdict neutral"', html)

    # 移除幻覺網址：read-more 的 href 必須是今日真實新聞 URL，否則整個連結拿掉
    real_urls = set()
    for a in data.get("us_news", []) + data.get("tw_news", []):
        u = (a.get("url") or "").strip()
        if u:
            real_urls.add(u)

    def _strip_fake_link(m):
        return m.group(0) if m.group(1).strip() in real_urls else ""

    html = _re.sub(
        r'<a class="read-more"[^>]*href="([^"]*)"[^>]*>.*?</a>',
        _strip_fake_link, html, flags=_re.DOTALL
    )

    # 代號 → 公司中英文名：把 ticker 類 span 內的純代號展開成「公司名 + 小灰代號」
    tw_hint = {}
    for code, d in data.get("tw_market", {}).items():
        if isinstance(d, dict) and d.get("name"):
            tw_hint[code] = d["name"]

    # 新手友善「一眼看懂買賣」總覽：從訊號卡自動彙整每支股票的買/賣/持有/觀望
    _verdict = {
        "buy":  ("🟢 可以買進", "buy"),
        "hold": ("🟡 抱著別動", "hold"),
        "sell": ("🔴 建議賣出", "sell"),
        "wait": ("⚪ 先觀望",   "wait"),
    }
    _card_re = _re.compile(
        r'<div class="signal-card (buy|hold|sell|wait)">.*?'
        r'<span class="signal-ticker">\s*([^<]+?)\s*</span>'
        r'(?:\s*<span class="signal-day-move (up|down)">\s*([^<]*?)\s*</span>)?'
        r'.*?<div class="signal-reason">\s*(.*?)\s*</div>',
        _re.DOTALL,
    )
    _rows = []
    for verdict, code_raw, dm_dir, dm_text, reason in _card_re.findall(html):
        code = stock_names.pick_code(code_raw)
        label, cls = _verdict[verdict]
        move = f'<span class="action-move {dm_dir}">{dm_text}</span>' if dm_dir else ""
        reason_plain = _re.sub(r"<[^>]+>", "", reason).strip()
        _rows.append(
            f'<div class="action-item {cls}">'
            f'<div class="action-main"><span class="action-name">{stock_names.badge_html(code, tw_hint.get(code))}</span>'
            f'{move}<span class="action-verdict {cls}">{label}</span></div>'
            f'<div class="action-reason">{reason_plain}</div></div>'
        )
    if _rows:
        board = (
            '<div class="action-board">'
            '<div class="action-board-title">📋 一眼看懂：你的股票今天買還是賣</div>'
            + "".join(_rows)
            + '<div class="action-legend">🟢 買進＝現在可考慮進場 ｜ 🟡 持有＝抱著別動 ｜ '
            '🔴 賣出＝建議獲利了結或停損（認賠出場） ｜ ⚪ 觀望＝先別出手</div></div>'
        )
        html = html.replace(
            '<div class="signal-header">', board + '\n<div class="signal-header">', 1
        )

    def _expand_ticker(m):
        cls, content = m.group(1), m.group(2)
        if "<" in content:
            return m.group(0)
        code = stock_names.pick_code(content)
        return f'<span class="{cls}">{stock_names.badge_html(code, tw_hint.get(code))}</span>'

    html = _re.sub(
        r'<span class="(signal-ticker|ticker|stock-news-ticker|earnings-ticker|rookie-name)">([^<]*)</span>',
        _expand_ticker, html
    )

    def _expand_impact(m):
        direction, content = m.group(1), m.group(2)
        if "<" in content:
            return m.group(0)
        code = stock_names.pick_code(content)
        arrow = "▲" if direction == "up" else "▼"
        tag = "看漲" if direction == "up" else "看跌"
        label = stock_names.label_with_code(code, tw_hint.get(code))
        return f'<span class="impact-stock {direction}">{arrow} {label} {tag}</span>'

    html = _re.sub(
        r'<span class="impact-stock (up|down)">([^<]*)</span>',
        _expand_impact, html
    )

    # 沒有任何個股的空「影響個股」區塊直接移除
    def _strip_empty_impact(m):
        return m.group(0) if "impact-stock" in m.group(0) else ""

    html = _re.sub(
        r'<div class="news-impact">.*?</div>',
        _strip_empty_impact, html, flags=_re.DOTALL
    )

    return html


DIGEST_EMAIL_MAX_HOLDINGS = 12


def generate_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                    email_safe: bool = False) -> str:
    # email 版：持倉太多時只留變動最大的 N 支，避免信件過長被 Gmail 截斷（完整版見網頁）
    if email_safe:
        us0 = list(user_us_stocks or [])
        tw0 = list(user_tw_stocks or [])
        if len(us0) + len(tw0) > DIGEST_EMAIL_MAX_HOLDINGS:
            um = data.get("us_market", {})
            tm = data.get("tw_market", {})

            def _mv(sym, mkt):
                return abs((mkt.get(sym) or {}).get("change_pct", 0) or 0)

            ranked = sorted(
                [(s, "us") for s in us0] + [(s, "tw") for s in tw0],
                key=lambda x: _mv(x[0], um if x[1] == "us" else tm),
                reverse=True,
            )[:DIGEST_EMAIL_MAX_HOLDINGS]
            user_us_stocks = [s for s, k in ranked if k == "us"]
            user_tw_stocks = [s for s, k in ranked if k == "tw"]

    market_text = _format_market_data(data, user_us_stocks, user_tw_stocks)
    us_news_text = _format_news(data.get("us_news", []), max_items=6)
    tw_news_text = _format_news(data.get("tw_news", []), max_items=5)
    date = data.get("date", "")

    has_holdings = bool(user_us_stocks or user_tw_stocks)
    user_holding_count = len(user_us_stocks or []) + len(user_tw_stocks or [])
    is_beginner = user_holding_count <= 4
    default_us = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "TSM", "JPM"]
    watchlist_us = user_us_stocks if user_us_stocks else default_us
    watchlist_tw = user_tw_stocks if user_tw_stocks else []
    all_holdings = watchlist_us + watchlist_tw

    # Portfolio performance summary for prompt context
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    portfolio_lines = []
    if has_holdings:
        for sym in (user_us_stocks or []):
            if sym in us_market:
                d = us_market[sym]
                portfolio_lines.append(f"  {stock_names.display_name(sym)}（{sym}）: {d['change_pct']:+.2f}% (${d['price']})")
            else:
                portfolio_lines.append(f"  {stock_names.display_name(sym)}（{sym}）: 今日無數據")
        for sym in (user_tw_stocks or []):
            if sym in tw_market:
                d = tw_market[sym]
                portfolio_lines.append(f"  {stock_names.display_name(sym, d.get('name'))}（{sym}）: {d['change_pct']:+.2f}% (${d['price']})")

    watchlist_section = f"【用戶持倉清單（這份報告的核心主角）】\n美股：{', '.join(watchlist_us)}"
    if watchlist_tw:
        watchlist_section += f"\n台股：{', '.join(watchlist_tw)}"
    if portfolio_lines:
        watchlist_section += "\n\n【持倉今日漲跌摘要】\n" + "\n".join(portfolio_lines)

    few_stocks_note = ""
    if has_holdings and len(all_holdings) < 3:
        few_stocks_note = f"""
【用戶持倉不多（只有 {len(all_holdings)} 支），請主動做到以下事情】
1. 在「持倉深度追蹤」區塊中，除了追蹤現有持倉，還要主動推薦 2-3 支「相關股票」，說明為什麼值得關注
2. 在「今天的結論」後面，加一個「💡 你可能也感興趣」區塊，推薦 2-3 支跟用戶持倉同產業或有關聯的股票，附上今日表現和一句話說明理由
3. TLDR 的最後一條改成：「建議你也關注：XXX（理由一句話）」"""

    holdings_instruction = f"（只寫用戶持倉：{', '.join(watchlist_us)}，有數據的才寫。stock-comment 必須與該股今日實際漲跌方向一致——上漲就講上漲原因、下跌就講下跌原因，嚴禁對下跌的股票說「營收成長帶來正面影響」這類與走勢矛盾的話。每支給明確今日評語：漲跌原因 + 短期要注意什麼）"
    tw_holdings_instruction = ""
    if watchlist_tw:
        tw_holdings_instruction = f"""
<div class="section-label">🏢 你的台股今天怎樣</div>
（只寫用戶台股持倉：{', '.join(watchlist_tw)}，有數據的才寫，格式同美股 stock-card，同樣給出明確今日評語）"""

    personalized_news_instruction = f"""
<div class="section-label">🔍 持倉深度追蹤</div>
（只從上方「今日新聞」清單裡，找出真實存在、且確實提到以下持倉的新聞：{', '.join(all_holdings)}
‼️ 嚴禁編造新聞標題或網址；找不到對應新聞的持倉就跳過不寫。
每個有相關新聞的股票寫一個 stock-news-item，格式：
<div class="stock-news-item">
  <span class="stock-news-ticker">（代號）</span>
  <div class="stock-news-content">
    <div class="stock-news-headline">（相關新聞標題，口語化改寫，不超過 25 字）</div>
    <div class="stock-news-impact">📊 影響分析：（這則消息對這支股票代表什麼？要買/持有/賣/觀望？給出明確建議，一句話）</div>
    <a class="read-more" href="（URL）" target="_blank">閱讀原文 →</a>
  </div>
</div>
{f"持倉不多，請也推薦 2-3 支相關股票的 stock-news-item，ticker 後面加上「推薦關注」字樣" if few_stocks_note else ""}
如果沒有任何持倉相關新聞，寫：<div class="stock-news-empty">今日無持倉相關重大新聞</div>）"""

    us_pref = list(dict.fromkeys(user_us_stocks or []))
    tw_pref = list(dict.fromkeys(user_tw_stocks or []))
    signal_stocks = list(dict.fromkeys(us_pref + tw_pref))
    if not signal_stocks:
        signal_stocks = ["AAPL", "MSFT", "NVDA", "TSLA"]

    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    all_market = {**us_market, **tw_market}
    def _abs_change(sym):
        d = all_market.get(sym, {})
        return abs(d.get("change_pct", 0))
    # 個人化版本：用戶每一支持倉都要有操作訊號卡（上限 10 張，依波動排序）
    if has_holdings:
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)[:10]
    else:
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)[:5]

    signal_instruction = f"""
<div class="signal-header">
  <div class="signal-header-title">⚡ 詳細進出場計畫</div>
  <div class="signal-header-subtitle">上面每支股票的買賣價位拆解 · 1-2 週視角</div>
</div>
<div class="signal-grid">
為以下每一支股票各生成一個 signal-card（一支都不能少，順序照列）：{', '.join(top_signal_stocks)}
每張卡格式（最外層 class 從 buy/hold/sell/wait 四選一，要跟結論一致）：
<div class="signal-card buy">
  <div class="signal-card-top">
    <span class="signal-ticker">代號</span>
    <span class="signal-day-move up">▲ +x.xx%</span>
    <div class="signal-score-block"><span class="signal-score">0-10</span><span class="signal-score-label">/ 10</span></div>
    <span class="signal-bias bullish">📈 BULLISH</span>
  </div>
  <div class="signal-body">
    <div class="signal-reason">用新手也聽得懂的白話，講這支股票今天該怎麼辦，依它今天自己的數據與消息，不可用「AI 潛力」這類通用空話</div>
    <div class="signal-battle-plan">
      <div class="battle-row"><span class="battle-label">建議買價</span><span class="battle-val">$xxx–$xxx</span></div>
      <div class="battle-row"><span class="battle-label">賺錢目標</span><span class="battle-val up">$xxx</span></div>
      <div class="battle-row"><span class="battle-label">止損賣價</span><span class="battle-val down">$xxx</span></div>
    </div>
    <div class="signal-watch">👀 觀察重點：接下來最該盯的一件事（財報日 / 某個關鍵價位 / 某則消息後續）</div>
    <div class="signal-meta">
      <span class="signal-badge buy">🟢 建議買入</span>
      <span class="signal-confidence">信心 XX%</span>
      <span class="signal-horizon">⏱ 短線1-2週</span>
    </div>
  </div>
</div>
規則：
- signal-ticker span 內只放純代號（例如 NVDA、2330），系統會自動補公司中英文名
- signal-day-move 填該股今日實際漲跌幅，class（up/down）跟漲跌方向一致；今日無數據就整個 signal-day-move span 省略
- 評分對應：8-10 強力買進 / 6-7 偏多可加碼 / 4-5 持有觀望 / 2-3 偏空減碼 / 0-1 建議賣出
- signal-badge 文字用「🟢 建議買入 / 🟡 續抱持有 / 🔴 建議賣出 / ⚪ 暫時觀望」，class 對應 buy/hold/sell/wait，要跟最外層 class 一致
- 進場 / 目標 / 停損價位要落在該股目前股價的合理範圍，台股用台幣、美股用美元
</div>
<div class="signal-disclaimer">⚠️ AI 分析僅供參考，不構成投資建議</div>"""

    rookie_section = ""
    if is_beginner:
        rookie_section = """
<div class="section-label">🌱 新手推薦：現在適合入手的股票</div>
（這位讀者是投資新手、持股不多。請從上方「今日數據」中，挑 1-2 支「體質穩健、知名度高、適合新手入門」的大型藍籌股
——例如蘋果、微軟、Google、台積電這類；‼️ 絕對不要推薦高波動的小型股、概念股、迷因股給新手。只能推薦今日有真實數據的股票。
每支一張 rookie-pick：
<div class="rookie-pick">
  <div class="rookie-top">
    <span class="rookie-name">代號</span>
    <span class="rookie-verdict">🟢 適合新手入手</span>
  </div>
  <div class="rookie-why">用最白話的話講 2-3 句：這是什麼公司、為什麼適合新手（大家都認識、體質穩）、今天為什麼可以考慮買</div>
  <div class="rookie-tip">💡 新手提醒：先小額試單、別一次重押；想更穩健可定期定額買指數型 ETF（台股 0050、美股 VOO）</div>
</div>
若今天大盤大跌、沒有適合進場的標的，就只放一張 rookie-pick，rookie-verdict 改成「🟡 今天先別急」，rookie-why 說明今天先觀望、可等回穩或改用定期定額。
rookie-name span 內只放純代號，系統會自動補公司名。最多 2 張。）"""

    prompt = f"""你是這位用戶的專屬財經顧問，說話生活化、直接、像朋友。這份報告是**專門為持有 {', '.join(all_holdings) if has_holdings else '各種股票的'} 的用戶客製化生成的**，不是通用報告。

【無幻覺原則 — 最重要，違反就是廢稿】
- 所有內容只能基於以下提供的真實數據和新聞，不得憑空補充或使用訓練資料臆測
- 新聞標題、內文、URL 一律只能從下方「今日新聞」清單取用；URL 必須一字不差原樣複製，嚴禁自己拼湊或編造任何網址
- 找不到對應的真實新聞時，就不要寫那張新聞卡 / stock-news-item，絕對不要為了湊數量而捏造
- 如果某項資訊不足，就說「今日數據不足」，不要捏造

【個人化原則】
- TLDR 30秒重點：如果用戶持倉有重要動向，**第一條就寫他的股票**，不是寫大盤
- 所有分析都圍繞用戶的持倉，大盤新聞只在跟他持倉有關時才詳細寫
- 給建議要明確：說「建議觀望」「可以考慮加倉」「注意停損」，不要模糊
- 口語化，像在 Line 傳訊息，不是寫報告

【寫作風格】
- 讀者是完全不懂股票的新手：用最白話的方式講，少用術語；非用不可的術語（例如停損、殖利率、財報）第一次出現要用括號簡單解釋
- 每一支股票都要讓人立刻知道「該買、該賣、還是抱著」，不可講得模稜兩可
- 數字要具體（不說「大幅上漲」，要說「漲了 3.2%」）
- 每個重點一兩句話說清楚，不廢話
- 繁體中文
- 內文提到個股時用「中文名（代號）」，例如「輝達（NVDA）」「台積電（2330）」，不要只寫代號
{few_stocks_note}
日期：{date}

{watchlist_section}

{market_text}

【今日美股新聞（已過濾假訊息，精選）】
{us_news_text}

【今日台股新聞】
{tw_news_text}

請輸出以下 HTML 結構（直接輸出 HTML，不加 markdown code block）：

<div class="tldr">
<div class="tldr-title">☕ 30 秒看完今天重點</div>
<ul>
  <li>（最重要的事，一句話）</li>
  <li>（第二重要的事）</li>
  <li>（第三重要的事）</li>
  <li>（第四重要的事，如有）</li>
</ul>
</div>

{signal_instruction}
{rookie_section}

<div class="section-label">🌡️ 市場情緒儀表板</div>
<div class="indicator-bar">
  <div class="indicator-item">
    <div class="indicator-label">VIX 恐慌指數</div>
    <div class="indicator-value indicator-VIXCLASS">（VIX數值）</div>
    <div class="indicator-sub">（平靜 / 警戒 / 極度恐慌）</div>
  </div>
  <div class="indicator-item">
    <div class="indicator-label">恐貪指數</div>
    <div class="indicator-value indicator-FGCLASS">（分數/100）</div>
    <div class="indicator-sub">（Fear / Neutral / Greed）</div>
  </div>
  <div class="indicator-item">
    <div class="indicator-label">美國10年債</div>
    <div class="indicator-value">（殖利率%）</div>
    <div class="indicator-sub">（升息預期參考）</div>
  </div>
  <div class="indicator-item">
    <div class="indicator-label">黃金 / 原油</div>
    <div class="indicator-value">（金價） / （油價）</div>
    <div class="indicator-sub">（漲跌%）</div>
  </div>
  <div class="indicator-item">
    <div class="indicator-label">USD/TWD 匯率</div>
    <div class="indicator-value">（匯率）</div>
    <div class="indicator-sub">（台幣升貶）</div>
  </div>
</div>

<div class="section-label">₿ 加密貨幣</div>
<div class="crypto-bar">
  <div class="crypto-item">
    <div class="crypto-name">BTC</div>
    <div class="crypto-price BTCDIR">（價格）</div>
    <div class="crypto-change">（漲跌%）</div>
  </div>
  <div class="crypto-item">
    <div class="crypto-name">ETH</div>
    <div class="crypto-price ETHDIR">（價格）</div>
    <div class="crypto-change">（漲跌%）</div>
  </div>
</div>

<div class="section-label">📈 大盤怎麼了</div>
<div class="market-summary">（用 2-3 句話說大盤狀況，口語化，包含台股）</div>

<div class="section-label">🔄 板塊輪動：哪個板塊最強？</div>
<div class="sector-bar">
（根據板塊 ETF 資料，列出今日表現前三和後三，用 sector-item 格式，包含 sector-name 和 sector-move up/down）
例如：
  <div class="sector-item">
    <span class="sector-name">XLK 科技</span>
    <span class="sector-move up">▲ +2.1%</span>
    <span class="sector-comment">（一句話說為什麼）</span>
  </div>
（共 6 個，強弱各三）
</div>

<div class="section-label">🔥 今天最重要的 5 件事</div>
<div class="news-card">
  <div class="news-tag verified">✅ 多源確認</div>
  <div class="news-headline">（標題，口語化改寫，不超過 25 字）</div>
  <div class="news-why">💡 為什麼重要：（這件事的來龍去脈與後續影響，要有實質分析，不可只是把標題換句話說）</div>
  <div class="news-impact">
    <span class="impact-label">📊 影響個股</span>
    <span class="impact-stock up">NVDA</span>
    <span class="impact-stock down">INTC</span>
  </div>
  <a class="read-more" href="（URL）" target="_blank">閱讀原文 →</a>
</div>
（重複 5 次，單一來源用 <div class="news-tag single">⚠️ 單一來源</div>）

‼️ news-impact 是強制要求：5 張新聞卡【每一張都必須】有 news-impact 區塊，且至少列 1 支 impact-stock。
- impact-stock span 內只放純股票代號（例如 NVDA、AAPL、2330），不要放公司名，系統會自動補名稱與漲跌標示
- class 用 up＝這則消息對該股是利多（可能漲）、down＝利空（可能跌）
- 想不到具體個股時，就挑受影響產業的龍頭股：Fed 利率→JPM、GS；油價→XOM、CVX；AI/算力→NVDA、TSM；半導體→TSM、2330、2454；消費→AMZN、WMT
- 優先列跟用戶持倉（{', '.join(all_holdings) if has_holdings else '主流科技股'}）相關的個股
- 只有新聞完全與任何上市公司無關時（例如純政治事件）才可省略，且這種最多 1 張

<div class="section-label">🔗 二階思考：美股如何影響台灣？</div>
<div class="second-order">
（根據今天美股動向，分析對台灣供應鏈的傳導影響。例如：NVDA 漲 → CoWoS 封裝需求 → 台積電/日月光受惠。只寫真正有關聯的，沒有就不寫。2-3 條 bullet，繁體中文）
</div>

{personalized_news_instruction}

<div class="section-label">🏢 你的美股今天怎樣</div>
<div class="stock-card">
  <span class="ticker">（代號）</span>
  <span class="stock-move up/down">（▲/▼ 漲跌%）</span>
  <div class="stock-comment">（漲/跌原因 + 要不要擔心，一句話）</div>
</div>
{holdings_instruction}
{tw_holdings_instruction}

<div class="section-label">📅 即將公布財報</div>
<div class="earnings-list">
（根據財報日曆，列出未來兩週內的財報，格式：
  <div class="earnings-item">
    <span class="earnings-ticker">（代號）</span>
    <span class="earnings-date">（日期）</span>
    <span class="earnings-note">（一句話：市場預期什麼）</span>
  </div>
若無資料則寫「近期無重大財報」）
</div>

<div class="section-label">🎯 今天的結論</div>
<div class="verdict SENTIMENT">
  <div class="verdict-emoji">（📈 偏多 / 📉 偏空 / 😐 觀望）</div>
  <div class="verdict-text">（2-3 句話，今天市場情緒 + 普通人應該注意什麼）</div>
</div>
<div class="watch-list">
  <div class="watch-title">📌 本週還要注意</div>
  <div class="watch-item">日期 · 事件名稱</div>
  （watch-item 重複 2-4 次，每個即將發生的重要事件一行，務必每行都包在 watch-item 裡）
</div>

注意：
- SENTIMENT 換成 bullish / bearish / neutral
- VIXCLASS 換成 fear（VIX>20）或 neutral（VIX≤20）
- FGCLASS 換成 fear（分數<45）、neutral（45-55）、greed（>55）
- BTCDIR/ETHDIR 換成 up（漲）或 down（跌）
- signal-ticker、ticker、stock-news-ticker、earnings-ticker、impact-stock 這些 span 內一律只放純股票代號，系統會自動補上公司中英文名稱
"""

    raw = _llm_generate(prompt)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    return _postprocess_html(raw, data)
