#!/usr/bin/env python3
"""
SEO 個股長尾文章自動生成 pipeline
- 每次跑生 5 篇 (default),配合 GitHub Actions weekly cron
- 用 Claude haiku 寫,每篇 ~800-1200 字
- 鎖長尾關鍵字:「<個股名> <主題> 2026」例如「台積電 2330 配息 2026」
- 輸出到 docs/blog/<slug>.html(自包含 HTML 含 MarketDaily 設計系統)
- 自動更新 docs/blog/index.html 列表
- sitemap.xml 自動 append 新文章

用法:
  python scripts/seo_articles.py                 # 預設生 5 篇
  python scripts/seo_articles.py --count 10      # 改 10 篇
  python scripts/seo_articles.py --dry           # 只 print 不寫檔
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"

BLOG_DIR = ROOT / "docs" / "blog"
BLOG_DIR.mkdir(parents=True, exist_ok=True)
SEEDS_FILE = ROOT / "scripts" / "seo_seeds.json"

# 種子主題池 — 每篇文章從這拼湊長尾關鍵字
US_STOCKS = [
    ("NVDA", "輝達"), ("AAPL", "蘋果"), ("TSM", "台積電 ADR"),
    ("MSFT", "微軟"), ("META", "Meta"), ("GOOGL", "Google"),
    ("AMZN", "亞馬遜"), ("TSLA", "特斯拉"), ("AMD", "AMD"),
    ("NFLX", "Netflix"), ("AVGO", "博通"), ("PLTR", "Palantir"),
    ("COIN", "Coinbase"), ("UBER", "Uber"), ("DIS", "迪士尼"),
]
TW_STOCKS = [
    ("2330", "台積電"), ("2454", "聯發科"), ("2317", "鴻海"),
    ("2891", "中信金"), ("2882", "國泰金"), ("0050", "元大台灣50"),
    ("0056", "元大高股息"), ("00878", "國泰永續高股息"),
    ("2603", "長榮"), ("2308", "台達電"), ("3034", "聯詠"),
    ("2412", "中華電"), ("8299", "群聯"), ("3008", "大立光"),
]
TOPICS = [
    "投資前必看 3 個風險",
    "本益比合理嗎",
    "配息政策解析",
    "2026 展望",
    "競爭優勢與護城河",
    "近期財報重點",
    "適合長期持有嗎",
    "技術面 vs 基本面",
    "vs 同業比較",
    "新手第一次買要注意什麼",
]

# 財經名詞教學(2026-07-05 分發瓶頸研究缺口 A:不綁個股,搜尋量最大,合規最安全)
# 每篇 slug 前綴固定為 "term",讓既有 related_html() 自動把全部詞彙文章群聚互連
# (topic cluster 效果,無需額外程式碼)。
TERM_TOPICS = [
    ("本益比 PE Ratio", "本益比是什麼 怎麼看 2026"),
    ("殖利率", "股票殖利率是什麼 怎麼算 2026"),
    ("ROE 股東權益報酬率", "ROE是什麼 好公司標準 2026"),
    ("毛利率與營益率", "毛利率 營業利益率 差別 2026"),
    ("EPS 每股盈餘", "EPS是什麼 怎麼看好壞 2026"),
    ("現金流量表", "現金流量表怎麼看 三大現金流 2026"),
    ("除權息", "除權息是什麼 填權填息 2026"),
    ("融資融券", "融資融券是什麼 差別風險 2026"),
    ("法人買賣超", "法人買賣超是什麼 怎麼看 2026"),
    ("庫藏股", "庫藏股是什麼 對股價影響 2026"),
    ("KD指標", "KD指標是什麼 黃金交叉死亡交叉 2026"),
    ("RSI 相對強弱指標", "RSI是什麼 超買超賣怎麼用 2026"),
    ("布林通道", "布林通道是什麼 怎麼用 2026"),
    ("市值排名", "股票市值是什麼 怎麼算 2026"),
    ("Beta值與系統性風險", "Beta值是什麼 股票風險 2026"),
    ("財報三大報表", "財報怎麼看 損益表資產負債表現金流量表 2026"),
    ("股票分割", "股票分割是什麼 對投資人影響 2026"),
    ("ETF 與個股差異", "ETF跟股票差在哪 適合誰 2026"),
    ("定期定額投資", "定期定額是什麼 適合新手嗎 2026"),
    ("財報公布時間與行事曆", "財報公布時間怎麼查 2026"),
]

# 總經指標教學(2026-07-05 分發瓶頸研究缺口 C:不綁個股/不需即時資料 grounding,
# 與 TERM_TOPICS 同一套零幻覺手法——這些是穩定的教科書定義與機制說明,不涉及會過時的絕對數字,
# 差異在於 TERM_TOPICS 是「公司層級」財務比率/技術指標,這裡是「總體經濟層級」指標,SEO 關鍵字不重疊。
# 每篇 slug 前綴固定為 "macro",讓既有 related_html() 自動把全部總經文章群聚互連。
MACRO_TOPICS = [
    ("CPI 消費者物價指數", "CPI是什麼 通膨怎麼看 2026"),
    ("PMI 採購經理人指數", "PMI是什麼 景氣領先指標 2026"),
    ("GDP 經濟成長率", "GDP是什麼 對股市影響 2026"),
    ("失業率", "失業率是什麼 對股市影響 2026"),
    ("Fed 利率決議與升降息", "Fed升息降息 對股市影響 2026"),
    ("殖利率曲線倒掛", "殖利率曲線倒掛是什麼 景氣衰退訊號 2026"),
    ("景氣對策信號燈", "景氣對策信號燈是什麼 燈號解讀 2026"),
    ("VIX 恐慌指數", "VIX恐慌指數是什麼 怎麼看 2026"),
    ("美元指數 DXY", "美元指數是什麼 對台股影響 2026"),
    ("非農就業報告 NFP", "非農就業數據是什麼 對美股影響 2026"),
    ("台灣中央銀行升降息", "央行升息降息 對台股影響 2026"),
    ("美國10年期公債殖利率", "10年期公債殖利率 對股市影響 2026"),
    ("零售銷售數據", "零售銷售數據是什麼 消費指標 2026"),
    ("ISM 製造業指數", "ISM製造業指數是什麼 景氣訊號 2026"),
    ("消費者信心指數", "消費者信心指數是什麼 對股市影響 2026"),
    ("貨幣供給 M1B 與 M2", "M1B M2是什麼 資金動能指標 2026"),
    ("台股加權指數與費半指數", "台股加權指數 費城半導體指數 關聯 2026"),
    ("通膨預期與抗通膨債券", "通膨預期是什麼 抗通膨債券 2026"),
    ("三大法人期貨未平倉", "期貨未平倉是什麼 法人多空指標 2026"),
    ("財報季與財測", "財報季是什麼 財測怎麼看 2026"),
]

# 產業供應鏈全景(2026-07-05 分發瓶頸研究缺口 D:重用既有 supply_chain.json,
# 66 家已核實公司資料,工程成本最低+零幻覺風險,因資料直接餵給 LLM 當唯一事實來源)
CHAIN_TOPIC = "供應鏈全景:上下游廠商解析"
SUPPLY_CHAIN_FILE = ROOT / "docs" / "data" / "supply_chain.json"
CHAIN_TICKER_ALIAS = {"TSM": "2330.TW"}  # ADR 對應台灣母股資料
CHAIN_SKIP = {"COIN", "2891", "0050", "0056", "00878"}  # ETF 或無 verified 資料,跳過


def _load_chain_db() -> dict:
    try:
        return json.loads(SUPPLY_CHAIN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


CHAIN_DB = _load_chain_db()


def chain_key_for(ticker: str, market: str):
    """把 TOPICS 池的 ticker 對應到 supply_chain.json 的 key,查無資料回傳 None。"""
    if ticker in CHAIN_SKIP:
        return None
    alias = CHAIN_TICKER_ALIAS.get(ticker)
    if alias:
        return alias if alias in CHAIN_DB else None
    if market == "us":
        return ticker if ticker in CHAIN_DB else None
    for suffix in (".TW", ".TWO"):
        key = f"{ticker}{suffix}"
        if key in CHAIN_DB:
            return key
    return None


def slug_of(ticker: str, topic: str) -> str:
    safe = re.sub(r"[^\w一-鿿]+", "-", topic)[:30]
    return f"{ticker.lower()}-{safe}-{datetime.now():%Y%m}"


def load_published() -> set:
    """掃 docs/blog/ 內已存在 slug,避免重複生。"""
    return {f.stem for f in BLOG_DIR.glob("*.html") if f.stem != "index"}


def ticker_of_slug(slug: str) -> str:
    """slug 格式 f"{ticker}-{topic}-{yyyymm}",ticker 本身不含 '-',取第一段即可。"""
    return slug.split("-")[0].lower()


def scan_articles() -> list:
    """掃全部已發布文章,回傳 [{slug, ticker, title}, ...] 供算相關文章用。"""
    out = []
    for f in BLOG_DIR.glob("*.html"):
        if f.stem == "index":
            continue
        try:
            m = re.search(r"<title>(.+?)\s*\|", f.read_text(encoding="utf-8"))
            title = m.group(1) if m else f.stem
        except Exception:
            title = f.stem
        out.append({"slug": f.stem, "ticker": ticker_of_slug(f.stem), "title": title})
    return out


RELATED_BLOCK_OPEN = '<div style="margin:32px 0 0;padding:20px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:14px;">'


def related_html(ticker: str, exclude_slug: str, articles: list) -> str:
    """同代號的其他文章互連,形成 topic cluster;沒有同代號文章就回傳空字串。"""
    same = [a for a in articles if a["ticker"] == ticker.lower() and a["slug"] != exclude_slug]
    if not same:
        return ""
    items = "\n".join(
        f'    <li style="margin:8px 0;"><a href="{a["slug"]}.html" '
        f'style="color:#a5b4fc;text-decoration:none;font-weight:600;">{a["title"]}</a></li>'
        for a in same[:5]
    )
    return f"""  {RELATED_BLOCK_OPEN}
    <p style="font-size:13px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.5px;margin:0 0 10px;">相關文章</p>
    <ul style="margin:0;padding:0;list-style:none;">
{items}
    </ul>
  </div>"""


def reconcile_related_links(dry: bool) -> list:
    """批次寫檔是逐篇即時掃描,同批次挑到同代號的文章只會單向連結(先寫的看不到後寫的)。
    寫檔全部跑完後重掃一次,把每篇文章的「相關文章」區塊校正成雙向一致,不論寫入順序。"""
    articles = scan_articles()
    block_pattern = re.compile(r"[ \t]*" + re.escape(RELATED_BLOCK_OPEN) + r".*?</div>\n?", re.DOTALL)
    cta_marker = '<div class="cta">'
    updated = []
    for a in articles:
        fpath = BLOG_DIR / f"{a['slug']}.html"
        html = fpath.read_text(encoding="utf-8")
        expected = related_html(a["ticker"], a["slug"], articles)
        m = block_pattern.search(html)
        if m:
            if m.group(0).strip() == expected.strip():
                continue
            new_html = html[: m.start()] + (expected + "\n" if expected else "") + html[m.end() :]
        else:
            if not expected or cta_marker not in html:
                continue
            new_html = html.replace(cta_marker, expected + "\n  " + cta_marker, 1)
        updated.append(a["slug"])
        if dry:
            print(f"  [dry] would sync related links: {a['slug']}")
        else:
            fpath.write_text(new_html, encoding="utf-8")
            print(f"  ✓ related links synced: {a['slug']}")
    return updated


def call_claude(system: str, user: str, max_tokens: int = 2000) -> str:
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode(),
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return "".join(c.get("text", "") for c in data.get("content", [])).strip()


SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手。寫繁體中文 SEO 長尾文章。

規則:
- 800-1200 字
- 結構:H1 標題、引言(問題切入)、H2 分段(3-5 個)、結論 + CTA(訂閱 MarketDaily 早報)
- 開頭 80 字內必須出現關鍵字 + 數字(SEO bonus)
- 內容要有實質資訊,不空泛
- **不能保證收益、不能喊進喊出**(改寫成「值得關注」「需評估個人風險」)
- **絕對禁止捏造具體絕對數字**:你沒有即時行情/財報資料,不可寫出任何「股價 XX 元」「EPS XX 元」「配息 XX 元」「每股淨值 XX 元」這類絕對金額數字——這些數字會隨時間變動,寫死幾乎必然是幻覺(曾發生真實案例:文章寫某股「股價 30 元」但實際股價是 141 元)。涉及估值/配息/淨值主題時,只能用**相對描述**:區間型比率(本益比/殖利率/毛利率可講「歷史區間約 X-Y%」)、趨勢方向、或直接請讀者「請查詢券商即時報價與最新財報」,絕不給出看似精確的假絕對金額。
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html 或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可"""


