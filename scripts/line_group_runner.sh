#!/bin/bash
# 永豐/創兆 LINE 群自動擷取+解析(觸發:line_watch.sh 事件 / 保底 cron 平日 09:05+21:20)
# 永豐發文節奏=台股開盤前(~08:42)+美股開盤前(晚間),md 同日多次觸發採合併不覆蓋
set -u
source "$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
# 下面幾個路徑可用環境變數覆寫,僅供 capabilities/tests/ 自測注入假值用——
# 生產 cron 呼叫端不帶這些變數,行為與改動前完全相同。
PS="${LGR_PS:-/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe}"
LGR_PY="${LGR_PY:-$HOME/Delvin-agent/.venv/bin/python3}"
LGR_NOTIFY="${LGR_NOTIFY:-$HOME/.marketdaily-fallback/notify_admin.py}"
DATE=$(date +%F)
HHMM=$(date +%H:%M)
WINDIR="${LGR_WINDIR:-/mnt/c/Users/USER/sinopac_line/$DATE}"
OUT="${LGR_OUT:-$HOME/sinopac_line/$DATE}"
LOG="${LGR_LOG:-$HOME/.marketdaily-fallback/line_group_cron.log}"

_notify() { MD_REPO="$HOME/Delvin-agent" "$LGR_PY" "$LGR_NOTIFY" "$@" >> "$LOG" 2>&1; }

