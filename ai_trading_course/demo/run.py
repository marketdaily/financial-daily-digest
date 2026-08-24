"""閉環主程式：資料 → 訊號 → 回測 → 驗證 → 風控 → paper 指令 → 誠實結論。

跑法：  python3 run.py
這支會對 UNIVERSE 每檔股票跑完整流程，並示範「多重檢定如何膨脹假 Sharpe」。
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import config
from data import get_prices
from strategy import ma_cross_signal
from backtest import run_backtest, buy_and_hold
from validation import metrics, walk_forward, sharpe
from paper import todays_order

LINE = "=" * 64


def analyse(stock_id):
    df = get_prices(stock_id, config.START, config.END)
    print(f"\n{LINE}\n  {stock_id}  （{df.index[0].date()} ~ {df.index[-1].date()}，{len(df)} 天）\n{LINE}")

    # --- 1) 全期回測 vs Buy&Hold（先打敗最笨基準）---
    sig = ma_cross_signal(df, config.FAST, config.SLOW)
    strat = run_backtest(df, sig)
    bh = buy_and_hold(df)
    print(f"  策略   MA{config.FAST}/{config.SLOW}（全期、單一參數）：{metrics(strat, n_trials=1)}")
    print(f"  基準   Buy & Hold              ：{metrics(bh, n_trials=1)}")

    # --- 2) 多重檢定示範：掃 48 組參數，挑最好的那組 ---
    best_sr, best_p, results = -9, None, []
    for f in config.SCAN_FAST:
        for s in config.SCAN_SLOW:
            if f >= s:
                continue
            r = run_backtest(df, ma_cross_signal(df, f, s))
            sr = sharpe(r)
            results.append(sr)
            if sr > best_sr:
                best_sr, best_p, best_ret = sr, (f, s), r
    n_trials = len(results)
    print(f"\n  ⚠ 掃了 {n_trials} 組參數，挑出最好的 MA{best_p[0]}/{best_p[1]}：")
    print(f"      天真看：Sharpe {best_sr:.3f}  →  看起來很神")
    print(f"      誠實看：{metrics(best_ret, n_trials=n_trials)}  ← DSR 把「試了{n_trials}次」打折後的真相")

    # --- 3) walk-forward 樣本外（真正算數的數字）---
    wf = walk_forward(df, config.FAST, config.SLOW)
    print(f"\n  樣本外 walk-forward（只算沒看過的年份）：{metrics(wf, n_trials=1)}")

    # --- 4) 今天的 paper 指令（風控大小已算好）---
    print(f"\n  今日 paper 指令：{todays_order(df)}")


def main():
    print("AI 交易工程 · 最小可動閉環 demo")
    print("資料源 FinMind｜策略 MA 交叉｜驗證 walk-forward + Deflated Sharpe｜風控 1% 風險式 sizing｜paper 模擬")
    for sid in config.UNIVERSE:
        try:
            analyse(sid)
        except Exception as e:
            print(f"  {sid} 失敗：{e}")
    print(f"\n{LINE}")
    print("  誠實結論：簡單 MA 交叉在台股大型股『單一參數』常輸 Buy&Hold；")
    print("  掃參數挑最好那組的高 Sharpe，被 DSR 一打折多半現形（=過擬合/運氣）。")
    print("  這正是這個 demo 要教的事：edge 要先過驗證篩子，不是看回測漂不漂亮。")
    print(LINE)


if __name__ == "__main__":
    main()
