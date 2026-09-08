#!/usr/bin/env python3
"""規則式優化器:讀 insights 帳本 → 每個 ad/adset 的建議(PAUSE / SCALE_UP / SWAP_CREATIVE / HOLD / WATCH)。

  python -m marketing.adops.optimizer --ledger marketing/adops/ledger/insights_act_FIXTURE.jsonl --until 2026-09-08
  python -m marketing.adops.optimizer --ledger ... --profile client_rules.json --json

⚠️ 只輸出建議與理由,沒有任何寫入 Meta 的呼叫;「加碼 +20%」是給人看的動作卡,不是 API 指令。
每份輸出附 audit 戳記:data_hash(輸入列)+ rules_version + rules_hash,任何人可用同一份帳本重算驗證。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "rules.json"
sys.path.insert(0, str(HERE.parent.parent))
from marketing.adops.insights_pull import load_ledger, data_hash  # noqa: E402

ACTIONS = ("PAUSE", "SWAP_CREATIVE", "SCALE_UP", "WATCH", "HOLD")


def load_rules(profile=None):
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    if profile:
        rules.update({k: v for k, v in json.loads(Path(profile).read_text(encoding="utf-8")).items() if not k.startswith("_")})
        rules["profile"] = str(profile)
    return rules


def rules_hash(rules):
    return hashlib.sha256(json.dumps({k: v for k, v in rules.items() if not k.startswith("_")}, sort_keys=True).encode()).hexdigest()[:12]


def aggregate(rows, level):
    """把窗口內每日列聚合成一個實體一列。frequency 用 impressions/reach 重算(每日 frequency 平均是錯的)。"""
    out = {}
    for r in rows:
        if r["level"] != level:
            continue
        o = out.setdefault(r["id"], {
            "id": r["id"], "name": r["name"], "level": level, "campaign_name": r.get("campaign_name"),
            "adset_name": r.get("adset_name"), "objective": r.get("objective"), "currency": r.get("currency"),
            "conversion_type": r.get("conversion_type"), "spend": 0.0, "impressions": 0, "reach": 0,
            "clicks": 0, "link_clicks": 0, "conversions": 0.0, "days": 0, "sources": set(),
        })
        o["spend"] += r["spend"]; o["impressions"] += r["impressions"]; o["reach"] += r["reach"]
        o["clicks"] += r["clicks"]; o["link_clicks"] += r["link_clicks"]; o["conversions"] += r["conversions"]
        o["days"] += 1; o["sources"].add(r.get("source"))
    for o in out.values():
        imp, cl, sp, cv = o["impressions"], o["clicks"], o["spend"], o["conversions"]
        o["ctr"] = round(100.0 * cl / imp, 4) if imp else 0.0
        o["cpc"] = round(sp / cl, 2) if cl else None
        o["cpm"] = round(1000.0 * sp / imp, 2) if imp else None
        o["frequency"] = round(imp / o["reach"], 2) if o["reach"] else None
        o["cpa"] = round(sp / cv, 2) if cv else None
        o["spend"] = round(sp, 2)
        o["sources"] = sorted(s for s in o["sources"] if s)
    return list(out.values())


def decide(e, rules):
    """回 (action, reason, evidence)。順序=風險優先:樣本不足 > 疲勞 > CTR 死 > CPA 爆 > CPA 好 > 觀察。
    邊界:等於門檻不觸發(ctr == floor 不算低;frequency == cap 不算疲勞;cpa == target*ratio 走保守側)。"""
    ev = {k: e.get(k) for k in ("spend", "impressions", "clicks", "ctr", "cpc", "cpm", "frequency", "conversions", "cpa", "days")}
    if e["impressions"] < rules["min_impressions"] or e["spend"] < rules["min_spend"]:
        return "HOLD", (f"樣本不足:曝光 {e['impressions']:,} / 花費 {e['spend']:,.0f} 低於判讀門檻"
                        f"(曝光 ≥{rules['min_impressions']:,} 且花費 ≥{rules['min_spend']:,});不對雜訊動手"), ev
    if e["frequency"] is not None and e["frequency"] > rules["frequency_cap"]:
        return "SWAP_CREATIVE", (f"素材疲勞:頻率 {e['frequency']} 超過上限 {rules['frequency_cap']}"
                                 f"(同一人平均已看 {e['frequency']} 次,CTR {e['ctr']}%);換素材而非加預算"), ev
    if e["ctr"] < rules["ctr_floor_pct"]:
        return "PAUSE", f"CTR {e['ctr']}% 低於地板 {rules['ctr_floor_pct']}%(曝光 {e['impressions']:,} 已足夠判讀);建議暫停並改 hook", ev
    has_conv_goal = e.get("conversion_type") is not None and rules.get("cpa_target")
    if has_conv_goal:
        if e["conversions"] == 0:
            return "WATCH", f"已花 {e['spend']:,.0f} 零轉換({e['clicks']} 點擊);再觀察一個窗口,若仍零轉換轉 PAUSE", ev
        if e["cpa"] > rules["cpa_target"] * rules["cpa_pause_ratio"]:
            return "PAUSE", (f"CPA {e['cpa']:,.0f} 超過目標 {rules['cpa_target']:,} 的 {rules['cpa_pause_ratio']}×"
                             f"(轉換 {e['conversions']:.0f} 次);建議暫停"), ev
        if e["cpa"] < rules["cpa_target"] * rules["cpa_scale_ratio"] and e["conversions"] >= rules["min_conversions_for_scale"]:
            return "SCALE_UP", (f"CPA {e['cpa']:,.0f} 優於目標 {rules['cpa_target']:,} 的 {rules['cpa_scale_ratio']}×"
                                f"且轉換 {e['conversions']:.0f} ≥ {rules['min_conversions_for_scale']};建議預算 +{rules['scale_step_pct']}%(逐日,CPA 開始劣化即停)"), ev
        return "WATCH", f"CPA {e['cpa']:,.0f} 在目標帶內(目標 {rules['cpa_target']:,});維持", ev
    if rules.get("cpc_ceiling") and e["cpc"] is not None and e["cpc"] > rules["cpc_ceiling"]:
        return "PAUSE", f"CPC {e['cpc']} 超過上限 {rules['cpc_ceiling']}(無轉換目標的流量活動以 CPC 判);建議暫停", ev
    return "WATCH", f"無轉換事件可判(目標 {e.get('objective')});CTR {e['ctr']}% / CPC {e['cpc']} 正常,維持", ev


def run(ledger, until=None, rules=None, levels=("ad", "adset")):
    rules = rules or load_rules()
    rows = load_ledger(Path(ledger))
    if not rows:
        raise SystemExit(f"帳本空:{ledger}")
    until = until or max(r["date"] for r in rows)
    since = (datetime.fromisoformat(until) - timedelta(days=rules["window_days"] - 1)).date().isoformat()
    win = [r for r in rows if since <= r["date"] <= until]
    recs = []
    for level in levels:
        for e in aggregate(win, level):
            action, reason, ev = decide(e, rules)
            recs.append({"level": level, "id": e["id"], "name": e["name"], "campaign_name": e["campaign_name"],
                         "adset_name": e["adset_name"], "action": action, "reason": reason, "evidence": ev,
                         "sources": e["sources"]})
    order = {a: i for i, a in enumerate(ACTIONS)}
    recs.sort(key=lambda r: (order[r["action"]], r["level"], -(r["evidence"]["spend"] or 0)))
    sources = sorted({s for r in win for s in [r.get("source")] if s})
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"since": since, "until": until, "days": rules["window_days"]},
        "rows_in_window": len(win), "sources": sources,
        "audit": {"data_hash": data_hash(win), "rules_version": rules["version"], "rules_hash": rules_hash(rules),
                  "ledger": str(ledger), "automation": "recommend-only;no account writes"},
        "rules": {k: v for k, v in rules.items() if not k.startswith("_")},
        "counts": {a: sum(1 for r in recs if r["action"] == a) for a in ACTIONS},
        "recommendations": recs,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--until")
    ap.add_argument("--profile", help="客戶規則覆寫 JSON")
    ap.add_argument("--out", help="寫 JSON 到檔")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.ledger, a.until, load_rules(a.profile))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    src = "🧪 FIXTURE" if res["sources"] == ["fixture"] else ",".join(res["sources"])
    print(f"Ad Ops optimizer  窗口 {res['window']['since']}→{res['window']['until']}  來源 {src}  列 {res['rows_in_window']}")
    print(f"  audit data_hash={res['audit']['data_hash']} rules={res['audit']['rules_version']}/{res['audit']['rules_hash']}")
    print("  " + "  ".join(f"{k} {v}" for k, v in res["counts"].items()))
    for r in res["recommendations"]:
        ev = r["evidence"]
        print(f"  [{r['action']:<13}] {r['level']:<6} {r['name']:<22} spend {ev['spend']:>9,.0f} ctr {ev['ctr']:>5}% "
              f"freq {ev['frequency']} conv {ev['conversions']:.0f} cpa {ev['cpa']}\n{'':17}{r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
