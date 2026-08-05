#!/bin/bash
# 一次性安裝:WSL「一個進程 OOM = 所有分頁陣亡」的連坐防線
# 用法:sudo bash ~/Delvin-agent/scripts/wsl_oom_install_guard.sh
#
# 背景見 scripts/wsl_oom_watch.sh 檔頭與 /etc/systemd/system/init.scope.d/oom-no-collateral.conf
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "❌ 需要 root:sudo bash $0"; exit 1; }

DIR=/etc/systemd/system/init.scope.d
mkdir -p "$DIR"
cat > "$DIR/oom-no-collateral.conf" <<'EOF'
# 2026-08-05 根因修復:WSL 全部 claude 分頁被一次殺光(當天第 4 次)
#
# 根因鏈:
#   單一 claude.exe 進程失控吃 11.9GB
#     ⚠️ claude.exe = Claude Code 自己的執行檔(npm @anthropic-ai/claude-code v2.1.222,
#        bin/claude.exe,289MB **ELF** 檔)。副檔名雖是 .exe 但它是 Linux 原生二進位,
#        與 Windows / WSL interop 完全無關。comm 差異:走 symlink 執行→"claude",
#        直接跑完整路徑→"claude.exe"。此機器跑 opus[1m](1M context),記憶體需求極大。
#   → WSL kernel global OOM(上限 15.6GB = 主機 31.2GB 的 50%,當時無 .wslconfig)
#   → OOM killer 送了 SIGKILL 但它沒真的死:四輪 OOM 都是同一個 PID 2290516、
#     rss 一模一樣(2967040 pages),記憶體從未釋放,所以每 ~2 分鐘就再 OOM 一次
#     (15:36:59 / 15:39:00 / 15:41:20 / 15:43:38,正好 4 次)。
#     ⚠️ 「為何 SIGKILL 殺不掉」未完全證實;卡在不可中斷(D)狀態是合理解釋,
#        同時段 dmesg 有 9P I/O 異常(Operation canceled @p9io.cpp:258)可佐證,但非定論。
#   → 它位在 init.scope 內(OOM log: task_memcg=/init.scope)
#   → systemd 預設 OOMPolicy=stop:cgroup 內任一進程被 OOM 殺掉 → 停掉整個單元
#   → init.scope 正是裝著所有互動 session 的地方,停止等 90s 逾時 → SIGKILL 全部分頁
#     (實測延遲 86-90s,恰好等於 TimeoutStopUSec=1min30s)
#
# OOMPolicy=continue 斷開最後一環:別的進程 OOM 死了,不要連坐殺掉整個 init.scope。
# 這不讓記憶體問題消失,但讓「一個失控進程 = 全部工作階段陣亡」不再成立。
[Scope]
OOMPolicy=continue
EOF

systemctl daemon-reload

policy=$(systemctl show init.scope -p OOMPolicy --value)
echo "--- 驗收 ---"
echo "init.scope OOMPolicy = $policy"
if [ "$policy" = "continue" ]; then
  echo "✅ 連坐防線已生效"
else
  echo "❌ 仍為 $policy,未生效 —— 請回報,不要當作已修好"
  exit 1
fi
