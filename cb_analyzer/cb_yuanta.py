"""元大證券 CBAS 選擇權報價表 → 報價帳本。

許乃方(Andrea Hsu, 元大金融交易部)每週寄「CB資產交換選擇權報價表」,信件本文內嵌
「下周拆解標的」表:可承作起日/名稱/代號/擔保/TCRI/百元報價/折現率/選擇權到期日/
賣回日/年期/賣回價/轉換價/轉換價值/CB市價/溢折價/參考單價/發行張數/波動度(21D)。
= 我們實際下單那一端的真實報價。吃進 .yuanta_quotes.json 後:
  - cb.py 單檔分析自動套用該檔的 百元報價(premium_quote)+折現率(asset_swap_spread),
    標示「元大報價單 日期」;CLI --premium/--interest 明示輸入仍優先。
  - 元大版轉換價 vs 系統轉換價 差異 >0.5% → 警示(權威交叉源,搭配 cb_conv_watch)。

  python3 cb_yuanta.py --ingest <file>   解析信件內容檔(get_thread JSON 或原始 HTML)入帳本
  python3 cb_yuanta.py --list            列出帳本內報價
  python3 cb_yuanta.py 52892             查單一債券報價
注意:Gmail MCP 抓不到附件但本文表格就夠;全自動化(cron 收信)需設 Gmail 應用程式密碼後改走 IMAP。"""
import os
import re
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, ".yuanta_quotes.json")

HEADER_KEY = "百元報價"


def _load():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _date(s):
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", str(s or "").strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def parse_quote_table(html, quote_date=None):
    """信件 HTML → [{bond_code, name, premium_pct, discount_rate_pct, ...}]。
    以含「百元報價」表頭的 <table> 為錨;cell 抽文字後按欄位順序對位。"""
    tables = re.findall(r"<table[^>]*>.*?</table>", html, re.S | re.I)
    target = next((t for t in tables if HEADER_KEY in t), None)
    if not target:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", target, re.S | re.I):
        cells = [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c)).replace("&nbsp;", "")
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        cells = [c for c in cells if c != ""]
        if len(cells) < 17 or HEADER_KEY in "".join(cells):
            continue
        # 欄序:起日 名稱 代號 擔保 TCRI 百元報價 折現率 選擇權到期 賣回日 年期 賣回價 轉換價 轉換價值 CB市價 溢折價 參考單價 發行張數 波動度
        # 名稱可能被拆(KY 尾綴),用「代號=4~6位數字」定位後前後對齊
        ci = next((i for i, c in enumerate(cells) if re.fullmatch(r"\d{4,6}", c)), None)
        if ci is None or ci < 1:
            continue
        c = cells
        row = {
            "start_date": c[0],
            "name": "".join(c[1:ci]),
            "bond_code": c[ci],
            "collateral": c[ci + 1],
            "tcri": int(c[ci + 2]) if c[ci + 2].isdigit() else None,
            "premium_pct": _num(c[ci + 3]),          # 百元報價(權利金/per100)
            "discount_rate_pct": _num(c[ci + 4]),    # 折現率=拆解利息%/年
            "opt_expiry": _date(c[ci + 5]),          # 選擇權到期日(=賣回日-14日曆日)
            "put_date": _date(c[ci + 6]),
            "tenor_year": _num(c[ci + 7]),
            "put_price": _num(c[ci + 8]),
            "conv_price": _num(c[ci + 9]),           # 元大版轉換價(權威交叉源)
            "parity": _num(c[ci + 10]),
            "cb_price": _num(c[ci + 11]),
            "premium_discount_pct": _num(c[ci + 12]),
            "unit_price_nt": _num(c[ci + 13]),
            "issue_lots": _num(c[ci + 14]),
            "vol_21d_pct": _num(c[ci + 15]) if len(c) > ci + 15 else None,
            "quote_date": quote_date,
        }
        if row["premium_pct"] is not None and row["bond_code"]:
            out.append(row)
    return out


def ingest_html(html, quote_date=None, verbose=False):
    """單一信件 HTML 字串 → 入帳本(同債券較新報價日才覆蓋)。回入帳筆數。IMAP/檔案共用。"""
    quote_date = quote_date or datetime.date.today().isoformat()
    ledger = _load()
    n = 0
    for row in parse_quote_table(html, quote_date):
        prev = ledger.get(row["bond_code"])
        if prev and (prev.get("quote_date") or "") > quote_date:
            continue
        ledger[row["bond_code"]] = row
        n += 1
    if n:
        _save(ledger)
    if verbose and n:
        print(f"  元大報價入帳 {n} 筆(報價日 {quote_date})")
    return n


def subject_quote_date(subj, fallback=None):
    """主旨「…報價表_2026/7/6」→ 2026-07-06。"""
    dm = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", subj or "")
    return (f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
            if dm else fallback)


def ingest(path):
    """path = Gmail get_thread 存檔(JSON)或原始 HTML/txt。解析→入帳本(同債券新日期覆蓋)。"""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    bodies = []
    quote_date = None
    try:
        j = json.loads(raw)
        for m in j.get("messages", []):
            bodies.append(m.get("htmlBody") or m.get("plaintextBody") or "")
            quote_date = subject_quote_date(m.get("subject"),
                                            str(m.get("date") or "")[:10] or None)
    except ValueError:
        bodies = [raw]
    quote_date = quote_date or datetime.date.today().isoformat()
    n = sum(ingest_html(b, quote_date) for b in bodies)
    ledger = _load()
    print(f"已入帳 {n} 筆元大報價(帳本共 {len(ledger)} 檔,報價日 {quote_date})")
    for b, r in sorted(ledger.items()):
        if r.get("quote_date") == quote_date:
            print(f"  {r['name']}({b}) 百元報價 {r['premium_pct']}% · 折現率 {r['discount_rate_pct']}%"
                  f" · 轉換價 {r['conv_price']} · CB市價 {r['cb_price']}")
    return n


def get_quote(bond_code, max_age_days=14):
    """單檔最新元大報價;超過 max_age_days 視為過期回 None(報價每週更新,舊價不能拿來下單)。"""
    r = _load().get(str(bond_code).strip())
    if not r:
        return None
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(r["quote_date"])).days
    except (ValueError, KeyError, TypeError):
        return None
    return {**r, "age_days": age} if age <= max_age_days else None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--ingest":
        ingest(args[1])
        return
    if args[0] == "--list":
        for b, r in sorted(_load().items()):
            print(f"{r.get('quote_date')} {r['name']}({b}) 百元報價 {r['premium_pct']}%"
                  f" 折現率 {r['discount_rate_pct']}% 轉換價 {r['conv_price']}")
        return
    r = get_quote(args[0]) or _load().get(args[0])
    print(json.dumps(r, ensure_ascii=False, indent=1) if r else f"{args[0]}:帳本無報價")


if __name__ == "__main__":
    main()
