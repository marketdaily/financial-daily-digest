#!/usr/bin/env python3
"""把既有 logs/fallback_*.log 的「本班掉慢路徑次數」補進 postcheck LLM 帳本(一次性,可重跑)。

digest_postcheck 的常態化分流需要歷史才判得出「這是常態還是新事件」;沒有歷史的第一天會把
早就常態化的訊號當新事件推播。這支從真實 log 逐班回填(不是造數字),已存在的 (date,edition)
不重複寫。escalated 依當天 postcheck log 是否真的印出 [LLM鏈] 判定——那些才是真的推播過的。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest_postcheck as dp

REPO = dp.REPO
path = dp._ledger_path()
seen = set()
if path.exists():
    # 壞行/缺鍵直接跳過:這支的賣點是「一次性、可重跑」,遇到一列壞資料就 traceback
    # 退出的話,帳本一旦髒掉就再也回填不了(驗證者 F9b)。
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
for log in sorted((REPO / "logs").glob("fallback_*.log")):
    date = re.search(r"fallback_(\d{4}-\d{2}-\d{2})\.log", log.name).group(1)
    txt = log.read_text(encoding="utf-8", errors="replace")
    for ed in ("tw", "us"):
        if (date, ed) in seen or f"market={ed}" not in txt:
            continue
        slow, local_n = dp.llm_shift_counts(txt, ed)
        pc = REPO / "logs" / f"postcheck_{date}_{ed}.log"
        pushed = pc.exists() and "[LLM鏈]" in pc.read_text(encoding="utf-8", errors="replace")
        rows.append({"date": date, "edition": ed, "slow": slow, "local": local_n,
                     "escalated": bool(pushed), "chronic": False, "backfill": True})

rows.sort(key=lambda r: (r["date"], r["edition"]))
if rows:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"回填 {len(rows)} 筆 → {path}")
for r in rows[-8:]:
    print("  ", r["date"], r["edition"], "slow=", r["slow"], "pushed=" if r["escalated"] else "", sep=" ")