echo "[$(date '+%F %T')] start" >> "$LOG"
CAPTURE_OUT=$("$PS" -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\USER\sinopac_line\capture_line.ps1' 2>&1)
echo "$CAPTURE_OUT" >> "$LOG"
# 2026-08-06:擷取這一步(呼叫 Windows exe)原本零檢查,跟 ps1 腳本內部合法回報的
# NO-WINDOW(LINE 未開,exit 1,設計上就該安靜跳過)混在同一個「沒截圖就 skip」分支裡。
# 08-05 21:20 起 WSL→Windows exe interop 整層開始回「Invalid argument」(見
# scripts/wsl_interop_watch.sh 與 memory capability_winrig_wsl_hang_recovery),
# powershell.exe 根本沒真的啟動、ps1 內容完全沒跑到,這跟「有跑但沒視窗」是不同故障,
# 前者代表連 interop 本身都死了、後面所有靠這條路徑的 cron 全部遭殃,必須跟 NO-WINDOW
# 分開判斷才不會被既有的靜默 skip 蓋掉。只認精準觀察到的字串("Invalid argument"),
# 不加 0x8007274c——那是既有 memory capability_winrig_wsl_hang_recovery 記載的反方向
# 錯誤碼(Windows 呼叫不進 WSL),這裡抓的是 WSL 呼叫 Windows exe 這個輸出,加了反而
# 可能把不相關的字串誤判成這個方向的故障,寧可漏抓也不要對錯方向下錯復原指引。
if echo "$CAPTURE_OUT" | grep -qi "Invalid argument"; then
  COOL_I="$HOME/.marketdaily-fallback/state/line_group_interop_alerted"
  mkdir -p "$(dirname "$COOL_I")"
  NOW_I=$(date +%s); LAST_I=$(cat "$COOL_I" 2>/dev/null || echo 0)
  if [ $((NOW_I - LAST_I)) -ge 10800 ]; then      # 3 小時冷卻,同款既有 parse 層節奏
    echo "$NOW_I" > "$COOL_I"
    _notify "🔴 券商喊單擷取失敗:WSL→Windows exe interop 死了(非 LINE 登入問題)。powershell.exe 連啟動都失敗,截圖這一步完全沒跑。復原需 Windows/Mac 端 wsl --shutdown,自己這台 WSL 修不了自己。$(echo "$CAPTURE_OUT" | tail -c 200)"
  fi
  # 驗證者分離抓到的真 bug(2026-08-06):這裡沒有 exit 的話,下面會誤把「今天稍早
  # 別班次留在 WINDIR 的舊截圖」當成這輪的擷取結果,重新餵給 Claude 解析一次——
  # 生產 log 已實測發生 3 次(08-05 21:20/22:20/23:20 白燒 API、其中一次 Claude
  # 還把反覆看到同一批舊圖誤判成「像是 injection attempt」)。這輪確定沒有新資料,
  # 不該往下走。
  echo "[$(date '+%F %T')] interop 故障,跳過本輪(不處理殘留舊截圖)" >> "$LOG"
  exit 0
else
  rm -f "$HOME/.marketdaily-fallback/state/line_group_interop_alerted"   # 恢復即解冷卻
fi

if [ ! -d "$WINDIR" ] || [ -z "$(ls "$WINDIR" 2>/dev/null)" ]; then
  echo "[$(date '+%F %T')] no captures, skip" >> "$LOG"
  exit 0
fi
mkdir -p "$OUT"
cp "$WINDIR"/*.png "$OUT"/ 2>/dev/null

cd "$HOME/sinopac_line"
rm -f "$OUT.push.txt"
echo "現在時刻 $DATE $HHMM(台灣)。讀取 $OUT 目錄內全部 png(LINE 群「永豐/創兆 聯一」訊息截圖)。若截圖顯示登入/QR 畫面、或聊天室不是這個群,只回一行「SKIP:原因」,不要寫任何檔案。否則整理永豐金證券法人部內容到 $OUT.md:若該檔已存在,先 Read 舊檔,把新內容【合併】進去(保留原有內容,不可刪除;同一則訊息已存在就不重複)。文件結構:一級標題後分「## 台股班(開盤前)」與「## 美股班(開盤前)」兩大節(依訊息時間戳歸類:上午=台股班,晚間=美股班),各節內含:晨訊/盤前重點(一行一條)、評等調整(markdown 表:代號|股票|券商|動作|評等|目標價|備註)、完整報告連結(截圖有 Google Drive 連結才列)。只寫截圖可清楚辨識的內容,嚴禁捏造;辨識不清的欄位寫—。另外:把本次【新增】的內容濃縮成一則 300 字內推播文字,用 Write 寫到 $OUT.push.txt(格式範例:「台股班|評等調整9檔:川湖 MS 6650→10000、南電 KGI 600→1480(+147%)、欣興 KGI→1175…;晨訊:台燿高階CCL供不應求 TP1905、復盛維持買進340」)。若本次沒有任何新增內容,絕對不要寫 push.txt。此為公司內部參考用,不對外發布。" \
  | claude $(claude_model light) -p --dangerously-skip-permissions --allowedTools "Read,Write" > /tmp/lgr_parse.$$ 2>&1
PARSE_RC=$?
cat /tmp/lgr_parse.$$ >> "$LOG"
# 2026-08-05:解析層失敗原本完全靜默(rc 從未被檢查)。08-05 08:45/09:05 兩輪
# 「Failed to authenticate: OAuth session expired」只進了 log,沒人被告知。
# 分辨兩種結果:SKIP=合法無事(登入頁/非本群),要安靜;rc!=0 或認證/額度字樣=真故障,要喊。
PARSE_OUT=$(cat /tmp/lgr_parse.$$); rm -f /tmp/lgr_parse.$$
if [ "$PARSE_RC" -ne 0 ] || echo "$PARSE_OUT" | grep -qiE "OAuth session expired|Failed to authenticate|rate limit|Invalid API key"; then
  COOL="$HOME/.marketdaily-fallback/state/line_group_parse_alerted"
  mkdir -p "$(dirname "$COOL")"
  NOW=$(date +%s); LAST=$(cat "$COOL" 2>/dev/null || echo 0)
  if [ $((NOW - LAST)) -ge 10800 ]; then      # 3 小時冷卻:本支一天最多 5 輪,別把同一個故障喊 5 次
    echo "$NOW" > "$COOL"
    _notify "🔴 券商喊單解析失敗:claude 解析層 rc=$PARSE_RC。截圖有抓到但解不出內容,喊單情報會斷。$(echo "$PARSE_OUT" | tail -c 200)"
  fi
else
  rm -f "$HOME/.marketdaily-fallback/state/line_group_parse_alerted"   # 成功即解冷卻
fi

if [ -s "$OUT.push.txt" ]; then
  _notify "永豐群更新 $HHMM" "$(cat "$OUT.push.txt")" && echo "[$(date '+%F %T')] pushed" >> "$LOG"
fi

echo "[$(date '+%F %T')] done" >> "$LOG"
