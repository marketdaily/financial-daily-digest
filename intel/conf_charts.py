"""法說會簡報「圖表裡的數字」抽取(信息差引擎積木 #8b,補 tw_investor_materials 的已知天花板)。

背景:`tw_investor_materials.py` 用 PyMuPDF 抽文字層餵 Ollama 摘要,但法說會簡報的財測/營收
結構數字大量畫在圖表裡,文字層完全看不到。該模組註解原本把這記為「摘要品質上限…不是 bug」,
本檔把那個上限補掉。實測樣本:宇隆(2233)簡報 p4 文字層僅 17 字(`營收應用別占比與目標
2027年`),該頁實際有 9 年 × 4 應用別共 36 個營收占比數據。

兩段式,各用各的強項(2026-07-30 於 winrig 5080 實測校準,非推論):
1. 本地 Unlimited-OCR(baidu/Unlimited-OCR,3B,MIT)= 免費的**區域偵測器**:輸出
   `<|det|>chart [x1,y1,x2,y2]<|/det|>` / `<|det|>image ...` / `<|det|>table ...`,能語意區分
   「資料圖表」與「裝飾照片」。
2. Gemini vision 只讀被標為 chart 的頁 → 結構化 JSON(實測宇隆 p4 36 個數據點全對)。

⚠️坑(2026-07-30 實測記錄,省後人重踩):
1. Unlimited-OCR 偵測到 chart 後【刻意不轉錄內容】——`document parsing.` / `OCR.` /
   `Free OCR.` / `OCR with format.` 四種 prompt 實測行為一致,一律吐 det 框然後留白。
   它只能當偵測器,**不可**拿來讀圖表數字。
2. 不可用 PyMuPDF 的「圖片覆蓋率」heuristic 選頁:裝飾照片頁(大魯閣 p10 兒童樂園照,
   圖覆蓋 104%)一樣高覆蓋率,實測 10 份簡報誤判過半。必須用 OCR 的語意標籤才準。
3. Gemini inline_data 圖片過大直接 HTTP 400(實測 6000×3375 即 400),送出前必須縮到
   長邊 ≤ MAX_SIDE。縮圖後 194KB base64 正常。
4. `model.infer()` 回傳 None,det 標籤只印到 stdout → 必須 redirect_stdout 捕捉。
5. Gemini 2.5 系 thinking 會吃 maxOutputTokens 額度(見 memory
   reference_gemini_thinking_max_tokens 的殘章事故)→ 必檢查 finishReason,MAX_TOKENS
   視同失敗換下一個 model/key,不可把截斷結果當成功。
6. 模型載入約 10s、每頁偵測 2-5s。worker 一次載入處理整批,禁止每份 PDF 重載模型。
7. 本檔需 torch+transformers,只在 winrig(GPU)可跑;`intel/patrol.py` 那端**不 import 本檔**,
   走 queue/cache 檔案介面解耦,無 GPU 環境完全不受影響(fail-open)。
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout

try:
    import fitz
except ImportError:
    fitz = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(HERE, ".conf_chart_queue.json")
CACHE = os.path.join(HERE, ".conf_chart_cache.json")

MODEL_NAME = os.environ.get("UNLIMITED_OCR_MODEL", "baidu/Unlimited-OCR")
DPI = 200
MAX_SIDE = 1600
MAX_PDFS_PER_RUN = int(os.environ.get("CONF_CHART_MAX_PDFS", "3"))
MAX_PAGES_PER_PDF = 40
MAX_CHART_PAGES_PER_PDF = 8
CACHE_TTL_DAYS = 120

GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
DET_RE = re.compile(r"<\|det\|>(\w+)\s*\[([^\]]*)\]<\|/det\|>")

CHART_PROMPT = """Role: You are a financial data extractor reading one slide from a Taiwan
listed company's investor conference deck.

Task: Read EVERY data point rendered inside the chart(s) on this slide and return it as JSON.

