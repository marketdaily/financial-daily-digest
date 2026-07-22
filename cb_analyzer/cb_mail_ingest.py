"""Gmail IMAP 自動收元大 CB 郵件(cron 平日 08-18 每 10 分,flock 防重疊,冪等)。

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
import email.utils
import imaplib
import datetime
import zoneinfo
from email.header import decode_header

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SEEN_PATH = os.path.join(HERE, ".mail_seen.json")
STATUS_PATH = os.path.join(HERE, "mail_ingest_status.json")
FILES_DIR = os.path.join(HERE, "inbox_files")
SENDERS = ["ANDREA_HSU@yuanta.com", "wuy100@gmail.com", "tssco.com.tw"]  # 元大許乃方 / 老闆余威廷轉寄 / 元富證券
TAIPEI = zoneinfo.ZoneInfo("Asia/Taipei")
# cb-desk 事件通知佇列:push_notifier 常駐 tail 這個檔(cbdesk/event_alert.record_notifications
# 的落帳檔=notifier 的輸入),照它的行格式 append 一行=直推同一條 web push 管線
DESK_EVENT_LOG = os.path.expanduser("~/cb-desk/data/event_notifications.jsonl")

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


def _write_status(new_items, latest, scanned, push="none", path=STATUS_PATH):
    """成功掃完才寫(失敗保留上一次成功狀態):最後成功時間+本輪新增+最新一封許乃方郵件。
    /api/brief 讀這個檔顯示「郵件資料多新」,tmp+replace 原子寫,不讓半寫檔騙到簡報。"""
    st = {"last_success": datetime.datetime.now(TAIPEI).isoformat(timespec="seconds"),
          "new_items": new_items, "scanned": scanned, "push": push,
          "latest_mail": ({"subject": latest[1],
                           "date": latest[0].astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M")}
                          if latest else None)}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _notify_desk(subjects, log_path=DESK_EVENT_LOG):
    """新郵件事件推進 cb-desk 既有 web push 管線(格式仿 cbdesk/event_alert 落帳行:
    code/source/level/signal/notified_at;push_notifier 30s 內 tail 到就推給訂閱分析師)。
    cb-desk 不在/寫入失敗 → 回錯誤字串進 status 檔,絕不讓推播反過來弄死 ingest。"""
    try:
        if not os.path.isdir(os.path.dirname(log_path)):
            return "skipped:cb-desk 不存在"
        now = datetime.datetime.now(TAIPEI).isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as f:
            for s in subjects:
                row = {"code": "📬", "source": "元大信箱", "level": "info",
                       "signal": ((s or "").strip() or "新 CB 郵件")[:80],
                       "notified_at": now}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return f"event_log:{len(subjects)}"
    except Exception as e:
        return f"failed:{type(e).__name__}"


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
        andrea_ids = set()
        for snd in SENDERS:
            typ, data = M.search(None, f'(FROM "{snd}" SINCE {since})')
            if typ == "OK":
                ids += data[0].split()
                if snd == SENDERS[0]:
                    andrea_ids.update(data[0].split())
        ids = list(dict.fromkeys(ids))   # 去重(同信可能命中多寄件人)
        KEYS = ("選擇權報價表", "CB發行案件更新", "CB初級市場資訊", "可轉債基本資料")
        handled = 0
        latest = None        # 最新一封許乃方郵件 (aware datetime, 主旨) — 含已處理過的
        new_subjects = []    # 本輪真的新入庫的郵件主旨 → 推播給訂閱分析師
        for mid in ids:
            # 1) header 輕量分流(老闆個人信箱信多,不可對每封抓完整含大圖 RFC822)
            typ, hd = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT DATE)])")
            if typ != "OK" or not hd or not hd[0]:
                continue
            hmsg = email.message_from_bytes(hd[0][1])
            msgid = (hmsg.get("Message-ID") or "").strip()
            subj = _dec(hmsg.get("Subject"))
            if mid in andrea_ids:
                try:
                    dt = email.utils.parsedate_to_datetime(hmsg.get("Date") or "")
                except (TypeError, ValueError):
                    dt = None
                if dt and dt.tzinfo and (latest is None or dt > latest[0]):
                    latest = (dt, subj)
            if not msgid or msgid in seen:
                continue
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
            if did:
                handled += 1
                new_subjects.append(subj)
        _save_seen(seen)
        push = _notify_desk(new_subjects) if new_subjects else "none"
        _write_status(handled, latest, len(ids), push)
        if need_restart:
            _restart_server()
        print(f"郵件掃描完成:處理 {handled} 封(掃 {len(ids)} 封,推播 {push})")
        return 0
    except (imaplib.IMAP4.error, OSError) as e:
        # 每 10 分跑一次,暫時性 IMAP/網路失敗只留一行 log、exit 0 不吵 cron;
        # status 檔不動 → 簡報顯示的仍是上一次成功時間(誠實呈現資料多舊)
        print(f"IMAP 失敗(略過本輪):{type(e).__name__}: {e}")
        return 0
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
