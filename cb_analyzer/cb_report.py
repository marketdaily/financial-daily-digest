"""把 rank() 結果輸出成自包含 HTML 報告(深色玻璃卡片風)+ 內建互動資金模擬器。"""
import os, html, json, datetime
import cb_core
import cb_profiles
import cb_intel

HERE = os.path.dirname(os.path.abspath(__file__))


def _intel_html(code, spot=None):
    lines = cb_intel.intel_lines(code, spot)
    if not lines:
        return ""
    items = "".join(f'<div class="iline">{html.escape(ln)}</div>' for ln in lines)
    return f'<div class="intel"><div class="ihead">📊 市場情報</div>{items}</div>'


def _profile_html(code):
    """公司營運區塊:產業/主營/產品/上下游/客戶/合作。"""
    p = cb_profiles.get_profile(code)
    ind = p.get("industry") or "—"
    if not p.get("curated"):
        return (f'<div class="prof"><div class="pind">🏢 {html.escape(ind)}'
                f'<span class="uncur">產業分類(FinMind);詳細營運待補</span></div></div>')
    rows = []
    if p.get("business"):
        rows.append(f'<div class="pbiz">{html.escape(p["business"])}</div>')
    prods = "、".join(p.get("products") or [])
    if prods:
        rows.append(f'<div class="pline"><b>產品</b>{html.escape(prods)}</div>')
    for label, key in [("上游", "upstream"), ("下游", "downstream"),
                       ("客戶", "customers"), ("合作", "partners")]:
        v = p.get(key)
        if v:
            rows.append(f'<div class="pline"><b>{label}</b>{html.escape(v)}</div>')
    if p.get("note"):
        rows.append(f'<div class="pnote">💡 {html.escape(p["note"])}</div>')
    return (f'<div class="prof"><div class="pind">🏢 {html.escape(ind)}</div>'
            + "".join(rows) + "</div>")


def _pct(v, d=1):
    return f"{v*100:.{d}f}%" if v is not None else "—"


def _verdict(s):
    if s >= 70:
        return "強力候選", "#34d399"
    if s >= 58:
        return "有吸引力", "#34d399"
    if s >= 48:
        return "中性", "#fbbf24"
    return "吸引力低", "#f87171"


def _scen_bar(scen):
    """情境報酬橫條(SVG),負紅正綠,以權利金報酬率畫。"""
    rows = []
    maxabs = max((abs(s["return_on_premium"] or 0) for s in scen), default=1) or 1
    for s in scen:
        ror = s["return_on_premium"] or 0
        w = abs(ror) / maxabs * 46
        col = "#34d399" if ror >= 0 else "#f87171"
        left = 50 if ror >= 0 else 50 - w
        rows.append(
            f'<div class="sc"><span class="scm">{s["move"]*100:+.0f}%</span>'
            f'<div class="scbar"><i style="left:{left}%;width:{w}%;background:{col}"></i></div>'
            f'<span class="scr" style="color:{col}">{ror*100:+.0f}%</span></div>')
    return "".join(rows)


def _card(item, sd, a):
    vt, vc = _verdict(a["score"])
    g = lambda v: ("#34d399" if v >= 0 else "#f87171")
    if a.get("eligible"):
        elig_badge = '<span class="elig ok">✅ 可拆解</span>'
    else:
        why = "；".join(a.get("elig_reasons", []))
        elig_badge = f'<span class="elig no" title="{html.escape(why)}">❌ 不符準則</span>'
    ve = a.get("vol_edge")
    auction = ""
    if a.get("auction_low"):
        auction = f"競拍 {a['auction_low']}~{a['auction_high']}"
    cardcls = "card elig-card" if a.get("eligible") else "card dim-card"
    rows = f"""
    <div class="{cardcls}">
      <div class="chead">
        <div><span class="nm">{html.escape(item['name'])}</span> {elig_badge}
          <span class="cd">股 {item['stock_code']} · 債 {item['bond_code']}</span></div>
        <div class="score" style="--c:{vc}">{a['score']:.0f}<small>/100</small></div>
      </div>
      <div class="tags">
        <span>TCRI{item['tcri']}/{html.escape(item['collateral'])}</span>
        <span>{item['tenor_year']}年</span><span>{html.escape(item['put']['raw'])}</span>
        <span>{item['size_yi']}億</span><span>{html.escape(a.get('pricing_method') or '')}</span>
        <span class="vd" style="color:{vc}">{vt}</span>
      </div>
      <div class="grid">
        <div><b>{sd['spot']:.1f}</b><label>現股價</label></div>
        <div><b>{item['conv_price']}</b><label>轉換價</label></div>
        <div><b>{a['parity']:.0f}</b><label>parity</label></div>
        <div><b>{a['issue_price']:.1f}</b><label>清算價</label></div>
        <div><b>{a['bond_floor']:.1f}</b><label>債券底</label></div>
        <div><b>{a['option_value']:.1f}</b><label>選擇權</label></div>
        <div><b style="color:{g(a['edge_theo'])}">{a['theoretical']:.1f}</b><label>理論價</label></div>
        <div><b>{a['leverage']:.1f}×</b><label>槓桿</label></div>
      </div>
      <div class="vol">
        <span>發行隱含波動 <b>{_pct(a['implied_vol'],0)}</b></span>
        <span>前瞻波動 <b>{_pct(a['hist_vol'],0)}</b></span>
        <span style="color:{g(ve or 0)}">價差 <b>{('+' if (ve or 0)>=0 else '')}{(ve or 0)*100:.0f}pt</b>
          （{'選擇權便宜' if (ve or 0)>0 else '偏貴'}）</span>
        <span class="lossnote">下檔最多賠權利金 {a['cbas_premium']:.1f}</span>
      </div>
      <div class="scen"><div class="scl">股價情境 → 對權利金本金報酬</div>{_scen_bar(a['scenarios'])}</div>
      {_profile_html(item['stock_code'])}
      {_intel_html(item['stock_code'], sd.get('spot'))}
      <div class="reasons">{''.join(f'<span>{html.escape(r)}</span>' for r in a['score_reasons'])}</div>
    </div>"""
    return rows


