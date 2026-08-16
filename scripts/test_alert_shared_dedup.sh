#!/usr/bin/env bash
# cron_alert_failure 的共用去重帳本(2026-08-16)。
#
# 為什麼:兩條部署腿都死時,11 個 deploy 呼叫端各推一則紅 —— 同一個根因(憑證 / GitHub
# Actions 被停用)吵 11 次。重複告警會教人把整條通道靜音,那比沒有告警更糟。
# 判準是「行為」不是「措辭」:第一則要推、其餘同指紋的要被壓下、而且被壓下的次數不能消失。
set -u
LIB="${LIB:-$HOME/Delvin-agent/scripts/lib_cron_runner.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
chk() { [ "$2" = "$3" ] && ok "$1" || bad "$1(期望 '$3' 得到 '$2')"; }

WD=$(mktemp -d); trap 'rm -rf "$WD"' EXIT
# 假的 notify:把每次推播記一行,取代真的 web push
cat > "$WD/notify.py" <<'EOF'
import sys, os
open(os.environ["PUSHLOG"], "a", encoding="utf-8").write(sys.argv[1].splitlines()[0] + "\n")
EOF
export PUSHLOG="$WD/pushes.txt"; : > "$PUSHLOG"
export HOME_ORIG="$HOME"

run() {   # run <alert_dir_home> <name> <msg> [dedup_key]
  ( export HOME="$1"; shift
    export CRON_NOTIFY_BIN="$WD/notify.py"
    source "$LIB" >/dev/null 2>&1
    cron_alert_failure "$1" 1 "$2" /dev/null "${3:-}" ) >/dev/null 2>&1
}
FAKE="$WD/home"; mkdir -p "$FAKE/.marketdaily-fallback/state"
# .venv/bin/python 要存在(cron_alert_failure 用它跑 notify)
mkdir -p "$FAKE/Delvin-agent/.venv/bin"; ln -sf "$(command -v python3)" "$FAKE/Delvin-agent/.venv/bin/python"
export CRON_LIB_REPO="$FAKE/Delvin-agent"

echo "== cron_alert_failure 共用去重帳本 =="

# ① 沒傳 dedup key(舊行為):不同 name = 各自帳本 = 都會推
: > "$PUSHLOG"
run "$FAKE" caller_a "同一個根因的錯誤訊息"
run "$FAKE" caller_b "同一個根因的錯誤訊息"
chk "① 舊行為不變:不同 name 各推各的" "$(wc -l < "$PUSHLOG")" "2"

# ② 傳同一個 dedup key:第二則被壓下
: > "$PUSHLOG"
run "$FAKE" caller_c "兩條腿都沒把內容送上線" shared_key
run "$FAKE" caller_d "兩條腿都沒把內容送上線" shared_key
chk "② ⭐ 共用 key:同根因只吵一次" "$(wc -l < "$PUSHLOG")" "1"

# ③ 被壓下的不是「消失」:標題仍是第一個撞到的 caller,可追是誰先壞
chk "③ 標題留著第一個撞到的 caller" "$(grep -c 'caller_c' "$PUSHLOG")" "1"
chk "③ 第二個 caller 沒有自己的推播" "$(grep -c 'caller_d' "$PUSHLOG")" "0"

# ④ ⭐ 反向對照:共用 key 不可把**不同**根因也一起吃掉(那就變成消音而不是去重)
: > "$PUSHLOG"
run "$FAKE" caller_e "完全不一樣的另一種失敗:磁碟滿了" shared_key
chk "④ 不同指紋照樣推得出來(不是無條件消音)" "$(wc -l < "$PUSHLOG")" "1"

# ⑤ 抑制次數要真的**累加**(靜默砍資料是紅線)。
#   ⚠️ 原本寫成 `[ $n -ge 0 ]` —— 那是恆真的空斷言,任何實作都過。改成驗實際數字。
: > "$PUSHLOG"
run "$FAKE" caller_f "計數用的錯誤訊息" count_key      # 第一則:推出去,count 歸 0
run "$FAKE" caller_g "計數用的錯誤訊息" count_key      # 第二則:被壓,count→1
run "$FAKE" caller_h "計數用的錯誤訊息" count_key      # 第三則:被壓,count→2
n=$(cut -d'|' -f3 "$FAKE/.marketdaily-fallback/state/alert_dedup/count_key.fp" 2>/dev/null)
chk "⑤ 只推第一則" "$(wc -l < "$PUSHLOG")" "1"
chk "⑤ 被壓下的兩則有記帳(count=2,不是靜默丟掉)" "${n:-missing}" "2"

echo "── $PASS✓ $FAIL✗"
[ "$FAIL" -eq 0 ]
