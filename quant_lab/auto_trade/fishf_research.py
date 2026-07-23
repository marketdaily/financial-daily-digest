"""魚F 研究:日內均值回歸(高勝率型,用戶要的「拉勝率」正解)。
機制:平靜盤整日,價格偏離均線太多→反向做,快速停利(回到均線就跑)=勝率天生高、賠賠比低。
選日:平靜(波動閘過)且盤整(EMA糾結 g=0)——正是魚C空手、魚E不碰的日子→天生與魚C低相關。
紀律:walk-forward(參數只用過去選);與魚C/E『不同物種+不同日子』才可能真分散化。
用法:python3 fishf_research.py
"""
import math
from collections import defaultdict

import intraday_data
import tx_data
from paper_daily import c_gates

COST = 3.3


def is_f_day(bars_upto):
    """平靜日(vol_ok)= 魚F 的日子(低波動日內易均值回歸;與魚C同日但機制相反,之後查相關)。"""
    g, vol_ok = c_gates(bars_upto)
    return vol_ok


def fishf(rows, N, D, STOP):
    """日內均值回歸,一天一單。偏離N期均線>D點→反向,目標=回均線,停損=進場±STOP。"""
    if len(rows) < N + 10:
        return None
    closes = [x[4] for x in rows]
    pos = 0
    entry = target = stop = 0.0
    for k in range(N, len(rows)):
        hm, o, h, l, c = rows[k]
        ma = sum(closes[k - N:k]) / N
        if pos == 0:
            if hm >= "13:30":
                break
            if c > ma + D:
                pos, entry, target, stop = -1, c, ma, c + STOP
            elif c < ma - D:
                pos, entry, target, stop = 1, c, ma, c - STOP
            continue
        if (pos > 0 and l <= stop) or (pos < 0 and h >= stop):
            return pos * (stop - entry) - COST
        if (pos > 0 and h >= target) or (pos < 0 and l <= target):
            return pos * (target - entry) - COST
        if hm >= "13:44":
            return pos * (c - entry) - COST
    if pos:
        return pos * (rows[-1][4] - entry) - COST
    return None


def stats(pnls):
    n = len(pnls)
    if n == 0:
        return None
    m = sum(pnls) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in pnls) / (n - 1)) if n > 1 else 0
    w = [x for x in pnls if x > 0]
    l = [x for x in pnls if x <= 0]
    return dict(n=n, wr=len(w) / n, ratio=(sum(w)/len(w))/abs(sum(l)/len(l)) if l and w else 0,
                exp=m, sharpe=(m / sd if sd else 0))


def main():
    ib = intraday_data.load(day_session_only=True)
    db = defaultdict(list)
    for t, o, h, l, c, v in ib:
        db[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    allb = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(allb)}
    fdays = []
    for d in sorted(db):
        i = idx.get(d.isoformat())
        if i is None or i < 300:
            continue
        if is_f_day(allb[:i + 1]):
            fdays.append(d)
    print(f"魚F 適用日(平靜盤整)= {len(fdays)} 天(魚C空手的那些日子)\n")
    if len(fdays) < 40:
        print("樣本不足,無法研究")
        return

    grid = [(N, D, S) for N in (20, 30) for D in (20, 30, 40) for S in (50, 70)]
    print(f"{'(N,D,stop)':<16}{'筆數':>5}{'勝率':>6}{'賺賠比':>7}{'期望':>7}{'夏普':>7}  (全域in-sample)")
    for N, D, S in grid:
        p = [fishf(db[d], N, D, S) for d in fdays]
        p = [x for x in p if x is not None]
        st = stats(p)
        if st and st["n"] >= 20:
            mark = " ⭐高勝率" if st["wr"] > 0.6 else ""
            print(f"  N={N} D={D} S={S:<6}{st['n']:>5}{st['wr']:>6.0%}{st['ratio']:>6.1f}x{st['exp']:>+6.1f}{st['sharpe']:>+7.3f}{mark}")

    print("\n[walk-forward:參數只用過去選,測沒看過的段]")
    W, S_ = 50, 25
    oos = []
    i = 0
    while i + W + S_ <= len(fdays):
        ins = fdays[i:i + W]
        nxt = fdays[i + W:i + W + S_]
        best, best_e = None, -1e9
        for params in grid:
            p = [fishf(db[d], *params) for d in ins]
            p = [x for x in p if x is not None]
            if len(p) >= 12:
                e = sum(p) / len(p)
                if e > best_e:
                    best_e, best = e, params
        if best:
            oos += [x for x in (fishf(db[d], *best) for d in nxt) if x is not None]
        i += S_
    s = stats(oos)
    if s:
        print(f"  OOS: {s['n']}筆 勝率{s['wr']:.0%} 賺賠比{s['ratio']:.1f}x 期望{s['exp']:+.1f} 夏普{s['sharpe']:+.3f}")
        ok = s["wr"] > 0.55 and s["exp"] > 0
        verdict = f"✓高勝率({s['wr']:.0%})且正期望 → 魚F進paper,與魚C低相關可望真分散化" if ok \
            else f"✗勝率{s['wr']:.0%}/期望{s['exp']:+.1f} → 魚F此版不成立"
        print(f"\n  判定:{verdict}")
    else:
        print("  OOS 無交易")


if __name__ == "__main__":
    main()
