"""品牌社群卡 (Open Graph image) 渲染器 — 部落格文章專用,純本地 PIL,免網路。

輸出 1200×630 深色品牌卡:MarketDaily logo lockup + 分類/代碼眉標 + 文章標題。
分享 blog 連結時(LINE/Messenger/X/Reddit/PTT)有縮圖,並讓 Article schema 具 image。
被 scripts/seo_articles.py 呼叫(新文章 write_article + 舊文章 backfill_og_cards)。

render_card(out_path, ticker, market_label, title) 是唯一對外介面,失敗丟例外由呼叫端 fallback。
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 630
MARGIN = 90
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

BG_TOP = (16, 16, 34)
BG_BOTTOM = (10, 10, 20)
GRID = (26, 26, 48)
GLOW = (124, 108, 246)          # 品牌紫
PURPLE = (139, 124, 246)
PURPLE_LIGHT = (165, 180, 252)  # #a5b4fc 眉標
WHITE = (255, 255, 255)
MUTED = (148, 163, 184)         # #94a3b8
DIVIDER = (44, 44, 68)

_STOCK_MARKETS = {"台股", "美股"}
_TICKER_RE = re.compile(r"^(?:[0-9]{4}|[a-z]{1,5})$")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=0)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
        or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF
    )


def _tokenize(text: str) -> list[str]:
    """CJK/全形逐字成 token;ASCII 連續字元(數字/英文/半形標點)聚為一 token;空白為分隔 token。"""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif _is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    tokens = _tokenize(text)
    lines: list[str] = []
    cur = ""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        cand = cur + t
        if cur.strip() == "" or draw.textlength(cand, font=font) <= max_w:
            cur = cand
            i += 1
        else:
            lines.append(cur.rstrip())
            cur = ""
            if len(lines) == max_lines:
                break
    if cur.strip() and len(lines) < max_lines:
        lines.append(cur.rstrip())
        i = len(tokens)
    # 溢出→末行加省略號
    if i < len(tokens) and lines:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _fit_title(draw, title: str, max_w: int, max_lines: int):
    """由大到小挑第一個能在 max_lines 內排完的字級。"""
    for size in (66, 58, 50, 44, 38):
        font = _font(size)
        lines = _wrap(draw, title, font, max_w, max_lines + 1)
        if len(lines) <= max_lines:
            return font, _wrap(draw, title, font, max_w, max_lines), size
    font = _font(38)
    return font, _wrap(draw, title, font, max_w, max_lines), 38


def _eyebrow(ticker: str, market_label: str) -> str:
    t = (ticker or "").strip().lower()
    if market_label in _STOCK_MARKETS and _TICKER_RE.match(t):
        return f"{market_label} · {t.upper()}"
    return market_label or "個股分析"


def _background() -> Image.Image:
    # 垂直漸層
    base = Image.new("RGB", (W, H), BG_BOTTOM)
    top = Image.new("RGB", (W, H), BG_TOP)
    mask = Image.new("L", (1, H), 0)
    for y in range(H):
        mask.putpixel((0, y), int(255 * (1 - y / H)))
    base = Image.composite(top, base, mask.resize((W, H)))
    draw = ImageDraw.Draw(base)
    # 淡格線
    for x in range(0, W, 60):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 60):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)
    # 右上柔光
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([820, -260, 1420, 340], fill=GLOW + (60,))
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
    return base


def render_card(out_path, ticker: str, market_label: str, title: str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = _background()
    draw = ImageDraw.Draw(img)

    # logo lockup
    box = 64
    lx, ly = MARGIN, 78
    draw.rounded_rectangle([lx, ly, lx + box, ly + box], radius=16, fill=PURPLE)
    mf = _font(42)
    mb = draw.textbbox((0, 0), "M", font=mf)
    draw.text((lx + (box - (mb[2] - mb[0])) / 2 - mb[0], ly + (box - (mb[3] - mb[1])) / 2 - mb[1]),
              "M", font=mf, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    wf = _font(40)
    draw.text((lx + box + 22, ly + box / 2), "MarketDaily", font=wf, fill=WHITE,
              anchor="lm", stroke_width=1, stroke_fill=WHITE)

    # eyebrow
    ef = _font(30)
    draw.text((MARGIN, 246), _eyebrow(ticker, market_label), font=ef, fill=PURPLE_LIGHT)

    # title
    max_w = W - 2 * MARGIN
    tf, lines, size = _fit_title(draw, title, max_w, 3)
    line_h = int(size * 1.34)
    y = 300
    for ln in lines:
        draw.text((MARGIN, y), ln, font=tf, fill=WHITE, stroke_width=2, stroke_fill=WHITE)
        y += line_h

    # footer
    draw.line([(MARGIN, 548), (W - MARGIN, 548)], fill=DIVIDER, width=1)
    ff = _font(26)
    draw.text((MARGIN, 570), "marketdaily.ai", font=ff, fill=PURPLE_LIGHT)
    url_w = draw.textlength("marketdaily.ai", font=ff)
    draw.text((MARGIN + url_w, 570), "  · 每天早上 7 點,AI 幫你讀完財經新聞", font=ff, fill=MUTED)

    img.save(out_path, "PNG", optimize=True)
    return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/og_card_sample.png")
    ap.add_argument("--ticker", default="2330")
    ap.add_argument("--market", default="台股")
    ap.add_argument("--title", default="台積電 (2330) 競爭優勢與護城河深度解析")
    a = ap.parse_args()
    p = render_card(a.out, a.ticker, a.market, a.title)
    print(f"wrote {p} ({Path(p).stat().st_size} bytes)")
