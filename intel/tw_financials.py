"""台股財報結構化帳本(curriculum.md I 節「財報(完整財務數字結構化)尚未做」缺口,信息差引擎
台股第十二件)。

資料源:TWSE/TPEX 公開資訊觀測站(MOPS)openapi,免費/免key,一次性拉全市場「一般業」(_ci)
綜合損益表+資產負債表快照(同一模式已用於 mops_watch.py 的重訊/月營收兩端點)。

⚠️ 範圍限制(誠實記錄,非疏漏):僅涵蓋「一般業」(_ci)公司——金控/證券期貨/保險/異業四類
財報科目結構不同(另有 _fh/_bd/_ins/_mim 四組端點),本輪只做涵蓋率最高的一般業;watchlist
中若有金控股這類公司,會在 fetch 後找不到對應紀錄而被誠實跳過,不強行湊資料。

**已實測驗證、非假設的三個關鍵事實**(2026-07-09 建置時直接 curl 兩市場真實回應比對出來):
1. 這兩個 openapi 端點都只回傳「最新一期」全市場快照,`year=`/`season=` query 參數會被
   忽略——不能拿它們查歷史。跟 us_13f_ledger.py/pe_ratio_ledger.py 同款設計:沒有歷史查詢
   API 的資料源,只能靠自己每天 append 快照、累積出時間序列。
2. TWSE 與 TPEX 兩市場的財務科目中文欄位名(如「營業收入」「稅前淨利（淨損）」)完全相同,
   但資產負債表的「合計字眼」不同——TWSE 用「資產總額/負債總額/權益總額」,TPEX 用「資產
   總計/負債總計/權益總計」。
3. TPEX 自己的兩個端點(綜合損益表 vs 資產負債表)對「年度/季別」欄位命名也不一致——損益表
   端點用英文 `Year`/`Season`,資產負債表端點卻用中文「年度」「季別」。三處都已用多鍵
   fallback 涵蓋,見 `_normalize_*()`。

訊號定義(誠實框架:2026-07-07 curriculum I 節結論「免費層數字流信息源統計 edge 已到頂」——
這裡不重複造輪子宣稱已驗證方向性 edge,只誠實呈現財報數字變化幅度供人工判斷,若未來有需要
可用 signal_backtest_harness 事後驗真):
  🔴 本期由盈轉虧(淨利正轉負) 或 營收 YoY 年減 ≥20% 或 毛利率 QoQ 驟降 ≥5 個百分點
  🟡 營收 YoY 年減 ≥10% 或 QoQ 季減 ≥15% 或 毛利率 QoQ 下滑 ≥3 個百分點 或 負債比率(負債/
     資產)≥70%
  樣本 <2 期(尚無法算 QoQ)→誠實回 insufficient_data,不硬湊訊號

CLI:
  python3 -m intel.tw_financials run       # 抓最新一期全市場快照,過濾 watchlist 寫入帳本
  python3 -m intel.tw_financials signals   # 唯讀讀帳本算 classify(),供 patrol.py 併入巡邏
"""
import os
import sys
import json
import math
import fcntl
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEDGER = os.path.join(HERE, "tw_financials_ledger.jsonl")

