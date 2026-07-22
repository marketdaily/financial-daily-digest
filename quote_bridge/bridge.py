"""永豐 Shioaji 行情橋 — winrig 本機 daemon,經 named tunnel 供 Delvin 個人 dashboard 即時報價。

鐵則:唯讀行情+帳務查詢,全程無 place_order;金鑰只在本機 .env,永不進 Cloudflare。
行情授權限本人使用,回應只給帶 token 的請求(token 由 worker /watch-token 經 admin 驗證後下發)。
"""
import hmac
import json
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8788
SNAP_TTL = 3.0
TW_SYM = re.compile(r"^\d{4,6}[A-Z]?$")


def load_env(path):
    d = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    except FileNotFoundError:
        pass
    return d


ENV = load_env(os.path.expanduser("~/Delvin-agent/.env"))
TOKEN = ENV.get("QUOTE_BRIDGE_TOKEN", "")
ALLOWED_ORIGINS = {"https://marketdaily.ai", "https://www.marketdaily.ai"}


class Feed:
    def __init__(self):
        self._api = None
        self._lock = threading.Lock()
        self._login_ts = 0.0
        self._cache = {}

    def _login_locked(self):
        import shioaji as sj

        api = sj.Shioaji(simulation=False)
        api.login(
            api_key=ENV["SINOPAC_API_KEY"],
            secret_key=ENV["SINOPAC_SECRET_KEY"],
            fetch_contract=True,
            contracts_timeout=60000,
        )
        self._api = api
        self._login_ts = time.time()
        print(f"[bridge] login ok ts={int(self._login_ts)}", flush=True)

    def api(self):
        with self._lock:
            if self._api is None or time.time() - self._login_ts > 20 * 3600:
                if self._api is not None:
                    try:
                        self._api.logout()
                    except Exception:
                        pass
                    self._api = None
                self._login_locked()
            return self._api

    def reset(self):
        with self._lock:
            if self._api is not None:
                try:
                    self._api.logout()
                except Exception:
                    pass
            self._api = None

    def logged_in(self):
        return self._api is not None

    def quotes(self, syms):
        now = time.time()
        out, stale = [], []
        for s in syms:
            c = self._cache.get(s)
            if c and now - c[0] < SNAP_TTL:
                out.append(c[1])
            else:
                stale.append(s)
        if stale:
            api = self.api()
            contracts = []
            for s in stale:
                c = api.Contracts.Stocks[s]
                if c is not None:
                    contracts.append(c)
            snaps = api.snapshots(contracts) if contracts else []
            for sn in snaps:
                q = {
                    "symbol": sn.code,
                    "price": sn.close,
                    "change": round(sn.change_rate, 2),
                    "bid": sn.buy_price,
                    "ask": sn.sell_price,
                    "open": sn.open,
                    "high": sn.high,
                    "low": sn.low,
                    "volume": sn.total_volume,
                    "amount": sn.amount,
                    "ts": sn.ts // 1_000_000_000 if sn.ts else None,
                }
                self._cache[sn.code] = (now, q)
                out.append(q)
        return out

    def positions(self):
        api = self.api()
        try:
            pos = api.list_positions(api.stock_account)
        except Exception as ex:
            if "406" in str(ex) or "Not Acceptable" in str(ex):
                return {"status": "not_signed", "positions": []}
            raise
        rows = []
        for p in pos:
            rows.append(
                {
                    "code": p.code,
                    "quantity": p.quantity,
                    "avg_price": p.price,
                    "last_price": p.last_price,
                    "pnl": p.pnl,
                    "direction": str(getattr(p, "direction", "")),
                }
            )
        return {"status": "ok", "positions": rows}


FEED = Feed()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, obj):
        origin = self.headers.get("Origin", "")
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            if u.path == "/health":
                return self._send(200, {"ok": True, "logged_in": FEED.logged_in(), "ts": int(time.time())})
            t = (qs.get("t") or [""])[0]
            if not TOKEN or not hmac.compare_digest(t, TOKEN):
                return self._send(403, {"error": "forbidden"})
            if u.path == "/q":
                raw = (qs.get("syms") or [""])[0]
                syms = [s.strip().upper() for s in raw.split(",") if s.strip()][:60]
                syms = [s for s in syms if TW_SYM.match(s)]
                return self._send(200, {"quotes": FEED.quotes(syms), "src": "shioaji", "ts": int(time.time())})
            if u.path == "/positions":
                return self._send(200, FEED.positions())
            return self._send(404, {"error": "not_found"})
        except Exception as ex:
            traceback.print_exc()
            FEED.reset()
            try:
                return self._send(502, {"error": str(ex)[:200]})
            except Exception:
                pass


def prewarm():
    try:
        FEED.api()
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("QUOTE_BRIDGE_TOKEN missing in ~/Delvin-agent/.env")
    threading.Thread(target=prewarm, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[bridge] listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
