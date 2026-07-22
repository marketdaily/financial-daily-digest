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
        self._contracts = {}

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
        self._bidask_cb_installed = False
        self._subs, self._depth = {}, {}
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
            self._contracts = {}

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
                c = self._resolve(api, s)
                if c is not None:
                    contracts.append(c)
            snaps = api.snapshots(contracts) if contracts else []
            for sn in snaps:
                c = self._contracts.get(sn.code)
                q = {
                    "symbol": sn.code,
                    "name": (getattr(c, "name", "") or "").strip() or None,
                    "price": sn.close,
                    "change": round(sn.change_rate, 2),
                    "bid": sn.buy_price,
                    "ask": sn.sell_price,
                    "open": sn.open,
                    "high": sn.high,
                    "low": sn.low,
                    "volume": sn.total_volume,
                    "amount": sn.amount,
                    # Shioaji snapshot.ts 是「台北牆鐘時間偽裝成 epoch ns」(1.5.6 實測,
                    # 正式/模擬環境皆然)——減 8h 才是真 epoch,別直接當 UTC 用
                    "ts": sn.ts // 1_000_000_000 - 8 * 3600 if sn.ts else None,
                }
                self._cache[sn.code] = (now, q)
                out.append(q)
        return out

    def _resolve(self, api, s):
        """code → 合約。CB(可轉債)等不在 Contracts.Stocks 頂層索引,要逐交易所
        (TSE/OTC/OES)找。只快取命中:暫時性失敗不可釘死成「查無」。"""
        c = self._contracts.get(s)
        if c is not None:
            return c
        stocks = api.Contracts.Stocks
        try:
            c = stocks[s]
        except Exception:
            c = None
        if c is None:
            for ex in ("TSE", "OTC", "OES"):
                try:
                    sub = getattr(stocks, ex, None)
                    c = sub[s] if sub is not None else None
                except Exception:
                    c = None
                if c is not None:
                    break
        if c is not None:
            self._contracts[s] = c
        return c

    DEPTH_IDLE_S = 300

    def depth(self, sym):
        """五檔:on-demand 訂閱 BidAsk 串流,idle 5 分鐘自動退訂(訂閱上限 200 檔)。"""
        import shioaji as sj
        api = self.api()
        if not getattr(self, "_bidask_cb_installed", False):
            api.quote.set_on_bidask_stk_v1_callback(self._on_bidask)
            self._bidask_cb_installed = True
        now = time.time()
        if not hasattr(self, "_depth"):
            self._depth, self._subs = {}, {}
        if sym not in self._subs:
            contract = self._resolve(api, sym)
            if contract is None:
                return None
            api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.BidAsk,
                                version=sj.constant.QuoteVersion.v1)
        self._subs[sym] = now
        for s, t0 in list(self._subs.items()):
            if s != sym and now - t0 > self.DEPTH_IDLE_S:
                try:
                    c = self._contracts.get(s)
                    if c is not None:
                        api.quote.unsubscribe(c, quote_type=sj.constant.QuoteType.BidAsk,
                                              version=sj.constant.QuoteVersion.v1)
                except Exception:
                    pass
                self._subs.pop(s, None)
                self._depth.pop(s, None)
        return self._depth.get(sym)

    def _on_bidask(self, exchange, ba):
        try:
            self._depth[ba.code] = {
                "ts": int(time.time()),
                "bid": [[float(p), int(v)] for p, v in zip(ba.bid_price, ba.bid_volume)],
                "ask": [[float(p), int(v)] for p, v in zip(ba.ask_price, ba.ask_volume)],
            }
        except Exception:
            pass

    def kbars(self, sym, res=5, days=5):
        """近 N 日分 K(1 分 K 聚合成 res 分鐘)。ts 牆鐘偽 epoch→分桶用牆鐘、輸出真 epoch(-8h)。"""
        key = f"kb:{sym}:{res}:{days}"
        c = self._cache.get(key)
        now = time.time()
        if c and now - c[0] < 60:
            return c[1]
        import datetime as dt
        api = self.api()
        contract = self._resolve(api, sym)
        if contract is None:
            return []
        end = dt.date.today()
        kb = api.kbars(contract, start=(end - dt.timedelta(days=days + 4)).isoformat(), end=end.isoformat())
        bars, bucket = [], None
        for i in range(len(kb.ts)):
            wall = kb.ts[i] // 1_000_000_000
            b0 = wall - (wall % (res * 60))
            if bucket is None or bucket["t0"] != b0:
                if bucket:
                    bars.append(bucket)
                bucket = {"t0": b0, "t": b0 - 8 * 3600, "o": kb.Open[i], "h": kb.High[i],
                          "l": kb.Low[i], "c": kb.Close[i], "v": kb.Volume[i]}
            else:
                bucket["h"] = max(bucket["h"], kb.High[i])
                bucket["l"] = min(bucket["l"], kb.Low[i])
                bucket["c"] = kb.Close[i]
                bucket["v"] += kb.Volume[i]
        if bucket:
            bars.append(bucket)
        for b in bars:
            b.pop("t0", None)
        out = bars[-400:]
        self._cache[key] = (now, out)
        return out

    RANK_TYPES = {"change": "ChangePercentRank", "volume": "VolumeRank", "amount": "AmountRank",
                  "range": "DayRangeRank", "tick": "TickCountRank"}

    def ranks(self, rtype):
        key = f"rank:{rtype}"
        c = self._cache.get(key)
        now = time.time()
        if c and now - c[0] < 30:
            return c[1]
        import shioaji as sj
        api = self.api()
        st = getattr(sj.constant.ScannerType, self.RANK_TYPES[rtype])
        rows = []
        for d in api.scanners(scanner_type=st, count=50):
            prev = d.close - d.change_price
            rows.append({
                "code": d.code,
                "name": (d.name or "").strip(),
                "close": d.close,
                "change_pct": round(d.change_price / prev * 100, 2) if prev else None,
                "change_price": d.change_price,
                "volume": d.total_volume,
            })
        self._cache[key] = (now, rows)
        return rows

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
            if u.path == "/depth":
                sym = (qs.get("sym") or [""])[0].strip().upper()
                if not TW_SYM.match(sym):
                    return self._send(400, {"error": "bad_sym"})
                d = FEED.depth(sym)
                return self._send(200, {"depth": d, "sym": sym, "status": "ok" if d else "pending"})
            if u.path == "/kbars":
                sym = (qs.get("sym") or [""])[0].strip().upper()
                res = int((qs.get("res") or ["5"])[0])
                days = min(int((qs.get("days") or ["5"])[0]), 10)
                if not TW_SYM.match(sym) or res not in (1, 5, 15, 30, 60):
                    return self._send(400, {"error": "bad_params"})
                return self._send(200, {"bars": FEED.kbars(sym, res, days), "sym": sym, "res": res, "ts": int(time.time())})
            if u.path == "/ranks":
                rtype = (qs.get("type") or ["change"])[0]
                if rtype not in Feed.RANK_TYPES:
                    return self._send(400, {"error": "bad_type"})
                return self._send(200, {"ranks": FEED.ranks(rtype), "type": rtype, "ts": int(time.time())})
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
