#!/usr/bin/env python3
"""
公版日報存檔頁(docs/output/digest_*.html)的 SEO 骨架後製(2026-09-03,總體檢 §2.2):

1. `<h1>`:存檔頁原本沒有任何 H1(email 版面只有品牌字與日期)。插在 `<div class="header">`
   區塊的最末,文字=<title> 主句(`台股日報 2026-09-01｜特斯拉、聯發科、輝達`),
   純 inline style,不動 email 版面。
2. 頁尾互連:插在 `<div class="footer">` 開頭——「← 前一份 / 下一份 →」「同日另一版
   (台股早報 ⇄ 美股晚報)」「全部日報存檔 /archive/」「投資學堂 /blog/」。
   只連**磁碟上真的存在**的檔案,絕不猜日期。
3. 標題主句與個股名抽取放在本模組(`page_title` / `extract_stock_names`),
   `site_structured_data.py` 的 <title>/og:title/JSON-LD headline 也從這裡拿,
   兩支腳本對同一頁永遠算出同一句。

## 邊界(與 archive_cta.py 同一套解耦模式)
- 只後製「已寫出的靜態檔案」docs/output/,不碰 main.py::render_email_shell。
- `*_personal_*` 一律跳過。
- 注入區塊包在具名 marker 之間;每次執行先剝掉舊區塊再重算,結果相同就不寫檔(冪等)。
  marker 半毀 → fail-loud exit 3,不靜默。
- 錨點位置刻意選在 header 區塊**內部**與 footer 區塊**內部**:archive_cta 的兩個區塊
  分別插在 header **之前**與 footer **之前**,兩支腳本不論先後順序跑、跑幾次,
  彼此的相對位置都不變(否則第二輪 diff 非空=假冪等)。

用法:
  python scripts/archive_nav.py --dry     # 預覽
  python scripts/archive_nav.py           # 真寫入(冪等)
exit code: 0=全部成功 / 3=有檔案找不到錨點或 marker 半毀(已寫入其他檔,需告警)
"""
import argparse
import fcntl
import os
import re
import sys
from datetime import date as _date
from html import escape as _esc, unescape as _unesc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_OUTPUT = ROOT / "docs" / "output"
LOCK_PATH = ROOT / "logs" / "locks" / "archive_nav.lock"
TMP_DIR = ROOT / "logs" / "tmp"
BASE = "https://marketdaily.ai"

MARKER_START = "<!-- archive_nav:start -->"
MARKER_END = "<!-- archive_nav:end -->"
_BLOCK_RE = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n*", re.S)
_MARKER_TOKEN_RE = re.compile(re.escape(MARKER_START) + "|" + re.escape(MARKER_END))
_FNAME_RE = re.compile(r"^digest_(\d{4}-\d{2}-\d{2})(_us)?\.html$")
_CJK_RE = re.compile(r"[㐀-鿿]")
_TAG_RE = re.compile(r"<[^>]+>")
_SIGNAL_TICKER_OPEN = '<span class="signal-ticker">'
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans TC','PingFang TC',sans-serif"
_WEEKDAY = "一二三四五六日"


def edition_label(is_us: bool) -> str:
    return "美股晚報" if is_us else "台股日報"


def parse_filename(name: str):
    m = _FNAME_RE.match(name)
    if not m:
        return None
    return m.group(1), bool(m.group(2))


def _balanced_inner(html: str, open_idx: int, tag: str) -> tuple:
    """從 open_idx(某個 <tag ...> 的起點)找到對應的 </tag>,回 (inner_start, close_idx)。
    找不到回 (-1, -1)。用 token 計數而非 HTML parser:存檔頁是 email 級的規整 div/span。"""
    open_re = re.compile(rf"<{tag}\b[^>]*>|</{tag}>")
    depth = 0
    inner_start = -1
    for m in open_re.finditer(html, open_idx):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return inner_start, m.start()
        else:
            depth += 1
            if depth == 1:
                inner_start = m.end()
    return -1, -1


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", _unesc(_TAG_RE.sub(" ", s))).strip()


