"""新聞卡渲染。

版型結構參考對標帳號實際貼文拆解(2026-09-14 實看 @aipagedaily 封面):
上方約七成是圖 → 一條細分隔線 → 下方黑底 → 極粗壓縮體大標三到四行 → 底部一行小字。
那是社群新聞卡的通用編排慣例,好用的原因是:手機縮圖只看得到上半的圖與下半的大字。

⭐ 但有兩件他們做的我們**刻意不做**:
  ①他們把真人的臉合成進虛構場景(把某公司執行長合成成從直升機灑東西)——
    那是肖像權風險,而且跟「每個數字查得到出處」的定位直接衝突。
    我們的圖不放真人、不放商標(沿用 cardkit.vet_subject 的判準)。
  ②他們的卡片**從不標來源**。我們標 —— 那正是這個帳號唯一的差異點,
    把它放在卡片上而不是只放在文案裡,是因為圖會被轉走而文案不會。
視覺上也刻意分開:標題**左對齊**(他們置中)、來源標籤用品牌色。
"""
import json
import pathlib
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
BRAND = json.loads((ROOT / "brand.json").read_text())

W, H = 1080, 1350                 # 4:5,IG 直式版位
BAND = 0.34                       # 下方黑底佔比
INK = (14, 18, 18)
PAPER = (255, 255, 255)
ACCENT = (79, 181, 161)           # 品牌色(深色底上用亮版)
MUTED = (150, 163, 160)

FONTS = {
    "en": ["/home/userdelvin/.fonts/Anton-Regular.ttf",
           "/home/userdelvin/.fonts/Oswald-Bold.ttf",
           "/usr/share/fonts/truetype/lato/Lato-Heavy.ttf"],
    "zh": ["/home/userdelvin/.local/share/fonts/NotoSansCJKtc-Bold.otf",
           "/home/userdelvin/.local/share/fonts/NotoSansTC-VF.ttf"],
    "ui": ["/usr/share/fonts/truetype/lato/Lato-Heavy.ttf",
           "/home/userdelvin/.local/share/fonts/NotoSansCJKtc-Bold.otf"],
}


def _font(kind, size):
    for p in FONTS[kind]:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _is_cjk(s):
    return any("一" <= c <= "鿿" for c in s)


def _backdrop(path=None):
    """有現生圖就用,沒有就走程序化底 —— 發卡那條腿不准因為生圖掛掉而斷。"""
    top_h = H - int(H * BAND)
    if path and pathlib.Path(path).exists():
        try:
            im = Image.open(path).convert("RGB")
            r = max(W / im.width, top_h / im.height)
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
            x = (im.width - W) // 2
            y = (im.height - top_h) // 2
            return im.crop((x, y, x + W, y + top_h))
        except Exception:
            pass
    im = Image.new("RGB", (W, top_h), INK)
    d = ImageDraw.Draw(im)
    for i in range(top_h):                       # 垂直漸層,深到更深
        t = i / max(top_h - 1, 1)
        d.line([(0, i), (W, i)],
               fill=(int(18 + 26 * (1 - t)), int(26 + 34 * (1 - t)), int(26 + 32 * (1 - t))))
    for k in range(3):                           # 幾道斜向亮帶,避免死板
        x0 = int(W * (0.1 + 0.33 * k))
        d.polygon([(x0, 0), (x0 + 150, 0), (x0 - 220, top_h), (x0 - 370, top_h)],
                  fill=(int(24 + 8 * k), int(40 + 10 * k), int(38 + 9 * k)))
    return im.filter(ImageFilter.GaussianBlur(1.2))


