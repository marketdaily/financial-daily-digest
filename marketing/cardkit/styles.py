#!/usr/bin/env python3
"""cardkit 版面層 + 風格清單 + 輪替器。

四個獨立維度：版面(layout) × 背景(backdrop) × 色票(palette) × 字體/字重。
組合數上千，但**只發布策展過的清單** —— 亂數組合會產出難看的卡，
而「難看」在社群上比「重複」更貴。清單裡每一條都人工看過。

輪替規則(pick)：以貼文 id 的雜湊決定 → 同一則永遠得到同一個風格(可重現)，
再排除最近 N 則用過的風格 → 九宮格滑下來不會連續撞版。
"""
import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from . import backdrops
from .theme import (MD_PALETTES, MS_PALETTES, PALETTES, draw_lines, fit, font,
                    text_center, wrap_px, _width)

SIZE_45 = (1080, 1350)      # IG 4:5，觸及最佳
SIZE_11 = (1080, 1080)

STATE_DIR = Path(__file__).parent / "state"


# ── 品牌招牌 ────────────────────────────────────────────────────────────────
def _md_mark(d, x, y, size, pal):
    """MarketDaily 條圖標記。"""
    s = size / 48.0
    d.rounded_rectangle([x, y, x + size, y + size], radius=12 * s, fill=pal.surface,
                        outline=pal.accent, width=max(1, int(1.5 * s)))
    bars = [(9, 31, 6, 9, 0.45), (19, 23, 6, 17, 0.8), (29, 13, 6, 27, 1.0)]
    for bx, by, bw, bh, t in bars:
        c = tuple(int(pal.bg[i] + (pal.accent[i] - pal.bg[i]) * t) for i in range(3))
        d.rounded_rectangle([x + bx * s, y + by * s, x + (bx + bw) * s, y + (by + bh) * s],
                            radius=2 * s, fill=c)
    d.ellipse([x + 39 * s, y + 6 * s, x + 45 * s, y + 12 * s], fill=pal.accent2)


def _ms_seal(d, x, y, side, pal):
    """命書朱印「命」。朱砂在官網 token 只准用於印記。"""
    d.rectangle([x, y, x + side, y + side], fill=pal.seal)
    f = font(int(side * 0.72), 700, "serif")
    l, t, r, b = d.textbbox((0, 0), "命", font=f)
    d.text((x + side / 2 - (l + r) / 2, y + side / 2 - (t + b) / 2), "命", font=f, fill=(244, 236, 218))


def chrome(img, brand, pal, spec, compact=False):
    """品牌招牌 + 頁尾 + 選配 CTA 膠囊。

    每張卡都有這一層，這是「風格天天換、但一眼還是同一個帳號」的錨 ——
    沒有它，多風格就變成「看起來像十個不同的帳號」，那比全部長一樣更糟。
    """
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    if spec.get("cta"):
        cf = font(33, 700)
        cw2 = _width(spec["cta"], cf) + 96
        cx, cy = (w - cw2) / 2, h - int(h * 0.158)
        d.rounded_rectangle([cx, cy, cx + cw2, cy + 78], radius=39, fill=pal.accent)
        d.text((cx + 48, cy + 18), spec["cta"], font=cf, fill=pal.bg)
    if brand.key == "marketdaily":
        _md_mark(d, pad, int(h * 0.062), 62, pal)
        d.text((pad + 82, int(h * 0.062) + 8), "MarketDaily", font=font(40, 800), fill=pal.ink)
    else:
        _ms_seal(d, w - pad - 72, h - int(h * 0.055) - 72, 72, pal)
    if not compact:
        f = font(27, 500)
        text_center(d, brand.footer, w / 2, h - int(h * 0.062), f, pal.body)
    return img


def _kicker(d, text, x, y, pal, align="left", box_w=0, boxed=True):
    if not text:
        return y
    f = font(30, 700)
    tw = _width(text, f)
    if align == "center":
        x = x + (box_w - (tw + 56)) / 2
    if boxed:
        d.rounded_rectangle([x, y, x + tw + 56, y + 58], radius=29,
                            fill=None, outline=pal.accent, width=2)
        d.text((x + 28, y + 12), text, font=f, fill=pal.accent)
    else:
        d.text((x, y), text, font=f, fill=pal.accent)
    return y + 58


# ── 版面 ────────────────────────────────────────────────────────────────────
# 共同規則：每個版面先**量**出整塊內容多高，再放進安全區的垂直中央。
# 首版是「從固定 y 往下畫」，短內容就在下半留一大片空白、長內容就撞到頁尾 ——
# 對照表上一眼可見(2026-08-24)。量了才放，同一個版面吃長短不一的文案都成立。


