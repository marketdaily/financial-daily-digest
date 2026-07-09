import re
import yfinance as yf
from yahooquery import Ticker as YQTicker
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from config import (
    NEWS_API_KEY, US_INDICES, NEWS_WHITELIST_DOMAINS, TW_NEWS_WHITELIST_DOMAINS
)
from config_loader import get_us_stocks, get_tw_stocks, get_us_feeds, get_tw_feeds, get_domains

RSS_FEEDS = [
    # 美股財經
    ("reuters.com",     "https://feeds.reuters.com/reuters/businessNews"),
    ("cnbc.com",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("cnbc.com",        "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("cnbc.com",        "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("marketwatch.com", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("marketwatch.com", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("finance.yahoo.com","https://finance.yahoo.com/news/rssindex"),
    ("investing.com",   "https://www.investing.com/rss/news.rss"),
    ("investing.com",   "https://www.investing.com/rss/stock_market_news.rss"),
    ("seekingalpha.com","https://seekingalpha.com/market_currents.xml"),
    ("ft.com",          "https://www.ft.com/?format=rss"),
]

TW_RSS_FEEDS = [
    # 台股中文財經(2026-07-06 實測汰換:moneydj/cna feedburner/udn 舊 feed 已死回 0 篇)
    ("tw.stock.yahoo.com", "https://tw.stock.yahoo.com/rss?category=news"),
    ("technews.tw",        "https://technews.tw/feed/"),
    ("money.udn.com",      "https://money.udn.com/rssfeed/news/1001/5591?ch=money"),
]

def fetch_rss_news() -> list:
    articles = []
    cutoff = datetime.now() - timedelta(hours=36)
    feeds = get_us_feeds() or RSS_FEEDS
    for domain, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if published and published < cutoff:
                    continue
                articles.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", "")[:200],
                    "url": entry.get("link", f"https://{domain}"),
                    "source": {"name": domain},
                    "publishedAt": published.isoformat() if published else "",
                })
        except Exception:
            continue
    return articles


def _batch_prices(symbols: list) -> dict:
    """yahooquery 批次抓 + 重試 + yfinance 逐檔備援。
    GH Actions 上 Yahoo 常整批失敗(429/空回),7am 寄送時害美股全變「今日無報價」,故加韌性。"""
    if not symbols:
        return {}
    result = {}
    for _ in range(2):
        try:
            data = YQTicker(symbols).price
            if isinstance(data, dict):
                for sym in symbols:
                    if sym in result:
                        continue
                    p = data.get(sym, {})
                    if not isinstance(p, dict):
                        continue
                    price = p.get("regularMarketPrice")
                    prev = p.get("regularMarketPreviousClose")
                    if price and prev and prev != 0:
                        result[sym] = {
                            "price": round(float(price), 2),
                            "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 2),
                        }
            if len(result) == len(symbols):
                return result
        except Exception:
            pass
    # yahooquery 沒補齊的,逐檔用 yfinance 歷史價備援(不同 endpoint,常在 quote API 被擋時仍可用)
    for sym in [s for s in symbols if s not in result]:
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if len(hist) >= 2:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                if price and prev and prev != 0:
                    result[sym] = {
                        "price": round(price, 2),
                        "change_pct": round((price - prev) / prev * 100, 2),
                    }
        except Exception:
            continue
    return result


def _get_cached_price(symbol: str) -> dict:
    return _batch_prices([symbol]).get(symbol, {})


# TWSE OpenAPI — 一次取全部台股收盤，官方數據無 rate limit
_TWSE_CACHE: dict = {}
_TWSE_CACHE_TIME: datetime = None
_TWSE_DATA_DATE: str = None  # 這批 TWSE 收盤資料實際對應的交易日(ISO),用來判新鮮度


def _roc_to_iso(roc: str) -> str:
    """TWSE Date 欄位 '1150629'(民國) → '2026-06-29'。失敗回 None。"""
    try:
        roc = str(roc).strip()
        return f"{int(roc[:-4]) + 1911:04d}-{roc[-4:-2]}-{roc[-2:]}"
    except Exception:
        return None


def _parse_tw_change(raw) -> float:
    """台股除權息日 TWSE/TPEx 的 Change 欄位常是文字('除息'/'除權'/'除權息',可能夾帶數字)。
    直接 float() 會 ValueError 導致整支股票被丟棄(除息日報價消失)。
    這裡:純數字直接轉;夾帶數字抽數字;純文字(如'除息')回 0(當平盤,保留收盤價不丟股)。"""
    s = str(raw).strip()
    try:
        return float(s)
    except ValueError:
        pass
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return 0.0


def _fetch_twse_all() -> dict:
    """Return {stock_code: {name, price, change_pct}} for all TWSE listed stocks"""
    global _TWSE_CACHE, _TWSE_CACHE_TIME, _TWSE_DATA_DATE
    now = datetime.now()
    if _TWSE_CACHE and _TWSE_CACHE_TIME and (now - _TWSE_CACHE_TIME).seconds < 3600:
        return _TWSE_CACHE
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=15
        )
        data = resp.json()
        result = {}
        data_date = None
        for row in data:
            code = row.get("Code", "")
            if not code.isdigit():
                continue
            if data_date is None and row.get("Date"):
                data_date = _roc_to_iso(row["Date"])
            try:
                close = float(row["ClosingPrice"])
                change = _parse_tw_change(row["Change"])
                prev = close - change
                change_pct = (change / prev * 100) if prev != 0 else 0
                result[code] = {
                    "name": row.get("Name", code),
                    "price": round(close, 2),
                    "change_pct": round(change_pct, 2),
                }
            except (ValueError, ZeroDivisionError):
                continue
        _TWSE_CACHE = result
        _TWSE_CACHE_TIME = now
        _TWSE_DATA_DATE = data_date
        return result
    except Exception:
        return _TWSE_CACHE


def _expected_tw_session_date() -> str:
    """目前 TW 時間下,台股「應該已有收盤數據」的最近交易日(ISO)。
    台股 13:30 收盤,實務上 14:00 後就該有當日全市場收盤;故 TW 時間 ≥14:00 且今天是交易日
    → 期望今日;否則期望最近的過去交易日。給 _twse_is_stale 比對用。"""
    try:
        from analyzer import _TW_HOLIDAYS as holidays
    except Exception:
        holidays = set()
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)

    def _is_trading(d):
        return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in holidays

    d = tw_now.date()
    if not (_is_trading(d) and tw_now.hour >= 14):
        d = d - timedelta(days=1)
        for _ in range(10):
            if _is_trading(d):
                break
            d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _twse_is_stale() -> bool:
    """TWSE STOCK_DAY_ALL 端點偶爾延遲更新(尤其晚班 20:00 生成時仍停在上一交易日),
    導致個股收盤是舊的、卻和即時的加權指數(Yahoo)併在同一封信 → 日期打架。
    必須先呼叫過 _fetch_twse_all()。資料日 < 期望交易日即判定過期。"""
    if not _TWSE_DATA_DATE:
        return False
    return _TWSE_DATA_DATE < _expected_tw_session_date()


