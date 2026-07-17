"""TXO Gamma Exposure(GEX)研究:交易商 gamma 部位能否預測次日波動/回歸行為。

GEX(t) = Σ_K gamma(F,K,T,iv) × OI × 50,兩種符號慣例都測(台灣散戶=賣方文化,
美版「dealer 空 put 多 call」假設可能整個翻轉,讓資料自己說話):
- 美版慣例:GEX_us = Σ γ_c·OI_c − γ_p·OI_p(dealer 多 call 空 put)
- 量級版:GEX_abs = Σ γ_c·OI_c + γ_p·OI_p(不猜方向,只量「對沖 gamma 總量」)
gamma 用 ATM IV 統一算(忽略 smile,gamma 集中 ATM,二階誤差;誠實標注)。
訊號=T 日收盤 OI(收盤後可得)→ 檢驗 T+1:
①波動:T+1 振幅/|報酬| 按 GEX 五分位 ②行為:ret(T)×ret(T+1) 自相關按 GEX 分組
(正 gamma→阻尼→回歸=負自相關;負→放大→動能=正自相關)
③日級策略粗篩:低分位(放大器)→ 順昨日方向;高分位(阻尼器)→ 逆昨日方向。
用法:python3 gex_study.py
"""
import math

import txo_data
import tx_data

COST_PTS = 1.5
TX_POINT = 200


def gamma_b76(F, K, T, vol):
    if T <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    phi = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return phi / (F * vol * math.sqrt(T))


def build_gex(days):
    out = {}
    for d, x in days.items():
        F, T, iv = x["F"], max(x["dte"], 1) / 365.0, x["atm_iv"]
        us = mag = 0.0
        for ks, e in x["strikes"].items():
            if "oc" not in e:
                return None                      # 舊版快取無 OI
            g = gamma_b76(F, float(ks), T, iv)
            us += g * (e.get("oc", 0) - e.get("op", 0))
            mag += g * (e.get("oc", 0) + e.get("op", 0))
        out[d] = {"us": us * 50 * F, "mag": mag * 50 * F}
    return out


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def quintiles(pairs):
    """pairs=[(gex, 值)] → 5 組"""
    pairs = sorted(pairs)
    n = len(pairs)
    return [pairs[i * n // 5:(i + 1) * n // 5] for i in range(5)]


def main():
    days = txo_data.load("2023-01-01")
    gex = build_gex(days)
    if gex is None:
        print("快取還是 v1(無 OI),等 txo_data 重抓完成再跑。")
        return
    bars = tx_data.load("2020-01-01")
    idx = {b["date"]: i for i, b in enumerate(bars)}

    rows = []
    for d in sorted(gex):
        i = idx.get(d)
        if i is None or i + 1 >= len(bars) or i < 1:
            continue
        b0, b1, bm1 = bars[i], bars[i + 1], bars[i - 1]
        rows.append({
            "g_us": gex[d]["us"], "g_mag": gex[d]["mag"],
            "r0": (b0["close"] - bm1["close"]) / bm1["close"],
            "r1": (b1["close"] - b0["close"]) / b0["close"],
            "rng1": (b1["high"] - b1["low"]) / b0["close"],
            "oc1": b1["close"] - b1["open"],
        })
    print(f"GEX 樣本 {len(rows)} 天\n")

    for key, label in [("g_us", "美版符號 GEX"), ("g_mag", "量級版 |GEX|")]:
        print(f"【{label}:五分位 → 次日行為】")
        qs = quintiles([(r[key], r) for r in rows])
        print(f"  {'分位':<6}{'次日振幅均':>10}{'次日|報酬|':>10}{'自相關proxy':>12}")
        for i, q in enumerate(qs):
            rs = [r for _, r in q]
            rng = sum(r["rng1"] for r in rs) / len(rs)
            ar = sum(abs(r["r1"]) for r in rs) / len(rs)
            # 自相關 proxy:sign(r0)*r1 均值>0=動能、<0=回歸
            ac = sum((1 if r["r0"] > 0 else -1) * r["r1"] for r in rs) / len(rs)
            print(f"  Q{i+1:<5}{rng:>10.2%}{ar:>10.2%}{ac:>+12.3%}")
        lo = [r for _, r in qs[0]]
        hi = [r for _, r in qs[4]]
        s_lo = mstats([r["rng1"] for r in lo])
        s_hi = mstats([r["rng1"] for r in hi])
        pooled_se = math.sqrt(s_lo[1] ** 2 / s_lo[3] + s_hi[1] ** 2 / s_hi[3])
        t = (s_lo[0] - s_hi[0]) / pooled_se if pooled_se > 0 else 0
        print(f"  Q1 vs Q5 次日振幅差 t = {t:+.2f}(GEX 假說:低 gamma 波動大 → t 應顯著為正)\n")

    print("【日級策略粗篩(含成本):低分位順昨日方向、高分位逆昨日方向】")
    for key, label in [("g_us", "美版"), ("g_mag", "量級版")]:
        qs = quintiles([(r[key], r) for r in rows])
        pnls = []
        for _, r in qs[0]:
            side = 1 if r["r0"] > 0 else -1
            pnls.append(side * r["oc1"] - COST_PTS)
        for _, r in qs[4]:
            side = -1 if r["r0"] > 0 else 1
            pnls.append(side * r["oc1"] - COST_PTS)
        s = mstats(pnls)
        if s:
            m, sd, t, n = s
            wr = sum(1 for x in pnls if x > 0) / n
            print(f"  {label:<8} n={n:>4} 均 {m:+6.1f} 點 勝率 {wr:.0%} t={t:+.2f} 總 {sum(pnls)*TX_POINT:+,.0f} 元/口")

    print("\n口徑:gamma 用 ATM IV(忽略 smile)、±8% 履約價窗(截斷遠翼)、近月單一到期;")
    print("     OI=T 日收盤後可得,T+1 交易,無前視。粗篩性質,|t|>2 才進三關。")


if __name__ == "__main__":
    main()
