"""外資台指期淨部位跟隨(魚池 Tier B):三大法人期貨部位每日 15:00 後公布(T日資料
T日收盤後可得)→ 訊號=外資淨未平倉(多-空)的當日變化 → 次日開盤進場、收盤出場。
結構性理由:外資=資訊/動能流,散戶逆外資=長期輸家(先驗中上,但太有名,edge 可能已被吃)。
誠實口徑:T 日訊號只用 T+1 交易(無前視);成本 1.5 點/來回;前後半段各看(窮人 OOS)。
用法:python3 foreign_flow_study.py
"""
import os
import json
import math
import urllib.request

import tx_data

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
COST_PTS = 1.5


def fetch_foreign():
    url = f"{FINMIND}?dataset=TaiwanFuturesInstitutionalInvestors&data_id=TX&start_date=2020-01-01"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        rows = json.loads(r.read().decode()).get("data", [])
    out = {}
    for x in rows:
        if x.get("institutional_investors") == "外資":
            out[x["date"]] = (x["long_open_interest_balance_volume"]
                              - x["short_open_interest_balance_volume"])
    return out


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0), n


def run(bars, net_oi, dates, label, conviction=None):
    """T 日 Δ淨OI 為訊號 → T+1 開→收 損益(點,含成本)。conviction=只做 |Δ| 高於分位。"""
    deltas = {}
    prev = None
    for d in dates:
        if d in net_oi:
            if prev is not None:
                deltas[d] = net_oi[d] - prev
            prev = net_oi[d]
    idx = {b["date"]: i for i, b in enumerate(bars)}
    sig_days = [d for d in deltas if d in idx and idx[d] + 1 < len(bars)]
    thr = 0
    if conviction:
        mags = sorted(abs(deltas[d]) for d in sig_days)
        thr = mags[int(len(mags) * conviction)]
    pnls = []
    for d in sig_days:
        dl = deltas[d]
        if dl == 0 or abs(dl) < thr:
            continue
        b1 = bars[idx[d] + 1]
        side = 1 if dl > 0 else -1
        pnls.append(side * (b1["close"] - b1["open"]) - COST_PTS)
    s = mstats(pnls)
    if not s:
        print(f"  {label:<28} 樣本不足")
        return None
    m, sd, t, n = s
    wr = sum(1 for x in pnls if x > 0) / n
    print(f"  {label:<28} n={n:>4}  均 {m:+7.1f} 點  勝率 {wr:.0%}  t={t:+.2f}  總 {sum(pnls)*200:+,.0f} 元/口")
    return t


def main():
    bars = tx_data.load("2020-01-01")
    net_oi = fetch_foreign()
    dates = [b["date"] for b in bars]
    print(f"外資 TX 淨未平倉資料 {len(net_oi)} 天;TX 日線 {len(bars)} 根\n")
    print("【跟隨外資 Δ淨OI(T訊號→T+1開到收,含成本1.5點)】")
    half = len(bars) // 2
    t_full = run(bars, net_oi, dates, "全期間 2020-2026")
    run(bars[:half], net_oi, dates[:half], "前半段")
    run(bars[half:], net_oi, dates[half:], "後半段")
    t_conv = run(bars, net_oi, dates, "高信念版(|Δ|>70分位)", conviction=0.7)
    print("\n判定:", end="")
    ts = [t for t in (t_full, t_conv) if t is not None]
    if ts and max(abs(t) for t in ts) > 2:
        print("有訊號,值得進三關(WF/lockbox/DSR)正式驗。")
    else:
        print("無顯著訊號(|t|<2)——外資部位跟隨太有名,日級 edge 大概率已被吃掉。")


if __name__ == "__main__":
    main()
