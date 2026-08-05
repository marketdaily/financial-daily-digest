#!/bin/bash
# 把 Delvin 在 Windows Chrome 的登入狀態,種進 Claude 的代理瀏覽器(agent_browser.py)。
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

echo "[$(date +%T)] 等 Chrome 完全關閉(最多 6 分鐘)..."
for i in $(seq 1 180); do
  n=$("$TASKLIST" /FI "IMAGENAME eq chrome.exe" /NH 2>/dev/null | grep -ci "chrome.exe" || true)
  [ "$n" -eq 0 ] && { echo "[$(date +%T)] 已關閉(等了 $((i*2)) 秒)"; break; }
  sleep 2
done
n=$("$TASKLIST" /FI "IMAGENAME eq chrome.exe" /NH 2>/dev/null | grep -ci "chrome.exe" || true)
[ "$n" -ne 0 ] && { echo "TIMEOUT: Chrome 仍在執行,未動任何東西"; exit 2; }

rm -rf "$DST" 2>/dev/null; mkdir -p "$DST/Default/Network"
cp "$SRC/Local State" "$DST/Local State" || { echo "FAIL: Local State"; exit 3; }
cp "$SRC/Default/Network/Cookies" "$DST/Default/Network/Cookies" || { echo "FAIL: cookie DB 仍被鎖"; exit 3; }
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
