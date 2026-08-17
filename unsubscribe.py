"""日報退訂連結:token 與 URL 的唯一產生處(Python 寄信端與 Worker 端共用同一算法)。

token = HMAC-SHA256(INTERNAL_TOKEN, "unsub|v1|" + email) 前 16 hex(64-bit,不可枚舉)。
前綴 "unsub|v1|" 是 domain separation —— 同一把 INTERNAL_TOKEN 在別處當 Bearer,
沒有前綴時別的用途算出的簽章有機會被拿來冒用成退訂連結。

沒有 secret 時一律回空字串:呼叫端必須把「這封信沒有退訂連結」當正常分支處理,
不可硬塞一個算不出簽章的半殘 URL(點進去只會看到驗證失敗頁,比沒有連結更糟)。

⚠️ 輪替 INTERNAL_TOKEN 的人請先讀這段(2026-08-17 r2 驗證者 F7):
這把 secret 一換,**所有已經寄出去、還躺在收信匣裡的日報**,它們的退訂連結與
List-Unsubscribe header 會同時永久失效(點了只會看到「這個退訂連結無法驗證」),
官網三頁「日報底部可退訂」的宣稱又變成假的,Gmail/Apple 的 one-click POST 也會失敗
(投遞信譽風險)。Worker 端驗證會**同時接受 `INTERNAL_TOKEN` 與 `INTERNAL_TOKEN_2`**,
所以正確做法是:輪替前先把**舊值**寫進 worker 的 `INTERNAL_TOKEN_2`
(`npx wrangler secret put INTERNAL_TOKEN_2`),並保留至少一個日報生命週期(建議 ≥ 30 天)
再移除。CLAUDE.md 的「八處一起換」清單沒有列這一步。
"""
import hashlib
import hmac
import os
import re
from urllib.parse import quote

UNSUB_BASE = os.environ.get("MD_UNSUB_BASE", "https://api.marketdaily.ai/unsubscribe")
LINK_TEXT = "取消訂閱 / Unsubscribe"
_SECRET_ENVS = ("MARKETDAILY_INTERNAL_TOKEN", "INTERNAL_TOKEN")

# 兩端(這裡簽、Worker 驗)必須對同一個字串算 HMAC,所以「要修掉哪些字元」不可以交給
# 各自語言內建的 trim/strip 語義 —— 它們的字元集不一樣:
#   Python str.strip() 吃 U+001C–1F 與 U+0085,不吃 U+FEFF;JS .trim() 正好相反。
#   ⇒ 帶 BOM 的 email:Python 簽含 BOM 的字串、Worker 驗不含 BOM 的 ⇒ 那個人的退訂連結**永遠**驗不過。
# 這裡明寫成一個共用字元集(Worker 端 `UNSUB_TRIM` 逐字相同),兩邊都不靠內建語義。
_TRIM_CHARS = "\\t\\n\\v\\f\\r \\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff"
_TRIM_RE = re.compile(f"^[{_TRIM_CHARS}]+|[{_TRIM_CHARS}]+$")


def _secret() -> str:
    for k in _SECRET_ENVS:
        v = os.environ.get(k)
        if v:
            return v
    return ""


def norm_email(email: str) -> str:
    return _TRIM_RE.sub("", email or "").lower()


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
    # 「已經有連結了」的哨兵必須看 **href**,不能看 LINK_TEXT(2026-08-17 r2 驗證者 F3):
    # 版型哪天多一句提到「取消訂閱 / Unsubscribe」的**純文字**說明,這裡就會整批跳過注入,
    # 而寄後 postcheck 若也用同一個字串當判準,兩邊會被同一句話同時滿足 ⇒ 全批無連結、零告警。
    if UNSUB_BASE in html:
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
