"""一個引擎,三模式(backtest / paper / live),共用同一份策略程式碼。

抗自欺內建:walk-forward(每段 OOS 只評一次)、lockbox(留一段絕不看的資料)、
DSR(記 trial 數,把「試很多套挑最好」的運氣打折)、成交模型(穿越價差+滑價,
抓回測看不到的執行陷阱)。禮拜一 Shioaji 到,實作 ShioajiAdapter 接上即可。
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Mode(Enum):
    BACKTEST = "backtest"   # 餵歷史,快速篩策略
    PAPER = "paper"         # 餵即時、模擬成交,抓執行陷阱
    LIVE = "live"           # 餵即時、下真單


@dataclass
class Bar:
    t: int
    symbol: str
    bid: float
    ask: float
    last: float
    extra: dict = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


@dataclass
class Signal:
    symbol: str
    side: int          # +1 買 / -1 賣 / 0 平倉
    size: float
    reason: str = ""


@dataclass
class Fill:
    t: int
    symbol: str
    side: int
    size: float
    price: float       # 已含價差穿越+滑價的「真實」成交價


class DataAdapter(ABC):
    """資料源介面。歷史回放 + 即時都走這個。Shioaji 之後實作同介面。"""
    @abstractmethod
    def stream(self):
        ...


class Strategy(ABC):
    """一份訊號邏輯,三模式共用。禁止在此用未來資料。"""
    @abstractmethod
    def on_bar(self, bar: Bar) -> list[Signal]:
        ...


class FillModel:
    """回測/paper 的成交假設:買穿越到 ask、賣穿越到 bid,再加滑價。
    這一層就是回測 vs 實盤差距的來源——套利的 edge 常常死在這裡。"""
    def __init__(self, slippage_bps: float = 2.0):
        self.slip = slippage_bps / 1e4

    def execute(self, bar: Bar, sig: Signal) -> Fill | None:
        if sig.side == 0 or sig.size <= 0:
            return None
        px = bar.ask if sig.side > 0 else bar.bid   # 你付價差,不是拿中價
        px *= (1 + self.slip * sig.side)            # 再滑一點
        return Fill(bar.t, sig.symbol, sig.side, sig.size, px)


class Engine:
    def __init__(self, strategy: Strategy, adapter: DataAdapter, mode: Mode,
                 fill_model: FillModel | None = None, fee_bps: float = 1.5):
        self.strat = strategy
        self.adapter = adapter
        self.mode = mode
        self.fills = fill_model or FillModel()
        self.fee = fee_bps / 1e4
        self.pos: dict[str, float] = {}
        self.cash = 0.0
        self.trade_pnls: list[float] = []
        self._entry: dict[str, tuple[float, float]] = {}  # symbol -> (side*size, price)

    def run(self):
        for bar in self.adapter.stream():
            for sig in self.strat.on_bar(bar):
                if self.mode == Mode.LIVE:
                    raise NotImplementedError("接 ShioajiAdapter 下真單:Monday")
                fill = self.fills.execute(bar, sig)
                if fill:
                    self._apply(fill)
        return self.result()

    def _apply(self, f: Fill):
        cost = f.price * f.size
        fee = cost * self.fee
        signed = f.side * f.size
        prev = self.pos.get(f.symbol, 0.0)
        # 平倉即結算一筆已實現損益(供 per-trade 統計)
        if prev != 0 and (prev > 0) != (f.side > 0):
            e_signed, e_px = self._entry.get(f.symbol, (prev, f.price))
            closed = min(abs(prev), f.size)
            pnl = (f.price - e_px) * closed * (1 if prev > 0 else -1) - fee
            self.trade_pnls.append(pnl)
        self.pos[f.symbol] = prev + signed
        if self.pos[f.symbol] != 0:
            self._entry[f.symbol] = (self.pos[f.symbol], f.price)
        self.cash -= fee

    def result(self) -> dict:
        return {
            "mode": self.mode.value,
            "n_trades": len(self.trade_pnls),
            "total_pnl": round(sum(self.trade_pnls), 4),
            "trade_pnls": self.trade_pnls,
        }


# ---------- 抗自欺的統計工具 ----------

def deflated_sharpe(sharpe: float, n_trials: int, n_obs: int) -> float:
    """DSR(Bailey & López de Prado 簡化版)→ 回傳『扣掉試 n_trials 套的運氣後,
    真 Sharpe > 0 的機率』∈[0,1]。~0.5 或以下 = 很可能純運氣;越接近 1 = 越可信。
    sharpe 為每筆(per-trade)口徑;無 skew/kurt 修正(demo 簡化)。"""
    if n_obs < 2 or n_trials < 1:
        return 0.0
    # 純運氣下,試 n_trials 套能撈到的最大期望 Sharpe(每筆口徑)
    euler = 0.5772156649
    z = (1 - euler) * _norm_ppf(1 - 1.0 / n_trials) + euler * _norm_ppf(1 - 1.0 / (n_trials * math.e))
    sr0 = z / math.sqrt(n_obs)                       # 運氣門檻(per-trade)
    stat = (sharpe - sr0) * math.sqrt(n_obs - 1)     # 標準化成 z 分數
    return round(_norm_cdf(stat), 3)                 # → 機率


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    m = sum(pnls) / len(pnls)
    var = sum((x - m) ** 2 for x in pnls) / (len(pnls) - 1)
    return m / math.sqrt(var) if var > 0 else 0.0


def _norm_ppf(p: float) -> float:
    # Acklam 近似,避免依賴 scipy
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= ph:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def split_lockbox(data: list, train=0.6, oos=0.25):
    """三段:train(可反覆調)/ oos(walk-forward 驗)/ lockbox(絕不看,最後只跑一次)。"""
    n = len(data)
    i, j = int(n * train), int(n * (train + oos))
    return data[:i], data[i:j], data[j:]


def walk_forward(data: list, window: int, step: int):
    """滾動窗:每段 in-sample 之後緊接一段 out-of-sample,OOS 只評一次、不回頭重調。"""
    out = []
    s = 0
    while s + window + step <= len(data):
        out.append((data[s:s + window], data[s + window:s + window + step]))
        s += step
    return out
