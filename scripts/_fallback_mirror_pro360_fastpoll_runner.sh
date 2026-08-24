#!/bin/bash
# PRO360 快速輪詢(2026-08-17):每 15 分鐘掃「配對案件」第 1 頁,新網站案立刻推播老闆(不扣點)。
# 為什麼要快:08-17 王〇生一頁式購物網站案 14:23 寄通知,15:15 已「無法查看」——PRO360 網站案的聯繫名額 1 小時內就滿,
# 每天 09:30 的雷達完全來不及。與 09:30 全量跑共用 seen 檔,不重推。
set -u
REPO="$HOME/Delvin-agent"; SF="$HOME/storefront"; PY=python3
source "$REPO/scripts/lib_cron_runner.sh"
cd "$SF" || exit 1
SEEN="$HOME/.marketdaily-fallback/.pro360_seen_ids"; touch "$SEEN"
poll() {
  out=$("$PY" growth/pro360_radar.py --pages 1 2>&1); rc=$?
  echo "$out" | tail -3
  echo "$out" | grep -q "SESSION EXPIRED" && { MD_REPO="$REPO" "$REPO/.venv/bin/python" "$HOME/.marketdaily-fallback/notify_admin.py" "🔴 PRO360 快速輪詢:登入 session 過期,需重新登入" || true; return 3; }
  [ "$rc" -eq 0 ] || return "$rc"
  f=$(ls -t "$SF"/growth/out/pro360_cases_*.json | head -1)
  msg=$("$REPO/.venv/bin/python" - "$f" "$SEEN" <<'PYEOF'
import json,sys
d=json.load(open(sys.argv[1])); seen=set(open(sys.argv[2]).read().split())
new=[c for c in d["web"] if c["id"] not in seen and c["cat"] and any(k in c["cat"] for k in ("網站","網頁","架設","電商","購物","APP","UI","LINE","官網"))]
open(sys.argv[2],"a").write("".join(c["id"]+"\n" for c in new))
if new: print(f"⚡ PRO360 新網站案 {len(new)} 件(名額 1 小時內就滿,要回快說):\n"+"\n".join(f"• {c['cat']}｜{c['area']}｜預算 {c['budget'] or '未填'}｜扣 ${c['cost']}｜{c['url']}" for c in new[:5]))
PYEOF
)
  [ -n "$msg" ] && MD_REPO="$REPO" "$REPO/.venv/bin/python" "$HOME/.marketdaily-fallback/notify_admin.py" "$msg"
  # 老闆 08-17 令:簡單網站案零成本能做,收到第一時間搶 → 規則內自動報價(扣點),結果推播
  [ -f "$HOME/.marketdaily-fallback/pro360_autoquote.DISABLED" ] && return 0
  # 2026-08-19 老闆儲值 $6,000 後放寬:上限 $400 會跳過「五萬到十萬」這種好案(它的扣點是 $508)。
  # 判準是「扣點佔案子最低營收的比例」——$600 對一件 $50,000 的案是 1.2%,對 $15,000 也才 4%。
  aq=$(PRO360_MAX_COST="${PRO360_MAX_COST:-600}" "$PY" growth/pro360_autoquote.py 2>&1); echo "$aq" | tail -4
  q=$(echo "$aq" | grep -E "^(QUOTED|FAILED) " | head -5)
  [ -n "$q" ] && MD_REPO="$REPO" "$REPO/.venv/bin/python" "$HOME/.marketdaily-fallback/notify_admin.py" "🎯 PRO360 自動報價結果:
$q
(FAILED 多半=餘額不足或名額已滿;帳本 growth/out/pro360_quoted.jsonl)"
  return 0
}
cron_run_and_alert "pro360_fastpoll" poll
