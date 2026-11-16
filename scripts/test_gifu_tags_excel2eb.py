import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gifu_tags_excel2eb as g  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "research/gifu_nx102/NX102_GlobalVariables_CX-Designer_sample.txt")
SAMPLE_XLSX = os.path.join(ROOT, "research/gifu_nx102/客戶變數表_範例_16標籤.xlsx")


def golden_to_excel_rows():
    """把 #11 實際匯入成功的 txt 反向拆成客戶 Excel 的四欄;陣列交替用兩種寫法,兩條路徑都要測到。"""
    lines = open(GOLDEN, encoding="cp950").read().splitlines()[1:]
    rows = []
    for i, line in enumerate(lines):
        name, dtype, _, comment, *_ = line.split("\t")
        m = re.match(r"^(\w+)\[(\d+)\]$", dtype)
        if not m:
            rows.append([name, dtype, None, comment])
        elif i % 2:
            rows.append([name, m.group(1), int(m.group(2)), comment])
        else:
            rows.append([name, f"ARRAY[0..{int(m.group(2)) - 1}] OF {m.group(1)}", None, comment])
    return ["變數名稱", "資料型態", "陣列長度", "說明"], rows


def write_xlsx(path, header, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "變數表"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


class GoldenRoundTrip(unittest.TestCase):
    def test_excel_to_txt_matches_imported_file_byte_for_byte(self):
        header, rows = golden_to_excel_rows()
        self.assertEqual(len(rows), 16)
        with tempfile.TemporaryDirectory() as d:
            x, t = os.path.join(d, "in.xlsx"), os.path.join(d, "out.txt")
            write_xlsx(x, header, rows)
            self.assertEqual(g.main([x, t]), 0)
            self.assertEqual(open(t, "rb").read(), open(GOLDEN, "rb").read())

    def test_committed_sample_xlsx_matches(self):
        with tempfile.TemporaryDirectory() as d:
            t = os.path.join(d, "out.txt")
            self.assertEqual(g.main([SAMPLE_XLSX, t]), 0)
            self.assertEqual(open(t, "rb").read(), open(GOLDEN, "rb").read())

    def test_crlf_option(self):
        header, rows = golden_to_excel_rows()
        with tempfile.TemporaryDirectory() as d:
            x, t = os.path.join(d, "in.xlsx"), os.path.join(d, "out.txt")
            write_xlsx(x, header, rows)
            g.main([x, t, "--crlf"])
            self.assertEqual(open(t, "rb").read().replace(b"\r\n", b"\n"), open(GOLDEN, "rb").read())


class Rows(unittest.TestCase):
    def conv(self, *a):
        return g.convert_row(*a)

    def test_scalar(self):
        self.assertEqual(self.conv("A", "uint", "", "x")[0], ["A", "UINT", "", "x", "TRUE", "RW", ""])

    def test_length_column(self):
        cols, p = self.conv("A", "LREAL", "42", "")
        self.assertEqual((cols[1], p), ("LREAL[42]", []))

    def test_array_of_is_rewritten(self):
        cols, p = self.conv("A", "ARRAY[0..41] OF BOOL", "", "")
        self.assertEqual((cols[1], p), ("BOOL[42]", []))

    def test_array_lower_bound_nonzero(self):
        self.assertTrue(any("從 1 開始" in x for x in self.conv("A", "ARRAY[1..42] OF BOOL", "", "")[1]))

    def test_length_mismatch(self):
        self.assertTrue(any("不一致" in x for x in self.conv("A", "ARRAY[0..41] OF BOOL", "40", "")[1]))

    def test_length_one_or_zero_is_scalar(self):
        for L in ("0", "1", "-"):
            self.assertEqual(self.conv("A", "INT", L, "")[0][1], "INT")

    def test_string_len_is_not_array(self):
        cols, p = self.conv("S", "STRING[20]", "", "")
        self.assertEqual((cols[1], p), ("STRING[20]", []))

    def test_string_array_rejected(self):
        self.assertTrue(self.conv("S", "STRING", "5", "")[1])

    def test_struct_rejected(self):
        self.assertTrue(any("不支援" in x for x in self.conv("A", "sToolData", "", "")[1]))

    def test_bad_name(self):
        self.assertTrue(self.conv("1ABC", "INT", "", "")[1])
        self.assertTrue(self.conv("刀號", "INT", "", "")[1])

    def test_bad_length(self):
        self.assertTrue(self.conv("A", "INT", "abc", "")[1])

    def test_simplified_chinese_comment_flagged(self):
        self.assertTrue(any("cp950" in x for x in self.conv("A", "INT", "", "刀具长度")[1]))

    def test_tab_in_comment_flattened(self):
        self.assertEqual(self.conv("A", "INT", "", "a\tb\nc")[0][3], "a b c")


class Build(unittest.TestCase):
    def test_duplicate_and_blank_rows(self):
        lines, p = g.build(["變數名稱", "資料型態"], [["A", "INT"], [None, None], ["a", "INT"]])
        self.assertEqual(len(lines), 3)
        self.assertTrue(any("重複" in x and "第 4 列" in x for x in p))

    def test_header_any_order_and_english(self):
        lines, p = g.build(["Comment", "Data Type", "Name", "Array Length"], [["c", "REAL", "W", 3]])
        self.assertEqual((lines[1], p), ("W\tREAL[3]\t\tc\tTRUE\tRW\t", []))

    def test_missing_column(self):
        with self.assertRaises(g.TagError):
            g.build(["變數名稱", "說明"], [])

    def test_errors_block_output(self):
        with tempfile.TemporaryDirectory() as d:
            x, t = os.path.join(d, "in.xlsx"), os.path.join(d, "out.txt")
            write_xlsx(x, ["變數名稱", "資料型態"], [["A", "sStruct"]])
            self.assertEqual(g.main([x, t]), 1)
            self.assertFalse(os.path.exists(t))


if __name__ == "__main__":
    unittest.main()
