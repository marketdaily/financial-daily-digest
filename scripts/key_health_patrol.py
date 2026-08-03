"""key 健康巡檢(API/MCP 伺服器部首員,2026-08-03 部門成立日上線)。

盯「數據/服務類」API key 的有效性——LLM 廠商由 free_capacity_radar 每日體檢,
本巡檢不重複(系統不跟系統打架)。每日核心 7 檢+週日擴檢(耗額度的省著摸)。
判準:HTTP 200 且回應形狀對=活;401/403=key 死;429/額度=降級警告(不算死)。
失敗 exit 1 → runner 的 cron_run_and_alert 推 admin(自帶指紋去重)。
狀態落 state/key_health.json 供 admin/戰情面取用。

用法: .venv/bin/python scripts/key_health_patrol.py [--weekly] [--quiet]
"""
import datetime
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "state", "key_health.json")
E = os.environ.get


def _get(url, **kw):
    return requests.get(url, timeout=20, **kw)


def chk_finmind():
    """打真實 data 端點(1/600hr,可忽略):回 status 200+資料列=token 活。"""
    r = _get("https://api.finmindtrade.com/api/v4/data",
             params={"dataset": "TaiwanStockInfo", "data_id": "2330",
                     "token": E("FINMIND_TOKEN", "")})
    j = r.json()
    ok = r.status_code == 200 and j.get("status") == 200 and bool(j.get("data"))
    return ok, f"http={r.status_code} rows={len(j.get('data') or [])}"


def chk_fmp():
    """/api/v3 已是 legacy(2025-08 停),repo 實際用 /stable/——巡檢同步打 stable。"""
    r = _get(f"https://financialmodelingprep.com/stable/profile?symbol=AAPL&apikey={E('FMP_API_KEY', '')}")
    j = r.json() if r.status_code == 200 else None
    return r.status_code == 200 and isinstance(j, list) and len(j) > 0, f"http={r.status_code}"


def chk_newsapi():
    r = _get("https://newsapi.org/v2/top-headlines",
             params={"country": "us", "pageSize": 1, "apiKey": E("NEWS_API_KEY", "")})
    return r.status_code == 200 and r.json().get("status") == "ok", f"http={r.status_code}"


def chk_fred():
    r = _get("https://api.stlouisfed.org/fred/series/observations",
             params={"series_id": "DGS10", "api_key": E("FRED_API_KEY", ""),
                     "file_type": "json", "limit": 1, "sort_order": "desc"})
    return r.status_code == 200 and bool(r.json().get("observations")), f"http={r.status_code}"


def chk_brevo():
    r = _get("https://api.brevo.com/v3/account", headers={"api-key": E("BREVO_API_KEY", "")})
    return r.status_code == 200 and "email" in r.json(), f"http={r.status_code}"


def chk_beehiiv():
    pid = E("BEEHIIV_PUBLICATION_ID", "")
    r = _get(f"https://api.beehiiv.com/v2/publications/{pid}",
             headers={"Authorization": f"Bearer {E('BEEHIIV_API_KEY', '')}"})
    return r.status_code == 200, f"http={r.status_code}"


def chk_exa_budget():
    """不打 API(省 credits),只驗本月額度檔健康:用超 90% 才黃燈。"""
    try:
        with open(os.path.join(REPO, "intel", ".exa_budget.json"), encoding="utf-8") as f:
            b = json.load(f)
        used = b.get("used", 0)
        return used < 720, f"month={b.get('month')} used={used}/800"
    except FileNotFoundError:
        return True, "no budget file yet(尚未首跑)"


def chk_alphavantage():
    r = _get("https://www.alphavantage.co/query",
             params={"function": "GLOBAL_QUOTE", "symbol": "AAPL",
                     "apikey": E("ALPHAVANTAGE_API_KEY", "")})
    j = r.json()
    if "Note" in j or "Information" in j:
        return True, "額度用盡(25/day)非 key 死"
    return "Global Quote" in j, f"http={r.status_code}"


def chk_tavily():
    r = requests.post("https://api.tavily.com/search", timeout=20,
                      json={"api_key": E("TAVILY_API_KEY", ""), "query": "ping", "max_results": 1})
    return r.status_code == 200, f"http={r.status_code}"


def chk_context7():
    r = _get("https://context7.com/api/v2/libs/search?libraryName=requests&query=get",
             headers={"Authorization": f"Bearer {E('CONTEXT7_API_KEY', '')}"})
    return r.status_code == 200 and "results" in r.json(), f"http={r.status_code}"


def chk_mistral():
    r = _get("https://api.mistral.ai/v1/models",
             headers={"Authorization": f"Bearer {E('MISTRAL_API_KEY', '')}"})
    return r.status_code == 200, f"http={r.status_code}"


DAILY = [("finmind", chk_finmind), ("fmp", chk_fmp), ("newsapi", chk_newsapi),
         ("fred", chk_fred), ("brevo", chk_brevo), ("beehiiv", chk_beehiiv),
         ("exa_budget", chk_exa_budget)]
WEEKLY = [("alphavantage", chk_alphavantage), ("tavily", chk_tavily),
          ("context7", chk_context7), ("mistral_key", chk_mistral)]


def main():
    weekly = "--weekly" in sys.argv or datetime.date.today().weekday() == 6
    quiet = "--quiet" in sys.argv
    checks = DAILY + (WEEKLY if weekly else [])
    results, dead = {}, []
    for name, fn in checks:
        try:
            ok, note = fn()
        except Exception as e:
            ok, note = False, f"exc: {str(e)[:80]}"
        results[name] = {"ok": ok, "note": note}
        if not ok:
            dead.append(f"{name}({note})")
        if not quiet or not ok:
            print(f"  {'✅' if ok else '🔴'} {name}: {note}")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "weekly_ran": weekly, "results": results}, f, ensure_ascii=False, indent=1)
    if dead:
        print(f"🔴 key 巡檢失敗 {len(dead)}/{len(checks)}: {', '.join(dead)}")
        sys.exit(1)
    print(f"✅ key 巡檢全過 {len(checks)}/{len(checks)}{'(含週檢)' if weekly else ''}")


if __name__ == "__main__":
    main()
