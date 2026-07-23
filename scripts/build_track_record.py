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
import bisect
import fcntl
import hashlib
import json
import re
import shutil
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
            # 閘門名接受連字號:producer 端 rebuy-bleed 自 2026-07-13 起就帶 hyphen,
            # 舊 charset [a-z_]+ 配不上=該閘反事實追蹤靜默漏記(2026-07-21 盤點時發現)。
            gm = re.match(r"\s*gated:(buy|hold|sell|wait):([a-z_-]+)\s*$", str(c))
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


# ── 結算日曆(2026-07-13 真根治;前身=偽 bar 共識濾網,驗證見 research/verifier_settlement_guard_20260713.md;
#    日曆版獨立驗證+A/B 見 research/verifier_settlement_calendar_20260713.md,下述 F1/F3 即其 finding)──
# 結算原本用各檔自己的 sorted_dates[ref_idx+N] 位置索引:單檔 bar「多」(Yahoo 偽 bar:美股假期
# /週末填補)或「缺」(feed 缺洞)都讓索引整段平移到錯的交易日 → 錯結算價被 judge 首判凍進 label
# 永不自癒(2026-07 事故:美股 07/04 觀察日 07/03 偽 bar 讓 6 筆建議結算窗早一日、label 凍錯)。
# 根治=改數「市場共識交易日曆」:每市場取「覆蓋該日的檔中 ≥60% 有 bar」的日期為交易日,
# settlement = ref 在日曆上 +N,再回各檔查該日收盤(該檔缺 bar 就近往回、整窗停牌誠實待結)。
# 覆蓋分母 = 歷史跨距含該日的檔數(span-aware):cache 各檔左緣參差(3M 窗逐日重抓)不會把
# 深歷史真交易日誤判為低占比(舊濾網靠鄰日 contiguity 巧合才保住,驗證者 Finding 1 佐證)。
# 相對舊濾網的收斂:①「跨距內」偽 bar 不論出現在幾檔(灰帶 0.15–0.60 舊法漏抓,Finding 2)都
#   進不了日曆;右緣「未來日」偽 bar 另靠 cover>=2 閘擋單檔(F3)——⚠️殘窗:≥2 檔同印同一未來日
#   且結算恰發生在乾淨檔補齊前那輪 build,仍會凍錯 1d label+chg 事實欄,reconcile 對已存 chg
#   永不覆寫=無回溯自癒。窗口極窄(假期/週末單一 build)但非零,事故再現先查這裡。
# ②單檔缺真日不再讓該檔窗口默默變長——窗口對齊市場,價格就近結算且 stderr 可見
# ③「真交易日但多數檔缺」(Finding 1)仍不可分辨——落日曆外 → 全市場一致晚一日,錯法均勻可見,
#   不再只毒打資料乾淨的少數檔(純覆蓋率共識的不可約極限)。市場檔數 <5 不建日曆,退回位置索引。
# 市場分群 ticker.isdigit()(台股全數字含 5-6 位 ETF;美股全字母);MarketDaily 只推個股,
# 不含含字母的台股權證/ETN(如 07286P),若未來納入需改分群鍵(驗證者 Finding 3)。
_CONSENSUS_MIN_TICKERS = 5   # 市場檔數不足以建日曆 → 退回位置索引(原行為)
_CAL_REAL_FRAC = 0.60        # 覆蓋該日的檔 ≥ 此比例有 bar = 共識交易日
# ── 幽靈休市日濾網(2026-07-17)──
# 2026-07-10 颱風全市場休市,Yahoo 卻對 39/42 檔台股印出「=07-09 收盤複本」的幽靈 bar:
# 共識日曆的 ≥60% 覆蓋率防線只擋「少數檔的偽 bar」,對全市場級幽靈日結構性失明(93% 檔都有 bar
# → 07-10 混進日曆),結算落該日=拿到陳舊價、跨該日的窗=提早一個真實交易日。簽名=該日有 bar 的
# 檔裡 ≥90% 的收盤與各自前一個 bar 完全相同——單檔連兩日同收盤是常態(~1-2%),≥10 檔裡 9 成
# 同時發生只有「休市+資料商複製前日 bar」一種解釋(實測 07-10 為 39/39=100%,真交易日遠低於此)。
_PHANTOM_MIN_SYMBOLS = 10    # 有 bar 檔數低於此不判(樣本太薄,寧可保守不剔)
_PHANTOM_IDENTICAL_FRAC = 0.90
# fetch_prices 的 off-calendar 提示對已判定幽靈日免印(偵測行已印一次,39 檔逐檔印=洗版)
_LAST_PHANTOM_DAYS: dict[str, set] = {}


def _market_of(ticker: str) -> str:
    return "TW" if ticker.strip().isdigit() else "US"


def _market_trading_calendar(
        hist_by_ticker: dict[str, dict]) -> tuple[dict[str, list[str]], dict[str, dict[str, float]]]:
    """每市場共識交易日曆。回傳 ({mkt: sorted 交易日}, {mkt: {date: 覆蓋比}});檔數不足的市場不建。"""
    groups: dict[str, list[dict]] = {}
    for t, h in hist_by_ticker.items():
        if h:
            groups.setdefault(_market_of(t), []).append(h)
    cals: dict[str, list[str]] = {}
    freqs: dict[str, dict[str, float]] = {}
    for mkt, hists in groups.items():
        if len(hists) < _CONSENSUS_MIN_TICKERS:
            continue
        spans = [(min(h), max(h)) for h in hists]
        cnt: dict[str, int] = {}
        for h in hists:
            for d in h:
                cnt[d] = cnt.get(d, 0) + 1
        fr: dict[str, float] = {}
        cover: dict[str, int] = {}
        for d, c in cnt.items():
            n_cover = sum(1 for lo, hi in spans if lo <= d <= hi)
            cover[d] = n_cover
            fr[d] = c / n_cover if n_cover else 0.0
        freqs[mkt] = fr
        # 幽靈休市日:該日有 bar 的檔中 ≥_PHANTOM_IDENTICAL_FRAC 與各自前一 bar 完全相同 → 剔除
        same_cnt: dict[str, int] = {}
        both_cnt: dict[str, int] = {}
        for h in hists:
            sd_h = sorted(h)
            for i in range(1, len(sd_h)):
                v, pv = h[sd_h[i]], h[sd_h[i - 1]]
                if v is None or pv is None:
                    continue
                both_cnt[sd_h[i]] = both_cnt.get(sd_h[i], 0) + 1
                if abs(v - pv) < 1e-9:
                    same_cnt[sd_h[i]] = same_cnt.get(sd_h[i], 0) + 1
        phantom = {d for d, n in both_cnt.items()
                   if n >= _PHANTOM_MIN_SYMBOLS
                   and same_cnt.get(d, 0) / n >= _PHANTOM_IDENTICAL_FRAC}
        for d in sorted(phantom):
            print(f"[settle-cal] {mkt} {d}: 幽靈休市日剔除"
                  f"({same_cnt.get(d, 0)}/{both_cnt[d]} 檔 bar=前日複本;"
                  f"休市+資料商複製前日 bar 簽名)", file=sys.stderr)
        _LAST_PHANTOM_DAYS[mkt] = phantom
        # 覆蓋檔數 <2 不進日曆(2026-07-13 驗證者 F3):右緣「未來日期偽 bar」會讓分母塌縮成
        # 髒檔自己(fr=1.0)混進日曆;真右緣 bar 若暫時只有 1 檔有,晚一輪 build 自然補進,無害。
        cals[mkt] = sorted(d for d, f in fr.items()
                           if f >= _CAL_REAL_FRAC and cover[d] >= 2 and d not in phantom)
    return cals, freqs


