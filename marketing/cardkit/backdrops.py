#!/usr/bin/env python3
"""cardkit 背景層 —— 16 種程序化生成的深色背景，零素材、零 API、可重現。

為什麼是程序化而不是 AI 生圖：
    ①零邊際成本、零延遲，一天要出幾十張圖時這是唯一撐得住的做法；
    ②同一個 seed 永遠畫出同一張，出事時重現得了；
    ③AI 生圖在品牌卡上最常見的失敗是「白底 + 一眼看得出的 AI 感」，那兩件事在
      marketing/CLAUDE.md 都是明文禁止的(封面不可白底)。
    背景庫留了 `photo` 這一格接真實素材(命書的龍首)，AI 生圖未來要接也是接進同一個介面。

每個 backdrop 收 (size, palette, rng) 回一張 RGB 圖；顏色一律取自 palette，
所以換色票時整批背景跟著換，不會出現「背景是舊品牌色」這種漂移。
"""
import math

from PIL import Image, ImageDraw, ImageFilter


def _blank(size, pal):
    return Image.new("RGB", size, pal.bg)


def _mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _overlay(base, layer, alpha):
    """layer 以 alpha 疊上 base（alpha 可以是 0-1 純量）。"""
    return Image.blend(base, layer, alpha)


def _vignette(img, strength=0.55):
    w, h = img.size
    mask = Image.new("L", (w // 8, h // 8), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w // 16, -h // 16, w // 8 + w // 16, h // 8 + h // 16], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w // 40)).resize((w, h), Image.BILINEAR)
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


def _glow(img, pal, cx, cy, radius, strength=0.30, color=None):
    """柔光暈。用低解析畫再放大 —— 直接畫 1080 的漸層要 O(百萬) 次 putpixel。"""
    w, h = img.size
    sw, sh = w // 6, h // 6
    g = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(g)
    steps = 26
    for i in range(steps, 0, -1):
        r = radius / 6 * i / steps
        v = int(255 * (1 - i / steps) ** 1.6)
        d.ellipse([cx / 6 - r, cy / 6 - r, cx / 6 + r, cy / 6 + r], fill=v)
    g = g.filter(ImageFilter.GaussianBlur(sw // 12)).resize((w, h), Image.BILINEAR)
    tint = Image.new("RGB", (w, h), color or pal.accent)
    return Image.composite(Image.blend(img, tint, strength), img, g)


def _noise(size, rng, scale=6, amp=14):
    w, h = size
    sw, sh = max(2, w // scale), max(2, h // scale)
    n = Image.new("L", (sw, sh))
    n.putdata([128 + rng.randint(-amp, amp) for _ in range(sw * sh)])
    return n.resize((w, h), Image.BICUBIC)


def _grain(img, rng, amount=0.06, scale=2):
    n = _noise(img.size, rng, scale=scale, amp=60).convert("RGB")
    return Image.blend(img, n, amount)


# ── 背景 ────────────────────────────────────────────────────────────────────
def void(size, pal, rng):
    img = _blank(size, pal)
    img = _glow(img, pal, size[0] * 0.5, size[1] * 0.12, size[0] * 1.1, 0.16)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def grid(size, pal, rng):
    w, h = size
    img = _glow(_blank(size, pal), pal, w * 0.5, h * 0.14, w * 1.0, 0.18)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    step = 108
    line = _mix(pal.bg, pal.accent, 0.35)
    for x in range(step, w, step):
        d.line([(x, 0), (x, h)], fill=line, width=1)
    for y in range(step, h, step):
        d.line([(0, y), (w, y)], fill=line, width=1)
    return _grain(_vignette(_overlay(img, layer, 0.5), 0.45), rng, 0.05)


def scanline(size, pal, rng):
    w, h = size
    img = grid(size, pal, rng)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    for y in range(0, h, 6):
        d.rectangle([0, y + 3, w, y + 5], fill=(0, 0, 0))
    return _overlay(img, layer, 0.30)


def mesh(size, pal, rng):
    """多點徑向漸層混色 —— 低解析畫完再放大模糊，得到大面積柔和色塊。"""
    w, h = size
    sw, sh = 120, int(120 * h / w)
    small = Image.new("RGB", (sw, sh), pal.bg)
    d = ImageDraw.Draw(small)
    cols = [pal.accent, pal.accent2, _mix(pal.accent, pal.bg, 0.55), pal.surface]
    for i in range(5):
        cx, cy = rng.uniform(0, sw), rng.uniform(0, sh)
        r = rng.uniform(sw * 0.28, sw * 0.62)
        c = _mix(pal.bg, cols[i % len(cols)], rng.uniform(0.25, 0.55))
        for k in range(14, 0, -1):
            rr = r * k / 14
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                      fill=_mix(pal.bg, c, (1 - k / 14) ** 1.4))
    img = small.filter(ImageFilter.GaussianBlur(6)).resize(size, Image.BICUBIC)
    img = Image.blend(_blank(size, pal), img, 0.72)
    return _grain(_vignette(img, 0.42), rng, 0.06)


def topo(size, pal, rng):
    """等高線 —— 同心不規則環，資料/地形感。"""
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    cx, cy = w * rng.uniform(0.25, 0.75), h * rng.uniform(0.3, 0.7)
    base = rng.uniform(0, math.tau)
    for ring in range(1, 26):
        r = ring * (w / 26) * 0.95
        pts = []
        for a in range(0, 361, 6):
            th = math.radians(a)
            wobble = 1 + 0.06 * math.sin(3 * th + base + ring * 0.35) + 0.035 * math.sin(7 * th - ring * 0.2)
            pts.append((cx + r * wobble * math.cos(th), cy + r * wobble * math.sin(th) * 0.86))
        d.line(pts + [pts[0]], fill=_mix(pal.bg, pal.accent, 0.30), width=2)
    img = _overlay(img, layer, 0.55)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def ticker(size, pal, rng):
    """抽象 K 線 + 趨勢線，只當背景剪影，不代表任何真實行情。"""
    w, h = size
    img = _glow(_blank(size, pal), pal, w * 0.8, h * 0.75, w * 0.9, 0.12, pal.accent2)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    n = 34
    bw = w / n
    y = h * 0.62
    up, dn = pal.accent2, _mix(pal.bg, pal.accent, 0.9)
    for i in range(n):
        delta = rng.uniform(-1, 1) * h * 0.035
        o, c = y, y + delta
        hi = min(o, c) - abs(rng.gauss(0, 1)) * h * 0.02
        lo = max(o, c) + abs(rng.gauss(0, 1)) * h * 0.02
        x = i * bw + bw / 2
        col = up if c < o else dn
        d.line([(x, hi), (x, lo)], fill=col, width=2)
        d.rectangle([x - bw * 0.28, min(o, c), x + bw * 0.28, max(o, c)], fill=col)
        y = c
        y = max(h * 0.42, min(h * 0.86, y))
    img = _overlay(img, layer, 0.32)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def nodes(size, pal, rng):
    """網路節點圖 —— AI／模型題材用。"""
    w, h = size
    img = _glow(_blank(size, pal), pal, w * 0.5, h * 0.5, w * 0.95, 0.14)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    pts = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(46)]
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            dist = math.hypot(a[0] - b[0], a[1] - b[1])
            if dist < w * 0.20:
                t = 1 - dist / (w * 0.20)
                d.line([a, b], fill=_mix(pal.bg, pal.accent, 0.30 * t), width=1)
    for p in pts:
        r = rng.uniform(2, 5)
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=_mix(pal.bg, pal.accent2, 0.75))
    img = _overlay(img, layer, 0.60)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def rays(size, pal, rng):
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    cx, cy = w * rng.choice([0.12, 0.88]), h * -0.1
    for i in range(28):
        a = math.radians(rng.uniform(20, 160))
        spread = math.radians(rng.uniform(0.6, 2.4))
        far = w * 2
        p1 = (cx + far * math.cos(a - spread), cy + far * math.sin(a - spread))
        p2 = (cx + far * math.cos(a + spread), cy + far * math.sin(a + spread))
        d.polygon([(cx, cy), p1, p2], fill=_mix(pal.bg, pal.accent, 0.13))
    img = _overlay(img, layer.filter(ImageFilter.GaussianBlur(16)), 0.55)
    img = _glow(img, pal, cx, cy + h * 0.05, w * 0.8, 0.22)
    return _grain(_vignette(img, 0.55), rng, 0.05)


def flow(size, pal, rng):
    """流場筆觸 —— 柔性有機質感，適合非數據型內容。"""
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    ox, oy = rng.uniform(0, 10), rng.uniform(0, 10)
    for _ in range(150):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        pts = [(x, y)]
        for _ in range(48):
            a = math.sin((x / w + ox) * 3.1) * 2.2 + math.cos((y / h + oy) * 2.7) * 2.2
            x += math.cos(a) * 9
            y += math.sin(a) * 9
            pts.append((x, y))
        d.line(pts, fill=_mix(pal.bg, pal.accent, rng.uniform(0.22, 0.55)), width=rng.choice([1, 2, 2, 3]))
    img = _overlay(img, layer.filter(ImageFilter.GaussianBlur(1.2)), 0.62)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def starmap(size, pal, rng):
    """星圖 + 星座連線 —— 命理／天象題材。"""
    w, h = size
    img = _glow(_blank(size, pal), pal, w * 0.5, h * 0.3, w * 1.0, 0.12, pal.accent)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    for _ in range(320):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.choice([1, 1, 1, 2, 2, 3])
        v = rng.uniform(0.3, 1.0)
        d.ellipse([x - r, y - r, x + r, y + r], fill=_mix(pal.bg, pal.ink, v))
    for _ in range(3):
        cons = [(rng.uniform(w * 0.1, w * 0.9), rng.uniform(h * 0.1, h * 0.9))]
        for _ in range(rng.randint(3, 5)):
            px, py = cons[-1]
            cons.append((px + rng.uniform(-w * 0.16, w * 0.16), py + rng.uniform(-h * 0.12, h * 0.12)))
        d.line(cons, fill=_mix(pal.bg, pal.accent, 0.55), width=2)
        for p in cons:
            d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=pal.accent)
    img = _overlay(img, layer, 0.75)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def ink(size, pal, rng):
    """水墨暈染 —— 不規則團塊重度模糊。"""
    w, h = size
    sw, sh = 90, int(90 * h / w)
    small = Image.new("RGB", (sw, sh), pal.bg)
    d = ImageDraw.Draw(small)
    for _ in range(9):
        cx, cy = rng.uniform(0, sw), rng.uniform(0, sh)
        pts = []
        r0 = rng.uniform(sw * 0.10, sw * 0.30)
        for a in range(0, 360, 20):
            th = math.radians(a)
            r = r0 * rng.uniform(0.62, 1.38)
            pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
        d.polygon(pts, fill=_mix(pal.bg, rng.choice([pal.accent, pal.surface, pal.accent2]), rng.uniform(0.18, 0.42)))
    img = small.filter(ImageFilter.GaussianBlur(5)).resize(size, Image.BICUBIC)
    img = Image.blend(_blank(size, pal), img, 0.8)
    return _grain(_vignette(img, 0.45), rng, 0.07)


def halftone(size, pal, rng):
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    step = 20
    cx, cy = w * rng.uniform(0.2, 0.8), h * rng.uniform(0.15, 0.5)
    maxd = math.hypot(w, h)
    for y in range(step, h, step):
        for x in range(step, w, step):
            t = 1 - math.hypot(x - cx, y - cy) / maxd
            r = max(0.0, t) ** 2.6 * step * 0.42
            if r > 0.4:
                d.ellipse([x - r, y - r, x + r, y + r], fill=_mix(pal.bg, pal.accent, 0.62))
    img = _overlay(img, layer, 0.30)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def paper(size, pal, rng):
    """深色紙纖維 —— 高頻噪點拉伸出纖維方向感。"""
    w, h = size
    fib = _noise((w, h), rng, scale=3, amp=40).resize((w // 3, h), Image.BILINEAR).resize((w, h), Image.BILINEAR)
    img = Image.blend(_blank(size, pal), fib.convert("RGB"), 0.07)
    img = _glow(img, pal, w * 0.5, h * 0.2, w * 0.9, 0.07)
    return _vignette(img, 0.62)


def bokeh(size, pal, rng):
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    for _ in range(22):
        r = rng.uniform(w * 0.05, w * 0.22)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        c = _mix(pal.bg, rng.choice([pal.accent, pal.accent2]), rng.uniform(0.2, 0.5))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    img = _overlay(img, layer.filter(ImageFilter.GaussianBlur(w // 22)), 0.62)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def arcs(size, pal, rng):
    """同心細弧 —— 節氣／黃道軌跡感。"""
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    cx, cy = w * 0.5, h * 1.02
    for i in range(1, 22):
        r = i * w * 0.075
        d.arc([cx - r, cy - r, cx + r, cy + r], 190, 350,
              fill=_mix(pal.bg, pal.accent, 0.16 + 0.02 * (i % 4)), width=2 if i % 4 else 4)
    img = _overlay(img, layer, 0.7)
    img = _glow(img, pal, cx, cy - h * 0.55, w * 0.55, 0.14)
    return _grain(_vignette(img, 0.5), rng, 0.05)


def pillars(size, pal, rng):
    """四柱網格 —— 命盤語彙。"""
    w, h = size
    img = _blank(size, pal)
    layer = img.copy()
    d = ImageDraw.Draw(layer)
    cols, m = 4, w * 0.08
    cw = (w - 2 * m) / cols
    top, bot = h * 0.16, h * 0.86
    for i in range(cols + 1):
        x = m + i * cw
        d.line([(x, top), (x, bot)], fill=_mix(pal.bg, pal.accent, 0.30), width=2)
    for i in range(5):
        y = top + (bot - top) * i / 4
        d.line([(m, y), (w - m, y)], fill=_mix(pal.bg, pal.accent, 0.22), width=2)
    img = _overlay(img, layer, 0.55)
    img = _glow(img, pal, w * 0.5, h * 0.5, w * 0.9, 0.10)
    return _grain(_vignette(img, 0.55), rng, 0.05)


def photo(size, pal, rng, src=None, strength=0.55):
    """真實素材背景（Higgsfield Nano Banana 2 產的片場級底圖）。找不到檔就退回 ink，
    絕不因為缺圖產不出卡。"""
    if src:
        try:
            im = Image.open(src).convert("RGB")
            sw, sh = im.size
            side_w, side_h = size
            scale = max(side_w / sw, side_h / sh)
            im = im.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
            left = (im.size[0] - side_w) // 2
            top = max(0, min(im.size[1] - side_h, int(im.size[1] * 0.5) - side_h // 2))
            im = im.crop((left, top, left + side_w, top + side_h))
            img = Image.blend(_blank(size, pal), im, strength)
            # ⚠️ 遮罩是**對比度保證，不是裝飾**：沒有它，金色標題會落在龍鱗的金線上整段讀不出來
            # (命書 2026-08-17 第一版圖就是這樣)。
            #
            # ⭐ 但它要**看圖說話**：底圖是照著「上緣 45% 是純黑」的構圖規格生成的，
            #    對本來就黑的上緣再壓一層 88% 的遮罩，等於把花錢生的圖蓋掉，卡片又變回純色塊。
            #    所以先量上緣實際亮度，暗就少壓、亮才多壓 —— 判準是「字讀不讀得到」，
            #    不是「有沒有蓋滿」。
            w, h = size
            # 量的是**上緣 45%** —— 那正是生成時下給模型的構圖規格所涵蓋的區域，
            # 也正是標題會壓下去的位置。量整張或量上四成都會被下半的主體拉偏。
            top = img.crop((0, 0, w, int(h * 0.45))).convert("L").resize((16, 16))
            lum = sum(top.getdata()) / 256.0
            peak = 248 if lum > 70 else (205 if lum > 40 else 170)
            fade_to = 0.70 if lum > 70 else 0.60
            scrim = Image.new("L", (1, h))
            a, bnd = int(h * 0.16), int(h * fade_to)
            for y in range(h):
                if y <= a:
                    v = peak
                elif y >= bnd:
                    v = 0
                else:
                    v = int(peak * (1 - (y - a) / (bnd - a)) ** 1.25)
                scrim.putpixel((0, y), v)
            img = Image.composite(_blank(size, pal), img, scrim.resize(size))
            return _vignette(img, 0.40)
        except Exception:
            pass
    return ink(size, pal, rng)


REGISTRY = {
    "void": void, "grid": grid, "scanline": scanline, "mesh": mesh, "topo": topo,
    "ticker": ticker, "nodes": nodes, "rays": rays, "flow": flow, "starmap": starmap,
    "ink": ink, "halftone": halftone, "paper": paper, "bokeh": bokeh, "arcs": arcs,
    "pillars": pillars, "photo": photo,
}
