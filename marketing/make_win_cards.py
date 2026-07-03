"""渲染戰績武器化(P2.5 打法3)圖卡 —— win_cards_queue.json → PNG。

只做渲染,不寫 social_posts.json、不觸發任何發文(feedback_social_post_verify:
發文前仍須人工逐字核對 caption_zh,本腳本只產出可審核的圖卡資產)。

配色沿用 P1.5 修4 已定案的品牌語意:避坑(sell/wait,真 edge)= EMERALD 綠、
看多延續(buy/hold)= GOLD 琥珀中性,不用 red 過度暗示看多是「壞」。

跑法:python make_win_cards.py [限筆數,預設全部]
"""
import re
import sys
from pathlib import Path

from social_cards import make_card

ROOT = Path(__file__).parent.parent
QUEUE_FILE = Path(__file__).parent / "win_cards_queue.json"
OUT = Path(__file__).parent / "assets" / "posts" / "win"

EMERALD = "#4AF626"
GOLD = "#FFB000"

AVOIDANCE_CLASSES = {"sell", "wait"}

import json


def load_candidates():
    payload = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    return payload.get("candidates", [])


def slugify(candidate: dict) -> str:
    ticker = re.sub(r"[^A-Za-z0-9]", "", candidate["ticker"])
    return f"win_{candidate['date']}_{ticker}_{candidate['verdict_class']}"


def spec_for(candidate: dict) -> dict:
    pct = candidate["pct_move_5d"]
    direction = "上漲" if pct > 0 else ("下跌" if pct < 0 else "持平")
    accent = EMERALD if candidate["verdict_class"] in AVOIDANCE_CLASSES else GOLD
    return {
        "tag": f"戰績對帳 · {candidate['verdict_label']}",
        "headline": f"{candidate['name']}({candidate['ticker']})\n5個交易日後{direction} {pct:+.2f}%",
        "body": f"{candidate['date']} 建議{candidate['verdict_label']},判斷正確。",
        "cta": "完整對帳 marketdaily.ai/track-record →",
        "accent": accent,
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    candidates = load_candidates()
    if limit:
        candidates = candidates[:limit]
    OUT.mkdir(parents=True, exist_ok=True)
    made = 0
    for c in candidates:
        out = OUT / f"{slugify(c)}.png"
        make_card(spec_for(c), out)
        made += 1
        print(f"✅ {out.relative_to(Path(__file__).parent)}")
    print(f"\n共渲染 {made} 張 → {OUT}(僅本機資產,未寫入 social_posts.json,發文前仍需人工審核)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
