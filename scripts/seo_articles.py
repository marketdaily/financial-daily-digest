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
import subprocess
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

# 新手教學(2026-07-05 分發瓶頸研究缺口 F:與 TERM_TOPICS/MACRO_TOPICS 的差異化角度——
# 那兩組是「單一名詞/指標是什麼」的定義型內容,這裡是「怎麼做/怎麼選/該注意什麼」的流程與決策型內容
# (開戶/下單/資產配置/心理偏誤/檢查清單),鎖定不同搜尋意圖的關鍵字,避免內容重疊稀釋 SEO。
# 每篇 slug 前綴固定為 "guide",讓既有 related_html() 自動把全部新手教學文章群聚互連。
BEGINNER_TOPICS = [
    ("第一次買股票前要準備什麼", "股票新手 第一次買股票 準備什麼 2026"),
    ("新手投資最常犯的5個錯誤", "投資新手 常犯錯誤 2026"),
    ("市價單與限價單怎麼選", "市價單 限價單 怎麼選 2026"),
    ("存股與波段操作,新手適合哪一種", "存股 波段 新手適合哪種 2026"),
    ("資產配置入門:股債比例怎麼抓", "資產配置 股債比例 新手 2026"),
    ("風險承受度自我評估:我適合哪種投資", "風險承受度 評估 適合投資 2026"),
    ("投資與投機的差別:新手該有的心態", "投資 投機 差別 心態 2026"),
    ("複利效果為什麼重要:越早開始投資越好", "複利效果 越早投資越好 2026"),
    ("零股交易是什麼:小額投資新手指南", "零股交易 小額投資 新手 2026"),
    ("多少錢可以開始投資:小資族入門攻略", "多少錢開始投資 小資族 2026"),
    ("基本面技術面籌碼面差在哪:新手選股入門", "基本面 技術面 籌碼面 差別 新手 2026"),
    ("停損與停利怎麼設:新手風險管理入門", "停損 停利 怎麼設 新手 2026"),
    ("常見投資心理偏誤:定錨效應與處置效應", "投資心理偏誤 定錨效應 處置效應 2026"),
    ("第一次買股票前的檢查清單", "買股票前 檢查清單 新手 2026"),
    ("緊急預備金該存多少才能開始投資", "緊急預備金 開始投資 多少 2026"),
    ("追高殺低的心理陷阱:新手如何避免", "追高殺低 心理陷阱 新手 如何避免 2026"),
    ("投資新手該追蹤哪些財經資訊來源", "投資新手 財經資訊來源 怎麼選 2026"),
    ("複委託與海外券商差在哪:美股投資新手指南", "複委託 海外券商 差別 美股新手 2026"),
    ("新手常見QA:零股划算嗎 股利怎麼領", "新手投資QA 零股 股利 2026"),
    ("證券開戶要準備什麼文件:新手開戶流程", "證券開戶 準備文件 流程 新手 2026"),
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


def backfill_beacon(dry: bool) -> list:
    """對 docs/blog/ 全部 html 注入 attribution beacon(缺 marker 才注入,冪等)。
    新文章走 PAGE_TEMPLATE 的 {beacon} 已自帶;此函式負責①beacon 上線前就存在的舊文章
    ②任何未來手動落檔遺漏的檔案。以 BEACON_MARKER 判存在→已有即 no-op,可安全重跑。"""
    injected = []
    for f in BLOG_DIR.glob("*.html"):
        html = f.read_text(encoding="utf-8")
        if BEACON_MARKER in html:
            continue
        if "</body>" not in html:
            continue
        slug = "blog-index" if f.stem == "index" else f.stem
        new_html = html.replace("</body>", beacon_for(slug) + "\n</body>", 1)
        injected.append(f.stem)
        if dry:
            print(f"  [dry] would inject beacon: {f.name}")
        else:
            f.write_text(new_html, encoding="utf-8")
            print(f"  ✓ beacon injected: {f.name}")
    return injected


OG_MARKER = 'property="og:image"'


def _inject_schema_image(html: str, image: str) -> str:
    """把 image 加進既有 JSON-LD Article schema(冪等,robust via json)。抽不到就原樣返回。"""
    m = re.search(r'(<script type="application/ld\+json">)(.*?)(</script>)', html, re.S)
    if not m:
        return html
    try:
        data = json.loads(m.group(2))
    except Exception:
        return html
    if isinstance(data, dict) and "image" not in data:
        data["image"] = [image]
        new_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        return html[:m.start(2)] + new_json + html[m.end(2):]
    return html


def backfill_og_cards(dry: bool) -> list:
    """對 docs/blog/ 全部既有文章補社群卡(og:image + twitter:card + schema image)。
    冪等:已含 og:image 即 no-op,可安全重跑;產卡失敗個別文章 fallback 站台預設 og.png。
    新文章走 PAGE_TEMPLATE 已自帶,此函式只補 og:image 上線前的舊文。"""
    done = []
    for f in BLOG_DIR.glob("*.html"):
        if f.stem == "index":
            continue
        html = f.read_text(encoding="utf-8")
        if OG_MARKER in html:
            continue
        tm = re.search(r"<title>(.+?)\s*\|", html)
        title = tm.group(1) if tm else f.stem
        dm = re.search(r'<meta name="description" content="([^"]*)"', html)
        desc = dm.group(1) if dm else title
        cm = re.search(r"個股分析 · ([^<]+?)</div>", html)
        market_label = cm.group(1).strip() if cm else "台股"
        ticker = ticker_of_slug(f.stem)
        og_image = og_image_for(f.stem, ticker, market_label, title)
        block = (
            f'<meta property="og:site_name" content="MarketDaily">\n'
            f'<meta property="og:image" content="{og_image}">\n'
            f'<meta property="og:image:width" content="1200">\n'
            f'<meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{title}">\n'
            f'<meta name="twitter:description" content="{desc}">\n'
            f'<meta name="twitter:image" content="{og_image}">'
        )
        if '<link rel="canonical"' in html:
            html2 = re.sub(r'(<link rel="canonical"[^>]*>)', block + r"\n\1", html, count=1)
        else:
            html2 = html.replace("</title>", "</title>\n" + block, 1)
        html2 = _inject_schema_image(html2, og_image)
        done.append(f.stem)
        if dry:
            print(f"  [dry] would add og card: {f.name}")
        else:
            f.write_text(html2, encoding="utf-8")
            print(f"  ✓ og card: {f.name}")
    return done


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


BEGINNER_SYSTEM = """你是 MarketDaily 的新手投資教育 SEO 內容寫手。寫繁體中文投資新手入門教學文章,面向完全沒有投資經驗、正準備跨出第一步的讀者。

規則:
- 800-1200 字
- **這是新手引導文,不是名詞定義文**:重點在「怎麼做/怎麼選/該注意什麼」的實務引導(可用清單/步驟/比較角度),不要退化成單一財務比率或總經指標的定義教學——那類主題本站已有其他系列文章涵蓋,若發現主題其實只是在解釋一個名詞,請改用更寬的流程/決策/心法角度切入
- 結構:H1 標題(含關鍵字)、引言(從新手常見困惑或痛點切入)、H2 分 2-4 段實務引導、H2「常見誤區」、結論 + CTA
- 開頭 80 字內出現關鍵字
- 絕對禁止捏造具體絕對數字(股價/手續費費率/報酬率)、不得推薦或點名特定券商/App/投顧——若需比較不同帳戶類型(如複委託 vs 海外券商)只講概念性差異(稅務/幣別/交易時間等),不列具體費率數字,一律建議讀者「洽詢所屬證券商/查詢官方最新公告」取得現在的實際條件
- 不能保證收益、不能喊進喊出
- 語氣友善、鼓勵,像帶新手入門的導師,不是空泛的百科定義
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html 或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可"""


def beginner_slug(topic: str) -> str:
    safe = re.sub(r"[^\w一-鿿]+", "-", topic)[:30]
    return f"guide-{safe}-{datetime.now():%Y%m}"


def gen_beginner_article(topic: str, keyword: str) -> dict:
    user = f"""寫一篇 SEO 投資新手入門教學文章。

關鍵字:「{keyword}」
主題:{topic}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(BEGINNER_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else topic
    return {
        "ticker": "guide",  # 共用同一 pseudo-ticker,讓 related_html() 自動群聚成新手教學叢集
        "name": topic,
        "topic": keyword,
        "market": "guide",
        "title": title,
        "body_html": body,
        "slug": beginner_slug(topic),
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
STOCKNAME_CACHE_FILE = ROOT / "scripts" / ".stockname_cache.json"


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


# 財報/法說會事件反應文(2026-07-05 分發瓶頸研究缺口 E:唯一需要事件觸發的類型。
# intel/tw_investor_conf.py(法說會排程)+ intel/tw_investor_materials.py(PDF重點摘要,本機Ollama)
# 兩個既有信息差引擎連接器已是現成觸發器,本類型只是把它們接進部落格管線——現況(缺口研究原話)是
# 隨機週抽,錯過新鮮度窗口;改成「這週誰有真實法說會事件落在時效窗口內,就優先寫這家」。
# 台股專屬(法說會連接器資料源僅台股),只涵蓋 TW_STOCKS;ticker 用真實代號(非 pseudo-ticker),
# 讓 related_html() 把事件文章自動併入該檔既有的 chain/dividend/主題文章 cluster。
EVENT_SKIP = {"0050", "0056", "00878"}  # ETF 無公司法說會
EVENT_WINDOW_PAST_DAYS = 10   # 已召開10天內:PDF材料通常已上傳,值得回顧重點
EVENT_WINDOW_FUTURE_DAYS = 20  # 即將召開20天內:值得前瞻提醒
EVENT_TOPIC_HIGHLIGHT = "法說會重點解讀"
EVENT_TOPIC_ADVANCE = "法說會前哨:已揭露重點"
EVENT_TOPIC_PREVIEW = "法說會前瞻"
EVENT_TOPIC_RECAP_GENERIC = "法說會回顧"

# ⚠️2026-07-05 驗證者分離抓到的真實bug教訓:「有沒有PDF材料」跟「這場法說會是否已經召開」是
# 兩件獨立的事——券商邀約的海外巡迴說明會常常沿用稍早既有簡報(檔名日期可能是更早那次法說會的),
# 即使 days_until 還是正數(尚未召開),PDF 材料也可能已經存在。原本只用 `if materials` 二分,
# 會讓「即將召開但已有舊材料」的案例被寫成「已經召開/已經公布」的過去式語氣,對讀者是錯誤時態。
# 改成 (is_past × has_materials) 四象限,各自對應正確時態的 system prompt。

EVENT_HIGHLIGHT_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文法說會重點解讀文章。

情境:這場法說會**已經召開過**,你有真實的簡報重點可引用。

規則:
- 800-1200 字
- 結構:H1 標題、引言(這場法說會為何值得關注)、H2「法說會重點摘要」(逐條整理下方提供的真實重點)、
  H2「這類重點對投資人的意義」(概念性教學,不做買賣建議)、結論 + CTA
- **只能使用下方提供的「真實法說會重點」內容,絕對不可新增清單以外的具體數字/展望/保證**——這些重點
  是從公司官方法說會簡報 PDF 抽取整理,你的任務是把它組織成好讀的文章並做意義解讀,不是新增內容
- 不能保證收益、不能喊進喊出,不做買賣建議
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時)用「2026」這種年度即可,但法說會日期本身可原樣引用"""

EVENT_ADVANCE_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文文章。

情境:某公司**即將**召開法人說明會(尚未舉行),但市場上已有一份公司先前公開揭露的簡報資料流通
(常見於券商邀約的海外巡迴說明會,沿用稍早既有簡報)。

規則:
- 800-1200 字
- **時態務必正確**:這場法說會**尚未召開**,絕對不可寫成「已經公布」「本次說明會公布了」這類
  過去式語氣;下方提供的重點是公司**先前已公開揭露**的資料內容,請用「公司已公開的資料顯示」
  「先前已揭露」這類語氣,並清楚說明即將召開的這場法說會日期,建議讀者屆時查詢正式紀錄確認
  是否有更新內容
- 結構:H1 標題、引言(即將召開的法說會+已公開資料的背景)、H2「已公開的重點摘要」(逐條整理
  下方提供的真實重點,用「已公開揭露」語氣,不可暗示是本場即將召開的會議才公布的新內容)、
  H2「這類重點對投資人的意義」(概念性教學,不做買賣建議)、結論 + CTA
- **只能使用下方提供的「真實已公開重點」內容,絕對不可新增清單以外的具體數字/展望/保證**
- 不能保證收益、不能喊進喊出,不做買賣建議
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時)用「2026」這種年度即可,但法說會日期本身可原樣引用"""

EVENT_PREVIEW_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文法說會前瞻文章。

情境:某公司**即將**召開法人說明會(尚未舉行),且目前查無可引用的公開簡報重點。

規則:
- 800-1200 字
- 結構:H1 標題、引言(這場法說會的時間與背景)、H2「法人說明會通常會揭露什麼」(概念性教學:營運成果/
  展望/產能利用率等常見揭露項目,不針對這家公司杜撰具體內容)、H2「投資人該怎麼準備」、結論 + CTA
- 下方只提供「真實排程資訊」(公司/日期/主旨),**沒有提供具體財報數字或展望內容**——絕對不可自行
  杜撰這場法說會會公布的具體數字或結論,只能就法說會這類活動的一般性質做教學,需要提到本次細節處
  請讀者「屆時查詢公開資訊觀測站或公司官網取得正式內容」
- 不能保證收益、不能喊進喊出,不做買賣建議
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時)用「2026」這種年度即可,但法說會排程日期本身可原樣引用"""