def zone(st, size):
    """(上界, 下界)：避開頂部品牌列與底部頁尾/朱印。"""
    h = size[1]
    top, bot = st.get("_zone", (0.165, 0.875))
    return int(h * top), int(h * bot)


def _place(top, bot, block_h, bias=0.5):
    """把 block 放進 [top,bot]。bias<0.5 偏上。塞不下就貼齊上界(寧可下面被裁也不要上面被砍)。"""
    room = bot - top - block_h
    return top + max(0, int(room * bias))


def lay_hero(img, spec, pal, st):
    """置中大字。最泛用，也最像「一句話海報」。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.10)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 98 if spec.get("kicker") else 0
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.58), [104, 92, 84, 76, 68, 60, 54, 48],
                       st["family"], st.get("weight", 800), 1.24)
    head_h = len(lines) * lh
    body_parts = None
    body_h = 0
    if spec.get("body"):
        bf, blines, blh = fit(spec["body"], cw, int(zh * 0.26), [40, 37, 34, 31, 28],
                              st["family"], 400, 1.55)
        body_parts = (bf, blines, blh)
        body_h = 66 + len(blines) * blh
    y = _place(top, bot, kick_h + head_h + body_h)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal, "center", cw)
        y += kick_h
    y = draw_lines(d, lines, pad, y, f, lh, pal.ink, "center", cw)
    if body_parts:
        d.line([(w / 2 - 60, y + 34), (w / 2 + 60, y + 34)], fill=pal.accent, width=3)
        bf, blines, blh = body_parts
        draw_lines(d, blines, pad, y + 66, bf, blh, pal.body, "center", cw)
    return img


def lay_left(img, spec, pal, st):
    """左對齊資訊塊 + 強調短線。MarketDaily 原本那一版的骨架。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 92 if spec.get("kicker") else 0
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.56), [92, 84, 76, 68, 60, 54, 48],
                       st["family"], st.get("weight", 800), 1.24)
    head_h = len(lines) * lh
    body_parts, body_h = None, 0
    if spec.get("body"):
        bf, blines, blh = fit(spec["body"], cw, int(zh * 0.28), [40, 37, 34, 31, 28],
                              st["family"], 400, 1.55)
        body_parts = (bf, blines, blh)
        body_h = 44 + len(blines) * blh
    y = _place(top, bot, kick_h + 52 + head_h + body_h, 0.44)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal)
        y += kick_h
    d.rounded_rectangle([pad, y, pad + 76, y + 8], radius=4, fill=pal.accent)
    y = draw_lines(d, lines, pad, y + 52, f, lh, pal.ink)
    if body_parts:
        bf, blines, blh = body_parts
        draw_lines(d, blines, pad, y + 44, bf, blh, pal.body)
    return img


def lay_bigstat(img, spec, pal, st):
    """巨型數字當主角。stat 沒給就退回 hero —— 缺欄位不該產出空白卡。"""
    stat = spec.get("stat")
    if not stat:
        return lay_hero(img, spec, pal, st)
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.10)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 92 if spec.get("kicker") else 0
    size = 320
    while _width(stat, font(size, 800)) > cw and size > 90:
        size -= 10
    sf = font(size, 800)
    stat_h = int(size * 1.10) + (74 if spec.get("stat_label") else 0)
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.30), [64, 58, 52, 46, 42, 38],
                       st["family"], 700, 1.32)
    head_h = 30 + len(lines) * lh
    y = _place(top, bot, kick_h + stat_h + head_h)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal, "center", cw)
        y += kick_h
    text_center(d, stat, w / 2, y, sf, pal.accent)
    y += int(size * 1.10)
    if spec.get("stat_label"):
        text_center(d, spec["stat_label"], w / 2, y, font(38, 600), pal.body)
        y += 74
    draw_lines(d, lines, pad, y + 30, f, lh, pal.ink, "center", cw)
    return img


