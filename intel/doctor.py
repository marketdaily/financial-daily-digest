"""信息差引擎渠道體檢(intel/doctor.py,2026-08-04)。

**要解的問題**:24 個連接器每個都「自成一體 + 任何失敗靜默降級」(見各 connector 檔頭紀律)。
這在管線層是對的——單一訊源掛掉不該拖垮日報。但它產生一個致命的觀測性缺口:
**上游改版導致某訊源永久產出零訊號,在 latest.json 裡跟「本週真的沒事件」長得一模一樣。**
例:tw_fsc 的 RSS serno 若被金管會換掉,fsc_penalty 從此永遠不出現,沒有任何人會發現。

**做法(抄 Agent-Reach 的能力層架構,2026-08-04 評估該 repo 時學到)**:
  1. 渠道化——34 個連接器共用 19 個上游,以「渠道」為體檢單位而非檔案。
  2. 真實探測——實際打上游 + **驗回傳形狀**,不是只看 HTTP 200(200 回一頁登入牆也是 200)。
  3. 分辨三態——OK / 需設定(缺金鑰,附申請處方) / 壞掉(上游改版或封鎖,附診斷)。
     「需設定」與「壞掉」混為一談是最常見的體檢廢話來源:前者要人去申請,後者要人去修碼。
  4. 有序候選——同一渠道有備援路徑的(如 Reddit OAuth ▸ RSS)回報**當前實際走哪條**。

**刻意不做**:不改任何既有 connector(scope-lock);本檔純唯讀探測,不寫 latest.json、
不碰帳本、不觸發任何 connector 的副作用。

用法:
    python3 -m intel.doctor              # 人看的報告
    python3 -m intel.doctor --json       # 機器讀
    python3 -m intel.doctor --strict     # 有渠道壞掉即 exit 1(給 cron 用)
    python3 -m intel.doctor --only sec_edgar,finmind
"""
import os
import ssl
import json
import time
import gzip
import argparse
import datetime
import subprocess
import urllib.parse
import urllib.request
import concurrent.futures

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# ⭐ 探測必須沿用 production 的 transport 與 UA,不是只沿用 URL。
# 2026-08-04 首版就是沒做到:doctor 一律用自訂 UA + urllib,把 tpex/PTT/集保/金管會
# 四個【健康】渠道誤報成壞掉(它們在 production 分別走 Mozilla UA 或 shell curl)。
# 誤報率 4/5 的體檢比沒有體檢更糟——它會養出「反正都紅的」的警報疲勞。
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SEC_UA = "marketdaily-intel-doctor/1.0 (delvin.12345678@gmail.com)"  # SEC 要求可辨識聯絡人
UA = BROWSER_UA
TIMEOUT = 15
RETRIES = 2  # 網路層(status 0)才重試。tpex.org.tw 實測有節點憑證鏈壞掉
             # (SSL: Missing Subject Key Identifier),3 次跑會中 1 次,一次重試不夠。

OK, CONFIG, BROKEN = "ok", "config", "broken"


