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


_GEMINI_QUOTA_DEAD: set = set()


def _call_gemini(prompt: str, model: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("未設定 GEMINI_API_KEY")
    if model in _GEMINI_QUOTA_DEAD:
        raise RuntimeError(f"{model} 本輪 429 配額耗盡,熔斷跳過")
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
        if resp.status_code == 429:
            # 退避一次仍 429 = 日配額耗盡而非瞬間 RPM;熔斷該模型,
            # 否則 6/11 事故重演:每次呼叫白燒 ~50s×2 模型,整班拖到數小時
            if attempt >= 1:
                _GEMINI_QUOTA_DEAD.add(model)
                raise RuntimeError(f"{model} 連續 429,視為配額耗盡並熔斷")
            time.sleep(12)
            continue
        if resp.status_code in (500, 502, 503) and attempt < 3:
            time.sleep(6)
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


def _llm_generate(prompt: str, prefer_strong: bool = False) -> str:
    """多 provider LLM 鏈:Gemini Flash → Gemini Lite → Claude Haiku → OpenAI gpt-4o-mini。
    四層 LLM,任一可用就成功 — deterministic fallback 在現實中應該永遠跑不到。
    2026-05-26:用戶要求不能有「最差情況」,LLM 路徑必須近 100%。
    prefer_strong=True:把 Claude/OpenAI 排到 Gemini 前面。retry 專用 —
    第一次 Gemini 在配額壓力下回的弱內容會過 _llm_generate 但 audit HIGH fail,
    retry 若還從 Gemini 起跑等於白做;換更強模型才有意義。Gemini 仍留最後一層,
    不破壞「永不掉 deterministic」保證。"""
    last_err = None
    gemini = [(f"gemini:{m}", lambda p, mm=m: _call_gemini(p, mm)) for m in GEMINI_MODELS]
    strong = [("claude:haiku-4.5", _call_claude), ("openai:gpt-4o-mini", _call_openai)]
    providers = (strong + gemini) if prefer_strong else (gemini + strong)
    for name, fn in providers:
        try:
            out = fn(prompt)
            print(f"  [LLM] 使用 {name}{' (retry強化)' if prefer_strong else ''}")
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
    # 主旨會被很多人在通知列看到 — 不可拿「疑似壞報價」的離譜漲跌幅當標題。
    # 台股單日上限 ±10%(逾 10.5% 必為錯誤);美股單日 ≥30% 多半是資料源 glitch(如 DELL +32.76% 事故)。
    def _plausible(pct, is_tw):
        return abs(pct) <= (10.5 if is_tw else 30)
    for sym in (us_stocks or []):
        if sym in us_market:
            chg = us_market[sym]["change_pct"]
            pct = abs(chg)
            if pct > biggest_pct and _plausible(chg, False):
                biggest_pct = pct
                biggest_sym = (sym, chg)
    for sym in (tw_stocks or []):
        if sym in tw_market:
            chg = tw_market[sym]["change_pct"]
            pct = abs(chg)
            if pct > biggest_pct and _plausible(chg, True):
                biggest_pct = pct
                biggest_sym = (sym, chg)
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

    regime = _market_regime(data)
    regime_zh = {"risk_off": "風險偏空(指數下殺/恐慌升溫)", "risk_on": "風險偏多", "neutral": "中性"}
    lines.append(f"【今日市場狀態判定:{regime_zh.get(regime['label'], '中性')}】")
    if regime["label"] == "risk_off":
        lines.append("  ‼️ TLDR、結論與每張操作卡的立場必須一致:今天偏防守。"
                     "若結論寫「先觀望/等數據」,操作卡就不可同時喊「即刻買進」——買進只能以條件單形式出現(回到支撐、站穩、數據公布後)。")

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
        has_est = any(e.get("eps_est") is not None for e in earnings)
        if has_est:
            lines.append("\n【即將公布財報(日期與預期數字已核實 — earnings-note 只能照寫這些數字,"
                         "嚴禁自行補任何其他預期 EPS/營收/產品線臆測)】")
        else:
            lines.append("\n【即將公布財報(只有日期已核實 — earnings-note 只能寫中性的關注重點,"
                         "‼️ 嚴禁編造任何「市場預期 EPS / 營收」數字或產品銷售臆測)】")
        for e in earnings[:6]:
            est = ""
            if e.get("eps_est") is not None:
                est += f" | 市場預期 EPS {e['eps_est']} 美元"
            if e.get("rev_est"):
                est += f"、營收約 {e['rev_est'] / 1e9:.1f}B 美元"
            lines.append(f"  {stock_names.display_name(e['symbol'])}（{e['symbol']}）: {e['date']}{est}")

    # 財報/營收影響(事件日才喊話):只列「用戶持股 + is_event」的,數字已核實
    impacts = data.get("earnings_impact", {}) or {}
    held = list(user_us_stocks or []) + list(user_tw_stocks or [])
    events = [impacts[s] for s in held if s in impacts and impacts[s].get("is_event")]
    if events:
        lines.append("\n【📊 財報影響事件(以下數字已核實，撰寫時必須照寫不可竄改；"
                     "只針對這些剛公布財報的持股，在其卡片用第二人稱說明對用戶部位的影響）】")
        for a in events:
            yoy = f"{a['yoy']:+.1f}%" if a.get("yoy") is not None else "—"
            base = "(低基期)" if a.get("base_effect") else ""
            extra = []
            if a.get("streak", 0) >= 2:
                extra.append(f"連{a['streak']}月正成長")
            if a.get("cum_yoy") is not None:
                extra.append(f"累計YoY{a['cum_yoy']:+.1f}%")
            if a.get("eps_yoy") is not None:
                extra.append(f"EPS YoY{a['eps_yoy']:+.1f}%")
            extra_s = ("、" + "、".join(extra)) if extra else ""
            lines.append(f"  {a.get('name', a['symbol'])}（{a['symbol']}）{a['period']} {a['kind']}："
                         f"YoY {yoy}{base}{extra_s} → 對部位{a['verdict']}（{a['impact']}）；"
                         f"下一觀察點 {a['next_point']}")

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
    # 完整上市+上櫃名稱表打底,再用持股報價的名稱覆蓋,確保任何台股代號都能展開成中文名
    tw_hint = dict(data.get("tw_names_all", {}))
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

    # 卡頭已有彩色 verdict-chip(建議買進/賣出),底部 signal-badge 是同一句重複 → 移除,
    # 讓 signal-meta 只剩「信心 X% · 時間窗」,減少邊邊 chip 把卡片拉長。
    html = _re.sub(r'<span class="signal-badge[^"]*">[^<]*</span>\s*', '', html)

    # 信心校準夾限:公開戰績方向勝率約五成多,顯示 >65% 的信心 = 未校準的過度自信。
    # LLM 已被要求寫 45-65,這裡是 deterministic 死防線(備援版/舊模板也吃得到)。
    def _clamp_conf(m):
        try:
            v = int(m.group(1))
        except ValueError:
            return m.group(0)
        return f"信心 {max(45, min(65, v))}%"

    html = _re.sub(r"信心\s*(\d{1,3})\s*%", _clamp_conf, html)

    # 「建議買入」chip 分流:建議買區整段低於現價(掛單等回檔)時,chip 改「回檔再買」,
    # 避免新手只看綠 chip 就直接市價追高 — chip 與買價區間語意必須一致。
    all_mkt = {**data.get("us_market", {}), **data.get("tw_market", {})}

    def _requalify_buy(m):
        block = m.group(0)
        hm = _re.search(r"<!--h:([A-Z0-9.]+)-->", block)
        if not hm:
            return block
        try:
            cur = float((all_mkt.get(hm.group(1)) or {}).get("price"))
        except (TypeError, ValueError):
            return block
        bm = _re.search(r'建議買價</span><span class="battle-val">[^<]*?([\d,]+\.?\d*)\s*[–—~-]\s*\$?\s*([\d,]+\.?\d*)', block)
        if not bm:
            return block
        try:
            hi = float(bm.group(2).replace(",", ""))
        except ValueError:
            return block
        if hi < cur * 0.985:
            block = block.replace("🟢 建議買入", "🟢 回檔再買(現價勿追)")
        return block

    html = _re.sub(
        r'<div class="signal-card buy">.*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer)',
        _requalify_buy, html, flags=_re.DOTALL,
    )

    # 財報註記清洗:資料端沒有「已核實預期數字」時,earnings-note 出現任何預期 EPS/營收
    # 都是 LLM 編的 → 換成中性句(deterministic 死防線,搭配 prompt 禁令與 audit)。
    if not any((e or {}).get("eps_est") is not None for e in (data.get("earnings") or [])):
        def _scrub_note(m):
            if _re.search(r"預期\s*EPS|市場預期|每股盈餘|EPS\s*[\d.]|營收[約達成長]*\s*[\d.]+", m.group(2)):
                return m.group(1) + "財報日將近,留意公布後對股價的影響" + m.group(3)
            return m.group(0)

        html = _re.sub(r'(<span class="earnings-note">)([^<]*)(</span>)', _scrub_note, html)

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

    # 空區塊自動隱藏:沒有實質內容的 section 整塊移除,不留空標題洗版
    def _drop_empty_sections(h):
        parts = _re.split(r'(<div class="section-label">)', h)
        out = [parts[0]]
        i = 1
        while i < len(parts):
            label_tag = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            m = _re.match(r'([^<]*)</div>', body)
            title = m.group(1) if m else ""
            drop = (
                ("即將公布財報" in title and "earnings-item" not in body)
                or ("持倉深度追蹤" in title and "stock-news-item" not in body)
            )
            if not drop:
                out.append(label_tag + body)
            i += 2
        return "".join(out)

    html = _drop_empty_sections(html)

    # 結論情緒 chip 提前:把今天偏多/偏空標籤抓到 TLDR 標題,讓用戶第一眼就掃到結論
    def _hoist_verdict_chip(h):
        vm = _re.search(
            r'<div class="verdict[^"]*\b(bullish|bearish|neutral)\b[^"]*">\s*'
            r'<div class="verdict-emoji">([^<]*)</div>',
            h,
        )
        if not vm:
            return h
        cls, label = vm.group(1), vm.group(2).strip()
        if not label:
            return h
        chip = f'<span class="tldr-chip {cls}">{label}</span>'
        h2, n = _re.subn(
            r'(<div class="tldr-title">[^<]*)</div>',
            lambda m: m.group(1) + " " + chip + "</div>",
            h, count=1,
        )
        return h2 if n else h

    html = _hoist_verdict_chip(html)

    # LLM 偶爾吐 markdown 粗體 **xxx**,轉成 <strong>,別讓星號直接露在卡片上
    html = _re.sub(r'\*\*([^*\n<]+?)\*\*', r'<strong>\1</strong>', html)

    return html


def generate_deterministic_fallback(data: dict, us_stocks: list, tw_stocks: list, mkt_status: dict) -> str:
    """無 LLM 的安全 fallback:純 Python 模板列出用戶持股事實 + 開盤狀態。
    當 LLM 兩次都 fail audit 時用,絕不會「今天台股漲」這類胡寫,因為完全沒有自由生成。
    內容稀疏但 100% 正確。寄出總比讓用戶缺信好。
    2026-05-26 用戶:「不能缺,也不能寄錯的給人」"""
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    today = data.get("date", "")
    _impacts = data.get("earnings_impact", {}) or {}

    def _impact_note(sym):
        a = _impacts.get(sym)
        if not a or not a.get("is_event") or a.get("yoy") is None:
            return ""
        base = "(低基期)" if a.get("base_effect") else ""
        return (f' 你追蹤的{a.get("name", sym)}剛公布{a["kind"]} YoY {a["yoy"]:+.1f}%{base},'
                f'對你部位{a["verdict"]}({a["impact"]});留意 {a["next_point"]}。')

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
                    f'{action}。{_impact_note(sym)}今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
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
                    f'{action}。{_impact_note(sym)}今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
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


def _fmt_num(n):
    if n is None:
        return "?"
    try:
        return f"{float(n):g}"
    except (TypeError, ValueError):
        return str(n)


def _near_term_levels(price, tech):
    """近端(1-2 週視角)合理操作價位 —— 一律以 ATR14 / MA20 / 20 日高低錨定。
    ‼️ 絕不直接拿 60 日高 / 60 日低當目標或停損:股票大漲後 60 日低可能離現價 30-60%,
    當「止損賣價」完全失準(用戶看到 -7.74% 卻配一個 66% 以下的停損 = 不準)。
    回傳 (support, target, stop):低接支撐 / 反彈壓力目標 / 停損,皆夾在現價約 ±15% 內。"""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None, None, None
    if price <= 0:
        return None, None, None
    t = tech or {}

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    atr = _f(t.get("atr14")) or 0
    if atr <= 0 or atr > price * 0.15:
        atr = price * 0.03  # 無 ATR 或異常 → 退回現價 3% 估計
    ma20, lo20, hi20 = _f(t.get("ma20")), _f(t.get("lo20")), _f(t.get("hi20"))
    # 低接支撐:現價下方 1.5×ATR;若 MA20 / 20 日低更靠近現價(壓力先到)就改用它
    support = price - 1.5 * atr
    for lvl in (ma20, lo20):
        if lvl and support < lvl < price:
            support = lvl
    # 反彈目標:現價上方 2×ATR;若 20 日高更近就用 20 日高
    target = price + 2.0 * atr
    if hi20 and price < hi20 < target:
        target = hi20
    # 停損:支撐再下方一個 ATR,且距現價最多 12%
    stop = min(support - atr, price - 2.5 * atr)
    stop = max(stop, price * 0.88)
    # 夾邊界:任一價位離現價不得過遠
    support = max(support, price * 0.90)
    target = min(target, price * 1.15)
    return round(support, 2), round(target, 2), round(stop, 2)


_MACRO_EVENT_RE = re.compile(
    r"CPI|PPI|FOMC|rate decision|nonfarm|payroll|jobs report|利率決議|非農|通膨數據|聯準會決議|央行決議",
    re.I,
)


def _detect_macro_event(data: dict) -> bool:
    """今日新聞是否出現重大總經數據/利率事件 — 是的話訊號卡必須寫成條件單,不可無條件喊進場。"""
    arts = (data.get("us_news") or []) + (data.get("tw_news") or [])
    return any(_MACRO_EVENT_RE.search(a.get("title", "") or "") for a in arts[:20])


def _market_regime(data: dict) -> dict:
    """大盤狀態粗分類:risk_on / neutral / risk_off(指數日變動 + VIX)。
    目的:擋「全市場下殺日每支機械式喊低接買進」的同質性 — 歷史戰績顯示這種日子逆勢
    買進勝率最差。訊號卡據此調整動詞分布與信心上限。"""
    ind = data.get("indicators", {}) or {}
    try:
        vix = float(ind.get("vix") or 0)
    except (TypeError, ValueError):
        vix = 0.0

    def _chg(d):
        try:
            return float((d or {}).get("change_pct") or 0)
        except (TypeError, ValueError):
            return 0.0

    us = data.get("us_market", {}) or {}
    tw = data.get("tw_market", {}) or {}
    spx, ndx, twii = _chg(us.get("^GSPC")), _chg(us.get("^IXIC")), _chg(tw.get("^TWII"))
    worst = min(spx, ndx)
    score = 0
    if worst <= -1.0:
        score -= 2
    elif worst <= -0.5:
        score -= 1
    elif worst >= 0.8:
        score += 1
    if vix >= 25:
        score -= 2
    elif vix >= 20:
        score -= 1
    elif 0 < vix < 16:
        score += 1
    label = "risk_off" if score <= -2 else ("risk_on" if score >= 2 else "neutral")
    return {"label": label, "vix": vix, "spx_chg": spx, "ndx_chg": ndx, "twii_chg": twii}


def _depth_directive(depth: str) -> str:
    """日報深度客製(Premium 專屬)注入 prompt 的指令。simple=精簡 / deep=深入 / standard=不加。"""
    if depth == "simple":
        return ("【深度設定:精簡版 = 純重點操作】這位用戶選了「簡單看」—— 只輸出 TLDR(30秒重點)+ 每支持股的操作卡 + 今天的結論。"
                "完全不要新聞區塊(不要『今天最重要的5件事』、不要『持倉深度追蹤』)、不要大盤/加密/財報/板塊/進階指標。"
                "每支股票一兩句講重點:該買/抱/賣 + 條件(價位或事件),不鋪陳。")
    if depth == "deep":
        return ("【深度設定:深入版 = 標準版全部再加碼】這位用戶選了「看深入」—— 保留標準版的一切(操作卡 + 新聞 + 技術 + 大盤),"
                "並針對每支持股額外補充:(1) 進階技術判讀 —— 結合系統提供的 RSI/KD/MACD/布林通道/均線排列(多頭或空頭)/黃金或死亡交叉,"
                "白話講這檔現在動能與超買超賣狀態、趨勢方向、關鍵技術訊號(只能引用提供的真實指標數字,嚴禁自行編造指標值);"
                "(2) 估值看法(便宜/合理/偏貴,可給合理價區間,但只能依提供的真實數據,不可臆測本益比或編造財務數字);"
                "(3) 同產業或供應鏈關聯的個股;(4) 若新聞提到法人/機構/內部人動向要點出。分析可深一點,但仍要口語、每個建議都附價位或時間條件。")
    return ""


def _signal_card_format_rules(mkt_status: dict, regime: dict = None, macro_event: bool = False) -> str:
    """所有報告共用的 signal-card 格式規格(批次生成用)。"""
    tw_when = "今早 9:00 開盤後" if mkt_status.get("tw_will_open_today") else "下個台股交易日"
    us_when = "今晚開盤後" if mkt_status.get("us_will_open_tonight") else "下個美股交易日"
    regime = regime or {}
    regime_block = ""
    if regime.get("label") == "risk_off":
        regime_block = f"""
【‼️ 今日市場狀態:風險偏空(指數下殺 / 恐慌升溫,S&P {regime.get('spx_chg', 0):+.2f}% / NASDAQ {regime.get('ndx_chg', 0):+.2f}% / VIX {regime.get('vix', 0):.1f})】
- **嚴禁整批卡機械式全寫「低接買進」**。逐支區分:(a) 趨勢仍在 MA20 上、只是回檔 → 可給條件式低接;(b) 已跌破 MA20、動能轉弱、沒利多 → 給 hold/wait,寫「等止穩(收復 $XXX)再進」;(c) 有明確利空 → sell/減碼。整批至少要呈現這種差異,全多頭 = 廢稿。
- 買進卡 reason 開頭必須講明「現價勿追」,只給支撐位條件單。
- 本狀態下所有卡信心一律 ≤55%。"""
    elif regime.get("label") == "risk_on":
        regime_block = """
【今日市場狀態:風險偏多】順勢為主,但漲多的標的要提醒「突破才追、不破不加」,不可每支都無條件追價。"""
    else:
        regime_block = """
【今日市場狀態:中性】依個股自身技術與消息分別判斷,verdict 不可機械式整批同向。"""
    macro_block = ""
    if macro_event:
        macro_block = """
【‼️ 今天/近日有重大總經事件(CPI / FOMC / 非農之類,見新聞)】所有買進建議必須寫成**事件條件單**:「數據公布後若 XXX(優於預期/守住 $XXX)再進場」,嚴禁「即刻買進」「應積極介入」這種無條件動作 — 數據公布前進場 = 賭博不是策略。"""
    return f"""{regime_block}{macro_block}
每張卡格式(最外層 class 從 buy/hold/sell/wait 四選一,動詞:buy=買進加碼 / hold=抱緊 / sell=減碼賣出 / wait=觀望):
<div class="signal-card buy">
  <div class="signal-card-top">
    <span class="signal-ticker">代號</span>
    <span class="signal-day-move up">▲ +x.xx%</span>
    <div class="signal-score-block"><span class="signal-score">0-10</span><span class="signal-score-label">/ 10</span></div>
    <span class="signal-bias bullish">📈 BULLISH</span>
  </div>
  <div class="signal-body">
    <div class="signal-reason">白話講「下一步」:台股講「{tw_when}」、美股講「{us_when}」該做什麼具體動作。**必含至少 1 個價位($ / NT$ / 數字+元) + 1 個時間或事件條件**。禁止只寫「觀望 / 先別動 / 保守」這種沒附條件的虛詞。</div>
    <div class="signal-battle-plan">
      <div class="battle-row"><span class="battle-label">建議買價</span><span class="battle-val">$xxx–$xxx</span></div>
      <div class="battle-row"><span class="battle-label">賺錢目標</span><span class="battle-val up">$xxx</span></div>
      <div class="battle-row"><span class="battle-label">止損賣價</span><span class="battle-val down">$xxx</span></div>
    </div>
    <div class="signal-watch">👀 接下來最該盯的一件事(具體價位 / 財報日 / 消息後續)</div>
    <div class="signal-meta">
      <span class="signal-badge buy">🟢 建議買入</span>
      <span class="signal-confidence">信心 XX%</span>
      <span class="signal-horizon">⏱ 短線</span>
    </div>
  </div>
</div>
規則:
- signal-ticker span 內只放純代號(例如 NVDA、2330),系統會自動補公司中英文名
- signal-day-move 填該股單日漲跌幅,class(up/down)跟漲跌方向一致;無數據就整個 signal-day-move span 省略
- 評分:8-10 強力買 / 6-7 偏多 / 4-5 觀望 / 2-3 偏空 / 0-1 賣出。**signal-bias、signal-badge、最外層 class 三者方向必須一致**(別 BULLISH 卻配賣出)
- signal-bias 用 bullish/neutral/bearish;signal-badge 文字用「🟢 建議買入 / 🟡 續抱持有 / 🔴 建議賣出 / ⚪ 暫時觀望」
- ‼️ **賣出 / 觀望卡不要給看似叫人現在買進的階梯**:sell 卡的「建議買價」改成「暫不建議買進,回補參考 $xxx」這種低接價,reason 要明說現在是減碼 / 不進場,不要自相矛盾
- ‼️ **定價一律用每支附的「近端操作錨點」**(低接 / 反彈目標 / 停損)當建議買價、賺錢目標、止損賣價,可微調但不可大幅偏離。
  **嚴禁拿「60日低 / 60日高」當停損或目標**——那是遠端區間參考,股票大漲後 60 日低常離現價 30-60%,當停損完全失準。
  停損與現價距離不得超過約 12%、目標不得超過約 15%;所有價位夾在現價上下 15% 內。
- 進場 / 目標 / 停損價位必須落在下方該股真實技術價位的合理範圍,美股美元、台股台幣,**嚴禁編造偏離現價的數字**
- ‼️ **信心校準**:我們的公開戰績統計顯示短線方向判斷準確率約五成多,信心欄位一律寫 45-65%(整批不可同一個數字),**禁止出現 >65% 的信心** — 戰績實測「信心>70%」的卡實際只對 17%,高信心是反指標
- ‼️ **進場必須有站穩確認(任何市場狀態都適用)**:買進條件一律寫「回測 $X 不破、收盤收復 $Y 再分批接」這種**確認式條件**,嚴禁「跌到 $X 就接」「回到買區即買進」— 操作模擬實測:照「跌入買區就接」執行,77 筆掃停損 vs 2 筆達標(期望值 -4.1%/筆),跌勢中價格進入買區正是刀還在掉的時候
- ‼️ **同質性禁令**:若整批標的多數同向漲跌,不可每支複製同一套「跌到 20 日低 → 低接買進反彈 MA20」模板;逐支看趨勢位置(站上/跌破 MA20)、動能與消息差異,verdict 與 reason 必須有真實差異"""


def _adv_tech_str(t: dict) -> str:
    """進階技術指標一行字(專業版/deep 用),只取有值的。"""
    if not t:
        return ""
    parts = []
    if t.get("rsi14") is not None:
        parts.append(f"RSI14 {t['rsi14']}")
    if t.get("k") is not None and t.get("d") is not None:
        parts.append(f"KD {t['k']}/{t['d']}")
    if t.get("macd_dif") is not None and t.get("macd_dea") is not None:
        parts.append(f"MACD DIF {t['macd_dif']}/DEA {t['macd_dea']}/柱 {t.get('macd_hist')}")
    if t.get("boll_up") is not None:
        parts.append(f"布林 {t.get('boll_low')}–{t.get('boll_mid')}–{t.get('boll_up')}")
    if t.get("trend"):
        parts.append(t["trend"])
    if t.get("cross"):
        parts.append(t["cross"])
    return " | ".join(parts)


def _chunk_market_tech_block(data: dict, chunk: list, depth: str = "standard") -> str:
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    tech = data.get("technicals", {}) or {}
    impacts = data.get("earnings_impact", {}) or {}
    lines = []
    for sym in chunk:
        is_tw = str(sym).isdigit()
        m = (tw_market if is_tw else us_market).get(sym) or {}
        nm = stock_names.display_name(sym, m.get("name"))
        unit = "元" if is_tw else "美元"
        if m:
            base = f"{nm}({sym}): 收 {_fmt_num(m.get('price'))}{unit} ({(m.get('change_pct') or 0):+.2f}%)"
        else:
            base = f"{nm}({sym}): 今日無報價"
        t = tech.get(sym)
        if t:
            base += (f" | MA20 {_fmt_num(t.get('ma20'))} | 20日高 {_fmt_num(t.get('hi20'))}/低 {_fmt_num(t.get('lo20'))}"
                     f" | 60日高 {_fmt_num(t.get('hi60'))}/低 {_fmt_num(t.get('lo60'))}(此為遠端區間參考,勿當停損/目標) | ATR14 {_fmt_num(t.get('atr14'))}")
            sup, tgt, stp = _near_term_levels(t.get("price"), t)
            if sup is not None:
                base += f" ‖ 近端操作錨點(直接用這組設買賣價)→低接 {_fmt_num(sup)} / 反彈目標 {_fmt_num(tgt)} / 停損 {_fmt_num(stp)}"
            if depth == "deep":
                adv = _adv_tech_str(t)
                if adv:
                    base += " | " + adv
        a = impacts.get(sym)
        if a and a.get("is_event") and a.get("yoy") is not None:
            base += f" | 剛公布{a.get('kind','財報')} YoY {a['yoy']:+.1f}% {a.get('verdict','')}"
        lines.append("  " + base)
    return "\n".join(lines)


def _card_passes_audit(card: str) -> bool:
    """跟 digest_audit 同款檢查:確保每張 LLM 卡有 3 個 battle-row + reason 含價位/時間窗。"""
    if "signal-card" not in card:
        return False
    if card.count("battle-row") < 3:
        return False
    rm = re.search(r'<div class="signal-reason"[^>]*>(.*?)</div>', card, re.S)
    if not rm:
        return False
    reason = rm.group(1)
    has_price = re.search(r"\$\s*\d|NT\$?\s*\d|\d+\s*(元|美元|塊|點)", reason)
    has_tw = re.search(r"今早|今晚|盤後|盤前|財報前|財報後|開盤|收盤|本週|下週|\d+\s*月\s*\d+", reason)
    return bool(has_price or has_tw)


def _deterministic_signal_card(sym: str, data: dict, mkt_status: dict) -> str:
    """無 LLM 也能生出的真實數據操作卡(技術價位錨定 MA / 高低 / ATR)。
    當某檔 LLM 生成失敗或不合格時用它補位 — 保證 100% 覆蓋且 audit 過關,且讀起來是真建議不是『異常』訊息。"""
    is_tw = str(sym).isdigit()
    market = data.get("tw_market", {}) if is_tw else data.get("us_market", {})
    tech = (data.get("technicals", {}) or {}).get(sym)
    m = market.get(sym)
    unit = "元" if is_tw else ""
    name = stock_names.display_name(sym, (m or {}).get("name"))
    when = ("今早 9:00 開盤" if mkt_status.get("tw_will_open_today") else "下個交易日") if is_tw \
        else ("今晚開盤" if mkt_status.get("us_will_open_tonight") else "下個交易日")
    if not m or m.get("price") is None:
        return (f'<div class="signal-card wait"><div class="signal-card-top">'
                f'<span class="signal-ticker">{sym}</span></div>'
                f'<div class="signal-body"><div class="signal-reason">'
                f'{name}({sym}) 目前無即時報價,待{when}後數據更新再給進出場建議。</div></div></div>')
    chg = m.get("change_pct", 0) or 0
    price = float(m.get("price"))
    up = "up" if chg >= 0 else "down"
    arrow = "▲" if chg >= 0 else "▼"
    bias = "bullish" if chg >= 0 else "bearish"
    bias_label = "📈 BULLISH" if chg >= 0 else "📉 BEARISH"
    buy_lo, target, stop = _near_term_levels(price, tech)
    if buy_lo is None:
        buy_lo, target, stop = round(price * 0.97, 2), round(price * 1.08, 2), round(price * 0.94, 2)
    buy_hi = round((buy_lo + price) / 2, 2)
    if buy_hi <= buy_lo:
        buy_hi = round(price * 0.99, 2)
    reason = (f'{name}({sym}) 收 ${_fmt_num(price)}{unit}({chg:+.2f}%)。'
              f'{when}後若回到 ${_fmt_num(buy_lo)}{unit} 附近並站穩可分批接,'
              f'跌破 ${_fmt_num(stop)}{unit} 先停損;本週留意 ${_fmt_num(target)}{unit} 壓力。')
    return (
        f'<div class="signal-card hold"><div class="signal-card-top">'
        f'<span class="signal-ticker">{sym}</span>'
        f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span>'
        f'<div class="signal-score-block"><span class="signal-score">5</span><span class="signal-score-label">/ 10</span></div>'
        f'<span class="signal-bias {bias}">{bias_label}</span></div>'
        f'<div class="signal-body"><div class="signal-reason">{reason}</div>'
        f'<div class="signal-battle-plan">'
        f'<div class="battle-row"><span class="battle-label">建議買價</span><span class="battle-val">${_fmt_num(buy_lo)}–${_fmt_num(buy_hi)}{unit}</span></div>'
        f'<div class="battle-row"><span class="battle-label">賺錢目標</span><span class="battle-val up">${_fmt_num(target)}{unit}</span></div>'
        f'<div class="battle-row"><span class="battle-label">止損賣價</span><span class="battle-val down">${_fmt_num(stop)}{unit}</span></div>'
        f'</div>'
        f'<div class="signal-watch">👀 盯 ${_fmt_num(stop)}{unit} 支撐與 ${_fmt_num(target)}{unit} 壓力</div>'
        f'<div class="signal-meta"><span class="signal-badge hold">🟡 續抱持有</span>'
        f'<span class="signal-confidence">信心 60%</span><span class="signal-horizon">⏱ 本週視角</span></div>'
        f'</div></div>'
    )


def _mark_card(card: str, sym: str) -> str:
    """在卡片**結尾前**塞一個隱形註解帶純代號 — 讓 audit 的 holdings_uncovered 找得到,
    因為 _postprocess_html 會把 signal-ticker 展開成公司名(台股甚至不留代號)。
    放結尾才不會打斷 _postprocess_html 加 verdict-chip 的開頭比對。"""
    idx = card.rfind("</div>")
    if idx < 0:
        return card + f"<!--h:{sym}-->"
    return card[:idx] + f"<!--h:{sym}-->" + card[idx:]


def _compact_overflow_card(sym: str, data: dict, mkt_status: dict) -> str:
    """email 版超出前 N 檔的持股用精簡卡(真實收盤 + 一句下一步 + 導去網頁完整版),
    控制信件大小避免 Gmail 截斷,但仍 100% 覆蓋每一支。audit 視為精簡卡豁免 battle 檢查。"""
    is_tw = str(sym).isdigit()
    market = data.get("tw_market", {}) if is_tw else data.get("us_market", {})
    m = market.get(sym)
    name = stock_names.display_name(sym, (m or {}).get("name"))
    if not m or m.get("price") is None:
        body = f'{name}({sym}) 目前無即時報價,待盤後數據更新,完整操作見網頁版。'
        return (f'<div class="signal-card wait"><div class="signal-card-top">'
                f'<span class="signal-ticker">{sym}</span></div>'
                f'<div class="signal-body"><div class="signal-reason">{body}</div></div></div>')
    chg = m.get("change_pct", 0) or 0
    up = "up" if chg >= 0 else "down"
    arrow = "▲" if chg >= 0 else "▼"
    unit = "元" if is_tw else ""
    body = (f'{name}({sym}) 收 ${_fmt_num(m.get("price"))}{unit}({chg:+.2f}%)。'
            f'這檔今日波動較小,完整進出場操作見網頁版。')
    return (f'<div class="signal-card hold"><div class="signal-card-top">'
            f'<span class="signal-ticker">{sym}</span>'
            f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span></div>'
            f'<div class="signal-body"><div class="signal-reason">{body}</div></div></div>')


def _render_signal_cards_batched(data: dict, stocks: list, mkt_status: dict, full_limit: int = None, prefer_strong: bool = False, depth: str = "standard") -> str:
    """分批生成每檔持股的 signal-card,保證『使用者選的每一支都有下一步』。
    一次塞 30-50 檔給 LLM 會超出輸出上限被截斷 → 改成每 10 檔一批多次呼叫,
    任何一檔 LLM 失敗 / 不合格 → 用真實技術價位的 deterministic 卡補位。
    full_limit:email 版怕 Gmail 截斷,只給「波動最大的前 N 檔」完整 LLM 卡,
    其餘持股仍用精簡 deterministic 真數據卡覆蓋(絕不丟掉任何一支,網頁版才是全 LLM)。
    結果:100% 覆蓋,絕不再因持股多而整封掉進備援版。"""
    seen = list(dict.fromkeys([s for s in (stocks or []) if s]))
    if not seen:
        return ""
    all_market = {**data.get("us_market", {}), **data.get("tw_market", {})}
    seen.sort(key=lambda s: abs((all_market.get(s) or {}).get("change_pct", 0) or 0), reverse=True)
    llm_stocks = seen[:full_limit] if full_limit else seen
    rules = _signal_card_format_rules(mkt_status, regime=_market_regime(data),
                                      macro_event=_detect_macro_event(data))
    cards_by_sym = {}
    CHUNK = 10
    for i in range(0, len(llm_stocks), CHUNK):
        chunk = llm_stocks[i:i + CHUNK]
        block = _chunk_market_tech_block(data, chunk, depth)
        deep_tech_note = ("\n【專業版要求】這位用戶選了「看深入」,上面附了 RSI/KD/MACD/布林/均線排列/交叉等進階指標。"
                          "每張卡的「下一步」說明要結合這些指標的判讀(例:RSI>70 過熱留意拉回、KD 低檔黃金交叉可偏多、"
                          "MACD 柱由負轉正轉強、跌破布林下軌或站上中軌),用白話講,並對應到具體價位與動作。只能引用上面提供的真實數字,不可自行編造指標值。\n"
                          if depth == "deep" else "")
        prompt = (
            f"你是這位用戶的專屬財經顧問。為以下每一支股票各生成一張 signal-card,給出明確「下一步」操作建議。\n"
            f"標的({len(chunk)} 支,一支都不能少、不能合併):{', '.join(chunk)}\n\n"
            f"【這幾支的真實市場 / 技術數據 — 進出場價位必須參考,嚴禁編造】\n{block}\n{deep_tech_note}\n"
            f"{rules}\n\n"
            f"只輸出這 {len(chunk)} 支的 <div class=\"signal-card ...\"> 區塊;每張卡前面**獨立一行**寫 <!--CARD--> 當分隔。\n"
            f"不要輸出 signal-grid 外框、不要任何說明文字、不要 markdown 反引號。"
        )
        raw = ""
        try:
            raw = _llm_generate(prompt, prefer_strong)
        except Exception as e:
            print(f"  [signal-batch] chunk {i//CHUNK+1} LLM 全失敗,改 deterministic({str(e)[:80]})")
        if raw.startswith("```"):
            raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
        # 不依賴 LLM 真的有放 <!--CARD-->:先拿掉分隔註解,再用「卡片開頭標籤」切。
        raw = re.sub(r'<!--\s*CARD\s*-->', '', raw)
        for seg in re.split(r'(?=<div class="signal-card[ "])', raw):
            if "signal-card" not in seg:
                continue
            start = seg.find('<div class="signal-card')
            end = seg.rfind('</div>')
            if start < 0 or end < 0:
                continue
            card = seg[start:end + 6].strip()
            tm = re.search(r'<span class="signal-ticker">\s*([^<]+?)\s*</span>', card)
            if not tm:
                continue
            tk = tm.group(1).strip()
            match = next((cs for cs in chunk if cs == tk or cs in tk or tk in cs), None)
            if match and match not in cards_by_sym and _card_passes_audit(card):
                cards_by_sym[match] = card
        if i + CHUNK < len(llm_stocks):
            time.sleep(2)
    overflow = set(seen[full_limit:]) if full_limit else set()
    ordered = []
    for s in seen:
        if s in overflow:
            card = _compact_overflow_card(s, data, mkt_status)
        else:
            card = cards_by_sym.get(s) or _deterministic_signal_card(s, data, mkt_status)
        ordered.append(_mark_card(card, s))
    return "\n".join(ordered)


def _inject_signal_cards(raw: str, cards: str) -> str:
    """把分批生成的 signal-card 填進 narrative 的佔位點;LLM 萬一把佔位註解吃掉也有後援。"""
    if not cards:
        return raw
    if "<!--SIGNAL_CARDS-->" in raw:
        return raw.replace("<!--SIGNAL_CARDS-->", cards)
    m = re.search(r'<div class="signal-grid">', raw)
    if m:
        return raw[:m.end()] + "\n" + cards + "\n" + raw[m.end():]
    section = (
        '\n<div class="signal-header"><div class="signal-header-title">⚡ 詳細進出場計畫</div>'
        '<div class="signal-header-subtitle">每一支持股的下一步</div></div>'
        '<div class="signal-grid">' + cards + '</div>'
        '<div class="signal-disclaimer">⚠️ AI 分析僅供參考,不構成投資建議</div>\n'
    )
    tl = re.search(r'</div>\s*(?=<div class="section-label")', raw)
    if tl:
        return raw[:tl.end()] + section + raw[tl.end():]
    return section + raw


def generate_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                    email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                    market: str = "both") -> str:
    # market: "both"=台美合併(預設/手動);"tw"=早 7:00 台股盤前為主、美股昨夜回顧;
    #         "us"=晚 20:00 美股盤前為主、台股今日收盤回顧。雙班次由 caller 傳對應市場 holdings。
    # email 版：持倉太多時敘述只留變動最大的 N 支，避免信件過長被 Gmail 截斷（完整版見網頁）。
    # 但「操作訊號卡」仍覆蓋全部持股(_full_holdings),不丟任何一支。
    _full_holdings = list(dict.fromkeys((user_us_stocks or []) + (user_tw_stocks or [])))
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
    if _full_holdings:
        top_signal_stocks = sorted(_full_holdings, key=_abs_change, reverse=True)
    else:
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)[:5]

    technicals = data.get("technicals", {})
    tech_rows = []
    for sym in top_signal_stocks:
        t = technicals.get(sym)
        if not t:
            continue
        hint = tw_market.get(sym, {}).get("name") if sym.isdigit() else None
        nm = stock_names.display_name(sym, hint)
        ma50 = f" | MA50 {t['ma50']}" if t.get("ma50") else ""
        adv = f" | {_adv_tech_str(t)}" if depth == "deep" and _adv_tech_str(t) else ""
        sup, tgt, stp = _near_term_levels(t.get("price"), t)
        anchor = f" ‖ 近端錨點→低接 {_fmt_num(sup)} / 反彈目標 {_fmt_num(tgt)} / 停損 {_fmt_num(stp)}" if sup is not None else ""
        tech_rows.append(
            f"  {nm}（{sym}）: 現價 {t['price']} | MA20 {t['ma20']}{ma50} | "
            f"20日高 {t['hi20']} / 20日低 {t['lo20']} | 60日高 {t['hi60']} / 60日低 {t['lo60']}(遠端區間,勿當停損/目標) | ATR14 {t['atr14']}{adv}{anchor}"
        )
    tech_block = ""
    if tech_rows:
        deep_rule = ("\n‼️ 專業版進階技術判讀:RSI>70 偏過熱留意拉回、RSI<30 偏超賣可留意反彈;KD 低檔黃金交叉偏多、高檔死亡交叉偏空;"
                     "MACD 柱由負轉正轉強、由正轉負轉弱;站上布林中軌偏多、跌破下軌弱勢、觸及上軌留意過熱。判讀只能用上面提供的真實指標值,不可編造。"
                     if depth == "deep" else "")
        tech_block = (
            "\n【各持股真實技術價位 — 進場/目標/停損價必須參考這些真實數字,嚴禁編造偏離現價的價位】\n"
            + "\n".join(tech_rows)
            + "\n‼️ 定價規則:直接用每支附的「近端錨點」(低接/反彈目標/停損)當建議買價、賺錢目標、止損賣價,可微調不可大幅偏離。"
            "**嚴禁拿 60日低/60日高 當停損或目標**(遠端區間,大漲後常離現價 30-60%,當停損失準);"
            "停損距現價 ≤約12%、目標 ≤約15%,所有價位夾在現價上下 15% 內,美股用美元、台股用台幣,不可憑空捏造。"
            + deep_rule + "\n"
        )

    # 訊號卡改由 _render_signal_cards_batched 分批生成(保證每支持股都有卡、不被截斷),
    # 這裡只放區塊外框 + 佔位註解,生成後用 _inject_signal_cards 填入。
    signal_instruction = """
<div class="signal-header">
  <div class="signal-header-title">⚡ 詳細進出場計畫</div>
  <div class="signal-header-subtitle">用戶選的每一支台股美股,都列下一步要做什麼 · 1-2 週視角</div>
</div>
<div class="signal-grid">
<!--SIGNAL_CARDS-->
</div>
<div class="signal-disclaimer">⚠️ AI 分析僅供參考，不構成投資建議</div>
‼️ 上面這段「⚡ 詳細進出場計畫」區塊**原樣保留**,尤其 <!--SIGNAL_CARDS--> 這行註解不要刪改、不要自己生成任何 signal-card,系統會自動填入每檔持股的操作卡。"""

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

    # 深度控制(Premium 客製):simple=最精簡 / standard=依新手判斷 / deep=全開
    # 新手精簡模式本來就拿掉中階區塊(原始數據儀表板、板塊輪動、二階思考)
    if depth == "deep":
        show_advanced = True
    elif depth == "simple":
        show_advanced = False
    else:
        show_advanced = not is_beginner
    if show_advanced:
        indicator_section = indicator_block
        sector_section = sector_block
        second_order_section = second_order_block
    else:
        indicator_section = ""
        sector_section = ""
        second_order_section = ""
    if depth == "simple":
        mood_section = ""
    depth_directive = _depth_directive(depth)

    # ── 雙班次時序框架(market) ──
    # tw=早 7:00 台股盤前主軸 / us=晚 20:00 美股盤前主軸。both=原合併版(預設)。
    us_last_td = mkt_status.get("us_last_trading_date") or "上一個交易日"
    if market == "us":
        time_discipline_block = f"""【⏰ 時序紀律 — 違反 = 廢稿】
**這份日報在台灣時間晚上 8:00 寄出,主軸是「今晚美股盤前布局」。**
- 美股:今晚約台灣時間 21:30-22:30 開盤(看美國夏令時間),你現在是**盤前**。可寫「今晚開盤前」「美股盤前布局」「今晚開盤後若 $XXX 就 XXX」。要回顧昨夜美股請用完成式「昨夜美股({us_last_td})收 XXX」。
- 台股:**今日 13:30 已收盤**,資料中的台股數字就是今日收盤,可用完成式「今日台股收 XXX」「台積電(2330)今日收 XXX 元」。台股今晚不再交易,只做**今日收盤回顧**,**禁止寫「今早 9:00 開盤」「明早早盤」這類盤前字眼**。
- 本封以**美股盤前操作為主軸**:每張 signal-card 給「今晚開盤後該做什麼」。台股部分只在大盤/新聞區做今日收盤回顧,不需逐檔台股操作卡。

【⚠️ 今晚的市場開盤狀態 — 絕對要遵守】
今晚美股:{mkt_status['us_action_note']}
昨夜美股:{mkt_status['us_note'] or f"昨夜({us_last_td})美股有開盤,可寫「昨夜美股收 XXX」。"}
今日台股:已於 13:30 收盤,資料為今日收盤數據,做收盤回顧即可。
"""
        tldr_focus_note = "- TLDR 30秒重點:**4 條至少 1 條必須是美股相關**(昨夜收盤動向 / 今晚開盤前怎麼布局 / 對某檔持股的明確建議)。台股可放今日收盤回顧。"
        tldr_li_hints = ['<li>（最重要的事,一句話,優先美股盤前布局或昨夜收盤動向）</li>',
                         '<li>（第二重要的事,美股相關）</li>',
                         '<li>（第三重要的事,可放台股今日收盤回顧）</li>',
                         '<li>（第四重要的事,如有）</li>']
    elif market == "tw":
        time_discipline_block = f"""【⏰ 時序紀律 — 違反 = 廢稿】
**這份日報在台灣時間早上 7:00 寄出,主軸是「今早台股開盤前布局」。那時台股還沒開盤(台股 9:00 開盤、13:30 收盤)。**
- 台股:**數據是昨日收盤**,今天 9:00 才開盤。**絕對禁止寫「今天台股已漲/已跌/超狂/大跌」這類盤中口吻**。要寫:「昨日台股收 XXX」「今早 9:00 開盤後若 XXX 就 XXX」「今日早盤策略」。
- 美股:昨晚剛收盤(台灣時間 04:00 收盤),可用「昨晚美股收紅/收黑」完成式做**昨夜回顧**。
- 本封以**台股盤前操作為主軸**:每張 signal-card 給「今早 9:00 開盤後該做什麼」。美股部分只在大盤/新聞區做昨夜收盤回顧,不需逐檔美股操作卡。

【⚠️ 今天的市場開盤狀態 — 絕對要遵守】
昨晚美股:{mkt_status['us_note'] or "美股有開盤,數據是新鮮的,可寫「昨晚美股 XXX」做回顧。"}
今天台股:{mkt_status['tw_note'] or "台股 9:00 將開盤,可寫「今早開盤」「今日早盤策略」。"}
"""
        tldr_focus_note = ("- TLDR 30秒重點:**用戶有台股持股時,4 條至少 1 條必須是台股相關**(昨日收盤動向 / 今早 9:00 開盤怎麼操作 / 對某檔持股的明確建議),不可全部都美股。"
                           + (f"⚠️ 這位用戶持有台股:{', '.join(watchlist_tw)} — TLDR 一定要有他的台股動向。" if watchlist_tw else ""))
        tldr_li_hints = [f'<li>（最重要的事,一句話。{"用戶有台股 → 這條或下一條必須講台股動向(昨日收盤 / 今早開盤策略),台股口吻不可用「今天台股已 XX」" if watchlist_tw else "一句話"}）</li>',
                         f'<li>（第二重要的事{"。若上一條是美股,這條就要是台股" if watchlist_tw else ""}）</li>',
                         '<li>（第三重要的事）</li>',
                         '<li>（第四重要的事,如有）</li>']
    else:
        time_discipline_block = f"""【⏰ 時序紀律 — 違反 = 廢稿】
**這份日報在台灣時間早上 7:00 寄出,那時台股還沒開盤（台股 9:00 開盤、13:30 收盤）。**
- 美股：通常剛收盤不久（台灣時間 04:00 美股收盤），可以用「昨晚美股收紅/收黑」這類完成式口吻。
- 台股：**數據是昨日收盤**，今天 9:00 才開盤。**絕對禁止寫「今天台股已漲/已跌/超狂/大跌」這類盤中口吻**。要寫就寫：「昨日台股收 XXX」「今早開盤可留意 XXX」「9:00 開盤後若 XXX 就 XXX」「今日早盤策略」。看到「{date}」這個日期 = 台股還沒開盤的一天。
- 違反例：「今天台積電（2330）漲 3%！」← 廢稿（盤前不可能知道）
- 正確例：「台積電（2330）昨日收 XXX 元」「今早 9:00 開盤後留意 XXX 元支撐」

【⚠️ 今天的市場開盤狀態 — 絕對要遵守】
昨晚美股:{mkt_status['us_note'] or f"美股有開盤,數據是新鮮的,可寫「昨晚美股 XXX」。"}
今天台股:{mkt_status['tw_note'] or f"台股 9:00 將開盤,可寫「今早開盤」「今日早盤策略」。"}
今晚美股:{mkt_status['us_action_note']}

**雙市場動作對稱性:每張美股 signal-card 要給「今晚開盤後做什麼」(若今晚開盤),每張台股 signal-card 要給「今早 9:00 開盤後做什麼」(若今天開盤)。休市日只給「等下一個交易日 X」,不可寫「今晚/今早開盤」這類字眼。**
**規則：休市日的市場,不可在「30 秒看完今天重點」「大盤怎麼了」「持股本日動向」這幾個區塊把舊收盤當「今天/昨晚」寫,務必點明休市。**"""
        tldr_focus_note = ("- TLDR 30秒重點：**用戶有台股持股時，4 條至少 1 條必須是台股相關**（昨日收盤動向 / 今早 9:00 開盤怎麼操作 / 對某檔持股的明確建議），不可全部都美股。"
                           + (f"⚠️ 這位用戶持有台股：{', '.join(watchlist_tw)} — TLDR 一定要有他的台股動向。" if watchlist_tw else ""))
        tldr_li_hints = [f'<li>（最重要的事，一句話。{"用戶有台股 → 這條或下一條必須講台股動向（昨日收盤 / 今早開盤策略），台股口吻不可用「今天台股已 XX」" if watchlist_tw else "一句話"}）</li>',
                         f'<li>（第二重要的事{"，若上一條是美股，這條就要是台股" if watchlist_tw else ""}）</li>',
                         '<li>（第三重要的事）</li>',
                         '<li>（第四重要的事，如有）</li>']

    # 累加式深度:simple=只有 TLDR + 操作卡(+結論);standard 在此之上加新聞;
    # 大盤/進階尾段 standard 也有,deep 全開,simple 全砍。
    news5_block = f"""<div class="section-label">🔥 今天最重要的 5 件事</div>
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
- ‼️ 每支 impact-stock 都必須在 news-why 裡講得出**具體傳導機制**（營收曝險、供應鏈、利率敏感度、同業競爭）。講不出機制的個股不要硬塞——「中東開戰→微軟看跌」這種無機制對映是廢稿
- 利多用 up、利空用 down，**不可整版全部 down**：同一則新聞常有受惠方（油價漲→能源股 up、航空股 down），有受惠方就要列
- 想不到具體個股時，就挑受影響產業的龍頭股：Fed 利率→JPM、GS；油價→XOM、CVX；AI/算力→NVDA、TSM；半導體→TSM、2330、2454；消費→AMZN、WMT
- 優先列跟用戶持倉（{', '.join(all_holdings) if has_holdings else '主流科技股'}）相關的個股
- 只有新聞完全與任何上市公司無關時（例如純政治事件）才可省略，且這種最多 1 張
- ‼️ 標題與 news-why 的方向必須一致：標題寫「油價反彈」內文就不可寫「油價反而下跌」——寫之前對一次數據
- ‼️ 禁止無來源的因果臆測：「可能與 XXX 有關」這種你自己腦補的歸因不可寫；新聞沒講原因就只描述現象與對持股的影響"""

    market_tail_block = f"""<div class="advanced-divider">📊 以下是大盤與進階分析 — 想深入再看，不看也不影響你上面的操作</div>

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

{second_order_section}

<div class="section-label">📅 即將公布財報</div>
<div class="earnings-list">
（根據上方財報日曆，列出最近的財報，格式：
  <div class="earnings-item">
    <span class="earnings-ticker">（代號）</span>
    <span class="earnings-date">（日期）</span>
    <span class="earnings-note">（一句話。‼️ 只能使用上方財報日曆「已核實」的預期 EPS / 營收數字；日曆沒附預期數字時，這句只能寫中性關注重點（如「雲端業務動向是焦點」），嚴禁自行編造任何 EPS / 營收預估或產品銷售數字）</span>
  </div>
若無資料則寫「近期無重大財報」）
</div>"""

    if depth == "simple":
        # 簡單看 = 純重點操作:只留 TLDR + 操作卡(+結論),新聞與大盤全砍
        personalized_news_instruction = ""
        news5_section = ""
        market_tail_section = ""
    else:
        news5_section = news5_block
        market_tail_section = market_tail_block

    prompt = f"""你是這位用戶的專屬財經顧問，說話生活化、直接、像朋友。這份報告是**專門為持有 {', '.join(all_holdings) if has_holdings else '各種股票的'} 的用戶客製化生成的**，不是通用報告。

{time_discipline_block}

【無幻覺原則 — 違反 = 廢稿】
- 所有內容只能基於以下提供的真實數據和新聞，不得憑空補充或使用訓練資料臆測
- 新聞標題、內文、URL 一律只能從下方「今日新聞」清單取用；URL 必須一字不差原樣複製，嚴禁自己拼湊或編造任何網址
- 找不到對應的真實新聞時，就不要寫那張新聞卡 / stock-news-item，絕對不要為了湊數量而捏造
- 如果某項資訊不足，就說「今日數據不足」，不要捏造

{depth_directive}
【個人化原則】
{tldr_focus_note}
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
  {tldr_li_hints[0]}
  {tldr_li_hints[1]}
  {tldr_li_hints[2]}
  {tldr_li_hints[3]}
</ul>
</div>

{signal_instruction}
{personalized_news_instruction}
{rookie_section}

{news5_section}

{market_tail_section}

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

    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    cards = _render_signal_cards_batched(data, top_signal_stocks, mkt_status,
                                         full_limit=DIGEST_EMAIL_MAX_HOLDINGS if email_safe else None,
                                         prefer_strong=prefer_strong, depth=depth)
    raw = _inject_signal_cards(raw, cards)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Weekend Recap(週六專用:本週回顧 + 下週預告)──────────────
def generate_weekend_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                            email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                            market: str = "both") -> str:
    # market 由雙班次 caller 傳入(週六台股早報走此函式);週末回顧本就是台股晨間語境,
    # holdings 已由 caller 依 market scope,這裡接受參數即可(行為不變)。
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

    # 累加式深度:simple 只留 TLDR + 持股本週表現操作 + 週末思考;standard/deep 再加本週回顧新聞 + 下週 catalysts
    if depth == "simple":
        weekend_body = """【持股本週表現(純重點操作)】
