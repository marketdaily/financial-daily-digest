import csv, json, os, datetime as dt
from collections import defaultdict

OUT = os.path.dirname(os.path.abspath(__file__))

def load(name):
    with open(os.path.join(OUT, f"{name}.json")) as f:
        arr = json.load(f)
    dates, opens, closes = [], {}, {}
    for a in arr:
        d = dt.date.fromisoformat(a["date"])
        dates.append(d); opens[d] = a["open"]; closes[d] = a["close"]
    rets, gaps = {}, {}
    for i in range(1, len(dates)):
        d, p = dates[i], dates[i-1]
        if closes[p]:
            rets[d] = (closes[d] / closes[p] - 1) * 100
            o = opens.get(d)
            if o and o > 0 and abs(o - closes[p]) > 1e-9:
                gaps[d] = (o / closes[p] - 1) * 100
    return dates, rets, gaps, closes

twii_d, twii_r, twii_g, twii_c = load("twii_o")
mkts = {n: load(f"{n}_o") for n in ["kospi", "n225", "hsi", "sse", "sox", "spx", "vix", "stoxx"]}

# 台指期夜盤(2017-05+)
tx = defaultdict(dict)
with open(os.path.join(OUT, "tx_all.csv")) as f:
    rdr = csv.reader(f); next(rdr)
    for row in rdr:
        if len(row) < 18: continue
        try: d = dt.datetime.strptime(row[0].strip(), "%Y/%m/%d").date()
        except ValueError: continue
        m = row[2].strip()
        if not (len(m) == 6 and m.isdigit()): continue
        try: tx[(d, row[17].strip())][m] = (float(row[6]), int(row[9] or 0))
        except ValueError: continue
g_dates = sorted({d for (d, s) in tx if s == "一般"})
def tx_night(d):
    night = tx.get((d, "盤後"))
    if not night: return None
    pg = None
    for x in g_dates:
        if x < d: pg = x
        else: break
    if not pg or (pg, "一般") not in tx: return None
    prev = tx[(pg, "一般")]
    m = max(night, key=lambda k: night[k][1])
    if m not in prev or prev[m][0] <= 0 or night[m][0] <= 0: return None
    return (night[m][0] / prev[m][0] - 1) * 100

def last_before(dates, d):
    prev = None
    for x in dates:
        if x < d: prev = x
        else: break
    return prev

# 特徵表:每個台股交易日
rows = []
for d in twii_d:
    if d < dt.date(2010, 2, 1) or d not in twii_r: continue
    r = {"date": d, "twii": twii_r[d]}
    open_d = None
    # 開盤到收盤(09:00 可行動者的實際承受)
    # twii open 有值才算
    for n in ["kospi", "n225", "hsi", "sse", "sox", "spx", "vix", "stoxx"]:
        dts, rets, gaps, _ = mkts[n]
        pd_ = last_before(dts, d)
        r[f"{n}_prev"] = rets.get(pd_) if pd_ else None
    # 當日開盤 gap(08:00 TW 可得:韓/日)
    for n in ["kospi", "n225"]:
        dts, rets, gaps, _ = mkts[n]
        r[f"{n}_gap"] = gaps.get(d)
    r["tx_night"] = tx_night(d) if d >= dt.date(2017, 5, 16) else None
    rows.append(r)

years = (rows[-1]["date"] - rows[0]["date"]).days / 365.25
base = [r["twii"] for r in rows]
base_tail = sum(1 for x in base if x <= -3) / len(base) * 100

def show(sub, label):
    n = len(sub)
    if n < 5:
        print(f"  {label:42s} n={n:4d}  (樣本太少)"); return
    rets = [r["twii"] for r in sub]
    mean = sum(rets) / n
    tail = sum(1 for x in rets if x <= -3) / n * 100
    neg = sum(1 for x in rets if x < 0) / n * 100
    print(f"  {label:42s} n={n:4d} ({n/years:4.1f}次/年)  mean={mean:+.2f}%  P(<=-3%)={tail:5.1f}%  P(<0)={neg:4.0f}%")

print(f"樣本 {len(rows)} 台股交易日({rows[0]['date']}~{rows[-1]['date']},{years:.1f}年)")
print(f"基礎率:mean={sum(base)/len(base):+.3f}%  P(<=-3%)={base_tail:.2f}%\n")

print("=== ① 單變量領先性(06:20 可得:各市場昨收報酬)===")
for n, zh in [("sox", "費半"), ("spx", "S&P"), ("kospi", "韓KOSPI"), ("n225", "日經"),
              ("hsi", "恒生"), ("sse", "上證"), ("stoxx", "歐Stoxx")]:
    for th in (-2, -3, -4):
        sub = [r for r in rows if r[f"{n}_prev"] is not None and r[f"{n}_prev"] <= th]
        show(sub, f"{zh}昨收 <= {th}%")
    print()

