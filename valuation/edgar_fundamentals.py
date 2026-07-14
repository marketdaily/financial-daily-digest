"""美股基本面(免費 SEC EDGAR companyfacts)——FMP 付費 gate(HTTP 402)的免費替代。

SEC EDGAR 完全免費、無需 key(與 intel/us_insider.py 同源)。
用途:餵 valuation/dcf.py::us_dcf 所需的年度自由現金流、股數、淨負債。

資料鏈:ticker → CIK(company_tickers.json)→ companyfacts XBRL → 年度 OCF/capex/現金/負債/股數。
紀律:缺料 / 欄位對不上一律回 None,絕不硬掰(us_dcf 收到 None 就不出 DCF 段,與現況一致)。

CLI: python3 valuation/edgar_fundamentals.py AAPL MSFT NVDA
"""
import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SEC = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"
# SEC 要求帶可辨識聯絡資訊的 User-Agent,否則 403(與 us_insider.py 同一組)。
UA = "MarketDaily research contact@marketdaily.ai"
CIK_CACHE = os.path.join(HERE, ".us_cik_map.json")
CIK_MAP_TTL_DAYS = 30
# 資產負債表 instant 值(現金/投資/負債/股數)超過最新 as-of 日這麼多個月 = 公司已停用該
# XBRL tag、值凍結在最後一次申報,不可當現況採用(否則 HEI 用 2015 股數→DCF 5x 偏高、
# AMGN 用 2017 短投→淨負債少算 $38B)。錨定最新資產負債表日,舊於此窗的腿一律視為缺料。
STALE_MONTHS = 15

# 年度現金流量的 XBRL 概念(us-gaap)。營業現金流跨年代有兩種寫法,都吃。
OCF_CONCEPTS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]
# 資產負債表(instant)概念,依序 fallback。
CASH_CONCEPTS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
STI_CONCEPTS = [  # 短期投資/可交易證券(cash-rich 公司的淨現金主體,如 AAPL)
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesCurrent",
]
LT_DEBT_NONCUR_CONCEPTS = ["LongTermDebtNoncurrent", "LongTermDebt"]
LT_DEBT_CUR_CONCEPTS = ["LongTermDebtCurrent", "DebtCurrent"]
SHORT_BORROW_CONCEPTS = ["ShortTermBorrowings", "ShorttermBorrowings"]
# 單一「總負債」概念:含金融子公司/資本租賃的公司(GM/HD/ORCL)常把全部債務塞這裡,
# 標準分項(Noncurrent/Current)會嚴重低估 → 取分項合計與此的較大者,net_debt 才不失真。
TOTAL_DEBT_CONCEPTS = [
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
    "DebtLongtermAndShorttermCombinedAmount",
    "LongTermDebtAndCapitalLeaseObligations",
]


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


# ── ticker → CIK ──
def _refresh_cik_map(path=CIK_CACHE):
    raw = json.loads(_fetch(f"{SEC}/files/company_tickers.json", timeout=30))
    out = {}
    for row in raw.values():
        t = str(row.get("ticker", "")).upper()
        c = row.get("cik_str")
        if t and c is not None:
            out[t] = str(c).zfill(10)
    if out:
        try:
            with open(path, "w") as f:
                json.dump(out, f)
        except OSError:
            pass
    return out


def _load_cik_map(path=CIK_CACHE):
    try:
        age = (time.time() - os.path.getmtime(path)) / 86400.0
        if age <= CIK_MAP_TTL_DAYS:
            with open(path) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    return _refresh_cik_map(path)


def symbol_to_cik(symbol, cik_map=None):
    cik_map = cik_map if cik_map is not None else _load_cik_map()
    s = str(symbol).upper()
    cik = cik_map.get(s)
    if cik:
        return cik
    # SEC 用連字號(BRK-B/BF-B),用戶持股常寫成點(BRK.B);互轉重試。
    for alt in (s.replace(".", "-"), s.replace("-", ".")):
        if alt != s and alt in cik_map:
            return cik_map[alt]
    return None


# ── companyfacts 解析 ──
def _days(start, end):
    try:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
        return (e - s).days
    except (TypeError, ValueError):
        return None


def _shift_months(iso_date, months):
    """回 iso_date 往前 months 個月的日期字串(ISO,可字典序比較);壞輸入回 None。"""
    try:
        d = datetime.date.fromisoformat(iso_date[:10])
    except (TypeError, ValueError):
        return None
    m = d.month - 1 - months
    y = d.year + m // 12
    m = m % 12 + 1
    return f"{y:04d}-{m:02d}-{min(d.day, 28):02d}"


def _units_usd(facts, section, concept):
    node = facts.get(section, {}).get(concept)
    if not node:
        return []
    units = node.get("units", {})
    # 股數是 'shares' 單位,金額是 'USD'
    for key in ("USD", "shares"):
        if key in units:
            return units[key]
    # 萬一單位名不同,取第一個
    return next(iter(units.values()), []) if units else []


