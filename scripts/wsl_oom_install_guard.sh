#!/bin/bash
# 一次性安裝:WSL「一個進程 OOM = 所有分頁陣亡」的連坐防線
# 用法:sudo bash ~/Delvin-agent/scripts/wsl_oom_install_guard.sh
#
# 背景見 scripts/wsl_oom_watch.sh 檔頭與 /etc/systemd/system/init.scope.d/oom-no-collateral.conf
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "❌ 需要 root:sudo bash $0"; exit 1; }

UNITS_FILE="$(dirname "$0")/wsl_oom_units.txt"
[ -f "$UNITS_FILE" ] || { echo "❌ 找不到清單 $UNITS_FILE"; exit 1; }

# 共用根因說明（寫進每份 drop-in 的檔頭，讓十個月後打開檔案的人看得懂為什麼有這行）
read -r -d '' RATIONALE <<'RAT' || true
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
#
# ⚠️ 2026-08-30 復發:同一機制在 winrig-remote-server.service 上原封不動再演一次——
#   run_claude 派出的子 Claude(node)寄生在該 unit 的 cgroup,吃到 7.7GB/10.2GB 觸發
#   global OOM,systemd 依 OOMPolicy=stop 把【整個 unit】判 Failed(result=oom-kill),
#   MCP server 本體陪葬 → CF tunnel 502 → 遠端控制中斷,且 client 端 MCP 不會自己恢復。
#   根因不是「並發打掛」(那是我當時的錯誤歸因),是 OOM 連坐漏保護第二個 cgroup。
#   受保護清單已抽成 wsl_oom_units.txt,新增 unit 只改那一處。
RAT

fail=0
while IFS='|' read -r unit section reason; do
  case "$unit" in ''|\#*) continue ;; esac
  DIR="/etc/systemd/system/${unit}.d"
  mkdir -p "$DIR"
  {
    printf '%s\n' "$RATIONALE"
    printf '#\n# 本 drop-in 保護:%s\n# 理由:%s\n' "$unit" "$reason"
    printf '[%s]\nOOMPolicy=continue\n' "$section"
  } > "$DIR/oom-no-collateral.conf"
  echo "  裝上 $DIR/oom-no-collateral.conf"
done < "$UNITS_FILE"

systemctl daemon-reload

echo "--- 驗收 ---"
while IFS='|' read -r unit section reason; do
  case "$unit" in ''|\#*) continue ;; esac
  policy=$(systemctl show "$unit" -p OOMPolicy --value 2>/dev/null)
  if [ "$policy" = "continue" ]; then
    echo "✅ $unit OOMPolicy=continue"
  else
    echo "❌ $unit OOMPolicy=${policy:-未知} —— 未生效,不要當作已修好"
    fail=1
  fi
done < "$UNITS_FILE"

[ "$fail" -eq 0 ] || exit 1
echo "✅ 連坐防線已在全部 $(grep -cv '^#\|^$' "$UNITS_FILE") 個 cgroup 生效"
