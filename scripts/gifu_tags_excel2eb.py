"""客戶 Excel 變數表 → Weintek EasyBuilder Pro 可匯入的 OMRON NJ/NX 標籤 txt(CX-Designer 格式)。

Excel 欄位(第一列為表頭,欄序不拘,依名稱比對):變數名稱 / 資料型態 / 陣列長度 / 說明
輸出格式與 2026-11-16 spike #11 實際匯入成功的檔案相同:
  cp950、Tab 分隔、表頭 HOST NAME/DATATYPE/ADDRESS/COMMENT/TAGLINK/RW/POU、陣列寫 `T[N]`。
EB 對 `ARRAY[0..N] OF T` 會顯示「成功匯入」卻安靜略過該行,所以一律轉成 `T[N+1]`。

用法: python scripts/gifu_tags_excel2eb.py 客戶變數表.xlsx 輸出.txt [--crlf] [--sheet 名稱]
"""
import argparse
import re
import sys

HEADER = ["HOST NAME", "DATATYPE", "ADDRESS", "COMMENT", "TAGLINK", "RW", "POU"]
SUPPORTED = {"BOOL", "SINT", "BYTE", "USINT", "INT", "WORD", "UINT", "DINT", "UDINT", "DWORD",
             "REAL", "LINT", "ULINT", "LWORD", "LREAL", "STRING"}
COLS = {
    "name": ("變數名稱", "變數名", "name", "variable"),
    "type": ("資料型態", "資料類型", "型態", "data type", "datatype", "type"),
    "len": ("陣列長度", "長度", "array length", "length"),
    "comment": ("說明", "註解", "備註", "comment", "description"),
}
ARRAY_OF = re.compile(r"^ARRAY\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*OF\s+(\w+(?:\[\d+\])?)$", re.I)
BRACKET = re.compile(r"^(\w+)\s*\[\s*(\d+)\s*\]$")
STRING_LEN = re.compile(r"^STRING\s*\[\s*(\d+)\s*\]$", re.I)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TagError(ValueError):
    pass


def _norm(h):
    return re.sub(r"\s+", " ", str(h or "")).strip().lower()


def map_header(header):
    idx = {}
    normed = [_norm(h) for h in header]
    for key, names in COLS.items():
        for n in names:
            if n.lower() in normed:
                idx[key] = normed.index(n.lower())
                break
    missing = [COLS[k][0] for k in ("name", "type") if k not in idx]
    if missing:
        raise TagError(f"Excel 缺少欄位: {', '.join(missing)}(表頭={header})")
    return idx


def _cell(row, idx, key):
    i = idx.get(key)
    if i is None or i >= len(row) or row[i] is None:
        return ""
    v = row[i]
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def convert_row(name, dtype, length, comment):
    """回傳 (txt 一行的欄位 list, 問題清單)。問題非空時呼叫端決定是否中止。"""
    problems = []
    if not IDENT.match(name):
        problems.append(f"{name!r}: 變數名稱含非法字元(只允許英數與底線,且不可數字開頭)")
    t = re.sub(r"\s+", " ", dtype).strip()
    n = None
    m = ARRAY_OF.match(t)
    if m:
        lo, hi, t = int(m.group(1)), int(m.group(2)), m.group(3)
        if lo != 0:
            problems.append(f"{name}: 陣列下標從 {lo} 開始,Weintek 只支援從 0 開始")
        n = hi - lo + 1
    elif BRACKET.match(t) and not STRING_LEN.match(t):
        b = BRACKET.match(t)
        t, n = b.group(1), int(b.group(2))
    t = t.upper()
    if length not in ("", "0", "1", "-"):
        if not length.isdigit():
            problems.append(f"{name}: 陣列長度 {length!r} 不是正整數")
        else:
            L = int(length)
            if n is not None and n != L:
                problems.append(f"{name}: 資料型態寫 {n} 個元素,陣列長度欄寫 {L},不一致")
            n = L
    base = re.sub(r"\[.*", "", t)
    if base not in SUPPORTED:
        problems.append(f"{name}: 型別 {dtype!r} 不支援(結構/列舉請改匯出成員變數)")
    if base == "STRING" and n:
        problems.append(f"{name}: STRING 陣列 EB 不支援")
    if "\t" in comment or "\n" in comment:
        comment = re.sub(r"\s+", " ", comment)
    try:
        comment.encode("cp950")
    except UnicodeEncodeError:
        problems.append(f"{name}: 說明含 cp950 無法表示的字(簡體/罕用字),EB 匯入會亂碼")
    out_type = f"{t}[{n}]" if n else t
    return [name, out_type, "", comment, "TRUE", "RW", ""], problems


def read_excel(path, sheet=None):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    while rows and not any(c not in (None, "") for c in rows[0]):
        rows.pop(0)
    if not rows:
        raise TagError("Excel 是空的")
    return rows[0], rows[1:]


def build(header, rows):
    idx = map_header(header)
    lines, problems, seen = ["\t".join(HEADER)], [], set()
    for r_no, row in enumerate(rows, 2):
        name = _cell(row, idx, "name")
        if not name:
            continue
        cols, probs = convert_row(name, _cell(row, idx, "type"), _cell(row, idx, "len"),
                                  _cell(row, idx, "comment"))
        if name.upper() in seen:
            probs.append(f"{name}: 變數名稱重複")
        seen.add(name.upper())
        problems += [f"Excel 第 {r_no} 列 {p}" for p in probs]
        lines.append("\t".join(cols))
    return lines, problems


def write_txt(lines, dst, crlf=False):
    nl = "\r\n" if crlf else "\n"
    with open(dst, "w", encoding="cp950", newline="") as f:
        f.write(nl.join(lines) + nl)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("xlsx")
    ap.add_argument("txt")
    ap.add_argument("--sheet")
    ap.add_argument("--crlf", action="store_true", help="Windows 換行(LF/CRLF 兩種都實測可匯入)")
    a = ap.parse_args(argv)
    header, rows = read_excel(a.xlsx, a.sheet)
    lines, problems = build(header, rows)
    for p in problems:
        print("ERROR", p, file=sys.stderr)
    if problems:
        print(f"有 {len(problems)} 個問題,未輸出。修正 Excel 後重跑。", file=sys.stderr)
        return 1
    write_txt(lines, a.txt, a.crlf)
    print(f"{len(lines) - 1} tags -> {a.txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
