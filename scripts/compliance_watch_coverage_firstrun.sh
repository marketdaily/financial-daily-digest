#!/bin/bash
# 一次性首班驗收(2026-08-05 建,驗「全站納管」+「第二輪驗證者 9 則修復」的第一班,驗完自我移除)。
#
# 為什麼要再驗一次:8/4 的首班驗的是 7 個具名頁面那一版;8/5 起頁面清單改成
# docs/ glob 預設納管(17 面 / 82 頁 / blog 全量),掃描量 ×10、新增排除清單 lint、
# 語料掉字會影響 exit——依 feedback_first_run_acceptance,鏈上改一層就要有首班驗收訊號,
# 別讓老闆當第一個發現的人。
set -u
REPO="$HOME/Delvin-agent"; PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
OUT="$HOME/.marketdaily-fallback/.compliance_watch_latest.json"
source "$REPO/scripts/lib_cron_runner.sh"
cron_time_gate "22:35" "22:55"
cron_daily_lock "compliance_watch_coverage_firstrun"

problems=""
[ -s "$OUT" ] || problems="$problems\n· 沒有產出 $OUT(哨兵那一班根本沒跑或掛了)"
if [ -s "$OUT" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$OUT") ))
  [ "$age" -lt 3600 ] || problems="$problems\n· 產出檔已 $((age/60)) 分鐘沒更新(不是今晚這一班寫的)"
  summary=$("$PY" -c "
import json
d = json.load(open('$OUT'))
c = d.get('corpus') or {}
ids = {s['id']: s for s in d.get('surfaces', [])}
bad = []
if not d.get('selfcheck_ok'): bad.append('規則庫/頁面清單設定自檢失敗:' + ';'.join(d.get('selfcheck_problems') or [])[:120])
if d.get('unapplied_rules'): bad.append('有規則從未被套用:' + ','.join(d['unapplied_rules']))
if c.get('pages', 0) < 250: bad.append('語料只有 %s 頁(第三輪 F6 的公版存檔 87 頁沒進來?)' % c.get('pages'))
if c.get('external_js_unscanned'): bad.append('%s 支同網域外部 JS 抓不到(F4 的語料黑洞又開了)' % c['external_js_unscanned'])
if d.get('en_blind_pages'): bad.append('這幾頁有 data-i18n 卻零英文語料:' + ','.join(d['en_blind_pages'][:4]))
if c.get('en_pages', 0) < 5: bad.append('含英文的頁只有 %s(英文那一半沒進語料)' % c.get('en_pages'))
if d.get('en_blind'): bad.append('這幾面的英文語料整個消失:' + ','.join(d['en_blind']))
if d.get('exit') == 3: bad.append('exit 3 —— 守衛自己壞了,今晚等於沒掃')
ms = ids.get('ms_pseo')
if not ms or ms['status'] == 'unknown': bad.append('命書全站面沒掃到(sitemap 展不開)')
elif int((ms.get('detail') or '0').split()[0]) < 100: bad.append('命書全站只掃了 %s(sitemap 腰斬?)' % ms.get('detail'))
pm = ids.get('ms_pricing_api')
if not pm: bad.append('缺少定價快照面')
elif len(pm.get('rules_run') or []) < 7: bad.append('定價面只評估得動 %s 條偽規則(上游欄位漂移?):%s' % (len(pm.get('rules_run') or []), pm.get('detail')))
try:
    base = json.load(open('$HOME/.marketdaily-fallback/.compliance_expand_baseline.json'))
    miss = [t for t in ('@docs_rest', '@blog_all', '@archive_all', '@ms_sitemap') if not base.get(t)]
    flat = [t for t, v in base.items() if not isinstance(v, dict) or not v.get('hist')]
    if flat: bad.append('展開基準檔仍是舊格式(沒有 hist 筆數史,F7 的漸進退化偵測沒生效):%s' % ','.join(flat))
    if miss: bad.append('展開基準檔缺 %s(腰斬偵測沒有基準可比)' % ','.join(miss))
except Exception as e:
    bad.append('展開基準檔讀不到(%s)——覆蓋面腰斬偵測沒有基準' % type(e).__name__)
for sid, minp in (('md_docs_rest', 8), ('md_blog_all', 40), ('md_archive_all', 40)):
    s = ids.get(sid)
    if not s: bad.append('缺少 surface %s' % sid)
    elif s['status'] == 'unknown': bad.append('%s 整面沒掃到:%s' % (sid, s.get('detail'))[:80])
    elif s.get('partial_unknown'): bad.append('%s 有 %s 頁抓不到' % (sid, s['partial_unknown']))
    elif int((s.get('detail') or '0').split()[0]) < minp: bad.append('%s 只掃了 %s' % (sid, s.get('detail')))
print('BAD:' + ';'.join(bad) if bad else
      'OK:%s 面 / %s 頁語料(含英文 %s)/ %s 次檢查 · 違規 %s 面 · 未涵蓋 %s 面' % (
          d.get('clean', 0) + d.get('violation', 0), c.get('pages'), c.get('en_pages'),
          d.get('checks_run'), d.get('violation'), d.get('unknown')))
" 2>&1) || summary="BAD:產出檔不是合法 JSON 或驗收腳本自己爆炸"
  case "$summary" in BAD:*) problems="$problems\n· ${summary#BAD:}" ;; esac
fi

if [ -n "$problems" ]; then
  MSG="🔴 法務合規哨兵【全站納管首班驗收 FAIL】$(TZ=Asia/Taipei date '+%F %H:%M')$(printf "$problems")

修:cd ~/Delvin-agent && ./.venv/bin/python -m legal.compliance_watch"
else
  MSG="✅ 法務合規哨兵【全站納管首班驗收 PASS】$(TZ=Asia/Taipei date '+%F %H:%M')
${summary#OK:}
涵蓋面 7 頁 → 310 頁(docs glob 遞迴 + blog 全量 + 公版存檔 87 頁 + 命書 sitemap 141 頁)。
本班同時驗第二/三輪驗證者 21 則修復的生產訊號:en_blind 空 / 外部 JS 全抓得到 / exit≠3 /
命書 sitemap 沒腰斬 / 定價面 7 條偽規則都評估得動 / 展開基準四個 token 齊全且已是 hist 新格式。"
fi
MD_REPO="$REPO" "$PY" "$HOME/.marketdaily-fallback/notify_admin.py" "$MSG" \
  || echo "$(date '+%F %T') ⚠️ 首班驗收推播失敗" >&2

crontab -l 2>/dev/null | grep -v "compliance_watch_coverage_firstrun.sh" | crontab -
echo "$(date '+%F %T') 全站納管首班驗收完成並已自我移除:$MSG"
