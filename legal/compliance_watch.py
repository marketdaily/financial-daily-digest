"""法務部生產面合規哨兵(2026-08-04)。

**要解的問題**:公司所有合規防線都在「產出前」(pricing.test.mjs / post_gate.py / 日報 audit)。
線上頁面 deploy 之後沒有任何東西看過——任一視窗或 agent 改了 `docs/` 直接部署就繞過全部閘門,
而罰則是真的錢(公平法 §42:5萬–2500萬;投顧法 §107:橋頭 111 金訴 235 判 2年2月+沒收 802 萬)。
本檔**抓真的線上頁面**,把 `dept_legal` 的四張檢查表變成每晚會自己跑的判準。

三態(抄 intel/doctor.py 的分辨法,同一個致命歧義):
  clean    掃過了、乾淨
  violation掃過了、咬到紅線
  unknown  **沒掃到**(抓不到頁面/解析失敗)——絕不可跟 clean 混為一談

覆蓋率保證(2026-08-04 突變 harness 教訓:「零覆蓋率」與「全數通過」長得一樣的地方必須有計數器):
  1. 每次跑先 `rules.selfcheck()`——規則自己壞掉(regex 打錯)會讓它從此永遠零命中,
     輸出卻長得像全站乾淨。selfcheck 不過 → exit 3,不進掃描。
  2. 統計每條規則被套用幾次;**有規則一次都沒被套用(pack 名打錯)→ exit 3**。
  3. 掃描成功面數 0 → exit 3。
  4. 有 unknown 面 → 至少 exit 2,報告頭一行就寫「本次未涵蓋 N 面」。

用法:
    python3 -m legal.compliance_watch              # 人看的報告
    python3 -m legal.compliance_watch --json       # 機器讀
    python3 -m legal.compliance_watch --offline    # 只跑規則庫自檢(不連網,給 CI/自測用)
    python3 -m legal.compliance_watch --only md_index,ms_pricing_api
"""
import os
import re
import sys
import json
import html
import time
import argparse
import datetime
import urllib.parse
import urllib.request
import urllib.error
import concurrent.futures

from legal import rules as R

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# 促銷觀測帳本是**每晚會被寫**的狀態,所以放在 repo 外(同其他 runner 的 state):
# cron 每晚在 tracked 路徑生出改動 = 一堆 cron_abort_if_dirty 生態鏈會被餓死
# (見 capability dirty_tree_watch)。舉證表 price_sold_evidence.json 是人工維護的設定,留在 repo。
_STATE_DIR = os.path.join(os.path.expanduser("~"), ".marketdaily-fallback")
PROMO_LEDGER = os.environ.get("COMPLIANCE_PROMO_LEDGER") or (
    os.path.join(_STATE_DIR, ".compliance_promo_ledger.json") if os.path.isdir(_STATE_DIR)
    else os.path.join(HERE, "promo_ledger.json"))
SOLD_EVIDENCE = os.environ.get("COMPLIANCE_SOLD_EVIDENCE") or os.path.join(
    HERE, "price_sold_evidence.json")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 20
RETRIES = 1

# 單檔促銷上限(天)。與 fortune-ai/worker/src/pricing.js 的 PROMO_MAX_DAYS 同值——
# 那邊是「不准部署」的閘,這邊是「線上真的長怎樣」的哨兵,兩者刻意重複。
PROMO_MAX_DAYS = 60
# 兩檔促銷之間必須恢復定價的最短天數。無縫續檔 = 「限時特惠」變常態價 = 定價虛列
# (公平法 §21;pricing.js 法規紅線 5 明文但**原本沒有任何東西會偵測**,open #95)。
PROMO_MIN_GAP_DAYS = 30

CLEAN, VIOLATION, UNKNOWN = "clean", "violation", "unknown"

# 促銷閘的檢查不是 rules.py 裡的規則(它吃 JSON 不吃文字),但一樣要被覆蓋率守衛盯著,
# 否則它永遠 unknown 也不會有人發現——有真金流的那一面無聲失守(驗證者 F11)。
PROMO_PSEUDO_RULES = ("ms_promo_too_long", "ms_promo_rolling", "ms_promo_backtoback",
                      "ms_price_leak", "ms_compare_at_unproven", "ms_promo_snapshot_shape",
                      "ms_ledger_unreadable")