def lay_quote(img, spec, pal, st):
    """大引號 + 襯線 —— 觀點型、金句型。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.12)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.52), [82, 74, 66, 60, 54, 48, 44],
                       "serif", 600, 1.44)
    head_h = len(lines) * lh
    body_parts, body_h = None, 0
    if spec.get("body"):
        bf, blines, blh = fit(spec["body"], cw, int(zh * 0.22), [36, 33, 30, 27], "serif", 400, 1.55)
        body_parts = (bf, blines, blh)
        body_h = 70 + len(blines) * blh
    mark_h = 150
    y = _place(top, bot, mark_h + head_h + body_h)
    d.text((pad - 16, y - 60), "“", font=font(230, 800, "serif"), fill=pal.accent)
    y += mark_h
    y = draw_lines(d, lines, pad, y, f, lh, pal.ink)
    d.line([(pad, y + 36), (pad + 90, y + 36)], fill=pal.accent, width=3)
    if body_parts:
        bf, blines, blh = body_parts
        draw_lines(d, blines, pad, y + 70, bf, blh, pal.body)
    return img


def _items(spec):
    it = spec.get("items")
    if it:
        return [str(x) for x in it][:5]
    body = spec.get("body") or ""
    parts = [p.strip() for p in body.replace("、", "\n").split("\n") if p.strip()]
    return parts[:5]


def lay_list(img, spec, pal, st):
    """編號條列。items 沒給就從 body 拆行。"""
    items = _items(spec)
    if not items:
        return lay_left(img, spec, pal, st)
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 92 if spec.get("kicker") else 0
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.30), [72, 64, 58, 52, 46],
                       st["family"], 800, 1.22)
    head_h = len(lines) * lh
    row_room = int(zh * 0.58) // max(1, len(items))
    rows = []
    for it in items:
        itf, itl, itlh = fit(it, cw - 96, row_room - 20, [46, 42, 38, 34, 30, 27], st["family"], 500, 1.4)
        rows.append((itf, itl, itlh, max(len(itl) * itlh + 30, 78)))
    total = kick_h + head_h + 44 + sum(r[3] for r in rows)
    y = _place(top, bot, total, 0.46)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal)
        y += kick_h
    y = draw_lines(d, lines, pad, y, f, lh, pal.ink) + 44
    for i, (itf, itl, itlh, rh) in enumerate(rows, 1):
        d.ellipse([pad, y + 2, pad + 54, y + 56], outline=pal.accent, width=3)
        text_center(d, str(i), pad + 27, y + 12, font(30, 800), pal.accent)
        draw_lines(d, itl, pad + 92, y + 2, itf, itlh, pal.ink)
        y += rh
    return img


def lay_rank(img, spec, pal, st):
    """排行榜階梯 —— 立場型內容(誰第一)的專用版面，天生招人反駁。"""
    items = _items(spec)
    if not items:
        return lay_left(img, spec, pal, st)
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 88 if spec.get("kicker") else 0
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.30), [78, 70, 62, 56, 50],
                       st["family"], 800, 1.22)
    head_h = len(lines) * lh
    n = len(items)
    row_h = min(158, int(zh * 0.54) // n)
    total = kick_h + head_h + 50 + row_h * n
    y = _place(top, bot, total, 0.42)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal)
        y += kick_h
    y = draw_lines(d, lines, pad, y, f, lh, pal.ink) + 50
    for i, it in enumerate(items, 1):
        t = 1.0 - (i - 1) / max(1, n)
        bar_w = int(cw * (0.46 + 0.54 * t))
        c = tuple(int(pal.bg[k] + (pal.accent[k] - pal.bg[k]) * (0.22 + 0.55 * t)) for k in range(3))
        d.rounded_rectangle([pad, y, pad + bar_w, y + row_h - 22], radius=14, fill=c)
        num_col = pal.bg if i == 1 else pal.ink
        d.text((pad + 26, y + (row_h - 22) / 2 - int(row_h * 0.33)), str(i),
               font=font(int(row_h * 0.50), 800), fill=num_col)
        itf, itl, itlh = fit(it, bar_w - 140, row_h - 34, [44, 40, 36, 32, 28], st["family"], 700, 1.2)
        draw_lines(d, itl, pad + 116, y + (row_h - 22 - len(itl) * itlh) / 2, itf, itlh, num_col)
        y += row_h
    return img


def lay_split(img, spec, pal, st):
    """上下兩格對比 —— 迷思 vs 事實。left/right 沒給就用 headline/body。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    top_t = spec.get("left") or spec["headline"]
    bot_t = spec.get("right") or spec.get("body") or ""
    mid = (top + bot) // 2
    d.rectangle([0, mid - 3, w, mid + 3], fill=pal.accent)
    for label, text, y0, y1, col in (
            ((spec.get("left_label") or "✕"), top_t, top, mid - 46, pal.body),
            ((spec.get("right_label") or "✓"), bot_t, mid + 46, bot, pal.ink)):
        if not text:
            continue
        f, lines, lh = fit(text, cw, (y1 - y0) - 86, [80, 72, 64, 58, 52, 46, 40], st["family"], 700, 1.3)
        blk = 70 + len(lines) * lh
        yy = _place(y0, y1, blk)
        d.text((pad, yy), label, font=font(46, 800), fill=pal.accent)
        draw_lines(d, lines, pad, yy + 70, f, lh, col)
    return img


