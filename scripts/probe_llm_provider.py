"""免費 LLM 候選 provider 實測台(2026-07-30 #18)。

為什麼要有這支:候選模型用小 prompt 一律給假綠燈。真正會打死模型的是日報的
**真實 10 檔批次卡 prompt**(7-8k tokens、規則區塊、要求輸出 10 張完整 HTML 卡)——
歷史上被這關刷掉的:kimi-k2(8000 output 全燒在 reasoning、答案 0 字)、
glm-4.7-flash(把答案包進 <p>)、gemma-4-26b(finish_reason:length 寫不出答案)、
nemotron-3-120b(捏造題目沒給的數字)。所以這支一律抓真實 prompt 再重放。

⚠️ 探針自己會製造假陰性(2026-07-30 第一版就中):Groq 免費層 TPM 是**每分鐘滾動窗口**,
一次真實批次呼叫就吃掉 ~7000/8000,把候選連續打會讓後面每一支都回 413/429 而看起來「不可用」。
所以同一支模型之間強制隔 SPACING 秒,且錯誤一律印完整內文——不要拿自己壓出來的 429 當結論。

用法:
    .venv/bin/python scripts/probe_llm_provider.py                # 用預設候選清單
    .venv/bin/python scripts/probe_llm_provider.py groq:gpt-oss-20b ...
    PROBE_PROMPT_FILE=/path/real_prompt.txt .venv/bin/python scripts/probe_llm_provider.py
        # 重用已抓過的真實 prompt,省掉每輪重抓市場數據

判準(全部要過才算可用):
  · 產出卡數 == 送進去的檔數(少一張 = 靜默丟資料,違反 feedback_no_silent_limits)
  · reason 中位數 >= 70 字(卡級品質閘 _card_passes_audit 的門檻)
  · 不得出現 prompt 沒給過的價格數字(抄範例/捏造)
  · 耗時(慢到吃掉寄出死線 = 不可用,晚報 45 次呼叫 ×144s 就是 07-30 遲到 1h35 的成因)
"""
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer  # noqa: E402
from data_fetcher import fetch_all  # noqa: E402

# 真實標的:取 07-30 晚報實際出現過的美股持股,不是編出來的代號
PROBE_STOCKS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "MU", "AVGO", "TSM", "INTC", "QCOM"]

SPACING = int(os.environ.get("PROBE_SPACING", 65))   # Groq TPM 是每分鐘滾動窗口
# 一次要幾張卡:批次 prompt=10,逐支重生 prompt=1。用錯數字會把好模型判成「少卡」不可用
# (2026-07-30 我自己中過:拿 10 檔批次的判準去量重生路徑)。
EXPECT = int(os.environ.get("PROBE_EXPECT_CARDS", len(PROBE_STOCKS)))

CANDIDATES = [
    ("groq:gpt-oss-20b", lambda p: analyzer._call_groq(p, model="openai/gpt-oss-20b")),
    ("groq:llama-3.3-70b", lambda p: analyzer._call_groq(p, model="llama-3.3-70b-versatile")),
    ("groq:qwen3.6-27b", lambda p: analyzer._call_groq(p, model="qwen/qwen3.6-27b")),
    ("groq:gpt-oss-safeguard-20b", lambda p: analyzer._call_groq(p, model="openai/gpt-oss-safeguard-20b")),
    ("groq:llama-3.1-8b", lambda p: analyzer._call_groq(p, model="llama-3.1-8b-instant")),
]


