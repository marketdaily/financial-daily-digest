#!/usr/bin/env python3
"""把既有 docs/output/digest_*.html 公版存檔的 signal-reason 長度統計補進趨勢帳本
(一次性,可重跑;仿 postcheck_llm_ledger_backfill.py 同款手法)。

沒有這支就要等 record_reason_median() 每天自然累積,新守衛上線那天之前的日子永遠是
空的——但本機已經留著 90 天的公版 archive,直接讀就有真實歷史,不必等。已存在的
(date,edition) 不重複寫。壞檔/缺卡一律跳過,不讓整支腳本因單一壞檔中止(帳本回填
的賣點是「一次性、可重跑」)。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest_postcheck as dp
import digest_audit

REPO = dp.REPO
path = dp.REASON_MEDIAN_LEDGER
seen = set()
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if isinstance(r, dict) and r.get("date") and r.get("edition"):
                seen.add((r["date"], r["edition"]))
        except Exception:
            continue

rows = []
for html_path in sorted((REPO / "docs" / "output").glob("digest_*.html")):
    m = re.match(r"digest_(\d{4}-\d{2}-\d{2})(_us)?\.html$", html_path.name)
    if not m:
        continue
    date, edition = m.group(1), ("us" if m.group(2) else "tw")
    if (date, edition) in seen:
        continue
    try:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        stats = digest_audit.signal_reason_stats(html)
    except Exception:
        continue
    if stats.get("n", 0) < 1:
        continue
    rows.append({"date": date, "edition": edition, **stats, "backfill": True})

rows.sort(key=lambda r: (r["date"], r["edition"]))
if rows:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"回填 {len(rows)} 筆(既有 {len(seen)} 筆跳過),帳本={path}")
