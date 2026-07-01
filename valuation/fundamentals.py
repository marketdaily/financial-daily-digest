"""日報估值帶 + 籌碼/法人(看深入專屬)。
全部用真實客觀數字,缺料一律回 None / 跳過,絕不編造,絕不拖垮日報。
- 台股估值:FinMind TaiwanStockPER → 本益比 + 近一年百分位(自身歷史,客觀 cheap/fair/expensive)。
- 美股估值:FMP P/E + 成長(eps_yoy / yoy)→ PEG(便宜<1 / 合理1-2 / 偏貴>2)。
- 台股籌碼:FinMind 三大法人買賣超 → 外資+投信近 5 日淨額(張)。
- 美股籌碼:FMP 內部人交易近 90 日 買/賣筆數淨額(沒 key / 失敗則略)。
CLI: python3 valuation/fundamentals.py 2330 NVDA
"""
import os, sys, json, urllib.request, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FINMIND = "https://api.finmindtrade.com/api/v4/data"
FMP = "https://financialmodelingprep.com/stable"
FMP_KEY = os.environ.get("FMP_API_KEY", "").strip()
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _finmind(dataset, data_id, start_date):
    url = f"{FINMIND}?dataset={dataset}&data_id={data_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    return _http_json(url).get("data", [])


def _pct_rank(series, value):
    """value 在 series 裡的百分位(0-100),越低=越便宜。"""
    arr = [x for x in series if x is not None and x > 0]
    if not arr or value is None:
        return None
    below = sum(1 for x in arr if x <= value)
    return round(below / len(arr) * 100)


# ── 台股:本益比 + 近一年百分位 ──
def tw_valuation(stock_id, today):
    try:
        start = (today - datetime.timedelta(days=400)).isoformat()
        rows = _finmind("TaiwanStockPER", stock_id, start)
    except Exception:
        return None
    rows = [r for r in (rows or []) if r.get("PER") not in (None, 0, "0")]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("date", ""))
    cur = rows[-1]
    try:
        per = float(cur.get("PER"))
    except (TypeError, ValueError):
        return None
    if per <= 0:
        return None
    series = []
    for r in rows:
        try:
            series.append(float(r.get("PER")))
        except (TypeError, ValueError):
            pass
    pct = _pct_rank(series, per)
    pbr = cur.get("PBR")
    yld = cur.get("dividend_yield")
    if pct is None:
        cls, label = "fair", f"本益比 {per:.1f} 倍"
    elif pct <= 30:
        cls, label = "cheap", f"本益比 {per:.1f} 倍(近一年第 {pct} 百分位,相對便宜)"
    elif pct >= 70:
        cls, label = "rich", f"本益比 {per:.1f} 倍(近一年第 {pct} 百分位,相對偏貴)"
    else:
        cls, label = "fair", f"本益比 {per:.1f} 倍(近一年第 {pct} 百分位,估值中性)"
    extra = []
    if yld not in (None, 0, "0"):
        try:
            extra.append(f"殖利率 {float(yld):.1f}%")
        except (TypeError, ValueError):
            pass
    if extra:
        label += "、" + "、".join(extra)
    return {"valuation": label, "val_class": cls, "per": round(per, 1)}


# ── 美股:P/E + 成長 → PEG ──
def us_valuation(symbol, growth_pct):
    if not FMP_KEY:
        return None
    try:
        rows = _http_json(f"{FMP}/quote?symbol={symbol}&apikey={FMP_KEY}")
    except Exception:
        return None
    if not rows or not isinstance(rows, list):
        return None
    q = rows[0]
    pe = q.get("pe")
    try:
        pe = float(pe)
    except (TypeError, ValueError):
        return None
    if pe <= 0:
        return {"valuation": "目前虧損或無正本益比,改看成長與現金流", "val_class": "na", "pe": None}
    if growth_pct and growth_pct > 3:
        peg = pe / growth_pct
        if peg < 1:
            cls, tag = "cheap", "相對成長偏便宜"
        elif peg <= 2:
            cls, tag = "fair", "估值合理"
        else:
            cls, tag = "rich", "相對成長偏貴"
        label = f"本益比 {pe:.0f} 倍 / 成長 {growth_pct:.0f}% → PEG {peg:.1f}({tag})"
    else:
        cls = "rich" if pe >= 35 else ("fair" if pe >= 18 else "cheap")
        label = f"本益比 {pe:.0f} 倍(無明確成長數據,僅供參考)"
    return {"valuation": label, "val_class": cls, "pe": round(pe, 1)}


