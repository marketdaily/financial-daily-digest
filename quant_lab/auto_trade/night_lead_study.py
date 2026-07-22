"""夜盤領先日盤(用戶提議的「全球脈絡鎖區間」):台指夜盤=美歐行情的總和,
測「夜盤方向/幅度」對「日盤 08:46→13:44」的預測力。
H1 方向:跟夜盤方向做日盤(門檻 0/30/60 點)
H2 波動:夜盤大動作 → 日盤振幅變大?(給魚C的趨勢日機率當閘)
成本 1.5 點。用 intraday 快取(含夜盤),無新資料源。
用法:python3 night_lead_study.py
"""
import math
import datetime
from collections import defaultdict

import intraday_data


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def main():
    bars = intraday_data.load(day_session_only=False)
    night = defaultdict(list)   # 歸屬到「次日日盤」的夜盤序列
    day = defaultdict(list)
    for t, o, h, l, c, v in bars:
        hm = t.hour * 60 + t.minute
        if 8 * 60 + 46 <= hm <= 13 * 60 + 45:
            day[t.date()].append((hm, o, h, l, c))
        elif hm >= 15 * 60 + 1:
            night[(t + datetime.timedelta(days=1)).date()].append((hm, c))
        elif hm <= 5 * 60:
            night[t.date()].append((hm + 1440, c))
    rows = []
    for d in sorted(day):
        if d not in night or len(night[d]) < 60 or len(day[d]) < 200:
            continue
        ns = sorted(night[d])
        n_ret = ns[-1][1] - ns[0][1]
        db = day[d]
        d_open = db[0][1]
        d_close = db[-1][4]
        d_rng = max(x[2] for x in db) - min(x[3] for x in db)
        gap = d_open - ns[-1][1]
        rows.append({"night": n_ret, "day": d_close - d_open, "rng": d_rng, "gap": gap})
    print(f"配對樣本 {len(rows)} 天(夜盤→次日日盤)\n")

    print("【H1 方向:開盤跟夜盤方向 → 13:44 出(含成本1.5點)】")
    half = len(rows) // 2
    for label, seg in [("全期間", rows), ("前半", rows[:half]), ("後半", rows[half:])]:
        for thr in (0, 30, 60):
            p = [(1 if r["night"] > 0 else -1) * r["day"] - 1.5
                 for r in seg if abs(r["night"]) >= thr]
            s = mstats(p)
            if not s:
                continue
            m, sd, t, n = s
            wr = sum(1 for x in p if x > 0) / n
            print(f"  {label:<5} |夜|≥{thr:>3}: n={n:>3} 均 {m:+6.1f} 點 勝率 {wr:.0%} t={t:+.2f}")
    print("\n【H2 波動:夜盤幅度 → 日盤振幅(給魚C當趨勢日機率閘)】")
    srt = sorted(rows, key=lambda r: abs(r["night"]))
    lo, hi = srt[:len(srt) // 3], srt[-len(srt) // 3:]
    sl, sh = mstats([r["rng"] for r in lo]), mstats([r["rng"] for r in hi])
    se = math.sqrt(sl[1] ** 2 / sl[3] + sh[1] ** 2 / sh[3])
    print(f"  夜盤安靜1/3 → 日盤振幅均 {sl[0]:.0f} 點;夜盤激烈1/3 → {sh[0]:.0f} 點;差 t={(sh[0]-sl[0])/se:+.2f}")


if __name__ == "__main__":
    main()
