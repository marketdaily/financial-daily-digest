"""signal_ledger 結算端公司行動守衛(ca_settlement_guard)。

背景(2026-07-17 price_integrity 稽核追加前置,backlog P2.6):signal_ledger.score() 的
事後報酬 = (price_now - price_at_signal) / price_at_signal,兩端都是 raw 未還原價
(TW=FinMind TaiwanStockPrice / US=FMP quote)。持有窗 [訊號日, 今日] 內若發生
分割/減資/大額配股,報酬是機械假象(0050 2025-06 1:4 分割 raw = -74.8% 假懸崖;
CB 小型股幾乎年年配股,量級 2~37%)——eff_days 閘放行後的第一份「信息差訊號準不準」
結論會被這些污染。故結算前逐列掃窗內 CA,嫌疑列排除統計但計數可見。

偵測(gap 簽名邏輯衍生自 ~/autonomous/capabilities/price_integrity/logic.py v2;
跨 repo import 不可行——cron 環境無 ~/autonomous 保證,此處為結算專用實作):
- TW(純數字碼):FinMind TaiwanStockPrice 窗抓(與結算價同源,偵測的正是污染這筆
  報酬的同一序列的不連續),相鄰收盤 |gap|>10.5%=上市櫃漲跌停物理上限外,只可能是
  CA 或資料錯誤,兩者都該把該列踢出統計。興櫃無漲跌幅限制會誤傷(保守方向:誤排除
  合法列少樣本,不會偽造報酬;參 ca_conversion_guard F4 教訓,此處用途不同故可接受)。
- US:只用 Yahoo events(splits ∪ 單次股息殖利率>3%)。**不用 gap 腿**——本模組
  驗證者 F1(2026-07-17)實測:Yahoo chart 的 US close 序列是回溯 split-adjusted,
  真分割在 close 上沒有懸崖(NVDA 2024-06-10 10:1 分割 gap 零命中、events 命中);
  且 US 無漲跌幅限制,gap>20% 會把財報崩跌/暴漲等真實行情當 CA 排除=結果相關截尾
  (系統性砍掉最大贏/最大輸,TW「物理上限」推理不轉移到 US)。US splits 偵測因此
  單源依賴 Yahoo events(對 US 可靠,live 驗證命中;TW 側才有 events 缺漏問題)。
- day-0 邊界:TW 訊號價由 patrol 21:30(收盤後)記錄,訊號日當天的 CA 已反映在
  price_at_signal → hit 需嚴格晚於訊號日才算污染;US 記錄時點對當日盤屬模糊
  (21:30 TW≈09:30 ET 開盤)→ hit 當日即算(保守)。

誠實邊界(不可拿掉再引用):
- TW 除權息 gap ≤10.5% 偵測不到(現金股利 2-8%、小額配股)→ 事後報酬有已知的
  小幅低估偏差。正解=FINMIND_TOKEN 到位後補 TaiwanStockPriceAdj 交叉腿
  (adj/raw 比值跳變=精確 CA 日,含全部股利),見 DECISIONS m-finmind。
- US 減資/spin-off 等不進 Yahoo events 的 CA 抓不到(gap 腿因 F1 不可用,無備援)。
- 抓不到資料=unknown 不是 clean(fail-closed):嫌疑與未知都排除統計、分開計數,
  絕不靜默當乾淨(price_integrity 驗證者 F3 教訓)。窗內有壞列(解析失敗)時即使
  無 hit 也回 unknown——壞列可能藏著訊號日後的 CA(驗證者 F2)。
- 序列首列必須不晚於訊號日,否則 unknown——起點墊 16 日曆日蓋春節 9-11 天連休
  (驗證者 F3:連休中記的訊號用連休前舊價當分母,復市首日 CA 是最典型污染組合);
  IPO/資料起點晚於訊號同型洞一併擋。

用法:
    from intel.ca_settlement_guard import make_ca_check_fn
    check = make_ca_check_fn()                 # end 預設今天
    check("0050", "2025-06-01")                # -> {"status": "suspect"|"clean"|"unknown", "why": ...}
CLI 抽查: python3 -m intel.ca_settlement_guard 0050 2025-06-01
"""
import os
import sys
import json
import math
import time
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".ca_scan_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()

TW_GAP = 0.105       # 上市櫃單日漲跌停 ±10% 物理上限外=非市場波動
US_DIV_YIELD = 0.03  # 單次配息殖利率>3% 即足以扭曲事後報酬判讀
START_PAD_DAYS = 16  # 窗起點往前墊:必須蓋住春節 9-11 天連休(驗證者 F3),gap 需訊號日前收盤當分母
FETCH_SLEEP = 0.25   # 連續抓取間隔,對 FinMind 匿名層禮貌性節流


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_tw_window(code, start, end):
    """FinMind raw 日價(與 valuation.ledger.tw_price 結算腿同源)。
    回 list[{date, close, open}] 舊→新;抓取失敗或空資料回 None(=unknown,非 clean)。"""
    try:
        url = (f"{FINMIND}?dataset=TaiwanStockPrice&data_id={code}"
               f"&start_date={start}&end_date={end}")
        if TOKEN:
            url += f"&token={TOKEN}"
        data = _http_json(url).get("data", [])
        if not data:
            return None
        return [{"date": r.get("date"), "close": r.get("close"), "open": r.get("open")}
                for r in data]
    except Exception:
        return None