print("=== ② 08:15 可得:開盤 gap(韓/日 08:00 TW 開盤)===")
for n, zh in [("kospi", "韓KOSPI"), ("n225", "日經")]:
    for th in (-1.5, -2, -3):
        sub = [r for r in rows if r[f"{n}_gap"] is not None and r[f"{n}_gap"] <= th]
        show(sub, f"{zh}開盤gap <= {th}%")
    print()

trig = lambda r: ((r["sox_prev"] is not None and r["sox_prev"] <= -3) or
                  (r["kospi_prev"] is not None and r["kospi_prev"] <= -4))

print("=== ③ 增量價值:現行 06:20 閘門沒抓到的,08:15 gap 能補多少 ===")
no_gate = [r for r in rows if not trig(r)]
show(no_gate, "閘門未觸發日(全部)")
for th in (-1.5, -2, -3):
    show([r for r in no_gate if r["kospi_gap"] is not None and r["kospi_gap"] <= th],
         f"閘門未觸發 且 韓gap <= {th}%")
    show([r for r in no_gate if r["n225_gap"] is not None and r["n225_gap"] <= th],
         f"閘門未觸發 且 日gap <= {th}%")
print()

print("=== ④ 反向增量:閘門觸發日,08:15 韓股開盤反彈能不能再軟化 ===")
gated = [r for r in rows if trig(r)]
show(gated, "閘門觸發日(全部)")
show([r for r in gated if r["kospi_gap"] is not None and r["kospi_gap"] >= 0.5], "觸發 且 韓gap >= +0.5%")
show([r for r in gated if r["kospi_gap"] is not None and r["kospi_gap"] <= -2], "觸發 且 韓gap <= -2%(雙確認)")
nt = [r for r in gated if r["tx_night"] is not None]
show([r for r in nt if r["tx_night"] >= 0.5 and r["kospi_gap"] is not None and r["kospi_gap"] >= 0], "觸發 且 夜盤>=+0.5 且 韓gap>=0")
show([r for r in nt if r["tx_night"] >= 0.5 and r["kospi_gap"] is not None and r["kospi_gap"] < 0], "觸發 且 夜盤>=+0.5 但 韓gap<0")
print()

print("=== ⑤ 疊加/獨立性:誰是同一個訊號、誰有獨立資訊 ===")
sox3 = [r for r in rows if r["sox_prev"] is not None and r["sox_prev"] <= -3]
show([r for r in sox3 if r["kospi_prev"] is not None and r["kospi_prev"] <= -4], "費半<=-3 且 韓昨收<=-4(重疊)")
show([r for r in sox3 if r["kospi_prev"] is None or r["kospi_prev"] > -4], "費半<=-3 但 韓昨收>-4")
k4 = [r for r in rows if r["kospi_prev"] is not None and r["kospi_prev"] <= -4]
show([r for r in k4 if r["sox_prev"] is None or r["sox_prev"] > -3], "韓昨收<=-4 但 費半>-3")
h3 = [r for r in rows if r["hsi_prev"] is not None and r["hsi_prev"] <= -3]
show([r for r in h3 if not trig(r)], "恒生昨收<=-3 且 現行閘門未觸發")
n3 = [r for r in rows if r["n225_prev"] is not None and r["n225_prev"] <= -3]
show([r for r in n3 if not trig(r)], "日經昨收<=-3 且 現行閘門未觸發")
s3 = [r for r in rows if r["stoxx_prev"] is not None and r["stoxx_prev"] <= -3]
show([r for r in s3 if not trig(r)], "歐Stoxx昨收<=-3 且 現行閘門未觸發")
print()

print("=== ⑥ 年代穩定性:08:15 韓gap<=-2 候選(含未觸發日增量)===")
for lo, hi in [(2010, 2015), (2016, 2020), (2021, 2026)]:
    sub = [r for r in no_gate if lo <= r["date"].year <= hi
           and r["kospi_gap"] is not None and r["kospi_gap"] <= -2]
    show(sub, f"{lo}-{hi} 未觸發且韓gap<=-2")
print()

print("=== ⑦ 「他們跌≠我們跌」:韓昨收<=-4 觸發日按當日 08:15 資訊分桶 ===")
show([r for r in k4 if r["kospi_gap"] is not None and r["kospi_gap"] <= -1], "韓昨收<=-4 且今晨韓再低開<=-1(恐慌延續)")
show([r for r in k4 if r["kospi_gap"] is not None and r["kospi_gap"] >= 0], "韓昨收<=-4 但今晨韓平高開(恐慌止血)")