EVENT_RECAP_GENERIC_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文文章。

情境:某公司的法人說明會**已經召開**,但目前查無公開簡報摘要內容可引用。

規則:
- 800-1200 字
- **時態務必正確**:這場法說會已經召開,行文請用過去式描述時間背景,但**絕對不可杜撰**這場
  會議實際公布的任何具體數字/結論(你沒有這場會議的簡報內容)
- 結構:H1 標題、引言(這場法說會已於何時召開)、H2「法人說明會通常會揭露什麼」(概念性教學,
  不針對這家公司杜撰具體內容)、H2「怎麼查詢這場法說會的正式內容」、結論 + CTA
- 明確請讀者「查詢公開資訊觀測站或公司官網取得正式簡報內容」
- 不能保證收益、不能喊進喊出,不做買賣建議
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時)用「2026」這種年度即可,但法說會日期本身可原樣引用"""


def event_slug(code: str, date_start: str) -> str:
    return f"{code.lower()}-event-{date_start.replace('-', '')}"


def _event_highlight_grounding_text(name: str, code: str, conf_entry: dict, materials: dict) -> str:
    lines = [
        f"公司:{name}({code})",
        f"法說會日期:{conf_entry['date_start']}",
        f"主旨:{conf_entry.get('subject', '')}",
        "真實法說會重點(從官方簡報PDF抽取整理,不可新增未列出的重點):",
    ]
    for h in materials.get("highlights", []):
        lines.append(f"- {h}")
    if materials.get("has_guidance"):
        lines.append("(本次簡報含公司對未來展望的說明,但具體數字仍以上列重點為準,不可延伸推測)")
    return "\n".join(lines)


def _event_advance_grounding_text(name: str, code: str, conf_entry: dict, materials: dict) -> str:
    days_until = conf_entry["days_until"]
    lines = [
        f"公司:{name}({code})",
        f"即將召開的法說會日期:{conf_entry['date_start']}({days_until}天後,尚未召開)",
        f"主旨:{conf_entry.get('subject', '')}",
        "公司先前已公開揭露的重點內容(從已公開簡報PDF抽取整理,不可新增未列出的重點,"
        "也不可宣稱這是本場即將召開法說會才公布的新內容):",
    ]
    for h in materials.get("highlights", []):
        lines.append(f"- {h}")
    if materials.get("has_guidance"):
        lines.append("(該資料含公司對未來展望的說明,但具體數字仍以上列重點為準,不可延伸推測)")
    return "\n".join(lines)


def _event_preview_grounding_text(name: str, code: str, conf_entry: dict) -> str:
    days_until = conf_entry["days_until"]
    timing = f"已於{-days_until}天前召開" if days_until < 0 else f"{days_until}天後召開"
    return (
        f"公司:{name}({code})\n"
        f"法說會日期(真實排程,MOPS官方資料):{conf_entry['date_start']}({timing})\n"
        f"主旨:{conf_entry.get('subject', '')}"
    )


def gen_event_article(code: str, name: str, market: str, conf_entry: dict, materials: dict) -> dict:
    is_past = conf_entry["days_until"] < 0
    if materials and is_past:
        grounding = _event_highlight_grounding_text(name, code, conf_entry, materials)
        system, topic = EVENT_HIGHLIGHT_SYSTEM, EVENT_TOPIC_HIGHLIGHT
    elif materials:
        grounding = _event_advance_grounding_text(name, code, conf_entry, materials)
        system, topic = EVENT_ADVANCE_SYSTEM, EVENT_TOPIC_ADVANCE
    elif is_past:
        grounding = _event_preview_grounding_text(name, code, conf_entry)
        system, topic = EVENT_RECAP_GENERIC_SYSTEM, EVENT_TOPIC_RECAP_GENERIC
    else:
        grounding = _event_preview_grounding_text(name, code, conf_entry)
        system, topic = EVENT_PREVIEW_SYSTEM, EVENT_TOPIC_PREVIEW
    user = f"""寫一篇 SEO 文章,主題是「{name}({code}) {topic}」。