def lay_duel(img, spec, pal, st):
    """左右兩欄對照 —— A 說 vs B 說。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.07)
    colw = (w - 2 * pad - 48) / 2
    top, bot = zone(st, img.size)
    zh = bot - top
    kick_h = 96 if spec.get("kicker") else 0
    cols = []
    for label, text in (((spec.get("left_label") or "A"), spec.get("left") or spec["headline"]),
                        ((spec.get("right_label") or "B"), spec.get("right") or spec.get("body") or "")):
        if not text:
            cols.append(None)
            continue
        f, lines, lh = fit(text, colw, int(zh * 0.62), [72, 64, 58, 52, 46, 40, 34], st["family"], 700, 1.34)
        cols.append((label, f, lines, lh, 66 + len(lines) * lh))
    body_h = max((c[4] for c in cols if c), default=0)
    y = _place(top, bot, kick_h + body_h, 0.42)
    if kick_h:
        _kicker(d, spec["kicker"], pad, y, pal)
        y += kick_h
    d.line([(w / 2, y - 16), (w / 2, y + body_h + 16)], fill=pal.accent, width=2)
    for i, c in enumerate(cols):
        if not c:
            continue
        label, f, lines, lh, _ = c
        x = pad + i * (colw + 48)
        d.text((x, y), label, font=font(34, 800), fill=pal.accent)
        draw_lines(d, lines, x, y + 66, f, lh, pal.ink if i else pal.body)
    return img


def lay_banner(img, spec, pal, st):
    """頂部色帶 + 大標 —— 新聞快評感。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    d.rectangle([0, top, w, top + 78], fill=pal.accent)
    d.text((pad, top + 16), spec.get("kicker") or "快評", font=font(38, 800), fill=pal.bg)
    zt = top + 78
    zh = bot - zt
    f, lines, lh = fit(spec["headline"], cw, int(zh * 0.56), [88, 80, 72, 64, 58, 52, 46],
                       st["family"], 800, 1.24)
    head_h = len(lines) * lh
    body_parts, body_h = None, 0
    if spec.get("body"):
        bf, blines, blh = fit(spec["body"], cw, int(zh * 0.30), [38, 35, 32, 29], st["family"], 400, 1.55)
        body_parts = (bf, blines, blh)
        body_h = 44 + len(blines) * blh
    y = _place(zt, bot, head_h + body_h, 0.42)
    y = draw_lines(d, lines, pad, y, f, lh, pal.ink)
    if body_parts:
        bf, blines, blh = body_parts
        draw_lines(d, blines, pad, y + 44, bf, blh, pal.body)
    return img


