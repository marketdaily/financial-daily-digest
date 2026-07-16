"""波動率風險溢酬的正規衡量:ATM IV(t) vs 之後到到期的「未來」實現波動。

上一版 txo_vol_wf 用回望 EWMA 當比較基準(方法論缺陷,已標注);這版是正規口徑:
保險費(IV)對照之後真正發生的理賠(未來 RV),溢酬>0 才有「賣保險」的生意。
- 未來 RV:進場日起 dte 個日曆日內的 TX 日報酬年化標準差(交易日換算 252/365)
- 重疊樣本會灌水顯著性 → 另附「每合約取第一筆」的非重疊樣本 t 檢定(誠實版)
- 條件切片:IV 三分位 / 前5日絕對報酬(平靜vs剛震盪) / dte 桶 → 找溢酬肥的 regime
用法:python3 txo_premium_study.py
"""
import math

import txo_data
import tx_data


def main():
    days = txo_data.load("2023-01-01")
    tx = tx_data.load("2020-01-01")
    closes = [(r["date"], r["close"]) for r in tx]
    idx = {d: i for i, (d, _) in enumerate(closes)}

    def future_rv(date, dte_cal):
        i = idx.get(date)
        if i is None:
            return None
        n_td = max(3, round(dte_cal * 252 / 365))
        if i + n_td >= len(closes):
            return None                      # 視窗未走完,不猜
        rets = [math.log(closes[j + 1][1] / closes[j][1]) for j in range(i, i + n_td)]
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var * 252)

    def past_move(date, k=5):
        i = idx.get(date)
        if i is None or i < k:
            return None
        return abs(math.log(closes[i][1] / closes[i - k][1]))

    rows = []
    for d in sorted(days):
        x = days[d]
        rv = future_rv(d, x["dte"])
        if rv is None:
            continue
        rows.append({"date": d, "contract": x["contract"], "iv": x["atm_iv"],
                     "rv": rv, "prem": x["atm_iv"] - rv, "dte": x["dte"],
                     "move5": past_move(d)})
    if not rows:
        print("樣本不足")
        return

    def stats(sub, label):
        n = len(sub)
        ps = [r["prem"] for r in sub]
        m = sum(ps) / n
        pos = sum(1 for p in ps if p > 0) / n
        print(f"  {label:<28} n={n:>4}  平均溢酬 {m:+.1%}  為正 {pos:.0%}")
        return m

    print(f"IV vs 未來實現波動(到期口徑),樣本 {len(rows)} 天"
          f"({rows[0]['date']} → {rows[-1]['date']})\n")
    print("【全樣本(重疊,顯著性會灌水,只看方向)】")
    stats(rows, "全部")

    # 非重疊:每合約取第一筆 → 獨立樣本 t 檢定
    seen, indep = set(), []
    for r in rows:
        if r["contract"] not in seen:
            seen.add(r["contract"])
            indep.append(r)
    ps = [r["prem"] for r in indep]
    n = len(ps)
    m = sum(ps) / n
    sd = math.sqrt(sum((p - m) ** 2 for p in ps) / (n - 1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0
    print("\n【非重疊(每合約第一筆,獨立樣本,誠實檢定)】")
    print(f"  n={n}  平均 {m:+.1%}  標準差 {sd:.1%}  t={t:+.2f}"
          f"  → {'顯著' if abs(t) > 2 else '不顯著'}(|t|>2 門檻)")

    print("\n【條件切片(找溢酬肥的 regime;重疊樣本,方向參考)】")
    ivs = sorted(r["iv"] for r in rows)
    q1, q2 = ivs[len(ivs) // 3], ivs[2 * len(ivs) // 3]
    stats([r for r in rows if r["iv"] <= q1], f"低 IV(≤{q1:.0%})")
    stats([r for r in rows if q1 < r["iv"] <= q2], "中 IV")
    stats([r for r in rows if r["iv"] > q2], f"高 IV(>{q2:.0%})")
    mv = [r for r in rows if r["move5"] is not None]
    mvs = sorted(r["move5"] for r in mv)
    med = mvs[len(mvs) // 2]
    stats([r for r in mv if r["move5"] <= med], "前5日平靜(|報酬|低)")
    stats([r for r in mv if r["move5"] > med], "前5日剛震盪(|報酬|高)")
    stats([r for r in rows if r["dte"] <= 20], "近到期(dte≤20)")
    stats([r for r in rows if r["dte"] > 20], "遠到期(dte>20)")

    print("\n口徑:IV=近月ATM(parity F+Black-76);RV=進場日起至到期的TX日報酬年化;"
          "\n未走完視窗的近期樣本已剔除(不外推)。")


if __name__ == "__main__":
    main()
