"""馬克羊#1 尾盤強制平倉:1分K 正式裁決(初測 n=30 的升級版,定義完全對齊
quant_lab/tail_exit/tail_exit_study.py)。

假說:①趨勢日 13:30→13:44 順勢有「強平燃料」延續 ②13:44 出場優於抱到 13:45。
定義(無前視):趨勢=開盤(08:45)→13:30 淨移動;價格取分鐘K收盤
  p1330=13:29K收、p1344=13:43K收、p1345=13:44K收(日盤末根)。
可交易版:|趨勢|≥門檻 → 13:30 順勢進場、13:44 出場,成本 1.5 點。
用法:python3 tail_exit_formal.py
"""
import math
from collections import defaultdict

import intraday_data

COST_PTS = 1.5
TX_POINT = 200


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def build_days():
    bars = intraday_data.load(day_session_only=True)
    by_day = defaultdict(dict)
    for t, o, h, l, c, v in bars:
        by_day[t.date()][t.strftime("%H:%M")] = (o, c)
    days = []
    # Shioaji 分鐘K時間戳=K棒「結束」時間:08:45那根標08:46;13:30整點價=標13:30那根的收盤
    for d in sorted(by_day):
        m = by_day[d]
        if "08:46" not in m or "13:30" not in m or "13:44" not in m or "13:45" not in m:
            continue
        days.append({"date": d, "open": m["08:46"][0], "p1330": m["13:30"][1],
                     "p1344": m["13:44"][1], "p1345": m["13:45"][1]})
    return days


def main():
    days = build_days()
    print(f"完整日 {len(days)} 天({days[0]['date']} → {days[-1]['date']})\n")

    print(f"{'門檻':>5}{'n':>5}{'延續均(點)':>10}{'t':>7}{'勝率':>6}{'最後1分均':>10}{'t':>7}")
    print("-" * 52)
    for th in (150, 250, 400):
        sel = [x for x in days if abs(x["p1330"] - x["open"]) >= th]
        if len(sel) < 5:
            print(f"{th:>5}{len(sel):>5}   樣本不足")
            continue
        sgn = lambda x: 1 if x["p1330"] > x["open"] else -1
        cont = [sgn(x) * (x["p1344"] - x["p1330"]) for x in sel]
        last = [sgn(x) * (x["p1345"] - x["p1344"]) for x in sel]
        cm, _, ct, cn = mstats(cont)
        lm, _, lt, _ = mstats(last)
        wr = sum(1 for v in cont if v > 0) / cn
        print(f"{th:>5}{cn:>5}{cm:>+10.1f}{ct:>+7.2f}{wr:>6.0%}{lm:>+10.1f}{lt:>+7.2f}")

    print("\n【可交易版:13:30 順勢進 → 13:44 出,含成本 1.5 點】")
    half = len(days) // 2
    for label, seg in [("全期間", days), ("前半", days[:half]), ("後半", days[half:])]:
        for th in (150, 250):
            sel = [x for x in seg if abs(x["p1330"] - x["open"]) >= th]
            if len(sel) < 5:
                continue
            pnls = [(1 if x["p1330"] > x["open"] else -1) * (x["p1344"] - x["p1330"]) - COST_PTS
                    for x in sel]
            m, sd, t, n = mstats(pnls)
            wr = sum(1 for v in pnls if v > 0) / n
            print(f"  {label:<6} 門檻{th}: n={n:>3} 均 {m:+6.1f} 點 勝率 {wr:.0%} t={t:+.2f} "
                  f"總 {sum(pnls)*TX_POINT:+,.0f} 元/口")

    print("\n口徑:近月連續(TXFR1)、日盤分鐘K、無前視;「13:44出優於13:45」看最後1分均值的負向程度。")


if __name__ == "__main__":
    main()
