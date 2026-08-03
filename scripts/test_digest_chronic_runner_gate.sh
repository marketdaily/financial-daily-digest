#!/bin/bash
# 沙盒驗 digest_chronic_runner.sh:窗口閘 + 每日鎖 + rc 路由 + 記帳時序 + guard(白名單/繳械/測試把關)。
# 手法:假 HOME(內含真 git repo + 假 bare remote)+ 假 date/python/claude(PATH shim)。
# ⚠️ 假 shim 必須放在 runner 自己 export 的 PATH 首位(.venv/bin),否則會被洗掉 → 全部情境
# 靜默走真實時鐘 exit 0,看起來綠其實根本沒跑到(postcheck runner gate 踩過的假綠)。
#
# ⭐ 兩個「上一版假綠」的教訓(第 1 輪驗證者 F1 note③ / F4):
#  ①gate 測試不可用空殼:空殼必過 → 「白名單內+測試過→套用」證明的是空殼會過,不是把關有效。
#    這裡的 stub **對 main.py 內容敏感**(含 BROKEN 就紅),所以「代理改壞碼→blocked_tests」是真的走完把關。
#  ②gate 清單直接從 runner 檔案解析:有人往清單加測試但沒同步沙盒 → 這裡會缺檔而炸,不會靜默漏測。
#  ⚠️ 沙盒證明的是 **runner 的邏輯**;「生產那 8 支真測試在 worktree 裡跑不跑得動」是另一回事,
#    由 scripts/test_digest_chronic_gate_env.sh 用真 repo 的真 worktree 驗(F1 的本體)。
set -u
RUNNER="$HOME/.marketdaily-fallback/digest_chronic_runner.sh"
REALLIB="$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
SRC="$HOME/Delvin-agent/scripts"
FAILS=0

# gate 清單的唯一真源 = runner 自己
GATE_LIST=$(sed -n '/^GATE_TESTS="/,/"$/p' "$RUNNER" | sed 's/^GATE_TESTS="//; s/"$//')
[ -n "$GATE_LIST" ] || { echo "✗ 解析不到 runner 的 GATE_TESTS(沙盒與 runner 脫鉤,拒絕假綠)"; exit 1; }

