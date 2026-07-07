"""CB 拆解(CBAS)量化核心。
CB = 債券底 + (100/轉換價) 張轉換選擇權。
拆解後投資人把債券底賣斷給銀行，只留選擇權當部位 → 權利金當本金、parity 當曝險 → 槓桿。
所有假設參數集中在 ASSUMPTIONS，可由呼叫端覆寫。"""
import math

# ── 可調假設 ──────────────────────────────────────────────
ASSUMPTIONS = {
    "rf": 0.013,            # 台幣無風險利率(10Y 公債約 1.2~1.5%)
    "asset_swap_spread": 0.020,  # 拆解資產交換 銀行收的年化融資 spread(TCRI5~6 約 1.5~2.5%)
    "vol_window": 60,       # 歷史波動率取樣交易日數
    # TCRI 信用評等 → 折現用的年化信用利差(疊在 rf 上),用來算債券底
    "tcri_spread": {1: 0.008, 2: 0.010, 3: 0.015, 4: 0.020, 5: 0.028,
                    6: 0.038, 7: 0.052, 8: 0.066, 9: 0.082},
    "default_tcri": 6,
    "vol_w_short": 0.35,    # 前瞻波動:短期(EWMA)權重
    "vol_w_long": 0.65,     # 長期(120d)權重
    # 發行人強制贖回(台灣CB標準條款:收盤價連續30營業日達轉換價130%可贖回→持有人被迫轉換,上檔被封)
    # 這是 Parisian 型條款(要持續超過,非瞬觸):用標準近似「有效障礙上移」
    # B_eff = 轉換價 × trigger × exp(0.5826·σ·√(window/252)),波動越大有效障礙越高;
    # σ→∞ 時 B_eff→∞ 收斂回無強贖 vanilla(隱波反解永遠有解)。call_adjust=False 退回純 BS。
    "call_adjust": True,
    "call_trigger_mult": 1.30,   # 條款觸價(轉換價的倍數;少數CB是1.5,可用 --set 或 config 改)
    "call_window_days": 30,      # 連續營業日數
    # 老闆的拆解硬門檻(不是加分,是及格線;任一不過直接淘汰)
    "elig_tcri": [3, 4],    # TCRI 須為 3 或 4 → 銀行才肯承做資產交換
    "elig_min_size": 10,    # 發行量 ≥ 雙位數億 → 有流動性、資產交換台吃得下
}


def eligible(item, a=ASSUMPTIONS):
    """老闆準則:TCRI∈{3,4} 且 發行量≥10億。回 (是否合格, 原因list)。
    TCRI 未知(現有 CB 無 TEJ 評等)時該條無法判定,以 --tcri 帶入。"""
    reasons = []
    tcri = item.get("tcri")
    size = item.get("size_yi")
    ok_size = (size is not None) and (size >= a["elig_min_size"])
    if tcri is None:
        reasons.append("TCRI 未知(TEJ 專有;用 --tcri N 帶入判定)")
        ok_tcri = False
    else:
        ok_tcri = tcri in a["elig_tcri"]
        if not ok_tcri:
            reasons.append(f"TCRI {tcri} 不在 {a['elig_tcri']}(銀行難承做資產交換)")
    if not ok_size:
        reasons.append(f"發行量 {size}億 < {a['elig_min_size']}億(流動性不足)")
    return (ok_tcri and ok_size), reasons


def set_config(**kw):
    """覆寫假設參數(rf / asset_swap_spread / vol_w_short / vol_w_long / tcri_spread)。"""
    for k, v in kw.items():
        if v is None:
            continue
        if k == "tcri_spread" and isinstance(v, dict):
            ASSUMPTIONS["tcri_spread"].update({int(kk): vv for kk, vv in v.items()})
        elif k in ASSUMPTIONS:
            ASSUMPTIONS[k] = v
    return ASSUMPTIONS


def eligibility(item):
    return eligible(item, ASSUMPTIONS)

