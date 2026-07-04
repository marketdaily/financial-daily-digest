import os
import re
import time
import requests
import stock_names
from config import GEMINI_API_KEY

# 免費 LLM 引擎：Gemini Flash 系列（免費，無需付費）。
# flash-latest 品質佳為主；flash-lite 免費層每日額度最高，作為備援確保不斷線。
# 2026-06-30 更正:Anthropic key 實測正常(sonnet/haiku 皆 200),Claude 為可用付費後援+council 席次;
# OpenAI 純因 .env 未設 key 而停用(補 key 即恢復)。Gemini 仍是免費主力,故擴充 model fallback ——
# 最穩+最高品質的 2.5-flash 擺第一,
# 再墊 lite + 2.0 世代(獨立配額桶,2.5 配額爆時頂上),flash-latest(別名,常 503)放最後。
# 實測(本機 key,2026-06-25):2.5-flash/2.5-flash-lite=200、2.0-flash/lite=429(配額,會重置)、
# flash-latest=503、1.5 系列=404 已下架。
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite",
                 "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ── 近端價位錨定參數(_near_term_levels / _postprocess_html 買點分流共用)──
NEAR_HIGH_RATIO = 0.985      # 建議買區上緣低於現價 1.5% 以上 → chip 改「回檔再買」
ATR_MAX_RATIO = 0.15         # ATR 超過現價 15% 視為異常
ATR_FALLBACK_RATIO = 0.03    # 無 ATR / 異常時退回現價 3% 估計
SUPPORT_ATR_MULT = 1.5       # 低接支撐:現價下方 1.5×ATR
TARGET_ATR_MULT = 2.0        # 反彈目標:現價上方 2×ATR
STOP_MAX_ATR_MULT = 2.5      # 停損距現價至多 2.5×ATR
STOP_FLOOR_RATIO = 0.88      # 停損不得低於現價 -12%
SUPPORT_FLOOR_RATIO = 0.90   # 支撐不得低於現價 -10%
TARGET_CAP_RATIO = 1.15      # 目標不得高於現價 +15%

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