# $1=情境 $2=HH:MM $3=偵測器rc $4=fix鍵值(逗號) $5=claude行為 $6=期望verdict $7=期望推播 $8=期望記帳
# 可選環境變數:CASE_VERDICT_JSON(覆寫偵測器 JSON 的 verdict 區塊)、CASE_BASELINE_RED=1、CASE_PUSH_FAIL=1
run_case() {
  local name=$1 hhmm=$2 detrc=$3 keys=$4 claude_mode=$5 want_verdict=$6 want_push=$7 want_rec=$8
  local T; T=$(mktemp -d)
  local R="$T/home/Delvin-agent"
  mkdir -p "$R/scripts" "$R/.venv/bin" "$T/home/.marketdaily-fallback/state" "$T/bin"
  cp "$REALLIB" "$R/scripts/"
  cp "$RUNNER" "$T/home/.marketdaily-fallback/"
  cp "$SRC/digest_chronic_playbook.md" "$R/scripts/"
  cp "$SRC/digest_chronic_triage.py" "$R/scripts/"     # summary_line 用真的,不用假摘要
  echo "print('x')" > "$R/main.py"

  # gate stub:①多行(才驗得出「刪行=繳械」)②對 main.py 內容敏感(才驗得出真的把關)
  local t
  for t in $GATE_LIST; do
    cat > "$R/scripts/$t.py" <<'STUB'
#!/usr/bin/env python3
import sys
from pathlib import Path
src = Path("main.py").read_text(encoding="utf-8") if Path("main.py").exists() else ""
if "BROKEN" in src:
    print("stub gate: main.py 壞了")
    sys.exit(1)
sys.exit(0)
STUB
  done
  # 注意:GATE_LIST 是多行多欄的字串,取「第一支」要取第一個**單字**,不是第一行
  local FIRSTT; FIRSTT=$(echo $GATE_LIST | awk '{print $1}')
  [ "${CASE_BASELINE_RED:-}" = 1 ] && printf '#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n' \
      > "$R/scripts/$FIRSTT.py"

  ( cd "$R" && git init -q . && git config user.email t@t && git config user.name t \
      && git add -A && git commit -qm init ) >/dev/null 2>&1
  git init -q --bare "$T/remote.git" >/dev/null 2>&1
  if [ "${CASE_PUSH_FAIL:-}" = 1 ]; then
    printf '#!/bin/sh\nexit 1\n' > "$T/remote.git/hooks/pre-receive"; chmod +x "$T/remote.git/hooks/pre-receive"
  fi
  ( cd "$R" && git branch -M main && git remote add origin "$T/remote.git" \
      && git push -q origin main ) >/dev/null 2>&1

  local FIXJSON
  FIXJSON="{\"verdict\":\"fix\",\"shifts_seen\":10,\"blind\":\"\",\"parse_drift\":[],\"ledger_broken\":\"\",\"cooling\":[],\"escalate\":[],\"fix\":[$(echo "$keys" | tr ',' '\n' | sed 's/.*/{"key":"&","hits":3}/' | paste -sd, -)]}"
  [ -z "$keys" ] && FIXJSON='{"verdict":"fix","shifts_seen":10,"blind":"","parse_drift":[],"ledger_broken":"","cooling":[],"escalate":[],"fix":[]}'
  [ -n "${CASE_VERDICT_JSON:-}" ] && FIXJSON="$CASE_VERDICT_JSON"

  local CASE_NOTIFY_RC=${CASE_NOTIFY_RC:-0}
  cat > "$R/.venv/bin/python" <<EOF
#!/bin/bash
case "\$*" in
  *scripts/test_*.py) exec /usr/bin/python3 "\$@" ;;   # guard 的測試把關要真的跑,不能被 shim 吃掉變假綠
  *notify_admin.py*) echo "\$*" >> "$T/pushed"; exit ${CASE_NOTIFY_RC:-0} ;;
  *dotenv*) echo ""; exit 0 ;;
  *digest_chronic_triage.py\ record\ *) echo "\$*" >> "$T/records"; exit 0 ;;
  *digest_chronic_triage.py\ --json*) echo '$FIXJSON'; exit $detrc ;;
  -m*py_compile*) exit 0 ;;
  -c*) shift; exec /usr/bin/python3 -c "\$@" ;;
esac
exit 0
EOF
  chmod +x "$R/.venv/bin/python"
  cat > "$R/.venv/bin/date" <<EOF
#!/bin/bash
case "\$*" in
  *+%H) echo "${hhmm%%:*}" ;;
  *+%M) echo "${hhmm##*:}" ;;
  *+%u) echo "1" ;;
  *+%Y-%m-%d) echo "2026-08-03" ;;
  *) /bin/date "\$@" ;;
esac
EOF
  chmod +x "$R/.venv/bin/date"
  cat > "$R/.venv/bin/claude" <<EOF
#!/bin/bash
touch "$T/claude_ran"
case "$claude_mode" in
  ok)        echo "print('fixed')" >> main.py; touch .chronic_done ;;
  scope)     mkdir -p docs && echo x > docs/leak.html; touch .chronic_done ;;
  breakcode) echo "# BROKEN" >> main.py; touch .chronic_done ;;
  tamper)    echo "print('fixed')" >> main.py; touch .chronic_done
             printf '#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n' > "scripts/$FIRSTT.py" ;;
  halfway)   echo "print('half')" >> main.py ;;   # 改了東西但沒留完工標記 = 被 timeout 砍在半路
