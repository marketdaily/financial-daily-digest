#!/usr/bin/env python3
"""cardkit 底層：品牌色票、字體、CJK 排版。

為什麼要這一層(2026-08-24 老闆令「why is everything the same?」)：
    MarketDaily 的 social_cards.py 是**一個**寫死的 SVG 版面，命書的 card_theme.py 是
    **一張**龍首照片 + 金框。兩邊各自都只有一種長相，所以整個 IG 九宮格滑下來像同一張圖
    重複貼了九次。修法不是「再手刻第二個模板」——那只是把 1 變成 2，下個月又會被問一樣的
    問題。正解是把「版面／背景／色票／字體」拆成四個可獨立換的維度，由 styles.py 組合成
    一份**策展過的**風格清單，發文時輪替。

⚠️ 這裡刻意不引入任何外部渲染器(rsvg-convert 沒裝、Playwright 要開 Chrome)：
    純 PIL 兩個 repo 的 venv 都有(各自 12.3.0)，命書那條腿不會因為缺套件整個斷掉。
"""
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path.home() / ".local/share/fonts"
SANS = FONT_DIR / "NotoSansTC-VF.ttf"
SERIF = FONT_DIR / "NotoSerifTC-VF.ttf"

_FONT_CACHE = {}


def font(size, weight=700, family="sans"):
    """可變字重字體。weight 是 Noto VF 的 wght 軸(100–900)。"""
    key = (family, int(size), int(weight))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = SERIF if family == "serif" else SANS
    f = ImageFont.truetype(str(path), int(size))
    try:
        f.set_variation_by_axes([int(weight)])
    except Exception:
        pass
    _FONT_CACHE[key] = f
    return f


class Palette:
    """一組配色。所有風格都必須深底 —— marketing/CLAUDE.md「封面不可白底」是硬規則。"""

    def __init__(self, key, bg, surface, ink, body, accent, accent2, seal=None, family="sans"):
        self.key = key
        self.bg = bg
        self.surface = surface
        self.ink = ink
        self.body = body
        self.accent = accent
        self.accent2 = accent2
        self.seal = seal or accent
        self.family = family

    def luminance(self):
        r, g, b = self.bg
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255


# ── MarketDaily ──────────────────────────────────────────────────────────────
# 起點是 social_cards.py 現行色(#0A0A08 底 / #FFB000 琥珀 / #4AF626 終端綠)，
# 其餘幾組是把同一個「深色終端機」語言換色相，不是另立品牌。
MD_PALETTES = [
    Palette("amber",  (10, 10, 8),   (18, 17, 13),  (245, 230, 200), (170, 160, 140), (255, 176, 0),   (74, 246, 38)),
    Palette("ice",    (7, 11, 18),   (13, 19, 30),  (226, 238, 250), (140, 158, 180), (86, 180, 255),  (150, 240, 255)),
    Palette("violet", (12, 8, 20),   (20, 14, 32),  (238, 232, 252), (156, 146, 180), (167, 120, 255), (86, 220, 255)),
    Palette("green",  (6, 14, 10),   (11, 22, 16),  (226, 246, 232), (136, 166, 146), (74, 246, 38),   (255, 176, 0)),
    Palette("ember",  (16, 8, 8),    (26, 14, 13),  (250, 232, 226), (176, 148, 140), (255, 96, 72),   (255, 176, 0)),
    Palette("slate",  (11, 11, 13),  (19, 20, 23),  (238, 240, 244), (150, 155, 164), (198, 168, 120), (255, 176, 0), family="serif"),
]

# ── 命書 mingshu.tw ──────────────────────────────────────────────────────────
# 主色票直接取自官網 web/css/direction-tianji.css :root（黑 #0c0a07 / 古銅金 #c9a35c /
# 朱砂 #a63d2a）。其餘是同一套東方語言的相鄰色相；朱砂在官網 token 裡只准用於印記，
# 所以 seal 欄位獨立留著，不當文字色。
MS_PALETTES = [
    Palette("moxin",  (12, 10, 7),   (20, 17, 12),  (244, 236, 218), (168, 152, 119), (201, 163, 92),  (210, 171, 96),  seal=(166, 61, 42), family="serif"),
    Palette("zhusha", (18, 9, 8),    (28, 15, 12),  (247, 233, 222), (176, 140, 124), (198, 96, 72),   (201, 163, 92),  seal=(166, 61, 42), family="serif"),
    Palette("qingyu", (7, 14, 14),   (12, 22, 22),  (230, 244, 240), (134, 164, 158), (110, 190, 170), (201, 163, 92),  seal=(166, 61, 42), family="serif"),
    Palette("xuanshui", (8, 10, 20), (13, 17, 32),  (232, 236, 250), (140, 150, 180), (140, 160, 240), (201, 163, 92),  seal=(166, 61, 42), family="serif"),
    Palette("cangmu", (10, 13, 9),   (17, 21, 15),  (238, 240, 226), (152, 162, 132), (168, 190, 110), (201, 163, 92),  seal=(166, 61, 42), family="serif"),
]

