"""資金模擬器:給定本金 → 買哪些 CB(拆解)、怎麼配、抱到期預期賺多少、多久回本、賺錢機率。
方法:蒙地卡羅模擬標的股價到到期日(GBM,前瞻波動),算每檔拆解部位損益分佈,再組成投組。
拆解部位:權利金當本金(下檔最多賠光權利金)、上檔=max(到期parity-賣回價,0)。單口面額 NT$100,000。"""
import math, random
import cb_core

UNIT_FACE = 100_000.0   # 台股 CB 單口面額(報價per100 → ×1000 = 每口 NT$)


def _gbm_terminal(spot, drift, vol, T, z):
    return spot * math.exp((drift - 0.5 * vol * vol) * T + vol * math.sqrt(T) * z)


def _pct(sorted_list, q):
    if not sorted_list:
        return 0.0
    i = min(len(sorted_list) - 1, max(0, int(q * len(sorted_list))))
    return sorted_list[i]


def breakeven(item, a, strike, drift=0.07):
    """回本所需:到期股價需達 breakeven_S(使 parity=賣回價+權利金),對現價漲幅%,
    及用中位數 GBM 路徑估『預期幾年回本』。回 (be_S, move, t_years, reachable)。"""
    K = item["conv_price"]
    vol = a["hist_vol"]
    be_parity = strike + a["cbas_premium"]
    be_S = K * be_parity / 100.0
    move = be_S / a["spot"] - 1.0
    T = a["T_opt"]
    if be_S <= a["spot"]:
        return be_S, move, 0.0, True            # 已在回本點之上
    g = drift - 0.5 * vol * vol                  # 中位數對數漂移率
    if g <= 0:
        return be_S, move, None, False           # 中位數路徑到不了(靠波動/運氣)
    t = math.log(be_S / a["spot"]) / g
    return be_S, move, t, (t <= T)


def simulate_portfolio(candidates, capital, drift=0.07, rho=0.35, n=20000,
                       weights=None, seed=20260702):
    """candidates: list of (item, a) 其中 a=cb_core.analyze 結果(需 ok)。
    capital: 本金 NT$。weights: 各檔資金權重(None=依評分)。回 dict。"""
    random.seed(seed)
    cands = [(it, a) for it, a in candidates if a.get("ok") and a.get("cbas_premium", 0) > 0]
    if not cands:
        return {"ok": False, "reason": "無可模擬標的"}

    # 權重:預設依評分(下限防呆),上限單檔 45% 分散
    if weights is None:
        scores = [max(a["score"], 1) for _, a in cands]
        s = sum(scores)
        weights = [x / s for x in scores]
    weights = [min(w, 0.45) for w in weights]
    ws = sum(weights)
    weights = [w / ws for w in weights]

    legs = []
    for (it, a), w in zip(cands, weights):
        unit_cap = a["cbas_premium"] * 1000.0
        units = int((capital * w) // unit_cap)
        if units >= 1:
            legs.append(_make_leg(it, a, units, drift))
    if not legs:
        return {"ok": False, "reason": "本金不足以買進任一口(權利金 × 1000/口)"}
    return _run_mc(legs, drift, rho, n, seed, capital=capital)


def _make_leg(it, a, units, drift):
    strike, _ = cb_core.redemption_value(it.get("put"))
    be_S, be_move, be_t, reach = breakeven(it, a, strike, drift)
    premium = a["cbas_premium"]
    return {
        "item": it, "a": a, "units": units, "premium": premium,
        "unit_cap": premium * 1000.0, "deployed": units * premium * 1000.0,
        "strike": strike, "T": a["T_opt"], "vol": a["hist_vol"],
        "K": it["conv_price"], "spot": a["spot"], "shares": a["shares"],
        "be_S": be_S, "be_move": be_move, "be_years": be_t, "be_reach": reach,
        "leg_pnls": [],
    }


def _run_mc(legs, drift, rho, n, seed=20260702, capital=None):
    random.seed(seed)
    deployed = sum(L["deployed"] for L in legs)
    if deployed <= 0:
        return {"ok": False, "reason": "組合投入為 0"}
    port_pnls = []
    for _ in range(n):
        zm = random.gauss(0, 1)                    # 共同市場因子(相關性)
        total = 0.0
        for L in legs:
            eps = random.gauss(0, 1)
            z = math.sqrt(rho) * zm + math.sqrt(1 - rho) * eps
            S_T = _gbm_terminal(L["spot"], drift, L["vol"], L["T"], z)
            parity_T = 100.0 * S_T / L["K"]
            payoff = max(parity_T - L["strike"], 0.0)
            pnl = (payoff - L["premium"]) * 1000.0 * L["units"]
            L["leg_pnls"].append(pnl)
            total += pnl
        port_pnls.append(total)
    port_pnls.sort()
    exp_pnl = sum(port_pnls) / n
    horizon = sum(L["deployed"] * L["T"] for L in legs) / deployed
    exp_final = deployed + exp_pnl
    ann = (exp_final / deployed) ** (1 / horizon) - 1 if exp_final > 0 else -1.0
    for L in legs:
        lp = sorted(L["leg_pnls"])
        L["exp_pnl"] = sum(lp) / len(lp)
        L["prob_profit"] = sum(1 for x in lp if x > 0) / len(lp)
        L["leg_pnls"] = None
    return {
        "ok": True, "capital": capital if capital is not None else deployed,
        "deployed": deployed, "cash_left": (capital - deployed) if capital else 0,
        "horizon": horizon, "drift": drift, "rho": rho, "n": n,
        "exp_pnl": exp_pnl, "exp_final": exp_final,
        "exp_return": exp_pnl / deployed, "ann_return": ann,
        "prob_profit": sum(1 for x in port_pnls if x > 0) / n,
        "p5": _pct(port_pnls, 0.05), "p50": _pct(port_pnls, 0.50), "p95": _pct(port_pnls, 0.95),
        "max_loss": -deployed, "legs": legs,
    }


def simulate_explicit(triples, drift=0.07, rho=0.35, n=20000, seed=20260702):
    """指定張數的組合模擬。triples=[(item, a, units), …]。回同 _run_mc 結果。"""
    legs = [_make_leg(it, a, int(u), drift) for it, a, u in triples if int(u) > 0 and a.get("ok")]
    if not legs:
        return {"ok": False, "reason": "組合為空或張數為 0"}
    return _run_mc(legs, drift, rho, n, seed)


def multi_drift_explicit(triples, base_drift=0.07, **kw):
    drifts = [(0.0, "保守/零漂移"), (base_drift, "基準"), (max(base_drift * 2, 0.15), "樂觀")]
    out = []
    for d, label in drifts:
        r = simulate_explicit(triples, drift=d, **kw)
        r["drift"] = d
        r["drift_label"] = label
        out.append(r)
    return out


def multi_drift(candidates, capital, base_drift=0.07, **kw):
    """跑保守/基準/樂觀三個股票年報酬情境,回 list。base_drift=使用者設定的基準漂移。"""
    drifts = [(0.0, "保守/零漂移"), (base_drift, "基準"), (max(base_drift * 2, 0.15), "樂觀")]
    out = []
    for d, label in drifts:
        r = simulate_portfolio(candidates, capital, drift=d, **kw)
        r["drift"] = d
        r["drift_label"] = label
        out.append(r)
    return out