def extract_stock_names(html: str, limit: int = 3) -> list:
    """依內文順序抽前 N 支個股的中文名(零捏造:只從 signal-ticker 卡片名稱欄拿)。

    卡片格式 `<span class="signal-ticker"><span ...>特斯拉 Tesla</span><span ...>TSLA</span></span>`
    → 取第一個內層 span 的文字,再取其中第一個含 CJK 的詞(「特斯拉 Tesla」→「特斯拉」);
    整段沒有 CJK 就用第一個詞(例如純英文名)。舊版(2026-05,stock-card/.ticker)沒有名稱欄
    → 回空清單,標題退回不帶個股的版本。"""
    names = []
    pos = 0
    while len(names) < limit:
        i = html.find(_SIGNAL_TICKER_OPEN, pos)
        if i < 0:
            break
        inner_start, close = _balanced_inner(html, i, "span")
        if close < 0:
            break
        pos = close
        inner = html[inner_start:close]
        first_span = re.search(r"<span\b[^>]*>(.*?)</span>", inner, re.S)
        text = _clean_text(first_span.group(1) if first_span else inner)
        toks = text.split()
        cjk = [t for t in toks if _CJK_RE.search(t)]
        name = cjk[0] if cjk else (toks[0] if toks else "")
        if name and name not in names:
            names.append(name)
    return names


def headline(date: str, is_us: bool, names: list) -> str:
    """<h1> 主句(不帶品牌)。"""
    base = f"{edition_label(is_us)} {date}"
    return f"{base}｜{'、'.join(names)}" if names else base


def page_title(date: str, is_us: bool, names: list) -> str:
    return f"{headline(date, is_us, names)} — MarketDaily"


def strip_existing_block(html: str) -> str:
    return _BLOCK_RE.sub("", html)


def marker_defect(html: str):
    toks = _MARKER_TOKEN_RE.findall(html)
    if len(toks) % 2:
        return "marker_orphan"
    for i in range(0, len(toks), 2):
        if toks[i] != MARKER_START or toks[i + 1] != MARKER_END:
            return "marker_unpaired"
    return None


def _wrap(block: str) -> str:
    return MARKER_START + "\n" + block + "\n" + MARKER_END + "\n"


def _url(date: str, is_us: bool) -> str:
    return f"{BASE}/output/digest_{date}{'_us' if is_us else ''}"