def _settle_on_calendar(hist_dict: dict, sd: list[str], cal: list[str], cal_set: set[str],
                        ticker: str, d: str) -> dict | None:
    """在市場日曆上數結算窗(消除單檔 bar 增/缺造成的位置平移)。回傳與位置索引法同構的欄位。"""
    i = bisect.bisect_left(cal, d)
    if i >= len(cal):
        return None
    ref_date = cal[i]
    # 基準價:優先 rec 日當天 bar,次日曆 ref 日,再退檔內下一個「日曆上的」bar(週末 rec/feed 缺洞)。
    # 三層全部閘在日曆上(2026-07-13 驗證者 F1):rec 日=假日/週末而髒 feed 恰有當日偽 bar 時,
    # 不閘會直接拿偽價當基準(帳本現存 36 筆假日 key+7 筆週六 key 都踩得到)。
    if d in cal_set and d in hist_dict:
        base_date, close = d, hist_dict[d]
    elif ref_date in hist_dict:
        base_date, close = ref_date, hist_dict[ref_date]
    else:
        later = [dd for dd in sd if dd >= d and dd in cal_set]
        if not later:
            return None
        base_date, close = later[0], hist_dict[later[0]]
        print(f"[settle-cal] {ticker} {d}: 日曆 ref {ref_date} 無 bar,基準退至 {base_date}",
              file=sys.stderr)
    last_bar = sd[-1]

    def px(n: int) -> tuple[float | None, str | None]:
        j = i + n
        if j >= len(cal):
            return None, None                # 市場日曆還沒長到 → 未到期
        tgt = cal[j]
        if tgt <= base_date:
            # 退化窗守衛(2026-07-17):rec 日無 bar 使基準前推越過日曆 ref 時,結算日可能
            # 落在基準日當日或之前(chg 恆 0 的假結算,6907 2026-07-10 實例)→ 誠實待結
            print(f"[settle-cal] {ticker} {d}+{n}: 結算日 {tgt} ≤ 基準日 {base_date},"
                  f"退化窗待結", file=sys.stderr)
            return None, None
        if tgt > last_bar:
            return None, None                # 該檔資料尚未涵蓋結算日 → 未到期(同位置法右緣,不用停牌舊價結算)
        v = hist_dict.get(tgt)
        if v is not None:
            return v, tgt
        # 結算日該檔缺 bar(停牌/feed 缺洞)→ 就近往回取窗內最後一個「日曆上的」bar
        k = bisect.bisect_right(sd, tgt) - 1
        while k >= 0 and sd[k] > base_date:
            if sd[k] in cal_set:
                print(f"[settle-cal] {ticker} {d}+{n}: 結算日 {tgt} 無 bar,就近用 {sd[k]}",
                      file=sys.stderr)
                return hist_dict[sd[k]], sd[k]
            k -= 1
        return None, None                    # 整窗無 bar(長停牌)→ 誠實待結

    path_dates = [dd for dd in sd if dd > base_date and dd in cal_set][:13]
    p1, d1 = px(1)
    p5, d5 = px(5)
    p21, d21 = px(21)
    p63, d63 = px(63)
    return {"close": close, "next_close": p1, "close_5d": p5,
            "close_21d": p21, "close_63d": p63,
            "base_date": base_date,
            "date_1d": d1, "date_5d": d5, "date_21d": d21, "date_63d": d63,
            "path": [hist_dict[dd] for dd in path_dates], "path_dates": path_dates}


# ── 現金股息修正(2026-07-17)────────────────────────────────────
# Yahoo quote.close 語意:分割/除權(配股)會回溯調整(0050 2025-06-18 1:4、4989 2026-06-29 實證),
# 現金股息「不」調整(2330/3034/6669 快取=官方 raw 實證)→ 持有窗跨除息日時 chg 被股息機械性壓低:
# buy 假 loss/sell·wait 假 win(除權息旺季系統性偏差,2026-07-17 稽核實測 41 筆公版 label 翻轉,
# A 勝率被低估 ~0.7pp、C 被高估 ~0.7pp)。修正=結算價加回窗內現金股息(持有人實際拿到)。
# TW 主源=FinMind TaiwanStockDividendResult(官方;Yahoo TW events 不可靠:漏 0050 真分割、列
# 6669 幽靈分割),FinMind 網路/API 失敗才退 Yahoo events;US=Yahoo v8 events=div(query2 直連)。
# 除權(配股)列不加現金(Yahoo close 已回溯調整,再加=重複計算),僅 stderr 提示。
# 失敗語意=fail-open:抓不到股息 → 該檔本輪無調整(=舊行為)+stderr 警告,絕不讓夜跑 crash。
DIV_CACHE_FILE = ROOT / "scripts" / ".div_cache.json"
_DIV_CACHE_FRESH_H = 20          # 快取 20h 內免重抓(一天一次)
_DIV_SCALE_SANITY = (0.2, 1.2)   # 快取前收/FinMind before_price 合理帶(除權回溯調整換算用)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _events_valid(evs) -> bool:
    """股息事件清單形狀驗證(fetch 產出與快取讀回共用):date 必須是 ISO 字串、金額可轉
    float。毒快取自癒——非法列=整筆作廢重抓,不讓髒 date 流進 _attach_window_divs 的
    bisect 比較炸掉夜跑(驗證者 F4)。"""
    if not isinstance(evs, list):
        return False
    for ev in evs:
        if not isinstance(ev, dict):
            return False
        dd = ev.get("date")
        if not isinstance(dd, str) or not _ISO_DATE_RE.match(dd):
            return False
        try:
            float(ev.get("cash") or 0.0)
            float(ev.get("stock") or 0.0)
        except (TypeError, ValueError):
            return False
    return True


def _fetch_finmind_dividends(ticker: str, start_iso: str) -> list[dict] | None:
    """FinMind TaiwanStockDividendResult → [{'date','cash','stock','before_price'},...]。
    網路/API 失敗回 None(呼叫端 fallback);status 200 空資料回 []=該檔真的無除權息。"""
    params = {"dataset": "TaiwanStockDividendResult",
              "data_id": ticker, "start_date": start_iso}
    tok = os.environ.get("FINMIND_TOKEN", "").strip()  # 同 intel/* 連接器慣例;未配置=匿名層
    if tok:
        params["token"] = tok
    url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[div] finmind {ticker}: {exc}", file=sys.stderr)
        return None
    if data.get("status") != 200:
        print(f"[div] finmind {ticker}: status={data.get('status')}", file=sys.stderr)
        return None
    out = []
    # payload 形狀漂移(data 非 list/列非 dict/date 非 ISO 字串)=整檔回 None 觸發 Yahoo
    # fallback:解析迴圈原在 try 外,status 200 + 形狀漂移會炸穿夜跑,且非法 date 會先進
    # .div_cache.json 再 crash _attach_window_divs,20h 新鮮期內每輪重放毒快取(驗證者 F4)。
    try:
        rows = data.get("data") or []
        if not isinstance(rows, list):
            raise TypeError(f"data 形狀 {type(rows).__name__}")
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError(f"row 形狀 {type(row).__name__}")
            kind = str(row.get("stock_or_cache_dividend") or "")
            try:
                amt = float(row.get("stock_and_cache_dividend") or 0.0)
            except (TypeError, ValueError):
                continue
            dd = row.get("date")
            if dd in (None, ""):
                continue
            if not isinstance(dd, str) or not _ISO_DATE_RE.match(dd):
                raise TypeError(f"date 非 ISO 字串: {dd!r}")
            if amt <= 0:
                continue
            ev = {"date": dd, "cash": 0.0, "stock": 0.0,
                  "before_price": row.get("before_price")}
            # kind 精確集合比對:「現金股利」型詞彙含『股』字,子字串判斷會把它誤歸
            # 配股而靜默略過現金修正(驗證者 F5,vocab 裸子字串 beekeeper 同型坑)
            if kind in ("息", "除息"):
                ev["cash"] = amt
            elif kind in ("權", "除權"):
                ev["stock"] = amt
            else:
                # 「權息」合併列/未知詞彙:現金歸屬不明,寧可不調整(fail-open)也不錯加
                print(f"[div] {ticker} {dd}: kind={kind!r} 無法歸類,不調整",
                      file=sys.stderr)
                ev["ambiguous"] = True
            out.append(ev)
    except Exception as exc:
        print(f"[div] finmind {ticker}: payload 異常({exc}),退 Yahoo", file=sys.stderr)
        return None
    return out


