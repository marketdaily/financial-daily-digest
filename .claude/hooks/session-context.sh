#!/usr/bin/env bash
# SessionStart hook:把跨視窗的近況灌進新 session 的上下文。
# 目的:用戶常同時開多個 Claude 視窗,新視窗一開就要知道別的視窗剛做了什麼,
# 用戶一提「那個」就能接上,不用再問是哪一個。
set -euo pipefail

# 自動偵測本機的專案路徑(Mac / winrig 共用同一支腳本)
REPO=""
for c in "/Users/delvin/Downloads/Delvin agent" "/home/userdelvin/Delvin-agent"; do
  [ -d "$c" ] && REPO="$c" && break
done
[ -z "$REPO" ] && exit 0
cd "$REPO" 2>/dev/null || exit 0

echo "=== 跨視窗近況(SessionStart 自動注入) ==="

echo "--- 最近 8 筆 git commit ---"
git log -8 --format="%h %cd %s" --date=format:"%m/%d %H:%M" 2>/dev/null || true

UNCOMMITTED="$(git status --short 2>/dev/null | grep -vE '^\?\?' || true)"
if [ -n "$UNCOMMITTED" ]; then
  echo "--- ⚠️ 有未 commit 的改動(可能是另一個視窗正在進行,動它之前先確認) ---"
  echo "$UNCOMMITTED"
fi

# --- 其他視窗最近的對話(自動抽取,不靠手動 WORKLOG) ---
PROJDIR="$HOME/.claude/projects/$(printf '%s' "$REPO" | sed 's#[/ ]#-#g')"
if [ -d "$PROJDIR" ]; then
  python3 - "$PROJDIR" <<'PY' 2>/dev/null || true
import sys, os, glob, json, time, datetime
d = sys.argv[1]
files = sorted(glob.glob(os.path.join(d, '*.jsonl')), key=os.path.getmtime, reverse=True)
now = time.time()
out = []
shown = 0
for f in files:
    if now - os.path.getmtime(f) < 20:   # 跳過剛建立的本視窗
        continue
    prompts = []
    try:
        for line in open(f, encoding='utf-8'):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('type') != 'user':
                continue
            c = (o.get('message') or {}).get('content')
            if not isinstance(c, str):
                continue
            t = c.strip().replace('\n', ' ')
            if not t or t[0] == '<' or t.startswith('[Request interrupted') \
               or 'system-reminder' in t or t.startswith('Caveat:') \
               or t.startswith('Continue from where'):
                continue
            prompts.append(t[:100])
    except Exception:
        continue
    if not prompts:
        continue
    ts = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime('%m/%d %H:%M')
    out.append('• 視窗[%s] 最近講的:' % ts)
    for p in prompts[-4:]:
        out.append('    - ' + p)
    shown += 1
    if shown >= 3:
        break
if out:
    print('--- 其他視窗最近的對話(你說「那個/剛剛」時先看這裡) ---')
    print('\n'.join(out))
PY
fi

if [ -f "$REPO/WORKLOG.md" ]; then
  echo "--- WORKLOG.md 最近 25 行(各視窗開工/收工紀錄) ---"
  tail -n 25 "$REPO/WORKLOG.md" 2>/dev/null || true
fi

echo "=== 規則:做非小事先在 WORKLOG.md 寫一條(日期+在做什麼);改完立刻 commit,別留 working tree 被別的視窗洗掉 ==="
exit 0
