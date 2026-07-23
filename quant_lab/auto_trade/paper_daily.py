"""Paper 前測日跑器(winrig cron 每晚執行;僅 FinMind 免費源,不需 Shioaji):
- 魚B 外資高信念跟隨:|Δ淨OI|≥85分位(擴張窗,只用過去)→ 次日開→收,成本1.5點
- 魚A 條件賣跨式:IV−EWMA>3% 且 10≤dte≤40 且 GEX≥近60日中位 → 賣ATM跨式;
  出場=edge<1%/持有≥5天/mark>1.5×進場/換月,成本4.4點(價差+費稅雙腿來回)
狀態 .paper/state.json;帳本 .paper/ledger.jsonl(事件流,唯一真源)。
這是兩條魚的「真 OOS 裁決」:訊號規格 2026-07-17 凍結,不得再調參。
用法:python3 paper_daily.py
"""
import os
import json
import datetime

import urllib.request

import tx_data
import txo_data
from foreign_flow_study import fetch_foreign
from gex_study import build_gex
from txo_vol_wf import ewma_vol_by_date, straddle

HERE = os.path.dirname(os.path.abspath(__file__))
PDIR = os.path.join(HERE, ".paper")
STATE = os.path.join(PDIR, "state.json")
LEDGER = os.path.join(PDIR, "ledger.jsonl")
LOG_LIVE = os.path.join(PDIR, "live_log.txt")
COST_B = 3.3   # 台指期真實來回:期交稅1.83點(法定0.002%x2)+五折手續費~0.5點+價差~1點
COST_A = 4.4
START_EQUITY = 3_000_000            # 虛擬本金(用戶實際資金規模)
PV = {"A": 50, "B": 50, "C": 50, "E": 50}  # 小台1口/跨式1組,皆每點NT$50
HARD_DD = 0.20                      # 回撤煞車:權益回撤≥20% 停開新倉(人工複核)
ALERT_URL = "https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push"