SURFACES = [
    {"id": "md_index", "label": "MarketDaily 首頁",
     "url": "https://marketdaily.ai/", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing", "marketdaily_disclaimer"]},
    {"id": "md_pricing", "label": "MarketDaily 方案頁",
     "url": "https://marketdaily.ai/pricing.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_testimonials", "label": "MarketDaily 見證頁",
     "url": "https://marketdaily.ai/testimonials.html", "kind": "html",
     "packs": ["marketdaily"]},
    {"id": "md_track_record", "label": "MarketDaily 戰績頁",
     "url": "https://marketdaily.ai/track-record.html", "kind": "html",
     # 戰績頁是勝率數字的合法真源(公版可查證),不列入 marketing pack
     "packs": ["marketdaily"]},
    {"id": "md_vs_chatgpt", "label": "MarketDaily 對比頁",
     "url": "https://marketdaily.ai/vs-chatgpt.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_guide", "label": "MarketDaily 使用指南",
     "url": "https://marketdaily.ai/guide.html", "kind": "html",
     "packs": ["marketdaily"]},
    # 以下 2026-08-04 補(驗證者 F13:原本只掃 7/145 個真實頁面,而 blog 正是
    # project_blog_seo_fabricated_numbers 事故的發生地,一篇都沒掃)
    {"id": "md_terms", "label": "MarketDaily 服務條款",
     "url": "https://marketdaily.ai/terms.html", "kind": "html", "packs": ["marketdaily"]},
    {"id": "md_privacy", "label": "MarketDaily 隱私權",
     "url": "https://marketdaily.ai/privacy.html", "kind": "html", "packs": ["marketdaily"]},
    {"id": "md_faq", "label": "MarketDaily 常見問題",
     "url": "https://marketdaily.ai/faq.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_about", "label": "MarketDaily 關於我們",
     "url": "https://marketdaily.ai/about.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_vs", "label": "MarketDaily 競品比較",
     "url": "https://marketdaily.ai/vs.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_agents", "label": "MarketDaily AI 代理人",
     "url": "https://marketdaily.ai/agents.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    # ⭐ 這兩面是**預設納管**的:清單由 docs/ 的 glob 展開,不是人手維護的白名單。
    #    F13 的根因是「忘了把新頁面加進 SURFACES」——那種清單只會愈來愈舊,
    #    所以改成「新頁面自動納管,不掃的要在 DOCS_EXCLUDE 具名並寫理由」。
    {"id": "md_docs_rest", "label": "MarketDaily 其餘線上頁面(glob 自動納管)",
     "url": "@docs_rest", "kind": "html_multi",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_blog_all", "label": "Blog 全部文章(捏造數字事故發生地)",
     "url": "@blog_all", "kind": "html_multi",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_digest_latest", "label": "日報公版存檔(最新)",
     "url": "@latest_digest", "kind": "html",
     "packs": ["marketdaily", "marketdaily_disclaimer"]},
    {"id": "ms_index", "label": "命書首頁",
     "url": "https://mingshu.tw/", "kind": "html",
     "packs": ["mingshu"]},
    # 命書是唯一有真金流的線,原本只掃首頁 1 面 2 條規則——而稀缺話術/療效宣稱最可能出現在
    # 142 個 pSEO 內容頁上。清單取自**線上 sitemap**(那才是「實際部署了什麼」的真源;
    # 命書的頁面也不在本 repo 裡,拿本機檔案當清單會永遠對不上)。
    {"id": "ms_pseo", "label": "命書全站頁面(線上 sitemap 展開)",
     "url": "@ms_sitemap", "kind": "html_multi",
     "packs": ["mingshu"]},
    {"id": "ms_pricing_api", "label": "命書定價快照(公平法促銷閘)",
     "url": "https://fortune-ai.delvin-12345678.workers.dev/api/pricing", "kind": "promo",
     "packs": []},
]

# 不納管的頁面。**每一條都要有理由**——這份清單是唯一能縮小覆蓋面的地方,沒有理由的
# 排除等於偷偷把某頁移出視線。清單本身也會被 lint:排除了一個不存在的檔案=設定過期。
DOCS_EXCLUDE = {
    "404.html": "錯誤頁,可見文字 144 字(無行銷文案),掃了只會永遠 unknown",
    "dashboard-preview.html": "整頁 JS 渲染的示意畫面,HTML 只有 17 字",
    "preferences.html": "登入牆後的偏好設定頁,未登入抓到的是 134 字空殼",
}


def _docs_dir(*parts):
    return os.path.join(REPO, "docs", *parts)


def _named_doc_files():
    """已經有專屬 surface(可能帶客製 packs)的 docs 檔名——不重複掃。"""
    out = set()
    for sf in SURFACES:
        u = sf.get("url", "")
        if u.startswith("https://marketdaily.ai/") and u.endswith(".html"):
            out.add(u.rsplit("/", 1)[-1])
        elif u == "https://marketdaily.ai/":
            out.add("index.html")
    return out


def docs_page_urls():
    """docs/ 底下**全部**頂層頁面的線上網址(扣掉已具名與 DOCS_EXCLUDE)。
    新頁面 deploy 之後自動納管——這是 F13 的結構性解,不是把清單抄長一點。"""
    try:
        files = sorted(f for f in os.listdir(_docs_dir()) if f.endswith(".html"))
    except Exception:
        return []
    skip = _named_doc_files() | set(DOCS_EXCLUDE)
    return [f"https://marketdaily.ai/{f}" for f in files if f not in skip]


def blog_urls(limit=None):
    """blog 全部文章的線上網址(新到舊)。清單來源=本機 docs/blog(部署來源),但**抓的是線上頁面**。"""
    d = _docs_dir("blog")
    try:
        files = [f for f in os.listdir(d) if f.endswith(".html") and f != "index.html"]
    except Exception:
        return []
    files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
    if limit:
        files = files[:limit]
    return [f"https://marketdaily.ai/blog/{f}" for f in files]


_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
MS_SITEMAP = "https://mingshu.tw/sitemap.xml"


def sitemap_urls(sitemap=MS_SITEMAP, skip=("https://mingshu.tw/",)):
    """從**線上 sitemap** 展開頁面清單(命書的 pSEO 頁不在本 repo,而且線上 sitemap 才是
    「實際部署了什麼」的真源)。抓不到 → 空清單 → 該面 unknown,不會靜靜地綠。"""
    code, body = fetch(sitemap, timeout=20, retries=1)
    if code != 200:
        return []
    return [u for u in _SITEMAP_LOC.findall(body) if u not in skip]


def config_problems():
    """設定自己過期/寫錯的偵測。回傳 list[str],非空=exit 3(守衛壞了,不是今晚抓不到)。

    ⚠️ 排除清單過期是**靜默縮小覆蓋面**的典型形狀:頁面改名之後,舊的排除項還在,
    新名字卻沒人排除也沒人具名——看起來一切正常,實際上多了一頁沒人看/少了一頁該看。
    """
    probs = []
    try:
        have = set(os.listdir(_docs_dir()))
    except Exception as e:
        return [f"讀不到 docs/ 目錄({type(e).__name__}),頁面清單無法展開"]
    for f in sorted(DOCS_EXCLUDE):
        if f not in have:
            probs.append(f"DOCS_EXCLUDE 排除了不存在的檔案 {f}(頁面改名/刪除,排除清單已過期)")
    for f in sorted(_named_doc_files()):
        if f not in have:
            probs.append(f"SURFACES 指向不存在的 docs/{f}(網址已死或檔案改名)")
    return probs


# ── 抓取 ────────────────────────────────────────────────────────────────
def fetch(url, timeout=TIMEOUT, retries=RETRIES):
    """回傳 (status, body)。網路層例外一律轉成 (0, 錯誤字串),絕不拋出。"""
    last = (0, "unknown")
    # 非 ASCII 路徑要先百分比編碼,否則 urllib 直接 UnicodeEncodeError
    # (中文檔名的 blog 文章實測全掛,而且會被記成「抓不到」而非「網址寫錯」)
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(safe, headers={
                "User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.getcode(), raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, f"HTTP {e.code}"
        except Exception as e:
            last = (0, f"{type(e).__name__}: {e}")
            if attempt < retries:
                time.sleep(1.5)
    return last


def latest_digest_url(today=None):
    """公版存檔以日期命名;往前找最多 5 天,回傳第一個 200 的 URL(找不到→None)。"""
    d = today or datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    for back in range(5):
        ymd = (d - datetime.timedelta(days=back)).strftime("%Y-%m-%d")
        for suffix in ("", "_us"):
            url = f"https://marketdaily.ai/output/digest_{ymd}{suffix}.html"
            code, _ = fetch(url, timeout=12, retries=0)
            if code == 200:
                return url
    return None


# ── HTML → 使用者看得到的字 ────────────────────────────────────────────
_DROP = re.compile(r"(?is)<(script|style|template|noscript)\b.*?</\1>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
# ⚠️ block-level 標籤要換成**換行**而不是空白:換空白的話 `</h2><li>` 會把兩個語意無關的
#    元素併成同一「句」,整套「proximity 不得跨句」的防線在真實 HTML 上直接失效
#    (2026-08-04 驗證者 F3 實測產出 CRITICAL 級誤報)。inline 標籤才換空白。
_BLOCK_TAG = re.compile(r"(?is)</?(p|div|li|ul|ol|h[1-6]|tr|td|th|table|br|hr|section|article|"
                        r"header|footer|nav|aside|main|form|label|option|blockquote|dt|dd|figcaption)\b[^>]*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_SCRIPT = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
# i18n 字典躺在 inline <script> 裡,是**真的會顯示給用戶看的字**;
# 上限拉到 4000(原本 300 會把長段落整段丟掉,生產首頁今天就中了一筆——驗證者 F10)。
_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.){4,4000})"' r"|'((?:[^'\\\n]|\\.){4,4000})'")
_CJK = re.compile(r"[一-龥]")
# 屬性文字:meta/og description 是搜尋結果與社群分享上真正給人看的行銷文案,
# alt/title/placeholder 同理。原本整個標籤被刪掉 = 從未被掃(驗證者 F9)。
_META = re.compile(r"""(?is)<meta\b[^>]*?(?:name|property)\s*=\s*["']"""
                   r"""(description|og:description|og:title|twitter:description|twitter:title)["']"""
                   r"""[^>]*?content\s*=\s*["']([^"']{4,600})["']""")
_META_REV = re.compile(r"""(?is)<meta\b[^>]*?content\s*=\s*["']([^"']{4,600})["']"""
                       r"""[^>]*?(?:name|property)\s*=\s*["']"""
                       r"""(description|og:description|og:title|twitter:description|twitter:title)["']""")
_ATTR_TEXT = re.compile(r"""(?is)\b(alt|title|placeholder|aria-label)\s*=\s*["']([^"']{4,400})["']""")
# 英文 i18n 字典:≥4 個英文單字才算文案(過濾 selector/URL/class 名)
_EN_SENTENCE = re.compile(r"(?:[A-Za-z][A-Za-z'’\-]{1,}\s+){3,}[A-Za-z]")


def _looks_like_copy(s):
    return bool(_CJK.search(s)) or bool(_EN_SENTENCE.search(s))


def visible_text(page, stats=None):
    """把一頁 HTML 轉成「使用者真的看得到的字」。stats(可選 dict)會收到覆蓋率計數。"""
    # ⚠️ 順序:先移除 script/style,**再**處理註解。反過來的話 JS 裡的字面 `<!--`
    #    會跟後面任何一個 `-->` 配對,把中間的真實文案整段吃掉(驗證者 F12)。
    no_script = _DROP.sub("\n", page)
    body = _COMMENT.sub(" ", no_script)
    text = html.unescape(_TAG.sub(" ", _BLOCK_TAG.sub("\n", body)))
    parts = [text]

    for m in _META.finditer(page):
        parts.append(html.unescape(m.group(2)))
    for m in _META_REV.finditer(page):
        parts.append(html.unescape(m.group(1)))
    for m in _ATTR_TEXT.finditer(_DROP.sub(" ", page)):
        parts.append(html.unescape(m.group(2)))

    dropped = 0
    kept = 0
    for m in _SCRIPT.finditer(page):
        block = m.group(1)
        for lit in _LITERAL.finditer(block):
            s = lit.group(1) or lit.group(2) or ""
            if _looks_like_copy(s):
                kept += 1
                parts.append(html.unescape(s.replace("\\n", " ").replace('\\"', '"')))
        # 超長字面值(超過 _LITERAL 上限)會靜默掉出語料 → 計數,零覆蓋率必須看得見
        for lit in re.finditer(r'"((?:[^"\\\n]|\\.){4001,})"', block):
            if _looks_like_copy(lit.group(1)):
                dropped += 1
    if stats is not None:
        stats["js_literals_kept"] = kept
        stats["js_literals_dropped"] = dropped
    return re.sub(r"[ \t　]+", " ", "\n".join(parts))


# ── 命書促銷閘(公平法) ─────────────────────────────────────────────────
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_ledger(path):
    """回傳 (ledger, problem)。**檔案不存在=正常(首次跑);解析壞掉=事故,不可當成空帳本。**

    ⚠️ 這裡吞例外會 fail-open 而且不可逆(2026-08-04 驗證者 F2):帳本毀損後歷史被清空 →
    教科書級的假倒數回報零 finding;程式接著把「現在這個已被延長的截止時刻」當成首次觀測
    寫回去 → 唯一能咬 rolling 的基準被永久抹掉,之後永遠也抓不到。
    """
    if not os.path.exists(path):
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("promos", []), list):
            raise ValueError("帳本結構不對(promos 應為 list)")
        for h in data.get("promos", []):
            if not isinstance(h, dict):
                raise ValueError("promos 內含非物件項目")
        return data, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _atomic_write(path, obj):
    """tmp + os.replace。cron 每 10 分鐘跑一次、winrig 有斷電前科,直接 open(...,'w') 會留半截檔。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _promo_key(h):
    """帳本鍵 = (id, starts_at_ms)。只用 id 的話,半年後沿用同一個 id 的全新一檔會被判成
    『截止時刻往後跳 3672 小時』的 CRITICAL 誤報,而且跳過續檔閘(驗證者 F7)。"""
    return (h.get("id"), h.get("starts_at_ms"))


def _shape_problem(snap):
    """線上 JSON 形狀變了要回報成 finding,不是拋例外讓整面變 unknown(驗證者 F11)。"""
    if not isinstance(snap, dict):
        return "定價快照不是物件"
    if not isinstance(snap.get("items"), dict):
        return f"items 應為物件,實得 {type(snap.get('items')).__name__}"
    for pid, it in snap["items"].items():
        if not isinstance(it, dict):
            return f"品項 {pid} 不是物件(實得 {type(it).__name__})"
    if snap.get("promo") is not None and not isinstance(snap.get("promo"), dict):
        return f"promo 應為物件,實得 {type(snap.get('promo')).__name__}"
    if snap.get("now") is not None and not isinstance(snap.get("now"), (int, float)):
        return f"now 應為數字,實得 {type(snap.get('now')).__name__}"
    return None


def check_promo(snap, ledger, now_ms=None, write_path=None, ledger_problem=None):
    """回傳 (findings, new_ledger)。snap=/api/pricing 的解析結果。

    這裡的每一條都對應 `fortune-ai/worker/src/pricing.js` 檔頭的法規紅線,差別是
    **那邊擋部署、這邊看線上實況**——線上是 worker 的舊版本、或有人手改 KV,那邊測試全綠也沒用。
    """
    out = []
    shape = _shape_problem(snap)
    if shape:
        out.append({"rule": "ms_promo_snapshot_shape", "severity": R.CRITICAL, "law": "公平法 §21",
                    "evidence": f"線上定價快照形狀變了:{shape}——促銷閘等於全盲"})
        return out, dict(ledger or {})

    led = dict(ledger or {})
    # ⚠️ 逐筆深拷貝,不是 list(...)。淺拷貝會讓我們就地改到呼叫端手上那份帳本——
    #    而帳本裡的 ends_at_ms 正是偵測 rolling timer 的唯一基準,被自己改掉=證據銷毀。
    #    (2026-08-04 突變 M7 存活才揭出來:測試比對的兩份其實是同一個物件,永遠相等。)
    hist = [dict(h) for h in led.get("promos", [])]
    promo = snap.get("promo") or {}
    items = snap.get("items") or {}
    now_ms = now_ms or snap.get("now") or int(time.time() * 1000)

    # 帳本毀損 = 偵測基準不見了,fail-closed:回報 + **拒絕寫回**(保留毀損檔供鑑識)
    if ledger_problem:
        out.append({"rule": "ms_ledger_unreadable", "severity": R.HIGH,
                    "law": "公平法 §21(rolling timer 偵測基準)",
                    "evidence": f"促銷觀測帳本讀不到/結構壞掉({ledger_problem})——"
                                "假倒數偵測在修好之前是盲的,本次刻意不覆寫帳本"})
        write_path = None

    if not items:
        out.append({"rule": "ms_promo_snapshot", "severity": R.CRITICAL,
                    "law": "公平法 §21", "evidence": "定價快照沒有任何品項——前端會拿不到價格"})
        return out, led

    active = bool(promo.get("active"))
    if active:
        sid = promo.get("id") or "(無 id)"
        starts, ends = promo.get("starts_at"), promo.get("ends_at")
        s_ms, e_ms = _parse_iso_ms(starts), _parse_iso_ms(ends)
        if s_ms is None or e_ms is None:
            out.append({"rule": "ms_promo_window", "severity": R.HIGH, "law": "公平法 §21",
                        "evidence": f"促銷 {sid} 的起訖時間無法解析:{starts!r}→{ends!r}"})
        else:
            days = (e_ms - s_ms) / 86400000.0
            if days > PROMO_MAX_DAYS:
                out.append({"rule": "ms_promo_too_long", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"促銷 {sid} 長 {days:.1f} 天 > 上限 {PROMO_MAX_DAYS} 天"
                                        "——「限時特惠」變常態價,定價即屬虛列"})
            key = (sid, s_ms)
            prev = [h for h in hist if _promo_key(h) == key]
            if prev:
                old_e = prev[-1].get("ends_at_ms")
                if old_e and e_ms > old_e + 60000:
                    out.append({"rule": "ms_promo_rolling", "severity": R.CRITICAL, "law": "公平法 §21/§25",
                                "evidence": f"促銷 {sid} 的截止時刻往後跳了 "
                                            f"{(e_ms - old_e)/3600000:.1f} 小時(上次觀測 "
                                            f"{_ms_ymd(old_e)} → 現在 {_ms_ymd(e_ms)})——假倒數"})
            else:
                others = [h for h in hist if _promo_key(h) != key and h.get("ends_at_ms")]
                if others:
                    last_end = max(h["ends_at_ms"] for h in others)
                    gap = (s_ms - last_end) / 86400000.0
                    if gap < PROMO_MIN_GAP_DAYS:
                        out.append({"rule": "ms_promo_backtoback", "severity": R.HIGH,
                                    "law": "公平法 §21(pricing.js 紅線 5)",
                                    "evidence": f"新促銷 {sid} 距上一檔結束僅 {gap:.1f} 天 "
                                                f"< 應恢復定價 {PROMO_MIN_GAP_DAYS} 天——無縫續檔"})
                hist.append({"id": sid, "starts_at_ms": s_ms, "ends_at_ms": e_ms,
                             "first_seen": _ms_ymd(now_ms)})
            # ⚠️ 只更新 last_seen,**絕不覆寫 ends_at_ms**——帳本裡那個值是「第一次看到的
            #    截止時刻」,正是拿來咬 rolling timer 的基準。覆寫掉等於自己把證據銷毀。
            for h in hist:
                if _promo_key(h) == key:
                    h["last_seen"] = _ms_ymd(now_ms)
    else:
        # 促銷未啟動時,實收必須等於定價:不等於代表有第二份價格數字在線上活著
        for pid, it in sorted(items.items()):
            if it.get("price") != it.get("list"):
                out.append({"rule": "ms_price_leak", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"{pid} 無促銷但 price={it.get('price')} ≠ list={it.get('list')}"})
            if it.get("promo"):
                out.append({"rule": "ms_price_leak", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"{pid} 無促銷期間卻回報 promo=true"})

    # 劃線價(compare_at)要有「曾以該價格販售相當數量」的舉證(公處字 098101 華碩案)
    evidence = _load_json(SOLD_EVIDENCE, {}).get("sold", {})
    for pid, it in sorted(items.items()):
        if it.get("compare_at") not in (None, 0) and not evidence.get(pid):
            out.append({"rule": "ms_compare_at_unproven", "severity": R.CRITICAL,
                        "law": "公平法 §21;公處字第098101號(華碩)",
                        "evidence": f"{pid} 對外劃線價 {it.get('compare_at')},"
                                    f"但 legal/price_sold_evidence.json 沒有該品項的定價成交舉證"})

    led["schema_version"] = 1
    led["promos"] = hist[-24:]   # 保留最近 24 檔,防無限增長
    led["last_checked"] = _ms_ymd(now_ms)
    if write_path:
        _atomic_write(write_path, led)
    return out, led


def _quarantine(path):
    """毀損帳本另存 .corrupt-<ts> 供鑑識,不是直接覆蓋掉。"""
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        os.replace(path, f"{path}.corrupt-{ts}")
    except Exception:
        pass


def expected_rule_ids(surfaces):
    """由 SURFACES 的 packs 靜態推導「這批設定**應該**會套用到哪些規則」。
    與抓取成敗完全無關——這是分辨「設定壞掉」與「今晚抓不到」的唯一乾淨方法。"""
    ids = set()
    for sf in surfaces:
        if sf.get("kind") == "promo":
            ids.update(PROMO_PSEUDO_RULES)
            continue
        for r in R.rules_for(sf.get("packs", []), sf.get("exclude_rules", ())):
            ids.add(r["id"])
    return ids


def _parse_iso_ms(s):
    if not s:
        return None
    try:
        return int(datetime.datetime.fromisoformat(str(s)).timestamp() * 1000)
    except Exception:
        return None


def _ms_ymd(ms):
    return datetime.datetime.fromtimestamp(ms / 1000 + 8 * 3600, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


_DIGEST_YMD = re.compile(r"digest_(\d{4}-\d{2}-\d{2})")


def _digest_age_days(url, today=None):
    """公版存檔的日期距今天幾天(抓不出日期→None)。"""
    m = _DIGEST_YMD.search(url or "")
    if not m:
        return None
    d = today or (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).date()
    try:
        return (d - datetime.date.fromisoformat(m.group(1))).days
    except Exception:
        return None


# ── 掃描 ────────────────────────────────────────────────────────────────
SUB_WORKERS = 6   # html_multi 內層的併發(外層 5 × 內層 6 對自家 Pages 是安全的量)


def _expand_multi(token):
    return {"@docs_rest": docs_page_urls, "@blog_all": blog_urls,
            "@ms_sitemap": sitemap_urls}.get(token, list)()


def _merge_corpus(acc, one):
    """把子頁的語料統計加總。零覆蓋率要看得見:語言分佈與被丟棄的長字串都要有數字。"""
    if not one:
        return
    acc["pages"] += one.get("pages", 0)
    acc["cjk_pages"] += one.get("cjk_pages", 0)
    acc["en_pages"] += one.get("en_pages", 0)
    acc["literals_dropped"] += one.get("literals_dropped", 0)


def scan_surface(sf, write_ledger=True):
    res = {"id": sf["id"], "label": sf["label"], "url": sf["url"],
           "status": UNKNOWN, "findings": [], "rules_run": [], "detail": ""}
    url = sf["url"]
    if url == "@latest_digest":
        url = latest_digest_url()
        if not url:
            res["detail"] = "近 5 天的公版存檔都抓不到(digest 交付可能也出事了)"
            return res
        res["url"] = url
        # 存檔過期時報告要講出來:掃的是三天前那份、卻只寫「乾淨」,等於替一份沒人看的舊檔背書
        res["stale_days"] = _digest_age_days(url)

    if sf["kind"] == "promo":
        code, body = fetch(url)
        if code != 200:
            res["detail"] = f"定價快照抓不到(HTTP {code}):{body[:120]}"
            return res
        try:
            snap = json.loads(body)
        except Exception as e:
            res["detail"] = f"定價快照不是合法 JSON:{e}"
            return res
        led, led_problem = load_ledger(PROMO_LEDGER)
        if led_problem:
            _quarantine(PROMO_LEDGER)
        findings, _ = check_promo(snap, led or {}, ledger_problem=led_problem,
                                  write_path=PROMO_LEDGER if write_ledger else None)
        res["rules_run"] = list(PROMO_PSEUDO_RULES)
        res["findings"] = findings
        res["status"] = VIOLATION if findings else CLEAN
        res["detail"] = (f"促銷{'啟動中' if (snap.get('promo') or {}).get('active') else '未啟動'}"
                         f",{len(snap.get('items') or {})} 品項")
        return res

    if sf["kind"] == "html_multi":
        # 明列的 urls 優先;否則展開 @token(token 打錯 → 空清單 → unknown,不會靜靜地綠)
        urls = list(sf.get("urls") or []) or _expand_multi(url)
        applicable = R.rules_for(sf["packs"], sf.get("exclude_rules", ()))
        res["rules_run"] = [r["id"] for r in applicable]
        if not urls:
            res["detail"] = "展開後一個網址都沒有(來源清單消失了)"
            return res
        ok_n, unknown_n = 0, 0
        res["partial_unknown"] = 0
        res["corpus"] = {"pages": 0, "cjk_pages": 0, "en_pages": 0, "literals_dropped": 0}
        with concurrent.futures.ThreadPoolExecutor(max_workers=SUB_WORKERS) as ex:
            subs = list(ex.map(lambda u: (u, scan_surface(
                {**sf, "kind": "html", "url": u, "label": u}, write_ledger=False)), urls))
        for u, sub in subs:
            _merge_corpus(res["corpus"], sub.get("corpus"))
            if sub["status"] == UNKNOWN:
                unknown_n += 1
                res["partial_unknown"] = unknown_n
                continue
            ok_n += 1
            for f in sub["findings"]:
                res["findings"].append({**f, "url": u})
        res["url"] = f"{len(urls)} 個網址"
        res["detail"] = f"{ok_n} 頁掃過 / {unknown_n} 頁抓不到 / {len(applicable)} 條規則"
        if res["findings"]:
            res["status"] = VIOLATION
        elif ok_n == 0:
            res["status"] = UNKNOWN
        else:
            res["status"] = CLEAN
            if unknown_n:
                res["detail"] += "(部分頁面未涵蓋)"
        return res

    code, body = fetch(url)
    if code != 200:
        res["detail"] = f"HTTP {code}:{body[:120]}"
        return res
    stats = {}
    text = visible_text(body, stats)
    if len(text) < 200:
        # 抓到了但幾乎沒有字 = 前端整頁 JS 渲染或被擋 → 這不是「乾淨」,是沒看到
        res["detail"] = f"可見文字僅 {len(text)} 字,判定為沒有真的掃到"
        return res
    # 遮罩比例守衛:法定聲明白名單一旦寫成無界 pattern,會把整頁後半段遮成空白,
    # 於是真違規再也不在語料裡而報告一片綠(2026-08-04 驗證者 F1)。挖掉太多=沒真的掃到。
    masked = R.strip_exempt(text)[1]
    if masked > 0.3 * len(text):
        res["detail"] = (f"法定聲明白名單遮掉了 {masked}/{len(text)} 字"
                         f"({masked * 100 // max(len(text), 1)}%)——語料被吃掉,判定為沒有真的掃到")
        return res
    applicable = R.rules_for(sf["packs"], sf.get("exclude_rules", ()))
    for rule in applicable:
        res["rules_run"].append(rule["id"])
        for hit in R.check_rule(rule, text):
            res["findings"].append({"rule": rule["id"], "title": rule["title"],
                                    "severity": rule["severity"], "law": rule["law"],
                                    "pattern": hit["pattern"], "evidence": hit["evidence"]})
    res["status"] = VIOLATION if res["findings"] else CLEAN
    res["detail"] = f"{len(text)} 字 / {len(applicable)} 條規則"
    # 語料觀測性:①這一頁到底有沒有英文進來(全站 i18n,只掃到中文那半=另一半沒人看過,
    # 卻被計入「乾淨 N 面」——驗證者 F5)②有沒有長字串因為上限而被靜默丟掉(F10)。
    res["corpus"] = {"pages": 1,
                     "cjk_pages": 1 if _CJK.search(text) else 0,
                     "en_pages": 1 if _EN_SENTENCE.search(text) else 0,
                     "literals_dropped": stats.get("js_literals_dropped", 0)}
    if res["corpus"]["literals_dropped"]:
        res["detail"] += f"(⚠️ {res['corpus']['literals_dropped']} 個超長字串沒進語料)"
    return res


def run(only=None, write_ledger=True, workers=5):
    ok, problems = R.selfcheck()
    cfg = config_problems()
    report = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "rules_total": len(R.RULES), "selfcheck_ok": ok,
              "selfcheck_problems": problems + cfg,
              "surfaces": [], "unapplied_rules": [], "not_run_due_to_unknown": [],
              "clean": 0, "violation": 0, "unknown": 0,
              "corpus": {"pages": 0, "cjk_pages": 0, "en_pages": 0, "literals_dropped": 0},
              # violation_count 與 exit 分開:exit 3(守衛壞了)會蓋掉 exit 1,
              # 機器讀 exit 時真違規的筆數不可以跟著消失(驗證者 F6)
              "checks_run": 0, "violation_count": 0, "exit": 0}
    if not ok or cfg:
        # 規則庫壞掉、或頁面清單設定過期 → 這次的「乾淨」不算數
        report["selfcheck_ok"] = False
        report["exit"] = 3
        return report

    todo = [s for s in SURFACES if not only or s["id"] in only]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_surface, s, write_ledger): s for s in todo}
        results = []
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                s = futs[f]
                results.append({"id": s["id"], "label": s["label"], "url": s["url"],
                                "status": UNKNOWN, "findings": [], "rules_run": [],
                                "detail": f"掃描器自己爆炸:{type(e).__name__}: {e}"})
    order = {s["id"]: i for i, s in enumerate(SURFACES)}
    report["surfaces"] = sorted(results, key=lambda r: order.get(r["id"], 99))

    applied = set()
    for r in report["surfaces"]:
        report[r["status"]] += 1
        report["checks_run"] += len(r["rules_run"])
        report["violation_count"] += len(r["findings"])
        applied.update(r["rules_run"])
        _merge_corpus(report["corpus"], r.get("corpus"))

    # ⚠️「應該被套用的規則」由 SURFACES 的 packs **靜態推導**,與抓取成敗無關。
    #    拿「成功掃描的 surface」去算的話,任何暫時抓不到的頁面都會讓它獨佔的 pack
    #    變成「從未被套用」→ 誤診成「pack 名打錯/規則庫壞了」並推假告警(驗證者 F6)。
    #    靜態就套不到 = 設定真的壞掉(exit 3);靜態套得到但因 unknown 沒跑到 = exit 2 的事。
    expected = expected_rule_ids(todo)
    report["unapplied_rules"] = sorted(r["id"] for r in R.RULES if r["id"] not in expected)
    report["not_run_due_to_unknown"] = sorted(expected - applied)

    if (report["unapplied_rules"] or report["checks_run"] == 0
            or report["clean"] + report["violation"] == 0):
        report["exit"] = 3
    elif report["violation"]:
        report["exit"] = 1
    elif (report["unknown"] or report["not_run_due_to_unknown"]
          or any(s.get("partial_unknown") for s in report["surfaces"])
          or report["corpus"]["literals_dropped"]):
        # 多網址面裡有子頁抓不到、或有長字串沒進語料 = 部分未涵蓋,不可以宣稱 exit 0 全乾淨
        report["exit"] = 2
    return report


# ── 輸出 ────────────────────────────────────────────────────────────────
_ICON = {CLEAN: "✅", VIOLATION: "🔴", UNKNOWN: "⚠️"}


def render(rep):
    L = []
    if not rep["selfcheck_ok"]:
        L.append("🔴 規則庫自檢失敗——掃描沒有跑。規則壞掉時「全站乾淨」是假的:")
        L += [f"   - {p}" for p in rep["selfcheck_problems"]]
        return "\n".join(L)
    L.append(f"法務合規哨兵 {rep['generated']}  規則 {rep['rules_total']} 條 / "
             f"檢查 {rep['checks_run']} 次")
    L.append(f"  ✅ 乾淨 {rep['clean']} 面 · 🔴 違規 {rep['violation']} 面 · ⚠️ 未涵蓋 {rep['unknown']} 面")
    c = rep.get("corpus") or {}
    if c.get("pages"):
        # 語言分佈是「站台的英文那一半有沒有被看過」的唯一可見證據(驗證者 F5);
        # 掉字計數是「有語料靜默沒進來」的唯一可見證據(F10)。兩個都是零覆蓋率偵測器。
        L.append(f"  語料 {c['pages']} 頁(含中文 {c['cjk_pages']} · 含英文 {c['en_pages']})"
                 + (f" · ⚠️ {c['literals_dropped']} 個超長字串沒進語料" if c["literals_dropped"] else ""))
        if not c["en_pages"]:
            L.append("  ⚠️ 這批語料一句英文都沒有——全站有 i18n 中英切換,英文那一半可能沒被掃到")
    if rep["unapplied_rules"]:
        L.append(f"  🔴 有規則一次都沒被套用(pack 名打錯?):{', '.join(rep['unapplied_rules'])}")
    L.append("")
    for s in rep["surfaces"]:
        stale = s.get("stale_days")
        age = f"(存檔是 {stale} 天前那份)" if stale else ""
        L.append(f"{_ICON[s['status']]} {s['id']:<18} {s['label']}  {s['detail']}{age}")
        if s["status"] == UNKNOWN:
            L.append(f"     ↳ {s['url']}")
        for f in s["findings"]:
            L.append(f"     ✗ [{f['severity']}] {f.get('title') or f['rule']} — {f['law']}")
            L.append(f"       證據:{f['evidence'][:160]}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true", help="只跑規則庫自檢,不連網")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-ledger", action="store_true", help="不寫促銷帳本(測試用)")
    a = ap.parse_args(argv)

    if a.offline:
        ok, problems = R.selfcheck()
        rep = {"generated": "offline", "rules_total": len(R.RULES), "selfcheck_ok": ok,
               "selfcheck_problems": problems, "surfaces": [], "unapplied_rules": [],
               "clean": 0, "violation": 0, "unknown": 0, "checks_run": 0, "exit": 0 if ok else 3}
        print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else
              (f"規則庫自檢:{'✅ 全過' if ok else '🔴 失敗'}({len(R.RULES)} 條)" +
               ("" if ok else "\n" + "\n".join("  - " + p for p in problems))))
        return rep["exit"]

    only = [x for x in a.only.split(",") if x] or None
    rep = run(only=only, write_ledger=not a.no_ledger)
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else render(rep))
    return rep["exit"]


if __name__ == "__main__":
    sys.exit(main())
