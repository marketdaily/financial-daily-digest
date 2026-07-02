"""抓 CB 發行公司歷史日線(2018 起)供回測:未調整(複製生產端 vol)+ 還原權值(算實際觸及)。"""
import os, json, time, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
START = "2018-01-01"


def fetch(dataset, code):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={START}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("data", [])


def main():
    db = json.load(open(os.path.join(HERE, "..", "cb_database.json")))
    codes = sorted({it.get("stock_code") for it in db["items"] if it.get("stock_code")})
    codes.append("TAIEX")
    done, fail = 0, []
    for code in codes:
        for dataset, suffix in (("TaiwanStockPrice", ""), ("TaiwanStockPriceAdj", "_adj")):
            if code == "TAIEX" and suffix == "_adj":
                continue
            path = os.path.join(DATA, f"{code}{suffix}.json")
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                continue
            for attempt in range(3):
                try:
                    rows = fetch(dataset, code)
                    if rows:
                        json.dump(rows, open(path, "w"))
                        done += 1
                        print(f"{code}{suffix}: {len(rows)} rows", flush=True)
                    else:
                        fail.append(f"{code}{suffix}:empty")
                    break
                except Exception as e:
                    if attempt == 2:
                        fail.append(f"{code}{suffix}:{e}")
                    time.sleep(5 * (attempt + 1))
            time.sleep(0.8)
    print(f"DONE fetched={done} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