SQRT2 = math.sqrt(2.0)


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def touch_prob(S, b, T, sigma, drift):
    """GBM 期間內曾觸及上方水位 b 的機率(反射原理)。
    這是專業口徑:CBAS 下檔封頂,期間內碰到回本點即可帶時間價值獲利出場,
    所以『曾觸及機率』遠比『抱到期終值機率』貼近實戰。"""
    if b <= S:
        return 1.0
    if T <= 0 or sigma <= 0:
        return 0.0
    a = math.log(b / S)
    nu = drift - 0.5 * sigma * sigma
    st = sigma * math.sqrt(T)
    return (_norm_cdf((-a + nu * T) / st)
            + math.exp(2.0 * nu * a / (sigma * sigma)) * _norm_cdf((-a - nu * T) / st))


def bs_call(S, K, T, sigma, r):
    """單股 Black-Scholes 買權，回 (price, delta, gamma, vega)。"""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0)
        return intrinsic, (1.0 if S > K else 0.0), 0.0, 0.0
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vt
    d2 = d1 - vt
    price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    delta = _norm_cdf(d1)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    gamma = pdf / (S * vt)
    vega = S * pdf * math.sqrt(T)
    return price, delta, gamma, vega


def _uo_call(S, K, T, sigma, r, B):
    """Reiner-Rubinstein up-and-out 買權 + 觸價即付 (B−K) rebate。
    觸及 B = 發行人強贖 → 持有人轉換,拿走當下內含值(B−K);沒觸及 = 一般買權到期。
    S ≥ B(已在可贖回區)直接回內含值。已用蒙地卡羅交叉驗證(backtest/test_call_barrier.py)。"""
    if S >= B:
        return max(S - K, 0.0)
    if T <= 0 or sigma <= 0:
        return max(min(S, B) - K, 0.0) if S > K else 0.0
    sq = sigma * math.sqrt(T)
    var = sigma * sigma
    mu = (r - 0.5 * var) / var
    lam = math.sqrt(mu * mu + 2.0 * r / var)
    N = _norm_cdf
    disc = math.exp(-r * T)
    x1 = math.log(S / K) / sq + (1 + mu) * sq
    x2 = math.log(S / B) / sq + (1 + mu) * sq
    y1 = math.log(B * B / (S * K)) / sq + (1 + mu) * sq
    y2 = math.log(B / S) / sq + (1 + mu) * sq
    pw1, pw2 = (B / S) ** (2 * (mu + 1)), (B / S) ** (2 * mu)
    A_ = S * N(x1) - K * disc * N(x1 - sq)
    B_ = S * N(x2) - K * disc * N(x2 - sq)
    C_ = S * pw1 * N(-y1) - K * disc * pw2 * N(-y1 + sq)
    D_ = S * pw1 * N(-y2) - K * disc * pw2 * N(-y2 + sq)
    uo = max(A_ - B_ + C_ - D_, 0.0)
    z = math.log(B / S) / sq + lam * sq
    rebate = (B - K) * ((B / S) ** (mu + lam) * N(-z)
                        + (B / S) ** (mu - lam) * N(-z + 2 * lam * sq))
    return uo + rebate


def call_barrier(K, sigma, a=ASSUMPTIONS):
    """強贖有效障礙(Parisian 持續窗近似,障礙隨σ上移)。"""
    trig = a.get("call_trigger_mult", 1.30)
    win = a.get("call_window_days", 30)
    return K * trig * math.exp(0.5826 * sigma * math.sqrt(win / 252.0))


def option_px(S, K, T, sigma, r, a=ASSUMPTIONS):
    """轉換選擇權單股定價:預設含發行人強贖上限(見 ASSUMPTIONS 註解);greeks 用中央差分。
    回 (price, delta, gamma, vega)。call_adjust=False 時退回純 BS。"""
    if not a.get("call_adjust", True):
        return bs_call(S, K, T, sigma, r)
    if S <= 0 or K <= 0 or sigma <= 0 or T <= 0:
        return bs_call(S, K, T, sigma, r)
    B = call_barrier(K, sigma, a)
    px = _uo_call(S, K, T, sigma, r, B)
    h = max(S * 0.005, 1e-6)
    up = _uo_call(S + h, K, T, sigma, r, B)
    dn = _uo_call(S - h, K, T, sigma, r, B)
    delta = max(-1.0, min((up - dn) / (2 * h), 1.5))
    gamma = (up - 2 * px + dn) / (h * h)
    hv = 0.01
    vega = (_uo_call(S, K, T, sigma + hv, r, B)
            - _uo_call(S, K, T, max(sigma - hv, 1e-4), r, B)) / (2 * hv)
    return px, delta, gamma, vega


