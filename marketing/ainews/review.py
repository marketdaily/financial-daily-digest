"""把當天草稿渲染成一頁可讀的 HTML —— 老闆在手機上核稿用。

為什麼需要這個:草稿是 winrig 上的 JSON,老闆在手機上讀不到。
沒有這一層,「對外發布先給老闆看」這條規矩在實務上就會卡住整台機器 ——
規矩不是靠意志力執行的,是靠那件事夠不夠好做。

用法:python -m marketing.ainews.review [YYYY-MM-DD] > out.html
"""
import datetime
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BRAND = json.loads((ROOT / "brand.json").read_text())

FMT_LABEL = {"explainer": "新聞解釋文", "roundup": "24 小時彙整", "listicle": "存檔清單"}

CSS = """
:root{--pa:#F1F3F1;--cd:#FBFCFB;--ink:#14181A;--i2:#3D4A4B;--i3:#6B7A79;
--ru:#D3DAD8;--ru2:#E4E9E7;--ac:#0B6E5F;--acs:#DCEBE7;--wa:#8A4B07;--was:#F7E9D8}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--pa:#0E1212;--cd:#161B1B;
--ink:#E7EBE9;--i2:#B3BEBB;--i3:#7E8C89;--ru:#2A3332;--ru2:#212a29;--ac:#4FB5A1;--acs:#16302C;
--wa:#D79B4E;--was:#2E2416}}
:root[data-theme=dark]{--pa:#0E1212;--cd:#161B1B;--ink:#E7EBE9;--i2:#B3BEBB;--i3:#7E8C89;
--ru:#2A3332;--ru2:#212a29;--ac:#4FB5A1;--acs:#16302C;--wa:#D79B4E;--was:#2E2416}
*{box-sizing:border-box}
body{background:var(--pa);color:var(--ink);margin:0;padding-inline:18px;
font:16px/1.65 "Noto Sans TC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.w{max-width:740px;margin:0 auto;padding-block:32px 64px}
h1{font-size:26px;line-height:1.15;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--i2);margin:0 0 4px}
.hint{background:var(--acs);border-left:3px solid var(--ac);padding:12px 16px;margin-block:18px;
font-size:15px;color:var(--i2)}
.post{border:1px solid var(--ru);background:var(--cd);margin-block:22px}
.hd{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;justify-content:space-between;
padding:11px 16px;border-bottom:1px solid var(--ru);background:var(--pa);font-size:12px;color:var(--i3)}
.num{display:inline-block;background:var(--ink);color:var(--pa);font-weight:700;
padding:1px 9px;border-radius:2px;margin-right:8px;font-size:13px}
.hl{font-size:18px;font-weight:700;padding:16px 18px 0;line-height:1.3}
.blk{padding:14px 18px}
.lb{font-size:11px;letter-spacing:.1em;color:var(--ac);font-weight:700;margin-bottom:7px}
.tx{white-space:pre-wrap;font-size:15px;line-height:1.62}
.seg{border-left:2px solid var(--ru);padding:2px 0 2px 13px;margin-block:11px;white-space:pre-wrap;font-size:15px}
.seg:first-of-type{border-left-color:var(--ac)}
.src{padding:10px 18px;border-top:1px solid var(--ru2);font-size:13px;color:var(--i3);
word-break:break-all}
.src a{color:var(--ac)}
.none{background:var(--was);border-left:3px solid var(--wa);padding:14px 16px;color:var(--i2)}
"""


def render(date_str=None):
    date_str = date_str or datetime.date.today().isoformat()
    f = ROOT / "drafts" / f"{date_str}.json"
    items = json.loads(f.read_text()) if f.exists() else []
    e = html.escape
    out = [f"<title>{e(BRAND['name'])} 待審草稿 {date_str}</title>", f"<style>{CSS}</style>",
           '<div class="w">', f"<h1>{e(BRAND['name'])}｜{date_str} 待審草稿</h1>",
           f'<p class="sub">共 {len(items)} 則，一篇都還沒發出去。</p>',
           '<div class="hint">回我要發哪幾號就好，例如「1 3 發」或「全發」。'
           '沒被點到的不會發出去。任何一則要改，直接說哪裡不對。</div>']
    if not items:
        out.append('<div class="none">今天沒有通過閘門的草稿。'
                   '這可能是沒有夠格的新聞，也可能是驗證者把它們都擋下來了，'
                   '兩者的差別在 cron log 裡看得到。</div>')
    for i, it in enumerate(items, 1):
        d = it["draft"]
        fmt = FMT_LABEL.get(it.get("format", "explainer"), it.get("format", ""))
        src = it.get("source") or "無外部來源（原創清單）"
        out.append('<div class="post">')
        out.append(f'<div class="hd"><span>{e(fmt)}</span><span>來源：{e(str(src))}</span></div>')
        out.append(f'<div class="hl"><span class="num">{i}</span>{e(d.get("headline",""))}</div>')
        out.append('<div class="blk"><div class="lb">INSTAGRAM / FACEBOOK（英文）</div>'
                   f'<div class="tx">{e(d.get("caption",""))}</div></div>')
        chain = d.get("threads_chain") or []
        if chain:
            segs = "".join(f'<div class="seg">{e(s)}</div>' for s in chain)
            out.append(f'<div class="blk"><div class="lb">THREADS 串（繁體中文，{len(chain)} 則）'
                       f'</div>{segs}</div>')
        elif d.get("threads_caption"):
            out.append('<div class="blk"><div class="lb">THREADS（繁體中文）</div>'
                       f'<div class="tx">{e(d["threads_caption"])}</div></div>')
        u = it.get("source_url")
        out.append('<div class="src">' +
                   (f'出處：<a href="{e(u)}">{e(u)}</a>' if u else "出處：無（這則是原創清單，不引用外部來源）") +
                   "</div></div>")
    out.append("</div>")
    return "\n".join(out)


if __name__ == "__main__":
    print(render(sys.argv[1] if len(sys.argv) > 1 else None))
