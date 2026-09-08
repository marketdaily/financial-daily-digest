#!/usr/bin/env python3
"""白牌週報 HTML:KPI 表 + 本週動作與理由 + 可稽核戳記。

  python -m marketing.adops.report --ledger marketing/adops/ledger/insights_act_FIXTURE.jsonl --client "皇海科技" \
      --agency "QFX Solution" --until 2026-09-08 --out marketing/adops/out/weekly_kingconn.html

報表裡沒有任何預估或編造:所有數字都從帳本列聚合;動作卡來自 optimizer;戳記讓客戶可用同一份帳本重算。
"""
import argparse
import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from marketing.adops.insights_pull import load_ledger  # noqa: E402
from marketing.adops.optimizer import aggregate, load_rules, run as optimize  # noqa: E402

ACTION_ZH = {"PAUSE": "暫停", "SWAP_CREATIVE": "換素材", "SCALE_UP": "加碼", "WATCH": "觀察", "HOLD": "樣本不足"}
ACTION_COLOR = {"PAUSE": "#B42318", "SWAP_CREATIVE": "#B54708", "SCALE_UP": "#067647", "WATCH": "#175CD3", "HOLD": "#667085"}


def _n(v, d=0):
    if v is None:
        return "—"
    return f"{v:,.{d}f}"


def kpi_totals(entities):
    t = {"spend": 0.0, "impressions": 0, "reach": 0, "clicks": 0, "conversions": 0.0}
    for e in entities:
        for k in t:
            t[k] += e[k]
    t["ctr"] = round(100.0 * t["clicks"] / t["impressions"], 2) if t["impressions"] else 0.0
    t["cpc"] = round(t["spend"] / t["clicks"], 2) if t["clicks"] else None
    t["cpm"] = round(1000.0 * t["spend"] / t["impressions"], 2) if t["impressions"] else None
    t["cpa"] = round(t["spend"] / t["conversions"], 2) if t["conversions"] else None
    return t


def build(ledger, client, agency, until=None, rules=None, prev=True):
    rules = rules or load_rules()
    res = optimize(ledger, until, rules)
    rows = load_ledger(Path(ledger))
    w = res["window"]
    cur_rows = [r for r in rows if w["since"] <= r["date"] <= w["until"]]
    p_until = (datetime.fromisoformat(w["since"]) - timedelta(days=1)).date().isoformat()
    p_since = (datetime.fromisoformat(p_until) - timedelta(days=w["days"] - 1)).date().isoformat()
    prev_rows = [r for r in rows if p_since <= r["date"] <= p_until]
    camps = sorted(aggregate(cur_rows, "campaign"), key=lambda e: -e["spend"])
    tot = kpi_totals(aggregate(cur_rows, "ad") or camps)
    ptot = kpi_totals(aggregate(prev_rows, "ad")) if prev_rows else None
    fixture = res["sources"] == ["fixture"]
    cur = rules.get("currency", "TWD")

    def delta(k, d=0, pct=True):
        if not ptot or ptot.get(k) in (None, 0) or tot.get(k) is None:
            return ""
        ch = (tot[k] - ptot[k]) / ptot[k] * 100
        return f'<span class="d" style="color:{"#067647" if ch >= 0 else "#B42318"}">{ch:+.0f}% vs 上週</span>'

    tiles = [("廣告花費", f"{cur} {_n(tot['spend'])}", delta("spend")), ("曝光", _n(tot["impressions"]), delta("impressions")),
             ("觸及", _n(tot["reach"]), delta("reach")), ("點擊 / CTR", f"{_n(tot['clicks'])} / {tot['ctr']}%", delta("ctr")),
             ("CPC / CPM", f"{_n(tot['cpc'], 1)} / {_n(tot['cpm'], 1)}", delta("cpc")),
             ("轉換 / CPA", f"{_n(tot['conversions'])} / {_n(tot['cpa'])}", delta("cpa"))]
    tile_html = "".join(f'<div class="tile"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div>{d}</div>' for k, v, d in tiles)
    camp_html = "".join(
        f"<tr><td>{html.escape(str(e['name']))}</td><td class=r>{_n(e['spend'])}</td><td class=r>{_n(e['impressions'])}</td>"
        f"<td class=r>{e['ctr']}%</td><td class=r>{_n(e['cpc'], 1)}</td><td class=r>{_n(e['frequency'], 2)}</td>"
        f"<td class=r>{_n(e['conversions'])}</td><td class=r>{_n(e['cpa'])}</td></tr>" for e in camps)
    acts = [r for r in res["recommendations"] if r["action"] != "WATCH"]
    watch = [r for r in res["recommendations"] if r["action"] == "WATCH"]
    act_html = "".join(
        f'<div class="act"><span class="tag" style="background:{ACTION_COLOR[r["action"]]}">{ACTION_ZH[r["action"]]}</span>'
        f'<b>{html.escape(str(r["name"]))}</b> <small>({r["level"]} · {html.escape(str(r["campaign_name"]))})</small>'
        f'<div class="why">{html.escape(r["reason"])}</div></div>' for r in acts) or "<p>本週沒有需要動作的項目。</p>"
    watch_html = "".join(f"<li><b>{html.escape(str(r['name']))}</b> — {html.escape(r['reason'])}</li>" for r in watch)
    a = res["audit"]
    banner = ('<div class="warn">🧪 本報表由合成 fixture 產生(非真實帳戶),僅示範格式與規則。</div>' if fixture else "")
    doc = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>{html.escape(client)} 廣告週報 {w['since']}–{w['until']}</title>
