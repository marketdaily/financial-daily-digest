#!/usr/bin/env python3
"""免費算力雷達:一次逾時不可以被寫成「掉線」(2026-09-16)。

守的災難:probe 只有兩態時,一次 Read timeout 就讓某席從 True 翻成 False,
於是推一則「🔴 免費算力掉線」,下一輪又推「🟢 恢復」——09-11 與 09-14 的兩則
openrouter 告警都是這樣來的,那個席次其實一直活著。
假的掉線通知比沒有通知更糟:它教人忽略這個頻道,真的死那次就沒人信了。

判準對著災難寫:量的是「會不會發出掉線通知」,不是「probe 有沒有回 False」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import free_capacity_radar as R  # noqa: E402

FAILS = []


def ck(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


def run(probe_results, prev_health, quiet=True):
    """只跑 main 的健康迴圈那一段,不碰網路/不寫 state/不推播。"""
    seq = list(probe_results)
    calls = {"push": [], "saved": None}
    orig = (R.probe_alive, R.load_state, R.save_state, R.push_admin,
            R.list_models, R.queue_backlog, R.QUIET, R.time.sleep)
    R.probe_alive = lambda v, m: seq.pop(0)
    R.load_state = lambda: {"health": prev_health, "models": {}}
    R.save_state = lambda st: calls.__setitem__("saved", st)
    R.push_admin = lambda msg: calls["push"].append(msg)
    R.list_models = lambda v: None
    R.queue_backlog = lambda lines: None
    R.QUIET = quiet
    R.time.sleep = lambda s: None
    try:
        R.main()
    finally:
        (R.probe_alive, R.load_state, R.save_state, R.push_admin,
         R.list_models, R.queue_backlog, R.QUIET, R.time.sleep) = orig
    return calls


N = len(R.HEALTH)
ALIVE = (True, "200")
UNKNOWN = (None, "ReadTimeout: read timed out(重試後仍如此)")
DEAD = (False, "401 key 失效")
PREV_ALL_ALIVE = {lbl: {"alive": True, "note": "200"} for lbl, _, _ in R.HEALTH}


def main():
    # ① 全活 → 不推任何東西
    c = run([ALIVE] * N, PREV_ALL_ALIVE)
    ck("全部活著時完全安靜", not c["push"], c["push"])

    # ② ⭐ 一輪問不到 → 絕不可以發「掉線」
    c = run([UNKNOWN] + [ALIVE] * (N - 1), PREV_ALL_ALIVE)
    ck("⭐ 單次逾時不發掉線通知", not any("掉線" in m for m in c["push"]), c["push"])
    lbl = R.HEALTH[0][0]
    ck("單次逾時沿用上一輪判定(仍算活著)",
       c["saved"]["health"][lbl]["alive"] is True, c["saved"]["health"][lbl])
    ck("有記下這輪沒問到(streak=1)", c["saved"]["health"][lbl]["unknown_streak"] == 1)

    # ③ 連續第 2 輪仍問不到 → 這才算掉線(一直問不到本身就是故障)
    prev = {k: dict(v) for k, v in PREV_ALL_ALIVE.items()}
    prev[lbl] = {"alive": True, "note": "問不到", "unknown_streak": 1}
    c = run([UNKNOWN] + [ALIVE] * (N - 1), prev)
    ck("連續第 2 輪問不到才發掉線", any("掉線" in m for m in c["push"]), c["push"])
    ck("掉線訊息講出是『問不到』不是假裝知道原因",
       any("問不到" in m for m in c["push"]), c["push"])

    # ④ 對方明確回答(401)→ 第一輪就該算死,不必等連續
    c = run([DEAD] + [ALIVE] * (N - 1), PREV_ALL_ALIVE)
    ck("明確被拒(401)第一輪就算掉線", any("掉線" in m for m in c["push"]), c["push"])

    # ⑤ 死→活 要發恢復
    prev = {k: dict(v) for k, v in PREV_ALL_ALIVE.items()}
    prev[lbl] = {"alive": False, "note": "401"}
    c = run([ALIVE] * N, prev)
    ck("復活要發🟢恢復", any("恢復" in m for m in c["push"]), c["push"])

    # ⑥ 突變對照:把門檻改成 1(=退回舊行為)⇒ ② 必須紅
    keep = R.UNKNOWN_STREAK_DEAD
    R.UNKNOWN_STREAK_DEAD = 1
    c = run([UNKNOWN] + [ALIVE] * (N - 1), PREV_ALL_ALIVE)
    mutated_alerts = any("掉線" in m for m in c["push"])
    R.UNKNOWN_STREAK_DEAD = keep
    ck("⭐ 突變(門檻退回 1)會讓單次逾時又發掉線 ⇒ 本測試真的在量這件事", mutated_alerts)

    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 條沒過:{FAILS}")
        return 1
    print("✅ 免費算力雷達三態全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
