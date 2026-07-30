"""回歸測試:全免費 LLM 令(2026-07-26 Delvin 親令「全部用免費的,不要扣錢」)。

鎖住四件事:
1. 預設(無 DIGEST_PAID_CARDS)下,即使呼叫端帶 prefer_paid=True,付費 Claude 也絕不被呼叫。
2. 免費鏈順序:junk 席(openrouter/cerebras)必須排在本地 GPU 之後(絕對最後),不站品質要道。
3. Gemini 429 分流:per_day → 立即熔斷;per_minute → 退避重試不判死(07-23 晚班品質塌陷根因)。
4. Gemini key 分區(2026-07-27):key2=日報保留桶——日報 run(DIGEST_RUN=1)key2 優先、
   key1 溢流;背景呼叫端(無 DIGEST_RUN)只准 key1,絕不碰保留桶(07-23/24/27 三場
   清晨配額枯竭實鍋的根治)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DIGEST_PAID_CARDS", None)
import analyzer  # noqa: E402


def run():
    # ── 1) 付費 Claude 預設絕不被呼叫 ──
    calls = []
    orig_claude, orig_gemini = analyzer._call_claude, analyzer._call_gemini
    analyzer._call_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("付費 Claude 被呼叫了!"))
    analyzer._call_gemini = lambda p, m, system=None: "FREE_OK"
    try:
        out = analyzer._llm_generate("test", prefer_paid=True)
        assert out == "FREE_OK", f"[FAIL] 未走免費鏈: {out}"
        # 開關打開才允許付費(驗證 opt-in 機制存在)
        os.environ["DIGEST_PAID_CARDS"] = "1"
        analyzer._call_claude = lambda *a, **k: "PAID_OK"
        analyzer._call_gemini = lambda p, m, system=None: (_ for _ in ()).throw(RuntimeError("skip"))
        out2 = analyzer._llm_generate("test", prefer_paid=True)
        assert out2 == "PAID_OK", f"[FAIL] opt-in 開關失效: {out2}"
    finally:
        os.environ.pop("DIGEST_PAID_CARDS", None)
        analyzer._call_claude, analyzer._call_gemini = orig_claude, orig_gemini

    # ── 2) 鏈序:junk 席在 local 之後 ──
    order = []

    def _mk(name, ok=False):
        def f(*a, **k):
            order.append(name)
            if ok:
                return "OK"
            raise RuntimeError("fail")
        return f
    origs = {n: getattr(analyzer, n) for n in
             ("_call_gemini", "_call_groq", "_call_cf_ai", "_call_openrouter",
              "_call_cerebras", "_call_openai", "_call_ollama")}
    try:
        analyzer._call_gemini = _mk("gemini")
        analyzer._call_groq = _mk("groq")
        analyzer._call_cf_ai = _mk("cf")
        analyzer._call_openrouter = _mk("openrouter")
        analyzer._call_cerebras = _mk("cerebras", ok=True)  # 最後一席成功,終止迴圈
        analyzer._call_openai = _mk("openai")
        analyzer._call_ollama = _mk("local")
        analyzer._llm_generate("test")
        i_local, i_or = order.index("local"), order.index("openrouter")
        # 2026-07-30 鏈序意圖更新:原斷言是 local < openrouter,前提「openrouter=垃圾席」
        # (當時綁 nemotron-3-super-120b,07-26 因 no-json/抄範例被降級)。現升級為
        # ultra-550b 並實測能對真實 10 檔批次 prompt 產出完整 10 張卡(144s),而 local
        # qwen2.5:14b 對同一 prompt 600s 超時 → openrouter 必須排在 local 前,否則備援路徑
        # 先白等 10 分鐘才輪到能做事的那層,直接吃掉寄出死線。
        # 「junk 墊底」的原意由 cerebras(402 無 credits,真垃圾)守住:它仍在 local 之後。
        assert i_or < i_local, f"[FAIL] 能做完事的免費後衛(openrouter 550b)應排在 local 前: {order}"
        assert i_local < order.index("cerebras"), f"[FAIL] junk(cerebras) 未墊底: {order}"
        assert order.index("groq") < i_or, f"[FAIL] groq 應在後衛層前: {order}"
    finally:
        for n, f in origs.items():
            setattr(analyzer, n, f)

    # ── 3) 429 分流 ──
    class _Resp:
        def __init__(self, code, body="", headers=None):
            self.status_code, self.text, self.headers = code, body, headers or {}

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "GOK"}]}}]}

        def raise_for_status(self):
            pass
    seq = []
    orig_post, orig_sleep = analyzer.requests.post, analyzer.time.sleep
    analyzer.time.sleep = lambda s: seq.append(("sleep", s))
    try:
        # per_minute → 退避後重試同 key 成功,不判死
        analyzer._GEMINI_QUOTA_DEAD.clear()
        replies = [_Resp(429, "quota per_minute exceeded", {"retry-after": "2"}), _Resp(200)]
        analyzer.requests.post = lambda *a, **k: replies.pop(0)
        out = analyzer._call_gemini("p", "m1")
        assert out == "GOK" and not analyzer._GEMINI_QUOTA_DEAD, \
            f"[FAIL] per_minute 不该判死: {analyzer._GEMINI_QUOTA_DEAD}"
        # per_day → 立即熔斷(不重試)
        analyzer._GEMINI_QUOTA_DEAD.clear()
        cnt = {"n": 0}

        def _post_day(*a, **k):
            cnt["n"] += 1
            return _Resp(429, "generate_requests_per_model_per_day limit: 0")
        analyzer.requests.post = _post_day
        try:
            analyzer._call_gemini("p", "m1")
            raise AssertionError("[FAIL] per_day 應 raise")
        except RuntimeError:
            pass
        assert analyzer._GEMINI_QUOTA_DEAD, "[FAIL] per_day 未熔斷"
        assert cnt["n"] <= len([k for k in (analyzer.GEMINI_API_KEY, analyzer.GEMINI_API_KEY_2) if k]), \
            f"[FAIL] per_day 不该重試同 key: {cnt['n']} 次"
    finally:
        analyzer.requests.post, analyzer.time.sleep = orig_post, orig_sleep
        analyzer._GEMINI_QUOTA_DEAD.clear()

    # ── 4) key 分區:key2=日報保留桶 ──
    urls = []

    def _post_cap(url, *a, **k):
        urls.append(url)
        return _Resp(200)
    orig_post = analyzer.requests.post
    orig_k1, orig_k2 = analyzer.GEMINI_API_KEY, analyzer.GEMINI_API_KEY_2
    orig_run = os.environ.pop("DIGEST_RUN", None)
    try:
        analyzer.requests.post = _post_cap
        analyzer.GEMINI_API_KEY, analyzer.GEMINI_API_KEY_2 = "KEY1AAAAAA", "KEY2BBBBBB"
        analyzer._GEMINI_QUOTA_DEAD.clear()
        # 背景(無 DIGEST_RUN):只准 key1
        analyzer._call_gemini("p", "m1")
        assert "KEY1AAAAAA" in urls[-1] and "KEY2BBBBBB" not in urls[-1], \
            f"[FAIL] 背景呼叫應只用 key1: {urls[-1][-20:]}"
        # 背景遇 key1 per_day 熔斷:不得溢流到 key2(保留桶不可侵犯)
        def _post_429(url, *a, **k):
            urls.append(url)
            return _Resp(429, "generate_requests_per_model_per_day limit: 0")
        analyzer.requests.post = _post_429
        try:
            analyzer._call_gemini("p", "m1")
            raise AssertionError("[FAIL] 背景 key1 死應 raise,不可用 key2")
        except RuntimeError:
            pass
        assert not any("KEY2BBBBBB" in u for u in urls), "[FAIL] 背景呼叫碰到了保留桶 key2"
        # 日報 run:key2 優先
        os.environ["DIGEST_RUN"] = "1"
        analyzer._GEMINI_QUOTA_DEAD.clear()
        analyzer.requests.post = _post_cap
        analyzer._call_gemini("p", "m2")
        assert "KEY2BBBBBB" in urls[-1], f"[FAIL] 日報 run 應 key2 優先: {urls[-1][-20:]}"
    finally:
        analyzer.requests.post = orig_post
        analyzer.GEMINI_API_KEY, analyzer.GEMINI_API_KEY_2 = orig_k1, orig_k2
        analyzer._GEMINI_QUOTA_DEAD.clear()
        if orig_run is None:
            os.environ.pop("DIGEST_RUN", None)
        else:
            os.environ["DIGEST_RUN"] = orig_run

    print("✅ 全免費 LLM 回歸測試全過(付費絕不呼叫/junk 墊底/429 RPM-RPD 分流/key2 日報保留桶)")


if __name__ == "__main__":
    run()
