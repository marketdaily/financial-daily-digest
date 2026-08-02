#!/bin/bash
# 沙盒驗 digest_chronic_runner.sh:窗口閘 + 每日鎖 + rc 路由 + 記帳時序 + guard 白名單/測試把關。
# 手法:假 HOME(內含真 git repo + 假 bare remote)+ 假 date/python/claude(PATH shim)。
# ⚠️ 假 shim 必須放在 runner 自己 export 的 PATH 首位(.venv/bin),否則會被洗掉 → 全部情境
# 靜默走真實時鐘 exit 0,看起來綠其實根本沒跑到(postcheck runner gate 踩過的假綠)。
set -u
RUNNER="$HOME/.marketdaily-fallback/digest_chronic_runner.sh"
REALLIB="$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
FAILS=0

# $1=情境 $2=HH:MM $3=偵測器rc $4=fix鍵值(逗號) $5=claude行為(none|ok|scope|badtest)
# $6=期望verdict字串(在log裡grep;- =不檢查) $7=期望推播(yes/no) $8=期望記帳動作(- =不檢查)
run_case() {
  local name=$1 hhmm=$2 detrc=$3 keys=$4 claude_mode=$5 want_verdict=$6 want_push=$7 want_rec=$8
  local T; T=$(mktemp -d)
  local R="$T/home/Delvin-agent"
  mkdir -p "$R/scripts" "$R/.venv/bin" "$T/home/.marketdaily-fallback/state" "$T/bin"
  cp "$REALLIB" "$R/scripts/"
  cp "$RUNNER" "$T/home/.marketdaily-fallback/"
  cp "$HOME/Delvin-agent/scripts/digest_chronic_playbook.md" "$R/scripts/"
  echo "print('x')" > "$R/main.py"
  ( cd "$R" && git init -q . && git config user.email t@t && git config user.name t \
      && git add -A && git commit -qm init ) >/dev/null 2>&1
  git init -q --bare "$T/remote.git" >/dev/null 2>&1
  ( cd "$R" && git remote add origin "$T/remote.git" && git push -q origin main 2>/dev/null \
      || ( cd "$R" && git branch -M main && git push -q origin main ) ) >/dev/null 2>&1

  local FIXJSON="{\"verdict\":\"fix\",\"fix\":[$(echo "$keys" | tr ',' '\n' | sed 's/.*/{"key":"&"}/' | paste -sd, -)],\"escalate\":[]}"
  [ -z "$keys" ] && FIXJSON='{"verdict":"fix","fix":[],"escalate":[]}'
  [ "$detrc" = "2" ] && FIXJSON='{"verdict":"escalate","fix":[],"escalate":[{"key":"delivery"}]}'

  cat > "$R/.venv/bin/python" <<EOF
#!/bin/bash
case "\$*" in
  *scripts/test_*.py) exec /usr/bin/python3 "\$@" ;;   # guard 的測試把關要真的跑,不能被 shim 吃掉變假綠
  *notify_admin.py*) echo "\$*" >> "$T/pushed"; exit 0 ;;
  *dotenv*) echo ""; exit 0 ;;
  *digest_chronic_triage.py\ record\ *) echo "\$*" >> "$T/records"; exit 0 ;;
  *digest_chronic_triage.py\ --json*) echo '$FIXJSON'; exit $detrc ;;
  *digest_chronic_triage.py*) echo "摘要文字"; exit $detrc ;;
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
case "$claude_mode" in
  ok)      echo "print('fixed')" >> main.py ;;
  scope)   mkdir -p docs && echo x > docs/leak.html ;;
  badtest) echo "print('fixed')" >> main.py; mkdir -p scripts
           printf '#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n' > scripts/test_digest_chronic_triage.py ;;
esac
exit 0
EOF
  chmod +x "$R/.venv/bin/claude"
  # 假 test:guard 會跑 worktree 裡存在的 scripts/test_*.py(用真 PY shim,預設 exit 0)
  printf '#!/usr/bin/env python3\n' > "$R/scripts/test_digest_chronic_triage.py"
  ( cd "$R" && git add -A && git commit -qm files ) >/dev/null 2>&1

  if [ "${DEBUG_CASE:-}" = "$name" ]; then
    PATH="$T/bin:$PATH" HOME="$T/home" bash -x "$T/home/.marketdaily-fallback/digest_chronic_runner.sh" 2>&1 | tail -40
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
  if [ "$want_rec" != "-" ]; then echo "$recs" | grep -q "$want_rec" || ok=0; fi
  if [ "$ok" = 1 ]; then
    echo "  ✓ $name (rc=$rc push=$push 記帳=${recs:0:60})"
  else
    echo "  ✗ $name rc=$rc push=$push(want $want_push) 記帳=$recs"
    echo "     log: $(echo "$logtxt" | tr '\n' '|' | tail -c 300)"
    FAILS=$((FAILS+1))
  fi
  RUN_T="$T"
}

echo "digest_chronic_runner 沙盒:"
run_case "窗口外(10:30)不跑"        "10:30" 0 "k1"           none "-"              no  "-"
[ -f "$RUN_T/home/.marketdaily-fallback/logs/chronic_2026-08-03.log" ] && { echo "  ✗ 窗口外仍寫了 log"; FAILS=$((FAILS+1)); }
run_case "無慢性失分安靜退"          "11:10" 1 ""             none "安靜退"          no  "-"
run_case "需人工只推播不 spawn"      "11:10" 2 ""             none "escalate"       yes "escalated delivery"
run_case "偵測器自己炸了要推播"      "11:10" 3 ""             none "detector crashed" yes "-"
run_case "rc0 但無 fix 項=邏輯不一致" "11:10" 0 ""            none "fix 清單是空的"          yes "-"
run_case "代理沒改任何檔=none"       "11:10" 0 "personal_audio" none "verdict=none"  yes "blocked personal_audio"
run_case "改到白名單外整包丟棄"      "11:10" 0 "personal_audio" scope "blocked_scope" yes "blocked personal_audio"
run_case "未過測試把關整包丟棄"      "11:10" 0 "personal_audio" badtest "blocked_tests" yes "blocked personal_audio"
run_case "白名單內+測試過→套用push"  "11:10" 0 "personal_audio" ok   "verdict=apply"  yes "applied personal_audio"

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
