"""衍生品/籌碼分析層:給分析師看一檔標的時,補上 cb_intel(法人流向)沒涵蓋的
融資融券、借券賣出、個股期貨基差、選擇權隱含波動。目的=分析輔助,不是下單訊號。

全功能:融資融券+券資比、借券、個股期貨基差(Shioaji 即時,期交所官方對照表263檔)、
個股選擇權 ATM IV(FinMind 日資料+Black-76,=CB 定價的市場端 vol 錨)。
CB 視角:個股期貨「逆價差擴大」=拆解者期貨對沖壓力的足跡,值得盯。
用法:cd cb_analyzer && python3 cb_derivatives.py 2330
"""
import os
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".deriv_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _finmind(dataset, code, start):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data", [])


def _cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception:
        pass


def margin_short(code, today=None):
    """融資融券餘額(張)+ 近5/20日變化 + 券資比。回 dict 或 None。當日快取。
    券資比高=空單多、軋空燃料;融資急增=散戶追買(極端時反指標)。"""
    today = today or datetime.date.today()
    c = _cache()
    ck = f"ms:{code}:{today.isoformat()}"
    if ck in c:
        return c[ck]
    start = (today - datetime.timedelta(days=45)).isoformat()
    try:
        d = _finmind("TaiwanStockMarginPurchaseShortSale", code, start)
    except Exception:
        return None
    if not d:
        return None
    d.sort(key=lambda x: x.get("date", ""))
    last = d[-1]
    mt = last.get("MarginPurchaseTodayBalance")
    st = last.get("ShortSaleTodayBalance")
    if mt is None:
        return None

    def chg(field, k):
        if len(d) <= k:
            return None
        a, b = d[-1].get(field), d[-1 - k].get(field)
        return (a - b) if (a is not None and b is not None) else None

    out = {
        "date": last.get("date"),
        "margin_bal": mt,
        "short_bal": st,
        "margin_chg_5d": chg("MarginPurchaseTodayBalance", 5),
        "margin_chg_20d": chg("MarginPurchaseTodayBalance", 20),
        "short_chg_20d": chg("ShortSaleTodayBalance", 20),
        "short_margin_ratio": round(st / mt * 100, 1) if (st and mt) else None,
    }
    sr = out["short_margin_ratio"]
    m20 = out["margin_chg_20d"]
    flags = []
    if sr is not None and sr >= 20:
        flags.append(f"券資比 {sr}% 偏高(軋空燃料)")
    base20 = (mt - m20) if (m20 is not None and mt is not None) else None
    if base20 and base20 > 0 and m20 / base20 > 0.15:
        flags.append("融資近20日急增>15%(散戶追買,極端反指標)")
    out["signal"] = " / ".join(flags) if flags else "融資券結構中性"
    c[ck] = out
    _save(c)
    return out


def securities_lending(code, today=None):
    """借券賣出餘額(法人放空的另一管道)。回 dict 或 None。資料集缺欄位就靜默降級。"""
    today = today or datetime.date.today()
    start = (today - datetime.timedelta(days=30)).isoformat()
    try:
        d = _finmind("TaiwanStockSecuritiesLending", code, start)
    except Exception:
        return None
    if not d:
        return None
    d.sort(key=lambda x: x.get("date", ""))
    last = d[-1]
    bal = last.get("SecuritiesLendingBalance") or last.get("balance")
    if bal is None:
        return None
    return {"date": last.get("date"), "lending_bal": bal}


_SJ = {"api": None}


def _shioaji():
    """懶載入 Shioaji(production,只讀報價不下單)。key 在 repo 根 .env。失敗回 None。"""
    if _SJ["api"] is not None:
        return _SJ["api"]
    try:
        env = {}
        for base in (HERE, os.path.dirname(HERE)):
            p = os.path.join(base, ".env")
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    if "=" in line and not line.startswith("#"):
                        k, v = line.strip().split("=", 1)
                        env.setdefault(k, v)
        import shioaji as sj
        import time
        api = sj.Shioaji()
        kw = dict(api_key=env["SHIOAJI_API_KEY"], secret_key=env["SHIOAJI_SECRET_KEY"])
        try:
            api.login(fetch_contract=True, **kw)
        except TypeError:
            api.login(**kw)
        time.sleep(4)
        _SJ["api"] = api
        return api
    except Exception:
        return None


MAP_CACHE = os.path.join(HERE, ".stockfut_map.json")


