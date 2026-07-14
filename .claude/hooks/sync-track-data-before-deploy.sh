#!/usr/bin/env bash
# PreToolUse(Bash)hook:部署 docs 到 Cloudflare Pages 前,自動用 origin 最新版覆蓋
# winrig 管理的資料檔,防止本地舊檔蓋掉線上新資料。
#
# 坑(memory project_track_record_definition / feedback_marketdaily_priority):
#   winrig 每天 08:00 TW 重建 docs/data/track-record.json(含 board.json)→ commit+push+部署。
#   若之後有人從 Mac 手動 `wrangler pages deploy docs` 而本地這幾個 json 落後 origin,
#   就會把 winrig 剛部署的最新戰績/看板 json 蓋回舊版 → 首頁戰績卡片 + /track-record 回歸。
#   以前靠「記得先 git pull」防守=不可靠。改成部署前自動同步,不需任何人記得。
#
# 行為:非阻擋型,一律 exit 0。只在偵測到 wrangler pages deploy docs 時動作;
#       fetch 失敗就沿用本地(不比現況差);只覆蓋工作區檔案、不動 git index。

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception:
    print("")
' 2>/dev/null)"

# 只在「部署 docs 到 Pages」時才動作,其餘 Bash 呼叫立即放行(零副作用)
printf '%s' "$CMD" | grep -qiE 'wrangler +pages +deploy +docs' || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$ROOT" ] && exit 0

git -C "$ROOT" fetch origin main -q 2>/dev/null || true

# winrig cron 每日自動 commit 的資料檔(source of truth 在 winrig,Mac 絕不手改)
SYNCED=""
for f in docs/data/track-record.json docs/data/board.json; do
  tmp="$(mktemp)"
  if git -C "$ROOT" show origin/main:"$f" > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
    if ! cmp -s "$tmp" "$ROOT/$f" 2>/dev/null; then
      mv "$tmp" "$ROOT/$f"
      SYNCED="$SYNCED $f"
    else
      rm -f "$tmp"
    fi
  else
    rm -f "$tmp"
  fi
done

[ -n "$SYNCED" ] && echo "✅ 部署前已從 origin 同步最新資料(防蓋掉 winrig 新版):$SYNCED" >&2
exit 0
