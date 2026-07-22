#!/usr/bin/env python3
"""ai_slop_lint 生產管線整合迴歸測試(2026-07-21)。

凍結語意:
- seo_articles.slop_gated:sloppy 重生一次仍髒即丟棄(None)、clean 一次過、
  lint 積木缺席 fail-open 放行(lint 是品質閘不是產線依賴)。
- promote_ad_creatives._slop_verdict + eligible:sloppy caption 拒收入佇列、clean 放行。

用法: python3 scripts/test_slop_gate_integration.py   (exit 0=全過)
"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)


SLOP = ("值得注意的是,在當今快速發展的數位時代,我們深入探討這個至關重要的話題。"
        "總而言之,隨著科技的不斷進步,打造全方位的解決方案至關重要。"
        "首先,我們需要全面了解;其次,深入分析;最後,總結來說,這無疑是一個里程碑。"
        "In today's fast-paced world, it is worth noting that we delve into this topic. "
        "Moreover, it serves as a testament to the ever-evolving landscape. "
        "In conclusion, unlocking the full potential is a game-changer that underscores everything.") * 3
CLEAN = ("台積電第二季營收季增 12%,毛利率 53.2%。法說會提到先進製程 N2 於 2026 下半年量產,"
         "資本支出維持 380 億美元。") * 8

import seo_articles as sa  # noqa: E402

calls = {"n": 0}


def gen_sloppy():
    calls["n"] += 1
    return {"body_html": SLOP}


def gen_clean():
    calls["n"] += 1
    return {"body_html": CLEAN}


calls["n"] = 0
check("blog: sloppy 重生一次仍髒 → 丟棄", sa.slop_gated(gen_sloppy, "t") is None and calls["n"] == 2)
calls["n"] = 0
check("blog: clean 一次過", sa.slop_gated(gen_clean, "t") is not None and calls["n"] == 1)
orig, sa.AI_SLOP_LINT, sa._slop_mod = sa.AI_SLOP_LINT, Path("/nonexistent/logic.py"), None
calls["n"] = 0
check("blog: lint 缺席 fail-open 放行", sa.slop_gated(gen_sloppy, "t") is not None and calls["n"] == 1)
sa.AI_SLOP_LINT, sa._slop_mod = orig, None

os.chdir(ROOT / "marketing")
spec = importlib.util.spec_from_file_location("pac", ROOT / "marketing" / "promote_ad_creatives.py")
pac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pac)

drafts = [
    {"id": "t_slop", "caption_zh": SLOP, "status": "approved", "platform": "instagram", "score": 1},
    {"id": "t_clean",
     "caption_zh": "每天 07:00,你的持股重點直接進信箱。台積電、輝達、0050——你設定,AI 整理。限時免費。",
     "status": "approved", "platform": "instagram", "score": 1},
]
by_id = {d["id"]: r for d, r in pac.eligible(drafts, set())}
check("caption: sloppy 拒收入佇列", bool(by_id.get("t_slop")) and "AI-slop" in by_id["t_slop"])
check("caption: clean 放行", by_id.get("t_clean") is None)

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{'FAIL: ' + ', '.join(failed) if failed else 'ALL PASS'} ({len(RESULTS) - len(failed)}/{len(RESULTS)})")
sys.exit(1 if failed else 0)
