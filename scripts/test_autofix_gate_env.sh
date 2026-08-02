#!/bin/bash
# 自動修「gate 環境」守衛(2026-08-03,第 1 輪驗證者 F1 的本體 + 同日在 digest_selfheal 查到的實鍋)。
#
# 病灶(兩支自動修 runner 同款):修復代理在**拋棄式 git worktree** 裡跑一份 gate 測試清單,
# 全過才准 apply。worktree 只含 tracked 檔 —— `logs/`、`.env` 都被 .gitignore 擋在外面。
# 清單裡只要有一支依賴這些東西,它在 worktree 內**恆紅** → guard 永遠 blocked_tests →
# 自動修永遠到不了 apply。而外觀完全正常:fail-closed、每天推播「代理的修復未過測試把關」,
# 沒有任何測試會變紅,沒有任何人會發現這條產線是死的。
#   實例:digest_selfheal 的 gate 有 test_free_llm_only(要 .env 的 GEMINI_API_KEY)→
#   2026-07-24 上線以來,只要它真的修好過任何東西,都會被當成「修不好」丟掉。
#
# 這支就是那個會變紅的測試:用**真 repo 的真 worktree** 跑**生產那幾份 gate 清單**,全綠才算數。
# 各 runner 的沙盒測試驗的是 runner 邏輯(用 stub 測試),證明不了這件事。
set -u
REPO="${MD_REPO:-$HOME/Delvin-agent}"
BASE="${MD_FALLBACK_BASE:-$HOME/.marketdaily-fallback}"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

RUNNERS="digest_chronic_runner.sh digest_selfheal_runner.sh"
FAILS=0
TOTAL=0

WT="/tmp/autofix_gate_env.$$"
git -C "$REPO" worktree add --detach "$WT" HEAD >/dev/null 2>&1 || {
  echo "❌ worktree 建立失敗(無法驗證 gate 環境)"; exit 1; }
cleanup() { git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"
            git -C "$REPO" worktree prune >/dev/null 2>&1 || true; }
trap cleanup EXIT

for rn in $RUNNERS; do
  R="$BASE/$rn"
  if [ ! -f "$R" ]; then
    echo "❌ 找不到 runner:$R(gate 清單無真源,拒絕假綠)"; FAILS=$((FAILS+1)); continue
  fi
  # 清單的唯一真源 = runner 自己的 GATE_TESTS="...";解析不到 = 有人改寫了結構,必須有人知道
  GATE_LIST=$(sed -n '/^GATE_TESTS="/,/"$/p' "$R" | sed 's/^GATE_TESTS="//; s/"$//')
  if [ -z "$GATE_LIST" ]; then
    echo "❌ $rn:解析不到 GATE_TESTS(清單改寫成別的形式?這支守衛就瞎了)"; FAILS=$((FAILS+1)); continue
  fi
  echo "$rn(gate $(echo $GATE_LIST | wc -w) 支):"
  for t in $GATE_LIST; do
    TOTAL=$((TOTAL+1))
    if [ ! -f "$WT/scripts/$t.py" ]; then
      echo "  ✗ $t —— 檔案不在版控內(worktree 裡沒有它,gate fail-closed 判紅)"
      FAILS=$((FAILS+1)); continue
    fi
    out=$( cd "$WT" && MD_CHRONIC_REAL_LOGS="$REPO/logs" "$PY" "scripts/$t.py" 2>&1 ); rc=$?
    if [ "$rc" = 0 ]; then
      echo "  ✓ $t"
    else
      echo "  ✗ $t rc=$rc"
      echo "$out" | tail -6 | sed 's/^/      /'
      FAILS=$((FAILS+1))
    fi
  done
  # 每支 runner 都必須有 baseline 閘:沒有的話,「gate 環境壞了」會一直偽裝成「代理修不好」
  grep -q 'baseline gate' "$R" || {
    echo "  ✗ $rn 沒有 baseline gate(未修改的 worktree 先驗一次),gate 壞掉時會偽裝成代理修不好"
    FAILS=$((FAILS+1)); }
done

if [ "$FAILS" = 0 ]; then
  echo "全過($TOTAL 支):自動修的 gate 在乾淨 worktree 裡是綠的(baseline 可達,apply 這條路走得通)"
  exit 0
fi
echo "❌ $FAILS 項未過 —— 對應的自動修永遠不可能 apply,先修 gate 環境"
exit 1
