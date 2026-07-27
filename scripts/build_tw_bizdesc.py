"""全台股「公司在幹嘛」白話簡介生成(docs/tw-bizdesc.js)。
LLM(Gemini flash)批次生成+確定性審計層(長度/禁詞/中文比例,不過關 fallback 產業模板)+
斷點快取(scripts/.tw_bizdesc_cache.json,重跑只補缺)。--verify 抽樣獨立事實查核。
ETF 不走 LLM(確定性標籤)。prompt 依 genai-prompt-pro Part 6(Role→Context→Task→
編號可測約束→schema+filled example→資料不足範例,最終 prompt 英文)。"""
import json
import os
import random
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
CACHE = os.path.join(HERE, ".tw_bizdesc_cache.json")
OUT = os.path.join(DOCS, "tw-bizdesc.js")
BATCH = 40
MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

PROMPT = """Role: You are a Taiwan stock market data editor writing factual one-line company
descriptions in Traditional Chinese for a finance app.

Context: Each input line is a Taiwan-listed company: stock code, Chinese name, and its
official TWSE/TPEx industry category. Descriptions are shown in a stock-detail page under
「公司簡介」. Readers are retail investors.

Task: For each company, write ONE plain-language Traditional Chinese sentence describing
what the company actually does (its main business / products / position).

Constraints (all verifiable):
1. 12-48 Traditional Chinese characters per description. No line breaks.
2. Facts only: main products, services, business model, market position. If you are NOT
   confident about this specific company, derive a safe generic description from its name
   and industry category, and set "c":"low".
3. Forbidden: any numbers or percentages, stock advice words (買進/賣出/看好/目標價),
   superlatives you cannot verify (第一/最大 — allowed ONLY for widely known facts like
   台積電=晶圓代工龍頭), English words except universal acronyms (DRAM, IC, PCB, LED, AI, ETF).
4. Neutral tone. No marketing adjectives (領先/卓越/優質).
5. Output STRICT JSON array only — no markdown fences, no commentary.

Output schema with filled examples:
[{"code":"2408","d":"DRAM 記憶體製造廠,產品用於伺服器、行動裝置與消費性電子","c":"high"},
 {"code":"9999","d":"主營電子零組件相關產品之製造與銷售","c":"low"}]

Edge case: the second example above shows the required fallback when you do not reliably
know the company — generic but true, derived from industry category, marked "c":"low".

Companies:
"""


def env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


E = env(os.path.join(ROOT, ".env"))
# key2=日報保留桶(2026-07-27 配額分區):背景腳本只准 key1,見 analyzer._call_gemini
KEYS = [k for k in (E.get("GEMINI_API_KEY"),) if k] or [k for k in (E.get("GEMINI_API_KEY_2"),) if k]


def _gemini(prompt, model, key, temperature):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096}}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read().decode())
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _claude(prompt, temperature):
    body = json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 4096,
                       "temperature": temperature,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type": "application/json", "x-api-key": E.get("ANTHROPIC_API_KEY", ""),
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    return out["content"][0]["text"]


def llm(prompt, temperature=0.2):
    last = None
    for attempt in (
        lambda: _gemini(prompt, MODELS[0], KEYS[0], temperature),
        lambda: _gemini(prompt, MODELS[1], KEYS[-1], temperature),
        lambda: _claude(prompt, temperature),
    ):
        try:
            return attempt()
        except Exception as ex:
            last = ex
            if "429" in str(ex):
                time.sleep(5)
    raise RuntimeError(f"all providers failed: {last}")


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("["), t.rfind("]")
    return json.loads(t[i:j + 1])


ZH_RE = re.compile(r"[一-鿿]")
BAD_RE = re.compile(r"\d{2,}|%|買進|賣出|看好|看壞|目標價|建議|推薦|領先|卓越|優質")


def audit(desc, industry):
    """確定性審計:過=原文;不過=產業 fallback。回 (desc, ok)。"""
    d = (desc or "").strip().replace("\n", "")
    n_zh = len(ZH_RE.findall(d))
    if 8 <= n_zh <= 60 and len(d) <= 80 and not BAD_RE.search(d):
        return d, True
    return f"主營{industry}相關業務(簡介整理中)", False


