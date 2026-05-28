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


# US 聯邦假日(NYSE 休市) — 2026 ~ 2028 涵蓋。每年初要補。
# 來源:NYSE 官方行事曆。
_US_HOLIDAYS = {
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
    # 2028
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29",
    "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25",
}

# TW 國定假日 (TWSE 休市) — 2026 涵蓋,每年初要補。
_TW_HOLIDAYS = {
    "2026-01-01",  # 元旦
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # 春節
    "2026-02-27", "2026-02-28",  # 228
    "2026-04-03", "2026-04-06",  # 兒童節 + 清明
    "2026-05-01",  # 勞動節
    "2026-06-19",  # 端午
    "2026-09-25",  # 中秋
    "2026-10-09",  # 國慶連假
}


def _market_status(today_iso: str) -> dict:
    """
    根據今天日期(TW 時區),回傳美股 + 台股的開盤狀態,
    讓 prompt 能明說「昨晚美股休市」「今天台股有開盤」等真實事實,
    避免 LLM 把幾天前收盤當「今天/昨晚」寫。

    today_iso 形如 '2026-05-26'(TW 當地日期,日報寄送日)
    """
    from datetime import date, timedelta
    try:
        y, m, d = map(int, today_iso.split("-"))
        td = date(y, m, d)
    except Exception:
        return {"us_traded_last_session": True, "tw_will_open_today": True,
                "us_last_trading_date": None, "tw_last_trading_date": None,
                "us_note": "", "tw_note": ""}

    def _is_trading(d_: date, holidays: set) -> bool:
        if d_.weekday() >= 5:  # 週六日
            return False
        return d_.isoformat() not in holidays

    # 「昨晚美股」對應 TW 今天 - 1 天 (因美股 04:00 TW 收盤)
    yest = td - timedelta(days=1)
    us_traded = _is_trading(yest, _US_HOLIDAYS)
    us_last = yest
    if not us_traded:
        # 往前找最近一個美股交易日
        scan = yest
        for _ in range(7):
            scan = scan - timedelta(days=1)
            if _is_trading(scan, _US_HOLIDAYS):
                us_last = scan
                break

    # 「今晚美股」對應 TW 今天那天的美股 session (美東 9:30 = TW 21:30 / 22:30)
    us_will_open_tonight = _is_trading(td, _US_HOLIDAYS)
    us_next_trading = td
    if not us_will_open_tonight:
        scan = td
        for _ in range(7):
            scan = scan + timedelta(days=1)
            if _is_trading(scan, _US_HOLIDAYS):
                us_next_trading = scan
                break

    # 今天台股是否將開盤
    tw_open = _is_trading(td, _TW_HOLIDAYS)
    tw_last = td
    if not tw_open:
        scan = td
        for _ in range(7):
            scan = scan - timedelta(days=1)
            if _is_trading(scan, _TW_HOLIDAYS):
                tw_last = scan
                break
    else:
        # 今天有開,「最新已有數據」= 昨日(若是交易日)
        scan = td - timedelta(days=1)
        for _ in range(7):
            if _is_trading(scan, _TW_HOLIDAYS):
                tw_last = scan
                break
            scan = scan - timedelta(days=1)

    us_note = ""
    if not us_traded:
        us_note = (f"⚠️ **昨晚({yest.isoformat()})美股因美國假日/週末休市,沒有新收盤數據。"
                   f"資料中的美股數字是 {us_last.isoformat()} 的收盤。**"
                   f"絕對不可寫「今天美股漲/跌」「昨晚美股收紅/黑」 — 要明說「昨晚美股因 X 休市,最近一次收盤是 {us_last.isoformat()}」。")

    # 今晚美股動作窗口(對稱台股的「今早 9:00 開盤」)
    if us_will_open_tonight:
        us_action_note = (f"✅ **今晚({td.isoformat()})美股將正常開盤(美東 9:30 = TW 21:30-22:30 之間,看夏令時間)。**"
                          f"美股每張 signal-card / stock-card 必須給「今晚開盤後該做什麼」的明確指示:"
                          f"「今晚開盤後若 $XXX 以下分批接」「突破 $XXX 才追」「跌破 $XXX 停損」「今晚財報前先觀望,等盤後出數字」。"
                          f"不可只寫「續抱」「觀望」這類沒有時間窗的字眼 — 用戶看的是「我今晚下班後該怎麼動」。")
    else:
        us_action_note = (f"⚠️ **今晚({td.isoformat()})美股休市,不會開盤。下次開盤是 {us_next_trading.isoformat()}。**"
                          f"美股部分只寫「持有觀察 / 等 {us_next_trading.isoformat()} 開盤後 X」,不可寫「今晚開盤」這類字眼。")

    tw_note = ""
    if not tw_open:
        tw_note = (f"⚠️ **今天({today_iso})台股休市,不會開盤。**"
                   f"資料中的台股數字是 {tw_last.isoformat()} 的收盤。"
                   f"不要寫「今早 9:00 開盤」「今日早盤」這類字眼 — 要明說「今天台股休市,本期重點放美股」。")

    return {
        "us_traded_last_session": us_traded,
        "us_will_open_tonight": us_will_open_tonight,
        "tw_will_open_today": tw_open,
        "us_last_trading_date": us_last.isoformat(),
        "us_next_trading_date": us_next_trading.isoformat(),
        "tw_last_trading_date": tw_last.isoformat(),
        "us_note": us_note,
        "us_action_note": us_action_note,
        "tw_note": tw_note,
    }


