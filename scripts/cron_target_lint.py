#!/usr/bin/env python3
"""cron 目標存在性守衛:每個 cron runner 呼叫的 python 模組/腳本是否真的還在。

2026-07-30 事故:intel/reddit_buzz.py 在 07-23 main 重對齊時遺失(只活在 backup 分支),
reddit_buzz cron 從此每天 `No module named intel.reddit_buzz` 失敗一週才被人眼在告警頁看到。
單一 runner 的 cron_run_and_alert 會推播,但「檔案不見了」這件事本身沒人在事前檢查——
本守衛把整類失敗(git 操作弄丟被 cron 依賴的檔案)變成事前可偵測。

掃描來源:crontab + ~/.marketdaily-fallback/*.sh 的 `-m <module>` 與 `<path>.py` 呼叫。
exit 1 = 有解析不到的目標(呼叫端負責推播);exit 0 = 全部存在。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FALLBACK = Path.home() / ".marketdaily-fallback"

# `python -m pkg.mod` / `"$PY" -m pkg.mod`
RE_MODULE = re.compile(r"-m\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
# `"$REPO/scripts/foo.py"` / `$REPO/intel/bar.py` / 裸 scripts/foo.py。
# (?<![/\w]) 是必要的:少了它,別的 repo 的絕對路徑(/home/userdelvin/cb-desk/scripts/eod_snapshot.py)
# 尾段會被誤認成本 repo 的相對路徑 → 假陽性(首跑實地踩到)。
RE_SCRIPT = re.compile(
    r"(?<![/\w])(?:\$\{?REPO\}?/|\$\{?HOME\}?/Delvin-agent/)?"
    r"((?:scripts|intel|marketing|quant_lab|cb_analyzer|audio_brief)/[A-Za-z0-9_./-]+\.py)")


def shell_sources() -> list[tuple[str, str]]:
    """回傳 [(來源名, 內容)]:crontab 全文 + 每個 fallback runner。"""
    out: list[tuple[str, str]] = []
    try:
        ct = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        if ct.returncode == 0:
            out.append(("crontab", ct.stdout))
    except Exception:
        pass
    if FALLBACK.is_dir():
        for sh in sorted(FALLBACK.glob("*.sh")):
            try:
                out.append((f"fallback/{sh.name}", sh.read_text(errors="replace")))
            except OSError:
                continue
    return out


def module_exists(mod: str) -> bool:
    """不 import(避免副作用/耗時),純檔案系統解析 pkg.mod → pkg/mod.py 或 pkg/mod/__init__.py。"""
    rel = Path(*mod.split("."))
    return (REPO / rel.with_suffix(".py")).is_file() or (REPO / rel / "__init__.py").is_file()


def scan() -> list[str]:
    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    for src, text in shell_sources():
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for mod in RE_MODULE.findall(s):
                # 只查本 repo 的套件(第一段是 repo 內既存目錄),外部套件如 -m pip 略過
                if not (REPO / mod.split(".")[0]).is_dir():
                    continue
                if (src, mod) in seen or module_exists(mod):
                    continue
                seen.add((src, mod))
                missing.append(f"{src}: python -m {mod} → 模組不存在")
            for rel in RE_SCRIPT.findall(s):
                if (src, rel) in seen or (REPO / rel).is_file():
                    continue
                seen.add((src, rel))
                missing.append(f"{src}: {rel} → 檔案不存在")
    return missing


def main() -> int:
    missing = scan()
    if not missing:
        print("✅ cron 目標存在性:全部呼叫的模組/腳本都在")
        return 0
    print(f"✗ cron 目標缺失 {len(missing)} 項(cron 會每次失敗):")
    for m in missing:
        print(f"  - {m}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