def fetch_us_window(sym, start, end):
    """Yahoo chart 一次拿 close 序列+events。回 (rows, events) 或 (None, None)。
    events = {"splits": [date_iso,...], "dividends": [{date, amount},...]}"""
    try:
        p1 = int(datetime.datetime.fromisoformat(start + "T00:00:00+00:00").timestamp())
        p2 = int(datetime.datetime.fromisoformat(end + "T00:00:00+00:00").timestamp()) + 86400
        j = _http_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
            f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits")
        res = j["chart"]["result"][0]
        ts = res.get("timestamp") or []
        closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        rows = []
        for t, c in zip(ts, closes):
            d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat()
            rows.append({"date": d, "close": c})
        ev = res.get("events") or {}

        def _ev_date(v):
            return datetime.datetime.fromtimestamp(
                int(v.get("date", 0)), datetime.timezone.utc).date().isoformat()
        events = {
            "splits": [_ev_date(v) for v in (ev.get("splits") or {}).values()],
            "dividends": [{"date": _ev_date(v), "amount": v.get("amount")}
                          for v in (ev.get("dividends") or {}).values()],
        }
        if not rows:
            return None, None
        return rows, events
    except Exception:
        return None, None


def scan_gaps(rows, gap_thresh):
    """相鄰收盤 gap 掃描(衍生自 price_integrity.scan_rows_full,保留壞列計數——
    n_bad>0 且零 hit 時「掃不出來」≠「證明乾淨」,呼叫端須降級 unknown)。"""
    rs, n_bad = [], 0
    for r in rows or []:
        try:
            d = str(r["date"])[:10]
            c = float(r["close"])
        except (KeyError, TypeError, ValueError):
            n_bad += 1
            continue
        if not (c > 0 and math.isfinite(c)):
            n_bad += 1
            continue
        rs.append({"date": d, "close": c})
    rs.sort(key=lambda x: x["date"])
    hits = []
    for a, b in zip(rs, rs[1:]):
        try:
            gap = b["close"] / a["close"] - 1.0
        except ZeroDivisionError:
            n_bad += 1
            continue
        if abs(gap) > gap_thresh:
            hits.append({"date": b["date"], "gap": round(gap, 4)})
    return {"hits": hits, "n_bad": n_bad, "n_rows": len(rs),
            "first_date": rs[0]["date"] if rs else None}


def _div_yield_hits(rows, dividends, min_yield=US_DIV_YIELD):
    """單次配息殖利率>門檻的事件日。分母=除息日前最近收盤;窗內無更早收盤時退用
    除息日當日/之後首筆(除息後價偏低→殖利率略高估=偏向 suspect,保守方向)。"""
    closes = sorted((r["date"], r["close"]) for r in rows
                    if isinstance(r.get("close"), (int, float)) and r.get("close"))
    hits = []
    for dv in dividends or []:
        amt, d = dv.get("amount"), dv.get("date")
        if not (isinstance(amt, (int, float)) and amt and d):
            continue
        prev = [c for dt, c in closes if dt < d]
        base = prev[-1] if prev else next((c for dt, c in closes if dt >= d), None)
        if not base:
            continue
        if amt / base > min_yield:
            hits.append({"date": d, "yield": round(amt / base, 4)})
    return hits


def _scan_code(code, start, end, fetch_tw=fetch_tw_window, fetch_us=fetch_us_window):
    """單一 code 的窗內 CA 掃描。回 {"ok", "suspect_dates", "n_bad", "first_date"}。
    ok=False → 呼叫端一律 unknown(fail-closed)。n_bad/first_date 由 check() 消費
    (壞列不可證乾淨/序列起點不可晚於訊號日——驗證者 F2/F3,判定需訊號日故不在此層)。"""
    if str(code).isdigit():
        rows = fetch_tw(code, start, end)
        if rows is None:
            return {"ok": False, "suspect_dates": [], "n_bad": 0, "first_date": None}
        g = scan_gaps(rows, TW_GAP)
        if g["n_rows"] < 2:
            return {"ok": False, "suspect_dates": [], "n_bad": g["n_bad"],
                    "first_date": g["first_date"]}
        return {"ok": True, "suspect_dates": sorted(h["date"] for h in g["hits"]),
                "n_bad": g["n_bad"], "first_date": g["first_date"]}
    rows, events = fetch_us(code, start, end)
    if rows is None:
        return {"ok": False, "suspect_dates": [], "n_bad": 0, "first_date": None}
    # US 不用 gap 腿(驗證者 F1:Yahoo US close 是 split-adjusted,分割無懸崖可掃;
    # 且無漲跌幅限制,gap 門檻會截尾真實極端行情)。scan_gaps 只借 n_bad/first_date 記帳。
    g = scan_gaps(rows, gap_thresh=float("inf"))
    if g["n_rows"] < 2:
        return {"ok": False, "suspect_dates": [], "n_bad": g["n_bad"],
                "first_date": g["first_date"]}
    dates = set(events.get("splits") or [])
    dates.update(h["date"] for h in _div_yield_hits(rows, events.get("dividends")))
    return {"ok": True, "suspect_dates": sorted(dates), "n_bad": g["n_bad"],
            "first_date": g["first_date"]}


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(path, cache):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass  # 快取寫不進去只影響效能不影響正確性