{grounding}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(system, user, max_tokens=3000)
    body = strip_code_fence(body)
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {topic}"
    return {
        "ticker": code,
        "name": name,
        "topic": topic,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": event_slug(code, conf_entry["date_start"]),
    }


def pick_event_seeds(count: int, published: set) -> list:
    """掃 TW_STOCKS 有沒有真實法說會事件落在時效窗口內(已召開10天內或即將召開20天內);
    查無時效內事件就回傳空 list,不硬湊(同 pick_dividend_seeds 紀律)。"""
    if count <= 0:
        return []
    try:
        from intel.tw_investor_conf import scan as conf_scan
        from intel.tw_investor_materials import fetch_materials
    except Exception:
        return []
    codes = [c for c, n in TW_STOCKS if c not in EVENT_SKIP]
    name_of = dict(TW_STOCKS)
    try:
        by_code = conf_scan(codes)
    except Exception:
        return []
    windowed = []
    for code, entry in by_code.items():
        d = entry.get("days_until")
        if d is None:
            continue
        if -EVENT_WINDOW_PAST_DAYS <= d <= EVENT_WINDOW_FUTURE_DAYS:
            windowed.append((code, entry))
    windowed.sort(key=lambda x: abs(x[1]["days_until"]))  # 離現在最近的事件優先
    picked = []
    for code, entry in windowed:
        slug = event_slug(code, entry["date_start"])
        if slug in published:
            continue
        name = name_of.get(code, code)
        materials = None
        if entry.get("pdf_zh") or entry.get("pdf_en"):
            materials = fetch_materials(code, name, entry)
        picked.append((code, name, "tw", entry, materials))
        if len(picked) >= count:
            break
    return picked


