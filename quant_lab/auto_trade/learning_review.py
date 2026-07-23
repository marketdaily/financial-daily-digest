"""每月自我學習複盤(winrig cron 月初跑):不是重跑回測看分數,是『學為什麼』——
把交易按盤勢切片,找出「哪種考題會做/不會做」,產出新假設進 pond,並偵測 edge 衰退。
真學習紀律:此處產出的都是【假設】,標「待 forward 驗證」,絕不自動部署。
資料:歷史(結構學習)+ .paper/ledger.jsonl(真 forward 學習,累積後才有力)。
用法:python3 learning_review.py
"""
import os
import json
import math
import datetime
from collections import defaultdict

import tx_data
import intraday_data
from paper_daily import pick_mode, replay_intraday, PDIR

COST = 3.3
PV = 50


def regime_of(bars):
    """把每天標成盤勢桶:趨勢強度(EMA斜率) × 波動分位。"""
    from paper_daily import c_gates
    g, vol_ok = c_gates(bars)
    return ("趨勢" if g != 0 else "盤整"), ("平靜" if vol_ok else "高波動")


def learn():
    allb = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(allb)}
    ib = intraday_data.load(day_session_only=True)
    db = defaultdict(list)
    for t, o, h, l, c, v in ib:
        db[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    dates = sorted(d for d in db if len(db[d]) >= 250)

    # 逐日重播,按盤勢桶歸類
    buckets = defaultdict(list)
    recent, older = [], []
    half = dates[len(dates) // 2]
    for d in dates:
        i = idx.get(d.isoformat())
        if i is None or i < 300:
            continue
        sub = allb[:i + 1]
        f, dr = pick_mode(sub)
        if f is None:
            continue
        r = replay_intraday(db[d], f, dr)
        if r is None:
            continue
        pnl = r["side"] * (r["exit"] - r["entry"]) - COST
        tr, vol = regime_of(sub)
        buckets[(f, tr, vol)].append(pnl)
        (recent if d >= half else older).append(pnl)

    print("=== 每月學習複盤 ===")
    print(f"複盤日 {datetime.date.today().isoformat()}\n")
    print("【1. 哪種考題會做?——盤勢切片(歷史結構學習)】")
    print(f"  {'魚×盤勢':<20}{'筆數':>5}{'每筆均':>9}{'勝率':>7}")
    for k, v in sorted(buckets.items(), key=lambda kv: -sum(kv[1])):
        f, tr, vol = k
        m = sum(v) / len(v)
        wr = sum(1 for x in v if x > 0) / len(v)
        flag = " ⭐該多打" if m > 5 else (" ⚠️該避開" if m < -5 else "")
        print(f"  魚{f}·{tr}{vol:<8}{len(v):>5}{m:>+8.1f}點{wr:>7.0%}{flag}")

    print("\n【2. edge 有沒有在衰退?——近半 vs 前半(市場題目變了嗎)】")
    for lbl, seg in [("前半段", older), ("近半段", recent)]:
        if seg:
            m = sum(seg) / len(seg)
            print(f"  {lbl}: {len(seg)}筆 每筆均 {m:+.1f}點 總 {sum(seg)*PV:+,.0f}元")
    if recent and older:
        drift = sum(recent) / len(recent) - sum(older) / len(older)
        print(f"  → 漂移 {drift:+.1f}點/筆 "
              + ("(近期變好)" if drift > 3 else "(近期衰退,需查regime或重驗)" if drift < -3 else "(穩定)"))

    print("\n【3. 真 forward 學習(paper 帳本)】")
    try:
        evs = [json.loads(l) for l in open(os.path.join(PDIR, "ledger.jsonl"), encoding="utf-8")]
        trades = [e for e in evs if "pnl_ntd" in e]
        if len(trades) < 5:
            print(f"  paper 僅 {len(trades)} 筆,樣本不足——真學習還在累積(這才是唯一沒污染的老師)")
        else:
            byf = defaultdict(list)
            for e in trades:
                byf[e["fish"]].append(e["pnl_ntd"])
            for f, v in byf.items():
                print(f"  魚{f}: {len(v)}筆 {sum(v):+,}元 勝率{sum(1 for x in v if x>0)/len(v):.0%}")
    except FileNotFoundError:
        print("  paper 帳本尚未生成")

    print("\n【4. 產出的新假設(進 pond,待 forward 驗證,不自動部署)】")
    print("  - 檢視第1點:有無『某魚在某盤勢一致虧』→ 該盤勢加禁區閘(新假設)")
    print("  - 檢視第2點:若近期衰退→該 edge 可能被市場學走,查是否需退役或換 regime")
    print("  ⚠️ 以上皆假設;任何規則變更必先 forward paper 驗,禁止看到結果就改上線。")


if __name__ == "__main__":
    learn()