def _stockfut_map():
    """期交所官方「股票期貨/選擇權標的一覽」→ {證券代號:{fut:CDF, opt:CDO}}。快取30天。
    (Shioaji 1.5 的 Contracts 無法列舉,官方對照表才是正解。)"""
    import re
    import time
    try:
        c = json.load(open(MAP_CACHE, encoding="utf-8"))
        if time.time() - c.get("_fetched", 0) < 30 * 86400:
            return c["map"]
    except Exception:
        pass
    req = urllib.request.Request("https://www.taifex.com.tw/cht/2/stockLists",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html_s = r.read().decode("utf-8", "ignore")
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_s, re.S):
        cells = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 6 or not re.fullmatch(r"[A-Z]{2}", cells[0]) or not re.fullmatch(r"\d{4,6}", cells[2]):
            continue
        stock, pref = cells[2], cells[0]
        is_fut = "●" in cells[4]
        is_opt = "●" in cells[5] if len(cells) > 5 else False
        if stock not in out and is_fut:                # 首列=標準契約(非小型)
            out[stock] = {"fut": pref + "F", "opt": (pref + "O") if is_opt else None}
    try:
        json.dump({"_fetched": time.time(), "map": out}, open(MAP_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass
    return out


def futures_basis(code):
    """個股期貨基差(連續近月-現貨)。負=逆價差(避險/空方壓力)。無標的/不可用回 None。"""
    m = _stockfut_map().get(str(code))
    if not m or not m.get("fut"):
        return None
    api = _shioaji()
    if api is None:
        return None
    try:
        grp = api.Contracts.Futures.get(m["fut"])
        f = grp[m["fut"] + "R1"]                        # 連續近月
        stk = api.Contracts.Stocks[str(code)]
        snaps = api.snapshots([f, stk])
        px = {s.code: s.close for s in snaps}
        fut_px, spot = px.get(f.code), px.get(str(code))
        if not fut_px or not spot:
            return None
        return {"fut": f.code, "fut_px": fut_px, "spot": spot,
                "basis": round(fut_px - spot, 2),
                "basis_pct": round((fut_px / spot - 1) * 100, 2)}
    except Exception:
        return None


def _bs_call(F, K, T, vol):
    import math
    if T <= 0 or vol <= 0:
        return max(F - K, 0.0)
    d1 = (math.log(F / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return F * N(d1) - K * N(d2)


def options_iv(code):
    """個股選擇權近月 ATM 隱含波動(FinMind 日資料+Black-76 反解,EOD 錨點)。
    僅大型股有掛;有值=CB 定價的市場端 vol 錨(對照 cb_core 前瞻波動)。無則 None。"""
    m = _stockfut_map().get(str(code))
    if not m or not m.get("opt"):
        return None
    try:
        import datetime
        start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        rows = _finmind("TaiwanOptionDaily", m["opt"], start)
        for x in rows:                                   # 沒成交用結算價(TAIFEX 每日必標)
            if not x.get("close"):
                x["close"] = x.get("settlement_price") or 0
        rows = [x for x in rows if len(str(x.get("contract_date", ""))) == 6
                and (x.get("close") or 0) > 0]
        if not rows:
            return None
        last_day = max(x["date"] for x in rows)
        day = [x for x in rows if x["date"] == last_day]
        near = min(x["contract_date"] for x in day)
        chain = [x for x in day if x["contract_date"] == near]
        pairs = {}
        for x in chain:
            pairs.setdefault(x["strike_price"], {})[x["call_put"]] = x["close"]
        both = {k: v for k, v in pairs.items() if "call" in v and "put" in v}
        if len(both) < 2:
            return None
        F_est = sorted(k + v["call"] - v["put"] for k, v in both.items())[len(both) // 2]
        K = min(both, key=lambda k: abs(k - F_est))
        y, mo = int(str(near)[:4]), int(str(near)[4:6])
        d1 = datetime.date(y, mo, 1)
        expiry = d1 + datetime.timedelta(days=(2 - d1.weekday()) % 7 + 14)
        T = max((expiry - datetime.date.fromisoformat(last_day)).days, 1) / 365.0
        px = both[K]["call"]
        lo, hi = 0.01, 3.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if _bs_call(F_est, K, T, mid) < px:
                lo = mid
            else:
                hi = mid
        return {"iv": round(0.5 * (lo + hi), 4), "K": K, "dte": round(T * 365),
                "date": last_day, "F": round(F_est, 1)}
    except Exception:
        return None


def derivatives_lines(code, spot=None):
    """給單檔報告用的衍生品/籌碼行 list(與 cb_intel.intel_lines 平行,不重複法人流向)。"""
    lines = []
    ms = margin_short(code)
    if ms:
        seg = f"融資餘額 {ms['margin_bal']:,}張"
        if ms["margin_chg_20d"] is not None:
            seg += f"(近20日{'+' if ms['margin_chg_20d']>=0 else ''}{ms['margin_chg_20d']:,})"
        if ms["short_bal"] is not None:
            seg += f"、融券 {ms['short_bal']:,}張"
        if ms["short_margin_ratio"] is not None:
            seg += f",券資比 {ms['short_margin_ratio']}%"
        lines.append(seg)
        if ms["signal"] and ms["signal"] != "融資券結構中性":
            lines.append(f"籌碼訊號:{ms['signal']}")
    sl = securities_lending(code)
    if sl:
        lines.append(f"借券賣出餘額 {sl['lending_bal']:,}(法人空方)")
    fb = futures_basis(code)
    if fb:
        tone = "逆價差(避險/空方壓力)" if fb["basis"] < 0 else "正價差"
        lines.append(f"個股期貨({fb['fut']})基差 {fb['basis']:+.2f}({fb['basis_pct']:+.2f}%,{tone})")
    oi = options_iv(code)
    if oi:
        lines.append(f"個股選擇權 ATM 隱含波動 {oi['iv']:.0%}(K={oi['K']:.0f}, {oi['dte']}天)← 市場端 vol 錨,可對照 CB 前瞻波動")
    return lines


def main():
    import sys
    if len(sys.argv) < 2:
        print("用法:python3 cb_derivatives.py <股票代碼>")
        return
    code = sys.argv[1]
    print(f"=== {code} 衍生品/籌碼層 ===")
    ms = margin_short(code)
    if ms:
        print(json.dumps(ms, ensure_ascii=False, indent=1))
    else:
        print("融資融券:無資料(或 FinMind 暫時取不到)")
    print("\n報告行:")
    for ln in derivatives_lines(code):
        print(" •", ln)


if __name__ == "__main__":
    main()
