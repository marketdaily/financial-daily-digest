"""CF Workers AI neuron 預算閘門(免費層 10,000 neurons/UTC 日)。

2026-07-30 發現:07-26 Gemini 免費桶被 Google 收回後,日報退到 CF 當主力,自此**每天都超額**
(07-26~29 實測 22.3k/48.1k/61.2k/43.7k neurons,超額部分按 $0.011/1k 計費 ≈ $0.4/日)。
Delvin 的常令是「全部用免費、不要扣錢」,所以 CF 不能無上限用——本模組把免費額度變成硬閘門:
額度將盡即讓 `_call_cf_ai` raise,LLM 鏈自然往下掉到零成本的本機 GPU。

帳法:proxy 回傳每次呼叫的 in/out token,乘 CF 官方 neuron 單價累加進當日(UTC)帳本。
自家帳號的 CF AI 流量全部經這支 proxy,故本地帳本即權威值;要對帳可查 CF GraphQL
`aiInferenceAdaptiveGroups`(dimensions.date 是 UTC 日,與本帳本同基準)。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# CF 官方定價(neurons per 1M tokens),鍵=model id。未列入的模型用保守預設。
NEURON_PRICE = {
    "@cf/openai/gpt-oss-120b": (31818, 68182),
    "@cf/moonshotai/kimi-k2.6": (86364, 363636),
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": (26668, 204805),
    "@cf/meta/llama-3.1-8b-instruct-fast": (4119, 34868),
}
_DEFAULT_PRICE = (86364, 363636)  # 未知模型按最貴的算,寧可早關閘也不要偷偷超額

FREE_DAILY_NEURONS = 10_000

# 上限=免費額度(留 5% 餘裕),即「絕不產生帳單」。
# 這個值一度必須放寬到 60,000,因為當時每位用戶各自生成卡片,風暴日 76 次呼叫 ≈38,000
# neurons,硬卡免費線會讓 CF 被擋後無免費替代可用(本機 qwen2.5:14b 在真實 10 卡 prompt
# 上 600s 超時、OpenRouter 550b 要 144s/次)→ 大量訂閱者收備援版,與「絕對不要再看到閹割版」
# 衝突。2026-07-30 的零邊際成本改造(卡片池聯集預生成+盡力卡共用)把工作量降到
# ≈9,758 neurons/日(21 用戶/97 標的,即使 CF 扛 100% 的卡),取捨因此消失 → 收回到免費線。
# ⚠️ 這個上限的正當性依賴那條去重路徑還在:若 main._prewarm_card_pool 失效或卡片池
# 被繞過,成本會回到舊曲線並開始撞這個閘門(撞到就會推播,見 cf_neuron_watch_runner.sh)。
BUDGET_CEILING = int(os.environ.get("CF_NEURON_CEILING", 9_500))

LEDGER = Path(__file__).resolve().parent / "logs" / "cf_neuron_ledger.json"


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        with LEDGER.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def neurons_for(model: str, in_tokens: int, out_tokens: int) -> float:
    pin, pout = NEURON_PRICE.get(model, _DEFAULT_PRICE)
    return in_tokens / 1e6 * pin + out_tokens / 1e6 * pout


def spent_today() -> float:
    """當日(UTC)已消耗 neurons。帳本只留最近幾天,不會無限長大。"""
    return float(_load().get(_utc_date(), {}).get("neurons", 0.0))


def remaining() -> float:
    return max(0.0, BUDGET_CEILING - spent_today())


def budget_ok() -> bool:
    """還有預算可打 CF。False = 該讓路給零成本 provider(本機 GPU)。"""
    return spent_today() < BUDGET_CEILING


def record(model: str, in_tokens: int, out_tokens: int) -> float:
    """記一次呼叫,回傳本次 neurons。多程序(tw/us 兩班+council)可能並行 → 用 O_EXCL 鎖。"""
    neu = neurons_for(model, in_tokens, out_tokens)
    today = _utc_date()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    lock = LEDGER.with_suffix(".json.lock")
    fd = None
    for _ in range(50):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            import time
            time.sleep(0.1)
    try:
        data = _load()
        day = data.setdefault(today, {"neurons": 0.0, "calls": 0, "by_model": {}})
        day["neurons"] = round(float(day.get("neurons", 0.0)) + neu, 2)
        day["calls"] = int(day.get("calls", 0)) + 1
        bm = day.setdefault("by_model", {})
        bm[model] = round(float(bm.get(model, 0.0)) + neu, 2)
        # 只留最近 14 天
        for k in sorted(data)[:-14]:
            data.pop(k, None)
        tmp = LEDGER.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        tmp.replace(LEDGER)
    finally:
        if fd is not None:
            os.close(fd)
            try:
                os.unlink(str(lock))
            except OSError:
                pass
    return neu


def summary() -> str:
    day = _load().get(_utc_date(), {})
    return (f"CF neurons 今日(UTC {_utc_date()}):{day.get('neurons', 0):.0f}/{BUDGET_CEILING} "
            f"({day.get('calls', 0)} 次呼叫,免費層上限 {FREE_DAILY_NEURONS})")