def _fetch_yahoo_dividends(sym_candidates: list[str], rng: str = "6mo") -> list[dict] | None:
    """Yahoo v8 events=div。日期轉換與 yahoo_chart 同款 fromtimestamp(本地)保持對齊。"""
    for sym in sym_candidates:
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(sym)}?interval=1d&range={rng}&events=div")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            r = (data.get("chart") or {}).get("result") or []
            if not r:
                continue
            ev = (r[0].get("events") or {}).get("dividends") or {}
            agg: dict[str, float] = {}
            for v in ev.values():
                dd = datetime.fromtimestamp(v["date"]).date().isoformat()
                agg[dd] = agg.get(dd, 0.0) + float(v["amount"])
            return [{"date": dd, "cash": amt, "stock": 0.0, "before_price": None}
                    for dd, amt in sorted(agg.items())]
        except Exception as exc:
            print(f"[div] yahoo {sym}: {exc}", file=sys.stderr)
            continue
    return None


def fetch_dividends(tickers: set[str], start_iso: str) -> dict[str, list[dict]]:
    """全部代碼的除權息事件(.div_cache.json 快取 20h;失敗 fail-open 沿用舊快取或空)。"""
    try:
        cache = json.loads(DIV_CACHE_FILE.read_text()) if DIV_CACHE_FILE.exists() else {}
    except Exception:
        cache = {}
    out: dict[str, list[dict]] = {}
    dirty = False
    now = datetime.now()
    for t in sorted(tickers):
        ent = cache.get(t)
        if ent and not _events_valid(ent.get("events") or []):
            print(f"[div] {t}: 快取事件形狀非法,作廢重抓(毒快取自癒)", file=sys.stderr)
            ent = None
        if ent and ent.get("start") and ent["start"] <= start_iso:
            try:
                age_h = (now - datetime.fromisoformat(ent["fetched_at"])).total_seconds() / 3600
            except Exception:
                age_h = 1e9
            if 0 <= age_h < _DIV_CACHE_FRESH_H:
                out[t] = ent.get("events") or []
                continue
        if _market_of(t) == "TW":
            evs = _fetch_finmind_dividends(t, start_iso)
            if evs is None:  # FinMind 失敗才退 Yahoo;空 list=真的沒有,不退
                evs = _fetch_yahoo_dividends([f"{t}.TW", f"{t}.TWO"])
        else:
            evs = _fetch_yahoo_dividends([t])
        if evs is None:
            if ent:
                print(f"[div] {t}: 本輪抓取失敗,沿用舊快取({ent.get('fetched_at')})",
                      file=sys.stderr)
                out[t] = ent.get("events") or []
            else:
                print(f"[div] {t}: 無股息資料可用,本輪不調整(fail-open)", file=sys.stderr)
                out[t] = []
            continue
        out[t] = evs
        cache[t] = {"fetched_at": now.isoformat(timespec="seconds"),
                    "start": start_iso, "events": evs}
        dirty = True
        time.sleep(0.25)
    if dirty:
        try:
            DIV_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))
        except Exception as exc:
            print(f"[div] cache write failed: {exc}", file=sys.stderr)
    return out


def _attach_window_divs(fields: dict, events: list[dict], hist_dict: dict,
                        cal: list[str], ticker: str) -> None:
    """把 (基準日, 結算日] 窗內現金股息掛到 fields['div_{hz}']。
    生效日語意:排定除息日遇休市順延到日曆上第一個 ≥ 排定日的交易日
    (FinMind date=排定日;3034 2026-07-10 颱風休市 → 07-13 生效實例)。"""
    base = fields.get("base_date")
    if not base or not events or not cal:
        return
    sd = sorted(hist_dict)
    resolved: list[tuple[str, float]] = []
    for ev in events:
        dd = ev.get("date") or ""
        if not dd or ev.get("ambiguous"):
            continue
        i = bisect.bisect_left(cal, dd)
        if i >= len(cal):
            continue  # 生效日在日曆右緣外(未來事件)
        eff = cal[i]
        if ev.get("stock"):
            if base < eff <= (fields.get("date_63d") or fields.get("date_21d")
                              or fields.get("date_5d") or fields.get("date_1d") or ""):
                print(f"[div] {ticker} {eff}: 除權(配股 {ev['stock']})不加現金"
                      f"(Yahoo close 已回溯調整)", file=sys.stderr)
            continue
        cash = float(ev.get("cash") or 0.0)
        if cash <= 0:
            continue
        # 尺度換算:快取序列可能被「更晚的除權/分割」回溯調整,官方股息金額是 raw 尺度;
        # 用 快取前收/官方 before_price 換算(無 before_price 或帶外 → 1.0 並提示)
        factor = 1.0
        bp = ev.get("before_price")
        prevs = [x for x in sd if x < eff]
        if bp and prevs:
            cp = hist_dict.get(prevs[-1])
            f = None
            try:
                if cp:
                    f = cp / float(bp)
            except (TypeError, ValueError, ZeroDivisionError):
                f = None
            if f is not None:
                if _DIV_SCALE_SANITY[0] <= f <= _DIV_SCALE_SANITY[1]:
                    factor = f
                else:
                    print(f"[div] {ticker} {eff}: 尺度帶外"
                          f"(cache_prev/before_price={f:.3f}),股息不換算", file=sys.stderr)
        resolved.append((eff, cash * factor))
    if not resolved:
        return
    for hz in ("1d", "5d", "21d", "63d"):
        tgt = fields.get(f"date_{hz}")
        if not tgt:
            continue
        tot = sum(c for e, c in resolved if base < e <= tgt)
        if tot:
            fields[f"div_{hz}"] = tot