def make_ca_check_fn(today=None, cache_path=CACHE,
                     fetch_tw=fetch_tw_window, fetch_us=fetch_us_window,
                     sleep_s=FETCH_SLEEP):
    """回 check(code, sig_date_iso) -> {"status": "clean"|"suspect"|"unknown", "why": str}。

    - 每 code 每輪最多真抓一次:成功入 memo+磁碟;失敗也入 memo(標 failed,本輪同 code
      不再重打——驗證者 F4:配額最緊的時刻不可放大請求量)但不入磁碟(跨輪自動重試);
      memo 失敗項不遮蔽本可涵蓋的磁碟有效項(memo/disk 各自檢查涵蓋)。
    - suspect 判定:窗內存在 CA 嫌疑日——TW 需嚴格晚於訊號日(收盤後記錄,day-0 已反映),
      US 含訊號日當天(記錄時點對當日盤模糊,保守)。
    - 任何解析/抓取失敗=unknown(fail-closed),絕不回 clean。無嫌疑但窗內有壞列
      (n_bad>0)=unknown(壞列可能藏訊號日後的 CA,驗證者 F2);序列首列晚於訊號日
      =unknown(訊號日前分母缺席,連休/IPO 洞,驗證者 F3)。"""
    end = (today if isinstance(today, str) else
           (today or datetime.date.today()).isoformat())
    disk = _load_cache(cache_path)
    memo = {}

    def _covers(ent, start):
        return (isinstance(ent, dict) and ent.get("ok")
                and isinstance(ent.get("suspect_dates"), list)  # 半壞快取不採信
                and ent.get("first_date")  # 舊 schema(無 first_date)不採信→重抓
                and ent.get("start", "9999") <= start and ent.get("end", "") >= end)

    def check(code, sig_date):
        code = str(code)
        try:
            sd = datetime.date.fromisoformat(str(sig_date)[:10])
        except ValueError:
            return {"status": "unknown", "why": "bad sig_date"}
        start = (sd - datetime.timedelta(days=START_PAD_DAYS)).isoformat()
        ent_m, ent_d = memo.get(code), disk.get(code)
        if _covers(ent_m, start):
            ent = ent_m
        elif _covers(ent_d, start):
            ent = ent_d
        elif isinstance(ent_m, dict) and not ent_m.get("ok"):
            ent = ent_m  # 本輪已對此 code 失敗過:不重打(F4),直接走下方 unknown
        else:
            # 起點取「本次需求」與「既有磁碟快取」較早者,避免同 code 較早訊號來回重抓
            if isinstance(ent_d, dict) and ent_d.get("start", "9999") < start:
                start = ent_d["start"]
            if memo:  # 同一輪已抓過別的 code 才節流,首抓不必等
                time.sleep(sleep_s)
            scan = _scan_code(code, start, end, fetch_tw=fetch_tw, fetch_us=fetch_us)
            ent = {"start": start, "end": end, **scan}
            memo[code] = ent
            if scan["ok"]:
                disk[code] = ent
                _save_cache(cache_path, disk)
        if not ent.get("ok"):
            return {"status": "unknown", "why": "fetch/scan failed — cannot certify clean"}
        sig_iso = sd.isoformat()
        first = ent.get("first_date")
        if not first or first > sig_iso:
            return {"status": "unknown",
                    "why": "series starts after signal — pre-signal baseline missing"}
        is_tw = code.isdigit()
        for d in ent.get("suspect_dates", []):
            if (d > sig_iso) if is_tw else (d >= sig_iso):
                return {"status": "suspect", "why": f"CA-signature at {d} in holding window"}
        if ent.get("n_bad", 0) > 0:
            return {"status": "unknown",
                    "why": "dirty rows in window — cannot certify clean"}
        return {"status": "clean", "why": ""}

    return check


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 -m intel.ca_settlement_guard <code> <sig_date_iso>")
        sys.exit(2)
    fn = make_ca_check_fn()
    print(json.dumps(fn(sys.argv[1], sys.argv[2]), ensure_ascii=False))
