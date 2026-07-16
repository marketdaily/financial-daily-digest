"""衍生品/籌碼分析層:給分析師看一檔標的時,補上 cb_intel(法人流向)沒涵蓋的
融資融券、借券賣出、個股期貨基差、選擇權隱含波動。目的=分析輔助,不是下單訊號。

現在能跑的(FinMind 免費):融資融券餘額+券資比、借券賣出餘額。
禮拜一接 Shioaji 後補:個股期貨基差、選擇權市場 IV(可回頭當 CB 定價的市場端 vol 錨)。
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


def futures_basis(code):
    """個股期貨基差(期貨 - 現貨)。禮拜一接 Shioaji 後實作:
    basis>0 逆價差=看空/避險需求,<0 正價差=看多。現回 None(hook)。"""
    return None  # TODO(Shioaji Monday): api.snapshots 個股期貨 vs 現股


def options_iv(code):
    """上市選擇權市場隱含波動 + put/call skew。禮拜一接 Shioaji 後實作。
    ⚠️ 台灣個股選擇權流動性普遍差,僅少數大型股(如 2330)+ 指數(TXO)有意義;
    有值時可回頭當 cb_core CB 定價的『市場端 vol 錨』交叉驗證。現回 None(hook)。"""
    return None  # TODO(Shioaji Monday): 選擇權鏈 → BS 反解 IV(接 cb_core 同一套)


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
    if fb is not None:
        lines.append(f"個股期貨基差 {fb:+.2f}")
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
    print("\n(期貨基差 / 選擇權 IV = 禮拜一接 Shioaji 後補的 hook)")


if __name__ == "__main__":
    main()
