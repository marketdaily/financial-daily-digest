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
# e2e 視角是同一個子系統的另一個鏡頭:不併回去的話,同一個病被拆成兩個 key,各自湊不到門檻
check("key/personal-e2e-merged", ct.finding_key("[個人語音e2e] 訂閱者點自己的專屬語音連結卡住")[0],
      "personal_audio")
check("key/audio-e2e-merged", ct.finding_key("[語音頁e2e] 守衛本身跑不動(TimeoutError)")[0], "audio")

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

# ── 4b. postcheck rc=3(公版存檔不存在):有判決但沒有「N 個問題」header ──
# 舊版把整班算成「查不到判決」→ 湊兩班就報「複檢自己沒在跑」,把人帶去查錯方向
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "postcheck_2026-07-30_us.log"
    p.write_text("=== start ===\n✗ 公版 archive 不存在:digest_2026-07-30_us.html\n=== end rc=3 ===\n",
                 encoding="utf-8")
    s = ct.parse_shift_log(p)
    check("missing_archive/verdict", (s["verdict"], s["date"], s["edition"]), ("fail", "2026-07-30", "us"))
    check("missing_archive/key", ct.finding_key(s["findings"][0])[0], "archive:missing_archive")
    gaps_ma = ct.coverage_gaps(tw("2026-07-30T23:59:00"), days=0, log_dir=d)
    check("missing_archive/not-a-gap", [g for g in gaps_ma if "us" in g], [])
    check_true("missing_archive/escalate-only", "archive:missing_archive" in ct.ESCALATE_ONLY_KEYS)

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

    # 3 次但只跨 2 個日曆天(同日 tw+us 不是獨立觀測)→ 當插曲,不立案
    write_shift(d, "2026-07-24", "tw", [SHALLOW])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("chronic/3hits-2days-episode", [i["key"] for i in r["episode"]],
          ["archive:signal_reason_shallow"])
    check("chronic/episode-not-fix", (r["fix"], r["verdict"]), ([], "clean"))
    check_true("chronic/episode-in-summary", "插曲" in ct.summary_line(r), ct.summary_line(r))

    # 補到跨 3 個日曆天 → 才算慢性
    build(d, [("2026-07-22", "us", [SHALLOW, PA_CDN])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("chronic/3days-fix", [i["key"] for i in r["fix"]], ["archive:signal_reason_shallow"])
    check("chronic/verdict", r["verdict"], "fix")
    check("chronic/hits", r["fix"][0]["hits"], 4)
    check("chronic/days", r["fix"][0]["days"], 3)

with tempfile.TemporaryDirectory() as d:
    # 同一班同一 key 出現兩行(manifest 缺 + CDN 驗不到)只能算一次,不然一班就自己撐成慢性
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-22", "us", [PA_CDN]),
                           ("2026-07-23", "tw", [PA_CDN]), ("2026-07-23", "us", [PA_MANIFEST]),
                           ("2026-07-24", "tw", [PA_CDN, PA_MANIFEST])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    pa = [i for i in r["chronic"] if i["key"] == "personal_audio"]
    check("chronic/dedup-in-shift", pa[0]["hits"] if pa else None, 4)
    check("chronic/dedup-days", pa[0]["days"] if pa else None, 3)
    check("chronic/dedup-samples", len(pa[0]["samples"]) if pa else None, 3)

with tempfile.TemporaryDirectory() as d:
    # 全部命中都在窗口前段(最近 4 班都沒犯)→ 視為已止血,不重複立案
    led = str(Path(d) / "led.jsonl")
    build(d, [("2026-07-14", "tw", [SHALLOW]), ("2026-07-14", "us", [SHALLOW]),
              ("2026-07-15", "tw", [SHALLOW]), ("2026-07-15", "us", [SHALLOW]),
              ("2026-07-13", "tw", [SHALLOW]), ("2026-07-13", "us", []),
              ("2026-07-16", "tw", []), ("2026-07-16", "us", []),
              ("2026-07-17", "tw", []), ("2026-07-17", "us", [])])
    r = ct.triage(now=tw("2026-07-18T11:00:00"), log_dir=d, ledger=led, gap_days=0)
    check("chronic/stale-hits-no-trigger", r["verdict"], "clean")

# ── 6. 分類路由:infra 忽略、delivery 只升級 ──
with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-22", "us", [LLM]), ("2026-07-23", "tw", [LLM]),
                           ("2026-07-24", "tw", [LLM])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/llm-not-fixed", (r["fix"], r["escalate"]), ([], []))
    check("route/llm-listed", [i["route"] for i in r["chronic"]], ["infra_ignored"])
    check("route/llm-verdict", r["verdict"], "clean")
    # 摘要不可以宣稱「無慢性失分」——infra 類每班都在犯,只是不歸這裡改碼(驗證者 Notes)
    check_true("route/llm-summary-honest", "infra 類 1 項" in ct.summary_line(r), ct.summary_line(r))

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-22", "us", [DELIV]), ("2026-07-23", "tw", [DELIV]),
                           ("2026-07-24", "tw", [DELIV])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/delivery-escalate", [i["key"] for i in r["escalate"]], ["delivery"])
    check("route/delivery-not-fix", r["fix"], [])
    check("route/delivery-verdict", r["verdict"], "escalate")

with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    UNK = "[新種檢查] 每天都在發生"
    build(d, BASE_CLEAN + [("2026-07-22", "us", [UNK]), ("2026-07-23", "tw", [UNK]),
                           ("2026-07-24", "tw", [UNK])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("route/unknown-escalate", [i["key"] for i in r["escalate"]], ["other:新種檢查"])

# ── 7. 帳本:cooldown / 上限 / resolved / 未來日 / 壞損 ──
def chronic_env(d):
    build(d, BASE_CLEAN + [("2026-07-22", "us", [SHALLOW]), ("2026-07-23", "tw", [SHALLOW]),
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

    # 一次 runner 執行=attempted + 一筆結局,只能算「一次嘗試」(否則上限 2 實際只有 1 次)
    led.write_text("".join(json.dumps({"date": dt, "key": KEY, "action": a}, ensure_ascii=False) + "\n"
                           for dt, a in [("2026-07-10", "attempted"), ("2026-07-10", "blocked")]),
                   encoding="utf-8")
    r3a = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/one-run-one-attempt", [i["key"] for i in r3a["fix"]], [KEY])
    check("ledger/one-run-attempts", r3a["fix"][0]["attempts"] if r3a["fix"] else None, 1)

    # 中止型結局(push 失敗/讓路/apply 空)不算用掉額度:一次網路抖動不該永久燒掉自動修資格
    led.write_text("".join(json.dumps({"date": dt, "key": KEY, "action": a}, ensure_ascii=False) + "\n"
                           for dt, a in [("2026-07-01", "attempted"), ("2026-07-01", "aborted"),
                                         ("2026-07-02", "attempted"), ("2026-07-02", "aborted")]),
                   encoding="utf-8")
    r3b = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/aborted-not-counted", [i["key"] for i in r3b["fix"]], [KEY])
    check("ledger/aborted-attempts", r3b["fix"][0]["attempts"] if r3b["fix"] else None, 0)

    # 兩個【不同開工日】的嘗試仍再犯 → 升級給人,不再自動修
    led.write_text("".join(json.dumps({"date": dt, "key": KEY, "action": a}, ensure_ascii=False) + "\n"
                           for dt, a in [("2026-07-10", "attempted"), ("2026-07-10", "blocked"),
                                         ("2026-07-11", "attempted"), ("2026-07-11", "applied")]),
                   encoding="utf-8")
    r3 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/max-attempts", [i["key"] for i in r3["escalate"]], [KEY])
    check("ledger/max-attempts-no-fix", r3["fix"], [])

    check("ledger/max-attempts-count", r3["escalate"][0]["attempts"] if r3["escalate"] else None, 2)
    # 升級提醒去重:剛講過就不重講,隔了 ESCALATE_REMIND_DAYS 天才再講(但絕不永久閉嘴)
    led2 = led.read_text(encoding="utf-8")
    led.write_text(led2 + json.dumps({"date": "2026-07-23", "key": KEY, "action": "escalated"},
                                     ensure_ascii=False) + "\n", encoding="utf-8")
    r3c = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/escalate-dedup", (r3c["verdict"], r3c["notify"]), ("escalate", False))
    led.write_text(led2 + json.dumps({"date": "2026-07-10", "key": KEY, "action": "escalated"},
                                     ensure_ascii=False) + "\n", encoding="utf-8")
    r3d = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/escalate-remind-again", (r3d["verdict"], r3d["notify"]), ("escalate", True))
    # 但「守衛自己瞎了/帳本壞了」不可被去重降噪:剛講過的同一個 key + 帳本壞掉 → 仍必須推播
    led.write_text(led2 + json.dumps({"date": "2026-07-23", "key": KEY, "action": "escalated"},
                                     ensure_ascii=False) + "\n這行不是 json\n", encoding="utf-8")
    r3e = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/infra-level-never-muted",
          (bool(r3e["ledger_broken"]), r3e["notify"]), (True, True))
    led.write_text(led2, encoding="utf-8")

    # resolved 之後前帳一筆勾銷(否則同一個 key 一輩子只能被機器修兩次)
    led.write_text(led.read_text(encoding="utf-8")
                   + json.dumps({"date": "2026-07-12", "key": KEY, "action": "resolved"},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    r4 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/resolved-resets", [i["key"] for i in r4["fix"]], [KEY])

    # ⭐ aborted 不燒額度,但**冷卻照算**(第 2 輪驗證者 F1)。兩者共用同一份清單時,
    # 持續性中止(主樹一直有 WIP / push 一直失敗)= 每天 spawn 一次 opus、attempts 恆為 0、
    # 永遠不會升級給人 —— 「不無限重刷 token」與「修不好就叫人」兩條紅線一起破。
    led.write_text(json.dumps({"date": "2026-07-23", "key": KEY, "action": "attempted"},
                              ensure_ascii=False) + "\n"
                   + json.dumps({"date": "2026-07-23", "key": KEY, "action": "aborted"},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    ra = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/aborted-still-cools", ([i["key"] for i in ra["cooling"]], ra["fix"]), ([KEY], []))
    check("ledger/aborted-attempts-zero", ra["cooling"][0]["attempts"] if ra["cooling"] else None, 0)

    # 連續中止達上限 → 停止重試改叫人(有東西一直擋著,不是「還沒用到額度」)
    led.write_text("".join(
        json.dumps({"date": dt, "key": KEY, "action": a}, ensure_ascii=False) + "\n"
        for dt in ("2026-07-14", "2026-07-15", "2026-07-16") for a in ("attempted", "aborted")),
        encoding="utf-8")
    rab = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/consecutive-aborted-escalates", [i["key"] for i in rab["escalate"]], [KEY])
    check("ledger/consecutive-aborted-not-fix", rab["fix"], [])


    # ⭐ 日期「壞值」不可以只是靜靜地變成冷卻(第 2 輪驗證者 F3)。
    # 舊版:未來日 → cooling(36325 天)、壞字串 → cooling(永遠),verdict=cooling → rc=1 →
    # runner 看到摘要含「冷卻中」就安靜退,而 ledger_broken 是空字串 = 帳本壞掉那道告警從未觸發。
    # 這與 shioaji 守望器的「未來日 first_seen 讓唯一的主動告警永久靜音」是同一個形狀。
    for label, bad_date in (("future", "2026-09-01"), ("garbage", "不是日期")):
        led.write_text(json.dumps({"date": bad_date, "key": KEY, "action": "attempted"},
                                  ensure_ascii=False) + "\n", encoding="utf-8")
        rb = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
        check(f"ledger/{label}-date-not-silent",
              (rb["verdict"], rb["notify"], bool(rb["ledger_broken"]), rb["fix"]),
              ("escalate", True, True, []))
        check_true(f"ledger/{label}-date-in-summary", "帳本" in ct.summary_line(rb),
                   ct.summary_line(rb))

    # 帳本壞掉 → 不自動修(避免重複立案),但必須升級(不可靜默)
    led.write_text("{壞掉的 json\n", encoding="utf-8")
    r6 = ct.triage(now=NOW, log_dir=d, ledger=str(led), gap_days=0)
    check("ledger/broken-no-fix", r6["fix"], [])
    check("ledger/broken-escalate", [i["key"] for i in r6["escalate"]], [KEY])
    check_true("ledger/broken-reason", bool(r6["ledger_broken"]), r6["ledger_broken"])
    # 多種損壞混在一起時,回報不能只剩最後一種(運維只看到冰山一角)
    led.write_text("{壞的\n" + json.dumps({"key": "k"}) + "\n不是 json\n", encoding="utf-8")
    _, broken_multi = ct.read_ledger(str(led))
    check_true("ledger/broken-counts-all", "共 3 行壞掉" in broken_multi, broken_multi)
    # 三種損壞的**每一種**都要看得到:只回報最後一種 = 運維只看到冰山一角
    check_true("ledger/broken-lists-first", "第 1 行" in broken_multi, broken_multi)
    check_true("ledger/broken-lists-mid", "第 2 行" in broken_multi, broken_multi)
    # 型別漂移(key 是 list / action 是數字):欄位都在、卻永遠比不中 → 該筆記帳等於消失,
    # 冷卻與額度被靜默清零。必須算「帳本壞掉」而不是安靜放行(第 2 輪驗證者 Notes)
    led.write_text(json.dumps({"date": "2026-07-20", "key": ["k"], "action": "attempted"}) + "\n",
                   encoding="utf-8")
    _, broken_type = ct.read_ledger(str(led))
    check_true("ledger/type-drift-is-broken", "型別" in broken_type, broken_type)
    led.write_text(json.dumps({"date": "2026-07-20", "key": "k", "action": 123}) + "\n",
                   encoding="utf-8")
    _, broken_act = ct.read_ledger(str(led))
    check_true("ledger/action-type-is-broken", bool(broken_act), broken_act)
    check_true("ledger/broken-in-summary", "帳本" in ct.summary_line(r6), ct.summary_line(r6))

# ── 7b. 一輪只立一個 key(第 2 輪驗證者 F6)──
# runner 把整包 key 丟給同一個代理,收尾卻對**每一個** key 記同一個結局 → 沒被碰過的 key
# 一樣燒額度、一樣進冷卻,兩輪後兩個都被判「修過還犯,交人工」。讓「一次執行=一個 key」
# 在偵測層就成立,記帳才對得起現實。
with tempfile.TemporaryDirectory() as d:
    led = str(Path(d) / "led.jsonl")
    build(d, BASE_CLEAN + [("2026-07-22", "us", [SHALLOW, PA_CDN]),
                           ("2026-07-23", "tw", [SHALLOW, PA_CDN]),
                           ("2026-07-23", "us", [SHALLOW]),
                           ("2026-07-24", "tw", [SHALLOW, PA_CDN])])
    r = ct.triage(now=NOW, log_dir=d, ledger=led, gap_days=0)
    check("batch/one-key-only", len(r["fix"]), 1)
    check("batch/picks-most-hits", r["fix"][0]["key"], "archive:signal_reason_shallow")
    check("batch/rest-deferred", [i["key"] for i in r["deferred"]], ["personal_audio"])
    check_true("batch/deferred-visible-in-summary", "排隊" in ct.summary_line(r), ct.summary_line(r))

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
              ("2026-07-22", "tw", [SHALLOW]), ("2026-07-22", "us", [])])
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
    # 用法錯 → rc=2(需人工)。**絕不可以是 1**:1 會被 runner 讀成「今天沒事」
    check("cli/bad-arg", run_cli(["--nope"], env).returncode, 2)
    check("cli/bad-record", run_cli(["record", "xxx", "k"], env).returncode, 2)
    # 空 key 會寫進帳本 → read_ledger 從此永久回報「缺 key」→ 所有 key 只 escalate 不自動修
    check("cli/record-empty-key", run_cli(["record", "attempted", ""], env).returncode, 2)
    check("cli/window-missing-value", run_cli(["--window"], env).returncode, 2)
    check("cli/window-nonnumeric", run_cli(["--window", "abc"], env).returncode, 2)
    # 分流器自己炸了 → rc=3(CRASH_RC),與「無事」分開,runner 才推得出「守衛死了」
    crash = run_cli([], dict(env, MD_CHRONIC_NOW="not-a-date"))
    check("cli/crash-rc", crash.returncode, ct.CRASH_RC)
    check_true("cli/crash-traceback", "Traceback" in crash.stderr, crash.stderr[-200:])
    # 小窗口手跑不可恆為失明(MIN_SHIFTS 要夾住 window)
    check("cli/small-window", run_cli(["--window", "3", "--json"], env).returncode in (0, 1, 2), True)
    small = json.loads(run_cli(["--window", "3", "--json"], env).stdout)
    check("cli/small-window-not-blind", small["blind"], "")
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
