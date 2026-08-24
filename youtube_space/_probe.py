"""One-shot probe: confirm Gemini image gen + Groq English TTS work with .env keys."""
import base64, sys
from pathlib import Path
import requests

ROOT = Path(__file__).parent
ENV = {}
for ln in (ROOT.parent / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.strip().split("=", 1)
        ENV[k] = v


def probe_image():
    key = ENV["GEMINI_API_KEY"]
    prompt = ("A photorealistic cinematic still of the Sun seen from deep space, "
              "dramatic lens flare, 16:9 widescreen, NASA Hubble aesthetic")
    for modalities in (None, ["IMAGE"], ["TEXT", "IMAGE"]):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash-image:generateContent?key={key}")
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if modalities:
            body["generationConfig"] = {"responseModalities": modalities}
        r = requests.post(url, json=body, timeout=180)
        tag = modalities or "default"
        if r.status_code != 200:
            print(f"  image [{tag}] -> {r.status_code}: {r.text[:200]}")
            continue
        for part in r.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                (ROOT / "_probe.jpg").write_bytes(
                    base64.b64decode(part["inlineData"]["data"]))
                print(f"  IMAGE OK [{tag}] -> _probe.jpg "
                      f"({(ROOT / '_probe.jpg').stat().st_size // 1024} KB)")
                return
        print(f"  image [{tag}] -> 200 but no inlineData")
    print("  IMAGE FAILED")


def probe_tts():
    key = ENV["GROQ_API_KEY"]
    line = "Right now, the Sun is ninety three million miles away."
    for model, voice in (("canopylabs/orpheus-v1-english", "autumn"),
                         ("playai-tts", "Fritz-PlayAI"),
                         ("playai-tts", "Atlas-PlayAI")):
        r = requests.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "voice": voice, "input": line,
                  "response_format": "wav"}, timeout=120)
        if r.status_code == 200:
            (ROOT / "_probe.wav").write_bytes(r.content)
            print(f"  TTS OK [{model} / {voice}] -> _probe.wav "
                  f"({len(r.content) // 1024} KB)")
            return
        print(f"  tts [{model} / {voice}] -> {r.status_code}: {r.text[:160]}")
    print("  TTS FAILED")


if __name__ == "__main__":
    print("probing Gemini image generation ...")
    probe_image()
    print("probing Groq English TTS ...")
    probe_tts()
