"""Build /docs/data/track-record.json from digest HTML history.

Walks docs/output/digest_YYYY-MM-DD.html (non-personal),
extracts stock mentions across 3 formats:
  - .action-item   (verdict class: buy / hold / sell / wait)
  - .signal-card   (signal-bias: bullish / neutral / bearish)
  - .stock-card    (NLP keyword pass on comment text)

Each mention is classified A (direction) or C (risk-avoidance).
yfinance gives next-trading-day close → win / loss.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse
from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = ROOT / "docs" / "output"
OUT_DIR = ROOT / "docs" / "data"
OUT_FILE = OUT_DIR / "track-record.json"
CACHE_FILE = ROOT / "scripts" / ".price_cache.json"
# 匿名化逐筆帳本(修5):不進 docs/(不對外部署),只給機器自己稽核用
LEDGER_FILE = ROOT / "scripts" / "personal_ledger.jsonl"
LEDGER_AUDIT_FILE = ROOT / "scripts" / "personal_ledger_audit.json"

# When local digest files are missing (e.g., on CI runners), pull from CDN.
CDN_BASE = "https://marketdaily.ai/output"


# ── Keyword maps ──────────────────────────────────────────────────
BULL_KW = ("看漲", "建議買進", "可以買進", "繼續持有", "繼續抱", "抱緊", "適合新手",
           "穩健", "動能充足", "可以期待", "強勁", "突破", "偏多")

# 真正看空才算 C(stock-card 解析時必須命中至少 2 個關鍵字才採用,避免「觀望」
# 之類的中性偏謹慎詞被當成看空,造成 C 類勝率虛低)。
# 已移除 "拉回" "觀望" "保守" "別出手" — 這些屬於中性偏謹慎,不是看空。
BEAR_KW = ("停損", "獲利了結", "認賠出場", "建議賣出", "風險升高", "短期過熱",
           "減碼", "看跌", "偏空")

# ── TW ticker → 中文公司名 對照表 ────────────────────────────────
# 用於 signal-card / stock-card 解析時補上中文公司名(parse 出來只有 4 位數代碼時)
TW_NAMES: dict[str, str] = {
    # 半導體 / IC 設計
    "2330": "台積電", "2303": "聯電", "2454": "聯發科", "2379": "瑞昱",
    "3034": "聯詠", "2327": "國巨", "3037": "欣興", "3711": "日月光投控",
    "6669": "緯穎", "2474": "可成", "3008": "大立光", "3481": "群創",
    "2049": "上銀", "4938": "和碩", "2357": "華碩", "2353": "宏碁",
    # 電子代工 / 系統
    "2317": "鴻海", "2382": "廣達", "2308": "台達電",
    # 金融
    "2882": "國泰金", "2891": "中信金", "2884": "玉山金", "2885": "元大金",
    "2880": "華南金", "2886": "兆豐金", "2887": "台新金", "2890": "永豐金",
    "2892": "第一金", "2881": "富邦金", "2883": "凱基金", "2888": "新光金",
    "5871": "中租-KY", "2823": "中壽",
    # 航運 / 運輸
    "2603": "長榮", "2609": "陽明", "2615": "萬海", "2618": "長榮航",
    "2610": "華航", "2207": "和泰車",
    # 鋼鐵 / 塑化 / 原物料
    "2002": "中鋼", "1301": "台塑", "1303": "南亞", "1326": "台化",
    "6505": "台塑化", "1102": "亞泥", "1101": "台泥", "2105": "正新",
    "1402": "遠東新",
    # 食品 / 民生
    "1216": "統一", "2912": "統一超", "9904": "寶成", "9910": "豐泰",
    # 電信
    "2412": "中華電", "4904": "遠傳", "3045": "台灣大",
    # ETF
    "0050": "元大台灣50", "0056": "元大高股息", "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息", "00929": "復華台灣科技優息",
    "00940": "元大台灣價值高息", "00713": "元大台灣高息低波",
}


def _enrich_tw_name(name: str, ticker: str) -> str:
    """If ticker is a 4-digit TW code and name is empty, look up Chinese name."""
    if name:
        return name
    if re.fullmatch(r"\d{4}", ticker):
        return TW_NAMES.get(ticker, "")
    return name


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_name_ticker(span) -> tuple[str, str]:
    """For nested name/ticker spans found in action-item / signal-card / stock-card."""
    children = [c for c in span.find_all("span") if c.get_text(strip=True)]
    if len(children) >= 2:
        return _clean(children[0].get_text()), _clean(children[1].get_text())
    txt = _clean(span.get_text())
    # Pattern: "輝達 Nvidia NVDA" or just "NVDA"
    parts = txt.split()
    if len(parts) >= 2 and re.fullmatch(r"[A-Z0-9.]+", parts[-1]):
        return " ".join(parts[:-1]), parts[-1]
    return "", txt


def parse_digest_html(date_str: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    by_ticker: dict[str, dict] = {}  # ticker → record (latest priority wins)
    # Priority: action-board > signal-card > stock-card (higher value = keep)
    PRI = {"action-board": 3, "signal-card": 2, "stock-card": 1}

    def maybe_add(rec: dict) -> None:
        # ticker 必須是美股 [A-Z.] 或台股 4-6 位數字;中文公司名等非法 ticker
        # (解析只抓到單一中文 span 時會誤判)直接擋掉,否則會炸 Yahoo URL ascii 編碼
        t = rec["ticker"]
        if not re.fullmatch(r"[A-Z][A-Z.]*|\d{4,6}", t):
            return
        existing = by_ticker.get(t)
        if existing is None or PRI[rec["source"]] > PRI[existing["source"]]:
            by_ticker[t] = rec

    # ── action-item (cleanest) ──
    for item in soup.select(".action-item"):
        cls = item.get("class", [])
        verdict_class = next((c for c in cls if c in ("buy", "hold", "sell", "wait")), None)
        if not verdict_class:
            continue
        name_span = item.select_one(".action-name")
        verdict_span = item.select_one(".action-verdict")
        reason_div = item.select_one(".action-reason")
        if not (name_span and verdict_span and reason_div):
            continue
        name, ticker = _extract_name_ticker(name_span)
        if not ticker:
            continue
        name = _enrich_tw_name(name, ticker)
        rtype = "A" if verdict_class in ("buy", "hold") else "C"
        maybe_add({
            "date": date_str,
            "name": name,
            "ticker": ticker,
            "market": "tw" if re.fullmatch(r"\d{4,6}", ticker) else "us",
            "verdict_class": verdict_class,
            "verdict_text": _clean(verdict_span.get_text()),
            "reason": _clean(reason_div.get_text()),
            "type": rtype,
            "source": "action-board",
        })

    # ── signal-card (with bias label) ──
    for card in soup.select(".signal-card"):
        bias = card.select_one(".signal-bias")
        ticker_span = card.select_one(".signal-ticker")
        reason_div = card.select_one(".signal-reason")
        if not (bias and ticker_span and reason_div):
            continue
        b_cls = bias.get("class", [])
        if "bullish" in b_cls:
            verdict_class, rtype = "buy", "A"
        elif "bearish" in b_cls:
            verdict_class, rtype = "sell", "C"
        elif "neutral" in b_cls:
            verdict_class, rtype = "wait", "C"
        else:
            continue
        # 顯示層優先(2026-07-08 量尺修正):降級閘門只改卡片 class+chip 不動 signal-bias,
        # 兩者不一致時用戶看到的是 class/chip — 結算必須量用戶看到的判斷,bias 只當 fallback。
        vc_shown = next((cc for cc in (card.get("class") or [])
                         if cc in ("buy", "hold", "sell", "wait")), None)
        if vc_shown and vc_shown != verdict_class:
            verdict_class = vc_shown
            rtype = "A" if vc_shown in ("buy", "hold") else "C"
        name, ticker = _extract_name_ticker(ticker_span)
        # 台股卡經 _postprocess 後 signal-ticker 只剩中文名(不露代號),抓不到真代碼 →
        # 用 _mark_card 塞在卡尾的隱形 <!--h:代號--> 標記補回(美股 ticker 是字母不受影響)。
        if not re.fullmatch(r"[A-Za-z0-9.]{1,6}", ticker or ""):
            for c in card.find_all(string=lambda t: isinstance(t, Comment)):
                mm = re.match(r"\s*h:\s*([0-9A-Za-z.]+)\s*$", str(c))
                if mm:
                    if not name or name == ticker:
                        name = _clean(ticker_span.get_text())
                    ticker = mm.group(1)
                    break
        if not ticker:
            continue
        name = _enrich_tw_name(name, ticker)

        # 卡片宣稱的信心 %(供校準分析:說 70% 的那些實際對幾成 + Brier)
        confidence = None
        conf_span = card.select_one(".signal-confidence")
        if conf_span:
            cm = re.search(r"(\d{1,3})\s*%", conf_span.get_text())
            if cm:
                cval = int(cm.group(1))
                # 髒值防呆:\d{1,3} 最寬可配到 999,超出合理機率範圍的值不採信(避免單筆髒資料
                # 主宰整批 Brier——(9.99-0)²≈98 遠大於正常 (0~1) 範圍,見 lesson calibration_honesty_*)
                confidence = cval if 0 <= cval <= 100 else None

        # 卡片寫的進出場價位(供 level-based 操作模擬:照建議做會賺還是賠)
        levels: dict[str, float | None] = {"entry_lo": None, "entry_hi": None, "target": None, "stop": None}
        for row in card.select(".battle-row"):
            lbl = row.select_one(".battle-label")
            val = row.select_one(".battle-val")
            if not (lbl and val):
                continue
            nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", val.get_text())]
            if not nums:
                continue
            t = lbl.get_text()
            if "買價" in t or "回補" in t:
                levels["entry_lo"] = min(nums)
                levels["entry_hi"] = max(nums)
            elif "目標" in t:
                levels["target"] = nums[0]
            elif "止損" in t or "停損" in t:
                levels["stop"] = nums[0]

        # 持有者框架卡(2026-07-07 持倉客製化):<!--pos:SYM:ENTRY--> 標記=用戶已持有、自填成本。
        # verdict 直接讀卡片 class(buy=加碼/hold=續抱/sell=減碼停損/wait=閘門降級防守),
        # 獨立 type="H" → 不混入 A/C 頭條統計,用 judge_holder 持有者規則結算。
        holder_entry = None
        for c in card.find_all(string=lambda t: isinstance(t, Comment)):
            pm = re.match(r"\s*pos:\s*[0-9A-Za-z.]+\s*:\s*([\d.]+)\s*$", str(c))
            if pm:
                try:
                    holder_entry = float(pm.group(1))
                except ValueError:
                    holder_entry = None
                break
        if holder_entry:
            vc_div = next((cc for cc in (card.get("class") or []) if cc in ("buy", "hold", "sell", "wait")), None)
            if vc_div:
                verdict_class = vc_div
            rtype = "H"

        # 閘門反事實標記 <!--gated:原判斷:閘門名-->:這張卡被降級過 → 結算時雙軌
        # (顯示的觀望 + 被擋的原判斷,見 stats.gate_effect),自動驗證閘門擋對還是擋錯。
        gated_from = gate_name = None
        for c in card.find_all(string=lambda t: isinstance(t, Comment)):
            gm = re.match(r"\s*gated:(buy|hold|sell|wait):([a-z_]+)\s*$", str(c))
            if gm:
                gated_from, gate_name = gm.group(1), gm.group(2)
                break

        maybe_add({
            "date": date_str,
            "name": name,
            "ticker": ticker,
            "market": "tw" if re.fullmatch(r"\d{4,6}", ticker) else "us",
            "verdict_class": verdict_class,
            "verdict_text": _clean(bias.get_text()),
            "reason": _clean(reason_div.get_text()),
            "type": rtype,
            "source": "signal-card",
            "confidence": confidence,
            **({"holder": True, "holder_entry": holder_entry} if holder_entry else {}),
            **({"gated_from": gated_from, "gate": gate_name} if gated_from else {}),
            **levels,
        })

    # ── stock-card (keyword NLP) ──
    for card in soup.select(".stock-card"):
        ticker_span = card.select_one(".ticker")
        comment_div = card.select_one(".stock-comment")
        if not (ticker_span and comment_div):
            continue
        name, ticker = _extract_name_ticker(ticker_span)
        if not ticker or ticker == "無數據":
            continue
        name = _enrich_tw_name(name, ticker)
        comment = _clean(comment_div.get_text())
        bear_hits = sum(1 for kw in BEAR_KW if kw in comment)
        bull_hits = sum(1 for kw in BULL_KW if kw in comment)
        # stock-card 沒有明確 verdict,完全靠 NLP 推斷,門檻要嚴:
        # 看空必須命中 ≥2 個強看空詞才採用,避免單一個「停損」二字就被當看空
        # 看多只要命中 ≥1 個(看多詞本身就比較少誤判)
        if bear_hits >= 2 and bull_hits == 0:
            verdict_class, rtype = "wait", "C"
        elif bull_hits >= 1 and bear_hits == 0:
            verdict_class, rtype = "buy", "A"
        else:
            continue
        maybe_add({
            "date": date_str,
            "name": name,
            "ticker": ticker,
            "market": "tw" if re.fullmatch(r"\d{4,6}", ticker) else "us",
            "verdict_class": verdict_class,
            "verdict_text": "🟢 偏多" if rtype == "A" else "⚠️ 風險",
            "reason": comment,
            "type": rtype,
            "source": "stock-card",
        })

    return list(by_ticker.values())


def yf_symbol(t: str) -> str:
    t = t.strip().upper()
    if re.fullmatch(r"\d{4}", t):
        return f"{t}.TW"
    return t


def load_cache() -> dict[str, dict]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WORKER = "https://marketdaily-webhook.delvin-12345678.workers.dev"
# 內部 token 用來呼叫 /internal/list-digests 列舉某日所有個人化 digest tokens
# 透過 GitHub Actions secret 或本機環境變數注入,未設定就只跑公版日報(向後相容)
import os
INTERNAL_TOKEN = os.environ.get("MARKETDAILY_INTERNAL_TOKEN", "").strip()


def yahoo_chart(sym: str, _start_iso: str, _end_iso: str) -> dict[str, float] | None:
    """Route through Cloudflare Worker /stock-chart for stable Yahoo access.

    Worker accepts ticker (raw, no .TW suffix — worker handles TW autodetect)
    and range in {1D, 5D, 1M, 3M}. Returns {symbol, prevClose, price, points}.
    """
    # Strip .TW because worker auto-handles TW symbols when /^\d{4}$/
    base = sym.replace(".TW", "").replace(".TWO", "")
    url = f"{WORKER}/stock-chart?ticker={urllib.parse.quote(base)}&range=3M"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            points = data.get("points") or []
            out: dict[str, float] = {}
            for p in points:
                ts = p.get("t")
                c = p.get("c")
                if ts is None or c is None:
                    continue
                d = datetime.fromtimestamp(ts).date().isoformat()
                out[d] = float(c)
            return out or None
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(1.5 + attempt * 2)
    print(f"[warn] worker {sym}: {last_err}", file=sys.stderr)
    return None


def fetch_prices(keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    cache = load_cache()
    by_ticker: dict[str, list[str]] = {}
    for t, d in keys:
        by_ticker.setdefault(t, []).append(d)

    out: dict[tuple[str, str], dict] = {}
    for ticker, dates in by_ticker.items():
        sym = yf_symbol(ticker)
        cache_key = f"{sym}::history"
        hist_dict: dict[str, float] | None = cache.get(cache_key)
        # 快取新鮮度:歷史快取一旦存就永不更新,跨日後窗口會凍結。
        # 若快取最新日期沒晚於「最新一筆建議日」,該日就抓不到隔日收盤 → 永遠待結。
        # 偵測到不夠新就丟棄重抓(根治 5/22 等舊建議卡在待結)。
        if hist_dict:
            latest_cached = max(hist_dict.keys()) if hist_dict else ""
            # 須同時新於「最新建議日」與「昨天」:月/季結算(21/63 交易日)靠每日重抓
            # 逐步補齊,若日報停更數日,舊條件會讓快取凍結、長天期永遠待結。
            yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
            if latest_cached <= max(dates) or latest_cached < yesterday:
                hist_dict = None
        if hist_dict is None:
            start = (datetime.fromisoformat(min(dates)) - timedelta(days=5)).date()
            # end 至少涵蓋到今天:月結/季結(21/63 交易日)靠每日重跑逐步補齊,
            # 不能只抓到「最新建議日+10 天」——日報若停更,舊建議的長天期結算會凍結。
            end = max(
                (datetime.fromisoformat(max(dates)) + timedelta(days=10)).date(),
                (datetime.now() + timedelta(days=1)).date(),
            )
            hist_dict = yahoo_chart(sym, start.isoformat(), end.isoformat())
            if not hist_dict:
                print(f"[skip] no data for {sym}", file=sys.stderr)
                continue
            cache[cache_key] = hist_dict
            save_cache(cache)
            time.sleep(0.35)  # be polite to yahoo
        # Lookup per date
        sorted_dates = sorted(hist_dict.keys())
        for d in dates:
            today = hist_dict.get(d)
            if today is None:
                # next trading day on/after
                later = [dd for dd in sorted_dates if dd >= d]
                if not later:
                    continue
                today = hist_dict[later[0]]
                ref_idx = sorted_dates.index(later[0])
            else:
                ref_idx = sorted_dates.index(d)
            nxt = hist_dict[sorted_dates[ref_idx + 1]] if ref_idx + 1 < len(sorted_dates) else None
            c5 = hist_dict[sorted_dates[ref_idx + 5]] if ref_idx + 5 < len(sorted_dates) else None
            c21 = hist_dict[sorted_dates[ref_idx + 21]] if ref_idx + 21 < len(sorted_dates) else None
            c63 = hist_dict[sorted_dates[ref_idx + 63]] if ref_idx + 63 < len(sorted_dates) else None
            path = [hist_dict[dd] for dd in sorted_dates[ref_idx + 1:ref_idx + 14]]
            out[(ticker, d)] = {"close": today, "next_close": nxt, "close_5d": c5,
                                "close_21d": c21, "close_63d": c63, "path": path}
    return out


# 現行模型世代起點:2026-06-11 部署「結構 prior 鎖方向 + 信心由 track-record 校準表覆寫」,
# 6/12 起的日報才是新制輸出(之前 = LLM 自填信心舊世代,實測為反指標)
MODEL_ERA_START = "2026-06-12"


def day_cluster_ci(recs: list[dict], nboot: int = 2000) -> list[float] | None:
    """按「日期」cluster bootstrap 的勝率 95% CI。
    同日記錄吃同一段市場走勢,高度相關;Wilson 假設獨立會給假窄 CI(有效樣本≈天數,非筆數)。"""
    by_day: dict[str, list[int]] = {}
    for r in recs:
        by_day.setdefault(r["date"], []).append(1 if r["outcome"] == "win" else 0)
    days = list(by_day)
    if len(days) < 2:
        return None
    import random
    rng = random.Random(7)
    rates = []
    for _ in range(nboot):
        vals: list[int] = []
        for _ in days:
            vals.extend(by_day[rng.choice(days)])
        if vals:
            rates.append(sum(vals) / len(vals) * 100)
    rates.sort()
    return [round(rates[int(0.025 * len(rates))], 1), round(rates[int(0.975 * len(rates))], 1)]


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """勝率的 Wilson 95% 信賴區間(%):小樣本紀律 — 只報點估計會把運氣當實力。
    N ≈ 1/edge²:5% 的 edge 要數百筆才能跟運氣區分,別用 20 筆下結論。"""
    if n == 0:
        return (0.0, 0.0)
    ph = wins / n
    den = 1 + z * z / n
    center = (ph + z * z / (2 * n)) / den
    half = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (round((center - half) * 100, 1), round((center + half) * 100, 1))


def calibration_stats(recs: list[dict]) -> dict | None:
    """信心校準:卡片說「信心 X%」的那些,實際對幾成?
    Brier = (1/N)·Σ(f−o)² — 0.25 = 丟銅板,< 0.25 才有預測力。
    這是日報信心數字該不該被相信的唯一證據,每天自動累積。"""
    pts = [(r["confidence"] / 100, 1 if r["outcome"] == "win" else 0)
           for r in recs
           if r.get("confidence") and r.get("outcome") in ("win", "loss")]
    if not pts:
        return None
    brier = sum((f - o) ** 2 for f, o in pts) / len(pts)
    bins: dict[str, list[int]] = {}
    for f, o in pts:
        b = "<=50" if f <= 0.50 else "51-60" if f <= 0.60 else "61-70" if f <= 0.70 else ">70"
        bins.setdefault(b, []).append(o)
    return {
        "n": len(pts),
        "brier": round(brier, 4),
        "coin_flip_brier": 0.25,
        "bins": {b: {"n": len(v), "hit_rate": round(sum(v) / len(v) * 100, 1)}
                 for b, v in sorted(bins.items())},
    }


def simulate_plan(rec: dict, prices: dict) -> dict | None:
    """level-based 操作模擬:不只問「方向對嗎」,問「照卡片寫的買價/目標/停損操作,結果如何」。
    規則:建議日後 3 個交易日內收盤進入買區(≤ entry_hi)= 進場(以該日收盤為成本);
    之後 10 個交易日內收盤先碰目標 = win、先碰停損 = loss;都沒碰 → 期滿以收盤對成本結算。
    限制:只有日收盤、無盤中高低 — 目標與停損都會低估觸發,偏差雙向,結果偏保守但公平。"""
    if rec.get("verdict_class") != "buy":
        return None
    hi, tgt, stp = rec.get("entry_hi"), rec.get("target"), rec.get("stop")
    if not (hi and tgt and stp):
        return None
    p = prices.get((rec["ticker"], rec["date"]))
    path = (p or {}).get("path") or []
    if not path:
        return None
    entry = None
    entry_i = -1
    for i, c in enumerate(path[:3]):
        if c <= hi:
            entry, entry_i = c, i
            break
    if entry is None:
        # 3 天內價格沒回到買區 → 單子沒成交(這不算錯,但要統計「建議常常掛不到」)
        return {"result": "no_fill", "ret_pct": None}
    rest = path[entry_i + 1:entry_i + 11]
    for c in rest:
        if c >= tgt:
            return {"result": "win", "ret_pct": round((c - entry) / entry * 100, 2)}
        if c <= stp:
            return {"result": "loss", "ret_pct": round((c - entry) / entry * 100, 2)}
    if len(rest) < 10:
        return {"result": "pending", "ret_pct": None}
    return {"result": "expired", "ret_pct": round((rest[-1] - entry) / entry * 100, 2)}


def fetch_spx_regime() -> dict[str, str]:
    """日期 → 大盤趨勢標記(SPX 收盤 vs 5 個交易日前:up/down)。
    用來把勝率按 regime 拆開 — 驗證「下跌 regime 整批喊買 = 主要虧損源」假設,
    並追蹤 2026-06-10 上線的 regime 閘門有沒有真的把 down-regime 勝率拉起來。"""
    closes = yahoo_chart("^GSPC", "", "")
    if not closes:
        return {}
    ds = sorted(closes)
    out = {}
    for i, d in enumerate(ds):
        if i >= 5:
            out[d] = "down" if closes[d] < closes[ds[i - 5]] else "up"
    return out


# 各結算天期設定:ref=價格欄位,hold=「抱住沒事」下方緩衝,wait=「別進場」容許小漲門檻。
# 月/季緩衝按 sqrt(時間) 放大(股價波動 ~ sqrt(t)):hold 3%×√(21/5)≈6%、3%×√(63/5)≈10%;
# wait 2%×√(21/5)≈4%、2%×√(63/5)≈7%。
_HORIZONS = {
    "1d":  {"ref": "next_close", "hold": 0.02, "wait": 0.01},
    "5d":  {"ref": "close_5d",   "hold": 0.03, "wait": 0.02},
    "21d": {"ref": "close_21d",  "hold": 0.06, "wait": 0.04},
    "63d": {"ref": "close_63d",  "hold": 0.10, "wait": 0.07},
}


def judge(rec: dict, prices: dict, horizon: str = "5d") -> str | None:
    """結算一筆建議。
    horizon="5d"(主指標/週結):建議日收盤 vs 5 個交易日後收盤 — 對齊卡片明寫的「短線 1-2 週視角」。
      2026-06-10 修正:原本只看隔日一天,拿單日雜訊評 1-2 週的建議 = 量尺錯位,
      量到的是「隔日漲跌擲銅板」不是建議品質。
    horizon="21d"/"63d"(月結/季結,2026-07-07 起):同一批判斷分別在 ~1 個月/~1 季後結算。
    horizon="1d"(輔助參考):隔日收盤,保留供對照。"""
    p = prices.get((rec["ticker"], rec["date"]))
    if not p:
        return None
    cfg = _HORIZONS[horizon]
    today = p["close"]
    ref = p.get(cfg["ref"])
    if ref is None:
        return None  # 尚未到結算日 → 待結
    chg = (ref - today) / today
    vc = rec["verdict_class"]
    if vc == "buy":
        return "win" if chg > 0 else "loss"
    if vc == "hold":
        # 2026-07-09 修正:「續抱」對讀者是不對稱的——照建議續抱後上漲是好結果,
        # 只有跌破下方緩衝才是建議錯(與 judge_holder 同規則)。舊版 ±3% 對稱緩衝
        # 把「續抱後大漲」也記輸,量的是「預測股價不動」不是建議品質
        # (實測 hold 桶 up/down regime 同時 ~20%,對稱地低=緩衝問題非方向問題)。
        return "win" if chg >= -cfg["hold"] else "loss"
    if vc == "sell":
        # sell 是強信號,必須真跌才算對
        return "win" if chg < 0 else "loss"
    if vc == "wait":
        # wait 是「中性偏空 / 暫時別進場」— 緩衝後小漲不算錯
        return "win" if chg < cfg["wait"] else "loss"
    return None


def judge_holder(rec: dict, prices: dict, horizon: str = "5d") -> str | None:
    """持有者框架結算(type="H",2026-07-07 持倉客製化):建議對象是「已持有」的用戶,
    量的是「聽這個建議 vs 出場,持有期間有沒有守住」:
      buy(加碼)   → 漲才算對(跟方向判斷同標準)
      hold(續抱)/wait(閘門降級的防守) → 沒有跌破緩衝就算對(續抱時大漲是好事,不對稱懲罰)
      sell(減碼/停損/獲利了結) → 之後真的跌=提前出場是對的"""
    p = prices.get((rec["ticker"], rec["date"]))
    if not p:
        return None
    cfg = _HORIZONS[horizon]
    ref = p.get(cfg["ref"])
    if ref is None:
        return None  # 尚未到結算日 → 待結
    chg = (ref - p["close"]) / p["close"]
    vc = rec["verdict_class"]
    if vc == "buy":
        return "win" if chg > 0 else "loss"
    if vc in ("hold", "wait"):
        return "win" if chg >= -cfg["hold"] else "loss"
    if vc == "sell":
        return "win" if chg < 0 else "loss"
    return None


def fetch_digest_html(date_str: str) -> str | None:
    """Try local file first; fall back to CDN."""
    local = DIGEST_DIR / f"digest_{date_str}.html"
    if local.exists():
        return local.read_text(encoding="utf-8", errors="ignore")
    # Cloudflare Pages 會把 .html 用 308 轉到無副檔名路徑;部分環境的 urllib
    # 不跟 308,故兩個 URL 都試,任一抓到非空 HTML 就用。
    for url in (f"{CDN_BASE}/digest_{date_str}.html", f"{CDN_BASE}/digest_{date_str}"):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            if html.strip():
                return html
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"[warn] cdn {url}: {exc}", file=sys.stderr)
    return None


_DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})\.html$")


def discover_dates() -> list[str]:
    """Discover digest dates from ACTUAL files on disk (source of truth),
    unioned with manifest + CDN manifest. 不單信 manifest.json —— 它會漂移
    (daily job 寫了 manifest 但沒 commit 回 origin → builder 看不到新日期,
    戰績頁因此凍結。改成以實體檔為準,manifest 只作補充。"""
    dates: set[str] = set()

    # 1) 實體檔案(最可靠):docs/output/digest_YYYY-MM-DD.html(排除 *_personal_*)
    for p in DIGEST_DIR.glob("digest_*.html"):
        if "_personal_" in p.name:
            continue
        m = _DATE_RE.search(p.name)
        if m:
            dates.add(m.group(1))

    # 2) 本機 manifest 補充
    manifest_local = DIGEST_DIR / "manifest.json"
    if manifest_local.exists():
        try:
            dates.update(json.loads(manifest_local.read_text()).get("dates", []))
        except Exception:
            pass

    # 3) 沒掃到任何實體檔時(乾淨 CI checkout 等)退回 CDN manifest
    if not dates:
        url = f"{CDN_BASE}/manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                dates.update(json.loads(resp.read().decode("utf-8")).get("dates", []))
        except Exception as exc:
            print(f"[warn] cdn manifest: {exc}", file=sys.stderr)

    return sorted(dates, reverse=True)


def list_personal_digest_tokens(date_str: str) -> list[str]:
    """呼叫 Worker /internal/list-digests 列舉某日所有個人化 digest tokens。
    沒設 INTERNAL_TOKEN 就回空清單(向後相容,只跑公版)。"""
    if not INTERNAL_TOKEN:
        return []
    url = f"{WORKER}/internal/list-digests?date={date_str}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("tokens") or []
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"[warn] list-digests {date_str}: {exc}", file=sys.stderr)
        return []


def fetch_personal_digest_html(token: str) -> str | None:
    """透過 Worker public /digest/{token} 取個人化日報 HTML。"""
    url = f"{WORKER}/digest/{token}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[warn] personal digest {token[:8]}: {exc}", file=sys.stderr)
        return None


def _personal_ledger_entries(judged_personal: list[dict], personal_sims: dict[int, dict],
                              regime_by_date: dict[str, str]) -> list[dict]:
    """匿名化個人化建議→帳本欄位(修5)。只留 user token 的雜湊,不留 token/姓名/持股原文
    ——夠讓 edge_audit 稽核方向/信心/期望值,不夠反推是哪個人。"""
    entries = []
    for r in judged_personal:
        outcome = r.get("outcome")
        if outcome not in ("win", "loss"):
            continue
        tok = r.get("_user_token") or ""
        user_hash = hashlib.sha256(tok.encode()).hexdigest()[:12] if tok else "unknown"
        sim = personal_sims.get(id(r))
        entries.append({
            "date": r["date"],
            "ticker": r["ticker"],
            "market": r.get("market"),
            "type": r.get("type"),
            "verdict_class": r.get("verdict_class"),
            "label": outcome,
            "prob": round(r["confidence"] / 100, 4) if r.get("confidence") else None,
            "regime": regime_by_date.get(r["date"]),
            "ret": sim["ret_pct"] if sim else None,
            "user_hash": user_hash,
            # 持有者框架(type="H")補記自填成本,供未來 per-position 稽核
            **({"holder_entry": r["holder_entry"]} if r.get("holder_entry") else {}),
        })
    return entries


def append_personal_ledger(entries: list[dict]) -> int:
    """append-only、跨日重跑 idempotent(同 date+ticker+type+verdict+user_hash 不重複寫入,
    因為 build_track_record 每次都重新走訪全部歷史日期)。"""
    existing_keys: set[tuple] = set()
    if LEDGER_FILE.exists():
        for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing_keys.add((e.get("date"), e.get("ticker"), e.get("type"),
                               e.get("verdict_class"), e.get("user_hash")))
    new_lines = []
    for e in entries:
        key = (e["date"], e["ticker"], e["type"], e["verdict_class"], e["user_hash"])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_lines.append(json.dumps(e, ensure_ascii=False))
    if new_lines:
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
    return len(new_lines)


def run_ledger_edge_audit() -> None:
    """對匿名帳本跑通用 edge_audit 稽核器,結果寫檔供 ~/autonomous/kpi_pull.py 讀進 kpi.md
    (修5 解鎖驗收:沒有這個就不知道未來的信心/regime/幾何修法有沒有讓 edge 變正)。
    best-effort:非 winrig 環境(沒有 ~/autonomous)就安靜跳過,不影響 track-record 主流程。"""
    if not LEDGER_FILE.exists():
        return
    audit_dir = Path.home() / "autonomous" / "capabilities" / "edge_audit"
    if not (audit_dir / "audit.py").exists():
        return
    try:
        sys.path.insert(0, str(audit_dir))
        import audit as edge_audit  # type: ignore

        records = [json.loads(l) for l in LEDGER_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        out = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_total": len(records),
            "a": edge_audit.audit_records([r for r in records if r.get("type") == "A"], group_by="market"),
            "c": edge_audit.audit_records([r for r in records if r.get("type") == "C"], group_by="market"),
        }
        LEDGER_AUDIT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ledger-audit] n={len(records)} -> {LEDGER_AUDIT_FILE}")
    except Exception as exc:
        print(f"[warn] ledger edge_audit failed: {exc}", file=sys.stderr)


def main() -> int:
    # 2026-07-07 Delvin 指令:舊世代引擎(結構 prior+校準信心上線前)的預測不是現行系統產的,
    # 混進公開頭條勝率=不真實 → 公開戰績只計 MODEL_ERA_START 起的記錄,全程用現行規則重算。
    # 舊記錄不銷毀:匿名帳本 personal_ledger.jsonl(append-only,不對外)保留全史供內部稽核。
    dates = [d for d in discover_dates() if d >= MODEL_ERA_START]
    if not dates:
        print("no digest dates discoverable from local or CDN", file=sys.stderr)
        return 1
    print(f"[discover] {len(dates)} dates to process (>= {MODEL_ERA_START})")

    all_records: list[dict] = []
    personal_records: list[dict] = []  # 跨用戶聚合用,不寫進公開 records 列表
    for date_str in dates:
        html = fetch_digest_html(date_str)
        if not html:
            print(f"[skip] digest_{date_str}.html: unreachable")
            continue
        recs = parse_digest_html(date_str, html)
        all_records.extend(recs)
        print(f"[parse] digest_{date_str}.html: {len(recs)} records")

        # 跨用戶:列舉當日所有個人化 digest tokens,parse 後僅算進 stats
        # 隱私策略:不洩漏個別用戶持股,records 列表只保留公版
        if INTERNAL_TOKEN:
            tokens = list_personal_digest_tokens(date_str)
            if tokens:
                # 去重避免同一個人化 digest 多次計算 — 用 (date, ticker, verdict, 持有者框架) 四元組
                # (持有者框架 H 卡與一般卡語意不同,不可被同 verdict 的公版卡吃掉)
                seen_keys = {(r["date"], r["ticker"], r["verdict_class"], r.get("type") == "H") for r in recs}
                added = 0
                for tok in tokens:
                    p_html = fetch_personal_digest_html(tok)
                    if not p_html:
                        continue
                    p_recs = parse_digest_html(date_str, p_html)
                    for pr in p_recs:
                        key = (pr["date"], pr["ticker"], pr["verdict_class"], pr.get("type") == "H")
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        pr["source_scope"] = "personal"  # 標記不寫入公開 records
                        pr["_user_token"] = tok  # 內部欄位:只供匿名帳本雜湊,絕不寫入任何輸出檔
                        personal_records.append(pr)
                        added += 1
                    time.sleep(0.1)  # 對 worker 客氣點
                print(f"  + personal: {len(tokens)} tokens → {added} new (ticker,verdict) added to stats only")

    # 公版 + 個人化合在一起算 price + judge
    combined = all_records + personal_records
    keys = {(r["ticker"], r["date"]) for r in combined}
    print(f"[fetch] {len(keys)} (ticker,date) pairs via yfinance (cached where possible)...")
    prices = fetch_prices(keys)

    def _judge_record(r: dict) -> None:
        # type="H"(持有者框架)用 judge_holder,其餘照舊
        jfn = judge_holder if r.get("type") == "H" else judge
        r["outcome"] = jfn(r, prices, "5d")
        r["outcome_1d"] = jfn(r, prices, "1d")
        r["outcome_21d"] = jfn(r, prices, "21d")
        r["outcome_63d"] = jfn(r, prices, "63d")

    judged_public = []
    for r in all_records:
        _judge_record(r)
        judged_public.append(r)
    judged_personal = []
    for r in personal_records:
        _judge_record(r)
        judged_personal.append(r)

    # 個人化逐筆模擬報酬(供匿名帳本用;獨立於下面 judged_all 的聚合 sims 迴圈,不影響既有 plan_sim 統計)
    personal_sims: dict[int, dict] = {}
    for r in judged_personal:
        if r.get("type") == "H":
            continue  # 持有者卡價位是減碼/停損位,照卡片進場模擬會失真(同下方頭條 sims 迴圈)
        s = simulate_plan(r, prices)
        if s:
            personal_sims[id(r)] = s

    # records 列表只放公版(隱私策略 A),personal 只進 stats
    judged_public.sort(key=lambda x: (x["date"], x["ticker"]), reverse=True)
    judged_all = judged_public + judged_personal  # stats 用

    a_recs = [r for r in judged_all if r["type"] == "A" and r["outcome"]]
    c_recs = [r for r in judged_all if r["type"] == "C" and r["outcome"]]
    a_wins = sum(1 for r in a_recs if r["outcome"] == "win")
    c_wins = sum(1 for r in c_recs if r["outcome"] == "win")
    a_rate = (a_wins / len(a_recs) * 100) if a_recs else 0.0
    c_rate = (c_wins / len(c_recs) * 100) if c_recs else 0.0

    # 公版單獨統計(供對比)
    a_pub = [r for r in judged_public if r["type"] == "A" and r["outcome"]]
    c_pub = [r for r in judged_public if r["type"] == "C" and r["outcome"]]
    a_pub_wins = sum(1 for r in a_pub if r["outcome"] == "win")
    c_pub_wins = sum(1 for r in c_pub if r["outcome"] == "win")

    # 1 日視角輔助統計(對照用)
    a1 = [r for r in judged_all if r["type"] == "A" and r.get("outcome_1d")]
    c1 = [r for r in judged_all if r["type"] == "C" and r.get("outcome_1d")]
    a1_wins = sum(1 for r in a1 if r["outcome_1d"] == "win")
    c1_wins = sum(1 for r in c1 if r["outcome_1d"] == "win")

    # 月結(21 交易日)/季結(63 交易日)勝率:同一批判斷換更長的結算尺,pending=尚未到期
    def horizon_block(field: str) -> dict:
        a_all = [r for r in judged_all if r["type"] == "A"]
        c_all = [r for r in judged_all if r["type"] == "C"]
        a = [r for r in a_all if r.get(field) in ("win", "loss")]
        c = [r for r in c_all if r.get(field) in ("win", "loss")]
        aw = sum(1 for r in a if r[field] == "win")
        cw = sum(1 for r in c if r[field] == "win")
        return {
            "a_count": len(a), "a_wins": aw,
            "a_rate": round(aw / len(a) * 100, 1) if a else 0.0,
            "a_ci95": list(wilson_ci(aw, len(a))),
            "a_pending": len(a_all) - len(a),
            "c_count": len(c), "c_wins": cw,
            "c_rate": round(cw / len(c) * 100, 1) if c else 0.0,
            "c_ci95": list(wilson_ci(cw, len(c))),
            "c_pending": len(c_all) - len(c),
        }

    monthly = horizon_block("outcome_21d")
    quarterly = horizon_block("outcome_63d")

    # 持有者框架(type="H")獨立統計:樣本先累積,不混入 A/C 頭條(同 07-07 era 切分的誠實原則)
    h_all = [r for r in judged_all if r.get("type") == "H"]
    h_recs = [r for r in h_all if r.get("outcome") in ("win", "loss")]
    h_wins = sum(1 for r in h_recs if r["outcome"] == "win")
    holder_stats = {
        "note": "持有者框架建議(用戶自填進場成本):judge_holder 獨立結算,不計入 A/C 頭條",
        "count": len(h_recs), "wins": h_wins,
        "rate": round(h_wins / len(h_recs) * 100, 1) if h_recs else 0.0,
        "ci95": list(wilson_ci(h_wins, len(h_recs))),
        "pending": len(h_all) - len(h_recs),
    }

    # ── 校準 / regime 拆解 / level-based 操作模擬(2026-06-10 自學三件套)──
    calib = calibration_stats(a_recs)

    regime_by_date = fetch_spx_regime()
    by_regime = {}
    for trend in ("up", "down"):
        sub = [r for r in a_recs if regime_by_date.get(r["date"]) == trend]
        w = sum(1 for r in sub if r["outcome"] == "win")
        lo, hi_ci = wilson_ci(w, len(sub))
        by_regime[trend] = {"a_count": len(sub), "a_wins": w,
                            "a_rate": round(w / len(sub) * 100, 1) if sub else 0.0,
                            "ci95": [lo, hi_ci]}

    # ── 世代切分(2026-07-03 回測診斷修復)──
    # 6/11 上線「結構 prior 鎖方向 + 信心由校準表覆寫」= 新模型;之前的記錄是 LLM 自填信心的舊世代
    # (實測舊世代信心>70 的 988 筆只中 34.5% = 反指標)。混算會讓舊毒回饋進今日信心
    # (_calibrated_confidence 讀 by_regime 反推),新模型永遠洗不乾淨 → 校準/regime 桶必須只吃新世代。
    # 另:同日記錄高度相關(每天 ~50 筆同一市況),Wilson CI 假獨立會假窄 → 補日 cluster bootstrap CI。
    era_a = [r for r in a_recs if r["date"] >= MODEL_ERA_START]
    era_c = [r for r in c_recs if r["date"] >= MODEL_ERA_START]
    era_a_wins = sum(1 for r in era_a if r["outcome"] == "win")
    era_c_wins = sum(1 for r in era_c if r["outcome"] == "win")
    era_by_regime = {}
    for trend in ("up", "down"):
        sub = [r for r in era_a if regime_by_date.get(r["date"]) == trend]
        w = sum(1 for r in sub if r["outcome"] == "win")
        era_by_regime[trend] = {"a_count": len(sub), "a_wins": w,
                                "a_rate": round(w / len(sub) * 100, 1) if sub else 0.0,
                                "a_ci95": list(wilson_ci(w, len(sub)))}
    # verdict×regime 細桶:analyzer._pp_bucket_autogate 的資料源(2026-07-08)——
    # 任一桶勝率持續失準,隔天日報該類 buy/sell 卡自動降級觀望,稽核→改規則不再等人工。
    era_by_verdict_regime = {}
    for vc in ("buy", "hold", "sell", "wait"):
        for trend in ("up", "down"):
            sub = [r for r in era_a + era_c
                   if r["verdict_class"] == vc and regime_by_date.get(r["date"]) == trend]
            w = sum(1 for r in sub if r["outcome"] == "win")
            n = len(sub)
            # 誠實閘門(2026-07-09,同 era_by_regime):n<15 是 `_pp_bucket_autogate` 本身
            # 認定「小樣本雜訊」的門檻(analyzer.py 該函式對此桶 n<15 直接跳過不動作)——
            # 這裡的 rate 欄位只供人工查閱/公開 JSON,對齊同一條線,不對外印出未達門檻的假精確%。
            era_by_verdict_regime[f"{vc}|{trend}"] = {
                "count": n, "wins": w,
                "rate": round(w / n * 100, 1) if n >= 15 else None,
                "status": "insufficient_data" if n < 15 else None}
    era = {
        "note": f"僅計 {MODEL_ERA_START} 起(結構prior+校準信心上線後)的現行模型;"
                "信心反推(_calibrated_confidence)應以此為準,避免舊世代反指標數據汙染",
        "since": MODEL_ERA_START,
        "a_count": len(era_a), "a_wins": era_a_wins,
        "a_rate": round(era_a_wins / len(era_a) * 100, 1) if era_a else 0.0,
        "a_ci95_day_cluster": day_cluster_ci(era_a),
        "c_count": len(era_c), "c_wins": era_c_wins,
        "c_rate": round(era_c_wins / len(era_c) * 100, 1) if era_c else 0.0,
        "c_ci95_day_cluster": day_cluster_ci(era_c),
        "by_regime": era_by_regime,
        "by_verdict_regime": era_by_verdict_regime,
        "calibration": calibration_stats(era_a),
        "days": len({r["date"] for r in era_a + era_c}),
    }

    sims = []
    for r in judged_all:
        if r.get("type") == "H":
            continue  # 持有者卡的價位是減碼/停損位,混進「照卡片進場」模擬會失真
        s = simulate_plan(r, prices)
        if s:
            sims.append(s)
    sim_win = [s for s in sims if s["result"] == "win"]
    sim_loss = [s for s in sims if s["result"] == "loss"]
    sim_exp = [s for s in sims if s["result"] == "expired"]
    closed = sim_win + sim_loss + sim_exp
    rets = [s["ret_pct"] for s in closed if s.get("ret_pct") is not None]
    plan_sim = {
        "note": "照卡片買價/目標/停損操作的模擬(僅日收盤近似,無盤中價,觸發偏保守)",
        "simulated": len(sims),
        "no_fill": sum(1 for s in sims if s["result"] == "no_fill"),
        "pending": sum(1 for s in sims if s["result"] == "pending"),
        "hit_target": len(sim_win),
        "hit_stop": len(sim_loss),
        "expired": len(sim_exp),
        "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "expectancy_note": "勝率≠獲利,avg_ret_pct(每筆平均報酬)才是期望值",
    }

    # 匿名化逐筆帳本(修5):只有個人化 token 資料時才有內容;沒 INTERNAL_TOKEN 時 personal_records
    # 為空,entries 也是空,append/audit 都是安全 no-op。
    # 閘門反事實結算(2026-07-08):被降級的卡雙軌結算——顯示判斷 vs 被擋的原判斷。
    # shown_rate > blocked_rate = 閘門擋對(降級後更準);反之該閘門要檢討。
    gate_counts: dict[str, dict] = {}
    for r in judged_all:
        gf = r.get("gated_from")
        if not gf or r.get("outcome") not in ("win", "loss"):
            continue
        cf = judge({**r, "verdict_class": gf}, prices, "5d")
        if cf not in ("win", "loss"):
            continue
        g = gate_counts.setdefault(r.get("gate") or "unknown",
                                   {"n": 0, "shown_wins": 0, "blocked_wins": 0})
        g["n"] += 1
        g["shown_wins"] += 1 if r["outcome"] == "win" else 0
        g["blocked_wins"] += 1 if cf == "win" else 0
    for g in gate_counts.values():
        g["shown_rate"] = round(g["shown_wins"] / g["n"] * 100, 1)
        g["blocked_rate"] = round(g["blocked_wins"] / g["n"] * 100, 1)
    gate_effect = {
        "note": "降級卡雙軌結算:shown=降級後顯示判斷勝率,blocked=若沒降級原判斷勝率;shown>blocked=閘門擋對",
        "gates": gate_counts,
    }

    ledger_entries = _personal_ledger_entries(judged_personal, personal_sims, regime_by_date)
    ledger_added = append_personal_ledger(ledger_entries)
    if ledger_added:
        print(f"[ledger] +{ledger_added} new personal ledger rows (candidates={len(ledger_entries)})")
    run_ledger_edge_audit()

    stats = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "horizon": "5d",
        "records_since": MODEL_ERA_START,
        "days_covered": len({r["date"] for r in judged_all}),
        "total_records": len(judged_all),
        "judged_records": len(a_recs) + len(c_recs),
        "one_day": {
            "a_count": len(a1), "a_wins": a1_wins,
            "a_rate": round(a1_wins / len(a1) * 100, 1) if a1 else 0.0,
            "c_count": len(c1), "c_wins": c1_wins,
            "c_rate": round(c1_wins / len(c1) * 100, 1) if c1 else 0.0,
        },
        "monthly": monthly,      # 21 個交易日 ≈ 一個月結算
        "quarterly": quarterly,  # 63 個交易日 ≈ 一季結算
        "holder": holder_stats,  # 持有者框架(持倉客製化)獨立統計
        "a_count": len(a_recs),
        "a_wins": a_wins,
        "a_rate": round(a_rate, 1),
        "a_ci95": list(wilson_ci(a_wins, len(a_recs))),
        "c_count": len(c_recs),
        "c_wins": c_wins,
        "c_rate": round(c_rate, 1),
        "c_ci95": list(wilson_ci(c_wins, len(c_recs))),
        "calibration": calib,
        "by_regime": by_regime,
        "era": era,
        "plan_sim": plan_sim,
        "gate_effect": gate_effect,
        # 區分公版 / 個人化來源,讓前端可看到是否包含跨用戶聚合
        "public_only": {
            "a_count": len(a_pub),
            "a_wins": a_pub_wins,
            "a_rate": round(a_pub_wins / len(a_pub) * 100, 1) if a_pub else 0.0,
            "c_count": len(c_pub),
            "c_wins": c_pub_wins,
            "c_rate": round(c_pub_wins / len(c_pub) * 100, 1) if c_pub else 0.0,
        },
        "personal_samples_added": len(judged_personal),
    }
    # 防呆:刷新拿到 0 筆通常是 CDN 抓取失敗,不是真的沒戰績。
    # 若既有檔案已有資料,拒絕用空結果覆蓋,改報錯讓排程 fail 不靜默歸零。
    if stats["total_records"] == 0 and OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))["stats"]["total_records"]
        except Exception:
            prev = 0
        if prev > 0:
            print(
                f"[abort] parsed 0 records but existing file has {prev} — "
                f"likely a fetch failure, refusing to overwrite.",
                file=sys.stderr,
            )
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps({"stats": stats, "records": judged_public}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pub = stats["public_only"]
    print(
        f"[write] {OUT_FILE}\n"
        f"  total={stats['total_records']} judged={stats['judged_records']} "
        f"(public={len(judged_public)} personal_added={stats['personal_samples_added']})\n"
        f"  A (all):    {a_wins}/{stats['a_count']} = {stats['a_rate']}%\n"
        f"  A (public): {pub['a_wins']}/{pub['a_count']} = {pub['a_rate']}%\n"
        f"  C (all):    {c_wins}/{stats['c_count']} = {stats['c_rate']}%\n"
        f"  C (public): {pub['c_wins']}/{pub['c_count']} = {pub['c_rate']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
