"""Crypto 資金費率套利(funding carry)誠實驗證——不同種類的 edge(與漲跌無關)。
機制:永續合約多頭付空頭資金費(每8h)。做 現貨多 + 永續空(delta 中性)→ 收 funding。
真實 Binance funding rate 歷史(公開,無金鑰)。誠實扣成本:建/平倉現貨+永續來回 taker。
關鍵誠實問題:①平均 funding 年化多少 ②多常轉負(空頭反付多頭) ③扣成本後淨carry
用法:python3 crypto_funding_carry.py
"""
import json, os, time, gzip, urllib.request

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".funding")
HOSTS = ["https://fapi.binance.com"]


def _get(path):
    last = None
    for h in HOSTS:
        try:
            req = urllib.request.Request(h + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
    raise last


def fetch_funding(symbol, days=730):
    os.makedirs(DIR, exist_ok=True)
    fp = os.path.join(DIR, f"{symbol}.json.gz")
    if os.path.exists(fp):
        with gzip.open(fp, "rt") as f:
            return json.load(f)
    end = int(time.time() * 1000)
    start = end - days * 86400 * 1000
    out, cur = [], start
    while cur < end:
        batch = _get(f"/fapi/v1/fundingRate?symbol={symbol}&startTime={cur}&limit=1000")
        if not batch:
            break
        out += batch
        nxt = batch[-1]["fundingTime"] + 1
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.2)
    rows = [{"t": b["fundingTime"], "rate": float(b["fundingRate"])} for b in out]
    with gzip.open(fp, "wt") as f:
        json.dump(rows, f)
    return rows


def analyze(symbol):
    rows = fetch_funding(symbol)
    if not rows:
        print(f"{symbol}: 無 funding 資料"); return
    rates = [r["rate"] for r in rows]
    n = len(rates)
    avg = sum(rates) / n
    periods_per_year = 3 * 365            # 每8h一次
    ann = avg * periods_per_year
    pos = sum(1 for x in rates if x > 0) / n
    neg_ann = min(rates) * periods_per_year
    import statistics as st
    sd_ann = st.pstdev(rates) * (periods_per_year ** 0.5)
    # 現金套利淨carry:年化funding - 成本(建+平各一次現貨+永續taker~0.04%×4腿≈0.16%,一次性)
    # 這裡看「持有一年」的淨:funding年化 - 0.16%(一次性成本攤一年)
    cost_once = 0.0016
    net_ann = ann - cost_once
    print(f"{symbol}: {n} 期(每8h) ≈ {n/3/365:.1f} 年")
    print(f"  平均 funding/期 = {avg*100:+.4f}%  → 年化毛 carry {ann*100:+.1f}%")
    print(f"  funding 為正比例 = {pos:.0%}(空頭收錢的比例)")
    print(f"  最負單期年化 = {neg_ann*100:+.0f}%(轉負時多頭反收,做空carry會賠)")
    print(f"  年化波動 = {sd_ann*100:.1f}%  → carry夏普 ≈ {ann/sd_ann:.2f}" if sd_ann else "")
    print(f"  ⭐淨carry(扣一次性成本0.16%)≈ {net_ann*100:+.1f}%/年")
    print()
    return dict(symbol=symbol, ann=ann, pos=pos, net=net_ann, sharpe=(ann/sd_ann if sd_ann else 0))


def main():
    print("資金費率套利(現貨多+永續空,收funding)——與漲跌無關的carry edge\n")
    res = [analyze(s) for s in ("BTCUSDT", "ETHUSDT")]
    res = [r for r in res if r]
    print("判定(誠實):")
    for r in res:
        v = "🟢 正carry可收" if r["net"] > 0.03 else "🟡 carry薄" if r["net"] > 0 else "🔴 carry負"
        print(f"  {r['symbol']}: 淨{r['net']*100:+.1f}%/年 carry夏普{r['sharpe']:.2f} {v}")
    print("\n⚠️ 真實限制:①要同時持現貨+永續(資金翻倍佔用)②轉負時要能反手或退出")
    print("   ③交易所風險/清算風險 ④此為無槓桿carry,3-5x槓桿放大(但清算風險同步放大)")


if __name__ == "__main__":
    main()
