"""日報退訂迴歸(2026-08-17 open #396)。

事故形狀:privacy / contact / index 三頁對外寫著「任何一封日報底部點『取消訂閱』即時生效」,
而 email 裡從來沒有那個連結、沒有 List-Unsubscribe header、也沒有任何端點 ——
官網宣稱存在、實際不存在(法務曝險)。修法是補實作而不是把文案改弱。

這支守的是「宣稱」與「實作」之間那四個接點:
  ① 連結算得出來且綁得住收信人(token)
  ② 每封寄出的信真的帶著它(footer 注入 + Brevo header)
  ③ 退訂 header 永遠不可以害一封信寄不出去(400 要能拔掉 header 重試,5xx 不重試=不雙寄)
  ④ 退訂真的會生效(兩層獨立過濾,而且各自 fail-open 到「照寄」而非「整批漏信」)
零網路:requests.post/get 全部替換成假的。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unsubscribe  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")
        print(f"  ✗ {name}: got={got!r} want={want!r}")
    else:
        print(f"  ✓ {name}")


def check_true(name, cond, why=""):
    check(name + (f" ({why})" if why else ""), bool(cond), True)


SEC = "test-secret-not-production"
EMAIL = "Reader@Example.com"


# ── ① token ────────────────────────────────────────────────────────────────
t1 = unsubscribe.unsub_token(EMAIL, SEC)
check("token 長度 16 hex", (len(t1), all(c in "0123456789abcdef" for c in t1)), (16, True))
check("token 大小寫無關(email 正規化)", unsubscribe.unsub_token("reader@example.com", SEC), t1)
check_true("token 綁 email", unsubscribe.unsub_token("other@example.com", SEC) != t1)
check_true("token 綁 secret", unsubscribe.unsub_token(EMAIL, "another-secret") != t1)

# domain separation:同一把 secret 在別處當 Bearer,少了 "unsub|v1|" 前綴的簽章不可以撞上退訂 token
import hashlib  # noqa: E402
import hmac  # noqa: E402
naked = hmac.new(SEC.encode(), b"reader@example.com", hashlib.sha256).hexdigest()[:16]
check_true("有 domain separation 前綴", naked != t1)

check("沒 secret 就不給半殘 URL", unsubscribe.unsub_url(EMAIL, ""), "")
check("空 email 不給 URL", unsubscribe.unsub_url("", SEC), "")
u = unsubscribe.unsub_url(EMAIL, SEC)
check_true("URL 帶 e= 與 t=", "e=reader%40example.com" in u and f"t={t1}" in u, u)


# ── ② footer 注入 ──────────────────────────────────────────────────────────
SHELL = ('<html><body><div class="wrapper">X'
         '<div class="footer">免責聲明<a href="https://marketdaily.ai">站</a></div>'
         '</div></body></html>')
out = unsubscribe.inject_footer_link(SHELL, EMAIL, SEC)
check_true("連結進了 footer 內", unsubscribe.LINK_TEXT in out
           and out.index(unsubscribe.LINK_TEXT) < out.index("</div></div></body>"))
check_true("token 在連結裡", t1 in out)
check("重複注入不會長兩份", unsubscribe.inject_footer_link(out, EMAIL, SEC).count(unsubscribe.LINK_TEXT), 1)
check("沒 secret 時 HTML 原封不動", unsubscribe.inject_footer_link(SHELL, EMAIL, ""), SHELL)

# 版型換了(footer class 沒了)也不准靜默消失 —— 那正是 #396 的形狀
NO_FOOTER = "<html><body><div>內容</div></body></html>"
o2 = unsubscribe.inject_footer_link(NO_FOOTER, EMAIL, SEC)
check_true("沒 footer → 退到 </body> 前", unsubscribe.LINK_TEXT in o2 and o2.endswith("</body></html>"))
o3 = unsubscribe.inject_footer_link("純片段沒有 body", EMAIL, SEC)
check_true("連 body 都沒有 → 接在尾巴", unsubscribe.LINK_TEXT in o3)


# ── ③ Brevo payload:header 帶了,而且永遠不會害信寄不出去 ─────────────────
import publisher  # noqa: E402

os.environ["MARKETDAILY_INTERNAL_TOKEN"] = SEC
CALLS = []


class FakeResp:
    def __init__(self, status):
        self.status_code = status
        self.ok = 200 <= status < 300

    def json(self):
        return {}


def fake_post_factory(statuses):
    seq = list(statuses)

    def fake_post(url, json=None, headers=None, timeout=None, params=None):
        CALLS.append(json)
        return FakeResp(seq.pop(0) if seq else 200)
    return fake_post


publisher.requests.post = fake_post_factory([201])
CALLS.clear()
ok = publisher.send_transactional_email("reader@example.com", "2026-08-17", "<html></html>", "k")
check("正常寄出回 True", ok, True)
hdrs = (CALLS[0] or {}).get("headers") or {}
check_true("List-Unsubscribe 是 <URL> 形式(RFC 2369)",
           hdrs.get("List-Unsubscribe", "").startswith("<https://") and hdrs["List-Unsubscribe"].endswith(">"),
           hdrs.get("List-Unsubscribe"))
check("one-click(RFC 8058)", hdrs.get("List-Unsubscribe-Post"), "List-Unsubscribe=One-Click")
check_true("header 裡的 token 對得上", unsubscribe.unsub_token("reader@example.com", SEC) in hdrs["List-Unsubscribe"])

publisher.requests.post = fake_post_factory([400, 201])
CALLS.clear()
ok = publisher.send_transactional_email("reader@example.com", "2026-08-17", "<html></html>", "k")
check("400 → 拔 header 重試後成功", (ok, len(CALLS)), (True, 2))
check("重試那次沒有 headers", "headers" in (CALLS[1] or {}), False)

publisher.requests.post = fake_post_factory([500, 201])
CALLS.clear()
ok = publisher.send_transactional_email("reader@example.com", "2026-08-17", "<html></html>", "k")
check("5xx 不重試(曖昧狀態不製造雙寄)", (ok, len(CALLS)), (False, 1))

del os.environ["MARKETDAILY_INTERNAL_TOKEN"]
publisher.requests.post = fake_post_factory([201])
CALLS.clear()
publisher.send_transactional_email("reader@example.com", "2026-08-17", "<html></html>", "k")
check("沒 secret 時不加 header(照寄)", "headers" in (CALLS[0] or {}), False)
os.environ["MARKETDAILY_INTERNAL_TOKEN"] = SEC


# ── ④ 退訂真的生效:兩層獨立過濾 ────────────────────────────────────────────
class FakeListResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.ok = 200 <= status < 300

    def json(self):
        return self._p


publisher.requests.get = lambda url, headers=None, params=None, timeout=None: FakeListResp({
    "contacts": [
        {"email": "a@x.com"},
        {"email": "gone@x.com", "emailBlacklisted": True},
        {"email": "b@x.com", "emailBlacklisted": False},
    ]})
check("Brevo 層:黑名單被剔除", publisher.get_all_subscribers(2), ["a@x.com", "b@x.com"])

publisher.requests.get = lambda url, headers=None, params=None, timeout=None: FakeListResp({
    "contacts": [{"email": "a@x.com"}]})
check("欄位不存在時 fail-open(照寄,不整批漏信)", publisher.get_all_subscribers(2), ["a@x.com"])

import main  # noqa: E402

SUBS = ["a@x.com", "Gone@X.com", "b@x.com"]
main.requests = None  # 確認 _drop_unsubscribed 用的是函式內 import,不吃模組級 requests

import requests as _rq  # noqa: E402
_orig_get = _rq.get

_rq.get = lambda url, headers=None, timeout=None: FakeListResp(
    {"ok": True, "emails": ["gone@x.com"], "count": 1})
check("KV 層:退訂者被剔除(大小寫無關)", main._drop_unsubscribed(SUBS), ["a@x.com", "b@x.com"])

_rq.get = lambda url, headers=None, timeout=None: FakeListResp({}, 500)
check("名單取不到 → fail-open 照寄", main._drop_unsubscribed(SUBS), SUBS)


def _boom(url, headers=None, timeout=None):
    raise RuntimeError("network down")


_rq.get = _boom
check("名單異常 → fail-open 照寄", main._drop_unsubscribed(SUBS), SUBS)

_rq.get = lambda url, headers=None, timeout=None: FakeListResp(
    {"ok": True, "emails": ["gone@x.com"]})
del os.environ["MARKETDAILY_INTERNAL_TOKEN"]
_saved = os.environ.pop("INTERNAL_TOKEN", None)
check("沒 token → 不過濾也不炸", main._drop_unsubscribed(SUBS), SUBS)
os.environ["MARKETDAILY_INTERNAL_TOKEN"] = SEC
if _saved:
    os.environ["INTERNAL_TOKEN"] = _saved
_rq.get = _orig_get


# ── ⑤ 公版存檔頁不可以帶著某個人的退訂 token ───────────────────────────────
shell = main.render_email_shell("2026-08-17", "<div>報告</div>")
check("render_email_shell 本身不含退訂連結(存檔頁共用它)", unsubscribe.LINK_TEXT in shell, False)
check_true("存檔頁不含任何 unsubscribe URL", "unsubscribe?" not in shell)


print()
if FAILS:
    print(f"❌ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 退訂迴歸全過")
