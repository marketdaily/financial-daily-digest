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
# 簡單變數賦值:`VAR="value"` / `VAR=value`(一行可用 `;` 分隔多個)。
RE_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\"(?:[^\"\\]|\\.)*\"|\S+)$")
# 行首 `cd <expr>`(忽略後面的 `|| exit 1` 等)。
RE_CD = re.compile(r"^cd\s+(\"(?:[^\"\\]|\\.)*\"|\S+)")
RE_VARREF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _resolve(expr: str, varmap: dict[str, str]) -> str:
    """展開 `$VAR`/`${VAR}`,只用已知變數表——查不到的原樣留著(不猜)。"""
    expr = _strip_quotes(expr)
    for _ in range(5):
        new = RE_VARREF.sub(lambda m: varmap.get(m.group(1), m.group(0)), expr)
        if new == expr:
            break
        expr = new
    return expr


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


def module_exists(mod: str, base: Path) -> bool:
    """不 import(避免副作用/耗時),純檔案系統解析 pkg.mod → pkg/mod.py 或 pkg/mod/__init__.py。"""
    rel = Path(*mod.split("."))
    return (base / rel.with_suffix(".py")).is_file() or (base / rel / "__init__.py").is_file()


def scan() -> list[str]:
    """逐行掃描,同時追蹤 `cd` 目標——runner 若先 `cd` 進另一個 repo(例如 fortune-ai)
    才呼叫 `-m scripts.foo`,該模組要對著那個 repo 驗證,而不是永遠假設是本 repo(Delvin-agent)。
    2026-08-06 事故:mingshu_pages_runner.sh 先 `cd "$FORTUNE"` 才跑
    `python -m scripts.seo.build_pages`(fortune-ai/scripts/seo/build_pages.py 真實存在),
    舊版永遠對 Delvin-agent/scripts/seo/ 驗證(不存在)→ 連兩天假陽性推播 admin。
    """
    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    for src, text in shell_sources():
        varmap: dict[str, str] = {"HOME": str(Path.home())}
        base = REPO
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for segment in s.split(";"):
                m = RE_ASSIGN.match(segment.strip())
                if m:
                    varmap[m.group(1)] = _resolve(m.group(2), varmap)
            m = RE_CD.match(s)
            if m:
                target = Path(_resolve(m.group(1), varmap))
                if target.is_absolute() and target.is_dir():
                    base = target
            for mod in RE_MODULE.findall(s):
                # 只查該 base 下的套件(第一段是既存目錄),外部套件如 -m pip 略過
                if not (base / mod.split(".")[0]).is_dir():
                    continue
                if (src, mod) in seen or module_exists(mod, base):
                    continue
                seen.add((src, mod))
                missing.append(f"{src}: python -m {mod} → 模組不存在({base})")
            for rel in RE_SCRIPT.findall(s):
                if (src, rel) in seen or (base / rel).is_file():
                    continue
                seen.add((src, rel))
                missing.append(f"{src}: {rel} → 檔案不存在({base})")
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