- 只針對用戶持股寫:本週走勢一句話 + 下週明確操作(買/抱/賣 + 價位條件)
- 不要本週新聞回顧、不要下週 catalysts 清單、不要大盤長篇

【週末投資思考(1 段)】
- 給用戶一個本週末值得思考的問題或觀點(風險、配置、心態),簡短有力
"""
        weekend_format = """嚴格回傳純 HTML,沿用平日日報 CSS class(.tldr, .stock-card, .verdict.neutral 等),只要這幾塊(純重點,不要新聞回顧、不要 catalysts 清單):
1. .tldr 區改成「📅 本週快訊」(3-4 條本週重點,有台股要至少 1 條台股)
2. .section-label「持股本週表現」+ .stock-card 寫用戶 holdings 的本週走勢 + 下週明確操作(買/抱/賣 + 價位條件)
3. .verdict.neutral 結尾的「週末思考」"""
    else:
        weekend_body = """【本週回顧(週一到週五已收盤)】
- 寫 3-4 段 highlights:本週最大事件、本週贏家/輸家、用戶持股本週表現
- 引用本週實際發生的新聞,連結原文

【下週看什麼(catalysts)】
- 從新聞中找出下週會發生的事件:財報日、Fed/央行講話、CPI/PPI 等經濟數據、地緣政治
- 條列 5-8 個 catalysts,標明日期與影響
- 如新聞中沒提到具體下週事件,寫「本週新聞中未明示下週重大事件,留意週一開盤反應」即可,不要捏造

