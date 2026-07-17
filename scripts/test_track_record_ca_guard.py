#!/usr/bin/env python3
"""build_track_record 跨公司行動(CA)守衛迴歸測試(2026-07-17)。

凍結三個修法的語意:
  1. 幽靈休市日濾網:全市場級「休市+資料商複製前日 bar」(2026-07-10 颱風實例,39/39 檔
     bar=前日複本)必須被剔出共識日曆;少數檔恰好連兩日同收盤不可誤殺;檔數<門檻不判。
  2. 現金股息修正:結算窗跨除息日 → chg=(settle+div-base)/base;股息在基準日當天不算
     (基準收盤已除息)、在結算日當天要算;排定日遇休市順延生效;除權(配股)不加現金;
     「除權息合併列」不調整(fail-open);尺度帶外不換算。
  3. 退化窗守衛:基準日前推越過日曆 ref 導致結算日 ≤ 基準日(chg 恆 0 假結算,6907
     2026-07-10 實例)→ 誠實待結(None)。

用法: .venv/bin/python scripts/test_track_record_ca_guard.py   (exit 0=全過)
純合成 fixture,零網路、零真實快取讀寫。
"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "btr", Path(__file__).resolve().parent / "build_track_record.py")
btr = importlib.util.module_from_spec(spec)
sys.modules["btr"] = btr
spec.loader.exec_module(btr)

FAILS = []


def check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"{status} {name}" + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def mk_hist(days, prices):
    return {d: p for d, p in zip(days, prices)}


# ── 1. 幽靈休市日濾網 ─────────────────────────────────────────
DAYS = [f"2026-07-{dd:02d}" for dd in (1, 2, 3, 6, 7, 8, 9, 10, 13, 14, 15)]
N = 12  # ≥ _PHANTOM_MIN_SYMBOLS


def synth_market(phantom_on="2026-07-10", n=N, n_phantom=None):
    """n 檔合成 TW 市場;phantom_on 那天全部(或 n_phantom 檔)bar=前日複本。"""
    hists = {}
    for k in range(n):
        prices = [100.0 + k + i * 0.7 for i in range(len(DAYS))]
        h = dict(zip(DAYS, prices))
        if phantom_on and (n_phantom is None or k < n_phantom):
            idx = DAYS.index(phantom_on)
            h[phantom_on] = h[DAYS[idx - 1]]
        hists[f"{1000 + k}"] = h
    return hists

cals, _ = btr._market_trading_calendar(synth_market())
check("1a 全市場幽靈日被剔出日曆", "2026-07-10" not in cals.get("TW", []),
      f"cal={cals.get('TW')}")
check("1b 其餘真交易日保留", all(d in cals.get("TW", []) for d in DAYS if d != "2026-07-10"))

cals2, _ = btr._market_trading_calendar(synth_market(n_phantom=3))
check("1c 少數檔(3/12)複本日不誤殺", "2026-07-10" in cals2.get("TW", []))

cals3, _ = btr._market_trading_calendar(synth_market(n=6))
check("1d 檔數 6<10 門檻不判幽靈(保守)", "2026-07-10" in cals3.get("TW", []))

cals4, _ = btr._market_trading_calendar(synth_market(phantom_on=None))
check("1e 無幽靈日時日曆完整", cals4.get("TW", []) == DAYS)

# ── 2. 現金股息修正 ───────────────────────────────────────────
cal = DAYS
h = mk_hist(DAYS, [100, 101, 102, 103, 104, 100, 101, 102, 103, 104, 105])


def fields_for(d, events):
    f = btr._settle_on_calendar(h, sorted(h), cal, set(cal), "9999", d)
    btr._attach_window_divs(f, events, h, cal, "9999")
    return f

ev_cash = [{"date": "2026-07-08", "cash": 5.0, "stock": 0.0, "before_price": 104.0}]
f = fields_for("2026-07-02", ev_cash)  # 窗 (07-02, 07-09]
check("2a 窗內現金股息掛上 div_5d", abs((f.get("div_5d") or 0) - 5.0) < 1e-9, str(f))
rec = {"ticker": "9999", "date": "2026-07-02"}
chg = btr.settlement_chg(rec, {("9999", "2026-07-02"): f}, "5d")
# 窗=(07-02,07-09],基準收盤 101、結算(07-09)收盤 101、div 5 → chg=(101+5-101)/101
check("2b chg 含股息 (101+5-101)/101", abs(chg - 5 / 101) < 1e-12, f"chg={chg}")

f = fields_for("2026-07-08", ev_cash)  # 除息=基準日當天:基準收盤已除息,不算
check("2c 股息在基準日當天不算", not f.get("div_5d"), str(f.get("div_5d")))

ev_settle = [{"date": "2026-07-09", "cash": 3.0, "stock": 0.0, "before_price": 100.0}]
f = fields_for("2026-07-02", ev_settle)  # 窗 (07-02, 07-09] 右閉:結算日當天要算
check("2d 股息在結算日當天要算", abs((f.get("div_5d") or 0) - 3.0) < 1e-9,
      str(f.get("div_5d")))

ev_defer = [{"date": "2026-07-04", "cash": 2.0, "stock": 0.0, "before_price": 102.0}]
f = fields_for("2026-07-02", ev_defer)  # 排定 07-04(週六/休市)→ 生效 07-06
check("2e 排定日遇休市順延生效(07-04→07-06)", abs((f.get("div_5d") or 0) - 2.0) < 1e-9)

ev_stock = [{"date": "2026-07-08", "cash": 0.0, "stock": 1.5, "before_price": 104.0}]
f = fields_for("2026-07-02", ev_stock)
check("2f 除權(配股)不加現金", not f.get("div_5d"))

ev_amb = [{"date": "2026-07-08", "cash": 0.0, "stock": 0.0, "before_price": 104.0,
           "ambiguous": True}]
f = fields_for("2026-07-02", ev_amb)
check("2g 除權息合併列不調整(fail-open)", not f.get("div_5d"))

# 尺度換算:快取序列被更晚除權回溯調整(快取前收=52,官方 before_price=104 → factor=0.5)
h_adj = mk_hist(DAYS, [50, 50.5, 51, 51.5, 52, 50, 50.5, 51, 51.5, 52, 52.5])
f = btr._settle_on_calendar(h_adj, sorted(h_adj), cal, set(cal), "9998", "2026-07-02")
btr._attach_window_divs(f, ev_cash, h_adj, cal, "9998")
check("2h 尺度換算 factor=52/104=0.5 → div=2.5",
      abs((f.get("div_5d") or 0) - 2.5) < 1e-9, str(f.get("div_5d")))

ev_insane = [{"date": "2026-07-08", "cash": 5.0, "stock": 0.0, "before_price": 10000.0}]
f = fields_for("2026-07-02", ev_insane)  # factor=104/10000=0.0104 帶外 → 不換算,原額 5.0
check("2i 尺度帶外不換算(fail-open 原額)", abs((f.get("div_5d") or 0) - 5.0) < 1e-9)

f = fields_for("2026-07-02", [])
check("2j 無事件零觸碰(div_* 不存在)", "div_5d" not in f and "div_1d" not in f)

ev_future = [{"date": "2026-08-20", "cash": 9.0, "stock": 0.0, "before_price": 105.0}]
f = fields_for("2026-07-02", ev_future)
check("2k 日曆右緣外未來事件不掛", not f.get("div_5d"))

# 1d/21d 各自窗口獨立累計
ev_two = [{"date": "2026-07-03", "cash": 1.0, "stock": 0.0, "before_price": 101.0},
          {"date": "2026-07-09", "cash": 2.0, "stock": 0.0, "before_price": 100.0}]
f = fields_for("2026-07-02", ev_two)
check("2l div_1d 只含 (07-02,07-03] 的 1.0", abs((f.get("div_1d") or 0) - 1.0) < 1e-9)
check("2m div_5d 含兩筆 3.0", abs((f.get("div_5d") or 0) - 3.0) < 1e-9)

# ── 3. 退化窗守衛 ─────────────────────────────────────────────
# rec 日(07-10)該檔無 bar → 基準前推到 07-13;舊行為 settle=cal[i+1]=07-13=基準 → chg=0 假結算
h_gap = {d: p for d, p in mk_hist(DAYS, [100, 101, 102, 103, 104, 100, 101, 102,
                                          103, 104, 105]).items() if d != "2026-07-10"}
f = btr._settle_on_calendar(h_gap, sorted(h_gap), cal, set(cal), "9997", "2026-07-10")
check("3a 退化窗 1d 誠實待結(None)", f is not None and f.get("next_close") is None,
      str(f and {k: f[k] for k in ('base_date', 'next_close', 'date_1d')}))
check("3b 同窗 5d 正常結算(07-13 基準+5=…未及則 None,不得=基準日)",
      f is not None and (f.get("date_5d") is None or f["date_5d"] > f["base_date"]))

# ── 4. settlement_chg 無 div 鍵向後相容 ───────────────────────
p_legacy = {"close": 100.0, "close_5d": 103.0}
chg = btr.settlement_chg({"ticker": "X", "date": "d"}, {("X", "d"): p_legacy}, "5d")
check("4a 無 div 鍵=舊語意 3%", abs(chg - 0.03) < 1e-12)

# ── 5. FinMind 列解析(_fetch_finmind_dividends 的 kind 拆分邏輯,離線驗)──
rows = [
    {"date": "2026-07-08", "stock_or_cache_dividend": "息", "stock_and_cache_dividend": 5.0,
     "before_price": 104.0},
    {"date": "2026-06-29", "stock_or_cache_dividend": "權", "stock_and_cache_dividend": 4.54,
     "before_price": 82.4},
    {"date": "2026-07-01", "stock_or_cache_dividend": "除權息", "stock_and_cache_dividend": 3.0,
     "before_price": 100.0},
    {"date": "2026-07-02", "stock_or_cache_dividend": "除息", "stock_and_cache_dividend": 1.97,
     "before_price": 60.0},
]
import json as _json
import urllib.request as _ur


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def read(self):
        return _json.dumps(self._p).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


_orig_urlopen = _ur.urlopen
_ur.urlopen = lambda req, timeout=20: _FakeResp({"status": 200, "data": rows})
try:
    evs = btr._fetch_finmind_dividends("9999", "2026-06-01")
finally:
    _ur.urlopen = _orig_urlopen
by_date = {e["date"]: e for e in evs}
check("5a 息→cash", by_date["2026-07-08"]["cash"] == 5.0)
check("5b 權→stock 不進 cash", by_date["2026-06-29"]["stock"] == 4.54
      and by_date["2026-06-29"]["cash"] == 0.0)
check("5c 除權息合併列→ambiguous", by_date["2026-07-01"].get("ambiguous") is True)
check("5d 除息→cash", by_date["2026-07-02"]["cash"] == 1.97)

_ur.urlopen = lambda req, timeout=20: _FakeResp({"status": 402, "msg": "rate limit"})
try:
    evs = btr._fetch_finmind_dividends("9999", "2026-06-01")
finally:
    _ur.urlopen = _orig_urlopen
check("5e FinMind 非 200 → None(觸發 fallback)", evs is None)

# ── 6. 驗證者第17案迴歸(F4 畸形 payload/毒快取、F5 kind 精確比對、F1 chg_basis)──


def _finmind_with(payload):
    _ur.urlopen = lambda req, timeout=20: _FakeResp(payload)
    try:
        return btr._fetch_finmind_dividends("9999", "2026-06-01")
    finally:
        _ur.urlopen = _orig_urlopen

check("6a status200+data=字串 → None 不 crash(F4)",
      _finmind_with({"status": 200, "data": "unexpected"}) is None)
check("6b data 列非 dict → None 不 crash(F4)",
      _finmind_with({"status": 200, "data": [["2026-07-08", 5.0]]}) is None)
check("6c date 非 ISO 字串(int) → None 不進快取(F4)",
      _finmind_with({"status": 200, "data": [
          {"date": 20260708, "stock_or_cache_dividend": "息",
           "stock_and_cache_dividend": 5.0, "before_price": 104.0}]}) is None)

evs = _finmind_with({"status": 200, "data": [
    {"date": "2026-07-08", "stock_or_cache_dividend": "現金股利",
     "stock_and_cache_dividend": 5.0, "before_price": 104.0},
    {"date": "2026-07-09", "stock_or_cache_dividend": "股票股利",
     "stock_and_cache_dividend": 2.0, "before_price": 100.0}]})
check("6d 「現金股利」不被『股』子字串誤歸配股 → ambiguous(F5)",
      evs is not None and evs[0].get("ambiguous") is True
      and evs[0]["cash"] == 0.0 and evs[0]["stock"] == 0.0, str(evs))
check("6e 「股票股利」未知詞彙 → ambiguous 不錯加",
      evs is not None and evs[1].get("ambiguous") is True, str(evs))

# 6f 毒快取自癒:非法 date 已寫進快取 → 下輪讀回作廢重抓,不炸 _attach_window_divs
import tempfile
_orig_cache_file = btr.DIV_CACHE_FILE
_tmpd = tempfile.mkdtemp()
btr.DIV_CACHE_FILE = Path(_tmpd) / "div_cache.json"
btr.DIV_CACHE_FILE.write_text(_json.dumps({"9999": {
    "fetched_at": btr.datetime.now().isoformat(timespec="seconds"),
    "start": "2026-06-01",
    "events": [{"date": 20260708, "cash": 5.0, "stock": 0.0, "before_price": None}]}}))
_ur.urlopen = lambda req, timeout=20: _FakeResp({"status": 200, "data": [
    {"date": "2026-07-08", "stock_or_cache_dividend": "息",
     "stock_and_cache_dividend": 5.0, "before_price": 104.0}]})
_orig_sleep = btr.time.sleep
btr.time.sleep = lambda s: None
try:
    got = btr.fetch_dividends({"9999"}, "2026-06-01")
finally:
    _ur.urlopen = _orig_urlopen
    btr.time.sleep = _orig_sleep
healed = _json.loads(btr.DIV_CACHE_FILE.read_text())
btr.DIV_CACHE_FILE = _orig_cache_file
check("6f 毒快取(int date)作廢重抓自癒(F4)",
      got.get("9999") == [{"date": "2026-07-08", "cash": 5.0, "stock": 0.0,
                           "before_price": 104.0}]
      and healed["9999"]["events"][0]["date"] == "2026-07-08", str(got))
check("6g 自癒後快取事件通過 _events_valid", btr._events_valid(healed["9999"]["events"]))
check("6h _events_valid 拒非法(int date/非 dict/非 list)",
      not btr._events_valid([{"date": 20260708, "cash": 5.0}])
      and not btr._events_valid(["x"]) and not btr._events_valid("x"))

# 6i-6k chg_basis fact-version(F1):舊列補 legacy 章、backfill 蓋現行章
row_old = {"ticker": "9999", "date": "2026-07-02", "verdict_class": "buy",
           "label": "win", "chg": 0.03, "rule": btr.JUDGE_RULE_VERSION}
check("6i 舊列(有 chg 無章)一次性補 legacy 章 px",
      btr._reconcile_row(row_old, None) is True
      and row_old.get("chg_basis") == btr.CHG_BASIS_LEGACY, str(row_old))
check("6i2 已補章列冪等(不再改動)", btr._reconcile_row(row_old, None) is False)

row_bf = {"ticker": "9999", "date": "2026-07-02", "verdict_class": "buy",
          "label": "win", "chg": None, "rule": btr.JUDGE_RULE_VERSION}
p_bf = {("9999", "2026-07-02"): {"close": 100.0, "close_5d": 103.0}}
btr._reconcile_row(row_bf, None, p_bf)
check("6j 價格快取 backfill 蓋現行章 px+div",
      row_bf["chg"] == 0.03 and row_bf.get("chg_basis") == btr.CHG_BASIS, str(row_bf))

row_fr = {"ticker": "9999", "date": "2026-07-02", "verdict_class": "buy",
          "label": "win", "chg": None, "rule": btr.JUDGE_RULE_VERSION}
btr._reconcile_row(row_fr, {"chg": 0.05, "chg_basis": btr.CHG_BASIS}, None)
check("6k fresh backfill 沿用 fresh 的章",
      row_fr["chg"] == 0.05 and row_fr.get("chg_basis") == btr.CHG_BASIS)

print()
if FAILS:
    print(f"❌ {len(FAILS)} 段失敗: {FAILS}")
    sys.exit(1)
print("✅ 全部通過")
sys.exit(0)
