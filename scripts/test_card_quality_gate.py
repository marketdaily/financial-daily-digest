"""回歸測試:卡級品質閘+重生迴圈(2026-07-26 Delvin「我要 100% 好的」)。

鎖住:①淺 reason(<70字,即使帶價位=07-23塌陷樣態)過不了卡級關 ②沒過關不再靜默掉
deterministic 模板——重生迴圈換模型重生,拿到好卡為止 ③重生也全敗才落 deterministic。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DIGEST_PAID_CARDS", None)
import analyzer  # noqa: E402


def _card(sym, reason):
    return (f'<div class="signal-card bull"><div class="signal-card-top">'
            f'<span class="signal-ticker">{sym}</span></div>'
            f'<div class="battle-row">a</div><div class="battle-row">b</div>'
            f'<div class="battle-row">c</div>'
            f'<div class="signal-reason">{reason}</div></div>')


SHALLOW = "現價$381.58 勿追,先觀望。"  # 帶價位但 <70 字 = 07-23 塌陷樣態
DEEP = ("現價$381.58 已跌破 MA20 $385.45 形成短線空頭結構,今晚開盤若無法收復 $385.45 "
        "先觀望;價跌量縮(0.71x)顯示賣壓趨緩,若回測 $372 支撐有守可分批接回,跌破 $368 停損。")


def run():
    # ── 1) 卡級閘:淺卡擋、深卡放 ──
    assert not analyzer._card_passes_audit(_card("AAPL", SHALLOW)), "[FAIL] 淺卡竟過關"
    assert analyzer._card_passes_audit(_card("AAPL", DEEP)), "[FAIL] 深卡被誤殺"

    # ── 2) 重生迴圈:第一輪吐淺卡→被擋→重生輪吐深卡→最終用深卡 ──
    calls = {"n": 0}

    def fake_llm(prompt, prefer_strong=False, prefer_paid=False):
        calls["n"] += 1
        return _card("AAPL", SHALLOW if calls["n"] == 1 else DEEP)

    data = {"us_market": {"AAPL": {"price": 381.58, "change_pct": -1.2, "name": "Apple"}},
            "tw_market": {}, "technicals": {}}
    origs = (analyzer._llm_generate, analyzer.build_council)
    analyzer._llm_generate = fake_llm
    analyzer.build_council = lambda *a, **k: {}
    try:
        out = analyzer._render_signal_cards_batched(data, ["AAPL"], {}, prefer_strong=False)
        assert "跌破 $368 停損" in out, f"[FAIL] 重生的深卡沒進最終輸出(calls={calls['n']})"
        assert calls["n"] >= 2, f"[FAIL] 淺卡被擋後沒有重生(只呼叫 {calls['n']} 次)"
        assert "待" not in out or "數據更新" not in out, "[FAIL] 不該落 deterministic 佔位卡"

        # ── 3) 重生也全吐淺卡 → 落 deterministic(正確但樸素,不寄淺分析) ──
        calls["n"] = 0
        analyzer._llm_generate = lambda p, prefer_strong=False, prefer_paid=False: _card("AAPL", SHALLOW)
        out2 = analyzer._render_signal_cards_batched(data, ["AAPL"], {}, prefer_strong=False)
        assert SHALLOW not in out2, "[FAIL] 淺卡不准進信"
        assert "signal-card" in out2, "[FAIL] deterministic 保底卡缺席(違反 100% 覆蓋)"
    finally:
        analyzer._llm_generate, analyzer.build_council = origs

    print(f"✅ 卡級品質閘+重生迴圈回歸全過(淺卡攔截/重生補好卡[{calls['n']}次呼叫]/全敗落保底)")


if __name__ == "__main__":
    run()
