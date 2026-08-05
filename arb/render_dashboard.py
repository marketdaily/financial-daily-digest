"""把 dashboard_data.json 渲染成單檔 HTML 後台(可發布為 Artifact)。

用法: ./.venv/bin/python -m arb.render_dashboard [輸出路徑]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "dashboard.html")

TEMPLATE = """<title>進貨台 · 跨境套利</title>
<style>
:root{
  --bg:#F7F8FA; --surface:#FFFFFF; --surface-2:#F1F4F9;
  --ink:#171B24; --muted:#5C6478; --line:#E2E6ED;
  --accent:#2D4A7C; --accent-soft:#E8EEF8;
  --good:#3F6B4C; --warn:#966D09; --crit:#8F4522;
  --shadow:0 1px 2px rgba(23,27,36,.06),0 4px 16px rgba(23,27,36,.05);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#12151C; --surface:#1A1F2A; --surface-2:#222836;
    --ink:#E8ECF3; --muted:#8B94A8; --line:#2A3140;
    --accent:#6B93D6; --accent-soft:#1E2938;
    --good:#6FA37D; --warn:#D4A72C; --crit:#C77A5A;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
  }
}
:root[data-theme="dark"]{
  --bg:#12151C; --surface:#1A1F2A; --surface-2:#222836;
  --ink:#E8ECF3; --muted:#8B94A8; --line:#2A3140;
  --accent:#6B93D6; --accent-soft:#1E2938;
  --good:#6FA37D; --warn:#D4A72C; --crit:#C77A5A;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
}
:root[data-theme="light"]{
  --bg:#F7F8FA; --surface:#FFFFFF; --surface-2:#F1F4F9;
  --ink:#171B24; --muted:#5C6478; --line:#E2E6ED;
  --accent:#2D4A7C; --accent-soft:#E8EEF8;
  --good:#3F6B4C; --warn:#966D09; --crit:#8F4522;
  --shadow:0 1px 2px rgba(23,27,36,.06),0 4px 16px rgba(23,27,36,.05);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","PingFang TC",
    "Microsoft JhengHei",sans-serif;
  font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased;
}
.num{font-variant-numeric:tabular-nums;
  font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
.wrap{max-width:1080px; margin:0 auto; padding:28px 20px 72px}

header.top{display:flex; flex-wrap:wrap; align-items:baseline; gap:12px; margin-bottom:6px}
h1{font-size:26px; font-weight:680; letter-spacing:-.02em; margin:0}
.sub{color:var(--muted); font-size:13px; margin:0 0 22px}

.summary{display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line);
  border-radius:10px; overflow:hidden; margin-bottom:14px}
.cell{background:var(--surface); padding:14px 16px}
.cell .k{font-size:11px; letter-spacing:.09em; text-transform:uppercase;
  color:var(--muted); display:block; margin-bottom:5px}
.cell .v{font-size:23px; font-weight:640; letter-spacing:-.02em}
.cell .v.pos{color:var(--good)}

.note{background:var(--accent-soft); border-left:3px solid var(--accent);
  padding:11px 15px; border-radius:0 7px 7px 0; font-size:13px;
  color:var(--ink); margin-bottom:30px}

h2{font-size:12px; letter-spacing:.11em; text-transform:uppercase;
  color:var(--muted); font-weight:620; margin:34px 0 13px;
  padding-bottom:8px; border-bottom:1px solid var(--line)}

.card{background:var(--surface); border:1px solid var(--line);
  border-radius:11px; box-shadow:var(--shadow); margin-bottom:15px; overflow:hidden}
.card > .stripe{height:3px; background:var(--good)}
.card.b > .stripe{background:var(--warn)}
.card.test > .stripe{background:var(--muted)}
.chead{display:flex; flex-wrap:wrap; align-items:flex-start;
  gap:12px; padding:15px 18px 13px}
.chead .name{flex:1 1 240px; min-width:0}
.chead h3{margin:0 0 4px; font-size:17px; font-weight:620; letter-spacing:-.01em;
  text-wrap:balance}