def _call_gemini(prompt: str, model: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("未設定 GEMINI_API_KEY")
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            # 2026-05-26 從 16000 → 32000:27 支持股 × ~600 tokens/卡 = 16k 上限剛好爆,
            # 任何持股多的用戶 signal-card 都會被截斷。提到 32k 留安全裕度。
            "maxOutputTokens": 32000,
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


def _call_claude(prompt: str) -> str:
    """Claude Haiku 4.5 作為付費後援(Gemini 全掛時用)。需要 ANTHROPIC_API_KEY。"""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 ANTHROPIC_API_KEY")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 16000,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


def _call_openai(prompt: str) -> str:
    """OpenAI gpt-4o-mini 作為最終付費後援(Claude 也掛時用)。需要 OPENAI_API_KEY。"""
    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 OPENAI_API_KEY")
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "max_tokens": 16000,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _llm_generate(prompt: str) -> str:
    """多 provider LLM 鏈:Gemini Flash → Gemini Lite → Claude Haiku → OpenAI gpt-4o-mini。
    四層 LLM,任一可用就成功 — deterministic fallback 在現實中應該永遠跑不到。
    2026-05-26:用戶要求不能有「最差情況」,LLM 路徑必須近 100%。"""
    last_err = None
    providers = []
    for model in GEMINI_MODELS:
        providers.append((f"gemini:{model}", lambda p, m=model: _call_gemini(p, m)))
    providers.append(("claude:haiku-4.5", _call_claude))
    providers.append(("openai:gpt-4o-mini", _call_openai))
    for name, fn in providers:
        try:
            out = fn(prompt)
            print(f"  [LLM] 使用 {name}")
            return out
        except Exception as e:
            last_err = e
            print(f"  [LLM] {name} 失敗({str(e)[:120]})")
    raise RuntimeError(f"所有 LLM provider 都失敗:{last_err}")


def get_personalized_subject(data: dict, us_stocks: list, tw_stocks: list, date: str) -> str:
    # 週六走 weekend recap → 主旨改成「本週回顧 + 下週重點」
    # 週一走 monday outlook → 主旨改成「週末重點 + 週一展望」,個股提及明示「上週五」
    from datetime import datetime, timezone, timedelta
    weekday = (datetime.now(timezone.utc) + timedelta(hours=8)).weekday()
    if weekday == 5:
        return f"📅 本週回顧 + 下週重點｜MarketDaily {date}"
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
    if weekday == 0:
        # 週一:基準是上週五收盤,主旨明寫「上週五」避免誤導
        if biggest_sym and biggest_pct >= 2:
            sym, pct = biggest_sym
            direction = "漲" if pct > 0 else "跌"
            return f"📅 上週五 {sym} {direction} {abs(pct):.1f}%+週一展望｜MarketDaily {date}"
        return f"📅 週末重點 + 週一展望｜MarketDaily {date}"
    if biggest_sym and biggest_pct >= 2:
        sym, pct = biggest_sym
        direction = "漲" if pct > 0 else "跌"
        # 台股早上 7 點還沒開盤,主旨要寫「昨日」;美股剛收盤可寫「今天」
        is_tw = sym in tw_market
        when = "昨日" if is_tw else "今天"
        return f"📊 你的 {sym} {when}{direction}了 {abs(pct):.1f}%｜財經日報 {date}"
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

    # signal-card 內把買/賣 verdict 拉到代號旁邊,讓「一眼看懂」效果更好
    # (原本 action-board 總覽已移除,改成直接在每張卡頂端標明買賣)
    _verdict_inline = {
        "buy":  "🟢 建議買入",
        "hold": "🟡 續抱持有",
        "sell": "🔴 建議賣出",
        "wait": "⚪ 暫時觀望",
    }
    _card_verdict_re = _re.compile(
        r'(<div class="signal-card (buy|hold|sell|wait)">\s*<div class="signal-card-top">\s*<span class="signal-ticker">[^<]+</span>)',
    )
    def _add_chip(m):
        full, verdict = m.group(1), m.group(2)
        label = _verdict_inline.get(verdict, "")
        chip = f'<span class="signal-verdict-chip {verdict}">{label}</span>'
        return f'{full}{chip}'
    html = _card_verdict_re.sub(_add_chip, html)

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


def generate_deterministic_fallback(data: dict, us_stocks: list, tw_stocks: list, mkt_status: dict) -> str:
    """無 LLM 的安全 fallback:純 Python 模板列出用戶持股事實 + 開盤狀態。
    當 LLM 兩次都 fail audit 時用,絕不會「今天台股漲」這類胡寫,因為完全沒有自由生成。
    內容稀疏但 100% 正確。寄出總比讓用戶缺信好。
    2026-05-26 用戶:「不能缺,也不能寄錯的給人」"""
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    today = data.get("date", "")
    parts = ['<div class="tldr"><div class="tldr-title">☕ 30 秒看完今天重點</div><ul>']
    parts.append('<li>⚠️ 今天 AI 個人化生成異常,這封是備援版本,只列基本事實不做主觀分析</li>')
    if mkt_status.get("us_traded_last_session"):
        parts.append(f'<li>昨晚美股({mkt_status["us_last_trading_date"]})已收盤,以下是你的美股持股表現</li>')
    else:
        parts.append(f'<li>昨晚美股因假日/週末休市,最近收盤 {mkt_status.get("us_last_trading_date", "?")}</li>')
    if mkt_status.get("tw_will_open_today"):
        parts.append('<li>今早 9:00 台股將開盤,以下是你的台股昨日收盤</li>')
    else:
        parts.append('<li>今天台股休市不開盤</li>')
    if mkt_status.get("us_will_open_tonight"):
        parts.append(f'<li>今晚美股將開盤(美東 9:30 = TW 21:30-22:30)</li>')
    else:
        parts.append(f'<li>今晚美股休市,下次開盤 {mkt_status.get("us_next_trading_date", "?")}</li>')
    parts.append('</ul></div>')

    parts.append('<div class="section-label">📊 你的持股(備援版)</div>')
    if us_stocks:
        parts.append('<div class="signal-grid">')
        for sym in us_stocks:
            d = us_market.get(sym)
            if d:
                chg = d.get("change_pct", 0)
                up = "up" if chg >= 0 else "down"
                arrow = "▲" if chg >= 0 else "▼"
                name = stock_names.display_name(sym)
                action = "等今晚開盤觀察價量" if mkt_status.get("us_will_open_tonight") else "等下個交易日"
                parts.append(
                    f'<div class="signal-card hold">'
                    f'<div class="signal-card-top">'
                    f'<span class="signal-ticker">{sym}</span>'
                    f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span>'
                    f'</div>'
                    f'<div class="signal-body">'
                    f'<div class="signal-reason">{name}({sym}) 昨晚收 ${d.get("price","?")} ,'
                    f'{action}。今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
                    f'</div></div>'
                )
            else:
                parts.append(
                    f'<div class="signal-card wait">'
                    f'<div class="signal-card-top"><span class="signal-ticker">{sym}</span></div>'
                    f'<div class="signal-body"><div class="signal-reason">'
                    f'{stock_names.display_name(sym)}({sym}) 今日無報價數據</div></div></div>'
                )
        parts.append('</div>')
    if tw_stocks:
        parts.append('<div class="signal-grid">')
        for sym in tw_stocks:
            d = tw_market.get(sym)
            if d:
                chg = d.get("change_pct", 0)
                up = "up" if chg >= 0 else "down"
                arrow = "▲" if chg >= 0 else "▼"
                name = stock_names.display_name(sym, d.get("name"))
                action = "等今早 9:00 開盤觀察價量" if mkt_status.get("tw_will_open_today") else "今天台股休市"
                parts.append(
                    f'<div class="signal-card hold">'
                    f'<div class="signal-card-top">'
                    f'<span class="signal-ticker">{sym}</span>'
                    f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span>'
                    f'</div>'
                    f'<div class="signal-body">'
                    f'<div class="signal-reason">{name}({sym}) 昨日收 ${d.get("price","?")} 元,'
                    f'{action}。今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
                    f'</div></div>'
                )
            else:
                parts.append(
                    f'<div class="signal-card wait">'
                    f'<div class="signal-card-top"><span class="signal-ticker">{sym}</span></div>'
                    f'<div class="signal-body"><div class="signal-reason">'
                    f'{stock_names.display_name(sym, d.get("name") if d else None)}({sym}) 今日無報價數據</div></div></div>'
                )
        parts.append('</div>')
    parts.append('<div class="signal-disclaimer">⚠️ 備援版本,僅為基本資料整理。主編已收到通知將盡速修復個人化分析。</div>')
    return "\n".join(parts)


DIGEST_EMAIL_MAX_HOLDINGS = 30  # email 版上限提到 30(原 12 太少)。Gmail 約 102KB 截斷,
# 30 張 signal-card + TLDR + 新聞應該還在範圍內。網頁完整版仍含全部不切。
# 2026-05-26 用戶炸:「使用者選擇每一個台股美股都要顯示」,原 12 等於把 27 支砍掉 15 支。

# 新手專區：開戶教學 + 名詞小辭典（靜態內容，附在輕度用戶日報底部）
ROOKIE_GUIDE_HTML = """
<div class="section-label">🎒 新手專區</div>
<div class="rookie-guide">
  <div class="rg-block">
    <div class="rg-head">🚀 還沒開始投資？三步驟上手</div>
    <div class="rg-step"><b>1. 開證券戶</b>：手機下載券商 App（台股如國泰、永豐；美股如 Firstrade、IBKR），線上開戶大約 10 分鐘。</div>
    <div class="rg-step"><b>2. 從小額開始</b>：第一次別投太多，用「賠掉也不影響生活」的金額練手感就好。</div>
    <div class="rg-step"><b>3. 定期定額</b>：設定每月固定買一點（例如每月 3000 元買 0050），不用猜時機，長期最穩。</div>
  </div>
  <div class="rg-block">
    <div class="rg-head">📖 看不懂的名詞？</div>
    <div class="rg-term"><b>停損</b>：股價跌到你設定的價位就賣出，避免賠更多。</div>
    <div class="rg-term"><b>目標價</b>：預期股價會漲到的價位，到了可以考慮獲利了結（賣出賺價差）。</div>
    <div class="rg-term"><b>ETF</b>：一籃子股票的組合（如 0050 ＝ 台灣前 50 大公司），買一張等於分散投資很多檔，新手最穩。</div>
    <div class="rg-term"><b>定期定額</b>：固定時間投入固定金額，漲跌都買，攤平成本、不用猜高低點。</div>
    <div class="rg-term"><b>藍籌股</b>：規模大、體質穩、大家都認識的公司股票（如蘋果、台積電）。</div>
    <div class="rg-term"><b>VIX 恐慌指數</b>：市場越害怕數字越高；20 以下算平靜，30 以上代表市場很緊張。</div>
  </div>
  <div class="rg-disclaimer">本專區為一般教學資訊，不構成投資建議；投資有風險，請評估自身狀況。</div>
</div>"""


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
    mkt_status = _market_status(date)

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
    # 個人化版本：用戶每一支持倉都要有操作訊號卡 — **絕對不切**,日報是主商品,
    # 用戶選的每一支台股美股都必須給「下一步」。波動大者排前面方便讀,但全留。
    # 2026-05-26 用戶炸:「使用者選擇每一個台股美股都要顯示下一步他們要做什麼」
    if has_holdings:
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)
    else:
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)[:5]

    signal_instruction = f"""
<div class="signal-header">
  <div class="signal-header-title">⚡ 詳細進出場計畫</div>
  <div class="signal-header-subtitle">用戶選的每一支台股美股,都列下一步要做什麼 · 1-2 週視角</div>
</div>
<div class="signal-grid">
**為以下每一支股票各生成一個 signal-card（共 {len(top_signal_stocks)} 支,一支都不能少、不能合併、不能省略,順序照列）**：{', '.join(top_signal_stocks)}
⚠️ 這份是用戶的主商品 — 他選的每一支都期待看到「下一步」,漏掉任一支用戶會炸。如果某支今日無報價數據,仍要生成 signal-card,用「📭 今日無報價」標示,並寫「等盤後數據出來後 X」這類動作。

每張卡格式（最外層 class 從 buy/hold/sell/wait 四選一，要跟結論一致）：
<div class="signal-card buy">
  <div class="signal-card-top">
    <span class="signal-ticker">代號</span>
    <span class="signal-day-move up">▲ +x.xx%</span>
    <div class="signal-score-block"><span class="signal-score">0-10</span><span class="signal-score-label">/ 10</span></div>
    <span class="signal-bias bullish">📈 BULLISH</span>
  </div>
  <div class="signal-body">
    <div class="signal-reason">**下一步要做什麼**:用白話講清楚這支股票「{'今早 9:00 開盤後' if mkt_status['tw_will_open_today'] else '下個交易日'}」(台股) 或「{'今晚開盤後' if mkt_status['us_will_open_tonight'] else '下個交易日'}」(美股) 該做什麼具體動作。動作必須是「買進 X / 加碼 X / 續抱 X / 減碼 X / 賣出 X / 等到 X 條件才動」其中一個,絕對禁止只寫「觀望」「先別動」「保守」沒附條件的虛詞。每張卡至少要有 1 個明確價位 + 1 個觸發條件(時間或事件)。例:「今晚開盤後若跌到 $580 以下,分批接 1/3 部位;若直接開高跳空,等回測 $590 再進」</div>
    <div class="signal-battle-plan">
      <div class="battle-row"><span class="battle-label">建議買價</span><span class="battle-val">$xxx–$xxx</span></div>
      <div class="battle-row"><span class="battle-label">賺錢目標</span><span class="battle-val up">$xxx</span></div>
      <div class="battle-row"><span class="battle-label">止損賣價</span><span class="battle-val down">$xxx</span></div>
    </div>
    <div class="signal-watch">👀 觀察重點：接下來最該盯的一件事（具體財報日 / 某個關鍵價位 / 某則消息後續）— 不可寫「持續觀察」這種空話</div>
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
- ‼️ 敢給 sell/wait：當該股有真實利空（估值過高 / 技術破位 / 重大利空消息 / 法人連續賣超），就要明確給 sell（強利空）或 wait（短中期不利但未到認賠程度），不要為了「政治正確」永遠 buy/hold。理由必須言之有物，不可只寫「短期波動大」這種空話
- 進場 / 目標 / 停損價位要落在該股目前股價的合理範圍，台股用台幣、美股用美元
- **signal-reason 內必須出現至少一個 $ 美元 / NT$ / 數字+元 / 時間窗(今早/今晚/盤後/財報前/X 月 X 日);三件都缺就是廢卡**
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

    # 市場氣氛白話框（所有人都有）
    mood_section = """<div class="section-label">🌡️ 今天市場氣氛</div>
