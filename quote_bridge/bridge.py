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
DERIV_PROD = re.compile(r"^[A-Z0-9]{2,6}$")


class UpstreamDataError(Exception):
    """上游資料拿不到(如定 ATM 所需的 spot)→ 502 誠實回報,不觸發整段 session reset。"""


def norm_snap_ts(ts_ns):
    """snapshot.ts=台北牆鐘偽 epoch ns → 真 epoch 秒(同 /q,-8h)。kbars 是牆鐘分桶另一套語義,勿互抄。"""
    return ts_ns // 1_000_000_000 - 8 * 3600 if ts_ns else None


def snap_row(sn):
    return {
        "code": sn.code,
        "price": sn.close,
        "bid": sn.buy_price,
        "ask": sn.sell_price,
        "volume": sn.total_volume,
        "ts": norm_snap_ts(sn.ts),
    }


def pick_near_next(contracts):
    """期貨群 → (近月, 次月)。排除 R1/R2 連續合約(delivery_date 與真實月份重複),依 delivery_date 排序。"""
    real = [c for c in contracts
            if getattr(c, "delivery_date", "") and not c.code.endswith(("R1", "R2"))]
    real.sort(key=lambda c: c.delivery_date)
    return (real[0] if real else None, real[1] if len(real) > 1 else None)


def pick_atm_window(strikes, spot, n):
    """履約價集合+spot → (atm, ATM±n 檔由小到大窗口)。tie 取低履約價;無 spot → (None, [])。"""
    ss = sorted(set(strikes))
    if not ss or not spot:
        return None, []
    atm = min(ss, key=lambda k: (abs(k - spot), k))
    i = ss.index(atm)
    return atm, ss[max(0, i - n): i + n + 1]


def parse_n(raw, default=8, cap=20):
    """optchain n:未給→default;非負整數字串,超上限截到 cap(回應帶生效值);非法→None(400)。"""
    if raw is None or raw == "":
        return default
    if not raw.isdecimal():
        return None
    return min(int(raw), cap)