INCOME_ENDPOINTS = [
    ("twse", "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"),
    ("tpex", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci"),
]
BALANCE_ENDPOINTS = [
    ("twse", "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci"),
    ("tpex", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci"),
]

REVENUE_YOY_RED = -20.0
REVENUE_YOY_YELLOW = -10.0
REVENUE_QOQ_YELLOW = -15.0
MARGIN_DELTA_RED = -5.0
MARGIN_DELTA_YELLOW = -3.0
DEBT_RATIO_YELLOW = 70.0


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _num(v):
    """空字串/None/壞格式一律回 None,不拋錯——MOPS 回應大量欄位視科目適用性留空字串。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _first(rec, keys):
    for k in keys:
        if k in rec and str(rec[k]).strip():
            return rec[k]
    return None


def _identity(rec):
    """回 (code, name, year, season) 或 None(缺任一識別欄位就整列跳過)。"""
    code = _first(rec, ["公司代號", "SecuritiesCompanyCode"])
    name = _first(rec, ["公司名稱", "CompanyName"])
    year = _first(rec, ["年度", "Year"])
    season = _first(rec, ["季別", "Season"])
    if not (code and year and season):
        return None
    return str(code).strip(), str(name or "").strip(), str(year).strip(), str(season).strip()


def _normalize_income(rec):
    ident = _identity(rec)
    if not ident:
        return None
    code, name, year, season = ident
    return {
        "code": code, "name": name, "year": year, "season": season,
        "revenue": _num(rec.get("營業收入")),
        "gross_profit": _num(rec.get("營業毛利（毛損）淨額")),
        "operating_income": _num(rec.get("營業利益（損失）")),
        "pretax_income": _num(rec.get("稅前淨利（淨損）")),
        "net_income": _num(rec.get("本期淨利（淨損）")),
        "eps": _num(rec.get("基本每股盈餘（元）")),
    }


def _normalize_balance(rec):
    ident = _identity(rec)
    if not ident:
        return None
    code, name, year, season = ident
    return {
        "code": code, "name": name, "year": year, "season": season,
        "current_assets": _num(rec.get("流動資產")),
        "total_assets": _num(_first(rec, ["資產總額", "資產總計"])),
        "current_liabilities": _num(rec.get("流動負債")),
        "total_liabilities": _num(_first(rec, ["負債總額", "負債總計"])),
        "total_equity": _num(_first(rec, ["權益總額", "權益總計"])),
    }


def _fetch_all(endpoints, normalize_fn):
    """依序試兩市場端點,任一失敗不可讓另一邊跟著沒資料(各自 try/except)。回
    {(code,year,season): normalized_dict},以先出現者為準(兩市場理論上不會有同代號)。"""
    out = {}
    for _market, url in endpoints:
        try:
            raw = _get(url)
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        for rec in raw:
            norm = normalize_fn(rec)
            if not norm:
                continue
            key = (norm["code"], norm["year"], norm["season"])
            out.setdefault(key, norm)
    return out


def fetch_snapshot(codes=None) -> dict:
    """回 {(code,year,season): merged_row},只保留 codes 集合內(未傳則不過濾,回全市場——
    呼叫端通常會傳 watchlist 過濾以免帳本無限膨脹)。income/balance 任一邊缺該
    (code,year,season) 就用 None 補值,不因單邊缺資料丟掉整列。"""
    income = _fetch_all(INCOME_ENDPOINTS, _normalize_income)
    balance = _fetch_all(BALANCE_ENDPOINTS, _normalize_balance)
    keys = set(income) | set(balance)
    if codes is not None:
        wanted = set(str(c) for c in codes)
        keys = {k for k in keys if k[0] in wanted}
    merged = {}
    for key in keys:
        inc = income.get(key, {})
        bal = balance.get(key, {})
        code, year, season = key
        name = inc.get("name") or bal.get("name") or ""
        merged[key] = {
            "code": code, "name": name, "year": year, "season": season,
            "revenue": inc.get("revenue"), "gross_profit": inc.get("gross_profit"),
            "operating_income": inc.get("operating_income"),
            "pretax_income": inc.get("pretax_income"), "net_income": inc.get("net_income"),
            "eps": inc.get("eps"),
            "current_assets": bal.get("current_assets"), "total_assets": bal.get("total_assets"),
            "current_liabilities": bal.get("current_liabilities"),
            "total_liabilities": bal.get("total_liabilities"), "total_equity": bal.get("total_equity"),
        }
    return merged


def _load_seen_keys():
    seen = set()
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    seen.add((row.get("code"), row.get("year"), row.get("season")))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seen


def record_snapshot(snapshot: dict) -> dict:
    """dedup by (code,year,season),check-then-append 用 fcntl.flock 包成臨界區——同
    us_13f_ledger.py/pe_ratio_ledger.py 已驗證過的 TOCTOU 防護模式。"""
    written, skipped = [], []
    os.makedirs(os.path.dirname(LEDGER) or ".", exist_ok=True)
    lock_path = LEDGER + ".lock"
    with open(lock_path, "a") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            seen = _load_seen_keys()
            with open(LEDGER, "a", encoding="utf-8") as f:
                for key in sorted(snapshot.keys()):
                    if key in seen:
                        skipped.append(list(key))
                        continue
                    row = dict(snapshot[key])
                    row["fetched_at"] = datetime.date.today().isoformat()
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    seen.add(key)
                    written.append(list(key))
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
    return {"written": written, "skipped": skipped}


def run(codes=None) -> dict:
    if codes is None:
        try:
            from intel.patrol import build_watchlist
            codes = sorted(build_watchlist())
        except Exception:
            codes = None
    snapshot = fetch_snapshot(codes)
    if not snapshot:
        return {"status": "fetch_failed", "written": [], "skipped": []}
    result = record_snapshot(snapshot)
    return {"status": "done", **result}


def _period_key(row):
    try:
        return (int(row.get("year", 0) or 0), int(row.get("season", 0) or 0))
    except (TypeError, ValueError):
        return (0, 0)


def _rows_for_code(code):
    rows = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if str(row.get("code")) == str(code):
                        rows.append(row)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    rows.sort(key=_period_key)
    return rows


def _pct_change(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _margin(row):
    rev, gp = row.get("revenue"), row.get("gross_profit")
    if rev is None or gp is None or rev <= 0:
        return None
    return gp / rev * 100.0


def _find_yoy(rows, latest):
    """同季去年同期——year-1、season 相同。找不到回 None(不硬湊)。"""
    ly, ls = _period_key(latest)
    for r in rows:
        y, s = _period_key(r)
        if y == ly - 1 and s == ls:
            return r
    return None


def _quarter_ord(row):
    """把 (year,season) 換成單調遞增的季度序數(year*4+season),用來判斷兩期是否真的
    相鄰一季。年度/季別非數字時回 None(誠實視為無法判斷,不可假設相鄰)。"""
    y, s = _period_key(row)
    if y == 0 and s == 0:
        return None
    return y * 4 + s


def classify(code: str) -> dict:
    """(VERIFIER 2026-07-09 補)`rows[-2]`/`rows[-1]` 只是帳本裡「最近記錄過的兩期」,
    不保證真的相鄰一季——若 cron 停擺跨過一整季、或某季全市場快照缺該公司,下一次比較會
    悄悄把跨兩季以上的變動當成單季 QoQ 呈報,誤導變動幅度的解讀。用 `_quarter_ord` 算實際
    季度間隔,只有真的相鄰(gap==1)才用「QoQ」框架呈現;間隔不明或 >1 季一律誠實回 None,
    不僅是門檻不觸發,而是連數字都不呈現(避免下游誤把跨季變動當單季讀)。"""
    rows = _rows_for_code(code)
    if len(rows) < 2:
        return {"code": code, "level": "insufficient_data", "periods_recorded": len(rows)}
    prev, latest = rows[-2], rows[-1]
    yoy_row = _find_yoy(rows, latest)
    prev_ord, latest_ord = _quarter_ord(prev), _quarter_ord(latest)
    is_adjacent_quarter = (prev_ord is not None and latest_ord is not None and latest_ord - prev_ord == 1)

    revenue_qoq = _pct_change(latest.get("revenue"), prev.get("revenue")) if is_adjacent_quarter else None
    revenue_yoy = _pct_change(latest.get("revenue"), yoy_row.get("revenue")) if yoy_row else None
    margin_latest, margin_prev = _margin(latest), _margin(prev)
    margin_delta = (margin_latest - margin_prev) if (
        is_adjacent_quarter and margin_latest is not None and margin_prev is not None) else None
    net_flip_to_loss = (
        latest.get("net_income") is not None and prev.get("net_income") is not None
        and latest["net_income"] < 0 <= prev["net_income"]
    )
    total_assets, total_liabilities = latest.get("total_assets"), latest.get("total_liabilities")
    debt_ratio = (total_liabilities / total_assets * 100.0) if (total_assets and total_liabilities is not None and total_assets > 0) else None

    reasons = []
    level = "plain"

    def _bump(new_level, reason):
        nonlocal level
        order = {"plain": 0, "yellow": 1, "red": 2}
        if order[new_level] > order[level]:
            level = new_level
        reasons.append(reason)

    if net_flip_to_loss:
        _bump("red", "本期由盈轉虧")
    if revenue_yoy is not None and revenue_yoy <= REVENUE_YOY_RED:
        _bump("red", f"營收YoY {revenue_yoy:+.1f}%")
    elif revenue_yoy is not None and revenue_yoy <= REVENUE_YOY_YELLOW:
        _bump("yellow", f"營收YoY {revenue_yoy:+.1f}%")
    if margin_delta is not None and margin_delta <= MARGIN_DELTA_RED:
        _bump("red", f"毛利率QoQ驟降{margin_delta:+.1f}個百分點")
    elif margin_delta is not None and margin_delta <= MARGIN_DELTA_YELLOW:
        _bump("yellow", f"毛利率QoQ下滑{margin_delta:+.1f}個百分點")
    if revenue_qoq is not None and revenue_qoq <= REVENUE_QOQ_YELLOW:
        _bump("yellow", f"營收QoQ {revenue_qoq:+.1f}%")
    if debt_ratio is not None and debt_ratio >= DEBT_RATIO_YELLOW:
        _bump("yellow", f"負債比率{debt_ratio:.1f}%")

    signal = "、".join(reasons) if reasons else "財報數字無顯著變化"
    return {
        "code": code, "name": latest.get("name", ""), "level": level, "signal": signal,
        "revenue_qoq_pct": None if revenue_qoq is None else round(revenue_qoq, 1),
        "revenue_yoy_pct": None if revenue_yoy is None else round(revenue_yoy, 1),
        "margin_delta_pp": None if margin_delta is None else round(margin_delta, 1),
        "debt_ratio_pct": None if debt_ratio is None else round(debt_ratio, 1),
        "net_flip_to_loss": net_flip_to_loss,
        "latest_period": f"{latest.get('year')}Q{latest.get('season')}",
        "prev_period": f"{prev.get('year')}Q{prev.get('season')}",
        "period_gap_quarters": (latest_ord - prev_ord) if (prev_ord is not None and latest_ord is not None) else None,
        "periods_recorded": len(rows),
    }


def active_signals(codes=None) -> dict:
    """唯讀,不觸網——供 patrol.py 每晚呼叫。只回傳 level in (yellow,red) 的 code,plain/
    insufficient_data 不進 by_code(同 tw_margin/tw_sbl/us_13f_ledger 慣例)。"""
    if codes is None:
        try:
            from intel.patrol import build_watchlist
            codes = sorted(build_watchlist())
        except Exception:
            codes = []
    out = {}
    for code in codes:
        try:
            result = classify(code)
        except Exception:
            # 單一 code 的帳本列髒掉不可讓整晚其餘 code 的訊號一起消失(同 us_13f_ledger 慣例)
            continue
        if result.get("level") in ("yellow", "red"):
            out[code] = result
    return out


def format_line(sig: dict) -> str:
    return f"{sig.get('name') or sig['code']}({sig['code']}):{sig['signal']}(較 {sig.get('prev_period')} 至 {sig.get('latest_period')})"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    elif cmd == "signals":
        print(json.dumps(active_signals(), ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
