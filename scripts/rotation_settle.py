#!/usr/bin/env python3
"""換股配對帳本週結算(2026-07-22,換股思路 v1 的自我審計層)。

rotation_pairs.jsonl 每列 = 日報建議「賣 from 換 to」的一組配對。
本檔每週(edge_cuts_weekly.sh 週日 16:00 班次)把滿 5 個交易日的未結算列補上:
  from_ret / to_ret = 建議日收盤 → +5 交易日收盤(與 track-record judge 同錨)
  rel = to_ret - from_ret;win = rel > 0(換股是對的)
結算累積 n≥30 首度跨線時推播 admin(樣本夠了,該裁決這功能去留)。
無外部參數;冪等(已結算列不動);任一腳價格抓不到 → 留待下週重試。
"""
import json
import os
import sys
import bisect
import importlib.util
import subprocess
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(REPO, "scripts", "rotation_pairs.jsonl")
NOTIFY = os.path.expanduser("~/.marketdaily-fallback/notify_admin.py")
ALERT_N = 30

_spec = importlib.util.spec_from_file_location(
    "btr", os.path.join(REPO, "scripts", "build_track_record.py"))
btr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(btr)


def fwd5(closes: dict, d: str):
    """建議日(或其後第一個交易日)收盤 → +5 交易日收盤的報酬%;資料不足回 None。"""
    if not closes:
        return None
    ds = sorted(closes)
    i = bisect.bisect_left(ds, d)
    if i >= len(ds) or i + 5 >= len(ds):
        return None
    return (closes[ds[i + 5]] / closes[ds[i]] - 1) * 100


def settle(rows: list, chart_fn) -> tuple[list, int]:
    today = date.today()
    cache: dict = {}

    def closes(sym):
        if sym not in cache:
            cache[sym] = chart_fn(sym, "", "") or {}
        return cache[sym]

    newly = 0
    for r in rows:
        if r.get("settled") or not r.get("date"):
            continue
        if (today - date.fromisoformat(r["date"])).days < 9:
            continue  # 5 個交易日還沒滿,下週再結
        fr = fwd5(closes(r["from"]), r["date"])
        to = fwd5(closes(r["to"]), r["date"])
        if fr is None or to is None:
            continue
        r["from_ret"] = round(fr, 2)
        r["to_ret"] = round(to, 2)
        r["rel"] = round(to - fr, 2)
        r["win"] = to - fr > 0
        r["settled"] = True
        newly += 1
    return rows, newly


def main() -> int:
    if not os.path.exists(PAIRS):
        print("尚無配對帳本,略過")
        return 0
    rows = [json.loads(l) for l in open(PAIRS, encoding="utf-8") if l.strip()]
    n_before = sum(1 for r in rows if r.get("settled"))
    rows, newly = settle(rows, btr.yahoo_chart)
    tmp = PAIRS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, PAIRS)
    done = [r for r in rows if r.get("settled")]
    wins = sum(1 for r in done if r.get("win"))
    rel_avg = sum(r.get("rel", 0) for r in done) / len(done) if done else 0.0
    print(f"配對總數 {len(rows)},本輪新結 {newly},累計已結 {len(done)}"
          + (f",換股勝率 {100 * wins / len(done):.1f}%、平均相對報酬 {rel_avg:+.2f}%" if done else ""))
    if n_before < ALERT_N <= len(done):
        msg = (f"💱 換股帳本累積 {len(done)} 筆已結算(首度跨 {ALERT_N}):"
               f"換股勝率 {100 * wins / len(done):.1f}%、平均相對報酬 {rel_avg:+.2f}%。"
               "樣本夠了,該裁決換股思路功能去留(day-cluster 檢驗後)。")
        subprocess.run([sys.executable, NOTIFY, "換股帳本", msg], timeout=60)
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
