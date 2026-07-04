"""台股法說會簡報 PDF 抓取+摘要(信息差引擎積木 #8,curriculum I 節「內容型」信息源第二項)。
`tw_investor_conf.py`(#7)只抓「法說會何時開」;這裡再往下一層——法說會真正有價值的是
簡報內容本身(財測數字、產業展望、風險揭露),此積木把 PDF 材料變成可讀摘要。

資料源:MOPS 法人說明會日程表同一份回應內,cells[6]/[7](中/英簡報 PDF onclick fileName)。
下載端點(2026-07-03 探測,已用 1432 大魯閣真實檔案驗證,5.8MB PDF 200 OK):
  POST https://mopsov.twse.com.tw/server-java/FileDownLoad
  body: step=9&filePath=/home/html/nas/STR/&fileName=<cells[6]/[7]抓到的檔名>&functionName=t100sb02_1
  免token、免CSRF(比 tw_holders 的 TDCC 好打很多)。

文字抽取:系統已裝 PyMuPDF(fitz),無需額外安裝(pypdf/pdfplumber皆未裝)。
摘要:呼叫本機 Ollama(qwen2.5:14b,零限流零成本),沿用 ~/gooaye_study/resume_extract.py
同款 ollama_generate()/loads_loose() 呼叫慣例(2026-07-03 修好 CPU fallback 後驗證穩定的積木)。

⚠️坑(2026-07-03 探測記錄,省後人重踩):
1. 只有真的有上傳材料的公司,cells[6]/[7] 才是 <a onclick=...fileName.value='XXX.pdf'...>;
   沒材料時是純文字(通常「無」或空白),FILENAME_RE 抓不到就回 None,呼叫端必須檢查再下載。
2. PDF 檔案可能達 5-10MB(圖表多的簡報常見),抽取純文字通常僅 5-15K 字元(圖片/圖表不含文字層),
   別預期能抽到圖表數字——這類法說會簡報的財測數字常在圖片裡,純文字抽取抓不到,摘要品質上限
   受限於此,不是 bug。
3. 不可對全市場批次下載(帶寬/CPU/禮貌爬蟲考量)——只在 watchlist 個股訊號 level 為 red/yellow
   (法說會在 20 天內)且有 pdf_zh 時才觸發下載,呼叫端(patrol.py)負責這個過濾,本模組只提供
   函式不主動批次跑。
4. Ollama 摘要失敗(逾時/JSON 格式錯誤)一律回 None,不擋主流程——這是「加值」不是「必要」欄位,
   patrol.py 沒有材料摘要一樣要能正常輸出法說會時程訊號(同其餘 connector 的 no-op 失敗風格)。
5. num_ctx 太小會讓 Ollama 在還沒吐完 JSON 前被截斷,format=json 模式下截斷結果是合法但不完整
   的字串(如只回 `{`),不會報錯,容易誤判為「模型壞了」——中文字元 token 數約是字元數的
   1.5-2 倍(不是 1:1),10K 字元中文文本用 num_ctx=8192 實測直接截斷,32768 才穩定跑完整份
   JSON。任何處理中文長文本的 Ollama 呼叫,num_ctx 抓字元數×2 再抓整數才安全。
"""
import json
import re
import time
import urllib.request
import urllib.parse

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

DOWNLOAD_URL = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
UA = "Mozilla/5.0"
OLLAMA_MODEL = "qwen2.5:14b-instruct-q4_K_M"
MAX_CHARS_FOR_SUMMARY = 12000  # 超過就截斷,避免 num_ctx 爆掉/摘要跑太久

SUMMARY_PROMPT = """你是財經分析助理。以下是台股上市櫃公司「{name}({code})」法人說明會簡報的文字內容
(PDF 抽取,圖表數字可能缺漏,只有文字層)。請只輸出一個 JSON 物件(繁體中文),結構如下,不要有其他文字:
{{
 "highlights": ["重點1(如營運展望/財測/新產能/風險揭露等,最多5條,每條不超過40字)", "..."],
 "has_guidance": true或false(是否提到具體財測數字或明確展望方向),
 "tone": "positive/neutral/negative(整體展望語氣)"
}}
簡報內容:
---
{text}
---"""


def download_pdf(filename, timeout=30):
    """回 PDF bytes,失敗回 None(不 raise,呼叫端可安全串接)。"""
    if not filename:
        return None
    data = urllib.parse.urlencode({
        "step": "9", "filePath": "/home/html/nas/STR/",
        "fileName": filename, "functionName": "t100sb02_1",
    }).encode()
    try:
        req = urllib.request.Request(DOWNLOAD_URL, data=data, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        if not body.startswith(b"%PDF"):
            return None
        return body
    except Exception:
        return None


def extract_text(pdf_bytes):
    """PDF bytes → 純文字,失敗回 ""。"""
    if not pdf_bytes or fitz is None:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _loads_loose(s):
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\n?|\n?```$", "", s)
    i = s.find("{")
    if i >= 0:
        s = s[i:]
    last = s.rfind("}")
    if last >= 0:
        s = s[:last + 1]
    return json.loads(s)


def _ollama_generate(prompt, num_ctx=32768, timeout=240, retries=2):
    body = json.dumps({
        "model": OLLAMA_MODEL, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read())
            return j["response"]
        except Exception:
            if attempt + 1 < retries:
                time.sleep(3)
    return None


def summarize(text, name="", code=""):
    """text → dict{highlights, has_guidance, tone} 或 None(抽取內容太少/Ollama 失敗)。"""
    text = (text or "").strip()
    if len(text) < 200:
        return None
    snippet = text[:MAX_CHARS_FOR_SUMMARY]
    prompt = SUMMARY_PROMPT.format(name=name, code=code, text=snippet)
    raw = _ollama_generate(prompt)
    if raw is None:
        return None
    try:
        data = _loads_loose(raw)
    except Exception:
        return None
    if not isinstance(data.get("highlights"), list):
        return None
    data["highlights"] = [str(h)[:60] for h in data["highlights"][:5]]
    return data


def fetch_materials(code, name, conf_entry):
    """conf_entry(tw_investor_conf.investor_conf()/scan() 的單筆結果) → 摘要 dict 或 None。
    呼叫端負責只在 red/yellow 時呼叫(避免對全市場批次下載),本函式本身不做 level 過濾。"""
    if not conf_entry:
        return None
    filename = conf_entry.get("pdf_zh") or conf_entry.get("pdf_en")
    if not filename:
        return None
    pdf_bytes = download_pdf(filename)
    text = extract_text(pdf_bytes)
    return summarize(text, name=name, code=code)


if __name__ == "__main__":
    import sys
    fn = sys.argv[1] if len(sys.argv) > 1 else "143220260630M003.pdf"
    nm = sys.argv[2] if len(sys.argv) > 2 else "測試公司"
    pdf = download_pdf(fn)
    txt = extract_text(pdf)
    print(f"pdf_bytes={len(pdf) if pdf else 0} text_chars={len(txt)}")
    print(json.dumps(summarize(txt, name=nm), ensure_ascii=False, indent=1))