<div class="mood-box">
  <div class="mood-emoji">（依今天 VIX、恐貪指數、大盤漲跌挑一個 emoji：😊 樂觀 / 😐 普通 / 😰 緊張）</div>
  <div class="mood-text">（一句白話：今天市場氣氛怎樣 + 新手該怎麼做，例如「氣氛偏樂觀，適合分批慢慢買進」「氣氛有點緊張，新手今天先別急著進場」）</div>
</div>"""

    indicator_block = """<div class="section-label">📊 市場情緒儀表板</div>
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
</div>"""

    sector_block = """<div class="section-label">🔄 板塊輪動：哪個板塊最強？</div>
<div class="sector-bar">
（根據板塊 ETF 資料，列出今日表現前三和後三，用 sector-item 格式，包含 sector-name 和 sector-move up/down）
例如：
  <div class="sector-item">
    <span class="sector-name">XLK 科技</span>
    <span class="sector-move up">▲ +2.1%</span>
    <span class="sector-comment">（一句話說為什麼）</span>
  </div>
（共 6 個，強弱各三）
</div>"""

    second_order_block = """<div class="section-label">🔗 二階思考：美股如何影響台灣？</div>
<div class="second-order">
（根據今天美股動向，分析對台灣供應鏈的傳導影響。例如：NVDA 漲 → CoWoS 封裝需求 → 台積電/日月光受惠。只寫真正有關聯的，沒有就不寫。2-3 條 bullet，繁體中文）
</div>"""

    # 新手精簡模式：拿掉中階區塊（原始數據儀表板、板塊輪動、二階思考）
    if is_beginner:
        indicator_section = ""
        sector_section = ""
        second_order_section = ""
    else:
        indicator_section = indicator_block
        sector_section = sector_block
        second_order_section = second_order_block

    prompt = f"""你是這位用戶的專屬財經顧問，說話生活化、直接、像朋友。這份報告是**專門為持有 {', '.join(all_holdings) if has_holdings else '各種股票的'} 的用戶客製化生成的**，不是通用報告。

