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
LEDGER_US = REPO / "quant_lab" / "market_forecast" / "shadow_ledger_us.jsonl"
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


def settle(twii_bars, today, ledger=None):
    ledger = ledger or LEDGER
    if not ledger.exists():
        return
    lines = ledger.read_text().splitlines()
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
                rec["skipped"] = "no_bar"
                changed = True
        out.append(json.dumps(rec, ensure_ascii=False))
    if changed:
        ledger.write_text("\n".join(out) + "\n")
        log("已結算舊預測")


US_FEATS_ASIA = [("twii_td", "twii"), ("kospi_td", "kospi"), ("n225_td", "n225"), ("hsi_td", "hsi")]


def build_features_us(today, data):
    """晚報 19:25 TW 生成時已定案:美股昨收(spx/sox/vix,bars 日期<today)+S&P 5日動能
    +亞洲當日收盤(==today,休市=0 無新資訊)。今晚美股 21:30 TW 才開盤,無前視。"""
    f = {}
    for key, name in [("spx_prev", "spx"), ("sox_prev", "sox")]:
        hist = [b for b in data[name] if b[0] < today]
        if len(hist) < 2 or not hist[-2][2]:
            raise ValueError(f"{name} 歷史不足")
        f[key] = (hist[-1][2] / hist[-2][2] - 1) * 100
    vh = [b for b in data["vix"] if b[0] < today]
    if len(vh) < 2:
        raise ValueError("vix 歷史不足")
    f["vix_lvl"] = vh[-1][2]
    f["vix_chg"] = (vh[-1][2] / vh[-2][2] - 1) * 100
    sh = [b for b in data["spx"] if b[0] < today]
    if len(sh) < 6 or not sh[-6][2]:
        raise ValueError("spx 動能歷史不足")
    f["spx_m5"] = (sh[-1][2] / sh[-6][2] - 1) * 100
    for key, name in US_FEATS_ASIA:
        tb = [b for b in data[name] if b[0] == today]
        prev = [b for b in data[name] if b[0] < today]
        if tb and tb[0][2] and prev and prev[-1][2]:
            f[key] = (tb[0][2] / prev[-1][2] - 1) * 100
        else:
            f[key] = 0.0
    return f


def forecast_tonight_us(test=False):
    """美股晚報 19:25 生成時由 data_fetcher.fetch_all 呼叫:model_us 算今晚 S&P500 收盤方向機率。
    只在晚報時窗(TW 17-21 平日)計算;失敗回 {}(缺了不缺信)。與台股版不同,US 無獨立 cron,
    ledger(shadow_ledger_us.jsonl)由本函數順手結算+記帳(單一觸發源=日報生成)。
    回測(us_ceiling_backtest.py,OOS 2015-2026):命中 58.1%(基礎率 54.3%)、top20% 信心日 66.7%;
    US-only 特徵無 edge(54.2%),增量全來自亞洲當日收盤 → 亞股是美股當晚的真領先資訊(反向成立,
    與 GLOBAL_LEAD.md「亞股昨收對台股無資訊」不矛盾:那是隔夜舊資訊,這是當日新資訊)。
    oc 但書同台股版:top20% 桶 open-to-close 只 55.4%,大半是隔夜跳空 → 永遠只當收盤預報。"""
    try:
        now = datetime.now(TW)
        if not test and (not (17 <= now.hour < 21) or now.weekday() >= 5):
            return {}
        model_all = json.loads(MODEL_PATH.read_text())
        if "model_us" not in model_all:
            return {}
        data = {k: bars(v) for k, v in SYMS.items()}
        today = now.date()
        try:
            settle(data["spx"], today, ledger=LEDGER_US)
        except Exception as e:
            log(f"US ledger 結算失敗(不影響今日預測): {e}")
        f = build_features_us(today, data)
        p = predict(model_all["model_us"], f)
        t = tier(p)
        out = {"p_up": round(p, 3), "tier": t, "slot": "us", "market": "us",
               "trained_through": model_all.get("trained_through_us", "")}
        try:
            from intel.forecast_explain import cascade_text
            out["cascade"] = cascade_text(model_all["model_us"], f)
        except Exception as e:
            log(f"cascade 附掛失敗(不影響預判): {e}")
        if not test:
            rec = {"ts": now.isoformat(timespec="seconds"), "date": today.isoformat(),
                   "slot": "us", "p_up": round(p, 4), "tier": t,
                   "features": {k: round(v, 3) for k, v in f.items()},
                   "trained_through": model_all.get("trained_through_us", "")}
            LEDGER_US.parent.mkdir(parents=True, exist_ok=True)
            with open(LEDGER_US, "a") as fo:
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
        else:
            log(f"[test] features={ {k: round(v, 2) for k, v in f.items()} } p_up={p:.3f} tier={t}")
        return out
    except Exception as e:
        log(f"forecast_tonight_us failed(fail-silent): {e}")
        return {}


def forecast_today():
    """日報 06:20 生成時由 data_fetcher.fetch_all 呼叫:slot a 模型算今日收盤方向機率。
    只在早報時窗(TW 04-09)計算(晚報是美股主場且韓日開盤未知);任何失敗回 {}(缺了不缺信)。
    不寫 shadow ledger——06:25 cron 另記,雙軌對帳。"""
    try:
        now = datetime.now(TW)
        if not (4 <= now.hour < 9) or now.weekday() >= 5:
            return {}
        model_all = json.loads(MODEL_PATH.read_text())
        data = {k: bars(v) for k, v in SYMS.items()}
        f = build_features("a", now.date(), data)
        p = predict(model_all["model_a"], f)
        out = {"p_up": round(p, 3), "tier": tier(p), "slot": "a",
               "trained_through": model_all["trained_through"]}
        try:
            from intel.forecast_explain import cascade_text
            out["cascade"] = cascade_text(model_all["model_a"], f)
        except Exception as e:
            log(f"cascade 附掛失敗(不影響預判): {e}")
        return out
    except Exception as e:
        log(f"forecast_today failed(fail-silent): {e}")
        return {}


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
