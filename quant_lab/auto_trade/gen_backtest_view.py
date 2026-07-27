"""生成魚C 策略的歷史回測視圖 → .paper/backtest.json(權益曲線+逐筆+統計),
供儀表板渲染「策略在動」的樣子。⚠️ 明確標為回測示意(含後見之明),非真實績效。
真實績效=forward paper(今天起累積)。winrig 月度可重生。
魚E 已處決(2026-07-27 幻想成交審計);出貨前過 fill_lint 閘門(停損記獲利=不出貨)。
用法:python3 gen_backtest_view.py
"""
import os
import json
from collections import defaultdict

import tx_data
import intraday_data
from paper_daily import pick_mode, replay_intraday, PDIR, START_EQUITY

COST = 3.3
PV = 50


def main():
    allb = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(allb)}
    ib = intraday_data.load(day_session_only=True)
    db = defaultdict(list)
    for t, o, h, l, c, v in ib:
        db[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    dates = sorted(d for d in db if len(db[d]) >= 250)

    trades = []
    eq = START_EQUITY
    curve = []
    for d in dates:
        i = idx.get(d.isoformat())
        if i is None or i < 300:
            continue
        f, dr = pick_mode(allb[:i + 1])
        if f is None:
            continue
        r = replay_intraday(db[d], f, dr)
        if r is None:
            continue
        pnl_pts = r["side"] * (r["exit"] - r["entry"]) - COST
        pnl = round(pnl_pts * PV)
        eq += pnl
        trades.append({"date": d.isoformat(), "fish": f,
                       "side": "多" if r["side"] > 0 else "空",
                       "reason": r["reason"], "pnl": pnl})
        curve.append(eq)
    def asym(sub):
        w=[t["pnl"] for t in sub if t["pnl"]>0]; l=[t["pnl"] for t in sub if t["pnl"]<=0]
        aw=sum(w)/len(w) if w else 0; al=sum(l)/len(l) if l else 0
        return {"n":len(sub),"wr":round(len(w)/len(sub)*100) if sub else 0,
                "avg_win":round(aw),"avg_loss":round(al),
                "ratio":round(aw/abs(al),1) if al else 0,"exp":round(sum(t["pnl"] for t in sub)/len(sub)) if sub else 0}
    from collections import defaultdict as _dd
    _byf=_dd(list)
    for t in trades: _byf[t["fish"]].append(t)
    wins = [t for t in trades if t["pnl"] > 0]

    # 激進加碼複利示意:口數=權益÷CAP(權益漲自動加碼、跌自動減碼),利潤滾入複利。
    # ⚠️ hindsight;複利+槓桿放大報酬也放大回撤;真實回撤比這更大。含 40% 回撤煞車(減半)。
    def compound_sim(cap, brake=0.40):
        ce = START_EQUITY; cur = []; seq = []; peak = ce; mdd = 0.0; braked = False
        for t in trades:
            lots = max(2, int(ce / cap))
            if braked:
                lots = max(1, lots // 2)          # 觸煞車後口數減半續跑(不歸零)
            ce += lots * t["pnl"]
            peak = max(peak, ce); dd = 1 - ce / peak if peak > 0 else 0
            mdd = max(mdd, dd)
            braked = dd >= brake                  # 回撤破胃納→減半
            cur.append(round(ce)); seq.append(lots)
        return {"curve": cur, "final": round(ce),
                "ret_pct": round((ce / START_EQUITY - 1) * 100, 1),
                "mdd_pct": round(mdd * 100, 1),
                "lots_start": seq[0] if seq else 0, "lots_max": max(seq) if seq else 0,
                "cap_per_lot": cap}
    compound = compound_sim(1_000_000)            # 穩健:起3口
    compound_aggr = compound_sim(180_000)         # 胃納:起~16口,吃到30-40%回撤

    peak_eq, mdd = START_EQUITY, 0.0
    for v in curve:
        peak_eq = max(peak_eq, v)
        mdd = max(mdd, 1 - v / peak_eq)

    from fill_lint import lint_trades
    bad = lint_trades(trades)
    if bad:
        for b in bad:
            print(f"🚨 fill-lint:{b['date']} 魚{b['fish']} 停損記獲利 {b['pnl']:+,}")
        raise SystemExit(f"❌ fill-realism 違規 {len(bad)} 筆,backtest.json 不出貨")

    out = {
        "fish_asym": {f: asym(v) for f,v in _byf.items()},
        "start": trades[0]["date"] if trades else None,
        "generated": dates[-1].isoformat(),
        "n": len(trades),
        "final_equity": eq,
        "ret_pct": round((eq / START_EQUITY - 1) * 100, 1),
        "mdd_pct": round(mdd * 100, 1),
        "win_rate": round(len(wins) / len(trades) * 100) if trades else 0,
        "curve": curve,
        "compound": compound,
        "compound_aggr": compound_aggr,
        "trades": trades[-25:],
    }
    os.makedirs(PDIR, exist_ok=True)
    with open(os.path.join(PDIR, "backtest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"回測視圖:{out['n']}筆 期末{out['final_equity']:,}({out['ret_pct']:+}%) 勝率{out['win_rate']}%")


if __name__ == "__main__":
    main()