【⏰ 時序紀律 — 違反 = 廢稿】
**這份日報在台灣時間早上 7:00 寄出，那時台股還沒開盤（台股 9:00 開盤、13:30 收盤）。**
- 美股：通常剛收盤不久（台灣時間 04:00 美股收盤），可以用「昨晚美股收紅/收黑」這類完成式口吻。
- 台股：**數據是昨日收盤**，今天 9:00 才開盤。**絕對禁止寫「今天台股已漲/已跌/超狂/大跌」這類盤中口吻**。要寫就寫：「昨日台股收 XXX」「今早開盤可留意 XXX」「9:00 開盤後若 XXX 就 XXX」「今日早盤策略」。看到「{date}」這個日期 = 台股還沒開盤的一天。
- 違反例：「今天台積電（2330）漲 3%！」← 廢稿（盤前不可能知道）
- 正確例：「台積電（2330）昨日收 XXX 元」「今早 9:00 開盤後留意 XXX 元支撐」

【⚠️ 今天的市場開盤狀態 — 絕對要遵守】
昨晚美股:{mkt_status['us_note'] or f"美股有開盤,數據是新鮮的,可寫「昨晚美股 XXX」。"}
今天台股:{mkt_status['tw_note'] or f"台股 9:00 將開盤,可寫「今早開盤」「今日早盤策略」。"}
今晚美股:{mkt_status['us_action_note']}