<style>
body{{font-family:-apple-system,"Noto Sans TC",Segoe UI,sans-serif;color:#101828;margin:0;background:#fff}}
.wrap{{max-width:900px;margin:0 auto;padding:40px 32px}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:32px 0 12px;border-bottom:1px solid #EAECF0;padding-bottom:6px}}
.meta{{color:#667085;font-size:13px}} .tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}}
.tile{{border:1px solid #EAECF0;border-radius:8px;padding:14px}} .tile .k{{font-size:12px;color:#667085}} .tile .v{{font-size:20px;font-weight:600;margin-top:4px}} .d{{font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:8px 6px;border-bottom:1px solid #EAECF0;text-align:left}} td.r,th.r{{text-align:right}} th{{color:#667085;font-weight:500}}
.act{{border:1px solid #EAECF0;border-radius:8px;padding:12px 14px;margin-bottom:10px}} .tag{{display:inline-block;color:#fff;font-size:12px;padding:2px 8px;border-radius:4px;margin-right:8px}}
.why{{color:#475467;font-size:13px;margin-top:6px}} .warn{{background:#FFFAEB;border:1px solid #FEDF89;color:#B54708;padding:10px 14px;border-radius:8px;font-size:13px;margin-top:16px}}
.audit{{background:#F9FAFB;border-radius:8px;padding:14px;font-size:12px;color:#475467;font-family:ui-monospace,Menlo,monospace;line-height:1.7}}
.foot{{color:#98A2B3;font-size:12px;margin-top:32px;line-height:1.6}}
</style></head><body><div class="wrap">
<h1>{html.escape(client)} 廣告成效週報</h1>
<div class="meta">期間 {w['since']} – {w['until']}(共 {w['days']} 天) · 平台 Meta(Facebook / Instagram) · 出具 {html.escape(agency)} · 貨幣 {cur}</div>
{banner}
<div class="tiles">{tile_html}</div>
<h2>活動層表現</h2>
<table><thead><tr><th>活動</th><th class=r>花費</th><th class=r>曝光</th><th class=r>CTR</th><th class=r>CPC</th><th class=r>頻率</th><th class=r>轉換</th><th class=r>CPA</th></tr></thead><tbody>{camp_html}</tbody></table>
<h2>本週動作與理由</h2>
{act_html}
<h2>維持觀察</h2>
<ul>{watch_html or '<li>無</li>'}</ul>
<h2>可稽核戳記</h2>
<div class="audit">data_hash {a['data_hash']} · rows {res['rows_in_window']} · source {','.join(res['sources'])}<br>
rules {a['rules_version']} / {a['rules_hash']}(CPA 目標 {rules.get('cpa_target')} · CTR 地板 {rules.get('ctr_floor_pct')}% · 頻率上限 {rules.get('frequency_cap')} · 判讀門檻 曝光 {rules.get('min_impressions')} / 花費 {rules.get('min_spend')})<br>
generated {res['generated_at']} · {a['automation']}</div>
<div class="foot">數據來源:Meta Marketing API insights(帳戶所有權屬客戶,{html.escape(agency)} 以合作夥伴存取讀取)。本報表中的「動作」皆為建議,任何帳戶變更均經客戶確認後由專人執行;報表不含預估或推算數字。
廣告內容之真實性由廣告主負責,{html.escape(agency)} 依公平交易法第 21 條對明知或可得而知之不實廣告負連帶責任,故上線前一律經素材合規審查。</div>
</div></body></html>"""
    return doc, res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--agency", default="QFX Solution")
    ap.add_argument("--until")
    ap.add_argument("--profile")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    doc, res = build(a.ledger, a.client, a.agency, a.until, load_rules(a.profile))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(doc, encoding="utf-8")
    print(f"週報 → {a.out}  ({len(doc):,} bytes;動作 {sum(v for k, v in res['counts'].items() if k != 'WATCH')} 項;audit {res['audit']['data_hash']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