def _tw_stocks_via_yahoo(codes: list, twse: dict, tpex: dict) -> dict:
    """TWSE 過期時改用 Yahoo 抓指定台股收盤(與加權指數同源同日,消除日期打架)。
    回 {code: {name, price, change_pct}};名稱沿用 TWSE/TPEx 既有對照。
    上市用 .TW、上櫃用 .TWO;不確定者(兩個官方源都過期/查無)兩種後綴都試,避免上櫃股漏掉。"""
    codes = [c for c in (codes or []) if c and c.isdigit()]
    if not codes:
        return {}
    tpex = tpex or {}
    out = {}

    def _label(c, p):
        # 名稱查無時寧可留空,不可拿裸代號當名稱(會蓋掉 tw_names_all 的正確名字)
        nm = ((twse.get(c) or {}).get("name") or (tpex.get(c) or {}).get("name")
              or tw_name_map().get(c) or "")
        out[c] = {"name": nm, "price": p["price"], "change_pct": p["change_pct"]}

    ymap = {c: _yahoo_symbol(c, twse, tpex) for c in codes}
    prices = _batch_prices(list(ymap.values()))
    for c, ysym in ymap.items():
        if prices.get(ysym):
            _label(c, prices[ysym])
    # 第一輪沒中的,改用另一個後綴重試(.TW↔.TWO),救官方源過期時無法判市別的上櫃股
    miss = [c for c in codes if c not in out]
    if miss:
        alt = {c: (f"{c}.TWO" if ymap[c].endswith(".TW") else f"{c}.TW") for c in miss}
        alt_prices = _batch_prices(list(alt.values()))
        for c, ysym in alt.items():
            if alt_prices.get(ysym):
                _label(c, alt_prices[ysym])
    return out


# 本班次「主源查無、連 Yahoo 都救不回」的台股代號(去重),run 尾端由 main.py 推 admin。
_LAST_TW_MISSING: list = []