**雙市場動作對稱性:每張美股 signal-card 要給「今晚開盤後做什麼」(若今晚開盤),每張台股 signal-card 要給「今早 9:00 開盤後做什麼」(若今天開盤)。休市日只給「等下一個交易日 X」,不可寫「今晚/今早開盤」這類字眼。**
**規則：休市日的市場,不可在「30 秒看完今天重點」「大盤怎麼了」「持股本日動向」這幾個區塊把舊收盤當「今天/昨晚」寫,務必點明休市。**

【無幻覺原則 — 違反 = 廢稿】
- 所有內容只能基於以下提供的真實數據和新聞，不得憑空補充或使用訓練資料臆測
- 新聞標題、內文、URL 一律只能從下方「今日新聞」清單取用；URL 必須一字不差原樣複製，嚴禁自己拼湊或編造任何網址
- 找不到對應的真實新聞時，就不要寫那張新聞卡 / stock-news-item，絕對不要為了湊數量而捏造
- 如果某項資訊不足，就說「今日數據不足」，不要捏造

【個人化原則】
- TLDR 30秒重點：**用戶有台股持股時，4 條至少 1 條必須是台股相關**（昨日收盤動向 / 今早 9:00 開盤怎麼操作 / 對某檔持股的明確建議），不可全部都美股。{f"⚠️ 這位用戶持有台股：{', '.join(watchlist_tw)} — TLDR 一定要有他的台股動向。" if watchlist_tw else ""}
- 所有分析都圍繞用戶的持倉，大盤新聞只在跟他持倉有關時才詳細寫
- 給建議要明確：說「建議買進 $XXX 以下」「續抱直到 $XXX」「跌破 $XXX 停損」，**禁止只寫「先觀望」「先別動」「保守為上」這類沒附條件的虛詞**。要說「觀望」就必須附「等什麼價位/事件」（例：「先觀望，等跌到 $580 再分批接」「先觀望，等 6/1 財報出來再決定」）。
- 口語化，像在 Line 傳訊息，不是寫報告

