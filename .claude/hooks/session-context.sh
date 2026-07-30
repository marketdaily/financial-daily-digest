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
now_dt = datetime.datetime.now(datetime.timezone.utc)
RECENT_CUTOFF_SEC = 24 * 3600  # 超過24小時的真人對話不當「最近」顯示,避免資訊過時誤導
HUMAN_SOURCES = ('typed', 'queued')  # 排除 tool_result 回饋/自主引擎 sdk-cli 注入/task通知
out = []
shown = 0
for f in files:
    if now - os.path.getmtime(f) < 20:   # 跳過剛建立的本視窗
        continue
    prompts = []
    latest_ts = None
    try:
        for line in open(f, encoding='utf-8'):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('type') != 'user' or o.get('promptSource') not in HUMAN_SOURCES:
                continue
            c = (o.get('message') or {}).get('content')
            if not isinstance(c, str):
                continue
            t = c.strip().replace('\n', ' ')
            if not t or t[0] == '<' or t.startswith('[Request interrupted') \
               or 'system-reminder' in t or t.startswith('Caveat:') \
               or t.startswith('Continue from where'):
                continue
            try:
                rec_ts = datetime.datetime.fromisoformat(o.get('timestamp', '').replace('Z', '+00:00'))
            except ValueError:
                continue
            prompts.append(t[:100])
            if latest_ts is None or rec_ts > latest_ts:
                latest_ts = rec_ts
    except Exception:
        continue
    if not prompts or latest_ts is None:
        continue
    if (now_dt - latest_ts).total_seconds() > RECENT_CUTOFF_SEC:
        continue
    ts = latest_ts.astimezone().strftime('%m/%d %H:%M')
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

# --- 🤖 自主進步機器近況(只在 winrig 有 ~/autonomous) ---
AUTO="$HOME/autonomous"
if [ -d "$AUTO" ]; then
  CAPS=$(grep -cE '^- 建立：[0-9]' "$AUTO/capabilities/INDEX.md" 2>/dev/null || echo 0)
  CYC=$(grep -cE '^\- \[' "$AUTO/autonomous_log.md" 2>/dev/null || echo 0)
  echo "--- 🤖 自主機器近況 ---"
  echo "能力庫 ${CAPS} 積木 · 累計 ${CYC} 輪值班。最近做的:"
  grep -E '^\- \[' "$AUTO/autonomous_log.md" 2>/dev/null | tail -n 2 | sed 's/^/  /' | cut -c1-160

  # ⚔️ 防打架(Delvin 2026-07-30 親令):機器「正在做/排隊中」的任務直接亮給每個新視窗——
  # 你要動的東西若跟下面重疊,先查它進度(斷點檔+WORKLOG),別重做一份撞車;
  # 反之你做掉了它排隊的事,把 state/current_task.md 改成 idle+一行說明,機器接手前會重讀。
  if grep -q "STATUS: in_progress" "$AUTO/state/current_task.md" 2>/dev/null; then
    echo "--- ⚔️ 機器手上的任務(in_progress,動同一塊前先看這裡防打架) ---"
    head -n 10 "$AUTO/state/current_task.md" | sed 's/^/  /' | cut -c1-200
  fi

  # 🌙 用戶不在時(睡覺/外出)機器完成的事——Delvin 2026-07-07 親令:睡醒開視窗要直接看到
  # 「額度刷新後接手做完了什麼」,不用每次開口問。列近 18 小時值班報告的標題(舊→新,最多 12 筆)。
  NIGHT=$(find "$AUTO/reports" -name '*.md' -mmin -1080 2>/dev/null | sort | tail -n 12)
  if [ -n "$NIGHT" ]; then
    echo "--- 🌙 你不在時完成的(近18h值班報告,舊→新;⚠️這段是給用戶看的,回覆開頭原樣轉述給他) ---"
    while IFS= read -r f; do
      ts=$(basename "$f" .md | sed -nE 's/^[0-9-]+_([0-9]{2})([0-9]{2})_.*/\1:\2/p')
      title=$(grep -m1 -E '^# ' "$f" 2>/dev/null \
        | sed -E 's/^# *//; s/^學習報告 ?· ?//; s/^[0-9-]+ [0-9:]+ TW ?· ?//')
      [ -z "$title" ] && title=$(basename "$f" .md)
      echo "  · [${ts:-??:??}] ${title:0:70}"
    done <<< "$NIGHT"
  fi
  echo "  ⓘ 用戶問「你(昨天/上次到現在)學了什麼」→ 跑 \`bash ~/autonomous/report.sh\` 給①增量②累計兩層報告。"
fi

echo "=== 規則:做非小事先在 WORKLOG.md 寫一條(日期+在做什麼);改完立刻 commit,別留 working tree 被別的視窗洗掉 ==="
exit 0
