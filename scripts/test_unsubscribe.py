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

# 正規化的字元集必須與 Worker 端 `UNSUB_TRIM_CHARS` 逐字相同(2026-08-17 驗證者 F6)。
# 不可以退回 `.strip()`:Python strip() 不吃 U+FEFF、JS trim() 吃 ⇒ 帶 BOM 的 email
# 由 Python 簽含 BOM 的字串、Worker 驗不含 BOM 的 ⇒ 那個人的退訂連結**永遠**驗不過。
# 反方向(U+001C–1F / U+0085)是 Python 吃得比 JS 多,同樣要在這條線上收斂成同一個集合。
for _ch, _why in (("﻿", "BOM:JS trim 吃、Python strip 不吃"),
                  ("\x1c", "U+001C:Python strip 吃、JS trim 不吃"),
                  ("\x85", "U+0085:同上"),
                  (" ", "NBSP"), ("　", "全形空白"), (" ", "行分隔符")):
    check(f"正規化吃掉 {_why}", unsubscribe.norm_email(_ch + "reader@example.com" + _ch),
          "reader@example.com")
check("正規化不動 email 內部字元", unsubscribe.norm_email(" A.b+tag@Ex.com "), "a.b+tag@ex.com")

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


# ── ⑥ 端到端:寄信路徑真的呼叫了上面那些零件 ────────────────────────────────
# 為什麼要有這一段(2026-08-17 驗證者 F2):①~⑤ 全是零件級的。把 `_flush_outbox` 裡
# `inject_footer_link` 整行刪掉(=#396 原封不動復活)、或把退訂過濾拆掉,上面 33 項照樣全綠 ——
# 測試檔宣稱守的是「每封寄出的信真的帶著它」,而那正是它唯一沒守到的一格。
# 這裡打樁 hold / clearance,讓 `_flush_outbox` 在零網路、零等待下真的跑一遍。
_stash = {k: getattr(main, k) for k in
          ("_hold_until_send_time", "_failover_send_clearance", "_local_send_clearance",
           "_enforce_send_deadline", "_late_send_notice", "_drop_unsubscribed",
           "_push_admin_alert")}
main._hold_until_send_time = lambda *a, **k: None
main._failover_send_clearance = lambda *a, **k: True
main._local_send_clearance = lambda *a, **k: True
main._enforce_send_deadline = lambda *a, **k: None
main._late_send_notice = lambda *a, **k: ""
ALERTS = []
main._push_admin_alert = lambda msg: ALERTS.append(msg)
os.environ["MARKETDAILY_INTERNAL_TOKEN"] = SEC

SENT = []


def fake_send(email, date, html, api_key, subject=None):
    SENT.append({"email": email, "html": html, "subject": subject})
    return True


BODY = '<html><body><div class="footer">footer</div></body></html>'
main._drop_unsubscribed = lambda subs: subs
SENT.clear()
main._flush_outbox([("a@x.com", BODY, "S"), ("b@x.com", BODY, "S")], "2026-08-17", fake_send, "k")
check("寄出 2 封", len(SENT), 2)
check_true("每封都帶退訂連結",
           all(unsubscribe.LINK_TEXT in s["html"] for s in SENT),
           "inject_footer_link 沒被寄信路徑呼叫到 = #396 原地復活")
# 綁對人:a 收到的必須是 a 自己的 token,不能是 b 的(否則他一點就退掉別人)
for s in SENT:
    check_true(f"{s['email']} 拿到自己的 token",
               unsubscribe.unsub_token(s["email"], SEC) in s["html"])
check_true("a 的信不含 b 的 token",
           unsubscribe.unsub_token("b@x.com", SEC) not in SENT[0]["html"])

# 退訂者不會進到寄出那一步(過濾在 hold **之後**:名單是生成起點抓的,那時他可能還沒退訂)
main._drop_unsubscribed = lambda subs: [e for e in subs if e != "gone@x.com"]
SENT.clear()
n = main._flush_outbox([("a@x.com", BODY, "S"), ("gone@x.com", BODY, "S")],
                       "2026-08-17", fake_send, "k")
check("退訂者不寄:只寄 1 封", (n, len(SENT)), (1, 1))
check("寄給留下的那位", SENT[0]["email"], "a@x.com")
SENT.clear()
main._drop_unsubscribed = lambda subs: []
check("全員退訂 → 一封都不寄", (main._flush_outbox([("gone@x.com", BODY, "S")],
                                                  "2026-08-17", fake_send, "k"), len(SENT)), (0, 0))

# run() 那層(生成前先剔除)是省成本的早濾,choke point 才是保證。兩層都要在。
import inspect  # noqa: E402
_run_src = inspect.getsource(main.run)
check_true("run() 生成前也先剔除退訂者(省下白生成的日報)",
           "_drop_unsubscribed(get_all_subscribers" in _run_src)

# 缺 token = 連結、header、KV 過濾三半同時靜默消失 ⇒ 必須推播,不可以只 print(驗證者 F4)
main._drop_unsubscribed = lambda subs: subs
del os.environ["MARKETDAILY_INTERNAL_TOKEN"]
_saved2 = os.environ.pop("INTERNAL_TOKEN", None)
ALERTS.clear()
SENT.clear()
main._flush_outbox([("a@x.com", BODY, "S")], "2026-08-17", fake_send, "k")
check("沒 token 仍照寄(死線:絕不缺信)", len(SENT), 1)
check("沒退訂路徑 → 推播 admin(沉默的守衛=沒有守衛)", len(ALERTS), 1)
# 只斷言「有一則告警」不夠:缺 token 時後面的 postcheck 也會發一則(內容不同),
# 兩種情形都是 len==1 ⇒ 那樣的斷言殺不掉「把自檢整個拿掉」這個突變。要認到是哪一則。
check_true("告警指出的是 token 算不出來,不是注入失效",
           ALERTS and "INTERNAL_TOKEN" in ALERTS[0], ALERTS[0] if ALERTS else "(無告警)")
os.environ["MARKETDAILY_INTERNAL_TOKEN"] = SEC
if _saved2:
    os.environ["INTERNAL_TOKEN"] = _saved2

# 注入落點失效(版型換掉)→ token 算得出來但信裡沒連結 ⇒ postcheck 要抓到
_orig_inject = unsubscribe.inject_footer_link
unsubscribe.inject_footer_link = lambda html, email, secret=None: html
ALERTS.clear()
SENT.clear()
main._flush_outbox([("a@x.com", BODY, "S")], "2026-08-17", fake_send, "k")
check("注入失效仍照寄", len(SENT), 1)
check("注入失效 → postcheck 推播", len(ALERTS), 1)
unsubscribe.inject_footer_link = _orig_inject

for k, v in _stash.items():
    setattr(main, k, v)


print()
if FAILS:
    print(f"❌ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 退訂迴歸全過")