【寫作風格】
- 讀者是完全不懂股票的新手：用最白話的方式講，少用術語；非用不可的術語（例如停損、殖利率、財報）第一次出現要用括號簡單解釋
- 每一支股票都要讓人立刻知道「該買、該賣、還是抱著」，且**動作必須附條件**（價位、事件、時間窗），不可只丟動詞
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
  <li>（最重要的事，一句話。{"用戶有台股 → 這條或下一條必須講台股動向（昨日收盤 / 今早開盤策略），台股口吻不可用「今天台股已 XX」" if watchlist_tw else "一句話"}）</li>
  <li>（第二重要的事{"，若上一條是美股，這條就要是台股" if watchlist_tw else ""}）</li>
  <li>（第三重要的事）</li>
  <li>（第四重要的事，如有）</li>
</ul>
</div>

{signal_instruction}
{rookie_section}

{mood_section}
{indicator_section}

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

{sector_section}

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

{second_order_section}

{personalized_news_instruction}

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
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Weekend Recap(週六專用:本週回顧 + 下週預告)──────────────
def generate_weekend_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                            email_safe: bool = False) -> str:
    """週六晨間日報:不講當日大盤(已收),改聚焦『本週回顧 + 下週重點』。"""
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
    us_news_text = _format_news(data.get("us_news", []), max_items=10)
    tw_news_text = _format_news(data.get("tw_news", []), max_items=8)
    date = data.get("date", "")

    holdings = (user_us_stocks or []) + (user_tw_stocks or [])
    has_holdings = bool(holdings)
    is_beginner = len(holdings) <= 4

    prompt = f"""你是這位用戶的專屬財經顧問。今天是**週六晨間**,美股週五已收盤、台股週五已收盤,週末兩天都不開盤。所以這份報告不講「今天大盤」,而是聚焦「本週發生了什麼 + 下週要看什麼」。

【無幻覺原則 — 違反就廢稿】
- 所有內容只能基於下方提供的真實市場數據和新聞,不得憑空補充或臆測
- 新聞 URL 必須一字不差原樣複製,嚴禁編造
- 找不到對應真實新聞就不要硬寫
- 如資訊不足,寫「本週資料不足」不要捏造

【個人化原則】
- 用戶持倉:{', '.join(holdings) if has_holdings else '尚未設定持股,以大盤龍頭股為例'}
- 內容要圍繞他的持股做本週復盤 + 下週展望
- 台股一律用公司名稱(可附代號),不要只報數字

【本週回顧(週一到週五已收盤)】
- 寫 3-4 段 highlights:本週最大事件、本週贏家/輸家、用戶持股本週表現
- 引用本週實際發生的新聞,連結原文

【下週看什麼(catalysts)】
- 從新聞中找出下週會發生的事件:財報日、Fed/央行講話、CPI/PPI 等經濟數據、地緣政治
- 條列 5-8 個 catalysts,標明日期與影響
- 如新聞中沒提到具體下週事件,寫「本週新聞中未明示下週重大事件,留意週一開盤反應」即可,不要捏造

【週末投資思考(1 段)】
- 給用戶一個本週末值得思考的問題或觀點(風險、配置、心態),簡短有力

【日期】{date}(週六)

【本週市場數據(以週五收盤為基準)】
{market_text}

【本週美股新聞】
{us_news_text}

【本週台股新聞】
{tw_news_text}

【輸出格式】嚴格回傳純 HTML,沿用平日日報 CSS class(.tldr, .news-card, .stock-card, .verdict.neutral, .watch-list 等),但內容主軸換成:
1. .tldr 區改成「📅 本週快訊」(3-4 條本週重點)
2. .section-label「本週回顧」+ 數張 .news-card 寫本週實際發生的大事
3. .section-label「下週 catalysts」+ .watch-list 列下週要看的事件 + 日期
4. .section-label「持股本週表現」+ .stock-card 寫用戶 holdings 的本週走勢
5. .verdict.neutral 結尾的「週末思考」

不要 markdown ```、不要在 .stock-card 內塞當日資料(改成本週區間)、不要寫「今日」「盤中」這類週六不該出現的字眼。
"""

    raw = _llm_generate(prompt)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Monday Outlook(週一專用:上週五收盤 + 週末新聞 + 本週展望 + Gap 警示)──────────────
