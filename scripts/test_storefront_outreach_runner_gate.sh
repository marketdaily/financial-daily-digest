#!/bin/bash
# 沙盒驗 storefront_outreach_runner.sh:①followup 有硬逾時 ②成功戳記只在三段 rc 全 0 才蓋。
#
# 起因(2026-09-15):那一班的 log 只寫到標題就沒了,整班無聲死在 followup 的 IMAP 上,
# 而【一則告警都沒響】——因為每一則的前提都是「腳本活到那一行」,行程被殺根本走不到。
# 更要命的是它從上線起就沒有成功戳記,所以不在 fleet_liveness 的艦隊裡:
# 「這班昨天到底有沒有跑完」在系統裡沒有任何地方回答得出來。
#
# 手法:假 HOME + 假 python(可指定各子指令的 exit code),不碰網路、不寄任何信。
set -u
RUNNER="${OUTREACH_RUNNER:-$HOME/.marketdaily-fallback/storefront_outreach_runner.sh}"   # 覆寫點:突變測試用副本
REALLIB="$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
FAILS=0
ok(){ echo "  ✓ $1"; }
ng(){ echo "  ✗ $1"; [ $# -gt 1 ] && echo "     $2"; FAILS=$((FAILS+1)); }

run_case() {   # $1=情境 $2=followup_rc $3=send_rc $4=dashboard_rc
  local name=$1 frc=$2 src=$3 drc=$4
  T=$(mktemp -d)
  mkdir -p "$T/home/Delvin-agent/scripts" "$T/home/Delvin-agent/.venv/bin" \
           "$T/home/.marketdaily-fallback" "$T/home/storefront/growth"
  cp "$REALLIB" "$T/home/Delvin-agent/scripts/"
  # ⚠️ 指定目的檔名:cp 會保留來源檔名,而下面是用固定名字執行的 —— 覆寫 RUNNER 做突變時
  #    沙盒裡會變成「檔案不存在」⇒ 每條斷言都紅,但紅的理由跟它要量的事無關(假的鑑別力)。
  cp "$RUNNER" "$T/home/.marketdaily-fallback/storefront_outreach_runner.sh"
  cat > "$T/home/Delvin-agent/.venv/bin/python" <<EOF
#!/bin/bash
case "\$*" in
  *notify_admin.py*)      echo "\$*" >> "$T/pushes"; exit 0 ;;
  *cli\ followup*)        echo "回信掃描:假的"; exit $frc ;;
  *outreach_claim_check*) echo "驗了 0 封:可寄 0、擋下 0"; exit 0 ;;
  *cli\ send*)            echo "(沙盒不寄)"; exit $src ;;
  *cli\ sync-dashboard*)  exit $drc ;;
  *leads_sync*)           exit 0 ;;
esac
exit 0
EOF
  chmod +x "$T/home/Delvin-agent/.venv/bin/python"
  HOME="$T/home" bash "$T/home/.marketdaily-fallback/storefront_outreach_runner.sh" >/dev/null 2>&1
  STAMP="$T/home/Delvin-agent/logs/ok/storefront_outreach.ok"
  LOG=$(cat "$T/home/Delvin-agent/logs/storefront_outreach_"*.log 2>/dev/null)
  PUSHES=$(cat "$T/pushes" 2>/dev/null)
}

echo "[1] 三段都成功 → 蓋戳記、走到 === end ==="
run_case allok 0 0 0
[ -f "$STAMP" ] && ok "成功時蓋下戳記(艦隊 liveness 才看得到這班)" || ng "成功應蓋戳記"
case "$LOG" in *"=== end"*) ok "跑到結尾";; *) ng "沒跑到結尾" "$LOG";; esac
case "$PUSHES" in "") ok "全綠不推播";; *) ng "全綠不該推播" "$PUSHES";; esac

echo "[2] ⭐ followup 失敗 → 不准蓋戳記(壞掉時已有告警,再蓋等於對自己謊報成功)"
run_case f_fail 3 0 0
[ -f "$STAMP" ] && ng "followup 壞掉還蓋戳記" || ok "followup 壞掉不蓋戳記"
case "$PUSHES" in *"回信掃描失敗"*) ok "有推回信掃描失敗";; *) ng "缺告警" "$PUSHES";; esac

echo "[3] ⭐ 寄件失敗 → 不准蓋戳記"
run_case s_fail 0 5 0
[ -f "$STAMP" ] && ng "寄件壞掉還蓋戳記" || ok "寄件壞掉不蓋戳記"

echo "[4] ⭐ 後台同步失敗 → 不准蓋戳記(畫面會停在舊資料而且看起來很正常)"
run_case d_fail 0 0 7
[ -f "$STAMP" ] && ng "後台同步壞掉還蓋戳記" || ok "後台同步壞掉不蓋戳記"

echo "[5] ⭐ followup 被硬逾時包住(09-15 掛死在 IMAP 的止血點)"
if grep -qE '^[[:space:]]*timeout [0-9]+ "\$PY" -m storefront\.cli followup' "$RUNNER"; then
  ok "followup 這行真的帶 timeout"
else
  ng "followup 沒有逾時保護" "$(grep -n 'cli followup' "$RUNNER")"
fi

echo "[6] ⭐ 逾時(124)會走進 RC_F 告警,不是安靜結束"
run_case f_timeout 124 0 0
case "$PUSHES" in *"rc=124"*) ok "逾時有推播且帶得出 124";; *) ng "逾時沒推播" "$PUSHES";; esac
[ -f "$STAMP" ] && ng "逾時還蓋戳記" || ok "逾時不蓋戳記"

echo
if [ "$FAILS" -gt 0 ]; then echo "❌ storefront outreach runner gate:$FAILS 條沒過"; exit 1; fi
echo "✅ storefront outreach runner gate 全過"
