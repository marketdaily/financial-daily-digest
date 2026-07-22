"""結算日日內足跡(日級已判無訊號,這裡看日內):結算價=現貨 13:00-13:30 均價
→ 結算日的 13:00-13:30 窗應有異常(收斂/波動)。⚠️ TXFR1 在結算週已換次月,
結算日當天序列多為「新近月」,到期合約的 pinning 看不到——能測的是「結算日的
市場整體日內行為」vs 常日,誠實標注此限制。
用法:python3 settlement_intraday.py
"""
import math
import datetime
from collections import defaultdict

import intraday_data
from txo_data import third_wednesday


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def main():
    bars = intraday_data.load(day_session_only=True)
    by_day = defaultdict(dict)
    for t, o, h, l, c, v in bars:
        by_day[t.date()][t.strftime("%H:%M")] = c
    dates = sorted(by_day)

    settles = set()
    for y in (2025, 2026):
        for m in range(1, 13):
            t = third_wednesday(f"{y}{m:02d}")
            nxt = [d for d in dates if d >= t]
            if nxt and (nxt[0] - t).days <= 5:
                settles.add(nxt[0])

    def win_stats(d):
        m = by_day[d]
        need = ["09:00", "13:00", "13:30", "13:44"]
        if any(k not in m for k in need):
            return None
        return {
            "am": (m["13:00"] - m["09:00"]),
            "w1300_1330": m["13:30"] - m["13:00"],
            "w1330_1344": m["13:44"] - m["13:30"],
            "aw": abs(m["13:30"] - m["13:00"]),
        }

    ev, base = [], []
    for d in dates:
        s = win_stats(d)
        if s:
            (ev if d in settles else base).append(s)
    print(f"結算日 {len(ev)} / 常日 {len(base)}\n")
    print(f"{'量':<16}{'結算日均':>10}{'常日均':>10}{'差t':>7}")
    print("-" * 45)
    for k, lab in [("w1300_1330", "13:00→13:30 淨移動"), ("aw", "13:00→13:30 |移動|"),
                   ("w1330_1344", "13:30→13:44 淨移動")]:
        a = [x[k] for x in ev]
        b = [x[k] for x in base]
        sa, sb = mstats(a), mstats(b)
        se = math.sqrt(sa[1] ** 2 / sa[3] + sb[1] ** 2 / sb[3])
        t = (sa[0] - sb[0]) / se if se > 0 else 0
        print(f"{lab:<16}{sa[0]:>+10.1f}{sb[0]:>+10.1f}{t:>+7.2f}")

    # 反轉假說:結算日 13:00-13:30 逆早盤方向?
    fades = [( -1 if x["am"] > 0 else 1) * x["w1300_1330"] for x in ev]
    s = mstats(fades)
    if s:
        print(f"\n結算日 fade 早盤方向(13:00→13:30):均 {s[0]:+.1f} 點 t={s[2]:+.2f} n={s[3]}")
    print("\n限制:TXFR1 結算週已換次月,無法觀察到期合約 pinning;此為市場整體足跡。")


if __name__ == "__main__":
    main()
