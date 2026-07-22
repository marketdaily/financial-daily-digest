"""台股融資融券連接器(信息差引擎積木 #4)。
散戶槓桿(融資)+看空押注(券資比)是法人動向之外的第二個籌碼面情緒指標。
資料源 FinMind(TaiwanStockMarginPurchaseShortSale + TaiwanStockPrice,免 token 可用);當日快取。
訊號定義(v1 啟發式門檻,同 tw_institutional/mops_watch 方法論——先建可行動訊號,精確門檻後續用 edge_audit 回測校準):
  🔴 融資 5 日遽減 ≥15%(疑似停損潮/斷頭賣壓,對照股價同期走勢:破底未止=趨勢確認,止穩=籌碼出清轉機)
  🔴 券資比 ≥15%(相對高檔,個股常態多在 1-5%,顯著看空押注偏高→軋空風險偏多留意)
  🟡 融資 5 日遽增 ≥15%(散戶追高過熱,短線籌碼轉弱警訊)
  🟡 融資使用率 ≥85%(逼近額度上限,拉回空間有限,易生斷頭賣壓)
  ⚪ 中性(只記錄不打擾)
"""
import os
import json
import datetime
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".margin_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _fetch(dataset, code, start):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data", [])


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def pct_change(new, old):
    if not old or new is None:
        return 0.0
    return (new - old) / old * 100.0


def classify(margin_bal, margin_5d_ago, short_bal, margin_limit, price_now, price_5d_ago):
    """回 {level, signal, rule}。純數字判斷,不叫網路。"""
    if margin_bal is None:
        return {"level": "unknown", "signal": "融資餘額資料缺漏,暫無法判斷", "rule": "unknown",
                "margin_chg_5d": None, "short_ratio": None, "util": None}
    margin_chg = pct_change(margin_bal, margin_5d_ago) if margin_5d_ago and margin_bal is not None else 0.0
    short_ratio = (short_bal / margin_bal * 100.0) if margin_bal and short_bal is not None else 0.0
    util = (margin_bal / margin_limit * 100.0) if margin_limit and margin_bal is not None else 0.0
    price_chg = pct_change(price_now, price_5d_ago) if price_5d_ago and price_now is not None else None

    if margin_chg <= -15:
        if price_chg is not None and price_chg <= -3:
            note = "股價同期續跌,趨勢確認"
        elif price_chg is not None and price_chg >= 0:
            note = "股價同期止穩,籌碼出清轉機留意"
        else:
            note = "股價走勢待確認"
        return {"level": "red", "signal": f"融資5日驟減{margin_chg:.1f}%(疑似斷頭/停損潮,{note})", "rule": "margin_plunge",
                "margin_chg_5d": round(margin_chg, 1), "short_ratio": round(short_ratio, 1), "util": round(util, 1)}
    if short_ratio >= 15:
        return {"level": "red", "signal": f"券資比{short_ratio:.1f}%(相對高檔,看空押注集中,軋空風險留意)", "rule": "short_ratio_high",
                "margin_chg_5d": round(margin_chg, 1), "short_ratio": round(short_ratio, 1), "util": round(util, 1)}
    if margin_chg >= 15:
        return {"level": "yellow", "signal": f"融資5日暴增{margin_chg:.1f}%(散戶追高過熱)", "rule": "margin_surge",
                "margin_chg_5d": round(margin_chg, 1), "short_ratio": round(short_ratio, 1), "util": round(util, 1)}
    if util >= 85:
        return {"level": "yellow", "signal": f"融資使用率{util:.1f}%(逼近額度上限,拉回易生斷頭壓力)", "rule": "margin_util_high",
                "margin_chg_5d": round(margin_chg, 1), "short_ratio": round(short_ratio, 1), "util": round(util, 1)}
    return {"level": "plain", "signal": "融資券中性", "rule": "neutral",
            "margin_chg_5d": round(margin_chg, 1), "short_ratio": round(short_ratio, 1), "util": round(util, 1)}


def _limit_steps(rows, key):
    """單日限額變化率序列。限額=股數基準(25% 流通股),分割/減資/配股發放在名目日
    精確跳因子(零噪音階梯,4967 名目 10-07 跳 ×0.7 而餘額 10-11 才換算);現金除息
    完全不動它(3006/2451 除息窗實測平坦)。非數值/非正值列跳過。"""
    vals = [r.get(key) for r in rows]
    vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
    return [b / a - 1.0 for a, b in zip(vals, vals[1:])]


