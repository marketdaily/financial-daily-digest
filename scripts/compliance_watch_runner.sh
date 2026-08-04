#!/bin/bash
# 法務部生產面合規哨兵(2026-08-04)。每晚 22:10 TW 跑。
#
# 為什麼是 22:10:排在當天所有會改動線上內容的班次【之後】——日報 US 班 21:00 存檔、
# 公版存檔 SEO、社群卡、品質戰情頁都跑完了,才有意義去看「今天結束時線上長什麼樣」。
#
# 只在【狀態轉變】時推播:
#   - 新出現的違規(surface×rule 為鍵)→ 🔴
#   - 之前有、現在沒了 → 🟢(讓 Delvin 知道處理完了,不用自己回頭查)
#   - 規則庫自檢失敗 / 有規則從未被套用(exit 3)→ 🔴 這是「守衛自己壞了」,最高優先
#   - 同一面連續 3 晚抓不到(unknown)→ ⚠️ dead-man,防「網路抖一下就永遠不掃了」
# 天天推「全部乾淨」會把真告警淹掉(同 intel_doctor 的分級精神)。
set -u
REPO="$HOME/Delvin-agent"; PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3
STATE="${COMPLIANCE_WATCH_STATE:-$HOME/.marketdaily-fallback/.compliance_watch_state.json}"
OUT="${COMPLIANCE_WATCH_OUT:-$HOME/.marketdaily-fallback/.compliance_watch_latest.json}"
NOTIFY="${COMPLIANCE_WATCH_NOTIFY:-$HOME/.marketdaily-fallback/notify_admin.py}"
source "$REPO/scripts/lib_cron_runner.sh"
# ⚠️ 自測入口(第三輪驗證者 F10):60 則突變沒有一則碰得到 runner,`exit "$rc"` 若被改回
#    `exit 0` 整份自測仍然全綠。有了這個閘,自測才跑得動整支 runner 去斷言 rc 與推播順序。
#    只有明確設環境變數才會生效,而且會印出來——不可能悄悄在生產打開。
if [ "${COMPLIANCE_WATCH_SELFTEST:-0}" = "1" ]; then
  echo "⚠️ SELFTEST 模式:略過時間閘與每日鎖(不可用於生產)"
else
  cron_time_gate "22:10" "22:30"
  cron_daily_lock "compliance_watch"
fi
cd "$REPO" || exit 1

SCAN_CMD=${COMPLIANCE_WATCH_CMD:-"$PY -m legal.compliance_watch"}
# 刻意不加引號:這裡要的就是分詞(自測會用 stub 指令替換掉掃描器)
# shellcheck disable=SC2086
$SCAN_CMD --json > "$OUT" 2>/dev/null
rc=$?
if [ ! -s "$OUT" ]; then
  # 哨兵自己掛掉也要看得見,否則就是「守衛自己是啞的」那個坑再演一次
  MD_REPO="$REPO" "$PY" "$NOTIFY" \
    "🔴 法務合規哨兵無法執行(rc=$rc,無輸出) $(TZ=Asia/Taipei date '+%F %H:%M') — 查 legal/compliance_watch.py" \
    || echo "$(date '+%F %T') ⚠️ 哨兵失敗告警推播也失敗" >&2
  exit 1
fi

