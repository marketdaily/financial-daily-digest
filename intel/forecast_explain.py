#!/usr/bin/env python3
"""把 market_forecast 的線性模型『黑箱機率』拆成『看得見的因果面板』(2026-07-23 Delvin 定調)。

模型是 logistic(線性),所以每個 driver 對 log-odds z 的貢獻正好是
    contrib_j = w[j+1] * (f[feat_j] - mu[j]) / sd[j]
—— 精確歸因、可加總還原成同一個機率,不是事後編故事。正=推漲、負=推跌、|值|=影響力。
面板 = 排序後的因果鏈;再接 FORECAST.md 的誠實可操作性但書,推出『能不能進場』那一行。

這一層只『解釋既有已驗證模型』,不新增任何預測——零建模風險。
用法: python3 -m intel.forecast_explain [--selftest]
"""
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "intel" / "market_forecast_model.json"
LEDGER = REPO / "quant_lab" / "market_forecast" / "shadow_ledger.jsonl"
LEDGER_US = REPO / "quant_lab" / "market_forecast" / "shadow_ledger_us.jsonl"

# driver → (中文短名, 一句因果機制, 單位)  單位: pct=漲跌% / lvl=水位
DRIVER_META = {
    "sox":       ("費半 SOX", "美國晶片股;台股半導體佔大盤權重約六成,最強領先鏈", "pct"),
    "spx":       ("美股 S&P500", "美股大盤 risk-on/off 情緒外溢", "pct"),
    "stoxx":     ("歐股 Stoxx50", "歐洲盤情緒", "pct"),
    "kospi":     ("韓股 KOSPI", "亞洲科技出口鏈連動", "pct"),
    "n225":      ("日經 225", "亞股連動", "pct"),
    "hsi":       ("港股恒生", "陸港資金情緒", "pct"),
    "vix_lvl":   ("VIX 恐慌水位", "低=市場敢冒險、高=避險縮手", "lvl"),
    "vix_chg":   ("VIX 變化", "恐慌升溫/降溫的速度", "pct"),
    "twii_prev": ("台股昨日", "昨天大漲/大跌後,今天常有均值回歸拉力(反向)", "pct"),
    "twii_m5":   ("台股5日動能", "短線漲多了容易回落(反向)", "pct"),
    "kospi_gap": ("韓股開盤跳空", "台股開盤前最新的亞股即時訊號", "pct"),
    "n225_gap":  ("日股開盤跳空", "台股開盤前最新的亞股即時訊號", "pct"),
    "spx_prev":  ("美股昨收 S&P", "美股自身昨日(單獨無 edge,需搭亞洲當日)", "pct"),
    "sox_prev":  ("費半昨收", "美國晶片昨日", "pct"),
    "spx_m5":    ("美股5日動能", "短線動能", "pct"),
    "twii_td":   ("台股今日收盤", "台股收盤後→美股當晚的新資訊", "pct"),
    "kospi_td":  ("韓股今日收盤", "亞股當日收盤領先美股當晚", "pct"),
    "n225_td":   ("日股今日收盤", "亞股當日收盤", "pct"),
    "hsi_td":    ("港股今日收盤", "亞股當日收盤", "pct"),
}


def _fmt_val(feat, v):
    unit = DRIVER_META.get(feat, ("", "", "pct"))[2]
    return f"水位 {v:.1f}" if unit == "lvl" else f"{v:+.1f}%"


def explain(model, f):
    """回傳 {p_up, z, intercept, drivers:[...] 依 |contrib| 降序}。p_up 精確等於 market_forecast.predict。"""
    feats, mu, sd, w = model["feats"], model["mu"], model["sd"], model["w"]
    z = w[0]
    drivers = []
    for j, k in enumerate(feats):
        contrib = w[j + 1] * (f[k] - mu[j]) / sd[j]
        z += contrib
        name, mech, _ = DRIVER_META.get(k, (k, "", "pct"))
        drivers.append({"feat": k, "name": name, "mech": mech,
                        "value": f[k], "contrib": contrib,
                        "dir": "漲" if contrib > 0 else "跌"})
    drivers.sort(key=lambda d: -abs(d["contrib"]))
    p = 1 / (1 + math.exp(-max(-30, min(30, z))))
    return {"p_up": p, "z": z, "intercept": w[0], "drivers": drivers}


def _tier(p):
    if p >= 0.75 or p <= 0.25:
        return "high"
    if p >= 0.6 or p <= 0.4:
        return "mid"
    return "noise"


