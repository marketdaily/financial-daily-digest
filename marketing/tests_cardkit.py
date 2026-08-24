#!/usr/bin/env python3
"""cardkit 自測 —— 跑法: python3 tests_cardkit.py

⚠️ 第一條測試是這裡最重要的一條：**斷言 make_card 真的走了 cardkit，而不是靜靜退回舊模板**。
   2026-08-24 接線時 social_cards 把所有選配欄位顯式填成 None，`spec.get(k, default)` 因此
   回 None(key 存在) → PIL 收到 None 當文字 → 例外 → 我寫的 fallback 安靜接住 → 圖照樣產出、
   程式回報成功，但**畫面還是舊模板**。老闆會看到「你說改好了，但看起來一模一樣」。
   有退路的地方就一定要有一條「退路沒被用到」的測試，否則退路本身就是說謊的機制。
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import social_cards  # noqa: E402
from cardkit import styles  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def test_no_silent_fallback():
    """每一種風格都要能吃『欄位齊全但多半是 None』的 spec，不准退回 legacy。"""
    calls = {"legacy": 0}
    orig = social_cards.make_card_legacy

    def spy(*a, **k):
        calls["legacy"] += 1
        return orig(*a, **k)

    social_cards.make_card_legacy = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            for i in range(len(styles.MD_STYLES) * 3):
                social_cards.make_card(
                    {"tag": "測試", "headline": f"第 {i} 張卡的主標題", "body": "一段內文",
                     "cta": "marketdaily.ai →", "accent": None},
                    Path(td) / f"t_{i}.png")
    finally:
        social_cards.make_card_legacy = orig
    check("make_card 全程走 cardkit，零次退回 legacy", calls["legacy"] == 0,
          f"退回了 {calls['legacy']} 次")


def test_all_styles_render():
    """每個品牌 × 每個風格 × 三種殘缺 spec 都要畫得出來。"""
    specs = [
        {"headline": "只有標題"},
        {"kicker": "標籤", "headline": "標題與標籤", "body": None, "items": None,
         "stat": None, "left": None, "right": None, "left_label": None, "right_label": None},
        {"kicker": "節氣", "headline": "多行\n標題", "body": "內文", "items": ["一", "二", "三"],
         "stat": "30秒", "stat_label": "說明", "left": "左", "right": "右"},
    ]
    bad = []
    for brand in styles.BRANDS:
        for st in styles.BRANDS[brand].styles:
            for j, sp in enumerate(specs):
                try:
                    img, _ = styles.render(dict(sp, id=f"t{j}"), brand, style=st["id"])
                    if img.size != (1080, 1350):
                        bad.append(f"{brand}/{st['id']}/{j}:size")
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{brand}/{st['id']}/{j}:{type(e).__name__}")
    check(f"全部風格 × 殘缺 spec 皆可算圖({len(styles.MD_STYLES)+len(styles.MS_STYLES)} 風格)",
          not bad, "; ".join(bad[:5]))


def test_assignment_stable_and_spread():
    """同一鍵永遠同一風格(可重現) + 相鄰不撞版(視覺才有變化)。"""
    import json
    with tempfile.TemporaryDirectory() as td:
        old = styles.STATE_DIR
        styles.STATE_DIR = Path(td)
        try:
            keys = [f"k{i}" for i in range(30)]
            first = [styles.assign("marketdaily", k)["id"] for k in keys]
            again = [styles.assign("marketdaily", k)["id"] for k in keys]
            check("同一張卡重跑得到同一個風格", first == again)
            adj = sum(1 for a, b in zip(first, first[1:]) if a == b)
            check("相鄰貼文零撞版", adj == 0, f"{adj} 次相鄰重複")
            check("30 則至少用到 8 種風格", len(set(first)) >= 8, f"只用了 {len(set(first))} 種")
            check("指派表寫得出來", (Path(td) / "marketdaily_recent.json").exists())
        finally:
            styles.STATE_DIR = old


def test_dark_only():
    """封面不可白底(marketing/CLAUDE.md 鐵則) —— 每個色票背景亮度都要夠暗。"""
    bright = [p.key for p in styles.MD_PALETTES + styles.MS_PALETTES if p.luminance() > 0.22]
    check("所有色票皆深底", not bright, f"過亮: {bright}")


def test_rendered_image_is_dark():
    """實際算出來的圖也要暗 —— 色票暗不代表疊完背景還暗。"""
    hot = []
    for brand in styles.BRANDS:
        for st in styles.BRANDS[brand].styles:
            img, _ = styles.render({"id": "lum", "headline": "亮度測試"}, brand, style=st["id"])
            small = img.resize((32, 40)).convert("L")
            avg = sum(small.getdata()) / (32 * 40)
            if avg > 90:
                hot.append(f"{brand}/{st['id']}={avg:.0f}")
    check("算出來的圖平均亮度 ≤ 90/255", not hot, "; ".join(hot))


if __name__ == "__main__":
    print("cardkit 自測")
    for fn in (test_no_silent_fallback, test_all_styles_render,
               test_assignment_stable_and_spread, test_dark_only, test_rendered_image_is_dark):
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n{'❌ 失敗 ' + str(len(FAILS)) + ' 項: ' + ', '.join(FAILS) if FAILS else '✅ 全過'}")
    sys.exit(1 if FAILS else 0)
