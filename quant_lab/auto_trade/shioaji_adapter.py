"""永豐 Shioaji → engine.DataAdapter。同介面,三模式共用。

- BACKTEST:api.kbars() 拉歷史 → Bar(bid/ask 由收盤±spread 近似;要真實逐筆改 use_ticks)
- PAPER/LIVE:訂閱即時 BidAsk,callback 推進 queue,generator 吐 Bar

金鑰走 .env(CLAUDE.md 鐵則):SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY。
simulation=True 走永豐模擬環境(paper),不會下真單。
⚠️ 標「# VERIFY」處禮拜一拿到 API 用實際版本核對欄位名(Shioaji 版本間會變)。
"""
from __future__ import annotations

import os
import queue
import threading

from engine import Bar, DataAdapter, Mode


def _load_env():
    """讀 .env 的 SHIOAJI_* 到 os.environ(若尚未載入)。無 python-dotenv 也能跑。"""
    if os.environ.get("SHIOAJI_API_KEY"):
        return
    bases = []
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = start
        for _ in range(4):                     # 往上走找 repo 根的 .env
            bases.append(d)
            d = os.path.dirname(d)
    for base in bases:
        p = os.path.join(base, ".env")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break


def login_env(simulation=True):
    """讀 .env 登入,相容 1.5(fetch_contract 參數)與 1.7+(已移除)。回 api。
    ⚠️ 安全預設=simulation=True(模擬環境,絕不下真單)。要真實環境的呼叫端**必須明確**
    傳 simulation=False——防止新/手滑程式碼誤登真實環境(記憶 DI 暗門 CRITICAL 根治)。
    注意:真實環境僅供拉資料/真下單;下真單另需 activate_ca 且訂單路徑明確切 place_order。"""
    _load_env()
    import shioaji as sj
    api = sj.Shioaji(simulation=simulation)
    kw = dict(api_key=os.environ["SHIOAJI_API_KEY"],
              secret_key=os.environ["SHIOAJI_SECRET_KEY"])
    try:
        api.login(fetch_contract=True, **kw)
    except TypeError:
        api.login(**kw)
    return api


