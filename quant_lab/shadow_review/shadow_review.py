"""Shadow Review — 券商/bot 成交紀錄行為覆盤(概念源自 HKUDS/Vibe-Trading Shadow Account)。

吃成交紀錄 → FIFO 配對成回合交易 → 行為畫像:勝率/賠率/期望值、處置效應
(輸單抱比贏單久)、報復性加碼、過度交易、手續費侵蝕。輸出 report.md + stats.json。

用法:
  python3 shadow_review.py <fills檔> [--fmt generic|bot_jsonl|tw_paper] [--out 目錄]

輸入格式:
  generic   CSV,欄位: date,symbol,side(BUY/SELL),qty,price,fee  (券商匯出先轉成這六欄)
  bot_jsonl 本倉 bot fills(action OPEN/CLOSE + side long/short + mark/exit_mark/fees)
  tw_paper  tw_paper_fills.jsonl(BUY/SELL + shares/price/fee,SELL 帶 pnl/hold_days)

統計誠實原則:樣本數 n 一律標示;n<20 的結論標「樣本不足,僅供參考」;不足以下
檢定的不硬給 p 值。
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime


def _parse_ts(s):
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    raise ValueError(f"無法解析時間: {s}")


def load_bot_jsonl(path):
    """OPEN/CLOSE 配對(bot 紀錄同 symbol 依序開平)。回合 = dict 清單。"""
    opens = defaultdict(list)
    trades = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            act = (r.get("action") or "").upper()
            sym = r.get("symbol") or "?"
            if act == "OPEN":
                opens[sym].append(r)
            elif act == "CLOSE" and opens[sym]:
                o = opens[sym].pop(0)
                t_in, t_out = _parse_ts(o["ts"]), _parse_ts(r["ts"])
                entry = o.get("mark") or o.get("entry_px") or o.get("btc_price")
                exit_ = r.get("exit_mark") or r.get("exit_px") or r.get("btc_price")
                fees = (o.get("fees") or o.get("fee") or 0) + (r.get("fees") or r.get("fee") or 0)
                pnl = r.get("hl_pnl")
                if pnl is None:
                    pnl = r.get("pnl")
                qty = o.get("qty") or o.get("size") or 0
                if pnl is None and entry and exit_ and qty:
                    sign = -1 if (o.get("side") == "short") else 1
                    pnl = (float(exit_) - float(entry)) * float(qty) * sign
                if pnl is None:
                    continue
                notional = float(entry) * float(qty) if entry and qty else None
                trades.append({
                    "symbol": sym, "side": o.get("side") or "long",
                    "entry_ts": t_in, "exit_ts": t_out,
                    "hold_days": (t_out - t_in).total_seconds() / 86400,
                    "pnl": float(pnl) - float(fees), "gross_pnl": float(pnl),
                    "fees": float(fees), "notional": notional,
                })
    return trades


def load_tw_paper(path):
    trades = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if (r.get("side") or "").upper() != "SELL" or r.get("pnl") is None:
                continue
            t_out = _parse_ts(r["date"])
            hold = float(r.get("hold_days") or 0)
            trades.append({
                "symbol": r.get("symbol", "?"), "side": "long",
                "entry_ts": None, "exit_ts": t_out, "hold_days": hold,
                "pnl": float(r["pnl"]), "gross_pnl": float(r["pnl"]) + float(r.get("fee") or 0),
                "fees": float(r.get("fee") or 0),
                "notional": float(r.get("shares") or 0) * float(r.get("price") or 0),
            })
    return trades


def load_generic_csv(path):
    """BUY/SELL 逐檔 FIFO 配對。欄位: date,symbol,side,qty,price,fee。"""
    import csv
    lots = defaultdict(list)  # symbol -> [(ts, qty_left, price, fee_per_unit)]
    trades = []
    with open(path, encoding="utf-8-sig") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["date"])
    for r in rows:
        side = (r["side"] or "").strip().upper()
        sym = r["symbol"].strip()
        ts = _parse_ts(r["date"])
        qty = float(r["qty"])
        px = float(r["price"])
        fee = float(r.get("fee") or 0)
        if side == "BUY":
            lots[sym].append([ts, qty, px, fee / qty if qty else 0])
        elif side == "SELL":
            remain, sell_fee_u = qty, fee / qty if qty else 0
            while remain > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(remain, lot[1])
                fees = take * (lot[3] + sell_fee_u)
                gross = (px - lot[2]) * take
                trades.append({
                    "symbol": sym, "side": "long",
                    "entry_ts": lot[0], "exit_ts": ts,
                    "hold_days": (ts - lot[0]).total_seconds() / 86400,
                    "pnl": gross - fees, "gross_pnl": gross, "fees": fees,
                    "notional": lot[2] * take,
                })
                lot[1] -= take
                remain -= take
                if lot[1] <= 1e-9:
                    lots[sym].pop(0)
    return trades


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _welch_t(a, b):
    """Welch t 檢定(雙樣本不等變異)。回 (t, 近似p);樣本不足回 (None, None)。"""
    if len(a) < 8 or len(b) < 8:
        return None, None
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return None, None
    t = (ma - mb) / se
    p = 2 * (1 - _norm_cdf(abs(t)))  # 大樣本常態近似
    return t, p


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def profile(trades):
    n = len(trades)
    s = {"n_trades": n}
    if n == 0:
        return s
    pnls = [t["pnl"] for t in trades]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    s["win_rate"] = round(len(wins) / n, 4)
    s["total_pnl"] = round(sum(pnls), 2)
    s["avg_win"] = round(_mean([t["pnl"] for t in wins]), 4) if wins else None
    s["avg_loss"] = round(_mean([t["pnl"] for t in losses]), 4) if losses else None
    if s["avg_win"] and s["avg_loss"]:
        s["payoff_ratio"] = round(abs(s["avg_win"] / s["avg_loss"]), 2)
    s["expectancy"] = round(_mean(pnls), 4)
    gross = sum(abs(t["gross_pnl"]) for t in trades)
    s["fee_drag_pct_of_gross"] = round(sum(t["fees"] for t in trades) / gross * 100, 2) if gross else None

    # 處置效應:輸單持有天數 vs 贏單持有天數
    hw = [t["hold_days"] for t in wins if t["hold_days"] is not None]
    hl = [t["hold_days"] for t in losses if t["hold_days"] is not None]
    if hw and hl:
        s["hold_days_win_avg"] = round(_mean(hw), 2)
        s["hold_days_loss_avg"] = round(_mean(hl), 2)
        t_stat, p = _welch_t(hl, hw)
        s["disposition"] = {
            "loser_held_longer": _mean(hl) > _mean(hw),
            "t": round(t_stat, 2) if t_stat is not None else None,
            "p": round(p, 4) if p is not None else None,
            "note": "n不足8+8,不做檢定" if t_stat is None else
                    ("顯著:輸單抱較久=處置效應" if p < 0.05 and _mean(hl) > _mean(hw) else "未達顯著"),
        }

    # 報復性交易:虧損後下一筆 notional 是否放大
    seq = [t for t in trades if t.get("notional") and t.get("exit_ts")]
    seq.sort(key=lambda t: t["exit_ts"])
    after_loss, after_win = [], []
    for prev, cur in zip(seq, seq[1:]):
        (after_loss if prev["pnl"] <= 0 else after_win).append(cur["notional"])
    if after_loss and after_win:
        s["sizing_after_loss_vs_win"] = {
            "avg_after_loss": round(_mean(after_loss), 2),
            "avg_after_win": round(_mean(after_win), 2),
            "ratio": round(_mean(after_loss) / _mean(after_win), 2),
            "n": [len(after_loss), len(after_win)],
            "note": "ratio>1.3=虧損後加碼傾向(報復性交易警訊)",
        }

    # 過度交易:日交易數分布
    by_day = defaultdict(int)
    for t in seq:
        by_day[t["exit_ts"].date()] += 1
    if by_day:
        counts = sorted(by_day.values())
        s["trades_per_active_day"] = {"avg": round(_mean(counts), 2), "max": counts[-1]}
    if n < 20:
        s["caveat"] = f"樣本僅 {n} 筆,所有結論僅供參考,不足以下統計判斷"
    return s


def render_report(stats, src, fmt):
    L = [f"# Shadow Review 覆盤報告", "",
         f"- 來源:`{src}`(格式 {fmt})", f"- 產生:{datetime.now().strftime('%Y-%m-%d %H:%M')}",
         f"- 回合數:{stats.get('n_trades', 0)}", ""]
    if stats.get("caveat"):
        L.append(f"> ⚠️ {stats['caveat']}\n")
    if stats.get("n_trades"):
        L += ["## 基本面", "",
              f"| 指標 | 值 |", "|---|---|",
              f"| 勝率 | {stats['win_rate']*100:.1f}% |",
              f"| 總損益(費後) | {stats['total_pnl']} |",
              f"| 平均贏/輸 | {stats.get('avg_win')} / {stats.get('avg_loss')} |",
              f"| 賠率(payoff) | {stats.get('payoff_ratio', '—')} |",
              f"| 每筆期望值 | {stats.get('expectancy')} |",
              f"| 手續費侵蝕(佔毛損益絕對值) | {stats.get('fee_drag_pct_of_gross', '—')}% |", ""]
        d = stats.get("disposition")
        if d:
            L += ["## 處置效應(輸單抱較久?)", "",
                  f"- 贏單平均持有 {stats['hold_days_win_avg']} 天 vs 輸單 {stats['hold_days_loss_avg']} 天",
                  f"- 檢定:{d['note']}" + (f"(t={d['t']}, p={d['p']})" if d.get('t') is not None else ""), ""]
        z = stats.get("sizing_after_loss_vs_win")
        if z:
            L += ["## 虧損後加碼傾向", "",
                  f"- 虧損後下一筆平均部位 {z['avg_after_loss']} vs 獲利後 {z['avg_after_win']}(ratio {z['ratio']},n={z['n']})",
                  f"- {z['note']}", ""]
        f = stats.get("trades_per_active_day")
        if f:
            L += ["## 交易頻率", "", f"- 有交易日平均 {f['avg']} 筆/日,最高 {f['max']} 筆", ""]
    L += ["---", "工具:quant_lab/shadow_review(概念源自 Vibe-Trading Shadow Account;統計誠實原則:樣本不足不硬給結論)"]
    return "\n".join(L)


LOADERS = {"bot_jsonl": load_bot_jsonl, "tw_paper": load_tw_paper, "generic": load_generic_csv}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fills")
    ap.add_argument("--fmt", choices=list(LOADERS), default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    fmt = args.fmt
    if not fmt:
        fmt = "generic" if args.fills.endswith(".csv") else (
            "tw_paper" if "tw_paper" in os.path.basename(args.fills) else "bot_jsonl")
    trades = LOADERS[fmt](args.fills)
    stats = profile(trades)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                                   os.path.splitext(os.path.basename(args.fills))[0])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    report = render_report(stats, args.fills, fmt)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n→ {out}/report.md, stats.json", file=sys.stderr)


if __name__ == "__main__":
    main()
