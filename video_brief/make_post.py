#!/usr/bin/env python3
"""影片+caption 打包成當日 reel 貼文:硬性驗證 → 上傳 KV → 寫 post json。

所有驗證都是確定性的(數字逐字回對源日報、影片規格、非黑幀、URL 可達),
任何一關不過就 abort 不產出 post json —— 發文端找不到 json 自然不發。
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "out"
KV_NAMESPACE = "9f3b5e510de04803bd0b59d451911d58"
MEDIA_BASE = "https://media.marketdaily.ai"
MOOD_EMOJI = {"bearish": "📉", "bullish": "📈", "neutral": "😐"}
FORBIDDEN = ("LINE", "Pro 方案", "邀請制", "勝率", "保證", "穩賺")


def die(msg):
    sys.exit(f"✗ VERIFY FAIL: {msg}")


def build_caption(brief):
    d = datetime.strptime(brief["date"], "%Y-%m-%d")
    label = "美股晚報" if brief["edition"] == "us" else "台股晨報"
    hook = brief["bullets"][0].replace("避坑：", "避坑 ")
    movers = brief["movers"][:3]
    mover_line = " · ".join(
        f"{m['name'].split()[0]} {'+' if not m['move'].startswith(('-', '+')) else ''}{m['move']}%"
        for m in movers)
    return (
        f"{MOOD_EMOJI.get(brief['mood'], '😐')} {d.month}/{d.day} {label}｜30 秒看完今天重點\n\n"
        f"{hook}\n"
        f"📊 {mover_line}\n\n"
        f"每支你選的股票都有完整進出場計畫\n"
        f"免費訂閱 👉 marketdaily.ai\n\n"
        f"#台股 #美股 #財經 #投資 #股市 #MarketDaily"
    )


def verify(brief, caption, mp4):
    src = (REPO / "docs" / "output" / brief["source_file"]).read_text(encoding="utf-8")

    for tok in re.findall(r"\d+(?:\.\d+)?%", caption):
        if tok.rstrip("%") not in src:
            die(f"caption 數字 {tok} 不在源日報")
    for bad in FORBIDDEN:
        if bad in caption:
            die(f"caption 含禁用詞「{bad}」")

    # 台股休市日(颱風等)不可出現開盤時序字眼(2026-07-10 事故;上游 main.py 已有
    # 確定性修復層,這裡是媒體端最後防線,抓到=生成端有洞,不出貨)
    if brief.get("tw_market_closed") and brief["edition"] == "tw":
        joined = caption + " ".join(brief.get("bullets", []))
        m = re.search(r"今早.{0,6}開盤|今日早盤", joined)
        if m:
            die(f"台股休市日 caption/bullets 含開盤時序字眼「{m.group(0)}」")

    if not mp4.exists():
        die("mp4 不存在")
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration:stream=width,height,codec_name",
         "-of", "json", str(mp4)], capture_output=True, text=True).stdout)
    dur = float(probe["format"]["duration"])
    if not 34 <= dur <= 40:
        die(f"時長異常 {dur}s")
    v = [s for s in probe["streams"] if s.get("codec_name") == "h264"]
    a = [s for s in probe["streams"] if s.get("codec_name") == "aac"]
    if not v or v[0]["width"] != 1080 or v[0]["height"] != 1920:
        die("影像流規格錯誤")
    if not a:
        die("缺音軌")

    # 0s=IG 預設封面幀、3s=thumb_offset 指定封面幀:太黑或太白都不准出貨(封面不能是白的)
    for ts in ("0", "3", "15", "33"):
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", ts, "-i", str(mp4), "-frames:v", "1",
             "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
             "-f", "null", "-"], capture_output=True, text=True)
        m = re.search(r"YAVG=([\d.]+)", r.stderr)
        if not m or float(m.group(1)) < 8:
            die(f"{ts}s 處畫面近全黑(YAVG={m.group(1) if m else '?'})")
        if float(m.group(1)) > 180:
            die(f"{ts}s 處畫面近全白(YAVG={m.group(1)}),封面/畫面不可白底")
    print("✓ 驗證全過(數字回對/禁用詞/規格/非黑幀/非白幀)")


def upload(mp4, key):
    # wrangler kv put 會在寫入已成功時偶發回非 0(tts.py 2026-07-09 兩連中同款),
    # rc 只當參考印出來,成敗以下方 HEAD content-length 相符為準
    url = f"{MEDIA_BASE}/{key}"
    size = mp4.stat().st_size
    for attempt in range(1, 4):
        r = subprocess.run(
            ["npx", "wrangler", "kv", "key", "put", key, "--path", str(mp4),
             "--namespace-id", KV_NAMESPACE, "--remote"],
            capture_output=True, text=True, cwd=REPO)
        if r.returncode == 0:
            break
        print(f"⚠ wrangler put rc={r.returncode} (attempt {attempt}/3): "
              f"{(r.stderr or r.stdout).strip()[-300:]}")
        time.sleep(5)
    for i in range(6):
        time.sleep(10)
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "MarketDailyBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if int(r.headers.get("content-length", 0)) == size:
                    print(f"✓ 上線 {url} ({size} bytes)")
                    return url
        except Exception:
            pass
    die(f"上傳後 {url} 驗不到正確檔案")


def main():
    briefs = sorted(OUT.glob("brief_*.json"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (briefs[-1] if briefs else None)
    if not src:
        sys.exit("找不到 brief json")
    brief = json.loads(src.read_text(encoding="utf-8"))
    mp4 = OUT / f"brief_{brief['date']}_{brief['edition']}.mp4"
    caption = build_caption(brief)
    verify(brief, caption, mp4)
    key = f"reel_{brief['date']}_{brief['edition']}.mp4"
    url = upload(mp4, key)
    post = {
        "id": f"reel_daily_{brief['date']}_{brief['edition']}",
        "date": brief["date"],
        "edition": brief["edition"],
        "video_url": url,
        "caption": caption,
        "platforms": ["instagram", "facebook", "youtube", "x", "tiktok"],
        "verified": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    out = OUT / f"post_{brief['date']}_{brief['edition']}.json"
    out.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {out.name}")
    print("---caption---")
    print(caption)


if __name__ == "__main__":
    main()
