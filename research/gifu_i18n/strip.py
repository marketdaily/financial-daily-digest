import sys
from PIL import Image, ImageDraw, ImageFont
# usage: strip.py out.png crop(x0,y0,x1,y1) img1 "cap1" img2 "cap2" ...
out, crop, rest = sys.argv[1], tuple(map(int, sys.argv[2].split(','))), sys.argv[3:]
pairs = list(zip(rest[::2], rest[1::2]))
f = ImageFont.truetype("/home/userdelvin/.local/share/fonts/NotoSansCJKtc-Regular.otf", 26)
ims = [Image.open(p).crop(crop) for p, _ in pairs]
W, H = ims[0].size; cols = 2; rows = (len(ims) + 1) // 2
o = Image.new("RGB", (W * cols, (H + 40) * rows), "white"); d = ImageDraw.Draw(o)
for i, (im, (_, c)) in enumerate(zip(ims, pairs)):
    x, y = (i % cols) * W, (i // cols) * (H + 40)
    d.text((x + 10, y + 3), c, fill="black", font=f); o.paste(im, (x, y + 40))
o.save(out)
