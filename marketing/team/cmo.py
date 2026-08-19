"""BLACKEDGE 行銷部 AI CMO —— 戰情看板。

對標 Okara AI CMO 的 Actions Feed,差別在:每一格數字都來自真實檔案或真實戳記,
沒有的東西一律標 UNKNOWN,不用 0 或「正常」頂替。

用法:
    python3 -m marketing.team.cmo feed              # 全隊戰情
    python3 -m marketing.team.cmo feed --brand mingshu
    python3 -m marketing.team.cmo feed --json
    python3 -m marketing.team.cmo scoreboard        # 對 Okara 逐席比分
"""
import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROSTER = Path(__file__).resolve().parent / "roster.json"
OK_DIR = ROOT / "logs" / "ok"

FRESH, STALE, UNKNOWN, NA = "FRESH", "STALE", "UNKNOWN", "N/A"


def load_roster():
    return json.loads(ROSTER.read_text(encoding="utf-8"))


def _stamp_age_h(name):
    p = OK_DIR / f"{name}.ok"
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 3600.0


def _newest_glob(patterns):
    """回傳 (age_h, 檔名);一個都沒命中回 (None, None)。"""
    best, name = None, None
    for pat in patterns:
        for p in ROOT.glob(pat):
            if not p.is_file():
                continue
            m = p.stat().st_mtime
            if best is None or m > best:
                best, name = m, p.name
    if best is None:
        return None, None
    return (time.time() - best) / 3600.0, name


def _jsonl_last_ts(path, id_prefix=None):
    """最後一筆(可選:最後一筆 id 帶指定前綴的)紀錄有多舊。
    id_prefix 存在時只認該前綴的紀錄 —— 不准拿別的席位的成果當自己的活性證據。"""
    p = ROOT / path
    if not p.exists():
        return None, None
    rec = None
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if id_prefix and not str(r.get("post", "")).startswith(id_prefix):
                    continue
                rec = r
    except Exception:
        return None, None
    if rec is None:
        return None, None
    ts = rec.get("ts") or rec.get("timestamp") or rec.get("date")
    if not ts:
        return None, None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            t = time.mktime(time.strptime(str(ts)[:26], fmt))
            return (time.time() - t) / 3600.0, str(rec.get("post") or ts)[:40]
        except ValueError:
            continue
    return None, None


def seat_evidence(seat):
    """產出物證據 —— 比戳記可信,因為它是「工作真的做完了」的直接痕跡。
    回傳 (age_h, 說明) 或 (None, None)。"""
    ev = seat.get("evidence")
    if not ev:
        return None, None
    kind = ev.get("kind")
    if kind == "newest_glob":
        age, name = _newest_glob(ev.get("patterns", []))
        return (age, f"產出 {name} {age:.1f}h 前") if age is not None else (None, None)
    if kind == "jsonl_last_ts":
        age, label = _jsonl_last_ts(ev.get("path", ""), ev.get("id_prefix"))
        return (age, f"最後一筆 {label} {age:.1f}h 前") if age is not None else (None, None)
    return None, None


def seat_liveness(seat):
    """回傳 (state, age_h, detail)。
    優先序:產出物證據 > logs/ok 戳記 > UNKNOWN。兩者皆無 → UNKNOWN,絕不當成健康。"""
    if seat.get("status") == "gap":
        return NA, None, "席位未建置"
    max_age = seat.get("max_age_h")
    ev_age, ev_detail = seat_evidence(seat)
    if ev_age is not None:
        if max_age is None:
            return UNKNOWN, ev_age, f"{ev_detail};未定義新鮮度門檻"
        state = FRESH if ev_age <= max_age else STALE
        return state, ev_age, f"{ev_detail} / 門檻 {max_age}h"
    stamps = seat.get("stamps") or []
    if not stamps:
        return UNKNOWN, None, "無產出物證據也無活性戳記,活著與否不可知"
    ages = {s: _stamp_age_h(s) for s in stamps}
    missing = [s for s, a in ages.items() if a is None]
    present = {s: a for s, a in ages.items() if a is not None}
    if not present:
        return UNKNOWN, None, f"戳記從未出現: {','.join(missing)}"
    worst_name, worst = max(present.items(), key=lambda kv: kv[1])
    max_age = seat.get("max_age_h")
    if max_age is None:
        return UNKNOWN, worst, "未定義新鮮度門檻"
    state = FRESH if worst <= max_age else STALE
    detail = f"{worst_name} {worst:.1f}h / 門檻 {max_age}h"
    if missing:
        state = UNKNOWN if state == FRESH else state
        detail += f";缺戳記 {','.join(missing)}"
    return state, worst, detail


# ---- backlog collectors:每一支都只讀真實檔案,讀不到回 None ----

def _json(path):
    p = ROOT / path
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def c_social_unposted():
    d = _json("marketing/social_posts.json")
    if d is None:
        return None, "social_posts.json 讀不到"
    items = d.get("posts") if isinstance(d, dict) else d
    if not isinstance(items, list):
        return None, "格式非預期"
    n = sum(1 for x in items if not x.get("posted") and not x.get("retired"))
    return n, "則待發貼文"


def c_drafts_pending():
    d = _json("marketing/ad_creative_drafts.json")
    if d is None:
        return None, "ad_creative_drafts.json 讀不到"
    items = d.get("drafts") if isinstance(d, dict) else d
    if not isinstance(items, list):
        return None, "格式非預期"
    n = sum(1 for x in items if x.get("status") == "pending_review")
    return n, "則草稿待驗證官裁決"


