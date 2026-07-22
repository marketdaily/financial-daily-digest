"""台股排行異動連接器(信息差引擎積木):讀 rank_scan_ledger.jsonl(quote_bridge/rank_scan.py
每交易日 13:50 快照 Shioaji scanners 5 榜 top50),零依賴不觸網。

訊號定義(v1 啟發式,精確門檻後續 edge_audit 校準):
  🔴 量能竄榜(volume_newface):今日量榜 top20,且近 10 個有資料的交易日從未進過量榜 top50
     ——無預警的量能 regime 轉變,常伴隨消息面/籌碼面異動(需 ≥5 個歷史交易日才判,冷啟動期不誤報)
  🟡 自選股上榜(watchlist_ranked):watchlist 個股出現在漲幅/量/額任一榜 top20(資訊型,提示今日異常活躍)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "rank_scan_ledger.jsonl")
NEWFACE_TOP = 20
HIST_TOP = 50
MIN_HIST_DAYS = 5
LOOKBACK_DAYS = 10
RANK_LABEL = {"change": "漲幅", "volume": "成交量", "amount": "成交額"}


def load_ledger(path=None, max_days=20):
    rows = []
    try:
        with open(path or LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("date") and e.get("ranks"):
                        rows.append(e)
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    rows.sort(key=lambda e: e["date"])
    return rows[-max_days:]


def classify(ledger, watchlist):
    """純函式:ledger(舊→新)+watchlist codes → list[{code,level,signal,rule}]。"""
    if not ledger:
        return []
    latest = ledger[-1]
    hist = ledger[:-1][-LOOKBACK_DAYS:]
    out = []
    ranks = latest.get("ranks") or {}

    vol_top20 = (ranks.get("volume") or [])[:NEWFACE_TOP]
    if len(hist) >= MIN_HIST_DAYS:
        hist_vol50 = set()
        for e in hist:
            for r in (e.get("ranks") or {}).get("volume", [])[:HIST_TOP]:
                hist_vol50.add(r["code"])
        for i, r in enumerate(vol_top20):
            if r["code"] not in hist_vol50:
                chg = f"{r['change_pct']:+.1f}%" if r.get("change_pct") is not None else "—"
                out.append({"code": r["code"], "level": "red", "rule": "volume_newface",
                            "signal": f"{r.get('name') or r['code']}({r['code']}) 量能竄榜:今日量榜第{i+1}"
                                      f"(近{len(hist)}日未進過top{HIST_TOP},{chg},{r.get('volume', 0):,}張)"})

    wl = {str(c).upper() for c in (watchlist or [])}
    seen = {o["code"] for o in out}
    for rtype in ("change", "volume", "amount"):
        for i, r in enumerate((ranks.get(rtype) or [])[:NEWFACE_TOP]):
            c = r["code"]
            if c in wl and c not in seen:
                seen.add(c)
                chg = f"{r['change_pct']:+.1f}%" if r.get("change_pct") is not None else "—"
                out.append({"code": c, "level": "yellow", "rule": "watchlist_ranked",
                            "signal": f"{r.get('name') or c}({c}) 今日{RANK_LABEL[rtype]}排行第{i+1}({chg}),異常活躍"})
    return out


def active_signals(watchlist, today=None, path=None):
    """patrol 消費入口:ledger 最新一筆需 ≤2 天新鮮,否則回 [](資料過期不判讀)。"""
    import datetime
    ledger = load_ledger(path)
    if not ledger:
        return []
    ref = today or datetime.date.today()
    try:
        age = (ref - datetime.date.fromisoformat(ledger[-1]["date"])).days
    except Exception:
        return []
    if age > 2:
        return []
    return classify(ledger, watchlist)


if __name__ == "__main__":
    import sys
    wl = sys.argv[1].split(",") if len(sys.argv) > 1 else []
    print(json.dumps(active_signals(wl), ensure_ascii=False, indent=1))
