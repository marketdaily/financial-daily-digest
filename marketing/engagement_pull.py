"""IG 成效回饋迴圈:拉近 14 天已發貼文的實際互動/觸及,寫 ledger + summary。

summary 給週日 Marketing Agents 生成鏈的研究代理讀,讓下一批 hook 偏向「實際有人看」
的型,而不是每週盲投。只讀不寫 Graph API。v1 只做 IG(FB/Threads insights 之後再議)。

用法:python engagement_pull.py
輸出:social_out/engagement_ledger.jsonl(append)、social_out/engagement_summary.json(覆寫)
"""
import json
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from auto_post import GRAPH, LOG_FILE, http, load_env

LEDGER = HERE / "social_out" / "engagement_ledger.jsonl"
SUMMARY = HERE / "social_out" / "engagement_summary.json"
LOOKBACK_DAYS = 14


def post_kind(pid):
    for prefix, kind in (("reel", "reel"), ("newsr", "news_reactive"), ("win", "win_card"),
                         ("tldr", "tldr"), ("adcreative", "adcreative")):
        if pid.startswith(prefix):
            return kind
    return "other"


def main():
    env = load_env()
    qtok = urllib.parse.quote(env["META_ACCESS_TOKEN"])
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    seen, targets = set(), []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ts", "") < cutoff:
            continue
        ig = (rec.get("results") or {}).get("instagram") or {}
        mid = ig.get("detail")
        if ig.get("ok") and mid and mid not in seen:
            seen.add(mid)
            targets.append((rec.get("post"), mid, rec.get("ts")))

    rows = []
    for pid, mid, ts in targets:
        ok, r = http(f"{GRAPH}/{mid}?fields=like_count,comments_count,media_product_type,"
                     f"permalink&access_token={qtok}")
        if not ok or "error" in r:
            continue
        row = {"post": pid, "kind": post_kind(pid), "media_id": mid, "posted_ts": ts,
               "likes": r.get("like_count"), "comments": r.get("comments_count"),
               "media_product_type": r.get("media_product_type"),
               "permalink": r.get("permalink")}
        for metrics in ("reach,saved", "reach"):
            ok2, ins = http(f"{GRAPH}/{mid}/insights?metric={metrics}&access_token={qtok}")
            if ok2 and isinstance(ins.get("data"), list) and ins["data"]:
                for m in ins["data"]:
                    vals = m.get("values") or [{}]
                    row[m.get("name")] = vals[0].get("value")
                break
        rows.append(row)

    pulled_at = datetime.now().isoformat(timespec="seconds")
    LEDGER.parent.mkdir(exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"pulled_at": pulled_at, **row}, ensure_ascii=False) + "\n")

    def avg(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 1) if xs else None

    by_kind = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)
    kinds = {k: {"n": len(v),
                 "avg_reach": avg([r.get("reach") for r in v]),
                 "avg_likes": avg([r.get("likes") for r in v]),
                 "avg_comments": avg([r.get("comments") for r in v])}
             for k, v in sorted(by_kind.items())}
    ranked = sorted((r for r in rows if isinstance(r.get("reach"), (int, float))),
                    key=lambda r: r["reach"], reverse=True)
    slim = lambda r: {k: r.get(k) for k in ("post", "kind", "reach", "likes", "comments")}
    summary = {
        "pulled_at": pulled_at, "lookback_days": LOOKBACK_DAYS, "platform": "instagram",
        "n_posts": len(rows), "by_kind": kinds,
        "top_by_reach": [slim(r) for r in ranked[:5]],
        "bottom_by_reach": [slim(r) for r in ranked[-5:]][::-1] if len(ranked) > 5 else [],
        "note": "IG-only;reach/saved 來自 Graph insights,likes/comments 為公開欄位,缺值="
                "該媒體型別不支援。供 marketing-generate 研究代理當上週實際成效參考,"
                "數字只准引用不准外推。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print(f"[engagement_pull] {len(rows)}/{len(targets)} 篇入帳;summary → {SUMMARY.name}")


if __name__ == "__main__":
    main()
