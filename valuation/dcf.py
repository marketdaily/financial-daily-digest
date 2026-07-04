"""DCF 內在價值(看深入專屬,附在本益比估值帶之後)。
兩階段自由現金流投影 + CAPM/WACC 折現 + Gordon 永續終值 → 每股合理價「區間」。
紀律(遵 dcf-valuation skill):
- 只算現金流穩定、可預測的公司;FCF 為負 / 資料不足 / WACC≤g 一律回 None,不硬掰。
- 絕不報單一目標價,回 WACC×終值成長敏感度網格的最小/最大角 → 合理價區間。
- 缺料一律回 None,絕不拖垮日報。
台股:FinMind 現金流量表 + 資產負債表(股本/現金/負債)。
美股:FMP cash-flow / balance-sheet / profile(需 FMP_API_KEY)。
CLI: python3 valuation/dcf.py 2330 NVDA
"""
import os
import sys
import json
import urllib.request
import urllib.error
import datetime

FINMIND = "https://api.finmindtrade.com/api/v4/data"
FMP = "https://financialmodelingprep.com/stable"
FMP_KEY = os.environ.get("FMP_API_KEY", "").strip()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()

# CAPM 參數(市場級預設,個股 beta 有抓到才覆蓋)
TW_RF, US_RF, ERP = 0.015, 0.043, 0.055
TERM_G_GRID = [0.020, 0.025, 0.030]  # 終值成長掃描(務實中央區)
STAGE1_YEARS = 5
G1_CAP = 0.12       # 第一階段成長上限(高成長強制收斂,不外推景氣高點)


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _finmind(dataset, data_id, start_date):
    url = f"{FINMIND}?dataset={dataset}&data_id={data_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    return _http_json(url).get("data", [])


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_fcf(fcfs):
    """把年度 FCF 序列轉成 (base_fcf, g1),並擋掉循環股/不可預測的現金流。
    紀律:DCF 只算現金流穩定可預測的公司。近 5 年 FCF 一旦轉負或斷崖式暴跌(>55% YoY)
    即判定為循環/不穩定 → 回 None,交回本益比估值帶,不硬套 DCF。"""
    win = fcfs[-min(5, len(fcfs)):]
    if len(win) < 3:
        return None
    if any(v <= 0 for v in win):            # 近 5 年 FCF 轉負 = 不穩定,不算
        return None
    for a, b in zip(win, win[1:]):          # 任一年斷崖式暴跌 = 循環股,不算
        if b < a * 0.45:
            return None
    base_fcf = (win[-1] + win[-2]) / 2       # 平滑最近兩年,壓年度波動
    n = len(win) - 1
    g1 = (win[-1] / win[0]) ** (1 / n) - 1
    g1 = max(0.0, min(G1_CAP, g1))
    return base_fcf, g1


def _fair_value_grid(base_fcf, g1, wacc_mid, net_debt, shares):
    """對 WACC∈{mid-1%, mid, mid+1%} × 終值成長掃描,回每股合理價的 (low, high)。
    第一階段成長 g1 於 N 年線性收斂到該格的終值成長。"""
    prices = []
    for wacc in (wacc_mid - 0.0075, wacc_mid, wacc_mid + 0.0075):
        if wacc <= 0:
            continue
        for tg in TERM_G_GRID:
            if wacc <= tg + 0.005:      # WACC 必須 > g,留 0.5% 緩衝否則終值爆炸
                continue
            fcf, pv = base_fcf, 0.0
            for t in range(1, STAGE1_YEARS + 1):
                # g1 於 N 年線性收斂到終值成長 tg
                gt = g1 + (tg - g1) * (t - 1) / max(1, STAGE1_YEARS - 1)
                fcf *= (1 + gt)
                pv += fcf / (1 + wacc) ** t
            tv = fcf * (1 + tg) / (wacc - tg)          # Gordon 永續終值
            pv += tv / (1 + wacc) ** STAGE1_YEARS
            equity = pv - net_debt                      # net_debt<0 = 淨現金,加回
            if shares > 0:
                prices.append(equity / shares)
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return None
    prices.sort()
    return prices[0], prices[-1]


def _pack(low, high, currency):
    unit = "NT$" if currency == "TWD" else "$"
    fmt = (lambda x: f"{unit}{x:,.0f}") if high >= 50 else (lambda x: f"{unit}{x:,.1f}")
    return {
        "dcf_low": round(low, 2), "dcf_high": round(high, 2),
        "dcf": f"DCF 合理價區間 {fmt(low)}–{fmt(high)}/股(兩階段FCF折現)",
    }