# 訊號匯流觀察文(2026-07-07 深研究夜課產出路線1,backlog.md P2.6,SEO第7種文章類型)。
# 2026-07-06 opus 深攻輪 confluence_analysis.py 驗證結論:多個正交籌碼訊號同日在同一檔股票
# 共振(4541 晟田案例)統計上 verdict=inconclusive——within-stock 配對控制後 pooled |CAR| 優勢
# 崩潰,整合免費層籌碼訊號不製造 edge(memory capability_signal_confluence_validation.md)。
# 這篇文章的定位因此**只能是質化案例觀察/公開資訊整理教學**,不可包裝成「訊號共振=更準」的
# 統計背書——這是本類型與其餘六種類型最大的差異:其餘六種在講事實(法說會/除息/供應鏈),
# 這種是在講「多個免費公開資料源剛好同時亮」這件事本身,措辭稍不慎極易滑向暗示 predictive
# power,故唯獨本類型在 gen_confluence_article() 內建 confluence_lint() 當出版前防線
# (其他六型的「不做買賣建議」只寫在 system prompt,沒有自動掃描複查 LLM 有沒有真的遵守)。
# 只在 intel/briefs/latest.json::by_code 當日 confluence degree(同日不同 connector 數)≥3
# 才觸發,查無就回傳空 list 不硬湊(同 pick_event_seeds/pick_dividend_seeds 紀律)。
CONFLUENCE_TOPIC = "多方籌碼訊號同日觀察"
CONFLUENCE_MIN_DEGREE = 3

# 窄義禁詞:單獨出現即違規,不需要上下文佐證。
# 2026-07-07 獨立驗證子代理實測抓到原版清單容易被繞過(如「值得投資人偏多留意」「命中率
# 相當高」「過去案例中偏多力道通常延續」全部零命中),已補上這些真實測出的變體詞。
CONFLUENCE_FORBIDDEN_PHRASES = [
    "建議買進", "建議賣出", "建議加碼", "建議減碼", "目標價",
    "看好後市", "看壞後市", "保證獲利", "穩賺", "勝率", "必漲", "必跌",
    "命中率", "上漲機率", "下跌機率", "操作上建議", "值得偏多", "值得偏空",
    "偏多留意", "偏空留意", "力道通常延續", "力道通常會延續", "力道有望延續",
]

# 「看多/看空」單獨出現常是中性教學用語(定義融資=投資人看多後市的槓桿工具/融券=投資人
# 看空後市的放空工具,CONFLUENCE_SYSTEM 明確要求教這段),原版無條件禁用會誤傷這段教學內容
# (2026-07-07 獨立驗證子代理實測「融資是投資人看多後市時的槓桿工具」被誤判)。改成只在
# 同一句子也出現「方向性語境詞」(暗示這是在對這檔股票/操作下判斷,而非定義名詞)才算違規,
# 同 marketing_compliance_lint 的 BROAD_SENSITIVE_PHRASES+PREMIUM_GATING_MARKERS
# co-occurrence 設計。
CONFLUENCE_BROAD_PHRASES = ["看多", "看空", "偏多操作", "偏空操作"]
# 注意:「後市」不可放進這份清單——「看多後市/看空後市」是定義融資/融券時的標準固定搭配
# 本身,放進去會讓中性教學句永遠共現觸發,等於變相恢復無條件禁用(2026-07-07 修復時實測
# 抓到這個自我矛盾,已排除)。context marker 只留「明確指向這檔股票/具體操作」的詞。
CONFLUENCE_DIRECTIONAL_CONTEXT_MARKERS = ["此股", "該股", "本檔", "這檔", "操作上", "建議"]

# 誠實揭露檢查拆兩部分、需同時滿足,而非「任一詞出現在文中任何位置即通過」——原版只查單一
# 清單裡任一詞,「僅供參考」這種每篇文章都可能出現的通用免責語即可誤過關,即使文章完全沒有
# 交代「內部曾回測、結果顯示無edge」這個實質內容(2026-07-07 獨立驗證子代理實測重現此漏洞)。
CONFLUENCE_HONESTY_TESTED_MARKERS = [
    "回測", "歷史回測", "历史回测", "歷史數據", "历史数据", "歷史資料", "历史资料",
    "內部測試", "内部测试", "歷史驗證", "历史验证",
]
CONFLUENCE_HONESTY_NEGATION_MARKERS = [
    "不具備", "不具备", "不代表", "非預測", "非预测", "不保證", "不保证",
    "未必", "不必然", "沒有可驗證", "没有可验证",
]


