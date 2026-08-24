"""Probe free, keyless image sources: NASA image library + Pollinations.ai."""
import urllib.parse
from pathlib import Path
import requests

ROOT = Path(__file__).parent


def probe_nasa():
    r = requests.get("https://images-api.nasa.gov/search",
                     params={"q": "sun corona", "media_type": "image"}, timeout=60)
    if r.status_code != 200:
        print(f"  NASA search -> {r.status_code}")
        return
    items = r.json()["collection"]["items"]
    print(f"  NASA search OK -> {len(items)} results")
    item = items[0]
    asset = requests.get(item["href"], timeout=60).json()
    orig = [u for u in asset if u.lower().endswith((".jpg", ".jpeg"))]
    orig = [u for u in orig if "~orig" in u or "~large" in u] or orig
    if orig:
        img = requests.get(orig[0], timeout=120)
        (ROOT / "_probe_nasa.jpg").write_bytes(img.content)
        print(f"  NASA IMAGE OK -> _probe_nasa.jpg "
              f"({len(img.content) // 1024} KB)  title={item['data'][0]['title'][:50]}")
    else:
        print("  NASA: no jpg asset")


def probe_pollinations():
    prompt = ("cinematic photorealistic still of Earth frozen in darkness, "
              "no sunlight, ice-covered continents, deep space documentary")
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(prompt)
           + "?width=1920&height=1080&nologo=true&seed=7&model=flux")
    r = requests.get(url, timeout=180)
    if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
        (ROOT / "_probe_poll.jpg").write_bytes(r.content)
        print(f"  POLLINATIONS OK -> _probe_poll.jpg ({len(r.content) // 1024} KB)")
    else:
        print(f"  POLLINATIONS -> {r.status_code}, "
              f"{len(r.content)} bytes, head={r.content[:60]}")


if __name__ == "__main__":
    print("probing NASA image library ...")
    try:
        probe_nasa()
    except Exception as e:
        print(f"  NASA FAILED: {e}")
    print("probing Pollinations.ai ...")
    try:
        probe_pollinations()
    except Exception as e:
        print(f"  POLLINATIONS FAILED: {e}")
