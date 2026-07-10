#!/usr/bin/env python3
"""公版日報 HTML → brief.json(短影音腳本資料層)。

只抽事實:30秒重點 bullets、個股當日漲跌(名稱/代碼/±%)、日期、多空氛圍。
不搬買賣價位/建議文字上社群(2026-06-02 明牌出包教訓,見 project_digest_autopost_disabled)。
每個抽出的數字都必須逐字存在於源 HTML,否則 abort。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "video_brief" / "out"


def find_digest(date_str=None, edition=None):
    files = sorted((REPO / "docs" / "output").glob("digest_*.html"))
    if not files:
        sys.exit("找不到任何公版日報")
    if date_str:
        suffix = f"digest_{date_str}{'_us' if edition == 'us' else ''}.html"
        hits = [f for f in files if f.name == suffix]
        if not hits:
            sys.exit(f"找不到 {suffix}")
        return hits[0]
    return files[-1]


def _strip(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def extract(path):
    h = path.read_text(encoding="utf-8")

    m = re.search(r"digest_(\d{4}-\d{2}-\d{2})(_us)?\.html", path.name)
    date_str, edition = m.group(1), ("us" if m.group(2) else "tw")

    chip = re.search(r'tldr-chip (\w+)', h)
    mood = chip.group(1) if chip else "neutral"

    tldr = re.search(r'<div class="tldr">.*?<ul>(.*?)</ul>', h, re.S)
    if not tldr:
        sys.exit("抽不到 30 秒重點區塊")
    bullets = [_strip(li) for li in re.findall(r"<li>(.*?)</li>", tldr.group(1), re.S)]
    bullets = [b for b in bullets if b]
    if not bullets:
        sys.exit("30 秒重點是空的")

    movers = []
    for card in re.findall(r'<div class="signal-card[^"]*">(.*?)signal-body', h, re.S):
        name_m = re.search(r"signal-ticker.*?>([^<]+)<", card, re.S)
        tick_m = re.search(r"monospace[^>]*>([A-Z0-9.]{1,10})<", card)
        move_m = re.search(r'signal-day-move (up|down)">([▲▼])\s*([+-][\d.]+)%', card)
        verdict_m = re.search(r'signal-verdict-chip [^"]*">[^\w]*([^<]+)<', card)
        if not (name_m and move_m):
            continue
        movers.append({
            "name": name_m.group(1).strip(),
            "ticker": tick_m.group(1) if tick_m else "",
            "dir": move_m.group(1),
            "move": move_m.group(3),
            "verdict": verdict_m.group(1).strip() if verdict_m else "",
        })

    sectors = [{"name": n.strip(), "move": mv.strip(), "comment": c.strip()}
               for n, mv, c in re.findall(
                   r'class="sector-name">([^<]+)<.*?class="sector-move[^"]*">([^<]+)<.*?class="sector-comment">([^<]+)<',
                   h, re.S)]
    news = [{"headline": hd.strip(), "why": re.sub(r"^💡\s*為什麼重要[：:]\s*", "", w).strip()}
            for hd, w in re.findall(
                r'class="news-headline">([^<]+)<.*?class="news-why">([^<]+)<', h, re.S)]

    text = _strip(h)
    tw_market_closed = bool(re.search(
        r"台股今(?:天|日)[^。]{0,12}休市|今(?:天|日)[^。]{0,6}台股[^。]{0,12}休市", text))

    brief = {
        "date": date_str,
        "edition": edition,
        "mood": mood,
        "bullets": bullets,
        "movers": movers,
        "sectors": sectors,
        "news": news,
        "tw_market_closed": tw_market_closed,
        "source_file": path.name,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
    }

    for mv in movers:
        if mv["move"] not in h:
            sys.exit(f"數字 {mv['move']} 不存在於源 HTML,abort")
    for s in sectors:
        for num in re.findall(r"[+-]?\d+(?:\.\d+)?", s["move"]):
            if num not in h:
                sys.exit(f"sector 數字 {num} 不存在於源 HTML,abort")
    for b in bullets:
        for num in re.findall(r"[+-]?\d+(?:\.\d+)?%", b):
            if num.lstrip("+-") not in h:
                sys.exit(f"bullet 數字 {num} 不存在於源 HTML,abort")
    return brief


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    edition = sys.argv[2] if len(sys.argv) > 2 else None
    path = find_digest(date_str, edition)
    brief = extract(path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"brief_{brief['date']}_{brief['edition']}.json"
    out.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {out.relative_to(REPO)}  bullets={len(brief['bullets'])} movers={len(brief['movers'])} mood={brief['mood']}")


if __name__ == "__main__":
    main()
