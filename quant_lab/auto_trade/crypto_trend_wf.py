"""Crypto 趨勢/動能 walk-forward 誠實驗證(aggressive 戰場首測)。
機制:Donchian 突破(收盤破 K 小時高→做多、破 K 小時低→做空),下一根執行。
成本:每次換倉 0.10% 來回(Binance perp taker 保守;掛單更低)。
紀律:參數只用過去選,測沒看過的段;報酬單位=%(無槓桿基準),另列槓桿後年化+回撤。
用法:python3 crypto_trend_wf.py [--symbol BTCUSDT]
"""
import argparse, math
import crypto_data

COST = 0.0010   # 來回換倉成本(taker 約 0.05%×2)
BARS_PER_YEAR = 24 * 365


def run(rows, K, cost=COST):
    """Donchian(K) 多空全時在場。回 (每根報酬序列, 換倉次數)。"""
    closes = [r[4] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    pos = 0
    rets, flips = [], 0
    for i in range(K, len(rows) - 1):
        hh = max(highs[i - K:i]); ll = min(lows[i - K:i])
        newpos = pos
        if closes[i] > hh:
            newpos = 1
        elif closes[i] < ll:
            newpos = -1
        if newpos != pos:
            flips += 1
        r_next = closes[i + 1] / closes[i] - 1
        gross = newpos * r_next
        net = gross - (cost if newpos != pos else 0)
        rets.append(net)
        pos = newpos
    return rets, flips


def sharpe_ann(rets):
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    return (m / sd * math.sqrt(BARS_PER_YEAR)) if sd else 0.0


def stats(rets):
    eq = 1.0; peak = 1.0; mdd = 0.0
    for x in rets:
        eq *= (1 + x); peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    yrs = len(rets) / BARS_PER_YEAR
    cagr = eq ** (1 / yrs) - 1 if yrs > 0 and eq > 0 else -1
    return eq - 1, cagr, mdd, sharpe_ann(rets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    a = ap.parse_args()
    rows = crypto_data.load(a.symbol)
    print(f"{a.symbol} {len(rows):,} 根 1H({rows[0][0]} → {rows[-1][0]})\n")

    grid = [12, 24, 48, 72, 168]   # 突破窗:半天~一週
    # 全域 in-sample(參考,會過度樂觀)
    print(f"{'Donchian K':>10}{'總報酬':>9}{'年化':>8}{'回撤':>7}{'夏普':>7}{'換倉':>7}")
    for K in grid:
        rets, flips = run(rows, K)
        tot, cagr, mdd, sh = stats(rets)
        print(f"{K:>10}{tot*100:>+8.0f}%{cagr*100:>+7.0f}%{mdd*100:>6.0f}%{sh:>+7.2f}{flips:>7}")

    # walk-forward:每窗用過去 60 天選最佳 K(依夏普),測接下來 20 天
    print("\n[walk-forward:K 只用過去選,測沒看過的段]")
    W, S = 24 * 60, 24 * 20
    oos = []
    i = 0
    while i + W + S <= len(rows):
        ins = rows[i:i + W]
        best, bh = None, -1e9
        for K in grid:
            r, _ = run(ins, K)
            s = sharpe_ann(r)
            if s > bh:
                bh, best = s, K
        seg = rows[i + W - max(grid):i + W + S]   # 帶入前導窗給 Donchian
        r, _ = run(seg, best)
        oos += r[-(S):] if len(r) >= S else r
        i += S
    tot, cagr, mdd, sh = stats(oos)
    print(f"  OOS: {len(oos):,} 根 總{tot*100:+.0f}% 年化{cagr*100:+.0f}% 回撤{mdd*100:.0f}% 夏普{sh:+.2f}")
    print(f"\n  槓桿後(你要的激進,吞 -30~40% 回撤):")
    for lev in (1, 2, 3):
        # 近似:報酬×lev、回撤×lev(小倉近似,大槓桿有路徑風險,僅示意)
        print(f"    {lev}x: 年化 {cagr*lev*100:+.0f}%  回撤 ~{mdd*lev*100:.0f}%"
              + ("  ← 撞你的回撤上限" if mdd * lev > 0.40 else ""))
    verdict = "🟢 OOS 正夏普→值得升格 paper" if sh > 0.3 else \
              "🟡 OOS 夏普偏弱,需再驗/換機制" if sh > 0 else "🔴 OOS 負→此機制在此幣無 edge"
    print(f"\n  判定:{verdict}(單一 in-sample,仍須 forward+DSR 扣試驗數)")


if __name__ == "__main__":
    main()
