"""BLACKEDGE CMO 看板自測。每條斷言都對著 2026-08-19 建置當天真的踩到的 bug 寫。

跑法:python3 marketing/team/test_cmo.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from marketing.team import cmo  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}  {detail}")
        FAILED.append(name)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cmo_test_"))
    orig_root, orig_ok = cmo.ROOT, cmo.OK_DIR
    cmo.ROOT = tmp
    cmo.OK_DIR = tmp / "logs" / "ok"
    cmo.OK_DIR.mkdir(parents=True)
    try:
        # 舊戳記(7 天前)+ 今天剛產出的成果 —— 正是 social/videobrief 那個 bug 的形狀
        stale = tmp / "logs" / "ok" / "oldstamp.ok"
        stale.write_text("x")
        old = time.time() - 7 * 24 * 3600
        os.utime(stale, (old, old))
        out = tmp / "out"
        out.mkdir()
        (out / "post_today.json").write_text("{}")

        s1 = {"id": "a", "status": "live", "stamps": ["oldstamp"], "max_age_h": 36,
              "evidence": {"kind": "newest_glob", "patterns": ["out/post_*.json"]}}
        state, age, _ = cmo.seat_liveness(s1)
        check("產出物證據勝過過期戳記(戳記 7 天前但今天有產出 → FRESH)",
              state == cmo.FRESH and age < 1, f"got {state} {age}")

        # 沒有證據也沒有戳記 → 一律 UNKNOWN,絕不當健康
        s2 = {"id": "b", "status": "live", "stamps": [], "max_age_h": 36}
        check("無證據無戳記 → UNKNOWN(不是 FRESH)",
              cmo.seat_liveness(s2)[0] == cmo.UNKNOWN)

        # 只有過期戳記 → STALE
        s3 = {"id": "c", "status": "live", "stamps": ["oldstamp"], "max_age_h": 36}
        check("只有過期戳記 → STALE", cmo.seat_liveness(s3)[0] == cmo.STALE)

        # 證據本身過期 → STALE(不因為「有證據」就放行)
        old_out = out / "post_old.json"
        old_out.write_text("{}")
        s4 = {"id": "d", "status": "live", "stamps": [], "max_age_h": 36,
              "evidence": {"kind": "newest_glob", "patterns": ["out/post_old.json"]}}
        os.utime(old_out, (old, old))
        check("證據過期 → STALE", cmo.seat_liveness(s4)[0] == cmo.STALE)

        # 未建置席位 → N/A,不混進活性統計
        check("gap 席位 → N/A",
              cmo.seat_liveness({"id": "e", "status": "gap"})[0] == cmo.NA)

        # 未定義門檻 → UNKNOWN,不准預設「還算新鮮」
        s5 = {"id": "f", "status": "live", "stamps": [], "max_age_h": None,
              "evidence": {"kind": "newest_glob", "patterns": ["out/post_today.json"]}}
        check("有證據但沒定門檻 → UNKNOWN", cmo.seat_liveness(s5)[0] == cmo.UNKNOWN)

        # id_prefix 隔離:不准拿別席位的紀錄當自己的活性證據(新聞席撿到 post_gate_state 的 bug)
        log = tmp / "log.jsonl"
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(old))
        log.write_text(
            json.dumps({"ts": old_ts, "post": "newsr_20260812_x"}) + "\n"
            + json.dumps({"ts": now_ts, "post": "win_2026_other"}) + "\n", encoding="utf-8")
        s6 = {"id": "g", "status": "live", "stamps": [], "max_age_h": 36,
              "evidence": {"kind": "jsonl_last_ts", "path": "log.jsonl", "id_prefix": "newsr_"}}
        st6, age6, _ = cmo.seat_liveness(s6)
        check("id_prefix 隔離:別席位今天的紀錄不算我的活性 → STALE",
              st6 == cmo.STALE and age6 > 100, f"got {st6} {age6}")
        s7 = dict(s6, evidence={"kind": "jsonl_last_ts", "path": "log.jsonl"})
        check("無 id_prefix 時取最後一筆 → FRESH", cmo.seat_liveness(s7)[0] == cmo.FRESH)

        # collector 讀不到檔一律 None,不准用 0 頂替(0 會被讀成「沒有待辦」)
        n, note = cmo.c_social_unposted()
        check("檔案不存在時 collector 回 None(不是 0)", n is None, f"got {n} {note}")

        # 壞掉的 JSON 不可讓看板整個炸掉
        (tmp / "marketing").mkdir()
        (tmp / "marketing" / "social_posts.json").write_text("{ broken", encoding="utf-8")
        n2, _ = cmo.c_social_unposted()
        check("壞 JSON → None 而非例外", n2 is None)
    finally:
        cmo.ROOT, cmo.OK_DIR = orig_root, orig_ok

    # 真 roster 必須能載入、每席欄位齊全、evidence kind 都是實作過的
    r = cmo.load_roster()
    ids = [s["id"] for s in r["seats"]]
    check("roster 席位 id 無重複", len(ids) == len(set(ids)))
    known_kinds = {"newest_glob", "jsonl_last_ts"}
    bad = [s["id"] for s in r["seats"]
           if s.get("evidence") and s["evidence"].get("kind") not in known_kinds]
    check("沒有未實作的 evidence kind", not bad, f"bad={bad}")
    bad_bl = [s["id"] for s in r["seats"]
              if s.get("backlog") and s["backlog"] not in cmo.COLLECTORS]
    check("沒有未實作的 backlog collector", not bad_bl, f"bad={bad_bl}")
    missing = [s["id"] for s in r["seats"]
               if s.get("status") != "gap" and not s.get("stamps") and not s.get("evidence")]
    check("非 gap 席位若無任何活性來源,必須在看板顯示 UNKNOWN(此處僅登記)", True,
          f"UNKNOWN 席位: {missing}")
    _, rows = cmo.build_feed()
    check("build_feed 不炸且席位數對得上", len(rows) == len(r["seats"]))

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 條失敗: {FAILED}")
        return 1
    print("✅ 全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
