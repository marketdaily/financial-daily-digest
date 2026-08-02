#!/usr/bin/env python3
"""digest_chronic_triage 離線自測(2026-08-03)。零網路、零外部相依。

`python3 scripts/test_digest_chronic_triage.py` → exit 0 = 全過。

⭐ 第 1 組是**契約測試**:fixture 不是我自己抄的格式,而是呼叫 `digest_postcheck.format_report`
(生產端唯一的輸出函式)產生的。抄格式的 fixture 只能證明「我對格式的想像」自洽,
生產端一改就同時騙過測試與偵測器(lesson `producer_format_drift_kills_consumers`)。
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import digest_chronic_triage as ct
import digest_postcheck as dp

FAILS = []
PY = sys.executable


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")


def check_true(name, cond, why=""):
    if not cond:
        FAILS.append(f"{name}: 條件不成立 {why}")


def tw(s):
    return datetime.fromisoformat(s).replace(tzinfo=ZoneInfo("Asia/Taipei"))


def write_shift(dirp, date, ed, problems, notices=(), prefix_lines=(), suffix_rc=True):
    """用【生產端的 format_report】造一班 log,外面包 runner 真的會寫的頭尾行。"""
    body = dp.format_report(date, ed, list(problems), list(notices))
    txt = [f"=== {date} 07:50:01 +0800 digest postcheck start ed={ed} ==="]
    txt += list(prefix_lines)
    txt.append(body)
    if suffix_rc:
        txt.append(f"=== end rc={1 if problems else 0} ===")
    (Path(dirp) / f"postcheck_{date}_{ed}.log").write_text("\n".join(txt) + "\n", encoding="utf-8")


SHALLOW = "[archive] signal_reason_shallow: signal-reason 深度塌陷(疑模型降級):7 張理由 median=79 字"
PA_MANIFEST = "[個人語音] manifest 不存在(main.py 掛鉤沒跑或 MD_AUDIO_TOKEN_SECRET 未設):manifest_x.json"
PA_CDN = "[個人語音] 15/15 支個人音檔 CDN 驗不到(personal.py 沒跑完或上傳掛了):['a', 'b']"
LLM = "[LLM鏈] 本班 20 次呼叫落到 openrouter 慢路徑(~144s/次≈48 分鐘)+本地 146 次 —— 強模層幾乎全滅"
DELIV = "[交付] 到硬死線仍查不到本班交付訊號(runner 未收尾且 origin 無公版存檔)"

# ── 1. 契約測試:生產格式 → 解析 → 條數/鍵值都對得上 ──
with tempfile.TemporaryDirectory() as d:
    write_shift(d, "2026-07-30", "tw", [SHALLOW, PA_MANIFEST], notices=["趨勢註記一則"])
    s = ct.parse_shift_log(Path(d) / "postcheck_2026-07-30_tw.log")
    check("contract/verdict", s["verdict"], "fail")
    check("contract/date", (s["date"], s["edition"]), ("2026-07-30", "tw"))
    check("contract/declared", s["declared"], 2)
    check("contract/parsed", len(s["findings"]), 2)
    check("contract/no-drift", s["parse_drift"], "")
    check("contract/notice-not-counted", any("趨勢註記" in f for f in s["findings"]), False)
    keys = [ct.finding_key(f)[0] for f in s["findings"]]
    check("contract/keys", keys, ["archive:signal_reason_shallow", "personal_audio"])

    write_shift(d, "2026-07-29", "us", [])
    s2 = ct.parse_shift_log(Path(d) / "postcheck_2026-07-29_us.log")
    check("contract/pass", (s2["verdict"], s2["date"], s2["edition"]), ("pass", "2026-07-29", "us"))

# ── 2. finding_key 對照 ──
check("key/archive", ct.finding_key(SHALLOW)[0], "archive:signal_reason_shallow")
check("key/personal", ct.finding_key(PA_CDN)[0], "personal_audio")
check("key/llm", ct.finding_key(LLM)[0], "llm_chain")
check("key/delivery", ct.finding_key(DELIV)[0], "delivery")
check("key/narration", ct.finding_key("[語音稿] 殘留 emoji「🔥」")[0], "narration")
check("key/audio", ct.finding_key("[語音] CDN 大小不符 local=1 remote=2")[0], "audio")
check("key/reel", ct.finding_key("[reel] caption 含 ++/-- 雙符號")[0], "reel")
# 認不得的前綴不准被丟掉——新種失分若靜默消失,慢性偵測就永遠看不到它
check("key/unknown-prefix", ct.finding_key("[新種檢查] 出事了")[0], "other:新種檢查")
check("key/no-prefix", ct.finding_key("裸文字沒有前綴")[0], "unstructured")
check("key/archive-no-check", ct.finding_key("[archive] 沒有冒號的訊息")[0], "archive:unknown")

# ── 3. 多輪輸出:defer 後重跑,只認最後一個判決 ──
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "postcheck_2026-07-30_tw.log"
    first = dp.format_report("2026-07-30", "tw", [SHALLOW, PA_CDN, LLM], [])
    final = dp.format_report("2026-07-30", "tw", [PA_CDN], [])
    p.write_text("=== start ===\n⏳ 2026-07-30 tw:查不到本班交付訊號 —— 判決延後\n"
                 + first + "\n=== end rc=1 ===\n=== start(重跑) ===\n" + final + "\n=== end rc=1 ===\n",
                 encoding="utf-8")
    s = ct.parse_shift_log(p)
    check("multi/declared", s["declared"], 1)
    check("multi/findings", [ct.finding_key(f)[0] for f in s["findings"]], ["personal_audio"])
    check("multi/no-drift", s["parse_drift"], "")

# ── 4. 解析漂移:header 說 3 條、只解析到 2 條 → 必須大聲,不准安靜少算 ──
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "postcheck_2026-07-30_us.log"
    p.write_text("✗ 寄後複檢 2026-07-30 us:3 個問題\n  - " + SHALLOW + "\n  - " + PA_CDN
                 + "\n  * 新格式的第三條\n=== end rc=1 ===\n", encoding="utf-8")
    s = ct.parse_shift_log(p)
    check_true("drift/flagged", bool(s["parse_drift"]), s["parse_drift"])
    check("drift/parsed", len(s["findings"]), 2)

# ── 5. 慢性判準 ──
def build(dirp, shifts):
    for date, ed, problems in shifts:
        write_shift(dirp, date, ed, problems)


BASE_CLEAN = [("2026-07-20", "tw", []), ("2026-07-20", "us", []),
              ("2026-07-21", "tw", []), ("2026-07-21", "us", []),
              ("2026-07-22", "tw", []), ("2026-07-22", "us", [])]
NOW = tw("2026-07-24T11:00:00")

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [SHALLOW]), ("2026-07-23", "us", [SHALLOW])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("chronic/2hits-no-trigger", r["verdict"], "clean")

    build(d, [("2026-07-23", "us", [SHALLOW, PA_CDN])])
    write_shift(d, "2026-07-24", "tw", [SHALLOW])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("chronic/3hits-fix", [i["key"] for i in r["fix"]], ["archive:signal_reason_shallow"])
    check("chronic/verdict", r["verdict"], "fix")
    check("chronic/hits", r["fix"][0]["hits"], 3)

with tempfile.TemporaryDirectory() as d:
    # 同一班同一 key 出現兩行(manifest 缺 + CDN 驗不到)只能算一次,不然一班就自己撐成慢性
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [PA_CDN]), ("2026-07-23", "us", [PA_MANIFEST]),
                           ("2026-07-24", "tw", [PA_CDN, PA_MANIFEST])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    pa = [i for i in r["chronic"] if i["key"] == "personal_audio"]
    check("chronic/dedup-in-shift", pa[0]["hits"] if pa else None, 3)
    check("chronic/dedup-samples", len(pa[0]["samples"]) if pa else None, 3)

with tempfile.TemporaryDirectory() as d:
    # 全部命中都在窗口前段(最近 4 班都沒犯)→ 視為已止血,不重複立案
    led = str(Path(d) / "led.jsonl")
    build(d, [("2026-07-14", "tw", [SHALLOW]), ("2026-07-14", "us", [SHALLOW]),
              ("2026-07-15", "tw", [SHALLOW]), ("2026-07-15", "us", []),
              ("2026-07-16", "tw", []), ("2026-07-16", "us", []),
              ("2026-07-17", "tw", []), ("2026-07-17", "us", [])])
    r = ct.triage(now=tw("2026-07-18T11:00:00"), log_dir=d, ledger=led, gap_days=0)
    check("chronic/stale-hits-no-trigger", r["verdict"], "clean")

# ── 6. 分類路由:infra 忽略、delivery 只升級 ──
with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [LLM]), ("2026-07-23", "us", [LLM]),
                           ("2026-07-24", "tw", [LLM])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/llm-not-fixed", (r["fix"], r["escalate"]), ([], []))
    check("route/llm-listed", [i["route"] for i in r["chronic"]], ["infra_ignored"])
    check("route/llm-verdict", r["verdict"], "clean")

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [DELIV]), ("2026-07-23", "us", [DELIV]),
                           ("2026-07-24", "tw", [DELIV])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/delivery-escalate", [i["key"] for i in r["escalate"]], ["delivery"])
    check("route/delivery-not-fix", r["fix"], [])
    check("route/delivery-verdict", r["verdict"], "escalate")

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    UNK = "[新種檢查] 每天都在發生"
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [UNK]), ("2026-07-23", "us", [UNK]),
                           ("2026-07-24", "tw", [UNK])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/unknown-escalate", [i["key"] for i in r["escalate"]], ["other:新種檢查"])

# ── 7. 帳本:cooldown / 上限 / resolved / 未來日 / 壞損 ──
def chronic_env(d):
    build(d, BASE_CLEAN + [("2026-07-23", "tw", [SHALLOW]), ("2026-07-23", "us", [SHALLOW]),
                           ("2026-07-24", "tw", [SHALLOW])])


with tempfile.TemporaryDirectory() as d:
    chronic_env(d)
    led = Path(d) / "led.jsonl"
    KEY = "archive:signal_reason_shallow"
    led.write_text(json.dumps({"date": "2026-07-23", "key": KEY, "action": "attempted"},
                              ensure_ascii=False) + "\n", encoding="utf-8")
    r = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/cooling", ([i["key"] for i in r["cooling"]], r["fix"]), ([KEY], []))
    check("ledger/cooling-verdict", r["verdict"], "cooling")

    # 冷卻期滿(COOLDOWN_DAYS=5,07-23 立案 → 07-29 已過)→ 可以再立案一次
    r2 = ct.triage(now=tw("2026-07-29T11:00:00"), log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/cooldown-expired", [i["key"] for i in r2["fix"]], [KEY])

    # 兩次嘗試仍再犯 → 升級給人,不再自動修
    led.write_text("".join(json.dumps({"date": dt, "key": KEY, "action": a}, ensure_ascii=False) + "\n"
                           for dt, a in [("2026-07-10", "attempted"), ("2026-07-11", "blocked")]),
                   encoding="utf-8")
    r3 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/max-attempts", [i["key"] for i in r3["escalate"]], [KEY])
    check("ledger/max-attempts-no-fix", r3["fix"], [])

    # resolved 之後前帳一筆勾銷(否則同一個 key 一輩子只能被機器修兩次)
    led.write_text(led.read_text(encoding="utf-8")
                   + json.dumps({"date": "2026-07-12", "key": KEY, "action": "resolved"},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    r4 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/resolved-resets", [i["key"] for i in r4["fix"]], [KEY])

    # 未來日期的 attempt(時鐘錯亂/手改)→ 當成冷卻中,不無限重刷
    led.write_text(json.dumps({"date": "2026-09-01", "key": KEY, "action": "attempted"},
                              ensure_ascii=False) + "\n", encoding="utf-8")
    r5 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/future-date-cools", ([i["key"] for i in r5["cooling"]], r5["fix"]), ([KEY], []))

    # 日期欄壞掉 → 算不出冷卻,當成冷卻中(不可因為讀不懂帳本就天天重複 spawn)
    led.write_text(json.dumps({"date": "不是日期", "key": KEY, "action": "attempted"},
                              ensure_ascii=False) + "\n", encoding="utf-8")
    r5b = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/bad-date-cools", ([i["key"] for i in r5b["cooling"]], r5b["fix"]), ([KEY], []))

    # 帳本壞掉 → 不自動修(避免重複立案),但必須升級(不可靜默)
    led.write_text("{壞掉的 json\n", encoding="utf-8")
    r6 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/broken-no-fix", r6["fix"], [])
    check("ledger/broken-escalate", [i["key"] for i in r6["escalate"]], [KEY])
    check_true("ledger/broken-reason", bool(r6["ledger_broken"]), r6["ledger_broken"])
    check_true("ledger/broken-in-summary", "帳本" in ct.summary_line(r6), ct.summary_line(r6))

# ── 8. 班表/缺件 dead-man:誰在檢查檢查者 ──
SUN, SAT, MON = tw("2026-08-02T12:00:00"), tw("2026-08-01T12:00:00"), tw("2026-08-03T12:00:00")
exp = dict.fromkeys(ct.expected_shifts(tw("2026-08-03T23:59:00"), days=3))
check("sched/no-sunday", any(dt == "2026-08-02" for dt, _ in exp), False)
check("sched/sat-tw-only", [ed for dt, ed in exp if dt == "2026-08-01"], ["tw"])
check("sched/weekday-both", [ed for dt, ed in exp if dt == "2026-07-31"], ["tw", "us"])
# 硬死線沒過的班次不算缺件(它可能正要跑)
exp_early = ct.expected_shifts(tw("2026-08-03T08:00:00"), days=1)
check("sched/before-deadline", [s for s in exp_early if s[0] == "2026-08-03"], [])
exp_mid = ct.expected_shifts(tw("2026-08-03T10:00:00"), days=1)
check("sched/after-tw-deadline", [s for s in exp_mid if s[0] == "2026-08-03"], [("2026-08-03", "tw")])

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN)  # 07-20~07-22 有判決,07-23 之後全空
    gaps = ct.coverage_gaps(tw("2026-07-24T23:59:00"), days=4, log_dir=d)
    check("gap/count", len(gaps), 4)     # 07-23 tw/us + 07-24 tw/us(23:59 時兩條死線都過了)
    r = ct.triage(now=tw("2026-07-24T12:00:00"), log_dir=d, ledger=led)
    check_true("gap/blind", bool(r["blind"]), r["blind"])
    check("gap/blind-verdict", r["verdict"], "escalate")
    check_true("gap/blind-in-summary", "失明" in ct.summary_line(r), ct.summary_line(r))

with tempfile.TemporaryDirectory() as d:
    # 美股休市夜:腳本印「跳過複檢」→ 算已覆蓋,不是缺件(否則每個美股假日都假警報)
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN)
    (Path(d) / "postcheck_2026-07-23_us.log").write_text(
        "=== start ===\n今晚美股休市,晚報整輪不發是預期行為,跳過複檢\n=== end rc=0 ===\n", encoding="utf-8")
    write_shift(d, "2026-07-23", "tw", [])
    gaps = ct.coverage_gaps(tw("2026-07-23T23:59:00"), days=1, log_dir=d)
    check("gap/us-holiday-skip", gaps, [])
    check("gap/skip-verdict", ct.parse_shift_log(Path(d) / "postcheck_2026-07-23_us.log")["verdict"], "skip")
    # 只有 defer、從沒判決 → 算缺件(它正是「複檢卡住沒收尾」的樣子)
    (Path(d) / "postcheck_2026-07-23_us.log").write_text(
        "=== start ===\n⏳ 查不到本班交付訊號,判決延後\n", encoding="utf-8")
    check("gap/defer-only-is-gap", ct.coverage_gaps(tw("2026-07-23T23:59:00"), days=1, log_dir=d),
          ["2026-07-23/us(log 內無判決)"])

with tempfile.TemporaryDirectory() as d:
    # 失明 + 有慢性失分同時發生 → 不准照舊自動改碼,一律先升級(資料來源本身可疑)
    led = str(Path(d) / "led.jsonl")
    build(d, [("2026-07-23", "tw", [SHALLOW]), ("2026-07-23", "us", [SHALLOW]),
              ("2026-07-24", "tw", [SHALLOW]), ("2026-07-24", "us", []),
              ("2026-07-22", "tw", []), ("2026-07-22", "us", [])])
    r = ct.triage(now=tw("2026-07-24T23:59:00"), log_dir=d, ledger=led, gap_days=7)
    check_true("blind+chronic/blind", bool(r["blind"]), r["blind"])
    check("blind+chronic/no-autofix", r["fix"], [])
    check("blind+chronic/escalated", [i["key"] for i in r["escalate"]], ["archive:signal_reason_shallow"])
    check("blind+chronic/verdict", r["verdict"], "escalate")

# ── 9. CLI:exit code 契約 + record 子命令 ──
def run_cli(args, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run([PY, str(HERE / "digest_chronic_triage.py")] + args,
                          capture_output=True, text=True, env=env)


with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    env = {"MD_CHRONIC_LOGDIR": d, "MD_CHRONIC_LEDGER": led, "MD_CHRONIC_NOW": "2026-07-24T11:00:00",
           "MD_CHRONIC_GAP_DAYS": "0"}
    build(d, BASE_CLEAN)
    check("cli/clean-rc", run_cli([], env).returncode, 1)
    chronic_env(d)
    p = run_cli(["--json"], env)
    check("cli/fix-rc", p.returncode, 0)
    check("cli/json", json.loads(p.stdout)["verdict"], "fix")
    check_true("cli/summary", "慢性失分立案" in run_cli([], env).stdout, run_cli([], env).stdout)

    r = run_cli(["record", "attempted", "archive:signal_reason_shallow", "自測"], env)
    check("cli/record-rc", r.returncode, 0)
    rec = json.loads(Path(led).read_text(encoding="utf-8").strip())
    check("cli/record-fields", (rec["key"], rec["action"], rec["date"]),
          ("archive:signal_reason_shallow", "attempted", "2026-07-24"))
    check("cli/record-then-cooling", run_cli([], env).returncode, 1)   # 冷卻中 → 安靜退
    check("cli/bad-arg", run_cli(["--nope"], env).returncode, 1)
    check("cli/bad-record", run_cli(["record", "xxx", "k"], env).returncode, 1)
    # 需人工(這裡用失明情境)→ rc=2,runner 靠它決定「只推播不 spawn」
    env_blind = dict(env, MD_CHRONIC_GAP_DAYS="7", MD_CHRONIC_NOW="2026-07-31T23:59:00")
    check("cli/escalate-rc", run_cli([], env_blind).returncode, 2)

# ── 10. 真實生產語料:對既有 postcheck log 跑一次,不可炸也不可解析漂移 ──
# 語料目錄可用 MD_CHRONIC_REAL_LOGS 覆寫(突變測試沙盒用);**找不到語料一律紅**,
# 不准 skip —— 自動 skip 的覆蓋率就是假的(2026-08-02 假綠教訓)。
REAL_LOGS = Path(os.environ.get("MD_CHRONIC_REAL_LOGS", str(HERE.parent / "logs")))
check_true("real/corpus-exists", REAL_LOGS.is_dir(), str(REAL_LOGS))
real = ct.triage(log_dir=str(REAL_LOGS), ledger="/dev/null")
check("real/no-drift", real["parse_drift"], [])
check_true("real/has-shifts", real["shifts_seen"] >= 4, real["shifts_seen"])

if FAILS:
    print("❌ digest_chronic_triage 自測未過:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✓ digest_chronic_triage 自測全過(契約/解析/慢性判準/路由/帳本/缺件 dead-man/CLI)")
