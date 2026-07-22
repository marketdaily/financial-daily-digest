#!/usr/bin/env python3
"""buy setup 條件化 edge 週檢自動迴圈(2026-07-22,Delvin「自動化都沒有在做」根治)。

07-13 報告結論寫「等 eff_days≥15 重跑再議」,但重跑靠人記得 → 本檔閉環:
每週日跑兩支【預先登記 cut】研究腳本(07-13 原 14 cut + 07-22 v2 新 8 cut)吃最新帳本,
快照落 ~/.marketdaily-fallback/edge_cuts_history/,與上一次快照比對裁決轉變:
  · 任一 cut 首度 PASS(eff_days≥15 + hit real_edge + DSR real_edge)→ admin 推播
  · 任一 cut 首度 hit=negative_edge 且 eff_days≥15 → admin 推播(閘門候選)
  · dip_pullback>=10% 的 eff_days 首度跨 15 → admin 推播(07-13 預告的重驗時點)
無轉變 → 安靜落檔。腳本自身失敗由外層 cron_run_and_alert 接手(守衛掛掉也要可見)。
"""
import glob
import json
import os
import subprocess
import sys
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "bin", "python")
SCRIPTS = {
    "v1": os.path.join(REPO, "research", "2026-07-13_buy_setup_conditional_edge.py"),
    "v2": os.path.join(REPO, "research", "2026-07-22_buy_selection_alpha_v2.py"),
}
HIST = os.path.expanduser("~/.marketdaily-fallback/edge_cuts_history")
NOTIFY = os.path.expanduser("~/.marketdaily-fallback/notify_admin.py")
DIP_CUT = "dip_pullback>=10%"


def run_script(path: str) -> dict:
    p = subprocess.run([PY, path], capture_output=True, text=True, timeout=600, cwd=REPO)
    if p.returncode != 0:
        raise RuntimeError(f"{os.path.basename(path)} exit={p.returncode}: {p.stderr[-400:]}")
    return json.loads(p.stdout)


def verdict_map(snap: dict) -> dict:
    out = {}
    for r in snap.get("results", []):
        if r.get("n", 0) > 0:
            out[r["name"]] = {"PASS": bool(r.get("PASS")),
                              "hit": r.get("hit_verdict"),
                              "effd": r.get("eff_days") or 0}
    return out


def prev_snapshot(tag: str, today: str) -> dict:
    files = sorted(f for f in glob.glob(os.path.join(HIST, f"*_{tag}.json"))
                   if not os.path.basename(f).startswith(today))
    if not files:
        return {}
    return verdict_map(json.load(open(files[-1])))


def main() -> int:
    os.makedirs(HIST, exist_ok=True)
    today = date.today().isoformat()
    alerts = []
    for tag, path in SCRIPTS.items():
        snap = run_script(path)
        with open(os.path.join(HIST, f"{today}_{tag}.json"), "w") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        cur, prev = verdict_map(snap), prev_snapshot(tag, today)
        for name, c in cur.items():
            p = prev.get(name, {})
            if c["PASS"] and not p.get("PASS"):
                alerts.append(f"🎯 edge cut 首度通過三閘:{name}(effd {c['effd']})→ 有資格進閘門提案")
            elif (c["hit"] == "negative_edge" and c["effd"] >= 15
                  and not (p.get("hit") == "negative_edge" and p.get("effd", 0) >= 15)):
                alerts.append(f"⛔ edge cut 首度 certified 負edge(effd≥15):{name} → 降級閘門候選")
            if name == DIP_CUT and c["effd"] >= 15 and p.get("effd", 99) < 15:
                alerts.append(f"👀 {DIP_CUT} eff_days 跨 15({c['effd']}),07-13 預告的重驗時點到,verdict={c['hit']}")
        n_pass = sum(1 for c in cur.values() if c["PASS"])
        print(f"[{tag}] cuts={len(cur)} PASS={n_pass} 快照已落 {today}_{tag}.json")
    if alerts:
        msg = "📐 edge 週檢裁決轉變\n" + "\n".join(alerts)
        subprocess.run([sys.executable, NOTIFY, "edge週檢", msg], timeout=60)
        print(msg)
    else:
        print("無裁決轉變,安靜落檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
