#!/usr/bin/env python3
r"""cron 目標存在性守衛:每個 cron runner 呼叫的 python 模組/腳本是否真的還在。

2026-07-30 事故:intel/reddit_buzz.py 在 07-23 main 重對齊時遺失(只活在 backup 分支),
reddit_buzz cron 從此每天 `No module named intel.reddit_buzz` 失敗一週才被人眼在告警頁看到。
單一 runner 的 cron_run_and_alert 會推播,但「檔案不見了」這件事本身沒人在事前檢查——
本守衛把整類失敗(git 操作弄丟被 cron 依賴的檔案)變成事前可偵測。

掃描來源:crontab + ~/.marketdaily-fallback/*.sh 的 `-m <module>` 與 `<path>.py` 呼叫。
exit 1 = 有解析不到的目標(呼叫端負責推播);exit 0 = 全部存在。

⚠️ 2026-08-12 兩處根治(別回頭簡化):
  1. **路徑解析改用共用積木 `~/autonomous/capabilities/cron_call_resolver`**。舊版自己刻的
     `RE_CD` 是行首錨定 + 只採絕對路徑的**第一個 cd**,碰到
     `cd ~/paper_trade && git pull; cd quant_lab/auto_trade && python3 paper_daily.py`
     這種兩段 cd 串接就解錯。`fleet_snapshot/coverage.py` 手刻的那份有一模一樣的 bug,
     還因此把 5 支真實存在的生產腳本報成「檔案不存在」。兩份手刻、同時錯 ⇒ 收斂成一份。
  2. **拔掉目錄白名單**。舊版 RE_SCRIPT 只認 Delvin-agent 底下 6 個目錄
     (scripts|intel|marketing|quant_lab|cb_analyzer|audio_brief),而且 `(?<![/\w])`
     lookbehind 會擋掉絕對路徑 ⇒ 全艦隊 140 個 cron 呼叫點裡,跨專案的那些
     (paper_trade / cardvault-pc / cb-desk / fortune-ai / taifex_archive / storefront /
     autonomous)**一個都檢查不到**,卻天天印「✅ 全部都在」。守衛的偵測面 = 它能救的面;
     接線守衛不准吃固定名單。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "autonomous" / "capabilities" / "cron_call_resolver"))
from resolve import scan_source  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FALLBACK = Path.home() / ".marketdaily-fallback"


def shell_sources() -> list[tuple[str, str, str, str | None]]:
    """回傳 [(來源名, 內容, mode, initial_cwd)]:crontab 全文 + 每個 fallback runner。

    mode 決定 cwd 語意:crontab 每行是獨立 job(逐行重置為 $HOME);.sh 是由上往下執行
    的同一支程式(cwd 累積),起始 cwd 未知 → None ⇒ 相對路徑判 unresolvable 而非缺失。
    """
    out: list[tuple[str, str, str, str | None]] = []
    try:
        ct = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        if ct.returncode == 0:
            out.append(("crontab", ct.stdout, "crontab", None))
    except Exception:
        pass
    if FALLBACK.is_dir():
        for sh in sorted(FALLBACK.glob("*.sh")):
            try:
                out.append((f"fallback/{sh.name}", sh.read_text(errors="replace"),
                            "script", None))
            except OSError:
                continue
    return out


def module_exists(mod: str, base: Path) -> bool:
    """不 import(避免副作用/耗時),純檔案系統解析 pkg.mod → pkg/mod.py 或 pkg/mod/__init__.py。"""
    rel = Path(*mod.split("."))
    return (base / rel.with_suffix(".py")).is_file() or (base / rel / "__init__.py").is_file()


def scan() -> tuple[list[str], list[str]]:
    """回傳 (缺失清單, 解析不出來的清單)。

    cwd 追蹤交給 cron_call_resolver——runner 若先 `cd` 進另一個 repo(例如 fortune-ai)
    才呼叫 `-m scripts.foo`,該模組要對著那個 repo 驗證,而不是永遠假設是本 repo(Delvin-agent)。
    2026-08-06 事故:mingshu_pages_runner.sh 先 `cd "$FORTUNE"` 才跑
    `python -m scripts.seo.build_pages`(fortune-ai/scripts/seo/build_pages.py 真實存在),
    舊版永遠對 Delvin-agent/scripts/seo/ 驗證(不存在)→ 連兩天假陽性推播 admin。

    「解析不出來」單獨回傳、**不當成缺失**:它是「我不知道這行呼叫誰」,不是「那個檔不見了」。
    把它併進缺失會製造假告警,併進 OK 則是替自己的盲區作證——兩邊都不行,所以獨立一欄。
    """
    missing: list[str] = []
    unresolvable: list[str] = []
    seen: set[tuple[str, str]] = set()
    for src, text, mode, initial_cwd in shell_sources():
        for call in scan_source(text, src, mode=mode, initial_cwd=initial_cwd):
            base = Path(call.cwd) if call.cwd else REPO
            if call.kind == "module":
                # 只查該 base 下的套件(第一段是既存目錄),外部套件如 -m pip / http.server 略過
                if not (base / call.raw.split(".")[0]).is_dir():
                    continue
                if (src, call.raw) in seen or module_exists(call.raw, base):
                    continue
                seen.add((src, call.raw))
                missing.append(f"{src}: python -m {call.raw} → 模組不存在({base})")
                continue
            if call.state == "unresolvable":
                if (src, call.raw) in seen:
                    continue
                seen.add((src, call.raw))
                unresolvable.append(f"{src}: {call.raw} → {call.reason}")
                continue
            if (src, call.path) in seen or os.path.isfile(call.path):
                continue
            seen.add((src, call.path))
            missing.append(f"{src}: {call.path} → 檔案不存在")
    return missing, unresolvable


def main() -> int:
    missing, unresolvable = scan()
    if unresolvable:
        # 印出來但不影響 exit code:沉默地吞掉盲區,守衛就變成在替自己作證。
        print(f"ℹ️ 解析不出基準目錄 {len(unresolvable)} 項(不算缺失,但也不算檢查過):")
        for u in unresolvable:
            print(f"  - {u}")
    if not missing:
        print("✅ cron 目標存在性:全部解析得出的模組/腳本都在")
        return 0
    print(f"✗ cron 目標缺失 {len(missing)} 項(cron 會每次失敗):")
    for m in missing:
        print(f"  - {m}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
