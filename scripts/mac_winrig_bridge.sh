#!/bin/bash
# mac_winrig_bridge —— 從 Mac 把一整段 bash 丟進 winrig 的 WSL 執行。
#
# ⚠️ 這支是【在 Mac 上跑】的,放在本 repo 只為了進版控不遺失(winrig 端不需要它)。
#    安裝:scp 到 Mac 或直接複製內容,`chmod +x ~/bin/wr`。
#
# 用途 = winrig MCP 掛掉時的備援腿。2026-08-30 實戰驗證:MCP server 被子工作 OOM 連坐
# 拖死後,client 端的 mcp__winrig__* 工具【不會自己恢復】(連 ToolSearch 都找不回),
# 但 SSH 這條腿獨立於 fastmcp / CF tunnel,完全可用。詳見 memory project_winrig_remote_mcp。
#
# 用法:
#   cat <<'EOF' | ~/bin/wr
#   cd ~/Delvin-agent && git status --short
#   EOF
#
# 為什麼是 stdin 而不是把指令塞進命令列:
#   v1 用 `ssh winrig "wsl -- bash -lc \"echo <base64>|base64 -d|bash\""`,長腳本會撞
#   Windows cmd 的 8191 字元上限,錯誤訊息是 Big5 亂碼的「命令列太長」,極難辨認。
#   改走 `bash -s` + stdin 就沒有長度限制,也不必處理任何跳脫。
#
# 已知行為:
#   · SSH 落地的是 Windows OpenSSH(不是 WSL),所以一定要 `wsl -d Ubuntu --` 包一層,
#     直接打 systemctl 會回「不是內部或外部命令」。
#   · 預設 cwd 是 /mnt/c/Users/USER(Windows 側)—— 每段自己 cd 或用絕對路徑。
#   · fresh boot 時 WSL 是關的,第一次呼叫會順便把它叫起來(server/tunnel 跟著起)。
set -u
ssh -o ConnectTimeout=15 winrig 'wsl -d Ubuntu -- bash -s' 2>&1
