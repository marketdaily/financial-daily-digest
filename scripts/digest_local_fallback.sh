#!/bin/zsh
# MarketDaily 日報本機備援 runner(bash/zsh 通用語法)
# ⚠️ launchd 背景程序被 TCC 擋在 ~/Downloads 外(bash 126/zsh 127 Operation not permitted),
# 所以 launchd 跑的是 ~/.marketdaily-fallback/repo(Downloads 外的獨立 clone)裡的本檔;
# 腳本用自身位置定位 repo root,每輪先 git pull 同步最新管線碼。
#
# 背景:2026-06-12 GitHub 帳號被 flag(shadow-ban),Actions 全面停用,
# 雲端管線(digest-cron worker → daily_digest.yml)斷線,日報寄不出去。
# launchd(com.marketdaily.digest-fallback)於 06:20 / 19:25 TW 觸發本腳本。
#
# 防重複寄送:先查 GitHub 當班是否已有 workflow run(公開 repo 免 token)。
# 有 run = 帳號已復活、雲端已接手 → 本機直接退出讓位,Actions 恢復後毋須拆除本機制。
# 寄出時間由 main.py _hold_until_send_time 釘在 07:00 / 20:00 TW 整點,與雲端一致。

set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
if [ -n "${ZSH_VERSION:-}" ]; then SELF="${(%):-%x}"; else SELF="${BASH_SOURCE[0]}"; fi
cd "$(dirname "$SELF")/.." || exit 1

# safe_pull：取代裸 `git pull --autostash`。只在 tracked 檔案完全乾淨(不含 untracked ??)時
# 才 pull --rebase，有殘留別人的未 commit 修改就跳過，絕不 autostash 動別人的工作
# (同 scripts/lib_cron_runner.sh::cron_safe_pull 的邏輯，這支腳本是 bash/zsh 通用檔獨立實作)。
safe_pull() {
  if ! git status --porcelain 2>/dev/null | grep -qv '^??'; then
    git pull --rebase origin main 2>/dev/null
  fi
}