def fetch_prices(keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    cache = load_cache()
    by_ticker: dict[str, list[str]] = {}
    for t, d in keys:
        by_ticker.setdefault(t, []).append(d)

    # Pass 1:取得每檔完整歷史(快取或抓取),先集齊才能跨檔算共識辨識偽 bar。
    hist_by_ticker: dict[str, dict[str, float]] = {}
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
        hist_by_ticker[ticker] = hist_dict

    # 跨檔共識日曆:結算窗一律數市場交易日,不再數各檔自己的 bar(見 fetch_prices 上方註解)。
    calendars, cal_freq = _market_trading_calendar(hist_by_ticker)
    cal_sets = {mkt: set(c) for mkt, c in calendars.items()}

    # 現金股息事件(跨除息窗 chg 修正用;fail-open,見 fetch_dividends)
    all_dates = [d for _, d in keys]
    div_events: dict[str, list[dict]] = {}
    if all_dates:
        div_start = (datetime.fromisoformat(min(all_dates))
                     - timedelta(days=7)).date().isoformat()
        div_events = fetch_dividends(
            {t for t, _ in keys if hist_by_ticker.get(t)}, div_start)

    # Pass 2:逐檔結算。
    out: dict[tuple[str, str], dict] = {}
    for ticker, dates in by_ticker.items():
        hist_dict = hist_by_ticker.get(ticker)
        if not hist_dict:
            continue
        sorted_dates = sorted(hist_dict.keys())
        mkt = _market_of(ticker)
        cal = calendars.get(mkt)
        if cal:
            fr = cal_freq.get(mkt) or {}
            for dd in sorted_dates:
                # 檔內 bar 不在日曆上(且落日曆範圍內)= 疑偽 bar/極少數覆蓋日,結算不採用;可見不靜默
                # (已判定的幽靈休市日免逐檔印:偵測時已印一次,39 檔逐檔印=洗版)
                if (dd not in cal_sets[mkt] and cal[0] <= dd <= cal[-1]
                        and dd not in _LAST_PHANTOM_DAYS.get(mkt, set())):
                    print(f"[settle-cal] off-calendar bar {ticker} {dd} "
                          f"(market freq {fr.get(dd, 0.0):.0%})", file=sys.stderr)
            for d in dates:
                fields = _settle_on_calendar(hist_dict, sorted_dates, cal, cal_sets[mkt], ticker, d)
                if fields:
                    _attach_window_divs(fields, div_events.get(ticker) or [],
                                        hist_dict, cal, ticker)
                    out[(ticker, d)] = fields
            continue
        # 市場檔數不足以建日曆 → 原位置索引法(單檔 bar 增缺仍會平移,但無共識可依);可見不靜默
        n_mkt = sum(1 for t in hist_by_ticker if _market_of(t) == mkt and hist_by_ticker[t])
        print(f"[settle-cal] market {mkt} 檔數 {n_mkt}<{_CONSENSUS_MIN_TICKERS},"
              f" {ticker} 退回位置索引結算", file=sys.stderr)
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
            def _at(n: int) -> tuple[float | None, str | None]:
                if ref_idx + n < len(sorted_dates):
                    dd = sorted_dates[ref_idx + n]
                    return hist_dict[dd], dd
                return None, None
            nxt, d1 = _at(1)
            c5, d5 = _at(5)
            c21, d21 = _at(21)
            c63, d63 = _at(63)
            path_dates = sorted_dates[ref_idx + 1:ref_idx + 14]
            path = [hist_dict[dd] for dd in path_dates]
            fields = {"close": today, "next_close": nxt, "close_5d": c5,
                      "close_21d": c21, "close_63d": c63, "path": path,
                      "path_dates": path_dates,
                      "base_date": sorted_dates[ref_idx],
                      "date_1d": d1, "date_5d": d5, "date_21d": d21, "date_63d": d63}
            _attach_window_divs(fields, div_events.get(ticker) or [],
                                hist_dict, sorted_dates, ticker)
            out[(ticker, d)] = fields
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
    pdates = (p or {}).get("path_dates") or []
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
    def _d(i):
        return pdates[i] if i < len(pdates) else None
    rest = path[entry_i + 1:entry_i + 11]
    for j, c in enumerate(rest):
        if c >= tgt:
            return {"result": "win", "ret_pct": round((c - entry) / entry * 100, 2),
                    "entry_date": _d(entry_i), "exit_date": _d(entry_i + 1 + j)}
        if c <= stp:
            return {"result": "loss", "ret_pct": round((c - entry) / entry * 100, 2),
                    "entry_date": _d(entry_i), "exit_date": _d(entry_i + 1 + j)}
    if len(rest) < 10:
        return {"result": "pending", "ret_pct": None, "entry_date": _d(entry_i)}
    return {"result": "expired", "ret_pct": round((rest[-1] - entry) / entry * 100, 2),
            "entry_date": _d(entry_i), "exit_date": _d(entry_i + len(rest))}


def _env_key(name: str) -> str:
    """從 ROOT/.env 或環境變數取 key(builder 在 winrig cron 只被注入 INTERNAL_TOKEN)。"""
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def _norm_tk(v) -> str:
    if isinstance(v, dict):
        v = v.get("symbol") or v.get("ticker") or ""
    return str(v).upper().replace(".TWO", "").replace(".TW", "").strip()


def fetch_user_pref_sets() -> dict[str, dict]:
    """email → 自選股集合(us/tw/all,正規化)。Brevo 訂閱名單 + worker /get-preferences
    (Bearer INTERNAL_TOKEN bypass)。供 token→用戶歸戶比對;失敗回空 dict(歸戶跳過,非致命)。"""
    brevo_key = _env_key("BREVO_API_KEY")
    if not (brevo_key and INTERNAL_TOKEN):
        return {}
    out: dict[str, dict] = {}
    try:
        list_id = _env_key("BREVO_LIST_ID") or "2"
        req = urllib.request.Request(
            f"https://api.brevo.com/v3/contacts/lists/{list_id}/contacts?limit=500",
            headers={"api-key": brevo_key, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            contacts = json.loads(resp.read()).get("contacts") or []
        for c in contacts[:200]:
            em = (c.get("email") or "").lower()
            if not em:
                continue
            try:
                preq = urllib.request.Request(
                    f"{WORKER}/get-preferences",
                    data=json.dumps({"email": em}).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {INTERNAL_TOKEN}", "User-Agent": UA},
                    method="POST")
                with urllib.request.urlopen(preq, timeout=15) as presp:
                    prefs = json.loads(presp.read())
            except Exception:
                continue
            us = {_norm_tk(x) for x in (prefs.get("us_stocks") or [])} - {""}
            tw = {_norm_tk(x) for x in (prefs.get("tw_stocks") or [])} - {""}
            if us or tw:
                out[em] = {"us": us, "tw": tw, "all": us | tw}
    except Exception as exc:
        print(f"[warn] pref-sets fetch failed: {exc}", file=sys.stderr)
    return out


def match_tokens_to_users(personal_records: list[dict]) -> dict[str, str]:
    """token → email 歸戶:用該 token 日報的『完整持股卡集合』比對用戶自選股。
    雙時段日報一個 token 只含單一市場的卡,故規則:
      候選 = 卡集合 ⊆ 用戶(us∪tw);唯一候選 → 歸戶;
      多候選 → 卡集合『恰等於』某用戶的 us 或 tw 全集且唯一 → 歸戶;否則留空不亂認。"""
    tok_cards: dict[str, set] = {}
    for r in personal_records:
        tok = r.get("_user_token") or ""
        tk = _norm_tk(r.get("ticker") or "")
        if tok and tk:
            tok_cards.setdefault(tok, set()).add(tk)
    if not tok_cards:
        return {}
    pref_sets = fetch_user_pref_sets()
    if not pref_sets:
        return {}
    tok_user: dict[str, str] = {}
    for tok, cards in tok_cards.items():
        subs = [em for em, p in pref_sets.items() if cards <= p["all"]]
        if len(subs) == 1:
            tok_user[tok] = subs[0]
        elif len(subs) > 1:
            exact = [em for em in subs
                     if cards == pref_sets[em]["us"] or cards == pref_sets[em]["tw"]]
            if len(exact) == 1:
                tok_user[tok] = exact[0]
    print(f"[match] token→user: {len(tok_user)}/{len(tok_cards)} tokens attributed "
          f"(users={len(pref_sets)})")
    return tok_user


def fetch_spx_regime(closes: dict[str, float] | None = None) -> dict[str, str]:
    """日期 → 大盤趨勢標記(SPX 收盤 vs 5 個交易日前:up/down)。
    用來把勝率按 regime 拆開 — 驗證「下跌 regime 整批喊買 = 主要虧損源」假設,
    並追蹤 2026-06-10 上線的 regime 閘門有沒有真的把 down-regime 勝率拉起來。"""
    if closes is None:
        closes = yahoo_chart("^GSPC", "", "")
    if not closes:
        return {}
    ds = sorted(closes)
    out = {}
    for i, d in enumerate(ds):
        if i >= 5:
            out[d] = "down" if closes[d] < closes[ds[i - 5]] else "up"
    return out


# 前夜 SPX 漲跌桶(2026-07-22,Delvin「看多勝率可悲——夜盤的影響」根因診斷):
# 「前夜」= call 日之前最後一個已完成 SPX session 的單日漲跌%。TW 早報 07:00 與 US 晚報
# 20:00 生成當下這都是已知資訊(analyzer 端即 us_market["^GSPC"].change_pct)。
# 帳本實證(702 筆去重 buy):SPX 收漲夜隔日追買 = 看多最大毒桶(0~+0.5% 桶勝率 17.8%/n=163),
# 既有 regime/追高閘全漏接(小漲夜不觸發 risk_on);收跌夜看多 50.7~78.3% 照常會贏。
# OOS 拆半與日 cluster 皆同向(日中位數 18% vs 70%)。桶邊界隨 JSON 下發,analyzer 讀同一份,
# 兩端永不漂移。up 桶不再細分 0~0.5/0.5+:era 世代天數不足會讓讀取端 day floor 永遠關門。
OVERNIGHT_BUCKET_EDGES: dict[str, tuple[float, float]] = {
    "dn_deep": (-999.0, -1.0),
    "dn": (-1.0, 0.0),
    "up": (0.0, 999.0),
}


def era_overnight_buckets(recs: list[dict], closes: dict[str, float]) -> dict:
    """era 記錄 × 前夜 SPX 桶 → analyzer._pp_overnight_autogate 的資料源。
    days 欄必帶:同夜記錄高度相關,n 會虛胖(day-cluster 教訓),讀取端必須用 day floor。
    closes 只有 3M(yahoo_chart range 上限,與 fetch_spx_regime 同一限制)→ 桶天然帶
    recency,更舊的 era 記錄自動淡出,不需另設衰減。"""
    ds = sorted(closes)

    def _bucket(d: str) -> str | None:
        i = bisect.bisect_left(ds, d)
        if i < 2:
            return None
        pct = (closes[ds[i - 1]] / closes[ds[i - 2]] - 1) * 100
        return next((k for k, (lo, hi) in OVERNIGHT_BUCKET_EDGES.items() if lo <= pct < hi), None)

    bmap = {d: _bucket(d) for d in {r["date"] for r in recs}}
    out: dict = {"buckets": {k: list(v) for k, v in OVERNIGHT_BUCKET_EDGES.items()}}
    for mk in ("tw", "us"):
        blk = {}
        for vc in ("buy", "hold", "sell", "wait"):
            for bn in OVERNIGHT_BUCKET_EDGES:
                sub = [r for r in recs if r.get("market") == mk and r["verdict_class"] == vc
                       and bmap.get(r["date"]) == bn]
                w = sum(1 for r in sub if r["outcome"] == "win")
                n = len(sub)
                blk[f"{vc}|{bn}"] = {
                    "count": n, "wins": w, "days": len({r["date"] for r in sub}),
                    "rate": round(w / n * 100, 1) if n >= 15 else None,
                    "status": "insufficient_data" if n < 15 else None}
        out[mk] = blk
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

# 判定規則版本:label_from_chg 的語意每次變更都必須 bump,並沿用 append_personal_ledger
# 的 reconcile 讓歷史帳本列從「存下的 chg 事實」重導出 label(2026-07-12 根治:append-only
# 帳本 × 規則演進 = 舊行永遠停在舊規則,「修規則+重跑」會靜默地什麼都沒修,見 8138144 的
# 22 筆 hold 凍結事故)。版本史:
#   v1 = hold 對稱 ±3%(2026-07-09 14:41 前)
#   v2 = hold 不對稱只罰跌破下緩衝(8755845 起)
JUDGE_RULE_VERSION = "v2"
# 全部曾經存在過的版本(bump 時同步 append):週跑偵測器 ledger_label_freshness 用來抓
# 帳本裡不在版本史上的髒 rule 值(=手改/竄改,FAIL)
JUDGE_RULE_HISTORY = ("v1", "v2")

# chg 事實欄的計算基準(fact-version):settlement_chg 2026-07-17 起含窗內現金股息,
# 帳本新舊列的 chg 從此混兩種語意——label 與 chg 自洽、rule 同為 v2,silent-drift
# 偵測器無從分辨(驗證者第17案 F1:27 筆跨除息窗凍錯列因此永久隱形)。事實欄自帶
# basis 章:寫入端蓋現行章,舊列由 _reconcile_row 一次性補 legacy 章,舊語意列從此
# 可枚舉。27 筆凍錯列改寫 label 動公開勝率,清單已列待 Delvin 拍板(比照 2026-07-13
# 9 筆前例),見 ~/autonomous/research/tr_ca_audit/ledger_27_frozen_flips.md。
CHG_BASIS = "px+div"        # 現行:(settle+div-base)/base
CHG_BASIS_LEGACY = "px"     # 2026-07-17 前:(settle-base)/base,不含現金股息


def settlement_chg(rec: dict, prices: dict, horizon: str = "5d") -> float | None:
    """結算日漲跌(原始事實):建議日收盤 → horizon 結算價的變化率;尚未到結算日回 None。
    2026-07-17 起含窗內現金股息(持有人實拿;除息機械缺口不再被算成虧損):
    chg = (settle + div - base) / base。除權(配股)/分割不加(Yahoo close 已回溯調整)。"""
    p = prices.get((rec["ticker"], rec["date"]))
    if not p:
        return None
    ref = p.get(_HORIZONS[horizon]["ref"])
    if ref is None:
        return None
    div = p.get("div_" + horizon) or 0.0
    return (ref + div - p["close"]) / p["close"]


def label_from_chg(verdict_class: str, chg: float, horizon: str = "5d",
                   holder: bool = False) -> str | None:
    """判定規則單一真源:從結算日漲跌導出 win/loss。judge()/judge_holder()/帳本 reconcile/
    零技能基線全部走這裡,規則只在此處存在一份(改語意必 bump JUDGE_RULE_VERSION)。
    一般框架(holder=False):
      buy  → 漲才算對
      hold → 2026-07-09 修正:「續抱」對讀者是不對稱的——照建議續抱後上漲是好結果,
             只有跌破下方緩衝才是建議錯(與持有者框架同規則)。舊版 ±3% 對稱緩衝
             把「續抱後大漲」也記輸,量的是「預測股價不動」不是建議品質
             (實測 hold 桶 up/down regime 同時 ~20%,對稱地低=緩衝問題非方向問題)。
      sell → 強信號,必須真跌才算對
      wait → 「中性偏空 / 暫時別進場」— 緩衝後小漲不算錯
    持有者框架(holder=True,type="H"):量的是「聽建議 vs 出場,持有期間有沒有守住」,
      wait(閘門降級的防守)與 hold 同規則(沒跌破緩衝就算對,大漲是好事不對稱懲罰)。"""
    cfg = _HORIZONS[horizon]
    if verdict_class == "buy":
        return "win" if chg > 0 else "loss"
    if verdict_class == "hold" or (holder and verdict_class == "wait"):
        return "win" if chg >= -cfg["hold"] else "loss"
    if verdict_class == "sell":
        return "win" if chg < 0 else "loss"
    if verdict_class == "wait":
        return "win" if chg < cfg["wait"] else "loss"
    return None


def judge(rec: dict, prices: dict, horizon: str = "5d") -> str | None:
    """結算一筆建議。
    horizon="5d"(主指標/週結):建議日收盤 vs 5 個交易日後收盤 — 對齊卡片明寫的「短線 1-2 週視角」。
      2026-06-10 修正:原本只看隔日一天,拿單日雜訊評 1-2 週的建議 = 量尺錯位,
      量到的是「隔日漲跌擲銅板」不是建議品質。
    horizon="21d"/"63d"(月結/季結,2026-07-07 起):同一批判斷分別在 ~1 個月/~1 季後結算。
    horizon="1d"(輔助參考):隔日收盤,保留供對照。"""
    chg = settlement_chg(rec, prices, horizon)
    if chg is None:
        return None  # 尚未到結算日 → 待結
    return label_from_chg(rec["verdict_class"], chg, horizon)


def judge_holder(rec: dict, prices: dict, horizon: str = "5d") -> str | None:
    """持有者框架結算(type="H",2026-07-07 持倉客製化):建議對象是「已持有」的用戶,
    量的是「聽這個建議 vs 出場,持有期間有沒有守住」:
      buy(加碼)   → 漲才算對(跟方向判斷同標準)
      hold(續抱)/wait(閘門降級的防守) → 沒有跌破緩衝就算對(續抱時大漲是好事,不對稱懲罰)
      sell(減碼/停損/獲利了結) → 之後真的跌=提前出場是對的"""
    chg = settlement_chg(rec, prices, horizon)
    if chg is None:
        return None  # 尚未到結算日 → 待結
    return label_from_chg(rec["verdict_class"], chg, horizon, holder=True)


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
                              regime_by_date: dict[str, str], prices: dict) -> list[dict]:
    """匿名化個人化建議→帳本欄位(修5)。只留 user token 的雜湊,不留 token/姓名/持股原文
    ——夠讓 edge_audit 稽核方向/信心/期望值,不夠反推是哪個人。
    2026-07-12 起每行加存原始事實欄:chg=結算日漲跌(全精度)+rule=判定規則版本,
    讓未來規則修正可由 reconcile 從事實重導出 label,不再依賴當時的價格快照。"""
    entries = []
    for r in judged_personal:
        outcome = r.get("outcome")
        if outcome not in ("win", "loss"):
            continue
        tok = r.get("_user_token") or ""
        user_hash = hashlib.sha256(tok.encode()).hexdigest()[:12] if tok else "unknown"
        sim = personal_sims.get(id(r))
        chg = settlement_chg(r, prices, "5d")
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
            "chg": chg,
            **({"chg_basis": CHG_BASIS} if chg is not None else {}),
            "rule": JUDGE_RULE_VERSION,
            # 持有者框架(type="H")補記自填成本,供未來 per-position 稽核
            **({"holder_entry": r["holder_entry"]} if r.get("holder_entry") else {}),
        })
    return entries


