#!/usr/bin/env python3
"""每日日報 → 社群貼文 全自動發布(永動引擎)。

抓當天線上日報 → 生成文案 + 圖卡 → 發到 IG / FB / Threads。(LINE 已全面退役 2026-07-06)
內容守門:日報解析重點不足則跳過,不發殘缺貼文。

用法:
    python auto_digest_post.py generate   # 抓日報、產文案+圖卡
    python auto_digest_post.py publish    # 把當天已產出的貼文發到各平台

排程在 generate 與 publish 之間 git push 圖卡,publish 用 raw URL 供平台抓圖。
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_post import (caption_for, load_env, post_facebook, post_instagram,
                       post_threads, post_x)
from digest_to_social import general_points, parse_digest
from social_cards import make_card

HERE = Path(__file__).parent
REPO = HERE.parent
OUT_DIR = HERE / "social_out"
SITE = "https://marketdaily.ai"
RAW_BASE = "https://raw.githubusercontent.com/marketdaily/financial-daily-digest/main"
TAGS = "#美股 #台股 #投資理財 #財經 #股市 #理財 #財經新聞"
MIN_POINTS = 2

PLATFORMS = {"instagram": post_instagram, "facebook": post_facebook,
             "threads": post_threads, "x": post_x}


def taiwan_date():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def short_date(d):
    p = d.split("-")
    return f"{int(p[1])}/{int(p[2])}" if len(p) == 3 else d


def fetch_digest(date):
    url = f"{SITE}/output/digest_{date}.html"
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "marketdaily-social"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore") if r.status == 200 else None
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 307, 308) else None
            if not loc:
                return None
            url = urllib.parse.urljoin(url, loc)
        except Exception:
            return None
    return None


def build_caption(points, date):
    bullets = "\n".join(f"• {p}" for p in points[:3])
    return (
        f"📈 {short_date(date)} 財經重點\n\n{bullets}\n\n"
        f"完整解讀 + 你的個人化持股,都在今天的 MarketDaily 日報。\n"
        f"每天早上 7 點免費送 👉 {SITE}\n\n"
        f"僅供參考,非投資建議。\n\n{TAGS}"
    )


def build_caption_x(points, date):
    """X 280 字限制版:取 2 則重點 + 連結。"""
    return (
        f"📈 {short_date(date)} 美股 + 台股重點\n\n"
        + "\n".join(points[:2])
        + f"\n\n完整解讀每早 7 點 → {SITE}\n#美股 #台股 #投資理財"
    )


def cmd_generate():
    date = taiwan_date()
    html = fetch_digest(date)
    if not html:
        print(f"⏭️  找不到 {date} 線上日報,跳過(不發文)")
        return
    d = parse_digest(html)
    points = general_points(d)
    if len(points) < MIN_POINTS:
        print(f"⏭️  {date} 日報解析重點不足({len(points)} 則),跳過")
        return
    day_dir = OUT_DIR / date
    day_dir.mkdir(parents=True, exist_ok=True)
    caption = build_caption(points, date)
    (day_dir / "digest_caption.txt").write_text(caption, encoding="utf-8")
    (day_dir / "digest_caption_x.txt").write_text(
        build_caption_x(points, date), encoding="utf-8")

    png = day_dir / "digest_card.png"
    make_card({
        "tag": f"{short_date(date)} 市場重點",
        "headline": "30 秒\n看完今天市場",
        "body": "\n".join(f"• {p}" for p in points[:3]),
        "cta": "完整日報每早 7 點 → bio",
    }, png)

    from PIL import Image
    card_dir = REPO / "docs" / "social"
    card_dir.mkdir(parents=True, exist_ok=True)
    jpg = card_dir / f"digest_card_{date}.jpg"
    Image.open(png).convert("RGB").save(jpg, "JPEG", quality=90)
    png.unlink()
    print(f"✓ {date} 貼文已產出 · 文案 {len(caption)} 字 · 圖卡 {jpg.name}")


def cmd_publish():
    date = taiwan_date()
    cap_f = OUT_DIR / date / "digest_caption.txt"
    if not cap_f.exists():
        print(f"⏭️  {date} 無待發貼文(generate 可能已跳過)")
        return
    caption = cap_f.read_text(encoding="utf-8")
    cap_x_f = OUT_DIR / date / "digest_caption_x.txt"
    caption_x = cap_x_f.read_text(encoding="utf-8") if cap_x_f.exists() else caption
    image_url = f"{RAW_BASE}/docs/social/digest_card_{date}.jpg"
    env = load_env()
    line_url = env.get("LINE_ADD_URL", "")
    targets = {k: v for k, v in PLATFORMS.items()
               if k != "x" or env.get("X_API_KEY")}
    print(f"發布 {date} 日報社群貼文 → {image_url}\n")
    results = {}
    for plat, fn in targets.items():
        cap = caption_x if plat == "x" else caption_for(caption, plat, line_url)
        try:
            ok, detail = fn(env, image_url, cap)
        except KeyError as e:
            ok, detail = False, f"缺少 {e}"
        # X 已改付費、未充值 → 任何失敗都軟略過,不算數;補 credits 後自動恢復發文。
        soft = not ok and plat == "x"
        results[plat] = {"ok": ok, "skipped": soft, "detail": str(detail)}
        mark = "✅" if ok else ("⏭️" if soft else "❌")
        print(f"  {mark} {plat}: {'(X 改手動,略過)' if soft else ''}{detail}")
    log = OUT_DIR / "digest_post_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(), "date": date,
                            "results": results}, ensure_ascii=False) + "\n")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "generate":
        cmd_generate()
    elif cmd == "publish":
        cmd_publish()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
