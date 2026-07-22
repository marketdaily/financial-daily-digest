import csv, json, os, datetime as dt
from collections import defaultdict

OUT = os.path.dirname(os.path.abspath(__file__))

def load_series(name):
    with open(os.path.join(OUT, f"{name}.json")) as f:
        arr = json.load(f)
    dates = [dt.date.fromisoformat(a["date"]) for a in arr]
    closes = [a["close"] for a in arr]
    rets = {}
    for i in range(1, len(dates)):
        rets[dates[i]] = (closes[i] / closes[i-1] - 1) * 100
    return dates, dict(zip(dates, closes)), rets

twii_dates, twii_close, twii_ret = load_series("twii")
kospi_dates, _, kospi_ret = load_series("kospi")
sox_dates, _, sox_ret = load_series("sox")

def last_before(dates, d):
    prev = None
    for x in dates:
        if x < d: prev = x
        else: break
    return prev

# --- TAIFEX TX: per (date, session, month) -> (close, volume) ---
tx = defaultdict(dict)
with open(os.path.join(OUT, "tx_all.csv")) as f:
    rdr = csv.reader(f)
    header = next(rdr)
    for row in rdr:
        if len(row) < 18: continue
        try:
            d = dt.datetime.strptime(row[0].strip(), "%Y/%m/%d").date()
        except ValueError:
            continue
        month = row[2].strip()
        if not (len(month) == 6 and month.isdigit()): continue
        sess = row[17].strip()
        try:
            close = float(row[6])
            vol = int(row[9] or 0)
        except ValueError:
            continue
        key = (d, sess)
        tx[key][month] = (close, vol)

general_dates = sorted({d for (d, s) in tx if s == "一般"})

def night_return(d):
    """夜盤報酬:D 的盤後收盤 vs 前一一般時段同月合約收盤。夜盤=前日15:00~D日05:00。"""
    night = tx.get((d, "盤後"))
    if not night: return None
    prev_g = None
    for x in general_dates:
        if x < d: prev_g = x
        else: break
    if prev_g is None: return None
    prev = tx.get((prev_g, "一般"))
    if not prev: return None
    month = max(night, key=lambda m: night[m][1])
    if month not in prev: return None
    nc, pv = night[month][0], prev[month][0]
    if nc <= 0 or pv <= 0: return None
    return (nc / pv - 1) * 100

# --- 觸發日建構(與 analyzer._crash_gate 同義:昨收訊號,無前視) ---
CRASH_SOX, CRASH_KOSPI = -3.0, -4.0
rows = []
for d in twii_dates:
    if d < dt.date(2017, 5, 16) or d not in twii_ret: continue
    kd = last_before(kospi_dates, d)
    sd = last_before(sox_dates, d)
    k = kospi_ret.get(kd) if kd else None
    s = sox_ret.get(sd) if sd else None
    trig_parts = []
    if s is not None and s <= CRASH_SOX: trig_parts.append(f"SOX{s:+.1f}")
    if k is not None and k <= CRASH_KOSPI: trig_parts.append(f"KOSPI{k:+.1f}")
    if not trig_parts: continue
    nr = night_return(d)
    rows.append({"date": d, "parts": trig_parts, "night": nr, "twii": twii_ret[d]})

def stats(sub, label):
    n = len(sub)
    if n == 0:
        print(f"{label:34s} n=0"); return
    rets = [r["twii"] for r in sub]
    mean = sum(rets) / n
    tail3 = sum(1 for r in rets if r <= -3) / n * 100
    neg = sum(1 for r in rets if r < 0) / n * 100
    worst = min(rets)
    print(f"{label:34s} n={n:3d}  mean={mean:+.2f}%  P(<=-3%)={tail3:4.1f}%  P(<0)={neg:4.1f}%  worst={worst:+.2f}%")

trig = [r for r in rows if r["night"] is not None]
print(f"觸發日總數 {len(rows)},有夜盤資料 {len(trig)}(缺 {len(rows)-len(trig)})\n")
stats(rows, "全部觸發日(=現行閘門)")
stats(trig, "觸發日(有夜盤)")
print()
stats([r for r in trig if r["night"] < 0], "夜盤 < 0(維持硬閘)")
stats([r for r in trig if r["night"] >= 0], "夜盤 >= 0(主檢定:軟化候選)")
stats([r for r in trig if r["night"] >= 0.5], "夜盤 >= +0.5(穩健性)")
stats([r for r in trig if 0 <= r["night"] < 0.5], "夜盤 0~+0.5(邊界帶)")
print()
# 年代穩定性
for lo, hi, tag in [(2017, 2020, "2017-2020"), (2021, 2023, "2021-2023"), (2024, 2026, "2024-2026")]:
    sub = [r for r in trig if lo <= r["date"].year <= hi]
    stats([r for r in sub if r["night"] >= 0], f"{tag} 夜盤>=0")
    stats([r for r in sub if r["night"] < 0], f"{tag} 夜盤<0")
print()
# 全樣本基礎率
all_rets = [twii_ret[d] for d in twii_dates if d in twii_ret and d >= dt.date(2017, 5, 16)]
base_tail = sum(1 for r in all_rets if r <= -3) / len(all_rets) * 100
print(f"基礎率:全部 {len(all_rets)} 交易日 P(<=-3%)={base_tail:.2f}%  mean={sum(all_rets)/len(all_rets):+.3f}%")
print()
print("=== 夜盤>=0 的觸發日明細 ===")
for r in trig:
    if r["night"] >= 0:
        print(f"{r['date']}  {'/'.join(r['parts']):22s} night={r['night']:+.2f}%  TWII當日={r['twii']:+.2f}%")
print()
print("=== 近期關鍵日 sanity check ===")
for r in rows:
    if r["date"] >= dt.date(2026, 7, 15) or r["date"] in (dt.date(2024, 8, 5), dt.date(2025, 4, 7), dt.date(2025, 1, 28)):
        print(f"{r['date']}  {'/'.join(r['parts']):22s} night={r['night'] if r['night'] is None else round(r['night'],2)}  TWII當日={r['twii']:+.2f}%")
