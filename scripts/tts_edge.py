"""Edge-TTS 文字轉語音(免費無限量,微軟 Neural 聲音)。

取代 Gemini TTS(免費層 10 RPD / 3 RPM 已不堪用)。
用法:
  python3 scripts/tts_edge.py "要念的文字" out.mp3
  python3 scripts/tts_edge.py --voice zh-TW-YunJheNeural --rate +10% "文字" out.mp3
  python3 scripts/tts_edge.py --file input.txt out.mp3
  python3 scripts/tts_edge.py --list          # 列出 zh-TW / en 聲音
需 pip install edge-tts(requirements.txt 未收錄;非日報 pipeline 依賴)。
"""
import argparse
import asyncio
import sys
from pathlib import Path

DEFAULT_VOICE = "zh-TW-HsiaoChenNeural"


async def list_voices():
    import edge_tts
    for v in await edge_tts.list_voices():
        if v["Locale"].startswith(("zh-TW", "en-US", "en-AU")):
            print(f'{v["ShortName"]:36s} {v["Gender"]:6s} {v["Locale"]}')


async def synth(text, out, voice, rate, volume):
    import edge_tts
    kw = {}
    if rate:
        kw["rate"] = rate
    if volume:
        kw["volume"] = volume
    await edge_tts.Communicate(text, voice, **kw).save(out)
    print(f"[tts] {voice} → {out} ({Path(out).stat().st_size:,} bytes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("out", nargs="?", default="tts_out.mp3")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=None, help="+10%% / -20%%")
    ap.add_argument("--volume", default=None)
    ap.add_argument("--file", help="從檔案讀文字")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        asyncio.run(list_voices())
        return 0
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not text:
        ap.error("需要文字(位置參數或 --file)")
    asyncio.run(synth(text, args.out, args.voice, args.rate, args.volume))
    return 0


if __name__ == "__main__":
    sys.exit(main())
