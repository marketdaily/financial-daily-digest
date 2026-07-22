"""GEX 牆位日內 S/R 檢驗(nickelninjatrades reel 的可程式化部分)。
假說:價格觸及「前日 OI 算出的最大 gamma 牆」後傾向被彈回(做市商對沖=阻尼)。
設計:牆=前日 ±3% 內 gamma×OI 最大履約價;安慰劑=同區間 gamma 最小履約價(≥100點遠)。
觸碰=09:16 後首次 1分K 高低夾住該價位;彈回=觸後30分收盤回到來向側(正=彈回)。
牆 vs 安慰劑同法計算,差異 t 檢定。無前視(牆用前日收盤 OI)。
用法:python3 gamma_wall_study.py
"""
import math
from collections import defaultdict

import intraday_data
import txo_data
from gex_study import gamma_b76


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def touch_bounce(rows, level):
    """rows=[(hm,o,h,l,c)],跳過前30根;回 觸碰後30分「彈回」點數(正=回到來向側)或 None。"""
    for i in range(30, len(rows) - 1):
        hm, o, h, l, c = rows[i]
        if hm >= "13:10":
            return None                      # 太晚觸碰,30分窗不完整
        if l <= level <= h:
            prev_c = rows[i - 1][4]
            side = 1 if prev_c > level else -1   # 來向:上方=1 下方=-1
            j = min(i + 30, len(rows) - 1)
            fwd = rows[j][4] - c
            return side * fwd                # 正=往來向移動=被牆彈回
    return None


def main():
    days_txo = txo_data.load("2023-01-01")
    bars = intraday_data.load(day_session_only=True)
    by_day = defaultdict(list)
    for t, o, h, l, c, v in bars:
        by_day[t.date()].append((t.strftime("%H:%M"), o, h, l, c))
    dates = sorted(d for d in by_day if len(by_day[d]) >= 250)

    wall_b, plac_b = [], []
    used = 0
    prev_map = {}
    tx_dates = sorted(days_txo)
    for d in dates:
        ds = d.isoformat()
        prior = [x for x in tx_dates if x < ds]
        if not prior:
            continue
        rec = days_txo[prior[-1]]
        F, T, iv = rec["F"], max(rec["dte"], 1) / 365.0, rec["atm_iv"]
        weights = {}
        for ks, e in rec["strikes"].items():
            if "oc" not in e:
                continue
            K = float(ks)
            if abs(K - F) / F > 0.03:
                continue
            weights[K] = gamma_b76(F, K, T, iv) * (e.get("oc", 0) + e.get("op", 0))
        if len(weights) < 6:
            continue
        wall = max(weights, key=weights.get)
        far = {k: w for k, w in weights.items() if abs(k - wall) >= 100}
        if not far:
            continue
        plac = min(far, key=far.get)
        used += 1
        wb = touch_bounce(by_day[d], wall)
        pb = touch_bounce(by_day[d], plac)
        if wb is not None:
            wall_b.append(wb)
        if pb is not None:
            plac_b.append(pb)

    print(f"可用日 {used};牆觸碰 {len(wall_b)} 次、安慰劑觸碰 {len(plac_b)} 次\n")
    sw, sp = mstats(wall_b), mstats(plac_b)
    if sw:
        print(f"gamma 牆:觸後30分彈回均 {sw[0]:+.1f} 點  t={sw[2]:+.2f}  n={sw[3]}")
    if sp:
        print(f"安慰劑位:觸後30分彈回均 {sp[0]:+.1f} 點  t={sp[2]:+.2f}  n={sp[3]}")
    if sw and sp:
        se = math.sqrt(sw[1] ** 2 / sw[3] + sp[1] ** 2 / sp[3])
        t = (sw[0] - sp[0]) / se if se > 0 else 0
        print(f"牆 − 安慰劑差:{sw[0]-sp[0]:+.1f} 點  t={t:+.2f}")
        print("\n判定:", "牆位有超越一般價位的彈回效應,值得進下一關" if t > 2
              else "牆位彈回與一般價位無統計差異(或反向)——reel 的牆位 S/R 在台指日內不成立/不夠強")


if __name__ == "__main__":
    main()