def _annual_flow(entries):
    """回 {fiscal_year_end_year(int): val},只取年報(10-K)且期長 ~1 年的年度值。
    同一年多次申報(重編)取 filed 最新。"""
    by_year = {}
    for e in entries:
        s, en, val = e.get("start"), e.get("end"), e.get("val")
        form, filed = str(e.get("form", "")), str(e.get("filed", ""))
        if s is None or en is None or val is None:
            continue
        if not form.startswith("10-K"):
            continue
        d = _days(s, en)
        if d is None or not (300 <= d <= 400):   # 只要年度(排除季/半年/累計)
            continue
        yr = int(en[:4])
        if yr not in by_year or filed > by_year[yr][1]:
            by_year[yr] = (float(val), filed)
    return {y: v for y, (v, _) in by_year.items()}


def _latest_instant(entries, forms=("10-K", "10-Q"), not_before=None):
    """回最近一筆 instant(cash/debt/shares)的 (end_date, val);取 end 最新、同 end 取 filed 最新。
    not_before(ISO 日字串)以下的 end 一律跳過——擋停用 tag 凍結的舊值。"""
    best_key, best_val = None, None
    for e in entries:
        en, val = e.get("end"), e.get("val")
        form, filed = str(e.get("form", "")), str(e.get("filed", ""))
        if en is None or val is None:
            continue
        if forms and not any(form.startswith(f) for f in forms):
            continue
        if not_before is not None and en < not_before:
            continue
        key = (en, filed)
        if best_key is None or key > best_key:
            best_key, best_val = key, (en, float(val))
    return best_val


def _merge_flows(facts, concepts, section="us-gaap"):
    """跨多個同義 XBRL 概念合併年度值(union by year)。公司常在不同年代換 tag
    (如 NVDA capex:早年 PropertyPlantAndEquipment、近年 ProductiveAssets),單取
    第一個非空概念會漏掉半段歷史。年度衝突時取「先列」概念(較規範者優先)。"""
    merged = {}
    for c in concepts:
        for y, v in _annual_flow(_units_usd(facts, section, c)).items():
            if y not in merged:
                merged[y] = v
    return merged


def _consecutive_tail(years):
    """回以最新年結尾的最長連續年序列。防年度斷層(換 tag/停牌)被 _normalize_fcf
    當成單年爆炸成長。例:[2010,2011,2012,2022,..,2026] → [2022,..,2026]。"""
    if not years:
        return []
    ys = sorted(set(years))
    tail = [ys[-1]]
    for y in reversed(ys[:-1]):
        if y == tail[0] - 1:
            tail.insert(0, y)
        else:
            break
    return tail


def _resolve_shares(facts, not_before=None):
    """總股數(供 equity/shares 算每股)。單一股別用 dei 封面股數(recency-guard:停用 tag 的
    凍結舊值不採用,如 HEI 的 2015 dei)→ 退回加權稀釋股數(全股別合計,來自最新 10-K 故必新鮮)
    → 再退 CommonStockSharesOutstanding。"""
    row = _latest_instant(_units_usd(facts, "dei", "EntityCommonStockSharesOutstanding"),
                          forms=("10-K", "10-Q", "20-F", "8-K", "S-1", "DEF"), not_before=not_before)
    if row and row[1] > 0:
        return row[1]
    wa = _merge_flows(facts, ["WeightedAverageNumberOfDilutedSharesOutstanding",
                              "WeightedAverageNumberOfSharesOutstandingBasic"])
    if wa:
        v = wa[max(wa)]
        if v and v > 0:
            return v
    row = _first_present_instant(facts, ["CommonStockSharesOutstanding"], forms=("10-K", "10-Q"),
                                 not_before=not_before)
    if row and row[1] > 0:
        return row[1]
    return None


def _first_present_instant(facts, concepts, section="us-gaap", forms=("10-K", "10-Q"), not_before=None):
    """依序 fallback,回第一個「存在且不早於 not_before」的最新 instant。
    forms 含 10-Q:最新資產負債表值常在季報(公司停在 10-K 的舊 tag 才是凍結源)。"""
    for c in concepts:
        got = _latest_instant(_units_usd(facts, section, c), forms=forms, not_before=not_before)
        if got is not None:
            return got  # (end_date, val)
    return None