def _env():
    """讀 .env,不依賴 python-dotenv(doctor 必須在任何環境都能跑)。"""
    out = dict(os.environ)
    try:
        with open(os.path.join(REPO, ".env"), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass
    return out


ENV = _env()


def fetch(url, data=None, headers=None, timeout=TIMEOUT, ua=UA, retries=RETRIES):
    """回傳 (status_code, body_text)。網路層例外一律轉成 (0, 錯誤字串),絕不拋出。
    status 0(連不上/TLS 抖動)才重試;HTTP 錯誤碼是上游的明確回答,重試沒有意義。"""
    for attempt in range(retries + 1):
        code, body = _fetch_once(url, data, headers, timeout, ua)
        if code != 0:
            return code, body
        if attempt < retries:
            time.sleep(1.5)
    return code, body


def curl_fetch(url, timeout=25, ua=UA, retries=RETRIES, http11=False):
    """給 production 本身就是 shell 出去打 curl 的渠道(tw_fsc / tw_holders / FRED)。

    ua=None 表示【刻意不指定 UA】——FRED 的 WAF 會擋自訂 UA,production 的
    macro_rates_ledger._get_text 就是靠 curl 預設 UA + --http1.1 才過得去
    (見 state/lessons/fred_stlouisfed_blocked.md)。探測若自作聰明加 UA 會誤報成壞掉。
    """
    err = "unknown"
    for attempt in range(retries + 1):
        try:
            cmd = ["curl", "-sL", "--max-time", str(timeout)]
            if http11:
                cmd.append("--http1.1")
            if ua:
                cmd += ["-A", ua]
            cmd.append(url)
            out = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
            if out.returncode == 0 and out.stdout:
                return 200, out.stdout.decode("utf-8", errors="replace")
            err = f"curl rc={out.returncode}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(1.5)
    return 0, err


def _fetch_once(url, data, headers, timeout, ua):
    hdrs = {"User-Agent": ua, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, data=data, headers=hdrs)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            return r.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def days_ago(n):
    """探測一律用相對日期。寫死日期的測試會在翻頁那天假死(harness_golden_live_data_drift)。"""
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def need(*keys):
    """缺金鑰→回傳缺的清單。"""
    return [k for k in keys if not (ENV.get(k) or "").strip()]


# ── 各渠道探測 ────────────────────────────────────────────────────────────
# 每個探測回傳 (status, detail)。判準一律「形狀」而非狀態碼:200 回一頁登入牆/
# 空殼 JSON 也是 200,只認 HTTP 碼等於沒體檢(Agent-Reach 的核心教訓)。

def p_twse():
    code, body = fetch("https://openapi.twse.com.tw/v1/opendata/t187ap05_L")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "回傳非 JSON(疑上游改版或擋爬)"
    if not isinstance(d, list) or not d:
        return BROKEN, "月營收端點回傳空陣列(此端點永不該為空)"
    if not any("公司代號" in r for r in d[:3]):
        return BROKEN, f"欄位結構已變:{list(d[0])[:6]}"
    return OK, f"月營收 {len(d)} 筆,欄位正常"


def p_tpex():
    code, body = fetch("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "回傳非 JSON(疑上游改版)"
    if not isinstance(d, list) or not d:
        return BROKEN, "櫃買日收盤回傳空陣列"
    return OK, f"櫃買日收盤 {len(d)} 筆"


def p_finmind():
    miss = need("FINMIND_TOKEN")
    if miss:
        return CONFIG, f"缺 {','.join(miss)} → finmindtrade.com 註冊免費帳號取 token 填進 .env"
    q = urllib.parse.urlencode({"dataset": "TaiwanStockPrice", "data_id": "2330",
                                "start_date": days_ago(10), "token": ENV["FINMIND_TOKEN"]})
    code, body = fetch(f"https://api.finmindtrade.com/api/v4/data?{q}")
    if code == 402 or code == 429:
        return BROKEN, f"HTTP {code} — 免費層額度用盡或方案不含此 dataset"
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "回傳非 JSON"
    if d.get("msg") != "success":
        return BROKEN, f"msg={d.get('msg')!r}(token 可能失效)"
    if not d.get("data"):
        return BROKEN, "2330 近 10 日價格為空(不合理,疑 dataset 更名)"
    return OK, f"2330 近 10 日 {len(d['data'])} 筆"


def p_yahoo():
    code, body = fetch("https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=5d&interval=1d")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    try:
        r = json.loads(body)["chart"]["result"][0]
    except Exception:
        return BROKEN, "chart.result 結構已變或被擋"
    if not r.get("timestamp"):
        return BROKEN, "無 timestamp(回傳空殼)"
    return OK, f"2330.TW {len(r['timestamp'])} 根日線"


def p_sec_edgar():
    code, body = fetch("https://www.sec.gov/files/company_tickers.json", ua=SEC_UA)
    if code != 200:
        return BROKEN, f"company_tickers HTTP {code}(SEC 需帶可辨識 UA,否則 403)"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "company_tickers 非 JSON"
    if not isinstance(d, dict) or len(d) < 1000:
        return BROKEN, f"company_tickers 筆數異常({len(d) if hasattr(d,'__len__') else '?'})"
    code2, body2 = fetch("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                         "&CIK=0000320193&type=4&dateb=&owner=include&count=5&output=atom",
                         ua=SEC_UA)
    if code2 != 200:
        return BROKEN, f"browse-edgar atom HTTP {code2}(ticker 對照可用但 filing 清單掛了)"
    if "<entry" not in body2:
        return BROKEN, "browse-edgar atom 無 <entry>(AAPL Form 4 不可能為空,疑改版)"
    return OK, f"ticker 對照 {len(d)} 筆 + AAPL Form 4 atom 正常"


def p_sec_litigation():
    code, body = fetch("https://www.sec.gov/rss/litigation/admin.xml", ua=SEC_UA)
    if code != 200:
        return BROKEN, f"HTTP {code}"
    if "<item" not in body:
        return BROKEN, "RSS 無 <item>(疑改版或改路徑)"
    return OK, f"行政程序 RSS {body.count('<item')} 則"


def p_cnyes():
    code, body = fetch("https://news.cnyes.com/api/v3/news/category/tw_forecast?limit=5")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    try:
        items = json.loads(body)["items"]["data"]
    except Exception:
        return BROKEN, "items.data 結構已變"
    if not items:
        return BROKEN, "tw_forecast 分類為空(不合理)"
    return OK, f"tw_forecast {len(items)} 則"


def p_cnyes_ess():
    q = urllib.parse.quote("台積電")
    code, body = fetch(f"https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={q}&limit=5")
    if code != 200:
        return BROKEN, f"HTTP {code}"
    try:
        d = json.loads(body)["data"]["items"]
    except Exception:
        return BROKEN, "data.items 結構已變"
    return (OK, f"關鍵字檢索 {len(d)} 則") if d else (BROKEN, "台積電關鍵字零結果(不合理)")


def p_fmp():
    miss = need("FMP_API_KEY")
    if miss:
        return CONFIG, "缺 FMP_API_KEY"
    code, body = fetch("https://financialmodelingprep.com/stable/grades-consensus"
                       f"?symbol=AAPL&apikey={ENV['FMP_API_KEY']}")
    if code in (401, 402, 403, 429) or "upgrade your plan" in body.lower() or "limit reach" in body.lower():
        return CONFIG, (f"HTTP {code} — 免費層額度/方案限制,非故障。us_analyst 已由 "
                        "edgar_fundamentals(SEC companyfacts)補位;要恢復需升級 FMP 方案")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    return OK, "評等共識端點可用"


def p_newsapi():
    miss = need("NEWS_API_KEY")
    if miss:
        return CONFIG, "缺 NEWS_API_KEY → newsapi.org 免費層註冊"
    code, body = fetch("https://newsapi.org/v2/everything?q=apple&pageSize=1&"
                       f"apiKey={ENV['NEWS_API_KEY']}")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:150]}"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "非 JSON"
    if d.get("status") != "ok":
        return BROKEN, f"status={d.get('status')} {d.get('message','')[:100]}"
    return OK, f"totalResults={d.get('totalResults')}"