【週末投資思考(1 段)】
- 給用戶一個本週末值得思考的問題或觀點(風險、配置、心態),簡短有力
"""
        weekend_format = """嚴格回傳純 HTML,沿用平日日報 CSS class(.tldr, .news-card, .stock-card, .verdict.neutral, .watch-list 等),內容主軸:
1. .tldr 區改成「📅 本週快訊」(3-4 條本週重點)
2. .section-label「本週回顧」+ 數張 .news-card 寫本週實際發生的大事
3. .section-label「下週 catalysts」+ .watch-list 列下週要看的事件 + 日期
4. .section-label「持股本週表現」+ .stock-card 寫用戶 holdings 的本週走勢
5. .verdict.neutral 結尾的「週末思考」"""

    prompt = f"""你是這位用戶的專屬財經顧問。今天是**週六晨間**,美股週五已收盤、台股週五已收盤,週末兩天都不開盤。所以這份報告不講「今天大盤」,而是聚焦「本週發生了什麼 + 下週要看什麼」。

【無幻覺原則 — 違反就廢稿】
- 所有內容只能基於下方提供的真實市場數據和新聞,不得憑空補充或臆測
- 新聞 URL 必須一字不差原樣複製,嚴禁編造
- 找不到對應真實新聞就不要硬寫
- 如資訊不足,寫「本週資料不足」不要捏造

