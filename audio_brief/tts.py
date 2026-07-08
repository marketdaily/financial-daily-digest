#!/usr/bin/env python3
"""旁白稿 → mp3(edge-tts zh-TW)→ 確定性驗證 → KV 上傳 media.marketdaily.ai。

驗證:時長 100-260s、非靜音(RMS > -40dB)、URL 可達且大小相符。任一不過=abort。
"""
import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VOICE = "zh-TW-HsiaoChenNeural"
RATE = "+8%"
KV_NAMESPACE = "9f3b5e510de04803bd0b59d451911d58"
MEDIA_BASE = "https://media.marketdaily.ai"


def die(msg):
    sys.exit(f"✗ AUDIO FAIL: {msg}")


async def synth(text, raw_mp3):
    import edge_tts
    tts = edge_tts.Communicate(text, VOICE, rate=RATE)
    await tts.save(str(raw_mp3))


def normalize(raw, final):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(raw), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:a", "libmp3lame", "-b:a", "96k", "-ar", "44100", str(final)],
        check=True, capture_output=True)


def verify(final):
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "json", str(final)], capture_output=True, text=True).stdout)
    dur = float(probe["format"]["duration"])
    if not 100 <= dur <= 260:
        die(f"時長 {dur:.0f}s 不在 100-260s")
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(final), "-af",
         "astats=metadata=1", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"RMS level dB:\s*(-?[\d.]+)", r.stderr)
    if not m or float(m[-1]) < -40:
        die(f"疑似靜音(RMS={m[-1] if m else '?'})")
    print(f"✓ 音檔驗證過 {dur:.0f}s RMS={m[-1]}dB")
    return dur


def upload(final, key):
    subprocess.run(
        ["npx", "wrangler", "kv", "key", "put", key, "--path", str(final),
         "--namespace-id", KV_NAMESPACE, "--remote"],
        check=True, capture_output=True, cwd=HERE.parent)
    url = f"{MEDIA_BASE}/{key}"
    size = final.stat().st_size
    for _ in range(6):
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
    die(f"上傳後 {url} 驗不到")


def main():
    txts = sorted(OUT.glob("narration_*.txt"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (txts[-1] if txts else None)
    if not src:
        sys.exit("找不到旁白稿,先跑 build_script.py")
    m = re.match(r"narration_(\d{4}-\d{2}-\d{2})_(\w+)\.txt", src.name)
    date_str, ed = m.group(1), m.group(2)
    text = src.read_text(encoding="utf-8")
    raw = OUT / f"_raw_{date_str}_{ed}.mp3"
    final = OUT / f"audio_{date_str}_{ed}.mp3"
    asyncio.run(synth(text, raw))
    normalize(raw, final)
    dur = verify(final)
    key = f"audio_{date_str}_{ed}.mp3"
    url = upload(final, key)
    meta = {"date": date_str, "edition": ed, "url": url,
            "duration_sec": round(dur), "chars": len(text)}
    (OUT / f"audio_{date_str}_{ed}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
