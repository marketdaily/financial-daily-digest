"""階段 3-4：特徵 + 訊號。簡單 MA 交叉。回傳 0/1 持倉訊號（1=持有多單）。

關鍵防呆：訊號用 shift(1)，代表「昨天收盤算出的訊號、今天才進場」，
避免 look-ahead（用到當天還沒發生的收盤價）。
"""
import pandas as pd


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ma_cross_signal(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    """快線 > 慢線 → 持有(1)，否則空手(0)。shift(1) 防未來函數。"""
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    raw = (f > s).astype(int)
    return raw.shift(1).fillna(0)