def lay_sticker(img, spec, pal, st):
    """超大字壓底 + 斜貼標籤 —— 最「社群」的一版，適合短句。刻意保持底部對齊。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.085)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    f, lines, lh = fit(spec["headline"], cw, int((bot - top) * 0.62),
                       [128, 112, 100, 88, 78, 68, 60], st["family"], 900, 1.14)
    y = bot - len(lines) * lh
    if spec.get("kicker"):
        kf = font(40, 800)
        tw = _width(spec["kicker"], kf)
        tag = Image.new("RGBA", (int(tw) + 80, 110), (0, 0, 0, 0))
        td = ImageDraw.Draw(tag)
        td.rounded_rectangle([0, 0, tw + 64, 84], radius=18, fill=pal.accent)
        td.text((32, 16), spec["kicker"], font=kf, fill=pal.bg)
        tag = tag.rotate(-7, expand=True, resample=Image.BICUBIC)
        img.paste(tag, (pad, max(top, y - 150)), tag)
    draw_lines(d, lines, pad, y, f, lh, pal.ink)
    return img


def lay_vertical(img, spec, pal, st):
    """直排標題（右起）—— 命書專用，一眼就是東方版面。"""
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.11)
    top, bot = zone(st, img.size)
    text = "".join(spec["headline"].split("\n"))
    size = 92
    per_col = max(4, int((bot - top) // (size * 1.16)))
    while math.ceil(len(text) / per_col) > 3 and size > 48:
        size -= 8
        per_col = max(4, int((bot - top) // (size * 1.16)))
    # ⚠️ 直排的孤字欄:len=25、per_col=12 會排成 12/12/1 —— 最後一欄一個字，
    # 看起來像排版壞掉。改成把總字數平均分到欄數上(12/12/1 → 9/8/8)。
    ncol = math.ceil(len(text) / per_col)
    if ncol > 1:
        per_col = math.ceil(len(text) / ncol)
    f = font(size, 700, "serif")
    step = int(size * 1.16)
    used_h = min(len(text), per_col) * step
    y0 = _place(top, bot, used_h, 0.30)
    x = w - pad - size
    for i, ch in enumerate(text):
        col, row = divmod(i, per_col)
        d.text((x - col * int(size * 1.5), y0 + row * step), ch, font=f, fill=pal.ink)
    if spec.get("body"):
        bw = w - 2 * pad - ncol * int(size * 1.5) - 40
        if bw > 220:
            bf, blines, blh = fit(spec["body"], bw, int((bot - top) * 0.5), [32, 29, 26, 24],
                                  "serif", 400, 1.6)
            draw_lines(d, blines, pad, y0 + min(used_h, 300) + 60, bf, blh, pal.body)
    d.line([(pad, y0), (pad, y0 + min(used_h, 260))], fill=pal.accent, width=3)
    return img



def lay_body(img, spec, pal, st):
    """輪播內文卡 —— 這張是拿來**讀**的不是拿來掃的：字距鬆、置中、頁碼在上、免責在下。

    刻意比封面安靜：一則貼文裡風格要一致，變化發生在**貼文與貼文之間**。
    整串輪播每張都在搶眼睛的話，讀者一張都讀不完。
    """
    w, h = img.size
    d = ImageDraw.Draw(img)
    pad = int(w * 0.115)
    cw = w - 2 * pad
    top, bot = zone(st, img.size)
    if spec.get("pages"):
        text_center(d, f"{spec.get('page', 1)} / {spec['pages']}", w / 2, top, font(32, 500), pal.accent)
    f, lines, lh = fit(spec["headline"], cw, int((bot - top) * 0.62), [56, 52, 48, 44, 40, 36, 32],
                       st["family"], 400, 1.62)
    y = _place(top + 60, bot - 60, len(lines) * lh)
    draw_lines(d, lines, pad, y, f, lh, pal.ink, "center", cw)
    if spec.get("note"):
        text_center(d, spec["note"], w / 2, bot - 6, font(30, 400), pal.body)
    return img


def lay_cta(img, spec, pal, st):
    """輪播末頁 CTA。IG caption 裡的網址不可點，所以講「連結在個人檔案」而不是印一串 UTM。

    ⚠️ 這裡不可以放 emoji：明體(NotoSerifTC)沒有 emoji glyph，PIL 不報錯，
       會靜靜畫一個豆腐方框出去(命書 2026-08-17 首版被抓到)。
    """
    w, h = img.size
    d = ImageDraw.Draw(img)
    top, bot = zone(st, img.size)
    lines = spec.get("cta_lines") or [spec["headline"]]
    # (字級, 字重, 下方間距)。間距寫死而不是用行高倍率 —— 這四行的角色不同
    # (問句／說明／網址／指路)，讓它們等距反而看起來像四句沒有關係的話。
    ROLES = [(72, 700, 54), (40, 400, 46), (58, 600, 34), (34, 400, 0)]
    total = sum(ROLES[min(i, 3)][0] + ROLES[min(i, 3)][2] for i in range(len(lines))) + 40
    y = _place(top, bot, total)
    for i, ln in enumerate(lines):
        size, weight, gap = ROLES[min(i, 3)]
        col = pal.accent if i == 2 else (pal.ink if i == 0 else pal.body)
        text_center(d, ln, w / 2, y, font(size, weight, st["family"]), col)
        y += size + gap
        if i == 1:
            d.line([(w / 2 - 120, y - 26), (w / 2 + 120, y - 26)], fill=pal.accent, width=2)
    return img


LAYOUTS = {
    "hero": lay_hero, "left": lay_left, "bigstat": lay_bigstat, "quote": lay_quote,
    "list": lay_list, "rank": lay_rank, "split": lay_split, "duel": lay_duel,
    "banner": lay_banner, "sticker": lay_sticker, "vertical": lay_vertical,
    "body": lay_body, "cta": lay_cta,
}



# ── 真實底圖(plates) ────────────────────────────────────────────────────────
# 2026-08-24 老闆:「你他媽只是換了個顏色而已，去用我的 higgsfield credit
# nano banana 2 去生成一些圖」。程序化背景解決的是「每張都一樣」，但它們仍然是圖形不是
# 影像 —— 卡片裡沒有任何「畫面」。這 14 張是 Nano Banana 2 依 genai-prompt-pro §4.5
# 片場 rig block 生成的:MarketDaily 走 Sony Venice 2 + Cooke S7/i 40mm + Greig Fraser /
# Villeneuve / Sicario 夜間車隊 / Vision3 500T 冷調;命書走 Hasselblad H6D-100c +
# HC 120mm macro + Sugimoto 極簡 / 王家衛環境光 / Eterna 近單色暖褐。兩組 rig 五欄全異。
# 每張都下了同一條交付約束:上緣 45% 是無細節暗場(標題要壓在那裡)、畫面零文字、燈具不入鏡。
PLATE_DIR = Path(__file__).parent / "plates"

PLATES = {
    "marketdaily": {
        "world": ["world_strait", "cargo_port"],
        "macro": ["macro_podium", "energy_lng"],
        "ai": ["ai_datacenter", "chip_wafer"],
        "company": ["chip_wafer", "market_floor"],
        "market": ["market_floor", "taipei_rain"],
        "local": ["taipei_rain"],
    },
    "mingshu": {
        "dragon": ["dragon_ink"],
        "sky": ["starfield_ridge", "moon_water"],
        "tool": ["luopan_compass"],
        "ritual": ["incense_smoke"],
        "season": ["dew_grass"],
    },
}


def plate_path(brand_key, name):
    p = PLATE_DIR / brand_key / f"{name}.jpg"
    return str(p) if p.exists() else None


def pick_plate(brand_key, topic, key):
    """(品牌, 題材, 卡片鍵) → 底圖檔。題材對得上就用該桶，對不上就在全部底圖裡雜湊挑。

    題材優先是重點:國際新聞配油輪、AI 新聞配機房、節氣配露水 —— 底圖跟內容有關係，
    才不是「隨機貼一張漂亮照片」。對不上時退回雜湊，永遠挑得到一張。
    """
    buckets = PLATES.get(brand_key, {})
    names = buckets.get(topic) if topic else None
    if not names:
        names = sorted({n for v in buckets.values() for n in v})
    if not names:
        return None
    n = int(hashlib.sha256(f"{brand_key}:{key}".encode()).hexdigest()[:8], 16)
    return plate_path(brand_key, names[n % len(names)])


# ── 品牌 ────────────────────────────────────────────────────────────────────
class Brand:
    def __init__(self, key, footer, styles, palettes, kicker=None):
        self.key = key
        self.footer = footer
        self.styles = styles
        self.palettes = palettes
        self.kicker = kicker


CALM = {"photo": "ink", "scanline": "void", "mesh": "void", "ticker": "grid",
        "nodes": "void", "rays": "void", "starmap": "void", "halftone": "paper",
        "bokeh": "void", "arcs": "paper", "pillars": "paper", "flow": "void",
        "topo": "paper", "grid": "grid", "ink": "ink", "void": "void", "paper": "paper"}


def _s(sid, layout, backdrop, palette, family="sans", weight=800, **extra):
    d = {"id": sid, "layout": layout, "backdrop": backdrop, "palette": palette,
         "family": family, "weight": weight, "body_backdrop": CALM.get(backdrop, "void")}
    d.update(extra)
    return d


# MarketDaily：14 種策展風格。每一條的 layout/backdrop/palette 至少有兩個維度不同，
# 所以連續兩則就算撞到同一個 layout 也不會看起來一樣。
MD_STYLES = [
    _s("terminal",   "left",    "scanline", "amber"),
    _s("neon_mesh",  "hero",    "mesh",     "amber"),
    _s("ice_stat",   "bigstat", "void",     "ice"),
    _s("tape",       "left",    "ticker",   "green"),
    _s("ai_nodes",   "hero",    "nodes",    "violet"),
    _s("ledger",     "quote",   "paper",    "slate",  family="serif", weight=600),
    _s("topo_list",  "list",    "topo",     "amber"),
    _s("myth_split", "split",   "halftone", "ember"),
    _s("breaking",   "banner",  "rays",     "ember"),
    _s("bold_tag",   "sticker", "mesh",     "green",  weight=900),
    _s("rank_board", "rank",    "grid",     "amber"),
    _s("versus",     "duel",    "void",     "ice"),
    _s("orbit",      "hero",    "bokeh",    "violet"),
    _s("flowfield",  "left",    "flow",     "green"),
    # ── 真實底圖組(Nano Banana 2) ──
    _s("plate_hero",   "hero",    "photo", "amber",  photo_strength=0.66),
    _s("plate_left",   "left",    "photo", "ice",    photo_strength=0.62),
    _s("plate_banner", "banner",  "photo", "ember",  photo_strength=0.58),
    _s("plate_stat",   "bigstat", "photo", "green",  photo_strength=0.60),
    _s("plate_sticker", "sticker", "photo", "violet", weight=900, photo_strength=0.68),
    _s("plate_quote",  "quote",   "photo", "slate",  family="serif", weight=600, photo_strength=0.58),
]

# 命書：12 種。主色票黑金取自官網 :root，龍首(photo)保留當其中一種而不是唯一一種。
MS_STYLES = [
    _s("dragon",     "hero",     "photo",    "moxin",    family="serif", weight=700,
       topic="dragon", photo_strength=0.58),
    _s("seal_min",   "hero",     "void",     "moxin",    family="serif", weight=700),
    _s("starmap",    "hero",     "starmap",  "xuanshui", family="serif", weight=700),
    _s("ink_quote",  "quote",    "ink",      "moxin",    family="serif", weight=600),
    _s("rank_zhu",   "rank",     "grid",     "zhusha",   family="serif", weight=700),
    _s("pan_grid",   "list",     "pillars",  "qingyu",   family="serif", weight=700),
    _s("duel_gpt",   "duel",     "void",     "xuanshui", family="serif", weight=700),
    _s("solar",      "hero",     "arcs",     "moxin",    family="serif", weight=700),
    _s("zhi_pai",    "vertical", "paper",    "moxin",    family="serif", weight=700),
    _s("banner_zhu", "banner",   "ink",      "zhusha",   family="serif", weight=700),
    _s("split_myth", "split",    "halftone", "cangmu",   family="serif", weight=700),
    _s("bold_ms",    "sticker",  "mesh",     "zhusha",   family="serif", weight=800),
    # ── 真實底圖組(Nano Banana 2) ──
    _s("plate_dragon", "hero",    "photo", "moxin",  family="serif", weight=700,
       topic="dragon", photo_strength=0.70),
    _s("plate_sky",    "hero",    "photo", "xuanshui", family="serif", weight=700,
       topic="sky", photo_strength=0.66),
    _s("plate_tool",   "left",    "photo", "moxin",  family="serif", weight=700,
       topic="tool", photo_strength=0.62),
    _s("plate_ritual", "quote",   "photo", "zhusha", family="serif", weight=600,
       topic="ritual", photo_strength=0.62),
    _s("plate_season", "vertical", "photo", "cangmu", family="serif", weight=700,
       topic="season", photo_strength=0.60),
]

BRANDS = {
    "marketdaily": Brand("marketdaily", "@marketdaily · marketdaily.ai", MD_STYLES, MD_PALETTES),
    "mingshu": Brand("mingshu", "mingshu.tw", MS_STYLES, MS_PALETTES, kicker="命書"),
}


# ── 輪替 ────────────────────────────────────────────────────────────────────
def _ledger_path(brand_key):
    return STATE_DIR / f"{brand_key}_recent.json"


def recent_styles(brand_key, limit=6):
    p = _ledger_path(brand_key)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))[-limit:]
    except Exception:
        return []


def remember_style(brand_key, style_id, keep=40):
    p = _ledger_path(brand_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        hist = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except Exception:
        hist = []
    hist.append(style_id)
    p.write_text(json.dumps(hist[-keep:], ensure_ascii=False), encoding="utf-8")


def photo_styles(brand_key):
    return [s for s in BRANDS[brand_key].styles if s["backdrop"] == "photo"]


def assign(brand_key, key, prefer=None, spread=5, photo_only=False):
    """(品牌, 卡片鍵) → 風格，且**寫進指派表**。

    為什麼要指派表而不是純雜湊：
      - 純雜湊同一張卡重跑永遠一樣(好)，但相鄰兩則有 1/N 機率撞同一個風格(壞)。
      - 純「避開最近 N 個」能保證不撞版(好)，但同一張卡重跑會換長相(壞，
        圖卡是會被重新產生的——promote_* 幾支發現 PNG 不在就現場再產一次)。
    指派表兩個都要：第一次指派時避開最近 spread 個，之後永遠回同一個。
    """
    p = _ledger_path(brand_key)
    try:
        led = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        led = {}
    if not isinstance(led, dict):
        led = {}
    amap = led.setdefault("map", {})
    order = led.setdefault("order", [])
    if key in amap:
        return next((s for s in BRANDS[brand_key].styles if s["id"] == amap[key]),
                    BRANDS[brand_key].styles[0])
    recent = [amap[k] for k in order[-spread:] if k in amap]
    st = pick(brand_key, key, avoid=recent, prefer=prefer, photo_only=photo_only)
    amap[key] = st["id"]
    order.append(key)
    led["order"] = order[-400:]
    led["map"] = {k: v for k, v in amap.items() if k in set(led["order"])}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(led, ensure_ascii=False, indent=0), encoding="utf-8")
    return st


def pick(brand_key, key, avoid=None, prefer=None, photo_only=False):
    """(品牌, 貼文id) → 風格。同一個 id 永遠得到同一個結果。

    avoid = 最近用過的風格 id；全部都被 avoid 掉時退回純雜湊(不會挑不到)。
    prefer = 內容型別提示(例如 'rank'/'news'/'ai')，命中就優先在那個子集裡挑。
    """
    brand = BRANDS[brand_key]
    pool = brand.styles
    # ⚠️ 這則有「按主題現生的底圖」時,風格**必須**落在 photo 版位。
    #    少了這道限制,現生的圖會被指派到程序化背景的風格上 —— 錢花了、圖產了,
    #    畫面上一點都看不到,而且程式一路回報成功。
    if photo_only:
        pool = photo_styles(brand_key) or pool
    if prefer:
        hinted = [s for s in pool if prefer in (s.get("tags") or []) or s["layout"] == prefer]
        if hinted:
            pool = hinted
    avoid = set(avoid or [])
    fresh = [s for s in pool if s["id"] not in avoid] or pool
    n = int(hashlib.sha256(f"{brand_key}:{key}".encode()).hexdigest()[:12], 16)
    return fresh[n % len(fresh)]


def render(spec, brand_key="marketdaily", style=None, size=SIZE_45, seed=None):
    """spec → PIL.Image。

    spec: {headline(必要), kicker?, body?, items?, stat?, stat_label?, left?, right?,
           left_label?, right_label?}
    """
    brand = BRANDS[brand_key]
    if style is None:
        style = assign(brand_key, spec.get("id") or spec["headline"], prefer=spec.get("prefer"),
                       photo_only=bool(spec.get("plate_path")))
    elif isinstance(style, str):
        style = next((s for s in brand.styles if s["id"] == style), brand.styles[0])
    # 安全區依品牌招牌的位置而定：MarketDaily 頂部有字標要讓開，命書只有右下朱印。
    style = dict(style)
    style.setdefault("_zone", (0.165, 0.875) if brand_key == "marketdaily" else (0.115, 0.845))
    pal = PALETTES[style["palette"]]
    rng = random.Random(seed if seed is not None
                        else int(hashlib.sha256((spec.get("id") or spec["headline"]).encode())
                                 .hexdigest()[:8], 16))
    bd = backdrops.REGISTRY[style["backdrop"]]
    if style["backdrop"] == "photo":
        src = (spec.get("plate_path") or style.get("photo")
               or pick_plate(brand_key, spec.get("topic") or style.get("topic"),
                             spec.get("id") or spec["headline"]))
        img = bd(size, pal, rng, src=src, strength=style.get("photo_strength", 0.62))
    else:
        img = bd(size, pal, rng)
    img = LAYOUTS[style["layout"]](img, spec, pal, style)
    img = chrome(img, brand, pal, spec)
    return img, style


def carousel(post_id, hook, bodies, cta_lines, brand_key="mingshu", size=SIZE_45,
             note=None, topic=None, plate_path=None):
    """一則貼文 → 整串輪播圖(封面 + 內文 × n + CTA)。

    風格在**貼文層級**指派：整串共用同一個色票與背景家族，所以一則貼文看起來是一件作品；
    下一則才換風格 —— 變化發生在時間軸上，不是在同一串裡。
    """
    # 現生的底圖只用在**封面**:內文卡是拿來讀的,一整串六張各配一張照片
    # 既貴(六倍 credit)又難讀,而且會讓一則貼文看起來像六個不同的人做的。
    st = assign(brand_key, post_id, photo_only=bool(plate_path))
    calm = dict(st, layout="body", backdrop=st.get("body_backdrop", "void"))
    out = []
    cover_img, _ = render({"id": post_id, "headline": hook, "kicker": BRANDS[brand_key].kicker,
                           "topic": topic, "plate_path": plate_path},
                          brand_key, style=st, size=size)
    out.append(("cover", cover_img))
    n = len(bodies)
    for i, text in enumerate(bodies, 1):
        img, _ = render({"id": f"{post_id}#b{i}", "headline": text, "page": i, "pages": n,
                         "note": note, "topic": topic}, brand_key, style=calm, size=size)
        out.append(("body", img))
    cta_style = dict(st, layout="cta")
    img, _ = render({"id": f"{post_id}#cta", "headline": cta_lines[0], "cta_lines": cta_lines,
                     "topic": topic}, brand_key, style=cta_style, size=size)
    out.append(("cta", img))
    return out
