#!/usr/bin/env bash
# deploy_docs_via_actions.sh "<原因>" [verify_url]
#
# 部署 docs/ 的**第二條腿**:走 GitHub Actions(pages_deploy.yml)用 GH secret
# CLOUDFLARE_API_TOKEN 部署,不依賴 winrig 本機的 wrangler OAuth 憑證。
# 背景:2026-08-12 winrig OAuth 憑證死掉 ⇒ 12 支 runner 的 deploy 全啞、公版存檔頁
# 404、零告警(open #270/#284)。本機那條腿死掉時用這條。
#
# ⚠️ Actions 部署的是 **origin/main 上的 docs/**,不是本機磁碟現狀。所以本腳本
#    fail-closed:本機 docs/ 與 origin/main 有落差就拒跑(叫你先 push),
#    絕不靜默部署舊內容——「部署成功但發的是上一版」比部署失敗更難發現。
#    確定要無視落差:DEPLOY_ALLOW_DRIFT=1。
#
# exit 0=部署且線上驗證 200 / 2=本機與 origin 有落差 / 3=dispatch 失敗
#        4=run 失敗或逾時 / 5=前置條件不足(gh 未登入等)
set -uo pipefail

REPO_DIR="${MD_REPO:-$HOME/Delvin-agent}"
WORKFLOW="pages_deploy.yml"
REASON="${1:-manual fallback deploy}"
VERIFY_URL="${2:-}"
POLL_MAX="${DEPLOY_POLL_MAX:-80}"        # 80 × 15s = 20 分鐘上限
GH="${GH_BIN:-gh}"

log() { echo "[deploy_via_actions] $*"; }

# cron 的 PATH 是 /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin —— **不含
# ~/.local/bin,而 gh 就裝在那裡**。2026-08-16 查獲:cron_deploy_docs 退到備援腿時,這支
# 一律停在「gh 未安裝」rc=5,連 dispatch 都沒試過(quality_board_deploy 今天就是這樣)。
# ⭐ 守衛的執行環境不等於我的執行環境:任何靠 PATH 找執行檔的備援路徑,都要自己解絕對路徑,
#    否則它在**最需要它的那一刻**(本機腿已經死了)才第一次暴露自己也是壞的。
_resolve_gh() {
  command -v "$GH" >/dev/null 2>&1 && { command -v "$GH"; return 0; }
  local d
  for d in "$HOME/.local/bin" "$HOME/.npm-global/bin" /usr/local/bin /usr/bin /bin /snap/bin; do
    [ -x "$d/gh" ] && { echo "$d/gh"; return 0; }
  done
  return 1
}

cd "$REPO_DIR" || { log "找不到 repo $REPO_DIR"; exit 5; }
GH="$(_resolve_gh)" || { log "gh 未安裝(PATH 與 ~/.local/bin 等已知位置都找不到)"; exit 5; }
"$GH" auth status >/dev/null 2>&1 || { log "gh 未登入"; exit 5; }

# ---- 落差守衛:Actions 發的是 origin/main ----
git fetch origin main -q 2>/dev/null || log "警告:git fetch 失敗,落差判斷可能過期"
drift=""
git diff --quiet origin/main -- docs/ 2>/dev/null || drift="tracked"
if [ -n "$(git status --porcelain -uall docs/ 2>/dev/null | head -1)" ]; then
  drift="${drift:+$drift+}worktree"
fi
if [ -n "$drift" ]; then
  if [ "${DEPLOY_ALLOW_DRIFT:-0}" = "1" ]; then
    log "⚠️ 本機 docs/ 與 origin/main 有落差($drift),DEPLOY_ALLOW_DRIFT=1 照跑,線上會是 origin 版本"
  else
    log "❌ 本機 docs/ 與 origin/main 有落差($drift):Actions 只發得出 origin 的版本。"
    log "   先把 docs/ commit+push 再跑;確定要發 origin 現況:DEPLOY_ALLOW_DRIFT=1"
    git status --porcelain -uall docs/ 2>/dev/null | head -5
    exit 2
  fi
fi

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "dispatch $WORKFLOW(reason=$REASON verify_url=${VERIFY_URL:-首頁})"
if ! "$GH" workflow run "$WORKFLOW" -f reason="$REASON" -f verify_url="$VERIFY_URL" 2>&1; then
  log "dispatch 失敗"
  exit 3
fi

# ---- 抓這次的 run id(createdAt >= dispatch 時間,防抓到上一次的 run) ----
run_id=""
for _ in $(seq 1 20); do
  sleep 3
  run_id="$("$GH" run list --workflow="$WORKFLOW" --event=workflow_dispatch -L 10 \
    --json databaseId,createdAt \
    --jq "[.[] | select(.createdAt >= \"$started_at\")] | sort_by(.createdAt) | last | .databaseId" 2>/dev/null)"
  [ -n "$run_id" ] && [ "$run_id" != "null" ] && break
  run_id=""
done
if [ -z "$run_id" ]; then
  log "dispatch 了但 20 次輪詢都找不到 run(可能 Actions 排隊中);人工查:gh run list --workflow=$WORKFLOW"
  exit 4
fi
log "run id=$run_id → https://github.com/$("$GH" repo view --json nameWithOwner --jq .nameWithOwner)/actions/runs/$run_id"

# ---- 等完成 ----
status=""; conclusion=""
for _ in $(seq 1 "$POLL_MAX"); do
  read -r status conclusion <<<"$("$GH" run view "$run_id" --json status,conclusion \
    --jq '"\(.status) \(.conclusion // "-")"' 2>/dev/null)"
  [ "$status" = "completed" ] && break
  sleep 15
done

if [ "$status" != "completed" ]; then
  log "❌ 逾時(status=$status),run $run_id 仍在跑"
  exit 4
fi
if [ "$conclusion" != "success" ]; then
  log "❌ run $run_id 結束於 $conclusion"
  "$GH" run view "$run_id" --log-failed 2>/dev/null | tail -30
  exit 4
fi
log "✅ 部署成功(run $run_id),線上驗證已在 workflow 內完成"
exit 0
