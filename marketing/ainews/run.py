"""AI 新聞內容線 CLI。

  scan   只列今天排序後的候選(不呼叫 LLM,零成本)
  draft  產 N 則草稿 → 確定性閘 → 獨立驗證者 → 寫檔(預設不發文)
  post   把已核可的草稿發出去(需 --confirm;預設拒絕)

⚠️ 對外發布一律先給老闆看過(2026-08-17 親令),所以 draft 與 post 是分開的兩個動作。
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.request

from . import sources, rank, draft as D, gates

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "drafts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

VERIFY_PROMPT = """You are an independent fact checker. You did not write this text.

FACTS the writer was given:
{facts}

DRAFT the writer produced:
{draft}

Check, one by one:
1. Does every factual claim in the draft appear in FACTS? List any claim that does not.
2. Does every number, percentage, date and name in the draft appear in FACTS?
3. Does the draft state as certain anything FACTS marks as unconfirmed, reported, or alleged?
4. Does the draft give investment advice, or tell anyone to buy or sell anything?
5. Is the draft understandable to someone who has never used an AI product?

Return ONLY JSON: {{"verdict": "pass" or "fail", "problems": ["..."], "worst": "one sentence"}}
Be strict. If a single claim cannot be traced to FACTS, the verdict is fail.
"""


def article_excerpt(url, limit=2500):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read(400000).decode("utf-8", "ignore")
    except Exception as e:
        return f"(could not fetch article body: {type(e).__name__})"
    html = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html)
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
    text = " ".join(re.sub(r"<[^>]+>", " ", p) for p in paras)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def cmd_scan(args):
    items, health = sources.fetch()
    hs = sources.health_summary(health)
    print(json.dumps(hs, ensure_ascii=False))
    if hs["dead"]:
        print(f"⚠️ 死掉的源:{hs['dead']} —— 訊源缺席可能是渠道死了,不是沒新聞")
    ranked = rank.rank(items)
    for r in ranked[:args.n]:
        print(f"{r['score']:6.1f} [{r['lane']:8s}] {r['confluence']}源 {r['age_h']:5.1f}h "
              f"{r['src_label']:16s} {r['title'][:90]}")
    return ranked


def cmd_draft(args):
    from marketing.news_reactive import call_claude
    items, health = sources.fetch()
    hs = sources.health_summary(health)
    print(json.dumps(hs, ensure_ascii=False))
    ranked = rank.rank(items)
    if not ranked:
        print("今天沒有可用候選。")
        return []

    state = rank.load_state()
    today = datetime.date.today().isoformat()
    out, tried = [], 0
    for cand in ranked:
        if len(out) >= args.n or tried >= args.n * 3:
            break
        tried += 1
        print(f"\n── [{cand['lane']}] {cand['title'][:80]}")
        facts = D.build_facts(cand, article_excerpt(cand["url"]))
        try:
            d = call_claude(D.build_prompt(facts), timeout_s=240)
        except Exception as e:
            print(f"  ✗ 產生失敗:{type(e).__name__}: {e}")
            continue
        d = D.decorate(d, facts)
        ok, why = gates.check(d, facts, D.BRAND)
        if not ok:
            print("  ✗ 確定性閘不過:" + " / ".join(why))
            continue
        print("  ✓ 確定性閘通過 → 獨立驗證者")
        try:
            v = call_claude(VERIFY_PROMPT.format(
                facts=json.dumps(facts, ensure_ascii=False, indent=1),
                draft=json.dumps({k: d[k] for k in ("headline", "caption", "threads_caption")},
                                 ensure_ascii=False, indent=1)), timeout_s=240)
        except Exception as e:
            print(f"  ✗ 驗證者打不通:{type(e).__name__} —— 不放行(fail-closed)")
            continue
        if v.get("verdict") != "pass":
            print(f"  ✗ 驗證者駁回:{v.get('worst')} | {v.get('problems')}")
            continue
        print("  ✓ 驗證者通過")
        out.append({"id": f"ai_{cand['key']}", "date": today, "lane": cand["lane"],
                    "score": cand["score"], "source": cand["src_label"],
                    "source_url": cand["url"], "story_keys": cand.get("story_keys", []),
                    "facts": facts, "draft": d, "status": "pending_owner_review"})

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{today}.json"
    prev = json.loads(path.read_text()) if path.exists() else []
    have = {p["id"] for p in prev}
    prev += [o for o in out if o["id"] not in have]
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=1))
    print(f"\n{len(out)} 則草稿 → {path}")
    return out


def cmd_post(args):
    print("post 尚未接上:對外發布需老闆先看過草稿並核可(2026-08-17 親令)。")
    print("草稿在", OUT)
    return 2


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("-n", type=int, default=20)
    d = sub.add_parser("draft"); d.add_argument("-n", type=int, default=3)
    p = sub.add_parser("post"); p.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    rc = {"scan": cmd_scan, "draft": cmd_draft, "post": cmd_post}[a.cmd](a)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
