#!/usr/bin/env python3
"""signal_ledger 結算端 CA 守衛(ca_settlement_guard)迴歸測試。

背景(2026-07-17 price_integrity 稽核前置):score() 事後報酬兩端皆 raw 未還原價,
持有窗跨分割/減資/大額配股=機械假報酬(0050 2025-06 1:4 分割 raw -74.8% 假懸崖同款)。
本檔凍結:①TW gap>10.5% 嫌疑必抓、≤10.5% 除息=已知盲區不誤抓 ②US splits∪大額配息
(events 單源;gap 腿因 Yahoo close 是 split-adjusted+US 無漲跌幅=截尾偏差,驗證者 F1 移除)
③day-0 邊界市場分歧(TW 嚴格晚於/US 含當日) ④抓取失敗=unknown 非 clean
(fail-closed) ⑤壞列+零hit=不能證明乾淨 ⑥快取(同 code 不重抓/失敗不入快取下次重試)
⑦score() 接線(排除統計+逐組計數+ca_guard 模式標示+全組排除仍有條目)
⑧驗證者第15案 F1-F4 迴歸 probes(第 6 段)。

fixture 全部合成注入,零網路、零觸真帳本(rows= 顯式傳入)。
用法: python3 scripts/test_ca_settlement_guard.py   (exit 0=全過)
"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intel import ca_settlement_guard as g
from intel import signal_ledger

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


def _series(pairs):
    return [{"date": d, "close": c} for d, c in pairs]


# ── 1. scan_gaps 基本簽名 ─────────────────────────────────────────────
clean = _series([("2026-07-01", 100), ("2026-07-02", 103), ("2026-07-03", 99)])
split = _series([("2026-07-01", 100), ("2026-07-02", 25)])   # 1:4 分割 raw -75%
r = g.scan_gaps(clean, g.TW_GAP)
ok("1a 乾淨序列零 hit 零壞列", r["hits"] == [] and r["n_bad"] == 0)
r = g.scan_gaps(split, g.TW_GAP)
ok("1b 分割 -75% 必中且日期正確", len(r["hits"]) == 1 and r["hits"][0]["date"] == "2026-07-02")
r = g.scan_gaps(_series([("2026-07-01", 100), ("2026-07-02", 210)]), g.TW_GAP)
ok("1c 減資形狀 +110% 必中", len(r["hits"]) == 1)
r = g.scan_gaps(_series([("2026-07-01", 100), ("2026-07-02", 95)]), g.TW_GAP)
ok("1d 除息 -5% 不觸發(文件明載盲區,非 bug)", r["hits"] == [])
r = g.scan_gaps([{"date": "2026-07-01", "close": "垃圾"}] + clean, g.TW_GAP)
ok("1e 壞列被計數不炸", r["n_bad"] == 1 and r["hits"] == [])
r = g.scan_gaps(_series([("2026-07-01", 100), ("2026-07-02", 0), ("2026-07-03", 99)]), g.TW_GAP)
ok("1f close=0 當壞列不當分割", r["n_bad"] == 1)

# ── 2. TW 狀態判定(注入 fetch) ────────────────────────────────────────
TW_SPLIT = _series([("2026-06-25", 100), ("2026-06-26", 101), ("2026-07-01", 25),
                    ("2026-07-02", 26)])


def fetch_tw_split(code, start, end):
    return TW_SPLIT


def fetch_none(*a):
    return None


def fetch_us_none(*a):
    return None, None


def mk(fetch_tw=fetch_none, fetch_us=fetch_us_none, path=None, today="2026-07-10"):
    return g.make_ca_check_fn(today=today, cache_path=path or os.path.join(
        tempfile.mkdtemp(), "c.json"), fetch_tw=fetch_tw, fetch_us=fetch_us, sleep_s=0)


chk = mk(fetch_tw=fetch_tw_split)
ok("2a TW 窗內分割=suspect", chk("2330", "2026-06-26")["status"] == "suspect")
ok("2b TW 訊號在分割後=clean", chk("2330", "2026-07-01")["status"] == "clean")
# day-0:hit 日=訊號日(收盤後記錄,已反映)→ TW 不算污染;前一日訊號則算
ok("2c TW day-0 hit 不算(嚴格晚於)", chk("2330", "2026-07-01")["status"] == "clean")
ok("2d TW hit 晚於訊號日=suspect", chk("2330", "2026-06-30")["status"] == "suspect")
chk = mk(fetch_tw=lambda c, s, e: _series([("2026-06-25", 100), ("2026-07-02", 95)]))
ok("2e TW 小 gap 序列=clean(盲區誠實)", chk("2330", "2026-06-26")["status"] == "clean")
chk = mk(fetch_tw=fetch_none)
ok("2f TW 抓取失敗=unknown 非 clean", chk("2330", "2026-06-26")["status"] == "unknown")
chk = mk(fetch_tw=lambda c, s, e: _series([("2026-06-25", 100)]))
ok("2g 序列<2列不能掃=unknown", chk("2330", "2026-06-26")["status"] == "unknown")
chk = mk(fetch_tw=lambda c, s, e: [{"date": "2026-06-25", "close": "bad"},
                                   {"date": "2026-06-26", "close": 100},
                                   {"date": "2026-06-27", "close": 101}])
ok("2h 壞列+零hit=unknown(不能證明乾淨)", chk("2330", "2026-06-26")["status"] == "unknown")

# ── 3. US 狀態判定 ────────────────────────────────────────────────────
US_ROWS = _series([("2026-06-25", 200.0), ("2026-06-26", 202.0), ("2026-06-27", 204.0)])


def us_fetch(events):
    def f(sym, start, end):
        return US_ROWS, events
    return f


chk = mk(fetch_us=us_fetch({"splits": ["2026-06-26"], "dividends": []}))
ok("3a US splits 事件=suspect", chk("NVDA", "2026-06-25")["status"] == "suspect")
ok("3b US 訊號在事件後=clean", chk("NVDA", "2026-06-27")["status"] == "clean")
ok("3c US day-0 含當日(>=)=suspect", chk("NVDA", "2026-06-26")["status"] == "suspect")
chk = mk(fetch_us=us_fetch({"splits": [], "dividends": [{"date": "2026-06-27", "amount": 10.0}]}))
ok("3d US 大額配息(5%)=suspect", chk("NVDA", "2026-06-25")["status"] == "suspect")
chk = mk(fetch_us=us_fetch({"splits": [], "dividends": [{"date": "2026-06-27", "amount": 1.0}]}))
ok("3e US 小額配息(0.5%)=clean", chk("NVDA", "2026-06-25")["status"] == "clean")
# F1:Yahoo US close 是 split-adjusted(真分割無懸崖可掃)且 US 無漲跌幅限制,
# gap 腿會把財報崩跌/暴漲當 CA 排除=結果相關截尾(META 2022-02-03 -26.4% 同款)→已移除。
chk = mk(fetch_us=lambda s, a, b: (
    _series([("2026-06-25", 200.0), ("2026-06-26", 90.0)]), {"splits": [], "dividends": []}))
ok("3f US 極端行情無事件=clean(F1:gap 腿截尾偏差已移除)",
   chk("NVDA", "2026-06-25")["status"] == "clean")
chk = mk(fetch_us=fetch_us_none)
ok("3g US 抓取失敗=unknown", chk("NVDA", "2026-06-25")["status"] == "unknown")

# ── 4. 快取行為 ──────────────────────────────────────────────────────
calls = {"n": 0}


def counting_fetch(code, start, end):
    calls["n"] += 1
    return TW_SPLIT


tmp = os.path.join(tempfile.mkdtemp(), "cache.json")
chk = mk(fetch_tw=counting_fetch, path=tmp)
chk("2330", "2026-06-26")
chk("2330", "2026-06-30")
ok("4a 同 code 記憶體 memo 只抓一次", calls["n"] == 1)
chk2 = mk(fetch_tw=counting_fetch, path=tmp)
chk2("2330", "2026-06-26")
ok("4b 磁碟快取跨實例命中不重抓", calls["n"] == 1)
# 較早訊號日超出快取窗 → 需重抓且新窗涵蓋較早起點
chk2("2330", "2026-05-01")
ok("4c 更早訊號日觸發擴窗重抓", calls["n"] == 2)
fails = {"n": 0}


def failing_fetch(code, start, end):
    fails["n"] += 1
    return None


tmp2 = os.path.join(tempfile.mkdtemp(), "cache.json")
chk = mk(fetch_tw=failing_fetch, path=tmp2)
chk("2330", "2026-06-26")
chk3 = mk(fetch_tw=failing_fetch, path=tmp2)
chk3("2330", "2026-06-26")
ok("4d 失敗不入磁碟快取,下次重試", fails["n"] == 2)
ok("4e 壞 sig_date=unknown 不炸", mk()("2330", "not-a-date")["status"] == "unknown")

# ── 5. score() 接線 ───────────────────────────────────────────────────
TODAY = datetime.date(2026, 7, 10)
ROWS = [
    {"date": "2026-06-20", "code": "1101", "source": "srcA", "level": "red",
     "price_at_signal": 100.0},
    {"date": "2026-06-20", "code": "2330", "source": "srcA", "level": "red",
     "price_at_signal": 100.0},
    {"date": "2026-06-21", "code": "9999", "source": "srcB", "level": "yellow",
     "price_at_signal": 50.0},
]


def price_fn(code):
    return {"1101": 25.0, "2330": 110.0, "9999": 55.0}[code]  # 1101 = 假 -75%(窗內分割)


def fake_ca(code, sig_date):
    return {"1101": {"status": "suspect", "why": "split"},
            "2330": {"status": "clean", "why": ""},
            "9999": {"status": "unknown", "why": "fetch failed"}}[code]


res = signal_ledger.score(rows=ROWS, price_fn=price_fn, today=TODAY, ca_check_fn=fake_ca)
ok("5a ca_guard=on 標示", res["ca_guard"] == "on")
ok("5b suspect/unknown 排除統計", res["n_scored"] == 1
   and res["n_ca_suspect"] == 1 and res["n_ca_unknown"] == 1)
gA = res["groups"]["srcA|red"]
ok("5c 逐組計數:srcA 只剩乾淨 1 筆+suspect 1", gA["n"] == 1 and gA["n_ca_suspect"] == 1)
gB = res["groups"]["srcB|yellow"]
ok("5d 全組被排除仍有條目(計數不消失)", gB["n"] == 0 and gB["n_ca_unknown"] == 1
   and gB["status"] == "insufficient_data")
det = {d["code"]: d for d in res["detail"]}
ok("5e detail 保留排除列+ca_status 標示", det["1101"]["ca_status"] == "suspect"
   and det["1101"]["outcome_pct"] == -75.0 and det["2330"]["ca_status"] == "clean")
res_off = signal_ledger.score(rows=ROWS, price_fn=price_fn, today=TODAY, ca_check_fn=None)
ok("5f 顯式關守衛=off+全列 unchecked+行為同舊版", res_off["ca_guard"] == "off"
   and res_off["n_scored"] == 3
   and all(d["ca_status"] == "unchecked" for d in res_off["detail"])
   and res_off["n_ca_suspect"] == 0)
ok("5g off 模式逐組計數仍存在為 0(schema 穩定)",
   res_off["groups"]["srcA|red"]["n_ca_suspect"] == 0)


def bad_ca(code, sig_date):
    raise RuntimeError("guard exploded")


res_bad = signal_ledger.score(rows=ROWS, price_fn=price_fn, today=TODAY, ca_check_fn=bad_ca)
ok("5h 守衛拋錯=該列 unknown 非 clean(fail-closed)", res_bad["n_scored"] == 0
   and res_bad["n_ca_unknown"] == 3)


def weird_ca(code, sig_date):
    return {"status": "totally-fine"}


res_w = signal_ledger.score(rows=ROWS, price_fn=price_fn, today=TODAY, ca_check_fn=weird_ca)
ok("5i 守衛回怪值=unknown(不默認乾淨)", res_w["n_ca_unknown"] == 3)

# 誠實閘 1/2 不被守衛破壞:8 筆同日乾淨列 → 樣本夠但日多樣性不足
many = [{"date": "2026-06-20", "code": f"90{i:02d}", "source": "srcC", "level": "red",
         "price_at_signal": 100.0} for i in range(8)]
res_m = signal_ledger.score(rows=many, price_fn=lambda c: 105.0, today=TODAY,
                            ca_check_fn=lambda c, d: {"status": "clean"})
ok("5j 既有兩道閘語意不變(day diversity 仍擋)",
   res_m["groups"]["srcC|red"]["status"] == "insufficient_day_diversity")

# ── 6. 驗證者第15案迴歸(F1-F4 probes,對應 verifier_ca_settlement_guard_report) ──
# 6a F2 Probe A:訊號前 hit 存在時,訊號後壞列不可被繞過(壞列=不能證明乾淨的不變量)
chk = mk(fetch_tw=lambda c, s, e: [
    {"date": "2026-02-01", "close": 100}, {"date": "2026-02-02", "close": 50},
    {"date": "2026-06-19", "close": 52}, {"date": "2026-07-01", "close": None},
    {"date": "2026-07-02", "close": "junk"}])
ok("6a F2 訊號前hit+訊號後壞列=unknown 非 clean",
   chk("2330", "2026-06-20")["status"] == "unknown")

# 6b F3 Probe B:連休中記的訊號(price_at_signal=連休前舊收盤),pad=16 蓋春節 9-11 天,
# 復市首日 CA 必須抓到(舊 pad=7 時分母落窗外→false clean,最典型污染組合)
CLOSURE = [("2026-02-10", 99.0), ("2026-02-13", 100.0),
           ("2026-02-24", 25.0), ("2026-02-25", 26.0)]


def fetch_closure(code, start, end):
    return [{"date": d, "close": c} for d, c in CLOSURE if start <= d <= end]


chk = mk(fetch_tw=fetch_closure, today="2026-03-01")
ok("6b F3 連休中訊號+復市首日分割=suspect(pad16 蓋春節)",
   chk("2330", "2026-02-21")["status"] == "suspect")

# 6c F3 同型洞:序列首列晚於訊號日(IPO/資料起點)=分母缺席,不可證乾淨
chk = mk(fetch_tw=lambda c, s, e: _series([("2026-06-25", 100), ("2026-06-26", 101)]))
ok("6c F3 序列首列晚於訊號日=unknown(IPO/資料起點洞)",
   chk("2330", "2026-06-01")["status"] == "unknown")

# 6d F4 Probe C:失敗 code 本輪只真抓一次(配額最緊時不可放大請求量)
fails6 = {"n": 0}


def failing6(code, start, end):
    fails6["n"] += 1
    return None


chk = mk(fetch_tw=failing6)
for _ in range(4):
    chk("2330", "2026-06-26")
ok("6d F4 失敗 code 本輪只真抓一次", fails6["n"] == 1)

# 6e F4 Probe D:memo 失敗項不遮蔽本可涵蓋的磁碟有效項(白丟樣本+多打一次)
calls6e = {"n": 0}


def flaky6e(code, start, end):
    calls6e["n"] += 1
    return TW_SPLIT if calls6e["n"] == 1 else None


tmp6e = os.path.join(tempfile.mkdtemp(), "cache.json")
chk = mk(fetch_tw=flaky6e, path=tmp6e)
chk("2330", "2026-06-26")                 # 成功入磁碟
chk6e = mk(fetch_tw=flaky6e, path=tmp6e)
r_wide = chk6e("2330", "2026-05-01")      # 擴窗重抓→失敗→memo failed
r_narrow = chk6e("2330", "2026-06-26")    # 磁碟本可涵蓋:不得被 memo 失敗項遮蔽
ok("6e F4 memo失敗項不遮蔽有效磁碟快取", r_wide["status"] == "unknown"
   and r_narrow["status"] == "suspect" and calls6e["n"] == 2)

# 6f 半壞快取(suspect_dates 非 list)不採信→重抓,不逐字元迭代出垃圾判定(Notes PROBE F)
tmp6f = os.path.join(tempfile.mkdtemp(), "cache.json")
with open(tmp6f, "w", encoding="utf-8") as f:
    json.dump({"2330": {"start": "2026-01-01", "end": "2026-07-10", "ok": True,
                        "suspect_dates": "2026-07-01", "n_bad": 0,
                        "first_date": "2026-06-01"}}, f)
calls6f = {"n": 0}


def counting6f(code, start, end):
    calls6f["n"] += 1
    return TW_SPLIT


chk = mk(fetch_tw=counting6f, path=tmp6f)
r6f = chk("2330", "2026-06-26")
ok("6f 半壞快取不採信→重抓出正確判定", calls6f["n"] == 1 and r6f["status"] == "suspect")

# 6g 舊 schema 快取(無 first_date,F3 前寫入)不採信→重抓
tmp6g = os.path.join(tempfile.mkdtemp(), "cache.json")
with open(tmp6g, "w", encoding="utf-8") as f:
    json.dump({"2330": {"start": "2026-01-01", "end": "2026-07-10", "ok": True,
                        "suspect_dates": [], "n_bad": 0}}, f)
calls6g = {"n": 0}


def counting6g(code, start, end):
    calls6g["n"] += 1
    return TW_SPLIT


chk = mk(fetch_tw=counting6g, path=tmp6g)
chk("2330", "2026-06-26")
ok("6g 舊 schema 快取(無 first_date)不採信→重抓", calls6g["n"] == 1)

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n{len(PASS) - n_fail}/{len(PASS)} passed")
sys.exit(1 if n_fail else 0)
