"""確定性閘:LLM 產完文案後,不靠另一個 LLM 就能擋掉的東西全部在這裡擋。

原則(全部來自踩過的坑):
- fail-closed:任何一條不過就退回,不放行、不「盡量修」。
- 數字必須在 facts 裡出現過(捏造數字是這個帳號唯一會死透的方式)。
- @handle 不交給模型(模型掰一個 handle 出來,我們就公開 tag 到無關路人身上)。
- 每條 reason 要能指出是哪一句出事,只回「不過」的閘門沒人修得動。
"""
import json
import re

# 合規:本帳號不做個股建議(投顧法),AI 新聞帳也不准夾帶操作字眼
FORBIDDEN = [
    "buy now", "sell now", "price target", "guaranteed", "guaranteed return",
    "risk-free", "sure thing", "to the moon", "financial advice", "not financial advice",
    "get rich", "double your money", "10x your", "must buy", "must sell",
    "買進", "賣出", "目標價", "保證", "穩賺", "必漲", "必跌", "財富自由",
]

# 只有明確確認過的官方帳號才准出現 @;其餘一律純文字公司名
ALLOWED_MENTIONS = {
    "openai", "anthropic", "google", "googledeepmind", "meta", "microsoft",
    "nvidia", "huggingface", "perplexity.ai", "xai", "tesla",
}

# 當事人不 tag 的情境:把公司 tag 進它自己的醜聞 = 把對方通知欄當曝光工具
NO_MENTION_MARKERS = ["lawsuit", "sues", "sued", "probe", "investigation", "fined",
                      "antitrust", "scandal", "leak", "breach", "fraud", "layoff",
                      "shut down", "banned", "recall", "resign"]

_NUM = re.compile(r"\d[\d,\.]*")
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def _numbers(text):
    out = set()
    for m in _NUM.findall(text or ""):
        t = m.strip(".,").replace(",", "")
        if not t:
            continue
        out.add(t)
    return out


def _facts_numbers(facts):
    blob = json.dumps(facts, ensure_ascii=False)
    return _numbers(blob)


def check(draft, facts, brand, platform_limits=None):
    """回 (ok, reasons[])。draft 需含 caption / threads_caption / headline / source_url。"""
    limits = platform_limits or {"caption": 2200, "threads_caption": 500}
    reasons = []
    cap = draft.get("caption", "") or ""
    th = draft.get("threads_caption", "") or ""
    head = draft.get("headline", "") or ""

    if not cap.strip():
        reasons.append("caption 空的")
    if not th.strip():
        reasons.append("threads_caption 空的")
    if not head.strip():
        reasons.append("headline 空的")

    # 1. 來源必須是這次真的抓到的那則,不准模型自己補一個網址
    if draft.get("source_url") != facts.get("source_url"):
        reasons.append(f"source_url 與 facts 不符:{draft.get('source_url')!r}")

    # 2. 長度
    for k, lim in limits.items():
        v = draft.get(k, "") or ""
        if len(v) > lim:
            reasons.append(f"{k} 超長 {len(v)}/{lim}")

    # 3. 數字必須在 facts 出現過(年份與清單序號除外)
    allowed = _facts_numbers(facts)
    for field in ("caption", "threads_caption", "headline"):
        for n in _numbers(draft.get(field, "")):
            if n in allowed or _YEARISH.match(n):
                continue
            if n in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
                continue
            reasons.append(f"{field} 出現 facts 裡沒有的數字:{n}")

    # 4. 禁詞
    low = f"{cap}\n{th}".lower()
    for w in FORBIDDEN:
        if w.lower() in low:
            reasons.append(f"禁詞:{w}")

    # 5. @handle 白名單 + 醜聞不 tag
    blob_ctx = f"{facts.get('title','')} {facts.get('summary','')}".lower()
    scandal = any(m in blob_ctx for m in NO_MENTION_MARKERS)
    for h in re.findall(r"@([A-Za-z0-9_.]+)", f"{cap} {th}"):
        hl = h.lower().rstrip(".")
        if hl == brand["handle"].lower():
            continue
        if scandal:
            reasons.append(f"負面題材不得 tag 當事人:@{h}")
        elif hl not in ALLOWED_MENTIONS:
            reasons.append(f"@{h} 不在已確認官方帳號白名單")

    # 6. 品牌 CTA 與 hashtag
    if f"@{brand['handle']}" not in cap:
        reasons.append("caption 未含 follow CTA 的品牌 handle")
    tags = re.findall(r"#[A-Za-z0-9_]+", cap)
    if not (3 <= len(tags) <= 8):
        reasons.append(f"hashtag 數量 {len(tags)},應在 3–8")

    # 7. Threads 版不該整包 hashtag(平台慣例不同,照抄 IG 只是雜訊)
    if len(re.findall(r"#[A-Za-z0-9_]+", th)) > 2:
        reasons.append("threads_caption hashtag 超過 2 個")

    return (not reasons), reasons