PALETTES = {p.key: p for p in MD_PALETTES + MS_PALETTES}


# ── CJK 排版 ────────────────────────────────────────────────────────────────
CJK_PUNCT = "，。！？；：、"
# 行尾不該停的虛詞、行首不該起的字。中文沒有詞界，硬切常落在虛詞上，一眼看得出是機器排的。
TAIL_BAN = set("不也就都很還是的了最沒有和與而但在把被讓給對從向為以之及其能會要可想去來做將連")
HEAD_BAN = set("的了呢嗎吧啊而且但是所以然後就是。，、；：！？」』）")


def segment(text):
    """切成不該被拆開的語塊；jieba 有就用真斷詞，沒有退回逐字(醜一點但不會產不出圖)。"""
    try:
        import jieba
        words = [w for w in jieba.cut(text) if w]
    except Exception:
        words = list(text)
    chunks = []
    for w in words:
        if w and w[0] in CJK_PUNCT and chunks:
            chunks[-1] += w
        else:
            chunks.append(w)
    return chunks


def _width(text, f):
    return f.getbbox(text)[2] - f.getbbox(text)[0] if text else 0


def wrap_px(text, f, max_w):
    """按像素寬斷行（語塊優先）。中英混排時按字數斷會亂，一定要量像素。

    ⚠️ 文字裡的 `\n` 是**作者指定的硬斷行**，必須先切開再各自斷行。
       首版沒做這件事：`\n` 被 jieba 當成一個普通語塊、量到的寬度≈0，於是兩段文字被
       接成同一行、再由 PIL 疊著畫出來 —— 對照表上每一張卡的主標都是糊的。
       (2026-08-24 第一版風格對照表抓到)
    """
    out = []
    for seg_text in str(text).split("\n"):
        if not seg_text.strip():
            continue
        out.extend(_wrap_one(seg_text, f, max_w))
    return out or [""]


def _wrap_one(text, f, max_w):
    lines, cur = [], ""
    for c in segment(text):
        while _width(c, f) > max_w:                      # 語塊自己就過長(長網址) → 硬切
            take = ""
            for ch in c:
                if _width(cur + take + ch, f) > max_w:
                    break
                take += ch
            if not take:
                take = c[0]
            lines.append(cur + take)
            c = c[len(take):]
            cur = ""
        if _width(cur + c, f) <= max_w:
            cur += c
        else:
            if cur:
                lines.append(cur)
            cur = c
    if cur:
        lines.append(cur)
    return lines


def penalty(lines):
    """一種排法有多難看。分數越低越好，絕對值沒有意義，只用於比較。"""
    p = 0.0
    for i, ln in enumerate(lines):
        if not ln:
            continue
        if i < len(lines) - 1 and ln[-1] in TAIL_BAN:
            p += 3
        if i > 0 and ln[0] in HEAD_BAN:
            p += 3
    if len(lines) > 1 and len(lines[-1]) <= 2:
        p += 4                                           # 孤字行
    return p


def fit(text, max_w, max_h, sizes, family="sans", weight=700, leading=1.28):
    """在候選字級裡挑排得下且最好看的那一種 → (font, lines, line_h)。

    ⚠️ max_h 是**硬約束不是扣分**：排不進去不是「比較醜」，是字跑到框外被裁掉。
       每一級都排不下時退回最小級並截行(寧可少一行也不要疊出去)。
    """
    best = None
    for size in sizes:
        f = font(size, weight, family)
        lines = wrap_px(text, f, max_w)
        line_h = int(size * leading)
        if len(lines) * line_h > max_h:
            continue
        score = penalty(lines) - size * 0.06
        if best is None or score < best[0]:
            best = (score, f, lines, line_h)
    if best is None:
        size = sizes[-1]
        f = font(size, weight, family)
        line_h = int(size * leading)
        lines = wrap_px(text, f, max_w)[: max(1, max_h // line_h)]
        return f, lines, line_h
    return best[1], best[2], best[3]


def draw_lines(d, lines, x, y, f, line_h, fill, align="left", box_w=0):
    for ln in lines:
        if align == "center":
            w = _width(ln, f)
            d.text((x + (box_w - w) / 2, y), ln, font=f, fill=fill)
        elif align == "right":
            w = _width(ln, f)
            d.text((x + box_w - w, y), ln, font=f, fill=fill)
        else:
            d.text((x, y), ln, font=f, fill=fill)
        y += line_h
    return y


def text_center(d, text, cx, y, f, fill):
    w = _width(text, f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)
    return w
