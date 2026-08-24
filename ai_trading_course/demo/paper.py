"""階段 7：紙上交易（模擬下單）。用最新一根 K 棒的訊號，產出「今天該怎麼下單」的指令。

這不是真下單——是把策略決策 + 風控大小，變成一張人看得懂的 paper 指令單。
真要接券商 API（ccxt / Shioaji）就是把這張單送出去，但永遠先 paper 跑一陣子。
"""
import config
from strategy import ma_cross_signal, atr
from risk import position_size


def todays_order(df, fast=config.FAST, slow=config.SLOW) -> dict:
    sig = ma_cross_signal(df, fast, slow)
    last_close = float(df["close"].iloc[-1])
    last_atr = float(atr(df).iloc[-1])
    holding = int(sig.iloc[-1])
    prev = int(sig.iloc[-2]) if len(sig) > 1 else 0

    if holding == 1 and prev == 0:
        action = "BUY 進場"
        stop = last_close - config.STOP_ATR_MULT * last_atr
        size = position_size(last_close, stop)
    elif holding == 0 and prev == 1:
        action = "SELL 出場"
        size = {"note": "平倉全部部位"}
    elif holding == 1:
        action = "HOLD 續抱"
        stop = last_close - config.STOP_ATR_MULT * last_atr
        size = position_size(last_close, stop)
    else:
        action = "FLAT 空手觀望"
        size = {}
    return {"action": action, "close": round(last_close, 2), "atr": round(last_atr, 2), **size}