def p_exa():
    miss = need("EXA_API_KEY")
    if miss:
        return CONFIG, "缺 EXA_API_KEY"
    payload = json.dumps({"query": "semiconductor supply chain", "numResults": 1}).encode()
    code, body = fetch("https://api.exa.ai/search", data=payload,
                       headers={"content-type": "application/json",
                                "x-api-key": ENV["EXA_API_KEY"]})
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:150]}"
    try:
        d = json.loads(body)
    except Exception:
        return BROKEN, "非 JSON"
    return (OK, f"{len(d.get('results', []))} 筆") if d.get("results") is not None else (BROKEN, "無 results 欄位")


def p_gemini():
    key = ENV.get("GEMINI_API_KEY") or ENV.get("GEMINI_API_KEY_2")
    if not key:
        return CONFIG, "缺 GEMINI_API_KEY"
    code, body = fetch(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:150]}"
    try:
        n = len(json.loads(body).get("models", []))
    except Exception:
        return BROKEN, "非 JSON"
    return (OK, f"{n} 個模型可用") if n else (BROKEN, "models 為空")


def p_fred():
    code, body = curl_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU",
                            ua=None, http11=True, timeout=20)
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    lines = [x for x in body.splitlines() if x.strip()]
    if len(lines) < 2 or "," not in lines[0]:
        return BROKEN, "非 CSV 或只有表頭"
    return OK, f"DFEDTARU {len(lines)-1} 列"


def p_goldprice():
    code, body = fetch("https://api.goldprice.dev/v1/prices")
    if code != 200:
        return BROKEN, f"HTTP {code}"
    try:
        json.loads(body)
    except Exception:
        return BROKEN, "非 JSON"
    return OK, "金價 API 正常"


def p_multpl():
    code, body = fetch("https://www.multpl.com/s-p-500-pe-ratio")
    if code != 200:
        return BROKEN, f"HTTP {code}"
    if "current" not in body.lower():
        return BROKEN, "頁面無 current 字樣(疑改版)"
    return OK, "S&P500 PE 頁面正常"


