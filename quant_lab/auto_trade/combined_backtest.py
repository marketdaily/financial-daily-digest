"""C+E regime 切換系統的整組回測:每天 pick_mode 路由(平靜趨勢→C突破/高波動→E fade)
→ replay_intraday 執行 → 累積權益。train/oos/lockbox 分段 + 權益曲線。
⚠️ 誠實揭露:開發期已多次看過 lockbox(魚C原始+波動閘校準),此回測大半 in-sample/已污染,
真法官=forward paper。且 intraday 僅 2025-01 起(~358日,約1.5年),樣本有限。成本 3.3 點。
用法:python3 combined_backtest.py
"""
import math
from collections import defaultdict

import tx_data
import intraday_data
from paper_daily import pick_mode, replay_intraday

COST = 3.3
PV = 200          # 小台每點 NT$50→用大台等價比較改200?這裡魚C/E paper=小台故 50
PV = 50


def mstats(xs):
    n = len(xs)
    if n < 2:
        return (0, 0, n)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, (m / (sd / math.sqrt(n)) if sd > 0 else 0), n


def max_dd(equity):
    peak = equity[0]
    mdd = 0
    for v in equity:
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    return mdd


def run_segment(days, db, bars_by_date, all_bars, idx):
    """回 [(date, fish, pnl_pts)]"""
    out = []
    for d in days:
        ds = d.isoformat()
        i = idx.get(ds)
        if i is None or i + 1 < 300:
            continue
        sub = all_bars[:i + 1]
        fish, dr = pick_mode(sub)
        if fish is None:
            continue
        r = replay_intraday(db[d], fish, dr)
        if r:
            pnl = r["side"] * (r["exit"] - r["entry"]) - COST
            out.append((d, fish, pnl))
    return out


def report(trades, label):
    if not trades:
        print(f"{label}: 0 筆")
        return
    pnls = [t[2] for t in trades]
    m, tstat, n = mstats(pnls)
    wr = sum(1 for x in pnls if x > 0) / n
    eq = [0]
    for p in pnls:
        eq.append(eq[-1] + p)
    mdd = max_dd(eq)
    byf = defaultdict(list)
    for _, f, p in trades:
        byf[f].append(p)
    fish_s = " | ".join(f"魚{f}:{len(v)}筆 {sum(v)*PV:+,.0f}元" for f, v in sorted(byf.items()))
    print(f"{label}: {n}筆 均{m:+.1f}點 勝率{wr:.0%} t={tstat:+.2f} "
          f"總{sum(pnls)*PV:+,.0f}元/口 最大回撤{mdd*PV:,.0f}元 最壞單筆{min(pnls)*PV:+,.0f}")
    print(f"    └ {fish_s}")


def main():
    all_bars = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(all_bars)}
    ib = intraday_data.load(day_session_only=True)
    db = defaultdict(list)
    for t, o, h, l, c, v in ib:
        db[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    dates = sorted(d for d in db if len(db[d]) >= 250)
    n = len(dates)
    tr, oo = dates[:int(n * .6)], dates[int(n * .6):int(n * .85)]
    lb = dates[int(n * .85):]
    print(f"intraday 可回測 {n} 天({dates[0]} → {dates[-1]});小台1口每點NT${PV}\n")

    for seg, name in [(tr, "train(前60%)"), (oo, "oos(中25%)"), (lb, "lockbox(後15%,已污染)"),
                      (dates, "全期間")]:
        report(run_segment(seg, db, None, all_bars, idx), name)

    # 全期間權益曲線(文字版)
    all_t = run_segment(dates, db, None, all_bars, idx)
    eq = 3_000_000
    peak = eq
    curve = []
    for d, f, p in all_t:
        eq += p * PV
        peak = max(peak, eq)
        curve.append((d, eq, 1 - eq / peak))
    if curve:
        print(f"\n虛擬300萬權益:期末 {curve[-1][1]:,.0f}({curve[-1][1]/3e6-1:+.1%}),"
              f"歷程最大回撤 {max((c[2] for c in curve))*100:.1f}%")
    print("\n⚠️ 誠實:開發期已看過lockbox→此數字大半in-sample,不能當edge證明;真裁決=forward paper。")


if __name__ == "__main__":
    main()