def _rescue_missing_tw(codes: list, resolved: dict, twse: dict, tpex: dict) -> None:
    """覆蓋率守門+自我修復:任何要求的台股代號在主源(TWSE/TPEx)查無報價,
    改用 Yahoo(.TW/.TWO 都試)救回,就地補進 resolved。
    連 Yahoo 都救不回的才記進 _LAST_TW_MISSING,由 main.py 推 admin(web push)。"""
    want = [c for c in (codes or []) if isinstance(c, str) and c.isdigit()]
    missing = [c for c in want if c not in resolved]
    if not missing:
        return
    rescued = _tw_stocks_via_yahoo(missing, twse or {}, tpex or {})
    for c in missing:
        if c in rescued:
            resolved[c] = rescued[c]
    for c in missing:
        if c not in resolved and c not in _LAST_TW_MISSING:
            _LAST_TW_MISSING.append(c)


# TPEx OpenAPI — 上櫃股票收盤(含群聯 8299、精測 6510 等),官方數據無 rate limit
_TPEX_CACHE: dict = {}
_TPEX_CACHE_TIME: datetime = None

def _fetch_tpex_all() -> dict:
    """Return {stock_code: {name, price, change_pct}} for all TPEx (上櫃) stocks"""
    global _TPEX_CACHE, _TPEX_CACHE_TIME
    now = datetime.now()
    if _TPEX_CACHE and _TPEX_CACHE_TIME and (now - _TPEX_CACHE_TIME).seconds < 3600:
        return _TPEX_CACHE
    # TPEx 部分節點憑證缺 Subject Key Identifier → Python3.13+ 嚴格驗證間歇 SSLError,
    # 重試換節點幾乎必成功(2026-07-09 事故:連兩次踩壞節點 → 上櫃名字全滅)
    for _ in range(4):
        try:
            resp = requests.get(
                "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
                timeout=15
            )
            result = {}
            for row in resp.json():
                code = (row.get("SecuritiesCompanyCode") or "").strip()
                if not code.isdigit():
                    continue
                try:
                    close = float(str(row["Close"]).strip())
                    change = _parse_tw_change(row["Change"])
                    prev = close - change
                    change_pct = (change / prev * 100) if prev != 0 else 0
                    result[code] = {
                        "name": (row.get("CompanyName") or code).strip(),
                        "price": round(close, 2),
                        "change_pct": round(change_pct, 2),
                    }
                except (ValueError, ZeroDivisionError, KeyError):
                    continue
            if result:
                _TPEX_CACHE = result
                _TPEX_CACHE_TIME = now
                return _TPEX_CACHE
        except Exception:
            continue
    return _TPEX_CACHE


_TW_NAME_CACHE: dict = {}
_TW_NAME_CACHE_TIME: datetime = None

def _tw_names_disk_path() -> str:
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", ".tw_names_cache.json")

def tw_name_map() -> dict:
    """全部上市(TWSE)+上櫃(TPEx)台股 {code: 中文名},給日報把代號展開成公司名。
    官方源斷線時(如 2026-07-09 winrig certifi 過期 → TPEx SSL 失敗)沿用磁碟上
    最後一次成功的名稱表,名字永不歸零 → 日報不會出現裸代號。"""
    global _TW_NAME_CACHE, _TW_NAME_CACHE_TIME
    import json
    now = datetime.now()
    if _TW_NAME_CACHE and _TW_NAME_CACHE_TIME and (now - _TW_NAME_CACHE_TIME).seconds < 3600:
        return _TW_NAME_CACHE
    names = {}
    try:
        for c, d in _fetch_twse_all().items():
            if d.get("name"):
                names[c] = d["name"]
    except Exception:
        pass
    for _ in range(4):
        try:
            resp = requests.get(
                "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
                timeout=15
            )
            for row in resp.json():
                code = (row.get("SecuritiesCompanyCode") or "").strip()
                name = (row.get("CompanyName") or "").strip()
                if code and name:
                    names.setdefault(code, name)
            break
        except Exception:
            continue
    fetched = len(names)
    disk = {}
    try:
        with open(_tw_names_disk_path(), encoding="utf-8") as f:
            disk = json.load(f) or {}
    except Exception:
        pass
    for c, n in disk.items():
        names.setdefault(c, n)
    if fetched and len(names) >= len(disk):
        try:
            with open(_tw_names_disk_path(), "w", encoding="utf-8") as f:
                json.dump(names, f, ensure_ascii=False)
        except Exception:
            pass
    if names:
        _TW_NAME_CACHE = names
        _TW_NAME_CACHE_TIME = now
    return _TW_NAME_CACHE or names


