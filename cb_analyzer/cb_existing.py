"""現有(已上市/上櫃)可轉債:從 TPEx 抓全市場 CB 發行條件,輸入任何代碼即可跑同一套拆解分析。
資料源 TPEx OpenAPI:bond_ISSBD5_data(國內轉換債)+ bond_ISSBD6_data(海外轉換債)。免 token。
缺 TCRI(TEJ 專有)→ 預設未知,可用 --tcri 帶入或自動沿用老闆 Excel 內同檔評等。
用剩餘年限(距今到賣回/到期)計價,非原始年期。"""
import os
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".existing_cb_cache.json")
CVKEY = "Conversion/ExchangePriceAtIssuance"
ENDPOINTS = [
    "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data",
    "https://www.tpex.org.tw/openapi/v1/bond_ISSBD6_data",
]


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pdate(s):
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def fetch_raw(force=False, today=None):
    today = today or datetime.date.today()
    if not force and os.path.exists(CACHE):
        try:
            with open(CACHE, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("date") == today.isoformat():
                return c["rows"]
        except Exception:
            pass
    rows = []
    for ep in ENDPOINTS:
        try:
            rows += json.loads(_get(ep))
        except Exception:
            continue
    if rows:
        try:
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump({"date": today.isoformat(), "rows": rows}, f, ensure_ascii=False)
        except Exception:
            pass
    return rows


def _yearfrac(d0, d1):
    return max((d1 - d0).days / 365.25, 0.05) if (d0 and d1) else None


def _to_item(d, today):
    conv = _num(d.get(CVKEY))
    bond = (d.get("BondCode") or "").strip()
    if not conv or not bond:
        return None
    issue_d = _pdate(d.get("IssueDate"))
    mat_d = _pdate(d.get("MaturityDate"))
    put_d = _pdate(d.get("PutOptionDate"))
    put_px = _num(d.get("PutOptionPrice"))
    yr_to_mat = _yearfrac(today, mat_d) or (_num(d.get("TenorYear")) or 3)

    if put_d and put_d > today and put_px and put_px > 0:
        n = _yearfrac(today, put_d)
        # 由賣回價反推年化殖利率(相對面額100),供顯示
        yld = ((put_px / 100.0) ** (1 / max(n, 0.1)) - 1) * 100 if put_px else 0
        put = {"kind": "YTP", "year": round(n, 2), "y_low": yld, "y_high": yld,
               "y_mid": round(yld, 2), "redeem_price": put_px,
               "raw": f"YTP@{put_d.isoformat()}={put_px:.1f}"}
    else:
        put = {"kind": "YTM", "year": round(yr_to_mat, 2), "y_low": 0, "y_high": 0,
               "y_mid": 0, "redeem_price": 100.0,
               "raw": f"YTM@{mat_d.isoformat() if mat_d else '?'}=100"}

    guaranteed = str(d.get("Guaranteed")) == "1"
    gdesc = (d.get("GuaranteeDescription") or "").strip()
    size = _num(d.get("IssueAmount"))
    size_yi = round(size / 1e8, 2) if size else None
    out_amt = _num(d.get("OutstandingAmount"))
    conv_s, conv_e = _pdate(d.get("Conversion/ExchangePeriodStartDate")), _pdate(d.get("Conversion/ExchangePeriodEndDate"))
    return {
        "section": "現有可轉債",
        "stock_code": (d.get("IssuerCode") or "").strip().lstrip("0") or (d.get("IssuerCode") or "").strip(),
        "bond_code": bond,
        "name": (d.get("ShortName") or d.get("IssuerName") or "").strip(),
        "tcri": None,
        "collateral": (gdesc[:6] if guaranteed and gdesc else ("有擔保" if guaranteed else "無擔")),
        "secured": guaranteed,
        "size_yi": size_yi,
        "underwriter": (d.get("Underwriter") or "").strip(),
        "announce_date": None,
        "effective_date": None,
        "bookbuild": "",
        "premium_low": None, "premium_high": None, "premium_mid": None,
        "conv_price": conv,
        "listing_date": d.get("ListingDate"),
        "maturity_date": mat_d.isoformat() if mat_d else None,
        "issue_date": issue_d.isoformat() if issue_d else None,
        "split_date": None,
        "put": put,
        "tenor_year": round(yr_to_mat, 2),
        "clearing_price": None,
        "auction_low": None, "auction_high": None,
        "pricing_method": "現有CB(次級市場)",
        "issue_price": None,
        "is_existing": True,
        # 籌碼/條款面(TPEx 每日檔):流通餘額→轉換進度;票面利率;轉換期間
        "outstanding_yi": round(out_amt / 1e8, 2) if out_amt else None,
        "converted_pct": round((1 - out_amt / size) * 100, 1) if (out_amt and size) else None,
        "coupon_rate": _num(d.get("CouponRate")),
        "conv_start": conv_s.isoformat() if conv_s else None,
        "conv_end": conv_e.isoformat() if conv_e else None,
        "note": (f"發行 {d.get('IssueDate','?')}→到期 {d.get('MaturityDate','?')};"
                 f"轉換價為發行時價,可能經反稀釋/除權息調整,精算前請核對最新轉換價與流通餘額"),
    }


_index = None


def _build_index(today):
    global _index
    if _index is not None:
        return _index
    _index = {"by_bond": {}, "by_stock": {}}
    for d in fetch_raw(today=today):
        if str(d.get("ListingStatus")) not in ("2", "5", ""):
            continue
        it = _to_item(d, today)
        if not it:
            continue
        _index["by_bond"][it["bond_code"]] = it
        _index["by_stock"].setdefault(it["stock_code"], []).append(it)
    return _index


def lookup(code, today=None):
    """輸入 CB 債券代碼(如 11011)或股票代碼(如 1101)或名稱片段 → 回符合的現有 CB item list。"""
    today = today or datetime.date.today()
    idx = _build_index(today)
    code = str(code).strip()
    if code in idx["by_bond"]:
        return [idx["by_bond"][code]]
    if code in idx["by_stock"]:
        return list(idx["by_stock"][code])
    hits = [it for it in idx["by_bond"].values() if code in it["name"]]
    return hits


def all_items(today=None):
    idx = _build_index(today or datetime.date.today())
    return list(idx["by_bond"].values())


def by_bond(bond_code, today=None):
    """單一債券代碼 → TPEx 現況 item(流通餘額/轉換進度/票面/轉換期間)或 None。
    給老闆 Excel 管線的 CB 掛牌後補籌碼面資訊用。"""
    idx = _build_index(today or datetime.date.today())
    return idx["by_bond"].get(str(bond_code).strip())