def load_universe():
    ind_src = open(os.path.join(DOCS, "tw-industry.js"), encoding="utf-8").read()
    industry = json.loads(re.search(r"const TW_INDUSTRY = (\{.*?\});", ind_src, re.S).group(1))
    stocks_src = open(os.path.join(DOCS, "stocks.js"), encoding="utf-8").read()
    m = re.search(r"const TW_STOCKS_FULL = \[(.*?)\];", stocks_src, re.S)
    names = dict(re.findall(r'\["([0-9A-Z]+)","([^"]*)"\]', m.group(1)))
    return industry, names


def main():
    industry, names = load_universe()
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE, encoding="utf-8"))

    todo = []
    for code, ind in industry.items():
        if code in cache:
            continue
        if ind == "ETF":
            cache[code] = {"d": "指數股票型基金(ETF)", "c": "etf"}
            continue
        todo.append((code, names.get(code, code), ind))
    print(f"宇宙 {len(industry)} 檔;已快取 {len(cache)};待生成 {len(todo)}")

    fallback_n = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        lines = "\n".join(f"{c} {n} [{ind}]" for c, n, ind in chunk)
        try:
            rows = parse_json(llm(PROMPT + lines))
        except Exception as ex:
            print(f"batch {i//BATCH} 失敗:{ex}")
            continue
        got = {str(r.get("code")): r for r in rows if r.get("code")}
        for c, n, ind in chunk:
            r = got.get(c)
            d, ok = audit(r.get("d") if r else None, ind)
            conf = (r.get("c") if r and ok else "low") or "low"
            if not ok:
                fallback_n += 1
            cache[c] = {"d": d, "c": conf}
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"batch {i//BATCH + 1}/{(len(todo)+BATCH-1)//BATCH} 完成(累計 {len(cache)})")
        time.sleep(3)

    biz = {c: v["d"] for c, v in cache.items()}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by scripts/build_tw_bizdesc.py — LLM 生成+確定性審計,快取 .tw_bizdesc_cache.json\n")
        f.write("const TW_BIZ = " + json.dumps(biz, ensure_ascii=False, separators=(",", ":")) + ";\n")
    lows = sum(1 for v in cache.values() if v["c"] == "low")
    print(f"{len(biz)} 檔 → {OUT} ({os.path.getsize(OUT)//1024}KB);low-confidence {lows};審計fallback {fallback_n}")


VERIFY_PROMPT = """Role: You are an independent fact-checker for Taiwan stock data.
Task: For each line (stock code, company name, proposed description), judge whether the
description is factually consistent with what that company actually does.
Constraints: 1. Answer for every line. 2. verdict must be "ok", "wrong", or "unsure".
3. "wrong" only when the description clearly mismatches the company's real business.
4. Output STRICT JSON array only, e.g. [{"code":"2330","verdict":"ok"}].
Lines:
"""


def verify(n=15):
    cache = json.load(open(CACHE, encoding="utf-8"))
    industry, names = load_universe()
    pool = [(c, v) for c, v in cache.items() if v["c"] not in ("low", "etf")]
    random.seed(20260722)
    sample = random.sample(pool, min(n, len(pool)))
    lines = "\n".join(f"{c} {names.get(c, c)}: {v['d']}" for c, v in sample)
    rows = parse_json(llm(VERIFY_PROMPT + lines, temperature=0.0))
    verdicts = {str(r["code"]): r["verdict"] for r in rows}
    ok = sum(1 for c, _ in sample if verdicts.get(c) == "ok")
    for c, v in sample:
        print(f"  {verdicts.get(c, '?'):6s} {c} {names.get(c, c)}: {v['d']}")
    print(f"驗證:{ok}/{len(sample)} ok")
    return 0 if ok >= len(sample) - 2 else 1


if __name__ == "__main__":
    if "--verify" in sys.argv:
        sys.exit(verify())
    main()
