#!/bin/bash
# digest_selfheal_runner.sh 的「代理新增測試必須自己全綠」閘門 —— 兩個方向都量。
#
# 2026-08-17 實鍋:自癒為當天備援事故新增 test_monday_tldr_and_card_balance.py,
# 該測試自己 2/19 紅,但 guard 的 GATE_TESTS 是寫死清單 ⇒ 這支從來不被執行 ⇒ 紅著照樣 apply。
#
# ⚠️ 本測試**從 runner 原始碼抽出那段迴圈來跑**(不手刻第二份判準):runner 改了而這裡沒跟上時,
# 抽取會失敗並判紅,而不是安靜地繼續測一份過期的副本。
set -u
RUNNER="${SELFHEAL_RUNNER:-$HOME/.marketdaily-fallback/digest_selfheal_runner.sh}"
PASS=0; FAIL=0
chk() { if [ "$2" = 1 ]; then echo "✅ $1"; PASS=$((PASS+1)); else echo "❌ $1"; FAIL=$((FAIL+1)); fi; }

[ -f "$RUNNER" ] || { echo "❌ 找不到 runner:$RUNNER"; exit 1; }

# 抽出閘門那段(從註解錨點到 py_compile 前一行)
SEG="$(awk '/^    # 代理\*\*新寫的\*\*測試檔也必須自己全綠/,/^    # py_compile 改過的 \.py/' "$RUNNER" \
      | sed '$d')"
chk "S0 成功從 runner 抽出閘門片段(抽不到=runner 已改而本測試沒跟上)" \
    "$([ -n "$SEG" ] && echo "$SEG" | grep -q 'scripts/test_\*\.py)' && echo 1 || echo 0)"
[ -n "$SEG" ] || { echo "抽取失敗,無法續測"; exit 1; }

WT="$(mktemp -d)"; trap 'rm -rf "$WT"' EXIT
mkdir -p "$WT/scripts"
printf 'import sys; sys.exit(0)\n' > "$WT/scripts/test_new_green.py"
printf 'import sys; sys.exit(1)\n' > "$WT/scripts/test_new_red.py"
printf 'import sys; sys.exit(1)\n' > "$WT/scripts/test_already_gated.py"   # 紅,但已在 GATE_TESTS
printf 'x = 1\n'                    > "$WT/analyzer.py"

PY=python3
GATE_TESTS="test_already_gated"

run_seg() {  # run_seg <CHANGED...> → stdout 只有 GATE_OK
  local CHANGED="$1" GATE_OK=1
  eval "$SEG" >&2   # 閘門自己的 ❌ 訊息走 stderr,否則會混進 $() 捕到的回傳值
  echo "$GATE_OK"
}

chk "S1 新增的紅測試 → GATE_OK=0(該擋的有擋)" \
    "$([ "$(run_seg 'scripts/test_new_red.py')" = 0 ] && echo 1 || echo 0)"
chk "S2 新增的綠測試 → GATE_OK=1(不誤殺合法修復)" \
    "$([ "$(run_seg 'scripts/test_new_green.py')" = 1 ] && echo 1 || echo 0)"
chk "S3 綠+紅混合 → GATE_OK=0(一支紅就整包擋)" \
    "$([ "$(run_seg 'scripts/test_new_green.py scripts/test_new_red.py')" = 0 ] && echo 1 || echo 0)"
chk "S4 非測試檔(analyzer.py)不被本閘門碰(交給既有 gate/py_compile)" \
    "$([ "$(run_seg 'analyzer.py')" = 1 ] && echo 1 || echo 0)"
chk "S5 已在 GATE_TESTS 的檔不重跑(run_gate 的職責,避免同一支跑兩次)" \
    "$([ "$(run_seg 'scripts/test_already_gated.py')" = 1 ] && echo 1 || echo 0)"

echo
if [ "$FAIL" = 0 ]; then echo "✅ 全過 ($PASS/$((PASS+FAIL)))"; exit 0; fi
echo "❌ 有失敗 ($PASS/$((PASS+FAIL)))"; exit 1
