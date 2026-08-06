#!/bin/bash
# cron_daily_lock() 迴歸(lib_cron_runner.sh)。
#
# 背景:此 WSL2 host(kernel 6.6/tmpfs)的 mkdir 併發下非原子(lesson wsl2_mkdir_not_atomic,
# 實測 4/200 兩行程同時 mkdir 成功)。舊版 cron_daily_lock 裸用 mkdir 認領,對多個生產呼叫端
# (social_post_runner 等)有 2-4% 雙重執行漏洞,對 send-once/落帳語意=真 bug。修法同既有
# capabilities/cron_catchup:用 flock 序列化「檢查墓碑→立碑」整段,mkdir 仍當跨 tick 持久墓碑。
#
# 手法:
#  ①②序列行為(舊語意不變)。
#  ③24-way barrier 併發壓測(機率性證據,3 輪,仿 cron_catchup.test.sh 第14段——這台 host 的
#    原始race窗很窄,幾十輪手測不保證每次都撞到,故不是本檔唯一的正確性依據)。
#  ④⑤**決定性**驗證 flock 真的是承重點(仿 cron_catchup.test.sh 第22段手法):外部行程握住
#    同一把 flock 檔案,斷言 cron_daily_lock 真的被擋住(要等外部釋放才能繼續)——若有人把 flock
#    移除退回裸 mkdir,這兩段會**確定性**失敗(不靠機率),彌補③的機率性弱點。
#  ⑥ 鎖逾時 fail-safe(外部長握鎖超過 -w 10 逾時)不可掛住呼叫端、也不可雙重認領。
set -u
LIB="$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
FAILS=0
ok() { echo "  ok: $1"; }
fail() { echo "  ✗ FAIL: $1"; FAILS=$((FAILS+1)); }

SB=$(mktemp -d)
trap 'rm -rf "$SB"' EXIT

run_lock() {   # $1=SB $2=name  → 呼叫 cron_daily_lock,回傳其 exit code,side-effect 印 CLAIMED
  local sb="$1" name="$2"
  ( CRON_LIB_REPO="$sb"
    # shellcheck source=/dev/null
    source "$LIB"
    cron_daily_lock "$name"
    echo CLAIMED
  )
}

# ── 1) 首次呼叫要認領成功(印 CLAIMED,exit 0)且真的立碑 ──────────────────
R1="$SB/t1"; mkdir -p "$R1"
out=$(run_lock "$R1" "j1"); rc=$?
if [ "$out" = "CLAIMED" ] && [ "$rc" -eq 0 ]; then ok "1-首次呼叫認領成功"; else fail "1-首次呼叫認領成功(out=$out rc=$rc)"; fi
[ -d "$R1/logs/locks/j1.$(TZ=Asia/Taipei date +%F)" ] && ok "1b-墓碑目錄已建立" || fail "1b-墓碑目錄已建立"

# ── 2) 同名同日第二次呼叫要靜默 exit 0、不印 CLAIMED(舊語意不變) ──────────
out=$(run_lock "$R1" "j1"); rc=$?
if [ -z "$out" ] && [ "$rc" -eq 0 ]; then ok "2-同日重複呼叫靜默 exit 0"; else fail "2-同日重複呼叫靜默 exit 0(out=$out rc=$rc)"; fi

# 不同 name 互不干擾
out=$(run_lock "$R1" "j2"); rc=$?
if [ "$out" = "CLAIMED" ] && [ "$rc" -eq 0 ]; then ok "2b-不同 name 各自獨立認領"; else fail "2b-不同 name 各自獨立認領(out=$out rc=$rc)"; fi

# ── 3) 24-way barrier 併發:全機只能有 1 個行程真的認領到(機率性,3 輪) ──
N_RACE=24
for round in 1 2 3; do
  RB="$SB/race$round"; rm -rf "$RB"; mkdir -p "$RB/arena"
  : > "$RB/arrived"
  : > "$RB/ran"
  for i in $(seq 1 "$N_RACE"); do
    (
      echo "$i" >> "$RB/arrived"
      while [ ! -e "$RB/go" ]; do sleep 0.02; done
      out=$(run_lock "$RB/arena" "race")
      [ "$out" = "CLAIMED" ] && echo x >> "$RB/ran"
    ) &
  done
  for _ in $(seq 1 200); do
    [ "$(wc -l < "$RB/arrived" 2>/dev/null || echo 0)" -ge "$N_RACE" ] && break
    sleep 0.05
  done
  : > "$RB/go"
  wait
  claims=$(wc -l < "$RB/ran" 2>/dev/null || echo 0)
  if [ "$claims" -eq 1 ]; then ok "3-併發只認領一次(第 $round 輪)"; else fail "3-併發只認領一次(第 $round 輪,claims=$claims 應為1)"; fi
