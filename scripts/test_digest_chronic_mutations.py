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
    ("只升級類被拿去自動改碼", 'ESCALATE_ONLY_KEYS = {"delivery"}', "ESCALATE_ONLY_KEYS = set()"),
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
