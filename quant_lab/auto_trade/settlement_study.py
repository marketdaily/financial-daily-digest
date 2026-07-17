"""台指結算日效應(魚池 Tier B):每月第三個週三(逢假日順延)結算,制度性換倉/
結算流量是否留下可交易的日級足跡(D-1/D0/D+1 的方向或波動異常)。
資料全在手(TX 日線),先驗中等——流量真實存在,但方向性未必。
用法:python3 settlement_study.py
"""
import math
import datetime

import tx_data
from txo_data import third_wednesday


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def main():
    bars = tx_data.load("2020-01-01")
    tds = [b["date"] for b in bars]
    idx = {d: i for i, d in enumerate(tds)}
    by = {b["date"]: b for b in bars}

    settles = []
    y0, y1 = int(tds[0][:4]), int(tds[-1][:4])
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            t = third_wednesday(f"{y}{m:02d}")
            cand = [d for d in tds if d >= t.isoformat()][:1]   # 逢假日順延
            if cand and (datetime.date.fromisoformat(cand[0]) - t).days <= 5:
                settles.append(cand[0])
    settles = [d for d in settles if d in idx and 1 <= idx[d] < len(tds) - 1]
    print(f"結算日 {len(settles)} 個({settles[0]} → {settles[-1]})\n")

    def day_ret(i):
        return (bars[i]["close"] - bars[i]["open"]) / bars[i]["open"] * 100

    base_r = [day_ret(i) for i in range(len(bars))]
    base_a = [abs(x) for x in base_r]
    bm_r, _, _, _ = mstats(base_r)
    bm_a, _, _, _ = mstats(base_a)

    print(f"{'窗':<8}{'n':>4}{'方向均(%)':>10}{'t':>7}{'|振幅|均(%)':>12}{'常日|振幅|':>10}")
    print("-" * 55)
    results = {}
    for label, off in [("D-1", -1), ("D0結算", 0), ("D+1", 1)]:
        rs = [day_ret(idx[d] + off) for d in settles]
        m, sd, t, n = mstats(rs)
        a = sum(abs(x) for x in rs) / n
        results[label] = (m, t)
        print(f"{label:<8}{n:>4}{m:>+10.3f}{t:>+7.2f}{a:>12.3f}{bm_a:>10.3f}")

    best = max(results.items(), key=lambda kv: abs(kv[1][1]))
    print(f"\n判定:最強窗 {best[0]} t={best[1][1]:+.2f} → "
          f"{'有訊號,進下一關' if abs(best[1][1]) > 2 else '無日級方向訊號(|t|<2);結算流量效應若存在應在日內(結算前30分鐘均價機制),待週一 1分K'}")


if __name__ == "__main__":
    main()