def credit_rate(tcri, a=ASSUMPTIONS):
    spread = a["tcri_spread"].get(tcri or a["default_tcri"], a["tcri_spread"][a["default_tcri"]])
    return a["rf"] + spread


def redemption_value(put):
    """賣回/到期金額(面額100):優先用實際賣回價 redeem_price;否則 YTP(n)=(y%) → 100*(1+y)^n;沒資料當 100。"""
    if not put or put.get("year") is None:
        return 100.0, 3
    n = put["year"]
    if put.get("redeem_price"):
        return float(put["redeem_price"]), n
    y = (put.get("y_mid") or 0.0) / 100.0
    return 100.0 * ((1.0 + y) ** n), n


def bond_floor(item, a=ASSUMPTIONS):
    """債券底 = 賣回/到期金額 按 (rf+信用利差) 折現到今天。"""
    redeem, n = redemption_value(item.get("put"))
    r = credit_rate(item.get("tcri"), a)
    return redeem / ((1.0 + r) ** n)


def conv_price(item):
    """轉換價:優先用表上的;沒有就用『訂價參考股價 × 溢價率』反推(參考股價需另給)。"""
    return item.get("conv_price")


def analyze(item, spot, hist_vol, a=ASSUMPTIONS, market_price=None, premium_quote=None):
    """核心分析。spot=現股價, hist_vol=年化歷史波動率(小數)。
    market_price=CB 次級市場成交價(有就用市場隱波,更即時)。
    premium_quote=券商拆解後直接報給你的 CBAS 權利金(per100)——我們實際買的就是這端,
    有帶就完全以它為準(零誤差),並反推等效 CB 價算隱波。回 dict。"""
    K = conv_price(item)
    if not K or not spot:
        return {"ok": False, "reason": "缺轉換價或現股價"}

    T = float(item.get("tenor_year") or 3)
    put = item.get("put") or {}
    # 拆解部位真正存續到賣回日(YTP)較貼近現實;沒有就用年期
    T_opt = float(put.get("year") or item.get("tenor_year") or 3)
    r = ASSUMPTIONS["rf"]
    shares = 100.0 / K                       # 每張 CB(面額100)可換股數
    parity = spot / K * 100.0                # 轉換價值

    floor = bond_floor(item, a)
    call_px, delta, gamma, vega = option_px(spot, K, T_opt, hist_vol, r, a)
    opt_value = shares * call_px             # 每張 CB 的轉換選擇權價值(含強贖上限)
    opt_vanilla = shares * bs_call(spot, K, T_opt, hist_vol, r)[0]   # 無強贖上界(參考)
    theo = floor + opt_value                 # 理論 CB 價

    financing = floor * a["asset_swap_spread"] * T_opt   # 期間融資成本(粗估)
    # 券商直接報權利金(我們實際買的拆解後選擇權端)→ 反推等效 CB 價,全鏈路以報價為準
    had_market = market_price is not None
    if premium_quote and not market_price:
        market_price = floor + premium_quote - financing

    clearing = item.get("clearing_price")
    clearing_known = clearing is not None
    # 買價基準:CB 現價 > 權利金報價(反推) > 承銷/競拍價 > 面額100佔位
    buy_price = market_price or clearing or 100.0
    buy_source = ("CB現價" if had_market else
                  ("權利金報價" if premium_quote else ("承銷價" if clearing_known else "面額100(估)")))
    issue = buy_price
    # 隱含波動率:解 σ 使 floor + shares*BS(σ) = 價格基準
    # 只在有『真實價格基準』(承銷價或市價)時才反推;無真實價不拿面額100 硬解(會產生假隱波)
    iv_clearing = implied_vol(spot, K, T_opt, r, shares, floor, clearing, a=a) if clearing_known else None
    iv_market = implied_vol(spot, K, T_opt, r, shares, floor, market_price, a=a) if market_price else None
    iv = iv_market if iv_market else iv_clearing
    iv_source = "市場價" if iv_market else ("承銷價" if clearing_known else "—")

    # ── CBAS 拆解經濟學 ──
    # 權利金:券商有直接報就用報價(零誤差);有真實買價(市價/承銷價)→ 真實計算;
    # 只有面額100佔位的推估才套「選擇權值一半」下限防呆(防止假便宜),不可蓋掉真實價差
    if premium_quote:
        premium = premium_quote
    elif market_price is not None or clearing_known:
        premium = max(buy_price - floor + financing, 0.1)
    else:
        premium = max(buy_price - floor + financing, opt_value * 0.5)
    leverage = parity / premium if premium > 0 else None
    eff_delta = shares * delta               # 每張 CB 對股價的 delta(張數×單股delta)
    # 損益槓桿:股價漲 1% → parity 漲 parity*1%,選擇權漲 ≈ eff_delta*spot*1%
    moneyness = spot / K                     # >1 價內

    scen = scenarios(item, spot, K, T_opt, hist_vol, r, shares, floor, premium, issue)

    vol_edge = (hist_vol - iv) if iv else None
    score, reasons = score_cb(item, dict(parity=parity, theo=theo, issue=issue,
                                         iv=iv, vol_edge=vol_edge, hist_vol=hist_vol,
                                         delta=delta, leverage=leverage,
                                         moneyness=moneyness), a)

    elig, elig_reasons = eligible(item, a)
    return {
        "ok": True,
        "eligible": elig, "elig_reasons": elig_reasons,
        "spot": spot, "conv_price": K, "shares": shares, "parity": parity,
        "moneyness": moneyness, "premium_at_issue": item.get("premium_mid"),
        "tenor": T, "T_opt": T_opt,
        "bond_floor": floor, "credit_rate": credit_rate(item.get("tcri"), a),
        "option_value": opt_value, "option_value_vanilla": opt_vanilla,
        "call_adjusted": bool(a.get("call_adjust", True)),
        "call_barrier_eff": call_barrier(K, hist_vol, a) / K if a.get("call_adjust", True) else None,
        "theoretical": theo, "issue_price": issue,
        "buy_price": buy_price, "buy_source": buy_source,
        "clearing_known": clearing_known, "pricing_method": item.get("pricing_method"),
        "auction_low": item.get("auction_low"), "auction_high": item.get("auction_high"),
        "edge_theo": theo - issue,
        "hist_vol": hist_vol, "implied_vol": iv,
        "iv_clearing": iv_clearing, "iv_market": iv_market, "iv_source": iv_source,
        "market_price": market_price, "premium_quote": premium_quote,
        "vol_edge": (hist_vol - iv) if iv else None,
        "delta": delta, "eff_delta": eff_delta, "gamma": gamma, "vega": vega,
        "cbas_premium": premium, "leverage": leverage,
        "max_loss_pct": 1.0,                 # 下檔最多賠光權利金 → 100%(但有限額)
        "scenarios": scen,
        "score": score, "score_reasons": reasons,
    }


