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

from . import sources, rank, draft as D, gates, formats

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "drafts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# ⚠️ 驗證者必須分版型。只寫一份會出現兩種結構性死局:
#  ①清單型是「作者原創內容」,沒有來源可回溯 ⇒ 用「每句都要回溯 FACTS」去驗,
#    這個版型永遠不可能出稿(閘門不是太嚴,是問錯問題)。
#  ②寫稿 prompt 要求「術語給四個字的解釋」,驗證者卻把解釋判成「FACTS 以外的加料」⇒
#    兩個 prompt 在互打,寫稿方照做就一定被駁。所以下面明寫允許簡短定義,並改驗它正不正確。
VERIFY_SOURCED = """You are an independent fact checker. You did not write this text.

FACTS the writer was given:
{facts}

DRAFT the writer produced:
{draft}

Check, one by one:
1. Does every factual claim about the world appear in FACTS? List any claim that does not.
2. Does every number, percentage, date and name appear in FACTS?
3. Does the draft state as certain anything FACTS marks as reported, alleged or unconfirmed?
4. Does the draft widen a claim's scope beyond what FACTS says, or change its tense?
5. Does the draft give investment advice, or tell anyone to buy or sell anything?
6. Is the draft understandable to someone who has never used an AI product?

ALLOWED, do not report these as problems:
- A short plain definition of a widely known company, product or technical term (for example
  "Hugging Face, a public model hub"). The writer is required to add these. Judge them only on
  whether the definition is ACCURATE; flag it only if it is wrong or misleading.
- Ordinary connective writing that carries no new claim.

Return ONLY JSON: {{"verdict": "pass" or "fail", "problems": ["..."], "worst": "one sentence"}}
A claim about the world that cannot be traced to FACTS is a fail. An accurate gloss is not.
"""

VERIFY_AUTHORED = """You are an independent editor checking a how-to list post before publication.
You did not write it. This post is the writer's own advice, so there is no source document to
trace it to. Do not ask for one. Judge it on whether it is true, safe and usable.

TOPIC the writer was given:
{facts}

DRAFT the writer produced:
{draft}

Check, one by one:
1. Does it claim any product, model or service does something it may not actually do?
2. Does it state any statistic, percentage, price, benchmark or research finding? There is no
   source here, so any of these is a fail.
3. Does it state a contested opinion as established fact?
4. Would each item actually work if a reader pasted it into a chatbot today? Flag any item that
   is vague, circular, or is advice rather than something usable.
5. Does it give financial, legal or medical advice?
6. Would a reader who has never used a chatbot know what to do with it?

ALLOWED, do not report these as problems:
- The writer's own count of the items, and numbers used as instructions ("in 3 bullets",
  "under 80 words"). These are directions to the reader, not claims about the world.
- The brand handle, the follow line and the hashtag block. The program adds those, not the writer.
- General craft advice about how to phrase a request.

Return ONLY JSON: {{"verdict": "pass" or "fail", "problems": ["..."], "worst": "one sentence"}}
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
        d = _gate_and_verify(d, facts, call_claude, "explainer")
        if not d:
            continue
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


def _gate_and_verify(d, facts, call_claude, label):
    """兩道關卡共用:確定性閘 → 全新 context 獨立驗證者。打不通一律不放行。"""
    d = D.decorate(d, facts)
    ok, why = gates.check(d, facts, D.BRAND)
    if not ok:
        print(f"  ✗ {label} 確定性閘不過:" + " / ".join(why))
        return None
    print(f"  ✓ {label} 確定性閘通過 → 獨立驗證者")
    payload = {k: d[k] for k in ("headline", "caption", "threads_caption") if k in d}
    for extra in ("cards", "items"):
        if extra in d:
            payload[extra] = d[extra]
    try:
        tmpl = VERIFY_SOURCED if facts.get("source_url") else VERIFY_AUTHORED
        v = call_claude(tmpl.format(
            facts=json.dumps(facts, ensure_ascii=False, indent=1),
            draft=json.dumps(payload, ensure_ascii=False, indent=1)), timeout_s=240)
    except Exception as e:
        print(f"  ✗ 驗證者打不通:{type(e).__name__} —— 不放行(fail-closed)")
        return None
    if v.get("verdict") != "pass":
        print(f"  ✗ 驗證者駁回:{v.get('worst')} | {v.get('problems')}")
        return None
    print("  ✓ 驗證者通過")
    return d


def _save(records):
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = OUT / f"{today}.json"
    prev = json.loads(path.read_text()) if path.exists() else []
    have = {p["id"] for p in prev}
    prev += [r for r in records if r["id"] not in have]
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=1))
    print(f"\n{len(records)} 則 → {path}")
    return path


def cmd_roundup(args):
    """24 小時彙整輪播卡。來源層已經聚類好,所以這個版型幾乎零額外成本。"""
    from marketing.news_reactive import call_claude
    items, health = sources.fetch()
    print(json.dumps(sources.health_summary(health), ensure_ascii=False))
    ranked = rank.rank(items)[:args.n]
    if len(ranked) < 3:
        print(f"只有 {len(ranked)} 則候選,不足以做彙整。")
        return []
    print(f"\n── 24 小時彙整({len(ranked)} 則)")
    for r in ranked:
        print(f"   · [{r['lane']}] {r['title'][:70]}")
    facts = formats.roundup_facts(ranked)
    try:
        d = call_claude(formats.roundup_prompt(ranked, len(ranked)), timeout_s=300)
    except Exception as e:
        print(f"  ✗ 產生失敗:{type(e).__name__}: {e}")
        return []
    d = _gate_and_verify(d, facts, call_claude, "roundup")
    if not d:
        return []
    today = datetime.date.today().isoformat()
    rec = [{"id": f"roundup_{today}", "date": today, "format": "roundup", "lane": "mixed",
            "source": facts["source_name"], "source_url": facts["source_url"],
            "facts": facts, "draft": d, "status": "pending_owner_review"}]
    _save(rec)
    return rec


def cmd_list(args):
    """存檔誘餌清單。完全不依賴新聞 —— 沒新聞的日子帳號照樣有東西發。"""
    from marketing.news_reactive import call_claude
    state = rank.load_state()
    topic = args.topic or formats.pick_topic(state)
    print(f"── 清單型:{topic}")
    facts = formats.listicle_facts(topic)
    try:
        d = call_claude(formats.listicle_prompt(topic, args.items), timeout_s=300)
    except Exception as e:
        print(f"  ✗ 產生失敗:{type(e).__name__}: {e}")
        return []
    d = _gate_and_verify(d, facts, call_claude, "listicle")
    if not d:
        return []
    today = datetime.date.today().isoformat()
    rec = [{"id": f"list_{abs(hash(topic)) % 10**8}", "date": today, "format": "listicle",
            "lane": "product", "topic": topic, "source": None, "source_url": None,
            "facts": facts, "draft": d, "status": "pending_owner_review"}]
    _save(rec)
    return rec


def cmd_post(args):
    print("post 尚未接上:對外發布需老闆先看過草稿並核可(2026-08-17 親令)。")
    print("草稿在", OUT)
    return 2


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("-n", type=int, default=20)
    d = sub.add_parser("draft"); d.add_argument("-n", type=int, default=3)
    r = sub.add_parser("roundup"); r.add_argument("-n", type=int, default=6)
    l = sub.add_parser("list"); l.add_argument("--topic"); l.add_argument("--items", type=int, default=7)
    p = sub.add_parser("post"); p.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    rc = {"scan": cmd_scan, "draft": cmd_draft, "roundup": cmd_roundup,
          "list": cmd_list, "post": cmd_post}[a.cmd](a)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
