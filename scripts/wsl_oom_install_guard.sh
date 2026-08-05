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
#   某進程失控吃 11.9GB(當次是 claude.exe,經 WSL interop 拉起的 Windows 端進程)
#   → WSL kernel global OOM(上限 15.6GB = 主機 31.2GB 的 50%,當時無 .wslconfig)
#   → OOM killer 選中它卻殺不死(真身在 Windows 側,Linux 只有代理殼)→ 記憶體不釋放
#   → 每 ~2 分鐘再 OOM 一次(15:36:59 / 15:39:00 / 15:41:20 / 15:43:38,正好 4 次)
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