def _short(date: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return f"{m:02d}-{d:02d}(週{_WEEKDAY[_date(y, m, d).weekday()]})"


def neighbours(date: str, is_us: bool, existing: set):
    """同一版次(台股/美股各自一條時間軸)的前一份/下一份 + 同日另一版。只回磁碟上存在的。"""
    same = sorted(d for d, u in existing if u == is_us)
    prev_d = next_d = None
    for d in same:
        if d < date:
            prev_d = d
        elif d > date:
            next_d = d
            break
    other = (date, not is_us) in existing
    return prev_d, next_d, other


def _h1_block(text: str) -> str:
    return (f'<h1 style="font-size:16px;font-weight:800;color:#1d1d1f;line-height:1.45;'
            f'margin:12px 0 0;letter-spacing:-0.2px;font-family:{_FONT};">{_esc(text)}</h1>')


def _nav_block(date: str, is_us: bool, existing: set) -> str:
    prev_d, next_d, other = neighbours(date, is_us, existing)
    ed = edition_label(is_us)
    a = 'style="color:#6366f1;text-decoration:none;font-weight:700;"'
    sep = " &nbsp;·&nbsp; "
    row1 = []
    if prev_d:
        row1.append(f'<a href="{_url(prev_d, is_us)}" {a} rel="prev">← {_short(prev_d)} {ed}</a>')
    if other:
        row1.append(f'<a href="{_url(date, not is_us)}" {a}>同日{edition_label(not is_us)} ↗</a>')
    if next_d:
        row1.append(f'<a href="{_url(next_d, is_us)}" {a} rel="next">{_short(next_d)} {ed} →</a>')
    row2 = [f'<a href="{BASE}/archive/" {a}>📚 全部日報存檔</a>',
            f'<a href="{BASE}/blog/" {a}>📖 投資學堂</a>']
    lines = (sep.join(row1) + "<br>" if row1 else "") + sep.join(row2)
    return (f'<nav aria-label="日報存檔導覽" style="margin:0 0 10px;padding:0 0 10px;'
            f'border-bottom:1px solid #e5e5ea;font-size:12px;line-height:2;font-family:{_FONT};">'
            f'{lines}</nav>')


def inject(html: str, date: str, is_us: bool, existing: set):
    """回傳 (new_html, reason)。reason=None 代表成功。"""
    defect = marker_defect(html)
    if defect:
        return None, defect
    clean = strip_existing_block(html)
    i_header = clean.find('<div class="header">')
    if i_header < 0:
        return None, "no_header_anchor"
    _, header_close = _balanced_inner(clean, i_header, "div")
    if header_close < 0:
        return None, "header_unbalanced"
    i_footer = clean.rfind('<div class="footer">')
    if i_footer < 0 or i_footer < i_header:
        return None, "no_footer_anchor"
    footer_inner_start = i_footer + len('<div class="footer">')

    names = extract_stock_names(clean)
    # 已有 <h1> 的頁(2026-05 舊版、週六週報特別版)不再加第二個:H1 一頁一個
    has_h1 = "<h1" in clean
    h1 = "" if has_h1 else _wrap(_h1_block(headline(date, is_us, names)))
    nav = _wrap(_nav_block(date, is_us, existing))
    # 先插後面的(footer),再插前面的(header),前面的索引才不會位移。
    # 區塊自帶結尾換行、不另加前導換行:strip 只剝 marker 到其後一個換行,多加的字元會每輪累積(假冪等)。
    out = clean[:footer_inner_start] + nav + clean[footer_inner_start:]
    if h1:
        out = out[:header_close] + h1 + out[header_close:]
    n_blocks = 1 if has_h1 else 2
    if (out.count(MARKER_START) != n_blocks or out.count(MARKER_END) != n_blocks
            or out.count("<h1") != 1):
        return None, "marker_postcondition"
    return out, None


def archive_files(directory=None):
    d = Path(directory) if directory else DOCS_OUTPUT
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("digest_*.html")
                  if "_personal_" not in p.name and _FNAME_RE.match(p.name))


def existing_set(files) -> set:
    return {parse_filename(p.name) for p in files}


def atomic_write(path: Path, text: str) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TMP_DIR / f"{path.name}.{os.getpid()}.nav.tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        path.write_text(text, encoding="utf-8")


def run(dry: bool = False, verbose: bool = True, directory=None):
    files = archive_files(directory)
    existing = existing_set(files)
    changed, skipped, unchanged = [], [], 0
    for path in files:
        date, is_us = parse_filename(path.name)
        try:
            html = path.read_text(encoding="utf-8")
            out, reason = inject(html, date, is_us, existing)
            if reason:
                skipped.append((path.name, reason))
                continue
            if out == html:
                unchanged += 1
                continue
            if not dry:
                atomic_write(path, out)
        except (OSError, UnicodeDecodeError) as e:
            skipped.append((path.name, f"io_error:{e.__class__.__name__}"))
            continue
        changed.append(path.name)
    if verbose:
        print(f"archive_nav: {'DRY ' if dry else ''}changed={len(changed)} "
              f"unchanged={unchanged} skipped={len(skipped)}")
        for name in changed[:5]:
            print(f"  + {name}")
        if len(changed) > 5:
            print(f"  + ...({len(changed) - 5} more)")
        for name, reason in skipped:
            print(f"  ! SKIPPED {name}: {reason}")
    return changed, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("archive_nav: 另一個實例正在執行,本次讓路")
            return 0
        _, skipped = run(dry=args.dry)
    return 3 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
