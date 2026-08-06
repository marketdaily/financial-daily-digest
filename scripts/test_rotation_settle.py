#!/usr/bin/env python3
"""rotation_settle.py 迴歸測試(2026-08-06 補測——換股配對帳本週結算 07-22 上線,

commit fa39e71 從未附測試檔;memory `project_rotation_advice` 聲稱的「五案例+settle
fixture 全過」查無實據(git log/grep 全庫零命中),此檔補上這個缺口)。

`rotation_settle.py` 每週日 16:00(edge_cuts_weekly.sh)結算 rotation_pairs.jsonl
未結列、當場改寫 tracked 檔 commit+push origin。這是一支會自動寫回生產 repo 的腳本,
零測試覆蓋=夜巡 selftest.sh 抓不到回歸,結算邏輯壞掉不會有人發現(帳本悄悄長歪)。

凍結語意:
- fwd5():資料不足(空 dict / 尾端不足 5 個交易日)回 None,不拋例外;錨點缺席(如週末)
  時 bisect_left 正確取其後第一個可用交易日。
- settle():冪等(已結算列原封不動,即使重算會得到不同數字)/ 未滿 9 天不結(邊界=剛好
  9 天結、剛好 8 天不結)/ 任一腳價格拿不到就跳過留待下週 / date 欄位型別漂移(非合法
  ISO 字串)跳過不崩潰,不拖垮同批其他健康列 / newly 只計本輪新結的筆數。
- parse_rows():截斷/壞掉的單行(json.loads 失敗)印警告跳過,不讓它拖垮整批(2026-08-06
  驗證者分離 F3——process 被 kill 在寫入中途是這支自動改寫 tracked 檔的腳本最該防的形狀)。
- dedupe_unsettled():未結算列 (date,from,to) 重複時只留第一筆,避免雙倍計入 wins/rel_avg
  (F4);已結算列是歷史事實,一律不去重。
- should_alert():n_before < 30 <= n_done 才觸發(首度跨線一次性,不重複推播)。

用法: python3 scripts/test_rotation_settle.py   (exit 0=全過)

驗證者分離(2026-08-06,全新 context,general-purpose agent):SOUND-WITH-CORRECTIONS,
4 findings 全修(F1 HIGH 8/9 天邊界零鑑別力、F2 MEDIUM fwd5 錨點斷言是恆真式、F3 MEDIUM
main() 對壞列零防禦會讓整批結算崩潰、F4 MINOR 重複列雙倍計入統計)。報告落盤
`~/autonomous/capabilities/tests/verifier_report_rotation_settle.md`,
check_report.py 驗收 exit 0,verdict 入 state/verifier_ledger.jsonl。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


import rotation_settle as rs  # noqa: E402

TODAY = date.today()


def d(n_days_ago):
    return (TODAY - timedelta(days=n_days_ago)).isoformat()


def daterange(start_days_ago, n):
    """回傳從 start_days_ago 天前開始、往今天方向連續 n 個交易日日期(略過週末近似值即可,
    測試只需要單調遞增的字串序列,非真實交易日曆)。"""
    base = TODAY - timedelta(days=start_days_ago)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


# ── fwd5() 單元 ─────────────────────────────────────────────────
check("fwd5: 空 dict 回 None", rs.fwd5({}, "2026-01-01") is None)

closes = {dt: 100.0 + i for i, dt in enumerate(daterange(20, 15))}
anchor = daterange(20, 15)[2]
expected = (closes[daterange(20, 15)[7]] / closes[anchor] - 1) * 100
check("fwd5: 正常計算(第 i 天到 i+5 天)", abs(rs.fwd5(closes, anchor) - expected) < 1e-9)

tail_dates = daterange(20, 15)
short_closes = {dt: 100.0 for dt in tail_dates[-4:]}  # 不足 5 個交易日尾端
check("fwd5: 尾端不足 5 個交易日回 None", rs.fwd5(short_closes, tail_dates[-4]) is None)

weekend_gap = dict(closes)
_all_dates = daterange(20, 15)
_missing_date, _next_date = _all_dates[5], _all_dates[6]
del weekend_gap[_missing_date]  # 模擬錨點剛好落在非交易日(週末/國定假日)
check("fwd5: 錨點缺席時(bisect_left)取其後第一個可用交易日,結果與直接查該日相同",
      rs.fwd5(weekend_gap, _missing_date) == rs.fwd5(weekend_gap, _next_date))


# ── settle() 單元 ───────────────────────────────────────────────
def make_chart_fn(mapping):
    def _fn(sym, _s, _e):
        return mapping.get(sym)
    return _fn


# case 1: 已結算列不動,即使重算會得到不同數字
rows1 = [{"date": d(30), "from": "A", "to": "B", "settled": True,
          "from_ret": 1.11, "to_ret": 2.22, "rel": 1.11, "win": True}]
chart1 = make_chart_fn({
    "A": {dt: 999.0 for dt in daterange(35, 15)},
    "B": {dt: 1.0 for dt in daterange(35, 15)},
})
out1, newly1 = rs.settle(rows1, chart1)
check("settle: 已結算列冪等不動(newly=0)", newly1 == 0)
check("settle: 已結算列數值未被覆寫", out1[0]["from_ret"] == 1.11 and out1[0]["to_ret"] == 2.22)

# case 2: 未滿 9 天不結(即使價格資料齊全)
rows2 = [{"date": d(5), "from": "A", "to": "B"}]
closes_full = {dt: 100.0 + i for i, dt in enumerate(daterange(15, 20))}
chart2 = make_chart_fn({"A": closes_full, "B": closes_full})
out2, newly2 = rs.settle(rows2, chart2)
check("settle: 未滿 9 天不結", newly2 == 0 and not out2[0].get("settled"))


def _settleable_chart(anchor: str):
    """給定錨點日期,建出兩腳皆有 10 天連續收盤資料的 chart_fn(供邊界測試共用)。"""
    fc, tc = {}, {}
    for i in range(10):
        dt = (date.fromisoformat(anchor) + timedelta(days=i)).isoformat()
        fc[dt] = 100.0 + i * 0.5
        tc[dt] = 100.0 + i * 2.0
    return make_chart_fn({"A": fc, "B": tc})


# case 2b: 8/9 天邊界(F1——原本 21 個斷言對這條邊界零鑑別力,off-by-one `<9`→`<8`
# 全數通過;這裡直接鎖死邊界兩側行為)
anchor9 = d(9)
rows_b9 = [{"date": anchor9, "from": "A", "to": "B"}]
out_b9, newly_b9 = rs.settle(rows_b9, _settleable_chart(anchor9))
check("settle: 剛好滿 9 天(邊界)→ 應結算", newly_b9 == 1 and out_b9[0].get("settled") is True)

anchor8 = d(8)
rows_b8 = [{"date": anchor8, "from": "A", "to": "B"}]
out_b8, newly_b8 = rs.settle(rows_b8, _settleable_chart(anchor8))
check("settle: 剛好差 1 天不滿 9 天(邊界)→ 不應結算",
      newly_b8 == 0 and not out_b8[0].get("settled"))

# case 3: 滿 9 天 + 兩腳資料齊全 → 正確結算(win=True:to 漲得比 from 多)
anchor3 = d(12)
from_closes = {}
to_closes = {}
base_dates = [(date.fromisoformat(anchor3) + timedelta(days=i)).isoformat() for i in range(10)]
for i, dt in enumerate(base_dates):
    from_closes[dt] = 100.0 + i * 0.5   # from 漲 2.5% over 5 步
    to_closes[dt] = 100.0 + i * 2.0     # to 漲 10% over 5 步
rows3 = [{"date": anchor3, "from": "A", "to": "B"}]
chart3 = make_chart_fn({"A": from_closes, "B": to_closes})
out3, newly3 = rs.settle(rows3, chart3)
r3 = out3[0]
check("settle: 滿 9 天且資料齊全 → 新結 1 筆", newly3 == 1)
check("settle: settled 欄位正確寫入", r3.get("settled") is True)
check("settle: win=True(to 漲得比 from 多)", r3.get("win") is True)
check("settle: rel = to_ret - from_ret", abs(r3["rel"] - (r3["to_ret"] - r3["from_ret"])) < 1e-6)

# case 3b: win=False(from 反而漲更多)
rows3b = [{"date": anchor3, "from": "A", "to": "B"}]
chart3b = make_chart_fn({"A": to_closes, "B": from_closes})  # 對調
out3b, _ = rs.settle(rows3b, chart3b)
check("settle: win=False(from 漲得比 to 多時)", out3b[0].get("win") is False)

# case 4: 缺 date 欄位 → 跳過不崩潰
rows4 = [{"from": "A", "to": "B"}]
out4, newly4 = rs.settle(rows4, chart3)
check("settle: 缺 date 欄位不崩潰且不結算", newly4 == 0 and not out4[0].get("settled"))

# case 5: 任一腳價格拿不到(chart_fn 回 None/空)→ 跳過留待下週,不崩潰
rows5 = [{"date": anchor3, "from": "A", "to": "MISSING"}]
chart5 = make_chart_fn({"A": from_closes})  # B/MISSING 查無資料
out5, newly5 = rs.settle(rows5, chart5)
check("settle: 一腳價格缺失時不結算不崩潰", newly5 == 0 and not out5[0].get("settled"))

# case 6: 混合批次 —— newly 只計本輪新結筆數,已結列不重複計入
rows6 = [
    {"date": d(30), "from": "A", "to": "B", "settled": True, "win": True, "rel": 5.0},
    {"date": anchor3, "from": "A", "to": "B"},
    {"date": d(3), "from": "A", "to": "B"},  # 未滿 9 天
]
out6, newly6 = rs.settle(rows6, chart3)
check("settle: 混合批次 newly 只算本輪新結(=1)", newly6 == 1)
check("settle: 混合批次已結列與未滿天數列皆維持原狀",
      out6[0]["settled"] is True and not out6[2].get("settled"))

# case 7(F3):date 欄位存在但型別漂移/髒資料(非合法 ISO 字串)→ 跳過不崩潰,不拖垮其他列
rows7 = [{"date": "N/A", "from": "A", "to": "B"}, {"date": anchor3, "from": "A", "to": "B"}]
out7, newly7 = rs.settle(rows7, chart3)
check("settle: date 欄位型別漂移('N/A')不崩潰且不結算該列",
      newly7 == 1 and not out7[0].get("settled") and out7[1].get("settled") is True)


# ── parse_rows()(F3):截斷/壞掉的單行 ────────────────────────────
lines_with_truncation = [
    '{"date": "2026-01-01", "from": "A", "to": "B"}\n',
    '{"date": "2026-01-02", "from": "A"\n',  # 截斷(process 被 kill 在寫入中途的典型形狀)
    '{"date": "2026-01-03", "from": "A", "to": "B"}\n',
    '\n',  # 空行應被忽略,非壞列
]
rows_parsed, n_bad = rs.parse_rows(lines_with_truncation)
check("parse_rows: 截斷行被跳過且計入 bad,不影響其他健康列", len(rows_parsed) == 2 and n_bad == 1)


# ── dedupe_unsettled()(F4):(date,from,to) 重複的未結算列只保留一筆 ──
rows_dup = [
    {"date": "2026-01-01", "from": "A", "to": "B"},
    {"date": "2026-01-01", "from": "A", "to": "B"},  # 未結算重複 key → 應被濾掉
    {"date": "2026-01-01", "from": "A", "to": "C", "settled": True},
    {"date": "2026-01-01", "from": "A", "to": "C", "settled": True},  # 已結算列(歷史事實)不去重
]
out_dedup, n_dropped = rs.dedupe_unsettled(rows_dup)
check("dedupe_unsettled: 未結算重複列只留一筆(dropped=1)", n_dropped == 1)
check("dedupe_unsettled: 已結算重複列不動(歷史事實保留兩筆)",
      len(out_dedup) == 3 and sum(1 for r in out_dedup if r.get("settled")) == 2)


# ── should_alert() 門檻穿越 ─────────────────────────────────────
check("should_alert: 29→30 首度跨線觸發", rs.should_alert(29, 30) is True)
check("should_alert: 30→31 已跨線過不重複觸發", rs.should_alert(30, 31) is False)
check("should_alert: 25→32 一次躍過門檻仍觸發", rs.should_alert(25, 32) is True)
check("should_alert: 30→30 本輪零新結不重複觸發", rs.should_alert(30, 30) is False)
check("should_alert: 0→5 未達門檻不觸發", rs.should_alert(0, 5) is False)


failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