def fetch_us_market():
    active_stocks = get_us_stocks()
    symbols = US_INDICES + [s if isinstance(s, str) else s["symbol"] for s in active_stocks]
    result = {}
    for sym in symbols:
        d = _get_cached_price(sym)
        if d:
            result[sym] = d
    return result


def fetch_tw_market():
    twse = _fetch_twse_all()
    tpex = _fetch_tpex_all()
    result = {}
    d = _get_cached_price("^TWII")
    if d:
        result["^TWII"] = d
    codes = [s["symbol"] if isinstance(s, dict) else s for s in get_tw_stocks()]
    # TWSE 端點延遲(晚班常見)→ 個股改走 Yahoo,與上方加權指數同日,避免日期打架
    yahoo_tw = _tw_stocks_via_yahoo(codes, twse, tpex) if _twse_is_stale() else {}
    for code in codes:
        if code in yahoo_tw:
            result[code] = yahoo_tw[code]
        elif code in twse:
            result[code] = twse[code]
        elif code in tpex:
            result[code] = tpex[code]
    _rescue_missing_tw(codes, result, twse, tpex)
    return result


def fetch_custom_stocks(symbols: list) -> dict:
    twse = _fetch_twse_all()
    tpex = None
    result = {}
    tw_codes = [s for s in symbols if s.isdigit()]
    yahoo_tw = {}
    if tw_codes and _twse_is_stale():
        tpex = _fetch_tpex_all()
        yahoo_tw = _tw_stocks_via_yahoo(tw_codes, twse, tpex)
    for sym in symbols:
        if sym.isdigit():
            if sym in yahoo_tw:
                result[sym] = yahoo_tw[sym]
            elif sym in twse:
                result[sym] = twse[sym]
            else:
                if tpex is None:
                    tpex = _fetch_tpex_all()
                if sym in tpex:
                    result[sym] = tpex[sym]
        else:
            d = _get_cached_price(sym)
            if d:
                result[sym] = d
    if tw_codes:
        if tpex is None:
            tpex = _fetch_tpex_all()
        _rescue_missing_tw(tw_codes, result, twse, tpex)
    return result


def _yahoo_symbol(code: str, twse: dict, tpex: dict) -> str:
    if code.isdigit():
        if code in twse:
            return f"{code}.TW"
        if code in tpex:
            return f"{code}.TWO"
        return f"{code}.TW"
    return code


