#!/usr/bin/env python3
import pathlib
from playwright.sync_api import sync_playwright

BASE = pathlib.Path(__file__).resolve().parent
CSS = (BASE / "style.css").read_text(encoding="utf-8")
BODY = (BASE / "body.html").read_text(encoding="utf-8")
OUT = BASE / "金融進階聖經.pdf"

HTML = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>金融進階聖經</title><style>{CSS}</style></head><body>{BODY}</body></html>"""

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        pg = b.new_page()
        pg.set_content(HTML, wait_until="networkidle")
        pg.pdf(path=str(OUT), format="A4", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    print("PDF ->", OUT, OUT.stat().st_size, "bytes")

if __name__ == "__main__":
    main()