def _fit_lines(draw, text, kind, box_w, max_lines, start, min_size=34):
    """由大往小找,直到塞得進指定行數。標題是卡片唯一要搶到的東西,寧可字大行少。"""
    text = text.strip()
    for size in range(start, min_size - 1, -2):
        f = _font(kind, size)
        avg = draw.textlength("字" if kind == "zh" else "M", font=f)
        per = max(int(box_w / max(avg * (1.0 if kind == "zh" else 0.62), 1)), 6)
        lines = (textwrap.wrap(text, width=per) if kind != "zh"
                 else [text[i:i + per] for i in range(0, len(text), per)])
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= box_w for l in lines):
            return f, lines, size
    f = _font(kind, min_size)
    return f, (textwrap.wrap(text, width=30)[:max_lines] if kind != "zh"
               else [text[i:i + 14] for i in range(0, len(text), 14)][:max_lines]), min_size


def render(headline, source, out_path, image_path=None, kicker=None, swipe=False):
    """headline=大標;source=出處(會印在卡上);kicker=題材線標籤。"""
    kind = "zh" if _is_cjk(headline) else "en"
    top_h = H - int(H * BAND)
    card = Image.new("RGB", (W, H), INK)
    card.paste(_backdrop(image_path), (0, 0))
    d = ImageDraw.Draw(card)

    # 圖與黑底交界:下緣先壓暗,避免圖太亮時和黑底斷得生硬
    # ⚠️ 交界要俐落。第一版用 220px 長漸層,結果圖和黑底糊成一片,
    # 「上圖下黑底」那個讓縮圖一眼看懂的結構整個消失了。改成短漸層只壓住圖的最下緣。
    fh = 130
    fade = Image.new("L", (W, fh), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(fh):
        fd.line([(0, i), (W, i)], fill=int(255 * (i / (fh - 1)) ** 2.2))
    card.paste(Image.new("RGB", (W, fh), INK), (0, top_h - fh), fade)

    pad = 62
    # 題材線標籤(左上),小而克制
    if kicker:
        kf = _font("ui", 26)
        tw = d.textlength(kicker.upper(), font=kf)
        d.rounded_rectangle([pad, pad, pad + tw + 34, pad + 48], 6, fill=ACCENT)
        d.text((pad + 17, pad + 10), kicker.upper(), font=kf, fill=INK)

    # 分隔線 + 品牌字標(置中壓在線上)
    ly = top_h
    wm = _font("ui", 24)
    name = BRAND["name"].upper()
    nw = d.textlength(name, font=wm)
    d.line([(pad, ly), (W / 2 - nw / 2 - 24, ly)], fill=(70, 82, 80), width=2)
    d.line([(W / 2 + nw / 2 + 24, ly), (W - pad, ly)], fill=(70, 82, 80), width=2)
    d.text((W / 2 - nw / 2, ly - 15), name, font=wm, fill=MUTED)

    # 大標:左對齊(對標帳號是置中,這裡刻意分開)
    box_w = W - pad * 2
    txt = headline if kind == "zh" else headline.upper()
    f, lines, size = _fit_lines(d, txt, kind, box_w, 4, 96 if kind == "en" else 74)
    lh = int(size * (1.02 if kind == "en" else 1.32))
    block = lh * len(lines)
    y = ly + 54 + max(0, (H - ly - 54 - 96 - block) // 2)
    for l in lines:
        d.text((pad, y), l, font=f, fill=PAPER)
        y += lh

    # 底行:來源印在卡上 —— 圖會被轉走,文案不會
    bf = _font("ui", 25)
    by = H - 62
    if source:
        lab = f"SOURCE · {source}".upper()
        d.text((pad, by), lab, font=bf, fill=ACCENT)
    tail = "SWIPE →" if swipe else f"@{BRAND['handle']}"
    d.text((W - pad - d.textlength(tail, font=bf), by), tail, font=bf, fill=MUTED)

    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out, "JPEG", quality=92)
    return str(out)


if __name__ == "__main__":
    import sys
    d = json.loads((ROOT / "drafts" / "2026-09-14.json").read_text())
    x = d[0]
    print(render(x["draft"]["headline"], x["source"], "/tmp/card_en.jpg", kicker=x["lane"]))
    print(render(x["draft"]["threads_chain"][0].split("\n")[0][:34], x["source"],
                 "/tmp/card_zh.jpg", kicker="科技"))
