#!/usr/bin/env python3
"""接日報自動裂變(P2.5 打法6)資料層進實際發文佇列 —— tldr_queue.json → social_posts.json。

規則(feedback_social_post_verify / feedback_no_fake_numbers / feedback_line_retired 死線):
- 只讀 tldr_queue.json(已由 tldr_extract.py 驗證過,只含公版存檔 100% 結構化數字區塊),
  不重算、不新增數字,caption 直接沿用 tldr_extract 產出的 caption_zh(唯一動作是視需要
  加平台 hashtag,不改內容本身的數字或語意)。
- id 用 `tldr_{date}_{variant}` 當去重鍵,已存在 social_posts.json 的一律跳過
  (可重複執行,只會新增未 promote 過的候選,不會重複 append)。
- platforms 固定 instagram/facebook/threads(不含 line——LINE 已全面退役;不含 x——X 現行手動)。
- 圖卡沒渲染過就用 make_tldr_cards.spec_for()+social_cards.make_card() 現場產生,
  沒有 sips 時退回既有 Playwright headless Chrome PNG→JPEG fallback,直接輸出到 docs/social/。
- 本腳本只寫 assets/posts/tldr/*.png、docs/social/*.jpg、social_posts.json——不觸發任何發文,
  不碰 main.py/analyzer.py/data_fetcher.py。實際發文仍由既有 cron(social_post_runner.sh)按既有
  每日鎖 + posted_ids() 去重逐篇跑。

跑法:python3 promote_tldr.py [限筆數,預設全部]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from auto_post import POSTS_FILE, _png_to_jpg_playwright  # noqa: E402
from make_tldr_cards import load_candidates, slugify, spec_for  # noqa: E402
from social_cards import make_card  # noqa: E402
import shutil
import subprocess

PNG_DIR = HERE / "assets" / "posts" / "tldr"
JPG_DIR = HERE.parent / "docs" / "social"

MARKET_TAG = {"us": "#美股", "tw": "#台股"}


def caption_for(c: dict) -> str:
    mtag = MARKET_TAG.get(c["variant"], "#財經")
    return f"{c['caption_zh']}\n\n#市場脈搏 {mtag} #財經日報"


def png_to_jpg(png_path: Path, jpg_path: Path):
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png_path), "--out", str(jpg_path)], capture_output=True, check=True)
    else:
        _png_to_jpg_playwright(png_path, jpg_path)


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    candidates = load_candidates()
    posts_payload = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    posts = posts_payload["posts"]
    already = {p["id"] for p in posts}
    picked = [c for c in candidates if slugify(c) not in already]
    picked.sort(key=lambda c: (c["date"], c["variant"]), reverse=True)
    if limit:
        picked = picked[:limit]
    if not picked:
        print("沒有新候選可 promote(可能都已在佇列中,或 tldr_queue.json 是空的)。")
        return 0
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    JPG_DIR.mkdir(parents=True, exist_ok=True)
    next_day = max((p.get("day") or 0) for p in posts) + 1
    added = []
    for c in picked:
        slug = slugify(c)
        png_path = PNG_DIR / f"{slug}.png"
        jpg_path = JPG_DIR / f"{slug}.jpg"
        if not png_path.exists():
            make_card(spec_for(c), png_path)
        png_to_jpg(png_path, jpg_path)
        posts.append({
            "id": slug,
            "day": next_day,
            "image": f"{slug}.png",
            "platforms": ["instagram", "facebook", "threads"],
            "caption": caption_for(c),
        })
        added.append(slug)
        next_day += 1
    POSTS_FILE.write_text(json.dumps(posts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"新增 {len(added)} 篇市場脈搏卡進佇列(day {next_day - len(added)}–{next_day - 1}):")
    for slug in added:
        print(f"  · {slug}")
    print(f"\n圖檔已輸出 {PNG_DIR} + {JPG_DIR}(尚未 deploy docs/,需另跑 wrangler pages deploy 才會公開可見)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
