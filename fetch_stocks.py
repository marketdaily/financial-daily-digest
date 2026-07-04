#!/usr/bin/env python3
"""
fetch_stocks.py — 從官方來源抓取「完整」股票宇宙,自動生成 docs/stocks.js
  美股:NASDAQ Trader 全清單 (NASDAQ + NYSE + AMEX/Arca/BATS) 普通股 + ETF + 特別股
  台股:TWSE ISIN 上市 + TPEx ISIN 上櫃 全股票 + 創新板 + ETF
資料以 type-to-search autocomplete 形式供 docs/preferences.html、docs/dashboard.html 使用。
"""
import re
import urllib.request
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "docs", "stocks.js")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_bytes(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── 美股:NASDAQ Trader 官方符號目錄 ──────────────────────────────────────────
US_JUNK_RE = re.compile(
    r"Warrant|\bRight\b|\bRights\b|\bUnit\b|\bUnits\b|When[\s-]?Issued|"
    r"Subscription|Test Stock|Test Common",
    re.I,
)
# 保留:純字母代號,或帶單一 .A/.B/.C 等股別字尾(例如 AGM.A)
US_SYM_RE = re.compile(r"^[A-Z]+(\.[A-Z])?$")


def clean_us_name(name):
    name = name.strip()
    # 去除常見贅字尾,讓搜尋結果乾淨
    for suf in (
        " - Common Stock", " Common Stock", " - Class A Common Stock",
        " - Ordinary Shares", " Ordinary Shares", " - Common Shares",
        " Common Shares", " - American Depositary Shares",
        " American Depositary Shares",
    ):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    return name.strip().rstrip(",").strip()


def parse_nasdaq_file(text, is_other):
    """is_other=True 解析 otherlisted.txt(NYSE/AMEX),否則 nasdaqlisted.txt"""
    out = []
    for ln in text.splitlines()[1:]:
        if ln.startswith("File Creation Time"):
            continue
        f = ln.split("|")
        if len(f) < 8:
            continue
        if is_other:
            sym, name, exch, cqs, etf, lot, test, ndq = f[:8]
        else:
            sym, name, mcat, test, fin, lot, etf, nxt = f[:8]
        if test == "Y":
            continue
        if not US_SYM_RE.match(sym):
            continue
        if US_JUNK_RE.search(name):
            continue
        # NASDAQ Trader 用 . 表示股別,報價/Worker 端慣用 -(例如 BRK-B)
        out_sym = sym.replace(".", "-")
        out.append((out_sym, clean_us_name(name)))
    return out


def fetch_us():
    print("  美股 NASDAQ Trader...", end=" ", flush=True)
    try:
        nd = fetch_bytes(
            "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
        ).decode("utf-8", "replace")
        ot = fetch_bytes(
            "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
        ).decode("utf-8", "replace")
        rows = parse_nasdaq_file(nd, False) + parse_nasdaq_file(ot, True)
        print(f"{len(rows)} 支")
        return rows
    except Exception as e:
        print(f"失敗: {e}")
        return []


# ── 台股:TWSE ISIN 服務(含 ETF / 創新板)──────────────────────────────────
TW_WANT = {"股票", "創新板", "ETF"}


def parse_isin(raw):
    text = raw.decode("ms950", "replace")
    rows = re.findall(r"<tr>(.*?)</tr>", text, re.DOTALL)
    cur = None
    out = []
    for r in rows:
        hm = re.match(r"\s*<td[^>]*colspan[^>]*>(.*?)</td>\s*$", r, re.DOTALL)
        if hm:
            cur = re.sub(r"<[^>]+>", "", hm.group(1)).strip()
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL)
        if len(tds) < 4:
            continue
        first = re.sub(r"<[^>]+>", "", tds[0]).strip()
        if cur in TW_WANT and "　" in first:
            code, name = first.split("　", 1)
            code, name = code.strip(), name.strip()
            if code and name:
                out.append((code, name))
    return out


def fetch_tw():
    result = {}
    for mode, label in [(2, "TWSE 上市"), (4, "TPEx 上櫃")]:
        print(f"  台股 {label}...", end=" ", flush=True)
        try:
            raw = fetch_bytes(
                f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            )
            rows = parse_isin(raw)
            for code, name in rows:
                result.setdefault(code, name)
            print(f"{len(rows)} 支")
        except Exception as e:
            print(f"失敗: {e}")
    return [(c, result[c]) for c in result]


# ── 輸出 ──────────────────────────────────────────────────────────────────────
def js_str(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def dedupe_sort(rows, numeric=False):
    seen = {}
    for sym, name in rows:
        if sym not in seen:
            seen[sym] = name
    items = list(seen.items())
    if numeric:
        items.sort(key=lambda x: (len(x[0]), x[0]))
    else:
        items.sort(key=lambda x: x[0])
    return items


def write_js(us, tw):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"// Auto-generated {now} by fetch_stocks.py — "
        f"{len(us)} US + {len(tw)} TW (完整股票宇宙)"
    ]
    lines.append("const US_STOCKS_FULL = [")
    for sym, name in us:
        lines.append(f'  ["{js_str(sym)}","{js_str(name)}"],')
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("];")
    lines.append("")
    lines.append("const TW_STOCKS_FULL = [")
    for code, name in tw:
        lines.append(f'  ["{js_str(code)}","{js_str(name)}"],')
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("];")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n✅ 寫入 {OUTPUT}")
    print(f"   美股:{len(us)} 支,台股:{len(tw)} 支")


if __name__ == "__main__":
    print("抓取完整股票宇宙...")
    us = dedupe_sort(fetch_us(), numeric=False)
    tw = dedupe_sort(fetch_tw(), numeric=True)
    if not us and not tw:
        print("❌ 所有來源都失敗,stocks.js 未更新")
        sys.exit(1)
    write_js(us, tw)
