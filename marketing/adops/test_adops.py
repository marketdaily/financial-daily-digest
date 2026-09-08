#!/usr/bin/env python3
"""adops 積木測試:fixture 跑通 / 冪等 / 規則邊界 / 報表戳記 / 零寫入。
零斷言 → exit 2(守衛自殺偵測);任何失敗 → exit 1。全部在 tmp 目錄跑,不碰 marketing/adops/ledger。"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from marketing.adops import insights_pull as ip, optimizer as op, report as rp  # noqa: E402

N = 0
FAILS = []


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}")
    else:
        print(f"  ✓ {msg}")


def entity(**kw):
    base = dict(id="x", name="x", level="ad", campaign_name="c", adset_name="s", objective="OUTCOME_LEADS", currency="TWD",
                conversion_type="lead", spend=5000.0, impressions=20000, reach=10000, clicks=300, link_clicks=280,
                conversions=10.0, days=7, sources=["fixture"])
    base.update(kw)
    e = base
    e["ctr"] = round(100.0 * e["clicks"] / e["impressions"], 4) if e["impressions"] else 0.0
    e["cpc"] = round(e["spend"] / e["clicks"], 2) if e["clicks"] else None
    e["cpm"] = round(1000.0 * e["spend"] / e["impressions"], 2) if e["impressions"] else None
    e["frequency"] = round(e["impressions"] / e["reach"], 2) if e["reach"] else None
    e["cpa"] = round(e["spend"] / e["conversions"], 2) if e["conversions"] else None
    return e


def main():
    tmp = Path(tempfile.mkdtemp(prefix="adops_test_"))
    try:
        ip.LEDGER_DIR = tmp  # 測試絕不寫進 repo 帳本
        print("① fixture 跑通 + 冪等")
        s1, rows = ip.pull("2026-09-02", "2026-09-08", dry_run=True, env={})
        check(s1["source"] == "fixture" and s1["rows"] == 77, f"fixture 77 列,source=fixture(得 {s1['rows']},{s1['source']})")
        check(all(r["source"] == "fixture" for r in rows), "每列都標 source=fixture")
        check(s1["note"].startswith("dry-run"), "note 明標 dry-run")
        s2, _ = ip.pull("2026-09-02", "2026-09-08", dry_run=True, env={})
        check(s2["added"] == 0 and s2["updated"] == 77 and s2["ledger_total"] == 77, "重跑冪等:新增 0 / 更新 77 / 總數 77")
        check(s1["data_hash"] == s2["data_hash"], "data_hash 重跑一致")
        s3, _ = ip.pull("2026-09-08", "2026-09-08", dry_run=False, env={"META_ADS_TOKEN": "", "META_AD_ACCOUNT_ID": ""})
        check(s3["source"] == "fixture" and "缺" in s3["note"], "沒憑證自動退 fixture 且講出缺什麼")
        ledger = ip.ledger_path("act_FIXTURE")

        print("② optimizer 設計行為")
        res = op.run(ledger, "2026-09-08")
        by = {r["id"]: r["action"] for r in res["recommendations"]}
        check(by.get("ad_3001") == "SCALE_UP", "winner ad_3001 → SCALE_UP")
        check(by.get("ad_3002") == "SWAP_CREATIVE", "fatigue ad_3002 → SWAP_CREATIVE")
        check(by.get("ad_3003") == "PAUSE", "lowctr ad_3003 → PAUSE")
        check(by.get("ad_3004") == "HOLD", "thin ad_3004 → HOLD")
        check(by.get("ad_3005") == "WATCH" and by.get("ad_3006") == "WATCH", "TRAFFIC 無轉換事件 → WATCH")
        check(res["audit"]["data_hash"] == s1["data_hash"], "optimizer audit data_hash == pull data_hash")
        check(res["sources"] == ["fixture"], "optimizer 標出來源 fixture")

        print("③ 規則邊界(等於門檻不觸發)")
        R = op.load_rules()
        a, _, _ = op.decide(entity(impressions=100000, reach=100000, clicks=int(100000 * R["ctr_floor_pct"] / 100)), R)
        check(a != "PAUSE", f"CTR == 地板 {R['ctr_floor_pct']}% 不暫停(得 {a})")
        a, _, _ = op.decide(entity(impressions=100000, reach=100000, clicks=int(100000 * R["ctr_floor_pct"] / 100) - 1), R)
        check(a == "PAUSE", "CTR 低於地板一點點 → PAUSE")
        a, _, _ = op.decide(entity(impressions=35000, reach=10000), R)
        check(a != "SWAP_CREATIVE", f"frequency == cap {R['frequency_cap']} 不算疲勞(得 {a})")
        a, _, _ = op.decide(entity(impressions=35100, reach=10000), R)
        check(a == "SWAP_CREATIVE", "frequency 3.51 超過 cap → SWAP_CREATIVE")
        a, _, _ = op.decide(entity(impressions=R["min_impressions"], reach=1000, clicks=100), R)
        check(a != "HOLD", "impressions == min 不算樣本不足")
        a, _, _ = op.decide(entity(impressions=R["min_impressions"] - 1, reach=1000, clicks=100), R)
        check(a == "HOLD", "impressions == min-1 → HOLD")
        a, _, _ = op.decide(entity(spend=R["min_spend"] - 0.01), R)
        check(a == "HOLD", "spend 低於 min_spend → HOLD")
        tgt = R["cpa_target"]
        a, _, _ = op.decide(entity(spend=tgt * R["cpa_scale_ratio"] * 10, conversions=10.0), R)
        check(a == "WATCH", "CPA == target×scale_ratio 走保守側(WATCH)")
        a, _, _ = op.decide(entity(spend=tgt * R["cpa_scale_ratio"] * 10 - 1, conversions=10.0), R)
        check(a == "SCALE_UP", "CPA 略優於 target×scale_ratio → SCALE_UP")
        a, _, _ = op.decide(entity(spend=max(R["min_spend"], 1.0) + 100, conversions=float(R["min_conversions_for_scale"] - 1),
                                   impressions=20000, reach=10000, clicks=300), R)
        check(a == "WATCH", "CPA 很好但轉換數 < min_conversions_for_scale → 不加碼")
        a, _, _ = op.decide(entity(spend=tgt * R["cpa_pause_ratio"] * 10, conversions=10.0), R)
        check(a == "WATCH", "CPA == target×pause_ratio 不暫停")
        a, _, _ = op.decide(entity(spend=tgt * R["cpa_pause_ratio"] * 10 + 1, conversions=10.0), R)
        check(a == "PAUSE", "CPA 超過 target×pause_ratio → PAUSE")
        a, r_, _ = op.decide(entity(conversions=0.0), R)
        check(a == "WATCH" and "零轉換" in r_, "有花費零轉換 → WATCH 並講明")
        a, _, _ = op.decide(entity(reach=0, impressions=20000), R)
        check(a in ("WATCH", "SCALE_UP"), "reach=0(frequency None)不崩潰")
        a, _, _ = op.decide(entity(conversion_type=None, conversions=0.0, objective="OUTCOME_TRAFFIC"), R)
        check(a == "WATCH", "無轉換事件的活動走 CTR/CPC 判 → WATCH")
        R2 = dict(R, cpc_ceiling=10)
        a, _, _ = op.decide(entity(conversion_type=None, conversions=0.0, objective="OUTCOME_TRAFFIC", spend=6000.0, clicks=300), R2)
        check(a == "PAUSE", "設 cpc_ceiling 後 CPC 超標 → PAUSE")
        prof = tmp / "profile.json"
        prof.write_text(json.dumps({"cpa_target": 100, "_note": "x"}), encoding="utf-8")
        R3 = op.load_rules(prof)
        check(R3["cpa_target"] == 100 and R3["ctr_floor_pct"] == R["ctr_floor_pct"], "客戶 profile 覆寫只蓋指定鍵")
        check(op.rules_hash(R3) != op.rules_hash(R), "規則改了 rules_hash 就變")

        print("④ 報表")
        doc, res2 = rp.build(ledger, "測試客戶", "QFX Solution", "2026-09-08")
        check("🧪" in doc and "fixture" in doc, "fixture 報表帶合成資料警示")
        check(res2["audit"]["data_hash"] in doc and res2["audit"]["rules_hash"] in doc, "報表印出 data_hash 與 rules_hash")
        body = doc.replace("報表不含預估或推算數字", "")
        check("預估" not in body and "推算" not in body, "報表不含預估/推算字眼(除免責聲明本句)")
        check(doc.count('class="act"') == sum(v for k, v in res2["counts"].items() if k != "WATCH"), "動作卡數 == 非 WATCH 建議數")
        check("公平交易法第 21 條" in doc, "報表帶代理商連帶責任揭露")
        check("不自動" in doc or "recommend-only" in doc, "報表聲明只建議不自動改帳戶")

        print("⑤ 零寫入守衛(原始碼層)")
        src = "".join(Path(ROOT / "marketing/adops" / f).read_text(encoding="utf-8") for f in ("insights_pull.py", "optimizer.py", "report.py"))
        check(not re.search(r'method\s*=\s*["\'](POST|DELETE|PUT)', src) and "urlopen(urllib.request.Request(url)" in src, "三支積木沒有任何 POST/DELETE/PUT")
        check("/campaigns" not in src and "/adsets\"" not in src and "status=PAUSED" not in src, "沒有建/改活動的 endpoint")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if N == 0:
        print("零斷言 → exit 2")
        return 2
    print(f"\n{N} 斷言,{len(FAILS)} 失敗")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
