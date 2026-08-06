#!/usr/bin/env python3
"""signal-reason 長度趨勢帳本迴歸測試(2026-08-06,backlog P1「寄後複檢每晚都在報真問題」
撈出的記帳缺口:median 字數以前只有觸發 signal_reason_shallow 失分時才會出現在 log 裡,
平常完全沒記帳,沒人看得出「哪幾天的日報比較薄」)。

涵蓋:
  1. digest_audit.signal_reason_stats() 的統計量正確性(median/min/max/n_below60)+
     備援卡過濾 + 卡數不足(<1)回傳 n=0。
  2. digest_postcheck.record_reason_median() 的寫入行為:正常寫入一行/--dry 不寫/
     n=0(全備援卡)不寫/多次呼叫 append 不覆蓋(讓 kpi_pull.py 讀取端可依 date 去重)。

零網路、零外部相依,全部用臨時檔案。
用法: .venv/bin/python scripts/test_signal_reason_median_ledger.py   (exit 0=全過)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest_audit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest_postcheck as dp

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")


def mk_reason(n):
    base = "建議 NT$1050 附近進場 目標 NT$1180 跌破 NT$980 停損 "
    filler = "後續觀察量能與法人買賣超動向再決定加減碼耐心等待財報不追高殺低嚴控部位風險"
    s = base
    while len(s) < n:
        s += filler
    return s[:n]


def build_html(lengths, fallback_extra=0):
    cards = []
    for i, n in enumerate(lengths):
        cards.append(
            f'<div class="signal-card">'
            f'<span class="signal-ticker">T{i:02d}</span>'
            f'<div class="signal-reason">{mk_reason(n)}</div>'
            f'</div>'
        )
    for i in range(fallback_extra):
        cards.append(
            '<div class="signal-card">'
            '<div class="signal-reason">個人化生成異常,主編將於下班次修復</div>'
            '</div>'
        )
    return "<html><body>" + "".join(cards) + "</body></html>"


# ── 1. signal_reason_stats() 統計量 ──
stats = digest_audit.signal_reason_stats(build_html([100, 120, 140, 160]))
check("median/偶數張", stats["median"], 130)
check("min", stats["min"], 100)
check("max", stats["max"], 160)
check("n", stats["n"], 4)
check("n_below60/全部達標", stats["n_below60"], 0)

stats_odd = digest_audit.signal_reason_stats(build_html([50, 90, 200]))
check("median/奇數張", stats_odd["median"], 90)
check("n_below60/一張<60", stats_odd["n_below60"], 1)

stats_fb = digest_audit.signal_reason_stats(build_html([100, 120], fallback_extra=3))
check("備援卡不計入 n", stats_fb["n"], 2)

stats_empty = digest_audit.signal_reason_stats(build_html([], fallback_extra=2))
check("全備援卡 → n=0", stats_empty.get("n"), 0)
check("全備援卡 → 無 median 鍵", "median" in stats_empty, False)

stats_none = digest_audit.signal_reason_stats("<html><body>沒有任何 signal-card</body></html>")
check("零 signal-card → n=0", stats_none.get("n"), 0)


# ── 2. record_reason_median() 寫入行為 ──
def with_ledger(fn):
    with tempfile.TemporaryDirectory() as d:
        orig = dp.REASON_MEDIAN_LEDGER
        dp.REASON_MEDIAN_LEDGER = Path(d) / "signal_reason_median_history.jsonl"
        try:
            fn(dp.REASON_MEDIAN_LEDGER)
        finally:
            dp.REASON_MEDIAN_LEDGER = orig


def _test_normal_write(path):
    html = build_html([100, 120, 140])
    dp.record_reason_median("2026-08-06", "tw", html, dry=False)
    check("正常寫入後檔案存在", path.exists(), True)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    check("正常寫入 1 行", len(rows), 1)
    check("寫入的 date", rows[0]["date"], "2026-08-06")
    check("寫入的 edition", rows[0]["edition"], "tw")
    check("寫入的 median", rows[0]["median"], 120)


def _test_dry_skips_write(path):
    html = build_html([100, 120, 140])
    dp.record_reason_median("2026-08-06", "tw", html, dry=True)
    check("--dry 不寫檔", path.exists(), False)


def _test_empty_stats_skips_write(path):
    html = build_html([], fallback_extra=3)
    dp.record_reason_median("2026-08-06", "tw", html, dry=False)
    check("全備援卡(n=0)不寫檔", path.exists(), False)


def _test_below_min_sample_skips_write(path):
    html = build_html([100, 120])  # n=2,低於新門檻 3(對齊 digest_audit 9b-2 最小樣本)
    dp.record_reason_median("2026-08-06", "tw", html, dry=False)
    check("n=2(<3 最小樣本)不寫檔", path.exists(), False)


def _test_append_not_overwrite(path):
    dp.record_reason_median("2026-08-04", "tw", build_html([100, 120, 140]), dry=False)
    dp.record_reason_median("2026-08-05", "tw", build_html([200, 220, 240]), dry=False)
    dp.record_reason_median("2026-08-05", "us", build_html([80, 90, 100]), dry=False)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    check("append 三次 → 3 行(不覆蓋)", len(rows), 3)
    dates = sorted((r["date"], r["edition"]) for r in rows)
    check("三行各自獨立留存", dates,
          [("2026-08-04", "tw"), ("2026-08-05", "tw"), ("2026-08-05", "us")])


with_ledger(_test_normal_write)
with_ledger(_test_dry_skips_write)
with_ledger(_test_empty_stats_skips_write)
with_ledger(_test_below_min_sample_skips_write)
with_ledger(_test_append_not_overwrite)


if FAILS:
    print(f"❌ {len(FAILS)} 項失敗:")
    for f in FAILS:
        print(f"   {f}")
    sys.exit(1)
print("✅ 全過:signal_reason_stats + record_reason_median")
sys.exit(0)
