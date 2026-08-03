#!/usr/bin/env python3
"""突變測試:確認 test_digest_chronic_triage.py 真的咬得住(每個突變都必須讓它變紅)。

⭐ 先跑 **baseline 閘**:未突變的副本在沙盒裡必須是綠的。少了這一步,「全部咬到」可能只是
因為沙盒本身壞掉(缺檔/路徑不對)導致每次都紅——那是假綠的鏡像版,一樣騙人
(2026-08-03 永豐守望器突變測試踩過同款坑)。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.home() / "Delvin-agent"
SRC = REPO / "scripts"
PY = str(REPO / ".venv" / "bin" / "python")
TARGET = "digest_chronic_triage.py"

MUTS = [
    ("慢性門檻失效", "MIN_HITS = 3", "MIN_HITS = 99"),
    ("近期閘失效(陳年舊帳照樣立案)", "RECENT_SHIFTS = 4", "RECENT_SHIFTS = 999"),
    ("解析漂移不回報", 'if len(out["findings"]) != out["declared"]:', "if False:"),
    ("同班同 key 不去重", "            if key in seen_this_shift:\n                continue",
                          "            if False:\n                continue"),
    ("只認第一個判決(defer 舊結果覆蓋定案)",
     '            last_idx, last_kind, last_m = i, "fail", m\n            continue',
     '            if last_idx is None:\n                last_idx, last_kind, last_m = i, "fail", m\n            continue'),
    ("infra 類不再被排除", 'INFRA_KEYS = {"llm_chain"}', "INFRA_KEYS = set()"),
    ("只升級類被拿去自動改碼", 'ESCALATE_ONLY_KEYS = {"delivery", "archive:missing_archive"}',
                               "ESCALATE_ONLY_KEYS = set()"),
    ("冷卻失效(天天重複立案)", "COOLDOWN_DAYS = 5", "COOLDOWN_DAYS = 0"),
    ("嘗試上限失效(修不好也一直修)", "MAX_ATTEMPTS = 2", "MAX_ATTEMPTS = 99"),
    ("壞帳本照樣自動修", "        elif broken:", "        elif False:"),
    ("失明時照樣自動改碼", '        elif out["blind"] or out["parse_drift"]:', "        elif False:"),
    ("美股休市被當成缺件", 'out["verdict"] = "skip" if any(SKIP_RE.search(ln) for ln in lines) else "none"',
                            'out["verdict"] = "none"'),
    ("缺件門檻失效", "MAX_GAPS = 2", "MAX_GAPS = 99"),
    ("週日被當成有班次", "        if wd == 7:\n            continue", "        if False:\n            continue"),
    ("週六晚報被當成有班次", '            if ed == "us" and wd == 6:\n                continue',
                              '            if False:\n                continue'),
    ("硬死線沒過就算缺件", "            if dl <= now:", "            if True:"),
    ("認不得的前綴被靜默吃掉", '        return f"other:{prefix}", rest[:120]', '        return "llm_chain", rest[:120]'),
    ("升級的 exit code 退化成無事", '"escalate": 2', '"escalate": 1'),
    # ── 第 1 輪驗證者 findings 的迴歸(這些突變=舊版的原形,必須被咬住)──
    ("F2 例外沒被轉成 CRASH_RC(炸了長得像沒事)", "        return CRASH_RC", "        return 1"),
    ("F2 用法錯回 1(會被 runner 讀成今天沒事)", '            return 2      # 用法錯',
                                                  '            return 1      # 用法錯'),
    ("F3 結局記錄也計入嘗試次數(跑一次=用掉兩次額度)",
     '        if action == "attempted":\n            started[d] = True',
     '        if action in ("attempted", "applied", "blocked"):\n            started[d + action] = True'),
    ("F3 中止型結局也燒額度(一次網路抖動永久封鎖)",
     '    real = [d for d in all_days if d not in aborted]  # 額度只算「真的用掉的那幾天」',
     '    real = list(all_days)'),
    ("升級提醒永遠不重講(講一次就永久閉嘴)", "    if not last_date:\n        return True",
                                              "    if last_date:\n        return False"),
    ("升級提醒不去重(每天推同一則)", '        out["notify"] = infra_level or any',
                                      '        out["notify"] = True or any'),
    ("偵測層自己的問題被降噪(守衛瞎了卻不吵)", "        infra_level = bool(", "        infra_level = False and bool("),
    ("e2e 前綴不併回子系統(靈敏度稀釋)", '    "個人語音e2e": "personal_audio",', '    "個人語音e2e": "pa_e2e",'),
    ("公版存檔不存在被當成沒判決(誤報成複檢沒在跑)", '    if last_kind == "missing_archive":', "    if False:"),
    ("壞帳本只報最後一種損壞", '    head = "、".join(bad[:3])', '    head = "、".join(bad[-1:])'),
    ("MIN_SHIFTS 不夾住 window(小窗口恆失明)", "    min_shifts = min(MIN_SHIFTS, window)", "    min_shifts = MIN_SHIFTS"),
    # ── 第 2 輪驗證者 findings 的迴歸 ──
    ("F1 冷卻跟著 aborted 一起被扣掉(持續中止=每天燒一次 opus)",
     '        d = _days_since(st["last_started_date"], now)', '        d = _days_since(st["last_attempt_date"], now)'),
    ("F1 連續中止不會升級(永遠等不到叫人)", "        elif st[\"consecutive_aborted\"] >= MAX_CONSECUTIVE_ABORTED:",
                                            "        elif False:"),
    ("F3 帳本日期壞值不算壞掉(靜靜變成永久冷卻)", "            if _days_since(r[\"date\"], now_hint) is None:",
                                                  "            if False:"),
    ("F3 未來日期不算壞掉(冷卻 36325 天=永久靜音)", "            if _days_since(r[\"date\"], now_hint) < 0:",
                                                    "            if False:"),
    ("F3 型別漂移靜默通過(該筆記帳等於消失)",
     '            if not all(isinstance(r.get(k), str) for k in ("key", "date")) \\',
     '            if False and not all(isinstance(r.get(k), str) for k in ("key", "date")) \\'),
    ("F6 一輪立多個 key(沒碰到的 key 也被記結局)", "    if len(out[\"fix\"]) > 1:", "    if False:"),
    ("F7 跨日曆天下限失效(一天半的插曲當慢性病)", "        if days < MIN_DAYS:", "        if False:"),
    ("F7 MIN_DAYS 被調成 1(等於沒有這條規則)", "MIN_DAYS = 3", "MIN_DAYS = 1"),
    ("record 接受空 key(帳本從此永久回報壞行)", "        if not argv[2].strip():", "        if False:"),
]


def sandbox(td, mutated=None):
    """把測試需要的三個檔+真實 logs 語料複製進沙盒。mutated=None 表示 baseline。"""
    td = Path(td)
    for f in ("test_digest_chronic_triage.py", "digest_postcheck.py", TARGET):
        shutil.copy(SRC / f, td)
    logs = td / "logs"
    logs.mkdir()
    for p in sorted((REPO / "logs").glob("postcheck_*.log"))[-14:]:
        shutil.copy(p, logs)
    if mutated is not None:
        (td / TARGET).write_text(mutated, encoding="utf-8")
    env = dict(os.environ, MD_CHRONIC_REAL_LOGS=str(logs))
    return subprocess.run([PY, str(td / "test_digest_chronic_triage.py")],
                          capture_output=True, text=True, cwd=td, env=env)


bad = []
with tempfile.TemporaryDirectory() as td:
    r = sandbox(td)
    if r.returncode != 0:
        print("❌ baseline 閘未過:沒突變的副本在沙盒裡就是紅的,後面「全部咬到」不可信")
        print(r.stdout[-1500:], r.stderr[-800:])
        sys.exit(1)
print("[baseline] 未突變副本在沙盒內全綠 ✓")

src = (SRC / TARGET).read_text(encoding="utf-8")
for name, a, b in MUTS:
    if a not in src:
        bad.append(f"{name}: 突變錨點找不到")
        print(f"[{name}] 錨點找不到✗")
        continue
    with tempfile.TemporaryDirectory() as td:
        r = sandbox(td, src.replace(a, b, 1))
    status = "咬到✓" if r.returncode != 0 else "沒咬到✗"
    print(f"[{name}] rc={r.returncode} {status}")
    if r.returncode == 0:
        bad.append(name)

print(("❌ 未咬到:" + "、".join(bad)) if bad else f"✓ 突變測試 {len(MUTS)}/{len(MUTS)} 全咬到")
sys.exit(1 if bad else 0)
