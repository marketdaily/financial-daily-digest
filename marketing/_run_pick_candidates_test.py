#!/usr/bin/env python3
"""合成候選測試 pick_candidates() 去重/多樣性邏輯,不重寫任何邏輯,直接呼叫既有函式。"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from promote_win_cards import pick_candidates  # noqa: E402

candidates = [
    {"date": "2026-05-21", "ticker": "A", "pct_move_5d": 5.0, "verdict_class": "buy",
     "name": "A Corp", "verdict_label": "買進", "market": "us"},
    {"date": "2026-05-21", "ticker": "B", "pct_move_5d": 20.0, "verdict_class": "buy",
     "name": "B Corp", "verdict_label": "買進", "market": "us"},
    {"date": "2026-05-21", "ticker": "C", "pct_move_5d": 1.0, "verdict_class": "buy",
     "name": "C Corp", "verdict_label": "買進", "market": "us"},
    {"date": "2026-06-01", "ticker": "MSFT", "pct_move_5d": -3.0, "verdict_class": "wait",
     "name": "Microsoft", "verdict_label": "觀望", "market": "us"},
    {"date": "2026-06-02", "ticker": "MSFT", "pct_move_5d": -4.0, "verdict_class": "wait",
     "name": "Microsoft", "verdict_label": "觀望", "market": "us"},
    {"date": "2026-06-03", "ticker": "MSFT", "pct_move_5d": -5.0, "verdict_class": "wait",
     "name": "Microsoft", "verdict_label": "觀望", "market": "us"},
]

picked = pick_candidates(candidates, set(), limit=10)

out_path = Path.cwd() / "result.txt"
out_path.write_text("\n".join(c["ticker"] for c in picked) + "\n", encoding="utf-8")
print(f"picked {len(picked)} candidates -> {out_path}")
for c in picked:
    print(f"  · {c['date']} {c['ticker']} pct={c['pct_move_5d']} verdict_class={c['verdict_class']}")
