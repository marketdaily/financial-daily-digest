#!/usr/bin/env python3
"""block-mass-email.sh 的正反對照自測。

2026-08-24 建立。收窄那條「整個 Brevo 網域都擋」的規則時發現:這個 hook 從 2026-05-22
上線到今天，從來沒有任何東西在驗它擋對了沒有。守衛沒有測試 = 不知道它守的是什麼。

正對照(必須擋下,exit 2)與反對照(必須放行,exit 0)兩邊都要有——只驗「會擋」不驗
「不會誤擋」，就是我今天撞到的那個狀況:它連 grep 都擋，而我完全不知道。
"""
import json
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parent.parent / ".claude/hooks/block-mass-email.sh"

MUST_BLOCK = [
    ("Brevo 交易信端點", "curl -X POST https://api.brevo.com/v3/smtp/email -d @body.json"),
    ("Sendinblue 舊端點", "curl https://api.sendinblue.com/v3/smtp/email"),
    ("行銷活動端點", "curl -X POST https://api.brevo.com/v3/emailCampaigns"),
    ("transactionalEmails", "curl https://api.brevo.com/v3/transactionalEmails/xyz"),
    ("手動觸發日報 workflow", "gh workflow run daily_digest.yml"),
    ("群發腳本", "python3 send_digest_to_all.py"),
    ("smtplib 真的寄出", "python3 -c 'import smtplib; s.sendmail(a,b,c)'"),
    ("swaks 寄信", "swaks --to a@b.com --from c@d.com"),
]

MUST_PASS = [
    ("讀 Brevo 帳號資訊", "curl -H 'api-key: X' https://api.brevo.com/v3/account"),
    ("設定寄件網域(DKIM/SPF)", "curl -X POST https://api.brevo.com/v3/senders/domains -d '{}'"),
    ("查寄件網域驗證狀態", "curl https://api.brevo.com/v3/senders/domains/qfxsolution.com"),
    ("grep 到這些字的一般指令", "grep -rn 'api.brevo.com' --include=*.py ."),
    ("SMTP 探測(RCPT 後 QUIT,不送 DATA)", "python3 -c 'import smtplib; s.rcpt(\"hi@x.com\"); s.quit()'"),
    ("看日報排程", "gh run list --workflow=daily_digest.yml"),
    ("一般 git 操作", "git commit -m 'send email docs'"),
    ("讀寄送紀錄檔", "cat logs/send_report.txt"),
]


def run(cmd):
    payload = json.dumps({"tool_input": {"command": cmd}})
    p = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True)
    return p.returncode


def main():
    fails = []
    for label, cmd in MUST_BLOCK:
        rc = run(cmd)
        ok = rc == 2
        print(f"  {'✅' if ok else '❌'} 應擋下  {label:<26} exit={rc}")
        if not ok:
            fails.append(f"沒擋下:{label} — {cmd}")
    print()
    for label, cmd in MUST_PASS:
        rc = run(cmd)
        ok = rc == 0
        print(f"  {'✅' if ok else '❌'} 應放行  {label:<26} exit={rc}")
        if not ok:
            fails.append(f"誤擋:{label} — {cmd}")
    print()
    if fails:
        print(f"❌ {len(fails)} 項不符:")
        for f in fails:
            print("   ", f)
        return 1
    print(f"✅ 正對照 {len(MUST_BLOCK)} 項全擋下、反對照 {len(MUST_PASS)} 項全放行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