MSG=$("$PY" - "$OUT" "$STATE" "$STATE.pending" <<'PYEOF'
import json, sys, os

cur = json.load(open(sys.argv[1], encoding="utf-8"))
prev = {}
if os.path.exists(sys.argv[2]):
    try:
        prev = json.load(open(sys.argv[2], encoding="utf-8"))
    except Exception:
        prev = {}

open_keys, detail = {}, {}
unknown_now = []
scanned = set()          # "surface_id:url" —— 這晚真的成功掃過的子頁
for s in cur.get("surfaces", []):
    if s["status"] == "unknown":
        unknown_now.append(s["id"])
    for u in s.get("scanned", []):
        scanned.add(f"{s['id']}:{u}")
    for f in s.get("findings", []):
        # ⚠️ 去重鍵必須含子頁網址(2026-08-05 驗證者 F8):覆蓋面擴到 223 頁之後,209 頁擠在
        #    3 個 html_multi surface 底下共用一個 surface:rule 鍵——第一頁違規推播過後,
        #    **另外 140 頁出現同一條規則的新違規完全不會有人知道**,修好第一頁也不會有 🟢。
        k = f"{s['id']}:{f.get('url') or s['id']}:{f['rule']}"
        open_keys[k] = True
        detail[k] = (f"[{f.get('severity','?')}] {s['label']} — {f.get('title') or f['rule']}"
                     + (f"\n  頁面:{f['url']}" if f.get("url") else "")
                     + f"\n  法源:{f.get('law','')[:70]}\n  證據:{f.get('evidence','')[:140]}")

prev_keys = set(prev.get("open", []))
prev_streak = prev.get("unknown_streak", {})
streak = {sid: prev_streak.get(sid, 0) + 1 for sid in unknown_now}

new = [k for k in open_keys if k not in prev_keys]
# ⚠️ 「不見了」≠「修好了」(第三輪驗證者 F8):鍵消失也可能是那一頁這晚抓不到。
#    Delvin 的結案流程就是看這則 🟢,把失明回報成已修復是最貴的一種假訊息。
#    只有「該子頁這晚真的被掃過而且沒再命中」才算排除;其餘保留 open 鍵(fail-closed)。
gone, unverified = [], []
for k in prev_keys:
    if k in open_keys:
        continue
    sid, rest = k.split(":", 1)
    url = rest.rsplit(":", 1)[0]
    (gone if f"{sid}:{url}" in scanned else unverified).append(k)
for k in unverified:
    open_keys.setdefault(k, True)   # 沒被證實修好之前不准從帳上消失
# ⚠️ exit 3 也要週期重推(驗證者 F5):原本只在「轉變成 exit 3」那一次推,而 exit 3 的路徑是
# **提早 return、surfaces 為空**——之後每晚都沒掃、每晚都靜默,連 unknown dead-man 都救不了
# (streak 從空 surfaces 算出來會被清成 0)。守衛自己壞掉本來就該一直吵。
cfg_n = (prev.get("cfg_streak", 0) + 1) if cur.get("exit") == 3 else 0
broke = cfg_n == 1 or (cfg_n >= 3 and cfg_n % 3 == 0)
# ⚠️ 週期重推,不是「恰好第 3 晚推一次」:一次性告警等於「這一面從此永遠沒人看,
# 而且再也不會有人提醒你」——2026-08-04 驗證者 F11 指出有真金流的命書定價面正屬此類。
dead = [sid for sid, n in streak.items() if n >= 3 and n % 3 == 0]   # 第 3/6/9… 晚各推一次

# 觀測性劣化(驗證者 F6):這些訊號原本只印在 render() 的人看路徑上,而生產走的是 --json,
# 所以「9 個超長字串沒進語料 / 一條規則沒跑到 / 全站英文語料消失 / 掃的是 4 天前的舊存檔」
# 連續幾晚都是**完全的靜默**。一晚寬限(網路抖動)之後每 3 晚重提一次。
obs = {}
c = cur.get("corpus") or {}
if c.get("literals_dropped"):
    obs["corpus_dropped"] = f"⚠️ {c['literals_dropped']} 個超長字串沒進語料——那些字沒有任何規則看過"
if cur.get("not_run_due_to_unknown"):
    obs["rules_not_run"] = ("⚠️ 有規則今晚一次都沒跑到(該掃的面抓不到):"
                            + ",".join(cur["not_run_due_to_unknown"][:6]))
if cur.get("en_blind"):
    obs["en_blind"] = ("⚠️ 這幾面的英文語料整個消失(i18n 中英切換,英文那一半沒人看):"
                       + ",".join(cur["en_blind"][:6]))
for s in cur.get("surfaces", []):
    if s.get("partial_unknown"):
        obs[f"partial:{s['id']}"] = (f"⚠️ {s['label']} 有 {s['partial_unknown']} 個子頁抓不到"
                                     "——這一面的「乾淨」只涵蓋抓得到的那些")
    if (s.get("stale_days") or 0) >= 2:
        obs[f"stale:{s['id']}"] = (f"⚠️ {s['label']} 掃的是 {s['stale_days']} 天前那份存檔"
                                   "——等於替一份沒人看的舊檔背書(交付可能也出事了)")
prev_obs = prev.get("obs_streak", {})
obs_streak = {k: prev_obs.get(k, 0) + 1 for k in obs}
obs_due = [k for k, n in obs_streak.items() if n >= 2 and (n - 2) % 3 == 0]   # 第 2/5/8… 晚

json.dump({"open": sorted(open_keys), "exit": cur.get("exit"), "unknown_streak": streak,
           "cfg_streak": cfg_n, "obs_streak": obs_streak,
           "generated": cur.get("generated")},
          open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False)

lines = []
if broke:
    probs = cur.get("selfcheck_problems") or []
    un = cur.get("unapplied_rules") or []
    lines.append("規則庫本身壞了——這次掃描的「乾淨」不算數:")
    lines += ["  · " + p for p in probs[:4]]
    if un:
        lines.append("  · 有規則從未被套用:" + ",".join(un))
for k in new:
    lines.append(detail[k])
for sid in dead:
    lines.append(f"⚠️ {sid} 已連續 3 晚抓不到——這一面等於沒有人看著")
for k in obs_due:
    lines.append(obs[k])
if unverified:
    lines.append("⚠️ 原違規頁這晚抓不到,無法確認是否已修(保留列管):" + ",".join(unverified[:6]))
if gone and not new and not broke:
    lines.append("✅ 已排除:" + ",".join(gone))
elif gone:
    lines.append("(同時排除:" + ",".join(gone) + ")")

if lines:
    icon = "🔴" if (new or broke) else ("⚠️" if (dead or obs_due or unverified) else "🟢")
    head = (f"{icon} 法務合規哨兵:{cur.get('violation',0)} 面違規 / "
            f"{cur.get('clean',0)} 面乾淨 / {cur.get('unknown',0)} 面未涵蓋")
    print(head + "\n\n" + "\n".join(lines) +
          "\n\n重跑:cd ~/Delvin-agent && ./.venv/bin/python -m legal.compliance_watch")
PYEOF
)
# ⚠️ state 必須**推播成功之後**才落地(第三輪驗證者 F9):原本內嵌 python 一算完就把 open 鍵
#    寫進 state,推播失敗只寫一行 stderr(沒有人看那個檔)→ 隔晚該鍵已不是 new → 該筆違規
#    從此永久靜默,而自測 ⑨d「同一違規次日不重推」還替這條路徑背書。
#    推播失敗 = 不動 state = 明晚原封不動再推一次。
if [ -n "$MSG" ]; then
  echo "notify: $MSG"
  if MD_REPO="$REPO" "$PY" "$NOTIFY" "$MSG"; then
    [ -f "$STATE.pending" ] && mv -f "$STATE.pending" "$STATE"
  else
    echo "$(date '+%F %T') ⚠️ 合規哨兵告警推播失敗(守衛自曝)——state 不落地,明晚重推" >&2
    rm -f "$STATE.pending"
    rc=$([ "$rc" -ne 0 ] && echo "$rc" || echo 4)
  fi
else
  [ -f "$STATE.pending" ] && mv -f "$STATE.pending" "$STATE"
fi
# ⚠️ 末行不可以是 exit 0(驗證者 F5):掃描器回 3(守衛自己壞了)時把 rc 吞成 0,
# cron 層與任何看 exit code 的監控就再也看不到「這台哨兵今晚根本沒掃」。
exit "$rc"
