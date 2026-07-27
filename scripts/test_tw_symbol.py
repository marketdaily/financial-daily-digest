#!/usr/bin/env python3
"""台股/美股代碼判別單一事實來源迴歸測試(2026-07-27 isdigit 家族根治)。

背景:00981A(字母尾碼主動式 ETF)被「全數字」判別 str.isdigit() 誤當美股 →
①prompt 層台股早盤鐵則不注入(hfks996 07-22/27 兩鍋第一層根因)
②deterministic fallback 卡/精簡卡去 us_market 查表 → 拿不到報價變「無即時報價」卡
③tw_n/us_n 計數與美股清單過濾皆錯。
根治:analyzer._is_tw_symbol()(首字數字=台股,同原 L1236 權威慣例)收斂全部 6 處
錯誤判別+4 處既有首字判別。本檔凍結 helper 語意與行情路由行為。

用法: .venv/bin/python scripts/test_tw_symbol.py   (exit 0=全過)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MD_SKIP_ADHOC_FETCH", "1")
import analyzer  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


# ── ① helper 真值表 ──────────────────────────────────────────
check("T1 00981A=台股(字母尾碼主動式ETF,實鍋案例)", analyzer._is_tw_symbol("00981A"))
check("T2 2330=台股", analyzer._is_tw_symbol("2330"))
check("T3 0050=台股(ETF)", analyzer._is_tw_symbol("0050"))
check("T4 AAPL=美股", not analyzer._is_tw_symbol("AAPL"))
check("T5 BRK.B=美股(帶點)", not analyzer._is_tw_symbol("BRK.B"))
check("T6 空字串非台股", not analyzer._is_tw_symbol(""))
check("T7 None 非台股", not analyzer._is_tw_symbol(None))

# ── ② deterministic fallback 卡行情路由(舊 bug:00981A 查 us_market 變無報價卡) ──
DATA = {
    "tw_market": {"00981A": {"price": 15.2, "change_pct": 1.3, "name": "統一台股增長主動式"}},
    "us_market": {"NVDA": {"price": 180.0, "change_pct": 0.5, "name": "NVIDIA"}},
    "technicals": {},
}
card = analyzer._deterministic_signal_card("00981A", DATA, {"tw_will_open_today": True})
check("D1 00981A fallback 卡拿到 tw_market 報價(非「無即時報價」)",
      "無即時報價" not in card and "15.2" in card)
check("D2 00981A fallback 卡走台股措辭(元+今早開盤窗口)",
      "元" in card and "今早 9:00 開盤" in card)
card_us = analyzer._deterministic_signal_card("NVDA", DATA, {"us_will_open_tonight": True})
check("D3 美股卡路由不受影響(NVDA 走 us_market,$ 計價有報價)",
      "$180" in card_us and "無即時報價" not in card_us)

# ── ③ 精簡卡同路由 ──
compact = analyzer._compact_overflow_card("00981A", DATA, {"tw_will_open_today": True})
check("C1 00981A 精簡卡拿到 tw_market 報價", "15.2" in compact)

# ── ④ 單一事實來源:stock_names.is_tw_symbol 為 canonical ──
import stock_names  # noqa: E402
check("S1 analyzer 委派 stock_names.is_tw_symbol 結果一致",
      all(stock_names.is_tw_symbol(s) == analyzer._is_tw_symbol(s)
          for s in ("00981A", "2330", "AAPL", "", None)))
check("S2 槓桿/反向/債券字母尾碼皆台股(00631L/00632R/00400A)",
      all(stock_names.is_tw_symbol(s) for s in ("00631L", "00632R", "00400A")))

# ── ⑤ data_fetcher:TWSE 全表解析不丟字母尾碼(舊 isdigit 丟 127 檔) ──
import data_fetcher as df  # noqa: E402
from datetime import datetime as _dt  # noqa: E402


class _R:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


orig_get = df.requests.get
df._TWSE_CACHE, df._TWSE_CACHE_TIME = {}, None
_rows = [
    {"Code": "2330", "Name": "台積電", "ClosingPrice": "1000", "Change": "10", "Date": "1150727"},
    {"Code": "00631L", "Name": "元大台灣50正2", "ClosingPrice": "200", "Change": "-2", "Date": "1150727"},
]
try:
    df.requests.get = lambda *a, **k: _R(_rows)
    twse = df._fetch_twse_all()
finally:
    df.requests.get = orig_get
    df._TWSE_CACHE, df._TWSE_CACHE_TIME = {}, None
check("F1 TWSE 解析保留字母尾碼商品(00631L 正2)",
      twse.get("00631L", {}).get("price") == 200.0)
check("F2 TWSE 解析純數字照常(2330)", "2330" in twse)

# ── ⑥ FinMind 救援層(00981A 級別:TWSE/TPEX/Yahoo 三源全 miss) ──
def _fm_get(url, params=None, **k):
    if (params or {}).get("dataset") == "TaiwanStockPrice":
        return _R({"data": [{"date": _dt.now().strftime("%Y-%m-%d"),
                             "close": 27.53, "spread": -0.01}]})
    return _R({"data": [{"stock_name": "統一台股增長主動式"}]})


orig_tok = os.environ.get("FINMIND_TOKEN")
orig_yahoo = df._tw_stocks_via_yahoo
df._TW_NAME_CACHE, df._TW_NAME_CACHE_TIME = {"2330": "台積電"}, _dt.now()
os.environ["FINMIND_TOKEN"] = "fake-token"
try:
    df.requests.get = _fm_get
    df._tw_stocks_via_yahoo = lambda *a, **k: {}
    resolved = {}
    df._LAST_TW_MISSING.clear()
    df._rescue_missing_tw(["00981A"], resolved, {}, {})
finally:
    df.requests.get = orig_get
    df._tw_stocks_via_yahoo = orig_yahoo
check("F3 00981A 進救援名單且 FinMind 補到報價",
      resolved.get("00981A", {}).get("price") == 27.53)
check("F4 FinMind 名稱補齊(TaiwanStockInfo)",
      resolved.get("00981A", {}).get("name") == "統一台股增長主動式")
check("F5 補到後不進 missing 告警", "00981A" not in df._LAST_TW_MISSING)

# ── ⑦ FinMind 過期資料 fail-closed(不寄過期價,照常進告警) ──
try:
    df.requests.get = lambda url, params=None, **k: _R(
        {"data": [{"date": "2026-01-05", "close": 9.9, "spread": 0}]})
    df._tw_stocks_via_yahoo = lambda *a, **k: {}
    resolved2 = {}
    df._LAST_TW_MISSING.clear()
    df._rescue_missing_tw(["00981A"], resolved2, {}, {})
    stale_missing = list(df._LAST_TW_MISSING)
finally:
    df.requests.get = orig_get
    df._tw_stocks_via_yahoo = orig_yahoo
    df._LAST_TW_MISSING.clear()
    if orig_tok is None:
        os.environ.pop("FINMIND_TOKEN", None)
    else:
        os.environ["FINMIND_TOKEN"] = orig_tok
check("F6 逾 7 天資料不收(不寄過期價)且進 missing 告警",
      not resolved2 and "00981A" in stale_missing)

ok = all(r for _, r in RESULTS)
print(f"\n{'✅ 全過' if ok else '❌ 有失敗'} ({sum(1 for _, r in RESULTS if r)}/{len(RESULTS)})")
sys.exit(0 if ok else 1)