def strip_code_fence(body: str) -> str:
    """防禦層:LLM 有時仍會用 ```html ... ``` 包住輸出,即使 prompt 已禁止,直接砍掉殘留圍欄。"""
    body = body.strip()
    body = re.sub(r"^```(?:html)?\s*\n?", "", body)
    body = re.sub(r"\n?```\s*$", "", body)
    return body.strip()


def gen_article(ticker: str, name: str, topic: str, market: str) -> dict:
    user = f"""寫一篇 SEO 文章。

關鍵字組合:「{name} {ticker} {topic}」
市場:{market}(美股/台股)

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。

回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    # 從 body 抽 H1 當 title
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {topic}"
    return {
        "ticker": ticker,
        "name": name,
        "topic": topic,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": slug_of(ticker, topic),
    }


TERM_SYSTEM = """你是 MarketDaily 的財經知識 SEO 內容寫手。寫繁體中文投資名詞教學文章,面向完全新手。

規則:
- 800-1200 字
- 結構:H1 標題(含關鍵字)、引言(為何這個名詞重要)、H2「定義與計算方式」、H2「怎麼解讀(什麼算好/壞)」、H2「常見誤區」、結論 + CTA
- 開頭 80 字內出現關鍵字
- 舉例只能用**相對描述**(如「本益比通常落在某個區間,產業別而異」),絕對不可捏造任何具體公司的絕對數字(股價/EPS/財報數字)
- 內容要有實質教學價值,像財經媒體的新手教學文,不是空泛定義
- 不能保證收益、不能喊進喊出
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html 或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可"""


def term_slug(term: str) -> str:
    safe = re.sub(r"[^\w一-鿿]+", "-", term)[:30]
    return f"term-{safe}-{datetime.now():%Y%m}"


def gen_term_article(term: str, keyword: str) -> dict:
    user = f"""寫一篇 SEO 投資名詞教學文章。

