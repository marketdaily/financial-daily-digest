#!/usr/bin/env python3
"""prompt -> mp4 via local ComfyUI (Wan 2.2 5B). usage: run_wan.py "prompt" [--w 1280 --h 704 --len 121 --steps 20 --seed N --prefix name --host IP:PORT]"""
import argparse, json, time, urllib.request, pathlib, sys, random
p = argparse.ArgumentParser()
p.add_argument("prompt"); p.add_argument("--w", type=int, default=1280); p.add_argument("--h", type=int, default=704)
p.add_argument("--len", type=int, default=121); p.add_argument("--steps", type=int, default=20)
p.add_argument("--seed", type=int, default=None); p.add_argument("--prefix", default="wan22")
p.add_argument("--host", default=None)
a = p.parse_args()
host = a.host or open(pathlib.Path(__file__).parent / "host.txt").read().strip()
tpl = (pathlib.Path(__file__).parent / "wan22_5b_t2v.json").read_text()
seed = a.seed if a.seed is not None else random.randint(0, 2**31)
wf = tpl.replace("__POS__", json.dumps(a.prompt)[1:-1]).replace("__W__", str(a.w)).replace("__H__", str(a.h)) \
        .replace("__LEN__", str(a.len)).replace("__STEPS__", str(a.steps)).replace("__SEED__", str(seed)).replace("__PREFIX__", a.prefix)
req = urllib.request.Request(f"http://{host}/prompt", data=json.dumps({"prompt": json.loads(wf)}).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=30))
pid = r["prompt_id"]; t0 = time.time()
print("queued", pid, "seed", seed, flush=True)
while True:
    time.sleep(5)
    h = json.load(urllib.request.urlopen(f"http://{host}/history/{pid}", timeout=30))
    if pid in h:
        st = h[pid]["status"]; el = time.time() - t0
        if st.get("status_str") == "error":
            print("ERROR", json.dumps(st)[:2000]); sys.exit(1)
        outs = h[pid]["outputs"]
        for nid, o in outs.items():
            for k in ("images", "gifs", "video", "videos"):
                for f in o.get(k, []): print("OUT", f.get("subfolder",""), f["filename"], f"{el:.0f}s")
        print(f"done {el:.0f}s"); break
    if time.time() - t0 > 3600: print("timeout"); sys.exit(2)
