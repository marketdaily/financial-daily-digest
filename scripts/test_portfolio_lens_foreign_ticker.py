"""回歸測試:portfolio_lens_foreign_ticker 誤判根治(2026-07-24 delvin 掉備援版實鍋)。

修前:token 只要「像代號」就算外來標的 → 年份(2026)/指數(23150)/價位(1085)/名詞縮寫
(AI/GDP/CPI/ETF)全被誤殺 → 老手+台股用戶每天被逼降 deterministic 備援版。
修後:必須是「真實上市證券」(台股比對 12k 代號表、美股比對 stock_names)才算外來;
真的洩漏進來的 AAPL/2330 仍在名表 → 照抓,防線不弱化。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest_audit as da  # noqa: E402

CHECK = "portfolio_lens_foreign_ticker"


def _lens_html(prose):
    return ('<html><body><div class="lens-wrap">組合透視'
            f'<div class="news-card">{prose}</div></div></body></html>')


def _has(fails, name):
    return any(f["check"] == name for f in fails)


def _audit(prose, tw, us=None):
    return da.audit_digest(_lens_html(prose), "2026-07-24",
                           us_holdings=us or [], tw_holdings=tw, market="tw")


def run():
    # 1) 誤判情境:老手台股敘述含年份/指數/價位/縮寫 → 修後絕不誤殺
    fp = ("你的組合以半導體為主,加權指數收在 23150 點,2026 下半年 AI 供應鏈是主軸,"
          "台積電(2330)佔比最高,聯發科(2454)其次,環球晶(6488)留意;若跌破 1085 元先減,"
          "留意 GDP、CPI 與 ETF 資金流。")
    hits = [f for f in _audit(fp, ["2330", "2454", "6488"]) if f["check"] == CHECK]
    assert not hits, f"[FAIL] 誤判未根治,仍抓到:{hits}"

    # 2) 真洩漏(美股):只持台股卻在「你的持股」視角列 AAPL → 仍須抓
    assert _has(_audit("你的持股中 AAPL 蘋果表現最佳,建議加碼。", ["2330", "2454"]), CHECK), \
        "[FAIL] 真洩漏 AAPL 漏抓,防線被弱化"

    # 3) 真洩漏(台股):持 2330 卻列未持有的真實代號 6488 → 仍須抓
    assert _has(_audit("你的持股 2330 台積電為主,另 6488 環球晶也納入配置。", ["2330"]), CHECK), \
        "[FAIL] 真洩漏 6488 漏抓"

    # 4) 乾淨情境:只提持股 + 一般數字(年份) → 不得誤報
    assert not _has(_audit("你的持股 2330 台積電、2454 聯發科穩健,2026 年可續抱。", ["2330", "2454"]), CHECK), \
        "[FAIL] 乾淨情境誤報"

    # 5) _is_real_ticker 單元:真標的 True、非證券數字/縮寫 False
    for t in ("2330", "6488", "0050", "AAPL", "NVDA"):
        assert da._is_real_ticker(t), f"[FAIL] {t} 應為真實證券"
    for t in ("2026", "23150", "1085", "GDP", "CPI", "ETF", "AI", ""):
        assert not da._is_real_ticker(t), f"[FAIL] {t} 不應被當證券"

    print("✅ portfolio_lens_foreign_ticker 回歸測試全過(5 組)")


if __name__ == "__main__":
    run()
