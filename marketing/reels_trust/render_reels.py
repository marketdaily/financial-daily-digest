"""Render two 12s portrait reels (1080x1920, 30fps, silent) using PIL frames + ffmpeg.

Output:
  docs/social/reel_track_record_zh.mp4
  docs/social/reel_vs_zh.mp4
"""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DOCS_SOCIAL = ROOT.parent.parent / "docs" / "social"
DOCS_SOCIAL.mkdir(parents=True, exist_ok=True)

W, H, FPS, DUR = 1080, 1920, 30, 12
TOTAL = FPS * DUR

FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_REG = "/System/Library/Fonts/STHeiti Light.ttc"


def font(size, bold=True):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def ease_in_out(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def text_center(draw, text, y, size, color, bold=True, alpha=255):
    f = font(size, bold)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2 - bbox[0]
    if alpha < 255:
        # render to temp layer
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((x, y - bbox[1]), text, font=f, fill=color + (alpha,))
        return layer
    draw.text((x, y - bbox[1]), text, font=f, fill=color)
    return None


def draw_check(base, cx, cy, size, color, alpha=255):
    """Draw a check mark (✓) as two line segments."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    s = size
    a = max(0, min(255, int(alpha)))
    col = color + (a,)
    width = max(8, s // 7)
    # short stroke: bottom-left to middle
    ld.line([(cx - s, cy + s * 0.1), (cx - s * 0.25, cy + s * 0.55)], fill=col, width=width)
    # long stroke: middle to top-right
    ld.line([(cx - s * 0.25, cy + s * 0.55), (cx + s * 0.9, cy - s * 0.55)], fill=col, width=width)
    return Image.alpha_composite(base, layer)


def draw_cross(base, cx, cy, size, color, alpha=255):
    """Draw an X cross as two line segments."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    s = size
    a = max(0, min(255, int(alpha)))
    col = color + (a,)
    width = max(8, s // 6)
    ld.line([(cx - s, cy - s), (cx + s, cy + s)], fill=col, width=width)
    ld.line([(cx - s, cy + s), (cx + s, cy - s)], fill=col, width=width)
    return Image.alpha_composite(base, layer)


def draw_arrow_down(base, cx, cy, size, color, alpha=255):
    """Draw a down arrow as line segments."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    s = size
    a = max(0, min(255, int(alpha)))
    col = color + (a,)
    width = max(8, s // 8)
    # vertical shaft
    ld.line([(cx, cy - s), (cx, cy + s * 0.6)], fill=col, width=width)
    # arrow head
    ld.line([(cx, cy + s * 0.6), (cx - s * 0.5, cy + s * 0.1)], fill=col, width=width)
    ld.line([(cx, cy + s * 0.6), (cx + s * 0.5, cy + s * 0.1)], fill=col, width=width)
    return Image.alpha_composite(base, layer)


def composite_text(base, text, y, size, color, bold=True, alpha=255):
    """Draw centered text with optional alpha. Returns updated base."""
    f = font(size, bold)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    bbox = ld.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2 - bbox[0]
    a = max(0, min(255, int(alpha)))
    ld.text((x, y - bbox[1]), text, font=f, fill=color + (a,))
    return Image.alpha_composite(base, layer)


def bg_gradient(top, bottom):
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return img.convert("RGBA")


def solid_bg(color):
    return Image.new("RGBA", (W, H), color + (255,))


def render_frame_track_record(t):
    """t = seconds, 0..12"""
    # Scene boundaries (s):
    # 0-2 hook1, 2-4 hook2, 4-7 stats, 7-10 turn, 10-12 cta
    if t < 2.0:
        bg = solid_bg((10, 10, 14))
        local = t  # 0..2
        # fade in then hold
        alpha = int(255 * ease_in_out(min(local / 1.0, 1.0)))
        bg = composite_text(bg, "他們都說", H // 2 - 200, 130, (180, 180, 188), True, alpha)
        bg = composite_text(bg, "自己很準", H // 2 + 40, 150, (220, 220, 226), True, alpha)
        return bg

    if t < 4.0:
        bg = solid_bg((10, 10, 14))
        local = t - 2.0  # 0..2
        alpha = int(255 * ease_in_out(min(local / 0.8, 1.0)))
        bg = composite_text(bg, "但", H // 2 - 320, 140, (220, 220, 226), True, alpha)
        bg = composite_text(bg, "沒人", H // 2 - 130, 230, (244, 63, 94), True, alpha)
        bg = composite_text(bg, "敢公開錯的紀錄", H // 2 + 160, 130, (220, 220, 226), True, alpha)
        return bg

    if t < 7.0:
        bg = bg_gradient((6, 9, 25), (16, 20, 50))
        local = t - 4.0  # 0..3
        # three stats stagger in: 0.0, 0.5, 1.0
        stats = [
            ("75.5%", "看多勝率", (52, 211, 153), 0.0),
            ("42.9%", "看空勝率", (244, 114, 114), 0.5),
            ("90", "累計個股", (251, 191, 36), 1.0),
        ]
        ys = [380, 850, 1320]
        # title
        bg = composite_text(bg, "真實戰績", 180, 90, (200, 210, 230), True, 255)
        for i, (num, label, color, delay) in enumerate(stats):
            local_i = local - delay
            if local_i < 0:
                continue
            alpha = int(255 * ease_in_out(min(local_i / 0.45, 1.0)))
            # subtle slide up: from +50 -> 0
            offset = int((1 - ease_in_out(min(local_i / 0.45, 1.0))) * 60)
            bg = composite_text(bg, num, ys[i] - offset, 220, color, True, alpha)
            bg = composite_text(bg, label, ys[i] + 200 - offset, 70, (200, 210, 230), False, alpha)
        return bg

    if t < 10.0:
        bg = solid_bg((10, 10, 14))
        local = t - 7.0  # 0..3
        a1 = int(255 * ease_in_out(min(local / 0.7, 1.0)))
        a2 = int(255 * ease_in_out(min((local - 0.9) / 0.7, 1.0))) if local > 0.9 else 0
        bg = composite_text(bg, "錯的", H // 2 - 360, 150, (244, 114, 114), True, a1)
        bg = composite_text(bg, "我們也列出來", H // 2 - 160, 130, (220, 220, 226), True, a1)
        bg = composite_text(bg, "100% 才是假的", H // 2 + 200, 110, (251, 191, 36), True, a2)
        return bg

    # 10-12 CTA
    bg = bg_gradient((10, 14, 35), (20, 28, 70))
    local = t - 10.0  # 0..2
    alpha = int(255 * ease_in_out(min(local / 0.6, 1.0)))
    bg = composite_text(bg, "查看公開戰績", H // 2 - 320, 110, (200, 210, 230), False, alpha)
    bg = composite_text(bg, "marketdaily.ai", H // 2 - 100, 130, (255, 255, 255), True, alpha)
    bg = composite_text(bg, "/track-record", H // 2 + 50, 110, (160, 180, 240), True, alpha)
    # blinking arrow
    blink = 0.6 + 0.4 * math.sin(local * 6.0)
    bg = draw_arrow_down(bg, W // 2, H // 2 + 340, 70, (255, 255, 255), int(255 * blink))
    return bg


def render_frame_vs(t):
    """vs competitors reel, 0..12s"""
    # 0-3 hook, 3-6 competitors, 6-9 marketdaily checks, 9-12 cta
    if t < 3.0:
        bg = solid_bg((10, 10, 14))
        local = t
        alpha = int(255 * ease_in_out(min(local / 0.8, 1.0)))
        bg = composite_text(bg, "為什麼", H // 2 - 360, 130, (200, 200, 208), True, alpha)
        bg = composite_text(bg, "不用", H // 2 - 200, 150, (220, 220, 226), True, alpha)
        a2 = int(255 * ease_in_out(min((local - 0.9) / 0.6, 1.0))) if local > 0.9 else 0
        bg = composite_text(bg, "三竹 / TradingView ?", H // 2 + 40, 100, (244, 114, 114), True, a2)
        return bg

    if t < 6.0:
        bg = solid_bg((12, 12, 18))
        local = t - 3.0  # 0..3
        rows = [
            ("三竹股市", "給你數據,不給判斷", 0.0),
            ("TradingView", "給工具,要你會用", 0.55),
            ("富途牛牛", "要你頻繁下單", 1.1),
        ]
        ys = [430, 870, 1310]
        bg = composite_text(bg, "目前的選擇", 200, 80, (180, 190, 210), False, 255)
        for i, (name, desc, delay) in enumerate(rows):
            li = local - delay
            if li < 0:
                continue
            alpha = int(255 * ease_in_out(min(li / 0.45, 1.0)))
            offset = int((1 - ease_in_out(min(li / 0.45, 1.0))) * 50)
            bg = composite_text(bg, name, ys[i] - offset, 110, (255, 255, 255), True, alpha)
            bg = composite_text(bg, desc, ys[i] + 140 - offset, 64, (180, 180, 200), False, alpha)
            bg = draw_cross(bg, 180, ys[i] + 60 - offset, 55, (244, 63, 94), alpha)
        return bg

    if t < 9.0:
        bg = bg_gradient((4, 30, 22), (8, 60, 45))
        local = t - 6.0  # 0..3
        title_a = int(255 * ease_in_out(min(local / 0.5, 1.0)))
        bg = composite_text(bg, "MarketDaily", 250, 140, (52, 211, 153), True, title_a)
        checks = [
            ("主動推送", 0.5),
            ("個人化內容", 0.95),
            ("公開戰績", 1.4),
            ("無利益衝突", 1.85),
        ]
        ys = [650, 870, 1090, 1310]
        for i, (label, delay) in enumerate(checks):
            li = local - delay
            if li < 0:
                continue
            alpha = int(255 * ease_in_out(min(li / 0.3, 1.0)))
            bg = draw_check(bg, 230, ys[i] + 40, 55, (52, 211, 153), alpha)
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            lf = font(90, True)
            ld.text((350, ys[i] - 10), label, font=lf, fill=(240, 255, 248, alpha))
            bg = Image.alpha_composite(bg, layer)
        return bg

    # 9-12 CTA
    bg = bg_gradient((10, 14, 35), (20, 28, 70))
    local = t - 9.0  # 0..3
    alpha = int(255 * ease_in_out(min(local / 0.6, 1.0)))
    bg = composite_text(bg, "看完整對比", H // 2 - 360, 110, (200, 210, 230), False, alpha)
    bg = composite_text(bg, "marketdaily.ai", H // 2 - 140, 130, (255, 255, 255), True, alpha)
    bg = composite_text(bg, "/vs", H // 2 + 10, 130, (160, 180, 240), True, alpha)
    blink = 0.6 + 0.4 * math.sin(local * 6.0)
    bg = draw_arrow_down(bg, W // 2, H // 2 + 320, 70, (255, 255, 255), int(255 * blink))
    return bg


def render_reel(name, frame_fn):
    print(f"[{name}] rendering {TOTAL} frames ...")
    with tempfile.TemporaryDirectory() as tmp:
        fd = Path(tmp)
        for i in range(TOTAL):
            t = i / FPS
            img = frame_fn(t).convert("RGB")
            img.save(fd / f"f{i:05d}.png", "PNG", compress_level=1)
            if i % 60 == 0:
                print(f"  {name}: frame {i}/{TOTAL}")
        out = DOCS_SOCIAL / f"{name}.mp4"
        print(f"[{name}] encoding -> {out}")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(fd / "f%05d.png"),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-movflags", "+faststart",
            "-an",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{r.stderr[-1500:]}")
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"[{name}] done: {out} ({size_mb:.2f} MB)")
        return out


def main():
    render_reel("reel_track_record_zh", render_frame_track_record)
    render_reel("reel_vs_zh", render_frame_vs)
    print("RENDER_DONE")


if __name__ == "__main__":
    main()
