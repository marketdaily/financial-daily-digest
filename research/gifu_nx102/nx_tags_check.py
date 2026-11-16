import re, sys

SUPPORTED = {"BOOL", "SINT", "BYTE", "USINT", "INT", "WORD", "UINT", "DINT", "UDINT", "DWORD",
             "REAL", "LINT", "ULINT", "LWORD", "LREAL", "STRING"}
ARRAY_OF = re.compile(r"^ARRAY\s*\[\s*(\d+)\s*\.\.\s*(\d+)\s*\]\s*OF\s+(\w+)$", re.I)


def main(src, dst):
    raw = open(src, "rb").read()
    try:
        text = raw.decode("cp950")
    except UnicodeDecodeError:
        text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    out, problems, n = [lines[0]], [], 0
    for i, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        cols = line.split("\t")
        name, dtype = cols[0], cols[1].strip()
        m = ARRAY_OF.match(dtype)
        if m:
            lo, hi, base = int(m.group(1)), int(m.group(2)), m.group(3).upper()
            if lo != 0:
                problems.append(f"line {i} {name}: array lower bound {lo} (Weintek requires 0)")
            dtype = f"{base}[{hi - lo + 1}]"
            cols[1] = dtype
        base = re.sub(r"\[.*", "", dtype).upper()
        if base.startswith("STRING") and "[" in dtype and not dtype.upper().startswith("STRING["):
            problems.append(f"line {i} {name}: string array not supported")
        if base.split("(")[0] not in SUPPORTED:
            problems.append(f"line {i} {name}: type {dtype} not supported (struct/enum? export members)")
        if len(cols) > 4 and cols[4].strip().upper() != "TRUE":
            problems.append(f"line {i} {name}: TAGLINK != TRUE")
        out.append("\t".join(cols))
        n += 1
    open(dst, "w", encoding="cp950", newline="").write("\r\n".join(out) + "\r\n")
    print(f"{n} tags -> {dst}")
    for p in problems:
        print("WARN", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