# ── 台股 DCF ──
def tw_dcf(stock_id, today):
    start = (today - datetime.timedelta(days=1900)).isoformat()
    try:
        cf = _finmind("TaiwanStockCashFlowsStatement", stock_id, start)
        bs = _finmind("TaiwanStockBalanceSheet", stock_id, start)
    except Exception:
        return None
    if not cf or not bs:
        return None
    # 年度 FCF = 營業現金流 + 資本支出(PP&E 已是負的流出)
    op, capex = {}, {}
    for r in cf:
        d = str(r.get("date", ""))
        if not d.endswith("12-31"):
            continue
        yr, ty, val = d[:4], r.get("type"), _f(r.get("value"))
        if val is None:
            continue
        if ty in ("NetCashInflowFromOperatingActivities", "CashFlowsFromOperatingActivities"):
            op[yr] = val
        elif ty == "PropertyAndPlantAndEquipment":
            capex[yr] = val
    fcf_by_year = {y: op[y] + capex.get(y, 0.0) for y in op}
    years = sorted(fcf_by_year)
    if len(years) < 3:
        return None
    norm = _normalize_fcf([fcf_by_year[y] for y in years])
    if not norm:
        return None
    base_fcf, g1 = norm
    # 資產負債表:股本→股數(面額10)、現金、有息負債
    latest = max(r.get("date", "") for r in bs)
    field = {}
    for r in bs:
        if r.get("date") == latest:
            field[r.get("type")] = _f(r.get("value"))
    cap = field.get("CapitalStock")
    if not cap or cap <= 0:
        return None
    shares = cap / 10.0
    cash = field.get("CashAndCashEquivalents") or 0.0
    debt = sum(field.get(k) or 0.0 for k in (
        "ShortTermBorrowings", "ShortTermBillsPayable", "BondsPayable",
        "LongTermBorrowings", "LongTermLiabilitiesCurrentPortion"))
    net_debt = debt - cash
    wacc_mid = TW_RF + 1.0 * ERP              # beta 預設 1.0(FinMind 無 beta)
    grid = _fair_value_grid(base_fcf, g1, wacc_mid, net_debt, shares)
    if not grid:
        return None
    return _pack(grid[0], grid[1], "TWD")


# ── 美股 DCF ──
def us_dcf(symbol):
    if not FMP_KEY:
        return None
    try:
        cf = _http_json(f"{FMP}/cash-flow-statement?symbol={symbol}&period=annual&limit=6&apikey={FMP_KEY}")
        prof = _http_json(f"{FMP}/profile?symbol={symbol}&apikey={FMP_KEY}")
        bs = _http_json(f"{FMP}/balance-sheet-statement?symbol={symbol}&period=annual&limit=1&apikey={FMP_KEY}")
    except urllib.error.HTTPError as e:
        print(f"[dcf] {symbol} skipped: HTTP {e.code} (FMP quota/rate-limit suspect)")
        return None
    except Exception as e:
        print(f"[dcf] {symbol} skipped: {e}")
        return None
    if not (isinstance(cf, list) and cf and isinstance(prof, list) and prof and isinstance(bs, list) and bs):
        return None
    fcfs = []
    for r in sorted(cf, key=lambda r: r.get("date", "")):
        v = _f(r.get("freeCashFlow"))
        if v is None:
            v0, cx = _f(r.get("operatingCashFlow")), _f(r.get("capitalExpenditure"))
            v = (v0 + cx) if (v0 is not None and cx is not None) else None
        if v is not None:
            fcfs.append(v)
    norm = _normalize_fcf(fcfs)
    if not norm:
        return None
    base_fcf, g1 = norm
    p = prof[0]
    shares = _f(p.get("sharesOutstanding")) or _f(p.get("mktCap")) and (_f(p.get("mktCap")) / (_f(p.get("price")) or 1))
    if not shares or shares <= 0:
        return None
    beta = _f(p.get("beta")) or 1.0
    b0 = bs[0]
    net_debt = _f(b0.get("netDebt"))          # FMP 直接給,優先用
    if net_debt is None:
        debt = (_f(b0.get("totalDebt")) or 0.0)
        cash = (_f(b0.get("cashAndShortTermInvestments")) or _f(b0.get("cashAndCashEquivalents")) or 0.0)
        net_debt = debt - cash
    wacc_mid = US_RF + max(0.6, min(1.8, beta)) * ERP
    grid = _fair_value_grid(base_fcf, g1, wacc_mid, net_debt, shares)
    if not grid:
        return None
    return _pack(grid[0], grid[1], "USD")


def compute_dcf(sym, today):
    """單檔 DCF;台股/美股自動分流,任何失敗回 None。"""
    try:
        if str(sym).isdigit():
            return tw_dcf(sym, today)
        return us_dcf(sym)
    except Exception:
        return None


if __name__ == "__main__":
    today = datetime.date.today()
    for s in (sys.argv[1:] or ["2330", "NVDA"]):
        print(s, "→", json.dumps(compute_dcf(s, today), ensure_ascii=False))
