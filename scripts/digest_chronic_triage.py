#!/usr/bin/env python3
"""寄後複檢「慢性失分」分流器(2026-08-03)。確定性、唯讀、零 LLM。

## 為什麼存在
`digest_postcheck` 每班會把失分推播一則 admin 告警,`digest_selfheal` 會在**硬錯備援**時
自動根因修。中間有一整片沒人接的地帶:**沒掉備援、但每隔幾班就再犯的 soft 失分**——
2026-07-24~08-01 實測:`signal_reason_shallow` 3 班、個人語音 4 班(橫跨兩週),
全部只有推播、沒有任何自動接手,靠人工盤點才被發現。推播不等於有人修。

本模組把「同一種失分反覆出現」變成可被機器接手的立案:
  ①唯讀解析既有 `logs/postcheck_<date>_<ed>.log`(不改 postcheck 的執行路徑)
  ②慢性判準:近 WINDOW 班內同一 key ≥ MIN_HITS 次,且最近 RECENT_SHIFTS 班內至少犯 1 次
  ③分類:可自動根因修 / 只能升級給人 / 基礎設施(別碰)
  ④帳本 cooldown + 升級:修過還再犯 → 停手改叫人,不無限重刷 token

## 反假綠設計(這類偵測器最常見的死法)
- **解析漂移**:postcheck 的 header 自己會寫「N 個問題」,解析出的條目數必須等於 N。
  不等 = 生產端格式改了而我沒跟上 → 回報 `parse_drift` 並要求告警,**絕不安靜地少算失分**
  (lesson `producer_format_drift_kills_consumers`)。
- **失明**:窗口內拿不到足夠有判決的班次(log 消失/postcheck 死掉)→ 回報 `blind`,
  不准把「看不到」當成「沒問題」。
- **帳本壞掉**:cooldown 判斷不了就不 spawn(避免重複立案),但一定告警(不靜默)。

## 介面
    python3 scripts/digest_chronic_triage.py [--window 10] [--min-hits 3] [--json]
exit 0 = 有可自動修的慢性失分(runner 應 spawn 修復代理)
exit 1 = 無事(安靜退)
exit 2 = 有事但不該自動修(升級給人 / 偵測器自己瞎了 / 帳本壞了)→ runner 只推播
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent

WINDOW = 10          # 往回看幾個「有判決的班次」
MIN_HITS = 3         # 同一 key 在窗口內犯幾次算慢性
RECENT_SHIFTS = 4    # 最近幾班內至少要犯 1 次(否則視為已止血,不重複立案)
MIN_SHIFTS = 4       # 窗口內少於這麼多班有判決 = 偵測器失明
COOLDOWN_DAYS = 5    # 同一 key 立案後的冷卻天數(給修復生效的時間)
MAX_ATTEMPTS = 2     # 自動修嘗試上限,超過改叫人

# 前綴 → 穩定 key。postcheck 的失分行一律長成 `  - [前綴] 內文`。
PREFIX_SLUG = {
    "archive": "archive",
    "交付": "delivery",
    "語音": "audio",
    "語音稿": "narration",
    "個人語音": "personal_audio",
    "reel": "reel",
    "LLM鏈": "llm_chain",
}
# 基礎設施類:改碼救不了(免費 LLM 桶枯竭),而且 postcheck 內建的 llm_chain_triage 已經在
# 分流+推播。放進來只會製造第二則重複告警(lesson: alert storm dedup)。
INFRA_KEYS = {"llm_chain"}
# 只能升級給人的:自動改碼的風險/半徑遠大於收益。
ESCALATE_ONLY_KEYS = {"delivery"}

VERDICT_FAIL_RE = re.compile(r"^✗ 寄後複檢 (\d{4}-\d{2}-\d{2}) (tw|us):(\d+) 個問題")
VERDICT_PASS_RE = re.compile(r"^✓ 寄後複檢 (\d{4}-\d{2}-\d{2}) (tw|us) ")
SKIP_RE = re.compile(r"跳過複檢")
MAX_GAPS = 2         # 近 7 天有這麼多「該有判決卻沒有」的班次 = postcheck 自己可能死了
FINDING_RE = re.compile(r"^ {2}- (.*)$")
LOGNAME_RE = re.compile(r"^postcheck_(\d{4}-\d{2}-\d{2})_(tw|us)\.log$")
PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
ARCHIVE_CHECK_RE = re.compile(r"^([a-z0-9_]+):")


def _now_tw():
    """台北時間的現在;`MD_CHRONIC_NOW`(ISO)可覆寫供測試造時序情境。"""
    override = os.environ.get("MD_CHRONIC_NOW")
    if override:
        return datetime.fromisoformat(override).replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return datetime.now(ZoneInfo("Asia/Taipei"))


def _log_dir():
    return Path(os.environ.get("MD_CHRONIC_LOGDIR") or (REPO / "logs"))


def _ledger_path():
    """帳本刻意放在 repo **之外**:它是「已經立過案」的唯一記憶,放 repo 內未追蹤的話
    `git clean -fd` 會把它清光 → cooldown/嘗試次數歸零 → 同一個 key 被無限重複立案
    (2026-08-03 永豐守望器剛踩過同款坑)。手跑與 cron 走同一個預設路徑,才不會出現
    「我手動跑看到的狀態跟生產不一樣」的陷阱;測試一律用 MD_CHRONIC_LEDGER 覆寫。"""
    return Path(os.environ.get("MD_CHRONIC_LEDGER")
                or (Path.home() / ".marketdaily-fallback" / "state" / "postcheck_chronic_ledger.jsonl"))


def finding_key(text):
    """一行失分 → (key, variant)。key 用來數慢性次數,variant 只是給修復代理看的證據。

    `[archive] signal_reason_shallow: ...` → `archive:signal_reason_shallow`
    `[個人語音] 15/15 支...`               → `personal_audio`
    認不得的前綴 → `other:<原前綴>`(**不准丟掉**:認不得也要被數到,否則新種失分永遠隱形)
    完全沒有前綴 → `unstructured`(同時會被上層當成解析漂移的旁證)
    """
    text = text.strip()
    m = PREFIX_RE.match(text)
    if not m:
        return "unstructured", text[:120]
    prefix, rest = m.group(1).strip(), m.group(2).strip()
    slug = PREFIX_SLUG.get(prefix)
    if slug is None:
        return f"other:{prefix}", rest[:120]
    if slug == "archive":
        c = ARCHIVE_CHECK_RE.match(rest)
        if c:
            return f"archive:{c.group(1)}", rest[:160]
        return "archive:unknown", rest[:160]
    return slug, rest[:160]


def parse_shift_log(path):
    """解析單一班次 log → dict。取【最後一個】判決區塊:runner 的 defer 會放鎖重跑,
    同一個檔案裡會有多輪輸出,只有最後一輪才是這一班的定案。"""
    out = {"path": str(path), "verdict": None, "date": None, "edition": None,
           "declared": None, "findings": [], "parse_drift": ""}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        out["parse_drift"] = f"log 讀取失敗:{e}"
        return out

    last_idx, last_kind, last_m = None, None, None
    for i, ln in enumerate(lines):
        m = VERDICT_FAIL_RE.match(ln)
        if m:
            last_idx, last_kind, last_m = i, "fail", m
            continue
        m = VERDICT_PASS_RE.match(ln)
        if m:
            last_idx, last_kind, last_m = i, "pass", m
    if last_idx is None:
        # 美股休市夜:腳本印「跳過複檢」就 return 0,沒有判決行——那是預期行為,不是缺件
        out["verdict"] = "skip" if any(SKIP_RE.search(ln) for ln in lines) else "none"
        return out

    out["date"], out["edition"] = last_m.group(1), last_m.group(2)
    if last_kind == "pass":
        out["verdict"] = "pass"
        return out

    out["verdict"] = "fail"
    out["declared"] = int(last_m.group(3))
    for ln in lines[last_idx + 1:]:
        if ln.startswith("==="):
            break
        m = FINDING_RE.match(ln)
        if m:
            out["findings"].append(m.group(1))
        elif VERDICT_FAIL_RE.match(ln) or VERDICT_PASS_RE.match(ln):
            break
    if len(out["findings"]) != out["declared"]:
        out["parse_drift"] = (f"header 宣告 {out['declared']} 個問題,實際解析出 "
                              f"{len(out['findings'])} 條 —— postcheck 輸出格式可能已改")
    return out


def collect_shifts(window=WINDOW, log_dir=None):
    """近 window 個【有判決】的班次,舊→新。班次序:同日 tw 早於 us。"""
    log_dir = Path(log_dir) if log_dir else _log_dir()
    entries = []
    if log_dir.is_dir():
        for p in log_dir.iterdir():
            m = LOGNAME_RE.match(p.name)
            if m:
                entries.append(((m.group(1), 0 if m.group(2) == "tw" else 1), p))
    entries.sort(key=lambda t: t[0])
    shifts = []
    for _, p in entries:
        s = parse_shift_log(p)
        if s["verdict"] in ("fail", "pass"):
            shifts.append(s)
    return shifts[-window:]


def expected_shifts(now, days=7):
    """近 days 天【硬死線已過】的班次清單(舊→新)。班表照 postcheck runner:
    週日無班次;週六只有早報(晚報週末停發);平日 tw+us。
    硬死線 = TW 09:00 / US 23:00(台北),沒過死線的班次不算缺件(它可能正要跑)。"""
    out = []
    for i in range(days, -1, -1):
        d = (now - timedelta(days=i)).date()
        wd = d.isoweekday()
        if wd == 7:
            continue
        for ed, deadline_min in (("tw", 9 * 60), ("us", 23 * 60)):
            if ed == "us" and wd == 6:
                continue
            dl = datetime.combine(d, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(minutes=deadline_min)
            if dl <= now:
                out.append((d.isoformat(), ed))
    return out


def coverage_gaps(now, days=7, log_dir=None):
    """該有判決卻查不到的班次。postcheck 是「檢查者」,**沒有人在檢查檢查者**——
    它整支死掉的樣子就是「什麼告警都沒有」,跟一切正常長得一模一樣(feedback_incident_to_detector)。"""
    log_dir = Path(log_dir) if log_dir else _log_dir()
    gaps = []
    for date_iso, ed in expected_shifts(now, days=days):
        p = log_dir / f"postcheck_{date_iso}_{ed}.log"
        if not p.exists():
            gaps.append(f"{date_iso}/{ed}(無 log)")
            continue
        v = parse_shift_log(p)["verdict"]
        if v in ("fail", "pass", "skip"):
            continue
        gaps.append(f"{date_iso}/{ed}(log 內無判決)")
    return gaps


def read_ledger(path=None):
    """回傳 (records, broken_reason)。壞掉時 records 仍回已讀到的部分,但 broken 非空
    → 上層必須改走「不 spawn + 告警」,不可當作沒事(fail-closed 且看得見)。"""
    path = Path(path) if path else _ledger_path()
    recs, broken = [], ""
    if not path.exists():
        return recs, ""
    try:
        for i, ln in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                broken = f"第 {i} 行不是合法 JSON"
                continue
            if not isinstance(r, dict) or not r.get("key") or not r.get("date"):
                broken = f"第 {i} 行缺 key/date 欄位"
                continue
            recs.append(r)
    except OSError as e:
        return recs, f"讀取失敗:{e}"
    return recs, broken


def append_ledger(rec, path=None):
    path = Path(path) if path else _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _days_since(date_iso, now):
    try:
        d = datetime.fromisoformat(date_iso).date()
    except ValueError:
        return None
    return (now.date() - d).days


def ledger_state(key, recs, now):
    """這個 key 現在該怎麼辦 → dict(attempts, last_attempt_date, cooling, resolved_after)。

    `resolved` 記錄= 人工或後續驗證確認修好了 → 之前的 attempts 一筆勾銷(否則一個 key
    一輩子只能被自動修兩次,半年後同名新 bug 就永遠叫不動機器)。
    """
    st = {"attempts": 0, "last_attempt_date": "", "cooling": False, "cool_days_left": 0}
    resolved_at = None
    for r in recs:
        if r.get("key") != key:
            continue
        if r.get("action") == "resolved":
            resolved_at = r.get("date")
    for r in recs:
        if r.get("key") != key:
            continue
        if resolved_at and str(r.get("date", "")) <= str(resolved_at):
            continue
        if r.get("action") in ("attempted", "applied", "blocked"):
            st["attempts"] += 1
            if str(r.get("date", "")) > st["last_attempt_date"]:
                st["last_attempt_date"] = str(r.get("date", ""))
    if st["last_attempt_date"]:
        d = _days_since(st["last_attempt_date"], now)
        if d is None:
            # 日期壞掉(手改帳本/寫入截斷):算不出冷卻 → 當成冷卻中。寧可晚一天立案,
            # 也不要因為「讀不懂帳本」而天天重複 spawn 修復代理。
            st["cooling"], st["cool_days_left"] = True, COOLDOWN_DAYS
        elif d < COOLDOWN_DAYS:
            # d<0(未來日期,時鐘錯亂)也落在這裡 → 一樣算冷卻中
            st["cooling"], st["cool_days_left"] = True, COOLDOWN_DAYS - d
    return st


def triage(window=WINDOW, min_hits=MIN_HITS, now=None, log_dir=None, ledger=None, gap_days=None):
    now = now or _now_tw()
    if gap_days is None:
        gap_days = int(os.environ.get("MD_CHRONIC_GAP_DAYS", 7))
    shifts = collect_shifts(window=window, log_dir=log_dir)
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "shifts_seen": len(shifts),
        "window": window, "min_hits": min_hits,
        "blind": "", "gaps": [], "parse_drift": [], "ledger_broken": "",
        "chronic": [], "fix": [], "escalate": [], "cooling": [],
        "verdict": "clean",
    }

    for s in shifts:
        if s["parse_drift"]:
            out["parse_drift"].append({"log": Path(s["path"]).name, "why": s["parse_drift"]})

    out["gaps"] = coverage_gaps(now, days=gap_days, log_dir=log_dir) if gap_days else []
    blind_bits = []
    if len(shifts) < MIN_SHIFTS:
        blind_bits.append(f"窗口內只找到 {len(shifts)} 個有判決的班次(<{MIN_SHIFTS})——"
                          "postcheck 可能沒在跑,或 log 被清掉;看不到 ≠ 沒問題")
    if len(out["gaps"]) >= MAX_GAPS:
        blind_bits.append(f"近 7 天有 {len(out['gaps'])} 個班次該有判決卻查不到:"
                          + "、".join(out["gaps"]) + " —— 寄後複檢本身可能沒在跑")
    out["blind"] = " | ".join(blind_bits)

    hits = {}      # key -> {shifts:[...], samples:[...]}
    recent_keys = set()
    for idx, s in enumerate(shifts):
        if s["verdict"] != "fail":
            continue
        seen_this_shift = set()
        for text in s["findings"]:
            key, variant = finding_key(text)
            if key in seen_this_shift:
                continue          # 同一班同一 key 只算一次(15/15 支不是 15 次慢性)
            seen_this_shift.add(key)
            h = hits.setdefault(key, {"shifts": [], "samples": []})
            h["shifts"].append(f"{s['date']}/{s['edition']}")
            if len(h["samples"]) < 3:
                h["samples"].append(variant)
            if idx >= len(shifts) - RECENT_SHIFTS:
                recent_keys.add(key)

    recs, broken = read_ledger(ledger)
    out["ledger_broken"] = broken

    for key, h in sorted(hits.items()):
        n = len(h["shifts"])
        if n < min_hits or key not in recent_keys:
            continue
        item = {"key": key, "hits": n, "shifts": h["shifts"], "samples": h["samples"]}
        out["chronic"].append(item)
        if key in INFRA_KEYS:
            item["route"] = "infra_ignored"
            continue
        st = ledger_state(key, recs, now)
        item.update(attempts=st["attempts"], last_attempt=st["last_attempt_date"])
        if key in ESCALATE_ONLY_KEYS or key.startswith("other:") or key == "unstructured":
            item["route"] = "escalate"
            item["why"] = "此類失分不開放自動改碼(半徑/風險過大或型別未知),直接叫人"
            out["escalate"].append(item)
        elif st["attempts"] >= MAX_ATTEMPTS:
            item["route"] = "escalate"
            item["why"] = f"已自動修 {st['attempts']} 次仍再犯 —— 自動修顯然沒打到根因,交人工"
            out["escalate"].append(item)
        elif st["cooling"]:
            item["route"] = "cooling"
            item["why"] = f"{st['last_attempt_date']} 才立過案,冷卻中(還剩 {st['cool_days_left']} 天)"
            out["cooling"].append(item)
        elif broken:
            item["route"] = "escalate"
            item["why"] = f"帳本壞了({broken}),判斷不了是否重複立案 → 不自動修,叫人"
            out["escalate"].append(item)
        elif out["blind"] or out["parse_drift"]:
            # 資料來源本身可疑(複檢沒在跑 / 輸出格式變了)時,不准在不可信的資料上自動改碼。
            # 這時最該做的是讓人知道「偵測層瞎了」,而不是安靜地照舊立案。
            item["route"] = "escalate"
            item["why"] = "偵測層可能失明或解析漂移,先修偵測層再談自動改碼"
            out["escalate"].append(item)
        else:
            item["route"] = "fix"
            out["fix"].append(item)

    if out["fix"]:
        out["verdict"] = "fix"
    elif out["escalate"] or out["blind"] or out["parse_drift"] or out["ledger_broken"]:
        out["verdict"] = "escalate"
    elif out["cooling"]:
        out["verdict"] = "cooling"
    return out


def summary_line(res):
    if res["verdict"] == "fix":
        return "🩺 慢性失分立案:" + "、".join(
            f"{i['key']}({i['hits']}/{res['shifts_seen']} 班)" for i in res["fix"])
    bits = []
    if res["blind"]:
        bits.append(f"偵測器失明:{res['blind']}")
    if res["parse_drift"]:
        bits.append("解析漂移:" + "; ".join(f"{d['log']} {d['why']}" for d in res["parse_drift"]))
    if res["ledger_broken"]:
        bits.append(f"帳本壞損:{res['ledger_broken']}")
    for i in res["escalate"]:
        bits.append(f"{i['key']}({i['hits']}/{res['shifts_seen']} 班)→ {i.get('why', '')}")
    if bits:
        return "⚠️ 寄後複檢慢性失分需人工:" + " | ".join(bits)
    if res["cooling"]:
        return "🟡 慢性失分冷卻中:" + "、".join(f"{i['key']}({i.get('why', '')})" for i in res["cooling"])
    return f"✓ 近 {res['shifts_seen']} 班無慢性失分"


def main(argv):
    if argv and argv[0] == "record":
        # 用法:record <action> <key> [note]   —— 給 runner(bash)記帳用
        if len(argv) < 3 or argv[1] not in ("attempted", "applied", "blocked", "escalated", "resolved"):
            raise SystemExit("用法:record <attempted|applied|blocked|escalated|resolved> <key> [note]")
        now = _now_tw()
        append_ledger({"ts": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
                       "key": argv[2], "action": argv[1], "note": " ".join(argv[3:])})
        print(f"記帳:{argv[1]} {argv[2]}")
        return 0

    window, min_hits, as_json = WINDOW, MIN_HITS, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--window":
            i += 1
            window = int(argv[i])
        elif a == "--min-hits":
            i += 1
            min_hits = int(argv[i])
        elif a == "--json":
            as_json = True
        else:
            raise SystemExit(f"未知參數 {a!r}(用法:--window N --min-hits N --json)")
        i += 1
    res = triage(window=window, min_hits=min_hits)
    if as_json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(summary_line(res))
    return {"fix": 0, "escalate": 2, "cooling": 1, "clean": 1}[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