# launchd 每 10 分鐘喚醒一次(時區無關);只在台灣時間班次窗口內動工:
#   早報窗 06:20-06:49(對齊 digest-cron 06:20)、晚報窗 19:25-19:54(對齊 19:25)
TWH=$((10#$(TZ=Asia/Taipei date +%H)))
TWM=$((10#$(TZ=Asia/Taipei date +%M)))
TWDOW=$(TZ=Asia/Taipei date +%u)   # 1=Mon .. 7=Sun
TWDATE=$(TZ=Asia/Taipei date +%Y-%m-%d)
HM=$((TWH * 60 + TWM))
if [ "$HM" -ge 380 ] && [ "$HM" -lt 410 ]; then MARKET=tw
elif [ "$HM" -ge 1165 ] && [ "$HM" -lt 1195 ]; then MARKET=us
else exit 0; fi

# 當日當班鎖:同一窗口內 10 分鐘輪詢只跑第一次(mkdir 原子性)
LOCK_DIR="logs/locks"; mkdir -p "$LOCK_DIR"
if ! mkdir "$LOCK_DIR/$TWDATE.$MARKET" 2>/dev/null; then exit 0; fi

LOG_DIR="logs"
exec >> "$LOG_DIR/fallback_$TWDATE.log" 2>&1
echo "=== $(date '+%F %T %z') fallback runner start (market=$MARKET) ==="

# 週末 skip,同 digest-cron resolveSchedule:週日早報 skip(週六照發 recap);週六/日晚報 skip
if [ "$MARKET" = tw ] && [ "$TWDOW" = 7 ]; then echo "skip: Sunday TW morning"; exit 0; fi
if [ "$MARKET" = us ] && { [ "$TWDOW" = 6 ] || [ "$TWDOW" = 7 ]; }; then echo "skip: weekend US evening"; exit 0; fi

cloud_run_count() {
  python3 - "$MARKET" <<'PY'
import json, subprocess, sys, urllib.request, datetime
market = sys.argv[1]
d = datetime.datetime.now(datetime.timezone.utc)
# 班次窗口起點同 watchdog shiftWindowStart:tw 班 22:00 UTC 起、us 班 11:00 UTC 起
if market == "tw":
    if d.hour < 22:
        d -= datetime.timedelta(days=1)
    start = d.replace(hour=22, minute=0, second=0, microsecond=0)
else:
    start = d.replace(hour=11, minute=0, second=0, microsecond=0)
path = ("/repos/marketdaily/financial-daily-digest/actions/workflows/daily_digest.yml"
        "/runs?per_page=5&created=%3E%3D" + start.strftime("%Y-%m-%dT%H:%M:%SZ"))
# 帳號被 flag 期間 repo 連未認證讀都 404,要先用 gh(帶認證);gh 不行再裸打
try:
    out = subprocess.run(["gh", "api", path], capture_output=True, timeout=30)
    if out.returncode == 0:
        print(len(json.loads(out.stdout).get("workflow_runs", [])))
        sys.exit(0)
except Exception:
    pass
try:
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "User-Agent": "md-local-fallback", "Accept": "application/vnd.github+json"})
    data = json.load(urllib.request.urlopen(req, timeout=20))
    print(len(data.get("workflow_runs", [])))
except Exception as e:
    print(f"ERR {e}")
PY
}

# 三次讓位檢查(0/60/120 秒):雲端 dispatch 在同分鐘發生,run 幾秒內就會出現
for wait in 0 60 120; do
  sleep "$wait"
  n=$(cloud_run_count)
  echo "cloud run check (market=$MARKET): $n"
  if [ "$n" != "0" ] && [[ "$n" != ERR* ]]; then
    echo "cloud has taken over -> yield, exit"
    exit 0
  fi
done

echo ">>> no cloud run, running digest locally (market=$MARKET)"
safe_pull
MARKET="$MARKET" /usr/bin/python3 main.py
rc=$?
echo "main.py exit=$rc"

push_admin_line() {
  python3 - "$1" <<'PY'
import sys, json, urllib.request, os
from dotenv import dotenv_values
tok = dotenv_values(".env").get("MARKETDAILY_ALERT_TOKEN") or ""
if not tok:
    print("no alert token, skip LINE"); sys.exit(0)
req = urllib.request.Request(
    "https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push",
    data=json.dumps({"message": sys.argv[1]}).encode(),
    headers={"content-type": "application/json", "authorization": "Bearer " + tok},
    method="POST")
try:
    print("LINE push:", urllib.request.urlopen(req, timeout=20).status)
except Exception as e:
    print("LINE push failed:", e)
PY
}

if [ "$rc" != "0" ]; then
  push_admin_line "🔴 [本機備援] $(TZ=Asia/Taipei date +%F) ${MARKET} 班日報本機執行失敗(exit=$rc),GitHub Actions 仍停用,需人工處理"
  exit "$rc"
fi

# 公版日報 archive commit(複製 daily_digest.yml 的 Persist 步驟;個人化版嚴格排除)
if [ -n "${ZSH_VERSION:-}" ]; then setopt null_glob; else shopt -s nullglob 2>/dev/null; fi
rm -f docs/output/*_personal_*
git config user.name "marketdaily-bot"
git config user.email "marketdailyhq@gmail.com"
PERSIST=()
for f in docs/output/digest_*.html; do
  [ -e "$f" ] || continue
  case "$f" in *_personal_*) continue;; esac
  git add "$f" && PERSIST+=("$f")
done
[ -e docs/output/manifest.json ] && git add docs/output/manifest.json 2>/dev/null && PERSIST+=(docs/output/manifest.json)
# analyzer.py 每班寫入的報價快取——digest runner 是唯一 persist owner;沒人收會 tracked-dirty
# 卡死全部 cron_abort_if_dirty 守門 runner(2026-07-17 孤兒檔餓死 cron 生態鏈事故;winrig run.sh 同步修)
[ -e scripts/buy_signal_log.json ] && git add scripts/buy_signal_log.json 2>/dev/null && PERSIST+=(scripts/buy_signal_log.json)
if python3 scripts/gen_sitemap.py; then git add docs/sitemap.xml && PERSIST+=(docs/sitemap.xml); else echo "sitemap gen skipped"; fi
# commit 一律帶 pathspec(2026-07-18):裸 commit 會把別視窗 pre-staged 未 commit 的檔掃進來
if [ "${#PERSIST[@]}" -eq 0 ] || git diff --cached --quiet -- "${PERSIST[@]}"; then
  echo "no new public digest to commit"
else
  git commit -m "chore(digest): persist public archive $(date -u +%Y-%m-%d) (local fallback)" -- "${PERSIST[@]}"
  safe_pull
  git push origin HEAD:main || echo "archive push failed"
fi

# 早班順帶補 weekly_track_record.yml 的活:刷戰績 + 部署 Pages(它的排程也被 Actions 停用波及)
if [ "$MARKET" = tw ]; then
  MARKETDAILY_INTERNAL_TOKEN="$(python3 -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('MARKETDAILY_INTERNAL_TOKEN') or '')")" \
    python3 scripts/build_track_record.py || echo "track record build failed"
  # build_track_record.py 同時寫兩個 tracked ledger 檔——只收 track-record.json 會讓本 clone
  # tracked 樹永遠髒,safe_pull 從此死掉、備援 pipeline 靜默跑舊碼(2026-07-18 fleet_deploy_gate
  # 驗證者 F5;winrig refresh_track_record.sh 的 LEDGER_PATHS 同一組)。zsh/bash 皆可的陣列寫法。
  TR_PERSIST=()
  for f in docs/data/track-record.json scripts/personal_ledger.jsonl scripts/personal_ledger_audit.json; do
    [ -e "$f" ] && TR_PERSIST+=("$f")
  done
  if [ "${#TR_PERSIST[@]}" -gt 0 ] && [ -n "$(git status --short -- "${TR_PERSIST[@]}")" ]; then
    git add -- "${TR_PERSIST[@]}"
    git commit -m "chore(track-record): auto-refresh $(date -u +%Y-%m-%d_%H%M)UTC (local fallback)" -- "${TR_PERSIST[@]}"
    safe_pull
    git push origin HEAD:main || echo "track record push failed"
  fi
  # deploy 面檢查(2026-07-18):deploy 上傳磁碟現狀,自家輸出上面已 pathspec commit 完,
  # 此時 docs/ 殘留 dirty/untracked=別視窗 WIP/草稿——跳過本輪部署(archive 已 commit,
  # 之後任一乾淨班次 deploy 會帶上線)。本檔不 source lib(獨立 clone 通用檔),自包含實作。
  if [ -z "$(git status --porcelain -uall -- docs/ 2>/dev/null)" ]; then
    npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true \
      --commit-message "daily refresh (local fallback)" || echo "pages deploy failed"
    python3 scripts/indexnow_ping.py || echo "indexnow ping skipped"
  else
    echo "docs deploy 面有 WIP/untracked,本輪跳過部署(archive 已 commit)"
  fi
fi

push_admin_line "✅ [本機備援] $(TZ=Asia/Taipei date +%F) ${MARKET} 班日報已由本機 Mac 寄出(GitHub Actions 仍停用中,記得到 https://support.github.com/contact/reinstatement 申訴解鎖)"
echo "=== $(date '+%F %T %z') fallback runner done ==="
