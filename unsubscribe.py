"""日報退訂連結:token 與 URL 的唯一產生處(Python 寄信端與 Worker 端共用同一算法)。

token = HMAC-SHA256(INTERNAL_TOKEN, "unsub|v1|" + email) 前 16 hex(64-bit,不可枚舉)。
前綴 "unsub|v1|" 是 domain separation —— 同一把 INTERNAL_TOKEN 在別處當 Bearer,
沒有前綴時別的用途算出的簽章有機會被拿來冒用成退訂連結。

沒有 secret 時一律回空字串:呼叫端必須把「這封信沒有退訂連結」當正常分支處理,
不可硬塞一個算不出簽章的半殘 URL(點進去只會看到驗證失敗頁,比沒有連結更糟)。
"""
import hashlib
import hmac
import os
from urllib.parse import quote

UNSUB_BASE = os.environ.get("MD_UNSUB_BASE", "https://api.marketdaily.ai/unsubscribe")
LINK_TEXT = "取消訂閱 / Unsubscribe"
_SECRET_ENVS = ("MARKETDAILY_INTERNAL_TOKEN", "INTERNAL_TOKEN")


def _secret() -> str:
    for k in _SECRET_ENVS:
        v = os.environ.get(k)
        if v:
            return v
    return ""


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def unsub_token(email: str, secret: str = None) -> str:
    s = _secret() if secret is None else secret
    if not s:
        return ""
    msg = "unsub|v1|" + norm_email(email)
    return hmac.new(s.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def unsub_url(email: str, secret: str = None) -> str:
    t = unsub_token(email, secret)
    if not t or not norm_email(email):
        return ""
    return f"{UNSUB_BASE}?e={quote(norm_email(email), safe='')}&t={t}"


def footer_link_html(email: str, secret: str = None) -> str:
    u = unsub_url(email, secret)
    if not u:
        return ""
    return (f'<a href="{u}" style="color:#9ca3af;text-decoration:underline;">'
            f'{LINK_TEXT}</a>')


def inject_footer_link(html: str, email: str, secret: str = None) -> str:
    """把退訂連結塞進日報 footer。找不到 footer 就退到 </body> 前,再不行接在尾巴——
    退訂連結不可以因為版型換了就靜默消失(那正是 #396 的形狀)。已經有連結時不重複塞。"""
    link = footer_link_html(email, secret)
    if not link or not html:
        return html
    if LINK_TEXT in html:
        return html
    i = html.find('<div class="footer">')
    if i != -1:
        j = html.find('</div>', i)
        if j != -1:
            return html[:j] + '<br><br>' + link + html[j:]
    j = html.rfind('</body>')
    tail = (f'<div style="text-align:center;font-size:11px;color:#9ca3af;'
            f'padding:14px 12px;">{link}</div>')
    if j != -1:
        return html[:j] + tail + html[j:]
    return html + tail
