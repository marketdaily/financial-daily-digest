#!/usr/bin/env python3
"""每日日報 → 社群內容自動化。

解析 output/digest_{date}.html,輸出當日 7 平台貼文文案 + 圖卡。
用法:
    python digest_to_social.py            # 處理最新一份日報
    python digest_to_social.py 2026-05-21 # 指定日期
產出:marketing/social_out/{date}/  (captions.md + tldr_card.png + news_card.png)
"""
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from social_cards import make_card

ROOT = Path(__file__).parent.parent
OUT_DIR = Path(__file__).parent / "social_out"
SITE = "https://marketdaily.ai"

TAGS_ZH = "#美股 #台股 #投資理財 #財經 #股市 #理財 #股票 #財經新聞 #投資"
TAGS_EN = "#stocks #investing #stockmarket #finance #stocknews #investingtips"


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def latest_digest():
    files = [f for f in sorted(glob.glob(str(ROOT / "output" / "digest_2*.html")))
             if "_personal_" not in f]
    return Path(files[-1]) if files else None


def parse_digest(html):
    dm = re.search(r'header-meta">\s*([0-9-]+)', html)
    date = dm.group(1) if dm else "today"

    tldr = []
    tm = re.search(r'class="tldr".*?</ul>', html, re.S)
    if tm:
        tldr = [strip_tags(x) for x in re.findall(r"<li>(.*?)</li>", tm.group(0), re.S)]

    ms = re.search(r'class="market-summary">(.*?)</div>', html, re.S)
    market = strip_tags(ms.group(1)) if ms else ""

    news = []
    for m in re.finditer(
        r'news-headline">(.*?)</div>\s*<div class="news-why">(.*?)</div>', html, re.S
    ):
        why = strip_tags(m.group(2))
        why = re.sub(r"^\s*[\U0001F4A1💡]?\s*為什麼重要[:：﹕]\s*", "", why)
        news.append({"headline": strip_tags(m.group(1)), "why": why})

    vm = re.search(
        r'class="verdict\s+(\w+)".*?verdict-emoji">(.*?)</div>\s*'
        r'<div class="verdict-text">(.*?)</div>', html, re.S,
    )
    verdict = None
    if vm:
        verdict = {"kind": vm.group(1), "emoji": strip_tags(vm.group(2)),
                   "text": strip_tags(vm.group(3))}

    return {"date": date, "tldr": tldr, "market": market, "news": news, "verdict": verdict}


def short_date(date):
    parts = date.split("-")
    return f"{int(parts[1])}/{int(parts[2])}" if len(parts) == 3 else date


def general_points(d):
    """公開貼文用的重點:優先用新聞標題(全市場、無個人化),
    再補上不含個人持股字眼的 TL;DR。日報多為個人化版本,故新聞標題優先。"""
    pts = [n["headline"] for n in d["news"]]
    pts += [t for t in d["tldr"] if "你" not in t]
    seen, out = set(), []
    for p in pts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def build_captions(d):
    md = short_date(d["date"])
    pts = general_points(d)
    p3 = pts[:3]
    bullets = "\n".join(f"• {p}" for p in p3)
    link = f"{SITE}/?utm_source={{platform}}&utm_medium=social"

    ig = (
        f"📈 {md} 財經重點\n\n{bullets}\n\n"
        f"完整解讀 + 你的個人化持股,都在今天的 MarketDaily 日報。\n"
        f"每天早上 7 點準時送 —— 免費訂閱,連結在 bio。\n\n"
        f"僅供參考,非投資建議。\n\n{TAGS_ZH}"
    )
    market_clean = re.split(
        r"[，,。]?\s*(?:但是|但|不過|可惜|然而|而)?\s*你", d["market"]
    )[0].strip(" ，,。、")
    fb = (
        f"📈 {md} 今日財經懶人包\n\n{bullets}\n\n"
        + (f"{market_clean}。\n\n" if market_clean else "")
        + "想每天早上 7 點 30 秒看完美股 + 台股?免費訂閱 MarketDaily 日報 👇\n"
        + f"{link.replace('{platform}', 'facebook')}\n\n僅供參考,非投資建議。"
    )
    threads = (
        f"{md} 盤後 ——\n\n" + "\n".join(p3[:2]) +
        "\n\n完整版每早 7 點,連結在下面 👇"
    )
    tiktok = (
        f"{md} 30 秒看完市場 📈\n"
        + " / ".join(h["headline"] for h in d["news"][:2])
        + f"\n完整日報每早 7 點 → 連結在 bio\n{TAGS_ZH}"
    )
    line = (
        f"【MarketDaily {md} 財經日報】\n"
        + (p3[0] if p3 else d["market"][:60])
        + f"\n\n看今天完整日報 👉 {link.replace('{platform}', 'line')}"
    )
    x = (
        f"📈 {md} 美股 + 台股重點\n\n"
        + "\n".join(p3[:2])
        + f"\n\n完整解讀每早 7 點 → {link.replace('{platform}', 'x')}\n"
        + "#美股 #台股 #投資理財"
    )
    youtube = (
        f"標題:{md} 30 秒看完美股 + 台股｜MarketDaily 財經日報\n\n"
        f"說明:\n{md} 今日市場重點,30 秒講完 📈\n\n"
        + "\n".join(f"• {p}" for p in p3)
        + "\n\n完整個人化日報每早 7 點免費送 👉 "
        + f"{link.replace('{platform}', 'youtube')}\n\n"
        + "僅供參考,非投資建議。\n\n"
        + f"#Shorts {TAGS_ZH}"
    )

    out = f"# MarketDaily 社群文案 — {d['date']}\n\n"
    out += "> 由 digest_to_social.py 從當日日報自動生成。發文前快速校稿即可。\n"
    out += "> bio 連結記得帶 UTM(各平台已標好)。\n\n"
    for name, body in [("Instagram", ig), ("Facebook", fb), ("Threads", threads),
                       ("X / Twitter", x), ("TikTok（影片說明）", tiktok),
                       ("YouTube Shorts（標題＋說明）", youtube), ("LINE 推播", line)]:
        out += f"## {name}\n\n```\n{body}\n```\n\n"
    out += f"## 英文版 hashtags（做純英文觸及時換上）\n\n```\n{TAGS_EN}\n```\n"
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    digest = (ROOT / "output" / f"digest_{arg}.html") if arg else latest_digest()
    if not digest or not digest.exists():
        sys.exit(f"找不到日報檔案:{digest}")

    d = parse_digest(digest.read_text(encoding="utf-8"))
    day_dir = OUT_DIR / d["date"]
    day_dir.mkdir(parents=True, exist_ok=True)

    (day_dir / "captions.md").write_text(build_captions(d), encoding="utf-8")

    pts = general_points(d)
    make_card({
        "tag": f"{short_date(d['date'])} 市場重點",
        "headline": "30 秒\n看完今天市場",
        "body": "\n".join(f"• {p}" for p in pts[:3]),
        "cta": "完整日報每早 7 點 → bio",
    }, day_dir / "tldr_card.png")

    if d["news"]:
        n0 = d["news"][0]
        why = n0["why"]
        make_card({
            "tag": "今日焦點",
            "accent": "#38bdf8",
            "headline": n0["headline"],
            "body": why[:96] + "…" if len(why) > 96 else why,
            "cta": "完整解讀在今天的日報 → bio",
        }, day_dir / "news_card.png")

    print(f"✓ {d['date']} 社群內容已產出 → {day_dir}")
    print("  · captions.md（7 平台文案）")
    print("  · tldr_card.png · news_card.png")


if __name__ == "__main__":
    main()