def implied_vol(S, K, T, r, shares, floor, target_price, lo=0.05, hi=2.5, a=ASSUMPTIONS):
    """二分法解隱含波動率,使 floor + shares*選擇權(σ) = target_price。
    定價用與 analyze 同一個 option_px(含強贖上限),模型內部一致;
    強贖上限使選擇權價值有上界,價格太貴解不出 → 回 hi(誠實顯示極端隱波)。"""
    target_opt = (target_price - floor) / shares
    if target_opt <= 0:
        return None
    f = lambda s: option_px(S, K, T, s, r, a)[0] - target_opt
    flo, fhi = f(lo), f(hi)
    if flo > 0:        # 連最低波動都比目標貴 → 選擇權被高估,回最低
        return lo
    if fhi < 0:
        return hi
    for _ in range(80):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-6:
            return mid
        if fm > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def scenarios(item, spot, K, T, vol, r, shares, floor, premium, issue,
              moves=(-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30)):
    """股價情境 → 拆解部位(權利金本金)損益。
    持有部位 = 選擇權;到期前用 BS 重算選擇權市值,報酬 = (新選擇權值-權利金)/權利金。"""
    out = []
    # 假設情境是『短期內』股價變動,時間價值少掉一點(用 0.8*T 近似持有半年到一年後)
    T2 = max(T * 0.6, 0.25)
    base_opt = shares * option_px(spot, K, T2, vol, r)[0]
    for m in moves:
        s2 = spot * (1 + m)
        opt2 = shares * option_px(s2, K, T2, vol, r)[0]
        # 拆解部位損益:選擇權市值變化 / 權利金(下檔以權利金為限)
        pnl = opt2 - base_opt
        ret_on_prem = pnl / premium if premium > 0 else None
        # 若選擇權歸零,最大損失 = 權利金
        floored = max(opt2 - base_opt, -premium)
        out.append({
            "move": m, "spot": s2,
            "parity": s2 / K * 100.0,
            "option_value": opt2,
            "pnl_per_cb": floored,
            "return_on_premium": (floored / premium) if premium > 0 else None,
        })
    return out


