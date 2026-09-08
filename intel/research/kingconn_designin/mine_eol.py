#!/usr/bin/env python3
"""皇海 EOL 料號 design-in 礦機
問題:39 顆停產 Molex/ALPS 卡座,現在還有誰的公開設計檔在用?每一個命中=一塊被迫換料的板子。
⭐ 料號格式決定生死:Molex 10 碼有兩種書寫慣例,只搜一種會漏掉大半(實測 503182-1852=249 命中,
   同一顆的 5031821852=194,而 47309-1525=0 但 0473091525=32)。所以逐顆搜多種變體再去重。
"""
import json, subprocess, time, sys, os, re
from collections import defaultdict

MAP = json.load(open(os.path.expanduser("~/kingconn/tools/xref/mapping.json")))
OUT = os.path.expanduser("~/Delvin-agent/intel/research/kingconn_designin/github_hits.json")

def variants(mpn, brand):
    v = {mpn}
    if brand == "Molex" and mpn.isdigit() and len(mpn) == 10:
        v.add(f"{mpn[:6]}-{mpn[6:]}")          # 503182-1852
        if mpn[0] == "0":
            v.add(f"{mpn[1:6]}-{mpn[6:]}")      # 47309-1525
            v.add(mpn[1:])                       # 473091525
    return sorted(v)

def search(q):
    for attempt in range(4):
        p = subprocess.run(["gh","api","-X","GET","search/code","-f",f"q={q}","-f","per_page=100"],
                           capture_output=True, text=True, timeout=120)
        if p.returncode == 0:
            try: return json.loads(p.stdout)
            except Exception: return None
        if "rate limit" in (p.stderr or "").lower() or "403" in (p.stderr or ""):
            time.sleep(25); continue
        return None
    return None

res = {}
for i,(mpn, meta) in enumerate(sorted(MAP.items())):
    entry = {"brand": meta["brand"], "card": meta["card"], "mech": meta.get("mech"),
             "kc": meta["kc"], "queries": {}, "repos": {}}
    for q in variants(mpn, meta["brand"]):
        d = search(q)
        time.sleep(7)                      # code search = 10 req/min
        if d is None:
            entry["queries"][q] = None; continue
        entry["queries"][q] = d.get("total_count", 0)
        for it in d.get("items", []):
            r = it["repository"]
            full = r["full_name"]
            rec = entry["repos"].setdefault(full, {
                "owner_type": r["owner"]["type"], "private": r.get("private"),
                "desc": (r.get("description") or "")[:200], "files": []})
            if it["path"] not in rec["files"]:
                rec["files"].append(it["path"])
    res[mpn] = entry
    print(f"[{i+1}/{len(MAP)}] {mpn} {meta['brand']:11s} repos={len(entry['repos']):3d} "
          f"counts={entry['queries']}", flush=True)
    json.dump(res, open(OUT,"w"), ensure_ascii=False, indent=1)
print("DONE ->", OUT)
