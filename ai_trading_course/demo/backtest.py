"""階段 5：回測。向量化算出策略的每日報酬（已扣換手成本）。"""
import numpy as np
import pandas as pd
import config


def run_backtest(df: pd.DataFrame, signal: pd.Series) -> pd.Series:
    """回傳策略每日報酬序列。進出場那天扣一次來回成本。"""
    ret = df["close"].pct_change().fillna(0)
    strat_ret = signal * ret
    # 換手：訊號改變的那天，扣手續費+稅+滑價
    turn = signal.diff().abs().fillna(0)
    cost = turn * (config.FEE + config.SLIPPAGE) + (signal.diff() < 0).astype(int) * config.TAX
    return strat_ret - cost


def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change().fillna(0)


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1 + returns).cumprod()
