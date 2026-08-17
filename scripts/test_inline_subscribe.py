#!/usr/bin/env python3
"""就地訂閱表單自測(離線,零網路,<5s,exit 0=健康)。

守的是 `scripts/inline_subscribe.py` 與它的兩個呼叫端(`archive_cta.py` 存檔頁、
`seo_articles.py` blog 頁)。這批頁面是全站最大的兩個流量群,表單壞掉 = 陌生讀者
一個都訂不了而且**沒有任何錯誤會被拋出來**(前端靜默失敗),所以斷言要咬到:
① 表單元素齊全且一頁只有一份 ② 打的是會真的完成訂閱的那支端點 ③ 四種回應分支都有話講
④ 冪等(重跑不疊、改文案會更新)⑤ 不破壞既有解析器(meta description / marker postcondition)
⑥ 沒有 JS 的人仍有退路 ⑦ 文案守合規口徑。

用法:./.venv/bin/python scripts/test_inline_subscribe.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(1, str(Path(__file__).resolve().parent))
import inline_subscribe as I  # noqa: E402
import archive_cta as A  # noqa: E402
import seo_articles as S  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}{(' — ' + extra) if extra else ''}")


print("[1] JS 字面值轉義(內嵌 <script> 裡最容易一發打穿的地方)")
check("單引號被轉義", I._js_str("it's") == "'it\\'s'", I._js_str("it's"))
check("反斜線被轉義", I._js_str("a\\b") == "'a\\\\b'", I._js_str("a\\b"))
check("換行不會斷行", "\n" not in I._js_str("a\nb"))
check("</script> 不會提早收標籤", "</script>" not in I._js_str("x</script>y"))
check("</ 一律轉義", I._js_str("</div>") == "'<\\/div>'", I._js_str("</div>"))

print("[2] 表單結構層")
f = I.form_fields(button_label="訂閱 →", theme="dark", lang="zh")
for eid in (I._ID_FORM, I._ID_EMAIL, I._ID_BTN, I._ID_MSG):
    check(f"含 id={eid} 恰一次", f.count(f'id="{eid}"') == 1)
check("email 欄位是 type=email", 'type="email"' in f)
check("按鈕是 submit(Enter 鍵也能送出)", 'type="submit"' in f)
check("按鈕文字有帶進去", "訂閱 →" in f)
check("訊息列預設隱藏", "display:none" in f.split(I._ID_MSG)[1][:120])
check("訊息列有 aria-live(螢幕閱讀器聽得到結果)", 'aria-live="polite"' in f)
fp = I.form_fields(button_label="x", msg_tag="p")
check("msg_tag=p 時不產生巢狀 div", "<p id=\"mdsub-msg\"" in fp and "<div id=\"mdsub-msg\"" not in fp)
check("msg_tag=p 有正確收尾標籤", "</p>" in fp)

print("[3] 表單行為層")
js = I.form_script(utm_source="src", utm_medium="med", utm_campaign="camp",
                   utm_content="cont", success_msg="成功了", lang="zh")
check("打的是 subscribe-free-direct(一次呼叫就進名單的那支)",
      "/subscribe-free-direct" in js)
check("不是打 set-password(那支要密碼才算訂閱)", "set-password" not in js)
check("POST + JSON", "method:'POST'" in js and "application/json" in js)
check("送出前擋掉無效 email", "test(email)" in js)
check("送出中鎖住按鈕(防連點重複註冊)", "b.disabled=true" in js)
check("成功分支說得出成功訊息", "成功了" in js)
check("退訂者分支有處理(不可謊稱訂閱成功)", "resubscribe_pending" in js)
check("收不到信分支有處理", "undeliverable_email" in js)
check("rate limit 分支有處理", "rate_limited" in js and "too_many_attempts" in js)
check("網路錯誤有 catch", ".catch(" in js)
check("失敗後解鎖按鈕可重試", js.count("b.disabled=false") >= 2)
check("預設歸因帶得進去", "'src'" in js and "'med'" in js and "'camp'" in js and "'cont'" in js)
check("網址有真 utm 時優先用真的", "real||" in js)
check("帶得上 visit_id(有 beacon 的頁面才 join 得回來)", "md-visit-id" in js)
check("script 標籤只收一次", js.count("</script>") == 1)
check("sessionStorage 讀取有 try/catch(私密模式不炸)",
      re.search(r"try\{vid=sessionStorage", js) is not None)
js_en = I.form_script(utm_source="s", utm_medium="m", utm_campaign="c",
                      utm_content="x", success_msg="done", lang="en")
check("英文語系走英文文案", "Please enter a valid email address." in js_en)

print("[4] 存檔頁(digest_*)頁尾區塊")
tw = A._bottom_block("2026-08-17", False)
us = A._bottom_block("2026-08-17", True)
check("恰一份表單", tw.count(f'id="{I._ID_FORM}"') == 1)
check("postcondition 用的簽名字串恰一次", tw.count(A._BOTTOM_SIG) == 1)
check("台股版講早上 7 點", "明天早上 7 點" in tw)
check("美股版講晚上 8 點", "今天晚上 8 點" in us)
check("台美版本的成功訊息不同(複製貼上會同時錯)",
      "明天早上 7 點" not in us and "今天晚上 8 點" not in tw)
check("歸因 campaign 跟著日期/版別走",
      "digest_2026-08-17'" in tw and "digest_2026-08-17_us'" in us)
check("noscript 保留連結退路", "<noscript>" in tw and "marketdaily.ai/?utm_source=digest_archive" in tw)
check("noscript 退路文字不撞簽名字串(會讓 postcondition 數成 2)",
      tw.count(A._BOTTOM_SIG) == 1 and "到 marketdaily.ai 訂閱" in tw)
check("合規:早鳥口徑仍在", "早鳥用戶永久保留免費使用權" in tw)
check("合規:不出現保證/穩賺類字眼",
      not any(w in tw for w in ("保證", "穩賺", "必漲", "獲利保證")))
check("不需信用卡的承諾仍在", "不需信用卡" in tw)

print("[5] 存檔頁注入冪等 + 既有守衛不被破壞")
PAGE = ('<html><body><div class="header">H</div><p>正文</p>'
        '<div class="footer">F</div></body></html>')
once, why = A.inject(PAGE, "2026-08-17", False)
check("首次注入成功", once is not None and why is None, str(why))
twice, why2 = A.inject(once, "2026-08-17", False)
check("重跑不疊第二份", twice == once, str(why2))
check("注入後恰一組 marker",
      once.count(A.MARKER_START) == 2 and once.count(A.MARKER_END) == 2)
check("注入後頁面含表單", f'id="{I._ID_FORM}"' in once)
changed, _ = A.inject(once, "2026-08-18", False)
check("換日期會更新既有頁面(不是黏在舊文案)",
      changed is not None and "digest_2026-08-18'" in changed and "digest_2026-08-17'" not in changed)

print("[6] blog 頁注入")
BLOG = ('<html lang="zh-Hant"><head><style>.cta{}</style></head><body><article class="wrap">'
        '<p>' + "這是一段夠長的正文" * 5 + '</p>\n'
        '  <div class="cta">\n'
        '    <p style="x">想每天早上 7 點收到這類分析?</p>\n'
        '    <a href="https://marketdaily.ai/?utm_source=blog&utm_medium=cta&utm_campaign=seo_foo">免費訂閱 →</a>\n'
        '  </div>\n'
        '  <p class="disc">免責</p>\n</article></body></html>')
b1 = S.insert_bottom_form(BLOG, "foo")
check("錨點被換成表單", b1 != BLOG and f'id="{I._ID_FORM}"' in b1)
check("原本那顆連出去的按鈕不再是主要行動",
      '<a href="https://marketdaily.ai/?utm_source=blog&utm_medium=cta&utm_campaign=seo_foo">免費訂閱 →</a>' not in b1)
b2 = S.insert_bottom_form(b1, "foo")
check("冪等:重跑逐位元相同", b2 == b1)
check("恰一份表單", b1.count(f'id="{I._ID_FORM}"') == 1)
cta_region = b1[b1.find('<div class="cta">'):]
cta_region = cta_region[:cta_region.find("</div>") + 6]
check("`.cta` 裡沒有巢狀 <div>(非貪婪剝除會提早收尾)",
      cta_region.count("<div") == 1)
check("meta description 仍抽得到正文(不是抽到 CTA)",
      S._first_prose(b1).startswith("這是一段夠長的正文"))
check("blog 歸因 utm_source=blog", "'blog'" in b1 and "seo_foo" in b1)
check("noscript 退路在", "<noscript>" in b1)
EN = BLOG.replace('lang="zh-Hant"', 'lang="en"')
b_en = S.insert_bottom_form(EN, "foo")
check("英文頁走英文按鈕", "Subscribe free →" in b_en)
NO_ANCHOR = "<html><body><p>沒有 CTA 的頁面</p></body></html>"
check("找不到錨點就原樣返回(不硬塞)",
      S.insert_bottom_form(NO_ANCHOR, "foo") == NO_ANCHOR)
HALF = b1.replace(I.FORM_MARKER_END, "", 1)
check("marker 半毀時不動它(不製造吃掉正文的第二種災難)",
      S.insert_bottom_form(HALF, "foo") == HALF)

print("[7] 兩個呼叫端共用同一份表單邏輯(不得各自手刻)")
src_a = Path(__file__).resolve().parent.joinpath("archive_cta.py").read_text(encoding="utf-8")
src_s = Path(__file__).resolve().parent.joinpath("seo_articles.py").read_text(encoding="utf-8")
for name, src in (("archive_cta", src_a), ("seo_articles", src_s)):
    # 守行為不守措辭:檔頭註解提到端點名是合理的,自己手刻一份送出邏輯才是問題。
    check(f"{name} 用 inline_subscribe 產表單", "inline_subscribe." in src)
    # (seo_articles 另有一支 /track/visit 歸因 beacon,那是別的東西,不在此列)
    check(f"{name} 沒有自己手刻的訂閱送出邏輯",
          not re.search(r'fetch\([^)]*(subscribe|set-password)', src)
          and "XMLHttpRequest" not in src
          and "addEventListener('submit'" not in src)

if FAILED:
    print(f"\ninline_subscribe selftest: {len(FAILED)} FAILED — {FAILED}")
    sys.exit(1)
print("\ninline_subscribe selftest: ALL PASS")