esac
exit 0
EOF
  chmod +x "$R/.venv/bin/claude"
  ( cd "$R" && git add -A && git commit -qm files ) >/dev/null 2>&1
  [ "${CASE_DIRTY_MAIN:-}" = 1 ] && echo "# 別視窗的 WIP" >> "$R/main.py"

  if [ "${DEBUG_CASE:-}" = "$name" ]; then
    PATH="$T/bin:$PATH" HOME="$T/home" bash -x "$T/home/.marketdaily-fallback/digest_chronic_runner.sh" 2>&1 | tail -60
  fi
  PATH="$T/bin:$PATH" HOME="$T/home" bash "$T/home/.marketdaily-fallback/digest_chronic_runner.sh" >/dev/null 2>&1
  local rc=$?
  local log="$T/home/.marketdaily-fallback/logs/chronic_2026-08-03.log"
  local logtxt=""; [ -f "$log" ] && logtxt=$(cat "$log")
  local push=no; [ -e "$T/pushed" ] && push=yes
  local recs=""; [ -e "$T/records" ] && recs=$(tr '\n' ';' < "$T/records")
  local ok=1
  [ "$rc" = 0 ] || ok=0
  [ "$push" = "$want_push" ] || ok=0
  if [ "$want_verdict" != "-" ]; then echo "$logtxt" | grep -q "$want_verdict" || ok=0; fi
  case "$want_rec" in
    -) : ;;
    "!"*) echo "$recs" | grep -q "${want_rec#!}" && ok=0 ;;   # 期望「不可出現」
    *) echo "$recs" | grep -q "$want_rec" || ok=0 ;;
  esac
  if [ "$ok" = 1 ]; then
    echo "  ✓ $name (rc=$rc push=$push 記帳=${recs:0:60})"
  else
    echo "  ✗ $name rc=$rc push=$push(want $want_push) 記帳=$recs (want $want_rec)"
    echo "     log: $(echo "$logtxt" | tr '\n' '|' | tail -c 400)"
    FAILS=$((FAILS+1))
  fi
  RUN_T="$T"
}

CLEAN_JSON='{"verdict":"clean","shifts_seen":10,"blind":"","parse_drift":[],"ledger_broken":"","cooling":[],"escalate":[],"fix":[]}'
COOL_JSON='{"verdict":"cooling","shifts_seen":10,"blind":"","parse_drift":[],"ledger_broken":"","cooling":[{"key":"personal_audio","why":"冷卻中"}],"escalate":[],"fix":[]}'
ESC_JSON='{"verdict":"escalate","shifts_seen":10,"blind":"","parse_drift":[],"ledger_broken":"","cooling":[],"notify":true,"escalate":[{"key":"delivery","hits":3,"why":"不開放自動改碼"}],"fix":[]}'
ESC_MUTE='{"verdict":"escalate","shifts_seen":10,"blind":"","parse_drift":[],"ledger_broken":"","cooling":[],"notify":false,"escalate":[{"key":"delivery","hits":3,"why":"不開放自動改碼"}],"fix":[]}'

