#!/usr/bin/env python3
"""接戰績武器化(P2.5 打法3)資料層進實際發文佇列 —— win_cards_queue.json → social_posts.json。

規則(feedback_social_post_verify / feedback_no_fake_numbers / feedback_line_retired 死線):
- 只讀 win_cards_queue.json(已由 win_card_data.py 驗證過真實 5 日漲跌%),不重算數字。
- id 用 `win_{date}_{ticker}_{verdict_class}` 當去重鍵,已存在 social_posts.json 的一律跳過
  (可重複執行,只會新增未промote過的候選,不會重複 append)。
- 同一天(date)只挑一則(取|pct|最大者)當代表,避免同日多檔連續洗版;按日期新到舊排序,
  最新的證據排在佇列前段(daily_run.py 仍照 posts 陣列順序逐篇發,不影響既有排班)。
- platforms 固定 instagram/facebook/threads(不含 line——LINE 已全面退役;不含 x——X 現行手動,見 auto_post.py)。
- 圖卡沒渲染過就用既有 make_win_cards.spec_for()+social_cards.make_card() 現場產生,
  沒有 sips 時退回 auto_post 已驗證過的 Playwright headless Chrome PNG→JPEG fallback,
  直接輸出到 docs/social/(供 daily_run.py 發文時組出的網址可直接命中,不需另外 stage)。
- 本腳本只寫 assets/posts/win/*.png、docs/social/*.jpg、social_posts.json——不觸發任何發文,
  不碰 main.py/analyzer.py/data_fetcher.py。實際發文仍由既有 cron(social_post_runner.sh)按既有
  每日鎖 + posted_ids() 去重逐篇跑。

跑法:python3 promote_win_cards.py [限筆數,預設 8]
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from auto_post import POSTS_FILE, _png_to_jpg_playwright  # noqa: E402
from make_win_cards import load_candidates, slugify, spec_for  # noqa: E402
from social_cards import make_card  # noqa: E402
import json
import shutil
import subprocess

PNG_DIR = HERE / "assets" / "posts" / "win"
JPG_DIR = HERE.parent / "docs" / "social"

HOOK = {
    "buy": "有些建議,事後回頭看也站得住腳。",
    "hold": "續抱的判斷,也留紀錄可查。",
    "sell": "有時候「避開」比「追上」更重要。",
    "wait": "有時候「不追」比「追上」更重要。",
}
MARKET_TAG = {"us": "#美股", "tw": "#台股"}


def caption_for(c: dict) -> str:
    pct = c["pct_move_5d"]
    direction = "上漲" if pct > 0 else ("下跌" if pct < 0 else "持平")
    hook = HOOK.get(c["verdict_class"], HOOK["wait"])
    mtag = MARKET_TAG.get(c.get("market"), "#美股")
    return (
        f"{hook}\n\n"
        f"{c['date']} {c['name']}({c['ticker']}):MarketDaily 當時建議「{c['verdict_label']}」,"
        f"5 個交易日後{direction} {abs(pct):.2f}%。\n\n"
        f"完整戰績對帳(看對看錯都列)→ "
        f"https://marketdaily.ai/track-record?utm_source=social&utm_medium=organic&utm_campaign={slugify(c)}\n\n"
        f"#戰績公開 {mtag} #財經日報 #投資理財 #透明"
    )


def png_to_jpg(png_path: Path, jpg_path: Path):
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png_path), "--out", str(jpg_path)], capture_output=True, check=True)
    else:
        _png_to_jpg_playwright(png_path, jpg_path)


MAX_PER_TICKER = 2  # 防同一檔(如 MSFT 連 4 篇「觀望」)洗版,批次內同檔上限


def pick_candidates(all_candidates: list, already: set, limit: int) -> list:
    """同日只留 |pct| 最大者(去同日洗版),按日期新到舊排序;批次內同檔至多 MAX_PER_TICKER 篇
    (優先取不同檔的證據,只有在額度不夠時才放寬同檔上限),跳過已 promote 過的 id。"""
    best_per_date = {}
    for c in all_candidates:
        cid = slugify(c)
        if cid in already:
            continue
        d = c["date"]
        if d not in best_per_date or abs(c["pct_move_5d"]) > abs(best_per_date[d]["pct_move_5d"]):
            best_per_date[d] = c
    ordered = sorted(best_per_date.values(), key=lambda c: c["date"], reverse=True)

    picked, ticker_count = [], {}
    for c in ordered:
        if len(picked) >= limit:
            break
        if ticker_count.get(c["ticker"], 0) >= MAX_PER_TICKER:
            continue
        picked.append(c)
        ticker_count[c["ticker"]] = ticker_count.get(c["ticker"], 0) + 1
    if len(picked) < limit:  # 額度不夠才放寬同檔上限,補滿 limit
        picked_ids = {slugify(c) for c in picked}
        for c in ordered:
            if len(picked) >= limit:
                break
            if slugify(c) in picked_ids:
                continue
            picked.append(c)
    return picked


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    candidates = load_candidates()
    posts_payload = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    posts = posts_payload["posts"]
    already = {p["id"] for p in posts}
    picked = pick_candidates(candidates, already, limit)
    if not picked:
        print("沒有新候選可 promote(可能都已在佇列中,或 win_cards_queue.json 是空的)。")
        return 0
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    JPG_DIR.mkdir(parents=True, exist_ok=True)
    next_day = max((p.get("day") or 0) for p in posts) + 1
    added = []
    for c in picked:
        slug = slugify(c)
        png_path = PNG_DIR / f"{slugify(c)}.png"
        jpg_path = JPG_DIR / f"{slugify(c)}.jpg"
        if not png_path.exists():
            make_card(spec_for(c), png_path)
        png_to_jpg(png_path, jpg_path)
        posts.append({
            "id": slug,
            "day": next_day,
            "image": f"{slugify(c)}.png",
            "platforms": ["instagram", "facebook", "threads"],
            "caption": caption_for(c),
        })
        added.append(slug)
        next_day += 1
    POSTS_FILE.write_text(json.dumps(posts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"新增 {len(added)} 篇戰績卡進佇列(day {next_day - len(added)}–{next_day - 1}):")
    for slug in added:
        print(f"  · {slug}")
    print(f"\n圖檔已輸出 {PNG_DIR} + {JPG_DIR}(尚未 deploy docs/,需另跑 wrangler pages deploy 才會公開可見)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