def score_cb(item, m, a=ASSUMPTIONS):
    """0~100 拆解吸引力評分。權重:波動率價差30 + 理論edge20 + moneyness20 + 信用15 + 流動性10 + 可拆解日5。"""
    reasons = []
    score = 0.0

    # 1) 波動率價差(歷史 - 隱含):選擇權便宜 = 好  [30]
    ve = m.get("vol_edge")
    if ve is not None:
        s = max(0, min(30, 15 + ve * 100))   # +0.15 vol edge → 滿分
        score += s
        reasons.append(f"波動率價差 {ve*100:+.1f}pt → {s:.0f}/30")
    else:
        score += 12
        reasons.append("波動率價差無法估(發行價未知)→ 12/30")

    # 2) 理論 vs 發行 edge  [20]
    issue = m["issue"] or 100
    edge_pct = (m["theo"] - issue) / issue
    s = max(0, min(20, 10 + edge_pct * 200))  # +5% edge → 滿分
    score += s
    reasons.append(f"理論價較發行 {edge_pct*100:+.1f}% → {s:.0f}/20")

    # 3) moneyness 甜蜜點(delta 0.4~0.7 最佳)  [20]
    d = m["delta"]
    if 0.4 <= d <= 0.7:
        s = 20
    elif 0.25 <= d < 0.4 or 0.7 < d <= 0.85:
        s = 14
    elif d < 0.25:
        s = max(0, 10 * d / 0.25)             # 太價外 delta 小
    else:
        s = 10                                 # 太價內 像股票少了槓桿
    score += s
    reasons.append(f"Delta {d:.2f}(甜蜜點0.4~0.7)→ {s:.0f}/20")

    # 4) 信用 TCRI(低=好,易拆解)  [15]
    t = item.get("tcri") or 6
    s = max(0, min(15, (9 - t) / 8 * 15 + 2))
    score += s
    reasons.append(f"TCRI {t} → {s:.0f}/15")

    # 5) 流動性 / 發行量  [10]
    size = item.get("size_yi") or 0
    s = min(10, math.log10(max(size, 1) + 1) / math.log10(31) * 10)
    score += s
    reasons.append(f"發行量 {size}億 → {s:.0f}/10")

    # 6) 槓桿合理性(過高=過度價外風險,4~10x 佳)  [5]
    lev = m.get("leverage")
    if lev:
        if 4 <= lev <= 12:
            s = 5
        elif lev < 4:
            s = 3
        else:
            s = 2
        score += s
        reasons.append(f"槓桿 {lev:.1f}x → {s:.0f}/5")

    return round(score, 1), reasons
