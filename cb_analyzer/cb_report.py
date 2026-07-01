"""把 rank() 結果輸出成自包含 HTML 報告(深色玻璃卡片風)。"""
import os, html, datetime
import cb_core
import cb_profiles

HERE = os.path.dirname(os.path.abspath(__file__))


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
                f'<tr><td>{n}</td><td class="sc" style="color:{vc}">{a["score"]:.0f}</td>'
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
        f'<tr><td>{html.escape(i["name"])}</td><td>{i["stock_code"]}</td>'
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
</style></head><body><div class="wrap">
<h1>台股 CB 拆解吸引力分析</h1>
<div class="sub">來源 {html.escape(db['source_file'])} · 產出 {today} · 已定價 {len(results)} 檔 / 全表 {db['count']} 檔</div>
<div class="crit">📏 <b>老闆拆解準則(硬門檻)</b>:TCRI 須為 <b>3 或 4</b>(銀行才肯承做資產交換)且
發行量 <b>≥ 雙位數億(10億)</b>(流動性足)。兩條同時滿足才值得拆解 —— 本期已定價
<b>{len(elig)}</b> 檔符合({len(other)} 檔不符已略過)。</div>
<div class="sec ok">✅ 符合準則 · 值得拆解</div>
<table><thead><tr><th>#</th><th>評分</th><th>名稱</th><th>代碼</th><th>評等</th><th>量</th><th>現價</th><th>parity</th>
<th>清算價</th><th>理論</th><th>隱波</th><th>前瞻波</th><th>槓桿</th><th>結論</th></tr></thead>
<tbody>{elig_rows}</tbody></table>
<div class="sec watch">👀 待定價觀察清單 · 符合準則但條件未定(盯著等承銷價)</div>
<table><thead><tr><th>名稱</th><th>代碼</th><th>評等</th><th>量</th><th>年期</th><th>階段</th><th>主辦</th></tr></thead>
<tbody>{watch_rows}</tbody></table>
<div class="sec ok">📇 可拆解個案卡(已定價)</div>
<div class="cards">{cards}</div>
<div class="sec watch">🏢 待定價觀察 · 公司個案卡</div>
<div class="cards">{watch_cards}</div>
<div class="foot">
<b>假設參數</b>:rf {A['rf']*100:.1f}% · 資產交換 spread {A['asset_swap_spread']*100:.1f}% ·
前瞻波動加權 短{A['vol_w_short']:.0%}/長{A['vol_w_long']:.0%} · TCRI 信用利差 {tcri_str}<br>
<span class="warn">⚠ 隱含波動由真實承銷/競拍價反解;前瞻波動 = EWMA(短) 與 120日(長)加權(均值回歸)。
模型未精算交易稅/賣回時點/流動性折價,評分供篩選排序,進場前仍須人工核對承銷條件與資產交換報價。</span>
</div></div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