Constraints (all verifiable):
1. Output ONE JSON object only. No prose, no markdown fences.
2. Transcribe numbers exactly as printed, including the unit or % sign as shown.
3. Never infer, interpolate, or round a value you cannot actually read. Omit it instead.
4. If the slide has no data chart (only photos, logos, or plain text), return
   {"has_chart": false, "charts": []}.
5. Keep any Chinese label in Traditional Chinese exactly as printed.

Schema:
{"has_chart": true,
 "charts": [{"title": "", "chart_type": "bar|line|pie|stacked_bar|table|other",
             "categories": [""],
             "series": [{"name": "", "values": [""]}],
             "notes": ""}]}"""


def _log(msg):
    """cron log 導向檔案時 print 是塊緩衝的,不 flush 會看不到進度(只在收工才一次吐)。"""
    print(msg, flush=True)


def _env(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return d


def _gemini_keys():
    """只回 key1。**絕不碰 GEMINI_API_KEY_2**——那是日報保留桶。

    2026-07-30 修正:原本回傳兩把 key,違反 analyzer._call_gemini 訂下的分區鐵則
    「日報 run(DIGEST_RUN=1)key2 優先、key1 溢流;背景呼叫端只准 key1」。本 worker 是
    背景 cron(03:20),而台股早報 05:20 就要用 key2——中間只隔 2 小時,免費層是 RPD(日配額),
    03:20 燒掉的額度早報拿不回來。這正是 07-23/24/27 三場日報品質事故的成因
    (「整夜背景工作把 RPD 吃光 → 全程弱模型鏈 → reason 塌陷/8 位掉 deterministic」)。
    圖表抽取是 nice-to-have,日報品質不是——衝突時本 worker 讓路。

    ⚠️ 刻意與 scripts/build_tw_bizdesc.py、scripts/seo_articles.py 的慣例
    (`[key1] or [key2]`,key1 缺失時拿 key2 墊底)不同:本 worker 連墊底都不拿,key1 沒了就
    直接不做。理由=那兩支的產出(SEO 文章/公司簡述)缺了要補很麻煩,本 worker 的產出是可重建
    的衍生快取,下一輪窗口再跑就有。別「順手統一」成有 key2 墊底的版本。
    """
    e = _env(os.path.join(ROOT, ".env"))
    k1 = e.get("GEMINI_API_KEY")
    return [k1] if k1 else []


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def enqueue(filename, code="", name=""):
    """把一份簡報排進 OCR 佇列(patrol 端呼叫,零 GPU 依賴)。已在佇列/已有快取則 no-op。"""
    if not filename:
        return False
    if filename in _load_json(CACHE, {}):
        return False
    q = _load_json(QUEUE, [])
    if any(item.get("filename") == filename for item in q):
        return False
    q.append({"filename": filename, "code": code, "name": name, "ts": int(time.time())})
    _save_json(QUEUE, q)
    return True


def cached_charts(filename):
    """已抽好的圖表資料 → list[chart dict],沒有就 []。patrol 端呼叫,零 GPU 依賴。"""
    entry = _load_json(CACHE, {}).get(filename)
    if not entry:
        return []
    return entry.get("charts", [])


def charts_as_text(charts, max_charts=6):
    """圖表 JSON → 給 LLM 摘要用的純文字段落(接在文字層後面)。"""
    if not charts:
        return ""
    lines = ["【簡報圖表數據(OCR+視覺模型抽取)】"]
    for c in charts[:max_charts]:
        title = (c.get("title") or "").strip()
        lines.append(f"◆ {title or c.get('chart_type', '圖表')}")
        cats = c.get("categories") or []
        if cats:
            lines.append("  期別:" + "、".join(str(x) for x in cats[:20]))
        for s in (c.get("series") or [])[:8]:
            vals = "、".join(str(v) for v in (s.get("values") or [])[:20])
            lines.append(f"  {s.get('name', '')}:{vals}")
        if c.get("notes"):
            lines.append(f"  註:{c['notes']}")
    return "\n".join(lines)


def _tonum(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def chart_facts(charts, max_facts=3):
    """圖表 JSON → 確定性事實行(**不經 LLM**)。

    2026-07-30 實測教訓:把圖表數據餵進 Ollama 摘要,14b 會把 36 個數據點消化成
    「汽車應用仍為主要收入來源」這種沒有數字的空話,連原本文字層抓到的營收數字都弄丟
    (摘要格式每條限 40 字、最多 5 條,本來就裝不下數據序列)。數字必須走確定性路徑,
    不可交給摘要模型保管——同 feedback_zero_error_no_miss 的 deterministic fallback 原則。

    取法:每個 series 的「最後一期 vs 前一期」,依變化幅度排序取前 max_facts 條。
    法說會簡報的信息差在最新期的結構變化,不在完整歷史序列。
    """
    scored = []
    for c in charts:
        cats = [str(x).strip() for x in (c.get("categories") or [])]
        if len(cats) < 2:
            continue
        title = (c.get("title") or "").strip()
        for s in (c.get("series") or []):
            vals = s.get("values") or []
            if len(vals) < 2 or len(vals) != len(cats):
                continue
            cur, prev = str(vals[-1]).strip(), str(vals[-2]).strip()
            ncur, nprev = _tonum(cur), _tonum(prev)
            if ncur is None or nprev is None or ncur == nprev:
                continue
            name = (s.get("name") or "").strip()
            # 期別與數值之間必須留空白:「2026年Q1」+「77%」黏成「2026年Q177%」會被讀成
            # 另一個數字,財經產品不留這種歧義。
            scored.append((abs(ncur - nprev),
                           f"{title}·{name} {cats[-2]} {prev} → {cats[-1]} {cur}"))
    scored.sort(key=lambda x: -x[0])
    return [line for _, line in scored[:max_facts]]


def _load_model():
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        MODEL_NAME, trust_remote_code=True, use_safetensors=True,
        torch_dtype=torch.bfloat16).eval().cuda()
    return model, tok


def detect_regions(model, tok, image_path):
    """單頁 → list[(label, bbox)]。infer() 回 None,det 標籤只在 stdout,故攔截 stdout。"""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            model.infer(tok, prompt="<image>document parsing.", image_file=image_path,
                        output_path="/tmp/_conf_chart_out", base_size=1024, image_size=640,
                        crop_mode=True, max_length=32768, no_repeat_ngram_size=35,
                        ngram_window=128, save_results=False)
    except Exception:
        return []
    out = []
    for label, box in DET_RE.findall(buf.getvalue()):
        nums = [int(x) for x in re.findall(r"\d+", box)]
        out.append((label, nums))
    return out


def _shrink(png_path):
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    out = png_path.replace(".png", "_s.png")
    im.save(out)
    return out


def read_chart_page(png_path, keys=None):
    """chart 頁圖片 → dict(Gemini vision),全部 model/key 都失敗回 None(fail-open)。"""
    import base64
    keys = keys or _gemini_keys()
    if not keys:
        return None
    small = _shrink(png_path)
    img = base64.b64encode(open(small, "rb").read()).decode()
    body = json.dumps({
        "contents": [{"parts": [{"text": CHART_PROMPT},
                                {"inline_data": {"mime_type": "image/png", "data": img}}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
    }).encode()
    for model in GEMINI_MODELS:
        for key in keys:
            try:
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                    f":generateContent?key={key}",
                    data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.loads(r.read())
                cand = out["candidates"][0]
                if cand.get("finishReason") == "MAX_TOKENS":
                    continue
                txt = cand["content"]["parts"][0]["text"].strip()
                if txt.startswith("```"):
                    txt = re.sub(r"^```\w*\n?|\n?```$", "", txt).strip()
                data = json.loads(txt)
                if not data.get("has_chart"):
                    return None
                return data
            except Exception:
                time.sleep(1)
    return None


def process_pdf(model, tok, filename, code="", name="", log=_log):
    """一份簡報 → {"charts": [...], "pages_scanned": n, "chart_pages": [...]}。"""
    from intel import tw_investor_materials as tim
    pdf = tim.download_pdf(filename)
    if not pdf or fitz is None:
        log(f"  {filename}: 下載失敗或無 PyMuPDF")
        return None
    doc = fitz.open(stream=pdf, filetype="pdf")
    total = len(doc)
    n_scan = min(total, MAX_PAGES_PER_PDF)
    if total > n_scan:
        log(f"  {filename}: {total} 頁,只掃前 {n_scan} 頁(MAX_PAGES_PER_PDF)")
    mat = fitz.Matrix(DPI / 72, DPI / 72)
    tmp = "/tmp/_conf_chart_pages"
    os.makedirs(tmp, exist_ok=True)
    chart_pages, charts = [], []
    for i in range(n_scan):
        png = os.path.join(tmp, f"{filename}_{i:03d}.png")
        doc[i].get_pixmap(matrix=mat).save(png)
        labels = [lbl for lbl, _ in detect_regions(model, tok, png)]
        if "chart" in labels:
            chart_pages.append(i)
        else:
            os.remove(png)
    doc.close()
    if len(chart_pages) > MAX_CHART_PAGES_PER_PDF:
        log(f"  {filename}: 偵測到 {len(chart_pages)} 個圖表頁,只讀前 "
            f"{MAX_CHART_PAGES_PER_PDF} 頁(MAX_CHART_PAGES_PER_PDF)")
        chart_pages = chart_pages[:MAX_CHART_PAGES_PER_PDF]
    keys = _gemini_keys()
    for i in chart_pages:
        png = os.path.join(tmp, f"{filename}_{i:03d}.png")
        data = read_chart_page(png, keys)
        if data:
            for c in data.get("charts", []):
                c["page"] = i + 1
                charts.append(c)
        for leftover in (png, png.replace(".png", "_s.png")):
            try:
                os.remove(leftover)
            except OSError:
                pass
    log(f"  {filename}({code} {name}): 掃 {n_scan} 頁 → 圖表頁 {len(chart_pages)} → "
        f"抽出 {len(charts)} 張圖表")
    return {"charts": charts, "pages_scanned": n_scan,
            "chart_pages": [i + 1 for i in chart_pages], "ts": int(time.time())}


def run_worker(log=_log):
    """佇列 worker:一次載入模型,處理最多 MAX_PDFS_PER_RUN 份。回 (處理數, 剩餘數)。"""
    queue = _load_json(QUEUE, [])
    if not queue:
        log("佇列為空,無事可做")
        return 0, 0
    cache = _load_json(CACHE, {})
    batch = [it for it in queue if it.get("filename") not in cache][:MAX_PDFS_PER_RUN]
    if not batch:
        _save_json(QUEUE, [])
        log(f"佇列 {len(queue)} 筆全部已在快取,清空")
        return 0, 0
    log(f"佇列 {len(queue)} 筆,本輪處理 {len(batch)} 筆(MAX_PDFS_PER_RUN={MAX_PDFS_PER_RUN})")
    model, tok = _load_model()
    done = 0
    for item in batch:
        fn = item["filename"]
        try:
            res = process_pdf(model, tok, fn, item.get("code", ""), item.get("name", ""), log)
        except Exception as e:
            log(f"  {fn}: 例外 {type(e).__name__}: {str(e)[:120]}")
            res = None
        cache[fn] = res or {"charts": [], "pages_scanned": 0, "chart_pages": [],
                            "ts": int(time.time()), "failed": True}
        done += 1
        _save_json(CACHE, cache)
    remaining = [it for it in queue if it.get("filename") not in cache]
    _save_json(QUEUE, remaining)
    log(f"完成 {done} 筆,佇列剩 {len(remaining)} 筆")
    return done, len(remaining)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--enqueue":
        print(enqueue(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
    elif len(sys.argv) > 1 and sys.argv[1] == "--show":
        cs = cached_charts(sys.argv[2])
        print(charts_as_text(cs) or "(無快取)")
    else:
        sys.path.insert(0, ROOT)
        run_worker()
