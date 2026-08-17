#!/usr/bin/env python3
"""就地訂閱表單(inline subscribe)——內容頁不必跳走就能訂閱。

## 為什麼(2026-08-18 成長輪,轉換乾旱 22 天後實查)
真人流量幾乎不在 landing page:`funnel_attribution` 顯示 landing 的 organic beacon 只有
~13/日,而全站最大的兩個頁面群是 `docs/output/digest_*`(公版存檔)與 `docs/blog/*`(68 篇
programmatic SEO)。這兩群頁面原本**只有連出去的 CTA**(`<a href="marketdaily.ai/?utm...">`),
讀者要訂閱得走:點連結 → 跨頁 → 輸 email → **設密碼(兩欄)** → 才真的進名單
(`/set-password` 才 addToBrevo)。一份**免費**電子報要走 4 步,每一步都在掉人。

`/subscribe-free-direct` 早就存在而且**一次呼叫就完成訂閱**(deliverable 檢查 → rate limit →
addToBrevo → `plan:free` → welcome 信 → recordConvert),只是前端只有 index.html 用得到。
本模組把它搬到讀者眼前:一欄 email、一顆按鈕、原地完成。

## 單一事實來源
存檔頁(`archive_cta.py`)與 blog 頁(`seo_articles.py`)共用這裡的同一份 HTML/JS 產生器。
⚠️ 不要在任一呼叫端手刻第二份 —— 同一份邏輯手刻兩次的下場是兩份同時錯(memory
`hub_guard_incidents` 的 cron_call_resolver 前車)。

## 刻意的邊界
- **不注入 visit beacon**:存檔頁目前沒有 beacon,加了會讓 `attr:visit` 的曝光量在某一天
  階梯式跳升,而漏斗靜默偵測器(`funnel.silent_exposure` / `event_rate_shift_flagged`)是
  拿曝光數在做檢定 —— 那會製造一次假訊號。歸因改走「轉換時直接帶 utm」,
  `recordConvert` 本來就接受無 visit_id 的 utm 欄位,渠道級成效照樣量得到。
- **不碰 email 版**:只後製 `docs/` 的靜態頁;寄出去的信裡永遠沒有這段 script。
- 沒有 JS 也要能訂閱:`<noscript>` 保留原本的連結退路。

## 合規(根 CLAUDE.md 全面免費化口徑)
文案只能講「限時免費 + 早鳥永久保留」,不得暗示未來個股分析會收費。
"""

API_BASE = "https://api.marketdaily.ai"

# 呼叫端用來做冪等剝除/postcondition 的具名 marker(成對)。
FORM_MARKER_START = "<!-- md-inline-subscribe:start -->"
FORM_MARKER_END = "<!-- md-inline-subscribe:end -->"

# 三個 element id 全域唯一:一頁只准有一份表單(呼叫端的 postcondition 會驗)。
_ID_FORM = "mdsub-form"
_ID_EMAIL = "mdsub-email"
_ID_BTN = "mdsub-btn"
_ID_MSG = "mdsub-msg"

_COPY = {
    "zh": {
        "placeholder": "your@email.com",
        "invalid": "請輸入有效的 Email",
        "sending": "送出中...",
        "ok_btn": "已訂閱 ✓",
        "resub_sent": "📬 你先前退訂過 —— 確認信已寄到這個信箱,點一下就恢復寄送。",
        "resub_fail": "你先前退訂過,但確認信寄不出去。請到「聯絡我們」告訴我們,我們手動幫你恢復。",
        "resub_btn": "已寄確認信 ✓",
        "undeliverable": "這個 Email 好像收不到信,請確認拼字是否正確。",
        "rate": "剛剛已經送出過一次了,請等幾分鐘再試。",
        "oops": "出了點問題,請稍後再試。",
        "neterr": "網路錯誤,請稍後再試。",
    },
    "en": {
        "placeholder": "your@email.com",
        "invalid": "Please enter a valid email address.",
        "sending": "Sending...",
        "ok_btn": "Subscribed ✓",
        "resub_sent": "📬 You unsubscribed earlier — we emailed a confirmation link. Click it to resume.",
        "resub_fail": "You unsubscribed earlier and we could not send the confirmation email — please contact us.",
        "resub_btn": "Confirmation sent ✓",
        "undeliverable": "This email looks undeliverable — please check the spelling.",
        "rate": "You just submitted this — please wait a few minutes and try again.",
        "oops": "Something went wrong. Please try again.",
        "neterr": "Network error. Please try again.",
    },
}


def _js_str(s: str) -> str:
    """字串進 JS 字面值:只用單引號包,轉義反斜線/單引號/換行/</。

    `</` 要轉義是因為這段 JS 內嵌在 `<script>` 裡,任何字面 `</script>` 會提早收掉標籤。
    """
    out = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return "'" + out.replace("</", "<\\/") + "'"