def c_blog_articles():
    p = ROOT / "docs" / "blog"
    if not p.exists():
        return None, "docs/blog 不存在"
    return len(list(p.glob("*.html"))), "篇文章線上"


def c_reddit_codes():
    d = _json("intel/reddit_buzz_latest.json")
    if d is None:
        return None, "reddit_buzz_latest.json 讀不到"
    by = d.get("by_code")
    if not isinstance(by, dict):
        return None, "格式非預期"
    return len(by), f"檔有社群聲量(掃描日 {d.get('date', '?')})"


def c_geo_gaps():
    d = _json("marketing/team/geo_state.json")
    if d is None:
        return None, "尚未跑過 geo_agent"
    gaps = d.get("gaps")
    if not isinstance(gaps, list):
        return None, "格式非預期"
    return len(gaps), f"個 AI 引用缺口(掃描日 {d.get('scanned_at', '?')[:10]})"


COLLECTORS = {
    "social_unposted": c_social_unposted,
    "drafts_pending": c_drafts_pending,
    "blog_articles": c_blog_articles,
    "reddit_codes": c_reddit_codes,
    "geo_gaps": c_geo_gaps,
}


def build_feed(brand=None):
    r = load_roster()
    rows = []
    for seat in r["seats"]:
        if brand and brand not in (seat.get("brands") or []):
            continue
        state, age, detail = seat_liveness(seat)
        count, unit, note = None, None, None
        key = seat.get("backlog")
        if key:
            fn = COLLECTORS.get(key)
            if fn is None:
                note = f"未實作的 collector: {key}"
            else:
                count, unit = fn()
                if count is None:
                    note = unit
                    unit = None
        rows.append({
            "id": seat["id"], "name": seat["name"], "status": seat["status"],
            "okara": seat.get("okara_counterpart"), "liveness": state,
            "age_h": round(age, 1) if age is not None else None,
            "liveness_detail": detail, "count": count, "unit": unit,
            "note": note or seat.get("gap_note"), "edge": seat.get("edge"),
        })
    return r, rows


ICON = {FRESH: "🟢", STALE: "🔴", UNKNOWN: "⚪", NA: "⬛"}


def print_feed(r, rows, brand=None):
    title = f"{r['team']} · {r['team_zh']}"
    if brand:
        title += f"  —  {r['brands'].get(brand, {}).get('name', brand)}"
    print(f"\n\033[1m{title}\033[0m")
    print(f"對標 {r['benchmark']['name']} (${r['benchmark']['price_usd_month']}/mo, "
          f"{r['benchmark']['agents_claimed']} agents)\n")
    print("  ACTIONS FEED")
    print("  " + "─" * 74)
    for x in rows:
        icon = ICON.get(x["liveness"], "?")
        head = f"  {icon} {x['name']:<12}"
        if x["count"] is not None:
            body = f"{x['count']} {x['unit']}"
        elif x["status"] == "gap":
            body = "\033[31m席位未建置\033[0m"
        else:
            body = x["liveness_detail"] or ""
        print(f"{head} {body}")
        if x["count"] is not None and x["liveness_detail"]:
            print(f"     {'':<12} \033[2m{x['liveness_detail']}\033[0m")
        if x["note"]:
            print(f"     {'':<12} \033[33m⚠ {x['note']}\033[0m")
    print("  " + "─" * 74)
    tot = len(rows)
    live = sum(1 for x in rows if x["status"] == "live")
    part = sum(1 for x in rows if x["status"] == "partial")
    gap = sum(1 for x in rows if x["status"] == "gap")
    unk = sum(1 for x in rows if x["liveness"] == UNKNOWN)
    stale = sum(1 for x in rows if x["liveness"] == STALE)
    print(f"  席位 {tot}  ·  🟩 完整 {live}  🟨 半套 {part}  🟥 未建置 {gap}"
          f"   |   活性: 🔴逾期 {stale}  ⚪不可知 {unk}")
    print()


def print_scoreboard(r):
    seats = r["seats"]
    print(f"\n\033[1m{r['team']} vs {r['benchmark']['name']}\033[0m  逐席比分\n")
    print(f"  {'席位':<14}{'Okara':<24}{'我方':<10}判定")
    print("  " + "─" * 74)
    win = tie = lose = 0
    for s in seats:
        ok = s.get("okara_counterpart") or "—(他們沒有)"
        mine = {"live": "完整", "partial": "半套", "gap": "無"}[s["status"]]
        if s["status"] == "gap":
            verdict, lose = "\033[31m落後\033[0m", lose + 1
        elif s.get("okara_counterpart") is None:
            verdict, win = "\033[32m獨有\033[0m", win + 1
        elif s["status"] == "partial":
            verdict, lose = "\033[31m落後\033[0m", lose + 1
        elif s.get("edge"):
            verdict, win = "\033[32m勝\033[0m", win + 1
        else:
            verdict, tie = "平", tie + 1
        print(f"  {s['name']:<14}{ok:<24}{mine:<10}{verdict}")
    print("  " + "─" * 74)
    print(f"  勝 {win} · 平 {tie} · 落後 {lose}")
    print("\n  Okara 已知結構弱點(我方可長期壓制的地方):")
    for w in r["benchmark"]["known_weaknesses"]:
        print(f"    · {w}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["feed", "scoreboard"], nargs="?", default="feed")
    ap.add_argument("--brand")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r, rows = build_feed(a.brand)
    if a.json:
        print(json.dumps({"team": r["team"], "brand": a.brand, "seats": rows},
                         ensure_ascii=False, indent=1))
        return
    if a.cmd == "scoreboard":
        print_scoreboard(r)
    else:
        print_feed(r, rows, a.brand)


if __name__ == "__main__":
    main()