def p_fsc():
    code, body = curl_fetch("https://www.fsc.gov.tw/RSS/Messages?serno=201202290003&language=chinese")
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}(serno 可能已被金管會更換)"
    if "<item" not in body:
        return BROKEN, "RSS 無 <item>(serno 失效或改版)"
    return OK, f"裁罰 RSS {body.count('<item')} 則"


def p_tdcc():
    code, body = curl_fetch("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", timeout=15)
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    if "SYNCHRONIZER_TOKEN" not in body:
        return BROKEN, "頁面無 SYNCHRONIZER_TOKEN 欄位(表單改版,tw_holders 會抓不到)"
    return OK, "集保查詢頁與 CSRF token 欄位正常"


def p_mops_conf():
    code, body = fetch("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1",
                       data=urllib.parse.urlencode({
                           "encodeURIComponent": "1", "step": "1", "firstin": "1",
                           "off": "1", "TYPEK": "sii",
                           "year": str(datetime.date.today().year - 1911),
                           "month": f"{datetime.date.today().month:02d}"}).encode(),
                       headers={"content-type": "application/x-www-form-urlencoded"})
    if code != 200:
        return BROKEN, f"HTTP {code}"
    if "<table" not in body.lower():
        return BROKEN, "回應無表格(法說會查詢改版)"
    return OK, "法說會查詢端點正常"


def p_ptt():
    code, body = fetch("https://www.ptt.cc/bbs/Stock/index.html",
                       headers={"Cookie": "over18=1"})
    if code != 200:
        return BROKEN, f"HTTP {code} — {body[:120]}"
    if "r-ent" not in body:
        return BROKEN, "版面無 r-ent class(PTT 改版)"
    return OK, f"Stock 版 {body.count('r-ent')} 篇"


def p_reddit():
    miss = need("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")
    if miss:
        return CONFIG, ("缺 " + ",".join(miss) + " → reddit.com/prefs/apps 建 type=script 的 app,"
                        "填進 .env 即自動走 OAuth 主路(100 QPM);匿名 .json 已被封,無零設定路徑")
    code, body = fetch("https://oauth.reddit.com/r/stocks/new?limit=1&raw_json=1")
    return (OK, "OAuth 可用") if code == 200 else (BROKEN, f"OAuth HTTP {code}")


def p_threads():
    miss = need("THREADS_ACCESS_TOKEN")
    if miss:
        return CONFIG, "缺 THREADS_ACCESS_TOKEN(social_buzz 的 Threads 源設計為金鑰閘門,空手即靜默略過)"
    code, _ = fetch("https://graph.threads.net/v1.0/keyword_search?q=stock&search_type=RECENT&"
                    f"access_token={ENV['THREADS_ACCESS_TOKEN']}")
    return (OK, "keyword_search 可用") if code == 200 else (BROKEN, f"HTTP {code}")


def p_congress():
    code, body = fetch("https://disclosures-clerk.house.gov/public_disc/financial-pdfs/"
                       f"{datetime.date.today().year}FD.ZIP", timeout=20)
    if code == 200:
        return OK, "眾院揭露 ZIP 可取得"
    code2, _ = fetch("https://disclosures-clerk.house.gov/")
    if code2 == 200:
        return BROKEN, f"年度 ZIP HTTP {code}(站台活著但今年檔案路徑不對,可能年初尚未產生)"
    return BROKEN, f"眾院揭露站不可達(ZIP {code} / 首頁 {code2})"