def entry_line(slot, tier, p_up):
    """『能不能進場』誠實層:FORECAST.md 鐵則=收盤預報,準的部分大半在開盤跳空,
    盤中追進吃不到;唯 slot b 高把握日 OOS 開盤後仍約 64%。永不寫成『開盤買進』。"""
    dir_word = "偏漲" if p_up >= 0.5 else "偏跌"
    base = "這是『收盤方向』預報——準的部分大半在開盤那一跳,09:00 後追進通常吃不到。"
    if slot == "b" and tier == "high":
        extra = (f"今天是少數『高把握開盤日』,方向{dir_word},盤中仍留有一點真優勢"
                 f"(OOS≈64%);但仍先確認沒過度跳空再考慮。")
    elif tier == "high":
        extra = f"方向{dir_word}、把握度高,但這是隔夜版,盤中優勢有限——當強氛圍參考,別追高。"
    elif tier == "noise":
        extra = "而且今天訊號雜、方向難判,更不該靠它進場;守好手上部位就好。"
    else:
        extra = f"方向{dir_word}但普通把握,當氛圍參考即可。"
    return "能不能進場:" + base + extra


def panel_text(model, f, slot="a"):
    ex = explain(model, f)
    p, t = ex["p_up"], _tier(ex["p_up"])
    dir_word = "偏漲" if p >= 0.5 else "偏跌"
    conf = {"high": "高把握", "mid": "中等把握", "noise": "雜訊日·方向難判"}[t]
    lines = [f"今日大盤預判(收盤方向):{dir_word} {p * 100:.0f}%  ·  {conf}"]
    ups = [d for d in ex["drivers"] if d["contrib"] > 0][:3]
    dns = [d for d in ex["drivers"] if d["contrib"] < 0][:3]
    if ups:
        lines.append("推漲的力量:")
        for d in ups:
            lines.append(f"  ▲ {d['name']} {_fmt_val(d['feat'], d['value'])} — {d['mech']}")
    if dns:
        lines.append("拉跌的力量:")
        for d in dns:
            lines.append(f"  ▼ {d['name']} {_fmt_val(d['feat'], d['value'])} — {d['mech']}")
    lines.append(entry_line(slot, t, p))
    return "\n".join(lines)


def _load_models():
    return json.loads(MODEL_PATH.read_text())


def selftest():
    m = _load_models()
    # 已驗證:decomposition 還原的 p_up 必須精確等於 market_forecast.predict + ledger 記錄值
    from intel.market_forecast import predict
    cases = [
        ("model_a", {"sox": 5.214, "spx": 0.886, "stoxx": -0.056, "kospi": -4.462, "n225": -4.031,
                     "hsi": 2.365, "vix_lvl": 17.05, "vix_chg": -8.579, "twii_prev": -0.519,
                     "twii_m5": -6.458}, 0.8952),  # 2026-07-22 ledger
        ("model_a", {"sox": 0.441, "spx": -0.136, "stoxx": 0.935, "kospi": 3.555, "n225": 3.26,
                     "hsi": -0.043, "vix_lvl": 16.64, "vix_chg": -2.405, "twii_prev": 4.201,
                     "twii_m5": -1.129}, 0.4666),  # 2026-07-23 ledger
    ]
    ok = True
    for mk, f, ledger_p in cases:
        ex = explain(m[mk], f)
        p_pred = predict(m[mk], f)
        sum_contrib = ex["intercept"] + sum(d["contrib"] for d in ex["drivers"])
        a1 = abs(ex["p_up"] - p_pred) < 1e-9           # 拆解還原 == 模型
        a2 = abs(ex["p_up"] - ledger_p) < 5e-4          # == 帳本記錄
        a3 = abs(sum_contrib - ex["z"]) < 1e-9          # 貢獻可加總還原 z
        status = "✅" if (a1 and a2 and a3) else "❌"
        if not (a1 and a2 and a3):
            ok = False
        print(f"{status} {mk} p={ex['p_up']:.4f} (model={p_pred:.4f} ledger={ledger_p}) "
              f"還原z={a3}")
    print("=== SELFTEST PASS ===" if ok else "=== SELFTEST FAIL ===")
    return ok


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    m = _load_models()
    for path, mk, slot, label in [(LEDGER, "model_a", "a", "台股早報"),
                                  (LEDGER_US, "model_us", "us", "美股晚報")]:
        if not path.exists():
            continue
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        if not lines:
            continue
        rec = json.loads(lines[-1])
        print(f"\n===== {label}({rec.get('date')}) =====")
        print(panel_text(m[mk], rec["features"], slot=rec.get("slot", slot)))


if __name__ == "__main__":
    main()