def capture_real_batch_prompt():
    """跑真實生卡路徑,攔下第一個送進 _llm_generate 的 prompt。"""
    cached = os.environ.get("PROBE_PROMPT_FILE")
    if cached and os.path.exists(cached):
        print(f"重用已抓過的真實 prompt:{cached}")
        with open(cached, encoding="utf-8") as f:
            return f.read(), None
    print(f"抓真實市場數據({len(PROBE_STOCKS)} 檔)…")
    data = fetch_all(extra_us_stocks=PROBE_STOCKS)
    mkt = analyzer._market_status(data["date"])
    box = {}

    def _capture(prompt, prefer_strong=False, prefer_paid=False):
        if "prompt" not in box:
            box["prompt"] = prompt
        raise RuntimeError("probe: prompt captured")

    orig = analyzer._llm_generate
    analyzer._llm_generate = _capture
    try:
        analyzer._render_signal_cards_batched(data, PROBE_STOCKS, mkt)
    except Exception:
        pass
    finally:
        analyzer._llm_generate = orig
    if "prompt" not in box:
        raise SystemExit("✗ 沒攔到 prompt——生卡路徑可能改了,先修這支探針再談候選")
    return box["prompt"], data


def _numbers(text):
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def score(name, out, prompt, elapsed):
    # ⚠️ 邊界要錨死:裸的 `class="signal-card` 會連 `class="signal-card-top"` 一起命中,
    # 每張卡算成兩張(2026-07-30 我自己中過,把 1 張卡印成「卡 2/1」差點誤判模型行為)。
    cards = re.findall(r'class="signal-card[ "]', out or "")
    reasons = [re.sub(r"<[^>]+>", "", r).strip()
               for r in re.findall(r'class="signal-reason"[^>]*>(.*?)</div>', out or "", re.S)]
    lens = sorted(len(r) for r in reasons)
    med = statistics.median(lens) if lens else 0
    # 捏造偵測:輸出裡出現、prompt 裡沒有的「像價位」的數字(3 位數以上或帶小數)
    p_nums = _numbers(prompt)
    o_nums = {n for n in _numbers(out or "") if ("." in n or len(n) >= 3)}
    invented = sorted(o_nums - p_nums)[:6]
    ok_count = len(cards) == EXPECT
    ok_depth = med >= 70
    ok_honest = not invented
    verdict = "✅ 可用" if (ok_count and ok_depth and ok_honest) else "❌ 不可用"
    print(f"{verdict} {name:<30} {elapsed:6.1f}s  卡 {len(cards):>2}/{EXPECT}  "
          f"reason中位數 {med:>3.0f} 字  長度 {lens}")
    if invented:
        print(f"      ⚠️ 疑似捏造/抄範例的數字: {invented}")
    if not ok_count and out:
        print(f"      輸出前 160 字: {out[:160]!r}")
    return {"name": name, "ok": ok_count and ok_depth and ok_honest,
            "elapsed": elapsed, "cards": len(cards), "median": med, "invented": invented}


def main():
    wanted = sys.argv[1:]
    cands = [c for c in CANDIDATES if not wanted or c[0] in wanted]
    prompt, _ = capture_real_batch_prompt()
    est = int(sum(0.3 if ord(c) < 128 else 1.0 for c in prompt))
    print(f"真實批次 prompt:{len(prompt)} 字元,估 {est} tokens\n")
    results = []
    for i, (name, fn) in enumerate(cands):
        if i:
            print(f"   …等 {SPACING}s 讓 TPM 滾動窗口清空(不等會壓出假 413/429)")
            time.sleep(SPACING)
        t0 = time.time()
        try:
            out = fn(prompt)
        except Exception as e:
            body = getattr(getattr(e, "response", None), "text", "") or ""
            print(f"❌ 不可用 {name:<30} {time.time()-t0:6.1f}s  呼叫失敗:{str(e)[:110]}")
            if body:
                print(f"      內文: {body[:260]}")
            results.append({"name": name, "ok": False, "elapsed": time.time() - t0})
            continue
        results.append(score(name, out, prompt, time.time() - t0))
    usable = [r for r in results if r.get("ok")]
    print(f"\n通過 {len(usable)}/{len(results)}:"
          + (", ".join(f"{r['name']}({r['elapsed']:.0f}s)" for r in sorted(usable, key=lambda x: x["elapsed"]))
             or "(無)"))


if __name__ == "__main__":
    main()
