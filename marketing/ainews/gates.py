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

# 無來源貼文(清單型)專用:數字閘在這裡沒有意義 —— 「限 60 字」是給讀者的指令,
# 不是對世界的宣稱,而且沒有任何 facts 可以比對。
# 正解不是放寬成不管,是換一個判準:凡是「查不了的統計型宣稱」一律禁止。
_STAT_CLAIM = re.compile(
    r"(\d[\d,\.]*\s*%"                      # 87%
    r"|\d[\d,\.]*\s*(million|billion|trillion|users|people|companies|hours saved)"
    r"|[$€£]\s*\d"                            # $500
    r"|\d[\d,\.]*\s*(x|times)\s+(faster|better|more|cheaper)"
    r"|studies show|research shows|studies have shown|experts (say|agree)"
    r"|most people (who|that)? ?(use|say)"
    r")", re.I)


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


def check(draft, facts, brand, platform_limits=None, mode=None):
    """回 (ok, reasons[])。draft 需含 caption / threads_caption / headline / source_url。

    mode 自動由 facts 推斷:有 source_url = sourced(數字必須可溯源);
    沒有 = unsourced(清單型,改禁統計型宣稱)。
    """
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

    # 1. 來源必須是這次真的抓到的那則,不准模型自己補一個網址。
    #    清單型貼文沒有外部來源(facts.source_url is None)⇒ 草稿也必須是 None,
    #    模型自己生一個網址出來一樣要擋。
    if draft.get("source_url") != facts.get("source_url"):
        reasons.append(f"source_url 與 facts 不符:{draft.get('source_url')!r}")

    # 1b. 文案裡不准出現 facts 以外的網址(模型很愛「補一個看起來合理的連結」)
    allowed_urls = {facts.get("source_url"), brand.get("site")}
    allowed_urls.discard(None)
    _chain_txt = " ".join(c for c in (draft.get("threads_chain") or []) if isinstance(c, str))
    for u in re.findall(r"https?://[^\s)\]]+", f"{cap} {th} {_chain_txt}"):
        if not any(u.startswith(a) for a in allowed_urls):
            reasons.append(f"文案出現 facts 以外的網址:{u[:60]}")

    # 2. 長度
    for k, lim in limits.items():
        v = draft.get(k, "") or ""
        if len(v) > lim:
            reasons.append(f"{k} 超長 {len(v)}/{lim}")

    # 3. 數字
    mode = mode or ("sourced" if facts.get("source_url") else "unsourced")
    if mode == "sourced":
        # 有來源 → 每個數字都要能在 facts 裡找到(年份與清單序號除外)
        allowed = _facts_numbers(facts)
        checked = {f: draft.get(f, "") for f in ("caption", "threads_caption", "headline")}
        for i, seg in enumerate(draft.get("threads_chain") or []):
            checked[f"threads_chain[{i+1}]"] = seg if isinstance(seg, str) else ""
        for field, val in checked.items():
            for n in _numbers(val):
                if n in allowed or _YEARISH.match(n):
                    continue
                if n in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
                    continue
                reasons.append(f"{field} 出現 facts 裡沒有的數字:{n}")
    else:
        # 無來源 → 數字放行(那是給讀者的指令),但任何查不了的統計型宣稱一律擋
        _fields = {f: draft.get(f, "") for f in ("caption", "threads_caption", "headline")}
        for i, seg in enumerate(draft.get("threads_chain") or []):
            _fields[f"threads_chain[{i+1}]"] = seg if isinstance(seg, str) else ""
        for field, val in _fields.items():
            m = _STAT_CLAIM.search(val or "")
            if m:
                reasons.append(f"{field} 出現無法查證的統計型宣稱:{m.group(0)[:40]}")
        for it in (draft.get("items") or []):
            m = _STAT_CLAIM.search(json.dumps(it, ensure_ascii=False))
            if m:
                reasons.append(f"清單項目出現無法查證的統計型宣稱:{m.group(0)[:40]}")

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

    # 6b. Threads 串
    chain = draft.get("threads_chain")
    if chain is not None:
        if not isinstance(chain, list) or not (2 <= len(chain) <= 5):
            reasons.append(f"threads_chain 段數不合(需 2–5,實際 {len(chain) if isinstance(chain, list) else 'not a list'})")
        else:
            for i, seg in enumerate(chain):
                if not isinstance(seg, str) or not seg.strip():
                    reasons.append(f"threads_chain 第 {i+1} 段是空的")
                    continue
                if len(seg) > 500:
                    reasons.append(f"threads_chain 第 {i+1} 段超長 {len(seg)}/500")
                if re.findall(r"#[A-Za-z0-9_]+", seg):
                    reasons.append(f"threads_chain 第 {i+1} 段不該有 hashtag")
            joined = "\n".join(c for c in chain if isinstance(c, str))
            n_handle = joined.count(f"@{brand['handle']}")
            if n_handle != 1:
                reasons.append(f"threads_chain 的品牌 handle 出現 {n_handle} 次(應剛好 1 次,且在最後一段)")
            elif f"@{brand['handle']}" not in chain[-1]:
                reasons.append("threads_chain 的品牌 handle 不在最後一段")

    # 7. Threads 版不該整包 hashtag(平台慣例不同,照抄 IG 只是雜訊)
    if len(re.findall(r"#[A-Za-z0-9_]+", th)) > 2:
        reasons.append("threads_caption hashtag 超過 2 個")

    return (not reasons), reasons