def _watch_card(item):
    """待定價觀察卡:條件未定沒有定價分析,只放合格標記+公司營運。"""
    return f"""
    <div class="card elig-card watch-card">
      <div class="chead">
        <div><span class="nm">{html.escape(item['name'])}</span>
          <span class="elig ok">✅ 符合準則</span>
          <span class="cd">股 {item['stock_code']} · 債 {item['bond_code']}</span></div>
        <div class="wtag">待定價</div>
      </div>
      <div class="tags">
        <span>TCRI{item['tcri']}/{html.escape(item['collateral'])}</span>
        <span>{item['size_yi']}億</span><span>{item['tenor_year']}年</span>
        <span>{html.escape(item['section'])}</span><span>{html.escape(item['underwriter'])}</span>
      </div>
      {_profile_html(item['stock_code'])}
      {_intel_html(item['stock_code'])}
      <div class="pnote2">條件未定,承銷價/轉換價出來後即可拆解定價分析。</div>
    </div>"""


def write_report(db, results, path=None):
    path = path or os.path.join(HERE, "report.html")
    A = cb_core.ASSUMPTIONS
    today = datetime.date.today().isoformat()
    elig = [r for r in results if r[2].get("eligible")]
    other = [r for r in results if not r[2].get("eligible")]

    def _rows(rs):
        out = ""
        for n, (item, sd, a) in enumerate(rs, 1):
            vt, vc = _verdict(a["score"])
            out += (
                f'<tr class="clk" onclick="quick(\'{item["bond_code"]}\')" title="點我看 {html.escape(item["name"])} 完整分析">'
                f'<td>{n}</td><td class="sc" style="color:{vc}">{a["score"]:.0f}</td>'
                f'<td>{html.escape(item["name"])}</td><td>{item["stock_code"]}</td>'
                f'<td>TCRI{item["tcri"]}</td><td>{item["size_yi"]}億</td>'
                f'<td>{sd["spot"]:.1f}</td><td>{a["parity"]:.0f}</td>'
                f'<td>{a["issue_price"]:.0f}</td><td>{a["theoretical"]:.0f}</td>'
                f'<td>{_pct(a["implied_vol"],0)}</td><td>{_pct(a["hist_vol"],0)}</td>'
                f'<td>{a["leverage"]:.1f}×</td><td style="color:{vc}">{vt}</td></tr>')
        return out
    elig_rows = _rows(elig) or '<tr><td colspan="14" style="text-align:center;color:#8b95a7">本期已定價案件無一符合</td></tr>'
    cards = "".join(_card(*r) for r in elig)
    tcri_str = " · ".join(f"{k}:{v*100:.1f}%" for k, v in A["tcri_spread"].items())

    watch = [i for i in db["items"]
             if (not i.get("conv_price") or not i.get("premium_mid"))
             and i.get("tcri") in A["elig_tcri"] and (i.get("size_yi") or 0) >= A["elig_min_size"]]
    watch.sort(key=lambda i: -(i.get("size_yi") or 0))
    watch_rows = "".join(
        f'<tr class="clk" onclick="quick(\'{i["stock_code"]}\')" title="點我看 {html.escape(i["name"])} 公司分析">'
        f'<td>{html.escape(i["name"])}</td><td>{i["stock_code"]}</td>'
        f'<td>TCRI{i["tcri"]}</td><td>{i["size_yi"]}億</td><td>{i["tenor_year"]}年</td>'
        f'<td>{html.escape(i["section"])}</td><td>{html.escape(i["underwriter"])}</td></tr>'
        for i in watch)
    watch_cards = "".join(_watch_card(i) for i in watch)

    doc = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CB 拆解分析 · {db['source_file']}</title>
