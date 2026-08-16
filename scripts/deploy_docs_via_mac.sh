#!/usr/bin/env bash
# 第三條部署腿:SSH 到 Mac,用 Mac 上那把 wrangler OAuth 發 docs。
#
# 為什麼存在(2026-08-16):leg1(winrig 本機 wrangler)沒有任何憑證、leg2(GitHub Actions)是
# 帳號層停用("Actions has been disabled for this user",permissions 端點還謊報 enabled:true),
# 兩條腿同時死了三天,pending 單堆到自癒額度用滿。當時的結論是「只有 Delvin 能修」——
# 但 Mac 上一直躺著一把有效的 wrangler OAuth(pages write),winrig→Mac 的 SSH 也早就通
# (brain_deliver_mac.sh 天天在用)。這支就是把那條路接起來。
#
# 契約與 leg2 相同(cron_deploy_docs 依此判斷):
#   0 = 已部署並驗證   2 = docs/ 與 origin/main 有落差(呼叫端登記 pending)
#   5 = 這條腿不可用(Mac 睡著/不可達/沒 node/沒 OAuth)  其他 = 部署失敗
#
# 鐵則:發的是 **origin/main 的 docs**(git archive),不是本機工作樹——
# 從髒工作樹或 feature branch 整包發會把 production 蓋成舊檔(L1 事故)。
set -uo pipefail

REPO_DIR="${MD_REPO:-$HOME/Delvin-agent}"
MAC="${DEPLOY_MAC_HOST:-delvin@100.78.136.77}"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15"
MAC_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
REASON="${1:-manual deploy via mac}"
VERIFY_URL="${2:-}"
REMOTE_DIR="/tmp/md_deploy_$$"

log() { echo "[deploy_via_mac] $*"; }
cleanup() { ssh $SSH_OPTS "$MAC" "rm -rf '$REMOTE_DIR'" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cd "$REPO_DIR" || { log "找不到 repo $REPO_DIR"; exit 5; }

# ---- 這條腿活著嗎(三態:活/不可達/缺件,不可壓成同一種) ----
if ! ssh $SSH_OPTS "$MAC" "true" >/dev/null 2>&1; then
  log "❌ Mac 不可達(睡眠或網路斷)——這條腿本輪不可用,非部署失敗"
  exit 5
fi
if ! ssh $SSH_OPTS "$MAC" "export PATH=$MAC_PATH; command -v node >/dev/null && [ -f ~/Library/Preferences/.wrangler/config/default.toml ]" >/dev/null 2>&1; then
  log "❌ Mac 上缺 node 或 wrangler OAuth 憑證"
  exit 5
fi

# ---- 落差判斷:Actions 與本腿都只發得出 origin/main ----
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

# ---- 送內容過去,並對「檔案數」驗收(截斷的傳輸不可以被當成成功) ----
expect=$(git ls-tree -r --name-only origin/main -- docs | wc -l)
[ "$expect" -gt 100 ] || { log "❌ origin/main 的 docs 只有 $expect 個檔,拒發(疑似 ref 解析錯誤)"; exit 3; }
log "送出 origin/main 的 docs($expect 檔)→ $MAC:$REMOTE_DIR"
if ! git archive --format=tar origin/main docs | ssh $SSH_OPTS "$MAC" "mkdir -p '$REMOTE_DIR' && tar x -C '$REMOTE_DIR'"; then
  log "❌ 傳輸失敗"; exit 3
fi
got=$(ssh $SSH_OPTS "$MAC" "find '$REMOTE_DIR/docs' -type f | wc -l" 2>/dev/null | tr -d ' \r')
if [ "${got:-0}" != "$expect" ]; then
  log "❌ 對岸只收到 ${got:-0} 個檔,應為 $expect —— 傳輸不完整,拒絕部署(整站上傳會把缺的檔從線上砍掉)"
  exit 3
fi
log "對岸檔案數驗收通過($got/$expect)"

# ---- 部署 ----
out=$(ssh $SSH_OPTS "$MAC" "export PATH=$MAC_PATH; cd '$REMOTE_DIR' && npx --yes wrangler@4 pages deploy docs \
  --project-name marketdaily --branch=main --commit-dirty=true --commit-message \"$(printf '%s' "$REASON" | tr -d '\"')\" 2>&1")
rc=$?
echo "$out" | tail -6
if [ "$rc" -ne 0 ]; then
  log "❌ Mac 端 wrangler 失敗 rc=$rc"; exit "$rc"
fi

url=$(echo "$out" | grep -oE 'https://[a-z0-9]+\.marketdaily\.pages\.dev' | tail -1)
if [ -z "$url" ]; then
  log "❌ 沒解析到部署網址——不確定有沒有發出去,當失敗處理"; exit 4
fi
code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$url/" || echo 000)
if [ "$code" != "200" ]; then
  log "❌ 部署網址 $url 回 $code"; exit 4
fi
log "✅ 已部署並驗證:$url"
if [ -n "$VERIFY_URL" ]; then
  vcode=$(curl -sL -o /dev/null -m 30 -w '%{http_code}' "$VERIFY_URL" || echo 000)
  log "verify $VERIFY_URL → $vcode"
  [ "$vcode" = "200" ] || exit 4
fi
exit 0
