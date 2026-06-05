#!/usr/bin/env bash
# PreToolUse(Bash)hook:強制攔截任何「會寄 email 給訂閱者」的動作。
# 硬規則(用戶 2026-05-22):日報只能由 digest-cron worker 的排程 cron 自動寄,
# 禁止手動觸發 daily_digest workflow、跑 send_*.py 測試腳本、直接 curl Brevo 寄信 API。
# 唯一例外:新訂閱者歡迎信由 Cloudflare Worker 自動發,不走 bash,不受此 hook 影響。
# 攔截方式:exit 2 + stderr 訊息,回饋給 Claude 並阻止該 Bash 呼叫。

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("tool_input",{}).get("command",""))
except Exception:
    print("")
' 2>/dev/null)"

[ -z "$CMD" ] && exit 0

deny() {
  echo "🚫 已被擋下:此指令可能會寄 email 給訂閱者,違反硬規則「日報只能由 digest-cron 排程自動寄」。" >&2
  echo "原因:$1" >&2
  echo "若真的要做,請先跟用戶口頭確認;歡迎信由 Worker 自動發、不需走這裡。" >&2
  exit 2
}

# 1) 手動觸發日報相關 GitHub workflow
if printf '%s' "$CMD" | grep -qiE 'gh +workflow +run' && \
   printf '%s' "$CMD" | grep -qiE 'digest|daily|send|寄送'; then
  deny "手動觸發日報/寄送 workflow(gh workflow run)"
fi

# 2) 直接打 Brevo / Sendinblue 寄信 API
if printf '%s' "$CMD" | grep -qiE 'api\.(brevo|sendinblue)\.com|smtp/email|transactionalEmails'; then
  deny "直接 curl Brevo/Sendinblue 寄信 API"
fi

# 3) 執行 send_*.py 之類群發腳本
if printf '%s' "$CMD" | grep -qiE '(python3?|\./)[^|;&]*send_[a-z_]*\.py'; then
  deny "執行 send_*.py 群發腳本"
fi

exit 0