<style>
:root{{--bg:#0a0e1a;--card:rgba(255,255,255,.04);--bd:rgba(255,255,255,.09);--mut:#8b95a7}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(900px 500px at 80% -10%,rgba(99,102,241,.18),transparent),var(--bg);
color:#e6e9f0;font-family:Inter,"Noto Sans TC",system-ui,sans-serif;line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px 80px}}
h1{{font-size:24px;margin:0 0 4px;background:linear-gradient(90deg,#a5b4fc,#818cf8);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:36px;
background:var(--card);border:1px solid var(--bd);border-radius:14px;overflow:hidden}}
th,td{{padding:9px 10px;text-align:right;border-bottom:1px solid rgba(255,255,255,.05)}}
th:nth-child(3),td:nth-child(3){{text-align:left}}
th{{background:rgba(255,255,255,.04);color:var(--mut);font-weight:600;font-size:12px}}
tr:last-child td{{border-bottom:0}}
td.sc{{font-weight:800}}
.cards{{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(330px,1fr))}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:18px;
backdrop-filter:blur(8px)}}
.chead{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}}
.nm{{font-size:18px;font-weight:700}}
.cd{{display:block;color:var(--mut);font-size:11px;margin-top:2px}}
.score{{font-size:30px;font-weight:800;color:var(--c);line-height:1}}
.score small{{font-size:12px;color:var(--mut);font-weight:500}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}}
.tags span{{font-size:11px;padding:2px 8px;border-radius:20px;background:rgba(255,255,255,.05);color:var(--mut)}}
.tags .vd{{margin-left:auto;font-weight:700;background:rgba(255,255,255,.08)}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px 6px;margin:10px 0 12px}}
.grid div{{text-align:center}}
.grid b{{font-size:16px;display:block}}
.grid label{{font-size:10px;color:var(--mut)}}
.vol{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--mut);
padding:10px 0;border-top:1px solid rgba(255,255,255,.06)}}
.vol b{{color:#e6e9f0}}.lossnote{{color:#fbbf24}}
.scen{{margin-top:6px}}.scl{{font-size:11px;color:var(--mut);margin-bottom:4px}}
.sc{{display:flex;align-items:center;gap:8px;font-size:11px;margin:2px 0}}
.scm{{width:36px;color:var(--mut)}}.scr{{width:42px;text-align:right;font-weight:700}}
.scbar{{position:relative;flex:1;height:8px;background:rgba(255,255,255,.05);border-radius:4px}}
.scbar i{{position:absolute;top:0;height:8px;border-radius:4px}}
.scbar::before{{content:"";position:absolute;left:50%;top:-2px;height:12px;width:1px;background:rgba(255,255,255,.2)}}
.reasons{{display:flex;flex-wrap:wrap;gap:4px;margin-top:12px}}
.reasons span{{font-size:10px;color:var(--mut);background:rgba(255,255,255,.03);padding:2px 7px;border-radius:6px}}
.foot{{margin-top:34px;color:var(--mut);font-size:11.5px;border-top:1px solid var(--bd);padding-top:16px}}
.warn{{color:#fbbf24}}
.crit{{background:linear-gradient(90deg,rgba(52,211,153,.14),transparent);border:1px solid rgba(52,211,153,.3);
border-radius:12px;padding:12px 16px;margin:0 0 20px;font-size:13.5px}}
.crit b{{color:#34d399}}
.sec{{font-size:15px;font-weight:700;margin:26px 0 10px;display:flex;align-items:center;gap:8px}}
.sec.ok{{color:#34d399}}.sec.no{{color:#8b95a7}}.sec.watch{{color:#a5b4fc}}
.elig{{font-size:11px;font-weight:700;padding:1px 8px;border-radius:20px;vertical-align:middle}}
.elig.ok{{background:rgba(52,211,153,.16);color:#34d399}}
.elig.no{{background:rgba(248,113,113,.14);color:#f87171}}
.elig-card{{border-color:rgba(52,211,153,.35);box-shadow:0 0 0 1px rgba(52,211,153,.12)}}
.dim-card{{opacity:.62}}
tr.er td{{background:rgba(52,211,153,.05)}}
.prof{{margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.06);font-size:12px}}
.pind{{color:#a5b4fc;font-weight:700;margin-bottom:4px}}
.uncur{{color:#8b95a7;font-weight:400;margin-left:6px;font-size:11px}}
.pbiz{{color:#e6e9f0;margin-bottom:5px;line-height:1.45}}
.pline{{color:#b7c0d0;margin:2px 0;line-height:1.5}}
.pline b{{color:#8b95a7;font-weight:600;margin-right:6px;font-size:11px}}
.pnote{{color:#fbbf24;margin-top:5px;font-size:11.5px}}
.pnote2{{color:#8b95a7;margin-top:10px;font-size:11.5px;font-style:italic}}
.watch-card .wtag{{font-size:12px;font-weight:700;color:#a5b4fc;background:rgba(165,180,252,.14);
padding:3px 10px;border-radius:20px;height:fit-content}}
.intel{{margin-top:10px;padding-top:9px;border-top:1px solid rgba(255,255,255,.06)}}
.ihead{{color:#7dd3fc;font-weight:700;font-size:12px;margin-bottom:3px}}
.iline{{color:#b7c0d0;font-size:11.5px;line-height:1.55;margin:1px 0}}
.search{{position:sticky;top:0;z-index:20;background:rgba(10,14,26,.92);backdrop-filter:blur(10px);
padding:16px 0;margin-bottom:8px;border-bottom:1px solid var(--bd)}}
.search h2{{font-size:15px;margin:0 0 8px;color:#a5b4fc}}
.sbar{{display:flex;gap:8px;flex-wrap:wrap}}
.sbar input{{flex:1;min-width:180px;background:rgba(255,255,255,.06);border:1px solid var(--bd);
border-radius:10px;padding:11px 14px;color:#e6e9f0;font-size:15px}}
.sbar input::placeholder{{color:#6b7688}}
.sbar button{{background:linear-gradient(90deg,#6366f1,#818cf8);border:0;border-radius:10px;
padding:11px 20px;color:#fff;font-weight:700;font-size:14px;cursor:pointer}}
.sbar button:active{{transform:scale(.97)}}
.sbar .cap{{max-width:130px;flex:0 0 auto}}
.shint{{color:var(--mut);font-size:11.5px;margin-top:6px}}
#sresult{{margin:14px 0}}
#sresult .cards{{margin-top:0}}
.serr{{color:#f87171;font-size:13px;padding:10px}}
.sloading{{color:#a5b4fc;font-size:13px;padding:10px}}
.simbox{{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:18px;margin-top:14px}}
.simbox h3{{margin:0 0 10px;font-size:15px;color:#34d399}}
.simrow{{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;margin:4px 0}}
.simrow b{{color:#e6e9f0}}
.simwhy{{font-size:12.5px;color:#b7c0d0;line-height:1.6;margin:8px 0}}
.simwhy .gg{{color:#34d399;font-weight:700}}.simwhy .yy{{color:#fbbf24;font-weight:700}}
.simwhy .rr{{color:#f87171;font-weight:700}}
.simtab{{width:100%;font-size:12.5px;margin-top:8px;border-collapse:collapse}}
.simtab td,.simtab th{{padding:5px 8px;text-align:right;border-bottom:1px solid rgba(255,255,255,.05)}}
.simtab th{{color:var(--mut)}}
.intro{{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px 18px;margin:4px 0 16px}}
.intro .lead{{color:#e6e9f0;font-size:14px;line-height:1.6}}
.steps{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
.step{{flex:1;min-width:200px;background:rgba(255,255,255,.04);border-radius:10px;padding:10px 12px;font-size:12.5px;color:#b7c0d0}}
.step b{{color:#a5b4fc}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}}
.chip{{font-size:12px;padding:5px 12px;border-radius:20px;background:rgba(129,140,248,.14);color:#a5b4fc;
border:1px solid rgba(129,140,248,.25);cursor:pointer;user-select:none}}
.chip:hover{{background:rgba(129,140,248,.26)}}
.slabels{{display:flex;gap:8px;flex-wrap:wrap;font-size:11px;color:var(--mut);margin-bottom:5px}}
details.gloss{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:0 16px;margin:0 0 16px}}
details.gloss summary{{cursor:pointer;padding:12px 0;color:#a5b4fc;font-weight:700;font-size:13.5px;list-style:none}}
details.gloss summary::-webkit-details-marker{{display:none}}
details.gloss summary::before{{content:"▸ ";color:#818cf8}}
details.gloss[open] summary::before{{content:"▾ "}}
.gitem{{padding:7px 0;border-top:1px solid rgba(255,255,255,.06);font-size:12.5px;color:#b7c0d0;line-height:1.55}}
.gitem b{{color:#e6e9f0}}
tbody tr.clk{{cursor:pointer}}
tbody tr.clk:hover td{{background:rgba(129,140,248,.10)}}
.twrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.portbox{{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px 18px;margin:0 0 16px}}
.portbox h2{{font-size:14px;margin:0 0 8px;color:#34d399}}
.portbox input{{background:rgba(255,255,255,.06);border:1px solid var(--bd);border-radius:9px;
padding:9px 11px;color:#e6e9f0;font-size:14px}}
.portbox .w1{{width:130px}} .portbox .w2{{width:78px}}
.portbox button{{background:linear-gradient(90deg,#6366f1,#818cf8);border:0;border-radius:9px;
padding:9px 16px;color:#fff;font-weight:700;font-size:13px;cursor:pointer}}
#plist{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}}
.pleg{{background:rgba(52,211,153,.12);border:1px solid rgba(52,211,153,.3);border-radius:20px;
padding:5px 10px 5px 12px;font-size:12.5px;color:#d1fae5;display:flex;align-items:center;gap:8px}}
.pleg b{{color:#fff}} .pleg span{{cursor:pointer;color:#f87171;font-weight:800}}
@media(max-width:640px){{.portbox input{{flex:1 1 44%}} .portbox .w1,.portbox .w2{{width:auto}}}}
@media(max-width:640px){{
  .wrap{{padding:18px 12px 60px}} h1{{font-size:20px}}
  .sbar input{{min-width:100%;flex:1 1 100%}} .sbar .cap{{max-width:none;flex:1 1 46%}}
  .sbar button{{flex:1 1 46%}} .grid{{grid-template-columns:repeat(3,1fr)}}
  .step{{min-width:100%}} table{{font-size:12px}} th,td{{padding:7px 6px}}
}}
</style></head><body><div class="wrap">
<h1>台股 CB 拆解分析台</h1>
<div class="sub">來源 {html.escape(db['source_file'])} · 產出 {today} · 已定價 {len(results)} 檔 / 全市場現有可轉債 380+ 檔可查</div>

<div class="intro">
  <div class="lead">輸入一個代碼,系統自動抓報價與條件,算出這檔 CB 拆解(CBAS)後的<b>權利金成本、槓桿倍數、下檔風險、抱到期的預期報酬</b>,並判斷是否符合我們的進場準則。也能輸入本金,模擬「該買什麼、多久回本、賺賠機率」。</div>
  <div class="steps">
    <div class="step"><b>① 查一檔</b><br>上方搜尋框輸入代碼(股票/債券/現有CB)或公司名 → 按「分析」</div>
    <div class="step"><b>② 看能不能買</b><br>看綠色「✅ 可拆解」標記與白話結論;紅色代表不符準則或不划算</div>
    <div class="step"><b>③ 試算資金</b><br>填本金(如 50萬)按「資金模擬」→ 看預期賺賠、回本時間、機率</div>
  </div>
</div>

<div class="search">
  <h2>🔎 輸入代碼即時分析</h2>
  <div class="slabels"><span>代碼 / 公司名</span></div>
  <div class="sbar">
    <input id="scode" placeholder="例如:5289、11011、宜鼎、台泥" autocomplete="off">
    <input id="stcri" class="cap" type="number" min="1" max="9" placeholder="TCRI(選填)" title="現有可轉債查不到 TCRI 時可手動填 1-9">
    <button onclick="doAnalyze()">分析這一檔</button>
    <button onclick="doPrice()" style="background:linear-gradient(90deg,#0ea5e9,#38bdf8)">查現價</button>
    <input id="scap" class="cap" placeholder="本金 如 50萬">
    <button onclick="doSim()" style="background:linear-gradient(90deg,#10b981,#34d399)">資金模擬</button>
  </div>
  <div class="chips">
    <span class="chip" onclick="quick('5289')">宜鼎二 5289</span>
    <span class="chip" onclick="quick('2303')">聯電 2303</span>
    <span class="chip" onclick="quick('11011')">台泥一永 11011</span>
    <span class="chip" onclick="quickSim('50萬')">💰 模擬 50萬</span>
    <span class="chip" onclick="quickSim('1000萬')">💰 模擬 1000萬</span>
  </div>
  <div class="shint">現有可轉債(如 11011)若沒 TCRI,填一下右邊 TCRI 欄位判準則會更準;資金模擬留空代碼=用目前符合準則的標的。</div>
  <div id="sresult"></div>
</div>

<div class="portbox">
  <h2>💼 組合模擬 · 自己指定每檔買幾張(填 CB 現價=零誤差)</h2>
  <div class="sbar">
    <input id="pcode" class="w1" placeholder="代碼 如 5289" autocomplete="off">
    <input id="punits" class="w2" type="number" min="1" placeholder="張數">
    <input id="pcbp" class="w2" placeholder="CB現價">
    <input id="ptcri" class="w2" type="number" min="1" max="9" placeholder="TCRI">
    <button onclick="addLeg()">＋ 加入</button>
    <button onclick="runPort()" style="background:linear-gradient(90deg,#10b981,#34d399)">模擬組合</button>
  </div>
  <div id="plist"></div>
  <div class="shint">例:5289 買 3 張 + 11011 買 5 張。「CB現價」填你券商看到的可轉債報價(面額100),填了那一檔就用真價算、零誤差;沒填則用承銷/面額估。結果顯示在上方。</div>
</div>

<details class="gloss"><summary>名詞白話解釋(點開)</summary>
  <div class="gitem"><b>拆解 / CBAS</b>:買進可轉債後,把「債券本金」賣斷給銀行(資產交換),自己只留「可轉股的權利」。等於用一小筆權利金,控制一大筆股票漲幅——下檔最多賠光權利金,上檔跟著股票漲。</div>
  <div class="gitem"><b>轉換價值 parity</b>:現在把 CB 換成股票值多少(以面額 100 計)。parity &gt; 100 代表已價內、換股就賺。</div>
  <div class="gitem"><b>債券底</b>:CB 當純債券、抱到賣回/到期能拿回多少(折現後)。這塊拆解時賣給銀行,是下檔保護。</div>
  <div class="gitem"><b>權利金</b>:拆解後你實際要付的本金(≈ 買價 − 債券底 + 融資)。也是最大可能虧損。</div>
  <div class="gitem"><b>槓桿倍數</b>:parity ÷ 權利金。用小錢控制大曝險的倍數,越高越敏感。</div>
  <div class="gitem"><b>前瞻波動 / 隱含波動</b>:前瞻=用歷史股價估未來波動(選擇權該值多少);隱含=市場承銷/成交價反推的波動。前瞻 &gt; 隱含 = 選擇權相對便宜。</div>
  <div class="gitem"><b>理論價</b>:債券底 + 選擇權的理論合理價。高於買價代表便宜。</div>
  <div class="gitem"><b>老闆準則</b>:TCRI 3-4(信用夠好、銀行才肯承做資產交換)+ 發行量雙位數億(流動性足)。兩條都過才值得拆。</div>
</details>

<details class="gloss"><summary>📐 分析原理與方法(用什麼算、怎麼估值、資料哪來——點開看完整說明)</summary>
  <div class="gitem"><b>1. 資料來源(都是公開、可查證)</b><br>
    · 現股報價、歷史股價、外資/投信買賣超 → <b>FinMind</b>(免費 API)<br>
    · 現有可轉債的發行條件(轉換價、賣回日/價、到期、發行量、擔保)→ <b>證券櫃買中心 TPEx OpenAPI</b>(全市場 380+ 檔)<br>
    · 發行管線(尚未上市的新案)→ 老闆每期的 CB 發行案件 Excel<br>
    · 法說會重點、券商目標價 → 公開新聞/法說簡報查證後建檔(company_intel.json)</div>

  <div class="gitem"><b>2. 核心觀念:一張 CB = 債券底 + 轉換選擇權</b><br>
    可轉債同時是「債券」和「可轉股的選擇權」。拆解(CBAS)就是把債券底賣給銀行、自己留選擇權。所以估值 = 分別算這兩塊再相加。</div>

  <div class="gitem"><b>3. 轉換價值 parity</b><br>
    parity = 現股價 ÷ 轉換價 × 100(面額)。例:股價 1575、轉換價 2180 → parity = 72.2,代表現在換股只值 72(面額 100),即價外。</div>

  <div class="gitem"><b>4. 債券底(下檔保護)</b><br>
    把 CB 當純債券:賣回/到期能拿回的金額,用「無風險利率 + 信用利差」折現回今天。<br>
    公式:債券底 = 賣回價 ÷ (1 + r)^n,其中 r = 無風險利率 + TCRI 信用利差,n = 距賣回/到期年數。<br>
    信用越差(TCRI 數字越大)利差越高、折現越兇、債券底越低。</div>

  <div class="gitem"><b>5. 轉換選擇權(上檔動能)= Black-Scholes 買權</b><br>
    每張 CB 內含 (100 ÷ 轉換價) 股的買權,履約價 = 轉換價。用 Black-Scholes 定價:<br>
    <span style="color:#a5b4fc">d₁ = [ln(S/K) + (r + σ²/2)·T] ÷ (σ·√T)　,　d₂ = d₁ − σ·√T</span><br>
    <span style="color:#a5b4fc">買權 = S·N(d₁) − K·e^(−rT)·N(d₂)</span><br>
    S=現股價、K=轉換價、T=距賣回/到期年數、σ=前瞻波動率、N()=常態累積分佈。選擇權值 = (100÷K) × 買權。</div>

  <div class="gitem"><b>6. 波動率怎麼估(最關鍵的輸入)</b><br>
    · <b>前瞻波動</b>(定價用):取 20/60/120 日歷史報酬 + EWMA(RiskMetrics λ=0.94,近期加權),再以「短期 {A['vol_w_short']:.0%} + 長期 {A['vol_w_long']:.0%}」加權。長期權重高是因為 CB 存續 3-5 年、波動會均值回歸。<br>
    · <b>隱含波動</b>:用真實承銷/競拍價(或次級市價)反解出市場認為的波動。前瞻 &gt; 隱含 = 選擇權相對便宜。</div>

  <div class="gitem"><b>7. 理論價 & 拆解槓桿</b><br>
    理論 CB 價 = 債券底 + 選擇權值;高於買價 = 便宜。<br>
    權利金(拆解實付本金)≈ 買價 − 債券底 + 期間融資(資產交換 spread × 年數)。<br>
    槓桿 = parity ÷ 權利金。下檔:選擇權最差歸零,最多賠光權利金(債券底已賣給銀行)。</div>

  <div class="gitem"><b>8. 綜合評分 0–100(六維加權)</b><br>
    波動率價差 30 分(選擇權便不便宜)+ 理論 vs 買價 20 分 + Delta 甜蜜點 0.4–0.7 共 20 分 + 信用 TCRI 15 分 + 流動性/發行量 10 分 + 槓桿合理性 5 分。</div>

  <div class="gitem"><b>9. 老闆準則(硬閘門,先過才談分數)</b><br>
    TCRI ∈ {{3,4}} 且 發行量 ≥ 10 億。任一不過 → 直接淘汰(銀行不肯承做資產交換 / 流動性不足)。</div>

  <div class="gitem"><b>10. 資金模擬(蒙地卡羅)</b><br>
    用幾何布朗運動(GBM)模擬股價到到期:<span style="color:#a5b4fc">S_T = S₀·exp[(μ − σ²/2)·T + σ·√T·Z]</span>,Z 為常態亂數,μ=年報酬假設(保守0%/基準7%/樂觀15%),多檔間用單因子相關 ρ。每次模擬算拆解部位損益 = (max(到期parity − 賣回價, 0) − 權利金),跑 2 萬次得出<b>預期賺賠、獲利機率、P5/中位/P95</b>。<br>
    <b>回本時間</b>:解中位數路徑何時漲到回本點(parity = 賣回價 + 權利金),得「約幾年回本」。</div>

  <div class="gitem"><b>11. 市場情報怎麼用</b><br>
    外資/投信近 5/20 日淨買賣(FinMind)→ 法人在買還是賣;券商目標價 → 反推隱含年報酬校準模擬漂移,並做「現實檢查」(目標價隱含漲幅 &lt; 回本所需漲幅 → 即使達標也回不了本)。</div>

  <div class="gitem"><b>12. 目前假設參數</b><br>
    無風險利率 {A['rf']*100:.1f}% · 資產交換 spread {A['asset_swap_spread']*100:.1f}%/年 · TCRI 信用利差 {tcri_str}。全部可調(cb_config.json)。</div>

  <div class="gitem" style="color:#fbbf24"><b>⚠ 限制與免責</b><br>
    模型未精算交易稅、賣回時點、流動性折價;現有 CB 的轉換價為發行時價、實際可能經反稀釋調整;券商目標價可能落後;評分供<b>篩選排序</b>非下單訊號。進場前務必人工核對承銷條件與銀行資產交換實際報價。</div>
</details>
<div class="crit">📏 <b>老闆拆解準則(硬門檻)</b>:TCRI 須為 <b>3 或 4</b>(銀行才肯承做資產交換)且
發行量 <b>≥ 雙位數億(10億)</b>(流動性足)。兩條同時滿足才值得拆解 —— 本期已定價
<b>{len(elig)}</b> 檔符合({len(other)} 檔不符已略過)。</div>
<div class="sec ok">✅ 符合準則 · 值得拆解　<span style="font-size:11px;color:#8b95a7;font-weight:400">(點任一列看完整分析)</span></div>
<div class="twrap"><table><thead><tr><th>#</th><th>評分</th><th>名稱</th><th>代碼</th><th>評等</th><th>量</th><th>現價</th><th>parity</th>
<th>清算價</th><th>理論</th><th>隱波</th><th>前瞻波</th><th>槓桿</th><th>結論</th></tr></thead>
<tbody>{elig_rows}</tbody></table></div>
<div class="sec watch">👀 待定價觀察清單 · 符合準則但條件未定(盯著等承銷價)　<span style="font-size:11px;color:#8b95a7;font-weight:400">(點任一列看公司分析)</span></div>
<div class="twrap"><table><thead><tr><th>名稱</th><th>代碼</th><th>評等</th><th>量</th><th>年期</th><th>階段</th><th>主辦</th></tr></thead>
<tbody>{watch_rows}</tbody></table></div>
<div class="sec ok">📇 可拆解個案卡(已定價)</div>
<div class="cards">{cards}</div>
<div class="sec watch">🏢 待定價觀察 · 公司個案卡</div>
<div class="cards">{watch_cards}</div>
<div class="foot">
<b>假設參數</b>:rf {A['rf']*100:.1f}% · 資產交換 spread {A['asset_swap_spread']*100:.1f}% ·
前瞻波動加權 短{A['vol_w_short']:.0%}/長{A['vol_w_long']:.0%} · TCRI 信用利差 {tcri_str}<br>
<span class="warn">⚠ 隱含波動由真實承銷/競拍價反解;前瞻波動 = EWMA(短) 與 120日(長)加權(均值回歸)。
模型未精算交易稅/賣回時點/流動性折價,評分供篩選排序,進場前仍須人工核對承銷條件與資產交換報價。</span>
</div></div>
<script>
const R=document.getElementById('sresult');
function seeR(){{try{{R.scrollIntoView({{behavior:'smooth',block:'start'}});}}catch(e){{}}}}
function busy(m){{R.innerHTML='<div class="sloading">'+m+'…</div>';seeR();}}
function err(m){{R.innerHTML='<div class="serr">'+m+'</div>';seeR();}}
async function call(u){{
  const r=await fetch(u); const t=await r.text();
  if(!r.ok) throw new Error(t||('HTTP '+r.status));
  return t;
}}
function quick(c){{document.getElementById('scode').value=c;document.getElementById('scap').value='';doAnalyze();}}
function quickSim(cap){{document.getElementById('scap').value=cap;doSim();}}
async function doPrice(){{
  const c=document.getElementById('scode').value.trim();
  if(!c){{err('請先輸入代碼');return;}}
  const t=document.getElementById('stcri').value.trim();
  busy('查 '+c+' 現價中');
  try{{ R.innerHTML=await call('/api/price?code='+encodeURIComponent(c)+(t?'&tcri='+t:''));seeR(); }}
  catch(e){{ err('查詢失敗:'+e.message); }}
}}
let PLEGS=[];
function renderLegs(){{
  document.getElementById('plist').innerHTML=PLEGS.map((l,i)=>
    '<span class="pleg"><b>'+l.code+'</b> '+l.units+'張'+(l.cbp?' @'+l.cbp:'')+(l.tcri?' T'+l.tcri:'')+
    ' <span onclick="rmLeg('+i+')">✕</span></span>').join('');
}}
function addLeg(){{
  const code=document.getElementById('pcode').value.trim();
  const units=parseInt(document.getElementById('punits').value);
  if(!code||!(units>0)){{err('組合:請填代碼與張數');return;}}
  PLEGS.push({{code:code,units:units,
    cbp:document.getElementById('pcbp').value.trim(),
    tcri:document.getElementById('ptcri').value.trim()}});
  document.getElementById('pcode').value='';document.getElementById('punits').value='';
  document.getElementById('pcbp').value='';document.getElementById('ptcri').value='';
  renderLegs();
}}
function rmLeg(i){{PLEGS.splice(i,1);renderLegs();}}
async function runPort(){{
  if(!PLEGS.length){{err('組合是空的,先「＋加入」幾檔');return;}}
  const s=PLEGS.map(l=>l.code+':'+l.units+':'+(l.cbp||'')+':'+(l.tcri||'')).join(',');
  busy('組合蒙地卡羅模擬中');
  try{{ R.innerHTML=await call('/api/portfolio?legs='+encodeURIComponent(s));seeR(); }}
  catch(e){{ err('組合模擬失敗:'+e.message); }}
}}
async function doAnalyze(){{
  const c=document.getElementById('scode').value.trim();
  if(!c){{err('請先輸入代碼或名稱');return;}}
  const t=document.getElementById('stcri').value.trim();
  busy('分析 '+c+' 中');
  try{{ R.innerHTML=await call('/api/analyze?code='+encodeURIComponent(c)+(t?'&tcri='+t:''));seeR(); }}
  catch(e){{ err('分析失敗:'+e.message); }}
}}
async function doSim(){{
  const cap=document.getElementById('scap').value.trim();
  if(!cap){{err('請先輸入本金,例如 50萬 或 1000萬');return;}}
  const c=document.getElementById('scode').value.trim();
  const t=document.getElementById('stcri').value.trim();
  busy('蒙地卡羅模擬中');
  try{{ R.innerHTML=await call('/api/sim?capital='+encodeURIComponent(cap)+(c?'&code='+encodeURIComponent(c):'')+(t?'&tcri='+t:''));seeR(); }}
  catch(e){{ err('模擬失敗:'+e.message); }}
}}
document.getElementById('scode').addEventListener('keydown',e=>{{if(e.key==='Enter')doAnalyze();}});
document.getElementById('scap').addEventListener('keydown',e=>{{if(e.key==='Enter')doSim();}});
(function(){{const p=new URLSearchParams(location.search);
  if(p.get('doc'))document.querySelectorAll('details.gloss').forEach(d=>d.open=true);
  const q=p.get('q');
  if(q){{document.getElementById('scode').value=q;
    if(p.get('t'))document.getElementById('stcri').value=p.get('t');
    if(p.get('cap')){{document.getElementById('scap').value=p.get('cap');doSim();}}else{{doAnalyze();}}}}}})();
</script>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