class ShioajiAdapter(DataAdapter):
    def __init__(self, contracts_spec, mode: Mode, start=None, end=None,
                 simulation=True, spread=0.02, use_ticks=False, max_live=100_000):
        """contracts_spec: [{"type":"stock|future|option","code":"2330|TXFG5|...",
                             "symbol":"對外用的名字(進 Bar.symbol)"}]"""
        self.spec = contracts_spec
        self.mode = mode
        self.start, self.end = start, end
        self.simulation = simulation
        self.spread = spread
        self.use_ticks = use_ticks
        self.api = None
        self._q: queue.Queue = queue.Queue(maxsize=max_live)
        self._stop = threading.Event()

    # ---------- 連線 ----------
    def login(self):
        _load_env()
        api_key = os.environ.get("SHIOAJI_API_KEY")
        secret = os.environ.get("SHIOAJI_SECRET_KEY")
        if not api_key or not secret:
            raise RuntimeError("缺 .env 的 SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY")
        import shioaji as sj  # 延遲載入:沒裝也能 import 本模組
        self.sj = sj
        self.api = sj.Shioaji(simulation=self.simulation)
        self.api.login(api_key=api_key, secret_key=secret, fetch_contract=True)  # VERIFY 參數名
        return self

    def _contract(self, spec):
        c = self.api.Contracts
        t = spec["type"]
        if t == "stock":
            return c.Stocks[spec["code"]]          # ETF 也走 Stocks
        if t == "future":
            return c.Futures[spec["code"]]         # VERIFY: 有時要 c.Futures.TXF[...]
        if t == "option":
            return c.Options[spec["code"]]
        raise ValueError(f"未知 contract type: {t}")

    # ---------- 統一入口 ----------
    def stream(self):
        if self.api is None:
            self.login()
        if self.mode == Mode.BACKTEST:
            yield from self._stream_history()
        else:
            yield from self._stream_live()

    # ---------- 歷史回放 ----------
    def _stream_history(self):
        bars = []
        for spec in self.spec:
            contract = self._contract(spec)
            sym = spec.get("symbol", spec["code"])
            if self.use_ticks:
                bars += self._ticks_to_bars(contract, sym)
            else:
                bars += self._kbars_to_bars(contract, sym)
        bars.sort(key=lambda b: b.t)               # 多標的按時間交錯回放
        yield from bars

    def _kbars_to_bars(self, contract, sym):
        kb = self.api.kbars(contract, start=self.start, end=self.end)  # VERIFY 參數名
        # kb 欄位:ts(ns epoch), Open, High, Low, Close, Volume
        ts, close = list(kb.ts), list(kb.Close)
        out = []
        half = self.spread / 2
        for t, px in zip(ts, close):
            out.append(Bar(t=int(t), symbol=sym, bid=px - half, ask=px + half,
                           last=px, extra={"src": "kbar"}))
        return out

    def _ticks_to_bars(self, contract, sym):
        # 真實逐筆:含真 bid/ask,但要逐日抓(api.ticks 一次一天)
        import datetime
        out = []
        d0 = datetime.date.fromisoformat(self.start)
        d1 = datetime.date.fromisoformat(self.end)
        day = d0
        while day <= d1:
            tk = self.api.ticks(contract, date=day.isoformat())  # VERIFY
            ts = list(getattr(tk, "ts", []))
            bid = list(getattr(tk, "bid_price", []))   # VERIFY 欄位名
            ask = list(getattr(tk, "ask_price", []))
            close = list(getattr(tk, "close", []))
            for i, t in enumerate(ts):
                b = bid[i] if i < len(bid) and bid[i] else close[i]
                a = ask[i] if i < len(ask) and ask[i] else close[i]
                out.append(Bar(int(t), sym, b, a, close[i], {"src": "tick"}))
            day += datetime.timedelta(days=1)
        return out

    # ---------- 即時訂閱(paper/live 共用同一份資料流)----------
    def _stream_live(self):
        sj = self.sj
        symmap = {}
        for spec in self.spec:
            contract = self._contract(spec)
            symmap[spec["code"]] = spec.get("symbol", spec["code"])
            self.api.quote.subscribe(contract,
                                     quote_type=sj.constant.QuoteType.BidAsk,   # VERIFY
                                     version=sj.constant.QuoteVersion.v1)

        def _push(code, bid, ask, last, t):
            sym = symmap.get(code, code)
            try:
                self._q.put_nowait(Bar(int(t), sym, float(bid), float(ask),
                                       float(last), {"src": "live"}))
            except queue.Full:
                pass  # 滿了丟最新?這裡先丟棄,之後可改環狀緩衝

        # 股/ETF 與 期/權 的 callback 不同,兩個都掛
        def on_stk(exchange, bidask):
            # bidask: .code .bid_price[5] .ask_price[5] .datetime  # VERIFY
            _push(bidask.code, bidask.bid_price[0], bidask.ask_price[0],
                  getattr(bidask, "close", bidask.bid_price[0]),
                  bidask.datetime.timestamp() * 1e9)

        def on_fop(exchange, bidask):
            _push(bidask.code, bidask.bid_price[0], bidask.ask_price[0],
                  getattr(bidask, "underlying_price", bidask.bid_price[0]),
                  bidask.datetime.timestamp() * 1e9)

        self.api.quote.set_on_bidask_stk_v1_callback(on_stk)   # VERIFY 方法名
        self.api.quote.set_on_bidask_fop_v1_callback(on_fop)

        while not self._stop.is_set():
            try:
                yield self._q.get(timeout=1.0)
            except queue.Empty:
                continue

    def stop(self):
        self._stop.set()

    def logout(self):
        if self.api is not None:
            try:
                self.api.logout()
            except Exception:
                pass
