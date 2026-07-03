"""MarketDaily 社群圖卡產生器 — SVG 模板 → PNG（macOS qlmanage 渲染）。

供 make_launch_cards.py（首批貼文）與 digest_to_social.py（每日日報）共用。
渲染策略：把卡片內容嵌進方形外框再交給 qlmanage（方形渲染才可靠），最後裁切回 w×h。
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

BG = "#0A0A08"
INK = "#F5E6C8"
BODY = "rgba(245,230,200,0.74)"
INDIGO = "#FFB000"
INDIGO_LIGHT = "#FFC74D"
GOLD = "#4AF626"
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'PingFang TC', 'Segoe UI', sans-serif"

W, H = 1080, 1350  # IG 4:5，社群觸及最佳比例


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _char_w(ch, size):
    return size * (1.0 if ord(ch) > 0x2E7F else 0.56)


def _wrap(text, size, max_w):
    lines = []
    for raw in text.split("\n"):
        cur, w = "", 0.0
        for ch in raw:
            cw = _char_w(ch, size)
            if w + cw > max_w and cur:
                lines.append(cur)
                cur, w = ch, cw
            else:
                cur += ch
                w += cw
        lines.append(cur)
    return lines


def _text_w(s, size):
    return sum(_char_w(c, size) for c in s)


def _icon(x, y, size):
    s = size / 48.0
    return (
        f'<g transform="translate({x},{y}) scale({s:.4f})">'
        '<rect width="48" height="48" rx="12" fill="#0A0A08"/>'
        '<rect x="0.75" y="0.75" width="46.5" height="46.5" rx="11.5" fill="none" stroke="#FFB000" stroke-opacity="0.4" stroke-width="1.5"/>'
        '<rect x="9" y="31" width="6" height="9" rx="2" fill="#A66E00"/>'
        '<rect x="19" y="23" width="6" height="17" rx="2" fill="#FFB000"/>'
        '<rect x="29" y="13" width="6" height="27" rx="2" fill="url(#mdg)"/>'
        '<circle cx="42" cy="9" r="3" fill="#4AF626"/></g>'
    )


def _card_inner(spec, w, h):
    """卡片內容（不含 <svg> 外框）。spec: {tag, headline, body?, cta?, accent?}。"""
    pad = 92
    cw = w - 2 * pad
    accent = spec.get("accent", INDIGO)
    tag = spec.get("tag", "")
    headline = spec["headline"]
    body = spec.get("body", "")
    cta = spec.get("cta", "")

    hl_size, hl_lh = 78, 100
    bd_size, bd_lh = 39, 62

    hl_lines = _wrap(headline, hl_size, cw)
    bd_lines = _wrap(body, bd_size, cw) if body else []

    block_h = len(hl_lines) * hl_lh + (50 + len(bd_lines) * bd_lh if bd_lines else 0)
    zone_top, zone_bot = 360, h - 280
    start = zone_top + max(0, (zone_bot - zone_top - block_h) // 2)

    defs = (
        '<defs>'
        '<linearGradient id="mdg" x1="0" y1="1" x2="1" y2="0">'
        '<stop offset="0%" stop-color="#FFB000"/><stop offset="55%" stop-color="#FFC74D"/><stop offset="100%" stop-color="#4AF626"/>'
        '</linearGradient>'
        '<radialGradient id="glow" cx="0.5" cy="0.16" r="0.85">'
        '<stop offset="0%" stop-color="#FFB000" stop-opacity="0.20"/>'
        '<stop offset="62%" stop-color="#FFB000" stop-opacity="0"/>'
        '</radialGradient>'
        '<pattern id="scan" width="6" height="6" patternUnits="userSpaceOnUse">'
        '<rect y="3" width="6" height="3" fill="#000" fill-opacity="0.18"/></pattern>'
        '</defs>'
    )

    p = [defs]
    p.append(f'<rect width="{w}" height="{h}" fill="{BG}"/>')
    p.append(f'<rect width="{w}" height="{h}" fill="url(#glow)"/>')

    grid, step = [], 108
    for gx in range(step, w, step):
        grid.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{h}"/>')
    for gy in range(step, h, step):
        grid.append(f'<line x1="0" y1="{gy}" x2="{w}" y2="{gy}"/>')
    p.append(f'<g stroke="#FFB000" stroke-opacity="0.05" stroke-width="1">{"".join(grid)}</g>')

    # 頂部品牌列
    p.append(_icon(pad, 88, 66))
    p.append(
        f'<text x="{pad + 86}" y="140" font-family="{FONT}" font-size="42" '
        f'font-weight="800" letter-spacing="-1" fill="{INK}">MarketDaily</text>'
    )
    if tag:
        tw = _text_w(tag, 27) + 58
        tx = w - pad - tw
        p.append(
            f'<rect x="{tx:.0f}" y="92" width="{tw:.0f}" height="58" rx="29" '
            f'fill="{accent}" fill-opacity="0.16" stroke="{accent}" stroke-opacity="0.55"/>'
        )
        p.append(
            f'<text x="{tx + tw / 2:.0f}" y="130" text-anchor="middle" '
            f'font-family="{FONT}" font-size="27" font-weight="700" '
            f'fill="{INDIGO_LIGHT}">{_esc(tag)}</text>'
        )

    # 強調短線
    p.append(f'<rect x="{pad}" y="{start - 46}" width="76" height="8" rx="4" fill="url(#mdg)"/>')

    # 主標
    for i, ln in enumerate(hl_lines):
        yb = start + hl_size + i * hl_lh
        p.append(
            f'<text x="{pad}" y="{yb}" font-family="{FONT}" font-size="{hl_size}" '
            f'font-weight="800" letter-spacing="-1.5" fill="{INK}">{_esc(ln)}</text>'
        )

    # 內文
    if bd_lines:
        by = start + hl_size + (len(hl_lines) - 1) * hl_lh + 50
        for i, ln in enumerate(bd_lines):
            yb = by + bd_size + i * bd_lh
            p.append(
                f'<text x="{pad}" y="{yb}" font-family="{FONT}" font-size="{bd_size}" '
                f'font-weight="500" fill="{BODY}">{_esc(ln)}</text>'
            )

    # CTA 膠囊
    if cta:
        ctw = _text_w(cta, 33) + 96
        cx = (w - ctw) / 2
        cy = h - 214
        p.append(f'<rect x="{cx:.0f}" y="{cy}" width="{ctw:.0f}" height="78" rx="39" fill="url(#mdg)"/>')
        p.append(
            f'<text x="{w / 2:.0f}" y="{cy + 50}" text-anchor="middle" font-family="{FONT}" '
            f'font-size="33" font-weight="700" fill="#0A0A08">{_esc(cta)}</text>'
        )

    # CRT 掃描線
    p.append(f'<rect width="{w}" height="{h}" fill="url(#scan)"/>')

    # 頁尾
    p.append(
        f'<text x="{w / 2:.0f}" y="{h - 88}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="27" font-weight="500" fill="rgba(255,255,255,0.4)">'
        f'@marketdaily &#183; marketdaily.ai</text>'
    )
    return "".join(p)


def render_card(spec, w=W, h=H):
    """獨立可用的 SVG 字串（w×h）。"""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">{_card_inner(spec, w, h)}</svg>'
    )


def _render_with_playwright(spec, out_path, w, h):
    """跨平台 fallback(winrig 無 rsvg-convert/qlmanage 時用):headless Chrome 直接screenshot inline SVG。"""
    from playwright.sync_api import sync_playwright

    svg = render_card(spec, w, h)
    html = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        f'*{{margin:0;padding:0}}body{{width:{w}px;height:{h}px;overflow:hidden}}'
        f'</style></head><body>{svg}</body></html>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.set_content(html, wait_until="load")
            page.screenshot(path=str(out_path))
        finally:
            browser.close()
    return out_path


def make_card(spec, out_path, w=W, h=H):
    """spec → PNG。優先用 rsvg-convert(跨平台),退回 macOS qlmanage,再退回 Playwright headless Chrome(跨平台)。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsvg-convert"):
        with tempfile.TemporaryDirectory() as td:
            svg_p = Path(td) / "card.svg"
            svg_p.write_text(render_card(spec, w, h), encoding="utf-8")
            subprocess.run(
                ["rsvg-convert", "-w", str(w), "-h", str(h), str(svg_p), "-o", str(out_path)],
                check=True, capture_output=True,
            )
        return out_path
    if shutil.which("qlmanage"):
        with tempfile.TemporaryDirectory() as td:
            side = max(w, h)
            ox, oy = (side - w) // 2, (side - h) // 2
            square = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" '
                f'width="{side}" height="{side}">'
                f'<rect width="{side}" height="{side}" fill="{BG}"/>'
                f'<svg x="{ox}" y="{oy}" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'{_card_inner(spec, w, h)}</svg></svg>'
            )
            svg_p = Path(td) / "card.svg"
            svg_p.write_text(square, encoding="utf-8")
            subprocess.run(
                ["qlmanage", "-t", "-s", str(side), "-o", td, str(svg_p)],
                capture_output=True,
            )
            big = Path(td) / "card.svg.png"
            if not big.exists():
                raise RuntimeError("qlmanage 渲染失敗")
            subprocess.run(
                ["sips", "-c", str(h), str(w), str(big), "--out", str(out_path)],
                capture_output=True, check=True,
            )
        return out_path
    return _render_with_playwright(spec, out_path, w, h)