def _ledger_key(e: dict) -> tuple:
    return (e.get("date"), e.get("ticker"), e.get("type"),
            e.get("verdict_class"), e.get("user_hash"))


def _ledger_pairs_missing_chg() -> set[tuple[str, str]]:
    """帳本裡還沒存 chg 事實欄的 (ticker,date)——併入本輪抓價,讓 reconcile 能直接
    從價格快取補事實(fresh 只覆蓋本輪可歸戶的 token,歷史列大多要走這條)。"""
    pairs: set[tuple[str, str]] = set()
    if LEDGER_FILE.exists():
        for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("chg") is None and e.get("ticker") and e.get("date"):
                pairs.add((e["ticker"], e["date"]))
    return pairs


def _reconcile_row(stored: dict, fresh: dict | None, prices: dict | None = None) -> bool:
    """就地補全既有帳本列的「事實欄」,回傳是否有改動。
    永不改 label——唯一例外是 rule 落後現行版本:從「存下的 chg 事實」重導出 label
    (2026-07-12 根治 8138144 事故:append-only × 規則演進 = 舊行凍結在舊規則;
    以後改 judge 語意只要 bump JUDGE_RULE_VERSION,下一輪 build 自動完成遷移,
    且從事實重導出,不受價格回溯調整 drift 影響)。"""
    changed = False
    # ret:寫入當下 sim 常 pending → null 被 dedup 永久凍結;之後任何一輪 sim 出值就補上。
    # 只填 null,永不覆蓋已有值。
    if stored.get("ret") is None and fresh and fresh.get("ret") is not None:
        stored["ret"] = fresh["ret"]
        changed = True
    # chg:舊列沒存事實 → 一次性 backfill。優先取 fresh(與本輪 judge 同一價格來源);
    # fresh 缺席(token 已不可歸戶)退回本輪價格快取直接結算——沒有 chg 的列在未來
    # 規則 bump 時無法遷移,等於病沒根治,所以 main() 會把缺 chg 列的鍵也併入抓價。
    # 極少數舊列 backfill 出的 chg 會與「當年首判凍結的 label」不一致(→蓋不了章、留白給偵測器)。
    # 2026-07-13 根因確認:非除息回溯調整,而是首判時 Yahoo feed 有偽 bar(美股假期/週末)讓
    # sorted_dates[ref_idx+N] 結算窗位置平移、凍錯 label;Yahoo 事後清 bar,backfill 才拿到正確窗口。
    # fetch_prices 已改市場共識日曆結算(2026-07-13 根治)防未來復發;既有 9 筆凍錯 label 待人工決定是否改寫(動公開勝率)。
    if stored.get("chg") is None:
        if fresh and fresh.get("chg") is not None:
            stored["chg"] = fresh["chg"]
            stored["chg_basis"] = fresh.get("chg_basis") or CHG_BASIS
            changed = True
        elif prices is not None:
            c = settlement_chg(stored, prices, "5d")
            if c is not None:
                stored["chg"] = c
                stored["chg_basis"] = CHG_BASIS
                changed = True
    elif "chg_basis" not in stored:
        # 一次性 fact-version 遷移:寫入端 2026-07-17 起必蓋 basis 章,故「有 chg 無章」
        # 的列只可能寫於語意變更前 → 補 legacy 章,讓舊語意列永遠可枚舉(驗證者 F1)
        stored["chg_basis"] = CHG_BASIS_LEGACY
        changed = True
    if stored.get("chg") is not None:
        derived = label_from_chg(stored.get("verdict_class"), stored["chg"], "5d",
                                 holder=stored.get("type") == "H")
        rule = stored.get("rule")
        if rule is None:
            # 自我認證遷移:存的 label 與現行規則一致才蓋章;不一致=legacy drift
            # (價格回溯調整等),留白給偵測器可見,不 silent 改寫歷史 label。
            if derived == stored.get("label"):
                stored["rule"] = JUDGE_RULE_VERSION
                changed = True
        elif rule != JUDGE_RULE_VERSION:
            # derived=None(新版規則不認得這個 verdict_class)→ 不蓋章不改 label,
            # 留在 pending_migration 給偵測器可見;蓋了章會變成永久 silent_drift 假陽性
            if derived is not None:
                if derived != stored.get("label"):
                    stored["label"] = derived
                stored["rule"] = JUDGE_RULE_VERSION
                changed = True
    return changed