def _confluence_sentences(html: str) -> list:
    """粗略切句(換行/中文句尾標點當邊界),供 CONFLUENCE_BROAD_PHRASES 的同句共現判斷用;
    不追求語法正確,只要邊界大致合理即可(同 marketing_compliance_lint 逐行掃描的精神)。"""
    return re.split(r"[\n。!!??]", html)


def confluence_lint(body_html: str) -> list:
    """回傳違規清單(空 list=通過)。規則見 CONFLUENCE_SYSTEM——這是本專案唯一「有沒有
    statistical edge」本身就是內容核心的類型,LLM 若照抄類似案例常見寫法很容易滑向暗示
    預測力,故加自動掃描當出版前硬性防線(其他六型只在 system prompt 交代,無自動複查)。
    ~/autonomous capabilities/narrative_compliance_lint 會 import 本函式對已發布文章
    做 post-hoc 複查(防手動編輯或未來程式繞過此 gate),單一來源在此,不重複定義規則。
    跟 marketing_compliance_lint 一樣,這是關鍵詞掃描不是語意理解,無法對抗任意創意寫法,
    只能拉高常見繞過寫法的門檻——誤判請人工複查再決定是否調整清單。"""
    violations = []
    for phrase in CONFLUENCE_FORBIDDEN_PHRASES:
        if phrase in body_html:
            violations.append(f"forbidden:{phrase}")
    for sent in _confluence_sentences(body_html):
        for phrase in CONFLUENCE_BROAD_PHRASES:
            if phrase in sent and any(m in sent for m in CONFLUENCE_DIRECTIONAL_CONTEXT_MARKERS):
                tag = f"forbidden_broad:{phrase}"
                if tag not in violations:
                    violations.append(tag)
    has_tested = any(m in body_html for m in CONFLUENCE_HONESTY_TESTED_MARKERS)
    has_negation = any(m in body_html for m in CONFLUENCE_HONESTY_NEGATION_MARKERS)
    if not (has_tested and has_negation):
        violations.append("missing_honesty_disclosure")
    return violations


CONFLUENCE_SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手,寫繁體中文「多方籌碼訊號同日觀察」文章。

情境:某檔股票在同一天,有多個各自獨立的免費公開籌碼資訊來源(法人買賣超/融資融券/借券賣出/
大戶持股分散/法說會排程等)同時出現訊號。這是**真實發生過的公開資訊巧合**,你的任務是把它
整理成好讀的案例觀察文,而不是宣稱這種巧合本身能預測股價。

**規則(違反任何一條都會被自動掃描退回,務必遵守)**:
- 絕對禁止使用:「建議買進」「建議賣出」「建議加碼」「建議減碼」「目標價」「看好後市」
  「看壞後市」「保證獲利」「穩賺」「勝率」「必漲」「必跌」「命中率」,以及任何暗示這種
  同日巧合「準/靈驗/力道會延續」的說法——這些字眼暗示你在做投資建議或預測,你不是
- 「看多」「看空」只能用於中性定義融資(投資人看多後市時使用的槓桿工具)/融券(投資人
  看空後市時使用的放空工具)這類概念性教學,**絕對不可用來對這檔股票本身、或建議讀者
  操作上偏多/偏空**(例如「此股操作上建議看多」這類句子絕對禁止出現)
- 文中必須同時包含①任一提及「這是根據歷史數據/回測結果」的說法(如「回測」「歷史數據」
  「內部測試」)②任一明確的負面用詞(如「不具備」「不代表」「非預測」「不保證」「未必」)
  ——完整意思:MarketDaily 內部曾用歷史數據回測「多個籌碼訊號同日出現」是否比單一訊號更準,
  結果顯示統計上**不具備**可驗證的優勢,這種同日多訊號巧合很可能只是反映該股票當下波動度
  較高、被更多資料源同時捕捉到,而非精準預測。**只寫「僅供參考」這種通用免責語不夠**,
  必須明確交代「內部曾用歷史數據測過,結果是沒有可驗證的優勢」這個實質內容
- 只能使用下方提供的「真實訊號」內容,絕對不可新增清單以外的具體數字或方向性推論
- 800-1200 字,結構:H1 標題、引言(這檔股票今天有哪些公開資訊同時亮起)、H2「今日同時出現的
  訊號」(逐條整理下方提供的真實訊號原文)、H2「這類同日巧合該怎麼解讀」(納入上述誠實揭露,
  說明這是案例觀察而非預測工具)、H2「這類公開籌碼資訊各自代表什麼」(概念性教學:法人買賣超/
  融資融券/借券賣出/大戶持股分別反映哪種市場參與者行為)、結論 + CTA
- 不能保證收益、不能喊進喊出,不做買賣建議,不使用感嘆號堆疊的煽動語氣
- 結尾 CTA:「想每天早上 7 點收到這類公開資訊整理?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝,也不要用 ```html
  或 ``` 包住輸出(直接輸出 HTML 標籤本身)
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時)用「2026」這種年度即可,但訊號發生日期本身可原樣引用"""


def confluence_slug(code: str, date: str) -> str:
    return f"{code.lower()}-confluence-{date.replace('-', '')}"


def _confluence_grounding_text(name: str, code: str, date: str, entries: list) -> str:
    lines = [
        f"公司:{name}({code})",
        f"日期:{date}",
        f"同日獨立來源數:{len(set(e.get('source') for e in entries))}",
        "真實訊號(逐條列出,不可新增清單以外的內容):",
    ]
    for e in sorted(entries, key=lambda e: e.get("source") or ""):
        lines.append(f"- [{e.get('source')}] {e.get('signal')}")
    return "\n".join(lines)


def gen_confluence_article(code: str, name: str, market: str, date: str, entries: list) -> dict:
    grounding = _confluence_grounding_text(name, code, date, entries)
    user = f"""寫一篇 SEO 文章,主題是「{name}({code}) {CONFLUENCE_TOPIC}」。