done

# ── 4) ⭐決定性:外部行程長握 flock 檔,cron_daily_lock 必須真的被擋住 ──────
# 若 flock 呼叫被移除(退回裸 mkdir),cron_daily_lock 不會被外部鎖擋,會在遠早於
# HELD_SEC 就完成認領——elapsed 會遠小於 HELD_SEC,本段確定性失敗,不靠機率。
R4="$SB/t4"; mkdir -p "$R4/logs/locks"
HELD_SEC=3
today=$(TZ=Asia/Taipei date +%F)
flock -x "$R4/logs/locks/.j4.flock" -c "sleep $HELD_SEC" &
HOLD_PID=$!
sleep 0.3   # 讓外部行程確實先拿到鎖
t0=$(date +%s.%N)
out=$(run_lock "$R4" "j4"); rc=$?
t1=$(date +%s.%N)
wait "$HOLD_PID" 2>/dev/null
elapsed=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.2f", b-a}')
if awk -v e="$elapsed" -v h="$HELD_SEC" 'BEGIN{exit !(e >= h - 0.5)}'; then
  ok "4-外部長握 flock 期間 cron_daily_lock 確實被擋住(elapsed=${elapsed}s >= ${HELD_SEC}s)"
else
  fail "4-外部長握 flock 期間 cron_daily_lock 確實被擋住(elapsed=${elapsed}s,應 >= ${HELD_SEC}s——像是 flock 沒生效)"
fi
if [ "$out" = "CLAIMED" ] && [ "$rc" -eq 0 ]; then ok "4b-外部鎖釋放後仍正確認領成功"; else fail "4b-外部鎖釋放後仍正確認領成功(out=$out rc=$rc)"; fi
[ -d "$R4/logs/locks/j4.$today" ] && ok "4c-墓碑目錄已建立" || fail "4c-墓碑目錄已建立"

# ── 5) 逾時 fail-safe:外部長握鎖超過 -w 10 上限,呼叫端必須在合理時間內拿回控制權 ──
#     且不可誤判為「已認領」(不印 CLAIMED),也不可留下墓碑(視為當次讓路,下個班次可重試)。
R5="$SB/t5"; mkdir -p "$R5/logs/locks"
flock -x "$R5/logs/locks/.j5.flock" -c "sleep 13" &
HOLD_PID5=$!
sleep 0.3
t0=$(date +%s.%N)
out=$(run_lock "$R5" "j5"); rc=$?
t1=$(date +%s.%N)
elapsed=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.2f", b-a}')
# 逾時上限 10s,允許排程抖動,理應在 9~13s 之間結束(遠早於外部行程的 13s 才對,允許 <=12s)
if awk -v e="$elapsed" 'BEGIN{exit !(e >= 9 && e <= 12.5)}'; then
  ok "5-逾時 fail-safe 在 ~10s 內放行(elapsed=${elapsed}s)"
else
  fail "5-逾時 fail-safe 在 ~10s 內放行(elapsed=${elapsed}s,應落在 9~12.5s)"
fi
if [ -z "$out" ] && [ "$rc" -eq 0 ]; then ok "5b-逾時不誤判為已認領(靜默 exit 0)"; else fail "5b-逾時不誤判為已認領(out=$out rc=$rc)"; fi
[ -d "$R5/logs/locks/j5.$today" ] && fail "5c-逾時不應留下墓碑(下班次應可重試)" || ok "5c-逾時不留墓碑,下班次可重試"
wait "$HOLD_PID5" 2>/dev/null

echo "----"
if [ "$FAILS" -eq 0 ]; then
  echo "ALL PASS (test_cron_daily_lock.sh)"
  exit 0
else
  echo "$FAILS FAILURES (test_cron_daily_lock.sh)"
  exit 1
fi
