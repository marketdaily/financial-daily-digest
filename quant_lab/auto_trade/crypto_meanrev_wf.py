"""Crypto 均值回歸 + 波動目標化 walk-forward(aggressive 戰場第二/三扇門)。
均值回歸:z=(close-MA_N)/std_N;z<-th 做多(超賣)、z>+th 做空,|z|<0.3 平倉。跟趨勢相反。
波動目標化:部位 = 目標波動/近期實現波動,把 60% native 回撤壓到可吞範圍。
成本 0.10% 來回。walk-forward 選參。
用法:python3 crypto_meanrev_wf.py [--symbol BTCUSDT]
"""
import argparse, math
import crypto_data

COST = 0.0010
BPY = 24 * 365


def zscore_series(closes, N):
    out = [None] * len(closes)
    for i in range(N, len(closes)):
        w = closes[i - N:i]
        m = sum(w) / N
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / N)
        out[i] = (closes[i] - m) / sd if sd else 0.0
    return out


def run_mr(rows, N, th, cost=COST):
    """均值回歸:超賣做多/超買做空,回中線平。回每根淨報酬。"""
    closes = [r[4] for r in rows]
    z = zscore_series(closes, N)
    pos = 0
    rets = []
    for i in range(N, len(rows) - 1):
        newpos = pos
        if z[i] is not None:
            if pos == 0:
                if z[i] < -th:
                    newpos = 1
                elif z[i] > th:
                    newpos = -1
            elif abs(z[i]) < 0.3:
                newpos = 0
        r_next = closes[i + 1] / closes[i] - 1
        net = newpos * r_next - (cost if newpos != pos else 0)
        rets.append(net)
        pos = newpos
    return rets


def vol_target(rows, base_rets, target_ann=0.5, N=48):
    """把 base 策略的每根報酬按近期實現波動反向縮放到 target_ann。"""
    closes = [r[4] for r in rows]
    lr = [0.0] + [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    out = []
    off = len(rows) - 1 - len(base_rets)   # base_rets 對齊起點
    for k, rt in enumerate(base_rets):
        i = off + k
        w = lr[max(0, i - N):i]
        rv = math.sqrt(sum(x * x for x in w) / len(w) * BPY) if w else 1.0
        lev = min(3.0, target_ann / rv) if rv else 0.0   # 上限 3x
        out.append(rt * lev)
    return out


def stats(rets):
    if not rets:
        return 0, 0, 0, 0
    eq = 1.0; peak = 1.0; mdd = 0.0
    for x in rets:
        eq *= (1 + x); peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    yrs = len(rets) / BPY
    cagr = eq ** (1 / yrs) - 1 if yrs > 0 and eq > 0 else -1
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) if len(rets) > 1 else 0
    sh = m / sd * math.sqrt(BPY) if sd else 0
    return eq - 1, cagr, mdd, sh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    a = ap.parse_args()
    rows = crypto_data.load(a.symbol)
    print(f"{a.symbol} {len(rows):,} 根 1H\n")

    grid = [(N, th) for N in (24, 48, 72) for th in (1.5, 2.0, 2.5)]
    print("均值回歸 全域 in-sample(參考):")
    print(f"{'(N,th)':>12}{'總報酬':>9}{'年化':>8}{'回撤':>7}{'夏普':>7}")
    for N, th in grid:
        r = run_mr(rows, N, th)
        tot, cagr, mdd, sh = stats(r)
        mark = " ⭐" if sh > 0.5 else ""
        print(f"  N={N} th={th:<5}{tot*100:>+7.0f}%{cagr*100:>+7.0f}%{mdd*100:>6.0f}%{sh:>+7.2f}{mark}")

    print("\n[walk-forward:(N,th) 只用過去選,測沒看過的段]")
    W, S = 24 * 60, 24 * 20
    oos = []
    i = 0
    while i + W + S <= len(rows):
        ins = rows[i:i + W]
        best, bh = None, -1e9
        for N, th in grid:
            s = stats(run_mr(ins, N, th))[3]
            if s > bh:
                bh, best = s, (N, th)
        seg = rows[i + W - 72:i + W + S]
        r = run_mr(seg, *best)
        oos += r[-S:] if len(r) >= S else r
        i += S
    tot, cagr, mdd, sh = stats(oos)
    print(f"  MR OOS: {len(oos):,}根 總{tot*100:+.0f}% 年化{cagr*100:+.0f}% 回撤{mdd*100:.0f}% 夏普{sh:+.2f}")

    vt = vol_target(rows[-len(oos) - 1:], oos, target_ann=0.4)
    tot2, cagr2, mdd2, sh2 = stats(vt)
    print(f"  +波動目標化(40%目標,≤3x): 年化{cagr2*100:+.0f}% 回撤{mdd2*100:.0f}% 夏普{sh2:+.2f}")
    v = "🟢 值得升paper" if sh > 0.3 else "🟡 偏弱需再驗" if sh > 0 else "🔴 此機制無edge"
    print(f"\n  判定:{v}(仍須 forward+DSR)")


if __name__ == "__main__":
    main()
