#!/bin/bash
# council_check.sh 的「掉備援人數」計數 —— 兩個方向都量。
#
# ⭐⭐ 2026-08-24 實鍋:原本用 `grep -cE 'deterministic|掉.*備援|改 deterministic'`,
# 拿**命中行數**當**受影響人數**,而那個 pattern 會吃到
# `[card-regen] 時間預算用盡,剩餘走 deterministic`(卡片重生預算訊息,用戶什麼都沒看到)。
# 實測 08-19~22 四班報「掉備援 1~4 位(用戶看得到)」而真實受影響 0 位;08-24 報 5 而真實 2 位。
# 連續 8 天每天一則假紅 = 把人訓練成忽略這個通道。
#
# ⚠️ 本測試**從 runner 原始碼抽出計數那幾行來跑**(不手刻第二份判準):
#    runner 改了而這裡沒跟上時,抽取會失敗並判紅,而不是安靜地繼續測一份過期的副本。
set -u
RUNNER="${COUNCIL_CHECK:-$HOME/.marketdaily-fallback/council_check.sh}"
PASS=0; FAIL=0
chk() { if [ "$2" = "$3" ]; then echo "✅ $1(得 $3)"; PASS=$((PASS+1)); else echo "❌ $1 期望 $2 實得 $3"; FAIL=$((FAIL+1)); fi }
[ -f "$RUNNER" ] || { echo "❌ 找不到 runner:$RUNNER"; exit 1; }

SEG_COUNT="$(awk '/^detfb=\$\(printf/,/^cardregen=/' "$RUNNER")"
if ! printf '%s' "$SEG_COUNT" | grep -q 'deterministic_fallback' \
   || ! printf '%s' "$SEG_COUNT" | grep -q 'cardregen='; then
  echo "❌ 抽不出計數片段(runner 已改而本測試沒跟上)"; exit 1
fi
echo "✅ 成功從 runner 抽出計數片段"; PASS=$((PASS+1))

count() {   # count <log內容> → "detfb cardregen"
  local SEG="$1" detfb cardregen
  eval "$SEG_COUNT"
  printf '%s %s' "$detfb" "$cardregen"
}

# ① 真的有人掉備援(權威彙總行)→ 必須數得出人數,不是行數
REAL='   ⚠️ a@x HIGH audit fail(tldr_section_missing),retry 一次
   🛡️ retry 仍 HIGH fail(tldr_section_missing) → 切 deterministic fallback
   ⚠️ b@x HIGH audit fail(tldr_section_missing),retry 一次
   🛡️ retry 仍 HIGH fail(tldr_section_missing) → 切 deterministic fallback
🛡️ 2 位走 deterministic fallback
   admin push status=200  🚨含老闆本人掉備援
🛡️ [deterministic_fallback] 2 位收到備援版(個人化生成連 retry 都失敗):a@x, b@x'
set -- $(count "$REAL")
chk "① 真的 2 位掉備援 → detfb=2(舊算法會報 5)" 2 "$1"
chk "①b 同一段沒有 card-regen → 0" 0 "$2"

# ② card-regen 預算用盡(用戶什麼都沒看到)→ detfb 必須是 0
NOISE='  [card-regen] 時間預算用盡,剩餘走 deterministic
  [card-regen] 時間預算用盡,剩餘走 deterministic
  [card-regen] 時間預算用盡,剩餘走 deterministic'
set -- $(count "$NOISE")
chk "② 只有 card-regen → detfb=0(舊算法會報 3 並喊「用戶看得到」)" 0 "$1"
chk "②b card-regen 另外記得住 → 3" 3 "$2"

# ③ 沒有彙總行時退回逐人行(舊格式/log 被截斷),仍要數對人數
OLDFMT='   🛡️ retry 仍 HIGH fail(x) → 切 deterministic fallback
  [card-regen] 時間預算用盡,剩餘走 deterministic'
set -- $(count "$OLDFMT")
chk "③ 無彙總行 → 退回逐人行,仍得 1(不被 card-regen 那行汙染)" 1 "$1"

# ④ 完全乾淨的一班 → 兩個都 0(不可無中生有)
set -- $(count '  一切正常
main.py exit=0')
chk "④ 乾淨班次 detfb=0" 0 "$1"
chk "④b 乾淨班次 cardregen=0" 0 "$2"

echo
echo "$PASS/$((PASS+FAIL)) 通過"
[ "$FAIL" = 0 ] || exit 1
