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
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import urllib.request
import urllib.error
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = ROOT / "docs" / "output"
OUT_DIR = ROOT / "docs" / "data"
OUT_FILE = OUT_DIR / "track-record.json"
CACHE_FILE = ROOT / "scripts" / ".price_cache.json"

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
        existing = by_ticker.get(rec["ticker"])
        if existing is None or PRI[rec["source"]] > PRI[existing["source"]]:
            by_ticker[rec["ticker"]] = rec

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
        name, ticker = _extract_name_ticker(ticker_span)
        if not ticker:
            continue
        name = _enrich_tw_name(name, ticker)
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
    url = f"{WORKER}/stock-chart?ticker={base}&range=1M"
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
        if hist_dict is None:
            start = (datetime.fromisoformat(min(dates)) - timedelta(days=5)).date()
            end = (datetime.fromisoformat(max(dates)) + timedelta(days=10)).date()
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
            out[(ticker, d)] = {"close": today, "next_close": nxt}
    return out


def judge(rec: dict, prices: dict) -> str | None:
    p = prices.get((rec["ticker"], rec["date"]))
    if not p or p.get("next_close") is None:
        return None
    today, nxt = p["close"], p["next_close"]
    chg = (nxt - today) / today
    vc = rec["verdict_class"]
    if vc == "buy":
        return "win" if chg >= 0 else "loss"
    if vc == "hold":
        return "win" if abs(chg) <= 0.02 else "loss"
    if vc == "sell":
        # sell 是強信號,必須真跌才算對
        return "win" if chg < 0 else "loss"
    if vc == "wait":
        # wait 是「中性偏空 / 暫時別進場」— 加 1% 緩衝,小漲不算錯
        return "win" if chg < 0.01 else "loss"
    return None


def fetch_digest_html(date_str: str) -> str | None:
    """Try local file first; fall back to CDN."""
    local = DIGEST_DIR / f"digest_{date_str}.html"
    if local.exists():
        return local.read_text(encoding="utf-8", errors="ignore")
    url = f"{CDN_BASE}/digest_{date_str}.html"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[warn] cdn {date_str}: {exc}", file=sys.stderr)
        return None


def discover_dates() -> list[str]:
    """Get list of digest dates: local manifest first, then CDN manifest."""
    manifest_local = DIGEST_DIR / "manifest.json"
    if manifest_local.exists():
        try:
            return json.loads(manifest_local.read_text())["dates"]
        except Exception:
            pass
    url = f"{CDN_BASE}/manifest.json"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))["dates"]
    except Exception as exc:
        print(f"[warn] cdn manifest: {exc}", file=sys.stderr)
        return []


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


def main() -> int:
    dates = discover_dates()
    if not dates:
        print("no digest dates discoverable from local or CDN", file=sys.stderr)
        return 1
    print(f"[discover] {len(dates)} dates to process")

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
                # 去重避免同一個人化 digest 多次計算 — 用 (date, ticker, verdict) 三元組
                seen_keys = {(r["date"], r["ticker"], r["verdict_class"]) for r in recs}
                added = 0
                for tok in tokens:
                    p_html = fetch_personal_digest_html(tok)
                    if not p_html:
                        continue
                    p_recs = parse_digest_html(date_str, p_html)
                    for pr in p_recs:
                        key = (pr["date"], pr["ticker"], pr["verdict_class"])
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        pr["source_scope"] = "personal"  # 標記不寫入公開 records
                        personal_records.append(pr)
                        added += 1
                    time.sleep(0.1)  # 對 worker 客氣點
                print(f"  + personal: {len(tokens)} tokens → {added} new (ticker,verdict) added to stats only")

    # 公版 + 個人化合在一起算 price + judge
    combined = all_records + personal_records
    keys = {(r["ticker"], r["date"]) for r in combined}
    print(f"[fetch] {len(keys)} (ticker,date) pairs via yfinance (cached where possible)...")
    prices = fetch_prices(keys)

    judged_public = []
    for r in all_records:
        r["outcome"] = judge(r, prices)
        judged_public.append(r)
    judged_personal = []
    for r in personal_records:
        r["outcome"] = judge(r, prices)
        judged_personal.append(r)

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

    stats = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days_covered": len({r["date"] for r in judged_all}),
        "total_records": len(judged_all),
        "judged_records": len(a_recs) + len(c_recs),
        "a_count": len(a_recs),
        "a_wins": a_wins,
        "a_rate": round(a_rate, 1),
        "c_count": len(c_recs),
        "c_wins": c_wins,
        "c_rate": round(c_rate, 1),
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
