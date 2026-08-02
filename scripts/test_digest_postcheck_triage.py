#!/usr/bin/env python3
"""digest_postcheck 交付閘 + LLM 慢路徑分流的離線迴歸(2026-08-02 警報疲勞根治)。

零網路、零外部相依:全部餵合成 log 文字與臨時帳本。
`python3 scripts/test_digest_postcheck_triage.py` → exit 0=全過。
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest_postcheck as dp

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")


def tw_now(s):
    return datetime.fromisoformat(s).replace(tzinfo=ZoneInfo("Asia/Taipei"))


LOG_TW_DONE = """=== 2026-07-31 05:20:01 +0800 winrig runner start (market=tw mode=normal) ===
[LLM] 使用 openrouter: x
=== 2026-07-31 07:00:45 +0800 winrig runner done ===
"""
LOG_TW_DONE_US_RUNNING = LOG_TW_DONE + """=== 2026-07-31 19:00:01 +0800 winrig runner start (market=us mode=normal) ===
[LLM] 使用 local: y
"""
LOG_BOTH_DONE = LOG_TW_DONE_US_RUNNING + "=== 2026-07-31 20:43:31 +0800 winrig runner done ===\n"

# ── 1. runner 收尾訊號:早班跑完不可讓晚班誤判成已交付 ──
check("done/tw", dp.runner_done_for_shift(LOG_TW_DONE_US_RUNNING, "tw"), True)
check("done/us-still-running", dp.runner_done_for_shift(LOG_TW_DONE_US_RUNNING, "us"), False)
check("done/us-finished", dp.runner_done_for_shift(LOG_BOTH_DONE, "us"), True)
check("done/no-log", dp.runner_done_for_shift("", "tw"), False)
# 早班中途死掉(沒有收尾行),晚班之後跑完 → 早班仍必須是「未交付」,不可撿晚班的收尾行當自己的
LOG_TW_CRASHED = """=== 2026-07-31 05:20:01 +0800 winrig runner start (market=tw mode=normal) ===
[LLM] 使用 openrouter: a
=== 2026-07-31 19:00:01 +0800 winrig runner start (market=us mode=normal) ===
=== 2026-07-31 20:43:31 +0800 winrig runner done ===
"""
check("done/tw-crashed-not-stolen", dp.runner_done_for_shift(LOG_TW_CRASHED, "tw"), False)
check("done/us-ok-same-log", dp.runner_done_for_shift(LOG_TW_CRASHED, "us"), True)

# ── 2. shift_delivered:兩個訊號任一即真;origin 查詢炸掉不可當成已交付 ──
check("deliv/log", dp.shift_delivered("2026-07-31", "us", log_text=LOG_BOTH_DONE,
                                      origin_fn=lambda *a: False), True)
check("deliv/origin", dp.shift_delivered("2026-07-31", "us", log_text=LOG_TW_DONE_US_RUNNING,
                                         origin_fn=lambda *a: True), True)
check("deliv/none", dp.shift_delivered("2026-07-31", "us", log_text=LOG_TW_DONE_US_RUNNING,
                                       origin_fn=lambda *a: False), False)


def boom(*a):
    raise RuntimeError("git 掛了")


check("deliv/origin-raises", dp.shift_delivered("2026-07-31", "us", log_text="",
                                                origin_fn=boom), False)

# ── 3. 交付閘判決表 ──
D = dp.delivery_verdict
# open #23 的原始情境:21:10 跑、日報 21:35 才寄,archive 已是生成當下寫的 → 必須 defer 而非失分
check("verdict/undelivered-early", D("2026-07-30", "us", True, False, False, tw_now("2026-07-30T21:10")), "defer")
check("verdict/delivered", D("2026-07-30", "us", True, False, True, tw_now("2026-07-30T21:10")), "ok")
check("verdict/past-deadline", D("2026-07-30", "us", True, False, False, tw_now("2026-07-30T23:00")), "undelivered")
check("verdict/past-deadline-no-archive", D("2026-07-30", "us", False, False, False, tw_now("2026-07-30T23:30")), "missing_archive")
check("verdict/tw-deadline-0850", D("2026-07-30", "tw", True, False, False, tw_now("2026-07-30T08:50")), "defer")
check("verdict/tw-deadline-0900", D("2026-07-30", "tw", True, False, False, tw_now("2026-07-30T09:00")), "undelivered")
# 補跑舊日期(--date 昨天)絕不能無限延後
check("verdict/past-date", D("2026-07-29", "tw", True, False, False, tw_now("2026-07-30T07:50")), "undelivered")
# 美股休市夜:整輪不發,不推播也不延後
check("verdict/us-holiday", D("2026-07-04", "us", False, True, False, tw_now("2026-07-04T21:10")), "skip")
# 休市夜卻有存檔(補寄/手動)→ 照常驗
check("verdict/us-holiday-with-archive", D("2026-07-04", "us", True, True, True, tw_now("2026-07-04T21:10")), "ok")
# 已交付但本機沒有存檔(雲端代打、本機沒 pull 到)→ 照舊 rc=3,不因交付閘被吞掉
check("verdict/delivered-no-archive", D("2026-07-30", "us", False, False, True, tw_now("2026-07-30T21:10")), "missing_archive")

# ── 4. 本班 LLM 用量切段:早報那段不可吃進晚報 ──
seg_log = """=== 2026-07-31 05:20:01 +0800 winrig runner start (market=tw mode=normal) ===
[LLM] 使用 openrouter: a
[LLM] 使用 openrouter: b
=== 2026-07-31 07:00:45 +0800 winrig runner done ===
=== 2026-07-31 19:00:01 +0800 winrig runner start (market=us mode=normal) ===
[LLM] 使用 openrouter: c
[LLM] 使用 local: d
=== 2026-07-31 20:43:31 +0800 winrig runner done ===
"""
check("counts/tw", dp.llm_shift_counts(seg_log, "tw"), (2, 0))
check("counts/us", dp.llm_shift_counts(seg_log, "us"), (1, 1))
check("counts/absent", dp.llm_shift_counts("", "tw"), (0, 0))


# ── 5. 分流:常態化降級 / 惡化升級 / 週期提醒 / 記帳壞掉 fail-closed ──
def with_ledger(rows, fn):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ledger.jsonl"
        if rows is not None:
            p.write_text("".join(
                (r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n"
                for r in rows), encoding="utf-8")
        os.environ["MD_POSTCHECK_LLM_LEDGER"] = str(p)
        try:
            return fn(p)
        finally:
            os.environ.pop("MD_POSTCHECK_LLM_LEDGER", None)


def rec(date, slow, escalated=False, edition="us"):
    return {"date": date, "edition": edition, "slow": slow, "local": 0,
            "escalated": escalated, "chronic": False}


chronic_rows = [rec("2026-07-27", 20, True), rec("2026-07-28", 22), rec("2026-07-29", 19),
                rec("2026-07-30", 26), rec("2026-07-31", 26)]

# 5a. 沒觸發門檻:不報,但要記帳(歷史完整才判得出常態)
def _t5a(p):
    probs, notes = dp.llm_chain_triage(2, 30, "2026-08-01", "us")
    check("triage/below-threshold", (probs, notes), ([], []))
    check("triage/below-threshold-recorded", len(p.read_text().strip().splitlines()), 1)
with_ledger([], _t5a)

# 5b. 空帳本第一次觸發 → 升級(新事件)
def _t5b(p):
    probs, notes = dp.llm_chain_triage(20, 3, "2026-08-01", "us")
    check("triage/first-hit-escalates", (len(probs), len(notes)), (1, 0))
with_ledger([], _t5b)

# 5c. 已是常態且沒惡化 → 降級成註記,不推播
def _t5c(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/chronic-downgrades", (len(probs), len(notes)), (0, 1))
    check("triage/chronic-note-visible", "常態" in notes[0], True)
    last = json.loads(p.read_text().strip().splitlines()[-1])
    check("triage/chronic-recorded", (last["slow"], last["escalated"]), (24, False))
with_ledger(chronic_rows, _t5c)

# 5d. 常態但顯著惡化(近期最糟 26 × 1.5 = 39)→ 升級
def _t5d(p):
    probs, notes = dp.llm_chain_triage(40, 1, "2026-08-01", "us")
    check("triage/chronic-worsening-escalates", (len(probs), len(notes)), (1, 0))
    check("triage/worsening-reason", "顯著惡化" in probs[0], True)
with_ledger(chronic_rows, _t5d)

# 5e. 常態但距上次推播已 7 天 → 週期提醒升級(不讓守衛永久靜音)
def _t5e(p):
    probs, _ = dp.llm_chain_triage(24, 3, "2026-08-03", "us")   # 上次 escalated 是 07-27
    check("triage/periodic-reminder", (len(probs), "週期提醒" in probs[0] if probs else False), (1, True))
with_ledger(chronic_rows, _t5e)

# 5f. 帳本壞檔 → fail-closed 升級(記帳壞掉不准靜音)
def _t5f(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/corrupt-ledger-failclosed", (len(probs), len(notes)), (1, 0))
    check("triage/corrupt-reason", "帳本" in probs[0], True)
with_ledger(["{壞掉的 json"], _t5f)

# 5g. 帳本寫不進去(唯讀目錄)→ 同樣 fail-closed
def _t5g(p):
    os.environ["MD_POSTCHECK_LLM_LEDGER"] = "/proc/nonexistent_dir/ledger.jsonl"
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/unwritable-ledger-failclosed", (len(probs), len(notes)), (1, 0))
with_ledger(chronic_rows, _t5g)

# 5h. --dry 不可污染帳本(測試/人工重跑不准動生產歷史)
def _t5h(p):
    before = p.read_text()
    dp.llm_chain_triage(24, 3, "2026-08-01", "us", dry=True)
    check("triage/dry-no-write", p.read_text(), before)
with_ledger(chronic_rows, _t5h)

# 5i. 另一個班別的歷史不可算進本班別的常態判斷
def _t5i(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "tw")
    check("triage/edition-isolated", (len(probs), len(notes)), (1, 0))
with_ledger(chronic_rows, _t5i)

# 5j. 同一天重跑(補跑)不可拿自己當歷史 → 仍視為新事件
def _t5j(p):
    probs, _ = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/self-not-history", len(probs), 1)
with_ledger([rec("2026-08-01", 24)], _t5j)

# ── 5k~5p. 驗證者 2026-08-02 抓到的缺陷:型別漂移 fail-closed / 去重 / 視窗語義 ──
# 5k. slow 欄型別漂移(字串/None)→ 必須 fail-closed 升級,不可拋例外讓呼叫端吞掉
def _t5k(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/type-drift-failclosed", (len(probs), len(notes)), (1, 0))
with_ledger(chronic_rows[:-1] + [{"date": "2026-07-31", "edition": "us", "slow": "26"}], _t5k)

def _t5l(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/null-slow-failclosed", (len(probs), len(notes)), (1, 0))
with_ledger(chronic_rows[:-1] + [{"date": "2026-07-31", "edition": "us", "slow": None}], _t5l)

# 5m. 缺 date 的列(舊格式漂移)→ 同樣 fail-closed,不可 KeyError 炸出去
def _t5m(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/missing-date-failclosed", (len(probs), len(notes)), (1, 0))
with_ledger(chronic_rows + [{"edition": "us", "slow": 30, "escalated": True}], _t5m)

# 5n. 同一班補跑多次不可污染視窗:(date,edition) 去重後仍只算一班
def _t5n(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/dedup-window", (len(probs), len(notes)), (1, 0))   # 去重後只剩 1 班命中→非常態
with_ledger([rec("2026-07-27", 0), rec("2026-07-28", 0), rec("2026-07-29", 0),
             rec("2026-07-30", 45, True), rec("2026-07-30", 45, True),
             rec("2026-07-30", 45, True), rec("2026-07-30", 45, True)], _t5n)

# 5o. 視窗要依日期排序取最近 5 班,不是取檔案末 5 列(補跑舊日期會亂序)
def _t5o(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-08-01", "us")
    check("triage/window-by-date", (len(probs), len(notes)), (0, 1))  # 最近 5 班有 3 班命中→常態
# 寫入順序刻意亂序(舊日期補跑排在後面):依日期排序取最近 5 班=3 班命中→常態;
# 若照「檔案末 5 列」取,會取到那四筆補跑的舊零值→只剩 1 命中→誤判成新事件。
with_ledger([rec("2026-07-29", 20, True), rec("2026-07-30", 45), rec("2026-07-31", 26),
             rec("2026-07-20", 0), rec("2026-07-21", 0), rec("2026-07-22", 0),
             rec("2026-07-23", 0)], _t5o)

# 5p. 補跑舊日期時,不可以拿它「未來」的班次當歷史
def _t5p(p):
    probs, notes = dp.llm_chain_triage(24, 3, "2026-07-28", "us")
    check("triage/no-future-history", (len(probs), len(notes)), (1, 0))
with_ledger([rec("2026-07-29", 40), rec("2026-07-30", 45), rec("2026-07-31", 26)], _t5p)

# ── 5q. shift_delivered 取真 origin_fn 時必須自己保證 cwd=repo(cron cwd=$HOME) ──
seen_cwd = {}


def spy_origin(ed, d):
    seen_cwd["cwd"] = os.getcwd()
    return True


_before = os.getcwd()
os.chdir("/")
try:
    got = dp.shift_delivered("2026-07-31", "us", log_text="", origin_fn=spy_origin)
finally:
    os.chdir(_before)
check("deliv/origin-runs-in-repo", (got, seen_cwd.get("cwd")), (True, str(dp.REPO)))
check("deliv/cwd-restored", os.getcwd(), _before)

# ── 5r. CLI:--date 的值不可以被當成班別 ──
check("cli/date-only", dp.parse_args(["--date", "2026-08-01"]), ("tw", "2026-08-01", False))
check("cli/normal", dp.parse_args(["us", "--date", "2026-08-01", "--dry"]), ("us", "2026-08-01", True))
try:
    dp.parse_args(["2026-08-01"])
    check("cli/bad-edition-rejected", "no-exit", "SystemExit")
except SystemExit:
    check("cli/bad-edition-rejected", "SystemExit", "SystemExit")

# ── 6. _now_tw 覆寫(測試造時序情境用,且預設不受環境影響) ──
os.environ["MD_POSTCHECK_NOW"] = "2026-07-30T21:10"
check("now/override", dp._now_tw().strftime("%Y-%m-%d %H:%M"), "2026-07-30 21:10")
os.environ.pop("MD_POSTCHECK_NOW")
check("now/default-tz", str(dp._now_tw().tzinfo), "Asia/Taipei")

if FAILS:
    print(f"✗ digest_postcheck 分流迴歸 {len(FAILS)} 項失敗")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✓ digest_postcheck 交付閘 + LLM 分流迴歸全過(45 項)")
