"""fill-realism 確定性 linter(2026-07-27 魚E 幻想成交事故 → 出事1次=當場建偵測器)。

不變量:停損出場不得記獲利。停損必須放在進場價的虧損側;成交價不得優於停損方向。
魚E 事故:進場用收盤穿越 OR 邊緣、停損固定邊緣±30,突破棒過衝≥30 時停損落在獲利側,
回測把停損記成保證獲利(34/124 筆貢獻了總 edge 的 94%)。此 linter 永久擋這類 bug。

用法:
  python3 fill_lint.py            # 掃 .paper/ledger.jsonl + .paper/backtest.json,違規 exit 1
  from fill_lint import lint_trades  # 回測產生器內嵌(違規=不出貨)
例外:trailing stop 類策略可合法獲利停損——該策略需在 record 標 trailing=True 才放行。
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))


def lint_trades(records):
    """records=[{...}] 需含 reason;損益取 pnl_pts/pnl/或 side*(exit-entry)。
    回傳違規列表(空=乾淨)。只檢查 reason=='stop' 且未標 trailing 的紀錄。"""
    bad = []
    for r in records:
        if r.get("reason") != "stop" or r.get("trailing"):
            continue
        pnl = r.get("pnl_pts", r.get("pnl"))
        if pnl is None and all(k in r for k in ("side", "entry", "exit")):
            pnl = r["side"] * (r["exit"] - r["entry"])
        if pnl is not None and pnl > 0:
            bad.append(r)
    return bad


def main():
    pdir = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else os.path.join(HERE, ".paper")
    n_bad = 0
    led = os.path.join(pdir, "ledger.jsonl")
    if os.path.exists(led):
        evs = [json.loads(l) for l in open(led, encoding="utf-8")]
        bad = lint_trades(evs)
        n_bad += len(bad)
        print(f"ledger.jsonl:{len(evs)} 事件,停損記獲利違規 {len(bad)} 筆")
        for b in bad:
            print(f"  🚨 {b.get('date')} 魚{b.get('fish')} pnl={b.get('pnl_pts', b.get('pnl'))}")
    bt = os.path.join(pdir, "backtest.json")
    if os.path.exists(bt):
        trades = json.load(open(bt, encoding="utf-8")).get("trades", [])
        bad = lint_trades(trades)
        n_bad += len(bad)
        print(f"backtest.json:近 {len(trades)} 筆,違規 {len(bad)} 筆")
        for b in bad:
            print(f"  🚨 {b.get('date')} 魚{b.get('fish')} pnl={b.get('pnl')}")
    print("✅ fill-realism 乾淨" if n_bad == 0 else f"❌ 共 {n_bad} 筆幻想成交嫌疑")
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
