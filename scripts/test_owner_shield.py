"""回歸測試:老闆護盾決策(2026-07-24 Delvin 親令「絕對不要再看到閹割版」)。

規則:老闆本人 + retry 後剩餘 HIGH 全為「軟錯」(理由偏短/籠統/TLDR 偏短,內容完整正確
只是不夠深) → 寄 AI 完整版而非閹割備援;有任一「硬錯」(版面壞/假數字/裸代號/漏持股/
時序錯/真洩漏)或非老闆 → 仍走備援。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MARKETDAILY_OWNER_EMAIL"] = "delvin.12345678@gmail.com"
import main  # noqa: E402

OWNER = "delvin.12345678@gmail.com"
OTHER = "someone.else@gmail.com"
SOFT = "signal_reason_shallow"
SOFT2 = "tldr_too_short"
HARD = "undefined_css_class"
HARD2 = "earnings_fabricated_estimates"


def run():
    A = main._owner_shield_applies

    # 老闆 + 純軟錯 → 護盾生效(寄完整版)
    assert A([SOFT], OWNER), "[FAIL] 老闆+單軟錯應護盾"
    assert A([SOFT, SOFT2], OWNER), "[FAIL] 老闆+多軟錯應護盾"
    assert A([SOFT], OWNER.upper()), "[FAIL] 大小寫應正規化"

    # 老闆 + 含任一硬錯 → 不護盾(仍走備援,因寄出=壞/錯的信)
    assert not A([HARD], OWNER), "[FAIL] 老闆+硬錯不該護盾"
    assert not A([SOFT, HARD], OWNER), "[FAIL] 軟+硬混合(有硬錯)不該護盾"
    assert not A([HARD, HARD2], OWNER), "[FAIL] 純硬錯不該護盾"

    # 非老闆 → 永不護盾(範圍鎖死只保護老闆本人)
    assert not A([SOFT], OTHER), "[FAIL] 非老闆不該護盾"
    assert not A([SOFT, SOFT2], OTHER), "[FAIL] 非老闆多軟錯也不護盾"

    # 無 HIGH → 不觸發(空清單)
    assert not A([], OWNER), "[FAIL] 無 HIGH 不該觸發護盾"

    # 分類完整性:SOFT 集合只含品質/深度類,不含任何硬錯
    hard_never_soft = {"undefined_css_class", "placeholder_prices", "fake_urls",
                       "tw_ticker_bare_code", "earnings_fabricated_estimates",
                       "holdings_uncovered", "ai_output_truncated", "prompt_instruction_leak",
                       "portfolio_lens_foreign_ticker", "tw_pre_market_tense"}
    assert not (main._SOFT_HIGH_CHECKS & hard_never_soft), \
        f"[FAIL] 硬錯誤入軟集合:{main._SOFT_HIGH_CHECKS & hard_never_soft}"

    print("✅ 老闆護盾決策回歸測試全過(10 斷言)")


if __name__ == "__main__":
    run()
