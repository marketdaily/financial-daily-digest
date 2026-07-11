#!/usr/bin/env python3
"""個人語音快報 manifest 層(main.py 寄送迴圈掛鉤用,全部 fail-open)。

流程:main.py 每位用戶最終 email HTML(audit 後)→ 這裡抽出他實際收到的個股
(名稱/漲跌/評估)+算不可猜 token → email 裡的 audio 連結加 &u={token} →
全部收進 manifest_{date}_{ed}.json(本機 gitignored,含 email 屬個資,chmod 600)。
audio_brief/personal.py 事後讀 manifest 逐人拼裝專屬音檔 pa_{date}_{ed}_{token}.mp3。

安全:
- token = HMAC-SHA256(MD_AUDIO_TOKEN_SECRET, email|date|ed) 前 16 hex(64-bit,不可枚舉)。
- 個人音檔 key 用 pa_ 前綴——media-worker /_list 白名單只放行 audio_,pa_ 不可列舉,
  只有拿到 email 連結的本人打得開(持股組合不外洩)。
- secret 未設 → 全部 no-op,信件維持公版連結(功能失效但絕不擋寄信)。
"""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

SECRET_ENV = "MD_AUDIO_TOKEN_SECRET"
PICKS_EMAIL = "__picks__"  # 精選版全員內容相同 → 共用一支音檔/一個 token


def audio_token(email: str, date: str, edition: str) -> str:
    secret = os.environ.get(SECRET_ENV, "")
    if not secret:
        return ""
    msg = f"{email.strip().lower()}|{date}|{edition}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


# 容忍 premailer 內聯後的屬性順序/夾帶 style(extract.py 的原版 regex 靠 class 開頭,這裡放寬)
_CARD_RE = re.compile(r'<div[^>]*class="[^"]*signal-card[^"]*"[^>]*>(.*?)(?:signal-body|</table>|$)', re.S)
_NAME_RE = re.compile(r'class="[^"]*signal-ticker[^"]*".*?>([^<>]+)<', re.S)
_TICK_RE = re.compile(r"monospace[^>]*>([A-Z0-9.]{1,10})<")
_MOVE_RE = re.compile(r'class="[^"]*signal-day-move (?:up|down)[^"]*"[^>]*>\s*[▲▼]?\s*([+-][\d.]+)%')
_VERDICT_RE = re.compile(r'class="[^"]*signal-verdict-chip[^"]*"[^>]*>([^<]+)<')
_EMOJI_RE = re.compile("[☀-➿️⬀-⯿\U0001f000-\U0001faff]")


def extract_email_movers(html: str) -> list:
    """從最終寄出的 email HTML 抽出用戶實際收到的個股卡(audit/fallback 後為準)。"""
    movers, seen = [], set()
    for card in _CARD_RE.findall(html or ""):
        name_m = _NAME_RE.search(card)
        move_m = _MOVE_RE.search(card)
        if not (name_m and move_m):
            continue
        name = _EMOJI_RE.sub("", name_m.group(1)).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        tick_m = _TICK_RE.search(card)
        verdict_m = _VERDICT_RE.search(card)
        movers.append({
            "name": name,
            "ticker": tick_m.group(1) if tick_m else "",
            "move": move_m.group(1),
            "verdict": _EMOJI_RE.sub("", verdict_m.group(1)).strip() if verdict_m else "",
        })
    return movers


_LINK_TEXT_PERSONAL = "沒空看?你的持股語音快報(免費)"
_LINK_TEXT_PICKS = "沒空看?AI 精選語音快報(免費)"


def personalize_email_audio(html: str, email: str, date: str, edition: str,
                            picks_mode: bool = False):
    """回傳 (new_html, manifest_entry|None)。任何一步不成立 → (原 html, None),
    信件維持公版 audio 連結,絕不因語音層壞了影響寄信。"""
    try:
        token = audio_token(PICKS_EMAIL if picks_mode else email, date, edition)
        if not token:
            return html, None
        old_qs = (f"?date={date}&amp;ed={edition}", f"?date={date}&ed={edition}")
        if not any(f"audio.html{q}" in html for q in old_qs):
            return html, None  # 週六早報等無語音連結班次
        movers = extract_email_movers(html)
        if not movers:
            return html, None
        for q in old_qs:
            sep = "&amp;" if "&amp;" in q else "&"
            html = html.replace(f"audio.html{q}", f"audio.html{q}{sep}u={token}")
        html = html.replace("沒空看?3 分鐘語音版(免費)",
                            _LINK_TEXT_PICKS if picks_mode else _LINK_TEXT_PERSONAL)
        entry = {
            "token": token,
            "email": PICKS_EMAIL if picks_mode else email,
            "picks": bool(picks_mode),
            "stocks": movers,
        }
        return html, entry
    except Exception:
        return html, None


def write_manifest(entries: list, date: str, edition: str):
    """寫 manifest(同 token 去重:精選版多人共用一份)。無 entries 不寫檔。"""
    if not entries:
        return None
    dedup, seen = [], set()
    for e in entries:
        if e and e.get("token") and e["token"] not in seen:
            seen.add(e["token"])
            dedup.append(e)
    if not dedup:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"manifest_{date}_{edition}.json"
    path.write_text(json.dumps({"date": date, "edition": edition, "entries": dedup},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(path, 0o600)
    return path