def norm_cp(right):
    v = getattr(right, "value", right)
    s = str(v).upper()
    if s in ("C", "CALL") or s.endswith(".CALL"):
        return "C"
    if s in ("P", "PUT") or s.endswith(".PUT"):
        return "P"
    return None


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
        self._deriv_lock = threading.Lock()
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
        self._tick_cb_installed = False
        self._ticks, self._tick_subs = {}, {}
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
                    # 前台「漲跌」欄=點數,「幅度」欄=百分比(券商慣例);點數用券商原生 change_price,不由 change 反推
                    "change_val": sn.change_price,
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

    TICKS_IDLE_S = 300
    BIG_LOT = 50

    def ticks(self, sym):
        """內外盤+大單:on-demand 訂閱 Tick 串流,idle 5 分鐘自動退訂(與五檔共用 200 檔訂閱上限)。"""
        import shioaji as sj
        import collections
        api = self.api()
        if not getattr(self, "_tick_cb_installed", False):
            api.quote.set_on_tick_stk_v1_callback(self._on_tick)
            self._tick_cb_installed = True
        now = time.time()
        if not hasattr(self, "_ticks"):
            self._ticks, self._tick_subs = {}, {}
        if sym not in self._tick_subs:
            contract = self._resolve(api, sym)
            if contract is None:
                return None
            self._ticks.setdefault(sym, {"ticks": collections.deque(maxlen=60),
                                         "out": 0, "in": 0, "big_buy": 0, "big_sell": 0})
            api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick,
                                version=sj.constant.QuoteVersion.v1)
        self._tick_subs[sym] = now
        for s, t0 in list(self._tick_subs.items()):
            if s != sym and now - t0 > self.TICKS_IDLE_S:
                try:
                    c = self._contracts.get(s)
                    if c is not None:
                        api.quote.unsubscribe(c, quote_type=sj.constant.QuoteType.Tick,
                                              version=sj.constant.QuoteVersion.v1)
                except Exception:
                    pass
                self._tick_subs.pop(s, None)
                self._ticks.pop(s, None)
        return self._ticks.get(sym)

    def _on_tick(self, exchange, tk):
        try:
            st = self._ticks.get(tk.code)
            if st is None:
                return
            v = int(tk.volume)
            io_t = int(getattr(tk, "tick_type", 0))  # 1=外盤 2=內盤 0=無法歸類
            st["ticks"].append({"ts": int(time.time()), "c": float(tk.close), "v": v, "io": io_t})
            if io_t == 1:
                st["out"] += v
            elif io_t == 2:
                st["in"] += v
            if v >= self.BIG_LOT:
                if io_t == 1:
                    st["big_buy"] += v
                elif io_t == 2:
                    st["big_sell"] += v
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
    # 衍生榜(2026-07-22 Delvin「三竹有的我們都要有」):漲停/即將漲停/跌停/即將跌停。
    # Shioaji 無對應 ScannerType → 從漲跌幅雙向掃描(各200檔)以 % 門檻推導;
    # 9.9% 當漲停近似(處置股/新上市無漲跌幅限制者會有例外,屬已知近似)。
    DERIVED_RANKS = {
        "limit_up": lambda p: p >= 9.9,
        "near_up": lambda p: 9.0 <= p < 9.9,
        "limit_down": lambda p: p <= -9.9,
        "near_dn": lambda p: -9.9 < p <= -9.0,
    }

    def _scan_rows(self, st, **kw):
        import shioaji as sj  # noqa: F401
        api = self.api()
        rows = []
        for d in api.scanners(scanner_type=st, **kw):
            prev = d.close - d.change_price
            rows.append({
                "code": d.code,
                "name": (d.name or "").strip(),
                "close": d.close,
                "change_pct": round(d.change_price / prev * 100, 2) if prev else None,
                "change_price": d.change_price,
                "volume": d.total_volume,
            })
        return rows

    def _pct_scan_both(self):
        """漲跌幅雙向各掃 200 檔取聯集(scanners ascending 語義不賭方向,兩邊都拿)。"""
        key = "scan:pct_both"
        c = self._cache.get(key)
        now = time.time()
        if c and now - c[0] < 30:
            return c[1]
        import shioaji as sj
        st = sj.constant.ScannerType.ChangePercentRank
        seen, rows = set(), []
        for asc in (False, True):
            try:
                part = self._scan_rows(st, ascending=asc, count=200)
            except TypeError:
                part = self._scan_rows(st, count=200)
            for r in part:
                if r["code"] not in seen:
                    seen.add(r["code"])
                    rows.append(r)
        self._cache[key] = (now, rows)
        return rows

    def ranks(self, rtype):
        key = f"rank:{rtype}"
        c = self._cache.get(key)
        now = time.time()
        if c and now - c[0] < 30:
            return c[1]
        if rtype in self.DERIVED_RANKS:
            pred = self.DERIVED_RANKS[rtype]
            rows = [r for r in self._pct_scan_both()
                    if r["change_pct"] is not None and pred(r["change_pct"])]
            rows.sort(key=lambda r: (-abs(r["change_pct"]), -(r["volume"] or 0)))
            rows = rows[:50]
        else:
            import shioaji as sj
            st = getattr(sj.constant.ScannerType, self.RANK_TYPES[rtype])
            rows = self._scan_rows(st, count=50)
        self._cache[key] = (now, rows)
        return rows

    # 指數類商品 underlying_code 是空字串(1.5.6 實測),spot 走白名單映射;
    # 個股期/個股選 uk='S' 帶現股代碼,走 _resolve。對不上→None,誠實回 null 不硬湊。
    IDX_SPOT = {"TXF": ("TSE", "001"), "MXF": ("TSE", "001"), "TMF": ("TSE", "001"),
                "TXO": ("TSE", "001"), "TX1": ("TSE", "001"), "TX2": ("TSE", "001"),
                "TX4": ("TSE", "001"), "TX5": ("TSE", "001")}
    FUT_TTL = 10.0
    OPT_TTL = 60.0

    def _group(self, category, prod):
        """ContractCategory 群只能屬性存取(dict 式索引是逐合約 code);未知商品→None。"""
        grp = getattr(category, prod, None)
        if grp is None or callable(grp):
            return None
        try:
            return list(grp)
        except TypeError:
            return None

    def _spot_contract(self, api, prod, sample):
        m = self.IDX_SPOT.get(prod)
        if m:
            try:
                return getattr(api.Contracts.Indexs, m[0])[m[1]]
            except Exception:
                return None
        uc = getattr(sample, "underlying_code", "") or ""
        if TW_SYM.match(uc):
            return self._resolve(api, uc)
        return None

    def fut(self, prod):
        """近月+次月+現貨 snapshot;未知商品→None(404)。快取 10s。"""
        key = f"fut:{prod}"
        c = self._cache.get(key)
        if c and time.time() - c[0] < self.FUT_TTL:
            return c[1]
        with self._deriv_lock:
            c = self._cache.get(key)
            if c and time.time() - c[0] < self.FUT_TTL:
                return c[1]
            api = self.api()
            contracts = self._group(api.Contracts.Futures, prod)
            if not contracts:
                return None
            near, nxt = pick_near_next(contracts)
            if near is None:
                return None
            want = [near] + ([nxt] if nxt is not None else [])
            spot_c = self._spot_contract(api, prod, near)
            if spot_c is not None:
                want.append(spot_c)
            snaps = {sn.code: sn for sn in api.snapshots(want)}

            def row(contract):
                sn = snaps.get(contract.code)
                if sn is None:
                    return None
                r = snap_row(sn)
                r["delivery_date"] = contract.delivery_date
                return r

            near_row = row(near)
            if near_row is None:
                raise UpstreamDataError("no snapshot for near contract")
            spot_sn = snaps.get(spot_c.code) if spot_c is not None else None
            out = {
                "near": near_row,
                "next": row(nxt) if nxt is not None else None,
                "spot": snap_row(spot_sn) if spot_sn is not None else None,
            }
            self._cache[key] = (time.time(), out)
            return out

    def optchain(self, prod, n):
        """最近到期月 ATM±n 檔 call+put(單次批次 snapshots);未知商品→None(404)。快取 60s。"""
        key = f"opt:{prod}:{n}"
        c = self._cache.get(key)
        if c and time.time() - c[0] < self.OPT_TTL:
            return c[1]
        with self._deriv_lock:
            c = self._cache.get(key)
            if c and time.time() - c[0] < self.OPT_TTL:
                return c[1]
            api = self.api()
            contracts = self._group(api.Contracts.Options, prod)
            if not contracts:
                return None
            dds = sorted({x.delivery_date for x in contracts if getattr(x, "delivery_date", "")})
            if not dds:
                return None
            expiry = dds[0]
            chain = [x for x in contracts if x.delivery_date == expiry]
            spot_c = self._spot_contract(api, prod, chain[0])
            spot = None
            if spot_c is not None:
                ssn = api.snapshots([spot_c])
                if ssn:
                    spot = ssn[0].close
            atm, window = pick_atm_window({x.strike_price for x in chain}, spot, n)
            if atm is None:
                raise UpstreamDataError("spot unavailable, cannot locate ATM")
            wset = set(window)
            sel = [x for x in chain if x.strike_price in wset]
            snaps = {sn.code: sn for sn in api.snapshots(sel)}
            rows = []
            for x in sorted(sel, key=lambda x: (x.strike_price, norm_cp(x.option_right) or "")):
                sn = snaps.get(x.code)
                if sn is None:
                    continue
                r = snap_row(sn)
                r["cp"] = norm_cp(x.option_right)
                r["strike"] = x.strike_price
                rows.append(r)
            out = {"expiry": expiry, "spot": spot, "atm": atm, "n": n, "chain": rows}
            self._cache[key] = (time.time(), out)
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
            if u.path == "/depth":
                sym = (qs.get("sym") or [""])[0].strip().upper()
                if not TW_SYM.match(sym):
                    return self._send(400, {"error": "bad_sym"})
                d = FEED.depth(sym)
                return self._send(200, {"depth": d, "sym": sym, "status": "ok" if d else "pending"})
            if u.path == "/ticks":
                sym = (qs.get("sym") or [""])[0].strip().upper()
                if not TW_SYM.match(sym):
                    return self._send(400, {"error": "bad_sym"})
                st = FEED.ticks(sym)
                if st is None:
                    return self._send(200, {"sym": sym, "status": "unsupported"})
                return self._send(200, {"sym": sym, "status": "ok" if st["ticks"] else "pending",
                                        "ticks": list(st["ticks"]),
                                        "inout": {"out": st["out"], "in": st["in"]},
                                        "big": {"buy": st["big_buy"], "sell": st["big_sell"],
                                                "thresh": FEED.BIG_LOT}})
            if u.path == "/kbars":
                sym = (qs.get("sym") or [""])[0].strip().upper()
                res = int((qs.get("res") or ["5"])[0])
                days = min(int((qs.get("days") or ["5"])[0]), 10)
                if not TW_SYM.match(sym) or res not in (1, 5, 15, 30, 60):
                    return self._send(400, {"error": "bad_params"})
                return self._send(200, {"bars": FEED.kbars(sym, res, days), "sym": sym, "res": res, "ts": int(time.time())})
            if u.path == "/ranks":
                rtype = (qs.get("type") or ["change"])[0]
                if rtype not in Feed.RANK_TYPES and rtype not in Feed.DERIVED_RANKS:
                    return self._send(400, {"error": "bad_type"})
                return self._send(200, {"ranks": FEED.ranks(rtype), "type": rtype, "ts": int(time.time())})
            if u.path == "/fut":
                prod = (qs.get("c") or [""])[0].strip().upper()
                if not DERIV_PROD.match(prod):
                    return self._send(400, {"error": "bad_params"})
                d = FEED.fut(prod)
                if d is None:
                    return self._send(404, {"error": "unknown product"})
                return self._send(200, {**d, "src": "shioaji", "ts": int(time.time())})
            if u.path == "/optchain":
                prod = (qs.get("c") or [""])[0].strip().upper()
                n = parse_n((qs.get("n") or [None])[0])
                if not DERIV_PROD.match(prod) or n is None:
                    return self._send(400, {"error": "bad_params"})
                d = FEED.optchain(prod, n)
                if d is None:
                    return self._send(404, {"error": "unknown product"})
                return self._send(200, {**d, "src": "shioaji", "ts": int(time.time())})
            if u.path == "/positions":
                return self._send(200, FEED.positions())
            return self._send(404, {"error": "not_found"})
        except UpstreamDataError as ex:
            return self._send(502, {"error": str(ex)[:200]})
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
