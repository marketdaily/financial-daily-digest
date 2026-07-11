#!/usr/bin/env python3
"""brief.json + template.html → 直式短影音 mp4。

Playwright 錄 CSS 動畫 → ffmpeg 轉 h264 + 程序生成配樂(無版權問題)。
用法: python3 render.py [out/brief_YYYY-MM-DD_tw.json]
"""
import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DURATION = 36.5


def make_music(path, duration=DURATION, sr=44100):
    """極簡 ambient bed:Am–F–C–G 和弦 pad + 底鼓脈衝,音量壓低當底。"""
    import numpy as np
    n = int(duration * sr)
    t = np.arange(n) / sr
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63),
              (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
    bar = duration / len(chords)
    audio = np.zeros(n)
    for i, chord in enumerate(chords):
        seg = (t >= i * bar) & (t < (i + 1) * bar)
        ts = t[seg] - i * bar
        env = np.minimum(ts / 1.8, 1.0) * np.minimum((bar - ts) / 1.8, 1.0)
        env = np.clip(env, 0, 1)
        for f in chord:
            audio[seg] += 0.12 * env * np.sin(2 * np.pi * f * ts) \
                        + 0.05 * env * np.sin(2 * np.pi * f * 0.5 * ts)
    pulse_period = 2.0
    ph = (t % pulse_period)
    audio += 0.10 * np.exp(-ph * 9) * np.sin(2 * np.pi * 55 * ph)
    fade = np.minimum(t / 2.0, 1.0) * np.minimum((duration - t) / 2.5, 1.0)
    audio *= np.clip(fade, 0, 1)
    audio = np.tanh(audio * 1.2) * 0.5
    pcm = (audio * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def record(brief_path):
    from playwright.sync_api import sync_playwright
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    inject = f'<body>\n<script>window.BRIEF = {json.dumps(brief, ensure_ascii=False)};</script>'
    page_html = tpl.replace("<body>", inject, 1)
    tmp = OUT / f"_render_{brief['date']}_{brief['edition']}.html"
    tmp.write_text(page_html, encoding="utf-8")

    vid_dir = OUT / "_rec"
    vid_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--force-device-scale-factor=1",
            "--disable-gpu", "--disable-dev-shm-usage",  # WSL/headless 環境 GPU process 起不來
        ])
        ctx = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            record_video_dir=str(vid_dir),
            record_video_size={"width": 1080, "height": 1920},
        )
        page = ctx.new_page()
        page.goto(tmp.as_uri())
        page.wait_for_function("window.__VIDEO_DONE === true", timeout=90000)
        video = page.video
        ctx.close()
        webm = video.path()
        browser.close()
    return brief, Path(webm)


def encode(brief, webm):
    music = OUT / "_music.wav"
    make_music(music)
    final = OUT / f"brief_{brief['date']}_{brief['edition']}.mp4"
    subprocess.run([
        # -ss 0.4:Playwright 錄影開頭含導航完成前的空白(白底)幀,裁掉才不會
        # 變成 IG 0s 預設封面(make_post 非白幀閘會擋;時序有變異,必須確定性裁除)
        "ffmpeg", "-y", "-ss", "0.4", "-i", str(webm), "-i", str(music),
        "-t", str(DURATION),
        "-vf", "fps=30,scale=1080:1920:flags=lanczos",
        "-c:v", "libx264", "-preset", "slow", "-crf", "21",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(final),
    ], check=True, capture_output=True)
    return final


def main():
    briefs = sorted(OUT.glob("brief_*.json"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (briefs[-1] if briefs else None)
    if not src or not src.exists():
        sys.exit("找不到 brief json,先跑 extract.py")
    brief, webm = record(src)
    final = encode(brief, webm)
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration,size:stream=width,height,codec_name",
         "-of", "json", str(final)], capture_output=True, text=True)
    info = json.loads(probe.stdout)
    print(f"✓ {final.name}")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
