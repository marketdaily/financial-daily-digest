#!/bin/bash
# 沙盒驗 digest_postcheck_runner.sh:時間窗口閘 + rc=4 放鎖重試 + 失分才推播。
# 手法:假 HOME + 假 date(PATH shim)+ 假 python(可指定 exit code)+ 假 notify_admin.py。
set -u
RUNNER="$HOME/.marketdaily-fallback/digest_postcheck_runner.sh"
REALLIB="$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
FAILS=0

run_case() {   # $1=情境名 $2=假時間HH:MM $3=星期(1-7) $4=python exit code $5=期望runner rc $6=期望鎖是否留下(yes/no) $7=期望推播(yes/no)
  local name=$1 hhmm=$2 dow=$3 pyrc=$4 want_rc=$5 want_lock=$6 want_push=$7
  local T; T=$(mktemp -d)
  mkdir -p "$T/home/Delvin-agent/scripts" "$T/home/Delvin-agent/.venv/bin" \
           "$T/home/.marketdaily-fallback" "$T/bin"
  cp "$REALLIB" "$T/home/Delvin-agent/scripts/"
  cp "$RUNNER" "$T/home/.marketdaily-fallback/"
  # 假 python:推播腳本走「記一筆」路徑,其餘(=digest_postcheck.py)回指定 exit code。
  # runner 用 "$PY" 同時跑複檢與推播,兩者必須分開,否則推播會被當成複檢的 exit code。
  cat > "$T/home/Delvin-agent/.venv/bin/python" <<EOF
#!/bin/bash
case "\$*" in
  *notify_admin.py*) touch "$T/pushed"; exit 0 ;;
esac
exit $pyrc
EOF
  chmod +x "$T/home/Delvin-agent/.venv/bin/python"
  # 假 date:只攔本腳本用到的格式。⚠️ 必須放在 runner 自己 export 的 PATH 首位
  # (.venv/bin),放外部 $T/bin 會被 runner 的 `export PATH=...` 洗掉 → 用到真時鐘,
  # 全部情境靜默走真實星期閘 exit 0,看起來「綠」其實根本沒跑到(假綠)。
  cat > "$T/home/Delvin-agent/.venv/bin/date" <<EOF
#!/bin/bash
case "\$*" in
  *+%H) echo "${hhmm%%:*}" ;;
  *+%M) echo "${hhmm##*:}" ;;
  *+%u) echo "$dow" ;;
  *+%Y-%m-%d) echo "2026-08-03" ;;
  *) /bin/date "\$@" ;;
esac
EOF
  chmod +x "$T/home/Delvin-agent/.venv/bin/date"
  export T_PUSHED="$T/pushed"
  if [ "${DEBUG_CASE:-}" = "$name" ]; then
    PATH="$T/bin:$PATH" HOME="$T/home" bash -x "$T/home/.marketdaily-fallback/digest_postcheck_runner.sh" 2>&1 | tail -30
    find "$T/home/Delvin-agent" | head -20
  fi
  PATH="$T/bin:$PATH" HOME="$T/home" bash "$T/home/.marketdaily-fallback/digest_postcheck_runner.sh" >/dev/null 2>&1
  local rc=$?
  local lock=no; [ -d "$T/home/Delvin-agent/logs/locks" ] && ls "$T/home/Delvin-agent/logs/locks" 2>/dev/null | grep -q postcheck && lock=yes
  local push=no; [ -e "$T_PUSHED" ] && push=yes
  # 品質戰情板抓 `=== end rc=(\d+)` 的最後一筆,非 0 即紅。defer 不是失分,所以 defer 的
  # log 裡絕不可以出現這行,否則老闆看板會在每個遲交付的班次亮紅燈(驗證者 F4)。
  local endline=no
  grep -qr "=== end rc=" "$T/home/Delvin-agent/logs" 2>/dev/null && endline=yes
  local boardbad=no
  [ "$pyrc" = "4" ] && [ "$endline" = "yes" ] && boardbad=yes
  if [ "$rc" = "$want_rc" ] && [ "$lock" = "$want_lock" ] && [ "$push" = "$want_push" ] \
     && [ "$boardbad" = "no" ]; then
    echo "  ✓ $name (rc=$rc lock=$lock push=$push board=綠)"
  else
    echo "  ✗ $name rc=$rc(want $want_rc) lock=$lock(want $want_lock) push=$push(want $want_push) 戰情板誤紅=$boardbad"
    FAILS=$((FAILS+1))
  fi
  rm -rf "$T"
}

echo "digest_postcheck_runner 沙盒驗:"
run_case "窗口外(10:00)靜默跳過"        10:00 1 0 0 no  no
run_case "早報窗口內全過"               07:50 1 0 0 yes no
run_case "早報硬死線 09:00(原本 07:59 就關窗)" 09:00 1 1 0 yes yes
run_case "早報死線後第二個 tick 09:10 仍在窗口(F7)" 09:10 1 1 0 yes yes
run_case "09:20 已出早報窗口"           09:20 1 1 0 no  no
run_case "rc=4 判決延後→放鎖不推播+戰情板不紅" 21:10 1 4 0 no  no
run_case "晚報失分→留鎖並推播"          21:10 1 1 0 yes yes
run_case "晚報硬死線 23:00 仍在窗口內"   23:00 1 1 0 yes yes
run_case "晚報死線後第二個 tick 23:10 仍在窗口(F7)" 23:10 1 1 0 yes yes
run_case "23:20 已出晚報窗口"           23:20 1 1 0 no  no
run_case "週日不跑"                     07:50 7 1 0 no  no
run_case "週六晚報不跑"                 21:10 6 1 0 no  no
[ "$FAILS" -eq 0 ] && echo "全過" || echo "$FAILS 項失敗"
exit $FAILS
