import urllib.request, urllib.parse, time, os, json, datetime as dt

OUT = os.path.dirname(os.path.abspath(__file__))
SYMS = {"^TWII": "twii_o", "^KS11": "kospi_o", "^N225": "n225_o", "^HSI": "hsi_o",
        "000001.SS": "sse_o", "^SOX": "sox_o", "^GSPC": "spx_o", "^VIX": "vix_o",
        "^STOXX50E": "stoxx_o"}

for sym, name in SYMS.items():
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           f"?period1=1262304000&period2={int(time.time())}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    out = []
    for t, o, c in zip(d["timestamp"], q["open"], q["close"]):
        if c is not None:
            out.append({"date": dt.datetime.fromtimestamp(t).date().isoformat(),
                        "open": o, "close": c})
    with open(os.path.join(OUT, f"{name}.json"), "w") as f:
        json.dump(out, f)
    print(f"{sym}: {len(out)} days ({out[0]['date']} ~ {out[-1]['date']})", flush=True)
    time.sleep(1.2)
