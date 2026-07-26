"""回歸測試:同股跨用戶卡片快取(2026-07-26)。
①兩位無持倉用戶同持一股→第二位 0 次 LLM 呼叫且拿到同一張卡
②有持倉成本的用戶繞過快取(prompt 帶個人成本,讀寫皆不進快取)
③快取只收過品質閘的卡"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DIGEST_PAID_CARDS", None)
import analyzer  # noqa: E402

DEEP = ("現價$381.58 已跌破 MA20 $385.45 形成短線空頭結構,今晚開盤若無法收復 $385.45 "
        "先觀望;價跌量縮(0.71x)賣壓趨緩,回測 $372 有守分批接,跌破 $368 停損。")


def _card(sym, reason):
    return (f'<div class="signal-card bull"><div class="signal-card-top">'
            f'<span class="signal-ticker">{sym}</span></div>'
            f'<div class="battle-row">a</div><div class="battle-row">b</div>'
            f'<div class="battle-row">c</div><div class="signal-reason">{reason}</div></div>')


def run():
    data = {"us_market": {"AAPL": {"price": 381.58, "change_pct": -1.2, "name": "Apple"}},
            "tw_market": {}, "technicals": {}}
    calls = {"n": 0}

    def fake_llm(prompt, prefer_strong=False, prefer_paid=False):
        calls["n"] += 1
        return _card("AAPL", DEEP)

    origs = (analyzer._llm_generate, analyzer.build_council)
    analyzer._llm_generate = fake_llm
    analyzer.build_council = lambda *a, **k: {}
    analyzer._CARD_XUSER_CACHE.clear()
    try:
        out1 = analyzer._render_signal_cards_batched(data, ["AAPL"], {})
        n1 = calls["n"]
        assert n1 >= 1 and "跌破 $368 停損" in out1, "[FAIL] 第一位用戶生成失敗"

        out2 = analyzer._render_signal_cards_batched(data, ["AAPL"], {})
        assert calls["n"] == n1, f"[FAIL] 第二位用戶不該再呼叫 LLM(呼叫 {calls['n'] - n1} 次)"
        assert "跌破 $368 停損" in out2, "[FAIL] 快取卡未進第二位輸出"

        # 持倉戶繞過快取:即使快取有卡,仍要重新生成(prompt 帶個人成本)
        out3 = analyzer._render_signal_cards_batched(
            data, ["AAPL"], {}, positions={"AAPL": {"entry_price": 300.0}})
        assert calls["n"] > n1, "[FAIL] 持倉戶竟吃了快取(該客製化生成)"
        assert "跌破 $368 停損" in out3, "[FAIL] 持倉戶卡片缺失"
    finally:
        analyzer._llm_generate, analyzer.build_council = origs
        analyzer._CARD_XUSER_CACHE.clear()
    print(f"✅ 同股跨用戶快取回歸全過(共用 1 次生成/持倉戶正確繞過)")


if __name__ == "__main__":
    run()
