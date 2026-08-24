#!/usr/bin/env python3
"""風格對照表 —— 把一個品牌的全部風格排成一張圖，人眼一次看完。

用法: python3 -m cardkit.preview marketdaily [out.png]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import styles
from .theme import font

DEMO = {
    "marketdaily": [
        {"id": "d1", "kicker": "訊號 vs 雜訊", "headline": "上千條新聞\n跟你有關的只有五條",
         "body": "設定持股，AI 每天只挑那幾條，中文寫給你看",
         "items": ["只留跟你持股有關的", "假消息先被濾掉", "30 秒讀完"],
         "stat": "30秒", "stat_label": "讀完一份財經早報",
         "left": "看完 80 則快訊還是不知道要幹嘛", "right": "只給消化過的重點",
         "left_label": "沒有 MarketDaily", "right_label": "有 MarketDaily"},
    ],
    "mingshu": [
        {"id": "m1", "kicker": "節氣", "headline": "星座在交界那天出生的人\n要看的是時刻",
         "body": "今年秋分那一秒太陽才進天秤，之前出生的還是處女",
         "items": ["先查真實節氣", "再定月柱", "最後才排時柱"],
         "stat": "08:05", "stat_label": "今年秋分交界的那一分鐘",
         "left": "GPT 用農曆月份排八字", "right": "命書查真實節氣界線",
         "left_label": "ChatGPT", "right_label": "命書"},
    ],
}


def sheet(brand_key, out_path, cols=5, thumb_w=380):
    demo = DEMO[brand_key][0]
    items = styles.BRANDS[brand_key].styles
    th = int(thumb_w * 1350 / 1080)
    rows = (len(items) + cols - 1) // cols
    pad, label_h = 22, 46
    W = cols * thumb_w + (cols + 1) * pad
    H = rows * (th + label_h) + (rows + 1) * pad
    sheet_img = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet_img)
    for i, st in enumerate(items):
        im, _ = styles.render(demo, brand_key, style=st["id"])
        im = im.resize((thumb_w, th), Image.LANCZOS)
        r, c = divmod(i, cols)
        x = pad + c * (thumb_w + pad)
        y = pad + r * (th + label_h + pad)
        sheet_img.paste(im, (x, y))
        d.text((x + 4, y + th + 10), f"{i+1:02d}  {st['id']}  ({st['layout']}/{st['backdrop']}/{st['palette']})",
               font=font(20, 600), fill=(210, 210, 215))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet_img.save(out_path)
    return out_path


if __name__ == "__main__":
    brand = sys.argv[1] if len(sys.argv) > 1 else "marketdaily"
    out = sys.argv[2] if len(sys.argv) > 2 else f"/tmp/{brand}_styles.png"
    print(sheet(brand, out))
