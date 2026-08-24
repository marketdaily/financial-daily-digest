#!/usr/bin/env python3
"""每則貼文按自己的主題生一張底圖(Higgsfield Nano Banana 2,headless)。

2026-08-24 老闆:「你要針對你 po 文的主題去生成圖」。
在此之前是 14 張固定素材照題材線配 —— 國際新聞永遠是那艘油輪。現在每則貼文用它自己的
內容生一張。

**分工不可混**:
  - 模型只供「畫面裡有什麼」(image_subject_en，一兩句英文)。
  - 這支程式供「怎麼拍」(rig block) 與「怎麼交件」(構圖/安全)。
    rig 與交付約束**永遠不由模型決定** —— 那是品牌一致性與可讀性的錨,
    交給模型等於每天換一個攝影師。

**四道防線**(缺一就會出事):
  1. 主體閘 `vet_subject()`:擋掉人物/文字/商標類主體。真人肖像＋命理或財經斷言=名譽權,
     商標入鏡=IP,畫面有字=AI 亂碼字。這些是確定性擋,不靠 prompt 拜託模型。
  2. 每日 credit 上限:超過就靜靜退回固定素材,不會有人半夜燒光額度。
  3. 快取:同一則貼文重產圖不重複扣款(promote/補發都會重跑產圖)。
  4. 失敗一律回 None → 呼叫端退回固定素材。**發文那條腿不准因為生圖掛掉而斷。**
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "gen_cache"
LEDGER = HERE / "state" / "imagegen_ledger.json"
MCP_URL = "https://mcp.higgsfield.ai/mcp"
MODEL = "nano_banana_2"
UA = "marketdaily-cardgen/1.0 (winrig)"

# 每天最多花這麼多 credit 在自動產圖上。8 則新聞 + 1 則命書 ≈ 18cr/天。
# 上限存在的理由不是省錢,是**故障時的爆炸半徑**:某天佇列爆量或迴圈重試,
# 沒有上限就是一夜燒光。超過上限不是報錯,是安靜退回固定素材(發文照常)。
DAILY_CREDIT_CAP = int(os.environ.get("CARDKIT_IMAGE_DAILY_CAP", "40"))
COST_PER_IMAGE = 2

# ── 片場規格(§4.5;兩組五欄全異,所以兩個帳號不像同一個攝影師拍的) ──────────
RIGS = {
    "marketdaily": (
        "Shot on a Sony Venice 2 with a Cooke S7/i 40mm T2.0 prime, framed 4:5. "
        "Photographed in the style of Greig Fraser and directed like Denis Villeneuve; "
        "reference: the night convoy sequence in Sicario. "
        "Kodak Vision3 500T stock, cool slate-teal grade with a single warm sodium accent, "
        "heavy atmospheric haze, deep negative fill so the shadows stay truly black. "
        "All lighting equipment sits outside the frame."),
    "mingshu": (
        "Shot on a Hasselblad H6D-100c with an HC 120mm f/4 macro, framed 4:5. "
        "Photographed with Hiroshi Sugimoto's tonal minimalism, lit like the ambient "
        "lamplight interiors of Wong Kar-wai's In the Mood for Love. "
        "Fujifilm Eterna stock, near-monochrome warm sepia-black grade, one soft practical "
        "source low in the frame, vast quiet negative space. "
        "All lighting equipment sits outside the frame."),
}

# 交付約束。零否定句 —— prose 模型沒有 negative 欄位,「no text」等於把 text 餵給它
# (genai_prompt_lint 的 prose_negation 抓過一次)。
DELIVERY = (
    "Composition for a text overlay: the upper 45 percent of the frame is one uninterrupted "
    "field of smooth deep black, empty and featureless, while the subject sits low in the "
    "lower third. Every surface in the frame is plain and unmarked; the only texture anywhere "
    "is the natural material of the objects themselves. The scene is unoccupied: everything in "
    "the frame is an object, a surface, architecture or weather. Overall exposure is dark, with "
    "light confined to small motivated pools, and the subject itself stays clearly legible "
    "inside its pool of light.")

# 主體閘:這些字出現在 image_subject_en 就退回固定素材。
# ⚠️ **整詞比對,不是子字串**。首版用 `w in low` 子字串比對,第一次真跑就把
#    "its still sur**face** split by one ripple" 判成人臉、退回庫存底圖 —— 而且是
#    「安靜地退回」,不看 log 根本不知道花錢做的功能沒在動。守衛咬太寬的傷害是無聲的。
BANNED = [
    # 真人 —— 肖像 + 財經/命理斷言 = 名譽權;而且 AI 畫的名人臉一眼假
    "portrait", "portraits", "face", "faces", "headshot", "president", "prime minister",
    "ceo", "chairman", "celebrity", "politician", "man", "woman", "men", "women",
    "person", "people", "crowd", "worker", "workers", "trader", "traders",
    # 商標 / 文字 —— IP 與 AI 亂碼字
    "logo", "wordmark", "brand", "signage", "billboard", "banner", "poster", "screen text",
    "headline", "newspaper", "magazine cover", "label", "lettering", "typography",
    # 具名公司/機構外觀(門面、總部)同樣是商標問題
    "nvidia", "apple store", "tesla", "google", "microsoft", "meta", "openai", "anthropic",
    "headquarters", "flag",
]
SUBJECT_MIN_WORDS, SUBJECT_MAX_WORDS = 8, 60


def vet_subject(subject):
    """回 (ok, reason)。**確定性**,不問 LLM。"""
    if not subject or not isinstance(subject, str):
        return False, "空的"
    s = subject.strip()
    if not s.isascii():
        return False, "必須是英文(非 ASCII)"
    n = len(s.split())
    if not SUBJECT_MIN_WORDS <= n <= SUBJECT_MAX_WORDS:
        return False, f"長度 {n} 字不在 {SUBJECT_MIN_WORDS}-{SUBJECT_MAX_WORDS}"
    low = s.lower()
    hit = [w for w in BANNED if re.search(r"\b" + re.escape(w) + r"\b", low)]
    if hit:
        return False, f"主體含禁詞 {hit[:3]}"
    return True, ""


def build_prompt(brand, subject):
    return f"{subject.strip().rstrip('.')} . {RIGS[brand]} {DELIVERY}"


# ── 每日額度帳本 ────────────────────────────────────────────────────────────
def _spent_today():
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return int(led.get(date.today().isoformat(), 0))


def _charge(n=COST_PER_IMAGE):
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        led = {}
    today = date.today().isoformat()
    led[today] = int(led.get(today, 0)) + n
    led = {k: v for k, v in sorted(led.items())[-40:]}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, ensure_ascii=False), encoding="utf-8")


# ── Higgsfield headless ────────────────────────────────────────────────────
def _token():
    r = subprocess.run(["higgsfield", "auth", "token"], capture_output=True, text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def _rpc(tok, payload, timeout=120):
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(), headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json",
        # ⚠️ UA 必填:Cloudflare 擋預設的 python-urllib 回 403(higgsfield_token_sync 同坑)
        "Accept": "application/json, text/event-stream", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(raw)


def _structured(resp):
    return (resp.get("result") or {}).get("structuredContent") or {}


def generate(brand, subject, key, out_path, timeout_s=180, log=print):
    """主體 → 2k 4:5 底圖。任何一步失敗回 None(呼叫端退回固定素材)。"""
    if os.environ.get("CARDKIT_IMAGEGEN_OFF") == "1":
        return None
    if brand not in RIGS:
        return None
    ok, why = vet_subject(subject)
    if not ok:
        log(f"  ⚠️ 產圖主體不合格({why}),改用固定素材")
        return None

    prompt = build_prompt(brand, subject)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{brand}_{hashlib.sha1(prompt.encode()).hexdigest()[:16]}.jpg"
    if cached.exists():
        log(f"  ♻️ 產圖快取命中({cached.name}),不扣 credit")
        return str(cached)

    if _spent_today() + COST_PER_IMAGE > DAILY_CREDIT_CAP:
        log(f"  ⚠️ 今日產圖已用 {_spent_today()}/{DAILY_CREDIT_CAP} credit,改用固定素材")
        return None

    tok = _token()
    if not tok:
        log("  ⚠️ 拿不到 Higgsfield token,改用固定素材")
        return None
    try:
        _rpc(tok, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "cardgen", "version": "1"}}}, timeout=60)
        sub = _rpc(tok, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "generate_image_batch", "arguments": {"requests": [{"index": 0, "params": {
                "model": MODEL, "prompt": prompt, "aspect_ratio": "4:5",
                "resolution": "2k", "use_unlim": False}}]}}}, timeout=120)
        jobs = _structured(sub).get("jobs") or []
        if not jobs or not jobs[0].get("job_id"):
            log(f"  ⚠️ 產圖送出失敗:{json.dumps(sub, ensure_ascii=False)[:180]}")
            return None
        job_id = jobs[0]["job_id"]
        _charge()          # 送出即計費,不等成功 —— 額度是送出當下就扣的
        url, deadline = None, time.time() + timeout_s
        while time.time() < deadline:
            w = _rpc(tok, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "jobs_wait", "arguments": {
                    "jobs": [{"index": 0, "job_id": job_id}], "timeout_seconds": 15}}}, timeout=60)
            st = _structured(w)
            row = (st.get("jobs") or [{}])[0]
            if row.get("status") == "completed" and row.get("result_url"):
                url = row["result_url"]
                break
            if row.get("status") in ("failed", "canceled"):
                log(f"  ⚠️ 產圖 job 失敗:{row.get('status')}")
                return None
        if not url:
            log("  ⚠️ 產圖逾時,改用固定素材")
            return None
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
        from PIL import Image
        from io import BytesIO
        im = Image.open(BytesIO(raw)).convert("RGB").resize((1080, 1350), Image.LANCZOS)
        im.save(cached, "JPEG", quality=86, optimize=True)
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            im.save(out_path, "JPEG", quality=86, optimize=True)
        log(f"  🖼️ 依貼文主題產圖完成({COST_PER_IMAGE}cr,今日 {_spent_today()}/{DAILY_CREDIT_CAP})")
        return str(cached)
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️ 產圖例外({type(e).__name__}: {e}),改用固定素材")
        return None