def push(msg):
    """web push 到用戶手機(走 MarketDaily alert-worker,token 在 .env)。失敗靜默。"""
    from shioaji_adapter import _load_env
    _load_env()
    tok = os.environ.get("MARKETDAILY_ALERT_TOKEN") or os.environ.get("ALERT_TOKEN")
    if not tok:
        return
    try:
        req = urllib.request.Request(ALERT_URL,
            data=json.dumps({"message": msg[:4900]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def log_ev(ev):
    ev["logged_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    print(" ", json.dumps(ev, ensure_ascii=False, default=str))


def realize(st, fish, pnl_pts, ev):
    ev["pnl_pts"] = round(pnl_pts, 1)
    ev["pnl_ntd"] = round(pnl_pts * PV[fish])
    st["equity"] = st.get("equity", START_EQUITY) + ev["pnl_ntd"]
    st["peak"] = max(st.get("peak", START_EQUITY), st["equity"])
    ev["equity"] = st["equity"]
    log_ev(ev)
    names = {"A": "賣跨式", "B": "外資跟隨", "C": "ORB順勢當沖", "E": "高波動fade當沖"}
    dd = 1 - st["equity"] / st["peak"]
    push(f"📒 paper {names.get(fish, fish)} {ev.get('date','')} "
         f"{'獲利' if ev['pnl_ntd']>=0 else '虧損'} {ev['pnl_ntd']:+,} 元"
         f"|權益 {st['equity']:,.0f}({st['equity']/START_EQUITY-1:+.1%})"
         + (f"|⚠️回撤{dd:.0%}" if dd >= 0.05 else ""))
    if dd >= HARD_DD:
        push(f"⛔ paper 回撤煞車觸發({dd:.0%}):停開新倉,需人工複核")


def halted(st):
    dd = 1 - st.get("equity", START_EQUITY) / st.get("peak", START_EQUITY)
    return dd >= HARD_DD, dd


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fishB": {"pending": None}, "fishA": {"held": None},
                "equity": START_EQUITY, "peak": START_EQUITY}


def main():
    os.makedirs(PDIR, exist_ok=True)
    st = load_state()
    bars = tx_data.load("2020-01-01", refresh=True)
    by_date = {b["date"]: b for b in bars}
    today = bars[-1]["date"]
    print(f"paper_daily @ {today}")

    # ---- 魚B:先結算,再產訊號 ----
    pend = st["fishB"]["pending"]
    if pend and today > pend["signal_date"]:
        b = bars[-1] if bars[-1]["date"] > pend["signal_date"] else None
        # 執行日=訊號日後第一個交易日(當前最後一根若比訊號日新,即為執行日)
        exec_bar = next((x for x in bars if x["date"] > pend["signal_date"]), None)
        if exec_bar:
            pnl = pend["side"] * (exec_bar["close"] - exec_bar["open"]) - COST_B
            realize(st, "B", pnl, {"fish": "B", "type": "fill+close",
                    "signal_date": pend["signal_date"], "exec_date": exec_bar["date"],
                    "side": pend["side"]})
            st["fishB"]["pending"] = None
    net = fetch_foreign()
    ds = sorted(d for d in net if d in by_date)
    stop_all, dd_now = halted(st)
    if stop_all:
        print(f"  ⛔ 回撤煞車:權益回撤 {dd_now:.0%} ≥ {HARD_DD:.0%},停開新倉")
    if ds and ds[-1] == today and st["fishB"]["pending"] is None and not stop_all:
        deltas = [net[ds[i]] - net[ds[i - 1]] for i in range(1, len(ds))]
        d_today = deltas[-1]
        hist = sorted(abs(x) for x in deltas[:-1] if x != 0)
        thr = hist[int(len(hist) * 0.85)] if hist else 0
        if d_today != 0 and abs(d_today) >= thr:
            st["fishB"]["pending"] = {"signal_date": today, "side": 1 if d_today > 0 else -1}
            log_ev({"fish": "B", "type": "signal", "date": today,
                    "delta_oi": d_today, "thr": round(thr), "side": st["fishB"]["pending"]["side"]})

    # ---- 魚A:先管持倉,再看進場 ----
    days = txo_data.load("2023-01-01")
    vols = ewma_vol_by_date()
    gex = build_gex(days)
    held = st["fishA"]["held"]
    if today in days:
        rec = days[today]
        rv = vols.get(today)
        edge = (rec["atm_iv"] - rv) if rv else None
        if held:
            same = rec["contract"] == held["contract"]
            mark = straddle(rec, held["K"]) if same else None
            held["age"] += 1
            reason = None
            if not same or mark is None:
                reason, exit_px = "roll", held["last_mark"]
            elif mark > held["entry_px"] * 1.5:
                reason, exit_px = "stop", mark
            elif held["age"] >= 5:
                reason, exit_px = "timeout", mark
            elif edge is not None and edge < 0.01:
                reason, exit_px = "converged", mark
            if reason:
                pnl = held["entry_px"] - exit_px - COST_A
                realize(st, "A", pnl, {"fish": "A", "type": "exit", "reason": reason,
                        "date": today, "entry": held["entry_px"], "exit": exit_px})
                st["fishA"]["held"] = None
            else:
                held["last_mark"] = mark
                log_ev({"fish": "A", "type": "mark", "date": today, "mark": mark,
                        "u_pnl_pts": round(held["entry_px"] - mark, 1), "age": held["age"]})
        if st["fishA"]["held"] is None and edge is not None and not stop_all:
            gs = sorted(gex[d]["mag"] for d in sorted(gex)[-60:])
            g_med = gs[len(gs) // 2]
            if edge > 0.03 and 10 <= rec["dte"] <= 40 and gex[today]["mag"] >= g_med:
                px = straddle(rec, rec["atm_K"])
                if px:
                    st["fishA"]["held"] = {"contract": rec["contract"], "K": rec["atm_K"],
                                           "entry_px": px, "last_mark": px, "age": 0,
                                           "entry_date": today}
                    log_ev({"fish": "A", "type": "entry", "date": today, "K": rec["atm_K"],
                            "straddle_px": px, "iv": rec["atm_iv"], "edge": round(edge, 3),
                            "dte": rec["dte"]})
    else:
        print("  魚A:今日 TXO 資料尚未可得(FinMind 更新中),下次補")

    # ---- ETF 折溢價每日快照(自建歷史,魚D 回測的原料;官方無歷史源)----
    try:
        from etf_inav import fetch as etf_fetch
        snap = etf_fetch()
        rec = {"date": today, "prem": {c: v["prem_pct"] for c, v in snap.items()}}
        with open(os.path.join(PDIR, "etf_prem_history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  ETF 折溢價快照:{len(rec['prem'])} 檔入庫")
    except Exception as e:
        print(f"  ETF 快照跳過:{e}")

    # ---- 魚C:MTF-ORB(用戶哲學版,盤後用 Shioaji 當日1分K重播)----
    try:
        fish_ce(bars, today, st)
    except Exception as e:
        print(f"  魚C 本次跳過:{type(e).__name__} {e}")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, default=str)


def pick_mode(bars):
    """regime 路由:平靜+趨勢明→魚C breakout;高波動→魚E fade(相反);其餘觀望。
    回 (fish, dir) 或 (None, 0)。dir 對 fade 無意義(對稱)。"""
    g, vol_ok = c_gates(bars)
    if vol_ok and g != 0:
        return "C", g          # 平靜趨勢日:順勢突破
    if not vol_ok:
        return "E", 0          # 高波動亂盤日:fade 突破(規格凍結 2026-07-23,弱證據 t=0.45,paper 驗)
    return None, 0             # 平靜但無趨勢:觀望


def replay_intraday(rows, fish, dir):
    """盤後用當日1分K重播一筆。rows=[(hm,o,h,l,c)]。回 dict(entry/exit/pnl/reason) 或 None。
    魚C:突破OR順勢,停損OR另一側。魚E:突破OR反手,停損突破外緣+30。皆13:44出。"""
    if len(rows) < 40:
        return None
    orh = max(x[2] for x in rows[:30])
    orl = min(x[3] for x in rows[:30])
    pos = 0
    entry = stop = 0.0
    ehm = ""
    for hm, o, h, l, c in rows[30:]:
        if pos == 0:
            if hm >= "13:30":
                break
            if fish == "C":
                if dir > 0 and c > orh:
                    pos, entry, stop, ehm = 1, c, orl, hm
                elif dir < 0 and c < orl:
                    pos, entry, stop, ehm = -1, c, orh, hm
            else:  # E fade
                if c > orh:
                    pos, entry, stop, ehm = -1, c, orh + 30, hm
                elif c < orl:
                    pos, entry, stop, ehm = 1, c, orl - 30, hm
            continue
        if (pos > 0 and l <= stop) or (pos < 0 and h >= stop):
            return {"side": pos, "entry": entry, "exit": stop, "reason": "stop", "ehm": ehm, "xhm": hm}
        if hm >= "13:44":
            return {"side": pos, "entry": entry, "exit": c, "reason": "eod", "ehm": ehm, "xhm": hm}
    if pos:
        return {"side": pos, "entry": entry, "exit": rows[-1][4], "reason": "eod", "ehm": ehm, "xhm": rows[-1][0]}
    return None


def c_gates(bars):
    """魚C 兩道閘(規格凍結 2026-07-22):日線 EMA9>21>50 排列(只用昨日以前)
    + 波動閘(20日ATR%≤近252日80分位)。回 (gate, vol_ok)。"""
    closes = [b["close"] for b in bars]
    def ema(n):
        e, k = None, 2 / (n + 1)
        for c in closes[:-1]:
            e = c if e is None else c * k + e * (1 - k)
        return e
    e9, e21, e50 = ema(9), ema(21), ema(50)
    g = 1 if e9 > e21 > e50 else (-1 if e9 < e21 < e50 else 0)
    trs = [max(bars[i]["high"] - bars[i]["low"], abs(bars[i]["high"] - bars[i-1]["close"]),
               abs(bars[i]["low"] - bars[i-1]["close"])) / bars[i]["close"]
           for i in range(len(bars) - 252, len(bars))]
    atr20 = sum(trs[-20:]) / 20
    vol_ok = atr20 <= sorted(sum(trs[i:i+20])/20 for i in range(len(trs)-20))[int(0.8*(len(trs)-20))]
    return g, vol_ok


def c_done_today(today):
    """live 盤中已記錄今天的魚C → 晚間重播跳過(live 主、重播備)。"""
    try:
        for l in open(LEDGER, encoding="utf-8"):
            e = json.loads(l)
            if e.get("fish") in ("C", "E") and e.get("date") == today:
                return True
    except FileNotFoundError:
        pass
    return False


def fish_ce(bars, today, st):
    """魚C(平靜趨勢日 breakout)/魚E(高波動日 fade)regime 路由,盤後重播。
    live_intraday 盤中已記錄則跳過(live 主、重播備援)。"""
    dates = [b["date"] for b in bars]
    if dates[-1] != today or len(bars) < 300:
        return
    if c_done_today(today):
        print("  魚C/E:盤中 live 已記錄今日,重播跳過")
        return
    stop_all, _ = halted(st)
    fish, dir = pick_mode(bars)
    if fish is None or stop_all:
        g, vok = c_gates(bars)
        print(f"  魚C/E:今日觀望(方向={g}, 波動OK={vok}, 煞車={stop_all})")
        return
    from shioaji_adapter import login_env
    import time as _t
    api = login_env()
    _t.sleep(3)
    kb = api.kbars(api.Contracts.Futures.TXF["TXFR1"], start=today, end=today)
    api.logout()
    rows = []
    for ts, o, h, l, c in zip(kb.ts, kb.Open, kb.High, kb.Low, kb.Close):
        t = datetime.datetime.utcfromtimestamp(int(ts) / 1e9)
        hm = t.strftime("%H:%M")
        if "08:46" <= hm <= "13:45":
            rows.append((hm, o, h, l, c))
    r = replay_intraday(rows, fish, dir)
    if r:
        pnl = r["side"] * (r["exit"] - r["entry"]) - COST_B
        realize(st, fish, pnl, {"fish": fish, "type": "trade", "date": today, "side": r["side"],
                "entry": r["entry"], "exit": r["exit"], "reason": r["reason"], "mode":
                ("breakout" if fish == "C" else "fade")})
    else:
        print(f"  魚{fish}({'突破' if fish=='C' else 'fade'}):今日無觸發,未進場")


def write_report():
    """帳本 → .paper/index.html(自足式,winrig 8912 端口對 Tailscale 供瀏覽)。"""
    try:
        evs = [json.loads(l) for l in open(LEDGER, encoding="utf-8")]
    except FileNotFoundError:
        evs = []
    st = load_state()
    eq = st.get("equity", START_EQUITY)
    peak = st.get("peak", START_EQUITY)
    dd = 1 - eq / peak if peak else 0
    ret = eq / START_EQUITY - 1
    # 權益曲線(從事件流重建)
    curve = [START_EQUITY] + [e["equity"] for e in evs if "equity" in e]
    if len(curve) > 1:
        mn, mx = min(curve), max(curve)
        span = (mx - mn) or 1
        pts = " ".join(f"{i*300/(len(curve)-1):.1f},{40-(v-mn)/span*36:.1f}" for i, v in enumerate(curve))
        svg = f'<svg viewBox="0 0 300 44" style="width:100%;height:44px"><polyline points="{pts}" fill="none" stroke="{"#6dbd88" if curve[-1]>=curve[0] else "#dd7f68"}" stroke-width="1.5"/></svg>'
    else:
        svg = '<div style="color:#6b7078;font-size:.8rem">等第一筆結算後出現曲線</div>'
    equity_html = (f'<div class="card" style="grid-column:1/-1"><div class="t">虛擬帳戶(本金 {START_EQUITY:,})</div>'
                   f'<div class="v {"pos" if ret>=0 else "neg"}">{eq:,.0f} 元({ret:+.2%})</div>'
                   f'<div class="s">回撤 {dd:.1%}(煞車線 {HARD_DD:.0%})· 規模:小台1口/跨式1組</div>{svg}</div>')
    names = {"A": "A 條件賣跨式+GEX", "B": "B 外資高信念跟隨", "C": "C ORB順勢(平靜趨勢日)", "E": "E fade(高波動亂盤日)"}
    cards, cum = equity_html, {}
    for f in ("A", "B", "C", "E"):
        pnls = [e["pnl_ntd"] for e in evs if e.get("fish") == f and "pnl_ntd" in e]
        cum[f] = sum(pnls)
        wr = (sum(1 for x in pnls if x > 0) / len(pnls)) if pnls else 0
        w=[x for x in pnls if x>0]; ll=[x for x in pnls if x<=0]
        aw=sum(w)/len(w) if w else 0; al=sum(ll)/len(ll) if ll else 0
        ratio=f"{aw/abs(al):.1f}x" if al else "—"
        extra=f' · 賺賠比 {ratio}' if pnls else ''
        cards += (f'<div class="card"><div class="t">{names[f]}</div>'
                  f'<div class="v {"pos" if cum[f]>=0 else "neg"}">{cum[f]:+,} 元</div>'
                  f'<div class="s">{len(pnls)} 筆 · 勝率 {wr:.0%}{extra}</div></div>')
    posi = []
    if st["fishA"].get("held"):
        h = st["fishA"]["held"]
        posi.append(f"魚A 持倉:{h['contract']} K={h['K']} 進 {h['entry_px']} 最新mark {h['last_mark']}(第{h['age']}天)")
    if st["fishB"].get("pending"):
        p = st["fishB"]["pending"]
        posi.append(f"魚B 待執行:{p['signal_date']} 訊號 → 次交易日 {'做多' if p['side']>0 else '做空'}")
    strat_html = """
<h2 style="font-size:1rem;margin:22px 0 8px">📖 策略說明(給人看的版本)</h2>
<div class="fish"><b>A|收保險費(賣跨式選擇權)</b><br>
<span class="why">邏輯:選擇權=保險。只在「保費明顯超收」且「做市商自動對沖會壓住行情」的日子當保險公司,收權利金。</span><br>
進場:隱含波動比實際波動貴 3% 以上+距到期 10-40 天+GEX(對沖阻尼)高於近 60 日中位。<br>
出場:保費回歸/持有滿 5 天/虧到 1.5 倍停損/合約換月。規模:1 組。<br>
<span class="ev">依據:800 天研究——保費超收集中在高波動期;GEX 高的日子隔天行情被壓(t=+2.6)。出手很少,一月約 0-2 次。</span></div>
<div class="fish"><b>B|跟外資大單搭順風車</b><br>
<span class="why">邏輯:外資建大部位要分好幾天下單,第一天的大動作後面還有續單。輸家=反應慢的資金。</span><br>
進場:外資台指期淨部位單日變化進入歷史前 15% 大 → 次日開盤跟方向,收盤出。<br>
<span class="ev">依據:6.5 年回測唯一通過 DSR 統計檢定的訊號(0.917),最終保留段勝率 69%;因樣本仍少,由 paper 定生死。規模:小台 1 口。</span></div>
<div class="fish"><b>C|看長做短,一天一單(老闆您提的哲學)</b><br>
<span class="why">邏輯:日線趨勢明確+市場不在發瘋的日子,等開盤 30 分鐘定出區間,順趨勢方向做一單:錯了小賠認,對了抱到收盤前。贏大輸小,不求高勝率。</span><br>
進場:日線 EMA 多/空排列+波動閘(市場太瘋不進)+突破開盤區間。<br>
出場:停損=區間另一側;否則 13:44 出(絕不留到強制平倉踩踏時段)。規模:小台 1 口。<br>
<span class="ev">依據:平靜趨勢日回測正;高波動年出手稀疏(月2-3次)。</span></div>
<div class="fish" style="border-left-color:#8a5f1c"><b>E|高波動日反手 fade(regime 互補,弱候選測試中)</b><br>
<span class="why">邏輯:魚C 空手的高波動亂盤日不再枯坐——突破多半是假的,反手做(fade),贏大輸小。</span><br>
進場:波動閘擋下的日子(最兇20%),突破OR30就反向進,停損=突破外緣+30點,13:44出。<br>
<span class="ev">⚠️ 依據弱(高波動日回測 +3.9點/筆但 t=0.45=可能是運氣),明確標為「測試中」由 paper 裁決;高波動年出手頻繁(月~20次),裁決快。</span></div>
<div class="fish" style="border-left-color:#9a6a22"><b>⚖️ 交易紀律(全部寫死在程式裡,不靠意志力)</b><br>
虛擬本金 300 萬照真實規則運作;回撤 10% 減碼、20% 全面停單;策略規格已凍結不得中途調參;
<b>裁決規則:魚C 滿 30 筆自動判生死(均值為正→升真錢 1 口小台;差→處決),魚B 滿 10 筆、魚A 滿 5 筆同理。</b></div>"""
    rows = ""
    for e in reversed(evs[-40:]):
        pnl = e.get("pnl_ntd")
        cls = "" if pnl is None else (' class="pos"' if pnl >= 0 else ' class="neg"')
        rows += (f"<tr><td>{e.get('date', e.get('exec_date',''))}</td><td>{e['fish']}</td>"
                 f"<td>{e['type']}{('/'+e['reason']) if e.get('reason') else ''}</td>"
                 f"<td{cls}>{f'{pnl:+,}' if pnl is not None else '—'}</td></tr>")
    html = f"""<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="600"><title>Paper 帳本</title><style>
body{{background:#14161b;color:#e8e6df;font:15px/1.6 -apple-system,"PingFang TC",sans-serif;max-width:640px;margin:0 auto;padding:20px}}
h1{{font-size:1.2rem}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}
.card{{background:#1c1f26;border:1px solid #2a2e37;border-radius:10px;padding:12px 14px}}
.card .t{{font-size:.78rem;color:#9a9e a6;color:#9aa0a8}}.card .v{{font-size:1.3rem;font-weight:600}}
.card .s{{font-size:.78rem;color:#9aa0a8}}.pos{{color:#6dbd88}}.neg{{color:#dd7f68}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:.85rem}}
td,th{{padding:6px 8px;border-bottom:1px solid #2a2e37;text-align:left}}
.posi{{background:#1c1f26;border-radius:8px;padding:10px 14px;margin:12px 0;font-size:.85rem}}
.ft{{color:#6b7078;font-size:.75rem;margin-top:16px}}
.fish{{background:#1c1f26;border:1px solid #2a2e37;border-left:3px solid #2f5657;border-radius:8px;padding:10px 14px;margin:8px 0;font-size:.85rem;line-height:1.65}}
.fish .why{{color:#bfc1ba}}.fish .ev{{color:#9aa0a8;font-size:.8rem}}
.btnote{{background:#2c2617;border:1px solid #4a3f1c;border-radius:8px;padding:9px 13px;font-size:.8rem;color:#d3a656;margin:6px 0 10px;line-height:1.6}}
.dlog{{font-size:.8rem}}.dl{{padding:4px 8px;border-bottom:1px solid #2a2e37;color:#9aa0a8}}.dl.t{{color:#6dbd88}}.dl .dd{{color:#6b7078;margin-right:8px;font-variant-numeric:tabular-nums}}</style>
<h1>📒 Paper 前測帳本(規格凍結 2026-07-17/22,真 OOS)</h1>
<div class="cards">{cards}</div>
<div class="posi">{'<br>'.join(posi) if posi else '目前無持倉/無待執行'}</div>
{strat_html}
<table><tr><th>日期</th><th>魚</th><th>事件</th><th>損益(元)</th></tr>{rows or '<tr><td colspan=4>帳本尚無事件</td></tr>'}</table>
<div class="ft">每晚 20:10 winrig 自動更新 · 產生於 {datetime.datetime.now().isoformat(timespec='seconds')}</div>"""
    # 近期每日決策(讀 live_log.txt,讓空手日也看得見系統在運作)
    dlog = ""
    try:
        lines = [l.strip() for l in open(LOG_LIVE, encoding="utf-8") if l.strip()]
        keep = [l for l in lines if any(k in l for k in ("閘門", "進場", "出場", "收工", "不進場"))]
        for l in keep[-12:][::-1]:
            ts, msg = (l.split(" ", 1) + [""])[:2]
            d = ts[:10] + " " + ts[11:16]
            traded = ("進場" in msg or "出場" in msg)
            dlog += f'<div class="dl {"t" if traded else ""}"><span class="dd">{d}</span> {msg}</div>'
    except Exception:
        pass
    if dlog:
        panel = f'<h2 style="font-size:1rem;margin:20px 0 6px">🕗 魚C 每日決策日誌(空手也是決策)</h2><div class="dlog">{dlog}</div>'
        anchor = '<h2 style="font-size:1rem;margin:22px 0 8px">📖 策略說明'
        html = html.replace(anchor, panel + anchor, 1) if anchor in html else html + panel
    # 回測示意面板(策略在歷史上怎麼跑;明確標非真實績效)
    try:
        bt = json.load(open(os.path.join(PDIR, "backtest.json"), encoding="utf-8"))
        cv = bt["curve"]
        if len(cv) > 1:
            mn, mx = min(cv), max(cv); sp = (mx - mn) or 1
            pts = " ".join(f"{i*300/(len(cv)-1):.1f},{50-(v-mn)/sp*46:.1f}" for i, v in enumerate(cv))
            col = "#6dbd88" if cv[-1] >= START_EQUITY else "#dd7f68"
            svg = f'<svg viewBox="0 0 300 54" style="width:100%;height:70px"><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.5"/></svg>'
        else:
            svg = ""
        trows = ""
        for t in bt["trades"][::-1]:
            cls = "pos" if t["pnl"] >= 0 else "neg"
            trows += f'<tr><td>{t["date"]}</td><td>魚{t["fish"]}</td><td>{t["side"]}</td><td class="{cls}">{t["pnl"]:+,}</td></tr>'
        btpanel = (f'<h2 style="font-size:1rem;margin:22px 0 6px">📉 策略回測示意(非真實績效·含後見之明)</h2>'
                   f'<div class="btnote">⚠️ 這是 C+E 策略在 2025-01→今 的歷史重播,幫你「看到策略怎麼動」。'
                   f'因規則是看過這段歷史後設計的,<b>不代表未來、不是承諾</b>。真實績效看上方「虛擬帳戶」(今天起累積)。</div>'
                   f'<div class="card" style="grid-column:1/-1"><div class="t">回測 {bt["n"]} 筆 · 勝率 {bt["win_rate"]}%（{bt.get("start","?")} → {bt.get("generated","?")}）</div>'
                   f'<div class="v {"pos" if bt["ret_pct"]>=0 else "neg"}">{bt["final_equity"]:,}（{bt["ret_pct"]:+}%）</div>{svg}'
                   f'<div style="display:flex;justify-content:space-between;color:#6b7078;font-size:.72rem;margin-top:-4px">'
                   f'<span>{bt.get("start","?")}</span><span>共 {bt["n"]} 筆 · 曲線=全期</span><span>{bt.get("generated","?")}</span></div></div>'
                   + '<div class="btnote" style="color:#9aa0a8;background:#1c1f26;border-color:#2a2e37">🎯 少輸多贏檢查(賺賠比＝平均贏÷平均輸):'
                   + ' ｜ '.join(f'魚{ff} 勝率{a["wr"]}% 贏{a["avg_win"]:+,}/輸{a["avg_loss"]:+,} <b>賺賠比{a["ratio"]}x</b> 期望{a["exp"]:+,}'
                                 for ff, a in bt.get("fish_asym", {}).items()) + '</div>'
                   f'<div style="color:#6b7078;font-size:.78rem;margin:8px 0 2px">最近 {len(bt["trades"])} 筆(非全期;完整績效看上方曲線)</div>'
                   f'<table><tr><th>日期</th><th>魚</th><th>方向</th><th>損益</th></tr>{trows}</table>')
        anchor = '<h2 style="font-size:1rem;margin:22px 0 8px">📖 策略說明'
        html = html.replace(anchor, btpanel + anchor, 1) if anchor in html else html + btpanel
    except FileNotFoundError:
        pass

    anchor = '<h2 style="font-size:1rem;margin:22px 0 8px">📖 策略說明'
    # 💎 CB 凸性彈藥清單面板(讀 cb_analyzer/cb_convexity.json;老闆可轉債的便宜凸性)
    try:
        cbp = os.path.join(HERE, "..", "..", "cb_analyzer", "cb_convexity.json")
        cb = json.load(open(cbp, encoding="utf-8"))
        tnm = {1: "✅門檻", 2: "⚠️規模夠·信用弱", 3: "小規模"}
        def _cbrow(r):
            ve = f'{r["vol_edge"]*100:+.1f}%' if r.get("vol_edge") is not None else "—"
            cls = "pos" if (r.get("vol_edge") or 0) > 0 else "neg"
            iv = f'{r["iv"]*100:.0f}%' if r.get("iv") else "—"
            hv = f'{r["hv"]*100:.0f}%' if r.get("hv") else "—"
            return (f'<tr><td>{r["name"]}</td><td>{r["code"]}</td><td>{r["spot"]:.1f}</td>'
                    f'<td>{r["K"]:.1f}</td><td>{r["parity"]:.0f}</td><td>{r["floor"]:.0f}</td>'
                    f'<td>{hv}/{iv}</td><td class="{cls}">{ve}</td><td>{r["edge_theo"]:+.1f}</td>'
                    f'<td>{r.get("tcri")}</td><td>{r.get("size")}億</td><td>{tnm.get(r.get("tier"),"")}</td></tr>')
        cbrows = "".join(_cbrow(r) for r in cb.get("rows", []))
        cbpanel = (f'<h2 style="font-size:1rem;margin:22px 0 6px">💎 CB 凸性彈藥清單(老闆的可轉債)</h2>'
                   f'<div class="btnote">「便宜度」= 標的實現波動 − CB反解隱波(正=內嵌選擇權被賤賣:下檔債底撐、上檔吃股票波動=高信念集中壓的彈藥)。'
                   f'⚠️ 隱波從承銷價反解非交易所IV;{cb.get("n_priced")}/{cb.get("n_total")}檔可定價;現階段可拆池全是 TCRI 5-7 中弱信用(無一過投資級門檻)。</div>'
                   f'<div class="card" style="grid-column:1/-1;overflow-x:auto"><table>'
                   f'<tr><th>名稱</th><th>股</th><th>現股</th><th>轉換價</th><th>parity</th><th>債底</th>'
                   f'<th>實波/內隱</th><th>便宜度</th><th>理論edge</th><th>TCRI</th><th>規模</th><th>層</th></tr>'
                   f'{cbrows}</table></div>')
        html = html.replace(anchor, cbpanel + anchor, 1) if anchor in html else html + cbpanel
    except (FileNotFoundError, KeyError, ValueError):
        pass

    # 🪙 Crypto 量化研究面板(四扇門誠實記分;靜態研究定論)
    crypto = [("裸趨勢突破", "BTC WF夏普+0.27 / +2%年 / 46%回撤", "🟡弱"),
              ("均值回歸", "全負(夏普-1.2~-2.2)= 動能主導不回歸", "🔴無"),
              ("無腦持有", "BTC-1% / ETH-44%(此2年盤整偏空)", "🔴虧"),
              ("資金費率套利", "淨carry +4.7%/年 · 80%期為正 · 夏普高", "🟢真但低")]
    crows = "".join(f'<tr><td>{n}</td><td>{d}</td><td>{v}</td></tr>' for n, d, v in crypto)
    crypanel = (f'<h2 style="font-size:1rem;margin:22px 0 6px">🪙 Crypto 量化研究(誠實記分)</h2>'
                f'<div class="btnote">crypto 沒有躺賺演算法:純價格門(趨勢/回歸)此窗口難,唯一真 edge 是資金費率套利但只 +4.7%(債券型底倉)。'
                f'⚠️ crypto native vol 極高(持有就54-69%回撤)→ 槓桿=爆倉。高報酬=小edge×槓桿 或 CB凸性×高信念。</div>'
                f'<div class="card" style="grid-column:1/-1;overflow-x:auto"><table>'
                f'<tr><th>機制(門)</th><th>walk-forward 結果</th><th>判定</th></tr>{crows}</table></div>')
    html = html.replace(anchor, crypanel + anchor, 1) if anchor in html else html + crypanel

    with open(os.path.join(PDIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # FinMind 限流/網路瞬斷等:不炸 cron,明天自然補跑(魚B結算用「訊號日後第一根」不會漏)
        print(f"paper_daily 跳過本次:{type(e).__name__} {e}")
    finally:
        os.makedirs(PDIR, exist_ok=True)
        try:
            write_report()
        except Exception as e:
            print(f"report 產生失敗:{e}")
