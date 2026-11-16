"""Clone EB event-log export row 2 as template; emit one row per (LB addr, label) → .xls importable by EB 事件登錄→匯入."""
import sys, xlrd, xlwt
src, dst = sys.argv[1], sys.argv[2]
ALARMS = [(6410, "L_ALM_SPINDLE", "主軸過熱"), (6411, "L_ALM_AIR", "氣壓不足")]
s = xlrd.open_workbook(src).sheet_by_index(0)
hdr, tpl = s.row_values(1), s.row_values(2)
col = {h: i for i, h in reversed(list(enumerate(hdr)))}  # first occurrence wins
wb = xlwt.Workbook(encoding="utf-8"); ws = wb.add_sheet(s.name)
for c, v in enumerate(s.row_values(0)): ws.write(0, c, v)
for c, v in enumerate(hdr): ws.write(1, c, v)
for r, (addr, lbl, text) in enumerate(ALARMS, start=2):
    row = list(tpl)
    row[col["位址 (讀取位址)"]] = str(addr)
    row[col["內容"]] = text
    row[col["標籤名稱"]] = lbl
    row[col["位址 (觸發條件)"]] = str(addr)
    for c, v in enumerate(row): ws.write(r, c, v)
wb.save(dst)