echo "digest_chronic_runner 沙盒(gate 清單 $(echo "$GATE_LIST" | wc -w) 支,由 runner 檔案解析):"
CASE_VERDICT_JSON="$CLEAN_JSON" \
run_case "窗口外(10:30)不跑"          "10:30" 1 ""  none "-"                no  "-"
[ -f "$RUN_T/home/.marketdaily-fallback/logs/chronic_2026-08-03.log" ] && { echo "  ✗ 窗口外仍寫了 log"; FAILS=$((FAILS+1)); }
CASE_VERDICT_JSON="$CLEAN_JSON" \
run_case "無慢性失分安靜退"            "11:10" 1 ""  none "安靜退"            no  "-"
CASE_VERDICT_JSON="$COOL_JSON" \
run_case "冷卻中也安靜退"              "11:10" 1 ""  none "安靜退"            no  "-"
# rc=1 卻不是預期摘要 = 輸出被截斷/環境怪異 → 寧可吵也不要靜音(第 1 輪 F2)
run_case "rc=1 但摘要異常要推播"       "11:10" 1 "personal_audio" none "摘要異常" yes "-"
CASE_VERDICT_JSON="$ESC_JSON" \
run_case "需人工只推播不 spawn"        "11:10" 2 ""  none "escalate"          yes "escalated delivery"
[ -e "$RUN_T/claude_ran" ] && { echo "  ✗ escalate 情境竟然 spawn 了 claude"; FAILS=$((FAILS+1)); }
# 未到重講週期:不推播,**也不可以記 escalated**(每輪都記→last_escalated 天天往前推→永久靜音)
CASE_VERDICT_JSON="$ESC_MUTE" \
run_case "需人工但未到重講週期"        "11:10" 2 ""  none "未到重講週期"       no  "!escalated"
run_case "偵測器自己炸了(rc=3)要推播" "11:10" 3 "" none "detector crashed"  yes "-"
CASE_VERDICT_JSON="$CLEAN_JSON" \
run_case "rc0 但無 fix 項=邏輯不一致"  "11:10" 0 ""  none "fix 清單是空的"    yes "-"
# 未改任何東西時 gate 就紅 → 不 spawn、不記帳、推播「先修 gate 環境」(第 1 輪 F1 的形狀)
CASE_BASELINE_RED=1 \
run_case "baseline gate 紅就不 spawn"  "11:10" 0 "personal_audio" ok "baseline gate 紅" yes "!attempted"
[ -e "$RUN_T/claude_ran" ] && { echo "  ✗ baseline 紅卻仍 spawn 了 claude(白燒 token)"; FAILS=$((FAILS+1)); }
run_case "代理沒改任何檔=none"         "11:10" 0 "personal_audio" none      "verdict=none"   yes "blocked personal_audio"
run_case "改到白名單外整包丟棄"        "11:10" 0 "personal_audio" scope     "blocked_scope"  yes "blocked personal_audio"
run_case "改壞碼→測試把關擋下"         "11:10" 0 "personal_audio" breakcode "blocked_tests"  yes "blocked personal_audio"
run_case "動 gate 測試=繳械整包丟棄"   "11:10" 0 "personal_audio" tamper    "blocked_tamper" yes "blocked personal_audio"
CASE_PUSH_FAIL=1 \
run_case "push 失敗記 aborted 不燒額度" "11:10" 0 "personal_audio" ok       "verdict=apply"  yes "aborted personal_audio"
run_case "白名單內+測試過→套用push"    "11:10" 0 "personal_audio" ok        "verdict=apply"  yes "applied personal_audio"
# 沒有完工標記 = 被 timeout 砍在半路,半成品不可 apply(第 2 輪驗證者 Notes)
run_case "無完工標記→不套用半成品"     "11:10" 0 "personal_audio" halfway   "aborted_halfway" yes "aborted personal_audio"
# 主樹 scope 內有別視窗 WIP → **spawn 前**就讓路,不燒 15 分鐘 opus(第 2 輪驗證者 F1 加重情節 B)
CASE_DIRTY_MAIN=1 \
run_case "主樹髒→spawn 前就讓路"       "11:10" 0 "personal_audio" ok        "spawn 前發現"   no  "!attempted"
[ -e "$RUN_T/claude_ran" ] && { echo "  ✗ 主樹髒卻仍 spawn 了 claude(白燒 token)"; FAILS=$((FAILS+1)); }
# 推播全通道失敗(403/斷網)→ 不可記 escalated,否則 last_escalated 前推 = 接下來 7 天真靜音
CASE_VERDICT_JSON="$ESC_JSON" CASE_NOTIFY_RC=1 \
run_case "推播送不出去→不記 escalated" "11:10" 2 ""  none "推播送不出去"    yes "!escalated"

# 立案記帳必須在 spawn 之前(中途斷電也不可以天天重複立案)
T2=$RUN_T
if [ -f "$T2/records" ] && [ "$(head -1 "$T2/records" | grep -c 'record attempted')" != 1 ]; then
  echo "  ✗ 第一筆記帳不是 attempted(立案記帳必須先於 spawn)"; FAILS=$((FAILS+1))
else
  echo "  ✓ 立案記帳先於 spawn(第一筆=attempted)"
fi

echo "  ⓘ 每日鎖由 mkdir 原子性保證(同 postcheck runner gate 已驗機制)"

[ "$FAILS" = 0 ] && { echo "全過"; exit 0; }
echo "$FAILS 個情境未過"; exit 1
