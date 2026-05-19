import requests
from config import GROQ_API_KEY

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


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
                entry = f"  {sym}: ${d['price']} {arrow}{d['change_pct']:+.2f}%"
                (gainers if d["change_pct"] >= 0 else losers).append(entry)
            else:
                no_data.append(f"  {sym}: 今日無數據")
        for sym in (user_tw_stocks or []):
            if sym in tw:
                d = tw[sym]
                arrow = "▲" if d["change_pct"] >= 0 else "▼"
                entry = f"  {sym} {d.get('name','')}: ${d['price']} {arrow}{d['change_pct']:+.2f}%"
                (gainers if d["change_pct"] >= 0 else losers).append(entry)
            else:
                no_data.append(f"  {sym}: 今日無數據")
        for line in gainers + losers + no_data:
            lines.append(line)

    lines.append("\n【美股個股（市場參考）】")
    default_us = ["AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AMD","TSM","ARM","JPM","GS","BRK-B"]
    show_us = list(dict.fromkeys((user_us_stocks or []) + default_us))
    for sym in show_us:
        if sym in us:
            d = us[sym]
            flag = " ⭐持倉" if user_us_stocks and sym in user_us_stocks else ""
            lines.append(f"  {sym}: {d['price']} ({d['change_pct']:+.2f}%){flag}")

    lines.append("\n【台股個股】")
    for sym, d in tw.items():
        if sym != "^TWII":
            flag = " ⭐持倉" if user_tw_stocks and sym in user_tw_stocks else ""
            lines.append(f"  {d.get('name', sym)}: {d['price']} ({d['change_pct']:+.2f}%){flag}")

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
            lines.append(f"  {e['symbol']}: {e['date']}")

    return "\n".join(lines)


def _format_news(articles: list, max_items: int = 8) -> str:
    lines = []
    for a in articles[:max_items]:
        tag = "✅" if a.get("verified") else "⚠️"
        url = a.get("url", "")
        sources = ", ".join(a.get("sources", []))
        lines.append(f"  {tag} {a.get('title', '')} [{sources}] URL:{url}")
    return "\n".join(lines)


def generate_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None) -> str:
    market_text = _format_market_data(data, user_us_stocks, user_tw_stocks)
    us_news_text = _format_news(data.get("us_news", []))
    tw_news_text = _format_news(data.get("tw_news", []))
    date = data.get("date", "")

    has_holdings = bool(user_us_stocks or user_tw_stocks)
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
                portfolio_lines.append(f"  {sym}: {d['change_pct']:+.2f}% (${d['price']})")
            else:
                portfolio_lines.append(f"  {sym}: 今日無數據")
        for sym in (user_tw_stocks or []):
            if sym in tw_market:
                d = tw_market[sym]
                portfolio_lines.append(f"  {sym}: {d['change_pct']:+.2f}% (${d['price']})")

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

    holdings_instruction = f"（只寫用戶持倉：{', '.join(watchlist_us)}，有數據的才寫。每支股票都要給出明確的今日評語：漲跌原因 + 短期要注意什麼）"
    tw_holdings_instruction = ""
    if watchlist_tw:
        tw_holdings_instruction = f"""
<div class="section-label">🏢 你的台股今天怎樣</div>
（只寫用戶台股持倉：{', '.join(watchlist_tw)}，有數據的才寫，格式同美股 stock-card，同樣給出明確今日評語）"""

    personalized_news_instruction = f"""
<div class="section-label">🔍 持倉深度追蹤</div>
（從今日新聞中，找出跟以下持倉相關的消息：{', '.join(all_holdings)}
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

    prompt = f"""你是這位用戶的專屬財經顧問，說話生活化、直接、像朋友。這份報告是**專門為持有 {', '.join(all_holdings) if has_holdings else '各種股票的'} 的用戶客製化生成的**，不是通用報告。

【無幻覺原則】
- 所有內容只能基於以下提供的真實數據和新聞，不得憑空補充或使用訓練資料臆測
- 如果某項資訊不足，就說「今日數據不足」，不要捏造

【個人化原則】
- TLDR 30秒重點：如果用戶持倉有重要動向，**第一條就寫他的股票**，不是寫大盤
- 所有分析都圍繞用戶的持倉，大盤新聞只在跟他持倉有關時才詳細寫
- 給建議要明確：說「建議觀望」「可以考慮加倉」「注意停損」，不要模糊
- 口語化，像在 Line 傳訊息，不是寫報告

【寫作風格】
- 數字要具體（不說「大幅上漲」，要說「漲了 3.2%」）
- 每個重點一兩句話說清楚，不廢話
- 繁體中文，可夾帶英文股票代號
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
  <div class="news-why">💡 為什麼重要：（這對股市的影響）</div>
  <a class="read-more" href="（URL）" target="_blank">閱讀原文 →</a>
</div>
（重複 5 次，單一來源用 <div class="news-tag single">⚠️ 單一來源</div>）

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
  （2-4 個即將發生的重要事件，格式：日期 · 事件名稱）
</div>

注意：
- SENTIMENT 換成 bullish / bearish / neutral
- VIXCLASS 換成 fear（VIX>20）或 neutral（VIX≤20）
- FGCLASS 換成 fear（分數<45）、neutral（45-55）、greed（>55）
- BTCDIR/ETHDIR 換成 up（漲）或 down（跌）
"""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
