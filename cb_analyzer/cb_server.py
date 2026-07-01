"""本機小伺服器:服務儀表板 + 搜尋框後端。
  GET /                     → index.html(儀表板,含搜尋框)
  GET /api/analyze?code=&tcri=   → 該代碼完整分析卡(HTML 片段)
  GET /api/sim?capital=&code=&tcri= → 資金模擬結果(HTML 片段)
啟動:python3 cb_server.py [port]   預設 8911。"""
import os, sys, html, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cb_core, cb_data, cb_profiles, cb_intel, cb_simulate, cb_report
import cb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = cb.load_db()
VW = lambda: (cb_core.ASSUMPTIONS["vol_w_short"], cb_core.ASSUMPTIONS["vol_w_long"])


def analyze_fragment(code, tcri=None):
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
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"])
        if a.get("ok"):
            cards.append(cb_report._card(it, sd, a))
    return '<div class="cards">' + "".join(cards) + "</div>"


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


def sim_fragment(capital, code=None, tcri=None, drift=0.07):
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
        a = cb_core.analyze(it, sd["spot"], sd["vol_blend"])
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
    for L in base["legs"]:
        it = L["item"]
        oob = (L["spot"] / L["K"] - 1) * 100
        bey = ("約 %.1f 年" % L["be_years"]) if L["be_years"] else "中位數到不了(需高於預期漲勢)"
        o.append('<div class="simrow"><b>▶ 買進 %s(股%s/債%s)</b>　%d 口 = NT$%s　現價 %.1f / 轉換價 %s</div>'
                 % (html.escape(it["name"]), it["stock_code"], it["bond_code"],
                    L["units"], f"{L['deployed']:,.0f}", L["spot"], L["K"]))
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
        o.append('<div class="simrow"><span class="yy">⌛ 抱到期 %.1f 年　獲利機率 <b>%.0f%%</b></span>　'
                 '下檔最多賠光權利金 NT$%s</div>'
                 % (L["T"], L["prob_profit"] * 100, f"{L['deployed']:,.0f}"))

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
             '假設 GBM+前瞻波動+相關ρ%.2f,下檔封頂權利金,未計稅費。</div>'
             % (f"{base['p5']:+,.0f}", f"{base['p50']:+,.0f}", f"{base['p95']:+,.0f}", base["rho"]))
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
            if u.path == "/api/analyze":
                tc = g("tcri")
                return self._send(200, analyze_fragment(g("code") or "", int(tc) if tc else None))
            if u.path == "/api/sim":
                tc = g("tcri")
                return self._send(200, sim_fragment(g("capital") or "", g("code"),
                                                    int(tc) if tc else None))
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