{grounding}

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。
回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(CONFLUENCE_SYSTEM, user, max_tokens=3000)
    body = strip_code_fence(body)
    violations = confluence_lint(body)
    if violations:
        raise ValueError(f"confluence_lint 未通過(拒絕出版): {violations}")
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {CONFLUENCE_TOPIC}"
    return {
        "ticker": code,
        "name": name,
        "topic": CONFLUENCE_TOPIC,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": confluence_slug(code, date),
    }


def _load_latest_brief() -> dict:
    try:
        return json.loads((ROOT / "intel" / "briefs" / "latest.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fetch_clean_stock_name(code: str) -> str:
    """FinMind TaiwanStockInfo 官方股票簡稱——cb_database 內部追蹤名常帶 CB 系列編號
    (如「宏致四」「至上11」指該公司第 N 次可轉債發行),不適合當公開文章的公司名稱。"""
    import urllib.request
    try:
        url = f"{FINMIND}?dataset=TaiwanStockInfo&data_id={code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read().decode()).get("data", [])
        for row in rows:
            if row.get("stock_id") == code and row.get("stock_name"):
                return row["stock_name"]
        return ""
    except Exception:
        return ""


def clean_stock_name(code: str, fallback: str) -> str:
    """cache-first(同天內免重打 FinMind API);查無資料退回 fallback(cb_database 內部追蹤名)。"""
    try:
        cache = json.loads(STOCKNAME_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    today = datetime.now().strftime("%Y-%m-%d")
    entry = cache.get(code)
    if entry and entry.get("date") == today:
        return entry.get("name") or fallback
    name = _fetch_clean_stock_name(code)
    cache[code] = {"date": today, "name": name}
    try:
        STOCKNAME_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return name or fallback


def pick_confluence_seeds(count: int, published: set) -> list:
    """掃 intel/briefs/latest.json::by_code,同日 confluence degree(獨立 connector 數)≥3
    才觸發;查無就回傳空 list,不硬湊(同 pick_event_seeds 紀律)。degree 高的優先。

    `intel/briefs/latest.json` 是跨子系統邊界的資料(夜間 patrol.py cron 產出,15 個
    connector 任一個未來改版都可能寫出非預期 schema)——2026-07-07 獨立驗證子代理指出
    原版對格式異常(entries 非 list、entry 非 dict、缺 source 欄位)沒有防呆,會讓
    AttributeError 逃出這支函式、越過 main() 唯一的 per-article try/except,砍掉當週
    整批文章生成(不只 confluence 這一種類型陪葬)。故對每個 code 的資料逐一防呆,壞掉的
    code 直接跳過而非讓整個函式炸掉。"""
    if count <= 0:
        return []
    brief = _load_latest_brief()
    date = brief.get("date")
    by_code = brief.get("by_code")
    if not date or not isinstance(by_code, dict) or not by_code:
        return []
    try:
        from intel.patrol import build_watchlist
        wl = build_watchlist()
    except Exception:
        wl = {}
    candidates = []
    for code, entries in by_code.items():
        if not isinstance(entries, list):
            continue
        valid_entries = [e for e in entries if isinstance(e, dict) and e.get("source") and e.get("signal")]
        sources = set(e["source"] for e in valid_entries)
        if len(sources) < CONFLUENCE_MIN_DEGREE:
            continue
        if confluence_slug(code, date) in published:
            continue
        candidates.append((len(sources), code, valid_entries))
    candidates.sort(key=lambda x: -x[0])
    picked = []
    for _, code, entries in candidates:
        name = clean_stock_name(code, wl.get(code) or code)
        picked.append((code, name, "tw", date, entries))
        if len(picked) >= count:
            break
    return picked


# Attribution beacon(2026-07-13 分發瓶頸裁決:SEO 是唯一 automatable-at-scale 成長管道,
# 但 blog 頁面過去零埋點→search→閱讀流量完全隱形。此 beacon 讓每篇文章的真人閱讀落成
# attr:visit 記錄,funnel_attribution 積木即可回答「SEO 到底有沒有帶客」。
# 設計要點:①navigator.webdriver guard——自家 site_scan/site-audit/引擎輪掃描不落資料
#          (與 docs/index.html:1871、track-record.html 同款,2026-07-12 ef6ae6a 已驗有效);
#          ②每 session 一次(md-visit-id sessionStorage guard,與首頁共享→blog 先打贏、
#            點 CTA 到首頁不重複打,同一 session 正確歸因到 blog 起點);
#          ③organic 落地(URL 無 utm)標 utm_source=blog/utm_medium=organic/utm_content=<slug>
#            讓 funnel 能逐篇分辨 blog-origin session;有真 utm 的分享連結則保留原值。
# ⚠️ BEACON_JS 永遠不經過 str.format()——它含大量 {}(JS 物件/箭頭函式),一律以「已 replace
#   __SLUG__ 的成品字串」當 .format() 的 beacon= 參數傳入(值內的 {} 不會被 format 再解讀),
#   或在 index f-string 內以 {BEACON_JS.replace(...)} 內插;絕不可把它塞進 format 模板字面。
BEACON_JS = """<!-- md-attr-beacon -->
<script>
(function(){
  try {
    var WORKER_URL = "https://api.marketdaily.ai";
    var p = new URL(window.location.href).searchParams;
    var real = p.get("utm_source");
    var utm = {
      utm_source:   real || "blog",
      utm_medium:   p.get("utm_medium")   || (real ? null : "organic"),
      utm_campaign: p.get("utm_campaign") || null,
      utm_term:     p.get("utm_term")     || null,
      utm_content:  p.get("utm_content")  || "__SLUG__",
    };
    if (real) {
      var payload = { utm_source: utm.utm_source, utm_medium: utm.utm_medium, utm_campaign: utm.utm_campaign, ts: Date.now() };
      try { sessionStorage.setItem("md-attr", JSON.stringify(payload)); localStorage.setItem("md-attr-first", JSON.stringify(payload)); } catch (e) {}
    }
    if (!navigator.webdriver && !sessionStorage.getItem("md-visit-id")) {
      fetch(WORKER_URL + "/track/visit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ utm_source: utm.utm_source, utm_medium: utm.utm_medium, utm_campaign: utm.utm_campaign, utm_term: utm.utm_term, utm_content: utm.utm_content, ts: Date.now() }),
      })
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(d){ if (d && d.visit_id) { try { sessionStorage.setItem("md-visit-id", d.visit_id); } catch (e) {} } })
        .catch(function(){});
    }
  } catch (e) {}
})();
</script>"""

BEACON_MARKER = "<!-- md-attr-beacon -->"


def beacon_for(slug: str) -> str:
    """回傳該 slug 專屬的 beacon 成品字串(__SLUG__ 已填)。"""
    return BEACON_JS.replace("__SLUG__", slug)


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
<meta property="og:site_name" content="MarketDaily">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{og_image}">
<link rel="canonical" href="https://marketdaily.ai/blog/{slug}.html">
<link rel="alternate" type="application/rss+xml" title="MarketDaily 個股分析" href="/feed.xml">
<script type="application/ld+json">{schema_json}</script>
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
{beacon}
</body>
</html>"""


MARKET_LABELS = {"us": "美股", "tw": "台股", "term": "投資知識", "macro": "總體經濟", "guide": "新手教學"}


def _git_first_commit_date(fname: Path) -> str:
    """該檔案第一次進 git 的日期(ISO8601)。查不到就退回檔案 mtime。"""
    try:
        out = subprocess.run(
            ["git", "log", "--follow", "--diff-filter=A", "--format=%aI", "--", str(fname)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out:
            return out.splitlines()[-1]
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(fname.stat().st_mtime, timezone(timedelta(hours=8))).isoformat()
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _existing_date_published(fname: Path):
    """重新渲染既有檔案時,盡量保留原本的 datePublished(而非每次重寫都刷新成今天)。"""
    if not fname.exists():
        return None
    try:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', fname.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


DEFAULT_OG_IMAGE = "https://marketdaily.ai/assets/og.png"


def og_image_for(slug: str, ticker: str, market_label: str, title: str) -> str:
    """回傳該文章 og:image 絕對 URL。嘗試用 scripts/og_card.py 生成品牌卡(冪等,存在即略過);
    任何失敗(PIL 不在/字型缺/渲染例外)一律 fallback 站台預設 og.png——保證管線永不因產圖而斷。"""
    try:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from og_card import render_card
        out = BLOG_DIR / "og" / f"{slug}.png"
        if not out.exists():
            render_card(out, ticker, market_label, title)
        if out.exists() and out.stat().st_size > 0:
            return f"https://marketdaily.ai/blog/og/{slug}.png"
    except Exception as e:
        print(f"  [og_card] fallback default ({type(e).__name__}: {e})")
    return DEFAULT_OG_IMAGE


def _article_schema_json(title: str, desc: str, slug: str, date_published: str,
                         date_modified: str, image: str = DEFAULT_OG_IMAGE) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "image": [image],
        "datePublished": date_published,
        "dateModified": date_modified,
        "author": {"@type": "Organization", "name": "MarketDaily"},
        "publisher": {
            "@type": "Organization",
            "name": "MarketDaily",
            "logo": {"@type": "ImageObject", "url": "https://marketdaily.ai/logo-icon.svg"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"https://marketdaily.ai/blog/{slug}.html"},
    }
    return json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")


def write_article(art: dict, dry: bool) -> Path:
    slug = art["slug"]
    fname = BLOG_DIR / f"{slug}.html"
    if art["market"] == "term":
        desc = f"{art['name']} — MarketDaily 投資知識整理。"
    elif art["market"] == "macro":
        desc = f"{art['name']} — MarketDaily 總體經濟指標整理。"
    elif art["market"] == "guide":
        desc = f"{art['name']} — MarketDaily 新手投資教學整理。"
    else:
        desc = f"{art['name']} ({art['ticker']}) {art['topic']} — MarketDaily 整理。"
    related = related_html(art["ticker"], slug, scan_articles())
    date_modified = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    date_published = _existing_date_published(fname) or _git_first_commit_date(fname) or date_modified
    market_label = MARKET_LABELS.get(art["market"], "台股")
    og_image = DEFAULT_OG_IMAGE if dry else og_image_for(slug, art["ticker"], market_label, art["title"])
    schema_json = _article_schema_json(art["title"], desc, slug, date_published, date_modified, og_image)
    html = PAGE_TEMPLATE.format(
        title=art["title"],
        desc=desc,
        slug=slug,
        slug_short=slug[:32],
        market_label=market_label,
        body=art["body_html"],
        related=related,
        updated=date_modified,
        schema_json=schema_json,
        og_image=og_image,
        beacon=beacon_for(slug),
    )
    if dry:
        print(f"  [dry] {fname.name}({len(html)} bytes)")
        return fname
    fname.write_text(html, encoding="utf-8")
    print(f"  ✓ {fname.name}")
    return fname


def regenerate_blog_index(dry: bool):
    """掃 docs/blog/ 所有文章,生成 index.html 列表頁。"""
    # 按 datePublished 排序(新→舊),而非 mtime。og/beacon/rss 回填會把全部文章 mtime
    # 刷成同一天 → mtime 排序退化成任意 glob 順序、最新文章被埋;datePublished 與 git 首次
    # 提交日一致且穩定,git checkout 也不會改動。slug 當決定性次序(同日多篇時可重現)。
    _articles = [f for f in BLOG_DIR.glob("*.html") if f.stem != "index"]
    _keyed = [((_existing_date_published(f) or _git_first_commit_date(f)), f.stem, f) for f in _articles]
    _keyed.sort(key=lambda k: (k[0], k[1]), reverse=True)
    files = [f for _, _, f in _keyed]
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
<title>財經知識庫 · 投資學堂 | MarketDaily</title>
<meta name="description" content="MarketDaily 財經知識庫:個股拆解、法說會前瞻、除權息、供應鏈全景,到總經指標與新手入門,涵蓋美股、台股。">
<meta name="facebook-domain-verification" content="ylg7ynhyj5ywyoierjgo7mchqdvbek" />
<link rel="alternate" type="application/rss+xml" title="MarketDaily 個股分析" href="/feed.xml">
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
  <h1>財經知識庫 · {len(items)} 篇</h1>
  <div class="grid">{cards}</div>
</div>
{beacon_for("blog-index")}
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


def pick_beginner_seeds(count: int, published: set) -> list:
    if count <= 0:
        return []
    import random
    rng = random.Random(int(datetime.now().timestamp()) + 5)
    candidates = list(BEGINNER_TOPICS)
    rng.shuffle(candidates)
    picked = []
    for topic, keyword in candidates:
        if beginner_slug(topic) in published:
            continue
        picked.append((topic, keyword))
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
    # 配額:5 種常青缺口填充池(A詞彙/D供應鏈/B除權息/C總經/F新手)各最多 1 篇,剩下才給既有個股×主題組合。
    # STOCK_RESERVE 保留至少 1 個名額給長青個股池——production 一週只跑一次 --count 5,若缺口池
    # 都用固定順序搶,個股池永遠分不到(2026-07-05 驗證者分離抓到的真實回歸,曾在此發生)。
    # 常青缺口池彼此的搶奪順序依 ISO 週數輪替(而非寫死 term>chain>dividend>macro>beginner),
    # 讓每個池子輪流被排在最後、輪流被犧牲,不會有後加入的池子長期被排擠到 0。
    # event(法說會事件)池不加入這個輪替——常青池子這週沒搶到,下週topic還在、可以再搶;
    # 但 event 池是真實時效窗口(法說會日期一過,那個素材就永久錯過),若跟常青池搶同一輪替
    # 排到後面會被排擠到 0 次嘗試,等於系統性漏接時效性內容(2026-07-05 驗證者分離抓到的
    # 真實回歸)。故給 event 池固定優先於輪替之前先查,查到真實窗口內事件才佔用名額,
    # 查無事件(絕大多數週次)不消耗任何名額,常青池輪替預算不受影響。
    # confluence(訊號匯流觀察)池同理不加入輪替:當日 by_code degree≥3 是特定日期的真實
    # 巧合,錯過當晚 patrol.py 快照就再也拿不回同一批訊號,跟 event 池同一種「真實時效窗口」
    # 屬性,故用同一套「固定優先於輪替+查無不佔名額」處理(見 pick_confluence_seeds)。
    STOCK_RESERVE = 1
    gap_budget = max(args.count - STOCK_RESERVE, 0)
    event_seeds = pick_event_seeds(min(1, gap_budget), published)
    gap_budget -= len(event_seeds)
    confluence_seeds = pick_confluence_seeds(min(1, gap_budget), published)
    gap_budget -= len(confluence_seeds)
    gap_pickers = {
        "term": lambda n: pick_term_seeds(n, published),
        "chain": lambda n: pick_chain_seeds(n, published),
        "dividend": lambda n: pick_dividend_seeds(n, published),
        "macro": lambda n: pick_macro_seeds(n, published),
        "beginner": lambda n: pick_beginner_seeds(n, published),
    }
    gap_order = list(gap_pickers)
    rotate = int(datetime.now().strftime("%V")) % len(gap_order)
    gap_order = gap_order[rotate:] + gap_order[:rotate]
    gap_seeds = {k: [] for k in gap_pickers}
    for key in gap_order:
        if gap_budget <= 0:
            break
        gap_seeds[key] = gap_pickers[key](min(1, gap_budget))
        gap_budget -= len(gap_seeds[key])
    term_seeds = gap_seeds["term"]
    chain_seeds = gap_seeds["chain"]
    dividend_seeds = gap_seeds["dividend"]
    macro_seeds = gap_seeds["macro"]
    beginner_seeds = gap_seeds["beginner"]
    stock_n = (args.count - len(term_seeds) - len(chain_seeds) - len(dividend_seeds)
               - len(macro_seeds) - len(beginner_seeds) - len(event_seeds) - len(confluence_seeds))
    stock_seeds = pick_seeds(stock_n, published) if stock_n > 0 else []
    if not any([term_seeds, chain_seeds, dividend_seeds, macro_seeds, beginner_seeds, event_seeds,
                confluence_seeds, stock_seeds]):
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
    for topic, keyword in beginner_seeds:
        print(f"  • 新手教學 — {topic}")
        try:
            art = gen_beginner_article(topic, keyword)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for code, name, market, conf_entry, materials in event_seeds:
        is_past = conf_entry["days_until"] < 0
        kind = "重點解讀" if (materials and is_past) else "前哨" if materials else ("回顧" if is_past else "前瞻")
        print(f"  • {market.upper()} {code} {name} — 法說會{kind}")
        try:
            art = gen_event_article(code, name, market, conf_entry, materials)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    for code, name, market, date, entries in confluence_seeds:
        degree = len(set(e.get("source") for e in entries))
        print(f"  • {market.upper()} {code} {name} — {CONFLUENCE_TOPIC}(degree={degree})")
        try:
            art = gen_confluence_article(code, name, market, date, entries)
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
    print("④ 回填 attribution beacon(缺 marker 才注入,冪等)...")
    backfill_beacon(args.dry)

    print("④ 補社群卡 og:image...")
    backfill_og_cards(args.dry)
    print("⑤ 更新 blog index...")
    regenerate_blog_index(args.dry)
    print("⑥ 更新 RSS feed(docs/feed.xml)...")
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from blog_feed import build_feed
        build_feed(args.dry)
    except Exception as e:
        print(f"  [feed] skip(不阻斷管線): {type(e).__name__}: {e}")
    print("✓ done")


if __name__ == "__main__":
    main()
