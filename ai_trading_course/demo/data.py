"""階段 1-2：資料擷取 + 清洗。FinMind 抓台股日線，本地快取，避免重複打 API。"""
import pathlib
import pandas as pd
import requests

CACHE = pathlib.Path(__file__).resolve().parent / "cache"
CACHE.mkdir(exist_ok=True)
API = "https://api.finmindtrade.com/api/v4/data"


def get_prices(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """回傳 index=date、含 open/high/low/close/volume 的乾淨 DataFrame。"""
    f = CACHE / f"{stock_id}_{start}_{end}.csv"
    if f.exists():
        df = pd.read_csv(f, parse_dates=["date"])
    else:
        r = requests.get(API, params={
            "dataset": "TaiwanStockPrice", "data_id": stock_id,
            "start_date": start, "end_date": end}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            raise RuntimeError(f"{stock_id} 無資料")
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df.to_csv(f, index=False)

    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df = df.dropna().sort_values("date").set_index("date")
    # 清洗：濾掉成交量 0（停牌）與異常價
    df = df[(df["volume"] > 0) & (df["close"] > 0)]
    return df
