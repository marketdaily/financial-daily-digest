"""_uo_call(強贖上限選擇權)閉式解 vs 蒙地卡羅交叉驗證。
MC:GBM 日頻路徑,首次觸 B 即以 (B−K) 折現入帳;未觸及則到期 max(S−K,0) 折現。
日頻離散監控會低估觸價機率 → MC 略高於連續監控閉式解,容忍 3%+0.15 絕對值。"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cb_core


def mc_uo(S, K, T, sigma, r, B, n_paths=60000, seed=7, pay="intrinsic"):
    rng = random.Random(seed)
    steps = max(int(T * 252), 10)
    dt = T / steps
    drift = (r - 0.5 * sigma * sigma) * dt
    volstep = sigma * math.sqrt(dt)
    total = 0.0
    for _ in range(n_paths):
        s = S
        hit = False
        for i in range(1, steps + 1):
            s *= math.exp(drift + volstep * rng.gauss(0, 1))
            if s >= B:
                # pay="rebate":付 (B−K) → 觸價偵測偏晚+付偏少 = 下界
                # pay="intrinsic":付 (s−K) overshoot 內含值 → 過度補償 = 上界
                # 兩口徑夾住連續監控真值
                pv = (B - K) if pay == "rebate" else (s - K)
                total += pv * math.exp(-r * i * dt)
                hit = True
                break
        if not hit:
            total += max(s - K, 0.0) * math.exp(-r * T)
    return total / n_paths


def check(S, K, T, sigma, r, mult):
    B = K * mult
    cf = cb_core._uo_call(S, K, T, sigma, r, B)
    lo = mc_uo(S, K, T, sigma, r, B, pay="rebate")
    hi = mc_uo(S, K, T, sigma, r, B, pay="intrinsic")
    vanilla = cb_core.bs_call(S, K, T, sigma, r)[0]
    slack = 0.01 * max(hi, 1.0) + 0.1      # MC 抽樣誤差緩衝
    ok = (lo - slack) <= cf <= (hi + slack) and cf <= vanilla + 1e-9
    print(f"S={S} K={K} T={T} σ={sigma} B={B:.1f}: 閉式 {cf:.3f} ∈ MC夾擠 [{lo:.3f}, {hi:.3f}] "
          f"(vanilla {vanilla:.3f}) {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    cases = [
        (90.2, 95.3, 3.0, 0.56, 0.013, 1.35),   # 至上11 實例
        (1590, 2180, 3.0, 0.84, 0.013, 1.35),   # 宜鼎二 實例(深價外高波動)
        (100, 100, 2.0, 0.30, 0.013, 1.35),     # 價平中波動
        (100, 80, 1.0, 0.40, 0.013, 1.35),      # 價內(近障礙)
        (100, 100, 3.0, 0.50, 0.013, 3.0),      # 障礙極遠 → 應趨近 vanilla
    ]
    ok = all(check(*c) for c in cases)
    # 障礙極遠收斂 vanilla 檢查
    far = cb_core._uo_call(100, 100, 3.0, 0.5, 0.013, 100 * 50)
    van = cb_core.bs_call(100, 100, 3.0, 0.5, 0.013)[0]
    conv = abs(far - van) < 0.01
    print(f"B→∞ 收斂 vanilla:{far:.4f} vs {van:.4f} {'PASS' if conv else 'FAIL'}")
    sys.exit(0 if (ok and conv) else 1)


if __name__ == "__main__":
    main()
