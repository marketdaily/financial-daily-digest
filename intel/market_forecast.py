#!/usr/bin/env python3
"""每日大盤預判 shadow 模組(2026-07-21)。

兩時點對台股「收盤對收盤」方向給校準機率(收盤預報,非進場訊號):
  slot a = 06:25(隔夜:費半/S&P/歐股/韓日港昨收+VIX+台股動能)
  slot b = 08:16(加韓/日開盤 gap,韓股 08:00 TW 開盤)
模型=quant_lab/market_forecast/train.py 凍結權重(intel/market_forecast_model.json)。
OOS 天花板(2015-2026,詳 quant_lab/market_forecast/FORECAST.md):
  收盤方向:A 66.6%/B 69.7%;最有把握 20% 日子:A 84.9%/B 88.3%
  ⚠️ 開盤後可捕捉(open-to-close):A 54.1%/B 56.2%,只有 B 高信心日 64.2%——
  所以這是「收盤預報+regime 輸入」,任何文案不得寫成「開盤買進」。
shadow 模式:只記帳 quant_lab/market_forecast/shadow_ledger.jsonl(gitignored,winrig 本機),
每次執行先結算舊預測。跑滿兩週看 hit rate 對不對得上 OOS 再決定進日報。fail-silent。

用法:python3 -m intel.market_forecast [--slot a|b] [--test]
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "intel" / "market_forecast_model.json"
LEDGER = REPO / "quant_lab" / "market_forecast" / "shadow_ledger.jsonl"
TW = timezone(timedelta(hours=8))
SYMS = {"sox": "^SOX", "spx": "^GSPC", "stoxx": "^STOXX50E", "kospi": "^KS11",
        "n225": "^N225", "hsi": "^HSI", "vix": "^VIX", "twii": "^TWII"}


def log(msg):
    print(f"[{datetime.now(TW).strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def bars(sym):
    """Yahoo 日線 → [(TW日期, open, close)];時間戳一律轉 UTC+8 取日期(與訓練資料同基準)。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(sym)}?range=1mo&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    out = []
    for t, o, c in zip(d["timestamp"], q["open"], q["close"]):
        if c is not None:
            out.append((datetime.fromtimestamp(t, tz=TW).date(), o, c))
    return out


def build_features(slot, today, data):
    f = {}
    for name in ["sox", "spx", "stoxx", "kospi", "n225", "hsi"]:
        hist = [b for b in data[name] if b[0] < today]
        if len(hist) < 2 or not hist[-2][2]:
            raise ValueError(f"{name} 歷史不足")
        f[name] = (hist[-1][2] / hist[-2][2] - 1) * 100
    vh = [b for b in data["vix"] if b[0] < today]
    if len(vh) < 2:
        raise ValueError("vix 歷史不足")
    f["vix_lvl"] = vh[-1][2]
    f["vix_chg"] = (vh[-1][2] / vh[-2][2] - 1) * 100
    th = [b for b in data["twii"] if b[0] < today]
    if len(th) < 6:
        raise ValueError("twii 歷史不足")
    f["twii_prev"] = (th[-1][2] / th[-2][2] - 1) * 100
    f["twii_m5"] = (th[-1][2] / th[-6][2] - 1) * 100
    if slot == "b":
        for name, key, required in [("kospi", "kospi_gap", True), ("n225", "n225_gap", False)]:
            tb = [b for b in data[name] if b[0] == today]
            prev = [b for b in data[name] if b[0] < today]
            if tb and tb[0][1] and prev and prev[-1][2] and abs(tb[0][1] - prev[-1][2]) > 1e-9:
                f[key] = (tb[0][1] / prev[-1][2] - 1) * 100
            elif required:
                raise ValueError(f"{name} 今日開盤 K 棒未出(休市或延遲)")
            else:
                f[key] = 0.0
    return f


def predict(model, f):
    import math
    mu, sd, w, feats = model["mu"], model["sd"], model["w"], model["feats"]
    z = w[0]
    for j, k in enumerate(feats):
        z += w[j + 1] * (f[k] - mu[j]) / sd[j]
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def tier(p):
    if p >= 0.75 or p <= 0.25:
        return "high"
    if p >= 0.6 or p <= 0.4:
        return "mid"
    return "noise"


def settle(twii_bars, today):
    if not LEDGER.exists():
        return
    lines = LEDGER.read_text().splitlines()
    by_date = {b[0].isoformat(): b for b in twii_bars}
    changed = False
    out = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if "actual_cc" not in rec and rec.get("date", "") < today.isoformat():
            b = by_date.get(rec["date"])
            if b:
                prev = [x for x in twii_bars if x[0].isoformat() < rec["date"]]
                if prev and prev[-1][2]:
                    cc = (b[2] / prev[-1][2] - 1) * 100
                    oc = (b[2] / b[1] - 1) * 100 if b[1] else None
                    rec["actual_cc"] = round(cc, 2)
                    rec["actual_oc"] = round(oc, 2) if oc is not None else None
                    rec["hit_cc"] = (rec["p_up"] > 0.5) == (cc > 0)
                    changed = True
            elif (today - datetime.strptime(rec["date"], "%Y-%m-%d").date()).days > 7:
                rec["skipped"] = "no_twii_bar"
                changed = True
        out.append(json.dumps(rec, ensure_ascii=False))
    if changed:
        LEDGER.write_text("\n".join(out) + "\n")
        log("已結算舊預測")


def main():
    test = "--test" in sys.argv
    slot = None
    if "--slot" in sys.argv:
        slot = sys.argv[sys.argv.index("--slot") + 1]
    now = datetime.now(TW)
    if slot not in ("a", "b"):
        slot = "a" if now.hour < 8 else "b"
    today = now.date()
    if now.weekday() >= 5 and not test:
        log("週末,跳過")
        return
    model_all = json.loads(MODEL_PATH.read_text())
    model = model_all["model_a" if slot == "a" else "model_b"]
    try:
        data = {k: bars(v) for k, v in SYMS.items()}
    except Exception as e:
        log(f"行情抓取失敗,fail-silent:{e}")
        return
    if not test:
        try:
            settle(data["twii"], today)
        except Exception as e:
            log(f"結算失敗(不影響今日預測):{e}")
    try:
        f = build_features(slot, today, data)
    except ValueError as e:
        log(f"特徵不足,跳過:{e}")
        return
    p = predict(model, f)
    t = tier(p)
    log(f"slot={slot} {today} P(收漲)={p*100:.0f}% tier={t} "
        f"(trained_through={model_all['trained_through']})")
    if test:
        log(f"features={ {k: round(v, 2) for k, v in f.items()} }")
        return
    rec = {"ts": now.isoformat(timespec="seconds"), "date": today.isoformat(),
           "slot": slot, "p_up": round(p, 4), "tier": t,
           "features": {k: round(v, 3) for k, v in f.items()},
           "trained_through": model_all["trained_through"]}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a") as fo:
        fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log("已入 shadow 帳本")


if __name__ == "__main__":
    main()
