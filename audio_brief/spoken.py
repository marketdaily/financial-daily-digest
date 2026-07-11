#!/usr/bin/env python3
"""語音快報共用口語層(公版 build_script.py 與個人版 personal.py 共用)。

職責:把日報 HTML 世界的字串轉成「聽得懂」的旁白:
- verdict 內部術語 → 白話(「同型判斷近期實測失準,自動降級」不准直接唸給訂閱者)
- 新聞 vs 30秒重點去重(颱風休市唸兩次事故)
- 零資訊新聞黑名單(鯨魚大額交易類:無法行動、解釋循環)
- 同 verdict 個股分組壓縮(「續抱持有」連唸五次=機械式聽感)
全部確定性規則,不走 LLM。
"""
import re

_EMOJI_RE = re.compile("[☀-➿️⬀-⯿\U0001f000-\U0001faff]")

# 內部術語 → 白話(exact 片語優先,其餘走通則轉換)
_VERDICT_PHRASES = [
    ("觀望·同型判斷近期實測失準,自動降級", "系統轉趨保守,先觀望"),
    ("同型判斷近期實測失準,自動降級", "系統轉趨保守"),
    ("同型判斷近期失準", "系統轉趨保守"),
    ("站回 MA20 再議", "等股價站回二十日均線再考慮"),
    ("守停損,站回 MA20 再議", "守好停損,等股價站回二十日均線再考慮"),
    ("跌深超賣慎追空", "跌深超賣,先不追空"),
    ("跌深超賣別追空,守停損", "跌深超賣別追空,守好停損"),
    ("減碼/出場", "建議減碼或出場"),
]


def spoken_verdict(v: str) -> str:
    """把 signal-verdict-chip 文字轉成可唸的白話。未知字串走通則:去 emoji、
    「·」轉逗號、括號攤平、MA20/MA60 轉中文。"""
    if not v:
        return ""
    v = _EMOJI_RE.sub("", v).strip()
    for src, dst in _VERDICT_PHRASES:
        v = v.replace(src, dst)
    v = v.replace("·", ",")
    v = v.replace("(", ",").replace(")", "").replace("（", ",").replace("）", "")
    v = re.sub(r"MA\s*20", "二十日均線", v)
    v = re.sub(r"MA\s*60", "六十日均線", v)
    v = re.sub(r",{2,}", ",", v).strip(", ")
    return v


def spoken_pct(move: str) -> str:
    """"+3.20" → 「上漲3.20%」;±0 → 「持平」。"""
    v = (move or "").lstrip("+-")
    try:
        if float(v) == 0:
            return "持平"
    except ValueError:
        pass
    sign = "下跌" if str(move).startswith("-") else "上漲"
    return f"{sign}{v}%"


_NOISE_NEWS_RE = re.compile(r"大額交易|鯨魚|whale|大單異動", re.I)


def is_noise_news(headline: str) -> bool:
    """零資訊新聞:無法行動、解釋循環(「大額交易代表信心強」)。"""
    return bool(_NOISE_NEWS_RE.search(headline or ""))


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s or "")


def news_duplicates_bullets(headline: str, bullets: list) -> bool:
    """新聞標題與 30 秒重點講同一件事(前綴重疊)就跳過,不唸兩次。"""
    nh = _norm(headline)
    if len(nh) < 8:
        return False
    for b in bullets or []:
        nb = _norm(b)
        if nh[:10] in nb or nb[:10] in nh:
            return True
    return False


def pick_news(news: list, bullets: list, limit: int = 2) -> list:
    """公版新聞挑選:去噪音、去與 bullets 重複,取前 limit 則。"""
    out = []
    for n in news or []:
        hd = (n.get("headline") or "").strip()
        if not hd or is_noise_news(hd) or news_duplicates_bullets(hd, bullets):
            continue
        out.append(n)
        if len(out) >= limit:
            break
    return out


# 「沒故事」的 verdict:個股沒大波動時,逐檔唸只會變成機械式重複
_QUIET_VERDICTS = ("續抱持有", "暫時觀望")


def is_interesting(move: str, verdict: str, threshold: float = 2.0) -> bool:
    """值得逐檔唸:漲跌夠大,或評估不是安靜的續抱/觀望。"""
    try:
        big = abs(float((move or "0").lstrip("+"))) >= threshold
    except ValueError:
        big = False
    quiet = spoken_verdict(verdict) in _QUIET_VERDICTS
    return big or not quiet


def mover_line(m: dict, verdict_label: str) -> str:
    """單檔個股旁白行。"""
    seg = f"{m['name']},昨日{spoken_pct(m['move'])}"
    sv = spoken_verdict(m.get("verdict") or "")
    if sv:
        seg += f",{verdict_label}:{sv}"
    return seg + "。"


def grouped_quiet_lines(quiet: list, verdict_label: str) -> list:
    """把安靜個股按 verdict 分組壓縮:「台積電、蘋果、微軟,{label}都是續抱持有」。"""
    groups = {}
    for m in quiet:
        groups.setdefault(spoken_verdict(m.get("verdict") or ""), []).append(m["name"])
    lines = []
    for sv, names in groups.items():
        if not sv:
            lines.append(f"{'、'.join(names)},昨日波動不大。")
        elif len(names) == 1:
            lines.append(f"{names[0]},昨日波動不大,{verdict_label}:{sv}。")
        else:
            lines.append(f"{'、'.join(names)},昨日波動都不大,{verdict_label}都是:{sv}。")
    return lines


def split_movers(movers: list, detail_cap: int = 10) -> tuple:
    """個股拆成(逐檔唸 detail, 分組壓縮 quiet)。detail 保持原順序、封頂 detail_cap;
    全部都安靜時至少逐檔唸前 3 檔(不能整段只有分組句)。"""
    detail = [m for m in movers if is_interesting(m.get("move", ""), m.get("verdict", ""))]
    if not detail:
        detail = movers[:3]
    detail = detail[:detail_cap]
    detail_ids = {id(m) for m in detail}
    quiet = [m for m in movers if id(m) not in detail_ids]
    return detail, quiet


def stock_name_tokens(name: str, ticker: str = "") -> list:
    """「特斯拉 Tesla」→ [特斯拉, Tesla];配對新聞相關性用。"""
    toks = [t for t in re.split(r"[\s/()（）]+", name or "") if len(t) >= 2]
    if ticker and len(ticker) >= 2:
        toks.append(ticker)
    return toks


def news_mentions(n: dict, tokens: list) -> bool:
    text = (n.get("headline") or "") + (n.get("why") or "")
    return any(t in text for t in tokens)
