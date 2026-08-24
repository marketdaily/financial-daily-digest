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
# ⚠️ 2026-08-24 收窄(Delvin 口頭放行 QFX 寄件網域設定):原本整個網域都擋,連唯讀的
# /v3/account 與設定寄件網域(DKIM/SPF)的 /v3/senders/domains 都打不開,甚至 grep 到
# 這串字的指令都被擋。那不是這條規則要防的事——它要防的是「把信寄出去」。
# 改成只擋真正的寄信出口;設定類端點放行。同時補上原本完全沒守的 smtplib 直寄。
if printf '%s' "$CMD" | grep -qiE '/v3/smtp/email|transactionalEmails|/v3/emailCampaigns'; then
  deny "直接打寄信端點(/v3/smtp/email、transactionalEmails、emailCampaigns)"
fi

# 2b) 用 smtplib / swaks / sendmail 直接寄信(原本沒守這條)
# 註:SMTP 交握探測到 RCPT TO 就 QUIT、不送 DATA,不算寄信,所以不擋 s.rcpt()。
# ⚠️ 別寫成 'smtplib[^|;&]*sendmail' —— 真實寫法是 "import smtplib; s.sendmail(...)",
#    中間就有分號,那個字元類會把它排除掉,自測當場抓到這個洞。分開兩次 grep 才對。
if printf '%s' "$CMD" | grep -qi 'smtplib' && \
   printf '%s' "$CMD" | grep -qiE 'sendmail|send_message'; then
  deny "以 smtplib 直接寄出信件"
fi
if printf '%s' "$CMD" | grep -qiE '\bswaks\b|\bsendmail\b +-|\bmailx\b|\bmutt\b +-s'; then
  deny "以命令列工具直接寄出信件(swaks / sendmail / mailx / mutt)"
fi

# 3) 執行 send_*.py 之類群發腳本
if printf '%s' "$CMD" | grep -qiE '(python3?|\./)[^|;&]*send_[a-z_]*\.py'; then
  deny "執行 send_*.py 群發腳本"
fi

exit 0
