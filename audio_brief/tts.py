#!/usr/bin/env python3
"""旁白稿 → mp3(主路徑 F5-TTS 陳華克隆聲,退場 edge-tts zh-TW)→ 確定性驗證 → KV 上傳。

F5 = winrig 常駐 jarvis-f5 服務(localhost:5124),逐句合成(短句乾淨)+句間留白再串接;
數字/百分比/年份先轉中文唸法。F5 任一環節失敗(連不上/單句失敗/驗證不過)→ 整段退 edge-tts。
驗證:時長 100-260s、非靜音(RMS > -40dB)、URL 可達且大小相符。兩條路徑都不過=abort。
"""
import asyncio
import json
import os
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
F5_URL = os.environ.get("MD_F5_URL", "http://127.0.0.1:5124/tts")
F5_GAP_S = 0.15
KV_NAMESPACE = "9f3b5e510de04803bd0b59d451911d58"
MEDIA_BASE = "https://media.marketdaily.ai"


def die(msg):
    sys.exit(f"✗ AUDIO FAIL: {msg}")


async def synth(text, raw_mp3):
    import edge_tts
    tts = edge_tts.Communicate(text, VOICE, rate=RATE)
    await tts.save(str(raw_mp3))


_cn2an = None


def _num_zh(s):
    global _cn2an
    if _cn2an is None:
        try:
            import cn2an as _c
            _cn2an = _c
        except Exception:
            _cn2an = False
    if not _cn2an:
        return s
    try:
        z = _cn2an.an2cn(s)
        for a, b in (("点", "點"), ("负", "負"), ("两", "兩"), ("万", "萬"), ("亿", "億")):
            z = z.replace(a, b)
        return z
    except Exception:
        return s


_DIGIT_ZH = str.maketrans("0123456789", "零一二三四五六七八九")


_EMOJI_RE = re.compile("[☀-➿️⬀-⯿\U0001f000-\U0001faff]")


def _tts_normalize(t):
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"(\d{4})(?=\s*年)", lambda m: m.group(1).translate(_DIGIT_ZH), t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: "百分之" + _num_zh(m.group(1)), t)
    t = re.sub(r"(?<=\d)\s*[~～\-－]\s*(?=\d)", "到", t)
    t = re.sub(r"[$＄]|US\$|NT\$", "", t)
    t = re.sub(r"\d+(?:\.\d+)?", lambda m: _num_zh(m.group(0)), t)
    return t


def _split_chunks(text, limit=60):
    chunks = []
    for p in re.split(r"(?<=[。！？!?\n])", text):
        p = p.strip()
        if not p or not re.search(r"[\w一-鿿]", p):
            continue
        while len(p) > limit:
            cut = max(p.rfind(c, 20, limit) for c in "，,、;；:：")
            if cut < 20:
                cut = limit - 1
            chunks.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            chunks.append(p)
    return chunks


def synth_f5(text, raw_wav):
    import wave
    chunks = _split_chunks(text)
    if not chunks:
        raise RuntimeError("旁白稿切句後為空")
    frames, params = [], None
    for i, c in enumerate(chunks):
        tmp = OUT / f"_f5_{i:03d}.wav"
        req = urllib.request.Request(
            F5_URL, data=json.dumps({"text": _tts_normalize(c), "out": str(tmp)}).encode(),
            headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=180).read())
        if not r.get("ok") or not tmp.exists():
            raise RuntimeError(f"F5 第 {i + 1}/{len(chunks)} 句失敗: {r.get('err')}")
        with wave.open(str(tmp), "rb") as w:
            if params is None:
                params = w.getparams()
            frames.append(w.readframes(w.getnframes()))
        tmp.unlink()
        frames.append(b"\x00" * (int(F5_GAP_S * params.framerate)
                                 * params.sampwidth * params.nchannels))
    with wave.open(str(raw_wav), "wb") as w:
        w.setparams(params)
        w.writeframes(b"".join(frames))
    print(f"✓ F5 克隆聲合成 {len(chunks)} 句")


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


def _head_size(url):
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "MarketDailyBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("content-length", 0))
    except Exception:
        return -1


def upload(final, key):
    url = f"{MEDIA_BASE}/{key}"
    size = final.stat().st_size
    # wrangler kv put 會在寫入已成功時偶發回非 0(2026-07-09 兩連中),
    # 所以 rc 只當參考,成敗以 HEAD content-length 相符為準
    for attempt in range(1, 4):
        r = subprocess.run(
            ["npx", "wrangler", "kv", "key", "put", key, "--path", str(final),
             "--namespace-id", KV_NAMESPACE, "--remote"],
            capture_output=True, text=True, cwd=HERE.parent)
        if r.returncode == 0:
            break
        print(f"⚠ wrangler put rc={r.returncode} (attempt {attempt}/3): "
              f"{(r.stderr or r.stdout).strip()[-300:]}")
        if _head_size(url) == size:
            break
        time.sleep(5)
    for _ in range(6):
        time.sleep(10)
        if _head_size(url) == size:
            print(f"✓ 上線 {url} ({size} bytes)")
            return url
    die(f"上傳後 {url} 驗不到")


def main():
    txts = sorted(OUT.glob("narration_*.txt"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (txts[-1] if txts else None)
    if not src:
        sys.exit("找不到旁白稿,先跑 build_script.py")
    m = re.match(r"narration_(\d{4}-\d{2}-\d{2})_(\w+)\.txt", src.name)
    date_str, ed = m.group(1), m.group(2)
    text = src.read_text(encoding="utf-8")
    final = OUT / f"audio_{date_str}_{ed}.mp3"
    voice = "f5-clone"
    try:
        raw = OUT / f"_raw_{date_str}_{ed}.wav"
        synth_f5(text, raw)
        normalize(raw, final)
        dur = verify(final)
    except (Exception, SystemExit) as e:
        print(f"✗ F5 克隆聲路徑失敗,退 edge-tts: {e}")
        voice = "edge"
        raw = OUT / f"_raw_{date_str}_{ed}.mp3"
        asyncio.run(synth(text, raw))
        normalize(raw, final)
        dur = verify(final)
    key = f"audio_{date_str}_{ed}.mp3"
    url = upload(final, key)
    meta = {"date": date_str, "edition": ed, "url": url,
            "duration_sec": round(dur), "chars": len(text), "voice": voice}
    (OUT / f"audio_{date_str}_{ed}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