def append_personal_ledger(entries: list[dict], prices: dict | None = None) -> int:
    """append-only、跨日重跑 idempotent(同 date+ticker+type+verdict+user_hash 不重複寫入,
    因為 build_track_record 每次都重新走訪全部歷史日期)。
    2026-07-12 起外加事實 reconcile:既有列補 ret/chg、rule 蓋章與規則遷移(見 _reconcile_row)。
    有 patch 才整檔原子改寫(tmp+rename,先落 .bak);純新增走 append。git 版控=審計軌跡。
    全程持 flock(改寫引入 read→rewrite→rename 窗口,並發 append 會被無聲蓋掉;帳本唯一
    排程寫者是本腳本+每日鎖,鎖防的是手動跑 build/backfill 與 cron 重疊)。"""
    with open(LEDGER_FILE.parent / (LEDGER_FILE.name + ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return _append_personal_ledger_locked(entries, prices)


def _append_personal_ledger_locked(entries: list[dict], prices: dict | None) -> int:
    # stored_rows 元素=dict(可解析列)或原始字串(不可解析列)。壞行是審計證據:讀入時
    # 跳過=改寫時永久刪除,不對稱;改為原樣穿透到改寫輸出,只告警不消滅。
    stored_rows: list[dict | str] = []
    existing_keys: set[tuple] = set()
    n_bad = 0
    if LEDGER_FILE.exists():
        for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                stored_rows.append(line)
                n_bad += 1
                continue
            stored_rows.append(e)
            existing_keys.add(_ledger_key(e))
    if n_bad:
        print(f"[ledger] WARN: {n_bad} unparseable lines preserved verbatim (查根因,別手刪)",
              file=sys.stderr)

    fresh_by_key: dict[tuple, dict] = {}
    for e in entries:
        fresh_by_key.setdefault(_ledger_key(e), e)

    appended = [e for k, e in fresh_by_key.items() if k not in existing_keys]

    patched = 0
    for stored in stored_rows:
        if isinstance(stored, dict) and \
                _reconcile_row(stored, fresh_by_key.get(_ledger_key(stored)), prices):
            patched += 1

    if patched:
        if LEDGER_FILE.exists():
            shutil.copy2(LEDGER_FILE, LEDGER_FILE.parent / (LEDGER_FILE.name + ".bak"))
        tmp = LEDGER_FILE.parent / (LEDGER_FILE.name + ".tmp")
        all_rows = stored_rows + appended
        tmp.write_text("\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
                                 for r in all_rows) + "\n",
                       encoding="utf-8")
        tmp.replace(LEDGER_FILE)
        print(f"[ledger] reconcile: {patched} rows patched (ret/chg/rule), {len(appended)} appended")
    elif appended:
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(e, ensure_ascii=False) for e in appended) + "\n")
    return len(appended)