.chead .meta{font-size:12.5px; color:var(--muted)}
.roi{text-align:right; flex:0 0 auto}
.roi b{display:block; font-size:27px; font-weight:680; letter-spacing:-.025em;
  line-height:1.05; color:var(--good)}
.roi.b b{color:var(--warn)}
.roi span{font-size:10.5px; letter-spacing:.09em; text-transform:uppercase;
  color:var(--muted)}

.pill{display:inline-block; font-size:10.5px; font-weight:640; letter-spacing:.06em;
  padding:2.5px 8px; border-radius:20px; text-transform:uppercase; vertical-align:2px;
  margin-left:7px}
.pill.a{background:var(--good); color:#fff}
.pill.b{background:var(--warn); color:#fff}
.pill.test{background:var(--muted); color:#fff}

.breakdown{display:flex; flex-wrap:wrap; gap:0; border-top:1px solid var(--line);
  background:var(--surface-2)}
.bd{flex:1 1 92px; padding:10px 14px; border-right:1px solid var(--line)}
.bd:last-child{border-right:0}
.bd .k{font-size:10.5px; color:var(--muted); display:block; letter-spacing:.05em}
.bd .v{font-size:14.5px; font-weight:600}
.bd.total .v{color:var(--accent)}

.livewrap{padding:13px 18px 17px; border-top:1px solid var(--line)}
.livehead{display:flex; justify-content:space-between; align-items:baseline;
  gap:10px; margin-bottom:9px}
.livehead .t{font-size:12px; letter-spacing:.07em; text-transform:uppercase;
  color:var(--muted); font-weight:620}
.tblscroll{overflow-x:auto}
table{width:100%; border-collapse:collapse; font-size:13.5px; min-width:520px}
th{text-align:left; font-size:10.5px; letter-spacing:.07em; text-transform:uppercase;
  color:var(--muted); font-weight:620; padding:0 10px 7px 0; white-space:nowrap}
th.r,td.r{text-align:right}
td{padding:8px 10px 8px 0; border-top:1px solid var(--line); vertical-align:middle}
td.title{max-width:330px; font-size:13px; line-height:1.4}
tr:first-child td{border-top:1px solid var(--line)}
.gain{color:var(--good); font-weight:620}
.muted-row{opacity:.55}
.gatechip{display:inline-block; font-size:10.5px; font-weight:620; padding:2px 7px;
  border-radius:20px; white-space:nowrap}
.gatechip.pass{background:var(--good); color:#fff}
.gatechip.warn{background:var(--warn); color:#fff}
.gatechip.blocked{background:var(--crit); color:#fff}

a.btn{display:inline-block; background:var(--accent); color:#fff; text-decoration:none;
  font-size:12.5px; font-weight:600; padding:6px 13px; border-radius:6px;
  white-space:nowrap; transition:opacity .15s}
a.btn:hover{opacity:.85}
a.btn.ghost{background:transparent; color:var(--accent);
  border:1px solid var(--accent); font-weight:560}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

.legomatrix{overflow-x:auto}
.legomatrix table{min-width:560px}
.best{background:var(--accent-soft)}

details{background:var(--surface); border:1px solid var(--line); border-radius:11px;
  padding:0; margin-top:15px; overflow:hidden}
summary{cursor:pointer; padding:14px 18px; font-weight:600; font-size:14px;
  list-style:none; display:flex; justify-content:space-between; align-items:center}
summary::-webkit-details-marker{display:none}
summary::after{content:"＋"; color:var(--muted); font-weight:400}
details[open] summary::after{content:"−"}
.deadbody{padding:0 18px 16px; font-size:13.5px}
.deadbody ul{margin:0; padding-left:19px; color:var(--muted)}
.deadbody li{margin-bottom:7px}
.deadbody b{color:var(--ink)}

footer{margin-top:34px; padding-top:16px; border-top:1px solid var(--line);
  font-size:12px; color:var(--muted); line-height:1.7}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:560px){
  .roi{flex-basis:100%; text-align:left}
  .bd{flex:1 1 46%}
}
</style>

<div class="wrap">
  <header class="top">
    <h1>進貨台</h1>
  </header>
  <p class="sub" id="stamp"></p>

  <div class="summary" id="summary"></div>
  <div class="note" id="headnote"></div>

  <h2>高爾夫線 · 日本拍賣 → 台灣</h2>
  <div id="golf"></div>

  <h2>樂高線 · 美國清倉 → 台灣</h2>
  <div id="lego"></div>

  <div id="dead"></div>

  <footer id="foot"></footer>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const n = v => (v == null ? '—' : Number(v).toLocaleString('en-US'));
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ---- 頂部總覽:只計 grade A/B 的建議首批 ---- */
// 總覽只計「四關全過」的現貨——沒過關的不該進投資總額
const BUYABLE = D.golf.flatMap(g => (g.live.items || [])
  .filter(x => x.ok_to_buy && x.margin_f2f)
  .map(x => ({...x, from: g.name})));
const cost = BUYABLE.reduce((a, x) => a + x.landed, 0);
const gain = BUYABLE.reduce((a, x) => a + x.margin_f2f, 0);
const roi = cost ? Math.round(gain / cost * 100) : 0;
document.getElementById('summary').innerHTML = [
  ['四關全過', BUYABLE.length + ' 件'],
  ['全買下來要', 'NT$' + n(cost)],
  ['預估淨利', 'NT$' + n(gain), 'pos'],
  ['整批 ROI', roi + '%', 'pos'],
  ['日圓匯率', D.rate_jpy_twd.toFixed(4)],
].map(([k, v, c]) =>
  `<div class="cell"><span class="k">${k}</span><span class="v ${c || ''}">${v}</span></div>`
).join('');

const dt = new Date(D.generated);
document.getElementById('stamp').textContent =
  '行情更新 ' + dt.toLocaleString('zh-TW', {hour12:false}) + '　·　匯率來源 ' + D.rate_source;

document.getElementById('headnote').innerHTML =
  '<b>怎麼用:</b>只有「四關」欄位是綠色的才可以買——它代表 ①台灣錨有足量樣本 ②規格世代相符 ' +
  '③賣家好評率 ≥99% ④現在可以下標,四項全過。灰掉的那幾列是查給你看的,不是建議買的。' +
  '所有成本已含日本國內運費、國際運費、關稅 5%、營業稅 5%;售價錨用台灣<b>實際刊登行情</b>' +
  '且經過樣本數與關鍵字漂移校正,不是代理商定價。';

/* ---- 高爾夫卡片 ---- */
document.getElementById('golf').innerHTML = D.golf.map(g => {
  const m = g.market || {};
  const cls = g.grade === 'A' ? '' : (g.grade === 'TEST' ? 'test' : 'b');
  const roiTxt = m.roi != null ? m.roi + '%' : '測試';
  const gate = it => {
    if (it.error) return {cls:'blocked', txt:'查驗失敗'};
    if (it.biddable === false) return {cls:'blocked', txt:'不可下標'};
    if (it.seller_rating == null) return {cls:'blocked', txt:'評價未知'};
    if (!it.ok_to_buy) return {cls:'warn', txt:`賣家 ${it.seller_rating}%`};
    return {cls:'pass', txt:`賣家 ${it.seller_rating}%`};
  };
  const rows = (g.live.items || []).map(it => {
    const gt = gate(it), pass = gt.cls === 'pass' && it.margin_f2f;
    return `
    <tr class="${pass ? '' : 'muted-row'}">
      <td class="title">${esc(it.title)}</td>
      <td class="r num">¥${n(it.jpy)}</td>
      <td class="r num">${n(it.landed)}</td>
      <td class="r num ${pass ? 'gain' : ''}">${it.margin_f2f ? '+' + n(it.margin_f2f) : '—'}</td>
      <td class="r num">${it.roi != null ? it.roi + '%' : '—'}</td>
      <td class="r"><span class="gatechip ${gt.cls}">${gt.txt}</span></td>
      <td class="r">${pass
        ? `<a class="btn" href="${it.buyee}" target="_blank" rel="noopener">去 Buyee 下標</a>`
        : `<a class="btn ghost" href="${it.buyee}" target="_blank" rel="noopener">查看</a>`}</td>
    </tr>`;}).join('');
  const liveTbl = g.sell ? `
    <div class="tblscroll"><table>
      <thead><tr><th>現在拍場上的貨</th><th class="r">日圓</th><th class="r">落地成本</th>
      <th class="r">淨利</th><th class="r">ROI</th><th class="r">四關</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : `
    <div class="tblscroll"><table>
      <thead><tr><th>現在拍場上的貨</th><th class="r">日圓</th><th class="r">落地成本</th>
      <th class="r">四關</th><th></th></tr></thead>
      <tbody>${(g.live.items || []).map(it => {
        const gt = gate(it);
        return `<tr class="muted-row"><td class="title">${esc(it.title)}</td>
        <td class="r num">¥${n(it.jpy)}</td><td class="r num">${n(it.landed)}</td>
        <td class="r"><span class="gatechip blocked">無台灣錨</span></td>
        <td class="r"><a class="btn ghost" href="${it.buyee}" target="_blank" rel="noopener">查看</a></td></tr>`;
      }).join('')}
      </tbody></table></div>`;
  return `
  <article class="card ${cls}">
    <div class="stripe"></div>
    <div class="chead">
      <div class="name">
        <h3>${esc(g.name)}<span class="pill ${cls || 'a'}">${g.grade}</span></h3>
        <div class="meta">${esc(g.tw_note)}</div>
      </div>
      <div class="roi ${cls}"><b>${roiTxt}</b><span>單筆 ROI</span></div>
    </div>
    <div class="breakdown">
      <div class="bd"><span class="k">日拍中位</span><span class="v num">¥${n(m.median_jpy)}</span></div>
      <div class="bd"><span class="k">30日成交</span><span class="v num">${n(m.count30d)} 筆</span></div>
      <div class="bd total"><span class="k">落地成本</span><span class="v num">${n(m.landed)}</span></div>
      <div class="bd"><span class="k">台灣售價</span><span class="v num">${g.sell ? n(g.sell) : '無錨'}</span></div>
      <div class="bd"><span class="k">面交淨利</span><span class="v num gain">${m.margin_f2f ? '+' + n(m.margin_f2f) : '—'}</span></div>
      <div class="bd"><span class="k">蝦皮淨利</span><span class="v num">${m.margin_shopee ? '+' + n(m.margin_shopee) : '—'}</span></div>
    </div>
    <div class="livewrap">
      <div class="livehead">
        <span class="t">拍場現貨 ${g.live.count} 件</span>
        <a class="btn ghost" href="${g.live.buyee_search}" target="_blank" rel="noopener">在 Buyee 看全部</a>
      </div>
      ${liveTbl}
    </div>
  </article>`;
}).join('');

/* ---- 樂高 ---- */
document.getElementById('lego').innerHTML = D.lego.map(L => {
  const best = L.scenarios.reduce((a, b) => b.margin > a.margin ? b : a);
  return `
  <article class="card">
    <div class="stripe"></div>
    <div class="chead">
      <div class="name">
        <h3>${esc(L.name)}</h3>
        <div class="meta">${L.pieces.toLocaleString()} 片 · 實重 ${L.weight_kg}kg · 材積重 ${L.vol_kg}kg ·
          計費 ${L.bill_kg}kg · ${esc(L.box)}<br>${esc(L.note)}</div>
      </div>
      <div class="roi"><b>${best.roi}%</b><span>最佳情境</span></div>
    </div>
    <div class="livewrap">
      <div class="legomatrix"><table>
        <thead><tr><th>情境</th><th class="r">美國進價</th><th class="r">運費</th>
        <th class="r">落地成本</th><th class="r">台灣售價</th><th class="r">淨利</th><th class="r">ROI</th></tr></thead>
        <tbody>${L.scenarios.map(s => `
          <tr class="${s === best ? 'best' : ''}">
            <td>${esc(s.label)}</td>
            <td class="r num">$${s.usd}</td>
            <td class="r num">${n(s.ship)}</td>
            <td class="r num">${n(s.landed)}</td>
            <td class="r num">${n(L.tw_sell)}</td>
            <td class="r num ${s.margin > 0 ? 'gain' : ''}">${s.margin > 0 ? '+' : ''}${n(s.margin)}</td>
            <td class="r num">${s.roi}%</td>
          </tr>`).join('')}
        </tbody></table></div>
      <div class="livehead" style="margin-top:12px">
        <span class="t">去哪買</span>
        <span>${L.links.map(([t, u]) =>
          `<a class="btn ghost" href="${u}" target="_blank" rel="noopener" style="margin-left:6px">${esc(t)}</a>`).join('')}</span>
      </div>
    </div>
  </article>`;
}).join('');

/* ---- 判死清單 ---- */
document.getElementById('dead').innerHTML = `
<details>
  <summary>已判死 / 暫緩的線(點開看死因,免得重複研究)</summary>
  <div class="deadbody"><ul>
    <li><b>盒裝 CPU</b> — 毛利率 6.7-8.7% 低於 Micro Center 所在各州銷售稅率 5.6-9%,數學上無解;
      且 Micro Center 在四個免稅州零分店。唯一活路=線上下單直寄 Oregon 免稅倉,需美國友人 5 分鐘實測。</li>
    <li><b>露營帳篷 / Arc'teryx</b> — 損益兩平買價 US$321 vs 全美最深清倉 US$320.99,價差為零;
      始祖鳥另有仿品把價格錨拉到公司貨兩折的檸檬市場問題。</li>
    <li><b>捲線器</b> — 台灣水貨行情已被壓到 NT$9,300-9,800,蝦皮抽 14% 後淨利為負,只有 FB 面交勉強 +500。</li>
    <li><b>有線 HHKB</b> — 台灣同行已把價格壓到 9,700-10,300,淨利僅 1,700-2,500 且月銷個位數。</li>
    <li><b>球鞋 / 無線類 / SSD / 保健美妝 / 嬰幼</b> — 價差倒掛,或 NCC/BSMI/食藥署層級的「賣了就違法」。</li>
    <li><b>Scotty Cameron Phantom</b> — 日拍中位 ¥58,864,落地 14,735 vs 台灣 15,800,淨利僅 1,065。</li>
  </ul></div>
</details>`;

document.getElementById('foot').innerHTML =
  'ROI = 單筆交易報酬率(淨利÷落地成本),<b>不是年化</b>——賣不掉就是 0,週轉速度要首批才知道。<br>' +
  '蝦皮淨利已扣 ' + (D.shopee_pct * 100) + '% + NT$' + D.shopee_flat + ';FB 社團面交零抽成,是主戰場。<br>' +
  '球桿出貨走黑貓「高爾夫宅急便」180cm/20kg 內本島單一價 NT$310,可直寄球場櫃檯。<br>' +
  '樂高運費為估值(空運 NT$375/kg、海運 NT$125/kg)待實測校準;樂高整盒放不進任何 USPS 統一費率箱。';
</script>
"""


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    with open(os.path.join(HERE, "dashboard_data.json"), encoding="utf-8") as f:
        data = json.load(f)
    for g in data["golf"]:
        g["live"] = {k: v for k, v in g["live"].items()
                     if k in ("count", "items", "buyee_search")}
        g["live"]["items"] = g["live"].get("items", [])[:5]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</script>", "<\\/script>")
    html = TEMPLATE.replace("__DATA__", payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"→ {out_path} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
