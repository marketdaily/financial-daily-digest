"""BLACKEDGE · GEO 席 —— AI 引用缺口偵測器。

問題:買家已經在問 AI「最好的 X 是什麼」,AI 引用誰,誰就拿到流量。
Okara 的 GEO Agent 只告訴你「偵測到 N 個引用缺口」;這支把 AI **真正引用的來源 URL**
抓下來逐一比對,每個缺口都附可查證的競品清單 —— 缺口不是推論,是有出處的事實。

誠實邊界(寫進輸出,不准對外含糊):
  · 引擎是 Gemini + Google Search grounding。它是「AI 答案引擎會引用誰」的一個真實樣本,
    **不等於** ChatGPT / Google AI Overview 的引用結果。不得由此宣稱「你不在 ChatGPT 裡」。
  · 每次 grounding 的搜尋詞與引用集合會浮動;單次結果是快照,趨勢要看帳本累積。
  · API 失敗一律不寫檔、不覆蓋舊快照(fail-closed)—— 寧可沒有資料,不要有假資料。

用法:
    python3 -m marketing.team.geo_agent scan                 # 掃全部品牌
    python3 -m marketing.team.geo_agent scan --brand marketdaily
    python3 -m marketing.team.geo_agent report
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATE = HERE / "geo_state.json"
LEDGER = HERE / "geo_ledger.jsonl"
QUERIES = HERE / "geo_queries.json"
MODEL = "gemini-2.5-flash"
# 免費層配額是「每模型每分鐘」分桶的 —— 這把 key 同時被日報/新聞快評吃,
# 換模型 = 換一個全新的配額桶,比乾等有效。
# ⚠️ 2026-08-20 實查:`gemini-2.0-flash` 在這把 key 上【不存在】(404) —— 原本三個配額桶
# 只有兩個是真的。名單一律用 models API 列出來、而且實際打過的名字。
MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-3.5-flash",
                   "gemini-2.5-flash-lite", "gemini-3.5-flash-lite"]
ENGINE_NOTE = ("Gemini 2.5 Flash + Google Search grounding。這是「AI 答案引擎會引用誰」的一個真實樣本,"
               "不等於 ChatGPT / Google AI Overview 的引用結果。")


def _load_keys():
    """所有可用的 Gemini key(免費層配額分區,第一把撞 429 就換第二把)。"""
    names = ("GEMINI_API_KEY", "GEMINI_API_KEY_2")
    found = {}
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
            for n in names:
                if line.startswith(n + "="):
                    found[n] = line.split("=", 1)[1].strip().strip('"').strip("'")
    for n in names:
        v = os.environ.get(n)
        if v:
            found.setdefault(n, v)
    return [found[n] for n in names if found.get(n)]


def _call(query, key, timeout=90, model=MODEL):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]}
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout)), model


def ask_grounded(query, keys, timeout=90, tries=4, dead=None):
    """回傳 (answer_text, [{'domain':..,'uri':..}]) 或拋例外。絕不回半套資料。

    免費層 grounding 配額很緊。策略:
      · 429 = 這把 key 現在滿了 → 換下一把;全部滿了才指數退避重試。
      · 其他錯(401/404 等)= 這把 key 根本不能用 → 標死,之後不再浪費時間試它,
        但**不因此放棄整題** —— 一把壞 key 不該蓋掉另一把只是暫時限流的 key。
    """
    dead = dead if dead is not None else set()
    r, last = None, None
    for attempt in range(tries):
        alive = [k for k in keys if any((k, m) not in dead for m in MODEL_FALLBACKS)]
        if not alive:
            break
        for key in alive:
            for model in MODEL_FALLBACKS:
                if (key, model) in dead:
                    continue
                try:
                    r, used = _call(query, key, timeout, model)
                    break
                except urllib.error.HTTPError as e:
                    last = e
                    if e.code != 429:
                        dead.add((key, model))
                    r = None
                except Exception as e:
                    last = e
                    r = None
            if r is not None:
                break
        if r is not None:
            break
        time.sleep(min(45, 6 * (2 ** attempt)))
    if r is None:
        raise last if last else RuntimeError("no usable key")
    cand = r["candidates"][0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    chunks = cand.get("groundingMetadata", {}).get("groundingChunks", []) or []
    cites = []
    for c in chunks:
        w = c.get("web") or {}
        dom = (w.get("title") or "").strip().lower()
        if dom:
            cites.append({"domain": dom, "uri": w.get("uri", "")})
    return text, cites, used


def resolve(uri, timeout=15):
    """把 grounding redirect 解成真實 URL(給老闆可點的競品連結);解不開就回原樣。"""
    try:
        req = urllib.request.Request(uri, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return uri


def default_queries():
    return {
        "marketdaily": {
            "domains": ["marketdaily.ai"],
            "queries": [
                "What are the best free daily stock market email newsletters for Taiwan investors?",
                "台股每日盤前分析電子報推薦 免費",
                "AI 選股 每日報告 台股 美股 推薦服務",
                "free AI-generated daily stock analysis newsletter US and Taiwan stocks",
            ],
        },
        "mingshu": {
            "domains": ["mingshu.tw"],
            "queries": [
                "線上八字命書 客製化 推薦",
                "AI 紫微斗數 命盤 命書 線上服務推薦",
                "2026 流年運勢 個人化命書 哪裡買",
            ],
        },
    }


def load_queries():
    if QUERIES.exists():
        return json.loads(QUERIES.read_text(encoding="utf-8"))
    q = default_queries()
    QUERIES.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return q


def scan(brand=None, resolve_urls=True, max_resolve=6):
    keys = _load_keys()
    if not keys:
        print("GEMINI_API_KEY 不存在 —— 不寫檔、不猜。", file=sys.stderr)
        return 2
    cfg = load_queries()
    targets = {brand: cfg[brand]} if brand else cfg
    if brand and brand not in cfg:
        print(f"未知品牌 {brand};已設定的有 {list(cfg)}", file=sys.stderr)
        return 2

    results, gaps, errors = [], [], []
    dead = set()
    for bname, bcfg in targets.items():
        ours = [d.lower() for d in bcfg["domains"]]
        for q in bcfg["queries"]:
            try:
                text, cites, used_model = ask_grounded(q, keys, dead=dead)
            except Exception as e:
                errors.append({"brand": bname, "query": q,
                               "error": f"{type(e).__name__}: {str(e)[:160]}"})
                continue
            doms = []
            for c in cites:
                if c["domain"] not in doms:
                    doms.append(c["domain"])
            cited = any(any(o in d for o in ours) for d in doms)
            row = {"brand": bname, "query": q, "cited": cited, "engine": used_model,
                   "n_sources": len(doms), "cited_domains": doms}
            if not cited:
                comp = []
                for c in cites[:max_resolve]:
                    comp.append({"domain": c["domain"],
                                 "url": resolve(c["uri"]) if resolve_urls else c["uri"]})
                row["competitors_cited"] = comp
                row["answer_excerpt"] = text[:400]
                gaps.append(row)
            results.append(row)
            time.sleep(4)
            print(("  ✅ 有被引用  " if cited else "  ❌ 缺口      ")
                  + f"[{bname}] {q[:52]}  ({len(doms)} 個來源)")

    if errors and not results:
        print(f"\n全部查詢都失敗({len(errors)} 筆)——不寫檔,保留上一份快照。", file=sys.stderr)
        for e in errors:
            print("   ", e["error"], file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = {"scanned_at": now, "engine": "+".join(sorted({r.get("engine", MODEL) for r in results})), "engine_note": ENGINE_NOTE,
             "brand_filter": brand, "n_queries": len(results),
             "n_cited": sum(1 for r in results if r["cited"]),
             "gaps": gaps, "results": results, "errors": errors}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with LEDGER.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({"ts": now, "engine": MODEL, **{k: v for k, v in r.items()
                     if k in ("brand", "query", "cited", "n_sources", "cited_domains", "engine")}},
                     ensure_ascii=False) + "\n")
    ok = ROOT / "logs" / "ok" / "geo_agent.ok"
    ok.parent.mkdir(parents=True, exist_ok=True)
    ok.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    print(f"\n掃描 {len(results)} 題 · 被引用 {state['n_cited']} · 缺口 {len(gaps)}"
          + (f" · 查詢失敗 {len(errors)}" if errors else ""))
    return 0


def report():
    if not STATE.exists():
        print("尚未跑過 scan。", file=sys.stderr)
        return 1
    s = json.loads(STATE.read_text(encoding="utf-8"))
    print(f"\n\033[1mGEO 引用缺口\033[0m  掃描於 {s['scanned_at']}  引擎 {s['engine']}")
    print(f"  {s['n_queries']} 題中被引用 {s['n_cited']} 題,缺口 {len(s['gaps'])} 個\n")
    for g in s["gaps"]:
        print(f"  ❌ [{g['brand']}] {g['query']}")
        print(f"     AI 引用了這些人(我們不在其中):")
        for c in g.get("competitors_cited", []):
            print(f"       · {c['domain']:<28} {c['url'][:78]}")
        print()
    print(f"  \033[2m誠實邊界:{s['engine_note']}\033[0m\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "report"], nargs="?", default="scan")
    ap.add_argument("--brand")
    ap.add_argument("--no-resolve", action="store_true")
    a = ap.parse_args()
    if a.cmd == "report":
        sys.exit(report())
    sys.exit(scan(a.brand, resolve_urls=not a.no_resolve))


if __name__ == "__main__":
    main()