def form_script(*, utm_source: str, utm_medium: str, utm_campaign: str,
                utm_content: str, success_msg: str, lang: str = "zh") -> str:
    """表單的行為層。歸因:網址有真 utm 就用真的,沒有才用本頁預設(鏡射 blog beacon 的規則)。"""
    c = _COPY.get(lang, _COPY["zh"])
    return (
        "<script>\n(function(){\n"
        f'  var API={_js_str(API_BASE)};\n'
        f'  var f=document.getElementById({_js_str(_ID_FORM)}),'
        f'e=document.getElementById({_js_str(_ID_EMAIL)}),'
        f'b=document.getElementById({_js_str(_ID_BTN)}),'
        f'm=document.getElementById({_js_str(_ID_MSG)});\n'
        "  if(!f||!e||!b||!m){return;}\n"
        "  function say(t,ok){m.textContent=t;m.style.color=ok?'#6ee7b7':'#fca5a5';m.style.display='block';}\n"
        "  function attr(){\n"
        "    var p,real=null;\n"
        "    try{p=new URL(window.location.href).searchParams;real=p.get('utm_source');}catch(x){p=null;}\n"
        "    var vid=null;try{vid=sessionStorage.getItem('md-visit-id')||null;}catch(x){}\n"
        "    return {visit_id:vid,\n"
        f"      utm_source: real||{_js_str(utm_source)},\n"
        f"      utm_medium: (p&&p.get('utm_medium'))||(real?null:{_js_str(utm_medium)}),\n"
        f"      utm_campaign: (p&&p.get('utm_campaign'))||{_js_str(utm_campaign)},\n"
        f"      utm_content: (p&&p.get('utm_content'))||{_js_str(utm_content)}}};\n"
        "  }\n"
        "  f.addEventListener('submit',function(ev){\n"
        "    ev.preventDefault();\n"
        "    var email=(e.value||'').trim().toLowerCase();\n"
        f"    if(!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)){{say({_js_str(c['invalid'])},false);return;}}\n"
        "    var old=b.textContent;\n"
        f"    b.disabled=true;b.textContent={_js_str(c['sending'])};\n"
        "    var body=attr();body.email=email;\n"
        "    fetch(API+'/subscribe-free-direct',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})\n"
        "      .then(function(r){return r.json().catch(function(){return {};});})\n"
        "      .then(function(d){\n"
        "        d=d||{};\n"
        "        if(d.resubscribe_pending){\n"
        f"          say(d.sent?{_js_str(c['resub_sent'])}:{_js_str(c['resub_fail'])},!!d.sent);\n"
        f"          b.textContent={_js_str(c['resub_btn'])};return;\n"
        "        }\n"
        "        if(d.ok){\n"
        f"          say({_js_str(success_msg)},true);b.textContent={_js_str(c['ok_btn'])};e.disabled=true;return;\n"
        "        }\n"
        f"        if(d.error==='undeliverable_email'){{say({_js_str(c['undeliverable'])},false);}}\n"
        f"        else if(d.error==='rate_limited'||d.error==='too_many_attempts'){{say({_js_str(c['rate'])},false);}}\n"
        f"        else{{say({_js_str(c['oops'])},false);}}\n"
        "        b.disabled=false;b.textContent=old;\n"
        "      })\n"
        f"      .catch(function(){{say({_js_str(c['neterr'])},false);b.disabled=false;b.textContent=old;}});\n"
        "  });\n"
        "})();\n</script>"
    )


def form_fields(*, button_label: str, theme: str = "dark", lang: str = "zh",
                msg_tag: str = "div") -> str:
    """表單的結構層(inline style,不依賴呼叫端的 CSS —— 存檔頁沒有共用樣式表)。

    `msg_tag`:blog 頁必須傳 `"p"`。那邊 `_first_prose` 用非貪婪 `<div class="cta">.*?</div>`
    把 CTA 從 meta description 的候選正文裡剝掉,**巢狀 `<div>` 會讓它提早收尾**、把
    CTA 尾巴留在 prose 區(seo_articles.py 的頁首 CTA 已經為同一個理由踩過)。
    """
    c = _COPY.get(lang, _COPY["zh"])
    if theme == "dark":  # 深底面板(存檔頁的深藍卡)
        inp = ("width:100%;max-width:280px;box-sizing:border-box;padding:13px 14px;border-radius:10px;"
               "border:1px solid rgba(255,255,255,0.25);background:rgba(255,255,255,0.10);color:#ffffff;"
               "font-size:15px;outline:none;")
        btn = ("padding:13px 26px;border:0;border-radius:10px;background:#ffffff;color:#312e81;"
               "font-size:15px;font-weight:800;cursor:pointer;white-space:nowrap;")
    else:  # 站內深色頁上的漸層卡(blog)
        inp = ("width:100%;max-width:280px;box-sizing:border-box;padding:13px 14px;border-radius:10px;"
               "border:1px solid rgba(255,255,255,0.18);background:rgba(255,255,255,0.06);color:#fff;"
               "font-size:15px;outline:none;")
        btn = ("padding:13px 26px;border:0;border-radius:10px;"
               "background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;"
               "font-size:15px;font-weight:800;cursor:pointer;white-space:nowrap;")
    return (
        f'<form id="{_ID_FORM}" style="display:flex;flex-wrap:wrap;gap:10px;'
        f'justify-content:center;align-items:center;margin:0 0 10px;">'
        f'<input id="{_ID_EMAIL}" type="email" autocomplete="email" inputmode="email" '
        f'placeholder="{c["placeholder"]}" aria-label="Email" style="{inp}">'
        f'<button id="{_ID_BTN}" type="submit" style="{btn}">{button_label}</button>'
        f'</form>'
        f'<{msg_tag} id="{_ID_MSG}" role="status" aria-live="polite" '
        f'style="display:none;font-size:13px;line-height:1.7;margin:0 0 6px;"></{msg_tag}>'
    )
