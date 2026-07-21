import urllib.request, urllib.parse, time, os, json, datetime as dt

OUT = os.path.dirname(os.path.abspath(__file__))

def fetch_taifex():
    path = os.path.join(OUT, "tx_all.csv")
    rows = []
    start = dt.date(2017, 5, 15)
    end = dt.date(2026, 7, 21)
    cur = start
    n_req = 0
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=29), end)
        data = urllib.parse.urlencode({
            "down_type": "1", "commodity_id": "TX",
            "queryStartDate": cur.strftime("%Y/%m/%d"),
            "queryEndDate": chunk_end.strftime("%Y/%m/%d"),
        }).encode()
        req = urllib.request.Request(
            "https://www.taifex.com.tw/cht/3/futDataDown", data=data,
            headers={"User-Agent": "Mozilla/5.0"})
        for attempt in range(3):
            try:
                raw = urllib.request.urlopen(req, timeout=30).read()
                break
            except Exception as e:
                if attempt == 2: raise
                time.sleep(3)
        text = raw.decode("big5", errors="replace")
        lines = text.strip().splitlines()
        if len(lines) > 1:
            rows.extend(lines[1:])
        n_req += 1
        if n_req % 10 == 0:
            print(f"taifex {cur} ({len(rows)} rows)", flush=True)
        cur = chunk_end + dt.timedelta(days=1)
        time.sleep(0.6)
    header = "交易日期,契約,到期月份,開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量"
    with open(path, "w") as f:
        f.write(header + "\n" + "\n".join(rows))
    print(f"taifex done: {len(rows)} rows -> {path}", flush=True)

def fetch_yahoo(sym, name):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           f"?period1=1451606400&period2={int(time.time())}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    out = []
    q = d["indicators"]["quote"][0]
    for t, c in zip(d["timestamp"], q["close"]):
        if c is not None:
            out.append({"date": dt.datetime.fromtimestamp(t).date().isoformat(), "close": c})
    with open(os.path.join(OUT, f"{name}.json"), "w") as f:
        json.dump(out, f)
    print(f"{sym}: {len(out)} days ({out[0]['date']} ~ {out[-1]['date']})", flush=True)
    time.sleep(1)

fetch_yahoo("^TWII", "twii")
fetch_yahoo("^KS11", "kospi")
fetch_yahoo("^SOX", "sox")
fetch_taifex()
