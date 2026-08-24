"""跌深超賣反彈 shadow 追蹤(2026-07-13,setup 挖掘②的 forward test)。
每日:全 universe(ledger 歷史 ticker)算 bear 結構+RSI<=30 → 候選記入 bounce_shadow.jsonl;
既有列滿 5 個交易日自動結算 chg;附滾動統計。兩週後 EV/勝率過 gate 才升級進日報。
規則預先登記:bear=P<MA20<MA50, RSI14<=30。零 LLM、零寄信、不碰日報。
"""
import json, time, math, urllib.request, sys
from pathlib import Path
from datetime import date

ROOT=Path(__file__).resolve().parent
LEDGER=ROOT/"bounce_shadow.jsonl"
UA={"User-Agent":"Mozilla/5.0"}

def fetch(sym):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=6mo&interval=1d"
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=20) as r:
        j=json.loads(r.read())
    res=j["chart"]["result"][0]
    ts=res.get("timestamp") or []; cl=res["indicators"]["quote"][0].get("close") or []
    return [(time.strftime("%Y-%m-%d",time.gmtime(t)),c) for t,c in zip(ts,cl) if c is not None]

def series(tk):
    for sym in ([f"{tk}.TW",f"{tk}.TWO"] if tk.isdigit() else [tk]):
        for _ in range(3):
            try:
                h=fetch(sym)
                if len(h)>60: return h
            except Exception:
                time.sleep(1.2)
    return None

def signal(h):
    px=[c for _,c in h]
    if len(px)<52: return None
    p=px[-1]; ma20=sum(px[-20:])/20; ma50=sum(px[-50:])/50
    if not (p<ma20<ma50): return None
    g=[max(px[k]-px[k-1],0) for k in range(-14,0)]
    l=[max(px[k-1]-px[k],0) for k in range(-14,0)]
    ag,al=sum(g)/14,sum(l)/14
    rsi=100 if al==0 else 100-100/(1+ag/al)
    return {"price":p,"rsi":round(rsi,1)} if rsi<=30 else None

def main():
    today=date.today().isoformat()
    rows=[json.loads(s) for s in LEDGER.read_text(encoding="utf-8").splitlines() if s.strip()] if LEDGER.exists() else []
    seen={(r["date"],r["ticker"]) for r in rows}
    hist_rows=[json.loads(s) for s in open(ROOT.parent/"scripts/personal_ledger.jsonl",encoding="utf-8") if s.strip()]
    universe=sorted({e["ticker"] for e in hist_rows})
    cache={}
    new=0
    for tk in universe:
        h=series(tk); time.sleep(0.4)
        if not h: continue
        cache[tk]=h
        sig=signal(h)
        if sig and (today,tk) not in seen:
            rows.append({"date":today,"ticker":tk,"entry":sig["price"],"rsi":sig["rsi"],"chg":None})
            new+=1
    # 結算:滿 5 個交易 bar 的未結列
    settled=0
    for r in rows:
        if r["chg"] is not None: continue
        h=cache.get(r["ticker"]) or series(r["ticker"])
        if not h: continue
        cache[r["ticker"]]=h
        dates=[d for d,_ in h]
        if r["date"] not in dates:
            import bisect
            i=bisect.bisect_right(dates,r["date"])-1
        else:
            i=dates.index(r["date"])
        if i>=0 and i+5<len(h):
            r["chg"]=round(h[i+5][1]/h[i][1]-1,5); settled+=1
    tmp=LEDGER.with_suffix(".tmp")
    tmp.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n",encoding="utf-8")
    tmp.replace(LEDGER)
    done=[r for r in rows if r["chg"] is not None]
    if done:
        ev=sum(r["chg"] for r in done)/len(done)
        wr=100*sum(1 for r in done if r["chg"]>0)/len(done)
        print(f"{today}: +{new} 候選, 結算 {settled}; 累計 n={len(done)} EV={ev:+.2%} 勝率={wr:.0f}%")
    else:
        print(f"{today}: +{new} 候選, 尚無結算")

if __name__=="__main__":
    main()
