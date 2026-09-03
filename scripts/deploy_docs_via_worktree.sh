#!/usr/bin/env bash
# deploy_docs_via_worktree.sh "<原因>" [verify_url]
#
# 部署 docs/ 的**本機 origin/main 腿**(2026-09-03):用 winrig 本機的 wrangler 憑證,但發的是
# `git archive origin/main -- docs`(乾淨匯出),**不是磁碟現狀**。
#
# 為什麼存在:deploy_drift 自癒原本只綁 GitHub Actions 那條腿(pages_deploy.yml),而那條腿
# 08-13 與 09-03 兩度死於帳號層「Actions has been disabled for this user」——本機 wrangler
# 明明活著(API token),自癒卻沒有任何一條腿能用。cron_deploy_docs 的 leg1 不能拿來自癒,
# 因為它上傳磁碟現狀:別視窗的 WIP 會被一起發上線(L1 事故)。這支補上「本機憑證 × origin 內容」
# 這個缺角。
#
# 契約與 deploy_docs_via_actions.sh / deploy_docs_via_mac.sh 相同(cron_deploy_docs / deploy_drift 依此判斷):
#   0 = 已部署並驗證   2 = docs/ 與 origin/main 有落差(DEPLOY_ALLOW_DRIFT=1 可無視)
#   5 = 這條腿不可用(wrangler 憑證死/沒 node)  3 = origin ref 異常拒發   4 = 部署或線上驗證失敗
set -u
REASON="${1:-manual}"; VERIFY_URL="${2:-}"
REPO_DIR="${REPO_DIR:-$HOME/Delvin-agent}"
PROJECT="${PAGES_PROJECT:-marketdaily}"
BASE_URL="${DEPLOY_BASE_URL:-https://marketdaily.ai}"
log() { echo "[deploy_via_worktree] $*"; }
cd "$REPO_DIR" || { log "找不到 repo $REPO_DIR"; exit 5; }
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
command -v node >/dev/null 2>&1 || { log "❌ 沒有 node,這條腿不可用"; exit 5; }
# 憑證來源沿用 lib(.env 的 CLOUDFLARE_API_TOKEN → 環境變數 → Mac 借用),**不在這裡再抄一份**
# (同一段憑證邏輯手刻 N 份正是 08-11 三天停機的成因)。cron 環境是非互動的,沒這行 wrangler 直接拒跑。
# shellcheck disable=SC1090
CRON_LIB_REPO="$REPO_DIR" . "$REPO_DIR/scripts/lib_cron_runner.sh" 2>/dev/null || true
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || _cron_export_cf_token_mac 2>/dev/null || true

# 憑證活體檢查(「有」≠「能」):whoami 失敗就是這條腿死了,不是內容的問題
if ! timeout 60 npx wrangler whoami 2>&1 | grep -q "Account ID\|logged in"; then
  log "❌ wrangler 憑證不可用(whoami 失敗)——這條腿本輪不可用"
  exit 5
fi

git fetch origin main -q 2>/dev/null || log "警告:git fetch 失敗,落差判斷可能過期"
drift=""
git diff --quiet origin/main -- docs/ 2>/dev/null || drift="tracked"
if [ -n "$(git status --porcelain -uall docs/ 2>/dev/null | head -1)" ]; then
  drift="${drift:+$drift+}worktree"
fi
if [ -n "$drift" ]; then
  if [ "${DEPLOY_ALLOW_DRIFT:-0}" = "1" ]; then
    log "⚠️ docs/ 與 origin/main 有落差($drift),DEPLOY_ALLOW_DRIFT=1 照跑,線上會是 origin 版本"
  else
    log "❌ docs/ 與 origin/main 有落差($drift):本腿只發得出 origin 版本,先 commit+push"
    exit 2
  fi
fi

expect=$(git ls-tree -r --name-only origin/main -- docs | wc -l)
[ "$expect" -gt 100 ] || { log "❌ origin/main 的 docs 只有 $expect 個檔,拒發(疑似 ref 解析錯誤)"; exit 3; }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/md_docs_origin.XXXXXX") || exit 4
trap 'rm -rf "$TMP"' EXIT
git archive origin/main -- docs | tar -x -C "$TMP" || { log "❌ git archive origin/main 失敗"; exit 4; }
got=$(find "$TMP/docs" -type f | wc -l)
[ "$got" -eq "$expect" ] || { log "❌ 匯出檔數 $got ≠ origin $expect,拒發"; exit 4; }
log "origin/main docs 匯出 $got 檔 → wrangler pages deploy(project=$PROJECT reason=$REASON)"

# 從 repo 目錄跑 npx(用 repo 自己的 node_modules/wrangler),只把匯出目錄當上傳來源
out=$(timeout 600 npx wrangler pages deploy "$TMP/docs" --project-name "$PROJECT" \
        --branch=main --commit-dirty=true --commit-message "$REASON" 2>&1)
rc=$?
printf '%s\n' "$out" | tail -4
[ "$rc" -eq 0 ] || { log "❌ wrangler pages deploy rc=$rc"; exit 4; }

# 線上驗證:首頁必 200;verify_url 跟隨 308(存檔頁活著時 CF 回 308→200)
sleep 8
code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$BASE_URL/?cb=$RANDOM" || echo 000)
[ "$code" = "200" ] || { log "❌ 部署後首頁 $BASE_URL → $code"; exit 4; }
if [ -n "$VERIFY_URL" ]; then
  vcode=$(curl -sL -o /dev/null -m 30 -w '%{http_code}' "$VERIFY_URL?cb=$RANDOM" || echo 000)
  log "verify $VERIFY_URL → $vcode"
  [ "$vcode" = "200" ] || exit 4
fi
log "✅ origin/main docs 已上線並驗證"
exit 0