def generate_monday_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                           email_safe: bool = False) -> str:
    """週一晨間日報:前兩天(週六、週日)沒開盤,所以基準是『上週五收盤』。
    重點:週末新聞累積 + 上週五收盤回顧 + 本週 catalysts + 週一開盤 gap 風險 +
    每檔持股仍給明確操作建議(買/抱/賣/觀望)。"""
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
    us_news_text = _format_news(data.get("us_news", []), max_items=10)
    tw_news_text = _format_news(data.get("tw_news", []), max_items=8)
    date = data.get("date", "")

    holdings = (user_us_stocks or []) + (user_tw_stocks or [])
    has_holdings = bool(holdings)
    is_beginner = len(holdings) <= 4

    # 算上週五日期(今天是週一,往前推 3 天)
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    tw_now = _dt.now(_tz.utc) + _td(hours=8)
    last_friday = (tw_now - _td(days=3)).strftime("%Y-%m-%d")

    default_us = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "TSM", "JPM"]
    watchlist_us = user_us_stocks if user_us_stocks else default_us
    watchlist_tw = user_tw_stocks if user_tw_stocks else []
    all_holdings = watchlist_us + watchlist_tw

    # 操作訊號卡的股票清單(用戶持倉優先,持倉超過 8 檔取波動最大前 8 檔)
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    all_market = {**us_market, **tw_market}
    def _abs_change(sym):
        d = all_market.get(sym, {})
        return abs(d.get("change_pct", 0))
    if has_holdings:
        signal_stocks = sorted(all_holdings, key=_abs_change, reverse=True)[:8]
    else:
        signal_stocks = ["AAPL", "MSFT", "NVDA", "TSLA"]

    signal_skeleton = f"""
<div class="signal-header">
  <div class="signal-header-title">💡 你的持股本週怎麼操作</div>
  <div class="signal-header-subtitle">上週五收盤位置 + 週末新聞 + 本週催化劑 · 給出明確動詞</div>
</div>
<div class="signal-grid">
為以下每一支股票各生成一張 signal-card(一支都不能少,順序照列):{', '.join(signal_stocks)}
每張卡完整格式(最外層 class 從 buy/hold/sell/wait 四選一,動詞對應:buy=買進加碼 / hold=抱緊 / sell=減碼賣出 / wait=今早觀望):
<div class="signal-card buy">
  <div class="signal-card-top">
    <span class="signal-ticker">代號</span>
    <span class="signal-day-move up">▲ +x.xx%(上週五單日)</span>
    <div class="signal-score-block"><span class="signal-score">0-10</span><span class="signal-score-label">/ 10</span></div>
    <span class="signal-bias bullish">📈 BULLISH</span>
  </div>
  <div class="signal-body">
    <div class="signal-reason">必須含 4 要素:①上週五收盤位置(例:上週五收 $XXX,週線 +X%)②週末新聞影響(例:週末傳出 OOO 對 XXX 屬利多/利空;若無新聞寫「週末無重大新聞」)③本週催化劑(例:本週四財報、Fed 週三開會)④為何給這個動作(例:故建議今早觀望前 30 分鐘是否守住 $XXX)。嚴禁寫「靜觀其變」「視情況」「再觀察看看」這類模糊詞 — 必須有明確動詞。</div>
    <div class="signal-battle-plan">
      <div class="battle-row"><span class="battle-label">建議買價</span><span class="battle-val">$xxx–$xxx</span></div>
      <div class="battle-row"><span class="battle-label">賺錢目標</span><span class="battle-val up">$xxx</span></div>
      <div class="battle-row"><span class="battle-label">止損賣價</span><span class="battle-val down">$xxx</span></div>
    </div>
    <div class="signal-watch">👀 本週要盯:接下來最該盯的一件事(財報日/Fed 講話/關鍵價位)</div>
    <div class="signal-meta">
      <span class="signal-badge buy">🟢 建議買入</span>
      <span class="signal-confidence">信心 XX%</span>
      <span class="signal-horizon">⏱ 本週視角</span>
    </div>
  </div>
</div>
規則:
- signal-ticker span 內只放純代號(例如 NVDA、2330),系統會自動補公司中英文名
- signal-day-move 填「上週五」單日漲跌幅,class(up/down)跟漲跌方向一致;上週五無數據就整個 signal-day-move span 省略
- 評分對應:8-10 強力買進 / 6-7 偏多可加碼 / 4-5 持有觀望 / 2-3 偏空減碼 / 0-1 建議賣出
- signal-badge 文字用「🟢 建議買入 / 🟡 續抱持有 / 🔴 建議賣出 / ⚪ 今早觀望」,class 對應 buy/hold/sell/wait,要跟最外層 class 一致
- ‼️ 敢給 sell/wait:當該股有真實利空(週末爆出重大利空新聞 / 上週五已破關鍵支撐 / 本週有負面催化劑),就要明確給 sell 或 wait,不要為了「政治正確」永遠 buy/hold。理由必須言之有物,點名具體利空消息或價位
- 進場/目標/停損價位要落在該股上週五收盤的合理範圍,台股台幣、美股美元
- 嚴禁省略 signal-header、signal-ticker、signal-reason 三個 span — 缺一個系統「一眼看懂」總覽就生不出來
</div>
<div class="signal-disclaimer">⚠️ AI 分析僅供參考,不構成投資建議</div>"""

    prompt = f"""你是這位用戶的專屬財經顧問。今天是**週一晨間**,週六週日股市都沒開盤,所以這份報告的數據基準是「**上週五({last_friday})收盤**」,內容主軸是:
1. 週末兩天累積的新聞(可能影響今早開盤)
2. 上週五美股/台股收盤回顧
3. 週一開盤可能跳空的風險(gap risk)
4. 本週重要事件預告(財報、Fed、CPI、台股除權息等)
5. 每檔持股的明確操作建議(必須給出動詞)

【無幻覺原則 — 違反就廢稿】
- 所有內容只能基於下方提供的真實市場數據和新聞,不得憑空補充或臆測
- 新聞 URL 必須一字不差原樣複製,嚴禁編造
- 找不到對應真實新聞就不要硬寫
- 「上週五收盤」價格直接引用下方市場數據,不可改動

【個人化原則】
- 用戶持倉:{', '.join(holdings) if has_holdings else '尚未設定持股,以大盤龍頭股為例'}
- 內容圍繞他的持股做:上週五表現 + 週末新聞影響 + 本週催化劑 + 操作建議
- 台股一律用公司名稱(可附代號),不要只報數字

【🚨 強制操作建議規則(週一最重要)】
就算前兩天沒開盤,**每檔持股仍必須給出明確操作動詞**。不可寫「靜觀其變」「視情況」「再觀察看看」這類模糊詞。
每張 signal-card 必須:
- class 用 "buy" / "hold" / "sell" / "wait" 其中一個(對應動詞:買進加碼 / 抱緊 / 減碼賣出 / 觀望)
- signal-reason 必須包含:
  ① 上週五收盤位置(例:「上週五收 $XXX,週線+X%」)
  ② 週末新聞影響(例:「週末傳出 OOO,對 XXX 屬利多/利空」),如無新聞寫「週末無重大新聞」
  ③ 本週要盯的催化劑(例:「本週四財報」、「Fed 週三開會」)
  ④ 為什麼是這個動作(例:「故建議今早觀望,等盤中前 30 分鐘看是否守住 $XXX」)
- 嚴禁只給動詞不給理由

【📅 週末新聞 + 週一 Gap 風險】
這是週一特有區塊,必須出現:
- 整理週末兩天(週六週日)累積的關鍵新聞,標題明示「週末發生」
- 根據週末新聞推估今早美股期貨/台股開盤偏多/偏空/中性的方向
- 對應到具體 playbook:例如「若 NVDA 開盤跳空向上 >2% → 等回拉接;跳空向下 → 分批接 $XXX-XXX」

【本週催化劑(必須出現)】
- 從新聞中找出本週會發生的事件:財報日、Fed 講話、CPI/PPI、台股除權息
- 條列 5-8 個 catalysts,標明日期(週幾)與對哪些持股有影響
- 如新聞中沒提到,寫「本週新聞中未明示具體事件,持續追蹤」即可,不要捏造

【日期】{date}(週一,基準=上週五 {last_friday} 收盤)

【上週五市場數據】
{market_text}

【週末美股新聞(週六週日累積)】
{us_news_text}

【週末台股新聞(週六週日累積)】
{tw_news_text}

【輸出格式】嚴格回傳純 HTML,沿用平日日報 CSS class,順序如下:
1. .tldr 區改成「📅 週一展望」標題,列 3-4 條:①週末最大事件 ②上週五收盤摘要 ③本週要看什麼 ④今早 gap 方向
2. .section-label「📰 週末重點新聞」+ 數張 .news-card,標題明示「週末發生」,有影響個股就掛 impact-stock
3. .section-label「📊 上週五收盤回顧」+ .market-summary,**所有數據敘述都要說「上週五」不可寫「今天」**
4. .section-label「⚠️ 週一開盤 Gap 風險」+ 一張 .verdict.SENTIMENT 卡片,寫明開盤方向 + 具體 playbook
5. .section-label「📅 本週催化劑」+ .watch-list 列出本週事件 + 日期
6. **持股操作訊號卡(必須完整輸出下方 signal-skeleton 模板)**:
{signal_skeleton}
7. .verdict.neutral 結尾「週一心法」,提醒週一通常波動大、可觀察前 30 分鐘再進場

不要 markdown ```、不要寫「今天大盤」這類週一早上不該出現的字眼(因為現在還沒開盤),改用「上週五」「今早開盤前」「本週」。
"""

    raw = _llm_generate(prompt)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result