def fetch_companyfacts(symbol, cik=None):
    cik = cik or symbol_to_cik(symbol)
    if not cik:
        return None
    try:
        raw = _fetch(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik}.json", timeout=30)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def fetch_us_fundamentals(symbol, cik=None, _cf=None):
    """回 us_dcf 需要的正規化基本面,或 None。
    {fcfs:[oldest..newest 年度FCF], shares, net_debt, beta:None, source:'edgar', fy_years:[...]}
    fcfs = 年度 OCF − capex(EDGAR 的 capex=正的付款額,故用減法)。"""
    cf = _cf if _cf is not None else fetch_companyfacts(symbol, cik)
    if not cf:
        return None
    facts = cf.get("facts", {})
    if not facts:
        return None

    ocf = _merge_flows(facts, OCF_CONCEPTS)
    capex = _merge_flows(facts, CAPEX_CONCEPTS)
    if not ocf:
        return None
    both = [y for y in ocf if y in capex]          # 兩者都有的年度才算得出 FCF
    years = _consecutive_tail(both)                # 只取連續尾段,防斷層假成長
    if len(years) < 3:
        return None
    fcfs = [ocf[y] - capex[y] for y in years]      # capex 為正付款額 → 減
    fcfs = fcfs[-6:]                                # 最多近 6 年,oldest→newest

    # 資產負債表 as-of 錨點:cash+debt 概念的最新 instant 日(10-K+10-Q,不設 not_before 才找得到
    # 真正最新)。所有 instant 腿(cash/STI/debt/shares)必須不早於此日 STALE_MONTHS 個月,
    # 否則=停用 tag 凍結的舊值(HEI 2015 股數/AMGN 2017 短投/SBUX 2022 現金/TSLA 2013 負債)。
    _anchor_dates = []
    for c in (CASH_CONCEPTS + LT_DEBT_NONCUR_CONCEPTS + TOTAL_DEBT_CONCEPTS):
        row = _latest_instant(_units_usd(facts, "us-gaap", c))
        if row:
            _anchor_dates.append(row[0])
    bs_asof = max(_anchor_dates) if _anchor_dates else None
    not_before = _shift_months(bs_asof, STALE_MONTHS) if bs_asof else None

    shares = _resolve_shares(facts, not_before=not_before)
    if not shares or shares <= 0:
        return None

    cash_row = _first_present_instant(facts, CASH_CONCEPTS, not_before=not_before)
    cash = cash_row[1] if cash_row else 0.0
    sti_row = _first_present_instant(facts, STI_CONCEPTS, not_before=not_before)
    if sti_row:
        cash += sti_row[1]

    cur_row = _first_present_instant(facts, LT_DEBT_CUR_CONCEPTS, not_before=not_before)
    cur_debt = cur_row[1] if cur_row else 0.0
    sb_row = _first_present_instant(facts, SHORT_BORROW_CONCEPTS, not_before=not_before)
    short_borrow = sb_row[1] if sb_row else 0.0
    # 雙重計數守衛:ShortTermBorrowings 與 LongTermDebtCurrent 同額 = 同一當期到期債被雙標
    # (AMD:兩者皆 0.874B),不重複加。
    if short_borrow and cur_debt and abs(short_borrow - cur_debt) <= max(1e6, 0.01 * cur_debt):
        short_borrow = 0.0
    # 長債腿:優先「真·非流動長債」LongTermDebtNoncurrent——有它才把當期到期/短借加上去。
    # 若只剩聚合 LongTermDebt(us-gaap 定義本身=含當期到期額),它已是全額,不可再加當期腿,
    # 否則 current 被重複計(AT&T:LTDNoncur 停在 2012→退聚合 134.7B 又加 DebtCurrent 6.8B=
    # 141.5B,比公司自報 IncludingCurrentMaturities 總額 136.1B 還高 → net_debt 高估數十億)。
    ltd_noncur_row = _first_present_instant(facts, ["LongTermDebtNoncurrent"], not_before=not_before)
    if ltd_noncur_row:
        component_debt = ltd_noncur_row[1] + cur_debt + short_borrow
    else:
        agg_row = _first_present_instant(facts, ["LongTermDebt"], not_before=not_before)
        component_debt = agg_row[1] if agg_row else 0.0
    total_debt = 0.0
    for c in TOTAL_DEBT_CONCEPTS:
        row = _first_present_instant(facts, [c], not_before=not_before)
        if row and row[1] > total_debt:
            total_debt = row[1]
    debt = max(component_debt, total_debt)   # 取較完整者,防分項低估
    net_debt = debt - cash

    return {
        "fcfs": fcfs,
        "shares": shares,
        "net_debt": net_debt,
        "beta": None,          # EDGAR 無市場 beta → 呼叫端預設 1.0
        "source": "edgar",
        "fy_years": years[-6:],
    }


if __name__ == "__main__":
    for s in (sys.argv[1:] or ["AAPL", "MSFT", "NVDA"]):
        d = fetch_us_fundamentals(s)
        if d:
            print(f"{s}: source={d['source']} years={d['fy_years']} "
                  f"fcfs(bn)={[round(x/1e9, 1) for x in d['fcfs']]} "
                  f"shares(bn)={round(d['shares']/1e9, 3)} net_debt(bn)={round(d['net_debt']/1e9, 1)}")
        else:
            print(f"{s}: None")
        time.sleep(0.3)
