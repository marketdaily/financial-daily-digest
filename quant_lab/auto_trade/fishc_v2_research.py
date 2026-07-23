"""魚C 拉勝率研究:進場確認過濾(打假突破)。walk-forward 驗證,不看全域答案。
機制假設:魚C 的輸單多來自「假突破」(突破後立刻反轉)。加兩個確認閘可濾掉:
  - confirm:突破後要「連續站穩 N 根」才進(N=1 即現行)
  - buffer:收盤要突破 OR 邊界「至少 X 點」才算(X=0 即現行)
自我驗證:confirm=1/buffer=0 必須重現現行魚C基準(~56%勝率),對不上就不信變體。
walk-forward:每窗只用過去選最佳(confirm,buffer),測沒看過的下一段,每段用一次。
用法:python3 fishc_v2_research.py
"""
import math
from collections import defaultdict

import intraday_data
import tx_data
from paper_daily import pick_mode

COST = 3.3


def fishc(rows, gdir, confirm, buffer):
    """魚C 帶確認閘。回 pnl(點,含成本)或 None。"""
    if len(rows) < 40:
        return None
    orh = max(x[2] for x in rows[:30])
    orl = min(x[3] for x in rows[:30])
    cons = 0
    pos = 0
    entry = stop = 0.0
    for hm, o, h, l, c in rows[30:]:
        if pos == 0:
            if hm >= "13:30":
                break
            if gdir > 0:
                if c > orh + buffer:
                    cons += 1
                    if cons >= confirm:
                        pos, entry, stop = 1, c, orl
                else:
                    cons = 0
            elif gdir < 0:
                if c < orl - buffer:
                    cons += 1
                    if cons >= confirm:
                        pos, entry, stop = -1, c, orh
                else:
                    cons = 0
            continue
        if (pos > 0 and l <= stop) or (pos < 0 and h >= stop):
            return pos * (stop - entry) - COST
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
    wr = len(w) / n
    ratio = (sum(w) / len(w)) / abs(sum(l) / len(l)) if l and w else 0
    return dict(n=n, wr=wr, ratio=ratio, exp=m, sharpe=(m / sd if sd else 0))


def main():
    ib = intraday_data.load(day_session_only=True)
    db = defaultdict(list)
    for t, o, h, l, c, v in ib:
        db[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    allb = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(allb)}
    # 收集魚C日(pick_mode==C)及其方向
    cdays = []
    for d in sorted(db):
        i = idx.get(d.isoformat())
        if i is None or i < 300:
            continue
        f, dr = pick_mode(allb[:i + 1])
        if f == "C":
            cdays.append((d, dr))
    print(f"魚C 交易日 {len(cdays)} 天\n")

    # 自我驗證:baseline 必須重現
    base = [fishc(db[d], dr, 1, 0) for d, dr in cdays]
    base = [x for x in base if x is not None]
    s = stats(base)
    print(f"[自我驗證] baseline(confirm=1,buffer=0): {s['n']}筆 勝率{s['wr']:.0%} 期望{s['exp']:+.1f}點")
    print(f"           已知魚C基準≈56%/+19點 → {'✓對上,變體可信' if abs(s['wr']-0.56)<0.06 else '✗對不上,停止(harness有問題)'}\n")
    if abs(s["wr"] - 0.56) >= 0.06:
        return

    # 全域網格(僅供參考,會過度樂觀)
    grid = [(cf, bf) for cf in (1, 2, 3) for bf in (0, 10, 20, 30)]
    print(f"{'(confirm,buffer)':<18}{'筆數':>5}{'勝率':>6}{'賺賠比':>7}{'期望':>7}{'夏普':>7}  (全域in-sample)")
    for cf, bf in grid:
        p = [fishc(db[d], dr, cf, bf) for d, dr in cdays]
        p = [x for x in p if x is not None]
        st = stats(p)
        if st and st["n"] >= 20:
            mark = " ⭐勝率↑" if st["wr"] > s["wr"] + 0.03 else ""
            print(f"  cf={cf} buf={bf:<10}{st['n']:>5}{st['wr']:>6.0%}{st['ratio']:>6.1f}x{st['exp']:>+6.1f}{st['sharpe']:>+7.3f}{mark}")

    # walk-forward:每窗選最佳(依期望值),測下一段
    print("\n[walk-forward:參數只用過去選,測沒看過的段]")
    W, S = 60, 30
    oos_base, oos_sel = [], []
    i = 0
    while i + W + S <= len(cdays):
        ins = cdays[i:i + W]
        nxt = cdays[i + W:i + W + S]
        best = None
        best_exp = -1e9
        for cf, bf in grid:
            p = [fishc(db[d], dr, cf, bf) for d, dr in ins]
            p = [x for x in p if x is not None]
            if len(p) >= 15:
                e = sum(p) / len(p)
                if e > best_exp:
                    best_exp, best = e, (cf, bf)
        if best:
            oos_sel += [x for x in (fishc(db[d], dr, best[0], best[1]) for d, dr in nxt) if x is not None]
        oos_base += [x for x in (fishc(db[d], dr, 1, 0) for d, dr in nxt) if x is not None]
        i += S
    sb, ss = stats(oos_base), stats(oos_sel)
    print(f"  OOS baseline(不過濾): {sb['n']}筆 勝率{sb['wr']:.0%} 期望{sb['exp']:+.1f} 夏普{sb['sharpe']:+.3f}")
    print(f"  OOS 確認閘(過去選): {ss['n']}筆 勝率{ss['wr']:.0%} 期望{ss['exp']:+.1f} 夏普{ss['sharpe']:+.3f}")
    dwr = ss["wr"] - sb["wr"]
    print(f"\n  判定:勝率 {sb['wr']:.0%}→{ss['wr']:.0%}({dwr:+.0%}),期望 {sb['exp']:+.1f}→{ss['exp']:+.1f} → "
          + ("✓確認閘拉高勝率且不傷期望=魚C-v2進paper" if dwr > 0.03 and ss["exp"] >= sb["exp"] - 1
             else "✗過濾沒用或傷期望,維持現行魚C"))


if __name__ == "__main__":
    main()