# ── 渠道註冊表 ────────────────────────────────────────────────────────────
# feeds = 該渠道供給 latest.json 的 source 字串(query.py SOURCE_MEANING 的 key)。
# 這是本體檢真正的價值:某個 feed 在 latest.json 缺席時,能立刻回答
# 「是真的沒事件,還是這條渠道死了」。
CHANNELS = [
    ("twse_openapi", "TWSE 開放 API", p_twse,
     ["mops_news", "revenue", "twse_notice", "twse_notetrans", "twse_punish"],
     ["mops_watch", "tw_surveillance", "tw_leadflow", "tw_financials"]),
    ("tpex_openapi", "櫃買中心開放 API", p_tpex, [], ["tw_financials", "tw_leadflow"]),
    ("finmind", "FinMind 台股籌碼", p_finmind, ["institutional", "margin", "sbl"],
     ["tw_institutional", "tw_margin", "tw_sbl", "ca_settlement_guard"]),
    ("yahoo_chart", "Yahoo 行情", p_yahoo, [], ["bounce_shadow", "market_forecast", "tw_leadflow"]),
    ("tdcc_holders", "集保股權分散", p_tdcc, ["holders"], ["tw_holders"]),
    ("sec_edgar", "SEC EDGAR", p_sec_edgar, ["us_insider", "us_8k", "us_13f"],
     ["us_insider", "us_8k_events", "us_13f_ledger"]),
    ("sec_litigation", "SEC 行政程序 RSS", p_sec_litigation, ["us_sec_admin"], ["us_sec_regulatory"]),
    ("cnyes_news", "鉅亨新聞分類 API", p_cnyes, ["news_tw", "tw_analyst"],
     ["news_signals", "tw_analyst_ratings"]),
    ("cnyes_ess", "鉅亨關鍵字檢索", p_cnyes_ess, [], ["tw_broker_calls"]),
    ("fmp", "FMP 分析師評等", p_fmp, ["us_analyst"], ["us_analyst"]),
    ("newsapi", "NewsAPI 美股新聞", p_newsapi, ["news_us"], ["news_signals"]),
    ("exa", "Exa 語意搜尋", p_exa, [], ["exa_search"]),
    ("gemini", "Gemini vision(法說會圖表)", p_gemini, [], ["conf_charts"]),
    ("fred", "FRED 總經利率", p_fred, [], ["macro_rates_ledger"]),
    ("goldprice", "金價 API", p_goldprice, [], ["gold_macro"]),
    ("multpl", "S&P500 本益比", p_multpl, [], ["pe_ratio_ledger"]),
    ("fsc_rss", "金管會裁罰 RSS", p_fsc, ["fsc_penalty"], ["tw_fsc"]),
    ("mops_conf", "MOPS 法說會查詢", p_mops_conf, ["investor_conf"],
     ["tw_investor_conf", "tw_investor_materials"]),
    ("ptt", "PTT 股板", p_ptt, [], ["social_buzz"]),
    ("reddit", "Reddit 社群聲量", p_reddit, [], ["reddit_buzz"]),
    ("threads", "Threads 關鍵字", p_threads, [], ["social_buzz"]),
    ("congress", "美國會議員揭露", p_congress, ["us_congress"], ["us_congress_trades"]),
]

ICON = {OK: "✅", CONFIG: "[!]", BROKEN: "[X]"}
WORD = {OK: "可用", CONFIG: "需設定", BROKEN: "壞掉"}


def run_one(entry):
    name, label, probe, feeds, mods = entry
    t0 = time.time()
    try:
        status, detail = probe()
    except Exception as e:
        # fail-open:單一探測炸掉不可以讓整份體檢失效(decision_queue 教訓 F3)
        status, detail = BROKEN, f"探測器自身例外 {type(e).__name__}: {e}"
    return {"name": name, "label": label, "status": status, "detail": detail,
            "feeds": feeds, "modules": mods, "elapsed": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="有渠道壞掉即 exit 1")
    ap.add_argument("--only", default="", help="逗號分隔的渠道名")
    a = ap.parse_args()

    picked = [c for c in CHANNELS if not a.only or c[0] in a.only.split(",")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(run_one, picked))
    results.sort(key=lambda r: ({OK: 2, CONFIG: 1, BROKEN: 0}[r["status"]], r["name"]))

    broken = [r for r in results if r["status"] == BROKEN]
    cfg = [r for r in results if r["status"] == CONFIG]
    okn = len(results) - len(broken) - len(cfg)

    if a.json:
        print(json.dumps({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                          "ok": okn, "config": len(cfg), "broken": len(broken),
                          "channels": results}, ensure_ascii=False, indent=2))
    else:
        print("信息差引擎渠道體檢")
        print("=" * 60)
        print("圖例:✅ 可用   [!] 需設定(缺金鑰,要人去申請)   [X] 壞掉(上游變了,要人去修)\n")
        for r in results:
            print(f"{ICON[r['status']]} {r['name']:<16} {r['label']}")
            print(f"    {r['detail']}  ({r['elapsed']}s)")
            if r["feeds"]:
                print(f"    供給訊源: {', '.join(r['feeds'])}")
        print("\n" + "=" * 60)
        print(f"狀態:{okn}/{len(results)} 渠道可用、{len(cfg)} 需設定、{len(broken)} 壞掉")
        dead_feeds = sorted({f for r in broken for f in r["feeds"]})
        if dead_feeds:
            print(f"⚠️ 下列訊源在 latest.json 缺席時【不是沒事件,是渠道死了】: {', '.join(dead_feeds)}")

    return 1 if (a.strict and broken) else 0


if __name__ == "__main__":
    raise SystemExit(main())
