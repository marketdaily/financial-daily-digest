"""本機小伺服器:服務儀表板 + 搜尋框後端。
  GET /                     → index.html(儀表板,含搜尋框)
  GET /api/analyze?code=&tcri=   → 該代碼完整分析卡(HTML 片段)
  GET /api/sim?capital=&code=&tcri= → 資金模擬結果(HTML 片段)
啟動:python3 cb_server.py [port]   預設 8911。"""
import os, sys, html, json, math, datetime, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cb_core, cb_data, cb_profiles, cb_intel, cb_simulate, cb_report, cb_ledger
import cb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = cb.load_db()
VW = lambda: (cb_core.ASSUMPTIONS["vol_w_short"], cb_core.ASSUMPTIONS["vol_w_long"])


def _fair_premium(a):
    """權利金合理上限 = 選擇權理論值 + 期間融資(=CB買在理論價時的權利金)。"""
    fin = a["bond_floor"] * cb_core.ASSUMPTIONS["asset_swap_spread"] * a["T_opt"]
    return a["option_value"] + fin


def _outlook(it, a, drift=0.07):
    """回 (be_S, be_move, p_touch, p_term, cal):回本點、所需漲幅、期間內曾觸及機率
    (v4 歷史校準點估計,cal 內含七年 regime 區間與判定下限)、抱到期仍過機率(保守下限)。"""
    strike, _ = cb_core.redemption_value(it.get("put"))
    K, spot, T, vol = it["conv_price"], a["spot"], a["T_opt"], a["hist_vol"]
    be_S = K * (strike + a["cbas_premium"]) / 100.0
    be_move = be_S / spot - 1
    p_raw = cb_core.touch_prob(spot, be_S, T, vol, drift)
    cal = cb_ledger.calibrate_touch(p_raw, spot, be_S, T, vol)
    p_touch = cal["p"]
    if be_S <= spot:
        p_term = 0.85
    else:
        d = (math.log(spot / be_S) + (drift - 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
        p_term = cb_core._norm_cdf(d)
    cb_ledger.record(it, a, be_S, p_touch, p_term,
                     extra={"p_touch_raw": p_raw, "p_lo": cal["lo"], "p_hi": cal["hi"],
                            "p_floor": cal["floor"], "calib": cal["method"]})
    return be_S, be_move, p_touch, p_term, cal


def _verdict_parts(it, a, be_move=None, p_touch=None, p_term=None, cal=None):
    """回 (tag, 顏色, 一句話, 怎麼做)。be_move=回本所需漲幅;p_touch/p_term=_outlook 的兩種機率;
    cal=v4 校準 dict——閘門一律用 floor(最差年份下限),不用點估計(回測鐵則:下限絕不高估)。"""
    elig, reasons = cb_core.eligibility(it)
    mv = (a["moneyness"] - 1) * 100
    where = f"價內 {mv:+.0f}%" if mv >= 0 else f"價外 {abs(mv):.0f}%"
    need = (be_move * 100) if be_move is not None else (abs(mv) + 8)
    if not elig:
        # 「查不到評等」≠「股票不好」:資料缺一格就補一格,不能講成不要碰
        size_ok = (it.get("size_yi") or 0) >= cb_core.ASSUMPTIONS["elig_min_size"]
        if it.get("tcri") is None and size_ok:
            return ("❓ 只缺信用評等(其他條件已過)", "#a5b4fc",
                    "免費資料查不到這檔的 TEJ TCRI 評等——這是資料缺一格,不是股票不好。"
                    "而且:若券商已經對這檔報過拆解權利金(老闆有在做)=銀行肯承作=信用事實上已達標。",
                    "把 TCRI 填進搜尋框旁的欄位再按一次分析;或跟我說評等,我記住以後就不用再填。下面的數字分析照樣能看。")
        return ("❌ 不要碰", "#f87171",
                "不符我們的進場準則(" + "、".join(reasons) + "),這檔不做。",
                "跳過這檔,看清單裡標「✅」的。")
    if mv < -18 or need > 45:
        # 深價外≠不能做:權利金合理+波動夠大 → 專業的「風險封頂選擇權注」,論組合注不論單壓
        fp = _fair_premium(a)
        p_gate = (cal or {}).get("floor") or p_touch  # 閘門用最差年份下限,寧可保守
        if p_gate and p_gate >= 0.35 and a["cbas_premium"] <= fp * 1.03:
            return ("🟡 組合可配一注(單壓不行)", "#fbbf24",
                    f"股價還在{where},死抱到期只有約 {(p_term or 0)*100:.0f}% 機率賺;"
                    f"但波動夠大,期間內有約 {p_touch*100:.0f}% 機率碰到回本點(+{need:.0f}%)——"
                    f"碰到就能帶著剩餘時間價值獲利出場,權利金也在合理值內、下檔封頂。"
                    f"這是專業的『風險封頂選擇權注』。",
                    f"組合裡配一小注(單檔 ≤10~15% 資金),進場同時設好出場紀律"
                    f"(股價接近回本點或權利金翻倍就走);想單壓全部資金的人跳過這檔。")
        return ("⚠️ 先別急,再等等", "#fbbf24",
                f"股價離轉換價很遠({where})、要漲約 +{need:.0f}% 才回本,"
                f"而且現在權利金報價偏貴或波動不夠大,勝算撐不起這個價。",
                "先觀望,或跟券商殺權利金;等股價靠近轉換價、或報價回到合理值再進。")
    if a["score"] >= 65 and mv >= -8:
        return ("✅ 可以拆解", "#34d399",
                f"條件不錯({where}),用一小筆權利金放大股票漲幅,而且最多就賠這筆權利金。",
                "可以進場。單一部位別壓太重(建議 ≤ 總資金兩三成),進場同時定好出場紀律。")
    if a["score"] >= 58:
        return ("✅ 可以拆解(等好價)", "#34d399",
                f"符合準則、條件 OK({where})。",
                "可以進場,但盡量等好一點的價位再出手。")
    return ("⚠️ 普通,可觀察", "#fbbf24",
            f"有符合準則但沒特別便宜({where})。",
            "先放觀察名單,等更便宜的權利金或股票波動變大再考慮。")


def _exit_plan(it, a, be_S, be_move):
    """出場劇本:分年觸及機率 + 出場價位表(股價→權利金約值→報酬→動作)+ 機械紀律 + 訊息差用法。"""
    K, spot, vol, T = it["conv_price"], a["spot"], a["hist_vol"], a["T_opt"]
    rf = cb_core.ASSUMPTIONS["rf"]
    prem, shares = a["cbas_premium"], a["shares"]
    T2 = max(T * 0.6, 0.5)                       # 假設中段持有,剩餘時間價值

    def mtm(S):
        return shares * cb_core.bs_call(S, K, T2, vol, rf)[0]

    # 權利金翻倍點(選擇權市值=2×成本的股價,二分求解)
    dbl = None
    lo, hi = spot, spot * 5
    if mtm(hi) >= 2 * prem:
        for _ in range(60):
            mid = (lo + hi) / 2
            if mtm(mid) >= 2 * prem:
                hi = mid
            else:
                lo = mid
        dbl = hi
    rows = []

    def add(name, S, act):
        v = mtm(S)
        rows.append((name, S, v, (v / prem - 1) if prem > 0 else 0, act))

    if dbl:
        add("權利金翻倍點", dbl, "賣一半——本金全部收回,剩下的部位零成本抱")
    add("回本點", be_S, "至少出一半,剩下改用移動停利(跌回 15% 就走)")
    r = cb_intel.research(it["stock_code"])
    tp = (r or {}).get("target_price")
    if tp and tp > spot:
        add("券商目標價", tp, "全出、或最多留 1/3——市場共識的頂到了")
    rows.sort(key=lambda x: x[1])
    trs = "".join(
        '<tr><td style="text-align:left">%s</td><td>%.0f(%+.0f%%)</td><td>%.1f</td>'
        '<td style="color:%s">%+.0f%%</td><td style="text-align:left">%s</td></tr>'
        % (n, S, (S / spot - 1) * 100, v, "#34d399" if pr >= 0 else "#f87171", pr * 100, act)
        for n, S, v, pr, act in rows)

    # 分年觸及機率(72% 那個數字拆成時間軸)
    yrs, seen = [], set()
    for y in (1.0, 2.0, T):
        y = min(y, T)
        k = round(y, 1)
        if k in seen:
            continue
        seen.add(k)
        py = cb_ledger.calibrate_touch(cb_core.touch_prob(spot, be_S, y, vol, 0.07),
                                       spot, be_S, y, vol)["p"]
        yrs.append((k, py))
    ytxt = " → ".join(f"{y:.1f}年內 <b>{p*100:.0f}%</b>" for y, p in yrs)

    return (
        '<div class="simwhy" style="margin-top:12px;border-top:1px solid rgba(255,255,255,.08);padding-top:10px">'
        '<span class="gg">🎯 出場劇本(什麼時候賣、賣多少)</span>'
        f'<div class="iline">碰到回本點的機率照時間拆:{ytxt}(波動大的股票,前段就有不小機會)</div>'
        '<table class="simtab"><tr><th style="text-align:left">賣點</th><th>股價(距現價)</th>'
        '<th>權利金約值</th><th>報酬</th><th style="text-align:left">建議動作</th></tr>'
        + trs + "</table>"
        '<div class="iline" style="margin-top:6px"><b>機械紀律(進場當天就寫死,不靠感覺):</b>'
        '①權利金市值翻倍→先賣一半收回本金 '
        '②股價碰回本點→至少出一半 '
        f'③到期/賣回日前 6 個月股價仍低於轉換價 8 折→全部出場(時間價值會加速歸零) '
        '④外資+投信同步連賣 10 日以上或公司下修展望→提前減碼</div>'
        '<div class="iline" style="color:#7dd3fc"><b>訊息差怎麼用:</b>'
        '每月 10 日前的月營收、法說會、財報是波動事件——「碰到回本點」最常發生在這些日子前後,'
        '事件前一週把出場單價位掛好;本卡的「法人現在」每天更新,翻買=先行訊號、連賣=提前減碼訊號。'
        '把持倉寫進 holdings.json,首頁「今日結論」就會每天自動盯這些出場條件。</div>'
        '</div>')


def _human_card(it, sd, a):
    """白話卡:先結論、白話重點、怎麼做;技術數字收進 <details>。"""
    prem = a["cbas_premium"]
    spot = a["spot"]
    T = a["T_opt"]
    be_S, be_move, p_touch, p_term, cal = _outlook(it, a)
    tag, col, oneliner, action = _verdict_parts(it, a, be_move, p_touch, p_term, cal)
    lev = a.get("leverage") or 0
    src = a["buy_source"]
    if a.get("premium_quote"):
        price_note = "(已用券商報你的權利金,零誤差)"
    elif a.get("market_price"):
        price_note = "(已用你帶入的 CB 現價,零誤差)"
    else:
        price_note = "(推估;拿到券商權利金報價後填「進階選填」=零誤差)"

    fp = _fair_premium(a)
    fp_gap = fp - prem
    if src.startswith("面額"):
        # 推估基準=面額100 時,「便宜 X」是失真比較,不給貴俗判定
        fair_txt = (f'權利金 <b>{fp:.1f} 以內</b>(約 NT${fp*1000:,.0f}/張)才划算。'
                    f'目前的 {prem:.1f} 是推估——拿到券商報價,填進「進階選填」再比')
    else:
        fair_txt = (f'權利金 <b>{fp:.1f} 以內</b>(約 NT${fp*1000:,.0f}/張)才划算。'
                    + (f'目前 {prem:.1f},比上限便宜 {fp_gap:.1f} ✓'
                       if fp_gap >= 0 else
                       f'目前 {prem:.1f},<b style="color:#f87171">貴了 {abs(fp_gap):.1f}</b>——殺價,殺不動就不做'))
    bullets = [
        ("買一張要付", f'<b>約 NT${prem*1000:,.0f}</b>——這也是<b>最多賠的錢</b>,不會賠更多(債券部分銀行扛){price_note}'),
        ("出價上限", fair_txt),
        ("要開始賺", f'股票要從 {spot:.1f} 漲到 <b>{be_S:.1f}</b>(約 <b>{be_move*100:+.0f}%</b>)'),
        ("中途獲利機率", f'<b>約 {p_touch*100:.0f}%</b>'
         + (f'(市況好壞年份約 {cal["lo"]*100:.0f}~{cal["hi"]*100:.0f}%,判定用保守下限 {cal["floor"]*100:.0f}%)'
            if cal.get("lo") else "")
         + f'——{T:.1f} 年內股價碰到回本點就能獲利出場。<b>實戰看這個</b>'
         + ('<br><span style="color:#94a3b8;font-size:11px">已用 2019-25 台股 CB 族群 6.6 萬筆歷史回測校準'
            '(舊版公式全期系統性低估)</span>' if cal.get("method") == "empirical_band_v4" else "")),
        ("死抱到期仍賺", f'約 {p_term*100:.0f}%(死抱不動的保守下限)'),
        ("槓桿", f'用 NT${prem*1000:,.0f} 控制約 NT${a["parity"]*1000:,.0f} 的股票曝險(約 {lev:.1f} 倍)'),
    ]
    if it.get("tcri_src") == "override":
        bullets.append(("信用評等", f'TCRI {it["tcri"]}(推定)——{html.escape(it.get("tcri_note", ""))}'))
    fn = cb_intel.flow_narrative(it["stock_code"])
    if fn:
        bullets.append(("法人現在", fn.replace("法人流向:", "")))
    r = cb_intel.research(it["stock_code"])
    if r and r.get("target_price"):
        up = (r["target_price"] / spot - 1) * 100
        bullets.append(("券商看", f'目標價 {r["target_price"]}'
                        + (f'(還有 +{up:.0f}% 空間)' if up > 0 else f'(已超過目標 {abs(up):.0f}%)')))

    lis = "".join(f'<li><span class="k">{k}</span><span class="v">{v}</span></li>' for k, v in bullets)
    return (
        f'<div class="hcard">'
        f'<span class="hname">{html.escape(it["name"])}</span>'
        f'<span class="hcode">股 {it["stock_code"]} · 債 {it["bond_code"]} · {it.get("collateral","")} · 報價 {sd.get("date","")}</span>'
        f'<div class="verdict" style="color:{col};background:{col}1e;border:1px solid {col}55">{tag}</div>'
        f'<div class="hone">{html.escape(oneliner)}</div>'
        f'<ul class="hbul">{lis}</ul>'
        f'<div class="haction"><b>怎麼做:</b>{html.escape(action)}</div>'
        f'{_exit_plan(it, a, be_S, be_move)}'
        f'<details class="tech"><summary></summary><div class="cards">{cb_report._card(it, sd, a)}</div></details>'
        f'</div>')


def _holdings():
    try:
        with open(os.path.join(HERE, "holdings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _holdings_section():
    """持倉監控:每檔算現估值+檢查出場條件,觸發就亮警示。"""
    hold = _holdings()
    if not hold:
        return ('<div class="bone" style="margin-top:10px">💼 想讓系統每天盯「什麼時候賣」:'
                '把持倉寫進 cb_analyzer/<b>holdings.json</b>(格式見 holdings.example.json),'
                '這裡就會自動顯示每檔的出場警示(翻倍賣半/碰回本點/時間價值臨界/法人轉賣)。</div>')
    out = ['<div class="bhead" style="margin-top:14px">💼 持倉監控(每天自動盯出場條件)</div>']
    for h in hold:
        r, e = _resolve(str(h.get("code", "")), h.get("tcri"))
        if not r:
            out.append(f'<div class="bone">⚠ {html.escape(str(h.get("code")))}:{html.escape(e)}</div>')
            continue
        it, sd, a = r
        prem_paid = h.get("prem_paid")
        units = h.get("units") or 0
        mtm = a["option_value"]                       # 理論市值(per100)近似
        alerts = []
        pr_txt = ""
        if prem_paid:
            pr = mtm / prem_paid - 1
            pr_txt = f'成本 {prem_paid} → 現估 {mtm:.1f}(<b style="color:{"#34d399" if pr>=0 else "#f87171"}">{pr*100:+.0f}%</b>)'
            strike, _ = cb_core.redemption_value(it.get("put"))
            be_entry = it["conv_price"] * (strike + prem_paid) / 100.0
            if mtm >= 2 * prem_paid:
                alerts.append("🔔 權利金已約翻倍 → 賣一半收回本金")
            if a["spot"] >= be_entry:
                alerts.append(f"🔔 已碰你的回本點({be_entry:.0f})→ 至少出一半")
        if a["T_opt"] < 0.5 and a["moneyness"] < 0.8:
            alerts.append("🔔 剩不到半年仍深價外 → 出場,別讓時間價值歸零")
        fn = cb_intel.flow_narrative(it["stock_code"]) or ""
        if "賣超" in fn:
            alerts.append("⚠ 法人賣超中 → 留意,連賣拉長就減碼")
        status = "、".join(alerts) if alerts else "✅ 續抱,未觸發出場條件"
        scolor = "#f87171" if any(x.startswith("🔔") for x in alerts) else ("#fbbf24" if alerts else "#34d399")
        out.append(
            '<div class="brow" onclick="quick(\'%s\')">'
            '<span class="bnm">%s</span><span class="bfair">%d 張 %s</span>'
            '<span class="bone" style="color:%s">%s</span></div>'
            % (it["bond_code"], html.escape(it["name"]), units, pr_txt, scolor, html.escape(status)))
    return "".join(out)


def brief_fragment():
    """今日結論:老闆一打開就看到——哪幾檔能拆、出價上限多少、哪幾檔在等定價。"""
    A = cb_core.ASSUMPTIONS
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    go, mix, wait, rows = 0, 0, 0, []
    qdate = ""
    for it in DB["items"]:
        if not (it.get("conv_price") and it.get("premium_mid")):
            continue
        if not cb_core.eligibility(it)[0]:
            continue
        sd = cb_data.get_stock(it["stock_code"], vol_weights=VW())
        if not sd:
            continue
        qdate = sd.get("date") or qdate
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"])
        if not a.get("ok"):
            continue
        be_S, be_move, p_touch, p_term, cal = _outlook(it, a)
        tag, col, one, _act = _verdict_parts(it, a, be_move, p_touch, p_term, cal)
        if tag.startswith("✅"):
            go += 1
        elif tag.startswith("🟡"):
            mix += 1
        else:
            wait += 1
        rows.append(
            '<div class="brow" onclick="quick(\'%s\')" title="點我看完整分析">'
            '<span class="btag" style="color:%s;background:%s1a;border-color:%s55">%s</span>'
            '<span class="bnm">%s</span>'
            '<span class="bfair">權利金上限 <b>%.1f</b>(約 NT$%s/張)——券商報這以內才接</span>'
            '<span class="bone">%s</span></div>'
            % (it["bond_code"], col, col, col, html.escape(tag),
               html.escape(it["name"]), _fair_premium(a),
               f"{_fair_premium(a)*1000:,.0f}", html.escape(one)))
    watch = [i for i in DB["items"]
             if (not i.get("conv_price") or not i.get("premium_mid"))
             and i.get("tcri") in A["elig_tcri"] and (i.get("size_yi") or 0) >= A["elig_min_size"]]
    watch.sort(key=lambda i: -(i.get("size_yi") or 0))
    wnames = "、".join(f'{html.escape(i["name"])}({i["stock_code"]})' for i in watch)
    if go:
        head = f'今天有 <b style="color:#34d399">{go} 檔可以進場拆解</b>'
        if mix:
            head += f',{mix} 檔可用組合小注參與'
        head += f',另外 {wait} 檔建議再等。' if wait else '。'
    elif mix:
        head = (f'今天有 <b style="color:#fbbf24">{mix} 檔可以用「組合配一小注」的方式參與</b>'
                f'(權利金合理、期間內碰回本點機率夠;單壓全部資金不行,見下)'
                + (f',另外 {wait} 檔建議再等。' if wait else '。'))
    elif rows:
        head = (f'今天<b>沒有建議直接進場的標的</b>——{wait} 檔符合準則但時機不對(見下),'
                f'先不動作也是一種決定。')
    else:
        head = '目前沒有已定價且符合準則的案件。'
    if watch:
        head += (f' 另有 <b style="color:#a5b4fc">{len(watch)} 檔符合準則、正在等承銷定價</b>:'
                 f'{wnames} —— 定價一公布,輸入代碼馬上出結論。')
    return (
        '<div class="bhead">📌 今日結論　<span class="bsub">報價日 %s · 產生於 %s · 準則:TCRI 3-4 且 ≥10億</span></div>'
        '<div class="blead">%s</div>%s%s'
        % (qdate or "—", now, head, "".join(rows), _holdings_section()))


def _sim_verdict(base):
    """(tag, color, 一句白話) — 資金/組合模擬共用的先結論。"""
    pp = base["prob_profit"]
    p50 = base["p50"]
    dep = base["deployed"]
    if pp < 0.25:
        return ("❌ 不建議這樣買", "#f87171",
                f"最可能的結果(中位數)是 NT${p50:+,.0f},賺錢機率只有 {pp*100:.0f}%——"
                f"這樣配比較像賭運氣,不像投資。")
    if base["exp_pnl"] > 0 and pp >= 0.45:
        return ("✅ 這樣買可以", "#34d399",
                f"賺錢機率 {pp*100:.0f}%、預期賺 NT${base['exp_pnl']:+,.0f},"
                f"最壞情況也只賠投入的 NT${dep:,.0f}(權利金),風險有底。")
    return ("⚠️ 普通,想清楚再進", "#fbbf24",
            f"賺錢機率 {pp*100:.0f}%、最可能結果 NT${p50:+,.0f}——不算差但也不便宜,"
            f"可以等更好的價位或標的。")


def analyze_fragment(code, tcri=None, prem=None, cbprice=None):
    hits = cb.find(DB, code)
    if tcri:
        for it in hits:
            it["tcri"] = tcri
    if not hits:
        return '<div class="serr">找不到「%s」。試股票碼(5289)、債券碼(52892/11011)或公司名。</div>' % html.escape(code)
    cards = []
    for it in hits[:8]:
        if not it.get("conv_price"):
            cards.append(cb_report._watch_card(it))
            continue
        sd = cb_data.get_stock(it["stock_code"], vol_weights=VW())
        if not sd:
            cards.append('<div class="serr">%s(%s):抓不到現股報價,略過。</div>'
                         % (html.escape(it["name"]), it["stock_code"]))
            continue
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"],
                            market_price=cbprice, premium_quote=prem)
        if a.get("ok"):
            cards.append(_human_card(it, sd, a))
    return "".join(cards)


def _why_grow_html(code, spot):
    p = cb_profiles.get_profile(code)
    bits = []
    if p.get("curated"):
        if p.get("business"):
            bits.append(html.escape(p["business"]))
        if p.get("downstream"):
            bits.append("下游:" + html.escape(p["downstream"]))
        if p.get("note"):
            bits.append("題材/地位:" + html.escape(p["note"]))
    else:
        bits.append("產業:" + html.escape(p.get("industry") or "—"))
    out = '<div class="simwhy"><span class="gg">📈 為什麼會漲:</span>' + "　".join(bits)
    for ln in cb_intel.intel_lines(code, spot):
        out += '<div class="iline">· ' + html.escape(ln) + "</div>"
    return out + "</div>"


def sim_fragment(capital, code=None, tcri=None, drift=0.07, cbprice=None, prem=None):
    """cbprice=你實際能買到的 CB 價(常是 103、104,不會是 100);prem=券商權利金報價。
    兩者只在有指定代碼時套用(全市場掃描不能一價套全部)。"""
    cap = cb._parse_capital(capital)
    if not cap:
        return '<div class="serr">本金格式看不懂,例如 50萬、1000萬、5000000。</div>'
    codes = [code] if code else None
    hits = []
    if codes:
        for c in codes:
            hits += cb.find(DB, c)
    else:
        hits = [i for i in DB["items"]
                if i.get("conv_price") and i.get("premium_mid") and cb_core.eligibility(i)[0]]
    if tcri:
        for it in hits:
            it["tcri"] = tcri
    cands = []
    for it in hits:
        if not it.get("conv_price"):
            continue
        sd = cb_data.get_stock(it["stock_code"], vol_weights=VW())
        if not sd:
            continue
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"],
                            market_price=cbprice if code else None,
                            premium_quote=prem if code else None)
        if a.get("ok"):
            cands.append((it, a))
    if not cands:
        return ('<div class="serr">找不到可模擬標的。輸入代碼指定(現有CB請帶 TCRI),'
                '或留空用符合準則者。</div>')
    single = cap < 1_000_000 or len(cands) == 1
    if single:
        cands = sorted(cands, key=lambda x: x[1]["score"], reverse=True)[:1]
    scen = cb_simulate.multi_drift(cands, cap, base_drift=drift)
    base = next((r for r in scen if r["ok"] and abs(r["drift"] - drift) < 1e-9), None)
    if not base or not base["ok"]:
        return '<div class="serr">%s</div>' % html.escape((base or {}).get("reason", "本金不足買進任一口"))

    o = ['<div class="simbox"><h3>💰 資金模擬　本金 NT$%s　(%s)</h3>'
         % (f"{cap:,.0f}", "小資單押" if single else "分散投組")]
    vt, vc, vone = _sim_verdict(base)
    o.append('<div class="verdict" style="color:%s;background:%s1e;border:1px solid %s55">%s</div>'
             '<div class="hone">%s</div>' % (vc, vc, vc, html.escape(vt), html.escape(vone)))
    o.append('<div class="simrow">白話總結:拿出 <b>NT$%s</b>(剩 NT$%s 現金)→ 抱約 <b>%.1f 年</b> → '
             '最好賺 NT$%s(前5%%)、最壞賠光投入的 NT$%s、賺錢機率 <b>%.0f%%</b>。</div>'
             % (f"{base['deployed']:,.0f}", f"{max(base['cash_left'],0):,.0f}", base["horizon"],
                f"{base['p95']:+,.0f}", f"{base['deployed']:,.0f}", base["prob_profit"] * 100))
    for L in base["legs"]:
        it = L["item"]
        oob = (L["spot"] / L["K"] - 1) * 100
        bey = ("約 %.1f 年" % L["be_years"]) if L["be_years"] else "中位數到不了(需高於預期漲勢)"
        la = L["a"]
        o.append('<div class="simrow"><b>▶ 買進 %s(股%s/債%s)</b>　%d 口 = NT$%s　現價 %.1f / 轉換價 %s　'
                 'CB 買價 <b>%.1f</b>(%s)→ 權利金 %.1f/張</div>'
                 % (html.escape(it["name"]), it["stock_code"], it["bond_code"],
                    L["units"], f"{L['deployed']:,.0f}", L["spot"], L["K"],
                    la["buy_price"], la["buy_source"], L["premium"]))
        o.append(_why_grow_html(it["stock_code"], L["spot"]))
        why = ('<div class="simwhy"><span class="yy">⏳ 為什麼要等:</span>現價距轉換價 %+.0f%%;'
               '要獲利股票需漲 +%.0f%%(到 %.1f);以前瞻波動 %.0f%% 估,%s才到回本點' %
               (oob, L["be_move"] * 100, L["be_S"], L["vol"] * 100, bey))
        r = cb_intel.research(it["stock_code"])
        if r and r.get("target_price"):
            tup = (r["target_price"] / L["spot"] - 1) * 100
            if tup < L["be_move"] * 100:
                why += ('<div class="iline"><span class="rr">⚠ 現實檢查:券商目標僅隱含 %+.0f%% &lt; 回本所需 +%.0f%% '
                        '→ 即使達標仍回不了本,不適合單押,宜換近價平標的</span></div>' % (tup, L["be_move"] * 100))
        why += '</div>'
        o.append(why)
        o.append('<div class="simrow"><span class="yy">⌛ 死抱到期 %.1f 年　獲利機率 <b>%.0f%%</b>(保守下限)</span>　'
                 '下檔最多賠光權利金 NT$%s</div>'
                 % (L["T"], L["prob_profit"] * 100, f"{L['deployed']:,.0f}"))
        cal_leg = cb_ledger.calibrate_touch(
            cb_core.touch_prob(L["spot"], L["be_S"], L["T"], L["vol"], drift),
            L["spot"], L["be_S"], L["T"], L["vol"])
        band_txt = ("(好壞年份 %.0f~%.0f%%)" % (cal_leg["lo"] * 100, cal_leg["hi"] * 100)
                    if cal_leg.get("lo") else "")
        o.append('<div class="simrow"><span class="gg">⚡ 實戰口徑:</span>期間內股價<b>曾碰到</b>回本點的機率約 '
                 '<b>%.0f%%</b>%s——碰到就能帶著剩餘時間價值獲利出場,不必等到期(專業做法)</div>'
                 % (cal_leg["p"] * 100, band_txt))

    o.append('<table class="simtab"><tr><th>情境(股票年報酬)</th><th>預期賺賠</th><th>年化</th><th>賺錢機率</th></tr>')
    for rr in scen:
        if not rr["ok"]:
            continue
        col = "#34d399" if rr["exp_pnl"] > 0 else "#f87171"
        o.append('<tr><td style="text-align:left">%s(%.0f%%)</td>'
                 '<td style="color:%s">NT$%s</td><td>%.0f%%</td><td>%.0f%%</td></tr>'
                 % (rr["drift_label"], rr["drift"] * 100, col, f"{rr['exp_pnl']:+,.0f}",
                    rr["ann_return"] * 100, rr["prob_profit"] * 100))
    o.append("</table>")
    o.append('<div class="iline" style="margin-top:8px">基準分佈:悲觀(P5) NT$%s · 中位 NT$%s · 樂觀(P95) NT$%s｜'
             '假設 GBM+前瞻波動+相關ρ%.2f,下檔封頂權利金,未計稅費。'
             '注意:表格全部是「死抱到期」的保守口徑;實戰可在期間內碰到回本點時獲利出場(機率見各檔⚡),'
             '且台灣 CB 發行方常有把股價推過轉換價的動機(轉股免還債),隨機漫步假設整體偏保守。</div>'
             % (f"{base['p5']:+,.0f}", f"{base['p50']:+,.0f}", f"{base['p95']:+,.0f}", base["rho"]))
    o.append("</div>")
    return "".join(o)


def _resolve(code, tcri=None, cbprice=None, prem=None):
    """代碼 → (item, sd, a)。cbprice=CB 現價;prem=券商報的拆解後權利金(我們實際買的,優先)。"""
    hits = cb.find(DB, code)
    it = next((h for h in hits if h.get("conv_price")), None)
    if not it:
        return None, "找不到或條件未定"
    if tcri:
        it["tcri"] = tcri
    sd = cb_data.get_stock(it["stock_code"], vol_weights=VW())
    if not sd:
        return None, "抓不到現股報價"
    a = cb_core.analyze(it, sd["spot"], sd["vol_blend"], market_price=cbprice, premium_quote=prem)
    return (it, sd, a), None


def price_fragment(code, tcri=None, cbprice=None, prem_q=None):
    r, e = _resolve(code, tcri, cbprice, prem_q)
    if not r:
        return '<div class="serr">%s:%s</div>' % (html.escape(code), e)
    it, sd, a = r
    src = a["buy_source"]
    prem = a["cbas_premium"]
    return (
        '<div class="simbox"><h3>📈 %s(股%s/債%s)現價與拆解基準</h3>'
        '<div class="simrow"><b>現股價 %.2f</b>(%s,即時)　轉換價 %s　'
        '<b>parity %.1f</b>(%s)</div>'
        '<div class="simrow">債券底 %.1f　CB 合理價 %.1f　<b>權利金上限 %.1f</b>——券商報這以內才接　目前權利金 <b>%.1f</b>(NT$%s)　槓桿 %.1f×</div>'
        '<div class="iline">買價基準:<b>%s</b>%s</div>'
        '<div class="iline" style="color:#7dd3fc">要零誤差:我們買的是拆解後的權利金端——券商報權利金給你時,'
        '填進「權利金報價」欄(組合的每檔也可以填),整套就用真實報價算。</div></div>'
        % (html.escape(it["name"]), it["stock_code"], it["bond_code"],
           sd["spot"], sd["date"], it["conv_price"],
           a["parity"], "價內" if a["moneyness"] > 1 else "價外",
           a["bond_floor"], a["theoretical"], _fair_premium(a), prem, f"{prem*1000:,.0f}",
           a["leverage"] or 0,
           src, ("(券商權利金 %.1f)" % prem_q) if prem_q else
                (("(你帶入 %.1f)" % cbprice) if cbprice else "(未帶報價,為估計值)")))


def _parse_legs(s):
    """'5289:3:126:3:39,…' → [(code, units, cbprice, tcri, prem)]。欄位:代碼:張數:CB現價:TCRI:權利金報價。"""
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        f = (part.split(":") + ["", "", "", ""])[:5]
        code = f[0].strip()
        try:
            units = int(float(f[1])) if f[1].strip() else 0
        except ValueError:
            units = 0
        cbp = float(f[2]) if f[2].strip() else None
        tc = int(f[3]) if f[3].strip() else None
        pr = float(f[4]) if f[4].strip() else None
        if code and units > 0:
            out.append((code, units, cbp, tc, pr))
    return out


def portfolio_fragment(legs_str, drift=0.07):
    legs = _parse_legs(legs_str or "")
    if not legs:
        return '<div class="serr">組合是空的。格式:代碼:張數(可加 CB現價、TCRI)。</div>'
    triples, rows, bad = [], [], []
    for code, units, cbp, tc, pr in legs:
        r, e = _resolve(code, tc, cbp, pr)
        if not r:
            bad.append("%s(%s)" % (code, e))
            continue
        it, sd, a = r
        triples.append((it, a, units))
        rows.append((it, sd, a, units, cbp))
    if not triples:
        return '<div class="serr">組合都查不到:%s</div>' % html.escape("、".join(bad))
    scen = cb_simulate.multi_drift_explicit(triples, base_drift=drift)
    base = next((x for x in scen if x["ok"] and abs(x["drift"] - drift) < 1e-9), None)
    if not base or not base["ok"]:
        return '<div class="serr">%s</div>' % html.escape((base or {}).get("reason", "模擬失敗"))
    pm = {id(L["item"]): L for L in base["legs"]}

    o = ['<div class="simbox"><h3>💼 組合模擬(你指定張數)</h3>']
    vt, vc, vone = _sim_verdict(base)
    o.append('<div class="verdict" style="color:%s;background:%s1e;border:1px solid %s55">%s</div>'
             '<div class="hone">%s</div>' % (vc, vc, vc, html.escape(vt), html.escape(vone)))
    o.append('<div class="simrow">白話總結:這組要拿出 <b>NT$%s</b> → 抱約 <b>%.1f 年</b> → '
             '最好賺 NT$%s(前5%%)、最壞賠光 NT$%s、賺錢機率 <b>%.0f%%</b>。</div>'
             % (f"{base['deployed']:,.0f}", base["horizon"],
                f"{base['p95']:+,.0f}", f"{base['deployed']:,.0f}", base["prob_profit"] * 100))
    o.append('<table class="simtab"><tr><th style="text-align:left">標的</th><th>張數</th>'
             '<th title="你填的實際買入價;未填=推估">買入價</th><th>權利金/張</th><th>投入</th>'
             '<th title="死抱到期的保守下限">到期獲利機率</th>'
             '<th title="期間內曾碰到回本點=可帶時間價值提前獲利出場;實戰看這個">中途獲利機率</th>'
             '<th>預期損益(到期)</th></tr>')
    for it, sd, a, units, cbp in rows:
        L = pm.get(id(it))
        exp = f"{L['exp_pnl']:+,.0f}" if L else "—"
        pp = f"{L['prob_profit']*100:.0f}%" if L else "—"
        pt = (f"{cb_ledger.calibrate_touch(cb_core.touch_prob(L['spot'], L['be_S'], L['T'], L['vol'], drift), L['spot'], L['be_S'], L['T'], L['vol'])['p']*100:.0f}%"
              if L else "—")
        col = "#34d399" if (L and L["exp_pnl"] > 0) else "#f87171"
        o.append('<tr><td style="text-align:left">%s<br><span style="color:#8b95a7;font-size:11px">股%s/債%s</span></td>'
                 '<td>%d</td><td>%s%s</td><td>%.1f</td><td>NT$%s</td><td>%s</td>'
                 '<td style="color:#34d399;font-weight:700">%s</td>'
                 '<td style="color:%s">NT$%s</td></tr>'
                 % (html.escape(it["name"]), it["stock_code"], it["bond_code"], units,
                    ("%.1f" % cbp) if cbp else a["buy_source"], "",
                    a["cbas_premium"],
                    f"{L['deployed']:,.0f}" if L else "—", pp, pt, col, exp))
    o.append("</table>")
    if bad:
        o.append('<div class="iline" style="color:#f87171">略過查不到的:%s</div>' % html.escape("、".join(bad)))

    o.append('<div class="simrow" style="margin-top:10px"><b>組合合計投入 NT$%s</b>　'
             '抱到期約 %.1f 年　整體獲利機率 <b>%.0f%%</b></div>'
             % (f"{base['deployed']:,.0f}", base["horizon"], base["prob_profit"] * 100))
    o.append('<table class="simtab"><tr><th style="text-align:left">情境(股票年報酬)</th>'
             '<th>整組預期損益</th><th>年化</th><th>獲利機率</th></tr>')
    for rr in scen:
        if not rr["ok"]:
            continue
        col = "#34d399" if rr["exp_pnl"] > 0 else "#f87171"
        o.append('<tr><td style="text-align:left">%s(%.0f%%)</td><td style="color:%s">NT$%s</td>'
                 '<td>%.0f%%</td><td>%.0f%%</td></tr>'
                 % (rr["drift_label"], rr["drift"] * 100, col, f"{rr['exp_pnl']:+,.0f}",
                    rr["ann_return"] * 100, rr["prob_profit"] * 100))
    o.append("</table>")
    o.append('<div class="iline" style="margin-top:8px">基準分佈:悲觀(P5) NT$%s · 中位 NT$%s · 樂觀(P95) NT$%s｜'
             '下檔封頂於權利金合計 NT$%s(債券底歸銀行)。填了「權利金報價」的腿=零誤差(CB現價次之),未填=以承銷/面額推估。'
             '表格為「死抱到期」保守口徑;實戰可在期間內碰到回本點時帶時間價值獲利出場,真實勝率高於表列。</div>'
             % (f"{base['p5']:+,.0f}", f"{base['p50']:+,.0f}", f"{base['p95']:+,.0f}",
                f"{base['deployed']:,.0f}"))
    o.append("</div>")
    return "".join(o)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        g = lambda k: (qs.get(k, [None])[0])
        try:
            if u.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                    return self._send(200, f.read())
            if u.path == "/api/brief":
                return self._send(200, brief_fragment())
            if u.path == "/api/analyze":
                tc = g("tcri"); pr = g("prem"); cp = g("cbprice")
                return self._send(200, analyze_fragment(g("code") or "", int(tc) if tc else None,
                                                        float(pr) if pr else None,
                                                        float(cp) if cp else None))
            if u.path == "/api/sim":
                tc = g("tcri"); cp = g("cbprice"); pr = g("prem")
                return self._send(200, sim_fragment(g("capital") or "", g("code"),
                                                    int(tc) if tc else None,
                                                    cbprice=float(cp) if cp else None,
                                                    prem=float(pr) if pr else None))
            if u.path == "/api/price":
                tc = g("tcri"); cp = g("cbprice"); pr = g("prem")
                return self._send(200, price_fragment(g("code") or "", int(tc) if tc else None,
                                                      float(cp) if cp else None,
                                                      float(pr) if pr else None))
            if u.path == "/api/portfolio":
                dr = g("drift")
                return self._send(200, portfolio_fragment(g("legs") or "",
                                                          float(dr) if dr else 0.07))
            # 其他:當靜態檔(report.html 等)
            p = os.path.join(HERE, u.path.lstrip("/"))
            if os.path.isfile(p) and os.path.realpath(p).startswith(HERE):
                ct = "image/png" if p.endswith(".png") else "text/html; charset=utf-8"
                with open(p, "rb") as f:
                    return self._send(200, f.read(), ct)
            self._send(404, '<div class="serr">404</div>')
        except Exception as e:
            self._send(500, '<div class="serr">伺服器錯誤:%s</div>' % html.escape(str(e)))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8911
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print(f"CB 分析伺服器 → http://localhost:{port}/  (Ctrl+C 停)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
