"""馬克羊#2 指數調整日事件研究(index-level 第一關)。

假說:MSCI 季審/台灣50 定審生效日,被動資金被迫在收盤時點交易 → 生效日異常
波動/量,且壓力方向次日部分回歸(fade 可吃)。
日曆(公開規則,不用爬):
- MSCI 季審生效 = 2/5/8/11 月最後交易日收盤(5/11 為半年審,流量更大,分開看)
- 台灣50(FTSE)定審生效 = 3/6/9/12 月第三個週五收盤後(取 ≤ 該日的最後交易日)
體檢:0050 生效日成交量 / 20日均量——日期算對,量必然爆;量不爆=日曆錯,結論作廢。
交易測試(方向不可知的 index-level 版):fade 生效日盤中方向,持有到次日收盤。
用法:python3 rebalance_study.py
"""
import math
import json
import datetime
import urllib.request
import os

import tx_data

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
TX_POINT = 200


def last_trading_on_or_before(target, trading_days):
    ds = target.isoformat()
    prior = [d for d in trading_days if d <= ds]
    return prior[-1] if prior else None


def build_events(trading_days):
    events = []
    y0, y1 = int(trading_days[0][:4]), int(trading_days[-1][:4])
    for y in range(y0, y1 + 1):
        for m, kind in [(2, "MSCI季審"), (5, "MSCI半年審"), (8, "MSCI季審"), (11, "MSCI半年審")]:
            nxt = datetime.date(y + (m == 12), (m % 12) + 1, 1)
            last = nxt - datetime.timedelta(days=1)
            d = last_trading_on_or_before(last, trading_days)
            if d:
                events.append((d, kind))
        for m in (3, 6, 9, 12):
            first = datetime.date(y, m, 1)
            fri = first + datetime.timedelta(days=(4 - first.weekday()) % 7 + 14)
            d = last_trading_on_or_before(fri, trading_days)
            if d:
                events.append((d, "台灣50定審"))
    return sorted(set(events))


def etf_volume_ratio(dates_needed):
    """0050 事件日成交量 / 前20日均量(日曆體檢)。抓一次全期間。"""
    url = f"{FINMIND}?dataset=TaiwanStockPrice&data_id=0050&start_date=2020-01-01"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode()).get("data", [])
    except Exception:
        return {}
    vols = [(x["date"], x.get("Trading_Volume") or 0) for x in rows]
    out = {}
    for i, (d, v) in enumerate(vols):
        if d in dates_needed and i >= 20:
            avg = sum(x[1] for x in vols[i - 20:i]) / 20
            if avg > 0:
                out[d] = v / avg
    return out


def mstats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return m, sd, t, n


def main():
    bars = tx_data.load("2020-01-01")
    by_date = {b["date"]: b for b in bars}
    tds = [b["date"] for b in bars]
    nxt = {tds[i]: tds[i + 1] for i in range(len(tds) - 1)}

    events = [(d, k) for d, k in build_events(tds) if d in nxt]
    ev_dates = {d for d, _ in events}
    print(f"事件日曆:{len(events)} 個(TX 資料 {tds[0]} → {tds[-1]})")

    vr = etf_volume_ratio(ev_dates)
    if vr:
        mean_vr = sum(vr.values()) / len(vr)
        spike = sum(1 for v in vr.values() if v > 1.5) / len(vr)
        print(f"日曆體檢:0050 事件日量/20日均量 平均 {mean_vr:.1f}x,>1.5x 佔 {spike:.0%}"
              f"(量不爆=日曆錯,以下作廢)\n")

    base_rng = [abs(b["close"] - b["open"]) / b["open"] for b in bars]
    base_gap = []
    for i in range(len(bars) - 1):
        base_gap.append((bars[i + 1]["open"] - bars[i]["close"]) / bars[i]["close"])

    groups = {}
    for d, k in events:
        groups.setdefault(k, []).append(d)
    groups["全部事件"] = [d for d, _ in events]

    print(f"{'組別':<12}{'n':>4}{'事件日振幅':>10}{'常日振幅':>10}{'次日gap均':>10}{'fade損益(點)':>14}{'t':>7}")
    print("-" * 68)
    fade_all = {}
    for k, ds in groups.items():
        rng = [abs(by_date[d]["close"] - by_date[d]["open"]) / by_date[d]["open"] for d in ds]
        gaps, fades = [], []
        for d in ds:
            b0, b1 = by_date[d], by_date[nxt[d]]
            gaps.append((b1["open"] - b0["close"]) / b0["close"])
            side = -1 if b0["close"] > b0["open"] else 1     # fade 事件日盤中方向
            fades.append(side * (b1["close"] - b0["close"]))
        s = mstats(fades)
        if not s:
            continue
        m, sd, t, n = s
        fade_all[k] = fades
        print(f"{k:<12}{n:>4}{sum(rng)/len(rng):>10.2%}{sum(base_rng)/len(base_rng):>10.2%}"
              f"{sum(gaps)/len(gaps):>+10.3%}{m:>+11.1f} 點{t:>+7.2f}")

    print("\n口徑:fade=收盤反向進場持有至次日收盤,未扣成本(TX 來回約1-2點,自行心扣);")
    print("     方向用「當日開收盤」代理盤中壓力方向(index-level 粗版,無納入/剔除名單)。")
    fades = fade_all.get("全部事件", [])
    s = mstats(fades)
    if s:
        m, sd, t, n = s
        wr = sum(1 for x in fades if x > 0) / n
        print(f"\n判定:全部事件 fade n={n},均值 {m:+.1f} 點/次,勝率 {wr:.0%},t={t:+.2f} → "
              f"{'值得進下一關(個股層+WF)' if abs(t) > 1.5 and m > 10 else '此粗版無足夠訊號,edge 若存在應在個股納入/剔除層,需名單資料'}")


if __name__ == "__main__":
    main()