def _call_gemini(prompt: str, model: str, system: str = None) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("未設定 GEMINI_API_KEY")
    if model in _GEMINI_QUOTA_DEAD:
        raise RuntimeError(f"{model} 本輪 429 配額耗盡,熔斷跳過")
    payload = {
        "systemInstruction": {"parts": [{"text": system or _SYSTEM_PROMPT}]},
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


def _call_claude(prompt: str, system: str = None, model: str = "claude-sonnet-4-6") -> str:
    """Claude 作為付費後援(Gemini 全掛 / audit retry 時用)。需要 ANTHROPIC_API_KEY。
    2026-06-25 從 Haiku 升 Sonnet:備援只在 Gemini 失敗時觸發,正好是最需要拉高品質的時刻,
    Sonnet 比 Haiku 強很多、又只 Opus 約 1/5 成本,救援 CP 值最高。
    council 席次改傳 model=haiku + 乾淨 system,省錢且不被 HTML system prompt 帶歪成吐 HTML。"""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 ANTHROPIC_API_KEY")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 16000,
            "system": system or _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


LLM_TEMPERATURE = 0.4  # 全 OpenAI 相容 provider 共用(gemini 另在自家 payload 帶同值)


def _call_openai_style(url: str, key_env: str, prompt: str, system: str, model: str,
                       max_tokens: int, extra_headers: dict = None, content_type: bool = False,
                       retry_429_once: bool = False, timeout: int = 120) -> str:
    """openai / groq / openrouter / cerebras 四家共用的 chat-completions 轉接
    (原本四份逐字複製的樣板,2026-07-03 P2 收斂)。headers 順序、payload 欄位、
    重試行為逐家凍結於 refactor_harness 的 provider 快照 —— 改這裡必先過快照 diff。
    gemini / claude / cf_ai / ollama 的線路形狀真的不同,不硬塞進來。"""
    key = os.environ.get(key_env)
    if not key:
        raise RuntimeError(f"未設定 {key_env}")
    headers = {"Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": LLM_TEMPERATURE,
        "messages": [
            {"role": "system", "content": system or _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    resp = None
    for attempt in range(2 if retry_429_once else 1):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if retry_429_once and resp.status_code == 429 and attempt < 1:
            time.sleep(8)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_openai(prompt: str, system: str = None) -> str:
    """OpenAI gpt-4o-mini 作為最終付費後援(Claude 也掛時用)。需要 OPENAI_API_KEY。
    .env 目前未設此 key → 此 caller 直接 raise,council/fallback 自動跳過(非錯誤)。"""
    return _call_openai_style(
        "https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY",
        prompt, system, model="gpt-4o-mini", max_tokens=16000,
        content_type=True, timeout=180)


def _call_groq(prompt: str, system: str = None,
               model: str = "openai/gpt-oss-120b", max_tokens: int = 8000) -> str:
    """Groq(GPT-OSS 120B)免費後援。OpenAI 相容 API、速度快,免費層有獨立配額桶。
    注:Groq 於 2026-07-01 通知 llama-3.3-70b-versatile deprecate、2026-08-16 停用,
    官方建議替換為 openai/gpt-oss-120b,已切換避免停用後掉回 deterministic。
    定位:Gemini 免費配額耗盡、Claude 又瞬斷時的『免費第三張網』,接住原本會掉
    deterministic 的班次(2026-07-01 事故:Gemini 429+Claude DNS 抖→3 chunk 掉備援)。
    GROQ_API_KEY 已在 .env;沒設則 raise,鏈/席次自動跳過(非錯誤)。"""
    return _call_openai_style(
        "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
        prompt, system, model=model, max_tokens=max_tokens,
        content_type=True, retry_429_once=True)


def _call_cf_ai(prompt: str, system: str = None,
                model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast", max_tokens: int = 600) -> str:
    """Cloudflare Workers AI(免費層 10k neurons/日),經自家 md-ai-proxy worker(Bearer 驗證)。
    獨立配額桶+獨立網路路徑(CF edge),與 Gemini/Groq/Anthropic 都不同廠商。
    沒設 CF_AI_PROXY_TOKEN → raise,鏈/席次自動跳過(非錯誤)。"""
    tok = os.environ.get("CF_AI_PROXY_TOKEN")
    url = os.environ.get("CF_AI_PROXY_URL")
    if not tok or not url:
        raise RuntimeError("未設定 CF_AI_PROXY_TOKEN")
    r = requests.post(url, headers={"Authorization": f"Bearer {tok}"},
                      json={"model": model, "max_tokens": max_tokens,
                            "messages": [{"role": "system", "content": system or _SYSTEM_PROMPT},
                                         {"role": "user", "content": prompt}]},
                      timeout=120)
    r.raise_for_status()
    return str(r.json()["response"]).strip()


def _call_openrouter(prompt: str, system: str = None,
                     model: str = "meta-llama/llama-3.3-70b-instruct:free", max_tokens: int = 600) -> str:
    """OpenRouter 免費層(:free 模型每日額度)。OpenAI 相容 API、獨立廠商聚合器。
    預接線:沒設 OPENROUTER_API_KEY → raise,席次/鏈自動跳過。用戶自行註冊拿 key
    (Cloudflare Turnstile 擋自動註冊)後填進 .env 即自動啟用一席,不需改程式。"""
    return _call_openai_style(
        "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY",
        prompt, system, model=model, max_tokens=max_tokens,
        extra_headers={"HTTP-Referer": "https://marketdaily.ai", "X-Title": "MarketDaily"})


def _call_cerebras(prompt: str, system: str = None,
                   model: str = "llama-3.3-70b", max_tokens: int = 600) -> str:
    """Cerebras 免費層(晶圓級引擎,推理極快)。OpenAI 相容 API、獨立廠商。
    預接線:沒設 CEREBRAS_API_KEY → raise,席次/鏈自動跳過。用戶自行註冊拿 key
    (reCAPTCHA 擋自動註冊)後填進 .env 即自動啟用一席。"""
    return _call_openai_style(
        "https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY",
        prompt, system, model=model, max_tokens=max_tokens)


def _call_ollama(prompt: str, system: str = None,
                 model: str = "qwen2.5:14b-instruct-q4_K_M", max_tokens: int = 600) -> str:
    """winrig 本地 5080 GPU(Ollama)。零配額、零 429、不吃網路 —— 全雲端 LLM 斷線
    (如 7/1 WSL DNS 瞬斷,Gemini/Claude/Groq 同時解析失敗)時唯一還活著的席次/備援。
    只在 winrig 上有效;雲端 CI 環境連不上 localhost 會立刻 raise,鏈/席次自動跳過。
    num_ctx 16384:卡片生成 prompt(10支+新聞+規則)可達 6-10k tokens,預設 ctx 會靜默截斷。"""
    try:
        r = requests.post("http://localhost:11434/api/chat", json={
            "model": model,
            "messages": [{"role": "system", "content": system or _SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}],
            "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.4, "num_predict": max_tokens, "num_ctx": 16384},
        }, timeout=600)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError("ollama 連不上(非 winrig 環境或服務沒起)")


def _is_transient_dns_error(e) -> bool:
    """WSL2 的 DNS 全走 Windows 主機轉發(nameserver 10.255.255.254),主機網路瞬抖時
    整台 WSL 有幾秒解不到任何網域(NameResolutionError / Temporary failure in name
    resolution / Failed to resolve)。這種是暫時性、幾秒就過 → 值得等一下整輪重試;
    配額 429 / 認證錯不是這種,不該重試。2026-07-01 事故:一次 DNS 瞬斷讓 Gemini+Claude
    +Groq(全走同條 DNS)同時解析失敗 → 3 chunk 掉 deterministic。"""
    s = str(e).lower()
    return ("nameresolutionerror" in s or "failed to resolve" in s
            or "temporary failure in name resolution" in s)


def _llm_generate(prompt: str, prefer_strong: bool = False) -> str:
    """多 provider LLM 鏈:Gemini(多 model)→ Claude Sonnet → Groq Llama70B(免費)→ OpenAI。
    四層 LLM,任一可用就成功 — deterministic fallback 在現實中應該永遠跑不到。
    2026-05-26:用戶要求不能有「最差情況」,LLM 路徑必須近 100%。
    prefer_strong=True:把 Claude/OpenAI 排到 Gemini 前面。retry 專用 —
    第一次 Gemini 在配額壓力下回的弱內容會過 _llm_generate 但 audit HIGH fail,
    retry 若還從 Gemini 起跑等於白做;換更強模型才有意義。Gemini 仍留最後一層,
    不破壞「永不掉 deterministic」保證。
    2026-07-01:全鏈失敗且屬 DNS 瞬斷(整台 WSL 幾秒解不到,連 Groq 也救不了,因走同條
    Windows DNS)→ 等 8s 讓瞬斷過去、重試整輪一次(Gemini 已熔斷的維持快跳過不再撞 429)。"""
    gemini = [(f"gemini:{m}", lambda p, mm=m: _call_gemini(p, mm)) for m in GEMINI_MODELS]
    # Groq(Llama70B,免費)排在付費 OpenAI 前:Gemini 配額死 + Claude 抖時的免費接手層。
    strong = [("claude:sonnet-4.6", _call_claude),
              ("groq:gpt-oss-120b", lambda p: _call_groq(p)),
              # 免費雲端 70B 層(獨立廠商/網路路徑):CF Workers AI 一定在;
              # OpenRouter/Cerebras 沒 key 時 raise 自動跳過,填 key 即自動補進鏈。
              ("cf:llama-3.3-70b", lambda p: _call_cf_ai(p, max_tokens=8000)),
              ("openrouter:llama-70b", lambda p: _call_openrouter(p, max_tokens=8000)),
              ("cerebras:llama-70b", lambda p: _call_cerebras(p, max_tokens=8000)),
              ("openai:gpt-4o-mini", _call_openai)]
    # 本地 GPU 永遠排最後一張網:品質不如雲端大模型(有 audit 閘門把關),
    # 但零配額且不吃網路,全雲端斷線(DNS 瞬斷/配額同時死)時是唯一活口。
    local = [("local:qwen2.5-14b", lambda p: _call_ollama(p, max_tokens=9000))]
    providers = ((strong + gemini) if prefer_strong else (gemini + strong)) + local
    last_err = None
    for rnd in range(2):
        dns_blip = False
        for name, fn in providers:
            try:
                out = fn(prompt)
                print(f"  [LLM] 使用 {name}{' (retry強化)' if prefer_strong else ''}{' (DNS重試後)' if rnd else ''}")
                return out
            except Exception as e:
                last_err = e
                if _is_transient_dns_error(e):
                    dns_blip = True
                print(f"  [LLM] {name} 失敗({str(e)[:120]})")
        # 全 provider 失敗:只有『疑似 DNS 瞬斷』才值得等 8s 重試整輪(配額/認證錯重試也沒用)
        if dns_blip and rnd == 0:
            print("  [LLM] 全鏈失敗且疑似 DNS 瞬斷(WSL→Windows DNS 抖),等 8s 重試整輪")
            time.sleep(8)
            continue
        break
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
    # 主旨裡的個股:台股一律用中文名(不可露代碼)、美股用「中文 代號」
    def _subj_label(s):
        return stock_names.label_with_code(s, tw_market.get(s, {}).get("name")) if s in tw_market else s
    if weekday == 0:
        # 週一:基準是上週五收盤,主旨明寫「上週五」避免誤導
        if biggest_sym and biggest_pct >= 2:
            sym, pct = biggest_sym
            direction = "漲" if pct > 0 else "跌"
            return f"📅 上週五 {_subj_label(sym)} {direction} {abs(pct):.1f}%+週一展望｜MarketDaily {date}"
        return f"📅 週末重點 + 週一展望｜MarketDaily {date}"
    if biggest_sym and biggest_pct >= 2:
        sym, pct = biggest_sym
        direction = "漲" if pct > 0 else "跌"
        # 台股早上 7 點還沒開盤,主旨要寫「昨日」;美股剛收盤可寫「今天」
        is_tw = sym in tw_market
        when = "昨日" if is_tw else "今天"
        return f"📊 你的 {_subj_label(sym)} {when}{direction}了 {abs(pct):.1f}%｜財經日報 {date}"
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


def _pp_strip_llm_style(html: str) -> str:
    import re as _re
    # LLM 偶爾違規輸出整頁 HTML 連自帶 <style>(Claude Haiku 尤其常見;2026-06-11 用戶截圖):
    # premailer 會把它的 .signal-card{display:flex;flex-direction:column} 內聯進每張卡,
    # Gmail 行動版支援 flex 但丟 flex-direction → 卡片變橫排、chip 拉成整卡高。
    # 死防線:LLM 夾帶的 style 與文件骨架整塊剝掉,內文只能吃模板 CSS。
    html = _re.sub(r'<style[^>]*>.*?</style>', '', html, flags=_re.S | _re.I)
    html = _re.sub(r'<!DOCTYPE[^>]*>|</?(?:html|head|body)[^>]*>|<meta[^>]*>|<title[^>]*>.*?</title>', '', html, flags=_re.S | _re.I)
    return html


def _pp_clear_placeholders(html: str) -> str:
    import re as _re
    # 死防線:LLM 不知道確切數字時偶爾寫成 XXX/XX 佔位符(2026-06-25 真兇:新聞「為什麼重要」
    # 寫「賣超金額高達 XXX 億元」直接洩進公版)。用戶硬規則:任何數字佔位符不可外露給訂閱者。
    # 先把含佔位符的整段子句(逗號分隔)整塊刪掉讓句子讀得通,再清落單的 X 佔位符。
    html = _re.sub(r'[，、]\s*[^，、。；:\n<>]*?[XＸ]{2,}\s*(?:億元|億美元|億|兆|萬元|美元|元|點|%|％)[^，、。；\n<>]*', '', html)
    html = _re.sub(r'\s*[XＸ]{2,}\s*(?:億元|億美元|億|兆|萬元|美元|元|點|%|％)', '', html)
    html = _re.sub(r'(?:NT)?\$[XＸ]{2,}', '', html)
    html = _re.sub(r'(?<![A-Za-z])[XＸ]{3,}(?![A-Za-z])', '', html)
    return html


def _pp_indicator_class(html: str, data: dict) -> str:
    import re as _re
    ind = data.get("indicators", {})

    vix = ind.get("vix", 15)
    html = html.replace("indicator-VIXCLASS", "indicator-fear" if vix > 20 else "indicator-neutral")

    fg = ind.get("fear_greed") or {}
    fg_score = fg.get("score", 50)
    html = html.replace("indicator-FGCLASS", "indicator-fear" if fg_score < 45 else "indicator-greed" if fg_score > 55 else "indicator-neutral")
    # LLM 偶發把 indicator-VIXCLASS/FGCLASS 整個 token 換成裸 fear/greed/neutral(CSS 只定義
    # indicator-*),audit undefined_css_class 判 HIGH → 整封白白 retry;後處理直接補正
    html = _re.sub(r'class="indicator-value (fear|greed|neutral)"',
                   r'class="indicator-value indicator-\1"', html)
    return html


def _pp_crypto_dir(html: str, data: dict) -> str:
    crypto = data.get("crypto", {})
    btc_dir = "up" if (crypto.get("btc") or {}).get("change_pct", 0) >= 0 else "down"
    eth_dir = "up" if (crypto.get("eth") or {}).get("change_pct", 0) >= 0 else "down"
    import re as _re
    html = _re.sub(r'\bBTCDIR(?:\s+(?:up|down))?\b', btc_dir, html)
    html = _re.sub(r'\bETHDIR(?:\s+(?:up|down))?\b', eth_dir, html)

    html = _re.sub(r'class="verdict SENTIMENT"', 'class="verdict neutral"', html)
    return html


def _pp_strip_fake_links(html: str, data: dict) -> str:
    import re as _re
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
    return html


def _pp_tw_hint(data: dict) -> dict:
    # 代號 → 公司中英文名：把 ticker 類 span 內的純代號展開成「公司名 + 小灰代號」
    # 完整上市+上櫃名稱表打底,再用持股報價的名稱覆蓋,確保任何台股代號都能展開成中文名
    tw_hint = dict(data.get("tw_names_all", {}))
    for code, d in data.get("tw_market", {}).items():
        if isinstance(d, dict) and d.get("name"):
            tw_hint[code] = d["name"]
    return tw_hint


def _pp_strip_rogue_cards(html: str) -> str:
    import re as _re
    # 清掉 narrative LLM 私自夾帶的 signal-card:批次卡都有 <!--h:SYM--> 標記且過了
    # _card_passes_audit,無標記卡 = 未把關的 rogue 卡(6/11 preflight 抓到 UMAC 虛詞卡
    # + 無 ticker '?' 卡都是這來源,害整封掉 deterministic fallback)。批次卡已 100% 覆蓋
    # 持股,rogue 卡純重複。備援版模板整份無標記 → 「存在標記卡才執行」保住它。
    if "<!--h:" in html:
        html = _re.sub(
            r'<div class="signal-card[ "].*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer|<div class="section-label")',
            lambda m: m.group(0) if "<!--h:" in m.group(0) else "",
            html, flags=_re.DOTALL,
        )
    return html


def _pp_verdict_chip(html: str) -> str:
    import re as _re
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
    return html


def _pp_knife_gate(html: str, _techs_gate: dict) -> str:
    import re as _re
    # 接刀閘門(deterministic):空頭結構(價<MA20<MA50)的個股若卡片還是「建議買入」,
    # 強制降級為觀望條件單 — plan_sim 實證 77 掃停損 vs 2 達標的主要來源就是逆勢接刀,
    # prompt 規則擋第一層,這裡是不靠 LLM 自覺的死防線。

    def _demote_knife(m):
        block = m.group(0)
        hm = _re.search(r"<!--h:([A-Z0-9.]+)-->", block)
        if not hm or _quant_prior(_techs_gate.get(hm.group(1))) != "bear":
            return block
        block = block.replace('class="signal-card buy"', 'class="signal-card wait"', 1)
        block = block.replace('<span class="signal-verdict-chip buy">🟢 建議買入</span>',
                              '<span class="signal-verdict-chip wait">⚪ 觀望·空頭結構(站回 MA20 再議)</span>', 1)
        return block

    html = _re.sub(
        r'<div class="signal-card buy">.*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer)',
        _demote_knife, html, flags=_re.DOTALL,
    )
    return html


def _pp_extended_gate(html: str, _techs_gate: dict, _regime_label: str) -> str:
    import re as _re
    # regime 閘門(deterministic):風險偏多市況 + 個股本身已漲多(RSI14≥70 或站上布林上緣),
    # buy/hold 卡片一律加「漲多勿追/漲多可減」提示 — 2026-06-10 版只靠 prompt 軟性提醒
    # (「漲多的標的要提醒突破才追」),個人化抱單常常沒咬到;這裡補一道不靠 LLM 自覺的死防線,
    # 跟 _demote_knife(逆勢接刀)對稱,但只換 chip 文字不動 reason 段落(避免規則式改寫自然語言出錯)。

    def _demote_extended(m):
        block, cls = m.group(0), m.group(1)
        if _regime_label != "risk_on" or cls not in ("buy", "hold"):
            return block
        hm = _re.search(r"<!--h:([A-Z0-9.]+)-->", block)
        if not hm:
            return block
        t = _techs_gate.get(hm.group(1))
        if _quant_prior(t) != "bull" or not _is_extended(t):
            return block
        if cls == "buy":
            return _re.sub(r'<span class="signal-verdict-chip buy">[^<]*</span>',
                           '<span class="signal-verdict-chip buy">🟢 買入·漲多勿追高</span>', block, count=1)
        return _re.sub(r'<span class="signal-verdict-chip hold">[^<]*</span>',
                       '<span class="signal-verdict-chip hold">🟡 續抱·漲多可減</span>', block, count=1)

    html = _re.sub(
        r'<div class="signal-card (buy|hold)">.*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer)',
        _demote_extended, html, flags=_re.DOTALL,
    )
    return html


def _pp_strip_badges(html: str) -> str:
    import re as _re
    # 卡頭已有彩色 verdict-chip(建議買進/賣出),底部 signal-badge 是同一句重複 → 移除,
    # 讓 signal-meta 只剩「信心 X% · 時間窗」,減少邊邊 chip 把卡片拉長。
    html = _re.sub(r'<span class="signal-badge[^"]*">[^<]*</span>\s*', '', html)
    return html


def _pp_clamp_confidence(html: str) -> str:
    import re as _re
    # 信心校準夾限:公開戰績方向勝率約五成多,顯示 >65% 的信心 = 未校準的過度自信。
    # LLM 已被要求寫 45-65,這裡是 deterministic 死防線(備援版/舊模板也吃得到)。
    def _clamp_conf(m):
        try:
            v = int(m.group(1))
        except ValueError:
            return m.group(0)
        return f"信心 {max(45, min(65, v))}%"

    html = _re.sub(r"信心\s*(\d{1,3})\s*%", _clamp_conf, html)
    return html


def _pp_recalibrate_confidence(html: str, _regime_label: str) -> str:
    import re as _re
    # 信心改由歷史校準表反推:每張卡的信心用 track-record 實測命中率(依 verdict 桶+regime)覆寫,
    # LLM 自填數字只在校準表讀不到時當後備(上面已夾限)。每日戰績更新,數字自動跟著校準。
    def _recalibrate_card(m):
        block, cls = m.group(0), m.group(1)
        hm = _re.search(r"<!--h:([A-Z0-9.]+)-->", block)
        sym = hm.group(1) if hm else ""
        cv = _calibrated_confidence(cls, _regime_label, sym)
        if cv is not None:
            # AI 委員會分歧度回饋:三方意見分歧越大,信心再往下壓(分歧=真實不確定性)
            cverd = _COUNCIL_CACHE.get(sym)
            if cverd and cverd.get("dissent"):
                cv = max(35, cv - cverd["dissent"] * 5)
            block = _re.sub(r'(<span class="signal-confidence">)信心\s*\d{1,3}\s*%',
                            lambda sm: f"{sm.group(1)}信心 {cv}%", block)
        return block

    html = _re.sub(
        r'<div class="signal-card (buy|hold|sell|wait)">.*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer)',
        _recalibrate_card, html, flags=_re.DOTALL,
    )
    return html


def _pp_requalify_buy(html: str, data: dict) -> str:
    import re as _re
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
        if hi < cur * NEAR_HIGH_RATIO:
            block = block.replace("🟢 建議買入", "🟢 回檔再買(現價勿追)")
        return block

    html = _re.sub(
        r'<div class="signal-card buy">.*?(?=<div class="signal-card[ "]|<div class="signal-disclaimer)',
        _requalify_buy, html, flags=_re.DOTALL,
    )
    return html


def _pp_scrub_earnings_notes(html: str, data: dict) -> str:
    import re as _re
    # 財報註記清洗:資料端沒有「已核實預期數字」時,earnings-note 出現任何預期 EPS/營收
    # 都是 LLM 編的 → 換成中性句(deterministic 死防線,搭配 prompt 禁令與 audit)。
    if not any((e or {}).get("eps_est") is not None for e in (data.get("earnings") or [])):
        def _scrub_note(m):
            if _re.search(r"預期\s*EPS|市場預期|每股盈餘|EPS\s*[\d.]|營收[約達成長]*\s*[\d.]+", m.group(2)):
                return m.group(1) + "財報日將近,留意公布後對股價的影響" + m.group(3)
            return m.group(0)

        html = _re.sub(r'(<span class="earnings-note">)([^<]*)(</span>)', _scrub_note, html)
    return html


def _pp_expand_tickers(html: str, tw_hint: dict) -> str:
    import re as _re
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

    # 台股一律只露中文名,不留代碼:清掉內文 LLM 寫的「名稱（2330）」括號代碼。
    # 用名稱表比對只清「真實台股代號」→ 不誤傷年份/價位;美股 ticker 是字母,本規則不碰。
    _tw_codes = set(tw_hint.keys())
    def _strip_tw_paren_code(m):
        return "" if m.group(1) in _tw_codes else m.group(0)
    html = _re.sub(r'[ 　]?[（(]\s*([0-9]{4})\s*[）)]', _strip_tw_paren_code, html)
    return html


def _pp_strip_empty_impact(html: str) -> str:
    import re as _re
    # 沒有任何個股的空「影響個股」區塊直接移除
    def _strip_empty_impact(m):
        return m.group(0) if "impact-stock" in m.group(0) else ""

    html = _re.sub(
        r'<div class="news-impact">.*?</div>',
        _strip_empty_impact, html, flags=_re.DOTALL
    )
    return html


def _pp_drop_empty_sections(html: str) -> str:
    import re as _re
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
    return html


def _pp_hoist_verdict_chip(html: str) -> str:
    import re as _re
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
    return html


def _pp_markdown_bold(html: str) -> str:
    import re as _re
    # LLM 偶爾吐 markdown 粗體 **xxx**,轉成 <strong>,別讓星號直接露在卡片上
    html = _re.sub(r'\*\*([^*\n<]+?)\*\*', r'<strong>\1</strong>', html)
    return html


def _pp_fix_bare_wait(html: str) -> str:
    import re as _re
    # 孤立觀望詞修補:audit(isolated_wait_phrase)同款判定 —— 觀望詞後 60 字內無
    # 價位/事件/日期條件 → 自動補上條件式尾巴,讓「觀望」永遠帶「等什麼」,不留裸虛詞。
    _BARE_WAIT_FIX = {
        "先觀望": "先觀望,等關鍵支撐站穩或利空消化再進場",
        "先別動": "先別動,等站回均線、方向確認再說",
        "保守為上": "保守為上,等站上 MA20 再加碼",
        "靜觀其變": "靜觀其變,等下一個關鍵價位或消息明朗再動",
        "按兵不動": "按兵不動,等突破確認或回測支撐再出手",
    }

    def _fix_bare_wait(h):
        def _repl(m):
            ctx = h[m.start(): m.start() + 60]
            if _re.search(r"\$\d|NT\$?\d|\d+\s*(元|美元|塊|點)|(等|直到).{0,12}(再|才|後)|財報|FOMC|\d+月\d+", ctx):
                return m.group(1)
            return _BARE_WAIT_FIX[m.group(1)]
        return _re.sub(r"(先觀望|先別動|保守為上|靜觀其變|按兵不動)", _repl, h)

    html = _fix_bare_wait(html)
    return html


def _postprocess_html(html: str, data: dict) -> str:
    html = _pp_strip_llm_style(html)
    html = _pp_clear_placeholders(html)
    html = _pp_indicator_class(html, data)
    html = _pp_crypto_dir(html, data)
    html = _pp_strip_fake_links(html, data)
    tw_hint = _pp_tw_hint(data)
    html = _pp_strip_rogue_cards(html)
    html = _pp_verdict_chip(html)
    _techs_gate = data.get("technicals", {}) or {}
    html = _pp_knife_gate(html, _techs_gate)
    _regime_label = _market_regime(data).get("label", "neutral")
    html = _pp_extended_gate(html, _techs_gate, _regime_label)
    html = _pp_strip_badges(html)
    html = _pp_clamp_confidence(html)
    html = _pp_recalibrate_confidence(html, _regime_label)
    html = _pp_requalify_buy(html, data)
    html = _pp_scrub_earnings_notes(html, data)
    html = _pp_expand_tickers(html, tw_hint)
    html = _pp_strip_empty_impact(html)
    html = _pp_drop_empty_sections(html)
    html = _pp_hoist_verdict_chip(html)
    html = _pp_markdown_bold(html)
    html = _pp_fix_bare_wait(html)
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
        parts.append('<li>今晚美股將開盤(美東 9:30 = TW 21:30-22:30)</li>')
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
                parts.append(_mark_card(
                    f'<div class="signal-card hold">'
                    f'<div class="signal-card-top">'
                    f'<span class="signal-ticker">{sym}</span>'
                    f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span>'
                    f'</div>'
                    f'<div class="signal-body">'
                    f'<div class="signal-reason">{name}({sym}) 昨晚收 ${d.get("price","?")} ,'
                    f'{action}。{_impact_note(sym)}今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
                    f'</div></div>', sym
                ))
            else:
                parts.append(_mark_card(
                    f'<div class="signal-card wait">'
                    f'<div class="signal-card-top"><span class="signal-ticker">{sym}</span></div>'
                    f'<div class="signal-body"><div class="signal-reason">'
                    f'{stock_names.display_name(sym)}({sym}) 今日無報價數據</div></div></div>', sym
                ))
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
                parts.append(_mark_card(
                    f'<div class="signal-card hold">'
                    f'<div class="signal-card-top">'
                    f'<span class="signal-ticker">{sym}</span>'
                    f'<span class="signal-day-move {up}">{arrow} {chg:+.2f}%</span>'
                    f'</div>'
                    f'<div class="signal-body">'
                    f'<div class="signal-reason">{name}({sym}) 昨日收 ${d.get("price","?")} 元,'
                    f'{action}。{_impact_note(sym)}今日 AI 分析異常,主編將於 24 小時內修復並重發完整版。</div>'
                    f'</div></div>', sym
                ))
            else:
                parts.append(_mark_card(
                    f'<div class="signal-card wait">'
                    f'<div class="signal-card-top"><span class="signal-ticker">{sym}</span></div>'
                    f'<div class="signal-body"><div class="signal-reason">'
                    f'{stock_names.display_name(sym, d.get("name") if d else None)}({sym}) 今日無報價數據</div></div></div>', sym
                ))
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
    if atr <= 0 or atr > price * ATR_MAX_RATIO:
        atr = price * ATR_FALLBACK_RATIO  # 無 ATR 或異常 → 退回現價估計
    ma20, lo20, hi20 = _f(t.get("ma20")), _f(t.get("lo20")), _f(t.get("hi20"))
    # 低接支撐:現價下方 SUPPORT_ATR_MULT×ATR;若 MA20 / 20 日低更靠近現價(壓力先到)就改用它
    support = price - SUPPORT_ATR_MULT * atr
    for lvl in (ma20, lo20):
        if lvl and support < lvl < price:
            support = lvl
    # 反彈目標:現價上方 TARGET_ATR_MULT×ATR;若 20 日高更近就用 20 日高
    target = price + TARGET_ATR_MULT * atr
    if hi20 and price < hi20 < target:
        target = hi20
    # 停損:支撐再下方一個 ATR,且不得超出 STOP 邊界
    stop = min(support - atr, price - STOP_MAX_ATR_MULT * atr)
    stop = max(stop, price * STOP_FLOOR_RATIO)
    # 夾邊界:任一價位離現價不得過遠
    support = max(support, price * SUPPORT_FLOOR_RATIO)
    target = min(target, price * TARGET_CAP_RATIO)
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


def _quant_prior(t: dict) -> str:
    """個股趨勢結構 prior:bull / bear / neutral。
    篩選器回測(順勢 64% vs 逆勢負期望)+ plan_sim 實證(逆勢接刀 77 掃停損 vs 2 達標)
    → 方向判斷不交給 LLM 自由發揮,先用價格 vs MA20/MA50 的結構當硬 prior。
    只在完整空頭結構(價<MA20<MA50)才判 bear,資料不足一律 neutral(閘門寧鬆勿誤殺)。"""
    if not t:
        return "neutral"
    try:
        p = float(t.get("price") or 0)
        ma20 = float(t.get("ma20") or 0)
        ma50 = float(t.get("ma50") or 0)
    except (TypeError, ValueError):
        return "neutral"
    if not (p and ma20 and ma50):
        return "neutral"
    if p > ma20 > ma50:
        return "bull"
    if p < ma20 < ma50:
        return "bear"
    return "neutral"


def _is_extended(t: dict) -> bool:
    """個股短線是否「漲多」(RSI14≥70 過熱,或站上布林上緣)——標準技術門檻,不靠 LLM 自覺判斷。
    資料不足一律 False(跟 _quant_prior 同哲學:寧鬆勿誤殺)。"""
    if not t:
        return False
    rsi = t.get("rsi14")
    if rsi is not None:
        try:
            if float(rsi) >= 70:
                return True
        except (TypeError, ValueError):
            pass
    try:
        price = float(t.get("price") or 0)
        boll_up = t.get("boll_up")
    except (TypeError, ValueError):
        return False
    if price and boll_up is not None:
        try:
            if price >= float(boll_up):
                return True
        except (TypeError, ValueError):
            pass
    return False


_TRACK_STATS_CACHE = {"loaded": False, "stats": None}


def _track_stats():
    """讀 repo 內 docs/data/track-record.json 的 stats(daily workflow checkout 自帶,每日更新)。
    讀不到回 None → 信心沿用夾限後備,不擋管線。"""
    if not _TRACK_STATS_CACHE["loaded"]:
        _TRACK_STATS_CACHE["loaded"] = True
        try:
            import os
            import json
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "track-record.json")
            with open(p, encoding="utf-8") as f:
                _TRACK_STATS_CACHE["stats"] = (json.load(f) or {}).get("stats") or None
        except Exception:
            _TRACK_STATS_CACHE["stats"] = None
    return _TRACK_STATS_CACHE["stats"]


def _tldr_avoid_edge_note() -> str:
    """避坑/看多勝率動態帶入 TLDR prompt(取代舊版寫死「避坑勝率 86.7% vs 看多 30%」——
    對不上任何真實稽核數字,恐被 LLM 原樣抄進用戶信件,踩禁止虛假數字)。
    優先用 era 桶(現行模型世代,同 _calibrated_confidence 邏輯),n<20 樣本太小就不掛數字只講方向。"""
    s = _track_stats()
    if not s:
        return "避坑是我們實測最強的能力,每天都要交付"
    era = s.get("era") or {}
    src = era if era.get("c_count") else s
    a_n, c_n = src.get("a_count") or 0, src.get("c_count") or 0
    a_rate, c_rate = src.get("a_rate"), src.get("c_rate")
    if c_rate is not None and c_n >= 20 and a_rate is not None and a_n >= 20:
        return f"避坑是我們實測最強的能力(避坑勝率 {c_rate:.1f}% vs 看多 {a_rate:.1f}%),每天都要交付"
    if c_rate is not None and c_n >= 20:
        return f"避坑是我們實測最強的能力(避坑勝率 {c_rate:.1f}%),每天都要交付"
    return "避坑是我們實測最強的能力,每天都要交付"


def _calibrated_confidence(card_cls: str, regime_label: str, sym: str = ""):
    """信心 = 歷史校準表反推,不採 LLM 自填(實測 LLM 自填信心 Brier 0.513、>70% 只對 17% = 反指標)。
    桶:buy→A 看多命中率(依 regime 分桶)、sell→C 避坑命中率、hold/wait→50。
    empirical 向 50% 收縮(K=20 偽樣本)抗小樣本噪音;±3 穩定抖動防整批同數字。無資料回 None。"""
    s = _track_stats()
    if not s:
        return None
    # 2026-07-03 回測診斷修復:只吃「現行模型世代」(6/12 起,stats["era"])的桶,不吃全期混算——
    # 舊世代(LLM 自填信心)實測是反指標,混算會把舊毒回饋進今日信心,形成永遠洗不掉的自我迴圈
    # (實例:全期 up-regime 桶 20.1% 把 risk_on 買進卡信心壓到 35,而新世代同桶實際 ~61%)。
    # era 桶樣本小沒關係,K=20 收縮自然拉向 50 = 誠實的「還不知道」。
    src = s.get("era") if (s.get("era") or {}).get("a_count") else s
    K = 20.0

    def _shrunk(w, n):
        try:
            w, n = float(w), float(n)
        except (TypeError, ValueError):
            return None
        if n <= 0:
            return None
        return (w + K * 0.5) / (n + K) * 100.0

    v = None
    if card_cls == "buy":
        br = src.get("by_regime") or {}
        bucket = br.get("up") if regime_label == "risk_on" else (br.get("down") if regime_label == "risk_off" else None)
        if bucket:
            v = _shrunk(bucket.get("a_wins"), bucket.get("a_count"))
        if v is None:
            v = _shrunk(src.get("a_wins"), src.get("a_count"))
    elif card_cls == "sell":
        v = _shrunk(src.get("c_wins"), src.get("c_count"))
    else:
        v = 50.0
    if v is None:
        return None
    jitter = (sum(ord(ch) for ch in str(sym)) % 7) - 3
    return int(max(35, min(75, round(v + jitter))))


# ── AI 投資委員會(multi-model council)──────────────────────────────────
# 用戶要的不是「fallback(一個模型講了算,其餘只當備援)」,而是「多個 AI 一起辯論再下決策」。
# 死防線不變:方向仍由結構 prior(_quant_prior)鎖死、信心仍由 track-record 校準;
# council 只在「論點 / 反向風險 / 結構容許範圍內的傾向」這層運作,並把三模型「分歧度」
# 回饋給信心(分歧大→信心再往下壓)。每支股票一輪只跑一次,跨用戶共用 _COUNCIL_CACHE。
# 席次 = 真.跨廠商多模型:Gemini(2.5-lite/2.0,各自獨立配額桶)+ Claude Haiku。
# 2026-06-30 實測:ANTHROPIC_API_KEY 正常(sonnet/haiku 皆 200),所以 Claude 是真席次;
# OpenAI 純因 .env 未設 key → _call_openai raise 自動跳過(非錯誤),補上 key 即多一席。
# 配額保護:Gemini 席次用 lite/2.0(獨立桶),把 2.5-flash 留給用戶可見的卡片生成,避免
# council 吃爆配額害卡片掉備援版;Claude 席次/裁判用便宜的 Haiku;每輪上限 _COUNCIL_MAX 支。
# 席次/裁判一律傳乾淨的分析師 system(_COUNCIL_SYS),不沿用 HTML 生成器 system 以免被帶歪。
_COUNCIL_CACHE: dict = {}
_COUNCIL_ENABLED = os.environ.get("DIGEST_COUNCIL", "1") != "0"
_COUNCIL_MAX = int(os.environ.get("DIGEST_COUNCIL_MAX", "40") or "40")
_COUNCIL_SYS = "你是嚴謹務實的台美股短線分析師。只輸出被要求的 JSON,不寫任何多餘文字、不要 HTML、不要 markdown。"
_COUNCIL_HAIKU = "claude-haiku-4-5-20251001"
_COUNCIL_SEATS = [
    ("gemini:2.5-lite", lambda p: _call_gemini(p, "gemini-2.5-flash-lite", system=_COUNCIL_SYS)),
    ("gemini:2.0-flash", lambda p: _call_gemini(p, "gemini-2.0-flash", system=_COUNCIL_SYS)),
    # Groq:免費且獨立配額桶。gpt-oss-120b 免費層 TPM 只有 8000,席次回應是小 JSON,
    # max_tokens 必須壓小,否則 prompt+max_tokens 超過每分鐘 token 預算 → 全數 413
    # (2026-07-01 換模型後連兩天 36/36 全滅的根因)
    ("groq:gpt-oss-120b", lambda p: _call_groq(p, system=_COUNCIL_SYS, max_tokens=1000)),
    ("claude:haiku", lambda p: _call_claude(p, system=_COUNCIL_SYS, model=_COUNCIL_HAIKU)),
    # Sonnet 當第二把 Claude 聲音:Gemini 全 429 時仍湊得到 ≥2 席,council 不會整個熄火
    ("claude:sonnet", lambda p: _call_claude(p, system=_COUNCIL_SYS, model="claude-sonnet-4-6")),
    # winrig 本地 5080(零配額零429):清晨 Gemini 必空桶時保底的第三把獨立聲音;
    # 雲端 CI 環境連不上 localhost → 席次熔斷自動停用,不影響
    ("local:qwen2.5-14b", lambda p: _call_ollama(p, system=_COUNCIL_SYS, max_tokens=300)),
    # Cloudflare Workers AI(免費 10k neurons/日,經 md-ai-proxy):第四家獨立廠商聲音
    ("cf:llama-3.3-70b", lambda p: _call_cf_ai(p, system=_COUNCIL_SYS, max_tokens=300)),
    # 預接線:沒 key raise→席次自動停用;用戶註冊後填 .env 即多一席,不需改程式
    ("openrouter:llama-70b", lambda p: _call_openrouter(p, system=_COUNCIL_SYS, max_tokens=300)),
    ("cerebras:llama-70b", lambda p: _call_cerebras(p, system=_COUNCIL_SYS, max_tokens=300)),
    ("openai", lambda p: _call_openai(p, system=_COUNCIL_SYS)),
]
_COUNCIL_JUDGE = lambda p: _call_claude(p, system=_COUNCIL_SYS, model=_COUNCIL_HAIKU)
# 席次級熔斷:某席配額耗盡/沒 key/連敗 3 次 → 本輪剩餘標的直接跳過該席,
# 只在停用當下印一行。否則 36 支持股 × 3 個死席 = 百餘行失敗 log,
# council_check 的 q429 門檻天天爆表誤判紅色(2026-07-02 用戶反映的洗版根因)。
_COUNCIL_SEAT_DEAD: dict = {}
_COUNCIL_SEAT_FAILS: dict = {}
_COUNCIL_DEAD_MARKERS = ("熔斷", "未設定", "配額耗盡", "413", "連不上")


def _council_seat_call(nm, fn, prompt: str):
    if nm in _COUNCIL_SEAT_DEAD:
        return None
    try:
        o = _council_json(fn, prompt)
        _COUNCIL_SEAT_FAILS[nm] = 0
        return o
    except Exception as ex:
        msg = str(ex)
        _COUNCIL_SEAT_FAILS[nm] = _COUNCIL_SEAT_FAILS.get(nm, 0) + 1
        if any(k in msg for k in _COUNCIL_DEAD_MARKERS) or _COUNCIL_SEAT_FAILS[nm] >= 3:
            _COUNCIL_SEAT_DEAD[nm] = msg[:60]
            print(f"  [council] 席次 {nm} 本輪停用({msg[:60]})")
        else:
            print(f"  [council] 席次 {nm} 失敗({msg[:60]})")
        return None


def _council_json(fn, prompt: str) -> dict:
    import json
    raw = fn(prompt)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("no json")
    return json.loads(raw[s:e + 1])


def _council_one(sym: str, name_zh: str, block_line: str, prior: str):
    """3 模型各給傾向+論點+風險 → 裁判綜合。回 verdict dict 或 None(不足成會)。"""
    import json
    prior_txt = {
        "bull": "多頭結構(價>MA20>MA50)——傾向只能 long 或 neutral,禁止 short",
        "bear": "空頭結構(價<MA20<MA50)——傾向只能 short 或 neutral,禁止 long",
        "neutral": "盤整——long/short/neutral 皆可,依數據判斷",
    }.get(prior, "盤整——依數據判斷")
    seat_prompt = (
        f"你是台美股短線分析委員之一,獨立判斷 {name_zh}({sym}) 未來 1-2 週傾向。只看數據,不要客套。\n"
        f"【真實數據】{block_line}\n"
        f"【結構硬約束】{prior_txt}。\n"
        f"只輸出 JSON,不要其他字:"
        f'{{"lean":"long|short|neutral","conviction":1-5,'
        f'"thesis":"<=35字 為何是這傾向","key_risk":"<=25字 什麼會推翻它"}}'
    )
    opinions = []
    for nm, fn in _COUNCIL_SEATS:
        o = _council_seat_call(nm, fn, seat_prompt)
        if o is None:
            continue
        lean = str(o.get("lean", "")).lower()
        if lean not in ("long", "short", "neutral"):
            lean = "neutral"
        # 結構硬約束:違反方向的傾向降為 neutral(死防線,席次不可翻方向)
        if prior == "bull" and lean == "short":
            lean = "neutral"
        if prior == "bear" and lean == "long":
            lean = "neutral"
        try:
            conv = max(1, min(5, int(o.get("conviction") or 3)))
        except (TypeError, ValueError):
            conv = 3
        opinions.append({"seat": nm, "lean": lean, "conviction": conv,
                         "thesis": str(o.get("thesis") or "")[:120],
                         "key_risk": str(o.get("key_risk") or "")[:90]})
    if len(opinions) < 2:
        return None
    leans = [o["lean"] for o in opinions]
    uniq = set(leans)
    if len(uniq) == 1:
        dissent = 0
    elif "long" in uniq and "short" in uniq:
        dissent = 2
    else:
        dissent = 1
    thesis = key_risk = ""
    judge_prompt = (
        f"你是首席分析師,裁判 {name_zh}({sym}) 委員會三方意見,產出最終卡片用論點。\n"
        f"【結構約束】{prior_txt}\n【三方意見】{json.dumps(opinions, ensure_ascii=False)}\n"
        f"綜合共識與分歧(不要只抄一家)。只輸出 JSON:"
        f'{{"thesis":"<=45字 口語最終論點","key_risk":"<=30字 最該盯的反向風險"}}'
    )
    try:
        j = _council_json(_COUNCIL_JUDGE, judge_prompt)
        thesis = str(j.get("thesis") or "")[:140]
        key_risk = str(j.get("key_risk") or "")[:100]
    except Exception as ex:
        print(f"  [council] {sym} 裁判失敗,改用最高信念席次({str(ex)[:60]})")
    if not thesis:
        top = max(opinions, key=lambda o: o["conviction"])
        thesis, key_risk = top["thesis"], top["key_risk"]
    return {"sym": sym, "prior": prior, "thesis": thesis, "key_risk": key_risk,
            "dissent": dissent, "n": len(opinions), "leans": leans}


def build_council(data: dict, stocks: list, depth: str = "standard") -> dict:
    """為這批持股建立 AI 委員會共識(每支一輪只跑一次,跨用戶共用快取)。
    fail-safe:停用 / 任何失敗 → 回傳當下已有的結果(可能空),絕不擋管線。"""
    if not _COUNCIL_ENABLED:
        return {}
    tech = data.get("technicals", {}) or {}
    all_m = {**(data.get("us_market", {}) or {}), **(data.get("tw_market", {}) or {})}
    seen = [s for s in dict.fromkeys([x for x in (stocks or []) if x])]
    todo = [s for s in seen if s not in _COUNCIL_CACHE]
    capped = todo[:_COUNCIL_MAX]
    if len(todo) > _COUNCIL_MAX:
        print(f"  [council] 本輪 {len(todo)} 支新標的超過上限 {_COUNCIL_MAX},只跑前 {_COUNCIL_MAX} 支(其餘走原單模型路徑)")
    for sym in capped:
        try:
            block = _chunk_market_tech_block(data, [sym], depth).strip()
            prior = _quant_prior(tech.get(sym))
            nm = stock_names.display_name(sym, (all_m.get(sym) or {}).get("name"))
            v = _council_one(sym, nm, block, prior)
        except Exception as ex:
            print(f"  [council] {sym} 整體失敗({str(ex)[:60]})")
            v = None
        if v:
            _COUNCIL_CACHE[sym] = v
            print(f"  [council] {sym} 共識 dissent={v['dissent']} ({v['n']}席): {v['thesis'][:30]}")
        time.sleep(1)
    return {s: _COUNCIL_CACHE[s] for s in seen if s in _COUNCIL_CACHE}


def _council_prompt_block(council: dict, chunk: list) -> str:
    """把委員會共識組成注入卡片 prompt 的文字塊。"""
    if not council:
        return ""
    lines = []
    for s in chunk:
        v = council.get(s)
        if not v:
            continue
        tag = ("(三方分歧大,語氣需保守)" if v["dissent"] >= 2
               else ("(三方略有分歧)" if v["dissent"] == 1 else ""))
        line = f"  {s}:論點—{v['thesis']}"
        if v.get("key_risk"):
            line += f";反向風險—{v['key_risk']}"
        lines.append(line + tag)
    if not lines:
        return ""
    return ("\n【AI 投資委員會共識(多模型辯論+裁判綜合;方向已由技術結構鎖定,以下是論點與風險)】\n"
            "把每支對應的「論點」融進該卡 signal-reason、「反向風險」寫進 signal-watch;"
            "不可自創與委員會相反的論點;標『分歧大』的那幾支語氣要保守、別給高信心口吻。\n"
            + "\n".join(lines) + "\n")


# ── AI 委員會公版精選(給沒選該市場持股的用戶,每天保證兩封信)────────────
# 合規(COMPLIANCE_STRUCTURE.md):精選對所有用戶完全相同、免費全開,不依付費差異化。
_PICKS_CACHE: dict = {}


def _momentum_picks(data: dict, market: str, n: int, exclude: set = None) -> list:
    """無 LLM 的保底選股:多頭結構(價>MA20>MA50)優先,其次當日動能。"""
    exclude = exclude or set()
    mkt = (data.get("us_market") if market == "us" else data.get("tw_market")) or {}
    tech = data.get("technicals", {}) or {}
    cands = [s for s in mkt if not s.startswith("^") and s not in exclude
             and (mkt.get(s) or {}).get("price") is not None]

    def _key(s):
        prior = _quant_prior(tech.get(s))
        chg = (mkt.get(s) or {}).get("change_pct", 0) or 0
        return (1 if prior == "bull" else 0, chg)

    return sorted(cands, key=_key, reverse=True)[:n]


def council_top_picks(data: dict, market: str, n: int = 3) -> list:
    """AI 委員會投票選出「今日最有潛力」的 n 支公版精選。
    每輪只跑一次(快取),所有用戶共用同一份結果。
    fail-safe:席次不足 / 全失敗 → 動能保底選股;絕不拋例外、絕不擋寄信。"""
    key = (market, n)
    if key in _PICKS_CACHE:
        return _PICKS_CACHE[key]
    picks: list = []
    try:
        mkt = (data.get("us_market") if market == "us" else data.get("tw_market")) or {}
        tech = data.get("technicals", {}) or {}
        cands = [s for s in mkt if not s.startswith("^")
                 and (mkt.get(s) or {}).get("price") is not None]
        # 有技術數據者優先(卡片能錨真實價位),再按當日波動排序;候選壓 20 支內控 prompt 長度
        cands.sort(key=lambda s: (s in tech, abs((mkt.get(s) or {}).get("change_pct", 0) or 0)), reverse=True)
        cands = cands[:20]
        if len(cands) <= n:
            picks = list(cands)
        else:
            lines = []
            for s in cands:
                m = mkt.get(s) or {}
                nm = stock_names.display_name(s, m.get("name"))
                prior = {"bull": "多頭", "bear": "空頭"}.get(_quant_prior(tech.get(s)), "盤整")
                lines.append(f"{nm}({s}) 現價{m.get('price')} 今日{(m.get('change_pct') or 0):+.2f}% 結構:{prior}")
            label = "美股" if market == "us" else "台股"
            seat_prompt = (
                f"你是投資委員會委員之一,獨立判斷、不要客套。從下列{label}候選(皆為真實今日數據)中,"
                f"選出未來 1-2 週最有潛力的 {n} 支,優先多頭結構、有明確題材或動能者。\n"
                + "\n".join(lines) + "\n"
                '只輸出 JSON,不要其他字:{"picks":["代號","代號","代號"]}'
                "(依看好程度排序,代號必須來自上面候選清單)"
            )
            scores: dict = {}
            voters = 0
            for nm_, fn in _COUNCIL_SEATS:
                o = _council_seat_call(nm_, fn, seat_prompt)
                if not o:
                    continue
                got = False
                for rank, p in enumerate([str(x).upper().strip() for x in (o.get("picks") or []) if x][:n]):
                    hit = next((c for c in cands if c == p or c in p), None)
                    if hit:
                        scores[hit] = scores.get(hit, 0) + (n - rank)
                        got = True
                if got:
                    voters += 1
            if voters >= 2 and scores:
                picks = sorted(scores, key=lambda s: -scores[s])[:n]
                print(f"  [picks] {market} 委員會 {voters} 席投票 → {picks}")
            else:
                print(f"  [picks] {market} 委員會席次不足({voters} 席) → 動能保底選股")
        if len(picks) < n:
            picks += _momentum_picks(data, market, n - len(picks), exclude=set(picks))
    except Exception as ex:
        print(f"  [picks] {market} 選股整體失敗({str(ex)[:80]}) → 動能保底")
        try:
            picks = _momentum_picks(data, market, n)
        except Exception:
            picks = []
    _PICKS_CACHE[key] = picks
    return picks


# 精選模式 prompt 口吻鐵則(三個報告變體共用):標的非用戶持有,不可寫成「你的持股」
_PICKS_PROMPT_NOTE = (
    "【重要口吻鐵則:這位用戶尚未設定本班次市場的持股,報告裡的個股是系統 AI 委員會今日公版精選"
    "(推薦研究用,用戶並未持有)。所有個股卡片與敘述一律用「值得關注/建議研究/若要進場可看 $X」"
    "的推薦口吻,嚴禁出現「你的持股/你持有/你的部位/加碼/減碼/續抱」這類已持有措辭"
    "(操作動詞用 買進/觀望/先別進場)。結構與格式照常。】\n\n"
)


def _depth_directive(depth: str) -> str:
    """日報深度客製(全體用戶可選)注入 prompt 的指令。simple=精簡 / deep=深入 / standard=不加。"""
    if depth == "simple":
        return ("【深度設定:精簡版 = 純重點操作】這位用戶選了「簡單看」—— 只輸出 TLDR(30秒重點)+ 每支持股的操作卡 + 今天的結論。"
                "完全不要新聞區塊(不要『今天最重要的5件事』、不要『持倉深度追蹤』)、不要大盤/加密/財報/板塊/進階指標。"
                "每支股票一兩句講重點:該買/抱/賣 + 條件(價位或事件),不鋪陳。")
    if depth == "deep":
        return ("【深度設定:深入版 = 標準版全部再加碼】這位用戶選了「看深入」—— 保留標準版的一切(操作卡 + 新聞 + 技術 + 大盤),"
                "並針對每支持股額外補充:(1) 進階技術判讀 —— 結合系統提供的 RSI/KD/MACD/布林通道/均線排列(多頭或空頭)/黃金或死亡交叉,"
                "白話講這檔現在動能與超買超賣狀態、趨勢方向、關鍵技術訊號(只能引用提供的真實指標數字,嚴禁自行編造指標值);"
                "(2) 估值看法(便宜/合理/偏貴,只能依提供的真實數據,不可臆測本益比或編造財務數字);若系統提供了「DCF 合理價區間」,"
                "務必拿現價跟區間比對,白話講是低於下緣(潛在低估、較有安全邊際)、落在區間內(合理)、還是高於上緣(潛在高估、追高要留意),"
                "並提醒 DCF 對成長與折現率假設敏感、區間是參考非精準目標價;本益比法與 DCF 若一個喊貴一個喊便宜,要並陳兩個角度別只報一邊;"
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
- 有附「量能」時(相對量比 / 帶量·量縮 / 量價配合·背離)當**確認佐證**融進 reason 或 watch:突破/進場最好帶量確認、價漲量縮或量能背離要在 watch 提醒風險。**量能只是佐證,不可拿來改 verdict 方向或信心**(方向已由結構鎖定)。
- 進場 / 目標 / 停損價位必須落在下方該股真實技術價位的合理範圍,美股美元、台股台幣,**嚴禁編造偏離現價的數字**
- ‼️ **信心校準**:我們的公開戰績統計顯示短線方向判斷準確率約五成多,信心欄位一律寫 45-65%(整批不可同一個數字),**禁止出現 >65% 的信心** — 戰績實測「信心>70%」的卡實際只對 17%,高信心是反指標
- ‼️ **進場必須有站穩確認(任何市場狀態都適用)**:買進條件一律寫「回測 $X 不破、收盤收復 $Y 再分批接」這種**確認式條件**,嚴禁「跌到 $X 就接」「回到買區即買進」— 操作模擬實測:照「跌入買區就接」執行,77 筆掃停損 vs 2 筆達標(期望值 -4.1%/筆),跌勢中價格進入買區正是刀還在掉的時候
- ‼️ **同質性禁令**:若整批標的多數同向漲跌,不可每支複製同一套「跌到 20 日低 → 低接買進反彈 MA20」模板;逐支看趨勢位置(站上/跌破 MA20)、動能與消息差異,verdict 與 reason 必須有真實差異
- ‼️ **趨勢結構鐵則(量化 prior,優先於你自己的方向判斷)**:技術行標「結構:空頭」的個股**禁止 buy verdict**——只能 wait/hold + 站回 MA20 之上的條件單(系統會強制改寫違規卡,別浪費字);標「結構:多頭」的不寫「跌到 X 低接」,改順勢條件(回測 MA20 不破續抱、突破前高加碼)。方向交給結構,你負責講清楚理由、風險與條件價位
- 信心欄位照 45-65 填即可,系統會用歷史戰績校準表覆寫成實測命中率,你的數字只是版面占位"""


def _vol_str(t: dict) -> str:
    """量能佐證一行字(全檔次用):相對量比+狀態+量價配合/背離。只取有值的。"""
    if not t or t.get("vol_ratio") is None:
        return ""
    s = f"量能:相對量 {t['vol_ratio']}x"
    if t.get("vol_state"):
        s += f"({t['vol_state']})"
    if t.get("pv"):
        s += "," + t["pv"]
    return s


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


def _macro_backdrop_note(data: dict) -> str:
    """大盤宏觀背景一句(標準+看深入注入個股 prompt 當連動參考)。只取有值的真實數字。"""
    ind = (data or {}).get("indicators") or {}
    parts = []
    fg = ind.get("fear_greed") or {}
    if fg.get("rating"):
        parts.append(f"市場情緒 {fg['rating']}(VIX {_fmt_num(ind.get('vix'))})")
    if ind.get("us10y") is not None:
        parts.append(f"美10年債殖利率 {_fmt_num(ind.get('us10y'))}%")
    oil = ind.get("oil") or {}
    if oil.get("price") is not None:
        parts.append(f"原油 {_fmt_num(oil.get('price'))}({(oil.get('change_pct') or 0):+.1f}%)")
    gold = ind.get("gold") or {}
    if gold.get("price") is not None:
        parts.append(f"黃金 {_fmt_num(gold.get('price'))}({(gold.get('change_pct') or 0):+.1f}%)")
    twd = ind.get("usdtwd") or {}
    if twd.get("rate") is not None:
        parts.append(f"美元台幣 {_fmt_num(twd.get('rate'))}")
    return " ｜ ".join(parts)


def _portfolio_lens_block(data: dict, holdings: list, depth: str = "standard") -> str:
    """組合透視(看深入專屬):純計算整個持股的集中度與最大組合風險,缺料/持股太少不談。
    只用既有資料(結構 prior / 政壇訊號 / 估值 / 籌碼),不編造、不經 LLM。"""
    if depth != "deep":
        return ""
    holds = list(dict.fromkeys([h for h in (holdings or []) if h]))
    if len(holds) < 3:
        return ""
    tech = data.get("technicals", {}) or {}
    allm = {**(data.get("us_market") or {}), **(data.get("tw_market") or {})}
    fund = data.get("fundamentals") or {}
    n = len(holds)
    bull = bear = neu = up = down = 0
    for h in holds:
        p = _quant_prior(tech.get(h))
        bull += p == "bull"; bear += p == "bear"; neu += p == "neutral"
        chg = (allm.get(h) or {}).get("change_pct")
        if chg is not None:
            up += chg >= 0; down += chg < 0
    tw_n = sum(1 for h in holds if str(h).isdigit())
    us_n = n - tw_n
    pol_tks = set()
    for s in (data.get("political_signals") or []):
        for t in (s.get("affected") or []):
            pol_tks.add(str(t).upper())
    pol_hit = [h for h in holds if str(h).upper() in pol_tks]
    rich = [h for h in holds if (fund.get(h) or {}).get("val_class") == "rich"]
    sell_chips = [h for h in holds if (fund.get(h) or {}).get("chip_class") == "sell"]
    dcf_over = []
    for h in holds:
        hi = (fund.get(h) or {}).get("dcf_high")
        px = (allm.get(h) or {}).get("price")
        if hi and px and px > hi:
            dcf_over.append(h)
    overvalued = [h for h in holds if h in rich or h in dcf_over]  # 本益比或DCF任一偏貴

    rows = [f"<b>結構分佈</b>:多頭 {bull} / 盤整 {neu} / 空頭 {bear}（共 {n} 檔）"]
    if us_n and tw_n:
        rows.append(f"<b>市場配置</b>:美股 {us_n} 檔、台股 {tw_n} 檔")
    elif tw_n:
        rows.append(f"<b>市場配置</b>:全部 {tw_n} 檔台股(單一市場)")
    else:
        rows.append(f"<b>市場配置</b>:全部 {us_n} 檔美股(單一市場)")
    if rich:
        rows.append(f"<b>估值偏貴</b>:{', '.join(rich[:5])}（追高風險集中)")
    if dcf_over:
        rows.append(f"<b>DCF 內在價值偏貴</b>:{', '.join(dcf_over[:5])}（現價高於折現合理區間上緣)")
    if sell_chips:
        rows.append(f"<b>法人/內部人偏賣</b>:{', '.join(sell_chips[:5])}")
    if pol_hit:
        rows.append(f"<b>政策面曝險</b>:{', '.join(pol_hit[:5])} 同受今日政壇訊號波及")

    half = max(2, round(n * 0.5))
    if bear >= half:
        risk = f"{bear}/{n} 檔處於空頭結構,組合同向下行風險高 —— 別整批低接,優先減碼最弱、保留現金等止穩。"
    elif len(overvalued) >= max(2, round(n * 0.4)):
        risk = f"{len(overvalued)} 檔估值偏貴(本益比或 DCF 內在價值),追高風險集中在高估值族群 —— 高檔不加碼,等回檔再評估。"
    elif len(pol_hit) >= 2:
        risk = f"{len(pol_hit)} 檔同受今日政壇/政策訊號波及,政策面是這組持股的共同變數 —— 盯後續政策確認再決定加減碼。"
    elif (us_n == 0) ^ (tw_n == 0):
        risk = "持股集中單一市場,缺乏跨市場分散 —— 該市場若系統性回檔,整組一起受傷。"
    elif bull >= half:
        risk = f"{bull}/{n} 檔多頭結構,順勢但同向 —— 大盤一旦轉弱會一起拉回,設好整組停利紀律。"
    else:
        risk = "持股結構分散、無單一面向過度集中,維持現有紀律即可。"

    rows_html = "".join(
        f'<div style="font-size:13px;color:#3a3a3c;margin:4px 0;line-height:1.55;">• {r}</div>' for r in rows
    )
    return (
        '<div class="section-label">🧭 你的組合透視（看深入專屬）</div>'
        '<div class="news-card" style="border-color:#dfe3ff;">'
        '<div style="font-size:12px;color:#8e8e93;margin-bottom:7px;line-height:1.5;">'
        '把你整組持股放在一起看 —— 不只逐支,而是集中度與最大共同風險。</div>'
        f'{rows_html}'
        f'<div style="margin-top:9px;padding:8px 11px;background:#fff4e0;'
        f'border-left:3px solid #f59e0b;border-radius:8px;font-size:13px;color:#8a4500;line-height:1.55;">'
        f'⚠️ <b>最大組合風險</b>:{risk}</div>'
        '</div>'
    )


def _chunk_market_tech_block(data: dict, chunk: list, depth: str = "standard") -> str:
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    tech = data.get("technicals", {}) or {}
    impacts = data.get("earnings_impact", {}) or {}
    # 政治訊號回饋:把被點名個股對映到該則訊號(標準+看深入用,簡單看不注入)
    pol_by_tk = {}
    if depth != "simple":
        for s in (data.get("political_signals") or []):
            for tk in (s.get("affected") or []):
                pol_by_tk.setdefault(str(tk).upper(), s)
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
            _prior_txt = {"bull": "多頭結構(價>MA20>MA50,順勢操作,不寫逢低接)",
                          "bear": "空頭結構(價<MA20<MA50,禁建議買入,最多站回MA20的觀望條件)",
                          "neutral": "盤整(中性,逐支看消息與位置)"}[_quant_prior(t)]
            base += f" | 結構:{_prior_txt}"
            sup, tgt, stp = _near_term_levels(t.get("price"), t)
            if sup is not None:
                base += f" ‖ 近端操作錨點(直接用這組設買賣價)→低接 {_fmt_num(sup)} / 反彈目標 {_fmt_num(tgt)} / 停損 {_fmt_num(stp)}"
            if depth != "simple":
                vs = _vol_str(t)
                if vs:
                    base += " | " + vs
            if depth == "deep":
                adv = _adv_tech_str(t)
                if adv:
                    base += " | " + adv
        a = impacts.get(sym)
        if a and a.get("is_event") and a.get("yoy") is not None:
            base += f" | 剛公布{a.get('kind','財報')} YoY {a['yoy']:+.1f}% {a.get('verdict','')}"
        elif a and depth != "simple":
            # 非事件日基本面脈絡:連續成長 / 累計 YoY / 近期 YoY(標準+看深入,當背景非喊話)
            g = []
            if a.get("streak", 0) >= 2:
                g.append(f"營收連{a['streak']}月正成長")
            if a.get("cum_yoy") is not None:
                g.append(f"累計YoY {a['cum_yoy']:+.1f}%")
            elif a.get("yoy") is not None:
                g.append(f"近期YoY {a['yoy']:+.1f}%")
            if a.get("eps_yoy") is not None:
                g.append(f"EPS YoY {a['eps_yoy']:+.1f}%")
            if g:
                base += f" | 基本面背景:{'、'.join(g)}"
        ps = pol_by_tk.get(str(sym).upper())
        if ps:
            _dir = {"bullish": "偏多", "bearish": "偏空", "mixed": "分歧"}.get(ps.get("direction"), "分歧")
            base += f" | ⚡政壇訊號({_dir}/強度{ps.get('severity','?')}):{str(ps.get('headline_zh') or '')[:38]}"
        if depth == "deep":
            f = (data.get("fundamentals") or {}).get(sym) or {}
            if f.get("valuation"):
                base += f" | 估值:{f['valuation']}"
            if f.get("dcf"):
                base += f" | {f['dcf']}"
                price, lo, hi = m.get("price"), f.get("dcf_low"), f.get("dcf_high")
                if price and lo and hi:
                    if price < lo:
                        base += f"(現價 {_fmt_num(price)} 低於區間下緣,潛在低估)"
                    elif price > hi:
                        base += f"(現價 {_fmt_num(price)} 高於區間上緣,潛在高估、留意追高)"
                    else:
                        base += f"(現價 {_fmt_num(price)} 落在合理區間內)"
            if f.get("chips"):
                base += f" | 籌碼:{f['chips']}"
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
    if _quant_prior(tech) == "bear":
        ma20 = (tech or {}).get("ma20")
        reclaim = _fmt_num(ma20) if ma20 else _fmt_num(buy_hi)
        reason = (f'{name}({sym}) 收 ${_fmt_num(price)}{unit}({chg:+.2f}%),目前空頭結構(價<MA20<MA50),先不接。'
                  f'{when}後站回 ${reclaim}{unit} 之上並收穩再評估分批;持有者跌破 ${_fmt_num(stop)}{unit} 先減碼控風險。')
    else:
        reason = (f'{name}({sym}) 收 ${_fmt_num(price)}{unit}({chg:+.2f}%)。'
                  f'{when}後若回測 ${_fmt_num(buy_lo)}{unit} 不破、收盤收復 ${_fmt_num(buy_hi)}{unit} 再分批接,'
                  f'跌破 ${_fmt_num(stop)}{unit} 先停損;本週留意 ${_fmt_num(target)}{unit} 壓力。')
    # 備援卡 reason 含字面「價<MA20<MA50」,< 會被瀏覽器當 HTML 標籤吃掉→文字斷在「(價」+版型變形。
    # 轉全形保證渲染不破(備援路徑必須零失敗)。
    reason = reason.replace("<", "＜").replace(">", "＞")
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


def _render_signal_cards_batched(data: dict, stocks: list, mkt_status: dict, full_limit: int = None, prefer_strong: bool = False, depth: str = "standard", picks_mode: bool = False) -> str:
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
    council = build_council(data, llm_stocks, depth)
    cards_by_sym = {}
    CHUNK = 10
    deep_tech_note = ("\n【專業版要求】這位用戶選了「看深入」,上面可能附了 RSI/KD/MACD/布林/均線排列/交叉等進階指標,以及「估值」「籌碼」。"
                          "每張卡的「下一步」說明要結合這些判讀:\n"
                          "- 進階指標:RSI>70 過熱留意拉回、KD 低檔黃金交叉可偏多、MACD 柱由負轉正轉強、跌破布林下軌或站上中軌,用白話講並對應具體價位。\n"
                          "- 估值:把「估值」那句(本益比/百分位/PEG)寫進 reason 當體質判斷——偏貴→提醒追高風險、別在高檔重壓;相對便宜→回檔較有撐。"
                          "**估值只影響語氣與部位心態,不可拿來改寫技術面的進場/目標/停損價位(價位一律照近端錨點)**。\n"
                          "- 籌碼:把「籌碼」那句(外資/投信買賣超、內部人動向)寫進 signal-watch 當該盯的事;法人連續賣超是警訊、連續買超是支撐,但仍以技術結構定方向。\n"
                          "- 雙情境(看深入加值):signal-reason 結尾用一句講兩條路——「若站上/跌破 $X 則偏多看 $A;若失守/突破不過 $Y 則轉弱看 $B」,用真實技術價位,給用戶條件分支而非單點。\n"
                          "- 反方風險:signal-watch 除了該盯的事,再點一句「什麼會推翻這個判斷」(例:跌破 $X 多頭結構就破功、財報不如預期、外資轉賣),讓用戶知道自己可能錯在哪。\n"
                          "只能引用上面提供的真實數字,沒附的指標/估值/籌碼就不要提,嚴禁自行編造任何數字。\n"
                          if depth == "deep" else "")
    macro_note = ""
    if depth != "simple":
        _mb = _macro_backdrop_note(data)
        macro_note = (
            f"\n【今日宏觀背景(真實數據)】{_mb}\n" if _mb else "\n"
        ) + (
                "【新資料用法 — 只補強理由與觀察,不得改寫方向/價位/信心】\n"
                "- 標到「⚡政壇訊號」的個股:在該卡 signal-reason 或 signal-watch 點出這則訊號對它的影響(關稅/利率/補貼等),"
                "把它列為「該盯的事」;但 verdict 方向仍以技術結構為準,政壇訊號只調整語氣與觀察重點,不可單憑一則貼文就翻多翻空。\n"
                "- 標到「基本面背景」(連續成長/累計YoY/EPS YoY)的個股:當作這檔體質的背景脈絡寫進 reason(例:基本面撐腰、回檔較有支撐),"
                "不要當成今日進場理由,也不可編造任何沒列出的財務數字。\n"
                "- 宏觀背景只對「真的敏感」的持股連動(利率↑→金融/高估值成長股、油價→能源/航運、避險情緒→防禦vs風險),講不出機制的就別硬扯。\n"
            )
    def _mk_prompt(sub: list) -> str:
        block = _chunk_market_tech_block(data, sub, depth)
        if picks_mode:
            _tw_open = "今早 9:00 開盤後" if mkt_status.get("tw_will_open_today") else "下個台股交易日"
            _us_open = "今晚開盤後" if mkt_status.get("us_will_open_tonight") else "下個美股交易日"
            lead = ("你是財經顧問。以下是 AI 委員會今日精選標的(用戶並未持有,推薦研究用)。為每一支各生成一張 signal-card,"
                    "用「值得關注/若要進場可看 $X/先觀望」的推薦口吻,嚴禁「你的持股/加碼/減碼/續抱」等已持有措辭。"
                    f"signal-reason 仍要點出明確時機字眼(台股標的寫「{_tw_open}」、美股標的寫「{_us_open}」),"
                    "不可只寫「值得關注/保持觀望」這種沒有時間點的空話。\n")
        else:
            lead = "你是這位用戶的專屬財經顧問。為以下每一支股票各生成一張 signal-card,給出明確「下一步」操作建議。\n"
        return (
            lead +
            f"標的({len(sub)} 支,一支都不能少、不能合併):{', '.join(sub)}\n\n"
            f"【這幾支的真實市場 / 技術數據 — 進出場價位必須參考,嚴禁編造】\n{block}\n{deep_tech_note}{macro_note}{_council_prompt_block(council, sub)}\n"
            f"{rules}\n\n"
            f"只輸出這 {len(sub)} 支的 <div class=\"signal-card ...\"> 區塊;每張卡前面**獨立一行**寫 <!--CARD--> 當分隔。\n"
            f"不要輸出 signal-grid 外框、不要任何說明文字、不要 markdown 反引號。"
        )

    def _collect(raw: str, sub: list):
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
            match = next((cs for cs in sub if cs == tk or cs in tk or tk in cs), None)
            if match and match not in cards_by_sym and _card_passes_audit(card):
                cards_by_sym[match] = card

    for i in range(0, len(llm_stocks), CHUNK):
        chunk = llm_stocks[i:i + CHUNK]
        try:
            _collect(_llm_generate(_mk_prompt(chunk), prefer_strong), chunk)
        except Exception as e:
            # chunk(10支)全鏈失敗 → 先拆單支重試再認輸:大 prompt 是 Groq 免費層
            # 8000 TPM 放不下的(gpt-oss-120b),單支小 prompt 那張免費網就接得住;
            # 連 2 支單支也失敗才判定全鏈真的死了,剩餘走 deterministic(省時間)。
            print(f"  [signal-batch] chunk {i//CHUNK+1} LLM 全失敗({str(e)[:80]}),拆單支重試")
            misses = 0
            for s in chunk:
                if s in cards_by_sym:
                    continue
                if misses >= 2:
                    print(f"  [signal-batch] 連 {misses} 支單支重試也失敗,本 chunk 其餘改 deterministic")
                    break
                try:
                    _collect(_llm_generate(_mk_prompt([s]), prefer_strong), [s])
                    misses = 0
                except Exception as e2:
                    misses += 1
                    print(f"  [signal-batch] 單支 {s} 重試仍失敗({str(e2)[:60]})")
                time.sleep(1)
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


def _trim_holdings_for_email(data: dict, user_us_stocks, user_tw_stocks):
    """email 版持股裁切:總數超過 DIGEST_EMAIL_MAX_HOLDINGS 時,敘述只留單日變動最大的 N 支
    (避免信件過長被 Gmail 截斷;操作訊號卡另以 _full_holdings 覆蓋全部持股,不受此裁切影響)。
    低於上限時原樣回傳(保留 None/原引用語意)。三版報告(平日/週末/週一)共用。"""
    us0 = list(user_us_stocks or [])
    tw0 = list(user_tw_stocks or [])
    if len(us0) + len(tw0) <= DIGEST_EMAIL_MAX_HOLDINGS:
        return user_us_stocks, user_tw_stocks
    um = data.get("us_market", {})
    tm = data.get("tw_market", {})

    def _mv(sym, mkt):
        return abs((mkt.get(sym) or {}).get("change_pct", 0) or 0)

    ranked = sorted(
        [(s, "us") for s in us0] + [(s, "tw") for s in tw0],
        key=lambda x: _mv(x[0], um if x[1] == "us" else tm),
        reverse=True,
    )[:DIGEST_EMAIL_MAX_HOLDINGS]
    return [s for s, k in ranked if k == "us"], [s for s, k in ranked if k == "tw"]


def _gr_watchlist_section(data: dict, user_us_stocks: list, user_tw_stocks: list,
                          watchlist_us: list, watchlist_tw: list, has_holdings: bool,
                          picks_mode: bool) -> str:
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

    if picks_mode:
        watchlist_section = f"【AI 委員會今日精選標的(用戶未持有——這份報告的核心主角)】\n美股：{', '.join(watchlist_us)}"
    else:
        watchlist_section = f"【用戶持倉清單（這份報告的核心主角）】\n美股：{', '.join(watchlist_us)}"
    if watchlist_tw:
        watchlist_section += f"\n台股：{', '.join(watchlist_tw)}"
    if portfolio_lines:
        watchlist_section += ("\n\n【精選標的今日漲跌摘要】\n" if picks_mode else "\n\n【持倉今日漲跌摘要】\n") + "\n".join(portfolio_lines)
    return watchlist_section


def _gr_personalized_news(has_holdings: bool, all_holdings: list):
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
{"持倉不多，請也推薦 2-3 支相關股票的 stock-news-item，ticker 後面加上「推薦關注」字樣" if few_stocks_note else ""}
如果沒有任何持倉相關新聞，寫：<div class="stock-news-empty">今日無持倉相關重大新聞</div>）"""
    return few_stocks_note, personalized_news_instruction


def _gr_signal_stocks_tech(data: dict, user_us_stocks: list, user_tw_stocks: list,
                           market: str, _full_holdings: list):
    us_pref = list(dict.fromkeys(user_us_stocks or []))
    tw_pref = list(dict.fromkeys(user_tw_stocks or []))
    signal_stocks = list(dict.fromkeys(us_pref + tw_pref))
    if not signal_stocks:
        # 公版(無持股)預設關注股。tw 早報 = 台股權值 + 美股權值(早報的 digest_<date>.html 是
        # track-record 唯一解析來源,必須同時含台股美股,戰績才有台股又不丟美股);
        # us 晚報只給訂閱者看美股(_us 檔不進 track-record)。原本公版只有美股 → 台股戰績長期空白。
        TW_CORE = ["2330", "2454", "2317"]
        US_CORE = ["AAPL", "MSFT", "NVDA", "TSLA"]
        if market == "us":
            signal_stocks = US_CORE
        else:  # tw 早報 / both / 手動:台股 + 美股都出
            signal_stocks = TW_CORE + US_CORE

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
        # 公版關注股全出(台股權值+美股權值最多 7 檔),不切,確保 track-record 每天都收到台股與美股
        top_signal_stocks = sorted(signal_stocks, key=_abs_change, reverse=True)

    return top_signal_stocks


def _gr_prompt_blocks(depth: str, is_beginner: bool):
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

    # 深度控制(全體用戶可選,合規結構 COMPLIANCE_STRUCTURE.md:內容不得依付費分級):
    # simple=最精簡 / standard 與 deep=含中階區塊(原始數據儀表板、板塊輪動、二階思考)。
    # standard 一律完整,不因付費或持股數偷降級(2026-06-25 用戶反映:選 standard 卻收到 simple);
    # 想要精簡的用戶選「簡單看」。is_premium 禁止用於任何內容分級。
    show_advanced = depth != "simple"
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
    return (signal_instruction, rookie_section, mood_section,
            indicator_section, sector_section, second_order_section, depth_directive)


def _gr_time_discipline(market: str, mkt_status: dict, watchlist_tw: list, date: str):
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
- 違反例：「今天台積電漲 3%！」← 廢稿（盤前不可能知道）
- 正確例：「台積電昨日收 XXX 元」「今早 9:00 開盤後留意 XXX 元支撐」（台股只寫中文名、不帶代碼）

【⚠️ 今天的市場開盤狀態 — 絕對要遵守】
昨晚美股:{mkt_status['us_note'] or "美股有開盤,數據是新鮮的,可寫「昨晚美股 XXX」。"}
今天台股:{mkt_status['tw_note'] or "台股 9:00 將開盤,可寫「今早開盤」「今日早盤策略」。"}
今晚美股:{mkt_status['us_action_note']}

**雙市場動作對稱性:每張美股 signal-card 要給「今晚開盤後做什麼」(若今晚開盤),每張台股 signal-card 要給「今早 9:00 開盤後做什麼」(若今天開盤)。休市日只給「等下一個交易日 X」,不可寫「今晚/今早開盤」這類字眼。**
**規則：休市日的市場,不可在「30 秒看完今天重點」「大盤怎麼了」「持股本日動向」這幾個區塊把舊收盤當「今天/昨晚」寫,務必點明休市。**"""
        tldr_focus_note = ("- TLDR 30秒重點：**用戶有台股持股時，4 條至少 1 條必須是台股相關**（昨日收盤動向 / 今早 9:00 開盤怎麼操作 / 對某檔持股的明確建議），不可全部都美股。"
                           + (f"⚠️ 這位用戶持有台股：{', '.join(watchlist_tw)} — TLDR 一定要有他的台股動向。" if watchlist_tw else ""))
        tldr_li_hints = [f'<li>（最重要的事，一句話。{"用戶有台股 → 這條或下一條必須講台股動向（昨日收盤 / 今早開盤策略），台股口吻不可用「今天台股已 XX」" if watchlist_tw else "一句話"}）</li>',
                         f'<li>（第二重要的事{"，若上一條是美股，這條就要是台股" if watchlist_tw else ""}）</li>',
                         '<li>（第三重要的事）</li>',
                         '<li>（第四重要的事，如有）</li>']
    return time_discipline_block, tldr_focus_note, tldr_li_hints


def _gr_depth_sections(depth: str, has_holdings: bool, all_holdings: list,
                       personalized_news_instruction: str, mood_section: str,
                       indicator_section: str, sector_section: str, second_order_section: str):
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
- ‼️ impact-stock 必須與新聞主體**同一個具體次產業**，不可只因都算「半導體/科技」就亂掛：光通訊／CPO（如華星光、聯亞、聯鈞、光聖）≠ IC 設計（如聯發科 2454）≠ 晶圓代工（如台積電 2330）≠ 記憶體 ≠ 封測。例：「某光通訊廠獲利大增」只能標光通訊同業，**不可標聯發科或台積電**只因都是半導體
- 利多用 up、利空用 down，**不可整版全部 down**：同一則新聞常有受惠方（油價漲→能源股 up、航空股 down），有受惠方就要列
- 想不到具體個股時，就挑受影響產業的龍頭股：Fed 利率→JPM、GS；油價→XOM、CVX；AI/算力→NVDA、TSM；晶圓代工→TSM、2330；IC 設計→2454、NVDA、AMD；消費→AMZN、WMT
- 跟用戶持倉（{', '.join(all_holdings) if has_holdings else '主流科技股'}）相關的個股優先列，**但僅限該新聞與持股有真實傳導機制時**；不可只因用戶持有某股、就把無關新聞硬掛到它身上（例：用戶持聯發科，但某光通訊小廠財報新聞與聯發科無實質關聯，就不該標聯發科）——寧可改列新聞主體真正所屬次產業的個股，或這張卡不掛該持股
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
    return personalized_news_instruction, news5_section, market_tail_section


def _gr_build_prompt(date: str, all_holdings: list, has_holdings: bool,
                     time_discipline_block: str, depth_directive: str, tldr_focus_note: str,
                     few_stocks_note: str, watchlist_section: str, market_text: str,
                     us_news_text: str, tw_news_text: str, tldr_li_hints: list,
                     signal_instruction: str, personalized_news_instruction: str,
                     rookie_section: str, news5_section: str, market_tail_section: str) -> str:
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
- TLDR 必含一條「⚠️ 避坑」:點名今天最該避開的標的或最危險的行為(追高/接刀/重大數據前重倉),一句話講理由——{_tldr_avoid_edge_note()};持股全無風險時改寫大盤層級的最大風險提醒
- 所有分析都圍繞用戶的持倉，大盤新聞只在跟他持倉有關時才詳細寫
- 給建議要明確：說「建議買進 $XXX 以下」「續抱直到 $XXX」「跌破 $XXX 停損」，**禁止只寫「先觀望」「先別動」「保守為上」這類沒附條件的虛詞**。要說「觀望」就必須附「等什麼價位/事件」（例：「先觀望，等跌到 $580 再分批接」「先觀望，等 6/1 財報出來再決定」）。
- 口語化，像在 Line 傳訊息，不是寫報告

【寫作風格】
- 讀者是完全不懂股票的新手：用最白話的方式講，少用術語；非用不可的術語（例如停損、殖利率、財報）第一次出現要用括號簡單解釋
- 每一支股票都要讓人立刻知道「該買、該賣、還是抱著」，且**動作必須附條件**（價位、事件、時間窗），不可只丟動詞
- 數字要具體（不說「大幅上漲」，要說「漲了 3.2%」）
- 每個重點一兩句話說清楚，不廢話
- 繁體中文
- 內文提到個股：美股用「中文名（代號）」例如「輝達（NVDA）」；**台股只用中文名、不加代碼**，例如「台積電」「聯發科」（不可寫成「台積電（2330）」），更不可只寫代號
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
    return prompt


def generate_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                    email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                    market: str = "both", is_premium: bool = False, picks_mode: bool = False) -> str:
    # market: "both"=台美合併(預設/手動);"tw"=早 7:00 台股盤前為主、美股昨夜回顧;
    #         "us"=晚 20:00 美股盤前為主、台股今日收盤回顧。雙班次由 caller 傳對應市場 holdings。
    _full_holdings = list(dict.fromkeys((user_us_stocks or []) + (user_tw_stocks or [])))
    if email_safe:
        user_us_stocks, user_tw_stocks = _trim_holdings_for_email(data, user_us_stocks, user_tw_stocks)

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

    watchlist_section = _gr_watchlist_section(data, user_us_stocks, user_tw_stocks,
                                              watchlist_us, watchlist_tw, has_holdings, picks_mode)

    few_stocks_note, personalized_news_instruction = _gr_personalized_news(has_holdings, all_holdings)

    top_signal_stocks = _gr_signal_stocks_tech(data, user_us_stocks, user_tw_stocks,
                                               market, _full_holdings)

    (signal_instruction, rookie_section, mood_section, indicator_section,
     sector_section, second_order_section, depth_directive) = _gr_prompt_blocks(depth, is_beginner)

    time_discipline_block, tldr_focus_note, tldr_li_hints = _gr_time_discipline(
        market, mkt_status, watchlist_tw, date)

    personalized_news_instruction, news5_section, market_tail_section = _gr_depth_sections(
        depth, has_holdings, all_holdings, personalized_news_instruction,
        mood_section, indicator_section, sector_section, second_order_section)

    prompt = _gr_build_prompt(date, all_holdings, has_holdings,
                              time_discipline_block, depth_directive, tldr_focus_note,
                              few_stocks_note, watchlist_section, market_text,
                              us_news_text, tw_news_text, tldr_li_hints,
                              signal_instruction, personalized_news_instruction,
                              rookie_section, news5_section, market_tail_section)

    if picks_mode:
        prompt = _PICKS_PROMPT_NOTE + prompt
    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    cards = _render_signal_cards_batched(data, top_signal_stocks, mkt_status,
                                         full_limit=DIGEST_EMAIL_MAX_HOLDINGS if email_safe else None,
                                         prefer_strong=prefer_strong, depth=depth, picks_mode=picks_mode)
    cards += _portfolio_lens_block(data, all_holdings, depth)
    raw = _inject_signal_cards(raw, cards)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Weekend Recap(週六專用:本週回顧 + 下週預告)──────────────
def _weekend_monday_preamble(data: dict, user_us_stocks: list, user_tw_stocks: list, email_safe: bool):
    """週六/週一晨間報告共用前置(generate_weekend_report/generate_monday_report逐字重複抽出):
    holdings 解析、email 裁切、市場資料與新聞格式化(週末新聞量固定美股10篇/台股8篇)。"""
    _full_holdings = list(dict.fromkeys((user_us_stocks or []) + (user_tw_stocks or [])))
    if email_safe:
        user_us_stocks, user_tw_stocks = _trim_holdings_for_email(data, user_us_stocks, user_tw_stocks)
    market_text = _format_market_data(data, user_us_stocks, user_tw_stocks)
    us_news_text = _format_news(data.get("us_news", []), max_items=10)
    tw_news_text = _format_news(data.get("tw_news", []), max_items=8)
    date = data.get("date", "")
    holdings = (user_us_stocks or []) + (user_tw_stocks or [])
    has_holdings = bool(holdings)
    is_beginner = len(holdings) <= 4
    return (user_us_stocks, user_tw_stocks, _full_holdings, market_text, us_news_text,
            tw_news_text, date, holdings, has_holdings, is_beginner)


def generate_weekend_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                            email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                            market: str = "both", is_premium: bool = False, picks_mode: bool = False) -> str:
    # market 由雙班次 caller 傳入(週六台股早報走此函式);週末回顧本就是台股晨間語境,
    # holdings 已由 caller 依 market scope,這裡接受參數即可(行為不變)。
    """週六晨間日報:不講當日大盤(已收),改聚焦『本週回顧 + 下週重點』。"""
    (user_us_stocks, user_tw_stocks, _full_holdings, market_text, us_news_text,
     tw_news_text, date, holdings, has_holdings, is_beginner) = _weekend_monday_preamble(
        data, user_us_stocks, user_tw_stocks, email_safe)
    mkt_status = _market_status(date)

    # 操作訊號卡股票清單(用 _full_holdings 保證不受 email 裁切影響,每支持股都要有「下一步」)。
    us_market = data.get("us_market", {})
    tw_market = data.get("tw_market", {})
    all_market = {**us_market, **tw_market}
    def _abs_change(sym):
        d = all_market.get(sym, {})
        return abs(d.get("change_pct", 0))
    if _full_holdings:
        signal_stocks = sorted(_full_holdings, key=_abs_change, reverse=True)
    else:
        signal_stocks = ["2330", "2454", "2317", "AAPL", "MSFT", "NVDA", "TSLA"]

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

    if picks_mode:
        prompt = _PICKS_PROMPT_NOTE + prompt
    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    # 訊號卡另外分批生成填入,保證每支持股都有「下一步」——不依賴 LLM 自己寫的敘述性 .stock-card。
    # 2026-07-04 發現:本函式先前從未產生 signal-card,持股用戶必觸發 audit holdings_uncovered,
    # retry 同樣必敗,只能靠 deterministic fallback 頂住(見 _mark_card 呼叫處註解)。
    cards = _render_signal_cards_batched(data, signal_stocks, mkt_status,
                                         full_limit=DIGEST_EMAIL_MAX_HOLDINGS if email_safe else None,
                                         prefer_strong=prefer_strong, depth=depth, picks_mode=picks_mode)
    cards += _portfolio_lens_block(data, signal_stocks, depth)
    raw = _inject_signal_cards(raw, cards)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result


# ─── Monday Outlook(週一專用:上週五收盤 + 週末新聞 + 本週展望 + Gap 警示)──────────────
def generate_monday_report(data: dict, user_us_stocks: list = None, user_tw_stocks: list = None,
                           email_safe: bool = False, prefer_strong: bool = False, depth: str = "standard",
                           market: str = "both", is_premium: bool = False, picks_mode: bool = False) -> str:
    # market 由雙班次 caller 傳入(週一台股早報走此函式);週一展望本就是台股晨間語境,
    # holdings 已由 caller 依 market scope,這裡接受參數即可(行為不變)。
    """週一晨間日報:前兩天(週六、週日)沒開盤,所以基準是『上週五收盤』。
    重點:週末新聞累積 + 上週五收盤回顧 + 本週 catalysts + 週一開盤 gap 風險 +
    每檔持股仍給明確操作建議(買/抱/賣/觀望)。"""
    # email 版敘述只聚焦波動最大的 30 檔,但「操作訊號卡」仍覆蓋全部持股(全列在 _full_holdings)。
    (user_us_stocks, user_tw_stocks, _full_holdings, market_text, us_news_text,
     tw_news_text, date, holdings, has_holdings, is_beginner) = _weekend_monday_preamble(
        data, user_us_stocks, user_tw_stocks, email_safe)

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
        # 公版(無持股):週一台股早報同時出台股權值+美股權值,讓 track-record 收進台股戰績
        if market == "us":
            signal_stocks = ["AAPL", "MSFT", "NVDA", "TSLA"]
        else:
            signal_stocks = ["2330", "2454", "2317", "AAPL", "MSFT", "NVDA", "TSLA"]

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

    if picks_mode:
        prompt = _PICKS_PROMPT_NOTE + prompt
    raw = _llm_generate(prompt, prefer_strong)
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-zA-Z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    cards = _render_signal_cards_batched(data, signal_stocks, mkt_status,
                                         full_limit=DIGEST_EMAIL_MAX_HOLDINGS if email_safe else None,
                                         prefer_strong=prefer_strong, depth=depth, picks_mode=picks_mode)
    cards += _portfolio_lens_block(data, all_holdings, depth)
    raw = _inject_signal_cards(raw, cards)
    result = _postprocess_html(raw, data)
    if is_beginner:
        result += ROOKIE_GUIDE_HTML
    return result
