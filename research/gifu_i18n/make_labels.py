import openpyxl, sys
L = [  # name, [(zh, en) per state]
 ("L_TITLE",      [("刀具列表", "Tool List")]),
 ("L_LANGBTN",    [("English", "English"), ("中文", "中文")]),
 ("L_PREWASH",    [("停用", "Disabled"), ("啟用", "Enabled")]),
 ("L_COL_LEN",    [("基準刀長", "Base Length")]),
 ("L_ALM_SPINDLE",[("主軸過熱", "Spindle overheat")]),
 ("L_ALM_AIR",    [("氣壓不足", "Low air pressure")]),
 ("L_NOLOGIN",    [("未登入", "Not logged in")]),
 ("L_HDR_TIME",   [("觸發時間", "Time")]),
 ("L_HDR_MSG",    [("警報訊息", "Message")]),
 ("L_CAPTION",    [("目前警報", "Active Alarms")]),
]
NL, NS = 8, max(len(s) for _, s in L)
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "標籤"
ws.append(["文字標籤名稱"] + [f"Language {l}, 狀態 {s}" for s in range(NS) for l in range(1, NL+1)])
for name, states in L:
    row = [name]
    for s in range(NS):
        zh, en = states[s] if s < len(states) else ("", "")
        row += [zh, en] + [""] * (NL - 2)
    ws.append(row)
wb.save(sys.argv[1])
