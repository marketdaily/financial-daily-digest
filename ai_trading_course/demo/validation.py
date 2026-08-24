"""階段 5 的靈魂：驗證數學。Sharpe / Deflated Sharpe / walk-forward。

這是全 demo 最重要的檔。它的工作是「殺掉」看起來漂亮、實際是運氣的策略。
"""
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis
import config
from strategy import ma_cross_signal
from backtest import run_backtest

ANN = 252  # 一年交易日


def sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.std() == 0 or len(r) < 2:
        return 0.0
    return np.sqrt(ANN) * r.mean() / r.std()


def cagr(returns: pd.Series) -> float:
    eq = (1 + returns).prod()
    yrs = len(returns) / ANN
    return eq ** (1 / yrs) - 1 if yrs > 0 and eq > 0 else -1.0


def max_drawdown(returns: pd.Series) -> float:
    eq = (1 + returns).cumprod()
    return (eq / eq.cummax() - 1).min()


def deflated_sharpe(returns: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014)。

    依「你試了 n_trials 次」把觀察到的 Sharpe 打折，回傳「這個 Sharpe>0 為真」的機率。
    試的次數越多 → 期望最大 Sharpe 越高 → 同樣的 SR 越不顯著。
    """
    r = returns.dropna()
    T = len(r)
    if T < 10:
        return 0.0
    sr = sharpe(r) / np.sqrt(ANN)            # 轉回「每期」Sharpe
    sk = float(skew(r))
    kt = float(kurtosis(r, fisher=False))    # 非超額峰度

    # 多重檢定下，期望的「最大 Sharpe」基準（n_trials 次抽樣的極值）
    # n_trials<3 時極值公式無定義 → 退化成 PSR（只測 SR>0，基準=0）
    if n_trials < 3:
        sr0 = 0.0
    else:
        e = 0.5772156649
        z1 = norm.ppf(1 - 1.0 / n_trials)
        z2 = norm.ppf(1 - 1.0 / (n_trials * np.e))
        sr0 = ((1 - e) * z1 + e * z2) / np.sqrt(T)  # 期望最大 SR（純運氣基準）

    denom = np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr ** 2)
    if denom == 0:
        return 0.0
    dsr = norm.cdf((sr - sr0) * np.sqrt(T - 1) / denom)
    return float(dsr)


def metrics(returns: pd.Series, n_trials: int = 1) -> dict:
    return {
        "CAGR": round(cagr(returns), 4),
        "Sharpe": round(sharpe(returns), 3),
        "MaxDD": round(max_drawdown(returns), 4),
        "DSR": round(deflated_sharpe(returns, n_trials), 3),
        "days": len(returns),
    }


def walk_forward(df, fast, slow):
    """滾動：訓練 N 年（這裡參數固定故訓練段只是隔離）→ 測下一年，串接樣本外報酬。"""
    oos = []
    years = sorted(df.index.year.unique())
    for i in range(config.TRAIN_YEARS, len(years)):
        test_yr = years[i]
        test = df[df.index.year == test_yr]
        if len(test) < 30:
            continue
        sig = ma_cross_signal(df, fast, slow).reindex(test.index)
        oos.append(run_backtest(test, sig))
    return pd.concat(oos) if oos else pd.Series(dtype=float)
