"""buy setup 條件化挖掘(2026-07-13 Delvin 親令「精準預判」)。
全量抓 ledger 全部 ticker 的日線史(2025-09 起)→ 1451 筆已結算列在 rec 日的技術 setup
→ setup × verdict × train/test(06-20 切,預先登記)EV/勝率表。
假設預先登記(來自 project_track_record_attribution):追高輸/回檔贏/bear結構sell贏。
"""
import json, math, time, urllib.request, sys
from collections import defaultdict
from datetime import date as D
from pathlib import Path

ROOT=Path("/home/userdelvin/Delvin-agent")
OUT=Path("/home/userdelvin/autonomous/research/2026-07-13_buy_setup_conditioning.md")
HCACHE=ROOT/"scripts"/".setup_mining_hist.json"

rows=[json.loads(s) for s in open(ROOT/"scripts/personal_ledger.jsonl",encoding="utf-8") if s.strip()]
rows=[e for e in rows if e.get("label") in ("win","loss") and e.get("chg") is not None]
tickers=sorted({e["ticker"] for e in rows})
print(f"{len(rows)} rows, {len(tickers)} tickers", flush=True)

hist=json.loads(HCACHE.read_text()) if HCACHE.exists() else {}
UA={"User-Agent":"Mozilla/5.0"}
def fetch(sym):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=20) as r:
        j=json.loads(r.read())
    res=j["chart"]["result"][0]
    ts=res.get("timestamp") or []
    cl=res["indicators"]["quote"][0].get("close") or []
    out={}
    for t,c in zip(ts,cl):
        if c is not None:
            out[time.strftime("%Y-%m-%d",time.gmtime(t))]=c
    return out

for i,tk in enumerate(tickers):
    if tk in hist: continue
    got=None
    cands=[f"{tk}.TW",f"{tk}.TWO"] if tk.isdigit() else [tk]
    for sym in cands:
        for att in range(3):
            try:
                got=fetch(sym)
                if len(got)>60: break
                got=None
            except Exception:
                time.sleep(1.5)
        if got: break
    hist[tk]=got or {}
    if i%20==0:
        HCACHE.write_text(json.dumps(hist))
        print(f"fetch {i}/{len(tickers)}",flush=True)
    time.sleep(0.4)
HCACHE.write_text(json.dumps(hist))
print("history done",flush=True)

import bisect
def feat(e):
    h=hist.get(e["ticker"]) or {}
    if not h: return None
    items=sorted(h.items()); dates=[x[0] for x in items]; px=[x[1] for x in items]
    i=bisect.bisect_right(dates,e["date"])-1
    if i<52: return None
    p=px[i]; ma20=sum(px[i-19:i+1])/20; ma50=sum(px[i-49:i+1])/50
    r5=p/px[i-5]-1; hi20=max(px[i-19:i+1]); ddown=p/hi20-1
    # RSI14
    gains=[max(px[k]-px[k-1],0) for k in range(i-13,i+1)]
    losses=[max(px[k-1]-px[k],0) for k in range(i-13,i+1)]
    ag=sum(gains)/14; al=sum(losses)/14
    rsi=100 if al==0 else 100-100/(1+ag/al)
    struct="uptrend" if p>ma20>ma50 else ("bear" if p<ma20<ma50 else "mixed")
    return dict(struct=struct,r5=r5,ext=(p-ma20)/ma20,ddown=ddown,rsi=rsi)

def setup(f):
    if f["struct"]=="uptrend" and f["ext"]>0.06: return "uptrend_extended"
    if f["struct"]=="uptrend" and f["r5"]<=0:   return "uptrend_pullback"
    if f["struct"]=="uptrend":                   return "uptrend_steady"
    if f["struct"]=="bear" and f["rsi"]<=30:     return "bear_oversold"
    if f["struct"]=="bear":                      return "bear"
    return "mixed"

SPLIT="2026-06-20"
def stats(xs):
    n=len(xs)
    if n<2: return n,0,0,0
    mu=sum(xs)/n; sd=math.sqrt(sum((x-mu)**2 for x in xs)/(n-1))
    return n,mu,sd,(mu/(sd/math.sqrt(n)) if sd>0 else 0)

lines=["# buy setup 條件化挖掘(2026-07-13)","",
f"- 全帳本 {len(rows)} 已結算列;train ≤ {SPLIT} < test;setup 分類與假設預先登記,不掃參。",
"- chg=5 交易日結算漲跌。buy/hold 看多(chg>0=對)、sell/wait 避空(chg<0=對)。",""]
skipped=0
byvs=defaultdict(lambda: defaultdict(list))
for e in rows:
    f=feat(e)
    if not f: skipped+=1; continue
    half="train" if e["date"]<=SPLIT else "test"
    byvs[(e["verdict_class"],setup(f))][half].append(e["chg"])
lines.append(f"(價史不足跳過 {skipped} 筆)\n")
for vc in ("buy","hold","wait","sell"):
    lines.append(f"## {vc}")
    lines.append(f"| setup | train n | train EV | train t | test n | test EV | 方向一致 |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in ("uptrend_pullback","uptrend_steady","uptrend_extended","mixed","bear","bear_oversold"):
        tr=byvs[(vc,s)]["train"]; te=byvs[(vc,s)]["test"]
        ntr,mtr,_,ttr=stats(tr); nte,mte,_,_=stats(te)
        agree="✅" if (ntr>=20 and nte>=10 and mtr*mte>0) else ""
        lines.append(f"| {s} | {ntr} | {mtr:+.2%} | {ttr:+.1f} | {nte} | {mte:+.2%} | {agree} |")
    lines.append("")
OUT.write_text("\n".join(lines),encoding="utf-8")
print("\n".join(lines[-40:]))
print(f"\nreport → {OUT}",flush=True)