def fetch_technicals(symbols: list) -> dict:
    """各持股真實技術價位:現價/MA20/MA50/20日高低/60日高低/ATR14,給日報訂進出場關卡用真實數字。"""
    syms = list(dict.fromkeys([s for s in (symbols or []) if s]))
    if not syms:
        return {}
    import pandas as pd
    twse = _fetch_twse_all()
    tpex = _fetch_tpex_all()
    ymap = {s: _yahoo_symbol(s, twse, tpex) for s in syms}
    try:
        h = YQTicker(list(ymap.values())).history(period="3mo")
    except Exception:
        return {}
    if h is None or not hasattr(h, "columns") or "close" not in getattr(h, "columns", []):
        return {}
    out = {}
    for raw, ysym in ymap.items():
        try:
            df = h
            if isinstance(h.index, pd.MultiIndex):
                lvl0 = h.index.get_level_values(0)
                if ysym not in lvl0:
                    continue
                df = h.xs(ysym, level=0)
            c = df["close"].dropna()
            if len(c) < 25:
                continue
            hi, lo = df["high"], df["low"]
            prev = c.shift(1)
            tr = pd.concat([(hi - lo), (hi - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            price = float(c.iloc[-1])
            ma20 = round(float(c.tail(20).mean()), 2)
            ma50 = round(float(c.tail(50).mean()), 2) if len(c) >= 50 else None
            row = {
                "price": round(price, 2),
                "ma20": ma20,
                "ma50": ma50,
                "hi20": round(float(hi.tail(20).max()), 2),
                "lo20": round(float(lo.tail(20).min()), 2),
                "hi60": round(float(hi.tail(60).max()), 2),
                "lo60": round(float(lo.tail(60).min()), 2),
                "atr14": round(float(atr), 2),
            }
            row.update(_advanced_indicators(c, hi, lo, price, ma20, ma50))
            if "volume" in getattr(df, "columns", []):
                row.update(_volume_metrics(c, df["volume"]))
            out[raw] = row
        except Exception:
            continue
    return out


def _advanced_indicators(c, hi, lo, price, ma20, ma50):
    """進階技術指標(專業版/deep 用):RSI14 / MACD / KD / 布林 / MA5 / 交叉 / 排列。
    全部從同一份 3 個月 OHLCV 算,失敗某項回 None,不拖垮整批。"""
    import pandas as pd
    out = {}
    def _f(v, n=2):
        try:
            return round(float(v), n) if pd.notna(v) else None
        except Exception:
            return None
    try:
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        out["rsi14"] = _f(100 - 100 / (1 + rs.iloc[-1]), 1)
    except Exception:
        out["rsi14"] = None
    try:
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        out["macd_dif"] = _f(dif.iloc[-1])
        out["macd_dea"] = _f(dea.iloc[-1])
        out["macd_hist"] = _f((dif.iloc[-1] - dea.iloc[-1]))
    except Exception:
        out["macd_dif"] = out["macd_dea"] = out["macd_hist"] = None
    try:
        low9 = lo.rolling(9).min()
        high9 = hi.rolling(9).max()
        rsv = ((c - low9) / (high9 - low9) * 100).fillna(50)
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        out["k"] = _f(k.iloc[-1], 1)
        out["d"] = _f(d.iloc[-1], 1)
    except Exception:
        out["k"] = out["d"] = None
    try:
        mid = c.rolling(20).mean()
        std = c.rolling(20).std()
        out["boll_up"] = _f(mid.iloc[-1] + 2 * std.iloc[-1])
        out["boll_mid"] = _f(mid.iloc[-1])
        out["boll_low"] = _f(mid.iloc[-1] - 2 * std.iloc[-1])
    except Exception:
        out["boll_up"] = out["boll_mid"] = out["boll_low"] = None
    try:
        ma5 = float(c.tail(5).mean())
        out["ma5"] = round(ma5, 2)
        ma5s = c.rolling(5).mean()
        ma20s = c.rolling(20).mean()
        diff = (ma5s - ma20s).dropna()
        cross = None
        if len(diff) >= 3:
            recent = diff.tail(3)
            if recent.iloc[0] <= 0 and recent.iloc[-1] > 0:
                cross = "黃金交叉"
            elif recent.iloc[0] >= 0 and recent.iloc[-1] < 0:
                cross = "死亡交叉"
        out["cross"] = cross
    except Exception:
        out["ma5"] = out["cross"] = None
    try:
        if ma50 and price > ma20 > ma50:
            out["trend"] = "多頭排列"
        elif ma50 and price < ma20 < ma50:
            out["trend"] = "空頭排列"
        else:
            out["trend"] = "盤整"
    except Exception:
        out["trend"] = None
    return out


def _volume_metrics(c, v):
    """量能佐證(全檔次用):相對量比+量能狀態+量價配合/背離。
    只當敘事佐證,不碰方向/信心/價位死防線。資料不足回空 dict。"""
    out = {}
    try:
        vol = v.dropna()
        if len(vol) < 20:
            return out
        vma20 = float(vol.tail(20).mean())
        if not vma20 or vma20 <= 0:
            return out
        ratio = float(vol.iloc[-1]) / vma20
        out["vol_ratio"] = round(ratio, 2)
        if ratio >= 2.0:
            state = "爆量"
        elif ratio >= 1.5:
            state = "帶量"
        elif ratio <= 0.6:
            state = "量縮"
        else:
            state = "量平"
        out["vol_state"] = state
        cc = c.dropna()
        if len(cc) >= 6:
            p_chg = float(cc.iloc[-1]) / float(cc.iloc[-6]) - 1
            v_recent = float(vol.tail(5).mean()) / vma20
            up = p_chg > 0.02
            down = p_chg < -0.02
            v_up = v_recent >= 1.15
            v_dn = v_recent <= 0.85
            pv = None
            if up and v_up:
                pv = "價漲量增(量價齊揚,確認)"
            elif up and v_dn:
                pv = "價漲量縮(背離,追高留意)"
            elif down and v_up:
                pv = "價跌量增(賣壓沉重,弱勢)"
            elif down and v_dn:
                pv = "價跌量縮(賣壓趨緩)"
            if pv:
                out["pv"] = pv
    except Exception:
        return out
    return out


def fetch_ticker_news(extra_symbols: list = None) -> list:
    articles = []
    seen = set()
    base = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "TSM", "AMD"]
    all_symbols = list(dict.fromkeys(base + (extra_symbols or [])))
    for symbol in all_symbols:
        try:
            ticker = yf.Ticker(symbol)
            for item in ticker.news[:5]:
                title = item.get("title", "")
                if title in seen:
                    continue
                seen.add(title)
                url = item.get("link", "")
                domain = url.split("/")[2].replace("www.", "") if url else "finance.yahoo.com"
                articles.append({
                    "title": title,
                    "description": item.get("summary", ""),
                    "url": url,
                    "source": {"name": domain},
                    "publishedAt": "",
                    "relatedTicker": symbol,
                })
        except Exception:
            continue
    return articles


def fetch_us_news(extra_tickers: list = None):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    domains = ",".join(get_domains() or NEWS_WHITELIST_DOMAINS)
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=stock+market+economy+fed+earnings"
        f"&domains={domains}"
        f"&from={yesterday}"
        f"&language=en"
        f"&sortBy=relevancy"
        f"&pageSize=20"
        f"&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        api_articles = data.get("articles", [])
    except Exception:
        api_articles = []

    rss_articles = fetch_rss_news()
    ticker_articles = fetch_ticker_news(extra_tickers)
    return api_articles + rss_articles + ticker_articles


def _fetch_cnyes_tw_news(limit: int = 15) -> list:
    """Fetch TW stock news from cnyes.com API."""
    categories = ["tw_stock", "headline"]
    articles = []
    cutoff = datetime.now() - timedelta(hours=36)
    seen = set()
    for cat in categories:
        try:
            resp = requests.get(
                f"https://news.cnyes.com/api/v3/news/category/{cat}",
                params={"limit": limit},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            items = resp.json().get("items", {}).get("data", [])
            for item in items:
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                pub_ts = item.get("publishAt", 0)
                published = datetime.fromtimestamp(pub_ts) if pub_ts else None
                if published and published < cutoff:
                    continue
                news_id = item.get("newsId", "")
                url = f"https://news.cnyes.com/news/id/{news_id}" if news_id else "https://news.cnyes.com"
                seen.add(title)
                articles.append({
                    "title": title,
                    "description": item.get("summary", "")[:200],
                    "url": url,
                    "source": {"name": "cnyes.com"},
                    "publishedAt": published.isoformat() if published else "",
                    "lang": "zh",
                })
        except Exception:
            continue
    return articles


def fetch_tw_rss_news() -> list:
    articles = _fetch_cnyes_tw_news()
    cutoff = datetime.now() - timedelta(hours=36)
    seen_titles = {a["title"] for a in articles}

    fallback_feeds = get_tw_feeds() or TW_RSS_FEEDS
    for domain, url in fallback_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if published and published < cutoff:
                    continue
                seen_titles.add(title)
                articles.append({
                    "title": title,
                    "description": entry.get("summary", "")[:200],
                    "url": entry.get("link", f"https://{domain}"),
                    "source": {"name": domain},
                    "publishedAt": published.isoformat() if published else "",
                    "lang": "zh",
                })
        except Exception:
            continue
    return articles


_TW_STOCK_NEWS_JUNK = ("個股概覽", "爆料同學會", "PTT", "Dcard")


def _fetch_tw_stock_news(codes: list) -> list:
    """每支台股持股用 Google News RSS(zh-TW)查「名稱+代號」點名新聞。
    泛市場源(cnyes/yahoo)只蓋權值股,持股沒被頭條提到就整天零新聞 → 這裡逐支補洞。
    只收白名單媒體 + 36h 內,來源域名取自 entry.source(Google 連結是轉址不能 parse URL)。"""
    if not codes:
        return []
    import urllib.parse
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    names = tw_name_map()
    cutoff = datetime.now() - timedelta(hours=36)
    uniq = list(dict.fromkeys([str(c) for c in codes if str(c).isdigit()]))[:80]

    def _whitelisted(domain: str) -> bool:
        return any(domain == d or domain.endswith("." + d) for d in TW_NEWS_WHITELIST_DOMAINS)

    def _one(code: str) -> list:
        name = names.get(code)
        if not name:
            return []
        q = urllib.parse.quote(f"{name} {code}")
        out = []
        try:
            feed = feedparser.parse(
                f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
            for entry in feed.entries[:15]:
                if len(out) >= 3:
                    break
                title = (entry.get("title") or "").strip()
                if not title or any(j in title for j in _TW_STOCK_NEWS_JUNK):
                    continue
                if not getattr(entry, "published_parsed", None):
                    continue
                published = datetime.fromtimestamp(_time.mktime(entry.published_parsed))
                if published < cutoff:
                    continue
                src = getattr(entry, "source", {}) or {}
                href = src.get("href", "")
                domain = href.split("/")[2].replace("www.", "") if href.startswith("http") else ""
                if not _whitelisted(domain):
                    continue
                src_name = (src.get("title") or domain).strip()
                if src_name and title.endswith(" - " + src_name):
                    title = title[:-(len(src_name) + 3)].strip()
                out.append({
                    "title": title,
                    "description": "",
                    "url": entry.get("link", ""),
                    "source": {"name": src_name},
                    "source_domain": domain,
                    "publishedAt": published.isoformat(),
                    "lang": "zh",
                    "relatedTicker": code,
                })
        except Exception:
            pass
        return out

    articles, seen = [], set()
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_one, uniq):
            for a in res:
                if a["title"] in seen:
                    continue
                seen.add(a["title"])
                articles.append(a)
    return articles


def fetch_tw_news(extra_tw_stocks: list = None):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=Taiwan+stock+TSMC+TWD+Taiwan+economy"
        f"&from={yesterday}"
        f"&language=en"
        f"&sortBy=relevancy"
        f"&pageSize=20"
        f"&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        api_articles = data.get("articles", [])
    except Exception:
        api_articles = []
    tw_rss = fetch_tw_rss_news()
    # 個股點名新聞:有持股用持股,無持股(公版)用預設台股池,保證每支都查過一輪
    per_stock_codes = extra_tw_stocks or [s for s in get_tw_stocks() if str(s).isdigit()][:10]
    per_stock = _fetch_tw_stock_news(per_stock_codes)
    return api_articles + tw_rss + per_stock


def fetch_indicators() -> dict:
    ind_syms = ["^VIX", "^TNX", "GC=F", "CL=F", "TWD=X"]
    raw = _batch_prices(ind_syms)
    indicators = {}

    if "^VIX" in raw:
        indicators["vix"] = raw["^VIX"]["price"]
    if "^TNX" in raw:
        indicators["us10y"] = raw["^TNX"]["price"]
    if "GC=F" in raw:
        indicators["gold"] = {"price": raw["GC=F"]["price"], "change_pct": raw["GC=F"]["change_pct"]}
    if "CL=F" in raw:
        indicators["oil"] = {"price": raw["CL=F"]["price"], "change_pct": raw["CL=F"]["change_pct"]}
    if "TWD=X" in raw:
        indicators["usdtwd"] = {"rate": raw["TWD=X"]["price"], "change_pct": raw["TWD=X"]["change_pct"]}

    if "vix" in indicators:
        vix = indicators["vix"]
        if vix > 30:   score, rating = 15, "Extreme Fear"
        elif vix > 25: score, rating = 30, "Fear"
        elif vix > 20: score, rating = 45, "Neutral"
        elif vix > 15: score, rating = 65, "Greed"
        else:          score, rating = 80, "Extreme Greed"
        indicators["fear_greed"] = {"score": score, "rating": rating}

    return indicators


def fetch_crypto() -> dict:
    raw = _batch_prices(["BTC-USD", "ETH-USD"])
    result = {}
    if "BTC-USD" in raw:
        result["btc"] = raw["BTC-USD"]
    if "ETH-USD" in raw:
        result["eth"] = raw["ETH-USD"]
    return result


SECTOR_ETFS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "醫療",
    "XLY": "非必需消費",
    "XLC": "通訊",
    "XLI": "工業",
    "XLP": "必需消費",
}


def fetch_sector_performance() -> list:
    sectors = []
    raw = _batch_prices(list(SECTOR_ETFS.keys()))
    for symbol, name in SECTOR_ETFS.items():
        if symbol in raw:
            sectors.append({"symbol": symbol, "name": name, "change_pct": raw[symbol]["change_pct"]})
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    return sectors


def fetch_earnings_calendar() -> list:
    """財報日曆。優先用 FMP stable API(含已核實的市場預期 EPS / 營收),
    拿不到再退回 yfinance(只有日期,不帶任何預期數字 — LLM 嚴禁自行補)。"""
    import os
    events = []
    watchlist = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "TSM"]
    fmp_key = os.environ.get("FMP_API_KEY", "").strip()
    if fmp_key:
        try:
            frm = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            to = (datetime.now(timezone.utc) + timedelta(days=120)).strftime("%Y-%m-%d")
            resp = requests.get(
                "https://financialmodelingprep.com/stable/earnings-calendar",
                params={"from": frm, "to": to, "apikey": fmp_key}, timeout=20)
            rows = resp.json()
            if isinstance(rows, list):
                by_sym: dict = {}
                for r in rows:
                    s = r.get("symbol")
                    d = (r.get("date") or "")[:10]
                    if s in watchlist and d and (s not in by_sym or d < by_sym[s]["date"]):
                        by_sym[s] = {"symbol": s, "date": d,
                                     "eps_est": r.get("epsEstimated"),
                                     "rev_est": r.get("revenueEstimated")}
                events = list(by_sym.values())
        except Exception as e:
            print(f"[earnings] FMP failed, fallback yfinance dates-only: {e}")
    if events:
        events.sort(key=lambda x: x["date"])
        return events
    for symbol in watchlist:
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if cal is None:
                continue
            if isinstance(cal, dict):
                date_val = cal.get("Earnings Date")
                if date_val:
                    if isinstance(date_val, list):
                        date_val = date_val[0]
                    events.append({"symbol": symbol, "date": str(date_val)[:10]})
            elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
                date_val = cal["Earnings Date"].iloc[0]
                events.append({"symbol": symbol, "date": str(date_val)[:10]})
        except Exception:
            continue
    events.sort(key=lambda x: x["date"])
    return events


def fetch_all(extra_us_stocks: list = None, extra_tw_stocks: list = None):
    us_market = fetch_us_market()
    if extra_us_stocks:
        missing = [s for s in extra_us_stocks if s not in us_market]
        if missing:
            us_market.update(fetch_custom_stocks(missing))

    tw_market = fetch_tw_market()
    if extra_tw_stocks:
        missing_tw = [s for s in extra_tw_stocks if s not in tw_market]
        if missing_tw:
            tw_market.update(fetch_custom_stocks(missing_tw))

    # 公版預設關注股(無持股用戶/公版日報/AI 精選候選池用):美股全預設池 + 台股權值,
    # 確保公版 signal-card 與委員會精選都有真實技術價位可錨
    default_us_syms = [s for s in get_us_stocks() if isinstance(s, str)][:15]
    tech_syms = list(dict.fromkeys(
        (extra_us_stocks or []) + (extra_tw_stocks or [])
        + default_us_syms + ["AAPL", "MSFT", "NVDA", "TSLA", "2330", "2454", "2317"]))
    technicals = fetch_technicals(tech_syms)

    the_date = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    # 財報/營收影響(事件日才喊話) — 估值出錯絕不拖垮日報,整段 try 包住
    earnings_impact = {}
    try:
        import datetime as _dt
        from valuation.earnings_impact import compute_impacts
        earnings_impact = compute_impacts(extra_us_stocks, extra_tw_stocks,
                                          _dt.date.fromisoformat(the_date))
    except Exception as _e:
        print(f"[earnings_impact] skipped: {_e}")

    # 估值帶 + 籌碼/法人(看深入專屬) — 缺料 / 無 key 一律跳過,絕不拖垮日報
    fundamentals = {}
    try:
        import datetime as _dt2
        from valuation.fundamentals import compute_fundamentals
        fundamentals = compute_fundamentals(extra_us_stocks, extra_tw_stocks,
                                            _dt2.date.fromisoformat(the_date), earnings_impact)
    except Exception as _e:
        print(f"[fundamentals] skipped: {_e}")

    # 政壇市場訊號(Grok 抓政治人物 X 貼文) — 無 XAI_API_KEY 時回 [],缺了不缺信
    political_signals = []
    try:
        from grok_political import fetch_political_signals
        political_signals = fetch_political_signals(window_hours=24)
    except Exception as _e:
        print(f"[political_signals] skipped: {_e}")

    # 信息差引擎夜間簡報(法人/融資融券/借券/集保大戶/法說會/美股分析師+內部人) — 依代號查表,
    # intel/patrol.py 每晚 21:30 產出,latest.json 缺檔或格式異動一律回 {},缺了不缺信
    intel_signals = {}
    try:
        import json as _json
        import os as _os
        _intel_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "intel", "briefs", "latest.json")
        with open(_intel_path, encoding="utf-8") as _f:
            intel_signals = _json.load(_f).get("by_code") or {}
    except Exception as _e:
        print(f"[intel_signals] skipped: {_e}")

    return {
        "fundamentals": fundamentals,
        "us_market": us_market,
        "tw_market": tw_market,
        "technicals": technicals,
        "tw_names_all": tw_name_map(),
        "us_news": fetch_us_news(extra_us_stocks),
        "tw_news": fetch_tw_news(extra_tw_stocks),
        "indicators": fetch_indicators(),
        "crypto": fetch_crypto(),
        "sectors": fetch_sector_performance(),
        "earnings": fetch_earnings_calendar(),
        "earnings_impact": earnings_impact,
        "political_signals": political_signals,
        "intel_signals": intel_signals,
        # 必用 TW 時區：GH Actions runner 在 UTC，06:55 TW 寄送時 UTC 還是前一天
        # 2026-05-27 出包過：runner UTC 22:55 (= TW 5/27 06:55) datetime.now()→5/26
        # 害 _market_status() 拿 5/26 算「昨晚」變成 5/25 Memorial Day 假，日報通篇寫錯
        "date": the_date
    }
