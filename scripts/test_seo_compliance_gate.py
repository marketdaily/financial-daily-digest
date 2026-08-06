#!/usr/bin/env python3
"""seo_articles 寫檔前合規閘迴歸測試(2026-08-06,08-06 驗證者分離 3 findings 修復後補測)。

背景:legal/compliance_watch.py 每晚 22:10 才會掃到線上頁面(含 blog),中間最長 24h
的暴露窗口全靠 LLM prompt 指示(非確定性)。此閘複用 legal/rules.py **同一份**
marketdaily+marketdaily_marketing pack 的規則(forbidden+proximity+context_required,
只排除 required),在 write_article() 之前擋下違規,把暴露窗口從「隔夜巡檢才抓到」
收斂成「寫檔前擋下」。

凍結語意:
- slop_gated:違規文字(如捏造勝率數字)重生一次仍違規 → 丟棄(None)。
- slop_gated:合規乾淨文字 → 一次過。
- _compliance_report 涵蓋 proximity 類規則(F1 CRITICAL 修復):md_paywall_stock
  (投信投顧法§4/§107 刑責)是 proximity 類,原版只套 forbidden 類會漏接風險最高的規則。
- 合規規則庫在**規則評估過程中**(非只有 import 那行)壞掉 → fail-open 放行,不讓生成
  管線因規則庫壞掉而停擺、也不吃掉重試機會(F2 修復)。
- 合規閘丟棄計入 `_GEN_STATS['compliance_discards']`,供 main() 收工時彙總可見度/告警
  (F3 修復,非只印 stdout)。

用法: python3 scripts/test_seo_compliance_gate.py   (exit 0=全過)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


CLEAN = ("台積電第二季營收季增 12%,毛利率 53.2%。法說會提到先進製程 N2 於 2026 下半年量產,"
         "資本支出維持 380 億美元,產業展望審慎樂觀。") * 3
VIOLATION = CLEAN + "MarketDaily 訊號勝率高達 88%,已幫助超過 500 位訂閱者穩定獲利。"
# 2026-08-06 驗證者 F1 CRITICAL 原始重現案例:訂閱與目標價/買賣點同句共現(proximity 類,
# md_paywall_stock,投信投顧法§4/§107 刑責)——原版只套 forbidden 類完全漏接這條。
PAYWALL_VIOLATION = (CLEAN + "訂閱後就能看到我們對台積電的目標價與買賣點,幫助你掌握進出場價。")

import seo_articles as sa  # noqa: E402

# ── 單元測試:_compliance_report 本身 ──────────────────────────────
report_clean = sa._compliance_report(CLEAN)
check("_compliance_report: 乾淨文字 findings 為空 list(規則庫確實有載入,非 fail-open None)",
      report_clean == [])

report_bad = sa._compliance_report(VIOLATION)
check("_compliance_report: 捏造勝率數字被抓到(forbidden 類)", bool(report_bad)
      and any(f["id"] == "md_fabricated_stats" for f in report_bad))

report_paywall = sa._compliance_report(PAYWALL_VIOLATION)
check("_compliance_report: 付費牆同句共現被抓到(proximity 類,F1 CRITICAL 修復)",
      bool(report_paywall) and any(f["id"] == "md_paywall_stock" for f in report_paywall))

# ── 整合測試:slop_gated 迴圈接線 + _GEN_STATS 計數(F3)──────────────
calls = {"n": 0}


def gen_violation():
    calls["n"] += 1
    return {"body_html": VIOLATION}


def gen_clean():
    calls["n"] += 1
    return {"body_html": CLEAN}


sa._GEN_STATS["compliance_discards"] = 0
calls["n"] = 0
check("slop_gated: 違規文字重生一次仍違規 → 丟棄",
      sa.slop_gated(gen_violation, "t") is None and calls["n"] == 2)
check("_GEN_STATS: 合規丟棄計數 +1(F3 修復)", sa._GEN_STATS["compliance_discards"] == 1)

calls["n"] = 0
check("slop_gated: 合規乾淨文字 → 一次過", sa.slop_gated(gen_clean, "t") is not None and calls["n"] == 1)

# ── fail-open(F2):規則庫評估過程中壞掉(非只有 import 失敗)也要放行 ──────────────
from legal import rules as R  # noqa: E402

_orig_rules = list(R.RULES)
_bad_rules = [dict(r, patterns=["(unbalanced("]) if r.get("kind") == "forbidden" else r
              for r in R.RULES]
R.RULES[:] = _bad_rules
try:
    report_crash = sa._compliance_report(VIOLATION)
    check("_compliance_report: 規則評估中途壞掉(壞 regex)→ fail-open 回 None(F2 修復)",
          report_crash is None)
    calls["n"] = 0
    check("slop_gated: 規則庫壞掉時不因例外整篇消失,fail-open 一次過",
          sa.slop_gated(gen_violation, "t") is not None and calls["n"] == 1)
finally:
    R.RULES[:] = _orig_rules

# ── fail-open:規則庫整個不可 import ──────────────────────────────
import builtins  # noqa: E402
_orig_import = builtins.__import__


def _blocked_import(name, *a, **kw):
    if name == "legal" or name.startswith("legal."):
        raise ImportError("simulated: legal package unavailable")
    return _orig_import(name, *a, **kw)


builtins.__import__ = _blocked_import
try:
    report_unavailable = sa._compliance_report(VIOLATION)
    check("_compliance_report: 規則庫不可用 → fail-open 回 None", report_unavailable is None)
    calls["n"] = 0
    check("slop_gated: 規則庫不可用時違規文字仍放行(fail-open,一次過)",
          sa.slop_gated(gen_violation, "t") is not None and calls["n"] == 1)
finally:
    builtins.__import__ = _orig_import

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
