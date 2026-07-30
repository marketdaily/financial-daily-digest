#!/usr/bin/env python3
"""未收尾事項帳本(2026-07-30 Delvin 追責:「你為什麼沒有直接收掉而是要等我問你才講」)。

問題:我在收工摘要裡把「已完成」講得很完整,卻把「還沒收掉/還沒在生產驗證/我自己造成的風險」
留在心裡,老闆不問就不會知道。責任不能靠我的良心——要有機器保證。

機制:任何 session 做事時把未收乾的事項 `add` 進來;Stop hook(session 結束)自動檢查,
還有 open 項就**主動推播老闆手機**。收掉了就 `close`。零 open 項時完全不吵。

用法:
  open_items.py add "一句話說明" [--why "為什麼還沒收"] [--owner me|delvin] [--risk high|med|low]
  open_items.py close <id> [--note "怎麼收的"]
  open_items.py list [--json]
  open_items.py push        # 有 open 項就推播(Stop hook 呼叫,無項目時靜默 exit 0)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "state" / "open_items.json"
NOTIFY = Path.home() / ".marketdaily-fallback" / "notify_admin.py"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _load() -> list:
    try:
        with LEDGER.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)
    tmp.replace(LEDGER)


def cmd_add(a) -> int:
    items = _load()
    nid = max((i.get("id", 0) for i in items), default=0) + 1
    items.append({"id": nid, "what": a.what, "why": a.why or "", "owner": a.owner,
                  "risk": a.risk, "opened": _now(), "closed": None, "note": ""})
    _save(items)
    print(f"#{nid} 已登記({a.risk} risk / owner={a.owner}):{a.what}")
    return 0


def cmd_close(a) -> int:
    items = _load()
    for i in items:
        if i.get("id") == a.id:
            if i.get("closed"):
                print(f"#{a.id} 早已收掉({i['closed']})")
                return 0
            i["closed"] = _now()
            i["note"] = a.note or ""
            _save(items)
            print(f"#{a.id} 已收:{i['what']}")
            return 0
    print(f"找不到 #{a.id}", file=sys.stderr)
    return 1


def _open_items() -> list:
    return [i for i in _load() if not i.get("closed")]


def cmd_list(a) -> int:
    items = _open_items()
    if a.json:
        print(json.dumps(items, ensure_ascii=False))
        return 0
    if not items:
        print("✅ 沒有未收尾事項")
        return 0
    print(f"⚠️ {len(items)} 項未收尾:")
    for i in items:
        print(f"  #{i['id']} [{i['risk']}/{i['owner']}] {i['what']}")
        if i.get("why"):
            print(f"        原因:{i['why']}")
    return 0


PUSH_STATE = ROOT / "state" / "open_items_push.json"
REMIND_SEC = int(os.environ.get("OPEN_ITEMS_REMIND_SEC", 12 * 3600))


def _should_push(items: list) -> tuple[bool, bool]:
    """回 (要不要推, 是不是純提醒)。

    2026-07-30 Delvin:「why notify me 3 times with the same stuff?」——Stop hook 每次
    session 結束都呼叫,同一份名單被原封不動推了 3 次。規則改成:只有「冒出新項目」才
    立刻推;名單沒變就最多每 REMIND_SEC 提醒一次;純粹關掉項目(名單變短)不推。
    """
    ids = sorted(i.get("id") for i in items)
    now = datetime.now(timezone.utc).timestamp()
    last_ids, last_ts = [], 0.0
    try:
        with PUSH_STATE.open(encoding="utf-8") as fh:
            st = json.load(fh)
        last_ids = st.get("ids", []) or []
        last_ts = float(st.get("ts", 0) or 0)
    except (OSError, ValueError, TypeError):
        pass   # fail-open:狀態讀不到就照推,寧可吵一次也不要漏掉新事項
    fresh = [i for i in ids if i not in last_ids]
    due = (now - last_ts) >= REMIND_SEC
    if not fresh and not due:
        return False, False
    return True, (not fresh)


def _mark_pushed(items: list) -> None:
    PUSH_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PUSH_STATE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump({"ids": sorted(i.get("id") for i in items),
                   "ts": datetime.now(timezone.utc).timestamp(),
                   "at": _now()}, fh, ensure_ascii=False)
    tmp.replace(PUSH_STATE)


def cmd_push(a) -> int:
    """有 open 項就推播老闆。無項目=靜默(hook 每次 session 結束都會呼叫,不能變成噪音)。"""
    items = _open_items()
    if not items:
        return 0
    go, remind_only = _should_push(items)
    if not go and not getattr(a, "force", False):
        print(f"名單未變且未到提醒間隔({REMIND_SEC}s),不推播({len(items)} 項仍 open)")
        return 0
    order = {"high": 0, "med": 1, "low": 2}
    items.sort(key=lambda i: order.get(i.get("risk"), 3))
    head = ("⏰ 提醒:這些還沒收乾(名單沒變,每 %dh 提醒一次)" % (REMIND_SEC // 3600)
            if remind_only else "📋 這次做完但**還沒收乾**的 %d 項(機器主動報,不用你問):" % len(items))
    lines = [head, ""]
    for i in items:
        tag = {"high": "🔴", "med": "🟡", "low": "⚪"}.get(i.get("risk"), "⚪")
        who = "等你" if i.get("owner") == "delvin" else "我"
        lines.append(f"{tag} #{i['id']} {i['what']}（{who}）")
        if i.get("why"):
            lines.append(f"    → {i['why']}")
    lines += ["", "收掉的會自動從這份名單消失;要我先做哪一項直接跟任一 Claude 視窗講編號。"]
    msg = "\n".join(lines)
    if not NOTIFY.exists():
        print(msg)
        _mark_pushed(items)
        return 0
    env = dict(os.environ, MD_REPO=str(ROOT))
    py = ROOT / ".venv" / "bin" / "python"
    subprocess.run([str(py if py.exists() else sys.executable), str(NOTIFY), msg],
                   env=env, capture_output=True, timeout=120)
    _mark_pushed(items)
    print(f"已推播 {len(items)} 項未收尾事項")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("what")
    p.add_argument("--why", default=""); p.add_argument("--owner", default="me", choices=["me", "delvin"])
    p.add_argument("--risk", default="med", choices=["high", "med", "low"]); p.set_defaults(fn=cmd_add)
    p = sub.add_parser("close"); p.add_argument("id", type=int)
    p.add_argument("--note", default=""); p.set_defaults(fn=cmd_close)
    p = sub.add_parser("list"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("push"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_push)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
