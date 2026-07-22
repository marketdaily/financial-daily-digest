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
SENDERS = ["ANDREA_HSU@yuanta.com", "wuy100@gmail.com", "tssco.com.tw"]  # 元大許乃方 / 老闆余威廷轉寄 / 元富證券

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


def _looks_like_cb_db(xlsx_path):
    """試解析:像 CB 發行清單才准重建,防未知格式靜默洗空 live DB。
    2026-07-17 事故:CBAS報價表被誤當發行清單重建(它恰好在 stock_code 欄放了
    債券代碼樣的數字,舊版只驗 isdigit 就放行,120 筆全錯位蓋掉 live 五天)。
    加嚴:正股 4 碼 + 債券代碼 5-6 碼都對得上才算有效檔(董事會通過段還沒有
    債券代碼,靠掛牌/送件段就遠超門檻,不受影響)。"""
    try:
        from parse_excel import parse as _parse
        items = _parse(xlsx_path)
    except Exception:
        return False, 0
    good = sum(1 for i in items
               if re.fullmatch(r"\d{4}", str(i.get("stock_code") or ""))
               and re.fullmatch(r"\d{5,6}", str(i.get("bond_code") or ""))
               and i.get("name"))
    return (good >= 5), good


def _restart_server():
    """cb_server 啟動時把 DB 快取在記憶體、不會自動重載;更新資料庫後必須重啟才生效。"""
    import subprocess
    import time
    subprocess.run(["pkill", "-f", "python3 cb_server.py$"])
    time.sleep(1)
    logf = open(os.path.join(HERE, "server.log"), "a")
    subprocess.Popen([sys.executable, "cb_server.py"], cwd=HERE,
                     stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    print("  cb_server 已重啟(載入新資料庫)")


def run(days=7):
    user, pw = _env()
    if not user or not pw:
        print("GMAIL_USER/GMAIL_APP_PASSWORD 未設定(.env),跳過郵件收取")
        return 0
    seen = _load_seen()
    need_restart = False
    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        ids = []
        for snd in SENDERS:
            typ, data = M.search(None, f'(FROM "{snd}" SINCE {since})')
            if typ == "OK":
                ids += data[0].split()
        ids = list(dict.fromkeys(ids))   # 去重(同信可能命中多寄件人)
        KEYS = ("選擇權報價表", "CB發行案件更新", "CB初級市場資訊", "可轉債基本資料")
        handled = 0
        for mid in ids:
            # 1) header 輕量分流(老闆個人信箱信多,不可對每封抓完整含大圖 RFC822)
            typ, hd = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT)])")
            if typ != "OK" or not hd or not hd[0]:
                continue
            hmsg = email.message_from_bytes(hd[0][1])
            msgid = (hmsg.get("Message-ID") or "").strip()
            if not msgid or msgid in seen:
                continue
            subj = _dec(hmsg.get("Subject"))
            subj_match = any(k in subj for k in KEYS)
            # 2) 不靠主旨用詞:已知寄件人只要夾帶 xlsx 就視為候選(BODYSTRUCTURE 廉價偵測,不下載大圖)
            has_xlsx = False
            if not subj_match:
                typ, bs = M.fetch(mid, "(BODYSTRUCTURE)")
                if typ == "OK" and bs and bs[0]:
                    blob = bs[0][1] if isinstance(bs[0], tuple) else bs[0]
                    blob = blob if isinstance(blob, bytes) else str(blob).encode()
                    low = blob.lower()
                    has_xlsx = (b".xlsx" in low) or (b"spreadsheetml" in low)
            if not (subj_match or has_xlsx):
                seen.append(msgid)          # 非 CB 郵件,標記略過
                continue
            # 3) 候選 → 抓完整信處理
            typ, msgdata = M.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msgdata[0][1])
            html, atts = _bodies_and_attachments(msg)
            did = False
            if "選擇權報價表" in subj:               # 內文報價表(無附件)
                qd = cb_yuanta.subject_quote_date(subj)
                n = cb_yuanta.ingest_html(html, qd)
                print(f"✉ {subj[:40]} → 報價入帳 {n} 筆")
                did = True
            for fn, blob in atts:                    # xlsx 附件:依內容路由,不靠主旨/檔名用詞
                if not fn.lower().endswith((".xlsx", ".xls")):
                    continue
                os.makedirs(FILES_DIR, exist_ok=True)
                fp = os.path.join(FILES_DIR, fn)
                with open(fp, "wb") as f:
                    f.write(blob)
                did = True
                if "基本資料" in fn:                  # 可轉債基本資料表 → 僅備查
                    print(f"✉ {subj[:36]} → 存 {fn}(基本資料備查)")
                    continue
                ok, cnt = _looks_like_cb_db(fp)      # 試解析守門:像 CB 發行清單才重建
                if ok:
                    print(f"✉ {subj[:36]} → {fn}(解析 {cnt} 檔),重建資料庫:")
                    if _rebuild_db(fp):
                        need_restart = True
                else:
                    print(f"⚠ {subj[:36]} → {fn} 僅解析 {cnt} 檔,疑似新格式;已存檔未重建(未動 live),請通知我加解析器")
            seen.append(msgid)
            handled += 1 if did else 0
        _save_seen(seen)
        if need_restart:
            _restart_server()
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
