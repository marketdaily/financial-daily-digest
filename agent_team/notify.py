"""Agent Team 交付通知 — 即時完成信 + 晨間匯總信(Brevo HTML 卡片)"""
import sys, os, json, glob, re
import html as _html
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)
STATE = os.path.join(DIR, "state.json")
OWNER = "delvin.12345678@gmail.com"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TPE = timezone(timedelta(hours=8))


def _load_key():
    """讀 BREVO 金鑰:先環境變數,再 repo 根目錄 .env(純 stdlib,不依賴 dotenv/config)。"""
    key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("SENDER_EMAIL")
    envp = os.path.join(ROOT, ".env")
    if (not key or not sender) and os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.strip() == "BREVO_API_KEY" and not key:
                key = v
            elif k.strip() == "SENDER_EMAIL" and not sender:
                sender = v
    return key, sender or "delvin.12345678@gmail.com"


BREVO_API_KEY, SENDER_EMAIL = _load_key()

STATUS = {
    "done":    ("#30d158", "✅ 完成"),
    "failed":  ("#ff453a", "❌ 失敗"),
    "working": ("#ff9f0a", "⏳ 接力中"),
}


def parse_task(path):
    text = open(path, encoding="utf-8").read()
    meta, body = {}, text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, body.strip()


def section(body, name):
    out, capture = [], False
    for line in body.splitlines():
        if line.strip().startswith("## "):
            capture = line.strip()[3:].strip() == name
            continue
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"last_digest": "", "last_worker_run": "", "limit_hit": False}


def save_state(s):
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def md_to_html(md):
    out, in_ul, in_code = [], False, False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>"); in_code = False
            else:
                if in_ul:
                    out.append("</ul>"); in_ul = False
                out.append('<pre style="background:#0f0c29;color:#c4b5fd;padding:14px;'
                           'border-radius:10px;overflow:auto;font-size:12px;">')
                in_code = True
            continue
        if in_code:
            out.append(_html.escape(line)); continue
        if not line.strip():
            if in_ul:
                out.append("</ul>"); in_ul = False
            continue
        esc = _html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`(.+?)`", r'<code style="background:#eef;padding:1px 5px;'
                     r'border-radius:4px;">\1</code>', esc)
        stripped = line.lstrip()
        if line.startswith("### "):
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f'<h3 style="font-size:14px;color:#312e81;margin:16px 0 6px;">{esc[4:]}</h3>')
        elif line.startswith("## "):
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f'<h2 style="font-size:15px;color:#1e1b4b;margin:18px 0 8px;'
                       f'border-left:3px solid #6366f1;padding-left:8px;">{esc[3:]}</h2>')
        elif stripped.startswith(("- ", "* ")):
            if not in_ul:
                out.append('<ul style="margin:6px 0;padding-left:20px;color:#444;'
                           'font-size:13px;line-height:1.9;">')
                in_ul = True
            out.append(f"<li>{esc.lstrip()[2:]}</li>")
        else:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f'<p style="font-size:13px;color:#444;line-height:1.7;margin:6px 0;">{esc}</p>')
    if in_ul:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def shell(subtitle, inner):
    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
  <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:26px 28px;">
    <div style="font-size:11px;color:#a5b4fc;letter-spacing:3px;text-transform:uppercase;">MarketDaily Agent Team</div>
    <h1 style="margin:6px 0 0;font-size:21px;font-weight:800;color:#fde68a;">{subtitle}</h1>
  </div>
  <div style="padding:24px 28px;">{inner}</div>
  <div style="background:#1a1a2e;padding:14px 28px;text-align:center;font-size:11px;color:rgba(255,255,255,0.35);line-height:1.9;">
    夜間值班系統 · 自動產生
  </div>
</div></body></html>"""


def _send(subject, html):
    if not BREVO_API_KEY:
        print("❌ 找不到 BREVO_API_KEY"); return False
    payload = json.dumps({
        "sender": {"name": "MarketDaily Agent Team", "email": SENDER_EMAIL},
        "to": [{"email": OWNER}],
        "subject": subject,
        "htmlContent": html,
    }).encode("utf-8")
    req = urllib.request.Request(BREVO_URL, data=payload, method="POST",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            print("✅ 寄出 " + subject)
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ 失敗 {e.code} {e.read().decode('utf-8', 'ignore')} {subject}")
        return False
    except Exception as e:
        print(f"❌ 失敗 {e} {subject}")
        return False


def instant(path):
    meta, body = parse_task(path)
    color, label = STATUS.get(meta.get("status", "done"), STATUS["done"])
    title = meta.get("title", "任務")
    inner = f"""
    <div style="display:inline-block;background:{color};color:#fff;font-size:12px;font-weight:700;
         padding:4px 12px;border-radius:20px;margin-bottom:14px;">{label}</div>
    <table width="100%" style="font-size:12px;color:#888;margin-bottom:10px;">
      <tr><td>工種 {meta.get('type','-')} · 優先 {meta.get('priority','-')}</td>
          <td align="right">{meta.get('id','')}</td></tr>
    </table>
    <h2 style="font-size:17px;color:#1a1a1a;margin:0 0 14px;">{_html.escape(title)}</h2>
    {md_to_html(body)}
    """
    return _send(f"[Agent Team] {label} — {title}", shell(f"{label} 任務交付", inner))


def digest():
    state = load_state()
    since = state.get("last_digest", "")
    items = []
    for folder in ("done", "failed"):
        for p in sorted(glob.glob(os.path.join(DIR, folder, "*.md"))):
            meta, body = parse_task(p)
            if meta.get("completed", "") > since:
                items.append((meta, body))
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(TPE).strftime("%Y-%m-%d")
    if not items:
        inner = ('<p style="font-size:14px;color:#666;line-height:1.7;">昨夜沒有完成的任務。'
                 '佇列是空的,或任務還在進行中。</p>')
    else:
        done = sum(1 for m, _ in items if m.get("status") == "done")
        failed = len(items) - done
        cards = []
        for meta, body in items:
            color, label = STATUS.get(meta.get("status", "done"), STATUS["done"])
            summary = section(body, "摘要") or section(body, "進度紀錄") or "(無摘要)"
            cards.append(f"""
            <div style="border:1px solid #e2e8f0;border-left:4px solid {color};border-radius:10px;
                 padding:14px 16px;margin-bottom:12px;">
              <div style="font-size:14px;font-weight:700;color:#1a1a1a;">{_html.escape(meta.get('title','任務'))}</div>
              <div style="font-size:11px;color:#999;margin:3px 0 8px;">{label} · {meta.get('type','-')} · {meta.get('id','')}</div>
              {md_to_html(summary)}
            </div>""")
        inner = (f'<p style="font-size:14px;color:#333;margin:0 0 16px;">昨夜值班結算 — '
                 f'完成 <strong style="color:#30d158;">{done}</strong> · '
                 f'失敗 <strong style="color:#ff453a;">{failed}</strong></p>'
                 + "".join(cards))
    ok = _send(f"☀️ Agent Team 晨間匯總 — {today}", shell("☀️ 晨間匯總", inner))
    if ok:
        state["last_digest"] = now_utc
        save_state(state)
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: notify.py task <任務檔路徑> | notify.py digest")
        sys.exit(1)
    if sys.argv[1] == "task" and len(sys.argv) > 2:
        instant(sys.argv[2])
    elif sys.argv[1] == "digest":
        digest()
    else:
        print(f"未知指令: {sys.argv[1]}")
        sys.exit(1)
