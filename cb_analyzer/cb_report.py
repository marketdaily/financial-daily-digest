"""把 rank() 結果輸出成自包含 HTML 報告(深色玻璃卡片風)。"""
import os, html, datetime
import cb_core

HERE = os.path.dirname(os.path.abspath(__file__))


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
    ve = a.get("vol_edge")
    auction = ""
    if a.get("auction_low"):
        auction = f"競拍 {a['auction_low']}~{a['auction_high']}"
    rows = f"""
    <div class="card">
      <div class="chead">
        <div><span class="nm">{html.escape(item['name'])}</span>
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
      <div class="reasons">{''.join(f'<span>{html.escape(r)}</span>' for r in a['score_reasons'])}</div>
    </div>"""
    return rows


def write_report(db, results, path=None):
    path = path or os.path.join(HERE, "report.html")
    A = cb_core.ASSUMPTIONS
    today = datetime.date.today().isoformat()
    rank_rows = ""
    for n, (item, sd, a) in enumerate(results, 1):
        vt, vc = _verdict(a["score"])
        rank_rows += (
            f'<tr><td>{n}</td><td class="sc" style="color:{vc}">{a["score"]:.0f}</td>'
            f'<td>{html.escape(item["name"])}</td><td>{item["stock_code"]}</td>'
            f'<td>{sd["spot"]:.1f}</td><td>{a["parity"]:.0f}</td>'
            f'<td>{a["issue_price"]:.0f}</td><td>{a["theoretical"]:.0f}</td>'
            f'<td>{_pct(a["implied_vol"],0)}</td><td>{_pct(a["hist_vol"],0)}</td>'
            f'<td>{a["leverage"]:.1f}×</td><td style="color:{vc}">{vt}</td></tr>')
    cards = "".join(_card(*r) for r in results)
    tcri_str = " · ".join(f"{k}:{v*100:.1f}%" for k, v in A["tcri_spread"].items())

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
</style></head><body><div class="wrap">
<h1>台股 CB 拆解吸引力分析</h1>
<div class="sub">來源 {html.escape(db['source_file'])} · 產出 {today} · 已定價 {len(results)} 檔 / 全表 {db['count']} 檔</div>
<table><thead><tr><th>#</th><th>評分</th><th>名稱</th><th>代碼</th><th>現價</th><th>parity</th>
<th>清算價</th><th>理論</th><th>隱波</th><th>前瞻波</th><th>槓桿</th><th>結論</th></tr></thead>
<tbody>{rank_rows}</tbody></table>
<div class="cards">{cards}</div>
<div class="foot">
<b>假設參數</b>:rf {A['rf']*100:.1f}% · 資產交換 spread {A['asset_swap_spread']*100:.1f}% ·
前瞻波動加權 短{A['vol_w_short']:.0%}/長{A['vol_w_long']:.0%} · TCRI 信用利差 {tcri_str}<br>
<span class="warn">⚠ 隱含波動由真實承銷/競拍價反解;前瞻波動 = EWMA(短) 與 120日(長)加權(均值回歸)。
模型未精算交易稅/賣回時點/流動性折價,評分供篩選排序,進場前仍須人工核對承銷條件與資產交換報價。</span>
</div></div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