def ca_conversion_suspect(prices, date_lo, date_hi, limit_rows=None, limit_key=None):
    """分割/減資在生效日把股數餘額原地換算(5536 1:2 分割日融資餘額×2、4967 減資
    ×0.7,2026-07-17 稽核實測),跨進 5 日窗時變化率是機械跳升非籌碼行為。
    v2(驗證者第12案):相鄰收盤 |變化|>10.5%(漲跌停物理上限)只是初篩,單獨不足——
    大額現金除息(3006/2451 2022-07 歷史重放 2/4 觸發=誤壓有機斷頭訊號)、興櫃/新上市
    無漲跌幅時段(1623)、價格缺洞使比較跨多日,皆會產生 >10.5% 假缺口。
    故加限額錨定:①價格缺口 且 限額單日|跳變|>5% → 壓;②限額單日下降>5%(減資/註銷
    專屬簽名,配股/增資只會升)→ 價格缺口 <10.5% 的小減資(factor>0.905 舊盲區)也壓;
    ③限額資料不可用(<2 有效列)→ 退回純價格缺口判定(寧可誤壓不漏放)。
    配股不誤壓:餘額除權/發放日皆不跳(三重實證),發放日限額升但無價格缺口配套
    (大配股除權缺口+發放日限額升同窗=既知接受的誤壓類)。價格全缺時不壓(fail-open);
    非數值 close 列跳過(髒資料不炸巡邏)。"""
    gap = False
    prev = None
    for p in prices:
        d, c = p.get("date"), p.get("close")
        if not d or not isinstance(c, (int, float)) or c <= 0 or d > date_hi:
            continue
        if prev is not None and d > date_lo and abs(c / prev - 1.0) > 0.105:
            gap = True
        prev = c
    if limit_rows is None:
        return gap
    steps = _limit_steps(limit_rows, limit_key)
    if not steps:
        return gap
    if any(s < -0.05 for s in steps):
        return True
    return gap and any(abs(s) > 0.05 for s in steps)


def margin(code, today=None):
    """回 dict:融資餘額/券資比/使用率/5日變動+訊號分級。抓不到回 None。"""
    today = today or datetime.date.today()
    cache = _load_cache()
    ck = f"{code}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]
    start = (today - datetime.timedelta(days=20)).isoformat()
    try:
        rows = _fetch("TaiwanStockMarginPurchaseShortSale", code, start)
        prices = _fetch("TaiwanStockPrice", code, start)
    except Exception:
        return None
    if not rows:
        return None
    rows.sort(key=lambda x: x["date"])
    prices.sort(key=lambda x: x["date"])
    price_by_date = {p["date"]: p.get("close") for p in prices if p.get("close")}

    last = rows[-1]
    margin_bal = last.get("MarginPurchaseTodayBalance", 0)
    short_bal = last.get("ShortSaleTodayBalance", 0)
    margin_limit = last.get("MarginPurchaseLimit", 0)

    idx_5d = -6 if len(rows) >= 6 else 0
    margin_5d_ago = rows[idx_5d].get("MarginPurchaseTodayBalance", 0)
    date_5d_ago = rows[idx_5d].get("date")

    price_now = price_by_date.get(last["date"])
    price_5d_ago = price_by_date.get(date_5d_ago)

    out = {
        "date": last["date"],
        "margin_balance": margin_bal,
        "short_balance": short_bal,
        "margin_limit": margin_limit,
    }
    out.update(classify(margin_bal, margin_5d_ago, short_bal, margin_limit, price_now, price_5d_ago))
    if out.get("rule") in ("margin_plunge", "margin_surge") and ca_conversion_suspect(
            prices, date_5d_ago or "", last["date"],
            limit_rows=rows, limit_key="MarginPurchaseLimit"):
        out.update({"level": "plain", "rule": "ca_conversion_guard",
                    "signal": "疑似分割/減資使融資餘額換算跳動(價格缺口+限額跳變佐證),5日變化率失真不判讀"})
    elif out.get("rule") == "margin_util_high" and any(
            abs(s) > 0.05 for s in _limit_steps(rows[-6:], "MarginPurchaseLimit")):
        # 名目日限額已換算而餘額未換算的錯位窗(4967 實測差 4 交易日):util 分母失真,
        # 減資方向會 ×(1/factor) 灌水假觸發 → 壓;分割方向只遮蔽(同樣不可判讀)
        out.update({"level": "plain", "rule": "ca_conversion_guard",
                    "signal": "限額單日跳變(股數基準變動),融資使用率分母換算錯位失真不判讀"})

    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    _save_cache(cache)
    return out


def scan(codes, pause=0.4):
    """批次掃描,回 {code: margin_dict}。禮貌節流。"""
    out = {}
    for c in codes:
        r = margin(c)
        if r:
            out[c] = r
        time.sleep(pause)
    return out


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(json.dumps(margin(code), ensure_ascii=False, indent=1))
