#!/usr/bin/env python3
"""buy 選股 alpha v2:新一批【預先登記】特徵 cut(Delvin 2026-07-22「看多勝率想怎麼變高」親令)。

繼承 2026-07-13_buy_setup_conditional_edge.py 的全部方法鐵則(非重複發明):
載入該模組直接複用 load/features/universe/eval 積木。本檔只新增預登記 cut:
  乖離帶(ext20)、5 日動能(ret5)、夜盤 SPX × 回檔/結構 交互。
多重檢定 n_trials = 14(原) + 8(新) = 22,兩支腳本同罰(誠實:同一個帳本上總共試過 22 刀)。

跑法: .venv/bin/python research/2026-07-22_buy_selection_alpha_v2.py
輸出: JSON(stdout)+ 摘要(stderr)。純唯讀,不改 analyzer;PASS 才有資格進閘門提案。
"""
import json
import os
import statistics
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "cond_edge", os.path.join(HERE, "2026-07-13_buy_setup_conditional_edge.py"))
ce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ce)

N_TRIALS_TOTAL = 22  # 14 原登記 + 8 本檔新登記


def spx_prev_map(prices):
    """call 日 → 前一晚 SPX 漲跌%(與 analyzer._pp_overnight_autogate 同語義:
    call 日之前最後一個已完成 session 對其前一 session)。^GSPC 不在 price_cache
    (它只存個股)→ 用 docs/data/track-record.json 沒存原始序列,改抓 builder 同源 worker。"""
    import importlib.util as iu
    bspec = iu.spec_from_file_location(
        "btr", os.path.join(os.path.dirname(HERE), "scripts", "build_track_record.py"))
    btr = iu.module_from_spec(bspec)
    bspec.loader.exec_module(btr)
    closes = btr.yahoo_chart("^GSPC", "", "") or {}
    ds = sorted(closes)
    import bisect

    def prev_chg(d):
        i = bisect.bisect_left(ds, d)
        if i < 2:
            return None
        return (closes[ds[i - 1]] / closes[ds[i - 2]] - 1) * 100
    return prev_chg


def add_features_v2(rows, prices):
    for r in rows:
        key = ce.price_key(r["ticker"], r["market"])
        _, closes = ce.series_upto(prices, key, r["date"])
        r["_ret5"] = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None
        m = ce.ma20(closes)
        r["_ext20"] = (closes[-1] / m - 1) * 100 if (m and closes) else None
    return rows


def registered_cuts_v2(prev_chg):
    def num(x):
        return isinstance(x, (int, float))

    def spx_dn(r):
        c = prev_chg(r["date"])
        return c is not None and c < 0

    return [
        # 動能:買弱 vs 追強(與 07-13「買弱勢>買強勢」先驗一致,方向預先聲明)
        ("ret5<=-7% (買急跌)", lambda r: num(r.get("_ret5")) and r["_ret5"] <= -7),
        ("ret5>=+7% (追急漲,預期負)", lambda r: num(r.get("_ret5")) and r["_ret5"] >= 7),
        # 乖離帶
        ("ext20>=+5% (高乖離,預期負)", lambda r: num(r.get("_ext20")) and r["_ext20"] >= 5),
        ("ext20<=-5% (深跌破MA20)", lambda r: num(r.get("_ext20")) and r["_ext20"] <= -5),
        # 夜盤 × 選股 交互(timing 閘已上線;這裡測 selection 疊加)
        ("dip>=10% AND spx_prev<0", lambda r: num(r.get("_pullback")) and r["_pullback"] >= 0.10 and spx_dn(r)),
        ("below_ma20 AND spx_prev<0", lambda r: r.get("_above_ma20") is False and spx_dn(r)),
        # dip 假設的市場切分(07-13 遺留追蹤)
        ("dip>=10% AND tw", lambda r: num(r.get("_pullback")) and r["_pullback"] >= 0.10 and r.get("market") == "tw"),
        ("rsi<35 (放寬超賣)", lambda r: num(r.get("_rsi")) and r["_rsi"] < 35),
    ]


def main():
    rows = ce.load_rows()
    prices = ce.load_prices()
    ce.add_features(rows, prices)
    add_features_v2(rows, prices)
    ce.add_rebuy_bleed(rows, prices)
    base_rate, day_mean = ce.universe_stats(rows)
    buy = [r for r in rows if r.get("verdict_class") == "buy"]
    prev_chg = spx_prev_map(prices)

    results = []
    for name, pred in registered_cuts_v2(prev_chg):
        subset = [r for r in buy if pred(r)]
        results.append(ce.eval_cut(name, subset, base_rate, day_mean, n_trials=N_TRIALS_TOTAL))

    out = {
        "generated": date.today().isoformat(),
        "universe_base_rate_pct": round(base_rate * 100, 2),
        "n_buy": len(buy),
        "n_trials_multiplicity": N_TRIALS_TOTAL,
        "results": results,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print("\n=== v2 新登記 cut 摘要 (PASS = eff_days>=15 且 hit real_edge 且 DSR real_edge) ===", file=sys.stderr)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"  ---- {r['name']:34s} n=0", file=sys.stderr)
            continue
        mark = "✅PASS" if r["PASS"] else "  ----"
        print(f"{mark} {r['name']:34s} n={r['n']:3d} effd={r['eff_days']:5.1f} "
              f"win={r['winrate']:4.1f}%(base {r['base_rate']:.1f}) EV={r['ev_pct']:+.2f}% "
              f"neuEV={r['daily_neu_mean_pct']:+.3f}%/d hit={r['hit_verdict']} dsr={r['dsr_verdict']}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