關鍵字:「{keyword}」
名詞:{term}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(TERM_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else term
    return {
        "ticker": "term",  # 共用同一 pseudo-ticker,讓 related_html() 自動群聚成詞彙叢集
        "name": term,
        "topic": keyword,
        "market": "term",
        "title": title,
        "body_html": body,
        "slug": term_slug(term),
    }


MACRO_SYSTEM = """你是 MarketDaily 的總體經濟 SEO 內容寫手。寫繁體中文總經指標教學文章,面向想看懂新聞財經術語的一般投資人。

規則:
- 800-1200 字
- 結構:H1 標題(含關鍵字)、引言(為何這個指標重要/多久公布一次)、H2「這個指標怎麼算/怎麼公布」、
  H2「怎麼解讀(數字高低代表什麼)」、H2「對台股/美股的傳導機制」、H2「常見誤區」、結論 + CTA
- 開頭 80 字內出現關鍵字
- **這是總經機制教學,不是即時數據快報**:絕對不可寫出任何「目前 CPI 是 X%」「現在利率是 X%」
  「上次數值是 X」這類具體即時數字或日期——這些會隨時間變動,你沒有即時資料,寫死幾乎必然是幻覺。
  只能用**相對描述**討論歷史區間或典型水準(如「消費者物價年增率長期落在某個區間,超過某個區間
  常被視為升息壓力」),並請讀者「請查詢主計總處/官方最新公布數字」取得現在的實際數值
- 內容要有實質教學價值,像財經媒體的總經專欄,不是空泛定義
- 不能保證收益、不能喊進喊出
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html 或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可"""


def macro_slug(indicator: str) -> str:
    safe = re.sub(r"[^\w一-鿿]+", "-", indicator)[:30]
    return f"macro-{safe}-{datetime.now():%Y%m}"


def gen_macro_article(indicator: str, keyword: str) -> dict:
    user = f"""寫一篇 SEO 總經指標教學文章。

關鍵字:「{keyword}」
指標:{indicator}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(MACRO_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else indicator
    return {
        "ticker": "macro",  # 共用同一 pseudo-ticker,讓 related_html() 自動群聚成總經叢集
        "name": indicator,
        "topic": keyword,
        "market": "macro",
        "title": title,
        "body_html": body,
        "slug": macro_slug(indicator),
    }


CHAIN_SYSTEM = """你是 MarketDaily 的產業供應鏈 SEO 內容寫手。寫繁體中文長尾文章,主題是特定公司的供應鏈上下游關係。

規則:
- 800-1200 字
- 結構:H1 標題、引言、H2「上游供應商」、H2「下游客戶」、H2「產業鏈風險與集中度觀察」、結論 + CTA
- **只能使用下方提供的「真實供應鏈資料」裡列出的公司與描述,絕對不可捏造清單以外的公司名稱、角色或數字**——這些是已核實的真實資料,你的任務是把它組織成好讀的文章,不是新增內容
- 可依資料裡的「集中度」描述做質化的風險/替代性觀察,但不可給出任何具體營收占比/股價/財報數字(除非資料本身有提供)
- 不能保證收益、不能喊進喊出
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html 或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期,用「2026」這種年度即可"""


def _chain_grounding_text(entry: dict) -> str:
    mid = entry.get("mid", {})
    lines = [f"公司:{mid.get('name', '')}({entry.get('ticker', '')})"]
    if mid.get("desc"):
        lines.append(f"業務模式:{mid['desc']}")
    lines.append("上游供應商(真實資料,不可新增未列出的公司):")
    for s in entry.get("upstream", []):
        tk = f"({s['ticker']})" if s.get("ticker") else ""
        crit = f"; 集中度:{s['criticality']}" if s.get("criticality") else ""
        lines.append(f"- {s.get('name_zh', '')}{tk}:{s.get('role', '')}{crit}")
    lines.append("下游客戶(真實資料,不可新增未列出的公司):")
    for c in entry.get("downstream", []):
        tk = f"({c['ticker']})" if c.get("ticker") else ""
        lines.append(f"- {c.get('name_zh', '')}{tk}:{c.get('role', '')}")
    return "\n".join(lines)


def gen_chain_article(ticker: str, name: str, market: str, chain_key: str) -> dict:
    entry = CHAIN_DB[chain_key]
    grounding = _chain_grounding_text(entry)
    user = f"""寫一篇 SEO 文章,主題是「{name}({ticker}) {CHAIN_TOPIC}」。

真實供應鏈資料(唯一可用資料來源,不可新增清單以外的公司):
{grounding}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(CHAIN_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {CHAIN_TOPIC}"
    return {
        "ticker": ticker,
        "name": name,
        "topic": CHAIN_TOPIC,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": slug_of(ticker, CHAIN_TOPIC),
    }


# 除權息旺季導覽(2026-07-05 分發瓶頸研究缺口 B:現正7-9月台股除權息旺季,時效性最高;
# 用 FinMind TaiwanStockDividend 真實歷史除息資料當唯一事實來源,同 CHAIN_DB grounding 手法防幻覺。
# 台股專屬機制,只涵蓋 TW_STOCKS,不含美股)
DIVIDEND_TOPIC = "除權息時間與歷史紀錄"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
DIVIDEND_CACHE_FILE = ROOT / "scripts" / ".dividend_cache.json"
DIVIDEND_SKIP = {"0050", "0056", "00878"}  # ETF 配息機制與個股不同(收益平準金等),不適用本文類型


def _fetch_dividend_history(ticker: str) -> list:
    """FinMind TaiwanStockDividend 近 3 年真實除息紀錄(除息日+每股現金股利),只留有實際除息日的筆數。"""
    import urllib.request
    try:
        start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
        url = f"{FINMIND}?dataset=TaiwanStockDividend&data_id={ticker}&start_date={start}"
        if FINMIND_TOKEN:
            url += f"&token={FINMIND_TOKEN}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        rows = []
        for row in data.get("data", []):
            ex_date = row.get("CashExDividendTradingDate") or ""
            cash = row.get("CashEarningsDistribution") or 0
            if ex_date and cash:
                rows.append({
                    "ex_date": ex_date,
                    "cash": round(float(cash), 2),
                    "pay_date": row.get("CashDividendPaymentDate") or "",
                })
        return rows[-6:]
    except Exception:
        return []


def _load_dividend_cache() -> dict:
    try:
        return json.loads(DIVIDEND_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def dividend_history_for(ticker: str) -> list:
    """cache-first(當天內免重打 FinMind API);查無資料回傳空 list,呼叫端需自行跳過。"""
    cache = _load_dividend_cache()
    today = datetime.now().strftime("%Y-%m-%d")
    entry = cache.get(ticker)
    if entry and entry.get("date") == today:
        return entry.get("rows", [])
    rows = _fetch_dividend_history(ticker)
    cache[ticker] = {"date": today, "rows": rows}
    try:
        DIVIDEND_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rows


DIVIDEND_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文除權息主題文章。

規則:
- 800-1200 字
- 結構:H1 標題、引言、H2「除權息是什麼(機制簡介)」、H2「{公司}近年真實除息紀錄」、
  H2「除權息旺季(每年7-9月為主)投資人該注意什麼」、結論 + CTA
- **只能使用下方提供的「真實除息資料」裡列出的日期與金額,絕對不可捏造清單以外的日期/金額,
  也不可推測或杜撰任何未提供的未來除息日期**——這些是 FinMind 官方已核實的歷史資料,你的任務
  是把它組織成好讀的文章並做除權息機制教學,不是新增內容
- 資料集不含「填息天數」,可概念性教學「填息/貼息」是什麼,但**不可捏造這檔股票具體填息花了幾天**
- 不能保證收益、不能喊進喊出
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可,但除息歷史紀錄本身的日期可原樣引用"""


def _dividend_grounding_text(name: str, ticker: str, rows: list) -> str:
    lines = [f"公司:{name}({ticker})", "近年真實除息紀錄(FinMind 官方資料,不可新增未列出的紀錄):"]
    for r in rows:
        pay = r["pay_date"] or "未提供"
        lines.append(f"- 除息日 {r['ex_date']}:每股現金股利 {r['cash']} 元(發放日 {pay})")
    return "\n".join(lines)


def gen_dividend_article(ticker: str, name: str, market: str, rows: list) -> dict:
    grounding = _dividend_grounding_text(name, ticker, rows)
    user = f"""寫一篇 SEO 文章,主題是「{name}({ticker}) {DIVIDEND_TOPIC}」。

{grounding}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(DIVIDEND_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {DIVIDEND_TOPIC}"
    return {
        "ticker": ticker,
        "name": name,
        "topic": DIVIDEND_TOPIC,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": slug_of(ticker, DIVIDEND_TOPIC),
    }


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="/logo-icon.svg">
<link rel="apple-touch-icon" href="/logo-icon.svg">
<title>{title} | MarketDaily</title>
<meta name="description" content="{desc}">
<meta name="facebook-domain-verification" content="ylg7ynhyj5ywyoierjgo7mchqdvbek" />
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://marketdaily.ai/blog/{slug}.html">
<link rel="canonical" href="https://marketdaily.ai/blog/{slug}.html">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background:#0a0a14; color:#e2e8f0; font-family:'Inter','PingFang TC',sans-serif; line-height:1.75; }}
.wrap {{ max-width:720px; margin:0 auto; padding:48px 24px 80px; }}
.topnav {{ position:sticky; top:0; background:rgba(10,10,20,0.85); backdrop-filter:blur(12px); border-bottom:1px solid rgba(255,255,255,0.08); padding:14px 24px; display:flex; justify-content:space-between; align-items:center; z-index:10; }}
.topnav a {{ color:#a5b4fc; text-decoration:none; font-weight:700; }}
.crumb {{ font-size:13px; color:rgba(255,255,255,0.5); margin-bottom:12px; letter-spacing:0.5px; text-transform:uppercase; }}
h1 {{ font-size:36px; font-weight:900; color:#fff; margin:6px 0 24px; letter-spacing:-0.5px; }}
h2 {{ font-size:24px; font-weight:800; color:#fff; margin:36px 0 14px; }}
h3 {{ font-size:18px; font-weight:700; color:#c7d2fe; margin:24px 0 10px; }}
p {{ font-size:16px; color:#cbd5e1; margin:0 0 16px; }}
ul, ol {{ margin:12px 0 20px 24px; }}
li {{ font-size:16px; color:#cbd5e1; margin:8px 0; }}
strong {{ color:#fbbf24; font-weight:700; }}
.cta {{ background:linear-gradient(135deg,rgba(99,102,241,0.15),rgba(168,85,247,0.15)); border:1px solid rgba(99,102,241,0.35); border-radius:14px; padding:24px; margin:40px 0 0; text-align:center; }}
.cta a {{ display:inline-block; margin-top:14px; padding:14px 28px; background:linear-gradient(135deg,#6366f1,#a855f7); color:#fff; font-weight:800; text-decoration:none; border-radius:10px; }}
.disc {{ font-size:12px; color:rgba(255,255,255,0.4); margin-top:32px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.08); }}
</style>
</head>
<body>
<div class="topnav">
  <a href="/">MarketDaily ←</a>
  <a href="/blog/index.html">所有文章</a>
</div>
<article class="wrap">
  <div class="crumb">MARKETDAILY · 個股分析 · {market_label}</div>
  {body}
{related}
  <div class="cta">
    <p style="font-size:18px;color:#fff;font-weight:800;margin:0;">想每天早上 7 點收到這類分析?</p>
    <p style="font-size:14px;color:rgba(255,255,255,0.65);margin:6px 0 0;">免費訂閱 MarketDaily — 美股 + 台股 AI 過濾日報,30 秒讀完。</p>
    <a href="https://marketdaily.ai/?utm_source=blog&utm_medium=cta&utm_campaign=seo_{slug_short}">免費訂閱 →</a>
  </div>
  <p class="disc">本文僅供資訊整理,非投資建議。投資有風險,請評估自身狀況。資料更新:{updated}</p>
</article>
</body>
</html>"""


MARKET_LABELS = {"us": "美股", "tw": "台股", "term": "投資知識", "macro": "總體經濟"}


def write_article(art: dict, dry: bool) -> Path:
    slug = art["slug"]
    fname = BLOG_DIR / f"{slug}.html"
    if art["market"] == "term":
        desc = f"{art['name']} — MarketDaily 投資知識整理。"
    elif art["market"] == "macro":
        desc = f"{art['name']} — MarketDaily 總體經濟指標整理。"
    else:
        desc = f"{art['name']} ({art['ticker']}) {art['topic']} — MarketDaily 整理。"
    related = related_html(art["ticker"], slug, scan_articles())
    html = PAGE_TEMPLATE.format(
        title=art["title"],
        desc=desc,
        slug=slug,
        slug_short=slug[:32],
        market_label=MARKET_LABELS.get(art["market"], "台股"),
        body=art["body_html"],
        related=related,
        updated=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
    )
    if dry:
        print(f"  [dry] {fname.name}({len(html)} bytes)")
        return fname
    fname.write_text(html, encoding="utf-8")
    print(f"  ✓ {fname.name}")
    return fname


def regenerate_blog_index(dry: bool):
    """掃 docs/blog/ 所有文章,生成 index.html 列表頁。"""
    files = sorted(BLOG_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.stem != "index"]
    items = []
    for f in files:
        try:
            m = re.search(r"<title>(.+?)\s*\|", f.read_text(encoding="utf-8"))
            title = m.group(1) if m else f.stem
        except Exception:
            title = f.stem
        items.append({"slug": f.stem, "title": title})

    cards = "\n".join(
        f'<a class="card" href="{it["slug"]}.html"><div class="card-title">{it["title"]}</div>'
        f'<div class="card-meta">→ 閱讀</div></a>'
        for it in items
    ) or '<p style="color:rgba(255,255,255,0.5)">尚無文章。</p>'

    idx_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="/logo-icon.svg">
<link rel="apple-touch-icon" href="/logo-icon.svg">
<title>個股分析文章 | MarketDaily</title>
<meta name="description" content="MarketDaily 個股深度分析,涵蓋美股、台股長尾關鍵字。">
<meta name="facebook-domain-verification" content="ylg7ynhyj5ywyoierjgo7mchqdvbek" />
<link rel="canonical" href="https://marketdaily.ai/blog/index.html">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0a0a14; color:#e2e8f0; font-family:'Inter','PingFang TC',sans-serif; }}
.wrap {{ max-width:880px; margin:0 auto; padding:48px 24px 80px; }}
.topnav {{ padding:14px 24px; display:flex; justify-content:space-between; border-bottom:1px solid rgba(255,255,255,0.08); }}
.topnav a {{ color:#a5b4fc; text-decoration:none; font-weight:700; }}
h1 {{ font-size:32px; font-weight:900; color:#fff; margin-bottom:32px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }}
.card {{ display:block; padding:20px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:14px; text-decoration:none; color:inherit; transition:all 0.15s; }}
.card:hover {{ background:rgba(99,102,241,0.10); border-color:rgba(99,102,241,0.40); transform:translateY(-2px); }}
.card-title {{ font-size:16px; font-weight:700; color:#fff; line-height:1.5; }}
.card-meta {{ font-size:13px; color:#a5b4fc; margin-top:10px; }}
</style>
</head>
<body>
<div class="topnav">
  <a href="/">← MarketDaily</a>
  <a href="/pricing.html">定價</a>
</div>
<div class="wrap">
  <h1>個股分析 · {len(items)} 篇</h1>
  <div class="grid">{cards}</div>
</div>
</body>
</html>"""
    out = BLOG_DIR / "index.html"
    if dry:
        print(f"  [dry] index({len(items)} items)")
    else:
        out.write_text(idx_html, encoding="utf-8")
        print(f"  ✓ index.html ({len(items)} items)")


def pick_term_seeds(count: int, published: set) -> list:
    if count <= 0:
        return []
    import random
    rng = random.Random(int(datetime.now().timestamp()) + 1)
    candidates = list(TERM_TOPICS)
    rng.shuffle(candidates)
    picked = []
    for term, keyword in candidates:
        if term_slug(term) in published:
            continue
        picked.append((term, keyword))
        if len(picked) >= count:
            break
    return picked


def pick_macro_seeds(count: int, published: set) -> list:
    if count <= 0:
        return []
    import random
    rng = random.Random(int(datetime.now().timestamp()) + 4)
    candidates = list(MACRO_TOPICS)
    rng.shuffle(candidates)
    picked = []
    for indicator, keyword in candidates:
        if macro_slug(indicator) in published:
            continue
        picked.append((indicator, keyword))
        if len(picked) >= count:
            break
    return picked


def pick_chain_seeds(count: int, published: set) -> list:
    if count <= 0:
        return []
    import random
    rng = random.Random(int(datetime.now().timestamp()) + 2)
    all_stocks = [(c, n, "us") for c, n in US_STOCKS] + [(c, n, "tw") for c, n in TW_STOCKS]
    seen_keys = set()
    candidates = []
    for code, name, market in all_stocks:
        if code in CHAIN_TICKER_ALIAS:
            continue  # 別名(如 TSM)一律用母股原生 ticker 產文,避免同一份供應鏈資料生出近乎重複的兩篇文章
        key = chain_key_for(code, market)
        if key and key not in seen_keys:
            seen_keys.add(key)
            candidates.append((code, name, market, key))
    rng.shuffle(candidates)
    picked = []
    for code, name, market, key in candidates:
        if slug_of(code, CHAIN_TOPIC) in published:
            continue
        picked.append((code, name, market, key))
        if len(picked) >= count:
            break
    return picked


def pick_dividend_seeds(count: int, published: set) -> list:
    """只在 TW_STOCKS 挑,且即時查 FinMind 確認真的有除息紀錄才收(查無資料的股票不硬湊)。"""
    if count <= 0:
        return []
    import random
    rng = random.Random(int(datetime.now().timestamp()) + 3)
    candidates = [(c, n) for c, n in TW_STOCKS if c not in DIVIDEND_SKIP]
    rng.shuffle(candidates)
    picked = []
    for code, name in candidates:
        if slug_of(code, DIVIDEND_TOPIC) in published:
            continue
        rows = dividend_history_for(code)
        if not rows:
            continue
        picked.append((code, name, "tw", rows))
        if len(picked) >= count:
            break
    return picked


def pick_seeds(count: int, published: set) -> list:
    """從 stocks × topics 配對,挑沒寫過的 N 個。"""
    import random
    rng = random.Random(int(datetime.now().timestamp()))
    combos = []
    for code, name in US_STOCKS:
        for topic in TOPICS:
            combos.append((code, name, topic, "us"))
    for code, name in TW_STOCKS:
        for topic in TOPICS:
            combos.append((code, name, topic, "tw"))
    rng.shuffle(combos)
    picked = []
    for code, name, topic, market in combos:
        slug = slug_of(code, topic)
        if slug in published:
            continue
        picked.append((code, name, topic, market))
        if len(picked) >= count:
            break
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not ANTHROPIC_KEY and not args.dry:
        print("✗ ANTHROPIC_API_KEY missing in .env"); sys.exit(1)

    published = load_published()
    print(f"① 已發布 {len(published)} 篇,挑新主題 ×{args.count}...")
    # 配額:每次最多 1 篇財經名詞教學(缺口A)+ 1 篇供應鏈全景(缺口D)+ 1 篇除權息導覽(缺口B)
    # + 1 篇總經指標教學(缺口C),剩下的名額才給既有個股×主題組合,避免長青池子被單次跑完排擠。
    term_seeds = pick_term_seeds(min(1, args.count), published)
    chain_seeds = pick_chain_seeds(min(1, max(args.count - len(term_seeds), 0)), published)
    remaining = max(args.count - len(term_seeds) - len(chain_seeds), 0)
    dividend_seeds = pick_dividend_seeds(min(1, remaining), published)
    remaining = max(remaining - len(dividend_seeds), 0)
    macro_seeds = pick_macro_seeds(min(1, remaining), published)
    stock_n = args.count - len(term_seeds) - len(chain_seeds) - len(dividend_seeds) - len(macro_seeds)
    stock_seeds = pick_seeds(stock_n, published) if stock_n > 0 else []
    if not term_seeds and not chain_seeds and not dividend_seeds and not macro_seeds and not stock_seeds:
        print("  全部組合都發過了,沒新主題可挑。"); return
    print("② 生成中...")
    for term, keyword in term_seeds:
        print(f"  • 詞彙教學 — {term}")
        try:
            art = gen_term_article(term, keyword)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for code, name, market, chain_key in chain_seeds:
        print(f"  • {market.upper()} {code} {name} — {CHAIN_TOPIC}")
        try:
            art = gen_chain_article(code, name, market, chain_key)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for code, name, market, rows in dividend_seeds:
        print(f"  • {market.upper()} {code} {name} — {DIVIDEND_TOPIC}")
        try:
            art = gen_dividend_article(code, name, market, rows)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for indicator, keyword in macro_seeds:
        print(f"  • 總經教學 — {indicator}")
        try:
            art = gen_macro_article(indicator, keyword)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for code, name, topic, market in stock_seeds:
        print(f"  • {market.upper()} {code} {name} — {topic}")
        try:
            art = gen_article(code, name, topic, market)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    print("③ 校正相關文章雙向連結...")
    reconcile_related_links(args.dry)
    print("④ 更新 blog index...")
    regenerate_blog_index(args.dry)
    print("✓ done")


if __name__ == "__main__":
    main()