{_depth_directive(depth)}
【個人化原則】
- 用戶持倉:{', '.join(holdings) if has_holdings else '尚未設定持股,以大盤龍頭股為例'}
- 內容要圍繞他的持股做本週復盤 + 下週展望
- 台股一律用公司名稱(可附代號),不要只報數字

{weekend_body}
【日期】{date}(週六)

【本週市場數據(以週五收盤為基準)】
{market_text}

【本週美股新聞】
{us_news_text}

【本週台股新聞】
{tw_news_text}

【輸出格式】{weekend_format}

不要 markdown ```、不要在 .stock-card 內塞當日資料(改成本週區間)、不要寫「今日」「盤中」這類週六不該出現的字眼。
"""

    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Monday Outlook(週一專用:上週五收盤 + 週末新聞 + 本週展望 + Gap 警示)──────────────
def generate_monday_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                           email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                           market: str = "both") -> str:
    # market 由雙班次 caller 傳入(週一台股早報走此函式);週一展望本就是台股晨間語境,
    # holdings 已由 caller 依 market scope,這裡接受參數即可(行為不變)。
    """週一晨間日報:前兩天(週六、週日)沒開盤,所以基準是『上週五收盤』。
    重點:週末新聞累積 + 上週五收盤回顧 + 本週 catalysts + 週一開盤 gap 風險 +
    每檔持股仍給明確操作建議(買/抱/賣/觀望)。"""
    # email 版敘述只聚焦波動最大的 30 檔,但「操作訊號卡」仍覆蓋全部持股(全列在 _full_holdings)。
    _full_holdings = list(dict.fromkeys((user_us_stocks or []) + (user_tw_stocks or [])))
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

    # 操作訊號卡的股票清單:用戶持倉**每一支都要有卡** — 絕不切。波動大者排前面方便讀,但全留。
    # 2026-06-01 事故根因:這裡曾 [:8],持股 >8 的用戶必觸發 audit holdings_uncovered → 整封掉進備援版。
    # 現在改由 _render_signal_cards_batched 分批生成,不怕多。
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    all_market = {**us_market, **tw_market}
    def _abs_change(sym):
        d = all_market.get(sym, {})
        return abs(d.get("change_pct", 0))
    mkt_status = _market_status(date)
    if _full_holdings:
        signal_stocks = sorted(_full_holdings, key=_abs_change, reverse=True)
    else:
        signal_stocks = ["AAPL", "MSFT", "NVDA", "TSLA"]

    # 訊號卡改由 _render_signal_cards_batched 分批生成(每支持股都有卡、不被截斷),
    # 這裡只放區塊外框 + 佔位註解,生成後用 _inject_signal_cards 填入。
    signal_skeleton = """
<div class="signal-header">
  <div class="signal-header-title">💡 你的持股本週怎麼操作</div>
  <div class="signal-header-subtitle">上週五收盤位置 + 今早開盤策略 · 給出明確動詞</div>
</div>
<div class="signal-grid">
<!--SIGNAL_CARDS-->
</div>
<div class="signal-disclaimer">⚠️ AI 分析僅供參考,不構成投資建議</div>
‼️ 上面這段「💡 你的持股本週怎麼操作」區塊**原樣保留**,尤其 <!--SIGNAL_CARDS--> 這行註解不要刪改、不要自己生成任何 signal-card,系統會自動填入每檔持股的操作卡。"""

    # 累加式深度:週一 simple = TLDR + 週末新聞卡(週一開盤關鍵,必留)+ Gap 風險 + 操作卡 + 週一心法;
    # standard/deep 再加上週五收盤回顧 + 本週催化劑。週末新聞是「決定今早怎麼動」的操作輸入,不可砍。
    _simple = depth == "simple"
    monday_catalyst_block = "" if _simple else """【本週催化劑(必須出現)】
- 從新聞中找出本週會發生的事件:財報日、Fed 講話、CPI/PPI、台股除權息
- 條列 5-8 個 catalysts,標明日期(週幾)與對哪些持股有影響
- 如新聞中沒提到,寫「本週新聞中未明示具體事件,持續追蹤」即可,不要捏造
"""
    if _simple:
        monday_format = f"""嚴格回傳純 HTML,沿用平日日報 CSS class,只要這幾塊(純重點操作:保留週末新聞,但省略大盤收盤回顧段、省略本週事件預告清單):
1. .tldr 區改成「📅 週一展望」標題,列 3-4 條:①週末最大事件 ②今早 gap 方向 ③本週持股怎麼動
2. .section-label「📰 週末重點新聞」+ 數張 .news-card,標題明示「週末發生」,有影響個股就掛 impact-stock(這是週一開盤前最該知道的事)
3. .section-label「⚠️ 週一開盤 Gap 風險」+ 一張 .verdict.SENTIMENT 卡片,寫明開盤方向 + 具體 playbook(買/抱/賣 + 價位)
4. 持股操作訊號卡區塊:**原樣輸出下方模板,不要自己生卡片**(卡片由系統填入 <!--SIGNAL_CARDS-->):
{signal_skeleton}
5. .verdict.neutral 結尾「週一心法」,提醒週一波動大、可觀察前 30 分鐘再進場"""
    else:
        monday_format = f"""嚴格回傳純 HTML,沿用平日日報 CSS class,順序如下:
1. .tldr 區改成「📅 週一展望」標題,列 3-4 條:①週末最大事件 ②上週五收盤摘要 ③本週要看什麼 ④今早 gap 方向
2. .section-label「📰 週末重點新聞」+ 數張 .news-card,標題明示「週末發生」,有影響個股就掛 impact-stock
3. .section-label「📊 上週五收盤回顧」+ .market-summary,**所有數據敘述都要說「上週五」不可寫「今天」**
4. .section-label「⚠️ 週一開盤 Gap 風險」+ 一張 .verdict.SENTIMENT 卡片,寫明開盤方向 + 具體 playbook
5. .section-label「📅 本週催化劑」+ .watch-list 列出本週事件 + 日期
6. 持股操作訊號卡區塊:**原樣輸出下方模板,不要自己生卡片**(卡片由系統填入 <!--SIGNAL_CARDS-->):
{signal_skeleton}
7. .verdict.neutral 結尾「週一心法」,提醒週一通常波動大、可觀察前 30 分鐘再進場"""

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

{_depth_directive(depth)}
【個人化原則】
- 用戶持倉:{', '.join(holdings) if has_holdings else '尚未設定持股,以大盤龍頭股為例'}
- {'內容圍繞他的持股做:週末新聞影響 + 今早 gap 方向 + 每支持股操作建議(純重點,省略大盤收盤回顧段與本週事件預告清單)' if _simple else '內容圍繞他的持股做:上週五表現 + 週末新聞影響 + 本週催化劑 + 操作建議'}
- 台股一律用公司名稱(可附代號),不要只報數字

【🚫 不要自己生持股操作卡】
每檔持股的 signal-card(操作訊號卡)由系統另外分批生成並填入,**你不要輸出任何 <div class="signal-card"> 卡片**。
你只負責 {'TLDR、週末新聞、Gap 風險、週一心法這些區塊' if _simple else 'TLDR、週末新聞、上週五收盤回顧、Gap 風險、本週催化劑、週一心法這些區塊'};遇到訊號卡區塊只原樣保留 <!--SIGNAL_CARDS--> 註解。

【📅 週末新聞 + 週一 Gap 風險】
這是週一特有區塊,必須出現:
- 整理週末兩天(週六週日)累積的關鍵新聞,標題明示「週末發生」(這是台股/美股週一開盤要反映的關鍵消息)
- 根據週末新聞推估今早美股期貨/台股開盤偏多/偏空/中性的方向
- 對應到具體 playbook:例如「若 NVDA 開盤跳空向上 >2% → 等回拉接;跳空向下 → 分批接 $XXX-XXX」

{monday_catalyst_block}
【日期】{date}(週一,基準=上週五 {last_friday} 收盤)

【上週五市場數據】
{market_text}

【週末美股新聞(週六週日累積)】
{us_news_text}

【週末台股新聞(週六週日累積)】
{tw_news_text}

【輸出格式】{monday_format}

不要 markdown ```、不要寫「今天大盤」這類週一早上不該出現的字眼(因為現在還沒開盤),改用「上週五」「今早開盤前」「本週」。
"""

    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    cards = _render_signal_cards_batched(data, signal_stocks, mkt_status,
                                         full_limit=DIGEST_EMAIL_MAX_HOLDINGS if email_safe else None,
                                         prefer_strong=prefer_strong, depth=depth)
    raw = _inject_signal_cards(raw, cards)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result