def _zero_skill_baseline(records: list[dict], since: str | None = None) -> dict:
    """零技能基線(2026-07-12 H3 方法論修正):hit-rate 對 wait/hold 這種不對稱勝利條件,
    baseline=50% 是錯的虛無假設。正確做法:同宇宙全部可結算 (ticker,date) 的 chg,
    算「無腦全標同一類」的命中率當各類基線。chg 來自帳本存的事實欄(reconcile backfill),
    不需重抓價格。演算法對齊 ~/autonomous/research/verifier_repro_20260712.py R3。"""
    pairs_all: set[tuple] = set()
    chg_by_pair: dict[tuple, float] = {}
    regime_by_pair: dict[tuple, str] = {}
    for r in records:
        if r.get("label") not in ("win", "loss"):
            continue
        d = r.get("date") or ""
        if since and d < since:
            continue
        key = (r.get("ticker"), d)
        pairs_all.add(key)
        if r.get("chg") is not None and key not in chg_by_pair:
            chg_by_pair[key] = r["chg"]
        if r.get("regime") and key not in regime_by_pair:
            regime_by_pair[key] = r["regime"]  # regime 是日級別,同 (ticker,date) 一致
    chgs = list(chg_by_pair.values())
    out: dict = {"n_pairs": len(chgs), "n_pairs_missing_chg": len(pairs_all) - len(chgs)}
    if since:
        out["since"] = since
    if chgs:
        for cls in ("buy", "hold", "sell", "wait"):
            wins = sum(1 for c in chgs if label_from_chg(cls, c, "5d") == "win")
            out[cls] = round(100 * wins / len(chgs), 1)
        # regime-條件化基線(2026-07-13):regime 過濾子集(如 chase_high=buy∩up)的正確虛無假設。
        # up-regime 全市場漲多→buy null 遠高於全 regime 43.4;用全 regime null 會把 up-regime
        # 追高的負 edge 遮蔽掉(kpi_pull era 4b 逐筆按 (regime,verdict_class) 混合取此表)。
        by_regime: dict = {}
        for rg in sorted(set(regime_by_pair.values())):
            rg_chgs = [chg_by_pair[k] for k in chg_by_pair if regime_by_pair.get(k) == rg]
            if not rg_chgs:
                continue
            blk = {"n_pairs": len(rg_chgs)}
            for cls in ("buy", "hold", "sell", "wait"):
                wins = sum(1 for c in rg_chgs if label_from_chg(cls, c, "5d") == "win")
                blk[cls] = round(100 * wins / len(rg_chgs), 1)
            by_regime[rg] = blk
        if by_regime:
            out["by_regime"] = by_regime
    return out


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
        judged = [r for r in records if r.get("label") in ("win", "loss")]
        out = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_total": len(records),
            "rule": JUDGE_RULE_VERSION,
            "a": edge_audit.audit_records([r for r in records if r.get("type") == "A"], group_by="market"),
            "c": edge_audit.audit_records([r for r in records if r.get("type") == "C"], group_by="market"),
            # 各類 hit-rate 的正確對照尺:讀 kpi/audit 時拿同類 baseline 比,不拿 50%
            "baseline": {
                "note": "零技能基線=同宇宙全部可結算(ticker,date)無腦全標同類的命中率(5d);"
                        "wait/hold 勝利條件不對稱,50% 不是正確虛無假設",
                "all_with_chg": _zero_skill_baseline(records),
                "era": _zero_skill_baseline(records, since=MODEL_ERA_START),
            },
            # 標籤新鮮度摘要:legacy_unstamped=舊列 label 與現行規則導出不一致(價格 drift 等),
            # 蓋不了章;數字變大要查(週跑偵測器 ledger_label_freshness 會擋)
            "label_freshness": {
                "n_judged": len(judged),
                "n_rule_current": sum(1 for r in judged if r.get("rule") == JUDGE_RULE_VERSION),
                "n_rule_legacy_unstamped": sum(1 for r in judged if r.get("rule") is None),
                "n_missing_chg": sum(1 for r in judged if r.get("chg") is None),
            },
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
    keys |= _ledger_pairs_missing_chg()
    print(f"[fetch] {len(keys)} (ticker,date) pairs via yfinance (cached where possible)...")
    prices = fetch_prices(keys)

    def _judge_record(r: dict) -> None:
        # type="H"(持有者框架)用 judge_holder,其餘照舊
        jfn = judge_holder if r.get("type") == "H" else judge
        r["outcome"] = jfn(r, prices, "5d")
        r["outcome_1d"] = jfn(r, prices, "1d")
        r["outcome_21d"] = jfn(r, prices, "21d")
        r["outcome_63d"] = jfn(r, prices, "63d")
        # 幅度事實欄(2026-07-23):除 win/loss 外,存各期還原後實際漲跌率(chg),
        # 讓下游能算期望值/少輸多贏(賺賠比),而非只有勝率——勝率無幅度會騙人(見個股訊號回測)。
        # chg 已含窗內現金股息還原(settlement_chg 語義),與 label 同源不再另抓價。
        for _h in ("1d", "5d", "21d", "63d"):
            _c = settlement_chg(r, prices, _h)
            if _c is not None:
                r[f"ret_{_h}"] = round(_c, 4)

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

    spx_closes = yahoo_chart("^GSPC", "", "") or {}
    regime_by_date = fetch_spx_regime(spx_closes)
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
        "by_verdict_overnight": era_overnight_buckets(era_a + era_c, spx_closes),
        "calibration": calibration_stats(era_a),
        "days": len({r["date"] for r in era_a + era_c}),
    }

    # ── 分市場拆分(2026-07-16 台股戰績卡資料層先備:UI 等 Delvin 點頭,先不動前端)──
    # 與頭條同一把尺(5d outcome+Wilson CI),era 子集另附 day-cluster CI(同日相關,Wilson 假獨立會假窄)。
    # 純加法輸出:既有讀取端(track-record.html/kpi_pull/site_scan)都按鍵取值,不受新鍵影響。
    by_market = {}
    for mk in ("tw", "us"):
        ma = [r for r in a_recs if r.get("market") == mk]
        mc = [r for r in c_recs if r.get("market") == mk]
        maw = sum(1 for r in ma if r["outcome"] == "win")
        mcw = sum(1 for r in mc if r["outcome"] == "win")
        ema = [r for r in ma if r["date"] >= MODEL_ERA_START]
        emc = [r for r in mc if r["date"] >= MODEL_ERA_START]
        emaw = sum(1 for r in ema if r["outcome"] == "win")
        emcw = sum(1 for r in emc if r["outcome"] == "win")
        by_market[mk] = {
            "a_count": len(ma), "a_wins": maw,
            "a_rate": round(maw / len(ma) * 100, 1) if ma else 0.0,
            "a_ci95": list(wilson_ci(maw, len(ma))),
            "c_count": len(mc), "c_wins": mcw,
            "c_rate": round(mcw / len(mc) * 100, 1) if mc else 0.0,
            "c_ci95": list(wilson_ci(mcw, len(mc))),
            "era": {
                "since": MODEL_ERA_START,
                "a_count": len(ema), "a_wins": emaw,
                "a_rate": round(emaw / len(ema) * 100, 1) if ema else 0.0,
                "a_ci95_day_cluster": day_cluster_ci(ema),
                "c_count": len(emc), "c_wins": emcw,
                "c_rate": round(emcw / len(emc) * 100, 1) if emc else 0.0,
                "c_ci95_day_cluster": day_cluster_ci(emc),
                "days": len({r["date"] for r in ema + emc}),
            },
        }

    sims = []
    for r in judged_all:
        if r.get("type") == "H":
            continue  # 持有者卡的價位是減碼/停損位,混進「照卡片進場」模擬會失真
        s = simulate_plan(r, prices)
        if s:
            s["date"] = r["date"]
            # 內部明細用(絕不寫入公開 JSON):個股+用戶 token,由 worker 端 token→email 歸戶
            s["_ticker"] = r.get("ticker")
            s["_name"] = r.get("name")
            s["_market"] = r.get("market")
            s["_tok"] = r.get("_user_token") or ""
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
        # 每日模擬報酬序列(內部淨值曲線用):按建議日分組,只有日期+報酬率,無個股/用戶資訊。
        # rets=當日已結束模擬單的報酬%(no_fill/pending 不在內),n_cards=當日全部模擬單(含 no_fill)。
        "by_day": [
            {
                "d": d,
                "n_cards": sum(1 for s in sims if s["date"] == d and s["result"] != "pending"),
                "rets": [s["ret_pct"] for s in sims
                         if s["date"] == d and s.get("ret_pct") is not None],
            }
            for d in sorted({s["date"] for s in sims})
        ],
        # 逐筆已結束模擬單(組合層級資金分配模擬用):c=建議日,e=進場日,x=出場日,ret=報酬%。
        # 無個股/用戶資訊。admin 後台據此做「單筆固定比例+現金池佔用」的真實跟單模擬。
        "trades": sorted(
            [
                {"c": s["date"], "e": s["entry_date"], "x": s["exit_date"], "ret": s["ret_pct"]}
                for s in closed
                if s.get("ret_pct") is not None and s.get("entry_date") and s.get("exit_date")
            ],
            key=lambda t: (t["e"], t["x"]),
        ),
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

    ledger_entries = _personal_ledger_entries(judged_personal, personal_sims, regime_by_date, prices)
    ledger_added = append_personal_ledger(ledger_entries, prices)
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
        "by_market": by_market,  # 分市場拆分(台股戰績卡資料層,2026-07-16)
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

    # 可見清單 = 公版 + 全用戶持股(Delvin 2026-07-14 指令:公開戰績持股一定要全用戶持股)。
    # 舊「隱私策略 A」只輸出 judged_public(7 檔),那 1000+ 筆全用戶個人化建議只餵勝率、被藏起來
    # → 截圖只看到 3 檔台股的病根。現改為把個人化紀錄「匿名去重」後也寫進可見 records。
    # 隱私三閘:①排除持有者框架(H/holder)卡 —— 它含用戶成本價,會間接洩漏誰持有;
    #          ②依 (date,ticker,verdict) 去重 → 呈現「用戶群當天對某股的看法」聚合,非逐用戶;
    #          ③剝除所有內部欄位(_user_token / source_scope 等),絕不輸出任何用戶識別。
    _seen_vis = {(r["date"], r["ticker"], r["verdict_class"]) for r in judged_public}
    visible_personal: list[dict] = []
    for r in judged_personal:
        if r.get("type") == "H" or r.get("holder"):
            continue  # 持有者卡含成本價,不進公開清單
        k = (r["date"], r["ticker"], r["verdict_class"])
        if k in _seen_vis:
            continue
        _seen_vis.add(k)
        clean = {kk: vv for kk, vv in r.items()
                 if not kk.startswith("_") and kk not in ("source_scope", "holder_entry")}
        clean["scope"] = "aggregate"  # 前端可標示為「訂閱者持股聚合」
        visible_personal.append(clean)
    visible_records = judged_public + visible_personal
    visible_records.sort(key=lambda x: (x["date"], x["ticker"]), reverse=True)
    stats["visible_personal_added"] = len(visible_personal)

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
        json.dumps({"stats": stats, "records": visible_records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 內部逐筆明細(含個股+用戶token):寫本地檔,由 winrig 排程 POST 到 worker
    # /internal/plan-trades 歸戶進 KV,admin 後台認證後才看得到。
    # 絕不進公開 JSON、絕不 commit(.gitignore 已擋)。
    tok_user = match_tokens_to_users(personal_records)
    internal_trades = [
        {"c": s["date"], "t": s.get("_ticker"), "name": s.get("_name"),
         "m": s.get("_market"), "e": s.get("entry_date"), "x": s.get("exit_date"),
         "ret": s.get("ret_pct"), "result": s["result"], "tok": s.get("_tok") or "",
         "u": tok_user.get(s.get("_tok") or "")}
        for s in sims if s["result"] != "no_fill"
    ]
    # 每用戶逐卡隔日勝負(用戶勝率統一隔日尺,與戰績頁頭條同一把):每張個人化卡
    # 帶 verdict + 隔日結算結果,供 admin 用戶抽屜算「此用戶日報卡片勝率(隔日)」。
    internal_cards = []
    for r in personal_records:
        internal_cards.append({
            "c": r["date"], "t": r.get("ticker"), "name": r.get("name"),
            "m": r.get("market"), "v": r.get("verdict_class"),
            "o": judge(r, prices, "1d"),  # win/loss/None=待結
            "tok": r.get("_user_token") or "",
            "u": tok_user.get(r.get("_user_token") or ""),
        })
    internal_file = ROOT / "scripts" / "plan_sim_trades_internal.json"
    internal_file.write_text(
        json.dumps({"generated_at": stats["generated_at"], "trades": internal_trades,
                    "cards": internal_cards},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[write] {internal_file} ({len(internal_trades)} trades, "
          f"{len(internal_cards)} cards, internal only)")
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
