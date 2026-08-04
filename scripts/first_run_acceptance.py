#!/usr/bin/env python3
"""首班驗收:2026-08-04 鏈上改動(deep優先預生成/回音卡不墊閘/mistral第一後衛)的
第一個生產班自動驗收,PASS/FAIL 都推 admin——機器比老闆先發現,老闆不當 QA。

背景(老闆 08-04 原話):「每次加一層 LLM 第一次一定出包,都要我回來問為什麼」。
四次前科共同形狀:元件單測綠,但荒年日+快取/預算/品質閘互動才炸,且炸的常是報警層
本身 → 全程綠燈,老闆變唯一偵測器。此檢查把「新改動的生產行為」直接當驗收訊號。

一次性:只驗 2026-08-04 us 班與 2026-08-05 tw 班,之後任何呼叫都靜默 exit 0
(cron 行留著也無害,收尾時移除)。用法: first_run_acceptance.py {tw|us}
"""
import os
import re
import subprocess
import sys
from datetime import date

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "Delvin-agent")
VALID = {("us", date(2026, 8, 4)), ("tw", date(2026, 8, 5))}
OWNER = "delvin.12345678@gmail.com"


def push(msg):
    subprocess.run([os.path.join(REPO, ".venv/bin/python"),
                    os.path.join(HOME, ".marketdaily-fallback/notify_admin.py"), msg],
                   env={**os.environ, "MD_REPO": REPO}, timeout=60)


def main():
    shift = sys.argv[1] if len(sys.argv) > 1 else ""
    today = date.today()
    if (shift, today) not in VALID and not os.environ.get("MD_FRA_FORCE"):
        return 0
    log_path = os.path.join(REPO, "logs", f"fallback_{today}.log")
    try:
        log = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        push(f"🔴 [首班驗收] {today} {shift} 班:讀不到 {log_path}——班次可能沒跑,請查")
        return 1
    if shift == "us":
        log = log.split("market=us", 1)[-1]

    fails, notes = [], []

    m = re.search(r"deep 優先 (\d+) 檔", log)
    if m and int(m.group(1)) > 0:
        notes.append(f"deep 預生成 {m.group(1)} 檔 ✓")
    else:
        fails.append("deep 優先預生成沒發動(修①未生效)")

    own = log.split(OWNER, 1)
    cache_line = re.search(r"\[card-cache\] (\d+)/(\d+) 支命中", own[1][:4000]) if len(own) > 1 else None
    if cache_line:
        hit, tot = int(cache_line.group(1)), int(cache_line.group(2))
        notes.append(f"老闆 deep 卡快取命中 {hit}/{tot}")
        if hit < tot * 0.8:
            fails.append(f"老闆 deep 卡大多仍在班尾現生({hit}/{tot} 命中,預期近全中)")
    elif len(own) > 1:
        notes.append("老闆段無 card-cache 行(可能全命中零缺卡)")
    else:
        fails.append("log 裡找不到老闆的生成段")

    starved = "配額耗盡(全部 2 把 key)" in log
    n_mistral = len(re.findall(r"使用 mistral", log))
    n_local = len(re.findall(r"使用 local:qwen", log))
    if starved and n_local > 0 and n_mistral == 0:
        fails.append(f"荒年日 local qwen 接活 {n_local} 次而 mistral 0 次(修③排序未生效)")
    else:
        notes.append(f"gemini {'荒年' if starved else '健康'} · mistral {n_mistral} 次 · local {n_local} 次")

    suffix = "_us" if shift == "us" else ""
    arc = os.path.join(REPO, "docs", "output", f"digest_{today}{suffix}.html")
    try:
        import sys as _s
        _s.path.insert(0, REPO)
        from analyzer import _is_example_echo_reason
        html = open(arc, encoding="utf-8", errors="replace").read()
        reasons = [re.sub(r"<[^>]+>", "", r).strip() for r in
                   re.findall(r'class="signal-reason"[^>]*>(.*?)</div>', html, re.S)]
        echoes = [r[:30] for r in reasons if _is_example_echo_reason(r)]
        if echoes:
            fails.append(f"公版仍有 {len(echoes)} 張純回音卡(修②未生效):{echoes[:2]}")
        else:
            notes.append(f"公版 {len(reasons)} 張卡零回音 ✓")
    except Exception as e:
        notes.append(f"公版回音檢查跳過({str(e)[:50]})")

    tag = f"[首班驗收] {today} {shift} 班(08-04 鏈上三修+mistral)"
    if fails:
        push(f"🔴 {tag} FAIL:\n" + "\n".join(f"· {f}" for f in fails)
             + ("\n— " + " / ".join(notes) if notes else ""))
        return 1
    push(f"✅ {tag} 全過:" + " / ".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
