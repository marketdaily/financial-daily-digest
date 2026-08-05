#!/bin/bash
# 把 Delvin 在 Windows Chrome 的登入狀態,種進 Claude 的代理瀏覽器(agent_browser.py)。
#
# ⚠️⚠️ 2026-08-05 實測:這條路對「現代 Chrome + FB/IG」**行不通,別再試**。兩層防盜:
#   ① Chrome 136+ 禁止在預設 user-data-dir 開 --remote-debugging-port(專防偷 cookie)
#      → 用真 profile 開 headless,CDP 根本不 listen。
#   ② cookie 是 v20 App-Bound 加密,金鑰綁原 profile 路徑 → 複製 profile 到別的目錄再開,
#      解出來是 0 筆(TOTAL=0)。
#   兩層合起來 = 「背景把既有登入偷出來」被 Chrome 設計性擋死。
#   → 要種登入請改用 agent_browser_login.py:在代理瀏覽器裡**互動登入一次**(Chrome 認可的路)。
#   本檔僅對「舊版 Chrome / v10 cookie / 非 FB-IG 的站」可能還有用,保留備查。
#
# 何時要跑:代理瀏覽器對某站顯示「⛔ 未登入」時(session 過期、或第一次接一個新平台)。
# 頻率:不高。FB/IG 的 session 動輒數月,種一次可以用很久 —— 這正是本工具存在的目的:
#       把「每次都要 Delvin 手動點」變成「偶爾種一次」。
#
# ⚠️ 前提:Delvin 必須先**完全關閉 Chrome**。執行中的 Chrome 會鎖住 cookie DB,
#         Windows 與 WSL 兩側都複製不出來(實測 Permission denied)。本腳本會等它關。
# ⚠️ 隱私:cookie DB 是全站共用一份,但**只有指定網域會被種進代理瀏覽器**,
#         中繼檔用完立即刪除。不指定網域就不要跑。
#
# 用法: ./seed_agent_browser.sh facebook.com instagram.com threads.net
set -u
[ $# -eq 0 ] && { echo "用法: $0 <網域> [網域...]   例:$0 facebook.com instagram.com"; exit 1; }
DOMAINS="$*"

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
TASKLIST="/mnt/c/Windows/System32/tasklist.exe"
PS="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
SRC="/mnt/c/Users/USER/AppData/Local/Google/Chrome/User Data"
DST_WIN='C:\Users\USER\AppData\Local\Temp\cc-fb-profile'
DST="/mnt/c/Users/USER/AppData/Local/Temp/cc-fb-profile"
trap 'rm -rf "$WORK"' EXIT

# 判準是「cookie 檔真的複製得出來」,不是「chrome.exe 數量歸零」——
# 後者只是前者的代理指標,而且會說謊:Chrome 常留背景 process(背景應用程式設定、
# crashpad、別的 headless 實例),數量不為零但檔案早就沒被鎖了。2026-08-05 就是
# 卡在這個假條件上乾等到逾時,而那時檔案其實已經可以複製。
echo "[$(date +%T)] 等 cookie DB 可複製(=Chrome 放開鎖;最多 6 分鐘)..."
rm -rf "$DST" 2>/dev/null; mkdir -p "$DST/Default/Network"
OK=0
for i in $(seq 1 180); do
  if cp "$SRC/Default/Network/Cookies" "$DST/Default/Network/Cookies" 2>/dev/null; then
    OK=1; echo "[$(date +%T)] 拿到了(等了 $((i*2)) 秒)"; break
  fi
  [ $((i % 15)) -eq 0 ] && echo "[$(date +%T)] 仍被鎖住,請確認 Chrome 完全關閉(含背景常駐)"
  sleep 2
done
[ "$OK" -ne 1 ] && { echo "TIMEOUT: cookie DB 始終被鎖,未動任何東西"; exit 2; }
cp "$SRC/Local State" "$DST/Local State" || { echo "FAIL: Local State"; exit 3; }
cp "$SRC/Default/Preferences" "$DST/Default/Preferences" 2>/dev/null
SIZE=$(stat -c%s "$DST/Default/Network/Cookies")
# 空的 cookie DB 約 20KB —— 大小過小代表複製失敗、Chrome 又自建了一份空的,
# 不擋下來的話後面會拿到一個「成功但沒有任何登入」的假綠。
[ "$SIZE" -lt 100000 ] && { echo "FAIL: cookie DB 只有 ${SIZE} bytes,顯然不是真的那份"; exit 3; }
echo "[$(date +%T)] cookie DB 已複製 ${SIZE} bytes"

# cookie 值是 App-Bound 加密的,只有 Chrome 自己解得開 → 用同一支 chrome.exe 開副本來解。
cat > "$WORK/dump.ps1" <<'PS1'
param([string]$Out = "$env:TEMP\cc-cookies.json", [int]$Port = 9222)
$ErrorActionPreference = "Stop"
$v = Invoke-RestMethod "http://127.0.0.1:$Port/json/version"
$ws = New-Object System.Net.WebSockets.ClientWebSocket
$ws.ConnectAsync([Uri]$v.webSocketDebuggerUrl, [Threading.CancellationToken]::None).Wait()
$bytes = [Text.Encoding]::UTF8.GetBytes('{"id":1,"method":"Network.getAllCookies"}')
$ws.SendAsync([ArraySegment[byte]]::new($bytes), 1, $true, [Threading.CancellationToken]::None).Wait()
$buf = New-Object byte[] 131072; $sb = New-Object Text.StringBuilder
do {
  $r = $ws.ReceiveAsync([ArraySegment[byte]]::new($buf), [Threading.CancellationToken]::None); $r.Wait()
  [void]$sb.Append([Text.Encoding]::UTF8.GetString($buf, 0, $r.Result.Count))
} while (-not $r.Result.EndOfMessage)
[IO.File]::WriteAllText($Out, $sb.ToString(), [Text.UTF8Encoding]::new($false))
$o = $sb.ToString() | ConvertFrom-Json
Write-Output "TOTAL=$($o.result.cookies.Count)"
PS1
cp "$WORK/dump.ps1" "/mnt/c/Users/USER/AppData/Local/Temp/cc-dump.ps1"

echo "[$(date +%T)] 背景無視窗啟動 Chrome 副本(絕不開視窗、不搶焦點)..."
"$PS" -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -WindowStyle Hidden -ArgumentList @('--headless=new','--remote-debugging-port=9222','--user-data-dir=$DST_WIN','--no-first-run','--no-default-browser-check','--disable-gpu','about:blank')" >/dev/null 2>&1
for i in $(seq 1 25); do
  /mnt/c/Windows/System32/curl.exe -s --max-time 2 http://127.0.0.1:9222/json/version >/dev/null 2>&1 && break
  sleep 1
done

echo "[$(date +%T)] 透過 CDP 取出 cookie..."
"$PS" -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\USER\AppData\Local\Temp\cc-dump.ps1' 2>&1 | tail -1
cp "/mnt/c/Users/USER/AppData/Local/Temp/cc-cookies.json" "$WORK/cookies.json" || { echo "FAIL: 取不到 cookie JSON"; exit 4; }

echo "[$(date +%T)] 收拾 Windows 側(關副本、刪 profile 與中繼檔)..."
"$PS" -NoProfile -Command "
Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { \$_.CommandLine -like '*cc-fb-profile*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }
Start-Sleep -Seconds 2
Remove-Item -Recurse -Force '$DST_WIN' -ErrorAction SilentlyContinue
Remove-Item -Force \"\$env:TEMP\cc-cookies.json\",\"\$env:TEMP\cc-dump.ps1\" -ErrorAction SilentlyContinue" >/dev/null 2>&1
echo "[$(date +%T)] ✅ Windows 側乾淨了 —— Chrome 可以重開"

echo "[$(date +%T)] 種進代理瀏覽器(只限:$DOMAINS)"
python3 "$HERE/agent_browser.py" import "$WORK/cookies.json" $DOMAINS