# ── 台股籌碼:三大法人近 5 日淨額 ──
def tw_chips(stock_id, today):
    try:
        start = (today - datetime.timedelta(days=12)).isoformat()
        rows = _finmind("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start)
    except Exception:
        return None
    if not rows:
        return None
    by_date = {}
    for r in rows:
        by_date.setdefault(r.get("date"), []).append(r)
    last5 = sorted(by_date.keys())[-5:]
    if not last5:
        return None
    foreign = trust = 0
    for d in last5:
        for r in by_date[d]:
            nm = r.get("name", "")
            net = (r.get("buy", 0) or 0) - (r.get("sell", 0) or 0)
            if "Foreign" in nm:
                foreign += net
            elif "Investment_Trust" in nm or "Trust" in nm:
                trust += net
    f_lot = foreign / 1000
    t_lot = trust / 1000
    if abs(f_lot) < 50 and abs(t_lot) < 50:
        return {"chips": "三大法人近5日進出平淡", "chip_class": "neutral"}
    parts = []
    if abs(f_lot) >= 50:
        parts.append(f"外資近5日{'買超' if f_lot > 0 else '賣超'} {abs(f_lot):,.0f} 張")
    if abs(t_lot) >= 50:
        parts.append(f"投信{'買超' if t_lot > 0 else '賣超'} {abs(t_lot):,.0f} 張")
    cls = "buy" if (f_lot + t_lot) > 0 else "sell"
    return {"chips": "、".join(parts), "chip_class": cls}


# ── 美股籌碼:內部人交易近 90 日 ──
def us_chips(symbol):
    if not FMP_KEY:
        return None
    try:
        rows = _http_json(f"{FMP}/insider-trading/search?symbol={symbol}&page=0&limit=40&apikey={FMP_KEY}")
    except Exception:
        return None
    if not rows or not isinstance(rows, list):
        return None
    cutoff = (datetime.date.today() - datetime.timedelta(days=90))
    buys = sells = 0
    for r in rows:
        d = str(r.get("transactionDate") or r.get("filingDate") or "")[:10]
        try:
            if datetime.date.fromisoformat(d) < cutoff:
                continue
        except ValueError:
            continue
        t = (r.get("transactionType") or r.get("acquisitionOrDisposition") or "")
        if t.startswith("P") or t == "A":
            buys += 1
        elif t.startswith("S") or t == "D":
            sells += 1
    if buys == 0 and sells == 0:
        return None
    if buys > sells:
        return {"chips": f"內部人近90日 {buys} 買 / {sells} 賣(偏買)", "chip_class": "buy"}
    if sells > buys:
        return {"chips": f"內部人近90日 {buys} 買 / {sells} 賣(偏賣)", "chip_class": "sell"}
    return {"chips": f"內部人近90日 {buys} 買 / {sells} 賣(中性)", "chip_class": "neutral"}


def compute_fundamentals(us_syms, tw_syms, today, earnings_impact=None):
    """回傳 {sym: {valuation, val_class, chips, chip_class, ...}}。任何單檔失敗只跳過該檔。"""
    ei = earnings_impact or {}
    try:
        from valuation.dcf import compute_dcf
    except Exception:
        compute_dcf = None
    out = {}
    for sym in (tw_syms or []):
        rec = {}
        try:
            v = tw_valuation(sym, today)
            if v:
                rec.update(v)
        except Exception:
            pass
        try:
            c = tw_chips(sym, today)
            if c:
                rec.update(c)
        except Exception:
            pass
        if compute_dcf:
            try:
                d = compute_dcf(sym, today)
                if d:
                    rec.update(d)
            except Exception:
                pass
        if rec:
            out[sym] = rec
    for sym in (us_syms or []):
        rec = {}
        a = ei.get(sym) or {}
        growth = a.get("eps_yoy")
        if growth is None:
            growth = a.get("yoy")
        try:
            v = us_valuation(sym, growth)
            if v:
                rec.update(v)
        except Exception:
            pass
        try:
            c = us_chips(sym)
            if c:
                rec.update(c)
        except Exception:
            pass
        if compute_dcf:
            try:
                d = compute_dcf(sym, today)
                if d:
                    rec.update(d)
            except Exception:
                pass
        if rec:
            out[sym] = rec
    return out


if __name__ == "__main__":
    today = datetime.date.today()
    syms = sys.argv[1:] or ["2330", "NVDA"]
    tw = [s for s in syms if s.isdigit()]
    us = [s for s in syms if not s.isdigit()]
    res = compute_fundamentals(us, tw, today)
    print(json.dumps(res, ensure_ascii=False, indent=2))
