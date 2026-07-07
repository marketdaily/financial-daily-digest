"""Gmail IMAP 自動收元大 CB 郵件(cron 每日跑,冪等)。

需 .env(repo 根)提供:
  GMAIL_USER=delvin.12345678@gmail.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Google 應用程式密碼(非登入密碼)
缺任一 → 靜默跳過(exit 0),不吵 cron;設好即全自動。

處理規則(寄件人 ANDREA_HSU@yuanta.com,近 N 天):
  1. 主旨含「選擇權報價表」→ 信件本文內嵌表 → cb_yuanta.ingest_html 入報價帳本
  2. 主旨含「CB發行案件更新」→ 下載 xlsx 附件到 inbox_files/ → 自動 rebuild cb_database
  3. 主旨含「可轉債基本資料」→ 下載 xlsx 存檔備查(暫不解析)
已處理信件記 .mail_seen.json(Message-ID),重跑不重複。

  python3 cb_mail_ingest.py --run          # cron 用
  python3 cb_mail_ingest.py --run --days 30   # 首次回補近30天
"""
import os
import re
import sys
import json
import email
import imaplib
import datetime
from email.header import decode_header

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SEEN_PATH = os.path.join(HERE, ".mail_seen.json")
FILES_DIR = os.path.join(HERE, "inbox_files")
SENDER = "ANDREA_HSU@yuanta.com"

sys.path.insert(0, HERE)
import cb_yuanta


def _env():
    creds = {}
    try:
        for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
            line = line.strip()
            if line.startswith("GMAIL_") and "=" in line:
                k, _, v = line.partition("=")
                creds[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return creds.get("GMAIL_USER"), creds.get("GMAIL_APP_PASSWORD")


def _load_seen():
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _save_seen(seen):
    tmp = SEEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen[-500:], f)
    os.replace(tmp, SEEN_PATH)


def _dec(s):
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        out.append(part.decode(enc or "utf-8", errors="ignore")
                   if isinstance(part, bytes) else part)
    return "".join(out)


def _bodies_and_attachments(msg):
    html, atts = "", []
    for part in msg.walk():
        ctype = part.get_content_type()
        fn = _dec(part.get_filename() or "")
        if fn:
            atts.append((fn, part.get_payload(decode=True) or b""))
        elif ctype == "text/html":
            payload = part.get_payload(decode=True) or b""
            cs = part.get_content_charset() or "utf-8"
            html += payload.decode(cs, errors="ignore")
    return html, atts


def _rebuild_db(xlsx_path):
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(HERE, "cb.py"), "--update", xlsx_path],
                       capture_output=True, text=True, timeout=120)
    print(("  " + (r.stdout or r.stderr).strip().splitlines()[-1]) if (r.stdout or r.stderr) else "")
    return r.returncode == 0


def run(days=7):
    user, pw = _env()
    if not user or not pw:
        print("GMAIL_USER/GMAIL_APP_PASSWORD 未設定(.env),跳過郵件收取")
        return 0
    seen = _load_seen()
    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, f'(FROM "{SENDER}" SINCE {since})')
        ids = data[0].split() if typ == "OK" else []
        handled = 0
        for mid in ids:
            typ, msgdata = M.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msgdata[0][1])
            msgid = msg.get("Message-ID", "").strip()
            if not msgid or msgid in seen:
                continue
            subj = _dec(msg.get("Subject"))
            html, atts = _bodies_and_attachments(msg)
            did = False
            if "選擇權報價表" in subj:
                qd = cb_yuanta.subject_quote_date(subj)
                n = cb_yuanta.ingest_html(html, qd)
                print(f"✉ {subj[:40]} → 報價入帳 {n} 筆")
                did = True
            elif "CB發行案件更新" in subj:
                for fn, blob in atts:
                    if fn.lower().endswith(".xlsx"):
                        os.makedirs(FILES_DIR, exist_ok=True)
                        p = os.path.join(FILES_DIR, fn)
                        with open(p, "wb") as f:
                            f.write(blob)
                        print(f"✉ {subj[:40]} → 存附件 {fn},重建資料庫:")
                        _rebuild_db(p)
                        did = True
            elif "可轉債基本資料" in subj:
                for fn, blob in atts:
                    if fn.lower().endswith((".xlsx", ".xls")):
                        os.makedirs(FILES_DIR, exist_ok=True)
                        with open(os.path.join(FILES_DIR, fn), "wb") as f:
                            f.write(blob)
                        print(f"✉ {subj[:40]} → 存附件 {fn}(備查)")
                        did = True
            if did or subj:            # 看過就記,不重複掃
                seen.append(msgid)
                handled += 1 if did else 0
        _save_seen(seen)
        print(f"郵件掃描完成:處理 {handled} 封(掃 {len(ids)} 封)")
        return 0
    except imaplib.IMAP4.error as e:
        print(f"IMAP 失敗:{e}(檢查應用程式密碼)")
        return 1
    finally:
        try:
            M.logout()
        except Exception:
            pass


if __name__ == "__main__":
    days = 7
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    sys.exit(run(days))
